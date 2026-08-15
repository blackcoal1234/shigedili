"""DDBC/DILA 人名權威資料參考採集器（88 位詩人）。

本工具面向 DDBC Authority Web Services（DILA 佛學權威資料庫）的人名查詢端點，
為詩行萬里詩人語料補充「人名/朝代/生卒」參考識別記錄，並刻意與行旅管線解耦：
任何結果都停留在 ``data/candidates`` 候選層，出身地（birthPlace）僅作靜態參考，
永遠不會被寫入或路由為任何旅程事件。

允許輸出：
* data/candidates/poet_dila_person_matches.jsonl
* data/candidates/poet_dila_person_coverage.json
* .cache/background_sources/dila_person/**
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import socket
import ssl
import subprocess
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence


ROOT = Path(__file__).resolve().parent.parent
POEMS_JSON = ROOT / "data" / "poems.json"
CANDIDATE_DIR = ROOT / "data" / "candidates"
CACHE_DIR = ROOT / ".cache" / "background_sources" / "dila_person"

MATCHES_JSONL = CANDIDATE_DIR / "poet_dila_person_matches.jsonl"
COVERAGE_JSON = CANDIDATE_DIR / "poet_dila_person_coverage.json"

SCHEMA_VERSION = 1
PARSER_VERSION = "dila-person-reference-v1"
EXPECTED_ROSTER_SIZE = 88

DILA_SOURCE_NAME = "DDBC Authority Web Services (DILA 佛學權威資料庫)"
DILA_API_DOCS_URL = "https://authority.dila.edu.tw/docs/services/person_query.php"
ENDPOINT = "https://authority.dila.edu.tw/webwidget/getAuthorityData.php"
DILA_CALLBACK = "shixing_dila_cb"
DILA_OPEN_CONTENT_URL = "https://authority.dila.edu.tw/docs/open_content/"
DILA_CC_LICENSE = "CC BY-SA 2.5 台灣 (CC BY-SA 2.5 TW)"
DILA_CC_LICENSE_URL = "https://creativecommons.org/licenses/by-sa/2.5/tw/"
DILA_LICENSE_NOTE = (
    "來源為 DDBC Authority 開放內容（Open Content）：" + DILA_OPEN_CONTENT_URL + "；"
    "官方授權為 " + DILA_CC_LICENSE + "（" + DILA_CC_LICENSE_URL + "）。"
    "person_query 說明頁本身未再逐條重申每筆記錄之授權條款，使用前請以 Open Content 頁面為準。"
    "本工具僅作人名/朝代/生卒參考識別，不作行年或路線證據。"
)

RETRYABLE_STATUS = frozenset({408, 429})
# 只有真正新取得（fetched）或離線顯式命中（cache_hit）的響應才允許替換所選詩人的既有記錄。
# fetch_failed_cache_used 是網絡失敗＋陳舊緩存，不得僅因緩存體可解析就清掉舊候選或覆寫先前狀態。
FRESH_REPLACE_STATUSES = frozenset({"fetched", "cache_hit"})


def is_retryable_status(code: int | None) -> bool:
    if code is None:
        return False
    return code in RETRYABLE_STATUS or 500 <= code <= 599
DILA_HOST = "authority.dila.edu.tw"
_NO_DYNASTY_TOKENS = frozenset({"沒有給定朝代", "没有给定朝代", "不詳", "不详", "無朝代"})
ROUTE_EVENT_FIELDS = frozenset(
    {
        "event_type",
        "event_year",
        "year_start",
        "year_end",
        "lon",
        "lat",
        "longitude",
        "latitude",
        "historical_place",
        "place_code",
        "route",
        "journey",
        "coordinates",
        "location",
    }
)

# 詩人名字的簡→繁對照（僅涵蓋語料內 88 位詩人會用到的字，保持對照可預測且精確）。
_S2T = {
    "仪": "儀", "刘": "劉", "庄": "莊", "锡": "錫", "卢": "盧", "纶": "綸",
    "叶": "葉", "梦": "夢", "吕": "呂", "吴": "吳", "问": "問",
    "参": "參", "张": "張", "龄": "齡", "干": "幹", "继": "繼",
    "巩": "鞏", "隐": "隱", "贺": "賀", "鹤": "鶴", "杨": "楊", "万": "萬",
    "亿": "億", "尧": "堯", "欧": "歐", "阳": "陽", "温": "溫", "涣": "渙",
    "维": "維", "罗": "羅", "聂": "聶", "苏": "蘇", "轼": "軾", "辙": "轍",
    "浑": "渾", "观": "觀", "铸": "鑄", "贾": "賈", "岛": "島",
    "钱": "錢", "陆": "陸", "渊": "淵", "陈": "陳", "与": "與", "义": "義",
    "韦": "韋", "应": "應", "韩": "韓", "骆": "駱", "宾": "賓", "适": "適",
    "黄": "黃", "弃": "棄", "许": "許", "彦": "彥", "坚": "堅", "咏": "詠",
}
_T2S = {traditional: simplified for simplified, traditional in _S2T.items()}
_S2T_TABLE = str.maketrans(_S2T)
_T2S_TABLE = str.maketrans(_T2S)

# 詩人通說生卒參考年限（公曆），僅用於同名/同姓候選的生卒重疊消歧評分，
# 不是行年、路線或事實證據。與 data/candidates/poet_birth_years.json 中已核實的六人一致。
KNOWN_LIFE_SPANS: dict[str, tuple[int, int]] = {
    "白居易": (772, 846), "王维": (701, 761), "李白": (701, 762), "孟浩然": (689, 740),
    "杜甫": (712, 770), "高适": (704, 765), "李商隐": (813, 858), "王昌龄": (698, 757),
    "岑参": (715, 770), "杜牧": (803, 852), "王之涣": (688, 742), "刘禹锡": (772, 842),
    "柳宗元": (773, 819), "韩愈": (768, 824), "王勃": (650, 676), "李贺": (790, 816),
    "骆宾王": (619, 687), "陈子昂": (659, 700), "张九龄": (678, 740), "贺知章": (659, 744),
    "元稹": (779, 831), "张志和": (730, 810), "韦应物": (737, 792), "常建": (708, 765),
    "张继": (715, 779), "祖咏": (699, 746), "韦庄": (836, 910), "李煜": (937, 978),
    "温庭筠": (812, 870), "许浑": (791, 858), "罗隐": (833, 910), "杜荀鹤": (846, 904),
    "皮日休": (838, 883), "聂夷中": (837, 884), "司空曙": (720, 790), "卢纶": (739, 799),
    "钱起": (710, 782), "李益": (746, 829), "孟郊": (751, 814), "贾岛": (779, 843),
    "张籍": (766, 830), "王建": (767, 830), "沈佺期": (656, 714), "宋之问": (656, 712),
    "上官仪": (608, 664), "苏轼": (1037, 1101), "辛弃疾": (1140, 1207), "陆游": (1125, 1210),
    "李清照": (1084, 1155), "欧阳修": (1007, 1072), "王安石": (1021, 1086), "黄庭坚": (1045, 1105),
    "范成大": (1126, 1193), "杨万里": (1127, 1206), "尤袤": (1127, 1194), "柳永": (987, 1053),
    "晏殊": (991, 1055), "晏几道": (1038, 1110), "秦观": (1049, 1100), "周邦彦": (1056, 1121),
    "姜夔": (1155, 1221), "吴文英": (1200, 1260), "张炎": (1248, 1320), "陈与义": (1090, 1138),
    "文天祥": (1236, 1283), "范仲淹": (989, 1052), "司马光": (1019, 1086), "朱熹": (1130, 1200),
    "林逋": (967, 1028), "梅尧臣": (1002, 1060), "苏辙": (1039, 1112), "苏洵": (1009, 1066),
    "张孝祥": (1132, 1170), "曾巩": (1019, 1083), "张元干": (1091, 1170), "陈亮": (1143, 1194),
    "刘克庄": (1187, 1269), "叶梦得": (1077, 1148), "贺铸": (1052, 1125), "张先": (990, 1078),
    "欧阳炯": (896, 971), "朱淑真": (1135, 1180), "程颢": (1032, 1085), "陆九渊": (1139, 1193),
    "吕本中": (1084, 1145), "杨亿": (974, 1020), "钱惟演": (977, 1034), "石延年": (994, 1041),
}

# 朝代相容族：本地標籤「唐」「宋」與 DILA 粗粒度朝代之間的相容集合（僅用於評分）。
_DYNASTY_FAMILIES = {
    "唐": frozenset(
        {
            "唐", "唐末", "五代", "五代十國", "五代十国", "南唐", "後唐", "後梁", "後晉", "後漢", "後周",
            "吳越", "南漢", "前蜀", "後蜀", "閩", "荊南", "楚",
        }
    ),
    "宋": frozenset({"宋", "北宋", "南宋"}),
}

NAME_SCORE = {
    "exact_name": 100,
    "traditional_alias": 90,
    "simplified_alias": 90,
    "mixed_simplified_traditional_alias": 85,
    "record_alias_matches_poet": 75,
    "names_field_alias": 70,
    "substring": 20,
}
DYNASTY_SCORE = {"exact": 50, "compatible": 40, "unknown": 0, "mismatch": -60}
CREDIBLE_NAME_METHODS = frozenset(
    {
        "exact_name",
        "traditional_alias",
        "simplified_alias",
        "mixed_simplified_traditional_alias",
        "record_alias_matches_poet",
        "names_field_alias",
    }
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_name(value: object) -> str:
    return unicodedata.normalize("NFC", str(value or "")).strip().replace(" ", "")


def simplified_name(value: object) -> str:
    return normalize_name(value).translate(_T2S_TABLE)


def traditional_name(value: object) -> str:
    return normalize_name(value).translate(_S2T_TABLE)


def aliases_for_name(value: object) -> tuple[str, ...]:
    name = normalize_name(value)
    if not name:
        return ()
    variants = sorted({name, traditional_name(name), simplified_name(name)})
    return tuple(dict.fromkeys(v for v in variants if v))


def name_match_method(local_name: str, source_name: str) -> str | None:
    local = normalize_name(local_name)
    source = normalize_name(source_name)
    if not source:
        return None
    if source == local:
        return "exact_name"
    if source == traditional_name(local):
        return "traditional_alias"
    if source == simplified_name(local):
        return "simplified_alias"
    if simplified_name(source) == simplified_name(local):
        return "mixed_simplified_traditional_alias"
    return None


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def stable_id(*parts: object) -> str:
    raw = json.dumps(parts, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def canonical_json(value: object, *, pretty: bool = False) -> str:
    if pretty:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        with tmp.open("wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def atomic_write_text(path: Path, text: str) -> None:
    atomic_write_bytes(path, text.encode("utf-8"))


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    payload = "".join(canonical_json(row) + "\n" for row in rows)
    atomic_write_text(path, payload)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig") as handle:
        for line_no, raw in enumerate(handle, 1):
            line = raw.strip()
            if not line:
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_no}: expected a JSON object")
            rows.append(value)
    return rows


def read_coverage(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    return value if isinstance(value, dict) else None


@dataclass(frozen=True)
class PoetSpec:
    name: str
    dynasty: str
    poem_count: int
    dynasty_counts: tuple[tuple[str, int], ...] = ()
    dynasty_resolution: str = "single_local_label"


@dataclass(frozen=True)
class LifeSpan:
    birth: tuple[int, int] | None = None
    death: tuple[int, int] | None = None


@dataclass(frozen=True)
class DilaRecord:
    authorityID: str
    name: str
    dynasty: str
    born_begin: str
    born_end: str
    died_begin: str
    died_end: str
    birth_place_code: str
    birth_place_name: str
    death_place_code: str
    death_place_name: str
    note: str
    note_full: str
    aliases: tuple[str, ...]
    lang: str
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def born_years(self) -> tuple[int, int] | None:
        years = [year for year in (parse_year(self.born_begin), parse_year(self.born_end)) if year is not None]
        return (min(years), max(years)) if years else None

    @property
    def died_years(self) -> tuple[int, int] | None:
        years = [year for year in (parse_year(self.died_begin), parse_year(self.died_end)) if year is not None]
        return (min(years), max(years)) if years else None

    @property
    def life_years(self) -> tuple[int, int] | None:
        born, died = self.born_years, self.died_years
        if born is None and died is None:
            return None
        start = born[0] if born else died[0]
        end = died[1] if died else born[1]
        if start is None or end is None:
            return None
        return (start, end)

    @property
    def dynasty_tokens(self) -> tuple[str, ...]:
        return tuple(token for token in _split_dynasty(self.dynasty) if token)


@dataclass(frozen=True)
class FetchResult:
    poet: str
    query_url: str
    usable: bool
    attempt_status: str
    body: bytes = b""
    content_sha256: str = ""
    retrieved_at: str = ""
    from_cache: bool = False
    http_status: int | None = None
    error: str = ""
    retry_count: int = 0
    retry_waits: tuple[float, ...] = ()
    cache_path: str = ""
    row_metadata: dict[str, Any] = field(default_factory=dict)


def parse_year(value: object) -> int | None:
    if value is None:
        return None
    match = re.search(r"([+-]?\d{1,6})", str(value))
    if not match:
        return None
    return int(match.group(1))


def _split_dynasty(value: object) -> list[str]:
    raw = str(value or "").strip()
    return [token.strip() for token in re.split(r"[;；,，、\s]+", raw) if token.strip()]


_LANG_TAG = re.compile(r"\[[^\]]*\]\s*")


def parse_names_field(value: object) -> tuple[str, ...]:
    text = str(value or "").strip()
    if not text:
        return ()
    if text.startswith("["):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                text = ",".join(str(item) for item in parsed)
        except (ValueError, TypeError):
            pass
    text = _LANG_TAG.sub("，", text)
    tokens = [normalize_name(token) for token in re.split(r"[,，、;；\r\n]+", text)]
    return tuple(sorted(dict.fromkeys(token for token in tokens if token)))


def parse_jsonp(raw: bytes | str) -> tuple[str, dict[str, Any]]:
    text = raw if isinstance(raw, str) else raw.decode("utf-8-sig")
    text = text.strip()
    if text.startswith("{") or text.startswith("null"):
        # 官方端點在省略 jsoncallback 時會直接輸出裸 JSON object 或字面 null。
        payload = json.loads(text)
        if payload is None:
            payload = {}
        if not isinstance(payload, dict):
            raise ValueError("JSONP payload is not an object")
        return "", payload
    first = text.find("(")
    if first == -1:
        raise ValueError("response is neither JSONP with a callback wrapper nor a JSON object")
    callback = text[:first].strip()
    inner = text[first + 1:].rstrip()
    inner = inner.rstrip("; \t\r\n")
    if inner.endswith(")"):
        inner = inner[:-1]
    inner = inner.rstrip()
    payload = json.loads(inner)
    if payload is None:
        # 零結果：服務以字面 null 返回（HTTP 200），按無記錄處理。
        payload = {}
    if not isinstance(payload, dict):
        raise ValueError("JSONP payload is not an object")
    return callback, payload


def _record_from_dict(raw: dict[str, Any]) -> DilaRecord:
    name = normalize_name(raw.get("name"))
    return DilaRecord(
        authorityID=str(raw.get("authorityID") or "").strip(),
        name=name or str(raw.get("name") or "").strip(),
        dynasty=str(raw.get("dynasty") or "").strip(),
        born_begin=str(raw.get("bornDateBegin") or "").strip(),
        born_end=str(raw.get("bornDateEnd") or "").strip(),
        died_begin=str(raw.get("diedDateBegin") or "").strip(),
        died_end=str(raw.get("diedDateEnd") or "").strip(),
        birth_place_code=str(raw.get("birthPlaceCode") or "").strip(),
        birth_place_name=str(raw.get("birthPlaceName") or "").strip(),
        death_place_code=str(raw.get("deathPlaceCode") or "").strip(),
        death_place_name=str(raw.get("deathPlaceName") or "").strip(),
        note=str(raw.get("note") or "").strip(),
        note_full=str(raw.get("noteFull") or "").strip(),
        aliases=parse_names_field(raw.get("names")),
        lang=str(raw.get("lang") or "").strip(),
        raw=dict(raw),
    )


def person_records_from_payload(payload: dict[str, Any]) -> tuple[list[DilaRecord], dict[str, Any]]:
    data_keys = sorted(
        (key for key in payload if re.fullmatch(r"data\d+", str(key))),
        key=lambda key: int(str(key)[4:]),
    )
    row_metadata = {key: value for key, value in payload.items() if not re.fullmatch(r"data\d+", str(key))}
    records: list[DilaRecord] = []
    for key in data_keys:
        value = payload[key]
        if not isinstance(value, dict):
            continue
        record = _record_from_dict(value)
        if record.name:
            records.append(record)
    return records, row_metadata


def dynasty_match_kind(poet_dynasty: str, record_tokens: Sequence[str]) -> str:
    family = _DYNASTY_FAMILIES.get(poet_dynasty, frozenset())
    tokens = [token for token in record_tokens if token not in _NO_DYNASTY_TOKENS]
    if not tokens:
        return "unknown"
    for token in record_tokens:
        if token == poet_dynasty:
            return "exact"
    for token in record_tokens:
        if token in family:
            return "compatible"
    return "mismatch"


# 本地通說生卒年為近似值；與 DILA 生卒區間分開比較時，各放寬 ±LOCAL_YEAR_TOLERANCE 年的窗口，
# 避免「通說與權威範圍差一兩年」被誤判為硬性矛盾。仍保持生年/卒年分開比較，不做並集重疊。
LOCAL_YEAR_TOLERANCE = 3


def local_life_years(poet_name: str) -> LifeSpan | None:
    span = KNOWN_LIFE_SPANS.get(normalize_name(poet_name))
    if span is None:
        return None
    birth, death = span
    return LifeSpan(
        birth=(birth - LOCAL_YEAR_TOLERANCE, birth + LOCAL_YEAR_TOLERANCE),
        death=(death - LOCAL_YEAR_TOLERANCE, death + LOCAL_YEAR_TOLERANCE),
    )


def sanitize_note(value: object, limit: int = 300) -> str:
    text = str(value or "").strip()
    text = re.sub(r"<[^>]*>", "", text)
    text = (
        text.replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
    )
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def _overlap_years(record_years: tuple[int, int], local_span: tuple[int, int]) -> int:
    start = max(record_years[0], local_span[0])
    end = min(record_years[1], local_span[1])
    return max(0, end - start + 1)


def score_date(record: DilaRecord, local_life: LifeSpan | None) -> dict[str, Any]:
    """生卒分開比較：出生區間對本地生年、卒年區間對本地卒年。

    不可用（任一方 unknown）保持中性；任何已知配對重疊為 0 即視為硬性矛盾（取消資格）。
    用生卒並集重疊會對「生年不合、卒年不合但並集有交集」的候選產生虛假加分，因此分開比較。
    """
    parts: dict[str, int] = {}
    if local_life is not None:
        if record.born_years is not None and local_life.birth is not None:
            parts["birth"] = _overlap_years(record.born_years, local_life.birth)
        if record.died_years is not None and local_life.death is not None:
            parts["death"] = _overlap_years(record.died_years, local_life.death)
    if not parts:
        return {"date_score": 0, "date_known": False, "date_contradiction": False, "overlap_parts": parts}
    if any(value == 0 for value in parts.values()):
        return {"date_score": -90, "date_known": True, "date_contradiction": True, "overlap_parts": parts}
    total = sum(parts.values())
    return {"date_score": 40 + min(total, 20), "date_known": True, "date_contradiction": False, "overlap_parts": parts}


def score_candidate(
    poet: PoetSpec,
    record: DilaRecord,
    local_life: LifeSpan | None,
) -> dict[str, Any] | None:
    method = name_match_method(poet.name, record.name)
    if method is None:
        if poet.name in record.aliases or simplified_name(poet.name) in record.aliases:
            method = "record_alias_matches_poet"
        elif (
            poet.name in record.name
            or traditional_name(poet.name) in record.name
            or simplified_name(poet.name) in simplified_name(record.name)
        ):
            method = "substring"
        else:
            return None
    name_score = NAME_SCORE.get(method, 20)

    dk = dynasty_match_kind(poet.dynasty, record.dynasty_tokens)
    dynasty_score = DYNASTY_SCORE[dk]

    date = score_date(record, local_life)
    total = name_score + dynasty_score + date["date_score"]
    return {
        "record": record,
        "name_method": method,
        "name_score": name_score,
        "dynasty_kind": dk,
        "dynasty_score": dynasty_score,
        "date_score": date["date_score"],
        "date_known": date["date_known"],
        "date_contradiction": date["date_contradiction"],
        "date_overlap_parts": date["overlap_parts"],
        "record_born_years": record.born_years,
        "record_died_years": record.died_years,
        "local_birth_years": local_life.birth if local_life else None,
        "local_death_years": local_life.death if local_life else None,
        "total": total,
        "credible": method in CREDIBLE_NAME_METHODS and not date["date_contradiction"],
    }


def build_match_row(
    poet: PoetSpec,
    score: dict[str, Any],
    *,
    selected: bool,
    outcome: str,
    result: FetchResult,
    row_metadata: dict[str, Any],
) -> dict[str, Any]:
    record: DilaRecord = score["record"]
    born_years = record.born_years
    died_years = record.died_years
    return {
        "schema_version": SCHEMA_VERSION,
        "parser_version": PARSER_VERSION,
        "record_type": "poet_dila_person_match",
        "reference_id": stable_id("dila", poet.name, poet.dynasty, record.authorityID, record.name),
        "poet": poet.name,
        "dynasty": poet.dynasty,
        "poem_count": poet.poem_count,
        "poet_status": outcome,
        "match_status": "matched" if selected else "ambiguous",
        "selected": selected,
        "match_method": score["name_method"],
        "match_score": {
            "name": score["name_score"],
            "dynasty": score["dynasty_score"],
            "date": score["date_score"],
            "total": score["total"],
        },
        "dynasty_match": score["dynasty_kind"],
        "date_overlap": {
            "overlap_parts": score["date_overlap_parts"],
            "date_known": score["date_known"],
            "date_contradiction": score["date_contradiction"],
            "record_born_years": list(score["record_born_years"]) if score["record_born_years"] else None,
            "record_died_years": list(score["record_died_years"]) if score["record_died_years"] else None,
            "local_birth_years": list(score["local_birth_years"]) if score["local_birth_years"] else None,
            "local_death_years": list(score["local_death_years"]) if score["local_death_years"] else None,
        },
        "authorityID": record.authorityID,
        "canonical_name": record.name,
        "aliases": list(record.aliases),
        "record_dynasty": record.dynasty,
        "born_range": {
            "begin": record.born_begin,
            "end": record.born_end,
            "years": list(born_years) if born_years else None,
        },
        "died_range": {
            "begin": record.died_begin,
            "end": record.died_end,
            "years": list(died_years) if died_years else None,
        },
        "birth_place": {"code": record.birth_place_code, "name": record.birth_place_name},
        "death_place": {"code": record.death_place_code, "name": record.death_place_name},
        "birthplace_reference_only": True,
        "note": sanitize_note(record.note),
        "source": DILA_SOURCE_NAME,
        "endpoint": ENDPOINT,
        "source_url": result.query_url,
        "license_note": DILA_LICENSE_NOTE,
        "content_sha256": result.content_sha256,
        "accessed_at": result.retrieved_at,
        "from_cache": result.from_cache,
        "http_status": result.http_status,
        "attempt_status": result.attempt_status,
        "retry_count": result.retry_count,
        "row_metadata": dict(row_metadata) if row_metadata else {},
    }


def select_for_poet(
    poet: PoetSpec,
    records: Sequence[DilaRecord],
    result: FetchResult,
    local_life: LifeSpan | None,
    row_metadata: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], str]:
    metadata = row_metadata or {}
    scored = [
        score
        for record in records
        for score in [score_candidate(poet, record, local_life)]
        if score is not None
    ]
    if not scored:
        return [], "not_found"
    scored.sort(key=lambda item: (-item["total"], item["record"].authorityID, item["record"].name))
    credible = [item for item in scored if item["credible"]]
    if credible:
        top_score = max(item["total"] for item in credible)
        winners = [item for item in credible if item["total"] == top_score]
        if len(winners) == 1:
            selected = winners[0]
            outcome = "matched"
        else:
            selected = None
            outcome = "ambiguous"
    else:
        selected = None
        outcome = "ambiguous"

    rows: list[dict[str, Any]] = []
    for item in scored:
        rows.append(
            build_match_row(
                poet,
                item,
                selected=(item is selected),
                outcome=outcome,
                result=result,
                row_metadata=metadata,
            )
        )
    return rows, outcome


def load_roster(path: Path = POEMS_JSON) -> list[PoetSpec]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, list):
        raise ValueError(f"{path} must contain a JSON array")
    counts: Counter[tuple[str, str]] = Counter()
    dynasties: dict[str, set[str]] = defaultdict(set)
    for poem in payload:
        if not isinstance(poem, dict):
            continue
        poet = normalize_name(poem.get("poet") or poem.get("author"))
        dynasty = normalize_name(poem.get("dynasty"))
        if not poet or not dynasty:
            continue
        counts[(poet, dynasty)] += 1
        dynasties[poet].add(dynasty)
    roster: list[PoetSpec] = []
    for poet, values in dynasties.items():
        local_counts = tuple(sorted(((dynasty, counts[(poet, dynasty)]) for dynasty in values)))
        ranked = sorted(local_counts, key=lambda item: (-item[1], item[0]))
        if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
            raise ValueError(f"poet has tied local dynasty labels: {poet}: {dict(local_counts)}")
        chosen = ranked[0][0]
        roster.append(
            PoetSpec(
                name=poet,
                dynasty=chosen,
                poem_count=sum(value for _dynasty, value in local_counts),
                dynasty_counts=local_counts,
                dynasty_resolution="single_local_label" if len(local_counts) == 1 else "majority_local_label",
            )
        )
    return sorted(roster, key=lambda item: (item.dynasty, item.name))


def resolve_selection(roster: Sequence[PoetSpec], scope: str, poets_arg: str | None) -> list[str]:
    available = {item.name for item in roster}
    if poets_arg is not None:
        requested: list[str] = []
        for raw in re.split(r"[,，]", poets_arg):
            poet = normalize_name(raw)
            if poet and poet not in requested:
                requested.append(poet)
        if not requested:
            raise ValueError("--poets did not contain a poet name")
        unknown = [poet for poet in requested if poet not in available]
        if unknown:
            raise ValueError(f"unknown poet(s): {', '.join(unknown)}")
        return requested
    if scope == "core":
        missing = [poet for poet in ("李白", "杜甫", "白居易", "苏轼", "陆游", "李清照") if poet not in available]
        if missing:
            raise ValueError(f"core poet(s) absent from corpus: {', '.join(missing)}")
        return ["李白", "杜甫", "白居易", "苏轼", "陆游", "李清照"]
    if scope == "all":
        return [item.name for item in roster]
    raise ValueError("scope must be core or all")


def person_query_url(name: str, callback: str = DILA_CALLBACK) -> str:
    query = urllib.parse.urlencode({"type": "person", "id": name, "jsoncallback": callback})
    return f"{ENDPOINT}?{query}"


class CacheStore:
    """Content-addressed bodies plus an atomic URL pointer with checksum."""

    def __init__(self, root: Path = CACHE_DIR) -> None:
        self.root = root
        self.body_dir = root / "bodies"
        self.meta_dir = root / "meta"

    @staticmethod
    def url_key(url: str) -> str:
        return hashlib.sha256(url.encode("utf-8")).hexdigest()

    def meta_path(self, url: str) -> Path:
        return self.meta_dir / f"{self.url_key(url)}.json"

    def read(self, url: str) -> tuple[bytes | None, dict[str, Any] | None, str]:
        meta_path = self.meta_path(url)
        if not meta_path.exists():
            return None, None, "cache_miss"
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if not isinstance(meta, dict) or meta.get("url") != url:
                return None, None, "cache_metadata_invalid"
            body_name = str(meta.get("body_file") or "")
            if not re.fullmatch(r"[0-9a-f]{64}\.bin", body_name):
                return None, None, "cache_metadata_invalid"
            body_path = self.body_dir / body_name
            body = body_path.read_bytes()
            digest = sha256_bytes(body)
            if digest != meta.get("sha256") or len(body) != int(meta.get("bytes", -1)):
                return None, None, "cache_checksum_mismatch"
            return body, meta, "cache_hit"
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return None, None, "cache_invalid"

    def store(
        self,
        url: str,
        body: bytes,
        *,
        retrieved_at: str,
        content_type: str = "",
        http_status: int = 200,
    ) -> dict[str, Any]:
        digest = sha256_bytes(body)
        body_name = f"{digest}.bin"
        body_path = self.body_dir / body_name
        if not body_path.exists() or sha256_bytes(body_path.read_bytes()) != digest:
            atomic_write_bytes(body_path, body)
        meta = {
            "schema_version": SCHEMA_VERSION,
            "url": url,
            "sha256": digest,
            "bytes": len(body),
            "body_file": body_name,
            "retrieved_at": retrieved_at,
            "content_type": content_type,
            "http_status": http_status,
        }
        atomic_write_text(self.meta_path(url), canonical_json(meta, pretty=True))
        return meta


def _backoff_seconds(attempt: int) -> float:
    return min(15.0, 1.5 * (2 ** attempt))


def _cert_verify_failed(exc: urllib.error.URLError) -> bool:
    reason = getattr(exc, "reason", None)
    if isinstance(reason, ssl.SSLCertVerificationError):
        return True
    text = str(reason or exc)
    return "CERTIFICATE_VERIFY_FAILED" in text or "certificate verify failed" in text.lower()


def _is_dila_host(url: str) -> bool:
    host = urllib.parse.urlparse(url).netloc.split(":")[0].lower()
    return host == DILA_HOST


class _DilaHostRedirectHandler(urllib.request.HTTPRedirectHandler):
    """僅允許 authority.dila.edu.tw 同主機重定向的 redirect handler。

    用在「未驗證 context」的 SSL 回退路徑上：若伺服器把請求重定向到其他主機，
    直接拋出 URLError 中止，絕不讓未驗證的 context 跟隨到非 DILA 主機。
    同主機（authority.dila.edu.tw）重定向則正常放行。
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not _is_dila_host(newurl):
            raise urllib.error.URLError(
                f"redirect blocked: {newurl} is not on allowed host {DILA_HOST}"
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def open_dila_with_ssl_fallback(
    opener: Callable[..., Any],
    request: Any,
    timeout: float | None = None,
    context: Any = None,
) -> Any:
    """對 authority.dila.edu.tw 的窄範圍 SSL 回退。

    官方端點僅在 TLS 憑證校驗因 Missing Subject Key Identifier 失敗時，
    對同一主機再用未驗證 context 重試一次；不全局關閉 SSL，
    也不對其他任何主機啟用回退。回退路徑使用 ``_DilaHostRedirectHandler``，
    任何指向非 authority.dila.edu.tw 主機的重定向都會被拒絕（永不跟隨）。
    """
    try:
        return opener(request, timeout=timeout)
    except urllib.error.URLError as exc:
        if _cert_verify_failed(exc) and _is_dila_host(request.full_url):
            return opener(request, timeout=timeout, context=context or ssl._create_unverified_context())
        raise


def default_opener(request: Any, timeout: float | None = None, context: Any = None) -> Any:
    if context is not None:
        opener = urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=context),
            _DilaHostRedirectHandler(),
        )
        return opener.open(request, timeout=timeout)
    return urllib.request.urlopen(request, timeout=timeout)


