"""同一意象跨诗人情感比较所用的轻量规则。

本模块只描述可复核的文本匹配规则，不给任何意象预设固定情感值。
情感由意象所在分句及其相邻分句中的语境词动态触发，并允许一首诗
同时命中多个情感标签。
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Iterable


TARGET_POETS = ("李白", "杜甫", "白居易", "苏轼", "陆游", "李清照")
TARGET_IMAGERY = ("月", "酒", "舟", "雁", "雨")

# aliases 只承担“这个意象有没有出现”的判断，不能在此附加情感标签。
IMAGERY_RULES: dict[str, dict[str, object]] = {
    "月": {
        "label": "月亮",
        "aliases": (
            "明月", "皓月", "孤月", "残月", "缺月", "落月", "新月", "秋月",
            "月色", "月光", "月影", "月华", "月轮", "月下", "月夜", "月明",
            "婵娟", "桂魄", "玉兔", "蟾宫", "月",
        ),
        "description": "月体、月色及婵娟等传统代称；排除正月、三月等月份表达。",
    },
    "酒": {
        "label": "酒",
        "aliases": (
            "美酒", "清酒", "浊酒", "醇酒", "诗酒", "绿蚁", "新醅", "金樽",
            "玉樽", "芳樽", "匏樽", "樽", "尊前", "一尊", "酒", "酌", "酣",
            "醉", "觞", "盏", "杯",
        ),
        "description": "酒、酒器及明确的饮酒动作；不把一般饮水词直接计作酒。",
    },
    "舟": {
        "label": "舟船",
        "aliases": (
            "孤舟", "扁舟", "轻舟", "行舟", "归舟", "兰舟", "一苇", "舳舻",
            "楼船", "船", "舟", "孤帆", "归帆", "云帆", "帆", "舫", "舸",
            "艇", "棹", "桨",
        ),
        "description": "舟船本体及帆、棹、桨等能明确指向舟行的相关称谓。",
    },
    "雁": {
        "label": "鸿雁",
        "aliases": (
            "鸿雁", "孤雁", "归雁", "征雁", "秋雁", "雁阵", "雁字", "断雁",
            "飞鸿", "孤鸿", "归鸿", "征鸿", "断鸿", "鸿影", "鸿飞", "雁",
        ),
        "description": "雁及可确认指鸟的鸿；不把“鸿都”等人名、地名中的单个鸿计入。",
    },
    "雨": {
        "label": "雨",
        "aliases": (
            "风雨", "烟雨", "夜雨", "春雨", "秋雨", "细雨", "微雨", "苦雨",
            "骤雨", "好雨", "霖雨", "霏雨", "霖", "雨",
        ),
        "description": "各种降雨形态及霖雨等近义表达。",
    },
}


# 每条规则由一组可直接检查的语境词构成。命中任一词即记录该标签；
# 多个标签可以同时出现，因此各情感概率之和不要求等于 1。
EMOTION_CONTEXT_RULES: dict[str, dict[str, object]] = {
    "思乡怀人": {
        "keywords": (
            "故乡", "故园", "故国", "乡心", "还乡", "归乡", "思乡", "忆江南",
            "怀子由", "怀旧", "亲朋", "家书", "故人", "相忆", "思量", "念人",
            "寄君", "寄愁心", "望乡", "忆君", "梦还乡", "吾乡",
        ),
        "description": "指向故乡、亲友或跨越空间的怀念。",
    },
    "离别惜别": {
        "keywords": (
            "送别", "将别", "恨别", "惜别", "别离", "离索", "离合", "送行",
            "一为别", "与君别", "别君", "辞帝京", "西辞", "明日隔", "分散",
            "相见难", "无穷别", "临别", "离人", "别时", "别经年",
        ),
        "description": "送别、分别及对重逢困难的感受。",
    },
    "漂泊孤寂": {
        "keywords": (
            "天涯", "作客", "客愁", "羁旅", "漂沦", "沦落", "远游", "异乡",
            "孤舟", "孤帆", "孤鸿", "孤坟", "孤光", "孤村", "孤臣", "独酌",
            "独宿", "独往来", "独登", "寂寞", "凄凉", "无人省", "无相亲",
            "谁与共", "空船", "独倾", "沙洲冷", "旅人", "行人",
        ),
        "description": "羁旅、客居、独处和缺乏陪伴。",
    },
    "忧国伤时": {
        "keywords": (
            "国破", "忧国", "为国", "中原", "王师", "九州", "遗民", "恢复",
            "社稷", "庙社", "烽火", "干戈", "丧乱", "战乱", "征人", "戍楼",
            "戍边", "戍轮台", "边庭", "铁马", "胡未灭", "逆胡", "将军不战",
            "兵车", "从军", "天下寒士", "忧黎元", "故垒", "征尘",
        ),
        "description": "战争、国家命运、民生疾苦及恢复理想。",
    },
    "豪迈旷达": {
        "keywords": (
            "何妨", "谁怕", "任平生", "长风破浪", "会当凌绝顶", "天生我材",
            "千金散尽", "须尽欢", "且徐行", "直挂云帆", "豪杰", "壮志",
            "壮思", "意气", "胸胆", "少年狂", "谈笑间", "共适", "无尽藏",
            "此心安处", "归去", "放白鹿", "开心颜", "休将白发", "一览众山小",
        ),
        "description": "进取、自信、超越困境或主动自我调适。",
    },
    "欢愉闲适": {
        "keywords": (
            "欢乐", "欢笑", "欢颜", "喜雨", "乐甚", "行乐", "为乐", "得意",
            "自在", "怡然", "闲人", "水自闲", "相逢", "会面", "宴", "共此",
            "好雨", "晴方好", "亦奇", "最爱", "春风", "花满", "能饮一杯",
            "新茶", "陶陶", "天真", "欣然", "清风徐来", "丰年留客",
        ),
        "description": "宴饮相聚、游赏、闲居或明朗轻快的感受。",
    },
    "哲思超越": {
        "keywords": (
            "人生", "世事", "古今", "古人今人", "阴晴圆缺", "万事", "真伪",
            "天地", "须臾", "无穷", "逝者如斯", "盈虚", "一瞬", "无尽",
            "造物", "逆旅", "身非我有", "人有悲欢", "此事古难全", "何羡",
            "一场大梦", "梦中身", "谁知", "何似", "不识真面目", "纸上得来",
        ),
        "description": "关于时间、人生、物我、真假或有限与永恒的思考。",
    },
    "爱情相思": {
        "keywords": (
            "相思", "思君", "君情", "妾心", "佳人", "红颜", "玉颜", "鸳鸯",
            "连理", "两心", "山盟", "锦书", "深情", "恩爱", "欢情", "多情",
            "无情恼", "与谁邻", "窈窕", "长恨", "肠断处", "不见人",
        ),
        "description": "恋慕、夫妻追忆及爱情离合。",
    },
    "悲愁伤逝": {
        "keywords": (
            "悲", "愁", "哀", "伤心", "凋伤", "怆", "凄", "恨", "泪", "泣",
            "肠断", "白发", "白头", "衰鬓", "鬓如霜", "多病", "病骨", "死",
            "萧瑟", "萧森", "冷", "寒", "寂寞", "憔悴", "落叶", "残阳",
            "老", "空照", "不见", "难", "苦", "咨嗟", "叹息",
        ),
        "description": "悲哀、忧愁、衰老、死亡与时间消逝。",
    },
}

EMOTIONS = tuple(EMOTION_CONTEXT_RULES)


# 用于“伴随意象”表。此处仍然只做语词归并，不携带情感值。
COMPANION_IMAGERY_RULES: dict[str, tuple[str, ...]] = {
    "日": ("落日", "残阳", "斜阳", "夕阳", "日"),
    "星": ("星河", "星辰", "斗牛", "星"),
    "云": ("白云", "浮云", "烟云", "云"),
    "风": ("春风", "秋风", "东风", "西风", "清风", "风"),
    "雪": ("暮雪", "夜雪", "雪"),
    "霜": ("霜鬓", "霜华", "霜"),
    "露": ("白露", "玉露", "露"),
    "山": ("青山", "空山", "远山", "山"),
    "江": ("长江", "大江", "江水", "江"),
    "河": ("黄河", "银河", "河"),
    "湖": ("西湖", "洞庭", "湖"),
    "海": ("沧海", "江海", "海"),
    "花": ("桃花", "梨花", "梅花", "落花", "花"),
    "柳": ("杨柳", "柳"),
    "梅": ("梅花", "岭梅", "梅"),
    "竹": ("竹柏", "竹杖", "竹"),
    "灯": ("孤灯", "残灯", "挑灯", "灯烛", "灯"),
    "笛箫": ("羌笛", "洞箫", "箫", "笛"),
    "琴瑟": ("琵琶", "琴", "瑟"),
    "剑": ("宝剑", "剑"),
    "马": ("铁马", "白马", "马"),
    "猿": ("猿声", "猿啸", "猿"),
    "鹤": ("黄鹤", "鹤"),
    "莺燕": ("黄鹂", "莺", "燕子", "燕"),
    "城楼": ("高楼", "戍楼", "城楼", "楼", "城"),
}


CLAUSE_SPLIT_RE = re.compile(r"(?<=[。！？；!?;])|[\r\n]+")
MONTH_RE = re.compile(r"[零〇一二三四五六七八九十正腊冬孟仲季]\s*月")


def split_clauses(text: str) -> list[str]:
    """按换行和句末标点切分，保留原标点以便页面展示证据。"""
    return [part.strip() for part in CLAUSE_SPLIT_RE.split(text or "") if part.strip()]


def _ordered_aliases(imagery: str) -> tuple[str, ...]:
    rule = IMAGERY_RULES[imagery]
    return tuple(sorted(set(rule["aliases"]), key=len, reverse=True))


def matched_aliases(text: str, imagery: str) -> list[str]:
    """返回文本中命中的意象别名；同一别名只返回一次。"""
    if imagery not in IMAGERY_RULES:
        raise KeyError(f"未知目标意象：{imagery}")

    work = text or ""
    matches: list[str] = []
    for alias in _ordered_aliases(imagery):
        if alias not in work:
            continue
        if imagery == "月" and alias == "月":
            # 去掉“八月、中秋七月既望”等月份词后再判断裸“月”。
            work_without_months = MONTH_RE.sub("", work)
            if "月" not in work_without_months:
                continue
        matches.append(alias)
    return matches


def contains_imagery(text: str, imagery: str) -> bool:
    return bool(matched_aliases(text, imagery))


def evidence_contexts(text: str, imagery: str, neighbor: int = 1) -> list[dict[str, object]]:
    """提取命中意象的证据分句，并拼接前后相邻分句作为情感语境。"""
    clauses = split_clauses(text)
    rows: list[dict[str, object]] = []
    for index, clause in enumerate(clauses):
        aliases = matched_aliases(clause, imagery)
        if not aliases:
            continue
        left = max(0, index - max(0, neighbor))
        right = min(len(clauses), index + max(0, neighbor) + 1)
        rows.append(
            {
                "line": clause,
                "context": "".join(clauses[left:right]),
                "aliases": aliases,
                "clause_index": index,
            }
        )
    return rows


def emotion_matches(text: str) -> dict[str, list[str]]:
    """按语境返回多标签情感及其命中词，不做互斥和固定赋值。"""
    source = text or ""
    matches: dict[str, list[str]] = {}
    for emotion, rule in EMOTION_CONTEXT_RULES.items():
        hits = [word for word in rule["keywords"] if word in source]
        if hits:
            matches[emotion] = sorted(set(hits), key=lambda word: (-len(word), word))
    return matches


def local_emotion_matches(context_rows: Iterable[dict[str, object]]) -> dict[str, list[str]]:
    """合并一首诗内同一意象的所有局部语境情感，标签仍按诗作计一次。"""
    merged: dict[str, set[str]] = {}
    for row in context_rows:
        for emotion, words in emotion_matches(str(row.get("context") or "")).items():
            merged.setdefault(emotion, set()).update(words)
    return {
        emotion: sorted(words, key=lambda word: (-len(word), word))
        for emotion, words in merged.items()
    }


def companion_imagery(text: str, excluded: str | None = None) -> list[str]:
    """返回局部语境中的伴随意象；每类在一首诗中最多计一次。"""
    source = text or ""
    found: set[str] = set()

    for imagery in TARGET_IMAGERY:
        if imagery != excluded and contains_imagery(source, imagery):
            found.add(imagery)

    for canonical, aliases in COMPANION_IMAGERY_RULES.items():
        if canonical == excluded:
            continue
        if any(alias in source for alias in sorted(set(aliases), key=len, reverse=True)):
            found.add(canonical)
    return sorted(found)


def sample_level(sample_count: int) -> str:
    """返回项目书约定的小样本展示等级。"""
    if sample_count < 10:
        return "不排名"
    if sample_count < 30:
        return "探索"
    return "正式"


def count_companions(contexts: Iterable[str], excluded: str) -> Counter[str]:
    """按“每首诗每种伴随意象一次”聚合伴随意象。"""
    counts: Counter[str] = Counter()
    for context in contexts:
        counts.update(set(companion_imagery(context, excluded=excluded)))
    return counts
