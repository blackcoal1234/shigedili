# -*- coding: utf-8 -*-
"""平行时空 759：李白遇赦 vs 杜甫石壕 + 一镜到底流放夜郎动画。

零参数运行：
    python 数据可视化脚本/viz_33_year759.py

产出：
    output/33_平行时空759.html
    output/assets/competition/year759_data.json
"""
from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
POEMS_PATH   = ROOT / "data" / "poems.json"
VERIFIED_PATH = ROOT / "data" / "reviewed" / "verified_poem_contexts.csv"
LIBAI_CSV    = ROOT / "data" / "candidates" / "libai_spirit_chronology.csv"
DUFU_CSV     = ROOT / "data" / "candidates" / "dufu_spirit_chronology.csv"
DICT_PATH    = ROOT / "data" / "spirit_image_dict.py"
OUT_HTML     = ROOT / "output" / "33_平行时空759.html"
OUT_JSON     = ROOT / "output" / "assets" / "competition" / "year759_data.json"

NAV_ITEMS = [
    ("30_诗行万里_参赛版.html",   "总入口"),
    ("31_凝望罗盘.html",          "凝望罗盘"),
    ("32_身与心双层地图.html",    "身与心"),
    ("33_平行时空759.html",       "平行时空"),
    ("34_一字识诗人.html",        "一字识诗"),
    ("35_两种孤独与夸张签名.html","孤独·夸张"),
    ("36_同龄对齐.html",          "同龄对齐"),
    ("37_可听的诗.html",          "可听的诗"),
]


# ─────────────────────── helpers ────────────────────────────────────────────

def load_poems() -> dict[tuple[str,str], str]:
    raw = json.loads(POEMS_PATH.read_text(encoding="utf-8"))
    poems = raw if isinstance(raw, list) else raw.get("poems", [])
    idx: dict[tuple[str,str], str] = {}
    for p in poems:
        author = p.get("author") or p.get("poet") or ""
        title  = (p.get("title") or "").strip()
        body   = (p.get("body")  or "").strip()
        if author and title and body:
            idx[(author, title)] = body
    return idx


def split_lines(body: str) -> list[str]:
    lines = []
    for part in re.split(r"[。！？；\n]", body or ""):
        part = part.strip(" ，、：:；;。！？\t\r\n")
        if part:
            lines.append(part)
    return lines


def load_spirit_dict() -> list[tuple[str, str, str | None, float, int | None, str]]:
    """Parse spirit_image_dict.py and return the SPIRIT_DICT list."""
    src = DICT_PATH.read_text(encoding="utf-8")
    entries = []
    for m in re.finditer(
        r'\(\s*"([^"]+)"\s*,\s*"([^"]+)"\s*,\s*("([^"]+)"|None)\s*,'
        r'\s*([-\d.]+)\s*,\s*(\d+|None)\s*,\s*"([^"]*)"\s*\)',
        src,
    ):
        word, category = m.group(1), m.group(2)
        cluster = m.group(4) if m.group(3) != "None" else None
        sentiment = float(m.group(5))
        scale_raw = m.group(6)
        scale = int(scale_raw) if scale_raw != "None" else None
        entries.append((word, category, cluster, sentiment, scale, m.group(7)))
    # sort longest first for greedy match
    entries.sort(key=lambda e: len(e[0]), reverse=True)
    return entries


def emotion_color(val: float) -> str:
    """Map [-1, 1] sentiment to a rgba colour."""
    if val >= 0.15:
        # green-jade (豪情)
        t = min(1.0, val / 0.8)
        r = int(38  + (80  - 38)  * t)
        g = int(120 + (180 - 120) * t)
        b = int(110 + (80  - 110) * t)
    elif val <= -0.15:
        # cinnabar-red (愁苦)
        t = min(1.0, -val / 0.8)
        r = int(182 + (220 - 182) * t)
        g = int(74  + (40  - 74)  * t)
        b = int(63  + (40  - 63)  * t)
    else:
        r, g, b = 180, 178, 170   # neutral stone
    return f"rgba({r},{g},{b},0.35)"


def score_line(line: str, spirit: list) -> tuple[float, list[str]]:
    """Return (sentiment_avg, [matched_words]) for a poem line."""
    text = line
    hits: list[str] = []
    scores: list[float] = []
    for word, _, _, sent, _, _ in spirit:
        if word in text:
            hits.append(word)
            scores.append(sent)
            text = text.replace(word, "·" * len(word), 1)
    avg = sum(scores) / len(scores) if scores else 0.0
    return avg, hits


