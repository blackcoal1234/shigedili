"""Exact-selection glossary lookup and isolated AI draft persistence."""
from __future__ import annotations

import hashlib, json, os, re, threading, time, uuid
from collections import deque
from math import ceil
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from .cache import SCHEMA_VERSION
from .glossary import PoetryGlossary

_MEANINGFUL = re.compile(r"[A-Za-z0-9\u3400-\u9fff]")
_HTML_TAG = re.compile(r"<\s*/?\s*[A-Za-z][^>]*>")
_DRAFT_LOCK = threading.Lock()
_TEXT_LIMITS = {"definition": 2000, "inContext": 1000, "category": 100,
                "sourceNote": 300, "model": 200, "source.title": 300,
                "source.url": 2048}
_DRAFT_KEYS = {"draftId", "request", "result"}
_REQUEST_KEYS = {
    "poemId", "title", "poet", "dynasty", "lineNo", "line",
    "startOffset", "endOffset", "term", "mode",
}
_RESULT_KEYS = {
    "term", "definition", "inContext", "category", "method",
    "reviewStatus", "sourceNote", "sources", "model", "draftId", "reused",
}
_DRAFT_METHODS = {"llm", "llm_web"}
_DRAFT_SOURCE_NOTES = {
    "model": "模型生成，待人工审核",
    "web": "模型联网检索，来源见引用，待人工审核",
}

class SelectionGlossaryError(ValueError): pass
class GlossaryProviderError(RuntimeError): pass
class GlossaryDraftStoreError(RuntimeError): pass
class GlossaryRateLimitError(RuntimeError):
    def __init__(self, retry_after: float):
        self.retry_after = max(0.0, retry_after)
        super().__init__("释义请求过于频繁，请稍后再试")


class GlossaryQuota:
    """Small in-process sliding-window quota for model-backed explanations."""

    def __init__(self, *, limit: int = 20, window_seconds: float = 60.0,
                 clock: Callable[[], float] = time.monotonic):
        if limit < 1 or window_seconds <= 0:
            raise ValueError("释义额度必须是正数")
        self.limit = limit
        self.window_seconds = float(window_seconds)
        self._clock = clock
        self._events: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def consume(self, client_key: str) -> None:
        key = client_key.strip() if isinstance(client_key, str) else "unknown"
        key = key or "unknown"
        now = self._clock()
        with self._lock:
            events = self._events.setdefault(key, deque())
            cutoff = now - self.window_seconds
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= self.limit:
                raise GlossaryRateLimitError(events[0] + self.window_seconds - now)
            events.append(now)

class GlossaryModelClient(Protocol):
    def explain(self, *, context: dict[str, Any], mode: str) -> dict[str, Any]: ...

