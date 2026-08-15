"""可视化 10：离线诗人对比页。"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config import OUTPUT_DIR
from data.image_dict import IMAGE_DICT, lookup as lookup_image, words as image_words
from data.place_dict import PLACE_DICT, aliases as place_aliases
from data.season_rules import detect_season
from viz_assets import inject_index_backlink


POEMS_JSON = ROOT / "data" / "poems.json"
MAX_TOP_ITEMS = 10
MAX_REPRESENTATIVE_POEMS = 8


def greedy_counts(text: str, tokens: list[str]) -> Counter[str]:
    """按长词优先贪心计数，避免短词重复吞掉长词。"""
    counts: Counter[str] = Counter()
    work = text or ""
    for token in tokens:
        count = work.count(token)
        if count:
            counts[token] += count
            work = work.replace(token, "路" * len(token))
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


def load_poems() -> list[dict[str, str]]:
    records = json.loads(POEMS_JSON.read_text(encoding="utf-8"))
    poems: list[dict[str, str]] = []
    for row in records:
        poems.append(
            {
                "title": str(row.get("title") or ""),
                "poet": str(row.get("poet") or row.get("author") or ""),
                "dynasty": str(row.get("dynasty") or ""),
                "school": str(row.get("school") or ""),
                "body": str(row.get("body") or ""),
            }
        )
    return poems


def place_rows(counter: Counter[str], limit: int | None = None) -> list[dict[str, object]]:
    meta = {alias: (modern, province) for alias, modern, province, *_ in PLACE_DICT}
    rows = []
    items = counter.most_common(limit) if limit is not None else counter.most_common()
    for word, count in items:
        modern, province = meta.get(word, ("", ""))
        rows.append({"word": word, "count": int(count), "modern": modern, "province": province})
    return rows


def image_rows(counter: Counter[str], limit: int | None = None) -> list[dict[str, object]]:
    meta = {word: (category, sentiment) for word, category, sentiment in IMAGE_DICT}
    rows = []
    items = counter.most_common(limit) if limit is not None else counter.most_common()
    for word, count in items:
        category, sentiment = meta.get(word, ("", 0))
        rows.append({"word": word, "count": int(count), "category": category, "sentiment": sentiment})
    return rows


def build_payload() -> dict[str, object]:
    poems = load_poems()
    place_tokens = place_aliases()
    image_tokens = image_words()
    grouped: dict[str, dict[str, object]] = {}

    for poem in poems:
        poet = poem["poet"]
        if not poet:
            continue
        body = poem["body"]
        title = poem["title"]
        place_counts = greedy_counts(f"{title}\n{body}", place_tokens)
        image_counts = greedy_counts(body, image_tokens)
        sentiment = estimate_sentiment(image_counts)
        season = detect_season(title, body) or "未标"
        group = grouped.setdefault(
            poet,
            {
                "poet": poet,
                "dynasty": poem["dynasty"],
                "school": poem["school"],
                "poem_count": 0,
                "total_chars": 0,
                "sentiment_total": 0.0,
                "season_counts": Counter(),
                "place_counts": Counter(),
                "image_counts": Counter(),
                "representative_poems": [],
            },
        )
        group["poem_count"] = int(group["poem_count"]) + 1
        group["total_chars"] = int(group["total_chars"]) + len(body)
        group["sentiment_total"] = float(group["sentiment_total"]) + sentiment
        group["season_counts"][season] += 1
        group["place_counts"].update(place_counts)
        group["image_counts"].update(image_counts)
        representatives = group["representative_poems"]
        if isinstance(representatives, list) and len(representatives) < MAX_REPRESENTATIVE_POEMS:
            representatives.append(
                {
                    "title": title,
                    "season": season,
                    "sentiment": round(sentiment, 3),
                    "body_len": len(body),
                    "excerpt": body.replace("\n", " ")[:96],
                }
            )

    summaries: dict[str, dict[str, object]] = {}
    for poet, group in grouped.items():
        poem_count = int(group["poem_count"])
        season_counts = {season: int(count) for season, count in group["season_counts"].items()}
        summaries[poet] = {
            "poet": poet,
            "dynasty": group["dynasty"],
            "school": group["school"],
            "poem_count": poem_count,
            "total_chars": int(group["total_chars"]),
            "avg_body_len": round(int(group["total_chars"]) / poem_count, 1) if poem_count else 0,
            "avg_sentiment": round(float(group["sentiment_total"]) / poem_count, 3) if poem_count else 0,
            "season_counts": season_counts,
            "top_places": place_rows(group["place_counts"], MAX_TOP_ITEMS),
            "top_images": image_rows(group["image_counts"], MAX_TOP_ITEMS),
            "all_places": place_rows(group["place_counts"]),
            "all_images": image_rows(group["image_counts"]),
            "representative_poems": group["representative_poems"],
        }

    poets = sorted(summaries, key=lambda name: (str(summaries[name].get("dynasty") or ""), name))
    defaults = {
        "a": "李白" if "李白" in summaries else (poets[0] if poets else ""),
        "b": "杜甫" if "杜甫" in summaries else (poets[1] if len(poets) > 1 else (poets[0] if poets else "")),
    }
    return {
        "poets": poets,
        "summaries": summaries,
        "defaults": defaults,
        "summary": {
            "poet_count": len(poets),
            "poem_count": len(poems),
            "place_alias_count": len(PLACE_DICT),
            "image_word_count": len(IMAGE_DICT),
        },
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
    <title>诗行万里 · 诗人对比</title>
    <style>
    :root {
        --bg: #f4f7fb;
        --panel: #ffffff;
        --ink: #102033;
        --muted: #627083;
        --line: #d9e2ee;
        --accent: #0f766e;
        --accent-soft: #def7ef;
        --warn: #9f580a;
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
        padding: 28px 0 42px;
    }
    h1 {
        margin: 0;
        font-size: 30px;
        line-height: 1.2;
        letter-spacing: 0;
    }
    .subtitle {
        max-width: 840px;
        margin: 9px 0 0;
        color: var(--muted);
        font-size: 14px;
        line-height: 1.75;
    }
    .metrics {
        display: grid;
        grid-template-columns: repeat(4, minmax(120px, 1fr));
        gap: 10px;
        margin: 18px 0 16px;
    }
    .metric,
    .panel {
        border: 1px solid var(--line);
        border-radius: 8px;
        background: var(--panel);
    }
    .metric {
        min-height: 76px;
        padding: 13px 15px;
    }
    .metric span {
        display: block;
        color: var(--muted);
        font-size: 13px;
    }
    .metric strong {
        display: block;
        margin-top: 8px;
        font-size: 22px;
        line-height: 1.2;
        letter-spacing: 0;
    }
    .filters {
        display: grid;
        grid-template-columns: minmax(180px, 1fr) minmax(180px, 1fr) auto;
        gap: 10px;
        align-items: end;
        padding: 14px;
        margin-bottom: 16px;
    }
    .state-panel {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
        padding: 13px 14px;
        margin-bottom: 16px;
    }
    .state-panel span {
        display: block;
        color: var(--muted);
        font-size: 12px;
    }
    .state-panel strong {
        display: block;
        margin-top: 4px;
        font-size: 15px;
        line-height: 1.45;
        overflow-wrap: anywhere;
    }
    .state-panel small {
        display: block;
        min-height: 18px;
        margin-top: 4px;
        color: var(--accent);
        font-size: 12px;
        line-height: 1.5;
    }
    .state-actions {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
        justify-content: flex-end;
    }
    label {
        display: grid;
        gap: 6px;
        color: var(--muted);
        font-size: 13px;
    }
    select,
    button {
        min-height: 38px;
        border: 1px solid #cbd7e6;
        border-radius: 6px;
        background: #fff;
        color: var(--ink);
        font: inherit;
        font-size: 14px;
    }
    select { width: 100%; padding: 0 10px; }
    button {
        padding: 0 14px;
        background: var(--ink);
        color: #fff;
        font-weight: 700;
        cursor: pointer;
    }
    .button-secondary {
        background: #fff;
        color: var(--ink);
    }
    .compare-grid {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 16px;
    }
    .panel { overflow: hidden; }
    .panel-head {
        display: flex;
        align-items: baseline;
        justify-content: space-between;
        gap: 10px;
        padding: 14px 16px;
        border-bottom: 1px solid var(--line);
    }
    .panel-head h2 {
        margin: 0;
        font-size: 18px;
        line-height: 1.35;
        letter-spacing: 0;
    }
    .panel-head span {
        color: var(--muted);
        font-size: 13px;
    }
    .panel-body { padding: 14px 16px 16px; }
    .stat-grid {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 8px;
        margin-bottom: 14px;
    }
    .mini-stat {
        min-height: 64px;
        padding: 10px;
        border: 1px solid var(--line);
        border-radius: 7px;
        background: #f8fafc;
    }
    .mini-stat span {
        display: block;
        color: var(--muted);
        font-size: 12px;
    }
    .mini-stat strong {
        display: block;
        margin-top: 5px;
        font-size: 18px;
        line-height: 1.2;
        overflow-wrap: anywhere;
    }
    .section-title {
        margin: 16px 0 8px;
        color: #334155;
        font-size: 15px;
        line-height: 1.35;
        letter-spacing: 0;
    }
    .bars {
        display: grid;
        gap: 7px;
    }
    .bar-row {
        display: grid;
        grid-template-columns: 42px minmax(0, 1fr) 42px;
        gap: 8px;
        align-items: center;
        color: var(--muted);
        font-size: 13px;
    }
    .bar-track {
        height: 10px;
        overflow: hidden;
        border-radius: 999px;
        background: #e2e8f0;
    }
    .bar-fill {
        height: 100%;
        min-width: 2px;
        border-radius: inherit;
        background: var(--accent);
    }
    .pill-list {
        display: flex;
        flex-wrap: wrap;
        gap: 7px;
    }
    .pill {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        max-width: 100%;
        min-height: 30px;
        padding: 5px 9px;
        border: 1px solid #cbd7e6;
        border-radius: 999px;
        background: #fff;
        color: #334155;
        font-size: 13px;
        overflow-wrap: anywhere;
    }
    .pill b { color: var(--warn); }
    .poems {
        display: grid;
        gap: 9px;
    }
    .poem {
        padding: 10px 11px;
        border: 1px solid var(--line);
        border-radius: 7px;
        background: #fbfdff;
    }
    .poem strong {
        display: block;
        margin-bottom: 5px;
        font-size: 14px;
    }
    .poem p {
        margin: 0;
        color: var(--muted);
        font-size: 13px;
        line-height: 1.6;
    }
    .shared {
        margin-top: 16px;
    }
    .difference {
        margin-top: 16px;
    }
    .difference-grid {
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        gap: 10px;
    }
    .diff-card {
        min-height: 88px;
        padding: 12px;
        border: 1px solid var(--line);
        border-radius: 7px;
        background: #fbfdff;
    }
    .diff-card span {
        display: block;
        color: var(--muted);
        font-size: 12px;
    }
    .diff-card strong {
        display: block;
        margin-top: 6px;
        color: var(--ink);
        font-size: 16px;
        line-height: 1.35;
        overflow-wrap: anywhere;
    }
    .diff-card p {
        margin: 5px 0 0;
        color: var(--muted);
        font-size: 12px;
        line-height: 1.45;
    }
    .shared-grid {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 12px;
    }
    .empty {
        color: var(--muted);
        font-size: 13px;
        line-height: 1.65;
    }
    @media (max-width: 860px) {
        .shell { width: min(100vw - 20px, 1240px); padding-top: 18px; }
        h1 { font-size: 25px; }
        .metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); }
        .filters,
        .state-panel,
        .compare-grid,
        .difference-grid,
        .shared-grid { grid-template-columns: 1fr; }
        .state-panel { align-items: stretch; }
        .state-actions { justify-content: flex-start; }
        .stat-grid { grid-template-columns: 1fr; }
    }
    </style>
</head>
<body>
    <main class="shell">
        <header>
            <h1>诗行万里 · 诗人对比</h1>
            <p class="subtitle">选择两位诗人，横向比较作品规模、季节分布、情感均值、高频地名、高频意象和代表诗作。统计口径与项目入库一致：地名匹配题名和正文，意象只匹配正文，并使用长词优先贪心计数。</p>
        </header>

        <section class="metrics" aria-label="数据规模">
            <div class="metric"><span>诗人</span><strong>__POET_COUNT__ 位</strong></div>
            <div class="metric"><span>诗作</span><strong>__POEM_COUNT__ 首</strong></div>
            <div class="metric"><span>地名词条</span><strong>__PLACE_COUNT__ 条</strong></div>
            <div class="metric"><span>意象词条</span><strong>__IMAGE_COUNT__ 条</strong></div>
        </section>

        <section class="panel filters" aria-label="选择诗人">
            <label>选择诗人 A
                <select id="poetASelect"></select>
            </label>
            <label>选择诗人 B
                <select id="poetBSelect"></select>
            </label>
            <button id="swapButton" type="button">交换</button>
        </section>

        <section class="panel state-panel" aria-label="对比状态">
            <div>
                <span>对比状态</span>
                <strong id="compareStateText">当前对比：加载中</strong>
                <small id="shareStatusText"></small>
            </div>
            <div class="state-actions">
                <button id="shareLinkButton" type="button">复制当前对比链接</button>
                <button id="copySummaryButton" type="button">复制对比摘要</button>
                <button id="clearMemoryButton" class="button-secondary" type="button">清除记忆</button>
            </div>
        </section>

        <section id="comparePanel" aria-label="对比概览"></section>
    </main>

    <script>
    window.POET_COMPARE_DATA = __DATA__;
    const data = window.POET_COMPARE_DATA;
    const STORAGE_KEY = "poetCompareState";
    const els = {
        poetA: document.getElementById("poetASelect"),
        poetB: document.getElementById("poetBSelect"),
        swap: document.getElementById("swapButton"),
        share: document.getElementById("shareLinkButton"),
        copySummary: document.getElementById("copySummaryButton"),
        clearMemory: document.getElementById("clearMemoryButton"),
        stateText: document.getElementById("compareStateText"),
        shareStatus: document.getElementById("shareStatusText"),
        panel: document.getElementById("comparePanel")
    };

    function escapeHtml(value) {
        return String(value == null ? "" : value).replace(/[&<>"']/g, function (ch) {
            return {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[ch];
        });
    }

    function fillSelect(select, selected) {
        select.innerHTML = data.poets.map(function (poet) {
            return '<option value="' + escapeHtml(poet) + '">' + escapeHtml(poet) + '</option>';
        }).join("");
        select.value = selected;
    }

    function isValidPoet(poet) {
        return Boolean(poet && data.summaries[poet]);
    }

    function validState(state) {
        if (!state || typeof state !== "object") return null;
        const a = String(state.a || "");
        const b = String(state.b || "");
        return isValidPoet(a) && isValidPoet(b) ? {a: a, b: b} : null;
    }

    function stateFromUrl() {
        try {
            const params = new URLSearchParams(window.location.search || "");
            return validState({a: params.get("a"), b: params.get("b")});
        } catch (_err) {
            return null;
        }
    }

    function stateFromStorage() {
        try {
            return validState(JSON.parse(localStorage.getItem(STORAGE_KEY) || "null"));
        } catch (_err) {
            return null;
        }
    }

    function initialState() {
        const urlState = stateFromUrl();
        if (urlState) return Object.assign({source: "URL 参数"}, urlState);
        const storedState = stateFromStorage();
        if (storedState) return Object.assign({source: "本地记忆"}, storedState);
        return {a: data.defaults.a, b: data.defaults.b, source: "默认对比"};
    }

    function currentState() {
        return {a: els.poetA.value, b: els.poetB.value};
    }

    function comparisonPath(state) {
        const params = new URLSearchParams();
        params.set("a", state.a);
        params.set("b", state.b);
        return (window.location.pathname || "10_诗人对比.html") + "?" + params.toString();
    }

    function comparisonHref(state) {
        const path = comparisonPath(state);
        try {
            return new URL(path, window.location.href).href;
        } catch (_err) {
            return path;
        }
    }

    function replaceUrl(path) {
        if (window.history && typeof window.history.replaceState === "function") {
            window.history.replaceState(null, "", path);
        }
    }

    function updateStateText(prefix) {
        const state = currentState();
        els.stateText.textContent = prefix + "：" + state.a + " / " + state.b;
    }

    function setShareStatus(message) {
        els.shareStatus.textContent = message || "";
    }

    function saveStateToMemory(state) {
        try {
            localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
            return true;
        } catch (_err) {
            return false;
        }
    }

    function persistCurrentState() {
        const state = currentState();
        if (!saveStateToMemory(state)) {
            setShareStatus("本地记忆不可用，仅更新当前链接。");
        }
        replaceUrl(comparisonPath(state));
        updateStateText("已记住当前对比");
    }

    function syncBootState(state) {
        const payload = {a: state.a, b: state.b};
        if (state.source === "URL 参数") {
            saveStateToMemory(payload);
        } else if (state.source === "本地记忆") {
            replaceUrl(comparisonPath(payload));
        }
    }

    function fmt(value, digits) {
        const number = Number(value || 0);
        return Number.isInteger(number) ? String(number) : number.toFixed(digits || 2);
    }

    function stat(label, value) {
        return '<div class="mini-stat"><span>' + escapeHtml(label) + '</span><strong>' + escapeHtml(value) + '</strong></div>';
    }

    function seasonBars(summary) {
        const seasons = ["春", "夏", "秋", "冬", "未标"];
        const counts = summary.season_counts || {};
        const maxValue = Math.max.apply(null, seasons.map(function (season) { return Number(counts[season] || 0); }).concat([1]));
        return '<div class="bars">' + seasons.map(function (season) {
            const value = Number(counts[season] || 0);
            const width = Math.max(2, Math.round(value / maxValue * 100));
            return '<div class="bar-row"><span>' + escapeHtml(season) + '</span><div class="bar-track"><div class="bar-fill" style="width:' + width + '%"></div></div><span>' + escapeHtml(value) + '</span></div>';
        }).join("") + '</div>';
    }

    function pillList(items, kind) {
        if (!items || !items.length) return '<div class="empty">暂无命中。</div>';
        return '<div class="pill-list">' + items.map(function (item) {
            const sub = kind === "place"
                ? [item.modern, item.province].filter(Boolean).join(" · ")
                : [item.category, item.sentiment ? "情感 " + item.sentiment : ""].filter(Boolean).join(" · ");
            return '<span class="pill"><span>' + escapeHtml(item.word) + '</span><b>' + escapeHtml(item.count) + '</b>' + (sub ? '<small>' + escapeHtml(sub) + '</small>' : '') + '</span>';
        }).join("") + '</div>';
    }

    function poemList(summary) {
        const poems = summary.representative_poems || [];
        if (!poems.length) return '<div class="empty">暂无代表诗作。</div>';
        return '<div class="poems">' + poems.map(function (poem) {
            return '<article class="poem"><strong>《' + escapeHtml(poem.title) + '》</strong><p>' +
                escapeHtml(poem.season || "未标") + ' · 情感 ' + escapeHtml(poem.sentiment) + ' · ' + escapeHtml(poem.body_len) + ' 字</p><p>' +
                escapeHtml(poem.excerpt || "") + '</p></article>';
        }).join("") + '</div>';
    }

    function card(summary) {
        return '<article class="panel">' +
            '<div class="panel-head"><h2>' + escapeHtml(summary.poet) + '</h2><span>' + escapeHtml([summary.dynasty, summary.school].filter(Boolean).join(" · ")) + '</span></div>' +
            '<div class="panel-body">' +
                '<div class="stat-grid">' +
                    stat("作品数", summary.poem_count + " 首") +
                    stat("平均字数", fmt(summary.avg_body_len, 1)) +
                    stat("情感均值", fmt(summary.avg_sentiment, 3)) +
                '</div>' +
                '<h3 class="section-title">季节分布</h3>' + seasonBars(summary) +
                '<h3 class="section-title">高频地名</h3>' + pillList(summary.top_places, "place") +
                '<h3 class="section-title">高频意象</h3>' + pillList(summary.top_images, "image") +
                '<h3 class="section-title">代表诗作</h3>' + poemList(summary) +
            '</div>' +
        '</article>';
    }

    function sharedItems(aItems, bItems) {
        const bByWord = new Map((bItems || []).map(function (item) { return [item.word, item]; }));
        return (aItems || []).filter(function (item) { return bByWord.has(item.word); }).map(function (item) {
            const other = bByWord.get(item.word);
            return Object.assign({}, item, {
                count: Number(item.count || 0) + Number(other.count || 0),
                leftCount: Number(item.count || 0),
                rightCount: Number(other.count || 0)
            });
        }).sort(function (left, right) { return right.count - left.count || left.word.localeCompare(right.word, "zh-Hans-CN"); }).slice(0, 10);
    }

    function sharedCount(aItems, bItems) {
        const bWords = new Set((bItems || []).map(function (item) { return item.word; }));
        return (aItems || []).filter(function (item) { return bWords.has(item.word); }).length;
    }

    function biggerLabel(aName, aValue, bName, bValue, unit, digits) {
        const left = Number(aValue || 0);
        const right = Number(bValue || 0);
        const diff = Math.abs(left - right);
        if (diff === 0) {
            return {
                strong: aName + " 与 " + bName + " 持平",
                detail: "差值 0" + unit
            };
        }
        const winner = left > right ? aName : bName;
        const loser = left > right ? bName : aName;
        return {
            strong: winner + " 高于 " + loser,
            detail: "差值 " + fmt(diff, digits) + unit
        };
    }

    function diffCard(label, result) {
        return '<div class="diff-card"><span>' + escapeHtml(label) + '</span><strong>' +
            escapeHtml(result.strong) + '</strong><p>' + escapeHtml(result.detail) + '</p></div>';
    }

    function renderDifferenceSummary(a, b) {
        const poemDiff = biggerLabel(a.poet, a.poem_count, b.poet, b.poem_count, " 首", 0);
        const lengthDiff = biggerLabel(a.poet, a.avg_body_len, b.poet, b.avg_body_len, " 字", 1);
        const sentimentDiff = biggerLabel(a.poet, a.avg_sentiment, b.poet, b.avg_sentiment, "", 3);
        const sharedPlaces = sharedCount(a.all_places, b.all_places);
        const sharedImages = sharedCount(a.all_images, b.all_images);
        return '<section id="differenceSummary" class="panel difference"><div class="panel-head"><h2>差异摘要</h2><span>' +
            escapeHtml(a.poet) + ' / ' + escapeHtml(b.poet) + '</span></div>' +
            '<div class="panel-body difference-grid">' +
                diffCard("作品数差异", poemDiff) +
                diffCard("平均字数差异", lengthDiff) +
                diffCard("情感均值差异", sentimentDiff) +
                '<div class="diff-card"><span>共同线索规模</span><strong>共同地名 ' + escapeHtml(sharedPlaces) +
                ' 个 / 共同意象 ' + escapeHtml(sharedImages) + ' 个</strong><p>基于全量地名和意象交集，不只看 Top10。</p></div>' +
            '</div></section>';
    }

    function sharedPillList(items, kind) {
        if (!items || !items.length) return '<div class="empty">暂无共同高频线索。</div>';
        return '<div class="pill-list">' + items.map(function (item) {
            const sub = kind === "place"
                ? [item.modern, item.province].filter(Boolean).join(" · ")
                : [item.category, item.sentiment ? "情感 " + item.sentiment : ""].filter(Boolean).join(" · ");
            return '<span class="pill"><span>' + escapeHtml(item.word) + '</span><b>A ' + escapeHtml(item.leftCount) + ' / B ' + escapeHtml(item.rightCount) + '</b>' + (sub ? '<small>' + escapeHtml(sub) + '</small>' : '') + '</span>';
        }).join("") + '</div>';
    }

    function renderShared(a, b) {
        const places = sharedItems(a.all_places, b.all_places);
        const images = sharedItems(a.all_images, b.all_images);
        return '<section class="panel shared"><div class="panel-head"><h2>共同线索</h2><span>' + escapeHtml(a.poet) + ' / ' + escapeHtml(b.poet) + '</span></div>' +
            '<div class="panel-body shared-grid">' +
                '<div><h3 class="section-title">共同高频地名</h3>' + sharedPillList(places, "place") + '</div>' +
                '<div><h3 class="section-title">共同高频意象</h3>' + sharedPillList(images, "image") + '</div>' +
            '</div></section>';
    }

    function render() {
        const a = data.summaries[els.poetA.value];
        const b = data.summaries[els.poetB.value];
        if (!a || !b) {
            els.panel.innerHTML = '<div class="panel"><div class="panel-body empty">请选择两位诗人。</div></div>';
            return;
        }
        els.panel.innerHTML = '<section class="compare-grid" aria-label="对比概览">' + card(a) + card(b) + '</section>' + renderDifferenceSummary(a, b) + renderShared(a, b);
    }

    function handleSelectionChange() {
        setShareStatus("");
        render();
        persistCurrentState();
    }

    function clearMemory() {
        try {
            localStorage.removeItem(STORAGE_KEY);
        } catch (_err) {
            setShareStatus("本地记忆不可用，已清空当前链接。");
        }
        replaceUrl(window.location.pathname || "10_诗人对比.html");
        updateStateText("未保存当前对比");
    }

    function fallbackCopy(text, onCopied, onBlocked) {
        const textarea = document.createElement("textarea");
        textarea.value = text;
        textarea.setAttribute("readonly", "readonly");
        textarea.style.position = "fixed";
        textarea.style.left = "-9999px";
        document.body.appendChild(textarea);
        textarea.select();
        try {
            if (document.execCommand && document.execCommand("copy")) {
                onCopied();
            } else {
                onBlocked();
            }
        } catch (_err) {
            onBlocked();
        }
        if (textarea.parentNode) {
            textarea.parentNode.removeChild(textarea);
        }
    }

    function copyText(text, onCopied, onBlocked) {
        if (navigator.clipboard && typeof navigator.clipboard.writeText === "function") {
            navigator.clipboard.writeText(text).then(function () {
                onCopied();
            }).catch(function () {
                fallbackCopy(text, onCopied, onBlocked);
            });
            return;
        }
        fallbackCopy(text, onCopied, onBlocked);
    }

    function copyCurrentLink() {
        const link = comparisonHref(currentState());
        copyText(link, function () {
            setShareStatus("已复制当前对比链接。");
        }, function () {
            setShareStatus("复制受限，可从地址栏复制当前链接。");
        });
    }

    function comparisonSummaryText() {
        const a = data.summaries[els.poetA.value];
        const b = data.summaries[els.poetB.value];
        if (!a || !b) return "";
        const poemDiff = biggerLabel(a.poet, a.poem_count, b.poet, b.poem_count, " 首", 0);
        const lengthDiff = biggerLabel(a.poet, a.avg_body_len, b.poet, b.avg_body_len, " 字", 1);
        const sentimentDiff = biggerLabel(a.poet, a.avg_sentiment, b.poet, b.avg_sentiment, "", 3);
        const sharedPlaces = sharedCount(a.all_places, b.all_places);
        const sharedImages = sharedCount(a.all_images, b.all_images);
        return [
            "诗人对比：" + a.poet + " / " + b.poet,
            "差异摘要：",
            "作品数：" + poemDiff.strong + "，" + poemDiff.detail,
            "平均字数：" + lengthDiff.strong + "，" + lengthDiff.detail,
            "情感均值：" + sentimentDiff.strong + "，" + sentimentDiff.detail,
            "共同线索：共同地名 " + sharedPlaces + " 个 / 共同意象 " + sharedImages + " 个",
            "代表诗作：" + a.poet + "《" + ((a.representative_poems || [])[0] || {}).title + "》；" + b.poet + "《" + ((b.representative_poems || [])[0] || {}).title + "》"
        ].join("\\n");
    }

    function copyComparisonSummary() {
        const summary = comparisonSummaryText();
        if (!summary) {
            setShareStatus("当前没有可复制的对比摘要。");
            return;
        }
        copyText(summary, function () {
            setShareStatus("已复制对比摘要。");
        }, function () {
            setShareStatus("复制受限，可手动选中差异摘要。");
        });
    }

    const bootState = initialState();
    fillSelect(els.poetA, bootState.a);
    fillSelect(els.poetB, bootState.b);
    els.poetA.addEventListener("change", handleSelectionChange);
    els.poetB.addEventListener("change", handleSelectionChange);
    els.swap.addEventListener("click", function () {
        const oldA = els.poetA.value;
        els.poetA.value = els.poetB.value;
        els.poetB.value = oldA;
        render();
        persistCurrentState();
    });
    els.share.addEventListener("click", copyCurrentLink);
    els.copySummary.addEventListener("click", copyComparisonSummary);
    els.clearMemory.addEventListener("click", clearMemory);
    render();
    updateStateText(bootState.source);
    syncBootState(bootState);
    </script>
</body>
</html>
"""
    html = (
        html.replace("__DATA__", data_json)
        .replace("__POET_COUNT__", f"{summary['poet_count']:,}")
        .replace("__POEM_COUNT__", f"{summary['poem_count']:,}")
        .replace("__PLACE_COUNT__", f"{summary['place_alias_count']:,}")
        .replace("__IMAGE_COUNT__", f"{summary['image_word_count']:,}")
    )
    out = OUTPUT_DIR / "10_诗人对比.html"
    html = inject_index_backlink(html)
    out.write_text(html, encoding="utf-8")
    print(f"  [ok] saved {out}  ({summary['poet_count']} 位诗人 / {summary['poem_count']} 首诗)")


if __name__ == "__main__":
    render()
