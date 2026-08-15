"""诗人精神地形图（viz_20）——意象漂移的五分期聚合与三线叠加页。

方法与诚实性口径
----------------
1. 编年只来自可引用来源：data/candidates/<poet>_spirit_chronology.csv（候选，
   status=candidate）与 data/reviewed/verified_poem_contexts.csv（人工审核）。
   status=superseded_by_verified 的候选行改用审核记录的年份地点与等级。
   本脚本绝不生成、推算任何新的系年。
2. 页面区分 A/B 级（实线/实心样式）与 C 级（虚线/空心 + "推定" 徽章）；
   year_precision=disputed 或已知系年争议诗必须展示 controversy_note。
3. 曲线描述的是"作品文本的意象特征"，不是诗人真实心理；样本是"编年可考
   抽样"，不是全集。这些口径都写在页面底部方法论说明框。

产物
----
- output/20_诗人精神地形图.html（默认 --poet 李白；其他诗人另起文件名）
- output/assets/spirit_terrain_data.json（全部聚合结果与逐诗证据明细）
"""
from __future__ import annotations

import argparse
import csv
import html as html_mod
import json
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from data.spirit_image_dict import CLUSTERS, SPIRIT_DICT, words  # noqa: E402

OUTPUT_DIR = ROOT / "output"
ASSETS_DIR = OUTPUT_DIR / "assets"
POEMS_JSON = ROOT / "data" / "poems.json"
JOURNEYS_JSON = ROOT / "data" / "reviewed" / "poet_journeys.json"
VERIFIED_CSV = ROOT / "data" / "reviewed" / "verified_poem_contexts.csv"
CANDIDATE_DIR = ROOT / "data" / "candidates"

POET_KEYS = {"李白": "libai", "杜甫": "dufu", "苏轼": "sushi", "白居易": "baijuyi"}

# 语料/候选表中的同诗异题，统一映射到 poems.json 的标题
TITLE_ALIASES = {"临路歌": "临终歌", "客中行": "客中作", "秋浦歌·其十五": "秋浦歌十七首·十五"}

# 有系年争议、必须展示 controversy_note 的诗（红线 4）
FORCED_CONTROVERSY = {"蜀道难", "将进酒", "独坐敬亭山", "登金陵凤凰台"}

# 五分期配置（poet 参数化预留：为新诗人补一份同结构配置即可）
PERIOD_CONFIG = {
    "李白": [
        {"no": 1, "name": "蜀中与出川", "years": "701–724", "short": "期1·蜀中", "assign": (None, 724), "band": (718.0, 724.5)},
        {"no": 2, "name": "出蜀干谒与漫游", "years": "725–741", "short": "期2·干谒漫游", "assign": (725, 741), "band": (724.5, 741.5)},
        {"no": 3, "name": "供奉翰林与赐金放还", "years": "742–744", "short": "期3·翰林放还", "assign": (742, 744), "band": (741.5, 744.5)},
        {"no": 4, "name": "漫游与安史乱起", "years": "744–755", "short": "期4·漫游乱起", "assign": (745, 755), "band": (744.5, 755.5)},
        {"no": 5, "name": "永王案流放与暮年", "years": "756–762", "short": "期5·流放暮年", "assign": (756, None), "band": (755.5, 763.5)},
    ]
}

EVENT_CONFIG = {
    "李白": [
        (725, "出蜀"),
        (742, "奉诏入京"),
        (744, "赐金放还"),
        (755, "安史乱起"),
        (757, "入永王幕下狱"),
        (758, "流放夜郎"),
        (759, "遇赦"),
        (762, "病逝当涂"),
    ]
}

# 底部地理条带的补充地点：取自候选编年里对应诗的年份与创作地（非行旅审核节点，空心显示）
BAND_EXTRA_CONFIG = {
    "李白": [
        {"title": "客中作", "label": "东鲁"},
        {"title": "流夜郎赠辛判官", "label": "夜郎道中"},
        {"title": "临终歌", "label": "当涂"},
    ]
}

# "大鹏的一生" 专题：同一意象的首尾对照
DAPENG_CONFIG = {
    "李白": {
        "keyword": "大鹏",
        "early": {
            "title": "上李邕",
            "period_label": "期1 · 蜀中/出川（传统口径）",
            "chronology_note": "传统赏析多将《上李邕》系于李白青年干谒时期，"
            "本项目暂无可引用编年记录，故不计入曲线样本，仅作意象对照展示。",
        },
        "late": {
            "title": "临终歌",
            "period_label": "期5 · 暮年当涂",
        },
    }
}

DICT_WORDS = words()  # 已按长度降序，供最长匹配
LOOKUP = {
    row[0]: {
        "word": row[0],
        "category": row[1],
        "cluster": row[2],
        "sentiment": row[3],
        "scale": row[4],
        "scale_basis": row[5],
    }
    for row in SPIRIT_DICT
}

CLUSTER_ORDER = ("豪情进取", "纵逸狂放", "隐逸超脱", "漂泊羁旅", "愁苦幽愤")
CLUSTER_SLUGS = {"豪情进取": "hq", "纵逸狂放": "zy", "隐逸超脱": "yy", "漂泊羁旅": "pb", "愁苦幽愤": "ck"}


def canon_title(title: str) -> str:
    title = title.strip()
    return TITLE_ALIASES.get(title, title)


def load_poems(poet: str) -> dict[str, str]:
    rows = json.loads(POEMS_JSON.read_text(encoding="utf-8"))
    result: dict[str, str] = {}
    for row in rows:
        name = str(row.get("poet") or row.get("author") or "")
        if name == poet:
            result[str(row.get("title") or "").strip()] = str(row.get("body") or "")
    return result


def load_verified(poet: str) -> dict[str, dict[str, str]]:
    if not VERIFIED_CSV.exists():
        return {}
    with VERIFIED_CSV.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return {
        canon_title(str(row.get("title") or "")): {k: str(v or "").strip() for k, v in row.items()}
        for row in rows
        if str(row.get("poet") or "").strip() == poet
    }


def detect_controversy(title: str, precision: str, source_note: str) -> str:
    """只用来源材料判断争议，不引入模型知识编造内容。"""
    if precision == "disputed":
        return source_note
    if title in FORCED_CONTROVERSY:
        return source_note or "该诗系年存在学术争议，来源备注见原始记录。"
    if re.search(r"另有.{1,12}说|存在研究空间|系年争议", source_note):
        return source_note
    return ""


def assign_period(periods: list[dict], year_mid: float) -> int:
    for p in periods:
        lo, hi = p["assign"]
        if (lo is None or year_mid >= lo) and (hi is None or year_mid <= hi):
            return int(p["no"])
    return int(periods[-1]["no"])


def year_display(start: int, end: int, precision: str) -> str:
    base = str(start) if start == end else f"{start}–{end}"
    if precision == "disputed":
        return f"{base}·存疑"
    if precision == "approximate":
        return f"约{base}"
    return base


