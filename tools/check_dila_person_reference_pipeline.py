"""Offline fixture tests for :mod:`dila_person_reference_pipeline`.

No test in this file performs a real network request; DILA is never contacted.
"""
from __future__ import annotations

import email.message
import io
import json
import socket
import ssl
import tempfile
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from unittest import mock

from dila_person_reference_pipeline import (
    CACHE_DIR,
    CREDIBLE_NAME_METHODS,
    DILA_CC_LICENSE,
    DILA_CC_LICENSE_URL,
    DILA_HOST,
    DILA_LICENSE_NOTE,
    DILA_OPEN_CONTENT_URL,
    DILA_SOURCE_NAME,
    MATCHES_JSONL,
    ROUTE_EVENT_FIELDS,
    CacheStore,
    DilaFetcher,
    DilaRecord,
    LifeSpan,
    LOCAL_YEAR_TOLERANCE,
    PoetSpec,
    _DilaHostRedirectHandler,
    active_status,
    attempt_record,
    build_coverage,
    build_match_row,
    canonical_json,
    collect,
    default_opener,
    dynasty_match_kind,
    is_retryable_status,
    load_roster,
    local_life_years,
    merge_matches,
    name_match_method,
    open_dila_with_ssl_fallback,
    parse_jsonp,
    parse_names_field,
    person_query_url,
    person_records_from_payload,
    resolve_run_plan,
    sanitize_note,
    score_candidate,
    score_date,
    select_for_poet,
    stable_id,
    traditional_name,
    write_jsonl,
)


FIXED_TIME = "2026-08-09T00:00:00+00:00"


def _cb(payload: object) -> bytes:
    return f"ddbcAuthPerson({json.dumps(payload, ensure_ascii=False)});".encode("utf-8")


def _record(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "authorityID": "A000001",
        "name": "白居易",
        "class": "",
        "gender": "1",
        "monk": "n",
        "bornDateBegin": "+0772-01-01",
        "bornDateEnd": "+0772-12-31",
        "diedDateBegin": "+0846-01-01",
        "diedDateEnd": "+0846-12-31",
        "note": "唐代大詩人，字樂天。",
        "noteFull": "",
        "birthDateString": "生於：唐, 大曆, 七年",
        "deathDateString": "卒於：唐, 會昌, 六年",
        "birthDateImpreciseFlag": "0",
        "deathDateImpreciseFlag": "0",
        "lang": "中文",
        "deathPlaceCode": "",
        "deathPlaceName": None,
        "birthPlaceCode": "PL000000044997",
        "birthPlaceName": "隴西",
        "dynasty": "唐",
        "names": "[中文] 白樂天,白香山,醉吟先生",
        "pinyin": {},
    }
    base.update(overrides)
    return base


WANGWEI_MULTI = _cb(
    {
        "data1": _record(
            authorityID="A004031",
            name="王維",
            bornDateBegin="+0699-01-01",
            bornDateEnd="+0699-12-31",
            diedDateBegin="+0759-08-02",
            diedDateEnd="+0759-08-30",
            birthPlaceCode="PL000000004787",
            birthPlaceName="祁縣",
            names="[中文] 王右丞,詩佛,王摩詰",
        ),
        "data2": _record(
            authorityID="A043553",
            name="王維章",
            dynasty="明",
            bornDateBegin="unknown",
            bornDateEnd="unknown",
            diedDateBegin="+1613-01-01",
            diedDateEnd="+1613-12-31",
            names="[中文] 王維章",
        ),
        "count": 2,
        "rowCount": 2,
    }
)

BAIJUYI_SINGLE = _cb({"data1": _record()})

LIBAI_SINGLE = _cb(
    {
        "data1": _record(
            name="李白",
            authorityID="A005220",
            bornDateBegin="+0701-01-01",
            bornDateEnd="+0702-12-31",
            diedDateBegin="+0762-01-01",
            diedDateEnd="+0762-12-31",
            birthPlaceCode="PL000000044997",
            birthPlaceName="隴西",
            names="[中文] 李太白,詩仙,李青蓮",
        )
    }
)

DUFU_SINGLE = _cb(
    {
        "data1": _record(
            name="杜甫",
            authorityID="A005221",
            bornDateBegin="+0712-01-01",
            bornDateEnd="+0712-12-31",
            diedDateBegin="+0770-01-01",
            diedDateEnd="+0770-12-31",
            birthPlaceCode="PL000000005001",
            birthPlaceName="鞏縣",
            names="[中文] 子美,杜少陵,詩聖",
        )
    }
)

NOT_FOUND_EMPTY = _cb({})
NOT_FOUND_OTHER = _cb({"data1": _record(name="張三", authorityID="A999999")})

BAD_JSONP = b"not json at all{"


class _FixedRng:
    def uniform(self, low: float, high: float) -> float:
        return (low + high) / 2


class _FakeResponse:
    def __init__(self, body: bytes, status: int = 200, headers: dict[str, str] | None = None) -> None:
        self._body = body
        self.status = status
        self.headers = headers or {}

    def read(self) -> bytes:
        return self._body

    def close(self) -> None:
        pass


def _http_error(code: int, retry_after: float | None = None) -> urllib.error.HTTPError:
    headers = email.message.Message()
    if retry_after is not None:
        headers.add_header("Retry-After", str(retry_after))
    return urllib.error.HTTPError(
        "https://fixture.invalid/", code, f"HTTP {code}", headers, io.BytesIO()
    )


def write_poems(tmp: str, entries: list[tuple[str, str, int]]) -> Path:
    path = Path(tmp) / "poems.json"
    poems = []
    for name, dynasty, count in entries:
        for index in range(count):
            poems.append(
                {"poet": name, "author": name, "dynasty": dynasty, "title": f"{name}{index}"}
            )
    path.write_text(json.dumps(poems, ensure_ascii=False), encoding="utf-8")
    return path


def seed_cache(cache_dir: Path, name: str, body: bytes) -> None:
    CacheStore(cache_dir).store(
        person_query_url(traditional_name(name)),
        body,
        retrieved_at=FIXED_TIME,
        content_type="text/javascript",
    )


def run_collect(
    tmp: str,
    poems_path: Path,
    cached: dict[str, bytes],
    *,
    scope: str = "all",
    poets: str | None = None,
    resume: bool = False,
    clock: object | None = None,
) -> tuple[dict, Path, Path, Path]:
    cache_dir = Path(tmp) / "cache"
    matches = Path(tmp) / "matches.jsonl"
    coverage = Path(tmp) / "coverage.json"
    for name, body in cached.items():
        seed_cache(cache_dir, name, body)
    coverage_value = collect(
        scope=scope,
        poets_arg=poets,
        offline=True,
        resume=resume,
        delay_min=0.1,
        delay_max=0.2,
        timeout=5.0,
        retries=0,
        poems_path=poems_path,
        cache_dir=cache_dir,
        matches_path=matches,
        coverage_path=coverage,
        clock=clock or (lambda: FIXED_TIME),
        sleeper=lambda _n: None,
        rng=_FixedRng(),
    )
    return coverage_value, matches, coverage, cache_dir


