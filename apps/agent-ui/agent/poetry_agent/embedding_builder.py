"""Offline, resumable compiler for SiliconFlow poetry embeddings."""

from __future__ import annotations

from collections import deque
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from contextlib import closing, contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
from typing import Any, Iterable, Iterator, Mapping, Sequence

from .embeddings import (
    EMBEDDING_SCHEMA_VERSION,
    MAX_EMBEDDING_CHUNK_CHARS,
    POINTER_SCHEMA_VERSION,
    TEXT_VERSION,
    EmbeddingProviderConfig,
    EmbeddingProviderError,
    SiliconFlowEmbeddingClient,
    canonical_line_text,
    canonical_poem_text,
    text_hash,
    vector_bytes,
)
from .knowledge import manifest_path_for, sha256_path
from .knowledge_builder import RUNTIME_DIR, stable_hash


class EmbeddingBuildError(RuntimeError):
    """The embedding compiler could not publish a complete artifact."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_bytes(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    payload = _json_bytes(value)
    with temporary.open("wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _safe_slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-.")
    return slug[:96] or "embedding-model"


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _read_manifest(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EmbeddingBuildError(f"manifest 读取失败: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise EmbeddingBuildError(f"manifest 必须是对象: {path}")
    return value


@contextmanager
def _destination_lock(destination: Path) -> Iterator[None]:
    lock_path = RUNTIME_DIR / (
        "embedding-build-" + stable_hash(destination.resolve(), length=24) + ".lock"
    )
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    if not lock_path.exists():
        try:
            lock_path.write_bytes(b"0")
        except FileExistsError:
            pass
    handle = lock_path.open("r+b")
    try:
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise EmbeddingBuildError(
                f"已有向量构建正在运行: {destination}"
            ) from exc
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


def _init_metadata(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        PRAGMA foreign_keys=ON;
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        ) WITHOUT ROWID;
        CREATE TABLE IF NOT EXISTS embedding_items (
            scope TEXT NOT NULL CHECK(scope IN ('poem','line')),
            target_id TEXT NOT NULL,
            poem_id TEXT NOT NULL,
            line_id TEXT,
            line_no INTEGER,
            title TEXT NOT NULL,
            poet TEXT NOT NULL,
            dynasty TEXT NOT NULL,
            text TEXT NOT NULL,
            text_hash TEXT NOT NULL,
            input_hash TEXT NOT NULL,
            input_text TEXT NOT NULL,
            vector_index INTEGER,
            status TEXT NOT NULL CHECK(status IN ('pending','running','completed','failed')),
            attempts INTEGER NOT NULL DEFAULT 0,
            error TEXT,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(scope,target_id)
        ) WITHOUT ROWID;
        CREATE INDEX IF NOT EXISTS idx_embedding_items_status
            ON embedding_items(scope,status,target_id);
        CREATE INDEX IF NOT EXISTS idx_embedding_items_filter
            ON embedding_items(scope,poet,dynasty,target_id);
        """
    )


def _meta(connection: sqlite3.Connection) -> dict[str, str]:
    return {
        str(row[0]): str(row[1])
        for row in connection.execute("SELECT key,value FROM meta")
    }


def _set_meta(connection: sqlite3.Connection, **values: Any) -> None:
    connection.executemany(
        "INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)",
        [(key, json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value)
         for key, value in values.items()],
    )


def _knowledge_identity(database: Path) -> dict[str, Any]:
    manifest_path = manifest_path_for(database)
    if not database.is_file() or not manifest_path.is_file():
        raise EmbeddingBuildError("主知识库或 manifest 不存在，请先构建知识库")
    manifest = _read_manifest(manifest_path)
    expected = manifest.get("databaseSha256")
    if not isinstance(expected, str) or len(expected) != 64:
        raise EmbeddingBuildError("主知识库 manifest 缺少 databaseSha256")
    if sha256_path(database) != expected:
        raise EmbeddingBuildError("主知识库数据库哈希与 manifest 不一致")
    if not isinstance(manifest.get("buildId"), str):
        raise EmbeddingBuildError("主知识库 manifest 缺少 buildId")
    return {
        "buildId": manifest["buildId"],
        "databaseSha256": expected,
        "sourceHashes": manifest.get("sourceHashes", {}),
        "schemaVersion": manifest.get("schemaVersion"),
    }


