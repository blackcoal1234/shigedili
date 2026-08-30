from __future__ import annotations

import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "数据可视化脚本"
OUTPUT = ROOT / "output" / "assets" / "competition"
sys.path.insert(0, str(ROOT / "tools"))

from famous_poet_corpus import load_analysis_poems  # noqa: E402


def load_module(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_output(name: str) -> dict:
    return json.loads((OUTPUT / name).read_text(encoding="utf-8"))


def test_year759_uses_stable_identity_before_legacy_hash() -> None:
    module = load_module("viz33_identity_test", "viz_33_year759.py")
    shared_hash = "same-legacy-hash"
    rows = [
        {
            "poet": "白居易",
            "body_hash": shared_hash,
            "work_id": "fw-a",
            "canonical_gushiwen_id": "canonical-a",
        },
        {
            "poet": "白居易",
            "body_hash": shared_hash,
            "work_id": "fw-b",
            "canonical_gushiwen_id": "canonical-b",
        },
    ]
    indexes = module.index_emotion_profiles(rows)
    selected = module.emotion_for_poem(
        indexes,
        {"author": "白居易", "source_poem_id": "canonical-b", "body_hash": shared_hash},
    )
    assert selected["work_id"] == "fw-b"
    with pytest.raises(ValueError, match="非唯一"):
        module.emotion_for_poem(indexes, {"author": "白居易", "body_hash": shared_hash})


def test_first_person_profile_fallback_rejects_hash_collision() -> None:
    module = load_module("viz39_identity_test", "viz_39_first_person_lives.py")
    indexes = {
        "by_work_id": {},
        "by_canonical_id": {},
        "by_body_hash": {("白居易", "collision"): [{"work_id": "a"}, {"work_id": "b"}]},
    }
    with pytest.raises(ValueError, match="非唯一"):
        module.profile_for_canonical(
            indexes, {"author": "白居易", "body_hash": "collision"}
        )


def test_imagery_tide_dating_resolves_shared_hash_by_poet_and_work_id(monkeypatch) -> None:
    module = load_module("viz38_dating_identity_test", "viz_38_imagery_tide.py")
    shared_hash = "shared-across-authors"
    rows = [
        {
            "author": "甲诗人",
            "title": "同文甲作",
            "work_id": "work-a",
            "body_hash": shared_hash,
            "body_original_hash": "variant-a",
            "person_period": "唐",
        },
        {
            "author": "乙诗人",
            "title": "同文乙作",
            "work_id": "work-b",
            "body_hash": shared_hash,
            "person_period": "宋",
        },
    ]
    monkeypatch.setattr(
        module,
        "verified_dating_rows",
        lambda: [
            {
                "bodyHash": "variant-a",
                "poet": "甲诗人",
                "title": "同文甲作",
                "yearStart": 849,
                "yearEnd": 849,
                "yearType": "approximate",
                "precisionRaw": "year",
                "tier": "verified-B",
                "grade": "B",
            },
            {
                "bodyHash": shared_hash,
                "poet": "乙诗人",
                "title": "同文乙作",
                "yearStart": 1068,
                "yearEnd": 1068,
                "yearType": "approximate",
                "precisionRaw": "year",
                "tier": "verified-B",
                "grade": "B",
            }
        ],
    )
    monkeypatch.setattr(module, "six_poet_csv_dating_rows", lambda _index: ([], {}))
    monkeypatch.setattr(module, "souyun_dating_rows", lambda _owners: ([], {}))

    by_work_id, works, stats = module.build_dating_table(rows, {})

    assert set(by_work_id) == {"work-a", "work-b"}
    assert {
        row["workId"]: (row["poet"], row["personPeriod"])
        for row in works
    } == {
        "work-a": ("甲诗人", "唐"),
        "work-b": ("乙诗人", "宋"),
    }
    assert by_work_id["work-a"]["bodyHash"] == "variant-a"
    assert by_work_id["work-b"]["bodyHash"] == shared_hash
    assert stats["hashCollisions"] == 1


def test_imagery_tide_year_type_and_even_median_rules() -> None:
    module = load_module("viz38_numeric_rules_test", "viz_38_imagery_tide.py")
    assert module.dating_year_type(800, 801, "exact") == "range"
    assert module.dating_year_type(800, 800, "exact") == "exact"
    assert module.dating_year_type(800, 800, "approximate") == "approximate"
    assert module.standard_median([1.0, 2.0, 9.0, 10.0]) == 5.5


def test_generated_consumers_report_dual_layer_counts() -> None:
    rows, source = load_analysis_poems()
    canonical = json.loads((ROOT / "data" / "poems.json").read_text(encoding="utf-8"))
    periods = Counter(row.get("person_period") for row in rows)

    home = read_output("home_data.json")
    assert home["corpus"]["analysis_source"] == source == "analysis_full"
    assert home["corpus"]["analysis_poems"] == len(rows)
    assert home["corpus"]["n_poems"] == len(canonical)
    assert all(poet["n_analysis"] >= poet["n_corpus"] for poet in home["poets"])

    tide = read_output("imagery_tide_data.json")
    assert tide["meta"]["corpusSource"] == source
    assert tide["meta"]["generatedFromPoems"] == len(rows)
    assert tide["meta"]["canonicalEvidencePoems"] == len(canonical)
    assert tide["meta"]["dynastyCounts"] == {"唐": periods["唐"], "宋": periods["宋"]}
    assert tide["meta"]["aggregatedPoems"] == periods["唐"] + periods["宋"]
    assert tide["meta"]["canonicalIdentityHashFallbacks"] == 0
    assert "data/analysis/famous_poets_full.jsonl.gz" in tide["method"]["sourceHashes"]
    assert all(
        node["linkedPoem"]["workId"] and node["linkedPoem"]["canonicalGushiwenId"]
        for node in tide["historicalLens"]["playbackNodes"]
    )

    dating = read_output("imagery_tide_dating.json")
    records = dating["records"]
    coverage = tide["chronology"]["coverage"]
    corpus_owner = {
        row["work_id"]: (row["author"], row["person_period"])
        for row in rows
    }
    work_ids = [record["workId"] for record in records]
    assert len(work_ids) == len(set(work_ids))
    assert all(
        corpus_owner[record["workId"]] == (record["poet"], record["personPeriod"])
        for record in records
    )
    assert all(
        record["yearType"]
        == ("range" if record["yearStart"] != record["yearEnd"] else (
            "exact" if record["precisionRaw"] in {"exact", "year_month"} else "approximate"
        ))
        for record in records
    )
    in_binary = [record for record in records if record["inBinary"]]
    artifact_tiers = Counter(record["evidenceTier"] for record in in_binary)
    assert len(in_binary) == coverage["datedWorks"]
    assert sum(item["works"] for item in tide["chronology"]["bins"]) == coverage["datedWorks"]
    assert dict(sorted(artifact_tiers.items())) == coverage["byTier"]
    assert sum(coverage["byTier"].values()) == coverage["datedWorks"]

    lives = read_output("first_person_lives_data.json")
    assert lives["project"]["corpus_source"] == source
    assert lives["project"]["corpus_poems"] == len(rows)
    assert lives["project"]["canonical_evidence_poems"] == len(canonical)
    for poet in lives["poets"]:
        if poet["portrait"] is not None:
            assert poet["portrait"]["sample_poems"] == poet["corpus_poems"]
        for chapter in poet["chapters"]:
            work = chapter.get("work")
            if work:
                assert work["work_id"] and work["canonical_gushiwen_id"]

    year759 = read_output("year759_data.json")
    assert year759["meta"]["emotion_corpus_source"] == source
    assert year759["meta"]["emotion_profile_poems"] == len(rows)
    assert all(scene["work_id"] and scene["canonical_gushiwen_id"] for story in year759["stories"] for scene in story["scenes"])


def test_imagery_tide_has_no_retired_fixed_corpus_assertions() -> None:
    source = (SCRIPTS / "viz_38_imagery_tide.py").read_text(encoding="utf-8")
    for retired in ("EXPECTED_CORPUS", "20,437条正文", "813,371", "818,688", "1,632,059"):
        assert retired not in source
    assert "load_analysis_poems" in source
    assert 'row.get("person_period")' in source


def test_imagery_tide_explains_tang_song_change_from_computed_data() -> None:
    tide = read_output("imagery_tide_data.json")
    analysis = tide["changeAnalysis"]
    findings = {item["id"]: item for item in analysis["findings"]}

    assert set(findings) == {
        "category-shift",
        "word-shift",
        "genre-driver",
        "author-driver",
        "chronology-signal",
        "context-shift",
    }
    assert f"{tide['dynastyAggregates']['唐']['ratePer10k']:.2f}" in analysis["thesis"]
    assert f"{tide['dynastyAggregates']['宋']['ratePer10k']:.2f}" in analysis["thesis"]
    assert "作者等权后却变为" in findings["category-shift"]["body"]
    assert "中间箱并非单调" in findings["chronology-signal"]["body"]
    assert "8.4%" in analysis["boundary"]
    assert "不足以证明" in analysis["boundary"]

    words = {row["word"] for row in tide["wordStats"]}
    assert all(
        word in words
        for finding in analysis["findings"]
        for word in finding["evidenceWords"]
    )

    html = (ROOT / "output" / "38_唐宋意象潮汐.html").read_text(encoding="utf-8")
    assert 'id="changeAnalysis"' in html
    assert "renderChangeAnalysis();" in html
    assert analysis["title"] in html
