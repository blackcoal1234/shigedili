"""可视化 7：四季词摘选与频率检索页。

功能：
1. 从诗题 + 正文中提取包含“春、夏、秋、冬”的二字词。
2. 统计词频、涉及诗作数、示例诗句。
3. 生成 output/07_四季词摘选.html。
4. 页面支持关键词检索、季节筛选、朝代筛选、排序和示例查看。
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from html import escape
from pathlib import Path

import pymysql

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config import DB_NAME, MYSQL, OUTPUT_DIR
from viz_assets import inject_index_backlink


POEMS_JSON = ROOT / "data" / "poems.json"

SEASON_NAMES = {
    "春": "春",
    "夏": "夏",
    "秋": "秋",
    "冬": "冬",
}

CHINESE_BLOCK_RE = re.compile(r"[\u4e00-\u9fff]+")
SEASON_CHARS = set(SEASON_NAMES)

# 前缀型季节词：早春、暮春、初夏、中秋、深秋、寒冬等
SEASON_PREFIX_CHARS = set("早新初暮晚残深仲孟季三九中小大寒隆立")

# 这些字跟在春夏秋冬后面时，通常不是一个稳定的季节意象词。
BAD_SUFFIX_CHARS = set(
    "的了着过也矣兮乎者而与于以为是之不无有将欲更又复还便皆其此那"
    "我吾君子人天年月日时处里上下来去归入出见闻知看思忆怜爱恨愁"
    "呈和及或如若对向从当似胜"
)

# 这些词虽然含春夏秋冬，但在统计“四季意象词”时通常噪声偏大。
# 如果你希望“青春”“春秋”“千秋”也纳入，直接从这里删掉即可。
EXCLUDE_TERMS = {
    "青春",
    "春秋",
    "千秋",
    "万秋",
}

MAX_EXAMPLES = 8


@dataclass(frozen=True)
class PoemRecord:
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
        read_timeout=15,
        write_timeout=15,
        cursorclass=pymysql.cursors.DictCursor,
    )


def load_from_database() -> list[PoemRecord]:
    with conn() as c, c.cursor() as cur:
        cur.execute(
            """
            SELECT pm.title,
                   pt.name AS poet,
                   COALESCE(pt.dynasty, '') AS dynasty,
                   COALESCE(pt.school, '') AS school,
                   pm.body
              FROM t_poem pm
              JOIN t_poet pt ON pt.poet_id = pm.poet_id
             ORDER BY pt.dynasty, pt.name, pm.title
            """
        )
        rows = cur.fetchall()

    return [
        PoemRecord(
            title=str(row.get("title") or ""),
            poet=str(row.get("poet") or ""),
            dynasty=str(row.get("dynasty") or ""),
            school=str(row.get("school") or ""),
            body=str(row.get("body") or ""),
        )
        for row in rows
    ]


def load_from_poems_json(reason: Exception | None = None) -> list[PoemRecord]:
    if reason is not None:
        print(f"  [warn] 数据库读取失败，改用 poems.json 离线兜底：{reason}")

    records = json.loads(POEMS_JSON.read_text(encoding="utf-8"))
    poems: list[PoemRecord] = []

    for row in records:
        poems.append(
            PoemRecord(
                title=str(row.get("title") or ""),
                poet=str(row.get("poet") or row.get("author") or ""),
                dynasty=str(row.get("dynasty") or ""),
                school=str(row.get("school") or ""),
                body=str(row.get("body") or ""),
            )
        )

    return sorted(poems, key=lambda item: (item.dynasty, item.poet, item.title))


def load_poems() -> list[PoemRecord]:
    try:
        return load_from_database()
    except Exception as exc:
        return load_from_poems_json(exc)


def season_of_term(term: str) -> str:
    for ch in term:
        if ch in SEASON_NAMES:
            return SEASON_NAMES[ch]
    return "未标"


def is_valid_term(term: str) -> bool:
    if len(term) != 2:
        return False
    if term in EXCLUDE_TERMS:
        return False
    if not all("\u4e00" <= ch <= "\u9fff" for ch in term):
        return False
    return any(ch in SEASON_CHARS for ch in term)


def extract_season_terms(text: str) -> list[str]:
    """提取包含春夏秋冬的二字词。

    规则说明：
    - 优先抓“春 + 后一字”，例如春蚕、春风、春水、春草。
    - 同时抓“修饰字 + 春夏秋冬”，例如早春、初夏、中秋、寒冬。
    - 过滤明显不是词的组合，例如春呈、春而、春于。
    """
    terms: list[str] = []

    for match in CHINESE_BLOCK_RE.finditer(text or ""):
        block = match.group(0)
        for index, char in enumerate(block):
            if char not in SEASON_CHARS:
                continue

            # 后接型：春蚕、春风、夏日、秋水、冬雪
            if index + 1 < len(block):
                nxt = block[index + 1]
                term = block[index:index + 2]
                if nxt not in BAD_SUFFIX_CHARS and is_valid_term(term):
                    terms.append(term)

            # 前缀型：早春、初夏、中秋、寒冬
            if index > 0:
                prev = block[index - 1]
                term = block[index - 1:index + 1]
                if prev in SEASON_PREFIX_CHARS and is_valid_term(term):
                    terms.append(term)

    return terms


def context_snippet(text: str, term: str, limit: int = 90) -> str:
    clean = " ".join((text or "").split())
    if not clean:
        return ""

    index = clean.find(term)
    if index < 0:
        return clean[:limit]

    radius = max(12, (limit - len(term)) // 2)
    start = max(0, index - radius)
    end = min(len(clean), index + len(term) + radius)
    snippet = clean[start:end]

    if start > 0:
        snippet = "…" + snippet
    if end < len(clean):
        snippet += "…"

    return snippet


def build_payload() -> dict[str, object]:
    poems = load_poems()

    term_freq: Counter[str] = Counter()
    term_poem_count: Counter[str] = Counter()
    term_examples: dict[str, list[dict[str, object]]] = defaultdict(list)
    season_freq: Counter[str] = Counter()

    for poem in poems:
        text = f"{poem.title}\n{poem.body}"
        terms = extract_season_terms(text)
        if not terms:
            continue

        per_poem = Counter(terms)
        for term, count in per_poem.items():
            season = season_of_term(term)
            term_freq[term] += count
            term_poem_count[term] += 1
            season_freq[season] += count

            if len(term_examples[term]) < MAX_EXAMPLES:
                term_examples[term].append(
                    {
                        "title": poem.title,
                        "poet": poem.poet,
                        "dynasty": poem.dynasty,
                        "school": poem.school,
                        "freq": int(count),
                        "snippet": context_snippet(text, term),
                    }
                )

    rows = []
    for term, freq in term_freq.most_common():
        rows.append(
            {
                "term": term,
                "season": season_of_term(term),
                "freq": int(freq),
                "poemCount": int(term_poem_count[term]),
                "examples": term_examples.get(term, []),
            }
        )

    top_terms = rows[:30]

    return {
        "summary": {
            "poemCount": len(poems),
            "termCount": len(rows),
            "mentionCount": int(sum(term_freq.values())),
            "springCount": int(season_freq["春"]),
            "summerCount": int(season_freq["夏"]),
            "autumnCount": int(season_freq["秋"]),
            "winterCount": int(season_freq["冬"]),
        },
        "rows": rows,
        "topTerms": top_terms,
        "seasonFreq": [
            {"season": "春", "freq": int(season_freq["春"])},
            {"season": "夏", "freq": int(season_freq["夏"])},
            {"season": "秋", "freq": int(season_freq["秋"])},
            {"season": "冬", "freq": int(season_freq["冬"])},
        ],
    }


def render() -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    payload = build_payload()
    data_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    summary = payload["summary"]

    html = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>诗行万里 · 四季词摘选</title>
    <style>
    :root {
        --bg: #f4f7fb;
        --panel: #ffffff;
        --ink: #102033;
        --muted: #627083;
        --line: #d9e2ee;
        --accent: #0f766e;
        --soft: #def7ef;
        --spring: #16a34a;
        --summer: #dc2626;
        --autumn: #b45309;
        --winter: #2563eb;
    }
    * { box-sizing: border-box; }
    body {
        margin: 0;
        min-height: 100vh;
        background: var(--bg);
        color: var(--ink);
        font-family: "Microsoft YaHei", "PingFang SC", Arial, sans-serif;
    }
    .shell {
        width: min(1240px, calc(100vw - 32px));
        margin: 0 auto;
        padding: 28px 0 44px;
    }
    h1 {
        margin: 0;
        font-size: 30px;
        line-height: 1.2;
    }
    .subtitle {
        margin: 9px 0 0;
        max-width: 860px;
        color: var(--muted);
        font-size: 14px;
        line-height: 1.75;
    }
    .metrics {
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        gap: 12px;
        margin: 18px 0;
    }
    .metric,
    .panel {
        border: 1px solid var(--line);
        border-radius: 10px;
        background: var(--panel);
    }
    .metric {
        min-height: 84px;
        padding: 14px 16px;
    }
    .metric span {
        display: block;
        color: var(--muted);
        font-size: 13px;
    }
    .metric strong {
        display: block;
        margin-top: 8px;
        font-size: 24px;
        line-height: 1.2;
    }
    .season-strip {
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        gap: 12px;
        margin-bottom: 18px;
    }
    .season-card {
        padding: 14px 16px;
        border-radius: 10px;
        border: 1px solid var(--line);
        background: #fff;
    }
    .season-card span {
        color: var(--muted);
        font-size: 13px;
    }
    .season-card strong {
        display: block;
        margin-top: 8px;
        font-size: 22px;
    }
    .filters {
        display: grid;
        grid-template-columns: minmax(260px, 1.4fr) repeat(3, minmax(120px, 0.8fr)) auto;
        gap: 10px;
        align-items: end;
        padding: 14px;
        margin-bottom: 16px;
    }
    label {
        display: grid;
        gap: 6px;
        color: var(--muted);
        font-size: 13px;
    }
    input,
    select,
    button {
        min-height: 38px;
        border: 1px solid #cbd7e6;
        border-radius: 7px;
        background: #fff;
        color: var(--ink);
        font: inherit;
        font-size: 14px;
    }
    input,
    select {
        width: 100%;
        padding: 0 10px;
    }
    button {
        padding: 0 14px;
        cursor: pointer;
        background: var(--ink);
        color: #fff;
        font-weight: 700;
    }
    .layout {
        display: grid;
        grid-template-columns: minmax(0, 0.95fr) minmax(360px, 1.05fr);
        gap: 16px;
        align-items: start;
    }
    .panel-head {
        display: flex;
        justify-content: space-between;
        align-items: baseline;
        gap: 12px;
        padding: 14px 16px;
        border-bottom: 1px solid var(--line);
    }
    .panel-head h2 {
        margin: 0;
        font-size: 18px;
    }
    .panel-head span {
        color: var(--muted);
        font-size: 13px;
    }
    .chart {
        padding: 12px 16px 16px;
    }
    .bar-row {
        display: grid;
        grid-template-columns: 64px minmax(0, 1fr) 52px;
        gap: 10px;
        align-items: center;
        min-height: 30px;
        margin: 4px 0;
        cursor: pointer;
    }
    .bar-term {
        font-weight: 700;
    }
    .bar-track {
        height: 12px;
        border-radius: 999px;
        background: #edf2f7;
        overflow: hidden;
    }
    .bar-fill {
        height: 100%;
        width: var(--w);
        border-radius: inherit;
        background: var(--accent);
    }
    .bar-value {
        color: var(--muted);
        text-align: right;
        font-variant-numeric: tabular-nums;
    }
    .table-wrap {
        max-height: 660px;
        overflow: auto;
    }
    table {
        width: 100%;
        border-collapse: collapse;
        font-size: 14px;
    }
    th,
    td {
        padding: 11px 12px;
        border-bottom: 1px solid var(--line);
        text-align: left;
        vertical-align: top;
    }
    th {
        position: sticky;
        top: 0;
        z-index: 1;
        background: #f8fafc;
        color: #334155;
        font-size: 13px;
    }
    tr {
        cursor: pointer;
    }
    tr:hover {
        background: #f8fafc;
    }
    tr.is-active {
        background: var(--soft);
    }
    .term-cell {
        font-weight: 800;
        font-size: 16px;
    }
    .pill {
        display: inline-flex;
        align-items: center;
        min-height: 24px;
        padding: 0 8px;
        border-radius: 999px;
        font-size: 12px;
        font-weight: 800;
        background: #f1f5f9;
    }
    .pill.spring { color: var(--spring); background: #ecfdf5; }
    .pill.summer { color: var(--summer); background: #fef2f2; }
    .pill.autumn { color: var(--autumn); background: #fffbeb; }
    .pill.winter { color: var(--winter); background: #eff6ff; }
    .example {
        padding: 14px 16px;
        border-bottom: 1px solid var(--line);
    }
    .example:last-child {
        border-bottom: 0;
    }
    .example h3 {
        margin: 0;
        font-size: 16px;
        line-height: 1.45;
    }
    .example-meta {
        margin-top: 6px;
        color: var(--muted);
        font-size: 13px;
    }
    .snippet {
        margin-top: 9px;
        color: #334155;
        font-size: 14px;
        line-height: 1.75;
    }
    mark {
        padding: 0 2px;
        border-radius: 3px;
        background: #fef3c7;
        color: inherit;
    }
    .empty {
        padding: 22px 16px;
        color: var(--muted);
        line-height: 1.7;
    }
    @media (max-width: 920px) {
        .metrics,
        .season-strip {
            grid-template-columns: repeat(2, minmax(0, 1fr));
        }
        .filters {
            grid-template-columns: 1fr 1fr;
        }
        .filters label:first-child {
            grid-column: 1 / -1;
        }
        .layout {
            grid-template-columns: 1fr;
        }
    }
    @media (max-width: 560px) {
        .shell {
            width: min(100vw - 20px, 1240px);
            padding-top: 18px;
        }
        h1 {
            font-size: 25px;
        }
        .metrics,
        .season-strip,
        .filters {
            grid-template-columns: 1fr;
        }
    }
    </style>
</head>
<body>
    <main class="shell">
        <section>
            <h1>诗行万里 · 四季词摘选</h1>
            <p class="subtitle">
                从诗题和正文中自动摘出包含“春、夏、秋、冬”的季节词，
                例如“春蚕到死丝方尽”中的“春蚕”，并统计出现频率、涉及诗作和上下文示例。
            </p>
        </section>

        <section class="metrics" aria-label="统计概览">
            <div class="metric"><span>诗作样本</span><strong>__POEM_COUNT__ 首</strong></div>
            <div class="metric"><span>四季词种数</span><strong>__TERM_COUNT__ 个</strong></div>
            <div class="metric"><span>四季词总频次</span><strong>__MENTION_COUNT__ 次</strong></div>
            <div class="metric"><span>当前显示</span><strong id="visibleCount">0 个</strong></div>
        </section>

        <section class="season-strip" aria-label="四季频次">
            <div class="season-card"><span>春词频次</span><strong>__SPRING_COUNT__</strong></div>
            <div class="season-card"><span>夏词频次</span><strong>__SUMMER_COUNT__</strong></div>
            <div class="season-card"><span>秋词频次</span><strong>__AUTUMN_COUNT__</strong></div>
            <div class="season-card"><span>冬词频次</span><strong>__WINTER_COUNT__</strong></div>
        </section>

        <section class="panel filters" aria-label="筛选">
            <label>检索
                <input id="queryInput" type="search" placeholder="词语、诗人、题名、上下文" autocomplete="off">
            </label>
            <label>季节
                <select id="seasonFilter">
                    <option value="">全部</option>
                    <option value="春">春</option>
                    <option value="夏">夏</option>
                    <option value="秋">秋</option>
                    <option value="冬">冬</option>
                </select>
            </label>
            <label>朝代
                <select id="dynastyFilter">
                    <option value="">全部</option>
                </select>
            </label>
            <label>排序
                <select id="sortSelect">
                    <option value="freq">按频次降序</option>
                    <option value="poemCount">按诗作数降序</option>
                    <option value="term">按词语排序</option>
                </select>
            </label>
            <button id="resetButton" type="button">重置</button>
        </section>

        <section class="layout">
            <section class="panel">
                <div class="panel-head">
                    <h2>高频四季词</h2>
                    <span>点击条形可快速筛选</span>
                </div>
                <div id="topChart" class="chart"></div>
            </section>

            <section class="panel">
                <div class="panel-head">
                    <h2>词频表</h2>
                    <span id="tableHint">点击词条查看示例</span>
                </div>
                <div class="table-wrap">
                    <table>
                        <thead>
                            <tr>
                                <th>词语</th>
                                <th>季节</th>
                                <th>总频次</th>
                                <th>涉及诗作</th>
                                <th>示例</th>
                            </tr>
                        </thead>
                        <tbody id="termTable"></tbody>
                    </table>
                </div>
            </section>
        </section>

        <section class="panel" style="margin-top:16px;">
            <div class="panel-head">
                <h2 id="detailTitle">词语示例</h2>
                <span id="detailHint">选择一个词语查看诗句上下文</span>
            </div>
            <div id="detailPanel">
                <div class="empty">暂无选择。</div>
            </div>
        </section>
    </main>

    <script>
    window.SEASON_TERM_DATA = __PAYLOAD__;

    const payload = window.SEASON_TERM_DATA;
    const rows = payload.rows || [];
    const els = {
        query: document.getElementById("queryInput"),
        season: document.getElementById("seasonFilter"),
        dynasty: document.getElementById("dynastyFilter"),
        sort: document.getElementById("sortSelect"),
        reset: document.getElementById("resetButton"),
        chart: document.getElementById("topChart"),
        table: document.getElementById("termTable"),
        visibleCount: document.getElementById("visibleCount"),
        detailTitle: document.getElementById("detailTitle"),
        detailHint: document.getElementById("detailHint"),
        detailPanel: document.getElementById("detailPanel"),
    };

    let activeTerm = rows[0] ? rows[0].term : "";

    function normalize(value) {
        return String(value || "").trim().toLowerCase();
    }

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

    function cssSeason(season) {
        if (season === "春") return "spring";
        if (season === "夏") return "summer";
        if (season === "秋") return "autumn";
        if (season === "冬") return "winter";
        return "";
    }

    function uniqueDynasties() {
        const set = new Set();
        rows.forEach(function (row) {
            (row.examples || []).forEach(function (example) {
                if (example.dynasty) set.add(example.dynasty);
            });
        });
        return Array.from(set).sort();
    }

    function fillDynastyFilter() {
        uniqueDynasties().forEach(function (dynasty) {
            const opt = document.createElement("option");
            opt.value = dynasty;
            opt.textContent = dynasty;
            els.dynasty.appendChild(opt);
        });
    }

    function rowSearchText(row) {
        const exampleText = (row.examples || []).map(function (item) {
            return [item.title, item.poet, item.dynasty, item.school, item.snippet].join(" ");
        }).join(" ");
        return normalize([row.term, row.season, exampleText].join(" "));
    }

    function filterRows() {
        const query = normalize(els.query.value);
        const season = els.season.value;
        const dynasty = els.dynasty.value;

        let filtered = rows.filter(function (row) {
            const matchQuery = !query || rowSearchText(row).indexOf(query) >= 0;
            const matchSeason = !season || row.season === season;
            const matchDynasty = !dynasty || (row.examples || []).some(function (item) {
                return item.dynasty === dynasty;
            });
            return matchQuery && matchSeason && matchDynasty;
        });

        const sortBy = els.sort.value;
        filtered.sort(function (a, b) {
            if (sortBy === "term") {
                return a.term.localeCompare(b.term, "zh-Hans-CN");
            }
            if (sortBy === "poemCount") {
                return (b.poemCount || 0) - (a.poemCount || 0) || (b.freq || 0) - (a.freq || 0);
            }
            return (b.freq || 0) - (a.freq || 0) || (b.poemCount || 0) - (a.poemCount || 0);
        });

        return filtered;
    }

    function renderChart(filtered) {
        const top = filtered.slice(0, 20);
        const max = Math.max.apply(null, top.map(function (row) { return row.freq || 0; }).concat([1]));

        if (!top.length) {
            els.chart.innerHTML = '<div class="empty">没有匹配的词语。</div>';
            return;
        }

        els.chart.innerHTML = top.map(function (row) {
            const width = Math.max(3, Math.round((row.freq || 0) / max * 100));
            return [
                '<div class="bar-row" data-term="' + escapeHtml(row.term) + '">',
                '<div class="bar-term">' + escapeHtml(row.term) + '</div>',
                '<div class="bar-track"><div class="bar-fill" style="--w:' + width + '%"></div></div>',
                '<div class="bar-value">' + escapeHtml(row.freq) + '</div>',
                '</div>'
            ].join("");
        }).join("");

        Array.prototype.forEach.call(els.chart.querySelectorAll(".bar-row"), function (node) {
            node.addEventListener("click", function () {
                activeTerm = node.dataset.term || "";
                els.query.value = activeTerm;
                render();
            });
        });
    }

    function renderTable(filtered) {
        els.visibleCount.textContent = filtered.length + " 个";

        if (!filtered.length) {
            els.table.innerHTML = '<tr><td colspan="5" class="empty">没有匹配的词语。</td></tr>';
            return;
        }

        els.table.innerHTML = filtered.map(function (row) {
            const first = (row.examples || [])[0] || {};
            const example = first.poet || first.title
                ? escapeHtml(first.poet || "") + "《" + escapeHtml(first.title || "") + "》"
                : "暂无";
            const active = row.term === activeTerm ? " class=\\"is-active\\"" : "";
            return [
                '<tr data-term="' + escapeHtml(row.term) + '"' + active + '>',
                '<td class="term-cell">' + escapeHtml(row.term) + '</td>',
                '<td><span class="pill ' + cssSeason(row.season) + '">' + escapeHtml(row.season) + '</span></td>',
                '<td>' + escapeHtml(row.freq) + '</td>',
                '<td>' + escapeHtml(row.poemCount) + '</td>',
                '<td>' + example + '</td>',
                '</tr>'
            ].join("");
        }).join("");

        Array.prototype.forEach.call(els.table.querySelectorAll("tr[data-term]"), function (node) {
            node.addEventListener("click", function () {
                activeTerm = node.dataset.term || "";
                renderDetail();
                renderTable(filterRows());
            });
        });
    }

    function highlight(text, term) {
        const safe = escapeHtml(text || "");
        if (!term) return safe;
        return safe.split(escapeHtml(term)).join("<mark>" + escapeHtml(term) + "</mark>");
    }

    function renderDetail() {
        const row = rows.find(function (item) { return item.term === activeTerm; });

        if (!row) {
            els.detailTitle.textContent = "词语示例";
            els.detailHint.textContent = "选择一个词语查看诗句上下文";
            els.detailPanel.innerHTML = '<div class="empty">暂无选择。</div>';
            return;
        }

        els.detailTitle.textContent = "“" + row.term + "”的诗句示例";
        els.detailHint.textContent = "总频次 " + row.freq + " 次 / 涉及 " + row.poemCount + " 首诗";

        const examples = row.examples || [];
        if (!examples.length) {
            els.detailPanel.innerHTML = '<div class="empty">暂无示例。</div>';
            return;
        }

        els.detailPanel.innerHTML = examples.map(function (item) {
            const meta = [item.dynasty, item.school, "本诗命中 " + (item.freq || 1) + " 次"]
                .filter(Boolean)
                .join(" / ");
            return [
                '<article class="example">',
                '<h3>' + escapeHtml(item.poet || "未标") + '《' + escapeHtml(item.title || "未题") + '》</h3>',
                '<div class="example-meta">' + escapeHtml(meta) + '</div>',
                '<div class="snippet">' + highlight(item.snippet || "", row.term) + '</div>',
                '</article>'
            ].join("");
        }).join("");
    }

    function render() {
        const filtered = filterRows();
        if (!filtered.some(function (row) { return row.term === activeTerm; })) {
            activeTerm = filtered[0] ? filtered[0].term : "";
        }
        renderChart(filtered);
        renderTable(filtered);
        renderDetail();
    }

    fillDynastyFilter();

    els.query.addEventListener("input", render);
    els.season.addEventListener("change", render);
    els.dynasty.addEventListener("change", render);
    els.sort.addEventListener("change", render);
    els.reset.addEventListener("click", function () {
        els.query.value = "";
        els.season.value = "";
        els.dynasty.value = "";
        els.sort.value = "freq";
        activeTerm = rows[0] ? rows[0].term : "";
        render();
    });

    render();
    </script>
</body>
</html>
"""

    html = html.replace("__PAYLOAD__", data_json)
    html = html.replace("__POEM_COUNT__", f"{summary['poemCount']:,}")
    html = html.replace("__TERM_COUNT__", f"{summary['termCount']:,}")
    html = html.replace("__MENTION_COUNT__", f"{summary['mentionCount']:,}")
    html = html.replace("__SPRING_COUNT__", f"{summary['springCount']:,}")
    html = html.replace("__SUMMER_COUNT__", f"{summary['summerCount']:,}")
    html = html.replace("__AUTUMN_COUNT__", f"{summary['autumnCount']:,}")
    html = html.replace("__WINTER_COUNT__", f"{summary['winterCount']:,}")

    html = inject_index_backlink(html)
    out = OUTPUT_DIR / "07_四季词摘选.html"
    out.write_text(html, encoding="utf-8")

    print(
        f"  [ok] saved {out}  "
        f"({summary['termCount']} 个四季词 / {summary['mentionCount']} 次命中)"
    )


if __name__ == "__main__":
    render()