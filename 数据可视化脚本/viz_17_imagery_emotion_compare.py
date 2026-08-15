"""可视化 17：同一意象的跨诗人情感差异。

数据口径：六位核心诗人（李白、杜甫、白居易、苏轼、陆游、李清照）
各取 poems.json 中该诗人的前 20 首，作为跨诗人可比的固定样本；
李白语料已扩充至 55 首（用于精神地形图专题），超出的部分不进入本页
样本，以保持六人样本量一致、基线可比。目标意象为月、酒、舟、雁、雨。
每首诗对同一意象最多计一次，情感来自意象所在分句及相邻分句的多标签
语境规则，并与诗人的 20 首固定样本情感基线比较。
"""
from __future__ import annotations

import json
import math
import re
import sys
from collections import Counter
from pathlib import Path

from pyecharts import options as opts
from pyecharts.charts import HeatMap
from pyecharts.commons.utils import JsCode


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config import OUTPUT_DIR
from data.imagery_emotion_rules import (
    EMOTIONS,
    EMOTION_CONTEXT_RULES,
    IMAGERY_RULES,
    TARGET_IMAGERY,
    TARGET_POETS,
    companion_imagery,
    emotion_matches,
    evidence_contexts,
    local_emotion_matches,
    sample_level,
)
from viz_assets import inject_index_backlink, localize_pyecharts_assets


POEMS_JSON = ROOT / "data" / "poems.json"
OUTPUT_HTML = OUTPUT_DIR / "17_同一意象的诗人情感差异.html"
CHART_ID = "imagery_emotion_heatmap"
# 拍板口径（2026-07）：每位诗人固定取语料前 20 首，保证六人样本量一致可比；
# 李白扩充语料（55 首）只服务精神地形图专题，不改变本页样本构成。
POEMS_PER_POET = 20


HEATMAP_TOOLTIP = JsCode(
    """
    function (params) {
        var v = params.value || [];
        function esc(value) {
            return String(value == null ? '' : value).replace(/[&<>"']/g, function (ch) {
                var code = ch.charCodeAt(0);
                if (code === 38) { return '&amp;'; }
                if (code === 60) { return '&lt;'; }
                if (code === 62) { return '&gt;'; }
                if (code === 34) { return '&quot;'; }
                if (code === 39) { return '&#39;'; }
                return ch;
            });
        }
        function pct(value) {
            return value == null ? '—' : (Number(value) * 100).toFixed(1) + '%';
        }
        function num(value) {
            return value == null ? '基线为 0，未计算' : Number(value).toFixed(2);
        }
        return '<strong>' + esc(v[8]) + ' · ' + esc(v[9]) + '</strong>'
            + '<br/>意象：' + esc(v[10])
            + '<br/>含意象样本：' + esc(v[6]) + ' 首（' + esc(v[7]) + '）'
            + '<br/>P(e|i,p)：' + pct(v[3])
            + '<br/>诗人基线 P(e|p)：' + pct(v[4])
            + '<br/>提升度 lift：' + num(v[5])
            + '<br/><span style="color:#64748b;">多标签语境概率，各情感之和不要求为 100%。</span>';
    }
    """
)


def load_target_poems() -> list[dict[str, object]]:
    """读取六位诗人各 20 首，并保留原始顺序作为稳定样本编号。"""
    rows = json.loads(POEMS_JSON.read_text(encoding="utf-8"))
    grouped: dict[str, list[dict[str, object]]] = {poet: [] for poet in TARGET_POETS}
    for source_index, row in enumerate(rows):
        poet = str(row.get("author") or row.get("poet") or "")
        if poet not in grouped or len(grouped[poet]) >= POEMS_PER_POET:
            continue
        grouped[poet].append(
            {
                "poem_id": f"{poet}-{source_index}",
                "source_index": source_index,
                "title": str(row.get("title") or "无题"),
                "poet": poet,
                "dynasty": str(row.get("dynasty") or ""),
                "body": str(row.get("body") or ""),
            }
        )

    shortages = {
        poet: len(poems)
        for poet, poems in grouped.items()
        if len(poems) != POEMS_PER_POET
    }
    if shortages:
        raise RuntimeError(f"目标诗人样本不足 20 首：{shortages}")
    return [poem for poet in TARGET_POETS for poem in grouped[poet]]


