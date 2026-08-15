"""可视化 3：朝代 × 季节作品分布。

每根柱子高度表示作品数，颜色固定表示季节；平均情感只放在 tooltip 中，
避免图例是季节而颜色又表达情感造成误读。
"""
import sys
import re
from pathlib import Path

import pymysql
from pyecharts import options as opts
from pyecharts.charts import Bar, Page
from pyecharts.commons.utils import JsCode

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from config import MYSQL, DB_NAME, OUTPUT_DIR
from viz_assets import inject_index_backlink, localize_pyecharts_assets

POET_OUTPUT_SEASON_BAR_ID = "poet_output_season_bar"
SEASON_COLORS = {
    "春": "#22c55e",
    "夏": "#f97316",
    "秋": "#d97706",
    "冬": "#2563eb",
    "未标": "#94a3b8",
}


SEASON_TOOLTIP_FORMATTER = JsCode(
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
        return '<strong>' + esc(params.name) + ' / ' + esc(params.seriesName) + '</strong>'
            + '<br/>作品数：' + esc(data.value || params.value)
            + '<br/>平均情感：' + esc(data.avgSentiment == null ? '' : data.avgSentiment.toFixed(3));
    }
    """
)


def polish_page(out: Path, poet_count: int, poem_count: int) -> None:
    html = out.read_text(encoding="utf-8")
    
    # Custom dashboard styling injection for varied look
    custom_css = """
    <style>
        body { background: #fdfdfd; font-family: "Segoe UI", sans-serif; padding: 40px; margin: 0; }
        .box { background: white; border-radius: 16px; box-shadow: 0 10px 30px rgba(0,0,0,0.04); padding: 30px; margin: 0 auto; max-width: 1200px; }
        .nav-link { position: absolute; top: 20px; left: 20px; text-decoration: none; color: #475569; font-weight: bold; background: #f1f5f9; padding: 8px 16px; border-radius: 8px; }
    </style>
    <a href="index.html" class="nav-link">← 返回大屏</a>
    """
    if "</head>" in html:
        html = html.replace("</head>", f"{custom_css}\n</head>")
    viewport = '<meta name="viewport" content="width=device-width, initial-scale=1.0">'
    if viewport not in html:
        html = html.replace('<meta charset="UTF-8">', f'<meta charset="UTF-8">\n    {viewport}', 1)

    style = """
    <style id="poet-output-responsive">
        html, body { margin: 0; padding: 0; background: #edf2f7; color: #0f172a; overflow-x: hidden; }
        body { font-family: "Microsoft YaHei", "PingFang SC", Arial, sans-serif; }
        .poet-output-hero {
            padding: 30px max(18px, calc((100vw - 1180px) / 2)) 20px;
            background: #f8fafc;
            border-bottom: 1px solid #dbe3ef;
        }
        .poet-output-title { margin: 0; font-size: 30px; line-height: 1.25; letter-spacing: 0; }
        .poet-output-subtitle { margin: 8px 0 0; color: #64748b; line-height: 1.75; font-size: 14px; }
        .box { display: flex; justify-content: center; align-items: flex-start; flex-wrap: wrap; gap: 22px; padding: 24px 12px 38px; }
        .chart-container {
            box-sizing: border-box;
            flex: 0 1 auto;
            min-width: 0;
            border: 1px solid #dbe3ef;
            border-radius: 8px;
            background: #fff;
            box-shadow: 0 10px 26px rgba(15, 23, 42, 0.08);
            overflow: hidden;
        }
        @media (max-width: 760px) {
            .poet-output-hero { padding: 22px 12px 16px; }
            .poet-output-title { font-size: 24px; }
            .box { padding: 16px 8px 28px; gap: 16px; }
            .chart-container {
                width: calc(100vw - 16px) !important;
                max-width: calc(100vw - 16px) !important;
                height: min(72vh, var(--chart-height)) !important;
                max-height: 72vh;
            }
        }
    </style>
"""
    old_style = '<style>.box { justify-content:center; display:flex; flex-wrap:wrap;  } </style>'
    if old_style in html:
        html = html.replace(old_style, style, 1)
    elif "poet-output-responsive" not in html:
        html = html.replace("</head>", f"{style}</head>", 1)

    html = re.sub(
        r'class="chart-container" style="width:(\d+)px; height:(\d+)px; ?"',
        (
            r'class="chart-container" data-chart-width="\1" data-chart-height="\2" '
            r'style="--chart-width:\1px; --chart-height:\2px; '
            r'width:100%; max-width:var(--chart-width); height:var(--chart-height); "'
        ),
        html,
    )

    hero = f"""
    <section class="poet-output-hero">
        <h1 class="poet-output-title">朝代 × 季节作品分布</h1>
        <p class="poet-output-subtitle">
            覆盖 {poet_count} 位诗人、{poem_count} 首作品。柱高表示作品数量，
            颜色固定表示季节；平均情感只在悬浮提示中展示。
        </p>
    </section>
"""
    html = html.replace("<body >", f"<body >\n{hero}", 1)

    script = """
    <script id="poet-output-resize">
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
    html = html.replace("</body>", f"{script}</body>", 1)
    html = inject_index_backlink(html)
    out.write_text(html, encoding="utf-8")


def render():
    with pymysql.connect(**MYSQL, database=DB_NAME) as conn, conn.cursor() as cur:
        cur.execute("SELECT COUNT(*), COALESCE(SUM(poem_count), 0) FROM t_poet WHERE poem_count > 0")
        poet_count, poem_count = cur.fetchone()

        cur.execute("""
            SELECT pt.dynasty, COALESCE(pm.season, '未标'), COUNT(*),
                   AVG(pm.sentiment)
              FROM t_poem  pm
              JOIN t_poet  pt ON pt.poet_id = pm.poet_id
             GROUP BY pt.dynasty, season
             ORDER BY pt.dynasty
        """)
        season_rows = cur.fetchall()

    # ---------- 朝代×季节堆叠柱 ----------
    dyn_order = sorted({r[0] for r in season_rows})
    season_order = ["春", "夏", "秋", "冬", "未标"]
    matrix = {(dyn, s): 0 for dyn in dyn_order for s in season_order}
    sent_matrix = {(dyn, s): 0.0 for dyn in dyn_order for s in season_order}
    for dyn, s, n, avg_s in season_rows:
        matrix[(dyn, s)] = int(n)
        sent_matrix[(dyn, s)] = float(avg_s or 0)

    bar2 = Bar(init_opts=opts.InitOpts(width="1000px", height="500px",
                                       chart_id=POET_OUTPUT_SEASON_BAR_ID))
    bar2.add_xaxis(dyn_order)
    for s in season_order:
        bar2.add_yaxis(
            s,
            [
                {
                    "value": matrix[(dyn, s)],
                    "avgSentiment": sent_matrix[(dyn, s)],
                    "itemStyle": {"color": SEASON_COLORS[s]},
                }
                for dyn in dyn_order
            ],
            stack="ALL",
            label_opts=opts.LabelOpts(is_show=True, position="inside"),
        )
    bar2.set_global_opts(
        title_opts=opts.TitleOpts(title="朝代 × 季节作品分布",
                                  subtitle="堆叠高度为作品数，颜色固定表示季节；平均情感见 tooltip",
                                  pos_left="center"),
        legend_opts=opts.LegendOpts(pos_top="8%"),
        xaxis_opts=opts.AxisOpts(name="朝代"),
        yaxis_opts=opts.AxisOpts(name="作品数"),
        tooltip_opts=opts.TooltipOpts(trigger="item", formatter=SEASON_TOOLTIP_FORMATTER),
    )

    from pyecharts.charts import Timeline
    page = Page(layout=Page.SimplePageLayout, page_title="季节分布")
    tl = Timeline()
    tl.add_schema(is_auto_play=True, play_interval=2000, pos_bottom="-5px")
    tl.add(bar2, "全量汇总")
    page.add(tl)
    out = OUTPUT_DIR / "03_诗人产出.html"
    page.render(str(out))
    localize_pyecharts_assets(out, OUTPUT_DIR)
    polish_page(out, int(poet_count or 0), int(poem_count or 0))
    print(f"  [ok] saved {out}  ({int(poet_count or 0)} 位诗人 / {int(poem_count or 0)} 首作品)")


if __name__ == "__main__":
    render()
