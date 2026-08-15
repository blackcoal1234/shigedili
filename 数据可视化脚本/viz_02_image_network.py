"""可视化 2：意象共现网络 + 类别玫瑰图

- 共现网络：在同一首诗里同时出现的两个意象，边权 +1。pyecharts.Graph 力导向。
- 玫瑰图：按"自然/人文/情志"大类聚合各意象出现次数，做极坐标玫瑰。
"""
import sys
from collections import defaultdict
from itertools import combinations
from pathlib import Path

import pymysql
from pyecharts import options as opts
from pyecharts.charts import Graph, Pie, Page

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from config import MYSQL, DB_NAME, OUTPUT_DIR


def fetch_image_cooccurrence(min_pair: int = 2, top_nodes: int = 60):
    """返回 (nodes, links)。"""
    sql = """
        SELECT pi.poem_id, im.word, im.category, im.sentiment, pi.freq
          FROM t_poem_image pi
          JOIN t_image im ON im.image_id = pi.image_id
    """
    rows = []
    with pymysql.connect(**MYSQL, database=DB_NAME) as conn, conn.cursor() as cur:
        cur.execute(sql)
        rows = cur.fetchall()

    # 按 poem 聚合
    by_poem: dict[int, list] = defaultdict(list)
    word_count: dict[str, int] = defaultdict(int)
    word_meta: dict[str, tuple] = {}
    for poem_id, word, cat, sent, freq in rows:
        by_poem[poem_id].append(word)
        word_count[word] += int(freq or 1)
        word_meta[word] = (cat, float(sent))

    # 取词频 Top N，避免图过密
    top_words = set(w for w, _ in sorted(word_count.items(),
                                         key=lambda x: -x[1])[:top_nodes])

    pair_count: dict[tuple, int] = defaultdict(int)
    for words in by_poem.values():
        uniq = sorted(set(w for w in words if w in top_words))
        for a, b in combinations(uniq, 2):
            pair_count[(a, b)] += 1

    cat_color = {
        "天象": "#5dc8ff", "地理": "#7bdfa3", "草木": "#9af07a",
        "禽鸟": "#ffd05d", "走兽": "#ffaa6a", "草虫": "#ff9277",
        "鳞介": "#73d2c8", "器物": "#c19eff", "建筑": "#ee82ee",
        "情志": "#ff6b8b",
    }
    nodes = []
    for w in top_words:
        cat, sent = word_meta[w]
        size = 14 + (word_count[w] ** 0.5) * 4
        nodes.append({
            "name": w,
            "symbolSize": size,
            "category": cat,
            "value": word_count[w],
            "itemStyle": {"color": cat_color.get(cat, "#cccccc")},
        })
    categories = [{"name": c} for c in sorted(set(word_meta[w][0] for w in top_words))]

    links = [{"source": a, "target": b, "value": v}
             for (a, b), v in pair_count.items() if v >= min_pair]
    return nodes, links, categories


def render():
    nodes, links, cats = fetch_image_cooccurrence(min_pair=2, top_nodes=60)

    graph = (
        Graph(init_opts=opts.InitOpts(width="1100px", height="700px",
                                      bg_color="#101430"))
        .add(
            "意象共现",
            nodes=nodes,
            links=links,
            categories=cats,
            layout="force",
            is_roam=True,
            is_focusnode=True,
            repulsion=1200,
            gravity=0.05,
            edge_length=[40, 200],
            linestyle_opts=opts.LineStyleOpts(color="#5a6298", curve=0.18,
                                              opacity=0.5),
            label_opts=opts.LabelOpts(is_show=True, color="#fff", font_size=11),
        )
        .set_global_opts(
            title_opts=opts.TitleOpts(
                title="意象共现网络",
                subtitle="同一首诗内共现关系  |  节点大小 ~ 出现频次  |  颜色 = 意象类别",
                title_textstyle_opts=opts.TextStyleOpts(color="#fff", font_size=20),
                subtitle_textstyle_opts=opts.TextStyleOpts(color="#a0a0c0"),
                pos_left="center",
            ),
            legend_opts=opts.LegendOpts(textstyle_opts=opts.TextStyleOpts(color="#ddd"),
                                        pos_top="8%"),
            tooltip_opts=opts.TooltipOpts(formatter="{b}"),
        )
    )

    # 玫瑰图：按类别汇总
    sql = """
        SELECT category, SUM(pi.freq) AS f
          FROM t_image im
          JOIN t_poem_image pi ON pi.image_id = im.image_id
         GROUP BY category
         ORDER BY f DESC
    """
    cat_data = []
    with pymysql.connect(**MYSQL, database=DB_NAME) as conn, conn.cursor() as cur:
        cur.execute(sql)
        for cat, f in cur.fetchall():
            cat_data.append((cat, int(f or 0)))

    pie = (
        Pie(init_opts=opts.InitOpts(width="900px", height="600px"))
        .add(
            "类别频次",
            cat_data,
            radius=["20%", "78%"],
            rosetype="area",
            label_opts=opts.LabelOpts(formatter="{b}\n{c} 次", font_size=12),
        )
        .set_global_opts(
            title_opts=opts.TitleOpts(title="意象类别玫瑰图",
                                      subtitle="按出现频次比较自然 / 人文 / 情志三大类",
                                      pos_left="center"),
            legend_opts=opts.LegendOpts(orient="vertical", pos_left="left"),
        )
    )

    page = Page(layout=Page.SimplePageLayout, page_title="意象关系")
    page.add(graph, pie)
    out = OUTPUT_DIR / "02_意象共现.html"
    page.render(str(out))
    
    html = out.read_text(encoding="utf-8")
    html = html.replace('<body>', '<body>\n<a href="index.html" style="position:absolute;left:20px;top:20px;text-decoration:none;color:#475569;font-weight:bold;background:#fff;padding:8px 16px;border-radius:8px;box-shadow:0 2px 4px rgba(0,0,0,0.1);z-index:999;">← 返回大屏</a>')
    out.write_text(html, encoding="utf-8")
    print(f"  [ok] saved {out}  ({len(nodes)} 个意象节点 / {len(links)} 条共现边)")


if __name__ == "__main__":
    render()
