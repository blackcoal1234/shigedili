from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "数据可视化脚本" / "viz_30_competition_home.py"
OUTPUT = ROOT / "output" / "assets" / "competition" / "home_data.json"
sys.path.insert(0, str(SCRIPT.parent))


def load_viz30():
    spec = importlib.util.spec_from_file_location("viz30_stable_identity", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_ambiguous_titles_require_explicit_source_identity() -> None:
    module = load_viz30()
    cases = (
        ("杜甫", "绝句", "549473b5211c"),
        ("白居易", "夜雨", "efa7971405ab"),
        ("白居易", "池上", "a8f44614071a"),
        ("陆游", "书愤", "7c14409ca751"),
        ("陆游", "冬夜读书示子聿", "51c560529d2a"),
    )
    for poet, title, canonical_id in cases:
        assert module.resolve_canonical(poet, title) is None
        resolved = module.resolve_canonical(
            poet,
            title,
            f"https://www.gushiwen.cn/shiwenv_{canonical_id}.aspx",
        )
        assert resolved["source_poem_id"] == canonical_id


def test_chronology_carries_exact_ids_for_known_title_collisions() -> None:
    module = load_viz30()
    expected = {
        ("杜甫", "绝句"): "549473b5211c",
        ("白居易", "夜雨"): "efa7971405ab",
        ("白居易", "池上"): "a8f44614071a",
        ("陆游", "书愤"): "7c14409ca751",
        ("陆游", "冬夜读书示子聿"): "51c560529d2a",
    }
    actual = {
        (poet, entry["title"]): entry.get("canonical_id")
        for poet, entries in module.CHRONO.items()
        for entry in entries
        if (poet, entry["title"]) in expected
    }
    assert actual == expected


def test_generated_evidence_never_uses_an_ambiguous_title_fallback() -> None:
    module = load_viz30()
    module.main()
    payload = json.loads(OUTPUT.read_text(encoding="utf-8"))
    for poet in payload["poets"]:
        for period in poet["curve"]["periods"]:
            for poem in period["poems"]:
                key = (poet["name"], module.norm_title(poem["title"]))
                candidates = module.CANONICAL_IDS_BY_TITLE.get(key, [])
                if len(candidates) > 1:
                    assert poem["canonical_gushiwen_id"] in candidates
                    assert poem["body_hash"]
        for station in poet["stations"]:
            if station.get("body_html"):
                assert station["canonical_gushiwen_id"]
                assert station["body_hash"]
