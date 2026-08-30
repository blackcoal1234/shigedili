"""数字与夸张扫描：读取分析语料，输出 number_stats.json（"李白夸张系数"维度）。

用法：
    python data/stylometry/scan_number.py

流程与口径：
  1. 通过统一 loader 严格读取全作品分析语料；缺失或 manifest 失配即失败。
  2. 匹配：用 number_dict.NUMBER_DICT，按词长从长到短贪心匹配，每个字符
     至多归入一个词条（"三千丈"优先于"三千"/"千"）。
  3. 计数口径：
     - hits / top_words 只统计 COUNTED_KINDS（cardinal/measure/time/vague）；
       weak（一片/一声…）与 ordinal（三月/五更…）单独计入
       weak_hits / ordinal_hits，不入 hits，也不入任何数量级统计。
     - 字数分母 = 正文中 CJK 统一表意文字（一-鿿）个数，
       标点、换行不计。
     - avg_magnitude = Σ(magnitude×次数)/Σ次数，仅对 counted hits。
     - hyperbole_per_100_chars = is_hyperbole 词条命中次数 / 字数 × 100。
       夸张判定从严（见 number_dict docstring），该密度是保守下界。
  4. per_poet 覆盖语料中全部诗人；max_expressions 为该诗人数量级最高的
     命中所在原句摘录前 5 条（按数量级降序，同句去重）。
  5. headline 由本次数据计算得出：诗人间夸张密度对比的最强发现。

输出 JSON 结构见项目统一约定（schema_version=1）。
"""

import re
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[1]
OUT_PATH = SCRIPT_DIR / "number_stats.json"

sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(PROJECT_ROOT / "tools"))
import number_dict  # noqa: E402
from famous_poet_corpus import atomic_dump_json, load_analysis_poems  # noqa: E402

CJK_RE = re.compile(r"[一-鿿]")
SENT_SPLIT_RE = re.compile(r"[。！？；\n]+")


def match_sentence(sent: str, table: dict, max_len: int):
    """贪心从长到短匹配一句，产出词条 dict 序列。"""
    out = []
    i, n = 0, len(sent)
    while i < n:
        hit = None
        for L in range(min(max_len, n - i), 0, -1):
            entry = table.get(sent[i:i + L])
            if entry is not None:
                hit = entry
                break
        if hit is not None:
            out.append(hit)
            i += len(hit["word"])
        else:
            i += 1
    return out


def scan():
    poems, corpus_source = load_analysis_poems(fallback=False)
    if corpus_source != "analysis_full":
        forbidden_fallback = "data/poems.json"
        raise RuntimeError(
            f"状态统计必须使用全作品语料，实际来源：{corpus_source}；"
            f"禁止回退 {forbidden_fallback}"
        )
    corpus_path = (
        "data/analysis/famous_poets_full.jsonl.gz"
        if corpus_source == "analysis_full"
        else "data/poems.json"
    )
    table = number_dict.as_table()
    max_len = max(len(w) for w in table)
    counted_kinds = number_dict.COUNTED_KINDS

    per_poem = []
    agg = defaultdict(lambda: {
        "poem_count": 0, "chars_total": 0, "hits_total": 0,
        "hyperbole_hits": 0, "weak_hits": 0, "ordinal_hits": 0,
        "mag_sum": 0.0, "mag_n": 0,
        "word_counter": Counter(),
        "expr": [],  # (magnitude, word, line, title)
    })

    for poem in poems:
        poet = poem.get("poet") or poem.get("author") or "佚名"
        title = poem.get("title", "")
        body = poem.get("body", "") or ""
        body_hash = poem.get("body_hash", "")
        chars = len(CJK_RE.findall(body))

        counter = Counter()
        weak = ordinal = hyper = 0
        mag_sum, mag_n = 0.0, 0
        exprs = []
        for sent in SENT_SPLIT_RE.split(body):
            sent = sent.strip()
            if not sent:
                continue
            for entry in match_sentence(sent, table, max_len):
                kind = entry["kind"]
                if kind == "weak":
                    weak += 1
                elif kind == "ordinal":
                    ordinal += 1
                else:  # counted
                    counter[entry["word"]] += 1
                    mag_sum += entry["magnitude"]
                    mag_n += 1
                    if entry["is_hyperbole"]:
                        hyper += 1
                    exprs.append((entry["magnitude"], entry["word"], sent))

        per_poem.append({
            "title": title,
            "poet": poet,
            "work_id": poem.get("work_id"),
            "canonical_gushiwen_id": poem.get("canonical_gushiwen_id"),
            "body_hash": body_hash,
            "hits": sorted(counter.items(), key=lambda kv: (-kv[1], kv[0])),
        })

        a = agg[poet]
        a["poem_count"] += 1
        a["chars_total"] += chars
        a["hits_total"] += sum(counter.values())
        a["hyperbole_hits"] += hyper
        a["weak_hits"] += weak
        a["ordinal_hits"] += ordinal
        a["mag_sum"] += mag_sum
        a["mag_n"] += mag_n
        a["word_counter"].update(counter)
        for mag, word, sent in exprs:
            a["expr"].append((mag, word, sent, title))

    per_poet = {}
    for poet, a in agg.items():
        chars = a["chars_total"]
        seen_lines = set()
        max_expr = []
        for mag, word, sent, title in sorted(
                a["expr"], key=lambda t: (-t[0], t[1])):
            if sent in seen_lines:
                continue
            seen_lines.add(sent)
            max_expr.append({"word": word, "magnitude": mag,
                             "line": sent, "title": title})
            if len(max_expr) >= 5:
                break
        per_poet[poet] = {
            "poem_count": a["poem_count"],
            "chars_total": chars,
            "hits_total": a["hits_total"],
            "hits_per_100_chars": round(a["hits_total"] / chars * 100, 3) if chars else 0.0,
            "top_words": [list(kv) for kv in a["word_counter"].most_common(10)],
            "avg_magnitude": round(a["mag_sum"] / a["mag_n"], 3) if a["mag_n"] else None,
            "hyperbole_hits": a["hyperbole_hits"],
            "hyperbole_per_100_chars": round(a["hyperbole_hits"] / chars * 100, 3) if chars else 0.0,
            "weak_hits": a["weak_hits"],
            "ordinal_hits": a["ordinal_hits"],
            "max_expressions": max_expr,
        }

    headline = build_headline(per_poet)

    stats = {
        "schema_version": 1,
        "corpus_source": corpus_source,
        "corpus_path": corpus_path,
        "dict_size": len(number_dict.NUMBER_DICT),
        "generated_from_poems": len(poems),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "dimension": "number_hyperbole",
        "headline": headline,
        "per_poet": per_poet,
        "per_poem": per_poem,
    }
    atomic_dump_json(OUT_PATH, stats)
    print(f"[scan_number] 完成: {len(poems)} 首 / {len(per_poet)} 位诗人 "
          f"-> {OUT_PATH}")
    print(f"[scan_number] headline: {headline}")
    return stats


