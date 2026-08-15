"""Offline fixture tests for :mod:`poet_reference_corpus`.

No test in this file performs a real network request.
"""
from __future__ import annotations

import json
import tempfile
import unittest
import urllib.error
from pathlib import Path

from poet_reference_corpus import (
    AssetFetcher,
    AssetSpec,
    BIOGRAPHIES_JSONL,
    CHINESE_POETRY_ASSETS,
    KANRIPO_ASSETS,
    CacheStore,
    FetchResult,
    PoetSpec,
    active_status,
    aliases_for_name,
    biography_rows_for_poet,
    bounded_worker_count,
    build_coverage,
    canonical_json,
    kanripo_rows,
    load_roster,
    merge_by_successful_assets,
    name_match_method,
    parse_author_asset,
    parse_kanripo_catalog,
    resolve_selection,
    stable_id,
    write_jsonl,
)


FIXED_TIME = "2026-08-09T00:00:00+00:00"


def fetch_result(asset: AssetSpec, body: bytes, *, digest: str = "a" * 64) -> FetchResult:
    return FetchResult(
        asset=asset,
        usable=True,
        attempt_status="cache_hit",
        body=body,
        content_sha256=digest,
        retrieved_at=FIXED_TIME,
        from_cache=True,
        http_status=200,
    )


KANRIPO_FIXTURE = """#-*- mode: org; -*-
** KR4d ZB4d 別集類-宋
*** KR4d0001 東坡全集-宋-蘇軾
:PROPERTIES:
:KR_ID: KR4d0001
:_RESP:    （宋）蘇軾撰
:END:
**** 人物
***** 蘇軾
      :PROPERTIES:
      :DYNASTY:  宋
      :FUNCTION: 撰
      :DATES:    1037 - 1101
      :END:
**** 版本
***** WYG
*** KR4d0002 晏幾道詞集-宋
:PROPERTIES:
:KR_ID: KR4d0002
:END:
**** 版本
***** WYG
** KR4c ZB4c 別集類-唐
*** KR4c0001 李太白集-唐-李白
:PROPERTIES:
:KR_ID: KR4c0001
:_RESP:    （唐）李白
:END:
**** 人物
***** 李白
      :PROPERTIES:
      :DYNASTY:  唐
      :FUNCTION: 撰
      :END:
"""


