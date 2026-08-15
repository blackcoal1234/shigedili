"""Independent, re-runnable, candidate-first journey-source collector.

Sources (all read-only, all optional, none fatal to a batch):
  * CBDB person API  -> person_event candidates (residence / posting)
  * Sou-yun official open/Poem API -> work_chronology candidates
    (the older HTML author index remains fixture/diagnostic compatibility only)
  * CNKGraph Biography API -> person_event + work_chronology candidates (experimental)

Network responses are stored in a content-addressed cache under
``.cache/journey_sources`` (polite: robots.txt, 1.5-3.0s default delay,
bounded retries, resumable).  Outputs under ``data/candidates/`` are written
idempotently and atomically; candidate ids are deterministic, and an existing
reviewer decision is never overwritten.

Reviewed data (data/reviewed/) is only ever read, never rewritten.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import threading
from collections import Counter
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, quote, urlparse

from bs4 import BeautifulSoup, FeatureNotFound, Tag

from background_adapters import FetchResult, HttpCacheClient, SharedHostGate
from background_contract import (
    CANDIDATE_DIR,
    CORE_POETS,
    REVIEWED_DIR,
    ROOT,
    atomic_write_text,
    corpus_poet_profiles,
    deterministic_id,
    load_poems,
    normalize_excerpt,
    normalize_title,
    poem_body_hash,
    read_jsonl,
    resolve_poets,
    utc_now,
    write_jsonl,
)
from poet_source_registry import (
    AUDITED_CBDB_PERSON_IDS,
    AUDITED_SOUYUN_AUTHOR_IDS,
    CNKGRAPH_SOURCE_METADATA,
    _SOUYUN_FRESH_IDENTITY_BLOCKERS,
    load_source_registry,
    merge_souyun_discoveries,
    registry_by_poet,
    write_source_registry,
)

JOURNEY_CACHE_DIR = ROOT / ".cache" / "journey_sources"

EVENT_CANDIDATES_JSONL = CANDIDATE_DIR / "journey_event_candidates.jsonl"
WORK_SUPPLEMENTS_JSONL = CANDIDATE_DIR / "work_chronology_supplements.jsonl"
SOURCE_STATUS_JSONL = CANDIDATE_DIR / "journey_source_status.jsonl"
COVERAGE_JSON = CANDIDATE_DIR / "journey_source_coverage.json"
REVIEWED_JOURNEYS = REVIEWED_DIR / "poet_journeys.json"

SOURCES = ("cbdb", "souyun", "cnkgraph")
COVERAGE_SCHEMA_VERSION = 4

CBDB_API = "https://cbdb.fas.harvard.edu/cbdbapi/person"
# Verified CBDB person IDs (BasicInfo.PersonId); querying by fixed id avoids the
# name-query "first match only" ambiguity.  Identity is still cross-checked below.
CBDB_PERSON_IDS = AUDITED_CBDB_PERSON_IDS
SOUYUN_AUTHOR_IDS = AUDITED_SOUYUN_AUTHOR_IDS
CNKGRAPH_BIOGRAPHY_API = "https://open.cnkgraph.com/api/Biography"
CNKGRAPH_WRITING_STAT_API = "https://open.cnkgraph.com/api/Biography/WritingStat"
# The 2026-08-09 probe contains authors with more than 200 pages (刘克庄 242),
# so the original suggested guard of 100 would truncate known-good coverage.
# 500 is still a finite runaway guard while covering the current 88-poet snapshot.
SOUYUN_AUTO_PAGE_LIMIT = 500
SOUYUN_POEM_API = "https://api.sou-yun.cn/open/Poem"

SLUGS = {
    "李白": "libai",
    "杜甫": "dufu",
    "白居易": "baijuyi",
    "苏轼": "sushi",
    "陆游": "luyou",
    "李清照": "liqingzhao",
}

REVIEWER_FIELDS = ("status", "reviewer", "review_note", "reviewed_at")
SUCCESS_STATUSES = {"ok", "collected", "empty", "no_usable_records"}
# Statuses that mean "this (poet, source) scope was collected completely".  Only
# these scopes are eligible for --refresh-successful-scopes stale clearing.
REFRESH_SUCCESS_STATUSES = {"collected", "ok", "empty", "no_usable_records"}

_YEAR_KEYS = ("Year", "year", "系年", "年份")
_PLACE_KEYS = ("Place", "Province", "City", "OldProvince", "OldSubProvince", "地点", "地址", "place", "placeName", "location")
_TITLE_KEYS = ("Title", "Subject", "标题", "题目", "title")

_YEAR_RE = re.compile(r"\d{3,4}")
_QUERY_ID_RE = re.compile(r"[?&]id=(\d+)")
_PAREN_RE = re.compile(r"（([^（）]*)）")
_MONTH_TOKEN_RE = re.compile(r"(正月|[一二三四五六七八九十\d]+月|春|夏|秋|冬|上旬|中旬|下旬)")
_SOUYUN_AUTHOR_RE = re.compile(r"\s·\s*([^\s]+)")
_SOUYUN_FOOTNOTE_RE = re.compile(r"[\u2460-\u24ff\u00b9\u00b2\u00b3\u2070-\u209f]")
_SOUYUN_TITLE_PAREN_RE = re.compile(r"（([^（）]*)）|\(([^()]*)\)")
_SOUYUN_GROUP_NOTE_RE = re.compile(r"(?:其)?[一二三四五六七八九十百千\d]+")


def _soup(html: str) -> BeautifulSoup:
    try:
        return BeautifulSoup(html, "lxml")
    except FeatureNotFound:
        return BeautifulSoup(html, "html.parser")


def _plain_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        for key in ("Content", "Value", "Name", "Text", "@value"):
            if key in value and value[key] is not None:
                return str(value[key]).strip()
        return ""
    return str(value).strip()


def _as_list(value: object) -> list[object]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _attr(obj: object, name: str) -> object:
    if not isinstance(obj, dict):
        return None
    candidates = (f"@{name}", name, f"{name[:1].upper()}{name[1:]}")
    for key in candidates:
        if key in obj and obj[key] is not None:
            return obj[key]
    return None


def parse_positive_year(value: object) -> int | None:
    """Return a positive year from CBDB-style strings, or None when unusable.

    ``0`` years (native-place records that are not travel events) are rejected.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    text = str(value).strip()
    if not text:
        return None
    if isinstance(value, (int, float)):
        num = int(value)
    else:
        match = _YEAR_RE.search(text)
        if not match:
            return None
        num = int(match.group(0))
    if num <= 0 or num > 3000:
        return None
    return num


# --------------------------------------------------------------------------- #
# CBDB person API
# --------------------------------------------------------------------------- #

def extract_cbdb_person(payload: object) -> dict[str, object] | None:
    """Unwrap Package.PersonAuthority.PersonInfo.Person defensively."""
    if not isinstance(payload, dict):
        return None
    package = payload.get("Package")
    if not isinstance(package, dict):
        package = payload
    pa = package.get("PersonAuthority")
    if not isinstance(pa, dict):
        pa = package.get("PersonInfo") or package.get("Person")
    pi = pa.get("PersonInfo") if isinstance(pa, dict) else None
    person = None
    if isinstance(pi, dict):
        person = pi.get("Person")
    if not isinstance(person, dict) and isinstance(pa, dict):
        person = pa.get("Person")
    if not isinstance(person, dict) and isinstance(package, dict):
        person = package.get("Person")
    if not isinstance(person, dict):
        return None
    person_id = _plain_text(_attr(person, "id"))
    if not person_id:
        person_id = _plain_text(_attr(person, "c_personid"))
    basic = person.get("BasicInfo")
    if not isinstance(basic, dict):
        basic = {}
    if not person_id:
        person_id = _plain_text(basic.get("PersonId"))
    name = _plain_text(_attr(person, "Name"))
    if not name:
        name = _plain_text(basic.get("ChName"))
    addresses = _cbdb_addresses(person)
    postings = _cbdb_postings(person)
    return {
        "person_id": person_id,
        "name": name,
        "index_year": _plain_text(basic.get("IndexYear")),
        "addresses": addresses,
        "postings": postings,
    }


def _cbdb_addresses(person: dict[str, object]) -> list[dict[str, object]]:
    holder = person.get("PersonAddresses")
    if not isinstance(holder, dict):
        return []
    return [item for item in _as_list(holder.get("Address")) if isinstance(item, dict)]


def _cbdb_postings(person: dict[str, object]) -> list[dict[str, object]]:
    holder = person.get("PersonPostings")
    if not isinstance(holder, dict):
        return []
    return [item for item in _as_list(holder.get("Posting")) if isinstance(item, dict)]


def _cbdb_common(
    poet: str,
    person_id: str,
    addr_id: str,
    event_type: str,
    start: int,
    end: int,
    place: str,
    pages: str,
    note: str,
    grade: str,
    cache_key: str,
    source_url: str,
    extra: dict[str, object] | None = None,
    id_parts: tuple[object, ...] = (),
) -> dict[str, object]:
    precision = "exact" if start == end else "approximate"
    # id_parts (e.g. office / posting id) keep same-year-same-place but distinct
    # postings as separate candidates instead of colliding into one.
    candidate_id = deterministic_id(poet, "cbdb", event_type, person_id, addr_id, start, end, place, *id_parts)
    row: dict[str, object] = {
        "candidate_id": candidate_id,
        "poet": poet,
        "event_type": event_type,
        "source": "cbdb",
        "year_start": start,
        "year_end": end,
        "year_precision": precision,
        "historical_place": place,
        "source_name": "中国历代人物传记资料库（CBDB）人物API",
        "source_pages": pages,
        "source_note": note,
        "source_url": source_url,
        "cbdb_person_id": person_id,
        "cbdb_addr_id": addr_id,
        "source_grade": grade,
        "access_level": "open_api",
        "license": "CC BY-NC-SA 4.0",
        "license_note": "CBDB 数据以 CC BY-NC-SA 4.0 发布；仅保存结构化字段与必要短引",
        "status": "needs_review",
        "raw_cache_key": cache_key,
        "extraction_method": "cbdb_person_api_v1",
        "collected_at": utc_now(),
        "reviewer": "",
        "review_note": "",
        "reviewed_at": "",
    }
    if extra:
        row.update(extra)
    return row


def _source_pages(obj: object) -> str:
    for key in ("Page", "Pages", "Source"):
        text = _plain_text(_attr(obj, key))
        if text:
            return text
    return ""


def _meaningful_source_pages(pages: object) -> bool:
    """A real bibliographic reference vs an unknown/empty placeholder.

    Values like ``未知`` / ``未詳`` / ``不详`` / ``unknown`` / ``0`` are not a
    meaningful source reference, so a record carrying only those must never be
    upgraded to B grade even with an exact year.
    """
    text = str(pages or "").strip()
    if not text:
        return False
    lowered = re.sub(r"\s+", "", text).casefold()
    if lowered in {"0", "未知", "未詳", "不详", "unknown", "無", "无", "n/a"}:
        return False
    if any(token in lowered for token in ("未詳", "未知", "不详")):
        return False
    return True


def _cbdb_address_candidate(
    poet: str, addr: dict[str, object], person_id: str, cache_key: str, source_url: str
) -> dict[str, object] | None:
    addr_id = _plain_text(_attr(addr, "AddrId"))
    name = _plain_text(_attr(addr, "AddrName"))
    first = parse_positive_year(_attr(addr, "FirstYear"))
    last = parse_positive_year(_attr(addr, "LastYear"))
    years = [y for y in (first, last) if y is not None]
    # A residence/visit candidate requires a valid FirstYear.  Native-place rows
    # whose start is 0 or blank must not become a journey even if LastYear is set.
    if not name or first is None or not years:
        return None
    start, end = min(years), max(years)
    pages = _source_pages(addr)
    addr_type = _plain_text(_attr(addr, "AddrType"))
    grade = "B" if _meaningful_source_pages(pages) and start == end else "C"
    note = f"CBDB人物({person_id or '?'}){addr_type or '居住/籍贯'}地址：{name}（{start}-{end}）"
    if pages:
        note += f"；出处：{pages}"
    return _cbdb_common(poet, person_id, addr_id, "residence", start, end, name, pages, note, grade, cache_key, source_url)


def _cbdb_posting_candidate(
    poet: str, post: dict[str, object], person_id: str, cache_key: str, source_url: str
) -> dict[str, object] | None:
    addr_id = _plain_text(_attr(post, "AddrId"))
    name = _plain_text(_attr(post, "AddrName"))
    if not name or name in {"0", "未詳", "[未詳]"} or name.startswith("[未詳]"):
        return None
    first = parse_positive_year(_attr(post, "FirstYear"))
    last = parse_positive_year(_attr(post, "LastYear"))
    years = [y for y in (first, last) if y is not None]
    if not years:
        return None
    start, end = min(years), max(years)
    office = _plain_text(_attr(post, "OfficeName")) or _plain_text(_attr(post, "Office"))
    posting_id = _plain_text(_attr(post, "PostingId"))
    pages = _source_pages(post)
    grade = "B" if _meaningful_source_pages(pages) and start == end else "C"
    note = f"CBDB人物({person_id or '?'})任官：{office or '任职'}于{name}（{start}-{end}）"
    if pages:
        note += f"；出处：{pages}"
    # Distinct postings in the same year and place (e.g. 知制诰 vs 主客郎中)
    # must stay separate candidates, so the office (and the posting id locator)
    # take part in the candidate id.
    return _cbdb_common(
        poet, person_id, addr_id, "posting", start, end, name, pages, note, grade, cache_key, source_url,
        extra={"office": office, "posting_id": posting_id},
        id_parts=(office, posting_id),
    )


def _ch_name_matches(poet: str, chname: str) -> bool:
    """Traditional/simplified tolerant name check (蘇軾/苏轼, 陸游/陆游, ...)."""
    def simplified(value: str) -> str:
        return (
            value.replace("蘇", "苏")
            .replace("軾", "轼")
            .replace("轍", "辙")
            .replace("陸", "陆")
            .replace("祕", "秘")
            .replace("館", "馆")
            .replace("臺", "台")
            .replace("萬", "万")
            .replace("無", "无")
        )
    return bool(chname) and (chname == poet or simplified(chname) == simplified(poet))


