"""可视化 15：诗人行旅事实、生平处境与文本情感。

数据来自人工审核的 poet_journeys.json。地图折线仅按节点年代连接，
不表示历史人物的真实道路或完整行程。
"""
from __future__ import annotations

import base64
import json
import re
import sys
from collections import Counter
from html import escape
from pathlib import Path
from urllib.parse import urlparse

from pyecharts import options as opts
from pyecharts.charts import Bar, Geo, Page, Scatter
from pyecharts.commons.utils import JsCode
from pyecharts.globals import ChartType, CurrentConfig, ThemeType

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config import OUTPUT_DIR
from viz_assets import (
    PYECHARTS_ASSET_HOST,
    localize_pyecharts_assets,
    premium_hero_html,
    write_premium_chart_page,
)


JOURNEY_JSON = ROOT / "data" / "reviewed" / "poet_journeys.json"
POEMS_JSON = ROOT / "data" / "poems.json"
OUT_HTML = OUTPUT_DIR / "15_诗人行旅与生命情感.html"
TARGET_POETS = ("李白", "杜甫", "白居易", "苏轼", "陆游", "李清照")
POET_COLORS = {
    "李白": "#38bdf8",
    "杜甫": "#fbbf24",
    "白居易": "#34d399",
    "苏轼": "#fb7185",
    "陆游": "#c4b5fd",
    "李清照": "#f472b6",
}
PAGE_TITLE = "诗人行旅与生命情感"
PAGE_SUBTITLE = (
    "以李白、杜甫、白居易、苏轼、陆游、李清照的已审核生平节点为纵轴，"
    "将可核验行旅事实、C 级生平处境归纳和关联作品的文本情感分层展示。"
)
PAGE_NOTE = (
    "重要口径：地图连线只表示人工选定节点的时间先后，不代表诗人实际行走的道路；"
    "处境指数是项目人工编码，只用于同一诗人的阶段比较；文本情感也不等于诗人真实性格。"
)


def load_payload() -> tuple[dict[str, object], dict[tuple[str, str], dict[str, str]]]:
    """读取审核节点与本地诗词，并阻止与语料库脱节的作品关联。"""
    payload = json.loads(JOURNEY_JSON.read_text(encoding="utf-8"))
    poem_rows = json.loads(POEMS_JSON.read_text(encoding="utf-8"))
    poems = {
        (
            str(row.get("poet") or row.get("author") or ""),
            str(row.get("title") or ""),
        ): {
            "body": str(row.get("body") or ""),
            "dynasty": str(row.get("dynasty") or ""),
        }
        for row in poem_rows
    }

    loaded_poets = tuple(str(group.get("poet") or "") for group in payload.get("poets", []))
    if set(loaded_poets) != set(TARGET_POETS):
        raise ValueError(f"行旅数据的诗人集合不符合预期：{loaded_poets}")

    for group in payload.get("poets", []):
        poet = str(group["poet"])
        for node in group.get("nodes", []):
            title = str(node["linked_poem"]["title"])
            poem = poems.get((poet, title))
            if poem is None:
                raise ValueError(f"关联作品不存在于 poems.json：{poet}《{title}》")
            evidence = str(node["linked_poem"]["text_emotion"]["evidence"])
            if evidence not in poem["body"]:
                raise ValueError(f"情感证据不在诗文中：{poet}《{title}》 -> {evidence}")

    return payload, poems


def flatten_nodes(payload: dict[str, object]) -> list[dict[str, object]]:
    """展平节点，保留所属诗人与朝代。"""
    rows: list[dict[str, object]] = []
    for group in payload.get("poets", []):
        poet = str(group["poet"])
        dynasty = str(group["dynasty"])
        for raw_node in sorted(group.get("nodes", []), key=lambda row: int(row["route_order"])):
            node = dict(raw_node)
            node["poet"] = poet
            node["dynasty"] = dynasty
            rows.append(node)
    return rows


def _js_base64_json(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=True, separators=(",", ":"))
    return base64.b64encode(payload.encode("ascii")).decode("ascii")


