"""生成主题版离线总入口与可核验 manifest。"""
from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "output"
POEMS_JSON = ROOT / "data" / "poems.json"
JOURNEYS_JSON = ROOT / "data" / "reviewed" / "poet_journeys.json"
CONTEXTS_CSV = ROOT / "data" / "reviewed" / "verified_poem_contexts.csv"
POEM_PAGE_DATA_ASSET = "assets/poem_page/poem_page_data.js"
TEXT_OUTPUT_SUFFIXES = {".css", ".csv", ".html", ".js", ".json", ".svg", ".txt"}


@dataclass(frozen=True)
class OutputItem:
    title: str
    href: str
    kind: str
    group: str
    note: str
    source_script: str


OUTPUTS = (
    OutputItem(
        "诗人行旅与生命情感",
        "15_诗人行旅与生命情感.html",
        "地图 / 时间轴",
        "核心研究",
        "六位诗人的到访节点、生平处境与诗词文本情感分层呈现。",
        "数据可视化脚本/viz_15_journey_emotion.py",
    ),
    OutputItem(
        "唐宋诗歌创作活动中心迁移",
        "16_唐宋诗歌创作活动中心迁移.html",
        "时序地图",
        "核心研究",
        "只使用审核后的创作地点，展示当前精细样本中的创作活动分布。",
        "数据可视化脚本/viz_16_literary_centers.py",
    ),
    OutputItem(
        "同一意象的诗人情感差异",
        "17_同一意象的诗人情感差异.html",
        "热力 / 证据",
        "核心研究",
        "比较月、酒、舟、雁、雨在六位诗人作品中的语境情感与提升度。",
        "数据可视化脚本/viz_17_imagery_emotion_compare.py",
    ),
    OutputItem(
        "诗人精神地形图",
        "20_诗人精神地形图.html",
        "论证 / 三线叠加",
        "核心研究",
        "李白编年诗的意象情感值与空间尺度五分期漂移；候选编年 B 级实证与 C 级推定分样式展示。",
        "数据可视化脚本/viz_20_spirit_terrain.py",
    ),
    OutputItem(
        "作品目录",
        "29_参赛导航.html",
        "作品导航",
        "作品系列",
        "汇总 30-44 号页面，作为现场演示与展项切换入口。",
        "数据可视化脚本/viz_29_competition_index.py",
    ),
    OutputItem(
        "诗行万里 · 总入口",
        "30_诗行万里_参赛版.html",
        "叙事总览",
        "作品系列",
        "一页总览语料、审核行旅节点、意象词典、数据来源与系列展项。",
        "数据可视化脚本/viz_30_competition_home.py",
    ),
    OutputItem(
        "凝望罗盘",
        "31_凝望罗盘.html",
        "玫瑰图 / 证据",
        "作品系列",
        "扫描方位凝望并按方向、句级情感和原句证据展开。",
        "数据可视化脚本/viz_31_gaze_compass.py",
    ),
    OutputItem(
        "身与心双层地图",
        "32_身与心双层地图.html",
        "双层地图",
        "作品系列",
        "联动对照审核行旅节点与诗中遥想地名。",
        "数据可视化脚本/viz_32_dual_map.py",
    ),
    OutputItem(
        "平行时空 759",
        "33_平行时空759.html",
        "同年对读",
        "作品系列",
        "对读公元 759 年李白与杜甫作品，并展开系年与逐句证据。",
        "数据可视化脚本/viz_33_year759.py",
    ),
    OutputItem(
        "一字识诗人",
        "34_一字识诗人.html",
        "统计竞猜",
        "作品系列",
        "以字符级统计签名呈现六位诗人的区别性用字。",
        "数据可视化脚本/viz_34_char_fingerprint.py",
    ),
    OutputItem(
        "两种孤独与夸张签名",
        "35_两种孤独与夸张签名.html",
        "词典统计 / 对比",
        "作品系列",
        "比较孤独语境光谱与数字夸张的诗人签名。",
        "数据可视化脚本/viz_35_solitude_hyperbole.py",
    ),
    OutputItem(
        "同龄对齐",
        "36_同龄对齐.html",
        "年龄泳道",
        "作品系列",
        "把六位诗人按虚岁对齐，对读同龄作品的情绪与意象。",
        "数据可视化脚本/viz_36_age_align.py",
    ),
    OutputItem(
        "可听的诗",
        "37_可听的诗.html",
        "声景统计",
        "作品系列",
        "统计诗中明写的声音意象并形成诗人声景。",
        "数据可视化脚本/viz_37_soundscape.py",
    ),
    OutputItem(
        "意象潮汐",
        "38_唐宋意象潮汐.html",
        "时序排名 / 朝代对比",
        "作品系列",
        "以每万正文汉字率比较唐宋客观意象，并按审核节点五章显影。",
        "数据可视化脚本/viz_38_imagery_tide.py",
    ),
    OutputItem(
        "诗人自述生命卷",
        "39_诗人自述生命卷.html",
        "生命叙事 / 情感曲线",
        "作品系列",
        "88 位诗人分四轮推进；首轮 22 位以第一视角重构、诗篇证据与情感曲线展开。",
        "数据可视化脚本/viz_39_first_person_lives.py",
    ),
    OutputItem(
        "山河证道",
        "40_山河证道.html",
        "地图闯关 / 证据学习",
        "作品系列",
        "依据审核作地设计四章地图闯关，并以提示、学习卡与诗印串联考据证据。",
        "数据可视化脚本/viz_40_shanhe_quest.py",
    ),
    OutputItem(
        "意象地理",
        "41_意象地理.html",
        "区域矩阵 / 原句证据",
        "作品系列",
        "以文化地理分区和意象提升度矩阵展示地域差异，并下钻到原句证据。",
        "数据可视化脚本/viz_41_imagery_geography.py",
    ),
    OutputItem(
        "被想象的地方",
        "42_被想象的地方.html",
        "亲历 / 想象对照",
        "作品系列",
        "对照审核作地与正文地名，区分亲历书写和身在别处的想象。",
        "数据可视化脚本/viz_42_dreamed_places.py",
    ),
    OutputItem(
        "飞花令·加行卷",
        "43_飞花令加行.html",
        "支线题库 / 互动学习",
        "作品系列",
        "通过地名飞花令、意象归乡与古今地名连线复习项目证据。",
        "数据可视化脚本/viz_43_side_quest.py",
    ),
    OutputItem(
        "数据质量与来源覆盖",
        "18_数据质量与来源覆盖.html",
        "质量看板",
        "方法与质量",
        "公开基础语料、精细考证、来源等级和缺失数据的覆盖情况。",
        "数据可视化脚本/viz_18_data_quality.py",
    ),
    OutputItem(
        "诗作检索",
        "08_诗作检索.html",
        "证据检索",
        "证据工具",
        "按作者、朝代和关键词返回原诗，作为图表结论的文本下钻入口。",
        "数据可视化脚本/viz_08_poem_browser.py",
    ),
    OutputItem(
        "赏析诗页",
        "44_诗页.html",
        "赏析 / 深链下钻",
        "证据工具",
        "一首诗一页：原诗意象高亮、导读卡、审核背景与三层层级作年作地，全部展项可下钻到 #poem= 深链。",
        "数据可视化脚本/viz_44_poem_page.py",
    ),
    OutputItem(
        "古地名与意象词典",
        "09_词典浏览.html",
        "词典",
        "证据工具",
        "核对古今地名、意象词和实际命中诗句。",
        "数据可视化脚本/viz_09_dictionary_browser.py",
    ),
    OutputItem(
        "主题数据库 ER 图",
        "00_主题数据库ER图.png",
        "数据库",
        "方法与质量",
        "展示基础诗词、创作时空、行旅、生平事件、多标签情感与来源证据表。",
        "数据可视化脚本/viz_00_er_diagram.py",
    ),
)

