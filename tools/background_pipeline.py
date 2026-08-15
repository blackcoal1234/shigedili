"""Collect, review, and publish traceable poem-background evidence."""
from __future__ import annotations

import argparse
import csv
import html
import io
import json
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qs, urlparse

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

from background_adapters import (  # noqa: E402
    HttpCacheClient,
    collect_cnkgraph,
    collect_gushiwen,
    enrich_place_with_chgis,
    ensure_cbdb_database,
    query_cbdb_identities,
)
from background_contract import (  # noqa: E402
    CANDIDATES_JSONL,
    CLAIM_TYPES,
    COLLECTION_STATUS_JSONL,
    CORE_POETS,
    FACT_CLAIM_TYPES,
    LEGACY_CONTEXTS_CSV,
    MANUAL_FIELDS,
    MANUAL_TEMPLATE_CSV,
    MAX_EVIDENCE_CHARS,
    POET_STATUS_JSONL,
    PROMPT_VERSION,
    REVIEWED_DIR,
    REVIEW_EXPORT_CSV,
    REVIEW_FIELDS,
    RICH_BACKGROUNDS_JSONL,
    SOURCE_BASE,
    STATUSES,
    atomic_write_text,
    candidate_poem_identity,
    compact_json,
    confidence_for,
    corpus_poets,
    deterministic_id,
    ensure_manual_template,
    first_line,
    load_poems,
    make_candidate,
    normalize_excerpt,
    normalize_title,
    poem_key,
    read_jsonl,
    select_poems,
    upsert_candidates,
    utc_now,
    validate_candidate,
    write_jsonl,
    write_review_csv,
)
from poet_source_registry import refresh_source_registry  # noqa: E402


LEGACY_FIELDS = (
    "poet",
    "title",
    "dynasty",
    "year_start",
    "year_end",
    "historical_place",
    "modern_city",
    "province",
    "lon",
    "lat",
    "source_name",
    "source_url",
    "source_note",
    "fact_grade",
    "status",
)

FACT_PUBLISHABLE = {"A", "B"}
DEFAULT_SOURCES = ("cnkgraph", "gushiwen", "cbdb", "chgis")
CONFLICT_CLAIM_TYPES = {"composition_date", "composition_place"}
OPEN_CONFLICT_STATUSES = {"collected", "extracted", "needs_review", "approved", "disputed"}
POET_LIFE_CACHE_JSON = ROOT / "data" / "cnkgraph_poet_life_cache.json"
POET_JOURNEYS_JSON = ROOT / "data" / "reviewed" / "poet_journeys.json"

LI_QINGZHAO_CACHE_EVIDENCE = {
    "一剪梅·红藕香残玉簟秋": {
        "locator": "李清照年历/1090、1103条目",
        "fragments": (
            "开封（1090年 - 1107年3月，7-24岁，作品：15）",
            "1103年7月，赵明诚出游。有词送别，作品：《一剪梅》",
        ),
    },
    "醉花阴·薄雾浓云愁永昼": {
        "locator": "李清照年历/1108条目",
        "fragments": (
            "益都（1108年 - 1121年，25-38岁，作品：13）",
            "1108年9月9日，赵明诚游仰天山，清照有词思之，作品：《醉花阴》",
        ),
    },
    "凤凰台上忆吹箫·香冷金猊": {
        "locator": "李清照年历/1108、1109条目",
        "fragments": (
            "益都（1108年 - 1121年，25-38岁，作品：13）",
            "1109年9月13日，赵明诚出游，有词抒思念之情，作品：《凤凰台上忆吹箫》",
        ),
    },
    "蝶恋花·晚止昌乐馆寄姊妹": {
        "locator": "李清照年历/1121昌乐条目",
        "fragments": (
            "昌乐（1121年，38岁，作品：1）",
            "1121年，秋，清照赴莱州途径昌乐，有词寄姊妹",
        ),
    },
    "声声慢·寻寻觅觅": {
        "locator": "李清照年历/1147条目",
        "fragments": (
            "1147年，居临安。有词《声声慢》写国破家亡晚年孀居之惨戚，作品：《声声慢》",
        ),
    },
}


def poem_lookup() -> tuple[dict[tuple[str, str], dict[str, Any]], dict[str, dict[str, Any]]]:
    by_name_title: dict[tuple[str, str], dict[str, Any]] = {}
    by_hash: dict[str, dict[str, Any]] = {}
    for poem in load_poems():
        by_name_title[(str(poem.get("poet") or ""), normalize_title(poem.get("title")))] = poem
        by_hash[str(poem.get("body_hash") or "")] = poem
    return by_name_title, by_hash


