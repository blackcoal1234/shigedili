# -*- coding: utf-8 -*-
"""viz_42 被想象的地方：在地书写 × 身在别处的想象（R3 展项）。

呈现 tools/build_imagination_index.py 的产出——「诗歌地域化」第三项研究产出：
每个地方被写成的诗，多少来自亲历，多少来自身在别处的想象。

两级口径并陈（与数据层一致）：
  核验级：亲历书写（A/B 级作地）vs 遥想书写（核验作地在异地、正文提及本地），
          被想象率＝遥想/(亲历+遥想)，附两侧 n；
  诗人级：六家行旅节点对照（到过 vs 书写而无节点），上界估计，不作结论。

前置：tools/build_imagination_index.py（间接依赖 place_profile）。
产出：output/42_被想象的地方.html（数据内嵌，file:// 直接可开）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC_JSON = ROOT / "output" / "assets" / "competition" / "imagination_index.json"
OUT_HTML = ROOT / "output" / "42_被想象的地方.html"

HTML_TMPL = r"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>42 · 被想象的地方 —— 在地书写与身在别处的想象</title>
<style>
:root{--paper:#f2f4f0;--ink:#252b27;--cinnabar:#b64b3f;--jade:#26786e;--gold:#a87527;--blue:#426f94;}
*{box-sizing:border-box;}
body{background:var(--paper);color:var(--ink);font-family:"Microsoft YaHei",sans-serif;line-height:1.7;margin:0;padding:16px;}
h1,h2,h3,.kai{font-family:KaiTi,STKaiti,"Microsoft YaHei",serif;}
.wrap{max-width:1080px;margin:0 auto;}
header{border-bottom:2px solid var(--ink);padding-bottom:10px;}
h1{margin:0;font-size:30px;letter-spacing:6px;}
h1 .sub{font-size:16px;color:var(--gold);letter-spacing:2px;margin-left:10px;}
.lead{margin:6px 0 2px;color:#3c443f;}
.meta-line{margin:0;font-size:12.5px;color:#6a726c;}
.meta-line b{color:var(--cinnabar);}
.panel{background:#fbfcfa;border:1px solid #dfe4de;border-radius:10px;padding:12px 16px;margin-top:14px;box-shadow:0 1px 3px rgba(37,43,39,.05);font-size:14px;color:#3c443f;}
#layout{display:flex;gap:14px;margin-top:14px;flex-wrap:wrap;align-items:flex-start;}
#rankList{flex:1 1 420px;}
#detail{flex:1 1 420px;position:sticky;top:12px;}
.rrow{display:flex;align-items:center;gap:8px;padding:5px 8px;border-radius:8px;cursor:pointer;}
.rrow:hover{background:#eef2ed;}
.rrow.sel{background:#e8efe9;outline:1px solid #bcd3c9;}
.rname{flex:0 0 72px;font-family:KaiTi,STKaiti,serif;font-size:16px;}
.rbar{flex:1;height:18px;display:flex;border-radius:4px;overflow:hidden;background:#eceee8;}
.rbar .c{background:var(--jade);height:100%;}
.rbar .d{background:var(--cinnabar);height:100%;}
.rnum{flex:0 0 150px;font-size:12px;color:#4a524c;}
.rnum b{color:var(--cinnabar);}
.rtag{flex:0 0 52px;text-align:center;font-size:12px;border-radius:4px;padding:0 4px;}
.hi{background:#f6e3df;color:var(--cinnabar);border:1px solid #ddb1a9;}
.lo{background:#e2ece6;color:var(--jade);border:1px solid #bcd3c9;}
.na{background:#eef1ec;color:#9aa39b;border:1px dashed #cfd6d0;}
.dh{font-family:KaiTi,STKaiti,serif;font-size:24px;border-bottom:2px solid var(--ink);padding-bottom:6px;}
.dsub{font-size:13px;color:#6a726c;margin-top:4px;}
.sec{margin-top:12px;}
.sec h3{margin:0 0 6px;font-size:15px;border-left:3px solid var(--jade);color:var(--jade);padding-left:8px;}
.sec h3.d{border-color:var(--cinnabar);color:var(--cinnabar);}
.ev{border-left:2px solid #cfd6d0;padding:3px 10px;margin:7px 0;font-size:13.5px;}
.ev .kai{font-size:15px;}
.ev .where{color:var(--cinnabar);font-size:12.5px;}
.ev .src{font-size:12px;color:#6a726c;}
.g{display:inline-block;border-radius:3px;padding:0 5px;font-size:11px;color:#fff;background:var(--jade);margin-right:5px;}
.g.A{background:var(--blue);}
.chips{display:flex;flex-wrap:wrap;gap:6px;}
.chip{border:1px solid #cfd6d0;border-radius:12px;padding:1px 10px;font-size:12.5px;background:#fff;}
.chip.v{border-color:#a9c4ba;color:var(--jade);}
.chip.n{border-color:#ddb1a9;color:var(--cinnabar);}
.stat3{display:flex;gap:10px;flex-wrap:wrap;margin:8px 0;}
.stat3>div{flex:1 1 100px;text-align:center;background:#f6f8f4;border:1px solid #e0e5de;border-radius:8px;padding:6px;}
.stat3 .v{font-size:20px;font-family:KaiTi,STKaiti,serif;}
.stat3 .k{font-size:11.5px;color:#6a726c;}
.note{font-size:12px;color:#9aa39b;margin-top:6px;}
footer{margin-top:16px;border-top:1px solid #dfe4de;padding-top:10px;font-size:12.5px;color:#6a726c;}
@media (max-width:820px){#detail{position:static;}}
</style>
</head>
<body>
<div class="wrap">
<header>
  <h1>被想象的地方<span class="sub">在地书写 × 身在别处的想象（R3）</span></h1>
  <p class="lead">每个地方被写成的诗里，多少出自亲历，多少出自身在别处的想象？——把「诗歌地域化」翻到背面看。</p>
  <p class="meta-line">核验诗 <b>__NF__</b> 首 · 入档地方 <b>__NP__</b> 处｜绿＝核验亲历书写，红＝核验「身在别处写此地」｜被想象率＝红/(绿+红)，分母≥__MINN__ 才输出｜点击行查看证据</p>
</header>

<div id="layout">
  <div id="rankList" class="panel">
    <b>地方排名</b>（按核验书写总量降序）：
    <div id="rows"></div>
  </div>
  <div id="detail" class="panel">点击左侧任一地方，查看亲历与遥想的逐条证据。</div>
</div>

<div class="panel">
  <b>方法与口径</b>——__POLICY__
</div>

<footer>诗行万里 · 被想象的地方（R3 在地率/被想象率）｜生成：tools/build_imagination_index.py + 数据可视化脚本/viz_42_dreamed_places.py</footer>
</div>

<script>
(function(){
"use strict";
var DATA = __DATA__;
var META = DATA.meta;
var el = function(id){ return document.getElementById(id); };
function esc(s){ return String(s==null?"":s).replace(/[&<>"']/g, function(c){
  return {"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c];}); }

var maxTotal = Math.max.apply(null, DATA.places.map(function(p){ return p.composed_n + p.dreamed_n; }));

var rows = [];
DATA.places.forEach(function(p, i){
  var total = p.composed_n + p.dreamed_n;
  var cw = Math.round(p.composed_n / maxTotal * 100), dw = Math.round(p.dreamed_n / maxTotal * 100);
  var tag;
  if(p.imagined_rate == null){ tag = '<span class="rtag na">样本不足</span>'; }
  else {
    var pct = Math.round(p.imagined_rate * 100);
    tag = '<span class="rtag ' + (pct >= 50 ? "hi" : "lo") + '">' + pct + '% 遥想</span>';
  }
  rows.push('<div class="rrow" data-i="' + i + '">' +
    '<span class="rname">' + esc(p.modern) + '</span>' +
    '<span class="rbar"><span class="c" style="width:' + cw + '%"></span><span class="d" style="width:' + dw + '%"></span></span>' +
    '<span class="rnum">亲历 ' + p.composed_n + ' · <b>遥想 ' + p.dreamed_n + '</b></span>' + tag + '</div>');
});
el("rows").innerHTML = rows.join("");

function showDetail(i){
  var p = DATA.places[i];
  var h = [];
  h.push('<div class="dh">' + esc(p.modern) + (p.province ? '（' + esc(p.province) + '）' : '') + '</div>');
  h.push('<div class="dsub">核验书写 ' + (p.composed_n + p.dreamed_n) + ' 首' +
    (p.imagined_rate != null ? ' · 被想象率 ' + Math.round(p.imagined_rate*100) + '%（亲历 ' + p.composed_n + ' / 遥想 ' + p.dreamed_n + '）' : ' · 样本不足，不输出率') + '</div>');
  h.push('<div class="stat3">' +
    '<div><div class="v">' + p.composed_n + '</div><div class="k">核验亲历书写</div></div>' +
    '<div><div class="v">' + p.dreamed_n + '</div><div class="k">身在别处写此地</div></div>' +
    '<div><div class="v">' + Object.keys(p.six_writers || {}).length + '</div><div class="k">六家书写人数</div></div>' +
    '<div><div class="v">' + (p.visited_poets || []).length + '</div><div class="k">行旅节点到过</div></div></div>');
  if(p.dreamed.length){
    h.push('<div class="sec"><h3 class="d">身在别处 · 遥想此地（核验级证据）</h3>');
    p.dreamed.forEach(function(d){
      h.push('<div class="ev"><span class="g ' + d.grade + '">' + d.grade + '</span>' +
        '<span class="kai">' + esc(d.poet) + '《' + esc(d.title) + '》</span>' +
        '<div class="where">实作于 ' + esc(d.actual_place) + (d.year ? '（约 ' + d.year + ' 年）' : '') + '</div>' +
        (d.line ? '<div class="kai">「' + esc(d.line) + '」</div>' : '') +
        '<div class="src">诗中「' + esc(d.alias) + '」指向此地</div></div>');
    });
    h.push('</div>');
  } else {
    h.push('<div class="sec"><h3 class="d">身在别处 · 遥想此地</h3><div class="note">核验样本中暂无「作地在异地而提及此地」的诗。</div></div>');
  }
  if(p.composed.length){
    h.push('<div class="sec"><h3>亲历 · 写于此地（A/B 级作地）</h3>');
    p.composed.forEach(function(c){
      h.push('<div class="ev"><span class="g ' + c.grade + '">' + c.grade + '</span>' +
        '<span class="kai">' + esc(c.poet) + '《' + esc(c.title) + '》</span>' +
        (c.year ? '<span class="src">约 ' + c.year + ' 年</span>' : '') + '</div>');
    });
    h.push('</div>');
  }
  var writers = Object.keys(p.six_writers || {});
  if(writers.length){
    h.push('<div class="sec"><h3>六家行旅对照（上界口径）</h3><div class="chips">');
    writers.forEach(function(w){
      var v = (p.visited_poets || []).indexOf(w) >= 0;
      h.push('<span class="chip ' + (v ? "v" : "n") + '">' + esc(w) +
        (v ? ' · 有行旅节点' : ' · 书写而无节点') + '</span>');
    });
    h.push('</div><div class="note">行旅节点为人工选定的知名生平节点，「无节点」≠「未到过」，此口径只作上界参考。</div></div>');
  }
  el("detail").innerHTML = h.join("");
  Array.prototype.forEach.call(document.querySelectorAll(".rrow"), function(r){
    r.classList.toggle("sel", +r.getAttribute("data-i") === i);
  });
}
Array.prototype.forEach.call(document.querySelectorAll(".rrow"), function(r){
  r.onclick = function(){ showDetail(+r.getAttribute("data-i")); };
});
showDetail(0);
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
        raise SystemExit("[failed] 缺少数据，先运行 tools/build_imagination_index.py")
    data = json.loads(SRC_JSON.read_text(encoding="utf-8"))

    data_js = json.dumps(data, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    data_js = data_js.replace("</", "<\\/")

    html = (
        HTML_TMPL
        .replace("__DATA__", data_js)
        .replace("__NF__", str(data["meta"]["n_facts_with_place"]))
        .replace("__NP__", str(data["meta"]["n_places"]))
        .replace("__MINN__", str(data["meta"]["min_n"]))
        .replace("__POLICY__", data["meta"]["policy"])
    )
    assert "NaN" not in html and "Infinity" not in html, "页面字面出现 NaN/Infinity"
    assert "__DATA__" not in html, "模板占位未替换"
    assert len(html.encode("utf-8")) >= 12000, "页面过小"

    OUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_HTML, "w", encoding="utf-8") as f:
        f.write(html)

    print("OK  ->", OUT_HTML, f"({OUT_HTML.stat().st_size} bytes)")
    top = data["places"][0]
    print(f"地方 {data['meta']['n_places']} | 首档：{top['modern']} 亲历{top['composed_n']} 遥想{top['dreamed_n']}")


if __name__ == "__main__":
    main()