def _source_rows(database: Path, scopes: Sequence[str]) -> Iterator[dict[str, Any]]:
    uri = database.as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        if "poem" in scopes:
            for row in connection.execute(
                "SELECT poem_id,title,poet,dynasty,body,body_hash "
                "FROM poems ORDER BY poem_id"
            ):
                item = dict(row)
                canonical = canonical_poem_text(item)
                yield {
                    "scope": "poem",
                    "target_id": item["poem_id"],
                    "poem_id": item["poem_id"],
                    "line_id": None,
                    "line_no": None,
                    "title": item["title"],
                    "poet": item["poet"],
                    "dynasty": item["dynasty"],
                    "text": item["body"],
                    "text_hash": item["body_hash"],
                    "input_hash": text_hash(canonical),
                    "input_text": canonical,
                }
        if "line" in scopes:
            for row in connection.execute(
                "SELECT l.line_id,l.poem_id,l.line_no,l.text,l.line_hash,p.title,p.poet,p.dynasty "
                "FROM lines l JOIN poems p ON p.poem_id=l.poem_id "
                "ORDER BY l.line_id"
            ):
                item = dict(row)
                canonical = canonical_line_text(item)
                yield {
                    "scope": "line",
                    "target_id": item["line_id"],
                    "poem_id": item["poem_id"],
                    "line_id": item["line_id"],
                    "line_no": item["line_no"],
                    "title": item["title"],
                    "poet": item["poet"],
                    "dynasty": item["dynasty"],
                    "text": item["text"],
                    "text_hash": item["line_hash"],
                    "input_hash": text_hash(canonical),
                    "input_text": canonical,
                }


def _seed_items(
    connection: sqlite3.Connection,
    database: Path,
    scopes: Sequence[str],
) -> None:
    now = _utc_now()
    sql = (
        "INSERT INTO embedding_items("
        "scope,target_id,poem_id,line_id,line_no,title,poet,dynasty,text,text_hash,"
        "input_hash,input_text,vector_index,status,attempts,error,updated_at"
        ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?,NULL,'pending',0,NULL,?) "
        "ON CONFLICT(scope,target_id) DO UPDATE SET "
        "poem_id=excluded.poem_id,line_id=excluded.line_id,line_no=excluded.line_no,"
        "title=excluded.title,"
        "poet=excluded.poet,dynasty=excluded.dynasty,text=excluded.text,"
        "text_hash=excluded.text_hash,input_text=excluded.input_text,"
        "input_hash=excluded.input_hash,status=CASE WHEN "
        "embedding_items.input_hash=excluded.input_hash AND "
        "embedding_items.status='completed' THEN 'completed' ELSE 'pending' END,"
        "vector_index=CASE WHEN embedding_items.input_hash=excluded.input_hash "
        "AND embedding_items.status='completed' THEN embedding_items.vector_index "
        "ELSE NULL END,error=NULL,updated_at=excluded.updated_at"
    )
    batch: list[tuple[Any, ...]] = []
    for item in _source_rows(database, scopes):
        batch.append(
            (
                item["scope"], item["target_id"], item["poem_id"], item["line_id"],
                item["line_no"],
                item["title"], item["poet"], item["dynasty"], item["text"],
                item["text_hash"], item["input_hash"], item["input_text"], now,
            )
        )
        if len(batch) >= 1000:
            connection.executemany(sql, batch)
            connection.commit()
            batch.clear()
    if batch:
        connection.executemany(sql, batch)
    placeholders = ",".join("?" for _ in scopes)
    connection.execute(
        f"DELETE FROM embedding_items WHERE scope NOT IN ({placeholders})", scopes
    )
    connection.execute("UPDATE embedding_items SET status='pending' WHERE status='running'")
    connection.commit()


def _batch_rows(
    connection: sqlite3.Connection,
    batch_size: int,
) -> Iterator[list[sqlite3.Row]]:
    connection.row_factory = sqlite3.Row
    cursor = connection.execute(
        "SELECT scope,target_id,input_text FROM embedding_items "
        "WHERE status IN ('pending','failed') ORDER BY scope,target_id"
    )
    while True:
        rows = cursor.fetchmany(batch_size)
        if not rows:
            return
        yield rows


