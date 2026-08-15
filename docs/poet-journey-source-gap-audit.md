# 诗人行旅来源缺口审计

## 1. 范围、快照与判定口径

- 审计对象：当前 88 人候选名单。
- 审计快照时间：`2026-08-09T21:50:59+08:00`。
- coverage 来源：`data/candidates/journey_source_coverage.json`；其中 `generated_at = 2026-08-09T13:18:14+00:00`。
- 快照总量：`event_candidates = 41,226`，`locatable_event_candidates = 40,750`，`unlocated_event_candidates = 476`；79 人已有 person-event，73 人至少有 1 条可定位 event。
- 可定位口径：同一 event candidate 同时具有有效 `latitude` 与 `longitude`。仅有地名字符串仍计入未定位。
- 缺口共 15 人：9 人 `event_candidates = 0`；另 6 人已有 30 条 event candidate，但 `locatable_events = 0`。
- 搜韵后台重试仅处理 work candidate。重试可能刷新 `ok/fetch_failed`，不改变本快照的 person-event 缺口、9+6 分组或 15 人名单；落盘前只读复核显示司马光已由审计时的 `fetch_failed` 刷新为 `ok`。

> **路线证据红线：静态籍贯、目录记录、传记或诗文文本不构成可直接落图的路线。** 只有在人工完成同人消歧、逐条摘出时间—地点主张、保留原文定位与来源 URL，并完成历史地名定位后，才可另行提出 event candidate；本审计及 backlog 均未创建事实 event。

## 2. 15 人缺口与现有来源状态

确定排序：先列 P0，按现有 event candidate 数降序；再列 P1，按预估补采收益与消歧成本排序。`chinese-poetry` 的 matched 项是传记文本；Kanripo matched 项是目录或作品文本，两者均不等于路线事件。

| 优先级 | 诗人 | gap_type | event / locatable | CBDB | CNKGraph | 搜韵（work） | chinese-poetry | Kanripo | 补采动作 |
|---|---|---|---:|---|---|---|---|---|---|
| P0 | 司马光 | 有 person-event、无可定位 event | 14 / 0 | collected | not_covered | ok（落盘前；审计时为 fetch_failed） | matched：传记文本 | matched：`KR4d0040 傳家集` 目录/文本 | 先对 14 条既有事件做历史地名消歧与坐标核验 |
| P0 | 李益 | 有 person-event、无可定位 event | 6 / 0 | collected | not_covered | ok | matched：传记文本 | not_found | 对 6 条既有事件补地点 authority ID 与坐标 |
| P0 | 钱惟演 | 有 person-event、无可定位 event | 4 / 0 | collected | not_covered | fetch_failed | matched：传记文本 | not_found | 对 4 条既有事件补历史地名映射 |
| P0 | 卢纶 | 有 person-event、无可定位 event | 3 / 0 | collected | not_covered | ok | matched：传记文本 | not_found | 对 3 条既有事件补历史地名映射 |
| P0 | 司空曙 | 有 person-event、无可定位 event | 2 / 0 | collected | not_covered | ok | matched：传记文本 | not_found | 对 2 条既有事件补历史地名映射 |
| P0 | 欧阳炯 | 有 person-event、无可定位 event | 1 / 0 | collected | not_covered | fetch_failed | matched：传记文本 | not_found | 先核对同人及时代，再定位 1 条既有事件 |
| P1 | 石延年 | 无 person-event | 0 / 0 | no_usable_records | not_covered | fetch_failed | matched：传记文本 | not_found | 官历较多，优先人工摘取纪年—任地候选 |
| P1 | 贺知章 | 无 person-event | 0 / 0 | no_usable_records | not_covered | ok | matched：传记文本 | not_found | 机构 authority 与正史/文集文本交叉摘证 |
| P1 | 张继 | 无 person-event | 0 / 0 | no_usable_records | not_covered | ok | matched：传记文本 | not_found | 机构 authority 与作品文本交叉摘证 |
| P1 | 聂夷中 | 无 person-event | 0 / 0 | no_usable_records | not_covered | ok | matched：传记文本 | not_found | 人工核验官职、任地和纪年是否同条共现 |
| P1 | 常建 | 无 person-event | 0 / 0 | identity_ambiguous | not_covered | ok | matched：传记文本 | matched：`KR4c0024 常建詩` 目录/文本 | 先解决 CBDB 四个同名候选，再摘取文本线索 |
| P1 | 上官仪 | 无 person-event | 0 / 0 | no_usable_records | not_covered | ok | matched：传记文本 | not_found | authority 交叉核验后摘取纪年—地点主张 |
| P1 | 祖咏 | 无 person-event | 0 / 0 | no_usable_records | not_covered | ok | matched：传记文本 | not_found | 排除同名项后人工摘证 |
| P1 | 张志和 | 无 person-event | 0 / 0 | no_usable_records | not_covered | ok | matched：传记文本 | not_found | 先核对“张龟龄”别名，再摘取正文线索 |
| P1 | 朱淑真 | 无 person-event | 0 / 0 | no_usable_records | not_covered | fetch_failed | matched：传记文本 | not_found | 生平争议较大，以年谱/学术记录人工复核为主 |

