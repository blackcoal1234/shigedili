"""可视化 8：离线诗作检索浏览器。"""
from __future__ import annotations

import json
import hashlib
import sys
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
from html import escape
from pathlib import Path

import pymysql

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config import DB_NAME, MYSQL, OUTPUT_DIR
from data.image_dict import lookup as lookup_image, words as image_words
from data.season_rules import detect_season
from viz_assets import inject_index_backlink


POEMS_JSON = ROOT / "data" / "poems.json"
RICH_BACKGROUNDS_JSONL = ROOT / "data" / "reviewed" / "verified_poem_backgrounds.jsonl"


@dataclass(frozen=True)
class PoemRecord:
    title: str
    poet: str
    dynasty: str
    school: str
    season: str
    sentiment: float
    body_len: int
    body: str
    body_hash: str

    def to_json(self, index: int, background: dict[str, object] | None = None) -> dict[str, object]:
        return {
            "id": index,
            "title": self.title,
            "poet": self.poet,
            "dynasty": self.dynasty,
            "school": self.school,
            "season": self.season,
            "sentiment": round(self.sentiment, 3),
            "body_len": self.body_len,
            "body": self.body,
            "background": background,
        }


def conn():
    return pymysql.connect(
        **MYSQL,
        database=DB_NAME,
        connect_timeout=5,
        read_timeout=15,
        write_timeout=15,
        cursorclass=pymysql.cursors.DictCursor,
    )


def as_float(value: object) -> float:
    if value is None:
        return 0.0
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


def greedy_image_counts(text: str, tokens: list[str]) -> Counter[str]:
    counts: Counter[str] = Counter()
    work = text or ""
    for token in tokens:
        count = work.count(token)
        if count:
            counts[token] += count
            work = work.replace(token, "·" * len(token))
    return counts


def estimate_sentiment(image_counts: Counter[str]) -> float:
    total_weight = sum(image_counts.values())
    if not total_weight:
        return 0.0
    total = 0.0
    for word, count in image_counts.items():
        meta = lookup_image(word)
        if meta:
            total += float(meta["sentiment"]) * count
    return total / total_weight


def load_from_database() -> list[PoemRecord]:
    with conn() as c, c.cursor() as cur:
        cur.execute(
            """
            SELECT pm.title,
                   pt.name AS poet,
                   pt.dynasty,
                   COALESCE(pt.school, '') AS school,
                   COALESCE(NULLIF(pm.season, ''), '未标') AS season,
                   pm.sentiment,
                   pm.body_len,
                   pm.body,
                   pm.body_hash
              FROM t_poem pm
              JOIN t_poet pt ON pt.poet_id = pm.poet_id
             ORDER BY pt.dynasty, pt.name, pm.title
            """
        )
        rows = cur.fetchall()
    return [
        PoemRecord(
            title=str(row["title"] or ""),
            poet=str(row["poet"] or ""),
            dynasty=str(row["dynasty"] or ""),
            school=str(row["school"] or ""),
            season=str(row["season"] or "未标"),
            sentiment=as_float(row.get("sentiment")),
            body_len=int(row.get("body_len") or len(str(row.get("body") or ""))),
            body=str(row.get("body") or ""),
            body_hash=str(row.get("body_hash") or hashlib.sha256(str(row.get("body") or "").encode("utf-8")).hexdigest()),
        )
        for row in rows
    ]


def load_from_poems_json(reason: Exception | None = None) -> list[PoemRecord]:
    if reason is not None:
        print(f"  [warn] 数据库读取失败，改用 poems.json 离线兜底：{reason}")
    records = json.loads(POEMS_JSON.read_text(encoding="utf-8"))
    images = image_words()
    poems: list[PoemRecord] = []
    for row in records:
        title = str(row.get("title") or "")
        body = str(row.get("body") or "")
        image_counts = greedy_image_counts(body, images)
        poems.append(
            PoemRecord(
                title=title,
                poet=str(row.get("poet") or row.get("author") or ""),
                dynasty=str(row.get("dynasty") or ""),
                school=str(row.get("school") or ""),
                season=detect_season(title, body) or "未标",
                sentiment=estimate_sentiment(image_counts),
                body_len=len(body),
                body=body,
                body_hash=str(row.get("body_hash") or hashlib.sha256(body.encode("utf-8")).hexdigest()),
            )
        )
    return sorted(poems, key=lambda item: (item.dynasty, item.poet, item.title))


