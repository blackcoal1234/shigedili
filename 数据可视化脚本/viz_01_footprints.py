
from __future__ import annotations

import json
import re
import ssl
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path

import pymysql
from pyecharts import options as opts
from pyecharts.charts import Bar, Geo, Map, Page
from pyecharts.commons.utils import JsCode
from pyecharts.globals import ChartType

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from config import DB_NAME, MYSQL, OUTPUT_DIR
from viz_assets import inject_index_backlink

POEM_SAMPLE_LIMIT = 8
POET_PLACE_SAMPLE_LIMIT = 6
CNKGRAPH_CACHE = ROOT / "data" / "cnkgraph_poet_life_cache.json"
PYECHARTS_ASSET_HOST = "https://assets.pyecharts.org/assets/v6/"
LOCAL_PYECHARTS_ASSET_DIR = OUTPUT_DIR / "assets" / "pyecharts" / "v6"
PYECHARTS_ASSETS = ("echarts.min.js", "maps/china.js")
HIGHLIGHT_SERIES_NAME = "诗人足迹高亮"

FOOTPRINT_TOOLTIP_FORMATTER = JsCode(
    """
    function (params) {
        var data = params.data || {};
        var value = data.value || [];
        var freq = data.freq || value[2] || 0;
        var poems = data.poems || [];
        var poetCount = data.poetCount || 0;
        var poemCount = data.poemCount || poems.length;
        function esc(text) {
            return String(text == null ? '' : text).replace(/[&<>"']/g, function (ch) {
                var code = ch.charCodeAt(0);
                if (code === 38) { return '&amp;'; }
                if (code === 60) { return '&lt;'; }
                if (code === 62) { return '&gt;'; }
                if (code === 34) { return '&quot;'; }
                if (code === 39) { return '&#39;'; }
                return ch;
            });
        }
        var html = '<div style="max-width:360px;line-height:1.6;white-space:normal;">'
            + '<strong>' + esc(data.modern || params.name) + '</strong>'
            + '<br/>' + esc(params.seriesName) + ' / 入诗次数 ' + esc(freq);
        if (data.poet) {
            html += '<br/>诗人：' + esc(data.poet);
        } else {
            html += '<br/>相关诗人 ' + esc(poetCount) + ' 位 / 诗作 ' + esc(poemCount) + ' 首';
        }
        if (poems.length) {
            html += '<br/><span style="color:#94a3b8;">诗作示例</span>';
            for (var i = 0; i < poems.length; i += 1) {
                var item = poems[i] || {};
                html += '<br/>' + esc(item.poet || data.poet || '') + '《' + esc(item.title) + '》 ×' + esc(item.freq || 1);
            }
        }
        if (data.hiddenPoemCount && data.hiddenPoemCount > 0) {
            html += '<br/><span style="color:#94a3b8;">另有 ' + esc(data.hiddenPoemCount) + ' 首</span>';
        }
        return html + '</div>';
    }
    """
)


PROVINCE_MAP_NAMES = {
    "北京": "北京市",
    "天津": "天津市",
    "上海": "上海市",
    "重庆": "重庆市",
    "河北": "河北省",
    "山西": "山西省",
    "辽宁": "辽宁省",
    "吉林": "吉林省",
    "黑龙江": "黑龙江省",
    "江苏": "江苏省",
    "浙江": "浙江省",
    "安徽": "安徽省",
    "福建": "福建省",
    "江西": "江西省",
    "山东": "山东省",
    "河南": "河南省",
    "湖北": "湖北省",
    "湖南": "湖南省",
    "广东": "广东省",
    "海南": "海南省",
    "四川": "四川省",
    "贵州": "贵州省",
    "云南": "云南省",
    "陕西": "陕西省",
    "甘肃": "甘肃省",
    "青海": "青海省",
    "台湾": "台湾省",
    "内蒙古": "内蒙古自治区",
    "广西": "广西壮族自治区",
    "西藏": "西藏自治区",
    "宁夏": "宁夏回族自治区",
    "新疆": "新疆维吾尔自治区",
    "香港": "香港特别行政区",
    "澳门": "澳门特别行政区",
}


def map_province_name(name: str) -> str:
    return PROVINCE_MAP_NAMES.get(name, name)


def conn():
    return pymysql.connect(**MYSQL, database=DB_NAME)


def clean_text(value: object) -> str:
    return str(value or "").strip()


def poem_snippet(body: str | None, limit: int = 84) -> str:
    text = re.sub(r"\s+", "", body or "")
    return text[:limit] + ("..." if len(text) > limit else "")


def download_pyecharts_asset(url: str) -> bytes:
    """下载 pyecharts 静态资源；证书链异常时仅对静态资源降级一次。"""
    try:
        with urllib.request.urlopen(url, timeout=20) as response:
            return response.read()
    except (ssl.SSLError, urllib.error.URLError):
        context = ssl._create_unverified_context()
        with urllib.request.urlopen(url, timeout=20, context=context) as response:
            return response.read()