class JsonpParsingTests(unittest.TestCase):
    def test_parse_jsonp_handles_callback_wrapper_and_trailing_semicolon(self) -> None:
        callback, payload = parse_jsonp('abc123({"data1": {"name": "李白"}});'.encode("utf-8"))
        self.assertEqual("abc123", callback)
        self.assertEqual({"data1": {"name": "李白"}}, payload)

    def test_parse_jsonp_handles_documented_callback_name(self) -> None:
        callback, payload = parse_jsonp(b'ddbcAuthPerson({"data1": {}});')
        self.assertEqual("ddbcAuthPerson", callback)
        self.assertIsInstance(payload, dict)

    def test_parse_jsonp_accepts_bare_json_object(self) -> None:
        callback, payload = parse_jsonp('{"data1": {"name": "李白"}}'.encode("utf-8"))
        self.assertEqual("", callback)
        self.assertEqual({"data1": {"name": "李白"}}, payload)

    def test_parse_jsonp_accepts_bare_null(self) -> None:
        callback, payload = parse_jsonp(b"null")
        self.assertEqual("", callback)
        self.assertEqual({}, payload)

    def test_parse_jsonp_rejects_neither_json_nor_wrapper(self) -> None:
        with self.assertRaises(ValueError):
            parse_jsonp(b"garbage without parentheses or json")

    def test_parse_jsonp_rejects_non_object_payload(self) -> None:
        with self.assertRaises(ValueError):
            parse_jsonp(b"cb([1, 2, 3]);")

    def test_multiple_dataN_records_and_row_metadata(self) -> None:
        callback, payload = parse_jsonp(WANGWEI_MULTI)
        records, metadata = person_records_from_payload(payload)
        self.assertEqual(2, len(records))
        self.assertEqual("A004031", records[0].authorityID)
        self.assertEqual("王維", records[0].name)
        self.assertEqual("A043553", records[1].authorityID)
        self.assertEqual("王維章", records[1].name)
        self.assertEqual({"count": 2, "rowCount": 2}, metadata)

    def test_parse_names_field_handles_language_tags_and_commas(self) -> None:
        aliases = parse_names_field("[中文] 白樂天,白香山,醉吟先生")
        self.assertIn("白樂天", aliases)
        self.assertIn("醉吟先生", aliases)
        self.assertEqual((), parse_names_field(""))

    def test_record_dates_and_life_years(self) -> None:
        record = DilaRecord(
            authorityID="A002039", name="白居易", dynasty="唐",
            born_begin="+0772-01-01", born_end="+0772-12-31",
            died_begin="+0846-01-01", died_end="+0846-12-31",
            birth_place_code="", birth_place_name="", death_place_code="", death_place_name="",
            note="", note_full="", aliases=(), lang="中文",
        )
        self.assertEqual((772, 772), record.born_years)
        self.assertEqual((846, 846), record.died_years)
        self.assertEqual((772, 846), record.life_years)
        unknown = DilaRecord(
            authorityID="X", name="王維章", dynasty="明",
            born_begin="unknown", born_end="unknown", died_begin="+1613-01-01", died_end="+1613-12-31",
            birth_place_code="", birth_place_name="", death_place_code="", death_place_name="",
            note="", note_full="", aliases=(), lang="中文",
        )
        self.assertEqual((1613, 1613), unknown.died_years)
        self.assertEqual((1613, 1613), unknown.life_years)


class NameAliasDynastyDateScoringTests(unittest.TestCase):
    def test_exact_name_and_dynasty_scores_high(self) -> None:
        poet = PoetSpec("白居易", "唐", 100)
        record = DilaRecord(
            authorityID="A002039", name="白居易", dynasty="唐",
            born_begin="+0772-01-01", born_end="+0772-12-31",
            died_begin="+0846-01-01", died_end="+0846-12-31",
            birth_place_code="", birth_place_name="", death_place_code="", death_place_name="",
            note="", note_full="", aliases=("白樂天",), lang="中文",
        )
        score = score_candidate(poet, record, local_life_years("白居易"))
        self.assertIsNotNone(score)
        self.assertEqual("exact_name", score["name_method"])
        self.assertEqual("exact", score["dynasty_kind"])
        self.assertEqual(100, score["name_score"])
        self.assertEqual(50, score["dynasty_score"])
        self.assertTrue(score["date_score"] > 0)
        self.assertTrue(score["credible"])

    def test_traditional_alias_matches(self) -> None:
        self.assertEqual("traditional_alias", name_match_method("苏轼", "蘇軾"))
        self.assertEqual("mixed_simplified_traditional_alias", name_match_method("黄庭坚", "黄庭堅"))
        self.assertIsNone(name_match_method("苏轼", "蘇轍"))

    def test_record_alias_matching_poet_name(self) -> None:
        record = DilaRecord(
            authorityID="X", name="青蓮居士", dynasty="唐",
            born_begin="", born_end="", died_begin="", died_end="",
            birth_place_code="", birth_place_name="", death_place_code="", death_place_name="",
            note="", note_full="", aliases=("李白",), lang="中文",
        )
        score = score_candidate(PoetSpec("李白", "唐", 10), record, None)
        self.assertIsNotNone(score)
        self.assertEqual("record_alias_matches_poet", score["name_method"])

    def test_dynasty_mismatch_is_penalized(self) -> None:
        record = DilaRecord(
            authorityID="A043553", name="王維章", dynasty="明",
            born_begin="unknown", born_end="unknown", died_begin="+1613-01-01", died_end="+1613-12-31",
            birth_place_code="", birth_place_name="", death_place_code="", death_place_name="",
            note="", note_full="", aliases=("王維章",), lang="中文",
        )
        score = score_candidate(PoetSpec("王维", "唐", 10), record, local_life_years("王维"))
        self.assertIsNotNone(score)
        self.assertEqual("substring", score["name_method"])
        self.assertEqual("mismatch", score["dynasty_kind"])
        self.assertEqual(-60, score["dynasty_score"])
        self.assertFalse(score["credible"])
        self.assertEqual("mismatch", dynasty_match_kind("唐", ("明",)))
        self.assertEqual("exact", dynasty_match_kind("唐", ("唐",)))
        self.assertEqual("compatible", dynasty_match_kind("唐", ("南唐",)))
        self.assertEqual("unknown", dynasty_match_kind("唐", ()))

    def test_date_overlap_separates_namesakes(self) -> None:
        poet = PoetSpec("李益", "唐", 10)
        overlapping = DilaRecord(
            authorityID="A1", name="李益", dynasty="唐",
            born_begin="+0746-01-01", born_end="+0746-12-31",
            died_begin="+0829-01-01", died_end="+0829-12-31",
            birth_place_code="", birth_place_name="", death_place_code="", death_place_name="",
            note="", note_full="", aliases=(), lang="中文",
        )
        distant = DilaRecord(
            authorityID="A2", name="李益", dynasty="唐",
            born_begin="+0900-01-01", born_end="+0900-12-31",
            died_begin="+0950-01-01", died_end="+0950-12-31",
            birth_place_code="", birth_place_name="", death_place_code="", death_place_name="",
            note="", note_full="", aliases=(), lang="中文",
        )
        local = local_life_years("李益")
        self.assertEqual((746 - LOCAL_YEAR_TOLERANCE, 746 + LOCAL_YEAR_TOLERANCE), local.birth)
        self.assertEqual((829 - LOCAL_YEAR_TOLERANCE, 829 + LOCAL_YEAR_TOLERANCE), local.death)
        first = score_candidate(poet, overlapping, local)
        second = score_candidate(poet, distant, local)
        self.assertGreater(first["date_score"], 0)
        self.assertEqual(-90, second["date_score"])
        self.assertTrue(first["credible"])
        self.assertFalse(second["credible"])

    def test_birth_death_compared_separately_not_union_lifetime(self) -> None:
        poet = PoetSpec("李益", "唐", 10)
        local = LifeSpan(birth=(700, 760), death=(790, 820))
        incompatible = DilaRecord(
            authorityID="A3", name="李益", dynasty="唐",
            born_begin="+0600-01-01", born_end="+0650-12-31",
            died_begin="+0900-01-01", died_end="+0930-12-31",
            birth_place_code="", birth_place_name="", death_place_code="", death_place_name="",
            note="", note_full="", aliases=(), lang="中文",
        )
        union_span = (600, 930)
        self.assertTrue(
            max(union_span[0], local.birth[0]) <= min(union_span[1], local.death[1]),
            "union lifetime would appear to overlap",
        )
        score = score_candidate(poet, incompatible, local)
        self.assertIsNotNone(score)
        self.assertEqual(-90, score["date_score"])
        self.assertTrue(score["date_contradiction"])
        self.assertFalse(score["credible"])
        self.assertEqual(0, score["date_overlap_parts"]["birth"])
        self.assertEqual(0, score["date_overlap_parts"]["death"])

    def test_single_known_part_stays_positive_when_it_overlaps(self) -> None:
        poet = PoetSpec("李益", "唐", 10)
        local = LifeSpan(birth=(746, 746), death=(829, 829))
        only_birth_known = DilaRecord(
            authorityID="A4", name="李益", dynasty="唐",
            born_begin="+0745-01-01", born_end="+0750-12-31",
            died_begin="unknown", died_end="unknown",
            birth_place_code="", birth_place_name="", death_place_code="", death_place_name="",
            note="", note_full="", aliases=(), lang="中文",
        )
        result = score_date(only_birth_known, local)
        self.assertTrue(result["date_known"])
        self.assertFalse(result["date_contradiction"])
        self.assertGreater(result["date_score"], 0)
        self.assertIn("birth", result["overlap_parts"])
        self.assertNotIn("death", result["overlap_parts"])

    def test_unknown_dates_stay_neutral(self) -> None:
        record = DilaRecord(
            authorityID="X", name="柳永", dynasty="宋",
            born_begin="unknown", born_end="unknown", died_begin="unknown", died_end="unknown",
            birth_place_code="", birth_place_name="", death_place_code="", death_place_name="",
            note="", note_full="", aliases=(), lang="中文",
        )
        score = score_candidate(PoetSpec("柳永", "宋", 10), record, local_life_years("柳永"))
        self.assertEqual(0, score["date_score"])
        self.assertFalse(score["date_known"])


