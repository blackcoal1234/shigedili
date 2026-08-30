from __future__ import annotations

import ast
import importlib.util
import os
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent
STAT_SCRIPTS = (
    ROOT / "data" / "stylometry" / "scan_color.py",
    ROOT / "data" / "stylometry" / "scan_number.py",
    ROOT / "data" / "stylometry" / "scan_solitude.py",
    ROOT / "data" / "stylometry" / "scan_sound.py",
    ROOT / "tools" / "build_emotion_profiles.py",
)


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _tree(path: Path) -> ast.Module:
    return ast.parse(_source(path), filename=str(path))


def _load_script(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_statistics_route_only_through_analysis_loader() -> None:
    for path in STAT_SCRIPTS:
        source = _source(path)
        tree = _tree(path)
        imported_names = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        called_names = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }

        assert "load_analysis_poems" in imported_names, path
        assert "load_analysis_poems" in called_names, path
        assert "atomic_dump_json" in imported_names, path
        assert "atomic_dump_json" in called_names, path
        assert "shutil" not in imported_names, path
        assert "time" not in imported_names, path
        assert "copyfile" not in source, path
        assert "load_snapshot" not in source, path
        assert "load_corpus_snapshot" not in source, path
        assert "poems_snapshot" not in source, path
        assert not any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "json"
            and node.func.attr in {"load", "loads"}
            for node in ast.walk(tree)
        ), path
        assert not any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "json"
            and node.func.attr == "dump"
            for node in ast.walk(tree)
        ), path


def test_statistics_publish_source_metadata_and_loader_hashes() -> None:
    for path in STAT_SCRIPTS:
        source = _source(path)
        tree = _tree(path)
        string_literals = {
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        }

        assert "corpus_source" in string_literals, path
        assert "corpus_path" in string_literals, path
        assert "analysis_full" in string_literals, path
        assert "data/analysis/famous_poets_full.jsonl.gz" in string_literals, path
        assert "data/poems.json" in string_literals, path
        assert "work_id" in string_literals, path
        assert "canonical_gushiwen_id" in string_literals, path
        body_hash_values = [
            value
            for mapping in ast.walk(tree)
            if isinstance(mapping, ast.Dict)
            for key, value in zip(mapping.keys, mapping.values)
            if isinstance(key, ast.Constant) and key.value == "body_hash"
        ]
        assert body_hash_values, path
        assert all(
            isinstance(value, (ast.Name, ast.Call))
            and (
                isinstance(value, ast.Name)
                or (
                    isinstance(value.func, ast.Attribute)
                    and value.func.attr == "get"
                )
            )
            for value in body_hash_values
        ), path


def test_run_all_builds_text_statistics_before_visualizations() -> None:
    source = _source(ROOT / "run_all.py")
    expected = (
        '"scan_color.py"',
        '"scan_number.py"',
        '"scan_solitude.py"',
        '"scan_sound.py"',
        '"build_emotion_profiles.py"',
    )
    positions = [source.index(name) for name in expected]
    assert positions == sorted(positions)
    assert positions[-1] < source.index('step("Step 5/5')
    assert 'ROOT / "data" / "stylometry"' in source
    assert "全作品状态扫描" in source
    assert "run_python(path)" in source


def test_canonical_page_routes_remain_separate() -> None:
    protected = [
        ROOT / "tools" / "build_poem_page_data.py",
        ROOT / "数据可视化脚本" / "viz_44_poem_page.py",
    ]
    agent_root = ROOT / "apps" / "agent-ui"
    for directory, dirnames, filenames in os.walk(agent_root):
        dirnames[:] = [
            name
            for name in dirnames
            if not name.startswith(".")
            and name not in {"node_modules", "__pycache__"}
        ]
        protected.extend(
            Path(directory) / name
            for name in filenames
            if Path(name).suffix in {".py", ".js", ".jsx", ".ts", ".tsx"}
        )
    for path in protected:
        assert "famous_poet_corpus" not in _source(path), path


