"""可视化 5：诗人情感倾向排序散点图 + 朝代意象类别热力

横轴：诗人（按平均情感倾向由低到高排序）
纵轴：作品平均情感倾向（来自 t_poem.sentiment）
气泡大小：作品数
颜色：平均情感倾向

下图：朝代-意象类别热力图（按朝代分组聚合各意象类别的频次）
"""
import sys
import re
import math
from pathlib import Path

import pymysql
from pyecharts import options as opts
from pyecharts.charts import Scatter, HeatMap, Page, Grid
from pyecharts.commons.utils import JsCode

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from config import MYSQL, DB_NAME, OUTPUT_DIR
from viz_assets import inject_index_backlink, localize_pyecharts_assets

SENTIMENT_NEGATIVE_THRESHOLD = -0.05
SENTIMENT_POSITIVE_THRESHOLD = 0.05
SENTIMENT_SCATTER_CHART_ID = "sentiment_scatter"
SENTIMENT_HEATMAP_CHART_ID = "sentiment_heatmap"
MAX_DEFAULT_VISIBLE_POETS = 42


SCATTER_TOOLTIP_FORMATTER = JsCode(
    """
    function (p) {
        var v = p.value || [];
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
        return '<strong>诗人：' + esc(v[2]) + '</strong>'
            + '<br/>朝代 / 流派：' + esc(v[3]) + ' / ' + esc(v[4])
            + '<br/>排序：' + esc(v[0])
            + '<br/>作品：' + esc(v[5]) + ' 首'
            + '<br/>情感：' + esc(v[1])
            + '<br/><span style="color:#64748b;">情感值越低偏冷峻，越高偏明朗。</span>';
    }
    """
)


HEAT_TOOLTIP_FORMATTER = JsCode(
    """
    function (params) {
        var raw = params.data || params.value || [];
        var category = raw[3] || params.name || '';
        var dynasty = raw[4] || params.seriesName || '';
        var freq = raw[2] == null ? 0 : raw[2];
        return '<strong>' + dynasty + ' / ' + category + '</strong>'
            + '<br/>意象类别频次：' + freq;
    }
    """
)


def conn():
    return pymysql.connect(**MYSQL, database=DB_NAME)


def load_poet_sentiment():
    sql = """
        SELECT pt.name, pt.dynasty, pt.school, COUNT(pm.poem_id), AVG(pm.sentiment)
          FROM t_poet pt
          LEFT JOIN t_poem pm ON pm.poet_id = pt.poet_id
         WHERE pt.poem_count > 0
         GROUP BY pt.poet_id
         ORDER BY pt.dynasty, AVG(pm.sentiment)
    """
    out = []
    with conn() as c, c.cursor() as cur:
        cur.execute(sql)
        for name, dyn, school, n, avg_s in cur.fetchall():
            out.append((name, dyn, school or "未分", int(n), float(avg_s or 0)))
    return out


def load_dyn_cat_matrix():
    sql = """
        SELECT pt.dynasty, im.category, SUM(pi.freq) AS f
          FROM t_poet pt
          JOIN t_poem pm ON pm.poet_id = pt.poet_id
          JOIN t_poem_image pi ON pi.poem_id = pm.poem_id
          JOIN t_image im ON im.image_id = pi.image_id
         GROUP BY pt.dynasty, im.category
    """
    rows = []
    with conn() as c, c.cursor() as cur:
        cur.execute(sql)
        rows = cur.fetchall()
    dyns = sorted({r[0] for r in rows})
    cats = sorted({r[1] for r in rows})
    matrix = {(d, c): 0 for d in dyns for c in cats}
    for d, ca, f in rows:
        matrix[(d, ca)] = int(f or 0)
    return dyns, cats, matrix


def sentiment_bucket(value: float) -> str:
    """按总览页同一阈值，把诗人平均情感分成三档。"""
    if value <= SENTIMENT_NEGATIVE_THRESHOLD:
        return "偏负"
    if value >= SENTIMENT_POSITIVE_THRESHOLD:
        return "偏正"
    return "中性"


def build_sentiment_summary(ranked: list[tuple[int, str, str, str, int, float]]) -> dict[str, int]:
    """统计诗人平均情感摘要，口径为每位诗人的作品平均情感。"""
    summary = {"偏负": 0, "中性": 0, "偏正": 0}
    for _, _, _, _, _, sentiment in ranked:
        summary[sentiment_bucket(sentiment)] += 1
    return summary