def build_node_meta(nodes: list[dict[str, object]]) -> dict[str, dict[str, object]]:
    meta: dict[str, dict[str, object]] = {}
    for node in nodes:
        life = node["life_context"]
        linked = node["linked_poem"]
        emotion = linked["text_emotion"]
        meta[str(node["id"])] = {
            "poet": node["poet"],
            "year": node["year_label"],
            "historical_place": node["place_historical"],
            "modern_place": node["place_modern"],
            "event": node["event"],
            "life_label": life["label"],
            "pressure": round(float(life["external_pressure"]) * 100),
            "poem": linked["title"],
            "emotion": emotion["label"],
            "valence": round(float(emotion["valence"]), 2),
            "intensity": round(float(emotion["intensity"]) * 100),
            "evidence": emotion["evidence"],
            "source_level": node["source_level"],
            "source_name": node["source_name"],
            "confidence": round(float(node["confidence"]) * 100),
            "relation_level": linked["relation_level"],
            "relation": linked["relation"],
        }
    return meta


def map_tooltip_formatter(meta: dict[str, dict[str, object]]) -> JsCode:
    return JsCode(
        """
        function (p) {
            var meta = JSON.parse(atob('__META__'));
            var d = meta[p.name];
            function esc(value) {
                return String(value == null ? '' : value).replace(/[&<>\"']/g, function (ch) {
                    var code = ch.charCodeAt(0);
                    if (code === 38) { return '&amp;'; }
                    if (code === 60) { return '&lt;'; }
                    if (code === 62) { return '&gt;'; }
                    if (code === 34) { return '&quot;'; }
                    if (code === 39) { return '&#39;'; }
                    return ch;
                });
            }
            if (!d) {
                return '<strong>时间顺序连线</strong><br/>'
                    + '<span style="color:#fbbf24;">仅表示人工选定节点的年代先后，不代表真实道路。</span>';
            }
            return '<strong>' + esc(d.poet) + ' · ' + esc(d.year) + '</strong>'
                + '<br/><b>行旅事实</b>：' + esc(d.historical_place) + '（' + esc(d.modern_place) + '）'
                + '<br/>' + esc(d.event)
                + '<br/><b>生平处境</b>：' + esc(d.life_label) + '（处境指数 ' + esc(d.pressure) + '）'
                + '<br/><b>文本情感</b>：《' + esc(d.poem) + '》 ' + esc(d.emotion)
                + '（倾向 ' + esc(d.valence) + '，强度 ' + esc(d.intensity) + '%）'
                + '<br/><span style="color:#cbd5e1;">证据：' + esc(d.evidence) + '</span>'
                + '<br/>节点来源：' + esc(d.source_level) + ' 级 · ' + esc(d.source_name)
                + '<br/>作品关联：' + esc(d.relation_level) + ' 级 · ' + esc(d.relation)
                + '<br/>节点置信度：' + esc(d.confidence) + '%';
        }
        """.replace("__META__", _js_base64_json(meta))
    )