def load_poems() -> list[PoemRecord]:
    try:
        return load_from_database()
    except Exception as exc:
        return load_from_poems_json(exc)


def load_approved_backgrounds() -> dict[str, dict[str, object]]:
    """Load only approved exports; candidates never enter the public browser."""
    if not RICH_BACKGROUNDS_JSONL.exists():
        return {}
    backgrounds: dict[str, dict[str, object]] = {}
    for line in RICH_BACKGROUNDS_JSONL.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict) or row.get("review_status") != "approved":
            continue
        key = row.get("poem_key") if isinstance(row.get("poem_key"), dict) else {}
        digest = str(key.get("body_hash") or "")
        if not digest:
            continue
        sources = []
        for source in row.get("sources") or []:
            if not isinstance(source, dict):
                continue
            sources.append(
                {
                    "name": str(source.get("name") or ""),
                    "url": str(source.get("url") or ""),
                    "citation": str(source.get("citation") or ""),
                    "locator": str(source.get("locator") or ""),
                    "grade": str(source.get("grade") or ""),
                    "excerpt": str(source.get("excerpt") or "")[:160],
                }
            )
        backgrounds[digest] = {
            "composition": row.get("composition") if isinstance(row.get("composition"), dict) else {},
            "background_summary": str(row.get("background_summary") or ""),
            "story_summary": str(row.get("story_summary") or ""),
            "controversy_note": str(row.get("controversy_note") or ""),
            "line_notes": row.get("line_notes") if isinstance(row.get("line_notes"), list) else [],
            "appreciation_points": row.get("appreciation_points") if isinstance(row.get("appreciation_points"), list) else [],
            "sources": sources,
            "publication_ready": bool(row.get("publication_ready")),
        }
    return backgrounds


def option_count(values: list[str]) -> int:
    return len({value for value in values if value})


