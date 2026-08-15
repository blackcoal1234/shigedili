"""可视化 11：离线流派画像页。"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config import OUTPUT_DIR
from data.image_dict import IMAGE_DICT, lookup as lookup_image, words as image_words
from data.place_dict import PLACE_DICT, aliases as place_aliases
from data.season_rules import detect_season
from viz_assets import inject_index_backlink


POEMS_JSON = ROOT / "data" / "poems.json"
MAX_TOP_ITEMS = 12
MAX_REPRESENTATIVE_POEMS = 8
MAX_POEM_CLUES = 4


def greedy_counts(text: str, tokens: list[str]) -> Counter[str]:
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
                "school": str(row.get("school") or "未分") or "未分",
                "body": str(row.get("body") or ""),
            }
        )
    return poems


def place_rows(counter: Counter[str]) -> list[dict[str, object]]:
    meta = {alias: (modern, province) for alias, modern, province, *_ in PLACE_DICT}
    rows = []
    for word, count in counter.most_common(MAX_TOP_ITEMS):
        modern, province = meta.get(word, ("", ""))
        rows.append({"word": word, "count": int(count), "modern": modern, "province": province})
    return rows


def image_rows(counter: Counter[str]) -> list[dict[str, object]]:
    meta = {word: (category, sentiment) for word, category, sentiment in IMAGE_DICT}
    rows = []
    for word, count in counter.most_common(MAX_TOP_ITEMS):
        category, sentiment = meta.get(word, ("", 0))
        rows.append({"word": word, "count": int(count), "category": category, "sentiment": sentiment})
    return rows


def clue_words(counter: Counter[str]) -> list[dict[str, object]]:
    return [
        {"word": word, "count": int(count)}
        for word, count in counter.most_common(MAX_POEM_CLUES)
    ]


def build_payload() -> dict[str, object]:
    poems = load_poems()
    place_tokens = place_aliases()
    image_tokens = image_words()
    grouped: dict[str, dict[str, object]] = {}

    for poem in poems:
        school = poem["school"] or "未分"
        title = poem["title"]
        body = poem["body"]
        poet = poem["poet"]
        place_counts = greedy_counts(f"{title}\n{body}", place_tokens)
        image_counts = greedy_counts(body, image_tokens)
        sentiment = estimate_sentiment(image_counts)
        season = detect_season(title, body) or "未标"
        group = grouped.setdefault(
            school,
            {
                "school": school,
                "poem_count": 0,
                "poets": set(),
                "total_chars": 0,
                "sentiment_total": 0.0,
                "season_counts": Counter(),
                "dynasty_counts": Counter(),
                "poet_counts": Counter(),
                "place_counts": Counter(),
                "image_counts": Counter(),
                "representative_poems": [],
            },
        )
        group["poem_count"] = int(group["poem_count"]) + 1
        group["poets"].add(poet)
        group["total_chars"] = int(group["total_chars"]) + len(body)
        group["sentiment_total"] = float(group["sentiment_total"]) + sentiment
        group["season_counts"][season] += 1
        group["dynasty_counts"][poem["dynasty"] or "未标"] += 1
        group["poet_counts"][poet] += 1
        group["place_counts"].update(place_counts)
        group["image_counts"].update(image_counts)
        representatives = group["representative_poems"]
        if isinstance(representatives, list) and len(representatives) < MAX_REPRESENTATIVE_POEMS:
            representatives.append(
                {
                    "title": title,
                    "poet": poet,
                    "dynasty": poem["dynasty"],
                    "season": season,
                    "sentiment": round(sentiment, 3),
                    "body_len": len(body),
                    "excerpt": body.replace("\n", " ")[:96],
                    "places": clue_words(place_counts),
                    "images": clue_words(image_counts),
                }
            )

    profiles: dict[str, dict[str, object]] = {}
    for school, group in grouped.items():
        poem_count = int(group["poem_count"])
        top_poets = [
            {"poet": poet, "count": int(count)}
            for poet, count in group["poet_counts"].most_common(10)
        ]
        profiles[school] = {
            "school": school,
            "poet_count": len(group["poets"]),
            "poem_count": poem_count,
            "total_chars": int(group["total_chars"]),
            "avg_body_len": round(int(group["total_chars"]) / poem_count, 1) if poem_count else 0,
            "avg_sentiment": round(float(group["sentiment_total"]) / poem_count, 3) if poem_count else 0,
            "season_counts": {key: int(value) for key, value in group["season_counts"].items()},
            "dynasty_counts": {key: int(value) for key, value in group["dynasty_counts"].items()},
            "top_poets": top_poets,
            "top_places": place_rows(group["place_counts"]),
            "top_images": image_rows(group["image_counts"]),
            "representative_poems": group["representative_poems"],
        }

    schools = sorted(profiles, key=lambda name: (-int(profiles[name]["poem_count"]), name))
    return {
        "schools": schools,
        "profiles": profiles,
        "defaults": {"school": schools[0] if schools else ""},
        "summary": {
            "school_count": len(schools),
            "poet_count": len({poem["poet"] for poem in poems if poem["poet"]}),
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
    <title>诗行万里 · 流派画像</title>
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
        max-width: 860px;
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
        grid-template-columns: minmax(180px, 1fr) minmax(180px, 1fr);
        gap: 10px;
        padding: 14px;
        margin-bottom: 16px;
    }
    label {
        display: grid;
        gap: 6px;
        color: var(--muted);
        font-size: 13px;
    }
    select {
        width: 100%;
        min-height: 38px;
        padding: 0 10px;
        border: 1px solid #cbd7e6;
        border-radius: 6px;
        background: #fff;
        color: var(--ink);
        font: inherit;
        font-size: 14px;
    }
    button {
        min-height: 38px;
        border: 1px solid #cbd7e6;
        border-radius: 6px;
        background: #f8fafc;
        color: #0f172a;
        font: inherit;
        font-size: 14px;
        font-weight: 700;
        cursor: pointer;
    }
    .state-tools {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
        padding: 12px 14px;
        margin-bottom: 16px;
    }
    .state-text {
        min-width: 0;
    }
    .profile-status {
        margin: 0;
        color: #334155;
        font-size: 13px;
        line-height: 1.6;
    }
    .state-text small {
        display: block;
        margin-top: 3px;
        color: var(--muted);
        font-size: 12px;
        line-height: 1.5;
    }
    .state-actions {
        display: flex;
        flex: 0 0 auto;
        gap: 8px;
    }
    .layout {
        display: grid;
        grid-template-columns: minmax(300px, 0.78fr) minmax(0, 1.22fr);
        gap: 16px;
        align-items: start;
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
    .school-list {
        display: grid;
        gap: 8px;
        max-height: 720px;
        overflow: auto;
        padding: 12px;
    }
    .school-item {
        width: 100%;
        border: 1px solid var(--line);
        border-radius: 7px;
        background: #fff;
        color: var(--ink);
        cursor: pointer;
        padding: 10px 11px;
        text-align: left;
        font: inherit;
    }
    .school-item.is-active {
        border-color: #2dd4bf;
        background: var(--accent-soft);
    }
    .school-title {
        display: flex;
        justify-content: space-between;
        gap: 8px;
        font-weight: 700;
    }
    .school-meta {
        margin-top: 5px;
        color: var(--muted);
        font-size: 13px;
    }
    .stat-grid {
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
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
    .two-cols {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 14px;
    }
    .bars {
        display: grid;
        gap: 7px;
    }
    .bar-row {
        display: grid;
        grid-template-columns: 54px minmax(0, 1fr) 42px;
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
    .poem-clues {
        margin-top: 8px;
        color: var(--muted);
        font-size: 12px;
        line-height: 1.55;
    }
    .clue-row {
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        gap: 5px;
        margin-top: 5px;
    }
    .clue-row span:first-child {
        font-weight: 700;
        color: #475569;
    }
    .clue {
        display: inline-flex;
        align-items: center;
        gap: 4px;
        min-height: 24px;
        padding: 2px 7px;
        border: 1px solid #d8e1ec;
        border-radius: 999px;
        background: #fff;
        color: #334155;
    }
    .clue b { color: var(--warn); }
    .empty {
        color: var(--muted);
        font-size: 13px;
        line-height: 1.65;
    }
    @media (max-width: 900px) {
        .shell { width: min(100vw - 20px, 1240px); padding-top: 18px; }
        h1 { font-size: 25px; }
        .metrics,
        .filters,
        .layout,
        .stat-grid,
        .two-cols { grid-template-columns: 1fr; }
        .state-tools { align-items: stretch; flex-direction: column; }
        .state-actions { flex-wrap: wrap; }
        .school-list { max-height: none; }
    }
    </style>
</head>
<body>
    <main class="shell">
        <header>
            <h1>诗行万里 · 流派画像</h1>
            <p class="subtitle">把 `poems.json` 中的流派字段做成可浏览画像：每个流派展示作品规模、诗人构成、朝代来源、季节结构、情感均值、高频地名、高频意象和代表诗作，补充词云之外的结构化比较。</p>
        </header>

        <section class="metrics" aria-label="数据规模">
            <div class="metric"><span>流派</span><strong>__SCHOOL_COUNT__ 类</strong></div>
            <div class="metric"><span>诗人</span><strong>__POET_COUNT__ 位</strong></div>
            <div class="metric"><span>诗作</span><strong>__POEM_COUNT__ 首</strong></div>
            <div class="metric"><span>词典</span><strong>__DICT_COUNT__ 条</strong></div>
        </section>

        <section class="panel filters" aria-label="筛选控制">
            <label>选择流派
                <select id="schoolSelect"></select>
            </label>
            <label>排序方式
                <select id="sortSelect">
                    <option value="poem">作品数</option>
                    <option value="poet">诗人数</option>
                    <option value="sentiment">情感均值</option>
                    <option value="school">流派名称</option>
                </select>
            </label>
        </section>

        <section class="panel state-tools" aria-label="画像状态">
            <div class="state-text">
                <p id="profileStatus" class="profile-status" aria-live="polite">画像状态：当前未使用画像链接或本地记忆</p>
                <small>本地状态保存为 schoolProfileState，可用画像链接复现当前流派与排序。</small>
            </div>
            <div class="state-actions">
                <button id="shareProfileButton" type="button">复制当前画像链接</button>
                <button id="clearProfileMemoryButton" type="button">清除记忆</button>
            </div>
        </section>

        <section class="layout">
            <aside class="panel">
                <div class="panel-head"><h2>流派列表</h2><span id="schoolCountLabel"></span></div>
                <div id="schoolList" class="school-list"></div>
            </aside>
            <section class="panel">
                <div class="panel-head"><h2>画像详情</h2><span id="profileTitle"></span></div>
                <div id="profilePanel" class="panel-body"></div>
            </section>
        </section>
    </main>

    <script>
    window.SCHOOL_PROFILE_DATA = __DATA__;
    const data = window.SCHOOL_PROFILE_DATA;
    const STORAGE_KEY = "schoolProfileState";
    const state = {
        school: data.defaults.school,
        sort: "poem"
    };
    const els = {
        school: document.getElementById("schoolSelect"),
        sort: document.getElementById("sortSelect"),
        list: document.getElementById("schoolList"),
        count: document.getElementById("schoolCountLabel"),
        title: document.getElementById("profileTitle"),
        panel: document.getElementById("profilePanel"),
        share: document.getElementById("shareProfileButton"),
        clearMemory: document.getElementById("clearProfileMemoryButton"),
        status: document.getElementById("profileStatus")
    };

    function escapeHtml(value) {
        return String(value == null ? "" : value).replace(/[&<>"']/g, function (ch) {
            return {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[ch];
        });
    }

    function normalizeSort(value) {
        const legacy = {
            "poem_count": "poem",
            "poet_count": "poet",
            "avg_sentiment": "sentiment"
        };
        value = legacy[value] || value;
        return ["poem", "poet", "sentiment", "school"].indexOf(value) >= 0 ? value : "poem";
    }

    function normalizeSchool(value) {
        return data.profiles[value] ? value : data.defaults.school;
    }

    function setStatus(message) {
        if (els.status) {
            els.status.textContent = message || "画像状态：当前未使用画像链接或本地记忆";
        }
    }

    function statePayload() {
        return {
            school: normalizeSchool(state.school),
            sort: normalizeSort(state.sort)
        };
    }

    function paramsFromPayload(payload) {
        const params = new URLSearchParams();
        if (payload.school) params.set("school", payload.school);
        if (payload.sort) params.set("sort", payload.sort);
        return params;
    }

    function shareUrl(payload) {
        const params = paramsFromPayload(payload || statePayload());
        try {
            const url = new URL(window.location.href);
            url.search = params.toString();
            return url.href;
        } catch (error) {
            const search = params.toString();
            return "11_流派画像.html" + (search ? "?" + search : "");
        }
    }

    function syncUrl(payload) {
        if (!window.history || !window.location) return;
        const params = paramsFromPayload(payload);
        const search = params.toString();
        const nextUrl = window.location.pathname + (search ? "?" + search : "") + (window.location.hash || "");
        window.history.replaceState(null, "", nextUrl);
    }

    function saveMemory(payload) {
        try {
            window.localStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
        } catch (error) {
            // localStorage 可能在隐私模式下不可用，页面交互仍保持可用。
        }
    }

    function clearMemory() {
        try {
            window.localStorage.removeItem(STORAGE_KEY);
        } catch (error) {
            // 清除失败不影响当前画像。
        }
    }

    function persistState(message) {
        const payload = statePayload();
        syncUrl(payload);
        saveMemory(payload);
        setStatus(message || "画像状态：已保存到画像链接和本地记忆");
    }

    function urlInitialState() {
        try {
            const params = new URLSearchParams(window.location.search || "");
            const hasState = params.has("school") || params.has("sort");
            if (!hasState) return null;
            return {
                school: normalizeSchool(params.get("school") || ""),
                sort: normalizeSort(params.get("sort") || "")
            };
        } catch (error) {
            return null;
        }
    }

    function memoryInitialState() {
        try {
            const raw = window.localStorage.getItem(STORAGE_KEY);
            if (!raw) return null;
            const parsed = JSON.parse(raw);
            if (!parsed || typeof parsed !== "object") return null;
            return {
                school: normalizeSchool(parsed.school || ""),
                sort: normalizeSort(parsed.sort || "")
            };
        } catch (error) {
            return null;
        }
    }

    function applyInitialState(payload) {
        if (!payload) return;
        state.school = normalizeSchool(payload.school);
        state.sort = normalizeSort(payload.sort);
        els.school.value = state.school;
        els.sort.value = state.sort;
    }

    function sortedSchools() {
        const rows = data.schools.slice();
        rows.sort(function (left, right) {
            const a = data.profiles[left];
            const b = data.profiles[right];
            if (state.sort === "school") return left.localeCompare(right, "zh-Hans-CN");
            if (state.sort === "sentiment") return Number(b.avg_sentiment || 0) - Number(a.avg_sentiment || 0) || left.localeCompare(right, "zh-Hans-CN");
            const field = state.sort === "poet" ? "poet_count" : "poem_count";
            return Number(b[field] || 0) - Number(a[field] || 0) || left.localeCompare(right, "zh-Hans-CN");
        });
        return rows;
    }

    function fillSelect() {
        els.school.innerHTML = data.schools.map(function (school) {
            return '<option value="' + escapeHtml(school) + '">' + escapeHtml(school) + '</option>';
        }).join("");
        els.school.value = state.school;
        els.sort.value = state.sort;
    }

    function fmt(value, digits) {
        const number = Number(value || 0);
        return Number.isInteger(number) ? String(number) : number.toFixed(digits || 2);
    }

    function stat(label, value) {
        return '<div class="mini-stat"><span>' + escapeHtml(label) + '</span><strong>' + escapeHtml(value) + '</strong></div>';
    }

    function bars(counts, order) {
        const keys = order || Object.keys(counts || {}).sort(function (a, b) {
            return Number(counts[b] || 0) - Number(counts[a] || 0) || a.localeCompare(b, "zh-Hans-CN");
        });
        const maxValue = Math.max.apply(null, keys.map(function (key) { return Number(counts[key] || 0); }).concat([1]));
        return '<div class="bars">' + keys.map(function (key) {
            const value = Number(counts[key] || 0);
            const width = Math.max(2, Math.round(value / maxValue * 100));
            return '<div class="bar-row"><span>' + escapeHtml(key) + '</span><div class="bar-track"><div class="bar-fill" style="width:' + width + '%"></div></div><span>' + escapeHtml(value) + '</span></div>';
        }).join("") + '</div>';
    }

    function pillList(items, kind) {
        if (!items || !items.length) return '<div class="empty">暂无命中。</div>';
        return '<div class="pill-list">' + items.map(function (item) {
            const sub = kind === "place"
                ? [item.modern, item.province].filter(Boolean).join(" · ")
                : [item.category, item.sentiment ? "情感 " + item.sentiment : ""].filter(Boolean).join(" · ");
            return '<span class="pill"><span>' + escapeHtml(item.word || item.poet) + '</span><b>' + escapeHtml(item.count) + '</b>' + (sub ? '<small>' + escapeHtml(sub) + '</small>' : '') + '</span>';
        }).join("") + '</div>';
    }

    function poemList(profile) {
        const poems = profile.representative_poems || [];
        if (!poems.length) return '<div class="empty">暂无代表诗作。</div>';
        return '<div class="poems">' + poems.map(function (poem) {
            const placeClues = clueList("地名线索", poem.places || []);
            const imageClues = clueList("意象线索", poem.images || []);
            return '<article class="poem"><strong>' + escapeHtml(poem.poet) + '《' + escapeHtml(poem.title) + '》</strong><p>' +
                escapeHtml([poem.dynasty, poem.season || "未标"].filter(Boolean).join(" · ")) +
                ' · 情感 ' + escapeHtml(poem.sentiment) + ' · ' + escapeHtml(poem.body_len) + ' 字</p><p>' +
                escapeHtml(poem.excerpt || "") + '</p><div class="poem-clues"><strong>命中线索</strong>' +
                placeClues + imageClues + '</div></article>';
        }).join("") + '</div>';
    }

    function clueList(label, items) {
        if (!items || !items.length) {
            return '<div class="clue-row"><span>' + escapeHtml(label) + '</span><em>暂无</em></div>';
        }
        return '<div class="clue-row"><span>' + escapeHtml(label) + '</span>' + items.map(function (item) {
            return '<i class="clue">' + escapeHtml(item.word) + '<b>' + escapeHtml(item.count) + '</b></i>';
        }).join("") + '</div>';
    }

    function renderList() {
        const rows = sortedSchools();
        els.count.textContent = rows.length + " 类";
        els.list.innerHTML = rows.map(function (school) {
            const profile = data.profiles[school];
            const active = school === state.school ? " is-active" : "";
            return '<button class="school-item' + active + '" type="button" data-school="' + escapeHtml(school) + '">' +
                '<div class="school-title"><span>' + escapeHtml(school) + '</span><span>' + escapeHtml(profile.poem_count) + ' 首</span></div>' +
                '<div class="school-meta">' + escapeHtml(profile.poet_count) + ' 位诗人 · 情感 ' + escapeHtml(profile.avg_sentiment) + '</div>' +
            '</button>';
        }).join("");
        Array.from(els.list.querySelectorAll("[data-school]")).forEach(function (button) {
            button.addEventListener("click", function () {
                state.school = button.getAttribute("data-school");
                els.school.value = state.school;
                render({persist: true});
            });
        });
    }

    function renderProfile() {
        const profile = data.profiles[state.school];
        if (!profile) {
            els.panel.innerHTML = '<div class="empty">请选择流派。</div>';
            return;
        }
        els.title.textContent = profile.school;
        els.panel.innerHTML =
            '<div class="stat-grid">' +
                stat("作品数", profile.poem_count + " 首") +
                stat("诗人数", profile.poet_count + " 位") +
                stat("平均字数", fmt(profile.avg_body_len, 1)) +
                stat("情感均值", fmt(profile.avg_sentiment, 3)) +
            '</div>' +
            '<h3 class="section-title">主要诗人</h3>' + pillList(profile.top_poets, "poet") +
            '<div class="two-cols">' +
                '<div><h3 class="section-title">季节结构</h3>' + bars(profile.season_counts, ["春", "夏", "秋", "冬", "未标"]) + '</div>' +
                '<div><h3 class="section-title">朝代来源</h3>' + bars(profile.dynasty_counts) + '</div>' +
            '</div>' +
            '<h3 class="section-title">高频地名</h3>' + pillList(profile.top_places, "place") +
            '<h3 class="section-title">高频意象</h3>' + pillList(profile.top_images, "image") +
            '<h3 class="section-title">代表诗作</h3>' + poemList(profile);
    }

    function render(options) {
        renderList();
        renderProfile();
        options = options || {};
        if (options.persist) {
            persistState(options.status);
        } else if (options.status) {
            setStatus(options.status);
        }
    }

    fillSelect();
    els.school.addEventListener("change", function () {
        state.school = els.school.value;
        render({persist: true});
    });
    els.sort.addEventListener("change", function () {
        state.sort = normalizeSort(els.sort.value);
        els.sort.value = state.sort;
        render({persist: true});
    });
    els.share.addEventListener("click", function () {
        const url = shareUrl();
        if (window.navigator && window.navigator.clipboard && window.navigator.clipboard.writeText) {
            window.navigator.clipboard.writeText(url).catch(function () {});
        }
        setStatus("画像状态：画像链接已复制");
    });
    els.clearMemory.addEventListener("click", function () {
        clearMemory();
        setStatus("画像状态：已清除本地记忆");
    });

    const fromUrl = urlInitialState();
    const fromMemory = fromUrl ? null : memoryInitialState();
    if (fromUrl) {
        applyInitialState(fromUrl);
        render({persist: true, status: "画像状态：已从链接参数恢复，并保存到本地记忆"});
    } else if (fromMemory) {
        applyInitialState(fromMemory);
        render({persist: true, status: "画像状态：已从本地记忆恢复，并同步到画像链接"});
    } else {
        render();
    }
    </script>
</body>
</html>
"""
    html = (
        html.replace("__DATA__", data_json)
        .replace("__SCHOOL_COUNT__", f"{summary['school_count']:,}")
        .replace("__POET_COUNT__", f"{summary['poet_count']:,}")
        .replace("__POEM_COUNT__", f"{summary['poem_count']:,}")
        .replace("__DICT_COUNT__", f"{summary['place_alias_count'] + summary['image_word_count']:,}")
    )
    out = OUTPUT_DIR / "11_流派画像.html"
    html = inject_index_backlink(html)
    out.write_text(html, encoding="utf-8")
    print(f"  [ok] saved {out}  ({summary['school_count']} 类流派 / {summary['poem_count']} 首诗)")


if __name__ == "__main__":
    render()
