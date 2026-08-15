"""Offline fixture and contract checks for the journey-source pipeline."""
from __future__ import annotations

import argparse
import json
import tempfile
import threading
import time
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import patch

from background_adapters import FetchResult
from background_contract import CANDIDATE_DIR, CORE_POETS, corpus_poet_profiles, corpus_poets, normalize_title

import journey_source_pipeline as jsp
import poet_source_registry as psr


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "journey_sources"


def fixture_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def fixture_json(name: str) -> object:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class FakeClient:
    """Deterministic offline stand-in for the polite HTTP cache client."""

    def __init__(
        self,
        *,
        html: str = "",
        payload: object = None,
        status: str = "ok",
        status_code: int = 200,
        note: str = "",
    ) -> None:
        self.html = html
        self.payload = payload
        self.status = status
        self.status_code = status_code
        self.note = note
        self.requests: list[str] = []
        self.cache_key = "fixture-cache-key"

    def request(self, method: str, url: str, **kwargs: object) -> FetchResult:
        del kwargs
        self.requests.append(url)
        return FetchResult(
            url=url,
            status=self.status,
            status_code=self.status_code,
            text=self.html,
            content=self.html.encode("utf-8"),
            content_type="text/html; charset=utf-8",
            cache_key=self.cache_key,
            note=self.note,
        )

    def get_json(self, url: str, **kwargs: object) -> tuple[FetchResult, object | None]:
        del kwargs
        self.requests.append(url)
        return (
            FetchResult(
                url=url,
                status=self.status,
                status_code=self.status_code,
                cache_key=self.cache_key,
                note=self.note,
            ),
            self.payload,
        )


class ScriptedPageClient(FakeClient):
    """Returns one (status, html) per requested sou-yun page, in order."""

    def __init__(self, pages: list[tuple[str, str]], note: str = "") -> None:
        super().__init__(html="", payload=None, status="ok", note=note)
        self.pages = list(pages)

    def request(self, method: str, url: str, **kwargs: object) -> FetchResult:
        del kwargs
        self.requests.append(url)
        status, html = self.pages.pop(0)
        return FetchResult(
            url=url,
            status=status,
            status_code=200 if status == "ok" else 500,
            text=html,
            content=html.encode("utf-8"),
            content_type="text/html; charset=utf-8",
            cache_key=f"fixture-{len(self.requests)}",
            note=self.note,
        )


class ScriptedJsonClient(FakeClient):
    """One deterministic FetchResult/payload pair per API call."""

    def __init__(self, pages: list[tuple[str, int, object | None]]) -> None:
        super().__init__()
        self.pages = list(pages)

    def get_json(self, url: str, **kwargs: object) -> tuple[FetchResult, object | None]:
        del kwargs
        self.requests.append(url)
        status, status_code, payload = self.pages.pop(0)
        return (
            FetchResult(
                url=url,
                status=status,
                status_code=status_code,
                cache_key=f"json-fixture-{len(self.requests)}",
                note=f"HTTP {status_code}" if status != "ok" else "",
            ),
            payload,
        )


def sample_poem(**updates: object) -> dict[str, object]:
    poem: dict[str, object] = {
        "poet": "李白",
        "author": "李白",
        "title": "金陵酒肆留别",
        "dynasty": "唐",
        "body": "风吹柳花满店香，吴姬压酒唤客尝。\n金陵子弟来相送，欲行不行各尽觞。",
        "body_hash": "b0e6e4e78b98d9b24ba13450d5a7fccbf33b2f2bd2d7f6b4e49d29f0a12661d8",
    }
    poem.update(updates)
    return poem


class SouyunParserTests(unittest.TestCase):
    def test_parses_year_month_no_year_and_subtitles(self) -> None:
        entries = jsp.parse_souyun_entries(fixture_text("souyun_author_page.html"))
        self.assertEqual(len(entries), 6)
        by_title = {entry["title"]: entry for entry in entries}

        jl = by_title["金陵酒肆留别"]
        self.assertEqual(jl["work_id"], "26161")
        self.assertEqual(jl["author"], "李白")
        self.assertEqual(jl["years"], [726])
        self.assertEqual(jl["precision"], "year_month")

        qp = by_title["清平调·其一"]
        self.assertEqual(qp["years"], [743])
        self.assertEqual(qp["precision"], "year")

        js = by_title["静夜思"]
        self.assertEqual(js["years"], [])
        self.assertEqual(js["precision"], "")

        self.assertEqual(by_title["秋浦歌（其十五）"]["years"], [754])
        self.assertEqual(by_title["其二"]["years"], [759])

    def test_work_id_extraction(self) -> None:
        self.assertEqual(jsp._souyun_work_id("Query.aspx?type=poem&id=26161"), "26161")
        self.assertEqual(jsp._souyun_work_id(""), "")
        self.assertEqual(jsp._souyun_work_id("Query.aspx?id=26249&type=poem"), "26249")

    def test_live_markup_uses_dynasty_dot_poet_not_author_date_span(self) -> None:
        html = (
            '<div class="poemTitle showDetail">'
            '<a href="Query.aspx?type=poem&amp;id=25812">赠孟浩然</a>'
            '<span class="author">（736年）</span> 盛唐 · 李白 五言律诗'
            '</div>'
        )
        entry = jsp.parse_souyun_entries(html)[0]
        self.assertEqual(entry["author"], "李白")
        self.assertEqual(entry["years"], [736])

    def test_title_variants_remove_editorial_notes_but_keep_group_number(self) -> None:
        annotated = jsp.souyun_title_variants("重题郑氏东亭 （原注：在新安界。） ①")
        self.assertIn(normalize_title("重题郑氏东亭"), annotated)
        grouped = jsp.souyun_title_variants("秋浦歌（其十五）")
        self.assertNotIn(normalize_title("秋浦歌"), grouped)


class SouyunCollectTests(unittest.TestCase):
    def setUp(self) -> None:
        self.index = jsp.build_poem_index()
        self.client = FakeClient(html=fixture_text("souyun_author_page.html"), status="ok")

    def test_collects_only_same_author_exact_matches(self) -> None:
        candidates, status = jsp.collect_souyun("李白", self.client, max_pages=1, poem_index=self.index, transport="html")
        self.assertEqual(status["status"], "collected")
        self.assertEqual(status["pages_requested"], 1)
        self.assertEqual(status["pages_completed"], 1)
        self.assertNotIn("failed_page", status)
        self.assertEqual(len(candidates), 3)
        titles = {row["poem_title"] for row in candidates}
        self.assertEqual(titles, {"金陵酒肆留别", "清平调·其一", "秋浦歌十七首·十五"})
        for row in candidates:
            self.assertEqual(row["source_grade"], "C")
            self.assertEqual(row["status"], "needs_review")
            self.assertEqual(row["license"], "")
            self.assertTrue(row["body_hash"])
            self.assertTrue(row["linked"])
            self.assertEqual(row["source_title_ambiguous"], False)
            self.assertTrue(row["souyun_work_id"])
            self.assertTrue(row["source_url"])
            self.assertTrue(row["source_note"])

    def test_first_page_is_zero_based(self) -> None:
        jsp.collect_souyun("李白", self.client, max_pages=1, poem_index=self.index, transport="html")
        self.assertEqual(
            self.client.requests[0],
            "https://www.sou-yun.cn/PoemIndex.aspx?author=15188&page=0",
        )

    def test_multi_page_collection(self) -> None:
        page0 = fixture_text("souyun_author_page.html")
        page1 = (
            '<div class="poemTitle showDetail">'
            '<a href="Query.aspx?type=poem&amp;id=777">将进酒</a>'
            '<span class="author">李白</span>'
            '<span class="showTime">（天宝十一载，752年）</span></div>'
        )
        client = ScriptedPageClient([("ok", page0), ("ok", page1)])
        candidates, status = jsp.collect_souyun("李白", client, max_pages=2, poem_index=self.index, transport="html")
        self.assertEqual(client.requests[0], "https://www.sou-yun.cn/PoemIndex.aspx?author=15188&page=0")
        self.assertEqual(client.requests[1], "https://www.sou-yun.cn/PoemIndex.aspx?author=15188&page=1")
        self.assertEqual(status["status"], "collected")
        self.assertEqual(status["pages_requested"], 2)
        self.assertEqual(status["pages_completed"], 2)
        self.assertEqual(len(candidates), 4)
        self.assertIn("将进酒", {row["poem_title"] for row in candidates})

    def test_partial_failure_keeps_earlier_candidates_but_not_collected(self) -> None:
        page0 = fixture_text("souyun_author_page.html")
        client = ScriptedPageClient([("ok", page0), ("fetch_failed", "")], note="HTTP 500 on page 2")
        candidates, status = jsp.collect_souyun("李白", client, max_pages=2, poem_index=self.index, transport="html")
        self.assertEqual(status["status"], "partial")
        self.assertEqual(status["pages_requested"], 2)
        self.assertEqual(status["pages_completed"], 1)
        self.assertEqual(status["failed_page"], 2)
        self.assertIn("HTTP 500", status["note"])
        self.assertEqual(len(candidates), 3)
        self.assertEqual({row["poem_title"] for row in candidates}, {"金陵酒肆留别", "清平调·其一", "秋浦歌十七首·十五"})

    def test_first_page_failure_preserves_original_status(self) -> None:
        client = ScriptedPageClient([("offline_cache_miss", "")], note="offline")
        candidates, status = jsp.collect_souyun("李白", client, max_pages=2, poem_index=self.index, transport="html")
        self.assertEqual(candidates, [])
        self.assertEqual(status["status"], "offline_cache_miss")
        self.assertEqual(status["pages_requested"], 2)
        self.assertEqual(status["pages_completed"], 0)
        self.assertEqual(status["failed_page"], 1)
        self.assertIn("offline", status["note"])

    def test_year_month_precision_and_years(self) -> None:
        candidates, _ = jsp.collect_souyun("李白", self.client, max_pages=1, poem_index=self.index, transport="html")
        by_title = {row["poem_title"]: row for row in candidates}
        self.assertEqual(by_title["金陵酒肆留别"]["year_start"], 726)
        self.assertEqual(by_title["金陵酒肆留别"]["year_end"], 726)
        self.assertEqual(by_title["金陵酒肆留别"]["precision"], "year_month")
        self.assertEqual(by_title["金陵酒肆留别"]["year_precision"], "exact")
        self.assertEqual(by_title["清平调·其一"]["year_start"], 743)
        self.assertEqual(by_title["清平调·其一"]["precision"], "year")
        self.assertEqual(by_title["清平调·其一"]["year_precision"], "approximate")
        self.assertEqual(by_title["秋浦歌十七首·十五"]["year_start"], 754)

    def test_no_year_and_subtitle_entries_never_mismatch(self) -> None:
        candidates, status = jsp.collect_souyun("李白", self.client, max_pages=1, poem_index=self.index, transport="html")
        notes = status["note"]
        self.assertIn("no_year:1", notes)
        self.assertIn("unmatched:2", notes)
        self.assertNotIn("静夜思", {row["poem_title"] for row in candidates})
        self.assertNotIn("秋浦歌", {row["poem_title"] for row in candidates})
        self.assertNotIn("其二", {row["poem_title"] for row in candidates})

    def test_bare_subtitle_without_context_cannot_match_real_index(self) -> None:
        entries = [
            {
                "work_id": "1",
                "title": "其二",
                "author": "李白",
                "years": [759],
                "precision": "year",
                "raw_text": "其二",
            }
        ]
        candidates, skips = jsp._souyun_page_candidates("李白", entries, self.index, "ck", "url")
        self.assertEqual(candidates, [])
        self.assertEqual(skips["unmatched"], 1)

    def test_ambiguous_duplicate_title_yields_no_candidate(self) -> None:
        index = {"杜甫": {normalize_title("绝句"): [sample_poem(poet="杜甫", title="绝句"), sample_poem(poet="杜甫", title="绝句")]}}
        entries = [
            {"work_id": "e1", "title": "绝句", "author": "杜甫", "years": [764], "precision": "year", "raw_text": "绝句"}
        ]
        candidates, skips = jsp._souyun_page_candidates("杜甫", entries, index, "ck", "url")
        self.assertEqual(candidates, [])
        self.assertEqual(skips["ambiguous"], 1)

    def test_author_mismatch_is_skipped(self) -> None:
        entries = [
            {"work_id": "e1", "title": "关山月", "author": "陆游", "years": [764], "precision": "year", "raw_text": "关山月"}
        ]
        candidates, skips = jsp._souyun_page_candidates("李白", entries, self.index, "ck", "url")
        self.assertEqual(candidates, [])
        self.assertEqual(skips["author_mismatch"], 1)

    def test_editorial_title_note_matches_only_exact_clean_variant(self) -> None:
        poem = sample_poem(poet="杜甫", author="杜甫", title="重题郑氏东亭", body_hash="dufu-note")
        index = {"杜甫": {normalize_title("重题郑氏东亭"): [poem]}}
        entries = [{
            "work_id": "e-note",
            "title": "重题郑氏东亭 （原注：在新安界。） ①",
            "author": "杜甫",
            "years": [759],
            "precision": "year",
            "raw_text": "重题郑氏东亭 （原注：在新安界。） ① （759年） 唐 · 杜甫",
        }]
        candidates, skips = jsp._souyun_page_candidates("杜甫", entries, index, "ck", "url")
        self.assertEqual(skips, {})
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["poem_title"], "重题郑氏东亭")
        self.assertEqual(candidates[0]["source_title"], entries[0]["title"])


class SouyunApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.index = jsp.build_poem_index()
        self.registry = {
            "poet": "李白",
            "dynasty": "Tang",
            "souyun": {"author_id": 15188},
        }

    def payload(self, title: str, work_id: int, year: str, *, count: int, page: int, size: int = 1) -> dict[str, object]:
        return {
            "Authors": {"Names": ["李白"], "AuthorIds": [15188], "Dynasties": ["Tang"]},
            "ShiData": [
                {
                    "Id": work_id,
                    "Dynasty": "盛唐",
                    "Author": "李白",
                    "AuthorId": 15188,
                    "AuthorDate": year,
                    "AuthorPlace": "CN3201",
                    "Type": "古体诗",
                    "TypeDetail": "GuTi",
                    "Rhyme": "文",
                    "Rank": 1,
                    "Title": {"Content": title},
                    "Clauses": [{"Content": "测试句。"}],
                    "Comments": [
                        {"Book": "测试诗话", "Content": "短评", "FullPath": "测试诗话/卷一", "IsComment": False}
                    ],
                }
            ],
            "Count": count,
            "PageNo": page,
            "PageSize": size,
        }

    def test_official_api_name_dynasty_identity_and_fields(self) -> None:
        client = ScriptedJsonClient([("ok", 200, self.payload("金陵酒肆留别", 26161, "726年五月", count=1, page=0, size=20))])
        candidates, status = jsp.collect_souyun(
            "李白", client, max_pages=0, poem_index=self.index, registry_entry=self.registry
        )
        self.assertIn("key=%E6%9D%8E%E7%99%BD", client.requests[0])
        self.assertIn("dynasty=Tang", client.requests[0])
        self.assertEqual(status["source_transport"], "official_api")
        self.assertEqual(status["author_id"], 15188)
        self.assertIs(status["identity_verified"], True)
        self.assertEqual(status["verified_author_name"], "李白")
        self.assertEqual(status["verified_dynasty"], "Tang")
        self.assertEqual(status["verified_author_id"], 15188)
        self.assertTrue(status["pagination_complete"])
        self.assertEqual(status["api_count"], 1)
        self.assertEqual(status["works_received"], 1)
        self.assertEqual(len(candidates), 1)
        row = candidates[0]
        self.assertEqual(row["year_start"], 726)
        self.assertEqual(row["precision"], "year_month")
        self.assertEqual(row["souyun_author_place"], "CN3201")
        self.assertEqual(row["souyun_comment_count"], 1)
        self.assertEqual(row["extraction_method"], "souyun_open_poem_api_v1")

    def test_auto_pages_until_count_complete(self) -> None:
        client = ScriptedJsonClient(
            [
                ("ok", 200, self.payload("金陵酒肆留别", 1, "726年", count=2, page=0)),
                ("ok", 200, self.payload("将进酒", 2, "752年", count=2, page=1)),
            ]
        )
        candidates, status = jsp.collect_souyun(
            "李白", client, max_pages=0, poem_index=self.index, registry_entry=self.registry
        )
        self.assertEqual(status["pages_completed"], 2)
        self.assertEqual(status["works_received"], 2)
        self.assertTrue(status["pagination_complete"])
        self.assertEqual(status["stop_reason"], "count_complete")
        self.assertIs(status["identity_verified"], True)
        self.assertEqual({row["poem_title"] for row in candidates}, {"金陵酒肆留别", "将进酒"})

    def test_identity_mismatch_is_rejected(self) -> None:
        payload = self.payload("金陵酒肆留别", 1, "726年", count=1, page=0)
        payload["Authors"] = {"Names": ["李白"], "AuthorIds": [999], "Dynasties": ["Tang"]}
        payload["ShiData"][0]["AuthorId"] = 999  # type: ignore[index]
        candidates, status = jsp.collect_souyun(
            "李白",
            ScriptedJsonClient([("ok", 200, payload)]),
            max_pages=0,
            poem_index=self.index,
            registry_entry=self.registry,
        )
        self.assertEqual(candidates, [])
        self.assertEqual(status["status"], "identity_mismatch")
        self.assertIs(status["identity_verified"], False)

    def test_fuzzy_author_results_distinguish_ambiguity_and_disambiguation_wall(self) -> None:
        ambiguous = {
            "Authors": {"Names": ["王建", "王建"], "AuthorIds": [18501, 19737], "Dynasties": ["Tang", "Tang"]},
            "ShiData": [],
            "Count": 2,
            "PageNo": 0,
            "PageSize": 0,
        }
        wang_registry = {"poet": "王建", "dynasty": "Tang", "souyun": {}}
        _, status = jsp.collect_souyun(
            "王建",
            ScriptedJsonClient([("ok", 200, ambiguous)]),
            max_pages=0,
            poem_index=self.index,
            registry_entry=wang_registry,
        )
        self.assertEqual(status["status"], "identity_ambiguous")
        self.assertIs(status["identity_verified"], False)

        fuzzy = {
            "Authors": {"Names": ["陆游", "陆游妾"], "AuthorIds": [34522, 99999], "Dynasties": ["Song", "Song"]},
            "ShiData": [],
            "Count": 2,
            "PageNo": 0,
            "PageSize": 0,
        }
        lu_registry = {"poet": "陆游", "dynasty": "Song", "souyun": {"author_id": 34522}}
        _, status = jsp.collect_souyun(
            "陆游",
            ScriptedJsonClient([("ok", 200, fuzzy)]),
            max_pages=0,
            poem_index=self.index,
            registry_entry=lu_registry,
        )
        self.assertEqual(status["status"], "discovered_author_id_but_api_requires_disambiguation")
        self.assertEqual(status["api_count_semantics"], "author_candidates")
        self.assertFalse(status["pagination_complete"])
        self.assertIs(status["identity_verified"], False)

    def test_two_consecutive_429_pauses_scope(self) -> None:
        client = ScriptedJsonClient([("fetch_failed", 429, None), ("fetch_failed", 429, None)])
        candidates, status = jsp.collect_souyun(
            "李白", client, max_pages=0, poem_index=self.index, registry_entry=self.registry
        )
        self.assertEqual(candidates, [])
        self.assertEqual(status["status"], "rate_limited")
        self.assertEqual(status["rate_limit_streak"], 2)
        self.assertTrue(status["retry_recommended"])
        self.assertIs(status["identity_verified"], False)

    def test_api_partial_never_marks_identity_verified(self) -> None:
        client = ScriptedJsonClient(
            [("ok", 200, self.payload("金陵酒肆留别", 1, "726年", count=2, page=0))]
        )
        _candidates, status = jsp.collect_souyun(
            "李白", client, max_pages=1, poem_index=self.index, registry_entry=self.registry
        )
        self.assertEqual(status["status"], "partial")
        self.assertIs(status["identity_verified"], False)

    def test_verified_success_status_can_persist_discovery(self) -> None:
        client = ScriptedJsonClient(
            [("ok", 200, self.payload("金陵酒肆留别", 26161, "726年", count=1, page=0, size=20))]
        )
        _candidates, status = jsp.collect_souyun(
            "李白", client, max_pages=0, poem_index=self.index, registry_entry=self.registry
        )
        registry = {
            "poets": [
                {
                    "poet": "李白",
                    "dynasty": "Tang",
                    "souyun": {"status": "name_query", "author_id": None},
                }
            ]
        }
        psr.merge_souyun_discoveries(registry, [status])
        source = registry["poets"][0]["souyun"]
        self.assertEqual(source["status"], "discovered")
        self.assertEqual(source["author_id"], 15188)
        self.assertIs(source["identity_verified"], True)
        self.assertEqual(source["verified_author_name"], "李白")
        self.assertEqual(source["verified_dynasty"], "Tang")

    def test_html_compat_stops_on_empty_and_no_next(self) -> None:
        empty = ScriptedPageClient([("ok", "")])
        _, empty_status = jsp.collect_souyun(
            "李白", empty, max_pages=2, poem_index=self.index, transport="html"
        )
        self.assertEqual(empty_status["stop_reason"], "empty_page")
        self.assertEqual(empty_status["pages_completed"], 1)
        no_next = ScriptedPageClient([("ok", fixture_text("souyun_author_page.html"))])
        _, next_status = jsp.collect_souyun(
            "李白", no_next, max_pages=0, poem_index=self.index, transport="html"
        )
        self.assertEqual(next_status["stop_reason"], "no_next_page")
        self.assertTrue(next_status["pagination_complete"])


class CbdbParseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.payload = fixture_json("cbdb_person.json")

    def test_person_extraction(self) -> None:
        person = jsp.extract_cbdb_person(self.payload)
        self.assertIsNotNone(person)
        assert person is not None
        self.assertEqual(person["person_id"], "32540")
        self.assertEqual(person["name"], "李白")
        self.assertEqual(person["index_year"], "701")
        self.assertEqual(len(person["addresses"]), 5)
        self.assertEqual(len(person["postings"]), 10)

    def test_nested_payload_is_tolerated(self) -> None:
        nested = {"Package": self.payload["Package"]}
        person = jsp.extract_cbdb_person(nested)
        assert person is not None
        self.assertEqual(person["person_id"], "32540")
        self.assertIsNone(jsp.extract_cbdb_person({"Package": {"NoPerson": {}}}))

    def test_year_parsing(self) -> None:
        self.assertEqual(jsp.parse_positive_year("701"), 701)
        self.assertEqual(jsp.parse_positive_year(0), None)
        self.assertEqual(jsp.parse_positive_year("0"), None)
        self.assertEqual(jsp.parse_positive_year(""), None)
        self.assertEqual(jsp.parse_positive_year(None), None)
        self.assertEqual(jsp.parse_positive_year("开元十四年"), None)
        self.assertEqual(jsp.parse_positive_year("726年"), 726)


class CbdbCollectTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = FakeClient(payload=fixture_json("cbdb_person.json"), status="ok")

    def test_collects_addresses_and_postings(self) -> None:
        candidates, status = jsp.collect_cbdb("李白", self.client)
        self.assertEqual(status["status"], "collected")
        self.assertEqual(status["candidates"], 8)
        self.assertEqual(len(candidates), 9)

        residences = [row for row in candidates if row["event_type"] == "residence"]
        postings = [row for row in candidates if row["event_type"] == "posting"]
        self.assertEqual(len(residences), 2)
        self.assertEqual(len(postings), 7)
        self.assertEqual(len({row["candidate_id"] for row in candidates}), 8)

    def test_same_place_year_different_offices_get_distinct_ids(self) -> None:
        candidates, _ = jsp.collect_cbdb("李白", self.client)
        jiangxia_758 = [
            row for row in candidates
            if row["event_type"] == "posting"
            and row["historical_place"] == "江夏"
            and row["year_start"] == 758
            and row["year_end"] == 758
        ]
        unique_rows = {row["candidate_id"]: row for row in jiangxia_758}
        self.assertEqual(len(unique_rows), 2)
        offices = {row["office"] for row in unique_rows.values()}
        self.assertEqual(offices, {"知制诰", "主客郎中"})

    def test_duplicate_record_is_idempotent_and_unique_counted(self) -> None:
        candidates, status = jsp.collect_cbdb("李白", self.client)
        unique_ids = {row["candidate_id"] for row in candidates}
        self.assertEqual(len(candidates), 9)
        self.assertEqual(len(unique_ids), 8)
        self.assertEqual(status["candidates"], 8)
        self.assertIn("raw", status["note"])
        self.assertIn("unique", status["note"])
        # The duplicated 知制诰 record collapses to a single candidate.
        zhizhigao = [row for row in candidates if row.get("office") == "知制诰"]
        self.assertEqual(len({row["candidate_id"] for row in zhizhigao}), 1)
        # Re-collecting an identical response is idempotent.
        second, _ = jsp.collect_cbdb("李白", FakeClient(payload=fixture_json("cbdb_person.json"), status="ok"))
        self.assertEqual({row["candidate_id"] for row in second}, unique_ids)

    def test_unknown_source_pages_never_upgrades_grade(self) -> None:
        candidates, _ = jsp.collect_cbdb("李白", self.client)
        tongzhou = next(row for row in candidates if row["event_type"] == "posting" and row["historical_place"] == "同州")
        # Exact year (835-835) but Page is "未知" -> must stay C, never B.
        self.assertEqual(tongzhou["year_start"], 835)
        self.assertEqual(tongzhou["source_pages"], "未知")
        self.assertEqual(tongzhou["source_grade"], "C")
        self.assertFalse(jsp._meaningful_source_pages("未知"))
        self.assertFalse(jsp._meaningful_source_pages("未詳"))
        self.assertFalse(jsp._meaningful_source_pages("0"))
        self.assertFalse(jsp._meaningful_source_pages(""))
        self.assertFalse(jsp._meaningful_source_pages("unknown"))
        self.assertTrue(jsp._meaningful_source_pages("《新唐书》卷一九五"))

    def test_address_rules(self) -> None:
        candidates, _ = jsp.collect_cbdb("李白", self.client)
        residences = {row["historical_place"]: row for row in candidates if row["event_type"] == "residence"}
        self.assertNotIn("绵州昌隆（今江油）", residences)
        self.assertNotIn("绵州昌隆", residences)
        self.assertNotIn("", residences)

        anlu = residences["安陆"]
        self.assertEqual(anlu["year_start"], 727)
        self.assertEqual(anlu["year_end"], 739)
        self.assertEqual(anlu["year_precision"], "approximate")
        self.assertEqual(anlu["source_grade"], "C")
        self.assertEqual(anlu["cbdb_person_id"], "32540")
        self.assertEqual(anlu["cbdb_addr_id"], "502")

        changan = residences["长安"]
        self.assertEqual(changan["year_start"], 742)
        self.assertEqual(changan["year_end"], 742)
        self.assertEqual(changan["year_precision"], "exact")
        self.assertEqual(changan["source_grade"], "B")
        self.assertTrue(changan["source_pages"])

    def test_address_requires_valid_first_year(self) -> None:
        # 籍贯类记录 FirstYear 为空/0、仅有 LastYear>0 不得成为行旅候选。
        candidates, _ = jsp.collect_cbdb("李白", self.client)
        self.assertEqual({row["historical_place"] for row in candidates if row["event_type"] == "residence"},
                         {"安陆", "长安"})

        native = fixture_json("cbdb_person.json")
        person = jsp.extract_cbdb_person(native)
        assert person is not None
        addresses = person["addresses"]
        for addr in addresses:
            if str(addr.get("AddrName")) == "绵州昌隆":
                self.assertIsNone(jsp.parse_positive_year(addr.get("FirstYear")))

    def test_zero_year_native_place_is_not_a_journey(self) -> None:
        candidates, _ = jsp.collect_cbdb("李白", self.client)
        for row in candidates:
            self.assertNotEqual(row["year_start"], 0)
            self.assertNotEqual(row["year_end"], 0)

    def test_queries_by_fixed_person_id(self) -> None:
        candidates, status = jsp.collect_cbdb("李白", self.client)
        self.assertEqual(status["status"], "collected")
        self.assertEqual(len(self.client.requests), 1)
        url = self.client.requests[0]
        self.assertIn("id=32540", url)
        self.assertNotIn("name=", url)

    def test_identity_mismatch_yields_no_candidates(self) -> None:
        wrong_payload = json.loads(json.dumps(fixture_json("cbdb_person.json")))
        person = wrong_payload["Package"]["PersonAuthority"]["PersonInfo"]["Person"]
        person["BasicInfo"]["ChName"] = "李黑"
        client = FakeClient(payload=wrong_payload, status="ok")
        candidates, status = jsp.collect_cbdb("李白", client)
        self.assertEqual(candidates, [])
        self.assertEqual(status["status"], "identity_mismatch")
        self.assertIn("identity_mismatch", status["note"])

    def test_person_id_mismatch_is_rejected(self) -> None:
        wrong_payload = json.loads(json.dumps(fixture_json("cbdb_person.json")))
        person = wrong_payload["Package"]["PersonAuthority"]["PersonInfo"]["Person"]
        person["BasicInfo"]["PersonId"] = "99999"
        client = FakeClient(payload=wrong_payload, status="ok")
        candidates, status = jsp.collect_cbdb("李白", client)
        self.assertEqual(candidates, [])
        self.assertEqual(status["status"], "identity_mismatch")

    def test_traditional_variant_names_are_accepted(self) -> None:
        self.assertTrue(jsp._ch_name_matches("苏轼", "蘇軾"))
        self.assertTrue(jsp._ch_name_matches("陆游", "陸游"))
        self.assertTrue(jsp._ch_name_matches("李白", "李白"))
        self.assertFalse(jsp._ch_name_matches("李白", "李黑"))

    def test_audited_alias_name_is_accepted_for_fixed_person_id(self) -> None:
        payload = json.loads(json.dumps(fixture_json("cbdb_person.json"), ensure_ascii=False))
        basic = payload["Package"]["PersonAuthority"]["PersonInfo"]["Person"]["BasicInfo"]
        basic["PersonId"] = "93417"
        basic["ChName"] = "张龟龄"
        registry_entry = {
            "cbdb": {
                "status": "audited_unique",
                "person_id": "93417",
                "accepted_names": ["张志和", "张龟龄"],
            }
        }
        _, status = jsp.collect_cbdb(
            "张志和", FakeClient(payload=payload), registry_entry=registry_entry
        )
        self.assertNotEqual(status["status"], "identity_mismatch")

    def test_posting_rules_filter_unknown_places(self) -> None:
        candidates, _ = jsp.collect_cbdb("李白", self.client)
        postings = [row for row in candidates if row["event_type"] == "posting"]
        places = {row["historical_place"] for row in postings}
        self.assertEqual(places, {"长安", "渝州", "江夏", "同州"})

        changan = next(row for row in postings if row["historical_place"] == "长安")
        self.assertEqual(changan["year_start"], 742)
        self.assertEqual(changan["year_end"], 744)
        self.assertEqual(changan["year_precision"], "approximate")
        self.assertEqual(changan["source_grade"], "C")

        jiangxia = next(row for row in postings if row["historical_place"] == "江夏")
        self.assertEqual(jiangxia["source_grade"], "B")
        self.assertEqual(jiangxia["year_precision"], "exact")

        yuzhou = next(row for row in postings if row["historical_place"] == "渝州")
        self.assertEqual(yuzhou["source_grade"], "C")

    def test_common_fields(self) -> None:
        candidates, _ = jsp.collect_cbdb("李白", self.client)
        for row in candidates:
            self.assertEqual(row["status"], "needs_review")
            self.assertEqual(row["access_level"], "open_api")
            self.assertEqual(row["license"], "CC BY-NC-SA 4.0")
            self.assertEqual(row["source"], "cbdb")
            self.assertTrue(row["raw_cache_key"])

    def test_fetch_failure_records_status(self) -> None:
        client = FakeClient(payload=None, status="fetch_failed", note="HTTP 500")
        candidates, status = jsp.collect_cbdb("李白", client)
        self.assertEqual(candidates, [])
        self.assertEqual(status["status"], "fetch_failed")


