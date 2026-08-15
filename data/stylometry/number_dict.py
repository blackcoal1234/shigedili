"""数字与量级词典：数词 → 近似数值 + 数量级(log10) + 夸张标记。

用于"李白夸张系数"维度的文体统计。本词典为课程项目中人工整理的分析工具，
词条参考常见古典诗词赏析口径选定，不是权威语言学资源；统计结论仅在下述
口径内成立，不宣称权威。

字段说明（NUMBER_DICT 五元组）：
    (词, 近似数值 value, 数量级 magnitude, 类别 kind, 是否夸张 is_hyperbole)
    magnitude = log10(value)，保留两位小数；value/magnitude 为 None 表示
    该词条不表数量（序数类），不参与任何数量级统计。

kind 口径：
    cardinal —— 基数词（一/三/十/百/千/三千/九万…），按字面近似数值取量级。
    measure  —— 数词+量度或名物的规模组合（三千丈/九万里/千尺/万壑/千帆…）。
    time     —— 数词+时间跨度（千秋/万古/百年/千载…）。
    vague    —— 词汇化虚指（万事/四海/九州/九天…），仍带数量级，多数不计夸张。
    weak     —— 弱数量："一"在"一片/一声/一点"等量词性、副词性搭配中不表
                实际计数，magnitude 记 0，扫描端按 kind 排除出 avg_magnitude。
    ordinal  —— 序数/月份/更次/节令（三月/五更/七夕…），不表数量。
                口径注：二字"数+月"一律按月份序数处理，会牺牲少量歧义
                （如"烽火连三月"实为"三个月之久"，此处仍按序数排除）。

is_hyperbole 口径（人工判定，从严）：
    标 True 的是"大数 × 度量/时间/景物"的经典修辞夸张组合（三千丈/九万里/
    万里/千尺/万古/千秋/千门/万户…）以及虚指大数（三千/八千/九万/千万/亿）。
    裸数词（一~十/百/千/万）一律不标夸张，即使语境中常为虚指（如"千磨万击"
    只计作 千+万 两个基数词）——宁可漏计不愿多计，因此"夸张密度"是保守下界。
    已知误差：词典无法按上下文消歧，"四万八千""十千"等在纪实文字中可为实数
    （如曾巩《越州赵公救灾记》的钱粮数），本词典按诗歌修辞常用口径标夸张，
    在散文语料上会有少量误标。

匹配约定：扫描时按词长从长到短贪心匹配（"三千丈"优先于"三千"，"三千"优先
于"三"和"千"），每个字符至多归入一个词条，避免重复计数。
"""