def compact_sentiment_range(values: list[float]) -> tuple[float, float]:
    """按实际情感值生成紧凑坐标和染色范围，并保留 0 情感中线。"""
    if not values:
        return -0.1, 0.1

    lower = min(min(values), 0)
    upper = max(max(values), 0)
    span = max(upper - lower, 0.1)
    padding = max(span * 0.18, 0.03)
    return (
        max(-1.0, math.floor((lower - padding) * 100) / 100),
        min(1.0, math.ceil((upper + padding) * 100) / 100),
    )


def default_zoom_end(total: int) -> float:
    """默认只展开一部分诗人，保留滑块继续浏览，避免全量点位挤在一起。"""
    if total <= 0:
        return 100
    visible_ratio = min(100, MAX_DEFAULT_VISIBLE_POETS / total * 100)
    return round(max(25, visible_ratio), 2)


def heatmap_pieces(max_value: int) -> list[dict[str, int | str]]:
    """用分段热力映射避免最大频次把其他格子的颜色全部压淡。"""
    if max_value <= 0:
        return [{"value": 0, "label": "0"}]

    return [
        {"min": 0, "max": 0, "label": "0"},
        {"min": 1, "max": max(1, math.ceil(max_value * 0.12)), "label": "低频"},
        {
            "min": math.ceil(max_value * 0.12) + 1,
            "max": max(math.ceil(max_value * 0.12) + 1, math.ceil(max_value * 0.35)),
            "label": "中低",
        },
        {
            "min": math.ceil(max_value * 0.35) + 1,
            "max": max(math.ceil(max_value * 0.35) + 1, math.ceil(max_value * 0.65)),
            "label": "中高",
        },
        {"min": math.ceil(max_value * 0.65) + 1, "max": max_value, "label": "高频"},
    ]


def render_summary_html(summary: dict[str, int]) -> str:
    total = sum(summary.values())
    return f"""
    <section id="sentiment-summary" class="sentiment-summary" aria-label="诗人平均情感摘要">
        <div>
            <strong>诗人平均情感摘要</strong>
            <span>按每位诗人的作品平均情感分桶，阈值：≤ {SENTIMENT_NEGATIVE_THRESHOLD} 为偏负，≥ {SENTIMENT_POSITIVE_THRESHOLD} 为偏正，其余为中性。</span>
        </div>
        <ul>
            <li><span>偏负</span><strong>{summary.get("偏负", 0)}</strong></li>
            <li><span>中性</span><strong>{summary.get("中性", 0)}</strong></li>
            <li><span>偏正</span><strong>{summary.get("偏正", 0)}</strong></li>
            <li><span>诗人总数</span><strong>{total}</strong></li>
        </ul>
    </section>
"""