def _retry_wait(headers: Any, attempt: int) -> float:
    if headers is not None and hasattr(headers, "get"):
        raw = headers.get("Retry-After")
        if raw:
            try:
                seconds = float(raw)
            except (TypeError, ValueError):
                seconds = None
            if seconds is not None and seconds >= 0:
                return min(60.0, seconds)
    return _backoff_seconds(attempt)


class DilaFetcher:
    def __init__(
        self,
        cache: CacheStore,
        *,
        offline: bool = False,
        timeout: float = 45.0,
        retries: int = 2,
        delay_min: float = 5.0,
        delay_max: float = 8.0,
        opener: Callable[..., Any] | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        rng: Any = random,
        clock: Callable[[], str] = utc_now,
    ) -> None:
        self.cache = cache
        self.offline = offline
        self.timeout = timeout
        self.retries = retries
        self.delay_min = delay_min
        self.delay_max = delay_max
        self.opener = opener or default_opener
        self.sleeper = sleeper
        self.rng = rng
        self.clock = clock

    def fetch(self, query_url: str, poet: str) -> FetchResult:
        cached_body, cached_meta, cache_status = self.cache.read(query_url)
        if self.offline:
            if cached_body is None or cached_meta is None:
                return FetchResult(
                    poet, query_url, False, "fetch_failed",
                    error=cache_status,
                )
            return FetchResult(
                poet, query_url, True, "cache_hit",
                body=cached_body,
                content_sha256=str(cached_meta["sha256"]),
                retrieved_at=str(cached_meta["retrieved_at"]),
                from_cache=True,
                http_status=int(cached_meta.get("http_status") or 200),
                cache_path=str(self.cache.meta_path(query_url)),
            )

        last_error = "network_failure"
        last_status: int | None = None
        waits: list[float] = []
        response: Any = None
        for attempt in range(self.retries + 1):
            try:
                request = urllib.request.Request(
                    query_url,
                    headers={
                        "User-Agent": "PoemJourneyDilaPersonReference/1.0 (+research; DILA authority web service)",
                        "Accept": "application/json,text/plain;q=0.9,*/*;q=0.5",
                    },
                )
                # DILA currently serves a certificate chain that Python 3.14
                # rejects for a missing Subject Key Identifier. Keep the
                # narrowly scoped, same-host-only fallback in the live fetch
                # path rather than leaving it as an unused helper.
                response = open_dila_with_ssl_fallback(
                    self.opener,
                    request,
                    timeout=self.timeout,
                )
                last_status = int(getattr(response, "status", 200) or 200)
                body = response.read()
                if last_status != 200 or not body:
                    raise OSError(f"HTTP {last_status} or empty body")
                retrieved_at = self.clock()
                headers = getattr(response, "headers", None)
                content_type = str(headers.get("Content-Type", "")) if hasattr(headers, "get") else ""
                meta = self.cache.store(
                    query_url,
                    body,
                    retrieved_at=retrieved_at,
                    content_type=content_type,
                    http_status=last_status,
                )
                return FetchResult(
                    poet, query_url, True, "fetched",
                    body=body,
                    content_sha256=str(meta["sha256"]),
                    retrieved_at=retrieved_at,
                    from_cache=False,
                    http_status=last_status,
                    retry_count=len(waits),
                    retry_waits=tuple(waits),
                    cache_path=str(self.cache.meta_path(query_url)),
                )
            except urllib.error.HTTPError as exc:
                last_status = int(exc.code)
                last_error = f"HTTP {exc.code}"
                try:
                    exc.close()
                except Exception:
                    pass
                if not is_retryable_status(exc.code) or attempt >= self.retries:
                    break
                wait = _retry_wait(exc.headers, attempt)
                waits.append(wait)
                self.sleeper(wait)
            except (TimeoutError, socket.timeout) as exc:
                last_error = f"TimeoutError: {exc}"
                if attempt >= self.retries:
                    break
                wait = _backoff_seconds(attempt)
                waits.append(wait)
                self.sleeper(wait)
            except urllib.error.URLError as exc:
                last_error = f"URLError: {exc}"
                if attempt >= self.retries:
                    break
                wait = _backoff_seconds(attempt)
                waits.append(wait)
                self.sleeper(wait)
            except OSError as exc:
                last_error = f"OSError: {exc}"
                if not is_retryable_status(last_status) or attempt >= self.retries:
                    break
                wait = _backoff_seconds(attempt)
                waits.append(wait)
                self.sleeper(wait)
            finally:
                if response is not None:
                    try:
                        response.close()
                    except Exception:
                        pass

        if cached_body is not None and cached_meta is not None:
            return FetchResult(
                poet, query_url, True, "fetch_failed_cache_used",
                body=cached_body,
                content_sha256=str(cached_meta["sha256"]),
                retrieved_at=str(cached_meta["retrieved_at"]),
                from_cache=True,
                http_status=last_status,
                error=last_error,
                retry_count=len(waits),
                retry_waits=tuple(waits),
                cache_path=str(self.cache.meta_path(query_url)),
            )
        return FetchResult(
            poet, query_url, False, "fetch_failed",
            http_status=last_status,
            error=last_error,
            retry_count=len(waits),
            retry_waits=tuple(waits),
        )

    def fetch_all(self, urls: Sequence[str], poets: Sequence[str] | None = None) -> list[FetchResult]:
        if poets is None:
            poets = list(urls)
        results: list[FetchResult] = []
        for index, url in enumerate(urls):
            results.append(self.fetch(url, poets[index]))
            if index + 1 < len(urls) and not self.offline:
                wait = self.rng.uniform(self.delay_min, self.delay_max)
                self.sleeper(wait)
        return results


