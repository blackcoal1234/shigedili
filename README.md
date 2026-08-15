# 诗行万里：唐宋诗词时空与意象情感

> 大数据分析技术 / Python 网络爬虫课程设计

本项目使用 Python 完成“网络采集 → JSON 原始数据 → MySQL 关系建模 → 文本与时空分析 → Pyecharts/Matplotlib 可视化 → 静态部署”的完整课程链路。

## 1. 数据规模

- 88 位唐宋诗人。
- 1772 首去重作品。
- 唐代 915 首，宋代 857 首。
- 六位核心诗人：李白、杜甫、白居易、苏轼、陆游、李清照。李白扩充至 55 首（用于精神地形图专题），其余五位各 20 首，核心样本共 155 首；意象比较页固定使用每人前 20 首、共 120 首可比样本。
- 当前有 86 条批准候选主张，导出 41 条作年作地富背景部分记录；完整富背景仍为 0 条。
- 精神地形图另有 23 条李白候选编年（B 级、status=candidate，存于 data/candidates/），与 41 条人工审核记录分层使用，不互相混入。
- 生平、行旅和创作地点使用独立审核数据，不从诗中地名直接推断。

1772 首属于课程级批量语料，适合展示并发采集、关系建模和自动化分析；项目不将其宣传为工业级海量数据。

## 2. 核心研究模块

### 诗人行旅与生命情感

首页按诗人切换，联动呈现六位诗人的审核行旅节点、生平处境、作品背景、原诗证据、意象词频和文本情感。地图连线只表示节点时间顺序，不代表真实道路。

### 唐宋诗歌创作活动中心迁移

只使用审核后的作品创作地点，按时期展示当前精细样本中的创作活动分布。诗中提及地点不参与该计算。

### 同一意象的跨诗人情感差异

比较“月、酒、舟、雁、雨”在六位诗人作品中的多标签情感、证据诗句和情感提升度，不再给每种意象绑定唯一固定情感。

### 诗人精神地形图（论证模块）

用人工双维度意象词典（五情感簇 + 1–5 级空间尺度）扫描李白编年可考的诗作，把意象命中折算为“情感值均值”与“空间尺度均值”两条曲线，叠加人生事件与地理行迹，观察五分期内的意象漂移。编年只来自可引用来源（候选编年 status=candidate 与人工审核记录），A/B 级实线呈现、C 级以“推定”样式区分，系年争议诗附各家观点；每处数字可回溯到具体诗句证据。