def load_chronology(poet: str, periods: list[dict]) -> list[dict]:
    """候选编年 + 审核记录，合成带来源的编年样本；绝不生成新系年。"""
    key = POET_KEYS.get(poet, poet)
    path = CANDIDATE_DIR / f"{key}_spirit_chronology.csv"
    verified = load_verified(poet)
    records: list[dict] = []
    seen: set[str] = set()

    if path.exists():
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                title = canon_title(str(row.get("title") or ""))
                status = str(row.get("status") or "").strip()
                if status not in {"candidate", "superseded_by_verified"}:
                    print(f"  [warn] 跳过状态为 {status!r} 的候选行：{title}")
                    continue
                precision = str(row.get("year_precision") or "").strip()
                if status == "superseded_by_verified":
                    v = verified.get(title)
                    if not v:
                        print(f"  [warn] {title} 标记 superseded_by_verified 但审核表无对应记录，跳过")
                        continue
                    start, end = int(v["year_start"]), int(v["year_end"])
                    rec = {
                        "title": title,
                        "year_start": start,
                        "year_end": end,
                        "year_precision": "",
                        "place": v.get("historical_place", ""),
                        "modern_city": v.get("modern_city", ""),
                        "fact_grade": v.get("fact_grade", "B"),
                        "status": "verified",
                        "chronology_source": "reviewed",
                        "source_name": v.get("source_name", ""),
                        "source_url": v.get("source_url", ""),
                        "source_note": v.get("source_note", ""),
                    }
                else:
                    start, end = int(row["year_start"]), int(row["year_end"])
                    rec = {
                        "title": title,
                        "year_start": start,
                        "year_end": end,
                        "year_precision": precision,
                        "place": str(row.get("historical_place") or "").strip(),
                        "modern_city": str(row.get("modern_city") or "").strip(),
                        "fact_grade": str(row.get("fact_grade") or "").strip() or "C",
                        "status": status,
                        "chronology_source": "candidate",
                        "source_name": str(row.get("source_name") or "").strip(),
                        "source_url": str(row.get("source_url") or "").strip(),
                        "source_note": str(row.get("source_note") or "").strip(),
                    }
                rec["year_mid"] = (rec["year_start"] + rec["year_end"]) / 2.0
                raw_period = str(row.get("period") or "").strip()
                rec["period"] = int(raw_period) if raw_period.isdigit() else assign_period(periods, rec["year_mid"])
                rec["controversy_note"] = detect_controversy(title, rec["year_precision"], rec["source_note"])
                rec["year_label"] = year_display(rec["year_start"], rec["year_end"], rec["year_precision"])
                records.append(rec)
                seen.add(title)
    else:
        print(f"  [warn] 未找到候选编年文件：{path}")

    # 审核表中不在候选表里的同诗人诗：直接并入（人工审核，等级按审核记录）
    for title, v in verified.items():
        if title in seen:
            continue
        if str(v.get("status") or "") and str(v.get("status")) not in {"approved"}:
            continue
        try:
            start, end = int(v["year_start"]), int(v["year_end"])
        except (KeyError, ValueError):
            continue
        rec = {
            "title": title,
            "year_start": start,
            "year_end": end,
            "year_precision": "",
            "place": v.get("historical_place", ""),
            "modern_city": v.get("modern_city", ""),
            "fact_grade": v.get("fact_grade", "B"),
            "status": "verified",
            "chronology_source": "reviewed",
            "source_name": v.get("source_name", ""),
            "source_url": v.get("source_url", ""),
            "source_note": v.get("source_note", ""),
        }
        rec["year_mid"] = (start + end) / 2.0
        rec["period"] = assign_period(periods, rec["year_mid"])
        rec["controversy_note"] = detect_controversy(title, "", rec["source_note"])
        rec["year_label"] = year_display(start, end, "")
        records.append(rec)

    records.sort(key=lambda r: (r["period"], r["year_mid"], r["title"]))
    return records


def split_sentences(body: str) -> list[str]:
    parts = re.split(r"[。！？；!?;\n]+", body)
    return [seg.strip().strip("，、 ") for seg in parts if seg.strip()]


def scan_poem(body: str) -> list[dict]:
    """词典最长匹配扫描：先长词后短词，命中位置不再重复计短词。"""
    hits: list[dict] = []
    for sent in split_sentences(body):
        i, n = 0, len(sent)
        while i < n:
            matched = None
            for word in DICT_WORDS:
                if sent.startswith(word, i):
                    matched = word
                    break
            if matched:
                info = LOOKUP[matched]
                hits.append(
                    {
                        "word": matched,
                        "category": info["category"],
                        "cluster": info["cluster"],
                        "sentiment": info["sentiment"],
                        "scale": info["scale"],
                        "sentence": sent,
                    }
                )
                i += len(matched)
            else:
                i += 1
    return hits


def aggregate_periods(periods: list[dict], records: list[dict]) -> list[dict]:
    stats = []
    for p in periods:
        rows = [r for r in records if r["period"] == p["no"]]
        hits = [h for r in rows for h in r["hits"]]
        cluster_counts = Counter(h["cluster"] for h in hits if h["cluster"])
        clustered = sum(cluster_counts.values())
        sentiments = [h["sentiment"] for h in hits]
        scales = [h["scale"] for h in hits if h["scale"] is not None]
        grade_mix = Counter(r["fact_grade"] for r in rows)
        disputed = sum(1 for r in rows if r["controversy_note"])
        stats.append(
            {
                "no": p["no"],
                "name": p["name"],
                "years": p["years"],
                "short": p["short"],
                "band": [p["band"][0], p["band"][1]],
                "poem_count": len(rows),
                "hit_count": len(hits),
                "clustered_hits": clustered,
                "cluster_counts": {c: cluster_counts.get(c, 0) for c in CLUSTERS},
                "cluster_share": {
                    c: (round(cluster_counts.get(c, 0) * 100.0 / clustered, 1) if clustered else 0.0)
                    for c in CLUSTERS
                },
                "mean_sentiment": round(sum(sentiments) / len(sentiments), 3) if sentiments else None,
                "mean_scale": round(sum(scales) / len(scales), 2) if scales else None,
                "scale_hits": len(scales),
                "grade_mix": dict(grade_mix),
                "disputed_count": disputed,
                "rep_year": round(sum(r["year_mid"] for r in rows) / len(rows), 1) if rows else None,
                "tentative": grade_mix.get("C", 0) > 0,
                "titles": [r["title"] for r in rows],
            }
        )
    return stats


def load_journey_band(poet: str, records: list[dict]) -> list[dict]:
    points: list[dict] = []
    payload = json.loads(JOURNEYS_JSON.read_text(encoding="utf-8-sig"))
    for group in payload.get("poets", []):
        if str(group.get("poet") or "") != poet:
            continue
        for node in sorted(group.get("nodes", []), key=lambda r: int(r["route_order"])):
            place = str(node.get("place_historical") or "").split("·")[0]
            points.append(
                {
                    "year": int(node["year"]),
                    "labelText": f"{place}\n{node['year']}",
                    "detail": str(node.get("event") or ""),
                    "kind": "journey",
                    "level": str(node.get("source_level") or "B"),
                }
            )
    rec_index = {r["title"]: r for r in records}
    for extra in BAND_EXTRA_CONFIG.get(poet, []):
        rec = rec_index.get(canon_title(extra["title"]))
        if not rec:
            continue
        points.append(
            {
                "year": int(round(rec["year_mid"])),
                "labelText": f"{extra['label']}\n{int(round(rec['year_mid']))}",
                "detail": f"《{rec['title']}》候选编年：{rec['year_label']}，{rec['place']}（{rec['fact_grade']}级）",
                "kind": "candidate",
                "level": rec["fact_grade"],
            }
        )
    points.sort(key=lambda p: p["year"])
    return points