def _recover_vectors(
    connection: sqlite3.Connection,
    work: Path,
    dimension: int | None,
    scopes: Sequence[str],
) -> None:
    for scope in scopes:
        path = work / f"{scope}s.f32"
        if dimension is None:
            if path.exists() and path.stat().st_size:
                raise EmbeddingBuildError("向量维度缺失但工作文件非空")
            continue
        row = connection.execute(
            "SELECT COALESCE(MAX(vector_index),-1) FROM embedding_items "
            "WHERE scope=? AND status='completed'",
            (scope,),
        ).fetchone()
        expected = (int(row[0]) + 1) * dimension * 4
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_bytes(b"")
        actual = path.stat().st_size
        if actual < expected:
            raise EmbeddingBuildError(f"{scope} 向量文件短于已提交检查点")
        if actual != expected:
            with path.open("r+b") as handle:
                handle.truncate(expected)


def _append_batch(
    connection: sqlite3.Connection,
    work: Path,
    rows: Sequence[sqlite3.Row],
    vectors: Sequence[Sequence[float]],
    dimension: int,
) -> None:
    if len(rows) != len(vectors):
        raise EmbeddingBuildError("批次向量数量与输入不一致")
    grouped: dict[str, list[tuple[sqlite3.Row, Sequence[float]]]] = {}
    for row, vector in zip(rows, vectors):
        if len(vector) != dimension:
            raise EmbeddingBuildError("批次向量维度不一致")
        grouped.setdefault(str(row["scope"]), []).append((row, vector))
    updates: list[tuple[int, str, str, str]] = []
    now = _utc_now()
    for scope, entries in grouped.items():
        path = work / f"{scope}s.f32"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("ab") as handle:
            index = handle.tell() // (dimension * 4)
            for row, vector in entries:
                handle.write(vector_bytes(vector))
                updates.append((index, now, scope, str(row["target_id"])))
                index += 1
            handle.flush()
            os.fsync(handle.fileno())
    connection.execute("SAVEPOINT embedding_batch")
    try:
        connection.executemany(
            "UPDATE embedding_items SET vector_index=?,status='completed',"
            "attempts=attempts+1,error=NULL,updated_at=? WHERE scope=? AND target_id=?",
            updates,
        )
        connection.execute("RELEASE embedding_batch")
        connection.commit()
    except Exception:
        connection.execute("ROLLBACK TO embedding_batch")
        connection.execute("RELEASE embedding_batch")
        raise


def _mark_failed(
    connection: sqlite3.Connection,
    rows: Sequence[sqlite3.Row],
    error: Exception,
) -> None:
    message = str(error)[:1000]
    now = _utc_now()
    connection.executemany(
        "UPDATE embedding_items SET status='failed',attempts=attempts+1,error=?,"
        "updated_at=? WHERE scope=? AND target_id=?",
        [(message, now, row["scope"], row["target_id"]) for row in rows],
    )
    connection.commit()


def _mark_for_split(
    connection: sqlite3.Connection,
    rows: Sequence[sqlite3.Row],
    error: Exception,
) -> None:
    """Checkpoint a rejected batch before retrying smaller groups."""

    message = str(error)[:1000]
    now = _utc_now()
    connection.executemany(
        "UPDATE embedding_items SET status='pending',attempts=attempts+1,error=?,"
        "updated_at=? WHERE scope=? AND target_id=?",
        [(message, now, row["scope"], row["target_id"]) for row in rows],
    )
    connection.commit()


