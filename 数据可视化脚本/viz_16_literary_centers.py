"""可视化 16：唐宋诗歌创作活动中心迁移（审核精细样本）。

数据边界：
    仅使用 data/reviewed/verified_poem_contexts.csv 中 status=approved、
    能与 poems.json 的作者/标题对应且坐标完整的创作背景记录。
    historical_place 是经年谱、校注或作品题序支持的创作地，不使用诗中提及地。

输出：
    output/16_唐宋诗歌创作活动中心迁移.html

运行：
    python .\数据可视化脚本\viz_16_literary_centers.py
"""
from __future__ import annotations

import csv
import json
import math
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from html import escape
from pathlib import Path

from pyecharts import options as opts
from pyecharts.charts import Bar, Geo, Page, Timeline
from pyecharts.commons.utils import JsCode
from pyecharts.globals import ChartType, ThemeType


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config import OUTPUT_DIR
from viz_assets import inject_premium_chart_page


DATA_CSV = ROOT / "data" / "reviewed" / "verified_poem_contexts.csv"
POEMS_JSON = ROOT / "data" / "poems.json"
OUT_HTML = OUTPUT_DIR / "16_唐宋诗歌创作活动中心迁移.html"
LOCAL_ASSET_DIR = OUTPUT_DIR / "assets" / "pyecharts" / "v6"

TARGET_POETS = ("李白", "杜甫", "白居易", "苏轼", "陆游", "李清照")
GRADE_WEIGHT = {"A": 1.0, "B": 0.75, "C": 0.5}
WORK_WEIGHT = 0.45
POET_WEIGHT = 0.35
EVIDENCE_WEIGHT = 0.20

PERIODS = (
    ("唐·开元天宝", 713, 755),
    ("唐·安史至大历", 756, 779),
    ("唐·中晚期", 780, 907),
    ("宋·北宋前中期", 960, 1079),
    ("宋·北宋晚期", 1080, 1126),
    ("宋·南宋前期", 1127, 1179),
    ("宋·南宋中后期", 1180, 1279),
)

COLORS = {
    "唐·开元天宝": "#f59e0b",
    "唐·安史至大历": "#ef4444",
    "唐·中晚期": "#f97316",
    "宋·北宋前中期": "#22c55e",
    "宋·北宋晚期": "#06b6d4",
    "宋·南宋前期": "#3b82f6",
    "宋·南宋中后期": "#a855f7",
}

CITY_TOOLTIP = JsCode(
    """
    function (params) {
        var data = params.data || {};
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
        var value = data.value || [];
        var html = '<div style="max-width:390px;line-height:1.7;white-space:normal;">'
            + '<strong style="font-size:16px;color:#f8fafc;">' + esc(params.name) + '</strong>'
            + '<br/><span style="color:#94a3b8;">' + esc(data.period || '') + '</span>'
            + '<br/>综合活跃度：<b>' + esc(data.activityIndex || value[2] || 0) + '</b>'
            + '<br/>审核作品：' + esc(data.poemCount || 0) + ' 首'
            + '<br/>独立诗人：' + esc(data.poetCount || 0) + ' 位'
            + '<br/>证据质量分：' + esc(data.qualityPoints || 0)
            + '<br/>作品份额 / 诗人参与份额 / 证据份额：'
            + esc(data.workShare || 0) + '% / ' + esc(data.poetShare || 0) + '% / ' + esc(data.qualityShare || 0) + '%';
        if (data.poets) {
            html += '<br/>诗人：' + esc(data.poets);
        }
        if (data.poems) {
            html += '<br/><span style="color:#94a3b8;">样本：</span>' + esc(data.poems);
        }
        return html + '</div>';
    }
    """
)


@dataclass(frozen=True)
class ContextRow:
    poet: str
    title: str
    dynasty: str
    year_start: int
    year_end: int
    historical_place: str
    modern_city: str
    province: str
    lon: float
    lat: float
    source_name: str
    source_url: str
    source_note: str
    fact_grade: str
    status: str

    @property
    def representative_year(self) -> int:
        return round((self.year_start + self.year_end) / 2)

    @property
    def quality_weight(self) -> float:
        return GRADE_WEIGHT[self.fact_grade]