# (词, 近似数值, 数量级log10, 类别, 是否夸张)
NUMBER_DICT = [
    # ── 基数词：个位与特殊 ──────────────────────────────
    ("一",     1,         0.00, "cardinal", False),
    ("二",     2,         0.30, "cardinal", False),
    ("两",     2,         0.30, "cardinal", False),
    ("双",     2,         0.30, "cardinal", False),
    ("三",     3,         0.48, "cardinal", False),
    ("四",     4,         0.60, "cardinal", False),
    ("五",     5,         0.70, "cardinal", False),
    ("六",     6,         0.78, "cardinal", False),
    ("七",     7,         0.85, "cardinal", False),
    ("八",     8,         0.90, "cardinal", False),
    ("九",     9,         0.95, "cardinal", False),
    ("十",     10,        1.00, "cardinal", False),
    ("半",     0.5,      -0.30, "cardinal", False),
    ("两三",   2.5,       0.40, "cardinal", False),
    ("三两",   2.5,       0.40, "cardinal", False),
    ("七八",   7.5,       0.88, "cardinal", False),
    # ── 基数词：十位 ────────────────────────────────────
    ("十二",   12,        1.08, "cardinal", False),
    ("十五",   15,        1.18, "cardinal", False),
    ("二十",   20,        1.30, "cardinal", False),
    ("二十四", 24,        1.38, "cardinal", False),
    ("三十",   30,        1.48, "cardinal", False),
    ("四十",   40,        1.60, "cardinal", False),
    ("五十",   50,        1.70, "cardinal", False),
    ("六十",   60,        1.78, "cardinal", False),
    ("七十",   70,        1.85, "cardinal", False),
    ("八十",   80,        1.90, "cardinal", False),
    ("九十",   90,        1.95, "cardinal", False),
    # ── 基数词：百及以上 ────────────────────────────────
    ("百",     100,       2.00, "cardinal", False),
    ("三百",   300,       2.48, "cardinal", False),
    ("五百",   500,       2.70, "cardinal", False),
    ("八百",   800,       2.90, "cardinal", False),
    ("千",     1000,      3.00, "cardinal", False),
    ("三千",   3000,      3.48, "cardinal", True),
    ("五千",   5000,      3.70, "cardinal", False),
    ("八千",   8000,      3.90, "cardinal", True),
    ("万",     10000,     4.00, "cardinal", False),
    ("十千",   10000,     4.00, "cardinal", True),
    ("九万",   90000,     4.95, "cardinal", True),
    ("四万八千", 48000,   4.68, "cardinal", True),
    ("十万",   100000,    5.00, "cardinal", False),
    ("百万",   1000000,   6.00, "cardinal", True),
    ("千万",   10000000,  7.00, "cardinal", True),
    ("亿",     100000000, 8.00, "cardinal", True),
    # ── 规模组合：数+长度量度 ──────────────────────────
    ("百尺",   100,   2.00, "measure", True),
    ("千尺",   1000,  3.00, "measure", True),
    ("三千尺", 3000,  3.48, "measure", True),
    ("百丈",   100,   2.00, "measure", True),
    ("千丈",   1000,  3.00, "measure", True),
    ("万丈",   10000, 4.00, "measure", True),
    ("三千丈", 3000,  3.48, "measure", True),
    ("千仞",   1000,  3.00, "measure", True),
    ("万仞",   10000, 4.00, "measure", True),
    ("五千仞", 5000,  3.70, "measure", True),
    ("百里",   100,   2.00, "measure", False),
    ("千里",   1000,  3.00, "measure", True),
    ("万里",   10000, 4.00, "measure", True),
    ("三千里", 3000,  3.48, "measure", True),
    ("三万里", 30000, 4.48, "measure", True),
    ("九万里", 90000, 4.95, "measure", True),
    # ── 规模组合：数+财货/器物/人马 ────────────────────
    ("千金",   1000,  3.00, "measure", True),
    ("万金",   10000, 4.00, "measure", True),
    ("千杯",   1000,  3.00, "measure", True),
    ("三百杯", 300,   2.48, "measure", True),
    ("百战",   100,   2.00, "measure", True),
    ("千军",   1000,  3.00, "measure", True),
    ("万马",   10000, 4.00, "measure", True),
    ("千骑",   1000,  3.00, "measure", True),
    ("万卷",   10000, 4.00, "measure", True),
    ("千呼",   1000,  3.00, "measure", True),
    ("万唤",   10000, 4.00, "measure", True),
    # ── 规模组合：数+层叠/景物 ─────────────────────────
    ("九重",   9,     0.95, "measure", True),
    ("千重",   1000,  3.00, "measure", True),
    ("万重",   10000, 4.00, "measure", True),
    ("千行",   1000,  3.00, "measure", True),
    ("千门",   1000,  3.00, "measure", True),
    ("万户",   10000, 4.00, "measure", True),
    ("千家",   1000,  3.00, "measure", True),
    ("千帆",   1000,  3.00, "measure", True),
    ("万木",   10000, 4.00, "measure", True),
    ("千山",   1000,  3.00, "measure", True),
    ("万径",   10000, 4.00, "measure", True),
    ("千树",   1000,  3.00, "measure", True),
    ("万树",   10000, 4.00, "measure", True),
    ("万条",   10000, 4.00, "measure", True),
    ("千岩",   1000,  3.00, "measure", True),
    ("万壑",   10000, 4.00, "measure", True),
    # ── 时间跨度 ────────────────────────────────────────
    ("百年",   100,   2.00, "time", False),
    ("千年",   1000,  3.00, "time", True),
    ("万年",   10000, 4.00, "time", True),
    ("千秋",   1000,  3.00, "time", True),
    ("千古",   1000,  3.00, "time", True),
    ("万古",   10000, 4.00, "time", True),
    ("万世",   10000, 4.00, "time", True),
    ("千载",   1000,  3.00, "time", True),
    ("百代",   100,   2.00, "time", True),
    ("三秋",   3,     0.48, "time", True),
    # ── 词汇化虚指 ──────────────────────────────────────
    ("万事",   10000, 4.00, "vague", False),
    ("万物",   10000, 4.00, "vague", False),
    ("四海",   4,     0.60, "vague", False),
    ("五湖",   5,     0.70, "vague", False),
    ("九州",   9,     0.95, "vague", False),
    ("九天",   9,     0.95, "vague", True),
    ("九霄",   9,     0.95, "vague", True),
    ("九泉",   9,     0.95, "vague", False),
    ("三军",   3,     0.48, "vague", False),
    ("六宫",   6,     0.78, "vague", False),
    ("百花",   100,   2.00, "vague", False),
    ("百草",   100,   2.00, "vague", False),
    # ── 弱数量："一"的量词性/副词性搭配 ────────────────
    ("一片",   1, 0.00, "weak", False),
    ("一声",   1, 0.00, "weak", False),
    ("一点",   1, 0.00, "weak", False),
    ("一时",   1, 0.00, "weak", False),
    ("一何",   1, 0.00, "weak", False),
    ("一任",   1, 0.00, "weak", False),
    ("一色",   1, 0.00, "weak", False),
    ("一自",   1, 0.00, "weak", False),
    ("一晌",   1, 0.00, "weak", False),
    ("一味",   1, 0.00, "weak", False),
    ("一番",   1, 0.00, "weak", False),
    ("一样",   1, 0.00, "weak", False),
    ("一般",   1, 0.00, "weak", False),
    ("一带",   1, 0.00, "weak", False),
    ("万一",   1, 0.00, "weak", False),
    # ── 序数/月份/更次/节令：不表数量 ──────────────────
    ("二月",   None, None, "ordinal", False),
    ("三月",   None, None, "ordinal", False),
    ("四月",   None, None, "ordinal", False),
    ("五月",   None, None, "ordinal", False),
    ("六月",   None, None, "ordinal", False),
    ("七月",   None, None, "ordinal", False),
    ("八月",   None, None, "ordinal", False),
    ("九月",   None, None, "ordinal", False),
    ("十月",   None, None, "ordinal", False),
    ("十一月", None, None, "ordinal", False),
    ("十二月", None, None, "ordinal", False),
    ("三更",   None, None, "ordinal", False),
    ("五更",   None, None, "ordinal", False),
    ("七夕",   None, None, "ordinal", False),
]