def _unique_evidence_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    seen: set[str] = set()
    evidence: list[dict[str, object]] = []
    for row in rows:
        line = str(row.get("line") or "").strip()
        if not line or line in seen:
            continue
        seen.add(line)
        evidence.append(
            {
                "line": line,
                "context": str(row.get("context") or "").strip(),
                "aliases": list(row.get("aliases") or []),
            }
        )
    return evidence


def _round_probability(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 6) if denominator else 0.0


def build_payload() -> dict[str, object]:
    poems = load_target_poems()
    poem_totals = Counter(str(poem["poet"]) for poem in poems)
    baseline_counts: dict[str, Counter[str]] = {
        poet: Counter() for poet in TARGET_POETS
    }
    for poem in poems:
        poet = str(poem["poet"])
        # 诗人基线用整首诗判断；同一诗内同一标签仍只计一次。
        baseline_counts[poet].update(emotion_matches(str(poem["body"])).keys())

    raw_records: dict[str, dict[str, list[dict[str, object]]]] = {
        imagery: {poet: [] for poet in TARGET_POETS}
        for imagery in TARGET_IMAGERY
    }
    for poem in poems:
        body = str(poem["body"])
        poet = str(poem["poet"])
        for imagery in TARGET_IMAGERY:
            context_rows = evidence_contexts(body, imagery, neighbor=1)
            if not context_rows:
                continue
            local_matches = local_emotion_matches(context_rows)
            local_context = "".join(
                dict.fromkeys(str(row.get("context") or "") for row in context_rows)
            )
            raw_records[imagery][poet].append(
                {
                    "poem_id": poem["poem_id"],
                    "title": poem["title"],
                    "dynasty": poem["dynasty"],
                    "evidence": _unique_evidence_rows(context_rows),
                    "emotions": list(local_matches),
                    "emotion_hits": local_matches,
                    "companions": companion_imagery(local_context, excluded=imagery),
                }
            )

    views: dict[str, dict[str, object]] = {}
    total_imagery_poem_hits = 0
    total_evidence_lines = 0
    for imagery in TARGET_IMAGERY:
        poet_rows: dict[str, dict[str, object]] = {}
        cells: list[dict[str, object]] = []
        finite_lifts: list[float] = []
        for poet in TARGET_POETS:
            records = raw_records[imagery][poet]
            sample_count = len(records)
            total_imagery_poem_hits += sample_count
            total_evidence_lines += sum(len(row["evidence"]) for row in records)
            level = sample_level(sample_count)
            conditional_counts: Counter[str] = Counter()
            companion_counts: Counter[str] = Counter()
            for record in records:
                conditional_counts.update(set(record["emotions"]))
                companion_counts.update(set(record["companions"]))

            emotion_rows: list[dict[str, object]] = []
            for emotion in EMOTIONS:
                conditional_count = int(conditional_counts[emotion])
                baseline_count = int(baseline_counts[poet][emotion])
                conditional = _round_probability(conditional_count, sample_count)
                baseline = _round_probability(baseline_count, poem_totals[poet])
                lift = round(conditional / baseline, 6) if baseline > 0 else None
                if lift is not None and math.isfinite(lift):
                    finite_lifts.append(lift)
                row = {
                    "poet": poet,
                    "emotion": emotion,
                    "sample_count": sample_count,
                    "level": level,
                    "conditional_count": conditional_count,
                    "conditional_denominator": sample_count,
                    "conditional": conditional,
                    "baseline_count": baseline_count,
                    "baseline_denominator": int(poem_totals[poet]),
                    "baseline": baseline,
                    "lift": lift,
                }
                emotion_rows.append(row)
                cells.append(row)

            nonzero_emotions = [
                row for row in emotion_rows if int(row["conditional_count"]) > 0
            ]
            nonzero_emotions.sort(
                key=lambda row: (
                    -float(row["conditional"]),
                    -(float(row["lift"]) if row["lift"] is not None else -1),
                    str(row["emotion"]),
                )
            )
            companions = [
                {
                    "name": name,
                    "count": int(count),
                    "rate": _round_probability(int(count), sample_count),
                }
                for name, count in companion_counts.most_common()
            ]
            poet_rows[poet] = {
                "poet": poet,
                "sample_count": sample_count,
                "level": level,
                "poem_total": int(poem_totals[poet]),
                "emotions": nonzero_emotions,
                "companions": companions,
                "records": records,
            }

        views[imagery] = {
            "imagery": imagery,
            "label": str(IMAGERY_RULES[imagery]["label"]),
            "description": str(IMAGERY_RULES[imagery]["description"]),
            "cells": cells,
            "poets": poet_rows,
            "max_lift": round(max(finite_lifts, default=1.0), 3),
            "matched_poem_count": sum(
                int(poet_rows[poet]["sample_count"]) for poet in TARGET_POETS
            ),
        }

    return {
        "poets": list(TARGET_POETS),
        "imagery": list(TARGET_IMAGERY),
        "emotions": list(EMOTIONS),
        "poem_totals": {poet: int(poem_totals[poet]) for poet in TARGET_POETS},
        "views": views,
        "summary": {
            "poet_count": len(TARGET_POETS),
            "poem_count": len(poems),
            "poems_per_poet": POEMS_PER_POET,
            "imagery_count": len(TARGET_IMAGERY),
            "emotion_count": len(EMOTIONS),
            "imagery_poem_hits": total_imagery_poem_hits,
            "evidence_line_count": total_evidence_lines,
        },
        "method": {
            "context_window": "命中意象的分句及前后各 1 个分句",
            "count_unit": "每首诗对同一意象、同一情感标签最多计 1 次",
            "thresholds": {"不排名": "<10", "探索": "10-29", "正式": ">=30"},
            "emotion_descriptions": {
                emotion: str(rule["description"])
                for emotion, rule in EMOTION_CONTEXT_RULES.items()
            },
        },
    }


