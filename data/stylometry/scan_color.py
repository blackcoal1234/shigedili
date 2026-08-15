"""色彩词扫描：读语料快照 → 输出 color_stats.json（每位诗人的"人生调色盘"）。

用法（可独立复跑，语料更新后重跑即刷新统计）：
    python data/stylometry/scan_color.py

并发安全：poems.json 可能正被其他工作流写入。本脚本每次先把 poems.json
复制成快照 poems_snapshot_color.json 再解析；解析失败等 5 秒重新复制重试，
最多 MAX_RETRY 次。

匹配算法：先把 EXCLUDE_WORDS（高频歧义词，见 color_dict docstring）用占位符
遮蔽，再按"长词优先"做非重叠最长匹配（如"金黄"优先于"金"/"黄"，
"皎洁"优先于"皎"），已匹配片段即被占位符替换，避免重复计数。

输出结构（schema_version=1）：
  per_poet: 覆盖语料内全部诗人；除通用字段外含维度特有字段
    color_families  各色系占比（8 系全量，含 0）
    palette         按频次加权的前 8 个色值（可直接当 UI 配色）
    bright_dark_ratio  (亮+1)/(暗+1) 拉普拉斯平滑比值，>1 偏亮 <1 偏暗
    bright_mid_dark    [亮,中,暗] 命中数
  per_poem: 每首诗的色彩词命中明细
  headline: 全语料最有趣的一条发现（规则法自动生成）
"""

import json
import re
import shutil
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from color_dict import COLOR_DICT, EXCLUDE_WORDS, FAMILIES, lookup, words  # noqa: E402

POEMS_PATH = HERE.parent / "poems.json"          # <root>/data/poems.json
SNAPSHOT_PATH = HERE / "poems_snapshot_color.json"
OUT_PATH = HERE / "color_stats.json"

MAX_RETRY = 5
RETRY_WAIT_SEC = 5

CJK_RE = re.compile(r"[一-鿿]")
PLACEHOLDER = "□"  # □ 非汉字占位符，等长替换已匹配/已屏蔽片段

INFO = {row[0]: dict(family=row[1], hex=row[2], brightness=row[3]) for row in COLOR_DICT}
SCAN_WORDS = words()  # 长词优先


def load_snapshot() -> list[dict]:
    """复制 poems.json 为快照后解析；失败等 5 秒重新复制重试。"""
    last_err = None
    for attempt in range(1, MAX_RETRY + 1):
        try:
            shutil.copyfile(POEMS_PATH, SNAPSHOT_PATH)
            with open(SNAPSHOT_PATH, encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, list) or not data:
                raise ValueError(f"快照不是非空列表: {type(data)}")
            return data
        except (OSError, ValueError, json.JSONDecodeError) as e:
            last_err = e
            print(f"[warn] 第{attempt}次读取快照失败: {e}；{RETRY_WAIT_SEC}s 后重试")
            time.sleep(RETRY_WAIT_SEC)
    raise SystemExit(f"读取语料失败（重试{MAX_RETRY}次）: {last_err}")


def scan_body(body: str) -> Counter:
    """对一首诗正文做屏蔽 + 长词优先非重叠匹配，返回 词->次数。"""
    masked = body
    for ex in EXCLUDE_WORDS:
        if ex in masked:
            masked = masked.replace(ex, PLACEHOLDER * len(ex))
    hits = Counter()
    for w in SCAN_WORDS:
        n = masked.count(w)
        if n:
            hits[w] = n
            masked = masked.replace(w, PLACEHOLDER * len(w))
    return hits


