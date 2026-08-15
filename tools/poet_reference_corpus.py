"""Collect open biographical and bibliographical references for the corpus poets.

This collector is deliberately independent from ``journey_source_pipeline``.
It downloads a small, fixed set of repository-level assets once, matches every
poet locally, and writes candidate/reference data only.  A biography or a
catalogue hit is never interpreted as journey evidence.

Allowed outputs:

* data/candidates/poet_reference_biographies.jsonl
* data/candidates/poet_kanripo_catalog_matches.jsonl
* data/candidates/poet_reference_coverage.json
* .cache/poet_reference_corpus/**
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import unicodedata
import urllib.error
import urllib.request
import uuid
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from itertools import product
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence


ROOT = Path(__file__).resolve().parent.parent
POEMS_JSON = ROOT / "data" / "poems.json"
CANDIDATE_DIR = ROOT / "data" / "candidates"
CACHE_DIR = ROOT / ".cache" / "poet_reference_corpus"

BIOGRAPHIES_JSONL = CANDIDATE_DIR / "poet_reference_biographies.jsonl"
KANRIPO_MATCHES_JSONL = CANDIDATE_DIR / "poet_kanripo_catalog_matches.jsonl"
COVERAGE_JSON = CANDIDATE_DIR / "poet_reference_coverage.json"

CORE_POETS = ("李白", "杜甫", "白居易", "苏轼", "陆游", "李清照")
EXPECTED_CORPUS_POETS = 88
SCHEMA_VERSION = 1
PARSER_VERSION = "poet-reference-corpus-v1"

CHINESE_POETRY_LICENSE = "MIT"
CHINESE_POETRY_LICENSE_URL = "https://github.com/chinese-poetry/chinese-poetry/blob/master/LICENSE"
KANRIPO_LICENSE = "CC BY-SA 4.0"
KANRIPO_LICENSE_URL = "https://creativecommons.org/licenses/by-sa/4.0/"


@dataclass(frozen=True)
class PoetSpec:
    name: str
    dynasty: str
    poem_count: int
    dynasty_counts: tuple[tuple[str, int], ...] = ()
    dynasty_resolution: str = "single_local_label"


@dataclass(frozen=True)
class AssetSpec:
    key: str
    source: str
    url: str
    license: str
    license_url: str
    dynasty: str | None = None


@dataclass(frozen=True)
class FetchResult:
    asset: AssetSpec
    usable: bool
    attempt_status: str
    body: bytes = b""
    content_sha256: str = ""
    retrieved_at: str = ""
    from_cache: bool = False
    http_status: int | None = None
    error: str = ""
    cache_path: str = ""


@dataclass(frozen=True)
class CatalogPerson:
    name: str
    dynasty: str
    function: str
    dates: str
    evidence: str


@dataclass(frozen=True)
class CatalogRecord:
    kr_id: str
    heading: str
    title: str
    category: str
    responsibility: str
    dynasties: tuple[str, ...]
    people: tuple[CatalogPerson, ...]
    header_line: str
    responsibility_line: str
    source_asset: AssetSpec
    content_sha256: str
    retrieved_at: str


CHINESE_POETRY_ASSETS: tuple[AssetSpec, ...] = (
    AssetSpec(
        key="authors_tang",
        source="chinese_poetry",
        dynasty="唐",
        url="https://raw.githubusercontent.com/chinese-poetry/chinese-poetry/master/%E5%85%A8%E5%94%90%E8%AF%97/authors.tang.json",
        license=CHINESE_POETRY_LICENSE,
        license_url=CHINESE_POETRY_LICENSE_URL,
    ),
    AssetSpec(
        key="authors_song",
        source="chinese_poetry",
        dynasty="宋",
        url="https://raw.githubusercontent.com/chinese-poetry/chinese-poetry/master/%E5%85%A8%E5%94%90%E8%AF%97/authors.song.json",
        license=CHINESE_POETRY_LICENSE,
        license_url=CHINESE_POETRY_LICENSE_URL,
    ),
)

KANRIPO_ASSETS: tuple[AssetSpec, ...] = tuple(
    AssetSpec(
        key=code.lower(),
        source="kanripo",
        url=f"https://raw.githubusercontent.com/kanripo/KR-Catalog/master/KR/{code}.txt",
        license=KANRIPO_LICENSE,
        license_url=KANRIPO_LICENSE_URL,
    )
    for code in ("KR4c", "KR4d", "KR4j")
)

ALL_ASSETS = CHINESE_POETRY_ASSETS + KANRIPO_ASSETS


# The corpus contains a bounded set of Tang/Song names.  Translating only the
# characters that occur in those names is safer than a home-grown general
# Chinese converter: matching remains exact after alias generation.
_S2T = {
    "仪": "儀", "刘": "劉", "庄": "莊", "锡": "錫", "卢": "盧", "纶": "綸",
    "叶": "葉", "梦": "夢", "马": "馬", "吕": "呂", "吴": "吳", "问": "問",
    "参": "參", "张": "張", "龄": "齡", "干": "幹", "继": "繼", "几": "幾",
    "巩": "鞏", "隐": "隱", "贺": "賀", "鹤": "鶴", "杨": "楊", "万": "萬",
    "亿": "億", "尧": "堯", "欧": "歐", "阳": "陽", "温": "溫", "涣": "渙",
    "维": "維", "罗": "羅", "聂": "聶", "苏": "蘇", "轼": "軾", "辙": "轍",
    "浑": "渾", "观": "觀", "颢": "顥", "铸": "鑄", "贾": "賈", "岛": "島",
    "钱": "錢", "陆": "陸", "渊": "淵", "陈": "陳", "与": "與", "义": "義",
    "韦": "韋", "应": "應", "韩": "韓", "骆": "駱", "宾": "賓", "适": "適",
    "黄": "黃", "弃": "棄", "许": "許", "彦": "彥", "坚": "堅", "咏": "詠",
}
_T2S = {traditional: simplified for simplified, traditional in _S2T.items()}
_S2T_TABLE = str.maketrans(_S2T)
_T2S_TABLE = str.maketrans(_T2S)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_name(value: object) -> str:
    return unicodedata.normalize("NFC", str(value or "")).strip().replace(" ", "")


def simplified_name(value: object) -> str:
    return normalize_name(value).translate(_T2S_TABLE)


def traditional_name(value: object) -> str:
    return normalize_name(value).translate(_S2T_TABLE)


def aliases_for_name(value: object) -> tuple[str, ...]:
    name = normalize_name(value)
    choices: list[tuple[str, ...]] = []
    for character in name:
        variants = {character}
        if character in _S2T:
            variants.add(_S2T[character])
        if character in _T2S:
            variants.add(_T2S[character])
        choices.append(tuple(sorted(variants)))
    return tuple(sorted("".join(parts) for parts in product(*choices))) if choices else ()


def name_match_method(local_name: str, source_name: str) -> str | None:
    local = normalize_name(local_name)
    source = normalize_name(source_name)
    if not source:
        return None
    if source == local:
        return "exact_name"
    if source == traditional_name(local):
        return "traditional_alias"
    if source == simplified_name(local):
        return "simplified_alias"
    if simplified_name(source) == simplified_name(local):
        return "mixed_simplified_traditional_alias"
    return None


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def stable_id(*parts: object) -> str:
    raw = json.dumps(parts, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def canonical_json(value: object, *, pretty: bool = False) -> str:
    if pretty:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        with tmp.open("wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def atomic_write_text(path: Path, text: str) -> None:
    atomic_write_bytes(path, text.encode("utf-8"))


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    payload = "".join(canonical_json(row) + "\n" for row in rows)
    atomic_write_text(path, payload)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig") as handle:
        for line_no, raw in enumerate(handle, 1):
            line = raw.strip()
            if not line:
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_no}: expected a JSON object")
            rows.append(value)
    return rows


def load_roster(path: Path = POEMS_JSON) -> list[PoetSpec]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, list):
        raise ValueError(f"{path} must contain a JSON array")
    counts: Counter[tuple[str, str]] = Counter()
    dynasties: dict[str, set[str]] = defaultdict(set)
    for poem in payload:
        if not isinstance(poem, dict):
            continue
        poet = normalize_name(poem.get("poet") or poem.get("author"))
        dynasty = normalize_name(poem.get("dynasty"))
        if not poet or not dynasty:
            continue
        counts[(poet, dynasty)] += 1
        dynasties[poet].add(dynasty)
    roster: list[PoetSpec] = []
    for poet, values in dynasties.items():
        local_counts = tuple(sorted(((dynasty, counts[(poet, dynasty)]) for dynasty in values)))
        ranked = sorted(local_counts, key=lambda item: (-item[1], item[0]))
        if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
            raise ValueError(f"poet has tied local dynasty labels: {poet}: {dict(local_counts)}")
        chosen = ranked[0][0]
        roster.append(
            PoetSpec(
                name=poet,
                dynasty=chosen,
                poem_count=sum(value for _dynasty, value in local_counts),
                dynasty_counts=local_counts,
                dynasty_resolution="single_local_label" if len(local_counts) == 1 else "majority_local_label",
            )
        )
    return sorted(roster, key=lambda item: (item.dynasty, item.name))


def resolve_selection(roster: Sequence[PoetSpec], scope: str, poets_arg: str | None) -> list[str]:
    available = {item.name for item in roster}
    if poets_arg is not None:
        requested: list[str] = []
        for raw in re.split(r"[,，]", poets_arg):
            poet = normalize_name(raw)
            if poet and poet not in requested:
                requested.append(poet)
        if not requested:
            raise ValueError("--poets did not contain a poet name")
        unknown = [poet for poet in requested if poet not in available]
        if unknown:
            raise ValueError(f"unknown poet(s): {', '.join(unknown)}")
        return requested
    if scope == "core":
        missing = [poet for poet in CORE_POETS if poet not in available]
        if missing:
            raise ValueError(f"core poet(s) absent from corpus: {', '.join(missing)}")
        return list(CORE_POETS)
    if scope == "all":
        return [item.name for item in roster]
    raise ValueError("scope must be core or all")


class CacheStore:
    """Content-addressed bodies plus an atomic URL pointer with checksum."""

    def __init__(self, root: Path = CACHE_DIR) -> None:
        self.root = root
        self.body_dir = root / "bodies"
        self.meta_dir = root / "meta"

    @staticmethod
    def url_key(url: str) -> str:
        return hashlib.sha256(url.encode("utf-8")).hexdigest()

    def meta_path(self, url: str) -> Path:
        return self.meta_dir / f"{self.url_key(url)}.json"

    def read(self, url: str) -> tuple[bytes | None, dict[str, Any] | None, str]:
        meta_path = self.meta_path(url)
        if not meta_path.exists():
            return None, None, "cache_miss"
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if not isinstance(meta, dict) or meta.get("url") != url:
                return None, None, "cache_metadata_invalid"
            body_name = str(meta.get("body_file") or "")
            if not re.fullmatch(r"[0-9a-f]{64}\.bin", body_name):
                return None, None, "cache_metadata_invalid"
            body_path = self.body_dir / body_name
            body = body_path.read_bytes()
            digest = sha256_bytes(body)
            if digest != meta.get("sha256") or len(body) != int(meta.get("bytes", -1)):
                return None, None, "cache_checksum_mismatch"
            return body, meta, "cache_hit"
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return None, None, "cache_invalid"

    def store(
        self,
        url: str,
        body: bytes,
        *,
        retrieved_at: str,
        content_type: str = "",
        http_status: int = 200,
    ) -> dict[str, Any]:
        digest = sha256_bytes(body)
        body_name = f"{digest}.bin"
        body_path = self.body_dir / body_name
        if not body_path.exists() or sha256_bytes(body_path.read_bytes()) != digest:
            atomic_write_bytes(body_path, body)
        meta = {
            "schema_version": SCHEMA_VERSION,
            "url": url,
            "sha256": digest,
            "bytes": len(body),
            "body_file": body_name,
            "retrieved_at": retrieved_at,
            "content_type": content_type,
            "http_status": http_status,
        }
        atomic_write_text(self.meta_path(url), canonical_json(meta, pretty=True))
        return meta


class AssetFetcher:
    def __init__(
        self,
        cache: CacheStore,
        *,
        offline: bool = False,
        timeout: float = 45.0,
        retries: int = 2,
        opener: Callable[..., Any] | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        clock: Callable[[], str] = utc_now,
    ) -> None:
        self.cache = cache
        self.offline = offline
        self.timeout = timeout
        self.retries = retries
        self.opener = opener or urllib.request.urlopen
        self.sleeper = sleeper
        self.clock = clock

    def fetch(self, asset: AssetSpec) -> FetchResult:
        cached_body, cached_meta, cache_status = self.cache.read(asset.url)
        if self.offline:
            if cached_body is None or cached_meta is None:
                return FetchResult(asset, False, "fetch_failed", error=cache_status)
            return FetchResult(
                asset,
                True,
                "cache_hit",
                body=cached_body,
                content_sha256=str(cached_meta["sha256"]),
                retrieved_at=str(cached_meta["retrieved_at"]),
                from_cache=True,
                http_status=int(cached_meta.get("http_status", 200)),
                cache_path=str(self.cache.meta_path(asset.url)),
            )

        last_error = "network_failure"
        last_status: int | None = None
        for attempt in range(self.retries + 1):
            response: Any = None
            try:
                request = urllib.request.Request(
                    asset.url,
                    headers={
                        "User-Agent": "PoemJourneyReferenceCorpus/1.0 (+research; repository assets only)",
                        "Accept": "application/json,text/plain;q=0.9,*/*;q=0.5",
                    },
                )
                response = self.opener(request, timeout=self.timeout)
                last_status = int(getattr(response, "status", 200) or 200)
                body = response.read()
                if last_status != 200 or not body:
                    raise OSError(f"HTTP {last_status} or empty body")
                retrieved_at = self.clock()
                headers = getattr(response, "headers", {})
                content_type = str(headers.get("Content-Type", "")) if hasattr(headers, "get") else ""
                meta = self.cache.store(
                    asset.url,
                    body,
                    retrieved_at=retrieved_at,
                    content_type=content_type,
                    http_status=last_status,
                )
                return FetchResult(
                    asset,
                    True,
                    "fetched",
                    body=body,
                    content_sha256=str(meta["sha256"]),
                    retrieved_at=retrieved_at,
                    from_cache=False,
                    http_status=last_status,
                    cache_path=str(self.cache.meta_path(asset.url)),
                )
            except urllib.error.HTTPError as exc:
                last_status = int(exc.code)
                last_error = f"HTTP {exc.code}"
                if exc.code not in {408, 429, 500, 502, 503, 504}:
                    break
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last_error = f"{type(exc).__name__}: {exc}"
            finally:
                if response is not None:
                    try:
                        response.close()
                    except Exception:
                        pass
            if attempt < self.retries:
                self.sleeper(min(8.0, 0.75 * (2**attempt)))

        if cached_body is not None and cached_meta is not None:
            return FetchResult(
                asset,
                True,
                "fetch_failed_cache_used",
                body=cached_body,
                content_sha256=str(cached_meta["sha256"]),
                retrieved_at=str(cached_meta["retrieved_at"]),
                from_cache=True,
                http_status=last_status,
                error=last_error,
                cache_path=str(self.cache.meta_path(asset.url)),
            )
        return FetchResult(asset, False, "fetch_failed", http_status=last_status, error=last_error)


def bounded_worker_count(requested: int, task_count: int) -> int:
    if requested < 1:
        raise ValueError("--workers must be at least 1")
    return max(1, min(2, requested, max(1, task_count)))


def fetch_assets(fetcher: AssetFetcher, assets: Sequence[AssetSpec], workers: int) -> list[FetchResult]:
    if not assets:
        return []
    pool_size = bounded_worker_count(workers, len(assets))
    results: list[FetchResult] = []
    with ThreadPoolExecutor(max_workers=pool_size, thread_name_prefix="poet-ref") as pool:
        futures = {pool.submit(fetcher.fetch, asset): asset for asset in assets}
        for future in as_completed(futures):
            asset = futures[future]
            try:
                results.append(future.result())
            except Exception as exc:  # Defensive isolation: one asset must not abort the others.
                results.append(FetchResult(asset, False, "fetch_failed", error=f"internal_error: {exc}"))
    return sorted(results, key=lambda item: item.asset.key)


def parse_author_asset(result: FetchResult) -> tuple[list[dict[str, Any]], FetchResult]:
    if not result.usable:
        return [], result
    try:
        payload = json.loads(result.body.decode("utf-8-sig"))
        if not isinstance(payload, list):
            raise ValueError("top-level value is not an array")
        rows = [item for item in payload if isinstance(item, dict) and normalize_name(item.get("name"))]
        if not rows:
            raise ValueError("no author records")
        return rows, result
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        return [], replace(result, usable=False, attempt_status="fetch_failed", error=f"parse_error: {exc}")


def biography_rows_for_poet(
    poet: PoetSpec,
    records: Sequence[dict[str, Any]],
    result: FetchResult,
) -> tuple[list[dict[str, Any]], str]:
    candidates: dict[tuple[str, str, str], dict[str, Any]] = {}
    for record in records:
        source_name = normalize_name(record.get("name"))
        method = name_match_method(poet.name, source_name)
        if method is None:
            continue
        source_id = str(record.get("id") or "").strip()
        desc = str(record.get("desc") or "").strip()
        candidates[(source_id, source_name, desc)] = record
    if not candidates:
        return [], "not_found"
    status = "matched" if len(candidates) == 1 else "ambiguous"
    rows: list[dict[str, Any]] = []
    for source_id, source_name, desc in sorted(candidates):
        method = name_match_method(poet.name, source_name) or "exact_alias"
        rows.append(
            {
                "schema_version": SCHEMA_VERSION,
                "record_type": "poet_reference_biography",
                "reference_id": stable_id("chinese_poetry", poet.name, poet.dynasty, source_id, source_name, desc),
                "poet": poet.name,
                "dynasty": poet.dynasty,
                "match_status": status,
                "match_method": method,
                "matched_name": source_name,
                "source_record_id": source_id,
                "desc": desc,
                "source": "chinese-poetry/chinese-poetry",
                "source_dataset": result.asset.key,
                "source_url": result.asset.url,
                "source_license": result.asset.license,
                "license_url": result.asset.license_url,
                "content_sha256": result.content_sha256,
                "retrieved_at": result.retrieved_at,
                "parser_version": PARSER_VERSION,
            }
        )
    return rows, status


_RECORD_HEADER = re.compile(r"^\*\*\*\s+(KR[0-9A-Za-z]+)\s+(.+?)\s*$")
_CATEGORY_HEADER = re.compile(r"^\*\*\s+(?!\*)(.+?)\s*$")
_PERSON_HEADER = re.compile(r"^\*\*\*\*\*\s+(.+?)\s*$")
_PROPERTY = re.compile(r"^\s*:([A-Za-z_]+):\s*(.*?)\s*$")
_DYNASTY_TOKEN = re.compile(r"(?:^|[-（(,，、\s])(唐|宋)(?:$|[-）),，、\s])")


def _record_title(heading: str) -> str:
    return heading.split("-", 1)[0].strip()


def _dynasties_from_text(*values: str) -> tuple[str, ...]:
    found: set[str] = set()
    for value in values:
        found.update(_DYNASTY_TOKEN.findall(value or ""))
    return tuple(sorted(found))


def parse_kanripo_catalog(result: FetchResult) -> tuple[list[CatalogRecord], FetchResult]:
    if not result.usable:
        return [], result
    try:
        text = result.body.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        return [], replace(result, usable=False, attempt_status="fetch_failed", error=f"parse_error: {exc}")
    lines = text.splitlines()
    starts: list[tuple[int, re.Match[str]]] = []
    for index, line in enumerate(lines):
        match = _RECORD_HEADER.match(line)
        if match:
            starts.append((index, match))
    if not starts:
        return [], replace(result, usable=False, attempt_status="fetch_failed", error="parse_error: no KR records")

    records: list[CatalogRecord] = []
    current_category = ""
    category_at: dict[int, str] = {}
    for index, line in enumerate(lines):
        category = _CATEGORY_HEADER.match(line)
        if category:
            current_category = category.group(1).strip()
        category_at[index] = current_category

    for position, (start, header) in enumerate(starts):
        stop = starts[position + 1][0] if position + 1 < len(starts) else len(lines)
        block = lines[start:stop]
        kr_id = header.group(1)
        heading = header.group(2).strip()
        top_properties: dict[str, str] = {}
        for line in block[1:]:
            if line.startswith("****"):
                break
            prop = _PROPERTY.match(line)
            if prop:
                top_properties[prop.group(1)] = prop.group(2).strip()
        responsibility = top_properties.get("_RESP", "")
        responsibility_line = next((line.strip() for line in block if line.lstrip().startswith(":_RESP:")), "")

        people: list[CatalogPerson] = []
        in_people = False
        active_name = ""
        active_props: dict[str, str] = {}

        def flush_person() -> None:
            nonlocal active_name, active_props
            if active_name:
                evidence_parts = [f"人物：{active_name}"]
                if active_props.get("DYNASTY"):
                    evidence_parts.append(f"朝代：{active_props['DYNASTY']}")
                if active_props.get("FUNCTION"):
                    evidence_parts.append(f"职责：{active_props['FUNCTION']}")
                people.append(
                    CatalogPerson(
                        name=normalize_name(active_name),
                        dynasty=normalize_name(active_props.get("DYNASTY")),
                        function=normalize_name(active_props.get("FUNCTION")),
                        dates=str(active_props.get("DATES") or "").strip(),
                        evidence="；".join(evidence_parts),
                    )
                )
            active_name = ""
            active_props = {}

        for line in block[1:]:
            if line.startswith("**** 人物"):
                in_people = True
                continue
            if in_people and line.startswith("****") and not line.startswith("*****"):
                flush_person()
                in_people = False
                continue
            if not in_people:
                continue
            person_match = _PERSON_HEADER.match(line)
            if person_match:
                flush_person()
                active_name = person_match.group(1).strip()
                continue
            prop = _PROPERTY.match(line)
            if active_name and prop:
                active_props[prop.group(1)] = prop.group(2).strip()
        flush_person()

        dynasties = set(_dynasties_from_text(heading, responsibility, category_at.get(start, "")))
        dynasties.update(person.dynasty for person in people if person.dynasty in {"唐", "宋"})
        records.append(
            CatalogRecord(
                kr_id=kr_id,
                heading=heading,
                title=_record_title(heading),
                category=category_at.get(start, ""),
                responsibility=responsibility,
                dynasties=tuple(sorted(dynasties)),
                people=tuple(people),
                header_line=block[0].strip(),
                responsibility_line=responsibility_line,
                source_asset=result.asset,
                content_sha256=result.content_sha256,
                retrieved_at=result.retrieved_at,
            )
        )
    return records, result


_RESP_ROLE_SUFFIXES = tuple(
    sorted(
        {
            "重編", "編次", "校注", "校訂", "集注", "箋注", "撰", "編", "輯", "注", "著",
            "述", "選", "評", "纂", "校", "序", "補", "箋", "傳", "集", "修", "刊",
        },
        key=len,
        reverse=True,
    )
)


def responsibility_names(value: str) -> set[str]:
    text = re.sub(r"[（(][^）)]*[）)]", "", value or "")
    names: set[str] = set()
    for raw in re.split(r"[,，、;；]", text):
        token = normalize_name(raw)
        changed = True
        while token and changed:
            changed = False
            for suffix in _RESP_ROLE_SUFFIXES:
                if token.endswith(suffix) and len(token) > len(suffix):
                    token = token[: -len(suffix)]
                    changed = True
                    break
        if 2 <= len(token) <= 8:
            names.add(token)
    return names


def catalog_match(record: CatalogRecord, poet: PoetSpec) -> tuple[str | None, tuple[str, ...], tuple[str, ...]]:
    aliases = set(aliases_for_name(poet.name))
    record_dynasty_known = bool(record.dynasties)
    if record_dynasty_known and poet.dynasty not in record.dynasties:
        return None, (), ()

    strong_methods: set[str] = set()
    weak_methods: set[str] = set()
    evidence: set[str] = set()

    header_parts = {normalize_name(part) for part in record.heading.split("-") if normalize_name(part)}
    if aliases & header_parts:
        strong_methods.add("header_author_exact")
        evidence.add(record.header_line)

    resp_names = responsibility_names(record.responsibility)
    if aliases & resp_names:
        strong_methods.add("responsibility_exact")
        if record.responsibility_line:
            evidence.add(record.responsibility_line)

    for person in record.people:
        if person.name not in aliases:
            continue
        if person.dynasty and person.dynasty != poet.dynasty:
            continue
        strong_methods.add("person_exact")
        evidence.add(person.evidence)

    if record_dynasty_known and any(alias and alias in record.title for alias in aliases):
        weak_methods.add("title_contains_alias")
        evidence.add(record.header_line)

    if strong_methods:
        return "matched", tuple(sorted(strong_methods | weak_methods)), tuple(sorted(evidence))
    if weak_methods:
        return "ambiguous", tuple(sorted(weak_methods)), tuple(sorted(evidence))
    return None, (), ()


def kanripo_rows(
    roster: Sequence[PoetSpec],
    records: Sequence[CatalogRecord],
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    provisional: list[dict[str, Any]] = []
    alias_owners: dict[str, set[str]] = defaultdict(set)
    for poet in roster:
        for alias in aliases_for_name(poet.name):
            alias_owners[alias].add(poet.name)
    for poet in roster:
        for record in records:
            status, methods, evidence = catalog_match(record, poet)
            if status is None:
                continue
            matched_aliases = sorted(
                alias
                for alias in aliases_for_name(poet.name)
                if alias in record.heading
                or alias in record.responsibility
                or any(alias == person.name for person in record.people)
            )
            provisional.append(
                {
                    "schema_version": SCHEMA_VERSION,
                    "record_type": "poet_kanripo_catalog_match",
                    "reference_id": stable_id("kanripo", poet.name, poet.dynasty, record.kr_id, record.source_asset.url),
                    "poet": poet.name,
                    "dynasty": poet.dynasty,
                    "match_status": status,
                    "match_methods": list(methods),
                    "matched_aliases": matched_aliases,
                    "kr_id": record.kr_id,
                    "title": record.title,
                    "catalog_heading": record.heading,
                    "category": record.category,
                    "responsibility": record.responsibility,
                    "people": [
                        {
                            "name": person.name,
                            "dynasty": person.dynasty,
                            "function": person.function,
                            "dates": person.dates,
                        }
                        for person in record.people
                    ],
                    "evidence": [item[:280] for item in evidence[:3]],
                    "source": "Kanripo/KR-Catalog",
                    "source_catalog": record.source_asset.key,
                    "source_url": record.source_asset.url,
                    "repository_url": f"https://github.com/kanripo/{record.kr_id}",
                    "source_license": record.source_asset.license,
                    "license_url": record.source_asset.license_url,
                    "content_sha256": record.content_sha256,
                    "retrieved_at": record.retrieved_at,
                    "parser_version": PARSER_VERSION,
                }
            )

    rows: list[dict[str, Any]] = []
    for row in provisional:
        collision_poets = sorted(
            {
                owner
                for alias in row.get("matched_aliases", [])
                for owner in alias_owners.get(str(alias), set())
            }
        )
        if len(collision_poets) > 1:
            row = dict(row)
            row["match_status"] = "ambiguous"
            row["match_methods"] = sorted(set(row["match_methods"]) | {"corpus_alias_collision"})
            row["collision_poets"] = collision_poets
        rows.append(row)

    outcomes: dict[str, str] = {}
    by_poet: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_poet[str(row["poet"])].append(row)
    for poet in roster:
        statuses = {str(row.get("match_status")) for row in by_poet.get(poet.name, [])}
        outcomes[poet.name] = "matched" if "matched" in statuses else "ambiguous" if "ambiguous" in statuses else "not_found"
    return sorted(rows, key=kanripo_sort_key), outcomes


def biography_sort_key(row: dict[str, Any]) -> tuple[str, ...]:
    return (
        str(row.get("dynasty") or ""),
        str(row.get("poet") or ""),
        str(row.get("source_dataset") or ""),
        str(row.get("source_record_id") or ""),
        str(row.get("reference_id") or ""),
    )


def kanripo_sort_key(row: dict[str, Any]) -> tuple[str, ...]:
    return (
        str(row.get("dynasty") or ""),
        str(row.get("poet") or ""),
        str(row.get("source_catalog") or ""),
        str(row.get("kr_id") or ""),
        str(row.get("reference_id") or ""),
    )


def merge_by_successful_assets(
    existing: Sequence[dict[str, Any]],
    incoming: Sequence[dict[str, Any]],
    *,
    successful_urls: set[str],
    selected_poets: set[str],
    sort_key: Callable[[dict[str, Any]], tuple[str, ...]],
) -> list[dict[str, Any]]:
    kept = [
        row
        for row in existing
        if not (str(row.get("poet") or "") in selected_poets and str(row.get("source_url") or "") in successful_urls)
    ]
    kept.extend(row for row in incoming if str(row.get("poet") or "") in selected_poets)
    deduplicated: dict[str, dict[str, Any]] = {}
    for row in kept:
        reference_id = str(row.get("reference_id") or stable_id(row))
        deduplicated[reference_id] = row
    return sorted(deduplicated.values(), key=sort_key)


def active_status(rows: Sequence[dict[str, Any]]) -> str:
    statuses = {str(row.get("match_status") or "") for row in rows}
    if "matched" in statuses:
        return "matched"
    if "ambiguous" in statuses:
        return "ambiguous"
    return "not_found"


def asset_attempt(result: FetchResult) -> dict[str, Any]:
    return {
        "key": result.asset.key,
        "url": result.asset.url,
        "status": result.attempt_status,
        "usable": result.usable,
        "from_cache": result.from_cache,
        "http_status": result.http_status,
        "content_sha256": result.content_sha256,
        "retrieved_at": result.retrieved_at,
        "cache_path": result.cache_path,
        "error": result.error,
    }


def build_coverage(
    roster: Sequence[PoetSpec],
    *,
    scope: str,
    selected_poets: Sequence[str],
    biography_rows: Sequence[dict[str, Any]],
    kanripo_matches: Sequence[dict[str, Any]],
    biography_outcomes: dict[str, str],
    kanripo_outcomes: dict[str, str],
    author_results: Sequence[FetchResult],
    catalog_results: Sequence[FetchResult],
    generated_at: str | None = None,
    poems_path: Path = POEMS_JSON,
) -> dict[str, Any]:
    generated = generated_at or utc_now()
    selected = set(selected_poets)
    bios_by_poet: dict[str, list[dict[str, Any]]] = defaultdict(list)
    kr_by_poet: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in biography_rows:
        bios_by_poet[str(row.get("poet") or "")].append(row)
    for row in kanripo_matches:
        kr_by_poet[str(row.get("poet") or "")].append(row)

    author_by_dynasty = {result.asset.dynasty: result for result in author_results}
    catalog_complete = bool(catalog_results) and all(result.usable for result in catalog_results)
    per_poet: list[dict[str, Any]] = []
    for poet in roster:
        bio_result = author_by_dynasty.get(poet.dynasty)
        current_bio = biography_outcomes.get(poet.name, "not_found")
        if bio_result is None or not bio_result.usable:
            current_bio = "fetch_failed"
        current_kr = kanripo_outcomes.get(poet.name, "not_found") if catalog_complete else "fetch_failed"
        active_bio = active_status(bios_by_poet.get(poet.name, []))
        active_kr = active_status(kr_by_poet.get(poet.name, []))
        per_poet.append(
            {
                "poet": poet.name,
                "dynasty": poet.dynasty,
                "poem_count": poet.poem_count,
                "local_dynasty_counts": dict(poet.dynasty_counts or ((poet.dynasty, poet.poem_count),)),
                "dynasty_resolution": poet.dynasty_resolution,
                "selected": poet.name in selected,
                "chinese_poetry": {
                    "status": current_bio,
                    "active_status": active_bio,
                    "candidate_count": sum(
                        1 for row in bios_by_poet.get(poet.name, []) if row.get("match_status") in {"matched", "ambiguous"}
                    ),
                    "persisted_record_count": len(bios_by_poet.get(poet.name, [])),
                },
                "kanripo": {
                    "status": current_kr,
                    "active_status": active_kr,
                    "candidate_count": len(kr_by_poet.get(poet.name, [])),
                    "persisted_record_count": len(kr_by_poet.get(poet.name, [])),
                },
            }
        )

    status_counts = {
        "chinese_poetry": dict(sorted(Counter(row["chinese_poetry"]["status"] for row in per_poet).items())),
        "kanripo": dict(sorted(Counter(row["kanripo"]["status"] for row in per_poet).items())),
    }
    roster_fingerprint = stable_id(
        [(item.name, item.dynasty, item.poem_count, item.dynasty_counts, item.dynasty_resolution) for item in roster]
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "parser_version": PARSER_VERSION,
        "generated_at": generated,
        "scope": scope,
        "selected_poets": list(selected_poets),
        "corpus": {
            "path": str(poems_path),
            "poet_count": len(roster),
            "poem_count": sum(item.poem_count for item in roster),
            "dynasty_counts": dict(sorted(Counter(item.dynasty for item in roster).items())),
            "roster_sha256": roster_fingerprint,
        },
        "sources": {
            "chinese_poetry": {
                "name": "chinese-poetry/chinese-poetry authors metadata",
                "license": CHINESE_POETRY_LICENSE,
                "license_url": CHINESE_POETRY_LICENSE_URL,
                "attempts": [asset_attempt(result) for result in sorted(author_results, key=lambda item: item.asset.key)],
                "status_counts": status_counts["chinese_poetry"],
            },
            "kanripo": {
                "name": "Kanripo KR-Catalog",
                "license": KANRIPO_LICENSE,
                "license_url": KANRIPO_LICENSE_URL,
                "attempts": [asset_attempt(result) for result in sorted(catalog_results, key=lambda item: item.asset.key)],
                "status_counts": status_counts["kanripo"],
            },
        },
        "totals": {
            "poets": len(roster),
            "selected_poets": len(selected),
            "biography_records": len(biography_rows),
            "kanripo_catalog_matches": len(kanripo_matches),
            "status_counts": status_counts,
            "complete_without_fetch_failures": all("fetch_failed" not in counts for counts in status_counts.values()),
        },
        "per_poet": per_poet,
        "interpretation_notes": [
            "chinese-poetry 的 desc 是开放参考简介，不是路线、作诗地点或精确行年证据。",
            "Kanripo 命中是目录书目关系；仅结构化姓名精确命中可列 matched，书名含名而无责任者佐证列 ambiguous。",
            "fetch_failed 表示本次相关全局资产不完整；active_status 与旧成功记录仍保留，避免联网失败清空成果。",
            "同一诗人的本地逐诗朝代标签冲突时采用数量最多的本地标签，并在 per_poet 保留全部计数；票数相同则终止，避免任意绑定。",
            "所有结果均停留在 data/candidates，不写入 data/reviewed。",
        ],
    }


def collect(
    *,
    scope: str,
    poets_arg: str | None,
    offline: bool,
    workers: int,
    timeout: float,
    retries: int,
    poems_path: Path = POEMS_JSON,
    cache_dir: Path = CACHE_DIR,
    biographies_path: Path = BIOGRAPHIES_JSONL,
    kanripo_path: Path = KANRIPO_MATCHES_JSONL,
    coverage_path: Path = COVERAGE_JSON,
    clock: Callable[[], str] = utc_now,
) -> dict[str, Any]:
    roster = load_roster(poems_path)
    selected_poets = resolve_selection(roster, scope, poets_arg)
    selected = set(selected_poets)
    fetcher = AssetFetcher(CacheStore(cache_dir), offline=offline, timeout=timeout, retries=retries, clock=clock)
    fetched = fetch_assets(fetcher, ALL_ASSETS, workers)
    fetched_by_key = {result.asset.key: result for result in fetched}

    parsed_author_results: list[FetchResult] = []
    authors_by_dynasty: dict[str, list[dict[str, Any]]] = {}
    fresh_biography_rows: list[dict[str, Any]] = []
    biography_outcomes: dict[str, str] = {}
    for asset in CHINESE_POETRY_ASSETS:
        records, result = parse_author_asset(fetched_by_key[asset.key])
        parsed_author_results.append(result)
        if result.usable and asset.dynasty:
            authors_by_dynasty[asset.dynasty] = records
            for poet in roster:
                if poet.dynasty != asset.dynasty:
                    continue
                rows, status = biography_rows_for_poet(poet, records, result)
                fresh_biography_rows.extend(rows)
                biography_outcomes[poet.name] = status

    parsed_catalog_results: list[FetchResult] = []
    records_by_asset: dict[str, list[CatalogRecord]] = {}
    all_catalog_records: list[CatalogRecord] = []
    for asset in KANRIPO_ASSETS:
        records, result = parse_kanripo_catalog(fetched_by_key[asset.key])
        parsed_catalog_results.append(result)
        if result.usable:
            records_by_asset[asset.url] = records
            all_catalog_records.extend(records)
    fresh_kanripo_rows, kanripo_outcomes = kanripo_rows(roster, all_catalog_records)

    old_biographies = read_jsonl(biographies_path)
    old_kanripo = read_jsonl(kanripo_path)
    biography_success_urls = {result.asset.url for result in parsed_author_results if result.usable}
    catalog_success_urls = {result.asset.url for result in parsed_catalog_results if result.usable}
    merged_biographies = merge_by_successful_assets(
        old_biographies,
        fresh_biography_rows,
        successful_urls=biography_success_urls,
        selected_poets=selected,
        sort_key=biography_sort_key,
    )
    merged_kanripo = merge_by_successful_assets(
        old_kanripo,
        fresh_kanripo_rows,
        successful_urls=catalog_success_urls,
        selected_poets=selected,
        sort_key=kanripo_sort_key,
    )

    coverage = build_coverage(
        roster,
        scope=scope,
        selected_poets=selected_poets,
        biography_rows=merged_biographies,
        kanripo_matches=merged_kanripo,
        biography_outcomes=biography_outcomes,
        kanripo_outcomes=kanripo_outcomes,
        author_results=parsed_author_results,
        catalog_results=parsed_catalog_results,
        generated_at=clock(),
        poems_path=poems_path,
    )

    write_jsonl(biographies_path, merged_biographies)
    write_jsonl(kanripo_path, merged_kanripo)
    atomic_write_text(coverage_path, canonical_json(coverage, pretty=True))
    return coverage


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="poet_reference_corpus",
        description="88位诗人开放参考史料补充采集器（与行旅管线解耦）",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    collect_parser = subparsers.add_parser("collect", help="下载全局资产、在本地匹配并写入候选层")
    collect_parser.add_argument("--scope", choices=("core", "all"), default="core")
    collect_parser.add_argument("--poets", default=None, help="逗号分隔诗人；显式名单优先于 --scope")
    collect_parser.add_argument("--offline", action="store_true", help="仅使用通过 checksum 校验的缓存")
    collect_parser.add_argument("--workers", type=int, default=2, help="跨 GitHub 文件并发，硬上限为 2")
    collect_parser.add_argument("--timeout", type=float, default=45.0)
    collect_parser.add_argument("--retries", type=int, default=2, help="初始请求后的额外重试次数")
    subparsers.add_parser("check", help="运行离线 fixture 测试")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "check":
        check_script = Path(__file__).with_name("check_poet_reference_corpus.py")
        return subprocess.run([sys.executable, str(check_script)], cwd=ROOT, check=False).returncode
    if args.workers < 1:
        raise SystemExit("--workers must be at least 1")
    if args.timeout <= 0:
        raise SystemExit("--timeout must be positive")
    if args.retries < 0:
        raise SystemExit("--retries must be non-negative")
    try:
        coverage = collect(
            scope=args.scope,
            poets_arg=args.poets,
            offline=args.offline,
            workers=args.workers,
            timeout=args.timeout,
            retries=args.retries,
        )
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        raise SystemExit(str(exc)) from exc
    totals = coverage["totals"]
    print(
        "[ok] poet reference corpus: "
        f"poets={totals['poets']} selected={totals['selected_poets']} "
        f"biographies={totals['biography_records']} kanripo={totals['kanripo_catalog_matches']}"
    )
    print(f"[ok] coverage: {COVERAGE_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