def lookup_poem(poems_idx: dict, author: str, title: str) -> str:
    aliases = {
        ("李白", "客中行"): "客中作",
        ("李白", "秋浦歌·其十五"): "秋浦歌十七首·十五",
        ("李白", "临路歌"): "临终歌",
    }
    body = poems_idx.get((author, title), "")
    if not body:
        body = poems_idx.get((author, aliases.get((author, title), title)), "")
    return body


def grade_badge(grade: str, source: str) -> str:
    if grade in ("A", "B"):
        cls = "badge grade-b"
        text = f"{grade}级·已在线核实"
    elif grade == "C":
        cls = "badge grade-c"
        text = "C级·推定"
    else:
        cls = "badge"
        text = f"{grade}级"
    badge = f'<span class="{cls}">{text}</span>'
    if "candidate" in (source or "").lower() or grade not in ("A", "B"):
        badge += ' <span class="badge" style="border-color:#9c7b3d;color:#9c7b3d">候选/推定</span>'
    return badge


# ─────────────────────── data builders ──────────────────────────────────────

def build_collision_poems(poems_idx: dict, spirit: list) -> dict:
    """Build the 759 and 757 side-by-side poem data."""
    def poem_data(author: str, title: str, year: int,
                  place: str, grade: str, status: str,
                  note: str = "") -> dict:
        body  = lookup_poem(poems_idx, author, title)
        lines = split_lines(body)
        scored = []
        for ln in lines:
            val, hits = score_line(ln, spirit)
            scored.append({
                "text":  ln,
                "val":   round(val, 3),
                "hits":  hits,
                "color": emotion_color(val),
            })
        overall = (sum(s["val"] for s in scored) / len(scored)) if scored else 0.0
        return {
            "author": author, "title": title, "year": year,
            "place": place, "grade": grade, "status": status,
            "note": note,
            "lines": scored,
            "overall_val": round(overall, 3),
            "badge_html": grade_badge(grade, status),
        }

    y759_libai = poem_data(
        "李白", "早发白帝城", 759,
        "奉节白帝城（今重庆市奉节县）", "B", "verified",
        "遇赦返江陵，轻舟已过万重山",
    )
    y759_dufu = poem_data(
        "杜甫", "石壕吏", 759,
        "三门峡石壕村（今河南省三门峡市）", "B", "candidate",
        "乱世，一个老妇在月夜被征役",
    )
    y757_libai = poem_data(
        "李白", "永王东巡歌·其一", 757,
        "浔阳（今江西省九江市）", "B", "candidate",
        "入永王幕，祸根伏笔",
    )
    y757_dufu = poem_data(
        "杜甫", "春望", 757,
        "长安（今陕西省西安市）", "B", "verified",
        "陷贼中，国破山河在",
    )
    return {
        "year759": {"libai": y759_libai, "dufu": y759_dufu},
        "year757": {"libai": y757_libai, "dufu": y757_dufu},
    }


def build_animation_nodes(poems_idx: dict, spirit: list) -> list[dict]:
    """Build the 6-node Li Bai exile-to-amnesty journey."""
    raw_nodes = [
        ("永王东巡歌·其一", 757, "浔阳", "江西省九江市", 115.99, 29.71,
         "757年：入永王幕，祸根伏笔", "B", "candidate"),
        ("流夜郎赠辛判官",  758, "江夏", "湖北省武汉市", 114.30, 30.59,
         "758年：下狱获释，流放夜郎途中", "B", "candidate"),
        ("上三峡",          759, "巫山", "重庆市巫山县", 110.08, 31.07,
         "759年：入三峡，三朝上黄牛，三暮行太迟", "B", "candidate"),
        ("早发白帝城",      759, "白帝城", "重庆市奉节县", 109.57, 31.02,
         "759年：遇赦！轻舟已过万重山", "B", "verified"),
        ("渡荆门送别",      725, None, None, 112.20, 31.04,
         "（行程推定）顺江东下荆门", "C", "candidate"),  # fallback node
        ("与夏十二登岳阳楼", 759, "岳阳楼", "湖南省岳阳市", 113.09, 29.36,
         "759年遇赦后：雁引愁心去，山衔好月来", "B", "candidate"),
    ]

    nodes = []
    for title, year, place_name, place_modern, lon, lat, event, grade, status in raw_nodes:
        if title is None:
            continue
        body  = lookup_poem(poems_idx, "李白", title)
        lines = split_lines(body)
        scored = []
        for ln in lines:
            val, hits = score_line(ln, spirit)
            scored.append({"text": ln, "val": round(val, 3), "hits": hits,
                           "color": emotion_color(val)})
        overall = (sum(s["val"] for s in scored) / len(scored)) if scored else 0.0
        nodes.append({
            "title":        title,
            "year":         year,
            "place":        place_name or "行程推定",
            "place_modern": place_modern or "",
            "lon":          lon,
            "lat":          lat,
            "event":        event,
            "grade":        grade,
            "status":       status,
            "badge_html":   grade_badge(grade, status),
            "lines":        scored,
            "overall_val":  round(overall, 3),
            "is_turning_point": title == "早发白帝城",
        })
    return nodes