def build_dapeng(poet: str, poems: dict[str, str], records: list[dict]) -> dict:
    cfg = DAPENG_CONFIG.get(poet)
    if not cfg:
        return {"available": False}
    keyword = cfg["keyword"]
    rec_index = {r["title"]: r for r in records}

    def side(side_cfg: dict) -> dict:
        title = canon_title(side_cfg["title"])
        body = poems.get(title)
        if not body:
            return {"available": False, "title": title}
        line = next((s for s in split_sentences(body) if keyword in s), "")
        rec = rec_index.get(title)
        return {
            "available": bool(line),
            "title": title,
            "line": line,
            "period_label": side_cfg.get("period_label", ""),
            "chronology_note": side_cfg.get("chronology_note", ""),
            "record": (
                {
                    "year_label": rec["year_label"],
                    "place": rec["place"],
                    "fact_grade": rec["fact_grade"],
                    "source_name": rec["source_name"],
                    "source_url": rec["source_url"],
                }
                if rec
                else None
            ),
        }

    early = side(cfg["early"])
    late = side(cfg["late"])
    return {"available": early["available"] and late["available"], "keyword": keyword, "early": early, "late": late}


def build_payload(poet: str) -> dict:
    periods_cfg = PERIOD_CONFIG[poet]
    poems = load_poems(poet)
    records = load_chronology(poet, periods_cfg)

    matched: list[dict] = []
    for rec in records:
        body = poems.get(rec["title"])
        if body is None:
            print(f"  [warn] 编年诗《{rec['title']}》不在 poems.json 语料中，跳过")
            continue
        hits = scan_poem(body)
        rec = dict(rec)
        rec["hits"] = hits
        rec["hit_count"] = len(hits)
        sentiments = [h["sentiment"] for h in hits]
        scales = [h["scale"] for h in hits if h["scale"] is not None]
        rec["mean_sentiment"] = round(sum(sentiments) / len(sentiments), 3) if sentiments else None
        rec["mean_scale"] = round(sum(scales) / len(scales), 2) if scales else None
        rec["cluster_counts"] = dict(Counter(h["cluster"] for h in hits if h["cluster"]))
        matched.append(rec)

    period_stats = aggregate_periods(periods_cfg, matched)
    band = load_journey_band(poet, matched)
    dapeng = build_dapeng(poet, poems, matched)
    grade_total = Counter(r["fact_grade"] for r in matched)

    return {
        "poet": poet,
        "poet_key": POET_KEYS.get(poet, poet),
        "generated_at": datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S"),
        "periods": period_stats,
        "events": [{"year": y, "name": n} for y, n in EVENT_CONFIG.get(poet, [])],
        "journey_band": band,
        "dapeng": dapeng,
        "per_poem": [
            {k: v for k, v in rec.items() if k != "assign"}
            for rec in matched
        ],
        "clusters": list(CLUSTER_ORDER),
        "dict_stats": {
            "total_words": len(SPIRIT_DICT),
            "clustered_words": sum(1 for row in SPIRIT_DICT if row[2] is not None),
            "scaled_words": sum(1 for row in SPIRIT_DICT if row[4] is not None),
        },
        "sample": {
            "poem_count": len(matched),
            "hit_count": sum(r["hit_count"] for r in matched),
            "corpus_poems": len(poems),
            "grade_mix": dict(grade_total),
            "disputed_count": sum(1 for r in matched if r["controversy_note"]),
            "candidate_count": sum(1 for r in matched if r["chronology_source"] == "candidate"),
            "reviewed_count": sum(1 for r in matched if r["chronology_source"] == "reviewed"),
        },
    }


# ---------------------------------------------------------------- HTML 组装

def esc(text: object) -> str:
    return html_mod.escape(str(text), quote=True)


def grade_badge(grade: str) -> str:
    cls = "grade grade-C" if grade == "C" else "grade"
    return f'<span class="{cls}" title="来源等级 {esc(grade)}">{esc(grade or "?")}</span>'


def build_metrics_html(payload: dict) -> str:
    s = payload["sample"]
    covered = sum(1 for p in payload["periods"] if p["poem_count"])
    gm = s["grade_mix"]
    grade_text = " · ".join(f"{g}级×{n}" for g, n in sorted(gm.items()))
    chips = [
        ("编年样本", f"{s['poem_count']} 首", f"候选 {s['candidate_count']} + 审核 {s['reviewed_count']}"),
        ("意象命中", f"{s['hit_count']} 处", f"词典 {payload['dict_stats']['total_words']} 词条"),
        ("覆盖分期", f"{covered}/5", "期1 蜀中暂无编年样本"),
        ("来源等级", grade_text or "—", f"系年存疑 {s['disputed_count']} 首"),
    ]
    parts = []
    for label, value, note in chips:
        parts.append(
            f'<div class="metric"><span class="metric-label">{esc(label)}</span>'
            f'<strong>{esc(value)}</strong><span class="metric-note">{esc(note)}</span></div>'
        )
    return "".join(parts)


def pick_evidence(hits: list[dict], limit: int = 3) -> list[dict]:
    """挑最有代表性的证据句：优先有簇、|情感值|大的命中，句子去重。"""
    ranked = sorted(hits, key=lambda h: (h["cluster"] is None, -abs(h["sentiment"])))
    picked, seen_sent = [], set()
    for h in ranked:
        if h["sentence"] in seen_sent:
            continue
        picked.append(h)
        seen_sent.add(h["sentence"])
        if len(picked) >= limit:
            break
    return picked


