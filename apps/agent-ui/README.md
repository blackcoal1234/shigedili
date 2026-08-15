# 诗行万里 Agent UI

这是独立于 `output/29_*.html` 至 `output/38_*.html` 的实验入口。离线展项继续由
Python 生成并可单独打开；本目录通过 CopilotKit / AG-UI 编排已有证据数据，再由
React 和 ECharts 渲染。

## 三项工具

- `generate_poet_route`：从审核行迹和候选编年快照生成可追溯路线；严格史料连线与
  “路径未载”的视觉转场分字段返回。
- `play_poem_scenes`：按史料系年播放逐诗篇镜头，默认每幕停驻并等待“下一步”。
- `compare_imagery`：比较审核词表内的唐宋每万字率及原句证据。

模型只负责选择工具和解释结构化结果。年份、地点、路线、统计值、证据等级和来源
均来自现有 Python 数据层；证据不足会返回 `insufficient_evidence`，不会用诗句地名
补写行程。

## 目录

- `agent/`：FastAPI、CopilotKit Python、AG-UI、缓存和领域工具。
- `web/`：Next.js、React、CopilotKit UI 和 ECharts 组件。
- `.cache/`：从离线生成 JSON 原子复制的运行缓存，不进入版本控制。
- `.run/`：统一启动器的 PID 和日志，不进入版本控制。

详细边界见 [ARCHITECTURE.md](ARCHITECTURE.md)，第三方归属见
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

## 安装与启动

首次运行：

```powershell
.\apps\agent-ui\start-dev.ps1 -Install
```

后续运行：

```powershell
.\apps\agent-ui\start-dev.ps1
```

查看已构建版本（启动更快，适合演示）：

```powershell
.\apps\agent-ui\start-dev.ps1 -Production
```

地址：

- Agent UI：`http://127.0.0.1:3000/`
- Agent API：`http://127.0.0.1:8123/docs`
- 稳定离线展项：`http://127.0.0.1:8770/29_参赛导航.html`

停止统一启动器创建的进程：

```powershell
.\apps\agent-ui\stop-dev.ps1
```

后端模型使用 OpenAI-compatible 配置；密钥只放环境变量：

```powershell
$env:AGENT_LLM_BASE_URL="https://PROVIDER.example/v1"
$env:AGENT_LLM_API_KEY="TOKEN"
$env:AGENT_LLM_MODEL="MODEL"
```

未配置模型时，后端以 degraded 模式启动，目录和三项确定性 REST Tool 仍可使用。

启动前可先生成诗句/意象/情感知识库：

```powershell
# 纯本地规则基线，无需模型密钥
python tools/build_poetry_knowledge_base.py --rebuild

# 配置 AGENT_LLM_* 后可选模型增强（默认/最高并发 64）
python tools/build_poetry_knowledge_base.py --llm --concurrency 64
```

Agent UI 顶部的“诗词知识库”使用只读 SQLite FTS 检索；查询阶段不会调用模型。
当前全量快照为 20,437 篇、143,842 个分句；规则基线已生成，外部模型未配置时
manifest 会诚实标记 `llm=not_enriched`，不会把规则分析冒充模型输出。

### SiliconFlow 向量索引

向量检索使用独立 sidecar，不改动主知识库。默认模型为 `BAAI/bge-m3`：

```powershell
$env:AGENT_EMBEDDING_BASE_URL="https://api.siliconflow.cn/v1"
$env:AGENT_EMBEDDING_API_KEY="YOUR_PRIVATE_KEY"
$env:AGENT_EMBEDDING_MODEL="BAAI/bge-m3"

# 首次建议从 8 路并发开始；确认账号限额后最高可调到 64
python tools/build_poetry_embeddings.py --scope both --batch-size 16 --concurrency 8 --timeout 60 --retries 4
```

构建器按批次持久化检查点，失败时保留 `.building` 目录；原命令重跑即可续建。
`--allow-partial` 只生成带 `status=partial` 的调试产物，服务不会将其激活为可查询索引。
完成后只原子切换 `output/assets/knowledge/embeddings/current.json`。页面继续使用
同一个知识库搜索入口，可选“关键词 / 语义 / 混合”；向量服务不可用时自动降级为
关键词检索。API Key 不写入数据库、manifest、日志或浏览器响应。大规模精确余弦检索
建议安装 NumPy：`pip install -e "apps/agent-ui/agent[vectors]"`。

## 验证

```powershell
apps\agent-ui\agent\.venv\Scripts\python.exe -m pytest apps\agent-ui\agent\tests -q
npm --prefix apps\agent-ui\web run lint
npm --prefix apps\agent-ui\web run typecheck
npm --prefix apps\agent-ui\web run test
npm --prefix apps\agent-ui\web run build
python tools\check_all.py --offline --keep-going
```

本轮行旅动画验收覆盖 `1440x900`、`700x900` 与 `390x844` 三个视口，检查史料实线、
视觉转场点线、五类透明刻符、连续弧线移动、反向回看、缺坐标切幕和页面溢出。
验收产物保存在：

- `output/playwright/agent_ui_song_print_acceptance.json`
- `output/playwright/agent_ui_song_print_1440.png`
- `output/playwright/agent_ui_song_print_700.png`
- `output/playwright/agent_ui_song_print_390.png`

OpenGenerativeUI 默认关闭，仅把已经返回的工具 payload 临时转换为解释图、SVG 或
交互部件，不修改史料数据。Uiverse Galaxy 只用于少量开关、加载态和播放按钮微交互。