class CnkgraphTests(unittest.TestCase):
    def bio_payload(self) -> dict[str, object]:
        return {
            "Biography": {
                "Name": "李白",
                "Id": 15188,
                "Activities": [
                    {
                        "Year": 725,
                        "Month": "春",
                        "OldYear": "开元十三年",
                        "Place": {"Province": "湖北", "City": "荆州", "Place": "荆门"},
                        "Activity": "初出蜀，沿江东下",
                    },
                    {
                        "Year": 742,
                        "Month": "秋",
                        "Place": {"Province": "陕西", "City": "长安"},
                        "Title": "翰林供奉",
                        "Activity": "应诏入京",
                    },
                    {
                        "Year": 755,
                        "Poems": [
                            {"Title": "赠汪伦", "Author": "李白", "AuthorDate": "天宝十四载"},
                            {"Title": "秋浦歌十七首", "Author": "李白", "AuthorDate": "天宝十三载"},
                        ],
                    },
                    {"Activity": "无年份活动", "Place": {"City": "扬州"}},
                    {"Year": 0, "Place": {"City": "某地"}},
                    {"Year": 99999, "Place": {"City": "某地"}},
                ],
            }
        }

    def test_biography_targeted_extraction(self) -> None:
        bio, events, works = jsp.extract_cnkgraph_biography(self.bio_payload())
        assert isinstance(bio, dict)
        self.assertEqual(len(events), 2)
        self.assertEqual(len(works), 2)
        self.assertEqual({ev["year_start"] for ev in events}, {725, 742})
        self.assertEqual({ev["historical_place"] for ev in events}, {"湖北·荆州·荆门", "陕西·长安"})
        self.assertEqual({w["poem_title"] for w in works}, {"赠汪伦", "秋浦歌十七首"})

    def test_same_year_place_distinct_activities_get_distinct_ids(self) -> None:
        payload = {"Biography": {"Name": "李白", "Id": 15188, "Activities": [
            {"Year": 725, "Place": {"City": "荆州"}, "Activity": "初出蜀，沿江东下"},
            {"Year": 725, "Place": {"City": "荆州"}, "Activity": "游荆门，会友人"},
        ]}}
        candidates, status = jsp.collect_cnkgraph("李白", FakeClient(payload=payload))
        self.assertEqual(status["status"], "collected")
        events = [row for row in candidates if row["event_type"] == "person_event"]
        self.assertEqual(len(events), 2)
        self.assertEqual(len({row["candidate_id"] for row in events}), 2)
        # Identical response is idempotent.
        second, _ = jsp.collect_cnkgraph("李白", FakeClient(payload=payload))
        self.assertEqual(
            {row["candidate_id"] for row in second if row["event_type"] == "person_event"},
            {row["candidate_id"] for row in events},
        )

    def test_work_chronology_never_carries_place(self) -> None:
        candidates, status = jsp.collect_cnkgraph("李白", FakeClient(payload=self.bio_payload()))
        self.assertEqual(status["status"], "collected")
        works = [row for row in candidates if row["event_type"] == "work_chronology"]
        events = [row for row in candidates if row["event_type"] == "person_event"]
        self.assertEqual(len(works), 2)
        self.assertEqual(len(events), 2)
        self.assertTrue(all(not row["historical_place"] for row in works))
        self.assertTrue(all(row["source_grade"] == "B" for row in candidates))
        self.assertTrue(all(row["status"] == "needs_review" for row in candidates))
        self.assertTrue(all(row["license"] == "" for row in candidates))

    def test_real_candidate_builders_use_registry_cnkgraph_metadata(self) -> None:
        request_url = "fixture://cnkgraph/response?Author=李白"
        event = jsp.make_cnkgraph_event_candidate(
            "李白",
            {
                "year_start": 742,
                "year_end": 742,
                "historical_place": "陕西·长安",
                "event_text": "应诏入京",
                "grade": "B",
            },
            15188,
            "event-cache",
            request_url,
        )
        work = jsp.make_cnkgraph_work_candidate(
            "李白",
            {
                "year_start": 755,
                "year_end": 755,
                "poem_title": "赠汪伦",
                "source_author": "李白",
                "grade": "B",
            },
            15188,
            "work-cache",
            request_url,
        )
        fields = ("source_url", "access_level", "source_grade", "license", "license_note")
        self.assertNotEqual(request_url, psr.CNKGRAPH_SOURCE_METADATA["source_url"])
        for candidate in (event, work):
            with self.subTest(event_type=candidate["event_type"]):
                self.assertEqual(
                    {field: candidate[field] for field in fields},
                    {field: psr.CNKGRAPH_SOURCE_METADATA[field] for field in fields},
                )

    def test_work_candidates_link_body_hash_by_unique_title(self) -> None:
        candidates, _ = jsp.collect_cnkgraph("李白", FakeClient(payload=self.bio_payload()))
        works = {row["poem_title"]: row for row in candidates if row["event_type"] == "work_chronology"}
        self.assertEqual(works["赠汪伦"]["linked"], True)
        self.assertTrue(works["赠汪伦"]["body_hash"])
        self.assertEqual(works["秋浦歌十七首"]["linked"], True)
        self.assertTrue(works["秋浦歌十七首"]["body_hash"])

    def test_unmatched_work_is_marked_unlinked(self) -> None:
        payload = {"Biography": {"Name": "李白", "Id": 15188, "Activities": [
            {"Year": 760, "Poems": [{"Title": "无此题目存在"}]}
        ]}}
        candidates, _ = jsp.collect_cnkgraph("李白", FakeClient(payload=payload))
        works = [row for row in candidates if row["event_type"] == "work_chronology"]
        self.assertEqual(len(works), 1)
        self.assertEqual(works[0]["linked"], False)
        self.assertEqual(works[0]["body_hash"], "")
        self.assertEqual(works[0]["historical_place"], "")
        self.assertIn("unlinked", works[0]["source_note"])

    def test_recursive_fallback_candidates_are_grade_c(self) -> None:
        payload = {"Nested": [
            {"Year": 725, "Place": {"City": "荆州"}},
            {"Year": 760, "Subject": "绝句"},
        ]}
        candidates, status = jsp.collect_cnkgraph("李白", FakeClient(payload=payload))
        self.assertEqual(status["status"], "collected")
        self.assertTrue(candidates)
        self.assertTrue(all(row["source_grade"] == "C" for row in candidates))
        self.assertTrue(
            all(row["extraction_method"] == "cnkgraph_biography_recursive_v1" for row in candidates)
        )
        self.assertTrue(all(row["license"] == "" for row in candidates))

    def test_204_and_timeout_are_recorded_not_fatal(self) -> None:
        no_content = FakeClient(payload=None, status="parse_failed", status_code=204, note="HTTP 204")
        candidates, status = jsp.collect_cnkgraph("李白", no_content)
        self.assertEqual(candidates, [])
        self.assertEqual(status["status"], "not_covered")
        self.assertEqual(status["writing_stat_status"], "not_covered")

        timeout = FakeClient(payload=None, status="fetch_failed", note="timeout after retries")
        candidates, status = jsp.collect_cnkgraph("李白", timeout)
        self.assertEqual(candidates, [])
        self.assertEqual(status["status"], "fetch_failed")

        blocked = FakeClient(payload=None, status="blocked_by_policy", note="login page")
        candidates, status = jsp.collect_cnkgraph("李白", blocked)
        self.assertEqual(candidates, [])
        self.assertEqual(status["status"], "blocked_by_policy")

    def test_recursive_extractor_is_conservative(self) -> None:
        payload = {"some": {"list": [{"Year": 725, "Place": {"City": "荆州"}}, {"Year": 0, "Place": "某地"}]}}
        events, works = jsp.recursive_cnkgraph_extract(payload)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["historical_place"], "荆州")
        self.assertEqual(events[0]["grade"], "C")
        self.assertEqual(works, [])