def resolve_run_plan(
    selected_poets: Sequence[str],
    existing_rows: Sequence[dict[str, Any]],
    resume: bool,
) -> tuple[list[str], list[str]]:
    existing_by_poet: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in existing_rows:
        existing_by_poet[str(row.get("poet") or "")].append(row)
    to_fetch: list[str] = []
    resumed: list[str] = []
    for poet in selected_poets:
        rows = existing_by_poet.get(poet, [])
        if resume and rows and any(str(row.get("match_status")) in {"matched", "ambiguous"} for row in rows):
            resumed.append(poet)
        else:
            to_fetch.append(poet)
    return to_fetch, resumed


def attempt_record(result: FetchResult, row_metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        "query_url": result.query_url,
        "attempt_status": result.attempt_status,
        "usable": result.usable,
        "from_cache": result.from_cache,
        "http_status": result.http_status,
        "retry_count": result.retry_count,
        "retry_waits": list(result.retry_waits),
        "content_sha256": result.content_sha256,
        "accessed_at": result.retrieved_at,
        "cache_path": result.cache_path,
        "error": result.error,
        "row_metadata": dict(row_metadata) if row_metadata else {},
    }


def dila_sort_key(row: dict[str, Any]) -> tuple[str, ...]:
    return (
        str(row.get("dynasty") or ""),
        str(row.get("poet") or ""),
        str(row.get("authorityID") or ""),
        str(row.get("reference_id") or ""),
    )