def verify_cbdb_identity(
    poet: str,
    expected_id: str,
    person: dict[str, object] | None,
    *,
    accepted_names: list[str] | None = None,
) -> tuple[bool, str]:
    """Verify the response really is the fixed CBDB person we asked for."""
    if person is None:
        return False, "no Person node in response"
    actual_id = str(person.get("person_id") or "")
    chname = str(person.get("name") or "")
    names = accepted_names or [poet]
    if not any(_ch_name_matches(name, chname) for name in names):
        return False, f"ChName {chname!r} does not match audited names {names} (identity_mismatch)"
    if actual_id and actual_id != expected_id:
        return False, f"PersonId {actual_id} != expected {expected_id} (identity_mismatch)"
    return True, ""


def _registry_source(registry_entry: dict[str, object] | None, source: str) -> dict[str, object]:
    if not isinstance(registry_entry, dict):
        return {}
    value = registry_entry.get(source)
    return value if isinstance(value, dict) else {}


def _souyun_registry_blocker(registry_entry: dict[str, object] | None) -> str:
    """Return the current registry's authoritative Sou-yun identity blocker."""
    status = str(_registry_source(registry_entry, "souyun").get("status") or "")
    return status if status in _SOUYUN_FRESH_IDENTITY_BLOCKERS else ""


def _souyun_registry_blocker_status(
    poet: str,
    registry_entry: dict[str, object] | None,
    *,
    max_pages: int,
    transport: str,
) -> dict[str, object] | None:
    """Materialize a blocker as a fresh zero-fetch status without using an id."""
    blocker = _souyun_registry_blocker(registry_entry)
    if not blocker:
        return None
    source_entry = _registry_source(registry_entry, "souyun")
    registry_note = str(source_entry.get("probe_note") or source_entry.get("note") or "").strip()
    note = f"current Sou-yun registry identity status is {blocker}; collection skipped"
    if registry_note:
        note += f": {registry_note}"
    return {
        "poet": poet,
        "source": "souyun",
        "source_transport": "official_api" if transport == "api" else "html_compat",
        "status": blocker,
        "source_url": str(source_entry.get("source_url") or ""),
        "note": note,
        "candidates": 0,
        "pages_requested": max_pages,
        "pages_completed": 0,
        "pagination_mode": "auto" if max_pages == 0 else "bounded",
        "pagination_complete": False,
        "author_id": None,
        "identity_verified": False,
        "retry_recommended": False,
        "checked_at": utc_now(),
    }


