# -*- coding: utf-8 -*-
"""side_quest_bank.json 质量门：干扰句不含令字、连线唯一解、证据完备。"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PATH = ROOT / "output" / "assets" / "competition" / "side_quest_bank.json"

MIN_FEIHUA, MIN_IMAGERY, MIN_LINK = 10, 6, 3


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    if not PATH.exists():
        raise SystemExit(f"[failed] 缺少 {PATH}，先运行 tools/build_side_quest_bank.py")

    # 确定性：重建一次须逐字节一致
    digest_before = hashlib.md5(PATH.read_bytes()).hexdigest()
    subprocess.run(
        [sys.executable, "tools/build_side_quest_bank.py"],
        cwd=ROOT, check=True, capture_output=True,
    )
    digest_after = hashlib.md5(PATH.read_bytes()).hexdigest()
    assert digest_before == digest_after, "题库重建不一致（存在非确定性来源）"

    data = json.loads(PATH.read_text(encoding="utf-8"))
    meta, qs = data["meta"], data["questions"]
    for field in ("n_questions", "base_points", "policy"):
        assert meta.get(field), f"meta 缺少 {field}"

    ids = set()
    n_type = {"feihualing": 0, "imagery_home": 0, "link": 0}
    for q in qs:
        qid = q["id"]
        assert qid and qid not in ids, f"id 重复：{qid}"
        ids.add(qid)
        t = q["type"]
        assert t in n_type, f"{qid} 未知题型 {t}"
        n_type[t] += 1
        assert q.get("prompt"), f"{qid} 缺题干"

        if t == "feihualing":
            ch = q["char"]
            assert ch in q["prompt"], f"{qid} 题干缺令字"
            opts = q["options"]
            assert len(opts) == 4, f"{qid} 选项数 {len(opts)} != 4"
            lines = [o["line"] for o in opts]
            assert len(set(lines)) == 4, f"{qid} 选项重复"
            assert ch in lines[q["correct"]], f"{qid} 正确项不含令字"
            for i, o in enumerate(opts):
                if i != q["correct"]:
                    assert ch not in o["line"], f"{qid} 干扰句含令字：{o['line']}"
            assert q["evidence"]["real"]["poet"] and q["evidence"]["corpus_hits"] > 0, f"{qid} 证据不全"

        elif t == "imagery_home":
            opts = q["options"]
            assert len(opts) == 4 and 0 <= q["correct"] < 4, f"{qid} 选项/答案非法"
            assert "41_意象地理.html" in q["evidence"].get("source", ""), f"{qid} 证据缺 R2 来源"
            assert q["hint"]["cost"] == 0.5 and q["hint"]["text"], f"{qid} 提示异常"

        elif t == "link":
            pairs = q["pairs"]
            assert len(pairs) == 4, f"{qid} 连线对数 {len(pairs)} != 4"
            moderns = [p["modern"] for p in pairs]
            assert len(set(moderns)) == 4, f"{qid} 今地重复，非唯一解"
            aliases = [p["alias"] for p in pairs]
            assert len(set(aliases)) == 4, f"{qid} 古名重复"
            for i, a in enumerate(aliases):
                for j, b in enumerate(aliases):
                    if i != j:
                        assert a not in b, f"{qid} 古名互为子串：{a}/{b}"
            assert sorted(q["left_order"]) == sorted(aliases), f"{qid} 左列非排列"
            assert sorted(q["right_order"]) == sorted(aliases), f"{qid} 右列非排列"
            for p in pairs:
                assert p["note"], f"{qid} 连线缺词典备注：{p['alias']}"

    assert n_type["feihualing"] >= MIN_FEIHUA, f"飞花令 {n_type['feihualing']} < {MIN_FEIHUA}"
    assert n_type["imagery_home"] >= MIN_IMAGERY, f"意象归乡 {n_type['imagery_home']} < {MIN_IMAGERY}"
    assert n_type["link"] >= MIN_LINK, f"连线 {n_type['link']} < {MIN_LINK}"
    assert meta["n_questions"] == len(qs), "meta 题数不一致"

    print(
        f"[ok] side_quest_bank：{len(qs)} 题（飞花令 {n_type['feihualing']} / 意象归乡 "
        f"{n_type['imagery_home']} / 连线 {n_type['link']}）| 干扰句校验/唯一解/证据/确定性重建 全部通过"
    )


if __name__ == "__main__":
    main()