MANIFEST_ASSETS = (
    OutputItem(
        "诗页数据资产",
        POEM_PAGE_DATA_ASSET,
        "离线数据",
        "运行资产",
        "44 号赏析诗页依赖的完整离线数据。",
        "tools/build_poem_page_data.py",
    ),
)


def release_bytes(path: Path) -> bytes:
    payload = path.read_bytes()
    if path.suffix.lower() in TEXT_OUTPUT_SUFFIXES:
        return payload.replace(b"\r\n", b"\n")
    return payload


def sha256(path: Path) -> str:
    return hashlib.sha256(release_bytes(path)).hexdigest()


def human_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / 1024 / 1024:.1f} MB"


def flatten_journey_count() -> int:
    if not JOURNEYS_JSON.exists():
        return 0
    payload = json.loads(JOURNEYS_JSON.read_text(encoding="utf-8-sig"))
    if isinstance(payload, list):
        return len(payload)
    if isinstance(payload, dict) and isinstance(payload.get("journeys"), list):
        return len(payload["journeys"])
    if isinstance(payload, dict):
        return sum(
            len(row.get("events", row.get("nodes", row.get("stops", []))))
            for row in payload.get("poets", [])
            if isinstance(row, dict)
        )
    return 0


def context_count() -> int:
    if not CONTEXTS_CSV.exists():
        return 0
    with CONTEXTS_CSV.open("r", encoding="utf-8-sig", newline="") as handle:
        return sum(1 for _ in csv.DictReader(handle))