def _chart_cells(payload: dict[str, object], imagery: str, metric: str) -> list[list[object]]:
    view = payload["views"][imagery]
    poets = list(payload["poets"])
    emotions = list(payload["emotions"])
    cells: list[list[object]] = []
    for row in view["cells"]:
        value = row[metric]
        cells.append(
            [
                emotions.index(row["emotion"]),
                poets.index(row["poet"]),
                value,
                row["conditional"],
                row["baseline"],
                row["lift"],
                row["sample_count"],
                row["level"],
                row["poet"],
                row["emotion"],
                imagery,
            ]
        )
    return cells


def build_heatmap(payload: dict[str, object]) -> HeatMap:
    default_imagery = "月"
    max_lift = max(2.0, float(payload["views"][default_imagery]["max_lift"]))
    chart = HeatMap(
        init_opts=opts.InitOpts(
            width="1240px",
            height="600px",
            chart_id=CHART_ID,
            bg_color="#ffffff",
        )
    )
    chart.add_xaxis(list(payload["emotions"]))
    chart.add_yaxis(
        "提升度 lift",
        list(payload["poets"]),
        _chart_cells(payload, default_imagery, "lift"),
        label_opts=opts.LabelOpts(
            is_show=True,
            position="inside",
            color="#102033",
            font_size=11,
            formatter=JsCode(
                "function(p){var v=p.value&&p.value[2];return v==null?'—':Number(v).toFixed(2);}"
            ),
        ),
    )
    chart.set_global_opts(
        legend_opts=opts.LegendOpts(is_show=False),
        tooltip_opts=opts.TooltipOpts(
            formatter=HEATMAP_TOOLTIP,
            is_confine=True,
            background_color="rgba(255,255,255,0.98)",
            border_color="#cbd5e1",
            textstyle_opts=opts.TextStyleOpts(color="#102033"),
        ),
        xaxis_opts=opts.AxisOpts(
            type_="category",
            position="top",
            axislabel_opts=opts.LabelOpts(
                interval=0,
                rotate=0,
                color="#334155",
                font_size=12,
                formatter=JsCode(
                    """
                    function(value) {
                        if (window.innerWidth > 560) { return value; }
                        var labels = {
                            '思乡怀人':'思乡',
                            '离别惜别':'离别',
                            '漂泊孤寂':'漂泊',
                            '忧国伤时':'忧国',
                            '豪迈旷达':'豪迈',
                            '欢愉闲适':'欢愉',
                            '哲思超越':'哲思',
                            '爱情相思':'爱情',
                            '悲愁伤逝':'悲愁'
                        };
                        return labels[value] || value;
                    }
                    """
                ),
            ),
            axisline_opts=opts.AxisLineOpts(
                linestyle_opts=opts.LineStyleOpts(color="#cbd5e1")
            ),
            splitarea_opts=opts.SplitAreaOpts(
                is_show=True,
                areastyle_opts=opts.AreaStyleOpts(color=["#ffffff", "#f8fafc"]),
            ),
        ),
        yaxis_opts=opts.AxisOpts(
            type_="category",
            axislabel_opts=opts.LabelOpts(color="#102033", font_size=13),
            axisline_opts=opts.AxisLineOpts(
                linestyle_opts=opts.LineStyleOpts(color="#cbd5e1")
            ),
            splitarea_opts=opts.SplitAreaOpts(
                is_show=True,
                areastyle_opts=opts.AreaStyleOpts(color=["#ffffff", "#f8fafc"]),
            ),
        ),
        visualmap_opts=opts.VisualMapOpts(
            min_=0,
            max_=max_lift,
            dimension=2,
            orient="horizontal",
            pos_left="center",
            pos_bottom="3%",
            range_color=["#e2e8f0", "#bae6fd", "#86efac", "#fde047", "#fb7185"],
            precision=2,
        ),
    )
    return chart


