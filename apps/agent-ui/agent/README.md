# 诗行万里 Agent 后端

本目录是 `apps/agent-ui/` 的实验性 Python Agent 服务。现有 29–38 号离线展项保持原样；本服务只读取并缓存它们的 Python 生成数据，为 React/CopilotKit 前端提供可渲染的结构化结果。

## 数据边界

- 路线与镜头：`output/assets/competition/year759_data.json`
- 意象统计：`output/assets/competition/imagery_tide_data.json`
- 88 位诗人目录和作品数：`data/poems.json`
- 请求路径不运行可视化生成器，也不写入 `data/` 或 `output/`。生成快照必须由 `数据可视化脚本/viz_33_year759.py` / `数据可视化脚本/viz_38_imagery_tide.py` 事先离线生成。
- 仓库在跨进程锁内读取现有快照，核对结构、内置源哈希和当前依赖哈希，再原子复制到 `apps/agent-ui/.cache`。快照缺失或哈希过期时返回 `source_error`，提示先运行对应离线生成器。
- `AGENT_CACHE_DIR` 不得等于或位于项目 `data/`、`output/` 内；路径会经过解析和大小写归一化后检查。
- LLM不读取原始文件，也不生成路线、年份、地点或意象率。
- 六位已有编年诗人返回完整路线；其余 82 位返回 `insufficient_evidence`、语料作品数和待补事实字段，不从诗题或正文地名推断路线。

每个工具响应固定含有：

```json
{
  "status": "ok",
  "schemaVersion": "1.0",
  "sourceHashes": {},
  "methodNote": "...",
  "payload": {}
}
```

## 诗词知识库

知识库是离线构建、在线只读的 SQLite FTS5 快照。它把 `data/poems.json`
编译为稳定诗篇 ID、稳定诗句 ID、原文偏移、意象命中、多维情感和分析运行记录。
本地词典/规则结果标记为 `method=rules`；只有显式使用 `--llm` 生成的候选才标记
`method=llm`，并保留模型、prompt、输入哈希、置信度、失败和重试状态。

```powershell
# 无网络、无模型也可完成的全量基线
python tools/build_poetry_knowledge_base.py --rebuild

# 可选模型增强（需先配置 AGENT_LLM_*；默认/最高并发 64）
python tools/build_poetry_knowledge_base.py --llm --concurrency 64

# 小批量试跑
python tools/build_poetry_knowledge_base.py --rebuild --poet 李白 --limit 20
```

默认产物为 `output/assets/knowledge/poetry_knowledge.sqlite3` 及同目录 manifest。
页面和 Agent 只打开只读连接，所以查询不会触发模型请求，也不会修改语料。
当前随项目生成的全量快照包含 20,437 篇诗文、143,842 个稳定分句和
164,279 条规则分析；manifest 中 `analysis.llm=not_enriched` 明确表示尚未用外部
模型批量增强。配置提供商前应确认其并发配额；构建器会对 429/5xx 退避重试并保留断点。

### SiliconFlow Embeddings

聊天分析使用 `AGENT_LLM_*`；向量模型必须使用独立的 `AGENT_EMBEDDING_*`：

```powershell
$env:AGENT_EMBEDDING_BASE_URL="https://api.siliconflow.cn/v1"
$env:AGENT_EMBEDDING_API_KEY="YOUR_PRIVATE_KEY"
$env:AGENT_EMBEDDING_MODEL="BAAI/bge-m3"
python tools/build_poetry_embeddings.py --scope both --batch-size 16 --concurrency 8 --timeout 60 --retries 4
```

产物位于 `output/assets/knowledge/embeddings/<model>/<buildId>/`，包含只读元数据、
诗句/整诗 float32 归一化向量和 manifest；`current.json` 是唯一发布指针。模型、实际
维度、文本模板版本、主知识库 buildId/databaseSha256 和每个文件哈希均会记录，但不
记录 API Key。批量大小遵守接口的 `1..32` 限制，CLI 并发允许 `1..64`，实际值应按
SiliconFlow 账号 RPM/QPS 调整。超过 bge-m3 上下文的长文会按不超过 7,000 字符的
自然边界分块，并以字符长度加权平均后重新归一化，不丢弃正文。HTTP 400 批次会自动
二分隔离坏项；失败构建不会发布为完整索引，重跑同一命令会从检查点继续。
`--allow-partial` 仅保留带 `status=partial` 的调试 artifact；服务不会激活它。

