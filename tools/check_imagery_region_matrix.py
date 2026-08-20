# -*- coding: utf-8 -*-
"""imagery_region_matrix.json 质量门：阈值、lift 一致性、证据完整性。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PATH = ROOT / "output" / "assets" / "competition" / "imagery_region_matrix.json"

MIN_REGIONS_WITH_WORDS = 6


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    if not PATH.exists():
        raise SystemExit(f"[failed] 缺少 {PATH}，先运行 tools/build_imagery_region_matrix.py")
    data = json.loads(PATH.read_text(encoding="utf-8"))

    meta = data["meta"]
    for field in ("n_located_poems", "thresholds", "policy", "regions"):
        assert meta.get(field), f"meta 缺少 {field}"
    assert meta["n_located_poems"] > 1000, "定位诗数异常"
    thr = meta["thresholds"]

    regions = data["regions"]
    assert len(regions) == len(meta["regions"]), "区域数与 meta 不一致"
    ids = [r["id"] for r in regions]
    assert len(ids) == len(set(ids)), "区域 id 重复"

    with_words = 0
    for r in regions:
        assert r["n_poems"] >= 0 and r.get("base_rate", 0) <= 1.0, f"{r['id']} 计数异常"
        for row in r["top_words"]:
            assert row["lift"] > 1.0, f"{r['id']} 混入 lift<=1：{row}"
            assert row["n_wr"] >= thr["min_cell"], f"{r['id']} 格点低于阈值：{row}"
            assert row["n_w"] >= thr["min_word_poems"], f"{r['id']} 词样本不足：{row}"
            assert row["n_wr"] <= row["n_w"], f"{r['id']} n_wr>n_w：{row}"
            # lift 与计数一致性
            base = r["n_poems"] / meta["n_located_poems"]
            expect = (row["n_wr"] / row["n_w"]) / base
            assert abs(row["lift"] - expect) < 0.01, f"{r['id']} lift 与计数不一致：{row}"
        if r["top_words"]:
            with_words += 1
            n_with_samples = sum(1 for row in r["top_words"] if row.get("samples"))
            assert n_with_samples >= len(r["top_words"]) * 0.6, (
                f"{r['id']} 证据原句覆盖不足（{n_with_samples}/{len(r['top_words'])}）"
            )
    assert with_words >= MIN_REGIONS_WITH_WORDS, (
        f"有归属意象的区域仅 {with_words} < {MIN_REGIONS_WITH_WORDS}"
    )

    words = data["words"]
    matrix_words = {row["word"] for r in regions for row in r["top_words"]}
    assert matrix_words <= set(words), f"矩阵词未入索引：{matrix_words - set(words)}"
    for w, info in words.items():
        assert info["n_w"] >= thr["min_word_poems"], f"词 {w} 入索引但低于阈值"
        for rid, cell in info["regions"].items():
            assert rid in ids, f"词 {w} 引用未知区域 {rid}"
            assert cell["n_wr"] >= thr["min_cell"], f"词 {w} 区域 {rid} 格点低于阈值"

    print(
        f"[ok] imagery_region_matrix：{len(regions)} 区域（{with_words} 个有归属意象） | "
        f"意象 {len(words)} 个 | 阈值/lift/证据校验全部通过"
    )


if __name__ == "__main__":
    main()
