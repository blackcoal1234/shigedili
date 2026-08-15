# 行旅史料数据源策略（journey_source_pipeline）

本文档说明 `tools/journey_source_pipeline.py` 所采数据源的定位、准入与证据
等级，以及人工审核门槛。采集器只产出**候选层**（`data/candidates/`），
绝不自动改写 `data/reviewed/` 中的已审核数据，也不自动发布任何结论。

## 1. 来源总览与定位

| 来源 | 定位 | 产出 | 默认证据等级 | 访问级别 |
| --- | --- | --- | --- | --- |
| 搜韵（Sou-yun）作者索引 | 结构化二手索引（入口） | work_chronology | C | public_web |
| CBDB 人物 API | 传记行旅事实（地址/任官） | person_event | B / C | open_api |
| CNKGraph Biography API | 传记时间线（可选、实验性） | person_event / work_chronology | B | open_api |
| CHGIS | 地名解析（只做解析，不做行旅事实） | 无候选（仅地名/坐标） | — | open_api |

### 1.1 搜韵是入口，不是结论

搜韵诗词地理（PoemGeo）页面是地图式入口：

- https://www.sou-yun.cn/PoemGeo.aspx （诗词地理总入口）
- https://www.sou-yun.cn/PoemIndex.aspx?author=15188 （作者索引，本采集器实际解析的页面）

作者固定 id：

| 诗人 | 搜韵 author id |
| --- | --- |
| 李白 | 15188 |
| 杜甫 | 17270 |
| 白居易 | 18804 |
| 苏轼 | 29937 |
| 陆游 | 34522 |
| 李清照 | 27794 |

搜韵索引页给出的年月属于“页面上的二手编年”，不携带底本页码。因此：

- 分页为 **0-based**：`page=0`（或无 page 参数）是首页，`page=1` 是第二页；
  采集器从首页开始逐页抓取。
- 只有标题能通过 `data/poems.json` **同作者作品**的 `normalize_title` **精确匹配**
  时才落盘（不做前缀/模糊匹配），并且：
  - 无年份条目不输出；
  - 组诗子题（如“其二”“秋浦歌（其十五）”）在缺少组题上下文时不得误匹配；
  - 同题多首（歧义）不输出。
- 命中后统一 `source_grade = C`、`status = needs_review`。
- 短证据仅保存结构化字段与必要短引，不发布页面全文。
- 搜韵无面向机器复用的明确开放许可，`license` 字段置空，处理说明写入 `license_note`。

### 1.2 CBDB：传记行旅事实，附许可证

官方 API 文档：

- https://input.cbdb.fas.harvard.edu/cbdbapi/index.html （CBDB API 说明页）
- https://cbdb.hsites.harvard.edu/cbdb-api （CBDB API 项目页）
- 数据查询：https://cbdb.fas.harvard.edu/cbdbapi/person?id=ID&mode=json

**查询方式**：按已核实的固定 person ID 查询（避免姓名查询“仅返回第一个匹配”
的风险）：

| 诗人 | CBDB PersonId |
| --- | --- |
| 李白 | 32540 |
| 杜甫 | 3915 |
| 白居易 | 32227 |
| 苏轼 | 3767 |
| 陆游 | 3640 |
| 李清照 | 19713 |

返回后解析 `Package.PersonAuthority.PersonInfo.Person.BasicInfo` 的
`ChName / IndexYear / PersonId` 并至少核验姓名（允许繁简变体，如
`蘇軾`/`苏轼`、`陸游`/`陆游`）；姓名或 PersonId 不符时
`status=identity_mismatch`、0 候选。

- 数据结构：`Package.PersonAuthority.PersonInfo.Person`
  - `PersonAddresses.Address`：**必须有有效 FirstYear**；仅当 `AddrName` 非空
    且 `FirstYear` 为正年份时输出 `person_event`（event_type=residence）。
    `FirstYear=0/空` 而 `LastYear>0` 的籍贯类记录不得当行程。
  - `PersonPostings.Posting`：仅当 `AddrName` 非空、非 `[未詳]`、非 `0`，
    且年份有效时输出 `person_event`（event_type=posting）。
- **籍贯 0 年不得当行程**：`FirstYear=0 / LastYear=0` 的籍贯记录一律过滤。
- **同年同地不同任职不合并**：posting 的 `candidate_id` 纳入 office 与 PostingId
  定位，知制诰/主客郎中等同地同年不同官职保持独立候选；`status.candidates` 统计
  **unique candidate_id**，note 中写 `raw/unique` 计数；完全相同记录重复出现仍幂等。
