# -*- coding: utf-8 -*-
"""rule_promoted_facts.jsonl 质量门：晋级规则复核、诚实标注、与人工核验零重叠。"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JSONL = ROOT / "data" / "promoted" / "rule_promoted_facts.jsonl"
SUMMARY = ROOT / "data" / "promoted" / "rule_promoted_summary.json"
REVIEWED = ROOT / "data" / "reviewed" / "verified_all_poet_fact_packages.jsonl"
POEMS = ROOT / "data" / "poems.json"

LON_MIN, LON_MAX = 73, 136
LAT_MIN, LAT_MAX = 17, 54
YEAR_TOL = 1


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    if not JSONL.exists():
        raise SystemExit(f"[failed] 缺少 {JSONL}，先运行 tools/promote_candidate_facts.py")

    # 确定性：重建逐字节一致
    digest_before = hashlib.md5(JSONL.read_bytes()).hexdigest()
    subprocess.run(
        [sys.executable, "tools/promote_candidate_facts.py"],
        cwd=ROOT, check=True, capture_output=True,
    )
    digest_after = hashlib.md5(JSONL.read_bytes()).hexdigest()
    assert digest_before == digest_after, "晋级结果重建不一致（存在非确定性来源）"

    records = [json.loads(l) for l in JSONL.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(records) >= 1000, f"晋级条数异常：{len(records)}"

    poems = json.loads(POEMS.read_text(encoding="utf-8"))
    corpus_keys = {(p.get("poet") or p.get("author") or "", p.get("title") or "") for p in poems}
    verified_keys = set()
    with open(REVIEWED, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                k = json.loads(line)["poem_key"]
                verified_keys.add((k["poet"], k["title"]))

    seen = set()
    n_place = 0
    for rec in records:
        key = rec["poem_key"]
        pk = (key["poet"], key["title"])
        assert pk not in seen, f"重复晋级：{pk}"
        seen.add(pk)
        assert pk in corpus_keys, f"晋级诗不在语料：{pk}"
        assert pk not in verified_keys, f"与人工核验重叠（禁止）：{pk}"

        v = rec["verification"]
        assert v["status"] == "promoted_by_rule", f"{pk} 状态标注错误"
        assert v["reviewer"] == "codex_rule_promotion_2026-08-16", f"{pk} 审者印记错误"
        assert "非人工核验" in v["note"], f"{pk} 缺诚实标注"
        rules = v["rules"]
        assert "G1_dual_source_year" in rules, f"{pk} 缺 G1"

        # G1 复核：≥2 来源族、年份互差 ≤1
        date_ev = [e for e in rec["evidence"] if "composition_date" in e["supports"]]
        fams = {e["source_family"] for e in date_ev}
        assert len(fams) >= 2, f"{pk} 来源族不足 2：{fams}"
        years = [rec["chronology"]["year_start"], rec["chronology"]["year_end"]]
        assert years[1] - years[0] <= YEAR_TOL, f"{pk} 年份跨度超限：{years}"

        # G2 复核：有作地 ⟺ 规则含 G2；坐标界内；推断标注
        chron = rec["chronology"]
        has_place = bool(chron.get("historical_place"))
        if has_place:
            n_place += 1
            assert "G2_journey_collocation" in rules, f"{pk} 有作地但缺 G2 规则"
            lon, lat = chron["lon"], chron["lat"]
            assert LON_MIN <= lon <= LON_MAX and LAT_MIN <= lat <= LAT_MAX, f"{pk} 坐标越界"
            journey_ev = [e for e in rec["evidence"] if e["source_family"] == "cbdb_journey"]
            assert journey_ev and journey_ev[0]["supports"] == ["composition_place_inferred"], (
                f"{pk} 行旅证据未标推断"
            )
        else:
            assert "G2_journey_collocation" not in rules, f"{pk} 无作地却带 G2"
            assert chron["lon"] is None and chron["lat"] is None, f"{pk} 无作地却有坐标"

    summary = json.loads(SUMMARY.read_text(encoding="utf-8"))
    assert summary["n_promoted"] == len(records), "summary 题数不一致"
    assert summary["n_with_place"] == n_place, "summary 作地数不一致"
    assert summary["n_poets"] == len({r["poem_key"]["poet"] for r in records}), "summary 诗人数不一致"
    assert "分流" in summary["policy"] and "promoted_by_rule" in summary["policy"], "policy 缺分流声明"

    print(
        f"[ok] rule_promoted_facts：{len(records)} 首（推断作地 {n_place}）| "
        f"诗人 {summary['n_poets']}（六家外 {summary['n_poets_beyond_six']}）| "
        f"G1 双源复核/G2 推断标注/与人工核验零重叠/确定性重建 全部通过"
    )


if __name__ == "__main__":
    main()
