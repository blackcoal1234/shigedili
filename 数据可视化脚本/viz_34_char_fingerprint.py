# -*- coding: utf-8 -*-
"""viz_34 一字识诗人：字符级 log-odds 签名字云 + 「四字猜诗人」竞猜。

零参数可复跑。产出：
  - output/assets/competition/fingerprint_data.json  页面数据
  - output/34_一字识诗人.html                        参赛页（数据同时内嵌，file://直接可开）

算法口径：
  - Monroe, Colaresi & Quinn (2008) "Fightin' Words" 的
    log-odds with informative Dirichlet prior，以单字（字符级）为统计单元。
  - 对比组：六核心诗人各自语料 vs poems.json 当前全量背景语料（背景含其本人，任务给定口径，
    这会略微压低 z、结论偏保守，方法区如实说明）。
  - 先验：alpha_w = ALPHA0 * 背景频率(w)，ALPHA0 = 1000。
  - 去一切非汉字字符；自建停用字表（STOP_CHARS，方法区逐字列出）；
    该字须在该诗人语料中出现 >= MIN_COUNT 次才参与排名；每人取 z 降序前 20 字。
  - z 只用于各诗人内部排序与字号映射，不做跨诗人比较（样本量不同，方法区声明）。
"""
from __future__ import annotations

import json
import math
import random
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
POEMS_PATH = ROOT / "data" / "poems.json"
OUT_HTML = ROOT / "output" / "34_一字识诗人.html"
OUT_JSON = ROOT / "output" / "assets" / "competition" / "fingerprint_data.json"

POETS = [
    ("libai", "李白", "#426f94"),
    ("dufu", "杜甫", "#7a5c3d"),
    ("baijuyi", "白居易", "#26786e"),
    ("sushi", "苏轼", "#b64b3f"),
    ("luyou", "陆游", "#8a3b2f"),
    ("liqingzhao", "李清照", "#9c5d8f"),
]

STOP_STR = "之乎者也不无一有何以为是此其而已矣焉哉兮于与所自相得可若乃且但亦又复更未莫非岂皆或既然则故遂"
STOP_CHARS = set(STOP_STR)
ALPHA0 = 1000.0
MIN_COUNT = 3
TOP_N = 20
MAX_EXAMPLES = 8

HAN_ONLY = re.compile(r"[^一-鿿]")


# ---------------------------------------------------------------- 语料
def han_chars(text: str) -> str:
    return HAN_ONLY.sub("", text)


def split_display_lines(body: str):
    """按句号级标点切出可展示的证据句（保留句内逗号），过滤过短/过长（小序散句）。"""
    out = []
    for seg in re.split(r"[。！？；;\n]", body):
        seg = seg.strip().strip("，、：:,.")
        if not seg:
            continue
        if len(seg) > 30:          # 排除长散句（如诗前小序）
            continue
        if len(han_chars(seg)) < 4:
            continue
        out.append(seg)
    return out


def load_corpora():
    with open(POEMS_PATH, encoding="utf-8") as f:
        poems = json.load(f)
    bg_counter = Counter()
    bg_chars = 0
    per_poet = {k: [] for k, _, _ in POETS}
    name2key = {name: key for key, name, _ in POETS}
    for p in poems:
        who = p.get("poet") or p.get("author")
        text = han_chars(p["body"])
        bg_counter.update(text)
        bg_chars += len(text)
        if who in name2key:
            per_poet[name2key[who]].append(p)
    return poems, per_poet, bg_counter, bg_chars


# ---------------------------------------------------------------- log-odds
def log_odds_top(poet_counter: Counter, n_i: int, bg_counter: Counter, n_bg: int):
    """informative-Dirichlet-prior log-odds，返回 z 降序 [(ch, z, delta, cnt)]。"""
    rows = []
    for ch, yi in poet_counter.items():
        if ch in STOP_CHARS or yi < MIN_COUNT:
            continue
        yb = bg_counter[ch]
        a_w = ALPHA0 * yb / n_bg
        num_i = (yi + a_w) / (n_i + ALPHA0 - yi - a_w)
        num_b = (yb + a_w) / (n_bg + ALPHA0 - yb - a_w)
        delta = math.log(num_i) - math.log(num_b)
        var = 1.0 / (yi + a_w) + 1.0 / (yb + a_w)
        z = delta / math.sqrt(var)
        rows.append((ch, z, delta, yi))
    rows.sort(key=lambda r: (-r[1], -r[3], r[0]))
    return rows