MIN_CHARS_FOR_RANK = 300  # 样本充分线：正文合计不足300字的诗人不入主榜，避免小样本失真


def build_headline(per_poet: dict) -> str:
    """基于本次数据计算诗人间夸张密度对比的最强发现（不预设结论）。

    主榜只比较 chars_total >= MIN_CHARS_FOR_RANK 的诗人；被排除的小样本
    诗人若密度高于主榜第1名，会在句末如实附注。
    """
    if not per_poet:
        return "语料为空，无可比较。"
    qualified = {p: v for p, v in per_poet.items()
                 if v["chars_total"] >= MIN_CHARS_FOR_RANK}
    small = {p: v for p, v in per_poet.items() if p not in qualified}
    if not qualified:
        qualified, small = dict(per_poet), {}

    rank = sorted(qualified.items(),
                  key=lambda kv: -kv[1]["hyperbole_per_100_chars"])
    (top_name, top) = rank[0]
    (snd_name, snd) = rank[1] if len(rank) > 1 else rank[0]
    med = statistics.median(v["hyperbole_per_100_chars"] for _, v in rank)
    n = len(rank)

    mag_rank = sorted(
        ((p, v["avg_magnitude"]) for p, v in qualified.items()
         if v["avg_magnitude"] is not None),
        key=lambda t: -t[1])
    mag_pos = {p: i + 1 for i, (p, _) in enumerate(mag_rank)}

    parts = [
        f"{len(per_poet)}位诗人中样本充分（≥{MIN_CHARS_FOR_RANK}字）的"
        f"{n}位里，夸张密度（每百字夸张数词）第1名为{top_name}："
        f"{top['hyperbole_per_100_chars']:.2f}",
    ]
    if snd_name != top_name and snd["hyperbole_per_100_chars"] > 0:
        parts.append(
            f"是第2名{snd_name}（{snd['hyperbole_per_100_chars']:.2f}）的"
            f"{top['hyperbole_per_100_chars'] / snd['hyperbole_per_100_chars']:.2f}倍")
    if med > 0:
        parts.append(
            f"全体中位数（{med:.2f}）的"
            f"{top['hyperbole_per_100_chars'] / med:.1f}倍")
    head = "，".join(parts) + "。"

    li = per_poet.get("李白")
    if li is not None and "李白" in qualified:
        li_pos = next(i + 1 for i, (p, _) in enumerate(rank) if p == "李白")
        if top_name == "李白":
            head += (f"李白平均数量级 {li['avg_magnitude']:.2f} 亦居"
                     f"{len(mag_rank)}人中第{mag_pos.get('李白', '?')}名，"
                     f"两项指标共同支撑\"李白夸张系数\"最高的判断。")
        else:
            head += (f"李白夸张密度 {li['hyperbole_per_100_chars']:.2f}，"
                     f"排第{li_pos}名；平均数量级排第{mag_pos.get('李白', '?')}名。")

    outliers = [(p, v) for p, v in small.items()
                if v["hyperbole_per_100_chars"] > top["hyperbole_per_100_chars"]]
    if outliers:
        notes = "、".join(
            f"{p}（{v['hyperbole_per_100_chars']:.2f}，仅{v['poem_count']}首"
            f"/{v['chars_total']}字）"
            for p, v in sorted(outliers,
                               key=lambda t: -t[1]["hyperbole_per_100_chars"]))
        head += f"小样本附注：{notes}密度更高，但样本不足不入榜。"
    return head


if __name__ == "__main__":
    scan()