@dataclass(frozen=True)
class CityMetric:
    period: str
    city: str
    province: str
    lon: float
    lat: float
    poem_count: int
    poet_count: int
    quality_points: float
    work_share: float
    poet_share: float
    quality_share: float
    activity_index: float
    poets: tuple[str, ...]
    poems: tuple[str, ...]
    grades: dict[str, int]


@dataclass(frozen=True)
class PeriodMetric:
    label: str
    start: int
    end: int
    rows: tuple[ContextRow, ...]
    cities: tuple[CityMetric, ...]
    center_lon: float
    center_lat: float

    @property
    def poet_count(self) -> int:
        return len({row.poet for row in self.rows})


def load_poem_keys() -> set[tuple[str, str, str]]:
    records = json.loads(POEMS_JSON.read_text(encoding="utf-8"))
    return {
        (
            str(row.get("poet") or row.get("author") or "").strip(),
            str(row.get("title") or "").strip(),
            str(row.get("dynasty") or "").strip(),
        )
        for row in records
    }


def load_contexts() -> tuple[list[ContextRow], dict[str, int]]:
    if not DATA_CSV.exists():
        raise FileNotFoundError(f"审核样本不存在：{DATA_CSV}")

    poem_keys = load_poem_keys()
    accepted: list[ContextRow] = []
    stats = Counter()

    with DATA_CSV.open("r", encoding="utf-8-sig", newline="") as file:
        for line_no, raw in enumerate(csv.DictReader(file), start=2):
            stats["reviewed_rows"] += 1
            status = str(raw.get("status") or "").strip()
            if status != "approved":
                stats["not_approved"] += 1
                continue

            try:
                year_start = int(str(raw.get("year_start") or "").strip())
                year_end = int(str(raw.get("year_end") or "").strip())
                lon = float(str(raw.get("lon") or "").strip())
                lat = float(str(raw.get("lat") or "").strip())
            except ValueError:
                stats["invalid_numeric"] += 1
                continue

            row = ContextRow(
                poet=str(raw.get("poet") or "").strip(),
                title=str(raw.get("title") or "").strip(),
                dynasty=str(raw.get("dynasty") or "").strip(),
                year_start=year_start,
                year_end=year_end,
                historical_place=str(raw.get("historical_place") or "").strip(),
                modern_city=str(raw.get("modern_city") or "").strip(),
                province=str(raw.get("province") or "").strip(),
                lon=lon,
                lat=lat,
                source_name=str(raw.get("source_name") or "").strip(),
                source_url=str(raw.get("source_url") or "").strip(),
                source_note=str(raw.get("source_note") or "").strip(),
                fact_grade=str(raw.get("fact_grade") or "").strip().upper(),
                status=status,
            )

            if (row.poet, row.title, row.dynasty) not in poem_keys:
                stats["unmatched_poem"] += 1
                continue
            if row.poet not in TARGET_POETS:
                stats["out_of_scope_poet"] += 1
                continue
            if row.fact_grade not in GRADE_WEIGHT:
                stats["invalid_grade"] += 1
                continue
            if not (73.0 <= row.lon <= 136.0 and 18.0 <= row.lat <= 54.0):
                stats["invalid_coordinate"] += 1
                continue
            if row.year_start > row.year_end:
                stats["invalid_year_range"] += 1
                continue
            if not row.modern_city or not row.historical_place or not row.source_url:
                stats["missing_context"] += 1
                continue

            accepted.append(row)

    stats["accepted_rows"] = len(accepted)
    return accepted, dict(stats)


def period_for(row: ContextRow) -> tuple[str, int, int] | None:
    year = row.representative_year
    for label, start, end in PERIODS:
        if start <= year <= end:
            return label, start, end
    return None


