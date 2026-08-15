"""Source adapters for the poem-background evidence pipeline."""
from __future__ import annotations

import datetime
import email.utils
import hashlib
import json
import os
import random
import re
import sqlite3
import tempfile
import threading
import time
import urllib.robotparser
import zipfile
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote, urlparse

import requests
from bs4 import BeautifulSoup, FeatureNotFound

from background_contract import (
    CACHE_DIR,
    PROMPT_VERSION,
    atomic_write_text,
    deterministic_id,
    first_line,
    make_candidate,
    normalize_excerpt,
    normalize_title,
    poem_key,
    source_match_score,
    utc_now,
)


USER_AGENT = "ShixingWanliBackgroundResearch/1.0 (+local academic project)"
CNKGRAPH_API = "https://open.cnkgraph.com/api"
CNKGRAPH_FIND = f"{CNKGRAPH_API}/writing/find"
CHGIS_ENDPOINT = "https://chgis.hudci.org/tgaz/placename"
CBDB_MANIFEST = "https://raw.githubusercontent.com/cbdb-project/cbdb_sqlite/master/latest.json"

LOGIN_MARKERS = (
    "open.weixin.qq.com",
    "微信登录",
    "扫码登录",
    "请输入验证码",
    "captcha",
    "登录后继续",
)

RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})
MAX_RETRY_AFTER = 60.0
BLOCKED_POLICY_CACHE_TTL = 60.0 * 60.0


@dataclass(frozen=True)
class FetchResult:
    url: str
    status: str
    status_code: int | None = None
    text: str = ""
    content: bytes = b""
    content_type: str = ""
    cache_key: str = ""
    note: str = ""
    from_cache: bool = False


class SharedHostGate:
    """Cross-client concurrency and request-spacing gate keyed by host.

    Journey workers each own their ``requests.Session``.  This small shared
    object coordinates only host pressure, so sessions are never shared across
    threads while Sou-yun can still be serialized and other APIs bounded.
    """

    def __init__(
        self,
        rules: dict[str, tuple[int, float, float]] | None = None,
        *,
        default: tuple[int, float, float] = (4, 0.0, 0.0),
    ) -> None:
        self.rules = dict(rules or {})
        self.default = default
        self._guard = threading.Lock()
        self._locks: dict[str, threading.Lock] = {}
        self._semaphores: dict[str, threading.BoundedSemaphore] = {}
        self._last_request: dict[str, float] = {}

    def _state(self, host: str) -> tuple[threading.Lock, threading.BoundedSemaphore, float, float]:
        with self._guard:
            limit, low, high = self.rules.get(host, self.default)
            limit = max(1, int(limit))
            lock = self._locks.setdefault(host, threading.Lock())
            semaphore = self._semaphores.get(host)
            if semaphore is None:
                semaphore = threading.BoundedSemaphore(limit)
                self._semaphores[host] = semaphore
            return lock, semaphore, max(0.0, float(low)), max(float(low), float(high))

    @contextmanager
    def slot(self, url: str):
        host = urlparse(url).netloc.casefold()
        lock, semaphore, low, high = self._state(host)
        semaphore.acquire()
        try:
            with lock:
                previous = self._last_request.get(host, 0.0)
                required = random.uniform(low, high)
                remaining = required - (time.monotonic() - previous)
                if remaining > 0:
                    time.sleep(remaining)
                self._last_request[host] = time.monotonic()
            yield
        finally:
            semaphore.release()


