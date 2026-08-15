# 候选史料扩展：独立只读审计

- 审计日期：2026-08-09（Asia/Hong_Kong）
- 审计性质：候选层独立 QA；审计命令只写本报告
- 88 人名单口径：`data/poems.json` 的 88 个唯一 `poet`
- 审查对象：
  - `data/candidates/poet_journey_gap_backlog.json`
  - `data/candidates/manual_source_evidence_tang_zero_event.jsonl`
  - `data/candidates/manual_source_evidence_song_zero_event.jsonl`
  - `data/candidates/cbdb_event_coordinate_supplements.jsonl`
  - `tools/cbdb_coordinate_backfill.py`
  - `tools/check_cbdb_coordinate_backfill.py`
  - 对应 `docs/` 说明文件

## 1. 明确验收结论

**结论：有条件通过候选层验收。**

四份数据文件均可解析，名单、字段、等级、时间—地点共现、坐标直联、来源 URL 与受保护产物检查均通过；本批资料适合继续进入人工审核队列。它们仍是 `candidate` / `lead` / `needs_manual_review`，尚未达到自动并入 `data/reviewed/` 或直接生成确定路线的条件。

### 隔离边界说明

审计开始后发现前序“搜韵重试”后台采集进程仍存活，且另有第二个同类进程不在首个 PID 的子树内。两个进程树均已终止。第二个进程在完全隔离前于 23:13 刷新过以下既有聚合候选文件：`journey_event_candidates.jsonl`、`work_chronology_supplements.jsonl`、`journey_source_status.jsonl`、`journey_source_coverage.json`。这些文件不在本报告指定的四份新增资料清单内，本审计没有据此改写结论；因缺少可信的 23:13 前快照，也没有执行回滚。四份被审资料、相关工具/文档、`data/reviewed` 与正式 `output` 的审计前后哈希均保持一致。此项属于前序后台任务的并发写入记录，不是本批候选资料的数据缺陷。

发现 3 个需要后续修整的一致性问题，其中 1 个中等级、2 个低等级；均未造成候选事实被误写入审核层：

| ID | 等级 | 需修项目 | 影响 | 建议 |
|---|---|---|---|---|
| QA-01 | 中 | `poet_journey_gap_backlog.json` 是 22:05 的采集前快照，仍把 6 人写成 `locatable_events=0`；22:37 生成的坐标补充已为六人全部补到至少 1 条坐标，共 19 条 | 若前端或调度器只读 backlog，会把已部分解决的 P0 缺口继续显示为“零可定位” | 下一轮只在候选层重算 backlog，增加 `resolved_by_coordinate_supplement`、`remaining_unlocated`；当前仍有 11/30 条未补坐标 |
| QA-02 | 低 | 两份手工证据使用了两套同义状态：唐代 `clue_only`，宋代 `lead_only` | 统一导入时需要额外映射 | 统一为一个枚举，或在 schema 中声明二者映射 |
| QA-03 | 低 | 宋代文件中 `source_record_id` 有两组有意重复：同一墓表支持两个事件、同一论文支持事件与年代线索 | `source_record_id` 是引文标识，不是行标识；若被误作主键会碰撞 | 导入前增加确定性 `evidence_id`，或使用 `(poet, source_record_id, event_summary, candidate_status)` 复合键 |

在线抽查中另有 CText 403、上海图书馆 RDF 500/连接失败、MQWW 超时；本轮按原状态记录，没有追加请求规避。相关记录继续保留其 C/D 级或线索状态，待后续换时段/网络复核。

## 2. 文件指纹与解析

| 文件 | bytes | SHA-256 | 解析结果 |
|---|---:|---|---|
| `poet_journey_gap_backlog.json` | 43,992 | `83231930f45e51a448b8dbc35236e34a9fe86e1df1390be05264f60dfaa715a8` | JSON PASS |
| `manual_source_evidence_tang_zero_event.jsonl` | 19,803 | `f653c589a0a570c6d5823ea704f8cf5ea371c8f608c3ec0b9ffee2e2d8f2f8cd` | 22/22 行 PASS |
| `manual_source_evidence_song_zero_event.jsonl` | 16,389 | `c079b1ede4af319c56b80be66d7083b2a9f3b45ca0cc3581be08f48d21809007` | 19/19 行 PASS |
| `cbdb_event_coordinate_supplements.jsonl` | 16,635 | `fa1c7faaecc9fafd0de4ed495f70fed78b9c7f3f35881a40b6ed68c28446c8e7` | 19/19 行 PASS |

