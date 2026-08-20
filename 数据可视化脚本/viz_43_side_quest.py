# -*- coding: utf-8 -*-
"""viz_43 飞花令·加行卷：山河证道番外（三题型练习场）。

三种题型（数据全部来自 tools/build_side_quest_bank.py，确定性生成）：
  地名飞花令——四句挑真，干扰句经校验不含令字；
  意象归乡——选项与证据直接来自 R2 意象×地域矩阵（题即论据）；
  古今地名连线——点选配对，即时判对错，附词典备注。

计分：每题基分 800；飞花令/意象各有一级提示 ×0.5；
连线按「首错前命中对数」计分：800 × 4/(4+错选次数)，下限 200。
段位（总分/满分）：≥85% 酒中仙 ≥70% 飞花手 ≥50% 行令人 其余 投壶手。

前置：tools/build_side_quest_bank.py。
产出：output/43_飞花令加行.html（数据内嵌，file:// 直接可开，零外部依赖）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC_JSON = ROOT / "output" / "assets" / "competition" / "side_quest_bank.json"
OUT_HTML = ROOT / "output" / "43_飞花令加行.html"

HTML_TMPL = r"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>43 · 飞花令 · 加行卷</title>
<style>
:root{--paper:#f2f4f0;--ink:#252b27;--cinnabar:#b64b3f;--jade:#26786e;--gold:#a87527;--blue:#426f94;}
*{box-sizing:border-box;}
body{background:var(--paper);color:var(--ink);font-family:"Microsoft YaHei",sans-serif;line-height:1.7;margin:0;padding:16px;}
h1,h2,h3,.kai{font-family:KaiTi,STKaiti,"Microsoft YaHei",serif;}
.wrap{max-width:880px;margin:0 auto;}
header{border-bottom:2px solid var(--ink);padding-bottom:10px;}
h1{margin:0;font-size:30px;letter-spacing:6px;}
h1 .sub{font-size:16px;color:var(--gold);letter-spacing:2px;margin-left:10px;}
.lead{margin:6px 0 2px;color:#3c443f;}
.meta-line{margin:0;font-size:12.5px;color:#6a726c;}
.meta-line b{color:var(--cinnabar);}
.panel{background:#fbfcfa;border:1px solid #dfe4de;border-radius:10px;padding:12px 16px;margin-top:14px;box-shadow:0 1px 3px rgba(37,43,39,.05);font-size:14px;color:#3c443f;}
.qhead{display:flex;gap:14px;align-items:baseline;font-size:13.5px;color:#3c443f;margin-bottom:8px;flex-wrap:wrap;}
.qhead .qno{font-family:KaiTi,STKaiti,serif;font-size:18px;}
.qhead .typ{color:var(--gold);font-family:KaiTi,STKaiti,serif;font-size:15px;}
.badge{display:inline-block;border-radius:4px;padding:0 8px;font-size:12px;line-height:20px;background:#e4ece7;color:var(--jade);border:1px solid #bcd3c9;}
.prompt{font-family:KaiTi,STKaiti,serif;font-size:21px;margin:6px 0 12px;}
.opts{display:flex;flex-direction:column;gap:8px;}
.opt{cursor:pointer;text-align:left;background:#fbfcfa;border:1px solid #cfd6d0;border-radius:8px;padding:8px 14px;font-size:16px;color:var(--ink);transition:all .15s;font-family:KaiTi,STKaiti,serif;}
.opt:hover:not(:disabled){border-color:var(--jade);background:#f0f5f2;}
.opt:disabled{cursor:default;}
.opt.right{border-color:var(--jade);background:#e9f2ed;color:var(--jade);}
.opt.wrong{border-color:var(--cinnabar);background:#f8ece9;color:var(--cinnabar);}
.hintbar{display:flex;gap:10px;align-items:center;margin-top:12px;flex-wrap:wrap;}
button.act{cursor:pointer;background:var(--jade);color:#fff;border:none;border-radius:8px;padding:7px 18px;font-size:14.5px;font-family:KaiTi,STKaiti,serif;letter-spacing:2px;}
button.act:disabled{background:#a9b3ad;cursor:not-allowed;}
button.act.ghost{background:transparent;color:var(--jade);border:1px solid var(--jade);}
button.act.sm{padding:3px 12px;font-size:12.5px;letter-spacing:1px;}
.hintext{background:#f6f2e8;border:1px dashed #d8c9a3;border-radius:8px;padding:8px 12px;font-size:13.5px;color:#4a4436;display:none;flex:1 1 260px;}
.evcard{margin-top:14px;background:#f6f8f4;border:1px solid #e0e5de;border-radius:8px;padding:10px 14px;display:none;}
.evcard h3{margin:2px 0 6px;font-size:15px;color:var(--blue);border-left:3px solid var(--blue);padding-left:8px;}
.evrow{margin:5px 0;font-size:13.5px;}
.evrow b{color:var(--blue);}
.evrow .lift{color:var(--cinnabar);}
.src{font-size:12px;color:#6a726c;}
table.mtab{border-collapse:collapse;width:100%;font-size:13px;margin-top:4px;}
table.mtab th,table.mtab td{border:1px solid #dfe4de;padding:4px 8px;text-align:left;}
table.mtab th{background:#eef1ec;font-weight:normal;}
.lcols{display:flex;gap:14px;margin-top:8px;flex-wrap:wrap;}
.lcol{flex:1 1 200px;display:flex;flex-direction:column;gap:8px;}
.ltitle{font-size:13px;color:#6a726c;text-align:center;}
.litem{cursor:pointer;background:#fbfcfa;border:1px solid #cfd6d0;border-radius:8px;padding:8px 12px;text-align:center;font-family:KaiTi,STKaiti,serif;font-size:18px;transition:all .12s;}
.litem:hover:not(.lock):not(.sel){border-color:var(--gold);}
.litem.sel{border-color:var(--blue);background:#e8eef4;box-shadow:0 0 0 1px var(--blue);}
.litem.lock{border-color:#a9c4ba;background:#e9f2ed;color:var(--jade);cursor:default;}
.litem.flash{border-color:var(--cinnabar);background:#f8ece9;color:var(--cinnabar);}
#endArea{display:none;}
#endArea .rank{font-size:34px;font-family:KaiTi,STKaiti,serif;color:var(--cinnabar);letter-spacing:8px;}
.stat3{display:flex;gap:12px;flex-wrap:wrap;margin:10px 0;}
.stat3>div{flex:1 1 120px;text-align:center;background:#f6f8f4;border:1px solid #e0e5de;border-radius:8px;padding:8px;}
.stat3 .v{font-size:22px;font-family:KaiTi,STKaiti,serif;}
.stat3 .k{font-size:12px;color:#6a726c;}
.qian span{display:inline-block;background:#fff;border:1px solid #d8cdb0;border-radius:6px;padding:2px 10px;margin:3px 4px 3px 0;font-size:13px;cursor:pointer;color:#4a4436;}
.qian span:hover{border-color:var(--gold);color:var(--gold);}
#resumeBar{display:none;}
footer{margin-top:16px;border-top:1px solid #dfe4de;padding-top:10px;font-size:12.5px;color:#6a726c;}
</style>
</head>
<body>
<div class="wrap">
<header>
  <h1>飞花令<span class="sub">加行卷 · 山河证道番外</span></h1>
  <p class="lead">三种加行：读句辨真（飞花令）、看意象识乡（意象归乡）、指古名认今地（连线）——全部题目确定性生成，证据可复核。</p>
  <p class="meta-line">共 <b>__N__</b> 题（飞花令 __NF__ / 意象归乡 __NI__ / 连线 __NL__）｜每题基分 <b>800</b>，提示 ×0.5｜总分与段位答完揭晓</p>
</header>

<div id="resumeBar" class="panel">检测到上次行囊——第 <b id="rQi"></b> 题，得分 <b id="rScore"></b>。
  <button class="act sm" id="btnResume">继续</button>
  <button class="act ghost sm" id="btnFresh">重新开始</button>
</div>

<section id="gameArea">
  <div class="qhead">
    <span class="qno" id="qNo">第 1 题</span>
    <span class="typ" id="qType"></span>
    <span>得分 <b id="scoreNow" style="color:var(--cinnabar)">0</b></span>
    <span id="streakNow"></span>
  </div>
  <div class="prompt" id="qPrompt"></div>
  <div id="qBody"></div>
  <div class="hintbar" id="hintBar">
    <button class="act ghost sm" id="btnHint">提示 ×0.5</button>
    <div class="hintext" id="hintText"></div>
  </div>
  <div class="evcard" id="evCard"></div>
</section>

<section id="endArea" class="panel">
  <h2 class="kai">加行终了</h2>
  <div class="rank" id="endRank"></div>
  <div class="stat3">
    <div><div class="v" id="endScore">0</div><div class="k">总得分 / 满分 __MAX__</div></div>
    <div><div class="v" id="endAcc">0/0</div><div class="k">答对题数</div></div>
    <div><div class="v" id="endStreak">0</div><div class="k">最长连对</div></div>
  </div>
  <div id="endQuote" class="kai" style="font-size:15px;color:#4a524c;"></div>
  <h3 style="margin-top:12px;">行囊 · 错题诗签</h3>
  <div class="qian" id="qianList"></div>
  <div style="margin-top:12px;">
    <button class="act" id="btnAgain">再来一轮</button>
    <button class="act ghost" id="btnReset">清除进度</button>
  </div>
</section>

<div class="panel">
  <b>方法与口径</b>——__POLICY__ 意象归乡的选项与证据来自 <a href="41_意象地理.html" style="color:var(--blue)">41_意象地理</a>（R2 lift 矩阵）；连线词典备注来自古地名词典；本卷不涉及作地核验，与山河证道正卷的 A/B 级考据口径相互独立。
</div>

<footer>诗行万里 · 飞花令加行卷｜生成：tools/build_side_quest_bank.py + 数据可视化脚本/viz_43_side_quest.py</footer>
</div>

<script>
(function(){
"use strict";
var BANK = __DATA__;
var QS = BANK.questions;
var MAX = QS.length * 800;
var SAVE_KEY = "shxw43_v1";
var el = function(id){ return document.getElementById(id); };
function esc(s){ return String(s==null?"":s).replace(/[&<>"']/g, function(c){
  return {"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c];}); }
function loadSave(){ try{ return JSON.parse(localStorage.getItem(SAVE_KEY) || "null"); }catch(e){ return null; } }
function writeSave(s){ try{ localStorage.setItem(SAVE_KEY, JSON.stringify(s)); }catch(e){} }
function clearSave(){ try{ localStorage.removeItem(SAVE_KEY); }catch(e){} }

var S = {qi:0, score:0, correct:0, streak:0, best:0, wrong:[]};
var cur = null, hintUsed = false, answered = false;
var linkState = null;

function typeName(t){
  return {feihualing:"飞花令", imagery_home:"意象归乡", link:"古今连线"}[t] || t;
}

function showQ(){
  cur = QS[S.qi]; hintUsed = false; answered = false; linkState = null;
  el("qNo").textContent = "第 " + (S.qi+1) + " / " + QS.length + " 题";
  el("qType").textContent = "· " + typeName(cur.type) + " ·";
  el("scoreNow").textContent = S.score;
  el("streakNow").textContent = S.streak > 1 ? "连对 " + S.streak : "";
  el("qPrompt").textContent = cur.prompt;
  el("hintText").style.display = "none";
  el("evCard").style.display = "none";
  el("evCard").innerHTML = "";
  var hasHint = cur.type !== "link";
  el("hintBar").style.display = hasHint ? "flex" : "none";
  el("btnHint").disabled = false;
  renderBody();
}

function renderBody(){
  var b = el("qBody");
  if(cur.type === "link"){ renderLink(b); return; }
  var html = ['<div class="opts">'];
  cur.options.forEach(function(o, i){
    var label = o.line !== undefined ? esc(o.line) : (o.region !== undefined ? esc(o.region) : esc(o.word));
    html.push('<button class="opt" data-i="' + i + '">' + label + '</button>');
  });
  html.push('</div>');
  b.innerHTML = html.join("");
  Array.prototype.forEach.call(b.querySelectorAll(".opt"), function(btn){
    btn.onclick = function(){ if(answered) return; pick(+btn.getAttribute("data-i")); };
  });
}

function pick(i){
  answered = true;
  var right = i === cur.correct;
  var mult = hintUsed ? 0.5 : 1;
  var pts = 0;
  var btns = el("qBody").querySelectorAll(".opt");
  btns[cur.correct].classList.add("right");
  btns[cur.correct].disabled = true;
  if(!right){ btns[i].classList.add("wrong"); btns[i].disabled = true; }
  Array.prototype.forEach.call(btns, function(x){ x.disabled = true; });
  if(right){ pts = Math.round(800 * mult); S.correct++; S.streak++; S.best = Math.max(S.best, S.streak); }
  else { S.streak = 0; S.wrong.push({qi:S.qi}); }
  S.score += pts;
  el("scoreNow").textContent = S.score;
  el("streakNow").textContent = S.streak > 1 ? "连对 " + S.streak : "";
  showEvCard(pts, right);
  saveAndNext();
}

/* ---------- 连线 ---------- */
function renderLink(b){
  var left = cur.left_order.slice();
  var right = cur.right_order.slice();
  linkState = {sel:null, matched:0, wrongTries:0, lock:{}};
  var byAlias = {};
  cur.pairs.forEach(function(p){ byAlias[p.alias] = p; });
  var html = ['<div class="lcols"><div class="lcol"><div class="ltitle">古名</div>'];
  left.forEach(function(a){ html.push('<div class="litem" data-side="L" data-v="' + esc(a) + '">' + esc(a) + '</div>'); });
  html.push('</div><div class="lcol"><div class="ltitle">今地（点左侧古名后再点）</div>');
  right.forEach(function(a){ html.push('<div class="litem" data-side="R" data-v="' + esc(byAlias[a].modern) + '" data-alias="' + esc(a) + '">' + esc(byAlias[a].modern) + '</div>'); });
  html.push('</div></div><div style="margin-top:8px;font-size:13px;color:#6a726c" id="linkTip">先点一个古名，再点它对应的今地。</div>');
  b.innerHTML = html.join("");
  Array.prototype.forEach.call(b.querySelectorAll(".litem"), function(item){
    item.onclick = function(){ onLinkClick(item); };
  });
}
function onLinkClick(item){
  if(answered || item.classList.contains("lock")) return;
  var side = item.getAttribute("data-side");
  if(side === "L"){
    var prev = el("qBody").querySelector(".litem.sel");
    if(prev) prev.classList.remove("sel");
    item.classList.add("sel");
    linkState.sel = item.getAttribute("data-v");
    el("linkTip").textContent = "「" + linkState.sel + "」——再点右侧它对应的今地。";
    return;
  }
  if(!linkState.sel){
    item.classList.add("flash");
    setTimeout(function(){ item.classList.remove("flash"); }, 400);
    el("linkTip").textContent = "先点左侧一个古名。";
    return;
  }
  var wantModern = null;
  cur.pairs.forEach(function(p){ if(p.alias === linkState.sel) wantModern = p.modern; });
  if(item.getAttribute("data-v") === wantModern){
    item.classList.add("lock");
    item.textContent = wantModern + "（" + linkState.sel + "）";
    var lsel = el("qBody").querySelector(".litem.sel");
    lsel.classList.remove("sel");
    lsel.classList.add("lock");
    linkState.matched++;
    linkState.sel = null;
    el("linkTip").textContent = "对上了。还剩 " + (4 - linkState.matched) + " 对。";
    if(linkState.matched === 4){
      answered = true;
      var pts = Math.max(200, Math.round(800 * 4 / (4 + linkState.wrongTries)));
      S.score += pts;
      if(linkState.wrongTries === 0){ S.correct++; S.streak++; S.best = Math.max(S.best, S.streak); }
      else { S.streak = 0; S.wrong.push({qi:S.qi}); }
      el("scoreNow").textContent = S.score;
      el("streakNow").textContent = S.streak > 1 ? "连对 " + S.streak : "";
      showEvCard(pts, linkState.wrongTries === 0);
      saveAndNext();
    }
  } else {
    linkState.wrongTries++;
    item.classList.add("flash");
    setTimeout(function(){ item.classList.remove("flash"); }, 400);
    el("linkTip").textContent = "不对——「" + linkState.sel + "」不在那里。再试（错选会扣分）。";
  }
}

/* ---------- 证据卡 ---------- */
function showEvCard(pts, right){
  var h = ['<h3>' + (right ? "✓ 对了" : "✗ 错了") + ' · 本题 +' + pts + ' 分</h3>'];
  if(cur.type === "feihualing"){
    var r = cur.evidence.real;
    h.push('<div class="evrow">真句：<b class="kai">「' + esc(r.line) + '」</b>——' + esc(r.poet) + '《' + esc(r.title) + '》</div>');
    h.push('<div class="evrow">语料中含「' + esc(cur.char) + '」的诗句共 <b>' + cur.evidence.corpus_hits + '</b> 句；其余三项均不含该字。</div>');
  } else if(cur.type === "imagery_home"){
    if(cur.evidence.kind === "lift_table"){
      h.push('<div class="evrow">各分区对线索词的 lift（&gt;1 为过表征）：</div><table class="mtab"><tr><th>分区</th><th>线索词命中</th></tr>');
      cur.evidence.rows.forEach(function(row){
        h.push('<tr><td>' + esc(row.region) + '</td><td class="kai">' + esc(row.hits) + '</td></tr>');
      });
      h.push('</table>');
    } else {
      h.push('<div class="evrow">「' + esc(cur.evidence.region) + '」的过表征意象：</div>');
      cur.evidence.words.forEach(function(w){
        h.push('<div class="evrow"><span class="lift kai">' + w.lift + '×</span> <b class="kai">' + esc(w.word) + '</b>（' + w.n_wr + '/' + w.n_w + ' 首）</div>');
      });
    }
    h.push('<div class="src">来源：<a href="' + esc(cur.evidence.source.split("（")[0]) + '" target="_blank">' + esc(cur.evidence.source) + '</a></div>');
  } else {
    h.push('<table class="mtab"><tr><th>古名</th><th>今地</th><th>词典备注</th></tr>');
    cur.pairs.forEach(function(p){
      h.push('<tr><td class="kai">「' + esc(p.alias) + '」</td><td>' + esc(p.modern) + '</td><td>' + esc(p.note) + '</td></tr>');
    });
    h.push('</table><div class="src">共错选 ' + linkState.wrongTries + ' 次，得分 800 × 4/(4+' + linkState.wrongTries + ')。</div>');
  }
  el("evCard").innerHTML = h.join("");
  el("evCard").style.display = "block";
}

function saveAndNext(){
  S.qi += 1;
  writeSave({qi:S.qi, score:S.score, correct:S.correct, best:S.best, wrong:S.wrong, done:S.qi >= QS.length});
  var nx = document.createElement("button");
  nx.className = "act";
  nx.id = "btnNext";
  nx.textContent = S.qi >= QS.length ? "加行终了 →" : "下一题 →";
  nx.onclick = function(){ if(S.qi >= QS.length) endGame(); else showQ(); };
  var bar = el("evCard");
  bar.appendChild(document.createElement("hr"));
  bar.appendChild(nx);
}

/* ---------- 提示 / 终局 ---------- */
el("btnHint").onclick = function(){
  if(answered || cur.type === "link") return;
  hintUsed = true;
  el("hintText").textContent = "【提示】" + cur.hint.text;
  el("hintText").style.display = "block";
  el("btnHint").disabled = true;
};
function rankOf(pct){
  if(pct >= 0.85) return ["酒中仙","飞花摘叶皆可入令——语料在你手里成了酒器。"];
  if(pct >= 0.70) return ["飞花手","令出即应，意象与地名都已入囊。"];
  if(pct >= 0.50) return ["行令人","渐入佳境——错题诗签里的证据句值得再读一遍。"];
  return ["投壶手","初学行令——每一枚诗签都是下一轮的令字。"];
}
function endGame(){
  el("gameArea").style.display = "none";
  el("endArea").style.display = "block";
  var pct = S.score / MAX;
  var rk = rankOf(pct);
  el("endRank").textContent = rk[0];
  el("endQuote").textContent = rk[1];
  el("endScore").textContent = S.score;
  el("endAcc").textContent = S.correct + "/" + QS.length;
  el("endStreak").textContent = S.best;
  el("qianList").innerHTML = S.wrong.length ? S.wrong.map(function(w){
    var q = QS[w.qi];
    return "<span data-qi=\"" + w.qi + "\">" + esc(typeName(q.type)) + " · " + esc(q.prompt.slice(0, 24)) + "…</span>";
  }).join("") : "（无错题——行囊空空，诗句满襟。）";
  Array.prototype.forEach.call(el("qianList").children, function(sp){
    sp.onclick = function(){ review(+sp.getAttribute("data-qi")); };
  });
}
function review(qi){
  var q = QS[qi];
  var b = el("qBody");
  el("endArea").style.display = "none";
  el("gameArea").style.display = "block";
  if(q.type === "link"){
    renderLink(b);
    Array.prototype.forEach.call(b.querySelectorAll(".litem"), function(it){
      it.classList.add("lock");
      it.onclick = null;
    });
  } else {
    var html = ['<div class="opts">'];
    q.options.forEach(function(o, i){
      var label = o.line !== undefined ? esc(o.line) : (o.region !== undefined ? esc(o.region) : esc(o.word));
      html.push('<button class="opt' + (i === q.correct ? " right" : "") + '" disabled>' + label + '</button>');
    });
    html.push('</div>');
    b.innerHTML = html.join("");
  }
  el("qNo").textContent = "诗签复读";
  el("qType").textContent = "· " + typeName(q.type) + " ·";
  el("qPrompt").textContent = q.prompt;
  el("hintBar").style.display = "none";
  var keepCur = cur, keepLink = linkState, keepAnswered = answered;
  cur = q; answered = true; linkState = {wrongTries: 0};
  showEvCard(0, false);
  cur = keepCur; linkState = keepLink; answered = keepAnswered;
  var back = document.createElement("button");
  back.className = "act ghost";
  back.textContent = "返回终局 ←";
  back.onclick = function(){
    el("evCard").style.display = "none";
    el("gameArea").style.display = "none";
    el("endArea").style.display = "block";
  };
  el("evCard").appendChild(document.createElement("hr"));
  el("evCard").appendChild(back);
}

el("btnAgain").onclick = function(){ clearSave(); S = {qi:0, score:0, correct:0, streak:0, best:0, wrong:[]};
  el("endArea").style.display = "none"; el("gameArea").style.display = "block"; showQ(); };
el("btnReset").onclick = function(){ clearSave(); location.reload(); };

/* ---------- 启动 ---------- */
(function boot(){
  var sv = loadSave();
  if(sv && sv.qi > 0 && sv.qi < QS.length && !sv.done){
    el("resumeBar").style.display = "block";
    el("rQi").textContent = sv.qi + 1;
    el("rScore").textContent = sv.score;
    el("btnResume").onclick = function(){
      el("resumeBar").style.display = "none";
      S = {qi:sv.qi, score:sv.score, correct:sv.correct||0, streak:0, best:sv.best||0, wrong:sv.wrong||[]};
      showQ();
    };
    el("btnFresh").onclick = function(){
      el("resumeBar").style.display = "none";
      clearSave();
      showQ();
    };
  } else {
    showQ();
  }
})();
})();
</script>
</body>
</html>
"""


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    if not SRC_JSON.exists():
        raise SystemExit("[failed] 缺少题库，先运行 tools/build_side_quest_bank.py")
    data = json.loads(SRC_JSON.read_text(encoding="utf-8"))

    data_js = json.dumps(data, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    data_js = data_js.replace("</", "<\\/")

    html = (
        HTML_TMPL
        .replace("__DATA__", data_js)
        .replace("__N__", str(data["meta"]["n_questions"]))
        .replace("__NF__", str(data["meta"]["n_feihualing"]))
        .replace("__NI__", str(data["meta"]["n_imagery"]))
        .replace("__NL__", str(data["meta"]["n_link"]))
        .replace("__MAX__", str(data["meta"]["n_questions"] * data["meta"]["base_points"]))
        .replace("__POLICY__", data["meta"]["policy"])
    )
    assert "NaN" not in html and "Infinity" not in html, "页面字面出现 NaN/Infinity"
    assert "__DATA__" not in html, "模板占位未替换"
    assert len(html.encode("utf-8")) >= 12000, "页面过小"

    OUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_HTML, "w", encoding="utf-8") as f:
        f.write(html)

    print("OK  ->", OUT_HTML, f"({OUT_HTML.stat().st_size} bytes)")
    print(f"题 {data['meta']['n_questions']}（飞花令 {data['meta']['n_feihualing']} / 意象 {data['meta']['n_imagery']} / 连线 {data['meta']['n_link']}）")


if __name__ == "__main__":
    main()
