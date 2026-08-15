#!/usr/bin/env python3
"""Validate and build deterministic, evidence-gated poem expansions.

The command-line interface is check-only unless ``--write`` is supplied.  It
never chooses an output location implicitly; both input and output paths are
provided by the caller.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import os
import tempfile
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import urlsplit


SCHEMA_VERSION = 1
METHOD = "verified_fact_expansion_v1"
ALLOWED_PRECISIONS = frozenset({"exact", "year", "approximate", "range"})
ALLOWED_GRADES = frozenset({"A", "B", "C", "D"})
ALLOWED_SUPPORTS = frozenset(
    {"composition_date", "composition_place", "life_event", "historical_context"}
)
AB_GRADES = frozenset({"A", "B"})


class FactPackageError(ValueError):
    """Raised when an input fact package fails the publication gate."""


def _fail(message: str) -> None:
    raise FactPackageError(message)


def _require_mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail(f"{field} must be an object")
    return value


def _require_list(value: Any, field: str) -> list[Any]:
    if not isinstance(value, list):
        _fail(f"{field} must be a list")
    return value


def _required(mapping: Mapping[str, Any], field: str, parent: str) -> Any:
    if field not in mapping:
        _fail(f"{parent}.{field} is required")
    return mapping[field]


def _nonempty_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail(f"{field} must be a non-empty string")
    return value


def _canonical_family(value: str) -> str:
    """Collapse known aliases while treating cosmetic spelling alike."""

    raw = value.strip().casefold()
    if "://" in raw:
        raw = (urlsplit(raw).hostname or raw).casefold()
    if raw.startswith("www."):
        raw = raw[4:]
    compact = "".join(character for character in raw if character.isalnum())

    known = {
        "cnkgraph": "cnkgraph",
        "opencnkgraph": "cnkgraph",
        "cnkgraphorg": "cnkgraph",
        "opencnkgraphorg": "cnkgraph",
        "cnkgraphcom": "cnkgraph",
        "opencnkgraphcom": "cnkgraph",
        "gushiwen": "gushiwen",
        "sogushiwen": "gushiwen",
        "gushiwencn": "gushiwen",
        "sogushiwencn": "gushiwen",
        "guwendao": "gushiwen",
        "guwendaonet": "gushiwen",
        "souyun": "souyun",
        "apisouyun": "souyun",
        "souyuncn": "souyun",
        "apisouyuncn": "souyun",
    }
    return known.get(compact, compact)


def _poem_author(poem: Mapping[str, Any]) -> Any:
    return poem.get("poet", poem.get("author"))


def _validate_poem_key(
    package: Mapping[str, Any], poems: Sequence[Mapping[str, Any]]
) -> Mapping[str, Any]:
    poem_key = _require_mapping(_required(package, "poem_key", "package"), "poem_key")
    for field in ("poet", "title", "dynasty", "body_hash"):
        _nonempty_string(_required(poem_key, field, "poem_key"), f"poem_key.{field}")

    body_hash = poem_key["body_hash"]
    matches = [poem for poem in poems if poem.get("body_hash") == body_hash]
    if len(matches) != 1:
        _fail(f"poem_key.body_hash must match exactly one poem; matched {len(matches)}")

    matched = matches[0]
    actual_identity = {
        "poet": _poem_author(matched),
        "title": matched.get("title"),
        "dynasty": matched.get("dynasty"),
    }
    for field, actual_value in actual_identity.items():
        if poem_key[field] != actual_value:
            _fail(f"poem_key.{field} does not exactly match poems.json")
    return poem_key


def _validate_chronology(package: Mapping[str, Any]) -> Mapping[str, Any]:
    chronology = _require_mapping(
        _required(package, "chronology", "package"), "chronology"
    )
    year_start = _required(chronology, "year_start", "chronology")
    year_end = _required(chronology, "year_end", "chronology")
    if (
        not isinstance(year_start, int)
        or isinstance(year_start, bool)
        or not isinstance(year_end, int)
        or isinstance(year_end, bool)
    ):
        _fail("chronology.year_start and chronology.year_end must be integers")
    if year_start > year_end:
        _fail("chronology.year_start must not exceed chronology.year_end")

    precision = _required(chronology, "year_precision", "chronology")
    if not isinstance(precision, str) or precision not in ALLOWED_PRECISIONS:
        _fail(
            "chronology.year_precision must be exact, year, approximate, or range"
        )

    for field in ("historical_place", "modern_place", "province"):
        _nonempty_string(
            _required(chronology, field, "chronology"), f"chronology.{field}"
        )

    def coordinate_present(field: str) -> bool:
        if field not in chronology or chronology[field] is None:
            return False
        return not (isinstance(chronology[field], str) and not chronology[field].strip())

    lon_present = coordinate_present("lon")
    lat_present = coordinate_present("lat")
    if lon_present != lat_present:
        _fail("chronology.lon and chronology.lat must be present as a pair")
    if lon_present:
        lon = chronology["lon"]
        lat = chronology["lat"]
        for value, field in ((lon, "lon"), (lat, "lat")):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                _fail(f"chronology.{field} must be a finite number")
            if not math.isfinite(value):
                _fail(f"chronology.{field} must be a finite number")
        if not -180 <= lon <= 180:
            _fail("chronology.lon must be in [-180, 180]")
        if not -90 <= lat <= 90:
            _fail("chronology.lat must be in [-90, 90]")
    return chronology


def _valid_http_url(value: Any) -> bool:
    if not isinstance(value, str) or not value or value != value.strip():
        return False
    parsed = urlsplit(value)
    return parsed.scheme.casefold() in {"http", "https"} and bool(parsed.netloc)


def _validate_evidence(package: Mapping[str, Any]) -> tuple[list[Any], str]:
    evidence = _require_list(_required(package, "evidence", "package"), "evidence")
    evidence_ids: set[str] = set()
    source_families: set[str] = set()
    claim_families = {
        "composition_date": set(),
        "composition_place": set(),
    }

    for index, raw_item in enumerate(evidence):
        field = f"evidence[{index}]"
        item = _require_mapping(raw_item, field)
        evidence_id = _nonempty_string(
            _required(item, "evidence_id", field), f"{field}.evidence_id"
        )
        if evidence_id in evidence_ids:
            _fail(f"{field}.evidence_id must be unique")
        evidence_ids.add(evidence_id)

        family = _nonempty_string(
            _required(item, "source_family", field), f"{field}.source_family"
        )
        canonical_family = _canonical_family(family)
        if not canonical_family:
            _fail(f"{field}.source_family must identify a source family")
        source_families.add(canonical_family)
        _nonempty_string(
            _required(item, "source_name", field), f"{field}.source_name"
        )

        source_url = _required(item, "source_url", field)
        if not _valid_http_url(source_url):
            _fail(f"{field}.source_url must be an http(s) URL")

        grade = _required(item, "source_grade", field)
        if not isinstance(grade, str) or grade not in ALLOWED_GRADES:
            _fail(f"{field}.source_grade must be one of A, B, C, D")

        supports = _require_list(_required(item, "supports", field), f"{field}.supports")
        if any(not isinstance(claim, str) or claim not in ALLOWED_SUPPORTS for claim in supports):
            _fail(f"{field}.supports contains an unsupported claim")
        if len(supports) != len(set(supports)):
            _fail(f"{field}.supports must not contain duplicates")
        if grade in AB_GRADES:
            for claim in claim_families:
                if claim in supports:
                    claim_families[claim].add(canonical_family)

        excerpt = _required(item, "excerpt", field)
        _nonempty_string(excerpt, f"{field}.excerpt")
        if len(excerpt) > 160:
            _fail(f"{field}.excerpt must be at most 160 characters")

    if len(source_families) < 2:
        _fail("evidence must contain at least two independent source_family values")
    for claim in ("composition_date", "composition_place"):
        if not claim_families[claim]:
            _fail(f"{claim} requires at least one A/B source")

    if all(len(claim_families[claim]) >= 2 for claim in claim_families):
        verdict = "strongly_corroborated"
    else:
        verdict = "corroborated"
    return evidence, verdict


def _validate_context_facts(
    package: Mapping[str, Any], evidence: Sequence[Mapping[str, Any]]
) -> list[Any]:
    facts = _require_list(
        _required(package, "context_facts", "package"), "context_facts"
    )
    known_evidence_ids = {item["evidence_id"] for item in evidence}
    fact_ids: set[str] = set()
    for index, raw_fact in enumerate(facts):
        field = f"context_facts[{index}]"
        fact = _require_mapping(raw_fact, field)
        fact_id = _nonempty_string(
            _required(fact, "fact_id", field), f"{field}.fact_id"
        )
        if fact_id in fact_ids:
            _fail(f"{field}.fact_id must be unique")
        fact_ids.add(fact_id)

        fact_text = _required(fact, "text", field)
        _nonempty_string(fact_text, f"{field}.text")
        if len(fact_text) > 180:
            _fail(f"{field}.text must be at most 180 characters")

        references = _require_list(
            _required(fact, "evidence_ids", field), f"{field}.evidence_ids"
        )
        if not references:
            _fail(f"{field} must cite at least one evidence_id")
        if any(not isinstance(reference, str) or not reference for reference in references):
            _fail(f"{field}.evidence_ids must contain non-empty strings")
        if len(references) != len(set(references)):
            _fail(f"{field}.evidence_ids must not contain duplicates")
        missing = [reference for reference in references if reference not in known_evidence_ids]
        if missing:
            _fail(f"{field}.evidence_id does not exist: {missing[0]}")
    return facts


def _validate_verification(package: Mapping[str, Any]) -> Mapping[str, Any]:
    verification = _require_mapping(
        _required(package, "verification", "package"), "verification"
    )
    status = _required(verification, "status", "verification")
    if not isinstance(status, str) or status not in {"verified", "hold"}:
        _fail("verification.status must be verified or hold")

    reviewer = _required(verification, "reviewer", "verification")
    reviewed_at = _required(verification, "reviewed_at", "verification")
    controversy_note = _required(
        verification, "controversy_note", "verification"
    )
    if not isinstance(reviewer, str):
        _fail("verification.reviewer must be a string")
    if not isinstance(reviewed_at, str):
        _fail("verification.reviewed_at must be a string")
    if not isinstance(controversy_note, str):
        _fail("verification.controversy_note must be a string")
    if status == "verified":
        if not reviewer.strip():
            _fail("verification.reviewer is required for verified packages")
        if not reviewed_at.strip():
            _fail("verification.reviewed_at is required for verified packages")
        if controversy_note != "":
            _fail("verification.controversy_note must be empty for verified packages")
    return verification


def _year_label(chronology: Mapping[str, Any]) -> str:
    year_start = chronology["year_start"]
    year_end = chronology["year_end"]
    return str(year_start) if year_start == year_end else f"{year_start}—{year_end}"


def _modern_place_label(chronology: Mapping[str, Any]) -> str:
    province = chronology["province"]
    modern_place = chronology["modern_place"]
    return modern_place if province in modern_place else f"{province}{modern_place}"


def _fact_summary(
    poem_key: Mapping[str, Any], chronology: Mapping[str, Any]
) -> str:
    return (
        f'据已核来源，《{poem_key["title"]}》'
        f"{'约系于' if chronology['year_precision'] == 'approximate' else '系于'}"
        f"{_year_label(chronology)}，"
        f'创作地点记为{chronology["historical_place"]}；'
        f"今地对应{_modern_place_label(chronology)}。"
    )


def validate_fact_package(
    package: Mapping[str, Any], poems: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    """Validate one package without mutating it or performing file I/O.

    The returned dictionary contains the derived verdict and deterministic text
    so callers can inspect the gate result without building an output record.
    """

    package = _require_mapping(package, "package")
    if isinstance(poems, (str, bytes)) or not isinstance(poems, Sequence):
        _fail("poems must be a sequence of poem objects")
    for index, poem in enumerate(poems):
        if not isinstance(poem, Mapping):
            _fail(f"poems[{index}] must be an object")

    poem_key = _validate_poem_key(package, poems)
    chronology = _validate_chronology(package)
    evidence, verdict = _validate_evidence(package)
    facts = _validate_context_facts(package, evidence)
    verification = _validate_verification(package)

    summary = _fact_summary(poem_key, chronology)
    expansion_text = summary + "".join(fact["text"] for fact in facts)
    if len(expansion_text) > 600:
        _fail("expansion_text must be at most 600 characters")

    return {
        "status": verification["status"],
        "fact_verdict": verdict,
        "fact_summary": summary,
        "expansion_text": expansion_text,
    }


def build_expansion_record(
    package: Mapping[str, Any], poems: Sequence[Mapping[str, Any]]
) -> dict[str, Any] | None:
    """Build one publication record, or return ``None`` for a valid hold."""

    validated = validate_fact_package(package, poems)
    if validated["status"] == "hold":
        return None
    return {
        "schema_version": SCHEMA_VERSION,
        "poem_key": copy.deepcopy(package["poem_key"]),
        "composition": copy.deepcopy(package["chronology"]),
        "context_facts": copy.deepcopy(package["context_facts"]),
        "sources": copy.deepcopy(package["evidence"]),
        "verification": copy.deepcopy(package["verification"]),
        "fact_verdict": validated["fact_verdict"],
        "fact_summary": validated["fact_summary"],
        "expansion_text": validated["expansion_text"],
        "method": METHOD,
    }


def _load_poems(path: str | os.PathLike[str]) -> list[Mapping[str, Any]]:
    poems_path = Path(path)
    try:
        data = json.loads(poems_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FactPackageError(f"failed to read poems JSON {poems_path}: {exc}") from exc
    if isinstance(data, Mapping) and isinstance(data.get("poems"), list):
        data = data["poems"]
    if not isinstance(data, list):
        _fail("poems JSON must contain a list")
    if any(not isinstance(poem, Mapping) for poem in data):
        _fail("poems JSON entries must be objects")
    return data


def _load_jsonl(path: str | os.PathLike[str]) -> list[Mapping[str, Any]]:
    input_path = Path(path)
    rows: list[Mapping[str, Any]] = []
    try:
        with input_path.open("r", encoding="utf-8") as source:
            for line_number, line in enumerate(source, start=1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise FactPackageError(
                        f"invalid JSON on line {line_number} of {input_path}: {exc.msg}"
                    ) from exc
                if not isinstance(row, Mapping):
                    _fail(f"line {line_number} of {input_path} must be a JSON object")
                rows.append(row)
    except (OSError, UnicodeError) as exc:
        raise FactPackageError(f"failed to read JSONL {input_path}: {exc}") from exc
    return rows


def _stable_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _record_sort_key(record: Mapping[str, Any]) -> tuple[str, str, str, str, str]:
    poem_key = record["poem_key"]
    return (
        poem_key["poet"],
        poem_key["title"],
        poem_key["dynasty"],
        poem_key["body_hash"],
        _stable_json(record),
    )


def _build_records(
    packages: Iterable[Mapping[str, Any]], poems: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    records = []
    for line_number, package in enumerate(packages, start=1):
        try:
            record = build_expansion_record(package, poems)
        except FactPackageError as exc:
            raise FactPackageError(f"input line {line_number}: {exc}") from exc
        if record is not None:
            records.append(record)
    records.sort(key=_record_sort_key)
    return records


def _serialize_records(records: Iterable[Mapping[str, Any]]) -> str:
    return "".join(_stable_json(record) + "\n" for record in records)


def build_file(
    input_jsonl: str | os.PathLike[str],
    output_jsonl: str | os.PathLike[str],
    poems_json: str | os.PathLike[str],
) -> int:
    """Validate input and atomically replace output with sorted verified rows."""

    poems = _load_poems(poems_json)
    packages = _load_jsonl(input_jsonl)
    try:
        records = _build_records(packages, poems)
        serialized = _serialize_records(records)
    except (TypeError, ValueError) as exc:
        if isinstance(exc, FactPackageError):
            raise
        raise FactPackageError(f"output record is not valid JSON: {exc}") from exc

    output_path = Path(output_jsonl)
    if not output_path.parent.exists():
        _fail(f"output directory does not exist: {output_path.parent}")

    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=output_path.parent,
            prefix=f".{output_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(serialized)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, output_path)
    except (OSError, UnicodeError) as exc:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
        raise FactPackageError(f"failed to write output JSONL {output_path}: {exc}") from exc
    return len(records)


def check_file(
    input_jsonl: str | os.PathLike[str], poems_json: str | os.PathLike[str]
) -> dict[str, int]:
    """Read and validate all rows without writing an output file."""

    poems = _load_poems(poems_json)
    packages = _load_jsonl(input_jsonl)
    verified = 0
    hold = 0
    for line_number, package in enumerate(packages, start=1):
        try:
            result = validate_fact_package(package, poems)
        except FactPackageError as exc:
            raise FactPackageError(f"input line {line_number}: {exc}") from exc
        if result["status"] == "verified":
            verified += 1
        else:
            hold += 1
    return {"rows": len(packages), "verified": verified, "hold": hold}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate poem fact packages; write only when --write is supplied."
    )
    parser.add_argument("--input", required=True, help="input fact-package JSONL")
    parser.add_argument("--output", help="output expansion JSONL (used with --write)")
    parser.add_argument(
        "--poems",
        default=str(Path(__file__).resolve().parents[1] / "data" / "poems.json"),
        help="poems.json used for exact poem identity checks",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="atomically write verified records to --output",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if args.write:
            if not args.output:
                parser.error("--output is required with --write")
            count = build_file(args.input, args.output, args.poems)
            result: dict[str, Any] = {
                "mode": "write",
                "output": str(Path(args.output)),
                "written": count,
            }
        else:
            counts = check_file(args.input, args.poems)
            result = {"mode": "check", **counts}
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except FactPackageError as exc:
        parser.exit(1, f"validation failed: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
