# -*- coding: utf-8 -*-
"""候选证据 → 规则晋级事实（不冒充人工核验）。

背景：人工核验事实包 124 首（6 人带坐标）远不够 88 人扩卷；候选层有
63,556 条作品系年（cnkgraph B / souyun C，其中 4,243 首双来源族）与
41,226 条行旅事件（全部带古地名、40,750 条带 CHGIS 坐标）。本工具用
确定性规则把达标候选晋级为「规则晋级事实」，与人工核验严格分流。

晋级门（全部硬性，无随机）：
  G1 双源作年：同一（诗人, 诗题）在 ≥2 个不同来源族（cnkgraph/souyun）
     均有年份且互差 ≤1 年 → 晋级 composition_date，两条来源全量入证据链。
  G2 行旅同地佐证（仅推断作地，非直接主张）：G1 通过的诗，若诗人在
     [诗年-1, 诗年+1] 窗口内有带坐标的行旅事件，且这些事件地点两两相距
     均 ≤300km（同年多点远隔视为行踪不明，不作地），则附 composition_place，
     evidence 标注 journey_collocation；supports 为 composition_place_inferred。

诚实约束：
  - verification.status = "promoted_by_rule"，reviewer =
    "codex_rule_promotion_2026-08-16"，note 明示「规则晋级·非人工核验；
    作地为行旅同地推断」；
  - 已在人工核验事实包（124 首）中的诗不重复晋级；
  - 输出至 data/promoted/，绝不写入 data/reviewed/；
  - 年份/地点/坐标全部来自候选原值，坐标取行旅事件的 CHGIS 回填值，
    今地名经 place_dict 解析（解析不出则留空并记 note，不猜测）。

产出：data/promoted/rule_promoted_facts.jsonl + rule_promoted_summary.json
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
OUT_DIR = ROOT / "data" / "promoted"
OUT_JSONL = OUT_DIR / "rule_promoted_facts.jsonl"
OUT_SUMMARY = OUT_DIR / "rule_promoted_summary.json"

YEAR_TOL = 1
PLACE_CLUSTER_KM = 300.0
REVIEWER_STAMP = "codex_rule_promotion_2026-08-16"

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


def resolve_modern(historical: str):
    """地名 → place_dict 今地名/省份：去括注后依次查别名列、今名列、去尾缀两列。

    只做词典精确解析，不做模糊猜测（项目门禁）。
    """
    name = (historical or "").strip()
    if not name:
        return None, None
    name = re.sub(r"[（(][^）)]*[）)]", "", name).strip()  # 「勉县（西县）」「莆田 (出生地)」→ 本名
    if not name:
        return None, None
    for cand in (name, re.sub(r"(府|郡|县|路|军|监|州)$", "", name)):
        if not cand:
            continue
        hit = ALIAS_INDEX.get(cand) or MODERN_INDEX.get(cand) or MODERN_INDEX.get(norm_place(cand))
        if hit:
            return hit["modern"], hit["province"]
    return None, None


def load_work_candidates() -> dict[tuple[str, str], dict[str, list[dict]]]:
    """按（诗人, 诗题）聚合系年候选（主候选 + 零事实诗人补采恢复文件），按来源族分组。"""
    grouped: dict[tuple[str, str], dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    paths = [WORK_CAND] + ([RECOVERY_CAND] if RECOVERY_CAND.exists() else [])
    for path in paths:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                r = json.loads(line)
                if r.get("event_type") != "work_chronology":
                    continue
                if r.get("year_start") is None:
                    continue
                grouped[(r.get("poet") or "", r.get("poem_title") or "")][r.get("source") or "?"].append(r)
    return grouped


def load_journey_events() -> dict[str, list[dict]]:
    """诗人 → 带坐标的行旅事件（含年份窗口与地点）。"""
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
                    "source": r.get("source") or "cbdb",
                    "source_name": r.get("source_name") or "",
                    "source_grade": r.get("source_grade") or "B",
                    "source_url": r.get("source_url") or "",
                    "note": r.get("source_note") or "",
                }
            )
    return events


def gate1_dual_year(families: dict[str, list[dict]]) -> list[dict] | None:
    """G1：≥2 来源族且年份互差 ≤1；返回入选证据（每族取年份中位最早一条）。"""
    fams = [f for f in families if f != "?"]
    if len(fams) < 2:
        return None
    picks = []
    years = []
    for fam in fams:
        rows = [r for r in families[fam] if r.get("year_start") is not None]
        if not rows:
            continue
        rows.sort(key=lambda r: (r["year_start"], r.get("candidate_id") or ""))
        pick = rows[0]
        picks.append(pick)
        years.append(int(pick["year_start"]))
    if len(picks) < 2:
        return None
    if max(years) - min(years) > YEAR_TOL:
        return None
    return picks


def gate2_journey_place(events: list[dict], year: int) -> dict | None:
    """G2：诗年 ±1 窗口内带坐标事件两两 ≤300km 才作地；返回作地或 None。"""
    window = [e for e in events if abs(e["year"] - year) <= YEAR_TOL]
    if not window:
        return None
    for i in range(len(window)):
        for j in range(i + 1, len(window)):
            if haversine_km(window[i]["lon"], window[i]["lat"], window[j]["lon"], window[j]["lat"]) > PLACE_CLUSTER_KM:
                return None  # 同年多地方远隔——行踪不明，不作地
    anchor = sorted(window, key=lambda e: (abs(e["year"] - year), e["year"], e["place"]))[0]
    return {"anchor": anchor, "events": window}


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    poems = json.loads(POEMS_PATH.read_text(encoding="utf-8"))
    poem_by_key = {}
    for p in poems:
        poem_by_key[(p.get("poet") or p.get("author") or "", p.get("title") or "")] = p

    verified_keys = set()
    if REVIEWED_PACKAGES.exists():
        with open(REVIEWED_PACKAGES, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                k = json.loads(line)["poem_key"]
                verified_keys.add((k["poet"], k["title"]))

    grouped = load_work_candidates()
    journeys = load_journey_events()

    out_records = []
    stats = {"g1_only": 0, "g1_g2_with_place": 0, "skipped_verified": 0, "skipped_no_corpus": 0,
             "ambiguous_year": 0}
    poets_with_coords: dict[str, int] = defaultdict(int)
    poet_counts: dict[str, int] = defaultdict(int)
    dynasty_counts: dict[str, int] = defaultdict(int)

    for (poet, title), families in sorted(grouped.items()):
        if (poet, title) in verified_keys:
            stats["skipped_verified"] += 1
            continue
        pm = poem_by_key.get((poet, title))
        if not pm:
            stats["skipped_no_corpus"] += 1
            continue
        picks = gate1_dual_year(families)
        if not picks:
            stats["ambiguous_year"] += 1
            continue

        years = [int(r["year_start"]) for r in picks]
        year = min(years)
        body = pm.get("body") or ""
        hash_ok = bool(body) and hashlib.sha256(body.encode()).hexdigest() == picks[0].get("body_hash")

        evidence = []
        for r in picks:
            evidence.append(
                {
                    "evidence_id": f"ev-{r.get('source')}",
                    "excerpt": (r.get("source_note") or "")[:120],
                    "source_family": r.get("source"),
                    "source_grade": r.get("source_grade") or "C",
                    "source_name": r.get("source_name") or "",
                    "source_url": r.get("source_url") or "",
                    "supports": ["composition_date"],
                }
            )

        chronology = {
            "historical_place": "",
            "modern_place": "",
            "province": "",
            "lon": None,
            "lat": None,
            "year_start": year,
            "year_end": max(years),
            "year_precision": "year",
        }
        rules = ["G1_dual_source_year"]

        g2 = gate2_journey_place(journeys.get(poet, []), year)
        if g2 is not None:
            anchor = g2["anchor"]
            modern, province = resolve_modern(anchor["place"])
            chronology.update(
                {
                    "historical_place": anchor["place"],
                    "modern_place": modern or "",
                    "province": norm_place(province) if province else "",
                    "lon": round(anchor["lon"], 4),
                    "lat": round(anchor["lat"], 4),
                }
            )
            evidence.append(
                {
                    "evidence_id": "ev-journey-collocation",
                    "excerpt": (
                        f"诗人{year}年前后行旅事件见于{anchor['place']}"
                        f"（{len(g2['events'])} 条带坐标事件，两两 ≤{int(PLACE_CLUSTER_KM)}km）"
                    ),
                    "source_family": "cbdb_journey",
                    "source_grade": anchor["source_grade"],
                    "source_name": anchor["source_name"],
                    "source_url": anchor["source_url"],
                    "supports": ["composition_place_inferred"],
                }
            )
            rules.append("G2_journey_collocation")
            stats["g1_g2_with_place"] += 1
            poets_with_coords[poet] += 1
        else:
            stats["g1_only"] += 1

        dynasty = pm.get("dynasty") or ""
        dynasty_counts[dynasty] += 1
        poet_counts[poet] += 1

        out_records.append(
            {
                "poem_key": {
                    "poet": poet,
                    "title": title,
                    "dynasty": dynasty,
                    "body_hash": picks[0].get("body_hash") or "",
                    "hash_ok": hash_ok,
                },
                "chronology": chronology,
                "evidence": evidence,
                "context_facts": [
                    {
                        "fact_id": "fact-promotion",
                        "text": (
                            f"规则晋级：{'、'.join(sorted({e['source_family'] for e in evidence[:2]}))} "
                            f"双源系年一致（{years[0]}{'–' + str(years[-1]) if years[-1] != years[0] else ''}）"
                            + ("；作地为行旅同地推断（非直接文献主张）" if "G2_journey_collocation" in rules else "")
                        ),
                    }
                ],
                "verification": {
                    "status": "promoted_by_rule",
                    "rules": rules,
                    "reviewer": REVIEWER_STAMP,
                    "note": "规则晋级·非人工核验；不写入 data/reviewed，不与 A/B 级人工事实混用",
                },
            }
        )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_records.sort(key=lambda r: (r["poem_key"]["poet"], r["poem_key"]["title"]))
    with open(OUT_JSONL, "w", encoding="utf-8") as f:
        for rec in out_records:
            f.write(json.dumps(rec, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n")

    covered_poets = sorted(poet_counts)
    new_poets = [p for p in covered_poets if p not in {"李白", "杜甫", "白居易", "苏轼", "陆游", "李清照"}]
    summary = {
        "n_promoted": len(out_records),
        "n_with_place": stats["g1_g2_with_place"],
        "n_date_only": stats["g1_only"],
        "n_poets": len(covered_poets),
        "n_poets_beyond_six": len(new_poets),
        "poets_beyond_six": new_poets,
        "poets_with_inferred_place": sorted(poets_with_coords),
        "dynasty_dist": dict(sorted(dynasty_counts.items())),
        "skipped": stats,
        "gates": {
            "G1_dual_source_year": f"≥2 来源族且年份互差 ≤{YEAR_TOL}；每族取最早年份记录",
            "G2_journey_collocation": (
                f"诗年 ±{YEAR_TOL} 窗口内带坐标行旅事件两两 ≤{int(PLACE_CLUSTER_KM)}km，"
                "作地为推断（supports=composition_place_inferred），非直接文献主张"
            ),
        },
        "policy": (
            "本集为规则晋级事实：verification.status=promoted_by_rule，"
            "与 data/reviewed 的人工核验事实严格分流；作地一律标注推断；"
            "不自动写入任何核验发布物。卷二若采用，页面须以「规则晋级」徽章区分「人工核验 A/B」。"
        ),
        "reviewer": REVIEWER_STAMP,
        "generated_by": "tools/promote_candidate_facts.py",
    }
    with open(OUT_SUMMARY, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2, allow_nan=False)

    print("OK  ->", OUT_JSONL, f"({OUT_JSONL.stat().st_size} bytes)")
    print("OK  ->", OUT_SUMMARY)
    print(
        f"晋级 {len(out_records)} 首（带推断作地 {stats['g1_g2_with_place']}） | "
        f"诗人 {len(covered_poets)}（六家之外 {len(new_poets)}） | 朝代 {dict(dynasty_counts)}"
    )
    print(f"跳过：已在人工核验 {stats['skipped_verified']} / 不在语料 {stats['skipped_no_corpus']} / 年份不合门 {stats['ambiguous_year']}")
    top = sorted(poets_with_coords.items(), key=lambda kv: -kv[1])[:8]
    print("推断作地最多的诗人:", "、".join(f"{p}({n})" for p, n in top))


if __name__ == "__main__":
    main()
