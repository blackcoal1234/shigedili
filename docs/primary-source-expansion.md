# 六位作家史料扩展路线图

> 范围：李白、杜甫、白居易、苏轼、陆游、李清照。  
> 目标：以可追溯的原始文本和学术权威资料补充人物行旅、作品编年与出处；所有机器抽取结果先作为 assertion（待核断言），不直接写入既成事实。  
> 原则：来源分层、逐条留证、许可随记录保存；“人物在某地”“作品提到某地”“作品写于某地”是三种不同断言，不得相互替代。

## 1. 优先级总览

| 优先级 | 工作包 | 主要来源 | 采集方式 | 输出 |
|---|---|---|---|---|
| P0 | 建立可复核文本与时间骨架 | Kanripo、CBDB、DILA 时间权威资料库 | 自动采集公开 API/数据包；限制频率并固定版本 | 人物、文本、日期和出处注册表；未经裁决的候选断言 |
| P1 | 地名解析和履历交叉核验 | CHGIS、中研院人名权威库 | CHGIS 仅在许可范围内自动用于内部解析；中研院页面只做人工/少量核验 | 历史地名候选、任官/迁徙证据、冲突清单 |
| P2 | 作品编年与创作地人工裁决 | 唐宋文学编年地图、Scripta Sinica、校注本/年谱 | 人工核验；取得明确许可后才接入结构化数据 | 经审定断言、争议断言、否定断言及完整引证链 |

## 2. P0：可立即执行的自动化骨架

### 2.1 Kanripo 文本注册表

API 文档：<https://www.kanripo.org/api>。Kanripo 页面文本标示 CC BY-SA；入库时必须保存 KR 编号、版本/edition、卷次、文本定位符、抓取时间和许可证。自动处理只生成日期、地点、人物和作品关系的**候选断言**。

| 人物 | KR 编号 | 文本 | Exact URL | 自动处理重点 |
|---|---|---|---|---|
| 李白 | `KR4c0014` | 《李太白集注》 | <https://www.kanripo.org/text/KR4c0014/> | 序跋、题注、自注中的日期/地点；作品标题和卷次 |
| 杜甫 | `KR4c0018` | 《集千家注杜工部诗集》 | <https://www.kanripo.org/text/KR4c0018/> | 纪行编排、题注与注家系年；区分原文和后出注释 |
| 白居易 | `KR4c0069` | 《白氏长庆集》 | <https://www.kanripo.org/text/KR4c0069/000> | 明示年月的序、书、诗题和自注；官地与游地分开建模 |
| 苏轼 | `KR4d0076` | 《东坡全集》 | <https://www.kanripo.org/text/KR4d0076/> | 优先处理所收年谱、序跋和书札，再关联作品 |
| 陆游 | `KR2g0056` | 《入蜀记》 | <https://www.kanripo.org/text/KR2g0056/> | 按日切分旅程事件，提取启程/抵达/停泊/住宿地点及原纪年 |
| 陆游 | `KR4d0267` | 《剑南诗稿》 | <https://www.kanripo.org/text/KR4d0267/000> | 题注、自注、卷序和显式纪年；生成作品编年候选 |
| 陆游 | `KR4d0268` | 《渭南文集》 | <https://www.kanripo.org/text/KR4d0268/> | 书札、记、序、墓志中的履历与时间证据 |
| 李清照 | — | 暂无已核实、可作为其专属文集底本的 Kanripo KR 编号 | 检索/接口入口：<https://www.kanripo.org/api> | 不虚构编号；其他文献中对李清照的提及只登记为旁证，作品正文与年谱转入 P2 人工校核 |

#### 自动处理步骤

1. 按上述固定 KR 编号读取目录、版本和卷次元数据，不按作者名进行无边界爬取。
2. 保存原始定位：`kr_id + edition + juan + section/line`；正文只保存必要的短证据摘录和稳定定位。
3. 识别年号、干支、月日、地名、移动动词及作品标题，生成 `candidate` assertion。
4. 将“文本中提到地点”默认标为 `place_mentioned`，不得自动提升为 `person_present_at` 或 `work_composed_at`。
5. 同一段中的日期与地点只有在语法关系明确时才建立弱关联；跨段或仅凭相邻顺序产生的关联标为推断级。

#### P0 验收标准

- 每条候选均可回到 exact URL 和卷/段定位；
- 原文、注释、序跋和后人年谱具有不同的 `source_layer`；
- 任一自动抽取均未以 `confirmed` 状态写入；
- 李清照没有被分配未经核实的 KR 编号。

### 2.2 CBDB 人物与结构化履历骨架

- API 文档：<https://input.cbdb.fas.harvard.edu/cbdbapi/index.html>
- SQLite 下载说明：<https://cbdb.hsites.harvard.edu/download-cbdb-standalone-database>
- 六人 ID：李白 `32540`、杜甫 `3915`、白居易 `32227`、苏轼 `3767`、陆游 `3640`、李清照 `19713`。
- 许可：CC BY-NC-SA 4.0；须署名、非商业、相同方式共享。

