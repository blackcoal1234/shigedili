# data/stylometry/ — 风格计量（stylometry）四维度

对著名诗人语料做四个维度的文体统计：
色彩、数字夸张、人称孤独、声音。每个维度三件套：人工词典（`.py`）、
扫描脚本（`scan_*.py`）、统计结果（`*_stats.json`）。

统计采用双语料层：默认优先读取 `analysis_full`（
`data/analysis/famous_poets_full.jsonl.gz`）作为全作品分析层；文件缺失时自动
回退 `canonical`（`data/poems.json`）。语料规模由每次 loader 返回结果动态决定，
输出中的 `generated_from_poems` 是实际扫描首数，不应写死。页面展示、事实卡与
赏析内容仍使用 canonical 语料，不随统计分析层切换。

身份规则与展示文本一致：canonical 正文已经是规范文本，只做换行、NFC 与首尾
空白规范化后生成 `normalized_body_hash` / `work_id`；不得再次经过 OpenCC。
上游繁简文本仍以 OpenCC `t2s` 结果作为分析正文，并用独立的
`dedupe_body_hash` 查找去重候选。即使多个 canonical 正文被 OpenCC 折叠为同一
候选键，也会保留各自的 `source_poem_id`、`canonical_gushiwen_id` 与 `work_id`，
不会据此合并真实作品。loader 当前返回物化后的 `list`，尚未改为流式接口。

> 诚实边界：四套词典均为本课程项目**人工整理的分析工具**，词条取舍口径写在
> 各词典文件 docstring 里；不是权威词库，一切统计结论只在各自口径内成立。

## 目录

| 维度 | 词典 | 词条数 | 扫描脚本 | 统计输出 |
|---|---|---|---|---|
| 色彩（人生调色盘） | `color_dict.py` | 61（另 21 个屏蔽词） | `scan_color.py` | `color_stats.json` |
| 数字夸张（李白夸张系数） | `number_dict.py` | 137 | `scan_number.py` | `number_stats.json` |
| 人称孤独（独白/对话型） | `solitude_dict.py` | 73 | `scan_solitude.py` | `solitude_stats.json` |
| 声音（可听见的诗） | `sound_dict.py` | 88（另 7 个屏蔽片段） | `scan_sound.py` | `sound_stats.json` |

## 四套词典口径（摘要，详见各文件 docstring）

- **色彩** `color_dict.py`：只收"显式色词"（白/朱/惨绿/鹅黄……），不收
  强色彩联想物（霜、雪、血不算色词）；金、银按材质自带色泽收入"金银"系。
  每词标注：色系（8 系）、近似 hex（手工调和，仅供可视化）、明度三档（亮/中/暗）。
  `EXCLUDE_WORDS` 在匹配前屏蔽高频歧义词：地名（金陵/白帝/蓝田）、人名
  （李白/白傅/杨朱/朱亥/丹丘）、时间（黄昏）、幽冥（黄泉）、绘画（丹青）、
  钱财（千金/万金）、金属义（金石）等。
- **数字夸张** `number_dict.py`：数词 → 近似数值 + 数量级 log10 + 六类
  （cardinal 基数 / measure 规模组合 / time 时间跨度 / vague 词汇化虚指 /
  weak 弱数量"一片一声" / ordinal 序数月份）。weak 与 ordinal 不入命中数与
  数量级统计。夸张标记从严：只标"大数×度量/时间/景物"经典组合与虚指大数，
  裸数词一律不标——夸张密度因此是**保守下界**。
- **人称孤独** `solitude_dict.py`：三类——孤独（独酌/孤灯/寂寞/无人……）、
  自称（我/吾/余/此身……）、他称（君/汝/故人/客……）。每词带 [0,1] 强度，
  多义字按"宁低勿高"打低权重（"空"0.25、"自"0.15）。自称/他称之比区分
  "独白型/对话型"诗人。
- **声音** `sound_dict.py`：只收"通常作为被听见的声音出现"的词——声音源
  （猿声/钟/砧/羌笛……）与拟声/听觉动词（啼/萧萧/滴/咽……），六类：
  兽鸣/鸟啼/器乐/钟磬/自然声/人声；每词带 [-1,1] 情感倾向人工标注。
  `EXCLUDE_PATTERNS` 先挖除已知误报（萧瑟、半江瑟瑟、杜鹃花、钟山、钟情等）。

四个扫描端统一采用**最长优先、不重叠**贪心匹配（"三千丈"只计 1 次，不再拆
"三千"+"千"；"猿声"不再重复计"猿"），色彩/声音维度在匹配前先屏蔽各自的
歧义词/误报片段。

## 统计 JSON 统一结构

```jsonc
{
  "schema_version": 1,
  "corpus_source": "analysis_full", // 或 "canonical"
  "corpus_path": "data/analysis/famous_poets_full.jsonl.gz",
  "dict_size": 61,                  // 该维度词典词条数
  "generated_from_poems": 80893,    // 当前示例；以实际动态规模为准
  "per_poet": {                     // 覆盖本次语料内全部诗人
    "李白": {
      "poem_count": 55,
      "hits_total": 131,
      "hits_per_100_chars": 1.83,   // 分母=正文 CJK 汉字数，标点换行不计
      "top_words": [["青", 27], ["白", 22]],
      // …… 维度特有字段，见下
    }
  },
  "per_poem": [                     // 每首诗的命中明细
    {"title": "望庐山瀑布", "poet": "李白",
     "work_id": "fw_…", "canonical_gushiwen_id": "…",
     "body_hash": "…", "hits": [["紫", 1], ["银", 1]]}
  ]
}
```