def build_geo(nodes: list[dict[str, object]]) -> Geo:
    node_meta = build_node_meta(nodes)
    geo = Geo(
        init_opts=opts.InitOpts(
            width="1240px",
            height="760px",
            theme=ThemeType.DARK,
            bg_color="rgba(0,0,0,0)",
            chart_id="journey_fact_geo",
        )
    )
    geo.add_schema(
        maptype="china",
        zoom=1.18,
        center=[108.5, 31.5],
        label_opts=opts.LabelOpts(is_show=False),
        itemstyle_opts=opts.ItemStyleOpts(
            color="#132238",
            border_color="#64748b",
            border_width=0.8,
            area_color="#132238",
        ),
        emphasis_itemstyle_opts=opts.ItemStyleOpts(area_color="#243b53"),
    )

    for node in nodes:
        geo.add_coordinate(
            str(node["id"]),
            float(node["longitude"]),
            float(node["latitude"]),
        )

    tooltip = map_tooltip_formatter(node_meta)
    for poet in TARGET_POETS:
        poet_nodes = [node for node in nodes if node["poet"] == poet]
        color = POET_COLORS[poet]
        geo.add(
            f"{poet}·生平节点",
            [(str(node["id"]), round(float(node["confidence"]) * 100)) for node in poet_nodes],
            type_=ChartType.EFFECT_SCATTER,
            color=color,
            symbol_size=JsCode("function(v){return 9 + Math.max(0, (v || 60) - 60) / 7;}"),
            effect_opts=opts.EffectOpts(scale=2.3, period=4, brush_type="stroke"),
            label_opts=opts.LabelOpts(is_show=False),
            tooltip_opts=opts.TooltipOpts(formatter=tooltip, is_confine=True),
        )
        line_pairs = [
            (str(left["id"]), str(right["id"]))
            for left, right in zip(poet_nodes, poet_nodes[1:])
        ]
        geo.add(
            f"{poet}·时间顺序连线",
            line_pairs,
            type_=ChartType.LINES,
            color=color,
            effect_opts=opts.EffectOpts(is_show=False),
            linestyle_opts=opts.LineStyleOpts(
                curve=0.16,
                opacity=0.58,
                width=1.8,
                type_="dashed",
            ),
            tooltip_opts=opts.TooltipOpts(formatter=tooltip, is_confine=True),
        )

    geo.set_global_opts(
        title_opts=opts.TitleOpts(
            title="已审核生平节点地图",
            subtitle="点为可审计节点；虚线只表示年代先后，不是真实道路",
            pos_left="center",
            pos_top="18px",
            title_textstyle_opts=opts.TextStyleOpts(color="#f8fafc", font_size=24),
            subtitle_textstyle_opts=opts.TextStyleOpts(color="#fbbf24", font_size=13),
        ),
        legend_opts=opts.LegendOpts(
            type_="scroll",
            pos_left="center",
            pos_top="76px",
            textstyle_opts=opts.TextStyleOpts(color="#cbd5e1"),
        ),
        tooltip_opts=opts.TooltipOpts(
            formatter=tooltip,
            is_confine=True,
            background_color="rgba(2,6,23,.96)",
            border_color="#475569",
            textstyle_opts=opts.TextStyleOpts(color="#e2e8f0", font_size=13),
        ),
    )
    return geo


def emotion_tooltip_formatter() -> JsCode:
    return JsCode(
        """
        function (p) {
            var v = p.value || [];
            function esc(value) {
                return String(value == null ? '' : value).replace(/[&<>\"']/g, function (ch) {
                    var code = ch.charCodeAt(0);
                    if (code === 38) { return '&amp;'; }
                    if (code === 60) { return '&lt;'; }
                    if (code === 62) { return '&gt;'; }
                    if (code === 34) { return '&quot;'; }
                    if (code === 39) { return '&#39;'; }
                    return ch;
                });
            }
            return '<strong>' + esc(p.seriesName) + ' · ' + esc(v[0]) + '</strong>'
                + '<br/>文本情感倾向：' + esc(v[1])
                + '<br/>情感标签：' + esc(v[3])
                + '<br/>情感强度：' + esc(v[4]) + '%'
                + '<br/>生平处境指数：' + esc(v[5])
                + '<br/>节点置信度：' + esc(v[6]) + '%'
                + '<br/>关联作品：《' + esc(v[7]) + '》'
                + '<br/><span style="color:#fbbf24;">处境指数是项目人工编码，不等于诗歌必然负面。</span>';
        }
        """
    )


