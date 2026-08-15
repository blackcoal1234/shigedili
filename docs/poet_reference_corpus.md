# 88 位诗人开放参考史料补充采集器

## 1. 定位与边界

`tools/poet_reference_corpus.py` 是一个与 `journey_source_pipeline` 解耦的候选层采集器。它从
`data/poems.json` 动态发现诗人和本地朝代，当前语料应得到 88 位诗人；脚本不维护另一份固定的
88 人名单，也不按诗人逐个发网络请求。

本工具只回答两类问题：

1. 开放作者元数据中是否存在该诗人的参考简介；
2. Kanripo 目录中是否存在与该诗人姓名、责任者或人物节点严格对应的书目记录。

这些材料是**开放参考史料**，不是作诗时间、创作地点或行旅路线证据。工具只写
`data/candidates/`，不会写入 `data/reviewed/`，也不生成或修改任何展项页面。

## 2. 来源、许可与固定下载资产

### 2.1 chinese-poetry/chinese-poetry

- 仓库：[chinese-poetry/chinese-poetry](https://github.com/chinese-poetry/chinese-poetry)
- 许可：[MIT](https://github.com/chinese-poetry/chinese-poetry/blob/master/LICENSE)
- 唐作者元数据：
  [authors.tang.json](https://raw.githubusercontent.com/chinese-poetry/chinese-poetry/master/%E5%85%A8%E5%94%90%E8%AF%97/authors.tang.json)
- 宋作者元数据：
  [authors.song.json](https://raw.githubusercontent.com/chinese-poetry/chinese-poetry/master/%E5%85%A8%E5%94%90%E8%AF%97/authors.song.json)

匹配规则：依据本地朝代只检查对应作者文件；作者 `name` 必须与本名完全相等，或经本项目
88 人姓名字符集内的逐字简繁变体组合后完全相等（兼容来源中“黄庭堅”一类简繁混排）。一个姓名得到多个不同源记录时统一标记
`ambiguous`，全部候选均保留，不自动挑选。输出保留 `desc`、源记录 `id`、下载 URL、内容
SHA-256 与抓取时间。

若同一诗人在 `data/poems.json` 的逐诗记录中出现多个朝代标签，查询朝代取本地记录数量最多
者，并在 coverage 的 `local_dynasty_counts` 与 `dynasty_resolution` 中保留原始计数；最高票相同
时中止采集，避免任意绑定到某一作者文件。

### 2.2 Kanripo KR-Catalog

- 仓库：[kanripo/KR-Catalog](https://github.com/kanripo/KR-Catalog)
- 许可：[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/)
- 扫描目录：
  [KR4c](https://raw.githubusercontent.com/kanripo/KR-Catalog/master/KR/KR4c.txt)、
  [KR4d](https://raw.githubusercontent.com/kanripo/KR-Catalog/master/KR/KR4d.txt)、
  [KR4j](https://raw.githubusercontent.com/kanripo/KR-Catalog/master/KR/KR4j.txt)

目录解析以 `*** KR_ID` 为记录边界，并读取标题、上级类别、`:_RESP:`、`**** 人物`、人物朝代
及职责。以下任一结构化强证据成立时记为 `matched`：

- 标题头的作者段与本名/简繁别名完全相等；
- `_RESP` 拆出的责任者姓名完全相等；
- `人物` 节点姓名完全相等，且其朝代不与本地朝代冲突。

若只有书名包含完整姓名、缺少责任者或人物节点佐证，则仅记 `ambiguous`。全文中的任意提及
不会作为匹配依据；目录朝代与本地朝代明确冲突时不命中。每条记录保存 KR_ID、标题、类别、
责任者、人物结构、短证据、目录 URL，以及目标仓库
`https://github.com/kanripo/KR_ID`。

## 3. CLI

在项目根目录运行：

```powershell
# 全体 88 人；跨 GitHub 文件最多两个并发任务
python tools/poet_reference_corpus.py collect --scope all --workers 2

# 默认核心六人
python tools/poet_reference_corpus.py collect --scope core

# 显式名单优先于 scope，重复姓名自动去重
python tools/poet_reference_corpus.py collect --poets 李白,苏轼,陆游

# 仅使用通过 checksum 校验的本地缓存
python tools/poet_reference_corpus.py collect --scope all --offline --workers 2

# 调用离线 fixture 测试
python tools/poet_reference_corpus.py check
```

`--workers` 的值即使大于 2，也会被硬限制为 2。并发仅发生在 5 个 GitHub 原始文件之间；下载
完成后，88 人匹配全部在本地执行。

## 4. 输出

### 4.1 `data/candidates/poet_reference_biographies.jsonl`

一行一个作者简介候选，主要字段：

```text
reference_id, poet, dynasty, match_status, match_method,
matched_name, source_record_id, desc,
source, source_dataset, source_url,
source_license, license_url,
content_sha256, retrieved_at, parser_version
```

`match_status` 为 `matched` 或 `ambiguous`。同名多记录不会静默归并。

### 4.2 `data/candidates/poet_kanripo_catalog_matches.jsonl`

一行一个“诗人 × KR_ID”目录匹配，主要字段：

```text
reference_id, poet, dynasty, match_status, match_methods, matched_aliases,
kr_id, title, catalog_heading, category, responsibility, people, evidence,
source_catalog, source_url, repository_url,
source_license, license_url,
content_sha256, retrieved_at, parser_version
```

同一 KR 记录可以合法列出多位责任者，各诗人按自己的结构化人物/职责分别匹配；这不构成
身份歧义。只有同一个姓名别名本身映射到多个本地诗人时，相关记录才降为 `ambiguous` 并写入
`collision_poets`。

### 4.3 `data/candidates/poet_reference_coverage.json`

覆盖报告始终列出语料中的全部诗人。每位诗人的两个来源状态属于：

- `matched`：存在至少一条结构化强匹配；
- `ambiguous`：仅有弱匹配，或同名/别名存在歧义；
- `not_found`：相关全局资产完整可用，但没有命中；
- `fetch_failed`：本次相关资产缺失、下载失败、缓存损坏或结构解析失败。

报告同时保存 `active_status`。如果联网失败，旧成功 JSONL 不被清空；当前 `status` 会写
`fetch_failed`，而 `active_status` 继续反映旧记录，使“本次尝试”与“仍可用的历史成功结果”不
混为一谈。`sources.*.attempts` 保存每个全局文件的 URL、HTTP 状态、缓存状态、SHA-256、错误
和抓取时间。

## 5. 缓存、原子性与失败恢复

缓存目录限定为 `.cache/poet_reference_corpus/`：

```text
.cache/poet_reference_corpus/
├── bodies/<content_sha256>.bin
└── meta/<url_sha256>.json
```

正文以内容 SHA-256 命名；URL 元数据包含正文文件名、字节数和 checksum。读取缓存时同时校验
URL、文件名、字节数与 SHA-256。在线请求失败但旧缓存仍完整时，尝试状态记为
`fetch_failed_cache_used` 并继续使用旧缓存；没有可用缓存时记 `fetch_failed`。

缓存指针、两个 JSONL 和 coverage 均先写同目录唯一临时文件、`flush + fsync` 后再
`os.replace`。刷新只替换“本次成功解析的资产 × 本次选择的诗人”；失败资产对应的旧记录原样
保留。所有 JSONL 在发布前使用固定排序键，JSON 对象键也固定排序。

## 6. 离线测试与验收

```powershell
python -m py_compile tools/poet_reference_corpus.py tools/check_poet_reference_corpus.py
python tools/check_poet_reference_corpus.py
python tools/poet_reference_corpus.py check
```

fixture 测试不访问网络，覆盖：

- 从模拟语料动态发现 88 人；
- 简繁姓名精确别名；
- 同名多源记录歧义；
- Kanripo 标题、责任者、人物、朝代与职责解析；
- 仅书名命中的降级处理；
- 稳定排序与确定性序列化；
- 离线缓存命中、checksum 损坏拒绝；
- 在线失败回退旧缓存并记录 attempt；
- 失败资产保留旧成功输出；
- coverage 的 88 人与四种显式来源状态。
