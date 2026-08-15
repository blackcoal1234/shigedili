#!/usr/bin/env python3
"""Regression checks for the merged 88-poet fact-expansion release."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from html import unescape
from collections import Counter
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))

from poem_fact_expansion import build_expansion_record, validate_fact_package  # noqa: E402
from build_all_poet_fact_release import (  # noqa: E402
    BASELINE_PACKAGES,
    BATCHES,
    EXPANSIONS,
    PACKAGES,
    POEMS,
    SHARDS,
    SUMMARY,
    FactPackageError,
    load_json,
    load_jsonl,
    reject_encoding_damage,
    validate_shard_semantics,
    validate_cross_batch_sources,
    transactional_replace_many,
    validate_status,
)


BUILD = TOOLS / "build_all_poet_fact_release.py"


class AllPoetFactReleaseTests(unittest.TestCase):
    maxDiff = None

    @classmethod
    def setUpClass(cls) -> None:
        cls.poems = load_json(POEMS)
        cls.packages = load_jsonl(PACKAGES)
        cls.expansions = load_jsonl(EXPANSIONS)
        cls.summary = load_json(SUMMARY)
        cls.poet_order = list(dict.fromkeys(row.get("poet", row.get("author")) for row in cls.poems))

    def test_corpus_and_batch_rosters_partition_88_poets(self) -> None:
        assigned = [poet for batch in BATCHES.values() for poet in batch]
        self.assertEqual(len(self.poet_order), 88)
        self.assertEqual(len(assigned), 82)
        self.assertEqual(len(set(assigned)), 82)
        self.assertEqual(set(self.poet_order) - set(assigned), {"李白", "杜甫", "白居易", "苏轼", "陆游", "李清照"})

    def test_every_shard_is_clean_and_status_matches_verified_rows(self) -> None:
        for batch_id, expected in BATCHES.items():
            with self.subTest(batch=batch_id):
                verified = load_jsonl(SHARDS / f"batch_{batch_id}_verified.jsonl")
                status = load_json(SHARDS / f"batch_{batch_id}_status.json")
                reject_encoding_damage(status, f"batch {batch_id} status")
                reject_encoding_damage(verified, f"batch {batch_id} verified")
                held, counts = validate_status(batch_id, status, verified, self.poems)
                self.assertEqual(sum(counts.values()), len(expected))
                self.assertEqual(len(held), counts.get("hold", 0))
                for package in verified:
                    self.assertEqual(validate_fact_package(package, self.poems)["status"], "verified")
                    validate_shard_semantics(package, batch_id)

    def test_release_identity_gate_and_no_duplicates(self) -> None:
        identities = []
        hashes = []
        for package in self.packages:
            with self.subTest(poem=package["poem_key"]):
                self.assertEqual(validate_fact_package(package, self.poems)["status"], "verified")
                key = package["poem_key"]
                identities.append((key["poet"], key["title"], key["body_hash"]))
                hashes.append(key["body_hash"])
        self.assertEqual(len(identities), len(set(identities)))
        self.assertEqual(len(hashes), len(set(hashes)))
        baseline_hashes = {row["poem_key"]["body_hash"] for row in load_jsonl(BASELINE_PACKAGES)}
        self.assertTrue(baseline_hashes <= set(hashes))

    def test_expansions_are_derived_one_to_one(self) -> None:
        by_hash = {row["poem_key"]["body_hash"]: row for row in self.expansions}
        self.assertEqual(len(by_hash), len(self.packages))
        self.assertEqual(set(by_hash), {row["poem_key"]["body_hash"] for row in self.packages})
        for package in self.packages:
            expected = build_expansion_record(package, self.poems)
            self.assertEqual(by_hash[package["poem_key"]["body_hash"]], expected)
            self.assertTrue(expected["fact_summary"])
            self.assertTrue(expected["expansion_text"])
            self.assertIn(package["poem_key"]["title"], expected["fact_summary"])
            self.assertIn(package["chronology"]["modern_place"], expected["fact_summary"])
            if package["chronology"]["year_precision"] == "approximate":
                self.assertIn("约系于", expected["fact_summary"])
            self.assertGreaterEqual(len(expected["sources"]), 2)
        texts = [row["expansion_text"] for row in self.expansions]
        self.assertEqual(len(texts), len(set(texts)))

    def test_summary_is_honest_and_accounts_for_all_poets(self) -> None:
        summary = self.summary
        package_counts = Counter(row["poem_key"]["poet"] for row in self.packages)
        verified = [poet for poet in self.poet_order if package_counts[poet]]
        missing = [poet for poet in self.poet_order if not package_counts[poet]]
        self.assertEqual(summary["coverage_target_poets"], 88)
        self.assertEqual(summary["verified_poet_count"], len(verified))
        self.assertEqual(summary["missing_poet_count"], len(missing))
        self.assertEqual(summary["held_back_poet_count"], len(summary["held_back"]))
        self.assertEqual(summary["release_count"], len(self.packages))
        coordinate_rows = [
            row
            for row in self.packages
            if row["chronology"].get("lon") is not None
            and row["chronology"].get("lat") is not None
        ]
        self.assertEqual(summary["coordinate_package_count"], len(coordinate_rows))
        self.assertEqual(
            summary["coordinate_poet_count"],
            len({row["poem_key"]["poet"] for row in coordinate_rows}),
        )
        self.assertEqual(summary["verified_poets"], verified)
        self.assertEqual(summary["missing_poets"], missing)
        self.assertEqual(summary["coverage_complete"], not missing)
        self.assertEqual(summary["release_status"], "complete" if not missing else "partial")
        self.assertEqual(summary["poet_counts"], {poet: package_counts[poet] for poet in verified})
        self.assertEqual(sum(row["assigned"] for row in summary["batch_stats"].values()), 82)
        self.assertEqual(sum(row["verified"] for row in summary["batch_stats"].values()), summary["new_verified_count"])
        self.assertEqual(sum(row["hold"] for row in summary["batch_stats"].values()), len(summary["held_back"]))
        self.assertEqual(len(summary["held_back"]), len(missing))
        self.assertEqual(summary["held_back_poet_count"], len(missing))
        if missing:
            self.assertIn(f"{len(verified)}/88", summary["scope_note"])
        else:
            self.assertIn("88位诗人", summary["scope_note"])

    def test_encoding_damage_is_rejected(self) -> None:
        with self.assertRaisesRegex(FactPackageError, "encoding-damaged"):
            reject_encoding_damage({"reason": "????????"}, "fixture")
        reject_encoding_damage({"source_url": "https://example.test/item?id=1"}, "fixture")

    def test_expansion_schema_and_aggregate_chronology_sources_are_rejected(self) -> None:
        with self.assertRaisesRegex(FactPackageError, "expansion record"):
            validate_shard_semantics(
                {"composition": {}, "sources": [], "context_facts": []}, "fixture"
            )
        package = {
            "context_facts": [],
            "evidence": [{
                "excerpt": "搜韵地理首页仅用于导航。",
                "source_url": "https://sou-yun.cn/PoemGeo.aspx",
                "supports": ["composition_place"],
            }],
        }
        with self.assertRaisesRegex(FactPackageError, "aggregate"):
            validate_shard_semantics(package, "fixture")

    def test_chronology_values_must_be_visible_in_evidence(self) -> None:
        package = json.loads(json.dumps(load_jsonl(SHARDS / "batch_01_verified.jsonl")[0], ensure_ascii=False))
        package["chronology"]["year_start"] = 9999
        package["chronology"]["year_end"] = 9999
        with self.assertRaisesRegex(FactPackageError, "year_start is not visible"):
            validate_shard_semantics(package, "fixture")

    def test_secondary_identity_only_sources_are_not_misgraded(self) -> None:
        for package in self.packages:
            if package["verification"]["reviewer"] != "codex_parallel_fact_audit_2026-08-13":
                continue
            for source in package["evidence"]:
                if source["supports"] == []:
                    self.assertIn(source["source_grade"], {"C", "D"})

    def test_no_conflict_language_in_verified_claim_evidence(self) -> None:
        conflict_terms = ("争议", "两说", "待考", "存疑", "未定", "disputed")
        for package in self.packages:
            if package["verification"]["reviewer"] != "codex_parallel_fact_audit_2026-08-13":
                continue
            for source in package["evidence"]:
                if source["supports"]:
                    folded = unescape(source["excerpt"]).casefold()
                    self.assertFalse(any(term in folded for term in conflict_terms))
            for fact in package["context_facts"]:
                folded = unescape(fact["text"]).casefold()
                self.assertFalse(any(term in folded for term in conflict_terms))

    def test_status_package_mismatch_is_rejected(self) -> None:
        batch_id = "01"
        rows = [
            {"poet": poet, "status": "hold", "title": "待核", "body_hash": "", "reason": "缺少直接创作地点证据", "sources": []}
            for poet in BATCHES[batch_id]
        ]
        status = {"schema_version": 1, "batch_id": batch_id, "assigned_poets": list(BATCHES[batch_id]), "results": rows}
        baseline_package = load_jsonl(BASELINE_PACKAGES)[0]
        with self.assertRaisesRegex(FactPackageError, "unassigned poet"):
            validate_status(batch_id, status, [baseline_package])
        status["results"][0]["status"] = "verified"
        with self.assertRaisesRegex(FactPackageError, "exactly one package"):
            validate_status(batch_id, status, [])

    def test_hold_status_must_reference_an_exact_local_poem(self) -> None:
        batch_id = "01"
        rows = [
            {"poet": poet, "status": "hold", "title": "待核", "body_hash": "missing", "reason": "缺少直接创作地点证据。", "sources": []}
            for poet in BATCHES[batch_id]
        ]
        status = {"schema_version": 1, "batch_id": batch_id, "assigned_poets": list(BATCHES[batch_id]), "results": rows}
        with self.assertRaisesRegex(FactPackageError, "status poem identity mismatch"):
            validate_status(batch_id, status, [], self.poems)

    def test_direct_work_source_reuse_across_poems_is_rejected(self) -> None:
        first = load_jsonl(BASELINE_PACKAGES)[0]
        second = json.loads(json.dumps(first, ensure_ascii=False))
        second["poem_key"] = dict(first["poem_key"])
        second["poem_key"]["body_hash"] = "different-body-hash"
        with self.assertRaisesRegex(FactPackageError, "reused across poem identities"):
            validate_cross_batch_sources([first, second], {})

    def test_transaction_rolls_back_existing_and_absent_targets(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            existing = root / "existing.json"
            absent = root / "absent.json"
            existing.write_bytes(b"old")
            staged_existing = root / "existing.new"
            staged_absent = root / "absent.new"
            staged_existing.write_bytes(b"new-existing")
            staged_absent.write_bytes(b"new-absent")
            real_replace = os.replace
            calls = 0

            def fail_second(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> None:
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("injected failure")
                real_replace(src, dst)

            with patch("build_all_poet_fact_release.os.replace", side_effect=fail_second):
                with self.assertRaises(FactPackageError):
                    transactional_replace_many({existing: staged_existing, absent: staged_absent})
            self.assertEqual(existing.read_bytes(), b"old")
            self.assertFalse(absent.exists())
            self.assertFalse(any(path.suffix in {".bak", ".new"} for path in root.iterdir()))

    def test_z_rebuild_is_byte_stable_and_preserves_inputs(self) -> None:
        watched = [BASELINE_PACKAGES]
        watched += [SHARDS / f"batch_{batch_id}_{suffix}" for batch_id in BATCHES for suffix in ("verified.jsonl", "status.json")]
        before_inputs = {path: path.read_bytes() for path in watched}
        before_outputs = {path: path.read_bytes() for path in (PACKAGES, EXPANSIONS, SUMMARY)}
        subprocess.run([sys.executable, str(BUILD)], cwd=ROOT, check=True)
        self.assertEqual(before_inputs, {path: path.read_bytes() for path in watched})
        self.assertEqual(before_outputs, {path: path.read_bytes() for path in before_outputs})

    def test_stage_failure_removes_earlier_temporaries(self) -> None:
        from build_all_poet_fact_release import stage_many

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            first = root / "first.json"
            missing_parent = root / "missing" / "second.json"
            with self.assertRaises(FactPackageError):
                stage_many({first: "one", missing_parent: "two"})
            self.assertFalse(any(path.suffix == ".new" for path in root.iterdir()))


if __name__ == "__main__":
    unittest.main(verbosity=2)
