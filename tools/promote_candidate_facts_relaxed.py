# -*- coding: utf-8 -*-
"""候选证据 → 放宽晋级事实（AI 辅助层，与严格晋级/人工核验三层分流）。

在 tools/promote_candidate_facts.py（严格门）之上的放宽层。放宽的是晋级门，
不是诚实底线：

放宽门（确定性规则，零随机）：
  R1 单源 B：仅 cnkgraph（B 级）一种来源族 → 作年事实，标注 single_source_b。
  R2 单源 C：仅 souyun（C 级）→ 作年事实，标注 single_source_c（最弱层）。
  R3 双源差 2-3 年：两族年份都在但互差 2-3 → 作年区间事实 [min,max]。
  G2r 行旅同地（放宽）：窗口 ±2 年、事件两两 ≤500km → 推断作地。

模型知识层（本工具唯一引入"模型自有知识"的地方，静态可审计）：
  KNOWLEDGE_PLACE_MAP —— 由模型历史地理知识整理的地名→今地/省份映射表，
  硬编码于本文件顶部，逐条可人工复核；命中时记
  evidence{source_family=ai_model_knowledge, grade=D}，
  chronology.place_resolution=ai_knowledge_map。它只做地名解析，
  绝不充当作年或作地的文献出处。

诚实约束：
  - 每条记录必须至少有一条真实文献证据（cnkgraph/souyun 原始记录）支撑作年；
  - verification.status = promoted_ai_assisted，与 promoted_by_rule /
    人工 verified 三层分流；输出仅入 data/promoted/ai_assisted_facts.jsonl；
  - 已人工核验（124）与已严格晋级（4,177）的键一律跳过，零重叠。
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "data"))
sys.path.insert(0, str(ROOT / "tools"))

from data.place_dict import PLACE_DICT  # noqa: E402
from build_place_profile import norm_place  # noqa: E402

POEMS_PATH = ROOT / "data" / "poems.json"
WORK_CAND = ROOT / "data" / "candidates" / "work_chronology_supplements.jsonl"
RECOVERY_CAND = ROOT / "data" / "candidates" / "work_chronology_zero_fact_recovery.jsonl"
JOURNEY_CAND = ROOT / "data" / "candidates" / "journey_event_candidates.jsonl"
REVIEWED_PACKAGES = ROOT / "data" / "reviewed" / "verified_all_poet_fact_packages.jsonl"
STRICT_PROMOTED = ROOT / "data" / "promoted" / "rule_promoted_facts.jsonl"
OUT_DIR = ROOT / "data" / "promoted"
OUT_JSONL = OUT_DIR / "ai_assisted_facts.jsonl"
OUT_SUMMARY = OUT_DIR / "ai_assisted_summary.json"

YEAR_TOL_DUAL = 3      # R3：双源互差 ≤3
JOURNEY_WIN = 2        # G2r：诗年 ±2
CLUSTER_KM = 500.0     # G2r：事件两两 ≤500km
REVIEWER_STAMP = "codex_relaxed_promotion_2026-08-16"

# ---- 模型知识地名表（静态、可审计；仅地名解析，非文献出处）----
# 键为去括注后的核心地名；值 (今地名展示, 省份)。
KNOWLEDGE_PLACE_MAP = {
    "零陵": ("零陵（永州）", "湖南"),
    "大荔": ("大荔", "陕西"),
    "仪征": ("仪征", "江苏"),
    "南丰": ("南丰", "江西"),
    "莆田": ("莆田", "福建"),
    "崇州": ("崇州", "四川"),
    "滑县": ("滑县", "河南"),
    "蓝田": ("蓝田（西安）", "陕西"),
    "兰溪": ("兰溪", "浙江"),
    "东至": ("东至", "安徽"),
    "浠水": ("浠水", "湖北"),
    "京山": ("京山", "湖北"),
    "建阳": ("建阳", "福建"),
    "宿州": ("宿州", "安徽"),
    "偃师": ("偃师（洛阳）", "河南"),
    "贵池": ("贵池（池州）", "安徽"),
    "巩义": ("巩义（郑州）", "河南"),
    "华县": ("华州（渭南）", "陕西"),
    "扶沟": ("扶沟", "河南"),
    "商丘": ("商丘", "河南"),
    "上高": ("上高", "江西"),
    "无锡": ("无锡", "江苏"),
    "吴淞": ("上海", "上海"),
    "孟州": ("孟州（河阳）", "河南"),
    "嵩县": ("嵩县（洛阳）", "河南"),
    "蒲城": ("蒲城", "陕西"),
    "荥阳": ("荥阳", "河南"),
    "益都": ("青州", "山东"),
    "富县": ("富县（鄜州）", "陕西"),
    "高安": ("高安", "江西"),
    "邓州": ("邓州", "河南"),
    "永康": ("永康", "浙江"),
    "勉县": ("勉县（汉中）", "陕西"),
    "德清": ("德清", "浙江"),
    "溧阳": ("溧阳", "江苏"),
    "宜阳": ("宜阳（洛阳）", "河南"),
}

ALIAS_INDEX = {}
MODERN_INDEX = {}
for _alias, _modern, _prov, _lon, _lat, _note in PLACE_DICT:
    if len(_alias) >= 2:
        ALIAS_INDEX[_alias] = {"modern": _modern, "province": _prov}
    _mkey = norm_place(_modern)
    if len(_mkey) >= 2:
        MODERN_INDEX.setdefault(_mkey, {"modern": _modern, "province": _prov})


def haversine_km(lon1, lat1, lon2, lat2):
    import math
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def core_name(place: str) -> str:
    """去括注、取第一个括号前的主名（「大荔（冯翊）沙苑」→「大荔」）。"""
    name = (place or "").strip()
    if not name:
        return ""
    head = re.split(r"[（(]", name)[0].strip()
    return head or name


def resolve_place(place: str):
    """返回 (modern, province, resolution_source)。词典优先，知识表兜底。"""
    name = (place or "").strip()
    if not name:
        return None, None, None
    core = core_name(name)
    # 1) 词典精确（别名列 / 今名列）
    for cand in (core, re.sub(r"(府|郡|县|路|军|监|州)$", "", core)):
        if not cand:
            continue
        hit = ALIAS_INDEX.get(cand) or MODERN_INDEX.get(cand) or MODERN_INDEX.get(norm_place(cand))
        if hit:
            return hit["modern"], norm_place(hit["province"]), "dict"
    # 2) 词典前缀（「杭州有美堂」→杭州、「无锡惠山」→无锡）
    for end in range(len(core), 1, -1):
        prefix = core[:end]
        hit = ALIAS_INDEX.get(prefix) or MODERN_INDEX.get(prefix)
        if hit:
            return hit["modern"], norm_place(hit["province"]), "dict_prefix"
    # 3) 模型知识表（静态可审计）
    if core in KNOWLEDGE_PLACE_MAP:
        modern, prov = KNOWLEDGE_PLACE_MAP[core]
        return modern, prov, "ai_knowledge_map"
    return None, None, None


def load_grouped() -> dict[tuple[str, str], dict[str, list[dict]]]:
    grouped: dict[tuple[str, str], dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for path in [WORK_CAND] + ([RECOVERY_CAND] if RECOVERY_CAND.exists() else []):
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                r = json.loads(line)
                if r.get("event_type") != "work_chronology" or r.get("year_start") is None:
                    continue
                grouped[(r.get("poet") or "", r.get("poem_title") or "")][r.get("source") or "?"].append(r)
    return grouped


def load_journey_events() -> dict[str, list[dict]]:
    events: dict[str, list[dict]] = defaultdict(list)
    with open(JOURNEY_CAND, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            lon, lat = r.get("longitude"), r.get("latitude")
            year = r.get("year_start")
            place = (r.get("historical_place") or "").strip()
            if lon is None or lat is None or year is None or not place:
                continue
            events[r.get("poet") or ""].append(
                {
                    "year": int(year),
                    "place": place,
                    "lon": float(lon),
                    "lat": float(lat),
                    "source_grade": r.get("source_grade") or "B",
                    "source_name": r.get("source_name") or "",
                    "source_url": r.get("source_url") or "",
                }
            )
    return events


def pick_evidence(rows: list[dict]) -> dict:
    rows = sorted(rows, key=lambda r: (r["year_start"], r.get("candidate_id") or ""))
    r = rows[0]
    return {
        "evidence_id": f"ev-{r.get('source')}",
        "excerpt": (r.get("source_note") or "")[:120],
        "source_family": r.get("source"),
        "source_grade": r.get("source_grade") or "C",
        "source_name": r.get("source_name") or "",
        "source_url": r.get("source_url") or "",
        "supports": ["composition_date"],
    }


def g2r_place(events: list[dict], year: int):
    window = [e for e in events if abs(e["year"] - year) <= JOURNEY_WIN]
    if not window:
        return None
    for i in range(len(window)):
        for j in range(i + 1, len(window)):
            if haversine_km(window[i]["lon"], window[i]["lat"], window[j]["lon"], window[j]["lat"]) > CLUSTER_KM:
                return None
    anchor = sorted(window, key=lambda e: (abs(e["year"] - year), e["year"], e["place"]))[0]
    return anchor, window


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    poems = json.loads(POEMS_PATH.read_text(encoding="utf-8"))
    poem_by_key = {(p.get("poet") or p.get("author") or "", p.get("title") or ""): p for p in poems}

    done_keys = set()
    for path, key_fn in (
        (REVIEWED_PACKAGES, lambda r: (r["poem_key"]["poet"], r["poem_key"]["title"])),
        (STRICT_PROMOTED, lambda r: (r["poem_key"]["poet"], r["poem_key"]["title"])),
    ):
        if path.exists():
            with open(path, encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        done_keys.add(key_fn(json.loads(line)))

    grouped = load_grouped()
    journeys = load_journey_events()

    out = []
    stats = {"R1_single_source_b": 0, "R2_single_source_c": 0, "R3_dual_source_range": 0,
             "with_place": 0, "place_via_ai_map": 0, "skipped_done": 0, "skipped_no_corpus": 0,
             "gap_too_large": 0}
    poet_counts: dict[str, int] = defaultdict(int)
    dynasty_counts: dict[str, int] = defaultdict(int)
    poet_with_place: dict[str, int] = defaultdict(int)

    for (poet, title), families in sorted(grouped.items()):
        if (poet, title) in done_keys:
            stats["skipped_done"] += 1
            continue
        pm = poem_by_key.get((poet, title))
        if not pm:
            stats["skipped_no_corpus"] += 1
            continue
        fams = {f: v for f, v in families.items() if f != "?"}

        year_lo = year_hi = None
        evidence = []
        rules = []
        if len(fams) >= 2:
            firsts = [pick_evidence(v) for v in fams.values()]
            years = [min(int(r["year_start"]) for r in v) for v in fams.values()]
            gap = max(years) - min(years)
            if gap <= YEAR_TOL_DUAL:
                year_lo, year_hi = min(years), max(years)
                evidence = firsts
                rule = "R3_dual_source_range" if gap > 1 else "R3_dual_exact"
                rules.append(rule)
                stats[rule] = stats.get(rule, 0) + 1
            else:
                stats["gap_too_large"] += 1
                continue
        elif "cnkgraph" in fams:
            year_lo = year_hi = min(int(r["year_start"]) for r in fams["cnkgraph"])
            evidence = [pick_evidence(fams["cnkgraph"])]
            rules.append("R1_single_source_b")
            stats["R1_single_source_b"] += 1
        elif "souyun" in fams or "gushiwen" in fams:
            src = "souyun" if "souyun" in fams else "gushiwen"
            year_lo = year_hi = min(int(r["year_start"]) for r in fams[src])
            evidence = [pick_evidence(fams[src])]
            rules.append("R2_single_source_c")
            stats["R2_single_source_c"] += 1
        else:
            continue

        # 每族一条文献证据已入链；补齐另一族（双源时上面已含）
        year = year_lo
        body = pm.get("body") or ""
        hash_ok = bool(body) and hashlib.sha256(body.encode()).hexdigest() == next(
            (r.get("body_hash") for f in fams.values() for r in f if r.get("body_hash")), ""
        )

        chronology = {
            "historical_place": "", "modern_place": "", "province": "",
            "lon": None, "lat": None,
            "year_start": year_lo, "year_end": year_hi, "year_precision": "year",
            "place_resolution": None,
        }

        g2 = g2r_place(journeys.get(poet, []), year)
        if g2 is not None:
            anchor, window = g2
            modern, prov, how = resolve_place(anchor["place"])
            chronology.update(
                {
                    "historical_place": anchor["place"],
                    "modern_place": modern or "",
                    "province": prov or "",
                    "lon": round(anchor["lon"], 4),
                    "lat": round(anchor["lat"], 4),
                    "place_resolution": how,
                }
            )
            evidence.append(
                {
                    "evidence_id": "ev-journey-collocation",
                    "excerpt": (
                        f"诗人{year}年前后行旅事件见于{anchor['place']}"
                        f"（{len(window)} 条带坐标事件，两两 ≤{int(CLUSTER_KM)}km，窗口 ±{JOURNEY_WIN} 年）"
                    ),
                    "source_family": "cbdb_journey",
                    "source_grade": anchor["source_grade"],
                    "source_name": anchor["source_name"],
                    "source_url": anchor["source_url"],
                    "supports": ["composition_place_inferred"],
                }
            )
            if how == "ai_knowledge_map":
                evidence.append(
                    {
                        "evidence_id": "ev-ai-place-map",
                        "excerpt": (
                            f"模型知识地名表：{core_name(anchor['place'])} 即今 {modern}（{prov}）"
                            "——静态可审计映射，非文献出处"
                        ),
                        "source_family": "ai_model_knowledge",
                        "source_grade": "D",
                        "source_name": "KNOWLEDGE_PLACE_MAP（tools/promote_candidate_facts_relaxed.py）",
                        "source_url": "",
                        "supports": ["modern_place_resolution"],
                    }
                )
                stats["place_via_ai_map"] += 1
            rules.append("G2r_journey_collocation_relaxed")
            stats["with_place"] += 1
            poet_with_place[poet] += 1

        dynasty = pm.get("dynasty") or ""
        dynasty_counts[dynasty] += 1
        poet_counts[poet] += 1
        out.append(
            {
                "poem_key": {
                    "poet": poet, "title": title, "dynasty": dynasty,
                    "body_hash": next((r.get("body_hash") for f in fams.values() for r in f if r.get("body_hash")), ""),
                    "hash_ok": hash_ok,
                },
                "chronology": chronology,
                "evidence": evidence,
                "context_facts": [
                    {
                        "fact_id": "fact-promotion",
                        "text": (
                            f"放宽晋级（{'；'.join(rules)}）："
                            f"作年 {year_lo}{'–' + str(year_hi) if year_hi != year_lo else ''}"
                            + ("；作地为行旅同地推断（非直接文献主张）" if "G2r_journey_collocation_relaxed" in rules else "")
                        ),
                    }
                ],
                "verification": {
                    "status": "promoted_ai_assisted",
                    "rules": rules,
                    "reviewer": REVIEWER_STAMP,
                    "note": (
                        "放宽晋级·AI 辅助层：单源可用、容差放宽；模型知识仅用于地名解析"
                        "（grade D，静态表），文献证据全部来自真实来源；非人工核验，"
                        "与 promoted_by_rule / 人工 verified 三层分流"
                    ),
                },
            }
        )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out.sort(key=lambda r: (r["poem_key"]["poet"], r["poem_key"]["title"]))
    with open(OUT_JSONL, "w", encoding="utf-8") as f:
        for rec in out:
            f.write(json.dumps(rec, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n")

    covered = sorted(poet_counts)
    summary = {
        "n_promoted": len(out),
        "n_with_place": stats["with_place"],
        "n_place_via_ai_map": stats["place_via_ai_map"],
        "gate_counts": {k: v for k, v in stats.items() if k.startswith(("R1", "R2", "R3"))},
        "n_poets": len(covered),
        "poets": covered,
        "poets_with_place": sorted(poet_with_place),
        "dynasty_dist": dict(sorted(dynasty_counts.items())),
        "skipped": {k: v for k, v in stats.items() if k.startswith("skipped") or k == "gap_too_large"},
        "gates": {
            "R1_single_source_b": "仅 cnkgraph（B 级）单源 → 作年",
            "R2_single_source_c": "仅 souyun（C 级）单源 → 作年（最弱层）",
            "R3_dual_source_range": f"双源互差 2–{YEAR_TOL_DUAL} 年 → 作年区间",
            "G2r_journey_collocation_relaxed": (
                f"诗年 ±{JOURNEY_WIN} 窗口内带坐标行旅事件两两 ≤{int(CLUSTER_KM)}km → 推断作地"
            ),
            "ai_knowledge_map": "模型知识静态地名表（KNOWLEDGE_PLACE_MAP），仅作今地名解析，grade D，可审计",
        },
        "policy": (
            "AI 辅助放宽层：每条至少一条真实文献证据支撑作年；模型知识仅地名解析并标 grade D；"
            "与人工核验（verified）和严格晋级（promoted_by_rule）三层分流，零重叠；"
            "任何页面引用须以「AI 辅助放宽」徽章区分。"
        ),
        "reviewer": REVIEWER_STAMP,
        "generated_by": "tools/promote_candidate_facts_relaxed.py",
    }
    with open(OUT_SUMMARY, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2, allow_nan=False)

    print("OK  ->", OUT_JSONL, f"({OUT_JSONL.stat().st_size} bytes)")
    print("OK  ->", OUT_SUMMARY)
    print(
        f"放宽晋级 {len(out)} 首（带推断作地 {stats['with_place']}，其中知识表解析 {stats['place_via_ai_map']}） | "
        f"诗人 {len(covered)} | 朝代 {dict(dynasty_counts)}"
    )
    print("门分布:", {k: v for k, v in stats.items() if k.startswith(("R1", "R2", "R3"))})
    print("跳过:", {k: v for k, v in stats.items() if k.startswith("skipped") or k == "gap_too_large"})
    top = sorted(poet_with_place.items(), key=lambda kv: -kv[1])[:10]
    print("推断作地最多的诗人:", "、".join(f"{p}({n})" for p, n in top))


if __name__ == "__main__":
    main()