def aggregate_periods(rows: list[ContextRow]) -> list[PeriodMetric]:
    by_period: dict[str, list[ContextRow]] = defaultdict(list)
    for row in rows:
        matched = period_for(row)
        if matched:
            by_period[matched[0]].append(row)

    output: list[PeriodMetric] = []
    for label, start, end in PERIODS:
        period_rows = sorted(
            by_period.get(label, []),
            key=lambda row: (row.representative_year, row.modern_city, row.poet, row.title),
        )
        if not period_rows:
            continue

        city_rows: dict[str, list[ContextRow]] = defaultdict(list)
        for row in period_rows:
            city_rows[row.modern_city].append(row)

        city_poet_total = sum(len({row.poet for row in items}) for items in city_rows.values())
        quality_total = sum(row.quality_weight for row in period_rows)
        city_metrics: list[CityMetric] = []

        for city, items in city_rows.items():
            poem_count = len(items)
            poets = tuple(sorted({row.poet for row in items}))
            quality_points = sum(row.quality_weight for row in items)
            work_share = poem_count / len(period_rows)
            poet_share = len(poets) / city_poet_total if city_poet_total else 0.0
            quality_share = quality_points / quality_total if quality_total else 0.0
            activity_index = 100.0 * (
                WORK_WEIGHT * work_share
                + POET_WEIGHT * poet_share
                + EVIDENCE_WEIGHT * quality_share
            )
            city_metrics.append(
                CityMetric(
                    period=label,
                    city=city,
                    province=items[0].province,
                    lon=sum(row.lon for row in items) / poem_count,
                    lat=sum(row.lat for row in items) / poem_count,
                    poem_count=poem_count,
                    poet_count=len(poets),
                    quality_points=quality_points,
                    work_share=100.0 * work_share,
                    poet_share=100.0 * poet_share,
                    quality_share=100.0 * quality_share,
                    activity_index=activity_index,
                    poets=poets,
                    poems=tuple(f"{row.poet}《{row.title}》" for row in items),
                    grades=dict(Counter(row.fact_grade for row in items)),
                )
            )

        city_metrics.sort(key=lambda item: (-item.activity_index, item.city))
        score_total = sum(item.activity_index for item in city_metrics) or 1.0
        center_lon = sum(item.lon * item.activity_index for item in city_metrics) / score_total
        center_lat = sum(item.lat * item.activity_index for item in city_metrics) / score_total
        output.append(
            PeriodMetric(
                label=label,
                start=start,
                end=end,
                rows=tuple(period_rows),
                cities=tuple(city_metrics),
                center_lon=center_lon,
                center_lat=center_lat,
            )
        )

    return output


def find_series(chart: Geo, name: str) -> dict:
    for series in chart.options.get("series", []):
        if series.get("name") == name:
            return series
    raise KeyError(f"找不到 Geo 系列：{name}")


def attach_city_metadata(geo: Geo, series_name: str, metrics: tuple[CityMetric, ...]) -> None:
    lookup = {metric.city: metric for metric in metrics}
    for item in find_series(geo, series_name).get("data", []):
        metric = lookup.get(str(item.get("name") or ""))
        if not metric:
            continue
        item.update(
            {
                "period": metric.period,
                "activityIndex": round(metric.activity_index, 2),
                "poemCount": metric.poem_count,
                "poetCount": metric.poet_count,
                "qualityPoints": round(metric.quality_points, 2),
                "workShare": round(metric.work_share, 1),
                "poetShare": round(metric.poet_share, 1),
                "qualityShare": round(metric.quality_share, 1),
                "poets": "、".join(metric.poets),
                "poems": "；".join(metric.poems),
            }
        )