def _run_batches(
    connection: sqlite3.Connection,
    work: Path,
    client: SiliconFlowEmbeddingClient,
    config: EmbeddingProviderConfig,
    scopes: Sequence[str],
) -> tuple[int, dict[str, int], int, int]:
    raw_dimension = _meta(connection).get("dimension", "")
    dimension = int(raw_dimension) if raw_dimension else 0
    _recover_vectors(connection, work, dimension or None, scopes)
    token_usage = {"prompt_tokens": 0, "total_tokens": 0}
    request_count = 0
    batches = iter(_batch_rows(connection, config.batch_size))
    split_batches: deque[list[sqlite3.Row]] = deque()
    in_flight: dict[Future[tuple[list[list[float]], dict[str, Any]]], list[sqlite3.Row]] = {}
    window = max(config.concurrency, config.concurrency * 2)

    def submit(executor: ThreadPoolExecutor) -> bool:
        if split_batches:
            rows = split_batches.popleft()
        else:
            try:
                rows = next(batches)
            except StopIteration:
                return False
        connection.executemany(
            "UPDATE embedding_items SET status='running',updated_at=? "
            "WHERE scope=? AND target_id=?",
            [(_utc_now(), row["scope"], row["target_id"]) for row in rows],
        )
        connection.commit()
        future = executor.submit(client.embed, [str(row["input_text"]) for row in rows])
        in_flight[future] = rows
        return True

    with ThreadPoolExecutor(max_workers=config.concurrency) as executor:
        while len(in_flight) < window and submit(executor):
            pass
        while in_flight:
            completed, _ = wait(in_flight, return_when=FIRST_COMPLETED)
            for future in completed:
                rows = in_flight.pop(future)
                request_count += 1
                try:
                    vectors, metadata = future.result()
                    current_dimension = len(vectors[0]) if vectors else 0
                    if not current_dimension:
                        raise EmbeddingBuildError("provider 返回空向量批次")
                    if not dimension:
                        dimension = current_dimension
                        _set_meta(connection, dimension=str(dimension))
                        connection.commit()
                        _recover_vectors(connection, work, dimension, scopes)
                    if current_dimension != dimension:
                        raise EmbeddingBuildError(
                            f"provider 维度变化: {dimension} -> {current_dimension}"
                        )
                    response_model = metadata.get("model")
                    if response_model and response_model != config.model:
                        raise EmbeddingBuildError(
                            f"provider 模型不一致: {response_model} != {config.model}"
                        )
                    usage = metadata.get("usage", {})
                    if isinstance(usage, Mapping):
                        for key in token_usage:
                            value = usage.get(key)
                            if isinstance(value, int) and value >= 0:
                                token_usage[key] += value
                    _append_batch(connection, work, rows, vectors, dimension)
                except Exception as exc:
                    if (
                        isinstance(exc, EmbeddingProviderError)
                        and exc.status_code == 400
                        and len(rows) > 1
                    ):
                        _mark_for_split(connection, rows, exc)
                        midpoint = len(rows) // 2
                        split_batches.appendleft(list(rows[midpoint:]))
                        split_batches.appendleft(list(rows[:midpoint]))
                    else:
                        _mark_failed(connection, rows, exc)
                while len(in_flight) < window and submit(executor):
                    pass
    return dimension, token_usage, request_count, window


def _counts(connection: sqlite3.Connection) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for scope in ("poem", "line"):
        rows = {
            str(status): int(count)
            for status, count in connection.execute(
                "SELECT status,COUNT(*) FROM embedding_items WHERE scope=? GROUP BY status",
                (scope,),
            )
        }
        result[scope] = {
            "total": sum(rows.values()),
            "completed": rows.get("completed", 0),
            "failed": rows.get("failed", 0),
            "pending": rows.get("pending", 0) + rows.get("running", 0),
        }
    return result