- 证据等级：有**有效底本/页码**（`未知`/`未詳`/`不详`/`0`/空等未知占位不算）且年份
  精确为 `B`，否则一律 `C`——未知出处即使年份精确也不升 B（真实数据中白居易同州835、
  苏轼英州/开封等 4 条已修正为 C；候选不删除，仍保留待人工核验）。
- 许可证：CBDB 数据以 **CC BY-NC-SA 4.0** 发布（官方数据库许可；
  https://projects.iq.harvard.edu/cbdb ）。采集器保存字段设
  `access_level=open_api`、`license=CC BY-NC-SA 4.0`，仅保存结构化字段与必要短引。
- 另可离线获取数据库快照：https://github.com/cbdb-project/cbdb_sqlite

### 1.3 CNKGraph：非商业开放接口，实验性

- 官方 OpenAPI 文档：https://open.cnkgraph.com/swagger
- Biography 接口：https://open.cnkgraph.com/api/Biography?Author=李白
  - **真实 payload 结构**（如已缓存苏轼约 17MB）：顶层 `Common / Traces / Title / ...`；
    `Traces[].Markers[]` 含 `Id / Title / Latitude / Longitude / RegionId / Detail`，
    `Detail` 为 HTML：`div.label1`（年份锚点，href 含 `beginYear/endYear`）后随
    `div.detail` 块，内含 `ViewDetail('scope=&author=&beginYear=N&endYear=M')` 行
    （事件文字）与嵌入的 `div.poemTitle.showDetail` 诗作链接
    （`/Writing/{id}?labeling=true` + `span.authorDate`）。
  - 旧式 `Biography.Activities` 结构仍支持（`BiographyActivityItem`）。
- 定位：**非商业开放接口**（数据版权属原底本，详见接口站点条款）；结构可能随版本
  变化，本适配标记为**实验性**。接口可能超时、返回 204 或要求登录——这些只记录
  状态（`journey_source_status.jsonl`），**不使整个批次失败**；失败分类
  （`parse_failed / fetch_failed / blocked_by_policy / partial`）与失败原因会保留，
  不会被后续成功页覆写。
- 解析原则：
  - 只输出能明确读出的年、地点、作品标题；
  - **Traces 结构**：只要顶层存在 `Traces` **列表**就一律走 trace parser（即使主
    `Markers` 缺失/空），**绝不递归 fallback 到 `Lines[].Markers`**；递归兜底仅用于
    完全不含 `Traces` 的旧结构。仅当行有明确 `beginYear/endYear`（label1 子 `<a>` 与
    inline 锚点都需两者齐全；孤立 `div.detail` 无直接前置 label1 不产出）才可能产出
    `person_event`。B 级 `person_event` 必须同时具备：非空短摘要、`Marker.Title`、
    `RegionId`、有效经纬度；只有诗作而无摘要的行仍产 work、不产 event。
    `historical_place` 取 `Marker.Title`，`RegionId`/经纬度写入
    `region_id/latitude/longitude` source 字段；marker 的 `Id/Key` 常为空，故
    `source_pages` 稳定定位为 `Marker[marker_index|RegionId|Title] label=<label id>
    row=<row序号> 年段`（row 序号保证同 marker 内每条事件独立定位，真实苏轼 6580 事件
    locator 唯一数=事件数）。`event_text` 只保留 120 字短摘要，完整规范化文本只以
    `event_hash`（sha256）参与 `candidate_id`，杜绝“前 120 字相同但尾部不同的事件被
    误并”；**`Traces[].Lines[].Markers` 的折线点不当作行旅史实**；
  - **嵌入诗作**：按诗人+标准化题名在语料中**精确/严格匹配**，`year` 取 `authorDate`
    或当前年份块；`work_chronology` 的 `historical_place` 恒为空，**绝不继承 marker
    地点**；保留 `source_title`、`author_date`、`writing_id`、`body_hash`（能关联时）；
  - **作者过滤（防证据污染）**：解析嵌入诗作 `span.poemAuthor a` 的 `source_author`；
    Biography Detail 会嵌入张说、韩愈、苏辙等**他人作品**，凡“明确且不匹配”目标诗人
    的作品一律不产出 work 候选（`_ch_name_matches` 支持繁简，如 `蘇軾`/`苏轼`）；
    作者为空的条目（多为组诗续条）**降为 C 级并强制 unlinked**（`source_author=""`、
    `linked=false`、`body_hash` 空），仍保留供人工核验，并在 `source_note` 注明
    “作者未标注，归属待人工复核”。真实苏轼数据复验：过滤后无 729 等生年前年份
    （work 年份 ≥1045）；
  - **日期保留范围与约数**：`725-727` → `year_start=725, year_end=727,
    year_precision=approximate`；`约725` → `725/725 approximate`；不做固定 exact、
    不取首个数字。覆盖 Traces `authorDate`、旧式 `Activities`（`Year/OldYear`）与
    递归兜底；`background_adapters.parse_year_range` 同步修复 `AuthorDate` 解析；
  - **源端同题多作不自动关联（防二次匹配污染）**：在一次 payload 的 works 集合内，
    按规范化标题统计 distinct `WritingId`（无 id 时按来源定位）；同标题对应 >1 个
    源作品时，**所有这些 work 一律 `linked=false`、`body_hash` 空**，并标
    `source_title_ambiguous=true`、note「源端同题多作，未自动关联」。只有“源端标题
    唯一 + 本地同作者题名唯一”才关联；同题源作仍按 `writing_id` 各自保存为独立候选。
    真实苏轼数据复验：89 个歧义标题，关联后无“一个本地诗多年份”异常；
  - 上述明确结构标 **B** 级（`extraction_method=cnkgraph_biography_traces_v1`）；
  - 有 `Year` + `Place` 的旧式活动 → `person_event`（定向解析 B 级，needs_review）；
    `candidate_id` 纳入 category/event_text/活动序号等唯一定位，**同年同地不同事件
    不合并**；
  - 有 `Year` + 作品标题（`Poems[].Title`）→ `work_chronology`（定向解析 B 级，
    needs_review），**不得把“年份附近的活动地点”推断为作品创作地**；作品标题按
    诗人+标准化题名在语料中唯一匹配时回填 `body_hash`，未匹配时明确标记
    `linked=false`（unlinked），`body_hash` 置空，地点字段恒为空；
  - **同作者同题同分多结果不任选第一个**：`background_adapters.find_cnkgraph_writing`
    检测并列，返回空并标记歧义（status=insufficient），绝不静默取首个匹配；
  - 若响应结构不稳定，走保守递归提取（`recursive_cnkgraph_extract`），仅对同时
    含可读年份与地点/标题的对象建候选，此类候选**降为 C 级**（`extraction_method=
    cnkgraph_biography_recursive_v1`），并在本文档标注为实验性。