class CnkgraphTraceTests(unittest.TestCase):
    """Offline tests for the real Biography Traces/Markers/Detail payload."""

    def marker_detail(self) -> str:
        return (
            "<div class='label1' id='a1_label'>"
            "<a href=\"javascript: ViewDetail('scope=&author=&beginYear=1036&endYear=1054')\">1036-1054年</a>，1-19岁"
            "</div>"
            "<div id='a1' class='detail'>"
            "<a href=\"javascript: ViewDetail('scope=&author=&beginYear=1036&endYear=1036')\">1036年</a>　苏轼生于眉山县纱縠行。<br />"
            "<a href=\"javascript: ViewDetail('scope=&author=&beginYear=1042&endYear=1042')\">1042年</a>　苏轼始读书。<br />"
            "<a href=\"javascript: ViewDetail('scope=&author=&beginYear=1044&endYear=1046')\">1044-1046年</a>　在眉山。作《题西林壁》。"
            "<div id='poem_9' class='_poem'><div id='poem_title_9' class='poemTitle showDetail'>"
            "<a href='/Writing/300123?labeling=true' target='_blank'>题西林壁</a>"
            "<span class='authorDate'>（1084年）</span>"
            "<span class='poemAuthor'><a href='javascript: ShowPoemAuthorProfile(29937, \"北宋\", \"苏轼\", \"poem_title_9\")'>苏轼</a></span>"
            "</div></div><br />"
            "<a href=\"javascript: ViewDetail('scope=&author=&beginYear=1045&endYear=1045')\">1045年</a>　苏洵命轼作《夏侯太初论》。"
            "<div id='poem_1' class='_poem'><div id='poem_title_1' class='poemTitle showDetail'>"
            "<a href='/Writing/1189518?labeling=true' target='_blank'>夏侯太初论</a>"
            "<span class='authorDate'>（1045年）</span>"
            "<span class='poemAuthor'><a href='javascript: ShowPoemAuthorProfile(29937, \"北宋\", \"苏轼\", \"poem_title_1\")'>苏轼</a></span>"
            "</div></div><br />"
            "</div>"
            "<div class='label1' id='a2_label'>"
            "<a href=\"javascript: ViewDetail('scope=&author=&beginYear=1055&endYear=1056')\">1055-1056年</a>，20-21岁"
            "</div>"
            "<div id='a2' class='detail'>"
            "<a href=\"javascript: ViewDetail('scope=&author=&beginYear=1055&endYear=1056')\">1055-1056年</a>　在家居丧。<br />"
            "</div>"
        )

    def trace_payload(self) -> dict[str, object]:
        return {
            "Common": None,
            "Title": "苏轼",
            "Traces": [
                {
                    "Center": None,
                    "Markers": [
                        {
                            "Id": None,
                            "Title": "眉山 (出生地)",
                            "RegionId": "CN5114",
                            "Latitude": 30.08,
                            "Longitude": 103.85,
                            "Detail": self.marker_detail(),
                        }
                    ],
                    "Lines": [
                        {
                            "Title": None,
                            "Detail": None,
                            "Markers": [
                                {
                                    "Id": None,
                                    "Title": "伪路线点",
                                    "RegionId": "X",
                                    "Latitude": 1.0,
                                    "Longitude": 2.0,
                                    "Detail": (
                                        "<div class='detail'>"
                                        "<a href=\"javascript: ViewDetail('scope=&author=&beginYear=999&endYear=999')\">999年</a>　这不是行旅史实。<br />"
                                        "</div>"
                                    ),
                                }
                            ],
                        }
                    ],
                }
            ],
        }

    def author_mix_detail(self) -> str:
        return (
            "<div class='label1' id='a1_label'>"
            "<a href=\"javascript: ViewDetail('scope=&author=&beginYear=1055&endYear=1055')\">1055年</a>，20岁"
            "</div>"
            "<div id='a1' class='detail'>"
            "<a href=\"javascript: ViewDetail('scope=&author=&beginYear=1055&endYear=1055')\">1055年</a>　在眉山。"
            "<div id='poem_a' class='_poem'><div id='poem_title_a' class='poemTitle showDetail'>"
            "<a href='/Writing/300123?labeling=true' target='_blank'>题西林壁</a>"
            "<span class='authorDate'>（1084年）</span>"
            "<span class='poemAuthor'><a href='javascript: ShowPoemAuthorProfile(29937, \"北宋\", \"苏轼\", \"poem_title_a\")'>苏轼</a></span>"
            "</div></div>"
            "<div id='poem_b' class='_poem'><div id='poem_title_b' class='poemTitle showDetail'>"
            "<a href='/Writing/200456?labeling=true' target='_blank'>和子由渑池怀旧</a>"
            "<span class='authorDate'>（1056年）</span>"
            "</div></div>"
            "<div id='poem_c' class='_poem'><div id='poem_title_c' class='poemTitle showDetail'>"
            "<a href='/Writing/200457?labeling=true' target='_blank'>念奴娇·赤壁怀古</a>"
            "<span class='authorDate'>（1082年）</span>"
            "<span class='poemAuthor'><a href='javascript: ShowPoemAuthorProfile(29937, \"北宋\", \"蘇軾\", \"poem_title_c\")'>蘇軾</a></span>"
            "</div></div>"
            "<div id='poem_d' class='_poem'><div id='poem_title_d' class='poemTitle showDetail'>"
            "<a href='/Writing/300789?labeling=true' target='_blank'>夜泊荆溪</a>"
            "<span class='authorDate'>（729年）</span>"
            "<span class='poemAuthor'><a href='javascript: ShowPoemAuthorProfile(9999, \"唐\", \"张说\", \"poem_title_d\")'>张说</a></span>"
            "</div></div>"
            "<br />"
            "</div>"
        )

    def author_mix_payload(self) -> dict[str, object]:
        return {
            "Traces": [
                {
                    "Markers": [
                        {
                            "Id": None,
                            "Title": "眉山 (出生地)",
                            "RegionId": "CN5114",
                            "Latitude": 30.08,
                            "Longitude": 103.85,
                            "Detail": self.author_mix_detail(),
                        }
                    ]
                }
            ]
        }

    def collect(self, payload: dict[str, object]) -> tuple[list[dict[str, object]], dict[str, object]]:
        return jsp.collect_cnkgraph("苏轼", FakeClient(payload=payload))

    def test_other_author_poems_are_filtered(self) -> None:
        candidates, _ = self.collect(self.author_mix_payload())
        works = {row["source_title"]: row for row in candidates if row["event_type"] == "work_chronology"}
        # 张说's poem (year 729) is clearly a different author -> dropped.
        self.assertNotIn("夜泊荆溪", works)
        self.assertNotIn(729, {row["year_start"] for row in works.values()})
        self.assertEqual(set(works), {"题西林壁", "和子由渑池怀旧", "念奴娇·赤壁怀古"})
        self.assertEqual(works["题西林壁"]["source_author"], "苏轼")
        self.assertEqual(works["和子由渑池怀旧"]["source_author"], "")
        self.assertEqual(works["念奴娇·赤壁怀古"]["source_author"], "蘇軾")
        self.assertIn("作者未标注", works["和子由渑池怀旧"]["source_note"])
        # Traditional-variant 蘇軾 still matches the target 苏轼.
        self.assertTrue(works["念奴娇·赤壁怀古"]["linked"])
        self.assertTrue(works["念奴娇·赤壁怀古"]["body_hash"])

    def test_source_same_title_multiple_works_not_linked(self) -> None:
        detail = (
            "<div class='label1' id='a1_label'>"
            "<a href=\"javascript: ViewDetail('scope=&author=&beginYear=1050&endYear=1050')\">1050年</a>，14岁"
            "</div>"
            "<div id='a1' class='detail'>"
            "<a href=\"javascript: ViewDetail('scope=&author=&beginYear=1050&endYear=1050')\">1050年</a>　作杂兴。"
            "<div id='poem_a' class='_poem'><div id='poem_title_a' class='poemTitle showDetail'>"
            "<a href='/Writing/700001?labeling=true' target='_blank'>杂兴</a>"
            "<span class='authorDate'>（1050年）</span>"
            "<span class='poemAuthor'><a href='javascript: ShowPoemAuthorProfile(3640, \"南宋\", \"陆游\", \"poem_title_a\")'>陆游</a></span>"
            "</div></div>"
            "<a href=\"javascript: ViewDetail('scope=&author=&beginYear=1051&endYear=1051')\">1051年</a>　又作杂兴。"
            "<div id='poem_b' class='_poem'><div id='poem_title_b' class='poemTitle showDetail'>"
            "<a href='/Writing/700002?labeling=true' target='_blank'>杂兴</a>"
            "<span class='authorDate'>（1051年）</span>"
            "<span class='poemAuthor'><a href='javascript: ShowPoemAuthorProfile(3640, \"南宋\", \"陆游\", \"poem_title_b\")'>陆游</a></span>"
            "</div></div>"
            "<a href=\"javascript: ViewDetail('scope=&author=&beginYear=1173&endYear=1173')\">1173年</a>　作关山月。"
            "<div id='poem_c' class='_poem'><div id='poem_title_c' class='poemTitle showDetail'>"
            "<a href='/Writing/700003?labeling=true' target='_blank'>关山月</a>"
            "<span class='authorDate'>（1173年）</span>"
            "<span class='poemAuthor'><a href='javascript: ShowPoemAuthorProfile(3640, \"南宋\", \"陆游\", \"poem_title_c\")'>陆游</a></span>"
            "</div></div>"
            "<br />"
            "</div>"
        )
        payload = {"Traces": [{"Markers": [{"Title": "山阴", "RegionId": "R1", "Detail": detail}]}]}
        candidates, status = jsp.collect_cnkgraph("陆游", FakeClient(payload=payload))
        self.assertEqual(status["status"], "collected")
        works = {row["writing_id"]: row for row in candidates if row["event_type"] == "work_chronology"}
        self.assertEqual(set(works), {"700001", "700002", "700003"})
        zaxing_a, zaxing_b = works["700001"], works["700002"]
        self.assertEqual(zaxing_a["source_title"], "杂兴")
        self.assertEqual(zaxing_a["linked"], False)
        self.assertEqual(zaxing_a["body_hash"], "")
        self.assertEqual(zaxing_a["source_title_ambiguous"], True)
        self.assertIn("源端同题多作", zaxing_a["source_note"])
        self.assertEqual(zaxing_b["linked"], False)
        self.assertEqual(zaxing_b["source_title_ambiguous"], True)
        # Multiple same-title source works stay as separate candidates (writing_id).
        self.assertNotEqual(zaxing_a["candidate_id"], zaxing_b["candidate_id"])
        guanshan = works["700003"]
        self.assertEqual(guanshan["linked"], True)
        self.assertTrue(guanshan["body_hash"])
        self.assertEqual(guanshan["source_title_ambiguous"], False)

    def test_structure_recognized_and_grade_b(self) -> None:
        self.assertTrue(jsp._has_trace_structure(self.trace_payload()))
        candidates, status = self.collect(self.trace_payload())
        self.assertEqual(status["status"], "collected")
        self.assertTrue(candidates)
        self.assertTrue(all(row["source_grade"] == "B" for row in candidates))
        self.assertTrue(all(row["extraction_method"] == "cnkgraph_biography_traces_v1" for row in candidates))
        self.assertTrue(all(row["license"] == "" for row in candidates))

    def test_multiple_year_blocks_and_embedded_poems(self) -> None:
        candidates, _ = self.collect(self.trace_payload())
        events = [row for row in candidates if row["event_type"] == "person_event"]
        works = [row for row in candidates if row["event_type"] == "work_chronology"]
        self.assertEqual(len(events), 5)
        self.assertEqual(
            {(row["year_start"], row["year_end"]) for row in events},
            {(1036, 1036), (1042, 1042), (1044, 1046), (1045, 1045), (1055, 1056)},
        )
        self.assertEqual({row["historical_place"] for row in events}, {"眉山 (出生地)"})
        self.assertEqual(len({row["candidate_id"] for row in events}), 5)

        by_title = {row["poem_title"]: row for row in works}
        self.assertEqual(set(by_title), {"题西林壁", "夏侯太初论"})
        xiling = by_title["题西林壁"]
        self.assertEqual(xiling["year_start"], 1084)
        self.assertEqual(xiling["writing_id"], "300123")
        self.assertEqual(xiling["linked"], True)
        self.assertTrue(xiling["body_hash"])
        self.assertEqual(xiling["source_title"], "题西林壁")
        xiahou = by_title["夏侯太初论"]
        self.assertEqual(xiahou["year_start"], 1045)
        self.assertEqual(xiahou["writing_id"], "1189518")
        self.assertEqual(xiahou["linked"], False)
        self.assertEqual(xiahou["body_hash"], "")

    def test_work_never_inherits_marker_place(self) -> None:
        candidates, _ = self.collect(self.trace_payload())
        works = [row for row in candidates if row["event_type"] == "work_chronology"]
        self.assertTrue(works)
        self.assertTrue(all(row["historical_place"] == "" for row in works))

    def test_event_source_locator_and_region(self) -> None:
        candidates, _ = self.collect(self.trace_payload())
        event = next(row for row in candidates if row["event_type"] == "person_event")
        self.assertIn("Marker[0|CN5114|眉山 (出生地)]", event["source_pages"])
        self.assertIn("label=a1", event["source_pages"])
        self.assertIn("row=0", event["source_pages"])
        self.assertIn("1036", event["source_pages"])
        self.assertEqual(event["region_id"], "CN5114")
        self.assertEqual(event["latitude"], 30.08)
        self.assertEqual(event["longitude"], 103.85)

    def test_parse_marker_detail_label_blocks(self) -> None:
        rows = jsp.parse_marker_detail(self.marker_detail())
        self.assertEqual(len(rows), 5)
        self.assertEqual(rows[0]["label_id"], "a1")
        self.assertEqual(rows[0]["begin"], 1036)
        self.assertEqual(rows[0]["row_index"], 0)
        self.assertEqual(rows[4]["label_id"], "a2")
        self.assertEqual(rows[4]["begin"], 1055)
        self.assertEqual(rows[4]["row_index"], 4)
        self.assertTrue(rows[0]["event_hash"])

    def test_lines_only_payload_never_falls_back(self) -> None:
        line_detail = (
            "<div class='label1' id='l1_label'>"
            "<a href=\"javascript: ViewDetail('scope=&author=&beginYear=999&endYear=999')\">999年</a>"
            "</div>"
            "<div id='l1' class='detail'>"
            "<a href=\"javascript: ViewDetail('scope=&author=&beginYear=999&endYear=999')\">999年</a>　路线点事件。<br />"
            "</div>"
        )
        payload = {
            "Traces": [
                {
                    "Markers": [],
                    "Lines": [{"Markers": [{"Title": "路线点", "RegionId": "X", "Latitude": 1.0, "Longitude": 2.0, "Detail": line_detail}]}],
                }
            ]
        }
        candidates, status = jsp.collect_cnkgraph("苏轼", FakeClient(payload=payload))
        self.assertEqual(candidates, [])
        self.assertEqual(status["status"], "empty")

    def test_isolated_detail_and_incomplete_years_produce_nothing(self) -> None:
        def collect(detail: str) -> list[dict[str, object]]:
            payload = {"Traces": [{"Markers": [{"Title": "某地", "RegionId": "R1", "Latitude": 30.0, "Longitude": 103.0, "Detail": detail}]}]}
            candidates, _ = jsp.collect_cnkgraph("苏轼", FakeClient(payload=payload))
            return [c for c in candidates if c["event_type"] == "person_event"]

        isolated = "<div class='detail'><a href=\"javascript: ViewDetail('scope=&author=&beginYear=1000&endYear=1000')\">1000年</a>　孤立详情。<br /></div>"
        self.assertEqual(collect(isolated), [])

        label_no_end = (
            "<div class='label1' id='l1_label'>"
            "<a href=\"javascript: ViewDetail('scope=&author=&beginYear=1000')\">1000年</a>"
            "</div>"
            "<div id='l1' class='detail'>"
            "<a href=\"javascript: ViewDetail('scope=&author=&beginYear=1001&endYear=1001')\">1001年</a>　正常行。<br />"
            "</div>"
        )
        self.assertEqual(collect(label_no_end), [])

        row_no_end = (
            "<div class='label1' id='l1_label'>"
            "<a href=\"javascript: ViewDetail('scope=&author=&beginYear=1000&endYear=1000')\">1000年</a>"
            "</div>"
            "<div id='l1' class='detail'>"
            "<a href=\"javascript: ViewDetail('scope=&author=&beginYear=1001')\">1001年</a>　只有开始年。<br />"
            "</div>"
        )
        self.assertEqual(collect(row_no_end), [])

    def test_person_event_requires_summary_title_region_and_coords(self) -> None:
        row = "<a href=\"javascript: ViewDetail('scope=&author=&beginYear=1050&endYear=1050')\">1050年</a>　苏轼在眉山读书。<br />"
        block = (
            "<div class='label1' id='l1_label'>"
            "<a href=\"javascript: ViewDetail('scope=&author=&beginYear=1050&endYear=1050')\">1050年</a>"
            "</div>"
            f"<div id='l1' class='detail'>{row}</div>"
        )

        def events(payload: dict[str, object]) -> list[dict[str, object]]:
            candidates, _ = jsp.collect_cnkgraph("苏轼", FakeClient(payload=payload))
            return [c for c in candidates if c["event_type"] == "person_event"]

        no_region = {"Traces": [{"Markers": [{"Title": "眉山", "Latitude": 30.0, "Longitude": 103.0, "Detail": block}]}]}
        self.assertEqual(events(no_region), [])
        no_coords = {"Traces": [{"Markers": [{"Title": "眉山", "RegionId": "CN5114", "Detail": block}]}]}
        self.assertEqual(events(no_coords), [])
        no_title = {"Traces": [{"Markers": [{"RegionId": "CN5114", "Latitude": 30.0, "Longitude": 103.0, "Detail": block}]}]}
        self.assertEqual(events(no_title), [])

    def test_poem_only_row_produces_work_but_no_event(self) -> None:
        detail = (
            "<div class='label1' id='l1_label'>"
            "<a href=\"javascript: ViewDetail('scope=&author=&beginYear=1082&endYear=1082')\">1082年</a>"
            "</div>"
            "<div id='l1' class='detail'>"
            "<a href=\"javascript: ViewDetail('scope=&author=&beginYear=1082&endYear=1082')\">1082年</a>　"
            "<div id='poem_9' class='_poem'><div id='poem_title_9' class='poemTitle showDetail'>"
            "<a href='/Writing/200457?labeling=true' target='_blank'>念奴娇·赤壁怀古</a>"
            "<span class='authorDate'>（1082年）</span>"
            "<span class='poemAuthor'><a href='javascript: ShowPoemAuthorProfile(29937, \"北宋\", \"苏轼\", \"poem_title_9\")'>苏轼</a></span>"
            "</div></div><br />"
            "</div>"
        )
        payload = {"Traces": [{"Markers": [{"Title": "眉山", "RegionId": "CN5114", "Latitude": 30.0, "Longitude": 103.0, "Detail": detail}]}]}
        candidates, _ = jsp.collect_cnkgraph("苏轼", FakeClient(payload=payload))
        events = [c for c in candidates if c["event_type"] == "person_event"]
        works = [c for c in candidates if c["event_type"] == "work_chronology"]
        self.assertEqual(events, [])
        self.assertEqual(len(works), 1)
        self.assertEqual(works[0]["source_title"], "念奴娇·赤壁怀古")
        self.assertTrue(works[0]["body_hash"])

    def test_same_summary_prefix_different_tail_events_are_distinct(self) -> None:
        common = "苏" * 130
        row1 = common + "甲事。"
        row2 = common + "乙事。"
        detail = (
            "<div class='label1' id='l1_label'>"
            "<a href=\"javascript: ViewDetail('scope=&author=&beginYear=1050&endYear=1050')\">1050年</a>"
            "</div>"
            "<div id='l1' class='detail'>"
            f"<a href=\"javascript: ViewDetail('scope=&author=&beginYear=1050&endYear=1050')\">1050年</a>　{row1}<br />"
            f"<a href=\"javascript: ViewDetail('scope=&author=&beginYear=1050&endYear=1050')\">1050年</a>　{row2}<br />"
            "</div>"
        )
        payload = {"Traces": [{"Markers": [{"Title": "眉山", "RegionId": "CN5114", "Latitude": 30.0, "Longitude": 103.0, "Detail": detail}]}]}
        candidates, _ = jsp.collect_cnkgraph("苏轼", FakeClient(payload=payload))
        events = [c for c in candidates if c["event_type"] == "person_event"]
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["event_text"], events[1]["event_text"])
        self.assertNotEqual(events[0]["candidate_id"], events[1]["candidate_id"])
        self.assertNotEqual(events[0]["source_pages"], events[1]["source_pages"])

    def test_work_candidate_keeps_author_date(self) -> None:
        candidates, _ = self.collect(self.trace_payload())
        works = {row["source_title"]: row for row in candidates if row["event_type"] == "work_chronology"}
        self.assertEqual(works["题西林壁"]["author_date"], "（1084年）")
        self.assertEqual(works["夏侯太初论"]["author_date"], "（1045年）")

    def test_parse_year_range_keeps_bounds_and_approximation(self) -> None:
        self.assertEqual(jsp._parse_year_range("725-727年"), (725, 727, "approximate"))
        self.assertEqual(jsp._parse_year_range("约725年"), (725, 725, "approximate"))
        self.assertEqual(jsp._parse_year_range("725年"), (725, 725, "exact"))
        self.assertEqual(jsp._parse_year_range("天宝十四载"), None)
        self.assertEqual(jsp._parse_year_range(""), None)

    def test_trace_poem_author_date_range_and_approximate(self) -> None:
        def poem_block(anchor: str, author_date: str, writing_id: str, title: str) -> str:
            return (
                f"<a href=\"javascript: ViewDetail('scope=&author=&beginYear={anchor}&endYear={anchor}')\">{anchor}年</a>　作。"
                f"<div id='poem_{writing_id}' class='_poem'><div id='poem_title_{writing_id}' class='poemTitle showDetail'>"
                f"<a href='/Writing/{writing_id}?labeling=true' target='_blank'>{title}</a>"
                f"<span class='authorDate'>（{author_date}）</span>"
                f"<span class='poemAuthor'><a href='javascript: ShowPoemAuthorProfile(29937, \"北宋\", \"苏轼\", \"poem_title_{writing_id}\")'>苏轼</a></span>"
                "</div></div><br />"
            )

        detail = (
            "<div class='label1' id='l1_label'>"
            "<a href=\"javascript: ViewDetail('scope=&author=&beginYear=725&endYear=727')\">725-727年</a>"
            "</div>"
            "<div id='l1' class='detail'>"
            + poem_block("725", "725-727年", "300123", "题西林壁")
            + poem_block("726", "约726年", "300124", "赤壁赋")
            + "</div>"
        )
        payload = {"Traces": [{"Markers": [{"Title": "某地", "RegionId": "R1", "Latitude": 30.0, "Longitude": 103.0, "Detail": detail}]}]}
        candidates, _ = jsp.collect_cnkgraph("苏轼", FakeClient(payload=payload))
        works = {row["source_title"]: row for row in candidates if row["event_type"] == "work_chronology"}
        xiling = works["题西林壁"]
        self.assertEqual(xiling["year_start"], 725)
        self.assertEqual(xiling["year_end"], 727)
        self.assertEqual(xiling["year_precision"], "approximate")
        chibi = works["赤壁赋"]
        self.assertEqual(chibi["year_start"], 726)
        self.assertEqual(chibi["year_end"], 726)
        self.assertEqual(chibi["year_precision"], "approximate")

    def test_empty_author_work_is_c_and_unlinked(self) -> None:
        candidates, _ = self.collect(self.author_mix_payload())
        works = {row["source_title"]: row for row in candidates if row["event_type"] == "work_chronology"}
        empty = works["和子由渑池怀旧"]
        self.assertEqual(empty["source_author"], "")
        self.assertEqual(empty["source_grade"], "C")
        self.assertEqual(empty["linked"], False)
        self.assertEqual(empty["body_hash"], "")
        self.assertIn("作者未标注", empty["source_note"])

    def test_interleaved_noise_div_breaks_label1_pairing(self) -> None:
        row = "<a href=\"javascript: ViewDetail('scope=&author=&beginYear=1050&endYear=1050')\">1050年</a>　在眉山。<br />"
        label = (
            "<div class='label1' id='l1_label'>"
            "<a href=\"javascript: ViewDetail('scope=&author=&beginYear=1050&endYear=1050')\">1050年</a>"
            "</div>"
        )
        clean = {"Traces": [{"Markers": [{"Title": "眉山", "RegionId": "CN5114", "Latitude": 30.0, "Longitude": 103.0, "Detail": label + f"<div id='l1' class='detail'>{row}</div>"}]}]}
        noisy = {"Traces": [{"Markers": [{"Title": "眉山", "RegionId": "CN5114", "Latitude": 30.0, "Longitude": 103.0, "Detail": label + "<div class='noise'>噪音</div>" + f"<div id='l1' class='detail'>{row}</div>"}]}]}

        def events(payload: dict[str, object]) -> list[dict[str, object]]:
            candidates, _ = jsp.collect_cnkgraph("苏轼", FakeClient(payload=payload))
            return [c for c in candidates if c["event_type"] == "person_event"]

        self.assertEqual(len(events(clean)), 1)
        self.assertEqual(events(noisy), [])

    def test_coordinate_bounds_are_enforced(self) -> None:
        row = "<a href=\"javascript: ViewDetail('scope=&author=&beginYear=1050&endYear=1050')\">1050年</a>　在眉山。<br />"
        block = (
            "<div class='label1' id='l1_label'>"
            "<a href=\"javascript: ViewDetail('scope=&author=&beginYear=1050&endYear=1050')\">1050年</a>"
            "</div>"
            f"<div id='l1' class='detail'>{row}</div>"
        )

        def events(lat: object, lon: object) -> list[dict[str, object]]:
            payload = {"Traces": [{"Markers": [{"Title": "眉山", "RegionId": "CN5114", "Latitude": lat, "Longitude": lon, "Detail": block}]}]}
            candidates, _ = jsp.collect_cnkgraph("苏轼", FakeClient(payload=payload))
            return [c for c in candidates if c["event_type"] == "person_event"]

        self.assertEqual(len(events(30.0, 103.0)), 1)
        self.assertEqual(events(float("inf"), 103.0), [])
        self.assertEqual(events(30.0, float("-inf")), [])
        self.assertEqual(events(91.0, 103.0), [])
        self.assertEqual(events(30.0, 181.0), [])
        self.assertEqual(events(-91.0, 103.0), [])
        self.assertEqual(events(30.0, -181.0), [])
        self.assertEqual(len(events(0.0, 0.0)), 1)
        self.assertFalse(jsp._valid_latitude(float("nan")))
        self.assertFalse(jsp._valid_longitude(181.0))
        self.assertTrue(jsp._valid_latitude(0.0))
        self.assertTrue(jsp._valid_longitude(-180.0))

    def test_inline_anchor_requires_both_years_for_new_row(self) -> None:
        detail = (
            "<div class='label1' id='l1_label'>"
            "<a href=\"javascript: ViewDetail('scope=&author=&beginYear=1000&endYear=1000')\">1000年</a>"
            "</div>"
            "<div id='l1' class='detail'>"
            "<a href=\"javascript: ViewDetail('scope=&author=&beginYear=1001')\">1001年</a>　缺endYear的行。<br />"
            "<a href=\"javascript: ViewDetail('scope=&author=&beginYear=1002&endYear=1002')\">1002年</a>　正常行。<br />"
            "</div>"
        )
        payload = {"Traces": [{"Markers": [{"Title": "某地", "RegionId": "R1", "Latitude": 30.0, "Longitude": 103.0, "Detail": detail}]}]}
        candidates, _ = jsp.collect_cnkgraph("苏轼", FakeClient(payload=payload))
        events = [c for c in candidates if c["event_type"] == "person_event"]
        # The malformed 1001 row yields nothing; the valid 1002 row is kept.
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["year_start"], 1002)
        self.assertEqual(events[0]["year_end"], 1002)

    def test_lines_points_never_produce_events(self) -> None:
        candidates, _ = self.collect(self.trace_payload())
        events = [row for row in candidates if row["event_type"] == "person_event"]
        self.assertNotIn("伪路线点", {row["historical_place"] for row in events})
        self.assertNotIn(999, {row["year_start"] for row in events})

    def test_events_are_dedup_stable(self) -> None:
        first, _ = self.collect(self.trace_payload())
        second, _ = self.collect(self.trace_payload())
        self.assertEqual(
            {row["candidate_id"] for row in first},
            {row["candidate_id"] for row in second},
        )
        self.assertEqual(len({row["candidate_id"] for row in first}), len(first))

    def test_marker_without_year_blocks_produces_nothing(self) -> None:
        payload = {
            "Traces": [
                {
                    "Markers": [
                        {
                            "Title": "无年份地点",
                            "RegionId": "R1",
                            "Detail": "<div class='detail'>仅文字，无年份锚点<br /></div>",
                        },
                        {"Title": "空详情", "RegionId": "R2", "Detail": None},
                    ]
                }
            ]
        }
        candidates, status = self.collect(payload)
        self.assertEqual(status["status"], "empty")
        self.assertEqual(candidates, [])