def _publish(
    work: Path,
    final: Path,
    root: Path,
    config: EmbeddingProviderConfig,
    knowledge: Mapping[str, Any],
    dimension: int,
    scopes: Sequence[str],
    usage: Mapping[str, int],
    request_count: int,
    concurrency_window: int,
) -> dict[str, Any]:
    metadata_path = work / "items.sqlite3"
    with closing(sqlite3.connect(metadata_path)) as connection:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()
        if not integrity or integrity[0] != "ok":
            raise EmbeddingBuildError("embedding metadata integrity_check 失败")
        counts = _counts(connection)
    files: dict[str, Any] = {
        "metadata": {
            "file": "items.sqlite3",
            "sha256": sha256_path(metadata_path),
        }
    }
    for scope in scopes:
        path = work / f"{scope}s.f32"
        completed = int(counts[scope]["completed"])
        if not path.is_file() or path.stat().st_size != completed * dimension * 4:
            raise EmbeddingBuildError(f"{scope} 向量文件大小校验失败")
        files[scope] = {
            "file": path.name,
            "sha256": sha256_path(path),
            "count": completed,
            "bytes": path.stat().st_size,
        }
    build_id = final.name
    manifest = {
        "schemaVersion": EMBEDDING_SCHEMA_VERSION,
        "buildId": build_id,
        "status": (
            "ready"
            if all(
                int(counts[scope]["failed"]) == 0
                and int(counts[scope]["pending"]) == 0
                for scope in scopes
            )
            else "partial"
        ),
        "generatedAt": _utc_now(),
        "provider": "siliconflow",
        "endpoint": config.endpoint,
        "model": config.model,
        "dimension": dimension,
        "dtype": "float32-le",
        "metric": "cosine",
        "normalized": True,
        "indexType": "exact_memmap",
        "textVersion": TEXT_VERSION,
        "longTextPolicy": {
            "maxChunkCharacters": MAX_EMBEDDING_CHUNK_CHARS,
            "aggregation": "character_weighted_mean_l2",
        },
        "knowledge": dict(knowledge),
        "scopes": list(scopes),
        "counts": counts,
        "usage": {
            "requestCount": request_count,
            "promptTokens": int(usage.get("prompt_tokens", 0)),
            "totalTokens": int(usage.get("total_tokens", 0)),
        },
        "buildConfig": {
            "batchSize": config.batch_size,
            "concurrency": config.concurrency,
            "maxInFlight": concurrency_window,
        },
        "files": files,
    }
    manifest_path = work / "manifest.json"
    _atomic_json(manifest_path, manifest)
    if final.exists():
        raise EmbeddingBuildError(f"目标向量 artifact 已存在: {final}")
    if manifest["status"] != "ready":
        # Keep a previous ready pointer serving while a diagnostic partial
        # artifact stays in the .building directory for a later resume.
        return manifest
    os.replace(work, final)
    final_manifest = final / "manifest.json"
    pointer = {
        "schemaVersion": POINTER_SCHEMA_VERSION,
        "artifact": final.relative_to(root).as_posix(),
        "manifestSha256": sha256_path(final_manifest),
        "updatedAt": _utc_now(),
    }
    _atomic_json(root / "current.json", pointer)
    return manifest


def _validate_reusable_artifact(
    artifact: Path,
    *,
    config: EmbeddingProviderConfig,
    knowledge: Mapping[str, Any],
    scopes: Sequence[str],
) -> dict[str, Any]:
    """Refuse to repoint at a cached artifact whose identity or files changed."""

    manifest = _read_manifest(artifact / "manifest.json")
    if manifest.get("schemaVersion") != EMBEDDING_SCHEMA_VERSION:
        raise EmbeddingBuildError("已有向量 artifact schemaVersion 无效")
    if manifest.get("status", "ready") != "ready":
        raise EmbeddingBuildError("已有向量 artifact 不是完整 ready 状态")
    if manifest.get("model") != config.model or manifest.get("textVersion") != TEXT_VERSION:
        raise EmbeddingBuildError("已有向量 artifact 与当前模型或文本版本不一致")
    if manifest.get("knowledge") != dict(knowledge):
        raise EmbeddingBuildError("已有向量 artifact 绑定了不同的知识库")
    if tuple(manifest.get("scopes", ())) != tuple(scopes):
        raise EmbeddingBuildError("已有向量 artifact scope 与本次构建不一致")
    dimension = manifest.get("dimension")
    if isinstance(dimension, bool) or not isinstance(dimension, int) or dimension <= 0:
        raise EmbeddingBuildError("已有向量 artifact dimension 无效")
    files = manifest.get("files")
    if not isinstance(files, Mapping):
        raise EmbeddingBuildError("已有向量 artifact 缺少 files")
    for entry in files.values():
        if not isinstance(entry, Mapping):
            raise EmbeddingBuildError("已有向量文件描述无效")
        path = (artifact / str(entry.get("file", ""))).resolve()
        if not _inside(path, artifact) or not path.is_file():
            raise EmbeddingBuildError("已有向量文件不存在或路径越界")
        if sha256_path(path) != entry.get("sha256"):
            raise EmbeddingBuildError("已有向量文件哈希不一致")
    for scope in scopes:
        entry = files.get(scope)
        if not isinstance(entry, Mapping):
            raise EmbeddingBuildError(f"已有向量 artifact 缺少 {scope} 文件")
        count = entry.get("count")
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise EmbeddingBuildError(f"已有向量 artifact {scope} count 无效")
        path = (artifact / str(entry["file"])).resolve()
        if path.stat().st_size != count * dimension * 4:
            raise EmbeddingBuildError(f"已有向量 artifact {scope} 文件长度无效")
    return manifest