def build_period_geo(period: PeriodMetric, center_history: list[PeriodMetric]) -> Geo:
    color = COLORS[period.label]
    geo = Geo(
        init_opts=opts.InitOpts(
            width="1200px",
            height="720px",
            bg_color="#07111f",
            theme=ThemeType.DARK,
        )
    )
    geo.add_schema(
        maptype="china",
        center=[105, 34],
        zoom=1.05,
        is_roam=True,
        itemstyle_opts=opts.ItemStyleOpts(
            color="#172033",
            border_color="#475569",
            border_width=0.8,
        ),
        emphasis_itemstyle_opts=opts.ItemStyleOpts(color="#26344d"),
        label_opts=opts.LabelOpts(is_show=False),
    )

    for metric in period.cities:
        geo.add_coordinate(metric.city, metric.lon, metric.lat)

    series_name = f"{period.label}·审核创作样本"
    geo.add(
        series_name,
        [(metric.city, round(metric.activity_index, 2)) for metric in period.cities],
        type_=ChartType.EFFECT_SCATTER,
        symbol_size=JsCode("function (value) { return Math.max(12, Math.min(34, 9 + value[2] * 0.42)); }"),
        color=color,
        effect_opts=opts.EffectOpts(scale=3.0, period=4.0, brush_type="stroke", color=color),
        label_opts=opts.LabelOpts(
            is_show=True,
            position="right",
            color="#f8fafc",
            font_size=11,
            formatter="{b}",
        ),
        tooltip_opts=opts.TooltipOpts(formatter=CITY_TOOLTIP),
    )
    attach_city_metadata(geo, series_name, period.cities)

    center_names: list[str] = []
    for item in center_history:
        center_name = f"重心·{item.label}"
        center_names.append(center_name)
        geo.add_coordinate(center_name, item.center_lon, item.center_lat)

    if len(center_names) > 1:
        geo.add(
            "样本重心迁移",
            list(zip(center_names[:-1], center_names[1:])),
            type_=ChartType.LINES,
            effect_opts=opts.EffectOpts(is_show=True, period=5, trail_length=0.25, symbol="arrow", symbol_size=6),
            linestyle_opts=opts.LineStyleOpts(color="#e2e8f0", width=2, opacity=0.68, curve=0.18),
            label_opts=opts.LabelOpts(is_show=False),
            tooltip_opts=opts.TooltipOpts(is_show=False),
        )

    geo.add(
        "历期样本加权重心",
        [(name, index + 1) for index, name in enumerate(center_names)],
        type_=ChartType.SCATTER,
        symbol="diamond",
        symbol_size=13,
        color="#f8fafc",
        itemstyle_opts=opts.ItemStyleOpts(
            color="#f8fafc",
            border_color="#0f172a",
            border_width=2,
        ),
        label_opts=opts.LabelOpts(is_show=False),
        tooltip_opts=opts.TooltipOpts(formatter="{b}"),
    )

    top_city = period.cities[0]
    geo.set_global_opts(
        title_opts=opts.TitleOpts(
            title=f"{period.label}（{period.start}-{period.end}）",
            subtitle=(
                f"审核样本 {len(period.rows)} 首｜城市 {len(period.cities)} 个｜"
                f"诗人 {period.poet_count} 位｜样本活跃度最高：{top_city.city} {top_city.activity_index:.2f}"
            ),
            pos_left="center",
            pos_top="2%",
            title_textstyle_opts=opts.TextStyleOpts(color="#f8fafc", font_size=21),
            subtitle_textstyle_opts=opts.TextStyleOpts(color="#94a3b8", font_size=12),
        ),
        legend_opts=opts.LegendOpts(
            pos_top="10%",
            pos_left="center",
            textstyle_opts=opts.TextStyleOpts(color="#cbd5e1"),
        ),
        tooltip_opts=opts.TooltipOpts(
            background_color="rgba(7,17,31,0.96)",
            border_color=color,
            textstyle_opts=opts.TextStyleOpts(color="#e2e8f0"),
        ),
    )
    return geo


