from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = ROOT / "output" / "assets" / "competition" / "year759_data.json"
HTML_PATH = ROOT / "output" / "33_平行时空759.html"
CANONICAL_PATH = ROOT / "data" / "poems.json"
MANIFEST_PATH = ROOT / "data" / "analysis" / "famous_poets_full_manifest.json"


def test_viz33_metadata_separates_canonical_evidence_and_full_emotion_corpus() -> None:
    payload = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    canonical = json.loads(CANONICAL_PATH.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    meta = payload["meta"]

    assert "corpus_poems" not in meta
    assert meta["canonical_evidence_poems"] == len(canonical)
    assert meta["canonical_evidence_source"] == "canonical"
    assert meta["canonical_evidence_path"] == "data/poems.json"
    assert meta["canonical_evidence_role"] == "display_and_chronology_evidence"
    assert meta["emotion_profile_poems"] == manifest["record_count"]
    assert meta["emotion_corpus_source"] == "analysis_full"
    assert meta["emotion_corpus_path"] == "data/analysis/famous_poets_full.jsonl.gz"
    assert meta["emotion_corpus_role"] == "full_work_textual_emotion_profiles"


def test_viz33_visible_copy_names_both_layers_without_calling_canonical_full() -> None:
    payload = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    html = HTML_PATH.read_text(encoding="utf-8")

    assert "D.meta.canonical_evidence_poems.toLocaleString" in html
    assert '"篇 canonical 展示/编年证据"' in html
    assert "D.meta.emotion_profile_poems.toLocaleString" in html
    assert '" 全作品情感画像"' in html
    assert "篇全量语料" not in html
    assert (
        'textContent="文本情感画像（"+D.meta.emotion_corpus_source+'
        '" 全作品层）："' in html
    )
    assert "两种口径不混算" in html
    assert "双层口径" in payload["method"]["scope_rule"]
