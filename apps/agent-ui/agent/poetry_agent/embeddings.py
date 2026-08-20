"""SiliconFlow embedding client and read-only vector sidecar repository.

The vector index is deliberately separate from the canonical poetry SQLite
snapshot.  A small ``current.json`` pointer selects one immutable artifact so
Windows readers never observe a half-published database/manifest pair.
"""

from __future__ import annotations

from array import array
from collections import OrderedDict
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import struct
import threading
import time
from typing import Any, Callable, Iterable, Iterator, Mapping, Sequence
from urllib.parse import urlsplit

import httpx

from .knowledge import manifest_path_for, sha256_path


EMBEDDING_SCHEMA_VERSION = "embedding-1.0"
POINTER_SCHEMA_VERSION = "embedding-pointer-1.0"
TEXT_VERSION = "poetry-metadata-v1"
DEFAULT_BASE_URL = "https://api.siliconflow.cn/v1"
DEFAULT_MODEL = "BAAI/bge-m3"
MAX_EMBEDDING_CHUNK_CHARS = 7000


def redact_secret(message: object, secret: str = "") -> str:
    """Keep provider diagnostics useful without echoing credentials."""

    text = str(message)
    if secret:
        text = text.replace(secret, "[REDACTED]")
    return text


class EmbeddingError(RuntimeError):
    """Base class for embedding provider and index failures."""