def build_timeline(periods: list[PeriodMetric]) -> Timeline:
    timeline = Timeline(
        init_opts=opts.InitOpts(
            width="1200px",
            height="760px",
            bg_color="#07111f",
            theme=ThemeType.DARK,
        )
    )
    center_history: list[PeriodMetric] = []
    for period in periods:
        center_history.append(period)
        timeline.add(build_period_geo(period, list(center_history)), time_point=period.label)

    timeline.add_schema(
        axis_type="category",
        is_auto_play=False,
        is_loop_play=False,
        play_interval=2600,
        pos_left="8%",
        pos_right="8%",
        pos_bottom="1%",
        label_opts=opts.LabelOpts(color="#cbd5e1", font_size=11),
        itemstyle_opts=opts.ItemStyleOpts(color="#334155", border_color="#94a3b8"),
        checkpointstyle_opts=opts.TimelineCheckPointerStyle(color="#f8fafc", border_color="#06b6d4"),
        controlstyle_opts=opts.TimelineControlStyle(
            color="#cbd5e1",
            border_color="#64748b",
            position="left",
        ),
    )
    return timeline


def build_period_bar(periods: list[PeriodMetric]) -> Bar:
    labels = [period.label for period in periods]
    bar = Bar(
        init_opts=opts.InitOpts(
            width="1200px",
            height="500px",
            bg_color="#07111f",
            theme=ThemeType.DARK,
        )
    )
    bar.add_xaxis(labels)
    bar.add_yaxis(
        "审核作品数",
        [len(period.rows) for period in periods],
        color="#06b6d4",
        category_gap="42%",
        label_opts=opts.LabelOpts(is_show=True, position="top", color="#e2e8f0"),
    )
    bar.add_yaxis(
        "覆盖城市数",
        [len(period.cities) for period in periods],
        color="#f59e0b",
        label_opts=opts.LabelOpts(is_show=True, position="top", color="#e2e8f0"),
    )
    bar.set_global_opts(
        title_opts=opts.TitleOpts(
            title="各时期精细样本量与空间覆盖",
            subtitle="柱高只描述当前审核样本，不等同于唐宋全量创作规模",
            pos_left="center",
            title_textstyle_opts=opts.TextStyleOpts(color="#f8fafc", font_size=20),
            subtitle_textstyle_opts=opts.TextStyleOpts(color="#94a3b8"),
        ),
        legend_opts=opts.LegendOpts(pos_top="12%", textstyle_opts=opts.TextStyleOpts(color="#cbd5e1")),
        xaxis_opts=opts.AxisOpts(
            axislabel_opts=opts.LabelOpts(color="#cbd5e1", rotate=18, font_size=11),
            axisline_opts=opts.AxisLineOpts(linestyle_opts=opts.LineStyleOpts(color="#475569")),
        ),
        yaxis_opts=opts.AxisOpts(
            name="条目数",
            min_=0,
            axislabel_opts=opts.LabelOpts(color="#94a3b8"),
            splitline_opts=opts.SplitLineOpts(
                is_show=True,
                linestyle_opts=opts.LineStyleOpts(color="rgba(148,163,184,0.16)"),
            ),
        ),
        tooltip_opts=opts.TooltipOpts(trigger="axis"),
    )
    return bar


def localize_assets(html: str) -> str:
    replacements = {
        "https://assets.pyecharts.org/assets/v6/echarts.min.js": "assets/pyecharts/v6/echarts.min.js",
        "https://assets.pyecharts.org/assets/v6/maps/china.js": "assets/pyecharts/v6/maps/china.js",
    }
    for remote, relative in replacements.items():
        local = LOCAL_ASSET_DIR / relative.removeprefix("assets/pyecharts/v6/")
        if not local.exists() or local.stat().st_size <= 1024:
            raise RuntimeError(f"本地可视化资源缺失或异常：{local}")
        html = html.replace(remote, relative)
    return html