def build_emotion_scatter(nodes: list[dict[str, object]]) -> Scatter:
    scatter = Scatter(
        init_opts=opts.InitOpts(
            width="1240px",
            height="600px",
            theme=ThemeType.DARK,
            bg_color="rgba(0,0,0,0)",
            chart_id="text_emotion_scatter",
        )
    )
    scatter.add_xaxis([])
    for poet in TARGET_POETS:
        data = []
        for node in nodes:
            if node["poet"] != poet:
                continue
            emotion = node["linked_poem"]["text_emotion"]
            data.append(
                [
                    int(node["year"]),
                    float(emotion["valence"]),
                    str(node["id"]),
                    str(emotion["label"]),
                    round(float(emotion["intensity"]) * 100),
                    round(float(node["life_context"]["external_pressure"]) * 100),
                    round(float(node["confidence"]) * 100),
                    str(node["linked_poem"]["title"]),
                ]
            )
        scatter.add_yaxis(
            poet,
            data,
            color=POET_COLORS[poet],
            symbol_size=JsCode("function(d){return 10 + (d[4] || 0) / 12;}"),
            label_opts=opts.LabelOpts(is_show=False),
            tooltip_opts=opts.TooltipOpts(formatter=emotion_tooltip_formatter(), is_confine=True),
        )

    scatter.set_global_opts(
        title_opts=opts.TitleOpts(
            title="关联作品的文本情感时序",
            subtitle="纵轴是诗词文本倾向，不是对诗人人格或心理健康的评分",
            pos_left="center",
            pos_top="18px",
            title_textstyle_opts=opts.TextStyleOpts(color="#f8fafc", font_size=23),
            subtitle_textstyle_opts=opts.TextStyleOpts(color="#94a3b8", font_size=13),
        ),
        legend_opts=opts.LegendOpts(
            pos_left="center",
            pos_top="76px",
            textstyle_opts=opts.TextStyleOpts(color="#cbd5e1"),
        ),
        xaxis_opts=opts.AxisOpts(
            type_="value",
            name="公元年",
            min_=720,
            max_=1220,
            split_number=10,
            name_gap=28,
            axislabel_opts=opts.LabelOpts(color="#cbd5e1"),
            axisline_opts=opts.AxisLineOpts(linestyle_opts=opts.LineStyleOpts(color="#64748b")),
            splitline_opts=opts.SplitLineOpts(
                is_show=True,
                linestyle_opts=opts.LineStyleOpts(color="#263449", opacity=0.8),
            ),
        ),
        yaxis_opts=opts.AxisOpts(
            type_="value",
            name="文本情感倾向",
            min_=-1,
            max_=1,
            interval=0.25,
            name_gap=40,
            axislabel_opts=opts.LabelOpts(color="#cbd5e1"),
            axisline_opts=opts.AxisLineOpts(linestyle_opts=opts.LineStyleOpts(color="#64748b")),
            splitline_opts=opts.SplitLineOpts(
                is_show=True,
                linestyle_opts=opts.LineStyleOpts(color="#263449", opacity=0.8),
            ),
        ),
        tooltip_opts=opts.TooltipOpts(
            formatter=emotion_tooltip_formatter(),
            is_confine=True,
            background_color="rgba(2,6,23,.96)",
            border_color="#475569",
            textstyle_opts=opts.TextStyleOpts(color="#e2e8f0", font_size=13),
        ),
        visualmap_opts=opts.VisualMapOpts(
            is_show=False,
            min_=-1,
            max_=1,
            dimension=1,
        ),
        datazoom_opts=[
            opts.DataZoomOpts(type_="inside", xaxis_index=0, range_start=0, range_end=100),
            opts.DataZoomOpts(
                type_="slider",
                xaxis_index=0,
                range_start=0,
                range_end=100,
                pos_bottom="5%",
                height=18,
            ),
        ],
    )
    return scatter


def pressure_tooltip_formatter() -> JsCode:
    return JsCode(
        """
        function (items) {
            var rows = Array.isArray(items) ? items : [items];
            if (!rows.length) { return ''; }
            var out = '<strong>' + rows[0].axisValue + '</strong>';
            rows.forEach(function (row) {
                out += '<br/><span style="color:' + row.color + ';">●</span> '
                    + row.seriesName + '：' + row.value + '%';
            });
            return out + '<br/><span style="color:#fbbf24;">两项指标不存在等号关系。</span>';
        }
        """
    )


