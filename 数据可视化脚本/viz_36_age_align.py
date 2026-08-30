# -*- coding: utf-8 -*-
"""viz_36 同龄对齐：六诗人按虚岁对齐的横向泳道图。

零参数可复跑。产出：
  - data/candidates/poet_birth_years.json   出生年 + 来源（cnkgraph 在线核实）
  - output/assets/competition/age_data.json 页面数据
  - output/36_同龄对齐.html                 参赛页
口径：
  - 虚岁 = 诗年 - 出生公历年 + 1；诗年取 year_start..year_end 中点（四舍五入）。
  - fact_grade = D 的行不进计算；candidate 编年在 hover 卡内带「候选」徽章。
  - 意象命中：spirit_image_dict 当前词条，按词长降序贪婪匹配（长词优先、遮蔽防重复计数）。
  - 情感画像 = 当前细粒度多标签情绪 + VAD（愉悦度/唤醒度/掌控感）+ 文学形容词。
  - 模型只辅助扩充候选词；发布值由本地词典规则复算，并保留命中证据。
"""
from __future__ import annotations

import csv
import importlib.util
import json
import math
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CAND = DATA / "candidates"
OUT = ROOT / "output"
COMP = OUT / "assets" / "competition"
CANONICAL_JSON = DATA / "poems.json"
FULL_MANIFEST_JSON = DATA / "analysis" / "famous_poets_full_manifest.json"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ---------------------------------------------------------------- 基础常量
POETS = [
    # key, 姓名, 主色, 出生公历年
    ("libai", "李白", "#426f94", 701),
    ("dufu", "杜甫", "#7a5c3d", 712),
    ("baijuyi", "白居易", "#26786e", 772),
    ("sushi", "苏轼", "#b64b3f", 1037),
    ("liqingzhao", "李清照", "#9c5d8f", 1084),
    ("luyou", "陆游", "#8a3b2f", 1125),
]

BIRTH_RECORDS = [
    {
        "poet": "李白", "birth_year": 701,
        "note": "cnkgraph 作者档案 Life 字段：701年1月16日—762；与《李太白年谱》（詹锳）通说一致。",
        "source_name": "cnkgraph唐宋文学编年地图开放API（2026-07-26在线核实）",
        "source_url": "https://open.cnkgraph.com/api/Writing/%E6%9D%8E%E7%99%BD",
    },
    {
        "poet": "杜甫", "birth_year": 712,
        "note": "cnkgraph 作者档案 Life 字段：712年2月12日—770；与《杜甫年谱》通说一致。",
        "source_name": "cnkgraph唐宋文学编年地图开放API（2026-07-26在线核实）",
        "source_url": "https://open.cnkgraph.com/api/Writing/%E6%9D%9C%E7%94%AB",
    },
    {
        "poet": "白居易", "birth_year": 772,
        "note": "cnkgraph 作者档案 Life 字段：772—846；与朱金城《白居易年谱》通说一致。",
        "source_name": "cnkgraph唐宋文学编年地图开放API（2026-07-26在线核实）",
        "source_url": "https://open.cnkgraph.com/api/Writing/%E7%99%BD%E5%B1%85%E6%98%93",
    },
    {
        "poet": "苏轼", "birth_year": 1037,
        "note": "生于农历景祐三年十二月十九（丙子年末），公历折算为1037年1月8日。cnkgraph 作者档案 Life 字段记为 1036年12月19日（农历样式）。本项目统一用公历 1037 计虚岁，与按农历丙子年起算的传统虚岁相差1岁，已在页面方法区注明。",
        "source_name": "cnkgraph唐宋文学编年地图开放API（2026-07-26在线核实）+ 孔凡礼《苏轼年谱》通说",
        "source_url": "https://open.cnkgraph.com/api/Writing/%E8%8B%8F%E8%BD%BC",
    },
    {
        "poet": "李清照", "birth_year": 1084,
        "note": "cnkgraph 作者档案 Life 字段：1084年2月5日—1151年4月10日；生年与徐培均《李清照集笺注》通说一致（卒年有约1155/1156异说）。",
        "source_name": "cnkgraph唐宋文学编年地图开放API（2026-07-26在线核实）",
        "source_url": "https://open.cnkgraph.com/api/Writing/%E6%9D%8E%E6%B8%85%E7%85%A7",
    },
    {
        "poet": "陆游", "birth_year": 1125,
        "note": "cnkgraph 作者档案 Life 字段：1125年10月17日—1210年12月29日（生日为农历十月十七，公历1125年11月13日）；与于北山《陆游年谱》通说一致。",
        "source_name": "cnkgraph唐宋文学编年地图开放API（2026-07-26在线核实）",
        "source_url": "https://open.cnkgraph.com/api/Writing/%E9%99%86%E6%B8%B8",
    },
]

# 李白无 life_stages.json，用任务给定五分期
LIBAI_STAGES = [
    {"index": 1, "label": "蜀中读书与出蜀", "year_start": 701, "year_end": 725},
    {"index": 2, "label": "干谒与漫游", "year_start": 726, "year_end": 741},
    {"index": 3, "label": "供奉翰林与赐金放还", "year_start": 742, "year_end": 744},
    {"index": 4, "label": "漫游与安史乱起", "year_start": 744, "year_end": 756},
    {"index": 5, "label": "永王案流放与暮年", "year_start": 757, "year_end": 762},
]

# 候选编年 CSV 诗题 → poems.json 诗题（异题同诗）
ALT_TITLES = {
    ("李白", "客中行"): "客中作",
    ("李白", "秋浦歌·其十五"): "秋浦歌十七首·十五",
    ("李白", "临路歌"): "临终歌",
}

PRECISION_LABEL = {"exact": "明确系年", "approximate": "约略系年", "disputed": "系年存疑"}

