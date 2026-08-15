"""Read-only, deterministic CBDB identity audit for the 88-poet corpus.

The module has no refresh or collection behaviour.  Its default CLI operation
only prints the audit; ``--output`` is the sole operation which writes a file.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from background_contract import corpus_poet_profiles
from poet_reference_corpus import aliases_for_name, normalize_name


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATABASE = ROOT / ".cache" / "background_sources" / "cbdb" / "latest.sqlite3"
DEFAULT_SNAPSHOT = ROOT / "data" / "candidates" / "cbdb_identity_audit_88.json"
OVERRIDES = {"张志和": 93417, "张先": 27114}
CHANG_JIAN_IDS = [94489, 147391, 149973, 163667]
ERA_RANGES = {"Tang": (618, 959), "Song": (960, 1279)}
YEAR_COLUMNS = (
    "c_birthyear",
    "c_deathyear",
    "c_index_year",
    "c_fl_earliest_year",
    "c_fl_latest_year",
)
SIDECAR_SUFFIXES = ("-wal", "-journal", "-shm")


class IdentityAuditError(ValueError):
    """Raised when the read-only input or audit invariants are invalid."""


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
            raise IdentityAuditError(f"could not inspect SQLite sidecar {sidecar}: {error}") from error
        if size:
            found.append(f"{sidecar.name} ({size} bytes)")
    if found:
        raise IdentityAuditError(f"non-empty SQLite sidecar present {phase}: {', '.join(found)}")


def _require_rollback_journal_header(database: Path) -> None:
    """Reject a WAL-format header before SQLite can create SHM on open."""
    with database.open("rb") as handle:
        header = handle.read(20)
    if len(header) < 20 or header[:16] != b"SQLite format 3\x00":
        raise IdentityAuditError("database does not have a valid SQLite 3 header")
    write_version, read_version = header[18], header[19]
    if (write_version, read_version) == (2, 2):
        raise IdentityAuditError("unsupported SQLite journal_mode 'wal'; expected 'delete'")
    if (write_version, read_version) != (1, 1):
        raise IdentityAuditError(
            f"unsupported SQLite header write/read versions: {write_version}/{read_version}"
        )


def _paths_refer_to_same_file(database: Path, output: Path) -> bool:
    """Detect lexical aliases, symlinks, and hard links without writing."""
    if database.resolve() == output.resolve():
        return True
    if database.exists() and output.exists():
        return os.path.samefile(database, output)
    return False


def _read_only_connection(database: Path) -> sqlite3.Connection:
    if not database.is_file():
        raise IdentityAuditError(f"CBDB database is missing: {database}")
    connection = sqlite3.connect(f"file:{database.resolve().as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    return connection


def _int_year(value: object) -> int | None:
    try:
        year = int(value)  # CBDB represents unknown values as both NULL and 0.
    except (TypeError, ValueError):
        return None
    return year if year else None


def _overlaps(left_start: int | None, left_end: int | None, era: tuple[int, int]) -> bool:
    if left_start is None and left_end is None:
        return False
    start = left_start if left_start is not None else left_end
    end = left_end if left_end is not None else left_start
    return start <= era[1] and end >= era[0]


def _candidate_score(row: dict[str, Any], dynasty: str, matched_primary: bool, matched_alias: bool) -> int | None:
    """Score a candidate after the Tang/Song period filter.

    CBDB dynasty bounds are the main evidence.  Birth, death, index, and
    first/last floruit years then break same-period homonyms deterministically.
    A candidate outside the requested period is removed before scoring.
    """
    era = ERA_RANGES.get(dynasty)
    if era is None:
        raise IdentityAuditError(f"unsupported corpus dynasty: {dynasty!r}")
    dyn_start, dyn_end = _int_year(row.get("c_start")), _int_year(row.get("c_end"))
    years = [_int_year(row.get(column)) for column in YEAR_COLUMNS]
    dynasty_match = _overlaps(dyn_start, dyn_end, era)
    year_matches = sum(year is not None and era[0] <= year <= era[1] for year in years)
    # A row with neither a matching dynasty interval nor a matching dated fact
    # has no era evidence and is intentionally excluded.
    if not dynasty_match and not year_matches:
        return None
    return 100 * int(dynasty_match) + 10 * year_matches + 3 * int(matched_primary) + int(matched_alias)


def _load_candidates(connection: sqlite3.Connection, profiles: Iterable[dict[str, Any]]) -> dict[str, dict[int, dict[str, Any]]]:
    """Stream both CBDB name columns once and retain only controlled aliases."""
    if not connection.in_transaction:
        raise IdentityAuditError("CBDB SELECTs require an explicit read-only transaction")
    names_to_poets: dict[str, set[str]] = defaultdict(set)
    for profile in profiles:
        poet = str(profile["poet"])
        for alias in aliases_for_name(poet):
            names_to_poets[normalize_name(alias)].add(poet)

    matched: dict[str, dict[int, dict[str, Any]]] = defaultdict(dict)
    primary_ids: dict[str, set[int]] = defaultdict(set)
    alias_ids: dict[str, set[int]] = defaultdict(set)
    for row in connection.execute("SELECT c_personid, c_name_chn FROM BIOG_MAIN"):
        for poet in names_to_poets.get(normalize_name(row["c_name_chn"]), ()):
            primary_ids[poet].add(int(row["c_personid"]))
    for row in connection.execute("SELECT c_personid, c_alt_name_chn FROM ALTNAME_DATA"):
        for poet in names_to_poets.get(normalize_name(row["c_alt_name_chn"]), ()):
            alias_ids[poet].add(int(row["c_personid"]))

    all_ids = sorted(set().union(*primary_ids.values(), *alias_ids.values())) if names_to_poets else []
    if not all_ids:
        return matched
    columns = ", ".join(f"b.{column}" for column in ("c_personid", "c_name_chn", *YEAR_COLUMNS, "c_dy"))
    placeholders = ",".join("?" for _ in all_ids)
    sql = f"""
        SELECT {columns}, d.c_dynasty_chn, d.c_start, d.c_end
        FROM BIOG_MAIN AS b
        LEFT JOIN DYNASTIES AS d ON d.c_dy = b.c_dy
        WHERE b.c_personid IN ({placeholders})
    """
    rows = {int(row["c_personid"]): dict(row) for row in connection.execute(sql, all_ids)}
    for poet in names_to_poets.values():
        for name in poet:
            for person_id in primary_ids[name] | alias_ids[name]:
                row = dict(rows[person_id])
                row["matched_primary"] = person_id in primary_ids[name]
                row["matched_alias"] = person_id in alias_ids[name]
                matched[name][person_id] = row
    return matched


def _accepted_names(poet: str, selected: dict[str, Any] | None) -> list[str]:
    # Matching uses every controlled alias.  The stored audit intentionally
    # preserves only the corpus spelling and selected CBDB primary spelling.
    names = {normalize_name(poet)}
    if selected:
        names.add(normalize_name(selected.get("c_name_chn")))
    return sorted(name for name in names if name)


def audit_profiles(
    database: Path | str,
    profiles: Iterable[dict[str, Any]],
    *,
    expected_sha256: str | None = None,
) -> dict[str, Any]:
    """Audit supplied corpus profiles against a CBDB SQLite file in read-only mode."""
    database = Path(database).resolve()
    profiles = [dict(profile) for profile in profiles]
    _require_no_nonempty_sidecars(database, "before audit")
    _require_rollback_journal_header(database)
    before = _stat_fingerprint(database)
    before_sha256 = sha256_file(database)
    after_initial_hash = _stat_fingerprint(database)
    if after_initial_hash != before:
        raise IdentityAuditError("database stat changed during the pre-query SHA-256 pass")
    _require_no_nonempty_sidecars(database, "after the pre-query SHA-256 pass")
    if expected_sha256 is not None and before_sha256 != expected_sha256:
        raise IdentityAuditError(f"database SHA-256 mismatch: expected {expected_sha256}, got {before_sha256}")

    connection = _read_only_connection(database)
    try:
        connection.execute("BEGIN")
        journal_mode_row = connection.execute("PRAGMA journal_mode").fetchone()
        journal_mode = str(journal_mode_row[0] if journal_mode_row else "").strip().casefold()
        if journal_mode != "delete":
            raise IdentityAuditError(
                f"unsupported SQLite journal_mode {journal_mode or '<empty>'!r}; expected 'delete'"
            )
        _require_no_nonempty_sidecars(database, "before transactional SELECTs")
        candidates = _load_candidates(connection, profiles)
        _require_no_nonempty_sidecars(database, "after transactional SELECTs")
        after_queries = _stat_fingerprint(database)
        after_sha256 = sha256_file(database)
        after_final_hash = _stat_fingerprint(database)
        if before != after_queries or before != after_final_hash:
            raise IdentityAuditError("database identity, size, or mtime changed while being audited")
        if before_sha256 != after_sha256:
            raise IdentityAuditError("database SHA-256 changed while being audited")
        _require_no_nonempty_sidecars(database, "after the post-query SHA-256 pass")
        connection.execute("COMMIT")
    finally:
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        connection.close()

    unique: dict[str, int] = {}
    ambiguous: dict[str, list[int]] = {}
    accepted_names: dict[str, list[str]] = {}
    selection_notes: dict[str, dict[str, Any]] = {}
    for profile in profiles:
        poet, dynasty = str(profile["poet"]), str(profile["dynasty"])
        rows = candidates.get(poet, {})
        if poet == "常建":
            present = [person_id for person_id in CHANG_JIAN_IDS if person_id in rows]
            # The intentionally unresolved record is stable only when all four
            # fixture IDs remain available; no other candidate can change it.
            if present != CHANG_JIAN_IDS:
                raise IdentityAuditError(f"常建 fixed ambiguity changed: {present}")
            ambiguous[poet] = CHANG_JIAN_IDS.copy()
            selection_notes[poet] = {"status": "ambiguous", "candidate_ids": CHANG_JIAN_IDS.copy(), "reason": "fixed_homonym_set"}
            continue

        scored = []
        for person_id, row in rows.items():
            score = _candidate_score(row, dynasty, bool(row["matched_primary"]), bool(row["matched_alias"]))
            if score is not None:
                scored.append((score, person_id, row))
        scored.sort(key=lambda item: (-item[0], item[1]))
        if poet in OVERRIDES:
            person_id = OVERRIDES[poet]
            selected = rows.get(person_id)
            if selected is None:
                raise IdentityAuditError(f"override candidate missing for {poet}: {person_id}")
            unique[poet] = person_id
            accepted_names[poet] = _accepted_names(poet, selected)
            selection_notes[poet] = {"status": "unique", "candidate_id": person_id, "reason": "minimal_manual_override", "score": _candidate_score(selected, dynasty, bool(selected["matched_primary"]), bool(selected["matched_alias"]))}
            continue
        if not scored:
            ambiguous[poet] = []
            selection_notes[poet] = {"status": "ambiguous", "candidate_ids": [], "reason": "no_era_matched_candidate"}
            continue
        best_score = scored[0][0]
        winners = [item for item in scored if item[0] == best_score]
        if len(winners) != 1:
            ambiguous[poet] = [person_id for _, person_id, _ in winners]
            selection_notes[poet] = {"status": "ambiguous", "candidate_ids": ambiguous[poet], "reason": "top_score_tie", "score": best_score}
            continue
        score, person_id, selected = winners[0]
        unique[poet] = person_id
        accepted_names[poet] = _accepted_names(poet, selected)
        selection_notes[poet] = {"status": "unique", "candidate_id": person_id, "reason": "unique_highest_score", "score": score}

    return {
        "source": "CBDB BIOG_MAIN.c_name_chn + ALTNAME_DATA.c_alt_name_chn read-only audit",
        "database_sha256": before_sha256,
        "unique": unique,
        "ambiguous": ambiguous,
        "rule": "Tang/Song era filter; only a unique highest score is auto-bound; 张志和 and 张先 use minimal overrides; 常建 remains fixed ambiguous.",
        "accepted_names": accepted_names,
        "selection_notes": selection_notes,
    }


def audit_default_database(database: Path | str = DEFAULT_DATABASE, *, expected_sha256: str | None = None) -> dict[str, Any]:
    return audit_profiles(database, corpus_poet_profiles(), expected_sha256=expected_sha256)


def semantic_differences(actual: dict[str, Any], expected: dict[str, Any]) -> list[str]:
    """Compare the identity-bearing portions of two audit documents."""
    differences: list[str] = []
    for key in ("unique", "ambiguous"):
        if actual.get(key) != expected.get(key):
            differences.append(f"{key} differs")
    actual_names, expected_names = actual.get("accepted_names", {}), expected.get("accepted_names", {})
    if set(actual_names) != set(expected_names):
        differences.append("accepted_names keys differ")
    else:
        for poet in actual_names:
            if set(actual_names[poet]) != set(expected_names[poet]):
                differences.append(f"accepted_names differs for {poet}")
    return differences


def validate_audit(audit: dict[str, Any], profiles: Iterable[dict[str, Any]]) -> list[str]:
    poets = [str(profile["poet"]) for profile in profiles]
    problems: list[str] = []
    if len(poets) != 88 or len(set(poets)) != 88:
        problems.append("corpus must contain exactly 88 distinct poets")
    if len(audit.get("unique", {})) != 87:
        problems.append("unique must contain 87 poets")
    if audit.get("ambiguous") != {"常建": CHANG_JIAN_IDS}:
        problems.append("ambiguous must contain only the fixed 常建 IDs")
    if set(audit.get("accepted_names", {})) != set(audit.get("unique", {})):
        problems.append("accepted_names must cover every unique poet exactly once")
    for poet, person_id in audit.get("unique", {}).items():
        names = set(audit.get("accepted_names", {}).get(poet, ()))
        if poet not in names:
            problems.append(f"accepted_names missing corpus name for {poet}")
        note = audit.get("selection_notes", {}).get(poet, {})
        if note.get("candidate_id") != person_id:
            problems.append(f"selection_notes missing selected ID for {poet}")
    return problems


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE, help="read-only SQLite input (default: cache CBDB)")
    parser.add_argument("--output", type=Path, help="atomically write JSON; omitted means print only")
    parser.add_argument("--check-against", type=Path, help="compare identity semantics with a snapshot")
    parser.add_argument("--expected-sha256", help="fail when the streamed database hash differs")
    args = parser.parse_args(argv)
    try:
        if args.output and _paths_refer_to_same_file(args.database, args.output):
            raise IdentityAuditError("--output must not refer to the --database file")
        audit = audit_default_database(args.database, expected_sha256=args.expected_sha256)
        problems = validate_audit(audit, corpus_poet_profiles())
        if problems:
            raise IdentityAuditError("; ".join(problems))
        if args.check_against:
            expected = json.loads(args.check_against.read_text(encoding="utf-8"))
            differences = semantic_differences(audit, expected)
            if differences:
                raise IdentityAuditError("; ".join(differences))
        payload = json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        if args.output:
            _atomic_write(args.output, payload)
        else:
            sys.stdout.write(payload)
    except (IdentityAuditError, OSError, sqlite3.Error, json.JSONDecodeError) as error:
        print(f"cbdb identity audit: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
