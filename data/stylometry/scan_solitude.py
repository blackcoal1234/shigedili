"""扫描语料：人称与孤独感维度（stylometry）。

流程：
1. 把 data/poems.json 复制为本目录快照 poems_snapshot_solitude.json 再解析
   （另一工作流可能正在写 poems.json；解析失败等 5 秒重新复制重试）。
2. 用 solitude_dict.py 按"最长优先、不重叠"贪心匹配全部诗歌正文。
3. 输出 solitude_stats.json（统一结构 schema_version=1）。

可独立复跑：语料更新后重新运行本脚本即刷新统计。

per_poet 维度特有字段：
- solitude_per_100_chars      孤独类命中数 / 正文汉字数 * 100
- solitude_weighted_per_100_chars  按词条强度加权的孤独密度
- self_other_ratio            自称命中 / 他称命中（他称为 0 时为 null）；
                              比值高 = 独白型，低 = 对话型
- top_solitude_lines          孤独加权密度最高的诗句前 5（句内加权分/句长）

用法：python scan_solitude.py
"""

import hashlib
import json
import os
import re
import shutil
import sys
import time
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
POEMS_PATH = os.path.join(ROOT, "data", "poems.json")
SNAPSHOT_PATH = os.path.join(HERE, "poems_snapshot_solitude.json")
OUT_PATH = os.path.join(HERE, "solitude_stats.json")

sys.path.insert(0, HERE)
import solitude_dict  # noqa: E402

CORE_POETS = ["李白", "杜甫", "白居易", "苏轼", "陆游", "李清照"]
CJK_RE = re.compile(r"[一-鿿]")
LINE_SPLIT_RE = re.compile(r"[，。！？；：、,.!?;:\s]+")


def load_poems(max_attempts: int = 6) -> list[dict]:
    """复制快照后解析；失败等 5 秒重新复制重试（并发写保护）。"""
    last_err = None
    for attempt in range(1, max_attempts + 1):
        try:
            shutil.copyfile(POEMS_PATH, SNAPSHOT_PATH)
            with open(SNAPSHOT_PATH, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list) and data:
                return data
            raise ValueError("快照不是非空列表")
        except (OSError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as e:
            last_err = e
            print(f"[scan_solitude] 第 {attempt} 次读取快照失败: {e}；5 秒后重试")
            time.sleep(5)
    raise RuntimeError(f"连续 {max_attempts} 次无法解析 poems.json: {last_err}")


def build_matcher():
    entries = {w: (c, s) for w, c, s in solitude_dict.SOLITUDE_DICT}
    max_len = max(len(w) for w in entries)
    return entries, max_len


def match_text(text: str, entries: dict, max_len: int) -> Counter:
    """最长优先、不重叠的贪心匹配，返回 词→次数。"""
    hits: Counter = Counter()
    i, n = 0, len(text)
    while i < n:
        matched = False
        for length in range(min(max_len, n - i), 0, -1):
            w = text[i : i + length]
            if w in entries:
                hits[w] += 1
                i += length
                matched = True
                break
        if not matched:
            i += 1
    return hits


def cjk_count(text: str) -> int:
    return len(CJK_RE.findall(text))


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    poems = load_poems()
    entries, max_len = build_matcher()

    per_poem_out = []
    agg: dict[str, dict] = {}

    for poem in poems:
        poet = poem.get("poet") or poem.get("author") or "佚名"
        title = poem.get("title", "")
        body = poem.get("body", "") or ""
        body_hash = poem.get("body_hash") or hashlib.sha256(
            body.encode("utf-8")
        ).hexdigest()

        hits = match_text(body, entries, max_len)
        chars = cjk_count(body)

        st = agg.setdefault(
            poet,
            {
                "poem_count": 0,
                "chars_total": 0,
                "word_counter": Counter(),
                "cat_counter": Counter(),
                "solitude_weighted": 0.0,
                "lines": [],
            },
        )
        st["poem_count"] += 1
        st["chars_total"] += chars
        st["word_counter"].update(hits)
        for w, n in hits.items():
            cat, inten = entries[w]
            st["cat_counter"][cat] += n
            if cat == "孤独":
                st["solitude_weighted"] += inten * n

        # 句级孤独密度（供 top_solitude_lines）
        for line in LINE_SPLIT_RE.split(body):
            if len(line) < 4:
                continue
            line_hits = match_text(line, entries, max_len)
            score = sum(
                entries[w][1] * n
                for w, n in line_hits.items()
                if entries[w][0] == "孤独"
            )
            if score > 0:
                density = score / len(line)
                sol_words = [w for w in line_hits if entries[w][0] == "孤独"]
                st["lines"].append(
                    {
                        "line": line,
                        "title": title,
                        "density": round(density, 4),
                        "solitude_words": sol_words,
                    }
                )

        per_poem_out.append(
            {
                "title": title,
                "poet": poet,
                "body_hash": body_hash,
                "hits": sorted(hits.items(), key=lambda kv: (-kv[1], kv[0])),
            }
        )

    per_poet_out = {}
    for poet, st in agg.items():
        chars = st["chars_total"]
        hits_total = sum(st["word_counter"].values())
        sol = st["cat_counter"]["孤独"]
        self_n = st["cat_counter"]["自称"]
        other_n = st["cat_counter"]["他称"]
        top_lines = sorted(
            st["lines"], key=lambda d: (-d["density"], d["line"])
        )[:5]
        per_poet_out[poet] = {
            "poem_count": st["poem_count"],
            "chars_total": chars,
            "hits_total": hits_total,
            "hits_per_100_chars": round(hits_total / chars * 100, 3) if chars else 0.0,
            "top_words": st["word_counter"].most_common(10),
            "category_counts": {
                "孤独": sol,
                "自称": self_n,
                "他称": other_n,
            },
            "solitude_per_100_chars": round(sol / chars * 100, 3) if chars else 0.0,
            "solitude_weighted_per_100_chars": (
                round(st["solitude_weighted"] / chars * 100, 3) if chars else 0.0
            ),
            "self_other_ratio": (
                round(self_n / other_n, 3) if other_n else None
            ),
            "top_solitude_lines": top_lines,
        }

    out = {
        "schema_version": 1,
        "dict_size": len(solitude_dict.SOLITUDE_DICT),
        "generated_from_poems": len(poems),
        "dimension": "人称与孤独感",
        "per_poet": per_poet_out,
        "per_poem": per_poem_out,
    }
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

    print(f"[scan_solitude] 已写出 {OUT_PATH}")
    print(f"  语料 {len(poems)} 首 / 诗人 {len(per_poet_out)} 位 / 词典 {out['dict_size']} 条")
    print("  六核心诗人孤独密度（孤独命中/百字）：")
    ranked = sorted(
        (p for p in CORE_POETS if p in per_poet_out),
        key=lambda p: -per_poet_out[p]["solitude_per_100_chars"],
    )
    for p in ranked:
        s = per_poet_out[p]
        ratio = s["self_other_ratio"]
        print(
            f"    {p}: solitude/100字={s['solitude_per_100_chars']:.3f}  "
            f"自/他比={ratio if ratio is not None else 'inf'}  "
            f"(自称{s['category_counts']['自称']} 他称{s['category_counts']['他称']})"
        )


if __name__ == "__main__":
    main()
