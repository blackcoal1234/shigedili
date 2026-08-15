"""季节线索识别规则。

规则目标是给课程项目中的每首诗标注一个“主季节”，用于看板聚合。
它是可解释的词表评分规则，不是严格文学考据模型。
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass


SEASONS = ("春", "夏", "秋", "冬")
TITLE_WEIGHT = 3
MASK = "·"


@dataclass(frozen=True)
class SeasonTerm:
    word: str
    weight: int


EXPLICIT_WEIGHT = 8
STRONG_WEIGHT = 6
IMAGE_WEIGHT = 3


SEASON_TERMS: dict[str, tuple[SeasonTerm, ...]] = {
    "春": (
        SeasonTerm("春", EXPLICIT_WEIGHT),
        SeasonTerm("春日", EXPLICIT_WEIGHT),
        SeasonTerm("春夜", EXPLICIT_WEIGHT),
        SeasonTerm("春晓", EXPLICIT_WEIGHT),
        SeasonTerm("春晚", EXPLICIT_WEIGHT),
        SeasonTerm("春风", STRONG_WEIGHT),
        SeasonTerm("春雨", STRONG_WEIGHT),
        SeasonTerm("春水", STRONG_WEIGHT),
        SeasonTerm("春江", STRONG_WEIGHT),
        SeasonTerm("春山", STRONG_WEIGHT),
        SeasonTerm("春草", STRONG_WEIGHT),
        SeasonTerm("春色", STRONG_WEIGHT),
        SeasonTerm("春光", STRONG_WEIGHT),
        SeasonTerm("春阴", STRONG_WEIGHT),
        SeasonTerm("春潮", STRONG_WEIGHT),
        SeasonTerm("东风", STRONG_WEIGHT),
        SeasonTerm("青阳", STRONG_WEIGHT),
        SeasonTerm("清明", STRONG_WEIGHT),
        SeasonTerm("寒食", STRONG_WEIGHT),
        SeasonTerm("上巳", STRONG_WEIGHT),
        SeasonTerm("花朝", STRONG_WEIGHT),
        SeasonTerm("社日", STRONG_WEIGHT),
        SeasonTerm("二月", IMAGE_WEIGHT),
        SeasonTerm("三月", IMAGE_WEIGHT),
        SeasonTerm("桃花", IMAGE_WEIGHT),
        SeasonTerm("桃李", IMAGE_WEIGHT),
        SeasonTerm("杏花", IMAGE_WEIGHT),
        SeasonTerm("梨花", IMAGE_WEIGHT),
        SeasonTerm("海棠", IMAGE_WEIGHT),
        SeasonTerm("柳絮", IMAGE_WEIGHT),
        SeasonTerm("柳色", IMAGE_WEIGHT),
        SeasonTerm("柳条", IMAGE_WEIGHT),
        SeasonTerm("新柳", IMAGE_WEIGHT),
        SeasonTerm("莺", IMAGE_WEIGHT),
        SeasonTerm("黄莺", IMAGE_WEIGHT),
        SeasonTerm("莺啼", IMAGE_WEIGHT),
        SeasonTerm("燕", IMAGE_WEIGHT),
        SeasonTerm("燕子", IMAGE_WEIGHT),
        SeasonTerm("归燕", IMAGE_WEIGHT),
        SeasonTerm("杜鹃", IMAGE_WEIGHT),
        SeasonTerm("芳草", IMAGE_WEIGHT),
        SeasonTerm("青草", IMAGE_WEIGHT),
        SeasonTerm("绿草", IMAGE_WEIGHT),
        SeasonTerm("杨柳", IMAGE_WEIGHT),
        SeasonTerm("烟柳", IMAGE_WEIGHT),
        SeasonTerm("落花", IMAGE_WEIGHT),
        SeasonTerm("飞花", IMAGE_WEIGHT),
        SeasonTerm("花落", IMAGE_WEIGHT),
        SeasonTerm("新绿", IMAGE_WEIGHT),
        SeasonTerm("菜花", IMAGE_WEIGHT),
        SeasonTerm("柳", IMAGE_WEIGHT),
    ),
    "夏": (
        SeasonTerm("夏", EXPLICIT_WEIGHT),
        SeasonTerm("夏日", EXPLICIT_WEIGHT),
        SeasonTerm("夏夜", EXPLICIT_WEIGHT),
        SeasonTerm("夏至", EXPLICIT_WEIGHT),
        SeasonTerm("初夏", STRONG_WEIGHT),
        SeasonTerm("盛夏", STRONG_WEIGHT),
        SeasonTerm("朱夏", STRONG_WEIGHT),
        SeasonTerm("暑", STRONG_WEIGHT),
        SeasonTerm("暑气", STRONG_WEIGHT),
        SeasonTerm("炎", STRONG_WEIGHT),
        SeasonTerm("炎天", STRONG_WEIGHT),
        SeasonTerm("炎夏", STRONG_WEIGHT),
        SeasonTerm("炎暑", STRONG_WEIGHT),
        SeasonTerm("溽暑", STRONG_WEIGHT),
        SeasonTerm("长夏", STRONG_WEIGHT),
        SeasonTerm("清夏", STRONG_WEIGHT),
        SeasonTerm("薰风", STRONG_WEIGHT),
        SeasonTerm("南风", STRONG_WEIGHT),
        SeasonTerm("荷风", STRONG_WEIGHT),
        SeasonTerm("采莲", STRONG_WEIGHT),
        SeasonTerm("荷香", IMAGE_WEIGHT),
        SeasonTerm("荷花", IMAGE_WEIGHT),
        SeasonTerm("荷叶", IMAGE_WEIGHT),
        SeasonTerm("荷塘", IMAGE_WEIGHT),
        SeasonTerm("小荷", IMAGE_WEIGHT),
        SeasonTerm("新荷", IMAGE_WEIGHT),
        SeasonTerm("红莲", IMAGE_WEIGHT),
        SeasonTerm("白莲", IMAGE_WEIGHT),
        SeasonTerm("莲花", IMAGE_WEIGHT),
        SeasonTerm("芙蕖", IMAGE_WEIGHT),
        SeasonTerm("菡萏", IMAGE_WEIGHT),
        SeasonTerm("莲", IMAGE_WEIGHT),
        SeasonTerm("芙蓉", IMAGE_WEIGHT),
        SeasonTerm("蝉", IMAGE_WEIGHT),
        SeasonTerm("鸣蝉", IMAGE_WEIGHT),
        SeasonTerm("新蝉", IMAGE_WEIGHT),
        SeasonTerm("蜩", IMAGE_WEIGHT),
        SeasonTerm("蜻蜓", IMAGE_WEIGHT),
        SeasonTerm("榴花", IMAGE_WEIGHT),
        SeasonTerm("石榴", IMAGE_WEIGHT),
        SeasonTerm("蒲葵", IMAGE_WEIGHT),
        SeasonTerm("绿阴", IMAGE_WEIGHT),
        SeasonTerm("树阴", IMAGE_WEIGHT),
        SeasonTerm("麦秋", IMAGE_WEIGHT),
        SeasonTerm("梅雨", IMAGE_WEIGHT),
        SeasonTerm("黄梅", IMAGE_WEIGHT),
    ),
    "秋": (
        SeasonTerm("秋", EXPLICIT_WEIGHT),
        SeasonTerm("秋日", EXPLICIT_WEIGHT),
        SeasonTerm("秋夜", EXPLICIT_WEIGHT),
        SeasonTerm("秋风", STRONG_WEIGHT),
        SeasonTerm("秋水", STRONG_WEIGHT),
        SeasonTerm("秋月", STRONG_WEIGHT),
        SeasonTerm("秋声", STRONG_WEIGHT),
        SeasonTerm("秋色", STRONG_WEIGHT),
        SeasonTerm("秋思", STRONG_WEIGHT),
        SeasonTerm("秋雨", STRONG_WEIGHT),
        SeasonTerm("清秋", STRONG_WEIGHT),
        SeasonTerm("晚秋", STRONG_WEIGHT),
        SeasonTerm("深秋", STRONG_WEIGHT),
        SeasonTerm("新秋", STRONG_WEIGHT),
        SeasonTerm("西风", STRONG_WEIGHT),
        SeasonTerm("金风", STRONG_WEIGHT),
        SeasonTerm("白露", STRONG_WEIGHT),
        SeasonTerm("寒露", STRONG_WEIGHT),
        SeasonTerm("霜降", STRONG_WEIGHT),
        SeasonTerm("中秋", STRONG_WEIGHT),
        SeasonTerm("重阳", STRONG_WEIGHT),
        SeasonTerm("九日", STRONG_WEIGHT),
        SeasonTerm("七夕", STRONG_WEIGHT),
        SeasonTerm("孟秋", STRONG_WEIGHT),
        SeasonTerm("菊", IMAGE_WEIGHT),
        SeasonTerm("菊花", IMAGE_WEIGHT),
        SeasonTerm("黄花", IMAGE_WEIGHT),
        SeasonTerm("桂子", IMAGE_WEIGHT),
        SeasonTerm("桂花", IMAGE_WEIGHT),
        SeasonTerm("桂", IMAGE_WEIGHT),
        SeasonTerm("梧桐", IMAGE_WEIGHT),
        SeasonTerm("梧叶", IMAGE_WEIGHT),
        SeasonTerm("桐叶", IMAGE_WEIGHT),
        SeasonTerm("红叶", IMAGE_WEIGHT),
        SeasonTerm("落叶", IMAGE_WEIGHT),
        SeasonTerm("黄叶", IMAGE_WEIGHT),
        SeasonTerm("枫林", IMAGE_WEIGHT),
        SeasonTerm("枫叶", IMAGE_WEIGHT),
        SeasonTerm("枫", IMAGE_WEIGHT),
        SeasonTerm("霜叶", IMAGE_WEIGHT),
        SeasonTerm("蛩", IMAGE_WEIGHT),
        SeasonTerm("蟋蟀", IMAGE_WEIGHT),
        SeasonTerm("寒蝉", IMAGE_WEIGHT),
        SeasonTerm("鸿雁", IMAGE_WEIGHT),
        SeasonTerm("征雁", IMAGE_WEIGHT),
        SeasonTerm("雁", IMAGE_WEIGHT),
        SeasonTerm("芦花", IMAGE_WEIGHT),
        SeasonTerm("荻花", IMAGE_WEIGHT),
        SeasonTerm("蒹葭", IMAGE_WEIGHT),
        SeasonTerm("冷露", IMAGE_WEIGHT),
        SeasonTerm("凉风", IMAGE_WEIGHT),
        SeasonTerm("天凉", IMAGE_WEIGHT),
        SeasonTerm("萧瑟", IMAGE_WEIGHT),
    ),
    "冬": (
        SeasonTerm("冬", EXPLICIT_WEIGHT),
        SeasonTerm("冬日", EXPLICIT_WEIGHT),
        SeasonTerm("冬夜", EXPLICIT_WEIGHT),
        SeasonTerm("冬至", EXPLICIT_WEIGHT),
        SeasonTerm("寒冬", STRONG_WEIGHT),
        SeasonTerm("严冬", STRONG_WEIGHT),
        SeasonTerm("初冬", STRONG_WEIGHT),
        SeasonTerm("隆冬", STRONG_WEIGHT),
        SeasonTerm("残冬", STRONG_WEIGHT),
        SeasonTerm("孟冬", STRONG_WEIGHT),
        SeasonTerm("腊", STRONG_WEIGHT),
        SeasonTerm("腊月", STRONG_WEIGHT),
        SeasonTerm("朔风", STRONG_WEIGHT),
        SeasonTerm("北风", STRONG_WEIGHT),
        SeasonTerm("寒风", STRONG_WEIGHT),
        SeasonTerm("岁寒", STRONG_WEIGHT),
        SeasonTerm("岁暮", STRONG_WEIGHT),
        SeasonTerm("年暮", STRONG_WEIGHT),
        SeasonTerm("暮冬", STRONG_WEIGHT),
        SeasonTerm("严寒", STRONG_WEIGHT),
        SeasonTerm("苦寒", STRONG_WEIGHT),
        SeasonTerm("天寒", STRONG_WEIGHT),
        SeasonTerm("寒天", STRONG_WEIGHT),
        SeasonTerm("寒梅", STRONG_WEIGHT),
        SeasonTerm("腊梅", STRONG_WEIGHT),
        SeasonTerm("早梅", STRONG_WEIGHT),
        SeasonTerm("冰雪", IMAGE_WEIGHT),
        SeasonTerm("冰霜", IMAGE_WEIGHT),
        SeasonTerm("飞雪", IMAGE_WEIGHT),
        SeasonTerm("落雪", IMAGE_WEIGHT),
        SeasonTerm("大雪", IMAGE_WEIGHT),
        SeasonTerm("小雪", IMAGE_WEIGHT),
        SeasonTerm("深雪", IMAGE_WEIGHT),
        SeasonTerm("暮雪", IMAGE_WEIGHT),
        SeasonTerm("残雪", IMAGE_WEIGHT),
        SeasonTerm("积雪", IMAGE_WEIGHT),
        SeasonTerm("风雪", IMAGE_WEIGHT),
        SeasonTerm("雪满", IMAGE_WEIGHT),
        SeasonTerm("雪晴", IMAGE_WEIGHT),
        SeasonTerm("雪夜", IMAGE_WEIGHT),
        SeasonTerm("雪", IMAGE_WEIGHT),
        SeasonTerm("冰", IMAGE_WEIGHT),
        SeasonTerm("冻", IMAGE_WEIGHT),
        SeasonTerm("冻云", IMAGE_WEIGHT),
        SeasonTerm("冻雨", IMAGE_WEIGHT),
        SeasonTerm("梅花", IMAGE_WEIGHT),
        SeasonTerm("梅", IMAGE_WEIGHT),
        SeasonTerm("霰", IMAGE_WEIGHT),
        SeasonTerm("炉火", IMAGE_WEIGHT),
        SeasonTerm("围炉", IMAGE_WEIGHT),
        SeasonTerm("炭", IMAGE_WEIGHT),
    ),
}


def _sorted_terms(season: str) -> list[SeasonTerm]:
    return sorted(SEASON_TERMS[season], key=lambda item: len(item.word), reverse=True)


def _score_text_with_counts(text: str, terms: list[SeasonTerm]) -> tuple[int, int, Counter[str]]:
    score = 0
    latest_index = -1
    counts: Counter[str] = Counter()
    work = text or ""
    for term in terms:
        start = 0
        while True:
            idx = work.find(term.word, start)
            if idx < 0:
                break
            score += term.weight
            counts[term.word] += 1
            latest_index = max(latest_index, idx)
            work = work[:idx] + (MASK * len(term.word)) + work[idx + len(term.word):]
            start = idx + len(term.word)
    return score, latest_index, counts


def _score_text(text: str, terms: list[SeasonTerm]) -> tuple[int, int]:
    score, latest_index, _counts = _score_text_with_counts(text, terms)
    return score, latest_index


def season_term_counts(title: str, body: str) -> Counter[tuple[str, str]]:
    """返回按评分口径加权后的季节线索词命中次数。"""
    counts: Counter[tuple[str, str]] = Counter()
    for season in SEASONS:
        terms = _sorted_terms(season)
        _title_score, _title_latest, title_counts = _score_text_with_counts(title, terms)
        _body_score, _body_latest, body_counts = _score_text_with_counts(body, terms)
        for word, value in title_counts.items():
            counts[(season, word)] += value * TITLE_WEIGHT
        for word, value in body_counts.items():
            counts[(season, word)] += value
    return counts


def season_scores(title: str, body: str) -> dict[str, int]:
    """返回春夏秋冬四类线索得分。"""
    scores: dict[str, int] = {}
    for season in SEASONS:
        terms = _sorted_terms(season)
        title_score, _ = _score_text(title, terms)
        body_score, _ = _score_text(body, terms)
        scores[season] = title_score * TITLE_WEIGHT + body_score
    return scores


def detect_season(title: str, body: str) -> str | None:
    """按标题+正文得分识别主季节；没有任何线索时返回 None。"""
    candidates: list[tuple[int, int, int, str]] = []
    title_text = title or ""
    body_text = body or ""
    body_offset = len(title_text) + 1
    for order, season in enumerate(SEASONS):
        terms = _sorted_terms(season)
        title_score, title_latest = _score_text(title_text, terms)
        body_score, body_latest = _score_text(body_text, terms)
        score = title_score * TITLE_WEIGHT + body_score
        if score <= 0:
            continue
        latest = -1
        if title_latest >= 0:
            latest = max(latest, title_latest)
        if body_latest >= 0:
            latest = max(latest, body_offset + body_latest)
        # 同分时选最后出现的季节线索，避免回到固定“春优先”。
        candidates.append((score, latest, -order, season))
    if not candidates:
        return None
    return max(candidates)[3]
