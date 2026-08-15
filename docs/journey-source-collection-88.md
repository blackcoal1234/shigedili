# 88 位诗人行旅史料采集说明

## 边界

本项目中的“全体史料”指：**当前 88 位语料诗人在已接入、可公开检索来源中的可复跑快照**。它不等于传世史料穷尽，也不等于事实已审核。网络解析结果全部先进入 `data/candidates/`；`.cache/` 只保存原始响应；`data/reviewed/` 只能由后续人工审核流程更新。

诗人名单从 `data/poems.json` 按首次出现顺序动态生成。当前为 88 人。朝代查询值统一为 `Tang` / `Song`；语料中高适、杨万里、欧阳炯存在少量跨标签记录，registry 同时保存 `dynasty_variants` 与计数，并以占比最高、同数时首次出现的标签作为主查询值，避免静默丢失这项数据问题。

## 来源与身份

registry schema v4 在 builder 输出的 88 人 × 3 来源（共 264 个来源条目）上统一显式保存 `source_url`、`access_level`、`source_grade`、`license`、`license_note`，字段值与候选层一致：

| 来源 | `source_url` | `access_level` | `source_grade` | `license` | 口径说明 |
| --- | --- | --- | --- | --- | --- |
| CBDB | `https://cbdb.fas.harvard.edu/cbdbapi/person` | `open_api` | `B` | `CC BY-NC-SA 4.0` | 有效底本/页码且年份精确时为 B；区间或缺少出处的具体候选降为 C。registry 的 `identity_source_url` 另行保留身份审计快照地址。 |
| 搜韵 | `https://api.sou-yun.cn/open/Poem` | `public_web` | `C` | 空字符串 | 官方 API 仍按公开网页来源口径处理；无机器复用的明确开放许可，仅保存结构化字段与必要短引，年份须人工复核。 |
| CNKGraph | `https://open.cnkgraph.com/api/Biography` | `open_api` | `B` | 空字符串 | 定向 Biography 结构解析按 B；保守递归或作者未核实的作品降为 C。接口为非商业使用，数据版权属原底本，许可说明与实验性标记写入 `license_note`。 |

### CBDB

- 数据库快照：`cbdb_20260801.sqlite3`
- SHA-256：`ec0be08186722c53f77b47f4513239afd6a505f8157994cc72b9fbd49c6fc21a`
- 身份审计快照：`data/candidates/cbdb_identity_audit_88.json`
- 审计结果：87 人唯一；常建保留 4 个候选 ID（94489 / 147391 / 149973 / 163667），不自动绑定。
- registry 中审计 ID 优先于直接姓名查询。王建 92047、叶梦得 2054、张先 27114、欧阳炯 93725、张志和 93417、李煜 3551 等已按审计结果隔离同名或别名风险；张志和/张龟龄、欧阳炯/欧阳迴只使用显式审计别名。

`ensure_cbdb_database()` 校验的是 ZIP **解压后的 SQLite 文件**，下载与解压均使用 `.part` 文件，校验通过后原子替换。fixture 测试只使用临时目录。

### 搜韵开放 API

主入口：

```text
https://api.sou-yun.cn/open/Poem?key=POET_NAME&scope=Author&dynasty=Tang|Song&jsonType=true&pageNo=0
```

主采集不再依赖当前易返回 429 的 `PoemIndex.aspx`；HTML 解析器只保留为显式 `--souyun-transport html` 的兼容/fixture 路径。API 采集会：

1. 在 `Authors.Names / AuthorIds / Dynasties` 中按“姓名完全相等 + 朝代匹配”筛选；
2. 多个 exact AuthorId 记 `identity_ambiguous`，不选第一个；
3. 单个 exact 但 `PageSize=0`、`ShiData` 为空时，记 `discovered_author_id_but_api_requires_disambiguation`；此时 `Count` 是作者候选数，不是作品数；
4. 正常结果按 `Count / PageSize` 自动翻页，记录名义 Count、实际页数、实际作品数、AuthorId 与完整性；自动模式设单诗人 500 页硬上限（当前探测最大为刘克庄 242 页）；
5. 同域固定单 worker、请求起始间隔 2–3 秒；连续两次 HTTP 429 记 `rate_limited` 并暂停该诗人范围，供 `--resume` 重试；
6. 无论刷新参数如何，旧搜韵候选都不会被物理清退。