四份文件均为 UTF-8、无 BOM、末尾有换行。JSONL 每个物理行恰为一条合法 JSON。

## 3. 88 人名单、字段与唯一性

### 3.1 缺口 backlog

- `schema_version=1`，15 条 `entries`，诗人名唯一且全部属于 88 人名单。
- 分组严格为：9 人 `no_person_event` + 6 人 `has_person_event_but_no_locatable_event`。
- 15 条均为 `status=needs_manual_review`；没有 `event` / `events` 事实字段，未把推荐来源写成既成事实。
- 46 个 URL 字段均为格式完整的 `https://` URL。
- `event_snapshot` 自述时间为 21:50，文件生成时间为 22:05；因此 QA-01 按“历史快照与新补充尚未对账”处理，而不是把旧数值当作当前事实。

### 3.2 唐代手工证据

- 22 条、7 人全部属于 88 人名单：贺知章、张继、常建、祖咏、上官仪、张志和、聂夷中。
- 16 个字段逐行一致且完整；无完全重复行；`(poet, source_record_id, event_summary)` 无重复。
- 等级：B=14、C=7、D=1；均在 A–D 枚举内。
- 状态：`event_candidate=7`、`clue_only=12`、`needs_manual_review=3`。
- 常建四重同名风险显式记录为 CBDB `94489|147391|149973|163667`，D 级并阻止自动绑定；CText 指向 94489 仅保留为 crosswalk。
- 张继、祖咏、聂夷中的同名/地名映射/异文风险均写入 `identity_basis` 或 `notes`。

### 3.3 宋代手工证据

- 19 条、2 人（石延年、朱淑真）均属于 88 人名单。
- 16 个字段逐行一致且完整；无完全重复行；复合语义键唯一。
- 等级：A=5、B=3、C=8、D=3；均在 A–D 枚举内。
- 状态：`event_candidate=7`、`lead_only=12`。
- 朱淑真生卒、籍贯、家世与作品归属冲突均显式保留，没有选择某一说写成定论。
- 两组重复 `source_record_id` 均为同一文献支持不同证据项，属于引文复用；见 QA-03。

### 3.4 CBDB 坐标补充

- 19 条记录，`candidate_id` 19/19 唯一，`stable_link_key` 19/19 唯一。
- 六位诗人全部属于 88 人名单：卢纶 3、司空曙 1、李益 4、司马光 9、欧阳炯 1、钱惟演 1。
- 事实等级 B=12、C=7；坐标等级 A=17、B=2；全部落在 A–D 枚举。
- 经纬度均为有限数，范围：纬度 31.085796–39.876800，经度 105.71695709–120.61862183；无 `(0,0)`，无越界值。
- 19 条均满足：`coordinate_source_table=ADDR_CODES`、`coordinate_source_row_id == cbdb_addr_id`。

## 4. `event_candidate` 时间—地点与“伪路线”检查

两份手工证据合计 14 条 `event_candidate`，每条都同时具有非空 `time_expression` 与 `place_expression`；等级分布为 A=4、B=7、C=3。

| 诗人 | 事件候选数 | 关键审计结论 |
|---|---:|---|
| 贺知章 | 2 | 归乡与东岳封禅均在《旧唐书》同一人物传内有时间和地点指向；“乡里→会稽永兴”属于传内指代解析，已在 notes 提醒展示层不要伪装成原句直书 |
| 张继 | 1 | “大历末—洪州”同条共现 |
| 常建 | 1 | “大历中—盱眙尉”同条共现；人物 ID 继续处于四重同名消歧状态 |
| 祖咏 | 1 | “开元十三年—汝坟别业”同一 authority 记录共现；现代落点冲突已显式保留，坐标应留空 |
| 张志和 | 1 | “大历九年秋八月—湖州/苕霅”碑铭同段共现 |
| 聂夷中 | 1 | “咸通中—华阴尉”同条共现；871 登第年没有被拼作任职年 |
| 石延年 | 6 | 墓表、编年、正史、方志各自独立给出时地；“河东”两条是同一任务簇的多源证据，文档已声明去重关系 |
| 朱淑真 | 1 | 1138 年以后临安西湖属于论文基于诗群的推定，C 级且明确待审 |

