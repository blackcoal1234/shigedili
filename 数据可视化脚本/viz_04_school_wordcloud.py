"""可视化 4：流派词云对比

按"豪放派 / 婉约派 / 山水田园 / 边塞派"四派各画一张词云，每派词云独立 PNG，
最后再拼成一张大图供报告使用。

词云采用 jieba 切词 + 自定义意象/常用语停用词过滤，颜色从冷到暖根据流派氛围
预设：豪放=赤、婉约=紫、山水=青、边塞=黄沙。
"""
import sys
from collections import Counter
from pathlib import Path

import jieba
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pymysql
from wordcloud import WordCloud

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from config import MYSQL, DB_NAME, OUTPUT_DIR

FONT = r"C:\Windows\Fonts\simhei.ttf"
plt.rcParams["font.family"] = "SimHei"
plt.rcParams["axes.unicode_minus"] = False

STOPWORDS = set("的了是不也无在与而以为之乎者其于则以及於矣兮哉")
STOPWORDS |= set("一二三四五六七八九十百千万")
STOPWORDS |= set("我你他她它人自有何不未已且更亦又即乃便皆共相每各只些可使将欲同所其")
STOPWORDS |= {"君子"}

SCHOOL_GROUPS = {
    "豪放派": None,
    "婉约派": None,
    "山水田园": None,
    "边塞派": None,
}  # None = 从数据库自动取该流派下所有诗人

PALETTE = {
    "豪放派": "Reds",
    "婉约派": "Purples",
    "山水田园": "Greens",
    "边塞派": "YlOrBr",
}


def fetch_corpus(poets: list[str]) -> str:
    if not poets:
        return ""
    sql = """
        SELECT pm.title, pm.body
          FROM t_poem pm
          JOIN t_poet pt ON pt.poet_id = pm.poet_id
         WHERE pt.name IN ({})
    """.format(",".join(["%s"] * len(poets)))
    text = []
    with pymysql.connect(**MYSQL, database=DB_NAME) as conn, conn.cursor() as cur:
        cur.execute(sql, poets)
        for title, body in cur.fetchall():
            text.append(title)
            text.append(body)
    return "\n".join(text)


def fetch_school_poets(school: str) -> list[str]:
    sql = "SELECT name FROM t_poet WHERE school=%s AND poem_count > 0"
    with pymysql.connect(**MYSQL, database=DB_NAME) as conn, conn.cursor() as cur:
        cur.execute(sql, (school,))
        return [r[0] for r in cur.fetchall()]


def tokenize(text: str) -> Counter:
    words = jieba.lcut(text) if hasattr(jieba, "lcut") else list(jieba.cut(text))
    counter: Counter = Counter()
    for w in words:
        w = w.strip()
        if not w or len(w) < 2:
            # 单字保留诗中常见高信息字（月、酒、雁、风…），其余丢弃
            if len(w) == 1 and w in {"月", "酒", "雁", "风", "雨", "山", "云", "舟",
                                      "梅", "柳", "雪", "孤", "愁", "泪", "醉", "梦",
                                      "花", "鸟", "春", "秋"}:
                counter[w] += 1
            continue
        if w in STOPWORDS:
            continue
        if any(ch in "，。！？；：、""''（）《》〈〉「」『』" for ch in w):
            continue
        counter[w] += 1
    return counter


def render_one(school: str, poets: list[str]) -> Path | None:
    text = fetch_corpus(poets)
    if not text.strip():
        print(f"  [skip] {school} 无数据")
        return None
    counts = tokenize(text)
    if not counts:
        return None
    wc = WordCloud(
        font_path=FONT,
        background_color="white",
        width=900, height=600,
        max_words=120,
        colormap=PALETTE.get(school, "viridis"),
        prefer_horizontal=0.9,
    ).generate_from_frequencies(counts)
    out = OUTPUT_DIR / f"04_词云_{school}.png"
    wc.to_file(str(out))
    return out


def render():
    paths = {}
    for school in SCHOOL_GROUPS:
        poets = fetch_school_poets(school)
        if not poets:
            print(f"  [skip] {school} 数据库中无诗人")
            continue
        p = render_one(school, poets)
        if p:
            paths[school] = p

    if not paths:
        print("  无可绘制流派词云。")
        return

    # 拼接 2x2 大图
    fig, axes = plt.subplots(2, 2, figsize=(16, 11))
    for ax, (school, p) in zip(axes.ravel(), paths.items()):
        img = plt.imread(p)
        ax.imshow(img)
        ax.set_title(school, fontsize=18, fontweight="bold")
        ax.axis("off")
    # 多余子图清空
    for ax in axes.ravel()[len(paths):]:
        ax.axis("off")
    fig.suptitle("唐宋四派词云对比", fontsize=22, fontweight="bold")
    out = OUTPUT_DIR / "04_流派词云.png"
    plt.tight_layout()
    plt.savefig(out, dpi=120, bbox_inches="tight", facecolor="white")
    plt.close()
    print(f"  [ok] saved {out}  ({len(paths)} 派)")


if __name__ == "__main__":
    render()
