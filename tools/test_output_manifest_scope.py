"""回归测试：发布 manifest 必须覆盖 40—44 号页及诗页数据资产。"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
EXPECTED_PAGES = {
    "40_山河证道.html",
    "41_意象地理.html",
    "42_被想象的地方.html",
    "43_飞花令加行.html",
    "44_诗页.html",
}
POEM_PAGE_ASSET = "assets/poem_page/poem_page_data.js"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_manifest_writer_covers_pages_and_poem_page_asset(tmp_path, monkeypatch) -> None:
    module = load_module(
        "viz_99_output_index_test",
        ROOT / "数据可视化脚本" / "viz_99_output_index.py",
    )
    monkeypatch.setattr(module, "OUTPUT_DIR", tmp_path)

    for item in (*module.OUTPUTS, *module.MANIFEST_ASSETS):
        path = tmp_path / item.href
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((item.href + "\n").encode("utf-8"))

    module.write_manifest()
    payload = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    rows = {row["href"]: row for row in payload["outputs"]}

    assert EXPECTED_PAGES <= rows.keys()
    asset_path = tmp_path / POEM_PAGE_ASSET
    assert rows[POEM_PAGE_ASSET]["exists"] is True
    assert rows[POEM_PAGE_ASSET]["bytes"] == asset_path.stat().st_size
    assert rows[POEM_PAGE_ASSET]["sha256"] == hashlib.sha256(
        asset_path.read_bytes()
    ).hexdigest()


def test_theme_checker_rejects_asset_byte_or_hash_drift(tmp_path, monkeypatch) -> None:
    module = load_module(
        "check_theme_outputs_test",
        ROOT / "tools" / "check_theme_outputs.py",
    )
    monkeypatch.setattr(module, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(module, "REQUIRED", (POEM_PAGE_ASSET,))
    asset_path = tmp_path / POEM_PAGE_ASSET
    asset_path.parent.mkdir(parents=True)
    asset_path.write_bytes(b"poem-page-data" * 16)

    row = {
        "href": POEM_PAGE_ASSET,
        "exists": True,
        "bytes": asset_path.stat().st_size,
        "sha256": module.sha256(asset_path),
    }
    (tmp_path / "manifest.json").write_text(
        json.dumps({"outputs": [row]}),
        encoding="utf-8",
    )
    module.check_manifest()

    row["bytes"] += 1
    (tmp_path / "manifest.json").write_text(
        json.dumps({"outputs": [row]}),
        encoding="utf-8",
    )
    with pytest.raises(AssertionError, match="字节数不一致"):
        module.check_manifest()

    row["bytes"] = asset_path.stat().st_size
    row["sha256"] = "0" * 64
    (tmp_path / "manifest.json").write_text(
        json.dumps({"outputs": [row]}),
        encoding="utf-8",
    )
    with pytest.raises(AssertionError, match="哈希不一致"):
        module.check_manifest()