## 3. 六类补采或核验来源：接口、许可与采集边界

以下只列已核实的机构或项目页。CBDB 是现有来源的再核验入口；其余用于补充 authority、文本线索或标识符交叉映射。

| # | 来源族 | 官方/项目入口 | 接口与可得字段 | 许可或访问限制 | 自动采集判断 |
|---:|---|---|---|---|---|
| 1 | China Biographical Database（CBDB） | [API 文档](https://input.cbdb.fas.harvard.edu/cbdbapi/index.html)；[项目 API 页](https://cbdb.hsites.harvard.edu/cbdb-api)；[商业许可说明](https://cbdb.hsites.harvard.edu/exclusive-commercial-license) | 人物基本信息、地址、任官记录及关联标识 | 数据许可为 CC BY-NC-SA 4.0；中国大陆商业使用另有专属许可说明 | 适合按人物小批查询并保留原始 ID；本批 9 人现有 CBDB 结果仍未产出 person-event |
| 2 | 上海图书馆开放数据 | [开放数据文档](https://opendata.library.sh.cn/docs/)；[2025 接口说明 PDF](https://opendata.library.sh.cn/download/docs/2025/20250627/03%20%E4%B8%8A%E6%B5%B7%E5%9B%BE%E4%B9%A6%E9%A6%86%E5%BC%80%E6%94%BE%E6%95%B0%E6%8D%AE%E6%8E%A5%E5%8F%A3%E4%B8%8E%E5%BA%94%E7%94%A8%E6%8A%80%E6%9C%AF.pdf) | 稳定 URI、JSON-LD、SPARQL、REST；人物生卒、籍贯、任官年等字段依记录而定 | 门户标示 CC 2.0 BY-NC-SA；接口需 key；请求间隔至少 2 秒；每资源每日最多 2,000 页；部分记录来源为 CBDB，需保留双重 provenance | 条件适合；按单人 URI 和文档限速采集，静态属性只作 identity/context |
| 3 | DILA 人名/地名规范资料库 | [文档首页](https://authority.dila.edu.tw/docs/)；[Person API](https://authority.dila.edu.tw/docs/services/person_query.php)；[Place API](https://authority.dila.edu.tw/docs/services/place_query.php)；[开放内容](https://authority.dila.edu.tw/docs/open_content/download.php) | TEI XML；人名异名、生卒，地名 authority ID、经纬度、现代行政区等 | API 文档未列每日额度；Person/Place 逐条资料的再利用条款在所查 API 页未明确，发布前需人工复核条款 | 适合单实体、小请求量查询；坐标可辅助 authority 对齐，不把籍贯点转成行旅事件 |
| 4 | Chinese Text Project（CTP） | [Linked Open Data](https://ctext.org/tools/linked-open-data)；[API](https://ctext.org/tools/api)；[FAQ](https://ctext.org/faq) | DataWiki/RDF 人物实体与标识符；正史、总集、墓志等数字文本 | RDF 为 CC BY-NC-SA 3.0，需署名与回链；FAQ 对批量页面下载设有限制 | 单实体 RDF 可条件自动化；数字文本按段人工摘证，不做大批页面抓取 |
| 5 | 明清妇女著作（MQWW） | [项目首页](https://mhdb.mh.sinica.edu.tw/mingqing/mqww/)；[下载页](https://mhdb.mh.sinica.edu.tw/mingqing/mqww/chinese/download.php) | 结构化作者页、活动年代、籍贯、作品与书目字段 | 页面公开；本次核查未在所查页面发现清晰再利用许可，Full Access 下载另设入口 | 仅作朱淑真的人工核验来源；批量或再发布前先确认条款 |
| 6 | Wikidata | [数据访问](https://www.wikidata.org/wiki/Help%3AData_access)；[SPARQL 查询服务](https://www.wikidata.org/wiki/Wikidata%3AQUERY) | 实体 ID、外部标识符、生卒与地点属性，SPARQL/RDF/JSON | 结构化数据 CC0；查询服务需遵循服务礼仪与节流 | 适合做最低优先级 ID crosswalk 与漏项发现；不单独据此生成路线事件 |

P0 的历史地名定位还可人工参照 [CHGIS V6 项目页](https://chgis.fas.harvard.edu/data/chgis/v6/)；其学术使用与再分发条款需逐项遵守。CHGIS 在本清单中作为地理核验工具，不计入上表六类人物补采来源。

## 4. 9 名无 person-event 诗人的逐人 URL 审计

“年份字段/地点字段”描述的是来源页面可供复核的字段类型或文本线索，不是已采纳事件。自动采集判断仅针对单实体或小请求量读取。

| P1 顺序 | 诗人 | 已核实项目 URL | 可核验的年份/地点字段 | 采集判断与路线结论 |
|---:|---|---|---|---|
| 1 | 石延年 | [上海图书馆人物 URI](https://data.library.sh.cn/entity/person/t8xysg5dpoca91sx)；[CTP DataWiki](https://ctext.org/datawiki.pl?if=gb&res=891411)；[CTP 墓志/传记文本](https://ctext.org/wiki.pl?chapter=8979483&if=en) | 上图记录含生卒、籍贯及未配地点的官职；CTP 文本可能含纪年与任地语句 | 上图单实体可条件采集；CTP 正文人工摘证。现状仅为静态资料与文本线索 |
| 2 | 贺知章 | [上海图书馆人物 URI](https://data.library.sh.cn/entity/person/xz1sb4c1ng3lg9nm)；[DILA A008710](https://authority.dila.edu.tw/person/search.php?aid=A008710)；[CTP DataWiki](https://ctext.org/datawiki.pl?if=gb&res=730865)；[CTP 文集文本](https://ctext.org/wiki.pl?chapter=220340&if=gb) | 上图/DILA 含生卒或年款、籍贯/authority 坐标；CTP 文本含可人工复核的归乡叙述 | authority 单实体可条件采集；正文人工摘证。籍贯坐标不是行旅路线 |
| 3 | 张继 | [上海图书馆人物 URI](https://data.library.sh.cn/entity/person/4po4uqxtynt9d4mt)；[DILA A010970](https://authority.dila.edu.tw/person/search.php?aid=A010970)；[CTP DataWiki](https://ctext.org/datawiki.pl?if=gb&res=2747113)；[CTP 作品文本](https://ctext.org/wiki.pl?chapter=692835&if=en) | 上图含卒年、任官年与籍贯；DILA 含籍贯 authority/坐标；CTP 为人物/作品线索 | 结构化单实体可条件采集；作品文本人工核验。任官年份与籍贯分列时不合并成事件 |
| 4 | 聂夷中 | [上海图书馆人物 URI](https://data.library.sh.cn/entity/person/du1vz6zzgsq83373)；[CTP DataWiki](https://ctext.org/datawiki.pl?if=gb&res=8148691)；[CTP 诗话/传记文本](https://ctext.org/wiki.pl?chapter=680333&if=en) | 上图含籍贯和未纪年的官职；CTP 正文可能提供生平叙述 | 上图可条件采集；正文人工摘证。官名、籍贯或文本各自都不构成路线 |
| 5 | 常建 | [CTP DataWiki](https://ctext.org/datawiki.pl?if=gb&remap=gb&res=3879813)；[CTP 附录文本](https://ctext.org/wiki.pl?chapter=2670339&if=gb) | DataWiki 提供人物实体/标识；附录是生平文本线索；上海图书馆本轮未定位到唯一同名记录 | 先人工解决 CBDB 四个同名候选；CTP 单实体可作 crosswalk，正文人工摘证 |
| 6 | 上官仪 | [上海图书馆人物 URI](https://data.library.sh.cn/entity/person/s7ajsy1mhaqjix5h)；[DILA A002430](https://authority.dila.edu.tw/person/search.php?aid=A002430)；[CTP DataWiki](https://ctext.org/datawiki.pl?if=gb&remap=gb&res=701508)；[CTP 传记文本](https://ctext.org/wiki.pl?chapter=823038&if=en) | 上图/DILA 含生卒、籍贯及部分任官年；CTP 为人物/传记文本 | authority 单实体可条件采集；正文人工摘证。静态年款与籍贯不拼接成事件 |
| 7 | 祖咏 | [上海图书馆人物 URI](https://data.library.sh.cn/entity/person/jc9a8uqjfgcrcldx)；[DILA A045185](https://authority.dila.edu.tw/person/search.php?aid=A045185)；[CTP DataWiki](https://ctext.org/datawiki.pl?if=gb&res=881893)；[CTP 文本一](https://ctext.org/wiki.pl?chapter=993917&if=gb)；[CTP 文本二](https://ctext.org/wiki.pl?chapter=336147&if=gb) | 上图/DILA 以籍贯 authority/坐标为主；CTP 提供作品与传记性文本线索 | 需排除同名宋僧记录；authority 可条件采集，正文人工摘证；籍贯点仅作身份背景 |
| 8 | 张志和 | [上海图书馆人物 URI（张龟龄）](https://data.library.sh.cn/entity/person/cjpoitivxrfhchtu)；[CTP DataWiki](https://ctext.org/datawiki.pl?if=gb&res=828166)；[CTP《新唐书》文本](https://ctext.org/dictionary.pl?chapter=181540&if=gb&sid=3060&trid=3677524) | 上图含别名、籍贯及未纪年官职；CTP 提供人物实体与正史文本 | 先人工核对别名链；上图/DataWiki 可条件采集，正史正文人工摘证 |
| 9 | 朱淑真 | [上海图书馆人物 URI](https://data.library.sh.cn/entity/person/1eenywu8eeyrm8ar)；[MQWW 人物页](https://mhdb.mh.sinica.edu.tw/mingqing/mqww/search/details-poet.php?language=eng&poetID=2163&showanth=&showbio=&showshihuaby=&showshihuaon=)；[CTP DataWiki](https://ctext.org/datawiki.pl?if=gb&res=640330) | 上图/MQWW 含生卒或活动年代、籍贯、作品/书目；不同记录的籍贯表述需人工处理 | 生平争议优先人工核验；MQWW 条款待确认。现有结构化字段主要是静态人物资料 |

## 5. 按优先级的补采清单

### P0：先定位已有 person-event（6 人）

1. **司马光（14）**：逐条读取 CBDB event 的原始地点字符串与时间，优先 DILA Place、CHGIS V6 做历史地名 authority 对齐；保留候选、置信度和依据。
2. **李益（6）**：同上；注意同名地与行政区沿革。
3. **钱惟演（4）**：同上；核对宋代地名有效期。
4. **卢纶（3）**：同上；地点不明确时保留未定位状态。
5. **司空曙（2）**：同上；不以籍贯坐标代填事件地点。
6. **欧阳炯（1）**：先做同人/时代核验，再做地点定位。

P0 只补既有候选的地理定位，不新增生平事实。每条需人工核对原始 event、历史地名 authority、时代有效性、经纬度与来源许可。

### P1：从结构化记录与文本线索提出候选（9 人）

1. **石延年**：上海图书馆 profile 与 CTP 墓志/传记文本交叉核验。
2. **贺知章**：上海图书馆、DILA 与 CTP 文本交叉核验。
3. **张继**：上海图书馆、DILA 与 CTP 作品/人物资料交叉核验。
4. **聂夷中**：核验官职是否附任地与纪年，再决定是否提出候选。
5. **常建**：先解决 CBDB identity ambiguity，再处理文本。
6. **上官仪**：authority 年款与正史文本交叉核验。
7. **祖咏**：先排除同名项，再处理文本。
8. **张志和**：先核对张龟龄别名链，再处理正史文本。
9. **朱淑真**：以学术项目和年谱证据人工复核，显式记录争议。

P1 的每个潜在线索至少需要：`poet_identity`、原文定位、原始 URL、时间表达、地点表达、事件类型、历史地名 authority、许可复核、人工审核结论。只含传记正文、作品目录、籍贯或生卒字段的记录保持 `needs_manual_review`，不直接进入事实 event。

## 7. 坐标回填后更新

候选层已通过 `ADDR_CODES` 直接关联补入 **19/30** 条坐标；仍有 **11** 条事件地点待人工定位。六位 P0 诗人的缺口类型由“完全无可定位事件”更新为 `has_unresolved_person_event_coordinates`。这些坐标仍是候选补充，不自动进入 `data/reviewed/`，也不以籍贯或现代代表城市替代事件地点。
