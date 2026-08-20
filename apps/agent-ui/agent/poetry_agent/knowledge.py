"""Read-only repository and schema contract for the poetry knowledge base.

The database is built offline by :mod:`poetry_agent.knowledge_builder`.  Every
request opens its own SQLite ``mode=ro`` connection, which keeps FastAPI thread
workers independent and prevents a search request from mutating the snapshot.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping


SCHEMA_VERSION = "1.0"
REQUIRED_TABLES = {
    "meta",
    "poems",
    "lines",
    "analyses",
    "imagery_mentions",
    "emotion_mentions",
    "analysis_runs",
    "analysis_jobs",
    "poem_fts",
    "line_fts",
    "poem_short_tokens",
    "line_short_tokens",
}
REQUIRED_COLUMNS = {
    "meta": {"key", "value"},
    "poems": {
        "poem_id", "source_poem_id", "title", "poet", "dynasty", "body",
        "body_hash", "source_url",
    },
    "lines": {
        "line_id", "poem_id", "line_no", "stanza_no", "text",
        "start_offset", "end_offset", "line_hash",
    },
    "analyses": {
        "analysis_id", "poem_id", "line_id", "kind", "summary",
        "interpretation", "method", "confidence", "model", "prompt_hash",
        "input_hash", "review_status", "evidence_json", "payload_json",
    },
    "imagery_mentions": {
        "mention_id", "poem_id", "line_id", "tag_id", "label", "evidence",
        "start_offset", "end_offset", "method",
    },
    "emotion_mentions": {
        "mention_id", "poem_id", "line_id", "tag_id", "label", "evidence",
        "start_offset", "end_offset", "method",
    },
    "analysis_runs": {"run_id", "method", "status", "prompt_hash", "input_hash"},
    "analysis_jobs": {"job_id", "run_id", "poem_id", "input_hash", "status"},
    "poem_fts": {"poem_id", "title", "poet", "dynasty", "body", "analysis_text"},
    "line_fts": {
        "line_id", "poem_id", "title", "poet", "dynasty", "text", "analysis_text",
    },
    "poem_short_tokens": {"token", "poem_id"},
    "line_short_tokens": {"token", "line_id", "poem_id"},
}


class KnowledgeError(RuntimeError):
    """Base class for knowledge-base failures."""


class KnowledgeValidationError(KnowledgeError):
    """A caller supplied an unsupported search or lookup argument."""


class KnowledgeUnavailableError(KnowledgeError):
    """The immutable snapshot is absent, invalid, or stale."""


def manifest_path_for(database_path: Path) -> Path:
    return database_path.with_suffix(".manifest.json")


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def init_schema(connection: sqlite3.Connection) -> None:
    """Create the versioned builder schema on a writable connection."""

    connection.executescript(
        """
        PRAGMA foreign_keys=ON;

        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        ) WITHOUT ROWID;

        CREATE TABLE IF NOT EXISTS poems (
            poem_id TEXT PRIMARY KEY,
            source_poem_id TEXT,
            title TEXT NOT NULL,
            poet TEXT NOT NULL,
            dynasty TEXT NOT NULL,
            school TEXT,
            genre TEXT,
            body TEXT NOT NULL,
            body_hash TEXT NOT NULL,
            source_site TEXT,
            source_url TEXT
        ) WITHOUT ROWID;
        CREATE INDEX IF NOT EXISTS idx_poems_poet ON poems(poet, poem_id);
        CREATE INDEX IF NOT EXISTS idx_poems_dynasty ON poems(dynasty, poem_id);
        CREATE INDEX IF NOT EXISTS idx_poems_source ON poems(source_poem_id);
        CREATE INDEX IF NOT EXISTS idx_poems_body_hash ON poems(body_hash);

        CREATE TABLE IF NOT EXISTS lines (
            line_id TEXT PRIMARY KEY,
            poem_id TEXT NOT NULL REFERENCES poems(poem_id) ON DELETE CASCADE,
            line_no INTEGER NOT NULL CHECK(line_no > 0),
            stanza_no INTEGER NOT NULL DEFAULT 1 CHECK(stanza_no > 0),
            text TEXT NOT NULL,
            start_offset INTEGER NOT NULL CHECK(start_offset >= 0),
            end_offset INTEGER NOT NULL CHECK(end_offset >= start_offset),
            line_hash TEXT NOT NULL,
            UNIQUE(poem_id, line_no)
        ) WITHOUT ROWID;
        CREATE INDEX IF NOT EXISTS idx_lines_poem_order
            ON lines(poem_id, line_no);

        CREATE TABLE IF NOT EXISTS analysis_runs (
            run_id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            method TEXT NOT NULL CHECK(method IN ('rules', 'llm')),
            model TEXT,
            prompt_version TEXT,
            prompt_hash TEXT,
            input_hash TEXT,
            status TEXT NOT NULL,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            config_json TEXT NOT NULL DEFAULT '{}'
        ) WITHOUT ROWID;

        CREATE TABLE IF NOT EXISTS analysis_jobs (
            job_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES analysis_runs(run_id) ON DELETE CASCADE,
            poem_id TEXT NOT NULL REFERENCES poems(poem_id) ON DELETE CASCADE,
            line_id TEXT REFERENCES lines(line_id) ON DELETE CASCADE,
            input_hash TEXT NOT NULL,
            status TEXT NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0,
            error TEXT,
            result_json TEXT,
            updated_at TEXT NOT NULL,
            UNIQUE(run_id, poem_id, line_id)
        ) WITHOUT ROWID;
        CREATE INDEX IF NOT EXISTS idx_jobs_resume
            ON analysis_jobs(run_id, status, poem_id, line_id);

        CREATE TABLE IF NOT EXISTS analyses (
            analysis_id TEXT PRIMARY KEY,
            poem_id TEXT NOT NULL REFERENCES poems(poem_id) ON DELETE CASCADE,
            line_id TEXT REFERENCES lines(line_id) ON DELETE CASCADE,
            kind TEXT NOT NULL,
            summary TEXT,
            interpretation TEXT,
            method TEXT NOT NULL CHECK(method IN ('rules', 'llm')),
            confidence REAL NOT NULL CHECK(confidence >= 0 AND confidence <= 1),
            model TEXT,
            prompt_hash TEXT,
            input_hash TEXT NOT NULL,
            review_status TEXT NOT NULL,
            evidence_json TEXT NOT NULL DEFAULT '[]',
            payload_json TEXT NOT NULL DEFAULT '{}',
            run_id TEXT REFERENCES analysis_runs(run_id) ON DELETE SET NULL
        ) WITHOUT ROWID;
        CREATE INDEX IF NOT EXISTS idx_analyses_poem
            ON analyses(poem_id, line_id, kind, method);

        CREATE TABLE IF NOT EXISTS imagery_mentions (
            mention_id TEXT PRIMARY KEY,
            target_scope TEXT NOT NULL CHECK(target_scope IN ('poem', 'line')),
            poem_id TEXT NOT NULL REFERENCES poems(poem_id) ON DELETE CASCADE,
            line_id TEXT REFERENCES lines(line_id) ON DELETE CASCADE,
            tag_id TEXT NOT NULL,
            label TEXT NOT NULL,
            category TEXT,
            matched_text TEXT NOT NULL,
            confidence REAL NOT NULL CHECK(confidence >= 0 AND confidence <= 1),
            evidence TEXT NOT NULL,
            start_offset INTEGER,
            end_offset INTEGER,
            method TEXT NOT NULL CHECK(method IN ('rules', 'llm')),
            run_id TEXT REFERENCES analysis_runs(run_id) ON DELETE SET NULL
        ) WITHOUT ROWID;
        CREATE INDEX IF NOT EXISTS idx_imagery_filter
            ON imagery_mentions(tag_id, label, poem_id, line_id);
        CREATE INDEX IF NOT EXISTS idx_imagery_poem
            ON imagery_mentions(poem_id, line_id);

        CREATE TABLE IF NOT EXISTS emotion_mentions (
            mention_id TEXT PRIMARY KEY,
            target_scope TEXT NOT NULL CHECK(target_scope IN ('poem', 'line')),
            poem_id TEXT NOT NULL REFERENCES poems(poem_id) ON DELETE CASCADE,
            line_id TEXT REFERENCES lines(line_id) ON DELETE CASCADE,
            tag_id TEXT NOT NULL,
            label TEXT NOT NULL,
            family TEXT,
            score REAL,
            share REAL,
            valence REAL,
            arousal REAL,
            dominance REAL,
            confidence REAL NOT NULL CHECK(confidence >= 0 AND confidence <= 1),
            evidence TEXT NOT NULL,
            start_offset INTEGER,
            end_offset INTEGER,
            method TEXT NOT NULL CHECK(method IN ('rules', 'llm')),
            run_id TEXT REFERENCES analysis_runs(run_id) ON DELETE SET NULL
        ) WITHOUT ROWID;
        CREATE INDEX IF NOT EXISTS idx_emotion_filter
            ON emotion_mentions(tag_id, label, poem_id, line_id);
        CREATE INDEX IF NOT EXISTS idx_emotion_poem
            ON emotion_mentions(poem_id, line_id);

        CREATE VIRTUAL TABLE IF NOT EXISTS poem_fts USING fts5(
            poem_id UNINDEXED,
            title,
            poet,
            dynasty,
            body,
            analysis_text,
            tokenize='trigram'
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS line_fts USING fts5(
            line_id UNINDEXED,
            poem_id UNINDEXED,
            title,
            poet,
            dynasty,
            text,
            analysis_text,
            tokenize='trigram'
        );
        CREATE TABLE IF NOT EXISTS poem_short_tokens (
            token TEXT NOT NULL,
            poem_id TEXT NOT NULL REFERENCES poems(poem_id) ON DELETE CASCADE,
            PRIMARY KEY(token, poem_id)
        ) WITHOUT ROWID;
        CREATE TABLE IF NOT EXISTS line_short_tokens (
            token TEXT NOT NULL,
            line_id TEXT NOT NULL REFERENCES lines(line_id) ON DELETE CASCADE,
            poem_id TEXT NOT NULL REFERENCES poems(poem_id) ON DELETE CASCADE,
            PRIMARY KEY(token, line_id)
        ) WITHOUT ROWID;
        CREATE INDEX IF NOT EXISTS idx_line_short_poem
            ON line_short_tokens(poem_id, line_id);
        """
    )
    connection.execute(
        "INSERT OR REPLACE INTO meta(key,value) VALUES('schema_version',?)",
        (SCHEMA_VERSION,),
    )


def _json_object(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


def _camelize(value: Any) -> Any:
    if isinstance(value, list):
        return [_camelize(item) for item in value]
    if isinstance(value, dict):
        return {
            "".join(
                part if index == 0 else part[:1].upper() + part[1:]
                for index, part in enumerate(str(key).split("_"))
            ): _camelize(item)
            for key, item in value.items()
        }
    return value


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _literal_fts_query(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _snippet(text: str, query: str, radius: int = 54) -> str:
    clean = " ".join((text or "").split())
    if not query:
        return clean[: radius * 2] + ("…" if len(clean) > radius * 2 else "")
    index = clean.casefold().find(query.casefold())
    if index < 0:
        return clean[: radius * 2] + ("…" if len(clean) > radius * 2 else "")
    start = max(0, index - radius)
    end = min(len(clean), index + len(query) + radius)
    return ("…" if start else "") + clean[start:end] + ("…" if end < len(clean) else "")


class PoetryKnowledgeRepository:
    """Validate and query an immutable poetry knowledge snapshot."""

    def __init__(
        self,
        path: Path,
        expected_sources: Mapping[str, str] | None = None,
    ) -> None:
        self.path = Path(path).expanduser().resolve()
        self.expected_sources = dict(expected_sources or {})
        self._verification_lock = threading.Lock()
        self._verified_identity: tuple[Any, ...] | None = None
        self._schema_identity: tuple[Any, ...] | None = None

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        if not self.path.is_file():
            raise KnowledgeUnavailableError(f"知识库文件不存在: {self.path}")
        uri = self.path.as_uri() + "?mode=ro"
        try:
            connection = sqlite3.connect(uri, uri=True, timeout=5.0)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA query_only=ON")
            connection.execute("PRAGMA foreign_keys=ON")
        except sqlite3.Error as exc:
            raise KnowledgeUnavailableError(f"知识库只读打开失败: {exc}") from exc
        try:
            yield connection
        except sqlite3.Error as exc:
            raise KnowledgeUnavailableError(f"知识库查询失败: {exc}") from exc
        finally:
            connection.close()

    def _metadata(self, connection: sqlite3.Connection) -> dict[str, Any]:
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
            )
        }
        missing = sorted(REQUIRED_TABLES - tables)
        if missing:
            raise KnowledgeUnavailableError(
                "知识库 schema 不完整: " + ", ".join(missing)
            )
        meta = {
            str(row["key"]): str(row["value"])
            for row in connection.execute("SELECT key,value FROM meta")
        }
        if meta.get("schema_version") != SCHEMA_VERSION:
            raise KnowledgeUnavailableError(
                f"知识库 schema 版本不受支持: {meta.get('schema_version')!r}"
            )
        hashes = _json_object(meta.get("source_hashes"), {})
        if not isinstance(hashes, dict):
            raise KnowledgeUnavailableError("知识库 source_hashes 无效")
        mismatches = [
            key
            for key, expected in self.expected_sources.items()
            if hashes.get(key) != expected
        ]
        if mismatches:
            raise KnowledgeUnavailableError(
                "知识库已过期，源哈希不一致: " + ", ".join(mismatches)
            )
        return {**meta, "sourceHashes": hashes}

    @staticmethod
    def _file_identity(path: Path) -> tuple[int, int, int, int]:
        stat = path.stat()
        return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)

    def _validate_schema_contract(self, connection: sqlite3.Connection) -> None:
        for table, required in REQUIRED_COLUMNS.items():
            columns = {
                str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")
            }
            missing = sorted(required - columns)
            if missing:
                raise KnowledgeUnavailableError(
                    f"知识库 {table} 缺少字段: {', '.join(missing)}"
                )
        for table in ("poem_fts", "line_fts"):
            row = connection.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone()
            ddl = str(row[0] if row else "").casefold().replace('"', "'")
            if "using fts5" not in ddl or "trigram" not in ddl:
                raise KnowledgeUnavailableError(f"知识库 {table} 未使用 FTS5 trigram")

    def _manifest(self, *, verify_database_hash: bool) -> dict[str, Any] | None:
        candidates = (manifest_path_for(self.path), Path(str(self.path) + ".manifest.json"))
        manifest_path = next((path for path in candidates if path.is_file()), None)
        if manifest_path is None:
            raise KnowledgeUnavailableError("知识库 manifest 不存在")
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise KnowledgeUnavailableError(f"知识库 manifest 读取失败: {exc}") from exc
        if not isinstance(payload, dict) or payload.get("schemaVersion") != SCHEMA_VERSION:
            raise KnowledgeUnavailableError("知识库 manifest 版本无效")
        digest = payload.get("databaseSha256")
        if (
            payload.get("database") != self.path.name
            or not isinstance(payload.get("buildId"), str)
            or not isinstance(payload.get("sourceHashes"), dict)
            or not isinstance(payload.get("filters"), dict)
            or not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest.casefold())
        ):
            raise KnowledgeUnavailableError("知识库 manifest 字段无效")
        if verify_database_hash:
            assert manifest_path is not None
            try:
                identity = (
                    *self._file_identity(self.path),
                    *self._file_identity(manifest_path),
                    digest,
                )
            except OSError as exc:
                raise KnowledgeUnavailableError(f"知识库文件状态读取失败: {exc}") from exc
            with self._verification_lock:
                if self._verified_identity != identity:
                    actual = sha256_path(self.path)
                    if actual != digest:
                        self._verified_identity = None
                        raise KnowledgeUnavailableError("知识库文件与 manifest 哈希不一致")
                    self._verified_identity = identity
        return payload

    def _verified_metadata(self, connection: sqlite3.Connection) -> dict[str, Any]:
        """Bind every public read to the signed snapshot metadata."""

        meta = self._metadata(connection)
        manifest = self._manifest(verify_database_hash=True)
        assert manifest is not None
        manifest_path = manifest_path_for(self.path)
        if not manifest_path.is_file():
            manifest_path = Path(str(self.path) + ".manifest.json")
        identity = (
            *self._file_identity(self.path),
            *self._file_identity(manifest_path),
            manifest["databaseSha256"],
        )
        with self._verification_lock:
            if self._schema_identity != identity:
                self._validate_schema_contract(connection)
                self._schema_identity = identity
        if manifest.get("buildId") != meta.get("build_id"):
            raise KnowledgeUnavailableError("知识库 manifest 与 build_id 不一致")
        if manifest.get("sourceHashes") != meta.get("sourceHashes"):
            raise KnowledgeUnavailableError("知识库 manifest 与 source_hashes 不一致")
        filters = _json_object(meta.get("build_filters"), {})
        if manifest.get("filters") != filters:
            raise KnowledgeUnavailableError("知识库 manifest 与构建范围不一致")
        return meta

    def status(self) -> dict[str, Any]:
        with self._connect() as connection:
            meta = self._verified_metadata(connection)
            counts = {
                "poemCount": connection.execute("SELECT COUNT(*) FROM poems").fetchone()[0],
                "lineCount": connection.execute("SELECT COUNT(*) FROM lines").fetchone()[0],
                "analysisCount": connection.execute("SELECT COUNT(*) FROM analyses").fetchone()[0],
                "imageryMentionCount": connection.execute(
                    "SELECT COUNT(*) FROM imagery_mentions"
                ).fetchone()[0],
                "emotionMentionCount": connection.execute(
                    "SELECT COUNT(*) FROM emotion_mentions"
                ).fetchone()[0],
                "llmCompletedCount": connection.execute(
                    "SELECT COUNT(*) FROM analysis_jobs WHERE status='completed'"
                ).fetchone()[0],
                "llmPendingCount": connection.execute(
                    "SELECT COUNT(*) FROM analysis_jobs WHERE status IN ('pending','failed','running')"
                ).fetchone()[0],
            }
        manifest = self._manifest(verify_database_hash=False)
        return {
            "available": True,
            "stale": False,
            "path": str(self.path),
            "schemaVersion": SCHEMA_VERSION,
            "buildId": meta.get("build_id"),
            "generatedAt": meta.get("generated_at"),
            "splitterVersion": meta.get("splitter_version"),
            "sourceHashes": meta["sourceHashes"],
            "manifest": manifest,
            **counts,
        }

    def quick_status(self) -> dict[str, Any]:
        """Return manifest-backed status without hashing or scanning the database."""

        if not self.path.is_file():
            raise KnowledgeUnavailableError(f"知识库文件不存在: {self.path}")
        manifest = self._manifest(verify_database_hash=False)
        assert manifest is not None
        hashes = manifest["sourceHashes"]
        mismatches = [
            key
            for key, expected in self.expected_sources.items()
            if hashes.get(key) != expected
        ]
        if mismatches:
            raise KnowledgeUnavailableError(
                "知识库已过期，源哈希不一致: " + ", ".join(mismatches)
            )
        return {
            "available": True,
            "stale": False,
            "path": str(self.path),
            "schemaVersion": manifest["schemaVersion"],
            "buildId": manifest["buildId"],
            "generatedAt": manifest.get("generatedAt"),
            "splitterVersion": manifest.get("splitterVersion"),
            "sourceHashes": hashes,
            "manifest": manifest,
            "poemCount": manifest.get("poemCount", 0),
            "lineCount": manifest.get("lineCount", 0),
            "analysisCount": manifest.get("analysisCount", 0),
            "imageryMentionCount": manifest.get("imageryMentionCount", 0),
            "emotionMentionCount": manifest.get("emotionMentionCount", 0),
        }

    def catalog_rows(self) -> tuple[list[dict[str, Any]], dict[str, str]]:
        """Aggregate the poet catalog in SQLite without loading the full corpus JSON."""

        status = self.quick_status()
        with self._connect() as connection:
            grouped_rows = connection.execute(
                "SELECT poet,dynasty,COUNT(*) AS work_count,MIN(poem_id) AS first_seen "
                "FROM poems GROUP BY poet,dynasty ORDER BY first_seen"
            ).fetchall()

        poets: dict[str, dict[str, Any]] = {}
        for row in grouped_rows:
            poet = str(row["poet"])
            dynasty = str(row["dynasty"] or "未知")
            work_count = int(row["work_count"])
            first_seen = str(row["first_seen"])
            item = poets.setdefault(
                poet,
                {
                    "poet": poet,
                    "workCount": 0,
                    "dynastyCounts": {},
                    "corpusOrder": first_seen,
                },
            )
            item["workCount"] += work_count
            item["dynastyCounts"][dynasty] = work_count
            item["corpusOrder"] = min(item["corpusOrder"], first_seen)

        rows = sorted(poets.values(), key=lambda item: item["corpusOrder"])
        for item in rows:
            item["dynasty"] = max(
                item["dynastyCounts"].items(), key=lambda pair: pair[1]
            )[0]
        return rows, dict(status["sourceHashes"])

    @staticmethod
    def _validate_search(
        query: str,
        poet: str | None,
        dynasty: str | None,
        imagery: str | None,
        emotion: str | None,
        scope: str,
        limit: int,
        offset: int,
    ) -> tuple[str, dict[str, str | None]]:
        if not isinstance(query, str):
            raise KnowledgeValidationError("query 必须是字符串")
        query = " ".join(query.strip().split())
        if len(query) > 160:
            raise KnowledgeValidationError("query 最长160字")
        if scope not in {"poem", "line", "all"}:
            raise KnowledgeValidationError("scope 必须是 poem/line/all")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 50:
            raise KnowledgeValidationError("limit 必须位于1..50")
        if isinstance(offset, bool) or not isinstance(offset, int) or not 0 <= offset <= 100_000:
            raise KnowledgeValidationError("offset 必须位于0..100000")
        filters: dict[str, str | None] = {}
        for name, value, maximum in (
            ("poet", poet, 32),
            ("dynasty", dynasty, 16),
            ("imagery", imagery, 32),
            ("emotion", emotion, 32),
        ):
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise KnowledgeValidationError(f"{name} 传入时不能为空")
            normalized = value.strip() if isinstance(value, str) else None
            if normalized and len(normalized) > maximum:
                raise KnowledgeValidationError(f"{name} 过长")
            filters[name] = normalized
        return query, filters

    @staticmethod
    def _filter_sql(alias: str, filters: Mapping[str, str | None], *, line: bool) -> tuple[list[str], list[Any]]:
        conditions: list[str] = []
        parameters: list[Any] = []
        if filters.get("poet"):
            conditions.append("p.poet=?")
            parameters.append(filters["poet"])
        if filters.get("dynasty"):
            conditions.append("p.dynasty=?")
            parameters.append(filters["dynasty"])
        if filters.get("imagery"):
            if line:
                conditions.append(
                    "l.line_id IN ("
                    "SELECT m.line_id FROM imagery_mentions m "
                    "WHERE m.line_id IS NOT NULL AND m.tag_id=? "
                    "UNION SELECT m.line_id FROM imagery_mentions m "
                    "WHERE m.line_id IS NOT NULL AND m.label=?)"
                )
            else:
                conditions.append(
                    "p.poem_id IN ("
                    "SELECT m.poem_id FROM imagery_mentions m WHERE m.tag_id=? "
                    "UNION SELECT m.poem_id FROM imagery_mentions m WHERE m.label=?)"
                )
            parameters.extend([filters["imagery"], filters["imagery"]])
        if filters.get("emotion"):
            if line:
                conditions.append(
                    "l.line_id IN ("
                    "SELECT e.line_id FROM emotion_mentions e "
                    "WHERE e.line_id IS NOT NULL AND e.tag_id=? "
                    "UNION SELECT e.line_id FROM emotion_mentions e "
                    "WHERE e.line_id IS NOT NULL AND e.label=?)"
                )
            else:
                conditions.append(
                    "p.poem_id IN ("
                    "SELECT e.poem_id FROM emotion_mentions e WHERE e.tag_id=? "
                    "UNION SELECT e.poem_id FROM emotion_mentions e WHERE e.label=?)"
                )
            parameters.extend([filters["emotion"], filters["emotion"]])
        return conditions, parameters

    def _search_select(
        self,
        *,
        kind: str,
        query: str,
        filters: Mapping[str, str | None],
        force_like: bool = False,
    ) -> tuple[str, list[Any]]:
        is_line = kind == "line"
        filter_conditions, filter_parameters = self._filter_sql(
            "l" if is_line else "p", filters, line=is_line
        )
        use_fts = len(query) >= 3 and not force_like
        use_short_fts = (
            bool(query)
            and len(query) <= 2
            and all(character.isalnum() for character in query)
            and not force_like
        )
        parameters: list[Any] = []
        if is_line:
            columns = (
                "'line' AS kind,p.poem_id,l.line_id,l.line_no,p.title,p.poet,p.dynasty,"
                "l.text AS content"
            )
            base = " FROM lines l JOIN poems p ON p.poem_id=l.poem_id"
            if use_fts:
                base += " JOIN line_fts ON line_fts.line_id=l.line_id"
                conditions = ["line_fts MATCH ?"]
                parameters.append(_literal_fts_query(query))
                rank = "bm25(line_fts)"
            elif use_short_fts:
                base += " JOIN line_short_tokens st ON st.line_id=l.line_id"
                conditions = ["st.token=?"]
                parameters.append(query.casefold())
                rank = "0.0"
            else:
                conditions = []
                rank = "0.0"
                if query:
                    pattern = "%" + _escape_like(query) + "%"
                    conditions.append(
                        "(l.text LIKE ? ESCAPE '\\' OR p.title LIKE ? ESCAPE '\\' "
                        "OR p.poet LIKE ? ESCAPE '\\')"
                    )
                    parameters.extend([pattern, pattern, pattern])
        else:
            columns = (
                "'poem' AS kind,p.poem_id,NULL AS line_id,NULL AS line_no,"
                "p.title,p.poet,p.dynasty,p.body AS content"
            )
            base = " FROM poems p"
            if use_fts:
                base += " JOIN poem_fts ON poem_fts.poem_id=p.poem_id"
                conditions = ["poem_fts MATCH ?"]
                parameters.append(_literal_fts_query(query))
                rank = "bm25(poem_fts)"
            elif use_short_fts:
                base += (
                    " JOIN ("
                    "SELECT poem_id FROM poem_short_tokens WHERE token=? "
                    "UNION SELECT poem_id FROM line_short_tokens WHERE token=?"
                    ") st ON st.poem_id=p.poem_id"
                )
                conditions = []
                parameters.extend([query.casefold(), query.casefold()])
                rank = "0.0"
            else:
                conditions = []
                rank = "0.0"
                if query:
                    pattern = "%" + _escape_like(query) + "%"
                    conditions.append(
                        "(p.poem_id=? OR p.title LIKE ? ESCAPE '\\' "
                        "OR p.poet LIKE ? ESCAPE '\\' OR p.body LIKE ? ESCAPE '\\')"
                    )
                    parameters.extend([query, pattern, pattern, pattern])
        conditions.extend(filter_conditions)
        parameters.extend(filter_parameters)
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        return "SELECT " + columns + f",{rank} AS relevance" + base + where, parameters

    def search(
        self,
        query: str = "",
        poet: str | None = None,
        dynasty: str | None = None,
        imagery: str | None = None,
        emotion: str | None = None,
        scope: str = "all",
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        query, filters = self._validate_search(
            query, poet, dynasty, imagery, emotion, scope, limit, offset
        )
        with self._connect() as connection:
            meta = self._verified_metadata(connection)
            def build_query(*, force_like: bool) -> tuple[str, list[Any]]:
                selects: list[str] = []
                parameters: list[Any] = []
                for kind in ("poem", "line"):
                    if scope not in {kind, "all"}:
                        continue
                    select, select_parameters = self._search_select(
                        kind=kind,
                        query=query,
                        filters=filters,
                        force_like=force_like,
                    )
                    selects.append(select)
                    parameters.extend(select_parameters)
                return " UNION ALL ".join(selects), parameters

            union, parameters = build_query(force_like=False)
            try:
                total = int(
                    connection.execute(
                        f"SELECT COUNT(*) FROM ({union}) results", parameters
                    ).fetchone()[0]
                )
                rows = connection.execute(
                    f"SELECT * FROM ({union}) results "
                    "ORDER BY relevance ASC, kind ASC, poem_id ASC, COALESCE(line_no,0) ASC "
                    "LIMIT ? OFFSET ?",
                    [*parameters, limit, offset],
                ).fetchall()
            except sqlite3.OperationalError as exc:
                # Older SQLite builds may lack the trigram tokenizer. Literal
                # LIKE remains correct (though slower) and is always parameterized.
                message = str(exc).casefold()
                if not query or len(query) < 3 or not any(
                    marker in message for marker in ("fts5", "tokenizer", "match")
                ):
                    raise
                union, parameters = build_query(force_like=True)
                total = int(
                    connection.execute(
                        f"SELECT COUNT(*) FROM ({union}) results", parameters
                    ).fetchone()[0]
                )
                rows = connection.execute(
                    f"SELECT * FROM ({union}) results "
                    "ORDER BY relevance ASC, kind ASC, poem_id ASC, COALESCE(line_no,0) ASC "
                    "LIMIT ? OFFSET ?",
                    [*parameters, limit, offset],
                ).fetchall()
            items: list[dict[str, Any]] = []
            for row in rows:
                line_id = row["line_id"]
                poem_id = row["poem_id"]
                items.append(
                    {
                        "kind": row["kind"],
                        "scope": row["kind"],
                        "poemId": poem_id,
                        "lineId": line_id,
                        "lineNo": row["line_no"],
                        "title": row["title"],
                        "poet": row["poet"],
                        "dynasty": row["dynasty"],
                        "text": row["content"] if row["kind"] == "line" else None,
                        "snippet": _snippet(row["content"], query),
                        "imagery": self._mentions(
                            connection, "imagery_mentions", poem_id, line_id
                        ),
                        "emotions": self._mentions(
                            connection, "emotion_mentions", poem_id, line_id
                        ),
                        "analysisMethods": self._analysis_methods(
                            connection, poem_id, line_id
                        ),
                    }
                )
        return {
            "query": query,
            "scope": scope,
            "filters": filters,
            "total": total,
            "limit": limit,
            "offset": offset,
            "items": items,
            "elapsedMs": round((time.perf_counter() - started) * 1000, 3),
            "buildId": meta.get("build_id"),
            "schemaVersion": SCHEMA_VERSION,
            "sourceHashes": meta["sourceHashes"],
        }

    @staticmethod
    def _analysis_methods(
        connection: sqlite3.Connection, poem_id: str, line_id: str | None
    ) -> list[str]:
        if line_id:
            rows = connection.execute(
                "SELECT DISTINCT method FROM analyses WHERE poem_id=? AND line_id=? ORDER BY method",
                (poem_id, line_id),
            )
        else:
            rows = connection.execute(
                "SELECT DISTINCT method FROM analyses WHERE poem_id=? ORDER BY method",
                (poem_id,),
            )
        return [str(row[0]) for row in rows]

    @staticmethod
    def _mentions(
        connection: sqlite3.Connection,
        table: str,
        poem_id: str,
        line_id: str | None,
    ) -> list[dict[str, Any]]:
        if table not in {"imagery_mentions", "emotion_mentions"}:
            raise AssertionError("unexpected mention table")
        if line_id:
            rows = connection.execute(
                f"SELECT * FROM {table} WHERE poem_id=? AND line_id=? ORDER BY confidence DESC,label,mention_id",
                (poem_id, line_id),
            ).fetchall()
        else:
            rows = connection.execute(
                f"SELECT * FROM {table} WHERE poem_id=? ORDER BY confidence DESC,label,mention_id",
                (poem_id,),
            ).fetchall()
        by_key: dict[tuple[str, str], dict[str, Any]] = {}
        result: list[dict[str, Any]] = []
        for row in rows:
            key = (str(row["tag_id"]), str(row["method"]))
            raw_evidence = _json_object(row["evidence"], None)
            evidence = (
                [str(value) for value in raw_evidence if str(value)]
                if isinstance(raw_evidence, list)
                else [str(row["evidence"])] if row["evidence"] else []
            )
            if key in by_key:
                current = by_key[key]
                current["evidence"] = list(
                    dict.fromkeys([*current["evidence"], *evidence])
                )
                current["occurrences"].append(
                    {
                        "lineId": row["line_id"],
                        "startOffset": row["start_offset"],
                        "endOffset": row["end_offset"],
                        "evidence": evidence,
                    }
                )
                if current["lineId"] != row["line_id"]:
                    current["lineId"] = None
                    current["startOffset"] = None
                    current["endOffset"] = None
                continue
            item = {
                "id": row["tag_id"],
                "label": row["label"],
                "confidence": row["confidence"],
                "evidence": evidence,
                "method": row["method"],
                "lineId": row["line_id"],
                "startOffset": row["start_offset"],
                "endOffset": row["end_offset"],
                "occurrences": [
                    {
                        "lineId": row["line_id"],
                        "startOffset": row["start_offset"],
                        "endOffset": row["end_offset"],
                        "evidence": evidence,
                    }
                ],
            }
            if table == "imagery_mentions":
                item.update({"category": row["category"], "matchedText": row["matched_text"]})
            else:
                item.update(
                    {
                        "family": row["family"],
                        "score": row["score"],
                        "share": row["share"],
                        "valence": row["valence"],
                        "arousal": row["arousal"],
                        "dominance": row["dominance"],
                    }
                )
            result.append(item)
            by_key[key] = item
        return result

    @staticmethod
    def _analyses(
        connection: sqlite3.Connection, poem_id: str, line_id: str | None
    ) -> list[dict[str, Any]]:
        if line_id is None:
            rows = connection.execute(
                "SELECT * FROM analyses WHERE poem_id=? AND line_id IS NULL ORDER BY method,kind,analysis_id",
                (poem_id,),
            ).fetchall()
        else:
            rows = connection.execute(
                "SELECT * FROM analyses WHERE poem_id=? AND line_id=? ORDER BY method,kind,analysis_id",
                (poem_id, line_id),
            ).fetchall()
        return [
            {
                "analysisId": row["analysis_id"],
                "kind": row["kind"],
                "summary": row["summary"],
                "interpretation": row["interpretation"],
                "method": row["method"],
                "confidence": row["confidence"],
                "model": row["model"],
                "promptHash": row["prompt_hash"],
                "inputHash": row["input_hash"],
                "reviewStatus": row["review_status"],
                "evidence": _camelize(_json_object(row["evidence_json"], [])),
                "payload": _camelize(_json_object(row["payload_json"], {})),
            }
            for row in rows
        ]

    def get_poem(self, poem_id: str) -> dict[str, Any] | None:
        poem_id = self._validate_id(poem_id, "poem_id")
        with self._connect() as connection:
            meta = self._verified_metadata(connection)
            poem = connection.execute(
                "SELECT * FROM poems WHERE poem_id=?", (poem_id,)
            ).fetchone()
            if poem is None:
                return None
            lines = []
            for row in connection.execute(
                "SELECT * FROM lines WHERE poem_id=? ORDER BY line_no", (poem_id,)
            ):
                line_id = str(row["line_id"])
                lines.append(
                    {
                        "lineId": line_id,
                        "lineNo": row["line_no"],
                        "stanzaNo": row["stanza_no"],
                        "text": row["text"],
                        "startOffset": row["start_offset"],
                        "endOffset": row["end_offset"],
                        "lineHash": row["line_hash"],
                        "analyses": self._analyses(connection, poem_id, line_id),
                        "imagery": self._mentions(
                            connection, "imagery_mentions", poem_id, line_id
                        ),
                        "emotions": self._mentions(
                            connection, "emotion_mentions", poem_id, line_id
                        ),
                    }
                )
            return {
                "poemId": poem["poem_id"],
                "sourcePoemId": poem["source_poem_id"],
                "title": poem["title"],
                "poet": poem["poet"],
                "dynasty": poem["dynasty"],
                "school": poem["school"],
                "genre": poem["genre"],
                "body": poem["body"],
                "bodyHash": poem["body_hash"],
                "sourceSite": poem["source_site"],
                "sourceUrl": poem["source_url"],
                "lines": lines,
                "analyses": self._analyses(connection, poem_id, None),
                "imagery": self._mentions(
                    connection, "imagery_mentions", poem_id, None
                ),
                "emotions": self._mentions(
                    connection, "emotion_mentions", poem_id, None
                ),
                "buildId": meta.get("build_id"),
                "schemaVersion": SCHEMA_VERSION,
                "sourceHashes": meta["sourceHashes"],
            }

    def get_line(self, line_id: str) -> dict[str, Any] | None:
        line_id = self._validate_id(line_id, "line_id")
        with self._connect() as connection:
            meta = self._verified_metadata(connection)
            row = connection.execute(
                "SELECT l.*,p.title,p.poet,p.dynasty FROM lines l "
                "JOIN poems p ON p.poem_id=l.poem_id WHERE l.line_id=?",
                (line_id,),
            ).fetchone()
            if row is None:
                return None
            poem_id = str(row["poem_id"])
            return {
                "lineId": row["line_id"],
                "poemId": poem_id,
                "lineNo": row["line_no"],
                "stanzaNo": row["stanza_no"],
                "text": row["text"],
                "startOffset": row["start_offset"],
                "endOffset": row["end_offset"],
                "lineHash": row["line_hash"],
                "title": row["title"],
                "poet": row["poet"],
                "dynasty": row["dynasty"],
                "analyses": self._analyses(connection, poem_id, line_id),
                "imagery": self._mentions(
                    connection, "imagery_mentions", poem_id, line_id
                ),
                "emotions": self._mentions(
                    connection, "emotion_mentions", poem_id, line_id
                ),
                "buildId": meta.get("build_id"),
                "schemaVersion": SCHEMA_VERSION,
                "sourceHashes": meta["sourceHashes"],
            }

    @staticmethod
    def _validate_id(value: str, field: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise KnowledgeValidationError(f"{field} 不能为空")
        normalized = value.strip()
        if len(normalized) > 200 or any(ord(character) < 32 for character in normalized):
            raise KnowledgeValidationError(f"{field} 无效")
        return normalized
