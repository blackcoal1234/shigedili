# -*- coding: utf-8 -*-
"""viz_29 参赛导航 —— 数媒比赛参赛版作品目录（演示起始页）

产出：
  output/29_参赛导航.html

定位：
  一张桌面端作品目录长卷，CARDS 列表中的参赛页面各一张卡（标题 / 一句话看点 /
  缩略说明），以暗夜诗卷与墨迹地理为视觉语言，作为现场演示的起始页。不做数据计算，只做导航；
  卡片文案与各页面自己的标题、副标题保持一致口径。

零参数直接复跑：python 数据可视化脚本/viz_29_competition_index.py
"""
from __future__ import annotations

import os
import re
import json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_HTML = os.path.join(ROOT, "output", "29_参赛导航.html")

# (编号, 文件名, 标题, 一句话看点, 缩略说明, 主色)
CARDS = [
    ("30", "30_诗行万里_参赛版.html", "诗行万里 · 总入口",
     "给每首课本诗一个人生坐标——一页读懂全部数据资产与 __N_EXHIBITS__ 个展项。",
     "__N_ANALYSIS__ 首状态层全作品、__N_POEMS__ 首 canonical 展示证据、__N_JOURNEY__ 个审核行旅节点与 409 词运行时意象词典的总览页（38 号历史对比另保留 160 词口径）：数据从哪里来、证据怎样分级、每个展项回答什么问题。",
     "#252b27"),
    ("31", "31_凝望罗盘.html", "凝望罗盘",
     "谁在望，望向哪个方向，望见了什么——__N_GAZE__ 处「望」的文本地理。",
     "全语料扫描方位凝望，八方玫瑰图＋句级情感染色；每个方向可点击展开原句证据，候选编年均带徽章。",
     "#426f94"),
    ("32", "32_身与心双层地图.html", "身与心双层地图",
     "身在何处（审核行旅实线），心向何方（诗中遥想地名弧线）。",
     "双层地图上下联动：身层是诗人亲历的行旅节点，心层是他们在诗里「想去 / 想到」的地名；两层凸包的错位即精神张力。",
     "#26786e"),
    ("33", "33_平行时空759.html", "平行时空 759",
     "同一年：一个人遇赦狂喜顺流而下，一个人在乱世记下抓人的差役。",
     "公元 759 年，李白《早发白帝城》与杜甫《石壕吏》同年对照；逐句词典命中与系年依据均可展开复核。",
     "#7a5c3d"),
    ("34", "34_一字识诗人.html", "一字识诗人",
     "一个高频字，猜出它属于哪位诗人——用字习惯的统计竞猜。",
     "把六位诗人的用字习惯放进统计里，各自最「像他自己」的二十个字；竞猜互动，点击即出统计证据。",
     "#b64b3f"),
    ("35", "35_两种孤独与夸张签名.html", "两种孤独 × 夸张签名",
     "孤独不是一种，夸张也不归李白独有——数据把两个成见各修正一次。",
     "__N_POETS__ 位精选名家 __N_ANALYSIS__ 首全作品中的孤独语境光谱，与数字夸张的诗人签名对比；榜首与排名随数据重算。",
     "#8a3b2f"),
    ("36", "36_同龄对齐.html", "同龄对齐",
     "同样的虚岁，六位诗人各自正在写什么。",
     "把六位诗人拉回同一条年龄轴：27 类多标签情绪、VAD 三维与文学形容词并列展示；候选系年逐首带徽章与证据句。",
     "#a87527"),
    ("37", "37_可听的诗.html", "可听的诗",
     "给 __N_ANALYSIS__ 首名家全作品做一次「录音」：猿声、钟声、砧声的声音维度。",
     "只统计诗里明写的声音意象，构成六位诗人各自的「声景」；词典与统计口径见页内「方法与数据」。",
     "#9c5d8f"),
    ("38", "38_唐宋意象潮汐.html", "意象潮汐",
     "同一套客观意象词典扫过唐宋正文，看两朝意象如何涨落。",
     "以 __N_ANALYSIS__ 首名家全作品、每万正文汉字率比较唐宋客观意象；跨代作品另列，再让规范诗库的审核节点按五章显影。",
     "#456f8a"),
    ("39", "39_诗人自述生命卷.html", "诗人自述生命卷",
     "从出生走向死亡：88 位诗人分四轮进入第一视角生命叙事。",
     "文本画像覆盖 __N_ANALYSIS__ 首名家全作品；生命章节只绑定规范诗篇、史料与 VAD 情感曲线，其余轮次保留资料就绪状态。",
     "#7d4d63"),
    ("40", "40_山河证道.html", "山河证道",
     "读诗句，在地图上点出它写于何处——诗词版 GeoGuessr，四章闯关集诗印。",
     "24 道题全部来自人工核验 A/B 级作地证据，按作地分四章（两京·朔方／巴蜀／江南／荆楚·江右）；三级提示（省份圈定／古今地名对照／意象地域证据），学习卡分栏考据与导读；通关盖诗印、解锁考据馆、点亮玩家行旅地图。",
     "#b64b3f"),
    ("41", "41_意象地理.html", "意象地理",
     "大漠孤烟真的属于边塞吗？把意象的地域归属变成可复核的倍率。",
     "九大文化地理分区 × 58 个意象的 lift 矩阵：lift＝P(区域|含意象)÷P(区域|提及地名)，只展示样本达阈值的过表征格点；格点可点击下钻原句证据，分区卡附意象地理档案。",
     "#426f94"),
    ("42", "42_被想象的地方.html", "被想象的地方",
     "每个地方被写成的诗，多少出自亲历，多少出自身在别处的想象？",
     "核验级对照：亲历书写（A/B 级作地）vs「身在别处写此地」（作地核验在异地而正文提及本地），被想象率附两侧 n；六家行旅节点对照作上界参考——长安与洛阳是被想象最多的地方。",
     "#7d4d63"),
    ("43", "43_飞花令加行.html", "飞花令·加行卷",
     "山河证道番外：读句辨真、看意象识乡、指古名认今地。",
     "三题型 22 题：地名飞花令（干扰句经校验不含令字）、意象归乡（选项即 R2 lift 矩阵证据）、古今地名连线（词典备注即教学）；确定性生成，重建逐字节一致。",
     "#a87527"),
    ("44", "44_诗页.html", "赏析诗页",
     "一首诗，一页看全——赏析平台的原子单位。",
     "__N_POEMS__ 首每首一个可深链页面（#poem=）：原诗意象高亮、导读卡（助手/模型分徽章，一律标注非人工考据）、审核创作背景（仅 approved）、三层层级作年作地徽章、情感与意象维度、关联入口；诗签收藏只存本机。",
     "#26786e"),
]