自动接入 `BasicInfo`、`PersonAddresses`、`PersonPostings`、`PersonTexts` 和条目来源，用作人物消歧及履历候选。按记录过滤来源：百科导入、Wikidata 和“未知”不进入已核事实层。陆游的 CBDB 地址覆盖较弱，李清照迁徙记录存在出处缺口和年代争议，两者均须进入人工复核队列。

### 2.3 DILA 时间规范

- 项目/API：<https://authority.dila.edu.tw/>
- 开放内容与下载：<https://ybh.chibs.edu.tw/docs/open_content/download.php>
- 许可：CC BY-SA 2.5 Taiwan。

执行规则：

1. 永久保存 `date_original`，例如“绍兴二年三月”。
2. 用 DILA 映射朝代、帝王、年号、年/月/日和公历范围，保存 DILA 记录 ID/版本。
3. 精度只到年时，`date_start`/`date_end` 表示该年范围，`date_precision=year`；不得补造月日。
4. 模糊词（春、岁暮、某日前后）保留原文，采用范围和 `circa=true`。
5. 转换失败、异历冲突或文本异文进入 `needs_review`，不得默认取最早或最晚日期。

## 3. P1：地名解析与权威履历复核

### 3.1 CHGIS 历史地名解析

- V6 数据页：<https://chgis.fas.harvard.edu/data/chgis/v6/>
- 哈佛项目页：<https://gis.harvard.edu/china-historical-gis>
- 复旦下载说明：<https://yugong.fudan.edu.cn/CHGIS/sjxz.htm>
- 使用条件：<https://yugong.fudan.edu.cn/CHGIS/bqsm.htm>

角色：将原文州、府、县、驿、山川等名称解析为具有有效年代、行政层级和坐标的历史地点候选。CHGIS 不提供人物行旅或作品创作事实。

许可风险：CHGIS 面向非商业学术/教育用途，含禁止转售或第三方再分发等限制，某些使用场景需另行取得许可。因此：

- 可在许可范围内自动用于内部地名匹配和地图计算；
- 对外数据只保存允许公开的标识符、匹配说明和自有断言，不随项目重新分发 CHGIS 图层或数据包；
- 每次发布前单独检查使用地区、用途和再分发条款；
- 无法唯一匹配时保留多个 `place_candidate`，由人工结合事件年份和上下文裁决。

解析顺序：原地名精确匹配 → 事件年份过滤有效期 → 上下级行政区约束 → 相邻行程约束。相邻行程只能帮助排序候选，不能单独证明地点。

### 3.2 中研院人名权威库

重点人物页：

- 陆游 `018485`：<https://newarchive.ihp.sinica.edu.tw/sncaccgi/sncacFtp?ACTION=TQ%2CsncacFtpqf%2CSN%3D018485%2C2nd%2Csearch_simple>
- 李清照 `018180`：<https://newarchive.ihp.sinica.edu.tw/sncaccgi/sncacFtp?ACTION=TQ%2CsncacFtpqf%2CSN%3D018180%2C2nd%2Csearch_simple>
- 苏轼 `018284`：<https://newarchive.ihp.sinica.edu.tw/sncaccgi/sncacFtp?ACTION=TQ%2CsncacFtpqf%2CSN%3D018284%2C2nd%2Csearch_simple>

角色：

- 人名、字、号、生卒、籍贯消歧；
- 用条目级来源核对任官履历和著述；
- 陆游页用于补 CBDB 中缺失的任官年代和地点；
- 李清照页用于登记生卒、籍贯和著述争议，而非直接覆盖其他来源。

采集边界与许可风险：页面可普通 GET 访问，但未找到人物数据库专属的公开批量 API 或明确的数据集再利用许可证。中研院的一般网站开放声明见 <https://www.sinica.edu.tw/cp/85>，不能据此推定整个人名权威库可批量复制或再分发。当前只做人工或少量页面核验，保存权威号、条目来源和页面 URL；系统化采集前须向史语所确认许可。

## 4. P2：人工裁决与条件性来源

### 4.1 唐宋文学编年地图

- 项目证据：<https://www.neac.gov.cn/seac/xwzx/201905/1133494.shtml>
- 地图入口：<https://cnkgraph.com/Map/PoetLife>
- 数据展示：<https://www.ditushu.com/book/27/>
- 搜韵作品接口说明：<https://opendata.library.sh.cn/2022/download/opendata/2022/%E6%90%9C%E9%9F%B5%E5%BC%80%E6%94%BE%E6%8E%A5%E5%8F%A3%E8%AF%B4%E6%98%8E%E6%96%87%E6%A1%A3.pdf>

