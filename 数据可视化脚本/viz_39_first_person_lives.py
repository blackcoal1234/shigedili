# -*- coding: utf-8 -*-
"""生成 39 号展项「诗人自述生命卷」。

范围：88 位诗人四轮总册；首轮 22 人生成证据约束的第一人称生命章节。
产出：
  output/39_诗人自述生命卷.html
  output/assets/competition/first_person_lives_data.json

叙事红线：
  - 诗句可作原文引用，但必须逐字存在于本地语料。
  - 所有「我」都是编辑性第一人称重构，不是诗人原话，也不等于史实。
  - VAD 与幽愤/讽刺词典信号只描述作品文本，不诊断诗人的真实心理。
"""
from __future__ import annotations

import json
import hashlib
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from famous_poet_corpus import load_analysis_poems  # noqa: E402

DATA_DIR = ROOT / "data"
CANDIDATE_DIR = DATA_DIR / "candidates"
OUT_HTML = ROOT / "output" / "39_诗人自述生命卷.html"
OUT_JSON = ROOT / "output" / "assets" / "competition" / "first_person_lives_data.json"
ROUNDS_PATH = CANDIDATE_DIR / "poet_life_rounds.json"

CONTENTIOUS_IDS = {"indignant", "satirical"}
STAGE_TITLES = (
    "生年与早岁",
    "初涉世事",
    "行路与转折",
    "中岁回望",
    "晚境与记录末端",
)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open(encoding="utf-8-sig") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path.name}:{line_number} JSON 非法") from exc
            if isinstance(row, dict):
                yield row