# ─────────────────────── HTML builder ───────────────────────────────────────

def nav_html(current: str) -> str:
    items = []
    for href, label in NAV_ITEMS:
        cls = 'class="active"' if href == current else ""
        items.append(f'<a href="{href}" {cls}>{label}</a>')
    return "<footer>" + "".join(items) + "</footer>"


def poem_columns_html(p1: dict, p2: dict, label1: str, label2: str,
                      color1: str, color2: str) -> str:
    def col(p: dict, color: str) -> str:
        lines_html = ""
        for ln in p["lines"]:
            lines_html += (
                f'<div class="poem-line" style="border-left:3px solid {ln["color"]};'
                f'padding-left:6px;margin:2px 0;font-family:KaiTi,STKaiti,serif;'
                f'font-size:19px">{ln["text"]}</div>'
            )
        return f"""
<div class="poem-col" style="border-top:4px solid {color};padding:16px;
     background:#fff;border-radius:4px;min-width:0">
  <div style="font-size:12px;color:#6f756f;margin-bottom:6px">{p['badge_html']}</div>
  <h3 style="font-family:KaiTi,STKaiti,serif;font-size:22px;margin:0 0 4px">
    《{p['title']}》</h3>
  <div style="font-size:12px;color:#6f756f;margin-bottom:10px">
    {p['year']}年 · {p['place']}</div>
  <div style="font-size:13px;color:#444;border-left:3px solid #a87527;
       padding:6px 8px;background:#f7f3e9;margin-bottom:10px">{p['note']}</div>
  <div class="poem-lines">{lines_html}</div>
  <div style="margin-top:10px;font-size:12px;color:#6f756f">
    情感均值 <b>{p['overall_val']:+.2f}</b>
    （词典命中 {sum(len(l['hits']) for l in p['lines'])} 处）
  </div>
</div>"""

    return f"""
<div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:12px">
  <div>
    <div style="font-size:13px;color:{color1};font-weight:700;margin-bottom:6px">{label1}</div>
    {col(p1, color1)}
  </div>
  <div>
    <div style="font-size:13px;color:{color2};font-weight:700;margin-bottom:6px">{label2}</div>
    {col(p2, color2)}
  </div>
</div>"""


