# -*- coding: utf-8 -*-
"""加行卷题库：地名飞花令 / 意象归乡 / 古今地名连线。

三种题型全部由现有数据确定性生成（无随机源，重建逐字节一致）：

  飞花令（12 题）：给一个令字，四句中挑出真正含它的诗句；干扰句取自语料
    且经校验不含令字。证据卡给出真句出处与「含令字诗句 n 首」语料计数。
  意象归乡（8 题）：直接复用 R2 意象×地域矩阵——
    A 型（区域归乡）：给一组过表征意象，问最可能落在哪个分区；
    B 型（意象归属）：问某分区最过表征的意象是哪个。
    证据卡给出各选项区域对这些词的 lift，题即论据。
  古今地名连线（4 题）：每轮 4 对古名→今名，取自 place_dict 别名词表，
    附词典备注（如「唐都」）。当场即时判对错。

产出：output/assets/competition/side_quest_bank.json
计分：每题基分 800；飞花令/意象题各有一级提示 ×0.5；连线无提示、每对即时反馈。
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "data"))

from data.place_dict import PLACE_DICT  # noqa: E402

POEMS_PATH = ROOT / "data" / "poems.json"
MATRIX_JSON = ROOT / "output" / "assets" / "competition" / "imagery_region_matrix.json"
OUT_JSON = ROOT / "output" / "assets" / "competition" / "side_quest_bank.json"

BASE_POINTS = 800
LING_CHARS = ["月", "花", "风", "春", "江", "山", "水", "夜", "秋", "雪", "酒", "舟"]
LINE_MIN, LINE_MAX = 5, 16
SENT_SPLIT = re.compile(r"(?<=[。！？；，])|\n")
FAMOUS = {"李白", "杜甫", "白居易", "苏轼", "陆游", "李清照"}


def stable(*parts: str) -> int:
    """跨进程稳定的确定性选择种子（Python 内建 hash 对字符串随机化，不可用）。"""
    return int(hashlib.md5("·".join(parts).encode("utf-8")).hexdigest(), 16)


def clean_lines(body: str) -> list[str]:
    out = []
    for raw in SENT_SPLIT.split(body or ""):
        seg = raw.strip().rstrip("，。；！？、")
        if LINE_MIN <= len(seg) <= LINE_MAX and re.fullmatch(r"[\u3400-\u9fff]+", seg):
            out.append(seg)
    return out


def build_feihualing(poems: list[dict]) -> list[dict]:
    """每令字一题：真句优先取名家，干扰句不含令字且长度相近。"""
    # 全语料句库（一次遍历）：句 + 诗人 + 题目
    pool: list[tuple[str, str, str]] = []
    for pm in poems:
        body = pm.get("body") or ""
        if not isinstance(body, str):
            continue
        poet = pm.get("poet") or pm.get("author") or "佚名"
        title = pm.get("title") or ""
        for line in clean_lines(body):
            pool.append((line, poet, title))
    pool.sort()

    questions = []
    for qi, ch in enumerate(LING_CHARS):
        hits = [t for t in pool if ch in t[0]]
        hits_famous = [t for t in hits if t[1] in FAMOUS] or hits
        if not hits_famous:
            continue
        real = hits_famous[stable("ling-real", ch) % len(hits_famous)]
        # 干扰句：不含令字、长度与真句差 <=3、来自不同诗
        near = [
            t for t in pool
            if ch not in t[0] and abs(len(t[0]) - len(real[0])) <= 3
            and (t[1], t[2]) != (real[1], real[2])
        ]
        decoys = []
        step = max(1, len(near) // 7 or 1)
        seed = stable("ling-decoy", ch)
        idx = seed % len(near) if near else 0
        while len(decoys) < 3 and near:
            cand = near[idx % len(near)]
            idx += step
            if all(cand[0] != d[0] for d in decoys):
                decoys.append(cand)
        if len(decoys) < 3:
            continue
        options = [real] + decoys
        order = sorted(range(4), key=lambda i: stable("ling-order", ch, str(i)))
        options = [options[i] for i in order]
        correct = next(i for i, o in enumerate(options) if o[0] == real[0])
        questions.append(
            {
                "type": "feihualing",
                "id": f"F{qi+1:02d}",
                "char": ch,
                "prompt": f"飞花令·「{ch}」——以下哪一句真的含有「{ch}」字？",
                "options": [
                    {"line": o[0], "poet": o[1], "title": o[2]} for o in options
                ],
                "correct": correct,
                "hint": {
                    "cost": 0.5,
                    "text": f"真句出自{real[1]}笔下——四句细读，其余三句均不含「{ch}」字。",
                },
                "evidence": {
                    "real": {"line": real[0], "poet": real[1], "title": real[2]},
                    "corpus_hits": len(hits),
                },
                "points": BASE_POINTS,
            }
        )
    return questions


def build_imagery_home() -> list[dict]:
    """意象归乡：A 型猜区域 / B 型猜意象，选项与证据全部来自 R2 矩阵。"""
    data = json.loads(MATRIX_JSON.read_text(encoding="utf-8"))
    regions = [r for r in data["regions"] if len(r["top_words"]) >= 3]
    assert len(regions) >= 4, "可用分区不足 4 个"
    by_id = {r["id"]: r for r in data["regions"]}
    questions = []

    # A 型：前 4 个有效分区各出一题
    for qi, r in enumerate(regions[:4]):
        clue_words = [t["word"] for t in r["top_words"][:3]]
        decoy_regions = [x for x in regions if x["id"] != r["id"]][:3]
        # 去歧义：线索词不得是干扰区的第 1 名
        decoy_regions = [
            d for d in decoy_regions
            if not any(w == d["top_words"][0]["word"] for w in clue_words)
        ][:3]
        if len(decoy_regions) < 3:
            continue
        options = [r] + decoy_regions
        order = sorted(range(4), key=lambda i: stable("img-a-order", r["id"], str(i)))
        options = [options[i] for i in order]
        correct = next(i for i, o in enumerate(options) if o["id"] == r["id"])
        lift_rows = []
        for o in options:
            cells = []
            for t in o["top_words"]:
                if t["word"] in clue_words:
                    cells.append(f"「{t['word']}」{t['lift']}×")
            lift_rows.append({"region": o["name"], "hits": "、".join(cells) or "（无过表征）"})
        questions.append(
            {
                "type": "imagery_home",
                "id": f"I{qi+1:02d}",
                "prompt": f"意象归乡——「{'、'.join(clue_words)}」这一组意象，最可能落在哪个分区？",
                "options": [{"region": o["name"]} for o in options],
                "correct": correct,
                "clue_words": clue_words,
                "hint": {
                    "cost": 0.5,
                    "text": f"其中「{clue_words[0]}」在正确分区的 lift 为 "
                            f"{next(t['lift'] for t in r['top_words'] if t['word'] == clue_words[0])}×"
                            f"（含它的诗落在此区的倍率）。",
                },
                "evidence": {
                    "kind": "lift_table",
                    "rows": lift_rows,
                    "source": "41_意象地理.html（R2 意象×地域矩阵）",
                },
                "points": BASE_POINTS,
            }
        )

    # B 型：再取 4 个分区（轮转），问「最过表征的意象」
    for qi, r in enumerate(regions[:4]):
        correct_word = r["top_words"][0]
        all_top = {t["word"] for x in regions for t in x["top_words"][:1]}
        decoy_words = sorted(
            w for w in all_top
            if w != correct_word["word"]
            and w not in {t["word"] for t in r["top_words"]}
        )
        picks = [
            decoy_words[(stable("img-b", r["id"], str(k)) + k * 3) % len(decoy_words)]
            for k in range(3)
        ]
        if len(set(picks)) < 3:
            continue
        options = [correct_word["word"]] + picks
        order = sorted(range(4), key=lambda i: stable("img-b-order", r["id"], str(i)))
        options = [options[i] for i in order]
        correct = options.index(correct_word["word"])
        questions.append(
            {
                "type": "imagery_home",
                "id": f"I{qi+5:02d}",
                "prompt": f"意象归属——在「{r['name']}」分区，最过表征（lift 最高）的意象是？",
                "options": [{"word": o} for o in options],
                "correct": correct,
                "region": r["name"],
                "hint": {
                    "cost": 0.5,
                    "text": f"正确答案的 lift 为 {correct_word['lift']}×，样本 {correct_word['n_wr']}/{correct_word['n_w']} 首。",
                },
                "evidence": {
                    "kind": "top_words",
                    "region": r["name"],
                    "words": [
                        {"word": t["word"], "lift": t["lift"], "n_wr": t["n_wr"], "n_w": t["n_w"]}
                        for t in r["top_words"][:5]
                    ],
                    "source": "41_意象地理.html（R2 意象×地域矩阵）",
                },
                "points": BASE_POINTS,
            }
        )
        if len([q for q in questions if q["type"] == "imagery_home"]) >= 8:
            break
    return questions


def build_link_rounds() -> list[dict]:
    """古今地名连线：4 轮，每轮 4 对；别名互不为子串、今地互不相同、优先带备注。"""
    candidates = [
        (alias, modern, province, note)
        for alias, modern, province, _lo, _la, note in PLACE_DICT
        if len(alias) >= 2 and note
    ]
    # 按稳定序轮转取轮次组
    candidates.sort(key=lambda r: (r[0], r[1]))
    rounds = []
    for ri in range(4):
        start = stable("link-round", str(ri)) % max(1, len(candidates) - 16)
        picked: list[tuple[str, str, str, str]] = []
        seen_modern: set = set()
        for row in candidates[start:] + candidates[:start]:
            alias, modern, _prov, _note = row
            if modern in seen_modern:
                continue
            if any(alias in p[0] or p[0] in alias for p in picked):
                continue
            picked.append(row)
            seen_modern.add(modern)
            if len(picked) == 4:
                break
        if len(picked) < 4:
            continue
        order = sorted(range(4), key=lambda i: stable("link-order", str(ri), str(i)))
        left = [picked[i] for i in order]
        right_order = sorted(range(4), key=lambda i: stable("link-right", str(ri), str(i)))
        right = [picked[i] for i in right_order]
        rounds.append(
            {
                "type": "link",
                "id": f"L{ri+1:02d}",
                "prompt": "古今地名连线——点左侧古名，再点右侧今地，四对全中即过。",
                "pairs": [
                    {
                        "alias": a,
                        "modern": m,
                        "province": p,
                        "note": n,
                    }
                    for a, m, p, n in picked
                ],
                "left_order": [p[0] for p in left],
                "right_order": [p[0] for p in right],
                "points": BASE_POINTS,
            }
        )
    return rounds


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    poems = json.loads(POEMS_PATH.read_text(encoding="utf-8"))
    if not MATRIX_JSON.exists():
        raise SystemExit("[failed] 缺少 R2 矩阵，先运行 tools/build_imagery_region_matrix.py")

    feihua = build_feihualing(poems)
    imagery_q = build_imagery_home()
    links = build_link_rounds()

    assert len(feihua) >= 10, f"飞花令题不足：{len(feihua)}"
    assert len(imagery_q) >= 6, f"意象归乡题不足：{len(imagery_q)}"
    assert len(links) >= 3, f"连线轮不足：{len(links)}"

    # 交错编队：飞花令与意象交替，连线每 6 题插一轮；循环条件保证全部入卷
    mixed = []
    fi, ii = 0, 0
    while fi < len(feihua) or ii < len(imagery_q):
        if len(mixed) % 6 == 5 and links:
            mixed.append(links.pop(0))
        elif fi < len(feihua):
            mixed.append(feihua[fi]); fi += 1
        elif ii < len(imagery_q):
            mixed.append(imagery_q[ii]); ii += 1
    mixed.extend(links)

    meta = {
        "n_questions": len(mixed),
        "n_feihualing": len(feihua),
        "n_imagery": len(imagery_q),
        "n_link": len([q for q in mixed if q["type"] == "link"]),
        "base_points": BASE_POINTS,
        "policy": (
            "飞花令干扰句经校验不含令字；意象归乡选项与证据直接来自 R2 意象×地域矩阵"
            "（题即论据）；连线取自古地名词典并附备注。全卷确定性生成，重建逐字节一致。"
        ),
        "generated_by": "tools/build_side_quest_bank.py",
    }
    data = {"meta": meta, "questions": mixed}
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"), allow_nan=False)

    print("OK  ->", OUT_JSON, f"({OUT_JSON.stat().st_size} bytes)")
    print(f"飞花令 {len(feihua)} | 意象归乡 {len(imagery_q)} | 连线 {meta['n_link']} | 合计 {len(mixed)}")
    for q in mixed[:6]:
        print(f"  {q['id']} {q['type']:<12} {q['prompt'][:38]}")


if __name__ == "__main__":
    main()