def build_evidence_html(payload: dict) -> str:
    blocks = []
    per_poem = payload["per_poem"]
    for idx, p in enumerate(payload["periods"]):
        rows = [r for r in per_poem if r["period"] == p["no"]]
        head = (
            f'<summary><span class="p-no">{esc(p["short"])}</span>'
            f'<span class="p-name">{esc(p["name"])}（{esc(p["years"])}）</span>'
            f'<span class="p-stat">{p["poem_count"]} 首 · {p["hit_count"]} 处命中'
            + (f' · 存疑 {p["disputed_count"]}' if p["disputed_count"] else "")
            + "</span></summary>"
        )
        if not rows:
            body = '<p class="empty-note">本期暂无可引用编年样本（蜀中期作品的系年记录待补，缺口不虚构）。</p>'
        else:
            trs = []
            for r in rows:
                tentative = r["fact_grade"] == "C" or r["year_precision"] == "disputed"
                row_cls = ' class="row-tentative"' if tentative else ""
                word_counts = Counter((h["word"], h["cluster"]) for h in r["hits"])
                chips = []
                for (word, cluster), count in sorted(word_counts.items(), key=lambda kv: -kv[1])[:8]:
                    slug = CLUSTER_SLUGS.get(cluster or "", "none")
                    label = f"{word}×{count}" if count > 1 else word
                    tip = cluster or "无簇（仅情感值）"
                    chips.append(f'<span class="chip chip-{slug}" title="{esc(tip)}">{esc(label)}</span>')
                if len(word_counts) > 8:
                    chips.append(f'<span class="chip chip-none">…等{len(word_counts)}词</span>')
                evid = []
                for h in pick_evidence(r["hits"]):
                    cl = h["cluster"] or "无簇"
                    evid.append(
                        f'<div class="evi-line">「{esc(h["sentence"])}」'
                        f'<span class="evi-tag">{esc(h["word"])}·{esc(cl)}</span></div>'
                    )
                src = ""
                if r["source_url"]:
                    src = (
                        f' <a class="src-link" href="{esc(r["source_url"])}" target="_blank" '
                        f'rel="noopener noreferrer" title="{esc(r["source_name"])}">来源↗</a>'
                    )
                tent_badge = '<span class="tent-badge">推定</span>' if tentative else ""
                trs.append(
                    f"<tr{row_cls}>"
                    f'<td class="td-title">《{esc(r["title"])}》{tent_badge}<div class="td-place">{esc(r["place"])}</div></td>'
                    f'<td class="td-year">{esc(r["year_label"])}{src}</td>'
                    f"<td>{grade_badge(r['fact_grade'])}</td>"
                    f'<td class="td-chips">{"".join(chips) or "—"}</td>'
                    f'<td class="td-evi">{"".join(evid) or "—"}</td>'
                    "</tr>"
                )
                if r["controversy_note"]:
                    trs.append(
                        '<tr class="controversy-row"><td colspan="5"><details><summary>⚠ 系年争议'
                        "（点击展开各家观点）</summary>"
                        f'<p>{esc(r["controversy_note"])}</p></details></td></tr>'
                    )
            body = (
                '<div class="table-wrap"><table><thead><tr><th>诗题</th><th>系年</th><th>等级</th>'
                "<th>命中意象（簇）</th><th>证据句</th></tr></thead><tbody>"
                + "".join(trs)
                + "</tbody></table></div>"
            )
        open_attr = " open" if idx == 1 else ""
        blocks.append(f'<details class="period-block"{open_attr}>{head}{body}</details>')
    return "".join(blocks)


def build_dapeng_html(payload: dict) -> str:
    d = payload["dapeng"]
    head = (
        '<div class="panel-head"><div><div class="panel-title">大鹏的一生 · 同一意象的首尾对照</div>'
        '<div class="panel-meta">同一只"大鹏"，起于扶摇，摧于中天——意象不变，姿态已换。</div></div></div>'
    )
    if not d.get("available"):
        return head + '<p class="empty-note" style="margin:16px">待补语料：语料中未同时收录《上李邕》与《临终歌》的大鹏句。</p>'

    def card(side: dict, accent: str) -> str:
        rec = side.get("record")
        if rec:
            meta = (
                f"{grade_badge(rec['fact_grade'])} {esc(rec['year_label'])} · {esc(rec['place'])}"
                + (
                    f' <a class="src-link" href="{esc(rec["source_url"])}" target="_blank" rel="noopener noreferrer">来源↗</a>'
                    if rec.get("source_url")
                    else ""
                )
            )
        else:
            meta = '<span class="tent-badge">无编年记录 · 不计入曲线</span>'
        note = f'<p class="dp-note">{esc(side["chronology_note"])}</p>' if side.get("chronology_note") else ""
        return (
            f'<div class="dp-card dp-{accent}"><div class="dp-kicker">{esc(side["period_label"])}</div>'
            f'<div class="dp-title">《{esc(side["title"])}》</div>'
            f'<blockquote class="dp-line">{esc(side["line"])}</blockquote>'
            f'<div class="dp-meta">{meta}</div>{note}</div>'
        )

    return (
        head
        + '<div class="dp-grid">'
        + card(d["early"], "rise")
        + '<div class="dp-arrow" aria-hidden="true">→</div>'
        + card(d["late"], "fall")
        + "</div>"
    )


