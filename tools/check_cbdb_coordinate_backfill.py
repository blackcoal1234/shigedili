"""Offline checks for :mod:`cbdb_coordinate_backfill`; no project data is written.

Temporary fixtures (SQLite databases and candidate JSONL) are created under a
throwaway directory.  The only project paths touched are read-only: the real
candidate input, the real CBDB database, and the real backfill products which
must be byte-identical to a fresh regeneration.
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

import cbdb_coordinate_backfill as backfill


SCRIPT = Path(backfill.__file__).resolve()


def run_cli(*arguments: object) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONUTF8"] = "1"
    return subprocess.run(
        [sys.executable, str(SCRIPT), *(str(argument) for argument in arguments)],
        cwd=backfill.ROOT,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def make_database(path: Path, rows: list[tuple]) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.executescript(
            """
            CREATE TABLE ADDR_CODES (
                c_addr_id INTEGER PRIMARY KEY, c_name_chn TEXT,
                c_firstyear INTEGER, c_lastyear INTEGER,
                x_coord REAL, y_coord REAL, CHGIS_PT_ID INTEGER
            );
            """
        )
        connection.executemany(
            "INSERT INTO ADDR_CODES VALUES (?, ?, ?, ?, ?, ?, ?)", rows
        )
        connection.commit()
    finally:
        connection.close()


def make_candidates(path: Path, records: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def make_candidate(
    candidate_id: str,
    *,
    poet: str = "卢纶",
    addr_id: object = 100,
    person_id: object = 1,
    place: str = "洛陽",
    event_type: str = "posting",
    year_start: int = 800,
    year_end: int = 800,
    year_precision: str = "exact",
    grade: str = "B",
    url: str = "https://cbdb.fas.harvard.edu/cbdbapi/person?id=1&mode=json",
) -> dict:
    return {
        "source": "cbdb",
        "candidate_id": candidate_id,
        "poet": poet,
        "cbdb_addr_id": str(addr_id),
        "cbdb_person_id": str(person_id),
        "historical_place": place,
        "event_type": event_type,
        "year_start": year_start,
        "year_end": year_end,
        "year_precision": year_precision,
        "source_grade": grade,
        "source_url": url,
    }


def run_fixture(directory: Path, addr_rows: list[tuple], candidates: list[dict], *, name: str = "fixture") -> dict:
    case = directory / name
    case.mkdir(exist_ok=True)
    database = case / "fixture.sqlite3"
    candidates_path = case / "candidates.jsonl"
    output = case / "out.jsonl"
    report = case / "report.md"
    make_database(database, addr_rows)
    make_candidates(candidates_path, candidates)
    result = backfill.backfill_coordinates(
        candidates_path, database, output=output, report=report
    )
    assert output.is_file() and report.is_file()
    return result


def test_direct_join_and_grades(directory: Path) -> None:
    result = run_fixture(
        directory,
        [
            (100, "洛陽", 960, 1126, 112.38263, 34.665276, 82840),
            (200, "并州", 979, 1058, 112.74468, 37.67847, None),
        ],
        [
            make_candidate("c1", addr_id=100, place="洛陽", year_start=1071, year_end=1071),
            make_candidate("c2", addr_id=200, place="并州", year_start=1054, year_end=1057, year_precision="approximate"),
        ],
        name="direct",
    )
    assert result["target_total"] == 2
    assert len(result["success"]) == 2 and not result["failures"]
    by_id = {record["candidate_id"]: record for record in result["success"]}
    assert by_id["c1"]["coordinate_grade"] == "A"
    assert by_id["c1"]["chgis_pt_id"] == 82840
    assert by_id["c1"]["lon"] == 112.38263 and by_id["c1"]["lat"] == 34.665276
    assert by_id["c1"]["event_year"] == 1071
    assert by_id["c2"]["coordinate_grade"] == "B"
    assert by_id["c2"]["chgis_pt_id"] is None
    assert by_id["c2"]["event_year"] == "1054-1057"
    assert by_id["c2"]["stable_link_key"] == backfill._stable_link_key(
        make_candidate("c2", addr_id=200, place="并州", year_start=1054, year_end=1057, year_precision="approximate")
    )


def test_missing_coords_and_zero_sentinel(directory: Path) -> None:
    result = run_fixture(
        directory,
        [
            (300, "劍南西川軍節度", 618, 907, None, None, None),
            (400, "溫國", 960, 1279, 0.0, 0.0, None),
        ],
        [
            make_candidate("d1", addr_id=300, place="劍南西川軍節度", poet="司空曙", year_start=785, year_end=785),
            make_candidate("d2", addr_id=400, place="溫國", poet="司马光", year_start=1086, year_end=1086),
        ],
        name="missing-zero",
    )
    assert not result["success"]
    reasons = {item["candidate_id"]: item["reason"] for item in result["failures"]}
    assert reasons["d1"] == backfill.DB_NULL_REASON
    assert reasons["d2"] == backfill.SENTINEL_REASON
    assert all(item["place"] in ("劍南西川軍節度", "溫國") for item in result["failures"])


def test_place_mismatch(directory: Path) -> None:
    result = run_fixture(
        directory,
        [(100, "洛陽", 960, 1126, 112.38263, 34.665276, 82840)],
        [make_candidate("m1", addr_id=100, place="長安", year_start=1071, year_end=1071)],
        name="place-mismatch",
    )
    assert not result["success"]
    assert result["failures"][0]["reason"] == "地名不匹配"


def test_year_intersection(directory: Path) -> None:
    result = run_fixture(
        directory,
        [
            (100, "洛陽", 960, 1126, 112.38263, 34.665276, 82840),
            (500, "開封", None, None, 114.34, 34.78, 44323),
            (600, "長安", 600, 618, 108.94, 34.26, 115470),
        ],
        [
            make_candidate("y1", addr_id=600, place="長安", year_start=700, year_end=700),
            make_candidate("y2", addr_id=500, place="開封", year_start=1058, year_end=1058),
            make_candidate("y3", addr_id=100, place="洛陽", year_start=1130, year_end=1200),
        ],
        name="year-intersect",
    )
    assert len(result["success"]) == 1
    assert result["success"][0]["candidate_id"] == "y2"
    reasons = {item["candidate_id"]: item["reason"] for item in result["failures"]}
    assert reasons["y1"] == "年份不相交"
    assert reasons["y3"] == "年份不相交"


def test_out_of_range_and_nonfinite_rejected(directory: Path) -> None:
    rows = [
        (700, "越東", 960, 1126, 200.0, 34.0, 1),
        (701, "越西", 960, 1126, 112.0, 95.0, 2),
        (702, "越極", 960, 1126, float("inf"), 34.0, 3),
    ]
    result = run_fixture(
        directory,
        rows,
        [
            make_candidate("o1", addr_id=700, place="越東", year_start=1000, year_end=1000),
            make_candidate("o2", addr_id=701, place="越西", year_start=1000, year_end=1000),
            make_candidate("o3", addr_id=702, place="越極", year_start=1000, year_end=1000),
        ],
        name="bounds",
    )
    assert not result["success"]
    reasons = {item["candidate_id"]: item["reason"] for item in result["failures"]}
    assert reasons["o1"] == "坐标越界/非有限"
    assert reasons["o2"] == "坐标越界/非有限"
    assert reasons["o3"] == backfill.DB_NULL_REASON


def test_duplicate_candidate_id_errors(directory: Path) -> None:
    database = directory / "dup.sqlite3"
    candidates_path = directory / "dup.jsonl"
    make_database(database, [(100, "洛陽", 960, 1126, 112.0, 34.0, 82840)])
    make_candidates(candidates_path, [
        make_candidate("same", addr_id=100, year_start=1071, year_end=1071),
        make_candidate("same", addr_id=100, year_start=1071, year_end=1071),
    ])
    try:
        backfill.backfill_coordinates(
            candidates_path, database,
            output=directory / "dup-out.jsonl", report=directory / "dup-report.md",
        )
    except backfill.BackfillError as error:
        assert "duplicate candidate_id" in str(error)
    else:
        raise AssertionError("duplicate candidate_id was accepted")


def test_association_conflict_errors(directory: Path) -> None:
    database = directory / "conflict.sqlite3"
    candidates_path = directory / "conflict.jsonl"
    make_database(database, [(100, "洛陽", 960, 1126, 112.0, 34.0, 82840)])
    make_candidates(candidates_path, [
        make_candidate("a1", addr_id=100, year_start=1071, year_end=1071),
        make_candidate("a2", addr_id=100, year_start=1071, year_end=1071),
    ])
    try:
        backfill.backfill_coordinates(
            candidates_path, database,
            output=directory / "conflict-out.jsonl", report=directory / "conflict-report.md",
        )
    except backfill.BackfillError as error:
        assert "conflicting association keys" in str(error)
    else:
        raise AssertionError("association conflict was accepted")


def test_readonly_and_inputs_unchanged(directory: Path) -> None:
    database = directory / "ro.sqlite3"
    candidates_path = directory / "ro.jsonl"
    output = directory / "ro-out.jsonl"
    make_database(database, [(100, "洛陽", 960, 1126, 112.0, 34.0, 82840)])
    make_candidates(candidates_path, [make_candidate("r1", addr_id=100, year_start=1071, year_end=1071)])
    db_before = database.read_bytes()
    cand_before = candidates_path.read_bytes()
    result = backfill.backfill_coordinates(
        candidates_path, database, output=output, report=directory / "ro-report.md"
    )
    assert database.read_bytes() == db_before
    assert candidates_path.read_bytes() == cand_before
    assert not list(directory.glob(f"{database.name}-*"))
    assert not backfill._paths_refer_to_same_file(database, output)
    assert not backfill._paths_refer_to_same_file(candidates_path, output)
    assert result["database_sha256"] == backfill.sha256_file(database)


def test_determinism(directory: Path) -> None:
    database = directory / "det.sqlite3"
    candidates_path = directory / "det.jsonl"
    rows = [
        (100, "洛陽", 960, 1126, 112.0, 34.0, 82840),
        (200, "并州", 979, 1058, 112.7, 37.6, None),
    ]
    make_database(database, rows)
    candidates = [
        make_candidate("z1", addr_id=100, year_start=1071, year_end=1071),
        make_candidate("z2", addr_id=200, place="并州", year_start=1054, year_end=1057, year_precision="approximate"),
    ]
    make_candidates(candidates_path, candidates)
    first_out = directory / "det1.jsonl"
    first_rep = directory / "det1.md"
    second_out = directory / "det2.jsonl"
    second_rep = directory / "det2.md"
    backfill.backfill_coordinates(candidates_path, database, output=first_out, report=first_rep)
    backfill.backfill_coordinates(candidates_path, database, output=second_out, report=second_rep)
    assert first_out.read_bytes() == second_out.read_bytes()
    assert first_rep.read_bytes() == second_rep.read_bytes()


def test_output_field_contract(directory: Path) -> None:
    result = run_fixture(
        directory,
        [(100, "洛陽", 960, 1126, 112.0, 34.0, 82840)],
        [make_candidate("f1", addr_id=100, year_start=1071, year_end=1071)],
        name="fields1",
    )
    record = result["success"][0]
    assert set(record) == set(backfill.OUTPUT_KEYS)
    assert isinstance(record["event_year"], int)
    assert isinstance(record["lon"], float) and isinstance(record["lat"], float)
    assert record["coordinate_source_table"] == backfill.COORDINATE_SOURCE_TABLE
    assert record["fact_grade"] == record["source_grade"]
    assert record["coordinate_grade"] in ("A", "B")
    assert backfill.NOTE in record["note"]
    assert record["coordinate_source_database"] in (
        backfill._database_reference(backfill.DEFAULT_DATABASE),
        str((directory / "fields1" / "fixture.sqlite3").resolve()).replace("\\", "/"),
    )
    assert backfill.sha256_file(directory / "fields1" / "fixture.sqlite3") == record["coordinate_source_database_sha256"]
    failure_fields = {"candidate_id", "poet", "year_start", "year_end", "place", "addr_id", "reason"}
    result2 = run_fixture(
        directory,
        [(100, "洛陽", 960, 1126, None, None, None)],
        [make_candidate("f2", addr_id=100, year_start=1071, year_end=1071)],
        name="fields2",
    )
    assert set(result2["failures"][0]) == failure_fields


def test_cli_refuses_input_alias_output(directory: Path) -> None:
    database = directory / "cli-source.sqlite3"
    make_database(database, [(100, "洛陽", 960, 1126, 112.0, 34.0, 82840)])
    result = run_cli("--database", database, "--output", database)
    assert result.returncode == 2, result.stderr
    assert "must not refer to" in result.stderr


def test_real_artifacts() -> None:
    if not backfill.DEFAULT_DATABASE.exists():
        print("integration explicitly skipped: CBDB database absent")
        return
    with tempfile.TemporaryDirectory(prefix="cbdb-coordinate-backfill-") as temporary:
        directory = Path(temporary)
        output = directory / "real-out.jsonl"
        report = directory / "real-report.md"
        candidates_before = backfill.DEFAULT_CANDIDATES.read_bytes()
        result = backfill.backfill_coordinates(
            backfill.DEFAULT_CANDIDATES, backfill.DEFAULT_DATABASE,
            output=output, report=report,
        )
        assert backfill.DEFAULT_CANDIDATES.read_bytes() == candidates_before
        assert not list(backfill.DEFAULT_DATABASE.parent.glob(f"{backfill.DEFAULT_DATABASE.name}-*"))

        assert result["target_total"] == 30
        assert len(result["success"]) == 19
        assert len(result["failures"]) == 11

        expected_success = Counter({"司空曙": 1, "卢纶": 3, "李益": 4, "司马光": 9, "欧阳炯": 1, "钱惟演": 1})
        expected_failure = Counter({"司空曙": 1, "李益": 2, "司马光": 5, "钱惟演": 3})
        assert Counter(item["poet"] for item in result["success"]) == expected_success
        assert Counter(item["poet"] for item in result["failures"]) == expected_failure

        sentinels = [item for item in result["failures"] if item["reason"] == backfill.SENTINEL_REASON]
        assert len(sentinels) == 1 and sentinels[0]["place"] == "溫國"
        assert sentinels[0]["addr_id"] == "25022"
        assert all(item["reason"] == backfill.DB_NULL_REASON for item in result["failures"] if item is not sentinels[0])

        grades = Counter(item["coordinate_grade"] for item in result["success"])
        assert grades == Counter({"A": 17, "B": 2})
        assert all(item["candidate_id"].isalnum() for item in result["success"])
        assert len({item["stable_link_key"] for item in result["success"]}) == 19

        regenerated_output = output.read_bytes()
        regenerated_report = report.read_bytes()
        assert backfill.DEFAULT_OUTPUT.read_bytes() == regenerated_output, (
            "data/candidates/cbdb_event_coordinate_supplements.jsonl is stale"
        )
        assert backfill.DEFAULT_REPORT.read_bytes() == regenerated_report, (
            "docs/cbdb-coordinate-backfill.md is stale"
        )

        loaded = [json.loads(line) for line in regenerated_output.decode("utf-8").splitlines() if line.strip()]
        assert len(loaded) == 19
        assert set(loaded[0]) == set(backfill.OUTPUT_KEYS)
        print("integration passed: targets=30, success=19, failures=11, A=17/B=2")


def test_invalid_addr_id_raises_backfill_error(directory: Path) -> None:
    database = directory / "bad-addr.sqlite3"
    candidates = directory / "bad-addr.jsonl"
    make_database(database, [(100, "洛陽", 960, 1126, 112.0, 34.0, 82840)])
    for raw in ("", "abc", None, 1.5):
        make_candidates(candidates, [make_candidate("ba1", addr_id=raw, year_start=1071, year_end=1071)])
        try:
            backfill.backfill_coordinates(candidates, database, output=directory / "bad-out.jsonl", report=directory / "bad-rep.md")
        except backfill.BackfillError as error:
            message = str(error)
            assert "invalid cbdb_addr_id" in message and "ba1" in message and "line 1" in message
        else:
            raise AssertionError(f"invalid cbdb_addr_id {raw!r} was accepted")


def test_invalid_year_fields_raise_backfill_error(directory: Path) -> None:
    database = directory / "bad-year.sqlite3"
    candidates = directory / "bad-year.jsonl"
    make_database(database, [(100, "洛陽", 960, 1126, 112.0, 34.0, 82840)])
    cases = [
        {"year_start": None, "year_end": 1071},
        {"year_start": 1071, "year_end": None},
        {"year_start": 1071, "year_end": "x"},
        {"year_start": 1072, "year_end": 1071},
    ]
    for index, overrides in enumerate(cases, 1):
        record = make_candidate(f"by{index}", addr_id=100, year_start=1071, year_end=1071)
        for key, value in overrides.items():
            if value is None:
                record.pop(key, None)
            else:
                record[key] = value
        make_candidates(candidates, [record])
        try:
            backfill.backfill_coordinates(candidates, database, output=directory / "by-out.jsonl", report=directory / "by-rep.md")
        except backfill.BackfillError as error:
            message = str(error)
            assert f"by{index}" in message and "line 1" in message
            assert "year_start" in message or "year_end" in message
        else:
            raise AssertionError(f"invalid years {overrides!r} were accepted")


def test_candidates_json_parse_error_has_path_and_line(directory: Path) -> None:
    database = directory / "parse.sqlite3"
    candidates = directory / "parse.jsonl"
    make_database(database, [(100, "洛陽", 960, 1126, 112.0, 34.0, 82840)])
    candidates.write_text('{"source": "cbdb"}\n{broken\n', encoding="utf-8")
    try:
        backfill.backfill_coordinates(candidates, database, output=directory / "parse-out.jsonl", report=directory / "parse-rep.md")
    except backfill.BackfillError as error:
        message = str(error)
        assert "malformed JSON" in message and str(candidates.resolve()) in message and "line 2" in message
    else:
        raise AssertionError("malformed candidates JSON was accepted")


def test_output_report_alias_rejected(directory: Path) -> None:
    database = directory / "or.sqlite3"
    candidates = directory / "or.jsonl"
    make_database(database, [(100, "洛陽", 960, 1126, 112.0, 34.0, 82840)])
    make_candidates(candidates, [make_candidate("or1", addr_id=100, year_start=1071, year_end=1071)])
    same = directory / "same-file"
    same.write_text("x", encoding="utf-8")
    hard_link = directory / "same-hard"
    os.link(same, hard_link)
    for output, report in ((same, same), (same, hard_link), (hard_link, same)):
        try:
            backfill.backfill_coordinates(candidates, database, output=output, report=report)
        except backfill.BackfillError as error:
            assert "same file" in str(error)
        else:
            raise AssertionError("output/report alias was accepted")


def test_candidates_hash_change_detected(directory: Path) -> None:
    database = directory / "cc-hash.sqlite3"
    candidates = directory / "cc-hash.jsonl"
    make_database(database, [(100, "洛陽", 960, 1126, 112.0, 34.0, 82840)])
    make_candidates(candidates, [make_candidate("ch1", addr_id=100, year_start=1071, year_end=1071)])
    original_hash = backfill.sha256_file
    calls: list[Path] = []

    def counted_hash(path: Path, chunk_size: int = 1024 * 1024) -> str:
        calls.append(path)
        digest = original_hash(path, chunk_size)
        if path.resolve() == candidates.resolve() and calls.count(path) == 2:
            return "0" * 64 if digest != "0" * 64 else "1" * 64
        return digest

    backfill.sha256_file = counted_hash
    try:
        try:
            backfill.backfill_coordinates(candidates, database, output=directory / "cc-hash-out.jsonl", report=directory / "cc-hash-rep.md")
        except backfill.BackfillError as error:
            assert "candidates file SHA-256 changed" in str(error)
        else:
            raise AssertionError("candidates SHA-256 drift was accepted")
    finally:
        backfill.sha256_file = original_hash


def test_candidates_stat_change_detected(directory: Path) -> None:
    database = directory / "cc-stat.sqlite3"
    candidates = directory / "cc-stat.jsonl"
    make_database(database, [(100, "洛陽", 960, 1126, 112.0, 34.0, 82840)])
    make_candidates(candidates, [make_candidate("cs1", addr_id=100, year_start=1071, year_end=1071)])
    original_stat = backfill._stat_fingerprint
    calls = 0
    stable = original_stat(candidates)

    def changed_stat(path: Path) -> tuple[int, int, int, int]:
        nonlocal calls
        if path.resolve() == candidates.resolve():
            calls += 1
            return stable if calls < 2 else (*stable[:3], stable[3] + 1)
        return original_stat(path)

    backfill._stat_fingerprint = changed_stat
    try:
        try:
            backfill.backfill_coordinates(candidates, database, output=directory / "cc-stat-out.jsonl", report=directory / "cc-stat-rep.md")
        except backfill.BackfillError as error:
            assert "candidates" in str(error) and "changed" in str(error)
        else:
            raise AssertionError("candidates stat drift was accepted")
    finally:
        backfill._stat_fingerprint = original_stat


def test_sidecar_and_wal_rejected(directory: Path) -> None:
    database = directory / "sc.sqlite3"
    candidates = directory / "sc.jsonl"
    make_database(database, [(100, "洛陽", 960, 1126, 112.0, 34.0, 82840)])
    make_candidates(candidates, [make_candidate("sc1", addr_id=100, year_start=1071, year_end=1071)])
    journal = Path(f"{database}-journal")
    journal.write_bytes(b"\xd9\xd5\x05\xf9\x20\xa1\x63\xd7" + b"\x00" * 8)
    try:
        try:
            backfill.backfill_coordinates(candidates, database, output=directory / "sc-out.jsonl", report=directory / "sc-rep.md")
        except backfill.BackfillError as error:
            assert "sidecar" in str(error) and "journal" in str(error)
        else:
            raise AssertionError("non-empty journal sidecar was accepted")
    finally:
        journal.unlink()

    wal_database = directory / "wal.sqlite3"
    make_database(wal_database, [(100, "洛陽", 960, 1126, 112.0, 34.0, 82840)])
    connection = sqlite3.connect(wal_database)
    try:
        assert connection.execute("PRAGMA journal_mode=WAL").fetchone()[0].casefold() == "wal"
        connection.execute("INSERT INTO ADDR_CODES VALUES (200, '并州', 979, 1058, 112.7, 37.6, NULL)")
        connection.commit()
    finally:
        connection.close()
    for suffix in backfill.SIDECAR_SUFFIXES:
        sidecar = Path(f"{wal_database}{suffix}")
        if sidecar.exists():
            sidecar.unlink()
    try:
        try:
            backfill.backfill_coordinates(candidates, wal_database, output=directory / "wal-out.jsonl", report=directory / "wal-rep.md")
        except backfill.BackfillError as error:
            assert "journal_mode" in str(error)
        else:
            raise AssertionError("WAL-mode database was accepted")
    finally:
        for suffix in backfill.SIDECAR_SUFFIXES:
            sidecar = Path(f"{wal_database}{suffix}")
            if sidecar.exists():
                sidecar.unlink()


def test_expected_sha256_mismatch_cli(directory: Path) -> None:
    database = directory / "sha-mismatch.sqlite3"
    candidates = directory / "sha-mismatch.jsonl"
    make_database(database, [(100, "洛陽", 960, 1126, 112.0, 34.0, 82840)])
    make_candidates(candidates, [make_candidate("sm1", addr_id=100, year_start=1071, year_end=1071)])
    output = directory / "sha-out.jsonl"
    report = directory / "sha-rep.md"
    before = database.read_bytes()
    result = run_cli("--database", database, "--candidates", candidates, "--output", output, "--report", report, "--expected-sha256", "0" * 64)
    assert result.returncode == 2, result.stderr
    assert "SHA-256 mismatch" in result.stderr
    assert not output.exists() and not report.exists()
    assert database.read_bytes() == before


def test_cli_no_report(directory: Path) -> None:
    database = directory / "no-rep.sqlite3"
    candidates = directory / "no-rep.jsonl"
    make_database(database, [(100, "洛陽", 960, 1126, 112.0, 34.0, 82840)])
    make_candidates(candidates, [make_candidate("nr1", addr_id=100, year_start=1071, year_end=1071)])
    output = directory / "no-rep-out.jsonl"
    report = directory / "no-rep.md"
    before_db = database.read_bytes()
    result = run_cli("--database", database, "--candidates", candidates, "--output", output, "--report", report, "--no-report")
    assert result.returncode == 0, result.stderr
    assert output.is_file()
    assert not report.exists()
    assert database.read_bytes() == before_db
    summary = json.loads(result.stdout)
    assert summary["success"] == 1 and summary["failures"] == 0


def test_cli_data_and_invalid_input_exit_2(directory: Path) -> None:
    database = directory / "cli-err.sqlite3"
    make_database(database, [(100, "洛陽", 960, 1126, 112.0, 34.0, 82840)])

    dup_candidates = directory / "cli-dup.jsonl"
    make_candidates(dup_candidates, [
        make_candidate("dup", addr_id=100, year_start=1071, year_end=1071),
        make_candidate("dup", addr_id=100, year_start=1071, year_end=1071),
    ])
    result = run_cli("--database", database, "--candidates", dup_candidates, "--output", directory / "dup-out.jsonl", "--no-report")
    assert result.returncode == 2, result.stderr
    assert "duplicate candidate_id" in result.stderr
    assert "Traceback" not in result.stderr

    bad_candidates = directory / "cli-badaddr.jsonl"
    make_candidates(bad_candidates, [make_candidate("bad1", addr_id="abc", year_start=1071, year_end=1071)])
    result = run_cli("--database", database, "--candidates", bad_candidates, "--output", directory / "bad-out.jsonl", "--no-report")
    assert result.returncode == 2, result.stderr
    assert "invalid cbdb_addr_id" in result.stderr and "bad1" in result.stderr
    assert "Traceback" not in result.stderr


def test_cli_rejects_hardlink_and_symlink_aliases(directory: Path) -> None:
    database = directory / "cli-link.sqlite3"
    candidates = directory / "cli-link.jsonl"
    make_database(database, [(100, "洛陽", 960, 1126, 112.0, 34.0, 82840)])
    make_candidates(candidates, [make_candidate("lk1", addr_id=100, year_start=1071, year_end=1071)])
    before = database.read_bytes()

    hard_link = directory / "database-hard.sqlite3"
    os.link(database, hard_link)
    result = run_cli("--database", database, "--candidates", candidates, "--output", hard_link, "--no-report")
    assert result.returncode == 2, result.stderr
    assert "must not refer" in result.stderr
    assert database.read_bytes() == before

    report = directory / "report-hard.md"
    report.write_text("x", encoding="utf-8")
    output_link = directory / "out-hard.jsonl"
    os.link(report, output_link)
    result = run_cli("--database", database, "--candidates", candidates, "--output", output_link, "--report", report)
    assert result.returncode == 2, result.stderr
    assert "same file" in result.stderr

    symbolic_link = directory / "database-symbolic.sqlite3"
    try:
        symbolic_link.symlink_to(database)
    except OSError:
        print("symlink alias case skipped: symlink creation unavailable")
    else:
        result = run_cli("--database", database, "--candidates", candidates, "--output", symbolic_link, "--no-report")
        assert result.returncode == 2, result.stderr
        assert "must not refer" in result.stderr
        assert database.read_bytes() == before


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="cbdb-coordinate-backfill-check-") as temporary:
        directory = Path(temporary)
        test_direct_join_and_grades(directory)
        test_missing_coords_and_zero_sentinel(directory)
        test_place_mismatch(directory)
        test_year_intersection(directory)
        test_out_of_range_and_nonfinite_rejected(directory)
        test_duplicate_candidate_id_errors(directory)
        test_association_conflict_errors(directory)
        test_readonly_and_inputs_unchanged(directory)
        test_determinism(directory)
        test_output_field_contract(directory)
        test_cli_refuses_input_alias_output(directory)
        test_invalid_addr_id_raises_backfill_error(directory)
        test_invalid_year_fields_raise_backfill_error(directory)
        test_candidates_json_parse_error_has_path_and_line(directory)
        test_output_report_alias_rejected(directory)
        test_candidates_hash_change_detected(directory)
        test_candidates_stat_change_detected(directory)
        test_sidecar_and_wal_rejected(directory)
        test_expected_sha256_mismatch_cli(directory)
        test_cli_no_report(directory)
        test_cli_data_and_invalid_input_exit_2(directory)
        test_cli_rejects_hardlink_and_symlink_aliases(directory)
    test_real_artifacts()
    print("cbdb_coordinate_backfill checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