HTML_TMPL = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>29 · 作品目录 —— 诗行万里 · 唐宋诗歌数字可视化</title>
<link rel="icon" href="data:,">
<meta name="theme-color" content="#090a09">
<style>
:root{{
  --night:#090a09;
  --night-soft:#10120f;
  --ivory:#f0e6d2;
  --ivory-dim:#aaa293;
  --jade:#4caa91;
  --jade-soft:rgba(76,170,145,.16);
  --gold:#9b8257;
  --gold-soft:rgba(155,130,87,.18);
  --hairline:rgba(240,230,210,.16);
  --hairline-strong:rgba(240,230,210,.30);
  --display:"STKaiti","KaiTi","FangSong",serif;
  --body:"Microsoft YaHei","PingFang SC",sans-serif;
}}
*{{box-sizing:border-box}}
html{{margin:0;padding:0;background:var(--night)}}
body{{
  margin:0;min-width:1180px;color:var(--ivory);font-family:var(--body);
  background:
    radial-gradient(circle at 76% 2%,rgba(76,170,145,.055),transparent 31%),
    radial-gradient(circle at 7% 38%,rgba(155,130,87,.045),transparent 28%),
    linear-gradient(115deg,#090a09 0%,#0c0e0c 46%,#080908 100%);
  font-size:16px;line-height:1.78;
  overflow-x:auto;
}}
a{{color:inherit}}
.page-shell{{
  width:min(2360px,calc(100vw - 112px));margin:0 auto;padding:54px 0 42px;
}}
.atlas{{position:relative;isolation:isolate;overflow:hidden}}
.atlas::before{{
  content:"";position:absolute;inset:0;z-index:-3;pointer-events:none;
  background:
    repeating-linear-gradient(0deg,rgba(240,230,210,.012) 0 1px,transparent 1px 5px),
    linear-gradient(90deg,transparent 0 49.94%,rgba(240,230,210,.025) 50%,transparent 50.06%);
  opacity:.44
}}
.plate-no{{
  position:absolute;top:0;right:10px;z-index:3;color:var(--jade);
  font-family:Georgia,"Times New Roman",serif;font-size:32px;line-height:1;
  letter-spacing:.04em
}}
.route-map{{
  position:absolute;inset:0 0 100px;z-index:-1;width:100%;height:calc(100% - 100px);
  pointer-events:none;overflow:visible
}}
.route-wash{{fill:none;stroke:url(#routeGradient);stroke-width:34;opacity:.09;filter:url(#inkSoft)}}
.route-line{{
  fill:none;stroke:url(#routeGradient);stroke-width:1.35;opacity:.72;
  stroke-dasharray:2 8;stroke-linecap:round
}}
.route-echo{{
  fill:none;stroke:var(--gold);stroke-width:.65;opacity:.22;
  stroke-dasharray:18 12
}}
.route-node{{fill:var(--night);stroke:var(--gold);stroke-width:1.2}}
.route-node--jade{{stroke:var(--jade)}}
.hero{{
  position:relative;width:53%;min-height:720px;padding:14px 4% 0 16px;z-index:2
}}
.hero .kicker{{
  display:flex;align-items:center;gap:18px;color:var(--gold);font-family:var(--display);
  font-size:15px;letter-spacing:.32em
}}
.hero .kicker::after{{content:"";width:72px;height:1px;background:var(--gold);opacity:.78}}
.hero h1{{
  margin:28px 0 10px;font-family:var(--display);font-size:clamp(76px,5vw,116px);
  line-height:.96;letter-spacing:.12em;font-weight:700;text-wrap:balance
}}
.hero .tagline{{
  max-width:880px;margin:0;color:var(--ivory-dim);font-family:var(--display);
  font-size:21px;letter-spacing:.08em;text-wrap:pretty
}}
.hero .rule{{width:64px;height:2px;margin:22px 0 0;border:0;background:var(--jade)}}
.hint{{
  max-width:780px;margin:28px 0 0;color:var(--ivory-dim);font-size:15px;
  line-height:1.95;text-wrap:pretty
}}
.hint .seal{{color:var(--jade)}}
.stats{{
  display:grid;grid-template-columns:repeat(4,minmax(120px,1fr));gap:30px;
  max-width:920px;margin:32px 0 0
}}
.stat{{margin:0;padding:0}}
.stat dt{{
  margin:0;color:var(--ivory);font-family:Georgia,"Times New Roman",serif;
  font-size:31px;line-height:1.1;letter-spacing:.035em;font-variant-numeric:tabular-nums
}}
.stat dd{{margin:8px 0 0;color:var(--ivory-dim);font-size:12px;letter-spacing:.08em}}
.directory{{
  position:relative;z-index:2;display:grid;grid-template-columns:repeat(12,minmax(0,1fr));
  grid-template-rows:500px repeat(8,minmax(260px,auto));column-gap:42px;row-gap:22px;
  margin-top:-620px;padding:0 18px 10px
}}
a.card{{
  position:relative;display:grid;grid-template-columns:94px minmax(0,1fr);align-content:start;
  column-gap:24px;padding:30px 24px 28px 0;color:inherit;text-decoration:none;
  border-top:1px solid var(--hairline);background:linear-gradient(90deg,transparent,rgba(16,18,15,.44));
  transition:border-color .22s ease,background-color .22s ease
}}
a.card::after{{
  content:"";position:absolute;left:94px;top:-2px;width:0;height:2px;background:var(--jade);
  transition:width .22s ease
}}
a.card:hover{{border-color:var(--hairline-strong);background-color:rgba(16,18,15,.58)}}
a.card:hover::after{{width:72px}}
a.card:focus-visible{{outline:2px solid var(--jade);outline-offset:6px}}
.card-index{{
  grid-column:1;grid-row:1;align-self:start;color:var(--jade);font-family:Georgia,"Times New Roman",serif;
  font-size:42px;line-height:1;font-variant-numeric:tabular-nums;text-align:right
}}
.card-copy{{grid-column:2;min-width:0}}
.card .num{{
  color:var(--ivory-dim);font-family:var(--display);font-size:13px;letter-spacing:.18em
}}
.card h2{{
  margin:8px 0 10px;color:var(--ivory);font-family:var(--display);font-size:32px;
  line-height:1.2;letter-spacing:.09em;font-weight:700;text-wrap:balance
}}
.card .hook{{margin:0 0 10px;color:var(--ivory-dim);font-size:14px;line-height:1.8;text-wrap:pretty}}
.card .desc{{margin:0;color:rgba(170,162,147,.82);font-size:12.5px;line-height:1.85;text-wrap:pretty}}
.card .go{{
  display:inline-flex;align-items:center;gap:10px;margin-top:14px;color:var(--jade);
  font-size:13px;letter-spacing:.12em
}}
.card .go::after{{content:"";width:28px;height:1px;background:currentColor;transition:width .22s ease}}
.card:hover .go::after{{width:46px}}
.card.entry{{
  grid-column:8 / 13;grid-row:1;display:block;align-self:start;min-height:430px;margin-top:78px;
  padding:60px 58px 50px;border:1px solid var(--hairline-strong);
  background:linear-gradient(145deg,rgba(16,18,15,.90),rgba(9,10,9,.72))
}}
.card.entry::before{{
  content:"";position:absolute;inset:-24px -24px 24px 24px;z-index:-1;
  border:1px solid var(--gold-soft);pointer-events:none
}}
.card.entry::after{{left:58px;top:-2px}}
.card.entry .card-index{{
  position:absolute;display:block;right:auto;left:-118px;top:-58px;color:var(--jade);
  font-size:34px;text-align:left
}}
.card.entry .card-index::after{{
  content:"";position:absolute;left:50%;top:48px;width:1px;height:72px;background:var(--jade);opacity:.55
}}
.card.entry .card-copy{{display:block}}
.card.entry .num{{font-size:15px}}
.card.entry h2{{margin:18px 0 18px;font-size:48px;letter-spacing:.1em}}
.card.entry .hook{{font-size:17px;line-height:1.9}}
.card.entry .desc{{font-size:14px;line-height:1.95}}
.directory > .card:nth-child(2){{grid-column:4 / 9;grid-row:2}}
.directory > .card:nth-child(3){{grid-column:1 / 6;grid-row:3}}
.directory > .card:nth-child(4){{grid-column:7 / 12;grid-row:3}}
.directory > .card:nth-child(5){{grid-column:1 / 6;grid-row:4}}
.directory > .card:nth-child(6){{grid-column:7 / 12;grid-row:4}}
.directory > .card:nth-child(7){{grid-column:2 / 7;grid-row:5}}
.directory > .card:nth-child(8){{grid-column:8 / 13;grid-row:5}}
.directory > .card:nth-child(9){{grid-column:1 / 6;grid-row:6}}
.directory > .card:nth-child(10){{grid-column:7 / 12;grid-row:6}}
.directory > .card:nth-child(11){{grid-column:2 / 7;grid-row:7}}
.directory > .card:nth-child(12){{grid-column:8 / 13;grid-row:7}}
.directory > .card:nth-child(13){{grid-column:1 / 6;grid-row:8}}
.directory > .card:nth-child(14){{grid-column:7 / 12;grid-row:8}}
.directory > .card:nth-child(15){{grid-column:4 / 10;grid-row:9}}
footer.page-foot{{
  position:relative;z-index:2;display:flex;justify-content:space-between;align-items:center;gap:24px;
  margin:48px 18px 0;border-top:1px solid var(--hairline);padding:22px 0 0;
  color:var(--ivory-dim);font-size:12px;letter-spacing:.05em
}}
footer.page-foot a{{color:var(--jade);text-decoration:none}}
@media (max-width:1680px){{
  .page-shell{{width:calc(100vw - 72px);padding-top:42px}}
  .hero{{min-height:660px;padding-right:3%}}
  .hero h1{{font-size:76px}}
  .hero .tagline{{font-size:18px}}
  .directory{{margin-top:-560px;column-gap:32px;grid-template-rows:470px repeat(8,minmax(250px,auto))}}
  .card.entry{{margin-top:64px;padding:48px 46px 40px}}
  .card.entry h2{{font-size:40px}}
  .card h2{{font-size:28px}}
  .card-index{{font-size:36px}}
}}

/* 参考图锁定：真实 HTML 的 2560×1440 构图级 1:1 重建 */
html,body{{background:#080a0a}}
body{{
  min-width:1280px;overflow-x:hidden;color:#efe0c7;
  background:
    radial-gradient(ellipse at 70% 5%,rgba(49,85,71,.05),transparent 30%),
    radial-gradient(ellipse at 16% 74%,rgba(143,110,60,.035),transparent 34%),
    #080a0a;
  -webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility
}}
.page-shell{{width:100%;margin:0;padding:0}}
.plate-no{{display:none}}
.atlas{{
  width:100%;min-height:calc(56.25vw + 1740px);overflow:hidden;
  background:linear-gradient(90deg,#080a0a 0%,#090b0a 54%,#080a0a 100%)
}}
.atlas::before{{
  position:fixed;z-index:-1;opacity:.30;
  background:
    repeating-linear-gradient(0deg,rgba(239,224,199,.011) 0 1px,transparent 1px 4px),
    repeating-linear-gradient(90deg,rgba(239,224,199,.006) 0 1px,transparent 1px 7px)
}}
.plate-no{{display:none}}
.route-map{{
  inset:auto;left:0;top:0;width:100%;height:56.25vw;max-height:1440px;z-index:0;
  overflow:hidden
}}
.route-map--continuation{{top:56.25vw;height:1680px;max-height:none;opacity:.68}}
.route-wash{{
  stroke-width:56;opacity:.17;filter:url(#inkDisplace);mix-blend-mode:screen;
  animation:ink-settle 1.8s cubic-bezier(.22,1,.36,1) both
}}
.route-ridge{{
  fill:none;stroke:#756b58;stroke-width:24;opacity:.13;filter:url(#inkFray);
  stroke-linecap:round;mix-blend-mode:screen
}}
.route-dust{{
  fill:none;stroke:#b4a17c;stroke-width:92;opacity:.035;filter:url(#inkSoft);
  stroke-linecap:round
}}
.route-line{{
  stroke:#9b8257;stroke-width:1.4;opacity:.68;stroke-dasharray:4200;
  stroke-dashoffset:4200;animation:route-draw 2.25s cubic-bezier(.22,1,.36,1) .18s forwards
}}
.route-echo{{
  stroke:#4caa91;stroke-width:1.05;opacity:.48;stroke-dasharray:3 13;
  animation:route-drift 18s linear infinite
}}
.route-branch{{fill:none;stroke:#9b8257;stroke-width:1;opacity:.38}}
.route-point circle{{
  fill:#080a0a;stroke:#9b8257;stroke-width:1.6;transition:stroke .22s ease,filter .22s ease,r .22s ease
}}
.route-point .point-core{{fill:#9b8257;stroke:none;opacity:.60}}
.route-point.is-active circle{{stroke:#4caa91;filter:drop-shadow(0 0 7px rgba(76,170,145,.75))}}
.route-point.is-active .point-core{{fill:#4caa91;opacity:1}}
.hero{{
  position:absolute;left:4.5%;top:2.66vw;z-index:3;width:31.1%;min-height:0;padding:0
}}
.hero .kicker{{
  gap:20px;color:#b49a70;font-size:.82vw;line-height:1.28;letter-spacing:.34em
}}
.hero .kicker::after{{width:82px;background:#9b8257}}
.hero h1{{
  margin:1.64vw 0 .94vw;font-size:4.75vw;line-height:.94;
  letter-spacing:.22em;color:#efe0c7;text-shadow:0 0 30px rgba(239,224,199,.035)
}}
.hero .tagline{{
  max-width:none;color:#c7bba8;font-size:1vw;line-height:1.5;
  letter-spacing:.055em;white-space:nowrap
}}
.hero .rule{{width:96px;height:2px;margin:.55vw 0 0;background:#4caa91}}
.hint{{
  width:92%;max-width:none;margin:1.35vw 0 0;color:#9c9589;font-size:.69vw;
  line-height:1.95
}}
.hint .seal{{color:#4caa91}}
.stats{{
  width:100%;max-width:none;grid-template-columns:repeat(4,minmax(0,1fr));gap:30px;margin:30px 0 0
}}
.stat dt{{font-size:clamp(24px,1.28vw,33px);color:#e6d7be}}
.stat dd{{margin-top:7px;color:#b3aa9a;font-size:.58vw}}
.geo-note{{
  position:absolute;z-index:3;width:9.2%;color:#afa394;font-family:Georgia,"Times New Roman",serif;
  font-size:.56vw;line-height:1.55;text-align:right;letter-spacing:.065em;
  font-variant-numeric:tabular-nums
}}
.geo-note::after{{
  content:"";position:absolute;left:calc(100% + 14px);top:48%;height:1px;background:#9b8257;opacity:.52
}}
.geo-note .coord{{display:block}}
.geo-note .proof{{display:block;margin-top:5px;color:#9b8257;font-family:var(--body);letter-spacing:.08em}}
.geo-note--a{{left:53.1%;top:4.67vw}}
.geo-note--a::after{{width:4.9vw}}
.geo-note--b{{left:42.5%;top:13.73vw}}
.geo-note--b::after{{width:4.4vw}}
.geo-note--c{{left:21.2%;top:23.18vw}}
.geo-note--c::after{{width:5vw}}
.geo-note--d{{left:6.9%;top:32.29vw}}
.geo-note--d::after{{width:5vw}}
.fold-rule{{
  position:absolute;z-index:1;height:1px;background:rgba(155,130,87,.20);pointer-events:none
}}
.fold-rule--31{{left:36.2%;right:14.5%;top:25.03vw}}
.fold-rule--32{{left:11.3%;right:7.2%;top:35.27vw}}
.fold-rule--34{{left:7.5%;right:7.2%;top:45.23vw}}
.directory{{
  position:relative;z-index:2;display:block;height:calc(56.25vw + 1580px);margin:0;padding:0
}}
.directory > a.card{{
  position:absolute;display:grid;grid-template-columns:3vw minmax(0,1fr);
  gap:0;padding:0;border:0;background:transparent;overflow:visible;
  animation:card-arrive .72s cubic-bezier(.22,1,.36,1) both;
  animation-delay:var(--delay,260ms)
}}
.directory > a.card::after{{display:none}}
.directory > a.card:hover{{background:rgba(239,224,199,.018)}}
.directory > a.card:not(.entry) .card-index{{
  grid-column:1;grid-row:1;color:#4caa91;font-size:1.8vw;text-align:left
}}
.directory > a.card:not(.entry) .card-copy{{
  position:relative;grid-column:2;padding:2px 0 0 1.1vw;border-left:1px solid rgba(155,130,87,.38)
}}
.directory > a.card:not(.entry) .card-copy::after{{
  content:"";position:absolute;left:-5px;bottom:2px;width:8px;height:8px;border:1px solid #9b8257;
  border-radius:50%;background:#080a0a
}}
.directory > a.card:not(.entry) .num{{font-size:.65vw}}
.directory > a.card:not(.entry) h2{{
  margin:7px 0 8px;font-size:1.65vw;line-height:1.15;letter-spacing:.10em
}}
.directory > a.card:not(.entry) .hook{{
  margin-bottom:7px;color:#a9a093;font-size:.67vw;line-height:1.72
}}
.directory > a.card:not(.entry) .desc{{
  color:#8f8a81;font-size:.58vw;line-height:1.72
}}
.directory > a.card:not(.entry) .go{{
  margin-top:8px;font-size:.62vw;letter-spacing:.10em
}}
.directory > .card.entry{{
  left:64.2%;top:8.18vw;width:30.2%;height:17.55vw;min-height:0;margin:0;
  grid-template-columns:1fr;padding:2.3vw 1.4vw 2.1vw;border:1px solid rgba(239,224,199,.28);
  background:linear-gradient(145deg,rgba(15,17,15,.77),rgba(8,10,10,.46));
  box-shadow:inset 0 0 48px rgba(239,224,199,.018)
}}
.directory > .card.entry::before{{
  inset:-1.35vw -1.15vw -1.3vw -1.55vw;border-color:rgba(155,130,87,.27)
}}
.directory > .card.entry::after{{
  content:"";display:block;position:absolute;left:auto;right:20px;top:20px;width:28px;height:28px;
  background:
    linear-gradient(#4caa91,#4caa91) 100% 0/18px 1px no-repeat,
    linear-gradient(#4caa91,#4caa91) 100% 0/1px 18px no-repeat,
    linear-gradient(#4caa91,#4caa91) 0 10px/18px 1px no-repeat,
    linear-gradient(#4caa91,#4caa91) 10px 10px/1px 18px no-repeat;
  opacity:.85
}}
.directory > .card.entry .card-index{{
  left:26.5%;top:-47%;right:auto;color:#4caa91;font-size:1.9vw
}}
.directory > .card.entry .card-index::after{{top:1.65em;height:1.33vw;background:#4caa91}}
.directory > .card.entry .card-copy{{grid-column:1}}
.directory > .card.entry .num{{font-size:.72vw}}
.directory > .card.entry h2{{
  margin:18px 0 16px;font-size:2.35vw;line-height:1.08;letter-spacing:.10em;white-space:nowrap
}}
.directory > .card.entry .hook{{font-size:.66vw;line-height:1.75}}
.directory > .card.entry .desc{{font-size:.58vw;line-height:1.78}}
.directory > .card.entry .go{{margin-top:14px;font-size:.62vw}}
.directory > .card:nth-child(2){{left:36.3%;top:25.2vw;width:25.2%;height:9.84vw}}
.directory > .card:nth-child(3){{left:19.7%;top:36.225vw;width:29.8%;height:8.89vw}}
.directory > .card:nth-child(4){{left:55%;top:36.225vw;width:36.6%;height:8.89vw}}
.directory > .card:nth-child(5){{left:9%;top:45.34vw;width:38%;height:10.3vw}}
.directory > .card:nth-child(6){{left:49.1%;top:45.34vw;width:43.4%;height:10.3vw}}
.directory > .card:nth-child(5) .card-index,
.directory > .card:nth-child(5) .card-copy,
.directory > .card:nth-child(6) .card-index,
.directory > .card:nth-child(6) .card-copy{{transform:translateY(1.25vw)}}
.directory > .card:nth-child(n+7){{
  width:41.5%;min-height:250px;padding:34px 24px 30px 0;border-top:1px solid rgba(155,130,87,.24);
  background:linear-gradient(90deg,transparent,rgba(15,17,15,.30))
}}
.directory > .card:nth-child(7){{left:7.5%;top:calc(56.25vw + 120px)}}
.directory > .card:nth-child(8){{left:52%;top:calc(56.25vw + 120px)}}
.directory > .card:nth-child(9){{left:7.5%;top:calc(56.25vw + 420px)}}
.directory > .card:nth-child(10){{left:52%;top:calc(56.25vw + 420px)}}
.directory > .card:nth-child(11){{left:7.5%;top:calc(56.25vw + 720px)}}
.directory > .card:nth-child(12){{left:52%;top:calc(56.25vw + 720px)}}
.directory > .card:nth-child(13){{left:7.5%;top:calc(56.25vw + 1020px)}}
.directory > .card:nth-child(14){{left:52%;top:calc(56.25vw + 1020px)}}
.directory > .card:nth-child(15){{left:29.25%;top:calc(56.25vw + 1320px);width:41.5%}}
.directory > .card:nth-child(n+7) .card-index{{font-size:40px}}
.directory > .card:nth-child(n+7) h2{{font-size:31px}}
.directory > .card:nth-child(n+7) .hook{{font-size:14px}}
.directory > .card:nth-child(n+7) .desc{{font-size:12.5px}}
footer.page-foot{{
  margin:0 7.5%;padding:24px 0 34px;border-top:1px solid rgba(155,130,87,.24);
  color:#8f8a81
}}
@keyframes route-draw{{to{{stroke-dashoffset:0}}}}
@keyframes route-drift{{to{{stroke-dashoffset:-320}}}}
@keyframes ink-settle{{from{{opacity:0;filter:blur(9px)}}to{{opacity:.17;filter:url(#inkDisplace)}}}}
@keyframes card-arrive{{from{{opacity:0;transform:translateY(16px)}}to{{opacity:1;transform:translateY(0)}}}}
@media (max-width:1680px){{
  .page-shell{{width:100%;padding:0}}
  .hero{{min-height:0;padding:0}}
  .directory{{margin:0;grid-template-rows:none;column-gap:0}}
  .directory > .card.entry{{margin:0;padding:2.3vw 1.4vw 2.1vw}}
}}
@media (prefers-reduced-motion:reduce){{
  .route-line,.route-echo,.route-wash,.directory > a.card{{animation:none!important}}
  .route-line{{stroke-dashoffset:0}}
  *{{scroll-behavior:auto!important;transition-duration:.01ms!important}}
}}
</style>
</head>
<body>
<div class="page-shell">
<main class="atlas">
<div class="plate-no" aria-hidden="true">29</div>

<svg class="route-map" viewBox="0 0 2560 1440" preserveAspectRatio="none" aria-hidden="true">
  <defs>
    <linearGradient id="routeGradient" x1="0" y1="0" x2="0.85" y2="1">
      <stop offset="0" stop-color="#6b5f4d"/>
      <stop offset="0.48" stop-color="#a08a66"/>
      <stop offset="1" stop-color="#615b4f"/>
    </linearGradient>
    <filter id="inkSoft" x="-35%" y="-20%" width="170%" height="140%">
      <feGaussianBlur stdDeviation="18"/>
    </filter>
    <filter id="inkDisplace" x="-35%" y="-20%" width="170%" height="140%">
      <feTurbulence type="fractalNoise" baseFrequency="0.012 0.075" numOctaves="4" seed="29" result="noise"/>
      <feDisplacementMap in="SourceGraphic" in2="noise" scale="32" xChannelSelector="R" yChannelSelector="B"/>
      <feGaussianBlur stdDeviation="0.8"/>
    </filter>
    <filter id="inkFray" x="-40%" y="-25%" width="180%" height="150%">
      <feTurbulence type="turbulence" baseFrequency="0.018 0.12" numOctaves="3" seed="17" result="grain"/>
      <feDisplacementMap in="SourceGraphic" in2="grain" scale="19"/>
    </filter>
  </defs>
  <path class="route-dust" d="M2135 -70 C2100 50 1870 40 1750 115 C1670 164 1630 130 1596 166 C1500 270 1380 310 1252 452 C1090 632 890 540 734 662 C600 767 505 760 391 900 C280 1035 60 950 42 1105 C26 1230 238 1160 286 1189 C335 1235 270 1360 120 1500"/>
  <path class="route-ridge" d="M2135 -70 C2100 50 1870 40 1750 115 C1670 164 1630 130 1596 166 C1500 270 1380 310 1252 452 C1090 632 890 540 734 662 C600 767 505 760 391 900 C280 1035 60 950 42 1105 C26 1230 238 1160 286 1189 C335 1235 270 1360 120 1500"/>
  <path class="route-wash" d="M2135 -70 C2100 50 1870 40 1750 115 C1670 164 1630 130 1596 166 C1500 270 1380 310 1252 452 C1090 632 890 540 734 662 C600 767 505 760 391 900 C280 1035 60 950 42 1105 C26 1230 238 1160 286 1189 C335 1235 270 1360 120 1500"/>
  <path class="route-echo" d="M2149 -69 C2114 53 1883 51 1762 125 C1680 175 1642 141 1607 178 C1510 279 1391 320 1264 463 C1101 642 902 553 747 675 C613 781 518 773 403 913 C293 1047 73 963 56 1118 C40 1244 252 1174 300 1203 C349 1249 284 1374 134 1514"/>
  <path class="route-line" d="M2135 -70 C2100 50 1870 40 1750 115 C1670 164 1630 130 1596 166 C1500 270 1380 310 1252 452 C1090 632 890 540 734 662 C600 767 505 760 391 900 C280 1035 60 950 42 1105 C26 1230 238 1160 286 1189 C335 1235 270 1360 120 1500"/>
  <path class="route-branch" d="M1596 166 L1515 166 M734 662 C820 691 902 733 990 754 M391 900 C454 953 520 1001 580 1028 M1490 944 L1490 1028 M285 1189 L300 1294 M1325 1218 L1325 1294"/>
  <g class="route-point" data-route-card="30" transform="translate(1596 166)"><circle r="12"/><circle class="point-core" r="3"/></g>
  <g class="route-point" data-route-card="31" transform="translate(990 754)"><circle r="9"/><circle class="point-core" r="2.5"/></g>
  <g class="route-point" data-route-card="32" transform="translate(580 1028)"><circle r="9"/><circle class="point-core" r="2.5"/></g>
  <g class="route-point" data-route-card="33" transform="translate(1490 1028)"><circle r="9"/><circle class="point-core" r="2.5"/></g>
  <g class="route-point" data-route-card="34" transform="translate(300 1294)"><circle r="9"/><circle class="point-core" r="2.5"/></g>
  <g class="route-point" data-route-card="35" transform="translate(1325 1294)"><circle r="9"/><circle class="point-core" r="2.5"/></g>
</svg>

<svg class="route-map route-map--continuation" viewBox="0 0 2560 1680" preserveAspectRatio="none" aria-hidden="true">
  <path class="route-dust" d="M120 -80 C470 90 220 270 430 430 C650 595 1170 410 1090 730 C1015 1035 1690 870 1590 1180 C1510 1430 1040 1370 1120 1760"/>
  <path class="route-ridge" d="M120 -80 C470 90 220 270 430 430 C650 595 1170 410 1090 730 C1015 1035 1690 870 1590 1180 C1510 1430 1040 1370 1120 1760"/>
  <path class="route-echo" d="M134 -80 C484 90 234 270 444 430 C664 595 1184 410 1104 730 C1029 1035 1704 870 1604 1180 C1524 1430 1054 1370 1134 1760"/>
  <path class="route-line" d="M120 -80 C470 90 220 270 430 430 C650 595 1170 410 1090 730 C1015 1035 1690 870 1590 1180 C1510 1430 1040 1370 1120 1760"/>
</svg>

<div class="geo-note geo-note--a" aria-label="西安坐标与证据">
  <span class="coord">__XIAN_LAT__<br>__XIAN_LON__</span>
  <span class="proof">长安 · 作地核验 __XIAN_COMPOSED__</span>
</div>
<div class="geo-note geo-note--b" aria-label="武汉坐标与证据">
  <span class="coord">__WUHAN_LAT__<br>__WUHAN_LON__</span>
  <span class="proof">江夏 · 作地核验 __WUHAN_COMPOSED__</span>
</div>
<div class="geo-note geo-note--c" aria-label="福州坐标与提及数量">
  <span class="coord">__FUZHOU_LAT__<br>__FUZHOU_LON__</span>
  <span class="proof">福州 · 正文提及 __FUZHOU_MENTIONS__</span>
</div>
<div class="geo-note geo-note--d" aria-label="广州坐标与提及数量">
  <span class="coord">__GUANGZHOU_LAT__<br>__GUANGZHOU_LON__</span>
  <span class="proof">广州 · 正文提及 __GUANGZHOU_MENTIONS__</span>
</div>

<div class="fold-rule fold-rule--31" aria-hidden="true"></div>
<div class="fold-rule fold-rule--32" aria-hidden="true"></div>
<div class="fold-rule fold-rule--34" aria-hidden="true"></div>

<header class="hero">
      <div class="kicker">唐宋诗歌数字可视化 · 作品目录</div>
  <h1>诗行万里</h1>
  <div class="tagline">给每首课本诗一个人生坐标 —— 六位唐宋诗人的生命情感与精神地形</div>
  <hr class="rule">
  <p class="hint">
    演示建议自 <span class="seal">__FIRST_EXHIBIT__ 总入口</span> 起步，依次浏览至 __LAST_EXHIBIT__ 赏析诗页，共 __N_EXHIBITS__ 个展项；
    全站纯 Python 脚本生成、本地离线运行，每个数字都可展开证据句复核。
  </p>
      <dl class="stats" aria-label="作品数据概览">
    <div class="stat"><dt>__FIRST_EXHIBIT__ — __LAST_EXHIBIT__</dt><dd>展项范围</dd></div>
    <div class="stat"><dt>__N_POEMS__</dt><dd>canonical 展示证据</dd></div>
    <div class="stat"><dt>__N_ANALYSIS__</dt><dd>首代表层作品</dd></div>
    <div class="stat"><dt>__N_JOURNEY__ ↔ 409</dt><dd>审核行旅 · 意象词典</dd></div>
  </dl>
</header>

    <section class="directory" aria-label="作品目录">
{cards}
</section>

<footer class="page-foot">
      <span>诗行万里 · 唐宋诗歌数字可视化 29 号 · 作品目录</span>
  <span>本页由脚本生成，可复跑复核：数据可视化脚本/viz_29_competition_index.py ·
  <a href="index.html">返回课程主站</a>
  </span>
</footer>
</main>
</div>
<script>
(() => {{
  const routePoints = Array.from(document.querySelectorAll('[data-route-card]'));
  const cards = document.querySelectorAll('a.card[data-card]');
  const clearRoute = () => routePoints.forEach((point) => point.classList.remove('is-active'));
  const activateRoute = (card) => {{
    clearRoute();
    const point = routePoints.find((item) => item.dataset.routeCard === card.dataset.card);
    if (point) point.classList.add('is-active');
  }};
  cards.forEach((card) => {{
    card.addEventListener('mouseenter', () => activateRoute(card));
    card.addEventListener('mouseleave', clearRoute);
    card.addEventListener('focus', () => activateRoute(card));
    card.addEventListener('blur', clearRoute);
  }});
}})();
</script>
</body>
</html>
"""

CARD_TMPL = """  <a class="card{entry}" href="{href}" data-card="{num}" style="--delay:{delay}ms">
    <div class="card-index" aria-hidden="true">{num}</div>
    <div class="card-copy">
          <div class="num">作品 · {num} 号</div>
      <h2>{title}</h2>
      <p class="hook">{hook}</p>
      <p class="desc">{desc}</p>
      <span class="go">进入展项</span>
    </div>
  </a>"""


def main():
    def read_json(*parts):
        with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
            return json.load(f)

    home = read_json("output", "assets", "competition", "home_data.json")
    gaze = read_json("output", "assets", "competition", "gaze_data.json")
    place_profile = read_json("output", "assets", "competition", "place_profile.json")
    corpus = home["corpus"]

    def fmt_count(value):
        return f"{int(value):,}"

    places = {row["key"]: row for row in place_profile["places"]}

    def place(key):
        row = places[key]
        for field in ("lat", "lon", "composed_n", "mentions_n"):
            if field not in row:
                raise KeyError(f"place_profile 缺少 {key}.{field}")
        return row

    def fmt_coord(value, hemisphere):
        return f"{abs(float(value)):.4f}° {hemisphere}"

    xian = place("西安")
    wuhan = place("武汉")
    fuzhou = place("福州")
    guangzhou = place("广州")

    tokens = {
        "__N_POEMS__": fmt_count(corpus["n_poems"]),
        "__N_ANALYSIS__": fmt_count(corpus["analysis_poems"]),
        "__N_POETS__": fmt_count(corpus["n_poets"]),
        "__N_JOURNEY__": fmt_count(corpus["n_journey_nodes"]),
        "__N_GAZE__": fmt_count(gaze["corpus"]["n_hits"]),
        "__N_EXHIBITS__": str(len(CARDS)),
        "__FIRST_EXHIBIT__": CARDS[0][0],
        "__LAST_EXHIBIT__": CARDS[-1][0],
        "__XIAN_LAT__": fmt_coord(xian["lat"], "N"),
        "__XIAN_LON__": fmt_coord(xian["lon"], "E"),
        "__XIAN_COMPOSED__": fmt_count(xian["composed_n"]),
        "__WUHAN_LAT__": fmt_coord(wuhan["lat"], "N"),
        "__WUHAN_LON__": fmt_coord(wuhan["lon"], "E"),
        "__WUHAN_COMPOSED__": fmt_count(wuhan["composed_n"]),
        "__FUZHOU_LAT__": fmt_coord(fuzhou["lat"], "N"),
        "__FUZHOU_LON__": fmt_coord(fuzhou["lon"], "E"),
        "__FUZHOU_MENTIONS__": fmt_count(fuzhou["mentions_n"]),
        "__GUANGZHOU_LAT__": fmt_coord(guangzhou["lat"], "N"),
        "__GUANGZHOU_LON__": fmt_coord(guangzhou["lon"], "E"),
        "__GUANGZHOU_MENTIONS__": fmt_count(guangzhou["mentions_n"]),
    }

    def expand(text):
        for old, new in tokens.items():
            text = text.replace(old, new)
        return text

    cards = []
    for index, (num, href, title, hook, desc, color) in enumerate(CARDS):
        cards.append(CARD_TMPL.format(
            entry=" entry" if num == "30" else "",
            color=color, href=href, num=num,
            delay=320 + index * 55,
            title=title, hook=expand(hook), desc=expand(desc),
        ))
    html = expand(HTML_TMPL).format(cards="\n".join(cards))

    os.makedirs(os.path.dirname(OUT_HTML), exist_ok=True)
    with open(OUT_HTML, "w", encoding="utf-8", newline="\n") as f:
        f.write(html)

    # 自检（与其他参赛版脚本同一口径）
    with open(OUT_HTML, encoding="utf-8") as f:
        txt = f.read()
    assert not re.search(r'<script[^>]+src\s*=\s*["\']http', txt), "禁止远程 script"
    for bad in ("NaN", "Infinity"):
        assert bad not in txt, f"页面字面出现 {bad}"
    assert 'name="viewport"' in txt, "缺 viewport"
    assert os.path.getsize(OUT_HTML) >= 5000, "体积不足 5000 字节"
    assert txt.count('<a class="card') == len(CARDS), "卡片数量与 CARDS 不一致"
    for _, href, _, _, _, _ in CARDS:
        assert os.path.exists(os.path.join(ROOT, "output", href)), f"目标页面不存在: {href}"
        assert f'href="{href}"' in txt, f"缺卡片链接: {href}"
    print("[check] exhibits=%d (%s-%s), html size=%d bytes, 无远程script, 无 NaN/Infinity 字面, viewport OK"
          % (len(CARDS), CARDS[0][0], CARDS[-1][0], os.path.getsize(OUT_HTML)))
    print("[ok] saved", OUT_HTML)


if __name__ == "__main__":
    main()
