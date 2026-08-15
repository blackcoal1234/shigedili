"""Offline checks for :mod:`cbdb_identity_audit`; no project data is written."""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

import cbdb_identity_audit as audit


SCRIPT = Path(audit.__file__).resolve()


def run_cli(*arguments: object) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONUTF8"] = "1"
    return subprocess.run(
        [sys.executable, str(SCRIPT), *(str(argument) for argument in arguments)],
        cwd=audit.ROOT,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def make_database(path: Path, rows: list[tuple], aliases: list[tuple] = ()) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE BIOG_MAIN (
            c_personid INTEGER PRIMARY KEY, c_name_chn TEXT, c_birthyear INTEGER,
            c_deathyear INTEGER, c_index_year INTEGER, c_fl_earliest_year INTEGER,
            c_fl_latest_year INTEGER, c_dy INTEGER
        );
        CREATE TABLE ALTNAME_DATA (c_personid INTEGER, c_alt_name_chn TEXT);
        CREATE TABLE DYNASTIES (c_dy INTEGER PRIMARY KEY, c_dynasty_chn TEXT, c_start INTEGER, c_end INTEGER);
        INSERT INTO DYNASTIES VALUES (6, '唐', 618, 907), (15, '宋', 960, 1279), (0, '未詳', 0, 0);
        """
    )
    connection.executemany("INSERT INTO BIOG_MAIN VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)
    connection.executemany("INSERT INTO ALTNAME_DATA VALUES (?, ?)", aliases)
    connection.commit()
    connection.close()


def make_corpus_database(path: Path) -> None:
    rows: list[tuple] = []
    for index, profile in enumerate(audit.corpus_poet_profiles()):
        poet = str(profile["poet"])
        dynasty = str(profile["dynasty"])
        dynasty_code = 6 if dynasty == "Tang" else 15
        year = 700 if dynasty == "Tang" else 1050
        if poet == "常建":
            rows.extend(
                (person_id, poet, None, None, None, None, None, dynasty_code)
                for person_id in audit.CHANG_JIAN_IDS
            )
            continue
        person_id = audit.OVERRIDES.get(poet, 1_000_000 + index)
        rows.append((person_id, poet, year, year + 50, year, year + 20, year + 40, dynasty_code))
    make_database(path, rows)


def make_committed_wal_database(path: Path) -> tuple[sqlite3.Connection, str, tuple[int, int, int, int]]:
    """Leave a committed row in WAL while keeping the main DB bytes unchanged."""
    make_database(path, [(1, "甲", 700, 760, 700, None, None, 6)])
    writer = sqlite3.connect(path)
    assert writer.execute("PRAGMA journal_mode=WAL").fetchone()[0].casefold() == "wal"
    writer.execute("PRAGMA wal_autocheckpoint=0")
    main_sha256 = audit.sha256_file(path)
    main_stat = audit._stat_fingerprint(path)
    writer.execute(
        "INSERT INTO BIOG_MAIN VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (2, "乙", 1050, 1100, 1050, None, None, 15),
    )
    writer.commit()
    reader = sqlite3.connect(path)
    try:
        assert reader.execute("SELECT COUNT(*) FROM BIOG_MAIN").fetchone()[0] == 2
    finally:
        reader.close()
    wal = Path(f"{path}-wal")
    assert wal.exists() and wal.stat().st_size > 0
    assert audit.sha256_file(path) == main_sha256
    assert audit._stat_fingerprint(path) == main_stat
    return writer, main_sha256, main_stat


def test_primary_alias_and_tie(directory: Path) -> None:
    database = directory / "small.sqlite3"
    make_database(
        database,
        [
            (1, "甲", 700, 760, 700, 730, 750, 6),
            (2, "甲", 1100, 1150, 1100, None, None, 15),
            (3, "乙別名", 1050, 1100, 1050, None, None, 15),
            (4, "丙", None, None, None, None, None, 6),
            (5, "丙", None, None, None, None, None, 6),
        ],
        [(3, "乙")],
    )
    result = audit.audit_profiles(database, [{"poet": "甲", "dynasty": "Tang"}, {"poet": "乙", "dynasty": "Song"}, {"poet": "丙", "dynasty": "Tang"}])
    assert result["unique"] == {"甲": 1, "乙": 3}
    assert result["ambiguous"] == {"丙": [4, 5]}
    assert set(result["accepted_names"]["乙"]) == {"乙", "乙別名"}
    assert result["selection_notes"]["乙"]["reason"] == "unique_highest_score"


def test_hash_mismatch(directory: Path) -> None:
    database = directory / "hash.sqlite3"
    make_database(database, [(1, "甲", 700, 760, 700, None, None, 6)])
    try:
        audit.audit_profiles(database, [{"poet": "甲", "dynasty": "Tang"}], expected_sha256="0" * 64)
    except audit.IdentityAuditError as error:
        assert "SHA-256 mismatch" in str(error)
    else:
        raise AssertionError("hash mismatch was accepted")


def test_query_snapshot_binding(directory: Path) -> None:
    database = directory / "snapshot.sqlite3"
    make_database(database, [(1, "甲", 700, 760, 700, None, None, 6)])
    original_hash = audit.sha256_file
    original_loader = audit._load_candidates
    hash_calls: list[Path] = []
    transaction_states: list[bool] = []

    def counted_hash(path: Path, chunk_size: int = 1024 * 1024) -> str:
        hash_calls.append(path)
        return original_hash(path, chunk_size)

    def checked_loader(connection: sqlite3.Connection, profiles: object) -> dict:
        transaction_states.append(connection.in_transaction)
        return original_loader(connection, profiles)

    audit.sha256_file = counted_hash
    audit._load_candidates = checked_loader
    try:
        result = audit.audit_profiles(database, [{"poet": "甲", "dynasty": "Tang"}])
    finally:
        audit.sha256_file = original_hash
        audit._load_candidates = original_loader
    assert len(hash_calls) == 2, hash_calls
    assert transaction_states == [True], transaction_states
    assert result["database_sha256"] == original_hash(database)


def test_snapshot_change_detection(directory: Path) -> None:
    database = directory / "changing.sqlite3"
    make_database(database, [(1, "甲", 700, 760, 700, None, None, 6)])
    original_hash = audit.sha256_file
    calls = 0

    def changing_hash(path: Path, chunk_size: int = 1024 * 1024) -> str:
        nonlocal calls
        calls += 1
        digest = original_hash(path, chunk_size)
        return digest if calls == 1 else ("0" * 64 if digest != "0" * 64 else "1" * 64)

    audit.sha256_file = changing_hash
    try:
        try:
            audit.audit_profiles(database, [{"poet": "甲", "dynasty": "Tang"}])
        except audit.IdentityAuditError as error:
            assert "SHA-256 changed" in str(error)
        else:
            raise AssertionError("pre/post SHA-256 drift was accepted")
    finally:
        audit.sha256_file = original_hash

    original_stat = audit._stat_fingerprint
    stable = original_stat(database)
    stat_calls = 0

    def changing_stat(path: Path) -> tuple[int, int, int, int]:
        nonlocal stat_calls
        stat_calls += 1
        return stable if stat_calls < 3 else (*stable[:3], stable[3] + 1)

    audit._stat_fingerprint = changing_stat
    try:
        try:
            audit.audit_profiles(database, [{"poet": "甲", "dynasty": "Tang"}])
        except audit.IdentityAuditError as error:
            assert "identity, size, or mtime changed" in str(error)
        else:
            raise AssertionError("database stat drift was accepted")
    finally:
        audit._stat_fingerprint = original_stat


def test_committed_wal_is_rejected(directory: Path) -> None:
    database = directory / "committed-wal.sqlite3"
    writer, main_sha256, main_stat = make_committed_wal_database(database)
    wal = Path(f"{database}-wal")
    wal_before = wal.read_bytes()
    try:
        try:
            audit.audit_profiles(database, [{"poet": "甲", "dynasty": "Tang"}])
        except audit.IdentityAuditError as error:
            assert "non-empty SQLite sidecar" in str(error)
            assert wal.name in str(error)
        else:
            raise AssertionError("committed WAL snapshot was accepted")
        result = run_cli("--database", database)
        assert result.returncode == 2, result.stderr
        assert "non-empty SQLite sidecar" in result.stderr
        assert audit.sha256_file(database) == main_sha256
        assert audit._stat_fingerprint(database) == main_stat
        assert wal.read_bytes() == wal_before
    finally:
        writer.close()


def test_wal_mode_without_sidecars_is_rejected(directory: Path) -> None:
    database = directory / "wal-mode.sqlite3"
    make_database(database, [(1, "甲", 700, 760, 700, None, None, 6)])
    connection = sqlite3.connect(database)
    assert connection.execute("PRAGMA journal_mode=WAL").fetchone()[0].casefold() == "wal"
    connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    connection.close()
    for suffix in audit.SIDECAR_SUFFIXES:
        sidecar = Path(f"{database}{suffix}")
        if sidecar.exists():
            sidecar.unlink()
    try:
        audit.audit_profiles(database, [{"poet": "甲", "dynasty": "Tang"}])
    except audit.IdentityAuditError as error:
        assert "unsupported SQLite journal_mode 'wal'" in str(error)
    else:
        raise AssertionError("sidecar-free WAL journal_mode was accepted")
    result = run_cli("--database", database)
    assert result.returncode == 2, result.stderr
    assert "unsupported SQLite journal_mode 'wal'" in result.stderr


def test_hot_journal_and_nonempty_shm_are_rejected(directory: Path) -> None:
    database = directory / "hot-journal.sqlite3"
    rows = [
        (person_id, f"人{person_id}", 700, 760, 700, None, None, 6)
        for person_id in range(1, 3001)
    ]
    make_database(database, rows)
    crash_script = """
import os
import sqlite3
import sys

connection = sqlite3.connect(sys.argv[1])
connection.execute("PRAGMA journal_mode=DELETE")
connection.execute("PRAGMA synchronous=FULL")
connection.execute("PRAGMA cache_size=5")
connection.execute("BEGIN IMMEDIATE")
connection.execute("UPDATE BIOG_MAIN SET c_index_year = c_index_year + 1")
os._exit(0)
"""
    crashed = subprocess.run(
        [sys.executable, "-c", crash_script, str(database)],
        cwd=audit.ROOT,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1"},
        check=False,
    )
    assert crashed.returncode == 0
    journal = Path(f"{database}-journal")
    assert journal.exists() and journal.stat().st_size > 0
    assert journal.read_bytes()[:8] == b"\xd9\xd5\x05\xf9\x20\xa1\x63\xd7"
    database_before = database.read_bytes()
    journal_before = journal.read_bytes()
    try:
        audit.audit_profiles(database, [{"poet": "甲", "dynasty": "Tang"}])
    except audit.IdentityAuditError as error:
        assert journal.name in str(error)
    else:
        raise AssertionError("hot rollback journal was accepted")
    result = run_cli("--database", database)
    assert result.returncode == 2, result.stderr
    assert journal.name in result.stderr
    assert database.read_bytes() == database_before
    assert journal.read_bytes() == journal_before

    journal.unlink()
    shm = Path(f"{database}-shm")
    shm.write_bytes(b"non-empty shared-memory fixture")
    try:
        audit.audit_profiles(database, [{"poet": "甲", "dynasty": "Tang"}])
    except audit.IdentityAuditError as error:
        assert shm.name in str(error)
    else:
        raise AssertionError("non-empty SHM sidecar was accepted")
    result = run_cli("--database", database)
    assert result.returncode == 2, result.stderr
    assert shm.name in result.stderr
    shm.unlink()


def test_sidecar_appearing_during_audit_is_rejected(directory: Path) -> None:
    database = directory / "sidecar-race.sqlite3"
    sidecar = Path(f"{database}-journal")
    make_database(database, [(1, "甲", 700, 760, 700, None, None, 6)])
    original_loader = audit._load_candidates

    def loader_with_sidecar(connection: sqlite3.Connection, profiles: object) -> dict:
        result = original_loader(connection, profiles)
        sidecar.write_bytes(b"appeared during transactional reads")
        return result

    audit._load_candidates = loader_with_sidecar
    try:
        try:
            audit.audit_profiles(database, [{"poet": "甲", "dynasty": "Tang"}])
        except audit.IdentityAuditError as error:
            assert "after transactional SELECTs" in str(error)
        else:
            raise AssertionError("sidecar created during audit was accepted")
    finally:
        audit._load_candidates = original_loader
        if sidecar.exists():
            sidecar.unlink()


def test_overrides_and_chang_jian(directory: Path) -> None:
    database = directory / "fixed.sqlite3"
    make_database(
        database,
        [
            (93417, "张龟龄", 730, 810, 730, None, None, 6),
            (450756, "张志和", None, None, None, None, None, 6),
            (13742, "张先", 992, 1039, 992, None, None, 15),
            (27114, "张先", 990, 1078, 990, None, None, 15),
            *[(person_id, "常建", None, None, None, None, None, 6 if person_id == 94489 else 0) for person_id in audit.CHANG_JIAN_IDS],
        ],
        [(93417, "张志和")],
    )
    result = audit.audit_profiles(
        database,
        [{"poet": "张志和", "dynasty": "Tang"}, {"poet": "张先", "dynasty": "Song"}, {"poet": "常建", "dynasty": "Tang"}],
    )
    assert result["unique"] == {"张志和": 93417, "张先": 27114}
    assert result["ambiguous"] == {"常建": audit.CHANG_JIAN_IDS}
    assert result["selection_notes"]["张志和"]["reason"] == "minimal_manual_override"


def test_query_only_rejects_writes(directory: Path) -> None:
    database = directory / "query-only.sqlite3"
    make_database(database, [(1, "甲", 700, 760, 700, None, None, 6)])
    before = database.read_bytes()
    connection = audit._read_only_connection(database)
    try:
        assert connection.execute("PRAGMA query_only").fetchone()[0] == 1
        connection.execute("BEGIN")
        try:
            connection.execute("UPDATE BIOG_MAIN SET c_name_chn = '乙' WHERE c_personid = 1")
        except sqlite3.OperationalError:
            pass
        else:
            raise AssertionError("query_only connection accepted a write")
    finally:
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        connection.close()
    assert database.read_bytes() == before


def test_cli_default_zero_landing(directory: Path) -> None:
    database = directory / "cli-default.sqlite3"
    make_corpus_database(database)
    before_names = {path.name for path in directory.iterdir()}
    before_database = database.read_bytes()
    result = run_cli("--database", database)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert len(payload["unique"]) == 87
    assert payload["ambiguous"] == {"常建": audit.CHANG_JIAN_IDS}
    assert {path.name for path in directory.iterdir()} == before_names
    assert database.read_bytes() == before_database


def test_cli_atomic_output(directory: Path) -> None:
    database = directory / "cli-output.sqlite3"
    output = directory / "audit.json"
    make_corpus_database(database)
    output.write_text("old payload", encoding="utf-8")
    before_database = database.read_bytes()
    result = run_cli("--database", database, "--output", output)
    assert result.returncode == 0, result.stderr
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert len(payload["accepted_names"]) == 87
    assert not list(directory.glob(f".{output.name}.*.tmp"))
    assert database.read_bytes() == before_database


def test_cli_rejects_database_output_aliases(directory: Path) -> None:
    database = directory / "cli-source.sqlite3"
    make_corpus_database(database)
    before = database.read_bytes()
    alias_parent = directory / "alias-parent"
    alias_parent.mkdir()
    lexical_alias = alias_parent / ".." / database.name
    hard_link = directory / "database-hard-link.sqlite3"
    os.link(database, hard_link)
    outputs = [database, lexical_alias, hard_link]
    symbolic_link = directory / "database-symbolic-link.sqlite3"
    try:
        symbolic_link.symlink_to(database)
    except OSError:
        print("symlink alias case skipped: symlink creation unavailable")
    else:
        outputs.append(symbolic_link)

    for output in outputs:
        result = run_cli("--database", database, "--output", output)
        assert result.returncode == 2, (output, result.stderr)
        assert "must not refer to" in result.stderr
        assert database.read_bytes() == before
    assert os.path.samefile(database, hard_link)


def test_cli_semantic_negative_exit_2(directory: Path) -> None:
    database = directory / "cli-semantic.sqlite3"
    snapshot = directory / "semantic-mismatch.json"
    output = directory / "must-not-exist.json"
    make_corpus_database(database)
    before = database.read_bytes()
    expected = audit.audit_default_database(database)
    first_poet = next(iter(expected["unique"]))
    expected["unique"][first_poet] += 1
    snapshot.write_text(json.dumps(expected, ensure_ascii=False), encoding="utf-8")
    result = run_cli(
        "--database",
        database,
        "--check-against",
        snapshot,
        "--output",
        output,
    )
    assert result.returncode == 2, result.stderr
    assert "unique differs" in result.stderr
    assert not output.exists()
    assert database.read_bytes() == before


def test_real_database_if_present() -> None:
    database = audit.DEFAULT_DATABASE
    snapshot = audit.DEFAULT_SNAPSHOT
    if not database.exists():
        print(f"integration explicitly skipped: CBDB database absent at {database}")
        return
    result = audit.audit_default_database(database)
    problems = audit.validate_audit(result, audit.corpus_poet_profiles())
    assert not problems, problems
    expected = json.loads(snapshot.read_text(encoding="utf-8"))
    differences = audit.semantic_differences(result, expected)
    assert not differences, differences
    assert len(result["accepted_names"]) == 87
    print("integration passed: unique=87, ambiguous=常建, accepted_names=87")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="cbdb-identity-audit-") as temporary:
        directory = Path(temporary)
        test_primary_alias_and_tie(directory)
        test_hash_mismatch(directory)
        test_query_snapshot_binding(directory)
        test_snapshot_change_detection(directory)
        test_committed_wal_is_rejected(directory)
        test_wal_mode_without_sidecars_is_rejected(directory)
        test_hot_journal_and_nonempty_shm_are_rejected(directory)
        test_sidecar_appearing_during_audit_is_rejected(directory)
        test_overrides_and_chang_jian(directory)
        test_query_only_rejects_writes(directory)
        test_cli_default_zero_landing(directory)
        test_cli_atomic_output(directory)
        test_cli_rejects_database_output_aliases(directory)
        test_cli_semantic_negative_exit_2(directory)
    test_real_database_if_present()
    print("cbdb_identity_audit checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