该项目最接近“人物—年份—地点—作品”目标，但编年地图当前有登录/限流，且未找到明确的数据集开放许可证。搜韵公开作品 API 提供作者、标题、正文、注释和出处等字段，不代表编年地图的年份、地点和路线数据同样开放。现阶段只人工核验；取得项目方明确的数据授权、版本和导出格式后，再单独设计自动接入。

### 4.2 Scripta Sinica 与校注本/年谱

- Scripta Sinica：<https://hanchi.ihp.sinica.edu.tw/ihp/hanji.htm>

用于复核《宋史》、笔记、地方志、书目提要及传记材料。该站未提供适合本项目的公共批量 API，故只人工检索并记录篇名、卷次、页码/定位。李清照的生卒、出生地/籍贯、南渡路线和作品归属，以及陆游诗文系年冲突，必须在此阶段形成“支持—反对—未决”证据组。

## 5. Assertion schema

建议每个来源断言独立成行；不同来源不得提前合并：

```yaml
assertion_id: string
subject_person_id: string          # 项目内部 ID
subject_authority_ids:
  cbdb: string|null
  ihp: string|null
claim_type: enum                   # person_present_at / office_held_at /
                                   # work_mentions_place / work_composed_at /
                                   # work_dated_to / work_authorship
work_id: string|null
work_title_original: string|null
event_type: string|null

date_original: string|null
calendar_system: string|null
date_start: date|null
date_end: date|null
date_precision: enum               # day / month / season / year / range / unknown
circa: boolean
dila_record_id: string|null

place_original: string|null
place_candidate_ids: [string]
place_resolved_id: string|null
place_resolution_status: enum      # unresolved / candidate / reviewed
place_resolution_note: string|null

source_system: string
source_layer: enum                 # primary_text / contemporary_record /
                                   # later_annotation / chronology /
                                   # authority_database / derived
source_record_id: string|null
kr_id: string|null
edition: string|null
juan: string|null
locator: string                    # 页、卷、段或稳定行号
source_url: uri
evidence_excerpt: string|null      # 仅必要短摘录
evidence_level: enum               # E1-E5，见下节
derivation_method: enum            # manual / rule / ner / imported

assertion_status: enum             # candidate / confirmed / disputed /
                                   # rejected / needs_review
supports_assertion_ids: [string]
conflicts_with_assertion_ids: [string]
reviewer: string|null
reviewed_at: datetime|null

license_id: string|null
license_url: uri|null
retrieved_at: datetime
source_version_or_hash: string|null
```

`work_composed_at` 必须是独立断言。人物某日出现在某地、诗题含地名、诗中写及某地、文本在某地刊刻，都不自动支持“作品创作于该地”。只有原文明确说明写作行为，或学术编年给出可核出处并经人工裁决，才可将该断言标为 `confirmed`。

## 6. 证据等级

| 等级 | 定义 | 默认状态 | 可支持的结论 |
|---|---|---|---|
| E1 | 原始文本有明确纪年、地点和行为陈述，并有稳定卷/段定位 | `needs_review`；人工核后可 `confirmed` | 文本明确陈述的事实；创作地仍须句法明确指向写作行为 |
| E2 | 同时代或近同时代记录，或作者自序、自注、书札等间接互证 | `needs_review` | 行旅、任官、交游或作品年代的强旁证 |
| E3 | 学术校注本、年谱或编年数据库给出可回查的原始出处 | `candidate`；人工核出处后升级 | 编年和地点的学术断言 |
| E4 | CBDB、中研院人名权威等结构化权威记录，有明确来源但尚未回查原书 | `candidate` | 身份、履历、地名和著述线索 |
| E5 | NER、题名地名、相邻事件、路线合理性或无出处聚合数据产生的推断 | `candidate` | 仅供检索和排序，不进入事实展示层 |

证据等级衡量“来源与断言之间的直接程度”，不等于真实性评分。冲突的 E1/E2 不得用多数票自动裁决；应保留不同版本、异文和学术解释。

## 7. 实施顺序与完成定义

### P0 完成定义

- 建立六人人物 ID、Kanripo 文本注册表和许可证登记；
- 完成陆游《入蜀记》的按日候选事件切分；
- 所有原纪年经 DILA 转换并保留原文、精度和转换依据；
- 所有机器结果均处于 `candidate`/`needs_review`。

### P1 完成定义

- 将地名候选按事件年代送入 CHGIS 解析，保留未决和多候选；
- 人工核对陆游、李清照、苏轼的中研院权威页；
- 输出 CBDB 与中研院记录冲突表，不执行静默覆盖；
- 公开导出不包含受限制的 CHGIS 原始图层。

### P2 完成定义

- 每条 `confirmed` 断言至少有一个可回查证据定位；
- 创作地断言经过专项人工复核，且与“提到地点”“人物所在地”严格区分；
- 李清照争议事实形成多断言并列，而不是单值覆盖；
- 发布前按记录审计署名、非商业、相同方式共享及再分发限制。
