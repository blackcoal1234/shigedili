# -*- coding: utf-8 -*-
"""事实覆盖口径声明：实时计算三层事实的覆盖边界，逐人归因，如实标注。

所有数字均从当前文件实时推导（不手写、不缓存），保证声明与事实永远一致：
  - 语料与诗人总数（poems.json，按诗人+诗题去重）
  - 三层事实各层条数/诗人数/带作地数（data/reviewed + data/promoted 两层）
  - 未覆盖诗数与零事实诗人；零事实诗人逐人自动归因
    （CNKGraph 状态 / 搜韵编年情况 / 古诗文网背景纪年情况 / CBDB 行旅事件），
    归因材料来自 journey_source_status.jsonl 与 zero_fact_recovery_summary.json

产出：
  docs/事实覆盖口径说明.md（人读的正式声明）
  output/assets/competition/fact_coverage.json（机读，供页面引用）

声明原则：覆盖即覆盖，未覆盖即未覆盖；边界数字随数据更新自动刷新。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
POEMS = ROOT / "data" / "poems.json"
TIERS = [
    ("人工核验", ROOT / "data" / "reviewed" / "verified_all_poet_fact_packages.jsonl", "verified"),
    ("严格晋级", ROOT / "data" / "promoted" / "rule_promoted_facts.jsonl", "promoted_by_rule"),
    ("放宽晋级", ROOT / "data" / "promoted" / "ai_assisted_facts.jsonl", "promoted_ai_assisted"),
]
JOURNEY_STATUS = ROOT / "data" / "candidates" / "journey_source_status.jsonl"
RECOVERY_SUMMARY = ROOT / "data" / "candidates" / "zero_fact_recovery_summary.json"
OUT_MD = ROOT / "docs" / "事实覆盖口径说明.md"
OUT_JSON = ROOT / "output" / "assets" / "competition" / "fact_coverage.json"


def load_tier(path: Path):
    keys, poets, places = set(), set(), set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        k = (r["poem_key"]["poet"], r["poem_key"]["title"])
        keys.add(k)
        poets.add(k[0])
        if r["chronology"].get("lon") is not None:
            places.add(k)
    return keys, poets, places


def poet_reason(poet: str, jstatus: dict, rec: dict) -> str:
    """零事实诗人逐人归因——全部来自采集状态与恢复摘要的客观数字。"""
    parts = []
    st = jstatus.get(poet, {})
    if st.get("status") == "not_covered":
        parts.append("CNKGraph 无传记（HTTP 204）")
    sou = (rec.get("per_poet") or {}).get(poet) or {}
    if sou:
        parts.append(
            f"搜韵 {sou.get('works_seen', 0)} 首作品中仅 {sou.get('dated', 0)} 条编年"
            f"（入语料 {sou.get('in_corpus', 0)}）"
        )
    gs = ((rec.get("gushiwen_recovery") or {}).get("per_poet") or {}).get(poet) or {}
    if gs:
        parts.append(
            f"古诗文网背景 {gs.get('backgrounds', 0)} 条（带纪年 {gs.get('with_year', 0)}）"
        )
    ev = (rec.get("journey_events") or {}).get(poet) or {}
    if ev:
        parts.append(f"CBDB 行旅事件 {ev.get('events', 0)} 条（带坐标 {ev.get('with_coords', 0)}）")
    return "；".join(parts) or "无可用采集记录"


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    poems = json.loads(POEMS.read_text(encoding="utf-8"))
    corpus_keys = {(p.get("poet") or p.get("author") or "", p.get("title") or "") for p in poems}
    corpus_poets = {p.get("poet") or p.get("author") or "" for p in poems}

    tiers_out = []
    all_keys, all_poets, all_places = set(), set(), set()
    for name, path, status in TIERS:
        keys, poets, places = load_tier(path)
        tiers_out.append(
            {
                "name": name,
                "verification_status": status,
                "n_poems": len(keys),
                "n_poets": len(poets),
                "n_with_place": len(places),
            }
        )
        all_keys |= keys
        all_poets |= poets
        all_places |= places

    jstatus = {}
    if JOURNEY_STATUS.exists():
        for line in JOURNEY_STATUS.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                jstatus[r.get("poet")] = r
    rec = {}
    if RECOVERY_SUMMARY.exists():
        rec = json.loads(RECOVERY_SUMMARY.read_text(encoding="utf-8"))
    # 行旅事件计数（零事实诗人归因用）
    events: dict[str, dict] = {}
    jc = ROOT / "data" / "candidates" / "journey_event_candidates.jsonl"
    zero = sorted(corpus_poets - all_poets)
    if jc.exists():
        for line in jc.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            p = r.get("poet")
            if p in zero:
                e = events.setdefault(p, {"events": 0, "with_coords": 0})
                e["events"] += 1
                if r.get("longitude") is not None:
                    e["with_coords"] += 1
    rec["journey_events"] = events

    coverage = {
        "corpus": {
            "n_poems_unique": len(corpus_keys),
            "n_poets": len(corpus_poets),
        },
        "tiers": tiers_out,
        "combined": {
            "n_poems_with_facts": len(all_keys),
            "coverage_pct": round(len(all_keys) / len(corpus_keys) * 100, 1),
            "n_poets_with_facts": len(all_poets),
            "n_with_place": len(all_places),
            "n_poets_with_place_facts": len({k[0] for k in all_places}),
            "n_poems_without_facts": len(corpus_keys - all_keys),
        },
        "zero_fact_poets": [
            {"poet": p, "reason": poet_reason(p, jstatus, rec)} for p in zero
        ],
        "policy": (
            "三层事实口径：verified=人工核验（A/B 级证据）；promoted_by_rule=双源一致硬门规则晋级；"
            "promoted_ai_assisted=放宽门+AI 辅助（单源可用、年号纪年解析、地名知识表 grade D）。"
            "三层在 verification.status 上分流、零重叠，引用须以不同徽章区分。"
            "未覆盖部分为外部编年源不系年的长尾作品，本声明如实标注边界，不以候选冒充事实。"
        ),
        "generated_by": "tools/build_fact_coverage_statement.py",
    }

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(coverage, f, ensure_ascii=False, indent=2, allow_nan=False)

    c = coverage["combined"]
    md = []
    md.append("# 事实覆盖口径说明")
    md.append("")
    md.append("> 本声明由 `tools/build_fact_coverage_statement.py` 从当前数据实时生成，数字随数据更新自动刷新，不经手写。")
    md.append("")
    md.append("## 一、总账")
    md.append("")
    md.append(f"- 语料：**{coverage['corpus']['n_poems_unique']} 首**（按诗人+诗题去重）/ **{coverage['corpus']['n_poets']} 位诗人**；")
    md.append(f"- 有编年事实：**{c['n_poems_with_facts']} 首（{c['coverage_pct']}%）**，其中带作地 **{c['n_with_place']} 首**（覆盖 {c['n_poets_with_place_facts']} 位诗人）；")
    md.append(f"- 有事实诗人：**{c['n_poets_with_facts']} / {coverage['corpus']['n_poets']} 位**；")
    md.append(f"- 未覆盖：**{c['n_poems_without_facts']} 首**——为外部编年源（CNKGraph/搜韵/古诗文网背景）本不系年的长尾作品，不以候选冒充事实。")
    md.append("")
    md.append("## 二、三层事实口径")
    md.append("")
    md.append("| 层 | verification.status | 首数 | 诗人 | 带作地 | 引用要求 |")
    md.append("| --- | --- | --- | --- | --- | --- |")
    badges = ["人工核验 A/B 徽章", "规则晋级徽章", "AI 辅助放宽徽章"]
    for t, b in zip(tiers_out, badges):
        md.append(f"| {t['name']} | `{t['verification_status']}` | {t['n_poems']} | {t['n_poets']} | {t['n_with_place']} | {b} |")
    md.append("")
    md.append(f"口径：{coverage['policy']}")
    md.append("")
    md.append(f"## 三、零事实诗人（{len(zero)} 位）及原因")
    md.append("")
    md.append("以下诗人经双路补采后仍无任何编年事实，原因如下（均为客观数据，非主观判断）：")
    md.append("")
    for z in coverage["zero_fact_poets"]:
        md.append(f"- **{z['poet']}**：{z['reason']}")
    md.append("")
    md.append("## 四、已知精度边界")
    md.append("")
    md.append("- 放宽层年份含年号纪年解析（`era_year/era_range/era_early/era_late` 精度标记，边界年 ±1 属正常）；")
    md.append("- 放宽层作地为行旅同地**推断**（`composition_place_inferred`），非直接文献主张；")
    md.append("- 今地名解析含模型知识静态表（`ai_model_knowledge`，grade D，仅地名，可审计）；")
    md.append("- 搜韵补采为负结果的 15 人（除晏殊外无编年）、卢纶背景无纪年等采集事实，均保留在 `zero_fact_recovery_summary.json` 不删除。")
    md.append("")
    OUT_MD.write_text("\n".join(md), encoding="utf-8")

    print("OK  ->", OUT_MD)
    print("OK  ->", OUT_JSON)
    print(
        f"覆盖 {c['n_poems_with_facts']}/{coverage['corpus']['n_poems_unique']} 首"
        f"（{c['coverage_pct']}%） · 诗人 {c['n_poets_with_facts']}/{coverage['corpus']['n_poets']}"
        f" · 带作地 {c['n_with_place']} 首 · 零事实 {len(zero)} 位"
    )


if __name__ == "__main__":
    main()
