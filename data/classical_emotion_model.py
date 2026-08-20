# -*- coding: utf-8 -*-
"""可复跑的古典诗词多维情感分类器。

模型辅助用于扩充本体候选；实际发布计算完全在本地执行，便于复核和重跑。
分类器输出多标签、VAD、文学形容词、证据词与置信度，不输出单一心理定论。
"""
from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from typing import Iterable

from classical_emotion_lexicon import (
    EMOTION_SPECS,
    EXCLUDED_PHRASES,
    NEGATORS,
    SPIRIT_CLUSTER_FALLBACK,
)


SAFE_SINGLE_CHAR = frozenset("愁悲哀哭泣泪恨怨愤惧恐惊喜欢笑悔怅孤独病老衰")
PUNCT_RE = re.compile(r"[^\u3400-\u9fff]+")
TEXT_BOUNDARY = "\x00"


def _is_blocked(source: str, start: int, end: int, term: str) -> bool:
    """处理专名/固定反向短语，以及单字直接情绪词前的否定。"""
    for phrase in EXCLUDED_PHRASES:
        left = max(0, start - len(phrase))
        right = min(len(source), end + len(phrase))
        window = source[left:right]
        offset = window.find(phrase)
        if offset >= 0:
            p0 = left + offset
            if p0 <= start and end <= p0 + len(phrase):
                return True
    max_negator_length = max(map(len, NEGATORS), default=0)
    prefix = source[max(0, start - max_negator_length):start]
    if any(prefix.endswith(negator) for negator in NEGATORS):
        return True
    return False


def _term_hits(source: str, terms: Iterable[tuple[str, float]]) -> list[dict[str, object]]:
    """同一情绪内最长词优先，避免「泪满」再次拆成「泪」。"""
    candidates: list[tuple[int, int, str, float]] = []
    for term, weight in terms:
        if len(term) == 1 and term not in SAFE_SINGLE_CHAR:
            continue
        cursor = 0
        while True:
            start = source.find(term, cursor)
            if start < 0:
                break
            end = start + len(term)
            if not _is_blocked(source, start, end, term):
                candidates.append((start, end, term, float(weight)))
            cursor = start + max(1, len(term))

    candidates.sort(key=lambda row: (-len(row[2]), -row[3], row[0]))
    occupied: set[int] = set()
    accepted: list[dict[str, object]] = []
    for start, end, term, weight in candidates:
        span = set(range(start, end))
        if span & occupied:
            continue
        occupied.update(span)
        accepted.append({"term": term, "weight": weight, "start": start})
    return sorted(accepted, key=lambda row: int(row["start"]))


def _spirit_fallback(
    body: str,
    spirit_entries: dict[str, dict[str, object]] | None,
    spirit_words: list[str] | None,
) -> tuple[Counter[str], dict[str, list[str]]]:
    scores: Counter[str] = Counter()
    evidence: dict[str, list[str]] = defaultdict(list)
    if not spirit_entries or not spirit_words:
        return scores, evidence

    work = body
    for word in spirit_words:
        # 古义语境例外：「残阳」在《暮江吟》中是明丽景物，并非悲情证据。
        if word == "残阳" and "可怜九月初三夜" in body:
            continue
        count = work.count(word)
        if not count:
            continue
        work = work.replace(word, "\x01" * len(word))
        cluster = spirit_entries[word].get("cluster")
        fallback = SPIRIT_CLUSTER_FALLBACK.get(str(cluster))
        if not fallback:
            continue
        emotion_id, weight = fallback
        scores[emotion_id] += float(weight) * count
        evidence[emotion_id].append(word)
    return scores, evidence


