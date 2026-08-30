"""声音意象扫描：读取分析语料，输出 sound_stats.json。

用法（可独立复跑，语料更新后重跑即刷新统计）：
    python scan_sound.py

匹配算法：先挖除 EXCLUDE_PATTERNS 已知误报片段，再按词长降序
最长优先匹配，命中即以占位符抹除，避免"猿声"同时计入"猿"与"声"。

per_poet 特有字段：
- sound_categories: 六类声音命中占比（兽鸣/鸟啼/器乐/钟磬/自然声/人声）
- soundscape_signature: 前 6 个标志性声音 [[词, 次数], ...]。
  标志性得分 = 次数 × lift，lift = 诗人内词频占比 / 全语料词频占比，
  即"既常出现、又比别人更偏爱"的声音；仅取次数≥2 的词，不足 6 个时
  按次数补足。
- quiet_ratio: 全诗无任何声音词的诗占比（"无声诗人"指数）
"""

import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent          # .../data/stylometry
DATA_DIR = HERE.parent                          # .../data
ROOT = DATA_DIR.parent
OUT_JSON = HERE / "sound_stats.json"

sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "tools"))
import sound_dict  # noqa: E402
from famous_poet_corpus import atomic_dump_json, load_analysis_poems  # noqa: E402

PLACEHOLDER = "□"  # □，与任何词条都不匹配


def cjk_len(text: str) -> int:
    """正文汉字数（统一 CJK 区），作为 hits_per_100_chars 的分母。"""
    return sum(1 for ch in text if "一" <= ch <= "鿿")


def scan_body(body: str, words_desc: list[str]) -> Counter:
    """对单首诗正文做最长优先匹配，返回 {词: 次数}。"""
    text = body
    for pat in sound_dict.EXCLUDE_PATTERNS:
        text = text.replace(pat, PLACEHOLDER * len(pat))
    hits: Counter = Counter()
    for w in words_desc:
        n = text.count(w)
        if n:
            hits[w] = n
            text = text.replace(w, PLACEHOLDER * len(w))
    return hits


def main() -> None:
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
    words_desc = sound_dict.words()
    cat_of = {row[0]: row[1] for row in sound_dict.SOUND_DICT}

    per_poem_out = []
    poet_word_hits: dict[str, Counter] = {}
    poet_poem_count: Counter = Counter()
    poet_quiet_count: Counter = Counter()
    poet_char_count: Counter = Counter()

    for p in poems:
        poet = p.get("poet") or p.get("author") or "未知"
        body = p.get("body") or ""
        hits = scan_body(body, words_desc)
        poet_poem_count[poet] += 1
        poet_char_count[poet] += cjk_len(body)
        if not hits:
            poet_quiet_count[poet] += 1
        poet_word_hits.setdefault(poet, Counter()).update(hits)
        per_poem_out.append({
            "title": p.get("title", ""),
            "poet": poet,
            "work_id": p.get("work_id"),
            "canonical_gushiwen_id": p.get("canonical_gushiwen_id"),
            "body_hash": p.get("body_hash", ""),
            "hits": sorted(hits.items(), key=lambda kv: (-kv[1], kv[0])),
        })

    # 全语料词频，用于 lift（标志性）计算
    corpus_hits: Counter = Counter()
    for c in poet_word_hits.values():
        corpus_hits.update(c)
    corpus_total = sum(corpus_hits.values())

    per_poet = {}
    for poet, n_poems in poet_poem_count.items():
        wh = poet_word_hits.get(poet, Counter())
        hits_total = sum(wh.values())
        chars = poet_char_count[poet]

        cat_counts: Counter = Counter()
        for w, n in wh.items():
            cat_counts[cat_of[w]] += n
        sound_categories = {
            cat: (round(cat_counts.get(cat, 0) / hits_total, 4) if hits_total else 0.0)
            for cat in sound_dict.VALID_CATEGORIES
        }

        # 标志性声音：次数×lift，取前6；不足6按次数补
        signature = []
        if hits_total:
            scored = []
            for w, n in wh.items():
                if n < 2:
                    continue
                poet_share = n / hits_total
                corpus_share = corpus_hits[w] / corpus_total
                scored.append((n * poet_share / corpus_share, n, w))
            scored.sort(key=lambda t: (-t[0], -t[1], t[2]))
            signature = [[w, n] for _, n, w in scored[:6]]
            if len(signature) < 6:
                chosen = {w for w, _ in signature}
                fill = sorted(((n, w) for w, n in wh.items() if w not in chosen),
                              key=lambda t: (-t[0], t[1]))
                signature += [[w, n] for n, w in fill[:6 - len(signature)]]

        per_poet[poet] = {
            "poem_count": n_poems,
            "hits_total": hits_total,
            "hits_per_100_chars": round(hits_total / chars * 100, 3) if chars else 0.0,
            "top_words": [[w, n] for w, n in
                          sorted(wh.items(), key=lambda kv: (-kv[1], kv[0]))[:10]],
            "sound_categories": sound_categories,
            "soundscape_signature": signature,
            "quiet_ratio": round(poet_quiet_count[poet] / n_poems, 4),
            "chars_total": chars,
        }

    stats = {
        "schema_version": 1,
        "corpus_source": corpus_source,
        "corpus_path": corpus_path,
        "dict_size": len(sound_dict.SOUND_DICT),
        "generated_from_poems": len(poems),
        "corpus_top_words": [[w, n] for w, n in corpus_hits.most_common(20)],
        "per_poet": dict(sorted(per_poet.items(),
                                key=lambda kv: -kv[1]["hits_total"])),
        "per_poem": per_poem_out,
    }
    atomic_dump_json(OUT_JSON, stats)
    print(f"[scan_sound] 扫描 {len(poems)} 首 / {len(per_poet)} 位诗人，"
          f"词典 {stats['dict_size']} 词条，总命中 {corpus_total}，"
          f"已写出 {OUT_JSON}")


if __name__ == "__main__":
    main()