class RosterTests(unittest.TestCase):
    def test_discovers_exactly_88_from_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "poems.json"
            poems = []
            for index in range(88):
                poet = f"诗人{index:02d}"
                dynasty = "唐" if index < 46 else "宋"
                poems.extend(
                    [
                        {"poet": poet, "author": poet, "dynasty": dynasty, "title": "甲"},
                        {"poet": poet, "author": poet, "dynasty": dynasty, "title": "乙"},
                    ]
                )
            path.write_text(json.dumps(poems, ensure_ascii=False), encoding="utf-8")
            roster = load_roster(path)
            self.assertEqual(88, len(roster))
            self.assertEqual(176, sum(item.poem_count for item in roster))
            self.assertEqual({"唐", "宋"}, {item.dynasty for item in roster})

    def test_conflicting_local_dynasty_uses_documented_majority(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "poems.json"
            path.write_text(
                json.dumps(
                    [
                        {"author": "甲", "dynasty": "唐"},
                        {"author": "甲", "dynasty": "唐"},
                        {"author": "甲", "dynasty": "宋"},
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            poet = load_roster(path)[0]
            self.assertEqual("唐", poet.dynasty)
            self.assertEqual(3, poet.poem_count)
            self.assertEqual("majority_local_label", poet.dynasty_resolution)
            self.assertEqual((("唐", 2), ("宋", 1)), poet.dynasty_counts)

    def test_tied_local_dynasty_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "poems.json"
            path.write_text(
                json.dumps(
                    [
                        {"author": "甲", "dynasty": "唐"},
                        {"author": "甲", "dynasty": "宋"},
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "tied"):
                load_roster(path)

    def test_explicit_poets_override_scope_and_are_deduplicated(self) -> None:
        roster = [PoetSpec("李白", "唐", 1), PoetSpec("杜甫", "唐", 1)]
        self.assertEqual(["杜甫", "李白"], resolve_selection(roster, "core", "杜甫,李白,杜甫"))
        with self.assertRaisesRegex(ValueError, "unknown"):
            resolve_selection(roster, "all", "不存在")


class NameAndBiographyTests(unittest.TestCase):
    def test_simplified_traditional_aliases_are_exact(self) -> None:
        self.assertIn("蘇軾", aliases_for_name("苏轼"))
        self.assertIn("陸九淵", aliases_for_name("陆九渊"))
        self.assertIn("黄庭堅", aliases_for_name("黄庭坚"))
        self.assertIn("黃庭坚", aliases_for_name("黄庭坚"))
        self.assertEqual("traditional_alias", name_match_method("苏轼", "蘇軾"))
        self.assertEqual("mixed_simplified_traditional_alias", name_match_method("黄庭坚", "黄庭堅"))
        self.assertIsNone(name_match_method("苏轼", "蘇轍"))

    def test_author_asset_and_unique_alias_match(self) -> None:
        asset = CHINESE_POETRY_ASSETS[1]
        body = json.dumps(
            [{"name": "蘇軾", "id": "sushi-1", "desc": "眉州眉山人。"}],
            ensure_ascii=False,
        ).encode("utf-8")
        records, result = parse_author_asset(fetch_result(asset, body))
        rows, status = biography_rows_for_poet(PoetSpec("苏轼", "宋", 20), records, result)
        self.assertEqual("matched", status)
        self.assertEqual(1, len(rows))
        self.assertEqual("traditional_alias", rows[0]["match_method"])
        self.assertEqual("眉州眉山人。", rows[0]["desc"])
        self.assertEqual(asset.url, rows[0]["source_url"])

    def test_duplicate_same_name_is_ambiguous_and_not_auto_selected(self) -> None:
        asset = CHINESE_POETRY_ASSETS[1]
        body = json.dumps(
            [
                {"name": "蘇軾", "id": "one", "desc": "甲"},
                {"name": "蘇軾", "id": "two", "desc": "乙"},
            ],
            ensure_ascii=False,
        ).encode("utf-8")
        records, result = parse_author_asset(fetch_result(asset, body))
        rows, status = biography_rows_for_poet(PoetSpec("苏轼", "宋", 20), records, result)
        self.assertEqual("ambiguous", status)
        self.assertEqual(2, len(rows))
        self.assertEqual({"ambiguous"}, {row["match_status"] for row in rows})


class KanripoTests(unittest.TestCase):
    def setUp(self) -> None:
        asset = KANRIPO_ASSETS[1]
        result = fetch_result(asset, KANRIPO_FIXTURE.encode("utf-8"), digest="b" * 64)
        self.records, self.result = parse_kanripo_catalog(result)

    def test_catalog_parser_extracts_records_people_and_responsibility(self) -> None:
        self.assertTrue(self.result.usable)
        self.assertEqual(3, len(self.records))
        first = self.records[0]
        self.assertEqual("KR4d0001", first.kr_id)
        self.assertEqual("東坡全集", first.title)
        self.assertEqual("（宋）蘇軾撰", first.responsibility)
        self.assertEqual("蘇軾", first.people[0].name)
        self.assertEqual("宋", first.people[0].dynasty)

    def test_structural_match_is_matched_title_only_is_ambiguous(self) -> None:
        roster = [
            PoetSpec("苏轼", "宋", 20),
            PoetSpec("晏几道", "宋", 20),
            PoetSpec("李白", "唐", 20),
        ]
        rows, outcomes = kanripo_rows(roster, self.records)
        self.assertEqual("matched", outcomes["苏轼"])
        self.assertEqual("ambiguous", outcomes["晏几道"])
        self.assertEqual("matched", outcomes["李白"])
        sushi = next(row for row in rows if row["poet"] == "苏轼")
        self.assertIn("person_exact", sushi["match_methods"])
        self.assertIn("responsibility_exact", sushi["match_methods"])
        yan = next(row for row in rows if row["poet"] == "晏几道")
        self.assertEqual(["title_contains_alias"], yan["match_methods"])
        self.assertLessEqual(max(map(len, yan["evidence"])), 280)

    def test_dynasty_mismatch_is_not_a_match(self) -> None:
        rows, outcomes = kanripo_rows([PoetSpec("李白", "宋", 1)], self.records)
        self.assertEqual([], rows)
        self.assertEqual("not_found", outcomes["李白"])

    def test_two_explicit_responsible_people_are_not_treated_as_identity_collision(self) -> None:
        fixture = """** KR4d ZB4d 別集類-宋
*** KR4d9999 二家合編-宋
:PROPERTIES:
:_RESP:    （宋）蘇軾,（宋）黃庭堅
:END:
**** 人物
***** 蘇軾
      :PROPERTIES:
      :DYNASTY: 宋
      :FUNCTION: 撰
      :END:
***** 黃庭堅
      :PROPERTIES:
      :DYNASTY: 宋
      :FUNCTION: 編
      :END:
"""
        records, _result = parse_kanripo_catalog(
            fetch_result(KANRIPO_ASSETS[1], fixture.encode("utf-8"), digest="c" * 64)
        )
        rows, outcomes = kanripo_rows(
            [PoetSpec("苏轼", "宋", 1), PoetSpec("黄庭坚", "宋", 1)],
            records,
        )
        self.assertEqual({"matched"}, {row["match_status"] for row in rows})
        self.assertEqual({"苏轼": "matched", "黄庭坚": "matched"}, outcomes)

    def test_parsing_and_rows_are_deterministic(self) -> None:
        roster = [PoetSpec("苏轼", "宋", 20), PoetSpec("李白", "唐", 20)]
        first_rows, first_outcomes = kanripo_rows(roster, self.records)
        second_records, _ = parse_kanripo_catalog(
            fetch_result(KANRIPO_ASSETS[1], KANRIPO_FIXTURE.encode("utf-8"), digest="b" * 64)
        )
        second_rows, second_outcomes = kanripo_rows(roster, second_records)
        self.assertEqual(first_rows, second_rows)
        self.assertEqual(first_outcomes, second_outcomes)
        self.assertEqual(canonical_json(first_rows), canonical_json(second_rows))


class CacheAndMergeTests(unittest.TestCase):
    def test_offline_cache_requires_valid_checksum(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache = CacheStore(Path(tmp))
            asset = CHINESE_POETRY_ASSETS[0]
            meta = cache.store(
                asset.url,
                b"fixture-body",
                retrieved_at=FIXED_TIME,
                content_type="application/json",
            )
            fetcher = AssetFetcher(
                cache,
                offline=True,
                opener=lambda *_args, **_kwargs: self.fail("offline mode attempted network"),
            )
            result = fetcher.fetch(asset)
            self.assertTrue(result.usable)
            self.assertEqual("cache_hit", result.attempt_status)
            (Path(tmp) / "bodies" / meta["body_file"]).write_bytes(b"corrupt")
            corrupt = fetcher.fetch(asset)
            self.assertFalse(corrupt.usable)
            self.assertEqual("fetch_failed", corrupt.attempt_status)
            self.assertIn("checksum", corrupt.error)

    def test_network_failure_uses_old_valid_cache_and_records_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache = CacheStore(Path(tmp))
            asset = CHINESE_POETRY_ASSETS[0]
            cache.store(asset.url, b"[]", retrieved_at=FIXED_TIME)

            def fail(*_args: object, **_kwargs: object) -> object:
                raise urllib.error.URLError("fixture offline")

            result = AssetFetcher(cache, retries=0, opener=fail, sleeper=lambda _n: None).fetch(asset)
            self.assertTrue(result.usable)
            self.assertTrue(result.from_cache)
            self.assertEqual("fetch_failed_cache_used", result.attempt_status)
            self.assertIn("fixture offline", result.error)

    def test_failed_asset_preserves_old_success_rows(self) -> None:
        old = [
            {
                "reference_id": "old",
                "poet": "苏轼",
                "source_url": "https://fixture.invalid/source",
                "match_status": "matched",
            }
        ]
        merged = merge_by_successful_assets(
            old,
            [],
            successful_urls=set(),
            selected_poets={"苏轼"},
            sort_key=lambda row: (str(row["reference_id"]),),
        )
        self.assertEqual(old, merged)
        self.assertEqual("matched", active_status(merged))

    def test_jsonl_atomic_output_has_stable_order_and_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rows.jsonl"
            rows = [{"b": 2, "a": 1}, {"b": 3, "a": 2}]
            write_jsonl(path, rows)
            first = path.read_bytes()
            write_jsonl(path, rows)
            self.assertEqual(first, path.read_bytes())
            self.assertNotIn(b".tmp", first)

    def test_global_file_workers_are_capped_at_two(self) -> None:
        self.assertEqual(1, bounded_worker_count(16, 1))
        self.assertEqual(2, bounded_worker_count(16, 5))
        self.assertEqual(1, bounded_worker_count(1, 5))


class CoverageTests(unittest.TestCase):
    def test_coverage_has_all_88_and_four_explicit_source_states(self) -> None:
        roster = [
            PoetSpec(name=f"诗人{index:02d}", dynasty="唐" if index < 46 else "宋", poem_count=1)
            for index in range(88)
        ]
        author_results = [
            fetch_result(CHINESE_POETRY_ASSETS[0], b"[]"),
            fetch_result(CHINESE_POETRY_ASSETS[1], b"[]"),
        ]
        catalog_results = [fetch_result(asset, b"fixture") for asset in KANRIPO_ASSETS]
        outcomes = {poet.name: "not_found" for poet in roster}
        coverage = build_coverage(
            roster,
            scope="all",
            selected_poets=[poet.name for poet in roster],
            biography_rows=[],
            kanripo_matches=[],
            biography_outcomes=outcomes,
            kanripo_outcomes=outcomes,
            author_results=author_results,
            catalog_results=catalog_results,
            generated_at=FIXED_TIME,
            poems_path=Path("fixture/poems.json"),
        )
        self.assertEqual(88, coverage["corpus"]["poet_count"])
        self.assertEqual(88, len(coverage["per_poet"]))
        allowed = {"matched", "ambiguous", "not_found", "fetch_failed"}
        for row in coverage["per_poet"]:
            self.assertIn(row["chinese_poetry"]["status"], allowed)
            self.assertIn(row["kanripo"]["status"], allowed)
        self.assertEqual({"not_found": 88}, coverage["sources"]["chinese_poetry"]["status_counts"])
        self.assertEqual({"not_found": 88}, coverage["sources"]["kanripo"]["status_counts"])
        notes = " ".join(coverage["interpretation_notes"])
        self.assertIn("不是路线", notes)

    def test_fetch_failure_is_separate_from_old_active_status(self) -> None:
        roster = [PoetSpec("苏轼", "宋", 1)]
        old_row = {"poet": "苏轼", "match_status": "matched"}
        failed = FetchResult(CHINESE_POETRY_ASSETS[1], False, "fetch_failed", error="fixture")
        catalog_failed = [FetchResult(asset, False, "fetch_failed", error="fixture") for asset in KANRIPO_ASSETS]
        coverage = build_coverage(
            roster,
            scope="all",
            selected_poets=["苏轼"],
            biography_rows=[old_row],
            kanripo_matches=[old_row],
            biography_outcomes={},
            kanripo_outcomes={},
            author_results=[failed],
            catalog_results=catalog_failed,
            generated_at=FIXED_TIME,
        )
        item = coverage["per_poet"][0]
        self.assertEqual("fetch_failed", item["chinese_poetry"]["status"])
        self.assertEqual("matched", item["chinese_poetry"]["active_status"])
        self.assertEqual("fetch_failed", item["kanripo"]["status"])
        self.assertEqual("matched", item["kanripo"]["active_status"])


class ContractTests(unittest.TestCase):
    def test_target_paths_stay_in_candidate_layer(self) -> None:
        self.assertEqual("data/candidates", BIOGRAPHIES_JSONL.parent.relative_to(BIOGRAPHIES_JSONL.parents[2]).as_posix())
        self.assertNotIn("reviewed", str(BIOGRAPHIES_JSONL).lower())

    def test_stable_id_distinguishes_records(self) -> None:
        self.assertNotEqual(stable_id("a", 0), stable_id("a", "0"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