def build_html(collision: dict, anim_nodes: list[dict]) -> str:
    nodes_json = json.dumps(anim_nodes, ensure_ascii=False)

    def slim(p: dict) -> dict:
        return {k: p[k] for k in
                ("author", "title", "year", "place", "overall_val",
                 "badge_html", "lines", "note")}

    col_json = json.dumps({
        "y759": {"libai": slim(collision["year759"]["libai"]),
                 "dufu":  slim(collision["year759"]["dufu"])},
        "y757": {"libai": slim(collision["year757"]["libai"]),
                 "dufu":  slim(collision["year757"]["dufu"])},
    }, ensure_ascii=False)

    cols759 = poem_columns_html(
        collision["year759"]["libai"], collision["year759"]["dufu"],
        "李白  ·  遇赦返江陵", "杜甫  ·  石壕征役",
        "#426f94", "#7a5c3d",
    )
    cols757 = poem_columns_html(
        collision["year757"]["libai"], collision["year757"]["dufu"],
        "李白  ·  入永王幕", "杜甫  ·  陷贼长安",
        "#426f94", "#7a5c3d",
    )
    nav = nav_html("33_平行时空759.html")
    static_fallback = "\n".join(
        f"<li>{n['year']}年 {n['place']} — 《{n['title']}》</li>"
        for n in anim_nodes
    )

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>平行时空759 · 诗行万里</title>
<script src="assets/pyecharts/v6/echarts.min.js"></script>
<script src="assets/pyecharts/v6/maps/china.js"></script>
<style>
:root{{--paper:#f2f4f0;--ink:#252b27;--muted:#6f756f;--line:#d9ddd7;
      --red:#b64b3f;--jade:#26786e;--gold:#a87527;--blue:#426f94;}}
*{{box-sizing:border-box}}html{{scroll-behavior:smooth}}
body{{margin:0;background:var(--paper);color:var(--ink);
     font-family:"Microsoft YaHei",sans-serif;line-height:1.7}}
h1,h2,h3{{font-family:KaiTi,STKaiti,"Microsoft YaHei",serif;font-weight:700}}
.wrap{{width:min(1200px,calc(100% - 32px));margin:0 auto}}
.hero{{padding:40px 0 28px;border-bottom:1px solid var(--line)}}
.eyebrow{{font-size:12px;color:var(--red);font-weight:700;letter-spacing:.05em}}
.hero h1{{margin:6px 0 4px;font-size:clamp(28px,4vw,48px)}}
.hero p{{color:var(--muted);max-width:820px;margin:6px 0}}
.section{{padding:36px 0}}
.section-title{{display:flex;align-items:baseline;gap:10px;margin-bottom:14px}}
.section-title .no{{color:var(--red);font-size:15px;font-weight:700}}
.section-title h2{{font-size:24px;margin:0}}
.badge{{display:inline-flex;border:1px solid currentColor;border-radius:99px;
        padding:2px 8px;font-size:11px;margin-right:4px}}
.grade-b{{color:var(--jade)}}.grade-c{{color:var(--gold)}}
#map759{{height:400px;border:1px solid var(--line);border-radius:6px;background:#edf0e8}}
.collision-label{{font-size:20px;font-family:KaiTi,STKaiti,serif;color:var(--red);
  text-align:center;padding:16px 0 8px;font-weight:700}}
.anim-wrap{{display:grid;grid-template-columns:1fr 360px;gap:0;border:1px solid var(--line);
  border-radius:6px;overflow:hidden;background:#fff;min-height:460px}}
#animMap{{height:460px;width:100%;background:#edf0e8}}
.anim-panel{{padding:20px;display:flex;flex-direction:column;gap:11px;
  border-left:1px solid var(--line);overflow-y:auto}}
.anim-controls{{display:flex;gap:8px;flex-wrap:wrap}}
.btn{{border:1px solid #aeb7ad;background:#fff;color:var(--ink);border-radius:4px;
  padding:8px 14px;cursor:pointer;font:inherit}}
.btn.primary{{background:var(--red);border-color:var(--red);color:#fff}}
.btn:disabled{{opacity:.4;cursor:default}}
.progress-bar{{height:4px;background:#e4e8e2;border-radius:2px;overflow:hidden}}
.progress-fill{{height:100%;background:var(--red);transition:width .4s ease;width:0}}
.anim-title{{font-family:KaiTi,STKaiti,serif;font-size:22px;font-weight:700;
  border-top:3px solid var(--blue);padding-top:10px}}
.anim-meta{{font-size:12px;color:var(--muted)}}
.anim-event{{font-size:13px;color:#444;border-left:3px solid var(--gold);
  padding:6px 8px;background:#f7f3e9}}
.anim-poem{{font-family:KaiTi,STKaiti,serif;font-size:18px;line-height:1.8}}
.anim-poem .pl{{opacity:0;transform:translateY(4px);animation:fdin .5s ease forwards}}
.anim-poem .pl:nth-child(2){{animation-delay:.1s}}
.anim-poem .pl:nth-child(3){{animation-delay:.2s}}
.anim-poem .pl:nth-child(4){{animation-delay:.3s}}
@keyframes fdin{{to{{opacity:1;transform:none}}}}
.turning-point .anim-title{{border-color:#b64b3f;color:#b64b3f}}
.emotion-bar{{display:grid;grid-template-columns:1fr auto;gap:4px;font-size:12px;color:var(--muted)}}
.emotion-track{{grid-column:1/-1;height:4px;background:#e4e8e2}}
.emotion-fill{{height:100%;background:var(--blue);transition:width .6s ease}}
.anim-source{{font-size:11px;color:var(--muted);margin-top:auto;
  border-top:1px dashed var(--line);padding-top:8px}}
details.method{{border:1px solid var(--line);background:#fff;border-radius:5px;padding:0 16px}}
details.method summary{{cursor:pointer;padding:12px 0;font-weight:700}}
.method-body{{border-top:1px solid var(--line);padding:12px 0 16px;font-size:13px;color:var(--muted)}}
.method-body li{{margin:5px 0}}
footer{{border-top:1px solid var(--line);padding:20px 0 36px;text-align:center}}
footer a{{color:var(--blue);font-size:13px;margin:0 8px;text-decoration:none}}
footer a.active{{color:var(--red);font-weight:700}}
@media(max-width:820px){{
  .anim-wrap{{grid-template-columns:1fr}}
  #animMap{{height:320px}}
  .anim-panel{{border-left:0;border-top:1px solid var(--line)}}
  .section{{padding:24px 0}}
}}
</style>
</head>
<body>

<header class="hero"><div class="wrap">
  <div class="eyebrow">33 · 平行时空</div>
  <h1>平行时空 759</h1>
  <p>同一年，同一个帝国：一个人狂喜顺流而下，一个人在乱世里记下抓人的差役。</p>
  <p style="font-size:13px">情感值由 197 词条意象词典计算，描述作品文本特征，不代表诗人真实心理。</p>
</div></header>

<main class="wrap">

<section class="section">
  <div class="section-title"><span class="no">壹</span><h2>759年·两枚坐标</h2></div>
  <p style="color:var(--muted);margin-bottom:12px">
    安史之乱第四年。李白在奉节遇赦，写下"轻舟已过万重山"；
    杜甫在石壕村，目睹差役夜晚抓人，写下《石壕吏》。
  </p>
  <div id="map759"></div>
  <div class="collision-label">同一年 · 同一个帝国</div>
  {cols759}
</section>

<section class="section" style="border-top:1px solid var(--line);padding-top:28px">
  <div class="section-title"><span class="no">贰</span><h2>757年·同一年的两首诗</h2></div>
  <p style="color:var(--muted);margin-bottom:12px">
    安史之乱第二年。李白入永王幕，写豪迈军歌；
    杜甫陷贼长安，写"烽火连三月，家书抵万金"。
    <span class="badge" style="border-color:#9c7b3d;color:#9c7b3d">候选/推定</span>
    <span class="badge grade-b">B级·已在线核实</span>
  </p>
  {cols757}
</section>

<section class="section" style="border-top:1px solid var(--line);padding-top:28px">
  <div class="section-title"><span class="no">叁</span><h2>一镜到底：流放夜郎·遇赦而返</h2></div>
  <p style="color:var(--muted);margin-bottom:14px">
    757→759，李白从入永王幕获罪，到流放夜郎，最终在白帝城遇赦返舟。
    点击"播放"跟随轻舟走完这段路。
  </p>
  <div class="anim-controls" style="margin-bottom:12px">
    <button class="btn primary" id="btnPlay">▶ 播放</button>
    <button class="btn" id="btnEnd">跳到结尾</button>
    <button class="btn" id="btnReplay" disabled>↺ 重播</button>
  </div>
  <div class="progress-bar" style="margin-bottom:12px">
    <div class="progress-fill" id="animProgress"></div>
  </div>
  <div class="anim-wrap">
    <div id="animMap"></div>
    <div class="anim-panel" id="animPanel">
      <div class="anim-title" id="animTitle">点击「播放」开始</div>
      <div class="anim-meta"  id="animMeta"></div>
      <div class="anim-event" id="animEvent" style="display:none"></div>
      <div class="anim-poem"  id="animPoem"></div>
      <div class="emotion-bar">
        <span id="emotionLabel">情感值</span><span id="emotionVal"></span>
        <div class="emotion-track"><div class="emotion-fill" id="emotionFill"></div></div>
      </div>
      <div class="anim-source" id="animSource"></div>
    </div>
  </div>
  <noscript>
    <p style="color:var(--muted);margin-top:12px">需要 JavaScript 查看动画；静态节点列表：</p>
    <ol style="font-size:14px;color:var(--muted);padding-left:1.5em">{static_fallback}</ol>
  </noscript>
</section>

<section class="section" style="border-top:1px solid var(--line);padding-top:24px">
  <details class="method">
    <summary>方法与数据说明</summary>
    <div class="method-body"><ul>
      <li><b>情感计算</b>：197 词条意象词典最长匹配，取命中词情感值均值；无命中记 0（标"中性"）。</li>
      <li><b>系年来源</b>：审核记录（A/B 级）与候选系年（B/C 级）分开标注；候选一律带"候选/推定"徽章。</li>
      <li><b>等级说明</b>：A/B 已在线核实（cnkgraph 或古诗文网）；C 为年谱题录未在线核实；D 不进计算。</li>
      <li><b>动画路线</b>：节点按系年顺序排列，连线只表示时间先后，不代表实际道路。</li>
      <li><b>边界声明</b>：情感值只描述文本特征，不断言诗人真实心理。</li>
      <li><b>数据来源</b>：cnkgraph 唐宋文学编年地图、古诗文网（guwendao.net）。</li>
    </ul></div>
  </details>
</section>
</main>

{nav}

<script>
const NODES = {nodes_json};

(function(){{
  const chart = echarts.init(document.getElementById('map759'));
  chart.setOption({{
    backgroundColor:'#edf0e8',
    geo:{{map:'china',roam:false,
      itemStyle:{{areaColor:'#e8ebe4',borderColor:'#c8cdc6'}},
      emphasis:{{itemStyle:{{areaColor:'#dde1da'}}}}}},
    series:[{{
      type:'effectScatter',coordinateSystem:'geo',
      rippleEffect:{{brushType:'stroke',scale:4}},symbolSize:14,
      data:[
        {{name:'李白·白帝城（遇赦）',value:[109.57,31.02],itemStyle:{{color:'#426f94'}}}},
        {{name:'杜甫·石壕村',value:[111.18,34.77],itemStyle:{{color:'#7a5c3d'}}}},
      ],
      label:{{show:true,position:'right',formatter:p=>p.name,fontSize:12,color:'#252b27'}},
    }}],
    tooltip:{{trigger:'item'}},
  }});
  window.addEventListener('resize',()=>chart.resize());
}})();

(function(){{
  const animMap=echarts.init(document.getElementById('animMap'));
  let currentIdx=-1,playing=false,raf=null,startTs=0;
  const DWELL_MS=4500;

  function baseOption(idx){{
    const center=idx>=0?[NODES[idx].lon,NODES[idx].lat]:[112,30];
    const zoom=idx>=0?5.5:3.8;
    const lineData=[];
    for(let i=0;i<Math.max(idx,0);i++)
      lineData.push({{coords:[[NODES[i].lon,NODES[i].lat],[NODES[i+1].lon,NODES[i+1].lat]]}});
    const scatterData=NODES.slice(0,idx+1).map((n,i)=>
      ({{name:n.title,value:[n.lon,n.lat],
        itemStyle:{{color:i===idx?'#b64b3f':'#426f94'}},
        symbolSize:i===idx?16:8}}));
    return {{
      backgroundColor:'#edf0e8',
      geo:{{map:'china',roam:true,center,zoom,
        animationDurationUpdate:700,
        itemStyle:{{areaColor:'#e8ebe4',borderColor:'#c8cdc6'}},
        emphasis:{{itemStyle:{{areaColor:'#dde1da'}}}}}},
      series:[
        {{type:'lines',coordinateSystem:'geo',data:lineData,
          lineStyle:{{color:'#426f94',width:2,opacity:.75}},effect:{{show:false}}}},
        {{type:'scatter',coordinateSystem:'geo',data:scatterData,
          label:{{show:true,position:'right',
            formatter:p=>NODES[p.dataIndex]?.place||'',
            fontSize:11,color:'#252b27'}}}},
      ],
    }};
  }}

  function renderPanel(n){{
    document.getElementById('animPanel').classList.toggle('turning-point',!!n.is_turning_point);
    document.getElementById('animTitle').textContent='《'+n.title+'》';
    document.getElementById('animMeta').textContent=
      n.year+'年 · '+n.place+(n.place_modern?' ('+n.place_modern+')':'');
    const ev=document.getElementById('animEvent');
    if(n.event){{ev.style.display='';ev.textContent=n.event;}}else ev.style.display='none';
    document.getElementById('animPoem').innerHTML=
      n.lines.map((l,i)=>
        `<div class="pl" style="border-left:3px solid ${{l.color}};padding-left:6px;`+
        `margin:2px 0;animation-delay:${{i*0.12}}s">${{l.text}}</div>`
      ).join('');
    const val=n.overall_val;
    document.getElementById('emotionLabel').textContent=
      val>0.1?'豪情 ↑':val<-0.1?'愁苦 ↓':'中性';
    document.getElementById('emotionVal').textContent=(val>=0?'+':'')+val.toFixed(2);
    const pct=Math.round((val+1)/2*100);
    document.getElementById('emotionFill').style.width=pct+'%';
    document.getElementById('emotionFill').style.background=
      val>0.1?'#26786e':val<-0.1?'#b64b3f':'#a87527';
    document.getElementById('animSource').innerHTML=
      n.badge_html+' '+n.grade+'级系年'+(n.status==='verified'?' · 已审核':' · 候选/推定');
    document.getElementById('animProgress').style.width=
      Math.round((currentIdx+1)/NODES.length*100)+'%';
  }}

  function goTo(idx){{
    if(idx<0||idx>=NODES.length)return;
    currentIdx=idx;
    animMap.setOption(baseOption(idx),{{notMerge:false}});
    renderPanel(NODES[idx]);
    document.getElementById('btnReplay').disabled=false;
  }}

  function playNext(){{
    if(currentIdx+1>=NODES.length){{playing=false;
      document.getElementById('btnPlay').textContent='▶ 播放';return;}}
    goTo(currentIdx+1);
    startTs=performance.now();
    raf=requestAnimationFrame(function tick(ts){{
      if(!playing)return;
      if(ts-startTs>=DWELL_MS)playNext();
      else raf=requestAnimationFrame(tick);
    }});
  }}

  document.getElementById('btnPlay').addEventListener('click',function(){{
    if(playing){{playing=false;this.textContent='▶ 播放';
      if(raf)cancelAnimationFrame(raf);}}
    else{{playing=true;this.textContent='⏸ 暂停';
      if(currentIdx<0)goTo(0);
      startTs=performance.now();
      raf=requestAnimationFrame(function tick(ts){{
        if(!playing)return;
        if(ts-startTs>=DWELL_MS)playNext();
        else raf=requestAnimationFrame(tick);
      }});}}
  }});
  document.getElementById('btnEnd').addEventListener('click',function(){{
    playing=false;if(raf)cancelAnimationFrame(raf);
    document.getElementById('btnPlay').textContent='▶ 播放';
    goTo(NODES.length-1);
    document.getElementById('animProgress').style.width='100%';
  }});
  document.getElementById('btnReplay').addEventListener('click',function(){{
    playing=false;if(raf)cancelAnimationFrame(raf);
    document.getElementById('btnPlay').textContent='▶ 播放';
    currentIdx=-1;
    document.getElementById('animProgress').style.width='0';
    animMap.setOption(baseOption(-1),{{notMerge:true}});
    document.getElementById('animTitle').textContent='点击「播放」开始';
    ['animMeta','animPoem','animSource'].forEach(id=>document.getElementById(id).textContent='');
    document.getElementById('animEvent').style.display='none';
    this.disabled=true;
  }});

  animMap.setOption(baseOption(-1));
  window.addEventListener('resize',()=>animMap.resize());
}})();
</script>
</body></html>"""


# ─────────────────────── main ───────────────────────────────────────────────

def main() -> None:
    print("Loading data…")
    poems_idx = load_poems()
    spirit    = load_spirit_dict()

    collision  = build_collision_poems(poems_idx, spirit)
    anim_nodes = build_animation_nodes(poems_idx, spirit)

    # remove the placeholder fallback node (渡荆门送别, year 725)
    anim_nodes = [n for n in anim_nodes if n["year"] >= 757]

    html = build_html(collision, anim_nodes)

    # validate basics before saving
    assert "NaN" not in html, "NaN found in HTML"
    assert "Infinity" not in html, "Infinity found in HTML"
    assert 'src="http' not in html, "Remote script found"
    assert '<meta name="viewport"' in html, "viewport meta missing"
    assert len(html.encode()) >= 5000, "HTML too small"

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(
        json.dumps({"collision": collision, "anim_nodes": anim_nodes},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    OUT_HTML.write_text(html, encoding="utf-8")
    print(f"  [ok] saved {OUT_HTML}  ({len(html.encode()):,} bytes)")
    print(f"  [ok] saved {OUT_JSON}")


if __name__ == "__main__":
    main()