def build_pressure_bar(nodes: list[dict[str, object]]) -> Bar:
    labels = [f"{node['poet']}·{node['year']}·{node['place_historical']}" for node in nodes]
    pressure = [round(float(node["life_context"]["external_pressure"]) * 100) for node in nodes]
    intensity = [
        round(float(node["linked_poem"]["text_emotion"]["intensity"]) * 100)
        for node in nodes
    ]
    visible_end = min(100, round(12 / max(len(labels), 1) * 100, 2))

    bar = Bar(
        init_opts=opts.InitOpts(
            width="1240px",
            height="610px",
            theme=ThemeType.DARK,
            bg_color="rgba(0,0,0,0)",
            chart_id="context_emotion_bar",
        )
    )
    bar.add_xaxis(labels)
    bar.add_yaxis(
        "生平处境指数（C 级人工编码）",
        pressure,
        color="#fbbf24",
        category_gap="38%",
        label_opts=opts.LabelOpts(is_show=False),
    )
    bar.add_yaxis(
        "作品文本情感强度（C 级标注）",
        intensity,
        color="#38bdf8",
        category_gap="38%",
        label_opts=opts.LabelOpts(is_show=False),
    )
    bar.set_global_opts(
        title_opts=opts.TitleOpts(
            title="生平处境与文本情感强度对照",
            subtitle="处境指数只用于同一诗人的阶段比较；高指数不意味作品必然悲伤",
            pos_left="center",
            pos_top="18px",
            title_textstyle_opts=opts.TextStyleOpts(color="#f8fafc", font_size=23),
            subtitle_textstyle_opts=opts.TextStyleOpts(color="#94a3b8", font_size=13),
        ),
        legend_opts=opts.LegendOpts(
            pos_left="center",
            pos_top="76px",
            textstyle_opts=opts.TextStyleOpts(color="#cbd5e1"),
        ),
        xaxis_opts=opts.AxisOpts(
            axislabel_opts=opts.LabelOpts(rotate=28, color="#cbd5e1", interval=0),
            axisline_opts=opts.AxisLineOpts(linestyle_opts=opts.LineStyleOpts(color="#64748b")),
        ),
        yaxis_opts=opts.AxisOpts(
            name="指标值（%）",
            min_=0,
            max_=100,
            interval=20,
            name_gap=34,
            axislabel_opts=opts.LabelOpts(color="#cbd5e1"),
            splitline_opts=opts.SplitLineOpts(
                is_show=True,
                linestyle_opts=opts.LineStyleOpts(color="#263449", opacity=0.8),
            ),
        ),
        tooltip_opts=opts.TooltipOpts(
            trigger="axis",
            formatter=pressure_tooltip_formatter(),
            is_confine=True,
            background_color="rgba(2,6,23,.96)",
            border_color="#475569",
            textstyle_opts=opts.TextStyleOpts(color="#e2e8f0", font_size=13),
        ),
        datazoom_opts=[
            opts.DataZoomOpts(
                type_="inside",
                xaxis_index=0,
                range_start=0,
                range_end=visible_end,
            ),
            opts.DataZoomOpts(
                type_="slider",
                xaxis_index=0,
                range_start=0,
                range_end=visible_end,
                pos_bottom="3%",
                height=18,
            ),
        ],
    )
    return bar