def render():
    poets = load_poet_sentiment()
    ranked = [
        (idx, name, dyn, school, n, s)
        for idx, (name, dyn, school, n, s) in enumerate(
            sorted(poets, key=lambda p: p[4]), 1
        )
    ]
    sentiment_summary = build_sentiment_summary(ranked)

    scatter = Scatter(init_opts=opts.InitOpts(width="1240px", height="620px"))
    scatter.add_xaxis([r[0] for r in ranked])
    data = [
        opts.ScatterItem(
            name=name,
            value=[rank, round(s, 3), name, dyn, school, n],
        )
        for rank, name, dyn, school, n, s in ranked
    ]
    sentiment_values = [s for _, _, _, _, _, s in ranked]
    sentiment_axis_min, sentiment_axis_max = compact_sentiment_range(sentiment_values)
    zoom_end = default_zoom_end(len(ranked))
    scatter.add_yaxis(
        "诗人",
        data,
        symbol_size=JsCode(
            "function(data){return Math.max(10, Math.min(34, 8 + Math.sqrt(data[5]) * 5));}"
        ),
        label_opts=opts.LabelOpts(is_show=False),
        markline_opts=opts.MarkLineOpts(
            is_silent=True,
            symbol="none",
            label_opts=opts.LabelOpts(
                is_show=True,
                formatter="情感中线",
                position="insideEndTop",
                color="#475569",
                font_size=12,
            ),
            linestyle_opts=opts.LineStyleOpts(
                color="#64748b",
                width=1.5,
                type_="dashed",
            ),
            data=[{"name": "情感中线", "yAxis": 0}],
        ),
    )
    scatter.set_global_opts(
        title_opts=opts.TitleOpts(
            title="唐宋诗人 · 平均情感倾向排序",
            subtitle="基于自建意象词典加权估算；每个点代表一位诗人，大小代表入库作品数",
            pos_left="center",
            pos_top="18px",
        ),
        xaxis_opts=opts.AxisOpts(name="诗人排序（由负向到正向）",
                                 type_="value", min_=1, max_=len(ranked),
                                 split_number=8,
                                 name_gap=28),
        yaxis_opts=opts.AxisOpts(name="情感倾向",
                                  min_=sentiment_axis_min,
                                  max_=sentiment_axis_max,
                                  name_gap=34,
                                  splitline_opts=opts.SplitLineOpts(is_show=True)),
        legend_opts=opts.LegendOpts(is_show=False),
        tooltip_opts=opts.TooltipOpts(
            formatter=SCATTER_TOOLTIP_FORMATTER,
            is_confine=True,
        ),
        visualmap_opts=opts.VisualMapOpts(
            type_="color",
            min_=sentiment_axis_min, max_=sentiment_axis_max, dimension=1,
            range_color=["#1d4ed8", "#94a3b8", "#dc2626"],
            pos_left="2%", pos_top="30%",
            precision=2,
            is_piecewise=False,
        ),
        datazoom_opts=[
            opts.DataZoomOpts(type_="inside", xaxis_index=0,
                              range_start=0, range_end=zoom_end),
            opts.DataZoomOpts(type_="slider", xaxis_index=0,
                              range_start=0, range_end=zoom_end,
                              pos_bottom="5%", height=18),
        ],
    )
    scatter_grid = Grid(
        init_opts=opts.InitOpts(
            width="1240px",
            height="620px",
            chart_id=SENTIMENT_SCATTER_CHART_ID,
        )
    )
    scatter_grid.add(
        scatter,
        grid_opts=opts.GridOpts(
            pos_left="9%", pos_right="5%", pos_top="20%", pos_bottom="18%"
        ),
    )

    # 朝代-类别热力
    dyns, cats, matrix = load_dyn_cat_matrix()
    data = []
    for i, d in enumerate(dyns):
        for j, c in enumerate(cats):
            data.append([j, i, matrix[(d, c)], c, d])
    max_v = max((v[2] for v in data), default=1)
    heat = (
        HeatMap(init_opts=opts.InitOpts(width="1240px", height="440px"))
        .add_xaxis(cats)
        .add_yaxis("",
                   dyns,
                   data,
                   label_opts=opts.LabelOpts(is_show=True,
                                             position="inside",
                                             font_size=12,
                                             color="#000"))
        .set_global_opts(
            title_opts=opts.TitleOpts(title="朝代 × 意象类别 频次热力",
                                      subtitle="颜色越深，表示该朝代诗作中对应意象类别出现越多",
                                      pos_left="center",
                                      pos_top="16px"),
            visualmap_opts=opts.VisualMapOpts(min_=0, max_=max_v,
                                              dimension=2,
                                              is_piecewise=True,
                                              pieces=heatmap_pieces(max_v),
                                              orient="horizontal",
                                              pos_left="center", pos_bottom="5%",
                                              range_color=["#dbeafe",
                                                           "#bfdbfe",
                                                           "#60a5fa",
                                                           "#2563eb",
                                                           "#1d4ed8"]),
            tooltip_opts=opts.TooltipOpts(
                formatter=HEAT_TOOLTIP_FORMATTER,
                is_confine=True,
            ),
            xaxis_opts=opts.AxisOpts(axislabel_opts=opts.LabelOpts(
                interval=0, margin=12),
                splitarea_opts=opts.SplitAreaOpts(
                is_show=True, areastyle_opts=opts.AreaStyleOpts(opacity=1))),
            yaxis_opts=opts.AxisOpts(splitarea_opts=opts.SplitAreaOpts(
                is_show=True, areastyle_opts=opts.AreaStyleOpts(opacity=1))),
        )
    )
    heat_grid = Grid(
        init_opts=opts.InitOpts(
            width="1240px",
            height="440px",
            chart_id=SENTIMENT_HEATMAP_CHART_ID,
        )
    )
    heat_grid.add(
        heat,
        grid_opts=opts.GridOpts(
            pos_left="8%", pos_right="6%", pos_top="24%", pos_bottom="24%"
        ),
    )

    page = Page(layout=Page.SimplePageLayout, page_title="情感与意象")
    page.add(scatter_grid, heat_grid)
    out = OUTPUT_DIR / "05_情感分布.html"
    page.render(str(out))
    localize_pyecharts_assets(out, OUTPUT_DIR)
    polish_page(out, sentiment_summary)
    print(f"  [ok] saved {out}  ({len(poets)} 位诗人 / {len(dyns)} 朝代 x {len(cats)} 类别)")