def finite_year(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(float(value)):
        return None
    year = int(value)
    return year if 500 <= year <= 1300 else None


def compact_text(value: Any, limit: int = 140) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def source_id(prefix: str, raw_id: Any) -> str:
    raw = str(raw_id or "").strip()
    clean = re.sub(r"[^0-9A-Za-z_-]+", "-", raw).strip("-")
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
    # 中文人名不能在 ASCII 清洗后悄然折叠成同一个 prefix。
    # 只要清洗造成信息损失，就追加原始 UTF-8 的稳定哈希。
    if not clean:
        clean = digest if raw else "missing"
    elif clean != raw or len(clean) > 48:
        stem = clean[:36].strip("-") or "id"
        clean = f"{stem}-{digest}"
    return f"{prefix}-{clean}"


def register_source(
    sources: dict[str, dict[str, Any]],
    sid: str,
    *,
    kind: str,
    name: str,
    url: str = "",
    grade: str = "",
    status: str = "",
    note: str = "",
) -> str:
    sources.setdefault(
        sid,
        {
            "id": sid,
            "kind": kind,
            "name": compact_text(name, 100),
            "url": str(url or ""),
            "grade": str(grade or ""),
            "status": str(status or ""),
            "note": compact_text(note, 220),
        },
    )
    return sid


def load_corpus() -> tuple[
    list[dict[str, Any]],
    dict[str, list[dict[str, Any]]],
    dict[tuple[str, str], dict[str, Any]],
    list[dict[str, Any]],
    str,
]:
    rows, corpus_source = load_analysis_poems()
    canonical_rows = read_json(DATA_DIR / "poems.json")
    if not isinstance(canonical_rows, list):
        raise TypeError("data/poems.json 必须是数组")
    by_poet: dict[str, list[dict[str, Any]]] = defaultdict(list)
    canonical_by_hash: dict[tuple[str, str], dict[str, Any]] = {}
    analysis_by_canonical_id: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        poet = str(row.get("poet") or row.get("author") or "").strip()
        work_id = str(row.get("work_id") or "").strip()
        if not poet or not work_id:
            continue
        by_poet[poet].append(row)
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
    if len(by_poet) != 88:
        raise AssertionError(f"语料应含 88 位诗人，实际 {len(by_poet)}")
    for raw_row in canonical_rows:
        row = dict(raw_row)
        poet = str(row.get("poet") or row.get("author") or "").strip()
        body_hash = str(row.get("body_hash") or "").strip()
        if not poet or not body_hash:
            continue
        canonical_id = str(row.get("source_poem_id") or "")
        analysis_match = analysis_by_canonical_id.get((poet, canonical_id))
        if analysis_match is None:
            raise KeyError(f"规范诗作缺少全作品稳定身份：{(poet, canonical_id)}")
        row["work_id"] = analysis_match["work_id"]
        row["canonical_gushiwen_id"] = canonical_id
        key = (poet, body_hash)
        if key in canonical_by_hash:
            raise ValueError(f"canonical poems.json 存在重复作者/body_hash：{key}")
        canonical_by_hash[key] = row
    return rows, dict(by_poet), canonical_by_hash, canonical_rows, corpus_source


def normalize_rounds(round_config: dict[str, Any], corpus_poets: set[str]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    raw_rounds = round_config.get("rounds")
    if not isinstance(raw_rounds, list) or len(raw_rounds) != 4:
        raise AssertionError("四轮配置必须恰有 4 组")
    active_round = int(round_config.get("active_round", 1))
    if active_round not in {1, 2, 3, 4}:
        raise AssertionError(f"active_round 必须在 1–4，实际 {active_round}")
    rounds: list[dict[str, Any]] = []
    membership: dict[str, int] = {}
    for index, row in enumerate(raw_rounds, start=1):
        number = int(row.get("round", row.get("number", index)))
        names = row.get("poets", row.get("cohort"))
        if isinstance(names, dict):
            names = names.get("poets") or names.get("names")
        if not isinstance(names, list) or len(names) != 22:
            raise AssertionError(f"第 {number} 轮必须恰有 22 人")
        names = [str(name).strip() for name in names]
        if len(names) != len(set(names)):
            raise AssertionError(f"第 {number} 轮有重复诗人")
        for name in names:
            if name in membership:
                raise AssertionError(f"{name} 被分入多轮")
            membership[name] = number
        rounds.append(
            {
                "round": number,
                "status": "complete" if number < active_round else "active" if number == active_round else "planned",
                "selection_note": str(row.get("selection_note") or row.get("note") or ""),
                "poets": names,
            }
        )
    if set(membership) != corpus_poets:
        missing = sorted(corpus_poets - set(membership))
        extra = sorted(set(membership) - corpus_poets)
        raise AssertionError(f"四轮名单与语料不一致；缺少={missing}；多出={extra}")
    return rounds, membership


def load_profiles() -> tuple[dict[str, Any], dict[str, dict]]:
    payload = read_json(DATA_DIR / "stylometry" / "emotion_profiles.json")
    rows = payload.get("profiles", []) if isinstance(payload, dict) else payload
    profiles: dict[str, dict] = {
        "by_work_id": {},
        "by_canonical_id": {},
        "by_body_hash": defaultdict(list),
    }
    for row in rows:
        poet = str(row.get("poet") or "")
        body_hash = str(row.get("body_hash") or "")
        work_id = str(row.get("work_id") or "")
        canonical_id = str(row.get("canonical_gushiwen_id") or "")
        if work_id:
            if work_id in profiles["by_work_id"]:
                raise ValueError(f"情感档案 work_id 重复：{work_id}")
            profiles["by_work_id"][work_id] = row
        if poet and canonical_id:
            key = (poet, canonical_id)
            if key in profiles["by_canonical_id"]:
                raise ValueError(f"情感档案 canonical ID 重复：{key}")
            profiles["by_canonical_id"][key] = row
        if poet and body_hash:
            profiles["by_body_hash"][(poet, body_hash)].append(row)
    return payload, profiles


def profile_for_analysis_row(indexes: dict[str, dict], row: dict[str, Any]) -> dict[str, Any] | None:
    work_id = str(row.get("work_id") or "")
    if work_id:
        profile = indexes["by_work_id"].get(work_id)
        if profile is None:
            raise KeyError(f"情感档案缺少 work_id：{work_id}")
        return profile
    poet = str(row.get("poet") or row.get("author") or "")
    candidates = indexes["by_body_hash"].get((poet, str(row.get("body_hash") or "")), [])
    if len(candidates) > 1:
        raise ValueError(f"情感档案 body_hash 非唯一，禁止回退：{(poet, row.get('body_hash'))}")
    return candidates[0] if candidates else None


def profile_for_canonical(indexes: dict[str, dict], poem: dict[str, Any]) -> dict[str, Any] | None:
    poet = str(poem.get("poet") or poem.get("author") or "")
    canonical_id = str(poem.get("source_poem_id") or "")
    if canonical_id:
        profile = indexes["by_canonical_id"].get((poet, canonical_id))
        if profile is not None:
            return profile
    work_id = str(poem.get("work_id") or "")
    if work_id:
        profile = indexes["by_work_id"].get(work_id)
        if profile is None:
            raise KeyError(f"情感档案缺少 work_id：{work_id}")
        return profile
    candidates = indexes["by_body_hash"].get((poet, str(poem.get("body_hash") or "")), [])
    if len(candidates) > 1:
        raise ValueError(f"情感档案 body_hash 非唯一，禁止回退：{(poet, poem.get('body_hash'))}")
    return candidates[0] if candidates else None


def load_readiness() -> dict[str, dict[str, Any]]:
    summary = read_json(CANDIDATE_DIR / "poet_history_collection_summary.json")
    return {str(row["poet"]): row for row in summary.get("poets", [])}


def readiness_view(row: dict[str, Any]) -> dict[str, Any]:
    events = row.get("person_events") or {}
    works = row.get("work_chronology") or {}
    refs = row.get("references") or {}
    biography = (refs.get("biography") or {}).get("record_count", 0)
    dila = (refs.get("dila") or {}).get("active_status", "")
    event_count = int(events.get("candidate_count") or 0)
    locatable = int(events.get("locatable_count") or 0)
    work_count = int(works.get("candidate_count") or 0)
    gap = bool((row.get("gap") or {}).get("listed"))
    score = 0
    score += 20 if biography else 0
    score += 15 if dila == "matched" else (6 if dila == "ambiguous" else 0)
    score += min(30, int(math.log10(event_count + 1) * 10))
    score += min(30, int(math.log10(work_count + 1) * 9))
    score += 5 if locatable else 0
    score -= 8 if gap else 0
    return {
        "score": max(0, min(100, score)),
        "biography_records": int(biography or 0),
        "dila_status": dila or "not_found",
        "person_event_candidates": event_count,
        "locatable_candidates": locatable,
        "work_chronology_candidates": work_count,
        "gap_flag": gap,
        "boundary": "均为候选/参考层，未经人工逐条核定",
    }


def load_lifespans(
    active_names: set[str], sources: dict[str, dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    spans: dict[str, dict[str, Any]] = {}
    for row in iter_jsonl(CANDIDATE_DIR / "poet_dila_person_matches.jsonl"):
        poet = str(row.get("poet") or "")
        if poet not in active_names or not row.get("selected") or row.get("match_status") != "matched":
            continue
        born_years = (row.get("born_range") or {}).get("years") or []
        died_years = (row.get("died_range") or {}).get("years") or []
        birth_range = [finite_year(value) for value in born_years]
        death_range = [finite_year(value) for value in died_years]
        birth_range = [value for value in birth_range if value is not None]
        death_range = [value for value in death_range if value is not None]
        sid = source_id("dila", row.get("reference_id") or row.get("authorityID") or poet)
        register_source(
            sources,
            sid,
            kind="person_lifespan_reference",
            name=str(row.get("source") or "DDBC Authority"),
            url=str(row.get("source_url") or ""),
            grade="B",
            status="reference_only",
            note="仅作人名身份与生卒参考，不作行路或内心证据。",
        )
        spans[poet] = {
            "birth_year": min(birth_range) if birth_range else None,
            "death_year": max(death_range) if death_range else None,
            "birth_range": [min(birth_range), max(birth_range)] if birth_range else None,
            "death_range": [min(death_range), max(death_range)] if death_range else None,
            "birth_place": compact_text((row.get("birth_place") or {}).get("name"), 40),
            "death_place": compact_text((row.get("death_place") or {}).get("name"), 40),
            "precision": "range" if len(set(birth_range + death_range)) > 2 else "reference",
            "source_ids": [sid],
            "note": "DILA 开放人名权威资料；仅作身份/生卒参考。",
        }

    birth_payload = read_json(CANDIDATE_DIR / "poet_birth_years.json")
    for row in birth_payload.get("records", []):
        poet = str(row.get("poet") or "")
        if poet not in active_names:
            continue
        year = finite_year(row.get("birth_year"))
        if year is None:
            continue
        sid = source_id("verified-birth", f"{poet}-{year}")
        register_source(
            sources,
            sid,
            kind="verified_birth_reference",
            name=str(row.get("source_name") or "项目核定生年表"),
            url=str(row.get("source_url") or ""),
            grade="A",
            status="verified_reference",
            note=str(row.get("note") or ""),
        )
        span = spans.setdefault(
            poet,
            {
                "birth_year": None,
                "death_year": None,
                "birth_range": None,
                "death_range": None,
                "birth_place": "",
                "death_place": "",
                "precision": "partial",
                "source_ids": [],
                "note": "目前只有核定生年；卒年待补。",
            },
        )
        span["birth_year"] = year
        span["birth_range"] = [year, year]
        if sid not in span["source_ids"]:
            span["source_ids"].append(sid)
    return spans


def grade_rank(value: Any) -> int:
    return {"A": 4, "B": 3, "C": 2, "D": 1}.get(str(value or "").upper(), 0)


def load_active_records(
    active_names: set[str], corpus_by_hash: dict[tuple[str, str], dict[str, Any]]
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, list[dict[str, Any]]]]:
    events_by_poet: dict[str, dict[tuple[Any, ...], dict[str, Any]]] = defaultdict(dict)
    for row in iter_jsonl(CANDIDATE_DIR / "journey_event_candidates.jsonl"):
        poet = str(row.get("poet") or "")
        year = finite_year(row.get("year_start"))
        if poet not in active_names or year is None:
            continue
        key = (
            year,
            str(row.get("event_type") or ""),
            str(row.get("historical_place") or ""),
            str(row.get("source") or ""),
        )
        old = events_by_poet[poet].get(key)
        if old is None or grade_rank(row.get("source_grade")) > grade_rank(old.get("source_grade")):
            events_by_poet[poet][key] = row

    works_by_poet: dict[str, dict[tuple[int, str], dict[str, Any]]] = defaultdict(dict)
    for row in iter_jsonl(CANDIDATE_DIR / "work_chronology_supplements.jsonl"):
        poet = str(row.get("poet") or "")
        year = finite_year(row.get("year_start"))
        body_hash = str(row.get("body_hash") or "")
        if (
            poet not in active_names
            or year is None
            or not body_hash
            or not row.get("linked")
            or (poet, body_hash) not in corpus_by_hash
        ):
            continue
        key = (year, body_hash)
        old = works_by_poet[poet].get(key)
        if old is None or grade_rank(row.get("source_grade")) > grade_rank(old.get("source_grade")):
            works_by_poet[poet][key] = row

    events = {
        poet: sorted(rows.values(), key=lambda row: (int(row["year_start"]), str(row.get("historical_place") or "")))
        for poet, rows in events_by_poet.items()
    }
    works = {
        poet: sorted(rows.values(), key=lambda row: (int(row["year_start"]), str(row.get("poem_title") or "")))
        for poet, rows in works_by_poet.items()
    }
    return events, works


def quantile_value(values: list[int], ratio: float) -> int:
    if not values:
        raise ValueError("空年份序列")
    index = int(round((len(values) - 1) * ratio))
    return values[max(0, min(len(values) - 1, index))]


def closest_unused(
    rows: list[dict[str, Any]], target: int, used: set[str], *, max_distance: int | None = None
) -> dict[str, Any] | None:
    candidates: list[tuple[int, int, str, dict[str, Any]]] = []
    for row in rows:
        rid = str(row.get("candidate_id") or f"{row.get('year_start')}:{row.get('body_hash')}:{row.get('historical_place')}")
        if rid in used:
            continue
        year = finite_year(row.get("year_start"))
        if year is None:
            continue
        distance = abs(year - target)
        if max_distance is not None and distance > max_distance:
            continue
        candidates.append((distance, -grade_rank(row.get("source_grade")), rid, row))
    if not candidates:
        return None
    row = min(candidates, key=lambda item: (item[0], item[1], item[2]))[3]
    used.add(str(row.get("candidate_id") or f"{row.get('year_start')}:{row.get('body_hash')}:{row.get('historical_place')}"))
    return row


def exact_quote(body: str, profile: dict[str, Any] | None) -> str:
    body = str(body or "").strip()
    if not body:
        return ""
    evidence = [] if not profile else [str(term) for term in profile.get("evidence", []) if str(term).strip()]
    pieces = [piece.strip() for piece in re.split(r"(?<=[。！？；])|\n+", body) if piece.strip()]
    for term in evidence:
        for piece in pieces:
            if term in piece and len(piece) <= 64:
                return piece
    for piece in pieces:
        if len(piece) <= 64:
            return piece
    return body[:48]


def emotion_dimensions(profile: dict[str, Any] | None) -> dict[str, float | None]:
    if not profile:
        return {"valence": None, "arousal": None, "dominance": None, "anger_signal": None, "confidence": None}
    contentious = 0.0
    for emotion in profile.get("top_emotions", []):
        if emotion.get("id") in CONTENTIOUS_IDS:
            contentious = max(contentious, float(emotion.get("share") or 0.0))
    return {
        "valence": round(float(profile["valence"]), 3) if isinstance(profile.get("valence"), (int, float)) else None,
        "arousal": round(float(profile["arousal"]), 3) if isinstance(profile.get("arousal"), (int, float)) else None,
        "dominance": round(float(profile["dominance"]), 3) if isinstance(profile.get("dominance"), (int, float)) else None,
        # 保留已发布契约键 anger_signal，但展示层明确命名为
        # 「幽愤/讽刺词典信号」，不把题中「怨/恨」误读为作者的真实愤怒。
        "anger_signal": round(max(0.0, min(1.0, contentious)), 3) if contentious else 0.0,
        "confidence": round(float(profile["confidence"]), 3) if isinstance(profile.get("confidence"), (int, float)) else None,
    }


def build_text_portrait(
    poet: str,
    corpus_rows: list[dict[str, Any]],
    profiles: dict[str, dict],
    chapters: list[dict[str, Any]],
) -> dict[str, Any]:
    """把「他是怎样的人」收紧为可证伪的「作品文本人格」。

    不从一首诗推断人格，只聚合该诗人的名家全作品规则模型信号。
    """
    local_profiles = [
        profile
        for row in corpus_rows
        if (profile := profile_for_analysis_row(profiles, row)) is not None
    ]
    primary_counts: Counter[str] = Counter()
    adjective_counts: Counter[str] = Counter()
    values: dict[str, list[float]] = {"valence": [], "arousal": [], "dominance": []}
    anger_rows: list[tuple[float, dict[str, Any]]] = []
    for profile in local_profiles:
        label = str(profile.get("primary_label") or "").strip()
        if label:
            primary_counts[label] += 1
        adjective_counts.update(
            str(value).strip()
            for value in profile.get("adjectives", [])
            if str(value).strip()
        )
        for key in values:
            value = profile.get(key)
            if isinstance(value, (int, float)) and math.isfinite(float(value)):
                values[key].append(float(value))
        anger_score = max(
            (
                float(emotion.get("share") or 0.0)
                for emotion in profile.get("top_emotions", [])
                if emotion.get("id") in CONTENTIOUS_IDS
            ),
            default=0.0,
        )
        if anger_score > 0:
            anger_rows.append((anger_score, profile))

    total = max(1, len(local_profiles))
    dominant = [
        {"label": label, "count": count, "share": round(count / total, 3)}
        for label, count in primary_counts.most_common(5)
    ]
    traits = [label for label, _ in adjective_counts.most_common(6)]
    center = {
        key: round(sum(series) / len(series), 3) if series else None
        for key, series in values.items()
    }
    chapter_points = [
        chapter
        for chapter in chapters
        if isinstance(chapter.get("dimensions", {}).get("valence"), (int, float))
    ]
    if chapter_points:
        low = min(chapter_points, key=lambda row: float(row["dimensions"]["valence"]))
        high = max(chapter_points, key=lambda row: float(row["dimensions"]["valence"]))
        low_year = low.get("work", {}).get("year", low["year_start"])
        high_year = high.get("work", {}).get("year", high["year_start"])
        curve_reading = (
            f"已生成编年候选章节中，效价低点对应 {low_year} 年作品所在的「{low['title']}」"
            f"（{low['dimensions']['valence']}），高点对应 {high_year} 年作品所在的「{high['title']}」"
            f"（{high['dimensions']['valence']}）；这条线不应被读成单向上升或衰落。"
        )
    else:
        curve_reading = "已生成章节尚无足够的可连接作品，不绘制人生起伏结论。"

    anger_examples = []
    title_by_work_id = {
        str(row.get("work_id") or ""): str(row.get("title") or "")
        for row in corpus_rows
    }
    for score, profile in sorted(anger_rows, key=lambda item: (-item[0], str(item[1].get("title") or "")))[:3]:
        body_hash = str(profile.get("body_hash") or "")
        work_id = str(profile.get("work_id") or "")
        anger_examples.append(
            {
                "title": title_by_work_id.get(work_id) or str(profile.get("title") or ""),
                "work_id": work_id,
                "canonical_gushiwen_id": str(profile.get("canonical_gushiwen_id") or ""),
                "body_hash": body_hash,
                "signal": round(score, 3),
            }
        )
    anger_rate = round(len(anger_rows) / total, 3)
    anger_reading = (
        f"在 {len(local_profiles)} 首有效文本画像中，{len(anger_rows)} 首触发「激愤/讽刺」规则信号"
        f"（{anger_rate:.1%}）。这表示作品文本的幽愤/讽刺词典线索，可能只来自题名或单一「怨/恨」字；"
        "不是对诗人真实愤怒的判定。"
    )
    emotion_text = "、".join(item["label"] for item in dominant[:3]) or "尚无稳定主情绪"
    trait_text = "、".join(traits[:4]) or "信号不足"
    return {
        "scope": "corpus_textual_persona_not_personality_diagnosis",
        "sample_poems": len(local_profiles),
        "dominant_emotions": dominant,
        "textual_traits": traits,
        "emotional_center": center,
        "summary": (
            f"在名家全作品语料收录的 {len(local_profiles)} 首作品中，{poet}的反复文本倾向为「{emotion_text}」，"
            f"聚合形容词为「{trait_text}」。这是作品中的言说方式，不是对历史人格的诊断。"
        ),
        "curve_reading": curve_reading,
        "anger": {
            "signal_poems": len(anger_rows),
            "signal_rate": anger_rate,
            "reading": anger_reading,
            "representative_works": anger_examples,
        },
    }


def record_source(
    row: dict[str, Any], sources: dict[str, dict[str, Any]], prefix: str, kind: str
) -> str:
    rid = row.get("candidate_id") or row.get("reference_id") or f"{row.get('poet')}-{row.get('year_start')}-{row.get('source')}"
    sid = source_id(prefix, rid)
    return register_source(
        sources,
        sid,
        kind=kind,
        name=str(row.get("source_name") or row.get("source") or kind),
        url=str(row.get("source_url") or row.get("source_pages") or ""),
        grade=str(row.get("source_grade") or ""),
        status=str(row.get("status") or "needs_review"),
        note=str(row.get("source_note") or "候选记录，待人工逐条复核。"),
    )


def lifespan_label(span: dict[str, Any] | None, observed: list[int]) -> str:
    if span:
        birth = span.get("birth_year")
        death = span.get("death_year")
        birth_range = span.get("birth_range")
        death_range = span.get("death_range")

        def display_range(value: Any, fallback: Any) -> str:
            if isinstance(value, list) and len(value) == 2 and all(isinstance(item, int) for item in value):
                return str(value[0]) if value[0] == value[1] else f"{value[0]}–{value[1]}"
            return str(fallback) if fallback is not None else "？"

        if birth is not None and death is not None:
            return f"{display_range(birth_range, birth)}—{display_range(death_range, death)}（区间参考）"
        if birth is not None:
            return f"{display_range(birth_range, birth)}—？（卒年待考）"
        if death is not None:
            return f"？—{display_range(death_range, death)}（生年待考）"
    if observed:
        return f"{min(observed)}—{max(observed)}（现存候选记录范围）"
    return "生卒待考"


def chapter_targets(span: dict[str, Any] | None, events: list[dict[str, Any]], works: list[dict[str, Any]]) -> list[int]:
    observed = sorted(
        {
            year
            for row in [*events, *works]
            if (year := finite_year(row.get("year_start"))) is not None
        }
    )
    if not observed:
        birth = finite_year(span.get("birth_year")) if span else None
        death = finite_year(span.get("death_year")) if span else None
        if birth is None or death is None or death < birth:
            raise AssertionError("诗人没有足以建立时间轴的生卒、事件或作品编年候选")
        # 只有生卒参考时保留五个明确的空白阶段；不为阶段补写事件或情绪。
        return [round(birth + (death - birth) * index / 4) for index in range(5)]
    start = int(span.get("birth_year")) if span and span.get("birth_year") is not None else observed[0]
    end = int(span.get("death_year")) if span and span.get("death_year") is not None else observed[-1]
    if end < start:
        start, end = observed[0], observed[-1]
    internal_values = [year for year in observed if start <= year <= end] or observed
    targets = [
        start,
        quantile_value(internal_values, 0.25),
        quantile_value(internal_values, 0.50),
        quantile_value(internal_values, 0.75),
        end,
    ]
    return sorted(targets)


def build_chapters(
    poet: str,
    round_number: int,
    span: dict[str, Any] | None,
    events: list[dict[str, Any]],
    works: list[dict[str, Any]],
    corpus_by_hash: dict[tuple[str, str], dict[str, Any]],
    profiles: dict[str, dict],
    sources: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    targets = chapter_targets(span, events, works)
    used_events: set[str] = set()
    used_works: set[str] = set()
    chapters: list[dict[str, Any]] = []
    for index, target in enumerate(targets):
        endpoint = index in {0, len(targets) - 1}
        # 生年/卒年章只允许挂接同年记录，避免把±3年近邻事件伪装成锚点年发生。
        work = closest_unused(works, target, used_works, max_distance=0 if endpoint else None)
        focal_year = target
        if work and not endpoint:
            focal_year = int(work["year_start"])
        # 同一章内的事件、作品必须是同年记录；不把相邻年份压缩成一个情绪点。
        event = closest_unused(events, focal_year, used_events, max_distance=0 if (endpoint or work) else None)
        if not work and not event and not endpoint:
            event = closest_unused(events, target, used_events)
            if event:
                focal_year = int(event["year_start"])

        source_ids: list[str] = []
        event_fact = ""
        place: str | None = None
        grade = "B"
        assertion_status = "evidence_gap"

        is_birth = endpoint and index == 0 and span and span.get("birth_year") == target
        is_death = endpoint and index == len(targets) - 1 and span and span.get("death_year") == target
        if is_birth or is_death:
            source_ids.extend(span.get("source_ids") or [])
            if is_birth:
                place = span.get("birth_place") or None
                birth_range = span.get("birth_range")
                birth_text = (
                    str(birth_range[0]) if isinstance(birth_range, list) and birth_range[0] == birth_range[1]
                    else f"{birth_range[0]}–{birth_range[1]}" if isinstance(birth_range, list) and len(birth_range) == 2
                    else str(target)
                )
                event_fact = f"生卒参考资料给出生年范围 {birth_text}"
                if place:
                    event_fact += f"，生地参考为「{place}」"
            else:
                place = span.get("death_place") or None
                death_range = span.get("death_range")
                death_text = (
                    str(death_range[0]) if isinstance(death_range, list) and death_range[0] == death_range[1]
                    else f"{death_range[0]}–{death_range[1]}" if isinstance(death_range, list) and len(death_range) == 2
                    else str(target)
                )
                event_fact = f"生卒参考资料给出卒年范围 {death_text}"
                if place:
                    event_fact += f"，卒地参考为「{place}」"
            event_fact += "；仅作身份/生卒参考，不作行路证据。"
            assertion_status = "reference_only"

        event_view: dict[str, Any] | None = None
        if event:
            event_sid = record_source(event, sources, "event", "person_event_candidate")
            source_ids.append(event_sid)
            event_year = int(event["year_start"])
            place = compact_text(event.get("historical_place"), 48) or place
            event_type = compact_text(event.get("event_type"), 32) or "person_event"
            event_view = {
                "type": event_type,
                "year_start": event_year,
                "year_end": int(event.get("year_end") or event_year),
                "place": place,
                "status": str(event.get("status") or "needs_review"),
                "source_grade": str(event.get("source_grade") or "C"),
            }
            if not event_fact:
                event_fact = f"候选人物事件记录：{event_year} 年"
                if place:
                    event_fact += f"，地点系于「{place}」"
                event_fact += f"（{event_type}）。"
            grade = str(event.get("source_grade") or grade)
            assertion_status = str(event.get("status") or "needs_review")

        work_view: dict[str, Any] | None = None
        profile: dict[str, Any] | None = None
        if work:
            body_hash = str(work.get("body_hash") or "")
            poem = corpus_by_hash[(poet, body_hash)]
            profile = profile_for_canonical(profiles, poem)
            work_sid = record_source(work, sources, "work", "work_chronology_candidate")
            source_ids.extend([work_sid, "poems-corpus", "emotion-profiles-v1"])
            quote = exact_quote(str(poem.get("body") or ""), profile)
            work_view = {
                "title": str(poem.get("title") or work.get("poem_title") or ""),
                "body_hash": body_hash,
                "work_id": str((profile or {}).get("work_id") or ""),
                "canonical_gushiwen_id": str(poem.get("source_poem_id") or ""),
                "profile_canonical_gushiwen_id": str((profile or {}).get("canonical_gushiwen_id") or ""),
                "year": int(work["year_start"]),
                "quote": quote,
                "emotion_summary": compact_text((profile or {}).get("summary"), 80) or "文本情绪信号不足",
                "primary_emotion": str((profile or {}).get("primary_label") or ""),
                "emotion_evidence": [str(term) for term in (profile or {}).get("evidence", [])[:5]],
                "chronology_status": str(work.get("status") or "needs_review"),
                "source_grade": str(work.get("source_grade") or "C"),
            }
            work_grade = str(work.get("source_grade") or "C")
            if not event_fact:
                event_fact = f"作品编年候选将《{work_view['title']}》系于 {work_view['year']} 年。"
                grade = work_grade
                assertion_status = str(work.get("status") or "needs_review")
            elif grade_rank(work_grade) and grade_rank(work_grade) < grade_rank(grade):
                # 章级徽章采用所有事件/作品证据中的最低等级，避免掩盖 C 级作品编年。
                grade = work_grade

        if not event_fact:
            event_fact = f"{target} 年是生卒/现存记录范围内的阶段锚点；尚无足以定位的具体事件。"
            if span:
                source_ids.extend(span.get("source_ids") or [])
        source_ids = list(dict.fromkeys(source_ids))
        if not source_ids:
            source_ids.append("poems-corpus")
        rated_grades = [
            str(sources[source_id].get("grade") or "").upper()
            for source_id in source_ids
            if source_id in sources and grade_rank(sources[source_id].get("grade"))
        ]
        if rated_grades:
            grade = min(rated_grades, key=grade_rank)

        if event and work_view:
            fp = f"这一阶段，候选记录把我的踪迹系在「{place or '地点待核'}」；另一条编年候选把《{work_view['title']}》放在 {work_view['year']} 年。诗中的「{work_view['emotion_summary']}」只是文本信号，不等于我的全部内心。"
        elif work_view:
            fp = f"这一阶段，作品编年候选把《{work_view['title']}》系于 {work_view['year']} 年。诗中显出「{work_view['emotion_summary']}」，但文本中的我不能直接等同于历史中的我。"
        elif event:
            fp = f"这一阶段，候选史料把我的踪迹系在「{place or '地点待核'}」。关于当时我真实的心情，材料没有给出直接答案。"
        elif is_birth:
            fp = "记录从我的生年开始，却没有保留我对早岁的直接讲述；这里不替沉默补写内心。"
        elif is_death:
            fp = "记录在卒年参考处收束；我不能为自己的最后时刻作证，编辑也不替证据补写。"
        else:
            fp = "这一阶段的史料尚未给出足够事件；这里不替我的沉默补写经历。"

        chapter_year = int(target if endpoint else focal_year)
        chapter_year_end = chapter_year
        birth_year = span.get("birth_year") if span else None
        birth_range = span.get("birth_range") if span else None
        death_range = span.get("death_range") if span else None
        if is_birth and isinstance(birth_range, list) and len(birth_range) == 2:
            chapter_year, chapter_year_end = int(birth_range[0]), int(birth_range[1])
        elif is_death and isinstance(death_range, list) and len(death_range) == 2:
            chapter_year, chapter_year_end = int(death_range[0]), int(death_range[1])
        if event_view:
            chapter_year = min(chapter_year, int(event_view["year_start"]))
            chapter_year_end = max(chapter_year_end, int(event_view["year_end"]))

        age: int | None = None
        age_range: list[int] | None = None
        if is_birth:
            age_range = [0, max(0, chapter_year_end - chapter_year)]
            age = 0 if age_range[1] == 0 else None
        elif isinstance(birth_range, list) and len(birth_range) == 2:
            age_min = chapter_year - int(birth_range[1])
            age_max = chapter_year_end - int(birth_range[0])
            if age_min >= 0:
                age_range = [age_min, age_max]
                age = age_min if age_min == age_max else None

        title = STAGE_TITLES[index]
        if index == 0 and not (span and span.get("birth_year") is not None):
            title = "现存记录起点"
        elif index == len(targets) - 1 and not (span and span.get("death_year") is not None):
            title = "现存记录末端"
        chapters.append(
            {
                "id": f"r{round_number}-{poet}-{index + 1}-{chapter_year}",
                "year_start": chapter_year,
                "year_end": chapter_year_end,
                "age": age,
                "age_range": age_range,
                "title": title,
                "event_fact": event_fact,
                "first_person": fp,
                "voice_mode": "editorial_first_person_reconstruction",
                "voice_label": "编辑性第一人称重构（非诗人原话）",
                "place": place,
                "event": event_view,
                "work": work_view,
                "dimensions": emotion_dimensions(profile),
                "source_ids": source_ids,
                "assertion_status": assertion_status,
                "source_grade": grade,
                "evidence_note": "事件与作品编年仍处候选层；章级证据徽章取所引材料中的最低等级；情绪值只是作品文本信号，不是心理诊断。",
            }
        )
    return sorted(chapters, key=lambda chapter: (chapter["year_start"], chapter["id"]))


def build_payload() -> dict[str, Any]:
    analysis_rows, corpus_by_poet, corpus_by_hash, canonical_rows, corpus_source = load_corpus()
    round_config = read_json(ROUNDS_PATH)
    rounds, membership = normalize_rounds(round_config, set(corpus_by_poet))
    active_round = int(round_config.get("active_round", 1))
    generated_names = {
        poet
        for row in rounds
        if int(row["round"]) <= active_round
        for poet in row["poets"]
    }
    profile_payload, profiles = load_profiles()
    if profile_payload.get("corpus_source") != corpus_source:
        raise AssertionError("emotion_profiles 与全作品分析语料来源不一致")
    if len(profile_payload.get("profiles", [])) != len(analysis_rows):
        raise AssertionError("emotion_profiles 与全作品分析语料篇数不一致")
    summary_by_poet = load_readiness()
    sources: dict[str, dict[str, Any]] = {}
    register_source(
        sources,
        "poems-corpus",
        kind="canonical_poem_corpus",
        name="data/poems.json",
        grade="A",
        status="local_canonical",
        note=f"本项目 {len(canonical_rows):,} 首规范诗歌语料；引句逐字回查。",
    )
    register_source(
        sources,
        "analysis-corpus",
        kind="full_famous_poet_analysis_corpus",
        name="data/analysis/famous_poets_full.jsonl.gz",
        grade="method",
        status=corpus_source,
        note=f"精选 88 位名家的 {len(analysis_rows):,} 首完整作品；仅用于文本状态聚合。",
    )
    register_source(
        sources,
        "emotion-profiles-v1",
        kind="deterministic_text_emotion_profile",
        name="data/stylometry/emotion_profiles.json",
        grade="method",
        status="model_output",
        note=f"基于 {len(analysis_rows):,} 首名家全作品的 VAD/情绪文本信号；不等于作者真实心理。",
    )
    spans = load_lifespans(generated_names, sources)
    events_by_poet, works_by_poet = load_active_records(generated_names, corpus_by_hash)

    poet_rows: list[dict[str, Any]] = []
    for round_row in rounds:
        for poet in round_row["poets"]:
            corpus_rows = corpus_by_poet[poet]
            dynasty_counts = Counter(str(row.get("person_period") or row.get("dynasty") or "") for row in corpus_rows)
            dynasty = dynasty_counts.most_common(1)[0][0]
            summary = summary_by_poet.get(poet, {})
            readiness = readiness_view(summary)
            events = events_by_poet.get(poet, [])
            works = works_by_poet.get(poet, [])
            span = spans.get(poet)
            observed_years = [
                year
                for row in [*events, *works]
                if (year := finite_year(row.get("year_start"))) is not None
            ]
            if membership[poet] <= active_round:
                full_lifespan = bool(span and finite_year(span.get("birth_year")) is not None and finite_year(span.get("death_year")) is not None)
                can_build_timeline = bool(events or works or full_lifespan)
                chapters = (
                    build_chapters(
                        poet,
                        membership[poet],
                        span,
                        events,
                        works,
                        corpus_by_hash,
                        profiles,
                        sources,
                    )
                    if can_build_timeline
                    else []
                )
                portrait = build_text_portrait(poet, corpus_rows, profiles, chapters)
                if chapters:
                    status = "round_complete" if membership[poet] < active_round else "active_round_generated"
                else:
                    status = "round_evidence_gap" if membership[poet] < active_round else "active_round_evidence_gap"
            else:
                chapters = []
                portrait = None
                status = "scheduled"
            lifespan = dict(span) if span else {
                "birth_year": None,
                "death_year": None,
                "birth_range": None,
                "death_range": None,
                "birth_place": "",
                "death_place": "",
                "precision": "unknown",
                "source_ids": [],
                "note": "结构化生卒参考待补。",
            }
            lifespan["label"] = lifespan_label(span, observed_years)
            poet_rows.append(
                {
                    "name": poet,
                    "dynasty": dynasty,
                    "round": membership[poet],
                    "status": status,
                    "corpus_poems": len(corpus_rows),
                    "readiness": readiness,
                    "lifespan": lifespan,
                    "portrait": portrait,
                    "chapters": chapters,
                }
            )

    return {
        "schema_version": 1,
        "project": {
            "title": "诗人自述生命卷",
            "subtitle": "《平行时空》的 88 人同素异形体",
            "total_poets": 88,
            "rounds": 4,
            "active_round": active_round,
            "cohort_size": 22,
            "active_poets": 22,
            "generated_poets": len(generated_names),
            "timeline_poets": sum(bool(row["chapters"]) for row in poet_rows),
            "evidence_gap_poets": sum(row["status"].endswith("evidence_gap") for row in poet_rows),
            "corpus_poems": sum(len(rows) for rows in corpus_by_poet.values()),
            "canonical_evidence_poems": len(canonical_rows),
            "corpus_source": corpus_source,
            "corpus_path": profile_payload.get("corpus_path", "data/analysis/famous_poets_full.jsonl.gz"),
            "narrative_mode": "editorial_first_person_reconstruction",
            "disclosure": "页面中的「我」是编辑性第一人称重构，不是诗人原话，不等于史实；只用于组织可回查的候选史料、诗句和文本情绪信号。",
            "method_note": f"文本画像聚合 {len(analysis_rows):,} 首名家全作品；原文引句与作品编年只绑定 {len(canonical_rows):,} 首规范证据。第 1–{active_round} 轮在证据足够时每人五章；无法建立时间轴者输出正式证据缺口结果。事件/作品编年仍为 needs_review 候选层，不伪装成已核定史实。",
        },
        "rounds": rounds,
        "poets": poet_rows,
        "sources": sources,
    }


HTML_TEMPLATE = r'''<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>39 · 诗人自述生命卷 —— 88 位诗人的证据约束第一人称传记</title>
  <link rel="icon" href="data:,">
  <script src="assets/pyecharts/v6/echarts.min.js"></script>
  <style>
    :root{--paper:#f2f4f0;--surface:#fff;--ink:#252b27;--muted:#69716b;--line:#d6dcd5;--cinnabar:#b64b3f;--jade:#26786e;--ochre:#a87527;--blue:#426f94;--violet:#7d4d63}
    *{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;color:var(--ink);background:var(--paper);font:14px/1.7 "Microsoft YaHei","PingFang SC",sans-serif}
    button,input{font:inherit}.topbar{position:sticky;top:0;z-index:10;background:#252b27;color:#f4f5f1;border-bottom:3px solid var(--cinnabar)}
    .topbar-inner{max-width:1440px;margin:auto;min-height:52px;padding:8px 20px;display:flex;align-items:center;gap:14px}.seal{display:grid;place-items:center;width:32px;height:32px;background:var(--cinnabar);font:20px KaiTi,serif}
    .brand{font:18px KaiTi,STKaiti,serif}.topbar .scope{margin-left:auto;color:#cbd1cb;font-size:12px}.shell{max-width:1440px;margin:auto;padding:28px 20px 48px}
    .hero{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:28px;padding:30px 0 26px;border-bottom:1px solid var(--line)}.eyebrow{color:var(--cinnabar);font-weight:700;letter-spacing:.16em}
    h1,h2,h3{font-family:KaiTi,STKaiti,"Songti SC",serif;font-weight:700}h1{font-size:clamp(32px,5vw,58px);line-height:1.08;margin:12px 0}.hero p{max-width:760px;color:#515953;margin:0}
    .stats{display:grid;grid-template-columns:repeat(2,112px);align-content:center}.stat{padding:13px 16px;border-left:1px solid var(--line)}.stat b{display:block;font:30px Georgia,serif}.stat span{font-size:12px;color:var(--muted)}
    .disclosure{margin:18px 0 24px;padding:14px 18px;border-left:4px solid var(--ochre);background:#fffaf0}.workspace{display:grid;grid-template-columns:310px minmax(0,1fr);gap:22px;align-items:start}
    .catalog{position:sticky;top:74px;background:var(--surface);border:1px solid var(--line);max-height:calc(100vh - 92px);display:flex;flex-direction:column}.catalog-head{padding:16px;border-bottom:1px solid var(--line)}
    .catalog-head h2{font-size:21px;margin:0 0 10px}.search{width:100%;height:40px;border:1px solid #aeb7af;background:#fff;padding:0 11px;color:var(--ink)}.search:focus,.filter:focus,.poet-button:focus{outline:3px solid rgba(66,111,148,.28);outline-offset:1px}
    .filters{display:flex;gap:6px;flex-wrap:wrap;margin-top:10px}.filter{border:1px solid var(--line);background:#f7f8f5;color:#4f5751;padding:5px 9px;cursor:pointer}.filter.active{background:var(--ink);border-color:var(--ink);color:#fff}
    .poet-list{overflow:auto;padding:8px;display:grid;gap:5px}.poet-button{text-align:left;border:1px solid transparent;background:transparent;padding:9px 10px;cursor:pointer;color:inherit;display:grid;grid-template-columns:1fr auto;gap:2px 8px}.poet-button:hover{background:#f5f6f2;border-color:var(--line)}.poet-button.active{background:#edf4f1;border-color:#a8c8c1;box-shadow:inset 3px 0 var(--jade)}
    .poet-name{font-family:KaiTi,STKaiti,serif;font-size:18px}.poet-meta,.readiness{font-size:11px;color:var(--muted)}.round-badge{grid-row:1/3;grid-column:2;align-self:center;font-size:11px;padding:2px 7px;border:1px solid var(--line)}.r1{color:#8e3329;border-color:#d6a29b}.r2,.r3,.r4{color:#677069}
    .reader{min-width:0}.poet-hero{background:var(--surface);border-top:4px solid var(--violet);padding:22px 24px;display:grid;grid-template-columns:minmax(0,1fr) auto;gap:16px;border-left:1px solid var(--line);border-right:1px solid var(--line)}
    .poet-hero h2{font-size:36px;margin:0}.poet-sub{color:var(--muted)}.meta-grid{display:grid;grid-template-columns:repeat(3,minmax(86px,1fr));gap:1px;background:var(--line);border:1px solid var(--line)}.meta-cell{background:#fff;padding:10px 13px}.meta-cell b{display:block;font-size:16px}.meta-cell span{font-size:11px;color:var(--muted)}
    .method-line{margin:0;padding:12px 24px;background:#f8f8f5;border:1px solid var(--line);color:#59615b;font-size:12px}.portrait-panel{background:#fff;border:1px solid var(--line);border-top:0;padding:20px 24px}.portrait-panel h3{font-size:25px;margin:0 0 8px}.portrait-panel p{margin:8px 0}.portrait-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:1px;background:var(--line);border:1px solid var(--line);margin-top:14px}.portrait-cell{background:#fbfcf9;padding:12px}.portrait-cell b{display:block;font:22px Georgia,serif;color:var(--violet)}.portrait-cell span{font-size:11px;color:var(--muted)}.reading{padding:11px 13px;background:#f7f8f5;border-left:3px solid var(--jade)}.anger-reading{border-left-color:var(--cinnabar)}.chart-wrap{background:#fff;border:1px solid var(--line);border-top:0;padding:14px 18px}.chart-head{display:flex;gap:12px;align-items:baseline}.chart-head h3{margin:0;font-size:20px}.chart-note{color:var(--muted);font-size:12px}.chart{height:300px;width:100%}
    .chapters{margin-top:18px;display:grid;gap:14px}.chapter{background:#fff;border:1px solid var(--line);display:grid;grid-template-columns:132px minmax(0,1fr)}.chapter-time{padding:22px 16px;background:#f7f7f3;border-right:1px solid var(--line)}.chapter-time .year{font:28px Georgia,serif;color:var(--violet)}.chapter-time .age{font-size:12px;color:var(--muted)}
    .chapter-body{padding:20px 22px}.chapter-body h3{font-size:24px;margin:0 0 10px}.voice-label{display:inline-block;font-size:11px;color:#845529;border-bottom:1px dotted #b98b58}.voice{margin:10px 0 14px;padding:14px 16px;background:#fbf8f1;border-left:3px solid var(--ochre);font-family:KaiTi,STKaiti,serif;font-size:19px;line-height:1.75}.fact{margin:8px 0;color:#414943}.work{margin-top:14px;padding-top:13px;border-top:1px solid var(--line)}.quote{font-family:KaiTi,STKaiti,serif;font-size:18px;color:#3f5160}.chips{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px}.chip{font-size:11px;padding:2px 7px;background:#eef2ee;color:#566057;border:1px solid #dbe1da}.grade{background:#f7eee4;color:#855325}
    details{margin-top:12px;color:var(--muted)}summary{cursor:pointer;color:var(--blue)}.source-list{margin:8px 0 0;padding-left:20px}.source-list a{color:var(--blue);overflow-wrap:anywhere}.scheduled{padding:34px;background:#fff;border:1px solid var(--line)}.scheduled h3{font-size:28px;margin-top:0}.readiness-bars{display:grid;gap:8px;max-width:560px}.ready-row{display:grid;grid-template-columns:150px 1fr auto;align-items:center;gap:10px}.track{height:7px;background:#e6eae4}.fill{height:100%;background:var(--jade)}
    .empty{padding:32px;color:var(--muted);text-align:center}.page-foot{margin-top:32px;padding:24px 0;border-top:1px solid var(--line);color:var(--muted)}.navlinks{display:flex;flex-wrap:wrap;gap:7px;margin-top:10px}.navlinks a{color:#4d5c53;text-decoration:none;border:1px solid var(--line);background:#fff;padding:5px 9px}.navlinks a.cur{color:#fff;background:var(--cinnabar);border-color:var(--cinnabar)}
    @media(max-width:900px){.hero{grid-template-columns:1fr}.stats{grid-template-columns:repeat(4,1fr)}.workspace{grid-template-columns:1fr}.catalog{position:static;max-height:none}.poet-list{max-height:340px}.poet-hero{grid-template-columns:1fr}.chapter{grid-template-columns:1fr}.chapter-time{border-right:0;border-bottom:1px solid var(--line);padding:12px 18px}.chart{height:260px}}
    @media(max-width:560px){.shell{padding:18px 12px 36px}.topbar-inner{padding-inline:12px}.topbar .scope{display:none}.stats{grid-template-columns:repeat(2,1fr)}.meta-grid,.portrait-grid{grid-template-columns:1fr}.poet-hero,.chapter-body,.portrait-panel{padding:18px}.ready-row{grid-template-columns:105px 1fr auto}.chart-wrap{padding-inline:8px}}
    @media(prefers-reduced-motion:reduce){html{scroll-behavior:auto}}
    /* 固定画幅背景：生命卷内容覆以轻纸白表面，滚动时画面持续可见。 */
    body{position:relative;min-height:100vh;background:transparent}
    body::before{content:"";position:fixed;inset:0;z-index:0;pointer-events:none;background:url("assets/generated/remaining_pages_20260830/39_life_scroll_v1.png") center center / cover no-repeat}
    body::after{content:"";position:fixed;inset:0;z-index:0;pointer-events:none;background:rgba(242,244,240,.13)}
    .topbar{z-index:10}.shell{position:relative;z-index:1}
    .catalog,.poet-hero,.portrait-panel,.chart-wrap,.chapter,.scheduled{background:rgba(255,255,255,.92);backdrop-filter:blur(1px)}
    .disclosure{background:rgba(255,250,240,.91)}
    .search,.meta-cell,.portrait-cell,.method-line,.chapter-time,.voice,.reading,.navlinks a{background-color:rgba(255,255,255,.89)}
  </style>
</head>
<body>
  <nav class="topbar" aria-label="项目标题"><div class="topbar-inner"><span class="seal">诗</span><span class="brand">诗行万里 · 诗人自述生命卷</span><span class="scope">39 号展项 · 首轮</span></div></nav>
  <main class="shell">
    <header class="hero">
      <div><div class="eyebrow">《平行时空》· 同素异形体</div><h1>88 位诗人，<br>从生年走向记录的尽头</h1><p>以诗人的第一视角组织生平候选史料、作品原句和情绪曲线；不伪造他们没有说过的话，不把诗中的「我」当作心理病历。</p></div>
      <div class="stats" aria-label="项目规模"><div class="stat"><b>88</b><span>诗人总册</span></div><div class="stat"><b>4</b><span>并行轮次</span></div><div class="stat"><b>22</b><span>首轮完成</span></div><div class="stat"><b>110</b><span>首轮生命章</span></div></div>
    </header>
    <p class="disclosure"><b>必读声明：</b>本页的「我」是<strong>编辑性第一人称重构</strong>，不是诗人原话，不等于史实。人物事件和作品编年仍处候选层；VAD 与幽愤/讽刺词典信号只描述作品文本，不代表诗人的完整、真实心理。</p>
    <section class="workspace">
      <aside class="catalog" aria-label="88位诗人选择器">
        <div class="catalog-head"><h2>88 人 · 四轮总册</h2><input id="poetSearch" class="search" type="search" role="searchbox" aria-label="搜索诗人" placeholder="搜索诗人…"><div class="filters" aria-label="轮次筛选"><button class="filter active" data-round="all" aria-pressed="true">88 人</button><button class="filter" data-round="1" aria-pressed="false">第 1 轮</button><button class="filter" data-round="2" aria-pressed="false">第 2 轮</button><button class="filter" data-round="3" aria-pressed="false">第 3 轮</button><button class="filter" data-round="4" aria-pressed="false">第 4 轮</button></div></div>
        <div id="poetList" class="poet-list" role="listbox" aria-label="88位诗人选择列表"></div>
      </aside>
      <article id="reader" class="reader" aria-live="polite"></article>
    </section>
    <footer class="page-foot">诗行万里 · 39 号展项 · 本页离线生成，每章均可展开证据来源。
<div class="navlinks"><a href="29_参赛导航.html">29 作品目录</a><a href="30_诗行万里_参赛版.html">30 总入口</a><a href="31_凝望罗盘.html">31 凝望罗盘</a><a href="32_身与心双层地图.html">32 双层地图</a><a href="33_平行时空759.html">33 平行时空</a><a href="34_一字识诗人.html">34 一字识诗人</a><a href="35_两种孤独与夸张签名.html">35 孤独与夸张</a><a href="36_同龄对齐.html">36 同龄对齐</a><a href="37_可听的诗.html">37 可听的诗</a><a href="38_唐宋意象潮汐.html">38 意象潮汐</a><a href="39_诗人自述生命卷.html" class="cur" aria-current="page">39 生命卷</a></div>
    </footer>
  </main>
  <script id="life-data" type="application/json">__DATA__</script>
  <script>
    "use strict";
    const DATA=JSON.parse(document.getElementById("life-data").textContent);let selected=DATA.rounds[0].poets[0],roundFilter="all",chart=null;
    const listEl=document.getElementById("poetList"),reader=document.getElementById("reader"),search=document.getElementById("poetSearch");
    const byName=Object.fromEntries(DATA.poets.map(p=>[p.name,p]));
    const esc=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
    function renderList(){
      const q=search.value.trim().toLowerCase();
      const rows=DATA.poets.filter(p=>(roundFilter==="all"||String(p.round)===roundFilter)&&(!q||p.name.toLowerCase().includes(q)));
      const selectionChanged=rows.length>0&&!rows.some(p=>p.name===selected);
      if(selectionChanged)selected=rows[0].name;
      listEl.innerHTML=rows.map(p=>`<button class="poet-button ${p.name===selected?"active":""}" role="option" aria-selected="${p.name===selected}" tabindex="${p.name===selected?0:-1}" data-poet="${esc(p.name)}"><span class="poet-name">${esc(p.name)}</span><span class="poet-meta">${esc(p.dynasty)} · ${p.corpus_poems} 首</span><span class="round-badge r${p.round}">第 ${p.round} 轮</span><span class="readiness">证据准备度 ${p.readiness.score}/100</span></button>`).join("")||'<div class="empty">未找到诗人</div>';
      const buttons=[...listEl.querySelectorAll("[data-poet]")];
      buttons.forEach((btn,index)=>{
        btn.addEventListener("click",()=>{selected=btn.dataset.poet;renderList();renderReader();});
        btn.addEventListener("keydown",event=>{
          const key=event.key;
          if(!["ArrowDown","ArrowUp","Home","End"].includes(key))return;
          event.preventDefault();
          const next=key==="Home"?0:key==="End"?buttons.length-1:key==="ArrowDown"?Math.min(buttons.length-1,index+1):Math.max(0,index-1);
          buttons[next].click();
          requestAnimationFrame(()=>listEl.querySelector('[tabindex="0"]')?.focus());
        });
      });
      if(selectionChanged)renderReader();
    }
    function sourceItems(ids){return ids.map(id=>DATA.sources[id]).filter(Boolean).map(s=>`<li><b>${esc(s.name)}</b> · ${esc(s.grade||"未分级")} · ${esc(s.status||"未标注")}${s.url?` · <a href="${esc(s.url)}" target="_blank" rel="noreferrer">来源页</a>`:""}<br>${esc(s.note||"")}</li>`).join("");}
    function chapterHTML(ch){const w=ch.work;const year=ch.year_end!==ch.year_start?`${ch.year_start}–${ch.year_end}`:ch.year_start;const age=Array.isArray(ch.age_range)?(ch.age_range[0]===ch.age_range[1]?`约 ${ch.age_range[0]} 岁`:`约 ${ch.age_range[0]}–${ch.age_range[1]} 岁`):(ch.age===null?"年龄待考":`约 ${ch.age} 岁`);return `<section class="chapter"><div class="chapter-time"><div class="year">${year}</div><div class="age">${age}</div><div class="chips"><span class="chip grade">${esc(ch.source_grade)} 级</span><span class="chip">${esc(ch.assertion_status)}</span></div></div><div class="chapter-body"><h3>${esc(ch.title)}</h3><span class="voice-label">${esc(ch.voice_label)}</span><blockquote class="voice">${esc(ch.first_person)}</blockquote><p class="fact"><b>可回查事实层：</b>${esc(ch.event_fact)}</p>${w?`<div class="work"><b>《${esc(w.title)}》</b> · 编年候选 ${w.year} 年 · ${esc(w.source_grade)} 级<p class="quote">「${esc(w.quote)}」</p><div class="chips"><span class="chip">${esc(w.emotion_summary)}</span>${w.emotion_evidence.map(t=>`<span class="chip">${esc(t)}</span>`).join("")}</div></div>`:""}<details><summary>查看证据与边界</summary><p>${esc(ch.evidence_note)}</p><ul class="source-list">${sourceItems(ch.source_ids)}</ul></details></div></section>`;}
    function readinessHTML(p){const r=p.readiness,items=[["人物事件候选",r.person_event_candidates],["可定位候选",r.locatable_candidates],["作品编年候选",r.work_chronology_candidates]];const max=Math.max(1,...items.map(x=>x[1]));const isGap=p.status.endsWith("evidence_gap");const title=isGap?`第 ${p.round} 轮 · 证据不足（正式结果）`:`已排入第 ${p.round} 轮`;const note=isGap?`${p.name}已经进入本轮处理，但现有生卒、事件与作品编年不足以建立时间轴。这里保留空白，不虚构连续人生。`:`${p.name}已进入 88 人总册。本轮先公布语料规模、轮次与候选证据准备度，不提前生成未复核的第一人称经历。`;return `<section class="scheduled"><h3>${title}</h3><p>${esc(note)}</p><div class="readiness-bars">${items.map(([label,value])=>`<div class="ready-row"><span>${label}</span><span class="track"><span class="fill" style="width:${Math.max(2,Math.round(value/max*100))}%"></span></span><b>${value}</b></div>`).join("")}</div><p><small>${esc(r.boundary)}</small></p></section>`;}
    function portraitHTML(p){const x=p.portrait;if(!x)return "";const c=x.emotional_center;const top=x.dominant_emotions.map(item=>`<span class="chip">${esc(item.label)} ${Math.round(item.share*100)}%</span>`).join("");const works=x.anger.representative_works.map(item=>`《${esc(item.title)}》 ${Math.round(item.signal*100)}%`).join("、")||"无高置信代表作";return `<section class="portrait-panel"><h3>作品里的这个人：先给可证伪的答案</h3><p>${esc(x.summary)}</p><div class="chips">${top}${x.textual_traits.slice(0,4).map(t=>`<span class="chip">${esc(t)}</span>`).join("")}</div><div class="portrait-grid"><div class="portrait-cell"><b>${c.valence??"—"}</b><span>全语料平均效价</span></div><div class="portrait-cell"><b>${c.arousal??"—"}</b><span>全语料平均唤醒</span></div><div class="portrait-cell"><b>${c.dominance??"—"}</b><span>全语料平均掌控</span></div></div><p class="reading"><b>曲线读法：</b>${esc(x.curve_reading)}</p><p class="reading anger-reading"><b>幽愤/讽刺词典信号：</b>${esc(x.anger.reading)} <small>词典高信号样本：${works}</small></p></section>`;}
    function drawChart(p){if(chart){chart.dispose();chart=null;}if(!p.chapters.length)return;const node=document.getElementById("lifeChart");chart=echarts.init(node,null,{renderer:"canvas"});const dims=[["valence","效价", "#b64b3f"],["arousal","唤醒", "#a87527"],["dominance","掌控", "#26786e"],["anger_signal","幽愤/讽刺词典信号", "#7d4d63"],["confidence","文本画像置信度", "#426f94"]];chart.setOption({animation:false,grid:{left:48,right:20,top:56,bottom:44},legend:{top:4,textStyle:{color:"#59615b"}},tooltip:{trigger:"axis",valueFormatter:v=>v===null?"无作品文本信号":Number(v).toFixed(3)},xAxis:{type:"category",data:p.chapters.map(c=>c.work?String(c.work.year):(c.year_end!==c.year_start?`${c.year_start}–${c.year_end}`:String(c.year_start))),axisLine:{lineStyle:{color:"#aeb7af"}}},yAxis:{type:"value",min:-1,max:1,splitLine:{lineStyle:{color:"#e5e9e3"}}},series:dims.map(([key,name,color])=>({name,type:"line",connectNulls:false,symbol:"circle",symbolSize:8,lineStyle:{width:2,color},itemStyle:{color},data:p.chapters.map(c=>c.dimensions[key])}))});}
    function renderReader(){const p=byName[selected];const life=p.lifespan?.label||"生卒待考";const state=p.status==="scheduled"?"已排期":p.status.endsWith("evidence_gap")?"证据不足":p.round===DATA.project.active_round?"本轮已生成":"已生成";reader.innerHTML=`<header class="poet-hero"><div><div class="eyebrow">第 ${p.round} 轮 · ${state}</div><h2>${esc(p.name)}</h2><div class="poet-sub">${esc(p.dynasty)} · ${esc(life)}</div></div><div class="meta-grid"><div class="meta-cell"><b>${p.corpus_poems}</b><span>全作品状态语料</span></div><div class="meta-cell"><b>${p.readiness.score}</b><span>证据准备度</span></div><div class="meta-cell"><b>${p.chapters.length}</b><span>已生成生命章</span></div></div></header><p class="method-line">文本画像使用名家全作品；生命曲线只连接规范诗作的编年候选。它不是一条「一路上升/下降」的传记定论，允许数据反驳成见。</p>${p.chapters.length?`${portraitHTML(p)}<section class="chart-wrap"><div class="chart-head"><h3>作品文本情绪曲线</h3><span class="chart-note">-1 至 1 · 空点表示该章无可连接作品</span></div><div id="lifeChart" class="chart" role="img" aria-label="${esc(p.name)}作品文本情绪曲线"></div></section><div class="chapters">${p.chapters.map(chapterHTML).join("")}</div>`:readinessHTML(p)}`;drawChart(p);}
    search.addEventListener("input",renderList);document.querySelectorAll(".filter").forEach(btn=>btn.addEventListener("click",()=>{roundFilter=btn.dataset.round;document.querySelectorAll(".filter").forEach(x=>{const on=x===btn;x.classList.toggle("active",on);x.setAttribute("aria-pressed",String(on));});renderList();}));window.addEventListener("resize",()=>chart&&chart.resize());renderList();renderReader();
  </script>
</body>
</html>'''


def main() -> None:
    payload = build_payload()
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    compact = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_HTML.write_text(HTML_TEMPLATE.replace("__DATA__", compact.replace("</", "<\\/")), encoding="utf-8")
    active_round = int(payload["project"]["active_round"])
    generated = [poet for poet in payload["poets"] if poet["round"] <= active_round]
    active = [poet for poet in payload["poets"] if poet["round"] == active_round]
    chapters = sum(len(poet["chapters"]) for poet in generated)
    assert len(payload["poets"]) == 88
    assert len(active) == 22 and all(
        len(poet["chapters"]) >= 4 or poet["status"].endswith("evidence_gap")
        for poet in generated
    )
    assert "http" not in "".join(re.findall(r'<script[^>]+src=["\']([^"\']+)', OUT_HTML.read_text(encoding="utf-8")))
    print(f"[ok] 88 人四轮总册；已推进至第 {active_round} 轮 / {len(generated)} 人 / {chapters} 章")
    print(f"[ok] JSON {OUT_JSON.stat().st_size:,} bytes -> {OUT_JSON}")
    print(f"[ok] HTML {OUT_HTML.stat().st_size:,} bytes -> {OUT_HTML}")


if __name__ == "__main__":
    main()
