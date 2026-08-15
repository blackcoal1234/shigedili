#!/usr/bin/env python3
"""Merge the reviewed 60-poem baseline with parallel 88-poet audit shards.

The shard directory is a candidate layer.  This builder revalidates every
verified package, checks every assigned poet has an explicit verified/hold
status, and then atomically writes three deterministic reviewed artifacts.
An incomplete audit is published honestly as partial coverage; it is never
labelled as an 88-poet complete release.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import parse_qs, urlsplit

from poem_fact_expansion import (
    FactPackageError,
    build_expansion_record,
    validate_fact_package,
)


ROOT = Path(__file__).resolve().parent.parent
POEMS = ROOT / "data" / "poems.json"
REVIEWED = ROOT / "data" / "reviewed"
SHARDS = ROOT / "data" / "candidates" / "fact_audit_shards"
BASELINE_PACKAGES = REVIEWED / "verified_poem_fact_packages.jsonl"
PACKAGES = REVIEWED / "verified_all_poet_fact_packages.jsonl"
EXPANSIONS = REVIEWED / "verified_all_poet_fact_expansions.jsonl"
SUMMARY = REVIEWED / "verified_all_poet_fact_release_summary.json"

SHARD_REVIEWER = "codex_parallel_fact_audit_2026-08-13"
SHARD_REVIEWED_AT = "2026-08-13T00:30:00+08:00"
CHINESE_RE = re.compile(r"[\u3400-\u9fff]")
CNKGRAPH_WRITING_RE = re.compile(r"^/api/[Ww]riting/\d+(?:/[Mm]ap[Ii]nfo)?/?$")

BATCHES: dict[str, tuple[str, ...]] = {
    "01": ("苏辙", "梅尧臣", "岑参", "元稹", "曾巩", "韩愈", "刘禹锡", "刘克庄", "张九龄", "高适", "黄庭坚"),
    "02": ("孟郊", "李贺", "李商隐", "吕本中", "柳宗元", "陈与义", "范仲淹", "罗隐", "许浑", "张籍", "宋之问"),
    "03": ("王维", "孟浩然", "皮日休", "王昌龄", "杜牧", "陈子昂", "朱熹", "王安石", "沈佺期", "辛弃疾", "欧阳修"),
    "04": ("范成大", "杨亿", "张元干", "韦庄", "贾岛", "骆宾王", "姜夔", "王建", "张孝祥", "苏洵", "叶梦得"),
    "05": ("杨万里", "文天祥", "王勃", "温庭筠", "贺铸", "秦观", "程颢", "韦应物", "杜荀鹤", "张先", "周邦彦"),
    "06": ("钱起", "陈亮", "吴文英", "尤袤", "林逋", "李煜", "柳永", "张炎", "王之涣", "陆九渊"),
    "07": ("上官仪", "卢纶", "司空曙", "司马光", "常建", "张志和", "张继", "晏几道", "晏殊"),
    "08": ("朱淑真", "李益", "欧阳炯", "石延年", "祖咏", "聂夷中", "贺知章", "钱惟演"),
}


def stable_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FactPackageError(f"failed to parse JSON {path}: {exc}") from exc


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as source:
            for line_number, line in enumerate(source, start=1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise FactPackageError(
                        f"invalid JSON on line {line_number} of {path}: {exc.msg}"
                    ) from exc
                if not isinstance(row, dict):
                    raise FactPackageError(
                        f"line {line_number} of {path} must be a JSON object"
                    )
                rows.append(row)
    except (OSError, UnicodeError) as exc:
        raise FactPackageError(f"failed to read JSONL {path}: {exc}") from exc
    return rows


def _walk_strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for key, item in value.items():
            yield from _walk_strings(key)
            yield from _walk_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_strings(item)


def reject_encoding_damage(value: Any, label: str) -> None:
    for text in _walk_strings(value):
        if "\ufffd" in text or "??" in text or _question_mark_damage(text):
            raise FactPackageError(f"{label} contains encoding-damaged text")


def _question_mark_damage(text: str) -> bool:
    """Detect replacement-like question marks while allowing URL queries."""
    if "?" not in text:
        return False
    if text.startswith(("http://", "https://")):
        return False
    return text.count("?") >= 2


def validate_shard_semantics(package: Mapping[str, Any], batch_id: str) -> None:
    """Apply publication rules that are stricter than the generic schema gate."""
    reject_encoding_damage(package, f"batch {batch_id} verified package")
    if "composition" in package or "sources" in package:
        raise FactPackageError(
            f"batch {batch_id} verified file contains an expansion record, not a fact package"
        )
    evidence_by_id = {
        evidence.get("evidence_id"): evidence
        for evidence in package.get("evidence", [])
        if isinstance(evidence, Mapping)
    }
    for fact in package.get("context_facts", []):
        text = fact.get("text", "") if isinstance(fact, Mapping) else ""
        if not isinstance(text, str) or not CHINESE_RE.search(text):
            raise FactPackageError(f"batch {batch_id} context facts must be written in Chinese")
        referenced = [evidence_by_id.get(evidence_id) for evidence_id in fact.get("evidence_ids", [])]
        supported_context = any(
            isinstance(evidence, Mapping)
            and set(evidence.get("supports", [])) & {"historical_context", "life_event"}
            for evidence in referenced
        )
        metadata_restatement = (
            "AuthorDate" in text
            and "AuthorPlace" in text
            and any(
                isinstance(evidence, Mapping)
                and {"composition_date", "composition_place"}
                <= set(evidence.get("supports", []))
                for evidence in referenced
            )
        )
        if not supported_context and not metadata_restatement:
            raise FactPackageError(
                f"batch {batch_id} context fact lacks historical_context/life_event support"
            )

    date_excerpts: list[str] = []
    place_excerpts: list[str] = []
    for evidence in package.get("evidence", []):
        if not isinstance(evidence, Mapping):
            continue
        excerpt = evidence.get("excerpt", "")
        if not isinstance(excerpt, str) or not CHINESE_RE.search(excerpt):
            raise FactPackageError(f"batch {batch_id} evidence excerpts must contain Chinese source text")
        supports = set(evidence.get("supports", []))
        if not supports and evidence.get("source_grade") in {"A", "B"}:
            raise FactPackageError(
                f"batch {batch_id} identity-only evidence must be graded C or D"
            )
        if evidence.get("source_grade") in {"A", "B"}:
            if "composition_date" in supports:
                date_excerpts.append(excerpt)
            if "composition_place" in supports:
                place_excerpts.append(excerpt)
        if not supports & {"composition_date", "composition_place"}:
            continue
        parsed = urlsplit(str(evidence.get("source_url", "")))
        host = (parsed.hostname or "").casefold()
        path = parsed.path
        query = parse_qs(parsed.query)
        path_folded = path.casefold()
        if any(marker in path_folded for marker in ("/search", "/author/", "/authors/", "/login")):
            raise FactPackageError(f"batch {batch_id} chronology evidence uses a non-direct page")
        if "cnkgraph" in host and not CNKGRAPH_WRITING_RE.fullmatch(path):
            raise FactPackageError(
                f"batch {batch_id} CNKGraph chronology evidence must use Writing/{{id}} or MapInfo"
            )
        if "gushiwen" in host and "shiwenv_" not in path_folded:
            raise FactPackageError(f"batch {batch_id} Gushiwen chronology evidence must be a work detail page")
        if "sou-yun" in host or "souyun" in host:
            if path_folded.endswith("/poemgeo.aspx") or path_folded.endswith("/poembooknav.aspx"):
                raise FactPackageError(f"batch {batch_id} Souyun aggregate page cannot support chronology")
            key_values = query.get("key", [])
            has_direct_key = len(key_values) == 1 and key_values[0].isdigit()
            has_direct_id = (
                bool(query.get("id"))
                or has_direct_key
                or "work_id" in excerpt.casefold()
                or "作品id" in excerpt
            )
            if not has_direct_id:
                raise FactPackageError(f"batch {batch_id} Souyun chronology evidence lacks a direct work id")

    chronology = package.get("chronology", {})
    date_text = " ".join(date_excerpts)
    for year_field in ("year_start", "year_end"):
        year = chronology.get(year_field)
        if str(year) not in date_text:
            raise FactPackageError(
                f"batch {batch_id} {year_field} is not visible in A/B evidence excerpts"
            )
    place_text = " ".join(place_excerpts)
    place_labels = [
        chronology.get("historical_place"),
        chronology.get("modern_place"),
        chronology.get("province"),
    ]
    def place_visible(label: Any) -> bool:
        if not isinstance(label, str) or not label.strip():
            return False
        label = label.strip()
        if label in place_text:
            return True
        parts = [part for part in re.split(r"[省市县区州府郡镇乡村山寺亭楼阁台园]+", label) if len(part) >= 2]
        return any(part in place_text for part in parts)

    if not any(place_visible(label) for label in place_labels):
        raise FactPackageError(
            f"batch {batch_id} chronology place is not visible in A/B evidence excerpts"
        )


def _poet_order(poems: list[dict[str, Any]]) -> list[str]:
    order: list[str] = []
    seen: set[str] = set()
    for poem in poems:
        poet = poem.get("poet", poem.get("author"))
        if isinstance(poet, str) and poet not in seen:
            seen.add(poet)
            order.append(poet)
    return order


def _identity(package: Mapping[str, Any]) -> tuple[str, str, str]:
    key = package["poem_key"]
    return key["poet"], key["title"], key["body_hash"]


def _sort_packages(rows: Iterable[dict[str, Any]], poet_rank: Mapping[str, int]) -> list[dict[str, Any]]:
    return sorted(
        rows,
        key=lambda row: (
            poet_rank[row["poem_key"]["poet"]],
            row["poem_key"]["title"],
            row["poem_key"]["body_hash"],
            stable_json(row),
        ),
    )


def validate_status(
    batch_id: str,
    value: Any,
    verified_packages: list[dict[str, Any]],
    poems: Iterable[Mapping[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    if not isinstance(value, dict):
        raise FactPackageError(f"batch {batch_id} status must be an object")
    reject_encoding_damage(value, f"batch {batch_id} status")
    if value.get("schema_version") != 1 or value.get("batch_id") != batch_id:
        raise FactPackageError(f"batch {batch_id} status metadata mismatch")
    expected = list(BATCHES[batch_id])
    if value.get("assigned_poets") != expected:
        raise FactPackageError(f"batch {batch_id} assigned_poets mismatch")
    results = value.get("results")
    if not isinstance(results, list) or len(results) != len(expected):
        raise FactPackageError(f"batch {batch_id} results must cover every assigned poet")
    if [row.get("poet") for row in results if isinstance(row, dict)] != expected:
        raise FactPackageError(f"batch {batch_id} result order/coverage mismatch")

    packages_by_poet: dict[str, list[dict[str, Any]]] = {}
    for package in verified_packages:
        packages_by_poet.setdefault(package["poem_key"]["poet"], []).append(package)
    unexpected = sorted(set(packages_by_poet) - set(expected))
    if unexpected:
        raise FactPackageError(f"batch {batch_id} contains unassigned poet {unexpected[0]}")

    held_back: list[dict[str, Any]] = []
    counts = Counter()
    poem_identities = None
    if poems is not None:
        poem_identities = {
            (
                poem.get("poet", poem.get("author")),
                poem.get("title"),
                poem.get("body_hash"),
            )
            for poem in poems
        }
    for poet, row in zip(expected, results):
        if not isinstance(row, dict):
            raise FactPackageError(f"batch {batch_id} result for {poet} must be an object")
        required = {"poet", "status", "title", "body_hash", "reason", "sources"}
        if not required <= set(row):
            raise FactPackageError(f"batch {batch_id} result for {poet} lacks required fields")
        status = row["status"]
        if status not in {"verified", "hold"}:
            raise FactPackageError(f"batch {batch_id} result for {poet} has invalid status")
        if not isinstance(row["sources"], list):
            raise FactPackageError(f"batch {batch_id} result sources for {poet} must be a list")
        if not isinstance(row["reason"], str) or not row["reason"].strip():
            raise FactPackageError(f"batch {batch_id} result for {poet} needs a reason")
        if not CHINESE_RE.search(row["reason"]):
            raise FactPackageError(f"batch {batch_id} result reason for {poet} must be Chinese")
        if any(
            not isinstance(url, str)
            or url != url.strip()
            or urlsplit(url).scheme.casefold() not in {"http", "https"}
            or not urlsplit(url).netloc
            for url in row["sources"]
        ):
            raise FactPackageError(f"batch {batch_id} result sources for {poet} must be http(s) URLs")
        if poem_identities is not None and (poet, row["title"], row["body_hash"]) not in poem_identities:
            raise FactPackageError(f"batch {batch_id} status poem identity mismatch for {poet}")
        packages = packages_by_poet.get(poet, [])
        if status == "verified":
            if len(packages) != 1:
                raise FactPackageError(f"batch {batch_id} verified {poet} must have exactly one package")
            package_identity = _identity(packages[0])
            if package_identity != (poet, row["title"], row["body_hash"]):
                raise FactPackageError(f"batch {batch_id} verified status/package mismatch for {poet}")
        else:
            if packages:
                raise FactPackageError(f"batch {batch_id} hold {poet} must not have a package")
            held_back.append({"batch_id": batch_id, **row})
        counts[status] += 1
    return held_back, dict(sorted(counts.items()))


def validate_cross_batch_sources(
    packages: Iterable[Mapping[str, Any]],
    poet_to_batch: Mapping[str, str],
) -> None:
    """Reject suspicious template reuse of one direct work URL across poems."""
    owners: dict[tuple[str, str], tuple[str, str, str]] = {}
    for package in packages:
        poet, title, body_hash = _identity(package)
        batch_id = poet_to_batch.get(poet, "baseline")
        for evidence in package.get("evidence", []):
            if not isinstance(evidence, Mapping) or not evidence.get("supports"):
                continue
            parsed = urlsplit(str(evidence.get("source_url", "")))
            host = (parsed.hostname or "").casefold()
            if "cnkgraph" not in host and "sou-yun" not in host and "souyun" not in host:
                continue
            query = parse_qs(parsed.query)
            if "cnkgraph" in host:
                match = re.search(r"/[Ww]riting/(\d+)", parsed.path)
                source_identity = f"writing:{match.group(1)}" if match else parsed.path
            else:
                work_keys = query.get("key", [])
                source_identity = (
                    f"work:{work_keys[0]}"
                    if len(work_keys) == 1 and work_keys[0].isdigit()
                    else parsed.path + "?" + parsed.query
                )
            key = (host, source_identity)
            identity = (poet, title, body_hash)
            previous = owners.setdefault(key, identity)
            if previous != identity:
                raise FactPackageError(
                    f"direct work source reused across poem identities: {key[0]}{key[1]}"
                )


def stage_text(path: Path, text: str) -> Path:
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", newline="\n", dir=path.parent,
            prefix=f".{path.name}.", suffix=".new", delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        return temporary
    except (OSError, UnicodeError) as exc:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise FactPackageError(f"failed to stage {path}: {exc}") from exc


def stage_many(texts: Mapping[Path, str]) -> dict[Path, Path]:
    staged: dict[Path, Path] = {}
    try:
        for target, text in texts.items():
            staged[target] = stage_text(target, text)
        return staged
    except FactPackageError:
        for temporary in staged.values():
            temporary.unlink(missing_ok=True)
        raise


def transactional_replace_many(replacements: Mapping[Path, Path]) -> None:
    """Replace a set of files, restoring old bytes or absence on failure."""
    backups: dict[Path, Path | None] = {}
    replaced: list[Path] = []
    try:
        for target in replacements:
            if target.exists():
                with tempfile.NamedTemporaryFile(
                    dir=target.parent, prefix=f".{target.name}.", suffix=".bak", delete=False
                ) as handle:
                    backup = Path(handle.name)
                shutil.copyfile(target, backup)
                backups[target] = backup
            else:
                backups[target] = None
        for target, staged in replacements.items():
            os.replace(staged, target)
            replaced.append(target)
    except OSError as exc:
        restore_errors: list[str] = []
        for target in reversed(replaced):
            backup = backups[target]
            try:
                if backup is None:
                    target.unlink(missing_ok=True)
                else:
                    os.replace(backup, target)
            except OSError as restore_exc:
                restore_errors.append(f"{target.name}: {restore_exc}")
        detail = f"transactional replace failed: {exc}"
        if restore_errors:
            detail += "; restore failures: " + "; ".join(restore_errors)
        raise FactPackageError(detail) from exc
    finally:
        for staged in replacements.values():
            staged.unlink(missing_ok=True)
        for backup in backups.values():
            if backup is not None:
                backup.unlink(missing_ok=True)


def build() -> dict[str, Any]:
    poems = load_json(POEMS)
    if not isinstance(poems, list) or any(not isinstance(row, dict) for row in poems):
        raise FactPackageError("data/poems.json must contain a list of poem objects")
    poet_order = _poet_order(poems)
    if len(poet_order) != 88:
        raise FactPackageError(f"expected 88 corpus poets, found {len(poet_order)}")
    assigned = [poet for batch in BATCHES.values() for poet in batch]
    if len(assigned) != 82 or len(set(assigned)) != 82:
        raise FactPackageError("batch roster must contain 82 unique non-core poets")
    if not set(assigned) < set(poet_order):
        raise FactPackageError("batch roster must be a proper subset of corpus poets")

    baseline = load_jsonl(BASELINE_PACKAGES)
    packages: list[dict[str, Any]] = list(baseline)
    held_back: list[dict[str, Any]] = []
    batch_stats: dict[str, dict[str, int]] = {}
    new_packages: list[dict[str, Any]] = []
    for batch_id in BATCHES:
        verified_path = SHARDS / f"batch_{batch_id}_verified.jsonl"
        status_path = SHARDS / f"batch_{batch_id}_status.json"
        verified = load_jsonl(verified_path)
        status = load_json(status_path)
        reject_encoding_damage(verified, f"batch {batch_id} verified packages")
        for package in verified:
            gate = validate_fact_package(package, poems)
            if gate["status"] != "verified":
                raise FactPackageError(f"batch {batch_id} contains non-verified package")
            validate_shard_semantics(package, batch_id)
            verification = package["verification"]
            if verification.get("reviewer") != SHARD_REVIEWER or verification.get("reviewed_at") != SHARD_REVIEWED_AT:
                raise FactPackageError(f"batch {batch_id} has unexpected review metadata")
        held, counts = validate_status(batch_id, status, verified, poems)
        held_back.extend(held)
        batch_stats[batch_id] = {
            "assigned": len(BATCHES[batch_id]),
            "verified": counts.get("verified", 0),
            "hold": counts.get("hold", 0),
        }
        new_packages.extend(verified)
        packages.extend(verified)

    for package in baseline:
        validate_fact_package(package, poems)
    poet_to_batch = {
        poet: batch_id for batch_id, batch_poets in BATCHES.items() for poet in batch_poets
    }
    validate_cross_batch_sources(new_packages, poet_to_batch)
    identities = [_identity(package) for package in packages]
    hashes = [identity[2] for identity in identities]
    if len(hashes) != len(set(hashes)):
        raise FactPackageError("merged release contains duplicate body_hash values")
    if len(identities) != len(set(identities)):
        raise FactPackageError("merged release contains duplicate poem identities")

    poet_rank = {poet: index for index, poet in enumerate(poet_order)}
    packages = _sort_packages(packages, poet_rank)
    expansions: list[dict[str, Any]] = []
    verdict_counts: Counter[str] = Counter()
    source_family_counts: Counter[str] = Counter()
    for package in packages:
        record = build_expansion_record(package, poems)
        if record is None:
            raise FactPackageError("merged release unexpectedly contains a hold package")
        expansions.append(record)
        verdict_counts[record["fact_verdict"]] += 1
        for source in record["sources"]:
            source_family_counts[source["source_family"]] += 1

    poet_counts = Counter(package["poem_key"]["poet"] for package in packages)
    coordinate_packages = [
        package
        for package in packages
        if package["chronology"].get("lon") is not None
        and package["chronology"].get("lat") is not None
    ]
    verified_poets = [poet for poet in poet_order if poet_counts[poet]]
    missing_poets = [poet for poet in poet_order if not poet_counts[poet]]
    coverage_complete = not missing_poets
    summary = {
        "schema_version": 1,
        "generated_by": "tools/build_all_poet_fact_release.py",
        "release_status": "complete" if coverage_complete else "partial",
        "coverage_complete": coverage_complete,
        "coverage_target_poets": 88,
        "verified_poet_count": len(verified_poets),
        "missing_poet_count": len(missing_poets),
        "held_back_poet_count": len(held_back),
        "release_count": len(packages),
        "baseline_release_count": len(baseline),
        "new_verified_count": len(new_packages),
        "coordinate_package_count": len(coordinate_packages),
        "coordinate_poet_count": len({package["poem_key"]["poet"] for package in coordinate_packages}),
        "verified_poets": verified_poets,
        "missing_poets": missing_poets,
        "poet_counts": {poet: poet_counts[poet] for poet in verified_poets},
        "batch_stats": batch_stats,
        "held_back": held_back,
        "source_family_counts": dict(sorted(source_family_counts.items())),
        "verdict_counts": dict(sorted(verdict_counts.items())),
        "scope_note": (
            "88位诗人均已有至少一首通过严格时地事实门的扩展。"
            if coverage_complete
            else f"严格事实门下当前覆盖{len(verified_poets)}/88位诗人；其余仅保留候选或hold，不冒充已核事实。"
        ),
        "coordinate_note": "经纬度只统计事实包中已有的来源坐标；地点已核但尚无坐标的记录不做自动猜测。",
    }

    package_text = "".join(stable_json(row) + "\n" for row in packages)
    expansion_text = "".join(stable_json(row) + "\n" for row in expansions)
    summary_text = stable_json(summary) + "\n"
    staged = stage_many({
        PACKAGES: package_text,
        EXPANSIONS: expansion_text,
        SUMMARY: summary_text,
    })
    transactional_replace_many(staged)
    return summary


def main() -> int:
    try:
        summary = build()
    except FactPackageError as exc:
        raise SystemExit(f"all-poet release build failed: {exc}") from exc
    print(stable_json({
        "release_status": summary["release_status"],
        "release_count": summary["release_count"],
        "verified_poet_count": summary["verified_poet_count"],
        "held_back": len(summary["held_back"]),
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
