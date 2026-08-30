# -*- coding: utf-8 -*-
"""viz_44 赏析诗页：一首诗 = 一个可深链的赏析页（统一诗页）。

赏析平台的原子单位：任何展项的「原句证据」都能下钻到
44_诗页.html#poem=<poem_id>，看到这首诗的全部已有资料——

  原诗（意象命中高亮）
  导读卡（summary / interpretation / origin；助手撰写与模型生成分徽章，
          一律标注「非人工考据」，与项目门禁一致）
  审核创作背景（仅 approved：背景故事 / 逐句译注 / 赏析要点 / A·B 级证据来源）
  作年作地事实（三层层级徽章：人工核验 A/B 实底，规则晋级与 AI 辅助虚线「推定」）
  文本维度（诗级多标签情感 + 意象命中标签）
  关联入口（检索 / 词典 / 核心诗人行旅与意象比较 / 山河证道）

读者侧轻功能（纯本地，无账号）：
  收藏诗签（localStorage）· 上一首 / 下一首 · 诗人筛选 · 关键词过滤。

前置：tools/build_poem_page_data.py → output/assets/poem_page/poem_page_data.js。
产出：output/44_诗页.html（数据经本地 script 资产载入，file:// 直接可开）。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from viz_assets import inject_index_backlink  # noqa: E402

DATA_JS = ROOT / "output" / "assets" / "poem_page" / "poem_page_data.js"
OUT_HTML = ROOT / "output" / "44_诗页.html"

HTML_TMPL = r"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>44 · 赏析诗页 —— 一首诗，一页看全</title>
<link rel="icon" href="data:,">
<style>
:root{--paper:#f2f4f0;--panel:#fafbf8;--ink:#252b27;--muted:#5c665f;--line:#d8ddd6;
--cinnabar:#b64b3f;--jade:#26786e;--gold:#a87527;--blue:#426f94;--wash:#eef2ec;}
*{box-sizing:border-box;}
body{background:var(--paper);color:var(--ink);font-family:"Microsoft YaHei",sans-serif;line-height:1.7;margin:0;}
h1,h2,h3,.kai{font-family:KaiTi,STKaiti,"Microsoft YaHei",serif;}
.wrap{max-width:1180px;margin:0 auto;padding:16px;}
header{border-bottom:2px solid var(--ink);padding-bottom:12px;display:flex;flex-wrap:wrap;gap:10px;align-items:flex-end;justify-content:space-between;}
h1{margin:0;font-size:28px;letter-spacing:4px;}
h1 .sub{font-size:15px;color:var(--gold);letter-spacing:2px;margin-left:10px;}
.stats{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px;}
.stat{font-size:12px;color:var(--muted);border:1px solid var(--line);border-radius:999px;padding:2px 10px;background:var(--panel);}
.stat b{color:var(--ink);}
.tools{display:flex;gap:8px;align-items:center;flex-wrap:wrap;}
.tools input,.tools select{border:1px solid var(--line);border-radius:6px;background:var(--panel);padding:7px 10px;font:inherit;font-size:13px;}
.tools input{width:220px;}
.tools a,.tools button{font:inherit;font-size:13px;color:var(--blue);text-decoration:none;border:1px solid var(--line);border-radius:6px;background:var(--panel);padding:6px 10px;cursor:pointer;}
.layout{display:grid;grid-template-columns:280px minmax(0,1fr);gap:16px;margin-top:16px;align-items:start;}
aside{position:sticky;top:12px;}
.sidebox{border:1px solid var(--line);border-radius:8px;background:var(--panel);overflow:hidden;}
.sidebox h2{margin:0;font-size:15px;letter-spacing:2px;padding:10px 12px;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;align-items:center;}
.sidebox h2 span{font-size:12px;color:var(--muted);font-family:"Microsoft YaHei",sans-serif;}
#poemList{max-height:calc(100vh - 220px);overflow:auto;padding:6px;}
.pitem{display:block;width:100%;text-align:left;border:0;background:none;font:inherit;cursor:pointer;padding:8px 9px;border-radius:6px;color:var(--ink);}
.pitem:hover{background:var(--wash);}
.pitem.on{background:var(--wash);box-shadow:inset 3px 0 0 var(--cinnabar);}
.pitem .pt{font-family:KaiTi,STKaiti,serif;font-size:15px;}
.pitem .pm{font-size:12px;color:var(--muted);margin-top:2px;}
.pitem .dots{display:inline-flex;gap:4px;margin-left:6px;}
.dot{width:7px;height:7px;border-radius:50%;display:inline-block;}
.dot.g{background:var(--jade);} .dot.r{background:var(--gold);} .dot.a{background:#9aa39b;}
.dot.d{background:var(--cinnabar);}
.dot.x{background:none;border:1px solid var(--jade);}
.list-note{font-size:12px;color:var(--muted);padding:8px 10px;}
article{border:1px solid var(--line);border-radius:8px;background:var(--panel);padding:26px 30px 30px;min-height:60vh;}
.art-head{display:flex;flex-wrap:wrap;gap:12px;align-items:baseline;justify-content:space-between;}
h2.ptitle{margin:0;font-size:34px;letter-spacing:3px;}
.star{border:1px solid var(--line);background:var(--panel);border-radius:6px;cursor:pointer;font:inherit;font-size:13px;color:var(--muted);padding:5px 12px;}
.star.on{color:var(--gold);border-color:var(--gold);}
.meta{display:flex;flex-wrap:wrap;gap:8px;margin:10px 0 0;align-items:center;}
.tag{font-size:12px;color:var(--ink);border:1px solid var(--line);border-radius:999px;padding:2px 10px;background:var(--wash);}
.tag.dim{color:var(--muted);}
.fact{font-size:13px;color:var(--ink);border-left:3px solid var(--jade);background:var(--wash);padding:4px 10px;border-radius:0 6px 6px 0;}
.tier{font-size:12px;border-radius:4px;padding:2px 8px;letter-spacing:1px;}
.tier.verified{background:var(--jade);color:#fff;}
.tier.rule{border:1px dashed var(--gold);color:var(--gold);background:none;}
.tier.ai{border:1px dashed #9aa39b;color:#6f7a72;background:none;}
section{margin-top:26px;}
h3{font-size:19px;letter-spacing:3px;margin:0 0 12px;border-bottom:1px solid var(--line);padding-bottom:8px;}
h3 small{font-size:12px;color:var(--muted);letter-spacing:0;font-family:"Microsoft YaHei",sans-serif;margin-left:10px;}
.poem-body{white-space:pre-wrap;font-family:KaiTi,STKaiti,serif;font-size:21px;line-height:2.1;margin:0;}
.poem-body.clamp{max-height:460px;overflow:hidden;position:relative;}
.poem-body.clamp:after{content:"";position:absolute;left:0;right:0;bottom:0;height:70px;background:linear-gradient(transparent,var(--panel));}
mark.im{background:none;border-bottom:2px dotted var(--blue);color:inherit;padding:0 1px;cursor:help;}
.expand{margin-top:10px;font:inherit;font-size:13px;color:var(--blue);background:none;border:1px solid var(--line);border-radius:6px;padding:5px 12px;cursor:pointer;}
.guide{border:1px solid var(--line);border-radius:8px;background:var(--wash);padding:16px 18px;}
.guide .lead{font-family:KaiTi,STKaiti,serif;font-size:17px;margin:0 0 10px;}
.guide p{margin:0 0 10px;font-size:14.5px;}
.guide .origin{color:var(--muted);font-size:13.5px;border-top:1px dashed var(--line);padding-top:10px;margin-bottom:0;}
.honesty{display:inline-block;font-size:12px;border-radius:4px;padding:2px 8px;margin-bottom:12px;letter-spacing:1px;}
.honesty.hw{background:#f4ead2;color:#7a5a17;border:1px solid var(--gold);}
.honesty.mo{background:#e8ecea;color:#5c665f;border:1px solid #b9c2ba;}
.bg-story{font-size:14.5px;margin:0 0 8px;}
.warn{color:var(--cinnabar);font-size:13px;margin:8px 0 0;}
.lnote{padding:10px 0;border-top:1px dashed var(--line);}
.lnote:first-of-type{border-top:0;}
.lnote .lo{font-family:KaiTi,STKaiti,serif;font-size:16px;white-space:pre-line;}
.lnote .lt{color:var(--ink);font-size:14px;margin-top:3px;}
.lnote .la{color:var(--muted);font-size:13px;margin-top:3px;}
ul.flat{list-style:none;margin:0;padding:0;}
ul.flat li{padding:8px 0;border-top:1px dashed var(--line);font-size:14px;}
ul.flat li:first-child{border-top:0;}
.src .st{font-weight:600;}
.src .sm{font-size:12px;color:var(--muted);margin-top:2px;}
.src .sx{font-size:13px;color:#4a5665;border-left:2px solid var(--gold);padding-left:8px;margin-top:4px;}
.src a{color:var(--blue);}
.chips{display:flex;flex-wrap:wrap;gap:8px;}
.chip{font-size:13px;border:1px solid var(--line);border-radius:999px;padding:3px 11px;background:var(--wash);}
.chip small{color:var(--muted);}
.chip.em{border-color:#cfe0db;background:#eaf3f0;}
.ag{border:1px solid #e4d9bd;background:#faf6ea;border-radius:8px;padding:16px 18px;}
.ag .lead{margin:0 0 10px;font-size:14.5px;}
.ag .lnote{border-top:1px dashed #e4d9bd;}
.ag-note{color:#8a7440;font-size:12.5px;border-top:1px dashed #e4d9bd;padding-top:8px;margin-top:12px;}
.ag-note a{color:var(--blue);text-decoration:none;border-bottom:1px dotted currentColor;}
.chip.im{border-color:#d8e0ea;background:#eef2f7;}
.links{display:flex;flex-wrap:wrap;gap:10px;}
.links a{font-size:13.5px;color:var(--blue);text-decoration:none;border:1px solid var(--line);border-radius:6px;padding:7px 13px;background:var(--panel);}
.links a:hover{background:var(--wash);}
.pager{display:flex;justify-content:space-between;gap:10px;margin-top:30px;border-top:1px solid var(--line);padding-top:14px;}
.pager button{font:inherit;font-size:13px;background:none;border:1px solid var(--line);border-radius:6px;padding:6px 12px;cursor:pointer;color:var(--ink);max-width:44%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.empty{color:var(--muted);font-size:13.5px;background:var(--wash);border:1px dashed var(--line);border-radius:6px;padding:10px 14px;}
.genbtn{margin-top:10px;font:inherit;font-size:13px;color:var(--blue);background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:6px 13px;cursor:pointer;}
.genbtn:disabled{color:var(--muted);cursor:wait;}
.gennote{margin-top:8px;color:var(--muted);font-size:12.5px;line-height:1.6;}
footer{margin-top:18px;color:var(--muted);font-size:12.5px;line-height:1.8;border-top:1px solid var(--line);padding-top:10px;}
footer b{color:var(--ink);}
/* ---- 固定画卷背景与纸白可读性表面 ---- */
body{background:transparent;position:relative;isolation:isolate;}
body::before{content:"";position:fixed;inset:0;z-index:-2;background:url("assets/generated/remaining_pages_20260830/44_poem_reading_v1.png") center center/cover no-repeat;}
body::after{content:"";position:fixed;inset:0;z-index:-1;background:rgba(248,246,238,.50);pointer-events:none;}
.wrap{position:relative;z-index:1;}
.sidebox,article{background:rgba(250,251,248,.90);}
.stat,.tools input,.tools select,.tools a,.tools button,.star,.links a,.genbtn{background-color:rgba(250,251,248,.94);}
.guide,.ag,.tag,.fact,.chip,.empty{background-color:rgba(250,251,248,.88);}
@media(max-width:900px){
  .layout{grid-template-columns:1fr;}
  aside{position:static;}
  #poemList{max-height:240px;}
  article{padding:18px 16px 22px;}
  h2.ptitle{font-size:26px;}
  .poem-body{font-size:18px;}
}
</style>
</head>
<body>
<div class="wrap">
<header>
  <div>
    <h1>赏析诗页<span class="sub">一首诗，一页看全</span></h1>
    <div class="stats" id="stats"></div>
  </div>
  <div class="tools">
    <input id="search" type="search" placeholder="搜诗题 / 诗人 / 诗句" autocomplete="off">
    <select id="poetSel"><option value="">全部诗人</option></select>
    <label style="font-size:13px;color:var(--muted)"><input type="checkbox" id="favOnly"> 只看诗签</label>
    <a href="index.html">总入口</a>
    <a href="29_参赛导航.html">参赛导航</a>
  </div>
</header>

<div class="layout">
  <aside>
    <div class="sidebox">
      <h2>诗卷 <span id="listCount"></span></h2>
      <div id="poemList"></div>
    </div>
  </aside>
  <article id="view" aria-live="polite"></article>
</div>

<footer id="foot"></footer>
</div>
<script src="assets/poem_page/poem_page_data.js"></script>
<script>
(function(){
"use strict";
var DATA = window.POEM_PAGE_DATA;
var POEMS = DATA.poems;
var META = DATA.meta;
var TIER_LABEL = DATA.meta.tier_labels || {verified:"人工核验 A/B", rule:"规则晋级·推定", ai:"AI 辅助·推定"};
var CORE_POETS = ["李白","杜甫","白居易","苏轼","陆游","李清照"];
var RICH_API_BASE = "http://127.0.0.1:8123";
var FAV_KEY = "poemPageFavs";

function esc(v){
  return String(v == null ? "" : v).replace(/[&<>"']/g, function(c){
    return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c];
  });
}
function safeUrl(v){
  var s = String(v || "");
  return (s.indexOf("https://") === 0 || s.indexOf("http://") === 0) ? s : "";
}
function favs(){
  try { return JSON.parse(localStorage.getItem(FAV_KEY) || "[]"); } catch (e) { return []; }
}
function setFavs(arr){ localStorage.setItem(FAV_KEY, JSON.stringify(arr)); }
function isFav(id){ return favs().indexOf(id) >= 0; }

var byId = {};
POEMS.forEach(function(p){ byId[p.id] = p; });

/* ---------- 列表 ---------- */
var state = { q: "", poet: "", favOnly: false, cur: null };

function tierDot(p){
  if (p.bg) return '<span class="dot d" title="人工核验富背景"></span>';
  if (p.f) return p.f.tier === "rule" ? '<span class="dot r" title="规则晋级"></span>' : '<span class="dot a" title="AI 辅助"></span>';
  return "";
}
function listPoems(){
  var q = state.q.trim().toLowerCase();
  var fs = favs();
  return POEMS.filter(function(p){
    if (state.poet && p.p !== state.poet) return false;
    if (state.favOnly && fs.indexOf(p.id) < 0) return false;
    if (!q) return true;
    return (p.t + " " + p.p + " " + p.b).toLowerCase().indexOf(q) >= 0;
  });
}
function renderList(){
  var list = listPoems();
  var box = document.getElementById("poemList");
  document.getElementById("listCount").textContent = list.length + " 首";
  if (!list.length){
    box.innerHTML = '<div class="list-note">没有匹配的诗作。</div>';
    return;
  }
  if (state.cur && list.map(function(p){return p.id;}).indexOf(state.cur) < 0){
    state.cur = list[0].id;
    renderPoem();
    return;
  }
  var cap = 80;
  var html = list.slice(0, cap).map(function(p){
    var richTitle = p.ag ? (p.ag.hw ? "助手续写译注" : "AI 预生成译注") : "";
    var dots = [tierDot(p), p.gd ? '<span class="dot g" title="有导读卡"></span>' : "", p.ag ? '<span class="dot x" title="' + richTitle + '"></span>' : ""].join("");
    return '<button class="pitem' + (p.id === state.cur ? " on" : "") + '" data-id="' + esc(p.id) + '">' +
      '<span class="pt">' + esc(p.t) + '<span class="dots">' + dots + '</span></span>' +
      '<div class="pm">' + esc(p.p) + ' · ' + esc(p.d || "未标") + '</div></button>';
  }).join("");
  if (list.length > cap) html += '<div class="list-note">已显示前 ' + cap + ' 首，请用搜索缩小范围。</div>';
  box.innerHTML = html;
  Array.prototype.forEach.call(box.querySelectorAll(".pitem"), function(btn){
    btn.addEventListener("click", function(){ location.hash = "poem=" + btn.dataset.id; });
  });
}

/* ---------- 诗页 ---------- */
function factLine(f){
  var bits = [];
  if (f.ys != null){
    var y = (f.ys === f.ye || f.ye == null) ? f.ys + " 年" : f.ys + "–" + f.ye + " 年";
    if (f.prec === "approximate" || f.prec === "era_range") y = "约 " + y;
    bits.push("作年 " + esc(y));
  }
  var place = [];
  if (f.hp) place.push(esc(f.hp));
  if (f.mp && f.mp !== f.hp) place.push("今 " + esc(f.mp));
  if (place.length) bits.push("作地 " + place.join(" · "));
  if (!bits.length) return "";
  return '<span class="fact">' + bits.join("　") + '</span>' +
    '<span class="tier ' + f.tier + '">' + esc(TIER_LABEL[f.tier] || f.tier) + "</span>";
}
function highlightBody(p){
  var html = esc(p.b);
  var texts = (p.imt || []).slice().sort(function(a,b){ return b.length - a.length; });
  texts.forEach(function(t){
    var et = esc(t);
    if (et.length >= 2 && html.indexOf(et) >= 0){
      html = html.split(et).join('<mark class="im">' + et + "</mark>");
    }
  });
  return html;
}
function guideCard(p){
  if (!p.gd) return '<div class="empty">本首暂无导读卡。导读卡由助手与模型按「通说」撰写，仍在逐批推进，未覆盖的诗作保持空态，不以模型知识补写。</div>';
  var g = p.gd;
  var badge = g.hw
    ? '<span class="honesty hw">助手撰写 · 非人工考据</span>'
    : '<span class="honesty mo">模型生成 · 非人工考据</span>';
  return '<div class="guide">' + badge +
    (g.s ? '<p class="lead">' + esc(g.s) + "</p>" : "") +
    (g.i ? "<p>" + esc(g.i) + "</p>" : "") +
    (g.o ? '<p class="origin">' + esc(g.o) + "</p>" : "") +
    "</div>";
}
function bgSection(p){
  var b = p.bg;
  var parts = [];
  parts.push('<section><h3>审核创作背景<small>仅人工批准记录</small></h3>');
  parts.push('<p class="bg-story">' + (b.story ? esc(b.story) : "暂无背景故事。") + "</p>");
  if (b.controversy) parts.push('<p class="warn">待考：' + esc(b.controversy) + "</p>");
  var notes = (b.notes || []).filter(function(n){ return n.original || n.translation || n.annotations.length; });
  if (notes.length){
    parts.push('<div style="margin-top:14px">');
    notes.forEach(function(n){
      parts.push('<div class="lnote">' +
        (n.original ? '<div class="lo">' + esc(n.original) + "</div>" : "") +
        (n.translation ? '<div class="lt">' + esc(n.translation) + "</div>" : "") +
        (n.annotations.length ? '<div class="la">注：' + esc(n.annotations.join("；")) + "</div>" : "") +
        "</div>");
    });
    parts.push("</div>");
  }
  if (b.ap && b.ap.length){
    parts.push('<div style="margin-top:14px"><b>赏析要点</b><ul class="flat">' +
      b.ap.map(function(x){ return "<li>" + esc(x) + "</li>"; }).join("") + "</ul></div>");
  }
  if (b.src && b.src.length){
    parts.push('<div style="margin-top:14px"><b>证据来源</b><ul class="flat">' +
      b.src.map(function(s){
        var url = safeUrl(s.url);
        var name = url ? '<a href="' + esc(url) + '" target="_blank" rel="noreferrer">' + esc(s.name || "未命名来源") + "</a>" : esc(s.name || "未命名来源");
        var meta = [s.citation, s.locator, s.grade ? s.grade + " 级" : ""].filter(Boolean).join(" · ");
        return '<li class="src"><span class="st">' + name + "</span>" +
          (meta ? '<div class="sm">' + esc(meta) + "</div>" : "") +
          (s.excerpt ? '<div class="sx">' + esc(s.excerpt) + "</div>" : "") + "</li>";
      }).join("") + "</ul></div>");
  }
  parts.push("</section>");
  return parts.join("");
}
function agSection(p){
  var a = p.ag;
  var parts = [];
  var heading = a.hw ? "助手续写 · 译注赏析" : "AI 预生成 · 译注赏析";
  var anchorText = {
    verified: "使用人工核验作年作地",
    rule: "使用规则晋级作年作地（推定）",
    ai: "使用 AI 辅助作年作地（推定）",
    none: "未使用核验作年作地"
  }[a.at || "none"] || "未使用核验作年作地";
  var referenceText = {
    assistant_authored: "译注赏析由助手撰写",
    reviewed_references: "译注赏析受经审核网站摘要约束",
    poem_only: "译注赏析仅依据原诗与可用事实锚",
    legacy_unconstrained: "旧版模型条目未接入网站证据约束"
  }[a.rm || (a.hw ? "assistant_authored" : "legacy_unconstrained")];
  var sourceLinks = (a.src || []).map(function(s){
    return '<a href="' + esc(s.u) + '" target="_blank" rel="noopener noreferrer">' +
      esc(s.n) + (s.id ? " · " + esc(s.id) : "") + "</a>";
  }).join("、");
  parts.push('<section><h3>' + heading + '<small>逐句译文与注释 · 待人工复核</small></h3>');
  parts.push('<div class="ag">');
  parts.push(a.hw
    ? '<span class="honesty hw">助手撰写 · 非人工考据</span>'
    : '<span class="honesty mo">模型生成' +
      (a.rm === "reviewed_references" ? " · 经审核摘要约束" : "") +
      ' · 非人工考据</span>');
  if (a.story) parts.push('<p class="lead">' + esc(a.story) + "</p>");
  (a.notes || []).forEach(function(n){
    parts.push('<div class="lnote">' +
      (n.original ? '<div class="lo">' + esc(n.original) + "</div>" : "") +
      (n.translation ? '<div class="lt">' + esc(n.translation) + "</div>" : "") +
      (n.annotations && n.annotations.length ? '<div class="la">注：' +
        esc(n.annotations.map(function(x){ return String(x).replace(/[；。]+$/, ""); }).join("；")) +
        "。</div>" : "") +
      "</div>");
  });
  if (a.ap && a.ap.length){
    parts.push('<div style="margin-top:14px"><b>赏析要点</b><ul class="flat">' +
      a.ap.map(function(x){ return "<li>" + esc(x) + "</li>"; }).join("") + "</ul></div>");
  }
  parts.push('<div class="ag-note">批次 ' + esc(a.batch || "—") + "　" +
    anchorText + "；" + referenceText + "。" +
    (sourceLinks ? "参考约束：" + sourceLinks + "。" : "") +
    "人工复核通过前不计入富背景验收。</div>");
  parts.push("</div></section>");
  return parts.join("");
}
function agPlaceholder(p){
  return '<section><h3>译注赏析<small>按需生成</small></h3>' +
    '<div class="empty">本首暂无译注赏析（手写层与模型层均未覆盖）。' +
    '<button class="genbtn" id="genBtn">⟳ 在线生成译注赏析</button>' +
    '<div class="gennote" id="genNote">离线 file:// 可完整浏览；在线生成请先运行 python tools/serve_output.py，以本地 HTTP 打开本页，并将页面实际 origin 加入 AGENT_ALLOWED_ORIGINS；' +
    '同时需运行 Agent API（默认 127.0.0.1:8123）并配置 AGENT_LLM_* 密钥。' +
    '生成结果经「原句与正文逐字一致」质量门校验后由服务端留档，徽章「模型生成 · 非人工考据」，重建管线后进入正式数据层。</div></div></section>';
}
function tryFetchJson(url, opts){
  if (typeof fetch !== "function") return Promise.reject(new Error("此环境不支持 fetch"));
  return fetch(url, opts).then(function(resp){
    return resp.json().then(function(body){ return {ok: resp.ok, status: resp.status, body: body}; });
  });
}
function attachGenButton(p){
  var btn = document.getElementById("genBtn");
  var note = document.getElementById("genNote");
  if (!btn) return;
  btn.addEventListener("click", function(){
    if (location.protocol === "file:"){
      note.textContent = "file:// 仅用于完整离线浏览，不发起在线生成。请运行 python tools/serve_output.py，通过本地 HTTP 打开本页，并将显示的页面 origin 加入 Agent API 的 AGENT_ALLOWED_ORIGINS。";
      return;
    }
    btn.disabled = true;
    btn.textContent = "⟳ 生成中…（约半分钟）";
    note.textContent = "正在请求本机 Agent API，模型按事实锚定生成，原句逐字校验。";
    tryFetchJson(RICH_API_BASE + "/knowledge/rich-guide", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({poem_id: p.id})
    }).then(function(resp){
      var item = resp.body && resp.body.item;
      if (resp.ok && item){
        p.ag = {
          story: item.story,
          notes: item.notes || [],
          ap: item.ap || [],
          batch: resp.body.batch || item.batch || "",
          hw: resp.body.source === "hand" || item.hw === true,
          at: item.anchor_tier || "none",
          rm: item.reference_mode ||
            ((resp.body.source === "hand" || item.hw === true) ? "assistant_authored" : "legacy_unconstrained"),
          src: (item.sources || []).map(function(s){
            return {id: s.reference_id || "", n: s.name || "", u: s.url || ""};
          })
        };
        renderPoem();
        return;
      }
      var reason = resp.body && resp.body.reason;
      if (resp.status === 503 && reason === "missing_env"){
        note.textContent = "Agent API 未配置密钥（AGENT_LLM_BASE_URL/API_KEY/MODEL），生成不可用；其余页面功能不受影响。";
      } else if (resp.status === 503 && reason === "knowledge_base_missing"){
        note.textContent = "Agent API 尚未构建诗词知识库，暂时无法生成；请先重建知识库，原诗与已有赏析仍可正常浏览。";
      } else if (resp.status === 503){
        note.textContent = "Agent API 当前不可用（" + esc(reason || "service_unavailable") + "）；原诗与已有赏析仍可正常浏览。";
      } else if (resp.status === 404){
        note.textContent = "该诗不在知识库，无法生成。";
      } else if (resp.status === 422){
        note.textContent = "质量门未通过（原句与正文不一致等），已拒绝返回：" + ((resp.body && resp.body.errors || []).join("；").slice(0, 80));
      } else {
        note.textContent = "请求失败（HTTP " + resp.status + "）。请确认已启动 Agent API，并已将当前页面 origin（" + location.origin + "）加入 AGENT_ALLOWED_ORIGINS。";
      }
      btn.disabled = false;
      btn.textContent = "⟳ 在线生成译注赏析";
    }).catch(function(){
      note.textContent = "无法连接 Agent API（默认 " + RICH_API_BASE + "）。请确认通过 python tools/serve_output.py 以 HTTP 打开，并将当前页面 origin（" + location.origin + "）加入 AGENT_ALLOWED_ORIGINS；离线浏览不受影响。";
      btn.disabled = false;
      btn.textContent = "⟳ 在线生成译注赏析";
    });
  });
}
function dimSection(p){
  var chips = [];
  (p.em || []).forEach(function(e){
    chips.push('<span class="chip em">' + esc(e.l) + "<small>　" + esc(e.f || "") + " · 占比 " + Math.round(e.sh * 100) + "%</small></span>");
  });
  (p.im || []).forEach(function(i){
    chips.push('<span class="chip im">' + esc(i.l) + "<small>　命中 " + esc(i.c) + (i.cat ? " · " + esc(i.cat) : "") + "</small></span>");
  });
  if (!chips.length) return '<section><h3>文本维度<small>词典规则扫描</small></h3><div class="empty">本首未命中意象与情感词典，不强行标注。</div></section>';
  return '<section><h3>文本维度<small>词典规则扫描，非人工判断</small></h3><div class="chips">' + chips.join("") + "</div></section>";
}
function linkSection(p){
  var links = [];
  links.push('<a href="08_诗作检索.html?q=' + encodeURIComponent(p.t) + '">在诗作检索中查此诗</a>');
  links.push('<a href="09_词典浏览.html">查意象与古地名词典</a>');
  if (CORE_POETS.indexOf(p.p) >= 0){
    links.push('<a href="15_诗人行旅与生命情感.html">看 ' + esc(p.p) + ' 的行旅与处境</a>');
    links.push('<a href="17_同一意象的诗人情感差异.html">六家意象情感比较</a>');
  }
  links.push('<a href="40_山河证道.html">去山河证道猜创作地</a>');
  return '<section><h3>关联入口</h3><div class="links">' + links.join("") + "</div></section>";
}
function renderPoem(){
  var p = byId[state.cur];
  var view = document.getElementById("view");
  if (!p){ view.innerHTML = '<div class="empty">未找到这首诗。</div>'; return; }
  document.title = p.t + " · " + p.p + " —— 赏析诗页";

  var list = listPoems();
  var idx = list.map(function(x){ return x.id; }).indexOf(p.id);
  var prev = idx > 0 ? list[idx - 1] : null;
  var next = idx >= 0 && idx < list.length - 1 ? list[idx + 1] : null;

  var metaTags = ['<span class="tag">' + esc(p.p) + "</span>", '<span class="tag dim">' + esc(p.d || "朝代未标") + "</span>"];
  if (p.sc) metaTags.push('<span class="tag dim">' + esc(p.sc) + "</span>");

  view.innerHTML =
    '<div class="art-head"><h2 class="ptitle">' + esc(p.t) + "</h2>" +
    '<button class="star' + (isFav(p.id) ? " on" : "") + '" id="starBtn">' + (isFav(p.id) ? "★ 已入诗签" : "☆ 收藏诗签") + "</button></div>" +
    '<div class="meta">' + metaTags.join("") + (p.f ? factLine(p.f) : '<span class="empty" style="padding:3px 10px">暂无核验作年作地</span>') + "</div>" +
    '<section><h3>原诗<small>蓝点线为意象命中，悬停无弹窗，见下方维度栏</small></h3>' +
      '<div class="poem-body clamp" id="poemBody">' + highlightBody(p) + "</div>" +
      '<button class="expand" id="expandBtn">展开全文</button>' +
    "</section>" +
    '<section><h3>导读卡<small>模型通说叙述 · 非人工考据</small></h3>' + guideCard(p) + "</section>" +
    (p.bg ? bgSection(p) : "") +
    (p.ag ? agSection(p) : agPlaceholder(p)) +
    dimSection(p) +
    linkSection(p) +
    '<div class="pager">' +
      (prev ? '<button id="prevBtn" title="' + esc(prev.t) + '">← 上一首 · ' + esc(prev.t) + "</button>" : "<span></span>") +
      (next ? '<button id="nextBtn" title="' + esc(next.t) + '">下一首 · ' + esc(next.t) + " →</button>" : "<span></span>") +
    "</div>";

  var body = document.getElementById("poemBody");
  var expand = document.getElementById("expandBtn");
  if (body.scrollHeight <= 470){ body.classList.remove("clamp"); expand.style.display = "none"; }
  expand.addEventListener("click", function(){
    var clamped = body.classList.toggle("clamp");
    expand.textContent = clamped ? "展开全文" : "收起长诗";
  });
  document.getElementById("starBtn").addEventListener("click", function(){
    var arr = favs();
    var at = arr.indexOf(p.id);
    if (at >= 0) arr.splice(at, 1); else arr.push(p.id);
    setFavs(arr);
    renderPoem();
  });
  if (prev) document.getElementById("prevBtn").addEventListener("click", function(){ location.hash = "poem=" + prev.id; });
  if (next) document.getElementById("nextBtn").addEventListener("click", function(){ location.hash = "poem=" + next.id; });
  attachGenButton(p);
  view.scrollIntoView && window.scrollTo({top: 0});
}

/* ---------- 头部与路由 ---------- */
function renderStats(){
  document.getElementById("stats").innerHTML =
    '<span class="stat">诗作 <b>' + META.poems.toLocaleString() + "</b> 首</span>" +
    '<span class="stat">诗人 <b>' + META.poets + "</b> 位</span>" +
    '<span class="stat">导读卡 <b>' + META.guides.toLocaleString() + "</b>（助手 " + META.guides_assistant + " / 模型 " + META.guides_model + "）</span>" +
    '<span class="stat">作年作地：人工核验 <b>' + META.facts_verified + "</b> · 规则晋级 <b>" + META.facts_rule.toLocaleString() + "</b> · AI 辅助 <b>" + META.facts_ai + "</b></span>" +
    '<span class="stat">译注赏析 <b>' + (META.assistant_rich || 0) + "</b> 首（手写 " + (META.rich_hand || 0) + " / 模型 " + (META.rich_llm || 0) + "）</span>";
  document.getElementById("foot").innerHTML =
    "<b>口径说明</b>　导读卡为助手 / 模型生成的通说叙述，非人工考据，不代表已验收结论；" +
    "作年作地分三层——人工核验 A/B 级（实底徽章）、规则晋级与 AI 辅助（虚线「推定」徽章），引用时须区分；" +
    "审核创作背景仅来自人工批准记录，候选与待考不进入页面；「译注赏析」由助手撰写或模型生成，待人工复核，复核通过前不计入富背景验收；" +
    "文本维度为词典规则扫描结果。本页无账号系统，诗签收藏只存于本机浏览器。";
}
function fillPoets(){
  var sel = document.getElementById("poetSel");
  sel.innerHTML = '<option value="">全部诗人</option>' + DATA.poets.map(function(name){
    return '<option value="' + esc(name) + '">' + esc(name) + "</option>";
  }).join("");
}
function defaultPoemId(){
  var withBg = POEMS.filter(function(p){ return p.bg && p.gd; });
  if (withBg.length) return withBg[0].id;
  var withGuide = POEMS.filter(function(p){ return p.gd; });
  return withGuide.length ? withGuide[0].id : POEMS[0].id;
}
function route(){
  var h = location.hash.replace(/^#/, "");
  if (h.indexOf("poem=") === 0){
    var id = h.slice(5);
    if (byId[id]){ state.cur = id; renderList(); renderPoem(); return; }
  } else if (h.indexOf("poet=") === 0){
    var name = decodeURIComponent(h.slice(5));
    state.poet = DATA.poets.indexOf(name) >= 0 ? name : "";
    document.getElementById("poetSel").value = state.poet;
    var list = listPoems();
    state.cur = list.length ? list[0].id : null;
    renderList();
    if (state.cur) renderPoem();
    return;
  }
  if (!state.cur) state.cur = defaultPoemId();
  renderList();
  renderPoem();
}
window.addEventListener("hashchange", route);
document.getElementById("search").addEventListener("input", function(e){
  state.q = e.target.value; renderList();
});
document.getElementById("poetSel").addEventListener("change", function(e){
  state.poet = e.target.value; renderList();
});
document.getElementById("favOnly").addEventListener("change", function(e){
  state.favOnly = e.target.checked; renderList();
});

renderStats();
fillPoets();
route();
})();
</script>
</body>
</html>
"""


def main() -> None:
    if not DATA_JS.exists():
        raise SystemExit(
            f"[failed] 缺少诗页数据：{DATA_JS}\n"
            "  先运行 python tools/build_poem_page_data.py 生成本地数据资产。"
        )
    OUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    html = inject_index_backlink(HTML_TMPL)
    OUT_HTML.write_text(html, encoding="utf-8", newline="\n")
    print(f"  [ok] saved {OUT_HTML}  (数据资产 {DATA_JS.name}，file:// 直接可开)")


if __name__ == "__main__":
    main()