对 41 条手工证据的 `event_summary`、`notes`、`identity_basis` 复核后，以下项目均保持为线索而未拼成路线：籍贯/基本地址、出生或卒年字段、父亲任官地、辑者/传记作者所在地、身后致祭、版本流转地点、仅有官名而无同条时间的记录。唐代上官仪只有死亡时间而无事件地点，因此保持 `clue_only`；宋代朱淑真的钱塘/盐官/歙州等说均保持 `lead_only`。

## 5. 坐标直接关联与工具审计

### 5.1 独立数据库复核

对 19 条坐标补充逐条回查：

1. `candidate_id` 在 `journey_event_candidates.jsonl` 中 19/19 命中；
2. 原候选 `cbdb_addr_id` 与补充记录 19/19 一致；
3. 以只读 SQLite 打开 `.cache/background_sources/cbdb/latest.sqlite3`；
4. 按 `cbdb_addr_id = ADDR_CODES.c_addr_id` 查询；
5. 地名、经纬度、`CHGIS_PT_ID`、有效年代区间 19/19 一致，无时间区间脱节。

数据库 SHA-256 为：

`ec0be08186722c53f77f47f4513239afd6a505f8157994cc72b9fbd49c6fc21a`

与 19 条补充记录及报告声明一致。

### 5.2 工具实现

`tools/cbdb_coordinate_backfill.py` 明确使用 SQLite URI `mode=ro`、`PRAGMA query_only=ON` 和显式事务；查询仅使用 `ADDR_CODES`，检查有限数、经纬度范围、`(0,0)` 哨兵、历史地名一致性和有效年代交集。代码与文档均明确排除出生地、索引地址、上级行政区、现代代表城市等替代推断。

运行 `python tools/check_cbdb_coordinate_backfill.py`：

```text
integration passed: targets=30, success=19, failures=11, A=17/B=2
cbdb_coordinate_backfill checks passed
```

检查脚本覆盖：直接关联、超界/非有限值、`(0,0)`、无坐标、只读输入不变、别名/同文件保护、候选 ID 与关联键冲突等负例。

## 6. 来源 URL 格式与联网低频抽查

### 6.1 格式

- backlog 46 个 URL 字段、两份手工证据 41 个 URL、坐标补充 19 个 URL，共 106 个 URL 字段。
- 106/106 均可由 URL 解析器识别为带主机名的 `https` URL；没有空 URL、相对 URL 或明文 HTTP。

### 6.2 联网抽查

采用低频 HEAD；服务器不支持 HEAD 时改用 GET。403/500/超时仅记录。抽查超过 12 条，核心结果如下：