- CNKGraph 无面向机器复用的明确开放许可，`license` 字段置空，处理说明写入
  `license_note`。

### 1.4 CHGIS：只做地名解析

- 接口：https://chgis.hudci.org/tgaz/placename?n=NAME&yr=YEAR&fmt=json
- 只用于把候选中的历史地名解析为现代坐标/行政区划，**不生成行旅事实候选**。
- **注意：CHGIS 只解析历史地名，不证明某位诗人到访过该地**。

## 2. 网络与缓存策略

- 原始响应写入 `.cache/journey_sources`（内容寻址缓存，键=请求的
  method+url+payload 的 SHA-256）。
- 复用 `tools/background_adapters.py` 的 `HttpCacheClient`（不改动它），
  以其 `cache_dir` 参数指向 `.cache/journey_sources`；三来源均只需 GET，
  无需实现额外 POST 缓存客户端。
- 礼貌策略：默认延迟 1.5–3.0 秒/域、超时 20s、重试 3 次、遵守 robots.txt。
- 可恢复：`--resume` 对搜韵按“已完成页数 >= 本次请求页数 且 状态完整成功”才跳过；
  扩大 `--max-souyun-pages` 会继续补页；`partial`/失败状态不会误判为已完成。
  状态行持久化 `pages_requested / pages_completed / failed_page`。
  `--offline` 只读缓存。

## 3. 证据等级与人工审核门槛

证据等级沿用项目口径（`SOURCE_BASE`）：A（可靠一手/正史+页码）、B（可靠
底本/页码或明确系年）、C（二手结构化索引/网页）、D（模型辅助）。

本采集器产物：

- 搜韵：一律 **C**（souyun work 明确 `linked=true`、`source_title_ambiguous=false`）；
- CBDB：**B**（明确底本/页码且年份精确）或 **C**（区间或缺少出处）；
- CNKGraph：定向 `Activities` 解析 **B**；保守递归 fallback **C**（实验性）；
  空作者 work **C** 且 unlinked。

**有效补充口径（linked/unlinked/ambiguous 拆分）**：

- `coverage`（`journey_source_coverage.json`）与 `report` 输出
  `linked_work_candidates / unlinked_work_candidates / ambiguous_work_candidates /
  reviewable_candidates`；coverage 另列 `locatable_event_candidates /
  unlocated_event_candidates`，避免把尚未解析坐标的传记事件当成可直接播放的路线点；
  总 event/work 数仍保留。
