# -*- coding: utf-8 -*-
"""被想象的地方（R3 在地率/被想象率）：核验级「亲历 vs 遥想」+ 诗人级上界。

两级口径（诚实分层，页面上必须并陈）：

【核验级 · 身在别处写此地】
  亲历书写(K) ＝ 人工核验事实包中作地为本地的诗（A/B 级证据）；
  遥想书写(K) ＝ 事实包中作地在异地 J≠K、但正文提及 K 的诗——
  「他此刻确实在别处」有核验作地背书，因此是证据级的遥想样本；
  被想象率(K) ＝ 遥想 / (亲历 + 遥想)，仅当分母 ≥ MIN_N 时输出。
  样本量受限于 124 首核验诗，页面必须同给两侧 n。

【诗人级 · 六家行旅对照（上界）】
  到过(K) ＝ data/reviewed/poet_journeys.json 中该诗人的人工审核节点含 K；
  书写而无节点(K) ＝ 六家语料中写过 K 但行旅节点无 K 的诗人。
  行旅节点是「知名生平节点精选」，无节点 ≠ 未到过——该口径只给上界，
  页面标注为上界估计，不作结论。

产出：output/assets/competition/imagination_index.json
零参数可复跑，输出确定。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "data"))
sys.path.insert(0, str(ROOT / "tools"))

from build_place_profile import (  # noqa: E402
    build_alias_index,
    load_fact_packages,
    norm_place,
)

POEMS_PATH = ROOT / "data" / "poems.json"
JOURNEYS_PATH = ROOT / "data" / "reviewed" / "poet_journeys.json"
OUT_JSON = ROOT / "output" / "assets" / "competition" / "imagination_index.json"

MIN_N = 2          # 分母低于此不输出被想象率
TOP_PLACES = 30
SIX_POETS = {"李白", "杜甫", "白居易", "苏轼", "陆游", "李清照"}
SENT_SPLIT = re.compile(r"(?<=[。！？；])|\n")


PROVINCE_HEAD = re.compile(
    r"^(黑龙江|内蒙古|广西|西藏|宁夏|新疆|北京|天津|上海|重庆|河北|山西|辽宁|吉林|"
    r"江苏|浙江|安徽|福建|江西|山东|河南|湖北|湖南|广东|海南|四川|贵州|云南|陕西|"
    r"甘肃|青海|台湾)(省|自治区|特别行政区)?"
)


def strip_province(place_modern: str) -> str:
    """「湖北省荆门市」→「荆门」，与 place_dict 今地名颗粒对齐。"""
    return norm_place(PROVINCE_HEAD.sub("", place_modern or ""))


def resolve_key(place_modern: str, all_keys: set, keys_by_len: list) -> str:
    """行政全称归并到词典键：精确 → 最长子串（如「九江市庐山」→「庐山」），失败返回原值。"""
    k = strip_province(place_modern)
    if not k:
        return ""
    if k in all_keys:
        return k
    for key in keys_by_len:
        if len(key) >= 2 and key in k:
            return key
    return k


def find_aliases(body: str, alias_index: dict) -> list[str]:
    return [a for a in alias_index if a in body]


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    poems = json.loads(POEMS_PATH.read_text(encoding="utf-8"))
    poem_index = {(p.get("poet") or p.get("author"), p.get("title")): p for p in poems}
    facts = load_fact_packages()
    alias_index = build_alias_index()
    all_keys = {v["key"] for v in alias_index.values()}
    keys_by_len = sorted(all_keys, key=len, reverse=True)

    # ---- 核验级 ----
    composed: dict[str, list[dict]] = {}     # K -> 亲历书写
    dreamed: dict[str, list[dict]] = {}      # K -> 遥想书写（身在别处写此地）
    n_facts_with_place = 0
    for rec in facts:
        chron = rec.get("chronology") or {}
        modern = chron.get("modern_place") or ""
        comp_key = resolve_key(modern, all_keys, keys_by_len)
        if not comp_key:
            continue
        n_facts_with_place += 1
        poet, title = rec["poem_key"]["poet"], rec["poem_key"]["title"]
        year = chron.get("year_start")
        grade = min(
            (ev.get("source_grade", "C") for ev in rec.get("evidence", [])
             if "composition_place" in ev.get("supports", [])),
            key=lambda g: {"A": 0, "B": 1, "C": 2}.get(g, 9),
            default="C",
        )
        composed.setdefault(comp_key, []).append(
            {"poet": poet, "title": title, "dynasty": rec["poem_key"]["dynasty"],
             "year": year, "grade": grade}
        )
        pm = poem_index.get((poet, title))
        body = (pm or {}).get("body") or ""
        if not isinstance(body, str) or not body:
            continue
        seen_keys: set = set()
        for alias in find_aliases(body, alias_index):
            key = alias_index[alias]["key"]
            if key == comp_key or key in seen_keys:
                continue
            seen_keys.add(key)
            line = ""
            for seg in SENT_SPLIT.split(body):
                seg = seg.strip()
                if alias in seg and 4 <= len(seg) <= 30:
                    line = seg[:30]
                    break
            dreamed.setdefault(key, []).append(
                {
                    "poet": poet, "title": title, "dynasty": rec["poem_key"]["dynasty"],
                    "year": year, "grade": grade,
                    "actual_place": chron.get("historical_place") or modern,
                    "alias": alias, "line": line,
                }
            )

    # ---- 诗人级上界（六家行旅） ----
    journeys = json.loads(JOURNEYS_PATH.read_text(encoding="utf-8"))
    visited: dict[str, set] = {}
    node_info: dict[str, dict] = {}
    for p in journeys.get("poets", []):
        poet = p.get("poet")
        keys = set()
        for n in p.get("nodes", []):
            k = resolve_key(n.get("place_modern") or "", all_keys, keys_by_len)
            if not k:
                continue
            keys.add(k)
            node_info.setdefault(k, {"lon": n.get("longitude"), "lat": n.get("latitude")})
        visited[poet] = keys
    six_writers: dict[str, dict] = {}      # K -> {poet: 诗数}
    for pm in poems:
        poet = pm.get("poet") or pm.get("author")
        if poet not in SIX_POETS:
            continue
        body = pm.get("body") or ""
        if not isinstance(body, str):
            continue
        for alias in find_aliases(body, alias_index):
            key = alias_index[alias]["key"]
            six_writers.setdefault(key, {}).setdefault(poet, 0)
            six_writers[key][poet] += 1

    # ---- 汇总 ----
    profile = json.loads(
        (ROOT / "output" / "assets" / "competition" / "place_profile.json").read_text(encoding="utf-8")
    ) if (ROOT / "output" / "assets" / "competition" / "place_profile.json").exists() else {"places": []}
    profile_by_key = {p["key"]: p for p in profile.get("places", [])}

    places_out = []
    keys = (set(composed) | set(dreamed) | set(six_writers)) & (
        set(profile_by_key) | set(composed) | set(dreamed)
    )
    for key in sorted(keys):
        comp, dream = composed.get(key, []), dreamed.get(key, [])
        n_comp, n_dream = len(comp), len(dream)
        if n_comp + n_dream == 0 and key not in six_writers:
            continue
        rate = round(n_dream / (n_comp + n_dream), 4) if (n_comp + n_dream) >= MIN_N else None
        writers = six_writers.get(key, {})
        visitors = sorted(po for po in writers if key in visited.get(po, set()))
        no_node = sorted(po for po in writers if key not in visited.get(po, set()))
        prof = profile_by_key.get(key, {})
        places_out.append(
            {
                "key": key,
                "modern": prof.get("modern") or key,
                "province": prof.get("province") or "",
                "lon": prof.get("lon") if prof.get("lon") is not None else node_info.get(key, {}).get("lon"),
                "lat": prof.get("lat") if prof.get("lat") is not None else node_info.get(key, {}).get("lat"),
                "composed_n": n_comp,
                "composed": comp[:8],
                "dreamed_n": n_dream,
                "dreamed": dream[:8],
                "imagined_rate": rate,
                "six_writers": writers,
                "visited_poets": visitors,
                "no_node_poets": no_node,
            }
        )
    places_out.sort(key=lambda r: (-(r["dreamed_n"] + r["composed_n"]), r["key"]))
    places_out = places_out[:TOP_PLACES]

    meta = {
        "n_facts_with_place": n_facts_with_place,
        "n_places": len(places_out),
        "min_n": MIN_N,
        "policy": (
            "核验级：亲历书写＝事实包作地为本地的诗（A/B）；遥想书写＝事实包作地在异地但正文提及本地"
            "（「身在别处写此地」有核验作地背书）；被想象率＝遥想/(亲历+遥想)，分母≥2 才输出，"
            "样本受限于 124 首核验诗，展示必须附两侧 n。诗人级：六家行旅节点为人工选定的知名节点，"
            "无节点≠未到过，只作上界参考，不作结论。"
        ),
        "generated_by": "tools/build_imagination_index.py",
    }

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump({"meta": meta, "places": places_out}, f, ensure_ascii=False, separators=(",", ":"), allow_nan=False)

    print("OK  ->", OUT_JSON, f"({OUT_JSON.stat().st_size} bytes)")
    print(f"核验诗 {n_facts_with_place} | 入档地方 {len(places_out)}")
    for p in places_out[:10]:
        rate = f"{p['imagined_rate']*100:.0f}%" if p["imagined_rate"] is not None else "-"
        print(
            f"  {p['modern']:<4} 亲历{p['composed_n']:>2} 遥想{p['dreamed_n']:>2} "
            f"被想象率{rate:>5}  六家书写{len(p['six_writers'])}人(到过{len(p['visited_poets'])})"
        )


if __name__ == "__main__":
    main()
