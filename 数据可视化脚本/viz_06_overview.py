"""可视化 6：核心分析概览看板。

这张图用于答辩开场或收束：把季节线索词、流派、地名、意象、
季节和情感六类分析结果放在一个 HTML 看板里，便于集中展示。
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import pymysql
from pyecharts import options as opts
from pyecharts.charts import Bar, Page, Pie

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config import DB_NAME, MYSQL, OUTPUT_DIR
from data.image_dict import IMAGE_DICT, lookup as lookup_image, words as image_words
from data.place_dict import PLACE_DICT, aliases as place_aliases, lookup as lookup_place
from data.season_rules import detect_season, season_term_counts
from viz_assets import inject_index_backlink, localize_pyecharts_assets

POEMS_JSON = ROOT / "data" / "poems.json"
VIZ_DIR = ROOT / "数据可视化脚本"
OVERVIEW_CHART_IDS = {
    "season_terms": "overview_season_terms_bar",
    "school": "overview_school_pie",
    "places": "overview_places_bar",
    "image": "overview_image_pie",
    "season": "overview_season_bar",
    "sentiment": "overview_sentiment_pie",
}


@dataclass
class OverviewData:
    source: str
    poet_count: int
    poem_count: int
    place_dict_count: int
    image_dict_count: int
    place_mention_count: int
    image_mention_count: int
    avg_sentiment: float
    avg_body_len: float
    visual_script_count: int
    season_term_counts: list[tuple[str, int]]
    school_counts: list[tuple[str, int]]
    top_places: list[tuple[str, int]]
    image_categories: list[tuple[str, int]]
    season_counts: list[tuple[str, int]]
    sentiment_buckets: list[tuple[str, int]]


def conn():
    return pymysql.connect(
        **MYSQL,
        database=DB_NAME,
        connect_timeout=5,
        read_timeout=15,
        write_timeout=15,
    )


def fetch_pairs(cur, sql: str, limit: int | None = None) -> list[tuple[str, int]]:
    cur.execute(sql, (limit,) if limit is not None else ())
    return [(str(name or "未标"), int(value or 0)) for name, value in cur.fetchall()]


def load_from_database() -> OverviewData:
    with conn() as c, c.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM t_poet WHERE poem_count > 0")
        poet_count = int(cur.fetchone()[0] or 0)
        cur.execute("SELECT COUNT(*), AVG(sentiment), AVG(body_len) FROM t_poem")
        poem_count, avg_sentiment, avg_body_len = cur.fetchone()
        cur.execute("SELECT COUNT(*) FROM t_place")
        place_dict_count = int(cur.fetchone()[0] or 0)
        cur.execute("SELECT COUNT(*) FROM t_image")
        image_dict_count = int(cur.fetchone()[0] or 0)
        cur.execute("SELECT COALESCE(SUM(freq), 0) FROM t_poem_place")
        place_mention_count = int(cur.fetchone()[0] or 0)
        cur.execute("SELECT COALESCE(SUM(freq), 0) FROM t_poem_image")
        image_mention_count = int(cur.fetchone()[0] or 0)

        cur.execute("SELECT title, body FROM t_poem")
        term_counts: Counter[tuple[str, str]] = Counter()
        for title, body in cur.fetchall():
            term_counts.update(season_term_counts(str(title or ""), str(body or "")))
        school_counts = fetch_pairs(cur, """
            SELECT COALESCE(NULLIF(pt.school, ''), '未分'), COUNT(pm.poem_id)
              FROM t_poet pt
              JOIN t_poem pm ON pm.poet_id = pt.poet_id
             GROUP BY COALESCE(NULLIF(pt.school, ''), '未分')
             ORDER BY COUNT(pm.poem_id) DESC
             LIMIT %s
        """, limit=8)
        top_places = fetch_pairs(cur, """
            SELECT CONCAT(pl.alias, '(', pl.modern, ')'), SUM(pp.freq)
              FROM t_place pl
              JOIN t_poem_place pp ON pp.place_id = pl.place_id
             GROUP BY pl.place_id
             ORDER BY SUM(pp.freq) DESC
             LIMIT %s
        """, limit=12)
        image_categories = fetch_pairs(cur, """
            SELECT im.category, SUM(pi.freq)
              FROM t_image im
              JOIN t_poem_image pi ON pi.image_id = im.image_id
             GROUP BY im.category
             ORDER BY SUM(pi.freq) DESC
        """)
        season_counts = fetch_pairs(cur, """
            SELECT COALESCE(NULLIF(season, ''), '未标'), COUNT(*)
              FROM t_poem
             GROUP BY COALESCE(NULLIF(season, ''), '未标')
             ORDER BY COUNT(*) DESC
        """)
        sentiment_buckets = fetch_pairs(cur, """
            SELECT CASE
                     WHEN sentiment <= -0.05 THEN '偏负'
                     WHEN sentiment >=  0.05 THEN '偏正'
                     ELSE '中性'
                   END AS bucket,
                   COUNT(*)
              FROM t_poem
             GROUP BY bucket
             ORDER BY FIELD(bucket, '偏负', '中性', '偏正')
        """)

    return OverviewData(
        source="MySQL 实时入库数据",
        poet_count=poet_count,
        poem_count=int(poem_count or 0),
        place_dict_count=place_dict_count,
        image_dict_count=image_dict_count,
        place_mention_count=place_mention_count,
        image_mention_count=image_mention_count,
        avg_sentiment=float(avg_sentiment or 0),
        avg_body_len=float(avg_body_len or 0),
        visual_script_count=count_visual_scripts(),
        season_term_counts=format_season_term_counts(term_counts),
        school_counts=school_counts,
        top_places=top_places,
        image_categories=image_categories,
        season_counts=season_counts,
        sentiment_buckets=sentiment_buckets,
    )


def greedy_counts(text: str, tokens: list[str]) -> Counter[str]:
    counts: Counter[str] = Counter()
    work = text
    for token in tokens:
        n = work.count(token)
        if n:
            counts[token] += n
            work = work.replace(token, "·" * len(token))
    return counts


def estimate_sentiment(image_counts: Counter[str]) -> float:
    total_weight = sum(image_counts.values())
    if not total_weight:
        return 0.0
    total = 0.0
    for word, freq in image_counts.items():
        meta = lookup_image(word)
        if meta:
            total += float(meta["sentiment"]) * freq
    return total / total_weight


def load_from_poems_json(reason: Exception | None = None) -> OverviewData:
    if reason is not None:
        print(f"  [warn] 数据库读取失败，改用 poems.json 离线兜底：{reason}")
    records = json.loads(POEMS_JSON.read_text(encoding="utf-8"))
    term_counts: Counter[tuple[str, str]] = Counter()
    school_counts: Counter[str] = Counter()
    place_counts: Counter[str] = Counter()
    image_category_counts: Counter[str] = Counter()
    season_counts: Counter[str] = Counter()
    sentiment_buckets: Counter[str] = Counter()
    sentiments: list[float] = []
    body_lengths: list[int] = []

    places = place_aliases()
    images = image_words()
    poets = set()
    for row in records:
        poet = row.get("poet") or row.get("author") or "未标"
        body = row.get("body") or ""
        text = f"{row.get('title') or ''}\n{body}"
        poets.add(poet)
        school_counts[row.get("school") or "未分"] += 1
        body_lengths.append(len(body))
        season_counts[detect_season(row.get("title") or "", body) or "未标"] += 1
        term_counts.update(season_term_counts(row.get("title") or "", body))

        poem_places = greedy_counts(text, places)
        place_counts.update(poem_places)
        poem_images = greedy_counts(body, images)
        for word, freq in poem_images.items():
            meta = lookup_image(word)
            if meta:
                image_category_counts[meta["category"]] += freq
        sentiment = estimate_sentiment(poem_images)
        sentiments.append(sentiment)
        if sentiment <= -0.05:
            sentiment_buckets["偏负"] += 1
        elif sentiment >= 0.05:
            sentiment_buckets["偏正"] += 1
        else:
            sentiment_buckets["中性"] += 1

    top_places = []
    for alias, count in place_counts.most_common(12):
        meta = lookup_place(alias)
        label = f"{alias}({meta['modern']})" if meta else alias
        top_places.append((label, count))

    return OverviewData(
        source="poems.json 离线兜底数据",
        poet_count=len(poets),
        poem_count=len(records),
        place_dict_count=len(PLACE_DICT),
        image_dict_count=len(IMAGE_DICT),
        place_mention_count=sum(place_counts.values()),
        image_mention_count=sum(image_category_counts.values()),
        avg_sentiment=sum(sentiments) / len(sentiments) if sentiments else 0.0,
        avg_body_len=sum(body_lengths) / len(body_lengths) if body_lengths else 0.0,
        visual_script_count=count_visual_scripts(),
        season_term_counts=format_season_term_counts(term_counts),
        school_counts=school_counts.most_common(8),
        top_places=top_places,
        image_categories=image_category_counts.most_common(),
        season_counts=season_counts.most_common(),
        sentiment_buckets=[
            ("偏负", sentiment_buckets["偏负"]),
            ("中性", sentiment_buckets["中性"]),
            ("偏正", sentiment_buckets["偏正"]),
        ],
    )


def load_overview_data() -> OverviewData:
    try:
        return load_from_database()
    except Exception as exc:
        return load_from_poems_json(exc)


def count_visual_scripts() -> int:
    return len([path for path in VIZ_DIR.glob("viz_*.py") if path.name != "viz_99_output_index.py"])


def format_season_term_counts(counts: Counter[tuple[str, str]], limit: int = 12) -> list[tuple[str, int]]:
    return [
        (f"{season}/{word}", int(value))
        for (season, word), value in counts.most_common(limit)
    ]


def no_empty(pairs: list[tuple[str, int]], label: str = "暂无数据") -> list[tuple[str, int]]:
    return pairs if pairs else [(label, 0)]


def make_season_terms_bar(data: OverviewData) -> Bar:
    pairs = no_empty(data.season_term_counts)[::-1]
    season_colors = {
        "春": "#22c55e",
        "夏": "#f97316",
        "秋": "#f59e0b",
        "冬": "#38bdf8",
    }
    return (
        Bar(init_opts=opts.InitOpts(width="760px", height="420px", chart_id=OVERVIEW_CHART_IDS["season_terms"]))
        .add_xaxis([name for name, _ in pairs])
        .add_yaxis(
            "加权命中",
            [
                {"value": value, "itemStyle": {"color": season_colors.get(name.split("/", 1)[0], "#64748b")}}
                for name, value in pairs
            ],
            label_opts=opts.LabelOpts(position="right"),
        )
        .reversal_axis()
        .set_global_opts(
            title_opts=opts.TitleOpts(
                title="季节线索词 Top12",
                subtitle="标题命中按 ×3 加权，正文命中按 ×1 计入",
                pos_left="center",
            ),
            xaxis_opts=opts.AxisOpts(name="加权命中次数"),
            yaxis_opts=opts.AxisOpts(axislabel_opts=opts.LabelOpts(font_size=10)),
            legend_opts=opts.LegendOpts(is_show=False),
            tooltip_opts=opts.TooltipOpts(trigger="axis", axis_pointer_type="shadow"),
        )
    )


def make_school_pie(data: OverviewData) -> Pie:
    pairs = no_empty(data.school_counts)
    return (
        Pie(init_opts=opts.InitOpts(width="520px", height="420px", chart_id=OVERVIEW_CHART_IDS["school"]))
        .add(
            "流派",
            pairs,
            radius=["36%", "72%"],
            label_opts=opts.LabelOpts(formatter="{b}\n{c} 首", font_size=11),
        )
        .set_colors(["#ef4444", "#0ea5e9", "#22c55e", "#f59e0b", "#8b5cf6", "#14b8a6", "#f97316", "#64748b"])
        .set_global_opts(
            title_opts=opts.TitleOpts(title="流派作品占比", pos_left="center"),
            legend_opts=opts.LegendOpts(orient="vertical", pos_left="left", pos_top="16%"),
        )
    )


def make_top_places_bar(data: OverviewData) -> Bar:
    pairs = no_empty(data.top_places)[::-1]
    return (
        Bar(init_opts=opts.InitOpts(width="760px", height="480px", chart_id=OVERVIEW_CHART_IDS["places"]))
        .add_xaxis([name for name, _ in pairs])
        .add_yaxis(
            "入诗次数",
            [value for _, value in pairs],
            label_opts=opts.LabelOpts(position="right"),
            itemstyle_opts=opts.ItemStyleOpts(color="#0f766e"),
        )
        .reversal_axis()
        .set_global_opts(
            title_opts=opts.TitleOpts(title="Top12 入诗地名", subtitle="古名(今地)", pos_left="center"),
            xaxis_opts=opts.AxisOpts(name="次数"),
            yaxis_opts=opts.AxisOpts(axislabel_opts=opts.LabelOpts(font_size=10)),
            tooltip_opts=opts.TooltipOpts(trigger="axis", axis_pointer_type="shadow"),
        )
    )


def make_image_category_pie(data: OverviewData) -> Pie:
    pairs = no_empty(data.image_categories)
    return (
        Pie(init_opts=opts.InitOpts(width="520px", height="480px", chart_id=OVERVIEW_CHART_IDS["image"]))
        .add(
            "意象类别",
            pairs,
            radius=["18%", "74%"],
            rosetype="area",
            label_opts=opts.LabelOpts(formatter="{b}\n{c}", font_size=11),
        )
        .set_colors(["#38bdf8", "#22c55e", "#84cc16", "#f59e0b", "#fb7185", "#14b8a6", "#8b5cf6", "#64748b"])
        .set_global_opts(
            title_opts=opts.TitleOpts(title="意象类别强度", pos_left="center"),
            legend_opts=opts.LegendOpts(orient="vertical", pos_left="left", pos_top="15%"),
        )
    )


def make_season_bar(data: OverviewData) -> Bar:
    order = ["春", "夏", "秋", "冬", "未标"]
    raw = dict(data.season_counts)
    pairs = [(name, raw.get(name, 0)) for name in order if name in raw]
    for name, value in data.season_counts:
        if name not in order:
            pairs.append((name, value))
    pairs = no_empty(pairs)
    colors = {"春": "#22c55e", "夏": "#f97316", "秋": "#f59e0b", "冬": "#38bdf8", "未标": "#94a3b8"}
    return (
        Bar(init_opts=opts.InitOpts(width="760px", height="380px", chart_id=OVERVIEW_CHART_IDS["season"]))
        .add_xaxis([name for name, _ in pairs])
        .add_yaxis(
            "作品数",
            [
                {"value": value, "itemStyle": {"color": colors.get(name, "#64748b")}}
                for name, value in pairs
            ],
            category_gap="45%",
            label_opts=opts.LabelOpts(position="top"),
        )
        .set_global_opts(
            title_opts=opts.TitleOpts(title="季节线索分布", pos_left="center"),
            legend_opts=opts.LegendOpts(is_show=False),
            yaxis_opts=opts.AxisOpts(name="作品数"),
            tooltip_opts=opts.TooltipOpts(trigger="axis", axis_pointer_type="shadow"),
        )
    )


def make_sentiment_pie(data: OverviewData) -> Pie:
    pairs = no_empty(data.sentiment_buckets)
    return (
        Pie(init_opts=opts.InitOpts(width="520px", height="380px", chart_id=OVERVIEW_CHART_IDS["sentiment"]))
        .add(
            "情感区间",
            pairs,
            radius=["34%", "70%"],
            label_opts=opts.LabelOpts(formatter="{b}\n{c} 首", font_size=11),
        )
        .set_colors(["#2563eb", "#94a3b8", "#dc2626"])
        .set_global_opts(
            title_opts=opts.TitleOpts(
                title="情感倾向概览",
                subtitle=f"平均值 {data.avg_sentiment:.3f}",
                pos_left="center",
            ),
            legend_opts=opts.LegendOpts(orient="vertical", pos_left="left", pos_top="18%"),
        )
    )


def format_int(value: int | float) -> str:
    return f"{int(value):,}"


def make_kpi_cards(data: OverviewData) -> str:
    items = [
        ("source", "数据来源", data.source, data.source),
        ("poet_count", "诗人数", data.poet_count, f"{format_int(data.poet_count)} 位"),
        ("poem_count", "诗作数", data.poem_count, f"{format_int(data.poem_count)} 首"),
        ("place_mention_count", "地名提及", data.place_mention_count, f"{format_int(data.place_mention_count)} 次"),
        ("image_mention_count", "意象提及", data.image_mention_count, f"{format_int(data.image_mention_count)} 次"),
        ("avg_sentiment", "平均情感", f"{data.avg_sentiment:.6f}", f"{data.avg_sentiment:.3f}"),
        ("avg_body_len", "平均篇幅", f"{data.avg_body_len:.6f}", f"{data.avg_body_len:.1f} 字"),
        ("visual_script_count", "可视化脚本", data.visual_script_count, f"{format_int(data.visual_script_count)} 个"),
    ]
    return "\n".join(
        (
            f'<div class="overview-kpi" data-kpi-key="{key}" data-kpi-value="{raw_value}">'
            f'<span>{label}</span><strong>{display_value}</strong></div>'
        )
        for key, label, raw_value, display_value in items
    )


def make_season_method_panel(data: OverviewData) -> str:
    season_counts = dict(data.season_counts)
    season_stat_items = [
        ("当前春季", "春", "#22c55e"),
        ("当前夏季", "夏", "#f97316"),
        ("当前秋季", "秋", "#f59e0b"),
        ("当前冬季", "冬", "#38bdf8"),
        ("无明确线索", "未标", "#64748b"),
    ]
    season_stat_html = "\n".join(
        (
            f'<div class="season-method-stat" data-season="{season}" '
            f'data-value="{int(season_counts.get(season, 0))}" style="--season-accent:{color};">'
            f"<span>{label}</span><strong>{season} {format_int(int(season_counts.get(season, 0)))}</strong></div>"
        )
        for label, season, color in season_stat_items
    )
    return f"""
        <section class="season-method-panel" aria-label="季节判定口径">
            <div class="season-method-copy">
                <span class="season-method-kicker">季节判定口径</span>
                <h2>扩充春夏秋冬物候词，修正夏冬偏少</h2>
                <p>
                    标题和正文共同参与评分：标题权重 ×3，正文权重 ×1；显式季节字和强季节短语权重更高，
                    重叠词按长词优先，避免“梅花”和“梅”重复计数。左侧季节线索词 Top12 展示实际命中的高频词。
                    每首诗仍只输出一个主季节；
                    没有明确线索归为未标，不是严格文学考据。
                </p>
            </div>
            <div class="season-method-stats" aria-label="当前样本季节数量">
                <span class="season-method-stats-title">当前样本</span>
                {season_stat_html}
            </div>
            <ul class="season-method-examples" aria-label="季节识别样例">
                <li><b>《夏日南亭怀辛大》</b><span>标题“夏日”加权，归为夏。</span></li>
                <li><b>《问刘十九》</b><span>正文“晚来天欲雪”，雪意象归为冬。</span></li>
                <li><b>《卖炭翁》</b><span>冰雪、天寒等线索叠加，归为冬。</span></li>
                <li><b>《晚晴》</b><span>“春去夏犹清”按总分和最后线索决策，不再固定春优先。</span></li>
            </ul>
        </section>
    """


def polish_page(out: Path, data: OverviewData) -> None:
    html = out.read_text(encoding="utf-8")
    viewport = '<meta name="viewport" content="width=device-width, initial-scale=1.0">'
    if viewport not in html:
        html = html.replace('<meta charset="UTF-8">', f'<meta charset="UTF-8">\n    {viewport}', 1)

    old_style = '<style>.box { justify-content:center; display:flex; flex-wrap:wrap;  } </style>'
    style = """<style>
    :root {
        --ink: #0f172a;
        --muted: #64748b;
        --line: #dbe3ef;
        --panel: #ffffff;
        --bg: #edf2f7;
        --navy: #111827;
    }
    * { box-sizing: border-box; }
    body {
        margin: 0;
        background: var(--bg);
        color: var(--ink);
        font-family: "Microsoft YaHei", "PingFang SC", Arial, sans-serif;
    }
    .overview-hero {
        background: #f8fafc;
        border-bottom: 1px solid var(--line);
        padding: 34px max(24px, calc((100vw - 1320px) / 2)) 26px;
    }
    .overview-title {
        margin: 0;
        font-size: 34px;
        line-height: 1.22;
        letter-spacing: 0;
    }
    .overview-subtitle {
        max-width: 980px;
        margin: 10px 0 0;
        color: var(--muted);
        font-size: 15px;
        line-height: 1.8;
    }
    .overview-kpis {
        display: grid;
        grid-template-columns: repeat(4, minmax(150px, 1fr));
        gap: 12px;
        margin-top: 20px;
        max-width: 1120px;
    }
    .season-method-panel {
        display: grid;
        grid-template-columns: minmax(280px, 1.1fr) minmax(300px, 0.9fr) minmax(320px, 1fr);
        gap: 18px;
        align-items: stretch;
        max-width: 1180px;
        margin-top: 18px;
        padding: 18px;
        border: 1px solid var(--line);
        border-radius: 8px;
        background: #fff;
        box-shadow: 0 8px 20px rgba(15, 23, 42, 0.06);
    }
    .season-method-kicker {
        display: inline-block;
        color: #0f766e;
        font-size: 13px;
        font-weight: 700;
        line-height: 1.4;
    }
    .season-method-copy h2 {
        margin: 6px 0 8px;
        color: var(--ink);
        font-size: 20px;
        line-height: 1.3;
        letter-spacing: 0;
    }
    .season-method-copy p {
        margin: 0;
        color: var(--muted);
        font-size: 14px;
        line-height: 1.8;
    }
    .season-method-stats {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 10px;
    }
    .season-method-stats-title {
        grid-column: 1 / -1;
        color: #0f766e;
        font-size: 13px;
        font-weight: 700;
        line-height: 1.3;
    }
    .season-method-stats div {
        min-height: 64px;
        padding: 11px 12px;
        border: 1px solid #e2e8f0;
        border-left: 4px solid var(--season-accent, #0ea5e9);
        border-radius: 8px;
        background: #f8fafc;
    }
    .season-method-stats span {
        display: block;
        color: var(--muted);
        font-size: 13px;
        line-height: 1.35;
    }
    .season-method-stats strong {
        display: block;
        margin-top: 6px;
        color: var(--ink);
        font-size: 20px;
        line-height: 1.2;
        letter-spacing: 0;
    }
    .season-method-examples {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 10px 14px;
        margin: 0;
        padding: 0;
        list-style: none;
    }
    .season-method-examples li {
        min-height: 62px;
        padding-left: 12px;
        border-left: 3px solid #0ea5e9;
    }
    .season-method-examples b,
    .season-method-examples span {
        display: block;
    }
    .season-method-examples b {
        color: var(--ink);
        font-size: 14px;
        line-height: 1.35;
    }
    .season-method-examples span {
        margin-top: 4px;
        color: var(--muted);
        font-size: 13px;
        line-height: 1.55;
    }
    .overview-kpi {
        min-height: 78px;
        padding: 14px 16px;
        border: 1px solid var(--line);
        border-radius: 8px;
        background: #fff;
        box-shadow: 0 8px 20px rgba(15, 23, 42, 0.06);
    }
    .overview-kpi span {
        display: block;
        color: var(--muted);
        font-size: 13px;
        line-height: 1.35;
    }
    .overview-kpi strong {
        display: block;
        margin-top: 7px;
        color: var(--ink);
        font-size: 21px;
        line-height: 1.25;
        letter-spacing: 0;
        overflow-wrap: anywhere;
    }
    .box {
        display: flex;
        justify-content: center;
        align-items: flex-start;
        flex-wrap: wrap;
        gap: 24px;
        padding: 26px 16px 42px;
    }
    .chart-container {
        max-width: calc(100vw - 32px);
        border: 1px solid var(--line);
        border-radius: 8px;
        background: #fff;
        box-shadow: 0 10px 28px rgba(15, 23, 42, 0.08);
        overflow: hidden;
    }
    @media (max-width: 720px) {
        .overview-hero { padding: 24px 14px 20px; }
        .overview-title { font-size: 26px; }
        .overview-subtitle { font-size: 14px; }
        .overview-kpis { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
        .season-method-panel { grid-template-columns: 1fr; padding: 14px; }
        .season-method-stats { grid-template-columns: repeat(2, minmax(0, 1fr)); }
        .season-method-examples { grid-template-columns: 1fr; }
        .overview-kpi { min-height: 72px; padding: 12px; }
        .overview-kpi strong { font-size: 18px; }
        .box { padding: 18px 8px 30px; gap: 16px; }
        .chart-container { width: calc(100vw - 16px) !important; max-width: calc(100vw - 16px); }
    }
    </style>"""
    if old_style in html:
        html = html.replace(old_style, style, 1)
    else:
        html = html.replace("</head>", f"{style}\n</head>", 1)

    hero = f"""
    <section class="overview-hero">
        <h1 class="overview-title">诗行万里 · 分析可视化</h1>
        <p class="overview-subtitle">
            围绕唐宋诗作的季节线索词、流派占比、地名热点、意象类别、
            季节线索和情感倾向集中展示核心分析结果。
        </p>
        <div class="overview-kpis">
            {make_kpi_cards(data)}
        </div>
        {make_season_method_panel(data)}
    </section>
    """
    html = html.replace("<body >", f"<body >\n{hero}", 1)
    resize_script = """
    <script>
    window.addEventListener("load", function () {
        function resizeCharts() {
            Object.keys(window).forEach(function (key) {
                if (key.indexOf("chart_") === 0 && window[key] && window[key].resize) {
                    window[key].resize();
                }
            });
        }
        resizeCharts();
        window.addEventListener("resize", resizeCharts);
    });
    </script>
    """
    html = html.replace("</body>", f"{resize_script}\n</body>", 1)
    html = inject_index_backlink(html)
    out.write_text(html, encoding="utf-8")


def render() -> None:
    data = load_overview_data()
    page = Page(layout=Page.SimplePageLayout, page_title="诗行万里分析可视化")
    page.add(
        make_season_terms_bar(data),
        make_school_pie(data),
        make_top_places_bar(data),
        make_image_category_pie(data),
        make_season_bar(data),
        make_sentiment_pie(data),
    )
    out = OUTPUT_DIR / "06_总览看板.html"
    page.render(str(out))
    localize_pyecharts_assets(out, OUTPUT_DIR)
    polish_page(out, data)
    print(
        f"  [ok] saved {out}  "
        f"({data.poet_count} 位诗人 / {data.poem_count} 首诗 / "
        f"{data.visual_script_count} 个可视化脚本)"
    )


if __name__ == "__main__":
    render()