class StabilityAndOutputTests(unittest.TestCase):
    def test_candidate_ids_are_deterministic(self) -> None:
        poem = sample_poem()
        entry = {"work_id": "26161", "title": "金陵酒肆留别", "author": "李白", "years": [726], "precision": "year_month"}
        first = jsp.make_work_chronology_candidate("李白", poem, entry, 726, 726, "ck", "url")
        second = jsp.make_work_chronology_candidate("李白", poem, entry, 726, 726, "ck", "url")
        self.assertEqual(first["candidate_id"], second["candidate_id"])
        self.assertEqual(len(first["candidate_id"]), 64)

    def test_upsert_preserves_reviewer_status(self) -> None:
        row = {
            "candidate_id": "a" * 64,
            "poet": "李白",
            "status": "approved",
            "reviewer": "审稿人",
            "review_note": "已核实",
            "reviewed_at": "2026-01-01T00:00:00+00:00",
            "year_start": 726,
            "year_end": 726,
        }
        refreshed = dict(row, status="needs_review", reviewed_at="")
        merged = jsp.upsert_rows([row], [refreshed])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["status"], "approved")
        self.assertEqual(merged[0]["reviewer"], "审稿人")
        self.assertEqual(merged[0]["review_note"], "已核实")
        self.assertEqual(merged[0]["reviewed_at"], "2026-01-01T00:00:00+00:00")

    def test_status_upsert_replaces_stale_run_fields(self) -> None:
        previous = {
            "poet": "李白",
            "source": "souyun",
            "status": "partial",
            "failed_page": 2,
            "pages_completed": 1,
        }
        current = {
            "poet": "李白",
            "source": "souyun",
            "status": "collected",
            "pages_completed": 5,
        }
        merged = jsp.upsert_status([previous], [current])
        self.assertEqual(merged, [current])
        self.assertNotIn("failed_page", merged[0])

    def test_repeated_collect_is_idempotent(self) -> None:
        client = FakeClient(payload=fixture_json("cbdb_person.json"))
        first, _ = jsp.collect_cbdb("李白", client)
        second, _ = jsp.collect_cbdb("李白", client)
        self.assertEqual({row["candidate_id"] for row in first}, {row["candidate_id"] for row in second})
        self.assertEqual(
            len({row["candidate_id"] for row in first}),
            len({row["candidate_id"] for row in second}),
        )

    def test_write_outputs_is_atomic_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            events = [
                {
                    "candidate_id": "b" * 64,
                    "poet": "李白",
                    "event_type": "residence",
                    "source": "cbdb",
                    "year_start": 727,
                    "year_end": 739,
                    "status": "needs_review",
                }
            ]
            works = [
                {
                    "candidate_id": "c" * 64,
                    "poet": "李白",
                    "event_type": "work_chronology",
                    "source": "souyun",
                    "year_start": 726,
                    "year_end": 726,
                    "status": "needs_review",
                }
            ]
            statuses = [
                {"poet": "李白", "source": "cbdb", "status": "collected", "candidates": 1},
                {"poet": "李白", "source": "souyun", "status": "collected", "candidates": 1},
            ]
            merged_events, merged_works, merged_status, coverage = jsp.write_outputs(
                events, works, statuses, base_dir=base
            )
            self.assertEqual(len(merged_events), 1)
            self.assertEqual(len(merged_works), 1)
            self.assertEqual(len(merged_status), 2)
            self.assertEqual(coverage["totals"]["event_candidates"], 1)
            self.assertEqual(coverage["totals"]["work_candidates"], 1)

            more_statuses = [{"poet": "李白", "source": "cnkgraph", "status": "no_content", "candidates": 0}]
            merged_events, merged_works, merged_status, coverage = jsp.write_outputs(
                [], [], more_statuses, base_dir=base
            )
            self.assertEqual(len(merged_events), 1)
            self.assertEqual(len(merged_status), 3)
            self.assertEqual((base / "journey_event_candidates.jsonl").exists(), True)
            self.assertEqual((base / "journey_source_status.jsonl").exists(), True)
            self.assertEqual((base / "journey_source_coverage.json").exists(), True)

    def test_coverage_is_byte_and_timestamp_idempotent_until_semantics_change(self) -> None:
        poet = corpus_poets()[0]
        event = {
            "candidate_id": "1" * 64,
            "poet": poet,
            "event_type": "residence",
            "source": "cbdb",
            "year_start": 700,
        }
        changed_event = {
            "candidate_id": "2" * 64,
            "poet": poet,
            "event_type": "posting",
            "source": "cbdb",
            "year_start": 701,
        }
        first_status = [{"poet": poet, "source": "cbdb", "status": "collected", "candidates": 1}]
        changed_status = [{"poet": poet, "source": "cbdb", "status": "collected", "candidates": 2}]

        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            coverage_path = base / "journey_source_coverage.json"
            with (
                patch.object(jsp, "utc_now", side_effect=["coverage-v1", "unused-v2", "coverage-v3"]),
                patch.object(jsp, "atomic_write_text", wraps=jsp.atomic_write_text) as coverage_write,
            ):
                _, _, _, first = jsp.write_outputs(
                    [event], [], first_status, base_dir=base
                )
                first_bytes = coverage_path.read_bytes()
                first_mtime = coverage_path.stat().st_mtime_ns
                self.assertEqual(first["generated_at"], "coverage-v1")
                self.assertEqual(first["totals"]["selected_poets"], 88)
                self.assertEqual(coverage_write.call_count, 1)

                time.sleep(0.02)
                _, _, _, repeated = jsp.write_outputs(
                    [event], [], first_status, base_dir=base
                )
                self.assertEqual(repeated["generated_at"], "coverage-v1")
                self.assertEqual(coverage_path.read_bytes(), first_bytes)
                self.assertEqual(coverage_path.stat().st_mtime_ns, first_mtime)
                self.assertEqual(coverage_write.call_count, 1)

                time.sleep(0.02)
                _, _, _, changed = jsp.write_outputs(
                    [event, changed_event], [], changed_status, base_dir=base
                )
                self.assertEqual(changed["generated_at"], "coverage-v3")
                self.assertNotEqual(coverage_path.read_bytes(), first_bytes)
                self.assertEqual(coverage_write.call_count, 2)

    def test_subset_write_keeps_complete_88_poet_coverage_snapshot(self) -> None:
        poets = corpus_poets()
        self.assertEqual(len(poets), 88)
        events = [
            {
                "candidate_id": f"{index:064x}",
                "poet": poet,
                "source": "cbdb",
                "event_type": "residence",
                "year_start": 700 + index,
            }
            for index, poet in enumerate(poets)
        ]
        works = [
            {
                "candidate_id": f"{index + len(poets):064x}",
                "poet": poet,
                "source": "souyun",
                "event_type": "work_chronology",
                "year_start": 700 + index,
                "linked": True,
            }
            for index, poet in enumerate(poets)
        ]
        statuses = [
            {
                "poet": poet,
                "source": source,
                "status": "collected",
                "candidates": 1 if source in {"cbdb", "souyun"} else 0,
            }
            for poet in poets
            for source in jsp.SOURCES
        ]
        subset = poets[:6]
        subset_statuses = [row for row in statuses if row["poet"] in subset]
        subset_events = [row for row in events if row["poet"] in subset]
        subset_works = [row for row in works if row["poet"] in subset]

        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            jsp.write_outputs(events, works, statuses, base_dir=base, poets=poets)
            merged_events, merged_works, merged_status, coverage = jsp.write_outputs(
                subset_events,
                subset_works,
                subset_statuses,
                base_dir=base,
                poets=subset,
            )
            self.assertEqual(len(merged_events), 88)
            self.assertEqual(len(merged_works), 88)
            self.assertEqual(len(merged_status), 264)
            self.assertEqual(coverage["totals"]["selected_poets"], 88)
            self.assertEqual(coverage["totals"]["status_lines"], 264)
            self.assertEqual(coverage["totals"]["candidates"], 176)
            self.assertEqual(len(coverage["per_poet"]), 88)
            for status in merged_status:
                scope = coverage["per_poet"][status["poet"]][status["source"]]
                self.assertEqual(scope["candidates"], status["candidates"])

            stable_files = {
                name: (base / name).read_bytes()
                for name in (
                    "journey_event_candidates.jsonl",
                    "work_chronology_supplements.jsonl",
                    "journey_source_status.jsonl",
                )
            }
            _, _, repeated_status, repeated_coverage = jsp.write_outputs(
                subset_events,
                subset_works,
                subset_statuses,
                base_dir=base,
                poets=subset,
            )
            self.assertEqual(len(repeated_status), 264)
            self.assertEqual(repeated_coverage["totals"], coverage["totals"])
            for name, payload in stable_files.items():
                self.assertEqual((base / name).read_bytes(), payload)
            on_disk = json.loads((base / "journey_source_coverage.json").read_text(encoding="utf-8"))
            self.assertEqual(on_disk["totals"]["selected_poets"], 88)
            self.assertEqual(on_disk["totals"]["status_lines"], 264)
            self.assertEqual(list(base.glob("*.tmp")), [])

    def test_duplicate_candidate_ids_reconcile_status_to_unique_disk_count(self) -> None:
        poet = "李白"
        candidate = {
            "candidate_id": "d" * 64,
            "poet": poet,
            "source": "cnkgraph",
            "event_type": "residence",
            "year_start": 742,
        }
        fetched_status = {
            "poet": poet,
            "source": "cnkgraph",
            "status": "collected",
            "candidates": 2,
        }
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            events, _, statuses, coverage = jsp.write_outputs(
                [candidate, dict(candidate)],
                [],
                [fetched_status],
                base_dir=base,
            )
            self.assertEqual(len(events), 1)
            self.assertEqual(statuses[0]["last_fetch_candidates"], 2)
            self.assertEqual(statuses[0]["candidates"], 1)
            self.assertEqual(coverage["per_poet"][poet]["cnkgraph"]["candidates"], 1)

            events2, _, statuses2, coverage2 = jsp.write_outputs(
                [candidate, dict(candidate)],
                [],
                [fetched_status],
                base_dir=base,
            )
            self.assertEqual(len(events2), 1)
            self.assertEqual(statuses2[0]["last_fetch_candidates"], 2)
            self.assertEqual(statuses2[0]["candidates"], 1)
            self.assertEqual(coverage2["per_poet"][poet]["cnkgraph"]["candidates"], 1)
            self.assertEqual(list(base.glob("*.tmp")), [])

    def test_last_fetch_count_stays_absent_when_input_omits_candidates(self) -> None:
        poet = "李白"
        event = {
            "candidate_id": "f" * 64,
            "poet": poet,
            "source": "cbdb",
            "event_type": "residence",
            "year_start": 744,
        }
        status_without_fetch_count = {
            "poet": poet,
            "source": "cbdb",
            "status": "collected",
        }
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            _, _, statuses, _ = jsp.write_outputs(
                [event], [], [status_without_fetch_count], base_dir=base
            )
            self.assertEqual(statuses[0]["candidates"], 1)
            self.assertNotIn("last_fetch_candidates", statuses[0])

            _, _, repeated_statuses, _ = jsp.write_outputs([], [], [], base_dir=base)
            self.assertEqual(repeated_statuses[0]["candidates"], 1)
            self.assertNotIn("last_fetch_candidates", repeated_statuses[0])

    def test_zero_fetch_souyun_status_counts_retained_old_candidate(self) -> None:
        poet = "李白"
        old_work = {
            "candidate_id": "e" * 64,
            "poet": poet,
            "source": "souyun",
            "event_type": "work_chronology",
            "year_start": 726,
            "linked": True,
        }
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            jsp.write_outputs(
                [],
                [old_work],
                [{"poet": poet, "source": "souyun", "status": "collected", "candidates": 1}],
                base_dir=base,
            )
            _, works, statuses, coverage = jsp.write_outputs(
                [],
                [],
                [{"poet": poet, "source": "souyun", "status": "collected", "candidates": 0}],
                base_dir=base,
                refresh_successful=True,
            )
            self.assertEqual(len(works), 1)
            self.assertEqual(statuses[0]["last_fetch_candidates"], 0)
            self.assertEqual(statuses[0]["candidates"], 1)
            scope = coverage["per_poet"][poet]["souyun"]
            self.assertEqual(scope["candidates"], statuses[0]["candidates"])
            self.assertEqual(scope["linked_work_candidates"], 1)
            self.assertEqual(scope["reviewable_candidates"], 1)

    def test_souyun_blockers_keep_old_candidates_stale_and_inactive(self) -> None:
        blocker_by_poet = {
            "王建": "identity_ambiguous",
            "杨万里": "discovered_author_id_but_api_requires_disambiguation",
        }
        old_works = [
            {
                "candidate_id": f"{1000 + index:064x}",
                "poet": poet,
                "source": "souyun",
                "event_type": "work_chronology",
                "year_start": 800 + index,
                "linked": True,
            }
            for index, poet in enumerate(blocker_by_poet)
        ]
        old_statuses = [
            {"poet": poet, "source": "souyun", "status": "collected", "candidates": 1}
            for poet in blocker_by_poet
        ]
        blocker_statuses = [
            {"poet": poet, "source": "souyun", "status": blocker, "candidates": 0}
            for poet, blocker in blocker_by_poet.items()
        ]
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            jsp.write_outputs([], old_works, old_statuses, base_dir=base)
            _, works, statuses, coverage = jsp.write_outputs(
                [], [], blocker_statuses, base_dir=base, refresh_successful=True
            )
            self.assertEqual(len(works), 2)
            by_scope = {(row["poet"], row["source"]): row for row in statuses}
            for poet, blocker in blocker_by_poet.items():
                status = by_scope[(poet, "souyun")]
                self.assertEqual(status["status"], blocker)
                self.assertEqual(status["last_fetch_candidates"], 0)
                self.assertEqual(status["candidates"], 1)
                scope = coverage["per_poet"][poet]["souyun"]
                self.assertEqual(scope["candidates"], 1)
                self.assertEqual(scope["stale_candidate_count"], 1)
                self.assertEqual(scope["linked_work_candidates"], 0)
                self.assertEqual(scope["reviewable_candidates"], 0)
            self.assertEqual(coverage["totals"]["candidates"], 2)
            self.assertEqual(coverage["totals"]["stale_candidate_count"], 2)
            self.assertEqual(coverage["totals"]["linked_work_candidates"], 0)
            self.assertEqual(coverage["totals"]["reviewable_candidates"], 0)

    def test_coverage_aggregation(self) -> None:
        statuses = [
            {"poet": "李白", "source": "cbdb", "status": "collected", "candidates": 5},
            {"poet": "李白", "source": "souyun", "status": "collected", "candidates": 3},
            {"poet": "李白", "source": "cnkgraph", "status": "collected", "candidates": 3},
        ]
        events = [
            {"poet": "李白", "source": "cbdb", "latitude": 34.27, "longitude": 108.95},
            {"poet": "李白", "source": "cbdb"},
        ]
        works = [
            {"poet": "李白", "source": "souyun", "linked": True} for _ in range(2)
        ] + [
            {"poet": "李白", "source": "cnkgraph", "linked": False, "source_title_ambiguous": True} for _ in range(1)
        ]
        coverage = jsp.build_coverage(statuses, events, works)
        self.assertEqual(coverage["totals"]["event_candidates"], 2)
        self.assertEqual(coverage["totals"]["locatable_event_candidates"], 1)
        self.assertEqual(coverage["totals"]["unlocated_event_candidates"], 1)
        self.assertEqual(coverage["totals"]["work_candidates"], 3)
        self.assertEqual(coverage["totals"]["linked_work_candidates"], 2)
        self.assertEqual(coverage["totals"]["unlinked_work_candidates"], 1)
        self.assertEqual(coverage["totals"]["ambiguous_work_candidates"], 1)
        self.assertEqual(coverage["totals"]["reviewable_candidates"], 2 + 2)
        self.assertEqual(coverage["per_poet"]["李白"]["cbdb"]["event_candidates"], 2)
        self.assertEqual(coverage["per_poet"]["李白"]["cbdb"]["locatable_event_candidates"], 1)
        self.assertEqual(coverage["per_poet"]["李白"]["souyun"]["work_candidates"], 2)
        self.assertEqual(coverage["per_poet"]["李白"]["souyun"]["linked_work_candidates"], 2)
        self.assertEqual(coverage["per_poet"]["李白"]["souyun"]["reviewable_candidates"], 2)
        self.assertEqual(coverage["per_poet"]["李白"]["cnkgraph"]["ambiguous_work_candidates"], 1)
        self.assertEqual(coverage["per_poet"]["杜甫"]["cnkgraph"]["status"], "not_collected")
        # Legacy souyun rows (no linked flag) count as linked via body_hash.
        legacy = [{"poet": "李白", "source": "souyun", "body_hash": "x" * 64}]
        self.assertTrue(jsp._work_is_linked(legacy[0]))


