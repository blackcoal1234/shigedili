# -*- coding: utf-8 -*-
"""viz_41 意象地理：意象 × 地域矩阵（R2 研究展项）。

呈现 tools/build_imagery_region_matrix.py 的产出：
  - 九大文化地理分区的过表征意象（lift 倍率 + 样本量）；
  - 意象×区域热力矩阵，格点可点击下钻原句证据；
  - 分区卡可点击查看该区 top 意象与证据句；
  - 区域省级行政映射与全部阈值口径页内公开。

前置：tools/build_imagery_region_matrix.py。
产出：output/41_意象地理.html（数据内嵌，file:// 直接可开）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC_JSON = ROOT / "output" / "assets" / "competition" / "imagery_region_matrix.json"
OUT_HTML = ROOT / "output" / "41_意象地理.html"

HTML_TMPL = r"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>41 · 意象地理 —— 意象×地域矩阵</title>
<script src="assets/pyecharts/v6/echarts.min.js"></script>
<style>
:root{--paper:#f2f4f0;--ink:#252b27;--cinnabar:#b64b3f;--jade:#26786e;--gold:#a87527;--blue:#426f94;}
*{box-sizing:border-box;}
body{background:var(--paper);color:var(--ink);font-family:"Microsoft YaHei",sans-serif;line-height:1.7;margin:0;padding:16px;}
h1,h2,h3,.kai{font-family:KaiTi,STKaiti,"Microsoft YaHei",serif;}
.wrap{max-width:1180px;margin:0 auto;}
header{border-bottom:2px solid var(--ink);padding-bottom:10px;}
h1{margin:0;font-size:30px;letter-spacing:6px;}
h1 .sub{font-size:16px;color:var(--gold);letter-spacing:2px;margin-left:10px;}
.lead{margin:6px 0 2px;color:#3c443f;}
.meta-line{margin:0;font-size:12.5px;color:#6a726c;}
.meta-line b{color:var(--cinnabar);}
.panel{background:#fbfcfa;border:1px solid #dfe4de;border-radius:10px;padding:12px 16px;margin-top:14px;box-shadow:0 1px 3px rgba(37,43,39,.05);font-size:14px;color:#3c443f;}
#layout{display:flex;gap:14px;margin-top:14px;flex-wrap:wrap;align-items:stretch;}
#regions{flex:0 0 300px;display:flex;flex-direction:column;gap:8px;}
.rcard{background:#fbfcfa;border:1px solid #dfe4de;border-left:4px solid var(--blue);border-radius:8px;padding:8px 12px;cursor:pointer;transition:all .15s;}
.rcard:hover{border-color:var(--jade);background:#f0f5f2;}
.rcard .rn{font-family:KaiTi,STKaiti,serif;font-size:17px;}
.rcard .rs{font-size:12px;color:#6a726c;}
.rcard .chips{margin-top:4px;}
.chip{display:inline-block;border:1px solid #cfd6d0;border-radius:12px;padding:0 8px;margin:1px 3px 1px 0;font-size:12px;background:#fff;}
.chip b{color:var(--cinnabar);font-weight:normal;}
#heatWrap{flex:1 1 560px;min-width:340px;background:#fbfcfa;border:1px solid #dfe4de;border-radius:10px;padding:10px;position:relative;}
#heat{width:100%;height:560px;}
.mapHint{position:absolute;left:18px;top:12px;font-size:12.5px;color:#6a726c;z-index:5;}
.mask{position:fixed;inset:0;background:rgba(37,43,39,.5);display:none;z-index:50;align-items:flex-start;justify-content:center;padding:24px 14px;overflow-y:auto;}
.mask.on{display:flex;}
.mbox{background:#fbfcfa;border:1px solid #dfe4de;border-radius:12px;max-width:640px;width:100%;padding:18px 22px;margin:auto 0;}
.mclose{margin-left:auto;border:none;background:transparent;font-size:22px;cursor:pointer;color:#5a615c;line-height:1;}
.mclose:hover{color:var(--cinnabar);}
.mh{font-family:KaiTi,STKaiti,serif;font-size:20px;border-bottom:2px solid var(--ink);padding-bottom:6px;margin-bottom:8px;}
.mrow{margin:8px 0;font-size:13.5px;}
.mrow b{color:var(--blue);}
.mrow .lift{color:var(--cinnabar);font-family:KaiTi,STKaiti,serif;font-size:16px;}
.sline{border-left:2px solid #d8cdb0;padding:2px 10px;margin:8px 0;font-size:13.5px;}
.sline .kai{font-size:15px;}
.sline .src{font-size:12px;color:#6a726c;}
table.mtab{border-collapse:collapse;width:100%;font-size:12.5px;margin-top:4px;}
table.mtab th,table.mtab td{border:1px solid #dfe4de;padding:3px 8px;text-align:left;}
table.mtab th{background:#eef1ec;font-weight:normal;}
footer{margin-top:16px;border-top:1px solid #dfe4de;padding-top:10px;font-size:12.5px;color:#6a726c;}
@media (max-width:900px){#heat{height:420px;}}
</style>
</head>
<body>
<div class="wrap">
<header>
  <h1>意象地理<span class="sub">意象 × 地域矩阵</span></h1>
  <p class="lead">同一套意象词典扫过全部语料——大漠孤烟真的属于边塞吗？画船藕花真的停在江南吗？把「地域化」变成可复核的倍率。</p>
  <p class="meta-line">定位诗 <b>__NLOC__</b> 首 · 入矩阵意象 <b>__NW__</b> 个 · 九大文化地理分区｜lift＝P(区域|含意象)÷P(区域|提及地名)，只展示过表征（lift&gt;1）且样本达阈值的格点｜点击热力图格点或分区卡查看原句证据</p>
</header>

<div id="layout">
  <div id="regions"></div>
  <div id="heatWrap">
    <div class="mapHint">横向为意象（按最强归属区域分组）· 纵向为分区 · 颜色越红倍率越高</div>
    <div id="heat"></div>
  </div>
</div>

<div class="panel">
  <b>方法与口径</b>——__POLICY__
  <div style="margin-top:8px">分区省级映射（今行政区归并，仅用于聚合展示）：</div>
  <table class="mtab" id="regionMapTab"></table>
</div>

<footer>诗行万里 · 意象地理（R2 意象×地域矩阵）｜生成：tools/build_imagery_region_matrix.py + 数据可视化脚本/viz_41_imagery_geography.py</footer>
</div>

<div class="mask" id="evMask"><div class="mbox" id="evBox"></div></div>

<script>
(function(){
"use strict";
var DATA = __DATA__;
var META = DATA.meta;
var REGIONS = DATA.regions;          // 依 meta 顺序
var WORDS = DATA.words;

function esc(s){ return String(s==null?"":s).replace(/[&<>"']/g, function(c){
  return {"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c];}); }
var el = function(id){ return document.getElementById(id); };

/* ---- 分区卡 ---- */
var rHtml = [];
REGIONS.forEach(function(r, i){
  var chips = r.top_words.slice(0,5).map(function(t){
    return '<span class="chip">' + esc(t.word) + ' <b>' + t.lift.toFixed(1) + '×</b></span>';
  }).join("") || '<span style="font-size:12px;color:#9aa39b">样本不足（' + r.n_poems + ' 首），不构成统计</span>';
  rHtml.push('<div class="rcard" data-ri="' + i + '"><span class="rn">' + esc(r.name) + '</span>' +
    '<span class="rs">' + r.n_poems + ' 首 · ' + r.n_poets + ' 位诗人</span>' +
    '<div class="chips">' + chips + '</div></div>');
});
el("regions").innerHTML = rHtml.join("");

/* ---- 矩阵词序：按最强归属区域分组，组内倍率降序 ---- */
var wordList = Object.keys(WORDS);
function bestRegionOf(w){
  var best = null;
  var regs = WORDS[w].regions || {};
  for (var rid in regs){
    var lv = regs[rid].lift;
    if (lv != null && (!best || lv > best.lift)) best = {rid: rid, lift: lv};
  }
  return best;
}
var regionIndex = {};
REGIONS.forEach(function(r, i){ regionIndex[r.id] = i; });
wordList.sort(function(a, b){
  var ba = bestRegionOf(a), bb = bestRegionOf(b);
  var ia = ba ? regionIndex[ba.rid] : 99, ib = bb ? regionIndex[bb.rid] : 99;
  if (ia !== ib) return ia - ib;
  return (bb ? bb.lift : 0) - (ba ? ba.lift : 0);
});
var wordIndex = {};
wordList.forEach(function(w, i){ wordIndex[w] = i; });

/* ---- 热力图 ---- */
var cells = [];
REGIONS.forEach(function(r, yi){
  r.top_words.forEach(function(t){
    cells.push([wordIndex[t.word], yi, t.lift]);
  });
});
/* 非过表征格点（矩阵词在其它区域的 lift）也入图，形成完整底色 */
wordList.forEach(function(w, xi){
  var regs = WORDS[w].regions || {};
  for (var rid in regs){
    var yi = regionIndex[rid];
    var lv = regs[rid].lift;
    var exists = cells.some(function(c){ return c[0]===xi && c[1]===yi; });
    if (!exists && lv != null) cells.push([xi, yi, lv]);
  }
});
var maxLift = Math.max.apply(null, cells.map(function(c){ return c[2]; }).concat([2]));

var chart = echarts.init(el("heat"));
chart.setOption({
  grid:{left:90, right:30, top:20, bottom:110},
  tooltip:{
    formatter: function(p){
      var w = wordList[p.data[0]], r = REGIONS[p.data[1]];
      var cell = (WORDS[w].regions||{})[r.id] || {n_wr:0};
      return '<b>' + esc(w) + '</b> × ' + esc(r.name) + '<br>lift ' + p.data[2].toFixed(2) +
        '×<br>' + cell.n_wr + ' / ' + WORDS[w].n_w + ' 首（含该意象的诗落在本区）';
    }
  },
  visualMap:{
    min:0, max:maxLift, calculable:true, orient:"horizontal",
    left:"center", bottom:0, itemHeight:120,
    text:["过表征 " + maxLift.toFixed(1) + "×", "低表征 0×"],
    inRange:{color:["#e8ede7","#f3ecd9","#e2c98f","#d99a59","#b64b3f"]}
  },
  xAxis:{
    type:"category", data:wordList, axisLabel:{rotate:58, fontSize:10, color:"#4a524c",
      fontFamily:"KaiTi,STKaiti,serif", interval:0},
    splitLine:{show:true, lineStyle:{color:"#eef1ec"}}
  },
  yAxis:{
    type:"category", data:REGIONS.map(function(r){ return r.name; }),
    axisLabel:{color:"#3c443f", fontSize:12, fontFamily:"KaiTi,STKaiti,serif"},
    splitLine:{show:true, lineStyle:{color:"#eef1ec"}}
  },
  series:[{
    type:"heatmap", data:cells,
    itemStyle:{borderColor:"#fbfcfa", borderWidth:1},
    emphasis:{itemStyle:{borderColor:"#252b27", borderWidth:2}}
  }]
});
window.addEventListener("resize", function(){ chart.resize(); });

/* ---- 证据弹窗 ---- */
function openBox(html){ el("evBox").innerHTML = html; el("evMask").classList.add("on"); }
document.addEventListener("click", function(e){
  if(e.target === el("evMask")) el("evMask").classList.remove("on");
});
function closeRow(){ return '<button class="mclose" onclick="document.getElementById(\'evMask\').classList.remove(\'on\')">×</button>'; }

chart.on("click", function(p){
  var w = wordList[p.data[0]], r = REGIONS[p.data[1]];
  var topRow = null;
  r.top_words.forEach(function(t){ if(t.word === w) topRow = t; });
  var cell = (WORDS[w].regions||{})[r.id] || {};
  var h = ['<div style="display:flex;align-items:baseline"><div class="mh">' + esc(w) + ' × ' + esc(r.name) + '</div>' + closeRow() + '</div>'];
  h.push('<div class="mrow">lift <span class="lift">' + p.data[2].toFixed(2) + '×</span> · 落在本区 <b>' + (cell.n_wr||0) + '</b> / ' + WORDS[w].n_w + ' 首（含「' + esc(w) + '」的诗） · 本区基准占比 ' + (r.base_rate*100).toFixed(1) + '%</div>');
  h.push('<div class="mrow">意象类别：<b>' + esc(WORDS[w].cat||"—") + '</b> · 词典情感倾向 ' + (WORDS[w].emotion >= 0 ? "+" : "") + WORDS[w].emotion + '</div>');
  if (topRow && topRow.samples && topRow.samples.length){
    h.push('<div class="mrow"><b>原句证据（语料样本）：</b></div>');
    topRow.samples.forEach(function(s){
      h.push('<div class="sline"><span class="kai">' + esc(s.line) + '</span><div class="src">——' + esc(s.poet) + '《' + esc(s.title) + '》</div></div>');
    });
  } else {
    h.push('<div class="mrow" style="color:#9aa39b">该格点为矩阵底色（非本区过表征词），不附证据句——分区过表征词见左侧分区卡。</div>');
  }
  openBox(h.join(""));
});

Array.prototype.forEach.call(document.querySelectorAll(".rcard"), function(card){
  card.onclick = function(){
    var r = REGIONS[+card.getAttribute("data-ri")];
    var h = ['<div style="display:flex;align-items:baseline"><div class="mh">' + esc(r.name) + ' · 意象地理档案</div>' + closeRow() + '</div>'];
    h.push('<div class="mrow">被写入 <b>' + r.n_poems + '</b> 首 · <b>' + r.n_poets + '</b> 位诗人 · 语料基准占比 ' + (r.base_rate*100).toFixed(1) + '%</div>');
    if (!r.top_words.length){
      h.push('<div class="mrow" style="color:#9aa39b">定位样本仅 ' + r.n_poems + ' 首，未达统计阈值，不给出归属结论。</div>');
    }
    r.top_words.forEach(function(t){
      h.push('<div class="mrow"><span class="lift">' + t.lift.toFixed(1) + '×</span> <b>' + esc(t.word) + '</b>（' + t.n_wr + '/' + t.n_w + ' 首）' +
        (t.samples && t.samples.length ? '' : ' <span style="color:#9aa39b">（无附证句）</span>') + '</div>');
      (t.samples||[]).forEach(function(s){
        h.push('<div class="sline"><span class="kai">' + esc(s.line) + '</span><div class="src">——' + esc(s.poet) + '《' + esc(s.title) + '》</div></div>');
      });
    });
    openBox(h.join(""));
  };
});

/* ---- 分区映射表 ---- */
var mt = ['<tr><th>分区</th><th>今省级行政区</th></tr>'];
META.regions.forEach(function(r){
  mt.push('<tr><td class="kai">' + esc(r.name) + '</td><td>' + r.provinces.map(esc).join("、") + '</td></tr>');
});
el("regionMapTab").innerHTML = mt.join("");
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
        raise SystemExit("[failed] 缺少矩阵数据，先运行 tools/build_imagery_region_matrix.py")
    data = json.loads(SRC_JSON.read_text(encoding="utf-8"))

    data_js = json.dumps(data, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    data_js = data_js.replace("</", "<\\/")

    html = (
        HTML_TMPL
        .replace("__DATA__", data_js)
        .replace("__NLOC__", str(data["meta"]["n_located_poems"]))
        .replace("__NW__", str(len(data["words"])))
        .replace("__POLICY__", data["meta"]["policy"])
    )
    assert "NaN" not in html, "页面字面出现 NaN"
    assert "Infinity" not in html, "页面字面出现 Infinity"
    assert "__DATA__" not in html, "模板占位未替换"
    assert len(html.encode("utf-8")) >= 15000, "页面过小"

    OUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_HTML, "w", encoding="utf-8") as f:
        f.write(html)

    print("OK  ->", OUT_HTML, f"({OUT_HTML.stat().st_size} bytes)")
    print(f"区域 {len(data['regions'])} | 意象 {len(data['words'])} | 定位诗 {data['meta']['n_located_poems']}")


if __name__ == "__main__":
    main()
