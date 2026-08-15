"""Shared contracts and deterministic helpers for poem-background evidence."""
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
CANDIDATE_DIR = DATA_DIR / "candidates"
REVIEWED_DIR = DATA_DIR / "reviewed"
CACHE_DIR = ROOT / ".cache" / "background_sources"

POEMS_JSON = DATA_DIR / "poems.json"
CANDIDATES_JSONL = CANDIDATE_DIR / "poem_background_candidates.jsonl"
COLLECTION_STATUS_JSONL = CANDIDATE_DIR / "background_collection_status.jsonl"
POET_STATUS_JSONL = CANDIDATE_DIR / "poet_identity_status.jsonl"
POET_SOURCE_REGISTRY_JSON = CANDIDATE_DIR / "poet_source_registry.json"
MANUAL_TEMPLATE_CSV = CANDIDATE_DIR / "manual_background_evidence.csv"
REVIEW_EXPORT_CSV = CANDIDATE_DIR / "background_review.csv"
RICH_BACKGROUNDS_JSONL = REVIEWED_DIR / "verified_poem_backgrounds.jsonl"
LEGACY_CONTEXTS_CSV = REVIEWED_DIR / "verified_poem_contexts.csv"

CORE_POETS = ("李白", "杜甫", "白居易", "苏轼", "陆游", "李清照")
DYNASTY_API_NAMES = {"唐": "Tang", "宋": "Song", "Tang": "Tang", "Song": "Song"}

CLAIM_TYPES = {
    "composition_date",
    "composition_place",
    "life_event",
    "historical_context",
    "annotation",
    "translation",
    "appreciation",
}
FACT_CLAIM_TYPES = {
    "composition_date",
    "composition_place",
    "life_event",
    "historical_context",
}
STATUSES = {
    "collected",
    "extracted",
    "needs_review",
    "approved",
    "rejected",
    "disputed",
    "insufficient",
}
SOURCE_BASE = {"A": 0.95, "B": 0.85, "C": 0.65, "D": 0.35}
MAX_EVIDENCE_CHARS = 160
PROMPT_VERSION = "background-evidence-v1"

MANUAL_FIELDS = (
    "poet",
    "title",
    "dynasty",
    "claim_type",
    "value_json",
    "evidence_excerpt",
    "source_title",
    "source_author",
    "publisher",
    "publication_year",
    "edition",
    "page",
    "source_url",
    "source_grade",
    "access_level",
    "license_note",
    "notes",
    "status",
)