class StaleRefreshTests(unittest.TestCase):
    """--refresh-successful-scopes semantics: replace on success, never on failure."""

    def setUp(self) -> None:
        self.old_event = {
            "candidate_id": "a" * 64, "poet": "李白", "source": "cbdb",
            "event_type": "residence", "year_start": 700, "year_end": 700, "status": "needs_review",
        }
        self.old_work = {
            "candidate_id": "b" * 64, "poet": "李白", "source": "souyun",
            "event_type": "work_chronology", "year_start": 726, "year_end": 726,
            "linked": True, "body_hash": "x" * 64, "status": "needs_review",
        }
        self.new_event = {
            "candidate_id": "c" * 64, "poet": "李白", "source": "cbdb",
            "event_type": "posting", "year_start": 742, "year_end": 744, "status": "needs_review",
        }

    def test_successful_scope_is_replaced(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            jsp.write_outputs([self.old_event], [self.old_work], [{"poet": "李白", "source": "cbdb", "status": "collected"}], base_dir=base)
            statuses = [
                {"poet": "李白", "source": "cbdb", "status": "collected", "candidates": 1},
                {"poet": "李白", "source": "souyun", "status": "partial", "failed_page": 1},
            ]
            merged_events, merged_works, _, _ = jsp.write_outputs(
                [self.new_event], [], statuses, base_dir=base, refresh_successful=True
            )
            # cbdb scope was collected -> old 'a' cleared, new 'c' written.
            event_ids = {row["candidate_id"] for row in merged_events}
            self.assertNotIn("a" * 64, event_ids)
            self.assertIn("c" * 64, event_ids)
            # souyun scope was partial -> never cleared; old 'b' preserved.
            work_ids = {row["candidate_id"] for row in merged_works}
            self.assertIn("b" * 64, work_ids)
            self.assertEqual(len(merged_works), 1)

    def test_failure_never_clears_and_default_upsert_is_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            jsp.write_outputs([self.old_event], [], [], base_dir=base)
            failed = [{"poet": "李白", "source": "cbdb", "status": "fetch_failed", "note": "HTTP 500"}]
            merged, _, _, _ = jsp.write_outputs([], [], failed, base_dir=base, refresh_successful=True)
            self.assertIn("a" * 64, {row["candidate_id"] for row in merged})
            # Without the flag the same run is a plain upsert: old row preserved.
            merged2, _, _, _ = jsp.write_outputs([self.new_event], [], [{"poet": "李白", "source": "cbdb", "status": "collected"}], base_dir=base)
            ids2 = {row["candidate_id"] for row in merged2}
            self.assertIn("a" * 64, ids2)
            self.assertIn("c" * 64, ids2)

    def test_refresh_preserves_reviewer_on_same_id(self) -> None:
        reviewed = dict(self.new_event, status="approved", reviewer="审稿人", review_note="已核实", reviewed_at="2026-01-01T00:00:00+00:00")
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            jsp.write_outputs([reviewed], [], [], base_dir=base)
            statuses = [{"poet": "李白", "source": "cbdb", "status": "collected", "candidates": 1}]
            merged, _, _, _ = jsp.write_outputs([self.new_event], [], statuses, base_dir=base, refresh_successful=True)
            self.assertEqual(len(merged), 1)
            self.assertEqual(merged[0]["status"], "approved")
            self.assertEqual(merged[0]["reviewer"], "审稿人")
            self.assertEqual(merged[0]["reviewed_at"], "2026-01-01T00:00:00+00:00")

    def test_souyun_success_never_physically_clears_older_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            jsp.write_outputs([], [self.old_work], [], base_dir=base)
            _, works, _, _ = jsp.write_outputs(
                [],
                [],
                [{"poet": "李白", "source": "souyun", "status": "collected", "candidates": 0}],
                base_dir=base,
                refresh_successful=True,
            )
            self.assertIn("b" * 64, {row["candidate_id"] for row in works})


class ResumeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.index = jsp.build_poem_index()

    @staticmethod
    def _souyun_blocker_cases() -> list[tuple[str, str, str]]:
        return [
            ("王建", "Tang", "identity_ambiguous"),
            (
                "杨万里",
                "Song",
                "discovered_author_id_but_api_requires_disambiguation",
            ),
        ]

    def test_collect_souyun_short_circuits_current_registry_blockers(self) -> None:
        for poet, dynasty, blocker in self._souyun_blocker_cases():
            with self.subTest(poet=poet, blocker=blocker):
                client = FakeClient(payload={"unexpected": "network response"})
                registry_entry = {
                    "poet": poet,
                    "dynasty": dynasty,
                    "souyun": {
                        "status": blocker,
                        "author_id": 99999,
                        "source_url": "fixture://registry",
                    },
                }
                candidates, status = jsp.collect_souyun(
                    poet,
                    client,
                    poem_index=self.index,
                    registry_entry=registry_entry,
                )
                self.assertEqual(client.requests, [])
                self.assertEqual(candidates, [])
                self.assertEqual(status["status"], blocker)
                self.assertIs(status["identity_verified"], False)
                self.assertIsNone(status["author_id"])
                self.assertEqual(status["candidates"], 0)

    def test_resume_registry_blocker_overrides_old_success_without_network(self) -> None:
        for poet, dynasty, blocker in self._souyun_blocker_cases():
            with self.subTest(poet=poet, blocker=blocker):
                client = FakeClient(payload={"unexpected": "network response"})
                previous = {
                    "poet": poet,
                    "source": "souyun",
                    "status": "collected",
                    "pages_requested": 1,
                    "pages_completed": 1,
                    "pagination_complete": True,
                    "author_id": 12345,
                    "identity_verified": True,
                    "candidates": 7,
                }
                registry = {
                    poet: {
                        "poet": poet,
                        "dynasty": dynasty,
                        "souyun": {"status": blocker, "author_id": 99999},
                    }
                }
                events, works, statuses = jsp.run_collection(
                    [poet],
                    ["souyun"],
                    client,
                    self.index,
                    max_souyun_pages=1,
                    resume=True,
                    existing_status=[previous],
                    registry=registry,
                )
                self.assertEqual(client.requests, [])
                self.assertEqual(events, [])
                self.assertEqual(works, [])
                self.assertEqual(len(statuses), 1)
                self.assertEqual(statuses[0]["status"], blocker)
                self.assertIs(statuses[0]["identity_verified"], False)
                self.assertIsNone(statuses[0]["author_id"])
                self.assertEqual(statuses[0]["candidates"], 0)

    def test_resume_skip_requires_completed_pages(self) -> None:
        self.assertFalse(jsp._resume_skip("souyun", None, 1))
        self.assertFalse(jsp._resume_skip("souyun", {"status": "ok", "pages_completed": 1}, 2))
        self.assertTrue(jsp._resume_skip("souyun", {"status": "ok", "pages_completed": 2}, 2))
        self.assertFalse(jsp._resume_skip("souyun", {"status": "partial", "pages_completed": 1}, 1))
        self.assertFalse(jsp._resume_skip("souyun", {"status": "fetch_failed", "pages_completed": 0}, 1))
        self.assertTrue(jsp._resume_skip("cbdb", {"status": "collected", "candidates": 5}, 1))
        self.assertFalse(jsp._resume_skip("cbdb", {"status": "identity_mismatch"}, 1))

    def test_zero_hit_success_still_blocks_nothing_on_expansion(self) -> None:
        # A previous full fetch with 0 hits covers only the pages it completed.
        prev = {"poet": "李白", "source": "souyun", "status": "ok", "pages_requested": 1, "pages_completed": 1, "candidates": 0}
        page0 = fixture_text("souyun_author_page.html")
        client = ScriptedPageClient([("ok", page0), ("ok", page0)])
        events, works, statuses = jsp.run_collection(
            ["李白"], ["souyun"], client, self.index,
            max_souyun_pages=2, resume=True, existing_status=[prev], souyun_transport="html",
        )
        self.assertEqual(len(statuses), 1)
        self.assertEqual(statuses[0]["status"], "collected")
        self.assertEqual(statuses[0]["pages_completed"], 2)
        self.assertEqual(statuses[0]["stop_reason"], "repeated_page")
        self.assertEqual(len(works), 3)

    def test_expanded_resume_refetches_to_fill_pages(self) -> None:
        prev = {"poet": "李白", "source": "souyun", "status": "collected", "pages_requested": 1, "pages_completed": 1, "candidates": 3}
        page0 = fixture_text("souyun_author_page.html")
        page1 = '<div class="poemTitle showDetail"><a href="Query.aspx?type=poem&amp;id=777">将进酒</a><span class="author">李白</span><span class="showTime">（天宝十一载，752年）</span></div>'
        client = ScriptedPageClient([("ok", page0), ("ok", page1)])
        events, works, statuses = jsp.run_collection(
            ["李白"], ["souyun"], client, self.index,
            max_souyun_pages=2, resume=True, existing_status=[prev], souyun_transport="html",
        )
        self.assertEqual(len(statuses), 1)
        self.assertEqual(statuses[0]["pages_requested"], 2)
        self.assertEqual(statuses[0]["pages_completed"], 2)
        self.assertEqual(statuses[0]["status"], "collected")

    def test_full_completion_is_skipped(self) -> None:
        prev = {"poet": "李白", "source": "souyun", "status": "collected", "pages_requested": 2, "pages_completed": 2, "candidates": 4}
        client = FakeClient(html=fixture_text("souyun_author_page.html"))
        events, works, statuses = jsp.run_collection(
            ["李白"], ["souyun"], client, self.index,
            max_souyun_pages=2, resume=True, existing_status=[prev], souyun_transport="html",
        )
        self.assertEqual(statuses, [])
        self.assertEqual(works, [])

    def test_partial_previous_status_is_retried(self) -> None:
        prev = {"poet": "李白", "source": "souyun", "status": "partial", "pages_requested": 2, "pages_completed": 1, "failed_page": 2}
        client = ScriptedPageClient([("ok", fixture_text("souyun_author_page.html")), ("ok", fixture_text("souyun_author_page.html"))])
        events, works, statuses = jsp.run_collection(
            ["李白"], ["souyun"], client, self.index,
            max_souyun_pages=2, resume=True, existing_status=[prev], souyun_transport="html",
        )
        self.assertEqual(len(statuses), 1)
        self.assertEqual(statuses[0]["status"], "collected")
        self.assertEqual(statuses[0]["pages_completed"], 2)


class CliValidationTests(unittest.TestCase):
    def _namespace(self, **overrides: object) -> argparse.Namespace:
        values: dict[str, object] = {
            "max_souyun_pages": 1,
            "timeout": 20.0,
            "retries": 3,
            "delay_min": 1.5,
            "delay_max": 3.0,
        }
        values.update(overrides)
        return argparse.Namespace(**values)

    def test_valid_args_pass(self) -> None:
        jsp._validate_collect_args(self._namespace())

    def test_invalid_args_raise(self) -> None:
        jsp._validate_collect_args(self._namespace(max_souyun_pages=0))
        with self.assertRaisesRegex(SystemExit, "max-souyun-pages"):
            jsp._validate_collect_args(self._namespace(max_souyun_pages=-2))
        with self.assertRaisesRegex(SystemExit, "timeout"):
            jsp._validate_collect_args(self._namespace(timeout=0))
        with self.assertRaisesRegex(SystemExit, "retries"):
            jsp._validate_collect_args(self._namespace(retries=-1))
        with self.assertRaisesRegex(SystemExit, "delay-min"):
            jsp._validate_collect_args(self._namespace(delay_min=0))
        with self.assertRaisesRegex(SystemExit, "delay-max"):
            jsp._validate_collect_args(self._namespace(delay_max=0.5, delay_min=2.0))


class CorpusRegistryAndConcurrencyTests(unittest.TestCase):
    def test_discovers_exactly_88_poets_and_keeps_core_default(self) -> None:
        profiles = corpus_poet_profiles()
        self.assertEqual(len(profiles), 88)
        self.assertEqual(len(corpus_poets()), 88)
        self.assertEqual(jsp.parse_poets(None), list(CORE_POETS))
        self.assertEqual(jsp.parse_poets(None, "all"), corpus_poets())
        self.assertEqual(jsp.parse_poets("王维,李白", "core"), ["王维", "李白"])
        self.assertTrue(all(profile["dynasty"] in {"Tang", "Song"} for profile in profiles))
        with self.assertRaisesRegex(SystemExit, "unknown poet"):
            jsp.parse_poets("不存在诗人", "all")

    def test_registry_uses_unique_id_and_never_picks_ambiguous(self) -> None:
        registry = psr.build_source_registry(
            [
                {
                    "poet": "王维",
                    "status": "matched",
                    "matches": [{"c_personid": 123}],
                    "source_version": "fixture",
                },
                {
                    "poet": "高适",
                    "status": "ambiguous",
                    "matches": [{"c_personid": 1}, {"c_personid": 2}],
                },
            ],
            audit={},
        )
        self.assertEqual(registry["poet_count"], 88)
        by_poet = psr.registry_by_poet(registry)
        self.assertEqual(by_poet["王维"]["cbdb"]["person_id"], "123")
        self.assertEqual(by_poet["王维"]["cbdb"]["status"], "matched")
        self.assertIsNone(by_poet["高适"]["cbdb"]["person_id"])
        self.assertEqual(by_poet["高适"]["cbdb"]["status"], "ambiguous")
        self.assertEqual(by_poet["李白"]["cbdb"]["person_id"], "32540")

    def test_audited_cbdb_snapshot_has_priority_over_low_quality_name_rows(self) -> None:
        audit = psr.load_cbdb_identity_audit()
        self.assertEqual(audit.get("database_sha256"), "ec0be08186722c53f77b47f4513239afd6a505f8157994cc72b9fbd49c6fc21a")
        registry = psr.build_source_registry(
            [{"poet": "王建", "status": "matched", "matches": [{"c_personid": 194596}]}],
            audit=audit,
        )
        by_poet = psr.registry_by_poet(registry)
        self.assertEqual(by_poet["王建"]["cbdb"]["person_id"], "92047")
        self.assertEqual(by_poet["王建"]["cbdb"]["status"], "audited_unique")
        self.assertIsNone(by_poet["常建"]["cbdb"]["person_id"])
        self.assertEqual(by_poet["常建"]["cbdb"]["match_person_ids"], ["94489", "147391", "149973", "163667"])
        expected_primary_names = {
            "王维": "王維",
            "高适": "高適",
            "苏轼": "蘇軾",
            "张志和": "張龜齡",
            "欧阳炯": "歐陽迴",
        }
        for poet, primary_name in expected_primary_names.items():
            with self.subTest(poet=poet):
                accepted = by_poet[poet]["cbdb"]["accepted_names"]
                self.assertIn(poet, accepted)
                self.assertIn(primary_name, accepted)

    def test_souyun_probe_registers_unique_ambiguous_and_disambiguation_identities(self) -> None:
        probe = psr.load_souyun_identity_probe()
        registry = psr.build_source_registry(audit=psr.load_cbdb_identity_audit(), souyun_probe=probe)
        by_poet = psr.registry_by_poet(registry)
        self.assertEqual(by_poet["王建"]["souyun"]["status"], "identity_ambiguous")
        self.assertEqual(by_poet["王建"]["souyun"]["candidate_author_ids"], [18501, 19737])
        self.assertIsNone(by_poet["王建"]["souyun"]["author_id"])
        self.assertEqual(by_poet["叶梦得"]["souyun"]["status"], "identity_ambiguous")
        self.assertEqual(
            by_poet["陆游"]["souyun"]["status"],
            "discovered_author_id_but_api_requires_disambiguation",
        )
        self.assertIs(by_poet["陆游"]["souyun"]["identity_verified"], False)
        self.assertEqual(by_poet["陆游"]["souyun"]["stale_candidate_author_ids"], [34522])
        self.assertEqual(by_poet["陆游"]["souyun"]["candidate_author_ids"], [34522])
        self.assertEqual(by_poet["欧阳炯"]["souyun"]["status"], "name_query")
        required_pages = [
            (int(row["count"]) + int(row["page_size"]) - 1) // int(row["page_size"])
            for row in probe["rows"]
            if isinstance(row, dict)
            and isinstance(row.get("count"), int)
            and isinstance(row.get("page_size"), int)
            and int(row["page_size"]) > 0
        ]
        self.assertLessEqual(max(required_pages), jsp.SOUYUN_AUTO_PAGE_LIMIT)

    def test_registry_refresh_preserves_souyun_discoveries_but_not_seed_conflicts(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "poet_source_registry.json"
            existing = psr.build_source_registry(audit=psr.load_cbdb_identity_audit())
            by_poet = psr.registry_by_poet(existing)
            by_poet["欧阳炯"]["souyun"].update(
                status="discovered",
                author_id=98765,
                identity_verified=True,
                verified_author_name="欧阳炯",
                verified_dynasty="Tang",
                verified_author_id=98765,
                identity_verification_method="souyun_open_poem_exact_name_dynasty_author_id",
                identity_verified_at="2026-08-01T00:00:00Z",
                identity_verified_from="fixture://ouyangjiong",
                discovered_at="2026-08-01T00:00:00Z",
                discovered_from="fixture://ouyangjiong",
            )
            by_poet["李白"]["souyun"].update(
                status="discovered",
                author_id=99999,
                identity_verified=True,
                verified_author_name="李白",
                verified_dynasty="Tang",
                verified_author_id=99999,
                identity_verification_method="souyun_open_poem_exact_name_dynasty_author_id",
                identity_verified_at="2026-08-01T00:00:00Z",
                identity_verified_from="fixture://libai",
                discovered_at="2026-08-01T00:00:00Z",
                discovered_from="fixture://libai",
            )
            psr.write_source_registry(existing, path)

            refreshed = psr.refresh_source_registry(path=path)
            refreshed_by_poet = psr.registry_by_poet(refreshed)
            self.assertEqual(refreshed_by_poet["欧阳炯"]["souyun"]["author_id"], 98765)
            self.assertEqual(refreshed_by_poet["欧阳炯"]["souyun"]["status"], "discovered")
            self.assertEqual(refreshed_by_poet["欧阳炯"]["souyun"]["discovered_from"], "fixture://ouyangjiong")
            self.assertEqual(refreshed_by_poet["李白"]["souyun"]["author_id"], 15188)
            self.assertEqual(refreshed_by_poet["李白"]["souyun"]["discovery_conflict_author_id"], 99999)

    def test_preserve_fresh_ambiguous_keeps_old_discovery_stale_only(self) -> None:
        fresh = {
            "poets": [
                {
                    "poet": "王建",
                    "dynasty": "Tang",
                    "souyun": {
                        "status": "identity_ambiguous",
                        "author_id": None,
                        "candidate_author_ids": [18501, 19737],
                    },
                }
            ]
        }
        old = {
            "poets": [
                {
                    "poet": "王建",
                    "dynasty": "Tang",
                    "souyun": {
                        "status": "discovered",
                        "author_id": 18501,
                        "identity_verified": True,
                        "verified_author_name": "王建",
                        "verified_dynasty": "Tang",
                        "verified_author_id": 18501,
                        "identity_verification_method": "souyun_open_poem_exact_name_dynasty_author_id",
                        "identity_verified_at": "2026-08-01T00:00:00Z",
                        "identity_verified_from": "fixture://wangjian",
                    },
                }
            ]
        }
        psr._preserve_souyun_discoveries(fresh, old)
        source = fresh["poets"][0]["souyun"]
        self.assertEqual(source["status"], "identity_ambiguous")
        self.assertIsNone(source["author_id"])
        self.assertEqual(source["stale_candidate_author_ids"], [18501])

    def test_preserve_name_query_requires_verified_provenance(self) -> None:
        fresh = {
            "poets": [
                {
                    "poet": "欧阳炯",
                    "dynasty": "Tang",
                    "souyun": {"status": "name_query", "author_id": None},
                }
            ]
        }
        old = {
            "poets": [
                {
                    "poet": "欧阳炯",
                    "dynasty": "Tang",
                    "souyun": {"status": "discovered", "author_id": 98765},
                }
            ]
        }
        psr._preserve_souyun_discoveries(fresh, old)
        source = fresh["poets"][0]["souyun"]
        self.assertEqual(source["status"], "name_query")
        self.assertIsNone(source["author_id"])
        self.assertEqual(source["stale_candidate_author_ids"], [98765])

    def test_merge_does_not_upgrade_disambiguation_status(self) -> None:
        registry = {
            "poets": [
                {
                    "poet": "秦观",
                    "dynasty": "Song",
                    "souyun": {
                        "status": "discovered_author_id_but_api_requires_disambiguation",
                        "author_id": 30713,
                    },
                }
            ]
        }
        psr.merge_souyun_discoveries(
            registry,
            [
                {
                    "poet": "秦观",
                    "source": "souyun",
                    "status": "discovered_author_id_but_api_requires_disambiguation",
                    "author_id": 30713,
                    "identity_verified": False,
                }
            ],
        )
        source = registry["poets"][0]["souyun"]
        self.assertEqual(source["status"], "discovered_author_id_but_api_requires_disambiguation")
        self.assertNotIn("identity_verified_at", source)

    def test_merge_rejects_unverified_collected_status(self) -> None:
        registry = {
            "poets": [
                {
                    "poet": "欧阳炯",
                    "dynasty": "Tang",
                    "souyun": {"status": "name_query", "author_id": None},
                }
            ]
        }
        psr.merge_souyun_discoveries(
            registry,
            [
                {
                    "poet": "欧阳炯",
                    "source": "souyun",
                    "status": "collected",
                    "author_id": 93725,
                    "identity_verified": False,
                }
            ],
        )
        source = registry["poets"][0]["souyun"]
        self.assertEqual(source["status"], "name_query")
        self.assertIsNone(source["author_id"])

    def test_merge_verified_success_keeps_fresh_identity_blockers(self) -> None:
        for blocker, active_author_id in (
            ("identity_ambiguous", None),
            ("discovered_author_id_but_api_requires_disambiguation", 31001),
        ):
            with self.subTest(blocker=blocker):
                registry = {
                    "poets": [
                        {
                            "poet": "PoetA",
                            "dynasty": "Tang",
                            "souyun": {
                                "status": blocker,
                                "author_id": active_author_id,
                                "identity_verified": False,
                            },
                        }
                    ]
                }
                psr.merge_souyun_discoveries(
                    registry,
                    [
                        {
                            "poet": "PoetA",
                            "source": "souyun",
                            "status": "collected",
                            "author_id": 31001,
                            "identity_verified": True,
                            "verified_author_name": "PoetA",
                            "verified_dynasty": "Tang",
                            "verified_author_id": 31001,
                            "checked_at": "2026-08-09T00:00:00Z",
                            "source_url": "fixture://verified",
                        }
                    ],
                )
                source = registry["poets"][0]["souyun"]
                self.assertEqual(source["status"], blocker)
                self.assertEqual(source["author_id"], active_author_id)
                self.assertIs(source["identity_verified"], False)
                self.assertEqual(source["stale_candidate_author_ids"], [31001])

    def test_positive_int_and_merge_reject_boolean_ids(self) -> None:
        self.assertIsNone(psr._positive_int(True))
        self.assertIsNone(psr._positive_int(False))
        registry = {
            "poets": [
                {
                    "poet": "PoetA",
                    "dynasty": "Tang",
                    "souyun": {"status": "name_query", "author_id": None},
                }
            ]
        }
        before = json.loads(json.dumps(registry))
        psr.merge_souyun_discoveries(
            registry,
            [
                {
                    "poet": "PoetA",
                    "source": "souyun",
                    "status": "collected",
                    "author_id": True,
                    "verified_author_id": True,
                    "identity_verified": True,
                    "verified_author_name": "PoetA",
                    "verified_dynasty": "Tang",
                }
            ],
        )
        self.assertEqual(registry, before)

    def test_repeated_verified_merge_is_deeply_idempotent(self) -> None:
        registry = {
            "generated_at": "initial",
            "poets": [
                {
                    "poet": "PoetA",
                    "dynasty": "Tang",
                    "souyun": {"status": "name_query", "author_id": None},
                }
            ],
        }
        status = {
            "poet": "PoetA",
            "source": "souyun",
            "status": "collected",
            "author_id": 31001,
            "identity_verified": True,
            "verified_author_name": "PoetA",
            "verified_dynasty": "Tang",
            "verified_author_id": 31001,
            "checked_at": "2026-08-09T00:00:00Z",
            "source_url": "fixture://verified",
        }
        with patch.object(psr, "utc_now", side_effect=["first-merge", "second-merge"]):
            psr.merge_souyun_discoveries(registry, [status])
            after_first = json.loads(json.dumps(registry))
            psr.merge_souyun_discoveries(registry, [status])
        self.assertEqual(registry, after_first)

    def test_parallel_and_serial_results_are_deterministic_and_clients_are_distinct(self) -> None:
        poets = ["李白", "杜甫", "王维", "苏轼"]
        used_clients: list[object] = []
        used_lock = threading.Lock()

        def fake_collect(poet: str, client: object, **_kwargs: object):
            with used_lock:
                used_clients.append(client)
            time.sleep(0.005 if poet in {"李白", "王维"} else 0.001)
            return [
                {
                    "candidate_id": (poet.encode("utf-8").hex() + "0" * 64)[:64],
                    "poet": poet,
                    "source": "cnkgraph",
                    "event_type": "residence",
                    "year_start": 700,
                }
            ], {"poet": poet, "source": "cnkgraph", "status": "collected", "candidates": 1}

        with patch.object(jsp, "collect_cnkgraph", side_effect=fake_collect):
            serial = jsp.run_collection(poets, ["cnkgraph"], FakeClient(), workers=1, existing_status=[])
            used_clients.clear()
            parallel = jsp.run_collection(
                poets,
                ["cnkgraph"],
                None,
                workers=4,
                source_workers={"cnkgraph": 3},
                client_factory=lambda: FakeClient(),
                existing_status=[],
            )
        self.assertEqual(
            [row["candidate_id"] for row in serial[0]],
            [row["candidate_id"] for row in parallel[0]],
        )
        self.assertEqual(
            [(row["poet"], row["source"], row["status"]) for row in serial[2]],
            [(row["poet"], row["source"], row["status"]) for row in parallel[2]],
        )
        self.assertEqual(len(used_clients), len(poets))
        self.assertEqual(len({id(client) for client in used_clients}), len(poets))

    def test_resume_auto_requires_completed_pagination(self) -> None:
        self.assertTrue(
            jsp._resume_skip("souyun", {"status": "collected", "pagination_complete": True}, 0)
        )
        self.assertFalse(
            jsp._resume_skip("souyun", {"status": "partial", "pagination_complete": False}, 0)
        )

    def test_coverage_can_materialize_all_88_poets(self) -> None:
        coverage = jsp.build_coverage([], [], [], poets=corpus_poets())
        self.assertEqual(coverage["totals"]["selected_poets"], 88)
        self.assertEqual(len(coverage["per_poet"]), 88)
        self.assertEqual(coverage["source_summary"]["cbdb"]["missing_poets"], 88)
        self.assertIn("writing_stat_status_counts", coverage["source_summary"]["cnkgraph"])

    def test_coverage_classifies_disambiguation_and_not_covered(self) -> None:
        poets = ["王建", "秦观", "欧阳炯", "李白"]
        statuses = [
            {"poet": "王建", "source": "souyun", "status": "identity_ambiguous"},
            {
                "poet": "秦观",
                "source": "souyun",
                "status": "discovered_author_id_but_api_requires_disambiguation",
            },
            {"poet": "欧阳炯", "source": "souyun", "status": "not_covered"},
            {"poet": "李白", "source": "souyun", "status": "collected"},
        ]
        summary = jsp.build_coverage(statuses, [], [], poets=poets)["source_summary"]["souyun"]
        self.assertEqual(summary["ambiguous_poets"], 2)
        self.assertEqual(summary["missing_poets"], 1)
        self.assertEqual(summary["successful_poets"], 1)
        self.assertEqual(summary["failed_poets"], 0)


class ReportTests(unittest.TestCase):
    def test_report_metrics_over_real_reviewed_data(self) -> None:
        result = jsp.compute_report(list(CORE_POETS))
        self.assertEqual(set(result), set(CORE_POETS))
        for poet, metric in result.items():
            self.assertIn("reviewed_nodes", metric)
            self.assertIn("chronology_rows", metric)
            self.assertIn("new_event_candidates", metric)
            self.assertIn("new_work_candidates", metric)
            self.assertIn("linked_work_candidates", metric)
            self.assertIn("unlinked_work_candidates", metric)
            self.assertIn("ambiguous_work_candidates", metric)
            self.assertIn("reviewable_candidates", metric)
            self.assertIn("conflicts", metric)
            self.assertIn("priority_gaps", metric)
            self.assertIn("source_counts", metric)
            self.assertIsInstance(metric["source_counts"], dict)
            # 有效补充只计 linked works。
            self.assertLessEqual(metric["new_work_candidates"], metric["linked_work_candidates"])
            self.assertEqual(
                metric["linked_work_candidates"] + metric["unlinked_work_candidates"],
                metric["linked_work_candidates"] + metric["unlinked_work_candidates"],
            )

    def test_chronology_windows_use_only_main_csv(self) -> None:
        import csv as _csv

        windows = jsp.load_chronology_windows(["李白"])
        path = CANDIDATE_DIR / "libai_spirit_chronology.csv"
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = sum(1 for _ in _csv.DictReader(handle))
        self.assertEqual(len(windows["李白"]), rows)


def main() -> int:
    suite = unittest.defaultTestLoader.loadTestsFromModule(__import__(__name__))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
