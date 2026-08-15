"""初始化主题版 MySQL 数据库并导入诗词、行旅和审核后富背景数据。"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import pymysql

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "data"))

from config import DB_NAME, DATA_DIR, MYSQL
from data.image_dict import IMAGE_DICT, words as image_words
from data.place_dict import PLACE_DICT, aliases as place_aliases
from data.season_rules import detect_season

SCHEMA_SQL = ROOT / "数据库操作脚本及数据库SQL" / "schema.sql"
POEMS_JSON = DATA_DIR / "poems.json"
JOURNEYS_JSON = DATA_DIR / "reviewed" / "poet_journeys.json"
CONTEXTS_CSV = DATA_DIR / "reviewed" / "verified_poem_contexts.csv"
RICH_BACKGROUNDS_JSONL = DATA_DIR / "reviewed" / "verified_poem_backgrounds.jsonl"
BACKGROUND_CANDIDATES_JSONL = DATA_DIR / "candidates" / "poem_background_candidates.jsonl"

EMOTION_LABELS = {
    "思乡": "对故乡、故国或归途的怀念",
    "怀人": "对亲友、伴侣或故人的思念",
    "离别": "送别、分别与关系中断",
    "孤独": "独处、羁旅和精神孤寂",
    "忧国": "战争、民生和国家命运忧思",
    "旷达": "超越现实压力的自我调适",
    "喜悦": "欣喜、赞美和生命活力",
    "悲愁": "哀伤、失意、衰老和困顿",
    "豪情": "进取、壮阔、自信和昂扬",
    "闲适": "日常、田园与安宁心境",
}

CONFIDENCE_MAP = {
    "high": 0.90,
    "medium": 0.70,
    "low": 0.45,
    "a": 0.95,
    "b": 0.80,
    "c": 0.60,
    "d": 0.30,
}


def extract_places(text: str) -> dict[str, int]:
    """按长词优先抽取诗中提及地点，不把它解释为创作地点。"""
    counts: dict[str, int] = {}
    work = text
    for alias in place_aliases():
        n = work.count(alias)
        if n:
            counts[alias] = counts.get(alias, 0) + n
            work = work.replace(alias, "·" * len(alias))
    return counts


def extract_images(text: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    work = text
    for word in image_words():
        n = work.count(word)
        if n:
            counts[word] = counts.get(word, 0) + n
            work = work.replace(word, "·" * len(word))
    return counts


def estimate_sentiment(images: dict[str, int]) -> float:
    """旧版固定词典分数，仅保留为兼容字段，不用于同意象异情结论。"""
    if not images:
        return 0.0
    lookup = {row[0]: row[2] for row in IMAGE_DICT}
    total_weight = sum(freq for word, freq in images.items() if word in lookup)
    if not total_weight:
        return 0.0
    total = sum(lookup[word] * freq for word, freq in images.items() if word in lookup)
    return round(total / total_weight, 2)


def body_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def parse_datetime(value: object) -> str | None:
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
        return parsed.replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def as_int(value: object) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return None


def as_float(value: object, default: float | None = None) -> float | None:
    if value in (None, ""):
        return default
    text = str(value).strip().lower()
    if text in CONFIDENCE_MAP:
        return CONFIDENCE_MAP[text]
    try:
        return float(text)
    except (TypeError, ValueError):
        return default


def run_schema(cur, reset: bool = False) -> None:
    sql = SCHEMA_SQL.read_text(encoding="utf-8").replace(
        "shixing_wanli",
        DB_NAME,
    )
    statements = [statement.strip() for statement in sql.split(";") if statement.strip()]
    for statement in statements:
        first_sql_line = next(
            (
                line.strip()
                for line in statement.splitlines()
                if line.strip() and not line.strip().startswith("--")
            ),
            "",
        )
        if not reset and first_sql_line.upper().startswith("DROP TABLE"):
            continue
        cur.execute(statement)


def column_names(cur, table: str) -> set[str]:
    cur.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema=%s AND table_name=%s",
        (DB_NAME, table),
    )
    return {row[0] for row in cur.fetchall()}


def index_names(cur, table: str) -> set[str]:
    cur.execute(
        "SELECT DISTINCT index_name FROM information_schema.statistics "
        "WHERE table_schema=%s AND table_name=%s",
        (DB_NAME, table),
    )
    return {row[0] for row in cur.fetchall()}


def migrate_existing_poem_table(cur) -> None:
    """让未执行 --reset 的旧六表数据库兼容新采集字段。"""
    columns = column_names(cur, "t_poem")
    additions = {
        "source_site": "VARCHAR(32)",
        "source_url": "VARCHAR(512)",
        "source_poem_id": "VARCHAR(128)",
        "body_hash": "CHAR(64) NULL",
        "crawled_at": "DATETIME",
    }
    for name, sql_type in additions.items():
        if name not in columns:
            cur.execute(f"ALTER TABLE t_poem ADD COLUMN {name} {sql_type}")

    cur.execute("SELECT poem_id, body FROM t_poem WHERE body_hash IS NULL OR body_hash=''")
    for poem_id, body in cur.fetchall():
        cur.execute(
            "UPDATE t_poem SET body_hash=%s WHERE poem_id=%s",
            (body_hash(body or ""), poem_id),
        )

    indexes = index_names(cur, "t_poem")
    if "uk_poet_title" in indexes:
        cur.execute("ALTER TABLE t_poem DROP INDEX uk_poet_title")
        indexes.remove("uk_poet_title")
    if "uk_poet_body_hash" not in indexes:
        cur.execute(
            "ALTER TABLE t_poem ADD UNIQUE INDEX uk_poet_body_hash(poet_id, body_hash)"
        )
    if "idx_source_poem" not in indexes:
        cur.execute("ALTER TABLE t_poem ADD INDEX idx_source_poem(source_poem_id)")
    cur.execute("ALTER TABLE t_poem MODIFY body_hash CHAR(64) NOT NULL")


def migrate_background_schema(cur) -> None:
    """Add evidence fields when incrementally upgrading an older theme database."""
    additions = {
        "t_source": {
            "source_grade": "CHAR(1) DEFAULT 'C'",
            "access_level": "VARCHAR(32) DEFAULT 'public_web'",
            "license_note": "TEXT",
            "content_hash": "CHAR(64)",
            "source_version": "VARCHAR(128)",
        },
        "t_claim_evidence": {
            "candidate_id": "CHAR(64)",
            "source_locator": "VARCHAR(512)",
            "extraction_method": "VARCHAR(64)",
            "model_id": "VARCHAR(128)",
            "prompt_version": "VARCHAR(64)",
            "reviewer": "VARCHAR(128)",
            "reviewed_at": "DATETIME",
        },
    }
    for table, columns in additions.items():
        existing = column_names(cur, table)
        for name, sql_type in columns.items():
            if name not in existing:
                cur.execute(f"ALTER TABLE {table} ADD COLUMN {name} {sql_type}")
    claim_indexes = index_names(cur, "t_claim_evidence")
    if "uk_claim_candidate" not in claim_indexes:
        cur.execute("ALTER TABLE t_claim_evidence ADD UNIQUE INDEX uk_claim_candidate(candidate_id)")


def load_dimensions(cur) -> tuple[dict[str, int], dict[str, int], dict[str, int]]:
    place_ids: dict[str, int] = {}
    image_ids: dict[str, int] = {}
    emotion_ids: dict[str, int] = {}

    for alias, modern, province, lon, lat, note in PLACE_DICT:
        cur.execute(
            "INSERT INTO t_place(alias, modern, province, lon, lat, note) "
            "VALUES (%s,%s,%s,%s,%s,%s) "
            "ON DUPLICATE KEY UPDATE modern=VALUES(modern), province=VALUES(province), "
            "lon=VALUES(lon), lat=VALUES(lat), note=VALUES(note)",
            (alias, modern, province, lon, lat, note),
        )
    cur.execute("SELECT alias, place_id FROM t_place")
    place_ids.update(cur.fetchall())

    for word, category, sentiment in IMAGE_DICT:
        cur.execute(
            "INSERT INTO t_image(word, category, sentiment) VALUES (%s,%s,%s) "
            "ON DUPLICATE KEY UPDATE category=VALUES(category), sentiment=VALUES(sentiment)",
            (word, category, sentiment),
        )
    cur.execute("SELECT word, image_id FROM t_image")
    image_ids.update(cur.fetchall())

    for label, description in EMOTION_LABELS.items():
        cur.execute(
            "INSERT INTO t_emotion(label, description) VALUES (%s,%s) "
            "ON DUPLICATE KEY UPDATE description=VALUES(description)",
            (label, description),
        )
    cur.execute("SELECT label, emotion_id FROM t_emotion")
    emotion_ids.update(cur.fetchall())
    return place_ids, image_ids, emotion_ids


def load_poems(
    cur,
    place_ids: dict[str, int],
    image_ids: dict[str, int],
) -> tuple[dict[str, int], dict[tuple[str, str], int], dict[str, int], int]:
    if not POEMS_JSON.exists():
        raise FileNotFoundError(f"缺少爬虫结果：{POEMS_JSON}")

    records = json.loads(POEMS_JSON.read_text(encoding="utf-8"))
    poet_ids: dict[str, int] = {}
    poem_ids: dict[tuple[str, str], int] = {}
    poem_hash_ids: dict[str, int] = {}

    for record in records:
        poet = record.get("poet") or record.get("author") or ""
        title = str(record.get("title") or "").strip()
        text = str(record.get("body") or "").strip()
        if not (poet and title and text):
            continue

        dynasty = record.get("dynasty") or ""
        school = record.get("school") or ""
        if poet not in poet_ids:
            cur.execute(
                "INSERT INTO t_poet(name, dynasty, school) VALUES (%s,%s,%s) "
                "ON DUPLICATE KEY UPDATE "
                "dynasty=COALESCE(NULLIF(VALUES(dynasty),''),dynasty), "
                "school=COALESCE(NULLIF(VALUES(school),''),school)",
                (poet, dynasty, school),
            )
            cur.execute("SELECT poet_id FROM t_poet WHERE name=%s", (poet,))
            poet_ids[poet] = cur.fetchone()[0]
        poet_id = poet_ids[poet]

        digest = record.get("body_hash") or body_hash(text)
        places = extract_places(title + "\n" + text)
        images = extract_images(text)
        sentiment = estimate_sentiment(images)
        season = detect_season(title, text)
        crawled_at = parse_datetime(record.get("crawled_at"))

        cur.execute(
            "SELECT poem_id FROM t_poem WHERE poet_id=%s AND body_hash=%s LIMIT 1",
            (poet_id, digest),
        )
        existing = cur.fetchone()
        if existing:
            poem_id = existing[0]
            cur.execute(
                "UPDATE t_poem SET title=%s,body=%s,body_len=%s,sentiment=%s,season=%s,"
                "source_site=%s,source_url=%s,source_poem_id=%s,crawled_at=%s "
                "WHERE poem_id=%s",
                (
                    title,
                    text,
                    len(text),
                    sentiment,
                    season,
                    record.get("source_site"),
                    record.get("source_url"),
                    record.get("source_poem_id"),
                    crawled_at,
                    poem_id,
                ),
            )
            cur.execute("DELETE FROM t_poem_place WHERE poem_id=%s", (poem_id,))
            cur.execute("DELETE FROM t_poem_image WHERE poem_id=%s", (poem_id,))
        else:
            cur.execute(
                "INSERT INTO t_poem("
                "poet_id,title,body,body_len,sentiment,season,source_site,source_url,"
                "source_poem_id,body_hash,crawled_at"
                ") VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    poet_id,
                    title,
                    text,
                    len(text),
                    sentiment,
                    season,
                    record.get("source_site"),
                    record.get("source_url"),
                    record.get("source_poem_id"),
                    digest,
                    crawled_at,
                ),
            )
            poem_id = cur.lastrowid

        poem_ids[(poet, title)] = poem_id
        poem_hash_ids[str(digest)] = poem_id
        for alias, freq in places.items():
            if alias in place_ids:
                cur.execute(
                    "INSERT INTO t_poem_place(poem_id,place_id,freq) VALUES (%s,%s,%s) "
                    "ON DUPLICATE KEY UPDATE freq=VALUES(freq)",
                    (poem_id, place_ids[alias], freq),
                )
        for word, freq in images.items():
            if word in image_ids:
                cur.execute(
                    "INSERT INTO t_poem_image(poem_id,image_id,freq) VALUES (%s,%s,%s) "
                    "ON DUPLICATE KEY UPDATE freq=VALUES(freq)",
                    (poem_id, image_ids[word], freq),
                )

    cur.execute(
        "UPDATE t_poet p SET poem_count="
        "(SELECT COUNT(*) FROM t_poem WHERE poet_id=p.poet_id)"
    )
    return poet_ids, poem_ids, poem_hash_ids, len(records)


def upsert_source(
    cur,
    name: str,
    url: str,
    note: str = "",
    source_type: str = "web",
    *,
    citation: str = "",
    source_grade: str = "C",
    access_level: str = "public_web",
    license_note: str = "",
    content_hash: str = "",
    source_version: str = "",
) -> int:
    if url:
        cur.execute("SELECT source_id FROM t_source WHERE source_url=%s LIMIT 1", (url,))
    else:
        cur.execute(
            "SELECT source_id FROM t_source "
            "WHERE source_url IS NULL AND source_name=%s LIMIT 1",
            (name,),
        )
    row = cur.fetchone()
    if row:
        source_id = row[0]
        cur.execute(
            "UPDATE t_source SET source_name=%s,source_note=%s,source_type=%s,"
            "citation=%s,source_grade=%s,access_level=%s,license_note=%s,"
            "content_hash=%s,source_version=%s "
            "WHERE source_id=%s",
            (
                name or "未命名来源",
                note,
                source_type,
                citation or None,
                str(source_grade or "C").upper()[:1],
                access_level or "public_web",
                license_note or None,
                content_hash or None,
                source_version or None,
                source_id,
            ),
        )
        return source_id
    cur.execute(
        "INSERT INTO t_source(source_name,source_url,source_type,citation,source_note,"
        "source_grade,access_level,license_note,content_hash,source_version,accessed_at) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,CURRENT_DATE)",
        (
            name or "未命名来源",
            url or None,
            source_type,
            citation or None,
            note,
            str(source_grade or "C").upper()[:1],
            access_level or "public_web",
            license_note or None,
            content_hash or None,
            source_version or None,
        ),
    )
    return cur.lastrowid


def iter_journey_events(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    if isinstance(payload.get("journeys"), list):
        return payload["journeys"]
    result: list[dict[str, Any]] = []
    for poet_row in payload.get("poets", []):
        poet = poet_row.get("poet") or poet_row.get("name")
        dynasty = poet_row.get("dynasty")
        for event in poet_row.get(
            "events",
            poet_row.get("nodes", poet_row.get("stops", [])),
        ):
            row = dict(event)
            row.setdefault("poet", poet)
            row.setdefault("dynasty", dynasty)
            result.append(row)
    return result


def infer_province(place: str) -> str:
    for suffix in ("省", "自治区"):
        if suffix in place:
            return place.split(suffix, 1)[0] + suffix
    for municipality in ("北京市", "上海市", "天津市", "重庆市"):
        if place.startswith(municipality):
            return municipality
    return ""


def life_context_text(value: object) -> str:
    if isinstance(value, dict):
        label = str(value.get("label") or "")
        reason = str(value.get("reason") or "")
        return "：".join(part for part in (label, reason) if part)
    return str(value or "")


def related_poem_titles(row: dict[str, Any]) -> list[str]:
    explicit = row.get("related_poems") or row.get("poems")
    if isinstance(explicit, list):
        return [str(item) for item in explicit if item]
    linked = row.get("linked_poem")
    if isinstance(linked, dict) and linked.get("title"):
        return [str(linked["title"])]
    return []


def load_journeys(cur, poet_ids: dict[str, int]) -> tuple[int, int]:
    if not JOURNEYS_JSON.exists():
        print(f"      [skip] 尚无 {JOURNEYS_JSON.name}")
        return 0, 0
    payload = json.loads(JOURNEYS_JSON.read_text(encoding="utf-8-sig"))
    events = iter_journey_events(payload)
    event_count = 0
    stop_count = 0

    for row in events:
        poet = row.get("poet") or row.get("name")
        if poet not in poet_ids:
            continue
        status = str(row.get("status") or row.get("review_status") or "approved")
        if status not in {"approved", "reviewed", "published"}:
            continue
        source_id = upsert_source(
            cur,
            str(row.get("source_name") or "未命名来源"),
            str(row.get("source_url") or ""),
            str(row.get("source_note") or row.get("note") or ""),
        )
        event_title = str(
            row.get("event_title")
            or row.get("event")
            or row.get("title")
            or "生平节点"
        )
        year_start = as_int(row.get("year_start") or row.get("year"))
        year_end = as_int(row.get("year_end")) or year_start
        modern_city = str(
            row.get("modern_city")
            or row.get("modern_place")
            or row.get("place_modern")
            or ""
        )
        historical_place = str(
            row.get("historical_place")
            or row.get("place_historical")
            or row.get("place")
            or modern_city
        )
        fact_grade = str(
            row.get("fact_grade")
            or row.get("source_level")
            or "C"
        ).upper()[:1]
        confidence = as_float(
            row.get("confidence"),
            CONFIDENCE_MAP.get(fact_grade.lower(), 0.6),
        )
        description = (
            str(row.get("description") or "")
            or life_context_text(row.get("life_context"))
            or str(row.get("context") or "")
        )
        province = str(row.get("province") or infer_province(modern_city))

        cur.execute(
            "SELECT event_id FROM t_life_event "
            "WHERE poet_id=%s AND event_title=%s AND year_start <=> %s LIMIT 1",
            (poet_ids[poet], event_title, year_start),
        )
        existing_event = cur.fetchone()
        if existing_event:
            event_id = existing_event[0]
            cur.execute(
                "UPDATE t_life_event SET event_type=%s,year_end=%s,historical_place=%s,"
                "modern_city=%s,province=%s,description=%s,source_id=%s,fact_grade=%s,"
                "review_status=%s WHERE event_id=%s",
                (
                    row.get("event_type") or "行旅",
                    year_end,
                    historical_place,
                    modern_city,
                    province,
                    description,
                    source_id,
                    fact_grade,
                    status,
                    event_id,
                ),
            )
        else:
            cur.execute(
                "INSERT INTO t_life_event("
                "poet_id,event_title,event_type,year_start,year_end,historical_place,"
                "modern_city,province,description,source_id,fact_grade,review_status"
                ") VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    poet_ids[poet],
                    event_title,
                    row.get("event_type") or "行旅",
                    year_start,
                    year_end,
                    historical_place,
                    modern_city,
                    province,
                    description,
                    source_id,
                    fact_grade,
                    status,
                ),
            )
            event_id = cur.lastrowid
            event_count += 1

        cur.execute(
            "SELECT stop_id FROM t_journey_stop "
            "WHERE poet_id=%s AND event_title=%s AND year_start <=> %s "
            "AND modern_city=%s LIMIT 1",
            (poet_ids[poet], event_title, year_start, modern_city),
        )
        existing_stop = cur.fetchone()
        related_poems = json.dumps(related_poem_titles(row), ensure_ascii=False)
        stop_values = (
            event_id,
            year_end,
            historical_place,
            modern_city,
            province,
            as_float(row.get("lon") or row.get("longitude")),
            as_float(row.get("lat") or row.get("latitude")),
            description,
            related_poems,
            source_id,
            fact_grade,
            confidence,
            status,
        )
        if existing_stop:
            cur.execute(
                "UPDATE t_journey_stop SET event_id=%s,year_end=%s,historical_place=%s,"
                "modern_city=%s,province=%s,lon=%s,lat=%s,life_context=%s,"
                "related_poems=%s,source_id=%s,fact_grade=%s,confidence=%s,"
                "review_status=%s WHERE stop_id=%s",
                (*stop_values, existing_stop[0]),
            )
        else:
            cur.execute(
                "INSERT INTO t_journey_stop("
                "poet_id,event_id,event_title,year_start,year_end,historical_place,"
                "modern_city,province,lon,lat,life_context,related_poems,source_id,"
                "fact_grade,confidence,review_status"
                ") VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    poet_ids[poet],
                    event_id,
                    event_title,
                    year_start,
                    *stop_values[1:],
                ),
            )
            stop_count += 1

    return event_count, stop_count


def load_contexts(cur, poem_ids: dict[tuple[str, str], int]) -> int:
    if not CONTEXTS_CSV.exists():
        print(f"      [skip] 尚无 {CONTEXTS_CSV.name}")
        return 0
    count = 0
    with CONTEXTS_CSV.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            status = (row.get("status") or "approved").strip()
            if status not in {"approved", "reviewed", "published"}:
                continue
            key = ((row.get("poet") or "").strip(), (row.get("title") or "").strip())
            poem_id = poem_ids.get(key)
            if not poem_id:
                print(f"      [warn] 未找到作品：{key[0]}《{key[1]}》")
                continue
            source_id = upsert_source(
                cur,
                row.get("source_name") or "未命名来源",
                row.get("source_url") or "",
                row.get("source_note") or "",
            )
            grade = (row.get("fact_grade") or "C").upper()[:1]
            confidence = as_float(
                row.get("confidence"),
                CONFIDENCE_MAP.get(grade.lower(), 0.6),
            )
            year_start = as_int(row.get("year_start") or row.get("year"))
            year_end = as_int(row.get("year_end") or row.get("year")) or year_start
            historical_place = row.get("historical_place") or row.get("composition_place")
            modern_city = row.get("modern_city") or row.get("modern_place")
            context_note = row.get("context_note") or row.get("source_note") or ""
            values = (
                year_start,
                year_end,
                historical_place,
                modern_city,
                row.get("province"),
                as_float(row.get("lon")),
                as_float(row.get("lat")),
                context_note,
                source_id,
                grade,
                confidence,
                status,
            )
            cur.execute(
                "INSERT INTO t_poem_context("
                "poem_id,year_start,year_end,historical_place,modern_city,province,"
                "lon,lat,context_note,source_id,fact_grade,confidence,review_status"
                ") VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON DUPLICATE KEY UPDATE year_start=VALUES(year_start),"
                "year_end=VALUES(year_end),historical_place=VALUES(historical_place),"
                "modern_city=VALUES(modern_city),province=VALUES(province),"
                "lon=VALUES(lon),lat=VALUES(lat),context_note=VALUES(context_note),"
                "fact_grade=VALUES(fact_grade),confidence=VALUES(confidence),"
                "review_status=VALUES(review_status)",
                (poem_id, *values),
            )
            cur.execute(
                "DELETE FROM t_claim_evidence WHERE claim_type='fact' "
                "AND subject_type='poem' AND subject_id=%s "
                "AND predicate_name='创作于' AND source_id=%s",
                (poem_id, source_id),
            )
            cur.execute(
                "INSERT INTO t_claim_evidence("
                "claim_type,subject_type,subject_id,predicate_name,object_text,source_id,"
                "evidence_text,fact_grade,confidence,review_status"
                ") VALUES ('fact','poem',%s,'创作于',%s,%s,%s,%s,%s,%s)",
                (
                    poem_id,
                    f"{year_start or '时间待考'} / {modern_city or '地点待考'}",
                    source_id,
                    context_note,
                    grade,
                    confidence,
                    status,
                ),
            )
            count += 1
    return count


def read_jsonl_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_no} 不是合法 JSONL") from exc
        if isinstance(row, dict):
            rows.append(row)
    return rows


def source_type_for(access_level: object) -> str:
    level = str(access_level or "").strip().casefold()
    if level == "authenticated_manual":
        return "manual"
    if level == "open_api":
        return "api"
    if level == "project_generated":
        return "project"
    return "web"


def candidate_value_text(value: object) -> str:
    """Keep claim values structured without duplicating third-party page text."""
    if isinstance(value, dict):
        clean = {key: item for key, item in value.items() if key != "source_excerpt"}
        return json.dumps(clean, ensure_ascii=False, sort_keys=True)
    return json.dumps(value, ensure_ascii=False)


def strongest_source_grade(rows: list[dict[str, Any]]) -> str:
    order = {"A": 4, "B": 3, "C": 2, "D": 1}
    grades = [str(row.get("source_grade") or "D").upper()[:1] for row in rows]
    return max(grades, key=lambda grade: order.get(grade, 0), default="D")


def load_rich_backgrounds(
    cur,
    poem_ids: dict[tuple[str, str], int],
    poem_hash_ids: dict[str, int],
) -> tuple[int, int]:
    if not RICH_BACKGROUNDS_JSONL.exists():
        print(f"      [skip] 尚无 {RICH_BACKGROUNDS_JSONL.name}")
        return 0, 0

    approved_candidates = {
        str(row.get("candidate_id") or ""): row
        for row in read_jsonl_records(BACKGROUND_CANDIDATES_JSONL)
        if row.get("status") == "approved" and row.get("candidate_id")
    }
    record_count = 0
    evidence_count = 0
    predicate_names = {
        "composition_date": "创作时间",
        "composition_place": "创作地点",
        "life_event": "关联生平事件",
        "historical_context": "时代与创作背景",
        "translation": "项目整理译文",
        "annotation": "项目整理注释",
        "appreciation": "项目整理赏析",
    }

    for record in read_jsonl_records(RICH_BACKGROUNDS_JSONL):
        if record.get("review_status") != "approved":
            continue
        key = record.get("poem_key") if isinstance(record.get("poem_key"), dict) else {}
        digest = str(key.get("body_hash") or "")
        poet = str(key.get("poet") or "").strip()
        title = str(key.get("title") or "").strip()
        poem_id = poem_hash_ids.get(digest) or poem_ids.get((poet, title))
        if not poem_id:
            print(f"      [warn] 富背景未找到作品：{poet}《{title}》")
            continue

        source_ids: dict[str, int] = {}
        for source in record.get("sources") or []:
            if not isinstance(source, dict):
                continue
            candidate_id = str(source.get("candidate_id") or "")
            source_ids[candidate_id] = upsert_source(
                cur,
                str(source.get("name") or "未命名来源"),
                str(source.get("url") or ""),
                str(source.get("excerpt") or "")[:160],
                source_type_for(source.get("access_level")),
                citation=str(source.get("citation") or ""),
                source_grade=str(source.get("grade") or "C"),
                access_level=str(source.get("access_level") or "public_web"),
                license_note=str(source.get("license_note") or ""),
            )

        composition = record.get("composition") if isinstance(record.get("composition"), dict) else {}
        date = composition.get("date") if isinstance(composition.get("date"), dict) else {}
        place = composition.get("place") if isinstance(composition.get("place"), dict) else {}
        composition_ids = [
            str(candidate_id)
            for candidate_id in (
                list(composition.get("date_evidence_ids") or [])
                + list(composition.get("place_evidence_ids") or [])
            )
            if candidate_id
        ]
        composition_candidates = [
            approved_candidates[candidate_id]
            for candidate_id in composition_ids
            if candidate_id in approved_candidates
        ]
        context_source_id = next(
            (source_ids[candidate_id] for candidate_id in composition_ids if candidate_id in source_ids),
            None,
        )
        if context_source_id and (date or place):
            confidence = max(
                (as_float(row.get("confidence"), 0.5) or 0.5 for row in composition_candidates),
                default=0.5,
            )
            cur.execute(
                "INSERT INTO t_poem_context("
                "poem_id,year_start,year_end,historical_place,modern_city,province,lon,lat,"
                "context_note,source_id,fact_grade,confidence,review_status"
                ") VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'approved') "
                "ON DUPLICATE KEY UPDATE year_start=VALUES(year_start),year_end=VALUES(year_end),"
                "historical_place=VALUES(historical_place),modern_city=VALUES(modern_city),"
                "province=VALUES(province),lon=VALUES(lon),lat=VALUES(lat),"
                "context_note=VALUES(context_note),fact_grade=VALUES(fact_grade),"
                "confidence=VALUES(confidence),review_status='approved'",
                (
                    poem_id,
                    as_int(date.get("year_start") or date.get("year")),
                    as_int(date.get("year_end") or date.get("year")) or as_int(date.get("year_start") or date.get("year")),
                    place.get("historical_place"),
                    place.get("modern_place") or place.get("modern_city"),
                    place.get("province"),
                    as_float(place.get("lon")),
                    as_float(place.get("lat")),
                    str(record.get("background_summary") or record.get("story_summary") or ""),
                    context_source_id,
                    strongest_source_grade(composition_candidates),
                    confidence,
                ),
            )

        cur.execute(
            "INSERT INTO t_poem_background("
            "poem_id,background_summary,story_summary,historical_context,controversy_note,"
            "publication_ready,review_status,reviewers,reviewed_at,export_method"
            ") VALUES (%s,%s,%s,%s,%s,%s,'approved',%s,%s,%s) "
            "ON DUPLICATE KEY UPDATE background_summary=VALUES(background_summary),"
            "story_summary=VALUES(story_summary),historical_context=VALUES(historical_context),"
            "controversy_note=VALUES(controversy_note),publication_ready=VALUES(publication_ready),"
            "review_status='approved',reviewers=VALUES(reviewers),reviewed_at=VALUES(reviewed_at),"
            "export_method=VALUES(export_method)",
            (
                poem_id,
                str(record.get("background_summary") or ""),
                str(record.get("story_summary") or ""),
                json.dumps(record.get("historical_context") or [], ensure_ascii=False),
                str(record.get("controversy_note") or ""),
                1 if record.get("publication_ready") else 0,
                json.dumps(record.get("reviewers") or [], ensure_ascii=False),
                parse_datetime(record.get("reviewed_at")),
                str(record.get("method") or "approved_evidence_export_v1"),
            ),
        )

        cur.execute("DELETE FROM t_poem_line_note WHERE poem_id=%s", (poem_id,))
        for note in record.get("line_notes") or []:
            if not isinstance(note, dict):
                continue
            cur.execute(
                "INSERT INTO t_poem_line_note("
                "poem_id,line_no,original_text,translation_text,annotations,evidence_ids,review_status,reviewed_at"
                ") VALUES (%s,%s,%s,%s,%s,%s,'approved',%s)",
                (
                    poem_id,
                    as_int(note.get("line_no")) or 0,
                    str(note.get("original") or ""),
                    str(note.get("translation") or ""),
                    json.dumps(note.get("annotations") or [], ensure_ascii=False),
                    json.dumps(note.get("evidence_ids") or [], ensure_ascii=False),
                    parse_datetime(record.get("reviewed_at")),
                ),
            )

        for candidate_id, source_id in source_ids.items():
            candidate = approved_candidates.get(candidate_id)
            if not candidate:
                continue
            cur.execute(
                "INSERT INTO t_claim_evidence("
                "candidate_id,claim_type,subject_type,subject_id,predicate_name,object_text,source_id,"
                "source_locator,evidence_text,fact_grade,confidence,review_status,extraction_method,"
                "model_id,prompt_version,reviewer,reviewed_at"
                ") VALUES (%s,%s,'poem',%s,%s,%s,%s,%s,%s,%s,%s,'approved',%s,%s,%s,%s,%s) "
                "ON DUPLICATE KEY UPDATE claim_type=VALUES(claim_type),subject_type='poem',"
                "subject_id=VALUES(subject_id),predicate_name=VALUES(predicate_name),"
                "object_text=VALUES(object_text),source_id=VALUES(source_id),"
                "source_locator=VALUES(source_locator),evidence_text=VALUES(evidence_text),"
                "fact_grade=VALUES(fact_grade),confidence=VALUES(confidence),review_status='approved',"
                "extraction_method=VALUES(extraction_method),model_id=VALUES(model_id),"
                "prompt_version=VALUES(prompt_version),reviewer=VALUES(reviewer),"
                "reviewed_at=VALUES(reviewed_at)",
                (
                    candidate_id,
                    str(candidate.get("claim_type") or ""),
                    poem_id,
                    predicate_names.get(str(candidate.get("claim_type") or ""), "背景主张"),
                    candidate_value_text(candidate.get("value")),
                    source_id,
                    str(candidate.get("source_locator") or ""),
                    str(candidate.get("evidence_excerpt") or "")[:160],
                    str(candidate.get("source_grade") or "C").upper()[:1],
                    as_float(candidate.get("confidence"), 0.5),
                    str(candidate.get("extraction_method") or ""),
                    str(candidate.get("model_id") or "") or None,
                    str(candidate.get("prompt_version") or "") or None,
                    str(candidate.get("reviewer") or "") or None,
                    parse_datetime(candidate.get("reviewed_at")),
                ),
            )
            evidence_count += 1
        record_count += 1
    return record_count, evidence_count


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reset", action="store_true", help="删除并重建项目表")
    args = parser.parse_args()

    try:
        conn = pymysql.connect(**MYSQL)
    except pymysql.MySQLError as exc:
        hint = "；请设置 SHIXING_MYSQL_PASSWORD 环境变量" if not MYSQL.get("password") else ""
        raise SystemExit(f"无法连接 MySQL：{exc}{hint}") from exc

    try:
        with conn.cursor() as cur:
            mode = "重建主题表" if args.reset else "增量升级"
            print(f"[1/6] 执行 schema.sql（{mode}）...")
            run_schema(cur, reset=args.reset)
            cur.execute(f"USE {DB_NAME}")
            if not args.reset:
                migrate_existing_poem_table(cur)
                migrate_background_schema(cur)

            print("[2/6] 写入地名、意象和情感词典...")
            place_ids, image_ids, emotion_ids = load_dimensions(cur)
            print(
                f"      地名 {len(place_ids)} / 意象 {len(image_ids)} / "
                f"情感 {len(emotion_ids)}"
            )

            print("[3/6] 导入诗词及基础关联...")
            poet_ids, poem_ids, poem_hash_ids, poem_count = load_poems(cur, place_ids, image_ids)
            print(f"      诗人 {len(poet_ids)} / 爬虫记录 {poem_count}")

            print("[4/6] 导入审核后的生平与行旅节点...")
            event_count, stop_count = load_journeys(cur, poet_ids)
            print(f"      新增事件 {event_count} / 新增行旅节点 {stop_count}")

            print("[5/6] 导入审核后的作品创作时空...")
            context_count = load_contexts(cur, poem_ids)
            print(f"      创作背景记录 {context_count}")

            print("[6/6] 导入审核后富背景、译注与证据链...")
            rich_count, evidence_count = load_rich_backgrounds(cur, poem_ids, poem_hash_ids)
            print(f"      富背景 {rich_count} / 证据链 {evidence_count}")
            conn.commit()
            print("      [ok] 主题版数据库导入完成")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
