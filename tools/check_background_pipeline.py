"""Offline contract and fixture checks for the poem-background pipeline."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import sqlite3
import tempfile
import unittest
import zipfile
from collections import Counter
from pathlib import Path
from unittest.mock import patch

import requests

from background_adapters import (
    FetchResult,
    HttpCacheClient,
    collect_cnkgraph,
    collect_gushiwen,
    ensure_cbdb_database,
    gushiwen_poem_id,
    parse_chgis_payload,
    parse_gushiwen_sections,
    query_cbdb_identities,
)
from background_contract import (
    CANDIDATES_JSONL,
    COLLECTION_STATUS_JSONL,
    CORE_POETS,
    LEGACY_CONTEXTS_CSV,
    MANUAL_FIELDS,
    MAX_EVIDENCE_CHARS,
    POET_STATUS_JSONL,
    RICH_BACKGROUNDS_JSONL,
    confidence_for,
    load_poems,
    make_candidate,
    normalize_title,
    read_jsonl,
    select_poems,
    source_match_score,
    upsert_candidates,
    validate_candidate,
)
from background_pipeline import (
    grouped_approved_records,
    legacy_grade,
    legacy_rows_from_rich,
    manual_candidates_from_csv,
    mark_source_conflicts,
    migrate_legacy_contexts,
    migrate_linqingzhao_cache_contexts,
    validate_model_claims,
)


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "background"


def fixture_json(name: str) -> object:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def fixture_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def sample_poem(**updates: object) -> dict[str, object]:
    poem: dict[str, object] = {
        "poet": "李白",
        "author": "李白",
        "title": "望庐山瀑布",
        "dynasty": "唐",
        "body": "日照香炉生紫烟，遥看瀑布挂前川。\n飞流直下三千尺，疑是银河落九天。",
        "source_poem_id": "abc123",
        "source_url": "https://www.gushiwen.cn/shiwenv_abc123.aspx",
    }
    poem.update(updates)
    return poem


class FixtureAdapterClient:
    def post_json(self, _url: str, _payload: object) -> tuple[FetchResult, object]:
        return (
            FetchResult(url="fixture://cnkgraph/find", status="ok", cache_key="find-cache"),
            fixture_json("cnkgraph_find.json"),
        )

    def get_json(self, url: str, *, respect_robots: bool = True) -> tuple[FetchResult, object]:
        del respect_robots
        fixture = "cnkgraph_region.json" if "/map/region/" in url else "cnkgraph_detail.json"
        return FetchResult(url=url, status="ok", cache_key=fixture), fixture_json(fixture)

    def request(self, _method: str, url: str, *, respect_robots: bool = True) -> FetchResult:
        del respect_robots
        return FetchResult(
            url=url,
            status="ok",
            status_code=200,
            text=fixture_text("gushiwen_page.html"),
            content=fixture_text("gushiwen_page.html").encode("utf-8"),
            content_type="text/html; charset=utf-8",
            cache_key="gushiwen-cache",
        )


class StubResponse:
    def __init__(
        self,
        status_code: int,
        text: str = "ok",
        url: str = "https://example.test/page",
        encoding: str | None = None,
        apparent_encoding: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self.content = text.encode("utf-8")
        self.url = url
        self.encoding = encoding
        self.apparent_encoding = apparent_encoding
        self.headers = headers or {"Content-Type": "text/html; charset=utf-8"}


class SequenceSession:
    def __init__(self, responses: list[object]) -> None:
        self.responses = list(responses)
        self.calls = 0
        self.headers: dict[str, str] = {}

    def request(self, *_args: object, **_kwargs: object) -> StubResponse:
        self.calls += 1
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        assert isinstance(item, StubResponse)
        return item


class MatchingTests(unittest.TestCase):
    def test_title_and_source_matching_rules(self) -> None:
        poem = sample_poem()
        self.assertEqual(normalize_title("《望庐山瀑布·其一》"), normalize_title("望庐山瀑布一"))
        self.assertEqual(
            source_match_score(
                poem,
                source_poem_id="abc123",
                source_poet="李白",
                source_title="无关标题",
            ),
            1.0,
        )
        self.assertEqual(
            source_match_score(
                poem,
                source_poem_id="abc123",
                source_poet="杜甫",
                source_title="望庐山瀑布",
            ),
            0.0,
        )
        self.assertEqual(
            source_match_score(poem, source_poet="李白", source_title="《望庐山瀑布》"),
            0.95,
        )
        self.assertEqual(
            source_match_score(
                poem,
                source_poet="李白",
                source_title="望庐山瀑布二首其一",
                source_first_line="日照香炉生紫烟，遥看瀑布挂前川。",
            ),
            0.90,
        )

    def test_confidence_formula(self) -> None:
        self.assertEqual(confidence_for("A", 1.0), 0.95)
        self.assertEqual(confidence_for("B", 0.95, agreeing_sources=2), 0.858)
        self.assertEqual(confidence_for("C", 0.95, conflict=True), 0.417)
        self.assertEqual(confidence_for("A", 1.0, agreeing_sources=2), 0.99)

    def test_candidate_ids_and_upsert_are_idempotent(self) -> None:
        poem = sample_poem()
        kwargs = {
            "evidence_excerpt": "系年：725年",
            "source_key": "fixture:one",
            "source_name": "固定样例",
            "source_locator": "第1页",
            "source_grade": "B",
        }
        first = make_candidate(poem, "composition_date", {"year_start": 725, "year_end": 725}, **kwargs)
        second = make_candidate(poem, "composition_date", {"year_start": 725, "year_end": 725}, **kwargs)
        self.assertEqual(first["candidate_id"], second["candidate_id"])
        first["value"] = {"year_start": 724, "year_end": 725, "reviewer_edit": True}
        merged = upsert_candidates([first], [second, second])
        self.assertEqual(len(merged), 1)
        self.assertTrue(merged[0]["value"]["reviewer_edit"])


class AdapterFixtureTests(unittest.TestCase):
    def test_gushiwen_parser_and_collector(self) -> None:
        parsed = parse_gushiwen_sections(fixture_text("gushiwen_page.html"))
        self.assertEqual(parsed["title"], "望庐山瀑布")
        self.assertEqual(parsed["author"], "李白")
        self.assertEqual({row["claim_type"] for row in parsed["sections"]}, {
            "translation", "annotation", "historical_context", "appreciation"
        })
        self.assertEqual(gushiwen_poem_id("https://www.gushiwen.cn/shiwenv_abc123.aspx"), "abc123")
        rows, status = collect_gushiwen(sample_poem(), FixtureAdapterClient())
        self.assertEqual(status["status"], "collected")
        self.assertEqual(len(rows), 4)
        self.assertTrue(all(row["match_score"] == 1.0 for row in rows))
        self.assertTrue(all(len(row["evidence_excerpt"]) <= MAX_EVIDENCE_CHARS for row in rows))

    def test_cnkgraph_collector(self) -> None:
        poem = sample_poem(source_poem_id="", source_url="")
        rows, status = collect_cnkgraph(poem, FixtureAdapterClient())
        self.assertEqual(status["status"], "collected")
        self.assertEqual({row["claim_type"] for row in rows}, {"composition_date", "composition_place"})
        date = next(row for row in rows if row["claim_type"] == "composition_date")
        place = next(row for row in rows if row["claim_type"] == "composition_place")
        self.assertEqual(date["value"]["year_start"], 725)
        self.assertEqual(place["value"]["modern_place"], "九江市")
        self.assertEqual(date["source_grade"], "B")

    def test_cnkgraph_ambiguous_tie_is_not_first_match(self) -> None:
        from background_adapters import find_cnkgraph_writing

        poem = sample_poem(source_poem_id="", source_url="")
        tied = {"Writings": [
            {"Author": "李白", "Title": "望庐山瀑布"},
            {"Author": "李白", "Title": "望庐山瀑布"},
        ]}
        best, score = find_cnkgraph_writing(poem, tied)
        self.assertIsNone(best)
        self.assertGreater(score, 0.0)

        distinct = {"Writings": [
            {"Author": "李白", "Title": "望庐山瀑布"},
            {"Author": "李白", "Title": "将进酒"},
        ]}
        best2, score2 = find_cnkgraph_writing(poem, distinct)
        self.assertIsNotNone(best2)
        self.assertEqual(best2["Title"], "望庐山瀑布")
        self.assertEqual(score2, 0.95)

    def test_cnkgraph_year_range_keeps_bounds(self) -> None:
        from background_adapters import parse_year_range

        self.assertEqual(parse_year_range("725-727年"), (725, 727, "approximate"))
        self.assertEqual(parse_year_range("约725年"), (725, 725, "approximate"))
        self.assertEqual(parse_year_range("725年"), (725, 725, "year"))
        self.assertEqual(parse_year_range("725年（开元13年）"), (725, 725, "year"))
        self.assertIsNone(parse_year_range("天宝十四载"))

    def test_chgis_parser_prefers_query_year(self) -> None:
        row = parse_chgis_payload(fixture_json("chgis.json"), query_year=725)
        assert row is not None
        self.assertEqual(row["chgis_id"], "hvd_123")
        self.assertAlmostEqual(row["lon"], 115.989402)
        self.assertAlmostEqual(row["lat"], 29.560618)

    def test_cbdb_sqlite_identity_lookup(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "cbdb.sqlite3"
            connection = sqlite3.connect(path)
            try:
                connection.executescript(fixture_text("cbdb_fixture.sql"))
            finally:
                connection.close()
            rows = query_cbdb_identities(path, ["李白", "同名者", "不存在"], {"sqlite_filename": "fixture"})
        by_poet = {row["poet"]: row for row in rows}
        self.assertEqual(by_poet["李白"]["status"], "matched")
        self.assertEqual(by_poet["同名者"]["status"], "ambiguous")
        self.assertEqual(by_poet["不存在"]["status"], "not_found")
        self.assertEqual(by_poet["李白"]["matches"][0]["c_personid"], 1001)


class HttpPolicyTests(unittest.TestCase):
    def make_client(self, folder: str, responses: list[object], retries: int = 3) -> tuple[HttpCacheClient, SequenceSession]:
        client = HttpCacheClient(
            cache_dir=Path(folder),
            retries=retries,
            min_delay=0,
            max_delay=0,
            timeout=0.01,
        )
        session = SequenceSession(responses)
        client.session = session  # type: ignore[assignment]
        return client, session

    @patch("background_adapters.time.sleep", return_value=None)
    def test_403_404_429_and_timeout(self, _sleep: object) -> None:
        with tempfile.TemporaryDirectory() as folder:
            for status_code in (403, 404):
                client, session = self.make_client(str(Path(folder) / str(status_code)), [StubResponse(status_code)])
                result = client.request("GET", f"https://example.test/{status_code}", respect_robots=False)
                self.assertEqual(result.status, "fetch_failed")
                self.assertEqual(result.status_code, status_code)
                self.assertEqual(session.calls, 1)

            client, session = self.make_client(
                str(Path(folder) / "429"),
                [StubResponse(429), StubResponse(200, '{"ok":true}')],
            )
            result = client.request("GET", "https://example.test/retry", respect_robots=False)
            self.assertEqual(result.status, "ok")
            self.assertEqual(session.calls, 2)

            client, session = self.make_client(
                str(Path(folder) / "timeout"),
                [requests.Timeout("timeout"), requests.Timeout("timeout"), requests.Timeout("timeout")],
            )
            result = client.request("GET", "https://example.test/timeout", respect_robots=False)
            self.assertEqual(result.status, "fetch_failed")
            self.assertEqual(session.calls, 3)

    def test_login_captcha_and_robots_are_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            client, _ = self.make_client(folder, [StubResponse(200, "请输入验证码")])
            result = client.request("GET", "https://example.test/login", respect_robots=False)
            self.assertEqual(result.status, "blocked_by_policy")
            self.assertEqual(result.content, b"")

            robots_client, session = self.make_client(str(Path(folder) / "robots"), [])
            with patch.object(robots_client, "_robots_allowed", return_value=False):
                robots = robots_client.request("GET", "https://example.test/private")
            self.assertEqual(robots.status, "blocked_by_policy")
            self.assertEqual(session.calls, 0)
            body_path, meta_path = robots_client._paths(robots.cache_key)
            self.assertTrue(body_path.exists())
            self.assertTrue(meta_path.exists())

    @patch("background_adapters.time.sleep", return_value=None)
    def test_blocked_policy_cache_expires_online_but_is_visible_offline(self, _sleep: object) -> None:
        url = "https://example.test/temporary-login-wall"
        with tempfile.TemporaryDirectory() as folder:
            self._write_entry(folder, url, status="blocked_by_policy", body=b"")
            online, session = self.make_client(folder, [StubResponse(200, "fresh")])
            result = online.request("GET", url, respect_robots=False)
            self.assertEqual(result.status, "ok")
            self.assertEqual(result.text, "fresh")
            self.assertFalse(result.from_cache)
            self.assertEqual(session.calls, 1)

        with tempfile.TemporaryDirectory() as folder:
            self._write_entry(folder, url, status="blocked_by_policy", body=b"")
            offline = HttpCacheClient(
                cache_dir=Path(folder), min_delay=0, max_delay=0, timeout=0.01, offline=True
            )
            offline.session = SequenceSession([])
            result = offline.request("GET", url, respect_robots=False)
            self.assertEqual(result.status, "blocked_by_policy")
            self.assertTrue(result.from_cache)

    def _write_entry(
        self, folder: str, url: str, *, status: str, body: bytes, encoding: str = "utf-8"
    ) -> None:
        client = HttpCacheClient(cache_dir=Path(folder), min_delay=0, max_delay=0, timeout=0.01)
        key = client._cache_key("GET", url)
        body_path, meta_path = client._paths(key)
        body_path.parent.mkdir(parents=True, exist_ok=True)
        body_path.write_bytes(body)
        meta_path.write_text(
            json.dumps(
                {
                    "url": url,
                    "status": status,
                    "status_code": 200,
                    "content_type": "application/json",
                    "encoding": encoding,
                    "note": "",
                    "fetched_at": "2026-01-01T00:00:00+00:00",
                    "sha256": hashlib.sha256(body).hexdigest(),
                    "adapter_version": "background-adapters-v1",
                }
            ),
            encoding="utf-8",
        )

    @patch("background_adapters.time.sleep", return_value=None)
    def test_negative_cache_is_retried_online_and_missed_offline(self, _sleep: object) -> None:
        with tempfile.TemporaryDirectory() as folder:
            self._write_entry(folder, "https://example.test/neg", status="fetch_failed", body=b"stale")
            client, session = self.make_client(folder, [StubResponse(200, '{"ok":true}')])
            result = client.request("GET", "https://example.test/neg", respect_robots=False)
            self.assertEqual(result.status, "ok")
            self.assertFalse(result.from_cache)
            self.assertEqual(session.calls, 1)

        with tempfile.TemporaryDirectory() as folder:
            self._write_entry(folder, "https://example.test/neg", status="fetch_failed", body=b"stale")
            offline = HttpCacheClient(
                cache_dir=Path(folder), min_delay=0, max_delay=0, timeout=0.01, offline=True
            )
            offline.session = SequenceSession([])
            missed = offline.request("GET", "https://example.test/neg")
            self.assertEqual(missed.status, "offline_cache_miss")

    @patch("background_adapters.time.sleep", return_value=None)
    def test_retries_zero_still_performs_one_network_attempt(self, _sleep: object) -> None:
        with tempfile.TemporaryDirectory() as folder:
            client, session = self.make_client(folder, [StubResponse(200, "once")], retries=0)
            result = client.request("GET", "https://example.test/once", respect_robots=False)
            self.assertEqual(result.status, "ok")
            self.assertEqual(result.text, "once")
            self.assertEqual(session.calls, 1)

    @patch("background_adapters.time.sleep", return_value=None)
    def test_corrupt_cache_checksum_is_a_miss(self, _sleep: object) -> None:
        url = "https://example.test/corrupt"
        with tempfile.TemporaryDirectory() as folder:
            self._write_entry(folder, url, status="ok", body=b"original")
            probe = HttpCacheClient(cache_dir=Path(folder), min_delay=0, max_delay=0, timeout=0.01)
            body_path, _meta_path = probe._paths(probe._cache_key("GET", url))
            body_path.write_bytes(b"tampered")

            online, session = self.make_client(folder, [StubResponse(200, "fresh")])
            result = online.request("GET", url, respect_robots=False)
            self.assertEqual(result.status, "ok")
            self.assertEqual(result.text, "fresh")
            self.assertFalse(result.from_cache)
            self.assertEqual(session.calls, 1)

        with tempfile.TemporaryDirectory() as folder:
            self._write_entry(folder, url, status="ok", body=b"original")
            probe = HttpCacheClient(cache_dir=Path(folder), min_delay=0, max_delay=0, timeout=0.01)
            body_path, _meta_path = probe._paths(probe._cache_key("GET", url))
            body_path.write_bytes(b"tampered")
            offline = HttpCacheClient(
                cache_dir=Path(folder), min_delay=0, max_delay=0, timeout=0.01, offline=True
            )
            result = offline.request("GET", url, respect_robots=False)
            self.assertEqual(result.status, "offline_cache_miss")

    @patch("background_adapters.time.sleep", return_value=None)
    def test_5xx_retries_with_backoff_and_succeeds(self, sleep: object) -> None:
        with tempfile.TemporaryDirectory() as folder:
            client, session = self.make_client(
                folder,
                [StubResponse(500), StubResponse(503), StubResponse(200, "recovered")],
            )
            result = client.request("GET", "https://example.test/flaky", respect_robots=False)
            self.assertEqual(result.status, "ok")
            self.assertEqual(result.text, "recovered")
            self.assertEqual(session.calls, 3)

        sleep.reset_mock()
        with tempfile.TemporaryDirectory() as folder:
            client, session = self.make_client(
                folder,
                [StubResponse(502, headers={"Retry-After": "5"}), StubResponse(200, "back")],
            )
            result = client.request("GET", "https://example.test/ra", respect_robots=False)
            self.assertEqual(result.status, "ok")
            self.assertEqual(session.calls, 2)
            self.assertEqual([call.args[0] for call in sleep.call_args_list], [5.0])

    def test_encoding_fallback_recovers_chinese_without_charset(self) -> None:
        chinese = "日照香炉生紫烟，遥看瀑布挂前川。"
        with tempfile.TemporaryDirectory() as folder:
            client, session = self.make_client(
                folder,
                [StubResponse(200, chinese, encoding="ISO-8859-1", apparent_encoding="utf-8")],
            )
            result = client.request("GET", "https://example.test/souyun", respect_robots=False)
            self.assertEqual(result.status, "ok")
            self.assertEqual(result.text, chinese)
            self.assertEqual(session.calls, 1)

        with tempfile.TemporaryDirectory() as folder:
            client, _ = self.make_client(
                folder,
                [StubResponse(200, chinese, encoding=None, apparent_encoding="utf-8")],
            )
            result = client.request("GET", "https://example.test/nocharset", respect_robots=False)
            self.assertEqual(result.text, chinese)

    @patch("background_adapters.time.sleep", return_value=None)
    def test_bad_json_online_bypasses_bad_cache_and_offline_stays_offline(self, _sleep: object) -> None:
        with tempfile.TemporaryDirectory() as folder:
            self._write_entry(folder, "https://example.test/badjson", status="ok", body=b"{not json")
            client, session = self.make_client(folder, [StubResponse(200, '{"good":true}')])
            result, payload = client.get_json("https://example.test/badjson", respect_robots=False)
            self.assertEqual(result.status, "ok")
            self.assertEqual(payload, {"good": True})
            self.assertFalse(result.from_cache)
            self.assertEqual(session.calls, 1)

        with tempfile.TemporaryDirectory() as folder:
            self._write_entry(folder, "https://example.test/badjson", status="ok", body=b"{not json")
            offline = HttpCacheClient(
                cache_dir=Path(folder), min_delay=0, max_delay=0, timeout=0.01, offline=True
            )
            offline.session = SequenceSession([])
            result, payload = offline.get_json("https://example.test/badjson", respect_robots=False)
            self.assertEqual(result.status, "parse_failed")
            self.assertIsNone(payload)

    def test_cbdb_manifest_hash_is_checked_against_extracted_sqlite(self) -> None:
        database_bytes = b"SQLite format 3\x00fixture-database-content"
        archive_buffer = io.BytesIO()
        with zipfile.ZipFile(archive_buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("cbdb_fixture.sqlite3", database_bytes)
        archive_bytes = archive_buffer.getvalue()
        expected = hashlib.sha256(database_bytes).hexdigest()
        self.assertNotEqual(hashlib.sha256(archive_bytes).hexdigest(), expected)

        class DownloadResponse:
            status_code = 200

            def __init__(self) -> None:
                self.closed = False

            def __enter__(self):
                return self

            def __exit__(self, *_args: object) -> None:
                self.closed = True

            def iter_content(self, chunk_size: int):
                for offset in range(0, len(archive_bytes), chunk_size):
                    yield archive_bytes[offset : offset + chunk_size]

        class DownloadSession:
            def __init__(self, response: DownloadResponse) -> None:
                self.response = response
                self.headers: dict[str, str] = {}

            def get(self, *_args: object, **_kwargs: object) -> DownloadResponse:
                return self.response

        with tempfile.TemporaryDirectory() as folder:
            client = HttpCacheClient(cache_dir=Path(folder), min_delay=0, max_delay=0)
            response = DownloadResponse()
            client.session = DownloadSession(response)  # type: ignore[assignment]
            manifest = {
                "huggingface_url": "https://example.test/cbdb.zip",
                "sha256": expected,
                "sqlite_filename": "fixture.sqlite3",
            }
            client.get_json = lambda *_args, **_kwargs: (  # type: ignore[method-assign]
                FetchResult(url="manifest", status="ok", status_code=200, cache_key="manifest"),
                manifest,
            )
            db_path, stored = ensure_cbdb_database(client)
            self.assertIsNotNone(db_path)
            assert db_path is not None
            self.assertEqual(db_path.read_bytes(), database_bytes)
            self.assertEqual(stored["verified_sha256"], expected)
            self.assertTrue(response.closed)
            self.assertEqual(list(Path(folder).joinpath("cbdb").glob("*.part")), [])

    def test_cbdb_cached_database_is_reused_only_when_checksum_matches(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            cache_dir = Path(folder)
            database = b"SQLite format 3\x00cached-fixture"
            expected = hashlib.sha256(database).hexdigest()
            db_path = cache_dir / "cbdb" / "latest.sqlite3"
            manifest_path = cache_dir / "cbdb" / "latest.json"
            db_path.parent.mkdir(parents=True, exist_ok=True)
            db_path.write_bytes(database)
            manifest_path.write_text(
                json.dumps({"sha256": expected, "sqlite_filename": "fixture.sqlite3"}),
                encoding="utf-8",
            )
            offline = HttpCacheClient(cache_dir=cache_dir, offline=True, min_delay=0, max_delay=0)
            reused, manifest = ensure_cbdb_database(offline)
            self.assertEqual(reused, db_path)
            self.assertEqual(manifest["verified_sha256"], expected)

            db_path.write_bytes(database + b"tampered")
            rejected, status = ensure_cbdb_database(offline)
            self.assertIsNone(rejected)
            self.assertEqual(status["status"], "checksum_failed")


class ExtractionAndReviewTests(unittest.TestCase):
    def source_candidate(self, **updates: object) -> dict[str, object]:
        candidate = make_candidate(
            sample_poem(),
            "composition_date",
            {"year_start": 725, "year_end": 725},
            evidence_excerpt="系年：725年",
            source_key="fixture:chronology",
            source_name="固定年谱",
            source_locator="第10页",
            source_grade="B",
        )
        candidate.update(updates)
        return candidate

    def test_model_claims_require_exact_input_evidence(self) -> None:
        poem = sample_poem()
        source = self.source_candidate()
        payload = {
            "claims": [
                {
                    "claim_type": "composition_date",
                    "value": {"year_start": 725, "year_end": 725},
                    "evidence_excerpt": "系年：725年",
                },
                {
                    "claim_type": "historical_context",
                    "value": {"text": "无来源事实"},
                    "evidence_excerpt": "模型自行补充",
                },
                {
                    "claim_type": "translation",
                    "value": {"line_no": 1, "original": "日照香炉生紫烟", "translation": "阳光照耀香炉峰，升起紫色烟霞。"},
                    "evidence_excerpt": "日照香炉生紫烟",
                },
                {
                    "claim_type": "translation",
                    "value": {"line_no": 2, "translation": "不应采用第三方译文证据"},
                    "evidence_excerpt": "系年：725年",
                },
            ]
        }
        rows = validate_model_claims(poem, [source], payload, "fixture-model")
        self.assertEqual([row["claim_type"] for row in rows], ["composition_date", "translation"])
        translation = rows[1]
        self.assertEqual(translation["source_name"], "项目模型辅助整理")
        self.assertEqual(translation["source_grade"], "D")
        self.assertEqual(translation["status"], "needs_review")

    def test_conflicting_sources_become_disputed(self) -> None:
        first = self.source_candidate()
        second = make_candidate(
            sample_poem(),
            "composition_date",
            {"year_start": 730, "year_end": 730},
            evidence_excerpt="另一年谱系于730年",
            source_key="fixture:other",
            source_name="另一固定年谱",
            source_locator="第20页",
            source_grade="B",
        )
        rows = [first, second]
        self.assertEqual(mark_source_conflicts(rows), 2)
        self.assertTrue(all(row["status"] == "disputed" for row in rows))
        self.assertTrue(all(float(row["confidence"]) < confidence_for("B", 0.95) for row in rows))

        compatible = [
            self.source_candidate(),
            make_candidate(
                sample_poem(),
                "composition_date",
                {"year_start": 724, "year_end": 725},
                evidence_excerpt="系于724至725年",
                source_key="fixture:range",
                source_name="区间年谱",
                source_locator="第2页",
                source_grade="B",
            ),
        ]
        self.assertEqual(mark_source_conflicts(compatible), 0)
        self.assertTrue(all(row["status"] == "needs_review" for row in compatible))

    def test_manual_authenticated_source_requires_full_citation(self) -> None:
        poem = select_poems("core", 1)[0]
        row = {field: "" for field in MANUAL_FIELDS}
        row.update(
            {
                "poet": str(poem["poet"]),
                "title": str(poem["title"]),
                "dynasty": str(poem["dynasty"]),
                "claim_type": "composition_date",
                "value_json": '{"year_start":725,"year_end":725}',
                "evidence_excerpt": "固定页码中的必要短引。",
                "source_title": "测试年谱",
                "source_author": "测试编者",
                "publisher": "测试出版社",
                "publication_year": "2020",
                "edition": "第1版",
                "page": "10",
                "source_grade": "B",
                "access_level": "authenticated_manual",
                "license_note": "仅保存短引",
            }
        )
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=MANUAL_FIELDS)
        writer.writeheader()
        writer.writerow(row)
        candidates = manual_candidates_from_csv(buffer.getvalue())
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["status"], "needs_review")
        self.assertEqual(candidates[0]["source_locator"], "第10页")

        row["page"] = ""
        invalid = io.StringIO()
        writer = csv.DictWriter(invalid, fieldnames=MANUAL_FIELDS)
        writer.writeheader()
        writer.writerow(row)
        with self.assertRaisesRegex(ValueError, "required manual fields"):
            manual_candidates_from_csv(invalid.getvalue())

    def test_third_party_text_never_becomes_public_appreciation(self) -> None:
        poem = select_poems("core", 1)[0]
        candidate = make_candidate(
            poem,
            "appreciation",
            {"source_excerpt": "第三方赏析原文", "heading": "赏析"},
            evidence_excerpt="第三方赏析原文",
            source_key="fixture:web",
            source_name="公共网页",
            source_url="https://example.test/poem",
            source_locator="赏析",
            source_grade="C",
            status="approved",
        )
        candidate.update(reviewer="fixture-reviewer", reviewed_at="2026-01-01T00:00:00+00:00")
        records = grouped_approved_records([candidate])
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["appreciation_points"], [])
        self.assertEqual(records[0]["sources"][0]["excerpt"], "第三方赏析原文")


class ProjectDataTests(unittest.TestCase):
    def test_core_scope_and_all_poets(self) -> None:
        # 语料扩容后（李白 55 首用于精神地形图专题）核心样本总量随数据实测，
        # 只保留“每位核心诗人至少 20 首”的下限与自洽性断言。
        core = select_poems("core")
        counts = Counter(str(row["poet"]) for row in core)
        self.assertEqual(set(counts), set(CORE_POETS))
        self.assertTrue(all(counts[poet] >= 20 for poet in CORE_POETS))
        self.assertGreaterEqual(len(core), len(CORE_POETS) * 20)
        self.assertEqual(len(core), sum(counts.values()))
        all_poems = load_poems()
        poets = {str(row["poet"]) for row in all_poems}
        self.assertGreaterEqual(len(poets), 80)
        self.assertEqual(len(select_poems("all", 1)), len(poets))

    def test_all_legacy_contexts_are_migrated_without_loss(self) -> None:
        with LEGACY_CONTEXTS_CSV.open("r", encoding="utf-8-sig", newline="") as handle:
            source_rows = list(csv.DictReader(handle))
        candidates = migrate_legacy_contexts([])
        identities = {
            (row["poem_key"]["poet"], row["poem_key"]["title"])
            for row in candidates
        }
        expected_identities = {
            (str(row.get("poet") or ""), str(row.get("title") or ""))
            for row in source_rows
        }
        self.assertEqual(len(candidates), len(source_rows) * 2)
        self.assertEqual(identities, expected_identities)
        self.assertEqual(len({row["candidate_id"] for row in candidates}), len(candidates))
        self.assertTrue(all(not validate_candidate(row) for row in candidates))
        self.assertTrue(
            all(
                row["source_grade"] != "A"
                for row in candidates
                if "API" in f"{row.get('source_name', '')} {row.get('evidence_excerpt', '')}"
                and not any(
                    token in f"{row.get('source_name', '')} {row.get('evidence_excerpt', '')}"
                    for token in ("作品序", "词序", "诗序", "题跋", "正史")
                )
            )
        )

        records = grouped_approved_records(candidates)
        legacy_rows = legacy_rows_from_rich(records)
        publishable_legacy = {
            (row["poem_key"]["poet"], row["poem_key"]["title"])
            for row in candidates
            if row["source_grade"] in {"A", "B"}
        }
        self.assertEqual(len(records), len(publishable_legacy))
        self.assertEqual(len(legacy_rows), len(publishable_legacy))

    def test_candidate_store_is_preserved_when_legacy_csv_is_reimported(self) -> None:
        existing = read_jsonl(CANDIDATES_JSONL)
        migrated = migrate_legacy_contexts(existing)
        self.assertTrue(
            {row["candidate_id"] for row in existing}
            <= {row["candidate_id"] for row in migrated}
        )
        self.assertEqual(len(migrated), len(existing))

    def test_linqingzhao_reviewed_cache_contexts_migrate_as_b_grade_claims(self) -> None:
        candidates = migrate_linqingzhao_cache_contexts([])
        self.assertEqual(len(candidates), 10)
        self.assertEqual(
            len({row["poem_key"]["body_hash"] for row in candidates}),
            5,
        )
        self.assertEqual(
            {row["claim_type"] for row in candidates},
            {"composition_date", "composition_place"},
        )
        self.assertTrue(all(row["source_grade"] == "B" for row in candidates))
        self.assertTrue(all(row["status"] == "approved" for row in candidates))
        self.assertTrue(
            all(row["reviewer"] == "existing_cache_migration" for row in candidates)
        )
        self.assertTrue(all(not validate_candidate(row) for row in candidates))

    def test_existing_pipeline_files_obey_contract_when_present(self) -> None:
        if CANDIDATES_JSONL.exists():
            rows = read_jsonl(CANDIDATES_JSONL)
            self.assertEqual(len(rows), len({row.get("candidate_id") for row in rows}))
            for row in rows:
                self.assertEqual(validate_candidate(row), [], row.get("candidate_id"))
                self.assertLessEqual(len(str(row.get("evidence_excerpt") or "")), MAX_EVIDENCE_CHARS)
        if RICH_BACKGROUNDS_JSONL.exists():
            for record in read_jsonl(RICH_BACKGROUNDS_JSONL):
                self.assertEqual(record.get("review_status"), "approved")
                for source in record.get("sources") or []:
                    self.assertLessEqual(len(str(source.get("excerpt") or "")), MAX_EVIDENCE_CHARS)


def readiness_summary() -> None:
    all_poets = {str(row.get("poet") or "") for row in load_poems()}
    core_hashes = {str(row.get("body_hash") or "") for row in select_poems("core")}
    statuses = read_jsonl(COLLECTION_STATUS_JSONL)
    attempted = {
        str((row.get("poem_key") or {}).get("body_hash") or "")
        for row in statuses
        if isinstance(row.get("poem_key"), dict)
        and str((row.get("poem_key") or {}).get("body_hash") or "") in core_hashes
    }
    identity_rows = read_jsonl(POET_STATUS_JSONL)
    identity_covered = {str(row.get("poet") or "") for row in identity_rows if row.get("poet")}
    identity_attempted = {
        str(row.get("poet") or "")
        for row in identity_rows
        if row.get("status") not in {"", "pending_collection"}
    }
    rich = read_jsonl(RICH_BACKGROUNDS_JSONL)
    complete = [row for row in rich if row.get("publication_ready")]
    candidates = read_jsonl(CANDIDATES_JSONL)
    approved_poems = {
        str((row.get("poem_key") or {}).get("body_hash") or "")
        for row in candidates
        if row.get("status") == "approved" and isinstance(row.get("poem_key"), dict)
    }
    print("\n[readiness]")
    print(f"  core collection attempts: {len(attempted)}/{len(core_hashes)} poems")
    print(
        "  poet identity status coverage: "
        f"{len(identity_covered)}/{len(all_poets)}; attempted: {len(identity_attempted)}/{len(all_poets)}"
    )
    print(f"  approved poem claims: {len(approved_poems)} poems")
    print(f"  publication-ready rich backgrounds: {len(complete)}/60 minimum")
    if len(complete) < 60:
        print("  pending: external collection, project translation/appreciation, and human review are still required")


def main() -> int:
    suite = unittest.defaultTestLoader.loadTestsFromModule(__import__(__name__))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    readiness_summary()
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