class EmbeddingProviderError(EmbeddingError):
    """SiliconFlow rejected a request or returned an invalid response."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class EmbeddingUnavailableError(EmbeddingError):
    """The vector sidecar is absent, stale, or cannot serve queries."""


@dataclass(frozen=True)
class EmbeddingProviderConfig:
    base_url: str = DEFAULT_BASE_URL
    api_key: str = ""
    model: str = DEFAULT_MODEL
    batch_size: int = 16
    concurrency: int = 8
    timeout: float = 60.0
    retries: int = 4

    def __post_init__(self) -> None:
        if not self.base_url.strip():
            raise ValueError("embedding base_url 不能为空")
        parsed = urlsplit(self.base_url.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("embedding base_url 必须是 http(s) URL")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("embedding base_url 不得包含凭据、查询参数或片段")
        if not self.model.strip():
            raise ValueError("embedding model 不能为空")
        if not 1 <= self.batch_size <= 32:
            raise ValueError("embedding batch_size 必须位于 1..32")
        if not 1 <= self.concurrency <= 64:
            raise ValueError("embedding concurrency 必须位于 1..64")
        if self.timeout <= 0:
            raise ValueError("embedding timeout 必须大于 0")
        if not 0 <= self.retries <= 10:
            raise ValueError("embedding retries 必须位于 0..10")

    @property
    def endpoint(self) -> str:
        base = self.base_url.strip().rstrip("/")
        return base if base.endswith("/embeddings") else base + "/embeddings"


def _normalize_vector(values: Sequence[Any]) -> list[float]:
    if not values:
        raise EmbeddingProviderError("embedding 向量为空")
    result: list[float] = []
    squared = 0.0
    for raw in values:
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            raise EmbeddingProviderError("embedding 含非数值元素")
        value = float(raw)
        if not math.isfinite(value):
            raise EmbeddingProviderError("embedding 含 NaN 或无穷值")
        result.append(value)
        squared += value * value
    if squared <= 0:
        raise EmbeddingProviderError("embedding 范数必须大于 0")
    scale = 1.0 / math.sqrt(squared)
    return [value * scale for value in result]


def validate_embedding_response(
    payload: Any,
    expected_count: int,
) -> tuple[list[list[float]], str | None, dict[str, int]]:
    """Validate and reorder an OpenAI-compatible embeddings response."""

    if not isinstance(payload, Mapping):
        raise EmbeddingProviderError("embedding 响应必须是 JSON 对象")
    data = payload.get("data")
    if not isinstance(data, list) or len(data) != expected_count:
        raise EmbeddingProviderError(
            f"embedding 响应数量不匹配: expected={expected_count} actual="
            f"{len(data) if isinstance(data, list) else 'invalid'}"
        )
    ordered: list[list[float] | None] = [None] * expected_count
    dimension: int | None = None
    for item in data:
        if not isinstance(item, Mapping):
            raise EmbeddingProviderError("embedding data 项必须是对象")
        index = item.get("index")
        if isinstance(index, bool) or not isinstance(index, int):
            raise EmbeddingProviderError("embedding data.index 必须是整数")
        if not 0 <= index < expected_count or ordered[index] is not None:
            raise EmbeddingProviderError("embedding data.index 重复或越界")
        vector = _normalize_vector(item.get("embedding", []))
        if dimension is None:
            dimension = len(vector)
        elif len(vector) != dimension:
            raise EmbeddingProviderError("embedding 响应维度不一致")
        ordered[index] = vector
    if any(vector is None for vector in ordered):
        raise EmbeddingProviderError("embedding 响应缺少 index")
    usage_raw = payload.get("usage")
    usage: dict[str, int] = {}
    if isinstance(usage_raw, Mapping):
        for key in ("prompt_tokens", "total_tokens"):
            value = usage_raw.get(key)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                usage[key] = value
    model = payload.get("model")
    return [vector for vector in ordered if vector is not None], (
        str(model) if isinstance(model, str) and model else None
    ), usage


def split_embedding_text(
    text: object,
    *,
    max_chars: int = MAX_EMBEDDING_CHUNK_CHARS,
) -> list[str]:
    """Split long text below the bge-m3 limit without discarding its tail."""

    clean = str(text).strip()
    if not clean:
        raise ValueError("embedding input 必须包含非空文本")
    if max_chars <= 0:
        raise ValueError("embedding chunk max_chars 必须大于 0")
    chunks: list[str] = []
    start = 0
    while start < len(clean):
        end = min(len(clean), start + max_chars)
        if end < len(clean):
            boundary_floor = start + (max_chars * 4 // 5)
            candidates = [
                clean.rfind(mark, boundary_floor, end) + 1
                for mark in ("\n", "。", "！", "？", "；")
            ]
            natural_end = max(candidates)
            if natural_end > boundary_floor:
                end = natural_end
        chunk = clean[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start = end
    if not chunks:
        raise ValueError("embedding input 必须包含非空文本")
    return chunks


class SiliconFlowEmbeddingClient:
    """Small validated client for ``POST /v1/embeddings``."""

    RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}

    def __init__(
        self,
        config: EmbeddingProviderConfig,
        *,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not config.api_key.strip():
            raise ValueError("AGENT_EMBEDDING_API_KEY 未配置")
        self.config = config
        self._client = client or httpx.Client(timeout=config.timeout)
        self._owns_client = client is None
        self._sleep = sleep

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "SiliconFlowEmbeddingClient":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    @staticmethod
    def _retry_delay(response: httpx.Response | None, attempt: int) -> float:
        if response is not None:
            raw = response.headers.get("Retry-After", "").strip()
            try:
                if raw:
                    return min(60.0, max(0.0, float(raw)))
            except ValueError:
                pass
        return min(30.0, 0.5 * (2**attempt))

    def _embed_request(
        self, texts: Sequence[str]
    ) -> tuple[list[list[float]], str, dict[str, int]]:
        """Send one provider-sized request and validate its response."""

        if not texts or len(texts) > self.config.batch_size:
            raise ValueError(
                f"embedding request 必须包含 1..{self.config.batch_size} 条文本"
            )
        response_model = self.config.model
        response: httpx.Response | None = None
        last_error: Exception | None = None
        for attempt in range(self.config.retries + 1):
            response = None
            try:
                response = self._client.post(
                    self.config.endpoint,
                    headers={
                        "Authorization": f"Bearer {self.config.api_key}",
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.config.model,
                        "input": list(texts),
                        "encoding_format": "float",
                    },
                )
                if response.status_code >= 400:
                    message = redact_secret(response.text[:500], self.config.api_key)
                    error = EmbeddingProviderError(
                        f"SiliconFlow embeddings HTTP {response.status_code}: {message}",
                        status_code=response.status_code,
                    )
                    if (
                        response.status_code not in self.RETRYABLE_STATUS
                        or attempt >= self.config.retries
                    ):
                        raise error
                    last_error = error
                else:
                    try:
                        payload = response.json()
                    except (ValueError, json.JSONDecodeError) as exc:
                        raise EmbeddingProviderError("embedding 响应不是有效 JSON") from exc
                    vectors, model, usage = validate_embedding_response(
                        payload, len(texts)
                    )
                    return vectors, model or response_model, usage
            except httpx.HTTPError as exc:
                last_error = EmbeddingProviderError(
                    f"SiliconFlow embeddings 网络失败: "
                    f"{redact_secret(exc, self.config.api_key)}"
                )
                if attempt >= self.config.retries:
                    raise last_error from exc
            if attempt < self.config.retries:
                self._sleep(self._retry_delay(response, attempt))
        raise EmbeddingProviderError(
            "SiliconFlow embeddings 请求失败: "
            f"{redact_secret(last_error or 'unknown', self.config.api_key)}"
        )

    def embed(self, texts: Sequence[str]) -> tuple[list[list[float]], dict[str, Any]]:
        clean = [str(text).strip() for text in texts]
        if not clean or any(not text for text in clean):
            raise ValueError("embedding input 必须包含非空文本")
        if len(clean) > self.config.batch_size:
            raise ValueError(
                f"embedding input 超过 batch_size={self.config.batch_size}"
            )
        expanded: list[str] = []
        owners: list[int] = []
        weights: list[int] = []
        for owner, text in enumerate(clean):
            for chunk in split_embedding_text(text):
                expanded.append(chunk)
                owners.append(owner)
                weights.append(len(chunk))

        chunk_vectors: list[list[float]] = []
        usage = {"prompt_tokens": 0, "total_tokens": 0}
        response_model = self.config.model
        request_count = 0
        for offset in range(0, len(expanded), self.config.batch_size):
            vectors, model, request_usage = self._embed_request(
                expanded[offset : offset + self.config.batch_size]
            )
            if model != response_model:
                raise EmbeddingProviderError(
                    f"provider 模型不一致: {model} != {response_model}"
                )
            chunk_vectors.extend(vectors)
            request_count += 1
            for key in usage:
                usage[key] += int(request_usage.get(key, 0))

        dimension = len(chunk_vectors[0])
        sums = [[0.0] * dimension for _ in clean]
        for vector, owner, weight in zip(chunk_vectors, owners, weights):
            if len(vector) != dimension:
                raise EmbeddingProviderError("embedding 响应维度不一致")
            for index, value in enumerate(vector):
                sums[owner][index] += value * weight
        return [_normalize_vector(values) for values in sums], {
            "model": response_model,
            "usage": usage,
            "request_count": request_count,
        }


def canonical_line_text(row: Mapping[str, Any]) -> str:
    return (
        f"诗题：{row['title']}\n作者：{row['poet']}\n朝代：{row['dynasty']}\n"
        f"诗句：{row['text']}"
    )


def canonical_poem_text(row: Mapping[str, Any]) -> str:
    return (
        f"诗题：{row['title']}\n作者：{row['poet']}\n朝代：{row['dynasty']}\n"
        f"全文：{row['body']}"
    )


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EmbeddingUnavailableError(f"向量元数据读取失败: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise EmbeddingUnavailableError(f"向量元数据必须是对象: {path}")
    return value


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


class PoetryEmbeddingRepository:
    """Validate one immutable vector artifact and execute cosine search."""

    def __init__(
        self,
        root: Path,
        knowledge_path: Path,
        *,
        client: SiliconFlowEmbeddingClient | None = None,
        query_cache_size: int = 128,
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        self.knowledge_path = Path(knowledge_path).expanduser().resolve()
        self.client = client
        self.query_cache_size = max(0, query_cache_size)
        self._cache: OrderedDict[tuple[str, str], list[float]] = OrderedDict()
        self._cache_lock = threading.Lock()
        self._activation_lock = threading.Lock()
        self._activation_key: tuple[int, ...] | None = None
        self._activation: dict[str, Any] | None = None
        self._knowledge_hash_key: tuple[int, int, int, int] | None = None
        self._knowledge_hash: str | None = None

    @property
    def pointer_path(self) -> Path:
        return self.root / "current.json"

    def _activation_cache_key(self) -> tuple[int, ...]:
        try:
            pointer_stat = self.pointer_path.stat()
        except OSError as exc:
            raise EmbeddingUnavailableError(
                f"向量索引指针读取失败: {exc}"
            ) from exc
        parts: list[int] = [
            pointer_stat.st_dev,
            pointer_stat.st_ino,
            pointer_stat.st_size,
            pointer_stat.st_mtime_ns,
        ]
        for path in (self.knowledge_path, manifest_path_for(self.knowledge_path)):
            try:
                stat = path.stat()
            except OSError:
                parts.extend((0, 0, 0, 0))
            else:
                parts.extend((stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns))
        return tuple(parts)

    def _activate(self) -> dict[str, Any]:
        if not self.pointer_path.is_file():
            raise EmbeddingUnavailableError(
                f"向量索引指针不存在: {self.pointer_path}"
            )
        key = self._activation_cache_key()
        if self._activation_key == key and self._activation is not None:
            return self._activation
        with self._activation_lock:
            key = self._activation_cache_key()
            if self._activation_key == key and self._activation is not None:
                return self._activation
            pointer = _read_json(self.pointer_path)
            if pointer.get("schemaVersion") != POINTER_SCHEMA_VERSION:
                raise EmbeddingUnavailableError("向量 current.json schemaVersion 无效")
            relative = pointer.get("artifact")
            if not isinstance(relative, str) or not relative.strip():
                raise EmbeddingUnavailableError("向量 current.json 缺少 artifact")
            artifact = (self.root / relative).resolve()
            if not _inside(artifact, self.root) or not artifact.is_dir():
                raise EmbeddingUnavailableError("向量 artifact 路径越界或不存在")
            manifest_path = artifact / "manifest.json"
            manifest = _read_json(manifest_path)
            if manifest.get("schemaVersion") != EMBEDDING_SCHEMA_VERSION:
                raise EmbeddingUnavailableError("向量 manifest schemaVersion 无效")
            expected_manifest_hash = pointer.get("manifestSha256")
            if (
                not isinstance(expected_manifest_hash, str)
                or sha256_path(manifest_path) != expected_manifest_hash
            ):
                raise EmbeddingUnavailableError("向量 manifest 哈希不一致")
            knowledge_manifest_path = manifest_path_for(self.knowledge_path)
            if not self.knowledge_path.is_file() or not knowledge_manifest_path.is_file():
                raise EmbeddingUnavailableError("主知识库或 manifest 不存在")
            knowledge_manifest = _read_json(knowledge_manifest_path)
            knowledge = manifest.get("knowledge")
            if not isinstance(knowledge, Mapping):
                raise EmbeddingUnavailableError("向量 manifest 缺少 knowledge 绑定")
            if knowledge.get("buildId") != knowledge_manifest.get("buildId"):
                raise EmbeddingUnavailableError("向量索引绑定了不同的知识库 buildId")
            database_hash = knowledge_manifest.get("databaseSha256")
            if (
                not isinstance(database_hash, str)
                or len(database_hash) != 64
                or knowledge.get("databaseSha256") != database_hash
            ):
                raise EmbeddingUnavailableError("向量索引绑定的知识库哈希已过期")
            try:
                database_stat = self.knowledge_path.stat()
                database_key = (
                    database_stat.st_dev,
                    database_stat.st_ino,
                    database_stat.st_size,
                    database_stat.st_mtime_ns,
                )
                if self._knowledge_hash_key != database_key:
                    actual_database_hash = sha256_path(self.knowledge_path)
                    if actual_database_hash != database_hash:
                        raise EmbeddingUnavailableError(
                            "主知识库文件与 manifest 哈希不一致"
                        )
                    self._knowledge_hash_key = database_key
                    self._knowledge_hash = actual_database_hash
                elif self._knowledge_hash != database_hash:
                    raise EmbeddingUnavailableError("主知识库哈希缓存不一致")
            except OSError as exc:
                raise EmbeddingUnavailableError(
                    f"主知识库文件状态读取失败: {exc}"
                ) from exc
            source_hashes = knowledge.get("sourceHashes")
            if source_hashes is not None and source_hashes != knowledge_manifest.get(
                "sourceHashes"
            ):
                raise EmbeddingUnavailableError("向量索引绑定的知识库源哈希已过期")
            dimension = manifest.get("dimension")
            if isinstance(dimension, bool) or not isinstance(dimension, int) or dimension <= 0:
                raise EmbeddingUnavailableError("向量 manifest dimension 无效")
            files = manifest.get("files")
            if not isinstance(files, Mapping):
                raise EmbeddingUnavailableError("向量 manifest 缺少 files")
            metadata_entry = files.get("metadata")
            if not isinstance(metadata_entry, Mapping):
                raise EmbeddingUnavailableError("向量 manifest 缺少 metadata 文件")
            for entry in files.values():
                if not isinstance(entry, Mapping):
                    raise EmbeddingUnavailableError("向量文件描述无效")
                name = entry.get("file")
                digest = entry.get("sha256")
                if not isinstance(name, str) or not isinstance(digest, str):
                    raise EmbeddingUnavailableError("向量文件描述缺少 file/sha256")
                path = (artifact / name).resolve()
                if not _inside(path, artifact) or not path.is_file():
                    raise EmbeddingUnavailableError(f"向量文件不存在: {name}")
                if sha256_path(path) != digest:
                    raise EmbeddingUnavailableError(f"向量文件哈希不一致: {name}")
            scopes = manifest.get("scopes")
            if not isinstance(scopes, list) or not scopes or any(
                scope not in {"poem", "line"} for scope in scopes
            ):
                raise EmbeddingUnavailableError("向量 manifest scopes 无效")
            for scope in scopes:
                entry = files.get(scope)
                if not isinstance(entry, Mapping):
                    raise EmbeddingUnavailableError(f"向量 manifest 缺少 {scope} 文件")
                count = entry.get("count")
                if isinstance(count, bool) or not isinstance(count, int) or count < 0:
                    raise EmbeddingUnavailableError(f"向量 manifest {scope} count 无效")
                vector_path = (artifact / str(entry.get("file", ""))).resolve()
                if vector_path.stat().st_size != count * dimension * 4:
                    raise EmbeddingUnavailableError(
                        f"向量文件长度与 manifest 不一致: {scope}"
                    )
            metadata_path = (artifact / str(metadata_entry.get("file", ""))).resolve()
            try:
                with sqlite3.connect(
                    metadata_path.as_uri() + "?mode=ro", uri=True
                ) as metadata_db:
                    metadata_db.execute("PRAGMA query_only=ON")
                    integrity = metadata_db.execute("PRAGMA quick_check").fetchone()
                    if not integrity or integrity[0] != "ok":
                        raise EmbeddingUnavailableError(
                            "向量 metadata SQLite 完整性校验失败"
                        )
                    columns = {
                        str(row[1])
                        for row in metadata_db.execute(
                            "PRAGMA table_info(embedding_items)"
                        )
                    }
                    required_columns = {
                        "scope",
                        "target_id",
                        "poem_id",
                        "line_id",
                        "line_no",
                        "title",
                        "poet",
                        "dynasty",
                        "text",
                        "status",
                        "vector_index",
                    }
                    if not required_columns.issubset(columns):
                        raise EmbeddingUnavailableError("向量 metadata schema 不完整")
                    for scope in scopes:
                        expected_count = int(files[scope]["count"])
                        row = metadata_db.execute(
                            "SELECT COUNT(*), COUNT(DISTINCT vector_index), "
                            "COALESCE(MIN(vector_index),0), COALESCE(MAX(vector_index),-1) "
                            "FROM embedding_items WHERE scope=? AND status='completed'",
                            (scope,),
                        ).fetchone()
                        completed, distinct_indexes, minimum, maximum = (
                            int(value) for value in row
                        )
                        if completed != expected_count or (
                            completed
                            and (
                                distinct_indexes != completed
                                or minimum != 0
                                or maximum != completed - 1
                            )
                        ):
                            raise EmbeddingUnavailableError(
                                f"向量 metadata {scope} 行索引与文件不一致"
                            )
            except sqlite3.Error as exc:
                raise EmbeddingUnavailableError(
                    f"向量 metadata SQLite 读取失败: {exc}"
                ) from exc
            if manifest.get("status", "ready") != "ready":
                raise EmbeddingUnavailableError("向量索引不是完整 ready 状态")
            activation = {
                "pointer": pointer,
                "artifact": artifact,
                "manifest": manifest,
            }
            self._activation_key = key
            self._activation = activation
            return activation

    def status(self) -> dict[str, Any]:
        activated = self._activate()
        manifest = activated["manifest"]
        return {
            "available": True,
            "stale": False,
            "root": str(self.root),
            "artifact": str(activated["artifact"]),
            "schemaVersion": manifest["schemaVersion"],
            "provider": manifest.get("provider"),
            "model": manifest.get("model"),
            "dimension": manifest.get("dimension"),
            "dtype": manifest.get("dtype"),
            "metric": manifest.get("metric"),
            "normalized": manifest.get("normalized"),
            "textVersion": manifest.get("textVersion"),
            "counts": manifest.get("counts", {}),
            "knowledge": manifest.get("knowledge", {}),
            "buildId": manifest.get("buildId"),
            "generatedAt": manifest.get("generatedAt"),
            "queryConfigured": self.client is not None,
        }

    def quick_status(self) -> dict[str, Any]:
        """Read pointer and manifest metadata without activating or hashing files."""

        pointer = _read_json(self.pointer_path)
        if pointer.get("schemaVersion") != POINTER_SCHEMA_VERSION:
            raise EmbeddingUnavailableError("向量 current.json schemaVersion 无效")
        relative = pointer.get("artifact")
        if not isinstance(relative, str) or not relative.strip():
            raise EmbeddingUnavailableError("向量 current.json 缺少 artifact")
        artifact = (self.root / relative).resolve()
        if not _inside(artifact, self.root) or not artifact.is_dir():
            raise EmbeddingUnavailableError("向量 artifact 路径越界或不存在")
        manifest = _read_json(artifact / "manifest.json")
        if manifest.get("schemaVersion") != EMBEDDING_SCHEMA_VERSION:
            raise EmbeddingUnavailableError("向量 manifest schemaVersion 无效")
        if manifest.get("status", "ready") != "ready":
            raise EmbeddingUnavailableError("向量索引不是完整 ready 状态")
        return {
            "available": True,
            "stale": False,
            "root": str(self.root),
            "artifact": str(artifact),
            "schemaVersion": manifest["schemaVersion"],
            "provider": manifest.get("provider"),
            "model": manifest.get("model"),
            "dimension": manifest.get("dimension"),
            "dtype": manifest.get("dtype"),
            "metric": manifest.get("metric"),
            "normalized": manifest.get("normalized"),
            "textVersion": manifest.get("textVersion"),
            "counts": manifest.get("counts", {}),
            "knowledge": manifest.get("knowledge", {}),
            "buildId": manifest.get("buildId"),
            "generatedAt": manifest.get("generatedAt"),
            "queryConfigured": self.client is not None,
        }

    def _query_vector(self, query: str, model: str) -> list[float]:
        key = (model, text_hash(query))
        with self._cache_lock:
            cached = self._cache.get(key)
            if cached is not None:
                self._cache.move_to_end(key)
                return list(cached)
        if self.client is None:
            raise EmbeddingUnavailableError("未配置 SiliconFlow 查询向量客户端")
        vectors, metadata = self.client.embed([query])
        if not vectors:
            raise EmbeddingUnavailableError("查询向量为空")
        if metadata.get("model") not in (None, model):
            raise EmbeddingUnavailableError("查询向量模型与索引模型不一致")
        vector = vectors[0]
        with self._cache_lock:
            self._cache[key] = list(vector)
            self._cache.move_to_end(key)
            while len(self._cache) > self.query_cache_size:
                self._cache.popitem(last=False)
        return vector

    @staticmethod
    def _score_file_python(
        path: Path,
        dimension: int,
        vector: Sequence[float],
        indexes: Iterable[int],
    ) -> list[tuple[float, int]]:
        size = dimension * 4
        scores: list[tuple[float, int]] = []
        try:
            with path.open("rb") as handle:
                for index in indexes:
                    handle.seek(index * size)
                    raw = handle.read(size)
                    if len(raw) != size:
                        raise EmbeddingUnavailableError("向量文件长度与元数据不一致")
                    values = struct.unpack(f"<{dimension}f", raw)
                    scores.append((sum(a * b for a, b in zip(values, vector)), index))
        except (OSError, struct.error) as exc:
            raise EmbeddingUnavailableError(f"向量文件读取失败: {exc}") from exc
        return scores

    @staticmethod
    def _score_file(
        path: Path,
        dimension: int,
        count: int,
        vector: Sequence[float],
        indexes: list[int],
    ) -> list[tuple[float, int]]:
        if not indexes or count <= 0:
            return []
        if any(index < 0 or index >= count for index in indexes):
            raise EmbeddingUnavailableError("向量索引位置越界")
        try:
            if path.stat().st_size != count * dimension * 4:
                raise EmbeddingUnavailableError("向量文件长度与元数据不一致")
        except OSError as exc:
            raise EmbeddingUnavailableError(f"向量文件读取失败: {exc}") from exc
        try:
            import numpy as np  # type: ignore[import-not-found]
        except ImportError:
            return PoetryEmbeddingRepository._score_file_python(
                path, dimension, vector, indexes
            )
        try:
            matrix = np.memmap(path, dtype="<f4", mode="r", shape=(count, dimension))
            query = np.asarray(vector, dtype=np.float32)
            selected = np.asarray(indexes, dtype=np.int64)
            scores = matrix[selected] @ query
        except (OSError, ValueError) as exc:
            raise EmbeddingUnavailableError(f"向量矩阵读取失败: {exc}") from exc
        return [(float(score), int(index)) for score, index in zip(scores, indexes)]

    @staticmethod
    @contextmanager
    def _metadata_connection(metadata_uri: str) -> Iterator[sqlite3.Connection]:
        try:
            with sqlite3.connect(metadata_uri, uri=True) as connection:
                connection.row_factory = sqlite3.Row
                connection.execute("PRAGMA query_only=ON")
                yield connection
        except (sqlite3.Error, OSError) as exc:
            raise EmbeddingUnavailableError(
                f"向量 metadata 查询失败: {exc}"
            ) from exc

    def search(
        self,
        query: str,
        *,
        scope: str = "line",
        poet: str | None = None,
        dynasty: str | None = None,
        imagery: str | None = None,
        emotion: str | None = None,
        limit: int = 20,
        offset: int = 0,
        query_vector: Sequence[float] | None = None,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        query = " ".join(query.strip().split())
        if not query:
            raise ValueError("语义检索 query 不能为空")
        if scope not in {"poem", "line", "all"}:
            raise ValueError("语义检索 scope 必须是 poem/line/all")
        if not 1 <= limit <= 50 or not 0 <= offset <= 100_000:
            raise ValueError("语义检索 limit/offset 超出范围")
        activated = self._activate()
        manifest = activated["manifest"]
        model = str(manifest.get("model") or "")
        dimension = int(manifest.get("dimension") or 0)
        vector = (
            _normalize_vector(query_vector)
            if query_vector is not None
            else self._query_vector(query, model)
        )
        if len(vector) != dimension:
            raise EmbeddingUnavailableError(
                f"查询向量维度 {len(vector)} 与索引维度 {dimension} 不一致"
            )
        metadata_path = activated["artifact"] / str(
            manifest["files"]["metadata"]["file"]
        )
        scopes = ("poem", "line") if scope == "all" else (scope,)
        candidates: list[dict[str, Any]] = []
        metadata_uri = metadata_path.as_uri() + "?mode=ro"
        with self._metadata_connection(metadata_uri) as connection:
            if imagery or emotion:
                connection.execute(
                    "ATTACH DATABASE ? AS knowledge", (str(self.knowledge_path),)
                )
            for current_scope in scopes:
                where = ["i.scope=?", "i.status='completed'"]
                params: list[Any] = [current_scope]
                if poet:
                    where.append("i.poet=?")
                    params.append(poet)
                if dynasty:
                    where.append("i.dynasty=?")
                    params.append(dynasty)
                if imagery:
                    target = "m.poem_id=i.poem_id" if current_scope == "poem" else "m.line_id=i.line_id"
                    where.append(
                        "EXISTS (SELECT 1 FROM knowledge.imagery_mentions m WHERE "
                        + target
                        + " AND (m.tag_id=? OR m.label=?))"
                    )
                    params.extend((imagery, imagery))
                if emotion:
                    target = "m.poem_id=i.poem_id" if current_scope == "poem" else "m.line_id=i.line_id"
                    where.append(
                        "EXISTS (SELECT 1 FROM knowledge.emotion_mentions m WHERE "
                        + target
                        + " AND (m.tag_id=? OR m.label=?))"
                    )
                    params.extend((emotion, emotion))
                rows = list(
                    connection.execute(
                        "SELECT scope,target_id,poem_id,line_id,line_no,title,poet,dynasty,"
                        "text,vector_index FROM embedding_items i WHERE "
                        + " AND ".join(where)
                        + " ORDER BY vector_index",
                        params,
                    )
                )
                if not rows:
                    continue
                entry = manifest["files"].get(current_scope)
                if not isinstance(entry, Mapping):
                    raise EmbeddingUnavailableError(
                        f"向量 manifest 缺少 {current_scope} 文件"
                    )
                count = int(entry.get("count") or 0)
                indexes = [int(row["vector_index"]) for row in rows]
                score_map = dict(
                    (index, score)
                    for score, index in self._score_file(
                        activated["artifact"] / str(entry["file"]),
                        dimension,
                        count,
                        vector,
                        indexes,
                    )
                )
                for row in rows:
                    candidates.append(
                        {
                            "scope": row["scope"],
                            "targetId": row["target_id"],
                            "poemId": row["poem_id"],
                            "lineId": row["line_id"],
                            "lineNo": row["line_no"],
                            "title": row["title"],
                            "poet": row["poet"],
                            "dynasty": row["dynasty"],
                            "text": row["text"],
                            "score": score_map[int(row["vector_index"])],
                            "retrievalMethod": "siliconflow_embedding_cosine",
                        }
                    )
        candidates.sort(
            key=lambda item: (-float(item["score"]), item["scope"], item["targetId"])
        )
        page = candidates[offset : offset + limit]
        for rank, item in enumerate(page, start=offset + 1):
            item["rank"] = rank
        return {
            "query": query,
            "scope": scope,
            "filters": {
                "poet": poet,
                "dynasty": dynasty,
                "imagery": imagery,
                "emotion": emotion,
            },
            "total": len(candidates),
            "limit": limit,
            "offset": offset,
            "items": page,
            "model": model,
            "dimension": dimension,
            "retrievalMethod": "siliconflow_embedding_cosine",
            "elapsedMs": round((time.perf_counter() - started) * 1000, 3),
            "buildId": manifest.get("buildId"),
        }


def vector_bytes(vector: Sequence[float]) -> bytes:
    values = array("f", vector)
    if struct.pack("=I", 1) != struct.pack("<I", 1):
        values.byteswap()
    return values.tobytes()