class HttpCacheClient:
    """Single-domain polite client with resumable content-addressed cache."""

    def __init__(
        self,
        *,
        cache_dir: Path = CACHE_DIR,
        timeout: float = 20.0,
        retries: int = 3,
        min_delay: float = 1.5,
        max_delay: float = 3.0,
        offline: bool = False,
        host_gate: SharedHostGate | None = None,
        blocked_policy_cache_ttl: float = BLOCKED_POLICY_CACHE_TTL,
    ) -> None:
        self.cache_dir = cache_dir
        self.timeout = timeout
        self.retries = retries
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.offline = offline
        self.host_gate = host_gate
        self.blocked_policy_cache_ttl = max(0.0, float(blocked_policy_cache_ttl))
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "zh-CN,zh;q=0.9"})
        self._last_request: dict[str, float] = {}
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}

    def _cache_key(self, method: str, url: str, payload: object = None) -> str:
        raw = json.dumps(
            {"method": method.upper(), "url": url, "payload": payload},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _paths(self, key: str) -> tuple[Path, Path]:
        folder = self.cache_dir / key[:2]
        return folder / f"{key}.body", folder / f"{key}.json"

    def _read_cache(self, key: str) -> FetchResult | None:
        body_path, meta_path = self._paths(key)
        if not (body_path.exists() and meta_path.exists()):
            return None
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            content = body_path.read_bytes()
        except (OSError, json.JSONDecodeError):
            return None
        expected_sha = str(meta.get("sha256") or "").strip().casefold()
        actual_sha = hashlib.sha256(content).hexdigest().casefold()
        # The metadata and body are one cache record.  A missing checksum or a
        # mismatch means a partial/corrupt write, so callers must treat it as a
        # miss (online re-fetch, offline offline_cache_miss).
        if not expected_sha or actual_sha != expected_sha:
            return None
        status = str(meta.get("status") or "ok")
        if status in {"fetch_failed", "parse_failed"}:
            # Negative cache is never a hit: online mode retries, offline mode
            # reports offline_cache_miss instead of surfacing a stale failure.
            return None
        if status == "blocked_by_policy" and not self.offline:
            # Login/captcha/robots responses describe a point-in-time access
            # state, not durable source content.  Keep a short online TTL to
            # avoid hammering the host during one run, then re-check on a later
            # run.  Offline mode may still surface the cached policy result.
            try:
                fetched_at = datetime.datetime.fromisoformat(
                    str(meta.get("fetched_at") or "").replace("Z", "+00:00")
                )
                if fetched_at.tzinfo is None:
                    fetched_at = fetched_at.replace(tzinfo=datetime.timezone.utc)
                age = (
                    datetime.datetime.now(datetime.timezone.utc)
                    - fetched_at.astimezone(datetime.timezone.utc)
                ).total_seconds()
            except (TypeError, ValueError):
                return None
            if age < 0 or age > self.blocked_policy_cache_ttl:
                return None
        charset = str(meta.get("encoding") or "utf-8")
        text = content.decode(charset, errors="replace")
        return FetchResult(
            url=str(meta.get("url") or ""),
            status=status,
            status_code=meta.get("status_code"),
            text=text,
            content=content,
            content_type=str(meta.get("content_type") or ""),
            cache_key=key,
            note=str(meta.get("note") or "cache"),
            from_cache=True,
        )

    def _write_cache(self, result: FetchResult, encoding: str = "utf-8") -> None:
        body_path, meta_path = self._paths(result.cache_key)
        body_path.parent.mkdir(parents=True, exist_ok=True)
        suffix = f".{os.getpid()}.{threading.get_ident()}.tmp"
        body_temp = body_path.with_name(body_path.name + suffix)
        meta_temp = meta_path.with_name(meta_path.name + suffix)
        meta = {
            "url": result.url,
            "status": result.status,
            "status_code": result.status_code,
            "content_type": result.content_type,
            "encoding": encoding,
            "note": result.note,
            "fetched_at": utc_now(),
            "sha256": hashlib.sha256(result.content).hexdigest(),
            "adapter_version": "background-adapters-v1",
        }
        try:
            body_temp.write_bytes(result.content)
            meta_temp.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(body_temp, body_path)
            os.replace(meta_temp, meta_path)
        finally:
            body_temp.unlink(missing_ok=True)
            meta_temp.unlink(missing_ok=True)

    def _wait_for_domain(self, url: str) -> None:
        domain = urlparse(url).netloc
        previous = self._last_request.get(domain, 0.0)
        required = random.uniform(self.min_delay, self.max_delay)
        remaining = required - (time.monotonic() - previous)
        if remaining > 0:
            time.sleep(remaining)
        self._last_request[domain] = time.monotonic()

    def _robots_allowed(self, url: str) -> bool:
        parsed = urlparse(url)
        if parsed.path.startswith("/api/") or parsed.netloc.startswith("open.cnkgraph.com"):
            return True
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin in self._robots:
            parser = self._robots[origin]
            return True if parser is None else parser.can_fetch(USER_AGENT, url)
        robots_url = origin + "/robots.txt"
        parser = urllib.robotparser.RobotFileParser()
        parser.set_url(robots_url)
        try:
            if self.host_gate is not None:
                with self.host_gate.slot(robots_url):
                    response = self.session.get(robots_url, timeout=min(self.timeout, 10))
            else:
                response = self.session.get(robots_url, timeout=min(self.timeout, 10))
            if response.status_code == 404:
                self._robots[origin] = None
                return True
            if response.status_code >= 400:
                self._robots[origin] = None
                return True
            parser.parse(response.text.splitlines())
            self._robots[origin] = parser
            return parser.can_fetch(USER_AGENT, url)
        except requests.RequestException:
            self._robots[origin] = None
            return True

    def request(
        self,
        method: str,
        url: str,
        *,
        json_payload: object = None,
        use_cache: bool = True,
        respect_robots: bool = True,
    ) -> FetchResult:
        key = self._cache_key(method, url, json_payload)
        if use_cache:
            cached = self._read_cache(key)
            if cached is not None:
                return cached
        if self.offline:
            return FetchResult(url=url, status="offline_cache_miss", cache_key=key)
        if respect_robots and not self._robots_allowed(url):
            result = FetchResult(
                url=url,
                status="blocked_by_policy",
                cache_key=key,
                note="robots.txt disallows fetch",
            )
            self._write_cache(result)
            return result

        last_note = ""
        last_status_code: int | None = None
        attempts = max(1, self.retries)
        for attempt in range(attempts):
            try:
                if self.host_gate is not None:
                    with self.host_gate.slot(url):
                        response = self.session.request(
                            method,
                            url,
                            json=json_payload,
                            timeout=self.timeout,
                            allow_redirects=True,
                        )
                else:
                    self._wait_for_domain(url)
                    response = self.session.request(
                        method,
                        url,
                        json=json_payload,
                        timeout=self.timeout,
                        allow_redirects=True,
                    )
            except requests.RequestException as exc:
                last_note = str(exc)
                if attempt + 1 < attempts:
                    time.sleep(self._backoff(attempt))
                continue

            content = response.content
            last_status_code = response.status_code
            encoding = response.encoding or ""
            if not encoding or encoding.casefold() == "iso-8859-1":
                encoding = response.apparent_encoding or "utf-8"
            text = content.decode(encoding, errors="replace")
            if any(marker.casefold() in (response.url + "\n" + text).casefold() for marker in LOGIN_MARKERS):
                result = FetchResult(
                    url=response.url,
                    status="blocked_by_policy",
                    status_code=response.status_code,
                    text="",
                    content=b"",
                    content_type=response.headers.get("Content-Type", ""),
                    cache_key=key,
                    note="login or captcha page detected",
                )
                self._write_cache(result)
                return result
            if response.status_code in RETRYABLE_STATUSES:
                last_note = f"HTTP {response.status_code}"
                if attempt + 1 < attempts:
                    retry_after = self._retry_after_seconds(response)
                    time.sleep(self._backoff(attempt, retry_after=retry_after))
                continue
            status = "ok" if 200 <= response.status_code < 300 else "fetch_failed"
            result = FetchResult(
                url=response.url,
                status=status,
                status_code=response.status_code,
                text=text,
                content=content,
                content_type=response.headers.get("Content-Type", ""),
                cache_key=key,
                note="" if status == "ok" else f"HTTP {response.status_code}",
            )
            self._write_cache(result, encoding=encoding)
            return result

        # Retries exhausted: never persist this as a success-bearing cache
        # entry (also skipped by _read_cache) so later runs can retry online.
        return FetchResult(
            url=url,
            status="fetch_failed",
            status_code=last_status_code,
            cache_key=key,
            note=last_note or "retries exhausted",
        )

    def _backoff(self, attempt: int, *, retry_after: float = 0.0) -> float:
        delay = 2.0**attempt
        if retry_after > 0:
            delay = max(delay, retry_after)
        return min(delay, MAX_RETRY_AFTER)

    def _retry_after_seconds(self, response: Any) -> float:
        headers = getattr(response, "headers", {}) or {}
        header = str(headers.get("Retry-After") or "").strip()
        if not header:
            return 0.0
        if header.isdigit():
            return min(float(header), MAX_RETRY_AFTER)
        try:
            stamp = email.utils.parsedate_to_datetime(header)
        except (TypeError, ValueError, OverflowError):
            return 0.0
        if stamp.tzinfo is None:
            return 0.0
        now = datetime.datetime.now(datetime.timezone.utc)
        return max(0.0, min((stamp - now).total_seconds(), MAX_RETRY_AFTER))

    def get_json(self, url: str, *, respect_robots: bool = True) -> tuple[FetchResult, object | None]:
        result = self.request("GET", url, respect_robots=respect_robots)
        return self._reparse_json("GET", url, result, respect_robots=respect_robots)

    def post_json(self, url: str, payload: object) -> tuple[FetchResult, object | None]:
        result = self.request("POST", url, json_payload=payload, respect_robots=False)
        return self._reparse_json("POST", url, result, json_payload=payload, respect_robots=False)

    def _reparse_json(
        self,
        method: str,
        url: str,
        result: FetchResult,
        *,
        json_payload: object = None,
        respect_robots: bool = True,
    ) -> tuple[FetchResult, object | None]:
        if result.status != "ok":
            return result, None
        try:
            return result, json.loads(result.text)
        except json.JSONDecodeError:
            if not self.offline and result.from_cache:
                fresh = self.request(
                    method,
                    url,
                    json_payload=json_payload,
                    use_cache=False,
                    respect_robots=respect_robots,
                )
                if fresh.status != "ok":
                    return fresh, None
                try:
                    return fresh, json.loads(fresh.text)
                except json.JSONDecodeError:
                    return (
                        FetchResult(**{**fresh.__dict__, "status": "parse_failed", "note": "invalid JSON"}),
                        None,
                    )
            return FetchResult(**{**result.__dict__, "status": "parse_failed", "note": "invalid JSON"}), None


def text_content(value: object) -> str:
    if isinstance(value, dict):
        return str(value.get("Content") or value.get("Name") or value.get("Value") or "").strip()
    return str(value or "").strip()


def api_items(payload: object) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("Writings", "WritingList", "Items", "Data", "data", "Result", "result"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return [payload]


def unwrap_mapping(payload: object, key: str) -> dict[str, Any] | None:
    if isinstance(payload, list) and payload and isinstance(payload[0], dict):
        return payload[0]
    if isinstance(payload, dict) and isinstance(payload.get(key), dict):
        return payload[key]
    return payload if isinstance(payload, dict) else None


def find_cnkgraph_writing(poem: dict[str, Any], payload: object) -> tuple[dict[str, Any] | None, float]:
    best: dict[str, Any] | None = None
    best_score = 0.0
    ties = 0
    for item in api_items(payload):
        score = source_match_score(
            poem,
            source_poet=text_content(item.get("Author")),
            source_title=text_content(item.get("Title")),
        )
        if score > best_score:
            best = item
            best_score = score
            ties = 1
        elif score > 0 and score == best_score:
            ties += 1
    if ties > 1:
        # Same author + same title matched by several source works: ambiguous.
        # Never silently pick the first tie.
        return None, best_score
    return best, best_score


def parse_year_range(value: object) -> tuple[int, int, str] | None:
    """``725-727`` -> (725, 727, 'approximate'); ``约725`` -> (725, 725, 'approximate').

    Single bare years stay ``year``; ranges and 约/前后 keep both bounds and are
    marked approximate instead of dropping to the first digit.
    """
    text = str(value or "")
    # Prefer Common Era values so parenthetical era-year annotations such as
    # ``725年（开元13年）`` do not become the false range 13-725.  Keep a
    # short-year fallback for genuinely early dates handled by this adapter.
    tokens = re.findall(r"(?<!\d)\d{3,4}(?!\d)", text)
    if not tokens:
        tokens = re.findall(r"(?<!\d)\d{1,2}(?!\d)", text)
    numbers = [int(m) for m in tokens]
    numbers = [n for n in numbers if 1 <= n <= 3000]
    if not numbers:
        return None
    approx = any(token in text for token in ("约", "約", "前后", "後", "左右"))
    if len(numbers) >= 2:
        return min(numbers), max(numbers), "approximate"
    return numbers[0], numbers[0], "approximate" if approx else "year"


def cnkgraph_place(writing: dict[str, Any]) -> tuple[str, str]:
    region_id = str(writing.get("AuthorPlace") or "").split(",", 1)[0].strip()
    place = ""
    for link in writing.get("Links") or []:
        if not isinstance(link, dict):
            continue
        if str(link.get("ResourcePath") or "").casefold() == "authorplace":
            place = str(link.get("Value") or link.get("Name") or "").strip()
            break
    detail = ""
    if "," in str(writing.get("AuthorPlace") or ""):
        detail = str(writing.get("AuthorPlace")).split(",", 1)[1].strip()
    if detail and detail not in place:
        place = f"{place}·{detail}" if place else detail
    return region_id, place


def normalize_year(value: object) -> int | None:
    match = re.search(r"-?\d{1,4}", str(value or ""))
    return int(match.group(0)) if match else None


def collect_cnkgraph(poem: dict[str, Any], client: HttpCacheClient) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    result, payload = client.post_json(
        CNKGRAPH_FIND,
        {"key": str(poem.get("title") or ""), "exactlyMatch": True, "clauseIndex": "title"},
    )
    status = {
        "poem_key": poem_key(poem),
        "adapter": "cnkgraph",
        "status": result.status,
        "source_url": result.url,
        "note": result.note,
        "checked_at": utc_now(),
    }
    if result.status != "ok" or payload is None:
        return [], status
    writing, score = find_cnkgraph_writing(poem, payload)
    if not writing or score < 0.85:
        note = (
            "ambiguous author/title match; multiple source works tie"
            if (not writing and score > 0)
            else "no author/title match above 0.85"
        )
        status.update(status="insufficient", note=note)
        return [], status

    writing_id = writing.get("Id") or writing.get("ID") or writing.get("id")
    detail_result = result
    if writing_id:
        detail_result, detail_payload = client.get_json(f"{CNKGRAPH_API}/writing/{writing_id}", respect_robots=False)
        detail = unwrap_mapping(detail_payload, "Writing")
        if detail_result.status == "ok" and detail:
            writing = detail
    score = max(
        score,
        source_match_score(
            poem,
            source_poet=text_content(writing.get("Author")),
            source_title=text_content(writing.get("Title")),
        ),
    )
    region_id, historical_place = cnkgraph_place(writing)
    region: dict[str, Any] = {}
    region_result: FetchResult | None = None
    if region_id:
        region_result, region_payload = client.get_json(
            f"{CNKGRAPH_API}/map/region/{region_id}", respect_robots=False
        )
        region = unwrap_mapping(region_payload, "Region") or {}
    modern_place = str(region.get("Name") or region.get("FullName") or historical_place or "").strip()
    year_range = parse_year_range(writing.get("AuthorDate"))
    source_url = f"{CNKGRAPH_API}/writing/{writing_id}" if writing_id else detail_result.url
    evidence = "；".join(
        part
        for part in (
            f"作品：{text_content(writing.get('Author'))}《{text_content(writing.get('Title'))}》",
            f"系年：{writing.get('AuthorDate')}" if writing.get("AuthorDate") else "",
            f"创作地：{historical_place or modern_place}" if historical_place or modern_place else "",
        )
        if part
    )
    common = {
        "evidence_excerpt": evidence,
        "source_key": f"cnkgraph:writing:{writing_id or deterministic_id(source_url)[:16]}",
        "source_name": "古籍文献知识图谱开放API",
        "source_url": source_url,
        "citation": "CNKGraph作品编年与地点数据；具体学术底本以接口说明及人工复核为准",
        "source_locator": f"Writing/{writing_id}" if writing_id else "writing/find",
        "source_grade": "B",
        "access_level": "open_api",
        "license_note": "仅保存结构化字段与必要短引",
        "match_score": score,
        "extraction_method": "cnkgraph_api_v1",
        "raw_cache_key": detail_result.cache_key,
    }
    candidates: list[dict[str, Any]] = []
    if year_range is not None:
        y_start, y_end, y_precision = year_range
        candidates.append(
            make_candidate(
                poem,
                "composition_date",
                {"year_start": y_start, "year_end": y_end, "precision": y_precision},
                **common,
            )
        )
    if historical_place or modern_place:
        candidates.append(
            make_candidate(
                poem,
                "composition_place",
                {
                    "historical_place": historical_place,
                    "modern_place": modern_place,
                    "region_id": region_id,
                    "lon": region.get("Longitude"),
                    "lat": region.get("Latitude"),
                },
                **common,
            )
        )
    status.update(status="collected" if candidates else "insufficient", note=f"{len(candidates)} claims")
    return candidates, status


SECTION_TYPES = {
    "译文": "translation",
    "翻译": "translation",
    "注释": "annotation",
    "创作背景": "historical_context",
    "背景": "historical_context",
    "赏析": "appreciation",
    "鉴赏": "appreciation",
}


def classify_heading(text: str) -> str | None:
    normalized = re.sub(r"\s+", "", text)
    for token, claim_type in SECTION_TYPES.items():
        if token in normalized:
            return claim_type
    return None


def parse_gushiwen_sections(html: str) -> dict[str, Any]:
    try:
        soup = BeautifulSoup(html, "lxml")
    except FeatureNotFound:
        soup = BeautifulSoup(html, "html.parser")
    title_el = soup.select_one("div.cont h1") or soup.find("h1")
    source_el = soup.select_one("div.cont p.source")
    body_el = soup.select_one("div.cont div.contson")
    title = title_el.get_text(" ", strip=True) if title_el else ""
    source_text = source_el.get_text(" ", strip=True) if source_el else ""
    author = ""
    author_links = source_el.select("a") if source_el else []
    author_link = author_links[-1] if author_links else None
    if author_link:
        author = author_link.get_text(" ", strip=True)
    if not author:
        match = re.search(r"[：:]?\s*([^\s\[\]【】]+)$", source_text)
        author = match.group(1) if match else ""
    body = body_el.get_text("\n", strip=True) if body_el else ""

    sections: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for heading in soup.find_all(["h2", "h3", "h4", "strong", "b"]):
        heading_text = heading.get_text(" ", strip=True)
        claim_type = classify_heading(heading_text)
        if not claim_type:
            continue
        container = heading.find_parent(["div", "section", "article", "li"]) or heading.parent
        if container is None:
            continue
        text = re.sub(r"\s+", " ", container.get_text(" ", strip=True)).strip()
        if text.startswith(heading_text):
            text = text[len(heading_text) :].lstrip(" ：:")
        excerpt = normalize_excerpt(text)
        if len(excerpt) < 8:
            continue
        key = (claim_type, excerpt)
        if key in seen:
            continue
        seen.add(key)
        sections.append(
            {
                "claim_type": claim_type,
                "heading": heading_text,
                "excerpt": excerpt,
            }
        )
    return {"title": title, "author": author, "body": body, "sections": sections}


def gushiwen_poem_id(url: object) -> str:
    match = re.search(r"/shiwenv_([0-9a-zA-Z_-]+)\.aspx(?:[?#]|$)", str(url or ""))
    return match.group(1) if match else ""


def collect_gushiwen(poem: dict[str, Any], client: HttpCacheClient) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    url = str(poem.get("source_url") or "").strip()
    if not url:
        source_id = str(poem.get("source_poem_id") or "").strip()
        if source_id:
            url = f"https://www.gushiwen.cn/shiwenv_{source_id}.aspx"
    status = {
        "poem_key": poem_key(poem),
        "adapter": "gushiwen",
        "status": "insufficient",
        "source_url": url,
        "note": "missing source URL",
        "checked_at": utc_now(),
    }
    if not url:
        return [], status
    result = client.request("GET", url, respect_robots=True)
    status.update(status=result.status, source_url=result.url, note=result.note)
    if result.status != "ok":
        return [], status
    parsed = parse_gushiwen_sections(result.text)
    score = source_match_score(
        poem,
        source_poem_id=gushiwen_poem_id(result.url),
        source_poet=parsed.get("author"),
        source_title=parsed.get("title"),
        source_first_line=parsed.get("body"),
    )
    if score < 0.85:
        status.update(status="insufficient", note=f"page match score {score:.2f} below 0.85")
        return [], status
    candidates: list[dict[str, Any]] = []
    for section in parsed["sections"]:
        excerpt = section["excerpt"]
        candidates.append(
            make_candidate(
                poem,
                section["claim_type"],
                {"source_excerpt": excerpt, "heading": section["heading"]},
                evidence_excerpt=excerpt,
                source_key=f"gushiwen:{poem.get('source_poem_id') or deterministic_id(result.url)[:16]}",
                source_name="古诗文网",
                source_url=result.url,
                citation=f"{parsed.get('author')}《{parsed.get('title')}》页面",
                source_locator=section["heading"],
                source_grade="C",
                access_level="public_web",
                license_note="仅保存必要短引；不发布第三方全文",
                match_score=score,
                extraction_method="gushiwen_section_parser_v1",
                raw_cache_key=result.cache_key,
            )
        )
    status.update(status="collected" if candidates else "insufficient", note=f"{len(candidates)} public sections")
    return candidates, status


def parse_chgis_payload(payload: object, *, query_year: int | None = None) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    rows = payload.get("placenames")
    if not isinstance(rows, list):
        return None
    candidates = [row for row in rows if isinstance(row, dict)]
    if not candidates:
        return None

    def row_score(row: dict[str, Any]) -> tuple[int, int]:
        # The service writes ranges as "618-907".  Treat the separator as a
        # range delimiter rather than interpreting the end year as negative.
        years = [int(x) for x in re.findall(r"\d{1,4}", str(row.get("years") or ""))]
        contains_year = 0
        distance = 999999
        if query_year is not None and years:
            start, end = min(years), max(years)
            if start <= query_year <= end:
                contains_year = 1
                distance = 0
            else:
                distance = min(abs(query_year - start), abs(query_year - end))
        return contains_year, -distance

    best = max(candidates, key=row_score)
    coords = [x.strip() for x in str(best.get("xy coordinates") or "").split(",")]
    lon = lat = None
    if len(coords) == 2:
        try:
            lon, lat = float(coords[0]), float(coords[1])
        except ValueError:
            lon = lat = None
    return {
        "chgis_id": best.get("sys_id"),
        "name": best.get("name"),
        "years": best.get("years"),
        "parent": best.get("parent name"),
        "feature_type": best.get("feature type"),
        "lon": lon,
        "lat": lat,
        "uri": best.get("uri"),
    }


def enrich_place_with_chgis(
    place: str,
    year: int | None,
    client: HttpCacheClient,
) -> tuple[dict[str, Any] | None, FetchResult]:
    query = f"?n={quote(place)}&fmt=json"
    if year is not None:
        query += f"&yr={year}"
    result, payload = client.get_json(CHGIS_ENDPOINT + query, respect_robots=False)
    return parse_chgis_payload(payload, query_year=year), result


def cbdb_cache_paths(cache_dir: Path = CACHE_DIR) -> tuple[Path, Path]:
    folder = cache_dir / "cbdb"
    return folder / "latest.sqlite3", folder / "latest.json"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest().lower()


def ensure_cbdb_database(client: HttpCacheClient) -> tuple[Path | None, dict[str, Any]]:
    db_path, manifest_path = cbdb_cache_paths(client.cache_dir)
    if db_path.exists() and manifest_path.exists():
        try:
            cached_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            cached_manifest = {}
        expected_cached_sha = str(
            cached_manifest.get("verified_sha256") or cached_manifest.get("sha256") or ""
        ).strip().lower()
        if re.fullmatch(r"[0-9a-f]{64}", expected_cached_sha):
            try:
                actual_cached_sha = _sha256_file(db_path)
            except OSError:
                actual_cached_sha = ""
            if actual_cached_sha == expected_cached_sha:
                normalized_manifest = {
                    **cached_manifest,
                    "status": "ok",
                    "verified_sha256": actual_cached_sha,
                    "verified_file": db_path.name,
                }
                if normalized_manifest != cached_manifest:
                    atomic_write_text(
                        manifest_path,
                        json.dumps(normalized_manifest, ensure_ascii=False, indent=2) + "\n",
                    )
                return db_path, normalized_manifest
            if client.offline:
                return None, {
                    "status": "checksum_failed",
                    "note": f"cached sqlite sha256 {actual_cached_sha or 'unreadable'} != manifest {expected_cached_sha}",
                }
    if client.offline:
        return None, {"status": "offline_cache_miss"}
    result, manifest = client.get_json(CBDB_MANIFEST, respect_robots=False)
    if result.status != "ok" or not isinstance(manifest, dict):
        return None, {"status": result.status, "note": result.note}
    url = str(manifest.get("huggingface_url") or "")
    expected_sha = str(manifest.get("sha256") or "").lower()
    if not url or not expected_sha:
        return None, {"status": "invalid_manifest"}
    db_path.parent.mkdir(parents=True, exist_ok=True)
    archive_fd, archive_name = tempfile.mkstemp(prefix="cbdb_", suffix=".zip.part", dir=db_path.parent)
    os.close(archive_fd)
    database_fd, database_name = tempfile.mkstemp(prefix="cbdb_", suffix=".sqlite3.part", dir=db_path.parent)
    os.close(database_fd)
    archive = Path(archive_name)
    database_part = Path(database_name)
    try:
        try:
            if client.host_gate is not None:
                gate = client.host_gate.slot(url)
            else:
                gate = nullcontext()
            with gate:
                response_context = client.session.get(
                    url,
                    stream=True,
                    timeout=max(client.timeout, 60),
                    allow_redirects=True,
                )
                with response_context as response:
                    if response.status_code != 200:
                        return None, {"status": "fetch_failed", "note": f"HTTP {response.status_code}"}
                    with archive.open("wb") as handle:
                        for chunk in response.iter_content(chunk_size=1024 * 1024):
                            if chunk:
                                handle.write(chunk)
        except requests.RequestException as exc:
            return None, {"status": "fetch_failed", "note": str(exc)}

        try:
            with zipfile.ZipFile(archive) as zf:
                members = [
                    name for name in zf.namelist()
                    if name.lower().endswith((".sqlite3", ".sqlite", ".db"))
                ]
                if not members:
                    return None, {"status": "archive_missing_database"}
                digest = hashlib.sha256()
                with zf.open(members[0]) as source, database_part.open("wb") as target:
                    while chunk := source.read(1024 * 1024):
                        digest.update(chunk)
                        target.write(chunk)
        except (OSError, zipfile.BadZipFile) as exc:
            return None, {"status": "archive_invalid", "note": str(exc)}

        actual_sha = digest.hexdigest().lower()
        if actual_sha != expected_sha:
            return None, {
                "status": "checksum_failed",
                "note": f"extracted sqlite sha256 {actual_sha} != manifest {expected_sha}",
            }
        os.replace(database_part, db_path)
        stored_manifest = {
            **manifest,
            "status": "ok",
            "verified_sha256": actual_sha,
            "verified_file": db_path.name,
        }
        atomic_write_text(manifest_path, json.dumps(stored_manifest, ensure_ascii=False, indent=2) + "\n")
        return db_path, stored_manifest
    finally:
        archive.unlink(missing_ok=True)
        database_part.unlink(missing_ok=True)


def _find_cbdb_biog_table(conn: sqlite3.Connection) -> tuple[str, list[str]] | None:
    tables = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    ordered = sorted(tables, key=lambda name: ("BIOG_MAIN" not in name.upper(), len(name)))
    for table in ordered:
        columns = [row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')]
        lowered = {col.casefold() for col in columns}
        if any(key in lowered for key in ("c_name_chn", "c_name", "name_chn")):
            return table, columns
    return None


def query_cbdb_identities(db_path: Path, poets: Iterable[str], manifest: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    conn = sqlite3.connect(db_path)
    try:
        found = _find_cbdb_biog_table(conn)
        if not found:
            return [
                {"poet": poet, "status": "schema_unsupported", "checked_at": utc_now()}
                for poet in poets
            ]
        table, columns = found
        by_lower = {column.casefold(): column for column in columns}
        name_col = next(by_lower[key] for key in ("c_name_chn", "c_name", "name_chn") if key in by_lower)
        id_col = next(
            (by_lower[key] for key in ("c_personid", "person_id", "id") if key in by_lower),
            columns[0],
        )
        select_columns = [id_col, name_col]
        for key in ("c_birthyear", "c_deathyear", "c_dy", "c_index_year"):
            if key in by_lower and by_lower[key] not in select_columns:
                select_columns.append(by_lower[key])
        quoted = ",".join(f'"{column}"' for column in select_columns)
        for poet in poets:
            matches = conn.execute(
                f'SELECT {quoted} FROM "{table}" WHERE "{name_col}"=? LIMIT 10',
                (poet,),
            ).fetchall()
            status = "matched" if len(matches) == 1 else "ambiguous" if matches else "not_found"
            rows.append(
                {
                    "poet": poet,
                    "status": status,
                    "matches": [dict(zip(select_columns, row)) for row in matches],
                    "source_name": "China Biographical Database SQLite",
                    "source_url": "https://github.com/cbdb-project/cbdb_sqlite",
                    "source_version": manifest.get("sqlite_filename") or manifest.get("generated_at_utc"),
                    "source_grade": "B",
                    "checked_at": utc_now(),
                }
            )
    finally:
        conn.close()
    return rows
