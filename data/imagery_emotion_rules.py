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
    "乡思归心": {"keywords": ("故乡", "故园", "乡关", "乡心", "梦还乡", "望乡", "归乡", "还乡", "吾乡", "故山", "故庐", "归心"), "description": "客地触景而生的乡思与归心。"},
    "怀人忆友": {"keywords": ("怀人", "忆君", "相忆", "念远", "故人", "亲朋", "怀子由", "寄君", "寄愁心", "音书", "尺素", "相思处"), "description": "对亲友知交的思念与音问阻隔。"},
    "送别依依": {"keywords": ("送别", "惜别", "临别", "别君", "与君别", "西辞", "送行", "折柳", "分袂", "别后", "别经年", "明日隔"), "description": "送行、分袂与依依惜别。"},
    "爱情缠绵": {"keywords": ("相思", "思君", "君情", "妾心", "鸳鸯", "连理", "两心", "山盟", "恩爱", "欢情", "深情", "多情"), "description": "恋慕、夫妻情爱与缠绵相思。"},
    "闺怨独守": {"keywords": ("独守空闺", "香闺", "妆楼", "翠楼", "罗帷", "玉枕", "鸳衾", "盼归", "待归", "倚阑干", "帘卷西风", "锦书谁寄"), "description": "闺中独守、盼归与幽怨。"},
    "羁旅漂泊": {"keywords": ("羁旅", "作客", "客愁", "客路", "天涯客", "漂沦", "沦落", "远游", "异乡", "旅夜", "孤蓬", "身世浮沉"), "description": "客居、远游与身世漂泊。"},
    "孤寂清冷": {"keywords": ("孤舟", "孤帆", "孤鸿", "孤村", "孤馆", "孤灯", "独酌", "独宿", "寂寞", "无人省", "谁与共", "沙洲冷"), "description": "独处、无人相伴的清冷孤寂。"},
    "悲秋萧瑟": {"keywords": ("悲秋", "秋思", "秋声", "秋风萧瑟", "无边落木", "黄叶", "衰草", "西风紧", "霜天", "暮秋", "秋雨", "万木凋"), "description": "由秋景触发的萧瑟与衰飒。"},
    "惜春伤逝": {"keywords": ("惜春", "伤春", "残春", "暮春", "花落", "花谢", "春归", "春去", "芳菲歇", "流水落花", "韶光易逝", "年华虚度"), "description": "惜春惜花与时光消逝。"},
    "迟暮病老": {"keywords": ("白发", "衰鬓", "霜鬓", "鬓如霜", "多病", "病骨", "残年", "暮年", "迟暮", "老病", "衰颜", "憔悴"), "description": "衰老、病痛与生命迟暮。"},
    "悼亡哀亲": {"keywords": ("悼亡", "亡妻", "丧亲", "孤坟", "生死两茫茫", "祭文", "哭子", "哭友", "遗孤", "亲恩", "泉下", "幽明永隔"), "description": "悼亡、怀亲与生死永隔。"},
    "忧国伤乱": {"keywords": ("国破", "忧国", "社稷", "烽火", "干戈", "丧乱", "战乱", "遗民", "山河破碎", "胡尘", "国难", "黍离"), "description": "国运衰危、战争乱离与感时。"},
    "忠愤报国": {"keywords": ("报国", "王师", "恢复中原", "九州同", "铁马冰河", "胡未灭", "戍轮台", "丹心", "从军", "杀敌", "楼兰", "忠魂"), "description": "恢复理想、守边报国与忠愤。"},
    "民生悲悯": {"keywords": ("黎元", "苍生", "天下寒士", "朱门酒肉臭", "冻死骨", "征夫", "哀鸿", "饥寒", "饿殍", "民瘼", "可怜身上衣", "妇啼一何苦"), "description": "对百姓疾苦与战争牺牲的悲悯。"},
    "怀才幽愤": {"keywords": ("怀才不遇", "壮志难酬", "报国无门", "不见用", "谗毁", "贬谪", "失路", "蹭蹬", "明珠暗投", "李广难封", "塞上长城空自许", "大道如青天"), "description": "才志受抑、遭谗贬谪的幽愤。"},
    "豪迈进取": {"keywords": ("长风破浪", "直挂云帆", "会当凌绝顶", "天生我材", "一览众山小", "壮志凌云", "气吞万里", "扶摇直上", "少年狂", "意气", "豪杰", "壮思"), "description": "雄健自信、建功进取的豪迈。"},
    "超然旷达": {"keywords": ("何妨", "谁怕", "任平生", "且徐行", "此心安处", "也无风雨也无晴", "一蓑烟雨", "何羡", "此事古难全", "一场大梦", "谈笑间", "休将白发"), "description": "面对逆境的自我调适与超然。"},
    "田园闲适": {"keywords": ("采菊东篱", "归田", "田园", "柴门", "茅舍", "新茶", "闲居", "闲坐", "怡然", "自在", "垂钓", "丰年留客"), "description": "田园生活、闲居饮茶的自适。"},
    "山水清赏": {"keywords": ("晴方好", "山色空蒙", "江山如画", "清风徐来", "水波不兴", "空翠", "烟岚", "清溪", "飞瀑", "幽泉", "胜景", "最爱湖东"), "description": "对山水胜景的清赏与愉悦。"},
    "归隐忘机": {"keywords": ("归隐", "隐逸", "归去", "忘机", "东篱", "桃源", "松下", "云外", "白鹿青崖", "心远地偏", "林泉", "远尘嚣"), "description": "离开尘网、归隐林泉的愿望。"},
    "禅悟哲思": {"keywords": ("禅心", "菩提", "本来无一物", "无住", "空门", "梵音", "顿悟", "物我", "盈虚", "逝者如斯", "阴晴圆缺", "不识真面目"), "description": "禅悟以及时间、物我的哲思。"},
    "咏史怀古": {"keywords": ("怀古", "吊古", "故垒", "古战场", "六朝", "前朝", "兴亡", "盛衰", "千古风流人物", "王谢堂前燕", "宫阙万间", "前不见古人"), "description": "凭吊遗迹、兴亡盛衰的历史感喟。"},
    "讽谏讥刺": {"keywords": ("讽谏", "讥刺", "权贵", "朱门", "宫市", "苛政", "佞臣", "昏君", "遍身罗绮者", "一曲红绡", "长安有贫者", "将军不战"), "description": "对权贵、苛政与社会不公的讽刺。"},
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
NEGATORS = ("不", "未", "莫", "勿", "无", "休")
EMOTION_EXCLUDED_PHRASES = (
    "莫愁", "无忧", "不愁", "不悲", "不恨", "无恨", "未老", "不老",
    "乐府", "长乐", "永乐", "行人司马",  # 人名、地名、官名等固定表达
)


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
        candidates: list[str] = []
        for word in sorted(set(rule["keywords"]), key=lambda item: (-len(item), item)):
            valid_occurrence = False
            start = source.find(word)
            while start >= 0:
                end = start + len(word)
                excluded_here = any(
                    ex_start <= start and end <= ex_start + len(excluded)
                    for excluded in EMOTION_EXCLUDED_PHRASES
                    for ex_start in (source.rfind(excluded, 0, end),)
                    if ex_start >= 0
                )
                negated_here = (
                    len(word) <= 2
                    and source[max(0, start - 2):start].endswith(NEGATORS)
                )
                if not excluded_here and not negated_here:
                    valid_occurrence = True
                    break
                start = source.find(word, start + 1)
            if not valid_occurrence:
                continue
            # 最长词优先：若较短词完全包含在已命中的长短语中，不重复展示。
            if any(word in longer for longer in candidates):
                continue
            candidates.append(word)
        hits = candidates
        if hits:
            matches[emotion] = hits
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