身份持久化另设强门槛：只有官方 API 已同时核验“精确诗人名（仅使用受控繁简规则）+ `Tang`/`Song` 朝代 + resolved AuthorId”，并且该范围最终状态为 `ok` 或 `collected`，状态行才写 `identity_verified=true`。`partial`、限流、失败、同名歧义和 `PageSize=0` 待消歧均保持 `false`，不会写成 registry 的 active discovery。builder 必须先根据 fresh probe 判定身份：多个 exact AuthorId 直接记 `identity_ambiguous`；单个 exact 但 `PageSize=0` 且 page0 无作品时直接记 `discovered_author_id_but_api_requires_disambiguation`。这两类 blocker 均优先于 `audited_seed`，seed ID 只写入去重的 `stale_candidate_author_ids`，且 `identity_verified=false`。

registry 刷新会同时识别带完整核验链的 `discovered` 与 `audited_seed`。完整链要求 `_SOUYUN_VERIFIED_PROVENANCE_FIELDS` 声明的九项字段全部存在且有效：`identity_verified`、核验姓名、朝代、AuthorId、核验方法、核验时间、核验来源、`discovered_at`、`discovered_from`；任一项缺失或空白，该旧 ID 只可进入 stale，不得恢复 active identity。字段完整时刷新会原样保留 provenance；新的歧义或待消歧状态仍绝对优先。相同输入的重复刷新保持内容与 `generated_at` 幂等。

当前 registry 的搜韵身份状态若属于既有 identity blocker（如 `identity_ambiguous` 或 `discovered_author_id_but_api_requires_disambiguation`），采集器会在发起请求前短路，并以该 blocker、`identity_verified=false`、本轮 0 候选覆盖旧成功状态；`--resume` 也不会因旧 `ok` / `collected` 而跳过这次状态纠正。旧搜韵候选仍可物理保留用于审计，但**保留不等于激活**：coverage 中该范围的 `candidates` 保留磁盘总数，`stale_candidate_count` 记录同一审计数，`reviewable_candidates` 与有效 `linked_work_candidates` 均为 0，且不会提升全局有效补充数。

2026-08-09 的 page0 探测快照原始件位于 `tmp/souyun_probe_88_summary.json`，候选层耐久副本位于 `data/candidates/souyun_identity_probe_88.json`：87 人 HTTP 200，欧阳炯一次连接失败；名义总 Count 49,728，通常 PageSize 20，约 2,540 页。registry 会导入该快照中的严格同名同朝代 ID；王建（18501 / 19737）与叶梦得（24994 / 23408）存在多个 exact 同名，因此只记录候选 ID、不自动绑定。陆游当前 probe 返回相关人名与单个 exact ID 34522，但 `PageSize=0`、page0 无作品，因此状态保持待消歧，34522 作为旧 seed 同时进入 stale；杨万里、尤袤、秦观、张炎、文天祥、林逋等同类结果采用相同规则。

`AuthorDate` 只生成 C 级编年候选；`AuthorPlace`、体裁、韵部、Rank 与评论书目作为来源元数据保存，不把地点代码自动推断为真实行路。

### CNKGraph

- 生平：`/api/Biography?Author=...`
- 作品统计：`/api/Biography/WritingStat?Author=...`
- Swagger：`https://open.cnkgraph.com/swagger/v1/swagger.json`

每个诗人范围同时缓存 Biography 与 WritingStat，并在状态/coverage 中记录 WritingStat 状态、缓存键、记录数及发现的 CSV/URL 引用。Biography 返回 HTTP 204 时记 `not_covered`，不是网络失败。WritingStat 本轮只做可追溯缓存与轻量统计引用，不将其内容直接提升为路线事实；未覆盖项会保留在后续补采队列。