def corpus_stats() -> tuple[int, int, int, int]:
    poems = json.loads(POEMS_JSON.read_text(encoding="utf-8"))
    poets = {
        str(row.get("poet") or row.get("author") or "")
        for row in poems
    }
    tang = sum((row.get("dynasty") or "") == "唐" for row in poems)
    song = sum((row.get("dynasty") or "") == "宋" for row in poems)
    return len(poems), len(poets), tang, song


def item_card(item: OutputItem) -> str:
    path = OUTPUT_DIR / item.href
    ready = path.exists() and path.stat().st_size > 0
    status = "已生成" if ready else "待生成"
    size = human_size(path.stat().st_size) if ready else "—"
    href = escape(item.href) if ready else "#"
    disabled = "" if ready else ' aria-disabled="true" class="module-card is-missing"'
    if ready:
        disabled = ' class="module-card"'
    return f"""
      <a href="{href}"{disabled} data-group="{escape(item.group)}"
         data-search="{escape(item.title + item.kind + item.note)}">
        <div class="module-meta">
          <span>{escape(item.group)}</span>
          <span>{escape(item.kind)}</span>
        </div>
        <h2>{escape(item.title)}</h2>
        <p>{escape(item.note)}</p>
        <div class="module-foot">
          <span class="status {'ready' if ready else ''}">{status}</span>
          <span>{size}</span>
        </div>
      </a>
    """


def write_manifest() -> None:
    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")
    rows = []
    for item in (*OUTPUTS, *MANIFEST_ASSETS):
        path = OUTPUT_DIR / item.href
        row = asdict(item)
        row.update(
            {
                "exists": path.exists(),
                "bytes": len(release_bytes(path)) if path.exists() else 0,
                "sha256": sha256(path) if path.exists() else "",
                "modified_at": (
                    datetime.fromtimestamp(path.stat().st_mtime)
                    .astimezone()
                    .isoformat(timespec="seconds")
                    if path.exists()
                    else ""
                ),
            }
        )
        rows.append(row)
    payload = {
        "project": "诗行万里·唐宋诗词时空与意象情感",
        "version": "theme-v1",
        "generated_at": generated_at,
        "outputs": rows,
    }
    (OUTPUT_DIR / "manifest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
        newline="\n",
    )