def _page_header(payload: dict[str, object]) -> str:
    summary = payload["summary"]
    return f"""
    <main class="imagery-page">
        <header class="hero">
            <div class="eyebrow">TANG–SONG IMAGERY LAB</div>
            <h1>同象异情：诗人如何写同一个意象</h1>
            <p>以月、酒、舟、雁、雨为观察入口，比较李白、杜甫、白居易、苏轼、陆游、李清照的局部语境情感。意象不预设固定情感，所有标签均由证据分句及其相邻语境触发。</p>
            <div class="metrics" aria-label="样本摘要">
                <div><span>精细样本</span><strong>{summary['poem_count']} 首</strong></div>
                <div><span>代表诗人</span><strong>{summary['poet_count']} 位</strong></div>
                <div><span>目标意象</span><strong>{summary['imagery_count']} 类</strong></div>
                <div><span>意象诗次</span><strong>{summary['imagery_poem_hits']} 次</strong></div>
            </div>
        </header>

        <section class="control-band" aria-label="比较维度">
            <div>
                <span class="control-label">意象</span>
                <div id="imagerySegment" class="segmented" role="group" aria-label="选择意象"></div>
            </div>
            <label class="metric-control" for="metricSelect">
                <span class="control-label">热力指标</span>
                <select id="metricSelect">
                    <option value="lift">提升度 lift</option>
                    <option value="conditional">条件概率 P(e|i,p)</option>
                </select>
            </label>
            <div class="threshold-legend" aria-label="样本等级">
                <span><i class="level-dot no-rank"></i>&lt;10 不排名</span>
                <span><i class="level-dot explore"></i>10–29 探索</span>
                <span><i class="level-dot formal"></i>≥30 正式</span>
            </div>
        </section>

        <section class="chart-panel" aria-labelledby="heatmapTitle">
            <div class="section-head">
                <div>
                    <span class="section-kicker">诗人 × 情感</span>
                    <h2 id="heatmapTitle">月意象的情感提升度</h2>
                    <p id="heatmapMeta"></p>
                </div>
                <div id="viewSampleStatus" class="sample-status"></div>
            </div>
    """


def _lower_sections() -> str:
    return """
        </section>

        <section class="evidence-section" aria-labelledby="evidenceTitle">
            <div class="section-head">
                <div>
                    <span class="section-kicker">语境审计</span>
                    <h2 id="evidenceTitle">伴随意象与证据诗句</h2>
                    <p>样本量、伴随意象、情感标签和原文证据使用同一统计口径。</p>
                </div>
            </div>
            <div id="evidenceTable" class="evidence-table-wrap"></div>
        </section>

        <section class="method-section" aria-labelledby="methodTitle">
            <div class="section-head">
                <div>
                    <span class="section-kicker">METHOD</span>
                    <h2 id="methodTitle">计算口径与限制</h2>
                </div>
            </div>
            <div class="formula-grid">
                <article>
                    <span>局部条件概率</span>
                    <strong>P(e|i,p) = N(i∩e,p) / N(i,p)</strong>
                    <p>某诗人含该意象的诗中，局部语境命中情感 e 的比例。同一诗可多标签，因此各比例之和不必为 100%。</p>
                </article>
                <article>
                    <span>诗人情感基线</span>
                    <strong>P(e|p) = N(e,p) / 20</strong>
                    <p>该诗人 20 首固定样本中命中情感 e 的比例，用来区分“诗人本来常写”与“该意象特别强化”。</p>
                </article>
                <article>
                    <span>意象情感提升度</span>
                    <strong>lift = P(e|i,p) / P(e|p)</strong>
                    <p>lift &gt; 1 表示该情感在此意象语境中高于诗人自身基线；基线为 0 时不计算提升度。</p>
                </article>
            </div>
            <div class="method-notes">
                <p><strong>语境窗口：</strong>意象所在分句及前后各一个分句。每首诗对同一意象、同一标签最多计一次。</p>
                <p><strong>样本等级：</strong>&lt;10 仅展示证据、不参与排名；10–29 为探索结果；≥30 才可作为正式比较。本页每位诗人固定取语料中前 20 首作为可比样本（扩充语料不进入本页），因此不会出现“正式”等级。</p>
                <p><strong>解释边界：</strong>规则分析反映当前样本中的文本语境，不等同于诗人的真实心理，也不能替代作品注释和文学史研究。</p>
            </div>
        </section>
    </main>
    """


