"""可视化 18：语料、创作时空与来源证据质量看板。"""
from __future__ import annotations

import csv
import hashlib
import json
import sys
from collections import Counter
from html import escape
from pathlib import Path

from pyecharts import options as opts
from pyecharts.charts import Bar, Page, Pie

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config import OUTPUT_DIR
from viz_assets import localize_pyecharts_assets, write_premium_chart_page

POEMS_JSON = ROOT / "data" / "poems.json"
JOURNEYS_JSON = ROOT / "data" / "reviewed" / "poet_journeys.json"
CONTEXTS_CSV = ROOT / "data" / "reviewed" / "verified_poem_contexts.csv"
CANDIDATES_JSONL = ROOT / "data" / "candidates" / "poem_background_candidates.jsonl"
COLLECTION_STATUS_JSONL = ROOT / "data" / "candidates" / "background_collection_status.jsonl"
POET_STATUS_JSONL = ROOT / "data" / "candidates" / "poet_identity_status.jsonl"
RICH_BACKGROUNDS_JSONL = ROOT / "data" / "reviewed" / "verified_poem_backgrounds.jsonl"
TARGET_POETS = ("李白", "杜甫", "白居易", "苏轼", "陆游", "李清照")
MAX_EVIDENCE_CHARS = 160

STATUS_LABELS = {
    "collected": "已采集",
    "extracted": "已结构化",
    "needs_review": "待审核",
    "approved": "已批准",
    "rejected": "已驳回",
    "disputed": "有争议",
    "insufficient": "证据不足",
    "offline_cache_miss": "离线缓存缺失",
    "blocked_by_policy": "政策阻止",
    "pending_collection": "待采集",
}


def load_poems() -> list[dict[str, object]]:
    return json.loads(POEMS_JSON.read_text(encoding="utf-8"))


