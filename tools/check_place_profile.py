# -*- coding: utf-8 -*-
"""place_profile.json 质量门：结构、坐标、证据等级、口径完整性。"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PATH = ROOT / "output" / "assets" / "competition" / "place_profile.json"

# 中国大陆大致范围（含港澳台边缘容差）
LON_MIN, LON_MAX = 73, 136
LAT_MIN, LAT_MAX = 17, 54

MIN_PLACES = 15
MIN_COMPOSED_PLACES = 10


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    if not PATH.exists():
        raise SystemExit(f"[failed] 缺少 {PATH}，先运行 tools/build_place_profile.py")
    data = json.loads(PATH.read_text(encoding="utf-8"))

    meta = data.get("meta") or {}
    for field in ("n_poems_corpus", "n_fact_with_coords_ab", "policy", "generated_by"):
        assert meta.get(field), f"meta 缺少 {field}"

    places = data.get("places") or []
    assert len(places) >= MIN_PLACES, f"地方数 {len(places)} < {MIN_PLACES}"
    composed_places = [p for p in places if p["composed_n"] > 0]
    assert len(composed_places) >= MIN_COMPOSED_PLACES, (
        f"有核验在地创作的地方仅 {len(composed_places)} < {MIN_COMPOSED_PLACES}"
    )

    keys = set()
    for p in places:
        key = p.get("key")
        assert key and key not in keys, f"key 缺失或重复：{key}"
        keys.add(key)
        lon, lat = p["lon"], p["lat"]
        assert isinstance(lon, (int, float)) and isinstance(lat, (int, float)), f"{key} 坐标非数值"
        assert LON_MIN <= lon <= LON_MAX and LAT_MIN <= lat <= LAT_MAX, f"{key} 坐标越界 {lon},{lat}"
        assert not (math.isnan(lon) or math.isnan(lat)), f"{key} 坐标 NaN"
        assert p.get("modern"), f"{key} 缺今地名"
        n_comp, n_ment = p["composed_n"], p["mentions_n"]
        assert n_comp >= 0 and n_ment >= 0 and (n_comp + n_ment) > 0, f"{key} 计数非法"
        rate = p["locality_rate"]
        assert rate is None or 0.0 <= rate <= 1.0, f"{key} 在地率越界 {rate}"
        if n_comp > 0:
            assert rate is not None and abs(rate - n_comp / (n_comp + n_ment)) < 1e-3, (
                f"{key} 在地率与两侧 n 不一致"
            )
        for c in p["composed"]:
            assert c.get("grade") in {"A", "B"}, f"{key} 在地创作混入非 A/B 级：{c}"
            assert c.get("poet") and c.get("title"), f"{key} composed 条目缺诗人/诗题"
            year = c.get("year")
            assert year is None or (isinstance(year, int) and -2000 < year < 2100), (
                f"{key} 年份异常 {year}"
            )
        if p["mentions_n"] > 0:
            assert p["mention_sample_titles"], f"{key} 被写入>0 但无样本"

    n_with_imagery = sum(1 for p in places if p["imagery_top"])
    assert n_with_imagery >= MIN_PLACES, f"带意象统计的地方仅 {n_with_imagery}"

    print(
        f"[ok] place_profile：{len(places)} 处地方 | "
        f"在地创作覆盖 {len(composed_places)} 处 | 意象覆盖 {n_with_imagery} 处 | 口径声明完备"
    )


if __name__ == "__main__":
    main()