# ---------------------------------------------------------------- 载入词典
def load_spirit_dict():
    spec = importlib.util.spec_from_file_location("spirit_image_dict", DATA / "spirit_image_dict.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    # 词长降序，保证长词优先
    entries = {row[0]: {"cluster": row[2], "sentiment": float(row[3])} for row in mod.SPIRIT_DICT}
    words = sorted(entries, key=len, reverse=True)
    return words, entries


def load_emotion_stats():
    spec = importlib.util.spec_from_file_location(
        "classical_emotion_lexicon", DATA / "classical_emotion_lexicon.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    stats = mod.validate()
    return stats["emotions"], stats["keywords"]


def index_emotion_profiles(rows):
    """按 canonical ID/work ID 索引，并保留哈希碰撞候选。"""
    indexes = {
        "by_canonical_id": {},
        "by_work_id": {},
        "by_body_hash": defaultdict(list),
    }
    for row in rows:
        profile = {
            field: value for field, value in row.items()
            if field not in {
                "poet", "title", "body_hash", "work_id", "canonical_gushiwen_id"
            }
        }
        entry = {"row": row, "profile": profile}
        work_id = row.get("work_id")
        if work_id:
            if work_id in indexes["by_work_id"]:
                raise ValueError(f"情感档案 work_id 重复: {work_id}")
            indexes["by_work_id"][work_id] = entry
        canonical_id = row.get("canonical_gushiwen_id")
        if canonical_id:
            key = (row["poet"], canonical_id)
            if key in indexes["by_canonical_id"]:
                raise ValueError(f"情感档案 canonical ID 重复: {key}")
            indexes["by_canonical_id"][key] = entry
        indexes["by_body_hash"][(row["poet"], row["body_hash"])].append(entry)
    return indexes


def load_emotion_profiles():
    """读取全语料细粒度情感档案，建立稳定身份索引。"""
    path = DATA / "stylometry" / "emotion_profiles.json"
    if not path.exists():
        raise FileNotFoundError(
            "缺少 emotion_profiles.json，请先运行 python tools/build_emotion_profiles.py"
        )
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload, index_emotion_profiles(payload["profiles"])


def load_dual_corpus_metadata(analysis_payload, analysis_record_count, canonical_count):
    """从已构建产物读取动态双层口径，并拒绝陈旧或降级后的状态数据。"""
    manifest = json.loads(FULL_MANIFEST_JSON.read_text(encoding="utf-8"))
    analysis_count = manifest.get("record_count")
    canonical_evidence_count = manifest.get("canonical_count")
    if analysis_count != analysis_record_count:
        raise ValueError(
            "情感状态档案与 full manifest 数量不一致: "
            f"profiles={analysis_record_count}, manifest={analysis_count}"
        )
    if analysis_payload.get("corpus_size") != analysis_count:
        raise ValueError("情感状态档案 corpus_size 与 full manifest 不一致")
    if canonical_evidence_count != canonical_count:
        raise ValueError(
            "canonical 证据库与 full manifest 数量不一致: "
            f"poems={canonical_count}, manifest={canonical_evidence_count}"
        )
    corpus_source = str(analysis_payload.get("corpus_source") or "")
    corpus_path = str(analysis_payload.get("corpus_path") or "")
    if corpus_source != "analysis_full" or not corpus_path:
        raise ValueError(
            "viz36 状态层必须来自 analysis_full，且必须公开 corpus_path"
        )
    return {
        "corpus_source": corpus_source,
        "corpus_path": corpus_path,
        "analysis_count": analysis_count,
        "canonical_evidence_count": canonical_evidence_count,
    }


def count_hits(body: str, words, entries):
    """长词优先 + 遮蔽，防止「孤舟」再被「舟」重复计数。"""
    text = body
    matched = []  # (word, count)
    for w in words:
        c = text.count(w)
        if c:
            matched.append((w, c))
            text = text.replace(w, chr(1) * len(w))
    hits = sum(c for _, c in matched)
    if hits == 0:
        return 0, None, None, []
    s = sum(entries[w]["sentiment"] * c for w, c in matched) / hits
    cluster_cnt = defaultdict(int)
    for w, c in matched:
        cl = entries[w]["cluster"]
        if cl:
            cluster_cnt[cl] += c
    dom = max(cluster_cnt, key=cluster_cnt.get) if cluster_cnt else None
    top = sorted(matched, key=lambda x: (-x[1], -len(x[0])))[:4]
    return hits, round(s, 3), dom, [f"{w}×{c}" for w, c in top]


# ---------------------------------------------------------------- 载入数据
def index_canonical_poems(poems):
    """保留同题异文候选，禁止用输入顺序隐式决定正文。"""
    indexed = defaultdict(list)
    for poem in poems:
        indexed[(poem["author"], poem["title"])].append(poem)
    return dict(indexed)


def select_canonical_poem(indexed, poet, title, chronology_row):
    candidates = indexed.get((poet, title), [])
    if len(candidates) == 1:
        return candidates[0]
    references = " ".join(
        str(chronology_row.get(field) or "")
        for field in ("source_url", "source_note")
    )
    matched = [
        poem for poem in candidates
        if poem.get("source_url") and poem["source_url"] in references
    ]
    if len(matched) == 1:
        return matched[0]
    raise ValueError(
        f"canonical 诗作无法唯一定位: {(poet, title)}，"
        f"候选={len(candidates)}，来源匹配={len(matched)}"
    )


def analysis_entry_for_canonical(indexes, poem):
    poet = poem["author"]
    canonical_id = poem.get("source_poem_id")
    if canonical_id:
        entry = indexes["by_canonical_id"].get((poet, canonical_id))
        if entry is None:
            raise KeyError(f"情感档案缺少 canonical ID: {(poet, canonical_id)}")
        return entry
    work_id = poem.get("work_id")
    if work_id:
        entry = indexes["by_work_id"].get(work_id)
        if entry is None:
            raise KeyError(f"情感档案缺少 work_id: {work_id}")
        return entry
    candidates = indexes["by_body_hash"].get((poet, poem.get("body_hash")), [])
    if len(candidates) > 1:
        raise ValueError(
            f"情感档案 body_hash 非唯一，禁止回退: {(poet, poem.get('body_hash'))}"
        )
    return candidates[0] if candidates else None


def emotion_for_canonical(indexes, poem):
    entry = analysis_entry_for_canonical(indexes, poem)
    return entry["profile"] if entry else None


def published_identity(entry, canonical_poem):
    if entry is None:
        raise KeyError(
            "canonical 证据作品无法回配 analysis_full 身份: "
            f"{(canonical_poem['author'], canonical_poem['title'])}"
        )
    row = entry["row"]
    work_id = str(row.get("work_id") or "").strip()
    body_hash = str(row.get("body_hash") or "").strip()
    if not work_id or not body_hash:
        raise ValueError("analysis_full 作品缺少 work_id/body_hash")
    canonical_id = row.get("canonical_gushiwen_id") or canonical_poem.get(
        "source_poem_id"
    )
    expected_canonical_id = canonical_poem.get("source_poem_id")
    if (
        expected_canonical_id
        and canonical_id
        and canonical_id != expected_canonical_id
    ):
        raise ValueError("情感档案与 canonical 证据的作品 ID 不一致")
    expected_body_hash = canonical_poem.get("body_hash")
    if expected_body_hash and body_hash != expected_body_hash:
        raise ValueError("情感档案与 canonical 证据的 body_hash 不一致")
    return {
        "work_id": work_id,
        "canonical_gushiwen_id": canonical_id or None,
        "body_hash": body_hash,
    }


def load_canonical_poems():
    poems = json.loads(CANONICAL_JSON.read_text(encoding="utf-8"))
    return index_canonical_poems(poems)


def load_chronology_rows():
    """六人候选编年，李白合并 p2-p5 补充行（主文件优先）。"""
    rows_by_poet = defaultdict(dict)  # poet -> {title: row}
    files = []
    for key, name, _c, _b in POETS:
        files.append((name, CAND / f"{key}_spirit_chronology.csv"))
    for i in range(2, 6):
        files.append(("李白", CAND / f"libai_spirit_chronology_p{i}.csv"))
    for _poet, path in files:
        with open(path, encoding="utf-8-sig", newline="") as fh:
            for r in csv.DictReader(fh):
                key = r["title"]
                if key not in rows_by_poet[r["poet"]]:
                    rows_by_poet[r["poet"]][key] = r
    return rows_by_poet


def load_stages():
    stages = {"李白": LIBAI_STAGES}
    for key, name, _c, _b in POETS:
        if key == "libai":
            continue
        d = json.loads((CAND / f"{key}_life_stages.json").read_text(encoding="utf-8"))
        stages[name] = [
            {"index": s["index"], "label": s["label"],
             "year_start": int(s["year_start"]), "year_end": int(s["year_end"])}
            for s in d["stages"]
        ]
    return stages


def period_label(poet_name, row, stages):
    """CSV period 列可能是数字、文字或空；优先按诗年落到分期区间。"""
    st = stages[poet_name]
    p = (row.get("period") or "").strip()
    if p.isdigit():
        for s in st:
            if s["index"] == int(p):
                return s["label"]
    if p:  # 文字型（李白 p 文件），按前两字匹配
        for s in st:
            if p[:2] in s["label"] or s["label"][:2] in p:
                return s["label"]
    try:
        y = (int(row["year_start"]) + int(row["year_end"])) // 2
        for s in st:
            if s["year_start"] <= y <= s["year_end"]:
                return s["label"]
    except (ValueError, KeyError):
        pass
    return p or "分期未定"


def first_line(body: str) -> str:
    for ln in re.split(r"[\n\r]+", body):
        ln = ln.strip()
        if ln:
            return ln[:26] + ("…" if len(ln) > 26 else "")
    return ""


# ---------------------------------------------------------------- 主流程
def build():
    words, entries = load_spirit_dict()
    emotion_count, emotion_rule_count = load_emotion_stats()
    spirit_count = len(entries)
    emotion_payload, emotion_profiles = load_emotion_profiles()
    canonical_poems = load_canonical_poems()
    corpus_meta = load_dual_corpus_metadata(
        emotion_payload,
        len(emotion_payload["profiles"]),
        sum(len(poems) for poems in canonical_poems.values()),
    )
    chron = load_chronology_rows()
    stages = load_stages()

    CAND.mkdir(parents=True, exist_ok=True)
    (CAND / "poet_birth_years.json").write_text(
        json.dumps({
            "generated_at": "2026-07-26", "status": "verified-online",
            "note": "六人出生公历年，viz_36 同龄对齐用。虚岁=诗年-出生年+1。",
            "records": BIRTH_RECORDS,
        }, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
        newline="\n",
    )

    poets_out = []
    excluded = []
    for key, name, color, birth in POETS:
        st = stages[name]
        poems = []
        for title, r in sorted(chron[name].items(), key=lambda kv: kv[1]["year_start"] or "9999"):
            grade = (r.get("fact_grade") or "").strip()
            ys, ye = (r.get("year_start") or "").strip(), (r.get("year_end") or "").strip()
            if grade == "D" or not ys or not ye:
                excluded.append((name, title, grade or "无系年"))
                continue
            y0, y1 = int(ys), int(ye)
            y_mid = (y0 + y1 + 1) // 2  # 中点四舍五入
            age = y_mid - birth + 1
            canonical_title = ALT_TITLES.get((name, title), title)
            canonical_poem = select_canonical_poem(
                canonical_poems, name, canonical_title, r
            )
            body = canonical_poem["body"]
            hits, senti, dom, top = count_hits(body, words, entries)
            analysis_entry = analysis_entry_for_canonical(
                emotion_profiles, canonical_poem
            )
            emotion = (analysis_entry or {}).get("profile") or {
                "primary": None, "primary_label": "情绪未定", "family": "未定",
                "color": "#8d8f88", "top_emotions": [],
                "adjectives": ["含混", "待考"], "summary": "词典信号不足，保留为待考",
                "valence": 0.0, "arousal": 0.35, "dominance": 0.0,
                "confidence": 0.12, "confidence_label": "低", "mixed": False,
                "rule_hits": 0, "evidence": [],
            }
            poems.append({
                **published_identity(analysis_entry, canonical_poem),
                "title": title, "year_start": y0, "year_end": y1, "year": y_mid,
                "age": age, "precision": PRECISION_LABEL.get(r.get("year_precision", ""), r.get("year_precision", "")),
                "period": period_label(name, r, stages), "grade": grade,
                "status": (r.get("status") or "").strip() or "candidate",
                "hits": hits, "senti": senti, "cluster": dom, "top": top,
                "emotion": emotion,
                "line": first_line(body),
            })
        poets_out.append({
            "key": key, "name": name, "color": color, "birth": birth,
            "death_age": st[-1]["year_end"] - birth + 1,
            "stages": [
                {"label": s["label"], "age0": s["year_start"] - birth + 1,
                 "age1": s["year_end"] - birth + 1,
                 "y0": s["year_start"], "y1": s["year_end"]}
                for s in st
            ],
            "poems": poems,
        })

    all_ages = sorted({p["age"] for po in poets_out for p in po["poems"]})
    age_min, age_max = all_ages[0], all_ages[-1]

    def nearest_with_data(t):
        if any(abs(a - t) <= 3 for a in all_ages):
            return t
        return min(all_ages, key=lambda a: abs(a - t))

    presets = [{"want": t, "use": nearest_with_data(t)} for t in (25, 35, 50)]

    payload = {
        "generated_at": "2026-07-26",
        "note": "viz_36 同龄对齐数据。情感状态来自全作品分析层；泳道作品来自 canonical 证据层的候选编年。虚岁=诗年-出生公历年+1，诗年取候选系年区间中点；fact_grade=D 不进计算。",
        **corpus_meta,
        "birth_source": "data/candidates/poet_birth_years.json（cnkgraph 2026-07-26 在线核实）",
        "emotion_method": emotion_payload.get("method", ""),
        "emotion_method_note": emotion_payload.get("method_note", ""),
        "emotion_ontology": emotion_payload.get("ontology", {}),
        "emotion_count": emotion_count,
        "emotion_rule_count": emotion_rule_count,
        "spirit_count": spirit_count,
        "age_min": age_min, "age_max": age_max, "presets": presets,
        "poets": poets_out,
        "excluded_rows": [{"poet": a, "title": b, "reason": c} for a, b, c in excluded],
    }
    COMP.mkdir(parents=True, exist_ok=True)
    (COMP / "age_data.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1, allow_nan=False),
        encoding="utf-8",
        newline="\n",
    )

    html = (HTML_TMPL
            .replace("__DATA__", json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False))
            .replace("__EMOTION_COUNT__", str(emotion_count))
            .replace("__EMOTION_RULE_COUNT__", str(emotion_rule_count))
            .replace("__SPIRIT_COUNT__", str(spirit_count))
            .replace("__ANALYSIS_COUNT__", str(corpus_meta["analysis_count"]))
            .replace(
                "__CANONICAL_EVIDENCE_COUNT__",
                str(corpus_meta["canonical_evidence_count"]),
            ))
    (OUT / "36_同龄对齐.html").write_text(
        html, encoding="utf-8", newline="\n"
    )

    # ------------------------------------------------ 控制台：同龄对照戏剧点扫描
    out = sys.stdout
    out.reconfigure(encoding="utf-8")
    n_pts = sum(len(po["poems"]) for po in poets_out)
    print(f"泳道点数 {n_pts}，剔除 {len(excluded)} 行（D级/无系年）：{[t for _, t, _ in excluded]}")
    print(f"虚岁范围 {age_min}-{age_max}，快捷键位 {[(p['want'], p['use']) for p in presets]}")
    best = []
    for t in range(age_min, age_max + 1):
        picks = []
        for po in poets_out:
            cand = [
                p for p in po["poems"]
                if abs(p["age"] - t) <= 1 and p["emotion"].get("primary")
            ]
            if cand:
                p = min(cand, key=lambda x: abs(x["age"] - t))
                picks.append((po["name"], p))
        if len(picks) >= 3:
            ss = [p["emotion"]["valence"] for _, p in picks]
            best.append((max(ss) - min(ss), t, picks))
    best.sort(reverse=True, key=lambda x: x[0])
    for spread, t, picks in best[:6]:
        seg = "；".join(
            f"{n}{p['age']}岁《{p['title']}》"
            f"VAD=({p['emotion']['valence']},{p['emotion']['arousal']},{p['emotion']['dominance']})"
            f"({p['emotion']['primary_label']})"
            for n, p in picks
        )
        print(f"[对照] {t}岁 情感张力{spread:.2f}: {seg}")


# ---------------------------------------------------------------- HTML 模板
HTML_TMPL = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="icon" href="data:,">
<title>同龄对齐 · 诗行万里</title>
<script src="assets/pyecharts/v6/echarts.min.js"></script>
<style>
:root{--paper:#f2f4f0;--ink:#252b27;--cinnabar:#b64b3f;--jade:#26786e;--gold:#a87527;--blue:#426f94;}
*{box-sizing:border-box;margin:0;padding:0;}
body{background:var(--paper);color:var(--ink);font-family:"Microsoft YaHei",sans-serif;line-height:1.7;}
h1,h2,h3,.kai{font-family:KaiTi,STKaiti,"Microsoft YaHei",serif;}
.wrap{max-width:1280px;margin:0 auto;padding:24px 16px 40px;}
header.top{text-align:center;padding:26px 12px 8px;}
header.top h1{font-size:34px;letter-spacing:6px;}
header.top .sub{color:#5a615c;margin-top:6px;font-size:14px;}
.badge{display:inline-block;font-size:11px;padding:1px 7px;border-radius:9px;border:1px solid var(--gold);color:var(--gold);vertical-align:2px;margin-left:6px;}
.panel{background:#fbfcfa;border:1px solid #dfe4de;border-radius:10px;padding:14px 16px;margin-top:16px;box-shadow:0 1px 3px rgba(37,43,39,.05);}
.ctrl{display:flex;flex-wrap:wrap;gap:12px 18px;align-items:center;}
.ctrl .age-read{font-family:KaiTi,STKaiti,serif;font-size:26px;min-width:96px;color:var(--cinnabar);}
.ctrl input[type=range]{flex:1 1 260px;accent-color:var(--cinnabar);height:26px;}
.ctrl .btn{border:1px solid var(--blue);color:var(--blue);background:transparent;border-radius:16px;padding:3px 14px;font-size:13px;cursor:pointer;font-family:inherit;}
.ctrl .btn:hover,.ctrl .btn.on{background:var(--blue);color:#fff;}
#headline{margin-top:10px;font-size:15px;color:#3c443f;}
#headline b{color:var(--cinnabar);}
.scroller{overflow-x:auto;margin-top:14px;border:1px solid #dfe4de;border-radius:10px;background:#fbfcfa;}
#lane{min-width:900px;width:100%;height:640px;}
.legend-row{display:flex;flex-wrap:wrap;gap:10px 22px;font-size:12px;color:#5a615c;margin-top:8px;align-items:center;}
.dotdemo{display:inline-block;border-radius:50%;vertical-align:middle;margin-right:4px;}
.spectrum{display:inline-block;width:116px;height:10px;border-radius:5px;vertical-align:middle;margin:0 5px;background:linear-gradient(90deg,#a84f49,#8f6880,#6687a3,#28776d,#d08b38);}
.ontology-note{margin-top:10px;padding:8px 11px;border-left:3px solid var(--gold);background:#f5f2e9;color:#5a5548;font-size:12px;}
.cards{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin-top:14px;}
.card{background:#fbfcfa;border:1px solid #dfe4de;border-left:4px solid #888;border-radius:8px;padding:10px 12px;font-size:13px;}
.card .who{font-family:KaiTi,STKaiti,serif;font-size:17px;}
.card .title{font-size:15px;margin:4px 0 2px;font-weight:bold;}
.card .meta{color:#5a615c;font-size:12px;}
.card .line{margin-top:6px;color:#3c443f;font-family:KaiTi,STKaiti,serif;}
.card .tags{margin-top:6px;display:flex;flex-wrap:wrap;gap:4px;}
.tag{font-size:11px;padding:0 6px;border-radius:8px;border:1px solid #c9cfc8;color:#5a615c;}
.tag.cand{border-color:var(--gold);color:var(--gold);}
.emotion-title{margin-top:8px;font-family:KaiTi,STKaiti,serif;font-size:15px;line-height:1.45;}
.emotion-pills{display:flex;flex-wrap:wrap;gap:4px;margin-top:6px;}
.emotion-pill{display:inline-flex;align-items:center;gap:4px;border:1px solid currentColor;border-radius:10px;padding:1px 7px;font-size:11px;background:#fff;}
.emotion-pill i{display:inline-block;width:6px;height:6px;border-radius:50%;background:currentColor;}
.evidence{margin-top:5px;color:#69706b;font-size:11px;line-height:1.45;}
.vad{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:5px;margin-top:8px;}
.vad-item{font-size:10px;color:#69706b;min-width:0;}
.vad-item b{display:block;font-size:11px;color:#414843;font-weight:500;white-space:nowrap;}
.meter{height:5px;border-radius:4px;background:#e1e5df;overflow:hidden;margin-top:2px;}
.meter i{display:block;height:100%;border-radius:4px;background:var(--jade);}
.confidence{font-size:10px;border-bottom:1px dotted currentColor;}
.card.empty{border-style:dashed;color:#7a817b;}
details.method{margin-top:26px;background:#fbfcfa;border:1px solid #dfe4de;border-radius:10px;padding:12px 16px;font-size:13px;color:#3c443f;}
details.method summary{cursor:pointer;font-family:KaiTi,STKaiti,serif;font-size:16px;color:var(--ink);}
details.method li{margin:6px 0 6px 18px;}
footer.nav{margin-top:34px;border-top:1px solid #d8ddd6;padding:16px 8px 30px;text-align:center;font-size:13px;}
footer.nav a{color:var(--blue);text-decoration:none;margin:0 9px;white-space:nowrap;line-height:2;}
footer.nav a:hover{color:var(--cinnabar);}
@media (max-width:850px){.cards{grid-template-columns:repeat(2,minmax(0,1fr));}}
@media (max-width:560px){header.top h1{font-size:26px;letter-spacing:3px;}.ctrl .age-read{font-size:21px;}.cards{grid-template-columns:1fr;}.vad{grid-template-columns:repeat(3,minmax(70px,1fr));overflow-x:auto;}}
/* 固定画幅背景：浅纸白表面保留图表与正文的阅读对比。 */
body{position:relative;min-height:100vh;background:transparent;}
body::before{content:"";position:fixed;inset:0;z-index:0;pointer-events:none;background:url("assets/generated/remaining_pages_20260830/36_age_alignment_v1.png") center center / cover no-repeat;}
body::after{content:"";position:fixed;inset:0;z-index:0;pointer-events:none;background:rgba(242,244,240,.14);}
.wrap{position:relative;z-index:1;}
.panel,.scroller,.card,details.method{background:rgba(251,252,250,.90);backdrop-filter:blur(1px);}
.ontology-note{background:rgba(245,242,233,.90);}
.emotion-pill{background:rgba(255,255,255,.88);}
</style>
</head>
<body>
<div class="wrap">
<header class="top">
  <h1>同龄对齐</h1>
  <div class="sub">把六位诗人拉回同一条年龄轴——同样的虚岁，各自正写什么<span class="badge">__EMOTION_COUNT__类情绪 · VAD三维</span></div>
  <div class="sub">状态层 __ANALYSIS_COUNT__ 首全作品 · 证据层 __CANONICAL_EVIDENCE_COUNT__ 首规范作品；本页只发布能稳定回配作品 ID 的候选编年点</div>
</header>

<section class="panel">
  <div class="ctrl">
    <span class="age-read kai">虚岁 <span id="ageVal">35</span></span>
    <input type="range" id="ageSlider" min="16" max="85" step="1" value="35" aria-label="年龄滑块">
    <span id="presetBox"></span>
  </div>
  <div id="headline" class="kai"></div>
  <div class="ontology-note">情感不再五选一：每首诗同时保留主情绪、次情绪、文学形容词，以及愉悦度 / 激越度 / 掌控感。低置信结果明确标记，不用模型猜测替代证据。</div>
</section>

<div class="scroller"><div id="lane"></div></div>
<div class="legend-row">
  <span><span class="dotdemo" style="width:7px;height:7px;background:#8d8f88;"></span><span class="dotdemo" style="width:13px;height:13px;background:#8d8f88;"></span>点的大小 = 该诗意象命中数（spirit 词典__SPIRIT_COUNT__词条）</span>
  <span>点色 = 主情绪 <span class="spectrum"></span>（__EMOTION_COUNT__类细粒度标签）</span>
  <span>底色横带 = 人生分期 · 竖线 = 当前对齐年龄 · 高亮窗口 ±3 岁</span>
</div>

<h2 class="kai" style="margin-top:22px;font-size:22px;">同样 <span id="ageVal2">35</span> 岁，他们各自在写——</h2>
<div class="cards" id="cardBox"></div>

<details class="method">
  <summary>方法与数据（口径与局限）</summary>
  <ul>
    <li><b>双层语料</b>：情感状态层来自 <code>analysis_full</code> 全作品语料（__ANALYSIS_COUNT__ 首）；编年、原句与页面泳道使用 canonical 证据层（__CANONICAL_EVIDENCE_COUNT__ 首）精确回配。每个发布点均保留 <code>work_id</code>、<code>canonical_gushiwen_id</code> 与 <code>body_hash</code>，不按同名诗题串联。</li>
    <li><b>出生年</b>：李白701、杜甫712、白居易772、苏轼1037、李清照1084、陆游1125，均于2026-07-26经 cnkgraph 唐宋文学编年地图开放API在线核实（见 data/candidates/poet_birth_years.json 附URL）。苏轼生于农历丙子年十二月十九（公历1037年1月8日），本页统一用公历1037计虚岁，与按农历丙子年起算的传统虚岁相差1岁。</li>
    <li><b>虚岁口径</b>：虚岁 = 诗年 − 出生公历年 + 1。诗年取候选系年区间（year_start–year_end）的中点四舍五入；区间跨度与系年精度（明确/约略/存疑）在悬停卡中如实展示。</li>
    <li><b>编年来源</b>：六人诗作系年取自 data/candidates/*_spirit_chronology.csv（候选级，B/C为主，来源为 cnkgraph 开放API与古诗文网创作背景互证），<b>未经人工终审</b>，故全页带「候选」徽章；fact_grade=D 与无系年的行不进入任何计算（剔除清单见数据文件 excluded_rows）。</li>
    <li><b>细粒度情感本体</b>：data/classical_emotion_lexicon.py 将表达扩为__EMOTION_COUNT__类，包括豪迈昂扬、报国壮志、纵逸狂放、友情酬赠、悼亡怀亲、欢愉明快、闲适恬淡、爱恋缠绵、眷恋怀旧、思乡怀人、离愁惜别、孤寂清冷、漂泊羁旅、悲恸哀伤、悲悯苍生、忧国伤时、幽愤不平、焦灼惊惧、失意无奈、衰老病痛、怀古感时、哲思澄明、归隐超脱等；一首诗允许多标签并存。</li>
    <li><b>连续指标</b>：VAD 分别表示愉悦度（Valence）、唤醒/激越度（Arousal）与掌控感（Dominance）。三项由命中标签原型按证据权重合成后映射到0–100，仅用于同一规则口径下比较。</li>
    <li><b>模型与证据</b>：语言模型用于扩充古典诗词候选表达与文学形容词，发布值由本地__EMOTION_RULE_COUNT__条关键词规则确定性复算；页面展示主/次标签、占比、命中词与置信度。旧五簇只作低权重回退，不再直接充当最终标签。</li>
    <li><b>局限</b>：每人仅20余首可系年代表作，泳道是抽样而非全集；「同样N岁」对读受系年精度影响，存疑条目请以悬停卡中的区间与出处为准；李清照晚期分期迄年沿用候选分期文件（其卒年本有1151/约1155-1156异说）。</li>
  </ul>
</details>

<footer class="nav">
  <a href="29_参赛导航.html">29 参赛导航</a><a href="30_诗行万里_参赛版.html">30 总入口</a><a href="31_凝望罗盘.html">31 凝望罗盘</a><a href="32_身与心双层地图.html">32 身与心双层地图</a><a href="33_平行时空759.html">33 平行时空759</a><a href="34_一字识诗人.html">34 一字识诗人</a><a href="35_两种孤独与夸张签名.html">35 两种孤独与夸张签名</a><a href="36_同龄对齐.html" style="color:var(--cinnabar);">36 同龄对齐</a><a href="37_可听的诗.html">37 可听的诗</a><a href="38_唐宋意象潮汐.html">38 意象潮汐</a><a href="39_诗人自述生命卷.html">39 诗人自述生命卷</a>
</footer>
</div>

<script>
var DATA = __DATA__;
(function(){
"use strict";
var poets = DATA.poets;
var N = poets.length;
var AGE_LO = Math.max(1, DATA.age_min - 3), AGE_HI = DATA.age_max + 3;
var slider = document.getElementById('ageSlider');
slider.min = AGE_LO; slider.max = AGE_HI;

function lerpHex(a, b, t){
  function h(x,i){ return parseInt(x.substr(1+i*2,2),16); }
  var r=Math.round(h(a,0)+(h(b,0)-h(a,0))*t), g=Math.round(h(a,1)+(h(b,1)-h(a,1))*t), bl=Math.round(h(a,2)+(h(b,2)-h(a,2))*t);
  return 'rgb('+r+','+g+','+bl+')';
}
var NEUTRAL='#8d8f88', RED='#b64b3f', GREEN='#26786e';
function sentiColor(s){
  if (s===null || s===undefined || s!==s) return NEUTRAL;
  var t = Math.max(-1, Math.min(1, s));
  return t<0 ? lerpHex(NEUTRAL, RED, -t) : lerpHex(NEUTRAL, GREEN, t);
}
function symSize(hits){ return Math.min(26, 6 + 2.4*Math.sqrt(hits||0)); }
function dimPct(v, signed){
  v=Number(v); if(v!==v) return 50;
  return signed?Math.round((Math.max(-1,Math.min(1,v))+1)*50):Math.round(Math.max(0,Math.min(1,v))*100);
}
function emotionPills(em){
  if(!em||!em.top_emotions||!em.top_emotions.length) return '<span class="emotion-pill" style="color:#8d8f88"><i></i>情绪待考</span>';
  return em.top_emotions.map(function(row){return '<span class="emotion-pill" style="color:'+row.color+'"><i></i>'+esc(row.label)+' '+Math.round(row.share*100)+'%</span>';}).join('');
}
function vadMarkup(em){
  em=em||{};
  var rows=[['愉悦',dimPct(em.valence,true),'#a87527'],['激越',dimPct(em.arousal,false),'#b64b3f'],['掌控',dimPct(em.dominance,true),'#26786e']];
  return '<div class="vad">'+rows.map(function(row){return '<div class="vad-item"><b>'+row[0]+' '+row[1]+'</b><div class="meter"><i style="width:'+row[1]+'%;background:'+row[2]+'"></i></div></div>';}).join('')+'</div>';
}

// ---- 泳道散点数据（同龄碰撞时纵向微错开） ----
var scatterData = [];
poets.forEach(function(po, li){
  var byAge = {};
  po.poems.forEach(function(p){ (byAge[p.age]=byAge[p.age]||[]).push(p); });
  Object.keys(byAge).forEach(function(a){
    byAge[a].forEach(function(p, k){
      var off = (k===0)?0:((k%2===1?1:-1) * 0.17 * Math.ceil(k/2));
      scatterData.push({ value:[p.age, li+off], lane:li, p:p, poet:po });
    });
  });
});
var stageData = [];
poets.forEach(function(po, li){
  po.stages.forEach(function(s, si){
    stageData.push({ value:[Math.max(1,s.age0), s.age1+1, li, si%2], si:si, label:s.label, y0:s.y0, y1:s.y1, color:po.color, poet:po.name });
  });
});

var chart = echarts.init(document.getElementById('lane'));
var X_LO = AGE_LO-1, X_HI = AGE_HI+1;
function renderStage(params, api){
  var d=stageData[params.dataIndex];
  var a0=Math.max(X_LO, api.value(0)), a1=Math.min(X_HI, api.value(1));
  if (a1<=a0) return null;
  var li=api.value(2), par=api.value(3);
  var x0=api.coord([a0, 0]), x1=api.coord([a1, 0]);
  var yTop=api.coord([0, li-0.42])[1], yBot=api.coord([0, li+0.42])[1];
  var rect={x:x0[0], y:yTop, width:x1[0]-x0[0], height:yBot-yTop};
  var group={type:'group', children:[{type:'rect', shape:rect, style:{fill:d.color, opacity: par? .13:.06}}]};
  if (rect.width>84){
    group.children.push({type:'text', silent:true, style:{x:x0[0]+5, y:yTop+11, text:d.label, fill:d.color, opacity:.75, font:'10px "Microsoft YaHei"'}});
  }
  if (d.si===0){ // 每条泳道左侧写诗人名
    group.children.push({type:'text', silent:true, style:{x:12, y:(yTop+yBot)/2, textVerticalAlign:'middle', text:d.poet, fill:d.color, font:'16px KaiTi, STKaiti, serif', fontWeight:'bold'}});
    group.children.push({type:'text', silent:true, style:{x:12, y:(yTop+yBot)/2+16, textVerticalAlign:'middle', text:'生'+poets[li].birth, fill:'#5a615c', font:'10px "Microsoft YaHei"'}});
  }
  return group;
}
function fmtPoem(d){
  var p=d.p, po=d.poet;
  var em=p.emotion||{};
  var yr = p.year_start===p.year_end ? (p.year_start+'年') : (p.year_start+'–'+p.year_end+'年');
  var badges = '<span style="border:1px solid #a87527;color:#a87527;border-radius:8px;padding:0 5px;font-size:11px;">候选·'+p.grade+'级</span>'
    + ' <span style="border:1px solid #c9cfc8;color:#5a615c;border-radius:8px;padding:0 5px;font-size:11px;">'+p.precision+'</span>';
  var ev=(em.evidence||[]).slice(0,6).join('、');
  return '<div style="max-width:300px;line-height:1.6;">'
    +'<b style="color:'+po.color+';">'+po.name+'</b> · <b>《'+p.title+'》</b><br>'
    + yr +' · 虚岁 '+p.age+' 岁 '+badges+'<br>'
    +'分期：'+p.period+'<br>'
    +'主情绪：<b style="color:'+(em.color||'#8d8f88')+'">'+esc(em.primary_label||'情绪未定')+'</b> · 置信'+esc(em.confidence_label||'低')+'<br>'
    +'描述：'+esc(em.summary||'待考')+'<br>'
    +'VAD：愉悦'+dimPct(em.valence,true)+' / 激越'+dimPct(em.arousal,false)+' / 掌控'+dimPct(em.dominance,true)+'<br>'
    +(ev?('证据词：'+esc(ev)+'<br>'):'')
    +(p.top.length?('高频意象：'+p.top.join('、')+'<br>'):'')
    +(p.line?('<span style="font-family:KaiTi,STKaiti,serif;color:#5a615c;">'+p.line+'</span>'):'')
    +'</div>';
}
var baseOpt = {
  animation:false,
  grid:{left:78, right:26, top:20, bottom:44},
  tooltip:{trigger:'item', backgroundColor:'#fbfcfa', borderColor:'#c9cfc8', textStyle:{color:'#252b27', fontSize:12},
    formatter:function(pr){
      if (pr.seriesIndex===0){ var d=stageData[pr.dataIndex]; return d.poet+' · '+d.label+'（'+d.y0+'–'+d.y1+'，虚岁'+Math.max(1,d.value[0])+'–'+(d.value[1]-1)+'）'; }
      return fmtPoem(scatterData[pr.dataIndex]);
    }},
  xAxis:{type:'value', min:AGE_LO-1, max:AGE_HI+1, interval:5,
    axisLabel:{formatter:'{value}岁', color:'#5a615c'}, axisLine:{lineStyle:{color:'#c9cfc8'}},
    splitLine:{lineStyle:{color:'#e4e8e2', type:'dashed'}}, name:'虚岁', nameTextStyle:{color:'#5a615c'}},
  yAxis:{type:'value', min:-0.6, max:N-0.4, inverse:true,
    axisLabel:{show:false}, axisLine:{show:false}, axisTick:{show:false}, splitLine:{show:false}},
  series:[
    {type:'custom', renderItem:renderStage, data:stageData, z:1, silent:false},
    {type:'scatter', data:[], z:5,
     markLine:{silent:true, symbol:'none', animation:false,
       lineStyle:{color:'#b64b3f', width:1.4, type:'solid', opacity:.75},
       label:{show:true, formatter:function(mp){return mp.value+'岁';}, color:'#b64b3f', fontSize:11},
       data:[{xAxis:35}]}}
  ]
};
function scatterItems(t){
  return scatterData.map(function(d){
    var inWin = Math.abs(d.p.age - t) <= 3;
    var em=d.p.emotion||{};
    return { value:d.value, symbolSize:symSize(d.p.hits),
      itemStyle:{ color:em.color||sentiColor(d.p.senti), opacity: inWin? .95 : .18,
        borderColor: inWin? '#252b27':'transparent', borderWidth: inWin? .8 : 0 } };
  });
}
function renderChart(t){
  baseOpt.series[1].data = scatterItems(t);
  baseOpt.series[1].markLine.data = [{xAxis:t}];
  chart.setOption(baseOpt);
}

// ---- 卡片与导语 ----
function esc(s){ return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
function renderCards(t){
  var box = document.getElementById('cardBox');
  var htm = '', parts = [];
  poets.forEach(function(po){
    var win = po.poems.filter(function(p){ return Math.abs(p.age-t)<=3; })
                      .sort(function(a,b){ return Math.abs(a.age-t)-Math.abs(b.age-t) || b.hits-a.hits; });
    if (win.length){
      var p = win[0];
      var em=p.emotion||{};
      parts.push('<b style="color:'+po.color+'">'+po.name+'</b>'+p.age+'岁写《'+esc(p.title)+'》'
        +'（<span style="color:'+(em.color||'#8d8f88')+'">'+esc(em.primary_label||'情绪未定')+'</span> · '+esc((em.adjectives||['待考']).slice(0,2).join('、'))+'）');
      var extra = win.length>1 ? '<div class="meta">同窗口另有 '+(win.length-1)+' 首：'+win.slice(1,3).map(function(q){return '《'+esc(q.title)+'》'+q.age+'岁';}).join('、')+(win.length>3?'…':'')+'</div>' : '';
      htm += '<div class="card" style="border-left-color:'+po.color+'">'
        +'<div class="who" style="color:'+po.color+'">'+po.name+'</div>'
        +'<div class="title">《'+esc(p.title)+'》</div>'
        +'<div class="meta">'+(p.year_start===p.year_end?p.year_start:(p.year_start+'–'+p.year_end))+'年 · 虚岁'+p.age+'岁 · '+esc(p.period)+'</div>'
        +(p.line?('<div class="line">'+esc(p.line)+'</div>'):'')
        +'<div class="emotion-title" style="color:'+(em.color||'#5a615c')+'">'+esc(em.summary||'情绪待考')
        +' <span class="confidence">置信'+esc(em.confidence_label||'低')+'</span></div>'
        +'<div class="emotion-pills">'+emotionPills(em)+'</div>'
        +vadMarkup(em)
        +((em.evidence||[]).length?('<div class="evidence">证据词：'+esc(em.evidence.slice(0,7).join('、'))+'</div>'):'')
        +'<div class="tags"><span class="tag cand">候选·'+p.grade+'级</span><span class="tag">'+esc(p.precision)+'</span>'
        +(em.mixed?('<span class="tag">复合情绪</span>'):'')
        +'<span class="tag">意象'+p.hits+'</span></div>'
        + extra +'</div>';
    } else {
      var near = null;
      po.poems.forEach(function(p){ if (!near || Math.abs(p.age-t)<Math.abs(near.age-t)) near = p; });
      htm += '<div class="card empty" style="border-left-color:'+po.color+'">'
        +'<div class="who" style="color:'+po.color+'">'+po.name+'</div>'
        +'<div class="meta">该年龄窗口（'+t+'±3岁）暂无可系年诗。</div>'
        +(near?('<div class="meta" style="margin-top:6px;">最近记录：'+near.age+'岁《'+esc(near.title)+'》（'+near.year_start+(near.year_start===near.year_end?'':'–'+near.year_end)+'年）</div>'):'')
        +'</div>';
    }
  });
  box.innerHTML = htm;
  document.getElementById('headline').innerHTML = parts.length
    ? '同样 <b>'+t+'</b> 岁——' + parts.join('；') + '。'
    : '同样 <b>'+t+'</b> 岁——这一窗口六人均无可系年诗，左右拖动看看邻近年龄。';
}

function update(t){
  t = Math.max(AGE_LO, Math.min(AGE_HI, t|0));
  slider.value = t;
  document.getElementById('ageVal').textContent = t;
  document.getElementById('ageVal2').textContent = t;
  renderChart(t);
  renderCards(t);
  var btns = document.querySelectorAll('#presetBox .btn');
  for (var i=0;i<btns.length;i++){ btns[i].classList.toggle('on', +btns[i].dataset.age===t); }
}

// 快捷按钮（预设若无数据，构建时已回退到最近有数据年龄）
var pb = document.getElementById('presetBox');
DATA.presets.forEach(function(pr){
  var b = document.createElement('button');
  b.className = 'btn'; b.dataset.age = pr.use;
  b.textContent = pr.want===pr.use ? (pr.want+'岁') : (pr.want+'岁→'+pr.use+'岁');
  b.title = pr.want===pr.use ? ('跳到'+pr.want+'岁') : (pr.want+'岁窗口无数据，跳到最近的'+pr.use+'岁');
  b.addEventListener('click', function(){ update(pr.use); });
  pb.appendChild(b);
});
slider.addEventListener('input', function(){ update(+slider.value); });
window.addEventListener('resize', function(){ chart.resize(); });
update(35);
})();
</script>
</body>
</html>
"""

if __name__ == "__main__":
    build()