def ensure_local_pyecharts_assets() -> dict[str, str]:
    """确保足迹页依赖的 ECharts 与中国地图资源可本地加载。"""
    replacements = {}
    for asset in PYECHARTS_ASSETS:
        local = LOCAL_PYECHARTS_ASSET_DIR / asset
        remote = PYECHARTS_ASSET_HOST + asset
        replacements[remote] = f"assets/pyecharts/v6/{asset}"
        if local.exists() and local.stat().st_size > 1024:
            continue

        local.parent.mkdir(parents=True, exist_ok=True)
        data = download_pyecharts_asset(remote)
        if len(data) <= 1024:
            raise RuntimeError(f"pyecharts 静态资源下载异常：{remote}")
        tmp = local.with_suffix(local.suffix + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(local)

    return replacements


def localize_pyecharts_assets(html_path: Path) -> None:

    replacements = ensure_local_pyecharts_assets()
    html = html_path.read_text(encoding="utf-8")
    for remote, local in replacements.items():
        html = html.replace(remote, local)
    html = inject_index_backlink(html)
    html_path.write_text(html, encoding="utf-8")


def all_dynasty_points() -> dict[str, list[tuple[str, float, float, int]]]:
    """返回 {dynasty: [(modern, lon, lat, freq)]}。"""
    sql = """
        SELECT pt.dynasty, pl.modern, pl.lon, pl.lat, SUM(pp.freq)
          FROM t_poet pt
          JOIN t_poem pm ON pm.poet_id = pt.poet_id
          JOIN t_poem_place pp ON pp.poem_id = pm.poem_id
          JOIN t_place pl ON pl.place_id = pp.place_id
         WHERE pl.modern IS NOT NULL AND pl.modern <> ''
           AND pl.lon IS NOT NULL AND pl.lat IS NOT NULL
         GROUP BY pt.dynasty, pl.modern, pl.lon, pl.lat
    """
    out: dict[str, list[tuple[str, float, float, int]]] = defaultdict(list)
    with conn() as c, c.cursor() as cur:
        cur.execute(sql)
        for dyn, modern, lon, lat, freq in cur.fetchall():
            out[clean_text(dyn) or "未标"].append((clean_text(modern), float(lon), float(lat), int(freq or 0)))
    return out


def _new_tooltip_meta() -> dict:
    return {"poets": set(), "poems": set(), "samples": []}


def _add_tooltip_row(meta: dict, poet: str, poem_id: int, title: str, freq: int) -> None:
    meta["poets"].add(poet)
    meta["poems"].add(poem_id)
    if len(meta["samples"]) < POEM_SAMPLE_LIMIT:
        meta["samples"].append({"poet": poet, "title": title, "freq": int(freq or 0)})


def _finalize_tooltips(raw: dict[tuple[str, str], dict]) -> dict[tuple[str, str], dict]:
    out = {}
    for key, meta in raw.items():
        poem_count = len(meta["poems"])
        samples = meta["samples"][:POEM_SAMPLE_LIMIT]
        out[key] = {
            "poetCount": len(meta["poets"]),
            "poemCount": poem_count,
            "hiddenPoemCount": max(0, poem_count - len(samples)),
            "samples": samples,
        }
    return out


def load_poem_tooltips() -> tuple[dict[tuple[str, str], dict], dict[tuple[str, str], dict]]:
    """读取足迹点 tooltip 所需的诗题样例。"""
    sql = """
        SELECT pt.dynasty, pt.name, pm.poem_id, pm.title, pl.modern, SUM(pp.freq) AS f
          FROM t_poet pt
          JOIN t_poem pm ON pm.poet_id = pt.poet_id
          JOIN t_poem_place pp ON pp.poem_id = pm.poem_id
          JOIN t_place pl ON pl.place_id = pp.place_id
         WHERE pl.modern IS NOT NULL AND pl.modern <> ''
         GROUP BY pt.dynasty, pt.name, pm.poem_id, pm.title, pl.modern
         ORDER BY f DESC, pt.name, pm.title
    """
    dynasty_tooltips = defaultdict(_new_tooltip_meta)
    poet_tooltips = defaultdict(_new_tooltip_meta)
    with conn() as c, c.cursor() as cur:
        cur.execute(sql)
        for dynasty, poet, poem_id, title, modern, freq in cur.fetchall():
            dynasty_key = (clean_text(dynasty) or "未标", clean_text(modern))
            poet_key = (clean_text(poet), clean_text(modern))
            _add_tooltip_row(dynasty_tooltips[dynasty_key], clean_text(poet), int(poem_id), clean_text(title), int(freq or 0))
            _add_tooltip_row(poet_tooltips[poet_key], clean_text(poet), int(poem_id), clean_text(title), int(freq or 0))
    return _finalize_tooltips(dynasty_tooltips), _finalize_tooltips(poet_tooltips)


def find_series(geo: Geo, series_name: str) -> dict:
    """按名称找到指定 Geo series，避免依赖追加顺序。"""
    for series in geo.options.get("series", []):
        if series.get("name") == series_name:
            return series
    raise KeyError(f"找不到 Geo series：{series_name}")


def attach_tooltip_metadata(geo: Geo, series_name: str, meta_by_city: dict[str, dict]) -> None:
    """给指定 Geo 散点 series 附加 tooltip 元数据。"""
    series = find_series(geo, series_name)
    for item in series.get("data", []):
        city_meta = meta_by_city.get(item.get("name"))
        if not city_meta:
            continue
        item["poems"] = city_meta["samples"]
        item["poetCount"] = city_meta["poetCount"]
        item["poemCount"] = city_meta["poemCount"]
        item["hiddenPoemCount"] = city_meta["hiddenPoemCount"]
        if item.get("value"):
            item["freq"] = item["value"][2]


def province_freq() -> dict[str, int]:
    sql = """
        SELECT pl.province, SUM(pp.freq) AS f
          FROM t_place pl
          JOIN t_poem_place pp ON pp.place_id = pl.place_id
         WHERE pl.province IS NOT NULL AND pl.province <> ''
         GROUP BY pl.province
    """
    out = defaultdict(int)
    with conn() as c, c.cursor() as cur:
        cur.execute(sql)
        for prov, freq in cur.fetchall():
            out[map_province_name(clean_text(prov))] += int(freq or 0)
    return dict(out)


def top_places(limit: int = 15) -> list[tuple[str, str, int]]:
    sql = """
        SELECT pl.alias, pl.modern, SUM(pp.freq) AS f
          FROM t_place pl
          JOIN t_poem_place pp ON pp.place_id = pl.place_id
         GROUP BY pl.place_id
         ORDER BY f DESC
         LIMIT %s
    """
    with conn() as c, c.cursor() as cur:
        cur.execute(sql, (limit,))
        return [(clean_text(alias), clean_text(modern), int(freq or 0)) for alias, modern, freq in cur.fetchall()]


def top_modern_places(limit: int = 15) -> list[tuple[str, int, int, int, str]]:
    sql = """
        SELECT pl.modern,
               SUM(pp.freq) AS f,
               COUNT(DISTINCT pp.poem_id) AS poem_count,
               COUNT(DISTINCT pl.alias) AS alias_count,
               GROUP_CONCAT(DISTINCT pl.alias ORDER BY pl.alias SEPARATOR '、') AS aliases
          FROM t_place pl
          JOIN t_poem_place pp ON pp.place_id = pl.place_id
         WHERE pl.modern IS NOT NULL AND pl.modern <> ''
         GROUP BY pl.modern
         ORDER BY f DESC, poem_count DESC, pl.modern
         LIMIT %s
    """
    with conn() as c, c.cursor() as cur:
        cur.execute(sql, (limit,))
        return [
            (clean_text(modern), int(freq or 0), int(poem_count or 0), int(alias_count or 0), clean_text(aliases))
            for modern, freq, poem_count, alias_count, aliases in cur.fetchall()
        ]


def load_poet_summaries() -> dict[str, dict]:
    sql = """
        SELECT name, dynasty, COALESCE(NULLIF(school, ''), '未分'), poem_count
          FROM t_poet
         WHERE poem_count > 0
         ORDER BY dynasty, name
    """
    summaries: dict[str, dict] = {}
    with conn() as c, c.cursor() as cur:
        cur.execute(sql)
        for name, dynasty, school, poem_count in cur.fetchall():
            name = clean_text(name)
            summaries[name] = {
                "name": name,
                "dynasty": clean_text(dynasty),
                "school": clean_text(school) or "未分",
                "poemCount": int(poem_count or 0),
                "placeCount": 0,
                "footprintFreq": 0,
            }
    return summaries


def load_poet_place_samples() -> dict[tuple[str, str], list[dict]]:
    sql = """
        SELECT pt.name, pl.modern, pm.poem_id, pm.title, pm.body, SUM(pp.freq) AS f
          FROM t_poet pt
          JOIN t_poem pm ON pm.poet_id = pt.poet_id
          JOIN t_poem_place pp ON pp.poem_id = pm.poem_id
          JOIN t_place pl ON pl.place_id = pp.place_id
         WHERE pl.modern IS NOT NULL AND pl.modern <> ''
         GROUP BY pt.name, pl.modern, pm.poem_id, pm.title, pm.body
         ORDER BY pt.name, pl.modern, f DESC, pm.title
    """
    samples: dict[tuple[str, str], list[dict]] = defaultdict(list)
    with conn() as c, c.cursor() as cur:
        cur.execute(sql)
        for poet, modern, poem_id, title, body, freq in cur.fetchall():
            key = (clean_text(poet), clean_text(modern))
            if len(samples[key]) >= POET_PLACE_SAMPLE_LIMIT:
                continue
            samples[key].append(
                {
                    "poemId": int(poem_id),
                    "poet": clean_text(poet),
                    "title": clean_text(title),
                    "freq": int(freq or 0),
                    "snippet": poem_snippet(body),
                }
            )
    return samples


def load_poet_places(poet_summaries: dict[str, dict]) -> dict[str, list[dict]]:
    sql = """
        SELECT pt.name,
               pt.dynasty,
               COALESCE(NULLIF(pt.school, ''), '未分'),
               pl.modern,
               COALESCE(pl.province, ''),
               pl.lon,
               pl.lat,
               SUM(pp.freq) AS f,
               COUNT(DISTINCT pm.poem_id) AS poem_count,
               GROUP_CONCAT(DISTINCT pl.alias ORDER BY pl.alias SEPARATOR '、') AS aliases
          FROM t_poet pt
          JOIN t_poem pm ON pm.poet_id = pt.poet_id
          JOIN t_poem_place pp ON pp.poem_id = pm.poem_id
          JOIN t_place pl ON pl.place_id = pp.place_id
         WHERE pl.modern IS NOT NULL AND pl.modern <> ''
           AND pl.lon IS NOT NULL AND pl.lat IS NOT NULL
         GROUP BY pt.name, pt.dynasty, pt.school, pl.modern, pl.province, pl.lon, pl.lat
         ORDER BY pt.name, f DESC, poem_count DESC, pl.modern
    """
    samples = load_poet_place_samples()
    places: dict[str, list[dict]] = defaultdict(list)
    with conn() as c, c.cursor() as cur:
        cur.execute(sql)
        for poet, dynasty, school, modern, province, lon, lat, freq, poem_count, aliases in cur.fetchall():
            poet_name = clean_text(poet)
            modern_name = clean_text(modern)
            item = {
                "poet": poet_name,
                "dynasty": clean_text(dynasty),
                "school": clean_text(school) or "未分",
                "modern": modern_name,
                "province": clean_text(province),
                "lon": float(lon),
                "lat": float(lat),
                "freq": int(freq or 0),
                "poemCount": int(poem_count or 0),
                "aliases": clean_text(aliases),
                "poems": samples.get((poet_name, modern_name), []),
            }
            places[poet_name].append(item)
            if poet_name in poet_summaries:
                poet_summaries[poet_name]["placeCount"] += 1
                poet_summaries[poet_name]["footprintFreq"] += int(freq or 0)
    return dict(places)


def load_cnkgraph_cache(path: Path = CNKGRAPH_CACHE) -> dict:
    """读取 CNKGraph 生平缓存；缺失时保持可离线降级。"""
    if not path.exists():
        return {"status": "missing", "poets": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {"status": "parse_failed", "error": str(exc), "poets": {}}
    if not isinstance(data, dict):
        return {"status": "parse_failed", "error": "cache root is not object", "poets": {}}
    poets = data.get("poets")
    if not isinstance(poets, dict):
        data["poets"] = {}
    data.setdefault("status", "ok")
    return data


def build_knowledge_data(poet_summaries: dict[str, dict], poet_places: dict[str, list[dict]]) -> dict:
    cache = load_cnkgraph_cache()
    poets = sorted(
        poet_summaries,
        key=lambda name: (
            str(poet_summaries[name].get("dynasty") or ""),
            -int(poet_summaries[name].get("poemCount") or 0),
            name,
        ),
    )
    return {
        "poets": poets,
        "poetSummaries": poet_summaries,
        "poetPlaces": poet_places,
        "cnkgraphCache": cache,
        "stats": {
            "poetCount": len(poets),
            "poetWithPlaceCount": sum(1 for name in poets if poet_places.get(name)),
            "poetPlaceCount": sum(len(items) for items in poet_places.values()),
            "localCachePoetCount": len(cache.get("poets", {})),
        },
    }


def json_for_script(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def inject_footprint_knowledge_ui(html_path: Path, stats: dict[str, int], knowledge_data: dict) -> None:
    """注入搜索、AI 答疑面板、知识库数据和响应式处理。"""
    html = html_path.read_text(encoding="utf-8")
    viewport = '<meta name="viewport" content="width=device-width, initial-scale=1.0">'
    if viewport not in html:
        html = html.replace('<meta charset="UTF-8">', f'<meta charset="UTF-8">\n    {viewport}', 1)

    if "shixing-footprint-knowledge-ui" not in html:
        style = """
    <style id="shixing-footprint-knowledge-ui">
        :root {
            --footprint-bg: #0f1115;
            --footprint-panel: #1a1d24;
            --footprint-surface: #252932;
            --footprint-text: #f0f6fc;
            --footprint-muted: #8b949e;
            --footprint-accent: #58a6ff;
            --footprint-accent-2: #2ea043;
            --footprint-line: #30363d;
        }
        html, body {
            margin: 0;
            padding: 0;
            height: 100vh;
            overflow: hidden;
            background: var(--footprint-bg);
            color: var(--footprint-text);
            font-family: "Microsoft YaHei", "PingFang SC", "Segoe UI", Arial, sans-serif;
        }
        body {
            display: flex;
            flex-direction: row;
            box-sizing: border-box;
        }
        .shixing-index-backlink {
            position: fixed;
            left: 18px;
            bottom: 18px;
            top: auto;
            z-index: 9999;
            width: auto;
            margin: 0;
            pointer-events: none;
        }
        .shixing-index-backlink a {
            min-height: 36px;
            padding: 0 14px;
            border-color: var(--footprint-line);
            background: rgba(37, 41, 50, 0.96);
            color: var(--footprint-muted);
            box-shadow: 0 10px 28px rgba(0, 0, 0, 0.34);
        }
        .footprint-knowledge-shell {
            flex: 0 0 380px;
            min-width: 300px;
            max-width: 520px;
            height: 100vh;
            margin: 0;
            padding: 22px;
            box-sizing: border-box;
            overflow-y: auto;
            resize: horizontal;
            background: var(--footprint-panel);
            border-right: 1px solid var(--footprint-line);
        }
        .footprint-knowledge-shell::-webkit-scrollbar,
        body > .box::-webkit-scrollbar,
        .footprint-result-list::-webkit-scrollbar {
            width: 8px;
            height: 8px;
        }
        .footprint-knowledge-shell::-webkit-scrollbar-thumb,
        body > .box::-webkit-scrollbar-thumb,
        .footprint-result-list::-webkit-scrollbar-thumb {
            background: var(--footprint-line);
            border-radius: 999px;
        }
        .footprint-knowledge-layout {
            display: flex;
            flex-direction: column;
            gap: 24px;
        }
        .footprint-tool-panel {
            display: flex;
            flex-direction: column;
            min-width: 0;
        }
        .footprint-tool-panel h2 {
            margin: 0 0 16px;
            padding-bottom: 12px;
            border-bottom: 1px solid var(--footprint-line);
            color: var(--footprint-text);
            font-size: 16px;
            font-weight: 800;
            line-height: 1.35;
            letter-spacing: 0;
        }
        .footprint-tool-panel h3 {
            margin: 22px 0 10px;
            color: var(--footprint-muted);
            font-size: 13px;
            font-weight: 700;
            line-height: 1.35;
            letter-spacing: 0;
        }
        .footprint-stats {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 10px;
            margin-bottom: 16px;
        }
        .footprint-stats > .footprint-stat:last-child {
            grid-column: 1 / -1;
        }
        .footprint-stat {
            min-height: 64px;
            border: 1px solid var(--footprint-line);
            border-radius: 8px;
            background: var(--footprint-surface);
            padding: 12px;
            box-sizing: border-box;
        }
        .footprint-stat span,
        .footprint-stat strong {
            display: block;
        }
        .footprint-stat span {
            color: var(--footprint-muted);
            font-size: 12px;
            line-height: 1.35;
        }
        .footprint-stat strong {
            margin-top: 5px;
            color: var(--footprint-accent);
            font-size: 23px;
            line-height: 1.1;
            letter-spacing: 0;
            font-family: Consolas, "Courier New", monospace;
        }
        .footprint-search-row,
        .footprint-ai-key {
            display: grid;
            grid-template-columns: minmax(0, 1fr) auto;
            gap: 8px;
            align-items: center;
        }
        .footprint-ai-key {
            margin: 8px 0 12px;
        }
        .footprint-search-row input,
        .footprint-ai-key input,
        .footprint-ai-question textarea {
            width: 100%;
            box-sizing: border-box;
            border: 1px solid var(--footprint-line);
            border-radius: 8px;
            background: #0d1117;
            color: var(--footprint-text);
            font: inherit;
            letter-spacing: 0;
        }
        .footprint-search-row input,
        .footprint-ai-key input {
            height: 38px;
            padding: 0 10px;
        }
        .footprint-ai-question textarea {
            min-height: 96px;
            padding: 10px;
            resize: vertical;
        }
        .footprint-button {
            min-height: 38px;
            border: 1px solid var(--footprint-accent);
            border-radius: 8px;
            background: var(--footprint-accent);
            color: #07111f;
            padding: 0 12px;
            font: inherit;
            font-weight: 700;
            cursor: pointer;
            white-space: nowrap;
        }
        .footprint-button.secondary {
            border-color: var(--footprint-line);
            background: var(--footprint-surface);
            color: var(--footprint-text);
        }
        .footprint-button:focus,
        .footprint-search-row input:focus,
        .footprint-ai-key input:focus,
        .footprint-ai-question textarea:focus {
            outline: 2px solid var(--footprint-accent);
            outline-offset: 2px;
        }
        .footprint-selection-summary,
        .footprint-ai-context,
        .footprint-ai-answer,
        .footprint-ai-status {
            border: 1px solid var(--footprint-line);
            border-radius: 8px;
            background: var(--footprint-surface);
            padding: 10px;
            line-height: 1.65;
            font-size: 13px;
            color: var(--footprint-muted);
        }
        .footprint-selection-summary {
            margin: 10px 0;
        }
        .footprint-result-list {
            display: grid;
            grid-template-columns: 1fr;
            gap: 8px;
            max-height: 280px;
            overflow: auto;
        }
        .footprint-result-list button {
            text-align: left;
            border: 1px solid var(--footprint-line);
            border-radius: 8px;
            background: var(--footprint-surface);
            padding: 9px 10px;
            color: var(--footprint-text);
            cursor: pointer;
            font: inherit;
            line-height: 1.45;
        }
        .footprint-result-list button strong,
        .footprint-result-list button span {
            display: block;
            overflow-wrap: anywhere;
        }
        .footprint-result-list button span {
            margin-top: 2px;
            color: var(--footprint-muted);
            font-size: 12px;
        }
        .footprint-result-list button.is-active,
        .footprint-place-list button.is-active {
            border-color: var(--footprint-accent);
            box-shadow: inset 0 0 0 1px var(--footprint-accent);
        }
        .footprint-place-list {
            display: flex;
            flex-wrap: wrap;
            gap: 6px;
            margin-top: 10px;
        }
        .footprint-place-list button {
            border: 1px solid var(--footprint-line);
            border-radius: 999px;
            background: var(--footprint-surface);
            color: var(--footprint-muted);
            padding: 5px 9px;
            font-size: 12px;
            cursor: pointer;
        }
        .footprint-ai-panel {
            min-height: 100%;
        }
        .footprint-ai-actions,
        .footprint-live-actions {
            display: flex;
            gap: 8px;
            align-items: center;
            justify-content: flex-end;
            margin-top: 8px;
            flex-wrap: wrap;
        }
        .footprint-live-actions {
            justify-content: flex-start;
            margin: 8px 0 10px;
        }
        .footprint-live-actions .footprint-ai-status {
            flex: 1 1 180px;
            margin-top: 0;
        }
        .footprint-ai-answer {
            margin-top: 10px;
            min-height: 92px;
            white-space: pre-wrap;
        }
        .footprint-ai-status {
            margin-top: 8px;
        }
        .footprint-cache-summary {
            margin-top: 8px;
        }
        .footprint-cache-header {
            display: flex;
            gap: 8px;
            align-items: baseline;
            flex-wrap: wrap;
            color: var(--footprint-text);
        }
        .footprint-cache-meta {
            color: var(--footprint-muted);
            font-size: 12px;
        }
        .footprint-cache-section {
            margin-top: 8px;
        }
        .footprint-cache-section strong {
            display: block;
            color: var(--footprint-text);
            margin-bottom: 2px;
        }
        .footprint-cache-section ul {
            margin: 4px 0 0 18px;
            padding: 0;
        }
        .footprint-cache-section li {
            margin: 2px 0;
        }
        .footprint-cache-link {
            color: var(--footprint-accent);
            text-decoration: none;
            border-bottom: 1px solid rgba(88, 166, 255, 0.32);
        }
        .footprint-cache-link:hover {
            border-bottom-color: var(--footprint-accent);
        }
        .footprint-muted {
            color: var(--footprint-muted);
        }
        body > .box {
            flex: 1 1 auto !important;
            min-width: 0;
            height: 100vh !important;
            margin: 0 !important;
            padding: 22px !important;
            box-sizing: border-box;
            overflow-y: auto;
            overflow-x: hidden;
            display: flex !important;
            flex-direction: column !important;
            flex-wrap: nowrap !important;
            justify-content: flex-start !important;
            gap: 24px !important;
            background: var(--footprint-bg);
        }
        body > .box > br {
            display: none;
        }
        .chart-container {
            flex: 0 0 auto !important;
            width: 100% !important;
            max-width: none !important;
            min-width: 0 !important;
            height: min(72vh, var(--chart-height, 720px)) !important;
            min-height: 460px;
            box-sizing: border-box;
            border: 1px solid var(--footprint-line);
            border-radius: 8px;
            background: var(--footprint-panel);
            box-shadow: 0 14px 34px rgba(0, 0, 0, 0.24);
            overflow: hidden;
        }
        @media (max-width: 920px) {
            html, body {
                height: auto;
                min-height: 100vh;
                overflow: auto;
            }
            body {
                display: block;
            }
            .footprint-knowledge-shell {
                width: 100%;
                max-width: none;
                height: auto;
                min-width: 0;
                resize: none;
                border-right: 0;
                border-bottom: 1px solid var(--footprint-line);
            }
            .footprint-stats {
                grid-template-columns: repeat(3, minmax(0, 1fr));
            }
            .footprint-stats > .footprint-stat:last-child {
                grid-column: auto;
            }
            body > .box {
                height: auto !important;
                min-height: 70vh;
                overflow: visible;
            }
            .chart-container {
                height: min(70vh, var(--chart-height, 720px)) !important;
            }
        }
        @media (max-width: 640px) {
            .footprint-knowledge-shell,
            body > .box {
                padding: 12px !important;
            }
            .footprint-stats,
            .footprint-search-row,
            .footprint-ai-key {
                grid-template-columns: 1fr;
            }
            .chart-container {
                min-height: 380px;
            }
        }
    </style>
"""
        html = html.replace("</head>", f"{style}</head>", 1)

    if '<section id="footprintKnowledgeShell"' not in html:
        panel = """
    <section id="footprintKnowledgeShell" class="footprint-knowledge-shell" aria-label="诗人足迹知识库">
        <div class="footprint-knowledge-layout">
            <div class="footprint-tool-panel">
                <h2>诗人搜索</h2>
                <div class="footprint-stats" aria-label="当前足迹统计">
                    <div class="footprint-stat" data-stat-key="all-footprints" data-value="{all_footprints}">
                        <span>全员足迹</span><strong>{all_footprints}</strong>
                    </div>
                    <div class="footprint-stat" data-stat-key="poet-count" data-value="{poet_count}">
                        <span>诗人数量</span><strong>{poet_count}</strong>
                    </div>
                    <div class="footprint-stat" data-stat-key="cache-count" data-value="{cache_count}">
                        <span>本地缓存</span><strong>{cache_count}</strong>
                    </div>
                </div>
                <div class="footprint-search-row">
                    <input id="poetSearchInput" type="search" autocomplete="off" placeholder="输入诗人名，例如：李白、杜甫、苏轼">
                    <button id="clearPoetSearchButton" class="footprint-button secondary" type="button">清空</button>
                </div>
                <div id="footprintSelectionSummary" class="footprint-selection-summary"></div>
                <div id="poetResultList" class="footprint-result-list" aria-label="诗人搜索结果"></div>
                <h3>入诗地</h3>
                <div id="poetPlaceList" class="footprint-place-list"></div>
            </div>
            <div id="footprintAiPanel" class="footprint-tool-panel footprint-ai-panel">
                <h2>AI 答疑</h2>
                <div class="footprint-muted">点击地图入诗地或高亮入诗地后，可结合本地诗作、流派和 CNKGraph 缓存向 DeepSeek 提问。</div>
                <div id="footprintAiContext" class="footprint-ai-context">尚未选择诗人入诗地。</div>
                <div class="footprint-live-actions">
                    <button id="crawlCnkgraphButton" class="footprint-button secondary" type="button">现爬 CNKGraph</button>
                    <div id="cnkgraphLiveStatus" class="footprint-ai-status">本地现爬服务默认：http://127.0.0.1:8131。</div>
                </div>
                <h3>DeepSeek Key</h3>
                <div class="footprint-ai-key">
                    <input id="deepseekApiKeyInput" type="password" autocomplete="off" placeholder="sk-...，仅保存到当前浏览器 localStorage">
                    <button id="saveDeepseekKeyButton" class="footprint-button" type="button">保存</button>
                </div>
                <div class="footprint-ai-question">
                    <textarea id="aiQuestionInput" placeholder="例如：这个地点和诗人的流派、生平、诗作背景有什么关系？"></textarea>
                </div>
                <div class="footprint-ai-actions">
                    <button id="askDeepseekButton" class="footprint-button" type="button">一键问 AI</button>
                </div>
                <div id="footprintAiStatus" class="footprint-ai-status">DeepSeek 默认模型：deepseek-v4-flash。</div>
                <div id="footprintAiAnswer" class="footprint-ai-answer"></div>
            </div>
        </div>
    </section>
""".format(
            all_footprints=int(stats.get("all_footprints", 0)),
            poet_count=int(knowledge_data.get("stats", {}).get("poetCount", 0)),
            cache_count=int(knowledge_data.get("stats", {}).get("localCachePoetCount", 0)),
        )
        backlink_match = re.search(
            r'(<nav\b[^>]*class="[^"]*\bshixing-index-backlink\b[^"]*"[^>]*>.*?</nav>)',
            html,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if backlink_match:
            html = f"{html[:backlink_match.end()]}\n{panel}{html[backlink_match.end():]}"
        else:
            body_match = re.search(r"<body\b[^>]*>", html, flags=re.IGNORECASE)
            if body_match:
                html = f"{html[:body_match.end()]}\n{panel}{html[body_match.end():]}"
            else:
                raise RuntimeError("足迹页 HTML 缺少 body 标签，无法注入知识库面板")

    html = re.sub(
        r'class="chart-container" style="width:(\d+)px; height:(\d+)px; ?"',
        (
            r'class="chart-container" data-chart-width="\1" data-chart-height="\2" '
            r'style="--chart-width:\1px; --chart-height:\2px; '
            r'width:100%; max-width:var(--chart-width); height:var(--chart-height); "'
        ),
        html,
    )

    data_script = f"""
    <script id="footprint-knowledge-data">
        window.FOOTPRINT_KNOWLEDGE_DATA = {json_for_script(knowledge_data)};
    </script>
"""
    ui_script = r"""
    <script id="footprint-knowledge-interaction">
        (function () {
            var data = window.FOOTPRINT_KNOWLEDGE_DATA || {};
            var poets = Array.isArray(data.poets) ? data.poets : [];
            var summaries = data.poetSummaries || {};
            var poetPlaces = data.poetPlaces || {};
            var cache = data.cnkgraphCache || { poets: {} };
            cache.poets = cache.poets || {};
            data.cnkgraphCache = cache;
            var currentPoet = "";
            var currentPlace = null;
            var LIVE_CNKGRAPH_ENDPOINT = "http://127.0.0.1:8131/api/cnkgraph/poet-life";

            function $(id) { return document.getElementById(id); }
            function storage() {
                return window.localStorage || {
                    getItem: function () { return null; },
                    setItem: function () {},
                    removeItem: function () {}
                };
            }
            function escapeHtml(text) {
                return String(text == null ? "" : text).replace(/[&<>"']/g, function (ch) {
                    var code = ch.charCodeAt(0);
                    if (code === 38) return "&amp;";
                    if (code === 60) return "&lt;";
                    if (code === 62) return "&gt;";
                    if (code === 34) return "&quot;";
                    if (code === 39) return "&#39;";
                    return ch;
                });
            }
            function summaryOf(poet) {
                return summaries[poet] || { name: poet, dynasty: "", school: "未分", poemCount: 0, placeCount: 0, footprintFreq: 0 };
            }
            function placesOf(poet) {
                return Array.isArray(poetPlaces[poet]) ? poetPlaces[poet] : [];
            }
            function cacheOf(poet) {
                return cache && cache.poets && cache.poets[poet] ? cache.poets[poet] : null;
            }
            function isCacheOk(cached) {
                return !!(cached && cached.status === "ok");
            }
            function isNavigationSummary(text) {
                var value = String(text || "").replace(/\s+/g, "");
                if (!value) return true;
                var navWords = ["唐宋文学编年地图", "年历", "地图", "人物", "专题", "丝绸之路诗词地图"];
                var hitCount = navWords.filter(function (word) { return value.indexOf(word) >= 0; }).length;
                return hitCount >= 4 && value.length < 90;
            }
            function shortText(text, limit) {
                var value = String(text || "").replace(/\s+/g, " ").trim();
                var max = Number(limit || 120);
                if (value.length <= max) return value;
                return value.slice(0, max) + "...";
            }
            function pad2(value) {
                return String(value).padStart(2, "0");
            }
            function formatCacheUpdatedAt(value) {
                if (!value) return "";
                var date = new Date(String(value));
                if (Number.isNaN(date.getTime())) return String(value);
                var utc8 = new Date(date.getTime() + 8 * 60 * 60 * 1000);
                return utc8.getUTCFullYear()
                    + "-" + pad2(utc8.getUTCMonth() + 1)
                    + "-" + pad2(utc8.getUTCDate())
                    + " " + pad2(utc8.getUTCHours())
                    + ":" + pad2(utc8.getUTCMinutes())
                    + ":" + pad2(utc8.getUTCSeconds())
                    + " UTC+8";
            }
            function timelineItems(cached, limit) {
                var items = Array.isArray(cached && cached.timeline) ? cached.timeline : [];
                return items.slice(0, limit || 5).map(function (item) {
                    if (!item || typeof item !== "object") return shortText(item, 120);
                    var year = String(item.year || "").trim();
                    var text = shortText(item.text || "", 120);
                    return year ? year + "：" + text : text;
                }).filter(Boolean);
            }
            function workBackgroundItems(cached, limit) {
                var backgrounds = cached && cached.work_backgrounds && typeof cached.work_backgrounds === "object"
                    ? cached.work_backgrounds
                    : {};
                return Object.keys(backgrounds).slice(0, limit || 4).map(function (title) {
                    return { title: title, text: shortText(backgrounds[title], 120) };
                }).filter(function (item) { return item.title || item.text; });
            }
            function cacheSummaryText(poet) {
                var cached = cacheOf(poet);
                if (isCacheOk(cached)) {
                    var lines = ["状态：已缓存"];
                    var summary = shortText(cached.life_summary || "", 160);
                    if (summary && !isNavigationSummary(summary)) lines.push("生平摘要：" + summary);
                    var timeline = timelineItems(cached, 5);
                    if (timeline.length) lines.push("年谱摘录：" + timeline.join("；"));
                    var backgrounds = workBackgroundItems(cached, 4);
                    if (backgrounds.length) {
                        lines.push("作品背景：" + backgrounds.map(function (item) {
                            return item.title + (item.text ? "：" + item.text : "");
                        }).join("；"));
                    }
                    if (cached.updated_at) lines.push("更新时间：" + formatCacheUpdatedAt(cached.updated_at));
                    if (lines.length === 1) lines.push("已存在 CNKGraph 缓存条目，但暂无可展示的结构化内容。");
                    return lines.join("\n");
                }
                if (cached) {
                    return (cached.status || "unknown") + (cached.note ? "：" + cached.note : "");
                }
                return "本地 CNKGraph 缓存暂无该诗人条目。";
            }
            function cacheSummaryHtml(poet) {
                var cached = cacheOf(poet);
                if (!isCacheOk(cached)) {
                    return '<div class="footprint-cache-summary"><strong>CNKGraph 缓存</strong><br>'
                        + escapeHtml(cacheSummaryText(poet)) + '</div>';
                }
                var summary = shortText(cached.life_summary || "", 180);
                var timeline = timelineItems(cached, 5);
                var backgrounds = workBackgroundItems(cached, 4);
                var html = '<div class="footprint-cache-summary">';
                html += '<div class="footprint-cache-header"><strong>CNKGraph 缓存</strong><span class="footprint-cache-meta">状态：已缓存</span></div>';
                if (cached.source_url) {
                    html += '<div class="footprint-cache-meta">来源：<a class="footprint-cache-link" href="'
                        + escapeHtml(cached.source_url) + '" target="_blank" rel="noopener noreferrer">CNKGraph 生平页</a></div>';
                }
                if (cached.updated_at) {
                    html += '<div class="footprint-cache-meta">更新时间：' + escapeHtml(formatCacheUpdatedAt(cached.updated_at)) + '</div>';
                }
                if (summary && !isNavigationSummary(summary)) {
                    html += '<div class="footprint-cache-section"><strong>生平摘要</strong>' + escapeHtml(summary) + '</div>';
                }
                if (timeline.length) {
                    html += '<div class="footprint-cache-section"><strong>年谱摘录</strong><ul>'
                        + timeline.map(function (item) { return '<li>' + escapeHtml(item) + '</li>'; }).join("")
                        + '</ul></div>';
                }
                if (backgrounds.length) {
                    html += '<div class="footprint-cache-section"><strong>作品背景</strong><ul>'
                        + backgrounds.map(function (item) {
                            return '<li><b>' + escapeHtml(item.title) + '</b>'
                                + (item.text ? '：' + escapeHtml(item.text) : '') + '</li>';
                        }).join("")
                        + '</ul></div>';
                }
                if (!summary && !timeline.length && !backgrounds.length) {
                    html += '<div class="footprint-cache-section">已存在 CNKGraph 缓存条目，但暂无可展示的结构化内容。</div>';
                }
                html += '</div>';
                return html;
            }
            function topPoets(limit) {
                return poets.slice().sort(function (a, b) {
                    var sa = summaryOf(a);
                    var sb = summaryOf(b);
                    return (Number(sb.footprintFreq || 0) - Number(sa.footprintFreq || 0)) || a.localeCompare(b, "zh-Hans-CN");
                }).slice(0, limit);
            }
            function searchPoets(query) {
                var q = String(query || "").trim();
                if (!q) return topPoets(10);
                return poets.filter(function (name) {
                    var info = summaryOf(name);
                    return name.indexOf(q) >= 0
                        || String(info.dynasty || "").indexOf(q) >= 0
                        || String(info.school || "").indexOf(q) >= 0;
                }).slice(0, 30);
            }
            function findFootprintChart() {
                if (!window.echarts || !document.querySelectorAll) return null;
                var nodes = Array.prototype.slice.call(document.querySelectorAll(".chart-container"));
                for (var i = 0; i < nodes.length; i += 1) {
                    var chart = echarts.getInstanceByDom(nodes[i]);
                    if (!chart || typeof chart.getOption !== "function") continue;
                    var option = chart.getOption() || {};
                    var series = option.series || [];
                    if (series.some(function (item) { return item && item.coordinateSystem === "geo"; })) return chart;
                }
                return null;
            }
            function highlightPoetOnMap(poet) {
                var chart = findFootprintChart();
                if (!chart || typeof chart.setOption !== "function") return;
                var rows = placesOf(poet).map(function (place) {
                    return {
                        name: place.modern,
                        modern: place.modern,
                        poet: poet,
                        freq: place.freq,
                        value: [place.lon, place.lat, place.freq],
                        poems: place.poems || [],
                        poemCount: place.poemCount || 0,
                        hiddenPoemCount: Math.max(0, Number(place.poemCount || 0) - (place.poems || []).length)
                    };
                });
                chart.setOption({ series: [{ name: "诗人足迹高亮", data: rows }] });
            }
            function poetFromMapPoint(row) {
                if (!row) return "";
                if (row.poet) return String(row.poet);
                var poems = Array.isArray(row.poems) ? row.poems : [];
                for (var i = 0; i < poems.length; i += 1) {
                    if (poems[i] && poems[i].poet) return String(poems[i].poet);
                }
                return "";
            }
            function placeFromMapPoint(row, fallbackName) {
                if (!row) return String(fallbackName || "");
                return String(row.modern || row.name || fallbackName || "");
            }
            function scrollKnowledgePanelIntoView() {
                var shell = $("footprintKnowledgeShell");
                if (shell && typeof shell.scrollIntoView === "function") {
                    shell.scrollIntoView({ behavior: "smooth", block: "start" });
                }
            }
            function selectFootprintPoint(row, fallbackName) {
                var poet = poetFromMapPoint(row);
                var modern = placeFromMapPoint(row, fallbackName);
                if (!poet || !modern) return false;
                selectFootprintPlace(poet, modern);
                scrollKnowledgePanelIntoView();
                return true;
            }
            function bindMapClick() {
                var chart = findFootprintChart();
                if (!chart || typeof chart.on !== "function") return;
                if (typeof chart.off === "function") chart.off("click");
                chart.on("click", function (params) {
                    var row = params && params.data ? params.data : null;
                    selectFootprintPoint(row, params && params.name);
                });
            }
            function renderSummary(matches) {
                var el = $("footprintSelectionSummary");
                if (!el) return;
                if (currentPoet) {
                    var info = summaryOf(currentPoet);
                    el.textContent = "已选择：" + currentPoet + "（" + (info.dynasty || "未标") + " / " + (info.school || "未分")
                        + "），入库作品 " + (info.poemCount || 0) + " 首，入诗地 " + placesOf(currentPoet).length + " 个。";
                    return;
                }
                el.textContent = "默认显示全员足迹：" + poets.length + " 位诗人；当前列表显示 " + matches.length + " 位，可搜索后高亮单诗人入诗地。";
            }
            function renderResultList(matches) {
                var list = $("poetResultList");
                if (!list) return;
                if (!matches.length) {
                    list.innerHTML = '<div class="footprint-muted">没有匹配的诗人。</div>';
                    return;
                }
                list.innerHTML = matches.map(function (poet) {
                    var info = summaryOf(poet);
                    var active = poet === currentPoet ? " is-active" : "";
                    return '<button type="button" class="' + active + '" data-poet="' + escapeHtml(poet) + '">'
                        + '<strong>' + escapeHtml(poet) + '</strong>'
                        + '<span>' + escapeHtml(info.dynasty || "未标") + ' / ' + escapeHtml(info.school || "未分")
                        + ' / ' + escapeHtml(info.placeCount || placesOf(poet).length) + ' 地点</span>'
                        + '</button>';
                }).join("");
            }
            function renderPlaceList(poet) {
                var list = $("poetPlaceList");
                if (!list) return;
                var places = placesOf(poet);
                if (!poet || !places.length) {
                    list.innerHTML = '<span class="footprint-muted">选择诗人后显示高频入诗地。</span>';
                    return;
                }
                list.innerHTML = places.slice(0, 18).map(function (place) {
                    var active = currentPlace && currentPlace.modern === place.modern ? " is-active" : "";
                    return '<button type="button" class="' + active + '" data-poet="' + escapeHtml(poet) + '" data-place="' + escapeHtml(place.modern) + '">'
                        + escapeHtml(place.modern) + ' ×' + escapeHtml(place.freq || 0)
                        + '</button>';
                }).join("");
            }
            function renderSearch() {
                var input = $("poetSearchInput");
                var query = input ? input.value : "";
                var matches = searchPoets(query);
                var exact = matches.length === 1 && matches[0] === String(query || "").trim();
                if (exact && currentPoet !== matches[0]) {
                    currentPoet = matches[0];
                    currentPlace = null;
                    highlightPoetOnMap(currentPoet);
                }
                if (!String(query || "").trim() && currentPoet) {
                    currentPoet = "";
                    currentPlace = null;
                    highlightPoetOnMap("");
                    renderAiContext();
                }
                renderSummary(matches);
                renderResultList(matches);
                renderPlaceList(currentPoet);
            }
            function selectPoet(poet) {
                currentPoet = poet;
                currentPlace = null;
                var input = $("poetSearchInput");
                if (input) input.value = poet;
                highlightPoetOnMap(poet);
                renderSearch();
                renderAiContext();
            }
            function selectFootprintPlace(poet, modern) {
                currentPoet = poet;
                var input = $("poetSearchInput");
                if (input) input.value = poet;
                var places = placesOf(poet);
                currentPlace = places.find(function (place) { return place.modern === modern; }) || null;
                highlightPoetOnMap(poet);
                renderSearch();
                renderAiContext();
            }
            function updateCnkgraphLiveControls(preserveStatus) {
                var button = $("crawlCnkgraphButton");
                var status = $("cnkgraphLiveStatus");
                if (!button || !status) return;
                if (!currentPoet) {
                    button.style.display = "none";
                    button.disabled = true;
                    button.dataset.force = "false";
                    button.textContent = "现爬 CNKGraph";
                    if (!preserveStatus) status.textContent = "选择诗人后，可对缺失的 CNKGraph 缓存当场现爬。";
                    return;
                }
                var cached = cacheOf(currentPoet);
                if (isCacheOk(cached)) {
                    button.style.display = "";
                    button.disabled = false;
                    button.dataset.force = "true";
                    button.textContent = "重新现爬 CNKGraph";
                    if (!preserveStatus) status.textContent = "当前诗人已有 CNKGraph 本地缓存，可重新现爬覆盖。";
                    return;
                }
                button.style.display = "";
                button.disabled = false;
                button.dataset.force = "false";
                button.textContent = "现爬 CNKGraph";
                if (!preserveStatus) {
                    status.textContent = cached
                        ? "当前 CNKGraph 缓存状态：" + (cached.status || "unknown") + "，可重试现爬。"
                        : "当前诗人暂无 CNKGraph 缓存，可现爬。";
                }
            }
            function renderAiContext() {
                var el = $("footprintAiContext");
                if (!el) return;
                if (!currentPoet) {
                    el.textContent = "尚未选择诗人入诗地。";
                    updateCnkgraphLiveControls();
                    return;
                }
                var info = summaryOf(currentPoet);
                var place = currentPlace || placesOf(currentPoet)[0] || null;
                var poems = place && Array.isArray(place.poems) ? place.poems : [];
                var poemHtml = poems.length ? poems.map(function (poem) {
                    return '<li>《' + escapeHtml(poem.title) + '》：' + escapeHtml(poem.snippet || "") + '</li>';
                }).join("") : '<li>本地诗作片段暂无。</li>';
                var cacheText = cacheSummaryText(currentPoet);
                var cacheHtml = cacheSummaryHtml(currentPoet);
                var plainContext = currentPoet
                    + " / " + (info.dynasty || "未标")
                    + " / 流派：" + (info.school || "未分")
                    + " / 地点：" + (place ? place.modern : "未选择")
                    + " / CNKGraph 缓存摘要：" + cacheText;
                el.textContent = plainContext;
                el.innerHTML = '<strong>' + escapeHtml(currentPoet) + '</strong>'
                    + ' / ' + escapeHtml(info.dynasty || "未标")
                    + ' / 流派：' + escapeHtml(info.school || "未分")
                    + '<br>地点：' + escapeHtml(place ? place.modern : "未选择")
                    + (place ? ' / 入诗次数：' + escapeHtml(place.freq || 0) + ' / 命中诗篇：' + escapeHtml(place.poemCount || poems.length) + ' 首' : '')
                    + cacheHtml
                    + '<ul>' + poemHtml + '</ul>';
                updateCnkgraphLiveControls();
            }
            function buildLocalContext() {
                var info = summaryOf(currentPoet);
                var place = currentPlace || placesOf(currentPoet)[0] || null;
                var cached = cacheOf(currentPoet);
                return { poet: currentPoet, dynasty: info.dynasty || "", school: info.school || "未分", poemCount: info.poemCount || 0, place: place, cnkgraphCache: cached || { status: "missing" } };
            }
            async function crawlCnkgraph() {
                var status = $("cnkgraphLiveStatus");
                var button = $("crawlCnkgraphButton");
                if (!currentPoet) {
                    if (status) status.textContent = "请先选择诗人。";
                    return null;
                }
                if (!window.fetch) {
                    if (status) status.textContent = "当前浏览器不支持 fetch，无法请求本地现爬服务。";
                    return null;
                }
                var force = !!(button && button.dataset && button.dataset.force === "true");
                if (button) button.disabled = true;
                if (status) status.textContent = force ? "正在重新采集 CNKGraph 缓存..." : "正在请求本地 CNKGraph 现爬服务...";
                var controller = typeof AbortController !== "undefined" ? new AbortController() : null;
                var timeoutId = controller && window.setTimeout ? window.setTimeout(function () {
                    controller.abort();
                }, 30000) : null;
                try {
                    var response = await fetch(LIVE_CNKGRAPH_ENDPOINT, {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        signal: controller ? controller.signal : undefined,
                        body: JSON.stringify({ poet: currentPoet, force: force })
                    });
                    var payload = await response.json();
                    if (!response.ok) {
                        throw new Error(payload && payload.message ? payload.message : "HTTP " + response.status);
                    }
                    if (payload && payload.record) {
                        cache.poets[currentPoet] = payload.record;
                    }
                    renderAiContext();
                    if (status) status.textContent = payload && payload.message ? payload.message : "CNKGraph 现爬完成。";
                    return payload;
                } catch (error) {
                    var message = error && error.name === "AbortError"
                        ? "请求超过 30 秒未返回，请确认本地现爬服务和 CNKGraph 登录浏览器状态。"
                        : (error && error.message ? error.message : String(error));
                    if (status) status.textContent = "无法连接本地采集服务或采集失败：" + message;
                    return null;
                } finally {
                    if (timeoutId) window.clearTimeout(timeoutId);
                    updateCnkgraphLiveControls(true);
                }
            }
            function buildPrompt(question) {
                var context = buildLocalContext();
                return "本地数据上下文如下，回答时必须分成【本地数据/缓存来源】和【模型补充推断】两部分；"
                    + "本地没有证据时要明确说没有证据，不能编造成数据库结论。\n"
                    + JSON.stringify(context, null, 2)
                    + "\n用户问题：" + question;
            }
            async function askDeepSeek() {
                var status = $("footprintAiStatus");
                var answer = $("footprintAiAnswer");
                var keyInput = $("deepseekApiKeyInput");
                var questionInput = $("aiQuestionInput");
                var key = keyInput ? String(keyInput.value || "").trim() : "";
                var question = questionInput ? String(questionInput.value || "").trim() : "";
                if (!key) {
                    if (status) status.textContent = "请先配置 DeepSeek Key。";
                    return;
                }
                if (!currentPoet) {
                    if (status) status.textContent = "请先选择诗人或入诗地。";
                    return;
                }
                if (!question) {
                    question = "请解释这个地点和诗人的流派、生平、诗作背景之间的关系。";
                    if (questionInput) questionInput.value = question;
                }
                if (!window.fetch) {
                    if (status) status.textContent = "当前浏览器不支持 fetch，无法直连 DeepSeek。";
                    return;
                }
                if (status) status.textContent = "正在请求 DeepSeek...";
                try {
                    var response = await fetch("https://api.deepseek.com/chat/completions", {
                        method: "POST",
                        headers: { "Content-Type": "application/json", "Authorization": "Bearer " + key },
                        body: JSON.stringify({
                            model: "deepseek-v4-flash",
                            messages: [
                                { role: "system", content: "你是诗行万里知识库助手。只把本地数据和 CNKGraph 缓存当作证据；其他知识必须标为模型补充推断。" },
                                { role: "user", content: buildPrompt(question) }
                            ],
                            temperature: 0.2
                        })
                    });
                    var payloadText = await response.text();
                    var payload = {};
                    try { payload = JSON.parse(payloadText); } catch (parseError) {}
                    if (!response.ok) throw new Error("HTTP " + response.status + " " + (payload.error && payload.error.message || payloadText || ""));
                    var content = payload.choices && payload.choices[0] && payload.choices[0].message ? payload.choices[0].message.content : payloadText;
                    if (answer) answer.textContent = content || "DeepSeek 返回为空。";
                    if (status) status.textContent = "已返回。";
                } catch (error) {
                    if (status) status.textContent = "DeepSeek 请求失败：" + (error && error.message ? error.message : String(error));
                    if (answer) answer.textContent = "浏览器直连可能被 CORS、网络或 Key 权限拦截；页面不会伪造 AI 成功结果。";
                }
            }
            function saveDeepSeekKey() {
                var input = $("deepseekApiKeyInput");
                var key = input ? String(input.value || "").trim() : "";
                storage().setItem("deepseekApiKey", key);
                var status = $("footprintAiStatus");
                if (status) status.textContent = key ? "DeepSeek Key 已保存到 localStorage。" : "DeepSeek Key 已清空。";
            }
            function restoreDeepSeekKey() {
                var input = $("deepseekApiKeyInput");
                if (!input) return;
                input.value = storage().getItem("deepseekApiKey") || "";
            }
            function bindEvents() {
                var input = $("poetSearchInput");
                if (input) input.addEventListener("input", renderSearch);
                var clear = $("clearPoetSearchButton");
                if (clear) clear.addEventListener("click", function () {
                    if (input) input.value = "";
                    currentPoet = "";
                    currentPlace = null;
                    highlightPoetOnMap("");
                    renderAiContext();
                    renderSearch();
                });
                var results = $("poetResultList");
                if (results) results.addEventListener("click", function (event) {
                    var target = event.target;
                    while (target && target !== results && !target.getAttribute("data-poet")) target = target.parentNode;
                    var poet = target && target.getAttribute ? target.getAttribute("data-poet") : "";
                    if (poet) selectPoet(poet);
                });
                var placeList = $("poetPlaceList");
                if (placeList) placeList.addEventListener("click", function (event) {
                    var target = event.target;
                    var poet = target && target.getAttribute ? target.getAttribute("data-poet") : "";
                    var place = target && target.getAttribute ? target.getAttribute("data-place") : "";
                    if (poet && place) selectFootprintPlace(poet, place);
                });
                var save = $("saveDeepseekKeyButton");
                if (save) save.addEventListener("click", saveDeepSeekKey);
                var crawl = $("crawlCnkgraphButton");
                if (crawl) crawl.addEventListener("click", crawlCnkgraph);
                var ask = $("askDeepseekButton");
                if (ask) ask.addEventListener("click", askDeepSeek);
                bindMapClick();
            }
            function init() {
                restoreDeepSeekKey();
                bindEvents();
                renderSearch();
                renderAiContext();
            }
            window.__selectFootprintPlaceForTest = selectFootprintPlace;
            window.__selectFootprintPointForTest = selectFootprintPoint;
            window.__crawlCnkgraphForTest = crawlCnkgraph;
            window.__askDeepSeekForTest = askDeepSeek;
            window.__footprintKnowledgeBuildPromptForTest = buildPrompt;
            if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
            else init();
        }());
    </script>
"""
    resize_script = """
    <script id="shixing-resize-charts">
        (function () {
            function resizeCharts() {
                if (!window.echarts) { return; }
                document.querySelectorAll('.chart-container').forEach(function (el) {
                    var chart = echarts.getInstanceByDom(el);
                    if (chart) { chart.resize(); }
                });
            }
            window.addEventListener('resize', resizeCharts);
            window.addEventListener('orientationchange', resizeCharts);
            setTimeout(resizeCharts, 0);
        }());
    </script>
"""
    if "footprint-knowledge-data" not in html:
        html = html.replace("</body>", f"{data_script}{ui_script}{resize_script}</body>", 1)
    elif "shixing-resize-charts" not in html:
        html = html.replace("</body>", f"{resize_script}</body>", 1)

    html_path.write_text(html, encoding="utf-8")


def render_geo(dyn_points: dict[str, list[tuple[str, float, float, int]]], dynasty_tooltips: dict[tuple[str, str], dict]) -> Geo:
    geo = (
        Geo(init_opts=opts.InitOpts(width="100%", height="720px", bg_color="#f0f4f8"))
        .add_schema(
            maptype="china",
            itemstyle_opts=opts.ItemStyleOpts(color="#e2e8f0", border_color="#94a3b8"),
            label_opts=opts.LabelOpts(is_show=False),
            emphasis_itemstyle_opts=opts.ItemStyleOpts(color="#cbd5e1"),
        )
    )
    seen = set()
    for pts in dyn_points.values():
        for modern, lon, lat, _ in pts:
            if modern not in seen:
                geo.add_coordinate(modern, lon, lat)
                seen.add(modern)

    dyn_color = {"唐": "#ff7a7a", "宋": "#7ad6ff", "魏晋": "#bbbbbb"}
    for dyn, pts in dyn_points.items():
        if not pts:
            continue
        merged = {}
        for modern, _lon, _lat, freq in pts:
            merged[modern] = max(merged.get(modern, 0), int(freq))
        series_name = f"{dyn}·入诗地"
        geo.add(
            series_name,
            list(merged.items()),
            type_=ChartType.SCATTER,
            symbol_size=8,
            color=dyn_color.get(dyn, "#9ca3af"),
            label_opts=opts.LabelOpts(is_show=False),
            tooltip_opts=opts.TooltipOpts(formatter=FOOTPRINT_TOOLTIP_FORMATTER),
        )
        attach_tooltip_metadata(
            geo,
            series_name,
            {modern: meta for (meta_dyn, modern), meta in dynasty_tooltips.items() if meta_dyn == dyn},
        )

    geo.add(
        HIGHLIGHT_SERIES_NAME,
        [],
        type_=ChartType.EFFECT_SCATTER,
        symbol_size=16,
        color="#14b8a6",
        effect_opts=opts.EffectOpts(scale=4.2, period=3.0, brush_type="stroke", color="#99f6e4"),
        label_opts=opts.LabelOpts(is_show=True, position="right", color="#fff", font_size=10),
        tooltip_opts=opts.TooltipOpts(formatter=FOOTPRINT_TOOLTIP_FORMATTER),
    )
    highlight = find_series(geo, HIGHLIGHT_SERIES_NAME)
    highlight["zlevel"] = 12
    highlight["z"] = 12
    highlight["itemStyle"] = {
        "color": "#14b8a6",
        "borderColor": "#ffffff",
        "borderWidth": 2,
        "shadowBlur": 16,
        "shadowColor": "rgba(20,184,166,0.65)",
    }

    geo.set_global_opts(
        title_opts=opts.TitleOpts(
            title="诗行万里 · 全员唐宋诗人足迹分布",
            subtitle="唐红｜宋蓝；默认展示全员入诗地，搜索诗人后以青色涟漪点高亮该诗人的入诗地",
            title_textstyle_opts=opts.TextStyleOpts(color="#fff", font_size=20),
            subtitle_textstyle_opts=opts.TextStyleOpts(color="#a0a0c0"),
            pos_left="center",
        ),
        legend_opts=opts.LegendOpts(textstyle_opts=opts.TextStyleOpts(color="#ddd"), pos_top="8%"),
        tooltip_opts=opts.TooltipOpts(formatter="{b}"),
    )
    return geo


def render_province_map(prov: dict[str, int]) -> Map:
    return (
        Map(init_opts=opts.InitOpts(width="100%", height="650px"))
        .add(
            "入诗频次",
            [(key, value) for key, value in prov.items()],
            maptype="china",
            is_map_symbol_show=False,
            label_opts=opts.LabelOpts(is_show=True, font_size=9),
        )
        .set_global_opts(
            title_opts=opts.TitleOpts(title="唐宋诗作中各省入诗频次热力图", pos_left="center"),
            visualmap_opts=opts.VisualMapOpts(
                max_=max(prov.values()) if prov else 1,
                is_piecewise=False,
                range_color=["#fff7ec", "#fdd49e", "#fc8d59", "#d7301f", "#7f0000"],
            ),
        )
    )


def render_top_alias_bar() -> Bar:
    tops = top_places(15)
    return (
        Bar(init_opts=opts.InitOpts(width="100%", height="500px"))
        .add_xaxis([f"{alias}({modern})" for alias, modern, _ in tops][::-1])
        .add_yaxis(
            "入诗次数",
            [int(freq) for _, _, freq in tops][::-1],
            label_opts=opts.LabelOpts(position="right"),
            itemstyle_opts=opts.ItemStyleOpts(color="#d7301f"),
        )
        .reversal_axis()
        .set_global_opts(
            title_opts=opts.TitleOpts(title="Top15 入诗古地名", subtitle="古名(今地)", pos_left="center"),
            xaxis_opts=opts.AxisOpts(name="次数"),
        )
    )


def render_top_modern_bar() -> Bar:
    modern_tops = top_modern_places(15)
    modern_bar_items = [
        {
            "value": int(freq),
            "modern": modern,
            "poemCount": int(poem_count),
            "aliasCount": int(alias_count),
            "aliases": aliases,
        }
        for modern, freq, poem_count, alias_count, aliases in modern_tops
    ][::-1]
    return (
        Bar(init_opts=opts.InitOpts(width="1100px", height="520px"))
        .add_xaxis([f"{modern}（古名数{alias_count}）" for modern, _, _, alias_count, _ in modern_tops][::-1])
        .add_yaxis(
            "入诗次数",
            modern_bar_items,
            label_opts=opts.LabelOpts(position="right"),
            itemstyle_opts=opts.ItemStyleOpts(color="#2b8cbe"),
        )
        .reversal_axis()
        .set_global_opts(
            title_opts=opts.TitleOpts(
                title="Top15 现代地点入诗频次",
                subtitle="按今地 modern 聚合；括号为古名数，补充古地名 Top 的重复视角",
                pos_left="center",
            ),
            xaxis_opts=opts.AxisOpts(name="次数"),
            tooltip_opts=opts.TooltipOpts(
                formatter=JsCode(
                    """
                    function (params) {
                        var data = params.data || {};
                        function esc(text) {
                            return String(text == null ? '' : text).replace(/[&<>"']/g, function (ch) {
                                var code = ch.charCodeAt(0);
                                if (code === 38) { return '&amp;'; }
                                if (code === 60) { return '&lt;'; }
                                if (code === 62) { return '&gt;'; }
                                if (code === 34) { return '&quot;'; }
                                if (code === 39) { return '&#39;'; }
                                return ch;
                            });
                        }
                        return '<strong>' + esc(data.modern || params.name) + '</strong>'
                            + '<br/>入诗次数：' + esc(data.value || params.value)
                            + '<br/>涉及作品：' + esc(data.poemCount || 0) + ' 首'
                            + '<br/>古名数：' + esc(data.aliasCount || 0)
                            + '<br/>合并古名：' + esc(data.aliases || '');
                    }
                    """
                )
            ),
        )
    )


def render() -> None:
    dyn_points = all_dynasty_points()
    dynasty_tooltips, _poet_tooltips = load_poem_tooltips()
    poet_summaries = load_poet_summaries()
    poet_places = load_poet_places(poet_summaries)
    knowledge_data = build_knowledge_data(poet_summaries, poet_places)
    prov = province_freq()

    page = Page(layout=Page.SimplePageLayout, page_title="诗人足迹知识库")
    page.add(
        render_geo(dyn_points, dynasty_tooltips),
        render_province_map(prov),
        render_top_alias_bar(),
        render_top_modern_bar(),
    )

    out = OUTPUT_DIR / "01_诗人足迹.html"
    page.render(str(out))
    localize_pyecharts_assets(out)
    footprint_stats = {"all_footprints": sum(len(items) for items in dyn_points.values())}
    inject_footprint_knowledge_ui(out, footprint_stats, knowledge_data)
    print(
        f"  [ok] saved {out}  "
        f"({sum(len(v) for v in dyn_points.values())} 条全员足迹 / "
        f"{len(knowledge_data['poets'])} 位诗人 / "
        f"{sum(len(v) for v in poet_places.values())} 条诗人-地点记录 / "
        f"{len(prov)} 省 / Top15 古地名 + 现代地点)"
    )


if __name__ == "__main__":
    render()
