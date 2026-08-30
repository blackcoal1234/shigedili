from __future__ import annotations

import ast
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parent.parent
PRODUCERS = (
    ROOT / "data" / "stylometry" / "scan_color.py",
    ROOT / "data" / "stylometry" / "scan_number.py",
    ROOT / "data" / "stylometry" / "scan_solitude.py",
    ROOT / "data" / "stylometry" / "scan_sound.py",
    ROOT / "tools" / "build_emotion_profiles.py",
)


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_corpus_module():
    return _load_module(
        "fail_closed_corpus", ROOT / "tools" / "famous_poet_corpus.py"
    )


def test_state_producers_explicitly_disable_canonical_fallback() -> None:
    for path in PRODUCERS:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "load_analysis_poems"
        ]
        assert calls, path
        for call in calls:
            fallback = next(
                (kw.value for kw in call.keywords if kw.arg == "fallback"), None
            )
            assert isinstance(fallback, ast.Constant), path
            assert fallback.value is False, path


def test_missing_full_corpus_fails_even_when_canonical_exists(tmp_path: Path) -> None:
    corpus = _load_corpus_module()
    canonical = tmp_path / "poems.json"
    canonical.write_text(
        json.dumps(
            [
                {
                    "author": "李白",
                    "dynasty": "唐",
                    "title": "静夜思",
                    "body": "床前明月光。",
                    "source_poem_id": "canonical-only",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    missing = tmp_path / "missing-full.jsonl.gz"
    with pytest.raises(FileNotFoundError) as exc_info:
        corpus.load_analysis_poems(
            full_path=missing,
            canonical_path=canonical,
            fallback=False,
            manifest_path=tmp_path / "missing-manifest.json",
        )

    assert exc_info.value.args == (missing,)


def test_manifest_mismatch_fails_without_canonical_fallback(tmp_path: Path) -> None:
    corpus = _load_corpus_module()
    full_path = ROOT / "data" / "analysis" / "famous_poets_full.jsonl.gz"
    canonical_path = ROOT / "data" / "poems.json"
    manifest = json.loads(
        (ROOT / "data" / "analysis" / "famous_poets_full_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    manifest["output_sha256"] = "0" * 64
    mismatched_manifest = tmp_path / "mismatched-manifest.json"
    mismatched_manifest.write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )

    with pytest.raises(RuntimeError, match="output_sha256 不匹配"):
        corpus.load_analysis_poems(
            full_path=full_path,
            canonical_path=canonical_path,
            fallback=False,
            manifest_path=mismatched_manifest,
        )


def test_run_all_checks_local_full_corpus_before_state_builds(monkeypatch) -> None:
    run_all = _load_module("fail_closed_run_all", ROOT / "run_all.py")
    monkeypatch.setattr(
        run_all,
        "parse_args",
        lambda: SimpleNamespace(
            no_crawl=True,
            recrawl=False,
            skip_db=True,
            reset_db=False,
            keep_legacy_output=True,
        ),
    )
    calls: list[tuple[str, tuple[str, ...]]] = []

    def record(path: Path, *args: str) -> None:
        calls.append((path.relative_to(ROOT).as_posix(), args))

    monkeypatch.setattr(run_all, "run_python", record)
    run_all.main()

    gate = ("tools/famous_poet_corpus.py", ("check", "--no-source-verify"))
    gate_index = calls.index(gate)
    required_consumers = (
        "data/stylometry/scan_color.py",
        "data/stylometry/scan_number.py",
        "data/stylometry/scan_solitude.py",
        "data/stylometry/scan_sound.py",
        "tools/build_emotion_profiles.py",
        "数据可视化脚本/viz_00_er_diagram.py",
    )
    for consumer in required_consumers:
        assert gate_index < next(
            index for index, (path, _args) in enumerate(calls) if path == consumer
        )