PAGE_CSS = """
<style id="imagery-emotion-page-style">
:root {
    --bg: #eef3f7;
    --panel: #ffffff;
    --ink: #102033;
    --muted: #607083;
    --line: #d7e0e9;
    --teal: #0f766e;
    --teal-soft: #dff4ef;
    --amber: #b45309;
    --rose: #be123c;
    --green: #15803d;
}
* { box-sizing: border-box; }
html, body { margin: 0; min-height: 100%; background: var(--bg); color: var(--ink); }
body { font-family: "Microsoft YaHei", "PingFang SC", "Segoe UI", Arial, sans-serif; }
.imagery-page { width: min(1240px, calc(100vw - 32px)); margin: 0 auto; padding: 18px 0 48px; }
.hero { padding: 30px; border: 1px solid #18354a; border-radius: 8px; background: #102c3a; color: #f8fafc; }
.eyebrow, .section-kicker, .control-label { display: block; font-size: 12px; font-weight: 800; letter-spacing: 0; }
.eyebrow { color: #6ee7d8; }
.hero h1 { margin: 12px 0 10px; font-size: 34px; line-height: 1.2; letter-spacing: 0; }
.hero > p { max-width: 850px; margin: 0; color: #c8d5df; font-size: 15px; line-height: 1.8; }
.metrics { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin-top: 24px; }
.metrics > div { min-height: 76px; padding: 13px 15px; border: 1px solid rgba(255,255,255,.18); border-radius: 6px; background: rgba(255,255,255,.07); }
.metrics span { display: block; color: #b7c7d3; font-size: 12px; }
.metrics strong { display: block; margin-top: 7px; font-size: 22px; }
.control-band, .chart-panel, .evidence-section, .method-section { margin-top: 16px; border: 1px solid var(--line); border-radius: 8px; background: var(--panel); }
.control-band { display: grid; grid-template-columns: minmax(330px, 1fr) 230px auto; gap: 20px; align-items: end; padding: 15px 17px; }
.control-label { margin-bottom: 7px; color: var(--muted); }
.segmented { display: inline-grid; grid-template-columns: repeat(5, 48px); border: 1px solid #b9c7d4; border-radius: 6px; overflow: hidden; }
.segmented button { width: 48px; min-height: 38px; padding: 0; border: 0; border-right: 1px solid #b9c7d4; background: #fff; color: #334155; font: inherit; font-weight: 800; cursor: pointer; }
.segmented button:last-child { border-right: 0; }
.segmented button.is-active { background: var(--teal); color: #fff; }
.segmented button:focus-visible, select:focus-visible, summary:focus-visible { outline: 3px solid #5eead4; outline-offset: 2px; }
.metric-control { display: block; }
select { width: 100%; min-height: 40px; padding: 0 34px 0 11px; border: 1px solid #b9c7d4; border-radius: 6px; background: #fff; color: var(--ink); font: inherit; }
.threshold-legend { display: flex; flex-wrap: wrap; gap: 8px 12px; align-items: center; padding-bottom: 8px; color: var(--muted); font-size: 12px; }
.threshold-legend span { white-space: nowrap; }
.level-dot { display: inline-block; width: 8px; height: 8px; margin-right: 5px; border-radius: 50%; }
.no-rank { background: #94a3b8; } .explore { background: var(--amber); } .formal { background: var(--green); }
.section-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; padding: 18px 20px 14px; border-bottom: 1px solid var(--line); }
.section-kicker { color: var(--teal); }
.section-head h2 { margin: 5px 0 0; font-size: 21px; line-height: 1.35; letter-spacing: 0; }
.section-head p { margin: 6px 0 0; color: var(--muted); font-size: 13px; line-height: 1.65; }
.sample-status { flex: 0 0 auto; padding: 7px 10px; border-radius: 6px; background: #fff7ed; color: var(--amber); font-size: 12px; font-weight: 800; }
#imagery_emotion_heatmap { width: 100% !important; height: 600px !important; }
.evidence-table-wrap { overflow-x: auto; }
.evidence-table { width: 100%; min-width: 1000px; border-collapse: collapse; }
.evidence-table th, .evidence-table td { padding: 13px 14px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; }
.evidence-table th { color: #475569; background: #f8fafc; font-size: 12px; }
.evidence-table td { color: #334155; font-size: 13px; line-height: 1.65; }
.evidence-table tbody tr:last-child td { border-bottom: 0; }
.poet-name { font-size: 15px; color: var(--ink); }
.sample-badge { display: inline-flex; margin-top: 5px; padding: 2px 7px; border: 1px solid #cbd5e1; border-radius: 999px; color: #64748b; font-size: 11px; }
.sample-badge.explore { border-color: #fed7aa; background: #fff7ed; color: var(--amber); }
.sample-badge.formal { border-color: #bbf7d0; background: #f0fdf4; color: var(--green); }
.pill-list { display: flex; flex-wrap: wrap; gap: 5px; max-width: 310px; }
.pill { display: inline-flex; align-items: center; min-height: 25px; padding: 3px 7px; border: 1px solid #cbd5e1; border-radius: 999px; background: #fff; color: #334155; font-size: 12px; white-space: nowrap; }
.pill b { margin-left: 4px; color: var(--teal); }
.empty { color: #94a3b8; }
details { max-width: 420px; }
summary { color: var(--teal); font-weight: 800; cursor: pointer; }
.evidence-list { display: grid; gap: 8px; margin-top: 9px; }
.evidence-item { padding-left: 10px; border-left: 2px solid #99f6e4; }
.evidence-item strong { display: block; color: var(--ink); font-size: 12px; }
.evidence-item q { display: block; margin-top: 3px; color: #475569; }
.evidence-item small { display: block; margin-top: 3px; color: #76869a; }
.formula-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 0; }
.formula-grid article { padding: 18px 20px; border-right: 1px solid var(--line); }
.formula-grid article:last-child { border-right: 0; }
.formula-grid span { color: var(--teal); font-size: 12px; font-weight: 800; }
.formula-grid strong { display: block; margin-top: 7px; font-family: Consolas, monospace; font-size: 15px; overflow-wrap: anywhere; }
.formula-grid p, .method-notes p { margin: 8px 0 0; color: var(--muted); font-size: 13px; line-height: 1.7; }
.method-notes { padding: 15px 20px 19px; border-top: 1px solid var(--line); background: #f8fafc; }
.method-notes p:first-child { margin-top: 0; }
@media (max-width: 900px) {
    .control-band { grid-template-columns: 1fr 1fr; }
    .threshold-legend { grid-column: 1 / -1; }
    .formula-grid { grid-template-columns: 1fr; }
    .formula-grid article { border-right: 0; border-bottom: 1px solid var(--line); }
    .formula-grid article:last-child { border-bottom: 0; }
}
@media (max-width: 640px) {
    .imagery-page { width: calc(100vw - 20px); padding-top: 10px; }
    .hero { padding: 20px 17px; }
    .hero h1 { font-size: 28px; }
    .metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .control-band { grid-template-columns: 1fr; gap: 14px; }
    .threshold-legend { grid-column: auto; }
    .section-head { display: block; padding: 15px; }
    .sample-status { display: inline-flex; margin-top: 10px; }
    #imagery_emotion_heatmap { height: 560px !important; }
}
</style>
"""