def polish_page(out: Path, sentiment_summary: dict[str, int]) -> None:
    """补一层页面样式，避免两个图表贴在一起。"""
    html = out.read_text(encoding="utf-8")
    viewport = '<meta name="viewport" content="width=device-width, initial-scale=1.0">'
    if viewport not in html:
        html = html.replace('<meta charset="UTF-8">', f'<meta charset="UTF-8">\n    {viewport}', 1)

    # Pyecharts 的 Page 默认样式会在 body 中再次定义 .box，必须先移除，
    # 否则它会覆盖下面的响应式布局样式。
    html = re.sub(
        r"\s*<style>\s*\.box\s*\{\s*justify-content:center;\s*display:flex;\s*flex-wrap:wrap;\s*\}\s*</style>\s*",
        "\n",
        html,
        count=1,
    )
    new_style = """<style id="sentiment-responsive">
    html { margin: 0; padding: 0; background: #faf8f5; overflow-x: hidden; }
    body {
        margin: 0;
        padding: 20px;
        box-sizing: border-box;
        background: #faf8f5;
        color: #333;
        overflow-x: hidden;
        font-family: "Georgia", serif;
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 20px;
    }
    .sentiment-summary {
        width: min(1180px, calc(100vw - 32px));
        box-sizing: border-box;
        margin: 28px auto 0;
        padding: 18px 22px;
        border: 1px solid #e2e8f0;
        border-radius: 8px;
        background: #ffffff;
        box-shadow: 0 10px 28px rgba(15, 23, 42, 0.08);
        display: grid;
        grid-template-columns: minmax(260px, 1.4fr) minmax(360px, 2fr);
        gap: 18px;
        align-items: center;
    }
    .sentiment-summary strong { display: block; font-size: 18px; margin-bottom: 6px; }
    .sentiment-summary span { color: #475569; line-height: 1.55; }
    .sentiment-summary ul {
        margin: 0;
        padding: 0;
        list-style: none;
        display: grid;
        grid-template-columns: repeat(4, minmax(86px, 1fr));
        gap: 10px;
    }
    .sentiment-summary li {
        min-height: 66px;
        border-radius: 8px;
        background: #f8fafc;
        border: 1px solid #e2e8f0;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
    }
    .sentiment-summary li strong { font-size: 22px; margin: 2px 0 0; }
    .box {
        width: min(1240px, calc(100vw - 40px));
        box-sizing: border-box;
        margin: 0 auto;
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 34px;
        padding: 32px 0 44px;
    }
    .chart-container {
        box-sizing: border-box;
        min-width: 0;
        border: 1px solid #e2e8f0;
        border-radius: 8px;
        background: #fff;
        box-shadow: 0 10px 28px rgba(15, 23, 42, 0.08);
    }
    @media (max-width: 760px) {
        .sentiment-summary {
            width: 100%;
            margin-top: 16px;
            padding: 16px;
            grid-template-columns: 1fr;
        }
        .sentiment-summary ul { grid-template-columns: repeat(2, minmax(0, 1fr)); }
        .box { padding: 16px 0 28px; gap: 22px; }
        .chart-container { width: 100% !important; max-width: 100% !important; }
    }
    </style>"""
    html = html.replace("</head>", f"{new_style}\n</head>", 1)

    if 'id="sentiment-summary"' not in html:
        html = html.replace('<div class="box">', render_summary_html(sentiment_summary) + '\n<div class="box">', 1)

    html = re.sub(
        r'class="chart-container" style="width:(\d+)px; height:(\d+)px; ?"',
        (
            r'class="chart-container" data-chart-width="\1" data-chart-height="\2" '
            r'style="--chart-width:\1px; --chart-height:\2px; '
            r'width:100%; max-width:var(--chart-width); height:var(--chart-height); "'
        ),
        html,
    )

    resize_script = """
    <script id="sentiment-resize">
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
    html = html.replace("</body>", f"{resize_script}</body>", 1)
    html = inject_index_backlink(html)
    out.write_text(html, encoding="utf-8")


if __name__ == "__main__":
    render()
