"""Dynamic source identities for the corpus-wide journey collectors.

The registry is candidate-layer metadata.  It records what an adapter may
query; it does not promote any historical fact into ``data/reviewed``.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

from background_contract import (
    CANDIDATE_DIR,
    POEMS_JSON,
    POET_SOURCE_REGISTRY_JSON,
    POET_STATUS_JSONL,
    atomic_write_text,
    corpus_poet_profiles,
    read_jsonl,
    utc_now,
)


REGISTRY_SCHEMA_VERSION = 4
CBDB_AUDIT_TEMP_JSON = POEMS_JSON.parent.parent / "tmp" / "cbdb_identity_audit_88.json"
CBDB_AUDIT_SNAPSHOT_JSON = CANDIDATE_DIR / "cbdb_identity_audit_88.json"
SOUYUN_PROBE_TEMP_JSON = POEMS_JSON.parent.parent / "tmp" / "souyun_probe_88_summary.json"
SOUYUN_PROBE_SNAPSHOT_JSON = CANDIDATE_DIR / "souyun_identity_probe_88.json"

# Source-wide defaults mirror the candidate rows emitted by
# ``journey_source_pipeline``.  Per-candidate evidence may be downgraded where
# noted, but every registry source entry carries the complete metadata contract.
CBDB_SOURCE_METADATA = {
    "source_url": "https://cbdb.fas.harvard.edu/cbdbapi/person",
    "access_level": "open_api",
    "source_grade": "B",
    "source_grade_note": "有有效底本/页码且年份精确时为 B 级；区间或缺少出处时为 C 级",
    "license": "CC BY-NC-SA 4.0",
    "license_note": "CBDB 数据以 CC BY-NC-SA 4.0 发布；仅保存结构化字段与必要短引",
}
SOUYUN_SOURCE_METADATA = {
    "source_url": "https://api.sou-yun.cn/open/Poem",
    "access_level": "public_web",
    "source_grade": "C",
    "license": "",
    "license_note": "搜韵无机器复用的明确开放许可；仅保存结构化字段与必要短引，年份需人工复核",
}
CNKGRAPH_SOURCE_METADATA = {
    "source_url": "https://open.cnkgraph.com/api/Biography",
    "access_level": "open_api",
    "source_grade": "B",
    "source_grade_note": "定向 Biography 结构解析为 B 级；保守递归或作者未核实的作品降为 C 级",
    "license": "",
    "license_note": "CNKGraph 为非商业开放接口，数据版权属原底本；无明确机器复用许可；仅保存结构化字段与必要短引，本适配标记为实验性",
}

# Manually audited seeds retained from the original six-poet collector.  These
# are explicit identifiers, not choices made from an ambiguous name search.
AUDITED_CBDB_PERSON_IDS = {
    "李白": "32540",
    "杜甫": "3915",
    "白居易": "32227",
    "苏轼": "3767",
    "陆游": "3640",
    "李清照": "19713",
}

AUDITED_SOUYUN_AUTHOR_IDS = {
    "李白": 15188,
    "杜甫": 17270,
    "白居易": 18804,
    "苏轼": 29937,
    "陆游": 34522,
    "李清照": 27794,
}

AUDITED_CBDB_ALIASES = {
    "欧阳炯": ["欧阳炯", "欧阳迴"],
    "张志和": ["张志和", "张龟龄"],
}


def _accepted_cbdb_names(poet: str, audit: dict[str, Any]) -> list[str]:
    """Return only names explicitly bound to the audited CBDB person id.

    CBDB's API normally returns traditional-character primary names while the
    corpus roster is simplified.  The identity audit therefore persists the
    exact API primary name for every unique person id.  Keeping those names in
    the audit (rather than applying a broad character conversion here) means a
    name variant is accepted only when it was observed for the already-audited
    person id.
    """
    values: list[object] = [poet, *AUDITED_CBDB_ALIASES.get(poet, [])]
    audited_names = audit.get("accepted_names")
    if isinstance(audited_names, dict):
        names = audited_names.get(poet)
        if isinstance(names, list):
            values.extend(names)
    result: list[str] = []
    for value in values:
        name = str(value or "").strip()
        if name and name not in result:
            result.append(name)
    return result


def _match_person_id(match: object) -> str:
    if not isinstance(match, dict):
        return ""
    lowered = {str(key).casefold(): value for key, value in match.items()}
    for key in ("c_personid", "person_id", "personid", "id"):
        value = lowered.get(key)
        if value not in (None, ""):
            return str(value).strip()
    return ""


def _latest_identity_rows(rows: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        poet = str(row.get("poet") or "").strip()
        if poet:
            latest[poet] = dict(row)
    return latest


def load_cbdb_identity_audit() -> dict[str, Any]:
    # A newly produced audit/probe in tmp is the refresh input; the candidate
    # snapshot is the durable fallback after temporary files are cleaned.
    for path in (CBDB_AUDIT_TEMP_JSON, CBDB_AUDIT_SNAPSHOT_JSON):
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict) and isinstance(payload.get("unique"), dict):
            return payload
    return {}


def snapshot_cbdb_identity_audit(audit: dict[str, Any] | None = None) -> None:
    payload = audit if audit is not None else load_cbdb_identity_audit()
    if payload:
        atomic_write_text(
            CBDB_AUDIT_SNAPSHOT_JSON,
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        )


def load_souyun_identity_probe() -> dict[str, Any]:
    for path in (SOUYUN_PROBE_TEMP_JSON, SOUYUN_PROBE_SNAPSHOT_JSON):
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict) and isinstance(payload.get("rows"), list):
            return payload
    return {}


def snapshot_souyun_identity_probe(probe: dict[str, Any] | None = None) -> None:
    payload = probe if probe is not None else load_souyun_identity_probe()
    if payload:
        atomic_write_text(
            SOUYUN_PROBE_SNAPSHOT_JSON,
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        )


def _souyun_dynasty_matches(value: object, expected: str) -> bool:
    text = str(value or "").strip()
    if expected == "Tang":
        return text == "Tang" or "唐" in text
    if expected == "Song":
        return text == "Song" or "宋" in text
    return False


def _souyun_entry(
    poet: str,
    dynasty: str,
    probe_row: dict[str, Any] | None,
) -> dict[str, Any]:
    seed = AUDITED_SOUYUN_AUTHOR_IDS.get(poet)
    row = probe_row or {}
    names = row.get("names") if isinstance(row.get("names"), list) else []
    author_ids = row.get("author_ids") if isinstance(row.get("author_ids"), list) else []
    dynasties = row.get("source_dynasties") if isinstance(row.get("source_dynasties"), list) else []
    exact_ids: list[int] = []
    for index, name in enumerate(names):
        author_id = author_ids[index] if index < len(author_ids) else None
        source_dynasty = dynasties[index] if index < len(dynasties) else ""
        try:
            numeric_id = int(author_id)
        except (TypeError, ValueError):
            continue
        if str(name or "").strip() == poet and numeric_id > 0 and _souyun_dynasty_matches(source_dynasty, dynasty):
            if numeric_id not in exact_ids:
                exact_ids.append(numeric_id)

    # Fresh probe blockers are stronger than historical audited seeds.  Resolve
    # ambiguity/disambiguation first; only a non-blocked probe may fall back to
    # the seed as an active identity.
    blocker_status = ""
    if len(exact_ids) > 1:
        blocker_status = "identity_ambiguous"
    elif (
        len(exact_ids) == 1
        and row.get("page_size") == 0
        and not row.get("page0_records")
    ):
        blocker_status = "discovered_author_id_but_api_requires_disambiguation"

    status = "name_query"
    author_id: int | None = None
    if blocker_status:
        status = blocker_status
        if len(exact_ids) == 1:
            author_id = exact_ids[0]
    elif seed is not None:
        status = "audited_seed"
        author_id = seed
    elif len(exact_ids) == 1:
        status = "probe_unique"
        author_id = exact_ids[0]

    entry: dict[str, Any] = {
        **SOUYUN_SOURCE_METADATA,
        "status": status,
        "author_id": author_id,
        "identity_verified": False,
        "author_name": poet,
        "candidate_author_ids": exact_ids,
        "query_strategy": "open_poem_author_name_dynasty",
        "probe_status": str(row.get("status") or "not_probed"),
        "probe_count": row.get("count"),
        "probe_page_size": row.get("page_size"),
        "probe_page0_records": row.get("page0_records", 0),
        "probe_note": str(row.get("note") or ""),
    }
    if blocker_status and seed is not None:
        entry["stale_candidate_author_ids"] = [seed]
    if seed is not None and exact_ids and seed not in exact_ids:
        entry["probe_conflict_author_ids"] = exact_ids
    return entry


def _cbdb_entry(
    poet: str,
    identity: dict[str, Any] | None,
    audit: dict[str, Any],
) -> dict[str, Any]:
    identity = identity or {}
    raw_status = str(identity.get("status") or "unresolved")
    matches = identity.get("matches") if isinstance(identity.get("matches"), list) else []
    match_ids = [person_id for match in matches if (person_id := _match_person_id(match))]
    unique_ids = list(dict.fromkeys(match_ids))
    seed = AUDITED_CBDB_PERSON_IDS.get(poet, "")

    audit_unique = audit.get("unique") if isinstance(audit.get("unique"), dict) else {}
    audit_ambiguous = audit.get("ambiguous") if isinstance(audit.get("ambiguous"), dict) else {}
    audited_id = str(audit_unique.get(poet) or "").strip()
    audited_candidates = audit_ambiguous.get(poet) if isinstance(audit_ambiguous.get(poet), list) else []
    if audited_id:
        return {
            **CBDB_SOURCE_METADATA,
            "status": "audited_unique",
            "person_id": audited_id,
            "id_source": "cbdb_20260801_readonly_identity_audit",
            "identity_status": raw_status,
            "match_count": 1,
            "match_person_ids": [audited_id],
            "seed_conflict_person_id": None,
            "source_name": str(audit.get("source") or "CBDB read-only identity audit"),
            "identity_source_url": "https://github.com/cbdb-project/cbdb_sqlite",
            "source_version": "cbdb_20260801.sqlite3",
            "database_sha256": str(audit.get("database_sha256") or ""),
            "audit_rule": str(audit.get("rule") or ""),
            "accepted_names": _accepted_cbdb_names(poet, audit),
            "checked_at": str(identity.get("checked_at") or ""),
        }
    if audited_candidates:
        return {
            **CBDB_SOURCE_METADATA,
            "status": "audited_ambiguous",
            "person_id": None,
            "id_source": "cbdb_20260801_readonly_identity_audit",
            "identity_status": raw_status,
            "match_count": len(audited_candidates),
            "match_person_ids": [str(value) for value in audited_candidates],
            "seed_conflict_person_id": None,
            "source_name": str(audit.get("source") or "CBDB read-only identity audit"),
            "identity_source_url": "https://github.com/cbdb-project/cbdb_sqlite",
            "source_version": "cbdb_20260801.sqlite3",
            "database_sha256": str(audit.get("database_sha256") or ""),
            "audit_rule": str(audit.get("rule") or ""),
            "accepted_names": _accepted_cbdb_names(poet, audit),
            "checked_at": str(identity.get("checked_at") or ""),
        }

    status = raw_status
    person_id = ""
    id_source = ""
    if raw_status == "matched" and len(unique_ids) == 1:
        person_id = unique_ids[0]
        status = "matched"
        id_source = "cbdb_sqlite_exact_name_unique"
    elif raw_status == "ambiguous" or len(unique_ids) > 1:
        status = "ambiguous"
    elif raw_status == "not_found":
        status = "not_found"
    else:
        status = "unresolved"

    seed_conflict = ""
    if seed:
        if person_id and person_id != seed:
            seed_conflict = person_id
            person_id = seed
            status = "seed_conflict"
        elif not person_id:
            person_id = seed
            status = "audited_seed"
        id_source = "audited_core_seed"

    return {
        **CBDB_SOURCE_METADATA,
        "status": status,
        "person_id": person_id or None,
        "id_source": id_source or None,
        "identity_status": raw_status,
        "match_count": len(matches),
        "match_person_ids": unique_ids,
        "seed_conflict_person_id": seed_conflict or None,
        "source_name": str(identity.get("source_name") or "China Biographical Database SQLite"),
        "identity_source_url": str(identity.get("source_url") or "https://github.com/cbdb-project/cbdb_sqlite"),
        "source_version": identity.get("source_version"),
        "checked_at": str(identity.get("checked_at") or ""),
        "accepted_names": _accepted_cbdb_names(poet, audit),
    }


def build_source_registry(
    identity_rows: Iterable[dict[str, Any]] | None = None,
    *,
    audit: dict[str, Any] | None = None,
    souyun_probe: dict[str, Any] | None = None,
) -> dict[str, Any]:
    identities = _latest_identity_rows(
        read_jsonl(POET_STATUS_JSONL) if identity_rows is None else identity_rows
    )
    audit_payload = load_cbdb_identity_audit() if audit is None else audit
    probe_payload = load_souyun_identity_probe() if souyun_probe is None else souyun_probe
    probe_rows = {
        str(row.get("poet") or ""): row
        for row in (probe_payload.get("rows") if isinstance(probe_payload.get("rows"), list) else [])
        if isinstance(row, dict) and str(row.get("poet") or "")
    }
    poets: list[dict[str, Any]] = []
    for profile in corpus_poet_profiles():
        poet = profile["poet"]
        poets.append(
            {
                **profile,
                "cbdb": _cbdb_entry(poet, identities.get(poet), audit_payload),
                "souyun": _souyun_entry(poet, profile["dynasty"], probe_rows.get(poet)),
                "cnkgraph": {
                    **CNKGRAPH_SOURCE_METADATA,
                    "status": "author_name",
                    "author_name": poet,
                    "query_strategy": "author_name",
                },
            }
        )
    return {
        "schema_version": REGISTRY_SCHEMA_VERSION,
        "generated_at": utc_now(),
        "poems_sha256": hashlib.sha256(POEMS_JSON.read_bytes()).hexdigest(),
        "poet_count": len(poets),
        "scope_note": "当前语料与可检索来源的身份快照；歧义姓名不自动选择 CBDB person id。",
        "cbdb_identity_audit": {
            "source": audit_payload.get("source"),
            "database_sha256": audit_payload.get("database_sha256"),
            "rule": audit_payload.get("rule"),
            "unique_count": len(audit_payload.get("unique") or {}),
            "ambiguous_count": len(audit_payload.get("ambiguous") or {}),
            "snapshot_file": str(CBDB_AUDIT_SNAPSHOT_JSON.relative_to(POEMS_JSON.parent.parent)).replace("\\", "/"),
        },
        "souyun_identity_probe": {
            "generated_at": probe_payload.get("generated_at"),
            "totals": probe_payload.get("totals") if isinstance(probe_payload.get("totals"), dict) else {},
            "snapshot_file": str(SOUYUN_PROBE_SNAPSHOT_JSON.relative_to(POEMS_JSON.parent.parent)).replace("\\", "/"),
        },
        "poets": poets,
    }


def write_source_registry(
    registry: dict[str, Any],
    path: Path = POET_SOURCE_REGISTRY_JSON,
) -> dict[str, Any]:
    atomic_write_text(path, json.dumps(registry, ensure_ascii=False, indent=2) + "\n")
    return registry


def _read_registry_document(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


_SOUYUN_FRESH_IDENTITY_BLOCKERS = {
    "identity_ambiguous",
    "discovered_author_id_but_api_requires_disambiguation",
}
_SOUYUN_VERIFIED_PROVENANCE_FIELDS = (
    "identity_verified",
    "verified_author_name",
    "verified_dynasty",
    "verified_author_id",
    "identity_verification_method",
    "identity_verified_at",
    "identity_verified_from",
    "discovered_at",
    "discovered_from",
)


def _positive_int(value: object) -> int | None:
    # ``bool`` is a subclass of ``int`` in Python; accepting True here would
    # silently persist the bogus author id 1 from malformed legacy data.
    if isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _has_complete_souyun_provenance(source: dict[str, Any]) -> bool:
    for field in _SOUYUN_VERIFIED_PROVENANCE_FIELDS:
        if field not in source:
            return False
        value = source[field]
        if field == "identity_verified":
            if value is not True:
                return False
        elif field == "verified_author_id":
            if _positive_int(value) is None:
                return False
        elif not isinstance(value, str) or not value.strip():
            return False
    return True


def _append_stale_candidate_ids(target: dict[str, Any], *values: object) -> None:
    merged: list[int] = []
    existing = target.get("stale_candidate_author_ids")
    source_values = list(existing) if isinstance(existing, list) else []
    source_values.extend(values)
    for value in source_values:
        number = _positive_int(value)
        if number is not None and number not in merged:
            merged.append(number)
    if merged:
        target["stale_candidate_author_ids"] = merged


def _is_verified_souyun_discovery(
    source: dict[str, Any], *, poet: str, dynasty: str
) -> bool:
    author_id = _positive_int(source.get("author_id"))
    return bool(
        source.get("status") in {"discovered", "audited_seed"}
        and _has_complete_souyun_provenance(source)
        and source.get("identity_verified") is True
        and author_id is not None
        and _positive_int(source.get("verified_author_id")) == author_id
        and str(source.get("verified_author_name") or "") == poet
        and str(source.get("verified_dynasty") or "") == dynasty
        and str(source.get("identity_verification_method") or "")
        and str(source.get("identity_verified_at") or "")
        and str(source.get("identity_verified_from") or "")
    )


def _preserve_souyun_discoveries(
    registry: dict[str, Any], existing: dict[str, Any]
) -> dict[str, Any]:
    """Keep previously discovered Sou-yun ids across CBDB/poem refreshes.

    The six audited ids in the freshly built registry remain authoritative.  A
    conflicting older discovery is recorded for review rather than replacing
    an audited seed.
    """
    old_by_poet = registry_by_poet(existing)
    for row in registry.get("poets", []):
        if not isinstance(row, dict):
            continue
        poet = str(row.get("poet") or "")
        old_source = (old_by_poet.get(poet) or {}).get("souyun")
        new_source = row.get("souyun")
        if not isinstance(old_source, dict) or not isinstance(new_source, dict):
            continue
        fresh_status = str(new_source.get("status") or "")
        dynasty = str(row.get("dynasty") or "")
        old_id = _positive_int(old_source.get("author_id"))
        new_id = _positive_int(new_source.get("author_id"))
        old_status = str(old_source.get("status") or "")
        old_is_active_identity = old_status in {"discovered", "audited_seed"}
        old_is_verified = _is_verified_souyun_discovery(
            old_source, poet=poet, dynasty=dynasty
        )

        old_stale = old_source.get("stale_candidate_author_ids")
        if isinstance(old_stale, list):
            _append_stale_candidate_ids(new_source, *old_stale)
        _append_stale_candidate_ids(
            new_source, old_source.get("discovery_conflict_author_id")
        )

        if fresh_status in _SOUYUN_FRESH_IDENTITY_BLOCKERS:
            # Fresh ambiguity/disambiguation evidence is authoritative.  An old
            # verified discovery or audited seed is retained only as a
            # non-active review candidate.
            if old_is_active_identity and old_id is not None:
                _append_stale_candidate_ids(new_source, old_id)
            continue

        if fresh_status == "name_query":
            if old_is_verified and old_id is not None:
                new_source["status"] = old_status
                new_source["author_id"] = old_id
                for key in _SOUYUN_VERIFIED_PROVENANCE_FIELDS:
                    if old_source.get(key) not in (None, ""):
                        new_source[key] = old_source[key]
            elif old_is_active_identity and old_id is not None:
                # Legacy active identities without verification provenance are
                # retained for review but are not trusted as active identities.
                _append_stale_candidate_ids(new_source, old_id)
            continue

        if not old_is_active_identity or old_id is None:
            continue
        if new_id is not None and new_id != old_id:
            _append_stale_candidate_ids(new_source, old_id)
            if old_is_verified:
                new_source["discovery_conflict_author_id"] = old_id
                new_source["discovery_conflict_at"] = str(
                    old_source.get("identity_verified_at")
                    or old_source.get("discovered_at")
                    or ""
                )
        elif new_id == old_id and old_is_verified:
            # A probe's ``probe_unique`` status is discovery input, not an
            # active identity status.  Restore the verified active status so a
            # second refresh can validate and preserve the same provenance.
            # A freshly built audited seed remains authoritative over an older
            # plain discovery for the same id.
            if fresh_status != "audited_seed":
                new_source["status"] = old_status
            for key in _SOUYUN_VERIFIED_PROVENANCE_FIELDS:
                if old_source.get(key) not in (None, ""):
                    new_source[key] = old_source[key]
    return registry


def refresh_source_registry(
    identity_rows: Iterable[dict[str, Any]] | None = None,
    *,
    path: Path = POET_SOURCE_REGISTRY_JSON,
) -> dict[str, Any]:
    audit = load_cbdb_identity_audit()
    souyun_probe = load_souyun_identity_probe()
    # Fixture/tests commonly refresh into a temporary registry.  Only the real
    # project registry refresh may update durable source snapshots.
    if Path(path).resolve() == POET_SOURCE_REGISTRY_JSON.resolve():
        snapshot_cbdb_identity_audit(audit)
        snapshot_souyun_identity_probe(souyun_probe)
    existing = _read_registry_document(path)
    registry = build_source_registry(identity_rows, audit=audit, souyun_probe=souyun_probe)
    _preserve_souyun_discoveries(registry, existing)
    if existing:
        old_content = {key: value for key, value in existing.items() if key != "generated_at"}
        new_content = {key: value for key, value in registry.items() if key != "generated_at"}
        if old_content == new_content and existing.get("generated_at"):
            registry["generated_at"] = existing["generated_at"]
    return write_source_registry(registry, path)


def registry_by_poet(registry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = registry.get("poets") if isinstance(registry.get("poets"), list) else []
    return {
        str(row.get("poet") or ""): row
        for row in rows
        if isinstance(row, dict) and str(row.get("poet") or "")
    }


def load_source_registry(
    *,
    path: Path = POET_SOURCE_REGISTRY_JSON,
    refresh_if_stale: bool = True,
) -> dict[str, Any]:
    expected = [profile["poet"] for profile in corpus_poet_profiles()]
    if path.exists():
        registry = _read_registry_document(path)
        actual = [
            str(row.get("poet") or "")
            for row in registry.get("poets", [])
            if isinstance(row, dict)
        ] if isinstance(registry, dict) else []
        current_poems_sha = hashlib.sha256(POEMS_JSON.read_bytes()).hexdigest()
        current_audit = load_cbdb_identity_audit()
        current_probe = load_souyun_identity_probe()
        registry_audit = registry.get("cbdb_identity_audit") if isinstance(registry.get("cbdb_identity_audit"), dict) else {}
        registry_probe = registry.get("souyun_identity_probe") if isinstance(registry.get("souyun_identity_probe"), dict) else {}
        audit_matches = (
            not current_audit
            or str(registry_audit.get("database_sha256") or "")
            == str(current_audit.get("database_sha256") or "")
        )
        probe_matches = (
            not current_probe
            or str(registry_probe.get("generated_at") or "")
            == str(current_probe.get("generated_at") or "")
        )
        if (
            actual == expected
            and int(registry.get("schema_version") or 0) == REGISTRY_SCHEMA_VERSION
            and str(registry.get("poems_sha256") or "") == current_poems_sha
            and audit_matches
            and probe_matches
        ):
            return registry
        if not refresh_if_stale:
            raise ValueError("poet source registry is stale or malformed")
    return refresh_source_registry(path=path)


def merge_souyun_discoveries(
    registry: dict[str, Any],
    status_rows: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    """Merge numeric IDs discovered from canonical Sou-yun pages in one place."""
    by_poet = registry_by_poet(registry)
    changed = False
    for status in status_rows:
        if str(status.get("source") or "") != "souyun":
            continue
        if (
            status.get("identity_verified") is not True
            or str(status.get("status") or "") not in {"ok", "collected"}
        ):
            continue
        poet = str(status.get("poet") or "")
        author_id = _positive_int(status.get("author_id"))
        if author_id is None or poet not in by_poet:
            continue
        target = by_poet[poet].get("souyun")
        if not isinstance(target, dict):
            continue
        verified_author_id = _positive_int(status.get("verified_author_id"))
        if verified_author_id != author_id:
            continue
        parent = by_poet[poet]
        verified_name = str(status.get("verified_author_name") or "")
        verified_dynasty = str(status.get("verified_dynasty") or "")
        if verified_name != poet or verified_dynasty not in {"Tang", "Song"}:
            continue
        if str(parent.get("dynasty") or "") not in {"", verified_dynasty}:
            continue
        verified_at = str(
            status.get("identity_verified_at") or status.get("checked_at") or ""
        )
        verified_from = str(
            status.get("identity_verified_from") or status.get("source_url") or ""
        )
        if not verified_at or not verified_from:
            continue

        # A fresh ambiguity/disambiguation result is stronger than a later
        # work-page hit.  Keep the verified id only as a review candidate; do
        # not turn the active registry identity into ``discovered``.
        if str(target.get("status") or "") in _SOUYUN_FRESH_IDENTITY_BLOCKERS:
            before_stale = list(target.get("stale_candidate_author_ids") or [])
            _append_stale_candidate_ids(target, author_id)
            if list(target.get("stale_candidate_author_ids") or []) != before_stale:
                changed = True
            continue

        existing = _positive_int(target.get("author_id"))
        if existing is not None and existing != author_id:
            conflict = {
                "discovery_conflict_author_id": author_id,
                "discovery_conflict_at": verified_at,
            }
            if any(target.get(key) != value for key, value in conflict.items()):
                target.update(conflict)
                changed = True
            continue
        retained_status = "audited_seed" if target.get("status") == "audited_seed" else "discovered"
        verified_values = {
            "status": retained_status,
            "author_id": author_id,
            "query_strategy": "open_poem_author_name_dynasty",
            "identity_verified": True,
            "verified_author_name": verified_name,
            "verified_dynasty": verified_dynasty,
            "verified_author_id": author_id,
            "identity_verification_method": "souyun_open_poem_exact_name_dynasty_author_id",
            "identity_verified_at": verified_at,
            "identity_verified_from": verified_from,
            "discovered_at": verified_at,
            "discovered_from": verified_from,
        }
        if any(target.get(key) != value for key, value in verified_values.items()):
            target.update(verified_values)
            changed = True
    if changed:
        registry["generated_at"] = utc_now()
    return registry