def poet_summary(poems: list[dict], hit_list: list[Counter]) -> dict:
    hits_all = Counter()
    for h in hit_list:
        hits_all.update(h)
    total_hits = sum(hits_all.values())
    total_chars = sum(len(CJK_RE.findall(p.get("body", ""))) for p in poems)

    fam_count = Counter()
    bright = Counter()
    hex_count = Counter()
    for w, n in hits_all.items():
        info = INFO[w]
        fam_count[info["family"]] += n
        bright[info["brightness"]] += n
        hex_count[info["hex"]] += n

    color_families = {
        f: (round(fam_count[f] / total_hits, 4) if total_hits else 0.0)
        for f in FAMILIES
    }
    palette = [hx for hx, _ in sorted(hex_count.items(), key=lambda kv: (-kv[1], kv[0]))[:8]]
    b, m, d = bright["亮"], bright["中"], bright["暗"]
    return {
        "poem_count": len(poems),
        "hits_total": total_hits,
        "hits_per_100_chars": round(total_hits / total_chars * 100, 3) if total_chars else 0.0,
        "top_words": [[w, n] for w, n in sorted(hits_all.items(), key=lambda kv: (-kv[1], kv[0]))[:10]],
        "color_families": color_families,
        "palette": palette,
        "bright_dark_ratio": round((b + 1) / (d + 1), 3),
        "bright_mid_dark": [b, m, d],
    }


COLD_FAMILIES = ("青绿", "蓝", "紫", "黑")
WARM_FAMILIES = ("红", "黄", "金银")


def make_headline(per_poet: dict) -> str:
    """规则法生成一条最有趣的发现：找相对全语料均值偏离最大的诗人色盘。"""
    # 全语料各系占比（按 hits 加权）
    weighted = Counter()
    grand = 0
    for st in per_poet.values():
        for f in FAMILIES:
            weighted[f] += st["color_families"][f] * st["hits_total"]
        grand += st["hits_total"]
    corpus_share = {f: (weighted[f] / grand if grand else 0.0) for f in FAMILIES}
    corpus_cold = sum(corpus_share[f] for f in COLD_FAMILIES)
    corpus_warm = sum(corpus_share[f] for f in WARM_FAMILIES)
    corpus_white = corpus_share["白"]

    candidates = []  # (偏离倍数, 文案)
    for poet, st in per_poet.items():
        if st["poem_count"] < 10 or st["hits_total"] < 40:
            continue
        cold = sum(st["color_families"][f] for f in COLD_FAMILIES)
        warm = sum(st["color_families"][f] for f in WARM_FAMILIES)
        white = st["color_families"]["白"]
        if corpus_cold:
            candidates.append((cold / corpus_cold,
                f"{poet}的调色盘明显偏冷：青绿/蓝/紫/黑合计占其色彩词的{cold:.0%}"
                f"（全语料均值{corpus_cold:.0%}的{cold / corpus_cold:.1f}倍）"))
        if corpus_warm:
            candidates.append((warm / corpus_warm,
                f"{poet}的调色盘明显偏暖：红/黄/金银合计占其色彩词的{warm:.0%}"
                f"（全语料均值{corpus_warm:.0%}的{warm / corpus_warm:.1f}倍）"))
        if corpus_white:
            candidates.append((white / corpus_white,
                f"{poet}是语料里最'白'的诗人：白系独占其色彩词的{white:.0%}"
                f"（全语料均值{corpus_white:.0%}的{white / corpus_white:.1f}倍）"))
    if not candidates:
        return "语料中色彩词命中过少，暂无显著发现"
    candidates.sort(key=lambda t: (-t[0], t[1]))
    return candidates[0][1]


def main() -> None:
    data = load_snapshot()
    by_poet = defaultdict(list)
    per_poem = []
    poet_hits = defaultdict(list)
    for p in data:
        poet = p.get("poet") or p.get("author") or "未知"
        hits = scan_body(p.get("body", ""))
        by_poet[poet].append(p)
        poet_hits[poet].append(hits)
        per_poem.append({
            "title": p.get("title", ""),
            "poet": poet,
            "body_hash": p.get("body_hash", ""),
            "hits": [[w, n] for w, n in sorted(hits.items(), key=lambda kv: (-kv[1], kv[0]))],
        })

    per_poet = {poet: poet_summary(by_poet[poet], poet_hits[poet])
                for poet in sorted(by_poet)}

    out = {
        "schema_version": 1,
        "dict_size": len(COLOR_DICT),
        "generated_from_poems": len(data),
        "headline": make_headline(per_poet),
        "per_poet": per_poet,
        "per_poem": per_poem,
    }
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"诗人数: {len(per_poet)}  诗歌数: {len(data)}  词典: {len(COLOR_DICT)} 词条")
    print(f"headline: {out['headline']}")
    print(f"已写出: {OUT_PATH}")


if __name__ == "__main__":
    main()