- **只有 linked works 计入“有效补充”**：`new_work_candidates`（report 的
  new_work）、`reviewable_candidates`、`priority_gaps`、`conflicts` 均只统计
  linked works（事件候选恒计入）；unlinked/ambiguous 另列待人工分流。
- 旧搜韵候选兼容：无 `linked` 字段但 `body_hash` 非空的视为 linked。

**审核门槛（不自动通过）**：

1. 所有候选默认 `status = needs_review`；只有人工审核后才能进入已审核数据。
2. 候选保留 `candidate_id` 稳定；同一 id 再次采集时，已有 `reviewer /
   status / review_note / reviewed_at` 不被覆盖。
3. `report` 只读对比 `data/reviewed/poet_journeys.json` 与六份主
   `*_spirit_chronology.csv`（不含 libai p2-p5 分片），报告 `conflicts`
   （同时期不同地点）与 `priority_gaps`（超出已审核覆盖范围的候选），
   供人工判断“延伸还是矛盾”，绝不自动发布。
4. **stale 刷新（显式开关）**：`collect --refresh-successful-scopes` 仅当本次
   (诗人, 来源) 的 status 为完整成功（`ok/collected/empty/no_usable_records`）
   时，先清退该范围旧候选再写新候选；`partial`/失败/offline 等绝不清退；同一
   candidate_id 上已有的 reviewer/status 字段在刷新时保留。默认（不带该开关）
   保持现有 upsert。

## 4. 官方精确 URL 清单

- 搜韵作者索引：https://www.sou-yun.cn/PoemIndex.aspx?author=ID&page=N （0-based）
- 搜韵诗词地理：https://www.sou-yun.cn/PoemGeo.aspx
- CBDB 人物 API：https://cbdb.fas.harvard.edu/cbdbapi/person?id=ID&mode=json
- CBDB API 说明页：https://input.cbdb.fas.harvard.edu/cbdbapi/index.html
- CBDB API 项目页：https://cbdb.hsites.harvard.edu/cbdb-api
- CBDB 数据库快照：https://github.com/cbdb-project/cbdb_sqlite
- CBDB 项目：https://projects.iq.harvard.edu/cbdb
- CNKGraph 开放 API 文档：https://open.cnkgraph.com/swagger
- CNKGraph Biography：https://open.cnkgraph.com/api/Biography?Author=NAME
- CNKGraph 诗词地理前端：https://cnkgraph.com/Map/PoetLife?author=NAME
- CHGIS 地名查询：https://chgis.hudci.org/tgaz/placename

## 5. 补充人工交叉核验来源（仅供人工复核，不自动入库）

以下来源用于**人工**交叉核验候选，采集器不自动抓取、不自动改写：

- 中央研究院文学 GIS 总入口：https://gis.rchss.sinica.edu.tw/cls/gis/
  旧子系统可达性不稳定、版权未授权机器复用，因此**只作人工复核**，
  不写入自动化采集与证据链。
- 国家社科项目说明：https://www.nopss.gov.cn/n1/2016/1201/c358282-28917753.html
  说明搜韵底层编年数据源自年谱、别集编年、文官资料等，**只作为方法与来源谱系**
  的参考，不直接采信具体系年。
- CText（中国哲学书电子化计划）只用于**核对原文**（引文/用字），**不证明路线**；
  行旅/到访判断必须由系年文献与人工审核完成。
- CHGIS 仅解析历史地名，**不证明到访**；地名与坐标只是空间定位辅助。

## 6. 命令示例

```bash
# 采集六人全部来源（默认延迟 1.5-3s、缓存于 .cache/journey_sources）
python tools/journey_source_pipeline.py collect

# 只采搜韵、翻 2 页、断点续采、离线只读缓存
python tools/journey_source_pipeline.py collect --sources souyun --max-souyun-pages 2 --resume --offline

# 对本次成功范围做 stale 清退重建（partial/失败不清退）
python tools/journey_source_pipeline.py collect --refresh-successful-scopes

# 离线 fixture 测试
python tools/check_journey_source_pipeline.py
python tools/journey_source_pipeline.py check

# 只读报告（对比已审核数据，不发布）
python tools/journey_source_pipeline.py report --poets 李白,杜甫
```

输出文件：

- `data/candidates/journey_event_candidates.jsonl`
- `data/candidates/work_chronology_supplements.jsonl`
- `data/candidates/journey_source_status.jsonl`
- `data/candidates/journey_source_coverage.json`