def center_out_order(n: int):
    """把 z 降序序列重排成「大字居中、小字向两侧」的展示顺序（返回索引序列）。"""
    order = []
    for i in range(n):
        if i % 2 == 0:
            order.append(i)
        else:
            order.insert(0, i)
    return order


def collect_examples(poet_poems, ch: str):
    """该字原句：先每诗取首个命中句保证诗目多样，再补第二命中句，至多 MAX_EXAMPLES。"""
    first_pass, second_pass = [], []
    for p in poet_poems:
        hits = [ln for ln in split_display_lines(p["body"]) if ch in ln]
        if hits:
            first_pass.append({"l": hits[0], "t": p["title"]})
            for extra in hits[1:]:
                second_pass.append({"l": extra, "t": p["title"]})
    return (first_pass + second_pass)[:MAX_EXAMPLES]


# ---------------------------------------------------------------- 构建
def build():
    poems, per_poet, bg_counter, n_bg = load_corpora()
    rng = random.Random(3407)

    poets_out = []
    stat_parts = []
    for key, name, color in POETS:
        plist = per_poet[key]
        corpus = "".join(han_chars(p["body"]) for p in plist)
        counter = Counter(corpus)
        n_i = len(corpus)
        ranked = log_odds_top(counter, n_i, bg_counter, n_bg)[:TOP_N]
        assert len(ranked) == TOP_N, f"{name} 签名字不足 {TOP_N} 个（仅 {len(ranked)}）"
        top = []
        for ch, z, delta, cnt in ranked:
            ex = collect_examples(plist, ch)
            assert ex, f"{name} 的签名字「{ch}」找不到证据句"
            top.append({
                "ch": ch,
                "z": round(z, 2),
                "d": round(delta, 3),
                "cnt": cnt,
                "fp": round(cnt / n_i * 1000, 2),          # 每千字（本人）
                "fb": round(bg_counter[ch] / n_bg * 1000, 2),  # 每千字（背景）
                "ex": ex,
            })
        poets_out.append({
            "key": key, "name": name, "color": color,
            "n_poems": len(plist), "n_chars": n_i,
            "top": top, "cloud_order": center_out_order(len(top)),
        })
        stat_parts.append(f"{name}{len(plist)}首/{n_i}字")

    # ---- 竞猜题库：每人 2 题、共 12 题；4 字优先取「不与他人 top20 重合」的字 ----
    top_chars = {po["key"]: [t["ch"] for t in po["top"]] for po in poets_out}
    example_of = {po["key"]: {t["ch"]: t["ex"][0] for t in po["top"]} for po in poets_out}
    quiz = []
    for po in poets_out:
        key = po["key"]
        others = set()
        for k2, chs in top_chars.items():
            if k2 != key:
                others.update(chs)
        uniq = [c for c in top_chars[key] if c not in others]
        rest = [c for c in top_chars[key] if c in others]
        pool = (uniq + rest)[:8]
        assert len(pool) == 8
        for chars in (pool[0::2], pool[1::2]):
            chars = list(chars)
            rng.shuffle(chars)
            quiz.append({
                "a": key,
                "chars": [{"c": c,
                           "l": example_of[key][c]["l"],
                           "t": example_of[key][c]["t"]} for c in chars],
            })
    rng.shuffle(quiz)
    assert len(quiz) >= 10

    data = {
        "meta": {
            "page": "34_一字识诗人",
            "method": "char-level log-odds with informative Dirichlet prior (Monroe et al. 2008)",
            "alpha0": ALPHA0,
            "min_count": MIN_COUNT,
            "top_n": TOP_N,
            "stop_chars": STOP_STR,
            "n_bg_poems": len(poems),
            "n_bg_chars": n_bg,
            "note": "背景语料含六人本人诗作（任务给定口径，z 偏保守）；z 仅作各诗人内部排序，不跨诗人比较。",
        },
        "poets": poets_out,
        "quiz": quiz,
    }
    return data, stat_parts