| 诗人/对象 | 记录 | URL | 结果 | 内容相关性 |
|---|---|---|---|---|
| 贺知章 | CBDB 15353 | <https://cbdb.fas.harvard.edu/cbdbapi/person.php?id=0015353> | 200 | 人物页存在；JSON 模式可核对贺知章 |
| 贺知章 | DILA A008710 | <https://authority.dila.edu.tw/person/search.php?aid=A008710> | 200 | 标题及正文命中賀知章 |
| 贺知章 | 《旧唐书》卷190中 | <https://zh.wikisource.org/wiki/舊唐書/卷190中> | 200 | 命中贺知章、开元十三年封岳、天宝三载归乡 |
| 张继 | 《全唐诗》卷242 | <https://zh.wikisource.org/wiki/全唐詩/卷242> | 200 | 正文命中張繼 |
| 常建 | CText DataWiki 3879813 | <https://ctext.org/datawiki.pl?if=gb&remap=gb&res=3879813> | 403 | 当前未在线确认；按规则记录，没有追加规避请求 |
| 常建 | CText《常建诗》 | <https://ctext.org/wiki.pl?chapter=2670339&if=gb&remap=gb> | 403 | 当前未在线确认 |
| 张志和 | 《全唐文》卷340 | <https://zh.wikisource.org/wiki/全唐文/卷0340> | 200 | 命中“元真子張志和”及大历九年湖州段 |
| 张志和 | DILA 苕霅 | <https://authority.dila.edu.tw/place/search.php?code=PLG00000000083> | 200 | 命中苕溪、霅溪及湖州说明 |
| 石延年 | 《石曼卿墓表》 | <https://zh.wikisource.org/wiki/石曼卿墓表> | 200 | 命中卒于京师、葬太清、通判海州等原文 |
| 石延年 | 《续资治通鉴长编》卷116 | <https://zh.wikisource.org/wiki/續資治通鑑長編_(四庫全書本)/卷116> | 200 | 命中石延年落职通判海州 |
| 石延年 | 《续资治通鉴长编》卷127 | <https://zh.wikisource.org/wiki/續資治通鑑長編_(四庫全書本)/卷127> | 200 | 页面存在；卷次匹配 |
| 石延年 | 《宋史》卷442 | <https://zh.wikisource.org/wiki/宋史/卷442> | 200 | 正文命中石延年 |
| 石延年 | CBDB 22278 JSON | <https://cbdb.fas.harvard.edu/cbdbapi/person?id=22278&mode=json> | 200 | `ChName` 解码为石延年，基本地址宋城 |
| 石延年 | 上海图书馆 RDF | <https://data.library.sh.cn/entity/person/t8xysg5dpoca91sx.ntriples> | 连接失败 | 当前未在线确认；保留 C 级线索 |
| 朱淑真 | MQWW 2163 | <https://mhdb.mh.sinica.edu.tw/mingqing/mqww/search/details-poet.php?language=eng&poetID=2163> | 两次 60 秒超时 | 当前未在线确认；建议异地复核 |
| 朱淑真 | 上海图书馆 RDF | <https://data.library.sh.cn/entity/person/1eenywu8eeyrm8ar.ntriples> | 500 | 服务端错误，保持 D 级线索 |
| 朱淑真 | 缪钺论文 | <https://journal.scu.edu.cn/info/1109/14831.htm> | 200 | 标题、作者、期次、摘要及 1138 年以后西湖论证均匹配 |
| 朱淑真 | 中研院《断肠词》 | <https://ascdc.digitalarchives.tw/collection_8433779.html> | HEAD 400，GET 200 | GET 命中题名、作者与识别号 2116 |
| 朱淑真 | 《四库提要》卷199 | <https://zh.wikisource.org/wiki/四庫全書總目提要/卷199> | 200 | 正文命中《断肠词》条 |
| 司马光 | CBDB 1488 JSON | <https://cbdb.fas.harvard.edu/cbdbapi/person?id=1488&mode=json> | 200 | 坐标补充所用人物 URL 模式有效 |

未见 404。CText 共 7 条在当前网络表现为 403/连接波动；MQWW 1 条超时；上海图书馆 RDF 2 条为连接失败/500。这些访问结果不等于史料内容为假，只表示本轮在线复核证据不足，继续按低等级候选管理。

## 7. `data/reviewed` 基线复核

基线：`tmp/reviewed_baseline_20260809.json`。

- 当前 `data/reviewed` 恰有 10 个文件；文件名集合与基线完全一致，无缺失、无新增。
- 10/10 的 bytes 与逐文件 SHA-256 均与基线一致。
- 按基线文件顺序计算 `SHA256(filename_utf8 || file_bytes ...)`，复算树哈希：

`be88e94140df4acca6b668988af52082eb2b0617e8ba1d3748b2a095e7662744`

与基线 `tree_sha256` 完全一致。**`data/reviewed` 本轮保持不变。**

## 8. 正式 29–38 HTML 对 manifest 复核

`output/manifest.json` 中正式 29–38 页共 10 个；逐页 bytes 与 SHA-256 全部匹配：

