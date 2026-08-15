"""可视化 12：市级行政区诗歌交互地图。

功能：
1. 首次运行自动下载并合并中国市级 GeoJSON 边界。
2. 生成本地地图文件：
   - output/assets/maps/china_city_prefecture.geojson
   - output/assets/maps/china_city_prefecture.js
3. 以中国市级行政区块为底图，不再只是点位图。
4. 鼠标滑过某个市：下方面板显示该市有哪些诗。
5. 点击某个市：下方面板显示该市完整诗词。
6. 支持城市、诗人、诗题、正文关键词检索。
7. 视觉风格与 99 总入口保持一致。

输出：
    output/12_市级诗歌地图.html

运行：
    python .\数据可视化脚本\viz_12_city_poem_map.py
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

import pymysql

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config import DB_NAME, MYSQL, OUTPUT_DIR
from data.place_dict import PLACE_DICT, aliases as place_aliases
from viz_assets import inject_static_page_base


POEMS_JSON = ROOT / "data" / "poems.json"

OUT_HTML = OUTPUT_DIR / "12_市级诗歌地图.html"
MAP_ASSET_DIR = OUTPUT_DIR / "assets" / "maps"
CITY_GEOJSON = MAP_ASSET_DIR / "china_city_prefecture.geojson"
CITY_GEOJS = MAP_ASSET_DIR / "china_city_prefecture.js"

GEO_CACHE_DIR = ROOT / "data" / "geojson_cache"
DATAV_BOUND_BASE = "https://geo.datav.aliyun.com/areas_v3/bound"
DATAV_QUERY_BASE = "https://geo.datav.aliyun.com/areas_v3/bound/geojson?code="

REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0 Safari/537.36"
    ),
    "Referer": "https://datav.aliyun.com/",
    "Accept": "application/json,text/plain,*/*",
}

MUNICIPALITY_ADCODE = {"110000", "120000", "310000", "500000"}
SPECIAL_REGION_NAMES = {"香港特别行政区", "澳门特别行政区", "台湾省"}

MAX_PREVIEW_POEMS = 8
MAX_POEMS_PER_CITY = 9999


@dataclass(frozen=True)
class RawHit:
    city: str
    province: str
    alias: str
    freq: int
    title: str
    poet: str
    dynasty: str
    school: str
    body: str


def conn():
    return pymysql.connect(
        **MYSQL,
        database=DB_NAME,
        connect_timeout=5,
        read_timeout=20,
        write_timeout=20,
        cursorclass=pymysql.cursors.DictCursor,
    )


def clean_text(value: object) -> str:
    return str(value or "").strip()


def normalize_province(value: object) -> str:
    province = clean_text(value)
    if not province:
        return "未标省份"
    return province


def normalize_city_name(value: object) -> str:
    name = clean_text(value)
    if not name:
        return "未标城市"

    name = re.sub(r"\s+", "", name)
    name = name.replace("特别行政区", "")
    name = name.replace("维吾尔自治区", "")
    name = name.replace("壮族自治区", "")
    name = name.replace("回族自治区", "")
    name = name.replace("自治区", "")
    name = name.replace("省", "")

    return name or "未标城市"


def normalize_admin_name(value: object) -> str:
    """用于市级地名和 GeoJSON feature name 的模糊匹配。"""
    name = clean_text(value)
    if not name:
        return ""

    name = re.sub(r"\s+", "", name)

    replacements = [
        "特别行政区",
        "维吾尔自治区",
        "壮族自治区",
        "回族自治区",
        "自治区",
        "土家族苗族自治州",
        "藏族羌族自治州",
        "哈尼族彝族自治州",
        "傣族景颇族自治州",
        "蒙古族藏族自治州",
        "蒙古自治州",
        "藏族自治州",
        "彝族自治州",
        "苗族自治州",
        "布依族苗族自治州",
        "自治州",
        "地区",
        "盟",
        "市",
        "省",
    ]

    for suffix in replacements:
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break

    return name


def make_request_json(url: str, retries: int = 3) -> dict:
    last_error: Exception | None = None

    for attempt in range(retries):
        try:
            request = urllib.request.Request(url, headers=REQUEST_HEADERS)
            with urllib.request.urlopen(request, timeout=20) as response:
                raw = response.read()
            text = raw.decode("utf-8", errors="replace")
            data = json.loads(text)
            if isinstance(data, dict) and data.get("type") == "FeatureCollection":
                return data
            if isinstance(data, dict) and data.get("features"):
                return data
            raise RuntimeError(f"返回内容不是有效 GeoJSON：{url}")
        except Exception as exc:
            last_error = exc
            time.sleep(1.2 * (attempt + 1))

    raise RuntimeError(f"下载 GeoJSON 失败：{url}；最后错误：{last_error}")


def fetch_datav_geojson(adcode: str) -> dict:
    GEO_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = GEO_CACHE_DIR / f"{adcode}_full.json"

    if cache_path.exists() and cache_path.stat().st_size > 1024:
        return json.loads(cache_path.read_text(encoding="utf-8"))

    urls = [
        f"{DATAV_BOUND_BASE}/{adcode}_full.json",
        f"{DATAV_QUERY_BASE}{adcode}_full",
    ]

    last_error: Exception | None = None
    for url in urls:
        try:
            data = make_request_json(url)
            cache_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            return data
        except Exception as exc:
            last_error = exc

    raise RuntimeError(f"无法获取行政区边界 adcode={adcode}；最后错误：{last_error}")


def valid_feature(feature: dict) -> bool:
    if not isinstance(feature, dict):
        return False
    if feature.get("type") != "Feature":
        return False
    geometry = feature.get("geometry")
    if not geometry:
        return False
    if geometry.get("type") not in {"Polygon", "MultiPolygon"}:
        return False
    coordinates = geometry.get("coordinates")
    return bool(coordinates)


def copy_feature_as_city(feature: dict, province_name: str = "") -> dict:
    props = dict(feature.get("properties") or {})
    name = clean_text(props.get("name"))
    adcode = clean_text(props.get("adcode"))

    props["name"] = name
    props["adcode"] = adcode
    props["level"] = "city"
    if province_name:
        props["provinceName"] = province_name

    return {
        "type": "Feature",
        "properties": props,
        "geometry": feature.get("geometry"),
    }


def build_city_geojson_from_datav() -> dict:
    """合并全国市级边界。

    逻辑：
    - 先下载全国 100000_full，取得省级 feature。
    - 普通省份：下载省级 *_full，里面通常是地级市 / 州 / 盟边界。
    - 直辖市：直接使用全国 feature 作为市级边界，不下钻到区县。
    - 港澳台：使用全国 feature 作为单独市级展示单元。
    """
    print("  [geo] 正在构建中国市级 GeoJSON 边界 ...")

    country = fetch_datav_geojson("100000")
    features: list[dict] = []
    seen_keys: set[str] = set()

    for province_feature in country.get("features", []):
        if not valid_feature(province_feature):
            continue

        props = province_feature.get("properties") or {}
        province_name = clean_text(props.get("name"))
        province_adcode = clean_text(props.get("adcode"))
        children_num = int(props.get("childrenNum") or 0)

        if not province_name or not province_adcode:
            continue

        is_municipality = province_adcode in MUNICIPALITY_ADCODE
        is_special = province_name in SPECIAL_REGION_NAMES

        if is_municipality or is_special or children_num <= 0:
            city_feature = copy_feature_as_city(province_feature, province_name=province_name)
            key = clean_text(city_feature["properties"].get("adcode")) or province_name
            if key not in seen_keys:
                seen_keys.add(key)
                features.append(city_feature)
            continue

        try:
            province_geo = fetch_datav_geojson(province_adcode)
        except Exception as exc:
            print(f"  [warn] 省级边界下载失败，跳过 {province_name}：{exc}")
            continue

        for city_feature_raw in province_geo.get("features", []):
            if not valid_feature(city_feature_raw):
                continue

            city_props = city_feature_raw.get("properties") or {}
            city_name = clean_text(city_props.get("name"))
            city_adcode = clean_text(city_props.get("adcode"))

            if not city_name:
                continue

            city_feature = copy_feature_as_city(city_feature_raw, province_name=province_name)
            key = city_adcode or f"{province_name}-{city_name}"
            if key in seen_keys:
                continue
            seen_keys.add(key)
            features.append(city_feature)

    out = {
        "type": "FeatureCollection",
        "name": "china_city_prefecture",
        "features": features,
    }

    return out


def ensure_city_geojson_assets() -> dict:
    MAP_ASSET_DIR.mkdir(parents=True, exist_ok=True)

    if CITY_GEOJSON.exists() and CITY_GEOJSON.stat().st_size > 1024:
        geojson = json.loads(CITY_GEOJSON.read_text(encoding="utf-8"))
    else:
        geojson = build_city_geojson_from_datav()
        CITY_GEOJSON.write_text(
            json.dumps(geojson, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )

    js = (
        "window.SHIXING_CITY_GEOJSON="
        + json.dumps(geojson, ensure_ascii=False, separators=(",", ":"))
        + ";\n"
        + "if(window.echarts){echarts.registerMap('china_city_prefecture', window.SHIXING_CITY_GEOJSON);}\n"
    )
    CITY_GEOJS.write_text(js, encoding="utf-8")

    print(f"  [geo] 市级边界：{len(geojson.get('features', []))} 个 feature -> {CITY_GEOJSON}")
    return geojson


def build_geo_lookup(geojson: dict) -> dict[str, dict[str, object]]:
    lookup: dict[str, dict[str, object]] = {}

    for feature in geojson.get("features", []):
        props = feature.get("properties") or {}
        name = clean_text(props.get("name"))
        province = clean_text(props.get("provinceName"))
        adcode = clean_text(props.get("adcode"))

        if not name:
            continue

        record = {
            "geoName": name,
            "province": province,
            "adcode": adcode,
        }

        norm_name = normalize_admin_name(name)
        norm_province = normalize_admin_name(province)

        keys = {
            f"exact:{name}",
            f"norm:{norm_name}",
            f"province_norm:{norm_province}:{norm_name}",
        }

        for key in keys:
            if key and key not in lookup:
                lookup[key] = record

    return lookup


def match_geo_city(city: str, province: str, lookup: dict[str, dict[str, object]]) -> dict[str, object] | None:
    city = clean_text(city)
    province = clean_text(province)

    if not city:
        return None

    norm_city = normalize_admin_name(city)
    norm_province = normalize_admin_name(province)

    candidates = [
        f"exact:{city}",
        f"exact:{city}市",
        f"norm:{norm_city}",
        f"province_norm:{norm_province}:{norm_city}",
    ]

    for key in candidates:
        if key in lookup:
            return lookup[key]

    return None


def load_hits_from_database() -> list[RawHit]:
    sql = """
        SELECT pl.modern,
               pl.province,
               pl.alias,
               pp.freq,
               pm.title,
               pm.body,
               pt.name AS poet,
               pt.dynasty,
               pt.school
          FROM t_place pl
          JOIN t_poem_place pp ON pp.place_id = pl.place_id
          JOIN t_poem pm ON pm.poem_id = pp.poem_id
          JOIN t_poet pt ON pt.poet_id = pm.poet_id
         ORDER BY pl.province, pl.modern, pt.dynasty, pt.name, pm.title
    """

    hits: list[RawHit] = []

    with conn() as c, c.cursor() as cur:
        cur.execute(sql)
        for row in cur.fetchall():
            city = normalize_city_name(row.get("modern"))
            province = normalize_province(row.get("province"))

            hits.append(
                RawHit(
                    city=city,
                    province=province,
                    alias=clean_text(row.get("alias")),
                    freq=int(row.get("freq") or 1),
                    title=clean_text(row.get("title")),
                    poet=clean_text(row.get("poet")),
                    dynasty=clean_text(row.get("dynasty")),
                    school=clean_text(row.get("school")),
                    body=clean_text(row.get("body")),
                )
            )

    return hits


def greedy_place_counts(text: str, tokens: list[str]) -> Counter[str]:
    counts: Counter[str] = Counter()
    work = text or ""

    for token in tokens:
        count = work.count(token)
        if count:
            counts[token] += count
            work = work.replace(token, "·" * len(token))

    return counts


def load_hits_from_poems_json(reason: Exception | None = None) -> list[RawHit]:
    if reason is not None:
        print(f"  [warn] 数据库读取失败，改用 poems.json 离线兜底：{reason}")

    records = json.loads(POEMS_JSON.read_text(encoding="utf-8"))

    place_meta = {
        alias: {
            "modern": modern,
            "province": province,
        }
        for alias, modern, province, *_ in PLACE_DICT
    }

    tokens = place_aliases()
    hits: list[RawHit] = []

    for row in records:
        title = clean_text(row.get("title"))
        body = clean_text(row.get("body"))
        text = f"{title}\n{body}"
        counts = greedy_place_counts(text, tokens)

        for alias, freq in counts.items():
            meta = place_meta.get(alias)
            if not meta:
                continue

            hits.append(
                RawHit(
                    city=normalize_city_name(meta["modern"]),
                    province=normalize_province(meta["province"]),
                    alias=alias,
                    freq=int(freq or 1),
                    title=title,
                    poet=clean_text(row.get("poet") or row.get("author")),
                    dynasty=clean_text(row.get("dynasty")),
                    school=clean_text(row.get("school")),
                    body=body,
                )
            )

    return hits


def load_hits() -> tuple[str, list[RawHit]]:
    try:
        return "MySQL 实时入库数据", load_hits_from_database()
    except Exception as exc:
        return "poems.json 离线兜底数据", load_hits_from_poems_json(exc)


def context_snippet(text: str, keyword: str = "", limit: int = 96) -> str:
    clean = " ".join(clean_text(text).split())

    if not clean:
        return ""

    if keyword:
        index = clean.find(keyword)
        if index >= 0:
            radius = max(18, (limit - len(keyword)) // 2)
            start = max(0, index - radius)
            end = min(len(clean), index + len(keyword) + radius)
            snippet = clean[start:end]
            if start > 0:
                snippet = "…" + snippet
            if end < len(clean):
                snippet += "…"
            return snippet

    return clean[:limit] + ("…" if len(clean) > limit else "")


def build_city_payload(geojson: dict) -> dict[str, object]:
    source, hits = load_hits()
    lookup = build_geo_lookup(geojson)

    city_meta: dict[str, dict[str, object]] = {}
    city_poem_map: dict[str, dict[tuple[str, str], dict[str, object]]] = defaultdict(dict)
    city_alias_counts: dict[str, Counter[str]] = defaultdict(Counter)
    city_poet_counts: dict[str, Counter[str]] = defaultdict(Counter)
    city_dynasty_counts: dict[str, Counter[str]] = defaultdict(Counter)
    city_freq: Counter[str] = Counter()
    unmatched_counter: Counter[str] = Counter()

    for hit in hits:
        match = match_geo_city(hit.city, hit.province, lookup)
        if not match:
            unmatched_counter[f"{hit.province}-{hit.city}"] += hit.freq
            continue

        geo_name = str(match["geoName"])
        province_name = str(match.get("province") or hit.province)
        adcode = str(match.get("adcode") or "")
        city_id = geo_name

        if city_id not in city_meta:
            city_meta[city_id] = {
                "id": city_id,
                "geoName": geo_name,
                "city": normalize_city_name(geo_name),
                "province": province_name,
                "adcode": adcode,
            }

        city_freq[city_id] += hit.freq
        city_alias_counts[city_id][hit.alias] += hit.freq
        city_poet_counts[city_id][hit.poet or "未标"] += 1
        city_dynasty_counts[city_id][hit.dynasty or "未标"] += 1

        poem_key = (hit.poet, hit.title)
        existing = city_poem_map[city_id].get(poem_key)

        if existing:
            existing["freq"] = int(existing["freq"]) + hit.freq
            aliases = existing.setdefault("aliases", [])
            if hit.alias and hit.alias not in aliases:
                aliases.append(hit.alias)
        else:
            city_poem_map[city_id][poem_key] = {
                "title": hit.title,
                "poet": hit.poet or "未标",
                "dynasty": hit.dynasty or "未标",
                "school": hit.school or "未分",
                "body": hit.body,
                "bodyLen": len(hit.body),
                "freq": hit.freq,
                "aliases": [hit.alias] if hit.alias else [],
                "snippet": context_snippet(hit.body, hit.alias),
            }

    cities: list[dict[str, object]] = []

    for city_id, meta in city_meta.items():
        poems = list(city_poem_map[city_id].values())
        poems.sort(
            key=lambda item: (
                -int(item.get("freq") or 0),
                str(item.get("dynasty") or ""),
                str(item.get("poet") or ""),
                str(item.get("title") or ""),
            )
        )

        cities.append(
            {
                "id": city_id,
                "geoName": meta["geoName"],
                "city": meta["city"],
                "province": meta["province"],
                "adcode": meta["adcode"],
                "freq": int(city_freq[city_id]),
                "poemCount": len(poems),
                "topAliases": [
                    {"alias": alias, "freq": int(freq)}
                    for alias, freq in city_alias_counts[city_id].most_common(8)
                    if alias
                ],
                "topPoets": [
                    {"poet": poet, "count": int(count)}
                    for poet, count in city_poet_counts[city_id].most_common(8)
                ],
                "dynasties": [
                    {"dynasty": dynasty, "count": int(count)}
                    for dynasty, count in city_dynasty_counts[city_id].most_common()
                ],
                "previewPoems": poems[:MAX_PREVIEW_POEMS],
                "poems": poems[:MAX_POEMS_PER_CITY],
            }
        )

    cities.sort(key=lambda item: (-int(item["poemCount"]), -int(item["freq"]), str(item["city"])))

    total_poems = sum(int(city["poemCount"]) for city in cities)
    total_freq = sum(int(city["freq"]) for city in cities)
    provinces = sorted({str(city["province"]) for city in cities if city.get("province")})

    return {
        "source": source,
        "summary": {
            "cityCount": len(cities),
            "provinceCount": len(provinces),
            "poemCityRefs": total_poems,
            "mentionCount": total_freq,
            "unmatchedPlaceCount": len(unmatched_counter),
            "unmatchedMentionCount": int(sum(unmatched_counter.values())),
            "geoFeatureCount": len(geojson.get("features", [])),
            "topCity": cities[0]["city"] if cities else "无",
            "topCityPoemCount": cities[0]["poemCount"] if cities else 0,
        },
        "cities": cities,
        "unmatchedPlaces": [
            {"place": place, "freq": int(freq)}
            for place, freq in unmatched_counter.most_common(30)
        ],
    }


def render() -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    MAP_ASSET_DIR.mkdir(parents=True, exist_ok=True)

    geojson = ensure_city_geojson_assets()
    payload = build_city_payload(geojson)
    summary = payload["summary"]
    data_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")

    html = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>诗行万里 · 市级诗歌地图</title>
    <script src="assets/pyecharts/v6/echarts.min.js"></script>
    <script src="assets/maps/china_city_prefecture.js"></script>
    <style>
    :root {
        --sx-bg-0: #050816;
        --sx-bg-1: #08111f;
        --sx-bg-2: #0f172a;
        --sx-panel: rgba(15, 23, 42, 0.76);
        --sx-panel-strong: rgba(15, 23, 42, 0.94);
        --sx-glass: rgba(255, 255, 255, 0.075);
        --sx-line: rgba(148, 163, 184, 0.22);
        --sx-line-strong: rgba(148, 163, 184, 0.38);
        --sx-text: #e5edf9;
        --sx-muted: #9aa8bd;
        --sx-soft: #cbd5e1;
        --sx-accent: #38bdf8;
        --sx-accent-2: #a78bfa;
        --sx-accent-3: #34d399;
        --sx-warn: #fbbf24;
        --sx-danger: #fb7185;
        --sx-shadow: 0 28px 80px rgba(0, 0, 0, 0.36);
        --sx-radius-xl: 28px;
        --sx-radius-lg: 22px;
        --sx-radius-md: 16px;
        --sx-radius-sm: 12px;
    }

    * { box-sizing: border-box; }

    html { scroll-behavior: smooth; }

    body {
        margin: 0;
        min-height: 100vh;
        color: var(--sx-text);
        font-family: "Microsoft YaHei", "PingFang SC", "Segoe UI", Arial, sans-serif;
        background:
            radial-gradient(circle at 8% 10%, rgba(56, 189, 248, 0.22), transparent 30%),
            radial-gradient(circle at 88% 8%, rgba(167, 139, 250, 0.22), transparent 28%),
            radial-gradient(circle at 60% 90%, rgba(52, 211, 153, 0.16), transparent 30%),
            linear-gradient(135deg, var(--sx-bg-0), var(--sx-bg-1) 42%, #111827);
        overflow-x: hidden;
    }

    body::before {
        content: "";
        position: fixed;
        inset: 0;
        z-index: -2;
        pointer-events: none;
        opacity: 0.16;
        background-image:
            linear-gradient(rgba(255,255,255,.06) 1px, transparent 1px),
            linear-gradient(90deg, rgba(255,255,255,.06) 1px, transparent 1px);
        background-size: 42px 42px;
        mask-image: linear-gradient(to bottom, black, transparent 86%);
    }

    body::after {
        content: "";
        position: fixed;
        inset: 0;
        z-index: -1;
        pointer-events: none;
        background:
            radial-gradient(circle at 22% 26%, rgba(56, 189, 248, 0.10), transparent 24%),
            radial-gradient(circle at 80% 70%, rgba(167, 139, 250, 0.10), transparent 28%);
        filter: blur(2px);
    }

    a { color: inherit; }

    .shell {
        width: min(1280px, calc(100vw - 36px));
        margin: 0 auto;
        padding: 24px 0 56px;
    }

    .hero {
        position: relative;
        min-height: 380px;
        padding: 30px;
        border: 1px solid var(--sx-line);
        border-radius: var(--sx-radius-xl);
        background:
            linear-gradient(135deg, rgba(15, 23, 42, 0.94), rgba(15, 23, 42, 0.64)),
            radial-gradient(circle at 82% 16%, rgba(56, 189, 248, 0.18), transparent 38%);
        box-shadow: var(--sx-shadow);
        overflow: hidden;
    }

    .hero::before {
        content: "";
        position: absolute;
        width: 360px;
        height: 360px;
        right: -120px;
        top: -150px;
        border-radius: 999px;
        background: var(--sx-accent);
        opacity: 0.16;
        filter: blur(22px);
    }

    .hero::after {
        content: "";
        position: absolute;
        inset: 0;
        pointer-events: none;
        background: linear-gradient(120deg, transparent, rgba(255,255,255,.07), transparent);
        transform: translateX(-130%);
        animation: sheen 7s ease-in-out infinite;
    }

    @keyframes sheen {
        0%, 62% { transform: translateX(-130%); }
        100% { transform: translateX(130%); }
    }

    .hero-inner {
        position: relative;
        z-index: 1;
        display: grid;
        grid-template-columns: minmax(0, 1.2fr) minmax(380px, 0.8fr);
        gap: 26px;
        align-items: end;
    }

    .eyebrow {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        color: #67e8f9;
        font-size: 12px;
        font-weight: 900;
        letter-spacing: 0.16em;
        text-transform: uppercase;
    }

    .eyebrow::before {
        content: "";
        width: 28px;
        height: 1px;
        background: currentColor;
    }

    h1 {
        margin: 16px 0 16px;
        max-width: 820px;
        color: #f8fafc;
        font-size: clamp(38px, 5vw, 70px);
        line-height: 1.02;
        letter-spacing: -0.06em;
    }

    .gradient {
        background: linear-gradient(90deg, #e0f2fe, #a7f3d0 44%, #c4b5fd);
        -webkit-background-clip: text;
        background-clip: text;
        color: transparent;
    }

    .subtitle {
        margin: 0;
        max-width: 840px;
        color: var(--sx-muted);
        font-size: 15px;
        line-height: 1.9;
    }

    .hero-note {
        margin-top: 14px;
        padding: 14px 16px;
        border: 1px solid rgba(251, 191, 36, 0.30);
        border-radius: var(--sx-radius-md);
        background: linear-gradient(135deg, rgba(120, 53, 15, 0.30), rgba(15, 23, 42, 0.58));
        color: #fde68a;
        font-size: 13px;
        line-height: 1.75;
    }

    .metrics {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 12px;
    }

    .metric {
        min-height: 106px;
        padding: 18px;
        border: 1px solid var(--sx-line);
        border-radius: var(--sx-radius-lg);
        background: rgba(255,255,255,.075);
        box-shadow: 0 20px 54px rgba(0,0,0,.22);
        backdrop-filter: blur(20px);
    }

    .metric span {
        display: block;
        color: var(--sx-muted);
        font-size: 13px;
        font-weight: 800;
    }

    .metric strong {
        display: block;
        margin-top: 10px;
        color: #f8fafc;
        font-size: 30px;
        line-height: 1.1;
        letter-spacing: -0.04em;
    }

    .control-panel {
        display: grid;
        grid-template-columns: minmax(280px, 1fr) minmax(160px, 220px) auto;
        gap: 12px;
        align-items: end;
        margin: 22px 0;
        padding: 16px;
        border: 1px solid var(--sx-line);
        border-radius: var(--sx-radius-lg);
        background:
            linear-gradient(145deg, rgba(255,255,255,.075), rgba(255,255,255,.035)),
            rgba(15, 23, 42, 0.72);
        box-shadow: 0 24px 68px rgba(0, 0, 0, 0.26);
        backdrop-filter: blur(22px);
    }

    label {
        display: grid;
        gap: 8px;
        color: var(--sx-soft);
        font-size: 13px;
        font-weight: 800;
    }

    input,
    select,
    button {
        min-height: 44px;
        border: 1px solid rgba(148, 163, 184, 0.28);
        border-radius: 14px;
        background: rgba(2, 6, 23, 0.45);
        color: var(--sx-text);
        font: inherit;
        font-size: 14px;
    }

    input,
    select {
        width: 100%;
        padding: 0 13px;
        outline: none;
    }

    input::placeholder { color: rgba(203, 213, 225, 0.55); }

    input:focus,
    select:focus {
        border-color: rgba(34, 211, 238, 0.72);
        box-shadow: 0 0 0 4px rgba(34, 211, 238, 0.10);
    }

    button {
        padding: 0 16px;
        cursor: pointer;
        font-weight: 900;
        background: linear-gradient(135deg, rgba(34, 211, 238, 0.20), rgba(167, 139, 250, 0.18));
    }

    .layout {
        display: grid;
        grid-template-columns: minmax(0, 1.38fr) minmax(360px, 0.62fr);
        gap: 18px;
        align-items: stretch;
    }

    .panel {
        border: 1px solid var(--sx-line);
        border-radius: var(--sx-radius-lg);
        background:
            linear-gradient(145deg, rgba(255,255,255,.075), rgba(255,255,255,.035)),
            rgba(15, 23, 42, 0.72);
        box-shadow: 0 24px 68px rgba(0, 0, 0, 0.26);
        backdrop-filter: blur(22px);
        overflow: hidden;
    }

    .panel-head {
        display: flex;
        align-items: baseline;
        justify-content: space-between;
        gap: 16px;
        padding: 18px 20px;
        border-bottom: 1px solid var(--sx-line);
        background: rgba(2, 6, 23, 0.22);
    }

    .panel-head h2 {
        margin: 0;
        color: #f8fafc;
        font-size: 22px;
        letter-spacing: -0.03em;
    }

    .panel-head span {
        color: var(--sx-muted);
        font-size: 13px;
        font-weight: 800;
    }

    #map {
        width: 100%;
        height: 760px;
    }

    .city-list {
        max-height: 760px;
        overflow: auto;
        padding: 12px;
        scrollbar-width: thin;
        scrollbar-color: rgba(34, 211, 238, 0.42) rgba(15, 23, 42, 0.4);
    }

    .city-item {
        position: relative;
        display: grid;
        gap: 7px;
        width: 100%;
        margin: 0 0 10px;
        padding: 14px;
        border: 1px solid rgba(148, 163, 184, 0.18);
        border-radius: var(--sx-radius-md);
        background: rgba(2, 6, 23, 0.28);
        color: var(--sx-text);
        text-align: left;
        cursor: pointer;
        transition: transform .18s ease, border-color .18s ease, background .18s ease;
    }

    .city-item:hover,
    .city-item.is-active {
        transform: translateY(-2px);
        border-color: rgba(34, 211, 238, 0.55);
        background: rgba(34, 211, 238, 0.10);
    }

    .city-title {
        display: flex;
        align-items: baseline;
        justify-content: space-between;
        gap: 10px;
    }

    .city-title strong {
        color: #f8fafc;
        font-size: 18px;
        letter-spacing: -0.03em;
    }

    .city-title span {
        color: #67e8f9;
        font-size: 13px;
        font-weight: 900;
    }

    .city-meta {
        color: var(--sx-muted);
        font-size: 13px;
        line-height: 1.6;
    }

    .tags {
        display: flex;
        flex-wrap: wrap;
        gap: 6px;
    }

    .tag {
        display: inline-flex;
        align-items: center;
        min-height: 24px;
        padding: 0 9px;
        border: 1px solid rgba(34, 211, 238, 0.30);
        border-radius: 999px;
        background: rgba(34, 211, 238, 0.10);
        color: #cffafe;
        font-size: 12px;
        font-weight: 900;
    }

    .detail-grid {
        display: grid;
        grid-template-columns: minmax(0, 0.82fr) minmax(0, 1.18fr);
        gap: 18px;
        margin-top: 18px;
    }

    .summary-box {
        padding: 18px;
    }

    .summary-title {
        display: flex;
        align-items: baseline;
        justify-content: space-between;
        gap: 16px;
    }

    .summary-title h2 {
        margin: 0;
        color: #f8fafc;
        font-size: 26px;
        letter-spacing: -0.04em;
    }

    .summary-title span {
        color: var(--sx-muted);
        font-size: 13px;
        font-weight: 900;
    }

    .city-stats {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 10px;
        margin-top: 16px;
    }

    .city-stat {
        min-height: 82px;
        padding: 12px;
        border: 1px solid rgba(148, 163, 184, 0.18);
        border-radius: var(--sx-radius-md);
        background: rgba(2, 6, 23, 0.26);
    }

    .city-stat span {
        display: block;
        color: var(--sx-muted);
        font-size: 12px;
        font-weight: 800;
    }

    .city-stat strong {
        display: block;
        margin-top: 8px;
        color: #f8fafc;
        font-size: 22px;
        letter-spacing: -0.04em;
    }

    .preview-list {
        margin-top: 16px;
        display: grid;
        gap: 10px;
    }

    .preview-poem {
        padding: 13px;
        border: 1px solid rgba(148, 163, 184, 0.16);
        border-radius: var(--sx-radius-md);
        background: rgba(2, 6, 23, 0.22);
    }

    .preview-poem strong {
        display: block;
        color: #f8fafc;
        font-size: 15px;
        line-height: 1.45;
    }

    .preview-poem small {
        display: block;
        margin-top: 5px;
        color: var(--sx-muted);
        line-height: 1.6;
    }

    .poem-panel {
        max-height: 720px;
        overflow: auto;
        padding: 18px;
        scrollbar-width: thin;
        scrollbar-color: rgba(34, 211, 238, 0.42) rgba(15, 23, 42, 0.4);
    }

    .poem-card {
        margin-bottom: 14px;
        padding: 16px;
        border: 1px solid rgba(148, 163, 184, 0.18);
        border-radius: var(--sx-radius-md);
        background: rgba(2, 6, 23, 0.26);
    }

    .poem-card h3 {
        margin: 0;
        color: #f8fafc;
        font-size: 18px;
        line-height: 1.42;
        letter-spacing: -0.03em;
    }

    .poem-meta {
        margin-top: 7px;
        color: var(--sx-muted);
        font-size: 13px;
        line-height: 1.65;
    }

    .poem-body {
        margin-top: 12px;
        color: #dbe7f8;
        font-size: 15px;
        line-height: 1.9;
        white-space: pre-wrap;
    }

    mark {
        padding: 0 2px;
        border-radius: 4px;
        background: rgba(250, 204, 21, 0.22);
        color: #fde68a;
    }

    .empty,
    .map-warning {
        padding: 18px;
        border: 1px dashed rgba(148, 163, 184, 0.34);
        border-radius: var(--sx-radius-md);
        background: rgba(255, 255, 255, 0.04);
        color: var(--sx-muted);
        text-align: center;
        font-weight: 800;
        line-height: 1.7;
    }

    .map-warning {
        display: none;
        margin: 14px;
        border-color: rgba(251, 191, 36, 0.32);
        background: rgba(120, 53, 15, 0.24);
        color: #fde68a;
    }

    @media (max-width: 1080px) {
        .hero-inner,
        .layout,
        .detail-grid {
            grid-template-columns: 1fr;
        }

        #map {
            height: 640px;
        }

        .city-list {
            max-height: 360px;
        }
    }

    @media (max-width: 720px) {
        .shell {
            width: min(100vw - 22px, 1280px);
            padding-top: 14px;
        }

        .hero {
            padding: 20px;
            border-radius: 22px;
        }

        h1 {
            font-size: 34px;
        }

        .metrics,
        .control-panel,
        .city-stats {
            grid-template-columns: 1fr;
        }

        #map {
            height: 520px;
        }
    }
    </style>
</head>
<body>
    <main class="shell">
        <section class="hero">
            <div class="hero-inner">
                <div>
                    <span class="eyebrow">City-Level Poetry Atlas</span>
                    <h1><span class="gradient">市级行政区诗歌地图</span></h1>
                    <p class="subtitle">
                        以中国市级行政区边界为底图，将诗中命中的现代地名聚合到对应城市。
                        鼠标滑过城市可以查看诗作摘要，点击城市可以展开该市完整诗词。
                    </p>
                    <div class="hero-note">
                        首次运行会自动构建本地市级 GeoJSON。直辖市按整市展示，普通省份按地级市 / 州 / 盟展示。
                        未能和 GeoJSON 匹配的古今地名不会落图，但会计入未匹配统计。
                    </div>
                </div>
                <div class="metrics">
                    <div class="metric"><span>市级边界</span><strong>__GEO_FEATURE_COUNT__</strong></div>
                    <div class="metric"><span>有诗城市</span><strong>__CITY_COUNT__</strong></div>
                    <div class="metric"><span>诗作关联</span><strong>__POEM_CITY_REFS__</strong></div>
                    <div class="metric"><span>未匹配地名</span><strong>__UNMATCHED_COUNT__</strong></div>
                </div>
            </div>
        </section>

        <section class="control-panel">
            <label>检索城市 / 诗人 / 诗题 / 正文
                <input id="queryInput" type="search" placeholder="例如：西安、李白、春风、江南">
            </label>
            <label>排序
                <select id="sortSelect">
                    <option value="poemCount">按诗作数降序</option>
                    <option value="freq">按地名命中次数降序</option>
                    <option value="city">按城市名称排序</option>
                </select>
            </label>
            <button id="resetBtn" type="button">重置</button>
        </section>

        <section class="layout">
            <section class="panel">
                <div class="panel-head">
                    <h2>中国市级行政区诗歌热力图</h2>
                    <span id="mapHint">滑过城市看摘要，点击城市看全文</span>
                </div>
                <div id="mapWarning" class="map-warning">
                    地图资源未加载。请确认 output/assets/maps/china_city_prefecture.js 和 output/assets/pyecharts/v6/echarts.min.js 存在。
                </div>
                <div id="map"></div>
            </section>

            <section class="panel">
                <div class="panel-head">
                    <h2>城市排行</h2>
                    <span id="visibleCount">0 个城市</span>
                </div>
                <div id="cityList" class="city-list"></div>
            </section>
        </section>

        <section class="detail-grid">
            <section class="panel summary-box">
                <div class="summary-title">
                    <h2 id="activeCityTitle">城市摘要</h2>
                    <span id="activeCitySub">请选择城市</span>
                </div>
                <div id="activeCityStats" class="city-stats"></div>
                <div id="activeCityTags" class="tags" style="margin-top:14px;"></div>
                <div id="previewList" class="preview-list">
                    <div class="empty">滑过或点击一个城市后，这里会显示诗作摘要。</div>
                </div>
            </section>

            <section class="panel">
                <div class="panel-head">
                    <h2>完整诗词</h2>
                    <span id="poemPanelHint">点击城市后显示</span>
                </div>
                <div id="poemPanel" class="poem-panel">
                    <div class="empty">暂未选择城市。</div>
                </div>
            </section>
        </section>
    </main>

    <script>
    window.CITY_POEM_PAYLOAD = __PAYLOAD__;

    const payload = window.CITY_POEM_PAYLOAD;
    const allCities = payload.cities || [];

    const els = {
        query: document.getElementById("queryInput"),
        sort: document.getElementById("sortSelect"),
        reset: document.getElementById("resetBtn"),
        cityList: document.getElementById("cityList"),
        visibleCount: document.getElementById("visibleCount"),
        activeCityTitle: document.getElementById("activeCityTitle"),
        activeCitySub: document.getElementById("activeCitySub"),
        activeCityStats: document.getElementById("activeCityStats"),
        activeCityTags: document.getElementById("activeCityTags"),
        previewList: document.getElementById("previewList"),
        poemPanel: document.getElementById("poemPanel"),
        poemPanelHint: document.getElementById("poemPanelHint"),
        mapWarning: document.getElementById("mapWarning"),
    };

    let chart = null;
    let activeCityId = allCities.length ? allCities[0].id : "";
    let clickedCityId = "";

    function escapeHtml(value) {
        return String(value == null ? "" : value).replace(/[&<>"']/g, function (ch) {
            return {
                "&": "&amp;",
                "<": "&lt;",
                ">": "&gt;",
                '"': "&quot;",
                "'": "&#39;"
            }[ch];
        });
    }

    function normalize(value) {
        return String(value || "").trim().toLowerCase();
    }

    function citySearchText(city) {
        const poemText = (city.poems || []).map(function (poem) {
            return [
                poem.title,
                poem.poet,
                poem.dynasty,
                poem.school,
                poem.body,
                (poem.aliases || []).join(" ")
            ].join(" ");
        }).join(" ");

        const aliasText = (city.topAliases || []).map(function (item) {
            return item.alias;
        }).join(" ");

        return normalize([
            city.city,
            city.geoName,
            city.province,
            aliasText,
            poemText
        ].join(" "));
    }

    function cityByGeoName(name) {
        return allCities.find(function (city) {
            return city.geoName === name || city.id === name;
        });
    }

    function filteredCities() {
        const query = normalize(els.query.value);

        let rows = allCities.filter(function (city) {
            return !query || citySearchText(city).indexOf(query) >= 0;
        });

        const sortBy = els.sort.value;
        rows.sort(function (a, b) {
            if (sortBy === "city") {
                return String(a.city).localeCompare(String(b.city), "zh-Hans-CN");
            }
            if (sortBy === "freq") {
                return (b.freq || 0) - (a.freq || 0) || (b.poemCount || 0) - (a.poemCount || 0);
            }
            return (b.poemCount || 0) - (a.poemCount || 0) || (b.freq || 0) - (a.freq || 0);
        });

        return rows;
    }

    function mapData(rows) {
        return rows.map(function (city) {
            return {
                name: city.geoName,
                cityId: city.id,
                city: city.city,
                province: city.province,
                value: city.poemCount,
                freq: city.freq,
                poemCount: city.poemCount,
                topAliases: city.topAliases || [],
                topPoets: city.topPoets || []
            };
        });
    }

    function renderMap(rows) {
        if (!window.echarts || !window.SHIXING_CITY_GEOJSON) {
            els.mapWarning.style.display = "block";
            return;
        }

        if (!chart) {
            chart = echarts.init(document.getElementById("map"));

            chart.on("mouseover", function (params) {
                if (params.seriesName !== "市级诗歌热力") {
                    return;
                }

                const city = cityByGeoName(params.name);
                if (city) {
                    activeCityId = city.id;
                    renderCitySummary(city, false);
                    renderCityList(filteredCities());
                }
            });

            chart.on("click", function (params) {
                if (params.seriesName !== "市级诗歌热力") {
                    return;
                }

                const city = cityByGeoName(params.name);
                if (city) {
                    activeCityId = city.id;
                    clickedCityId = city.id;
                    renderCitySummary(city, true);
                    renderFullPoems(city);
                    renderCityList(filteredCities());
                } else {
                    clickedCityId = "";
                    renderEmptyCity(params.name);
                }
            });

            window.addEventListener("resize", function () {
                chart.resize();
            });
        }

        const maxPoem = Math.max.apply(null, rows.map(function (city) {
            return city.poemCount || 0;
        }).concat([1]));

        chart.setOption({
            backgroundColor: "transparent",
            tooltip: {
                trigger: "item",
                backgroundColor: "rgba(15, 23, 42, 0.94)",
                borderColor: "rgba(56, 189, 248, 0.45)",
                borderWidth: 1,
                textStyle: {
                    color: "#e5edf9",
                    fontFamily: "Microsoft YaHei"
                },
                extraCssText: "box-shadow:0 18px 44px rgba(0,0,0,.35);border-radius:12px;",
                formatter: function (params) {
                    const city = cityByGeoName(params.name);
                    if (!city) {
                        return [
                            '<div style="min-width:190px;line-height:1.7;">',
                            '<strong style="font-size:16px;color:#fff;">' + escapeHtml(params.name || "") + '</strong>',
                            '<br/><span style="color:#94a3b8;">暂无诗作命中</span>',
                            '</div>'
                        ].join("");
                    }

                    const aliases = (city.topAliases || []).slice(0, 4).map(function (item) {
                        return escapeHtml(item.alias) + "×" + escapeHtml(item.freq);
                    }).join("、");

                    const poets = (city.topPoets || []).slice(0, 4).map(function (item) {
                        return escapeHtml(item.poet);
                    }).join("、");

                    return [
                        '<div style="min-width:230px;max-width:360px;line-height:1.7;">',
                        '<strong style="font-size:16px;color:#fff;">' + escapeHtml(city.province) + ' · ' + escapeHtml(city.city) + '</strong>',
                        '<br/>诗作关联：' + escapeHtml(city.poemCount || 0) + ' 首',
                        '<br/>地名命中：' + escapeHtml(city.freq || 0) + ' 次',
                        aliases ? '<br/><span style="color:#94a3b8;">高频地名：</span>' + aliases : '',
                        poets ? '<br/><span style="color:#94a3b8;">相关诗人：</span>' + poets : '',
                        '<br/><span style="color:#67e8f9;">点击查看完整诗词</span>',
                        '</div>'
                    ].join("");
                }
            },
            visualMap: {
                min: 0,
                max: maxPoem,
                calculable: true,
                show: true,
                right: 24,
                bottom: 28,
                text: ["诗作多", "诗作少"],
                textStyle: {
                    color: "#cbd5e1"
                },
                inRange: {
                    color: ["rgba(30, 41, 59, 0.82)", "#1e3a8a", "#0891b2", "#22c55e", "#facc15", "#fb7185"]
                },
                itemWidth: 14,
                itemHeight: 130,
                backgroundColor: "rgba(15,23,42,.52)",
                borderColor: "rgba(148,163,184,.22)",
                borderWidth: 1,
                padding: 10
            },
            series: [
                {
                    name: "市级诗歌热力",
                    type: "map",
                    map: "china_city_prefecture",
                    roam: true,
                    zoom: 1.08,
                    scaleLimit: {
                        min: 0.8,
                        max: 12
                    },
                    selectedMode: "single",
                    data: mapData(rows),
                    nameProperty: "name",
                    label: {
                        show: false,
                        color: "#cbd5e1",
                        fontSize: 10
                    },
                    itemStyle: {
                        areaColor: "rgba(15, 23, 42, 0.68)",
                        borderColor: "rgba(148, 163, 184, 0.30)",
                        borderWidth: 0.65
                    },
                    emphasis: {
                        label: {
                            show: true,
                            color: "#e0f2fe",
                            fontWeight: "bold"
                        },
                        itemStyle: {
                            areaColor: "rgba(56, 189, 248, 0.50)",
                            borderColor: "rgba(103, 232, 249, 0.92)",
                            borderWidth: 1.2,
                            shadowBlur: 18,
                            shadowColor: "rgba(34, 211, 238, 0.45)"
                        }
                    },
                    select: {
                        itemStyle: {
                            areaColor: "rgba(250, 204, 21, 0.72)",
                            borderColor: "#fde68a",
                            borderWidth: 1.2
                        },
                        label: {
                            show: true,
                            color: "#111827",
                            fontWeight: "bold"
                        }
                    }
                }
            ]
        }, true);
    }

    function renderCityList(rows) {
        els.visibleCount.textContent = rows.length + " 个城市";

        if (!rows.length) {
            els.cityList.innerHTML = '<div class="empty">没有匹配的城市。</div>';
            return;
        }

        els.cityList.innerHTML = rows.map(function (city) {
            const active = city.id === activeCityId || city.id === clickedCityId ? " is-active" : "";
            const aliases = (city.topAliases || []).slice(0, 3).map(function (item) {
                return '<span class="tag">' + escapeHtml(item.alias) + '×' + escapeHtml(item.freq) + '</span>';
            }).join("");

            return [
                '<button class="city-item' + active + '" type="button" data-city-id="' + escapeHtml(city.id) + '">',
                '<div class="city-title">',
                '<strong>' + escapeHtml(city.city) + '</strong>',
                '<span>' + escapeHtml(city.poemCount) + ' 首</span>',
                '</div>',
                '<div class="city-meta">' + escapeHtml(city.province) + ' / 地名命中 ' + escapeHtml(city.freq) + ' 次</div>',
                '<div class="tags">' + aliases + '</div>',
                '</button>'
            ].join("");
        }).join("");

        Array.prototype.forEach.call(els.cityList.querySelectorAll(".city-item"), function (node) {
            node.addEventListener("mouseenter", function () {
                const city = allCities.find(function (item) {
                    return item.id === node.dataset.cityId;
                });

                if (city) {
                    activeCityId = city.id;
                    renderCitySummary(city, false);
                    renderCityList(filteredCities());
                }
            });

            node.addEventListener("click", function () {
                const city = allCities.find(function (item) {
                    return item.id === node.dataset.cityId;
                });

                if (city) {
                    activeCityId = city.id;
                    clickedCityId = city.id;
                    renderCitySummary(city, true);
                    renderFullPoems(city);
                    renderCityList(filteredCities());

                    if (chart) {
                        chart.dispatchAction({
                            type: "select",
                            name: city.geoName
                        });
                    }
                }
            });
        });
    }

    function renderEmptyCity(name) {
        els.activeCityTitle.textContent = name || "未命中城市";
        els.activeCitySub.textContent = "该市暂无诗作命中";
        els.activeCityStats.innerHTML = [
            '<div class="city-stat"><span>诗作关联</span><strong>0</strong></div>',
            '<div class="city-stat"><span>地名命中</span><strong>0</strong></div>',
            '<div class="city-stat"><span>相关诗人</span><strong>0</strong></div>'
        ].join("");
        els.activeCityTags.innerHTML = "";
        els.previewList.innerHTML = '<div class="empty">该市目前没有匹配到诗作。</div>';
        els.poemPanelHint.textContent = "暂无诗词";
        els.poemPanel.innerHTML = '<div class="empty">该市目前没有完整诗词记录。</div>';
    }

    function renderCitySummary(city, fromClick) {
        if (!city) {
            els.activeCityTitle.textContent = "城市摘要";
            els.activeCitySub.textContent = "请选择城市";
            els.activeCityStats.innerHTML = "";
            els.activeCityTags.innerHTML = "";
            els.previewList.innerHTML = '<div class="empty">滑过或点击一个城市后，这里会显示诗作摘要。</div>';
            return;
        }

        els.activeCityTitle.textContent = city.province + " · " + city.city;
        els.activeCitySub.textContent = fromClick ? "已点击锁定" : "鼠标滑过预览";

        els.activeCityStats.innerHTML = [
            '<div class="city-stat"><span>诗作关联</span><strong>' + escapeHtml(city.poemCount) + '</strong></div>',
            '<div class="city-stat"><span>地名命中</span><strong>' + escapeHtml(city.freq) + '</strong></div>',
            '<div class="city-stat"><span>相关诗人</span><strong>' + escapeHtml((city.topPoets || []).length) + '</strong></div>'
        ].join("");

        els.activeCityTags.innerHTML = (city.topAliases || []).slice(0, 8).map(function (item) {
            return '<span class="tag">' + escapeHtml(item.alias) + ' × ' + escapeHtml(item.freq) + '</span>';
        }).join("");

        const poems = city.previewPoems || [];
        if (!poems.length) {
            els.previewList.innerHTML = '<div class="empty">这个城市暂无诗作示例。</div>';
            return;
        }

        els.previewList.innerHTML = poems.map(function (poem) {
            return [
                '<article class="preview-poem">',
                '<strong>' + escapeHtml(poem.poet) + '《' + escapeHtml(poem.title) + '》</strong>',
                '<small>' + escapeHtml(poem.dynasty) + ' / ' + escapeHtml(poem.school || "未分") + ' / 命中 ' + escapeHtml(poem.freq) + ' 次</small>',
                '<small>' + escapeHtml(poem.snippet || "") + '</small>',
                '</article>'
            ].join("");
        }).join("");
    }

    function highlightBody(text, aliases) {
        let safe = escapeHtml(text || "");

        (aliases || []).forEach(function (alias) {
            if (!alias) {
                return;
            }

            const escaped = escapeHtml(alias);
            safe = safe.split(escaped).join("<mark>" + escaped + "</mark>");
        });

        return safe;
    }

    function renderFullPoems(city) {
        if (!city) {
            els.poemPanelHint.textContent = "点击城市后显示";
            els.poemPanel.innerHTML = '<div class="empty">暂未选择城市。</div>';
            return;
        }

        const poems = city.poems || [];
        els.poemPanelHint.textContent = city.city + " · " + poems.length + " 首";

        if (!poems.length) {
            els.poemPanel.innerHTML = '<div class="empty">该城市暂无完整诗词。</div>';
            return;
        }

        els.poemPanel.innerHTML = poems.map(function (poem) {
            const aliasText = (poem.aliases || []).join("、");

            return [
                '<article class="poem-card">',
                '<h3>' + escapeHtml(poem.poet) + '《' + escapeHtml(poem.title) + '》</h3>',
                '<div class="poem-meta">',
                escapeHtml(poem.dynasty) + ' / ' + escapeHtml(poem.school || "未分"),
                ' / 命中 ' + escapeHtml(poem.freq) + ' 次',
                aliasText ? ' / 地名：' + escapeHtml(aliasText) : '',
                '</div>',
                '<div class="poem-body">' + highlightBody(poem.body || "", poem.aliases || []) + '</div>',
                '</article>'
            ].join("");
        }).join("");
    }

    function renderAll() {
        const rows = filteredCities();

        if (!rows.some(function (city) { return city.id === activeCityId; })) {
            activeCityId = rows.length ? rows[0].id : "";
        }

        if (!rows.some(function (city) { return city.id === clickedCityId; })) {
            clickedCityId = "";
        }

        renderMap(rows);
        renderCityList(rows);

        const activeCity = allCities.find(function (city) {
            return city.id === activeCityId;
        });

        renderCitySummary(activeCity, activeCity && activeCity.id === clickedCityId);

        if (clickedCityId) {
            const clicked = allCities.find(function (city) {
                return city.id === clickedCityId;
            });
            renderFullPoems(clicked);
        } else if (!rows.length) {
            renderFullPoems(null);
        }
    }

    els.query.addEventListener("input", renderAll);
    els.sort.addEventListener("change", renderAll);
    els.reset.addEventListener("click", function () {
        els.query.value = "";
        els.sort.value = "poemCount";
        activeCityId = allCities.length ? allCities[0].id : "";
        clickedCityId = "";
        renderAll();
    });

    renderAll();
    </script>
</body>
</html>
"""

    replacements = {
        "__PAYLOAD__": data_json,
        "__GEO_FEATURE_COUNT__": str(summary["geoFeatureCount"]),
        "__CITY_COUNT__": str(summary["cityCount"]),
        "__POEM_CITY_REFS__": str(summary["poemCityRefs"]),
        "__UNMATCHED_COUNT__": str(summary["unmatchedPlaceCount"]),
    }

    for key, value in replacements.items():
        html = html.replace(key, value)

    html = inject_static_page_base(
        html,
        page_key="city-poem-map",
        accent="#38bdf8",
        accent_2="#a78bfa",
        accent_3="#34d399",
        backlink_href="index.html",
    )

    OUT_HTML.write_text(html, encoding="utf-8")

    print(
        f"  [ok] saved {OUT_HTML}  "
        f"({summary['cityCount']} 个有诗城市 / "
        f"{summary['geoFeatureCount']} 个市级边界 / "
        f"{summary['poemCityRefs']} 条诗作关联 / "
        f"未匹配 {summary['unmatchedPlaceCount']} 个地名 / "
        f"数据源：{payload['source']})"
    )


if __name__ == "__main__":
    render()