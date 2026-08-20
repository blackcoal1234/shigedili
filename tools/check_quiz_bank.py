# -*- coding: utf-8 -*-
"""quiz_bank.json 质量门：结构、防泄底、证据等级、提示完备。"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PATH = ROOT / "output" / "assets" / "competition" / "quiz_bank.json"

LON_MIN, LON_MAX = 73, 136
LAT_MIN, LAT_MAX = 17, 54
MIN_QUESTIONS = 20
MAX_PER_POET = 4


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    if not PATH.exists():
        raise SystemExit(f"[failed] 缺少 {PATH}，先运行 tools/build_quiz_bank.py")
    data = json.loads(PATH.read_text(encoding="utf-8"))
    meta, questions = data["meta"], data["questions"]

    assert len(questions) >= MIN_QUESTIONS, f"题数 {len(questions)} < {MIN_QUESTIONS}"

    ids = set()
    per_poet: Counter = Counter()
    diff_count: Counter = Counter()
    for q in questions:
        qid = q["id"]
        assert qid and qid not in ids, f"题目 id 重复：{qid}"
        ids.add(qid)

        ans = q["answer"]
        assert ans.get("modern") and ans.get("province"), f"{qid} 答案缺今地名/省份"
        lon, lat = ans["lon"], ans["lat"]
        assert LON_MIN <= lon <= LON_MAX and LAT_MIN <= lat <= LAT_MAX, (
            f"{qid} 答案坐标越界 {lon},{lat}"
        )
        assert ans.get("grade") in {"A", "B"}, f"{qid} 答案证据等级非 A/B：{ans.get('grade')}"

        assert q["difficulty"] in (1, 2, 3), f"{qid} 难度非法"
        diff_count[q["difficulty"]] += 1
        per_poet[q["poet"]] += 1
        assert per_poet[q["poet"]] <= MAX_PER_POET, f"{qid} 诗人 {q['poet']} 超出每人上限"

        # 防泄底：展示句不得含诗人名、题目
        for line in q["lines"]:
            assert line.strip(), f"{qid} 展示句为空"
            assert q["poet"] not in line, f"{qid} 展示句泄露诗人名：{line}"
            assert q["title"] not in line or len(q["title"]) <= 2, f"{qid} 展示句泄露题目：{line}"

        # 三级提示完备
        hints = q["hints"]
        for key in ("province", "place", "imagery"):
            h = hints.get(key)
            assert h and (h.get("text") or "").strip(), f"{qid} 缺 {key} 提示"
        assert hints["province"]["correct"] != hints["province"]["decoy"], (
            f"{qid} 省份提示干扰项与正确项相同"
        )
        assert hints["province"]["correct"] == ans["province"], f"{qid} 省份提示与答案省份不一致"

        # 考据与导读分离
        for ev in q["evidence"]:
            assert ev["grade"] in {"A", "B"}, f"{qid} 考据证据混入非 A/B：{ev}"
            assert ev["source"], f"{qid} 证据缺出处"
        intro = q["reading_intro"]
        assert intro["generated_by"] == "rules_template", f"{qid} 导读来源标注错误"
        assert "非人工考据" in intro["label"], f"{qid} 导读未标注「非人工考据」"
        assert intro["text"].strip(), f"{qid} 导读为空"

        for more in q["same_place_more"]:
            assert more["poet"] and more["title"] and more["line"], f"{qid} 同地再读条目不完整"

    # 教学关：前 3 题应为难度 1
    for q in questions[:3]:
        assert q["difficulty"] == 1, f"教学关 {q['id']} 难度应为 1，实际 {q['difficulty']}"

    # 章节结构：完整划分、诗印唯一、考据馆链接规范
    chapters = data.get("chapters") or []
    assert len(chapters) >= 3, f"章节数 {len(chapters)} < 3"
    seen_qids: set = set()
    seals: set = set()
    for ch in chapters:
        assert ch.get("id") and ch.get("name") and ch.get("theme"), f"章节元信息缺失：{ch.get('id')}"
        assert ch["seal"] and ch["seal"] not in seals, f"诗印重复：{ch['seal']}"
        seals.add(ch["seal"])
        qids = ch.get("question_ids") or []
        assert len(qids) >= 3, f"章节 {ch['name']} 仅 {len(qids)} 题"
        for qid in qids:
            assert qid in ids, f"章节 {ch['name']} 引用未知题目 {qid}"
            assert qid not in seen_qids, f"题目 {qid} 被多章引用"
            seen_qids.add(qid)
        # 省份归章的完整覆盖由构建器断言，此处校验结构完整性
        assert ch.get("archives"), f"章节 {ch['name']} 缺考据馆链接"
        for a in ch["archives"]:
            assert a.get("title") and a.get("url", "").endswith(".html"), f"考据馆链接不完整：{a}"
    assert seen_qids == ids, f"章节未完整覆盖题目：缺 {ids - seen_qids}，多 {seen_qids - ids}"

    policy = meta.get("hint_policy") or {}
    for key in ("province", "place", "imagery"):
        assert 0 < policy.get(key, 0) <= 1, f"meta.hint_policy.{key} 缺失或非法"

    print(
        f"[ok] quiz_bank：{len(questions)} 题 · {len(chapters)} 章（诗印 {''.join(sorted(seals))}） | 难度分布 "
        f"{dict(sorted(diff_count.items()))} | 每人上限 {MAX_PER_POET} | "
        f"防泄底/三级提示/A-B 考据/导读标注/章节划分 全部通过"
    )


if __name__ == "__main__":
    main()
