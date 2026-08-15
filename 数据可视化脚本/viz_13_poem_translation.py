"""可视化 13：诗词白话翻译浏览器。

功能：
1. 从数据库读取已入库古诗词；数据库不可用时自动回退到 data/poems.json。
2. 为每首诗生成离线白话辅助译文，保证页面不联网也能展示“原文 + 译文”。
3. 页面左侧检索/筛选诗作，点击一首诗后，右侧并排展示原文和白话译文。
4. 可选接入 DeepSeek：用户在浏览器本地输入 Key，点击“AI 精译当前诗”后生成更自然的白话译文，并缓存在 localStorage。

输出：
    output/13_诗词白话翻译.html

运行：
    python .\数据可视化脚本\viz_13_poem_translation.py
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import pymysql

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config import DB_NAME, MYSQL, OUTPUT_DIR
from data.image_dict import lookup as lookup_image, words as image_words
from data.season_rules import detect_season
from viz_assets import inject_index_backlink


POEMS_JSON = ROOT / "data" / "poems.json"
OUT_HTML = OUTPUT_DIR / "13_诗词白话翻译.html"

# 这些词表用于离线生成“白话辅助译文”。它不是学术级注释，作用是让页面在无网络、无 API Key
# 的情况下也能完成交互展示。需要更自然的译文时，可在页面里用 DeepSeek 对单首诗精译。
PHRASE_TRANSLATIONS: tuple[tuple[str, str], ...] = (
    ("床前明月光", "床前洒着明亮的月光"),
    ("疑是地上霜", "我疑心那是地上结起的白霜"),
    ("举头望明月", "抬起头望着天上的明月"),
    ("低头思故乡", "低下头又想起遥远的故乡"),
    ("白日依山尽", "夕阳傍着群山慢慢沉落"),
    ("黄河入海流", "黄河奔腾着流向大海"),
    ("欲穷千里目", "想要看尽更远的景色"),
    ("更上一层楼", "就要再登上一层高楼"),
    ("春眠不觉晓", "春夜酣睡，不知不觉天已破晓"),
    ("处处闻啼鸟", "到处都能听见鸟儿啼鸣"),
    ("夜来风雨声", "昨夜传来风雨的声音"),
    ("花落知多少", "不知有多少花被吹落"),
    ("锄禾日当午", "农人在正午烈日下锄禾"),
    ("汗滴禾下土", "汗水一滴滴落进禾苗下的泥土"),
    ("谁知盘中餐", "谁知道盘中的饭食"),
    ("粒粒皆辛苦", "每一粒都饱含辛苦"),
    ("千山鸟飞绝", "群山中鸟儿都已飞尽"),
    ("万径人踪灭", "千万条小路上也看不到人的踪迹"),
    ("孤舟蓑笠翁", "一叶孤舟上坐着披蓑戴笠的老人"),
    ("独钓寒江雪", "独自在寒冷江面上垂钓风雪"),
    ("爆竹声中一岁除", "爆竹声响中旧的一年过去了"),
    ("春风送暖入屠苏", "春风送来暖意，人们饮着屠苏酒"),
    ("千门万户曈曈日", "千家万户迎来明亮的新日"),
    ("总把新桃换旧符", "总要用新的桃符换下旧的桃符"),
    ("不识庐山真面目", "看不清庐山真实的全貌"),
    ("只缘身在此山中", "只因为自己正身处这座山中"),
    ("大江东去", "大江向东奔流而去"),
    ("浪淘尽", "波浪淘洗尽了"),
    ("千古风流人物", "千百年来的英雄豪杰"),
    ("故垒西边", "旧日营垒的西边"),
    ("人道是", "人们说那是"),
    ("三国周郎赤壁", "三国时周瑜鏖战的赤壁"),
    ("乱石穿空", "嶙峋乱石直插天空"),
    ("惊涛拍岸", "汹涌波涛拍打江岸"),
    ("卷起千堆雪", "卷起如千堆白雪般的浪花"),
    ("江山如画", "江山壮丽得像画一样"),
    ("一时多少豪杰", "那一时代涌现了多少英雄豪杰"),
    ("明月几时有", "明月是什么时候出现的呢"),
    ("把酒问青天", "我举杯向青天发问"),
    ("不知天上宫阙", "不知道天上的宫殿"),
    ("今夕是何年", "今夜是哪一年"),
    ("但愿人长久", "只愿亲人朋友都能长久平安"),
    ("千里共婵娟", "即使相隔千里，也能共赏这轮明月"),
    ("无可奈何花落去", "对花儿凋落感到无可奈何"),
    ("似曾相识燕归来", "似曾相识的燕子又飞回来了"),
    ("小园香径独徘徊", "我独自在小园香径上徘徊"),
    ("山重水复疑无路", "山水重重，好像已经无路可走"),
    ("柳暗花明又一村", "柳色幽深、花光明丽处又出现一个村庄"),
    ("会当凌绝顶", "终将登上最高峰"),
    ("一览众山小", "俯视群山，觉得众山都显得渺小"),
    ("人生得意须尽欢", "人生得意时应当尽情欢乐"),
    ("莫使金樽空对月", "不要让酒杯空空地对着明月"),
    ("天生我材必有用", "上天生下我，必然有我的用处"),
    ("千金散尽还复来", "千金用尽了也还会再来"),
    ("劝君更尽一杯酒", "劝你再喝尽这一杯酒"),
    ("西出阳关无故人", "向西出了阳关，就难再遇到老朋友"),
    ("海内存知己", "四海之内只要有知心朋友"),
    ("天涯若比邻", "即使远在天涯也像近邻一样"),
    ("露从今夜白", "从今夜起白露渐浓"),
    ("月是故乡明", "月亮还是故乡的最明亮"),
    ("烽火连三月", "战火已经连续燃烧了好几个月"),
    ("家书抵万金", "一封家书抵得上万两黄金"),
    ("感时花溅泪", "感伤时局，见花也像落泪"),
    ("恨别鸟惊心", "怨恨离别，听鸟声也惊动内心"),
    ("国破山河在", "国家沦陷而山河依旧存在"),
    ("城春草木深", "春天的城中草木荒深"),
    ("日照香炉生紫烟", "阳光照着香炉峰，升起紫色烟霞"),
    ("遥看瀑布挂前川", "远远望去，瀑布像挂在山前的河流"),
    ("飞流直下三千尺", "水流飞泻而下，好像有三千尺"),
    ("疑是银河落九天", "仿佛银河从高高的天上落下来"),
    ("孤帆远影碧空尽", "孤帆的远影消失在碧蓝天空尽头"),
    ("唯见长江天际流", "只看见长江向天边流去"),
    ("两个黄鹂鸣翠柳", "两只黄鹂在翠绿柳枝间鸣叫"),
    ("一行白鹭上青天", "一行白鹭飞上青天"),
    ("窗含西岭千秋雪", "窗口映着西岭千年不化的积雪"),
    ("门泊东吴万里船", "门前停泊着从东吴远道而来的船"),
)

WORD_TRANSLATIONS: tuple[tuple[str, str], ...] = (
    ("吾", "我"), ("余", "我"), ("予", "我"), ("尔", "你"), ("汝", "你"),
    ("君", "你/您"), ("卿", "你"), ("妾", "我"), ("此", "这"), ("斯", "这"),
    ("兹", "这"), ("彼", "那"), ("谁", "谁"), ("何", "什么/为何"), ("安", "哪里/怎么"),
    ("焉", "哪里/于是"), ("胡", "为什么"), ("孰", "谁/哪一个"), ("几", "多少"),
    ("欲", "想要"), ("将", "将要"), ("当", "应当/正当"), ("须", "应当"),
    ("可", "可以"), ("堪", "能够/忍受"), ("忍", "忍心/忍受"), ("愿", "希望"),
    ("莫", "不要/没有"), ("勿", "不要"), ("未", "还没有"), ("不", "不"),
    ("无", "没有"), ("非", "不是"), ("乃", "于是/就是"), ("即", "就是/便"),
    ("便", "就"), ("遂", "于是"), ("复", "又"), ("还", "又/返回"), ("更", "更加/再"),
    ("犹", "仍然/好像"), ("尚", "还"), ("且", "暂且/并且"), ("亦", "也"),
    ("皆", "都"), ("尽", "全都/完尽"), ("俱", "都"), ("但", "只/只是"),
    ("唯", "只"), ("惟", "只/只是"), ("独", "独自"), ("空", "白白地/空旷"),
    ("徒", "白白地"), ("漫", "随意/徒然"), ("应", "应该/想必"), ("料", "料想"),
    ("拟", "打算/好像"), ("向", "向着/从前"), ("却", "却/再"), ("寻", "寻找"),
    ("看", "看见"), ("闻", "听见"), ("听", "听见"), ("见", "看见"), ("望", "远望"),
    ("忆", "回忆/想念"), ("思", "思念/思考"), ("念", "思念"), ("怜", "怜惜"),
    ("恨", "遗憾/怨恨"), ("愁", "忧愁"), ("悲", "悲伤"), ("喜", "欢喜"),
    ("行", "行走"), ("归", "归去/返回"), ("去", "离开/前往"), ("来", "到来"),
    ("至", "到达"), ("入", "进入"), ("出", "走出"), ("上", "登上"), ("下", "落下/下来"),
    ("临", "靠近/面对"), ("对", "面对"), ("倚", "倚靠"), ("凭", "倚着"),
    ("坐", "坐着/因为"), ("卧", "躺卧"), ("眠", "睡眠"), ("醒", "醒来"),
    ("晓", "清晨/知晓"), ("暮", "傍晚"), ("夕", "傍晚"), ("夜", "夜晚"),
    ("朝", "早晨"), ("旦", "早晨"), ("明", "明亮/明天"), ("暗", "昏暗"),
    ("寒", "寒冷"), ("冷", "寒冷"), ("暖", "温暖"), ("凉", "清凉"),
    ("春", "春天"), ("夏", "夏天"), ("秋", "秋天"), ("冬", "冬天"),
    ("风", "风"), ("雨", "雨"), ("雪", "雪"), ("霜", "霜"), ("露", "露水"),
    ("云", "云"), ("月", "月亮"), ("日", "太阳/日子"), ("烟", "烟雾/水汽"),
    ("霞", "霞光"), ("天", "天空"), ("山", "山"), ("水", "水/江河"), ("江", "江水"),
    ("河", "河水"), ("湖", "湖水"), ("海", "大海"), ("溪", "溪水"), ("泉", "泉水"),
    ("岸", "岸边"), ("洲", "水中陆地"), ("渚", "水中小洲"), ("沙", "沙洲/沙地"),
    ("城", "城池"), ("楼", "楼台"), ("阁", "楼阁"), ("亭", "亭子"), ("台", "高台"),
    ("桥", "桥"), ("门", "门"), ("窗", "窗户"), ("舟", "小船"), ("船", "船"),
    ("帆", "船帆"), ("马", "马"), ("雁", "大雁"), ("燕", "燕子"), ("鸟", "鸟儿"),
    ("莺", "黄莺"), ("鹤", "白鹤"), ("猿", "猿猴"), ("蝉", "蝉"), ("蝶", "蝴蝶"),
    ("花", "花"), ("柳", "柳树"), ("桃", "桃花/桃树"), ("李", "李花/李树"),
    ("梅", "梅花"), ("菊", "菊花"), ("竹", "竹子"), ("松", "松树"), ("草", "青草"),
    ("叶", "树叶"), ("枝", "枝条"), ("香", "香气"), ("酒", "酒"), ("杯", "酒杯/杯子"),
    ("书", "书信/书卷"), ("琴", "琴"), ("剑", "剑"), ("灯", "灯火"), ("梦", "梦"),
    ("故乡", "家乡"), ("故人", "老朋友"), ("客", "旅人/客居的人"), ("游子", "远行的人"),
    ("征人", "远征的人"), ("边塞", "边疆"), ("关山", "关隘和群山"), ("长安", "长安"),
    ("天涯", "遥远的地方"), ("人间", "人世间"), ("红尘", "世俗人间"),
    ("青山", "青翠的山"), ("白云", "白云"), ("明月", "明亮的月亮"), ("清风", "清凉的风"),
    ("流水", "流动的水"), ("落花", "凋落的花"), ("残阳", "将落的夕阳"), ("斜阳", "斜照的夕阳"),
    ("孤云", "孤独的云"), ("孤舟", "孤零零的小船"), ("归雁", "归来的大雁"),
    ("落日", "落下的太阳"), ("西风", "秋风/西来的风"), ("东风", "春风/东来的风"),
    ("黄昏", "傍晚"), ("阑干", "栏杆"), ("凭栏", "倚着栏杆"), ("离愁", "离别的忧愁"),
)

CLASSICAL_PARTICLES = "之乎者也矣兮焉哉耳尔欤耶"
LINE_SPLIT_RE = re.compile(r"(?<=[。！？；])\s*|\n+")
CHINESE_RE = re.compile(r"[\u4e00-\u9fff]")


@dataclass(frozen=True)
class PoemTranslationRecord:
    source_id: int | str
    title: str
    poet: str
    dynasty: str
    school: str
    season: str
    sentiment: float
    body_len: int
    body: str
    translation: str
    source: str

    def to_json(self, index: int) -> dict[str, object]:
        return {
            "id": index,
            "source_id": self.source_id,
            "title": self.title,
            "poet": self.poet,
            "dynasty": self.dynasty,
            "school": self.school,
            "season": self.season,
            "sentiment": round(self.sentiment, 3),
            "body_len": self.body_len,
            "body": self.body,
            "translation": self.translation,
            "source": self.source,
        }


def conn():
    return pymysql.connect(
        **MYSQL,
        database=DB_NAME,
        connect_timeout=5,
        read_timeout=20,
        write_timeout=20,
        cursorclass=pymysql.cursors.DictCursor,
    )


def as_float(value: object) -> float:
    if value is None:
        return 0.0
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


def normalize_text(value: object) -> str:
    text = str(value or "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t\u3000]+", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def split_poem_lines(text: str) -> list[str]:
    text = normalize_text(text)
    if not text:
        return []
    rough = LINE_SPLIT_RE.split(text)
    lines = [line.strip() for line in rough if line and line.strip()]
    if len(lines) <= 1:
        # 逗号通常承接同一句诗，尽量按逗号继续拆，便于“原文/译文”对齐展示。
        lines = [line.strip() for line in re.split(r"(?<=[，、])", text) if line.strip()]
    return lines or [text]


def strip_line_punctuation(line: str) -> tuple[str, str]:
    line = line.strip()
    if not line:
        return "", ""
    punct = ""
    if line[-1] in "，。！？；、：":
        punct = line[-1]
        line = line[:-1]
    return line.strip(), punct


def apply_replacements(text: str) -> str:
    converted = text
    for src, dst in sorted(PHRASE_TRANSLATIONS + WORD_TRANSLATIONS, key=lambda item: len(item[0]), reverse=True):
        if src and src in converted:
            converted = converted.replace(src, dst)
    converted = converted.translate({ord(ch): None for ch in CLASSICAL_PARTICLES})
    converted = re.sub(r"/[^，。；！？、\s]+", "", converted)
    converted = re.sub(r"\s+", "", converted)
    converted = converted.replace("你您", "您").replace("我我", "我")
    return converted.strip()


def make_plain_line(line: str) -> str:
    clean, punct = strip_line_punctuation(line)
    if not clean:
        return ""

    converted = apply_replacements(clean)
    if not converted:
        converted = clean

    # 少量模板化润色，让无法完全替换的诗句也能形成白话句式。
    if converted == clean:
        if len(clean) <= 4:
            converted = f"这里写到{clean}"
        elif any(ch in clean for ch in "风雨雪霜云月山水江河湖海花柳草树鸟雁舟帆城楼"):
            converted = f"诗人写下{clean}这一景象"
        elif any(ch in clean for ch in "愁悲恨思忆怜喜"):
            converted = f"诗人借{clean}表达内心情绪"
        else:
            converted = f"大意是：{clean}"

    if punct in "，、":
        return converted + "，"
    if punct in "。！？；":
        return converted + "。"
    return converted + "。"


def make_plain_translation(title: str, body: str) -> str:
    lines = split_poem_lines(body)
    translated = [make_plain_line(line) for line in lines]
    translated = [line for line in translated if line]
    if not translated:
        return "暂无可翻译文本。"
    return "\n".join(translated)


def greedy_image_counts(text: str, tokens: list[str]) -> Counter[str]:
    counts: Counter[str] = Counter()
    work = text or ""
    for token in tokens:
        count = work.count(token)
        if count:
            counts[token] += count
            work = work.replace(token, "·" * len(token))
    return counts


def estimate_sentiment(image_counts: Counter[str]) -> float:
    total_weight = sum(image_counts.values())
    if not total_weight:
        return 0.0
    total = 0.0
    for word, count in image_counts.items():
        meta = lookup_image(word)
        if meta:
            total += float(meta["sentiment"]) * count
    return total / total_weight


def load_from_database() -> list[PoemTranslationRecord]:
    with conn() as c, c.cursor() as cur:
        cur.execute(
            """
            SELECT pm.poem_id,
                   pm.title,
                   pt.name AS poet,
                   pt.dynasty,
                   COALESCE(pt.school, '') AS school,
                   COALESCE(NULLIF(pm.season, ''), '未标') AS season,
                   pm.sentiment,
                   pm.body_len,
                   pm.body
              FROM t_poem pm
              JOIN t_poet pt ON pt.poet_id = pm.poet_id
             ORDER BY pt.dynasty, pt.name, pm.title
            """
        )
        rows = cur.fetchall()

    poems: list[PoemTranslationRecord] = []
    for row in rows:
        title = normalize_text(row.get("title"))
        body = normalize_text(row.get("body"))
        poems.append(
            PoemTranslationRecord(
                source_id=int(row.get("poem_id") or 0),
                title=title,
                poet=normalize_text(row.get("poet")),
                dynasty=normalize_text(row.get("dynasty")),
                school=normalize_text(row.get("school")),
                season=normalize_text(row.get("season")) or "未标",
                sentiment=as_float(row.get("sentiment")),
                body_len=int(row.get("body_len") or len(body)),
                body=body,
                translation=make_plain_translation(title, body),
                source="database",
            )
        )
    return poems


def load_from_poems_json(reason: Exception | None = None) -> list[PoemTranslationRecord]:
    if reason is not None:
        print(f"  [warn] 数据库读取失败，改用 poems.json 离线兜底：{reason}")

    records = json.loads(POEMS_JSON.read_text(encoding="utf-8"))
    images = image_words()
    poems: list[PoemTranslationRecord] = []

    for index, row in enumerate(records):
        title = normalize_text(row.get("title"))
        body = normalize_text(row.get("body"))
        image_counts = greedy_image_counts(body, images)
        poems.append(
            PoemTranslationRecord(
                source_id=row.get("poem_id") or index,
                title=title,
                poet=normalize_text(row.get("poet") or row.get("author")),
                dynasty=normalize_text(row.get("dynasty")),
                school=normalize_text(row.get("school")),
                season=detect_season(title, body) or "未标",
                sentiment=estimate_sentiment(image_counts),
                body_len=len(body),
                body=body,
                translation=make_plain_translation(title, body),
                source="poems.json",
            )
        )

    return sorted(poems, key=lambda item: (item.dynasty, item.poet, item.title))


def load_poems() -> list[PoemTranslationRecord]:
    try:
        return load_from_database()
    except Exception as exc:
        return load_from_poems_json(exc)


def option_count(values: list[str]) -> int:
    return len({value for value in values if value})


def render() -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    poems = load_poems()
    dataset = [poem.to_json(index) for index, poem in enumerate(poems)]
    payload = json.dumps(dataset, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    poet_count = option_count([poem.poet for poem in poems])
    dynasty_count = option_count([poem.dynasty for poem in poems])
    school_count = option_count([poem.school for poem in poems])
    season_count = option_count([poem.season for poem in poems])

    html = rf"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>诗行万里 · 诗词白话翻译</title>
    <style>
    :root {{
        --bg: #f5f1e8;
        --panel: #fffaf1;
        --panel-strong: #fff7e6;
        --ink: #1f2933;
        --muted: #6b7280;
        --soft: #8b7355;
        --line: #eadcc2;
        --accent: #b45309;
        --accent-2: #0f766e;
        --accent-soft: #fff1d6;
        --ai: #eef2ff;
        --shadow: 0 18px 45px rgba(92, 64, 35, 0.12);
    }}
    * {{ box-sizing: border-box; }}
    body {{
        margin: 0;
        min-height: 100vh;
        background:
            radial-gradient(circle at top left, rgba(251, 191, 36, 0.20), transparent 34vw),
            linear-gradient(135deg, #f8f1df 0%, #f3ead8 45%, #eef7f2 100%);
        color: var(--ink);
        font-family: "Microsoft YaHei", "PingFang SC", Arial, sans-serif;
    }}
    .shell {{
        width: min(1360px, calc(100vw - 32px));
        margin: 0 auto;
        padding: 28px 0 46px;
    }}
    .hero {{
        display: grid;
        grid-template-columns: minmax(0, 1fr) auto;
        gap: 18px;
        align-items: end;
        margin-bottom: 18px;
    }}
    h1 {{
        margin: 0;
        font-size: clamp(28px, 4vw, 44px);
        line-height: 1.12;
        letter-spacing: -0.03em;
    }}
    .subtitle {{
        margin: 10px 0 0;
        max-width: 820px;
        color: var(--muted);
        font-size: 14px;
        line-height: 1.8;
    }}
    .hero-badge {{
        min-width: 220px;
        padding: 14px 16px;
        border: 1px solid var(--line);
        border-radius: 18px;
        background: rgba(255, 250, 241, 0.72);
        box-shadow: var(--shadow);
    }}
    .hero-badge span {{ display: block; color: var(--muted); font-size: 13px; }}
    .hero-badge strong {{ display: block; margin-top: 5px; font-size: 24px; }}
    .metrics {{
        display: grid;
        grid-template-columns: repeat(5, minmax(0, 1fr));
        gap: 10px;
        margin-bottom: 14px;
    }}
    .metric,
    .panel {{
        border: 1px solid var(--line);
        border-radius: 18px;
        background: rgba(255, 250, 241, 0.86);
        box-shadow: 0 12px 28px rgba(92, 64, 35, 0.08);
    }}
    .metric {{ padding: 14px 16px; min-height: 82px; }}
    .metric span {{ display: block; color: var(--muted); font-size: 13px; }}
    .metric strong {{ display: block; margin-top: 8px; font-size: 24px; line-height: 1.15; }}
    .filters {{
        display: grid;
        grid-template-columns: minmax(240px, 1.45fr) repeat(4, minmax(110px, 0.8fr)) auto;
        gap: 10px;
        align-items: end;
        padding: 14px;
        margin-bottom: 14px;
    }}
    label {{ display: grid; gap: 6px; color: var(--muted); font-size: 13px; }}
    input,
    select,
    button,
    textarea {{
        border: 1px solid #decba9;
        border-radius: 12px;
        background: #fffdf8;
        color: var(--ink);
        font: inherit;
        font-size: 14px;
    }}
    input,
    select {{ width: 100%; min-height: 40px; padding: 0 12px; }}
    textarea {{ width: 100%; min-height: 86px; padding: 10px 12px; resize: vertical; }}
    button {{
        min-height: 40px;
        padding: 0 14px;
        cursor: pointer;
        background: var(--ink);
        color: #fff;
        font-weight: 700;
        border-color: var(--ink);
    }}
    button.secondary {{ background: #fffdf8; color: var(--ink); border-color: #decba9; }}
    button.green {{ background: var(--accent-2); border-color: var(--accent-2); color: #fff; }}
    button:disabled {{ opacity: 0.5; cursor: not-allowed; }}
    .layout {{
        display: grid;
        grid-template-columns: minmax(310px, 0.72fr) minmax(0, 1.28fr);
        gap: 16px;
        align-items: start;
    }}
    .panel {{ overflow: hidden; }}
    .panel-head {{
        display: flex;
        align-items: baseline;
        justify-content: space-between;
        gap: 12px;
        padding: 15px 17px;
        border-bottom: 1px solid var(--line);
        background: rgba(255, 247, 230, 0.72);
    }}
    .panel-head h2 {{ margin: 0; font-size: 18px; line-height: 1.35; }}
    .panel-head span {{ color: var(--muted); font-size: 13px; }}
    .result-list {{ max-height: 760px; overflow: auto; padding: 10px; }}
    .result-item {{
        width: 100%;
        min-height: 86px;
        margin: 0 0 9px;
        padding: 12px 12px;
        border: 1px solid transparent;
        border-radius: 14px;
        background: #fffdf8;
        color: var(--ink);
        text-align: left;
        cursor: pointer;
    }}
    .result-item:hover {{ border-color: #eab308; }}
    .result-item.is-active {{ border-color: #f59e0b; background: var(--accent-soft); }}
    .result-title {{ display: flex; justify-content: space-between; gap: 10px; font-weight: 800; line-height: 1.4; }}
    .result-title small {{ flex: 0 0 auto; color: var(--accent); font-size: 12px; font-weight: 700; }}
    .result-meta,
    .result-snippet {{ margin-top: 7px; color: var(--muted); font-size: 13px; line-height: 1.55; }}
    .result-snippet {{ color: #4b5563; }}
    .detail {{ min-height: 760px; padding: 20px; }}
    .detail-top {{
        display: grid;
        grid-template-columns: minmax(0, 1fr) auto;
        gap: 12px;
        align-items: start;
        margin-bottom: 14px;
    }}
    .detail h2 {{ margin: 0; font-size: 30px; line-height: 1.22; letter-spacing: -0.02em; }}
    .detail-meta {{ display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }}
    .tag {{
        display: inline-flex;
        align-items: center;
        min-height: 28px;
        padding: 0 10px;
        border: 1px solid var(--line);
        border-radius: 999px;
        background: #fffdf8;
        color: #4b5563;
        font-size: 13px;
    }}
    .detail-actions {{ display: flex; flex-wrap: wrap; gap: 8px; justify-content: flex-end; }}
    .parallel {{
        display: grid;
        grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
        gap: 14px;
        align-items: stretch;
    }}
    .text-card {{
        border: 1px solid var(--line);
        border-radius: 18px;
        background: #fffdf8;
        overflow: hidden;
    }}
    .text-card h3 {{
        margin: 0;
        padding: 13px 15px;
        border-bottom: 1px solid var(--line);
        background: #fff7e6;
        font-size: 16px;
    }}
    .text-body {{
        padding: 16px 18px;
        white-space: pre-wrap;
        font-size: 18px;
        line-height: 2.05;
        font-family: "STKaiti", "KaiTi", "Songti SC", serif;
    }}
    .translation-body {{
        padding: 16px 18px;
        white-space: pre-wrap;
        font-size: 16px;
        line-height: 2.05;
    }}
    .line-pair {{
        display: grid;
        grid-template-columns: minmax(0, 0.92fr) minmax(0, 1.08fr);
        gap: 12px;
        padding: 11px 0;
        border-bottom: 1px dashed rgba(139, 115, 85, 0.24);
    }}
    .line-pair:last-child {{ border-bottom: 0; }}
    .line-original {{ font-family: "STKaiti", "KaiTi", "Songti SC", serif; font-size: 17px; line-height: 1.8; }}
    .line-translation {{ color: #374151; font-size: 15px; line-height: 1.85; }}
    .ai-panel {{
        margin-top: 14px;
        border: 1px solid #c7d2fe;
        border-radius: 18px;
        background: var(--ai);
        overflow: hidden;
    }}
    .ai-head {{
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
        padding: 13px 15px;
        border-bottom: 1px solid #c7d2fe;
    }}
    .ai-head h3 {{ margin: 0; font-size: 16px; }}
    .ai-body {{ padding: 14px 15px 16px; }}
    .ai-grid {{ display: grid; grid-template-columns: minmax(220px, 1fr) auto auto; gap: 8px; align-items: end; }}
    .ai-status {{ margin: 10px 0 0; color: #4f46e5; font-size: 13px; line-height: 1.6; }}
    .ai-output {{
        margin-top: 12px;
        min-height: 82px;
        padding: 12px 13px;
        border: 1px solid #c7d2fe;
        border-radius: 14px;
        background: #fff;
        white-space: pre-wrap;
        line-height: 1.85;
        color: #1f2937;
    }}
    .empty {{ padding: 28px; color: var(--muted); line-height: 1.75; }}
    .note {{ margin-top: 10px; color: var(--muted); font-size: 13px; line-height: 1.7; }}
    mark {{ padding: 0 2px; border-radius: 4px; background: #fde68a; color: inherit; }}
    @media (max-width: 1020px) {{
        .hero {{ grid-template-columns: 1fr; }}
        .metrics {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
        .filters {{ grid-template-columns: 1fr 1fr; }}
        .filters label:first-child {{ grid-column: 1 / -1; }}
        .layout {{ grid-template-columns: 1fr; }}
        .result-list {{ max-height: 460px; }}
        .detail {{ min-height: auto; }}
    }}
    @media (max-width: 720px) {{
        .shell {{ width: min(100vw - 20px, 1360px); padding-top: 18px; }}
        .metrics,
        .filters,
        .parallel,
        .line-pair,
        .ai-grid,
        .detail-top {{ grid-template-columns: 1fr; }}
        .detail-actions {{ justify-content: flex-start; }}
        .detail h2 {{ font-size: 24px; }}
        .text-body {{ font-size: 16px; }}
    }}
    </style>
</head>
<body>
    <main class="shell">
        <section class="hero">
            <div>
                <h1>诗行万里 · 诗词白话翻译</h1>
                <p class="subtitle">左侧选择或检索一首诗，右侧立即显示原文与白话译文。默认译文为本地规则生成的辅助译文；需要更自然的逐句译文时，可在页面底部输入 DeepSeek Key，对当前诗进行 AI 精译。</p>
            </div>
            <aside class="hero-badge">
                <span>交互方式</span>
                <strong>点诗即翻译</strong>
            </aside>
        </section>

        <section class="metrics" aria-label="翻译数据概览">
            <div class="metric"><span>诗作</span><strong>{len(poems):,} 首</strong></div>
            <div class="metric"><span>诗人</span><strong>{poet_count:,} 位</strong></div>
            <div class="metric"><span>朝代</span><strong>{dynasty_count:,} 类</strong></div>
            <div class="metric"><span>流派</span><strong>{school_count:,} 类</strong></div>
            <div class="metric"><span>季节标签</span><strong>{season_count:,} 类</strong></div>
        </section>

        <section class="panel filters" aria-label="筛选诗作">
            <label>关键词
                <input id="queryInput" type="search" placeholder="题名、诗人、原文、译文" autocomplete="off">
            </label>
            <label>诗人
                <select id="poetFilter"><option value="">全部</option></select>
            </label>
            <label>朝代
                <select id="dynastyFilter"><option value="">全部</option></select>
            </label>
            <label>流派
                <select id="schoolFilter"><option value="">全部</option></select>
            </label>
            <label>季节
                <select id="seasonFilter"><option value="">全部</option></select>
            </label>
            <button id="resetButton" type="button">重置</button>
        </section>

        <section class="layout">
            <aside class="panel">
                <div class="panel-head">
                    <h2>诗作列表</h2>
                    <span id="resultCount">0 首</span>
                </div>
                <div id="resultList" class="result-list"></div>
            </aside>
            <article class="panel">
                <div class="panel-head">
                    <h2>原文与白话</h2>
                    <span id="detailHint">点击左侧诗作</span>
                </div>
                <div id="detailPanel" class="detail" aria-live="polite"></div>
            </article>
        </section>
    </main>

    <script>
    window.TRANSLATION_BROWSER_DATA = {payload};

    const poems = window.TRANSLATION_BROWSER_DATA || [];
    const STATE_KEY = "poemTranslationBrowserState";
    const DEEPSEEK_KEY = "deepseekApiKey";
    const AI_CACHE_PREFIX = "poemTranslationAi:";

    const state = {{
        query: "",
        poet: "",
        dynasty: "",
        school: "",
        season: "",
        activeId: poems[0] ? poems[0].id : null,
    }};

    const els = {{
        query: document.getElementById("queryInput"),
        poet: document.getElementById("poetFilter"),
        dynasty: document.getElementById("dynastyFilter"),
        school: document.getElementById("schoolFilter"),
        season: document.getElementById("seasonFilter"),
        reset: document.getElementById("resetButton"),
        list: document.getElementById("resultList"),
        count: document.getElementById("resultCount"),
        detail: document.getElementById("detailPanel"),
        hint: document.getElementById("detailHint"),
    }};

    function storage() {{
        try {{ return window.localStorage; }} catch (error) {{
            return {{ getItem: () => null, setItem: () => {{}}, removeItem: () => {{}} }};
        }}
    }}

    function escapeHtml(value) {{
        return String(value == null ? "" : value).replace(/[&<>"']/g, function (ch) {{
            return {{"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}}[ch];
        }});
    }}

    function normalize(value) {{
        return String(value == null ? "" : value).trim();
    }}

    function poemHash(poem) {{
        const text = [poem.title, poem.poet, poem.body].join("|");
        let hash = 0;
        for (let i = 0; i < text.length; i += 1) {{
            hash = ((hash << 5) - hash + text.charCodeAt(i)) | 0;
        }}
        return String(Math.abs(hash));
    }}

    function aiCacheKey(poem) {{
        return AI_CACHE_PREFIX + poem.id + ":" + poemHash(poem);
    }}

    function getAiTranslation(poem) {{
        return storage().getItem(aiCacheKey(poem)) || "";
    }}

    function setAiTranslation(poem, value) {{
        storage().setItem(aiCacheKey(poem), value || "");
    }}

    function clearAiTranslation(poem) {{
        storage().removeItem(aiCacheKey(poem));
    }}

    function uniqOptions(key) {{
        return [...new Set(poems.map(item => normalize(item[key])).filter(Boolean))].sort((a, b) => a.localeCompare(b, "zh-Hans-CN"));
    }}

    function fillSelect(select, values) {{
        const old = select.value;
        select.innerHTML = '<option value="">全部</option>' + values.map(value => `<option value="${{escapeHtml(value)}}">${{escapeHtml(value)}}</option>`).join("");
        select.value = values.includes(old) ? old : "";
    }}

    function hydrateOptions() {{
        fillSelect(els.poet, uniqOptions("poet"));
        fillSelect(els.dynasty, uniqOptions("dynasty"));
        fillSelect(els.school, uniqOptions("school"));
        fillSelect(els.season, uniqOptions("season"));
    }}

    function searchableText(poem) {{
        return [poem.title, poem.poet, poem.dynasty, poem.school, poem.season, poem.body, poem.translation].join(" ").toLowerCase();
    }}

    function filteredPoems() {{
        const q = normalize(state.query).toLowerCase();
        return poems.filter(poem => {{
            if (state.poet && poem.poet !== state.poet) return false;
            if (state.dynasty && poem.dynasty !== state.dynasty) return false;
            if (state.school && poem.school !== state.school) return false;
            if (state.season && poem.season !== state.season) return false;
            if (q && !searchableText(poem).includes(q)) return false;
            return true;
        }});
    }}

    function compact(text, limit = 82) {{
        const clean = normalize(text).replace(/\s+/g, "");
        return clean.length > limit ? clean.slice(0, limit) + "…" : clean;
    }}

    function highlight(text) {{
        const raw = String(text == null ? "" : text);
        const q = normalize(state.query);
        if (!q) return escapeHtml(raw);

        const lower = raw.toLowerCase();
        const needle = q.toLowerCase();
        let cursor = 0;
        let html = "";

        while (true) {{
            const pos = lower.indexOf(needle, cursor);
            if (pos < 0) break;
            html += escapeHtml(raw.slice(cursor, pos));
            html += "<mark>" + escapeHtml(raw.slice(pos, pos + q.length)) + "</mark>";
            cursor = pos + q.length;
        }}

        html += escapeHtml(raw.slice(cursor));
        return html;
    }}

    function saveState() {{
        storage().setItem(STATE_KEY, JSON.stringify(state));
    }}

    function restoreState() {{
        try {{
            const saved = JSON.parse(storage().getItem(STATE_KEY) || "{{}}");
            Object.assign(state, saved);
        }} catch (error) {{}}
        els.query.value = state.query || "";
        els.poet.value = state.poet || "";
        els.dynasty.value = state.dynasty || "";
        els.school.value = state.school || "";
        els.season.value = state.season || "";
    }}

    function syncStateFromInputs() {{
        state.query = els.query.value || "";
        state.poet = els.poet.value || "";
        state.dynasty = els.dynasty.value || "";
        state.school = els.school.value || "";
        state.season = els.season.value || "";
    }}

    function renderList() {{
        const rows = filteredPoems();
        els.count.textContent = rows.length + " 首";

        if (!rows.length) {{
            els.list.innerHTML = '<div class="empty">没有匹配的诗作，请放宽关键词或筛选条件。</div>';
            renderDetail(null);
            return;
        }}

        if (!rows.some(item => item.id === state.activeId)) {{
            state.activeId = rows[0].id;
        }}

        els.list.innerHTML = rows.map(poem => `
            <button class="result-item ${{poem.id === state.activeId ? "is-active" : ""}}" type="button" data-id="${{poem.id}}">
                <div class="result-title">
                    <span>${{highlight(poem.title || "无题")}}</span>
                    <small>${{escapeHtml(poem.season || "未标")}}</small>
                </div>
                <div class="result-meta">${{escapeHtml(poem.dynasty || "未标")}} · ${{escapeHtml(poem.poet || "佚名")}} · ${{escapeHtml(poem.school || "未分")}}</div>
                <div class="result-snippet">${{highlight(compact(poem.body))}}</div>
            </button>
        `).join("");

        els.list.querySelectorAll(".result-item").forEach(button => {{
            button.addEventListener("click", function () {{
                state.activeId = Number(this.dataset.id);
                saveState();
                renderList();
            }});
        }});

        renderDetail(poems.find(item => item.id === state.activeId) || rows[0]);
        saveState();
    }}

    function splitLines(text) {{
        return normalize(text).split(/\n+/).map(line => line.trim()).filter(Boolean);
    }}

    function renderLinePairs(poem, activeTranslation) {{
        const originals = splitLines(poem.body);
        const translations = splitLines(activeTranslation || poem.translation);
        const total = Math.max(originals.length, translations.length);
        const pairs = [];
        for (let i = 0; i < total; i += 1) {{
            pairs.push(`
                <div class="line-pair">
                    <div class="line-original">${{escapeHtml(originals[i] || "")}}</div>
                    <div class="line-translation">${{escapeHtml(translations[i] || "")}}</div>
                </div>
            `);
        }}
        return pairs.join("");
    }}

    function currentPoem() {{
        return poems.find(item => item.id === state.activeId) || null;
    }}

    function renderDetail(poem) {{
        if (!poem) {{
            els.hint.textContent = "未选择";
            els.detail.innerHTML = '<div class="empty">点击左侧任意诗作后，这里会显示原文和白话翻译。</div>';
            return;
        }}

        const aiTranslation = getAiTranslation(poem);
        const activeTranslation = aiTranslation || poem.translation;
        const translationLabel = aiTranslation ? "AI 精译缓存" : "本地白话辅助译文";
        els.hint.textContent = translationLabel;

        els.detail.innerHTML = `
            <div class="detail-top">
                <div>
                    <h2>${{escapeHtml(poem.title || "无题")}}</h2>
                    <div class="detail-meta">
                        <span class="tag">${{escapeHtml(poem.dynasty || "未标")}}</span>
                        <span class="tag">${{escapeHtml(poem.poet || "佚名")}}</span>
                        <span class="tag">${{escapeHtml(poem.school || "未分")}}</span>
                        <span class="tag">${{escapeHtml(poem.season || "未标")}}</span>
                        <span class="tag">${{poem.body_len || 0}} 字</span>
                    </div>
                </div>
                <div class="detail-actions">
                    <button id="copyOriginalButton" type="button" class="secondary">复制原文</button>
                    <button id="copyTranslationButton" type="button" class="secondary">复制译文</button>
                    <button id="clearAiButton" type="button" class="secondary" ${{aiTranslation ? "" : "disabled"}}>清除 AI 译文</button>
                </div>
            </div>

            <section class="parallel" aria-label="原文和译文">
                <div class="text-card">
                    <h3>原文</h3>
                    <div class="text-body">${{escapeHtml(poem.body || "")}}</div>
                </div>
                <div class="text-card">
                    <h3>${{translationLabel}}</h3>
                    <div class="translation-body">${{escapeHtml(activeTranslation || "暂无译文")}}</div>
                </div>
            </section>

            <section class="text-card" style="margin-top:14px;">
                <h3>逐句对照</h3>
                <div class="translation-body">${{renderLinePairs(poem, activeTranslation)}}</div>
            </section>

            <section class="ai-panel" aria-label="AI 精译">
                <div class="ai-head">
                    <h3>AI 精译当前诗</h3>
                    <span class="tag">Key 仅保存在当前浏览器 localStorage</span>
                </div>
                <div class="ai-body">
                    <div class="ai-grid">
                        <label>DeepSeek Key
                            <input id="deepseekApiKeyInput" type="password" placeholder="sk-..." autocomplete="off">
                        </label>
                        <button id="saveDeepseekKeyButton" type="button" class="secondary">保存 Key</button>
                        <button id="askDeepseekButton" type="button" class="green">AI 精译</button>
                    </div>
                    <p id="aiStatus" class="ai-status">默认显示本地辅助译文；点击 AI 精译后会覆盖为当前诗的高质量译文缓存。</p>
                    <div id="aiOutput" class="ai-output">${{escapeHtml(aiTranslation || "AI 译文会显示在这里。")}}</div>
                    <p class="note">提示：如果浏览器直连被 CORS、网络或 Key 权限拦截，页面会保留本地辅助译文，不会伪造 AI 成功结果。</p>
                </div>
            </section>
        `;

        bindDetailActions(poem);
    }}

    function copyText(text, fallbackMessage) {{
        if (navigator.clipboard && navigator.clipboard.writeText) {{
            navigator.clipboard.writeText(text || "").catch(() => {{}});
        }} else {{
            const textarea = document.createElement("textarea");
            textarea.value = text || "";
            document.body.appendChild(textarea);
            textarea.select();
            try {{ document.execCommand("copy"); }} catch (error) {{}}
            textarea.remove();
        }}
        const status = document.getElementById("aiStatus");
        if (status) status.textContent = fallbackMessage;
    }}

    function bindDetailActions(poem) {{
        const copyOriginal = document.getElementById("copyOriginalButton");
        const copyTranslation = document.getElementById("copyTranslationButton");
        const clearAi = document.getElementById("clearAiButton");
        const saveKey = document.getElementById("saveDeepseekKeyButton");
        const ask = document.getElementById("askDeepseekButton");
        const keyInput = document.getElementById("deepseekApiKeyInput");

        if (keyInput) keyInput.value = storage().getItem(DEEPSEEK_KEY) || "";
        if (copyOriginal) copyOriginal.addEventListener("click", () => copyText(poem.body || "", "原文已复制。"));
        if (copyTranslation) copyTranslation.addEventListener("click", () => copyText(getAiTranslation(poem) || poem.translation || "", "译文已复制。"));
        if (clearAi) clearAi.addEventListener("click", () => {{ clearAiTranslation(poem); renderDetail(poem); }});
        if (saveKey) saveKey.addEventListener("click", saveDeepseekKey);
        if (ask) ask.addEventListener("click", translateWithDeepSeek);
    }}

    function saveDeepseekKey() {{
        const input = document.getElementById("deepseekApiKeyInput");
        const status = document.getElementById("aiStatus");
        const key = input ? normalize(input.value) : "";
        storage().setItem(DEEPSEEK_KEY, key);
        if (status) status.textContent = key ? "DeepSeek Key 已保存到 localStorage。" : "DeepSeek Key 已清空。";
    }}

    function buildDeepSeekPrompt(poem) {{
        return [
            "请把下面这首古诗词翻译成现代白话文。",
            "要求：",
            "1. 逐句翻译，尽量和原文句序一致。",
            "2. 不要扩写成长篇赏析，不要虚构背景。",
            "3. 输出格式用『原句：译文』，最后追加一段不超过120字的整体大意。",
            "",
            "题目：" + (poem.title || "无题"),
            "作者：" + (poem.dynasty || "") + " " + (poem.poet || "佚名"),
            "原文：",
            poem.body || ""
        ].join("\n");
    }}

    async function translateWithDeepSeek() {{
        const poem = currentPoem();
        const status = document.getElementById("aiStatus");
        const output = document.getElementById("aiOutput");
        const keyInput = document.getElementById("deepseekApiKeyInput");
        const key = keyInput ? normalize(keyInput.value) : "";

        if (!poem) {{
            if (status) status.textContent = "请先选择一首诗。";
            return;
        }}
        if (!key) {{
            if (status) status.textContent = "请先输入 DeepSeek Key。";
            return;
        }}
        if (!window.fetch) {{
            if (status) status.textContent = "当前浏览器不支持 fetch，无法直连 DeepSeek。";
            return;
        }}

        storage().setItem(DEEPSEEK_KEY, key);
        if (status) status.textContent = "正在请求 DeepSeek 精译...";
        if (output) output.textContent = "翻译中，请稍候...";

        try {{
            const response = await fetch("https://api.deepseek.com/chat/completions", {{
                method: "POST",
                headers: {{
                    "Content-Type": "application/json",
                    "Authorization": "Bearer " + key
                }},
                body: JSON.stringify({{
                    model: "deepseek-v4-flash",
                    messages: [
                        {{ role: "system", content: "你是严谨的中国古诗词白话翻译助手。只做翻译和简明大意，不编造作者生平或数据库外结论。" }},
                        {{ role: "user", content: buildDeepSeekPrompt(poem) }}
                    ],
                    temperature: 0.2
                }})
            }});

            const payloadText = await response.text();
            let payload = {{}};
            try {{ payload = JSON.parse(payloadText); }} catch (parseError) {{}}
            if (!response.ok) {{
                throw new Error("HTTP " + response.status + " " + ((payload.error && payload.error.message) || payloadText || ""));
            }}

            const content = payload.choices && payload.choices[0] && payload.choices[0].message
                ? payload.choices[0].message.content
                : payloadText;
            if (!content) throw new Error("DeepSeek 返回为空。");

            setAiTranslation(poem, content);
            if (status) status.textContent = "AI 精译已生成，并缓存到当前浏览器。";
            renderDetail(poem);
        }} catch (error) {{
            const message = error && error.message ? error.message : String(error);
            if (status) status.textContent = "DeepSeek 请求失败：" + message;
            if (output) output.textContent = "浏览器直连可能被 CORS、网络或 Key 权限拦截；请继续使用本地辅助译文，或改用你自己的后端代理。";
        }}
    }}

    function resetFilters() {{
        state.query = "";
        state.poet = "";
        state.dynasty = "";
        state.school = "";
        state.season = "";
        els.query.value = "";
        els.poet.value = "";
        els.dynasty.value = "";
        els.school.value = "";
        els.season.value = "";
        renderList();
    }}

    function bindEvents() {{
        [els.query, els.poet, els.dynasty, els.school, els.season].forEach(el => {{
            el.addEventListener("input", function () {{
                syncStateFromInputs();
                renderList();
            }});
            el.addEventListener("change", function () {{
                syncStateFromInputs();
                renderList();
            }});
        }});
        els.reset.addEventListener("click", resetFilters);
    }}

    hydrateOptions();
    restoreState();
    bindEvents();
    renderList();
    </script>
</body>
</html>
"""

    html = inject_index_backlink(html)
    OUT_HTML.write_text(html, encoding="utf-8")
    print(f"[ok] 写入 {OUT_HTML}")


if __name__ == "__main__":
    render()