## 3. 技术路线

    requests + BeautifulSoup + ThreadPoolExecutor
        → data/poems.json
        → Python 清洗、词典匹配与审核数据
        → MySQL 8.0 / PyMySQL
        → Pyecharts / Matplotlib
        → output/*.html、*.png
        → Python ThreadingHTTPServer

主要依赖：

- requests、BeautifulSoup4：网页采集与解析。
- PyMySQL、MySQL 8.0：结构化存储。
- Pyecharts：交互地图、时间轴、热力与关系图。
- Matplotlib、Pillow：ER 图和静态图片。
- Playwright：页面交互与桌面/移动端视觉验收，可选；不用于绕过登录、验证码或访问限制。

## 4. 目录结构

    诗行万里/
    ├── 爬虫脚本/
    │   └── spider_gushiwen.py
    ├── 数据库操作脚本及数据库SQL/
    │   ├── schema.sql
    │   ├── db_init.py
    │   └── db_crud.py
    ├── 数据可视化脚本/
    │   ├── viz_00_er_diagram.py
    │   ├── viz_08_poem_browser.py
    │   ├── viz_09_dictionary_browser.py
    │   ├── viz_15_journey_emotion.py
    │   ├── viz_16_literary_centers.py
    │   ├── viz_17_imagery_emotion_compare.py
    │   ├── viz_18_data_quality.py
    │   ├── viz_19_life_trace_app.py
    │   ├── viz_20_spirit_terrain.py
    │   ├── viz_29_competition_index.py
    │   ├── viz_30_competition_home.py
    │   ├── viz_31_gaze_compass.py
    │   ├── viz_32_dual_map.py
    │   ├── viz_33_year759.py
    │   ├── viz_34_char_fingerprint.py
    │   ├── viz_35_solitude_hyperbole.py
    │   ├── viz_36_age_align.py
    │   ├── viz_37_soundscape.py
    │   ├── viz_38_imagery_tide.py
    │   └── viz_99_output_index.py
    ├── data/
    │   ├── poems.json
    │   ├── candidates/
    │   │   ├── poem_background_candidates.jsonl
    │   │   ├── background_collection_status.jsonl
    │   │   ├── poet_identity_status.jsonl
    │   │   └── libai_spirit_chronology.csv
    │   ├── place_dict.py
    │   ├── image_dict.py
    │   ├── imagery_emotion_rules.py
    │   ├── spirit_image_dict.py
    │   └── reviewed/
    │       ├── poet_journeys.json
    │       ├── verified_poem_backgrounds.jsonl
    │       └── verified_poem_contexts.csv
    ├── tools/
    │   ├── background_pipeline.py
    │   ├── background_adapters.py
    │   ├── background_contract.py
    │   ├── check_background_pipeline.py
    │   ├── check_all.py
    │   ├── check_theme_data.py
    │   ├── check_theme_outputs.py
    │   └── serve_output.py
    ├── output/
    │   ├── assets/
    │   ├── index.html
    │   └── manifest.json
    ├── config.py
    ├── run_all.py
    ├── .env.example
    └── requirements.txt

旧版词云、季节、翻译、流派画像和相似推荐脚本仍可作为历史参考，但不再进入主题版 run_all.py、output/index.html 和 manifest.json。

## 5. 安装

推荐 Python 3.11 以上。

    python -m pip install -r requirements.txt

如需 Playwright：

    python -m playwright install chromium

MySQL 凭据只从环境变量读取。PowerShell 示例：

    $env:SHIXING_MYSQL_HOST="127.0.0.1"
    $env:SHIXING_MYSQL_PORT="3306"
    $env:SHIXING_MYSQL_USER="root"
    $env:SHIXING_MYSQL_PASSWORD="你的本机密码"
    $env:SHIXING_MYSQL_DATABASE="shixing_wanli"

不要把真实密码写回 config.py、README 或提交文件。

## 6. 背景采集、审核与发布

背景系统使用“采集候选 → 证据内结构化 → 人工审核 → 批准发布”四层流程。CNKGraph、CBDB、CHGIS 和古诗文网公开页可由适配器低频采集；知网、国图、现代注本、搜韵及其他登录或受限来源只走人工题录与短引入口。遇到登录页、验证码、robots 或服务条款限制时记录 `blocked_by_policy`，不尝试绕过。

常用命令：

    python tools/background_pipeline.py collect --scope core --resume
    python tools/background_pipeline.py collect --scope all --max-poems-per-poet 1 --resume
    python tools/background_pipeline.py extract --scope core --llm
    python tools/background_pipeline.py review --port 8140
    python tools/background_pipeline.py import-manual --input data/candidates/manual_background_evidence.csv
    python tools/background_pipeline.py export
    python tools/background_pipeline.py check

可选模型使用 OpenAI 兼容接口，只能依据输入证据生成候选，不允许用模型自身知识补全事实：

    $env:BACKGROUND_LLM_BASE_URL="https://api.deepseek.com"
    $env:BACKGROUND_LLM_API_KEY="你的私有Key"
    $env:BACKGROUND_LLM_MODEL="deepseek-v4-flash"

Key 只放环境变量。审核台只绑定 `127.0.0.1:8140`。原始网页缓存在未跟踪的 `.cache/background_sources/`，正式页面只读取 `approved` 数据；第三方证据短引不超过 160 字。

核心样本扩容至 155 首后，其中 118 首有采集尝试状态（李白新增 35 首暂未进入背景采集；另有 2 首因正文修订暂未按正文哈希匹配到历史采集状态）；88 位诗人均有身份处理状态。41 条已批准记录目前只完成作年作地，尚未同时满足“120–220 字背景故事、逐句自有译文、至少 2 条注释和 1 条赏析要点”，因此完整版进度必须如实记为 `0/60`，不能用模型批量生成后直接宣称验收完成。

### 6.1 诗篇事实扩展发布门

作品候选通过“作品正文与 `body_hash` 精确匹配 → 作品级创作时间与地点均有
A/B 级证据 → 至少两个独立来源家族 → 逐条人工核验”后，才进入事实扩展。
CNKGraph `Writing/{id}`、`Writing/{id}/MapInfo` 或搜韵具体作品 ID 可承担作品
级时地证据；作者活动地、诗题地名、作者分页和 `PoemGeo.aspx` 聚合首页均不能
单独承担创作地点。证据不足或存在实质争议的诗篇保留为 `hold`。

    python tools/build_all_poet_fact_release.py
    python tools/check_all_poet_fact_release.py

正式产物为：

- `data/reviewed/verified_all_poet_fact_packages.jsonl`：通过门禁的原始事实包；
- `data/reviewed/verified_all_poet_fact_expansions.jsonl`：由事实包确定性生成的扩展文本；
- `data/reviewed/verified_all_poet_fact_release_summary.json`：88 人覆盖率、逐批统计与 hold 清单。

摘要中的 `release_status` 只有在 88 位诗人均至少有一首通过门禁时才为
`complete`；否则固定为 `partial`，不以候选或作者活动地填补缺口。
摘要还分别记录有来源坐标的事实包数量与诗人数；已核地点若没有来源坐标，保持空值而不做
自动地理编码猜测。扩展文案由门禁通过的题名、作年、历史地点、今地与已引用背景事实
确定性生成；`approximate` 年份会明确写作“约系于”。

## 7. 一键运行

使用已有 1772 首语料、导入 MySQL 并生成全部主题页面：

    python run_all.py --no-crawl

清空并重建主题版数据库：

    python run_all.py --no-crawl --reset-db

不连接 MySQL，仅使用 JSON/CSV 生成离线可视化：

    python run_all.py --no-crawl --skip-db

强制重新抓取全部种子诗人：

    python run_all.py --recrawl

重新抓取会访问公开网站，应控制频率并遵守网站服务条款。答辩现场建议只使用已有缓存，避免网络状态影响演示。

`run_all.py` 默认只读取已经批准的数据，不自动运行背景采集、不访问付费模型，也不会把候选记录发布到页面。

## 8. 输出

| 文件 | 内容 |
|---|---|
| output/index.html | 可切换诗人的生命痕迹交互首页 |
| output/15_诗人行旅与生命情感.html | 行旅、生平处境和文本情感 |
| output/16_唐宋诗歌创作活动中心迁移.html | 审核创作地点的时期分布 |
| output/17_同一意象的诗人情感差异.html | 同意象跨诗人比较 |
| output/18_数据质量与来源覆盖.html | 数据规模、来源等级和覆盖缺口 |
| output/20_诗人精神地形图.html | 李白意象漂移五分期论证（三线叠加与证据表） |
| output/08_诗作检索.html | 原诗证据检索 |
| output/09_词典浏览.html | 古地名与意象词典 |
| output/00_主题数据库ER图.png | 扩展数据库 ER 图 |
| output/29_参赛导航.html | 参赛版 30-38 号页面总导航 |
| output/30_诗行万里_参赛版.html | 参赛版主叙事与数据资产总览 |
| output/31_凝望罗盘.html | 方位凝望的文本地理与原句证据 |
| output/32_身与心双层地图.html | 审核行旅与诗中遥想地名联动 |
| output/33_平行时空759.html | 公元 759 年李白、杜甫同年对读 |
| output/34_一字识诗人.html | 字符级统计签名与竞猜 |
| output/35_两种孤独与夸张签名.html | 孤独语境与数字夸张对比 |
| output/36_同龄对齐.html | 六位诗人虚岁对齐泳道 |
| output/37_可听的诗.html | 声音意象与诗人声景 |
| output/38_唐宋意象潮汐.html | 唐宋客观意象率与审核节点五章显影 |
| output/manifest.json | 输出大小、时间和 SHA-256 |

## 9. 本地部署

    python tools/serve_output.py

默认地址：

http://127.0.0.1:8000/index.html

若端口被占用，服务会从后续端口中选择可用端口。output 目录也可以直接复制到 Nginx 或其他静态网站服务器；浏览生成结果不需要连接 MySQL。

### CopilotKit 实验入口

`apps/agent-ui/` 是独立的联网实验层，不进入 `run_all.py`、离线导航或
`output/manifest.json`，因此 29–38 号页面仍可作为稳定离线展项使用。实验入口把
“生成诗人路线”“播放诗篇镜头”“比较唐宋意象”注册为结构化 Agent Tools；模型只做
编排，年份、地点、统计、证据等级和来源继续由现有 Python 数据层提供。

首次安装并同时启动离线展项、Agent API 和 React 前端：

    .\apps\agent-ui\start-dev.ps1 -Install

后续启动与停止：

    .\apps\agent-ui\start-dev.ps1
    .\apps\agent-ui\stop-dev.ps1

实验前端为 `http://127.0.0.1:3000/`，Agent API 为
`http://127.0.0.1:8123/docs`，离线展项使用
`http://127.0.0.1:8770/29_参赛导航.html`。详细配置与数据边界见
`apps/agent-ui/README.md` 和 `apps/agent-ui/ARCHITECTURE.md`。

## 10. 质量检查

列出检查项：

    python tools/check_all.py --list

执行全部离线检查：

    python tools/check_all.py --offline --keep-going

检查覆盖：

- Python 语法。
- 1772 首基础语料（基线 ≥1770）与六位核心诗人的核心样本；意象比较页固定使用每人前 20 首、共 120 首可比样本。
- 120 首核心作品采集尝试、88 位身份状态、候选审核状态、证据短引与发布完整度。
- 精神意象词典自检（簇合法、尺度 1–5、无重复、尺度依据齐全）、李白候选编年（期2–5 每期至少 3 条、来源与等级合规）与精神地形图页面（echarts 初始化、推定样式）。
- 行旅节点字段、坐标、来源与等级。
- 创作背景与现有作品精确匹配。
- 同意象计算口径和证据诗句。
- 核心 HTML、参赛版 29-38 号产物、离线脚本依赖、入口链接和 manifest 哈希。
- 旧版非主题输出已从正式 output 移除。

## 11. 数据解释边界

- t_poem_place 是诗中提及地点，不是创作地点。
- t_poem_context 是经过审核的作品创作时间与地点。
- t_journey_stop 是经过审核的诗人到访或停留节点。
- 生平处境和诗词文本情感是两条不同数据。
- A/B 级事实进入主要分析；C 级以推定样式展示；D 级不进入正式结论。
- 模型和规则结果必须显示方法、样本数、证据和置信度。
- 外部事件只能作为可核实的时代与生平背景，不能直接解释成诗人的真实心理。
- 精神地形图的意象曲线描述作品文本特征，不是诗人真实心理；候选编年为 B/C 级推定，未经人工审核的部分一律以推定样式（虚线、空心点、“推定”徽章）展示。