def classify_text(
    body: str,
    title: str = "",
    spirit_entries: dict[str, dict[str, object]] | None = None,
    spirit_words: list[str] | None = None,
) -> dict[str, object]:
    """返回一首诗的多维情感画像。"""
    # 标点是语义边界，不能直接删除后把相邻分句拼成一个伪短语。
    source = PUNCT_RE.sub(TEXT_BOUNDARY, body or "")
    title_source = PUNCT_RE.sub(TEXT_BOUNDARY, title or "")
    scores: Counter[str] = Counter()
    evidence: dict[str, list[str]] = defaultdict(list)
    rule_hits = 0

    for emotion_id, spec in EMOTION_SPECS.items():
        body_hits = _term_hits(source, spec["keywords"])
        title_hits = _term_hits(title_source, spec["keywords"])
        for row in body_hits:
            scores[emotion_id] += float(row["weight"])
            evidence[emotion_id].append(str(row["term"]))
            rule_hits += 1
        for row in title_hits:
            # 标题只作为辅助语境，避免「送某人」一题决定整首诗。
            scores[emotion_id] += float(row["weight"]) * 0.55
            evidence[emotion_id].append("题:" + str(row["term"]))

    fallback_scores, fallback_evidence = _spirit_fallback(
        source, spirit_entries, spirit_words
    )
    for emotion_id, score in fallback_scores.items():
        scores[emotion_id] += score
        evidence[emotion_id].extend(fallback_evidence[emotion_id])

    ranked = [(key, value) for key, value in scores.items() if value > 0]
    ranked.sort(key=lambda row: (-row[1], row[0]))
    if not ranked:
        return {
            "primary": None,
            "primary_label": "情绪未定",
            "family": "未定",
            "color": "#8d8f88",
            "top_emotions": [],
            "adjectives": ["含混", "待考"],
            "summary": "词典信号不足，保留为待考",
            "valence": 0.0,
            "arousal": 0.35,
            "dominance": 0.0,
            "confidence": 0.12,
            "confidence_label": "低",
            "mixed": False,
            "rule_hits": 0,
            "evidence": [],
        }

    total = sum(score for _, score in ranked)
    vector_weight = sum(score ** 1.12 for _, score in ranked[:8])
    vad = {}
    for dimension in ("valence", "arousal", "dominance"):
        value = sum(
            float(EMOTION_SPECS[key][dimension]) * (score ** 1.12)
            for key, score in ranked[:8]
        ) / vector_weight
        vad[dimension] = round(value, 3)

    top_rows = []
    for key, score in ranked[:3]:
        spec = EMOTION_SPECS[key]
        seen_terms = list(dict.fromkeys(evidence[key]))[:6]
        top_rows.append({
            "id": key,
            "label": spec["label"],
            "family": spec["family"],
            "color": spec["color"],
            "score": round(score, 3),
            "share": round(score / total, 3),
            "adjectives": list(spec["adjectives"]),
            "evidence": seen_terms,
        })

    primary_id = ranked[0][0]
    primary = EMOTION_SPECS[primary_id]
    descriptors = list(primary["adjectives"][:2])
    if len(top_rows) > 1:
        descriptors.append(str(EMOTION_SPECS[top_rows[1]["id"]]["adjectives"][0]))
    if vad["arousal"] >= 0.74 and "激越" not in descriptors:
        descriptors.append("激越")
    elif vad["arousal"] <= 0.30 and "低回" not in descriptors:
        descriptors.append("低回")
    descriptors = list(dict.fromkeys(descriptors))[:4]

    positive = sum(score for key, score in ranked if float(EMOTION_SPECS[key]["valence"]) > 0.2)
    negative = sum(score for key, score in ranked if float(EMOTION_SPECS[key]["valence"]) < -0.2)
    mixed = positive / total >= 0.22 and negative / total >= 0.22

    signal = 1 - math.exp(-total / 4.2)
    margin = ranked[0][1] / total
    diversity = min(1.0, rule_hits / 5.0)
    confidence = min(0.96, 0.18 + 0.38 * signal + 0.24 * margin + 0.16 * diversity)
    confidence_label = "高" if confidence >= 0.72 else ("中" if confidence >= 0.48 else "低")
    secondary = top_rows[1]["label"] if len(top_rows) > 1 else ""
    summary = "、".join(descriptors[:3])
    if secondary:
        summary += f"；兼有{secondary}"
    if mixed:
        summary += "（复合情绪）"

    all_evidence = []
    for row in top_rows:
        all_evidence.extend(row["evidence"])
    return {
        "primary": primary_id,
        "primary_label": primary["label"],
        "family": primary["family"],
        "color": primary["color"],
        "top_emotions": top_rows,
        "adjectives": descriptors,
        "summary": summary,
        **vad,
        "confidence": round(confidence, 3),
        "confidence_label": confidence_label,
        "mixed": mixed,
        "rule_hits": rule_hits,
        "evidence": list(dict.fromkeys(all_evidence))[:10],
    }


def dimension_percent(value: float, signed: bool = True) -> int:
    """V/D 的 -1..1 转 0..100；A 直接由 0..1 转换。"""
    if signed:
        return round((max(-1.0, min(1.0, value)) + 1) * 50)
    return round(max(0.0, min(1.0, value)) * 100)
