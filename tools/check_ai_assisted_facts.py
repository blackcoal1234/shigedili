# -*- coding: utf-8 -*-
"""ai_assisted_facts.jsonl 质量门：文献证据必备、知识层独立标注、三层零重叠。"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JSONL = ROOT / "data" / "promoted" / "ai_assisted_facts.jsonl"
SUMMARY = ROOT / "data" / "promoted" / "ai_assisted_summary.json"
REVIEWED = ROOT / "data" / "reviewed" / "verified_all_poet_fact_packages.jsonl"
STRICT = ROOT / "data" / "promoted" / "rule_promoted_facts.jsonl"
POEMS = ROOT / "data" / "poems.json"

LON_MIN, LON_MAX = 73, 136
LAT_MIN, LAT_MAX = 17, 54
BIB_FAMILIES = {"cnkgraph", "souyun", "gushiwen"}
ALLOWED_RULES = {"R1_single_source_b", "R2_single_source_c", "R3_dual_source_range", "R3_dual_exact"}
PLACE_RULE = "G2r_journey_collocation_relaxed"


def load_keys(path: Path):
    keys = set()
    if path.exists():
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    k = json.loads(line)["poem_key"]
                    keys.add((k["poet"], k["title"]))
    return keys


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    if not JSONL.exists():
        raise SystemExit(f"[failed] 缺少 {JSONL}，先运行 tools/promote_candidate_facts_relaxed.py")

    # 确定性
    before = hashlib.md5(JSONL.read_bytes()).hexdigest()
    subprocess.run(
        [sys.executable, "tools/promote_candidate_facts_relaxed.py"],
        cwd=ROOT, check=True, capture_output=True,
    )
    after = hashlib.md5(JSONL.read_bytes()).hexdigest()
    assert before == after, "放宽晋级重建不一致（非确定性来源）"

    records = [json.loads(l) for l in JSONL.read_text(encoding="utf-8").splitlines() if l.strip()]
    poems = json.loads(POEMS.read_text(encoding="utf-8"))
    corpus = {(p.get("poet") or p.get("author") or "", p.get("title") or "") for p in poems}
    overlap_forbidden = load_keys(REVIEWED) | load_keys(STRICT)

    seen = set()
    n_place = 0
    n_ai_map = 0
    for rec in records:
        key = rec["poem_key"]
        pk = (key["poet"], key["title"])
        assert pk not in seen, f"重复：{pk}"
        seen.add(pk)
        assert pk in corpus, f"不在语料：{pk}"
        assert pk not in overlap_forbidden, f"与人工核验/严格晋级重叠（禁止）：{pk}"

        v = rec["verification"]
        assert v["status"] == "promoted_ai_assisted", f"{pk} 状态错误"
        assert v["reviewer"] == "codex_relaxed_promotion_2026-08-16", f"{pk} 审者印记错误"
        assert "放宽" in v["note"] and "非人工核验" in v["note"], f"{pk} 缺放宽/分流标注"

        rules = set(v["rules"])
        assert rules & ALLOWED_RULES, f"{pk} 缺 R 门规则"
        assert rules - ({PLACE_RULE} | ALLOWED_RULES) == set(), f"{pk} 未知规则：{rules}"

        # 文献证据必备：作年必须至少一条真实来源
        date_bib = [
            e for e in rec["evidence"]
            if e["source_family"] in BIB_FAMILIES and "composition_date" in e["supports"]
        ]
        assert date_bib, f"{pk} 缺文献作年证据"
        for e in date_bib:
            assert e["source_grade"] in {"B", "C"}, f"{pk} 文献等级异常"
            assert e["source_name"] and e["source_url"], f"{pk} 文献证据缺出处"
        # R1 单源 B：唯一文献族必须是 cnkgraph；R2 只能是 souyun
        fams = {e["source_family"] for e in date_bib}
        if "R1_single_source_b" in rules:
            assert fams == {"cnkgraph"}, f"{pk} R1 族异常：{fams}"
        if "R2_single_source_c" in rules:
            assert fams <= {"souyun", "gushiwen"} and fams, f"{pk} R2 族异常：{fams}"

        # 模型知识层：只能做地名解析，grade D，且仅当 place_resolution 命中知识表
        ai_ev = [e for e in rec["evidence"] if e["source_family"] == "ai_model_knowledge"]
        chron = rec["chronology"]
        for e in ai_ev:
            assert e["source_grade"] == "D", f"{pk} 知识层等级必须 D"
            assert e["supports"] == ["modern_place_resolution"], f"{pk} 知识层支持项越界"
            assert not e["source_url"], f"{pk} 知识层不得伪造出处链接"
        has_place = bool(chron.get("historical_place"))
        if has_place:
            n_place += 1
            assert PLACE_RULE in rules, f"{pk} 有作地缺 G2r"
            assert LON_MIN <= chron["lon"] <= LON_MAX and LAT_MIN <= chron["lat"] <= LAT_MAX, f"{pk} 坐标越界"
            assert chron["place_resolution"] in {"dict", "dict_prefix", "ai_knowledge_map", None}, (
                f"{pk} 解析来源非法"
            )
            if chron["place_resolution"] is None:
                assert not chron.get("modern_place"), f"{pk} 未解析却有今地名"
            journey = [e for e in rec["evidence"] if e["source_family"] == "cbdb_journey"]
            assert journey and journey[0]["supports"] == ["composition_place_inferred"], f"{pk} 行旅推断未标注"
            if chron["place_resolution"] == "ai_knowledge_map":
                n_ai_map += 1
                assert ai_ev, f"{pk} 知识表命中但无知识层证据"
            else:
                assert not ai_ev, f"{pk} 非知识表解析不应有知识层证据"
        else:
            assert PLACE_RULE not in rules and chron["lon"] is None, f"{pk} 无作地却有作地规则/坐标"
            assert not ai_ev, f"{pk} 无作地不应有知识层证据"

    summary = json.loads(SUMMARY.read_text(encoding="utf-8"))
    assert summary["n_promoted"] == len(records), "summary 题数不一致"
    assert summary["n_with_place"] == n_place, "summary 作地数不一致"
    assert summary["n_place_via_ai_map"] == n_ai_map, "summary 知识表计数不一致"
    assert summary["n_poets"] == len({r["poem_key"]["poet"] for r in records}), "summary 诗人数不一致"
    assert "三层分流" in summary["policy"], "policy 缺三层分流声明"

    print(
        f"[ok] ai_assisted_facts：{len(records)} 首（推断作地 {n_place}，知识表解析 {n_ai_map}）| "
        f"诗人 {summary['n_poets']} | 文献证据必备/R 门族一致/知识层 grade-D 限地名/三层零重叠/确定性重建 全部通过"
    )


if __name__ == "__main__":
    main()
