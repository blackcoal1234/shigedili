# -*- coding: utf-8 -*-
"""viz_29 参赛导航 —— 数媒比赛参赛版作品目录（演示起始页）

产出：
  output/29_参赛导航.html

定位：
  一张简洁的作品目录卡片页，10 个参赛页面各一张卡（标题 / 一句话看点 /
  缩略说明），纸面文人风，作为现场演示的起始页。不做数据计算，只做导航；
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
     "给每首课本诗一个人生坐标——一页读懂全部数据资产与十个展项。",
     "__N_POEMS__ 首语料、__N_JOURNEY__ 个审核行旅节点、409 词运行时意象词典的总览页（38号历史对比另保留160词口径）：数据从哪里来、证据怎样分级、每个展项回答什么问题。",
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
     "__N_POETS__ 位诗人 __N_POEMS__ 首中的孤独语境光谱，与数字夸张的诗人签名对比；榜首与排名随数据重算。",
     "#8a3b2f"),
    ("36", "36_同龄对齐.html", "同龄对齐",
     "同样的虚岁，六位诗人各自正在写什么。",
     "把六位诗人拉回同一条年龄轴：27 类多标签情绪、VAD 三维与文学形容词并列展示；候选系年逐首带徽章与证据句。",
     "#a87527"),
    ("37", "37_可听的诗.html", "可听的诗",
     "给 __N_POEMS__ 首诗文做一次「录音」：猿声、钟声、砧声的声音维度。",
     "只统计诗里明写的声音意象，构成六位诗人各自的「声景」；词典与统计口径见页内「方法与数据」。",
     "#9c5d8f"),
    ("38", "38_唐宋意象潮汐.html", "意象潮汐",
     "同一套客观意象词典扫过唐宋正文，看两朝意象如何涨落。",
     "以每万正文汉字率比较唐宋客观意象，再让审核节点中的关联作品按五章显影；历史锚点只供对读，相关不等于因果。",
     "#456f8a"),
    ("39", "39_诗人自述生命卷.html", "诗人自述生命卷",
     "从出生走向死亡：88 位诗人分四轮进入第一视角生命叙事。",
     "首轮完成 22 位诗人的证据约束重构，以诗篇、史料与 VAD 情感曲线对读；其余 66 位保留轮次与资料就绪状态。",
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
]

HTML_TMPL = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>29 · 参赛导航 —— 诗行万里 · 数媒可视化参赛版作品目录</title>
<link rel="icon" href="data:,">
<style>
:root{{
  --paper:#f2f4f0; --surface:#ffffff; --ink:#252b27; --muted:#5a615c;
  --cinnabar:#b64b3f; --jade:#26786e; --gold:#a87527; --blue:#426f94;
  --line:#d8ddd6; --radius:6px; --shadow:0 1px 3px rgba(37,43,39,.08);
}}
*{{box-sizing:border-box}}
html,body{{margin:0;padding:0}}
body{{
  font-family:"Microsoft YaHei","PingFang SC",sans-serif;color:var(--ink);
  background:
    linear-gradient(rgba(49,57,51,.025) 1px,transparent 1px),
    linear-gradient(90deg,rgba(49,57,51,.025) 1px,transparent 1px),var(--paper);
  background-size:28px 28px;
  font-size:14px;line-height:1.7;
}}
a{{color:var(--jade)}}
.wrap{{max-width:1180px;margin:0 auto;padding:36px 24px 40px}}
header.hero{{text-align:center;margin-bottom:8px}}
header.hero .kicker{{font-size:13px;letter-spacing:4px;color:var(--muted)}}
header.hero h1{{
  font-family:"STKaiti","KaiTi",serif;font-size:40px;margin:8px 0 6px;
  letter-spacing:6px;font-weight:700
}}
header.hero .tagline{{font-size:15px;color:var(--muted)}}
header.hero .rule{{
  width:120px;height:2px;background:var(--cinnabar);margin:18px auto 0;border:0
}}
.hint{{
  max-width:760px;margin:18px auto 26px;text-align:center;font-size:13px;
  color:var(--muted)
}}
.hint .seal{{color:var(--cinnabar)}}
.grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px}}
a.card{{
  display:block;background:var(--surface);border:1px solid var(--line);
  border-top:3px solid var(--pc,var(--ink));border-radius:var(--radius);
  box-shadow:var(--shadow);padding:18px 20px 16px;color:inherit;
  text-decoration:none;transition:transform .15s ease,box-shadow .15s ease
}}
a.card:hover{{transform:translateY(-2px);box-shadow:0 4px 12px rgba(37,43,39,.14)}}
.card .num{{
  font-family:"STKaiti","KaiTi",serif;font-size:13px;color:var(--pc,var(--ink));
  letter-spacing:2px
}}
.card h2{{
  font-family:"STKaiti","KaiTi",serif;font-size:24px;margin:2px 0 8px;
  letter-spacing:2px;font-weight:700
}}
.card .hook{{font-size:14px;margin:0 0 8px;color:var(--ink)}}
.card .desc{{font-size:12.5px;margin:0;color:var(--muted)}}
.card .go{{
  display:inline-block;margin-top:10px;font-size:12.5px;color:var(--pc,var(--jade))
}}
.card.entry{{background:linear-gradient(rgba(37,43,39,.03),rgba(37,43,39,.0)),var(--surface)}}
footer.page-foot{{
  margin-top:30px;border-top:1px solid var(--line);padding-top:14px;
  color:var(--muted);font-size:12px;text-align:center
}}
footer.page-foot a{{color:var(--muted)}}
@media (max-width:860px){{
  .grid{{grid-template-columns:1fr}}
  header.hero h1{{font-size:30px;letter-spacing:4px}}
  .wrap{{padding:26px 14px 30px}}
}}
</style>
</head>
<body>
<div class="wrap">

<header class="hero">
  <div class="kicker">数媒可视化参赛版 · 作品目录</div>
  <h1>诗行万里</h1>
  <div class="tagline">给每首课本诗一个人生坐标 —— 六位唐宋诗人的生命情感与精神地形</div>
  <hr class="rule">
</header>

<p class="hint">
  演示建议自 <span class="seal">30 总入口</span> 起步，依次经过 31–39 展项；
  全站纯 Python 脚本生成、本地离线运行，每个数字都可展开证据句复核。
</p>

<div class="grid">
{cards}
</div>

<footer class="page-foot">
  诗行万里 · 数媒可视化参赛系列 29 号 · 参赛导航 ——
  本页由脚本生成，可复跑复核：数据可视化脚本/viz_29_competition_index.py ·
  <a href="index.html">返回课程主站</a>
</footer>
</div>
</body>
</html>
"""