PAGE_SCRIPT = """
<script id="imagery-emotion-interaction">
(function () {
    'use strict';
    const data = window.IMAGERY_EMOTION_DATA;
    const state = { imagery: '月', metric: 'lift' };
    const chartElement = document.getElementById('imagery_emotion_heatmap');
    const chart = window.echarts && chartElement ? echarts.getInstanceByDom(chartElement) : null;
    const imagerySegment = document.getElementById('imagerySegment');
    const metricSelect = document.getElementById('metricSelect');
    const heatmapTitle = document.getElementById('heatmapTitle');
    const heatmapMeta = document.getElementById('heatmapMeta');
    const sampleStatus = document.getElementById('viewSampleStatus');
    const evidenceTable = document.getElementById('evidenceTable');

    function esc(value) {
        return String(value == null ? '' : value).replace(/[&<>"']/g, function (ch) {
            return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch];
        });
    }
    function pct(value) { return (Number(value || 0) * 100).toFixed(1) + '%'; }
    function lift(value) { return value == null ? '—' : Number(value).toFixed(2); }
    function badgeClass(level) {
        if (level === '正式') return 'formal';
        if (level === '探索') return 'explore';
        return 'no-rank';
    }
    function metricValue(cell) { return cell[state.metric]; }
    function metricLabel() {
        return state.metric === 'lift' ? '情感提升度 lift' : '条件概率 P(e|i,p)';
    }
    function chartData(view) {
        return view.cells.map(function (cell) {
            const value = metricValue(cell);
            return {
                value: [
                    data.emotions.indexOf(cell.emotion), data.poets.indexOf(cell.poet), value,
                    cell.conditional, cell.baseline, cell.lift, cell.sample_count, cell.level,
                    cell.poet, cell.emotion, state.imagery
                ],
                itemStyle: { opacity: cell.level === '不排名' ? 0.48 : (cell.level === '探索' ? 0.82 : 1) }
            };
        });
    }
    function visualMax(view) {
        return state.metric === 'lift' ? Math.max(2, Number(view.max_lift || 1)) : 1;
    }
    function renderChart(view) {
        if (!chart) return;
        const isLift = state.metric === 'lift';
        chart.setOption({
            series: [{
                name: metricLabel(),
                data: chartData(view),
                label: {
                    show: true,
                    color: '#102033',
                    fontSize: 11,
                    formatter: function (p) {
                        const v = p.value && p.value[2];
                        if (v == null) return '—';
                        return isLift ? Number(v).toFixed(2) : Math.round(Number(v) * 100) + '%';
                    }
                }
            }],
            visualMap: [{
                min: 0,
                max: visualMax(view),
                dimension: 2,
                precision: 2,
                text: isLift ? ['相对基线更强', '相对基线更弱'] : ['局部占比高', '局部占比低'],
                inRange: { color: ['#e2e8f0', '#bae6fd', '#86efac', '#fde047', '#fb7185'] }
            }]
        });
        chart.resize();
    }
    function renderSegment() {
        imagerySegment.innerHTML = data.imagery.map(function (imagery) {
            const active = imagery === state.imagery ? ' is-active' : '';
            return '<button type="button" class="' + active + '" data-imagery="' + esc(imagery) +
                '" aria-pressed="' + (imagery === state.imagery ? 'true' : 'false') + '">' + esc(imagery) + '</button>';
        }).join('');
        Array.from(imagerySegment.querySelectorAll('[data-imagery]')).forEach(function (button) {
            button.addEventListener('click', function () {
                state.imagery = button.getAttribute('data-imagery');
                render();
            });
        });
    }
    function emotionPills(row) {
        if (!row.emotions.length) return '<span class="empty">局部语境未命中规则标签</span>';
        return '<div class="pill-list">' + row.emotions.map(function (item) {
            const detail = state.metric === 'lift' ? lift(item.lift) : pct(item.conditional);
            return '<span class="pill">' + esc(item.emotion) + '<b>' + detail + '</b></span>';
        }).join('') + '</div>';
    }
    function companionPills(row) {
        if (!row.companions.length) return '<span class="empty">无伴随意象</span>';
        return '<div class="pill-list">' + row.companions.slice(0, 8).map(function (item) {
            return '<span class="pill">' + esc(item.name) + '<b>' + esc(item.count) + '</b></span>';
        }).join('') + '</div>';
    }
    function evidenceDetails(row) {
        if (!row.records.length) return '<span class="empty">当前样本无此意象</span>';
        return '<details><summary>' + row.records.length + ' 首诗 / 展开证据</summary><div class="evidence-list">' +
            row.records.map(function (record) {
                const quote = record.evidence.map(function (e) { return e.line; }).join(' / ');
                const labels = record.emotions.length ? record.emotions.join('、') : '语境未判定';
                return '<div class="evidence-item"><strong>《' + esc(record.title) + '》</strong>' +
                    '<q>' + esc(quote) + '</q><small>标签：' + esc(labels) + '</small></div>';
            }).join('') + '</div></details>';
    }
    function renderEvidence(view) {
        const rows = data.poets.map(function (poet) {
            const row = view.poets[poet];
            const levelClass = badgeClass(row.level);
            const label = row.level === '不排名' ? '语境标签（不排名）' : '主要语境标签';
            return '<tr><td><strong class="poet-name">' + esc(poet) + '</strong><br/>' +
                '<span class="sample-badge ' + levelClass + '">' + esc(row.sample_count) + ' 首 · ' + esc(row.level) + '</span></td>' +
                '<td>' + companionPills(row) + '</td>' +
                '<td><small>' + esc(label) + '</small>' + emotionPills(row) + '</td>' +
                '<td>' + evidenceDetails(row) + '</td></tr>';
        }).join('');
        evidenceTable.innerHTML = '<table class="evidence-table"><thead><tr><th>诗人 / 样本等级</th>' +
            '<th>局部伴随意象（诗次）</th><th>' + esc(metricLabel()) + '</th><th>原文证据</th></tr></thead><tbody>' + rows + '</tbody></table>';
    }
    function renderMeta(view) {
        const levels = data.poets.reduce(function (acc, poet) {
            const level = view.poets[poet].level;
            acc[level] = (acc[level] || 0) + 1;
            return acc;
        }, {});
        heatmapTitle.textContent = state.imagery + '意象的' + metricLabel();
        heatmapMeta.textContent = view.description + ' 当前共命中 ' + view.matched_poem_count + ' 个“诗人—诗作”样本。';
        sampleStatus.textContent = '不排名 ' + (levels['不排名'] || 0) + ' 位 · 探索 ' + (levels['探索'] || 0) + ' 位 · 正式 ' + (levels['正式'] || 0) + ' 位';
    }
    function render() {
        const view = data.views[state.imagery];
        renderSegment();
        renderMeta(view);
        renderChart(view);
        renderEvidence(view);
    }
    metricSelect.addEventListener('change', function () {
        state.metric = metricSelect.value === 'conditional' ? 'conditional' : 'lift';
        render();
    });
    window.addEventListener('resize', function () { if (chart) chart.resize(); });
    render();
}());
</script>
"""