class SelectionTests(unittest.TestCase):
    def _records(self, values: list[dict[str, object]]) -> list[DilaRecord]:
        records, _metadata = person_records_from_payload({"data1": values})
        return records

    def test_unique_candidate_is_matched(self) -> None:
        records, _ = person_records_from_payload({"data1": _record()})
        rows, outcome = select_for_poet(
            PoetSpec("白居易", "唐", 100), records, _cached_result("白居易"),
            local_life_years("白居易"),
        )
        self.assertEqual("matched", outcome)
        self.assertEqual(1, len(rows))
        self.assertTrue(rows[0]["selected"])
        self.assertEqual("matched", rows[0]["match_status"])

    def test_namesake_runnerup_is_kept_but_not_selected(self) -> None:
        _callback, payload = parse_jsonp(WANGWEI_MULTI)
        records, metadata = person_records_from_payload(payload)
        rows, outcome = select_for_poet(
            PoetSpec("王维", "唐", 200), records, _cached_result("王维"),
            local_life_years("王维"), metadata,
        )
        self.assertEqual("matched", outcome)
        self.assertEqual(2, len(rows))
        selected = [row for row in rows if row["selected"]]
        self.assertEqual(1, len(selected))
        self.assertEqual("王維", selected[0]["canonical_name"])
        self.assertEqual("A004031", selected[0]["authorityID"])
        runner = next(row for row in rows if row["canonical_name"] == "王維章")
        self.assertFalse(runner["selected"])
        self.assertEqual("ambiguous", runner["match_status"])

    def test_exact_tie_is_ambiguous_not_first_hit(self) -> None:
        records, _ = person_records_from_payload(
            {
                "data1": _record(name="张籍", authorityID="A100", dynasty="唐",
                                 bornDateBegin="unknown", bornDateEnd="unknown",
                                 diedDateBegin="unknown", diedDateEnd="unknown"),
                "data2": _record(name="张籍", authorityID="B200", dynasty="唐",
                                 bornDateBegin="unknown", bornDateEnd="unknown",
                                 diedDateBegin="unknown", diedDateEnd="unknown"),
            }
        )
        rows, outcome = select_for_poet(
            PoetSpec("张籍", "唐", 50), records, _cached_result("张籍"), None,
        )
        self.assertEqual("ambiguous", outcome)
        self.assertEqual(2, len(rows))
        self.assertTrue(all(not row["selected"] for row in rows))
        self.assertTrue(all(row["match_status"] == "ambiguous" for row in rows))

    def test_date_overlap_breaks_tie(self) -> None:
        records, _ = person_records_from_payload(
            {
                "data1": _record(name="李益", authorityID="A1", dynasty="唐",
                                 bornDateBegin="+0746-01-01", bornDateEnd="+0746-12-31",
                                 diedDateBegin="+0829-01-01", diedDateEnd="+0829-12-31"),
                "data2": _record(name="李益", authorityID="A2", dynasty="唐",
                                 bornDateBegin="+0900-01-01", bornDateEnd="+0900-12-31",
                                 diedDateBegin="+0950-01-01", diedDateEnd="+0950-12-31"),
            }
        )
        rows, outcome = select_for_poet(
            PoetSpec("李益", "唐", 50), records, _cached_result("李益"), local_life_years("李益"),
        )
        self.assertEqual("matched", outcome)
        selected = next(row for row in rows if row["selected"])
        self.assertEqual("A1", selected["authorityID"])

    def test_not_found_empty_payload(self) -> None:
        records, _ = person_records_from_payload({"data1": {}})
        self.assertEqual([], records)
        rows, outcome = select_for_poet(PoetSpec("李白", "唐", 1), [], _cached_result("李白"), None)
        self.assertEqual([], rows)
        self.assertEqual("not_found", outcome)

    def test_not_found_name_does_not_match(self) -> None:
        records, _ = person_records_from_payload({"data1": _record(name="張三")})
        rows, outcome = select_for_poet(PoetSpec("李白", "唐", 1), records, _cached_result("李白"), None)
        self.assertEqual([], rows)
        self.assertEqual("not_found", outcome)


def _cached_result(name: str):
    from dila_person_reference_pipeline import FetchResult

    return FetchResult(
        poet=name, query_url=person_query_url(name), usable=True, attempt_status="cache_hit",
        content_sha256="a" * 64, retrieved_at=FIXED_TIME, from_cache=True, http_status=200,
    )