def render() -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    poem_count, poet_count, tang_count, song_count = corpus_stats()
    journeys = flatten_journey_count()
    contexts = context_count()
    cards = "".join(item_card(item) for item in OUTPUTS)
    generated = sum((OUTPUT_DIR / item.href).exists() for item in OUTPUTS)
    groups = ("全部", "核心研究", "作品系列", "证据工具", "方法与质量")
    filters = "".join(
        f'<button type="button" data-filter="{escape(group)}" '
        f'class="filter-button{" is-active" if group == "全部" else ""}">{escape(group)}</button>'
        for group in groups
    )
    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>诗行万里 · 唐宋诗词时空与意象情感</title>
  <link rel="icon" href="data:,">
  <style>
    :root {{
      --ink: #101828; --muted: #667085; --line: #d0d5dd; --surface: #ffffff;
      --page: #f2f4f7; --cyan: #087e8b; --coral: #d34f3f; --green: #287a56;
      --gold: #9a6700;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0; color: var(--ink); background: var(--page);
      font-family: "Microsoft YaHei", "PingFang SC", "Segoe UI", sans-serif;
      letter-spacing: 0;
    }}
    header {{
      border-bottom: 1px solid var(--line); background: #111827; color: #fff;
    }}
    .header-inner, main, footer {{ width: min(1240px, calc(100% - 32px)); margin: 0 auto; }}
    .header-inner {{ padding: 30px 0 26px; }}
    .eyebrow {{ margin: 0 0 7px; color: #67e8f9; font-size: 13px; font-weight: 700; }}
    h1 {{ margin: 0; font-size: clamp(28px, 4vw, 44px); line-height: 1.18; letter-spacing: 0; }}
    .lead {{ max-width: 880px; margin: 12px 0 0; color: #cbd5e1; line-height: 1.7; }}
    .metrics {{
      display: grid; grid-template-columns: repeat(6, minmax(0, 1fr));
      gap: 1px; margin-top: 24px; background: #374151; border: 1px solid #374151;
    }}
    .metric {{ min-height: 72px; padding: 13px 14px; background: #1f2937; }}
    .metric strong {{ display: block; font-size: 22px; }}
    .metric span {{ color: #9ca3af; font-size: 12px; }}
    main {{ padding: 24px 0 46px; }}
    .toolbar {{
      display: flex; align-items: center; gap: 12px; flex-wrap: wrap;
      padding-bottom: 18px; border-bottom: 1px solid var(--line);
    }}
    .filters {{ display: flex; gap: 8px; flex-wrap: wrap; }}
    .filter-button {{
      border: 1px solid #98a2b3; background: #fff; color: #344054;
      min-height: 36px; padding: 0 13px; border-radius: 4px; cursor: pointer;
      font: inherit; font-size: 13px;
    }}
    .filter-button.is-active {{ background: var(--cyan); border-color: var(--cyan); color: #fff; }}
    .search {{
      margin-left: auto; width: min(320px, 100%); height: 38px;
      border: 1px solid #98a2b3; border-radius: 4px; padding: 0 12px; font: inherit;
    }}
    .module-grid {{
      display: grid; grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 14px; margin-top: 18px;
    }}
    .module-card {{
      display: flex; flex-direction: column; min-height: 220px; padding: 19px;
      color: inherit; text-decoration: none; background: var(--surface);
      border: 1px solid var(--line); border-top: 4px solid var(--cyan); border-radius: 6px;
      transition: transform .16s ease, border-color .16s ease;
    }}
    .module-card:nth-child(3n+2) {{ border-top-color: var(--coral); }}
    .module-card:nth-child(3n) {{ border-top-color: var(--green); }}
    .module-card:hover {{ transform: translateY(-2px); border-color: #667085; }}
    .module-card.is-hidden {{ display: none; }}
    .module-card.is-missing {{ opacity: .58; pointer-events: none; }}
    .module-meta, .module-foot {{
      display: flex; align-items: center; justify-content: space-between;
      gap: 12px; color: var(--muted); font-size: 12px;
    }}
    .module-card h2 {{ margin: 24px 0 9px; font-size: 20px; line-height: 1.35; }}
    .module-card p {{ margin: 0; color: #475467; line-height: 1.7; flex: 1; }}
    .module-foot {{ padding-top: 18px; }}
    .status {{ color: #b42318; font-weight: 700; }}
    .status.ready {{ color: #067647; }}
    .boundary {{
      margin-top: 22px; padding: 18px 20px; border-left: 4px solid var(--gold);
      background: #fffaeb; color: #4e3b00; line-height: 1.75;
    }}
    footer {{ padding: 20px 0 34px; color: var(--muted); font-size: 13px; }}
    @media (max-width: 900px) {{
      .metrics {{ grid-template-columns: repeat(3, minmax(0, 1fr)); }}
      .module-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
    }}
    @media (max-width: 620px) {{
      .header-inner, main, footer {{ width: min(100% - 22px, 1240px); }}
      .metrics {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .module-grid {{ grid-template-columns: 1fr; }}
      .search {{ margin-left: 0; width: 100%; }}
    }}
  </style>
</head>
<body>
  <header>
    <div class="header-inner">
      <p class="eyebrow">PYTHON CRAWLER · MYSQL · PYECHARTS</p>
      <h1>诗行万里</h1>
      <p class="lead">唐宋诗人的生命轨迹、诗歌创作活动分布与同一意象的跨诗人情感差异。所有精细时空结论均绑定来源等级，基础语料与考证样本分层呈现。</p>
      <div class="metrics">
        <div class="metric"><strong>{poem_count}</strong><span>基础作品</span></div>
        <div class="metric"><strong>{poet_count}</strong><span>诗人</span></div>
        <div class="metric"><strong>{tang_count}</strong><span>唐代作品</span></div>
        <div class="metric"><strong>{song_count}</strong><span>宋代作品</span></div>
        <div class="metric"><strong>{contexts}</strong><span>创作背景</span></div>
        <div class="metric"><strong>{journeys}</strong><span>行旅节点</span></div>
      </div>
    </div>
  </header>
  <main>
    <div class="toolbar">
      <div class="filters">{filters}</div>
      <input class="search" id="moduleSearch" type="search" placeholder="检索诗人、意象或模块" aria-label="检索模块">
    </div>
    <div class="module-grid" id="moduleGrid">{cards}</div>
    <div class="boundary">
      当前共有 {generated}/{len(OUTPUTS)} 项成果已生成。诗中提及地点只用于文本地理分析；创作地点与诗人到访地点来自独立审核数据，二者不能互相替代。
    </div>
  </main>
  <footer>生成时间：{escape(datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S"))} · 数据与方法版本详见 manifest.json</footer>
  <script>
    const cards = [...document.querySelectorAll('.module-card')];
    const buttons = [...document.querySelectorAll('.filter-button')];
    const search = document.getElementById('moduleSearch');
    let activeGroup = '全部';
    function applyFilters() {{
      const query = search.value.trim().toLowerCase();
      cards.forEach(card => {{
        const groupOK = activeGroup === '全部' || card.dataset.group === activeGroup;
        const textOK = !query || card.dataset.search.toLowerCase().includes(query);
        card.classList.toggle('is-hidden', !(groupOK && textOK));
      }});
    }}
    buttons.forEach(button => button.addEventListener('click', () => {{
      activeGroup = button.dataset.filter;
      buttons.forEach(item => item.classList.toggle('is-active', item === button));
      applyFilters();
    }}));
    search.addEventListener('input', applyFilters);
  </script>
</body>
</html>
"""
    (OUTPUT_DIR / "index.html").write_text(
        html,
        encoding="utf-8",
        newline="\n",
    )
    write_manifest()
    print(f"  [ok] saved {OUTPUT_DIR / 'index.html'}")
    print(f"  [ok] saved {OUTPUT_DIR / 'manifest.json'}")


if __name__ == "__main__":
    render()