def test_stylometry_docs_describe_dynamic_dual_corpus() -> None:
    source = _source(ROOT / "data" / "stylometry" / "README.md")
    assert "analysis_full" in source
    assert "canonical" in source
    assert "动态" in source
    assert "build_emotion_profiles.py" in source
    assert "1772" not in source
    assert "snapshot" not in source.lower()
    assert "快照" not in source


def test_bai_juyi_legacy_hash_collision_routes_by_stable_identity() -> None:
    viz36 = _load_script(
        ROOT / "数据可视化脚本" / "viz_36_age_align.py", "viz36_hash_test"
    )
    canonical_variants = [
        {
            "author": "白居易",
            "title": "听弹湘妃怨",
            "body": "吴娃征调奏湘妃。",
            "body_hash": "7b73f495d6dbb02e4e99d77fe09edda387984041f5b0499e5c5b6223b17e85c9",
            "source_poem_id": "legacy-converted",
            "source_url": "https://example.test/a",
        },
        {
            "author": "白居易",
            "title": "听弹湘妃怨",
            "body": "吴娃徵调奏湘妃。",
            "body_hash": "7b73f495d6dbb02e4e99d77fe09edda387984041f5b0499e5c5b6223b17e85c9",
            "source_poem_id": "b2d24a75d258",
            "source_url": "https://example.test/b",
        },
    ]
    canonical = viz36.select_canonical_poem(
        viz36.index_canonical_poems(canonical_variants),
        "白居易",
        "听弹湘妃怨",
        {"source_note": "编年证据 https://example.test/b"},
    )
    profiles = viz36.index_emotion_profiles([
        {
            "poet": "白居易", "title": "听弹湘妃怨",
            "body_hash": "7b73f495d6dbb02e4e99d77fe09edda387984041f5b0499e5c5b6223b17e85c9",
            "work_id": "fw_20f8a28dc1e0f80989c9521e",
            "canonical_gushiwen_id": "legacy-converted",
            "primary_label": "甲",
        },
        {
            "poet": "白居易", "title": "听弹湘妃怨",
            "body_hash": "7b73f495d6dbb02e4e99d77fe09edda387984041f5b0499e5c5b6223b17e85c9",
            "work_id": "fw_069334816b781a2186c7748e",
            "canonical_gushiwen_id": "b2d24a75d258",
            "primary_label": "乙",
        },
    ])
    assert canonical["body"] == "吴娃徵调奏湘妃。"
    assert viz36.emotion_for_canonical(profiles, canonical)["primary_label"] == "乙"
    no_id = {key: value for key, value in canonical.items() if key != "source_poem_id"}
    with pytest.raises(ValueError, match="body_hash 非唯一"):
        viz36.emotion_for_canonical(profiles, no_id)

    viz37 = _load_script(
        ROOT / "数据可视化脚本" / "viz_37_soundscape.py", "viz37_hash_test"
    )
    canonical = viz37.select_canonical_poem(
        viz37.index_canonical_poems([canonical_variants[1]]),
        "白居易",
        "听弹湘妃怨",
    )
    sound_variants = [
        {
            "poet": "白居易", "title": "听弹湘妃怨",
            "body_hash": "7b73f495d6dbb02e4e99d77fe09edda387984041f5b0499e5c5b6223b17e85c9",
            "work_id": "fw_20f8a28dc1e0f80989c9521e",
            "canonical_gushiwen_id": "legacy-converted",
            "hits": [["甲", 1]],
        },
        {
            "poet": "白居易", "title": "听弹湘妃怨",
            "body_hash": "7b73f495d6dbb02e4e99d77fe09edda387984041f5b0499e5c5b6223b17e85c9",
            "work_id": "fw_069334816b781a2186c7748e",
            "canonical_gushiwen_id": "b2d24a75d258",
            "hits": [["乙", 2]],
        },
    ]
    indexes = viz37.index_sound_records(sound_variants)
    selected = viz37.sound_record_for_canonical(indexes, canonical)
    assert selected["hits"] == [["乙", 2]]
    assert viz37.rank_for_canonical(sound_variants, indexes, canonical) == 2
    with pytest.raises(ValueError, match="body_hash 非唯一"):
        viz37.sound_record_for_canonical(indexes, no_id)