REVIEW_FIELDS = (
    "candidate_id",
    "poet",
    "title",
    "dynasty",
    "claim_type",
    "value_json",
    "evidence_excerpt",
    "source_key",
    "source_name",
    "source_url",
    "citation",
    "source_locator",
    "source_grade",
    "access_level",
    "license_note",
    "match_score",
    "confidence",
    "extraction_method",
    "model_id",
    "prompt_version",
    "status",
    "reviewer",
    "review_note",
    "reviewed_at",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def clamp(value: float, low: float = 0.0, high: float = 0.99) -> float:
    return max(low, min(high, value))


def confidence_for(
    source_grade: str,
    match_score: float,
    *,
    agreeing_sources: int = 1,
    conflict: bool = False,
) -> float:
    grade = str(source_grade or "D").upper()[:1]
    base = SOURCE_BASE.get(grade, SOURCE_BASE["D"])
    agreement_bonus = 0.05 if agreeing_sources >= 2 else 0.0
    conflict_penalty = 0.20 if conflict else 0.0
    return round(clamp(base * float(match_score) + agreement_bonus - conflict_penalty), 3)


def normalize_title(value: object) -> str:
    text = str(value or "").strip().replace("．", "·").replace("・", "·")
    text = re.sub(r"[\s《》〈〉\[\]【】（）()·，,。.!！?？:：;；'\"“”‘’]", "", text)
    text = re.sub(r"(?:其|之)([一二三四五六七八九十\d]+)$", r"\1", text)
    return text.casefold()


def first_line(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    line = re.split(r"[。！？!?\n]", text, maxsplit=1)[0]
    return re.sub(r"\s+", "", line)


def source_match_score(
    poem: dict[str, Any],
    *,
    source_poem_id: object = "",
    source_poet: object = "",
    source_title: object = "",
    source_first_line: object = "",
) -> float:
    expected_id = str(poem.get("source_poem_id") or "").strip()
    actual_id = str(source_poem_id or "").strip()
    expected_poet = str(poem.get("poet") or poem.get("author") or "").strip()
    actual_poet = str(source_poet or "").strip()
    expected_title = normalize_title(poem.get("title"))
    actual_title = normalize_title(source_title)
    expected_first = first_line(poem.get("body"))
    actual_first = first_line(source_first_line)

    if (
        expected_id
        and actual_id
        and expected_id == actual_id
        and expected_poet
        and expected_poet == actual_poet
    ):
        return 1.0
    if expected_poet == actual_poet and expected_title and expected_title == actual_title:
        return 0.95
    if (
        expected_poet == actual_poet
        and expected_title
        and actual_title
        and (expected_title in actual_title or actual_title in expected_title)
        and expected_first
        and expected_first == actual_first
    ):
        return 0.90
    return 0.0


def poem_body_hash(poem: dict[str, Any]) -> str:
    digest = str(poem.get("body_hash") or "").strip()
    if digest:
        return digest
    return hashlib.sha256(str(poem.get("body") or "").encode("utf-8")).hexdigest()


def poem_key(poem: dict[str, Any]) -> dict[str, str]:
    return {
        "poet": str(poem.get("poet") or poem.get("author") or "").strip(),
        "title": str(poem.get("title") or "").strip(),
        "dynasty": str(poem.get("dynasty") or "").strip(),
        "body_hash": poem_body_hash(poem),
    }


def compact_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def deterministic_id(*parts: object) -> str:
    raw = "\x1f".join(compact_json(part) if isinstance(part, (dict, list)) else str(part or "") for part in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def normalize_excerpt(value: object, limit: int = MAX_EVIDENCE_CHARS) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit]


def make_candidate(
    poem: dict[str, Any],
    claim_type: str,
    value: object,
    *,
    evidence_excerpt: str,
    source_key: str,
    source_name: str,
    source_url: str = "",
    citation: str = "",
    source_locator: str = "",
    source_grade: str = "C",
    access_level: str = "public_web",
    license_note: str = "",
    match_score: float = 0.95,
    extraction_method: str = "parser",
    model_id: str = "",
    prompt_version: str = "",
    status: str = "needs_review",
    raw_cache_key: str = "",
    collected_at: str | None = None,
) -> dict[str, Any]:
    if claim_type not in CLAIM_TYPES:
        raise ValueError(f"unsupported claim_type: {claim_type}")
    if status not in STATUSES:
        raise ValueError(f"unsupported status: {status}")
    grade = str(source_grade or "D").upper()[:1]
    if grade not in SOURCE_BASE:
        raise ValueError(f"unsupported source_grade: {grade}")
    key = poem_key(poem)
    excerpt = normalize_excerpt(evidence_excerpt)
    candidate_id = deterministic_id(key, claim_type, value, source_key, source_locator, excerpt)
    return {
        "candidate_id": candidate_id,
        "poem_key": key,
        "claim_type": claim_type,
        "value": value,
        "evidence_excerpt": excerpt,
        "source_key": source_key,
        "source_name": str(source_name or "").strip(),
        "source_url": str(source_url or "").strip(),
        "citation": str(citation or "").strip(),
        "source_locator": str(source_locator or "").strip(),
        "source_grade": grade,
        "access_level": str(access_level or "public_web").strip(),
        "license_note": str(license_note or "").strip(),
        "match_score": round(float(match_score), 3),
        "confidence": confidence_for(grade, match_score),
        "extraction_method": extraction_method,
        "model_id": model_id,
        "prompt_version": prompt_version,
        "status": status,
        "raw_cache_key": raw_cache_key,
        "collected_at": collected_at or utc_now(),
        "reviewer": "",
        "review_note": "",
        "reviewed_at": "",
    }


def load_poems() -> list[dict[str, Any]]:
    rows = json.loads(POEMS_JSON.read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise ValueError("poems.json top-level value must be a list")
    result: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        item = dict(row)
        item["poet"] = str(item.get("poet") or item.get("author") or "").strip()
        item["body_hash"] = poem_body_hash(item)
        result.append(item)
    return result


def corpus_poet_profiles() -> list[dict[str, Any]]:
    """Return every corpus poet once, in stable first-appearance order.

    ``dynasty`` is normalized to the ASCII values accepted by Sou-yun's query
    parameter.  The original corpus label is retained as ``dynasty_label``.
    A few corpus rows carry cross-period or homonym labels.  The primary query
    dynasty is therefore the most frequent corpus label (ties use first
    appearance), while every observed variant and count remains explicit.
    """
    order: list[str] = []
    counts: dict[str, dict[str, int]] = {}
    label_order: dict[str, list[str]] = {}
    for poem in load_poems():
        poet = str(poem.get("poet") or "").strip()
        dynasty_label = str(poem.get("dynasty") or "").strip()
        if not poet:
            continue
        dynasty = DYNASTY_API_NAMES.get(dynasty_label)
        if dynasty is None:
            raise ValueError(f"unsupported dynasty for {poet}: {dynasty_label!r}")
        if poet not in counts:
            order.append(poet)
            counts[poet] = {}
            label_order[poet] = []
        counts[poet][dynasty] = counts[poet].get(dynasty, 0) + 1
        if dynasty not in label_order[poet]:
            label_order[poet].append(dynasty)
    profiles: list[dict[str, Any]] = []
    reverse_label = {"Tang": "唐", "Song": "宋"}
    for poet in order:
        variants = sorted(
            counts[poet],
            key=lambda dynasty: (-counts[poet][dynasty], label_order[poet].index(dynasty)),
        )
        dynasty = variants[0]
        profiles.append(
            {
                "poet": poet,
                "dynasty": dynasty,
                "dynasty_label": reverse_label[dynasty],
                "dynasty_variants": variants,
                "dynasty_counts": {key: counts[poet][key] for key in variants},
            }
        )
    return profiles


def corpus_poets() -> list[str]:
    """Stable corpus-wide poet list (currently 88 names)."""
    return [profile["poet"] for profile in corpus_poet_profiles()]


def resolve_poets(scope: str = "core", explicit: Iterable[str] | None = None) -> list[str]:
    """Resolve a CLI poet selection, with an explicit list taking precedence."""
    if scope not in {"core", "all"}:
        raise ValueError("scope must be core or all")
    available = corpus_poets()
    allowed = set(available)
    if explicit is not None:
        selected: list[str] = []
        seen: set[str] = set()
        for raw in explicit:
            poet = str(raw or "").strip()
            if poet and poet not in seen:
                selected.append(poet)
                seen.add(poet)
        unknown = [poet for poet in selected if poet not in allowed]
        if unknown:
            raise ValueError(f"unknown poet(s): {', '.join(unknown)}")
        if not selected:
            raise ValueError("explicit poet list is empty")
        return selected
    return list(CORE_POETS) if scope == "core" else available


def select_poems(scope: str, max_poems_per_poet: int | None = None) -> list[dict[str, Any]]:
    rows = load_poems()
    if scope not in {"core", "all"}:
        raise ValueError("scope must be core or all")
    allowed = set(CORE_POETS) if scope == "core" else None
    counts: dict[str, int] = {}
    selected: list[dict[str, Any]] = []
    for row in rows:
        poet = str(row.get("poet") or "")
        if allowed is not None and poet not in allowed:
            continue
        if max_poems_per_poet is not None and counts.get(poet, 0) >= max_poems_per_poet:
            continue
        counts[poet] = counts.get(poet, 0) + 1
        selected.append(row)
    return selected


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSONL at {path}:{line_no}: {exc}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"JSONL row must be an object at {path}:{line_no}")
        rows.append(value)
    return rows


def atomic_write_text(path: Path, text: str, *, backup: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if backup and path.exists():
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = path.with_name(f"{path.stem}.{stamp}{path.suffix}.bak")
        shutil.copy2(path, backup_path)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(text, encoding="utf-8")
    os.replace(temp, path)


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]], *, backup: bool = False) -> None:
    payload = "".join(compact_json(row) + "\n" for row in rows)
    atomic_write_text(path, payload, backup=backup)