def value_dict(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {"text": value}
        return parsed if isinstance(parsed, dict) else {"value": parsed}
    return {"value": value}


def strongest_grade(grades: Iterable[str]) -> str:
    order = {"A": 4, "B": 3, "C": 2, "D": 1}
    values = [str(grade or "D").upper()[:1] for grade in grades]
    return max(values, key=lambda grade: order.get(grade, 0), default="D")


def legacy_grade(row: dict[str, str]) -> str:
    grade = str(row.get("fact_grade") or "C").upper()[:1]
    source = f"{row.get('source_name', '')} {row.get('source_note', '')}"
    if grade == "A" and "API" in source and not any(token in source for token in ("作品序", "词序", "诗序", "题跋", "正史")):
        return "B"
    return grade if grade in SOURCE_BASE else "C"


def candidate_claim_signature(candidate: dict[str, Any]) -> tuple[str, str, str]:
    key = candidate.get("poem_key") if isinstance(candidate.get("poem_key"), dict) else {}
    return (
        str(key.get("body_hash") or ""),
        str(candidate.get("claim_type") or ""),
        compact_json(candidate.get("value")),
    )


def migrate_legacy_contexts(existing: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not LEGACY_CONTEXTS_CSV.exists():
        return existing
    by_name_title, _ = poem_lookup()
    incoming: list[dict[str, Any]] = []
    represented_claims = {
        candidate_claim_signature(row)
        for row in existing
        if row.get("status") == "approved"
    }
    reviewed_at = datetime.fromtimestamp(
        LEGACY_CONTEXTS_CSV.stat().st_mtime,
        tz=timezone.utc,
    ).isoformat(timespec="seconds")
    with LEGACY_CONTEXTS_CSV.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            poem = by_name_title.get(
                (str(row.get("poet") or "").strip(), normalize_title(row.get("title")))
            )
            if not poem:
                continue
            grade = legacy_grade(row)
            evidence = normalize_excerpt(row.get("source_note") or "Legacy reviewed context")
            source_url = str(row.get("source_url") or "").strip()
            source_key = f"legacy:{deterministic_id(row.get('source_name'), source_url)[:20]}"
            common = {
                "evidence_excerpt": evidence,
                "source_key": source_key,
                "source_name": str(row.get("source_name") or "历史审核数据"),
                "source_url": source_url,
                "citation": str(row.get("source_name") or "历史审核数据"),
                "source_locator": source_url or "legacy-review",
                "source_grade": grade,
                "access_level": "public_web" if source_url else "authenticated_manual",
                "license_note": "历史审核记录迁移；仅保留短引与题录",
                "match_score": 0.95,
                "extraction_method": "legacy_review_migration_v1",
                "status": "approved",
            }
            year_start = _int_or_none(row.get("year_start"))
            year_end = _int_or_none(row.get("year_end")) or year_start
            date_candidate = make_candidate(
                poem,
                "composition_date",
                {"year_start": year_start, "year_end": year_end, "precision": "range" if year_start != year_end else "year"},
                **common,
            )
            place_candidate = make_candidate(
                poem,
                "composition_place",
                {
                    "historical_place": str(row.get("historical_place") or ""),
                    "modern_place": str(row.get("modern_city") or ""),
                    "province": str(row.get("province") or ""),
                    "lon": _float_or_none(row.get("lon")),
                    "lat": _float_or_none(row.get("lat")),
                },
                **common,
            )
            for candidate in (date_candidate, place_candidate):
                candidate.update(
                    reviewer="legacy_import",
                    review_note="Migrated from verified_poem_contexts.csv",
                    reviewed_at=reviewed_at,
                )
                signature = candidate_claim_signature(candidate)
                if signature not in represented_claims:
                    incoming.append(candidate)
                    represented_claims.add(signature)
    return upsert_candidates(existing, incoming)


def migrate_linqingzhao_cache_contexts(
    existing: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Migrate five already-reviewed Li Qingzhao contexts through candidates."""
    if not POET_LIFE_CACHE_JSON.exists() or not POET_JOURNEYS_JSON.exists():
        return existing

    cache = json.loads(POET_LIFE_CACHE_JSON.read_text(encoding="utf-8"))
    poet_cache = (cache.get("poets") or {}).get("李清照") or {}
    timeline_texts = {
        str(row.get("text") or "").strip()
        for row in poet_cache.get("timeline") or []
        if isinstance(row, dict)
    }
    journeys = json.loads(POET_JOURNEYS_JSON.read_text(encoding="utf-8"))
    poet_group = next(
        (
            group
            for group in journeys.get("poets") or []
            if isinstance(group, dict) and group.get("poet") == "李清照"
        ),
        None,
    )
    if not poet_group:
        raise ValueError("李清照审核行旅节点不存在，无法迁移创作背景")

    nodes_by_title = {
        str((node.get("linked_poem") or {}).get("title") or ""): node
        for node in poet_group.get("nodes") or []
        if isinstance(node, dict) and isinstance(node.get("linked_poem"), dict)
    }
    by_name_title, _ = poem_lookup()
    reviewed_at = datetime.fromtimestamp(
        POET_JOURNEYS_JSON.stat().st_mtime,
        tz=timezone.utc,
    ).isoformat(timespec="seconds")
    source_url = str(poet_cache.get("source_url") or "").strip()
    incoming: list[dict[str, Any]] = []

    for title, evidence_spec in LI_QINGZHAO_CACHE_EVIDENCE.items():
        fragments = tuple(str(item) for item in evidence_spec["fragments"])
        missing = [fragment for fragment in fragments if fragment not in timeline_texts]
        if missing:
            raise ValueError(f"李清照年谱缓存缺少预期证据：{title} -> {missing}")
        poem = by_name_title.get(("李清照", normalize_title(title)))
        node = nodes_by_title.get(title)
        if not poem or not node:
            raise ValueError(f"李清照审核作品无法匹配：{title}")

        evidence_excerpt = normalize_excerpt("；".join(fragments))
        common = {
            "evidence_excerpt": evidence_excerpt,
            "source_key": "cnkgraph:poet-life:李清照",
            "source_name": str(node.get("source_name") or "CNKGraph 李清照年历"),
            "source_url": source_url,
            "citation": "徐培均《李清照年谱》（CNKGraph人物年历转述）",
            "source_locator": str(evidence_spec["locator"]),
            "source_grade": "B",
            "access_level": "public_web",
            "license_note": "既有公开缓存迁移；仅保留题录与必要短引",
            "match_score": 0.85,
            "extraction_method": "existing_cache_migration_v1",
            "status": "approved",
            "collected_at": str(cache.get("updated_at") or utc_now()),
        }
        year = _int_or_none(node.get("year"))
        date_candidate = make_candidate(
            poem,
            "composition_date",
            {"year_start": year, "year_end": year, "precision": str(node.get("year_precision") or "year")},
            **common,
        )
        place_candidate = make_candidate(
            poem,
            "composition_place",
            {
                "historical_place": str(node.get("place_historical") or ""),
                "modern_place": str(node.get("place_modern") or ""),
                "province": str(node.get("place_modern") or "")[:3],
                "lon": _float_or_none(node.get("longitude")),
                "lat": _float_or_none(node.get("latitude")),
            },
            **common,
        )
        for candidate in (date_candidate, place_candidate):
            candidate.update(
                reviewer="existing_cache_migration",
                review_note="由已审核行旅节点人工映射；短题关联不作自动匹配，CNKGraph转述年谱按B级处理。",
                reviewed_at=reviewed_at,
            )
            incoming.append(candidate)
    return upsert_candidates(existing, incoming)


def _int_or_none(value: object) -> int | None:
    try:
        return int(float(str(value))) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _float_or_none(value: object) -> float | None:
    try:
        return float(str(value)) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def load_and_migrate_candidates() -> list[dict[str, Any]]:
    candidates = migrate_legacy_contexts(read_jsonl(CANDIDATES_JSONL))
    candidates = migrate_linqingzhao_cache_contexts(candidates)
    write_jsonl(CANDIDATES_JSONL, candidates)
    ensure_manual_template()
    ensure_poet_status_coverage()
    return candidates


def merge_status_rows(path: Path, incoming: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    existing = read_jsonl(path)
    merged: dict[str, dict[str, Any]] = {}
    for row in [*existing, *incoming]:
        key = deterministic_id(row.get("poem_key") or row.get("poet"), row.get("adapter") or "identity")
        merged[key] = row
    rows = sorted(
        merged.values(),
        key=lambda row: (
            str((row.get("poem_key") or {}).get("poet") if isinstance(row.get("poem_key"), dict) else row.get("poet") or ""),
            str((row.get("poem_key") or {}).get("title") if isinstance(row.get("poem_key"), dict) else ""),
            str(row.get("adapter") or ""),
        ),
    )
    write_jsonl(path, rows)
    return rows


def ensure_poet_status_coverage() -> list[dict[str, Any]]:
    existing = read_jsonl(POET_STATUS_JSONL)
    covered = {str(row.get("poet") or "").strip() for row in existing}
    pending = [
        {
            "poet": poet,
            "status": "pending_collection",
            "matches": [],
            "source_name": "China Biographical Database SQLite",
            "source_url": "https://github.com/cbdb-project/cbdb_sqlite",
            "note": "运行 collect --scope all 完成人物身份解析",
            "checked_at": "",
        }
        for poet in corpus_poets()
        if poet not in covered
    ]
    return merge_status_rows(POET_STATUS_JSONL, pending) if pending else existing


def _date_interval(candidate: dict[str, Any]) -> tuple[int, int] | None:
    value = value_dict(candidate.get("value"))
    start = _int_or_none(value.get("year_start") or value.get("year"))
    end = _int_or_none(value.get("year_end") or value.get("year")) or start
    if start is None or end is None:
        return None
    return min(start, end), max(start, end)


def _normalized_place(value: object) -> str:
    return re.sub(r"[\s·,，。省市县区府州路道]+", "", str(value or "")).casefold()


def fact_group_conflicts(rows: list[dict[str, Any]]) -> bool:
    independent = {str(row.get("source_key") or "") for row in rows if row.get("source_key")}
    if len(independent) < 2 or not rows:
        return False
    claim_type = str(rows[0].get("claim_type") or "")
    if claim_type == "composition_date":
        intervals = [interval for row in rows if (interval := _date_interval(row))]
        return len(intervals) >= 2 and max(start for start, _ in intervals) > min(
            end for _, end in intervals
        )
    if claim_type == "composition_place":
        values = [value_dict(row.get("value")) for row in rows]
        modern = [
            _normalized_place(value.get("modern_place") or value.get("modern_city"))
            for value in values
        ]
        if all(modern):
            return len(set(modern)) > 1
        external_ids = [str(value.get("chgis_id") or value.get("region_id") or "").strip() for value in values]
        if all(external_ids):
            return len(set(external_ids)) > 1
        historical = [_normalized_place(value.get("historical_place")) for value in values]
        return bool(all(historical) and len(set(historical)) > 1)
    return False


def mark_source_conflicts(
    candidates: list[dict[str, Any]],
    *,
    include_approved: bool = False,
) -> int:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for candidate in candidates:
        if candidate.get("claim_type") not in CONFLICT_CLAIM_TYPES:
            continue
        if candidate.get("status") not in OPEN_CONFLICT_STATUSES:
            continue
        key = candidate.get("poem_key") if isinstance(candidate.get("poem_key"), dict) else {}
        groups[(str(key.get("body_hash") or ""), str(candidate.get("claim_type") or ""))].append(candidate)

    changed = 0
    for rows in groups.values():
        if fact_group_conflicts(rows):
            for row in rows:
                if row.get("status") == "approved" and not include_approved:
                    continue
                if row.get("status") != "disputed":
                    row["status"] = "disputed"
                    changed += 1
                note = str(row.get("review_note") or "").strip()
                marker = "来源对创作时间或地点存在冲突，需人工裁决"
                row["review_note"] = f"{note}；{marker}" if note and marker not in note else note or marker
                row["confidence"] = confidence_for(
                    str(row.get("source_grade") or "D"),
                    float(row.get("match_score") or 0),
                    conflict=True,
                )
            continue

        by_value: dict[str, set[str]] = defaultdict(set)
        for row in rows:
            by_value[compact_json(row.get("value"))].add(str(row.get("source_key") or ""))
        for row in rows:
            agreeing = len({key for key in by_value[compact_json(row.get("value"))] if key})
            row["confidence"] = confidence_for(
                str(row.get("source_grade") or "D"),
                float(row.get("match_score") or 0),
                agreeing_sources=agreeing,
                conflict=row.get("status") == "disputed",
            )
    return changed


def enrich_cnkgraph_places(
    candidates: list[dict[str, Any]],
    client: HttpCacheClient,
) -> None:
    dates: dict[tuple[str, str, str], int | None] = {}
    for candidate in candidates:
        identity = candidate_poem_identity(candidate)
        if candidate.get("claim_type") == "composition_date":
            dates[identity] = _int_or_none(value_dict(candidate.get("value")).get("year_start"))
    for candidate in candidates:
        if candidate.get("claim_type") != "composition_place":
            continue
        value = value_dict(candidate.get("value"))
        if value.get("lon") not in (None, "") and value.get("lat") not in (None, ""):
            continue
        place = str(value.get("historical_place") or value.get("modern_place") or "").split("·", 1)[0]
        if not place:
            continue
        mapped, result = enrich_place_with_chgis(place, dates.get(candidate_poem_identity(candidate)), client)
        if not mapped:
            continue
        value.update(
            {
                "chgis_id": mapped.get("chgis_id"),
                "chgis_years": mapped.get("years"),
                "chgis_parent": mapped.get("parent"),
                "lon": mapped.get("lon"),
                "lat": mapped.get("lat"),
                "chgis_uri": mapped.get("uri"),
                "chgis_cache_key": result.cache_key,
            }
        )
        candidate["value"] = value


def collect_command(args: argparse.Namespace) -> int:
    candidates = load_and_migrate_candidates()
    refresh_source_registry()
    max_per = args.max_poems_per_poet
    if max_per is None and args.scope == "all":
        max_per = 1
    poems = select_poems(args.scope, max_per)
    sources = tuple(token.strip().casefold() for token in args.sources.split(",") if token.strip())
    unsupported = set(sources) - set(DEFAULT_SOURCES)
    if unsupported:
        raise SystemExit(f"Unsupported sources: {sorted(unsupported)}")
    client = HttpCacheClient(
        timeout=args.timeout,
        retries=args.retries,
        min_delay=args.min_delay,
        max_delay=args.max_delay,
        offline=args.offline,
    )

    existing_status = read_jsonl(COLLECTION_STATUS_JSONL)
    terminal_statuses = {"collected", "insufficient", "blocked_by_policy"}
    completed = {
        (
            str((row.get("poem_key") or {}).get("body_hash") or ""),
            str(row.get("adapter") or ""),
        )
        for row in existing_status
        if row.get("status") in terminal_statuses
    } if args.resume else set()
    incoming_candidates: list[dict[str, Any]] = []
    statuses: list[dict[str, Any]] = []
    for index, poem in enumerate(poems, start=1):
        print(f"[{index}/{len(poems)}] {poem.get('poet')}《{poem.get('title')}》")
        for source in ("cnkgraph", "gushiwen"):
            if source not in sources:
                continue
            status_key = (str(poem.get("body_hash") or ""), source)
            if status_key in completed:
                continue
            collector = collect_cnkgraph if source == "cnkgraph" else collect_gushiwen
            rows, status = collector(poem, client)
            incoming_candidates.extend(rows)
            statuses.append(status)
            print(f"  {source}: {status.get('status')} / {len(rows)} claims")

    if "chgis" in sources:
        enrich_cnkgraph_places(incoming_candidates, client)

    candidates = upsert_candidates(candidates, incoming_candidates)
    mark_source_conflicts(candidates)
    write_jsonl(CANDIDATES_JSONL, candidates)
    merge_status_rows(COLLECTION_STATUS_JSONL, statuses)

    if "cbdb" in sources:
        poets = sorted({str(poem.get("poet") or "") for poem in poems if poem.get("poet")})
        db_path, manifest = ensure_cbdb_database(client)
        if db_path:
            identity_rows = query_cbdb_identities(db_path, poets, manifest)
        else:
            identity_rows = [
                {
                    "poet": poet,
                    "status": str(manifest.get("status") or "not_found"),
                    "note": str(manifest.get("note") or "CBDB database unavailable"),
                    "source_name": "China Biographical Database SQLite",
                    "source_url": "https://github.com/cbdb-project/cbdb_sqlite",
                    "checked_at": utc_now(),
                }
                for poet in poets
            ]
        merged_identities = merge_status_rows(POET_STATUS_JSONL, identity_rows)
        refresh_source_registry(merged_identities)

    print(f"Candidates: {len(candidates)} -> {CANDIDATES_JSONL}")
    print(f"Collection status: {COLLECTION_STATUS_JSONL}")
    return 0


def source_excerpt_corpus(rows: Iterable[dict[str, Any]]) -> str:
    return "\n".join(
        str(row.get("evidence_excerpt") or "")
        for row in rows
        if str(row.get("evidence_excerpt") or "")
    )


def parse_model_json(content: str) -> dict[str, Any]:
    text = content.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, re.IGNORECASE)
    if fence:
        text = fence.group(1).strip()
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError("model response must be a JSON object")
    return value


def validate_model_claims(
    poem: dict[str, Any],
    source_rows: list[dict[str, Any]],
    payload: dict[str, Any],
    model_id: str,
) -> list[dict[str, Any]]:
    source_corpus = source_excerpt_corpus(source_rows)
    original = str(poem.get("body") or "")
    candidates: list[dict[str, Any]] = []
    for raw in payload.get("claims") or []:
        if not isinstance(raw, dict):
            continue
        claim_type = str(raw.get("claim_type") or "")
        if claim_type not in CLAIM_TYPES:
            continue
        evidence = normalize_excerpt(raw.get("evidence_excerpt"))
        factual = claim_type in FACT_CLAIM_TYPES
        project_literary_claim = claim_type in {"translation", "appreciation"}
        allowed_corpus = source_corpus if factual else original if project_literary_claim else source_corpus + "\n" + original
        if not evidence or evidence not in allowed_corpus:
            continue
        evidence_source = next(
            (row for row in source_rows if evidence in str(row.get("evidence_excerpt") or "")),
            None,
        )
        if factual and not evidence_source:
            continue
        if evidence in original and not factual:
            evidence_source = None
        source = evidence_source or {
            "source_key": "project:model-assisted",
            "source_name": "项目模型辅助整理",
            "source_url": "",
            "citation": "基于原诗与已审核短引生成",
            "source_locator": "original-poem",
            "source_grade": "D",
            "access_level": "project_generated",
            "license_note": "项目生成内容；模型不作为事实来源",
            "match_score": 0.95,
        }
        candidates.append(
            make_candidate(
                poem,
                claim_type,
                raw.get("value"),
                evidence_excerpt=evidence,
                source_key=str(source.get("source_key") or "project:model-assisted"),
                source_name=str(source.get("source_name") or "项目模型辅助整理"),
                source_url=str(source.get("source_url") or ""),
                citation=str(source.get("citation") or ""),
                source_locator=str(source.get("source_locator") or "original-poem"),
                source_grade=str(source.get("source_grade") or "D"),
                access_level=str(source.get("access_level") or "project_generated"),
                license_note=str(source.get("license_note") or ""),
                match_score=float(source.get("match_score") or 0.95),
                extraction_method="llm_evidence_extract_v1",
                model_id=model_id,
                prompt_version=PROMPT_VERSION,
                status="needs_review",
            )
        )
    return candidates


def llm_request(poem: dict[str, Any], source_rows: list[dict[str, Any]]) -> tuple[dict[str, Any], str]:
    base_url = os.environ.get("BACKGROUND_LLM_BASE_URL", "https://api.deepseek.com")
    api_key = os.environ.get("BACKGROUND_LLM_API_KEY", "")
    model = os.environ.get("BACKGROUND_LLM_MODEL", "deepseek-v4-flash")
    if not api_key:
        raise SystemExit("Missing BACKGROUND_LLM_API_KEY")
    endpoint = base_url.rstrip("/")
    if not endpoint.endswith("/chat/completions"):
        endpoint += "/chat/completions"
    evidence = [
        {
            "candidate_id": row.get("candidate_id"),
            "source_name": row.get("source_name"),
            "source_locator": row.get("source_locator"),
            "source_grade": row.get("source_grade"),
            "excerpt": row.get("evidence_excerpt"),
        }
        for row in source_rows
        if row.get("evidence_excerpt")
    ]
    prompt = {
        "task": "只根据原诗和证据短引生成结构化候选，不使用外部知识，不补全缺失事实。",
        "poem": {
            "poet": poem.get("poet"),
            "title": poem.get("title"),
            "dynasty": poem.get("dynasty"),
            "body": poem.get("body"),
        },
        "evidence": evidence,
        "output": {
            "claims": [
                {
                    "claim_type": "允许的类型",
                    "value": "字符串或对象",
                    "evidence_excerpt": "必须逐字来自某条证据短引；译注赏析可来自原诗",
                }
            ]
        },
        "constraints": [
            "事实类候选没有证据则不输出",
            "翻译逐句输出，value包含line_no、original、translation",
            "注释value包含line_no、original、annotation",
            "赏析只给可由原诗支持的要点",
            "返回纯JSON",
        ],
    }
    response = requests.post(
        endpoint,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": model,
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": "你是古典诗词证据整理助手。事实必须逐字引用给定证据。"},
                {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
            ],
        },
        timeout=90,
    )
    response.raise_for_status()
    payload = response.json()
    content = payload["choices"][0]["message"]["content"]
    return parse_model_json(content), model


def extract_command(args: argparse.Namespace) -> int:
    if not args.llm:
        raise SystemExit("extract currently requires --llm")
    candidates = load_and_migrate_candidates()
    poems = select_poems(args.scope, args.max_poems_per_poet)
    by_hash = {str(poem.get("body_hash") or ""): poem for poem in poems}
    source_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in candidates:
        key = row.get("poem_key") if isinstance(row.get("poem_key"), dict) else {}
        digest = str(key.get("body_hash") or "")
        if digest in by_hash and row.get("extraction_method") != "llm_evidence_extract_v1":
            source_rows[digest].append(row)
    incoming: list[dict[str, Any]] = []
    processed = 0
    for digest, poem in by_hash.items():
        rows = source_rows.get(digest, [])
        if not rows:
            continue
        if args.limit is not None and processed >= args.limit:
            break
        payload, model = llm_request(poem, rows)
        generated = validate_model_claims(poem, rows, payload, model)
        incoming.extend(generated)
        processed += 1
        print(f"{poem.get('poet')}《{poem.get('title')}》: {len(generated)} model candidates")
    candidates = upsert_candidates(candidates, incoming)
    mark_source_conflicts(candidates)
    write_jsonl(CANDIDATES_JSONL, candidates)
    print(f"Extracted {len(incoming)} candidates from {processed} poems")
    return 0


def find_manual_poem(row: dict[str, str], lookup: dict[tuple[str, str], dict[str, Any]]) -> dict[str, Any] | None:
    return lookup.get((str(row.get("poet") or "").strip(), normalize_title(row.get("title"))))


def manual_candidates_from_csv(text: str) -> list[dict[str, Any]]:
    by_name_title, _ = poem_lookup()
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
    missing = set(MANUAL_FIELDS) - set(reader.fieldnames or ())
    if missing:
        raise ValueError(f"manual CSV missing fields: {sorted(missing)}")
    candidates: list[dict[str, Any]] = []
    required_manual = (
        "evidence_excerpt",
        "source_title",
        "source_author",
        "publisher",
        "publication_year",
        "edition",
        "page",
        "access_level",
    )
    for line_no, row in enumerate(reader, start=2):
        if not any(str(value or "").strip() for value in row.values()):
            continue
        poem = find_manual_poem(row, by_name_title)
        if not poem:
            raise ValueError(f"line {line_no}: poem not found: {row.get('poet')}《{row.get('title')}》")
        missing_values = [field for field in required_manual if not str(row.get(field) or "").strip()]
        if missing_values:
            raise ValueError(f"line {line_no}: required manual fields are empty: {missing_values}")
        excerpt = re.sub(r"\s+", " ", str(row.get("evidence_excerpt") or "")).strip()
        if len(excerpt) > MAX_EVIDENCE_CHARS:
            raise ValueError(
                f"line {line_no}: evidence excerpt exceeds {MAX_EVIDENCE_CHARS} characters"
            )
        claim_type = str(row.get("claim_type") or "").strip()
        if claim_type not in CLAIM_TYPES:
            raise ValueError(f"line {line_no}: invalid claim_type")
        try:
            value = json.loads(row.get("value_json") or "null")
        except json.JSONDecodeError as exc:
            raise ValueError(f"line {line_no}: invalid value_json") from exc
        citation = "，".join(
            token
            for token in (
                row.get("source_author"),
                row.get("source_title"),
                row.get("publisher"),
                row.get("edition"),
                row.get("publication_year"),
            )
            if token
        )
        source_locator = f"第{row.get('page')}页" if row.get("page") else str(row.get("source_url") or "")
        candidate = make_candidate(
            poem,
            claim_type,
            value,
            evidence_excerpt=excerpt,
            source_key=f"manual:{deterministic_id(citation, row.get('page'))[:20]}",
            source_name=str(row.get("source_title") or "人工录入学术资料"),
            source_url=str(row.get("source_url") or ""),
            citation=citation,
            source_locator=source_locator,
            source_grade=str(row.get("source_grade") or "B"),
            access_level=str(row.get("access_level") or "authenticated_manual"),
            license_note=str(row.get("license_note") or "仅保存题录、页码与必要短引"),
            match_score=0.95,
            extraction_method="manual_evidence_import_v1",
            status="needs_review",
        )
        candidate["review_note"] = str(row.get("notes") or "")
        candidates.append(candidate)
    return candidates


def import_manual_text(text: str) -> int:
    incoming = manual_candidates_from_csv(text)
    candidates = upsert_candidates(load_and_migrate_candidates(), incoming)
    mark_source_conflicts(candidates)
    write_jsonl(CANDIDATES_JSONL, candidates, backup=True)
    write_review_csv(REVIEW_EXPORT_CSV, candidates)
    return len(incoming)


def import_manual_command(args: argparse.Namespace) -> int:
    path = Path(args.input)
    count = import_manual_text(path.read_text(encoding="utf-8-sig"))
    print(f"Imported {count} manual evidence candidates")
    return 0


def candidate_fact_publishable(candidate: dict[str, Any], group: list[dict[str, Any]]) -> bool:
    if candidate.get("claim_type") not in FACT_CLAIM_TYPES:
        return True
    grade = str(candidate.get("source_grade") or "D")
    if grade in FACT_PUBLISHABLE:
        return True
    if grade != "C":
        return False
    source_keys = {
        str(row.get("source_key") or "")
        for row in group
        if row.get("claim_type") == candidate.get("claim_type")
        and row.get("status") == "approved"
        and row.get("source_grade") == "C"
        and compact_json(row.get("value")) == compact_json(candidate.get("value"))
    }
    return len(source_keys) >= 2


def grouped_approved_records(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    poems_by_hash = {str(poem.get("body_hash") or ""): poem for poem in load_poems()}
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for candidate in candidates:
        if candidate.get("status") != "approved":
            continue
        key = candidate.get("poem_key") if isinstance(candidate.get("poem_key"), dict) else {}
        digest = str(key.get("body_hash") or "")
        if digest in poems_by_hash:
            groups[digest].append(candidate)

    records: list[dict[str, Any]] = []
    for digest, rows in groups.items():
        poem = poems_by_hash[digest]
        publishable = [row for row in rows if candidate_fact_publishable(row, rows)]
        if not publishable:
            continue
        dates = [row for row in publishable if row.get("claim_type") == "composition_date"]
        places = [row for row in publishable if row.get("claim_type") == "composition_place"]
        contexts = [row for row in publishable if row.get("claim_type") in {"life_event", "historical_context"}]
        translations = [row for row in publishable if row.get("claim_type") == "translation"]
        annotations = [row for row in publishable if row.get("claim_type") == "annotation"]
        appreciations = [row for row in publishable if row.get("claim_type") == "appreciation"]

        date_values = {compact_json(row.get("value")) for row in dates}
        place_values = {compact_json(row.get("value")) for row in places}
        controversy: list[str] = []
        if len(date_values) > 1:
            controversy.append("不同来源对创作时间存在分歧")
        if len(place_values) > 1:
            controversy.append("不同来源对创作地点存在分歧")
        best_date = max(dates, key=lambda row: float(row.get("confidence") or 0), default=None)
        best_place = max(places, key=lambda row: float(row.get("confidence") or 0), default=None)

        line_notes: dict[int, dict[str, Any]] = {}
        for row in [*translations, *annotations]:
            value = value_dict(row.get("value"))
            line_no = _int_or_none(value.get("line_no")) or 0
            note = line_notes.setdefault(
                line_no,
                {
                    "line_no": line_no,
                    "original": str(value.get("original") or ""),
                    "translation": "",
                    "annotations": [],
                    "evidence_ids": [],
                },
            )
            if row.get("claim_type") == "translation":
                translation = str(value.get("translation") or value.get("text") or "").strip()
                if translation:
                    note["translation"] = translation
            else:
                annotation = str(value.get("annotation") or value.get("text") or "").strip()
                if annotation:
                    note["annotations"].append(annotation)
            note["evidence_ids"].append(row.get("candidate_id"))

        clean_line_notes = [
            note
            for note in sorted(line_notes.values(), key=lambda row: row["line_no"])
            if note["translation"] or note["annotations"]
        ]

        context_summaries: list[str] = []
        for row in contexts:
            value = value_dict(row.get("value"))
            summary = str(
                value.get("background_summary")
                or value.get("historical_context")
                or value.get("summary")
                or value.get("text")
                or ""
            ).strip()
            if summary and summary not in context_summaries:
                context_summaries.append(summary)
        background_summary = "；".join(context_summaries)[:220]
        story_options: list[tuple[str, dict[str, Any]]] = []
        for row in contexts:
            value = value_dict(row.get("value"))
            story = str(value.get("background_story") or value.get("background_summary") or "").strip()
            if 120 <= len(story) <= 220:
                story_options.append((story, row))
        story_summary, story_candidate = max(
            story_options,
            key=lambda item: float(item[1].get("confidence") or 0),
            default=("", {}),
        )

        appreciation_points: list[dict[str, Any]] = []
        for row in appreciations:
            value = value_dict(row.get("value"))
            point = str(
                value.get("appreciation")
                or value.get("point")
                or value.get("summary")
                or value.get("text")
                or ""
            ).strip()
            if not point:
                continue
            appreciation_points.append(
                {
                    "point": point,
                    "evidence_ids": [row.get("candidate_id")],
                }
            )

        sources: list[dict[str, Any]] = []
        seen_sources: set[tuple[str, str]] = set()
        for row in publishable:
            identity = (str(row.get("source_key") or ""), str(row.get("source_locator") or ""))
            if identity in seen_sources:
                continue
            seen_sources.add(identity)
            sources.append(
                {
                    "candidate_id": row.get("candidate_id"),
                    "source_key": row.get("source_key"),
                    "name": row.get("source_name"),
                    "url": row.get("source_url"),
                    "citation": row.get("citation"),
                    "locator": row.get("source_locator"),
                    "grade": row.get("source_grade"),
                    "access_level": row.get("access_level"),
                    "license_note": row.get("license_note"),
                    "excerpt": row.get("evidence_excerpt"),
                }
            )
        original_lines = [line for line in str(poem.get("body") or "").splitlines() if line.strip()]
        translated_lines = {note["line_no"] for note in clean_line_notes if note["line_no"] > 0 and note["translation"]}
        annotation_count = sum(len(note["annotations"]) for note in clean_line_notes)
        quality = {
            "background_story_120_220": bool(story_summary),
            "translation_lines": len(translated_lines),
            "original_lines": len(original_lines),
            "annotations": annotation_count,
            "appreciation_points": len(appreciation_points),
        }
        quality["rich_complete"] = bool(
            quality["background_story_120_220"]
            and quality["original_lines"]
            and quality["translation_lines"] >= quality["original_lines"]
            and quality["annotations"] >= 2
            and quality["appreciation_points"] >= 1
        )
        record = {
            "schema_version": "1.0",
            "poem_key": poem_key(poem),
            "composition": {
                "date": value_dict(best_date.get("value")) if best_date else {},
                "place": value_dict(best_place.get("value")) if best_place else {},
                "date_evidence_ids": [row.get("candidate_id") for row in dates],
                "place_evidence_ids": [row.get("candidate_id") for row in places],
            },
            "background_summary": background_summary,
            "historical_context": context_summaries,
            "story_summary": story_summary,
            "story_evidence_id": story_candidate.get("candidate_id") if story_candidate else "",
            "controversy_note": "；".join(controversy),
            "line_notes": clean_line_notes,
            "appreciation_points": appreciation_points,
            "sources": sources,
            "review_status": "approved",
            "publication_ready": quality["rich_complete"],
            "quality": quality,
            "reviewers": sorted({str(row.get("reviewer") or "") for row in publishable if row.get("reviewer")}),
            "reviewed_at": max((str(row.get("reviewed_at") or "") for row in publishable), default=""),
            "method": "approved_evidence_export_v1",
        }
        records.append(record)
    return sorted(records, key=lambda row: (row["poem_key"]["dynasty"], row["poem_key"]["poet"], row["poem_key"]["title"]))


def legacy_rows_from_rich(records: list[dict[str, Any]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for record in records:
        key = record["poem_key"]
        date = record.get("composition", {}).get("date") or {}
        place = record.get("composition", {}).get("place") or {}
        if not date and not place:
            continue
        sources = record.get("sources") or []
        composition_ids = set(record.get("composition", {}).get("date_evidence_ids") or [])
        composition_ids.update(record.get("composition", {}).get("place_evidence_ids") or [])
        composition_sources = [item for item in sources if item.get("candidate_id") in composition_ids]
        source = max(
            composition_sources or sources,
            key=lambda item: SOURCE_BASE.get(str(item.get("grade") or "D"), 0),
            default={},
        )
        rows.append(
            {
                "poet": str(key.get("poet") or ""),
                "title": str(key.get("title") or ""),
                "dynasty": str(key.get("dynasty") or ""),
                "year_start": str(date.get("year_start") or ""),
                "year_end": str(date.get("year_end") or date.get("year_start") or ""),
                "historical_place": str(place.get("historical_place") or ""),
                "modern_city": str(place.get("modern_place") or place.get("modern_city") or ""),
                "province": str(place.get("province") or ""),
                "lon": str(place.get("lon") or ""),
                "lat": str(place.get("lat") or ""),
                "source_name": str(source.get("name") or ""),
                "source_url": str(source.get("url") or ""),
                "source_note": str(source.get("excerpt") or record.get("background_summary") or ""),
                "fact_grade": str(source.get("grade") or "C"),
                "status": "approved",
            }
        )
    return rows


def write_legacy_csv(rows: list[dict[str, str]]) -> None:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=LEGACY_FIELDS)
    writer.writeheader()
    writer.writerows(rows)
    atomic_write_text(LEGACY_CONTEXTS_CSV, "\ufeff" + buffer.getvalue(), backup=True)


def export_command(_args: argparse.Namespace) -> int:
    candidates = load_and_migrate_candidates()
    if mark_source_conflicts(candidates, include_approved=True):
        write_jsonl(CANDIDATES_JSONL, candidates, backup=True)
    records = grouped_approved_records(candidates)
    write_jsonl(RICH_BACKGROUNDS_JSONL, records, backup=True)
    legacy_rows = legacy_rows_from_rich(records)
    write_legacy_csv(legacy_rows)
    write_review_csv(REVIEW_EXPORT_CSV, candidates)
    print(f"Rich backgrounds: {len(records)} -> {RICH_BACKGROUNDS_JSONL}")
    print(f"Legacy contexts: {len(legacy_rows)} -> {LEGACY_CONTEXTS_CSV}")
    return 0


def apply_review_update(payload: dict[str, Any]) -> dict[str, Any]:
    candidate_id = str(payload.get("candidate_id") or "")
    if not candidate_id:
        raise ValueError("candidate_id is required")
    candidates = load_and_migrate_candidates()
    target = next((row for row in candidates if row.get("candidate_id") == candidate_id), None)
    if not target:
        raise ValueError("candidate not found")
    status = str(payload.get("status") or target.get("status") or "needs_review")
    if status not in STATUSES:
        raise ValueError("invalid status")
    reviewer = str(payload.get("reviewer") or "").strip()
    if status == "approved" and not reviewer:
        raise ValueError("reviewer is required for approval")
    if "value" in payload:
        target["value"] = payload["value"]
    for field in (
        "evidence_excerpt",
        "source_name",
        "source_url",
        "citation",
        "source_grade",
        "source_locator",
        "access_level",
        "license_note",
        "review_note",
    ):
        if field in payload:
            target[field] = str(payload[field] or "").strip()
    target["source_grade"] = str(target.get("source_grade") or "D").upper()[:1]
    target["evidence_excerpt"] = normalize_excerpt(target.get("evidence_excerpt"))
    target["status"] = status
    target["reviewer"] = reviewer or str(target.get("reviewer") or "")
    if status in {"approved", "rejected", "disputed"}:
        target["reviewed_at"] = utc_now()
    target["confidence"] = confidence_for(
        str(target.get("source_grade") or "D"),
        float(target.get("match_score") or 0),
        conflict=status == "disputed",
    )
    mark_source_conflicts(candidates, include_approved=True)
    errors = validate_candidate(target)
    if errors:
        raise ValueError("; ".join(errors))
    write_jsonl(CANDIDATES_JSONL, candidates, backup=True)
    write_review_csv(REVIEW_EXPORT_CSV, candidates)
    return target


def import_review_csv(text: str) -> int:
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
    missing = set(REVIEW_FIELDS) - set(reader.fieldnames or ())
    if missing:
        raise ValueError(f"review CSV missing fields: {sorted(missing)}")
    candidates = load_and_migrate_candidates()
    by_id = {str(row.get("candidate_id") or ""): row for row in candidates}
    count = 0
    for line_no, row in enumerate(reader, start=2):
        candidate = by_id.get(str(row.get("candidate_id") or ""))
        if not candidate:
            raise ValueError(f"line {line_no}: candidate not found")
        source_key = str(row.get("source_key") or "").strip()
        if source_key and source_key != str(candidate.get("source_key") or ""):
            raise ValueError(f"line {line_no}: source_key is immutable")
        try:
            value = json.loads(row.get("value_json") or "null")
        except json.JSONDecodeError as exc:
            raise ValueError(f"line {line_no}: invalid value_json") from exc
        status = str(row.get("status") or candidate.get("status") or "needs_review")
        reviewer = str(row.get("reviewer") or "").strip()
        if status == "approved" and not reviewer:
            raise ValueError(f"line {line_no}: reviewer required for approval")
        candidate.update(
            value=value,
            evidence_excerpt=normalize_excerpt(row.get("evidence_excerpt")),
            source_name=str(row.get("source_name") or ""),
            source_url=str(row.get("source_url") or ""),
            citation=str(row.get("citation") or ""),
            source_grade=str(row.get("source_grade") or candidate.get("source_grade") or "D").upper()[:1],
            source_locator=str(row.get("source_locator") or ""),
            access_level=str(row.get("access_level") or ""),
            license_note=str(row.get("license_note") or ""),
            status=status,
            reviewer=reviewer,
            review_note=str(row.get("review_note") or ""),
            reviewed_at=str(row.get("reviewed_at") or (utc_now() if status in {"approved", "rejected", "disputed"} else "")),
        )
        count += 1
    mark_source_conflicts(candidates, include_approved=True)
    for candidate in candidates:
        errors = validate_candidate(candidate)
        if errors:
            raise ValueError(f"candidate {candidate.get('candidate_id')}: {'; '.join(errors)}")
    write_jsonl(CANDIDATES_JSONL, candidates, backup=True)
    write_review_csv(REVIEW_EXPORT_CSV, candidates)
    return count


REVIEW_HTML = r"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="icon" href="data:,">
<title>诗歌背景审核台</title><style>
:root{--bg:#f3f4f1;--panel:#fff;--ink:#202421;--muted:#6d746e;--line:#d7dcd6;--red:#b4473a;--jade:#28786e}
*{box-sizing:border-box}body{margin:0;color:var(--ink);font-family:"Microsoft YaHei",sans-serif;background:var(--bg)}
header{position:sticky;top:0;z-index:5;display:flex;align-items:center;justify-content:space-between;gap:16px;padding:14px 20px;background:#252a27;color:#fff}
h1{margin:0;font-size:19px}.tools{display:flex;gap:8px;flex-wrap:wrap}button,input,select,textarea{font:inherit}button{min-height:34px;padding:0 12px;border:1px solid #667069;border-radius:4px;background:#fff;color:#202421;cursor:pointer}
.shell{width:min(1480px,calc(100vw - 24px));margin:16px auto 40px}.filters{display:grid;grid-template-columns:1fr 160px 160px 160px;gap:8px;margin-bottom:12px}.filters input,.filters select{height:38px;padding:0 9px;border:1px solid var(--line);border-radius:4px;background:#fff}
.stats{margin-bottom:12px;color:var(--muted);font-size:12px}.card{display:grid;grid-template-columns:minmax(240px,.8fr) minmax(300px,1fr) minmax(340px,1.1fr);margin-bottom:12px;background:var(--panel);border:1px solid var(--line);border-radius:6px;overflow:hidden}.column{min-width:0;padding:16px;border-right:1px solid var(--line)}.column:last-child{border-right:0}.poem{white-space:pre-wrap;line-height:1.9;font-family:"STKaiti","KaiTi",serif;font-size:17px}.meta{color:var(--muted);font-size:11px;line-height:1.7}.excerpt{margin:12px 0;padding-left:10px;border-left:3px solid var(--red);line-height:1.65}.tag{display:inline-block;margin:0 5px 5px 0;padding:3px 6px;border-radius:3px;background:#edf1ed;font-size:10px}.tag.approved{color:#165e54;background:#dff1ed}.tag.disputed{color:#8d5312;background:#f7ead1}.field{display:grid;gap:5px;margin-bottom:9px}.field label{font-size:10px;color:var(--muted)}.field input,.field select,.field textarea{width:100%;padding:7px;border:1px solid var(--line);border-radius:4px}.field textarea{min-height:74px;resize:vertical}.field-grid{display:grid;grid-template-columns:1fr 1fr;gap:7px}.actions{display:flex;gap:7px;flex-wrap:wrap}.approve{background:var(--jade);color:white;border-color:var(--jade)}.reject{color:var(--red);border-color:#d5a19b}.message{position:fixed;right:20px;bottom:20px;padding:11px 14px;background:#252a27;color:#fff;border-radius:4px;display:none}
@media(max-width:900px){.filters{grid-template-columns:1fr 1fr}.card{grid-template-columns:1fr}.column{border-right:0;border-bottom:1px solid var(--line)}}
</style></head><body>
<header><h1>诗歌背景证据审核台</h1><div class="tools"><button id="exportBtn">导出审核CSV</button><button id="importBtn">导入审核CSV</button><button id="templateBtn">下载人工证据模板</button><button id="manualImportBtn">导入人工证据</button><input id="fileInput" type="file" accept=".csv" hidden><input id="manualFileInput" type="file" accept=".csv" hidden></div></header>
<main class="shell"><section class="filters"><input id="query" placeholder="诗人、诗题、来源或证据"><select id="status"><option value="">全部状态</option></select><select id="type"><option value="">全部类型</option></select><select id="grade"><option value="">全部等级</option></select></section><div class="stats" id="stats"></div><section id="cards"></section></main><div class="message" id="message"></div>
<script>
let payload={candidates:[],poems:{}};const $=id=>document.getElementById(id);const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function notify(text){const el=$('message');el.textContent=text;el.style.display='block';setTimeout(()=>el.style.display='none',1800)}
function fill(id,values){const el=$(id),selected=el.value,first=el.options[0]?.outerHTML||'<option value="">全部</option>';el.innerHTML=first+values.map(v=>`<option>${esc(v)}</option>`).join('');if([...el.options].some(o=>o.value===selected))el.value=selected}
function matches(c){const q=$('query').value.trim().toLowerCase(),k=c.poem_key||{};if($('status').value&&c.status!==$('status').value)return false;if($('type').value&&c.claim_type!==$('type').value)return false;if($('grade').value&&c.source_grade!==$('grade').value)return false;return !q||[k.poet,k.title,c.source_name,c.evidence_excerpt].some(v=>String(v||'').toLowerCase().includes(q))}
function card(c){
 const k=c.poem_key||{},poem=payload.poems[k.body_hash]||{},value=JSON.stringify(c.value,null,2),sourceUrl=/^https?:\/\//i.test(c.source_url||'')?c.source_url:'#';
 return `<article class="card" data-id="${c.candidate_id}"><div class="column"><h2>${esc(k.poet)}《${esc(k.title)}》</h2><div class="meta">${esc(k.dynasty)} · ${esc(c.claim_type)}</div><div class="poem">${esc(poem.body||'原诗未找到')}</div></div><div class="column"><div><span class="tag ${esc(c.status)}">${esc(c.status)}</span><span class="tag">${esc(c.source_grade)}级</span><span class="tag">置信度 ${esc(c.confidence)}</span></div><h3>${esc(c.source_name)}</h3><div class="meta">${esc(c.citation||'')}<br>${esc(c.source_locator||c.source_url||'')}</div><div class="excerpt">${esc(c.evidence_excerpt)}</div>${sourceUrl==='#'?'':`<a href="${esc(sourceUrl)}" target="_blank" rel="noreferrer">打开来源</a>`}</div><div class="column"><div class="field"><label>结构化值 JSON</label><textarea data-field="value">${esc(value)}</textarea></div><div class="field"><label>证据短引</label><textarea data-field="evidence_excerpt">${esc(c.evidence_excerpt)}</textarea></div><div class="field-grid"><div class="field"><label>来源名称</label><input data-field="source_name" value="${esc(c.source_name||'')}"></div><div class="field"><label>来源定位</label><input data-field="source_locator" value="${esc(c.source_locator||'')}"></div></div><div class="field"><label>题录</label><input data-field="citation" value="${esc(c.citation||'')}"></div><div class="field"><label>来源 URL</label><input data-field="source_url" value="${esc(c.source_url||'')}"></div><div class="field-grid"><div class="field"><label>访问方式</label><input data-field="access_level" value="${esc(c.access_level||'')}"></div><div class="field"><label>许可说明</label><input data-field="license_note" value="${esc(c.license_note||'')}"></div></div><div class="field"><label>来源等级 / 状态</label><div class="field-grid"><select data-field="source_grade">${['A','B','C','D'].map(v=>`<option ${v===c.source_grade?'selected':''}>${v}</option>`).join('')}</select><select data-field="status">${['collected','extracted','needs_review','approved','rejected','disputed','insufficient'].map(v=>`<option ${v===c.status?'selected':''}>${v}</option>`).join('')}</select></div></div><div class="field"><label>审核人</label><input data-field="reviewer" value="${esc(c.reviewer||'')}"></div><div class="field"><label>审核说明</label><input data-field="review_note" value="${esc(c.review_note||'')}"></div><div class="actions"><button class="approve" onclick="save('${c.candidate_id}','approved')">批准</button><button onclick="save('${c.candidate_id}','disputed')">标记争议</button><button class="reject" onclick="save('${c.candidate_id}','rejected')">驳回</button><button onclick="save('${c.candidate_id}',null)">保存编辑</button></div></div></article>`
}
function render(){const rows=payload.candidates.filter(matches);$('stats').textContent=`显示 ${rows.length} / ${payload.candidates.length} 条候选`;$('cards').innerHTML=rows.slice(0,250).map(card).join('')||'<p>暂无候选</p>'}
async function save(id,status){const card=document.querySelector(`[data-id="${id}"]`);let value;try{value=JSON.parse(card.querySelector('[data-field="value"]').value)}catch(e){notify('结构化值不是合法JSON');return}const field=name=>card.querySelector(`[data-field="${name}"]`).value;const body={candidate_id:id,value,evidence_excerpt:field('evidence_excerpt'),source_name:field('source_name'),source_url:field('source_url'),citation:field('citation'),source_locator:field('source_locator'),access_level:field('access_level'),license_note:field('license_note'),source_grade:field('source_grade'),status:status||field('status'),reviewer:field('reviewer'),review_note:field('review_note')};const r=await fetch('/api/decision',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const out=await r.json();if(!r.ok){notify(out.error||'保存失败');return}await load();notify(out.candidate.status==='disputed'?'检测到来源冲突，已标记争议':'已保存')}
async function load(){const r=await fetch('/api/data');payload=await r.json();fill('status',[...new Set(payload.candidates.map(x=>x.status))].sort());fill('type',[...new Set(payload.candidates.map(x=>x.claim_type))].sort());fill('grade',['A','B','C','D']);render()}
async function uploadCsv(input,endpoint){const f=$(input).files[0];if(!f)return;const r=await fetch(endpoint,{method:'POST',headers:{'Content-Type':'text/csv;charset=utf-8'},body:await f.text()});const out=await r.json();if(!r.ok){notify(out.error||'导入失败');return}await load();notify(`已导入 ${out.count} 行`)}
['query','status','type','grade'].forEach(id=>$(id).addEventListener(id==='query'?'input':'change',render));$('exportBtn').onclick=()=>location.href='/api/export.csv';$('importBtn').onclick=()=>$('fileInput').click();$('templateBtn').onclick=()=>location.href='/api/manual-template.csv';$('manualImportBtn').onclick=()=>$('manualFileInput').click();$('fileInput').onchange=()=>uploadCsv('fileInput','/api/import.csv');$('manualFileInput').onchange=()=>uploadCsv('manualFileInput','/api/import-manual.csv');load();
</script></body></html>"""


class ReviewHandler(BaseHTTPRequestHandler):
    server_version = "ShixingBackgroundReview/1.0"

    def log_message(self, format: str, *args: object) -> None:
        print(f"[review] {self.address_string()} {format % args}")

    def _json(self, payload: object, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _text(self, text: str, content_type: str, status: int = 200) -> None:
        body = text.encode("utf-8-sig" if "csv" in content_type else "utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._text(REVIEW_HTML, "text/html; charset=utf-8")
            return
        if parsed.path == "/api/data":
            candidates = load_and_migrate_candidates()
            poems = {
                str(poem.get("body_hash") or ""): {
                    "poet": poem.get("poet"),
                    "title": poem.get("title"),
                    "body": poem.get("body"),
                }
                for poem in load_poems()
            }
            self._json({"candidates": candidates, "poems": poems})
            return
        if parsed.path == "/api/export.csv":
            candidates = load_and_migrate_candidates()
            buffer = io.StringIO()
            writer = csv.DictWriter(buffer, fieldnames=REVIEW_FIELDS)
            writer.writeheader()
            from background_contract import review_csv_rows

            writer.writerows(review_csv_rows(candidates))
            self._text(buffer.getvalue(), "text/csv; charset=utf-8")
            return
        if parsed.path == "/api/manual-template.csv":
            ensure_manual_template()
            self._text(
                MANUAL_TEMPLATE_CSV.read_text(encoding="utf-8-sig"),
                "text/csv; charset=utf-8",
            )
            return
        self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length)
        try:
            if self.path == "/api/decision":
                payload = json.loads(body.decode("utf-8"))
                result = apply_review_update(payload)
                self._json({"ok": True, "candidate": result})
                return
            if self.path == "/api/import.csv":
                count = import_review_csv(body.decode("utf-8-sig"))
                self._json({"ok": True, "count": count})
                return
            if self.path == "/api/import-manual.csv":
                count = import_manual_text(body.decode("utf-8-sig"))
                self._json({"ok": True, "count": count})
                return
            self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
        except (ValueError, json.JSONDecodeError) as exc:
            self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)


def review_command(args: argparse.Namespace) -> int:
    load_and_migrate_candidates()
    write_review_csv(REVIEW_EXPORT_CSV, read_jsonl(CANDIDATES_JSONL))
    server = ThreadingHTTPServer(("127.0.0.1", args.port), ReviewHandler)
    print(f"Review console: http://127.0.0.1:{args.port}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nReview console stopped")
    finally:
        server.server_close()
    return 0


def check_command(_args: argparse.Namespace) -> int:
    return subprocess.run(
        [sys.executable, str(ROOT / "tools" / "check_background_pipeline.py")],
        cwd=ROOT,
        check=False,
    ).returncode


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    collect = sub.add_parser("collect", help="collect public-source candidates")
    collect.add_argument("--scope", choices=("core", "all"), default="core")
    collect.add_argument("--max-poems-per-poet", type=int)
    collect.add_argument("--sources", default=",".join(DEFAULT_SOURCES))
    collect.add_argument("--resume", action="store_true")
    collect.add_argument("--offline", action="store_true")
    collect.add_argument("--timeout", type=float, default=20.0)
    collect.add_argument("--retries", type=int, default=3, help="每个HTTP请求最多尝试次数；0仍至少尝试1次")
    collect.add_argument("--min-delay", type=float, default=1.5)
    collect.add_argument("--max-delay", type=float, default=3.0)
    collect.set_defaults(func=collect_command)

    extract = sub.add_parser("extract", help="extract structured candidates with an LLM")
    extract.add_argument("--scope", choices=("core", "all"), default="core")
    extract.add_argument("--max-poems-per-poet", type=int)
    extract.add_argument("--limit", type=int)
    extract.add_argument("--llm", action="store_true")
    extract.set_defaults(func=extract_command)

    review = sub.add_parser("review", help="start local review console")
    review.add_argument("--port", type=int, default=8140)
    review.set_defaults(func=review_command)

    manual = sub.add_parser("import-manual", help="import authenticated/manual evidence CSV")
    manual.add_argument("--input", required=True)
    manual.set_defaults(func=import_manual_command)

    export = sub.add_parser("export", help="publish approved records and legacy CSV")
    export.set_defaults(func=export_command)

    check = sub.add_parser("check", help="run offline data-contract checks")
    check.set_defaults(func=check_command)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if getattr(args, "max_poems_per_poet", None) is not None and args.max_poems_per_poet <= 0:
        raise SystemExit("--max-poems-per-poet must be positive")
    if getattr(args, "port", 8140) not in range(1, 65536):
        raise SystemExit("--port must be between 1 and 65535")
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
