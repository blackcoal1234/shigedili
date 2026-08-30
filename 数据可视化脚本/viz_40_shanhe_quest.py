# -*- coding: utf-8 -*-
"""viz_40 山河证道：诗词版 GeoGuessr（卷一·六家行迹，四章闯关）。

「诗歌地域化」主题的游戏化落地，章节化关卡壳（阶段二）：
  章节中枢（诗印集章 / 考据馆解锁 / 玩家行旅地图）
  → 每章 3~7 题（读诗句 → 三级提示 → 地图落子 → 距离计分）
  → 学习卡五层（对照/全诗/证据链/古今对照/考据与导读）
  → 章末档案卡（本章到访地方的诗格档案 + 盖诗印 + 解锁考据馆）。

卷一四章依 24 题实际作地分布划定（关即区域）：两京·朔方 / 巴蜀 / 江南 / 荆楚·江右。
通关一章解锁下一章；集齐四章诗印为卷一通关，按总分授予称号。

前置：先运行 tools/build_place_profile.py 与 tools/build_quiz_bank.py。
产出：output/40_山河证道.html（数据内嵌，file:// 直接可开，本地 ECharts 资产）。

口径：
  - 题目作地仅取人工核验 A/B 级证据；导读为规则模板并显式标注「非人工考据」。
  - 计分 round(5000 × exp(-距离km/300) × 提示系数)；提示系数取已用最严一档。
  - 第一章前 3 题为教学关（提示免费）；300 公里内记「答对」；错题收进行囊（诗签）。
  - 进度存 localStorage（shxw40_v2），断点续玩；可一键重置。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
QUIZ_JSON = ROOT / "output" / "assets" / "competition" / "quiz_bank.json"
PROFILE_JSON = ROOT / "output" / "assets" / "competition" / "place_profile.json"
INTROS_JSON = ROOT / "output" / "assets" / "competition" / "chapter_intros.json"
COVERAGE_JSON = ROOT / "output" / "assets" / "competition" / "fact_coverage.json"
OUT_HTML = ROOT / "output" / "40_山河证道.html"

SUFFIX_RE = re.compile(r"(省|市|县|区|特别行政区)$")


def _norm(name: str) -> str:
    prev = None
    cur = (name or "").strip()
    while cur and cur != prev:
        prev = cur
        cur = SUFFIX_RE.sub("", cur)
    return cur


def match_profile(answer: dict, profile_places: list[dict]) -> dict | None:
    """把题面答案（如「山东省青州市」）对上 place_profile 的地方条目。"""
    modern = answer.get("modern") or ""
    province = answer.get("province") or ""
    candidates = {modern, _norm(modern)}
    stripped = re.sub(rf"^{province}(省|自治区|特别行政区)?", "", modern)
    candidates |= {stripped, _norm(stripped)}
    historical = answer.get("historical") or ""
    if historical:
        candidates |= {historical, _norm(historical)}
    for place in profile_places:
        if place["key"] in candidates or place["modern"] in candidates:
            return place
    return None


def trim_profile(place: dict | None) -> dict | None:
    if not place:
        return None
    return {
        "key": place["key"],
        "modern": place["modern"],
        "province": place["province"],
        "historical_aliases": place.get("historical_aliases", [])[:8],
        "composed_n": place["composed_n"],
        "mentions_n": place["mentions_n"],
        "mention_poets_n": place["mention_poets_n"],
        "locality_rate": place["locality_rate"],
        "imagery_top": place["imagery_top"][:6],
        "mention_sample_titles": place["mention_sample_titles"][:6],
    }


HTML_TMPL = r"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>40 · 山河证道 —— 从意象读出地理</title>
<script src="assets/pyecharts/v6/echarts.min.js"></script>
<script src="assets/pyecharts/v6/maps/china.js"></script>
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
/* ---- 章节中枢 ---- */
#sealRow{display:flex;gap:14px;margin:14px 0 4px;flex-wrap:wrap;}
.seal{width:64px;height:64px;border-radius:50%;border:2px dashed #c3cac3;display:flex;align-items:center;justify-content:center;
  font-family:KaiTi,STKaiti,serif;font-size:30px;color:#c3cac3;background:#f7f9f6;position:relative;}
.seal.on{border:3px solid var(--cinnabar);color:var(--cinnabar);background:#fdf6f2;box-shadow:0 0 0 2px #fff,0 2px 6px rgba(182,75,63,.3);}
.seal .sn{position:absolute;bottom:-20px;left:50%;transform:translateX(-50%);font-size:11px;color:#6a726c;white-space:nowrap;font-family:"Microsoft YaHei",sans-serif;}
#chCards{display:flex;gap:12px;flex-wrap:wrap;margin-top:10px;}
.chcard{flex:1 1 240px;background:#fbfcfa;border:1px solid #dfe4de;border-top:4px solid var(--blue);border-radius:10px;padding:10px 14px;position:relative;}
.chcard.locked{opacity:.55;}
.chcard h3{margin:2px 0 2px;font-size:19px;}
.chcard .th{font-size:12.5px;color:#6a726c;min-height:38px;}
.chcard .st{font-size:13px;margin:4px 0;}
.chcard .st b{color:var(--cinnabar);}
button.act{cursor:pointer;background:var(--jade);color:#fff;border:none;border-radius:8px;padding:7px 18px;font-size:14.5px;font-family:KaiTi,STKaiti,serif;letter-spacing:2px;}
button.act:disabled{background:#a9b3ad;cursor:not-allowed;}
button.act.ghost{background:transparent;color:var(--jade);border:1px solid var(--jade);}
button.act.warn{background:var(--cinnabar);}
button.act.sm{padding:3px 12px;font-size:12.5px;letter-spacing:1px;}
#hub2col{display:flex;gap:14px;margin-top:14px;flex-wrap:wrap;align-items:stretch;}
#kao{flex:1 1 340px;}
#journey{flex:1 1 420px;background:#fbfcfa;border:1px solid #dfe4de;border-radius:10px;padding:8px;min-height:300px;}
#jmap{width:100%;height:300px;}
.kgrid{display:flex;gap:8px;flex-wrap:wrap;margin-top:8px;}
.kitem{border:1px solid #cfd6d0;border-radius:8px;padding:6px 10px;font-size:12.5px;background:#fff;min-width:150px;}
.kitem a{color:var(--blue);text-decoration:none;font-weight:bold;}
.kitem a:hover{text-decoration:underline;}
.kitem .note{color:#6a726c;font-size:11.5px;}
.kitem.lock{background:#f2f4f0;color:#9aa39b;border-style:dashed;}
.kitem.lock b{color:#9aa39b;}
/* ---- 答题 ---- */
#gameArea{display:flex;gap:14px;margin-top:14px;flex-wrap:wrap;align-items:stretch;}
.left{flex:1 1 380px;min-width:340px;}
.right{flex:1 1 520px;min-width:340px;}
#mapWrap{background:#fbfcfa;border:1px solid #dfe4de;border-radius:10px;height:520px;position:relative;}
#map{position:absolute;inset:8px;}
.mapHint{position:absolute;left:14px;top:10px;font-size:12.5px;color:#6a726c;z-index:5;background:rgba(251,252,250,.85);border-radius:6px;padding:2px 8px;}
.qhead{display:flex;gap:12px;align-items:baseline;font-size:13.5px;color:#3c443f;margin-bottom:8px;flex-wrap:wrap;}
.qhead .qno{font-family:KaiTi,STKaiti,serif;font-size:18px;color:var(--ink);}
.qhead .chn{color:var(--gold);font-family:KaiTi,STKaiti,serif;font-size:15px;}
.badge{display:inline-block;border-radius:4px;padding:0 8px;font-size:12px;line-height:20px;}
.b1{background:#e4ece7;color:var(--jade);border:1px solid #bcd3c9;}
.b2{background:#f4ead8;color:var(--gold);border:1px solid #dcc39a;}
.poemcard{background:#fbfcfa;border:1px solid #dfe4de;border-left:4px solid var(--cinnabar);border-radius:10px;padding:14px 18px;}
.poemcard .kai{font-size:21px;line-height:2;}
.poemcard .src{margin-top:6px;font-size:13px;color:#6a726c;}
#hintArea{margin-top:12px;}
.hbtns{display:flex;gap:8px;flex-wrap:wrap;}
.hbtn{flex:1 1 150px;cursor:pointer;text-align:left;background:#fbfcfa;border:1px solid #cfd6d0;border-radius:8px;padding:7px 10px;font-size:13px;color:#3c443f;transition:all .15s;}
.hbtn:hover:not(:disabled){border-color:var(--jade);background:#f0f5f2;}
.hbtn:disabled{opacity:.55;cursor:not-allowed;}
.hbtn .cost{color:var(--cinnabar);font-weight:bold;}
.hbtn .free{color:var(--jade);font-weight:bold;}
.hintext{background:#f6f2e8;border:1px dashed #d8c9a3;border-radius:8px;padding:8px 12px;margin-top:8px;font-size:13.5px;color:#4a4436;display:none;}
#guessBar{margin-top:12px;display:flex;gap:10px;align-items:center;flex-wrap:wrap;}
#guessBar .tip{font-size:13px;color:#6a726c;flex:1 1 160px;}
#multNow{font-size:13px;color:var(--gold);}
#progBar{height:8px;background:#e3e7e1;border-radius:4px;overflow:hidden;margin:6px 0 0;}
#progFill{height:100%;width:0;background:linear-gradient(90deg,var(--jade),var(--gold));transition:width .3s;}
/* ---- 章末 / 弹窗 ---- */
#chEnd .rank{font-size:34px;font-family:KaiTi,STKaiti,serif;color:var(--cinnabar);letter-spacing:8px;}
#chEnd .bigseal{float:right;width:96px;height:96px;border-radius:50%;border:4px solid var(--cinnabar);color:var(--cinnabar);
  display:flex;align-items:center;justify-content:center;font-family:KaiTi,STKaiti,serif;font-size:48px;margin-left:14px;
  background:#fdf6f2;transform:rotate(-8deg);box-shadow:0 2px 8px rgba(182,75,63,.25);}
.stat3{display:flex;gap:12px;flex-wrap:wrap;margin:10px 0;}
.stat3>div{flex:1 1 120px;text-align:center;background:#f6f8f4;border:1px solid #e0e5de;border-radius:8px;padding:8px;}
.stat3 .v{font-size:22px;font-family:KaiTi,STKaiti,serif;}
.stat3 .k{font-size:12px;color:#6a726c;}
.placeRows{clear:both;}
.placeRow{border:1px solid #dfe4de;border-radius:8px;padding:6px 12px;margin:6px 0;font-size:13px;background:#fff;}
.placeRow b{color:var(--blue);font-family:KaiTi,STKaiti,serif;font-size:15px;}
.placeRow .lr{color:var(--gold);}
.qian span{display:inline-block;background:#fff;border:1px solid #d8cdb0;border-radius:6px;padding:2px 10px;margin:3px 4px 3px 0;font-size:13px;cursor:pointer;color:#4a4436;}
.qian span:hover{border-color:var(--gold);color:var(--gold);}
.mask{position:fixed;inset:0;background:rgba(37,43,39,.5);display:none;z-index:50;align-items:flex-start;justify-content:center;padding:24px 14px;overflow-y:auto;}
.mask.on{display:flex;}
.mbox{background:#fbfcfa;border:1px solid #dfe4de;border-radius:12px;max-width:760px;width:100%;padding:20px 24px;margin:auto 0;}
.mclose{margin-left:auto;border:none;background:transparent;font-size:22px;cursor:pointer;color:#5a615c;line-height:1;}
.mclose:hover{color:var(--cinnabar);}
.lc-head{display:flex;align-items:baseline;gap:12px;flex-wrap:wrap;border-bottom:2px solid var(--ink);padding-bottom:8px;}
.lc-head .dist{font-size:26px;font-family:KaiTi,STKaiti,serif;}
.lc-head .pts{color:var(--cinnabar);font-weight:bold;}
.lc-place{margin:10px 0 4px;font-family:KaiTi,STKaiti,serif;font-size:19px;}
.lc-place small{font-size:13px;color:#6a726c;font-family:"Microsoft YaHei",sans-serif;}
.lc-poem{background:#f6f8f4;border:1px solid #e0e5de;border-radius:8px;padding:10px 14px;margin-top:10px;}
.lc-poem .t{font-family:KaiTi,STKaiti,serif;font-size:17px;}
.lc-poem .b{white-space:pre-wrap;font-family:KaiTi,STKaiti,serif;font-size:15.5px;line-height:1.9;margin-top:4px;}
.lc-sec{margin-top:14px;}
.lc-sec h3{margin:0 0 6px;font-size:15px;color:var(--blue);border-left:3px solid var(--blue);padding-left:8px;}
.chips{display:flex;flex-wrap:wrap;gap:6px;}
.chip{border:1px solid #cfd6d0;border-radius:14px;padding:1px 10px;font-size:12.5px;background:#fff;}
.chip .w{font-family:KaiTi,STKaiti,serif;font-size:15px;}
.chip.pos{border-color:#a9c4ba;color:var(--jade);}
.chip.neg{border-color:#ddb1a9;color:var(--cinnabar);}
table.ptab{border-collapse:collapse;width:100%;font-size:13px;margin-top:4px;}
table.ptab th,table.ptab td{border:1px solid #dfe4de;padding:4px 8px;text-align:left;}
table.ptab th{background:#eef1ec;font-weight:normal;color:#4a524c;}
.duo{display:flex;gap:12px;flex-wrap:wrap;margin-top:6px;}
.duo>div{flex:1 1 280px;border:1px solid #dfe4de;border-radius:8px;padding:10px 12px;font-size:13.5px;}
.duo .h{font-size:14px;margin-bottom:6px;}
.duo .kao .h{color:var(--jade);border-left:3px solid var(--jade);padding-left:8px;}
.duo .dao .h{color:var(--gold);border-left:3px solid var(--gold);padding-left:8px;}
.duo .dao{background:#faf7ef;}
.evrow{margin:6px 0;padding-left:8px;border-left:2px solid #cfd6d0;}
.evrow .g{display:inline-block;border-radius:3px;padding:0 5px;font-size:11.5px;color:#fff;background:var(--jade);margin-right:6px;}
.evrow .g.A{background:var(--blue);}
.evrow .src{font-size:12px;color:#6a726c;}
.more li{margin:4px 0;}
.lc-btns{display:flex;gap:10px;margin-top:16px;flex-wrap:wrap;justify-content:flex-end;}
.arc-row{margin:6px 0;font-size:13.5px;}
.arc-row b{color:var(--blue);}
footer{margin-top:18px;border-top:1px solid #dfe4de;padding-top:10px;font-size:12.5px;color:#6a726c;}
/* ---- 章题开卷卡（Seedance 槽位；无视频时水墨底降级） ---- */
#introOv{position:fixed;inset:0;z-index:60;display:none;background:linear-gradient(135deg,#f2f4f0 0%,#e8ece4 55%,#dfe4d8 100%);}
#introOv.on{display:block;}
#introOv video{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;opacity:.92;}
#introOv .iposter{position:absolute;inset:0;background-size:cover;background-position:center;}
#introBox{position:relative;width:100%;height:100%;display:flex;align-items:center;justify-content:center;}
.itext{text-align:center;position:relative;padding:28px 40px;border-radius:14px;background:rgba(251,252,250,.75);box-shadow:0 4px 18px rgba(37,43,39,.12);max-width:580px;margin:16px;}
.iseal{width:96px;height:96px;margin:0 auto 12px;border:4px solid var(--cinnabar);border-radius:50%;color:var(--cinnabar);font-family:KaiTi,STKaiti,serif;font-size:52px;display:flex;align-items:center;justify-content:center;background:#fdf6f2;transform:rotate(-8deg);}
@keyframes izoom{from{transform:rotate(-8deg) scale(1);}to{transform:rotate(-8deg) scale(1.12);}}
.iname{font-family:KaiTi,STKaiti,serif;font-size:44px;letter-spacing:10px;}
.itheme{color:#4a524c;font-size:15px;margin-top:4px;}
.ikai{font-family:KaiTi,STKaiti,serif;font-size:17px;color:var(--blue);margin-top:10px;}
.iscene{font-size:12px;color:#9aa39b;margin:8px 0 14px;}
/* ---- 固定画卷背景与纸白可读性表面 ---- */
body{background:transparent;position:relative;isolation:isolate;}
body::before{content:"";position:fixed;inset:0;z-index:-2;background:url("assets/generated/remaining_pages_20260830/40_43_mountain_game_v1.png") center center/cover no-repeat;}
body::after{content:"";position:fixed;inset:0;z-index:-1;background:rgba(248,246,238,.52);pointer-events:none;}
.wrap{position:relative;z-index:1;}
.panel,.chcard,#journey,#mapWrap,.poemcard,.mbox{background:rgba(251,252,250,.90);}
#journey,#mapWrap{background:rgba(251,252,250,.94);}
.kitem,.placeRow,.chip,.qian span,.lc-poem,.stat3>div{background-color:rgba(251,252,250,.92);}
@media (prefers-reduced-motion:reduce){.iseal{animation:none !important;}}
@media (max-width:900px){#mapWrap{height:420px;}}
</style>
</head>
<body>
<div class="wrap">
<header>
  <h1>山河证道<span class="sub">卷一 · 六家行迹 · 四章</span></h1>
  <p class="lead">诗行万里 · 地域化竞猜——读诗句，见山河：在地图上点出这首诗写于何处。通关一章，解锁下一章与考据馆；集齐四章诗印，卷一功成。</p>
  <p class="meta-line">共 <b>__NB__</b> 题 / <b>__NCH__</b> 章（作地均有人工核验 <b>A/B 级</b>证据）｜计分 <b>5000 × e<sup>−距离km/300</sup> × 提示系数</b>｜首章前 <b>__TUT__</b> 题教学关提示免费｜数据与口径见页脚</p>
</header>

<!-- ============ 章节中枢 ============ -->
<section id="hubArea">
  <div id="sealRow"></div>
  <div style="clear:both"></div>
  <div id="chCards"></div>
  <div id="hub2col">
    <div class="panel" id="kao">
      <b>考据馆</b>——通关章节解锁深度展项（在本页学习卡之外继续深挖证据）：
      <div class="kgrid" id="kaoGrid"></div>
    </div>
    <div id="journey">
      <div style="font-size:13px;color:#6a726c;padding:4px 8px;">你的行旅——诗人行万里，你行诗万里（绿＝300km 内答对，红＝偏出）</div>
      <div id="jmap"></div>
    </div>
  </div>
  <div style="margin-top:10px;">
    <button class="act ghost sm" id="btnResetAll">清除全部行囊与进度</button>
  </div>
</section>

<!-- ============ 答题 ============ -->
<section id="gameArea" style="display:none;">
  <div class="left">
    <div class="qhead">
      <span class="chn" id="chName"></span>
      <span class="qno" id="qNo">第 1 题</span>
      <span id="qDiff"></span>
      <span>得分 <b id="scoreNow" style="color:var(--cinnabar)">0</b></span>
      <span id="streakNow"></span>
      <span style="flex:1 1 30px"></span>
      <span id="multNow"></span>
    </div>
    <div class="poemcard">
      <div class="kai" id="poemLines"></div>
      <div class="src" id="poemSrc"></div>
    </div>
    <div id="hintArea">
      <div class="hbtns">
        <button class="hbtn" id="hProv">一级 · 省份圈定 <span class="cost">×0.7</span><div style="font-size:11.5px;color:#6a726c">缩小到大区</div></button>
        <button class="hbtn" id="hPlace">二级 · 古今对照 <span class="cost">×0.5</span><div style="font-size:11.5px;color:#6a726c">「长安」＝今西安？</div></button>
        <button class="hbtn" id="hImg">三级 · 意象证据 <span class="cost">×0.3</span><div style="font-size:11.5px;color:#6a726c">意象的地域归属</div></button>
      </div>
      <div class="hintext" id="htProv"></div>
      <div class="hintext" id="htPlace"></div>
      <div class="hintext" id="htImg"></div>
    </div>
    <div id="guessBar" class="panel">
      <span class="tip" id="guessTip">在右侧地图上点击你的判断：这首诗写于何处？</span>
      <button class="act" id="btnConfirm" disabled>落子定夺</button>
      <button class="act ghost sm" id="btnBackHub">暂回章节页</button>
    </div>
    <div id="progBar"><div id="progFill"></div></div>
  </div>
  <div class="right">
    <div id="mapWrap">
      <div class="mapHint" id="mapHint">滚轮缩放 · 拖拽平移 · 单击落子</div>
      <div id="map"></div>
    </div>
  </div>
</section>

<!-- ============ 章末 ============ -->
<section id="chEnd" class="panel" style="display:none;"></section>

<div class="panel" id="methodPanel">
  <b>方法与口径</b>——题目作地仅取人工核验事实包中 A/B 级证据记录；卷一四章依 24 题实际作地分布划定（关即区域：两京·朔方／巴蜀／江南／荆楚·江右）。三级提示中意象统计为核验样本确定性计数，古今对照出自项目古地名词典；「导读」由规则模板自动拼装并显式标注<b>非人工考据</b>，与「考据」栏严格分栏；展示句已剔除含诗人名的句子。地方诗格档案来自 tools/build_place_profile.py：在地创作为核验口径，被写入为全量语料扫描口径，在地率为实验性指标（两侧样本口径不同，展示均附 n）。本页零外部依赖：ECharts 与中国地图均为本地资产，进度存于浏览器 localStorage。__COVLINE__
</div>

<footer>
  诗行万里 · 山河证道（卷一）｜__NB__ 题 · __NCH__ 章 · 地方档案 __NBP__ 处｜
  生成：tools/build_quiz_bank.py + tools/build_place_profile.py + 数据可视化脚本/viz_40_shanhe_quest.py
</footer>
</div>

<!-- 学习卡 -->
<div class="mask" id="lcMask"><div class="mbox" id="lcBox"></div></div>
<!-- 地方档案 -->
<div class="mask" id="arcMask"><div class="mbox" id="arcBox"></div></div>
<!-- 章题开卷卡 -->
<div id="introOv"><div id="introBox"></div></div>

<script>
(function(){
"use strict";
var BANK = __DATA__;
var ARCHIVE = __ARCHIVE__;
var INTROS = __INTROS__;
var META = BANK.meta;
var QS = BANK.questions;
var CH = BANK.chapters;
var INTRO_BY = {};
(INTROS.slots || []).forEach(function(s){ INTRO_BY[s.chapter_id] = s; });
var introShown = {};
var TUT = (META.hint_policy && META.hint_policy.tutorial_free_first) || 0;
var MAXPTS = 5000 * QS.length;
var SAVE_KEY = "shxw40_v2";

var el = function(id){ return document.getElementById(id); };
function esc(s){ return String(s==null?"":s).replace(/[&<>"']/g, function(c){
  return {"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c];}); }
function havKm(a, b){
  var R = 6371, p1 = a[1]*Math.PI/180, p2 = b[1]*Math.PI/180;
  var dp = p2 - p1, dl = (b[0]-a[0])*Math.PI/180;
  var h = Math.sin(dp/2)*Math.sin(dp/2) + Math.cos(p1)*Math.cos(p2)*Math.sin(dl/2)*Math.sin(dl/2);
  return 2 * R * Math.asin(Math.sqrt(h));
}

/* ---------- 存档 ---------- */
function blankCh(order){ return {order: order.slice(), qi:0, score:0, correct:0, best:0, wrong:[], done:false}; }
function loadSave(){
  try{
    var s = JSON.parse(localStorage.getItem(SAVE_KEY) || "null");
    if(s && s.ch) return s;
  }catch(e){}
  return {ch:{}, visited:[]};
}
function writeSave(){ try{ localStorage.setItem(SAVE_KEY, JSON.stringify(SAVE)); }catch(e){} }
function clearSave(){ try{ localStorage.removeItem(SAVE_KEY); }catch(e){} }
var SAVE = loadSave();
function chDone(i){ var c = SAVE.ch[CH[i].id]; return !!(c && c.done); }
function allDone(){ for(var i=0;i<CH.length;i++){ if(!chDone(i)) return false; } return true; }
function totalScore(){ var t=0; for(var i=0;i<CH.length;i++){ var c=SAVE.ch[CH[i].id]; if(c) t+=c.score; } return t; }
function totalWrong(){ var w=[]; for(var i=0;i<CH.length;i++){ var c=SAVE.ch[CH[i].id]; if(c) w=w.concat(c.wrong); } return w; }

/* ---------- 地图 ---------- */
var map = null, jmap = null;
function baseMapOption(){
  return {
    geo:{
      map:"china", roam:true, zoom:1.1, scaleLimit:{min:0.8, max:12},
      itemStyle:{areaColor:"#eceee8", borderColor:"#b9c2ba", borderWidth:0.8},
      emphasis:{label:{color:"#3c443f", fontSize:10}, itemStyle:{areaColor:"#e2e8e0"}},
      label:{show:true, color:"#9aa39b", fontSize:8.5},
      select:{disabled:true}
    },
    series:[]
  };
}
function ensureMap(){
  if(map || typeof echarts === "undefined") return;
  map = echarts.init(el("map"));
  map.setOption(baseMapOption());
  map.getZr().on("click", function(params){
    if(revealed || !cur) return;
    var px = [params.offsetX, params.offsetY];
    var co = map.convertFromPixel({geoIndex:0}, px);
    if(!co || !isFinite(co[0]) || !isFinite(co[1])) return;
    if(co[0]<70 || co[0]>140 || co[1]<14 || co[1]>56) return;
    guess = [co[0], co[1]];
    el("btnConfirm").disabled = false;
    el("guessTip").innerHTML = "落子于 " + co[0].toFixed(1) + "°E, " + co[1].toFixed(1) + "°N——确定吗？";
    paintMarkers();
  });
  window.addEventListener("resize", function(){ map && map.resize(); jmap && jmap.resize(); });
}
function ensureJmap(){
  if(typeof echarts === "undefined") return;
  if(!jmap) jmap = echarts.init(el("jmap"));
  var hits = [], misses = [];
  (SAVE.visited||[]).forEach(function(v){
    (v.hit ? hits : misses).push({name:v.modern, value:[v.lon, v.lat]});
  });
  jmap.setOption({
    geo:{
      map:"china", roam:false, zoom:1.05, silent:true,
      itemStyle:{areaColor:"#eceee8", borderColor:"#c6cdc5", borderWidth:0.6},
      label:{show:false}
    },
    series:[
      {type:"scatter", coordinateSystem:"geo", symbolSize:9, itemStyle:{color:"#26786e"},
       label:{show:hits.length<=12, position:"top", color:"#26786e", fontSize:10, formatter:"{b}"},
       data:hits},
      {type:"scatter", coordinateSystem:"geo", symbolSize:8, itemStyle:{color:"#b64b3f", opacity:.75},
       label:{show:false}, data:misses}
    ]
  });
}
function paintMarkers(){
  if(!map) return;
  var series = [{
    type:"scatter", coordinateSystem:"geo", zlevel:2,
    symbolSize:12, itemStyle:{color:"#b64b3f"},
    label:{show:true, position:"top", formatter:"落子", color:"#b64b3f", fontSize:11},
    data: guess ? [{name:"guess", value:guess}] : []
  }];
  if(revealed && guess){
    var ans = [cur.answer.lon, cur.answer.lat];
    series.push({
      type:"scatter", coordinateSystem:"geo", zlevel:2,
      symbolSize:14, itemStyle:{color:"#26786e"},
      label:{show:true, position:"top", formatter:esc(cur.answer.modern), color:"#26786e", fontSize:11},
      data:[{name:"ans", value:ans}]
    });
    series.push({
      type:"lines", coordinateSystem:"geo", zlevel:2,
      lineStyle:{type:"dashed", color:"#a87527", width:2, curveness:0.15},
      data:[{coords:[guess, ans]}]
    });
  }
  map.setOption({series:series});
}

/* ---------- 章节中枢 ---------- */
function renderHub(){
  el("gameArea").style.display = "none";
  el("chEnd").style.display = "none";
  el("hubArea").style.display = "block";
  ensureJmap();
  var seals = [];
  CH.forEach(function(ch, i){
    var on = chDone(i);
    seals.push('<div class="seal' + (on?" on":"") + '">' + (on ? esc(ch.seal) : "？") +
      '<span class="sn">' + esc(ch.name) + '</span></div>');
  });
  el("sealRow").innerHTML = seals.join("");

  var cards = [];
  CH.forEach(function(ch, i){
    var locked = i > 0 && !chDone(i - 1);
    var c = SAVE.ch[ch.id];
    var st, btn;
    if(locked){
      st = "尚未启程——先通关「" + esc(CH[i-1].name) + "」";
      btn = '<button class="act" disabled>未解锁</button>';
    } else if(c && c.done){
      st = "已通关 · 得分 <b>" + c.score + "</b> · 答对 " + c.correct + "/" + c.order.length;
      btn = '<button class="act ghost sm" data-replay="' + i + '">重走此章（乱序）</button>';
    } else if(c && c.qi > 0){
      st = "行至第 " + (c.qi+1) + " / " + c.order.length + " 题 · 已得 " + c.score + " 分";
      btn = '<button class="act" data-go="' + i + '">继续旅程</button>';
    } else {
      st = ch.question_ids.length + " 题待启程" + (i===0 ? " · 前 " + TUT + " 题教学关提示免费" : "");
      btn = '<button class="act" data-go="' + i + '">启程</button>';
    }
    cards.push('<div class="chcard' + (locked?" locked":"") + '" style="border-top-color:' + ch.color + '">' +
      '<h3>' + (chDone(i) ? '「' + esc(ch.seal) + '」 ' : '') + esc(ch.name) + '</h3>' +
      '<div class="th">' + esc(ch.theme) + '</div>' +
      '<div class="st">' + st + '</div><div>' + btn + '</div></div>');
  });
  el("chCards").innerHTML = cards.join("");

  var kao = [];
  CH.forEach(function(ch, i){
    ch.archives.forEach(function(a){
      var open = chDone(i);
      kao.push(open
        ? '<div class="kitem"><a href="' + esc(a.url) + '" target="_blank">' + esc(a.title) + '</a><div class="note">' + esc(a.note) + '</div></div>'
        : '<div class="kitem lock"><b>🔒 ' + esc(a.title) + '</b><div class="note">通关「' + esc(ch.name) + '」解锁</div></div>');
    });
  });
  el("kaoGrid").innerHTML = kao.join("");

  Array.prototype.forEach.call(document.querySelectorAll("[data-go]"), function(b){
    b.onclick = function(){ startChapter(+b.getAttribute("data-go"), false); };
  });
  Array.prototype.forEach.call(document.querySelectorAll("[data-replay]"), function(b){
    b.onclick = function(){ startChapter(+b.getAttribute("data-replay"), true); };
  });
}
el("btnResetAll").onclick = function(){ clearSave(); location.reload(); };

/* ---------- 答题 ---------- */
var S = null;            // 当前章运行态 {ci, order, qi, score, correct, streak, best, wrong}
var cur = null, guess = null, revealed = false, usedHints = {};
var QIDX = {};
QS.forEach(function(q, i){ QIDX[q.id] = i; });

function startChapter(ci, replay){
  var ch = CH[ci];
  var order = ch.question_ids.slice();
  if(replay){
    for(var i=order.length-1;i>0;i--){ var j=Math.floor(Math.random()*(i+1)); var t=order[i]; order[i]=order[j]; order[j]=t; }
    SAVE.ch[ch.id] = blankCh(order);
    writeSave();
  }
  S = {ci:ci, order:(SAVE.ch[ch.id] || (SAVE.ch[ch.id]=blankCh(order))).order,
       qi:SAVE.ch[ch.id].qi, score:SAVE.ch[ch.id].score, correct:SAVE.ch[ch.id].correct,
       streak:0, best:SAVE.ch[ch.id].best, wrong:SAVE.ch[ch.id].wrong};
  el("hubArea").style.display = "none";
  el("chEnd").style.display = "none";
  el("gameArea").style.display = "flex";
  ensureMap();
  if(S.qi === 0){ showIntro(ci, showQ); } else { showQ(); }
}

/* ---------- 章题开卷卡（Seedance 槽位；无视频时水墨底降级） ---------- */
function showIntro(ci, cb){
  var ch = CH[ci];
  var s = INTRO_BY[ch.id] || {};
  if(introShown[ch.id]){ cb && cb(); return; }
  introShown[ch.id] = true;
  var bg = "";
  if(s.video){
    bg = '<video src="' + esc(s.video) + '" autoplay muted loop playsinline' +
         (s.poster ? ' poster="' + esc(s.poster) + '"' : "") + '></video>';
  } else if(s.poster){
    bg = '<div class="iposter" style="background-image:url(' + esc(s.poster) + ')"></div>';
  }
  var animated = !s.video && !s.poster;
  el("introBox").innerHTML = bg + '<div class="itext">' +
    '<div class="iseal"' + (animated ? ' style="animation:izoom 16s ease-in-out infinite alternate"' : "") + '>' + esc(ch.seal) + '</div>' +
    '<div class="iname">' + esc(ch.name) + '</div>' +
    '<div class="itheme">' + esc(ch.theme) + '</div>' +
    (s.poem_line ? '<div class="ikai">「' + esc(s.poem_line) + '」</div>' : "") +
    '<div class="iscene">' + (s.scene
        ? '开卷 · Seedance ' + esc(s.scene) + '《' + esc(s.scene_name) + '》' +
          (s.video ? '' : ' · 视频待生成，水墨底代行')
        : '开卷') + '</div>' +
    '<button class="act" id="introGo">启程 →</button></div>';
  el("introOv").classList.add("on");
  el("introGo").onclick = function(){
    el("introOv").classList.remove("on");
    cb && cb();
  };
}
function persistCh(){
  var c = SAVE.ch[CH[S.ci].id];
  c.qi = S.qi; c.score = S.score; c.correct = S.correct; c.best = S.best; c.wrong = S.wrong;
  writeSave();
}
function showQ(){
  cur = QS[QIDX[S.order[S.qi]]]; guess = null; revealed = false; usedHints = {};
  el("chName").textContent = CH[S.ci].name + " · " + (S.qi+1) + "/" + S.order.length;
  el("poemLines").innerHTML = cur.lines.map(function(l){ return esc(l); }).join("<br>");
  el("poemSrc").innerHTML = esc(cur.dynasty) + "代诗人作 · 题目作者答后揭晓";
  el("qNo").textContent = "第 " + (S.qi+1) + " 题";
  var dn = {1:["b1","易 · 诗中有地名"],2:["b2","中 · 意象充分"],3:["b3","难 · 意象含蓄"]}[cur.difficulty];
  el("qDiff").innerHTML = '<span class="badge '+dn[0]+'">'+dn[1]+'</span>' +
    (S.ci===0 && S.qi < TUT ? ' <span class="badge b1">教学关 · 提示免费</span>' : "");
  el("scoreNow").textContent = S.score;
  el("streakNow").textContent = S.streak > 1 ? "连对 " + S.streak : "";
  el("guessTip").textContent = "在右侧地图上点击你的判断：这首诗写于何处？";
  el("btnConfirm").disabled = true;
  ["Prov","Place","Img"].forEach(function(k){ el("h"+k).disabled = false; });
  ["htProv","htPlace","htImg"].forEach(function(id){ el(id).style.display = "none"; });
  updateMult();
  el("progFill").style.width = (S.qi / S.order.length * 100) + "%";
  if(map) map.setOption(baseMapOption());
}
function hintMult(){
  var m = 1.0;
  if(usedHints.province) m = Math.min(m, 0.7);
  if(usedHints.place) m = Math.min(m, 0.5);
  if(usedHints.imagery) m = Math.min(m, 0.3);
  return m;
}
function updateMult(){
  var free = S.ci===0 && S.qi < TUT;
  ["Prov","Place","Img"].forEach(function(k){
    var b = el("h"+k);
    var tag = b.querySelector(".cost, .free");
    if(tag){ tag.className = free ? "free" : "cost"; tag.textContent = free ? "免费" : ("×" + {Prov:0.7,Place:0.5,Img:0.3}[k]); }
  });
  var m = hintMult();
  el("multNow").textContent = m < 1 ? ("本题得分上限 ×" + m.toFixed(1)) : "";
}
function useHint(kind, textElId, btnId){
  if(revealed) return;
  usedHints[kind] = true;
  var h = cur.hints[kind];
  el(textElId).innerHTML = (kind==="place" ? "【古今对照】" : kind==="imagery" ? "【意象证据】" : "【省份圈定】") + esc(h.text);
  el(textElId).style.display = "block";
  el(btnId).disabled = true;
  updateMult();
}
el("hProv").onclick = function(){ useHint("province","htProv","hProv"); };
el("hPlace").onclick = function(){ useHint("place","htPlace","hPlace"); };
el("hImg").onclick = function(){ useHint("imagery","htImg","hImg"); };
el("btnBackHub").onclick = function(){ persistCh(); renderHub(); };

function fmtBody(b){
  return String(b||"").replace(/\s+/g,"")
    .replace(/([。！？；])/g, "$1\n").replace(/\n+/g,"\n").trim();
}
function confirmGuess(){
  if(!guess || revealed) return;
  revealed = true;
  var ans = [cur.answer.lon, cur.answer.lat];
  var dist = havKm(guess, ans);
  var free = S.ci===0 && S.qi < TUT;
  var mult = free ? 1 : hintMult();
  var pts = Math.round(5000 * Math.exp(-dist/300) * mult);
  S.score += pts;
  var hit = dist <= 300;
  if(hit){ S.correct++; S.streak++; S.best = Math.max(S.best, S.streak); }
  else { S.streak = 0; S.wrong.push({idx:S.order[S.qi], dist:Math.round(dist)}); }
  SAVE.visited.push({lon:ans[0], lat:ans[1], hit:hit, modern:cur.answer.modern});
  paintMarkers();
  el("scoreNow").textContent = S.score;
  el("streakNow").textContent = S.streak > 1 ? "连对 " + S.streak : "";
  el("guessTip").textContent = "本题相距 " + Math.round(dist) + " 公里——详见学习卡";
  el("btnConfirm").disabled = true;
  var last = S.qi === S.order.length - 1;
  S.qi += 1;
  if(last){ SAVE.ch[CH[S.ci].id].done = true; }
  persistCh();
  el("progFill").style.width = (S.qi / S.order.length * 100) + "%";
  showCard(dist, pts, mult, hit, false, last ? function(){ showChEnd(); } : function(){ showQ(); });
}

/* ---------- 学习卡 ---------- */
function showCard(dist, pts, mult, hit, readonly, onNext){
  var q = cur;
  var a = q.answer;
  var h = [];
  h.push('<div class="lc-head"><span class="dist">' + (hit?"✓":"✗") + ' 相距 ' + Math.round(dist) + ' 公里</span>' +
    '<span class="pts">' + (readonly ? "诗签复读" : "+" + pts + " 分" + (mult<1?"（系数 ×"+mult.toFixed(1)+"）":"")) + '</span>' +
    '<button class="mclose" id="lcClose">×</button></div>');
  h.push('<div class="lc-place">' + esc(a.historical ? a.historical + " · " : "") + '今' + esc(a.modern) +
    '（' + esc(a.province) + '）<small>' + (a.year ? "约 " + a.year + " 年 · " : "") +
    '作地证据 ' + a.grade + ' 级</small></div>');
  h.push('<div class="lc-poem"><div class="t">' + esc(q.dynasty) + ' · ' + esc(q.poet) + '《' + esc(q.title) + '》</div>' +
    '<div class="b">' + esc(fmtBody(q.full_body)) + '</div></div>');
  if(q.imagery_hits && q.imagery_hits.length){
    h.push('<div class="lc-sec"><h3>证据链 · 意象</h3><div class="chips">');
    q.imagery_hits.forEach(function(i){
      h.push('<span class="chip ' + (i.emotion>=0?"pos":"neg") + '"><span class="w">' + esc(i.word) +
        '</span> ' + esc(i.cat||"") + (i.line?"｜"+esc(i.line):"") + '</span>');
    });
    h.push('</div></div>');
  }
  var rows = (q.place_names||[]).map(function(p){
    return '<tr><td class="kai">「' + esc(p.alias) + '」</td><td>' + esc(p.modern) + '</td><td>' + esc(p.province) + '</td></tr>';
  });
  rows.push('<tr><td class="kai">本作之地</td><td>' + esc(a.modern) + '</td><td>' + esc(a.province) + '</td></tr>');
  h.push('<div class="lc-sec"><h3>古今地名对照</h3><table class="ptab"><tr><th>诗中/考订</th><th>今地</th><th>省份</th></tr>' + rows.join("") + '</table></div>');
  h.push('<div class="lc-sec"><h3>考据 与 导读（分栏，口径不同）</h3><div class="duo">');
  h.push('<div class="kao"><div class="h">考据 · 人工核验（A/B 级）</div>');
  (q.context_facts||[]).forEach(function(t){ h.push('<div class="evrow">' + esc(t) + '</div>'); });
  (q.evidence||[]).forEach(function(ev){
    h.push('<div class="evrow"><span class="g ' + ev.grade + '">' + ev.grade + '</span>' + esc(ev.excerpt) +
      '<div class="src">出处：' + esc(ev.source) + '</div></div>');
  });
  if(!(q.context_facts||[]).length && !(q.evidence||[]).length) h.push('<div class="evrow">（本题无附加摘录）</div>');
  h.push('</div><div class="dao"><div class="h">' + esc(q.reading_intro.label) + '</div>' + esc(q.reading_intro.text));
  if(q.emotion && q.emotion.primary){
    h.push('<div style="margin-top:6px;font-size:12.5px;color:#6a726c">情感画像：' + esc(q.emotion.primary) +
      '（愉悦度 ' + (q.emotion.valence>=0?"+":"") + q.emotion.valence.toFixed(2) + '，置信 ' + esc(q.emotion.confidence||"") + '）</div>');
  }
  if(q.same_place_more && q.same_place_more.length){
    h.push('<div style="margin-top:8px"><b>同地再读：</b><ul class="more">');
    q.same_place_more.forEach(function(m){
      h.push('<li>' + esc(m.poet) + '《' + esc(m.title) + '》——' + esc(m.line) + '</li>');
    });
    h.push('</ul></div>');
  }
  h.push('</div></div></div>');
  var arch = ARCHIVE[q.id];
  h.push('<div class="lc-btns">');
  if(arch) h.push('<button class="act ghost" id="btnArc">此地诗格档案</button>');
  h.push('<button class="act" id="lcNext">' + (onNext ? ((SAVE.ch[CH[S.ci].id]||{}).done ? "章末档案 →" : "下一题 →") : "返回") + '</button>');
  h.push('</div>');
  el("lcBox").innerHTML = h.join("");
  el("lcMask").classList.add("on");
  el("lcClose").onclick = function(){
    el("lcMask").classList.remove("on");
    if(!readonly && onNext) onNext();   /* 学习卡是本题主界面的一部分：关闭即前进 */
  };
  if(arch) el("btnArc").onclick = function(){ showArchive(q.id); };
  el("lcNext").onclick = function(){
    el("lcMask").classList.remove("on");
    if(onNext) onNext();  /* 复读模式仅关窗，停留原界面 */
  };
}

/* ---------- 地方档案 ---------- */
function showArchive(qid){
  var p = ARCHIVE[qid]; if(!p) return;
  var h = [];
  h.push('<div class="lc-head"><span class="dist">' + esc(p.modern) + ' · 诗格档案</span><button class="mclose" id="arcClose">×</button></div>');
  h.push('<div style="font-size:13px;color:#6a726c">古称：' + (p.historical_aliases||[]).map(esc).join("、") + '</div>');
  h.push('<div class="stat3">' +
    '<div><div class="v">' + p.composed_n + '</div><div class="k">核验在地创作（A/B）</div></div>' +
    '<div><div class="v">' + p.mentions_n + '</div><div class="k">语料被写入（含遥想）</div></div>' +
    '<div><div class="v">' + (p.locality_rate==null?"—":(p.locality_rate*100).toFixed(1)+"%") + '</div><div class="k">在地率（实验指标）</div></div></div>');
  if(p.imagery_top && p.imagery_top.length){
    h.push('<div class="lc-sec"><h3>被写入时的高频意象</h3><div class="chips">' +
      p.imagery_top.map(function(i){ return '<span class="chip ' + (i.avg_emotion>=0?"pos":"neg") + '"><span class="w">' + esc(i.word) + '</span>' + i.count + '</span>'; }).join("") + '</div></div>');
  }
  if(p.mention_sample_titles && p.mention_sample_titles.length){
    h.push('<div class="lc-sec"><h3>写到此地的诗（样本）</h3>');
    p.mention_sample_titles.forEach(function(t){
      h.push('<div class="arc-row">' + esc(t.poet) + '《' + esc(t.title) + '》(' + esc(t.dynasty) + ')</div>');
    });
    h.push('</div>');
  }
  h.push('<div style="font-size:12px;color:#6a726c;margin-top:8px">在地率＝核验在地创作 ÷（核验在地创作＋语料被写入）；两侧样本口径不同，仅为实验性指标。</div>');
  h.push('<div class="lc-btns"><button class="act ghost" id="arcBack">返回学习卡</button></div>');
  el("arcBox").innerHTML = h.join("");
  el("arcMask").classList.add("on");
  el("arcClose").onclick = function(){ el("arcMask").classList.remove("on"); };
  el("arcBack").onclick = function(){ el("arcMask").classList.remove("on"); };
}

/* ---------- 章末档案卡 ---------- */
function rankOf(pct){
  if(pct >= 0.85) return ["诗伯","山河尽在胸臆——你已把这部诗集走成了一幅地图。"];
  if(pct >= 0.70) return ["供奉","好眼力。意象与地理在你这里开始互相指认。"];
  if(pct >= 0.50) return ["游学士","渐入门径——多看学习卡里的证据链，意象自会报出地名。"];
  if(pct >= 0.30) return ["行客","已在路上。行囊里的诗签，都是下一次出发的坐标。"];
  return ["初行者","初行山河，莫愁前路——每一枚错题诗签都是一个再读一首的理由。"];
}
function showChEnd(){
  el("gameArea").style.display = "none";
  el("chEnd").style.display = "block";
  var ch = CH[S.ci];
  var c = SAVE.ch[ch.id];
  var h = [];
  h.push('<div class="bigseal">' + esc(ch.seal) + '</div>');
  h.push('<h2 class="kai">' + esc(ch.name) + ' · 章末档案</h2>');
  h.push('<div class="stat3">' +
    '<div><div class="v">' + c.score + '</div><div class="k">本章得分</div></div>' +
    '<div><div class="v">' + c.correct + '/' + c.order.length + '</div><div class="k">300km 内答对</div></div>' +
    '<div><div class="v">' + c.best + '</div><div class="k">最长连对</div></div>' +
    '<div><div class="v">' + totalScore() + '</div><div class="k">卷一累计</div></div></div>');
  h.push('<div class="placeRows"><h3 style="margin:8px 0 2px;color:var(--blue);border-left:3px solid var(--blue);padding-left:8px;font-size:15px;">本章到访 · 地方诗格</h3>');
  var seen = {};
  c.order.forEach(function(qid){
    var p = ARCHIVE[qid];
    if(!p || seen[p.key]) return;
    seen[p.key] = 1;
    h.push('<div class="placeRow"><b>' + esc(p.modern) + '</b>（' + esc(p.province) + '）　' +
      '核验在地创作 ' + p.composed_n + ' 首 · 被写入 ' + p.mentions_n + ' 首 · <span class="lr">在地率 ' +
      (p.locality_rate==null?"—":(p.locality_rate*100).toFixed(1)+"%") + '</span>' +
      (p.imagery_top && p.imagery_top.length
        ? '<div style="color:#6a726c;font-size:12.5px;margin-top:2px">意象：' +
          p.imagery_top.map(function(i){ return esc(i.word)+"("+i.count+")"; }).slice(0,6).join("、") + '</div>'
        : '') + '</div>');
  });
  h.push('</div>');
  h.push('<div style="margin-top:10px"><b>解锁考据馆：</b>' +
    ch.archives.map(function(a){ return '<a href="' + esc(a.url) + '" target="_blank" style="color:var(--blue)">' + esc(a.title) + '</a>'; }).join("、") + '</div>');
  if(c.wrong.length){
    h.push('<h3 style="margin:12px 0 2px;color:var(--gold);border-left:3px solid var(--gold);padding-left:8px;font-size:15px;">行囊 · 本章错题诗签</h3><div class="qian">');
    c.wrong.forEach(function(w){
      var q = QS[QIDX[w.idx]];
      h.push('<span data-idx="' + w.idx + '" data-dist="' + w.dist + '">' + esc(q.poet) + '《' + esc(q.title) + '》· 差 ' + w.dist + 'km</span>');
    });
    h.push('</div>');
  } else {
    h.push('<div class="kai" style="margin-top:10px;font-size:15px;color:var(--jade)">本章无错题——山河为证，字字皆中。</div>');
  }
  if(allDone()){
    var pct = totalScore() / MAXPTS;
    var rk = rankOf(pct);
    h.push('<div style="margin-top:14px;border-top:2px solid var(--ink);padding-top:10px">' +
      '<div class="rank">' + rk[0] + '</div><div class="kai" style="font-size:15px;color:#4a524c">' + rk[1] + '</div>' +
      '<div style="font-size:13px;color:#6a726c">卷一总得分 ' + totalScore() + ' / ' + MAXPTS + ' · 集齐诗印「' +
      CH.map(function(x){ return esc(x.seal); }).join("") + '」</div></div>');
  }
  h.push('<div class="lc-btns" style="justify-content:flex-start">' +
    '<button class="act" id="btnBackHub2">返回章节页' + (allDone() ? "（可重走任意章）" : "，下一章已解锁") + '</button></div>');
  el("chEnd").innerHTML = h.join("");
  el("btnBackHub2").onclick = renderHub;
  Array.prototype.forEach.call(el("chEnd").querySelectorAll(".qian span"), function(sp){
    sp.onclick = function(){
      var keep = cur;
      cur = QS[QIDX[sp.getAttribute("data-idx")]];
      showCard(+sp.getAttribute("data-dist"), 0, 1, false, true, null);
      cur = keep;
    };
  });
  writeSave();
}

el("btnConfirm").onclick = confirmGuess;

/* ---------- 启动 ---------- */
renderHub();
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

    if not QUIZ_JSON.exists():
        raise SystemExit("[failed] 缺少题库，先运行 tools/build_quiz_bank.py")
    if not PROFILE_JSON.exists():
        raise SystemExit("[failed] 缺少地方档案，先运行 tools/build_place_profile.py")

    bank = json.loads(QUIZ_JSON.read_text(encoding="utf-8"))
    profile = json.loads(PROFILE_JSON.read_text(encoding="utf-8"))
    places = profile["places"]
    if not bank.get("chapters"):
        raise SystemExit("[failed] 题库缺少章节结构，请更新 tools/build_quiz_bank.py 后重跑")
    intros = {"slots": []}
    if INTROS_JSON.exists():
        intros = json.loads(INTROS_JSON.read_text(encoding="utf-8"))
    cov_line = "编年事实覆盖边界见项目《事实覆盖口径说明》。"
    if COVERAGE_JSON.exists():
        cov = json.loads(COVERAGE_JSON.read_text(encoding="utf-8"))
        c = cov["combined"]
        cov_line = (
            f"编年事实覆盖边界（实时）：语料 {cov['corpus']['n_poems_unique']} 首中 "
            f"{c['n_poems_with_facts']} 首有编年事实（{c['coverage_pct']}%，三层口径），"
            f"{c['n_poets_with_facts']}/{cov['corpus']['n_poets']} 位诗人有事实——"
            f"未覆盖为外部编年源不系年的长尾作品，不以候选冒充事实（详见《事实覆盖口径说明》）。"
        )
    chapter_ids = {ch["id"] for ch in bank["chapters"]}
    assert all(s["chapter_id"] in chapter_ids for s in intros.get("slots", [])), (
        "chapter_intros.json 含未知章节，请重跑 tools/build_seedance_slots.py"
    )

    archive: dict[str, dict | None] = {}
    for q in bank["questions"]:
        archive[q["id"]] = trim_profile(match_profile(q["answer"], places))

    data_js = json.dumps(bank, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    data_js = data_js.replace("</", "<\\/")
    arch_js = json.dumps(archive, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    arch_js = arch_js.replace("</", "<\\/")
    intro_js = json.dumps(intros, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    intro_js = intro_js.replace("</", "<\\/")

    html = (
        HTML_TMPL
        .replace("__DATA__", data_js)
        .replace("__ARCHIVE__", arch_js)
        .replace("__INTROS__", intro_js)
        .replace("__NB__", str(len(bank["questions"])))
        .replace("__NCH__", str(len(bank["chapters"])))
        .replace("__TUT__", str(bank["meta"]["hint_policy"]["tutorial_free_first"]))
        .replace("__NBP__", str(len(places)))
        .replace("__COVLINE__", cov_line)
    )
    assert "NaN" not in html, "页面字面出现 NaN"
    assert "Infinity" not in html, "页面字面出现 Infinity"
    assert "__DATA__" not in html and "__ARCHIVE__" not in html and "__INTROS__" not in html and "__COVLINE__" not in html, "模板占位未替换"
    assert len(html.encode("utf-8")) >= 20000, "页面过小，疑似生成不完整"

    OUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_HTML, "w", encoding="utf-8") as f:
        f.write(html)

    n_arch = sum(1 for v in archive.values() if v)
    print("OK  ->", OUT_HTML, f"({OUT_HTML.stat().st_size} bytes)")
    print(
        f"题目 {len(bank['questions'])} | 章节 {len(bank['chapters'])}"
        f"（{'/'.join(ch['name'] for ch in bank['chapters'])}）"
        f" | 地方档案挂接 {n_arch}/{len(archive)}"
    )


if __name__ == "__main__":
    main()