def upsert_candidates(
    existing: Iterable[dict[str, Any]],
    incoming: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for row in [*existing, *incoming]:
        candidate_id = str(row.get("candidate_id") or "")
        if not candidate_id:
            continue
        if candidate_id not in merged:
            order.append(candidate_id)
            merged[candidate_id] = dict(row)
            continue
        previous = merged[candidate_id]
        # A repeated collection may fill newly-added adapter fields, but it must
        # never overwrite a reviewer edit or move an existing record backwards.
        merged[candidate_id] = {**row, **previous}
    return [merged[candidate_id] for candidate_id in order]


def candidate_poem_identity(row: dict[str, Any]) -> tuple[str, str, str]:
    key = row.get("poem_key") if isinstance(row.get("poem_key"), dict) else {}
    return (
        str(key.get("poet") or "").strip(),
        str(key.get("title") or "").strip(),
        str(key.get("dynasty") or "").strip(),
    )


def validate_candidate(row: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    candidate_id = str(row.get("candidate_id") or "")
    if len(candidate_id) != 64:
        errors.append("candidate_id must be a SHA-256 hex string")
    if row.get("claim_type") not in CLAIM_TYPES:
        errors.append("invalid claim_type")
    if row.get("status") not in STATUSES:
        errors.append("invalid status")
    if str(row.get("source_grade") or "") not in SOURCE_BASE:
        errors.append("invalid source_grade")
    if len(str(row.get("evidence_excerpt") or "")) > MAX_EVIDENCE_CHARS:
        errors.append("evidence excerpt exceeds limit")
    if not isinstance(row.get("poem_key"), dict):
        errors.append("missing poem_key")
    else:
        for key in ("poet", "title", "dynasty", "body_hash"):
            if not str(row["poem_key"].get(key) or ""):
                errors.append(f"missing poem_key.{key}")
    if row.get("status") == "approved":
        if not str(row.get("reviewer") or "") or not str(row.get("reviewed_at") or ""):
            errors.append("approved candidate lacks reviewer metadata")
        if not str(row.get("source_name") or ""):
            errors.append("approved candidate lacks source")
        if not str(row.get("evidence_excerpt") or ""):
            errors.append("approved candidate lacks evidence excerpt")
        if not str(row.get("source_locator") or row.get("source_url") or ""):
            errors.append("approved candidate lacks source locator")
    return errors


def review_csv_rows(candidates: Iterable[dict[str, Any]]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for candidate in candidates:
        poet, title, dynasty = candidate_poem_identity(candidate)
        result.append(
            {
                "candidate_id": str(candidate.get("candidate_id") or ""),
                "poet": poet,
                "title": title,
                "dynasty": dynasty,
                "claim_type": str(candidate.get("claim_type") or ""),
                "value_json": compact_json(candidate.get("value")),
                "evidence_excerpt": str(candidate.get("evidence_excerpt") or ""),
                "source_key": str(candidate.get("source_key") or ""),
                "source_name": str(candidate.get("source_name") or ""),
                "source_url": str(candidate.get("source_url") or ""),
                "citation": str(candidate.get("citation") or ""),
                "source_locator": str(candidate.get("source_locator") or ""),
                "source_grade": str(candidate.get("source_grade") or ""),
                "access_level": str(candidate.get("access_level") or ""),
                "license_note": str(candidate.get("license_note") or ""),
                "match_score": str(candidate.get("match_score") or ""),
                "confidence": str(candidate.get("confidence") or ""),
                "extraction_method": str(candidate.get("extraction_method") or ""),
                "model_id": str(candidate.get("model_id") or ""),
                "prompt_version": str(candidate.get("prompt_version") or ""),
                "status": str(candidate.get("status") or ""),
                "reviewer": str(candidate.get("reviewer") or ""),
                "review_note": str(candidate.get("review_note") or ""),
                "reviewed_at": str(candidate.get("reviewed_at") or ""),
            }
        )
    return result


def write_review_csv(path: Path, candidates: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    with temp.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REVIEW_FIELDS)
        writer.writeheader()
        writer.writerows(review_csv_rows(candidates))
    os.replace(temp, path)


def ensure_manual_template() -> None:
    if MANUAL_TEMPLATE_CSV.exists():
        return
    MANUAL_TEMPLATE_CSV.parent.mkdir(parents=True, exist_ok=True)
    with MANUAL_TEMPLATE_CSV.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=MANUAL_FIELDS)
        writer.writeheader()
