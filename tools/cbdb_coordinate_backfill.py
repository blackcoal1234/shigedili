"""Read-only CBDB coordinate backfill for six target poets.

Every candidate whose ``source`` is ``cbdb`` and that carries a ``cbdb_addr_id``
but no lon/lat is joined directly to ``ADDR_CODES`` on ``c_addr_id``.  The only
accepted evidence is the exact address row itself: the Chinese name must match
the candidate place after whitespace normalisation, coordinates must be finite
and within valid longitude/latitude bounds (never the ``(0, 0)`` sentinel), and
the event year interval must intersect the address interval.  No birthplace,
index address, parent administration, modern city or any other inference is used.

The database is opened with ``mode=ro``, ``PRAGMA query_only``, and every
``SELECT`` runs inside one explicit read-only transaction.  ``-wal``/``-journal``/
``-shm`` sidecars are rejected before, inside, and after the transaction window,
and the main file identity, size, mtime, and streamed SHA-256 are verified
unchanged between the pre-query and post-query passes.  Output must never refer
to an input through an alias, symlink, or hard link.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sqlite3
import sys
import uuid
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATABASE = ROOT / ".cache" / "background_sources" / "cbdb" / "latest.sqlite3"
DEFAULT_CANDIDATES = ROOT / "data" / "candidates" / "journey_event_candidates.jsonl"
DEFAULT_OUTPUT = ROOT / "data" / "candidates" / "cbdb_event_coordinate_supplements.jsonl"
DEFAULT_REPORT = ROOT / "docs" / "cbdb-coordinate-backfill.md"

TARGET_POETS = ("司空曙", "卢纶", "李益", "司马光", "欧阳炯", "钱惟演")
SOURCE = "cbdb"
COORDINATE_SOURCE_TABLE = "ADDR_CODES"
SIDECAR_SUFFIXES = ("-wal", "-journal", "-shm")
NOTE = "按 cbdb_addr_id 直接联接 ADDR_CODES，无地名推断/现代城市替代"
SENTINEL_REASON = "SENTINEL (0,0)"
DB_NULL_REASON = "DB NULL"
OUTPUT_KEYS = (
    "candidate_id",
    "stable_link_key",
    "poet",
    "event_year",
    "year_start",
    "year_end",
    "place",
    "lon",
    "lat",
    "cbdb_person_id",
    "cbdb_addr_id",
    "coordinate_source_table",
    "coordinate_source_row_id",
    "chgis_pt_id",
    "coordinate_source_database",
    "coordinate_source_database_sha256",
    "source_url",
    "source_grade",
    "fact_grade",
    "coordinate_grade",
    "note",
)


class BackfillError(ValueError):
    """Raised when a read-only input or a backfill invariant is invalid."""


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    """Return the actual streaming SHA-256 of *path*."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def _stat_fingerprint(path: Path) -> tuple[int, int, int, int]:
    """Return file identity, size, and nanosecond mtime for stability checks."""
    stat = path.stat()
    return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)


def _require_no_nonempty_sidecars(database: Path, phase: str) -> None:
    """Reject WAL, rollback-journal, and shared-memory sidecar state."""
    found: list[str] = []
    for suffix in SIDECAR_SUFFIXES:
        sidecar = Path(f"{database}{suffix}")
        try:
            size = sidecar.stat().st_size
        except FileNotFoundError:
            continue
        except OSError as error:
            raise BackfillError(f"could not inspect SQLite sidecar {sidecar}: {error}") from error
        if size:
            found.append(f"{sidecar.name} ({size} bytes)")
    if found:
        raise BackfillError(f"non-empty SQLite sidecar present {phase}: {', '.join(found)}")


def _require_rollback_journal_header(database: Path) -> None:
    """Reject a WAL-format header before SQLite can create SHM on open."""
    with database.open("rb") as handle:
        header = handle.read(20)
    if len(header) < 20 or header[:16] != b"SQLite format 3\x00":
        raise BackfillError("database does not have a valid SQLite 3 header")
    write_version, read_version = header[18], header[19]
    if (write_version, read_version) == (2, 2):
        raise BackfillError("unsupported SQLite journal_mode 'wal'; expected 'delete'")
    if (write_version, read_version) != (1, 1):
        raise BackfillError(
            f"unsupported SQLite header write/read versions: {write_version}/{read_version}"
        )