各维度 per_poet 特有字段：

- 色彩：`color_families`（8 系占比）、`palette`（频次加权前 8 色值）、
  `bright_dark_ratio`（(亮+1)/(暗+1)）、`bright_mid_dark`。
- 数字：`avg_magnitude`（平均数量级）、`hyperbole_hits` /
  `hyperbole_per_100_chars`（夸张密度）、`weak_hits`、`ordinal_hits`、
  `max_expressions`（数量级最高的原句摘录前 5）。
- 孤独：`category_counts`（孤独/自称/他称）、`solitude_per_100_chars`、
  `solitude_weighted_per_100_chars`（按强度加权）、`self_other_ratio`
  （自称/他称，高=独白型）、`top_solitude_lines`（孤独密度最高诗句前 5）。
- 声音：`sound_categories`（六类占比）、`soundscape_signature`
  （标志性声音：次数×lift 前 6）、`quiet_ratio`（全诗无声音词的诗占比）。

个别文件的少量额外顶层字段（`headline`、`generated_at`、`dimension`、
`corpus_top_words`）为维度自身附加信息，不影响统一结构。

## 复跑方法

语料更新后，在项目根目录逐个重跑即可刷新统计与情感档案：

```
python data/stylometry/scan_color.py
python data/stylometry/scan_number.py
python data/stylometry/scan_solitude.py
python data/stylometry/scan_sound.py
python tools/build_emotion_profiles.py
```

- **语料选择**：上述命令统一调用 `load_analysis_poems()`；全作品文件存在时
  使用 `analysis_full`，否则自动使用 `canonical`。实际来源和路径记录在输出的
  `corpus_source` / `corpus_path`。
- **幂等**：同一语料重跑输出逐字节一致（`number_stats.json` 仅
  `generated_at` 时间戳会变化），已实测验证。
- 词典自检：`python data/stylometry/color_dict.py`（其余三个同理），
  自检失败会以非零退出码报错。Windows 控制台建议
  `PYTHONIOENCODING=utf-8` 运行以正常显示中文输出。

## 已知局限

1. **单字色词无法逐一消歧**：素=平素、青=青史、苍=苍茫等语境中色感衰减，
   色彩词典取"视觉色感仍在场"的宽口径并在 docstring 声明。
2. **人名/地名屏蔽是清单式的，不能穷尽**。已屏蔽语料中实际出现的人名
   （李白/白傅/杨朱/朱亥/丹丘）；含色字的**地名**（青海/赤壁/金谷/苍梧/
   黄州等）因传统上仍带色感或频次极低而未屏蔽，按宽口径计入。顿号隔开的
   枚举（"金、石、丝、竹"）无法被"金石"屏蔽词覆盖，散文语料中有个位数残留。
3. **语料含少量散文**（《送孟东野序》《赤壁赋》等），数字词典按诗歌修辞口径
   标夸张，落在纪实散文上会有少量误标（docstring 已声明）。
4. **数字"数+月"一律按月份序数排除**，"烽火连三月"（三个月之久）这类会被
   牺牲；"一"的量词用法只列了 15 个高频搭配，未列入的"一X"仍按基数词计。
5. **孤独维度多义字靠低权重而非消歧**："自"（自古/自从）、"空"（空中/晴空）
   仍会计入孤独类命中（低强度），`solitude_per_100_chars` 会略高于真值，
   加权版 `solitude_weighted_per_100_chars` 更接近真实浓度；"郎/君/卿"含
   第三人称专名用法（周郎/刘郎），按口径仍计他称。
6. **声音泛用动词归类近似**："啼/鸣/噪"统一归"鸟啼"类，实际也覆盖猿啼、
   蝉鸣（长词优先已减少大部分误差）；情感倾向为人工标注，仅供可视化。
7. **小样本诗人**（个别诗人仅数首诗）密度类指标波动大，比较时请结合
   `poem_count` / `chars_total` 自行设样本门槛（数字维度 headline 用的是
   正文≥300 字）。

## 质检记录（2026-07-26）

- 2026-08-24：将 canonical 身份输入从 OpenCC `t2s` 结果改为规范展示正文；
  20,437 个 `source_poem_id` 均能在 full 中唯一回配相同 `work_id`。原先被
  OpenCC 折叠的 19 组 canonical 正文现分别保留；当前分析层为 80,893 条。

- 修复 `color_dict.py` 自检在 Windows GBK 控制台因"✓"字符崩溃的问题
  （改为 stdout 重配 UTF-8 + ASCII 结语）。
- 发现并修复系统性误匹配：正文中的人名"李白"（韩愈《送孟东野序》、程颢
  《秋日偶成》、李白《赠汪伦》共 3 处）、"白傅""杨朱""朱亥"被"白/朱"
  当作色彩词命中；金属义"金石"被"金"命中。均已加入 `EXCLUDE_WORDS`
  并重新生成 `color_stats.json`。
- 四份 stats JSON 结构校验通过（schema_version=1，per_poet 覆盖本次语料内
  全部诗人，per_poem 与动态语料规模一一对应）；四个词典自检通过；四个扫描
  脚本重跑验证幂等。
- 每维度抽 3 首名篇人工核对命中与原文一致（如《暮江吟》"半江瑟瑟"未被
  声音维度误计乐器"瑟"、《早发白帝城》"白帝"未被计入色彩）。