APP_TEMPLATE = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="description" content="诗人精神地形图：__POET__编年诗的意象情感值与空间尺度五分期漂移。">
  <title>诗人精神地形图 · __POET__ | 诗行万里</title>
  <link rel="icon" href="data:,">
  <script src="assets/pyecharts/v6/echarts.min.js"></script>
  <style>
    :root {
      --paper:#f2f4f0; --surface:#ffffff; --surface-soft:#f7f8f5;
      --ink:#202521; --muted:#6a726c; --line:#d7dcd6; --line-strong:#b9c1ba;
      --cinnabar:#b64b3f; --jade:#26786e; --gold:#a87527; --blue:#426f94;
      --slate:#4c5170; --radius:6px; --shadow:0 10px 28px rgba(30,40,33,.07);
    }
    * { box-sizing:border-box; }
    html { min-height:100%; scroll-behavior:smooth; }
    body {
      margin:0; color:var(--ink); background-color:var(--paper);
      background-image:linear-gradient(rgba(45,54,48,.025) 1px,transparent 1px),linear-gradient(90deg,rgba(45,54,48,.025) 1px,transparent 1px);
      background-size:24px 24px; font-family:"Microsoft YaHei","PingFang SC","Segoe UI",sans-serif;
      overflow-x:hidden;
    }
    a { color:inherit; }
    .backlink {
      position:fixed; top:14px; right:16px; z-index:30; padding:7px 13px; font-size:12px; font-weight:700;
      color:#fff; background:var(--jade); border-radius:20px; text-decoration:none; box-shadow:var(--shadow);
    }
    .backlink:hover { background:#1f635b; }
    .wrap { max-width:1180px; margin:0 auto; padding:26px 22px 46px; }
    h1,h2,h3,p { margin-top:0; }
    .page-head { display:flex; align-items:flex-start; justify-content:space-between; gap:18px; flex-wrap:wrap; margin-bottom:14px; }
    .seal-row { display:flex; gap:14px; align-items:flex-start; }
    .seal {
      width:44px; height:44px; flex:0 0 auto; display:grid; place-items:center; color:#fff; background:var(--cinnabar);
      border:1px solid #cf7469; border-radius:5px; font-family:"KaiTi","STKaiti",serif; font-size:27px;
    }
    .eyebrow { margin-bottom:5px; color:var(--cinnabar); font-size:11px; font-weight:800; letter-spacing:.14em; }
    h1 { margin-bottom:8px; font-family:"KaiTi","STKaiti",serif; font-size:30px; line-height:1.25; }
    .intro { max-width:760px; color:var(--muted); font-size:12px; line-height:1.8; margin-bottom:0; }
    .quality-badge {
      display:inline-flex; align-items:center; min-height:30px; padding:4px 11px; color:#704b14; background:#f7edd9;
      border:1px solid #dfc38c; border-radius:4px; font-size:11px; font-weight:700;
    }
    .metric-row { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:10px; margin:16px 0; }
    .metric {
      display:flex; flex-direction:column; gap:3px; padding:11px 14px; background:var(--surface);
      border:1px solid var(--line); border-left:3px solid var(--jade); border-radius:var(--radius); box-shadow:var(--shadow);
    }
    .metric-label { color:var(--muted); font-size:10px; font-weight:700; }
    .metric strong { font-size:17px; line-height:1.3; }
    .metric-note { color:var(--muted); font-size:10px; }
    .panel { margin:16px 0; background:var(--surface); border:1px solid var(--line); border-radius:var(--radius); box-shadow:var(--shadow); overflow:hidden; }
    .panel-head { display:flex; align-items:flex-start; justify-content:space-between; gap:14px; flex-wrap:wrap; padding:13px 16px; border-bottom:1px solid var(--line); }
    .panel-title { font-size:14px; font-weight:800; }
    .panel-meta { margin-top:4px; color:var(--muted); font-size:10.5px; line-height:1.6; max-width:720px; }
    .legend-mini { display:flex; flex-wrap:wrap; gap:11px; align-items:center; color:var(--muted); font-size:10px; padding-top:3px; }
    .lg::before { content:""; display:inline-block; width:9px; height:9px; margin-right:5px; border-radius:50%; vertical-align:-1px; }
    .lg-red::before { background:var(--cinnabar); }
    .lg-jade::before { background:var(--jade); }
    .lg-hollow::before { background:#fff; border:2px solid var(--gold); width:6px; height:6px; }
    .chart-scroll { overflow-x:auto; }
    .chart { width:100%; }
    .chart-main { height:560px; min-width:680px; }
    .chart-stack { height:400px; min-width:520px; }
    .dp-grid { display:grid; grid-template-columns:minmax(0,1fr) 40px minmax(0,1fr); align-items:stretch; gap:8px; padding:16px; }
    .dp-card { padding:15px 17px; background:var(--surface-soft); border:1px solid var(--line); border-radius:var(--radius); }
    .dp-rise { border-top:3px solid var(--cinnabar); }
    .dp-fall { border-top:3px solid var(--slate); }
    .dp-kicker { color:var(--muted); font-size:10px; font-weight:800; letter-spacing:.08em; }
    .dp-title { margin:6px 0 4px; font-family:"KaiTi","STKaiti",serif; font-size:19px; font-weight:700; }
    .dp-line { margin:10px 0; padding:9px 0 9px 13px; border-left:3px solid var(--gold); font-family:"KaiTi","STKaiti",serif; font-size:19px; line-height:1.65; }
    .dp-meta { display:flex; align-items:center; gap:7px; flex-wrap:wrap; color:var(--muted); font-size:11px; }
    .dp-note { margin:9px 0 0; color:#8a5a17; background:#faf3e3; border:1px dashed #dfc38c; border-radius:4px; padding:8px 10px; font-size:10.5px; line-height:1.7; }
    .dp-arrow { display:grid; place-items:center; color:var(--muted); font-size:22px; }
    .grade { display:inline-grid; place-items:center; width:24px; height:22px; color:#fff; background:var(--jade); border-radius:3px; font-size:12px; font-weight:800; }
    .grade-C { background:var(--gold); }
    .tent-badge { display:inline-block; margin-left:6px; padding:1px 7px; color:#8a5a17; background:#faf3e3; border:1px dashed var(--gold); border-radius:3px; font-size:10px; font-weight:700; vertical-align:2px; }
    .period-block { border-bottom:1px solid var(--line); }
    .period-block:last-child { border-bottom:0; }
    .period-block > summary { display:flex; align-items:baseline; gap:12px; flex-wrap:wrap; padding:12px 16px; cursor:pointer; list-style:none; }
    .period-block > summary::-webkit-details-marker { display:none; }
    .period-block > summary::before { content:"▸"; color:var(--muted); font-size:11px; }
    .period-block[open] > summary::before { content:"▾"; }
    .period-block[open] > summary { background:var(--surface-soft); }
    .p-no { font-family:Consolas,monospace; color:var(--cinnabar); font-size:12px; font-weight:800; }
    .p-name { font-size:13px; font-weight:700; }
    .p-stat { color:var(--muted); font-size:11px; }
    .table-wrap { overflow-x:auto; padding:0 16px 14px; }
    table { width:100%; min-width:680px; border-collapse:collapse; font-size:12px; }
    th { padding:8px 9px; color:var(--muted); font-size:10.5px; text-align:left; border-bottom:1px solid var(--line-strong); white-space:nowrap; }
    td { padding:9px; border-bottom:1px solid var(--line); vertical-align:top; line-height:1.6; }
    tbody tr:last-child td { border-bottom:0; }
    .td-title { min-width:120px; font-weight:700; }
    .td-place { margin-top:2px; color:var(--muted); font-size:10px; font-weight:400; }
    .td-year { white-space:nowrap; }
    .td-chips { min-width:170px; }
    .chip { display:inline-block; margin:0 4px 4px 0; padding:1px 7px; border-radius:3px; font-size:10.5px; color:#fff; }
    .chip-hq { background:var(--cinnabar); } .chip-zy { background:var(--gold); }
    .chip-yy { background:var(--jade); } .chip-pb { background:var(--blue); }
    .chip-ck { background:var(--slate); } .chip-none { background:#9aa39c; }
    .td-evi { min-width:230px; }
    .evi-line { margin-bottom:4px; font-family:"KaiTi","STKaiti",serif; font-size:13.5px; }
    .evi-tag { margin-left:6px; color:var(--muted); font-family:"Microsoft YaHei","PingFang SC",sans-serif; font-size:10px; }
    .row-tentative td { background:#fbf7ec; border-left:2px dashed var(--gold); }
    .controversy-row td { padding:0 9px 10px; background:#fbf7ec; border-left:2px dashed var(--gold); }
    .controversy-row summary { color:#8a5a17; font-size:11px; font-weight:700; cursor:pointer; padding:4px 0; }
    .controversy-row p { margin:5px 0 0; color:#6d5a33; font-size:10.5px; line-height:1.75; }
    .src-link { color:var(--jade); font-size:10.5px; text-underline-offset:3px; white-space:nowrap; }
    .empty-note { margin:0; padding:13px 16px; color:var(--muted); font-size:11.5px; }
    .method-note { margin:18px 0 0; padding:15px 18px; background:var(--surface-soft); border:1px dashed var(--line-strong); border-radius:var(--radius); }
    .method-note h2 { font-size:13px; margin-bottom:9px; }
    .method-note ul { margin:0; padding-left:18px; color:#4a534d; font-size:11.5px; line-height:1.9; }
    .method-note strong { color:var(--ink); }
    footer { margin-top:20px; color:var(--muted); font-size:10.5px; line-height:1.7; }
    @media (max-width:980px) {
      .metric-row { grid-template-columns:repeat(2,minmax(0,1fr)); }
      .dp-grid { grid-template-columns:1fr; }
      .dp-arrow { transform:rotate(90deg); }
    }
    @media (max-width:700px) {
      .wrap { padding:20px 12px 38px; }
      h1 { font-size:24px; }
      .chart-main { height:500px; }
      .chart-stack { height:360px; }
      .backlink { top:auto; bottom:14px; }
    }
    @media (max-width:420px) {
      .metric-row { grid-template-columns:1fr 1fr; gap:8px; }
      .metric strong { font-size:14px; }
    }
  </style>
</head>
<body>
  <a class="backlink" href="index.html">← 返回总入口</a>
  <div class="wrap">
    <header class="page-head">
      <div class="seal-row">
        <span class="seal">诗</span>
        <div>
          <div class="eyebrow">诗行万里 · 核心研究 20</div>
          <h1>诗人精神地形图 · __POET__</h1>
          <p class="intro">用人工双维度意象词典（五情感簇 + 五级空间尺度）扫描__POET__编年可考的
            __POEM_N__ 首诗，把"写了什么意象"折算成两条曲线：<strong>情感值均值</strong>与
            <strong>空间尺度均值</strong>，观察它们在人生五分期里的漂移。曲线描述作品文本特征，不是诗人真实心理。</p>
        </div>
      </div>
      <span class="quality-badge">候选编年数据 · A/B 实证与 C 推定分样式展示</span>
    </header>

    <div class="metric-row">__METRICS__</div>

    <section class="panel">
      <div class="panel-head">
        <div>
          <div class="panel-title">三线叠加 · 情感值 × 空间尺度 × 地理行迹</div>
          <div class="panel-meta">X 轴为公元纪年；曲线点落在各分期编年诗的平均年份上；金色虚线为人生事件；
            底部条带为地理行迹（实心=审核行旅节点，空心=候选编年地点，连线只表时间先后）。</div>
        </div>
        <div class="legend-mini"><span class="lg lg-red">情感值均值</span><span class="lg lg-jade">空间尺度均值</span><span class="lg lg-hollow">空心点=含C级推定编年</span></div>
      </div>
      <div class="chart-scroll"><div id="chartMain" class="chart chart-main"></div></div>
    </section>

    <section class="panel">
      <div class="panel-head">
        <div>
          <div class="panel-title">五簇 × 五期 · 意象命中占比堆叠</div>
          <div class="panel-meta">各期归簇意象命中的百分比构成：看"豪情进取 + 纵逸狂放"如何让位于"漂泊羁旅 + 愁苦幽愤"。
            期1 蜀中暂无编年样本，如实留空。</div>
        </div>
      </div>
      <div class="chart-scroll"><div id="chartStack" class="chart chart-stack"></div></div>
    </section>

    <section class="panel">__DAPENG__</section>

    <section class="panel">
      <div class="panel-head">
        <div>
          <div class="panel-title">证据表 · 每一处数字可回溯到具体诗句</div>
          <div class="panel-meta">按分期展开：诗题 / 系年 / 来源等级 / 命中意象（按簇着色） / 证据句。
            C 级或系年存疑的行整行使用"推定"底纹，争议诗附各家观点原文。完整逐诗明细见
            assets/__DATA_FILE__。</div>
        </div>
      </div>
      __EVIDENCE__
    </section>

    <section class="method-note">
      <h2>方法论与研究边界</h2>
      <ul>
        <li><strong>词典口径：</strong>意象词典为本项目人工整理（共 __DICT_TOTAL__ 词条，其中
          __DICT_CLUSTERED__ 条归入五情感簇、__DICT_SCALED__ 条标注 1–5 级空间尺度），
          不是外部权威词库或模型输出；匹配采用"先长词后短词"的最长匹配，命中位置不重复计短词。</li>
        <li><strong>样本口径：</strong>本页只统计"编年可考"的 __POEM_N__ 首（候选编年 __CAND_N__ 首 +
          人工审核 __REV_N__ 首），是覆盖五分期的代表作抽样，<strong>不是李白全集</strong>；
          期1（蜀中）目前没有可引用的编年记录，图中如实留空，不以模型知识补年。</li>
        <li><strong>等级含义：</strong>A=一手文献直接支持；B=可在线核实的学术年谱/权威注本/学术数据库（附来源链接）；
          C=仅题录常识的推定，页面一律用虚线、空心点与"推定"徽章区分。系年有争议的诗（如《蜀道难》《将进酒》
          《独坐敬亭山》《登金陵凤凰台》）在证据表附各家观点。</li>
        <li><strong>结论边界：</strong>情感值与空间尺度都是<strong>作品文本特征</strong>的统计描述，
          随语境摇摆的意象（月、风、舟等）只计情感值不归簇；曲线不能当作诗人真实心理的测量，
          分期均值也受抽样构成影响，只支持"同一诗人不同分期的相对比较"。</li>
      </ul>
    </section>

    <footer>生成时间 __GENERATED_AT__ · 聚合数据 assets/__DATA_FILE__ · 编年来源：cnkgraph 唐宋文学编年地图开放API、
      古诗文网创作背景页及各家年谱（逐条链接见证据表） · 本页离线可用，未引用任何远程资源。</footer>
  </div>

  <script id="appData" type="application/json">__APP_DATA__</script>
  <script>
  (function () {
    "use strict";
    var dataEl = document.getElementById("appData");
    var payload;
    try { payload = JSON.parse(dataEl.textContent); } catch (err) { return; }
    if (typeof echarts === "undefined") { return; }

    var colors = { jade: "#26786e", red: "#b64b3f", gold: "#a87527", blue: "#426f94", grid: "#d7dcd6", ink: "#303732", muted: "#6a726c", slate: "#4c5170" };
    var clusterColors = { "豪情进取": "#b64b3f", "纵逸狂放": "#a87527", "隐逸超脱": "#26786e", "漂泊羁旅": "#426f94", "愁苦幽愤": "#4c5170" };
    var periods = payload.periods;
    var XMIN = 718, XMAX = 765;

    function initChart(id) {
      var el = document.getElementById(id);
      return el ? echarts.init(el, null, { renderer: "canvas" }) : null;
    }

    function curvePoints(field, color) {
      var out = [];
      periods.forEach(function (p, i) {
        if (p[field] === null || p.rep_year === null) { return; }
        out.push({
          value: [p.rep_year, p[field]],
          periodIndex: i,
          symbol: p.tentative ? "emptyCircle" : "circle",
          symbolSize: p.tentative ? 11 : 9,
          itemStyle: p.tentative ? { color: "#ffffff", borderColor: color, borderWidth: 2, borderType: "dashed" } : { color: color }
        });
      });
      return out;
    }

    function bounds(field, pad) {
      var vals = [];
      periods.forEach(function (p) { if (p[field] !== null) { vals.push(p[field]); } });
      if (!vals.length) { return [-1, 1]; }
      var lo = Math.min.apply(null, vals) - pad;
      var hi = Math.max.apply(null, vals) + pad;
      return [Math.max(-1, Math.floor(lo * 10) / 10), Math.min(1, Math.ceil(hi * 10) / 10)];
    }

    var sentBounds = bounds("mean_sentiment", 0.12);

    var areaData = periods.map(function (p, i) {
      var name = p.poem_count ? p.short : p.short + "·无样本";
      return [
        { xAxis: p.band[0], name: name, itemStyle: { color: i % 2 ? "rgba(38,120,110,.055)" : "rgba(182,75,63,.045)" },
          label: { show: true, position: "insideBottom", distance: 5, color: colors.muted, fontSize: 10 } },
        { xAxis: p.band[1] }
      ];
    });

    var eventLines = payload.events.map(function (e, i) {
      return {
        xAxis: e.year,
        lineStyle: { color: colors.gold, type: "dashed", width: 1, opacity: 0.85 },
        label: {
          show: true, position: "insideEndTop", distance: 6 + (i % 2) * 58,
          formatter: String(e.year) + "\n" + e.name.split("").join("\n"),
          color: colors.ink, fontSize: 9, lineHeight: 10.5,
          backgroundColor: "rgba(255,255,255,.85)", padding: [2, 1]
        }
      };
    });
    eventLines.push({ yAxis: 0, lineStyle: { color: colors.grid, type: "solid", width: 1, opacity: 0.9 }, label: { show: false } });

    var bandPoints = payload.journey_band.map(function (node, i) {
      var isJourney = node.kind === "journey";
      return {
        value: [node.year, 0.5],
        labelText: node.labelText,
        detail: node.detail,
        symbol: "circle",
        symbolSize: isJourney ? 9 : 8,
        itemStyle: isJourney
          ? { color: colors.jade }
          : { color: "#ffffff", borderColor: colors.gold, borderWidth: 2 },
        label: {
          show: true, position: i % 2 ? "bottom" : "top", distance: 4,
          formatter: node.labelText, color: isJourney ? colors.ink : "#8a5a17",
          fontSize: 9, lineHeight: 11, align: "center"
        }
      };
    });
    var bandLine = payload.journey_band.map(function (node) { return [node.year, 0.5]; });

    var mainChart = initChart("chartMain");
    if (mainChart) {
      mainChart.setOption({
        animationDuration: 500,
        tooltip: {
          trigger: "item", confine: true,
          backgroundColor: "rgba(255,255,255,.97)", borderColor: colors.grid,
          textStyle: { color: colors.ink, fontSize: 11 },
          formatter: function (params) {
            var d = params.data || {};
            if (typeof d.periodIndex === "number") {
              var p = periods[d.periodIndex];
              var lines = ["<b>" + p.name + "（" + p.years + "）</b>", "编年诗 " + p.poem_count + " 首 · 意象命中 " + p.hit_count + " 处"];
              if (params.seriesName === "情感值均值") { lines.push("情感值均值：" + p.mean_sentiment + "（-1悲 ~ +1喜）"); }
              else { lines.push("空间尺度均值：" + p.mean_scale + "（空间意象 " + p.scale_hits + " 处）"); }
              if (p.disputed_count) { lines.push('<span style="color:#a87527">含系年存疑 ' + p.disputed_count + " 首</span>"); }
              return lines.join("<br>");
            }
            if (d.detail) { return "<b>" + String(d.labelText || "").replace("\n", " · ") + "</b><br>" + d.detail; }
            return params.seriesName;
          }
        },
        legend: {
          top: 6, left: 14, itemWidth: 16, itemHeight: 8,
          textStyle: { color: colors.muted, fontSize: 11 },
          data: ["情感值均值", "空间尺度均值"]
        },
        grid: [
          { left: 58, right: 46, top: 40, bottom: 186 },
          { left: 58, right: 46, height: 74, bottom: 64 }
        ],
        xAxis: [
          { type: "value", gridIndex: 0, min: XMIN, max: XMAX, axisLabel: { show: false }, axisTick: { show: false }, splitLine: { show: false }, axisLine: { lineStyle: { color: colors.grid } } },
          { type: "value", gridIndex: 1, min: XMIN, max: XMAX, interval: 5, axisLabel: { color: colors.muted, fontSize: 10, formatter: function (v) { return v + ""; } }, axisTick: { show: false }, splitLine: { show: false }, axisLine: { lineStyle: { color: colors.grid } }, name: "公元", nameTextStyle: { color: colors.muted, fontSize: 10 } }
        ],
        yAxis: [
          { type: "value", gridIndex: 0, min: sentBounds[0], max: sentBounds[1], name: "情感值", nameTextStyle: { color: colors.red, fontSize: 10 }, axisLabel: { color: colors.muted, fontSize: 10 }, splitLine: { lineStyle: { color: colors.grid, type: "dashed" } } },
          { type: "value", gridIndex: 0, min: 1, max: 5, interval: 1, position: "right", name: "空间尺度", nameTextStyle: { color: colors.jade, fontSize: 10 }, axisLabel: { color: colors.muted, fontSize: 10 }, splitLine: { show: false } },
          { type: "value", gridIndex: 1, min: 0, max: 1, show: false }
        ],
        series: [
          {
            name: "情感值均值", type: "line", xAxisIndex: 0, yAxisIndex: 0, z: 6,
            data: curvePoints("mean_sentiment", colors.red),
            lineStyle: { color: colors.red, width: 2.4 }, itemStyle: { color: colors.red },
            connectNulls: true,
            markArea: { silent: true, data: areaData },
            markLine: { silent: true, symbol: "none", animation: false, data: eventLines }
          },
          {
            name: "空间尺度均值", type: "line", xAxisIndex: 0, yAxisIndex: 1, z: 6,
            data: curvePoints("mean_scale", colors.jade),
            lineStyle: { color: colors.jade, width: 2.4 }, itemStyle: { color: colors.jade },
            connectNulls: true
          },
          {
            name: "地理行迹", type: "line", xAxisIndex: 1, yAxisIndex: 2, silent: true, z: 3,
            data: bandLine, symbol: "none",
            lineStyle: { color: colors.gold, width: 1.4, type: "dashed", opacity: 0.8 }
          },
          {
            name: "行旅节点", type: "scatter", xAxisIndex: 1, yAxisIndex: 2, z: 5,
            data: bandPoints, labelLayout: { hideOverlap: true }
          }
        ]
      }, true);
    }

    var stackChart = initChart("chartStack");
    if (stackChart) {
      var catLabels = periods.map(function (p) { return p.short + "\n" + (p.poem_count ? p.poem_count + "首·" + p.clustered_hits + "簇命中" : "无编年样本"); });
      stackChart.setOption({
        animationDuration: 500,
        tooltip: {
          trigger: "axis", axisPointer: { type: "shadow" }, confine: true,
          backgroundColor: "rgba(255,255,255,.97)", borderColor: colors.grid,
          textStyle: { color: colors.ink, fontSize: 11 },
          formatter: function (items) {
            if (!items || !items.length) { return ""; }
            var p = periods[items[0].dataIndex];
            var lines = ["<b>" + p.name + "（" + p.years + "）</b>"];
            if (!p.clustered_hits) { lines.push("无编年样本"); return lines.join("<br>"); }
            items.forEach(function (it) {
              var count = p.cluster_counts[it.seriesName] || 0;
              lines.push(it.marker + it.seriesName + "：" + it.value + "%（" + count + " 处）");
            });
            return lines.join("<br>");
          }
        },
        legend: { top: 6, textStyle: { color: colors.muted, fontSize: 11 }, itemWidth: 14, itemHeight: 9 },
        grid: { left: 52, right: 24, top: 44, bottom: 52 },
        xAxis: {
          type: "category", data: catLabels,
          axisLabel: { color: colors.muted, fontSize: 10, lineHeight: 14, interval: 0 },
          axisTick: { show: false }, axisLine: { lineStyle: { color: colors.grid } }
        },
        yAxis: {
          type: "value", min: 0, max: 100,
          axisLabel: { color: colors.muted, fontSize: 10, formatter: "{value}%" },
          splitLine: { lineStyle: { color: colors.grid, type: "dashed" } }
        },
        series: payload.clusters.map(function (name) {
          return {
            name: name, type: "bar", stack: "total", barWidth: "56%",
            itemStyle: { color: clusterColors[name] },
            emphasis: { focus: "series" },
            label: {
              show: true, color: "#ffffff", fontSize: 9,
              formatter: function (it) { return it.value >= 9 ? it.value + "%" : ""; }
            },
            data: periods.map(function (p) { return p.cluster_share[name]; })
          };
        })
      }, true);
    }

    window.addEventListener("resize", function () {
      if (mainChart) { mainChart.resize(); }
      if (stackChart) { stackChart.resize(); }
    });
  }());
  </script>
  <noscript>此页面需要启用 JavaScript 以呈现三线叠加图与堆叠条形图；证据表与方法论说明无需脚本即可阅读。</noscript>
</body>
</html>
"""


def render_html(payload: dict, data_file_name: str) -> str:
    app_data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    html = (
        APP_TEMPLATE.replace("__APP_DATA__", app_data)
        .replace("__METRICS__", build_metrics_html(payload))
        .replace("__EVIDENCE__", build_evidence_html(payload))
        .replace("__DAPENG__", build_dapeng_html(payload))
        .replace("__POET__", esc(payload["poet"]))
        .replace("__POEM_N__", str(payload["sample"]["poem_count"]))
        .replace("__CAND_N__", str(payload["sample"]["candidate_count"]))
        .replace("__REV_N__", str(payload["sample"]["reviewed_count"]))
        .replace("__DICT_TOTAL__", str(payload["dict_stats"]["total_words"]))
        .replace("__DICT_CLUSTERED__", str(payload["dict_stats"]["clustered_words"]))
        .replace("__DICT_SCALED__", str(payload["dict_stats"]["scaled_words"]))
        .replace("__DATA_FILE__", data_file_name)
        .replace("__GENERATED_AT__", payload["generated_at"])
    )
    return html


# ---------------------------------------------------------------- 自检

def check_html(path: Path) -> list[str]:
    problems: list[str] = []
    html = path.read_text(encoding="utf-8")
    if len(html.encode("utf-8")) < 5000:
        problems.append("HTML 小于 5000 字节")
    if re.search(r'<script[^>]+src=["\']https?://', html):
        problems.append("发现远程 script 引用")
    for token in ("NaN", "Infinity"):
        if token in html:
            problems.append(f"正文出现 {token}")
    node = shutil.which("node")
    scripts = re.findall(r"<script(?![^>]*\bsrc=)([^>]*)>(.*?)</script>", html, re.S)
    js_checked = 0
    for attrs, code in scripts:
        if "application/json" in attrs:
            try:
                json.loads(code)
            except json.JSONDecodeError as err:
                problems.append(f"内嵌 JSON 解析失败：{err}")
            continue
        if not code.strip():
            continue
        js_checked += 1
        if node:
            with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as tmp:
                tmp.write(code)
                tmp_path = tmp.name
            try:
                proc = subprocess.run([node, "--check", tmp_path], capture_output=True, text=True)
                if proc.returncode != 0:
                    problems.append(f"node --check 报错：{proc.stderr.strip()[:400]}")
            finally:
                Path(tmp_path).unlink(missing_ok=True)
        else:
            if code.count("{") != code.count("}") or code.count("(") != code.count(")"):
                problems.append("括号数量不平衡（node 不可用，退化检查）")
    if js_checked == 0:
        problems.append("未找到内嵌 JS 脚本")
    return problems


def main() -> None:
    parser = argparse.ArgumentParser(description="诗人精神地形图：意象漂移五分期聚合与页面生成")
    parser.add_argument("--poet", default="李白", help="诗人姓名（默认李白；其他诗人需先补 PERIOD_CONFIG 等配置）")
    args = parser.parse_args()
    poet = args.poet

    if poet not in PERIOD_CONFIG:
        print(f"  [err] 尚未为 {poet} 配置五分期（PERIOD_CONFIG/EVENT_CONFIG）。"
              f"当前支持：{'、'.join(PERIOD_CONFIG)}。脚本已按 poet 参数化，补配置即可扩展。")
        sys.exit(1)

    OUTPUT_DIR.mkdir(exist_ok=True)
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)

    key = POET_KEYS.get(poet, poet)
    if poet == "李白":
        out_html = OUTPUT_DIR / "20_诗人精神地形图.html"
        data_file_name = "spirit_terrain_data.json"
    else:
        out_html = OUTPUT_DIR / f"20_诗人精神地形图_{poet}.html"
        data_file_name = f"spirit_terrain_data_{key}.json"
    out_json = ASSETS_DIR / data_file_name

    payload = build_payload(poet)
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    html = render_html(payload, data_file_name)
    out_html.write_text(html, encoding="utf-8")

    print(f"== {poet} 精神地形图 · 分期统计 ==")
    for p in payload["periods"]:
        if p["poem_count"]:
            print(
                f"  期{p['no']} {p['name']}（{p['years']}）：{p['poem_count']} 首 / {p['hit_count']} 处命中 / "
                f"情感均值 {p['mean_sentiment']} / 尺度均值 {p['mean_scale']}（空间意象 {p['scale_hits']} 处）/ "
                f"等级 {p['grade_mix']} / 存疑 {p['disputed_count']}"
            )
        else:
            print(f"  期{p['no']} {p['name']}（{p['years']}）：无编年样本（如实留空）")
    d = payload["dapeng"]
    if d.get("available"):
        print(f"  大鹏对照：《{d['early']['title']}》「{d['early']['line']}」 → 《{d['late']['title']}》「{d['late']['line']}」")
    else:
        print("  大鹏对照：待补语料")

    problems = check_html(out_html)
    if problems:
        for msg in problems:
            print(f"  [check-fail] {msg}")
        sys.exit(2)
    print("  [check] HTML 自检通过：无远程脚本 / 无 NaN 与 Infinity / 内嵌 JS 通过 node --check")
    print(f"  [ok] saved {out_html}")
    print(f"  [ok] saved {out_json}")

    # 单独运行本脚本时同步 manifest 哈希；run_all 中 viz_19 收尾时仍会整体重算。
    try:
        from viz_99_output_index import write_manifest

        write_manifest()
        print(f"  [ok] manifest updated: {OUTPUT_DIR / 'manifest.json'}")
    except Exception as err:  # manifest 同步失败不应阻断页面生成
        print(f"  [warn] manifest 未同步：{err}")


if __name__ == "__main__":
    main()