def build_poetry_embeddings(
    *,
    knowledge_path: Path,
    output_root: Path,
    client: SiliconFlowEmbeddingClient,
    config: EmbeddingProviderConfig,
    scopes: Sequence[str] = ("poem", "line"),
    rebuild: bool = False,
    allow_partial: bool = False,
) -> dict[str, Any]:
    """Build or resume a versioned vector artifact, then switch one pointer."""

    database = Path(knowledge_path).expanduser().resolve()
    root = Path(output_root).expanduser().resolve()
    normalized_scopes = tuple(dict.fromkeys(scopes))
    if not normalized_scopes or any(scope not in {"poem", "line"} for scope in normalized_scopes):
        raise ValueError("scopes 必须由 poem/line 组成")
    knowledge = _knowledge_identity(database)
    identity = {
        "knowledge": knowledge,
        "provider": "siliconflow",
        "model": config.model,
        "textVersion": TEXT_VERSION,
        "scopes": normalized_scopes,
    }
    build_id = stable_hash(identity, length=24)
    model_root = root / _safe_slug(config.model)
    final = model_root / build_id
    work = model_root / f".{build_id}.building"
    with _destination_lock(root):
        root.mkdir(parents=True, exist_ok=True)
        model_root.mkdir(parents=True, exist_ok=True)
        if final.is_dir() and not rebuild:
            manifest = _validate_reusable_artifact(
                final,
                config=config,
                knowledge=knowledge,
                scopes=normalized_scopes,
            )
            pointer = {
                "schemaVersion": POINTER_SCHEMA_VERSION,
                "artifact": final.relative_to(root).as_posix(),
                "manifestSha256": sha256_path(final / "manifest.json"),
                "updatedAt": _utc_now(),
            }
            _atomic_json(root / "current.json", pointer)
            return manifest
        if rebuild:
            for target in (work, final):
                if target.exists():
                    resolved = target.resolve()
                    if model_root.resolve() not in resolved.parents:
                        raise EmbeddingBuildError("拒绝删除向量根目录之外的路径")
                    shutil.rmtree(target)
        work.mkdir(parents=True, exist_ok=True)
        metadata_path = work / "items.sqlite3"
        connection = sqlite3.connect(metadata_path)
        try:
            _init_metadata(connection)
            current = _meta(connection)
            identity_json = json.dumps(identity, ensure_ascii=False, sort_keys=True)
            if current.get("identity") not in (None, identity_json):
                raise EmbeddingBuildError("工作目录身份与本次向量构建不一致")
            _set_meta(
                connection,
                schema_version=EMBEDDING_SCHEMA_VERSION,
                identity=identity_json,
                model=config.model,
                text_version=TEXT_VERSION,
                knowledge_build_id=str(knowledge["buildId"]),
            )
            connection.commit()
            _seed_items(connection, database, normalized_scopes)
            dimension, usage, request_count, concurrency_window = _run_batches(
                connection, work, client, config, normalized_scopes
            )
            counts = _counts(connection)
            failed = sum(int(counts[scope]["failed"]) for scope in normalized_scopes)
            pending = sum(int(counts[scope]["pending"]) for scope in normalized_scopes)
            if not dimension:
                raise EmbeddingBuildError("没有生成任何向量")
            if (failed or pending) and not allow_partial:
                raise EmbeddingBuildError(
                    f"向量构建未完成: failed={failed} pending={pending}; 已保留断点"
                )
        finally:
            connection.close()
        return _publish(
            work,
            final,
            root,
            config,
            knowledge,
            dimension,
            normalized_scopes,
            usage,
            request_count,
            concurrency_window,
        )