# ---------------------------------------------------------------- 页面模板
HTML_TMPL = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="icon" href="data:,">
<title>一字识诗人 · 诗行万里</title>
<style>
:root{--paper:#f2f4f0;--ink:#252b27;--cinnabar:#b64b3f;--jade:#26786e;--gold:#a87527;--blue:#426f94;}
*{box-sizing:border-box;margin:0;padding:0;}
body{background:var(--paper);color:var(--ink);font-family:"Microsoft YaHei",sans-serif;line-height:1.7;}
h1,h2,h3,.kai{font-family:KaiTi,STKaiti,"Microsoft YaHei",serif;}
.wrap{max-width:1280px;margin:0 auto;padding:24px 16px 40px;}
header.top{text-align:center;padding:26px 12px 8px;}
header.top h1{font-size:34px;letter-spacing:6px;}
header.top .sub{color:#5a615c;margin-top:6px;font-size:14px;}
.panel{background:#fbfcfa;border:1px solid #dfe4de;border-radius:10px;padding:14px 16px;margin-top:16px;box-shadow:0 1px 3px rgba(37,43,39,.05);font-size:14px;color:#3c443f;}
.panel b{color:var(--cinnabar);}
.fgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:14px;margin-top:16px;}
.fcard{background:#fbfcfa;border:1px solid #dfe4de;border-top:3px solid #888;border-radius:10px;padding:12px 14px;}
.fhead{display:flex;justify-content:space-between;align-items:baseline;gap:8px;}
.fname{font-family:KaiTi,STKaiti,serif;font-size:22px;}
.fmeta{font-size:12px;color:#5a615c;}
.cloud{display:flex;flex-wrap:wrap;align-items:center;justify-content:center;gap:2px 10px;padding:12px 2px;min-height:150px;}
.cloud span{font-family:KaiTi,STKaiti,serif;cursor:pointer;line-height:1.25;transition:transform .12s;}
.cloud span:hover{transform:scale(1.18);text-shadow:0 1px 4px rgba(37,43,39,.28);}
.fhint{font-size:11px;color:#8a918b;text-align:center;}
.mask{position:fixed;inset:0;background:rgba(37,43,39,.45);display:none;z-index:50;align-items:center;justify-content:center;padding:16px;}
.mask.on{display:flex;}
.mbox{background:#fbfcfa;border:1px solid #dfe4de;border-radius:12px;max-width:600px;width:100%;max-height:80vh;overflow-y:auto;padding:18px 20px;}
.mhead{display:flex;align-items:center;gap:14px;border-bottom:1px dashed #d8ddd6;padding-bottom:10px;}
.mchar{font-family:KaiTi,STKaiti,serif;font-size:54px;line-height:1;}
.mwho{font-family:KaiTi,STKaiti,serif;font-size:18px;}
.mstats{font-size:12px;color:#5a615c;}
.mclose{margin-left:auto;border:none;background:transparent;font-size:24px;cursor:pointer;color:#5a615c;line-height:1;}
.mclose:hover{color:var(--cinnabar);}
.exline{margin-top:10px;font-size:14px;font-family:KaiTi,STKaiti,serif;}
.exline .src{color:#5a615c;font-size:12px;font-family:"Microsoft YaHei",sans-serif;margin-left:6px;white-space:nowrap;}
.hl{color:var(--cinnabar);font-weight:bold;}
.quiz{margin-top:30px;}
.quiz h2{font-size:24px;letter-spacing:3px;}
.qbar{display:flex;flex-wrap:wrap;gap:6px 20px;font-size:13px;color:#5a615c;align-items:center;margin-top:8px;}
.qbar b{color:var(--cinnabar);font-size:15px;}
.qchars{display:flex;justify-content:center;gap:14px;margin:18px 0 6px;flex-wrap:wrap;}
.qchar{width:78px;height:78px;background:#fbfcfa;border:1px solid #cfd6cf;border-radius:10px;display:flex;align-items:center;justify-content:center;font-family:KaiTi,STKaiti,serif;font-size:46px;box-shadow:2px 2px 0 #e2e6e0;}
.opts{display:flex;flex-wrap:wrap;justify-content:center;gap:10px;margin-top:12px;}
.opt{border:1.5px solid #888;background:#fbfcfa;border-radius:20px;padding:6px 18px;font-size:16px;font-family:KaiTi,STKaiti,serif;cursor:pointer;}
.opt:not(:disabled):hover{transform:translateY(-1px);box-shadow:0 2px 5px rgba(37,43,39,.15);}
.opt:disabled{cursor:default;opacity:.4;}
.opt.correct{color:#fff;opacity:1;}
.opt.wrong{opacity:1;background:#f0e0de;}
.qreveal{display:none;margin-top:16px;border-top:1px dashed #d8ddd6;padding-top:12px;font-size:14px;}
.qreveal.on{display:block;}
.qverdict{font-family:KaiTi,STKaiti,serif;font-size:18px;}
.qsrc{margin-top:8px;}
.btnq{margin-top:14px;border:1px solid var(--blue);color:var(--blue);background:transparent;border-radius:18px;padding:5px 22px;font-size:14px;cursor:pointer;font-family:inherit;}
.btnq:hover{background:var(--blue);color:#fff;}
.qfinal{display:none;text-align:center;padding:24px 12px;}
.qfinal .big{font-family:KaiTi,STKaiti,serif;font-size:30px;color:var(--cinnabar);}
details.method{margin-top:26px;background:#fbfcfa;border:1px solid #dfe4de;border-radius:10px;padding:12px 16px;font-size:13px;color:#3c443f;}
details.method summary{cursor:pointer;font-family:KaiTi,STKaiti,serif;font-size:16px;color:var(--ink);}
details.method li{margin:6px 0 6px 18px;}
details.method code{background:#eef1ec;border-radius:4px;padding:0 4px;font-size:12px;word-break:break-all;}
footer.nav{margin-top:34px;border-top:1px solid #d8ddd6;padding:16px 8px 30px;text-align:center;font-size:13px;}
footer.nav a{color:var(--blue);text-decoration:none;margin:0 9px;white-space:nowrap;line-height:2;}
footer.nav a:hover{color:var(--cinnabar);}
@media (max-width:480px){
  header.top h1{font-size:26px;letter-spacing:3px;}
  .qchar{width:62px;height:62px;font-size:38px;}
  .qchars{gap:10px;}
}
</style>
</head>
<body>
<div class="wrap">
<header class="top">
  <h1>一字识诗人</h1>
  <div class="sub">把六位诗人的用字习惯放进统计里——最「像他自己」的二十个字</div>
</header>

<section class="panel">
  以六人各自诗作为前景、全库 <b>__NBGP__ 首 / __NBGC__ 字</b>为背景，
  用字符级 <b>log-odds（informative Dirichlet prior）</b>算每个字的独特度 z 分数：
  z 越高，这个字越是他的「签名」。字号即 z 分数；点任意字可展开该字在其诗中的原句证据。
</section>

<div class="fgrid" id="fgrid"></div>

<section class="quiz panel" id="quizSec">
  <h2 class="kai">四字猜诗人</h2>
  <div class="qbar">
    <span>第 <b id="qNo">1</b> / <span id="qTotal">12</span> 题</span>
    <span>得分 <b id="qScore">0</b></span>
    <span>连对 <b id="qStreak">0</b></span>
    <span id="qHint" style="color:#8a918b;">四个签名字同出一人之手——是谁？</span>
  </div>
  <div id="qmain">
    <div class="qchars" id="qChars"></div>
    <div class="opts" id="qOpts"></div>
    <div class="qreveal" id="qReveal">
      <div id="qrBody"></div>
      <button class="btnq" id="qNext" type="button">下一题</button>
    </div>
  </div>
  <div class="qfinal" id="qFinal">
    <div class="big" id="qfLine"></div>
    <div style="margin-top:8px;color:#5a615c;font-size:14px;" id="qfSub"></div>
    <button class="btnq" id="qRestart" type="button">再来一轮</button>
  </div>
</section>

<details class="method">
  <summary>方法与数据（口径与局限）</summary>
  <ul>
    <li><b>模型</b>：Monroe, Colaresi &amp; Quinn (2008) “Fightin' Words” 的对数几率比 + 信息性 Dirichlet 先验，<b>字符级</b>。对诗人 i 的字 w：<code>δ_w = ln[(y_i+α_w)/(n_i+α0−y_i−α_w)] − ln[(y_bg+α_w)/(n_bg+α0−y_bg−α_w)]</code>，方差近似 <code>σ² ≈ 1/(y_i+α_w) + 1/(y_bg+α_w)</code>，<code>z = δ/σ</code>。先验 <code>α_w = α0 · y_bg(w)/n_bg</code>，取 <b>α0 = 1000</b>（相当于按背景频率摊给每个字约千分之几的伪计数，抑制低频字偶然爆高）。</li>
    <li><b>对比口径</b>：前景 = 该诗人全部在库诗作；背景 = 全库 __NBGP__ 首（__NBGC__ 个汉字，<b>含其本人</b>，任务给定口径）。背景含本人会摊薄差异、略微压低 z，结论偏保守而非偏激进。</li>
    <li><b>预处理</b>：去除一切非汉字字符（标点、注音、序号）；诗前小序文字一并计入字频；停用字表为自建，逐字如下：<code>__STOP__</code>；字须在该诗人语料中出现 ≥ __MINC__ 次才参与排名；每人取 z 降序前 20 字。</li>
    <li><b>字符级对样本波动的稳健性</b>：以单字为统计单元，一首诗即贡献数十至数百个观测；配合信息性先验，低频偶然字较难挤进前 20。</li>
    <li><b>样本差异声明</b>：六人实时样本为 __STATLINE__。语料越大，同等偏差的 |z| 越大，因此 <b>z 只用于各诗人内部排序与字号映射，不做跨诗人比较</b>；六张卡片之间的字号大小亦不可横向对比。</li>
    <li><b>证据句</b>：点击任意签名字即展开该字在其诗中的原句（至多 8 句，优先每诗取一句保证诗目多样，命中字以朱色高亮，附诗题）；卡片角标的篇数/字数即统计分母，可与方法区公式互核。</li>
    <li><b>竞猜题库</b>：构建时预生成 12 题（每人 2 题），每题 4 字取自该诗人 top-10 且尽量避开与他人 top-20 重合的字；页面内作答顺序随机打乱；纯本地 JS，无外部依赖。</li>
    <li><b>局限</b>：每人语料是代表作抽样而非全集（如白居易含《长恨歌》《琵琶行》两首长篇，叙事用字权重被放大）；李清照为词体，与诗体的文体差异也会进入签名字。本页不涉及编年推断，无候选/推定分级问题。</li>
  </ul>
</details>

<footer class="nav">
  <a href="29_参赛导航.html">29 参赛导航</a><a href="30_诗行万里_参赛版.html">30 总入口</a><a href="31_凝望罗盘.html">31 凝望罗盘</a><a href="32_身与心双层地图.html">32 身与心双层地图</a><a href="33_平行时空759.html">33 平行时空759</a><a href="34_一字识诗人.html" style="color:var(--cinnabar);">34 一字识诗人</a><a href="35_两种孤独与夸张签名.html">35 两种孤独与夸张签名</a><a href="36_同龄对齐.html">36 同龄对齐</a><a href="37_可听的诗.html">37 可听的诗</a><a href="38_唐宋意象潮汐.html">38 意象潮汐</a><a href="39_诗人自述生命卷.html">39 诗人自述生命卷</a>
</footer>
</div>

<div class="mask" id="mask">
  <div class="mbox" role="dialog" aria-modal="true">
    <div class="mhead">
      <span class="mchar" id="mChar"></span>
      <span>
        <div class="mwho" id="mWho"></div>
        <div class="mstats" id="mStats"></div>
      </span>
      <button class="mclose" id="mClose" type="button" aria-label="关闭">&times;</button>
    </div>
    <div id="mBody"></div>
  </div>
</div>

<script>
var DATA = __DATA__;
(function(){
"use strict";
var POETS = DATA.poets, byKey = {};
POETS.forEach(function(p){ byKey[p.key] = p; });

function esc(s){ return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
function hl(line, ch){ return esc(line).split(ch).join('<span class="hl">'+ch+'</span>'); }
function fin(v, fb){ return (typeof v === 'number' && v === v) ? v : fb; } // v!==v 即非数

// ---------------- 六张签名字云卡（自写 flex 网格，无外部库） ----------------
var grid = document.getElementById('fgrid');
POETS.forEach(function(po){
  var card = document.createElement('div');
  card.className = 'fcard';
  card.style.borderTopColor = po.color;
  var zmax = po.top[0].z, zmin = po.top[po.top.length-1].z;
  var span = (zmax - zmin) || 1;
  var cloud = '';
  po.cloud_order.forEach(function(i){
    var t = po.top[i];
    var r = fin((t.z - zmin) / span, 0);
    var fs = Math.round(15 + 27 * r);
    var op = (0.55 + 0.45 * r).toFixed(2);
    cloud += '<span style="font-size:'+fs+'px;color:'+po.color+';opacity:'+op+
      '" data-k="'+po.key+'" data-i="'+i+'" title="z='+t.z.toFixed(1)+'">'+t.ch+'</span>';
  });
  card.innerHTML =
    '<div class="fhead"><span class="fname" style="color:'+po.color+'">'+po.name+'</span>'+
    '<span class="fmeta">'+po.n_poems+'首 · '+po.n_chars+'字</span></div>'+
    '<div class="cloud">'+cloud+'</div>'+
    '<div class="fhint">字号 = 独特度 z 分数（仅本卡内可比） · 点任意字看原句证据</div>';
  grid.appendChild(card);
});

// ---------------- 证据句弹层 ----------------
var mask = document.getElementById('mask');
function openModal(key, idx){
  var po = byKey[key], t = po.top[idx];
  document.getElementById('mChar').textContent = t.ch;
  document.getElementById('mChar').style.color = po.color;
  document.getElementById('mWho').textContent = po.name + ' 的签名字';
  document.getElementById('mWho').style.color = po.color;
  document.getElementById('mStats').textContent =
    'z='+t.z.toFixed(1)+' · 在其诗中出现 '+t.cnt+' 次（每千字 '+t.fp+'）· 背景每千字 '+t.fb;
  var htm = '';
  t.ex.forEach(function(e){
    htm += '<div class="exline">「'+hl(e.l, t.ch)+'」<span class="src">——《'+esc(e.t)+'》</span></div>';
  });
  document.getElementById('mBody').innerHTML = htm;
  mask.classList.add('on');
}
grid.addEventListener('click', function(e){
  var el = e.target;
  if (el.tagName === 'SPAN' && el.dataset && el.dataset.k){
    openModal(el.dataset.k, parseInt(el.dataset.i, 10));
  }
});
document.getElementById('mClose').addEventListener('click', function(){ mask.classList.remove('on'); });
mask.addEventListener('click', function(e){ if (e.target === mask) mask.classList.remove('on'); });
document.addEventListener('keydown', function(e){ if (e.key === 'Escape') mask.classList.remove('on'); });

// ---------------- 四字猜诗人 ----------------
var quizAll = DATA.quiz;
document.getElementById('qTotal').textContent = quizAll.length;
var order = [], qi = 0, score = 0, streak = 0, best = 0, nCorrect = 0, answered = false;

function shuffle(a){
  for (var i = a.length - 1; i > 0; i--){
    var j = Math.floor(Math.random() * (i + 1));
    var tmp = a[i]; a[i] = a[j]; a[j] = tmp;
  }
  return a;
}
function bar(){
  document.getElementById('qNo').textContent = Math.min(qi + 1, order.length);
  document.getElementById('qScore').textContent = score;
  document.getElementById('qStreak').textContent = streak;
}
function showQ(){
  answered = false;
  bar();
  var q = order[qi];
  var chtm = '';
  q.chars.forEach(function(c){ chtm += '<div class="qchar">'+c.c+'</div>'; });
  document.getElementById('qChars').innerHTML = chtm;
  var ohtm = '';
  POETS.forEach(function(po){
    ohtm += '<button class="opt" type="button" data-k="'+po.key+'" style="border-color:'+po.color+
      ';color:'+po.color+'">'+po.name+'</button>';
  });
  document.getElementById('qOpts').innerHTML = ohtm;
  document.getElementById('qReveal').classList.remove('on');
  document.getElementById('qNext').textContent = (qi === order.length - 1) ? '查看战绩' : '下一题';
}
function answer(key, btn){
  if (answered) return;
  answered = true;
  var q = order[qi], right = (key === q.a), po = byKey[q.a];
  if (right){ score += 10; streak += 1; nCorrect += 1; if (streak > best) best = streak; }
  else { streak = 0; }
  bar();
  var btns = document.getElementById('qOpts').querySelectorAll('.opt');
  for (var i = 0; i < btns.length; i++){
    var b = btns[i];
    b.disabled = true;
    if (b.dataset.k === q.a){ b.classList.add('correct'); b.style.background = po.color; b.style.color = '#fff'; }
    else if (b === btn){ b.classList.add('wrong'); }
  }
  var htm = '<div class="qverdict">'+(right ? '答对了！' : '不对——')+
    '这四个字同出 <b style="color:'+po.color+'">'+po.name+'</b> 之手'+(right ? '（+10 分）' : '')+'</div>';
  htm += '<div class="qsrc">';
  q.chars.forEach(function(c){
    htm += '<div class="exline"><b style="color:'+po.color+'">'+c.c+'</b> · 「'+hl(c.l, c.c)+
      '」<span class="src">——《'+esc(c.t)+'》</span></div>';
  });
  htm += '</div>';
  document.getElementById('qrBody').innerHTML = htm;
  document.getElementById('qReveal').classList.add('on');
}
document.getElementById('qOpts').addEventListener('click', function(e){
  var el = e.target;
  if (el.tagName === 'BUTTON' && el.dataset && el.dataset.k) answer(el.dataset.k, el);
});
document.getElementById('qNext').addEventListener('click', function(){
  qi += 1;
  if (qi < order.length){ showQ(); }
  else {
    document.getElementById('qmain').style.display = 'none';
    var f = document.getElementById('qFinal');
    f.style.display = 'block';
    document.getElementById('qfLine').textContent = '得分 '+score+' · 答对 '+nCorrect+'/'+order.length;
    document.getElementById('qfSub').textContent = '最长连对 '+best+' 题。'+
      (nCorrect === order.length ? '字如其人，全部识破！' : nCorrect >= Math.ceil(order.length*0.7) ? '好眼力——再来一轮冲满分？' : '多点几个签名字看看原句，再战一轮。');
  }
});
function startQuiz(){
  order = shuffle(quizAll.slice());
  qi = 0; score = 0; streak = 0; best = 0; nCorrect = 0;
  document.getElementById('qmain').style.display = 'block';
  document.getElementById('qFinal').style.display = 'none';
  showQ();
}
document.getElementById('qRestart').addEventListener('click', startQuiz);
startQuiz();
})();
</script>
</body>
</html>
"""


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    data, stat_parts = build()

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"), allow_nan=False)

    data_js = json.dumps(data, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    data_js = data_js.replace("</", "<\\/")
    html = (HTML_TMPL
            .replace("__DATA__", data_js)
            .replace("__NBGP__", str(data["meta"]["n_bg_poems"]))
            .replace("__NBGC__", str(data["meta"]["n_bg_chars"]))
            .replace("__STOP__", STOP_STR)
            .replace("__MINC__", str(MIN_COUNT))
            .replace("__STATLINE__", "、".join(stat_parts)))

    assert "NaN" not in html, "页面字面出现 NaN"
    assert "Infinity" not in html, "页面字面出现 Infinity"
    assert len(html.encode("utf-8")) >= 5000, "页面小于 5000 字节"
    with open(OUT_HTML, "w", encoding="utf-8") as f:
        f.write(html)

    print("OK  ->", OUT_HTML, f"({OUT_HTML.stat().st_size} bytes)")
    print("OK  ->", OUT_JSON, f"({OUT_JSON.stat().st_size} bytes)")
    for po in data["poets"]:
        tops = "  ".join(f"{t['ch']}(z={t['z']:.1f})" for t in po["top"][:5])
        print(f"{po['name']:<4} {po['n_poems']}首/{po['n_chars']}字  top5: {tops}")
    print("quiz:", len(data["quiz"]), "题")


if __name__ == "__main__":
    main()
