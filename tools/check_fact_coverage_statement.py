# -*- coding: utf-8 -*-
"""fact_coverage 质量门：声明数字与三层事实文件逐项一致、确定性重建。"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MD = ROOT / "docs" / "事实覆盖口径说明.md"
JSONF = ROOT / "output" / "assets" / "competition" / "fact_coverage.json"
TIERS = [
    ROOT / "data" / "reviewed" / "verified_all_poet_fact_packages.jsonl",
    ROOT / "data" / "promoted" / "rule_promoted_facts.jsonl",
    ROOT / "data" / "promoted" / "ai_assisted_facts.jsonl",
]


def tier_counts(path: Path):
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
    return len(keys), len(poets), len(places)


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    for p in (MD, JSONF):
        if not p.exists():
            raise SystemExit(f"[failed] 缺少 {p}，先运行 tools/build_fact_coverage_statement.py")

    # 确定性
    before = hashlib.md5(JSONF.read_bytes()).hexdigest()
    subprocess.run(
        [sys.executable, "tools/build_fact_coverage_statement.py"],
        cwd=ROOT, check=True, capture_output=True,
    )
    after = hashlib.md5(JSONF.read_bytes()).hexdigest()
    assert before == after, "覆盖声明重建不一致"

    cov = json.loads(JSONF.read_text(encoding="utf-8"))
    poems = json.loads((ROOT / "data" / "poems.json").read_text(encoding="utf-8"))
    corpus_keys = {(p.get("poet") or p.get("author") or "", p.get("title") or "") for p in poems}
    corpus_poets = {p.get("poet") or p.get("author") or "" for p in poems}
    assert cov["corpus"]["n_poems_unique"] == len(corpus_keys), "语料数不一致"
    assert cov["corpus"]["n_poets"] == len(corpus_poets), "诗人数不一致"

    all_keys, all_poets, all_places = set(), set(), set()
    assert len(cov["tiers"]) == len(TIERS)
    for t, path in zip(cov["tiers"], TIERS):
        n, np_, npl = tier_counts(path)
        assert t["n_poems"] == n, f"{t['name']} 首数不一致"
        assert t["n_poets"] == np_, f"{t['name']} 诗人数不一致"
        assert t["n_with_place"] == npl, f"{t['name']} 作地数不一致"
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                k = (r["poem_key"]["poet"], r["poem_key"]["title"])
                all_keys.add(k)
                all_poets.add(k[0])
                if r["chronology"].get("lon") is not None:
                    all_places.add(k)

    c = cov["combined"]
    assert c["n_poems_with_facts"] == len(all_keys), "合计首数不一致"
    assert c["n_poets_with_facts"] == len(all_poets), "合计诗人不一致"
    assert c["n_with_place"] == len(all_places), "合计作地不一致"
    assert c["n_poems_without_facts"] == len(corpus_keys - all_keys), "未覆盖数不一致"
    assert abs(c["coverage_pct"] - round(len(all_keys) / len(corpus_keys) * 100, 1)) < 0.05, "覆盖率不一致"

    zero_expected = sorted(corpus_poets - all_poets)
    zero_stated = [z["poet"] for z in cov["zero_fact_poets"]]
    assert zero_stated == zero_expected, f"零事实诗人不一致：{zero_stated} vs {zero_expected}"
    for z in cov["zero_fact_poets"]:
        assert z["reason"].strip(), f"{z['poet']} 归因为空"

    md = MD.read_text(encoding="utf-8")
    for needle in ("三层事实口径", "零事实诗人", "不以候选冒充事实", str(c["n_poems_with_facts"])):
        assert needle in md, f"声明文档缺少 {needle}"

    print(
        f"[ok] fact_coverage：{c['n_poems_with_facts']}/{len(corpus_keys)} 首（{c['coverage_pct']}%）· "
        f"诗人 {c['n_poets_with_facts']}/{len(corpus_poets)} · 零事实 {len(zero_stated)} 位逐人归因 · "
        f"数字与三层文件逐项一致 · 确定性重建通过"
    )


if __name__ == "__main__":
    main()
