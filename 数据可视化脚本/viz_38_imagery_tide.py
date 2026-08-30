# -*- coding: utf-8 -*-
"""Generate competition page 38: 唐宋意象潮汐（分析版）.

Zero-argument rerun:
    python 数据可视化脚本/viz_38_imagery_tide.py

Read-only inputs:
    data/analysis/famous_poets_full.jsonl.gz
    data/poems.json
    data/imagery_tide_lexicon.py
    data/reviewed/poet_journeys.json
    data/reviewed/verified_all_poet_fact_packages.jsonl
    data/candidates/work_chronology_supplements.jsonl
    data/candidates/{libai,dufu,baijuyi,sushi,luyou,liqingzhao}_spirit_chronology.csv

Owned outputs:
    output/38_唐宋意象潮汐.html
    output/assets/competition/imagery_tide_data.json
    output/assets/competition/imagery_tide_dating.json

Analysis layers (all computed, none hand-written):
    1. headline conclusions driven by the numbers below;
    2. Tang/Song overall difference + author-equal-weighted replication;
    3. leave-one-author-out robustness for corpus-weighted and author-equal gaps;
    4. per-author exact additive contribution decomposition;
    5. chronology bins restricted to per-work dated works
       (verified packages > curated six-poet CSV candidates > souyun B/C candidates),
       every dated row keeps source name/URL, note, grade and year type;
    6. genre strata from explicit upstream datasets (poet.tang/poet.song = 诗,
       ci.song = 词, canonical = 未标) — 未标 is never silently dropped;
    7. sentence-level co-occurrence with minimum support and lift contrast.

Page template constants (TEMPLATE_CSS / TEMPLATE_BODY / TEMPLATE_SCRIPT) are
assembled from backups/viz38_20260829/tmp_template_*.txt by the injection step
documented in the delivery report; they are stored in this file verbatim.
"""

from __future__ import annotations

import csv
import glob
import hashlib
import importlib.util
import json
import math
import re
import sys
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from famous_poet_corpus import load_analysis_poems  # noqa: E402

FULL_CORPUS_PATH = ROOT / "data" / "analysis" / "famous_poets_full.jsonl.gz"
POEMS_JSON = ROOT / "data" / "poems.json"
LEXICON_PY = ROOT / "data" / "imagery_tide_lexicon.py"
JOURNEYS_JSON = ROOT / "data" / "reviewed" / "poet_journeys.json"
VERIFIED_PACKAGES_JSONL = ROOT / "data" / "reviewed" / "verified_all_poet_fact_packages.jsonl"
CHRONOLOGY_SUPPLEMENTS_JSONL = ROOT / "data" / "candidates" / "work_chronology_supplements.jsonl"
SIX_POET_CHRONOLOGY_PATHS = sorted(
    glob.glob(str(ROOT / "data" / "candidates" / "*_spirit_chronology.csv"))
)
OUT_JSON = ROOT / "output" / "assets" / "competition" / "imagery_tide_data.json"
OUT_HTML = ROOT / "output" / "38_唐宋意象潮汐.html"
OUT_DATING_JSON = ROOT / "output" / "assets" / "competition" / "imagery_tide_dating.json"

DYNASTIES = ("唐", "宋")
EVIDENCE_CANDIDATE_LIMIT = 64
EXCLUDED_CATEGORIES = {
    "情志": "主观情绪、动作或状态词，不属于本页的客观意象口径",
    "人物": "人物身份与称谓，不作为景物或器物意象统计",
    "空间": "抽象空间与距离概念，不作为具象物统计",
    "时序": "单独的时序标记不作为具象物统计",
}

CHAPTER_DEFS = (
    ("tang-travel", 725, 754, "盛唐远游"),
    ("an-shi", 755, 763, "安史乱中"),
    ("new-yuefu", 800, 825, "中唐新乐府"),
    ("northern-song", 1061, 1094, "北宋外任与贬谪"),
    ("southern-song", 1103, 1210, "南宋流离与家国"),
)
EXPECTED_CHAPTER_COUNTS = (7, 4, 6, 6, 13)

EVENT_ANCHORS = (
    {
        "year": 755,
        "label": "安史之乱",
        "role": "历史背景锚点，不参与词频计算",
        "sourceName": "《资治通鉴》卷二百一十七",
        "sourceUrl": "https://zh.wikisource.org/wiki/資治通鑑/卷217",
        "sourceNote": "原始史籍在线转录；本页只取755年为背景标记。",
    },
    {
        "year": 907,
        "label": "唐亡",
        "role": "历史背景锚点，不参与词频计算",
        "sourceName": "《资治通鉴》卷二百六十六",
        "sourceUrl": "https://zh.wikisource.org/wiki/資治通鑑/卷266",
        "sourceNote": "原始史籍在线转录；本页以907年作唐宋分界背景。",
    },
    {
        "year": 960,
        "label": "北宋建立",
        "role": "历史背景锚点，不参与词频计算",
        "sourceName": "《续资治通鉴长编》卷一",
        "sourceUrl": "https://zh.wikisource.org/wiki/續資治通鑑長編/卷001",
        "sourceNote": "原始史籍在线转录；本页只取960年为背景标记。",
    },
    {
        "year": 1079,
        "label": "乌台诗案",
        "role": "历史背景锚点，不参与词频计算",
        "sourceName": "cnkgraph 苏轼年谱开放数据",
        "sourceUrl": "https://open.cnkgraph.com/api/Biography?Author=%E8%8B%8F%E8%BD%BC",
        "sourceNote": "开放年谱数据用于核对元丰二年苏轼被逮与贬黄州的时间链。",
    },
    {
        "year": 1127,
        "label": "靖康之变",
        "role": "历史背景锚点，不参与词频计算",
        "sourceName": "《宋史》卷二十三·钦宗本纪",
        "sourceUrl": "https://zh.wikisource.org/wiki/宋史/卷023",
        "sourceNote": "原始史籍在线转录；本页只取1127年为背景标记。",
    },
)

# Finite, inspectable context rules. They do not claim to solve every
# classical-Chinese ambiguity.
CONTEXT_RULE_DEFS = (
    {"id": "month_number_prefix", "word": "月", "label": "月份数字前缀", "reason": "月前紧邻正、元、冬、腊、闰或数字月份，按历法月份排除。"},
    {"id": "month_calendar_context", "word": "月", "label": "月份日期语境", "reason": "月与本、是、去、每、当、同、次、翌等时间指示词，或朔、晦、具体日期等后缀相邻。"},
    {"id": "cloud_speech_cue", "word": "云", "label": "言说动词语境", "reason": "云前出现有限的说话者或引述副词，按‘说’义排除。"},
    {"id": "cloud_quotation_repetition", "word": "云", "label": "云云引述省略", "reason": "连续‘云云’表示引述省略，不是天空云象。"},
    {"id": "wind_abstract_suffix", "word": "风", "label": "风的抽象后缀", "reason": "风流、风雅、风俗、风教等固定抽象构词不作天象。"},
    {"id": "wind_abstract_prefix", "word": "风", "label": "风的抽象前缀", "reason": "文风、世风、家风、遗风及明确的‘棘序之风’等不作天象。"},
)
CONTEXT_RULE_BY_ID = {item["id"]: item for item in CONTEXT_RULE_DEFS}
MONTH_NUMBER_PREFIX_RE = re.compile(r"(?:闰)?(?:正|元|冬|腊|[一二三四五六七八九十百廿卅〇零0-9]{1,4})$")
MONTH_TIME_PREFIX_RE = re.compile(r"(?:本|去|每|当|同|次|翌)$")
MONTH_IS_PREFIX_RE = re.compile(r"(?:^|[，。；：、！？!?（）()\s]|至)是$")
MONTH_TIME_SUFFIX_RE = re.compile(r"^(?:份|朔|晦|以来|之(?:初|末)|(?:初|末)?[一二三四五六七八九十廿卅〇零0-9]{1,3}(?:日|号))")
CLOUD_SPEECH_PREFIX_RE = re.compile(r"(?:但|只|仅|又|或|乃|皆|咸|俱|尝|自|相|共|谓|称|答|问|报|告|语|闻|传|僧|客|人|者|俗|谚|诗|书|史|古|儒|师|公|君|翁|叟|吏|帝|王|臣|曰)$")
WIND_ABSTRACT_SUFFIXES = ("流", "雅", "俗", "教", "化", "气", "尚", "范", "采", "骨", "格", "韵", "致", "情", "纪", "操", "节", "标", "神", "度", "貌", "规")
WIND_ABSTRACT_PREFIX_RE = re.compile(r"(?:文|诗|词|世|士|学|家|门|民|国|乡|儒|政|教|仁|礼|古|遗|棘序之)$")

CATEGORY_COLORS = {
    "天象": "#456f8a",
    "地理": "#28766d",
    "草木": "#66824d",
    "禽鸟": "#a8762b",
    "走兽": "#8b6544",
    "草虫": "#95823f",
    "鳞介": "#4f8292",
    "器物": "#a34f44",
    "建筑": "#726179",
    "身体": "#9b5a73",
}

SENTENCE_END_RE = re.compile(r"[。！？!?；;\n]+")
REMOTE_SCRIPT_RE = re.compile(r"<script[^>]+src=[\"'](?:https?:)?//", re.I)

# ---------------------------------------------------------------------------
# Dating / binning / co-occurrence configuration. Every threshold is published
# on the page so readers can audit which points are drawn and which are not.
# ---------------------------------------------------------------------------

# 逐篇年代证据的三级优先级（同一作品取最高一级，不叠加）：
#   verified-B  人工复核包（verified_all_poet_fact_packages.jsonl，全部 verified，B 级）
#   curated-B/C 项目内部六诗人编年 CSV 中 status=candidate 的行（绑定规范库 poet+title）
#   candidate-B/C 搜韵开放 API 作品编年候选（needs_review，按 body_hash 已由上游 link）
DATING_TIER_LABELS = {
    "verified-B": "人工复核包（verified，B级证据）",
    "curated-B": "六诗人编年CSV候选（B级，未终审）",
    "curated-C": "六诗人编年CSV候选（C级，未终审）",
    "candidate-B": "搜韵编年候选（B级，未人工复核）",
    "candidate-C": "搜韵编年候选（C级，未人工复核）",
}
DATING_TIER_PRIORITY = ("verified-B", "curated-B", "curated-C", "candidate-B", "candidate-C")

BIN_WIDTH = 25
BIN_START_YEAR = 600
BIN_END_YEAR = 1324
MIN_BIN_WORKS = 40      # 时间箱画任意趋势点的最小作品数
MIN_BIN_CHARS = 4000    # 时间箱画任意趋势点的最小正文汉字
MIN_WORD_BIN_HITS = 8   # 单词单箱画点的最小命中数
MIN_PAIR_SUPPORT = 15   # 共现对进入对比榜的两侧最小支持数
MIN_COLLOCATE_COUNT = 8 # 语境迁移表的最小共现次数
TREND_WORD_COUNT = 10   # 时间轴可切换的词数
CI_Z = 1.96

GENRE_DEFS = (
    ("poetry", "诗", ("poet.tang", "poet.song")),
    ("ci", "词", ("ci.song",)),
    ("unmarked", "未标", ("canonical",)),
)
GENRE_BY_DATASET = {
    dataset: genre_id
    for genre_id, _label, datasets in GENRE_DEFS
    for dataset in datasets
}


def genre_for_poem(poem: dict) -> str:
    """Classify a merged work from every explicit upstream source.

    ``source_dataset`` identifies the retained primary record, not necessarily
    the only source. A canonical-primary work can still have an explicit
    poetry/ci match in ``sources`` and must not be mislabeled as unmarked.
    """
    datasets = {str(poem.get("source_dataset") or "")}
    datasets.update(
        str(source.get("source_dataset") or "")
        for source in poem.get("sources", [])
    )
    datasets.discard("")
    unknown = datasets - set(GENRE_BY_DATASET)
    assert not unknown, f"未知 source_dataset：{sorted(unknown)}"
    has_poetry = bool(datasets & {"poet.tang", "poet.song"})
    has_ci = "ci.song" in datasets
    assert not (has_poetry and has_ci), f"同一作品同时匹配诗库与词库：{poem.get('work_id')}"
    if has_ci:
        return "ci"
    if has_poetry:
        return "poetry"
    assert datasets == {"canonical"}, f"无法判定体裁来源：{sorted(datasets)}"
    return "unmarked"


def load_python_module(path: Path):
    spec = importlib.util.spec_from_file_location("imagery_tide_lexicon_for_viz38", path)
    assert spec and spec.loader, f"词典模块加载失败：{path}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def is_chinese_char(char: str) -> bool:
    code = ord(char)
    return (
        0x3400 <= code <= 0x4DBF
        or 0x4E00 <= code <= 0x9FFF
        or 0xF900 <= code <= 0xFAFF
        or 0x20000 <= code <= 0x2FA1F
        or 0x30000 <= code <= 0x323AF
    )


def chinese_char_count(text: str) -> int:
    return sum(is_chinese_char(char) for char in text)


def normalized_rate(hits: int, denominator: int) -> float:
    assert denominator > 0
    return round(hits * 10000 / denominator, 4)


def standard_median(values: list[float]) -> float:
    """Return the conventional median, averaging the middle pair when even."""
    if not values:
        return 0.0
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def poisson_ci(hits: int, denominator: int) -> tuple[float, float]:
    """Normal-approximation 95% CI for a per-10k rate with char exposure."""
    if denominator <= 0:
        return (0.0, 0.0)
    rate = hits * 10000 / denominator
    half = CI_Z * math.sqrt(max(hits, 0)) * 10000 / denominator
    return (round(max(rate - half, 0.0), 4), round(rate + half, 4))


def grade_counts(values) -> dict[str, int]:
    counts = Counter(values)
    return {grade: counts.get(grade, 0) for grade in ("A", "B", "C")}


def build_buckets(words: list[str]) -> dict[str, tuple[str, ...]]:
    buckets: dict[str, list[str]] = defaultdict(list)
    for word in words:
        buckets[word[0]].append(word)
    return {
        first: tuple(sorted(items, key=lambda word: (-len(word), word)))
        for first, items in buckets.items()
    }


def context_exclusion_rule(text: str, start: int, end: int, word: str) -> str | None:
    left = text[max(0, start - 8) : start]
    right = text[end : min(len(text), end + 8)]
    if word == "月":
        if MONTH_NUMBER_PREFIX_RE.search(left):
            return "month_number_prefix"
        if (
            MONTH_TIME_PREFIX_RE.search(left)
            or MONTH_IS_PREFIX_RE.search(left)
            or MONTH_TIME_SUFFIX_RE.match(right)
        ):
            return "month_calendar_context"
    elif word == "云":
        if left.endswith("云") or right.startswith("云"):
            pair_start = start - 1 if left.endswith("云") else start
            pair_left = text[max(0, pair_start - 8) : pair_start]
            if CLOUD_SPEECH_PREFIX_RE.search(pair_left):
                return "cloud_quotation_repetition"
        if CLOUD_SPEECH_PREFIX_RE.search(left):
            return "cloud_speech_cue"
    elif word == "风":
        if right.startswith(WIND_ABSTRACT_SUFFIXES):
            return "wind_abstract_suffix"
        if WIND_ABSTRACT_PREFIX_RE.search(left) and not right.startswith("霜"):
            return "wind_abstract_prefix"
    return None


def scan_text(
    text: str, buckets: dict[str, tuple[str, ...]]
) -> tuple[list[tuple[int, int, str]], list[tuple[int, int, str, str]]]:
    """Longest-match scan returning accepted and context-excluded matches."""
    matches: list[tuple[int, int, str]] = []
    exclusions: list[tuple[int, int, str, str]] = []
    index = 0
    while index < len(text):
        hit = None
        for word in buckets.get(text[index], ()):
            if text.startswith(word, index):
                hit = word
                break
        if hit is None:
            index += 1
            continue
        end = index + len(hit)
        rule_id = context_exclusion_rule(text, index, end, hit)
        if rule_id:
            exclusions.append((index, end, hit, rule_id))
        else:
            matches.append((index, end, hit))
        index = end
    for previous, current in zip(matches, matches[1:]):
        assert previous[1] <= current[0], "意象匹配出现重叠"
    return matches, exclusions