CARD_TMPL = """  <a class="card{entry}" style="--pc:{color}" href="{href}">
    <div class="num">参赛版 · {num} 号</div>
    <h2>{title}</h2>
    <p class="hook">{hook}</p>
    <p class="desc">{desc}</p>
    <span class="go">进入展项 →</span>
  </a>"""


def main():
    def read_json(*parts):
        with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
            return json.load(f)

    home = read_json("output", "assets", "competition", "home_data.json")
    gaze = read_json("output", "assets", "competition", "gaze_data.json")
    corpus = home["corpus"]
    tokens = {
        "__N_POEMS__": str(corpus["n_poems"]),
        "__N_POETS__": str(corpus["n_poets"]),
        "__N_JOURNEY__": str(corpus["n_journey_nodes"]),
        "__N_GAZE__": str(gaze["corpus"]["n_hits"]),
    }

    def expand(text):
        for old, new in tokens.items():
            text = text.replace(old, new)
        return text

    cards = []
    for num, href, title, hook, desc, color in CARDS:
        cards.append(CARD_TMPL.format(
            entry=" entry" if num == "30" else "",
            color=color, href=href, num=num,
            title=title, hook=expand(hook), desc=expand(desc),
        ))
    html = HTML_TMPL.format(cards="\n".join(cards))

    os.makedirs(os.path.dirname(OUT_HTML), exist_ok=True)
    with open(OUT_HTML, "w", encoding="utf-8") as f:
        f.write(html)

    # 自检（与其他参赛版脚本同一口径）
    with open(OUT_HTML, encoding="utf-8") as f:
        txt = f.read()
    assert not re.search(r'<script[^>]+src\s*=\s*["\']http', txt), "禁止远程 script"
    for bad in ("NaN", "Infinity"):
        assert bad not in txt, f"页面字面出现 {bad}"
    assert 'name="viewport"' in txt, "缺 viewport"
    assert os.path.getsize(OUT_HTML) >= 5000, "体积不足 5000 字节"
    for _, href, _, _, _, _ in CARDS:
        assert os.path.exists(os.path.join(ROOT, "output", href)), f"目标页面不存在: {href}"
        assert f'href="{href}"' in txt, f"缺卡片链接: {href}"
    print("[check] html size=%d bytes, 无远程script, 无 NaN/Infinity 字面, viewport OK"
          % os.path.getsize(OUT_HTML))
    print("[ok] saved", OUT_HTML)


if __name__ == "__main__":
    main()
