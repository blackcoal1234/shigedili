from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest


ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = ROOT / "data" / "analysis" / "famous_poets_full_manifest.json"
CANONICAL_PATH = ROOT / "data" / "poems.json"
EMOTION_PATH = ROOT / "data" / "stylometry" / "emotion_profiles.json"
SOUND_PATH = ROOT / "data" / "stylometry" / "sound_stats.json"
AGE_ASSET = ROOT / "output" / "assets" / "competition" / "age_data.json"
SOUND_ASSET = ROOT / "output" / "assets" / "competition" / "sound_page_data.json"


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def corpus_contract() -> dict[str, Any]:
    manifest = load_json(MANIFEST_PATH)
    canonical = load_json(CANONICAL_PATH)
    emotion = load_json(EMOTION_PATH)
    sound = load_json(SOUND_PATH)
    return {
        "manifest": manifest,
        "canonical": canonical,
        "emotion": emotion,
        "sound": sound,
        "emotion_by_work_id": {
            row["work_id"]: row for row in emotion["profiles"]
        },
        "sound_by_work_id": {
            row["work_id"]: row for row in sound["per_poem"]
        },
    }


def assert_identity(row: dict[str, Any]) -> None:
    assert set(("work_id", "canonical_gushiwen_id", "body_hash")) <= row.keys()
    assert isinstance(row["work_id"], str) and row["work_id"].startswith("fw_")
    assert isinstance(row["body_hash"], str) and len(row["body_hash"]) == 64
    canonical_id = row["canonical_gushiwen_id"]
    assert canonical_id is None or (
        isinstance(canonical_id, str) and canonical_id.strip()
    )


def assert_source_identity(
    published: dict[str, Any], source_by_work_id: dict[str, dict[str, Any]]
) -> None:
    assert_identity(published)
    source = source_by_work_id[published["work_id"]]
    assert published["body_hash"] == source["body_hash"]
    assert published["canonical_gushiwen_id"] == source.get(
        "canonical_gushiwen_id"
    )


def test_viz36_publishes_stable_identity_and_dual_corpus_metadata(
    corpus_contract: dict[str, Any],
) -> None:
    payload = load_json(AGE_ASSET)
    manifest = corpus_contract["manifest"]
    canonical = corpus_contract["canonical"]

    assert payload["corpus_source"] == "analysis_full"
    assert payload["corpus_path"] == "data/analysis/famous_poets_full.jsonl.gz"
    assert payload["analysis_count"] == manifest["record_count"]
    assert payload["canonical_evidence_count"] == manifest["canonical_count"]
    assert payload["canonical_evidence_count"] == len(canonical)

    poems = [poem for poet in payload["poets"] for poem in poet["poems"]]
    assert poems
    for poem in poems:
        assert_source_identity(poem, corpus_contract["emotion_by_work_id"])
        assert poem["canonical_gushiwen_id"] is not None

    html = (ROOT / "output" / "36_同龄对齐.html").read_text(encoding="utf-8")
    assert "状态层" in html
    assert "证据层" in html


def test_viz37_publishes_stable_identity_and_dual_corpus_metadata(
    corpus_contract: dict[str, Any],
) -> None:
    payload = load_json(SOUND_ASSET)
    meta = payload["meta"]
    manifest = corpus_contract["manifest"]
    canonical = corpus_contract["canonical"]

    assert meta["corpus_source"] == "analysis_full"
    assert meta["corpus_path"] == "data/analysis/famous_poets_full.jsonl.gz"
    assert meta["analysis_count"] == manifest["record_count"]
    assert meta["canonical_evidence_count"] == manifest["canonical_count"]
    assert meta["canonical_evidence_count"] == len(canonical)

    analysis_works = list(payload["topPoems"])
    analysis_works.extend(
        poem for poet in payload["poets"] for poem in poet["audible"]
    )
    assert analysis_works
    for poem in analysis_works:
        assert_source_identity(poem, corpus_contract["sound_by_work_id"])

    star_works = [payload["star"]["pipa"]]
    star_works.extend(payload["star"]["wangwei"]["poems"])
    star_works.extend(payload["star"]["border"]["dufu"]["poems"])
    star_works.extend(payload["star"]["border"]["gaoshi"]["poems"])
    canonical_ids = {
        poem["source_poem_id"] for poem in canonical if poem.get("source_poem_id")
    }
    for poem in star_works:
        assert_source_identity(poem, corpus_contract["sound_by_work_id"])
        assert poem["canonical_gushiwen_id"] in canonical_ids

    html = (ROOT / "output" / "37_可听的诗.html").read_text(encoding="utf-8")
    assert "状态层" in html
    assert "证据层" in html


def test_viz36_viz37_do_not_freeze_corpus_counts(
    corpus_contract: dict[str, Any],
) -> None:
    manifest = corpus_contract["manifest"]
    for name in ("viz_36_age_align.py", "viz_37_soundscape.py"):
        source = (ROOT / "数据可视化脚本" / name).read_text(encoding="utf-8")
        assert str(manifest["record_count"]) not in source
        assert str(manifest["canonical_count"]) not in source