def _paths_refer_to_same_file(first: Path, second: Path) -> bool:
    """Detect lexical aliases, symlinks, and hard links without writing."""
    if first.resolve() == second.resolve():
        return True
    if first.exists() and second.exists():
        return os.path.samefile(first, second)
    return False


def _read_only_connection(database: Path) -> sqlite3.Connection:
    if not database.is_file():
        raise BackfillError(f"CBDB database is missing: {database}")
    connection = sqlite3.connect(f"file:{database.resolve().as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    return connection


def normalize_place(text: object) -> str:
    """Collapse all Unicode whitespace; returns the canonical comparison form."""
    return " ".join(str(text or "").split())


def _int_year(value: object) -> int | None:
    try:
        year = int(value)  # CBDB represents unknown years as both NULL and 0.
    except (TypeError, ValueError):
        return None
    return year if year else None


def _as_float(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _years_intersect(event_start: int, event_end: int, first: object, last: object) -> bool:
    """True when the event interval overlaps the address interval (open ends allowed)."""
    low = _int_year(first)
    high = _int_year(last)
    if low is None and high is None:
        return True
    low = low if low is not None else -(10 ** 9)
    high = high if high is not None else 10 ** 9
    return event_start <= high and event_end >= low


def _event_year_label(year_start: int, year_end: int) -> int | str:
    """Exact single years are integers; ranges are the literal ``START-END``."""
    if year_start == year_end:
        return year_start
    return f"{year_start}-{year_end}"


def _stable_link_key(candidate: dict[str, Any]) -> str:
    """Deterministic key over immutable association fields only."""
    fields = (
        SOURCE,
        str(candidate["poet"]),
        str(candidate.get("cbdb_person_id")),
        str(candidate.get("cbdb_addr_id")),
        str(candidate.get("event_type")),
        str(candidate.get("year_start")),
        str(candidate.get("year_end")),
        normalize_place(candidate.get("historical_place")),
    )
    return hashlib.sha256("|".join(fields).encode("utf-8")).hexdigest()


def _evaluate(candidate: dict[str, Any], addr_row: dict[str, Any] | None) -> tuple[bool, str | None]:
    """Return ``(accepted, reason)``; ``reason`` is only set when rejected."""
    if addr_row is None:
        return False, "ADDR_CODES 无此 cbdb_addr_id"
    if normalize_place(addr_row.get("c_name_chn")) != normalize_place(candidate.get("historical_place")):
        return False, "地名不匹配"
    x = _as_float(addr_row.get("x_coord"))
    y = _as_float(addr_row.get("y_coord"))
    if x is None or y is None:
        return False, DB_NULL_REASON
    if x == 0.0 and y == 0.0:
        return False, SENTINEL_REASON
    if not (-180.0 <= x <= 180.0 and -90.0 <= y <= 90.0):
        return False, "坐标越界/非有限"
    if not _years_intersect(candidate["year_start"], candidate["year_end"], addr_row.get("c_firstyear"), addr_row.get("c_lastyear")):
        return False, "年份不相交"
    return True, None


def _coerce_int(value: object, field: str, candidate_id: str, line: int) -> int:
    """Strict integer coercion for association/year fields with a clear error."""
    try:
        if isinstance(value, bool):
            raise ValueError
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            return int(value.strip())
        if isinstance(value, float) and value.is_integer():
            return int(value)
        raise ValueError
    except (TypeError, ValueError) as error:
        raise BackfillError(
            f"candidate {candidate_id!r} (line {line}) has invalid {field}: {value!r}"
        ) from error


def _load_target_candidates(candidates_path: Path) -> list[dict[str, Any]]:
    """Stream the candidate JSONL and keep only target ``cbdb`` rows without lon/lat.

    Field integrity (candidate_id, cbdb_addr_id, year_start, year_end) is
    validated before any sorting; every failure names the candidate and the
    exact JSONL line, and parse errors include the candidates path.
    """
    targets: list[dict[str, Any]] = []
    seen: dict[str, int] = {}
    with candidates_path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            try:
                candidate = json.loads(line)
            except json.JSONDecodeError as error:
                raise BackfillError(
                    f"malformed JSON in {candidates_path} at line {line_number}: {error}"
                ) from error
            if not isinstance(candidate, dict):
                raise BackfillError(
                    f"non-object JSON in {candidates_path} at line {line_number}"
                )
            if candidate.get("source") != SOURCE:
                continue
            if candidate.get("poet") not in TARGET_POETS:
                continue
            if candidate.get("lon") or candidate.get("lat"):
                continue
            candidate_id = candidate.get("candidate_id")
            if candidate_id is None or str(candidate_id).strip() == "":
                raise BackfillError(
                    f"candidate (line {line_number}) is missing candidate_id in {candidates_path}"
                )
            candidate_id = str(candidate_id)
            if candidate_id in seen:
                raise BackfillError(
                    f"duplicate candidate_id {candidate_id!r} at lines "
                    f"{seen[candidate_id]} and {line_number}"
                )
            seen[candidate_id] = line_number
            candidate["cbdb_addr_id"] = str(_coerce_int(
                candidate.get("cbdb_addr_id"), "cbdb_addr_id", candidate_id, line_number
            ))
            year_start = _coerce_int(candidate.get("year_start"), "year_start", candidate_id, line_number)
            year_end = _coerce_int(candidate.get("year_end"), "year_end", candidate_id, line_number)
            if year_start > year_end:
                raise BackfillError(
                    f"candidate {candidate_id!r} (line {line_number}) has year_start {year_start} > year_end {year_end}"
                )
            candidate["year_start"] = year_start
            candidate["year_end"] = year_end
            targets.append(candidate)
    if not targets:
        raise BackfillError("no target cbdb candidates without lon/lat found")
    targets.sort(key=lambda item: (
        str(item["poet"]),
        item["year_start"],
        item["year_end"],
        item["cbdb_addr_id"],
        item["candidate_id"],
    ))
    return targets


def _database_reference(database: Path) -> str:
    """Record the database as a ROOT-relative path; absolute only when outside ROOT."""
    try:
        return database.relative_to(ROOT).as_posix()
    except ValueError:
        return database.as_posix()


def _build_output_record(
    candidate: dict[str, Any],
    addr_row: dict[str, Any],
    *,
    database_rel: str,
    database_sha256: str,
) -> dict[str, Any]:
    x = float(addr_row["x_coord"])
    y = float(addr_row["y_coord"])
    year_start = int(candidate["year_start"])
    year_end = int(candidate["year_end"])
    chgis_pt_id = _int_year(addr_row["CHGIS_PT_ID"])
    return {
        "candidate_id": str(candidate["candidate_id"]),
        "stable_link_key": _stable_link_key(candidate),
        "poet": str(candidate["poet"]),
        "event_year": _event_year_label(year_start, year_end),
        "year_start": year_start,
        "year_end": year_end,
        "place": normalize_place(candidate.get("historical_place")),
        "lon": x,
        "lat": y,
        "cbdb_person_id": str(candidate.get("cbdb_person_id")),
        "cbdb_addr_id": str(candidate.get("cbdb_addr_id")),
        "coordinate_source_table": COORDINATE_SOURCE_TABLE,
        "coordinate_source_row_id": int(addr_row["c_addr_id"]),
        "chgis_pt_id": chgis_pt_id,
        "coordinate_source_database": database_rel,
        "coordinate_source_database_sha256": database_sha256,
        "source_url": str(candidate.get("source_url", "")),
        "source_grade": str(candidate.get("source_grade", "")),
        "fact_grade": str(candidate.get("source_grade", "")),
        "coordinate_grade": "A" if chgis_pt_id is not None else "B",
        "note": NOTE,
    }


def backfill_coordinates(
    candidates: Path | str,
    database: Path | str,
    *,
    output: Path | str,
    report: Path | str | None = None,
    expected_sha256: str | None = None,
) -> dict[str, Any]:
    """Run the read-only CBDB coordinate backfill and atomically write the JSONL."""
    candidates = Path(candidates).resolve()
    database = Path(database).resolve()
    output = Path(output).resolve()
    report_path = Path(report).resolve() if report is not None else None

    for input_path in (candidates, database):
        if _paths_refer_to_same_file(input_path, output):
            raise BackfillError(f"--output must not refer to the --{'candidates' if input_path == candidates else 'database'} file")
    if report_path is not None and any(_paths_refer_to_same_file(input_path, report_path) for input_path in (candidates, database)):
        raise BackfillError("--report must not refer to an input file")
    if report_path is not None and _paths_refer_to_same_file(output, report_path):
        raise BackfillError("--output and --report must not refer to the same file")

    if not database.is_file():
        raise BackfillError(f"CBDB database is missing: {database}")
    if not candidates.is_file():
        raise BackfillError(f"candidates file is missing: {candidates}")

    _require_no_nonempty_sidecars(database, "before backfill")
    _require_rollback_journal_header(database)
    before_stat = _stat_fingerprint(database)
    before_sha256 = sha256_file(database)
    if _stat_fingerprint(database) != before_stat:
        raise BackfillError("database stat changed during the pre-query SHA-256 pass")
    if expected_sha256 is not None and before_sha256 != expected_sha256:
        raise BackfillError(f"database SHA-256 mismatch: expected {expected_sha256}, got {before_sha256}")

    candidates_stat = _stat_fingerprint(candidates)
    candidates_sha256 = sha256_file(candidates)
    if _stat_fingerprint(candidates) != candidates_stat:
        raise BackfillError("candidates stat changed during the pre-parse SHA-256 pass")

    targets = _load_target_candidates(candidates)

    if _stat_fingerprint(candidates) != candidates_stat:
        raise BackfillError("candidates file identity, size, or mtime changed while being read")
    after_candidates_sha256 = sha256_file(candidates)
    if _stat_fingerprint(candidates) != candidates_stat:
        raise BackfillError("candidates stat changed during the post-parse SHA-256 pass")
    if after_candidates_sha256 != candidates_sha256:
        raise BackfillError("candidates file SHA-256 changed while being read")
    addr_ids = sorted({int(item["cbdb_addr_id"]) for item in targets})
    placeholders = ",".join("?" for _ in addr_ids)
    sql = (
        f"SELECT c_addr_id, c_name_chn, c_firstyear, c_lastyear, x_coord, y_coord, CHGIS_PT_ID "
        f"FROM ADDR_CODES WHERE c_addr_id IN ({placeholders})"
    )

    connection = _read_only_connection(database)
    try:
        connection.execute("BEGIN")
        journal_mode_row = connection.execute("PRAGMA journal_mode").fetchone()
        journal_mode = str(journal_mode_row[0] if journal_mode_row else "").strip().casefold()
        if journal_mode != "delete":
            raise BackfillError(
                f"unsupported SQLite journal_mode {journal_mode or '<empty>'!r}; expected 'delete'"
            )
        _require_no_nonempty_sidecars(database, "before transactional SELECTs")
        addr_rows: dict[int, dict[str, Any]] = {}
        for row in connection.execute(sql, addr_ids):
            addr_rows[int(row["c_addr_id"])] = dict(row)
        _require_no_nonempty_sidecars(database, "after transactional SELECTs")
    finally:
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        connection.close()

    after_queries = _stat_fingerprint(database)
    after_sha256 = sha256_file(database)
    after_final = _stat_fingerprint(database)
    if before_stat != after_queries or before_stat != after_final:
        raise BackfillError("database identity, size, or mtime changed while being backfilled")
    if before_sha256 != after_sha256:
        raise BackfillError("database SHA-256 changed while being backfilled")
    _require_no_nonempty_sidecars(database, "after the post-query SHA-256 pass")

    success: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for candidate in targets:
        addr_row = addr_rows.get(int(candidate["cbdb_addr_id"]))
        accepted, reason = _evaluate(candidate, addr_row)
        if accepted:
            success.append(_build_output_record(
                candidate,
                addr_row,
                database_rel=_database_reference(database),
                database_sha256=before_sha256,
            ))
        else:
            failures.append({
                "candidate_id": str(candidate["candidate_id"]),
                "poet": str(candidate["poet"]),
                "year_start": candidate["year_start"],
                "year_end": candidate["year_end"],
                "place": normalize_place(candidate.get("historical_place")),
                "addr_id": candidate["cbdb_addr_id"],
                "reason": reason,
            })

    success.sort(key=lambda item: (
        item["poet"], item["year_start"], item["year_end"], item["cbdb_addr_id"], item["candidate_id"]
    ))
    failures.sort(key=lambda item: (
        item["poet"], item["year_start"], item["year_end"], item["addr_id"], item["candidate_id"]
    ))

    if len({record["candidate_id"] for record in success}) != len(success):
        raise BackfillError("duplicate candidate_id in backfill output")
    keys = [record["stable_link_key"] for record in success]
    if len(set(keys)) != len(keys):
        raise BackfillError("conflicting association keys in backfill output")

    _atomic_write_jsonl(output, success)

    result: dict[str, Any] = {
        "target_total": len(targets),
        "success": success,
        "failures": failures,
        "database": _database_reference(database),
        "database_sha256": before_sha256,
    }
    if report_path is not None:
        _atomic_write(report_path, _generate_report(result))
    return result


def _atomic_write(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _atomic_write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    payload = "".join(
        json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records
    )
    _atomic_write(path, payload)


def _generate_report(result: dict[str, Any]) -> str:
    success = result["success"]
    failures = result["failures"]
    per_poet_success: dict[str, int] = {}
    per_poet_failure: dict[str, int] = {}
    for poet in TARGET_POETS:
        per_poet_success[poet] = sum(1 for item in success if item["poet"] == poet)
        per_poet_failure[poet] = sum(1 for item in failures if item["poet"] == poet)

    lines: list[str] = []
    lines.append("# CBDB 坐标回填（严格直接联接）")
    lines.append("")
    lines.append("`tools/cbdb_coordinate_backfill.py` 是一个离线、只读、确定性的坐标回填工具：仅对 `source=cbdb` 且当前无 lon/lat 的六位目标诗人候选记录，按 `candidate.cbdb_addr_id = ADDR_CODES.c_addr_id` 直接联接，不接受出生地、索引地、上级行政区、现代代表城市或任何推断。")
    lines.append("")
    lines.append("## 输入与只读保证")
    lines.append("")
    lines.append("- 数据库只读：`.cache/background_sources/cbdb/latest.sqlite3`，以 SQLite `mode=ro` + `PRAGMA query_only` 打开，全部 `SELECT` 位于一个显式只读事务内，不创建/改变 WAL 或 journal。")
    lines.append("- 查询前后各以 1 MiB 分块实际流式计算一次主数据库 SHA-256；两次哈希必须一致，且主文件 identity、size、mtime 在检查窗口内保持稳定。`-wal`/`-journal`/`-shm` 非空 sidecar 在初始哈希、事务查询、最终哈希边界均被拒绝。")
    lines.append("- 目标诗人：司空曙、卢纶、李益、司马光、欧阳炯、钱惟演。目标记录仅 `source=cbdb` 且当前无 lon/lat。")
    lines.append("- 输出不允许通过路径别名、符号链接或硬链接指向任何输入文件。")
    lines.append("")
    lines.append("## 表结构与联接")
    lines.append("")
    lines.append("只使用 `ADDR_CODES` 一张表（列 `c_addr_id`、`c_name_chn`、`c_firstyear`、`c_lastyear`、`x_coord`、`y_coord`、`CHGIS_PT_ID`）。联接键：`candidate.cbdb_addr_id = ADDR_CODES.c_addr_id`。")
    lines.append("")
    lines.append("接受条件（全部满足才补充）：")
    lines.append("")
    lines.append("- `ADDR_CODES` 行存在；")
    lines.append("- `c_name_chn` 与 `historical_place` 规范化空白后相同；")
    lines.append("- `x_coord`/`y_coord` 均为有限数，且经度 [-180,180]、纬度 [-90,90]；拒绝 `(0,0)` 哨兵；")
    lines.append("- 事件 `year_start`/`year_end` 与 `ADDR_CODES` `c_firstyear`/`c_lastyear`（若有）相交。")
    lines.append("")
    lines.append("## 等级口径")
    lines.append("")
    lines.append("- `coordinate_grade = A`：坐标有效且 `chgis_pt_id` 非空。")
    lines.append("- `coordinate_grade = B`：坐标有效但 `chgis_pt_id` 为空。")
    lines.append("- `fact_grade` 保留候选记录的 `source_grade`。")
    lines.append("- `stable_link_key` 由不可变关联字段（source、poet、cbdb_person_id、cbdb_addr_id、event_type、year_start、year_end、historical_place）确定性推导。")
    lines.append("")
    lines.append("## 总体统计")
    lines.append("")
    lines.append(f"- 目标记录：{result['target_total']}")
    lines.append(f"- 成功补充：{len(success)}")
    lines.append(f"- 未补记录：{len(failures)}")
    lines.append(f"- 数据库 SHA-256：`{result['database_sha256']}`")
    lines.append("")
    lines.append("### 分诗人成功统计")
    lines.append("")
    lines.append("| 诗人 | 成功 | 未补 |")
    lines.append("| --- | --- | --- |")
    for poet in TARGET_POETS:
        lines.append(f"| {poet} | {per_poet_success[poet]} | {per_poet_failure[poet]} |")
    lines.append("")
    grade_counts = {"A": sum(1 for item in success if item["coordinate_grade"] == "A"),
                    "B": sum(1 for item in success if item["coordinate_grade"] == "B")}
    lines.append(f"### 等级分布：A={grade_counts['A']}，B={grade_counts['B']}")
    lines.append("")
    lines.append("## 成功补充清单")
    lines.append("")
    lines.append("| candidate_id | 诗人 | event_year | place | lon | lat | addr_id | grade |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for item in success:
        lines.append(
            f"| {item['candidate_id']} | {item['poet']} | {item['event_year']} | {item['place']} | {item['lon']} | {item['lat']} | {item['cbdb_addr_id']} | {item['coordinate_grade']} |"
        )
    lines.append("")
    lines.append("## 未补记录明细")
    lines.append("")
    lines.append("| candidate_id | 诗人 | 年份 | place | addr_id | reason |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for item in failures:
        year_label = _event_year_label(item["year_start"], item["year_end"])
        reason = item["reason"]
        if reason == SENTINEL_REASON:
            reason = f"**{SENTINEL_REASON}（哨兵，拒绝 (0,0)）**"
        elif reason == DB_NULL_REASON:
            reason = f"{DB_NULL_REASON}（坐标缺失）"
        lines.append(
            f"| {item['candidate_id']} | {item['poet']} | {year_label} | {item['place']} | {item['addr_id']} | {reason} |"
        )
    lines.append("")
    lines.append("## 复现与验证")
    lines.append("")
    lines.append("```powershell")
    lines.append("python tools/cbdb_coordinate_backfill.py")
    lines.append("python tools/check_cbdb_coordinate_backfill.py")
    lines.append("```")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE, help="read-only SQLite input (default: cache CBDB)")
    parser.add_argument("--candidates", type=Path, default=DEFAULT_CANDIDATES, help="candidate JSONL input")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="JSONL of successfully backfilled coordinates")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT, help="markdown report path")
    parser.add_argument("--no-report", action="store_true", help="do not write the markdown report")
    parser.add_argument("--expected-sha256", help="fail when the streamed database hash differs")
    args = parser.parse_args(argv)
    try:
        result = backfill_coordinates(
            args.candidates,
            args.database,
            output=args.output,
            report=None if args.no_report else args.report,
            expected_sha256=args.expected_sha256,
        )
        summary = {
            "output": str(Path(args.output).resolve()),
            "target_total": result["target_total"],
            "success": len(result["success"]),
            "failures": len(result["failures"]),
            "database_sha256": result["database_sha256"],
        }
        sys.stdout.write(json.dumps(summary, ensure_ascii=False, sort_keys=True) + "\n")
    except (BackfillError, OSError, sqlite3.Error, json.JSONDecodeError) as error:
        print(f"cbdb coordinate backfill: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