def sentence_spans(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    start = 0
    for match in SENTENCE_END_RE.finditer(text):
        end = match.end()
        left, right = start, end
        while left < right and text[left].isspace():
            left += 1
        while right > left and text[right - 1].isspace():
            right -= 1
        if left < right:
            spans.append((left, right))
        start = end
    left, right = start, len(text)
    while left < right and text[left].isspace():
        left += 1
    while right > left and text[right - 1].isspace():
        right -= 1
    if left < right:
        spans.append((left, right))
    return spans


def sentence_word_sets(
    spans: list[tuple[int, int]], matches: list[tuple[int, int, str]]
) -> list[tuple[int, int, frozenset[str]]]:
    """Group non-overlapping matches into their sentence spans.

    Returns (sentence_start, sentence_end, distinct word set) per span that
    contains at least one imagery match. Same sentence definition as evidence.
    """
    grouped: dict[tuple[int, int], set[str]] = defaultdict(set)
    span_index = 0
    for start, end, word in matches:
        while span_index + 1 < len(spans) and start >= spans[span_index][1]:
            span_index += 1
        sentence_start, sentence_end = spans[span_index]
        assert sentence_start <= start < end <= sentence_end
        grouped[(sentence_start, sentence_end)].add(word)
    return [
        (sentence_start, sentence_end, frozenset(words))
        for (sentence_start, sentence_end), words in grouped.items()
    ]


def evidence_for_record(
    poem: dict,
    record_index: int,
    matches: list[tuple[int, int, str]],
    poem_counts: Counter,
    spans: list[tuple[int, int]] | None = None,
) -> dict[str, list[dict]]:
    """Return one exact, untruncated evidence record per word and sentence."""
    if spans is None:
        spans = sentence_spans(poem["body"])
    grouped: dict[tuple[str, int, int], list[tuple[int, int]]] = defaultdict(list)
    span_index = 0
    for start, end, word in matches:
        while span_index + 1 < len(spans) and start >= spans[span_index][1]:
            span_index += 1
        sentence_start, sentence_end = spans[span_index]
        assert sentence_start <= start < end <= sentence_end
        grouped[(word, sentence_start, sentence_end)].append((start, end))

    result: dict[str, list[dict]] = defaultdict(list)
    for (word, sentence_start, sentence_end), positions in grouped.items():
        sentence = poem["body"][sentence_start:sentence_end]
        first_start, first_end = positions[0]
        local_start = first_start - sentence_start
        local_end = first_end - sentence_start
        assert sentence[local_start:local_end] == word
        result[word].append(
            {
                "title": poem.get("title") or "无题（上游未标）",
                "poet": poem["author"],
                "dynasty": poem.get("person_period") or poem["dynasty"],
                "sentence": sentence,
                "matchStart": local_start,
                "matchEnd": local_end,
                "sentenceMatchCount": len(positions),
                "poemWordHits": poem_counts[word],
                "recordIndex": record_index,
                "sourcePoemId": poem.get("canonical_gushiwen_id") or poem.get("source_poem_id", ""),
                "canonicalMatch": bool(poem.get("canonical_match") or poem.get("source_poem_id")),
                "workId": poem.get("work_id", ""),
                "sourceUrl": poem.get("source_url", ""),
            }
        )
    return result


def evidence_sort_key(item: dict):
    dynasty_order = {"唐": 0, "宋": 1}
    return (
        -int(bool(item.get("canonicalMatch"))),
        -item["poemWordHits"],
        dynasty_order.get(item["dynasty"], 9),
        item["poet"],
        item["title"],
        item["sentence"],
        item["matchStart"],
        item["recordIndex"],
    )


def dedupe_evidence(items: list[dict]) -> list[dict]:
    seen = set()
    output = []
    for item in sorted(items, key=evidence_sort_key):
        key = (item["dynasty"], item["poet"], item["title"], item["sentence"])
        if key in seen:
            continue
        seen.add(key)
        output.append(item)
    return output


def select_corpus_evidence(items: list[dict]) -> list[dict]:
    unique = dedupe_evidence(items)
    selected: list[dict] = []
    selected_keys = set()
    for dynasty in DYNASTIES:
        dynasty_items = [item for item in unique if item["dynasty"] == dynasty][:2]
        for item in dynasty_items:
            key = (item["dynasty"], item["poet"], item["title"], item["sentence"])
            selected_keys.add(key)
            selected.append(item)
    if len(selected) < 4:
        for item in unique:
            key = (item["dynasty"], item["poet"], item["title"], item["sentence"])
            if key in selected_keys:
                continue
            selected.append(item)
            selected_keys.add(key)
            if len(selected) == 4:
                break
    return selected


def retain_evidence(candidates: list[dict], additions: list[dict]) -> None:
    """流式保留足够的确定性候选，避免全量语料证据句占满内存。"""
    candidates.extend(additions)
    if len(candidates) > EVIDENCE_CANDIDATE_LIMIT * 2:
        candidates[:] = dedupe_evidence(candidates)[:EVIDENCE_CANDIDATE_LIMIT]


def public_evidence(item: dict) -> dict:
    return {
        key: item[key]
        for key in (
            "title",
            "poet",
            "dynasty",
            "sentence",
            "matchStart",
            "matchEnd",
            "sentenceMatchCount",
            "poemWordHits",
            "sourcePoemId",
            "canonicalMatch",
            "workId",
            "sourceUrl",
        )
    }


def exclusion_example(
    poem: dict, record_index: int, start: int, end: int, word: str, rule_id: str
) -> dict:
    spans = sentence_spans(poem["body"])
    sentence_start, sentence_end = next(
        (left, right) for left, right in spans if left <= start < end <= right
    )
    sentence = poem["body"][sentence_start:sentence_end]
    local_start = start - sentence_start
    local_end = end - sentence_start
    assert sentence[local_start:local_end] == word
    return {
        "ruleId": rule_id,
        "word": word,
        "dynasty": poem.get("person_period") or poem["dynasty"],
        "poet": poem["author"],
        "title": poem.get("title") or "无题（上游未标）",
        "sentence": sentence,
        "matchStart": local_start,
        "matchEnd": local_end,
        "recordIndex": record_index,
    }


def word_side_stats(
    dynasty: str,
    word: str,
    dynasty_chars: Counter,
    dynasty_poem_counts: Counter,
    dynasty_word_hits: dict[str, Counter],
    dynasty_word_poems: dict[str, Counter],
) -> dict:
    raw = dynasty_word_hits[dynasty][word]
    denominator = dynasty_chars[dynasty]
    poems_with_hit = dynasty_word_poems[dynasty][word]
    poem_records = dynasty_poem_counts[dynasty]
    return {
        "rawHits": raw,
        "ratePer10k": normalized_rate(raw, denominator),
        "chineseCharDenominator": denominator,
        "poemRecords": poem_records,
        "poemsWithHit": poems_with_hit,
        "poemHitRate": round(poems_with_hit / poem_records, 4) if poem_records else 0.0,
    }


# ---------------------------------------------------------------------------
# Per-work dating table
# ---------------------------------------------------------------------------


def dating_year_type(year_start: int, year_end: int, precision: str) -> str:
    """Normalize every dating source to the one published year-type rule."""
    if year_start != year_end:
        return "range"
    return "exact" if precision in {"exact", "year_month"} else "approximate"


def verified_dating_rows() -> list[dict]:
    rows = []
    with open(VERIFIED_PACKAGES_JSONL, encoding="utf-8") as handle:
        for line in handle:
            rec = json.loads(line)
            key = rec["poem_key"]
            chron = rec.get("chronology") or {}
            precision = chron.get("year_precision")
            if precision not in {"exact", "year", "approximate", "range"}:
                continue
            evidence = (rec.get("evidence") or [{}])[0]
            year_start, year_end = chron.get("year_start"), chron.get("year_end")
            if year_start is None or year_end is None:
                continue
            rows.append(
                {
                    "bodyHash": key.get("body_hash") or "",
                    "poet": key.get("poet") or "",
                    "title": key.get("title") or "",
                    "yearStart": int(year_start),
                    "yearEnd": int(year_end),
                    "yearType": dating_year_type(int(year_start), int(year_end), precision),
                    "precisionRaw": precision,
                    "tier": "verified-B",
                    "grade": evidence.get("source_grade") or "B",
                    "sourceName": evidence.get("source_name") or "",
                    "sourceUrl": evidence.get("source_url") or "",
                    "sourceNote": (evidence.get("excerpt") or "")[:160],
                    "reviewStatus": (rec.get("verification") or {}).get("status") or "",
                }
            )
    return rows


def six_poet_csv_dating_rows(canonical_index: dict) -> tuple[list[dict], dict]:
    rows: list[dict] = []
    stats = {"rows": 0, "candidate": 0, "bound": 0, "skippedStatus": 0, "skippedPrecision": 0, "skippedGrade": 0, "unboundTitle": 0}
    accepted_precisions = {"exact", "approximate", "disputed"}
    for path in SIX_POET_CHRONOLOGY_PATHS:
        with open(path, encoding="utf-8-sig") as handle:
            for raw in csv.DictReader(handle):
                stats["rows"] += 1
                status = (raw.get("status") or "").strip()
                if status != "candidate":
                    stats["skippedStatus"] += 1
                    continue
                stats["candidate"] += 1
                precision = (raw.get("year_precision") or "").strip()
                if precision not in accepted_precisions:
                    stats["skippedPrecision"] += 1
                    continue
                grade = (raw.get("fact_grade") or "").strip()
                if grade not in {"B", "C"}:
                    stats["skippedGrade"] += 1
                    continue
                poet = (raw.get("poet") or "").strip()
                title = (raw.get("title") or "").strip()
                matches = canonical_index.get((poet, title), [])
                if len(matches) != 1:
                    stats["unboundTitle"] += 1
                    continue
                record_index, poem = matches[0]
                try:
                    year_start = int(str(raw.get("year_start")).strip())
                    year_end = int(str(raw.get("year_end")).strip())
                except (TypeError, ValueError):
                    stats["skippedPrecision"] += 1
                    continue
                stats["bound"] += 1
                rows.append(
                    {
                        "bodyHash": poem.get("body_hash") or "",
                        "workId": poem.get("work_id") or "",
                        "poet": poet,
                        "title": title,
                        "yearStart": year_start,
                        "yearEnd": year_end,
                        "yearType": dating_year_type(year_start, year_end, precision),
                        "precisionRaw": precision,
                        "tier": f"curated-{grade}",
                        "grade": grade,
                        "sourceName": (raw.get("source_name") or "").strip(),
                        "sourceUrl": (raw.get("source_url") or "").strip(),
                        "sourceNote": ((raw.get("source_note") or "").strip())[:160],
                        "disputeNote": "系年存在争议" if precision == "disputed" else "",
                    }
                )
    return rows, stats


def souyun_dating_rows(hash_owners: dict[str, list[dict]]) -> tuple[list[dict], dict]:
    by_identity: dict[tuple[str, str], list[dict]] = defaultdict(list)
    stats = {"rows": 0, "linked": 0, "inCorpus": 0, "multiRow": 0, "disagreement": 0}
    with open(CHRONOLOGY_SUPPLEMENTS_JSONL, encoding="utf-8") as handle:
        for line in handle:
            rec = json.loads(line)
            stats["rows"] += 1
            if not rec.get("linked"):
                continue
            stats["linked"] += 1
            body_hash = rec.get("body_hash") or ""
            poet = str(rec.get("poet") or "")
            if not any(
                str(owner.get("author") or owner.get("poet") or "") == poet
                for owner in hash_owners.get(body_hash, [])
            ):
                continue
            if rec.get("year_start") is None or rec.get("year_end") is None:
                continue
            stats["inCorpus"] += 1
            by_identity[(body_hash, poet)].append(rec)
    rows = []
    for body_hash, poet in sorted(by_identity):
        candidates = by_identity[(body_hash, poet)]
        if len(candidates) > 1:
            stats["multiRow"] += 1
        candidates = sorted(
            candidates,
            key=lambda rec: (
                rec.get("source_grade") != "B",
                rec.get("year_start"),
                str(rec.get("candidate_id")),
            ),
        )
        chosen = candidates[0]
        spans = {(rec.get("year_start"), rec.get("year_end")) for rec in candidates}
        if len(spans) > 1:
            stats["disagreement"] += 1
        year_start, year_end = int(chosen["year_start"]), int(chosen["year_end"])
        grade = chosen.get("source_grade") or "C"
        precision = chosen.get("precision") or ""
        year_type = dating_year_type(year_start, year_end, precision)
        rows.append(
            {
                "bodyHash": body_hash,
                "poet": poet,
                "title": chosen.get("poem_title") or "",
                "yearStart": year_start,
                "yearEnd": year_end,
                "yearType": year_type,
                "precisionRaw": precision,
                "tier": f"candidate-{grade}",
                "grade": grade,
                "sourceName": chosen.get("source_name") or "",
                "sourceUrl": chosen.get("source_url") or "",
                "sourceNote": (chosen.get("source_note") or "")[:160],
                "candidateRows": len(candidates),
                "yearDisagreement": len(spans) > 1,
            }
        )
    return rows, stats


def build_dating_table(
    analysis_rows: list[dict], canonical_index: dict[tuple[str, str], list[tuple[int, dict]]]
) -> tuple[dict[str, dict], list[dict], dict]:
    """Return (workId -> best dating row, unique works, resolution stats)."""
    hash_owners: dict[str, list[dict]] = defaultdict(list)
    owners_by_work_id: dict[str, dict] = {}
    hash_collisions = 0
    for row in analysis_rows:
        work_id = str(row.get("work_id") or "")
        if not work_id or work_id in owners_by_work_id:
            raise ValueError(f"全作品语料 work_id 缺失或重复：{work_id!r}")
        owners_by_work_id[work_id] = row
        for key in (row.get("body_hash"), row.get("body_original_hash")):
            if not key:
                continue
            if row not in hash_owners[key]:
                if hash_owners[key]:
                    hash_collisions += 1
                hash_owners[key].append(row)

    verified = verified_dating_rows()
    curated, curated_stats = six_poet_csv_dating_rows(canonical_index)
    candidates, souyun_stats = souyun_dating_rows(hash_owners)

    def resolve_owner(dating: dict) -> dict | None:
        poet = str(dating.get("poet") or "")
        work_id = str(dating.get("workId") or "")
        if work_id:
            owner = owners_by_work_id.get(work_id)
            if owner is None:
                return None
            owner_poet = str(owner.get("author") or owner.get("poet") or "")
            return owner if owner_poet == poet else None
        candidates_for_hash = [
            owner
            for owner in hash_owners.get(str(dating.get("bodyHash") or ""), [])
            if str(owner.get("author") or owner.get("poet") or "") == poet
        ]
        if len(candidates_for_hash) > 1:
            title = str(dating.get("title") or "")
            titled = [owner for owner in candidates_for_hash if str(owner.get("title") or "") == title]
            if len(titled) == 1:
                candidates_for_hash = titled
        return candidates_for_hash[0] if len(candidates_for_hash) == 1 else None

    priority_index = {tier: index for index, tier in enumerate(DATING_TIER_PRIORITY)}
    best: dict[str, dict] = {}
    tier_counts: Counter = Counter()
    unresolved_rows: Counter = Counter()
    for source_rows in (verified, curated, candidates):
        for row in source_rows:
            owner = resolve_owner(row)
            if owner is None:
                unresolved_rows[row["tier"]] += 1
                continue
            work_id = str(owner["work_id"])
            resolved = dict(row)
            resolved["workId"] = work_id
            resolved["poet"] = str(owner.get("author") or owner.get("poet") or "")
            resolved["personPeriod"] = str(owner.get("person_period") or "")
            resolved["yearType"] = dating_year_type(
                int(resolved["yearStart"]),
                int(resolved["yearEnd"]),
                str(resolved.get("precisionRaw") or ""),
            )
            current = best.get(work_id)
            if current is None or priority_index[row["tier"]] < priority_index[current["tier"]]:
                best[work_id] = resolved

    for row in best.values():
        row["inBinary"] = row["personPeriod"] in DYNASTIES
        mid = (row["yearStart"] + row["yearEnd"]) / 2
        if row["inBinary"] and BIN_START_YEAR <= mid <= BIN_END_YEAR:
            row["binStart"] = int(mid // BIN_WIDTH) * BIN_WIDTH
        else:
            row["binStart"] = None
        tier_counts[row["tier"]] += 1

    stats = {
        "verifiedRows": len(verified),
        "curatedRows": len(curated),
        "candidateRows": len(candidates),
        "uniqueDatedWorks": len(best),
        "tierCounts": dict(sorted(tier_counts.items())),
        "hashCollisions": hash_collisions,
        "unresolvedRows": dict(sorted(unresolved_rows.items())),
        "curated": curated_stats,
        "souyun": souyun_stats,
    }
    return best, sorted(best.values(), key=lambda row: (row["tier"], row["poet"], row["yearStart"])), stats


def dating_artifact(works: list[dict], stats: dict, source_hashes: dict) -> dict:
    records = []
    for row in works:
        records.append(
            {
                "workId": row.get("workId") or "",
                "poet": row["poet"],
                "title": row["title"],
                "personPeriod": row["personPeriod"],
                "yearStart": row["yearStart"],
                "yearEnd": row["yearEnd"],
                "yearType": row["yearType"],
                "precisionRaw": row.get("precisionRaw") or "",
                "evidenceTier": row["tier"],
                "evidenceTierLabel": DATING_TIER_LABELS.get(row["tier"], row["tier"]),
                "grade": row.get("grade") or "",
                "sourceName": row.get("sourceName") or "",
                "sourceUrl": row.get("sourceUrl") or "",
                "sourceNote": row.get("sourceNote") or "",
                "disputeNote": row.get("disputeNote") or "",
                "candidateRows": row.get("candidateRows") or 1,
                "yearDisagreement": bool(row.get("yearDisagreement")),
                "inBinary": row["inBinary"],
                "binStart": row["binStart"],
                "bodyHash": row["bodyHash"],
            }
        )
    return {
        "meta": {
            "title": "38 唐宋意象潮汐 · 逐篇系年审计文件",
            "generatedBy": "数据可视化脚本/viz_38_imagery_tide.py",
            "priorityRule": "verified-B > curated-B > curated-C > candidate-B > candidate-C（同一作品取最高一级）",
            "yearTypeRule": (
                "exact=自序/题注等精确到月或人工复核判为精确；approximate=学术编年单一粒度年；"
                "range=起讫不同的区间。所有年份都不用作者生卒年或朝代中点伪造。"
            ),
            "stats": stats,
            "sourceHashes": source_hashes,
        },
        "records": records,
    }


def main() -> None:
    full_corpus_bytes = FULL_CORPUS_PATH.read_bytes()
    canonical_bytes = POEMS_JSON.read_bytes()
    lexicon_bytes = LEXICON_PY.read_bytes()
    journeys_bytes = JOURNEYS_JSON.read_bytes()
    verified_bytes = VERIFIED_PACKAGES_JSONL.read_bytes()
    supplements_bytes = CHRONOLOGY_SUPPLEMENTS_JSONL.read_bytes()
    six_csv_bytes = b"".join(Path(path).read_bytes() for path in SIX_POET_CHRONOLOGY_PATHS)
    analysis_rows, corpus_source = load_analysis_poems()
    canonical_poems = json.loads(canonical_bytes.decode("utf-8"))
    journeys = json.loads(journeys_bytes.decode("utf-8"))
    lexicon = load_python_module(LEXICON_PY)

    if corpus_source != "analysis_full":
        raise AssertionError("意象潮汐必须使用名家全作品分析语料")
    assert isinstance(canonical_poems, list) and canonical_poems, "规范诗库必须是非空数组"
    assert all(poem.get("title") and poem.get("author") and poem.get("body") for poem in canonical_poems)
    assert all(row.get("author") and row.get("body") and row.get("work_id") for row in analysis_rows)
    excluded_period_counts = Counter(
        str(row.get("person_period") or "未标")
        for row in analysis_rows
        if row.get("person_period") not in DYNASTIES
    )
    poems = [row for row in analysis_rows if row.get("person_period") in DYNASTIES]
    dynasty_poem_counts = Counter(poem["person_period"] for poem in poems)
    assert set(dynasty_poem_counts) == set(DYNASTIES) and all(dynasty_poem_counts.values())

    included_rows = list(lexicon.IMAGERY_TIDE_LEXICON)
    assert lexicon.validate() == {"terms": 160, "categories": 10}
    excluded_terms = [
        {
            "word": word,
            "category": category,
            "reason": (
                EXCLUDED_CATEGORIES[category]
                if category in EXCLUDED_CATEGORIES
                else "词条缺少具象尺度或意象说明，本页从客观意象口径排除"
            ),
        }
        for word, category in lexicon.HISTORICAL_EXCLUDED_TERMS
    ]
    assert len(included_rows) == 160, "客观意象词条口径应固定为 160"
    assert {row[1] for row in included_rows} == set(CATEGORY_COLORS)

    term_info = {
        row[0]: {
            "category": row[1],
            "cluster": row[2],
            "valence": row[3],
            "scale": row[4],
            "description": row[5],
        }
        for row in included_rows
    }
    words = sorted(term_info, key=lambda word: (-len(word), word))
    buckets = build_buckets(words)
    category_order = [category for category in CATEGORY_COLORS]
    category_term_counts = Counter(row[1] for row in included_rows)
    word_category = {word: term_info[word]["category"] for word in words}
    category_words: dict[str, list[str]] = defaultdict(list)
    for word in words:
        category_words[word_category[word]].append(word)

    # ---- stable identity indexes (needed by journey binding and CSV dating) ----
    analysis_by_canonical_id: dict[tuple[str, str], dict] = {}
    analysis_by_body_hash: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in analysis_rows:
        poet = str(row.get("author") or row.get("poet") or "")
        analysis_by_body_hash[(poet, str(row.get("body_hash") or ""))].append(row)
        canonical_ids = [row.get("canonical_gushiwen_id")]
        canonical_ids.extend(row.get("canonical_gushiwen_ids") or [])
        canonical_ids.extend(
            source.get("source_work_id")
            for source in row.get("sources", [])
            if source.get("source_dataset") == "canonical"
        )
        for raw_id in dict.fromkeys(canonical_ids):
            canonical_id = str(raw_id or "")
            if not canonical_id:
                continue
            key = (poet, canonical_id)
            if key in analysis_by_canonical_id:
                raise ValueError(f"全作品语料 canonical ID 重复：{key}")
            analysis_by_canonical_id[key] = row
    canonical_poem_index: dict[tuple[str, str], list[tuple[int, dict]]] = defaultdict(list)
    canonical_identity_hash_fallbacks = 0
    for record_index, raw_poem in enumerate(canonical_poems):
        poem = dict(raw_poem)
        poet = str(poem.get("author") or poem.get("poet") or "")
        canonical_id = str(poem.get("source_poem_id") or "")
        analysis_match = analysis_by_canonical_id.get((poet, canonical_id))
        if analysis_match is None:
            candidates = analysis_by_body_hash.get((poet, str(poem.get("body_hash") or "")), [])
            if len(candidates) != 1:
                raise KeyError(
                    f"规范诗作缺少唯一全作品稳定身份：{(poet, canonical_id)}；"
                    f"body_hash 候选={len(candidates)}"
                )
            analysis_match = candidates[0]
            canonical_identity_hash_fallbacks += 1
        poem["work_id"] = analysis_match["work_id"]
        poem["canonical_gushiwen_id"] = canonical_id
        poem["canonical_match"] = True
        canonical_poem_index[(poet, poem["title"])].append((record_index, poem))
    canonical_scan_cache: dict[int, dict] = {}
    canonical_record_evidence: dict[int, dict[str, list[dict]]] = {}

    # ---- per-work dating table (verified > curated CSV > souyun candidates) ----
    dating_by_work_id, dating_works, dating_stats = build_dating_table(analysis_rows, canonical_poem_index)
    assert all(row["yearType"] in {"exact", "approximate", "range"} for row in dating_works)
    assert all(row["tier"] in DATING_TIER_PRIORITY for row in dating_works)

    dynasty_chars: Counter = Counter()
    dynasty_authors: dict[str, set[str]] = {dynasty: set() for dynasty in DYNASTIES}
    dynasty_word_hits: dict[str, Counter] = {dynasty: Counter() for dynasty in DYNASTIES}
    dynasty_word_poems: dict[str, Counter] = {dynasty: Counter() for dynasty in DYNASTIES}
    dynasty_category_hits: dict[str, Counter] = {dynasty: Counter() for dynasty in DYNASTIES}
    dynasty_category_poems: dict[str, Counter] = {dynasty: Counter() for dynasty in DYNASTIES}
    dynasty_poems_with_imagery: Counter = Counter()
    evidence_candidates: dict[str, list[dict]] = defaultdict(list)
    context_exclusion_counts = Counter()
    context_exclusion_examples: dict[str, list[dict]] = defaultdict(list)
    zero_chinese_body_count = Counter()

    author_stats: dict[str, dict] = {}
    genre_stats: dict[str, dict[str, dict]] = {
        genre_id: {
            dynasty: {
                "poems": 0,
                "chars": 0,
                "poets": set(),
                "poemsWithImagery": 0,
                "wordHits": Counter(),
                "wordWorks": Counter(),
                "categoryHits": Counter(),
                "categoryWorks": Counter(),
            }
            for dynasty in DYNASTIES
        }
        for genre_id, _label, _datasets in GENRE_DEFS
    }
    bin_stats: dict[int, dict] = {}
    dated_period_counts: Counter = Counter()
    dated_tier_counts: Counter = Counter()
    dated_chars_total = 0
    dated_works_total = 0
    dated_authors: set[str] = set()
    sentence_totals: Counter = Counter()
    sentences_with_pair: Counter = Counter()
    sentence_word_counter: dict[str, Counter] = {dynasty: Counter() for dynasty in DYNASTIES}
    pair_counter: dict[str, Counter] = {dynasty: Counter() for dynasty in DYNASTIES}
    pair_examples: dict[tuple[str, str], list[tuple[str, int, int, int]]] = defaultdict(list)

    for record_index, poem in enumerate(poems):
        dynasty = poem["person_period"]
        author = poem["author"]
        dynasty_authors[dynasty].add(author)
        chars = chinese_char_count(poem["body"])
        if chars == 0:
            zero_chinese_body_count[dynasty] += 1
        spans = sentence_spans(poem["body"])
        sentence_totals[dynasty] += len(spans)
        matches, context_exclusions = scan_text(poem["body"], buckets)
        for start, end, word, rule_id in context_exclusions:
            context_exclusion_counts[rule_id] += 1
            if len(context_exclusion_examples[rule_id]) < 5:
                context_exclusion_examples[rule_id].append(
                    exclusion_example(poem, record_index, start, end, word, rule_id)
                )
        poem_counts = Counter(word for _, _, word in matches)
        dynasty_chars[dynasty] += chars
        dynasty_word_hits[dynasty].update(poem_counts)
        if poem_counts:
            dynasty_poems_with_imagery[dynasty] += 1
        category_counts = Counter()
        for word, count in poem_counts.items():
            category = term_info[word]["category"]
            category_counts[category] += count
            dynasty_word_poems[dynasty][word] += 1
        dynasty_category_hits[dynasty].update(category_counts)
        for category in category_counts:
            dynasty_category_poems[dynasty][category] += 1

        author_entry = author_stats.setdefault(
            author,
            {
                "dynasty": dynasty,
                "poems": 0,
                "chars": 0,
                "wordHits": Counter(),
                "wordWorks": Counter(),
            },
        )
        assert author_entry["dynasty"] == dynasty, f"作者跨唐宋分组：{author}"
        author_entry["poems"] += 1
        author_entry["chars"] += chars
        author_entry["wordHits"].update(poem_counts)
        for word in poem_counts:
            author_entry["wordWorks"][word] += 1

        genre_id = genre_for_poem(poem)
        genre_entry = genre_stats[genre_id][dynasty]
        genre_entry["poems"] += 1
        genre_entry["chars"] += chars
        genre_entry["poets"].add(author)
        genre_entry["wordHits"].update(poem_counts)
        for word in poem_counts:
            genre_entry["wordWorks"][word] += 1
        if poem_counts:
            genre_entry["poemsWithImagery"] += 1
        for category, count in category_counts.items():
            genre_entry["categoryHits"][category] += count
        for category in category_counts:
            genre_entry["categoryWorks"][category] += 1

        # ---- per-work dating (verified > curated > candidate), 25-year bins ----
        dating = dating_by_work_id.get(str(poem.get("work_id") or ""))
        if dating is not None and dating["inBinary"]:
            dated_period_counts[dynasty] += 1
            dated_tier_counts[dating["tier"]] += 1
            dated_chars_total += chars
            dated_works_total += 1
            dated_authors.add(author)
            if dating["binStart"] is not None:
                bin_entry = bin_stats.setdefault(
                    dating["binStart"],
                    {
                        "start": dating["binStart"],
                        "works": 0,
                        "chars": 0,
                        "authors": set(),
                        "tiers": Counter(),
                        "wordHits": Counter(),
                        "wordWorks": Counter(),
                    },
                )
                bin_entry["works"] += 1
                bin_entry["chars"] += chars
                bin_entry["authors"].add(author)
                bin_entry["tiers"][dating["tier"]] += 1
                bin_entry["wordHits"].update(poem_counts)
                for word in poem_counts:
                    bin_entry["wordWorks"][word] += 1

        # ---- sentence-level co-occurrence ----
        if matches:
            per_record_evidence = evidence_for_record(
                poem, record_index, matches, poem_counts, spans
            )
            for word, items in per_record_evidence.items():
                retain_evidence(evidence_candidates[word], items)
            for span_start, span_end, word_set in sentence_word_sets(spans, matches):
                for word in word_set:
                    sentence_word_counter[dynasty][word] += 1
                if len(word_set) >= 2:
                    sentences_with_pair[dynasty] += 1
                    ordered = sorted(word_set)
                    for left, right in combinations(ordered, 2):
                        pair_counter[dynasty][(left, right)] += 1
                        examples = pair_examples[(left, right)]
                        if sum(1 for item in examples if item[0] == dynasty) < 3:
                            examples.append((dynasty, record_index, span_start, span_end))

    assert sum(dynasty_poem_counts[dynasty] for dynasty in DYNASTIES) == len(poems)
    assert sum(dynasty_chars.values()) > 0, "全作品分析语料没有可计数字符"
    for dynasty in DYNASTIES:
        assert sum(dynasty_word_hits[dynasty].values()) == sum(
            dynasty_category_hits[dynasty].values()
        )
    assert set(context_exclusion_counts) == {item["id"] for item in CONTEXT_RULE_DEFS}
    # Representative true imagery must survive the finite disambiguation rules.
    assert context_exclusion_rule("山寺月中寻桂子", 2, 3, "月") is None
    assert context_exclusion_rule("今人不见古时月", 6, 7, "月") is None
    assert context_exclusion_rule("开帷月初吐", 2, 3, "月") is None
    assert context_exclusion_rule("身与波上月", 4, 5, "月") is None
    assert context_exclusion_rule("片帆浑是月", 4, 5, "月") is None
    assert context_exclusion_rule("持酒劝云云且住", 3, 4, "云") is None
    assert context_exclusion_rule("八月秋高风怒号", 4, 5, "风") is None
    assert context_exclusion_rule("青松阅世风霜古", 4, 5, "风") is None

    # genre totals must tile the binary corpus exactly
    assert sum(
        genre_stats[genre_id][dynasty]["poems"]
        for genre_id, _l, _d in GENRE_DEFS
        for dynasty in DYNASTIES
    ) == len(poems)
    assert sum(
        genre_stats[genre_id][dynasty]["chars"]
        for genre_id, _l, _d in GENRE_DEFS
        for dynasty in DYNASTIES
    ) == sum(dynasty_chars.values())

    combined_word_hits = dynasty_word_hits["唐"] + dynasty_word_hits["宋"]
    ranked_words = sorted(words, key=lambda word: (-combined_word_hits[word], word))

    # ---- author-equal weighting ----
    dynasty_author_lists = {
        dynasty: sorted(
            [
                author
                for author, entry in author_stats.items()
                if entry["dynasty"] == dynasty and entry["chars"] > 0
            ]
        )
        for dynasty in DYNASTIES
    }

    def author_word_rate(author: str, word: str) -> float:
        entry = author_stats[author]
        return entry["wordHits"][word] * 10000 / entry["chars"]

    author_equal_words: dict[str, dict] = {}
    for word in words:
        sides = {}
        for dynasty in DYNASTIES:
            authors = dynasty_author_lists[dynasty]
            rates = [author_word_rate(author, word) for author in authors]
            sides["tang" if dynasty == "唐" else "song"] = {
                "meanRate": round(sum(rates) / len(rates), 4) if rates else 0.0,
                "authors": len(authors),
            }
        author_equal_words[word] = {
            "tang": sides["tang"],
            "song": sides["song"],
            "deltaSongMinusTang": round(sides["song"]["meanRate"] - sides["tang"]["meanRate"], 4),
        }
    author_equal_overall = {}
    for dynasty in DYNASTIES:
        authors = dynasty_author_lists[dynasty]
        rates = [
            author_stats[author]["wordHits"].total() * 10000 / author_stats[author]["chars"]
            for author in authors
        ]
        author_equal_overall["tang" if dynasty == "唐" else "song"] = {
            "meanRate": round(sum(rates) / len(rates), 4) if rates else 0.0,
            "medianRate": round(standard_median(rates), 4),
            "authors": len(authors),
        }

    # ---- leave-one-author-out robustness ----
    def loo_report(
        total_tang: float,
        total_song: float,
        char_tang: int,
        char_song: int,
        author_hits,
        eq: dict | None = None,
        base_eq_gap: float | None = None,
    ) -> dict:
        base_gap = total_song * 10000 / char_song - total_tang * 10000 / char_tang
        gaps = []
        flips = []
        eq_gaps = []
        eq_flips = []
        for author, entry in sorted(author_stats.items()):
            hits = author_hits(author)
            if entry["dynasty"] == "唐":
                tang_h, tang_c = total_tang - hits, char_tang - entry["chars"]
                song_h, song_c = total_song, char_song
            else:
                tang_h, tang_c = total_tang, char_tang
                song_h, song_c = total_song - hits, char_song - entry["chars"]
            if tang_c <= 0 or song_c <= 0:
                continue
            gap = song_h * 10000 / song_c - tang_h * 10000 / tang_c
            gaps.append(gap)
            if (gap > 0) != (base_gap > 0):
                flips.append(author)
            if eq is not None:
                dynasty = entry["dynasty"]
                other = "宋" if dynasty == "唐" else "唐"
                rate_a = eq["rates"][author]
                mean_self = (eq["sums"][dynasty] - rate_a) / (eq["ns"][dynasty] - 1)
                mean_other = eq["sums"][other] / eq["ns"][other]
                eq_gap = mean_other - mean_self if dynasty == "唐" else mean_self - mean_other
                eq_gaps.append(eq_gap)
                if (eq_gap > 0) != (base_eq_gap > 0):
                    eq_flips.append(author)
        report = {
            "baseGap": round(base_gap, 4),
            "looMin": round(min(gaps), 4) if gaps else None,
            "looMax": round(max(gaps), 4) if gaps else None,
            "flips": sorted(flips),
        }
        if eq is not None:
            report["authorEqualBaseGap"] = round(base_eq_gap, 4)
            report["authorEqualLooMin"] = round(min(eq_gaps), 4) if eq_gaps else None
            report["authorEqualLooMax"] = round(max(eq_gaps), 4) if eq_gaps else None
            report["authorEqualFlips"] = sorted(eq_flips)
        return report

    def eq_from_values(rates_by_author: dict[str, float], sums: dict[str, float], ns: dict[str, int]) -> dict:
        return {"rates": rates_by_author, "sums": sums, "ns": ns}

    overall_eq_values = {}
    overall_eq_sums = {}
    overall_eq_ns = {}
    for dynasty in DYNASTIES:
        authors = dynasty_author_lists[dynasty]
        values = [
            author_stats[author]["wordHits"].total() * 10000 / author_stats[author]["chars"]
            for author in authors
        ]
        overall_eq_values.update(zip(authors, values))
        overall_eq_sums[dynasty] = sum(values)
        overall_eq_ns[dynasty] = len(values)
    overall_eq = eq_from_values(overall_eq_values, overall_eq_sums, overall_eq_ns)
    overall_base_eq_gap = overall_eq_sums["宋"] / overall_eq_ns["宋"] - overall_eq_sums["唐"] / overall_eq_ns["唐"]

    robustness_overall = loo_report(
        sum(dynasty_word_hits["唐"].values()),
        sum(dynasty_word_hits["宋"].values()),
        dynasty_chars["唐"],
        dynasty_chars["宋"],
        lambda author: author_stats[author]["wordHits"].total(),
        eq=overall_eq,
        base_eq_gap=overall_base_eq_gap,
    )

    robustness_words = {}
    for word in words:
        word_eq_values = {}
        word_eq_sums = {}
        word_eq_ns = {}
        for dynasty in DYNASTIES:
            authors = dynasty_author_lists[dynasty]
            values = [author_word_rate(author, word) for author in authors]
            word_eq_values.update(zip(authors, values))
            word_eq_sums[dynasty] = sum(values)
            word_eq_ns[dynasty] = len(values)
        base = word_eq_sums["宋"] / word_eq_ns["宋"] - word_eq_sums["唐"] / word_eq_ns["唐"]
        robustness_words[word] = loo_report(
            dynasty_word_hits["唐"][word],
            dynasty_word_hits["宋"][word],
            dynasty_chars["唐"],
            dynasty_chars["宋"],
            lambda author, word=word: author_stats[author]["wordHits"][word],
            eq=eq_from_values(word_eq_values, word_eq_sums, word_eq_ns),
            base_eq_gap=base,
        )
    robustness_categories = {}
    for category in category_order:
        tang_hits = sum(dynasty_word_hits["唐"][word] for word in category_words[category])
        song_hits = sum(dynasty_word_hits["宋"][word] for word in category_words[category])
        cat_eq_values = {}
        cat_eq_sums = {}
        cat_eq_ns = {}
        for dynasty in DYNASTIES:
            authors = dynasty_author_lists[dynasty]
            values = [
                sum(author_stats[author]["wordHits"][word] for word in category_words[category])
                * 10000
                / author_stats[author]["chars"]
                for author in authors
            ]
            cat_eq_values.update(zip(authors, values))
            cat_eq_sums[dynasty] = sum(values)
            cat_eq_ns[dynasty] = len(values)
        base = cat_eq_sums["宋"] / cat_eq_ns["宋"] - cat_eq_sums["唐"] / cat_eq_ns["唐"]
        robustness_categories[category] = loo_report(
            tang_hits,
            song_hits,
            dynasty_chars["唐"],
            dynasty_chars["宋"],
            lambda author, category=category: sum(
                author_stats[author]["wordHits"][word] for word in category_words[category]
            ),
            eq=eq_from_values(cat_eq_values, cat_eq_sums, cat_eq_ns),
            base_eq_gap=base,
        )

    # ---- exact additive author contribution decomposition ----
    def contribution_rows(word: str) -> dict:
        song_total_chars = dynasty_chars["宋"]
        tang_total_chars = dynasty_chars["唐"]
        song_parts = []
        tang_parts = []
        for author, entry in sorted(author_stats.items()):
            hits = entry["wordHits"][word]
            if entry["dynasty"] == "宋":
                contribution = hits * 10000 / song_total_chars
                song_parts.append(
                    {
                        "author": author,
                        "contribution": round(contribution, 4),
                        "hits": hits,
                        "charsShare": round(entry["chars"] / song_total_chars, 4),
                        "ownRate": round(hits * 10000 / entry["chars"], 4) if entry["chars"] else 0.0,
                    }
                )
            else:
                contribution = hits * 10000 / tang_total_chars
                tang_parts.append(
                    {
                        "author": author,
                        "contribution": round(contribution, 4),
                        "hits": hits,
                        "charsShare": round(entry["chars"] / tang_total_chars, 4),
                        "ownRate": round(hits * 10000 / entry["chars"], 4) if entry["chars"] else 0.0,
                    }
                )
        song_parts.sort(key=lambda row: (-row["contribution"], row["author"]))
        tang_parts.sort(key=lambda row: (-row["contribution"], row["author"]))
        gap = sum(row["contribution"] for row in song_parts) - sum(
            row["contribution"] for row in tang_parts
        )
        expected_gap = (
            dynasty_word_hits["宋"][word] * 10000 / song_total_chars
            - dynasty_word_hits["唐"][word] * 10000 / tang_total_chars
        )
        assert abs(gap - expected_gap) < 0.01, f"贡献分解不闭合：{word}"
        return {
            "word": word,
            "category": word_category[word],
            "gap": round(expected_gap, 4),
            "songTotal": round(sum(row["contribution"] for row in song_parts), 4),
            "tangTotal": round(-sum(row["contribution"] for row in tang_parts), 4),
            "song": song_parts[:6],
            "tang": tang_parts[:6],
        }

    # ---- word / category / aggregate stats ----
    word_stats = []
    word_stats_by_name = {}
    for word in ranked_words:
        tang = word_side_stats(
            "唐", word, dynasty_chars, dynasty_poem_counts, dynasty_word_hits, dynasty_word_poems
        )
        song = word_side_stats(
            "宋", word, dynasty_chars, dynasty_poem_counts, dynasty_word_hits, dynasty_word_poems
        )
        delta = round(song["ratePer10k"] - tang["ratePer10k"], 4)
        row = {
            "word": word,
            "category": term_info[word]["category"],
            "singleCharacter": len(word) == 1,
            "combinedRawHits": combined_word_hits[word],
            "combinedPoemsWithHit": dynasty_word_poems["唐"][word]
            + dynasty_word_poems["宋"][word],
            "tang": tang,
            "song": song,
            "deltaSongMinusTang": delta,
            "absoluteDelta": round(abs(delta), 4),
            "higherIn": "宋" if delta > 0 else ("唐" if delta < 0 else "持平"),
            "authorEqual": author_equal_words[word],
        }
        word_stats.append(row)
        word_stats_by_name[word] = row

    comparison_words = ranked_words[:14]
    frequent_pool = ranked_words[:24]
    contrast_words = sorted(
        frequent_pool,
        key=lambda word: (-word_stats_by_name[word]["absoluteDelta"], word),
    )[:12]
    top_contrasts = []
    for rank, word in enumerate(contrast_words, 1):
        row = dict(word_stats_by_name[word])
        row["rank"] = rank
        row["selectionRule"] = "全库总命中前24词中，按唐宋每万汉字率差绝对值排序"
        top_contrasts.append(row)

    category_stats = []
    for category in category_order:
        sides = {}
        for dynasty in DYNASTIES:
            raw = dynasty_category_hits[dynasty][category]
            sides["tang" if dynasty == "唐" else "song"] = {
                "rawHits": raw,
                "ratePer10k": normalized_rate(raw, dynasty_chars[dynasty]),
                "chineseCharDenominator": dynasty_chars[dynasty],
                "poemRecords": dynasty_poem_counts[dynasty],
                "poemsWithHit": dynasty_category_poems[dynasty][category],
            }
        category_stats.append(
            {
                "category": category,
                "color": CATEGORY_COLORS[category],
                "termCount": category_term_counts[category],
                **sides,
            }
        )

    dynasty_aggregates = {}
    for dynasty in DYNASTIES:
        raw_hits = sum(dynasty_word_hits[dynasty].values())
        dynasty_aggregates[dynasty] = {
            "poemRecords": dynasty_poem_counts[dynasty],
            "poets": len(dynasty_authors[dynasty]),
            "chineseChars": dynasty_chars[dynasty],
            "rawHits": raw_hits,
            "ratePer10k": normalized_rate(raw_hits, dynasty_chars[dynasty]),
            "poemsWithImagery": dynasty_poems_with_imagery[dynasty],
            "termsObserved": sum(dynasty_word_hits[dynasty][word] > 0 for word in words),
            "authorEqualRatePer10k": author_equal_overall[
                "tang" if dynasty == "唐" else "song"
            ]["meanRate"],
            "sentences": sentence_totals[dynasty],
        }

    # ---- chronology bins ----
    bin_list = []
    trend_words: list[str] = []
    for row in top_contrasts:
        if row["deltaSongMinusTang"] > 0 and len(trend_words) < 4:
            trend_words.append(row["word"])
    for row in top_contrasts:
        if row["deltaSongMinusTang"] < 0 and len(trend_words) < 6:
            trend_words.append(row["word"])
    for word in ("月", "山", "酒", "雁"):
        if word in term_info and word not in trend_words and len(trend_words) < TREND_WORD_COUNT:
            trend_words.append(word)
    for word in ranked_words:
        if len(trend_words) >= TREND_WORD_COUNT:
            break
        if word not in trend_words:
            trend_words.append(word)
    assert len(trend_words) == TREND_WORD_COUNT

    for bin_start in sorted(bin_stats):
        entry = bin_stats[bin_start]
        supported = entry["works"] >= MIN_BIN_WORKS and entry["chars"] >= MIN_BIN_CHARS
        word_payload = {}
        for word in words:
            hits = entry["wordHits"][word]
            if word in trend_words:
                low, high = poisson_ci(hits, entry["chars"]) if entry["chars"] else (0.0, 0.0)
                word_payload[word] = {
                    "hits": hits,
                    "works": entry["wordWorks"][word],
                    "ratePer10k": round(hits * 10000 / entry["chars"], 4) if entry["chars"] else 0.0,
                    "ciLow": low,
                    "ciHigh": high,
                    "supported": supported and hits >= MIN_WORD_BIN_HITS,
                }
        bin_list.append(
            {
                "start": bin_start,
                "end": bin_start + BIN_WIDTH - 1,
                "works": entry["works"],
                "chars": entry["chars"],
                "authors": len(entry["authors"]),
                "tiers": dict(sorted(entry["tiers"].items())),
                "trend": {word: word_payload[word] for word in trend_words},
            }
        )
    supported_bin_count = sum(
        1
        for item in bin_list
        if item["works"] >= MIN_BIN_WORKS and item["chars"] >= MIN_BIN_CHARS
    )

    dating_coverage = {
        "datedWorks": dated_works_total,
        "binaryWorks": len(poems),
        "workCoverage": round(dated_works_total / len(poems), 4),
        "datedChars": dated_chars_total,
        "totalChars": sum(dynasty_chars.values()),
        "charCoverage": round(dated_chars_total / sum(dynasty_chars.values()), 4),
        "byDynasty": {
            dynasty: {
                "works": dated_period_counts[dynasty],
                "poemRecords": dynasty_poem_counts[dynasty],
                "workCoverage": round(dated_period_counts[dynasty] / dynasty_poem_counts[dynasty], 4),
            }
            for dynasty in DYNASTIES
        },
        "byTier": dict(sorted(dated_tier_counts.items())),
        "datedAuthors": len(dated_authors),
        "totalAuthors": len(author_stats),
        "bins": len(bin_list),
        "supportedBins": supported_bin_count,
    }
    artifact_binary_tiers = Counter(row["tier"] for row in dating_works if row["inBinary"])
    assert sum(row["inBinary"] for row in dating_works) == dating_coverage["datedWorks"]
    assert sum(item["works"] for item in bin_list) == dating_coverage["datedWorks"]
    assert dict(sorted(artifact_binary_tiers.items())) == dating_coverage["byTier"]
    assert sum(dating_coverage["byTier"].values()) == dating_coverage["datedWorks"]

    # ---- genre strata ----
    genre_groups = []
    genre_group_keys = (
        ("poetry", "唐", "poetryTang"),
        ("poetry", "宋", "poetrySong"),
        ("ci", "唐", "ciTang"),
        ("ci", "宋", "ciSong"),
        ("unmarked", "唐", "unmarkedTang"),
        ("unmarked", "宋", "unmarkedSong"),
    )
    genre_labels = {genre_id: label for genre_id, label, _d in GENRE_DEFS}
    for genre_id, dynasty, key in genre_group_keys:
        entry = genre_stats[genre_id][dynasty]
        genre_groups.append(
            {
                "key": key,
                "genre": genre_id,
                "genreLabel": genre_labels[genre_id],
                "dynasty": dynasty,
                "poems": entry["poems"],
                "chars": entry["chars"],
                "poets": len(entry["poets"]),
                "rawHits": sum(entry["wordHits"].values()),
                "ratePer10k": round(sum(entry["wordHits"].values()) * 10000 / entry["chars"], 4)
                if entry["chars"]
                else 0.0,
                "poemsWithImagery": entry["poemsWithImagery"],
                "empty": entry["poems"] == 0,
            }
        )
    genre_word_stats = []
    for word in ranked_words:
        row = {"word": word, "category": word_category[word]}
        for _genre_id, _dynasty, key in genre_group_keys:
            entry = genre_stats[_genre_id][_dynasty]
            chars = entry["chars"]
            row[key] = {
                "hits": entry["wordHits"][word],
                "works": entry["wordWorks"][word],
                "ratePer10k": round(entry["wordHits"][word] * 10000 / chars, 4) if chars else 0.0,
            }
        poetry_song = row["poetrySong"]["ratePer10k"]
        ci_song = row["ciSong"]["ratePer10k"]
        row["ciMinusPoetrySong"] = round(ci_song - poetry_song, 4)
        genre_word_stats.append(row)
    genre_word_stats_supported = [
        row
        for row in genre_word_stats
        if row["poetrySong"]["hits"] >= 30 and row["ciSong"]["hits"] >= 10
    ]
    genre_word_stats_supported.sort(key=lambda row: (-abs(row["ciMinusPoetrySong"]), row["word"]))
    genre_word_stats = genre_word_stats_supported[:14]
    genre_category_stats = []
    for category in category_order:
        row = {
            "category": category,
            "color": CATEGORY_COLORS[category],
            "termCount": category_term_counts[category],
        }
        for genre_id, dynasty, key in genre_group_keys:
            entry = genre_stats[genre_id][dynasty]
            hits = sum(
                entry["wordHits"][word] for word in category_words[category]
            )
            chars = entry["chars"]
            row[key] = {
                "hits": hits,
                "ratePer10k": round(hits * 10000 / chars, 4) if chars else 0.0,
            }
        genre_category_stats.append(row)

    # ---- sentence-level co-occurrence post-processing ----
    cooc_totals = {
        dynasty: {
            "sentences": sentence_totals[dynasty],
            "sentencesWithPair": sentences_with_pair[dynasty],
            "pairCount": sum(pair_counter[dynasty].values()),
        }
        for dynasty in DYNASTIES
    }
    stable_pairs = []
    divergent_pairs = []
    for pair in sorted(set(pair_counter["唐"]) | set(pair_counter["宋"])):
        tang_count = pair_counter["唐"][pair]
        song_count = pair_counter["宋"][pair]
        combined = tang_count + song_count
        stable_pairs.append((pair, tang_count, song_count, combined))
    stable_pairs.sort(key=lambda item: (-item[3], item[0]))
    stable_pairs_out = []
    for (left, right), tang_count, song_count, combined in stable_pairs:
        if tang_count < MIN_PAIR_SUPPORT or song_count < MIN_PAIR_SUPPORT:
            continue
        if len(stable_pairs_out) >= 12:
            break
        stable_pairs_out.append(
            {
                "pair": [left, right],
                "category": word_category[left],
                "tangCount": tang_count,
                "songCount": song_count,
            }
        )

    def sentence_rate(dynasty: str, word: str) -> float:
        total = sentence_totals[dynasty]
        return sentence_word_counter[dynasty][word] / total if total else 0.0

    for (left, right), tang_count, song_count, _combined in stable_pairs:
        if tang_count < MIN_PAIR_SUPPORT or song_count < MIN_PAIR_SUPPORT:
            continue
        tang_total = sentence_totals["唐"]
        song_total = sentence_totals["宋"]
        tang_lift = (tang_count / tang_total) / (
            sentence_rate("唐", left) * sentence_rate("唐", right)
        ) if tang_total else 0.0
        song_lift = (song_count / song_total) / (
            sentence_rate("宋", left) * sentence_rate("宋", right)
        ) if song_total else 0.0
        divergent_pairs.append(
            {
                "pair": [left, right],
                "category": word_category[left],
                "tangCount": tang_count,
                "songCount": song_count,
                "tangLift": round(tang_lift, 4),
                "songLift": round(song_lift, 4),
                "liftDelta": round(song_lift - tang_lift, 4),
            }
        )
    divergent_pairs.sort(key=lambda row: (-abs(row["liftDelta"]), row["pair"]))
    divergent_pairs = divergent_pairs[:16]

    def pair_quote(pair_key: tuple[str, str], dynasty: str, limit: int = 2) -> list[dict]:
        quotes = []
        for example_dynasty, record_index, span_start, span_end in pair_examples.get(pair_key, []):
            if example_dynasty != dynasty or len(quotes) >= limit:
                continue
            poem = poems[record_index]
            sentence = poem["body"][span_start:span_end]
            left, right = pair_key
            first_pos = sentence.find(left)
            if first_pos < 0:
                first_pos = sentence.find(right)
            if first_pos < 0:
                continue
            word_for_hits = left if sentence.find(left) >= 0 else right
            quotes.append(
                {
                    "title": poem.get("title") or "无题（上游未标）",
                    "poet": poem["author"],
                    "dynasty": poem.get("person_period") or poem["dynasty"],
                    "sentence": sentence,
                    "matchStart": first_pos,
                    "matchEnd": first_pos + len(word_for_hits),
                    "sentenceMatchCount": 1,
                    "poemWordHits": pair_counter[dynasty][pair_key],
                    "sourcePoemId": poem.get("canonical_gushiwen_id") or poem.get("source_poem_id", ""),
                    "canonicalMatch": bool(poem.get("canonical_match") or poem.get("source_poem_id")),
                    "workId": poem.get("work_id", ""),
                    "sourceUrl": poem.get("source_url", ""),
                    "pair": list(pair_key),
                }
            )
        return quotes

    cooc_evidence = {}
    for row in divergent_pairs[:10]:
        pair_key = tuple(row["pair"])
        cooc_evidence["+".join(row["pair"])] = {
            "tang": pair_quote(pair_key, "唐"),
            "song": pair_quote(pair_key, "宋"),
        }

    collocates = []
    for word in trend_words[:8]:
        tang_items = []
        song_items = []
        for (left, right), tang_count in pair_counter["唐"].items():
            if left == word:
                tang_items.append((right, tang_count))
            elif right == word:
                tang_items.append((left, tang_count))
        for (left, right), song_count in pair_counter["宋"].items():
            if left == word:
                song_items.append((right, song_count))
            elif right == word:
                song_items.append((left, song_count))
        tang_items.sort(key=lambda item: (-item[1], item[0]))
        song_items.sort(key=lambda item: (-item[1], item[0]))
        collocates.append(
            {
                "word": word,
                "category": word_category[word],
                "tang": [
                    {"word": item[0], "count": item[1]}
                    for item in tang_items[:8]
                    if item[1] >= MIN_COLLOCATE_COUNT
                ][:8],
                "song": [
                    {"word": item[0], "count": item[1]}
                    for item in song_items[:8]
                    if item[1] >= MIN_COLLOCATE_COUNT
                ][:8],
            }
        )

    # ---- headline conclusions (computed, never hand-written numbers) ----
    conclusions = []

    def fmt_int(value: int) -> str:
        return f"{value:,}"

    overall_gap = dynasty_aggregates["宋"]["ratePer10k"] - dynasty_aggregates["唐"]["ratePer10k"]
    overall_gap_eq = (
        author_equal_overall["song"]["meanRate"] - author_equal_overall["tang"]["meanRate"]
    )
    conclusions.append(
        {
            "id": "overall",
            "headline": (
                f"总体意象密度：宋每万字 {dynasty_aggregates['宋']['ratePer10k']:.2f} 次，"
                f"唐每万字 {dynasty_aggregates['唐']['ratePer10k']:.2f} 次"
                + (f"（宋高 {overall_gap:.2f}）" if overall_gap >= 0 else f"（唐高 {abs(overall_gap):.2f}）")
            ),
            "body": (
                f"口径：{fmt_int(len(poems))} 条唐宋正文、{fmt_int(sum(dynasty_chars.values()))} 个正文汉字、"
                f"160 个客观意象词的非重叠命中。作者等权（唐 {author_equal_overall['tang']['authors']} 人、"
                f"宋 {author_equal_overall['song']['authors']} 人，每人一篇率平均）后为宋 "
                f"{author_equal_overall['song']['meanRate']:.2f} vs 唐 {author_equal_overall['tang']['meanRate']:.2f}，"
                f"方向{'不变' if (overall_gap >= 0) == (overall_gap_eq >= 0) else '反转'}；"
                f"留一作者检验翻转 {len(robustness_overall['flips'])} 次（等权口径翻转 "
                f"{len(robustness_overall['authorEqualFlips'])} 次）。"
            ),
            "evidenceWord": comparison_words[0],
        }
    )
    top_song_word = max(word_stats, key=lambda row: (row["deltaSongMinusTang"], -row["combinedRawHits"]))
    top_tang_word = min(word_stats, key=lambda row: (row["deltaSongMinusTang"], -row["combinedRawHits"]))
    song_contrib = contribution_rows(top_song_word["word"])
    tang_contrib = contribution_rows(top_tang_word["word"])
    char_ratio = dynasty_chars["宋"] / dynasty_chars["唐"]

    def contrib_label(rows: dict) -> str:
        song_top = rows["song"][0] if rows["song"] else None
        tang_top = rows["tang"][0] if rows["tang"] else None
        parts = []
        if song_top:
            parts.append(f"宋侧最大推手{song_top['author']}（贡献 {song_top['contribution']:.2f}/万字，本人率 {song_top['ownRate']:.2f}）")
        if tang_top:
            parts.append(f"唐侧基数主要来自{tang_top['author']}（贡献 {tang_top['contribution']:.2f}/万字）")
        return "；".join(parts)

    conclusions.append(
        {
            "id": "song-push",
            "headline": (
                f"宋侧最强增量词「{top_song_word['word']}」：唐 {top_song_word['tang']['ratePer10k']:.2f} → "
                f"宋 {top_song_word['song']['ratePer10k']:.2f} /万字（率差 {top_song_word['deltaSongMinusTang']:+.2f}，"
                f"原始次数 {top_song_word['song']['rawHits'] - top_song_word['tang']['rawHits']:+,}）"
            ),
            "body": (
                f"作品命中率从唐 {top_song_word['tang']['poemHitRate'] * 100:.1f}% 升到宋 {top_song_word['song']['poemHitRate'] * 100:.1f}%。"
                f"逐作者精确分解（两侧全部作者贡献之和恰等于率差 {song_contrib['gap']:+.2f}/万字）：{contrib_label(song_contrib)}。"
                f"留一作者检验翻转 {len(robustness_words[top_song_word['word']]['flips'])} 次，作者等权后率差仍为 "
                f"{author_equal_words[top_song_word['word']]['deltaSongMinusTang']:+.2f}/万字。"
            ),
            "evidenceWord": top_song_word["word"],
        }
    )
    conclusions.append(
        {
            "id": "tang-push",
            "headline": (
                f"唐侧最强存量词「{top_tang_word['word']}」：唐 {top_tang_word['tang']['ratePer10k']:.2f} /万字，"
                f"宋降至 {top_tang_word['song']['ratePer10k']:.2f}（率差 {top_tang_word['deltaSongMinusTang']:+.2f}）"
            ),
            "body": (
                f"作品命中率从唐 {top_tang_word['tang']['poemHitRate'] * 100:.1f}% 降到宋 {top_tang_word['song']['poemHitRate'] * 100:.1f}%；"
                f"宋正文汉字为唐的 {char_ratio:.2f} 倍，因此「{top_tang_word['word']}」在宋的原始次数仍多 "
                f"{top_tang_word['song']['rawHits'] - top_tang_word['tang']['rawHits']:+,} 次，但密度大幅下降——只看原始次数会误读方向。"
                f"逐作者分解（率差 {tang_contrib['gap']:+.2f}/万字）：{contrib_label(tang_contrib)}。"
                f"留一作者检验翻转 {len(robustness_words[top_tang_word['word']]['flips'])} 次，作者等权后率差为 "
                f"{author_equal_words[top_tang_word['word']]['deltaSongMinusTang']:+.2f}/万字。"
            ),
            "evidenceWord": top_tang_word["word"],
        }
    )
    dated_note = (
        f"逐篇系年覆盖 {fmt_int(dating_coverage['datedWorks'])} / {fmt_int(len(poems))} 条作品"
        f"（{dating_coverage['workCoverage'] * 100:.1f}%）、正文 {dating_coverage['charCoverage'] * 100:.1f}%；"
        f"其中进入二分的人工复核 {dating_coverage['byTier'].get('verified-B', 0)} 条、"
        f"六诗人CSV候选 {dating_coverage['byTier'].get('curated-B', 0) + dating_coverage['byTier'].get('curated-C', 0)} 条、"
        f"搜韵候选 {dating_coverage['byTier'].get('candidate-B', 0) + dating_coverage['byTier'].get('candidate-C', 0)} 条。"
    )
    conclusions.append(
        {
            "id": "chronology",
            "headline": (
                f"年代演变基于 {fmt_int(dating_coverage['datedWorks'])} 条有系年作品"
                f"（覆盖 {dating_coverage['workCoverage'] * 100:.1f}%），"
                f"{supported_bin_count} 个 25 年箱满足最低样本量"
            ),
            "body": dated_note
            + f"趋势只对每箱≥{MIN_BIN_WORKS}首、≥{MIN_BIN_CHARS}字、单词≥{MIN_WORD_BIN_HITS}命的箱画点；"
            "五代时段（约900–975）没有时间箱达到上述展示阈值，不画趋势。各词趋势与95%置信带见年代轴。",
            "evidenceWord": trend_words[0],
        }
    )
    genre_ci = genre_stats["ci"]["宋"]
    conclusions.append(
        {
            "id": "genre",
            "headline": (
                f"体裁分层：诗（上游诗库）{fmt_int(genre_stats['poetry']['唐']['poems'] + genre_stats['poetry']['宋']['poems'])} 条、"
                f"词（全宋词上游）{fmt_int(genre_ci['poems'])} 条、未标（规范库）"
                f"{fmt_int(genre_stats['unmarked']['唐']['poems'] + genre_stats['unmarked']['宋']['poems'])} 条"
            ),
            "body": (
                f"词体裁在上游只来自全宋词，唐侧样本为 {genre_stats['ci']['唐']['poems']} 条，"
                "因此本页不做“词的唐宋对比”，只做宋内部诗 vs 词对比与未标层的唐宋复算；"
                f"词宋侧意象密度 {round(sum(genre_ci['wordHits'].values()) * 10000 / genre_ci['chars'], 2)} /万字"
                f"（{fmt_int(genre_ci['chars'])} 字）。"
            ),
            "evidenceWord": genre_word_stats[0]["word"] if genre_word_stats else comparison_words[0],
        }
    )

    # ---- readable Tang -> Song interpretation (all statements remain computed) ----
    # The charts above expose the evidence, while this block answers the visitor's
    # actual question in prose: what changed, which corpus components explain the
    # observed gap, and where the data cannot support a causal claim.
    overall_change_pct = overall_gap / dynasty_aggregates["唐"]["ratePer10k"] * 100
    category_shift_rows = [
        {
            "category": row["category"],
            "delta": row["song"]["ratePer10k"] - row["tang"]["ratePer10k"],
            "authorEqualDelta": robustness_categories[row["category"]]["authorEqualBaseGap"],
        }
        for row in category_stats
    ]
    category_risers = sorted(category_shift_rows, key=lambda row: (-row["delta"], row["category"]))[:3]
    category_fallers = sorted(category_shift_rows, key=lambda row: (row["delta"], row["category"]))[:3]
    word_risers = sorted(word_stats, key=lambda row: (-row["deltaSongMinusTang"], row["word"]))[:3]
    word_fallers = sorted(word_stats, key=lambda row: (row["deltaSongMinusTang"], row["word"]))[:3]
    poetry_tang = genre_stats["poetry"]["唐"]
    poetry_song = genre_stats["poetry"]["宋"]
    poetry_tang_rate = sum(poetry_tang["wordHits"].values()) * 10000 / poetry_tang["chars"]
    poetry_song_rate = sum(poetry_song["wordHits"].values()) * 10000 / poetry_song["chars"]
    ci_song_rate = sum(genre_ci["wordHits"].values()) * 10000 / genre_ci["chars"]
    ci_song_char_share = genre_ci["chars"] / dynasty_chars["宋"]
    supported_edge_bins = [
        row
        for row in bin_list
        if row["trend"]["雨"]["supported"] and row["trend"]["云"]["supported"]
    ]
    chronology_early = supported_edge_bins[0]
    chronology_late = supported_edge_bins[-1]
    cooc_song_pair = max(divergent_pairs, key=lambda row: row["liftDelta"])
    cooc_tang_pair = min(divergent_pairs, key=lambda row: row["liftDelta"])

    def shift_labels(rows: list[dict]) -> str:
        return "、".join(f"{row['category']} {row['delta']:+.2f}" for row in rows)

    def word_shift_labels(rows: list[dict]) -> str:
        return "、".join(f"{row['word']} {row['deltaSongMinusTang']:+.2f}" for row in rows)

    change_analysis = {
        "title": "唐 → 宋：总量略降，内部结构明显分化",
        "thesis": (
            f"160 个客观意象词的总体密度从唐 {dynasty_aggregates['唐']['ratePer10k']:.2f} 降到宋 "
            f"{dynasty_aggregates['宋']['ratePer10k']:.2f} 次/万字，变化 {overall_change_pct:+.1f}%。"
            "不能把它简化成‘宋人少写意象’：类别、词项、体裁和搭配关系都在重新分配。"
        ),
        "findings": [
            {
                "id": "category-shift",
                "eyebrow": "类别重心",
                "title": "最稳定的下降发生在建筑、地理与走兽",
                "body": (
                    f"语料加权下降最多的是 {shift_labels(category_fallers)} 次/万字，"
                    "作者等权后方向仍全部为负。天象与器物虽在语料加权口径上分别 "
                    f"{category_risers[0]['delta']:+.2f}、{category_risers[1]['delta']:+.2f}，"
                    f"作者等权后却变为 {category_risers[0]['authorEqualDelta']:+.2f}、"
                    f"{category_risers[1]['authorEqualDelta']:+.2f}；它们的表面增量与作者产量构成有关。"
                ),
                "evidenceWords": [top_song_word["word"], top_tang_word["word"]],
            },
            {
                "id": "word-shift",
                "eyebrow": "关键词迁移",
                "title": "宋侧‘雨、酒、湖’增密，唐侧‘马、云、城’更突出",
                "body": (
                    f"160 词中率差最大的宋侧词项为 {word_shift_labels(word_risers)}；"
                    f"唐侧词项为 {word_shift_labels(word_fallers)}（均为宋−唐，每万字）。"
                    "这是本页最直接的‘意象潮汐’：不是原始次数多少，而是单位正文中的使用密度改变。"
                ),
                "evidenceWords": [row["word"] for row in word_risers[:2] + word_fallers[:2]],
            },
            {
                "id": "genre-driver",
                "eyebrow": "体裁解释",
                "title": "高密度宋词缩小了唐宋总体差距",
                "body": (
                    f"只看上游明确标为诗的作品，唐为 {poetry_tang_rate:.2f}、宋为 {poetry_song_rate:.2f} 次/万字，"
                    f"差 {poetry_song_rate - poetry_tang_rate:+.2f}；宋词为 {ci_song_rate:.2f} 次/万字，"
                    f"比宋诗高 {ci_song_rate - poetry_song_rate:+.2f}，占宋侧正文汉字 {ci_song_char_share * 100:.1f}%。"
                    "所以体裁混合会把宋侧总体率向上拉，但因唐侧没有同口径词样本，本页不把它解释成跨朝代的词体因果。"
                ),
                "evidenceWords": [genre_word_stats[0]["word"] if genre_word_stats else top_song_word["word"]],
            },
            {
                "id": "author-driver",
                "eyebrow": "作者解释",
                "title": "贡献集中于大样本作者，但方向不依赖任何单一诗人",
                "body": (
                    f"‘{top_song_word['word']}’宋侧最大贡献者是 {song_contrib['song'][0]['author']}，"
                    f"‘{top_tang_word['word']}’唐侧最大基数贡献者是 {tang_contrib['tang'][0]['author']}；"
                    f"但总体留一作者检验翻转 {len(robustness_overall['flips'])} 次，两个代表词也都是 0 次。"
                    "这说明作者产量影响差值大小，却不足以单独制造结论方向。"
                ),
                "evidenceWords": [top_song_word["word"], top_tang_word["word"]],
            },
            {
                "id": "chronology-signal",
                "eyebrow": "系年子样本",
                "title": "‘雨’走高、‘云’走低只是年代信号，不是单调历史曲线",
                "body": (
                    f"在同时满足阈值的最早箱 {chronology_early['start']}–{chronology_early['end']} 与最晚箱 "
                    f"{chronology_late['start']}–{chronology_late['end']} 中，‘雨’从 "
                    f"{chronology_early['trend']['雨']['ratePer10k']:.2f} 到 {chronology_late['trend']['雨']['ratePer10k']:.2f}，"
                    f"‘云’从 {chronology_early['trend']['云']['ratePer10k']:.2f} 到 "
                    f"{chronology_late['trend']['云']['ratePer10k']:.2f} 次/万字。中间箱并非单调，"
                    "这里只把它作为系年子样本中的阶段信号。"
                ),
                "evidenceWords": ["雨", "云"],
            },
            {
                "id": "context-shift",
                "eyebrow": "搭配关系",
                "title": "变化不只在单词频率，也发生在意象组合方式",
                "body": (
                    f"‘{'—'.join(cooc_song_pair['pair'])}’的共现 lift 从唐 {cooc_song_pair['tangLift']:.2f} 升到宋 "
                    f"{cooc_song_pair['songLift']:.2f}；‘{'—'.join(cooc_tang_pair['pair'])}’则从唐 "
                    f"{cooc_tang_pair['tangLift']:.2f} 降到宋 {cooc_tang_pair['songLift']:.2f}。"
                    "两侧均达到最低支持数，说明同一词库在唐宋形成了不同的句内组合网络。"
                ),
                "evidenceWords": list(dict.fromkeys(cooc_song_pair["pair"] + cooc_tang_pair["pair"])),
            },
        ],
        "boundary": (
            f"年代轴只覆盖 {dating_coverage['datedWorks']:,} 条作品（{dating_coverage['workCoverage'] * 100:.1f}%）和 "
            f"{dating_coverage['charCoverage'] * 100:.1f}% 的正文汉字，且候选系年占多数。"
            "因此它适合定位某些词在哪些 25 年箱增减，不足以证明战争、制度或审美观念直接造成了变化；"
            "页面中的‘原因’只指作者构成、体裁构成与词项结构这些可计算驱动。"
        ),
    }
    assert len(change_analysis["findings"]) == 6
    assert all(
        word in word_category
        for finding in change_analysis["findings"]
        for word in finding["evidenceWords"]
    )
    assert chronology_early["trend"]["雨"]["supported"] and chronology_late["trend"]["云"]["supported"]
    assert "不足以证明" in change_analysis["boundary"]

    analysis_by_canonical_id_size = len(analysis_by_canonical_id)

    # ---- journey / historical lens (unchanged contract) ----
    all_nodes = []
    for poet_record in journeys["poets"]:
        for node in poet_record["nodes"]:
            enriched = dict(node)
            enriched["poet"] = poet_record["poet"]
            enriched["dynasty"] = poet_record["dynasty"]
            all_nodes.append(enriched)
    assert len(all_nodes) == 38, "审核行旅数据应为 38 个节点"
    assert all(node["source_level"] in {"A", "B", "C"} for node in all_nodes)
    assert all(node["linked_poem"]["relation_level"] in {"A", "B", "C"} for node in all_nodes)

    chapter_members: dict[str, list[dict]] = {}
    assigned_ids = set()
    for chapter_id, start_year, end_year, _ in CHAPTER_DEFS:
        members = sorted(
            [node for node in all_nodes if start_year <= node["year"] <= end_year],
            key=lambda node: (node["year"], node["poet"], node.get("route_order", 0), node["id"]),
        )
        chapter_members[chapter_id] = members
        for node in members:
            assert node["id"] not in assigned_ids
            assigned_ids.add(node["id"])
    assert tuple(len(chapter_members[item[0]]) for item in CHAPTER_DEFS) == EXPECTED_CHAPTER_COUNTS
    outside_nodes = sorted(
        [node for node in all_nodes if node["id"] not in assigned_ids],
        key=lambda node: (node["year"], node["poet"], node["id"]),
    )
    assert [(node["year"], node["poet"]) for node in outside_nodes] == [(766, "杜甫"), (768, "杜甫")]

    def linked_record(node: dict) -> tuple[int, dict, dict]:
        key = (node["poet"], node["linked_poem"]["title"])
        candidates = canonical_poem_index.get(key, [])
        assert len(candidates) == 1, f"审核节点关联诗未唯一命中规范语料：{key} -> {len(candidates)}"
        record_index, poem = candidates[0]
        if record_index not in canonical_scan_cache:
            matches, exclusions = scan_text(poem["body"], buckets)
            counts = Counter(word for _, _, word in matches)
            canonical_scan_cache[record_index] = {
                "chars": chinese_char_count(poem["body"]),
                "matches": matches,
                "counts": counts,
                "contextExclusionCount": len(exclusions),
            }
            canonical_record_evidence[record_index] = evidence_for_record(
                poem, record_index, matches, counts
            )
        return record_index, poem, canonical_scan_cache[record_index]

    def node_public_record(node: dict) -> dict:
        record_index, poem, scan = linked_record(node)
        hits = sorted(scan["counts"].items(), key=lambda item: (-item[1], item[0]))
        node_evidence = []
        for word, items in sorted(canonical_record_evidence.get(record_index, {}).items()):
            for item in dedupe_evidence(items)[:1]:
                node_evidence.append(public_evidence(item))
        node_evidence.sort(key=lambda item: (-scan["counts"][item["sentence"][item["matchStart"] : item["matchEnd"]]], item["sentence"]))
        return {
            "id": node["id"],
            "year": node["year"],
            "yearLabel": node["year_label"],
            "yearPrecision": node["year_precision"],
            "poet": node["poet"],
            "dynasty": node["dynasty"],
            "placeHistorical": node["place_historical"],
            "placeModern": node["place_modern"],
            "longitude": node["longitude"],
            "latitude": node["latitude"],
            "event": node["event"],
            "sourceGrade": node["source_level"],
            "sourceName": node["source_name"],
            "sourceUrl": node["source_url"],
            "sourceNote": node.get("note", ""),
            "linkedPoem": {
                "title": node["linked_poem"]["title"],
                "relation": node["linked_poem"]["relation"],
                "relationGrade": node["linked_poem"]["relation_level"],
                "sourcePoemId": poem.get("source_poem_id", ""),
                "canonicalGushiwenId": poem.get("canonical_gushiwen_id", ""),
                "workId": poem.get("work_id", ""),
                "sourceUrl": poem.get("source_url", ""),
            },
            "body": poem["body"],
            "chineseChars": scan["chars"],
            "rawHits": sum(scan["counts"].values()),
            "hits": [{"word": word, "rawHits": count} for word, count in hits],
            "evidence": node_evidence,
            "recordIndex": record_index,
        }

    chapters = []
    chapter_evidence_candidates: dict[str, dict[str, list[dict]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for chapter_index, (chapter_id, start_year, end_year, title) in enumerate(CHAPTER_DEFS, 1):
        members = chapter_members[chapter_id]
        chapter_counts = Counter()
        chapter_word_poems = Counter()
        chapter_chars = 0
        public_nodes = []
        for node in members:
            record_index, _, scan = linked_record(node)
            chapter_chars += scan["chars"]
            chapter_counts.update(scan["counts"])
            for word in scan["counts"]:
                chapter_word_poems[word] += 1
            public_node = node_public_record(node)
            public_node["chapterId"] = chapter_id
            public_node["chapterIndex"] = chapter_index
            public_node["chapterTitle"] = title
            public_nodes.append(public_node)
            for word, items in canonical_record_evidence.get(record_index, {}).items():
                for item in items:
                    chapter_item = dict(item)
                    chapter_item.update(
                        {
                            "nodeId": node["id"],
                            "year": node["year"],
                            "sourceGrade": node["source_level"],
                            "relationGrade": node["linked_poem"]["relation_level"],
                        }
                    )
                    chapter_evidence_candidates[chapter_id][word].append(chapter_item)
        ranking_words_chapter = sorted(chapter_counts, key=lambda word: (-chapter_counts[word], word))[:10]
        ranking = [
            {
                "rank": rank,
                "word": word,
                "category": term_info[word]["category"],
                "singleCharacter": len(word) == 1,
                "rawHits": chapter_counts[word],
                "ratePer10k": normalized_rate(chapter_counts[word], chapter_chars),
                "chineseCharDenominator": chapter_chars,
                "nodeSample": len(members),
                "linkedPoemSample": len(members),
                "poemsWithHit": chapter_word_poems[word],
            }
            for rank, word in enumerate(ranking_words_chapter, 1)
        ]
        top_labels = "、".join(
            f"“{row['word']}”{row['rawHits']}次" for row in ranking[:3]
        )
        chapters.append(
            {
                "id": chapter_id,
                "index": chapter_index,
                "title": title,
                "startYear": start_year,
                "endYear": end_year,
                "nodeCount": len(members),
                "linkedPoemCount": len(members),
                "chineseChars": chapter_chars,
                "rawHits": sum(chapter_counts.values()),
                "ratePer10k": normalized_rate(sum(chapter_counts.values()), chapter_chars),
                "sourceGrades": {
                    "nodeFact": grade_counts(node["source_level"] for node in members),
                    "poemRelation": grade_counts(
                        node["linked_poem"]["relation_level"] for node in members
                    ),
                },
                "ranking": ranking,
                "nodes": public_nodes,
                "contextReading": (
                    f"本章由{len(members)}个审核节点及其{len(members)}首关联作品构成；"
                    f"客观意象命中居前的是{top_labels}。这是小样本文本共现提示，"
                    f"可与“{title}”的年代背景对读；相关不等于因果。"
                ),
            }
        )

    outside_public = [node_public_record(node) for node in outside_nodes]
    playback_nodes = [node for chapter in chapters for node in chapter["nodes"]]
    for step_index, node in enumerate(playback_nodes, 1):
        node["stepIndex"] = step_index
        node["stepCount"] = len(playback_nodes)
    all_public_nodes = playback_nodes + outside_public
    assert len(all_public_nodes) == 38
    assert len(playback_nodes) == 36

    displayed_words = set(words)

    evidence_payload = {}
    for word in sorted(displayed_words):
        corpus_evidence = [public_evidence(item) for item in select_corpus_evidence(evidence_candidates[word])]
        assert corpus_evidence or combined_word_hits[word] == 0, f"命中词缺少全语料证据：{word}"
        chapter_evidence = {}
        for chapter in chapters:
            items = chapter_evidence_candidates[chapter["id"]].get(word, [])
            if not items:
                continue
            selected = dedupe_evidence(items)[:3]
            chapter_evidence[chapter["id"]] = [
                {
                    **public_evidence(item),
                    "nodeId": item["nodeId"],
                    "year": item["year"],
                    "sourceGrade": item["sourceGrade"],
                    "relationGrade": item["relationGrade"],
                }
                for item in selected
            ]
        evidence_payload[word] = {
            "word": word,
            "category": term_info[word]["category"],
            "singleCharacter": len(word) == 1,
            "corpus": corpus_evidence,
            "chapters": chapter_evidence,
        }
        for evidence in corpus_evidence:
            assert evidence["sentence"][evidence["matchStart"] : evidence["matchEnd"]] == word
    for chapter in chapters:
        for row in chapter["ranking"]:
            assert chapter["id"] in evidence_payload[row["word"]]["chapters"]
    assert len(evidence_payload) == 160

    source_grade_definitions = journeys["methodology"]["source_levels"]
    overall_node_grades = grade_counts(node["source_level"] for node in all_nodes)
    overall_relation_grades = grade_counts(
        node["linked_poem"]["relation_level"] for node in all_nodes
    )
    latest_validation = max(
        (poem.get("content_validated_at", "") for poem in canonical_poems), default=""
    )

    dating_source_hashes = {
        "data/reviewed/verified_all_poet_fact_packages.jsonl": hashlib.sha256(verified_bytes).hexdigest(),
        "data/candidates/work_chronology_supplements.jsonl": hashlib.sha256(supplements_bytes).hexdigest(),
        "data/candidates/{libai,dufu,baijuyi,sushi,luyou,liqingzhao}_spirit_chronology.csv": hashlib.sha256(
            six_csv_bytes
        ).hexdigest(),
    }

    author_out = []
    for author in sorted(author_stats, key=lambda name: (author_stats[name]["dynasty"], -author_stats[name]["chars"], name)):
        entry = author_stats[author]
        top_words = sorted(entry["wordHits"].items(), key=lambda item: (-item[1], item[0]))[:8]
        author_out.append(
            {
                "author": author,
                "dynasty": entry["dynasty"],
                "poems": entry["poems"],
                "chineseChars": entry["chars"],
                "rawHits": entry["wordHits"].total(),
                "ratePer10k": round(entry["wordHits"].total() * 10000 / entry["chars"], 4)
                if entry["chars"]
                else 0.0,
                "topWords": [{"word": word, "rawHits": count} for word, count in top_words],
            }
        )

    robustness_word_rows = []
    for row in top_contrasts:
        word = row["word"]
        report = robustness_words[word]
        robustness_word_rows.append(
            {
                "word": word,
                "category": word_category[word],
                **report,
            }
        )

    data = {
        "meta": {
            "schemaVersion": "2.0",
            "title": "唐宋意象潮汐",
            "generatedFromPoems": len(analysis_rows),
            "aggregatedPoems": len(poems),
            "canonicalEvidencePoems": len(canonical_poems),
            "corpusSource": corpus_source,
            "corpusPath": "data/analysis/famous_poets_full.jsonl.gz",
            "excludedTransitionCounts": dict(sorted(excluded_period_counts.items())),
            "zeroChineseBodyCounts": {dynasty: zero_chinese_body_count[dynasty] for dynasty in DYNASTIES},
            "canonicalIdentityHashFallbacks": canonical_identity_hash_fallbacks,
            "analysisByCanonicalIdEntries": analysis_by_canonical_id_size,
            "sourceHashes": {
                "fullCorpusSha256": hashlib.sha256(full_corpus_bytes).hexdigest(),
                "poemsJsonSha256": hashlib.sha256(canonical_bytes).hexdigest(),
                "spiritImageDictSha256": hashlib.sha256(lexicon_bytes).hexdigest(),
                "poetJourneysSha256": hashlib.sha256(journeys_bytes).hexdigest(),
            },
            "corpusSha256": hashlib.sha256(full_corpus_bytes).hexdigest(),
            "corpusLatestValidation": latest_validation,
            "journeysUpdatedAt": journeys.get("updated_at", ""),
            "dynastyCounts": {dynasty: dynasty_poem_counts[dynasty] for dynasty in DYNASTIES},
            "totalChineseChars": sum(dynasty_chars.values()),
            "lexiconSourceTerms": len(included_rows) + len(excluded_terms),
            "includedObjectiveTerms": len(included_rows),
            "excludedTerms": len(excluded_terms),
            "displayedEvidenceWords": len(evidence_payload),
            "contextExcludedHits": sum(context_exclusion_counts.values()),
            "normalization": "每10,000个正文汉字的非重叠词条命中数",
            "datingCoverage": dating_coverage,
            "datingStats": dating_stats,
        },
        "dynastyAggregates": dynasty_aggregates,
        "authorEqualOverall": author_equal_overall,
        "categoryStats": category_stats,
        "wordStats": word_stats,
        "comparisonWords": comparison_words,
        "topContrasts": top_contrasts,
        "authorStats": author_out,
        "robustness": {
            "overall": robustness_overall,
            "categories": [
                {"category": category, "termCount": category_term_counts[category], **robustness_categories[category]}
                for category in category_order
            ],
            "words": robustness_word_rows,
            "rule": (
                "留一作者检验：对每个作者，从其所在朝代扣掉该作者的全部命中与正文汉字后重算唐宋率差，"
                "检查差值符号是否翻转；同时给出作者等权口径（去掉该作者后剩余作者率的平均）的对应检验。"
                " flips 为翻转该结论的作者名单，空名单表示删除任何单个作者都不反转结论。"
            ),
        },
        "authorContribution": {
            "words": [contribution_rows(row["word"]) for row in top_contrasts],
            "rule": (
                "精确可加分解：把宋侧每万字率拆成各宋作者命中/宋总汉字×10000，唐侧同理取负；"
                "两侧全部作者的贡献之和恰等于该词的宋唐率差。列出的只是贡献最大的前6位，"
                "总和等于率差的断言在生成脚本内校验。"
            ),
        },
        "chronology": {
            "binWidth": BIN_WIDTH,
            "minBinWorks": MIN_BIN_WORKS,
            "minBinChars": MIN_BIN_CHARS,
            "minWordBinHits": MIN_WORD_BIN_HITS,
            "trendWords": trend_words,
            "bins": bin_list,
            "coverage": dating_coverage,
            "tierLabels": DATING_TIER_LABELS,
            "rule": (
                "时间轴只使用逐篇系年证据：人工复核包 > 六诗人编年CSV候选 > 搜韵开放API候选（B优于C）。"
                "同作品多候选行时取等级最高的一行并保留分歧标记；区间系年按起讫中点入箱。"
                "作品无法可靠系年时保持 unknown，绝不使用作者生卒年中点或朝代中点补年。"
            ),
            "caveat": (
                "候选编年（搜韵B/C）未经人工复核，页面单独显示其占比；五代时段无样本属正常空窗；"
                "系年样本偏向有编年的名篇，作者构成逐箱展示，不等同于唐宋全体的年代分布。"
            ),
        },
        "genre": {
            "groups": genre_groups,
            "categoryStats": genre_category_stats,
            "wordStats": genre_word_stats,
            "rule": (
                "体裁只依据明确的上游数据集：poet.tang/poet.song=诗、ci.song=词、canonical（古诗文网规范库）=未标。"
                "标题含间隔号不作为判词依据，未标层单列，不从任何口径中悄悄排除。"
            ),
        },
        "cooccurrence": {
            "totals": cooc_totals,
            "stablePairs": stable_pairs_out,
            "divergentPairs": divergent_pairs,
            "collocates": collocates,
            "evidence": cooc_evidence,
            "rule": (
                f"句内共现：以句号、问号、叹号、分号或换行分句，同一句内出现两个不同意象词记一次；"
                f"对比榜要求两侧支持数都≥{MIN_PAIR_SUPPORT}句，lift=实际共现句数/独立情形期望，"
                f"语境迁移表只列共现≥{MIN_COLLOCATE_COUNT}句的搭配词。"
            ),
        },
        "conclusions": conclusions,
        "changeAnalysis": change_analysis,
        "evidence": evidence_payload,
        "historicalLens": {
            "reviewedNodeCount": len(all_nodes),
            "chapteredNodeCount": len(assigned_ids),
            "outsideChapterWindowCount": len(outside_nodes),
            "overallSourceGrades": {
                "nodeFact": overall_node_grades,
                "poemRelation": overall_relation_grades,
            },
            "events": list(EVENT_ANCHORS),
            "chapters": chapters,
            "playbackNodes": playback_nodes,
            "outsideChapterWindows": outside_public,
        },
        "categoryInfo": [
            {
                "name": category,
                "color": color,
                "termCount": category_term_counts[category],
            }
            for category, color in CATEGORY_COLORS.items()
        ],
        "method": {
            "corpusScope": (
                f"唐宋聚合使用 data/analysis/famous_poets_full.jsonl.gz 的名家全作品；"
                f"按诗人生平 period 精确纳入唐 {dynasty_poem_counts['唐']:,} 条、宋 {dynasty_poem_counts['宋']:,} 条。"
                f"另有 {sum(excluded_period_counts.values()):,} 条跨代/过渡期作品不进入唐宋二分，分组为 {dict(sorted(excluded_period_counts.items()))}。"
                f"原文、系年与行旅证据另由 data/poems.json 的 {len(canonical_poems):,} 条规范记录绑定。"
                "全作品含诗、词及上游收录的相关混合体裁，故统一称‘诗文正文’，不外推为全唐宋所有作者。"
            ),
            "denominator": (
                f"分母仅计正文中的CJK汉字；唐 {dynasty_chars['唐']:,} 字，宋 {dynasty_chars['宋']:,} 字。"
                f"其中正文不含可计 CJK 汉字的记录为唐 {zero_chinese_body_count['唐']} 条、宋 {zero_chinese_body_count['宋']} 条，"
                "仍保留在作品记录数中但对字符分母贡献为零。标准化率=原始命中数/正文汉字数×10,000；过渡期不进入任一分母。"
            ),
            "matching": (
                "逐篇正文从左到右扫描；每个位置按词长降序、同长度按词条字面序检查，"
                "命中后前移整个词长，因此长词优先且不产生重叠重复计数。"
            ),
            "singleCharacterCaveat": (
                "单字字符串匹配仍可能存在多义；本页对月的日历义、云的言说义、风的固定抽象构词"
                "执行有限上下文排除，并公开规则、次数与例证。其余结果仍是可复现的低层文本特征。"
            ),
            "authorEqualRule": (
                f"作者等权：先算每位作者的每万字率（命中/该作者正文汉字×10000），再对朝代内作者取算术平均；"
                f"唐 {author_equal_overall['tang']['authors']} 人、宋 {author_equal_overall['song']['authors']} 人（正文汉字为 0 的作者不参与）。"
                "它回答‘把高产作者压到一人一票后，差异是否仍在’，不替代语料加权率。"
            ),
            "looRule": (
                "留一作者检验对语料加权率与作者等权率分别执行；翻转定义为率差符号改变。"
                "对总命中率、10 个类别与率差最大的 12 个词全部执行，结果全部展示。"
            ),
            "contributionRule": (
                "作者贡献分解是精确可加的：宋侧各作者命中/宋总汉字×10000 之和恰为宋率，唐侧同理；"
                "两側之差恰为率差。图中只显示贡献最大的前 6 位作者，并注明其本人每万字率以区分‘量大’与‘率高’。"
            ),
            "datingRule": (
                "逐篇年代证据分三级并按优先级取用（同一作品不叠加）："
                "①人工复核包（verified_all_poet_fact_packages.jsonl，124 条，全部 verified、B 级证据）；"
                "②项目六诗人编年 CSV 中 status=candidate 的行（绑定规范库 poet+title，只取 B/C 级）；"
                "③搜韵开放 API 作品编年候选（needs_review，B/C 级，来自 data/candidates/work_chronology_supplements.jsonl）。"
                "年份类型 exact/approximate/range 逐条保存，无法系年的作品保持 unknown，"
                "绝不以作者生卒年中点或朝代中点补年。完整逐条来源见 imagery_tide_dating.json 审计文件。"
            ),
            "binRule": (
                f"25 年分箱（{BIN_START_YEAR}–{BIN_END_YEAR}），区间系年按起讫中点入箱；"
                f"只有箱内作品≥{MIN_BIN_WORKS} 首、正文≥{MIN_BIN_CHARS} 字才允许画趋势点，"
                f"单词还需该箱命中≥{MIN_WORD_BIN_HITS}。置信带为泊松正态近似 95% 区间（1.96×√命中/字数）。"
                f"当前 {len(bin_list)} 个非空箱中 {supported_bin_count} 个满足条件。"
            ),
            "genreRule": (
                "体裁比较只依据上游数据集字段：全唐诗/全宋诗（poet.tang、poet.song）记为诗，"
                "全宋词（ci.song）记为词，古诗文网规范库（canonical）无体裁字段记为未标并单独列出。"
                "词在上游无唐侧样本，因此不做词的唐宋对比，只做宋内部诗 vs 词与未标层复算。"
            ),
            "coocRule": (
                f"共现以句为单位（句号、问号、叹号、分号、换行分句），同一句出现两个不同意象词记一次共现；"
                f"唐宋对比榜要求两侧各≥{MIN_PAIR_SUPPORT}句支持；lift=实际共现频率/两词独立出现频率之积，"
                f"lift差=宋lift−唐lift；语境迁移表列出与该词共现≥{MIN_COLLOCATE_COUNT}句的最高频搭配词。"
            ),
            "includedCategories": [
                {
                    "category": category,
                    "termCount": category_term_counts[category],
                    "rule": "词条具有具象尺度与意象说明",
                }
                for category in category_order
            ],
            "excludedCategories": [
                {
                    "category": category,
                    "termCount": sum(item["category"] == category for item in excluded_terms),
                    "reason": reason,
                }
                for category, reason in EXCLUDED_CATEGORIES.items()
            ],
            "additionalExcludedTerms": [
                item for item in excluded_terms if item["category"] not in EXCLUDED_CATEGORIES
            ],
            "includedTerms": [
                {
                    "word": word,
                    **term_info[word],
                    "combinedRawHits": combined_word_hits[word],
                }
                for word in sorted(words)
            ],
            "contextExclusionRules": [
                {
                    **rule,
                    "excludedHits": context_exclusion_counts[rule["id"]],
                    "examples": context_exclusion_examples[rule["id"]],
                }
                for rule in CONTEXT_RULE_DEFS
            ],
            "chapterRule": (
                "历史动画只读取 data/reviewed/poet_journeys.json 的审核节点及其关联作品；"
                "五个年份窗口纳入36节点，并按年、诗人、原路线序、节点ID确定性排序后逐站停驻。"
                "五章只是背景分组。766、768两个杜甫节点落在窗口外，仅保留审计。"
            ),
            "chapterCaveat": (
                "带年份的历史镜头是38节点审核证据子集，不代表唐宋全朝语料；"
                "五章排名只描述36首关联作品。小样本文本共现可与时代背景对读，相关不等于因果。"
            ),
            "eventAnchorRule": (
                "755安史之乱、907唐亡、960北宋建立、1079乌台诗案、1127靖康之变"
                "仅作时间背景标记，不进入统计，也不用于推断因果；每一项均在页面列出史籍或"
                "开放年谱来源名称与URL。历史事件与意象变化只使用‘相关’‘同时出现’等对读表述。"
            ),
            "contrastRule": (
                "先取全库原始命中总量最高的24个客观意象词，再按唐宋每万汉字率差绝对值排序，"
                "展示前12项；差值定义为宋率减唐率。"
            ),
            "evidenceRule": (
                "证据句由同一次非重叠扫描的命中位置回溯；句界取句号、问号、叹号、分号或换行，"
                "页面保留完整句子，不截断。160个纳入词均有可按需打开的证据入口；有命中的词"
                "优先各取唐、宋的 canonical 匹配记录，再以全作品记录补足；零命中词明确显示为空。"
                "章节与节点证据只来自按作者、诗题唯一绑定的规范作品，不能由同题上游变体代替。"
            ),
            "sourceGradeDefinitions": source_grade_definitions,
            "datingTierLabels": DATING_TIER_LABELS,
            "exclusions": excluded_terms,
            "sourceHashes": {
                "data/analysis/famous_poets_full.jsonl.gz": hashlib.sha256(full_corpus_bytes).hexdigest(),
                "data/poems.json": hashlib.sha256(canonical_bytes).hexdigest(),
                "data/imagery_tide_lexicon.py": hashlib.sha256(lexicon_bytes).hexdigest(),
                "data/reviewed/poet_journeys.json": hashlib.sha256(journeys_bytes).hexdigest(),
                **dating_source_hashes,
            },
        },
    }

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    json_text = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    assert "NaN" not in json_text and "Infinity" not in json_text
    OUT_JSON.write_text(json_text, encoding="utf-8")

    artifact = dating_artifact(dating_works, dating_stats, dating_source_hashes)
    OUT_DATING_JSON.write_text(
        json.dumps(artifact, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n",
        encoding="utf-8",
    )

    embedded = json.dumps(data, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    embedded = embedded.replace("</", "<\\/")
    html = (
        HTML_TEMPLATE.replace("__VIZ38_CSS__", TEMPLATE_CSS)
        .replace("__VIZ38_BODY__", TEMPLATE_BODY)
        .replace("__VIZ38_SCRIPT__", TEMPLATE_SCRIPT)
        .replace("__IMAGERY_DATA__", embedded)
    )
    assert 'name="viewport"' in html
    assert '<script src="assets/pyecharts/v6/echarts.min.js"></script>' in html
    assert '<script src="assets/pyecharts/v6/maps/china.js"></script>' in html
    assert 'rel="icon" href="data:image/svg+xml' in html
    assert 'href="29_参赛导航.html"' in html
    assert not REMOTE_SCRIPT_RE.search(html), "页面出现远程脚本"
    assert "NaN" not in html and "Infinity" not in html
    assert len(html.encode("utf-8")) >= 5000
    OUT_HTML.write_text(html, encoding="utf-8")

    print(
        "OK 唐宋意象潮汐（分析版）："
        f"全作品{len(analysis_rows)}条，纳入二分{len(poems)}条"
        f"（唐{dynasty_poem_counts['唐']} / 宋{dynasty_poem_counts['宋']} / 过渡期{sum(excluded_period_counts.values())}），"
        f"正文汉字{sum(dynasty_chars.values())}，客观意象词{len(included_rows)}；"
        f"逐篇系年{dated_works_total}条（覆盖{dating_coverage['workCoverage'] * 100:.1f}%，"
        f"人工复核{dating_coverage['byTier'].get('verified-B', 0)}条），"
        f"非空时间箱{len(bin_list)}（满足样本量{supported_bin_count}）；"
        f"审核节点{len(all_nodes)}，入章{len(assigned_ids)}，窗口外{len(outside_nodes)}。"
    )
    print(
        f"作者等权总体率：唐{author_equal_overall['tang']['meanRate']} / 宋{author_equal_overall['song']['meanRate']}；"
        f"LOO翻转：总体{len(robustness_overall['flips'])}次，等权{len(robustness_overall['authorEqualFlips'])}次。"
    )
    print(f"JSON {OUT_JSON} ({OUT_JSON.stat().st_size} bytes)")
    print(f"DATING {OUT_DATING_JSON} ({OUT_DATING_JSON.stat().st_size} bytes)")
    print(f"HTML {OUT_HTML} ({OUT_HTML.stat().st_size} bytes)")


TEMPLATE_CSS = r'''
:root{
  --paper:#f3f5f1; --paper-2:#e9ede7; --surface:#fafbf8; --ink:#222822;
  --muted:#667068; --line:#d4dbd3; --line-strong:#bcc7bd;
  --tang:#456f8a; --song:#a34f44; --jade:#28766d; --gold:#a8762b;
  --shadow:0 8px 24px rgba(36,45,38,.055);
}
*{box-sizing:border-box}
html{scroll-behavior:smooth;background:var(--paper)}
body{width:100%;max-width:100vw;margin:0;color:var(--ink);background:var(--paper);font-family:"Microsoft YaHei","PingFang SC",sans-serif;line-height:1.65;overflow-x:hidden}
button,input{font:inherit}
button{color:inherit}
a{color:var(--jade);text-decoration:none;border-bottom:1px solid transparent}
a:hover{border-bottom-color:currentColor}
.wrap{width:100%;max-width:1400px;min-width:0;margin:0 auto;padding:0 24px}
.topbar{width:100%;max-width:100vw;min-width:0;border-bottom:1px solid var(--line);background:var(--surface)}
.topbar .wrap{padding-top:18px;padding-bottom:16px}
.title-row{display:flex;align-items:flex-end;justify-content:space-between;gap:22px}
.eyebrow{font-size:12px;color:var(--song);font-weight:700;margin-bottom:3px}
h1,h2,h3,.kai{font-family:KaiTi,STKaiti,"Songti SC",serif;font-weight:700}
h1{font-size:34px;line-height:1.15;margin:0;letter-spacing:0}
h1 .dot{color:var(--song)}
.dek{max-width:690px;margin:0;color:var(--muted);font-size:13px;text-align:right}
.audit-strip{display:flex;flex-wrap:wrap;gap:8px 18px;margin-top:12px;font-size:12px;color:var(--muted)}
.audit-strip b{color:var(--ink);font-variant-numeric:tabular-nums}
main{min-width:0;padding:24px 0 0}
section{width:100%;max-width:100%;min-width:0;padding:18px 0 34px;border-bottom:1px solid var(--line)}
.section-head{display:flex;align-items:baseline;justify-content:space-between;gap:18px;margin-bottom:9px}
.section-head h2{font-size:25px;line-height:1.2;margin:0;letter-spacing:0}
.section-kicker{font-size:12px;color:var(--muted);text-align:right}
.section-note{margin:0 0 14px;color:var(--muted);font-size:13px;max-width:970px}
.panel{background:var(--surface);border:1px solid var(--line);border-radius:6px;box-shadow:var(--shadow)}
.event-scroll,.tab-scroll,.chart-scroll{display:block;width:100%;max-width:100%;min-width:0;overflow-x:auto;overscroll-behavior-x:contain}
.event-rail{position:relative;min-width:900px;height:68px;margin:0 0 10px;border-top:1px solid var(--line-strong);border-bottom:1px solid var(--line);background:var(--paper-2)}
.event-rail::before{content:"";position:absolute;left:18px;right:18px;top:33px;height:1px;background:var(--line-strong)}
.event-anchor{position:absolute;top:0;height:68px;width:112px;transform:translateX(-50%);font-size:11px;text-align:center;color:var(--muted)}
.event-anchor::after{content:"";position:absolute;left:50%;top:28px;width:7px;height:7px;border:2px solid var(--song);background:var(--paper-2);transform:translateX(-50%) rotate(45deg)}
.event-anchor b{display:block;color:var(--ink);line-height:1.25;font-weight:700}
.event-anchor:nth-child(even){padding-top:41px}.event-anchor:nth-child(odd){padding-top:4px}
.chapter-tabs{display:flex;gap:6px;min-width:max-content;padding-bottom:2px}
.chapter-tab{height:42px;padding:0 15px;border:1px solid var(--line);border-radius:4px;background:var(--surface);cursor:pointer;white-space:nowrap;font-size:13px}
.chapter-tab[aria-selected="true"]{border-color:var(--jade);background:#e5eeea;color:#174f49;font-weight:700}
.chapter-tab .years{display:block;color:var(--muted);font-size:10px;line-height:1;margin-top:-3px}
.controls{display:flex;align-items:center;flex-wrap:wrap;gap:7px;margin:12px 0}
.tool-btn{height:38px;min-width:42px;padding:0 12px;border:1px solid var(--line-strong);border-radius:4px;background:var(--surface);cursor:pointer}
.tool-btn:hover,.tool-btn:focus-visible{border-color:var(--jade);outline:2px solid rgba(40,118,109,.14);outline-offset:1px}
.tool-btn.primary{background:var(--jade);border-color:var(--jade);color:white;font-weight:700}
.tool-btn:disabled{opacity:.45;cursor:default}
.auto-control{display:flex;align-items:center;gap:8px;height:38px;padding:0 10px;border-left:1px solid var(--line);font-size:12px;color:var(--muted)}
.switch{position:relative;width:38px;height:22px;flex:0 0 auto}
.switch input{position:absolute;opacity:0;inset:0}
.switch i{position:absolute;inset:0;border-radius:12px;background:#c7cec7;border:1px solid #adb6ae;transition:background .2s}
.switch i::after{content:"";position:absolute;left:2px;top:2px;width:16px;height:16px;border-radius:50%;background:white;box-shadow:0 1px 3px rgba(0,0,0,.2);transition:transform .2s}
.switch input:checked+i{background:var(--jade);border-color:var(--jade)}
.switch input:checked+i::after{transform:translateX(16px)}
.switch input:focus-visible+i{outline:2px solid rgba(40,118,109,.28);outline-offset:2px}
.play-status{margin-left:auto;font-size:12px;color:var(--muted);font-variant-numeric:tabular-nums}
.chapter-layout{display:grid;width:100%;max-width:100%;min-width:0;grid-template-columns:minmax(0,1.65fr) minmax(310px,.75fr);gap:14px;align-items:stretch}
.chapter-layout>*{min-width:0;max-width:100%}
.chart-stack{display:grid;grid-template-rows:270px 285px;min-width:0}
.map-canvas,.chart-canvas{width:100%;min-width:650px}
.map-canvas{height:270px;border-bottom:1px solid var(--line)}
.chart-canvas{height:285px}
.context-panel{padding:16px;min-width:0}
.context-panel h3{margin:0 0 4px;font-size:21px;line-height:1.25}
.chapter-badges{display:flex;flex-wrap:wrap;gap:5px;margin:8px 0 10px}
.badge{display:inline-flex;align-items:center;min-height:25px;padding:2px 7px;border:1px solid var(--line);border-radius:3px;background:var(--paper);font-size:11px;color:var(--muted)}
.context-reading{margin:0 0 12px;font-size:13px}
.evidence-mini{border-top:1px solid var(--line);padding-top:11px}
.evidence-mini h4{margin:0;font-size:15px}
.evidence-mini .word-meta{font-size:11px;color:var(--muted);margin-bottom:7px}
.node-list{max-height:148px;overflow:auto;margin-top:10px;border-top:1px solid var(--line)}
.node-row{padding:7px 0;border-bottom:1px solid var(--line);font-size:11px;line-height:1.45;color:var(--muted)}
.node-row b{color:var(--ink)}
.node-row .grade{float:right;color:var(--song);font-weight:700}
.node-row.current{background:#e5eeea;border-left:3px solid var(--jade);padding-left:7px}
.station-count{font-size:12px;color:var(--song);font-weight:700;font-variant-numeric:tabular-nums}
.station-source{margin:8px 0;padding-top:8px;border-top:1px solid var(--line);font-size:11px;color:var(--muted)}
.station-source a{overflow-wrap:anywhere}
.station-poem{max-height:190px;overflow:auto;margin:10px 0;padding:11px;background:var(--paper);border-left:3px solid var(--jade);white-space:pre-wrap;font-family:KaiTi,STKaiti,serif;font-size:16px;line-height:1.75}
.station-hits{display:flex;flex-wrap:wrap;gap:5px;margin:8px 0}
.station-hit{border:1px solid var(--line);background:var(--surface);padding:3px 7px;font-size:11px;cursor:pointer}
.event-anchor.active::after{background:var(--song);box-shadow:0 0 0 5px rgba(163,79,68,.14)}
.event-anchor a{font-size:10px}
.term-browser{display:grid;grid-template-columns:minmax(180px,.35fr) minmax(0,1fr);gap:10px}
.term-list{max-height:370px;overflow:auto;border:1px solid var(--line);background:var(--surface);padding:7px}
.term-list button{margin:2px;padding:3px 7px;border:1px solid var(--line);background:var(--paper);cursor:pointer;font-size:11px}
.term-detail{min-width:0}
.hash{font-family:Consolas,monospace;overflow-wrap:anywhere;font-size:10px}
.progress-track{height:3px;background:var(--line);overflow:hidden}
.progress-bar{height:100%;width:0;background:var(--jade)}
.dynasty-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:14px 0}
.dynasty-strip{display:grid;grid-template-columns:auto repeat(4,minmax(0,1fr));gap:10px;align-items:center;padding:12px 14px;border:1px solid var(--line);background:var(--surface);border-radius:6px}
.dynasty-strip h3{font-size:25px;margin:0;line-height:1}
.dynasty-strip.tang h3{color:var(--tang)}.dynasty-strip.song h3{color:var(--song)}
.metric{min-width:0;border-left:1px solid var(--line);padding-left:10px}
.metric b{display:block;font-size:16px;line-height:1.2;font-variant-numeric:tabular-nums;white-space:nowrap}
.metric span{display:block;color:var(--muted);font-size:10px;margin-top:3px}
.compare-layout{display:grid;width:100%;max-width:100%;min-width:0;grid-template-columns:minmax(0,1.55fr) minmax(330px,.7fr);gap:14px;align-items:stretch}
.compare-layout>*{min-width:0;max-width:100%}
.comparison-chart{height:540px;width:100%;min-width:720px}
.evidence-panel{padding:16px;min-width:0}
.evidence-panel h3{font-size:23px;margin:0;line-height:1.2}
.word-category{display:inline-block;margin-left:7px;font-family:"Microsoft YaHei",sans-serif;font-size:11px;color:var(--muted);font-weight:400}
.word-warning{margin:7px 0;padding:7px 8px;border-left:3px solid var(--gold);background:#f3eee2;color:#69572d;font-size:11px}
.word-sides{display:grid;grid-template-columns:1fr 1fr;gap:7px;margin:10px 0}
.word-side{padding:8px;border:1px solid var(--line);background:var(--paper);font-size:11px;color:var(--muted)}
.word-side b{display:block;font-size:15px;color:var(--ink);font-variant-numeric:tabular-nums}
.word-side.tang{border-top:3px solid var(--tang)}.word-side.song{border-top:3px solid var(--song)}
.quotes{display:grid;gap:7px}
.quote{margin:0;padding:9px 10px;border-left:3px solid var(--line-strong);background:var(--paper);font-family:KaiTi,STKaiti,"Songti SC",serif;font-size:15px;line-height:1.65;overflow-wrap:anywhere}
.quote mark{background:#eadcae;color:inherit;padding:0 1px}
.quote cite{display:block;font-family:"Microsoft YaHei",sans-serif;font-style:normal;font-size:10px;color:var(--muted);margin-top:3px}
.evidence-method{margin:9px 0 0;color:var(--muted);font-size:10px}
.contrast-row{display:flex;align-items:center;gap:6px;flex-wrap:wrap;margin:12px 0 0}
.contrast-label{font-size:11px;color:var(--muted);margin-right:3px}
.word-chip{height:31px;padding:0 8px;border:1px solid var(--line);border-radius:3px;background:var(--surface);cursor:pointer;font-size:11px}
.word-chip:hover{border-color:var(--jade)}
.legend-inline{display:flex;gap:14px;align-items:center;flex-wrap:wrap;margin:7px 0 0;font-size:11px;color:var(--muted)}
.legend-inline i{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:4px}
.category-block{margin-top:18px}
.category-chart{width:100%;min-width:720px;height:430px}
.method{margin:20px 0 0;border-top:1px solid var(--line-strong);border-bottom:1px solid var(--line);padding:0}
.method summary{cursor:pointer;padding:15px 0;font-weight:700;font-size:14px}
.method-body{padding:0 0 18px;font-size:12px;color:var(--muted)}
.method-body h3{font-family:"Microsoft YaHei",sans-serif;color:var(--ink);font-size:14px;margin:16px 0 5px}
.method-body p{margin:4px 0}
.method-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.method-table{width:100%;border-collapse:collapse;background:var(--surface)}
.method-table th,.method-table td{border:1px solid var(--line);padding:7px;text-align:left;vertical-align:top}
.method-table th{color:var(--ink);background:var(--paper-2)}
.audit-note{padding:10px;border-left:3px solid var(--song);background:#f3e9e6;color:#62443f}
footer{margin-top:42px;border-top:1px solid var(--line);padding:21px 0 34px;color:var(--muted);font-size:12px}
.site-nav{display:flex;gap:6px 15px;flex-wrap:wrap;margin-bottom:7px}
.site-nav a,.site-nav .here{white-space:nowrap}
.site-nav .here{color:var(--song);font-weight:700}
.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
@media(max-width:1000px){
  .chapter-layout,.compare-layout{grid-template-columns:minmax(0,1fr)}
  .context-panel,.evidence-panel{min-height:0}
  .play-status{width:100%;margin-left:0}
}
@media(max-width:720px){
  .wrap{padding:0 13px}
  .topbar .wrap{padding-top:14px;padding-bottom:13px}
  .title-row{display:block}
  h1{font-size:28px}
  .dek{text-align:left;margin-top:7px;font-size:12px}
  main{padding-top:12px}
  section{padding:14px 0 27px}
  .section-head{display:block}.section-head h2{font-size:22px}.section-kicker{text-align:left;margin-top:4px}
  .dynasty-grid{grid-template-columns:1fr}
  .dynasty-strip{grid-template-columns:50px repeat(2,minmax(0,1fr));gap:8px}
  .dynasty-strip h3{grid-row:1 / span 2;align-self:center}
  .dynasty-strip .metric:nth-of-type(3),.dynasty-strip .metric:nth-of-type(4){margin-top:4px}
  .chart-canvas{height:400px}
  .chart-stack{grid-template-rows:250px 360px}.map-canvas{height:250px}
  .comparison-chart{height:520px}
  .auto-control{border-left:0;padding-left:0}
  .method-grid{grid-template-columns:1fr}
  .term-browser{grid-template-columns:1fr}
  .quote{font-size:14px}
}
@media(prefers-reduced-motion:reduce){html{scroll-behavior:auto}.switch i,.switch i::after{transition:none}}

/* ——— 分析版新增（38 页七层结构） ——— */
.layer-chip{display:inline-block;min-width:24px;height:23px;line-height:23px;text-align:center;margin-right:9px;padding:0 7px;border-radius:3px;background:var(--jade);color:#fff;font-family:"Microsoft YaHei",sans-serif;font-size:12px;font-weight:700;vertical-align:4px}
.conclusion-grid{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:10px;margin:14px 0 0}
.conclusion-card{display:flex;flex-direction:column;gap:8px;padding:13px 14px;border:1px solid var(--line);border-radius:6px;background:var(--surface);box-shadow:var(--shadow)}
.conclusion-card h3{margin:0;font-size:15px;line-height:1.55}
.conclusion-card p{margin:0;font-size:12px;color:var(--muted);line-height:1.62}
.conclusion-card .card-foot{margin-top:auto;display:flex;gap:6px;flex-wrap:wrap;padding-top:6px}
.change-analysis{margin-top:18px;padding:22px 24px 20px;border:1px solid var(--line-strong);border-radius:7px;background:rgba(250,251,248,.97);box-shadow:var(--shadow);backdrop-filter:blur(2px)}
.change-analysis-head{display:grid;grid-template-columns:minmax(210px,.72fr) minmax(0,1.45fr);gap:28px;align-items:start;padding-bottom:17px;border-bottom:1px solid var(--line)}
.change-analysis-kicker{font-size:11px;letter-spacing:.18em;color:var(--song);font-weight:700}
.change-analysis h3{margin:7px 0 0;font-size:25px;line-height:1.35}
.change-thesis{margin:0;color:var(--ink);font-family:KaiTi,STKaiti,serif;font-size:18px;line-height:1.8}
.change-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:0 28px}
.change-finding{display:grid;grid-template-columns:38px minmax(0,1fr);gap:10px;padding:18px 0 15px;border-bottom:1px solid var(--line)}
.change-finding:nth-last-child(-n+2){border-bottom:0}
.change-index{font-family:Georgia,serif;font-size:21px;color:var(--jade);font-variant-numeric:tabular-nums}
.change-eyebrow{font-size:11px;letter-spacing:.12em;color:var(--muted);font-weight:700}
.change-finding h4{margin:3px 0 6px;font-size:17px;line-height:1.5}
.change-finding p{margin:0;color:var(--muted);font-size:12.5px;line-height:1.72;text-wrap:pretty}
.change-evidence{display:flex;gap:6px;flex-wrap:wrap;margin-top:10px}
.change-boundary{margin:4px 0 0;padding:13px 14px;border-top:1px solid var(--line-strong);background:var(--paper-2);color:var(--muted);font-size:12px;line-height:1.7}
.change-boundary b{color:var(--ink)}
.compare-extra{display:grid;grid-template-columns:minmax(0,1.15fr) minmax(0,1fr);gap:14px;margin-top:6px}
.authorEqual-chart{height:470px;width:100%;min-width:560px}
.loo-table{width:100%;border-collapse:collapse;background:var(--surface);font-size:11.5px}
.loo-table th,.loo-table td{border:1px solid var(--line);padding:6px 7px;text-align:left}
.loo-table th{background:var(--paper-2);white-space:nowrap;position:sticky;top:0}
.loo-table td.num{font-variant-numeric:tabular-nums;text-align:right}
.flip-badge{color:#8a2d1e;font-weight:700}
.safe-badge{color:#1d5c50}
.timeline-chart{width:100%;min-width:1080px;height:500px}
.coverage-strip{display:flex;flex-wrap:wrap;gap:8px 20px;margin:10px 0 12px;font-size:12px;color:var(--muted)}
.coverage-strip b{color:var(--ink);font-variant-numeric:tabular-nums}
.coverage-strip .candidate-tag{border-bottom:2px dotted #c9a227}
.trend-picks{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin:10px 0 0}
.trend-pick{display:inline-flex;align-items:center;gap:5px;height:30px;padding:0 9px;border:1px solid var(--line);border-radius:3px;background:var(--surface);cursor:pointer;font-size:12px}
.trend-pick input{accent-color:#28766d}
.trend-pick .sw{display:inline-block;width:9px;height:9px;border-radius:2px}
.contrib-chart{width:100%;min-width:760px;height:480px}
.genre-chart{width:100%;min-width:900px;height:450px}
.genre-note{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:8px;margin:12px 0}
.data-table{width:100%;border-collapse:collapse;background:var(--surface);font-size:12px}
.data-table th,.data-table td{border:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}
.data-table th{background:var(--paper-2);white-space:nowrap}
.data-table td.num,.data-table th.num{text-align:right;font-variant-numeric:tabular-nums}
.data-table tbody tr.rowlink:hover{background:#eef3ee;cursor:pointer}
.cooc-layout{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:14px;align-items:start}
.collocate-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin-top:4px}
.collocate-card{padding:10px 11px;border:1px solid var(--line);background:var(--surface);border-radius:6px}
.collocate-card h4{margin:0 0 6px;font-size:17px}
.collocate-card .col-title{display:flex;justify-content:space-between;font-size:11px;color:var(--muted);margin-top:5px;border-top:1px dashed var(--line);padding-top:4px}
.collocate-card .col-words{font-size:12px;line-height:1.85}
.collocate-card .col-words b{font-variant-numeric:tabular-nums;font-weight:400;color:var(--muted)}
.pair-evidence{margin-top:10px}
.coverage-tiles{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:10px;margin:12px 0}
.coverage-tile{padding:11px 12px;border:1px solid var(--line);background:var(--surface);border-radius:6px}
.coverage-tile b{display:block;font-size:19px;line-height:1.25;font-variant-numeric:tabular-nums;white-space:nowrap}
.coverage-tile span{display:block;font-size:11px;color:var(--muted);margin-top:3px}
.limit-list{margin:8px 0 0;padding-left:18px;font-size:12px;color:var(--muted)}
.limit-list li{margin:4px 0}
@media(max-width:1150px){
  .conclusion-grid,.coverage-tiles,.genre-note,.change-grid{grid-template-columns:repeat(2,minmax(0,1fr))}
  .change-analysis-head{grid-template-columns:1fr}
  .compare-extra,.cooc-layout{grid-template-columns:minmax(0,1fr)}
  .collocate-grid{grid-template-columns:repeat(2,minmax(0,1fr))}
}
@media(max-width:720px){
  .conclusion-grid,.coverage-tiles,.genre-note,.change-grid{grid-template-columns:1fr}
  .change-analysis{padding:18px 15px}
  .change-finding:nth-last-child(2){border-bottom:1px solid var(--line)}
  .collocate-grid{grid-template-columns:1fr}
}
/* 固定画幅背景：高密度图表使用更实的纸白底板。 */
body{position:relative;min-height:100vh;background:transparent}
body::before{content:"";position:fixed;inset:0;z-index:0;pointer-events:none;background:url("assets/generated/remaining_pages_20260830/38_imagery_tide_v1.png") center center / cover no-repeat}
body::after{content:"";position:fixed;inset:0;z-index:0;pointer-events:none;background:rgba(243,245,241,.12)}
.topbar,main,footer{position:relative;z-index:1}
.topbar{background:rgba(250,251,248,.96)}
.panel,.conclusion-card,.dynasty-strip,.term-list,.method-table,.loo-table,.data-table,.collocate-card,.coverage-tile{background:rgba(250,251,248,.95);backdrop-filter:blur(1px)}
.chapter-tab,.tool-btn,.station-hit,.word-chip,.trend-pick{background:rgba(250,251,248,.94)}
.badge,.station-poem,.term-list button,.word-side,.quote{background:rgba(243,245,241,.93)}
'''

TEMPLATE_BODY = r'''
<script>window.IMAGERY_TIDE_DATA=__IMAGERY_DATA__;</script>
<header class="topbar">
  <div class="wrap">
    <div class="title-row">
      <div><div class="eyebrow">诗行万里 · 参赛版 · 38</div><h1>唐宋意象潮汐<span class="dot">。</span></h1></div>
      <p class="dek">160 个客观意象词扫过唐宋名家全作品；本页不止回答“出现多少次”，还回答差异由谁推动、出现在哪些年代、是否受体裁与高产作者影响、语境如何迁移。每条结论都带样本量、统计口径与原句证据；历史锚点只供对读，相关不等于因果。</p>
    </div>
    <div class="audit-strip" id="auditStrip" aria-label="数据口径摘要"></div>
  </div>
</header>

<main class="wrap">
  <section id="conclusions">
    <div class="section-head">
      <h2><span class="layer-chip">一</span>关键计算结论</h2>
      <div class="section-kicker">全部由生成脚本计算 · 数字与样本量在卡片内 · 点击词查看原句证据</div>
    </div>
    <p class="section-note">五张卡片分别对应：总体差异及其作者等权复算与留一检验、宋侧最强增量词及其推手、唐侧最强存量词及其承载者、逐篇系年时间轴的覆盖与样本量、体裁分层的口径与样本。卡片中的每个数字都由页面数据直接算出，不是手写文案。</p>
    <div class="conclusion-grid" id="conclusionGrid"></div>
    <div class="change-analysis" id="changeAnalysis" aria-label="唐宋意象变化分析"></div>
  </section>

  <section id="dynastyCompare">
    <div class="section-head">
      <h2><span class="layer-chip">二</span>唐宋总体差异与作者等权稳健性</h2>
      <div class="section-kicker">语料加权 + 作者等权双口径 · 留一作者检验</div>
    </div>
    <p class="section-note">哑铃图是语料加权率（每 10,000 正文汉字非重叠命中数），悬停可见原始次数、分母、命中正文记录数与作品命中率；点击任一词查看唐宋证据句。下方散点图把率差放到作者等权口径：每位作者一票，高产作者不再独占权重。</p>
    <div class="dynasty-grid" id="dynastyGrid"></div>
    <div class="compare-layout">
      <div>
        <div class="panel chart-scroll"><div id="comparisonChart" class="comparison-chart" role="img" aria-label="唐宋高频客观意象标准化率哑铃图"></div></div>
        <div class="legend-inline"><span><i style="background:var(--tang)"></i>唐</span><span><i style="background:var(--song)"></i>宋</span><span>连线只表示同一词的两朝率差</span></div>
        <div class="contrast-row" id="contrastRow"></div>
      </div>
      <aside class="panel evidence-panel" id="aggregateEvidence" aria-live="polite"></aside>
    </div>
    <div class="category-block">
      <div class="section-head"><h2 style="font-size:21px">类别比较</h2><div class="section-kicker">10 类 · 160 词条 · 同一分母口径</div></div>
      <p class="section-note">类别率把同类词条的非重叠命中相加；悬停可核对原始次数、正文汉字分母、总样本与命中正文记录数。</p>
      <div class="panel chart-scroll"><div id="categoryChart" class="category-chart" role="img" aria-label="唐宋客观意象类别标准化率比较"></div></div>
    </div>
    <div class="section-head" style="margin-top:20px"><h2 style="font-size:21px">作者等权复算 · 留一作者检验</h2><div class="section-kicker" id="authorEqualKicker"></div></div>
    <p class="section-note">散点横轴为语料加权率差（宋−唐），纵轴为作者等权率差；虚线对角线为两口径完全一致的位置，十字线为零差参考。点明显偏离对角线，说明该词差异被高产作者放大或掩盖。右表为留一作者检验：逐个删除作者后重算率差，符号翻转记为一次反转。</p>
    <div class="compare-extra">
      <div class="panel chart-scroll"><div id="authorEqualChart" class="authorEqual-chart" role="img" aria-label="语料加权与作者等权率差散点图"></div></div>
      <div class="panel" style="padding:12px;overflow:auto;max-height:520px"><table class="loo-table" id="looTable"></table></div>
    </div>
  </section>

  <section id="chronology">
    <div class="section-head">
      <h2><span class="layer-chip">三</span>年代演变 · 逐篇系年时间轴</h2>
      <div class="section-kicker">只用有逐篇系年证据的作品 · 25 年箱 · 覆盖率与置信带同图</div>
    </div>
    <p class="section-note">时间轴只统计逐篇系年作品，证据分三级取用：人工复核包最优先，其次六诗人编年 CSV 候选，再次搜韵开放 API 候选（needs_review，B/C 级）。堆叠柱为各箱作品量（按证据级别着色），折线为词的每万字率：仅对作品≥40 首、正文≥4,000 字、该词命中≥8 次的箱画点，并给出 95% 置信带。样本不足的时间段不画趋势；约 900–975 的五代时段无样本属正常空窗。</p>
    <div class="coverage-strip" id="chronologyCoverage"></div>
    <div class="panel chart-scroll"><div id="timelineChart" class="timeline-chart" role="img" aria-label="唐宋意象年代趋势与样本覆盖"></div></div>
    <div class="trend-picks" id="trendPicks"></div>
    <div class="legend-inline"><span>浅点=样本不足未画趋势</span><span>置信带=1.96×√命中/字数（泊松近似）</span><span>竖虚线为历史事件锚点，仅作对读背景，相关不等于因果</span></div>
  </section>

  <section id="historical">
    <div class="section-head">
      <h2>三十六站 · 审核节点镜头</h2>
      <div class="section-kicker">年代层的证据镜头 · 默认逐站停驻 · 五章仅作背景分组</div>
    </div>
    <p class="section-note">动画按年、诗人、原路线序与节点 ID 确定性排列 36 个审核节点；每站都联动创作地点、历史锚点、章内统计、当前诗文与来源。地图连线只表示编年先后，不代表真实道路或旅行速度。这 38 个节点是人工审核证据子集，用于对读上方时间轴，不代表唐宋全朝语料。</p>
    <div class="event-scroll" aria-label="历史背景锚点，可横向滚动"><div class="event-rail" id="eventRail"></div></div>
    <div class="tab-scroll"><div class="chapter-tabs" id="chapterTabs" role="tablist" aria-label="历史章节"></div></div>
    <div class="controls" aria-label="逐站动画控制">
      <button class="tool-btn" id="restartBtn" title="回到第一站">↺ 重启</button>
      <button class="tool-btn" id="prevBtn" title="回到上一站">← 上一步</button>
      <button class="tool-btn primary" id="nextBtn" title="进入下一站">下一步 →</button>
      <button class="tool-btn" id="playBtn" title="播放或暂停当前站显影" aria-pressed="false">▶ 播放</button>
      <label class="auto-control" title="开启后才会在当前站显影结束后自动进入下一站">
        <span class="switch"><input type="checkbox" id="autoToggle"><i aria-hidden="true"></i></span>
        自动连播（默认关）
      </label>
      <span class="play-status" id="playStatus" role="status" aria-live="polite"></span>
    </div>
    <div class="chapter-layout">
      <div class="panel chart-shell">
        <div class="chart-scroll"><div class="chart-stack"><div id="routeMap" class="map-canvas" role="img" aria-label="审核节点编年路线地图"></div><div id="chapterChart" class="chart-canvas" role="img" aria-label="当前章节与当前站客观意象比较"></div></div></div>
        <div class="progress-track" role="progressbar" aria-label="当前站显影进度" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0"><div class="progress-bar" id="progressBar"></div></div>
      </div>
      <aside class="panel context-panel" id="chapterContext" aria-live="polite"></aside>
    </div>
  </section>

  <section id="authorContribution">
    <div class="section-head">
      <h2><span class="layer-chip">四</span>诗人贡献分解 · 差异由谁推动</h2>
      <div class="section-kicker">精确可加分解 · 全部作者贡献之和恰等于率差</div>
    </div>
    <p class="section-note">对率差最大的 12 个词，把宋侧每万字率拆成“每位宋作者命中 ÷ 宋总正文汉字 × 10000”，唐侧同理取负；两侧全部作者的贡献之和恰等于该词的宋唐率差（生成脚本内断言校验）。红条为宋作者（把词推向宋侧），蓝条为唐作者（构成唐侧基数，把率差往负向拉）。悬停显示作者本人每万字率，区分“写得多的量”与“用得密的率”。</p>
    <div class="contrast-row" id="contribPicks"></div>
    <div class="panel chart-scroll"><div id="contribChart" class="contrib-chart" role="img" aria-label="诗人对唐宋意象差异的精确贡献分解"></div></div>
    <div class="panel" style="padding:12px;overflow:auto;max-height:420px;margin-top:12px"><table class="data-table" id="authorTable"></table></div>
  </section>

  <section id="genre">
    <div class="section-head">
      <h2><span class="layer-chip">五</span>体裁分层 · 诗 / 词 / 未标</h2>
      <div class="section-kicker">体裁只依上游数据集字段判断 · 未标单列，不悄悄排除</div>
    </div>
    <p class="section-note">诗＝全唐诗/全宋诗上游记录；词＝全宋词上游记录；未标＝规范库记录（无体裁字段，其中不少标题含词牌间隔号，但按规则不用标题猜体裁）。词在上游没有唐侧样本，因此本页不做“词的唐宋对比”，只做宋内部诗 vs 词对比，并用未标层单独复算唐宋差异作为口径稳健性检查。</p>
    <div class="genre-note" id="genreNote"></div>
    <div class="panel chart-scroll"><div id="genreChart" class="genre-chart" role="img" aria-label="唐宋意象体裁分层类别比较"></div></div>
    <div class="panel" style="padding:12px;overflow:auto;margin-top:12px"><table class="data-table" id="genreTable"></table></div>
  </section>

  <section id="cooccurrence">
    <div class="section-head">
      <h2><span class="layer-chip">六</span>意象共现与语境迁移</h2>
      <div class="section-kicker">句内共现 · 最低支持数过滤 · lift 唐宋对比</div>
    </div>
    <p class="section-note">以句号、问号、叹号、分号或换行分句，同一句出现两个不同意象词记一次共现。两个榜单都要求唐宋两侧各至少 15 句支持，避免把偶然共现当规律；lift＝实际共现句频率 ÷ 两词独立出现频率之积，lift 差＝宋 lift − 唐 lift。下方语境迁移卡显示同一词在唐宋句内最高频搭配词的变化。点击“语境迁移”表行查看原句。</p>
    <div class="cooc-layout">
      <div class="panel" style="padding:12px;overflow:auto;max-height:430px"><h3 style="margin:0 0 8px;font-size:16px">稳定共现对（两侧支持数最高）</h3><table class="data-table" id="stablePairsTable"></table></div>
      <div class="panel" style="padding:12px;overflow:auto;max-height:430px"><h3 style="margin:0 0 8px;font-size:16px">语境迁移最大的共现对（lift 差）</h3><table class="data-table" id="divergentPairsTable"></table></div>
    </div>
    <div class="quotes pair-evidence" id="pairEvidence" aria-live="polite"></div>
    <h3 style="font-size:18px;margin:20px 0 8px">同一词的搭配环境（唐 → 宋）</h3>
    <div class="collocate-grid" id="collocateGrid"></div>
  </section>

  <section id="evidenceCoverage">
    <div class="section-head">
      <h2><span class="layer-chip">七</span>证据、覆盖率与方法限制</h2>
      <div class="section-kicker">覆盖率面板 · 160 词证据入口 · 逐条系年审计文件</div>
    </div>
    <p class="section-note">本层汇总各统计口径的样本覆盖：凡由候选编年（未人工复核）支撑的数字都以浅金标注。逐条系年的来源 URL、证据等级、年份类型保存在 output/assets/competition/imagery_tide_dating.json。下方 160 个词均可点开唐宋证据句。</p>
    <div class="coverage-tiles" id="coverageTiles"></div>
    <div class="panel" style="padding:12px;overflow:auto"><table class="data-table" id="coverageTable"></table></div>
    <div class="section-head" style="margin-top:20px"><h2 style="font-size:21px">160 词证据入口</h2><div class="section-kicker">点击任一词查看唐宋证据句、分母与命中率</div></div>
    <div class="term-browser" id="evidenceBrowser"></div>
  </section>

  <details class="method" id="method">
    <summary>方法、排除与证据审计</summary>
    <div class="method-body" id="methodBody"></div>
  </details>
</main>

<footer>
  <div class="wrap">
    <nav class="site-nav" aria-label="参赛页面导航">
      <a href="29_参赛导航.html">29 导航</a>
      <a href="30_诗行万里_参赛版.html">30 总入口</a>
      <a href="31_凝望罗盘.html">31 凝望罗盘</a>
      <a href="32_身与心双层地图.html">32 身与心双层地图</a>
      <a href="33_平行时空759.html">33 平行时空759</a>
      <a href="34_一字识诗人.html">34 一字识诗人</a>
      <a href="35_两种孤独与夸张签名.html">35 两种孤独与夸张签名</a>
      <a href="36_同龄对齐.html">36 同龄对齐</a>
      <a href="37_可听的诗.html">37 可听的诗</a>
      <span class="here">38 唐宋意象潮汐（本页）</span>
      <a href="39_诗人自述生命卷.html">39 诗人自述生命卷</a>
    </nav>
    <div>诗行万里 · 数媒可视化参赛版 · 本页离线生成，统计口径、逐篇系年来源与证据审计见“方法、排除与证据审计”。</div>
  </div>
</footer>
'''

TEMPLATE_SCRIPT = r'''
(function(){
"use strict";
var D=window.IMAGERY_TIDE_DATA;
var TANG="#456f8a", SONG="#a34f44", JADE="#28766d", INK="#222822", MUTED="#667068", LINE="#d4dbd3";
var GOLD="#a8762b", UM_TANG="#8a93a0", UM_SONG="#6d7a88";
var numberFmt=new Intl.NumberFormat("zh-CN");
function fmt(value){return typeof value==="number"?numberFmt.format(value):"—"}
function rate(value){return typeof value==="number"?Number(value).toFixed(2):"—"}
function pct(value){return typeof value==="number"?(value*100).toFixed(1)+"%":"—"}
function signed(value){return typeof value==="number"?(value>0?"+":"")+Number(value).toFixed(2):"—"}
function el(tag,cls,text){var node=document.createElement(tag);if(cls)node.className=cls;if(text!==undefined)node.textContent=text;return node}
function categoryColor(name){var item=D.categoryInfo.find(function(row){return row.name===name});return item?item.color:MUTED}
function gradeText(grades){return "A"+grades.A+" / B"+grades.B+" / C"+grades.C}
var wordMap={};D.wordStats.forEach(function(row){wordMap[row.word]=row});

var audit=document.getElementById("auditStrip");
var datingMeta=D.meta.datingCoverage||{};
[
  [fmt(D.meta.generatedFromPoems)+" 条","名家全作品"],
  ["唐 "+fmt(D.meta.dynastyCounts["唐"])+" · 宋 "+fmt(D.meta.dynastyCounts["宋"]),"二分样本（过渡期另列）"],
  [fmt(D.meta.totalChineseChars)+" 字","正文汉字分母"],
  [fmt(D.meta.includedObjectiveTerms)+" / "+fmt(D.meta.lexiconSourceTerms)+" 词","纳入 / 原词典"],
  [fmt(datingMeta.datedWorks)+" 条 · "+pct(datingMeta.workCoverage),"逐篇系年（覆盖作品）"],
  [fmt(D.historicalLens.reviewedNodeCount)+" 节点 · "+fmt(D.historicalLens.chapteredNodeCount)+" 入章","历史镜头"]
].forEach(function(item){var span=el("span");span.appendChild(el("b","",item[0]));span.appendChild(document.createTextNode(" "+item[1]));audit.appendChild(span)});

/* ============ 第一层 · 关键计算结论 ============ */
function renderConclusions(){
  var host=document.getElementById("conclusionGrid");
  D.conclusions.forEach(function(item){
    var card=el("article","conclusion-card");
    card.appendChild(el("h3","",item.headline));
    card.appendChild(el("p","",item.body));
    var foot=el("div","card-foot");
    var btn=el("button","word-chip","证据 · "+item.evidenceWord);
    btn.type="button";btn.title="查看该词的唐宋证据句与分母";
    btn.addEventListener("click",function(){
      showAggregateEvidence(item.evidenceWord);
      document.getElementById("aggregateEvidence").scrollIntoView({behavior:"smooth",block:"center"});
    });
    foot.appendChild(btn);
    card.appendChild(foot);
    host.appendChild(card);
  });
}

function renderChangeAnalysis(){
  var data=D.changeAnalysis,host=document.getElementById("changeAnalysis");
  if(!data||!host)return;
  var head=el("div","change-analysis-head");
  var titleBox=el("div");
  titleBox.appendChild(el("div","change-analysis-kicker","变化解读 · ANALYSIS"));
  titleBox.appendChild(el("h3","",data.title));
  head.appendChild(titleBox);
  head.appendChild(el("p","change-thesis",data.thesis));
  host.appendChild(head);
  var grid=el("div","change-grid");
  data.findings.forEach(function(item,index){
    var card=el("article","change-finding");
    card.appendChild(el("div","change-index",String(index+1).padStart(2,"0")));
    var body=el("div");
    body.appendChild(el("div","change-eyebrow",item.eyebrow));
    body.appendChild(el("h4","",item.title));
    body.appendChild(el("p","",item.body));
    var evidence=el("div","change-evidence");
    (item.evidenceWords||[]).forEach(function(word){
      if(!wordMap[word])return;
      var button=el("button","word-chip","原句 · "+word);
      button.type="button";
      button.addEventListener("click",function(){
        showAggregateEvidence(word);
        var target=document.getElementById("aggregateEvidence");
        window.scrollTo({top:target.getBoundingClientRect().top+window.scrollY-24,behavior:"smooth"});
      });
      evidence.appendChild(button);
    });
    body.appendChild(evidence);
    card.appendChild(body);
    grid.appendChild(card);
  });
  host.appendChild(grid);
  var boundary=el("p","change-boundary");
  boundary.appendChild(el("b","","解释边界："));
  boundary.appendChild(document.createTextNode(data.boundary));
  host.appendChild(boundary);
}

/* ============ 第二层 · 唐宋两端 ============ */
var dynastyGrid=document.getElementById("dynastyGrid");
[["唐","tang"],["宋","song"]].forEach(function(pair){var name=pair[0],stats=D.dynastyAggregates[name],strip=el("div","dynasty-strip "+pair[1]);strip.appendChild(el("h3","",name));[[fmt(stats.poemRecords),"正文记录"],[fmt(stats.chineseChars),"正文汉字"],[fmt(stats.rawHits),"原始命中"],[rate(stats.ratePer10k),"每万字 · 语料加权"],[rate(stats.authorEqualRatePer10k),"每万字 · 作者等权"]].forEach(function(item){var metric=el("div","metric");metric.appendChild(el("b","",item[0]));metric.appendChild(el("span","",item[1]));strip.appendChild(metric)});dynastyGrid.appendChild(strip)});
var authorEqualKicker=document.getElementById("authorEqualKicker");
authorEqualKicker.textContent="唐 "+D.authorEqualOverall.tang.authors+" 人 · 宋 "+D.authorEqualOverall.song.authors+" 人 · 总体等权率 唐 "+rate(D.authorEqualOverall.tang.meanRate)+" / 宋 "+rate(D.authorEqualOverall.song.meanRate);

var comparisonRows=D.comparisonWords.slice().reverse().map(function(word){return wordMap[word]});
var comparisonChart=window.echarts.init(document.getElementById("comparisonChart"));
var comparisonMax=Math.ceil(Math.max.apply(null,comparisonRows.map(function(row){return Math.max(row.tang.ratePer10k,row.song.ratePer10k)}))*1.12/5)*5;
comparisonChart.setOption({
  animationDuration:700,textStyle:{color:INK,fontFamily:'"Microsoft YaHei",sans-serif'},grid:{left:16,right:34,top:26,bottom:48,containLabel:true},
  xAxis:{type:"value",max:comparisonMax,name:"命中 / 每万正文汉字",nameLocation:"middle",nameGap:31,nameTextStyle:{fontSize:10,color:MUTED},axisLabel:{color:MUTED,fontSize:10},splitLine:{lineStyle:{color:"#e4e8e2"}}},
  yAxis:{type:"category",data:comparisonRows.map(function(row){return row.word}),axisTick:{show:false},axisLine:{show:false},axisLabel:{fontFamily:"KaiTi,STKaiti,serif",fontSize:15,color:INK}},
  tooltip:{trigger:"item",confine:true,formatter:function(params){var row=params.data;return "<b>"+row.word+"</b> · "+row.category+"<br>唐："+row.tang.rawHits+"次 · "+rate(row.tang.ratePer10k)+"/万字 · 命中 "+row.tang.poemsWithHit+"/"+row.tang.poemRecords+" 条（"+pct(row.tang.poemHitRate)+"） · 分母"+fmt(row.tang.chineseCharDenominator)+"字<br>宋："+row.song.rawHits+"次 · "+rate(row.song.ratePer10k)+"/万字 · 命中 "+row.song.poemsWithHit+"/"+row.song.poemRecords+" 条（"+pct(row.song.poemHitRate)+"） · 分母"+fmt(row.song.chineseCharDenominator)+"字"}},
  series:[{type:"custom",renderItem:function(params,api){var y=api.coord([0,api.value(2)])[1],x1=api.coord([api.value(0),api.value(2)])[0],x2=api.coord([api.value(1),api.value(2)])[0];return{type:"group",children:[{type:"line",shape:{x1:x1,y1:y,x2:x2,y2:y},style:{stroke:"#aeb8af",lineWidth:3}},{type:"circle",shape:{cx:x1,cy:y,r:6},style:{fill:TANG,stroke:"#fff",lineWidth:2}},{type:"circle",shape:{cx:x2,cy:y,r:6},style:{fill:SONG,stroke:"#fff",lineWidth:2}}]}} ,data:comparisonRows.map(function(row,index){return Object.assign({value:[row.tang.ratePer10k,row.song.ratePer10k,index]},row)}),encode:{x:[0,1],y:2}}]
});
comparisonChart.on("click",function(params){if(params.data&&params.data.word)showAggregateEvidence(params.data.word)});

var contrastRow=document.getElementById("contrastRow");contrastRow.appendChild(el("span","contrast-label","高频词中的率差前列："));
D.topContrasts.forEach(function(row){var button=el("button","word-chip",row.word+" · "+(row.deltaSongMinusTang>0?"宋+":"唐+")+rate(row.absoluteDelta));button.type="button";button.style.borderLeft="3px solid "+categoryColor(row.category);button.title="点击查看完整唐宋证据";button.addEventListener("click",function(){showAggregateEvidence(row.word)});contrastRow.appendChild(button)});

function showAggregateEvidence(word){
  var host=document.getElementById("aggregateEvidence"),row=wordMap[word],ev=D.evidence[word];host.innerHTML="";
  var title=el("h3","",word),cat=el("span","word-category",row.category+" · 全库"+fmt(row.combinedRawHits)+"次");title.style.color=categoryColor(row.category);title.appendChild(cat);host.appendChild(title);
  if(row.singleCharacter)host.appendChild(el("div","word-warning","单字匹配有构词与多义歧义：这里展示的是可复现的字符串特征，不是语义证明。"));
  var sides=el("div","word-sides");[["唐","tang",row.tang],["宋","song",row.song]].forEach(function(item){var side=el("div","word-side "+item[1]);side.appendChild(el("b","",item[0]+" · "+rate(item[2].ratePer10k)+" / 万字"));side.appendChild(document.createTextNode("原始 "+fmt(item[2].rawHits)+" 次 · 分母 "+fmt(item[2].chineseCharDenominator)+" 字 · 命中 "+fmt(item[2].poemsWithHit)+" / "+fmt(item[2].poemRecords)+" 条（"+pct(item[2].poemHitRate)+"）"));sides.appendChild(side)});host.appendChild(sides);
  var eq=row.authorEqual;
  if(eq)host.appendChild(el("p","evidence-method","作者等权（每人一票）：唐 "+rate(eq.tang.meanRate)+" / 宋 "+rate(eq.song.meanRate)+" · 等权率差 "+signed(eq.deltaSongMinusTang)+" · 样本 唐"+eq.tang.authors+"人 / 宋"+eq.song.authors+"人"));
  var quotes=el("div","quotes");ev.corpus.forEach(function(item){appendHighlightedQuote(quotes,item,"证据句完整保留")});if(!ev.corpus.length)quotes.appendChild(el("p","evidence-method","该纳入词在当前语料中没有保留命中。"));host.appendChild(quotes);host.appendChild(el("p","evidence-method","证据句由实际计数位置回溯；同词在诗文正文的原始命中次数随引文列出。唐宋率差为文本共现提示，可与时代背景对读，相关不等于因果。"))
}

var categoryChart=window.echarts.init(document.getElementById("categoryChart"));
var categoryRows=D.categoryStats.slice().reverse();
categoryChart.setOption({
  animationDuration:700,textStyle:{color:INK,fontFamily:'"Microsoft YaHei",sans-serif'},grid:{left:18,right:34,top:30,bottom:48,containLabel:true},legend:{data:["唐","宋"],top:6,right:18,textStyle:{color:MUTED}},
  xAxis:{type:"value",name:"命中 / 每万正文汉字",nameLocation:"middle",nameGap:30,nameTextStyle:{fontSize:10,color:MUTED},axisLabel:{color:MUTED,fontSize:10},splitLine:{lineStyle:{color:"#e4e8e2"}}},
  yAxis:{type:"category",data:categoryRows.map(function(row){return row.category+" · "+row.termCount+"词"}),axisTick:{show:false},axisLine:{show:false},axisLabel:{fontSize:12,color:INK}},
  tooltip:{trigger:"axis",axisPointer:{type:"shadow"},confine:true,formatter:function(params){var index=params[0].dataIndex,row=categoryRows[index];return "<b>"+row.category+"</b> · "+row.termCount+"词条<br>唐："+row.tang.rawHits+"次 · "+rate(row.tang.ratePer10k)+"/万字 · "+row.tang.poemsWithHit+"/"+row.tang.poemRecords+"条命中 · 分母"+fmt(row.tang.chineseCharDenominator)+"字<br>宋："+row.song.rawHits+"次 · "+rate(row.song.ratePer10k)+"/万字 · "+row.song.poemsWithHit+"/"+row.song.poemRecords+"条命中 · 分母"+fmt(row.song.chineseCharDenominator)+"字"}},
  series:[{name:"唐",type:"bar",barWidth:10,itemStyle:{color:TANG,borderRadius:[0,2,2,0]},data:categoryRows.map(function(row){return row.tang.ratePer10k})},{name:"宋",type:"bar",barWidth:10,itemStyle:{color:SONG,borderRadius:[0,2,2,0]},data:categoryRows.map(function(row){return row.song.ratePer10k})}]
});

/* 作者等权散点 */
var authorEqualChart=window.echarts.init(document.getElementById("authorEqualChart"));
(function(){
  var points=D.wordStats.filter(function(row){return row.combinedRawHits>0}).map(function(row){return{value:[row.deltaSongMinusTang,row.authorEqual.deltaSongMinusTang],word:row.word,category:row.category,hits:row.combinedRawHits,itemStyle:{color:categoryColor(row.category)}}});
  var maxAbs=Math.max.apply(null,points.map(function(p){return Math.max(Math.abs(p.value[0]),Math.abs(p.value[1]))}));
  var bound=Math.ceil(maxAbs*1.15);
  authorEqualChart.setOption({
    animationDuration:600,textStyle:{color:INK,fontFamily:'"Microsoft YaHei",sans-serif'},
    grid:{left:16,right:22,top:34,bottom:52,containLabel:true},
    xAxis:{type:"value",min:-bound,max:bound,name:"语料加权率差 宋−唐（每万字）",nameLocation:"middle",nameGap:30,nameTextStyle:{fontSize:11,color:MUTED},axisLabel:{color:MUTED,fontSize:10},splitLine:{lineStyle:{color:"#e4e8e2"}}},
    yAxis:{type:"value",min:-bound,max:bound,name:"作者等权率差",nameTextStyle:{fontSize:11,color:MUTED},axisLabel:{color:MUTED,fontSize:10},splitLine:{lineStyle:{color:"#e4e8e2"}}},
    tooltip:{trigger:"item",confine:true,formatter:function(params){var p=params.data;return "<b>"+p.word+"</b> · "+p.category+" · 全库"+fmt(p.hits)+"次<br>语料加权差 "+signed(p.value[0])+" · 作者等权差 "+signed(p.value[1])+"<br>点击查看证据"}},
    series:[{type:"scatter",symbolSize:9,data:points,
      markLine:{silent:true,symbol:"none",lineStyle:{type:"dashed",color:"#b0b8b0",width:1},label:{fontSize:9,color:MUTED},data:[{xAxis:0,label:{formatter:"加权差=0"}},{yAxis:0,label:{formatter:"等权差=0"}}]}},
      {type:"line",silent:true,symbol:"none",lineStyle:{type:"dashed",color:"#9aa89d",width:1.2,opacity:.8},data:[[-bound,-bound],[bound,bound]]}]
  });
  authorEqualChart.on("click",function(params){if(params.data&&params.data.word)showAggregateEvidence(params.data.word)});
})();

/* 留一作者检验表 */
function renderLooTable(){
  var host=document.getElementById("looTable");
  var thead=el("thead");var hr=el("tr");
  ["检验对象","率差·加权","率差·等权","LOO区间·加权","翻转·加权","LOO区间·等权","翻转·等权"].forEach(function(text){hr.appendChild(el("th","",text))});
  thead.appendChild(hr);host.appendChild(thead);
  var tbody=el("tbody");
  var rows=[{word:"全部160词合计",category:"—"}].concat(D.robustness.words);
  rows.forEach(function(row){
    var report=row.category==="—"?D.robustness.overall:D.robustness.words.find(function(item){return item.word===row.word});
    if(!report)return;
    var tr=el("tr");
    tr.appendChild(el("td","",row.word));
    var c1=el("td","num",signed(report.baseGap));tr.appendChild(c1);
    tr.appendChild(Object.assign(el("td","num",signed(report.authorEqualBaseGap)),{}));
    tr.appendChild(el("td","num",(report.looMin===null?"—":signed(report.looMin))+" ~ "+(report.looMax===null?"—":signed(report.looMax))));
    var flipCell=el("td");if(report.flips.length){flipCell.appendChild(el("span","flip-badge",report.flips.length+" 次："+report.flips.join("、")))}else{flipCell.appendChild(el("span","safe-badge","0 · 稳健"))}tr.appendChild(flipCell);
    tr.appendChild(el("td","num",(report.authorEqualLooMin===null?"—":signed(report.authorEqualLooMin))+" ~ "+(report.authorEqualLooMax===null?"—":signed(report.authorEqualLooMax))));
    var eqCell=el("td");if(report.authorEqualFlips.length){eqCell.appendChild(el("span","flip-badge",report.authorEqualFlips.length+" 次："+report.authorEqualFlips.join("、")))}else{eqCell.appendChild(el("span","safe-badge","0 · 稳健"))}tr.appendChild(eqCell);
    if(row.category==="—")tr.style.fontWeight="700";
    tbody.appendChild(tr);
  });
  host.appendChild(tbody);
}

/* ============ 第三层 · 年代演变 ============ */
function renderChronologyCoverage(){
  var host=document.getElementById("chronologyCoverage");
  var cov=D.chronology.coverage;
  var candidateCount=(cov.byTier["candidate-B"]||0)+(cov.byTier["candidate-C"]||0);
  var curatedCount=(cov.byTier["curated-B"]||0)+(cov.byTier["curated-C"]||0);
  var verifiedInBinary=cov.byTier["verified-B"]||0;
  var verifiedNote="人工复核系年 · 进入二分统计";
  [
    [fmt(cov.datedWorks)+" / "+fmt(cov.binaryWorks)+"（"+pct(cov.workCoverage)+"）","逐篇系年作品"],
    [pct(cov.charCoverage),"系年正文占比（"+fmt(cov.datedChars)+" / "+fmt(cov.totalChars)+" 字）"],
    [fmt(verifiedInBinary),verifiedNote],
    [fmt(curatedCount+candidateCount),"候选编年（六诗人CSV "+fmt(curatedCount)+"；搜韵 "+fmt(candidateCount)+"）",true],
    [fmt(cov.datedAuthors)+" / "+fmt(cov.totalAuthors),"系年作者覆盖"],
    [fmt(cov.supportedBins)+" / "+fmt(cov.bins),"满足样本量的 25 年箱"]
  ].forEach(function(item){
    var span=el("span",item[2]?"candidate-tag":"");
    span.appendChild(el("b","",item[0]));span.appendChild(document.createTextNode(" "+item[1]));host.appendChild(span);
  });
}

var timelineChart=window.echarts.init(document.getElementById("timelineChart"));
var TIER_ORDER=["verified-B","curated-B","curated-C","candidate-B","candidate-C"];
var TIER_COLORS={"verified-B":"#1d5c50","curated-B":"#4f8292","curated-C":"#7fa8b5","candidate-B":"#c9a227","candidate-C":"#e6d3a0"};
var TIER_SHORT={"verified-B":"人工复核","curated-B":"CSV候选B","curated-C":"CSV候选C","candidate-B":"搜韵候选B","candidate-C":"搜韵候选C"};
var trendVisible={};
D.chronology.trendWords.slice(0,3).forEach(function(word){trendVisible[word]=true});
function binLabel(bin){return String(bin.start)}
function eventMarkData(){
  var data=[];
  D.historicalLens.events.forEach(function(event){
    var bin=D.chronology.bins.find(function(item){return item.start<=event.year&&event.year<item.start+D.chronology.binWidth});
    if(!bin)return;
    data.push({xAxis:binLabel(bin),label:{formatter:event.year+"\n"+event.label,fontSize:9,color:"#8a4a42",lineHeight:13},lineStyle:{color:"#a34f44",type:"dashed",width:1,opacity:.55}});
  });
  return data;
}
function timelineOption(){
  var bins=D.chronology.bins;
  var series=[];
  TIER_ORDER.forEach(function(tier,index){
    var hasTier=bins.some(function(bin){return(bin.tiers[tier]||0)>0});
    if(!hasTier)return;
    series.push({name:TIER_SHORT[tier],type:"bar",stack:"coverage",yAxisIndex:1,barWidth:"62%",z:1,
      itemStyle:{color:TIER_COLORS[tier]},
      data:bins.map(function(bin){return bin.tiers[tier]||0}),
      markLine:index===0?{silent:true,symbol:"none",data:eventMarkData()}:undefined});
  });
  D.chronology.trendWords.forEach(function(word){
    if(!trendVisible[word])return;
    var color=categoryColor(wordMap[word].category);
    series.push({name:word+" 率",type:"line",yAxisIndex:0,z:5,symbol:"circle",symbolSize:5,connectNulls:false,
      lineStyle:{color:color,width:1.6},itemStyle:{color:color},
      data:bins.map(function(bin){var cell=bin.trend[word];return cell&&cell.supported?cell.ratePer10k:null})});
    var ciData=[];
    bins.forEach(function(bin,index){var cell=bin.trend[word];if(cell&&cell.supported)ciData.push([index,cell.ciLow,cell.ciHigh])});
    series.push({name:word+" 置信带",type:"custom",yAxisIndex:0,z:4,silent:true,
      renderItem:function(params,api){
        var x=api.coord([api.value(0),0])[0];
        var low=api.coord([api.value(0),api.value(1)])[1];
        var high=api.coord([api.value(0),api.value(2)])[1];
        var w=5;
        return{type:"group",children:[
          {type:"line",shape:{x1:x,y1:low,x2:x,y2:high},style:{stroke:color,lineWidth:1.3}},
          {type:"line",shape:{x1:x-w,y1:low,x2:x+w,y2:low},style:{stroke:color,lineWidth:1.1}},
          {type:"line",shape:{x1:x-w,y1:high,x2:x+w,y2:high},style:{stroke:color,lineWidth:1.1}}]};
      },
      data:ciData,encode:{x:0,y:[1,2]}});
  });
  return {
    animation:false,textStyle:{color:INK,fontFamily:'"Microsoft YaHei",sans-serif'},
    legend:{top:4,left:14,type:"scroll",textStyle:{color:MUTED,fontSize:10},data:series.map(function(item){return item.name})},
    grid:{left:20,right:24,top:56,bottom:64,containLabel:true},
    xAxis:{type:"category",data:bins.map(binLabel),name:"25年箱（起始年）",nameLocation:"middle",nameGap:34,nameTextStyle:{fontSize:10,color:MUTED},axisLabel:{color:MUTED,fontSize:10,rotate:38},axisTick:{show:false},axisLine:{show:false}},
    yAxis:[{type:"value",name:"命中/每万字",nameTextStyle:{fontSize:10,color:MUTED},axisLabel:{color:MUTED,fontSize:9},splitLine:{lineStyle:{color:"#e8ece7"}}},
           {type:"value",name:"作品数",nameTextStyle:{fontSize:10,color:MUTED},axisLabel:{color:MUTED,fontSize:9},splitLine:{show:false}}],
    tooltip:{trigger:"axis",confine:true,formatter:function(params){
      var index=params[0].dataIndex,bin=bins[index];if(!bin)return "";
      var html="<b>"+bin.start+"–"+bin.end+"</b> · 作品 "+fmt(bin.works)+" · 正文 "+fmt(bin.chars)+" 字 · 作者 "+bin.authors+" 人<br>";
      var tierBits=TIER_ORDER.filter(function(tier){return(bin.tiers[tier]||0)>0}).map(function(tier){return TIER_SHORT[tier]+" "+bin.tiers[tier]});
      if(tierBits.length)html+="证据级别："+tierBits.join(" · ")+"<br>";
      D.chronology.trendWords.forEach(function(word){
        if(!trendVisible[word])return;
        var cell=bin.trend[word];if(!cell)return;
        html+=word+"："+(cell.supported?rate(cell.ratePer10k)+"/万字（95%CI "+rate(cell.ciLow)+"–"+rate(cell.ciHigh)+"）· "+cell.hits+"次":"样本不足（"+cell.hits+"次）未画点")+"<br>";
      });
      return html;
    }},
    series:series
  };
}
function renderTrendPicks(){
  var host=document.getElementById("trendPicks");
  host.appendChild(el("span","contrast-label","切换趋势词："));
  D.chronology.trendWords.forEach(function(word){
    var label=el("label","trend-pick");
    var input=document.createElement("input");input.type="checkbox";input.checked=!!trendVisible[word];
    input.addEventListener("change",function(){trendVisible[word]=input.checked;timelineChart.setOption(timelineOption(),true)});
    label.appendChild(input);
    var sw=el("span","sw");sw.style.background=categoryColor(wordMap[word].category);label.appendChild(sw);
    label.appendChild(document.createTextNode(word));
    host.appendChild(label);
  });
}

/* ============ 第四层 · 诗人贡献分解 ============ */
var contribChart=window.echarts.init(document.getElementById("contribChart"));
var contribWord=D.authorContribution.words[0].word;
function contribOption(word){
  var entry=D.authorContribution.words.find(function(item){return item.word===word});
  var categories=[],songData=[],tangData=[];
  entry.song.forEach(function(row){categories.push(row.author);songData.push(row.contribution);tangData.push(null)});
  entry.tang.forEach(function(row){categories.push(row.author);songData.push(null);tangData.push(-row.contribution)});
  return {
    animation:false,textStyle:{color:INK,fontFamily:'"Microsoft YaHei",sans-serif'},
    title:{text:"「"+entry.word+"」· 宋唐率差 "+signed(entry.gap)+" /万字（"+entry.category+" · 全库"+fmt(wordMap[entry.word].combinedRawHits)+"次）",left:14,top:6,textStyle:{fontFamily:"KaiTi,STKaiti,serif",fontSize:16,color:INK},subtext:"宋侧各作者贡献之和=宋率，唐侧同理取负；图中只显示贡献前6位",subtextStyle:{fontSize:10,color:MUTED}},
    grid:{left:16,right:40,top:62,bottom:42,containLabel:true},
    xAxis:{type:"value",name:"对率差的贡献（每万字）",nameLocation:"middle",nameGap:28,nameTextStyle:{fontSize:10,color:MUTED},axisLabel:{color:MUTED,fontSize:10},splitLine:{lineStyle:{color:"#e4e8e2"}}},
    yAxis:{type:"category",data:categories,axisTick:{show:false},axisLine:{show:false},axisLabel:{fontSize:12,color:INK,fontFamily:"KaiTi,STKaiti,serif"}},
    tooltip:{trigger:"axis",axisPointer:{type:"shadow"},confine:true,formatter:function(params){
      var html="";
      params.forEach(function(item){
        if(item.value===null||item.value===undefined)return;
        var side=item.seriesName==="宋侧贡献"?entry.song:entry.tang;
        var row=side.find(function(x){return x.author===item.name});
        if(!row)return;
        html+="<b>"+row.author+"</b>（"+item.seriesName.replace("贡献","")+"）<br>贡献 "+signed(item.seriesName==="宋侧贡献"?row.contribution:-row.contribution)+" /万字 · 命中 "+row.hits+" 次<br>占朝代正文 "+pct(row.charsShare)+" · 本人每万字 "+rate(row.ownRate)+"<br>";
      });
      return html||"";
    }},
    series:[
      {name:"宋侧贡献",type:"bar",barMaxWidth:13,itemStyle:{color:SONG,borderRadius:[0,2,2,0]},data:songData},
      {name:"唐侧贡献",type:"bar",barMaxWidth:13,itemStyle:{color:TANG,borderRadius:[2,0,0,2]},data:tangData},
      {name:"零线",type:"line",silent:true,symbol:"none",lineStyle:{color:"#98a29a",width:1},data:categories.map(function(_c,i){return[i,0]})}]
  };
}
function renderContribPicks(){
  var host=document.getElementById("contribPicks");
  host.appendChild(el("span","contrast-label","选择意象词："));
  D.authorContribution.words.forEach(function(entry){
    var button=el("button","word-chip",entry.word+" · "+signed(entry.gap));
    button.type="button";button.style.borderLeft="3px solid "+categoryColor(entry.category);
    if(entry.word===contribWord)button.style.borderColor=JADE;
    button.addEventListener("click",function(){contribWord=entry.word;contribChart.setOption(contribOption(contribWord),true);renderContribPicks()});
    host.appendChild(button);
  });
}
function renderAuthorTable(){
  var host=document.getElementById("authorTable");
  var thead=el("thead"),hr=el("tr");
  ["朝代","作者","正文记录","正文汉字","每万字率","高频意象词 TOP3"].forEach(function(text){hr.appendChild(el("th","",text))});
  thead.appendChild(hr);host.appendChild(thead);
  var tbody=el("tbody");
  D.authorStats.forEach(function(row){
    var tr=el("tr");
    tr.appendChild(el("td","",row.dynasty));
    tr.appendChild(el("td","",row.author));
    tr.appendChild(Object.assign(el("td","num",fmt(row.poems))));
    tr.appendChild(Object.assign(el("td","num",fmt(row.chineseChars))));
    tr.appendChild(Object.assign(el("td","num",rate(row.ratePer10k))));
    tr.appendChild(el("td","",row.topWords.slice(0,3).map(function(item){return item.word+"×"+item.rawHits}).join(" · ")));
    tbody.appendChild(tr);
  });
  host.appendChild(tbody);
}

/* ============ 第五层 · 体裁分层 ============ */
function renderGenreNote(){
  var host=document.getElementById("genreNote");
  D.genre.groups.forEach(function(group){
    var tile=el("div","coverage-tile");
    tile.style.borderTop="3px solid "+(group.genre==="poetry"?(group.dynasty==="唐"?TANG:SONG):(group.genre==="ci"?GOLD:(group.dynasty==="唐"?UM_TANG:UM_SONG)));
    tile.appendChild(el("b","",group.genreLabel+" · "+group.dynasty));
    if(group.empty){tile.appendChild(el("span","","上游无该朝样本，不做该侧统计"))}
    else{var span2=el("span");span2.appendChild(document.createTextNode(fmt(group.poems)+" 条 · "+fmt(group.chars)+" 字 · "+rate(group.ratePer10k)+"/万字 · "+group.poets+" 人"));tile.appendChild(span2)}
    host.appendChild(tile);
  });
}
var genreChart=window.echarts.init(document.getElementById("genreChart"));
(function(){
  var seriesDefs=[
    {key:"poetryTang",name:"诗·唐",color:TANG},
    {key:"poetrySong",name:"诗·宋",color:SONG},
    {key:"ciSong",name:"词·宋",color:GOLD},
    {key:"unmarkedTang",name:"未标·唐",color:UM_TANG},
    {key:"unmarkedSong",name:"未标·宋",color:UM_SONG}
  ];
  var rows=D.genre.categoryStats.slice().reverse();
  genreChart.setOption({
    animationDuration:600,textStyle:{color:INK,fontFamily:'"Microsoft YaHei",sans-serif'},
    grid:{left:18,right:30,top:34,bottom:48,containLabel:true},
    legend:{top:4,right:16,textStyle:{color:MUTED,fontSize:11}},
    xAxis:{type:"value",name:"命中 / 每万正文汉字",nameLocation:"middle",nameGap:30,nameTextStyle:{fontSize:10,color:MUTED},axisLabel:{color:MUTED,fontSize:10},splitLine:{lineStyle:{color:"#e4e8e2"}}},
    yAxis:{type:"category",data:rows.map(function(row){return row.category+" · "+row.termCount+"词"}),axisTick:{show:false},axisLine:{show:false},axisLabel:{fontSize:12,color:INK}},
    tooltip:{trigger:"axis",axisPointer:{type:"shadow"},confine:true,formatter:function(params){
      var index=params[0].dataIndex,row=D.genre.categoryStats.slice().reverse()[index];
      var html="<b>"+row.category+"</b> · "+row.termCount+"词条<br>";
      seriesDefs.forEach(function(def){
        var cell=row[def.key];if(!cell)return;
        html+=def.name+"："+cell.hits+"次 · "+rate(cell.ratePer10k)+"/万字<br>";
      });
      html+="词·唐：上游无样本，不做该侧统计";
      return html;
    }},
    series:seriesDefs.map(function(def){
      return {name:def.name,type:"bar",barMaxWidth:9,itemStyle:{color:def.color,borderRadius:[0,2,2,0]},data:rows.map(function(row){return row[def.key].ratePer10k})};
    })
  });
})();
function renderGenreTable(){
  var host=document.getElementById("genreTable");
  var thead=el("thead"),hr=el("tr");
  ["词","类别","诗·唐","诗·宋","词·宋","未标·唐","未标·宋","词−诗（宋侧）"].forEach(function(text){hr.appendChild(el("th","",text))});
  thead.appendChild(hr);host.appendChild(thead);
  var tbody=el("tbody");
  D.genre.wordStats.forEach(function(row){
    var tr=el("tr","rowlink");
    tr.title="点击查看该词的唐宋证据句";
    tr.appendChild(el("td","",row.word));
    tr.appendChild(el("td","",row.category));
    [["poetryTang"],["poetrySong"],["ciSong"],["unmarkedTang"],["unmarkedSong"]].forEach(function(def){
      var cell=row[def[0]];
      tr.appendChild(Object.assign(el("td","num",rate(cell.ratePer10k)+" ("+fmt(cell.hits)+")")));
    });
    tr.appendChild(Object.assign(el("td","num",signed(row.ciMinusPoetrySong))));
    tr.addEventListener("click",function(){showAggregateEvidence(row.word);document.getElementById("aggregateEvidence").scrollIntoView({behavior:"smooth",block:"center"})});
    tbody.appendChild(tr);
  });
  host.appendChild(tbody);
}

/* ============ 第六层 · 共现与语境迁移 ============ */
function renderStablePairs(){
  var host=document.getElementById("stablePairsTable");
  var thead=el("thead"),hr=el("tr");
  ["意象对","类别","唐·共现句","宋·共现句"].forEach(function(text){hr.appendChild(el("th","",text))});
  thead.appendChild(hr);host.appendChild(thead);
  var tbody=el("tbody");
  D.cooccurrence.stablePairs.forEach(function(row){
    var tr=el("tr");
    tr.appendChild(el("td","",row.pair[0]+" + "+row.pair[1]));
    tr.appendChild(el("td","",row.category));
    tr.appendChild(Object.assign(el("td","num",fmt(row.tangCount))));
    tr.appendChild(Object.assign(el("td","num",fmt(row.songCount))));
    tbody.appendChild(tr);
  });
  host.appendChild(tbody);
}
function renderDivergentPairs(){
  var host=document.getElementById("divergentPairsTable");
  var thead=el("thead"),hr=el("tr");
  ["意象对","唐·句","宋·句","lift唐","lift宋","Δlift"].forEach(function(text){hr.appendChild(el("th","",text))});
  thead.appendChild(hr);host.appendChild(thead);
  var tbody=el("tbody");
  D.cooccurrence.divergentPairs.forEach(function(row){
    var tr=el("tr","rowlink");
    tr.title="点击查看该共现对的唐宋原句";
    tr.appendChild(el("td","",row.pair[0]+" + "+row.pair[1]));
    tr.appendChild(Object.assign(el("td","num",fmt(row.tangCount))));
    tr.appendChild(Object.assign(el("td","num",fmt(row.songCount))));
    tr.appendChild(Object.assign(el("td","num",rate(row.tangLift))));
    tr.appendChild(Object.assign(el("td","num",rate(row.songLift))));
    var delta=el("td","num",signed(row.liftDelta));
    delta.style.fontWeight="700";delta.style.color=row.liftDelta>0?SONG:TANG;
    tr.appendChild(delta);
    tr.addEventListener("click",function(){renderPairEvidence(row.pair)});
    tbody.appendChild(tr);
  });
  host.appendChild(tbody);
}
function appendPairQuote(container,item,extra){
  var sentence=item.sentence;
  var marks=[];
  item.pair.forEach(function(word){
    var idx=sentence.indexOf(word);
    if(idx>=0)marks.push([idx,idx+word.length,word]);
  });
  marks.sort(function(a,b){return a[0]-b[0]});
  var quote=el("blockquote","quote");
  var cursor=0;
  marks.forEach(function(mark){
    if(mark[0]<cursor)return;
    quote.appendChild(document.createTextNode(sentence.slice(cursor,mark[0])));
    quote.appendChild(el("mark","",sentence.slice(mark[0],mark[1])));
    cursor=mark[1];
  });
  quote.appendChild(document.createTextNode(sentence.slice(cursor)));
  var source=item.dynasty+" · "+item.poet+"《"+item.title+"》 · 共现对「"+item.pair[0]+" + "+item.pair[1]+"」句内同时出现";
  if(extra)source+=" · "+extra;
  quote.appendChild(el("cite","",source));
  container.appendChild(quote);
}
function renderPairEvidence(pair){
  var host=document.getElementById("pairEvidence");
  host.innerHTML="";
  host.appendChild(el("h4","","共现句证据 · "+pair[0]+" + "+pair[1]));
  var ev=D.cooccurrence.evidence[pair[0]+"+"+pair[1]];
  var quotes=el("div","quotes");
  var total=0;
  if(ev){
    ["tang","song"].forEach(function(side){
      (ev[side]||[]).forEach(function(item){appendPairQuote(quotes,item,item.dynasty==="唐"?"唐侧共现句":"宋侧共现句");total++});
    });
  }
  if(!total)quotes.appendChild(el("p","evidence-method","该共现对暂未保留原句样本。"));
  host.appendChild(quotes);
}
function renderCollocates(){
  var host=document.getElementById("collocateGrid");
  D.cooccurrence.collocates.forEach(function(entry){
    var card=el("div","collocate-card");
    card.style.borderLeft="3px solid "+categoryColor(entry.category);
    card.appendChild(el("h4","",entry.word));
    [["tang","唐","tang"],["song","宋","song"]].forEach(function(side){
      var title=el("div","col-title");
      title.appendChild(el("b","",side[1]+"·句内高频搭配"));
      title.appendChild(el("b","",entry[side[0]].length?"共现句数":"无≥8句搭配"));
      card.appendChild(title);
      var words=el("div","col-words");
      if(entry[side[0]].length){
        entry[side[0]].forEach(function(item){
          var line=el("div");
          line.appendChild(el("span","",""));
          var name=el("span","",item.word);
          var count=document.createElement("b");count.textContent=" ×"+item.count;
          line.appendChild(name);line.appendChild(count);
          words.appendChild(line);
        });
      }else{
        words.appendChild(el("span","","—"));
      }
      card.appendChild(words);
    });
    host.appendChild(card);
  });
}

/* ============ 第七层 · 覆盖率与证据入口 ============ */
function renderCoverage(){
  var tiles=document.getElementById("coverageTiles");
  var cov=D.chronology.coverage;
  var candidateCount=(cov.byTier["candidate-B"]||0)+(cov.byTier["candidate-C"]||0);
  var curatedCount=(cov.byTier["curated-B"]||0)+(cov.byTier["curated-C"]||0);
  var verifiedInBinary=cov.byTier["verified-B"]||0;
  [
    [pct(cov.workCoverage),"逐篇系年作品覆盖（"+fmt(cov.datedWorks)+" / "+fmt(cov.binaryWorks)+" 条）"],
    [pct(cov.charCoverage),"系年正文汉字覆盖（"+fmt(cov.datedChars)+" 字）"],
    [fmt(verifiedInBinary),"人工复核系年包 · B 级证据（进入二分统计）"],
    [fmt(candidateCount+curatedCount),"候选编年 · 六诗人CSV "+fmt(curatedCount)+" / 搜韵 "+fmt(candidateCount)+"（浅金标注）"],
    [fmt(cov.datedAuthors)+" / "+fmt(cov.totalAuthors),"系年作者覆盖"],
    [fmt(cov.supportedBins)+" / "+fmt(cov.bins),"满足样本量的 25 年箱"]
  ].forEach(function(item){
    var tile=el("div","coverage-tile");
    tile.appendChild(el("b","",item[0]));
    tile.appendChild(el("span","",item[1]));
    if(item[1].indexOf("候选")>=0)tile.style.borderTop="3px solid #c9a227";
    tiles.appendChild(tile);
  });
  var table=document.getElementById("coverageTable");
  var thead=el("thead"),hr=el("tr");
  ["口径","样本量","覆盖 / 分母","说明"].forEach(function(text){hr.appendChild(el("th","",text))});
  thead.appendChild(hr);table.appendChild(thead);
  var tbody=el("tbody");
  function addRow(cells){var tr=el("tr");cells.forEach(function(cell,index){tr.appendChild(index===0?el("td","",cell):Object.assign(el("td","num",cell)))});tbody.appendChild(tr)}
  addRow(["逐篇系年 · 唐",fmt(cov.byDynasty["唐"].works),pct(cov.byDynasty["唐"].workCoverage),"分母为唐全部正文记录 "+fmt(cov.byDynasty["唐"].poemRecords)+" 条"]);
  addRow(["逐篇系年 · 宋",fmt(cov.byDynasty["宋"].works),pct(cov.byDynasty["宋"].workCoverage),"分母为宋全部正文记录 "+fmt(cov.byDynasty["宋"].poemRecords)+" 条"]);
  D.genre.groups.forEach(function(group){
    if(group.empty)return;
    addRow(["体裁 · "+group.genreLabel+"（"+group.dynasty+"侧）",fmt(group.poems)+" 条",fmt(group.chars)+" 字","上游="+group.genreLabel+" · 每万字 "+rate(group.ratePer10k)]);
  });
  addRow(["句子总数 · 唐",fmt(D.dynastyAggregates["唐"].sentences),"—","共现分析分母"]);
  addRow(["句子总数 · 宋",fmt(D.dynastyAggregates["宋"].sentences),"—","共现分析分母"]);
  table.appendChild(tbody);
}
function renderEvidenceBrowser(){
  var host=document.getElementById("evidenceBrowser");
  var termList=el("div","term-list"),termDetail=el("div","term-detail");
  D.method.includedTerms.forEach(function(item){
    var button=el("button","",item.word+" · "+item.combinedRawHits);
    button.type="button";button.title=item.category+" · "+item.description;
    button.addEventListener("click",function(){renderAuditTerm(item.word,termDetail)});
    termList.appendChild(button);
  });
  host.appendChild(termList);host.appendChild(termDetail);
  renderAuditTerm(D.method.includedTerms[0].word,termDetail);
}

/* ============ 方法与审计 ============ */
function methodTable(rows,headers){var table=el("table","method-table"),head=el("tr");headers.forEach(function(text){head.appendChild(el("th","",text))});table.appendChild(head);rows.forEach(function(row){var tr=el("tr");row.forEach(function(text){table.appendChild(document.createTextNode(""));tr.appendChild(el("td","",text))});table.appendChild(tr)});return table}
function renderAuditTerm(word,host){host.innerHTML="";var row=wordMap[word],ev=D.evidence[word];host.appendChild(el("h3","",word+" · "+row.category));host.appendChild(el("p","","全库 "+fmt(row.combinedRawHits)+" 次；唐 "+fmt(row.tang.rawHits)+" 次（"+rate(row.tang.ratePer10k)+"/万字，命中 "+pct(row.tang.poemHitRate)+"），宋 "+fmt(row.song.rawHits)+" 次（"+rate(row.song.ratePer10k)+"/万字，命中 "+pct(row.song.poemHitRate)+"）。作者等权率：唐 "+rate(row.authorEqual.tang.meanRate)+" / 宋 "+rate(row.authorEqual.song.meanRate)+"。"));var quotes=el("div","quotes");ev.corpus.forEach(function(item){appendHighlightedQuote(quotes,item,"160词完整审计入口")});if(!ev.corpus.length)quotes.appendChild(el("p","evidence-method","该词已纳入口径，但当前语料没有保留命中。"));host.appendChild(quotes)}
function renderMethod(){
  var M=D.method,host=document.getElementById("methodBody");
  host.appendChild(el("div","audit-note","本页所有分析结论均由生成脚本从下列数据计算；候选编年（搜韵开放API，needs_review）以浅金标注，未做人工复核。逐条系年的来源、依据与证据等级保存在 output/assets/competition/imagery_tide_dating.json（每条含来源URL、证据级别、年份类型 exact/approximate/range）。"));
  host.appendChild(el("h3","","全语料口径"));host.appendChild(el("p","",M.corpusScope));host.appendChild(el("p","",M.denominator));
  host.appendChild(el("h3","","确定性匹配"));host.appendChild(el("p","",M.matching));host.appendChild(el("p","",M.singleCharacterCaveat));host.appendChild(el("p","",M.evidenceRule));
  host.appendChild(el("h3","","作者等权与留一检验"));host.appendChild(el("p","",M.authorEqualRule));host.appendChild(el("p","",M.looRule));host.appendChild(el("p","",M.contributionRule));
  host.appendChild(el("h3","","逐篇系年口径"));host.appendChild(el("p","",M.datingRule));host.appendChild(el("p","",M.binRule));
  host.appendChild(methodTable(Object.keys(M.datingTierLabels).map(function(tier){return[tier,M.datingTierLabels[tier],fmt((D.meta.datingCoverage.byTier||{})[tier]||0)]}),["证据级别","定义","系年作品条数"]));
  host.appendChild(el("h3","","体裁分层口径"));host.appendChild(el("p","",M.genreRule));
  host.appendChild(el("h3","","共现分析口径"));host.appendChild(el("p","",M.coocRule));
  var grid=el("div","method-grid"),left=el("div"),right=el("div");left.appendChild(el("h3","","纳入类别"));left.appendChild(methodTable(M.includedCategories.map(function(row){return[row.category,String(row.termCount),row.rule]}),["类别","词条","规则"]));right.appendChild(el("h3","","完整词条排除清单 · "+M.exclusions.length+"词"));right.appendChild(methodTable(M.exclusions.map(function(row){return[row.word,row.category,row.reason]}),["词","原类别","原因"]));grid.appendChild(left);grid.appendChild(right);host.appendChild(grid);
  host.appendChild(el("h3","","上下文消歧规则 · 共排除 "+fmt(D.meta.contextExcludedHits)+" 处"));host.appendChild(methodTable(M.contextExclusionRules.map(function(rule){return[rule.word,rule.label,String(rule.excludedHits),rule.reason,rule.examples.map(function(item){return item.poet+"《"+item.title+"》：『"+item.sentence+"』"}).join("\n")]}),["词","规则","排除数","判定","可复核例证"]));
  host.appendChild(el("h3","","历史章节与来源等级"));host.appendChild(el("p","",M.chapterRule));host.appendChild(el("p","",M.chapterCaveat));host.appendChild(el("p","",M.eventAnchorRule));
  host.appendChild(methodTable(D.historicalLens.events.map(function(event){return[String(event.year),event.label,event.sourceName,event.sourceUrl,event.sourceNote]}),["年份","事件","来源","URL","用途说明"]));
  host.appendChild(methodTable(["A","B","C"].map(function(grade){return[grade,M.sourceGradeDefinitions[grade]]}),["等级","原审核数据定义"]));
  host.appendChild(el("h3","","输入哈希与复跑"));Object.keys(M.sourceHashes).forEach(function(path){var p=el("p","hash",path+" · SHA-256 "+M.sourceHashes[path]);host.appendChild(p)});host.appendChild(el("p","",M.contrastRule));host.appendChild(el("p","","页面数据快照：output/assets/competition/imagery_tide_data.json；逐篇系年审计：output/assets/competition/imagery_tide_dating.json；生成脚本：数据可视化脚本/viz_38_imagery_tide.py。脚本零参数复跑，并动态核对全作品总量、唐宋分组、规范证据绑定、38节点、160词证据入口、贡献分解闭合与各分析层样本断言。"))
}

/* ============ 三十六站 · 审核节点镜头（原交互保留） ============ */
var chapters=D.historicalLens.chapters,nodes=D.historicalLens.playbackNodes;
var chapterMap={};chapters.forEach(function(chapter){chapterMap[chapter.id]=chapter});
var eventRail=document.getElementById("eventRail"),eventNodes=[];
D.historicalLens.events.forEach(function(event){
  var node=el("div","event-anchor");
  node.style.left=(3+((event.year-725)/(1210-725))*94)+"%";node.title=event.role+"；来源："+event.sourceName;
  node.appendChild(el("b","",event.year+" "+event.label));
  var link=el("a","","查看来源");link.href=event.sourceUrl;link.target="_blank";link.rel="noreferrer";node.appendChild(link);eventRail.appendChild(node);eventNodes.push(node);
});
function relevantEvent(station){var result=D.historicalLens.events[0];D.historicalLens.events.forEach(function(item){if(item.year<=station.year)result=item});return result}
function renderEventState(station){var active=relevantEvent(station);eventNodes.forEach(function(node,index){node.classList.toggle("active",D.historicalLens.events[index].year===active.year)})}

var tabs=document.getElementById("chapterTabs");
chapters.forEach(function(chapter,index){
  var button=el("button","chapter-tab",chapter.index+" · "+chapter.title);button.type="button";button.setAttribute("role","tab");button.setAttribute("aria-selected",index===0?"true":"false");
  button.appendChild(el("span","years",chapter.startYear+"–"+chapter.endYear+" · "+chapter.nodeCount+"站"));
  button.addEventListener("click",function(){goStation(nodes.findIndex(function(item){return item.chapterId===chapter.id}),true)});tabs.appendChild(button);
});

var routeMap=window.echarts.init(document.getElementById("routeMap"));
var chapterChart=window.echarts.init(document.getElementById("chapterChart"));
var stationIndex=0,progress=0,playing=false,frameHandle=0,autoTimer=0,startTime=0;
var duration=window.matchMedia&&window.matchMedia("(prefers-reduced-motion: reduce)").matches?1:1450;
var playBtn=document.getElementById("playBtn"),prevBtn=document.getElementById("prevBtn"),nextBtn=document.getElementById("nextBtn");
var restartBtn=document.getElementById("restartBtn"),autoToggle=document.getElementById("autoToggle");
var playStatus=document.getElementById("playStatus"),progressBar=document.getElementById("progressBar"),progressTrack=progressBar.parentNode;
function precisionText(value){return({year:"确定年",exact:"确定年",approximate:"约年",disputed:"系年有争议",range:"年份区间"})[value]||"系年未标精度"}
function stationRate(station,word){var hit=station.hits.find(function(item){return item.word===word});return hit?hit.rawHits*10000/station.chineseChars:0}
function routeOption(){
  var visited=nodes.slice(0,stationIndex+1),lines=[];
  for(var i=1;i<visited.length;i++){lines.push({coords:[[visited[i-1].longitude,visited[i-1].latitude],[visited[i].longitude,visited[i].latitude]]})}
  var current=nodes[stationIndex];
  return {animation:false,tooltip:{trigger:"item",confine:true,formatter:function(params){var item=params.data||{};return item.poet?"<b>"+item.year+" · "+item.poet+"</b><br>"+item.placeHistorical+"<br>《"+item.title+"》":"编年连线只表示先后"}},geo:{map:"china",roam:true,zoom:1.18,center:[105,35],label:{show:false},itemStyle:{areaColor:"#edf0eb",borderColor:"#b9c4bb"},emphasis:{itemStyle:{areaColor:"#e2e9e2"}}},series:[{type:"lines",coordinateSystem:"geo",silent:true,polyline:false,data:lines,lineStyle:{color:JADE,width:1.4,opacity:.42,curveness:.12}},{type:"scatter",coordinateSystem:"geo",symbolSize:6,data:visited.slice(0,-1).map(function(item){return{value:[item.longitude,item.latitude],year:item.year,poet:item.poet,placeHistorical:item.placeHistorical,title:item.linkedPoem.title,itemStyle:{color:item.dynasty==="唐"?TANG:SONG}}})},{type:"effectScatter",coordinateSystem:"geo",showEffectOn:"render",rippleEffect:{scale:3,brushType:"stroke"},symbolSize:12,data:[{value:[current.longitude,current.latitude],year:current.year,poet:current.poet,placeHistorical:current.placeHistorical,title:current.linkedPoem.title,itemStyle:{color:current.dynasty==="唐"?TANG:SONG}}],label:{show:true,position:"right",formatter:current.year+" · "+current.placeHistorical,color:INK,fontSize:11}}]};
}
function chapterOption(chapter,station,fraction){
  var rows=chapter.ranking.slice().reverse();
  var values=[];rows.forEach(function(row){values.push(row.ratePer10k,stationRate(station,row.word))});
  var maximum=Math.ceil(Math.max.apply(null,values)*1.16/10)*10||10;
  return {animation:false,textStyle:{color:INK,fontFamily:'"Microsoft YaHei",sans-serif'},grid:{left:18,right:92,top:45,bottom:42,containLabel:true},legend:{data:["章内平均","当前诗文"],right:15,top:8,textStyle:{fontSize:10,color:MUTED}},title:{text:chapter.title+" · 第"+station.stepIndex+"站",subtext:station.year+" · "+station.poet+"《"+station.linkedPoem.title+"》",left:18,top:4,textStyle:{fontFamily:"KaiTi,STKaiti,serif",fontSize:17,color:INK},subtextStyle:{fontSize:10,color:MUTED}},xAxis:{type:"value",max:maximum,name:"命中 / 每万正文汉字",nameLocation:"middle",nameGap:27,nameTextStyle:{fontSize:10,color:MUTED},axisLabel:{color:MUTED,fontSize:9},splitLine:{lineStyle:{color:"#e4e8e2"}}},yAxis:{type:"category",data:rows.map(function(row){return row.word}),axisTick:{show:false},axisLine:{show:false},axisLabel:{fontFamily:"KaiTi,STKaiti,serif",fontSize:14,color:INK}},tooltip:{trigger:"axis",axisPointer:{type:"shadow"},confine:true},series:[{name:"章内平均",type:"bar",barWidth:7,itemStyle:{color:"#aeb8af"},data:rows.map(function(row){return row.ratePer10k})},{name:"当前诗文",type:"bar",barWidth:7,itemStyle:{color:station.dynasty==="唐"?TANG:SONG},data:rows.map(function(row){return Number((stationRate(station,row.word)*fraction).toFixed(4))})}]};
}
function renderCharts(){var station=nodes[stationIndex],chapter=chapterMap[station.chapterId];routeMap.setOption(routeOption(),true);chapterChart.setOption(chapterOption(chapter,station,progress),true);progressBar.style.width=(progress*100)+"%";progressTrack.setAttribute("aria-valuenow",String(Math.round(progress*100)))}
function setPlayButton(){playBtn.textContent=playing?"Ⅱ 暂停":"▶ 播放";playBtn.setAttribute("aria-pressed",playing?"true":"false")}
function clearAuto(){if(autoTimer){clearTimeout(autoTimer);autoTimer=0}}
function finishStation(){playing=false;progress=1;renderCharts();setPlayButton();if(autoToggle.checked&&stationIndex<nodes.length-1){playStatus.textContent="第"+(stationIndex+1)+"站完成 · 即将自动进入下一站";autoTimer=setTimeout(function(){goStation(stationIndex+1,true)},1500)}else if(stationIndex===nodes.length-1){playStatus.textContent="第36站结束 · 可重启或选择章节"}else{playStatus.textContent="第"+(stationIndex+1)+"站已停驻 · 等待点击“下一步”"}}
function tick(now){if(!playing)return;progress=Math.min(1,(now-startTime)/duration);renderCharts();if(progress>=1){finishStation();return}frameHandle=requestAnimationFrame(tick)}
function play(){clearAuto();if(playing)return;if(progress>=1)progress=0;playing=true;startTime=performance.now()-progress*duration;setPlayButton();playStatus.textContent="第"+(stationIndex+1)+"站正在显影 · 完成后停驻";frameHandle=requestAnimationFrame(tick)}
function pause(){if(!playing)return;playing=false;cancelAnimationFrame(frameHandle);setPlayButton();playStatus.textContent="已暂停 · 点击播放继续当前站"}
function goStation(index,shouldPlay){
  clearAuto();cancelAnimationFrame(frameHandle);playing=false;stationIndex=Math.max(0,Math.min(nodes.length-1,index));progress=0;var station=nodes[stationIndex];
  Array.prototype.forEach.call(tabs.children,function(tab,i){tab.setAttribute("aria-selected",chapters[i].id===station.chapterId?"true":"false")});
  prevBtn.disabled=stationIndex===0;nextBtn.disabled=stationIndex===nodes.length-1;renderEventState(station);renderStationContext(station);renderCharts();setPlayButton();
  if(shouldPlay)play();else playStatus.textContent="第"+(stationIndex+1)+"站已就绪"
}
playBtn.addEventListener("click",function(){playing?pause():play()});prevBtn.addEventListener("click",function(){if(stationIndex>0)goStation(stationIndex-1,true)});nextBtn.addEventListener("click",function(){if(stationIndex<nodes.length-1)goStation(stationIndex+1,true)});restartBtn.addEventListener("click",function(){goStation(0,true)});
autoToggle.addEventListener("change",function(){clearAuto();if(autoToggle.checked&&progress>=1&&stationIndex<nodes.length-1){playStatus.textContent="自动连播已开启 · 即将进入下一站";autoTimer=setTimeout(function(){goStation(stationIndex+1,true)},600)}else if(!autoToggle.checked&&progress>=1){playStatus.textContent="自动连播已关闭 · 等待点击“下一步”"}});

function appendHighlightedQuote(container,item,extra){
  var quote=el("blockquote","quote");var sentence=item.sentence,start=item.matchStart,end=item.matchEnd;
  quote.appendChild(document.createTextNode(sentence.slice(0,start)));quote.appendChild(el("mark","",sentence.slice(start,end)));quote.appendChild(document.createTextNode(sentence.slice(end)));
  var source=item.dynasty+" · "+item.poet+"《"+item.title+"》 · "+(item.pair?"共现对「"+item.pair.join("+")+"」":"诗文正文该词"+item.poemWordHits+"次")+" · "+(item.canonicalMatch?"规范证据":"全作品收录");
  if(extra)source+=" · "+extra;quote.appendChild(el("cite","",source));container.appendChild(quote)
}
function showStationEvidence(station,word,host){host.innerHTML="";var items=station.evidence.filter(function(item){return item.sentence.slice(item.matchStart,item.matchEnd)===word});host.appendChild(el("h4","","当前站证据 · "+word));var quotes=el("div","quotes");items.forEach(function(item){appendHighlightedQuote(quotes,item,station.yearLabel+" · 节点"+station.sourceGrade+"级 / 关联"+station.linkedPoem.relationGrade+"级")});if(!items.length)quotes.appendChild(el("p","evidence-method","当前关联诗文没有该词的保留命中。"));host.appendChild(quotes)}
function sourceLink(label,url){var link=el("a","",label);link.href=url;link.target="_blank";link.rel="noreferrer";return link}
function renderStationContext(station){
  var chapter=chapterMap[station.chapterId],historical=relevantEvent(station),host=document.getElementById("chapterContext");host.innerHTML="";
  host.appendChild(el("div","station-count","第 "+station.stepIndex+" / "+station.stepCount+" 站 · "+chapter.title));host.appendChild(el("h3","",station.poet+"《"+station.linkedPoem.title+"》"));host.appendChild(el("div","section-kicker",station.yearLabel+" · "+precisionText(station.yearPrecision)+" · "+station.placeHistorical));
  var badges=el("div","chapter-badges");["节点"+station.sourceGrade+"级","关联"+station.linkedPoem.relationGrade+"级",station.dynasty,station.rawHits+"处意象命中"].forEach(function(text){badges.appendChild(el("span","badge",text))});host.appendChild(badges);host.appendChild(el("p","context-reading",station.event));
  var poem=el("div","station-poem",station.body);host.appendChild(poem);
  var hits=el("div","station-hits"),evidence=el("div","evidence-mini");
  var stationChips=[];
  function setStationEvidence(word){
    stationChips.forEach(function(chip){chip.style.background="";chip.style.color="";chip.style.fontWeight=""});
    stationChips.forEach(function(chip){if(chip.getAttribute("data-word")===word){chip.style.background="#e5eeea";chip.style.color="#174f49";chip.style.fontWeight="700"}});
    showStationEvidence(station,word,evidence);
  }
  station.hits.slice(0,14).forEach(function(item){var button=el("button","station-hit",item.word+" ×"+item.rawHits);button.type="button";button.setAttribute("data-word",item.word);button.style.borderLeft="3px solid "+categoryColor(wordMap[item.word].category);button.addEventListener("click",function(){setStationEvidence(item.word)});stationChips.push(button);hits.appendChild(button)});host.appendChild(hits);host.appendChild(evidence);if(station.hits.length)setStationEvidence(station.hits[0].word);else evidence.appendChild(el("p","evidence-method","当前诗文没有命中本页160词客观意象表。"));
  var source=el("div","station-source");source.appendChild(document.createTextNode("节点来源（"+station.sourceGrade+"级）："));source.appendChild(sourceLink(station.sourceName,station.sourceUrl));source.appendChild(document.createElement("br"));source.appendChild(document.createTextNode("诗作关联（"+station.linkedPoem.relationGrade+"级）："+station.linkedPoem.relation));if(station.linkedPoem.sourceUrl){source.appendChild(document.createTextNode(" · "));source.appendChild(sourceLink("诗文来源",station.linkedPoem.sourceUrl))}source.appendChild(document.createElement("br"));source.appendChild(document.createTextNode("当前历史背景："));source.appendChild(sourceLink(historical.year+" "+historical.label+" · "+historical.sourceName,historical.sourceUrl));host.appendChild(source);
  var list=el("div","node-list");chapter.nodes.forEach(function(node){var row=el("div","node-row"+(node.id===station.id?" current":""));row.tabIndex=0;row.setAttribute("role","button");row.appendChild(el("span","grade","节点"+node.sourceGrade+" / 关联"+node.linkedPoem.relationGrade));row.appendChild(el("b","",node.year+" · "+node.poet+"《"+node.linkedPoem.title+"》"));row.appendChild(document.createElement("br"));row.appendChild(document.createTextNode(node.placeHistorical+" · 来源："+node.sourceName+" · 关联："+node.linkedPoem.relation));row.addEventListener("click",function(){goStation(node.stepIndex-1,true)});row.addEventListener("keydown",function(event){if(event.key==="Enter"||event.key===" "){event.preventDefault();goStation(node.stepIndex-1,true)}});list.appendChild(row)});host.appendChild(list)
}

window.addEventListener("resize",function(){routeMap.resize();chapterChart.resize();comparisonChart.resize();categoryChart.resize();authorEqualChart.resize();timelineChart.resize();contribChart.resize();genreChart.resize()});

renderConclusions();
renderChangeAnalysis();
renderLooTable();
renderChronologyCoverage();
timelineChart.setOption(timelineOption(),true);
renderTrendPicks();
contribChart.setOption(contribOption(contribWord),true);
renderContribPicks();
renderAuthorTable();
renderGenreNote();
renderGenreTable();
renderStablePairs();
renderDivergentPairs();
renderCollocates();
renderCoverage();
renderEvidenceBrowser();
renderMethod();
showAggregateEvidence(D.comparisonWords[0]);
goStation(0,true);
})();
'''

HTML_TEMPLATE = r'''<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' rx='8' fill='%2328766d'/%3E%3Cpath d='M17 44c10-18 20-25 31-26-6 8-11 17-14 27-5-5-10-5-17-1z' fill='%23f3f5f1'/%3E%3C/svg%3E">
<title>38 · 唐宋意象潮汐 —— 诗行万里参赛版</title>
<script src="assets/pyecharts/v6/echarts.min.js"></script>
<script src="assets/pyecharts/v6/maps/china.js"></script>
<style>
__VIZ38_CSS__
</style>
</head>
<body>
__VIZ38_BODY__
<script>
__VIZ38_SCRIPT__
</script>
</body>
</html>
'''


if __name__ == "__main__":
    main()