def build_method_panel(
    periods: list[PeriodMetric],
    rows: list[ContextRow],
    target_poem_count: int,
    load_stats: dict[str, int],
) -> str:
    mapped_rate = 100.0 * len(rows) / load_stats["reviewed_rows"] if load_stats["reviewed_rows"] else 0.0
    coverage_rate = 100.0 * len(rows) / target_poem_count if target_poem_count else 0.0
    grade_counts = Counter(row.fact_grade for row in rows)

    period_rows_html: list[str] = []
    city_rows_html: list[str] = []
    for period in periods:
        top = period.cities[0]
        period_rows_html.append(
            "<tr>"
            f"<td>{escape(period.label)}</td>"
            f"<td>{period.start}-{period.end}</td>"
            f"<td>{len(period.rows)}</td>"
            f"<td>{period.poet_count}</td>"
            f"<td>{len(period.cities)}</td>"
            f"<td>{period.center_lon:.3f}, {period.center_lat:.3f}</td>"
            f"<td>{escape(top.city)} / {top.activity_index:.2f}</td>"
            "</tr>"
        )
        for metric in period.cities:
            city_rows_html.append(
                "<tr>"
                f"<td>{escape(period.label)}</td>"
                f"<td>{escape(metric.province)} · {escape(metric.city)}</td>"
                f"<td>{metric.poem_count}</td>"
                f"<td>{metric.poet_count}</td>"
                f"<td>{metric.quality_points:.2f}</td>"
                f"<td>{metric.work_share:.1f}%</td>"
                f"<td>{metric.poet_share:.1f}%</td>"
                f"<td>{metric.quality_share:.1f}%</td>"
                f"<td><strong>{metric.activity_index:.2f}</strong></td>"
                "</tr>"
            )

    evidence_rows_html: list[str] = []
    for row in sorted(rows, key=lambda item: (item.representative_year, item.poet, item.title)):
        period = period_for(row)
        year = str(row.year_start) if row.year_start == row.year_end else f"{row.year_start}-{row.year_end}"
        evidence_rows_html.append(
            "<tr>"
            f"<td>{escape(row.poet)}</td>"
            f"<td>《{escape(row.title)}》</td>"
            f"<td>{year}</td>"
            f"<td>{escape(row.historical_place)} → {escape(row.modern_city)}</td>"
            f"<td><span class=\"center-grade grade-{row.fact_grade.lower()}\">{row.fact_grade}</span></td>"
            f"<td>{escape(period[0] if period else '未分期')}</td>"
            f"<td><a href=\"{escape(row.source_url, quote=True)}\" target=\"_blank\" rel=\"noreferrer\">{escape(row.source_name)}</a>"
            f"<small>{escape(row.source_note)}</small></td>"
            "</tr>"
        )

    return f"""
    <section class="center-method shixing-premium-section" aria-label="样本与方法">
        <div class="center-kpis">
            <div><span>审核入图样本</span><strong>{len(rows)}</strong><small>status=approved 且坐标完整</small></div>
            <div><span>精细语料覆盖率</span><strong>{coverage_rate:.1f}%</strong><small>{len(rows)} / {target_poem_count} 首目标诗作</small></div>
            <div><span>审核记录入图率</span><strong>{mapped_rate:.1f}%</strong><small>{len(rows)} / {load_stats['reviewed_rows']} 条</small></div>
            <div><span>证据等级</span><strong>A {grade_counts['A']} · B {grade_counts['B']} · C {grade_counts['C']}</strong><small>A=1.00 / B=0.75 / C=0.50</small></div>
        </div>

        <div class="center-warning">
            本页是六位代表诗人当前精细样本的探索性“创作活动分布”，不能代表唐宋全部诗歌的真实文化中心，
            也不能据此直接推断全国文学重心。数据只采用有来源的创作地；不使用诗中提及地代替创作地。
        </div>

        <div class="center-formula-grid">
            <article>
                <h2>综合活跃度公式</h2>
                <code>I(c,t) = 100 × [0.45 × W(c,t) + 0.35 × P(c,t) + 0.20 × Q(c,t)]</code>
                <p>W：城市作品数 / 当期作品总数；P：城市独立诗人数 / 当期各城市独立诗人数之和；Q：城市证据质量分 / 当期证据质量总分。</p>
            </article>
            <article>
                <h2>样本加权中心</h2>
                <code>Lon(t) = Σ[Lon(c) × I(c,t)] / ΣI(c,t)</code>
                <p>纬度同式。地图白色菱形是各期样本加权中心，连线只表达当前样本的空间变化，不是历史因果结论。</p>
            </article>
        </div>

        <div class="center-table-panel">
            <h2>时期汇总</h2>
            <div class="center-table-scroll"><table>
                <thead><tr><th>时期</th><th>年份</th><th>作品</th><th>诗人</th><th>城市</th><th>样本重心</th><th>活跃度最高城市</th></tr></thead>
                <tbody>{''.join(period_rows_html)}</tbody>
            </table></div>
        </div>

        <details class="center-table-panel" open>
            <summary>查看全部单项指标</summary>
            <div class="center-table-scroll"><table>
                <thead><tr><th>时期</th><th>城市</th><th>作品数</th><th>诗人数</th><th>证据质量分</th><th>作品份额</th><th>诗人参与份额</th><th>证据份额</th><th>综合活跃度</th></tr></thead>
                <tbody>{''.join(city_rows_html)}</tbody>
            </table></div>
        </details>

        <details class="center-table-panel">
            <summary>查看 {len(rows)} 条作品级证据</summary>
            <div class="center-table-scroll"><table>
                <thead><tr><th>诗人</th><th>作品</th><th>年份</th><th>创作地</th><th>等级</th><th>分期</th><th>来源与审核说明</th></tr></thead>
                <tbody>{''.join(evidence_rows_html)}</tbody>
            </table></div>
        </details>
    </section>
    """