def polish_page(out: Path, payload: dict[str, object]) -> None:
    html = out.read_text(encoding="utf-8")
    html, title_replacements = re.subn(
        r"<title\b[^>]*>.*?</title>",
        "<title>同一意象的诗人情感差异</title>",
        html,
        count=1,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if title_replacements == 0:
        html = html.replace("</head>", "<title>同一意象的诗人情感差异</title>\n</head>", 1)
    if not re.search(r"<link\b[^>]*\brel=[\"'](?:shortcut )?icon[\"']", html, re.IGNORECASE):
        html = html.replace("</head>", '<link rel="icon" href="data:,">\n</head>', 1)
    viewport = '<meta name="viewport" content="width=device-width, initial-scale=1.0">'
    if viewport not in html:
        html = html.replace(
            '<meta charset="UTF-8">',
            f'<meta charset="UTF-8">\n    {viewport}',
            1,
        )
    html = html.replace("</head>", f"{PAGE_CSS}\n</head>", 1)
    html, body_replacements = re.subn(
        r"(<body\b[^>]*>)",
        lambda match: f"{match.group(1)}\n{_page_header(payload)}",
        html,
        count=1,
        flags=re.IGNORECASE,
    )
    if body_replacements != 1:
        raise RuntimeError("未找到 HTML body 起始标签，无法注入页面头部")

    chart_pattern = re.compile(
        rf'(<div id="{re.escape(CHART_ID)}"\s+class="chart-container"[^>]*></div>)'
    )
    if not chart_pattern.search(html):
        raise RuntimeError("未找到 Pyecharts 热力图容器，无法注入证据区块")
    html = chart_pattern.sub(r"\1\n" + _lower_sections(), html, count=1)

    data_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace(
        "</", "<\\/"
    )
    data_script = (
        '<script id="imagery-emotion-data">'
        f"window.IMAGERY_EMOTION_DATA={data_json};"
        "</script>"
    )
    html = html.replace("</body>", f"{data_script}\n{PAGE_SCRIPT}\n</body>", 1)
    html = inject_index_backlink(html)
    out.write_text(html, encoding="utf-8")


def render() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = build_payload()
    chart = build_heatmap(payload)
    chart.render(str(OUTPUT_HTML))
    localize_pyecharts_assets(OUTPUT_HTML, OUTPUT_DIR)
    polish_page(OUTPUT_HTML, payload)
    print(
        "  [ok] saved "
        f"{OUTPUT_HTML}  ({payload['summary']['poem_count']} 首 / "
        f"{payload['summary']['imagery_poem_hits']} 意象诗次)"
    )


if __name__ == "__main__":
    render()