def merge_matches(
    existing: Sequence[dict[str, Any]],
    fresh_by_poet: dict[str, list[dict[str, Any]]],
    replaced_poets: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    """合併舊行與本次新行。

    ``replaced_poets`` 為「本次成功解析」的詩人集合（顯式傳入，而非由新行是否為空推斷）：
    成功解析為 not_found（新行為空）也必須清掉該詩人的陳舊候選；fetch_failed/parse_failed
    的詩人不在此集合，其舊行保留。未在集合中的詩人（含未選詩人）一律保留舊行。
    """
    if replaced_poets is None:
        replaced_poets = sorted(poet for poet, rows in fresh_by_poet.items() if rows)
    replaced = set(replaced_poets)
    keep = [row for row in existing if str(row.get("poet") or "") not in replaced]
    rows: list[dict[str, Any]] = list(keep)
    for poet in sorted(replaced):
        rows.extend(fresh_by_poet.get(poet, []))
    deduplicated: dict[str, dict[str, Any]] = {}
    for row in rows:
        reference_id = str(row.get("reference_id") or stable_id(row))
        deduplicated.setdefault(reference_id, row)
    return sorted(deduplicated.values(), key=dila_sort_key)


def active_status(rows: Sequence[dict[str, Any]]) -> str:
    statuses = {str(row.get("match_status") or "") for row in rows}
    if "matched" in statuses:
        return "matched"
    if "ambiguous" in statuses:
        return "ambiguous"
    return "not_found"


def _semantic_payload(coverage: dict[str, Any]) -> dict[str, Any]:
    out = json.loads(canonical_json({key: value for key, value in coverage.items() if key != "generated_at"}))
    for item in out.get("per_poet", []):
        attempt = item.get("dila", {}).get("attempt")
        if isinstance(attempt, dict):
            attempt.pop("accessed_at", None)
            attempt.pop("cache_path", None)
    source = out.get("sources", {}).get("dila_person", {})
    for key in ("offline", "resume", "delay_min", "delay_max", "retries"):
        source.pop(key, None)
    return out


def build_coverage(
    roster: Sequence[PoetSpec],
    *,
    scope: str,
    selected_poets: Sequence[str],
    matches_rows: Sequence[dict[str, Any]],
    outcomes: dict[str, str],
    attempts: dict[str, dict[str, Any]],
    generated_at: str | None = None,
    poems_path: Path = POEMS_JSON,
    offline: bool = False,
    resume: bool = False,
    delay_min: float = 5.0,
    delay_max: float = 8.0,
    retries: int = 2,
    existing_coverage: dict[str, Any] | None = None,
    existing_rows: Sequence[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    generated = generated_at or utc_now()
    selected = set(selected_poets)
    by_poet: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in matches_rows:
        by_poet[str(row.get("poet") or "")].append(row)

    old_by_poet: dict[str, dict[str, Any]] = {}
    if existing_coverage is not None and isinstance(existing_coverage, dict):
        for item in existing_coverage.get("per_poet", []):
            if isinstance(item, dict):
                old_by_poet[str(item.get("poet") or "")] = item.get("dila", {})

    per_poet: list[dict[str, Any]] = []
    for poet in roster:
        rows = by_poet.get(poet.name, [])
        current = outcomes.get(poet.name)
        attempt = attempts.get(poet.name)
        if current is None or attempt is None:
            previous = old_by_poet.get(poet.name, {})
            if current is None:
                if attempt is not None:
                    # 本次已嘗試取數但未獲準替換（fetch_failed_cache_used）：
                    # 優先保留先前狀態；無先前覆蓋時取既有行的活動狀態；否則記為 fetch_failed。
                    current = (
                        previous.get("status")
                        or (active_status(rows) if rows else None)
                        or "fetch_failed"
                    )
                else:
                    current = previous.get("status", "not_fetched")
            if attempt is None:
                attempt = previous.get("attempt", {})
        per_poet.append(
            {
                "poet": poet.name,
                "dynasty": poet.dynasty,
                "poem_count": poet.poem_count,
                "local_dynasty_counts": dict(poet.dynasty_counts or ((poet.dynasty, poet.poem_count),)),
                "dynasty_resolution": poet.dynasty_resolution,
                "selected": poet.name in selected,
                "dila": {
                    "status": current,
                    "active_status": active_status(rows),
                    "candidate_count": sum(
                        1 for row in rows if str(row.get("match_status")) in {"matched", "ambiguous"}
                    ),
                    "persisted_record_count": len(rows),
                    "attempt": attempt,
                },
            }
        )

    status_counts = dict(sorted(Counter(str(row["dila"]["status"]) for row in per_poet).items()))
    complete_without_fetch_failures = "fetch_failed" not in status_counts and "parse_failed" not in status_counts
    roster_fingerprint = stable_id(
        [(item.name, item.dynasty, item.poem_count, item.dynasty_counts, item.dynasty_resolution) for item in roster]
    )
    coverage = {
        "schema_version": SCHEMA_VERSION,
        "parser_version": PARSER_VERSION,
        "generated_at": generated,
        "scope": scope,
        "selected_poets": sorted(selected_poets),
        "corpus": {
            "path": str(poems_path),
            "poet_count": len(roster),
            "poem_count": sum(item.poem_count for item in roster),
            "dynasty_counts": dict(sorted(Counter(item.dynasty for item in roster).items())),
            "roster_sha256": roster_fingerprint,
        },
        "sources": {
            "dila_person": {
                "name": DILA_SOURCE_NAME,
                "endpoint": ENDPOINT,
                "docs_url": DILA_API_DOCS_URL,
                "license_note": DILA_LICENSE_NOTE,
                "callback": DILA_CALLBACK,
                "offline": offline,
                "resume": resume,
                "delay_min": delay_min,
                "delay_max": delay_max,
                "retries": retries,
                "status_counts": status_counts,
                "complete_without_fetch_failures": complete_without_fetch_failures,
            }
        },
        "totals": {
            "poets": len(roster),
            "selected_poets": len(selected),
            "records": len(matches_rows),
            "status_counts": status_counts,
            "complete_without_fetch_failures": complete_without_fetch_failures,
        },
        "per_poet": per_poet,
        "interpretation_notes": [
            "DILA/DDBC 為佛學與歷史人名權威資料庫；其朝代與生卒為參考信息，僅用於人名消歧與參考識別，不是作詩地點、路線或行年證據。",
            "出身地（birthPlace）是靜態參考字段（birthplace_reference_only=true），永不寫入或路由任何旅程事件。",
            "同名多人時不取首條：按姓名/別名、朝代、生卒重疊三項得分，唯一可信高分者列 matched，其餘同名候選仍保留以展示歧義（ambiguous）。",
            "所有結果停留在 data/candidates 候選層，不寫入 data/reviewed；本輸出不含任何路線/事件字段。",
            "來源為 DDBC Authority 開放內容（Open Content：" + DILA_OPEN_CONTENT_URL + "；官方授權 " + DILA_CC_LICENSE + "）；僅作參考，不作事實或行年斷言。",
            "fetch_failed/parse_failed 會顯式持久化失敗狀態；失敗不會抹除已存在的舊匹配記錄，也不會縮小 88 人覆蓋。",
        ],
    }

    if (
        existing_coverage is not None
        and existing_rows is not None
        and canonical_json(matches_rows) == canonical_json(existing_rows)
        and _semantic_payload(coverage) == _semantic_payload(existing_coverage)
    ):
        coverage["generated_at"] = str(existing_coverage.get("generated_at") or generated)
    return coverage


def collect(
    *,
    scope: str,
    poets_arg: str | None,
    offline: bool = False,
    resume: bool = False,
    delay_min: float = 5.0,
    delay_max: float = 8.0,
    timeout: float = 45.0,
    retries: int = 2,
    poems_path: Path = POEMS_JSON,
    cache_dir: Path = CACHE_DIR,
    matches_path: Path = MATCHES_JSONL,
    coverage_path: Path = COVERAGE_JSON,
    clock: Callable[[], str] = utc_now,
    sleeper: Callable[[float], None] = time.sleep,
    rng: Any = random,
    opener: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    roster = load_roster(poems_path)
    selected_poets = resolve_selection(roster, scope, poets_arg)
    selected = set(selected_poets)
    by_name = {item.name: item for item in roster}
    existing = read_jsonl(matches_path)
    to_fetch, resumed = resolve_run_plan(selected_poets, existing, resume)

    fetcher = DilaFetcher(
        CacheStore(cache_dir),
        offline=offline,
        timeout=timeout,
        retries=retries,
        delay_min=delay_min,
        delay_max=delay_max,
        opener=opener,
        sleeper=sleeper,
        rng=rng,
        clock=clock,
    )
    # DILA's authority service stores/query-matches traditional forms.  The
    # project corpus is mostly simplified, so querying the local spelling
    # returns JSONP null for records that do exist (e.g. 贺知章/賀知章).
    # Query the deterministic traditional alias; downstream selection still
    # compares simplified/traditional aliases and dynasty/life spans.
    results = fetcher.fetch_all(
        [person_query_url(traditional_name(name)) for name in to_fetch],
        poets=to_fetch,
    )
    results_by_poet = dict(zip(to_fetch, results))

    fresh_by_poet: dict[str, list[dict[str, Any]]] = {}
    replaced_poets: set[str] = set()
    outcomes: dict[str, str] = {}
    attempts: dict[str, dict[str, Any]] = {}
    for poet_name in to_fetch:
        result = results_by_poet[poet_name]
        poet = by_name[poet_name]
        local_life = local_life_years(poet_name)
        records: list[DilaRecord] = []
        row_metadata: dict[str, Any] = {}
        parse_ok = False
        if result.usable:
            try:
                _callback, payload = parse_jsonp(result.body)
                records, row_metadata = person_records_from_payload(payload)
                parse_ok = True
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
                result = replace(result, usable=False, attempt_status="parse_failed", error=f"parse_error: {exc}")
        attempts[poet_name] = attempt_record(result, row_metadata)
        if parse_ok and result.attempt_status in FRESH_REPLACE_STATUSES:
            rows, outcome = select_for_poet(poet, records, result, local_life, row_metadata)
            fresh_by_poet[poet_name] = rows
            outcomes[poet_name] = outcome
            replaced_poets.add(poet_name)
        elif result.attempt_status == "fetch_failed_cache_used":
            # 網絡失敗＋陳舊緩存：即使緩存體可解析也不替換；舊行與先前狀態保留，
            # attempt 仍記錄本次 fetch_failed_cache_used（含 error）。status 由 build_coverage 回落決定。
            fresh_by_poet[poet_name] = []
        else:
            fresh_by_poet[poet_name] = []
            outcomes[poet_name] = "fetch_failed" if result.attempt_status != "parse_failed" else "parse_failed"

    # 被 --resume 跳過的詩人（已有 matched/ambiguous 持久化行）：本輪不取數、
    # 不寫 outcomes/attempts——build_coverage 會原樣回落保留其先前 status 與 attempt，
    # 避免用「resumed」樁覆寫原始抓取元數據，也保證無操作 resume 輪次與原輪字節一致。

    merged = merge_matches(existing, fresh_by_poet, replaced_poets=sorted(replaced_poets))
    coverage = build_coverage(
        roster,
        scope=scope,
        selected_poets=selected_poets,
        matches_rows=merged,
        outcomes=outcomes,
        attempts=attempts,
        generated_at=clock(),
        poems_path=poems_path,
        offline=offline,
        resume=resume,
        delay_min=delay_min,
        delay_max=delay_max,
        retries=retries,
        existing_coverage=read_coverage(coverage_path),
        existing_rows=existing,
    )

    write_jsonl(matches_path, merged)
    atomic_write_text(coverage_path, canonical_json(coverage, pretty=True))
    return coverage


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dila_person_reference_pipeline",
        description="DDBC/DILA 人名權威資料參考採集器（88 位詩人；與行旅管線解耦）",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    collect_parser = subparsers.add_parser("collect", help="順序查詢 DILA 人名權威端點並寫入候選層")
    collect_parser.add_argument("--scope", choices=("core", "all"), default="all")
    collect_parser.add_argument("--poets", default=None, help="逗號分隔詩人；顯式名單優先於 --scope")
    collect_parser.add_argument("--offline", action="store_true", help="僅使用通過 checksum 校驗的緩存，絕不發網絡請求")
    collect_parser.add_argument("--resume", action="store_true", help="跳過已有持久化匹配的詩人（保留其舊記錄）")
    collect_parser.add_argument("--delay-min", type=float, default=5.0, help="同域順序請求的最小間隔秒數（默認 5）")
    collect_parser.add_argument("--delay-max", type=float, default=8.0, help="同域順序請求的最大間隔秒數（默認 8）")
    collect_parser.add_argument("--timeout", type=float, default=45.0)
    collect_parser.add_argument("--retries", type=int, default=2, help="初始請求後的額外重試次數（timeout/429/5xx 且有限）")
    subparsers.add_parser("check", help="運行離線 fixture 測試")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "check":
        check_script = Path(__file__).with_name("check_dila_person_reference_pipeline.py")
        return subprocess.run([sys.executable, str(check_script)], cwd=ROOT, check=False).returncode
    if args.delay_min < 0:
        raise SystemExit("--delay-min must be non-negative")
    if args.delay_max < args.delay_min or args.delay_max <= 0:
        raise SystemExit("--delay-max must be >= --delay-min and positive")
    if args.timeout <= 0:
        raise SystemExit("--timeout must be positive")
    if args.retries < 0:
        raise SystemExit("--retries must be non-negative")
    try:
        coverage = collect(
            scope=args.scope,
            poets_arg=args.poets,
            offline=args.offline,
            resume=args.resume,
            delay_min=args.delay_min,
            delay_max=args.delay_max,
            timeout=args.timeout,
            retries=args.retries,
        )
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        raise SystemExit(str(exc)) from exc
    totals = coverage["totals"]
    print(
        "[ok] dila person references: "
        f"poets={totals['poets']} selected={totals['selected_poets']} records={totals['records']}"
    )
    for status, count in sorted(totals["status_counts"].items()):
        print(f"  {status}: {count}")
    print(f"[ok] coverage: {COVERAGE_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
