# 88人事实核验分片（第二轮）

本目录是并行核验的候选层，不直接替代 `data/reviewed/`。

每个批次只写两类文件：

- `batch_NN_verified.jsonl`：已通过 `tools/poem_fact_expansion.py` 严格事实门的完整事实包。
- `batch_NN_status.json`：该批每位诗人的核验结果、选诗和未通过原因。

硬规则：

1. 诗人、题名、朝代、`body_hash` 必须精确对应 `data/poems.json`。
2. 创作时间和地点均须有 A/B 级来源明确支持；不得由诗句、现代常识或相邻行程推定。
3. 至少两个独立来源家族；作品详情页可只承担身份核对（`supports: []`）。
4. 搜索页、作者分页、登录页、聚合页不算作品证据直链。
5. 有实质系年或地点争议的记录留在 status 中，不进入 verified JSONL。
6. 每条背景事实必须引用实际支持它的证据，不写心理判断。
7. 本轮目标为六位核心诗人以外的 82 位诗人各至少一首。

## 分片格式与作品级证据

- `batch_NN_verified.jsonl` 存放的是**原始事实包**，顶层必须包含
  `poem_key / chronology / evidence / context_facts / verification`；不得把
  `build_expansion_record()` 产出的 `composition / sources` 发布记录写进来。
- CNKGraph `Writing/{id}` 与 `Writing/{id}/MapInfo` 在作者、题名、正文精确
  对应本地诗篇，且 `AuthorDate / AuthorPlace` 非空时，可作为作品级时地
  证据；作者 Biography 的一般活动地不能单独承担作品创作地点。
- 搜韵 `PoemGeo.aspx` 首页或作者分页只用于导航。进入具体作品、核对作品
  ID、正文、`AuthorDate / AuthorPlace` 后，方可把作品级字段写入证据。
- 每条 verified 在落盘前必须直接调用 `validate_fact_package(package,
  poems)`；`status.json` 的 verified 题名与 body_hash 必须和事实包一一对应。
- JSON 统一由 Python 以 UTF-8、`ensure_ascii=False` 写入；状态理由、证据短引
  与背景事实使用中文，并拒绝替换问号或乱码。
