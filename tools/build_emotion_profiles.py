# -*- coding: utf-8 -*-
"""生成全语料细粒度情感档案。"""
from __future__ import annotations

import importlib.util
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = DATA / "stylometry" / "emotion_profiles.json"
sys.path.insert(0, str(DATA))

from classical_emotion_lexicon import EMOTION_SPECS, validate  # noqa: E402
from classical_emotion_model import classify_text  # noqa: E402
from famous_poet_corpus import atomic_dump_json, load_analysis_poems  # noqa: E402


def load_spirit():
    spec = importlib.util.spec_from_file_location("spirit_image_dict", DATA / "spirit_image_dict.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    entries = {
        row[0]: {"cluster": row[2], "sentiment": float(row[3])}
        for row in mod.SPIRIT_DICT
    }
    return entries, sorted(entries, key=len, reverse=True)


def build() -> dict[str, object]:
    ontology = validate()
    poems, corpus_source = load_analysis_poems(fallback=False)
    if corpus_source != "analysis_full":
        forbidden_fallback = "data/poems.json"
        raise RuntimeError(
            f"状态统计必须使用全作品语料，实际来源：{corpus_source}；"
            f"禁止回退 {forbidden_fallback}"
        )
    corpus_path = (
        "data/analysis/famous_poets_full.jsonl.gz"
        if corpus_source == "analysis_full"
        else "data/poems.json"
    )
    spirit_entries, spirit_words = load_spirit()
    rows = []
    labels: Counter[str] = Counter()
    confidence: Counter[str] = Counter()
    per_poet: dict[str, Counter[str]] = {}

    for poem in poems:
        profile = classify_text(
            poem.get("body", ""), poem.get("title", ""), spirit_entries, spirit_words
        )
        if profile["primary"]:
            labels[str(profile["primary_label"])] += 1
            per_poet.setdefault(poem["author"], Counter())[str(profile["primary_label"])] += 1
        confidence[str(profile["confidence_label"])] += 1
        rows.append({
            "poet": poem["author"],
            "title": poem["title"],
            "work_id": poem.get("work_id"),
            "canonical_gushiwen_id": poem.get("canonical_gushiwen_id"),
            "body_hash": poem.get("body_hash", ""),
            **profile,
        })

    payload = {
        "schema_version": 2,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "method": "model-assisted-lexicon + deterministic-local-multilabel-vad",
        "method_note": (
            "模型用于扩充候选情感词与文学形容词；发布值由本地规则复算。"
            "标签描述文本特征，不等同于作者心理诊断。"
        ),
        "corpus_source": corpus_source,
        "corpus_path": corpus_path,
        "corpus_size": len(poems),
        "ontology": {
            **ontology,
            "dimensions": ["valence", "arousal", "dominance"],
            "emotion_labels": [spec["label"] for spec in EMOTION_SPECS.values()],
        },
        "primary_distribution": labels.most_common(),
        "confidence_distribution": dict(confidence),
        "per_poet_primary": {
            poet: counts.most_common() for poet, counts in sorted(per_poet.items())
        },
        "profiles": rows,
    }
    atomic_dump_json(OUT, payload)
    return payload


if __name__ == "__main__":
    result = build()
    print(f"saved {OUT}")
    print(f"poems={result['corpus_size']} ontology={result['ontology']}")
    print("top primary:", result["primary_distribution"][:10])
    print("confidence:", result["confidence_distribution"])