CNKGraph event/work 候选的 `source_url`、`access_level`、默认 `source_grade`、`license`、`license_note` 直接复用 `poet_source_registry.CNKGRAPH_SOURCE_METADATA`，以 registry 常量作为单一来源；定向结构候选保持默认 B，保守递归或作者未核实候选仅对 `source_grade` 作既有 C 级降级。

## 并发、缓存与续抓

- 全局按 `(poet, source)` 建立任务池；每个任务创建独立 `HttpCacheClient` 和独立 `requests.Session`。
- `SharedHostGate` 只共享并发/间隔状态，不共享 Session。
- 搜韵 API 并发 1；CNKGraph 与 CBDB 使用有限并发；所有缓存 body/meta 通过同目录临时文件原子替换。
- 缓存命中前核验 meta 中的 SHA-256 与 body；缺失或不匹配视为 miss。`--retries=0` 仍执行一次网络尝试，避免零次循环。
- 候选与状态在内存中完成后稳定排序，由主线程单点写盘。
- 状态行的 `last_fetch_candidates`（仅当采集器原本给出 `candidates` 时记录）表示最近一轮响应解析出的本轮行数；`candidates` 则在候选按 `candidate_id` 合并后重算，表示该 `(poet, source)` 在两份候选文件中的实际唯一行数。因此，CNKGraph 本轮重复 ID 会被压成实际唯一数，搜韵本轮返回 0 但旧成功行被保留时也仍以磁盘保留数为准。
- `--resume` 只跳过完整成功的范围；自动搜韵分页必须有 `pagination_complete=true` 才跳过。
- 失败、204、歧义、待消歧或 partial 状态均不会清除旧成功候选。
- 候选 JSONL、状态 JSONL 与 coverage JSON 均通过同目录临时文件原子替换；相同批次重复写入按稳定键 upsert，不增加重复候选。coverage 写出前会与已有 JSON 做忽略 `generated_at` 的深比较：语义相同则沿用原时间戳并保持原文件字节不动，语义变化时才更新时间并原子替换。

推荐全量命令（由主流程执行，耗时较长）：

```powershell
python tools/journey_source_pipeline.py collect `
  --scope all `
  --sources cbdb,souyun,cnkgraph `
  --max-souyun-pages 0 `
  --resume `
  --workers 16 `
  --cbdb-workers 4 `
  --cnkgraph-workers 3 `
  --souyun-workers 1
```

也可分来源断点运行：

```powershell
python tools/journey_source_pipeline.py collect --scope all --sources cbdb,cnkgraph --resume
python tools/journey_source_pipeline.py collect --scope all --sources souyun --max-souyun-pages 0 --resume
```

## 人工复核队列

优先复核：

1. CBDB 常建的 4 个身份候选；
2. 搜韵多个 exact 同名作者；
3. 搜韵“已发现唯一 exact，但 API 仍要求消歧”的作者；
4. `AuthorDate` 与既有审核编年冲突的作品；
5. CNKGraph 与 CBDB 同年异地记录；
6. API 地点代码、别名或古今地映射尚未可靠解析的记录；
7. WritingStat `not_covered` / 失败 / 无可引用统计的诗人。

`data/candidates/journey_source_coverage.json`（当前 `schema_version=4`）始终从合并后的完整候选文件与完整状态文件汇总当前 88 人 × 3 来源的全局快照；`--poets` 只限定本批采集对象和命令行显示，不缩小该文件。coverage 汇总每位诗人的来源状态、成功/缺失/歧义/失败数量、候选可定位率与 WritingStat 覆盖，其中 `per_poet[诗人][来源].candidates` 与对应状态行的 `candidates` 使用同一磁盘合并口径。任何页面或报告都应使用“当前来源快照”“候选/待复核”等表述。