def custom_css() -> str:
    return """
    <style id="literary-center-method-style">
        .center-method { display:grid; grid-template-columns:minmax(0,1fr); gap:18px; }
        .center-method > * { min-width:0; }
        .center-kpis { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:12px; }
        .center-kpis > div,
        .center-formula-grid article,
        .center-table-panel,
        .center-warning {
            border:1px solid rgba(148,163,184,.24);
            border-radius:8px;
            background:rgba(15,23,42,.78);
        }
        .center-kpis > div { min-height:112px; padding:16px; }
        .center-kpis span,
        .center-kpis small { display:block; color:#94a3b8; font-size:12px; line-height:1.6; }
        .center-kpis strong { display:block; margin:8px 0 6px; color:#f8fafc; font-size:25px; line-height:1.15; overflow-wrap:anywhere; }
        .center-warning { padding:14px 16px; border-color:rgba(245,158,11,.4); color:#fde68a; line-height:1.8; }
        .center-formula-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px; }
        .center-formula-grid article { padding:18px; }
        .center-formula-grid h2,
        .center-table-panel h2 { margin:0 0 12px; color:#f8fafc; font-size:18px; }
        .center-formula-grid code { display:block; padding:12px; overflow-x:auto; border:1px solid rgba(6,182,212,.3); border-radius:6px; background:#07111f; color:#67e8f9; line-height:1.7; white-space:nowrap; }
        .center-formula-grid p { margin:12px 0 0; color:#aab7c8; font-size:13px; line-height:1.8; }
        .center-table-panel { padding:18px; }
        .center-table-panel summary { color:#f8fafc; font-size:17px; font-weight:800; cursor:pointer; }
        .center-table-panel[open] summary { margin-bottom:14px; }
        .center-table-scroll { width:100%; max-width:100%; overflow:auto; }
        .center-table-panel table { width:100%; min-width:900px; border-collapse:collapse; }
        .center-table-panel th,
        .center-table-panel td { padding:10px 12px; border-bottom:1px solid rgba(148,163,184,.18); text-align:left; vertical-align:top; line-height:1.65; }
        .center-table-panel th { position:sticky; top:0; background:#101a2c; color:#cbd5e1; font-size:12px; z-index:1; }
        .center-table-panel td { color:#aab7c8; font-size:13px; }
        .center-table-panel td strong { color:#67e8f9; }
        .center-table-panel td a { color:#7dd3fc; text-decoration:none; }
        .center-table-panel td a:hover { text-decoration:underline; }
        .center-table-panel td small { display:block; margin-top:5px; max-width:560px; color:#94a3b8; }
        .center-grade { display:inline-flex; align-items:center; justify-content:center; width:28px; height:24px; border-radius:4px; font-weight:900; }
        .grade-a { color:#86efac; background:rgba(34,197,94,.14); }
        .grade-b { color:#fde68a; background:rgba(245,158,11,.14); }
        .grade-c { color:#fda4af; background:rgba(244,63,94,.14); }
        body > .box { width:min(1240px,calc(100vw - 36px)); margin:0 auto 54px !important; padding:0 !important; gap:22px !important; }
        .chart-container { border-radius:8px !important; }
        @media (max-width:900px) {
            .center-kpis { grid-template-columns:repeat(2,minmax(0,1fr)); }
            .center-formula-grid { grid-template-columns:1fr; }
        }
        @media (max-width:560px) {
            .center-kpis { grid-template-columns:1fr; }
            .center-table-panel { padding:12px; }
        }
    </style>
    """


