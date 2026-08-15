#!/usr/bin/env python3
"""Regression tests for the verified poem fact expansion gate."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path


TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from poem_fact_expansion import (  # noqa: E402
    FactPackageError,
    build_expansion_record,
    build_file,
    validate_fact_package,
)


class PoemFactExpansionTests(unittest.TestCase):
    maxDiff = None

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.body = "朝辞白帝彩云间，千里江陵一日还。"
        self.body_hash = hashlib.sha256(self.body.encode("utf-8")).hexdigest()
        self.poems = [
            {
                "poet": "李白",
                "author": "李白",
                "title": "早发白帝城",
                "dynasty": "唐",
                "body": self.body,
                "body_hash": self.body_hash,
            }
        ]
        self.poems_path = self.root / "poems.json"
        self.poems_path.write_text(
            json.dumps(self.poems, ensure_ascii=False), encoding="utf-8"
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def make_package(self) -> dict:
        return {
            "poem_key": {
                "poet": "李白",
                "title": "早发白帝城",
                "dynasty": "唐",
                "body_hash": self.body_hash,
            },
            "chronology": {
                "year_start": 759,
                "year_end": 759,
                "year_precision": "year",
                "historical_place": "白帝城",
                "modern_place": "重庆市奉节县",
                "province": "重庆市",
                "lon": 109.57,
                "lat": 31.05,
            },
            "evidence": [
                {
                    "evidence_id": "ev-cnk",
                    "source_family": "cnkgraph",
                    "source_name": "中国历代人物传记资料库",
                    "source_url": "https://example.test/cnk/1",
                    "source_grade": "A",
                    "supports": ["composition_date", "composition_place"],
                    "excerpt": "资料记载此诗作于乾元二年，地点为白帝城。",
                },
                {
                    "evidence_id": "ev-local",
                    "source_family": "local_gazetteer",
                    "source_name": "奉节县志",
                    "source_url": "https://example.test/gazetteer/2",
                    "source_grade": "B",
                    "supports": ["composition_date", "composition_place"],
                    "excerpt": "方志材料将作年与白帝城行旅相联系。",
                },
            ],
            "context_facts": [
                {
                    "fact_id": "fact-1",
                    "text": "诗题中的白帝城位于今重庆市奉节县。",
                    "evidence_ids": ["ev-cnk", "ev-local"],
                },
                {
                    "fact_id": "fact-2",
                    "text": "两份材料均把创作地点记为白帝城。",
                    "evidence_ids": ["ev-local"],
                },
            ],
            "verification": {
                "status": "verified",
                "reviewer": "reviewer-1",
                "reviewed_at": "2026-08-12T10:00:00+08:00",
                "controversy_note": "",
            },
        }

    def write_jsonl(self, path: Path, rows: list[dict]) -> None:
        path.write_text(
            "".join(
                json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
                for row in rows
            ),
            encoding="utf-8",
        )

    def test_valid_two_independent_ab_sources_is_strong(self) -> None:
        package = self.make_package()
        validated = validate_fact_package(package, self.poems)
        self.assertEqual(validated["fact_verdict"], "strongly_corroborated")

        record = build_expansion_record(package, self.poems)
        self.assertEqual(record["schema_version"], 1)
        self.assertEqual(record["fact_verdict"], "strongly_corroborated")
        self.assertEqual(
            record["fact_summary"],
            "据已核来源，《早发白帝城》系于759，创作地点记为白帝城；今地对应重庆市奉节县。",
        )
        self.assertEqual(
            record["expansion_text"],
            record["fact_summary"]
            + package["context_facts"][0]["text"]
            + package["context_facts"][1]["text"],
        )
        self.assertEqual(record["method"], "verified_fact_expansion_v1")
        self.assertEqual(record["composition"], package["chronology"])
        self.assertEqual(record["sources"], package["evidence"])

    def test_range_fact_summary_interpolates_real_year_end(self) -> None:
        package = self.make_package()
        package["chronology"]["year_start"] = 759
        package["chronology"]["year_end"] = 762
        package["chronology"]["year_precision"] = "range"

        record = build_expansion_record(package, self.poems)

        self.assertIsNotNone(record)
        self.assertEqual(
            record["fact_summary"],
            "据已核来源，《早发白帝城》系于759—762，创作地点记为白帝城；今地对应重庆市奉节县。",
        )
        self.assertNotIn('chronology["year_end"]', record["fact_summary"])

    def test_approximate_summary_marks_uncertainty_and_deduplicates_province(self) -> None:
        package = self.make_package()
        package["chronology"]["year_precision"] = "approximate"
        package["chronology"]["modern_place"] = "奉节县"

        record = build_expansion_record(package, self.poems)

        self.assertIsNotNone(record)
        self.assertEqual(
            record["fact_summary"],
            "据已核来源，《早发白帝城》约系于759，创作地点记为白帝城；今地对应重庆市奉节县。",
        )

    def test_one_ab_plus_independent_c_is_corroborated(self) -> None:
        package = self.make_package()
        package["evidence"][1]["source_grade"] = "C"
        package["evidence"][1]["supports"] = ["historical_context"]
        package["context_facts"] = []
        validated = validate_fact_package(package, self.poems)
        self.assertEqual(validated["fact_verdict"], "corroborated")

    def test_aliases_from_same_source_family_are_not_independent(self) -> None:
        package = self.make_package()
        package["evidence"][1]["source_family"] = "open.cnkgraph"
        self.assert_invalid(package, "source_family")

    def test_other_known_family_aliases_are_collapsed(self) -> None:
        aliases = [
            ("gushiwen", "so.gushiwen"),
            ("gushiwen", "guwendao"),
            ("souyun", "api.sou-yun"),
        ]
        for first, second in aliases:
            with self.subTest(first=first, second=second):
                package = self.make_package()
                package["evidence"][0]["source_family"] = first
                package["evidence"][1]["source_family"] = second
                self.assert_invalid(package, "source_family")

    def test_body_hash_must_match_exactly_once(self) -> None:
        wrong = self.make_package()
        wrong["poem_key"]["body_hash"] = "0" * 64
        self.assert_invalid(wrong, "body_hash")

        duplicate_poems = self.poems + [copy.deepcopy(self.poems[0])]
        self.assert_invalid(self.make_package(), "body_hash", poems=duplicate_poems)

    def assert_invalid(
        self,
        package: dict,
        pattern: str | None = None,
        *,
        poems: list[dict] | None = None,
    ) -> None:
        with self.assertRaises(FactPackageError) as raised:
            validate_fact_package(package, self.poems if poems is None else poems)
        if pattern is not None:
            self.assertIn(pattern, str(raised.exception))

    def test_poem_identity_fields_are_exact(self) -> None:
        for field, value in (
            ("poet", "李 白"),
            ("title", "早发白帝城（其一）"),
            ("dynasty", "唐代"),
        ):
            with self.subTest(field=field):
                package = self.make_package()
                package["poem_key"][field] = value
                self.assert_invalid(package, field)

    def test_year_rules_reject_disputed_unknown_and_bad_ranges(self) -> None:
        bad_values = [
            ("year_precision", "disputed"),
            ("year_precision", "unknown"),
            ("year_start", "759"),
            ("year_end", 758),
            ("year_start", True),
        ]
        for field, value in bad_values:
            with self.subTest(field=field, value=value):
                package = self.make_package()
                package["chronology"][field] = value
                self.assert_invalid(package)

    def test_verified_requires_reviewer_reviewed_at_and_no_controversy(self) -> None:
        for field, value in (
            ("reviewer", ""),
            ("reviewed_at", ""),
            ("controversy_note", "尚有争议"),
            ("controversy_note", " "),
        ):
            with self.subTest(field=field):
                package = self.make_package()
                package["verification"][field] = value
                self.assert_invalid(package, field)

    def test_verification_status_is_closed_enum(self) -> None:
        package = self.make_package()
        package["verification"]["status"] = "draft"
        self.assert_invalid(package, "status")

    def test_context_fact_requires_existing_evidence_and_nonempty_text(self) -> None:
        package = self.make_package()
        package["context_facts"][0]["evidence_ids"] = ["missing"]
        self.assert_invalid(package, "evidence_id")

        package = self.make_package()
        package["context_facts"][0]["evidence_ids"] = []
        self.assert_invalid(package, "evidence")

        package = self.make_package()
        package["context_facts"][0]["text"] = ""
        self.assert_invalid(package, "text")

        package = self.make_package()
        package["context_facts"][0]["text"] = "史" * 181
        self.assert_invalid(package, "180")

    def test_evidence_ids_are_unique_and_supports_are_closed(self) -> None:
        package = self.make_package()
        package["evidence"][1]["evidence_id"] = "ev-cnk"
        self.assert_invalid(package, "evidence_id")

        package = self.make_package()
        package["evidence"][0]["supports"] = ["composition_date", "rumor"]
        self.assert_invalid(package, "supports")

    def test_url_excerpt_and_coordinate_validation(self) -> None:
        mutations = [
            ("bad URL", lambda p: p["evidence"][0].__setitem__("source_url", "ftp://example.test/x")),
            ("empty excerpt", lambda p: p["evidence"][0].__setitem__("excerpt", "")),
            ("long excerpt", lambda p: p["evidence"][0].__setitem__("excerpt", "引" * 161)),
            ("missing lat", lambda p: p["chronology"].__setitem__("lat", None)),
            ("infinite lon", lambda p: p["chronology"].__setitem__("lon", math.inf)),
            ("lon range", lambda p: p["chronology"].__setitem__("lon", 180.1)),
            ("lat range", lambda p: p["chronology"].__setitem__("lat", -90.1)),
        ]
        for label, mutate in mutations:
            with self.subTest(label=label):
                package = self.make_package()
                mutate(package)
                self.assert_invalid(package)

    def test_empty_place_strings_are_rejected_and_empty_coordinates_allowed(self) -> None:
        for field in ("historical_place", "modern_place", "province"):
            with self.subTest(field=field):
                package = self.make_package()
                package["chronology"][field] = "  "
                self.assert_invalid(package, field)

        package = self.make_package()
        package["chronology"]["lon"] = None
        package["chronology"]["lat"] = None
        validate_fact_package(package, self.poems)

        package = self.make_package()
        package["chronology"]["lon"] = ""
        package["chronology"]["lat"] = ""
        validate_fact_package(package, self.poems)

    def test_date_and_place_each_need_ab_evidence(self) -> None:
        for unsupported in ("composition_date", "composition_place"):
            with self.subTest(unsupported=unsupported):
                package = self.make_package()
                for evidence in package["evidence"]:
                    evidence["supports"] = [
                        claim for claim in evidence["supports"] if claim != unsupported
                    ]
                self.assert_invalid(package, unsupported)

    def test_expansion_length_limit_is_enforced(self) -> None:
        package = self.make_package()
        package["context_facts"] = [
            {
                "fact_id": f"fact-{index}",
                "text": "史" * 180,
                "evidence_ids": ["ev-cnk"],
            }
            for index in range(4)
        ]
        self.assert_invalid(package, "600")

    def test_hold_is_valid_but_is_not_written(self) -> None:
        hold = self.make_package()
        hold["verification"] = {
            "status": "hold",
            "reviewer": "",
            "reviewed_at": "",
            "controversy_note": "材料待复核",
        }
        validate_fact_package(hold, self.poems)
        self.assertIsNone(build_expansion_record(hold, self.poems))

        input_path = self.root / "input.jsonl"
        output_path = self.root / "output.jsonl"
        self.write_jsonl(input_path, [hold])
        count = build_file(input_path, output_path, self.poems_path)
        self.assertEqual(count, 0)
        self.assertEqual(output_path.read_bytes(), b"")

    def test_build_file_is_sorted_and_byte_idempotent(self) -> None:
        later = self.make_package()
        later["poem_key"] = dict(later["poem_key"])
        later["poem_key"]["title"] = "乙篇"
        later_hash = "b" * 64
        later["poem_key"]["body_hash"] = later_hash

        earlier = self.make_package()
        earlier["poem_key"] = dict(earlier["poem_key"])
        earlier["poem_key"]["title"] = "甲篇"
        earlier_hash = "a" * 64
        earlier["poem_key"]["body_hash"] = earlier_hash

        poems = [
            {"poet": "李白", "title": "甲篇", "dynasty": "唐", "body_hash": earlier_hash},
            {"poet": "李白", "title": "乙篇", "dynasty": "唐", "body_hash": later_hash},
        ]
        self.poems_path.write_text(
            json.dumps(poems, ensure_ascii=False), encoding="utf-8"
        )
        input_path = self.root / "input.jsonl"
        output_path = self.root / "output.jsonl"
        self.write_jsonl(input_path, [later, earlier])

        self.assertEqual(build_file(input_path, output_path, self.poems_path), 2)
        first_bytes = output_path.read_bytes()
        self.assertEqual(build_file(input_path, output_path, self.poems_path), 2)
        self.assertEqual(output_path.read_bytes(), first_bytes)

        rows = [json.loads(line) for line in first_bytes.decode("utf-8").splitlines()]
        self.assertEqual([row["poem_key"]["title"] for row in rows], ["乙篇", "甲篇"])
        for line in first_bytes.decode("utf-8").splitlines():
            self.assertEqual(line, json.dumps(json.loads(line), ensure_ascii=False, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    unittest.main(verbosity=2)
