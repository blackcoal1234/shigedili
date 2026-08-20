# -*- coding: utf-8 -*-
"""重新发布已验证的诗歌知识库快照，不重建或删除现有分析数据。"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
AGENT_DIR = ROOT / "apps" / "agent-ui" / "agent"
sys.path.insert(0, str(AGENT_DIR))

from poetry_agent.cache import sha256_source_file  # noqa: E402
from poetry_agent.knowledge import (  # noqa: E402
    SCHEMA_VERSION,
    manifest_path_for,
    sha256_path,
)
from poetry_agent.knowledge_builder import (  # noqa: E402
    DEFAULT_SOURCE,
    SPLITTER_VERSION,
    _source_hashes,
    stable_hash,
    utc_now,
    validate_database,
)


DEFAULT_DB = ROOT / "output" / "assets" / "knowledge" / "poetry_knowledge.sqlite3"
BUILDER_SOURCE = "apps/agent-ui/agent/poetry_agent/knowledge_builder.py"


class SnapshotPublishError(RuntimeError):
    pass


def _atomic_json(path: Path, payload: dict) -> None:
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def publish_snapshot(
    database: Path,
    *,
    allow_builder_hash_update: bool = False,
) -> dict:
    database = database.expanduser().resolve()
    if not database.is_file():
        raise SnapshotPublishError(f"知识库不存在: {database}")

    manifest_path = manifest_path_for(database)
    if not manifest_path.is_file():
        raise SnapshotPublishError(f"manifest 不存在: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    current_hashes = _source_hashes(DEFAULT_SOURCE)

    connection = sqlite3.connect(database)
    try:
        validate_database(connection)
        meta = dict(connection.execute("SELECT key,value FROM meta"))
        stored_hashes = json.loads(meta.get("source_hashes", "{}"))
        changed = sorted(
            key
            for key in set(stored_hashes) | set(current_hashes)
            if stored_hashes.get(key) != current_hashes.get(key)
        )
        disallowed = []
        for key in changed:
            path = ROOT / key
            eol_only_migration = (
                path.is_file()
                and stored_hashes.get(key) == sha256_path(path)
                and current_hashes.get(key) == sha256_source_file(path)
            )
            if eol_only_migration:
                continue
            if allow_builder_hash_update and key == BUILDER_SOURCE:
                continue
            disallowed.append(key)
        if disallowed:
            raise SnapshotPublishError(
                "源哈希变化超出允许边界: " + ", ".join(disallowed)
            )

        filters = json.loads(meta.get("build_filters", "{}"))
        build_id = meta.get("build_id")
        generated_at = utc_now()
        if changed:
            build_id = stable_hash(
                SCHEMA_VERSION,
                SPLITTER_VERSION,
                json.dumps(current_hashes, sort_keys=True),
                filters.get("poet") or "",
                filters.get("limit") or "all",
                length=24,
            )
            connection.execute(
                "INSERT OR REPLACE INTO meta(key,value) VALUES('source_hashes',?)",
                (json.dumps(current_hashes, ensure_ascii=False, sort_keys=True),),
            )
            connection.execute(
                "INSERT OR REPLACE INTO meta(key,value) VALUES('build_id',?)",
                (build_id,),
            )
        connection.execute(
            "INSERT OR REPLACE INTO meta(key,value) VALUES('generated_at',?)",
            (generated_at,),
        )
        connection.execute(
            "INSERT OR REPLACE INTO meta(key,value) VALUES('guide_status','assistant_enriched')"
        )
        connection.commit()
        validate_database(connection)

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
            "assistantGuideCount": connection.execute(
                "SELECT COUNT(*) FROM analyses WHERE kind='poem_guide' "
                "AND model='zcode-assistant-glm5.3'"
            ).fetchone()[0],
        }
    finally:
        connection.close()

    payload = {
        **manifest,
        **counts,
        "schemaVersion": SCHEMA_VERSION,
        "database": database.name,
        "databaseSha256": sha256_path(database),
        "buildId": build_id,
        "sourceHashes": current_hashes,
        "filters": filters,
        "generatedAt": generated_at,
    }
    _atomic_json(manifest_path, payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument(
        "--allow-builder-hash-update",
        action="store_true",
        help="仅允许 knowledge_builder.py 单项源哈希变化",
    )
    args = parser.parse_args()
    try:
        result = publish_snapshot(
            args.db,
            allow_builder_hash_update=args.allow_builder_hash_update,
        )
    except (SnapshotPublishError, sqlite3.Error, OSError, json.JSONDecodeError) as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 2
    print(
        "[ok] 发布知识库快照 "
        f"build={result['buildId']} guides={result['assistantGuideCount']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