def collect_cbdb(
    poet: str,
    client: HttpCacheClient,
    *,
    registry_entry: dict[str, object] | None = None,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    identity = _registry_source(registry_entry, "cbdb")
    person_id = str(identity.get("person_id") or CBDB_PERSON_IDS.get(poet) or "").strip()
    identity_status = str(identity.get("status") or ("audited_seed" if person_id else "unresolved"))
    status = {
        "poet": poet,
        "source": "cbdb",
        "status": "ok",
        "source_url": "",
        "note": "",
        "candidates": 0,
        "identity_status": identity_status,
        "person_id": person_id or None,
        "checked_at": utc_now(),
    }
    if not person_id:
        if "ambiguous" in identity_status:
            status["status"] = "identity_ambiguous"
            status["note"] = f"CBDB exact-name lookup for {poet} is ambiguous; no person id selected"
        elif identity_status == "not_found":
            status["status"] = "identity_not_found"
            status["note"] = f"CBDB exact-name lookup found no person id for {poet}"
        else:
            status["status"] = "identity_unresolved"
            status["note"] = f"CBDB identity for {poet} has no unique person id"
        return [], status
    url = f"{CBDB_API}?id={person_id}&mode=json"
    result, payload = client.get_json(url, respect_robots=True)
    status["source_url"] = result.url
    status["note"] = result.note
    if result.status == "offline_cache_miss":
        status["status"] = "offline_cache_miss"
        status["note"] = "offline mode; no cached response for this query"
        return [], status
    if result.status != "ok":
        # Keep the original failure classification (parse_failed / fetch_failed /
        # blocked_by_policy) and its reason instead of collapsing to one token.
        status["status"] = result.status
        status["note"] = result.note or result.status
        return [], status
    if payload is None:
        status["status"] = "parse_failed"
        status["note"] = "response is not valid JSON"
        return [], status
    person = extract_cbdb_person(payload)
    accepted_names = [
        str(value) for value in identity.get("accepted_names", []) if str(value or "").strip()
    ] if isinstance(identity.get("accepted_names"), list) else [poet]
    identity_ok, reason = verify_cbdb_identity(
        poet,
        person_id,
        person,
        accepted_names=accepted_names,
    )
    if not identity_ok:
        status["status"] = "identity_mismatch"
        status["note"] = reason
        return [], status
    assert person is not None
    index_year = str(person.get("index_year") or "")
    candidates: list[dict[str, object]] = []
    for addr in person["addresses"]:
        candidate = _cbdb_address_candidate(poet, addr, person["person_id"], result.cache_key, result.url)
        if candidate is not None:
            candidates.append(candidate)
    for post in person["postings"]:
        candidate = _cbdb_posting_candidate(poet, post, person["person_id"], result.cache_key, result.url)
        if candidate is not None:
            candidates.append(candidate)
    unique_ids = {str(candidate.get("candidate_id") or "") for candidate in candidates}
    status["candidates"] = len(unique_ids)
    status["status"] = "collected" if unique_ids else "no_usable_records"
    status["note"] = (
        f"id={person_id} 姓名={person.get('name')}"
        + (f" IndexYear={index_year}" if index_year else "")
        + f"；{len(person['addresses'])} addresses, {len(person['postings'])} postings; "
        f"{len(candidates)} raw, {len(unique_ids)} unique"
    )
    return candidates, status


# --------------------------------------------------------------------------- #
# Sou-yun author index (structured secondary index)
# --------------------------------------------------------------------------- #

def _souyun_work_id(href: str) -> str:
    match = _QUERY_ID_RE.search(href)
    return match.group(1) if match else ""


def _year_parenthetical(text: str) -> str:
    """Return the parenthetical segment that actually carries a year.

    Titles themselves may contain parentheses (e.g. ``秋浦歌（其十五）``), so the
    plain first-parenthetical rule is insufficient.
    """
    for match in _PAREN_RE.finditer(text):
        inner = match.group(1).strip()
        if _YEAR_RE.search(inner):
            return inner
    return ""


def _parse_year_info(paren: str) -> dict[str, object]:
    if not paren:
        return {"years": [], "precision": ""}
    years = [int(m) for m in _YEAR_RE.findall(paren)]
    years = [y for y in years if 1 <= y <= 3000]
    has_month = bool(_MONTH_TOKEN_RE.search(paren))
    precision = "year_month" if (years and has_month) else ("year" if years else "")
    return {"years": years, "precision": precision}


def parse_souyun_entries(html: str) -> list[dict[str, object]]:
    """Parse ``div.poemTitle.showDetail`` blocks into candidate entries."""
    soup = _soup(html)
    entries: list[dict[str, object]] = []
    for div in soup.select("div.poemTitle.showDetail"):
        link = div.select_one('a[href*="Query.aspx"]')
        if link is None:
            continue
        href = str(link.get("href") or "")
        title = _plain_text(link.get_text(" ", strip=True))
        if not title:
            continue
        full = div.get_text(" ", strip=True)
        # On the live site ``span.author`` currently contains the date, not the
        # poet.  The stable author signal is the visible ``dynasty · poet`` text.
        author_matches = _SOUYUN_AUTHOR_RE.findall(full)
        author = author_matches[-1] if author_matches else ""
        if not author:
            author_el = div.select_one(".poet, .writer, span[class*=writer], .author, span[class*=author]")
            fallback = _plain_text(author_el.get_text(" ", strip=True)) if author_el is not None else ""
            if fallback and not _YEAR_RE.search(fallback):
                author = fallback
        time_el = div.select_one(".showTime, .time, span[class*=time]")
        paren_source = time_el.get_text(" ", strip=True) if time_el is not None else full
        paren = _year_parenthetical(paren_source)
        year_info = _parse_year_info(paren)
        entries.append(
            {
                "work_id": _souyun_work_id(href),
                "title": title,
                "author": author,
                "parenthetical": paren,
                "years": year_info["years"],
                "precision": year_info["precision"],
                "raw_text": full,
            }
        )
    return entries


def build_poem_index() -> dict[str, dict[str, list[dict[str, object]]]]:
    """Map ``poet -> normalized_title -> [poem rows]`` from data/poems.json."""
    index: dict[str, dict[str, list[dict[str, object]]]] = {}
    for poem in load_poems():
        poet = str(poem.get("poet") or "")
        key = normalize_title(poem.get("title"))
        if not poet or not key:
            continue
        index.setdefault(poet, {}).setdefault(key, []).append(poem)
    return index


def find_matching_poems(poet: str, title: str, index: dict[str, dict[str, list[dict[str, object]]]]) -> list[dict[str, object]]:
    """Exact same-author normalize_title match only (never a fuzzy match)."""
    key = normalize_title(title)
    if not key:
        return []
    return list(index.get(poet, {}).get(key, []))


def souyun_title_variants(title: str) -> list[str]:
    """Return strict, auditable title variants for Sou-yun editorial markup.

    This is not fuzzy matching: it only removes footnote marks and parenthetical
    editorial notes.  Parentheses that are solely a group number (``其十五``)
    are retained so a bare group subtitle cannot be attached to another poem.
    """
    raw = str(title or "").strip()
    if not raw:
        return []
    no_footnotes = _SOUYUN_FOOTNOTE_RE.sub("", raw).strip()

    def strip_note(match: re.Match[str]) -> str:
        inner = (match.group(1) or match.group(2) or "").strip()
        compact = re.sub(r"\s+", "", inner)
        return match.group(0) if _SOUYUN_GROUP_NOTE_RE.fullmatch(compact) else ""

    no_editorial_notes = _SOUYUN_TITLE_PAREN_RE.sub(strip_note, no_footnotes).strip()
    values: list[str] = []
    for value in (raw, no_footnotes, no_editorial_notes):
        normalized = normalize_title(value)
        if normalized and normalized not in values:
            values.append(normalized)
    return values


def find_souyun_matching_poems(
    poet: str,
    title: str,
    index: dict[str, dict[str, list[dict[str, object]]]],
) -> list[dict[str, object]]:
    """Match only exact normalized Sou-yun title variants for the same poet."""
    # Deduplicate only the same row reached through multiple variants.  Two
    # separate corpus rows with the same title remain ambiguous, even if their
    # bodies happen to be identical.
    matches: dict[int, dict[str, object]] = {}
    poet_index = index.get(poet, {})
    for key in souyun_title_variants(title):
        for poem in poet_index.get(key, []):
            matches[id(poem)] = poem
    return list(matches.values())


def make_work_chronology_candidate(
    poet: str,
    poem: dict[str, object],
    entry: dict[str, object],
    y_start: int,
    y_end: int,
    cache_key: str,
    url: str,
    *,
    source_mode: str = "html",
) -> dict[str, object]:
    precision = str(entry.get("precision") or "year")
    year_precision = "exact" if precision == "year_month" else "approximate"
    work_id = str(entry.get("work_id") or "")
    if source_mode == "api":
        evidence = f"搜韵开放API AuthorDate 将《{poem.get('title')}》系于{y_start}-{y_end}年"
        if entry.get("author_date"):
            evidence += f"（{entry.get('author_date')}）"
    else:
        evidence = f"搜韵作者索引系《{poem.get('title')}》于{y_start}-{y_end}年"
        if entry.get("parenthetical"):
            evidence += f"（{entry.get('parenthetical')}）"
    candidate_id = deterministic_id(poet, "work_chronology", "souyun", work_id, poem_body_hash(poem), y_start, y_end)
    candidate: dict[str, object] = {
        "candidate_id": candidate_id,
        "poet": poet,
        "event_type": "work_chronology",
        "source": "souyun",
        "poem_title": str(poem.get("title") or ""),
        "body_hash": poem_body_hash(poem),
        "linked": True,
        "source_title_ambiguous": False,
        "year_start": y_start,
        "year_end": y_end,
        "year_precision": year_precision,
        "precision": precision,
        "souyun_work_id": work_id,
        "source_title": str(entry.get("title") or ""),
        "historical_place": "",
        "source_name": "搜韵开放API·作品编年索引" if source_mode == "api" else "搜韵·作者索引（编年二手索引）",
        "source_pages": url,
        "source_note": evidence,
        "source_url": url,
        "source_grade": "C",
        "access_level": "public_web",
        "license": "",
        "license_note": "搜韵无机器复用的明确开放许可；仅保存结构化字段与必要短引，年份需人工复核",
        "status": "needs_review",
        "raw_cache_key": cache_key,
        "extraction_method": "souyun_open_poem_api_v1" if source_mode == "api" else "souyun_poem_index_v1",
        "collected_at": utc_now(),
        "reviewer": "",
        "review_note": "",
        "reviewed_at": "",
    }
    if source_mode == "api":
        candidate.update(
            {
                "souyun_author_id": entry.get("author_id"),
                "souyun_author_date": str(entry.get("author_date") or ""),
                "souyun_author_place": str(entry.get("author_place") or ""),
                "souyun_dynasty": str(entry.get("dynasty") or ""),
                "souyun_type": str(entry.get("type") or ""),
                "souyun_type_detail": str(entry.get("type_detail") or ""),
                "souyun_rhyme": str(entry.get("rhyme") or ""),
                "souyun_rank": entry.get("rank"),
                "souyun_comment_count": int(entry.get("comment_count") or 0),
                "souyun_comment_sources": entry.get("comment_sources") or [],
            }
        )
    return candidate


def _souyun_page_candidates(
    poet: str,
    entries: list[dict[str, object]],
    index: dict[str, dict[str, list[dict[str, object]]]],
    cache_key: str,
    url: str,
    *,
    source_mode: str = "html",
) -> tuple[list[dict[str, object]], Counter[str]]:
    candidates: list[dict[str, object]] = []
    skips: Counter[str] = Counter()
    for entry in entries:
        years = entry.get("years")
        if not years:
            skips["no_year"] += 1
            continue
        author = str(entry.get("author") or "")
        if author and not _ch_name_matches(poet, author):
            skips["author_mismatch"] += 1
            continue
        matches = find_souyun_matching_poems(poet, str(entry.get("title") or ""), index)
        if not matches:
            skips["unmatched"] += 1
            continue
        if len(matches) > 1:
            skips["ambiguous"] += 1
            continue
        y_values = [int(y) for y in years]
        y_start, y_end = min(y_values), max(y_values)
        candidates.append(
            make_work_chronology_candidate(
                poet,
                matches[0],
                entry,
                y_start,
                y_end,
                cache_key,
                url,
                source_mode=source_mode,
            )
        )
    return candidates, skips


def _souyun_author_id(url: str, html: str) -> str:
    """Find a numeric author id from a redirect target or canonical page link."""
    query = parse_qs(urlparse(url).query)
    values = query.get("author") or []
    if values and str(values[0]).isdigit():
        return str(values[0])
    soup = _soup(html)
    for link in soup.select('a[href*="PoemIndex.aspx"][href*="author="]'):
        values = parse_qs(urlparse(str(link.get("href") or "")).query).get("author") or []
        if values and str(values[0]).isdigit():
            return str(values[0])
    return ""


def _souyun_has_next_page(html: str, current_page: int) -> bool:
    soup = _soup(html)
    for link in soup.select('a[href*="page="]'):
        values = parse_qs(urlparse(str(link.get("href") or "")).query).get("page") or []
        try:
            if values and int(values[0]) > current_page:
                return True
        except (TypeError, ValueError):
            continue
    return False


def _souyun_page_fingerprint(entries: list[dict[str, object]]) -> str:
    payload = [
        (
            str(entry.get("work_id") or ""),
            str(entry.get("title") or ""),
            str(entry.get("author") or ""),
            tuple(entry.get("years") or []),
        )
        for entry in entries
    ]
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _collect_souyun_html(
    poet: str,
    client: HttpCacheClient,
    *,
    max_pages: int = 1,
    poem_index: dict[str, dict[str, list[dict[str, object]]]] | None = None,
    registry_entry: dict[str, object] | None = None,
    auto_page_limit: int = SOUYUN_AUTO_PAGE_LIMIT,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    index = poem_index if poem_index is not None else build_poem_index()
    source_entry = _registry_source(registry_entry, "souyun")
    author_id = str(source_entry.get("author_id") or SOUYUN_AUTHOR_IDS.get(poet) or "").strip()
    dynasty = str((registry_entry or {}).get("dynasty") or "").strip()
    if not author_id and dynasty not in {"Tang", "Song"}:
        dynasty = next((profile["dynasty"] for profile in corpus_poet_profiles() if profile["poet"] == poet), "")
    query_strategy = "author_id" if author_id else "author_name_dynasty"
    if not author_id and not dynasty:
        return [], {
            "poet": poet,
            "source": "souyun",
            "status": "identity_unresolved",
            "note": f"no dynasty available for Sou-yun name query: {poet}",
            "candidates": 0,
            "checked_at": utc_now(),
        }
    auto_mode = max_pages == 0
    page_limit = max(1, int(auto_page_limit)) if auto_mode else max_pages
    all_candidates: list[dict[str, object]] = []
    total_entries = 0
    skip_counts: Counter[str] = Counter()
    completed = 0
    failed_page: int | None = None
    failure_status: dict[str, object] = {}
    stop_reason = ""
    seen_pages: set[str] = set()
    last_url = ""
    # Sou-yun pagination is 0-based: page=0 (or no page param) is the home page.
    for page_index in range(page_limit):
        if author_id:
            query = f"author={author_id}"
        else:
            query = f"author={quote(poet)}&dynasty={dynasty}"
        url = f"https://www.sou-yun.cn/PoemIndex.aspx?{query}&page={page_index}"
        result = client.request("GET", url, respect_robots=True)
        last_url = result.url or url
        status: dict[str, object] = {
            "poet": poet,
            "source": "souyun",
            "status": result.status,
            "source_url": result.url,
            "note": result.note,
            "candidates": 0,
            "page": page_index,
            "checked_at": utc_now(),
        }
        if result.status != "ok":
            failed_page = page_index + 1
            failure_status = status
            break
        completed += 1
        entries = parse_souyun_entries(result.text)
        discovered = _souyun_author_id(result.url, result.text)
        if discovered:
            author_id = discovered
        total_entries += len(entries)
        if not entries:
            stop_reason = "empty_page"
            break
        fingerprint = _souyun_page_fingerprint(entries)
        if fingerprint in seen_pages:
            stop_reason = "repeated_page"
            break
        seen_pages.add(fingerprint)
        candidates, skips = _souyun_page_candidates(poet, entries, index, result.cache_key, result.url)
        all_candidates.extend(candidates)
        skip_counts.update(skips)
        if auto_mode and not _souyun_has_next_page(result.text, page_index):
            stop_reason = "no_next_page"
            break
    status: dict[str, object] = {
        "poet": poet,
        "source": "souyun",
        "status": "ok",
        "source_url": "",
        "note": "",
        "candidates": len(all_candidates),
        "pages_requested": max_pages,
        "pages_completed": completed,
        "pagination_mode": "auto" if auto_mode else "bounded",
        "pagination_complete": False,
        "query_strategy": query_strategy,
        "source_transport": "html_compat",
        "author_id": int(author_id) if author_id.isdigit() else None,
        "page_hard_limit": page_limit if auto_mode else None,
        "checked_at": utc_now(),
    }
    if last_url:
        status["source_url"] = last_url
    skip_text = " ".join(f"{key}:{count}" for key, count in sorted(skip_counts.items()))
    base_note = f"{total_entries} entries; {len(all_candidates)} matched" + (f"; {skip_text}" if skip_text else "")
    if failed_page is not None:
        # A mid-run page failure must not be rewritten as a full success just
        # because earlier pages already produced candidates.
        status["failed_page"] = failed_page
        reason = str(failure_status.get("note") or failure_status.get("status") or "unknown failure")
        if completed == 0:
            status["status"] = str(failure_status.get("status") or "fetch_failed")
            status["source_url"] = str(failure_status.get("source_url") or "")
            status["note"] = f"failed at page {failed_page}: {reason}"
        else:
            status["status"] = "partial"
            status["note"] = f"failed at page {failed_page}: {reason}; {base_note}"
        return all_candidates, status
    if auto_mode and not stop_reason and completed >= page_limit:
        status["status"] = "partial"
        status["stop_reason"] = "hard_limit_reached"
        status["note"] = f"auto pagination reached hard limit {page_limit}; {base_note}"
        return all_candidates, status
    status["pagination_complete"] = bool(stop_reason) if auto_mode else completed >= max_pages or bool(stop_reason)
    if stop_reason:
        status["stop_reason"] = stop_reason
    status["status"] = "collected" if all_candidates else "ok"
    status["note"] = base_note + (f"; stop={stop_reason}" if stop_reason else "")
    return all_candidates, status


def _souyun_api_root(payload: object) -> dict[str, object] | None:
    if not isinstance(payload, dict):
        return None
    if any(key in payload for key in ("Authors", "ShiData", "Count", "PageNo", "PageSize")):
        return payload
    for key in ("Data", "data", "Result", "result"):
        nested = payload.get(key)
        if isinstance(nested, dict):
            found = _souyun_api_root(nested)
            if found is not None:
                return found
    return payload


def _souyun_api_values(value: object) -> list[object]:
    if value is None:
        return []
    return list(value) if isinstance(value, list) else [value]


def _souyun_api_int(value: object) -> int | None:
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _souyun_api_authors(root: dict[str, object]) -> list[dict[str, object]]:
    raw = root.get("Authors")
    if isinstance(raw, list):
        return [dict(row) for row in raw if isinstance(row, dict)]
    if not isinstance(raw, dict):
        return []
    names = _souyun_api_values(raw.get("Names"))
    author_ids = _souyun_api_values(raw.get("AuthorIds"))
    dynasties = _souyun_api_values(raw.get("Dynasties"))
    size = max(len(names), len(author_ids), len(dynasties), 0)
    return [
        {
            "name": names[index] if index < len(names) else "",
            "author_id": author_ids[index] if index < len(author_ids) else None,
            "dynasty": dynasties[index] if index < len(dynasties) else "",
        }
        for index in range(size)
    ]


def _souyun_dynasty_matches(value: object, expected: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    if expected == "Tang":
        return text == "Tang" or "唐" in text
    if expected == "Song":
        return text == "Song" or "宋" in text
    return False


def _souyun_api_comment_sources(work: dict[str, object]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    comments = work.get("Comments") if isinstance(work.get("Comments"), list) else []
    for comment in comments:
        if not isinstance(comment, dict):
            continue
        rows.append(
            {
                "book": str(comment.get("Book") or ""),
                "full_path": str(comment.get("FullPath") or ""),
                "is_comment": bool(comment.get("IsComment")),
                "excerpt": normalize_excerpt(comment.get("Content"), limit=80),
            }
        )
    return rows


def parse_souyun_api_page(payload: object) -> dict[str, object] | None:
    """Normalize one official ``open/Poem`` response without guessing fields."""
    root = _souyun_api_root(payload)
    if root is None:
        return None
    raw_works = root.get("ShiData")
    if not isinstance(raw_works, list):
        raw_works = []
    entries: list[dict[str, object]] = []
    for work in raw_works:
        if not isinstance(work, dict):
            continue
        title_node = work.get("Title") if isinstance(work.get("Title"), dict) else {}
        title = _plain_text(title_node.get("Content"))
        author_date = _plain_text(work.get("AuthorDate"))
        years = [int(value) for value in _YEAR_RE.findall(author_date)]
        years = [year for year in years if 1 <= year <= 3000]
        has_subyear = bool(_MONTH_TOKEN_RE.search(author_date))
        clauses = work.get("Clauses") if isinstance(work.get("Clauses"), list) else []
        body = "".join(
            _plain_text(clause.get("Content"))
            for clause in clauses
            if isinstance(clause, dict)
        )
        comment_sources = _souyun_api_comment_sources(work)
        entries.append(
            {
                "work_id": str(work.get("Id") or ""),
                "title": title,
                "author": _plain_text(work.get("Author")),
                "author_id": _souyun_api_int(work.get("AuthorId")),
                "dynasty": _plain_text(work.get("Dynasty")),
                "author_date": author_date,
                "author_place": _plain_text(work.get("AuthorPlace")),
                "years": years,
                "precision": "year_month" if years and has_subyear else ("year" if years else ""),
                "type": _plain_text(work.get("Type")),
                "type_detail": _plain_text(work.get("TypeDetail")),
                "rhyme": _plain_text(work.get("Rhyme")),
                "rank": work.get("Rank"),
                "body": body,
                "comment_count": len(comment_sources),
                "comment_sources": comment_sources,
                "raw_text": f"{title} {author_date} {_plain_text(work.get('AuthorPlace'))}".strip(),
            }
        )
    return {
        "authors": _souyun_api_authors(root),
        "entries": entries,
        "count": _souyun_api_int(root.get("Count")),
        "page_no": _souyun_api_int(root.get("PageNo")),
        "page_size": _souyun_api_int(root.get("PageSize")),
    }


def _verify_souyun_api_identity(
    poet: str,
    dynasty: str,
    expected_id: str,
    page: dict[str, object],
) -> tuple[str, str, str]:
    authors = page.get("authors") if isinstance(page.get("authors"), list) else []
    matches: list[str] = []
    for author in authors:
        if not isinstance(author, dict):
            continue
        name = str(author.get("name") or author.get("Names") or "")
        author_dynasty = author.get("dynasty") or author.get("Dynasties")
        author_id = str(author.get("author_id") or author.get("AuthorIds") or "").strip()
        if _ch_name_matches(poet, name) and _souyun_dynasty_matches(author_dynasty, dynasty) and author_id.isdigit():
            matches.append(author_id)
    if not matches:
        entries = page.get("entries") if isinstance(page.get("entries"), list) else []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            author_id = str(entry.get("author_id") or "").strip()
            if (
                _ch_name_matches(poet, str(entry.get("author") or ""))
                and _souyun_dynasty_matches(entry.get("dynasty"), dynasty)
                and author_id.isdigit()
            ):
                matches.append(author_id)
    unique = list(dict.fromkeys(matches))
    if not unique:
        return "identity_not_found", "", f"Sou-yun API returned no exact {poet}/{dynasty} author identity"
    if len(unique) > 1:
        return "identity_ambiguous", "", f"Sou-yun API returned multiple AuthorIds for {poet}: {', '.join(unique)}"
    if expected_id and unique[0] != expected_id:
        return "identity_mismatch", "", f"Sou-yun AuthorId {unique[0]} != expected {expected_id}"
    return "ok", unique[0], ""


def _collect_souyun_api(
    poet: str,
    client: HttpCacheClient,
    *,
    max_pages: int,
    poem_index: dict[str, dict[str, list[dict[str, object]]]],
    registry_entry: dict[str, object] | None,
    auto_page_limit: int,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    source_entry = _registry_source(registry_entry, "souyun")
    expected_id = str(source_entry.get("author_id") or SOUYUN_AUTHOR_IDS.get(poet) or "").strip()
    dynasty = str((registry_entry or {}).get("dynasty") or "").strip()
    if dynasty not in {"Tang", "Song"}:
        dynasty = next((profile["dynasty"] for profile in corpus_poet_profiles() if profile["poet"] == poet), "")
    checked_at = utc_now()
    base_status: dict[str, object] = {
        "poet": poet,
        "source": "souyun",
        "source_transport": "official_api",
        "status": "ok",
        "source_url": "",
        "note": "",
        "candidates": 0,
        "api_count": None,
        "api_page_size": None,
        "pages_requested": max_pages,
        "pages_completed": 0,
        "works_received": 0,
        "pagination_mode": "auto" if max_pages == 0 else "bounded",
        "pagination_complete": False,
        "author_id": int(expected_id) if expected_id.isdigit() else None,
        "identity_verified": False,
        "checked_at": checked_at,
    }
    if not dynasty:
        base_status.update(status="identity_unresolved", note=f"no Tang/Song dynasty for {poet}")
        return [], base_status

    auto_mode = max_pages == 0
    page_limit = max(1, auto_page_limit) if auto_mode else max_pages
    all_candidates: list[dict[str, object]] = []
    skip_counts: Counter[str] = Counter()
    seen_work_pages: set[tuple[str, ...]] = set()
    resolved_id = ""
    expected_count: int | None = None
    page_size: int | None = None
    works_received = 0
    pages_completed = 0
    rate_limit_streak = 0
    stop_reason = ""
    last_url = ""
    identity_matches = False

    for page_no in range(page_limit):
        url = (
            f"{SOUYUN_POEM_API}?key={quote(poet)}&scope=Author&dynasty={dynasty}"
            f"&jsonType=true&pageNo={page_no}"
        )
        result: FetchResult
        payload: object | None
        while True:
            result, payload = client.get_json(url, respect_robots=False)
            last_url = result.url or url
            if result.status_code == 429:
                rate_limit_streak += 1
                if rate_limit_streak >= 2:
                    base_status.update(
                        status="rate_limited",
                        note="Sou-yun API returned HTTP 429 twice consecutively; scope paused for resume",
                        source_url=last_url,
                        failed_page=page_no + 1,
                        rate_limit_streak=rate_limit_streak,
                        retry_recommended=True,
                        pages_completed=pages_completed,
                        works_received=works_received,
                        candidates=len(all_candidates),
                        api_count=expected_count,
                        api_page_size=page_size,
                        author_id=int(resolved_id or expected_id) if (resolved_id or expected_id).isdigit() else None,
                    )
                    return all_candidates, base_status
                continue
            rate_limit_streak = 0
            break

        if result.status != "ok":
            base_status.update(
                status="partial" if pages_completed else result.status,
                note=f"Sou-yun API page {page_no} failed: {result.note or result.status}",
                source_url=last_url,
                failed_page=page_no + 1,
                pages_completed=pages_completed,
                works_received=works_received,
                candidates=len(all_candidates),
                api_count=expected_count,
                api_page_size=page_size,
            )
            return all_candidates, base_status
        page = parse_souyun_api_page(payload)
        if page is None:
            base_status.update(
                status="not_covered" if pages_completed == 0 else "partial",
                note="Sou-yun API returned no structured poem payload",
                source_url=last_url,
                failed_page=page_no + 1,
                pages_completed=pages_completed,
                works_received=works_received,
                candidates=len(all_candidates),
            )
            return all_candidates, base_status
        pages_completed += 1
        entries = page.get("entries") if isinstance(page.get("entries"), list) else []
        if expected_count is None:
            expected_count = page.get("count") if isinstance(page.get("count"), int) else None
        if page_size is None:
            page_size = page.get("page_size") if isinstance(page.get("page_size"), int) else None
        if page_no == 0:
            identity_status, resolved_id, identity_note = _verify_souyun_api_identity(
                poet, dynasty, expected_id, page
            )
            if identity_status != "ok":
                base_status.update(
                    status=identity_status,
                    note=identity_note,
                    source_url=last_url,
                    pages_completed=pages_completed,
                )
                return [], base_status
            identity_matches = bool(resolved_id.isdigit() and int(resolved_id) > 0)
            if page_size == 0 and not entries:
                base_status.update(
                    status="discovered_author_id_but_api_requires_disambiguation",
                    note=(
                        "Sou-yun author search found one exact identity, but PageSize=0 and ShiData is empty; "
                        "API Count describes author candidates, not poems, and tested id parameters do not disambiguate"
                    ),
                    source_url=last_url,
                    pages_completed=pages_completed,
                    works_received=0,
                    api_count=expected_count,
                    api_count_semantics="author_candidates",
                    api_page_size=page_size,
                    author_id=int(resolved_id) if resolved_id.isdigit() else None,
                    pagination_complete=False,
                    retry_recommended=False,
                )
                return [], base_status
        exact_entries = [
            entry for entry in entries
            if isinstance(entry, dict)
            and _ch_name_matches(poet, str(entry.get("author") or ""))
            and str(entry.get("author_id") or "") == resolved_id
            and _souyun_dynasty_matches(entry.get("dynasty"), dynasty)
        ]
        works_received += len(exact_entries)
        fingerprint = tuple(str(entry.get("work_id") or "") for entry in exact_entries)
        if fingerprint in seen_work_pages and fingerprint:
            stop_reason = "repeated_page"
            break
        if fingerprint:
            seen_work_pages.add(fingerprint)
        candidates, skips = _souyun_page_candidates(
            poet,
            exact_entries,
            poem_index,
            result.cache_key,
            last_url,
            source_mode="api",
        )
        all_candidates.extend(candidates)
        skip_counts.update(skips)
        if not exact_entries:
            stop_reason = "empty_page"
            break
        if expected_count is not None and works_received >= expected_count:
            stop_reason = "count_complete"
            break
        if expected_count is not None and page_size:
            total_pages = max(1, math.ceil(expected_count / page_size))
            if pages_completed >= total_pages:
                stop_reason = "count_pages_complete"
                break

    complete = bool(stop_reason in {"empty_page", "count_complete", "count_pages_complete"})
    if expected_count == 0:
        complete = True
    bounded_incomplete = not auto_mode and expected_count is not None and works_received < expected_count
    hard_limit_incomplete = auto_mode and not complete and pages_completed >= page_limit
    skip_text = " ".join(f"{key}:{count}" for key, count in sorted(skip_counts.items()))
    note = f"API count={expected_count}; received={works_received}; matched={len(all_candidates)}"
    if skip_text:
        note += f"; {skip_text}"
    if stop_reason:
        note += f"; stop={stop_reason}"
    if bounded_incomplete:
        note += "; bounded page request did not cover full API count"
    if hard_limit_incomplete:
        note += f"; auto hard limit={page_limit} reached"
    final_status = "partial" if (bounded_incomplete or hard_limit_incomplete) else ("collected" if all_candidates else "ok")
    identity_verified = bool(final_status in {"ok", "collected"} and identity_matches)
    base_status.update(
        status=final_status,
        source_url=last_url,
        note=note,
        candidates=len(all_candidates),
        api_count=expected_count,
        api_page_size=page_size,
        pages_completed=pages_completed,
        works_received=works_received,
        author_id=int(resolved_id) if resolved_id.isdigit() else None,
        pagination_complete=complete,
        stop_reason=stop_reason or ("bounded_limit" if bounded_incomplete else "hard_limit_reached" if hard_limit_incomplete else ""),
        page_hard_limit=page_limit if auto_mode else None,
        identity_verified=identity_verified,
    )
    if identity_verified:
        base_status.update(
            verified_author_name=poet,
            verified_dynasty=dynasty,
            verified_author_id=int(resolved_id),
            identity_verification_method="souyun_open_poem_exact_name_dynasty_author_id",
            identity_verified_at=checked_at,
            identity_verified_from=last_url,
        )
    return all_candidates, base_status


def collect_souyun(
    poet: str,
    client: HttpCacheClient,
    *,
    max_pages: int = 1,
    poem_index: dict[str, dict[str, list[dict[str, object]]]] | None = None,
    registry_entry: dict[str, object] | None = None,
    auto_page_limit: int = SOUYUN_AUTO_PAGE_LIMIT,
    transport: str = "api",
) -> tuple[list[dict[str, object]], dict[str, object]]:
    if transport not in {"api", "html"}:
        raise ValueError("Sou-yun transport must be api or html")
    blocker_status = _souyun_registry_blocker_status(
        poet,
        registry_entry,
        max_pages=max_pages,
        transport=transport,
    )
    if blocker_status is not None:
        return [], blocker_status
    index = poem_index if poem_index is not None else build_poem_index()
    if transport == "html":
        return _collect_souyun_html(
            poet,
            client,
            max_pages=max_pages,
            poem_index=index,
            registry_entry=registry_entry,
            auto_page_limit=auto_page_limit,
        )
    return _collect_souyun_api(
        poet,
        client,
        max_pages=max_pages,
        poem_index=index,
        registry_entry=registry_entry,
        auto_page_limit=auto_page_limit,
    )


# --------------------------------------------------------------------------- #
# CNKGraph Biography API (optional / experimental)
# --------------------------------------------------------------------------- #

def _unwrap_biography(payload: object) -> object:
    if not isinstance(payload, dict):
        return payload
    for key in ("Biography", "biography", "Data", "data", "Result", "result"):
        value = payload.get(key)
        if isinstance(value, dict):
            return value
    return payload


def _activity_place(addr: object) -> str:
    if not isinstance(addr, dict):
        return ""
    parts: list[str] = []
    for key in ("OldSubProvince", "OldProvince", "Province", "City", "Place", "OldCity"):
        value = str(addr.get(key) or "").strip()
        if value and value not in {"0", "未詳", "[未詳]"} and (not parts or parts[-1] != value):
            parts.append(value)
    return "·".join(parts)


def _find_place_text(node: dict[str, object]) -> str:
    for key in _PLACE_KEYS:
        value = node.get(key)
        if isinstance(value, dict):
            place = _activity_place(value)
            if place:
                return place
        else:
            text = _plain_text(value)
            if text and text not in {"0", "未詳", "[未詳]"}:
                return text
    return ""


def extract_cnkgraph_biography(
    payload: object, poet: str = ""
) -> tuple[object, list[dict[str, object]], list[dict[str, object]]]:
    bio = _unwrap_biography(payload)
    person_events: list[dict[str, object]] = []
    works: list[dict[str, object]] = []
    if isinstance(bio, dict):
        activities = _as_list(bio.get("Activities") or bio.get("activities"))
        work_seq = 0
        for activity_index, activity in enumerate(activities):
            if not isinstance(activity, dict):
                continue
            year_range = _cnk_year_range(activity)
            if year_range is None:
                continue
            start, end, precision = year_range
            place = _activity_place(activity.get("Place")) or _activity_place(activity.get("MinorPlace"))
            if place:
                person_events.append(
                    {
                        "year_start": start,
                        "year_end": end,
                        "year_precision": precision,
                        "historical_place": place,
                        "event_text": _plain_text(activity.get("Activity")),
                        "category": _plain_text(activity.get("Category")),
                        "source_locator": f"Activity Year={start}-{end} Place={place}",
                        "index": activity_index,
                        "grade": "B",
                        "method": "cnkgraph_biography_api_v1",
                    }
                )
            for poem in _as_list(activity.get("Poems")):
                poem_title = _plain_text(poem.get("Title") or poem.get("Subject")) if isinstance(poem, dict) else ""
                if not poem_title:
                    continue
                source_author = _plain_text(poem.get("Author")) if isinstance(poem, dict) else ""
                if poet and source_author and not _ch_name_matches(poet, source_author):
                    continue
                works.append(
                    {
                        "year_start": start,
                        "year_end": end,
                        "year_precision": precision,
                        "poem_title": poem_title,
                        "source_author": source_author,
                        "source_locator": f"Activity Year={start}-{end} Poems[{poem_title}]",
                        "index": work_seq,
                        "grade": "B",
                        "method": "cnkgraph_biography_api_v1",
                    }
                )
                work_seq += 1
    if not person_events and not works:
        person_events, works = recursive_cnkgraph_extract(payload)
    return bio, person_events, works


def recursive_cnkgraph_extract(payload: object) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """Conservative recursive fallback; experimental.  Only yields objects that
    carry an explicit readable year plus an explicit place or title."""
    events: list[dict[str, object]] = []
    works: list[dict[str, object]] = []
    seen: set[int] = set()
    event_seq = 0
    work_seq = 0

    def _read_year(node: dict[str, object]) -> tuple[int, int, str] | None:
        for key in _YEAR_KEYS:
            value = node.get(key)
            if isinstance(value, bool):
                continue
            if isinstance(value, (int, float)) and 1 <= int(value) <= 3000:
                year = int(value)
                return year, year, "exact"
            if isinstance(value, str):
                parsed = _parse_year_range(value)
                if parsed is not None:
                    return parsed
        return None

    def walk(node: object) -> None:
        nonlocal event_seq, work_seq
        if isinstance(node, list):
            for item in node:
                walk(item)
            return
        if not isinstance(node, dict):
            return
        marker = id(node)
        if marker in seen:
            return
        seen.add(marker)
        year_range = _read_year(node)
        if year_range is not None:
            start, end, precision = year_range
            place = _find_place_text(node)
            title = next(
                (_plain_text(node.get(key)) for key in _TITLE_KEYS if _plain_text(node.get(key))),
                "",
            )
            if place:
                events.append(
                    {
                        "year_start": start,
                        "year_end": end,
                        "year_precision": precision,
                        "historical_place": place,
                        "event_text": "",
                        "category": "recursive",
                        "source_locator": "recursive-extractor",
                        "index": event_seq,
                        "grade": "C",
                        "method": "cnkgraph_biography_recursive_v1",
                    }
                )
                event_seq += 1
            if title:
                works.append(
                    {
                        "year_start": start,
                        "year_end": end,
                        "year_precision": precision,
                        "poem_title": title,
                        "source_locator": "recursive-extractor",
                        "index": work_seq,
                        "grade": "C",
                        "method": "cnkgraph_biography_recursive_v1",
                    }
                )
                work_seq += 1
        for value in node.values():
            walk(value)

    walk(payload)
    return events, works


# --------------------------------------------------------------------------- #
# CNKGraph Biography API -- real Traces/Markers/Detail structure
#
# The live Biography payload is organised as:
#   Common / Traces[] / ArticleStat / Title / ...
#   Traces[].Markers[] : { Id, Title, Latitude, Longitude, RegionId, Detail }
#   Marker.Detail      : HTML with one or more
#       <div class="label1"> (year-range anchor) followed by
#       <div class="detail"> containing rows of
#       <a href="...ViewDetail('...beginYear=N&endYear=M...')">YEAR</a>  TEXT
#       and embedded <div class="poemTitle showDetail"> blocks linking to
#       /Writing/{id}?labeling=true with a <span class="authorDate">.
#
# Traces[].Lines[].Markers are polyline points and are NOT travel facts.
# --------------------------------------------------------------------------- #

def _has_trace_structure(payload: object) -> bool:
    # Any payload whose top level carries a Traces *list* is the modern
    # Traces/Markers structure and must go through the trace parser -- even when
    # the main Markers are missing or empty.  The recursive fallback is only for
    # payloads with no Traces key at all, so Lines[].Markers can never be reached
    # as a fallback source of travel facts.
    return isinstance(payload, dict) and isinstance(payload.get("Traces"), list)


def _cnkgraph_markers(payload: object):
    """Yield marker dicts from Traces[].Markers only.

    Marker Id/Key are frequently null, so callers should pair each marker with
    its position (``enumerate(_cnkgraph_markers(payload))``) as the stable
    locator.  Polyline points under Traces[].Lines are never travel facts and
    are skipped.
    """
    if not isinstance(payload, dict):
        return
    traces = payload.get("Traces")
    if not isinstance(traces, list):
        return
    for trace in traces:
        if not isinstance(trace, dict):
            continue
        markers = trace.get("Markers")
        if not isinstance(markers, list):
            continue
        for marker in markers:
            if isinstance(marker, dict):
                yield marker


def _first_viewdetail_year(text: str, key: str) -> int | None:
    match = re.search(re.escape(key) + r"=(\d{1,4})", text)
    if not match:
        return None
    year = int(match.group(1))
    return year if 1 <= year <= 3000 else None


def _viewdetail_years(href: str) -> tuple[int | None, int | None]:
    return _first_viewdetail_year(href, "beginYear"), _first_viewdetail_year(href, "endYear")


def _is_poem_block(node: object) -> bool:
    return isinstance(node, Tag) and node.select_one("div.poemTitle.showDetail") is not None


def _marker_row_text(children: list[object]) -> str:
    parts: list[str] = []
    for child in children:
        if isinstance(child, Tag):
            if _is_poem_block(child):
                continue
            classes = " ".join(child.get("class") or [])
            if "inlineComment" in classes:
                continue
            parts.append(child.get_text(" ", strip=True))
        else:
            parts.append(str(child))
    return re.sub(r"\s+", " ", "".join(parts)).strip()


def _parse_marker_poem(block: Tag, row_begin: int, row_end: int) -> dict[str, object] | None:
    link = block.select_one("div.poemTitle.showDetail a[href*='/Writing/']")
    if link is None:
        return None
    href = str(link.get("href") or "")
    match = re.search(r"/Writing/(\d+)", href)
    writing_id = match.group(1) if match else ""
    title = _plain_text(link.get_text(" ", strip=True))
    if not title:
        return None
    author_date_el = block.select_one("span.authorDate")
    author_date = _plain_text(author_date_el.get_text(" ", strip=True)) if author_date_el else ""
    parsed = _parse_year_range(author_date)
    if parsed is not None:
        year_start, year_end, year_precision = parsed
    else:
        year_start, year_end = row_begin, row_end
        year_precision = "exact" if row_begin == row_end else "approximate"
    author_el = block.select_one("span.poemAuthor a")
    source_author = _plain_text(author_el.get_text(" ", strip=True)) if author_el is not None else ""
    return {
        "title": title,
        "writing_id": writing_id,
        "author_date": author_date,
        "year_start": year_start,
        "year_end": year_end,
        "year_precision": year_precision,
        "source_author": source_author,
    }


def _flush_marker_row(
    rows: list[dict[str, object]],
    begin: int | None,
    end: int | None,
    children: list[object],
    label_id: str = "",
    row_index: int = 0,
) -> bool:
    if begin is None or end is None:
        return False
    if not children:
        return False
    full_text = _marker_row_text(children)
    summary = normalize_excerpt(full_text, limit=120)
    poems = [
        poem
        for poem in (_parse_marker_poem(c, begin, end) for c in children if _is_poem_block(c))
        if poem is not None
    ]
    if not summary and not poems:
        return False
    rows.append(
        {
            "begin": begin,
            "end": end,
            "summary": summary,
            "poems": poems,
            "label_id": label_id,
            "row_index": row_index,
            # Identity is the full normalised text, but only its digest is kept.
            "event_hash": hashlib.sha256(full_text.encode("utf-8")).hexdigest(),
        }
    )
    return True


def _nearest_preceding_element_sibling(node: Tag) -> Tag | None:
    sibling = node.previous_sibling
    while sibling is not None and not isinstance(sibling, Tag):
        sibling = sibling.previous_sibling
    return sibling


def parse_marker_detail(detail: str) -> list[dict[str, object]]:
    """Split a Marker.Detail into year rows (label1 group -> detail rows).

    Strict rules:
      * every ``div.detail`` must have a DIRECTLY preceding ``div.label1`` -- the
        nearest preceding element sibling must itself be the label1 (an
        interleaved ``<div class='noise'>`` breaks the pairing);
      * the label1's child ``<a>`` ViewDetail href needs BOTH beginYear/endYear;
      * every inline year anchor needs BOTH beginYear/endYear; an anchor missing
        either ends the current row and discards the following content instead of
        opening a new valid row;
      * otherwise the block/row yields no B-grade rows.
    Each appended row carries a stable ``row_index`` ordinal (for unique locators)
    and an ``event_hash`` digest of the full normalised text.
    """
    soup = _soup(detail)
    rows: list[dict[str, object]] = []
    row_seq = 0
    for detail_div in soup.select("div.detail"):
        label = _nearest_preceding_element_sibling(detail_div)
        if label is None or label.name != "div" or "label1" not in (label.get("class") or []):
            continue
        link = label.select_one("a[href*='ViewDetail']")
        if link is None:
            continue
        group_begin, group_end = _viewdetail_years(str(link.get("href") or ""))
        if group_begin is None or group_end is None:
            continue
        label_id = str(detail_div.get("id") or "")
        begin, end = group_begin, group_end
        children: list[object] = []
        for child in detail_div.contents:
            years: tuple[int | None, int | None] | None = None
            if isinstance(child, Tag) and child.name == "a":
                href = str(child.get("href") or "")
                if "ViewDetail" in href and "beginYear" in href:
                    years = _viewdetail_years(href)
            if years is not None:
                # Any ViewDetail anchor is a row boundary; flush the current row.
                if _flush_marker_row(rows, begin, end, children, label_id, row_seq):
                    row_seq += 1
                if years[0] is not None and years[1] is not None:
                    begin, end = years
                else:
                    # Missing beginYear or endYear: no valid new row; discard the
                    # content that follows instead of merging it into this row.
                    begin, end = None, None
                children = []
            else:
                children.append(child)
        if _flush_marker_row(rows, begin, end, children, label_id, row_seq):
            row_seq += 1
    return rows


def _valid_latitude(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        and -90.0 <= float(value) <= 90.0
    )


def _valid_longitude(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        and -180.0 <= float(value) <= 180.0
    )


def _parse_year_range(
    text: object, default: tuple[int, int, str] | None = None
) -> tuple[int, int, str] | None:
    """Parse ``725-727`` / ``约725`` / ``725年`` into ``(start, end, precision)``.

    Ranges keep both bounds and are ``approximate``; a single year marked as
    approximate (约/約/前后/左右) stays ``approximate``; a bare single year is
    ``exact``.  Never silently drops to the first digit.
    """
    raw = str(text or "")
    numbers = [int(m) for m in _YEAR_RE.findall(raw)]
    numbers = [n for n in numbers if 1 <= n <= 3000]
    if not numbers:
        return default
    approx = any(token in raw for token in ("约", "約", "前后", "後", "左右", "之际", "間", "之际"))
    if len(numbers) >= 2:
        return min(numbers), max(numbers), "approximate"
    year = numbers[0]
    return year, year, "approximate" if approx else "exact"


def _cnk_year_range(activity: dict[str, object]) -> tuple[int, int, str] | None:
    """Year range/precision for a BiographyActivityItem (Year/OldYear text)."""
    year = activity.get("Year")
    if isinstance(year, bool):
        year = None
    elif isinstance(year, (int, float)):
        year = int(year)
    if isinstance(year, int) and 1 <= year <= 3000:
        return year, year, "exact"
    for key in ("Year", "year", "Date", "OldYear", "oldYear"):
        text = _plain_text(activity.get(key))
        if text:
            parsed = _parse_year_range(text)
            if parsed is not None:
                return parsed
    return None


def _cnk_year(activity: dict[str, object]) -> int | None:
    parsed = _cnk_year_range(activity)
    return parsed[0] if parsed is not None else None


def extract_cnkgraph_traces(
    payload: object, poet: str = ""
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """Parse the live Traces/Markers/Detail payload into B-grade candidates.

    Embedded poems whose ``.poemAuthor`` names a *different* author are evidence
    pollution (the biography detail can embed 张说/韩愈/苏辙 etc. works) and are
    dropped when the target ``poet`` is given and the author clearly does not
    match (traditional/simplified tolerant).  Poems with no author are kept for
    review since they are usually 组诗 continuation rows.
    """
    person_events: list[dict[str, object]] = []
    works: list[dict[str, object]] = []
    for marker_index, marker in enumerate(_cnkgraph_markers(payload)):
        detail = marker.get("Detail")
        if not isinstance(detail, str) or not detail.strip():
            continue
        marker_title = _plain_text(marker.get("Title"))
        region_id = _plain_text(marker.get("RegionId"))
        marker_key = "|".join(part for part in (region_id, marker_title) if part)
        if not marker_key:
            marker_key = "marker"
        for row in parse_marker_detail(detail):
            begin = row.get("begin")
            if begin is None:
                continue
            begin = int(begin)
            end = int(row.get("end") or begin)
            label_id = str(row.get("label_id") or "")
            row_index = int(row.get("row_index") or 0)
            summary = str(row.get("summary") or "")
            locator = f"Marker[{marker_index}|{region_id}|{marker_title}] label={label_id} row={row_index} {begin}-{end}"
            # B-grade person_event needs a non-empty summary, Marker.Title,
            # RegionId and valid coordinates.  A poem-only row may still yield a
            # work below but produces no event.
            if (
                marker_title
                and summary
                and region_id
                and _valid_latitude(marker.get("Latitude"))
                and _valid_longitude(marker.get("Longitude"))
            ):
                person_events.append(
                    {
                        "year_start": begin,
                        "year_end": end,
                        "year_precision": "exact" if begin == end else "approximate",
                        "historical_place": marker_title,
                        "event_text": summary,
                        "event_hash": str(row.get("event_hash") or ""),
                        "row_index": row_index,
                        "category": "trace",
                        "source_locator": locator,
                        "marker_key": marker_key,
                        "marker_index": marker_index,
                        "label_id": label_id,
                        "region_id": region_id,
                        "latitude": marker.get("Latitude"),
                        "longitude": marker.get("Longitude"),
                        "index": None,
                        "grade": "B",
                        "method": "cnkgraph_biography_traces_v1",
                    }
                )
            for poem in row.get("poems", []):
                source_author = str(poem.get("source_author") or "")
                if poet and source_author and not _ch_name_matches(poet, source_author):
                    continue
                works.append(
                    {
                        "year_start": int(poem["year_start"]),
                        "year_end": int(poem["year_end"]),
                        "year_precision": str(poem.get("year_precision") or "exact"),
                        "poem_title": str(poem["title"]),
                        "writing_id": str(poem.get("writing_id") or ""),
                        "author_date": str(poem.get("author_date") or ""),
                        "source_author": source_author,
                        "source_locator": f"{locator} Poems[{poem.get('writing_id') or poem.get('title')}]",
                        "index": None,
                        "grade": "B",
                        "method": "cnkgraph_biography_traces_v1",
                    }
                )
    return person_events, works


_CNKGRAPH_CANDIDATE_METADATA_FIELDS = (
    "source_url",
    "access_level",
    "source_grade",
    "license",
    "license_note",
)


def _cnkgraph_candidate_source_metadata(grade: str) -> dict[str, object]:
    """Copy canonical CNKGraph metadata, allowing documented grade downgrades."""
    metadata = {
        field: CNKGRAPH_SOURCE_METADATA[field]
        for field in _CNKGRAPH_CANDIDATE_METADATA_FIELDS
    }
    metadata["source_grade"] = grade
    return metadata


def make_cnkgraph_event_candidate(
    poet: str, event: dict[str, object], person_id: object, cache_key: str, url: str
) -> dict[str, object]:
    start = int(event["year_start"])
    end = int(event["year_end"])
    place = str(event["historical_place"])
    grade = str(event.get("grade") or CNKGRAPH_SOURCE_METADATA["source_grade"])
    method = str(event.get("method") or "cnkgraph_biography_api_v1")
    # Stable identity: person/place/years/grade/method plus marker/activity
    # identity and the full-text digest (event_hash), NOT the truncated 120-char
    # summary.  Two events whose summaries share the first 120 chars but differ
    # later must not collapse into one.  The human-readable locator is
    # deliberately NOT part of the id.
    identity = str(event.get("event_hash") or event.get("event_text") or "")
    candidate_id = deterministic_id(
        poet,
        "cnkgraph",
        "person_event",
        person_id,
        start,
        end,
        place,
        grade,
        method,
        event.get("marker_key") or event.get("category") or "",
        identity,
        event.get("index"),
    )
    note = f"CNKGraph传记{event.get('category') or '活动'}：{event.get('event_text') or ''}；地点{place}（{start}-{end}）"
    return {
        "candidate_id": candidate_id,
        "poet": poet,
        "event_type": "person_event",
        "source": "cnkgraph",
        "year_start": start,
        "year_end": end,
        "year_precision": event.get("year_precision", "exact"),
        "historical_place": place,
        "event_text": str(event.get("event_text") or ""),
        "event_hash": str(event.get("event_hash") or ""),
        "region_id": str(event.get("region_id") or ""),
        "latitude": event.get("latitude"),
        "longitude": event.get("longitude"),
        "source_name": "古籍文献知识图谱（CNKGraph）Biography API",
        "source_pages": str(event.get("source_locator") or ""),
        "source_note": note,
        **_cnkgraph_candidate_source_metadata(grade),
        "cnkgraph_person_id": str(person_id or ""),
        "status": "needs_review",
        "raw_cache_key": cache_key,
        "extraction_method": method,
        "collected_at": utc_now(),
        "reviewer": "",
        "review_note": "",
        "reviewed_at": "",
    }


def cnkgraph_ambiguous_source_titles(works: list[dict[str, object]]) -> set[str]:
    """Titles with more than one *distinct* source work in one payload.

    A poet can have several same-titled works in the source (different WritingId;
    fall back to the source locator when the id is missing).  Linking all of them
    to the single local same-titled poem would pollute its year claims, so every
    work carrying such a title must stay unlinked.
    """
    groups: dict[str, set[str]] = {}
    for work in works:
        key = normalize_title(work.get("poem_title"))
        if not key:
            continue
        identity = str(work.get("writing_id") or work.get("source_locator") or "")
        groups.setdefault(key, set()).add(identity)
    return {key for key, identities in groups.items() if len(identities) > 1}


def make_cnkgraph_work_candidate(
    poet: str,
    work: dict[str, object],
    person_id: object,
    cache_key: str,
    url: str,
    poem_index: dict[str, dict[str, list[dict[str, object]]]] | None = None,
    ambiguous_titles: set[str] | None = None,
) -> dict[str, object]:
    start = int(work["year_start"])
    end = int(work["year_end"])
    raw_title = str(work["poem_title"])
    writing_id = str(work.get("writing_id") or "")
    source_author = str(work.get("source_author") or "")
    grade = str(work.get("grade") or CNKGRAPH_SOURCE_METADATA["source_grade"])
    method = str(work.get("method") or "cnkgraph_biography_api_v1")
    # An unverified (empty) source author downgrades the work to C and blocks
    # auto-linking -- the piece is kept for manual authorship review.
    if not source_author:
        grade = "C"
    # Link only when the source title is unique *and* the local same-author title
    # is unique.  A source title shared by several works (different WritingId)
    # must never be auto-linked to a single local poem.
    title_norm = normalize_title(raw_title)
    source_ambiguous = bool(ambiguous_titles) and title_norm in ambiguous_titles
    matches = find_matching_poems(poet, raw_title, poem_index) if poem_index else []
    if not source_ambiguous and source_author and len(matches) == 1:
        poem = matches[0]
        body_hash = poem_body_hash(poem)
        poem_title = str(poem.get("title") or raw_title)
        linked = True
    else:
        body_hash = ""
        poem_title = raw_title
        linked = False
    candidate_id = deterministic_id(
        poet,
        "cnkgraph",
        "work_chronology",
        person_id,
        start,
        poem_title,
        body_hash,
        writing_id,
        work.get("index"),
    )
    note = f"CNKGraph传记系年：{poet}《{raw_title}》{start}-{end}年（不得据此推断创作地）"
    if source_ambiguous:
        note += "；源端同题多作，未自动关联"
    elif not linked:
        note += "；未匹配语料，body_hash 置空（unlinked）"
    if not source_author:
        note += "；作者未标注，归属待人工复核"
    return {
        "candidate_id": candidate_id,
        "poet": poet,
        "event_type": "work_chronology",
        "source": "cnkgraph",
        "poem_title": poem_title,
        "source_title": raw_title,
        "source_author": source_author,
        "author_date": str(work.get("author_date") or ""),
        "writing_id": writing_id,
        "source_title_ambiguous": source_ambiguous,
        "body_hash": body_hash,
        "linked": linked,
        "year_start": start,
        "year_end": end,
        "year_precision": work.get("year_precision", "exact"),
        "precision": "year",
        "historical_place": "",
        "source_name": "古籍文献知识图谱（CNKGraph）Biography API",
        "source_pages": str(work.get("source_locator") or ""),
        "source_note": note,
        **_cnkgraph_candidate_source_metadata(grade),
        "cnkgraph_person_id": str(person_id or ""),
        "status": "needs_review",
        "raw_cache_key": cache_key,
        "extraction_method": method,
        "collected_at": utc_now(),
        "reviewer": "",
        "review_note": "",
        "reviewed_at": "",
    }


def collect_cnkgraph(
    poet: str,
    client: HttpCacheClient,
    *,
    poem_index: dict[str, dict[str, list[dict[str, object]]]] | None = None,
    registry_entry: dict[str, object] | None = None,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    index = poem_index if poem_index is not None else build_poem_index()
    source_entry = _registry_source(registry_entry, "cnkgraph")
    author_name = str(source_entry.get("author_name") or poet).strip()
    url = f"{CNKGRAPH_BIOGRAPHY_API}?Author={quote(author_name)}"
    result, payload = client.get_json(url, respect_robots=False)
    stat_url = f"{CNKGRAPH_WRITING_STAT_API}?Author={quote(author_name)}"
    stat_result, stat_payload = client.get_json(stat_url, respect_robots=False)

    def stat_record_count(value: object) -> int:
        if isinstance(value, list):
            return len(value)
        if isinstance(value, dict):
            for key in ("Data", "data", "Items", "items", "Rows", "rows", "Result", "result"):
                nested = value.get(key)
                if isinstance(nested, list):
                    return len(nested)
            return len(value)
        return 0

    def stat_references(value: object) -> list[str]:
        found: list[str] = []

        def walk(node: object) -> None:
            if isinstance(node, dict):
                for child in node.values():
                    walk(child)
            elif isinstance(node, list):
                for child in node:
                    walk(child)
            elif isinstance(node, str) and ("csv" in node.casefold() or node.startswith("http")):
                if node not in found:
                    found.append(node)

        walk(value)
        return found[:20]

    if stat_result.status_code == 204:
        stat_status = "not_covered"
    elif stat_result.status == "ok" and stat_payload is not None:
        stat_status = "collected"
    else:
        stat_status = stat_result.status
    status = {
        "poet": poet,
        "source": "cnkgraph",
        "status": "ok",
        "source_url": result.url,
        "note": result.note,
        "candidates": 0,
        "author_name": author_name,
        "writing_stat_status": stat_status,
        "writing_stat_url": stat_result.url or stat_url,
        "writing_stat_cache_key": stat_result.cache_key,
        "writing_stat_records": stat_record_count(stat_payload),
        "writing_stat_references": stat_references(stat_payload),
        "checked_at": utc_now(),
    }
    if result.status_code == 204:
        status["status"] = "not_covered"
        status["note"] = "CNKGraph Biography returned HTTP 204 for this author"
        return [], status
    if result.status == "offline_cache_miss":
        status["status"] = "offline_cache_miss"
        status["note"] = "offline mode; no cached response for this query"
        return [], status
    if result.status == "blocked_by_policy":
        status["status"] = "blocked_by_policy"
        status["note"] = result.note or "login or captcha page detected"
        return [], status
    if result.status == "fetch_failed":
        status["status"] = "fetch_failed"
        status["note"] = result.note or "fetch failed after retries (timeout / HTTP error)"
        return [], status
    if result.status == "parse_failed" or payload is None:
        status["status"] = "no_content"
        status["note"] = result.note or "empty or non-JSON response (e.g., HTTP 204)"
        return [], status
    if result.status != "ok":
        status["status"] = "fetch_failed"
        status["note"] = result.note or result.status
        return [], status
    person_id = ""
    if _has_trace_structure(payload):
        # Real Biography payload: Traces/Markers/Detail (B grade, structural).
        person_events, works = extract_cnkgraph_traces(payload, poet=poet)
    else:
        bio, person_events, works = extract_cnkgraph_biography(payload, poet=poet)
        person_id = bio.get("Id") if isinstance(bio, dict) else ""
    candidates: list[dict[str, object]] = []
    for event in person_events:
        candidates.append(make_cnkgraph_event_candidate(poet, event, person_id, result.cache_key, result.url))
    ambiguous_titles = cnkgraph_ambiguous_source_titles(works)
    for work in works:
        candidates.append(
            make_cnkgraph_work_candidate(
                poet, work, person_id, result.cache_key, result.url,
                poem_index=index, ambiguous_titles=ambiguous_titles,
            )
        )
    status["candidates"] = len(candidates)
    status["status"] = "collected" if candidates else "empty"
    status["note"] = (
        f"{len(person_events)} person events, {len(works)} works"
        + (f"; {len(ambiguous_titles)} ambiguous source titles" if ambiguous_titles else "")
    )
    return candidates, status


# --------------------------------------------------------------------------- #
# Outputs: upsert + atomic writes
# --------------------------------------------------------------------------- #

def upsert_rows(existing: list[dict[str, object]], incoming: list[dict[str, object]]) -> list[dict[str, object]]:
    """Merge by candidate_id; a reviewer decision on an existing id is kept."""
    merged: dict[str, dict[str, object]] = {}
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
        merged[candidate_id] = {**previous, **row}
        for field in REVIEWER_FIELDS:
            merged[candidate_id][field] = previous.get(field) or merged[candidate_id].get(field)
    return [merged[candidate_id] for candidate_id in order]


def upsert_status(existing: list[dict[str, object]], incoming: list[dict[str, object]]) -> list[dict[str, object]]:
    """Per (poet, source) status upsert; the latest run wins."""
    merged: dict[tuple[str, str], dict[str, object]] = {}
    order: list[tuple[str, str]] = []
    for row in [*existing, *incoming]:
        key = (str(row.get("poet") or ""), str(row.get("source") or ""))
        if key not in merged:
            order.append(key)
        # Replace the whole status row.  Merging dictionaries leaves stale
        # run-specific fields such as failed_page on a later successful run.
        merged[key] = dict(row)
    return [merged[key] for key in order]


def _preserve_fetch_candidate_counts(
    status_rows: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Copy a present fetch-local count without inventing the optional field."""
    prepared: list[dict[str, object]] = []
    for source_row in status_rows:
        row = dict(source_row)
        if "candidates" in row and "last_fetch_candidates" not in row:
            row["last_fetch_candidates"] = row["candidates"]
        prepared.append(row)
    return prepared


def _reconcile_status_candidate_counts(
    status_rows: list[dict[str, object]],
    event_rows: list[dict[str, object]],
    work_rows: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Replace fetch-local counts with final, de-duplicated scope counts.

    Collectors report how many rows the latest response parsed.  Candidate files
    are subsequently upserted by ``candidate_id`` and may retain rows from an
    earlier successful fetch, so that fetch-local number is not a disk-snapshot
    count.  ``write_outputs`` preserves that input separately before this helper
    makes ``candidates`` describe the merged files used by coverage.
    """
    scope_counts = Counter(
        (str(row.get("poet") or ""), str(row.get("source") or ""))
        for row in [*event_rows, *work_rows]
    )
    reconciled: list[dict[str, object]] = []
    for source_row in status_rows:
        row = dict(source_row)
        scope = (str(row.get("poet") or ""), str(row.get("source") or ""))
        row["candidates"] = scope_counts.get(scope, 0)
        reconciled.append(row)
    return reconciled


def _work_is_linked(row: dict[str, object]) -> bool:
    if "linked" in row:
        return bool(row.get("linked"))
    # Legacy sou-yun rows predate the explicit linked flag: a non-empty body_hash
    # means the work was matched to the local corpus.
    return bool(row.get("body_hash"))


def _work_is_ambiguous(row: dict[str, object]) -> bool:
    return bool(row.get("source_title_ambiguous"))


def _event_is_locatable(row: dict[str, object]) -> bool:
    """Whether an event already carries a valid point usable by a route map."""
    return _valid_latitude(row.get("latitude")) and _valid_longitude(row.get("longitude"))


def _coverage_scope_is_stale(source: str, status: dict[str, object]) -> bool:
    """Whether retained candidates are audit-only under current identity state."""
    return source == "souyun" and str(status.get("status") or "") in _SOUYUN_FRESH_IDENTITY_BLOCKERS


def build_coverage(
    status_rows: list[dict[str, object]],
    event_rows: list[dict[str, object]],
    work_rows: list[dict[str, object]],
    poets: list[str] | None = None,
) -> dict[str, object]:
    poets = poets or list(CORE_POETS)
    poet_set = set(poets)
    selected_status = [row for row in status_rows if str(row.get("poet") or "") in poet_set]
    selected_events = [row for row in event_rows if str(row.get("poet") or "") in poet_set]
    selected_works = [row for row in work_rows if str(row.get("poet") or "") in poet_set]
    latest: dict[tuple[str, str], dict[str, object]] = {}
    for row in selected_status:
        latest[(str(row.get("poet") or ""), str(row.get("source") or ""))] = row

    def scope_works(poet: str, source: str) -> list[dict[str, object]]:
        return [row for row in selected_works if row.get("poet") == poet and row.get("source") == source]

    per_poet: dict[str, object] = {}
    for poet in poets:
        per: dict[str, object] = {}
        for source in SOURCES:
            status = latest.get((poet, source)) or {}
            scope_events = [
                row for row in selected_events
                if row.get("poet") == poet and row.get("source") == source
            ]
            events = len(scope_events)
            works = scope_works(poet, source)
            stale = _coverage_scope_is_stale(source, status)
            active_events = [] if stale else scope_events
            active_works = [] if stale else works
            locatable_events = sum(1 for row in active_events if _event_is_locatable(row))
            linked = sum(1 for row in active_works if _work_is_linked(row))
            unlinked = sum(1 for row in active_works if not _work_is_linked(row))
            ambiguous = sum(1 for row in active_works if _work_is_ambiguous(row))
            per[source] = {
                "status": status.get("status", "not_collected"),
                "note": status.get("note", ""),
                "candidates": events + len(works),
                "event_candidates": events,
                "locatable_event_candidates": locatable_events,
                "unlocated_event_candidates": len(active_events) - locatable_events,
                "work_candidates": len(works),
                "linked_work_candidates": linked,
                "unlinked_work_candidates": unlinked,
                "ambiguous_work_candidates": ambiguous,
                "reviewable_candidates": len(active_events) + linked,
                "stale_candidate_count": events + len(works) if stale else 0,
            }
            if source == "cnkgraph":
                per[source].update(
                    {
                        "writing_stat_status": status.get("writing_stat_status", "not_collected"),
                        "writing_stat_url": status.get("writing_stat_url", ""),
                        "writing_stat_cache_key": status.get("writing_stat_cache_key", ""),
                        "writing_stat_records": status.get("writing_stat_records", 0),
                        "writing_stat_references": status.get("writing_stat_references", []),
                    }
                )
        per_poet[poet] = per
    stale_scopes = {
        (poet, source)
        for (poet, source), status in latest.items()
        if _coverage_scope_is_stale(source, status)
    }
    active_events = [
        row for row in selected_events
        if (str(row.get("poet") or ""), str(row.get("source") or "")) not in stale_scopes
    ]
    active_works = [
        row for row in selected_works
        if (str(row.get("poet") or ""), str(row.get("source") or "")) not in stale_scopes
    ]
    linked_works = sum(1 for row in active_works if _work_is_linked(row))
    unlinked_works = sum(1 for row in active_works if not _work_is_linked(row))
    ambiguous_works = sum(1 for row in active_works if _work_is_ambiguous(row))
    locatable_events = sum(1 for row in active_events if _event_is_locatable(row))
    stale_candidate_count = (
        len(selected_events) + len(selected_works) - len(active_events) - len(active_works)
    )
    source_summary: dict[str, object] = {}
    for source in SOURCES:
        statuses = [str(per_poet[poet][source]["status"]) for poet in poets]
        counts = Counter(statuses)
        ambiguous = sum(
            count
            for status, count in counts.items()
            if "ambiguous" in status or "disambiguation" in status
        )
        missing = sum(
            count for status, count in counts.items()
            if status in {
                "not_collected",
                "unsupported",
                "identity_not_found",
                "identity_unresolved",
                "not_covered",
            }
        )
        successful = sum(count for status, count in counts.items() if status in REFRESH_SUCCESS_STATUSES)
        failed = len(poets) - successful - ambiguous - missing
        source_summary[source] = {
            "status_counts": dict(sorted(counts.items())),
            "successful_poets": successful,
            "missing_poets": missing,
            "ambiguous_poets": ambiguous,
            "failed_poets": failed,
        }
        if source == "cnkgraph":
            stat_counts = Counter(
                str(per_poet[poet][source].get("writing_stat_status") or "not_collected")
                for poet in poets
            )
            source_summary[source]["writing_stat_status_counts"] = dict(sorted(stat_counts.items()))
    return {
        "schema_version": COVERAGE_SCHEMA_VERSION,
        "generated_at": utc_now(),
        "sources": list(SOURCES),
        "poets": poets,
        "per_poet": per_poet,
        "source_summary": source_summary,
        "totals": {
            "selected_poets": len(poets),
            "event_candidates": len(selected_events),
            "locatable_event_candidates": locatable_events,
            "unlocated_event_candidates": len(active_events) - locatable_events,
            "work_candidates": len(selected_works),
            "linked_work_candidates": linked_works,
            "unlinked_work_candidates": unlinked_works,
            "ambiguous_work_candidates": ambiguous_works,
            "reviewable_candidates": len(active_events) + linked_works,
            "stale_candidate_count": stale_candidate_count,
            "candidates": len(selected_events) + len(selected_works),
            "status_lines": len(selected_status),
        },
    }


def _coverage_semantic_content(coverage: dict[str, object]) -> dict[str, object]:
    """Return the deep-comparable snapshot content, excluding its timestamp."""
    return {key: value for key, value in coverage.items() if key != "generated_at"}


def _refresh_scope_rows(old_rows: list[dict[str, object]], new_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    """Refresh a scope: drop stale ids, keep reviewer fields on surviving ids."""
    new_ids = {str(row.get("candidate_id") or "") for row in new_rows}
    keep = [row for row in old_rows if str(row.get("candidate_id") or "") in new_ids]
    return upsert_rows(keep, new_rows)


def _merge_scopes_with_refresh(
    existing: list[dict[str, object]],
    incoming: list[dict[str, object]],
    refresh_scopes: set[tuple[str, str]],
) -> list[dict[str, object]]:
    existing_out = [
        row for row in existing
        if (str(row.get("poet") or ""), str(row.get("source") or "")) not in refresh_scopes
    ]
    merged_out = upsert_rows(existing_out, incoming)
    by_scope: dict[tuple[str, str], list[dict[str, object]]] = {}
    for row in incoming:
        by_scope.setdefault((str(row.get("poet") or ""), str(row.get("source") or "")), []).append(row)
    refreshed: list[dict[str, object]] = []
    for scope in refresh_scopes:
        old = [row for row in existing if (str(row.get("poet") or ""), str(row.get("source") or "")) == scope]
        refreshed.extend(_refresh_scope_rows(old, by_scope.get(scope, [])))
    # refreshed rows carry reviewer decisions on surviving ids; put them first so
    # upsert_rows keeps their reviewer/status fields over the raw new rows.
    return upsert_rows(refreshed, merged_out)


def write_outputs(
    event_rows: list[dict[str, object]],
    work_rows: list[dict[str, object]],
    status_rows: list[dict[str, object]],
    *,
    base_dir: Path = CANDIDATE_DIR,
    refresh_successful: bool = False,
    poets: list[str] | None = None,
) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]], dict[str, object]]:
    """Merge and atomically write candidate/status files plus global coverage.

    ``poets`` is retained as batch-selection context for existing callers.  It
    must not scope the persisted coverage snapshot, which always represents the
    complete corpus after the incoming batch has been merged.
    """
    event_path = base_dir / "journey_event_candidates.jsonl"
    work_path = base_dir / "work_chronology_supplements.jsonl"
    status_path = base_dir / "journey_source_status.jsonl"
    coverage_path = base_dir / "journey_source_coverage.json"

    existing_events = read_jsonl(event_path)
    existing_works = read_jsonl(work_path)
    if refresh_successful:
        refresh_scopes = {
            (str(row.get("poet") or ""), str(row.get("source") or ""))
            for row in status_rows
            if str(row.get("status") or "") in REFRESH_SUCCESS_STATUSES
            and str(row.get("source") or "") != "souyun"
        }
        merged_events = _merge_scopes_with_refresh(existing_events, event_rows, refresh_scopes)
        merged_works = _merge_scopes_with_refresh(existing_works, work_rows, refresh_scopes)
    else:
        merged_events = upsert_rows(existing_events, event_rows)
        merged_works = upsert_rows(existing_works, work_rows)
    existing_status = read_jsonl(status_path)
    previous_coverage: dict[str, object] | None = None
    previous_coverage_schema = 0
    if coverage_path.exists():
        try:
            coverage_payload = json.loads(coverage_path.read_text(encoding="utf-8"))
            if isinstance(coverage_payload, dict):
                previous_coverage = coverage_payload
                previous_coverage_schema = int(coverage_payload.get("schema_version") or 0)
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            previous_coverage_schema = 0
    if previous_coverage_schema < COVERAGE_SCHEMA_VERSION:
        # One-time migration from the old fetch-local ``candidates`` meaning.
        existing_status = _preserve_fetch_candidate_counts(existing_status)
    incoming_status = _preserve_fetch_candidate_counts(status_rows)
    merged_status = upsert_status(existing_status, incoming_status)
    merged_status = _reconcile_status_candidate_counts(merged_status, merged_events, merged_works)

    stable_poets = [profile["poet"] for profile in corpus_poet_profiles()]
    poet_order = {poet: index for index, poet in enumerate(stable_poets)}
    source_order = {source: index for index, source in enumerate(SOURCES)}

    def row_key(row: dict[str, object]) -> tuple[object, ...]:
        year_text = str(row.get("year_start") or "")
        year = int(year_text) if year_text.lstrip("-").isdigit() else 0
        return (
            poet_order.get(str(row.get("poet") or ""), len(poet_order)),
            source_order.get(str(row.get("source") or ""), len(source_order)),
            year,
            str(row.get("candidate_id") or ""),
        )

    merged_events.sort(key=row_key)
    merged_works.sort(key=row_key)
    merged_status.sort(
        key=lambda row: (
            poet_order.get(str(row.get("poet") or ""), len(poet_order)),
            source_order.get(str(row.get("source") or ""), len(source_order)),
        )
    )

    write_jsonl(event_path, merged_events)
    write_jsonl(work_path, merged_works)
    write_jsonl(status_path, merged_status)
    coverage = build_coverage(merged_status, merged_events, merged_works, poets=stable_poets)
    coverage_unchanged = bool(
        previous_coverage is not None
        and "generated_at" in previous_coverage
        and _coverage_semantic_content(previous_coverage) == _coverage_semantic_content(coverage)
    )
    if coverage_unchanged and previous_coverage is not None:
        coverage["generated_at"] = previous_coverage["generated_at"]
    else:
        atomic_write_text(coverage_path, json.dumps(coverage, ensure_ascii=False, indent=2) + "\n")
    return merged_events, merged_works, merged_status, coverage


def run_collection(
    poets: list[str],
    sources: list[str],
    client: HttpCacheClient | None,
    poem_index: dict[str, dict[str, list[dict[str, object]]]] | None = None,
    *,
    max_souyun_pages: int = 1,
    resume: bool = False,
    existing_status: list[dict[str, object]] | None = None,
    registry: dict[str, dict[str, object]] | None = None,
    workers: int = 1,
    source_workers: dict[str, int] | None = None,
    client_factory: Callable[[], HttpCacheClient] | None = None,
    progress: bool = False,
    souyun_transport: str = "api",
) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
    index = poem_index if poem_index is not None else build_poem_index()
    existing_status = existing_status if existing_status is not None else read_jsonl(SOURCE_STATUS_JSONL)
    previous = {(str(row.get("poet") or ""), str(row.get("source") or "")): row for row in existing_status}
    registry = registry or {}
    workers = max(1, int(workers))
    if workers > 1 and client_factory is None:
        raise ValueError("parallel collection requires client_factory so requests.Session is never shared")
    if client is None and client_factory is None:
        raise ValueError("client or client_factory is required")
    caps = {source: workers for source in SOURCES}
    caps.update({source: max(1, int(value)) for source, value in (source_workers or {}).items()})
    source_slots = {source: threading.BoundedSemaphore(caps[source]) for source in SOURCES}
    tasks: list[tuple[int, str, str]] = []
    for poet in poets:
        for source in sources:
            key = (poet, source)
            prev = previous.get(key)
            registry_blocked = source == "souyun" and bool(_souyun_registry_blocker(registry.get(poet)))
            if resume and not registry_blocked and _resume_skip(source, prev, max_souyun_pages):
                continue
            tasks.append((len(tasks), poet, source))

    def execute(poet: str, source: str) -> tuple[list[dict[str, object]], dict[str, object]]:
        entry = registry.get(poet)
        if source == "souyun":
            blocker_status = _souyun_registry_blocker_status(
                poet,
                entry,
                max_pages=max_souyun_pages,
                transport=souyun_transport,
            )
            if blocker_status is not None:
                return [], blocker_status
        task_client = client_factory() if client_factory is not None else client
        assert task_client is not None
        with source_slots[source]:
            if source == "cbdb":
                return collect_cbdb(poet, task_client, registry_entry=entry)
            elif source == "souyun":
                return collect_souyun(
                    poet,
                    task_client,
                    max_pages=max_souyun_pages,
                    poem_index=index,
                    registry_entry=entry,
                    transport=souyun_transport,
                )
            elif source == "cnkgraph":
                return collect_cnkgraph(poet, task_client, poem_index=index, registry_entry=entry)
        return [], {
            "poet": poet,
            "source": source,
            "status": "unsupported",
            "note": "unknown source",
            "candidates": 0,
            "checked_at": utc_now(),
        }

    completed: dict[int, tuple[list[dict[str, object]], dict[str, object]]] = {}
    if workers == 1:
        for done, (position, poet, source) in enumerate(tasks, start=1):
            try:
                completed[position] = execute(poet, source)
            except Exception as exc:  # one source scope must never abort the batch
                completed[position] = ([], {
                    "poet": poet,
                    "source": source,
                    "status": "internal_error",
                    "note": f"{type(exc).__name__}: {exc}",
                    "candidates": 0,
                    "checked_at": utc_now(),
                })
            if progress:
                status = completed[position][1]
                print(f"[{done}/{len(tasks)}] {poet}/{source}: {status.get('status')} ({status.get('candidates', 0)})", flush=True)
    else:
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="journey-source") as pool:
            futures: dict[Future[tuple[list[dict[str, object]], dict[str, object]]], tuple[int, str, str]] = {
                pool.submit(execute, poet, source): (position, poet, source)
                for position, poet, source in tasks
            }
            for done, future in enumerate(as_completed(futures), start=1):
                position, poet, source = futures[future]
                try:
                    completed[position] = future.result()
                except Exception as exc:
                    completed[position] = ([], {
                        "poet": poet,
                        "source": source,
                        "status": "internal_error",
                        "note": f"{type(exc).__name__}: {exc}",
                        "candidates": 0,
                        "checked_at": utc_now(),
                    })
                if progress:
                    status = completed[position][1]
                    print(f"[{done}/{len(tasks)}] {poet}/{source}: {status.get('status')} ({status.get('candidates', 0)})", flush=True)

    event_rows: list[dict[str, object]] = []
    work_rows: list[dict[str, object]] = []
    status_rows: list[dict[str, object]] = []
    for position, _, _ in tasks:
        candidates, status = completed[position]
        for candidate in candidates:
            if candidate.get("event_type") == "work_chronology":
                work_rows.append(candidate)
            else:
                event_rows.append(candidate)
        status_rows.append(status)

    poet_order = {poet: index for index, poet in enumerate(poets)}
    source_order = {source: index for index, source in enumerate(SOURCES)}

    def candidate_key(row: dict[str, object]) -> tuple[object, ...]:
        return (
            poet_order.get(str(row.get("poet") or ""), len(poet_order)),
            source_order.get(str(row.get("source") or ""), len(source_order)),
            int(row.get("year_start") or 0) if str(row.get("year_start") or "").lstrip("-").isdigit() else 0,
            str(row.get("candidate_id") or ""),
        )

    event_rows.sort(key=candidate_key)
    work_rows.sort(key=candidate_key)
    status_rows.sort(
        key=lambda row: (
            poet_order.get(str(row.get("poet") or ""), len(poet_order)),
            source_order.get(str(row.get("source") or ""), len(source_order)),
        )
    )
    return event_rows, work_rows, status_rows


def _resume_skip(
    source: str,
    previous: dict[str, object] | None,
    max_souyun_pages: int,
) -> bool:
    """Decide whether --resume may skip a (poet, source) pair.

    Sou-yun is only skipped when the earlier run already completed *at least* as
    many pages as the current request and ended fully successfully, so expanding
    --max-souyun-pages always continues to fill the missing pages.  A previous
    full fetch with zero hits still counts as successful completion for the pages
    it did cover, so it never blocks a later page expansion.
    """
    if previous is None:
        return False
    if str(previous.get("status") or "") not in SUCCESS_STATUSES:
        return False
    if source == "souyun":
        if int(max_souyun_pages) == 0:
            return bool(previous.get("pagination_complete"))
        try:
            completed = int(previous.get("pages_completed") or 0)
        except (TypeError, ValueError):
            return False
        return completed >= int(max_souyun_pages)
    return True


# --------------------------------------------------------------------------- #
# Report (read-only, never publishes)
# --------------------------------------------------------------------------- #

def _to_year(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = int(str(value).strip())
    except ValueError:
        return None
    return number if number > 0 else None


def _norm_place(value: object) -> str:
    return re.sub(r"\s+", "", str(value or ""))


def load_reviewed_metrics(poets: list[str]) -> tuple[dict[str, int], dict[str, list[tuple[int, int, str]]]]:
    nodes: dict[str, int] = {}
    windows: dict[str, list[tuple[int, int, str]]] = {}
    data = json.loads(REVIEWED_JOURNEYS.read_text(encoding="utf-8"))
    for poet_entry in data.get("poets", []):
        name = str(poet_entry.get("poet") or "")
        if name not in poets:
            continue
        nodes[name] = len(poet_entry.get("nodes", []))
        windows[name] = []
        for node in poet_entry.get("nodes", []):
            year = node.get("year")
            if isinstance(year, (int, float)):
                windows[name].append((int(year), int(year), str(node.get("place_historical") or "")))
    return nodes, windows


def load_chronology_counts(poets: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for poet in poets:
        slug = SLUGS.get(poet)
        if not slug:
            counts[poet] = 0
            continue
        path = CANDIDATE_DIR / f"{slug}_spirit_chronology.csv"
        count = 0
        if path.exists():
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                count = sum(1 for _ in csv.DictReader(handle))
        counts[poet] = count
    return counts


def load_chronology_windows(poets: list[str]) -> dict[str, list[tuple[int, int, str]]]:
    windows: dict[str, list[tuple[int, int, str]]] = {poet: [] for poet in poets}
    for poet in poets:
        slug = SLUGS.get(poet)
        if not slug:
            continue
        # Only the six main spirit-chronology CSV files count as reviewed rows;
        # split/partial files (e.g. libai p2-p5) are excluded from the baseline.
        path = CANDIDATE_DIR / f"{slug}_spirit_chronology.csv"
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                start = _to_year(row.get("year_start"))
                end = _to_year(row.get("year_end"))
                if start is None and end is None:
                    continue
                windows[poet].append((start or end, end or start, str(row.get("historical_place") or "")))
    return windows


def load_candidate_metrics(poets: list[str]) -> tuple[dict[str, object], dict[str, list[dict[str, object]]]]:
    events = read_jsonl(EVENT_CANDIDATES_JSONL)
    works = read_jsonl(WORK_SUPPLEMENTS_JSONL)
    metrics: dict[str, object] = {
        poet: {
            "event_new": 0,
            "work_new": 0,
            "linked_work_candidates": 0,
            "unlinked_work_candidates": 0,
            "ambiguous_work_candidates": 0,
            "source_counts": Counter(),
        }
        for poet in poets
    }
    cand_rows: dict[str, list[dict[str, object]]] = {poet: [] for poet in poets}
    for row in [*events, *works]:
        poet = str(row.get("poet") or "")
        if poet not in metrics:
            continue
        metric = metrics[poet]
        metric["source_counts"][str(row.get("source") or "?")] += 1
        if row.get("event_type") == "work_chronology":
            # Effective supplement / review metrics only count linked works;
            # unlinked/ambiguous works are kept as noise to triage separately.
            if _work_is_linked(row):
                metric["linked_work_candidates"] += 1
                if row.get("status") == "needs_review":
                    metric["work_new"] += 1
            else:
                metric["unlinked_work_candidates"] += 1
            if _work_is_ambiguous(row):
                metric["ambiguous_work_candidates"] += 1
        elif row.get("status") == "needs_review":
            metric["event_new"] += 1
        cand_rows[poet].append(row)
    return metrics, cand_rows


def _overlap(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return not (a[1] < b[0] or b[1] < a[0])


def compute_conflicts_and_gaps(
    windows: list[tuple[int, int, str]], candidates: list[dict[str, object]]
) -> tuple[int, int]:
    conflicts = 0
    gaps = 0
    for candidate in candidates:
        # Conflicts/gaps reflect effective evidence only: every event candidate,
        # plus work candidates that are actually linked to the local corpus.
        if candidate.get("event_type") == "work_chronology" and not _work_is_linked(candidate):
            continue
        start = _to_year(candidate.get("year_start"))
        end = _to_year(candidate.get("year_end"))
        if start is None and end is None:
            continue
        y0, y1 = start or end, end or start
        overlaps = [w for w in windows if _overlap((y0, y1), (w[0], w[1]))]
        if overlaps:
            if candidate.get("historical_place"):
                reviewed_places = {_norm_place(w[2]) for w in overlaps if w[2]}
                candidate_place = _norm_place(candidate.get("historical_place"))
                if reviewed_places and candidate_place and candidate_place not in reviewed_places:
                    conflicts += 1
        else:
            gaps += 1
    return conflicts, gaps


def compute_report(poets: list[str]) -> dict[str, dict[str, object]]:
    reviewed_nodes, node_windows = load_reviewed_metrics(poets)
    chronology_counts = load_chronology_counts(poets)
    chronology_windows = load_chronology_windows(poets)
    metrics, cand_rows = load_candidate_metrics(poets)
    result: dict[str, dict[str, object]] = {}
    for poet in poets:
        windows = [*node_windows.get(poet, []), *chronology_windows.get(poet, [])]
        conflicts, gaps = compute_conflicts_and_gaps(windows, cand_rows.get(poet, []))
        metric = metrics[poet]
        result[poet] = {
            "reviewed_nodes": reviewed_nodes.get(poet, 0),
            "chronology_rows": chronology_counts.get(poet, 0),
            "new_event_candidates": metric["event_new"],
            "new_work_candidates": metric["work_new"],
            "linked_work_candidates": metric["linked_work_candidates"],
            "unlinked_work_candidates": metric["unlinked_work_candidates"],
            "ambiguous_work_candidates": metric["ambiguous_work_candidates"],
            "reviewable_candidates": metric["event_new"] + metric["work_new"],
            "conflicts": conflicts,
            "priority_gaps": gaps,
            "source_counts": dict(sorted(metric["source_counts"].items())),
        }
    return result


def print_report(result: dict[str, dict[str, object]]) -> None:
    header = (
        f"{'诗人':<6}{'reviewed':>9}{'chrono':>8}{'new_event':>11}{'new_work':>10}"
        f"{'reviewable':>11}{'conflict':>10}{'gaps':>7}  sources"
    )
    print(header)
    print("-" * len(header))
    for poet, metric in result.items():
        sources = ",".join(f"{k}:{v}" for k, v in metric["source_counts"].items())
        print(
            f"{poet:<7}{metric['reviewed_nodes']:>9}{metric['chronology_rows']:>8}"
            f"{metric['new_event_candidates']:>11}{metric['new_work_candidates']:>10}"
            f"{metric['reviewable_candidates']:>11}{metric['conflicts']:>10}{metric['priority_gaps']:>7}  {sources}"
        )
    print("\n[work 拆分]")
    for poet, metric in result.items():
        print(
            f"  {poet:<7}linked={metric['linked_work_candidates']:<5}"
            f"unlinked={metric['unlinked_work_candidates']:<5}"
            f"ambiguous={metric['ambiguous_work_candidates']}"
        )
    print(
        "\n说明：new_work/reviewable/conflicts/priority_gaps 只计 linked works（有效补充），"
        "unlinked/ambiguous 另列待人工分流；本报告只读，不自动发布/审批任何候选。"
    )


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def parse_poets(arg: str | None, scope: str = "core") -> list[str]:
    explicit = [name.strip() for name in arg.split(",") if name.strip()] if arg is not None else None
    try:
        return resolve_poets(scope, explicit)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc


def parse_sources(arg: str) -> list[str]:
    sources = [name.strip() for name in str(arg).split(",") if name.strip()]
    unknown = [name for name in sources if name not in SOURCES]
    if unknown:
        raise SystemExit(f"unknown source(s): {', '.join(unknown)}; allowed: {', '.join(SOURCES)}")
    return sources


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="journey_source_pipeline", description="行旅史料采集器（候选层优先）")
    subparsers = parser.add_subparsers(dest="command", required=True)

    collect = subparsers.add_parser("collect", help="采集 CBDB/搜韵/CNKGraph 候选并落盘")
    collect.add_argument("--scope", choices=("core", "all"), default="core", help="默认六人或语料全部诗人")
    collect.add_argument("--sources", default="cbdb,souyun,cnkgraph", help="逗号分隔来源")
    collect.add_argument("--poets", default=None, help="逗号分隔诗人；显式名单优先于 --scope")
    collect.add_argument("--max-souyun-pages", type=int, default=1, help="搜韵最多页数；0=自动至空/重复/计数完成，单诗人硬上限500")
    collect.add_argument("--resume", action="store_true", help="跳过已完成(ok/collected)的(诗人,来源)对")
    collect.add_argument(
        "--refresh-successful-scopes",
        action="store_true",
        help="对本次成功(ok/collected/empty/no_usable_records)的CBDB/CNKGraph范围："
        "先清退旧候选再写新候选；搜韵及partial/失败永不清退；默认保持 upsert",
    )
    collect.add_argument("--offline", action="store_true", help="只读缓存，不发起网络请求")
    collect.add_argument("--timeout", type=float, default=20.0)
    collect.add_argument("--retries", type=int, default=3, help="每个HTTP请求最多尝试次数；0仍至少尝试1次")
    collect.add_argument("--delay-min", type=float, default=1.5)
    collect.add_argument("--delay-max", type=float, default=3.0)
    default_workers = min(16, max(4, os.cpu_count() or 4))
    collect.add_argument("--workers", type=int, default=default_workers, help="全局任务池并发")
    collect.add_argument("--cbdb-workers", type=int, default=4, help="CBDB API 最大并发")
    collect.add_argument("--cnkgraph-workers", type=int, default=3, help="CNKGraph 最大任务并发")
    collect.add_argument("--souyun-workers", type=int, default=1, help="搜韵固定为1，避免触发限流")
    collect.add_argument(
        "--souyun-transport",
        choices=("api", "html"),
        default="api",
        help="默认官方 open/Poem API；html 仅兼容旧fixture/诊断",
    )

    subparsers.add_parser("check", help="运行离线 fixture 测试")

    report = subparsers.add_parser("report", help="对比已审核数据生成只读报告")
    report.add_argument("--scope", choices=("core", "all"), default="core")
    report.add_argument("--poets", default=None, help="逗号分隔诗人；显式名单优先")
    return parser


def _validate_collect_args(args: argparse.Namespace) -> None:
    problems: list[str] = []
    if args.max_souyun_pages < 0:
        problems.append(f"--max-souyun-pages must be >= 0, got {args.max_souyun_pages}")
    if args.timeout <= 0:
        problems.append(f"--timeout must be > 0, got {args.timeout}")
    if args.retries < 0:
        problems.append(f"--retries must be >= 0, got {args.retries}")
    if args.delay_min <= 0:
        problems.append(f"--delay-min must be > 0, got {args.delay_min}")
    if args.delay_max <= 0:
        problems.append(f"--delay-max must be > 0, got {args.delay_max}")
    if args.delay_max < args.delay_min:
        problems.append(f"--delay-max ({args.delay_max}) must be >= --delay-min ({args.delay_min})")
    for option in ("workers", "cbdb_workers", "cnkgraph_workers", "souyun_workers"):
        value = int(getattr(args, option, 1))
        if value <= 0:
            problems.append(f"--{option.replace('_', '-')} must be > 0, got {value}")
    if int(getattr(args, "souyun_workers", 1)) != 1:
        problems.append("--souyun-workers must be 1 (shared host safety limit)")
    if problems:
        raise SystemExit("invalid arguments:\n  " + "\n  ".join(problems))


def collect_main(args: argparse.Namespace) -> int:
    _validate_collect_args(args)
    poets = parse_poets(args.poets, args.scope)
    sources = parse_sources(args.sources)
    registry_doc = load_source_registry()
    registry = registry_by_poet(registry_doc)
    gate = SharedHostGate(
        {
            "api.sou-yun.cn": (1, max(2.0, args.delay_min), max(3.0, args.delay_max)),
            "www.sou-yun.cn": (1, max(1.5, args.delay_min), max(3.0, args.delay_max)),
            "sou-yun.cn": (1, max(1.5, args.delay_min), max(3.0, args.delay_max)),
            "open.cnkgraph.com": (
                min(3, args.cnkgraph_workers),
                max(0.25, args.delay_min / 3),
                max(0.75, args.delay_max / 3),
            ),
            "cbdb.fas.harvard.edu": (
                args.cbdb_workers,
                max(0.2, args.delay_min / 4),
                max(0.5, args.delay_max / 4),
            ),
        }
    )

    def client_factory() -> HttpCacheClient:
        return HttpCacheClient(
            cache_dir=JOURNEY_CACHE_DIR,
            timeout=args.timeout,
            retries=args.retries,
            min_delay=0,
            max_delay=0,
            offline=args.offline,
            host_gate=gate,
        )

    event_rows, work_rows, status_rows = run_collection(
        poets,
        sources,
        None,
        max_souyun_pages=args.max_souyun_pages,
        resume=args.resume,
        registry=registry,
        workers=args.workers,
        source_workers={
            "cbdb": args.cbdb_workers,
            "souyun": args.souyun_workers,
            "cnkgraph": args.cnkgraph_workers,
        },
        client_factory=client_factory,
        progress=True,
        souyun_transport=args.souyun_transport,
    )
    merge_souyun_discoveries(registry_doc, status_rows)
    write_source_registry(registry_doc)
    merged_events, merged_works, merged_status, coverage = write_outputs(
        event_rows,
        work_rows,
        status_rows,
        refresh_successful=args.refresh_successful_scopes,
        poets=poets,
    )
    by_source: Counter[str] = Counter()
    for row in [*merged_events, *merged_works]:
        by_source[str(row.get("source") or "?")] += 1
    print(f"poets: {', '.join(poets)}")
    print(
        f"sources: {', '.join(sources)}  (offline={args.offline}, resume={args.resume}, "
        f"refresh_successful={args.refresh_successful_scopes})"
    )
    print(
        f"workers: total={args.workers} cbdb={args.cbdb_workers} "
        f"cnkgraph={args.cnkgraph_workers} souyun={args.souyun_workers}"
    )
    print(f"event candidates: {len(merged_events)}  work candidates: {len(merged_works)}")
    print("by source: " + " ".join(f"{source}={count}" for source, count in sorted(by_source.items())))
    print(f"status lines: {len(merged_status)}")
    print(f"coverage: {COVERAGE_JSON}")
    return 0


def check_main(args: argparse.Namespace) -> int:
    del args
    script = Path(__file__).resolve().parent / "check_journey_source_pipeline.py"
    return subprocess.call([sys.executable, str(script)])


def report_main(args: argparse.Namespace) -> int:
    poets = parse_poets(args.poets, args.scope)
    result = compute_report(poets)
    print_report(result)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "collect":
        return collect_main(args)
    if args.command == "check":
        return check_main(args)
    if args.command == "report":
        return report_main(args)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