class CacheTests(unittest.TestCase):
    def test_offline_cache_hit_does_not_network(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache = CacheStore(Path(tmp))
            url = person_query_url("白居易")
            cache.store(url, BAIJUYI_SINGLE, retrieved_at=FIXED_TIME, content_type="text/javascript")
            fetcher = DilaFetcher(
                cache, offline=True,
                opener=lambda *_args, **_kwargs: self.fail("offline mode attempted network"),
            )
            result = fetcher.fetch(url, "白居易")
            self.assertTrue(result.usable)
            self.assertEqual("cache_hit", result.attempt_status)
            self.assertEqual(BAIJUYI_SINGLE, result.body)

    def test_offline_requires_valid_checksum(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache = CacheStore(Path(tmp))
            url = person_query_url("白居易")
            meta = cache.store(url, BAIJUYI_SINGLE, retrieved_at=FIXED_TIME)
            (Path(tmp) / "bodies" / meta["body_file"]).write_bytes(b"corrupt")
            fetcher = DilaFetcher(cache, offline=True)
            result = fetcher.fetch(url, "白居易")
            self.assertFalse(result.usable)
            self.assertEqual("fetch_failed", result.attempt_status)
            self.assertIn("checksum", result.error)

    def test_metadata_validation_rejects_bad_body_reference(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache = CacheStore(Path(tmp))
            url = person_query_url("白居易")
            cache.store(url, BAIJUYI_SINGLE, retrieved_at=FIXED_TIME)
            meta_path = cache.meta_path(url)
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            meta["body_file"] = "../etc/passwd"
            meta_path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
            fetcher = DilaFetcher(cache, offline=True)
            result = fetcher.fetch(url, "白居易")
            self.assertFalse(result.usable)
            self.assertIn("metadata", result.error)

    def test_fetch_success_stores_body_and_returns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache = CacheStore(Path(tmp))
            url = person_query_url("王维")

            def opener(_request, timeout=None):
                return _FakeResponse(WANGWEI_MULTI, headers={"Content-Type": "text/javascript"})

            fetcher = DilaFetcher(
                cache, retries=0, opener=opener, sleeper=lambda _n: None, clock=lambda: FIXED_TIME
            )
            result = fetcher.fetch(url, "王维")
            self.assertTrue(result.usable)
            self.assertEqual("fetched", result.attempt_status)
            self.assertFalse(result.from_cache)
            self.assertEqual(200, result.http_status)
            cached_body, meta, status = cache.read(url)
            self.assertEqual("cache_hit", status)
            self.assertEqual(WANGWEI_MULTI, cached_body)


class FetchAndRetryTests(unittest.TestCase):
    def test_429_retries_with_retry_after_then_succeeds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache = CacheStore(Path(tmp))
            calls = {"n": 0}
            sleeps: list[float] = []

            def opener(_request, timeout=None):
                calls["n"] += 1
                if calls["n"] <= 2:
                    raise _http_error(429, retry_after=3)
                return _FakeResponse(BAIJUYI_SINGLE)

            fetcher = DilaFetcher(
                cache, retries=2, opener=opener, sleeper=sleeps.append,
                clock=lambda: FIXED_TIME,
            )
            result = fetcher.fetch(person_query_url("白居易"), "白居易")
            self.assertTrue(result.usable)
            self.assertEqual("fetched", result.attempt_status)
            self.assertEqual(3, calls["n"])
            self.assertEqual(2, result.retry_count)
            self.assertEqual((3.0, 3.0), result.retry_waits)
            self.assertEqual([3.0, 3.0], sleeps)

    def test_5xx_retries_then_persists_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache = CacheStore(Path(tmp))
            sleeps: list[float] = []

            def opener(_request, timeout=None):
                raise _http_error(503)

            fetcher = DilaFetcher(
                cache, retries=2, opener=opener, sleeper=sleeps.append,
                clock=lambda: FIXED_TIME,
            )
            result = fetcher.fetch(person_query_url("王维"), "王维")
            self.assertFalse(result.usable)
            self.assertEqual("fetch_failed", result.attempt_status)
            self.assertEqual(503, result.http_status)
            self.assertEqual(2, result.retry_count)
            self.assertIn("HTTP 503", result.error)
            self.assertEqual([1.5, 3.0], sleeps)

    def test_any_5xx_status_is_retryable(self) -> None:
        self.assertTrue(is_retryable_status(507))
        self.assertTrue(is_retryable_status(599))
        self.assertTrue(is_retryable_status(500))
        self.assertTrue(is_retryable_status(503))
        self.assertTrue(is_retryable_status(429))
        self.assertTrue(is_retryable_status(408))
        self.assertFalse(is_retryable_status(404))
        self.assertFalse(is_retryable_status(301))
        self.assertFalse(is_retryable_status(None))

    def test_507_retries_then_succeeds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache = CacheStore(Path(tmp))
            calls = {"n": 0}
            sleeps: list[float] = []

            def opener(_request, timeout=None):
                calls["n"] += 1
                if calls["n"] == 1:
                    raise _http_error(507)
                return _FakeResponse(BAIJUYI_SINGLE)

            fetcher = DilaFetcher(
                cache, retries=2, opener=opener, sleeper=sleeps.append,
                clock=lambda: FIXED_TIME,
            )
            result = fetcher.fetch(person_query_url("白居易"), "白居易")
            self.assertTrue(result.usable)
            self.assertEqual("fetched", result.attempt_status)
            self.assertEqual(2, calls["n"])
            self.assertEqual(1, result.retry_count)
            self.assertEqual([1.5], sleeps)

    def test_timeout_retries_then_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache = CacheStore(Path(tmp))

            def opener(_request, timeout=None):
                raise TimeoutError("fixture slow")

            fetcher = DilaFetcher(cache, retries=1, opener=opener, sleeper=lambda _n: None)
            result = fetcher.fetch(person_query_url("李白"), "李白")
            self.assertFalse(result.usable)
            self.assertEqual("fetch_failed", result.attempt_status)
            self.assertEqual(1, result.retry_count)
            self.assertIn("TimeoutError", result.error)

    def test_socket_timeout_retries_then_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache = CacheStore(Path(tmp))
            sleeps: list[float] = []

            def opener(_request, timeout=None):
                raise socket.timeout("fixture socket timed out")

            fetcher = DilaFetcher(cache, retries=1, opener=opener, sleeper=sleeps.append)
            result = fetcher.fetch(person_query_url("杜甫"), "杜甫")
            self.assertFalse(result.usable)
            self.assertEqual("fetch_failed", result.attempt_status)
            self.assertEqual(1, result.retry_count)
            self.assertIn("fixture socket timed out", result.error)
            self.assertEqual([1.5], sleeps)

    def test_non_retryable_4xx_stops_immediately(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache = CacheStore(Path(tmp))
            calls = {"n": 0}

            def opener(_request, timeout=None):
                calls["n"] += 1
                raise _http_error(404)

            fetcher = DilaFetcher(cache, retries=5, opener=opener, sleeper=lambda _n: None)
            result = fetcher.fetch(person_query_url("杜甫"), "杜甫")
            self.assertFalse(result.usable)
            self.assertEqual(404, result.http_status)
            self.assertEqual(0, result.retry_count)
            self.assertEqual(1, calls["n"])

    def test_failure_with_valid_cache_falls_back_to_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache = CacheStore(Path(tmp))
            url = person_query_url("苏轼")
            cache.store(url, BAIJUYI_SINGLE, retrieved_at=FIXED_TIME)

            def opener(_request, timeout=None):
                raise _http_error(503)

            fetcher = DilaFetcher(cache, retries=0, opener=opener, sleeper=lambda _n: None)
            result = fetcher.fetch(url, "苏轼")
            self.assertTrue(result.usable)
            self.assertTrue(result.from_cache)
            self.assertEqual("fetch_failed_cache_used", result.attempt_status)
            self.assertIn("HTTP 503", result.error)

    def test_sequential_no_concurrency_and_delay_applied(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache = CacheStore(Path(tmp))
            urls = [person_query_url(name) for name in ("王维", "李白", "杜甫")]
            order: list[str] = []
            sleeps: list[float] = []

            def opener(request, timeout=None):
                order.append(request.full_url)
                return _FakeResponse(BAIJUYI_SINGLE)

            fetcher = DilaFetcher(
                cache, retries=0, opener=opener, sleeper=sleeps.append,
                rng=_FixedRng(), delay_min=5.0, delay_max=8.0, clock=lambda: FIXED_TIME,
            )
            results = fetcher.fetch_all(urls, poets=("王维", "李白", "杜甫"))
            self.assertEqual(urls, order)
            self.assertEqual([6.5, 6.5], sleeps)
            self.assertEqual([True, True, True], [result.usable for result in results])

    def test_offline_fetch_all_applies_no_delay(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache = CacheStore(Path(tmp))
            sleeps: list[float] = []
            for name in ("王维", "李白"):
                seed_cache(Path(tmp), name, BAIJUYI_SINGLE)
            fetcher = DilaFetcher(cache, offline=True, sleeper=sleeps.append, rng=_FixedRng())
            results = fetcher.fetch_all(
                [
                    person_query_url(traditional_name("王维")),
                    person_query_url(traditional_name("李白")),
                ],
                poets=("王维", "李白"),
            )
            self.assertEqual(2, len(results))
            self.assertTrue(all(result.usable for result in results))
            self.assertEqual([], sleeps)


class MergeResumeSubsetTests(unittest.TestCase):
    def _row(self, poet: str, status: str = "matched", authority_id: str = "A001") -> dict:
        return {
            "reference_id": stable_id("dila", poet, status, authority_id),
            "poet": poet,
            "dynasty": "唐",
            "match_status": status,
            "selected": status == "matched",
            "authorityID": authority_id,
        }

    def test_subset_run_preserves_unrelated_rows(self) -> None:
        existing = [self._row("李白"), self._row("杜甫")]
        fresh = {poet: [self._row(poet, authority_id="B001")] for poet in ("李白",)}
        merged = merge_matches(existing, fresh)
        poets = {row["poet"] for row in merged}
        self.assertEqual({"李白", "杜甫"}, poets)
        self.assertEqual(2, len(merged))
        self.assertIn("B001", [row["authorityID"] for row in merged if row["poet"] == "李白"])
        self.assertEqual("A001", next(row["authorityID"] for row in merged if row["poet"] == "杜甫"))

    def test_successful_not_found_clears_stale_rows_via_replaced_set(self) -> None:
        existing = [self._row("李白"), self._row("杜甫")]
        merged = merge_matches(existing, {"李白": []}, replaced_poets=["李白"])
        poets = {row["poet"] for row in merged}
        self.assertEqual({"杜甫"}, poets)
        self.assertEqual(1, len(merged))

    def test_fetch_failed_poet_rows_are_preserved(self) -> None:
        existing = [self._row("李白")]
        merged = merge_matches(existing, {"李白": [], "杜甫": []}, replaced_poets=["杜甫"])
        poets = {row["poet"] for row in merged}
        self.assertEqual({"李白"}, poets)
        self.assertEqual(1, len(merged))

    def test_parsed_not_found_clears_stale_rows_in_collect(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            poems = write_poems(tmp, [("李白", "唐", 2)])
            matches = Path(tmp) / "matches.jsonl"
            write_jsonl(matches, [self._row("李白")])
            coverage_value, matches_out, _, _ = run_collect(tmp, poems, {"李白": NOT_FOUND_EMPTY})
            item = coverage_value["per_poet"][0]
            self.assertEqual("not_found", item["dila"]["status"])
            self.assertEqual("not_found", item["dila"]["active_status"])
            self.assertEqual(0, item["dila"]["persisted_record_count"])
            self.assertEqual(0, matches_out.stat().st_size)

    def test_fetch_failed_in_collect_preserves_old_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            poems = write_poems(tmp, [("李白", "唐", 2)])
            matches = Path(tmp) / "matches.jsonl"
            write_jsonl(matches, [self._row("李白")])
            coverage_value, matches_out, _, _ = run_collect(tmp, poems, {})
            item = coverage_value["per_poet"][0]
            self.assertEqual("fetch_failed", item["dila"]["status"])
            self.assertEqual("matched", item["dila"]["active_status"])
            self.assertEqual(1, item["dila"]["persisted_record_count"])
            self.assertEqual(1, len([line for line in matches_out.read_text(encoding="utf-8").splitlines() if line]))

    def test_fetch_failed_cache_used_preserves_rows_status_but_records_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            poems = write_poems(tmp, [("李白", "唐", 2)])
            cache_dir = Path(tmp) / "cache"
            matches = Path(tmp) / "m.jsonl"
            coverage = Path(tmp) / "c.json"
            seed_cache(cache_dir, "李白", LIBAI_SINGLE)
            first = collect(
                scope="all", poets_arg=None, offline=True, resume=False,
                delay_min=0.1, delay_max=0.2, timeout=5, retries=0,
                poems_path=poems, cache_dir=cache_dir, matches_path=matches, coverage_path=coverage,
                clock=lambda: FIXED_TIME, sleeper=lambda _n: None, rng=_FixedRng(),
            )
            first_item = next(item for item in first["per_poet"] if item["poet"] == "李白")
            self.assertEqual("matched", first_item["dila"]["status"])

            seed_cache(cache_dir, "李白", NOT_FOUND_EMPTY)

            def opener(_request, timeout=None):
                raise _http_error(503)

            second = collect(
                scope="all", poets_arg=None, offline=False, resume=False,
                delay_min=0.1, delay_max=0.2, timeout=5, retries=0,
                poems_path=poems, cache_dir=cache_dir, matches_path=matches, coverage_path=coverage,
                clock=lambda: FIXED_TIME, sleeper=lambda _n: None, rng=_FixedRng(), opener=opener,
            )
            item = next(entry for entry in second["per_poet"] if entry["poet"] == "李白")
            self.assertEqual("matched", item["dila"]["status"])
            self.assertEqual("matched", item["dila"]["active_status"])
            self.assertEqual(1, item["dila"]["persisted_record_count"])
            attempt = item["dila"]["attempt"]
            self.assertEqual("fetch_failed_cache_used", attempt["attempt_status"])
            self.assertIn("HTTP 503", attempt["error"])
            persisted = [
                json.loads(line)
                for line in matches.read_text(encoding="utf-8").splitlines()
                if line
            ]
            self.assertEqual(1, len(persisted))
            self.assertEqual("李白", persisted[0]["poet"])
            self.assertEqual("matched", persisted[0]["match_status"])

    def test_subset_run_preserves_prior_unselected_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            poems = write_poems(tmp, [("白居易", "唐", 2), ("杜甫", "唐", 2)])
            cache_dir = Path(tmp) / "cache"
            matches = Path(tmp) / "m.jsonl"
            coverage = Path(tmp) / "c.json"
            for name, body in (("白居易", BAIJUYI_SINGLE), ("杜甫", DUFU_SINGLE)):
                seed_cache(cache_dir, name, body)
            first = collect(
                scope="all", poets_arg=None, offline=True, resume=False,
                delay_min=0.1, delay_max=0.2, timeout=5, retries=0,
                poems_path=poems, cache_dir=cache_dir, matches_path=matches, coverage_path=coverage,
                clock=lambda: FIXED_TIME, sleeper=lambda _n: None, rng=_FixedRng(),
            )
            first_by = {item["poet"]: item["dila"] for item in first["per_poet"]}
            self.assertEqual("matched", first_by["白居易"]["status"])
            self.assertEqual("matched", first_by["杜甫"]["status"])
            second = collect(
                scope="all", poets_arg="白居易", offline=True, resume=False,
                delay_min=0.1, delay_max=0.2, timeout=5, retries=0,
                poems_path=poems, cache_dir=cache_dir, matches_path=matches, coverage_path=coverage,
                clock=lambda: "2026-08-09T12:00:00+00:00", sleeper=lambda _n: None, rng=_FixedRng(),
            )
            second_by = {item["poet"]: item["dila"] for item in second["per_poet"]}
            self.assertEqual("matched", second_by["白居易"]["status"])
            self.assertEqual("matched", second_by["杜甫"]["status"])
            self.assertIn("attempt", second_by["杜甫"])
            self.assertEqual(1, second["totals"]["selected_poets"])
            self.assertEqual({"matched": 2}, second["totals"]["status_counts"])

    def test_resume_skips_poets_with_persisted_rows(self) -> None:
        existing = [self._row("白居易"), self._row("杜甫")]
        to_fetch, resumed = resolve_run_plan(["白居易", "杜甫", "李白"], existing, resume=True)
        self.assertEqual(["李白"], to_fetch)
        self.assertEqual(["白居易", "杜甫"], resumed)
        to_fetch_off, resumed_off = resolve_run_plan(["白居易"], existing, resume=False)
        self.assertEqual(["白居易"], to_fetch_off)
        self.assertEqual([], resumed_off)

    def test_offline_missing_cache_persists_explicit_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            poems = write_poems(tmp, [("李白", "唐", 2)])
            coverage_value, matches, coverage, _ = run_collect(tmp, poems, {})
            item = coverage_value["per_poet"][0]
            self.assertEqual("fetch_failed", item["dila"]["status"])
            self.assertEqual("not_found", item["dila"]["active_status"])
            self.assertIn("cache_miss", item["dila"]["attempt"]["error"])
            self.assertNotIn("matched", coverage_value["sources"]["dila_person"]["status_counts"])
            self.assertEqual({"fetch_failed": 1}, coverage_value["totals"]["status_counts"])

    def test_parse_failed_body_persists_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            poems = write_poems(tmp, [("李白", "唐", 2)])
            coverage_value, _, _, _ = run_collect(tmp, poems, {"李白": BAD_JSONP})
            item = coverage_value["per_poet"][0]
            self.assertEqual("parse_failed", item["dila"]["status"])
            self.assertEqual("parse_failed", item["dila"]["attempt"]["attempt_status"])

    def test_failed_fetch_preserves_old_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            poems = write_poems(tmp, [("王维", "唐", 2)])
            matches = Path(tmp) / "matches.jsonl"
            write_jsonl(matches, [self._row("王维")])
            coverage_value, _, _, _ = run_collect(tmp, poems, {})
            item = coverage_value["per_poet"][0]
            self.assertEqual("fetch_failed", item["dila"]["status"])
            self.assertEqual("matched", item["dila"]["active_status"])
            self.assertEqual(1, item["dila"]["persisted_record_count"])

    def test_subset_coverage_never_shrinks_below_88(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            poems = write_poems(tmp, [(f"詩人{index:02d}", "唐" if index < 46 else "宋", 2) for index in range(88)])
            coverage_value, _, _, _ = run_collect(tmp, poems, {"詩人00": BAIJUYI_SINGLE}, poets="詩人00")
            self.assertEqual(88, coverage_value["corpus"]["poet_count"])
            self.assertEqual(88, len(coverage_value["per_poet"]))
            self.assertEqual(1, coverage_value["totals"]["selected_poets"])


class AtomicIdempotencyTests(unittest.TestCase):
    def test_write_jsonl_is_atomic_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rows.jsonl"
            rows = [{"b": 2, "a": 1}, {"b": 3, "a": 2}]
            write_jsonl(path, rows)
            first = path.read_bytes()
            write_jsonl(path, rows)
            self.assertEqual(first, path.read_bytes())
            self.assertNotIn(b".tmp", first)

    def test_rerun_with_fixed_inputs_is_byte_identical(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            poems = write_poems(tmp, [("白居易", "唐", 3), ("杜甫", "唐", 3)])
            cached = {"白居易": BAIJUYI_SINGLE, "杜甫": WANGWEI_MULTI}
            first, matches_path, coverage_path, _ = run_collect(tmp, poems, cached)
            matches_snapshot = matches_path.read_bytes()
            coverage_snapshot = coverage_path.read_bytes()
            generated_snapshot = json.loads(coverage_snapshot.decode("utf-8"))["generated_at"]
            second, matches_path, coverage_path, _ = run_collect(
                tmp, poems, cached, clock=lambda: "2026-08-09T23:59:59+00:00"
            )
            self.assertEqual(matches_snapshot, matches_path.read_bytes())
            self.assertEqual(coverage_snapshot, coverage_path.read_bytes())
            self.assertEqual(
                generated_snapshot,
                json.loads(coverage_path.read_text(encoding="utf-8"))["generated_at"],
            )

    def test_noop_resume_preserves_generated_at(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            poems = write_poems(tmp, [("白居易", "唐", 3), ("杜甫", "唐", 3)])
            cached = {"白居易": BAIJUYI_SINGLE, "杜甫": WANGWEI_MULTI}
            first, matches_path, coverage_path, _ = run_collect(tmp, poems, cached)
            matches_snapshot = matches_path.read_bytes()
            generated_snapshot = json.loads(coverage_path.read_text(encoding="utf-8"))["generated_at"]
            first_statuses = {
                item["poet"]: item["dila"]["status"] for item in first["per_poet"]
            }
            second, matches_path, coverage_path, _ = run_collect(
                tmp, poems, cached, resume=True, poets="白居易,杜甫",
                clock=lambda: "2026-08-09T23:59:59+00:00",
            )
            self.assertEqual(matches_snapshot, matches_path.read_bytes())
            self.assertEqual(
                generated_snapshot,
                json.loads(coverage_path.read_text(encoding="utf-8"))["generated_at"],
            )
            second_statuses = {
                item["poet"]: item["dila"]["status"] for item in second["per_poet"]
            }
            self.assertEqual(first_statuses, second_statuses)
            self.assertTrue(second["sources"]["dila_person"]["resume"])
            self.assertEqual(1, second["totals"]["status_counts"].get("matched"))

    def test_matches_are_deterministically_sorted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            poems = write_poems(tmp, [("李白", "唐", 3), ("王维", "唐", 3)])
            cached = {"李白": BAIJUYI_SINGLE, "王维": WANGWEI_MULTI}
            first, matches_a, _, _ = run_collect(tmp, poems, cached)
            second, matches_b, _, _ = run_collect(tmp, poems, cached)
            rows_a = [json.loads(line) for line in matches_a.read_text(encoding="utf-8").splitlines() if line]
            rows_b = [json.loads(line) for line in matches_b.read_text(encoding="utf-8").splitlines() if line]
            self.assertEqual(rows_a, rows_b)
            keys = [(r["dynasty"], r["poet"], r["authorityID"], r["reference_id"]) for r in rows_a]
            self.assertEqual(sorted(keys), keys)


class RosterContractTests(unittest.TestCase):
    def test_discovers_exactly_88_from_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = write_poems(tmp, [(f"詩人{index:02d}", "唐" if index < 46 else "宋", 2) for index in range(88)])
            roster = load_roster(path)
            self.assertEqual(88, len(roster))
            self.assertEqual(176, sum(item.poem_count for item in roster))

    def test_tied_local_dynasty_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "poems.json"
            path.write_text(
                json.dumps(
                    [
                        {"poet": "甲", "author": "甲", "dynasty": "唐"},
                        {"poet": "甲", "author": "甲", "dynasty": "宋"},
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "tied"):
                load_roster(path)

    def test_match_rows_have_required_reference_fields(self) -> None:
        records, _ = person_records_from_payload({"data1": _record()})
        rows, _ = select_for_poet(
            PoetSpec("白居易", "唐", 100), records, _cached_result("白居易"),
            local_life_years("白居易"),
        )
        row = rows[0]
        for key in (
            "source_url",
            "authorityID",
            "canonical_name",
            "aliases",
            "dynasty",
            "born_range",
            "died_range",
            "birth_place",
            "note",
            "accessed_at",
            "license_note",
            "match_status",
        ):
            self.assertIn(key, row)
        self.assertIn("白樂天", row["aliases"])
        self.assertEqual(DILA_SOURCE_NAME, row["source"])
        self.assertEqual(DILA_LICENSE_NOTE, row["license_note"])

    def test_rows_never_contain_route_event_fields(self) -> None:
        records, _ = person_records_from_payload({"data1": _record()})
        rows, _ = select_for_poet(
            PoetSpec("白居易", "唐", 100), records, _cached_result("白居易"),
            local_life_years("白居易"),
        )
        for row in rows:
            banned = ROUTE_EVENT_FIELDS & set(row.keys())
            self.assertEqual(set(), banned)
            self.assertTrue(row["birthplace_reference_only"])
            self.assertEqual(True, row["birth_place"] and "name" in row["birth_place"])

    def test_target_paths_stay_in_candidate_layer(self) -> None:
        self.assertEqual("data/candidates", MATCHES_JSONL.parent.relative_to(MATCHES_JSONL.parents[2]).as_posix())
        self.assertNotIn("reviewed", str(MATCHES_JSONL).lower())
        self.assertEqual("dila_person", CACHE_DIR.name)
        self.assertIn("background_sources", str(CACHE_DIR))

    def test_active_status_rules(self) -> None:
        self.assertEqual("matched", active_status([self._row_for_active("a", "ambiguous"), self._row_for_active("b", "matched")]))
        self.assertEqual("ambiguous", active_status([self._row_for_active("a", "ambiguous")]))
        self.assertEqual("not_found", active_status([]))

    def test_license_note_states_cc_by_sa_and_correct_open_content_url(self) -> None:
        self.assertIn("/docs/open_content/", DILA_OPEN_CONTENT_URL)
        self.assertNotIn("open_content.php", DILA_OPEN_CONTENT_URL)
        self.assertIn(DILA_OPEN_CONTENT_URL, DILA_LICENSE_NOTE)
        self.assertIn(DILA_CC_LICENSE, DILA_LICENSE_NOTE)
        self.assertIn(DILA_CC_LICENSE_URL, DILA_LICENSE_NOTE)
        self.assertIn("CC BY-SA", DILA_LICENSE_NOTE)

    @staticmethod
    def _row_for_active(rid: str, status: str) -> dict:
        return {"reference_id": rid, "match_status": status}


class CoverageContractTests(unittest.TestCase):
    def test_coverage_reports_88_per_poet_and_status_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            poems = write_poems(tmp, [(f"詩人{index:02d}", "唐" if index < 46 else "宋", 2) for index in range(88)])
            cached = {f"詩人{index:02d}": BAIJUYI_SINGLE for index in range(88)}
            coverage_value, _, _, _ = run_collect(tmp, poems, cached)
            self.assertEqual(88, coverage_value["corpus"]["poet_count"])
            self.assertEqual(88, len(coverage_value["per_poet"]))
            allowed = {"matched", "ambiguous", "not_found", "fetch_failed", "parse_failed", "not_fetched"}
            for item in coverage_value["per_poet"]:
                self.assertIn(item["dila"]["status"], allowed)
                self.assertIn("attempt", item["dila"])
            notes = " ".join(coverage_value["interpretation_notes"])
            self.assertIn("作詩地點", notes)
            self.assertIn("birthplace_reference_only", notes)

    def test_attempt_record_keeps_failure_state(self) -> None:
        result = _cached_result("李白")
        result = result.__class__(
            poet="李白", query_url=person_query_url("李白"), usable=False,
            attempt_status="fetch_failed", http_status=429, retry_count=2,
            retry_waits=(3.0,), error="HTTP 429",
        )
        record = attempt_record(result, {})
        self.assertEqual("fetch_failed", record["attempt_status"])
        self.assertEqual(429, record["http_status"])
        self.assertEqual(2, record["retry_count"])
        self.assertEqual("HTTP 429", record["error"])


class LiveObservationTests(unittest.TestCase):
    def test_ssl_fallback_retries_unverified_only_for_dila_host(self) -> None:
        calls: list[object] = []

        def opener(request, timeout=None, **kwargs):
            calls.append(kwargs.get("context"))
            if kwargs.get("context") is None:
                raise urllib.error.URLError(
                    ssl.SSLCertVerificationError(1, "certificate verify failed: Missing Subject Key Identifier")
                )
            return _FakeResponse(BAIJUYI_SINGLE)

        request = urllib.request.Request(person_query_url("白居易"))
        response = open_dila_with_ssl_fallback(opener, request, timeout=5)
        self.assertIsInstance(response, _FakeResponse)
        self.assertEqual(2, len(calls))
        self.assertIsNone(calls[0])
        self.assertIsNotNone(calls[1])

    def test_ssl_fallback_never_applies_to_other_hosts(self) -> None:
        calls: list[object] = []

        def opener(request, timeout=None, **kwargs):
            calls.append(kwargs.get("context"))
            raise urllib.error.URLError(ssl.SSLCertVerificationError(1, "certificate verify failed"))

        request = urllib.request.Request("https://example.invalid/get")
        with self.assertRaises(urllib.error.URLError):
            open_dila_with_ssl_fallback(opener, request)
        self.assertEqual(1, len(calls))

    def test_ssl_fallback_does_not_mask_other_errors(self) -> None:
        def opener(request, timeout=None, **kwargs):
            raise urllib.error.URLError("name resolution failed")

        request = urllib.request.Request(person_query_url("李白"))
        with self.assertRaises(urllib.error.URLError):
            open_dila_with_ssl_fallback(opener, request)

    def test_redirect_handler_allows_same_host_and_blocks_cross_host(self) -> None:
        handler = _DilaHostRedirectHandler()
        original = urllib.request.Request(person_query_url("李白"))
        headers = email.message.Message()
        same_host = handler.redirect_request(
            original, None, 302, "Found", headers, person_query_url("杜甫")
        )
        self.assertIsNotNone(same_host)
        self.assertIn(DILA_HOST, same_host.full_url)
        self.assertEqual(DILA_HOST, urllib.parse.urlparse(same_host.full_url).netloc)
        with self.assertRaises(urllib.error.URLError):
            handler.redirect_request(
                original, None, 302, "Found", headers, "https://evil.example.invalid/steal"
            )

    def test_unverified_fallback_wiring_includes_redirect_guard(self) -> None:
        with mock.patch(
            "dila_person_reference_pipeline.ssl._create_unverified_context",
            return_value="unverified-ctx",
        ) as mock_ctx, mock.patch(
            "dila_person_reference_pipeline.urllib.request.build_opener"
        ) as mock_build, mock.patch(
            "dila_person_reference_pipeline.urllib.request.urlopen",
            side_effect=urllib.error.URLError(
                ssl.SSLCertVerificationError(1, "certificate verify failed")
            ),
        ):
            mock_build.return_value.open.return_value = _FakeResponse(BAIJUYI_SINGLE)
            request = urllib.request.Request(person_query_url("李白"))
            response = open_dila_with_ssl_fallback(default_opener, request, timeout=5)
            self.assertIsInstance(response, _FakeResponse)
            mock_ctx.assert_called_once()
            self.assertEqual(1, mock_build.call_count)
            handlers = mock_build.call_args[0]
            redirect_guards = [
                handler for handler in handlers if isinstance(handler, _DilaHostRedirectHandler)
            ]
            self.assertEqual(1, len(redirect_guards))
            https_handlers = [
                handler for handler in handlers if isinstance(handler, urllib.request.HTTPSHandler)
            ]
            self.assertEqual(1, len(https_handlers))
            self.assertEqual("unverified-ctx", https_handlers[0]._context)
            opener = mock_build.return_value.open
            opener.assert_called_once_with(request, timeout=5)

    def test_fetcher_uses_narrow_dila_ssl_fallback(self) -> None:
        calls: list[object] = []

        def opener(request, timeout=None, **kwargs):
            calls.append(kwargs.get("context"))
            if kwargs.get("context") is None:
                raise urllib.error.URLError(
                    ssl.SSLCertVerificationError(
                        1,
                        "certificate verify failed: Missing Subject Key Identifier",
                    )
                )
            return _FakeResponse(BAIJUYI_SINGLE)

        with tempfile.TemporaryDirectory() as tmp:
            fetcher = DilaFetcher(
                CacheStore(Path(tmp)),
                retries=0,
                opener=opener,
                sleeper=lambda _n: None,
            )
            result = fetcher.fetch(person_query_url("白居易"), "白居易")
        self.assertTrue(result.usable)
        self.assertEqual(2, len(calls))
        self.assertIsNone(calls[0])
        self.assertIsNotNone(calls[1])

    def test_null_result_is_empty_and_not_found(self) -> None:
        callback, payload = parse_jsonp(b"cb1(null);")
        self.assertEqual({}, payload)
        records, _ = person_records_from_payload(payload)
        self.assertEqual([], records)
        rows, outcome = select_for_poet(PoetSpec("李清照", "宋", 10), records, _cached_result("李清照"), None)
        self.assertEqual([], rows)
        self.assertEqual("not_found", outcome)

    def test_wangjian_multirow_resolves_by_dynasty_not_first_hit(self) -> None:
        payload = {
            "data1": _record(name="王建章", authorityID="A200001", dynasty="明",
                             bornDateBegin="unknown", bornDateEnd="unknown",
                             diedDateBegin="unknown", diedDateEnd="unknown", names="[中文] 王建章"),
            "data2": _record(name="王建", authorityID="A017625", dynasty="唐",
                             bornDateBegin="unknown", bornDateEnd="unknown",
                             diedDateBegin="unknown", diedDateEnd="unknown", names="[中文] 王建"),
            "data3": _record(name="王建中", authorityID="A200002", dynasty="元",
                             bornDateBegin="unknown", bornDateEnd="unknown",
                             diedDateBegin="unknown", diedDateEnd="unknown", names="[中文] 王建中"),
            "data4": _record(name="王建", authorityID="A200003", dynasty="清",
                             bornDateBegin="unknown", bornDateEnd="unknown",
                             diedDateBegin="unknown", diedDateEnd="unknown", names="[中文] 王建"),
            "data5": _record(name="王建", authorityID="A200004", dynasty="明",
                             bornDateBegin="+1500-01-01", bornDateEnd="+1500-12-31",
                             diedDateBegin="+1550-01-01", diedDateEnd="+1550-12-31", names="[中文] 王建"),
        }
        records, _ = person_records_from_payload(payload)
        self.assertEqual(5, len(records))
        self.assertNotEqual("A017625", records[0].authorityID)
        rows, outcome = select_for_poet(
            PoetSpec("王建", "唐", 50), records, _cached_result("王建"), local_life_years("王建")
        )
        self.assertEqual("matched", outcome)
        self.assertEqual(5, len(rows))
        selected = [row for row in rows if row["selected"]]
        self.assertEqual(1, len(selected))
        self.assertEqual("A017625", selected[0]["authorityID"])
        self.assertEqual("exact_name", selected[0]["match_method"])
        self.assertEqual("exact", selected[0]["dynasty_match"])
        self.assertTrue(all(not row["selected"] for row in rows if row is not selected[0]))

    def test_missing_dynasty_placeholder_is_unknown(self) -> None:
        self.assertEqual("unknown", dynasty_match_kind("唐", ("沒有給定朝代",)))
        self.assertEqual("unknown", dynasty_match_kind("宋", ("不詳",)))
        self.assertEqual("exact", dynasty_match_kind("唐", ("唐",)))
        self.assertEqual("compatible", dynasty_match_kind("唐", ("南唐",)))

    def test_notes_are_sanitized_and_truncated(self) -> None:
        noisy = "<a href=\"x\">李白</a> 盛唐詩人。" + "很長" * 300
        records, _ = person_records_from_payload({"data1": _record(note=noisy)})
        rows, _ = select_for_poet(
            PoetSpec("白居易", "唐", 100), records, _cached_result("白居易"), local_life_years("白居易")
        )
        note = rows[0]["note"]
        self.assertNotIn("<", note)
        self.assertNotIn(">", note)
        self.assertLessEqual(len(note), 300)
        self.assertIn("李白", note)
        self.assertEqual("李白 盛唐詩人。", sanitize_note("<a href=\"x\">李白</a> 盛唐詩人。"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