def render() -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    poems = load_poems()
    backgrounds = load_approved_backgrounds()
    dataset = [poem.to_json(index, backgrounds.get(poem.body_hash)) for index, poem in enumerate(poems)]
    payload = json.dumps(dataset, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    poet_count = option_count([poem.poet for poem in poems])
    dynasty_count = option_count([poem.dynasty for poem in poems])
    season_count = option_count([poem.season for poem in poems])

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <link rel="icon" href="data:,">
    <title>诗行万里 · 诗作检索</title>
    <style>
    :root {{
        --bg: #f4f7fb;
        --panel: #ffffff;
        --ink: #102033;
        --muted: #627083;
        --line: #d9e2ee;
        --accent: #0f766e;
        --accent-soft: #def7ef;
        --warn: #b45309;
    }}
    * {{ box-sizing: border-box; }}
    body {{
        margin: 0;
        min-height: 100vh;
        background: var(--bg);
        color: var(--ink);
        font-family: "Microsoft YaHei", "PingFang SC", Arial, sans-serif;
    }}
    .shell {{
        width: min(1240px, calc(100vw - 32px));
        margin: 0 auto;
        padding: 28px 0 42px;
    }}
    .topbar {{
        display: flex;
        align-items: flex-start;
        justify-content: space-between;
        gap: 18px;
        margin-bottom: 18px;
    }}
    h1 {{
        margin: 0;
        font-size: 30px;
        line-height: 1.2;
        letter-spacing: 0;
    }}
    .subtitle {{
        margin: 9px 0 0;
        max-width: 760px;
        color: var(--muted);
        font-size: 14px;
        line-height: 1.75;
    }}
    .metrics {{
        display: grid;
        grid-template-columns: repeat(4, minmax(120px, 1fr));
        gap: 10px;
        margin-bottom: 16px;
    }}
    .metric,
    .panel {{
        border: 1px solid var(--line);
        border-radius: 8px;
        background: var(--panel);
    }}
    .metric {{
        min-height: 76px;
        padding: 13px 15px;
    }}
    .metric span {{
        display: block;
        color: var(--muted);
        font-size: 13px;
    }}
    .metric strong {{
        display: block;
        margin-top: 8px;
        font-size: 22px;
        line-height: 1.2;
        letter-spacing: 0;
    }}
    .filters {{
        display: grid;
        grid-template-columns: minmax(220px, 1.4fr) repeat(4, minmax(110px, 0.8fr)) auto;
        gap: 10px;
        align-items: end;
        padding: 14px;
        margin-bottom: 10px;
    }}
    .state-tools {{
        display: grid;
        grid-template-columns: minmax(0, 1fr) auto auto;
        gap: 10px;
        align-items: center;
        padding: 11px 14px;
        margin-bottom: 16px;
    }}
    .state-tools span {{
        color: var(--muted);
        font-size: 13px;
        line-height: 1.5;
    }}
    label {{
        display: grid;
        gap: 6px;
        color: var(--muted);
        font-size: 13px;
    }}
    input,
    select,
    button {{
        min-height: 38px;
        border: 1px solid #cbd7e6;
        border-radius: 6px;
        background: #fff;
        color: var(--ink);
        font: inherit;
        font-size: 14px;
    }}
    input,
    select {{
        width: 100%;
        padding: 0 10px;
    }}
    button {{
        padding: 0 14px;
        cursor: pointer;
        background: var(--ink);
        color: #fff;
        font-weight: 700;
    }}
    .layout {{
        display: grid;
        grid-template-columns: minmax(300px, 0.92fr) minmax(0, 1.08fr);
        gap: 16px;
        align-items: start;
    }}
    .panel {{
        overflow: hidden;
    }}
    .panel-head {{
        display: flex;
        align-items: baseline;
        justify-content: space-between;
        gap: 10px;
        padding: 14px 16px;
        border-bottom: 1px solid var(--line);
    }}
    .panel-head h2 {{
        margin: 0;
        font-size: 18px;
        line-height: 1.35;
        letter-spacing: 0;
    }}
    .panel-head span {{
        color: var(--muted);
        font-size: 13px;
    }}
    .result-list {{
        max-height: 640px;
        overflow: auto;
        padding: 8px;
    }}
    .result-item {{
        width: 100%;
        min-height: 72px;
        margin: 0 0 8px;
        padding: 10px 11px;
        border: 1px solid transparent;
        border-radius: 7px;
        background: #f8fafc;
        color: var(--ink);
        text-align: left;
        cursor: pointer;
    }}
    .result-item.is-active {{
        border-color: #99f6e4;
        background: var(--accent-soft);
    }}
    .result-title {{
        display: flex;
        justify-content: space-between;
        gap: 10px;
        font-weight: 700;
        line-height: 1.4;
    }}
    .result-meta {{
        margin-top: 6px;
        color: var(--muted);
        font-size: 13px;
        line-height: 1.5;
    }}
    .result-snippet {{
        margin-top: 7px;
        color: #334155;
        font-size: 13px;
        line-height: 1.55;
    }}
    .result-snippet span {{
        margin-right: 6px;
        color: var(--muted);
        font-weight: 700;
    }}
    .detail {{
        min-height: 640px;
        padding: 20px 22px 24px;
    }}
    .detail h2 {{
        margin: 0;
        font-size: 26px;
        line-height: 1.25;
        letter-spacing: 0;
    }}
    .detail-meta {{
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
        margin-top: 12px;
    }}
    .tag {{
        display: inline-flex;
        align-items: center;
        min-height: 28px;
        padding: 0 9px;
        border: 1px solid var(--line);
        border-radius: 999px;
        background: #f8fafc;
        color: #334155;
        font-size: 13px;
    }}
    .poem-body {{
        margin-top: 18px;
        white-space: pre-wrap;
        font-size: 18px;
        line-height: 2.05;
    }}
    .background-section {{
        margin-top: 24px;
        padding-top: 18px;
        border-top: 1px solid var(--line);
    }}
    .background-section h3 {{
        margin: 0 0 10px;
        font-size: 17px;
        line-height: 1.4;
        letter-spacing: 0;
    }}
    .background-copy {{
        margin: 0;
        color: #334155;
        font-size: 14px;
        line-height: 1.8;
        white-space: pre-wrap;
    }}
    .background-facts {{
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
        margin: 0 0 12px;
    }}
    .background-fact {{
        padding: 5px 8px;
        border-left: 3px solid var(--accent);
        background: #f1f7f5;
        color: #24564f;
        font-size: 13px;
        line-height: 1.45;
    }}
    .line-note {{
        margin: 0;
        padding: 11px 0;
        border-top: 1px solid #e8edf3;
    }}
    .line-note:first-of-type {{
        border-top: 0;
    }}
    .line-note-original {{
        font-family: "STKaiti", "KaiTi", serif;
        font-size: 16px;
        line-height: 1.7;
    }}
    .line-note-translation {{
        margin-top: 5px;
        color: #334155;
        font-size: 14px;
        line-height: 1.7;
    }}
    .line-note-annotation {{
        margin-top: 5px;
        color: var(--muted);
        font-size: 13px;
        line-height: 1.7;
    }}
    .appreciation-list,
    .source-list {{
        margin: 0;
        padding: 0;
        list-style: none;
    }}
    .appreciation-list li,
    .source-list li {{
        padding: 9px 0;
        border-top: 1px solid #e8edf3;
        color: #334155;
        font-size: 14px;
        line-height: 1.7;
    }}
    .appreciation-list li:first-child,
    .source-list li:first-child {{
        border-top: 0;
    }}
    .source-title {{
        color: var(--ink);
        font-weight: 700;
    }}
    .source-meta {{
        margin-top: 3px;
        color: var(--muted);
        font-size: 12px;
        line-height: 1.65;
    }}
    .source-excerpt {{
        margin-top: 5px;
        padding-left: 9px;
        border-left: 2px solid #d8b46a;
        color: #4a5665;
        font-size: 13px;
        line-height: 1.7;
    }}
    .background-warning {{
        margin: 10px 0 0;
        color: var(--warn);
        font-size: 13px;
        line-height: 1.65;
    }}
    .empty {{
        padding: 24px;
        color: var(--muted);
        font-size: 14px;
        line-height: 1.7;
    }}
    mark {{
        padding: 0 2px;
        border-radius: 3px;
        background: #fef3c7;
        color: inherit;
    }}
    @media (max-width: 880px) {{
        .shell {{ width: min(100vw - 20px, 1240px); padding-top: 18px; }}
        .topbar {{ flex-direction: column; }}
        h1 {{ font-size: 25px; }}
        .metrics {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
        .filters {{ grid-template-columns: 1fr 1fr; }}
        .filters label:first-child {{ grid-column: 1 / -1; }}
        .state-tools {{ grid-template-columns: 1fr; }}
        .layout {{ grid-template-columns: 1fr; }}
        .detail {{ min-height: auto; }}
    }}
    @media (max-width: 560px) {{
        .filters {{ grid-template-columns: 1fr; }}
        .metrics {{ grid-template-columns: 1fr; }}
        .detail h2 {{ font-size: 22px; }}
        .poem-body {{ font-size: 16px; }}
    }}
    </style>
</head>
<body>
    <main class="shell">
        <section class="topbar">
            <div>
                <h1>诗行万里 · 诗作检索</h1>
                <p class="subtitle">按诗人、朝代、季节和关键词查看入库诗作，统计结果可以直接回到具体文本。</p>
            </div>
        </section>

        <section class="metrics" aria-label="数据概览">
            <div class="metric"><span>诗作</span><strong>{len(poems):,} 首</strong></div>
            <div class="metric"><span>诗人</span><strong>{poet_count:,} 位</strong></div>
            <div class="metric"><span>朝代</span><strong>{dynasty_count:,} 类</strong></div>
            <div class="metric"><span>季节标签</span><strong>{season_count:,} 类</strong></div>
        </section>

        <section class="panel filters" aria-label="筛选">
            <label>关键词
                <input id="queryInput" type="search" placeholder="题名、诗人、正文" autocomplete="off">
            </label>
            <label>诗人
                <select id="poetFilter"><option value="">全部</option></select>
            </label>
            <label>朝代
                <select id="dynastyFilter"><option value="">全部</option></select>
            </label>
            <label>流派
                <select id="schoolFilter"><option value="">全部</option></select>
            </label>
            <label>季节
                <select id="seasonFilter"><option value="">全部</option></select>
            </label>
            <button id="resetButton" type="button">重置</button>
        </section>
        <section class="panel state-tools" aria-label="筛选状态">
            <span id="stateHint">筛选状态会自动保存到本机，并同步为可复制的 URL 深链。</span>
            <button id="copyLinkButton" type="button">复制当前筛选链接</button>
            <button id="clearMemoryButton" type="button">清除记忆</button>
        </section>

        <section class="layout">
            <aside class="panel">
                <div class="panel-head">
                    <h2>检索结果</h2>
                    <span id="resultCount">0 首</span>
                </div>
                <div id="resultList" class="result-list"></div>
            </aside>
            <article class="panel">
                <div class="panel-head">
                    <h2>诗作详情</h2>
                    <span id="detailMeta">文本</span>
                </div>
                <div id="detailPanel" class="detail" aria-live="polite"></div>
            </article>
        </section>
    </main>
    <script>
    window.POEM_BROWSER_DATA = {payload};

    const poems = window.POEM_BROWSER_DATA;
    const STORAGE_KEY = "poemBrowserState";
    const state = {{
        query: "",
        poet: "",
        dynasty: "",
        school: "",
        season: "",
        activeId: poems[0] ? poems[0].id : null,
    }};
    const els = {{
        query: document.getElementById("queryInput"),
        poet: document.getElementById("poetFilter"),
        dynasty: document.getElementById("dynastyFilter"),
        school: document.getElementById("schoolFilter"),
        season: document.getElementById("seasonFilter"),
        reset: document.getElementById("resetButton"),
        copyLink: document.getElementById("copyLinkButton"),
        clearMemory: document.getElementById("clearMemoryButton"),
        hint: document.getElementById("stateHint"),
        list: document.getElementById("resultList"),
        count: document.getElementById("resultCount"),
        detail: document.getElementById("detailPanel"),
    }};

    function escapeHtml(value) {{
        return String(value ?? "").replace(/[&<>"']/g, function (char) {{
            return ({{ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }})[char];
        }});
    }}

    function uniqueSorted(key) {{
        return Array.from(new Set(poems.map(function (poem) {{ return poem[key] || ""; }}).filter(Boolean))).sort(function (a, b) {{
            return String(a).localeCompare(String(b), "zh-Hans-CN");
        }});
    }}

    function fillSelect(select, values) {{
        select.innerHTML = '<option value="">全部</option>' + values.map(function (value) {{
            return '<option value="' + escapeHtml(value) + '">' + escapeHtml(value) + '</option>';
        }}).join("");
    }}

    function hasOption(select, value) {{
        if (!value) return true;
        return Array.from(select.options).some(function (option) {{ return option.value === value; }});
    }}

    function safeJsonParse(value) {{
        try {{
            return JSON.parse(value || "null");
        }} catch (error) {{
            return null;
        }}
    }}

    function coerceState(raw) {{
        if (!raw || typeof raw !== "object") return null;
        const next = {{}};
        if (typeof raw.query === "string") next.query = raw.query;
        if (typeof raw.poet === "string" && hasOption(els.poet, raw.poet)) next.poet = raw.poet;
        if (typeof raw.dynasty === "string" && hasOption(els.dynasty, raw.dynasty)) next.dynasty = raw.dynasty;
        if (typeof raw.school === "string" && hasOption(els.school, raw.school)) next.school = raw.school;
        if (typeof raw.season === "string" && hasOption(els.season, raw.season)) next.season = raw.season;
        if (raw.activeId !== undefined && raw.activeId !== null && poems.some(function (poem) {{ return poem.id === Number(raw.activeId); }})) {{
            next.activeId = Number(raw.activeId);
        }}
        return next;
    }}

    function stateFromUrl() {{
        const params = new URLSearchParams(window.location.search || "");
        if (!Array.from(params.keys()).length) return null;
        return coerceState({{
            query: params.get("q") || "",
            poet: params.get("poet") || "",
            dynasty: params.get("dynasty") || "",
            school: params.get("school") || "",
            season: params.get("season") || "",
            activeId: params.get("id"),
        }});
    }}

    function stateFromStorage() {{
        return coerceState(safeJsonParse(localStorage.getItem(STORAGE_KEY)));
    }}

    function applyState(next) {{
        if (!next) return false;
        ["query", "poet", "dynasty", "school", "season"].forEach(function (key) {{
            if (Object.prototype.hasOwnProperty.call(next, key)) {{
                state[key] = String(next[key] || "");
            }}
        }});
        if (Object.prototype.hasOwnProperty.call(next, "activeId")) {{
            state.activeId = next.activeId;
        }}
        return true;
    }}

    function syncControls() {{
        els.query.value = state.query;
        els.poet.value = state.poet;
        els.dynasty.value = state.dynasty;
        els.school.value = state.school;
        els.season.value = state.season;
    }}

    function snapshotState() {{
        return {{
            query: state.query,
            poet: state.poet,
            dynasty: state.dynasty,
            school: state.school,
            season: state.season,
            activeId: state.activeId,
        }};
    }}

    function stateHasFilters() {{
        return Boolean(state.query || state.poet || state.dynasty || state.school || state.season);
    }}

    function stateParams() {{
        const params = new URLSearchParams();
        if (state.query) params.set("q", state.query);
        if (state.poet) params.set("poet", state.poet);
        if (state.dynasty) params.set("dynasty", state.dynasty);
        if (state.school) params.set("school", state.school);
        if (state.season) params.set("season", state.season);
        if (stateHasFilters() && state.activeId !== null && state.activeId !== undefined) params.set("id", String(state.activeId));
        return params;
    }}

    function currentPathWithQuery() {{
        const params = stateParams();
        const query = params.toString();
        return window.location.pathname + (query ? "?" + query : "");
    }}

    function currentShareLink() {{
        const path = currentPathWithQuery();
        return window.location.origin ? window.location.origin + path : path;
    }}

    function setHint(text) {{
        if (els.hint) {{
            els.hint.textContent = text;
        }}
    }}

    function persistState(message) {{
        localStorage.setItem(STORAGE_KEY, JSON.stringify(snapshotState()));
        window.history.replaceState(null, "", currentPathWithQuery());
        if (message) setHint(message);
    }}

    function normalized(value) {{
        return String(value || "").trim().toLowerCase();
    }}

    function highlight(text) {{
        const raw = String(text || "");
        const query = state.query.trim();
        if (!query) return escapeHtml(raw);
        const index = raw.toLowerCase().indexOf(query.toLowerCase());
        if (index < 0) return escapeHtml(raw);
        return escapeHtml(raw.slice(0, index)) + "<mark>" + escapeHtml(raw.slice(index, index + query.length)) + "</mark>" + escapeHtml(raw.slice(index + query.length));
    }}

    function hitSnippet(poem) {{
        const query = state.query.trim();
        if (!query) return "";
        const source = String([poem.title, poem.poet, poem.body].filter(Boolean).join(" ") || "");
        const lower = source.toLowerCase();
        const index = lower.indexOf(query.toLowerCase());
        if (index < 0) return "";
        const radius = 28;
        const start = Math.max(0, index - radius);
        const end = Math.min(source.length, index + query.length + radius);
        const prefix = start > 0 ? "…" : "";
        const suffix = end < source.length ? "…" : "";
        return (prefix + source.slice(start, end) + suffix).replace(/\\s+/g, " ");
    }}

    function safeExternalUrl(value) {{
        const text = String(value || "");
        return text.startsWith("https://") || text.startsWith("http://") ? text : "";
    }}

    function backgroundFacts(background) {{
        const composition = background && background.composition && typeof background.composition === "object" ? background.composition : {{}};
        const date = composition.date && typeof composition.date === "object" ? composition.date : {{}};
        const place = composition.place && typeof composition.place === "object" ? composition.place : {{}};
        const facts = [];
        const start = date.year_start || date.year || "";
        const end = date.year_end || start;
        if (start) {{
            facts.push('<span class="background-fact">作年：' + escapeHtml(start === end ? start + "年" : start + "-" + end + "年") + '</span>');
        }}
        const historical = place.historical_place || "";
        const modern = place.modern_place || place.modern_city || "";
        if (historical || modern) {{
            facts.push('<span class="background-fact">作地：' + escapeHtml([historical, modern && modern !== historical ? modern : ""].filter(Boolean).join("，")) + '</span>');
        }}
        return facts.join("");
    }}

    function renderBackground(background) {{
        if (!background || typeof background !== "object") {{
            return '<section class="background-section"><h3>创作背景</h3><p class="background-copy">暂无已审核背景。</p></section>' +
                '<section class="background-section"><h3>译注赏析</h3><p class="background-copy">暂无已审核译注赏析。</p></section>' +
                '<section class="background-section"><h3>证据来源</h3><p class="background-copy">暂无已审核证据来源。</p></section>';
        }}
        const summary = String(background.story_summary || background.background_summary || "").trim();
        const controversy = String(background.controversy_note || "").trim();
        const facts = backgroundFacts(background);
        const contextHtml = '<section class="background-section"><h3>创作背景</h3>' +
            (facts ? '<div class="background-facts">' + facts + '</div>' : '') +
            (summary ? '<p class="background-copy">' + escapeHtml(summary) + '</p>' : '<p class="background-copy">暂无已审核背景摘要。</p>') +
            (controversy ? '<p class="background-warning">待考：' + escapeHtml(controversy) + '</p>' : '') +
            '</section>';

        const notes = Array.isArray(background.line_notes) ? background.line_notes : [];
        const noteHtml = notes.filter(function (note) {{
            return note && (note.translation || (Array.isArray(note.annotations) && note.annotations.length));
        }}).map(function (note) {{
            const annotations = Array.isArray(note.annotations) ? note.annotations.filter(Boolean) : [];
            return '<div class="line-note">' +
                (note.original ? '<div class="line-note-original">' + escapeHtml(note.original) + '</div>' : '') +
                (note.translation ? '<div class="line-note-translation">' + escapeHtml(note.translation) + '</div>' : '') +
                (annotations.length ? '<div class="line-note-annotation">注：' + escapeHtml(annotations.join("；")) + '</div>' : '') +
                '</div>';
        }}).join("");
        const appreciations = (Array.isArray(background.appreciation_points) ? background.appreciation_points : []).map(function (item) {{
            return item && typeof item === "object" ? String(item.point || "").trim() : "";
        }}).filter(Boolean);
        const appreciationHtml = appreciations.length ? '<ul class="appreciation-list">' + appreciations.map(function (point) {{
            return '<li>' + escapeHtml(point) + '</li>';
        }}).join("") + '</ul>' : '';
        const literaryHtml = '<section class="background-section"><h3>译注赏析</h3>' +
            (noteHtml || appreciationHtml ? noteHtml + appreciationHtml : '<p class="background-copy">暂无已审核项目整理内容。</p>') +
            '</section>';

        const sources = Array.isArray(background.sources) ? background.sources : [];
        const sourceHtml = sources.map(function (source) {{
            if (!source || typeof source !== "object") return "";
            const url = safeExternalUrl(source.url);
            const title = escapeHtml(source.name || "未命名来源");
            const titleHtml = url ? '<a class="source-title" href="' + escapeHtml(url) + '" target="_blank" rel="noreferrer">' + title + '</a>' : '<span class="source-title">' + title + '</span>';
            const meta = [source.citation, source.locator, source.grade ? source.grade + "级" : ""].filter(Boolean).join(" · ");
            const excerpt = String(source.excerpt || "").slice(0, 160);
            return '<li>' + titleHtml +
                (meta ? '<div class="source-meta">' + escapeHtml(meta) + '</div>' : '') +
                (excerpt ? '<div class="source-excerpt">' + escapeHtml(excerpt) + '</div>' : '') +
                '</li>';
        }}).filter(Boolean).join("");
        const evidenceHtml = '<section class="background-section"><h3>证据来源</h3>' +
            (sourceHtml ? '<ul class="source-list">' + sourceHtml + '</ul>' : '<p class="background-copy">暂无已审核证据来源。</p>') +
            '</section>';
        return contextHtml + literaryHtml + evidenceHtml;
    }}

    function matches(poem) {{
        const query = normalized(state.query);
        if (state.poet && poem.poet !== state.poet) return false;
        if (state.dynasty && poem.dynasty !== state.dynasty) return false;
        if (state.school && poem.school !== state.school) return false;
        if (state.season && poem.season !== state.season) return false;
        if (!query) return true;
        return [poem.title, poem.poet, poem.dynasty, poem.school, poem.season, poem.body].some(function (value) {{
            return normalized(value).includes(query);
        }});
    }}

    function filteredPoems() {{
        return poems.filter(matches);
    }}

    function renderList(results) {{
        els.count.textContent = results.length + " 首";
        if (!results.length) {{
            els.list.innerHTML = '<div class="empty">暂无匹配诗作</div>';
            state.activeId = null;
            renderDetail(null);
            return;
        }}
        if (!results.some(function (poem) {{ return poem.id === state.activeId; }})) {{
            state.activeId = results[0].id;
        }}
        const visible = results.slice(0, 120);
        els.list.innerHTML = visible.map(function (poem) {{
            const active = poem.id === state.activeId ? " is-active" : "";
            const snippet = hitSnippet(poem);
            return '<button class="result-item' + active + '" type="button" data-id="' + poem.id + '">' +
                '<div class="result-title"><span>' + highlight(poem.title) + '</span><span>' + escapeHtml(poem.season || "未标") + '</span></div>' +
                '<div class="result-meta">' + escapeHtml(poem.poet) + ' · ' + escapeHtml(poem.dynasty || "未标") + ' · ' + escapeHtml(poem.body_len) + ' 字</div>' +
                (snippet ? '<div class="result-snippet"><span>命中片段</span>' + highlight(snippet) + '</div>' : '') +
            '</button>';
        }}).join("") + (results.length > visible.length ? '<div class="empty">已显示前 ' + visible.length + ' 首</div>' : "");
        Array.from(els.list.querySelectorAll(".result-item")).forEach(function (button) {{
            button.addEventListener("click", function () {{
                state.activeId = Number(button.dataset.id);
                render();
            }});
        }});
        renderDetail(poems.find(function (poem) {{ return poem.id === state.activeId; }}) || results[0]);
    }}

    function renderDetail(poem) {{
        if (!poem) {{
            els.detail.innerHTML = '<div class="empty">暂无诗作</div>';
            return;
        }}
        els.detail.innerHTML =
            '<h2>' + highlight(poem.title) + '</h2>' +
            '<div class="detail-meta">' +
                '<span class="tag">' + escapeHtml(poem.poet) + '</span>' +
                '<span class="tag">' + escapeHtml(poem.dynasty || "未标") + '</span>' +
                '<span class="tag">' + escapeHtml(poem.school || "未分") + '</span>' +
                '<span class="tag">' + escapeHtml(poem.season || "未标") + '</span>' +
                '<span class="tag">情感 ' + escapeHtml(poem.sentiment) + '</span>' +
            '</div>' +
            '<div class="poem-body">' + highlight(poem.body) + '</div>' +
            renderBackground(poem.background);
    }}

    function render(options) {{
        const settings = options || {{}};
        renderList(filteredPoems());
        if (settings.persist !== false) {{
            persistState(settings.message || "筛选状态已保存，可复制当前 URL 作为深链。");
        }}
    }}

    fillSelect(els.poet, uniqueSorted("poet"));
    fillSelect(els.dynasty, uniqueSorted("dynasty"));
    fillSelect(els.school, uniqueSorted("school"));
    fillSelect(els.season, uniqueSorted("season"));
    const urlState = stateFromUrl();
    if (urlState && applyState(urlState)) {{
        setHint("已从 URL 深链恢复筛选状态。");
    }} else if (applyState(stateFromStorage())) {{
        setHint("已恢复上次筛选状态。");
    }}
    syncControls();

    els.query.addEventListener("input", function () {{ state.query = els.query.value; render(); }});
    els.poet.addEventListener("change", function () {{ state.poet = els.poet.value; render(); }});
    els.dynasty.addEventListener("change", function () {{ state.dynasty = els.dynasty.value; render(); }});
    els.school.addEventListener("change", function () {{ state.school = els.school.value; render(); }});
    els.season.addEventListener("change", function () {{ state.season = els.season.value; render(); }});
    els.reset.addEventListener("click", function () {{
        state.query = "";
        state.poet = "";
        state.dynasty = "";
        state.school = "";
        state.season = "";
        els.query.value = "";
        els.poet.value = "";
        els.dynasty.value = "";
        els.school.value = "";
        els.season.value = "";
        state.activeId = poems[0] ? poems[0].id : null;
        render({{ message: "筛选已重置，默认状态已保存。" }});
    }});
    els.copyLink.addEventListener("click", function () {{
        const link = currentShareLink();
        setHint("当前筛选链接已复制/可复制：" + link);
        if (navigator.clipboard && navigator.clipboard.writeText) {{
            navigator.clipboard.writeText(link).catch(function () {{
                setHint("当前筛选链接可复制：" + link);
            }});
        }}
    }});
    els.clearMemory.addEventListener("click", function () {{
        localStorage.removeItem(STORAGE_KEY);
        window.history.replaceState(null, "", window.location.pathname);
        setHint("已清除本地记忆；当前页面筛选不会直接写回本地文件。");
    }});
    render({{ message: els.hint.textContent || "筛选状态已保存，可复制当前 URL 作为深链。" }});
    </script>
</body>
</html>
"""
    out = OUTPUT_DIR / "08_诗作检索.html"
    html = inject_index_backlink(html)
    out.write_text(html, encoding="utf-8")
    print(f"  [ok] saved {out}  ({len(poems)} 首诗 / {poet_count} 位诗人)")


if __name__ == "__main__":
    render()
