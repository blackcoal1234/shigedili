from __future__ import annotations

import ast
import importlib.util
import os
import subprocess
import sys
import types
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
VISUALS = (
    ROOT / "数据可视化脚本" / "viz_17_imagery_emotion_compare.py",
    ROOT / "数据可视化脚本" / "viz_31_gaze_compass.py",
    ROOT / "数据可视化脚本" / "viz_32_dual_map.py",
    ROOT / "数据可视化脚本" / "viz_34_char_fingerprint.py",
    ROOT / "数据可视化脚本" / "viz_35_solitude_hyperbole.py",
)
SIX = ("李白", "杜甫", "白居易", "苏轼", "陆游", "李清照")


def load_module(path: Path, name: str):
    if path == VISUALS[0] and "pyecharts" not in sys.modules:
        package = types.ModuleType("pyecharts")
        options = types.ModuleType("pyecharts.options")
        charts = types.ModuleType("pyecharts.charts")
        commons = types.ModuleType("pyecharts.commons")
        utils = types.ModuleType("pyecharts.commons.utils")
        charts.HeatMap = type("HeatMap", (), {})
        utils.JsCode = lambda value: value
        package.options = options
        sys.modules.update({
            "pyecharts": package, "pyecharts.options": options,
            "pyecharts.charts": charts, "pyecharts.commons": commons,
            "pyecharts.commons.utils": utils,
        })
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_all_visuals_call_full_corpus_loader_and_publish_metadata() -> None:
    required_text = {
        "corpus_source", "corpus_path", "analysis_count", "canonical_evidence_count",
        "data/analysis/famous_poets_full.jsonl.gz", "data/poems.json",
    }
    for path in VISUALS:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        called = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        assert "load_analysis_poems" in called, path
        assert all(value in source for value in required_text), path


def test_viz17_counts_and_denominators_match_loader() -> None:
    from data.imagery_emotion_rules import TARGET_POETS
    from tools.famous_poet_corpus import load_analysis_poems

    module = load_module(VISUALS[0], "viz17_full_test")
    rows, source = load_analysis_poems(fallback=False)
    expected = Counter(row["poet"] for row in rows if row["poet"] in TARGET_POETS)
    payload = module.build_payload()
    assert payload["summary"]["corpus_source"] == source == "analysis_full"
    assert payload["summary"]["analysis_count"] == sum(expected.values())
    assert payload["poem_totals"] == dict(expected)
    for view in payload["views"].values():
        for poet, row in view["poets"].items():
            assert row["matched_record_count"] == row["sample_count"]
            assert row["evidence_record_count"] == len(row["records"]) <= 24
            assert row["truncated"] == (row["sample_count"] > len(row["records"]))
            assert all(
                cell["baseline_denominator"] == expected[poet]
                for cell in view["cells"] if cell["poet"] == poet
            )
            canonical_flags = [record["canonical_match"] for record in row["records"]]
            assert canonical_flags == sorted(canonical_flags, reverse=True)


def test_exact_canonical_indexes_reject_same_title_and_legacy_hash_collisions() -> None:
    rows = [
        {
            "poet": "诗人", "title": "同题", "work_id": "work-a",
            "body_hash": "legacy-collision", "canonical_match": True,
            "canonical_gushiwen_id": "canonical-a",
        },
        {
            "poet": "诗人", "title": "同题", "work_id": "work-b",
            "body_hash": "legacy-collision", "canonical_match": True,
            "canonical_gushiwen_id": "canonical-b",
        },
        {
            "poet": "诗人", "title": "唯一", "work_id": "work-upstream",
            "body_hash": "legacy-collision", "canonical_match": False,
            "canonical_gushiwen_id": None,
        },
    ]
    for index, path in enumerate(VISUALS[1:3], start=31):
        module = load_module(path, f"viz{index}_identity_test")
        assert module.index_exact_canonical_by_title(rows) == {}


def test_geography_and_chronology_are_guarded_by_exact_canonical_identity() -> None:
    gaze = VISUALS[1].read_text(encoding="utf-8")
    dual = VISUALS[2].read_text(encoding="utf-8")
    assert 'if not h["canonical_match"]' in gaze
    assert 'chron_lookup.get(h["canonical_gushiwen_id"])' in gaze
    assert 'if pm.get("canonical_match") else None' in dual
    assert 'comp.get(pm.get("canonical_gushiwen_id"))' in dual
    assert "comp.get((poet, pm[\"title\"]))" not in dual


def test_no_legacy_fixed_sample_or_canonical_total() -> None:
    paths = (VISUALS[0], ROOT / "tools" / "check_imagery_emotion_compare.py")
    forbidden = ("POEMS_PER_POET", "前 20 首", "20 首固定样本", "1772")
    for path in paths:
        source = path.read_text(encoding="utf-8")
        assert not any(value in source for value in forbidden), path


def test_viz17_can_load_from_non_repo_cwd(tmp_path: Path) -> None:
    code = (
        "import importlib.util,sys,types;"
        "pkg=types.ModuleType('pyecharts');opts=types.ModuleType('pyecharts.options');"
        "charts=types.ModuleType('pyecharts.charts');commons=types.ModuleType('pyecharts.commons');"
        "utils=types.ModuleType('pyecharts.commons.utils');charts.HeatMap=type('HeatMap',(),{});"
        "utils.JsCode=lambda v:v;pkg.options=opts;"
        "sys.modules.update({'pyecharts':pkg,'pyecharts.options':opts,'pyecharts.charts':charts,"
        "'pyecharts.commons':commons,'pyecharts.commons.utils':utils});"
        f"p={str(VISUALS[0])!r};"
        "s=importlib.util.spec_from_file_location('viz17_cwd',p);"
        "m=importlib.util.module_from_spec(s);s.loader.exec_module(m);"
        "rows,source=m.load_target_poems();"
        "assert source=='analysis_full' and len(rows)>0"
    )
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    subprocess.run([sys.executable, "-c", code], cwd=tmp_path, env=env, check=True)