def _source_link(url: str, label: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return escape(label)
    return (
        f'<a href="{escape(url, quote=True)}" target="_blank" rel="noopener noreferrer">'
        f"{escape(label)}</a>"
    )


def build_audit_html(payload: dict[str, object], nodes: list[dict[str, object]]) -> str:
    grade_counts = Counter(str(node["source_level"]) for node in nodes)
    inferred_relations = sum(
        1 for node in nodes if str(node["linked_poem"]["relation_level"]) == "C"
    )
    avg_confidence = sum(float(node["confidence"]) for node in nodes) / max(len(nodes), 1)

    detail_groups = []
    for poet in TARGET_POETS:
        rows = []
        for node in nodes:
            if node["poet"] != poet:
                continue
            linked = node["linked_poem"]
            emotion = linked["text_emotion"]
            life = node["life_context"]
            rows.append(
                """
                <tr>
                    <td><strong>__YEAR__</strong><br><span>__PLACE__</span></td>
                    <td>__EVENT__</td>
                    <td><span class="journey-grade journey-grade-__NODE_GRADE__">__NODE_GRADE__</span> __SOURCE__<br><small>置信度 __CONFIDENCE__%</small></td>
                    <td>__CONTEXT__<br><small>处境指数 __PRESSURE__ · C 级人工编码</small></td>
                    <td><strong>《__POEM__》</strong><br>__EMOTION__（__VALENCE__ / __INTENSITY__%）<br><small>“__EVIDENCE__”</small></td>
                    <td><span class="journey-grade journey-grade-__REL_GRADE__">__REL_GRADE__</span> __RELATION__</td>
                </tr>
                """
                .replace("__YEAR__", escape(str(node["year_label"])))
                .replace("__PLACE__", escape(f"{node['place_historical']} / {node['place_modern']}"))
                .replace("__EVENT__", escape(str(node["event"])))
                .replace("__NODE_GRADE__", escape(str(node["source_level"])))
                .replace(
                    "__SOURCE__",
                    _source_link(str(node["source_url"]), str(node["source_name"])),
                )
                .replace("__CONFIDENCE__", str(round(float(node["confidence"]) * 100)))
                .replace("__CONTEXT__", escape(str(life["label"])))
                .replace("__PRESSURE__", str(round(float(life["external_pressure"]) * 100)))
                .replace("__POEM__", escape(str(linked["title"])))
                .replace("__EMOTION__", escape(str(emotion["label"])))
                .replace("__VALENCE__", f"{float(emotion['valence']):+.2f}")
                .replace("__INTENSITY__", str(round(float(emotion["intensity"]) * 100)))
                .replace("__EVIDENCE__", escape(str(emotion["evidence"])))
                .replace("__REL_GRADE__", escape(str(linked["relation_level"])))
                .replace("__RELATION__", escape(str(linked["relation"])))
            )
        detail_groups.append(
            f"""
            <details class="journey-audit-details">
                <summary>{escape(poet)} · {len(rows)} 个节点</summary>
                <div class="journey-table-wrap">
                    <table class="journey-audit-table">
                        <thead><tr>
                            <th>时间 / 地点</th><th>行旅事实</th><th>来源</th>
                            <th>生平处境</th><th>文本情感</th><th>作品关联</th>
                        </tr></thead>
                        <tbody>{''.join(rows)}</tbody>
                    </table>
                </div>
            </details>
            """
        )

    source_levels = payload["methodology"]["source_levels"]
    return f"""
    <section class="journey-method" aria-label="口径与数据分层">
        <div class="journey-method-head">
            <span>READING PROTOCOL</span>
            <h2>三层数据，三种不同的结论边界</h2>
            <p>{escape(str(payload['methodology']['line_semantics']))}</p>
        </div>
        <div class="journey-layer-grid">
            <section><b>01 行旅事实</b><p>{escape(str(payload['methodology']['three_layers']['journey_fact']))}</p></section>
            <section><b>02 生平处境</b><p>{escape(str(payload['methodology']['three_layers']['life_context']))}</p></section>
            <section><b>03 文本情感</b><p>{escape(str(payload['methodology']['three_layers']['text_emotion']))}</p></section>
        </div>
        <div class="journey-stat-strip" aria-label="审核数据统计">
            <span><b>{len(nodes)}</b>个节点</span>
            <span><b>{grade_counts.get('A', 0)}</b>个 A 级节点</span>
            <span><b>{grade_counts.get('B', 0)}</b>个 B 级节点</span>
            <span><b>{grade_counts.get('C', 0)}</b>个 C 级节点</span>
            <span><b>{inferred_relations}</b>条 C 级作品关联</span>
            <span><b>{avg_confidence:.0%}</b>平均节点置信度</span>
        </div>
        <div class="journey-grade-note">
            <span class="journey-grade journey-grade-A">A</span>{escape(str(source_levels['A']))}
            <span class="journey-grade journey-grade-B">B</span>{escape(str(source_levels['B']))}
            <span class="journey-grade journey-grade-C">C</span>{escape(str(source_levels['C']))}
        </div>
    </section>
    <section class="journey-audit" aria-label="节点证据账本">
        <div class="journey-method-head">
            <span>EVIDENCE LEDGER</span>
            <h2>节点证据账本</h2>
            <p>展开诗人名称可查看来源、置信度、生平处境归纳、文本证据及作品关联等级。</p>
        </div>
        {''.join(detail_groups)}
    </section>
    """


def journey_page_css() -> str:
    return """
    <style id="journey-emotion-page-style">
    .shixing-premium-hero h1,
    .shixing-premium-metric strong,
    .shixing-premium-panel-head h2 { letter-spacing: 0 !important; }
    .journey-method,
    .journey-audit {
        width: min(1240px, calc(100vw - 36px));
        margin: 8px auto 24px;
        padding: 24px 0;
        border-top: 1px solid rgba(148,163,184,.24);
        border-bottom: 1px solid rgba(148,163,184,.24);
    }
    .journey-method-head span {
        color: #67e8f9;
        font-size: 12px;
        font-weight: 900;
        letter-spacing: 0;
    }
    .journey-method-head h2 {
        margin: 8px 0 8px;
        color: #f8fafc;
        font-size: 24px;
        line-height: 1.35;
        letter-spacing: 0;
    }
    .journey-method-head p,
    .journey-layer-grid p {
        margin: 0;
        color: #9aa8bd;
        font-size: 13px;
        line-height: 1.75;
    }
    .journey-layer-grid {
        display: grid;
        grid-template-columns: repeat(3, minmax(0,1fr));
        gap: 22px;
        margin-top: 22px;
    }
    .journey-layer-grid section {
        min-width: 0;
        padding-left: 14px;
        border-left: 3px solid #38bdf8;
    }
    .journey-layer-grid section:nth-child(2) { border-left-color: #fbbf24; }
    .journey-layer-grid section:nth-child(3) { border-left-color: #c4b5fd; }
    .journey-layer-grid b { color: #e5edf9; font-size: 15px; }
    .journey-layer-grid p { margin-top: 7px; }
    .journey-stat-strip {
        display: grid;
        grid-template-columns: repeat(6, minmax(0,1fr));
        margin-top: 24px;
        border: 1px solid rgba(148,163,184,.22);
        background: rgba(15,23,42,.54);
    }
    .journey-stat-strip span {
        min-width: 0;
        padding: 13px 10px;
        border-right: 1px solid rgba(148,163,184,.18);
        color: #94a3b8;
        font-size: 12px;
        text-align: center;
        overflow-wrap: anywhere;
    }
    .journey-stat-strip span:last-child { border-right: 0; }
    .journey-stat-strip b { display: block; color: #f8fafc; font-size: 20px; }
    .journey-grade-note {
        display: flex;
        flex-wrap: wrap;
        gap: 8px 10px;
        align-items: center;
        margin-top: 14px;
        color: #94a3b8;
        font-size: 12px;
        line-height: 1.6;
    }
    .journey-grade {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 24px;
        height: 24px;
        border-radius: 4px;
        color: #07111f;
        font-weight: 900;
    }
    .journey-grade-A { background: #34d399; }
    .journey-grade-B { background: #38bdf8; }
    .journey-grade-C { background: #fbbf24; }
    .journey-audit-details {
        border-top: 1px solid rgba(148,163,184,.2);
    }
    .journey-audit-details:last-child { border-bottom: 1px solid rgba(148,163,184,.2); }
    .journey-audit-details summary {
        padding: 15px 4px;
        color: #e2e8f0;
        font-size: 15px;
        font-weight: 800;
        cursor: pointer;
    }
    .journey-table-wrap { overflow-x: auto; padding-bottom: 14px; }
    .journey-audit-table {
        width: 100%;
        min-width: 1120px;
        border-collapse: collapse;
        table-layout: fixed;
    }
    .journey-audit-table th,
    .journey-audit-table td {
        padding: 11px 10px;
        border: 1px solid rgba(148,163,184,.18);
        color: #b7c3d4;
        font-size: 12px;
        line-height: 1.6;
        vertical-align: top;
        overflow-wrap: anywhere;
    }
    .journey-audit-table th { color: #e2e8f0; background: rgba(2,6,23,.45); }
    .journey-audit-table td strong { color: #f8fafc; }
    .journey-audit-table td span,
    .journey-audit-table td small { color: #94a3b8; }
    .journey-audit-table td .journey-grade { color: #07111f; }
    .journey-audit-table a { color: #67e8f9; text-decoration: underline; text-underline-offset: 3px; }
    .box { padding-top: 12px !important; }
    @media (max-width: 960px) {
        .journey-layer-grid { grid-template-columns: 1fr; }
        .journey-stat-strip { grid-template-columns: repeat(3, minmax(0,1fr)); }
        .journey-stat-strip span:nth-child(3n) { border-right: 0; }
    }
    @media (max-width: 640px) {
        .journey-method,
        .journey-audit { width: calc(100vw - 22px); padding: 18px 0; }
        .journey-method-head h2 { font-size: 20px; }
        .journey-stat-strip { grid-template-columns: repeat(2, minmax(0,1fr)); }
        .journey-stat-strip span:nth-child(3n) { border-right: 1px solid rgba(148,163,184,.18); }
        .journey-stat-strip span:nth-child(2n) { border-right: 0; }
    }
    </style>
    """


def localize_china_asset(html_path: Path) -> None:
    """地图 JS 与 ECharts 一样使用 output/assets 中的本地文件。"""
    map_asset = OUTPUT_DIR / "assets" / "pyecharts" / "v6" / "maps" / "china.js"
    if not map_asset.exists() or map_asset.stat().st_size <= 1024:
        raise RuntimeError(f"本地中国地图资源缺失或异常：{map_asset}")

    html = html_path.read_text(encoding="utf-8")
    for remote in (
        f"{PYECHARTS_ASSET_HOST}maps/china.js",
        "https://assets.pyecharts.org/assets/v5/maps/china.js",
        "http://assets.pyecharts.org/assets/v5/maps/china.js",
    ):
        html = html.replace(remote, "assets/pyecharts/v6/maps/china.js")
    html_path.write_text(html, encoding="utf-8")


def page_metrics(nodes: list[dict[str, object]]) -> list[tuple[str, str]]:
    source_counts = Counter(str(node["source_level"]) for node in nodes)
    poem_count = len(
        {(str(node["poet"]), str(node["linked_poem"]["title"])) for node in nodes}
    )
    return [
        ("诗人样本", f"{len(TARGET_POETS)} 位"),
        ("审核节点", f"{len(nodes)} 个"),
        ("关联作品", f"{poem_count} 首"),
        (
            "A/B/C 节点",
            f"{source_counts.get('A', 0)}/{source_counts.get('B', 0)}/{source_counts.get('C', 0)}",
        ),
    ]


def polish_page(payload: dict[str, object], nodes: list[dict[str, object]]) -> None:
    html = OUT_HTML.read_text(encoding="utf-8")
    custom = journey_page_css()
    if "journey-emotion-page-style" not in html:
        html = html.replace("</head>", f"{custom}\n</head>", 1)

    # viz_assets 的公共主题方法负责样式和返回入口；若旧版辅助函数
    # 因 CSS 类名提前出现而跳过 Hero，使用同模块的 Hero 方法补齐首屏。
    if '<section class="shixing-premium-hero"' not in html:
        hero = premium_hero_html(
            title=PAGE_TITLE,
            subtitle=PAGE_SUBTITLE,
            eyebrow="Reviewed Journey · Life Context · Text Emotion",
            metrics=page_metrics(nodes),
            note=PAGE_NOTE,
        )
        html = re.sub(r"(<body\b[^>]*>)", rf"\1\n{hero}", html, count=1, flags=re.I)

    audit_html = build_audit_html(payload, nodes)
    if '<section class="journey-method"' not in html:
        html = html.replace('<div class="box">', f"{audit_html}\n<div class=\"box\">", 1)
    OUT_HTML.write_text(html, encoding="utf-8")


def render() -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    payload, _ = load_payload()
    nodes = flatten_nodes(payload)
    poem_count = len({(str(node["poet"]), str(node["linked_poem"]["title"])) for node in nodes})

    CurrentConfig.ONLINE_HOST = PYECHARTS_ASSET_HOST
    page = Page(layout=Page.SimplePageLayout, page_title="诗人行旅与生命情感")
    page.add(build_geo(nodes), build_emotion_scatter(nodes), build_pressure_bar(nodes))
    page.render(str(OUT_HTML))

    localize_pyecharts_assets(OUT_HTML, OUTPUT_DIR)
    localize_china_asset(OUT_HTML)
    write_premium_chart_page(
        OUT_HTML,
        page_key="journey-emotion",
        title=PAGE_TITLE,
        subtitle=PAGE_SUBTITLE,
        eyebrow="Reviewed Journey · Life Context · Text Emotion",
        metrics=page_metrics(nodes),
        note=PAGE_NOTE,
        accent="#38bdf8",
        accent_2="#fbbf24",
        accent_3="#c4b5fd",
        backlink_href="index.html",
    )
    polish_page(payload, nodes)

    print(
        f"  [ok] saved {OUT_HTML}  "
        f"({len(TARGET_POETS)} 位诗人 / {len(nodes)} 个节点 / {poem_count} 首关联作品 / 本地地图资源)"
    )


if __name__ == "__main__":
    render()