## Agent Tools

- `generate_poet_route(poet, include_approximate=True, include_disputed=True)`
- `play_poem_scenes(poet, start_scene_id=None, autoplay=False)`
- `compare_imagery(terms=None, limit=8, chapter_id=None)`
- `search_poetry_knowledge(query="", poet=None, dynasty=None, imagery=None, emotion=None, mode="lexical", scope="all", limit=20, offset=0)`
- `get_poem_knowledge(poem_id)`
- `get_line_knowledge(line_id)`

六个处理器同时注册为 LangChain Tools 和 CopilotKit Actions。DeepAgents 的文件、编辑、搜索和命令工具全部从模型可见工具集中移除；system prompt 要求史料事实与诗词分析必须来自上述工具。OpenGenerativeUI 只可将 `payload` 临时渲染为解释图、SVG或交互部件，不参与事实计算。

## 配置与运行

依赖声明在 `pyproject.toml`，核心协议版本固定为 CopilotKit Python `0.1.94` 和 `ag-ui-langgraph` `0.0.42`。本次交付不安装依赖。

安装环境后，从本目录运行：

```powershell
# 参照 .env.example 在当前终端设置三个 AGENT_LLM_* 环境变量
python -m poetry_agent.main
```

默认监听 `127.0.0.1:8123`。模型变量缺失时服务仍可启动，`/health` 返回 `degraded`，目录和直接数据 Actions 仍可工作；AG-UI对话图只报告配置缺口。

`output/44_诗页.html` 可用 `file://` 完整离线浏览，但浏览器此时发送的
`Origin: null` 不在默认 CORS 允许范围，不能在线生成。需要在线译注时，先在项目根目录运行
`python tools/serve_output.py`，再用显示的本地 HTTP 地址打开页面，并把该页面的确切 origin
（例如 `http://127.0.0.1:8000`）加入 `AGENT_ALLOWED_ORIGINS`；不要放宽为通配符。

## HTTP 接口

- `POST /`：原生 AG-UI 流式 Agent 端点
- `GET /health`：模型、源文件和缓存状态
- `GET /catalog/poets`：88 位诗人及路线证据覆盖
- `POST /tools/generate_poet_route`：直连 `generate_poet_route`
- `POST /tools/play_poem_scenes`：直连 `play_poem_scenes`
- `POST /tools/compare_imagery`：直连 `compare_imagery`
- `POST /tools/search_poetry_knowledge`：可供 Agent/CopilotKit 使用的结构化检索
- `POST /tools/get_poem_knowledge` / `get_line_knowledge`：稳定 ID 详情
- `GET /knowledge/status`：知识库版本、计数和源哈希
- `GET /knowledge/search`：页面快速检索
- `GET /knowledge/poems/{poem_id}` / `lines/{line_id}`：页面详情
- `GET /knowledge/rich-guide/{poem_id}`：查询已有译注赏析
- `POST /knowledge/rich-guide`：返回已有译注或按需生成；要求上述 HTTP origin/CORS 配置，未配置 `AGENT_LLM_*` Key 时以 HTTP 503 降级，不影响只读页面
- `/copilotkit/`：CopilotKit Python 发现、Agent 和 Action 兼容入口
- `/docs`：FastAPI OpenAPI 文档

六个 `/tools/*` 端点使用与 LangChain Tools 相同的 Pydantic 输入模型，并转发到同一个 `PoetryDataService`；正常结果和非法参数都使用固定五字段结构。React 前端应直接把工具结果中的 `payload` 传给 ECharts 组件，不解析 Agent 的自然语言来构造数据。

## 测试

测试不调用网络，也不改项目根数据：

```powershell
.\.venv\Scripts\python.exe -m pytest
```

覆盖 88/6/82 目录契约、六位完整路线、160 词意象契约、系年精度过滤、严格参数校验、三个 FastAPI 工具端点、只读快照复制、陈旧快照拒绝、缓存目录边界，以及所有工具调用前后 `data/`、`output/` 全部文件哈希和 mtime 不变。
