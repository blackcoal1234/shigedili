# -*- coding: utf-8 -*-
"""Generate competition page 38: 唐宋意象潮汐.

Zero-argument rerun:
    python 数据可视化脚本/viz_38_imagery_tide.py

Read-only inputs:
    data/poems.json
    data/spirit_image_dict.py
    data/reviewed/poet_journeys.json

Owned outputs:
    output/38_唐宋意象潮汐.html
    output/assets/competition/imagery_tide_data.json
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
POEMS_JSON = ROOT / "data" / "poems.json"
LEXICON_PY = ROOT / "data" / "spirit_image_dict.py"
JOURNEYS_JSON = ROOT / "data" / "reviewed" / "poet_journeys.json"
OUT_JSON = ROOT / "output" / "assets" / "competition" / "imagery_tide_data.json"
OUT_HTML = ROOT / "output" / "38_唐宋意象潮汐.html"

EXPECTED_CORPUS = {"唐": 9846, "宋": 10591}
DYNASTIES = ("唐", "宋")
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


def load_python_module(path: Path):
    spec = importlib.util.spec_from_file_location("spirit_image_dict_for_viz38", path)
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


def evidence_for_record(
    poem: dict,
    record_index: int,
    matches: list[tuple[int, int, str]],
    poem_counts: Counter,
) -> dict[str, list[dict]]:
    """Return one exact, untruncated evidence record per word and sentence."""
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
                "title": poem["title"],
                "poet": poem["author"],
                "dynasty": poem["dynasty"],
                "sentence": sentence,
                "matchStart": local_start,
                "matchEnd": local_end,
                "sentenceMatchCount": len(positions),
                "poemWordHits": poem_counts[word],
                "recordIndex": record_index,
                "sourcePoemId": poem.get("source_poem_id", ""),
            }
        )
    return result


def evidence_sort_key(item: dict):
    dynasty_order = {"唐": 0, "宋": 1}
    return (
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
        "dynasty": poem["dynasty"],
        "poet": poem["author"],
        "title": poem["title"],
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
    return {
        "rawHits": raw,
        "ratePer10k": normalized_rate(raw, denominator),
        "chineseCharDenominator": denominator,
        "poemRecords": dynasty_poem_counts[dynasty],
        "poemsWithHit": dynasty_word_poems[dynasty][word],
    }


def main() -> None:
    poems_bytes = POEMS_JSON.read_bytes()
    lexicon_bytes = LEXICON_PY.read_bytes()
    journeys_bytes = JOURNEYS_JSON.read_bytes()
    poems = json.loads(poems_bytes.decode("utf-8"))
    journeys = json.loads(journeys_bytes.decode("utf-8"))
    lexicon = load_python_module(LEXICON_PY)

    assert isinstance(poems, list) and len(poems) == 20437, "诗库总量应为 20,437"
    dynasty_poem_counts = Counter(poem.get("dynasty") for poem in poems)
    assert {dynasty: dynasty_poem_counts[dynasty] for dynasty in DYNASTIES} == EXPECTED_CORPUS
    assert set(dynasty_poem_counts) == set(DYNASTIES), "诗库只应包含唐、宋两朝"
    assert all(poem.get("title") and poem.get("author") and poem.get("body") for poem in poems)

    raw_rows = list(lexicon.SPIRIT_DICT)
    assert len(raw_rows) == 197
    assert len({row[0] for row in raw_rows}) == len(raw_rows), "词典词条不应重复"
    included_rows = [
        row
        for row in raw_rows
        if row[1] not in EXCLUDED_CATEGORIES and row[4] is not None and bool(row[5])
    ]
    excluded_terms = [
        {
            "word": row[0],
            "category": row[1],
            "reason": (
                EXCLUDED_CATEGORIES[row[1]]
                if row[1] in EXCLUDED_CATEGORIES
                else "词条缺少具象尺度或意象说明，本页从客观意象口径排除"
            ),
        }
        for row in raw_rows
        if row not in included_rows
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

    dynasty_chars = Counter()
    dynasty_authors: dict[str, set[str]] = {dynasty: set() for dynasty in DYNASTIES}
    dynasty_word_hits: dict[str, Counter] = {dynasty: Counter() for dynasty in DYNASTIES}
    dynasty_word_poems: dict[str, Counter] = {dynasty: Counter() for dynasty in DYNASTIES}
    dynasty_category_hits: dict[str, Counter] = {dynasty: Counter() for dynasty in DYNASTIES}
    dynasty_category_poems: dict[str, Counter] = {dynasty: Counter() for dynasty in DYNASTIES}
    dynasty_poems_with_imagery = Counter()
    scan_cache: list[dict] = []
    evidence_candidates: dict[str, list[dict]] = defaultdict(list)
    record_evidence: dict[int, dict[str, list[dict]]] = {}
    poem_index: dict[tuple[str, str], list[int]] = defaultdict(list)
    context_exclusion_counts = Counter()
    context_exclusion_examples: dict[str, list[dict]] = defaultdict(list)

    for record_index, poem in enumerate(poems):
        dynasty = poem["dynasty"]
        dynasty_authors[dynasty].add(poem["author"])
        poem_index[(poem["author"], poem["title"])].append(record_index)
        chars = chinese_char_count(poem["body"])
        assert chars > 0
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

        per_record_evidence = evidence_for_record(poem, record_index, matches, poem_counts)
        if per_record_evidence:
            record_evidence[record_index] = per_record_evidence
            for word, items in per_record_evidence.items():
                evidence_candidates[word].extend(items)
        scan_cache.append(
            {
                "chars": chars,
                "matches": matches,
                "counts": poem_counts,
                "contextExclusionCount": len(context_exclusions),
            }
        )

    assert sum(dynasty_poem_counts[dynasty] for dynasty in DYNASTIES) == 20437
    assert sum(dynasty_chars.values()) == 1632059, "汉字分母发生变化，请复核语料"
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

    combined_word_hits = dynasty_word_hits["唐"] + dynasty_word_hits["宋"]
    ranked_words = sorted(words, key=lambda word: (-combined_word_hits[word], word))

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

    category_order = [category for category in CATEGORY_COLORS]
    category_term_counts = Counter(row[1] for row in included_rows)
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
        }

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
        indexes = poem_index.get(key, [])
        assert len(indexes) == 1, f"审核节点关联诗未唯一命中主语料：{key} -> {indexes}"
        record_index = indexes[0]
        return record_index, poems[record_index], scan_cache[record_index]

    def node_public_record(node: dict) -> dict:
        record_index, poem, scan = linked_record(node)
        hits = sorted(scan["counts"].items(), key=lambda item: (-item[1], item[0]))
        node_evidence = []
        for word, items in sorted(record_evidence.get(record_index, {}).items()):
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
            for word, items in record_evidence.get(record_index, {}).items():
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
        ranking_words = sorted(chapter_counts, key=lambda word: (-chapter_counts[word], word))[:10]
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
            for rank, word in enumerate(ranking_words, 1)
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
        (poem.get("content_validated_at", "") for poem in poems), default=""
    )

    data = {
        "meta": {
            "schemaVersion": "1.0",
            "title": "唐宋意象潮汐",
            "generatedFromPoems": len(poems),
            "sourceHashes": {
                "poemsJsonSha256": hashlib.sha256(poems_bytes).hexdigest(),
                "spiritImageDictSha256": hashlib.sha256(lexicon_bytes).hexdigest(),
                "poetJourneysSha256": hashlib.sha256(journeys_bytes).hexdigest(),
            },
            "corpusSha256": hashlib.sha256(poems_bytes).hexdigest(),
            "corpusLatestValidation": latest_validation,
            "journeysUpdatedAt": journeys.get("updated_at", ""),
            "dynastyCounts": {dynasty: dynasty_poem_counts[dynasty] for dynasty in DYNASTIES},
            "totalChineseChars": sum(dynasty_chars.values()),
            "lexiconSourceTerms": len(raw_rows),
            "includedObjectiveTerms": len(included_rows),
            "excludedTerms": len(excluded_terms),
            "displayedEvidenceWords": len(evidence_payload),
            "contextExcludedHits": sum(context_exclusion_counts.values()),
            "normalization": "每10,000个正文汉字的非重叠词条命中数",
        },
        "dynastyAggregates": dynasty_aggregates,
        "categoryStats": category_stats,
        "wordStats": word_stats,
        "comparisonWords": comparison_words,
        "topContrasts": top_contrasts,
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
                "唐宋聚合使用 data/poems.json 全部20,437条正文记录，不去重：唐9,846条、"
                "宋10,591条。语料为诗、词、赋、序、论、行纪等混合体裁，故本页统一称"
                "‘诗文正文’，不把结果解释为纯诗歌全集。标题与作者只用于证据定位。"
            ),
            "denominator": (
                "分母仅计正文中的CJK汉字；唐813,371字，宋818,688字。"
                "标准化率=原始命中数/正文汉字数×10,000。"
            ),
            "matching": (
                "逐篇正文从左到右扫描；每个位置按词长降序、同长度按词条字面序检查，"
                "命中后前移整个词长，因此长词优先且不产生重叠重复计数。"
            ),
            "singleCharacterCaveat": (
                "单字字符串匹配仍可能存在多义；本页对月的日历义、云的言说义、风的固定抽象构词"
                "执行有限上下文排除，并公开规则、次数与例证。其余结果仍是可复现的低层文本特征。"
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
                    "termCount": sum(row[1] == category for row in raw_rows),
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
                "开放年谱来源名称与URL。"
            ),
            "contrastRule": (
                "先取全库原始命中总量最高的24个客观意象词，再按唐宋每万汉字率差绝对值排序，"
                "展示前12项；差值定义为宋率减唐率。"
            ),
            "evidenceRule": (
                "证据句由同一次非重叠扫描的命中位置回溯；句界取句号、问号、叹号、分号或换行，"
                "页面保留完整句子，不截断。160个纳入词均有可按需打开的证据入口；有命中的词"
                "优先各取唐、宋两例，零命中词明确显示为空。章节与节点证据只来自对应关联作品。"
            ),
            "sourceGradeDefinitions": source_grade_definitions,
            "exclusions": excluded_terms,
            "sourceHashes": {
                "data/poems.json": hashlib.sha256(poems_bytes).hexdigest(),
                "data/spirit_image_dict.py": hashlib.sha256(lexicon_bytes).hexdigest(),
                "data/reviewed/poet_journeys.json": hashlib.sha256(journeys_bytes).hexdigest(),
            },
        },
    }

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    json_text = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    assert "NaN" not in json_text and "Infinity" not in json_text
    OUT_JSON.write_text(json_text, encoding="utf-8")

    embedded = json.dumps(data, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    embedded = embedded.replace("</", "<\\/")
    html = HTML_TEMPLATE.replace("__IMAGERY_DATA__", embedded)
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
        "OK 唐宋意象潮汐："
        f"语料{len(poems)}条（唐{dynasty_poem_counts['唐']} / 宋{dynasty_poem_counts['宋']}），"
        f"正文汉字{sum(dynasty_chars.values())}，客观意象词{len(included_rows)}；"
        f"审核节点{len(all_nodes)}，入章{len(assigned_ids)}，窗口外{len(outside_nodes)}。"
    )
    print(f"JSON {OUT_JSON} ({OUT_JSON.stat().st_size} bytes)")
    print(f"HTML {OUT_HTML} ({OUT_HTML.stat().st_size} bytes)")


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
.wrap{width:100%;max-width:1240px;min-width:0;margin:0 auto;padding:0 24px}
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
</style>
</head>
<body>
<script>window.IMAGERY_TIDE_DATA=__IMAGERY_DATA__;</script>
<header class="topbar">
  <div class="wrap">
    <div class="title-row">
      <div><div class="eyebrow">诗行万里 · 参赛版 · 38</div><h1>唐宋意象潮汐<span class="dot">。</span></h1></div>
      <p class="dek">同一套客观意象词典扫过唐宋混合体裁正文；36 个审核节点按诗篇系年逐站显影，地图、历史事件、章节统计与原文证据同步。历史锚点只供对读，相关不等于因果。</p>
    </div>
    <div class="audit-strip" id="auditStrip" aria-label="数据口径摘要"></div>
  </div>
</header>

<main class="wrap">
  <section id="historical">
    <div class="section-head">
      <h2>三十六站 · 审核节点镜头</h2>
      <div class="section-kicker">默认逐站停驻 · 五章仅作背景分组</div>
    </div>
    <p class="section-note">动画按年、诗人、原路线序与节点 ID 确定性排列 36 个审核节点；每站都联动创作地点、历史锚点、章内统计、当前诗文与来源。地图连线只表示编年先后，不代表真实道路或旅行速度。</p>
    <div class="event-scroll" aria-label="历史背景锚点，可横向滚动"><div class="event-rail" id="eventRail"></div></div>
    <div class="tab-scroll"><div class="chapter-tabs" id="chapterTabs" role="tablist" aria-label="历史章节"></div></div>
    <div class="controls" aria-label="逐站动画控制">
      <button class="tool-btn" id="restartBtn" title="回到第一站">↺ 重启</button>
      <button class="tool-btn" id="prevBtn" title="回到上一站">← 上一步</button>
      <button class="tool-btn" id="playBtn" title="播放或暂停当前站显影" aria-pressed="false">▶ 播放</button>
      <button class="tool-btn primary" id="nextBtn" title="进入下一站">下一步 →</button>
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

  <section id="dynastyCompare">
    <div class="section-head">
      <h2>全语料 · 唐宋两端</h2>
      <div class="section-kicker">20,437 条正文记录 · 以正文汉字数归一</div>
    </div>
    <p class="section-note">哑铃图选择全库原始命中总量最高的 14 个客观意象。横向位置是每 10,000 个正文汉字的非重叠命中数；点击任一词查看唐宋原始次数、分母、命中正文记录数与完整证据句。</p>
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
    <div>诗行万里 · 数媒可视化参赛版 · 本页离线生成，统计口径与证据审计见上方“方法、排除与证据审计”。</div>
  </div>
</footer>

<script>
(function(){
"use strict";
var D=window.IMAGERY_TIDE_DATA;
var TANG="#456f8a", SONG="#a34f44", JADE="#28766d", INK="#222822", MUTED="#667068", LINE="#d4dbd3";
var numberFmt=new Intl.NumberFormat("zh-CN");
function fmt(value){return typeof value==="number"?numberFmt.format(value):"—"}
function rate(value){return typeof value==="number"?Number(value).toFixed(2):"—"}
function el(tag,cls,text){var node=document.createElement(tag);if(cls)node.className=cls;if(text!==undefined)node.textContent=text;return node}
function categoryColor(name){var item=D.categoryInfo.find(function(row){return row.name===name});return item?item.color:MUTED}
function gradeText(grades){return "A"+grades.A+" / B"+grades.B+" / C"+grades.C}
var wordMap={};D.wordStats.forEach(function(row){wordMap[row.word]=row});

var audit=document.getElementById("auditStrip");
[
  [fmt(D.meta.generatedFromPoems)+" 条","混合体裁正文"],
  ["唐 "+fmt(D.meta.dynastyCounts["唐"])+" · 宋 "+fmt(D.meta.dynastyCounts["宋"]),"样本"],
  [fmt(D.meta.totalChineseChars)+" 字","正文汉字分母"],
  [fmt(D.meta.includedObjectiveTerms)+" / "+fmt(D.meta.lexiconSourceTerms)+" 词","纳入 / 原词典"],
  [fmt(D.historicalLens.reviewedNodeCount)+" 节点 · "+fmt(D.historicalLens.chapteredNodeCount)+" 入章","历史镜头"]
].forEach(function(item){var span=el("span");span.appendChild(el("b","",item[0]));span.appendChild(document.createTextNode(" "+item[1]));audit.appendChild(span)});

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
  var source=item.dynasty+" · "+item.poet+"《"+item.title+"》 · 诗文正文该词"+item.poemWordHits+"次";
  if(extra)source+=" · "+extra;quote.appendChild(el("cite","",source));container.appendChild(quote)
}
function showStationEvidence(station,word,host){host.innerHTML="";var items=station.evidence.filter(function(item){return item.sentence.slice(item.matchStart,item.matchEnd)===word});host.appendChild(el("h4","","当前站证据 · "+word));var quotes=el("div","quotes");items.forEach(function(item){appendHighlightedQuote(quotes,item,station.yearLabel+" · 节点"+station.sourceGrade+"级 / 关联"+station.linkedPoem.relationGrade+"级")});if(!items.length)quotes.appendChild(el("p","evidence-method","当前关联诗文没有该词的保留命中。"));host.appendChild(quotes)}
function sourceLink(label,url){var link=el("a","",label);link.href=url;link.target="_blank";link.rel="noreferrer";return link}
function renderStationContext(station){
  var chapter=chapterMap[station.chapterId],historical=relevantEvent(station),host=document.getElementById("chapterContext");host.innerHTML="";
  host.appendChild(el("div","station-count","第 "+station.stepIndex+" / "+station.stepCount+" 站 · "+chapter.title));host.appendChild(el("h3","",station.poet+"《"+station.linkedPoem.title+"》"));host.appendChild(el("div","section-kicker",station.yearLabel+" · "+precisionText(station.yearPrecision)+" · "+station.placeHistorical));
  var badges=el("div","chapter-badges");["节点"+station.sourceGrade+"级","关联"+station.linkedPoem.relationGrade+"级",station.dynasty,station.rawHits+"处意象命中"].forEach(function(text){badges.appendChild(el("span","badge",text))});host.appendChild(badges);host.appendChild(el("p","context-reading",station.event));
  var poem=el("div","station-poem",station.body);host.appendChild(poem);
  var hits=el("div","station-hits"),evidence=el("div","evidence-mini");station.hits.slice(0,14).forEach(function(item){var button=el("button","station-hit",item.word+" ×"+item.rawHits);button.type="button";button.style.borderLeft="3px solid "+categoryColor(wordMap[item.word].category);button.addEventListener("click",function(){showStationEvidence(station,item.word,evidence)});hits.appendChild(button)});host.appendChild(hits);host.appendChild(evidence);if(station.hits.length)showStationEvidence(station,station.hits[0].word,evidence);else evidence.appendChild(el("p","evidence-method","当前诗文没有命中本页160词客观意象表。"));
  var source=el("div","station-source");source.appendChild(document.createTextNode("节点来源（"+station.sourceGrade+"级）："));source.appendChild(sourceLink(station.sourceName,station.sourceUrl));source.appendChild(document.createElement("br"));source.appendChild(document.createTextNode("诗作关联（"+station.linkedPoem.relationGrade+"级）："+station.linkedPoem.relation));if(station.linkedPoem.sourceUrl){source.appendChild(document.createTextNode(" · "));source.appendChild(sourceLink("诗文来源",station.linkedPoem.sourceUrl))}source.appendChild(document.createElement("br"));source.appendChild(document.createTextNode("当前历史背景："));source.appendChild(sourceLink(historical.year+" "+historical.label+" · "+historical.sourceName,historical.sourceUrl));host.appendChild(source);
  var list=el("div","node-list");chapter.nodes.forEach(function(node){var row=el("div","node-row"+(node.id===station.id?" current":""));row.tabIndex=0;row.setAttribute("role","button");row.appendChild(el("span","grade","节点"+node.sourceGrade+" / 关联"+node.linkedPoem.relationGrade));row.appendChild(el("b","",node.year+" · "+node.poet+"《"+node.linkedPoem.title+"》"));row.appendChild(document.createElement("br"));row.appendChild(document.createTextNode(node.placeHistorical+" · 来源："+node.sourceName+" · 关联："+node.linkedPoem.relation));row.addEventListener("click",function(){goStation(node.stepIndex-1,true)});row.addEventListener("keydown",function(event){if(event.key==="Enter"||event.key===" "){event.preventDefault();goStation(node.stepIndex-1,true)}});list.appendChild(row)});host.appendChild(list)
}

var dynastyGrid=document.getElementById("dynastyGrid");
[["唐","tang"],["宋","song"]].forEach(function(pair){var name=pair[0],stats=D.dynastyAggregates[name],strip=el("div","dynasty-strip "+pair[1]);strip.appendChild(el("h3","",name));[[fmt(stats.poemRecords),"正文记录"],[fmt(stats.chineseChars),"正文汉字"],[fmt(stats.rawHits),"原始命中"],[rate(stats.ratePer10k),"每万字命中"]].forEach(function(item){var metric=el("div","metric");metric.appendChild(el("b","",item[0]));metric.appendChild(el("span","",item[1]));strip.appendChild(metric)});dynastyGrid.appendChild(strip)});

var comparisonRows=D.comparisonWords.slice().reverse().map(function(word){return wordMap[word]});
var comparisonChart=window.echarts.init(document.getElementById("comparisonChart"));
var comparisonMax=Math.ceil(Math.max.apply(null,comparisonRows.map(function(row){return Math.max(row.tang.ratePer10k,row.song.ratePer10k)}))*1.12/5)*5;
comparisonChart.setOption({
  animationDuration:700,textStyle:{color:INK,fontFamily:'"Microsoft YaHei",sans-serif'},grid:{left:16,right:34,top:26,bottom:48,containLabel:true},
  xAxis:{type:"value",max:comparisonMax,name:"命中 / 每万正文汉字",nameLocation:"middle",nameGap:31,nameTextStyle:{fontSize:10,color:MUTED},axisLabel:{color:MUTED,fontSize:10},splitLine:{lineStyle:{color:"#e4e8e2"}}},
  yAxis:{type:"category",data:comparisonRows.map(function(row){return row.word}),axisTick:{show:false},axisLine:{show:false},axisLabel:{fontFamily:"KaiTi,STKaiti,serif",fontSize:15,color:INK}},
  tooltip:{trigger:"item",confine:true,formatter:function(params){var row=params.data;return "<b>"+row.word+"</b> · "+row.category+"<br>唐："+row.tang.rawHits+"次 · "+rate(row.tang.ratePer10k)+"/万字 · "+row.tang.poemsWithHit+"/"+row.tang.poemRecords+"条命中 · 分母"+fmt(row.tang.chineseCharDenominator)+"字<br>宋："+row.song.rawHits+"次 · "+rate(row.song.ratePer10k)+"/万字 · "+row.song.poemsWithHit+"/"+row.song.poemRecords+"条命中 · 分母"+fmt(row.song.chineseCharDenominator)+"字"}},
  series:[{type:"custom",renderItem:function(params,api){var y=api.coord([0,api.value(2)])[1],x1=api.coord([api.value(0),api.value(2)])[0],x2=api.coord([api.value(1),api.value(2)])[0];return{type:"group",children:[{type:"line",shape:{x1:x1,y1:y,x2:x2,y2:y},style:{stroke:"#aeb8af",lineWidth:3}},{type:"circle",shape:{cx:x1,cy:y,r:6},style:{fill:TANG,stroke:"#fff",lineWidth:2}},{type:"circle",shape:{cx:x2,cy:y,r:6},style:{fill:SONG,stroke:"#fff",lineWidth:2}}]}} ,data:comparisonRows.map(function(row,index){return Object.assign({value:[row.tang.ratePer10k,row.song.ratePer10k,index]},row)}),encode:{x:[0,1],y:2}}]
});
comparisonChart.on("click",function(params){if(params.data&&params.data.word)showAggregateEvidence(params.data.word)});

var contrastRow=document.getElementById("contrastRow");contrastRow.appendChild(el("span","contrast-label","高频词中的率差前列："));
D.topContrasts.forEach(function(row){var button=el("button","word-chip",row.word+" · "+(row.deltaSongMinusTang>0?"宋+":"唐+")+rate(row.absoluteDelta));button.type="button";button.style.borderLeft="3px solid "+categoryColor(row.category);button.title="点击查看完整唐宋证据";button.addEventListener("click",function(){showAggregateEvidence(row.word)});contrastRow.appendChild(button)});

function showAggregateEvidence(word){
  var host=document.getElementById("aggregateEvidence"),row=wordMap[word],ev=D.evidence[word];host.innerHTML="";
  var title=el("h3","",word),cat=el("span","word-category",row.category+" · 全库"+fmt(row.combinedRawHits)+"次");title.style.color=categoryColor(row.category);title.appendChild(cat);host.appendChild(title);
  if(row.singleCharacter)host.appendChild(el("div","word-warning","单字匹配有构词与多义歧义：这里展示的是可复现的字符串特征，不是语义证明。"));
  var sides=el("div","word-sides");[["唐","tang",row.tang],["宋","song",row.song]].forEach(function(item){var side=el("div","word-side "+item[1]);side.appendChild(el("b","",item[0]+" · "+rate(item[2].ratePer10k)+" / 万字"));side.appendChild(document.createTextNode("原始 "+fmt(item[2].rawHits)+" 次 · 分母 "+fmt(item[2].chineseCharDenominator)+" 字 · "+fmt(item[2].poemsWithHit)+" / "+fmt(item[2].poemRecords)+" 条命中"));sides.appendChild(side)});host.appendChild(sides);
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

function methodTable(rows,headers){var table=el("table","method-table"),head=el("tr");headers.forEach(function(text){head.appendChild(el("th","",text))});table.appendChild(head);rows.forEach(function(row){var tr=el("tr");row.forEach(function(text){tr.appendChild(el("td","",text))});table.appendChild(tr)});return table}
function renderAuditTerm(word,host){host.innerHTML="";var row=wordMap[word],ev=D.evidence[word];host.appendChild(el("h3","",word+" · "+row.category));host.appendChild(el("p","","全库 "+fmt(row.combinedRawHits)+" 次；唐 "+fmt(row.tang.rawHits)+" 次（"+rate(row.tang.ratePer10k)+"/万字），宋 "+fmt(row.song.rawHits)+" 次（"+rate(row.song.ratePer10k)+"/万字）。"));var quotes=el("div","quotes");ev.corpus.forEach(function(item){appendHighlightedQuote(quotes,item,"160词完整审计入口")});if(!ev.corpus.length)quotes.appendChild(el("p","evidence-method","该词已纳入口径，但当前语料没有保留命中。"));host.appendChild(quotes)}
function renderMethod(){
  var M=D.method,host=document.getElementById("methodBody");
  host.appendChild(el("div","audit-note","审核镜头共 "+D.historicalLens.reviewedNodeCount+" 节点；指定五章覆盖 "+D.historicalLens.chapteredNodeCount+" 节点，窗口外 "+D.historicalLens.outsideChapterWindowCount+" 节点（766 杜甫《秋兴八首·其一》、768 杜甫《登岳阳楼》）只保留审计，不进入动画。"));
  host.appendChild(el("h3","","全语料口径"));host.appendChild(el("p","",M.corpusScope));host.appendChild(el("p","",M.denominator));
  host.appendChild(el("h3","","确定性匹配"));host.appendChild(el("p","",M.matching));host.appendChild(el("p","",M.singleCharacterCaveat));host.appendChild(el("p","",M.evidenceRule));
  var grid=el("div","method-grid"),left=el("div"),right=el("div");left.appendChild(el("h3","","纳入类别"));left.appendChild(methodTable(M.includedCategories.map(function(row){return[row.category,String(row.termCount),row.rule]}),["类别","词条","规则"]));right.appendChild(el("h3","","完整词条排除清单 · "+M.exclusions.length+"词"));right.appendChild(methodTable(M.exclusions.map(function(row){return[row.word,row.category,row.reason]}),["词","原类别","原因"]));grid.appendChild(left);grid.appendChild(right);host.appendChild(grid);
  host.appendChild(el("h3","","160个纳入词与按需证据"));var browser=el("div","term-browser"),termList=el("div","term-list"),termDetail=el("div","term-detail");M.includedTerms.forEach(function(item){var button=el("button","",item.word+" · "+item.combinedRawHits);button.type="button";button.title=item.category+" · "+item.description;button.addEventListener("click",function(){renderAuditTerm(item.word,termDetail)});termList.appendChild(button)});browser.appendChild(termList);browser.appendChild(termDetail);host.appendChild(browser);renderAuditTerm(M.includedTerms[0].word,termDetail);
  host.appendChild(el("h3","","上下文消歧规则 · 共排除 "+fmt(D.meta.contextExcludedHits)+" 处"));host.appendChild(methodTable(M.contextExclusionRules.map(function(rule){return[rule.word,rule.label,String(rule.excludedHits),rule.reason,rule.examples.map(function(item){return item.poet+"《"+item.title+"》：『"+item.sentence+"』"}).join("\n")]}),["词","规则","排除数","判定","可复核例证"]));
  host.appendChild(el("h3","","历史章节与来源等级"));host.appendChild(el("p","",M.chapterRule));host.appendChild(el("p","",M.chapterCaveat));host.appendChild(el("p","",M.eventAnchorRule));
  host.appendChild(methodTable(D.historicalLens.events.map(function(event){return[String(event.year),event.label,event.sourceName,event.sourceUrl,event.sourceNote]}),["年份","事件","来源","URL","用途说明"]));
  host.appendChild(methodTable(["A","B","C"].map(function(grade){return[grade,M.sourceGradeDefinitions[grade]]}),["等级","原审核数据定义"]));
  host.appendChild(el("h3","","输入哈希与复跑"));Object.keys(M.sourceHashes).forEach(function(path){var p=el("p","hash",path+" · SHA-256 "+M.sourceHashes[path]);host.appendChild(p)});host.appendChild(el("p","",M.contrastRule));host.appendChild(el("p","","页面数据快照：output/assets/competition/imagery_tide_data.json；生成脚本：数据可视化脚本/viz_38_imagery_tide.py。脚本零参数复跑，并断言20,437条正文、唐宋记录数、汉字分母、38节点、36站次序与160词证据入口。"))
}

window.addEventListener("resize",function(){routeMap.resize();chapterChart.resize();comparisonChart.resize();categoryChart.resize()});
renderMethod();showAggregateEvidence(D.comparisonWords[0]);goStation(0,true);
})();
</script>
</body>
</html>
'''


if __name__ == "__main__":
    main()