| 页面 | bytes | SHA-256 | 结果 |
|---|---:|---|---|
| `29_参赛导航.html` | 8,116 | `eb62c274f0cffd42654ba1025cf8b56a4471c5bb6387a720db53b590a35c1a2e` | PASS |
| `30_诗行万里_参赛版.html` | 320,840 | `332e7c609525b060a20f21ce2660899d7fee440a48eb89d0884cc10ba2985fcc` | PASS |
| `31_凝望罗盘.html` | 195,613 | `f95a996189da61b9b60e73ab8885ae364a640729c74284879d6341df9ca451aa` | PASS |
| `32_身与心双层地图.html` | 158,166 | `5d3acc40a57e9345e31fd952839b2b760e19371a135b62f406cf6c3f3390e5ba` | PASS |
| `33_平行时空759.html` | 485,334 | `6d02b53eca42683b4eca8b55202adc6b9d33ebfa854c661676e64447fde8806f` | PASS |
| `34_一字识诗人.html` | 97,789 | `336babae3ee4e11a58a8b7bd41127de99d562d1806ce9bfe97052538a98f9d32` | PASS |
| `35_两种孤独与夸张签名.html` | 63,664 | `02ceabe39f71762d109b2b5944f96b02f0f863cde0af1dad0e5ecd2289d55176` | PASS |
| `36_同龄对齐.html` | 171,265 | `61158cc2ae8edb6eae68d5c3ca0ede655147da7fa7497bdba2efff35554567d2` | PASS |
| `37_可听的诗.html` | 94,186 | `cec31553606522e3e79a037464963243dd8d6ae3736a1826168af2e5bea653cc` | PASS |
| `38_唐宋意象潮汐.html` | 587,651 | `d00b96f5585b222db930032cd4afd45249f031ecce516ee8f9bc415207a53fe1` | PASS |

另发现 `output/33_平行时空759_codex_backup.html` 未列入 manifest；它与正式 33 页 bytes、SHA-256 完全相同，是内容一致的备份观察项，不构成正式产物差异。

## 9. 最终判定与准入条件

### PASS

- JSON/JSONL 解析、UTF-8、字段完整性。
- 88 人名单约束与诗人唯一性。
- A–D 等级枚举。
- 14/14 `event_candidate` 同时具有时间和地点。
- 同名、地名与生卒争议显式保留。
- 未把籍贯、生卒、父亲任官地、辑者所在地等拼成路线。
- 19/19 坐标由 `cbdb_addr_id` 直接关联 `ADDR_CODES.c_addr_id`，数值有限且在合法范围。
- 106/106 来源 URL 格式合法；联网抽查覆盖超过 12 条，受限响应如实记录。
- `data/reviewed` 清单、bytes、逐文件哈希与树哈希保持基线一致。
- 正式 29–38 HTML 10/10 与 manifest 一致。

### 进入下一阶段前需修

1. 按坐标补充重算 backlog 的“已解决/仍未解决”数量（QA-01）。
2. 统一 `clue_only` / `lead_only` 状态字典（QA-02）。
3. 为手工证据增加行级稳定 ID，避免把 `source_record_id` 误用为主键（QA-03）。
4. CText、MQWW、上海图书馆 RDF 的当前受限链接继续停留在线索层；复核成功前不提升等级。

**最终验收意见：候选资料扩展通过“候选层有条件验收”；修复 QA-01 后可进入批量人工审核编排，QA-02/03 宜在正式导入统一 schema 前完成。**

## 10. 控制器复核更新（2026-08-10）

上述三项结构性修整均已完成：

1. backlog 已对账 19 条 `ADDR_CODES` 直接坐标补充，六位 P0 诗人的缺口更新为
   `has_unresolved_person_event_coordinates`；30 条既有事件中仍有 11 条待定位。
2. `lead_only` 已统一为 `clue_only`；保留 3 条 `needs_manual_review` 用于同名或证据边界审查。
3. 两份人工证据 JSONL 的 41 行均新增稳定、唯一、可复算的 `evidence_id`。

搜韵尾批次随后恢复并完成，瞬时失败为 0；DILA 88 人顺序采集也已完成（64 唯一匹配、3 歧义、
21 未命中）。`python tools/check_all.py --offline --keep-going` 的 15 项检查全部通过，最终候选层
验收结论更新为 **PASS**。`data/reviewed` 与正式 29–38 页面仍保持基线哈希不变。
