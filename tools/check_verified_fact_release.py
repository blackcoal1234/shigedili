#!/usr/bin/env python3
"""Regression gate for the deterministic 60-poem fact-expansion release."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))

from poem_fact_expansion import build_expansion_record, validate_fact_package  # noqa: E402
from build_verified_fact_release import (  # noqa: E402
    LEGACY_BODY_HASH_REBIND_ALLOWLIST,
    FactPackageError,
    transactional_replace_many,
)

PACKAGES = ROOT / "data/reviewed/verified_poem_fact_packages.jsonl"
EXPANSIONS = ROOT / "data/reviewed/verified_poem_fact_expansions.jsonl"
SUMMARY = ROOT / "data/reviewed/verified_poem_fact_release_summary.json"
BACKGROUND = ROOT / "data/reviewed/verified_poem_backgrounds.jsonl"
CONTEXTS = ROOT / "data/reviewed/verified_poem_contexts.csv"
BUILD = TOOLS / "build_verified_fact_release.py"

REVIEWER = "codex_fact_audit_2026-08-12"
REVIEWED_AT = "2026-08-12T23:30:00+08:00"
EXPECTED_COUNTS = {"李白": 10, "杜甫": 12, "白居易": 8, "苏轼": 10, "陆游": 10, "李清照": 10}
BASELINE_HASH_SNAPSHOT = "d332f1b0a9ad65faf686eb0311bf50d267f14aa13812ac65828bbf5248883e8a"
NEW_TITLES = {
    "李白": {"金陵酒肆留别", "长干行·其一", "月下独酌·其一", "梦游天姥吟留别", "北风行", "赠汪伦"},
    "杜甫": {"望岳", "月夜忆舍弟", "秋兴八首·其一"},
    "白居易": {"池上", "梦微之", "钱塘湖春行"},
    "陆游": {"病起书怀", "秋夜将晓出篱门迎凉有感二首"},
    "李清照": {"武陵春·春晚", "夏日绝句", "渔家傲·记梦", "减字木兰花·卖花担上", "题八咏楼"},
}
NEW_CHRONOLOGY = {
    ("李白", "金陵酒肆留别"): (726, 726, "金陵"), ("李白", "长干行·其一"): (725, 725, "金陵长干里"),
    ("李白", "月下独酌·其一"): (744, 744, "长安"), ("李白", "梦游天姥吟留别"): (745, 746, "东鲁兖州瑕丘"),
    ("李白", "北风行"): (752, 752, "幽州（范阳一带）"), ("李白", "赠汪伦"): (755, 755, "泾县桃花潭"),
    ("杜甫", "望岳"): (736, 736, "泰山（齐鲁）"), ("杜甫", "月夜忆舍弟"): (759, 759, "秦州"), ("杜甫", "秋兴八首·其一"): (766, 766, "夔州"),
    ("白居易", "池上"): (835, 835, "洛阳池上"), ("白居易", "梦微之"): (840, 840, "洛阳"), ("白居易", "钱塘湖春行"): (823, 824, "钱塘湖（西湖）"),
    ("陆游", "病起书怀"): (1176, 1176, "成都"), ("陆游", "秋夜将晓出篱门迎凉有感二首"): (1192, 1192, "山阴"),
    ("李清照", "武陵春·春晚"): (1135, 1135, "金华"), ("李清照", "夏日绝句"): (1129, 1129, "乌江（和州）"),
    ("李清照", "渔家傲·记梦"): (1130, 1130, "浙东海上"), ("李清照", "减字木兰花·卖花担上"): (1101, 1101, "汴京"),
    ("李清照", "题八咏楼"): (1134, 1135, "金华八咏楼"),
}
STOPWORDS = frozenset("本诗 此诗 作品 创作 背景 条目 资料 记载 作者 年月 地点 系于 作于 在于 以及 并且 的了 是为 于 年 月 间" )
CONFLICT_TERMS = ("disputed", "两说并存", "待考", "争议", "驳议")


def jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


class VerifiedFactReleaseTests(unittest.TestCase):
    maxDiff = None

    @classmethod
    def setUpClass(cls) -> None:
        cls.poems = json.loads((ROOT / "data/poems.json").read_text(encoding="utf-8"))
        cls.packages = jsonl(PACKAGES)
        cls.expansions = jsonl(EXPANSIONS)
        cls.summary = json.loads(SUMMARY.read_text(encoding="utf-8"))

    def test_release_shape_and_identity(self) -> None:
        self.assertEqual(len(self.packages), 60)
        hashes = [item["poem_key"]["body_hash"] for item in self.packages]
        self.assertEqual(len(hashes), len(set(hashes)))
        self.assertEqual(Counter(item["poem_key"]["poet"] for item in self.packages), EXPECTED_COUNTS)
        baseline_hashes = sorted(row["poem_key"]["body_hash"] for row in jsonl(BACKGROUND))
        self.assertEqual(hashlib.sha256("\n".join(baseline_hashes).encode()).hexdigest(), BASELINE_HASH_SNAPSHOT)

    def test_all_packages_pass_existing_gate_and_fixed_review_fields(self) -> None:
        for package in self.packages:
            with self.subTest(package=package["poem_key"]):
                validated = validate_fact_package(package, self.poems)
                self.assertEqual(validated["status"], "verified")
                self.assertEqual(package["verification"], {"status": "verified", "reviewer": REVIEWER, "reviewed_at": REVIEWED_AT, "controversy_note": ""})
                self.assertGreaterEqual(len({e["source_family"] for e in package["evidence"]}), 2)
                self.assertTrue(all(len(e["excerpt"]) <= 160 for e in package["evidence"]))
                self.assertTrue(all(len(f["text"]) <= 180 for f in package["context_facts"]))

    def test_evidence_urls_are_direct_and_context_is_source_specific(self) -> None:
        supplements = {
            (row["poet"], row["poem_title"], row["source_url"])
            for row in jsonl(ROOT / "data/candidates/work_chronology_supplements.jsonl")
        }
        for package in self.packages:
            with self.subTest(package=package["poem_key"]):
                evidence = {item["evidence_id"]: item for item in package["evidence"]}
                for item in evidence.values():
                    url = item["source_url"]
                    self.assertNotIn("api.sou-yun.cn/open/Poem", url)
                    self.assertNotIn("search.aspx", url)
                    self.assertNotRegex(url, r"[\s（）。]" )
                    parsed = urlsplit(url)
                    self.assertTrue("/api/" in parsed.path or "shiwenv_" in parsed.path or "open/Poem" in parsed.path)
                    if item["source_family"] == "gushiwen":
                        self.assertNotRegex(item["excerpt"].casefold(), r"cnkgraph|api年谱|mapinfo")
                    self.assertFalse(
                        any(term in item["excerpt"].casefold() for term in CONFLICT_TERMS),
                        item["excerpt"],
                    )
                for fact in package["context_facts"]:
                    self.assertNotIn("编年资料将本诗系于", fact["text"])
                    self.assertNotIn("创作地点记为", fact["text"])
                    self.assertTrue(any(evidence[eid]["excerpt"] != fact["text"] for eid in fact["evidence_ids"]))
                    fact_terms = self.terms(fact["text"])
                    cited_terms = set().union(*(self.terms(evidence[eid]["excerpt"]) for eid in fact["evidence_ids"]))
                    self.assertTrue(fact_terms & cited_terms)
                    self.assertTrue(any(evidence[eid]["supports"] for eid in fact["evidence_ids"]))
                    self.assertTrue(all(evidence[eid]["supports"] for eid in fact["evidence_ids"]))

    @staticmethod
    def terms(value: str) -> set[str]:
        chunks = __import__("re").findall(r"[\u4e00-\u9fff]{2,}", value)
        return {chunk for chunk in chunks if chunk not in STOPWORDS and len(chunk) >= 2}

    def test_required_new_items_and_disambiguations(self) -> None:
        identities = {(p["poem_key"]["poet"], p["poem_key"]["title"]) for p in self.packages}
        for poet, titles in NEW_TITLES.items():
            self.assertTrue({(poet, title) for title in titles} <= identities)
        by_identity = {(p["poem_key"]["poet"], p["poem_key"]["title"]): p for p in self.packages}
        pool = by_identity[("白居易", "池上")]
        poem = next(x for x in self.poems if x["body_hash"] == pool["poem_key"]["body_hash"])
        self.assertTrue(poem["body"].startswith("小娃撑小艇"))
        self.assertIn("a8f44614071a", " ".join(item["source_url"] for item in pool["evidence"]))
        luyou = by_identity[("陆游", "秋夜将晓出篱门迎凉有感二首")]
        luyou_poem = next(x for x in self.poems if x["body_hash"] == luyou["poem_key"]["body_hash"])
        self.assertIn("迢迢天汉西南落", luyou_poem["body"])
        self.assertIn("三万里河东入海", luyou_poem["body"])
        dream = by_identity[("李清照", "渔家傲·记梦")]["chronology"]
        self.assertIn(dream.get("lon"), (None, ""))
        self.assertIn(dream.get("lat"), (None, ""))
        for identity, expected in NEW_CHRONOLOGY.items():
            chronology = by_identity[identity]["chronology"]
            self.assertEqual((chronology["year_start"], chronology["year_end"], chronology["historical_place"]), expected)

    def test_expansions_and_summary(self) -> None:
        self.assertEqual(len(self.expansions), 60)
        self.assertEqual(
            {item["poem_key"]["body_hash"] for item in self.expansions},
            {item["poem_key"]["body_hash"] for item in self.packages},
        )
        for expansion in self.expansions:
            self.assertTrue(expansion["fact_summary"])
            self.assertTrue(expansion["expansion_text"])
            self.assertTrue(expansion["sources"])
            self.assertGreater(len(expansion["expansion_text"]), len(expansion["fact_summary"]))
        texts = [item["expansion_text"] for item in self.expansions]
        self.assertEqual(len(texts), len(set(texts)))
        for package in self.packages:
            record = build_expansion_record(package, self.poems)
            self.assertIsNotNone(record)
            self.assertTrue(record["fact_summary"])
            self.assertTrue(record["expansion_text"])
        self.assertEqual(self.summary["schema_version"], 1)
        self.assertEqual(self.summary["release_count"], 60)
        self.assertEqual(self.summary["poet_counts"], EXPECTED_COUNTS)
        self.assertEqual(len(self.summary["newly_verified"]), 19)
        self.assertEqual(
            {(item["poet"], item["title"]) for item in self.summary["newly_verified"]},
            {(poet, title) for poet, titles in NEW_TITLES.items() for title in titles},
        )
        self.assertEqual(self.summary["held_back"], [])
        self.assertEqual(sum(self.summary["source_family_counts"].values()), 120)
        self.assertEqual(sum(self.summary["verdict_counts"].values()), 60)
        self.assertEqual(len(self.summary["legacy_rebindings"]), 5)
        self.assertEqual(
            {(row["poet"], row["title"], row["old_body_hash"]): row["new_body_hash"] for row in self.summary["legacy_rebindings"]},
            LEGACY_BODY_HASH_REBIND_ALLOWLIST,
        )
        self.assertNotIn(("白居易", "池上"), {(row["poet"], row["title"]) for row in self.summary["legacy_rebindings"]})

    def test_transactional_replace_rolls_back_all_files_on_midway_failure(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            targets = [root / name for name in ("packages", "expansions", "summary")]
            staged = [root / f"{path.name}.new" for path in targets]
            for index, (target, replacement) in enumerate(zip(targets, staged)):
                target.write_bytes(f"old-{index}".encode())
                replacement.write_bytes(f"new-{index}".encode())
            real_replace = os.replace
            calls = 0
            def fail_second(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> None:
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("injected replace failure")
                real_replace(src, dst)
            with patch("build_verified_fact_release.os.replace", side_effect=fail_second):
                with self.assertRaises(FactPackageError):
                    transactional_replace_many(dict(zip(targets, staged)))
            self.assertEqual([target.read_bytes() for target in targets], [b"old-0", b"old-1", b"old-2"])
            self.assertFalse(any(path.suffix in {".bak", ".new"} for path in root.iterdir()))

    def test_input_parse_failures_are_wrapped(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            bad_json = Path(raw) / "bad.jsonl"
            bad_json.write_text("{bad\n", encoding="utf-8")
            from build_verified_fact_release import load_jsonl, load_chronology_file
            with self.assertRaisesRegex(FactPackageError, "failed to parse JSONL"):
                load_jsonl(bad_json)
            bad_csv = Path(raw) / "bad.csv"
            bad_csv.write_text("wrong,headers\nvalue,value\n", encoding="utf-8")
            with self.assertRaisesRegex(FactPackageError, "lacks required columns"):
                load_chronology_file(bad_csv)

    def test_rebuild_is_byte_stable_and_preserves_existing_reviewed_inputs(self) -> None:
        watched = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in (BACKGROUND, CONTEXTS)}
        before = {path: path.read_bytes() for path in (PACKAGES, EXPANSIONS, SUMMARY)}
        subprocess.run([sys.executable, str(BUILD)], cwd=ROOT, check=True)
        self.assertEqual(watched, {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in watched})
        self.assertEqual(before, {path: path.read_bytes() for path in before})


if __name__ == "__main__":
    unittest.main(verbosity=2)