def inject_method_panel(html: str, panel: str) -> str:
    html = html.replace("</head>", f"{custom_css()}\n</head>", 1)
    marker = '<div class="box">'
    if marker in html:
        return html.replace(marker, f"{panel}\n{marker}", 1)
    return html.replace("</body>", f"{panel}\n</body>", 1)


def target_poem_count() -> int:
    records = json.loads(POEMS_JSON.read_text(encoding="utf-8"))
    return sum(
        1
        for row in records
        if str(row.get("poet") or row.get("author") or "").strip() in TARGET_POETS
    )


def render() -> None:
    rows, load_stats = load_contexts()
    periods = aggregate_periods(rows)
    if len(rows) < 20:
        raise RuntimeError(f"审核入图样本不足20条：当前 {len(rows)} 条")
    if not periods:
        raise RuntimeError("审核样本无法映射到任何预设时期")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    page = Page(layout=Page.SimplePageLayout, page_title="唐宋诗歌创作活动中心迁移")
    page.add(build_timeline(periods), build_period_bar(periods))
    page.render(str(OUT_HTML))

    total_target = target_poem_count()
    html = OUT_HTML.read_text(encoding="utf-8")
    html = localize_assets(html)
    html = inject_premium_chart_page(
        html,
        page_key="literary-centers",
        title="唐宋诗歌创作活动中心迁移",
        subtitle="以六位代表诗人的作品级编年与创作地证据，观察当前精细样本在七个时期中的空间分布与加权中心变化。",
        eyebrow="Reviewed Composition Contexts",
        metrics=[
            ("审核入图样本", f"{len(rows)} 首"),
            ("代表诗人", f"{len({row.poet for row in rows})} / {len(TARGET_POETS)} 位"),
            ("现代城市", f"{len({row.modern_city for row in rows})} 个"),
            ("精细语料覆盖", f"{100.0 * len(rows) / total_target:.1f}%"),
        ],
        note="探索性创作活动分布：仅代表当前审核精细样本；不使用诗中提及地，不能替代唐宋全量文学中心研究。",
        accent="#06b6d4",
        accent_2="#f59e0b",
        accent_3="#22c55e",
        backlink_href="index.html",
    )
    html = inject_method_panel(html, build_method_panel(periods, rows, total_target, load_stats))
    OUT_HTML.write_text(html, encoding="utf-8")

    print(
        f"  [ok] saved {OUT_HTML}  "
        f"({len(rows)} 条审核样本 / {len(periods)} 个时期 / "
        f"{len({row.modern_city for row in rows})} 个现代城市 / "
        f"目标精细语料覆盖率 {100.0 * len(rows) / total_target:.1f}%)"
    )


if __name__ == "__main__":
    render()