class OpenAICompatibleGlossaryClient:
    def __init__(self, base_url: str, api_key: str, model: str, *, timeout: float = 30,
                 transport: Callable[[str, dict[str, Any]], Mapping[str, Any]] | None = None):
        if not base_url or not api_key or not model:
            raise ValueError("base_url、api_key 和 model 均不能为空")
        self.base_url, self.api_key, self.model = base_url.rstrip("/"), api_key, model
        self.timeout, self._transport = timeout, transport or self._post

    def explain(self, *, context: dict[str, Any], mode: str) -> dict[str, Any]:
        if mode == "web":
            try:
                raw = self._transport(self.base_url + "/responses", {
                    "model": self.model, "tools": [{"type": "web_search"}],
                    "input": _prompt(context, True),
                })
                result = _parse_response(raw)
            except GlossaryProviderError:
                raise
            except Exception as exc:
                raise GlossaryProviderError("provider web_search 请求失败") from exc
            if not result["sources"]:
                raise GlossaryProviderError("Responses API 未返回 url_citation，拒绝无来源降级")
        elif mode == "model":
            try:
                raw = self._transport(self.base_url + "/chat/completions", {
                    "model": self.model,
                    "messages": [{"role": "user", "content": _prompt(context)}],
                    "response_format": {"type": "json_object"},
                })
                content = raw["choices"][0]["message"]["content"]
                result = json.loads(content) if isinstance(content, str) else content
            except Exception as exc:
                raise GlossaryProviderError("provider chat/completions 请求或响应无效") from exc
            if not isinstance(result, dict):
                raise GlossaryProviderError("chat/completions 结果必须是 JSON 对象")
        else:
            raise ValueError("mode 必须是 model 或 web")
        result["model"] = self.model
        return result

    def _post(self, endpoint: str, body: dict[str, Any]) -> Mapping[str, Any]:
        request = Request(endpoint, json.dumps(body, ensure_ascii=False).encode(), {
            "Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"
        }, method="POST")
        try:
            with urlopen(request, timeout=self.timeout) as response:
                result = json.loads(response.read().decode())
        except HTTPError as exc:
            raise GlossaryProviderError(f"provider HTTP {exc.code}") from exc
        except (URLError, OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise GlossaryProviderError("provider 请求失败") from exc
        if not isinstance(result, Mapping):
            raise GlossaryProviderError("provider 响应必须是 JSON 对象")
        return result

class GlossaryDraftStore:
    def __init__(self, path: Path): self.path = Path(path).expanduser().resolve()
    @property
    def lock_path(self) -> Path:
        return self.path.with_name(self.path.name + ".lock")

    @contextmanager
    def _locked(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with _DRAFT_LOCK, self.lock_path.open("a+b") as handle:
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                yield
            finally:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _read(self) -> dict[str, Any]:
        if not self.path.is_file():
            return {"version": SCHEMA_VERSION, "drafts": []}
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise GlossaryDraftStoreError("草稿库损坏或无法读取") from exc
        if (not isinstance(loaded, dict)
                or loaded.get("version") != SCHEMA_VERSION
                or not isinstance(loaded.get("drafts"), list)):
            raise GlossaryDraftStoreError("草稿库结构无效")
        seen: set[str] = set()
        for item in loaded["drafts"]:
            if not isinstance(item, Mapping):
                raise GlossaryDraftStoreError("草稿记录结构无效")
            draft_id = item.get("draftId")
            if not isinstance(draft_id, str) or not draft_id or draft_id in seen:
                raise GlossaryDraftStoreError("草稿 ID 无效或重复")
            seen.add(draft_id)
            _validate_draft_record(item)
        return loaded

    def find(self, draft_id: str) -> dict[str, Any] | None:
        with self._locked():
            return self._find_unlocked(self._read(), draft_id)

    @staticmethod
    def _find_unlocked(payload: Mapping[str, Any], draft_id: str) -> dict[str, Any] | None:
        for item in payload["drafts"]:
            if isinstance(item, Mapping) and item.get("draftId") == draft_id:
                _validate_draft_record(item)
                result = item["result"]
                return dict(result)
        return None

    def get_or_create(self, draft_id: str, request: Mapping[str, Any],
                      producer: Callable[[], Mapping[str, Any]],
                      before_produce: Callable[[], None] | None = None
                      ) -> tuple[dict[str, Any], bool]:
        """Find or produce one draft while retaining the OS lock across production."""
        with self._locked():
            payload = self._read()
            existing = self._find_unlocked(payload, draft_id)
            if existing is not None:
                existing["reused"] = True
                return existing, True
            if before_produce is not None:
                before_produce()
            result = dict(producer())
            record = {"draftId": draft_id, "request": dict(request), "result": result}
            _validate_draft_record(record)
            drafts = [x for x in payload["drafts"]
                      if not isinstance(x, Mapping) or x.get("draftId") != draft_id]
            drafts.append(record)
            drafts.sort(key=lambda x: str(x.get("draftId", "")))
            temp = self.path.with_name(f".{self.path.name}.{uuid.uuid4().hex}.tmp")
            try:
                temp.write_text(json.dumps({"version": SCHEMA_VERSION, "drafts": drafts},
                                ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                                encoding="utf-8")
                os.replace(temp, self.path)
            finally:
                temp.unlink(missing_ok=True)
            return result, False

    def save(self, draft_id: str, request: Mapping[str, Any], result: Mapping[str, Any]):
        with self._locked():
            payload = self._read()
            record = {"draftId": draft_id, "request": dict(request), "result": dict(result)}
            _validate_draft_record(record)
            drafts = [x for x in payload["drafts"]
                      if not isinstance(x, Mapping) or x.get("draftId") != draft_id]
            drafts.append(record)
            drafts.sort(key=lambda x: str(x.get("draftId", "")))
            temp = self.path.with_name(f".{self.path.name}.{uuid.uuid4().hex}.tmp")
            try:
                temp.write_text(json.dumps({"version": SCHEMA_VERSION, "drafts": drafts},
                                ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
                os.replace(temp, self.path)
            finally: temp.unlink(missing_ok=True)
    def status(self):
        count, error = 0, None
        if self.path.is_file():
            try:
                with self._locked():
                    count = len(self._read()["drafts"])
            except GlossaryDraftStoreError:
                error = "草稿库损坏或无法读取"
        return {"path": str(self.path), "exists": self.path.is_file(),
                "draftCount": count, "error": error}

class GlossarySelectionService:
    def __init__(self, repository: Any, glossary: PoetryGlossary, *,
                 model_client: GlossaryModelClient | None = None,
                 draft_store: GlossaryDraftStore | None = None, model_name: str = "",
                 quota: GlossaryQuota | None = None):
        self.repository, self.glossary = repository, glossary
        self.model_client, self.model_name = model_client, model_name
        self.quota = quota
        self.draft_store = draft_store or GlossaryDraftStore(
            glossary.project_root / "data" / "poetry_glossary_drafts.json")

    def status(self):
        snapshot = self.glossary.snapshot()
        return _response("ok", "释义状态来自已发布只读词典与独立待审草稿库。", {
            "configured": self.model_client is not None,
            "model": self.model_name or getattr(self.model_client, "model", None),
            "glossaryVersion": snapshot.version, "publishedCount": len(snapshot.entries),
            "glossaryError": snapshot.error, "draftStore": self.draft_store.status()})

    def explain(self, *, poem_id: int | str, line_no: int, start_offset: int,
                end_offset: int, mode: str, client_key: str | None = None):
        term = ""
        try:
            context, term = self._selection(poem_id, line_no, start_offset, end_offset, mode)
            local = self._published_exact(term)
            if local:
                return _response("ok", "精确选区命中已发布本地词典；未调用模型。", {
                    "term": term, "definition": local.definition, "inContext": local.in_context,
                    "category": local.category, "method": "local", "reviewStatus": "published",
                    "sourceNote": local.source_note, "sources": [], "model": None,
                    "draftId": None, "reused": False})
            if self.model_client is None:
                return _response("source_error", "未配置释义模型，未写入草稿。",
                                 _empty(term, mode, "未配置释义模型"))
            model = self.model_name or getattr(self.model_client, "model", "")
            model = _text(model, "model", True)
            draft_id = _draft_id(
                poem_id, line_no, start_offset, end_offset, mode, model
            )
            def produce():
                explain = getattr(self.model_client, "explain", None)
                if callable(explain):
                    raw = explain(context=context, mode=mode)
                else:
                    legacy = getattr(self.model_client, "explain_selection", None)
                    if not callable(legacy):
                        raise TypeError("模型客户端必须实现 explain(context=..., mode=...)")
                    raw = legacy({**context, "mode": mode})
                try:
                    normalized = _normalize(raw, mode)
                except SelectionGlossaryError as exc:
                    raise GlossaryProviderError("provider 返回内容不符合安全约束") from exc
                return {"term": term, **normalized,
                        "method": "llm_web" if mode == "web" else "llm",
                        "reviewStatus": "draft", "draftId": draft_id,
                        "model": model, "reused": False,
                        "sourceNote": ("模型联网检索，来源见引用，待人工审核"
                                       if mode == "web"
                                       else "模型生成，待人工审核")}
            result, reused = self.draft_store.get_or_create(
                draft_id, context, produce,
                before_produce=(
                    (lambda: self.quota.consume(client_key or "local"))
                    if self.quota is not None else None
                ),
            )
            result["reused"] = reused
            return _response("ok", "模型释义仅保存到独立待审草稿库。", result)
        except GlossaryRateLimitError as exc:
            payload = _empty(term, mode, "释义请求过于频繁，请稍后再试")
            payload["retryAfterSeconds"] = ceil(exc.retry_after)
            return _response("rate_limited", "达到单客户端释义额度，未调用模型。", payload)
        except SelectionGlossaryError as exc:
            return _response("invalid_request", str(exc), _empty(term, mode, str(exc)))
        except Exception:
            note = "释义服务暂时不可用，未写入新草稿。"
            return _response("source_error", note, _empty(term, mode, note))

    def _selection(self, poem_id, line_no, start, end, mode):
        if mode not in {"model", "web"}: raise SelectionGlossaryError("mode 必须是 model 或 web")
        if isinstance(line_no, bool) or not isinstance(line_no, int) or line_no < 1:
            raise SelectionGlossaryError("line_no 必须是正整数")
        if any(isinstance(x, bool) or not isinstance(x, int) for x in (start, end)):
            raise SelectionGlossaryError("选区偏移必须是整数")
        poem = self.repository.get_poem(poem_id)
        if poem is None: raise SelectionGlossaryError("诗歌不存在")
        line = next((x for x in poem.get("lines", ()) if x.get("lineNo") == line_no), None)
        if line is None or not isinstance(line.get("text"), str):
            raise SelectionGlossaryError("行号不存在或诗句文本无效")
        text = line["text"]
        if not 0 <= start < end <= len(text): raise SelectionGlossaryError("选区超出诗句范围")
        term = text[start:end]
        if not 1 <= len(term) <= 32: raise SelectionGlossaryError("选区长度必须为 1 至 32 字")
        if not _MEANINGFUL.search(term): raise SelectionGlossaryError("选区必须包含字母、数字或汉字")
        return ({"poemId": poem_id, "title": poem.get("title"), "poet": poem.get("poet"),
                 "dynasty": poem.get("dynasty"), "lineNo": line_no, "line": text,
                 "startOffset": start, "endOffset": end, "term": term, "mode": mode}, term)
    def _published_exact(self, term):
        folded = term.casefold()
        return next((x for x in self.glossary.snapshot().entries
                     if any(f.casefold() == folded for f in x.forms)), None)

SelectionGlossaryService = GlossarySelectionService


def _validate_draft_record(record: Mapping[str, Any]) -> None:
    """Reject tampered drafts before they can be reused or overwritten."""
    try:
        if set(record) != _DRAFT_KEYS:
            raise ValueError("草稿记录字段无效")
        draft_id = record.get("draftId")
        request = record.get("request")
        result = record.get("result")
        if not isinstance(draft_id, str) or not draft_id:
            raise ValueError("草稿 ID 无效")
        if not isinstance(request, Mapping) or not isinstance(result, Mapping):
            raise ValueError("草稿请求或结果无效")
        if set(request) != _REQUEST_KEYS or set(result) != _RESULT_KEYS:
            raise ValueError("草稿字段不完整或包含未知字段")

        poem_id = request["poemId"]
        if (isinstance(poem_id, bool) or not isinstance(poem_id, (str, int))
                or not str(poem_id).strip()):
            raise ValueError("poemId 无效")
        for field in ("title", "poet", "dynasty"):
            value = request[field]
            if value is not None:
                _text(value, field)
        line = _text(request["line"], "line", True)
        term = _text(request["term"], "term", True)
        line_no = request["lineNo"]
        start = request["startOffset"]
        end = request["endOffset"]
        if any(isinstance(value, bool) or not isinstance(value, int)
               for value in (line_no, start, end)):
            raise ValueError("草稿偏移无效")
        if line_no < 1 or not 0 <= start < end <= len(line):
            raise ValueError("草稿偏移超出范围")
        if len(term) > 32 or line[start:end] != term:
            raise ValueError("草稿选区与原句不一致")
        mode = request["mode"]
        if mode not in {"model", "web"}:
            raise ValueError("草稿模式无效")

        model = _text(result["model"], "model", True)
        if _text(result["term"], "term", True) != term:
            raise ValueError("草稿词语与请求不一致")
        if _text(result["definition"], "definition", True) is None:
            raise ValueError("草稿释义为空")
        _text(result["inContext"], "inContext")
        _text(result["category"], "category")
        if result["method"] != ("llm_web" if mode == "web" else "llm"):
            raise ValueError("草稿方法与模式不一致")
        if result["reviewStatus"] != "draft":
            raise ValueError("只能复用待审草稿")
        if _text(result["sourceNote"], "sourceNote", True) != _DRAFT_SOURCE_NOTES[mode]:
            raise ValueError("草稿来源备注无效")
        if not isinstance(result["reused"], bool):
            raise ValueError("草稿 reused 字段无效")
        if result["draftId"] != draft_id:
            raise ValueError("草稿 ID 不一致")
        expected_id = _draft_id(
            poem_id, line_no, start, end, mode, model
        )
        if draft_id != expected_id:
            raise ValueError("草稿 ID 与请求内容不一致")
        _validate_persisted_sources(result["sources"], mode)
    except (SelectionGlossaryError, TypeError, ValueError, KeyError) as exc:
        if isinstance(exc, GlossaryDraftStoreError):
            raise
        raise GlossaryDraftStoreError("草稿记录结构无效或已被篡改") from exc


def _validate_persisted_sources(value: Any, mode: str) -> None:
    if not isinstance(value, list) or len(value) > 5:
        raise ValueError("草稿来源列表无效")
    if mode == "model" and value:
        raise ValueError("模型释义不得携带未核验来源")
    seen: set[tuple[str, str | None]] = set()
    for item in value:
        if not isinstance(item, Mapping) or set(item) - {"url", "title"} or "url" not in item:
            raise ValueError("草稿来源结构无效")
        url = _text(item["url"], "source.url", True)
        title = _text(item.get("title"), "source.title")
        parsed = urlparse(url)
        if (parsed.scheme not in {"http", "https"} or not parsed.netloc
                or parsed.username is not None or parsed.password is not None):
            raise ValueError("草稿来源 URL 无效")
        key = (url, title)
        if key in seen:
            raise ValueError("草稿来源不得重复")
        seen.add(key)

def _response(status, note, payload):
    return {"status": status, "schemaVersion": SCHEMA_VERSION, "sourceHashes": {},
            "methodNote": note, "payload": payload}
def _empty(term, mode, note):
    return {"term": term, "definition": None, "inContext": None, "category": None,
            "method": "llm_web" if mode == "web" else "llm", "reviewStatus": "source_error",
            "sourceNote": note, "sources": [], "model": None, "draftId": None,
            "error": note, "reused": False}
def _text(value, field, required=False):
    if value is None:
        if required: raise SelectionGlossaryError(f"{field} 不能为空")
        return None
    if not isinstance(value, str): raise SelectionGlossaryError(f"{field} 必须是纯文本")
    value = value.strip()
    if required and not value: raise SelectionGlossaryError(f"{field} 不能为空")
    if len(value) > _TEXT_LIMITS.get(field, 2000):
        raise SelectionGlossaryError(f"{field} 超过长度限制")
    if _HTML_TAG.search(value):
        raise SelectionGlossaryError(f"{field} 不得包含 HTML 标签")
    if any(ord(x) < 32 and x not in "\n\r\t" for x in value):
        raise SelectionGlossaryError(f"{field} 包含非法控制字符")
    return value or None
def _sources(value):
    result = []
    for item in (value[:5] if isinstance(value, list) else []):
        if not isinstance(item, Mapping): continue
        try: title, url = _text(item.get("title"), "source.title"), _text(item.get("url"), "source.url", True)
        except SelectionGlossaryError: continue
        parsed = urlparse(url or "")
        if (parsed.scheme not in {"http", "https"} or not parsed.netloc
                or parsed.username is not None or parsed.password is not None):
            continue
        source = {"url": url}
        if title: source["title"] = title
        if source not in result: result.append(source)
    return result
def _normalize(raw, mode):
    if not isinstance(raw, Mapping): raise SelectionGlossaryError("模型结果必须是对象")
    return {"definition": _text(raw.get("definition"), "definition", True),
            "inContext": _text(raw.get("inContext"), "inContext"),
            "category": _text(raw.get("category"), "category"),
            "sourceNote": None,
            "sources": _sources(raw.get("sources")) if mode == "web" else [],
            "model": _text(raw.get("model"), "model")}
def _draft_id(poem_id, line, start, end, mode, model):
    raw = json.dumps([poem_id, line, start, end, mode, model],
                     ensure_ascii=False, separators=(",", ":"))
    return "gloss-draft-" + hashlib.sha256(raw.encode()).hexdigest()[:24]
def _prompt(context, sources=False):
    rule = "必须联网核对，并仅依据可引用网页回答。" if sources else "不得编造来源。"
    return "解释所选诗句词语，返回 JSON 对象，字段为 definition、inContext、category。" + rule + "\n上下文：" + json.dumps(context, ensure_ascii=False)
def _parse_response(raw):
    text, annotations = raw.get("output_text"), []
    for output in raw.get("output", []) if isinstance(raw.get("output"), list) else []:
        if not isinstance(output, Mapping): continue
        for content in output.get("content", []) if isinstance(output.get("content"), list) else []:
            if not isinstance(content, Mapping): continue
            if not text and isinstance(content.get("text"), str): text = content["text"]
            if isinstance(content.get("annotations"), list): annotations += content["annotations"]
    if not isinstance(text, str): raise GlossaryProviderError("Responses API 缺少 output_text")
    try: result = json.loads(text)
    except json.JSONDecodeError as exc:
        raise GlossaryProviderError("Responses API output_text 不是有效 JSON") from exc
    if not isinstance(result, dict): raise GlossaryProviderError("Responses API 输出必须是 JSON 对象")
    citations = []
    for note in annotations:
        if not isinstance(note, Mapping) or note.get("type") != "url_citation": continue
        cite = note.get("url_citation") if isinstance(note.get("url_citation"), Mapping) else note
        citations.append({"title": cite.get("title"), "url": cite.get("url")})
    result["sources"] = _sources(citations)
    return result