def flatten_journeys(payload: object) -> list[dict[str, object]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if not isinstance(payload, dict):
        return []
    if isinstance(payload.get("journeys"), list):
        return payload["journeys"]
    rows: list[dict[str, object]] = []
    for poet_row in payload.get("poets", []):
        if not isinstance(poet_row, dict):
            continue
        poet = poet_row.get("poet") or poet_row.get("name")
        for event in poet_row.get(
            "events",
            poet_row.get("nodes", poet_row.get("stops", [])),
        ):
            if isinstance(event, dict):
                item = dict(event)
                item.setdefault("poet", poet)
                rows.append(item)
    return rows


def load_journeys() -> list[dict[str, object]]:
    if not JOURNEYS_JSON.exists():
        return []
    payload = json.loads(JOURNEYS_JSON.read_text(encoding="utf-8-sig"))
    return flatten_journeys(payload)


def load_contexts() -> list[dict[str, str]]:
    if not CONTEXTS_CSV.exists():
        return []
    with CONTEXTS_CSV.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def load_jsonl(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    rows: list[dict[str, object]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{line_no} 不是 JSON 对象")
        rows.append(value)
    return rows


def poem_hash(row: dict[str, object]) -> str:
    digest = str(row.get("body_hash") or "").strip()
    if digest:
        return digest
    return hashlib.sha256(str(row.get("body") or "").encode("utf-8")).hexdigest()


def status_summary(counts: Counter[str]) -> str:
    return "、".join(
        f"{STATUS_LABELS.get(status, status)} {count}"
        for status, count in sorted(counts.items())
    ) or "暂无记录"


def pipeline_stats(poems: list[dict[str, object]]) -> dict[str, object]:
    candidates = load_jsonl(CANDIDATES_JSONL)
    collection_rows = load_jsonl(COLLECTION_STATUS_JSONL)
    identity_rows = load_jsonl(POET_STATUS_JSONL)
    rich_rows = load_jsonl(RICH_BACKGROUNDS_JSONL)

    core_hashes = {
        poem_hash(row)
        for row in poems
        if str(row.get("poet") or row.get("author") or "") in TARGET_POETS
    }
    attempted_core = {
        str((row.get("poem_key") or {}).get("body_hash") or "")
        for row in collection_rows
        if isinstance(row.get("poem_key"), dict)
        and str((row.get("poem_key") or {}).get("body_hash") or "") in core_hashes
    }
    corpus_poets = {
        str(row.get("poet") or row.get("author") or "")
        for row in poems
        if row.get("poet") or row.get("author")
    }
    identity_names = {
        str(row.get("poet") or "")
        for row in identity_rows
        if str(row.get("poet") or "") in corpus_poets
    }
    identity_attempted = {
        str(row.get("poet") or "")
        for row in identity_rows
        if row.get("status") not in {"", "pending_collection"}
        and str(row.get("poet") or "") in corpus_poets
    }
    identity_resolved = {
        str(row.get("poet") or "")
        for row in identity_rows
        if str(row.get("poet") or "") in corpus_poets
        and (
            str(row.get("status") or "") in {"ok", "matched", "found", "success"}
            or bool(row.get("matches"))
        )
    }

    candidate_statuses = Counter(str(row.get("status") or "unknown") for row in candidates)
    collection_statuses = Counter(str(row.get("status") or "unknown") for row in collection_rows)
    identity_statuses = Counter(str(row.get("status") or "unknown") for row in identity_rows)
    boundary_complete = [
        row
        for row in candidates
        if len(str(row.get("evidence_excerpt") or "")) <= MAX_EVIDENCE_CHARS
        and bool(str(row.get("license_note") or "").strip())
    ]
    approved_candidates = [row for row in candidates if row.get("status") == "approved"]

    def evidence_complete(row: dict[str, object]) -> bool:
        return bool(
            str(row.get("source_name") or "").strip()
            and str(row.get("evidence_excerpt") or "").strip()
            and len(str(row.get("evidence_excerpt") or "")) <= MAX_EVIDENCE_CHARS
            and str(row.get("source_grade") or "") in {"A", "B", "C", "D"}
            and str(row.get("reviewer") or "").strip()
            and str(row.get("reviewed_at") or "").strip()
            and str(row.get("source_locator") or row.get("source_url") or "").strip()
            and isinstance(row.get("confidence"), (int, float))
        )

    approved_complete = [row for row in approved_candidates if evidence_complete(row)]
    approved_poems = {
        str((row.get("poem_key") or {}).get("body_hash") or "")
        for row in approved_candidates
        if isinstance(row.get("poem_key"), dict)
    }
    publication_ready = [row for row in rich_rows if row.get("publication_ready") is True]
    return {
        "candidates": len(candidates),
        "candidate_statuses": candidate_statuses,
        "candidate_boundary_complete": len(boundary_complete),
        "approved_candidates": len(approved_candidates),
        "approved_evidence_complete": len(approved_complete),
        "approved_poems": len(approved_poems),
        "core_total": len(core_hashes),
        "core_attempted": len(attempted_core),
        "collection_statuses": collection_statuses,
        "identity_total": len(corpus_poets),
        "identity_covered": len(identity_names),
        "identity_attempted": len(identity_attempted),
        "identity_resolved": len(identity_resolved),
        "identity_statuses": identity_statuses,
        "rich_total": len(rich_rows),
        "rich_partial": len(rich_rows) - len(publication_ready),
        "publication_ready": len(publication_ready),
    }


def approved(row: dict[str, object]) -> bool:
    status = str(row.get("status") or row.get("review_status") or "approved")
    return status in {"approved", "reviewed", "published"}


def make_dynasty_bar(poems: list[dict[str, object]]) -> Bar:
    counts = Counter(str(row.get("dynasty") or "未知") for row in poems)
    poet_count = len(
        {str(row.get("poet") or row.get("author") or "") for row in poems}
    )
    labels = ["唐", "宋", "未知"]
    values = [counts.get(label, 0) for label in labels]
    chart = (
        Bar(init_opts=opts.InitOpts(width="1180px", height="390px"))
        .add_xaxis(labels)
        .add_yaxis(
            "作品数",
            values,
            category_gap="52%",
            itemstyle_opts=opts.ItemStyleOpts(color="#22d3ee"),
            label_opts=opts.LabelOpts(is_show=True, position="top"),
        )
        .set_global_opts(
            title_opts=opts.TitleOpts(
                title="基础爬虫语料",
                subtitle=f"{poet_count} 位诗人的批量语料与精细考证数据分层使用",
                pos_left="6%",
                pos_top="4%",
                title_textstyle_opts=opts.TextStyleOpts(
                    color="#f8fafc", font_size=20, font_weight="bold"
                ),
                subtitle_textstyle_opts=opts.TextStyleOpts(
                    color="#94a3b8", font_size=12
                ),
            ),
            legend_opts=opts.LegendOpts(
                pos_bottom="3%",
                textstyle_opts=opts.TextStyleOpts(color="#94a3b8"),
            ),
            yaxis_opts=opts.AxisOpts(
                name="作品数",
                name_textstyle_opts=opts.TextStyleOpts(color="#94a3b8"),
                axislabel_opts=opts.LabelOpts(color="#94a3b8"),
            ),
            xaxis_opts=opts.AxisOpts(
                axislabel_opts=opts.LabelOpts(color="#94a3b8")
            ),
        )
    )
    chart.options["grid"] = opts.GridOpts(
        pos_top="28%", pos_left="14%", pos_right="9%", pos_bottom="20%"
    ).opts
    return chart


def make_target_bar(poems: list[dict[str, object]]) -> Bar:
    counts = Counter(
        str(row.get("poet") or row.get("author") or "")
        for row in poems
    )
    chart = (
        Bar(init_opts=opts.InitOpts(width="1180px", height="420px"))
        .add_xaxis(list(TARGET_POETS))
        .add_yaxis(
            "现有作品",
            [counts.get(poet, 0) for poet in TARGET_POETS],
            itemstyle_opts=opts.ItemStyleOpts(color="#a78bfa"),
            label_opts=opts.LabelOpts(is_show=True, position="top"),
        )
        .set_global_opts(
            title_opts=opts.TitleOpts(
                title="六位精细研究诗人",
                subtitle="作品文本覆盖不等于创作时间地点覆盖",
                pos_left="6%",
                pos_top="4%",
                title_textstyle_opts=opts.TextStyleOpts(
                    color="#f8fafc", font_size=20, font_weight="bold"
                ),
                subtitle_textstyle_opts=opts.TextStyleOpts(
                    color="#94a3b8", font_size=12
                ),
            ),
            legend_opts=opts.LegendOpts(
                pos_bottom="3%",
                textstyle_opts=opts.TextStyleOpts(color="#94a3b8"),
            ),
            xaxis_opts=opts.AxisOpts(
                axislabel_opts=opts.LabelOpts(rotate=0, color="#94a3b8")
            ),
            yaxis_opts=opts.AxisOpts(
                axislabel_opts=opts.LabelOpts(color="#94a3b8")
            ),
        )
    )
    chart.options["grid"] = opts.GridOpts(
        pos_top="27%", pos_left="12%", pos_right="8%", pos_bottom="20%"
    ).opts
    return chart


def make_grade_pie(
    journeys: list[dict[str, object]],
    contexts: list[dict[str, str]],
) -> Pie:
    grades = Counter()
    for row in [*journeys, *contexts]:
        if approved(row):
            grades[
                str(row.get("fact_grade") or row.get("source_level") or "C").upper()[:1]
            ] += 1
    pairs = [(grade, grades.get(grade, 0)) for grade in ("A", "B", "C", "D")]
    grade_summary = " / ".join(f"{grade} {grades.get(grade, 0)}" for grade in ("A", "B", "C", "D"))
    return (
        Pie(init_opts=opts.InitOpts(width="1180px", height="440px"))
        .add(
            "审核记录",
            pairs,
            radius=["38%", "68%"],
            center=["50%", "60%"],
            label_opts=opts.LabelOpts(is_show=False),
        )
        .set_global_opts(
            title_opts=opts.TitleOpts(
                title="来源等级",
                subtitle=f"{grade_summary}（A/B发布，C推定，D排除）",
                pos_left="6%",
                pos_top="4%",
                title_textstyle_opts=opts.TextStyleOpts(
                    color="#f8fafc", font_size=20, font_weight="bold"
                ),
                subtitle_textstyle_opts=opts.TextStyleOpts(
                    color="#94a3b8", font_size=12
                ),
            ),
            legend_opts=opts.LegendOpts(
                pos_top="18%",
                pos_left="center",
                textstyle_opts=opts.TextStyleOpts(color="#cbd5e1"),
            ),
        )
    )


def make_candidate_status_bar(stats: dict[str, object]) -> Bar:
    counts = stats["candidate_statuses"]
    assert isinstance(counts, Counter)
    statuses = (
        "collected",
        "extracted",
        "needs_review",
        "approved",
        "rejected",
        "disputed",
        "insufficient",
    )
    chart = (
        Bar(init_opts=opts.InitOpts(width="1180px", height="420px"))
        .add_xaxis([STATUS_LABELS[status] for status in statuses])
        .add_yaxis(
            "候选主张",
            [counts.get(status, 0) for status in statuses],
            category_gap="46%",
            itemstyle_opts=opts.ItemStyleOpts(color="#0f766e"),
            label_opts=opts.LabelOpts(is_show=True, position="top"),
        )
        .set_global_opts(
            title_opts=opts.TitleOpts(
                title="候选审核状态",
                subtitle="仅 approved 主张进入公开富背景",
                pos_left="6%",
                pos_top="4%",
                title_textstyle_opts=opts.TextStyleOpts(
                    color="#f8fafc", font_size=20, font_weight="bold"
                ),
                subtitle_textstyle_opts=opts.TextStyleOpts(color="#94a3b8", font_size=12),
            ),
            legend_opts=opts.LegendOpts(
                pos_bottom="3%",
                textstyle_opts=opts.TextStyleOpts(color="#94a3b8"),
            ),
            xaxis_opts=opts.AxisOpts(axislabel_opts=opts.LabelOpts(color="#94a3b8")),
            yaxis_opts=opts.AxisOpts(axislabel_opts=opts.LabelOpts(color="#94a3b8")),
        )
    )
    chart.options["grid"] = opts.GridOpts(
        pos_top="28%", pos_left="12%", pos_right="8%", pos_bottom="20%"
    ).opts
    return chart


def quality_rows(
    poems: list[dict[str, object]],
    journeys: list[dict[str, object]],
    contexts: list[dict[str, str]],
    stats: dict[str, object],
) -> list[tuple[str, int, int, str]]:
    target_poems = [
        row
        for row in poems
        if str(row.get("poet") or row.get("author") or "") in TARGET_POETS
    ]
    approved_journeys = [row for row in journeys if approved(row)]
    approved_contexts = [row for row in contexts if approved(row)]
    return [
        (
            "基础诗词",
            len(poems),
            sum(bool(row.get("source_url")) for row in poems),
            "已有历史爬虫数据缺少逐条 URL，重新抓取后逐步补齐",
        ),
        (
            "六位诗人作品",
            len(target_poems),
            sum(bool(row.get("source_url")) for row in target_poems),
            "用于同意象语境分析",
        ),
        (
            "核心作品采集尝试",
            int(stats["core_total"]),
            int(stats["core_attempted"]),
            f"采集状态：{status_summary(stats['collection_statuses'])}",
        ),
        (
            "诗人身份处理状态",
            int(stats["identity_total"]),
            int(stats["identity_covered"]),
            (
                f"已尝试 {stats['identity_attempted']} 位，成功解析 {stats['identity_resolved']} 位；"
                f"状态：{status_summary(stats['identity_statuses'])}"
            ),
        ),
        (
            "背景候选版权边界",
            int(stats["candidates"]),
            int(stats["candidate_boundary_complete"]),
            f"第三方证据短引不超过 {MAX_EVIDENCE_CHARS} 字，并记录使用边界",
        ),
        (
            "批准主张证据完整性",
            int(stats["approved_candidates"]),
            int(stats["approved_evidence_complete"]),
            f"覆盖 {stats['approved_poems']} 首作品；需有来源、定位、等级、置信度、审核人和审核时间",
        ),
        (
            "富背景完整度",
            int(stats["rich_total"]),
            int(stats["publication_ready"]),
            f"部分记录 {stats['rich_partial']} 条；完整版还需120–220字背景、自有逐句译注、注释和赏析",
        ),
        (
            "可发布完整版",
            60,
            int(stats["publication_ready"]),
            "首版验收目标不少于60条；未完成内容不以候选或模型草稿充数",
        ),
        (
            "审核创作背景",
            len(approved_contexts),
            sum(bool(row.get("source_url")) for row in approved_contexts),
            "只用于创作活动分布，不使用诗中提及地",
        ),
        (
            "审核行旅节点",
            len(approved_journeys),
            sum(bool(row.get("source_url")) for row in approved_journeys),
            "连线只表示时间顺序，不代表真实道路",
        ),
    ]


def inject_quality_table(path: Path, rows: list[tuple[str, int, int, str]]) -> None:
    html = path.read_text(encoding="utf-8")
    body_rows = "".join(
        "<tr>"
        f"<td>{escape(name)}</td><td>{total}</td><td>{sourced}</td>"
        f"<td>{(sourced / total * 100 if total else 0):.1f}%</td><td>{escape(note)}</td>"
        "</tr>"
        for name, total, sourced, note in rows
    )
    panel = f"""
    <section class="quality-method">
      <h2>候选审核状态与覆盖率</h2>
      <div class="quality-table-wrap">
        <table>
          <thead><tr><th>数据层</th><th>总量</th><th>完成/合规</th><th>完成率</th><th>用途与限制</th></tr></thead>
          <tbody>{body_rows}</tbody>
        </table>
      </div>
      <p>完成率用于暴露缺口，不把离线缓存缺失伪装成“未找到”。正式页面中的生平、行旅与创作地点只读取批准数据，候选层不会进入公开页面。</p>
    </section>
    <style>
      .quality-method {{
        width: min(1180px, calc(100% - 32px));
        margin: 22px auto 42px;
        padding: 22px;
        box-sizing: border-box;
        border: 1px solid rgba(148,163,184,.28);
        background: rgba(15,23,42,.76);
        border-radius: 8px;
        color: #dbeafe;
      }}
      .quality-method h2 {{ margin: 0 0 14px; font-size: 20px; letter-spacing: 0; }}
      .quality-table-wrap {{ overflow-x: auto; }}
      .quality-method table {{ width: 100%; border-collapse: collapse; min-width: 760px; }}
      .quality-method th, .quality-method td {{
        padding: 12px 10px; border-bottom: 1px solid rgba(148,163,184,.2); text-align: left;
      }}
      .quality-method th {{ color: #67e8f9; font-weight: 700; }}
      .quality-method p {{ color: #94a3b8; line-height: 1.7; margin: 16px 0 0; }}
    </style>
    """
    html = html.replace("</body>", f"{panel}</body>")
    path.write_text(html, encoding="utf-8")


def render() -> None:
    poems = load_poems()
    journeys = load_journeys()
    contexts = load_contexts()
    stats = pipeline_stats(poems)
    rows = quality_rows(poems, journeys, contexts, stats)
    approved_journeys = sum(approved(row) for row in journeys)
    approved_contexts = sum(approved(row) for row in contexts)

    page = Page(
        page_title="诗行万里 · 数据质量与来源覆盖",
        layout=Page.SimplePageLayout,
    )
    page.add(
        make_dynasty_bar(poems),
        make_target_bar(poems),
        make_grade_pie(journeys, contexts),
        make_candidate_status_bar(stats),
    )
    OUTPUT_DIR.mkdir(exist_ok=True)
    out = OUTPUT_DIR / "18_数据质量与来源覆盖.html"
    page.render(str(out))
    localize_pyecharts_assets(out, OUTPUT_DIR)
    write_premium_chart_page(
        out,
        page_key="data-quality",
        eyebrow="DATA QUALITY / EVIDENCE",
        title="数据质量与来源覆盖",
        subtitle="把基础语料、采集尝试、审核候选与批准发布分层展示，主动暴露来源、证据和完成度缺口。",
        metrics=[
            ("核心采集尝试", f"{stats['core_attempted']} / {stats['core_total']} 首"),
            ("身份处理状态", f"{stats['identity_covered']} / {stats['identity_total']} 位"),
            ("批准富背景", f"{stats['rich_total']} 条"),
            ("可发布完整版", f"{stats['publication_ready']} / 60 条"),
        ],
        note="当前富背景均为已批准的部分记录；距离60条完整版验收线仍需项目自有译注、赏析与人工复核。诗中提及地、创作地和到访地不得混用。",
        accent="#22d3ee",
        accent_2="#a78bfa",
        accent_3="#f59e0b",
    )
    inject_quality_table(out, rows)
    print(f"  [ok] saved {out}")


if __name__ == "__main__":
    render()