# 参与数量级统计（avg_magnitude）的类别；weak/ordinal 被排除
COUNTED_KINDS = {"cardinal", "measure", "time", "vague"}

# 词典允许的全部类别
VALID_KINDS = {"cardinal", "measure", "time", "vague", "weak", "ordinal"}


def words() -> list[str]:
    """全部词条，按词长从长到短排序（供贪心匹配使用）。"""
    return sorted({row[0] for row in NUMBER_DICT}, key=len, reverse=True)


def lookup(word: str):
    """按词查词条，返回 dict 或 None。"""
    for row in NUMBER_DICT:
        if row[0] == word:
            return dict(word=row[0], value=row[1], magnitude=row[2],
                        kind=row[3], is_hyperbole=row[4])
    return None


def as_table() -> dict:
    """词 -> 词条dict 的映射（扫描端一次构建，避免线性查找）。"""
    return {row[0]: dict(word=row[0], value=row[1], magnitude=row[2],
                         kind=row[3], is_hyperbole=row[4])
            for row in NUMBER_DICT}


if __name__ == "__main__":
    import math
    from collections import Counter

    errors = []
    seen = set()
    for word, value, mag, kind, hyp in NUMBER_DICT:
        if word in seen:
            errors.append(f"重复词条: {word}")
        seen.add(word)
        if kind not in VALID_KINDS:
            errors.append(f"非法类别: {word} -> {kind}")
        if kind == "ordinal":
            if value is not None or mag is not None:
                errors.append(f"序数词条应 value/magnitude=None: {word}")
            if hyp:
                errors.append(f"序数词条不应标夸张: {word}")
        else:
            if value is None or mag is None:
                errors.append(f"非序数词条缺 value/magnitude: {word}")
            elif abs(mag - math.log10(value)) > 0.02:
                errors.append(f"数量级与数值不符: {word} mag={mag} "
                              f"log10({value})={math.log10(value):.3f}")
        if kind == "weak":
            if mag != 0.0:
                errors.append(f"弱数量词条应 magnitude=0: {word}")
            if hyp:
                errors.append(f"弱数量词条不应标夸张: {word}")

    kinds = Counter(row[3] for row in NUMBER_DICT)
    n_hyp = sum(1 for row in NUMBER_DICT if row[4])
    print(f"词条总数: {len(NUMBER_DICT)}")
    print(f"类别分布: {dict(kinds)}")
    print(f"夸张词条数: {n_hyp}")

    for probe in ("三千丈", "九万里", "万里", "一片", "三月", "一", "亿"):
        print(f"lookup({probe!r}) = {lookup(probe)}")

    assert lookup("三千丈")["is_hyperbole"] is True
    assert lookup("一片")["kind"] == "weak"
    assert lookup("三月")["magnitude"] is None
    assert lookup("不存在") is None
    assert words()[0] == "四万八千"  # 最长词条优先匹配
    assert lookup("十千")["is_hyperbole"] is True

    if errors:
        print("\n自检失败:")
        for e in errors:
            print(" -", e)
        raise SystemExit(1)
    print("\n自检通过 OK")
