"""可视化 9：离线词典浏览器。"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config import OUTPUT_DIR
from data.image_dict import IMAGE_DICT, words as image_words
from data.place_dict import PLACE_DICT, aliases as place_aliases
from viz_assets import inject_index_backlink


POEMS_JSON = ROOT / "data" / "poems.json"
MAX_EXAMPLES = 5


@dataclass(frozen=True)
class Example:
    poet: str
    title: str
    freq: int
    snippet: str

    def to_json(self) -> dict[str, object]:
        return {"poet": self.poet, "title": self.title, "freq": self.freq, "snippet": self.snippet}


def greedy_counts(text: str, tokens: list[str]) -> Counter[str]:
    counts: Counter[str] = Counter()
    work = text or ""
    for token in tokens:
        count = work.count(token)
        if count:
            counts[token] += count
            work = work.replace(token, "·" * len(token))
    return counts


def context_snippet(text: str, word: str, limit: int = 72) -> str:
    """生成包含命中词的短片段，便于解释词条为什么命中。"""
    clean = " ".join((text or "").split())
    if not clean:
        return ""
    index = clean.find(word)
    if index < 0:
        return clean[:limit]

    radius = max(8, (limit - len(word)) // 2)
    start = max(0, index - radius)
    end = min(len(clean), index + len(word) + radius)
    snippet = clean[start:end]
    if start > 0:
        snippet = "…" + snippet
    if end < len(clean):
        snippet += "…"
    return snippet[:limit]


def load_poems() -> list[dict[str, str]]:
    records = json.loads(POEMS_JSON.read_text(encoding="utf-8"))
    poems: list[dict[str, str]] = []
    for row in records:
        poems.append(
            {
                "poet": str(row.get("poet") or row.get("author") or ""),
                "title": str(row.get("title") or ""),
                "body": str(row.get("body") or ""),
            }
        )
    return poems


def mention_stats(tokens: list[str], poems: list[dict[str, str]], include_title: bool) -> tuple[Counter[str], dict[str, list[Example]], Counter[str]]:
    mention_counts: Counter[str] = Counter()
    poem_counts: Counter[str] = Counter()
    examples: dict[str, list[Example]] = defaultdict(list)
    for poem in poems:
        text = f"{poem['title']}\n{poem['body']}" if include_title else poem["body"]
        counts = greedy_counts(text, tokens)
        for word, freq in counts.items():
            mention_counts[word] += freq
            poem_counts[word] += 1
            examples[word].append(
                Example(
                    poet=poem["poet"],
                    title=poem["title"],
                    freq=freq,
                    snippet=context_snippet(text, word),
                )
            )
    for word, rows in examples.items():
        rows.sort(key=lambda item: (-item.freq, item.poet, item.title))
        examples[word] = rows[:MAX_EXAMPLES]
    return mention_counts, examples, poem_counts


def build_payload() -> dict[str, object]:
    poems = load_poems()
    place_mentions, place_examples, place_poem_counts = mention_stats(place_aliases(), poems, include_title=True)
    image_mentions, image_examples, image_poem_counts = mention_stats(image_words(), poems, include_title=False)

    places = []
    for alias, modern, province, lon, lat, note in PLACE_DICT:
        places.append(
            {
                "type": "place",
                "word": alias,
                "modern": modern,
                "province": province,
                "lon": lon,
                "lat": lat,
                "note": note,
                "mention_count": int(place_mentions[alias]),
                "poem_count": int(place_poem_counts[alias]),
                "examples": [item.to_json() for item in place_examples.get(alias, [])],
            }
        )

    images = []
    for word, category, sentiment in IMAGE_DICT:
        images.append(
            {
                "type": "image",
                "word": word,
                "category": category,
                "sentiment": sentiment,
                "mention_count": int(image_mentions[word]),
                "poem_count": int(image_poem_counts[word]),
                "examples": [item.to_json() for item in image_examples.get(word, [])],
            }
        )

    places.sort(key=lambda item: (-int(item["mention_count"]), item["word"]))
    images.sort(key=lambda item: (-int(item["mention_count"]), item["word"]))
    return {
        "places": places,
        "images": images,
        "summary": {
            "place_count": len(places),
            "image_count": len(images),
            "poem_count": len(poems),
            "place_mentions": int(sum(place_mentions.values())),
            "image_mentions": int(sum(image_mentions.values())),
        },
    }


def render() -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    payload = build_payload()
    data_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    summary = payload["summary"]

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>诗行万里 · 词典浏览</title>
    <style>
    :root {{
        --bg: #f4f7fb;
        --panel: #ffffff;
        --ink: #102033;
        --muted: #627083;
        --line: #d9e2ee;
        --accent: #0f766e;
        --soft: #def7ef;
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
    h1 {{
        margin: 0;
        font-size: 30px;
        line-height: 1.2;
        letter-spacing: 0;
    }}
    .subtitle {{
        margin: 9px 0 0;
        max-width: 820px;
        color: var(--muted);
        font-size: 14px;
        line-height: 1.75;
    }}
    .metrics {{
        display: grid;
        grid-template-columns: repeat(4, minmax(120px, 1fr));
        gap: 10px;
        margin: 18px 0 16px;
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
        grid-template-columns: minmax(240px, 1fr) 180px auto;
        gap: 10px;
        align-items: end;
        padding: 14px;
        margin-bottom: 16px;
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
    select {{ padding: 0 10px; width: 100%; }}
    button {{
        padding: 0 14px;
        background: var(--ink);
        color: #fff;
        font-weight: 700;
        cursor: pointer;
    }}
    .state-tools {{
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
        padding: 12px 14px;
        margin-bottom: 16px;
    }}
    .state-text {{
        min-width: 0;
    }}
    .filter-status {{
        margin: 0;
        color: #334155;
        font-size: 13px;
        line-height: 1.6;
    }}
    .state-text small {{
        display: block;
        margin-top: 3px;
        color: var(--muted);
        font-size: 12px;
        line-height: 1.5;
    }}
    .state-actions {{
        display: flex;
        flex: 0 0 auto;
        gap: 8px;
    }}
    .state-actions button {{
        background: #f8fafc;
        color: #0f172a;
    }}
    .layout {{
        display: grid;
        grid-template-columns: minmax(320px, 0.92fr) minmax(0, 1.08fr);
        gap: 16px;
        align-items: start;
    }}
    .panel {{ overflow: hidden; }}
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
        max-height: 650px;
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
        background: var(--soft);
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
    .detail {{
        min-height: 650px;
        padding: 20px 22px 24px;
    }}
    .detail h2 {{
        margin: 0;
        font-size: 26px;
        line-height: 1.25;
        letter-spacing: 0;
    }}
    .detail-grid {{
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 10px;
        margin-top: 16px;
    }}
    .field {{
        min-height: 62px;
        padding: 11px 12px;
        border: 1px solid var(--line);
        border-radius: 7px;
        background: #f8fafc;
    }}
    .field span {{
        display: block;
        color: var(--muted);
        font-size: 12px;
    }}
    .field strong {{
        display: block;
        margin-top: 6px;
        font-size: 16px;
        line-height: 1.3;
        overflow-wrap: anywhere;
    }}
    .examples {{
        margin-top: 18px;
    }}
    .examples h3 {{
        margin: 0 0 10px;
        font-size: 17px;
    }}
    .example-list {{
        display: grid;
        gap: 8px;
    }}
    .example {{
        padding: 10px 12px;
        border: 1px solid var(--line);
        border-radius: 7px;
        background: #fff;
        color: #334155;
        font-size: 14px;
        line-height: 1.5;
    }}
    .example-snippet {{
        margin-top: 6px;
        color: #475569;
        font-size: 13px;
        line-height: 1.6;
    }}
    .example-snippet span {{
        margin-right: 6px;
        color: var(--muted);
        font-weight: 700;
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
        h1 {{ font-size: 25px; }}
        .metrics {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
        .filters {{ grid-template-columns: 1fr 1fr; }}
        .filters label:first-child {{ grid-column: 1 / -1; }}
        .state-tools {{ align-items: stretch; flex-direction: column; }}
        .state-actions {{ flex-wrap: wrap; }}
        .layout {{ grid-template-columns: 1fr; }}
        .detail {{ min-height: auto; }}
    }}
    @media (max-width: 560px) {{
        .metrics, .filters, .detail-grid {{ grid-template-columns: 1fr; }}
        .detail h2 {{ font-size: 22px; }}
    }}
    </style>
</head>
<body>
    <main class="shell">
        <h1>诗行万里 · 词典浏览</h1>
        <p class="subtitle">检索古今地名映射和意象词典，查看现代地名、经纬度、类别、情感值、命中次数和诗作示例。</p>

        <section class="metrics" aria-label="词典概览">
            <div class="metric"><span>古今地名</span><strong>{summary['place_count']:,} 条</strong></div>
            <div class="metric"><span>意象词典</span><strong>{summary['image_count']:,} 条</strong></div>
            <div class="metric"><span>地名命中</span><strong>{summary['place_mentions']:,} 次</strong></div>
            <div class="metric"><span>意象命中</span><strong>{summary['image_mentions']:,} 次</strong></div>
        </section>

        <section class="panel filters" aria-label="筛选">
            <label>关键词
                <input id="queryInput" type="search" placeholder="古名、现代地名、类别、示例诗题" autocomplete="off">
            </label>
            <label>类型
                <select id="typeFilter">
                    <option value="">全部</option>
                    <option value="place">古今地名</option>
                    <option value="image">意象词典</option>
                </select>
            </label>
            <button id="resetButton" type="button">重置</button>
        </section>

        <section class="panel state-tools" aria-label="筛选状态">
            <div class="state-text">
                <p id="filterStatus" class="filter-status" aria-live="polite">筛选状态：当前未使用筛选链接或本地记忆</p>
                <small>本地状态保存为 dictionaryBrowserState，可用筛选链接复现当前词条。</small>
            </div>
            <div class="state-actions">
                <button id="shareLinkButton" type="button">复制当前筛选链接</button>
                <button id="clearMemoryButton" type="button">清除记忆</button>
            </div>
        </section>

        <section class="layout">
            <aside class="panel">
                <div class="panel-head">
                    <h2>词条列表</h2>
                    <span id="resultCount">0 条</span>
                </div>
                <div id="resultList" class="result-list"></div>
            </aside>
            <article class="panel">
                <div class="panel-head">
                    <h2>词条详情</h2>
                    <span>命中与示例</span>
                </div>
                <div id="detailPanel" class="detail" aria-live="polite"></div>
            </article>
        </section>
    </main>

    <script>
    window.DICTIONARY_BROWSER_DATA = {data_json};

    const data = window.DICTIONARY_BROWSER_DATA;
    const entries = data.places.concat(data.images);
    const STORAGE_KEY = "dictionaryBrowserState";
    const state = {{
        query: "",
        type: "",
        activeKey: entries[0] ? entries[0].type + ":" + entries[0].word : null,
    }};
    const els = {{
        query: document.getElementById("queryInput"),
        type: document.getElementById("typeFilter"),
        reset: document.getElementById("resetButton"),
        list: document.getElementById("resultList"),
        count: document.getElementById("resultCount"),
        detail: document.getElementById("detailPanel"),
        share: document.getElementById("shareLinkButton"),
        clearMemory: document.getElementById("clearMemoryButton"),
        status: document.getElementById("filterStatus"),
    }};

    function escapeHtml(value) {{
        return String(value ?? "").replace(/[&<>"']/g, function (char) {{
            return ({{ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }})[char];
        }});
    }}

    function normalized(value) {{
        return String(value || "").trim().toLowerCase();
    }}

    function entryKey(entry) {{
        return entry.type + ":" + entry.word;
    }}

    function findEntryByKey(key) {{
        return entries.find(function (entry) {{ return entryKey(entry) === key; }}) || null;
    }}

    function sanitizeType(value) {{
        return value === "place" || value === "image" ? value : "";
    }}

    function setStatus(message) {{
        if (els.status) {{
            els.status.textContent = message || "筛选状态：当前未使用筛选链接或本地记忆";
        }}
    }}

    function statePayload() {{
        return {{
            q: state.query || "",
            type: sanitizeType(state.type),
            id: state.activeKey || "",
        }};
    }}

    function paramsFromPayload(payload) {{
        const params = new URLSearchParams();
        if (payload.q) params.set("q", payload.q);
        if (payload.type) params.set("type", payload.type);
        if (payload.id) params.set("id", payload.id);
        return params;
    }}

    function shareUrl(payload) {{
        const params = paramsFromPayload(payload || statePayload());
        try {{
            const url = new URL(window.location.href);
            url.search = params.toString();
            return url.href;
        }} catch (error) {{
            const search = params.toString();
            return "09_词典浏览.html" + (search ? "?" + search : "");
        }}
    }}

    function syncUrl(payload) {{
        if (!window.history || !window.location) return;
        const params = paramsFromPayload(payload);
        const search = params.toString();
        const nextUrl = window.location.pathname + (search ? "?" + search : "") + (window.location.hash || "");
        window.history.replaceState(null, "", nextUrl);
    }}

    function saveMemory(payload) {{
        try {{
            window.localStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
        }} catch (error) {{
            // localStorage 在少数浏览器隐私模式下可能不可用，页面仍保持可用。
        }}
    }}

    function clearMemory() {{
        try {{
            window.localStorage.removeItem(STORAGE_KEY);
        }} catch (error) {{
            // 清除失败不影响当前筛选。
        }}
    }}

    function persistState(message) {{
        const payload = statePayload();
        syncUrl(payload);
        saveMemory(payload);
        setStatus(message || "筛选状态：已保存到筛选链接和本地记忆");
    }}

    function urlInitialState() {{
        try {{
            const params = new URLSearchParams(window.location.search || "");
            const hasState = params.has("q") || params.has("type") || params.has("id");
            if (!hasState) return null;
            return {{
                q: params.get("q") || "",
                type: sanitizeType(params.get("type") || ""),
                id: params.get("id") || "",
            }};
        }} catch (error) {{
            return null;
        }}
    }}

    function memoryInitialState() {{
        try {{
            const raw = window.localStorage.getItem(STORAGE_KEY);
            if (!raw) return null;
            const parsed = JSON.parse(raw);
            if (!parsed || typeof parsed !== "object") return null;
            return {{
                q: String(parsed.q || ""),
                type: sanitizeType(parsed.type || ""),
                id: String(parsed.id || ""),
            }};
        }} catch (error) {{
            return null;
        }}
    }}

    function applyInitialState(payload) {{
        if (!payload) return;
        state.query = payload.q || "";
        state.type = sanitizeType(payload.type);
        state.activeKey = findEntryByKey(payload.id) ? payload.id : state.activeKey;
        els.query.value = state.query;
        els.type.value = state.type;
    }}

    function typeLabel(type) {{
        return type === "place" ? "古今地名" : "意象词典";
    }}

    function searchable(entry) {{
        const examples = (entry.examples || []).map(function (item) {{ return item.poet + item.title; }}).join(" ");
        if (entry.type === "place") {{
            return [entry.word, entry.modern, entry.province, entry.note, examples].join(" ");
        }}
        return [entry.word, entry.category, entry.sentiment, examples].join(" ");
    }}

    function highlight(text) {{
        const raw = String(text || "");
        const query = state.query.trim();
        if (!query) return escapeHtml(raw);
        const index = raw.toLowerCase().indexOf(query.toLowerCase());
        if (index < 0) return escapeHtml(raw);
        return escapeHtml(raw.slice(0, index)) + "<mark>" + escapeHtml(raw.slice(index, index + query.length)) + "</mark>" + escapeHtml(raw.slice(index + query.length));
    }}

    function highlightTerm(text, term) {{
        const raw = String(text || "");
        const word = String(term || "");
        if (!word) return escapeHtml(raw);
        const index = raw.toLowerCase().indexOf(word.toLowerCase());
        if (index < 0) return escapeHtml(raw);
        return escapeHtml(raw.slice(0, index)) + "<mark>" + escapeHtml(raw.slice(index, index + word.length)) + "</mark>" + escapeHtml(raw.slice(index + word.length));
    }}

    function matches(entry) {{
        if (state.type && entry.type !== state.type) return false;
        const query = normalized(state.query);
        if (!query) return true;
        return normalized(searchable(entry)).includes(query);
    }}

    function filteredEntries() {{
        return entries.filter(matches);
    }}

    function renderList(results) {{
        els.count.textContent = results.length + " 条";
        if (!results.length) {{
            els.list.innerHTML = '<div class="empty">暂无匹配词条</div>';
            state.activeKey = null;
            renderDetail(null);
            return;
        }}
        if (!results.some(function (entry) {{ return entryKey(entry) === state.activeKey; }})) {{
            state.activeKey = entryKey(results[0]);
        }}
        els.list.innerHTML = results.slice(0, 180).map(function (entry) {{
            const active = entryKey(entry) === state.activeKey ? " is-active" : "";
            const meta = entry.type === "place"
                ? escapeHtml(entry.modern) + " · " + escapeHtml(entry.province)
                : escapeHtml(entry.category) + " · 情感 " + escapeHtml(entry.sentiment);
            return '<button class="result-item' + active + '" type="button" data-key="' + escapeHtml(entryKey(entry)) + '">' +
                '<div class="result-title"><span>' + highlight(entry.word) + '</span><span>' + typeLabel(entry.type) + '</span></div>' +
                '<div class="result-meta">' + meta + ' · 命中次数 ' + escapeHtml(entry.mention_count) + ' · 诗作 ' + escapeHtml(entry.poem_count) + '</div>' +
            '</button>';
        }}).join("") + (results.length > 180 ? '<div class="empty">已显示前 180 条</div>' : "");
        Array.from(els.list.querySelectorAll(".result-item")).forEach(function (button) {{
            button.addEventListener("click", function () {{
                state.activeKey = button.dataset.key;
                render({{ persist: true }});
            }});
        }});
        renderDetail(entries.find(function (entry) {{ return entryKey(entry) === state.activeKey; }}) || results[0]);
    }}

    function field(label, value) {{
        return '<div class="field"><span>' + escapeHtml(label) + '</span><strong>' + escapeHtml(value || "未填") + '</strong></div>';
    }}

    function renderExamples(entry) {{
        const examples = entry.examples || [];
        if (!examples.length) return '<div class="empty">暂无诗作示例</div>';
        return '<div class="example-list">' + examples.map(function (item) {{
            const snippet = item.snippet
                ? '<div class="example-snippet"><span>命中片段</span>' + highlightTerm(item.snippet, entry.word) + '</div>'
                : '';
            return '<div class="example">' + escapeHtml(item.poet) + '《' + escapeHtml(item.title) + '》 ×' + escapeHtml(item.freq) + snippet + '</div>';
        }}).join("") + '</div>';
    }}

    function renderDetail(entry) {{
        if (!entry) {{
            els.detail.innerHTML = '<div class="empty">暂无词条</div>';
            return;
        }}
        const fields = entry.type === "place"
            ? [
                field("现代地名", entry.modern),
                field("省份", entry.province),
                field("经度", entry.lon),
                field("纬度", entry.lat),
                field("备注", entry.note || "未填"),
                field("命中次数", entry.mention_count + " 次"),
                field("命中诗作", entry.poem_count + " 首"),
              ]
            : [
                field("类别", entry.category),
                field("情感", entry.sentiment),
                field("命中次数", entry.mention_count + " 次"),
                field("命中诗作", entry.poem_count + " 首"),
              ];
        els.detail.innerHTML =
            '<h2>' + highlight(entry.word) + '</h2>' +
            '<div class="detail-grid">' + fields.join("") + '</div>' +
            '<div class="examples"><h3>诗作示例</h3>' + renderExamples(entry) + '</div>';
    }}

    function render(options) {{
        renderList(filteredEntries());
        options = options || {{}};
        if (options.persist) {{
            persistState(options.status);
        }} else if (options.status) {{
            setStatus(options.status);
        }}
    }}

    els.query.addEventListener("input", function () {{
        state.query = els.query.value;
        render({{ persist: true }});
    }});
    els.type.addEventListener("change", function () {{
        state.type = els.type.value;
        render({{ persist: true }});
    }});
    els.reset.addEventListener("click", function () {{
        state.query = "";
        state.type = "";
        els.query.value = "";
        els.type.value = "";
        state.activeKey = entries[0] ? entryKey(entries[0]) : null;
        clearMemory();
        syncUrl({{ q: "", type: "", id: "" }});
        render({{ status: "筛选状态：已重置，筛选链接和本地记忆已清空" }});
    }});
    els.share.addEventListener("click", function () {{
        const url = shareUrl();
        if (window.navigator && window.navigator.clipboard && window.navigator.clipboard.writeText) {{
            window.navigator.clipboard.writeText(url).catch(function () {{}});
        }}
        setStatus("筛选状态：筛选链接已复制");
    }});
    els.clearMemory.addEventListener("click", function () {{
        clearMemory();
        setStatus("筛选状态：已清除本地记忆");
    }});

    const fromUrl = urlInitialState();
    const fromMemory = fromUrl ? null : memoryInitialState();
    if (fromUrl) {{
        applyInitialState(fromUrl);
        render({{ persist: true, status: "筛选状态：已从链接参数恢复，并保存到本地记忆" }});
    }} else if (fromMemory) {{
        applyInitialState(fromMemory);
        render({{ persist: true, status: "筛选状态：已从本地记忆恢复，并同步到筛选链接" }});
    }} else {{
        render();
    }}
    </script>
</body>
</html>
"""
    out = OUTPUT_DIR / "09_词典浏览.html"
    html = inject_index_backlink(html)
    out.write_text(html, encoding="utf-8")
    print(
        f"  [ok] saved {out}  "
        f"({summary['place_count']} 条地名 / {summary['image_count']} 条意象)"
    )


if __name__ == "__main__":
    render()
