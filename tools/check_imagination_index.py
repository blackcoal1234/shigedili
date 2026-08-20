# -*- coding: utf-8 -*-
"""imagination_index.json 质量门：计数一致、率一致、证据字段完备。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PATH = ROOT / "output" / "assets" / "competition" / "imagination_index.json"

MIN_PLACES = 15
MIN_RATE_DENOM = 2


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    if not PATH.exists():
        raise SystemExit(f"[failed] 缺少 {PATH}，先运行 tools/build_imagination_index.py")
    data = json.loads(PATH.read_text(encoding="utf-8"))

    meta = data["meta"]
    for field in ("n_facts_with_place", "policy", "generated_by", "min_n"):
        assert meta.get(field) is not None or field in meta, f"meta 缺少 {field}"
    assert meta["n_facts_with_place"] > 100, "核验诗数异常"

    places = data["places"]
    assert len(places) >= MIN_PLACES, f"地方数 {len(places)} < {MIN_PLACES}"

    keys = set()
    n_with_coords = 0
    for p in places:
        key = p["key"]
        assert key and key not in keys, f"key 缺失或重复：{key}"
        keys.add(key)
        nc, nd = p["composed_n"], p["dreamed_n"]
        assert nc >= 0 and nd >= 0 and (nc + nd) > 0, f"{key} 计数非法"
        assert p["composed_n"] >= len(p["composed"]), f"{key} composed 展示数大于计数"
        assert p["dreamed_n"] >= len(p["dreamed"]), f"{key} dreamed 展示数大于计数"
        rate = p["imagined_rate"]
        if rate is not None:
            assert (nc + nd) >= MIN_RATE_DENOM, f"{key} 分母不足却输出被想象率"
            assert abs(rate - nd / (nc + nd)) < 1e-3, f"{key} 被想象率与计数不一致"
        else:
            assert (nc + nd) < meta["min_n"], f"{key} 分母达标却未输出被想象率"
        for d in p["dreamed"]:
            assert d.get("actual_place"), f"{key} 遥想条目缺实作地：{d}"
            assert d.get("alias"), f"{key} 遥想条目缺诗中别名"
        if p.get("lon") is not None and p.get("lat") is not None:
            n_with_coords += 1
    assert n_with_coords >= len(places) * 0.8, f"带坐标地方仅 {n_with_coords}/{len(places)}"

    n_rated = sum(1 for p in places if p["imagined_rate"] is not None)
    assert n_rated >= 8, f"可输出被想象率的地方仅 {n_rated}"

    print(
        f"[ok] imagination_index：{len(places)} 处地方（{n_with_coords} 带坐标） | "
        f"{n_rated} 处达样本阈值输出被想象率 | 计数/率一致/证据字段 全部通过"
    )


if __name__ == "__main__":
    main()
