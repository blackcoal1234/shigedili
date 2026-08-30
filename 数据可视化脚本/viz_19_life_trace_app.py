"""生成“诗人生命痕迹”交互首页。

首页把六位重点诗人的审核行旅节点、关联诗作、创作背景、意象词频和
文本情感放到同一个联动界面。所有数据均在 Python 中整理后内嵌到静态
HTML，部署后不需要数据库或远程接口。
"""
from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from data.image_dict import IMAGE_DICT
from data.imagery_emotion_rules import emotion_matches
from tools.famous_poet_corpus import load_analysis_poems
from viz_99_output_index import write_manifest


OUTPUT_DIR = ROOT / "output"
OUT_HTML = OUTPUT_DIR / "index.html"
POEMS_JSON = ROOT / "data" / "poems.json"
JOURNEYS_JSON = ROOT / "data" / "reviewed" / "poet_journeys.json"
CONTEXTS_CSV = ROOT / "data" / "reviewed" / "verified_poem_contexts.csv"
CORPUS_PATH = "data/analysis/famous_poets_full.jsonl.gz"
CANONICAL_PATH = "data/poems.json"
TARGET_POETS = ("李白", "杜甫", "白居易", "苏轼", "陆游", "李清照")

# 行旅数据早于 canonical 稳定身份字段建立，节点本身只有诗题。这里把每个
# 审核节点一次性钉到 data/poems.json 的 source_poem_id；运行时只按该 ID
# 取原诗，并进一步回配 analysis_full 的 work_id。诗题仅用于发现映射过期，
# 绝不作为取诗或同题合并键。
JOURNEY_CANONICAL_IDS = {
    "libai-0725-jingmen": "d50eb19399e6",
    "libai-0728-wuhan": "d3f231047aef",
    "libai-0742-changan": "170df91879a2",
    "libai-0744-changan-departure": "870828ca8aaa",
    "libai-0753-xuancheng": "731e2a19594e",
    "libai-0759-baidi": "0f81015a040c",
    "dufu-0735-taian": "efec283b31e0",
    "dufu-0751-changan": "977076fa07f4",
    "dufu-0757-changan": "89d3a63c6d7f",
    "dufu-0759-qinzhou": "ad6f7cfa10c2",
    "dufu-0761-chengdu": "8e9ecc95d6a4",
    "dufu-0766-kuizhou": "3fd388b378db",
    "dufu-0768-yueyang": "c05fb9a17f71",
    "baijuyi-0800-changan": "b7820a12ebaa",
    "baijuyi-0805-zhouzhi": "796882166eaf",
    "baijuyi-0815-jiangzhou": "0581b0ba8bb4",
    "baijuyi-0817-lushan": "5e26797704a7",
    "baijuyi-0822-hangzhou": "af218ed70405",
    "baijuyi-0825-suzhou": "6ad0636b01a9",
    "sushi-1061-mianchi": "31bc973d596d",
    "sushi-1071-hangzhou": "8949464433f0",
    "sushi-1075-mizhou": "85b8792a66ac",
    "sushi-1080-huangzhou": "6b30455fdd3c",
    "sushi-1084-lushan": "f2f5469a6044",
    "sushi-1094-huizhou": "69a11cbab0b4",
    "luyou-1155-shenyuan": "d5ac0bd52789",
    "luyou-1167-shanyin": "09294abb5f67",
    "luyou-1172-nanzheng": "bf183dbd63bc",
    "luyou-1186-linan": "0ccd54b5b58a",
    "luyou-1192-shanyin": "beab5faf1894",
    "luyou-1199-shenyuan": "c69e5720e858",
    "luyou-1210-shanyin": "966c8a76211f",
    "liqingzhao-1103-kaifeng": "b7f6fef5bb0b",
    "liqingzhao-1108-yidu": "324219410b89",
    "liqingzhao-1109-yidu": "96689ee0c664",
    "liqingzhao-1121-changle": "ba87db9a6f2b",
    "liqingzhao-1129-wujiang": "e4cd80aceb52",
    "liqingzhao-1147-linan": "f82821b9d569",
}

PROFILE_NOTES = {
    "李白": "开阔想象与强烈自我表达并存；受挫节点中的诗句仍常保留转折性的昂扬力量。",
    "杜甫": "个体遭际与时代苦难彼此缠绕，私人感受不断延伸到民生、家国与历史现场。",
    "白居易": "叙事、日常经验与社会关切并重，仕途起伏和闲适自守在不同阶段交替出现。",
    "苏轼": "贬谪压力与自我调适反复并置；所谓旷达并非没有悲苦，而是对困境的持续回应。",
    "陆游": "家国理想、个人衰老与未酬之志长期叠加，晚年文本仍保留鲜明的行动愿望。",
    "李清照": "个人生活、时代离乱与南渡经验相互叠映，明快、相思和沉痛在生平转折前后形成鲜明对照。",
}

PROFILE_TAGS = {
    "李白": "宏阔想象 · 受挫反弹",
    "杜甫": "现实关切 · 沉郁递进",
    "白居易": "叙事日常 · 进退自持",
    "苏轼": "逆境调适 · 悲旷并置",
    "陆游": "家国执念 · 暮年未息",
    "李清照": "南渡转折 · 悲欢对照",
}


def load_poems() -> list[dict[str, str]]:
    rows = json.loads(POEMS_JSON.read_text(encoding="utf-8"))
    return [
        {
            "poet": str(row.get("poet") or row.get("author") or ""),
            "title": str(row.get("title") or ""),
            "body": str(row.get("body") or ""),
            "dynasty": str(row.get("dynasty") or ""),
            "school": str(row.get("school") or "未标注"),
            "source_poem_id": str(row.get("source_poem_id") or ""),
            "body_hash": str(row.get("body_hash") or ""),
        }
        for row in rows
    ]


def load_contexts() -> dict[tuple[str, str], dict[str, str]]:
    if not CONTEXTS_CSV.exists():
        return {}
    with CONTEXTS_CSV.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return {
        (str(row.get("poet") or "").strip(), str(row.get("title") or "").strip()): {
            "year": "-".join(
                part
                for part in (str(row.get("year_start") or ""), str(row.get("year_end") or ""))
                if part
            ),
            "historical_place": str(row.get("historical_place") or "").strip(),
            "modern_city": str(row.get("modern_city") or "").strip(),
            "source_name": str(row.get("source_name") or "").strip(),
            "source_url": str(row.get("source_url") or "").strip(),
            "source_note": str(row.get("source_note") or "").strip(),
            "fact_grade": str(row.get("fact_grade") or "").strip(),
        }
        for row in rows
    }


def analysis_canonical_ids(row: dict[str, object]) -> tuple[str, ...]:
    """Return canonical aliases carried by one analysis record, in stable order."""
    raw_ids: list[object] = [row.get("canonical_gushiwen_id")]
    raw_ids.extend(row.get("canonical_gushiwen_ids") or [])
    raw_ids.extend(
        source.get("source_work_id")
        for source in row.get("sources", [])
        if isinstance(source, dict) and source.get("source_dataset") == "canonical"
    )
    return tuple(dict.fromkeys(str(value or "").strip() for value in raw_ids if value))


def build_identity_indexes(
    canonical_rows: list[dict[str, str]],
    analysis_rows: list[dict[str, object]],
) -> tuple[
    dict[tuple[str, str], dict[str, str]],
    dict[tuple[str, str], dict[str, object]],
]:
    """Index both layers by exact canonical ID; titles never participate."""
    canonical_by_id: dict[tuple[str, str], dict[str, str]] = {}
    for row in canonical_rows:
        poet = str(row.get("poet") or row.get("author") or "").strip()
        canonical_id = str(row.get("source_poem_id") or "").strip()
        if not poet or not canonical_id:
            raise ValueError("canonical 诗作缺少 poet/source_poem_id")
        key = (poet, canonical_id)
        if key in canonical_by_id:
            raise ValueError(f"canonical 稳定身份重复：{key}")
        canonical_by_id[key] = row

    analysis_by_canonical_id: dict[tuple[str, str], dict[str, object]] = {}
    for row in analysis_rows:
        poet = str(row.get("poet") or row.get("author") or "").strip()
        work_id = str(row.get("work_id") or "").strip()
        if not poet or not work_id:
            raise ValueError("analysis_full 诗作缺少 poet/work_id")
        for canonical_id in analysis_canonical_ids(row):
            key = (poet, canonical_id)
            existing = analysis_by_canonical_id.get(key)
            if existing is not None and existing.get("work_id") != work_id:
                raise ValueError(f"canonical ID 串联到多个全作品身份：{key}")
            analysis_by_canonical_id[key] = row
    return canonical_by_id, analysis_by_canonical_id


def bind_contexts_to_canonical_ids(
    contexts: dict[tuple[str, str], dict[str, str]],
    journey_groups: dict[str, dict[str, object]],
    identity_map: dict[str, str] = JOURNEY_CANONICAL_IDS,
) -> dict[tuple[str, str], dict[str, str]]:
    """Bind legacy context rows to the node's audited canonical ID once."""
    nodes_by_label: dict[tuple[str, str], list[str]] = {}
    for poet, group in journey_groups.items():
        for node in group.get("nodes", []):
            label = (poet, str(node.get("linked_poem", {}).get("title") or ""))
            nodes_by_label.setdefault(label, []).append(str(node.get("id") or ""))

    bound: dict[tuple[str, str], dict[str, str]] = {}
    for label, context in contexts.items():
        node_ids = nodes_by_label.get(label, [])
        if not node_ids:
            continue
        if len(node_ids) != 1:
            raise ValueError(f"创作背景无法唯一绑定审核节点：{label} -> {node_ids}")
        canonical_id = identity_map.get(node_ids[0])
        if not canonical_id:
            raise KeyError(f"审核节点缺少 canonical 稳定身份：{node_ids[0]}")
        key = (label[0], canonical_id)
        if key in bound:
            raise ValueError(f"canonical 创作背景重复：{key}")
        bound[key] = context
    return bound


def resolve_node_poem(
    poet: str,
    node: dict[str, object],
    canonical_by_id: dict[tuple[str, str], dict[str, str]],
    analysis_by_canonical_id: dict[tuple[str, str], dict[str, object]],
    identity_map: dict[str, str] = JOURNEY_CANONICAL_IDS,
) -> tuple[dict[str, str], dict[str, object]]:
    """Resolve one journey node without any title-based fallback."""
    node_id = str(node.get("id") or "")
    canonical_id = identity_map.get(node_id)
    if not canonical_id:
        raise KeyError(f"审核节点缺少 canonical 稳定身份：{node_id}")
    key = (poet, canonical_id)
    canonical = canonical_by_id.get(key)
    if canonical is None:
        raise KeyError(f"审核节点引用未知 canonical 身份：{key}")
    analysis = analysis_by_canonical_id.get(key)
    if analysis is None:
        raise KeyError(f"canonical 身份未回配 analysis_full work_id：{key}")
    linked_title = str(node.get("linked_poem", {}).get("title") or "")
    if canonical["title"] != linked_title:
        raise ValueError(
            f"审核节点 canonical 映射已过期：{node_id} "
            f"期望《{linked_title}》，实际《{canonical['title']}》"
        )
    return canonical, analysis


def imagery_counts(poems: list[dict[str, str]], limit: int = 10) -> list[dict[str, object]]:
    text = "".join(row["body"] for row in poems)
    rows = []
    for word, category, sentiment in IMAGE_DICT:
        count = text.count(word)
        if count:
            rows.append(
                {
                    "word": word,
                    "category": category,
                    "sentiment": sentiment,
                    "count": count,
                }
            )
    rows.sort(key=lambda row: (-int(row["count"]), -len(str(row["word"])), str(row["word"])))
    return rows[:limit]


def poem_imagery_matches(body: str, limit: int = 6) -> list[dict[str, object]]:
    """返回当前诗作的非重叠词典意象命中，优先保留更具体的词。"""
    occupied: set[int] = set()
    rows: list[dict[str, object]] = []
    for word, category, sentiment in sorted(IMAGE_DICT, key=lambda row: (-len(row[0]), row[0])):
        count = 0
        start = 0
        while True:
            found = body.find(word, start)
            if found < 0:
                break
            positions = range(found, found + len(word))
            if not any(position in occupied for position in positions):
                occupied.update(positions)
                count += 1
            start = found + len(word)
        if count:
            rows.append(
                {
                    "word": word,
                    "category": category,
                    "sentiment": sentiment,
                    "count": count,
                }
            )
    rows.sort(key=lambda row: (-int(row["count"]), -len(str(row["word"])), str(row["word"])))
    return rows[:limit]


def emotion_counts(poems: list[dict[str, str]], limit: int = 7) -> list[dict[str, object]]:
    counts: Counter[str] = Counter()
    evidence: dict[str, list[str]] = {}
    for poem in poems:
        matches = emotion_matches(poem["body"])
        counts.update(matches.keys())
        for label, words in matches.items():
            evidence.setdefault(label, [])
            for word in words:
                if word not in evidence[label] and len(evidence[label]) < 4:
                    evidence[label].append(word)
    return [
        {"label": label, "count": count, "evidence": evidence.get(label, [])}
        for label, count in counts.most_common(limit)
    ]


def life_summary(
    poet: str,
    nodes: list[dict[str, object]],
    imagery: list[dict[str, object]],
    poem_count: int,
) -> str:
    first = nodes[0]
    last = nodes[-1]
    pressure_peak = max(nodes, key=lambda row: float(row["life_context"]["external_pressure"]))
    low_emotion = min(nodes, key=lambda row: float(row["linked_poem"]["text_emotion"]["valence"]))
    top_words = "、".join(str(row["word"]) for row in imagery[:3]) or "暂无"
    return (
        f"审核轨迹从{first['life_context']['label']}延伸到{last['life_context']['label']}；"
        f"处境指数最高的节点位于{pressure_peak['year_label']}的{pressure_peak['place_historical']}，"
        f"关联作品中情感倾向最低的节点是《{low_emotion['linked_poem']['title']}》。"
        f"当前 {poem_count} 首全作品状态语料的高频意象为{top_words}。"
    )


def build_payload() -> dict[str, object]:
    analysis_rows, corpus_source = load_analysis_poems(fallback=False)
    if corpus_source != "analysis_full":
        raise AssertionError(f"viz19 状态层必须使用 analysis_full，实际 {corpus_source}")
    canonical_rows = load_poems()
    journey_payload = json.loads(JOURNEYS_JSON.read_text(encoding="utf-8-sig"))
    journey_groups = {
        str(group.get("poet") or ""): group
        for group in journey_payload.get("poets", [])
    }
    canonical_by_id, analysis_by_canonical_id = build_identity_indexes(
        canonical_rows, analysis_rows
    )
    contexts_by_canonical_id = bind_contexts_to_canonical_ids(
        load_contexts(), journey_groups
    )
    analysis_by_poet = {
        poet: [row for row in analysis_rows if str(row.get("poet") or "") == poet]
        for poet in TARGET_POETS
    }
    canonical_by_poet = {
        poet: [row for row in canonical_rows if row["poet"] == poet]
        for poet in TARGET_POETS
    }
    poet_payload: dict[str, object] = {}

    for poet in TARGET_POETS:
        poems = analysis_by_poet[poet]
        evidence_poems = canonical_by_poet[poet]
        if not poems or not evidence_poems:
            raise AssertionError(f"重点诗人双层语料为空：{poet}")
        group = journey_groups[poet]
        nodes = []
        for raw in sorted(group.get("nodes", []), key=lambda row: int(row["route_order"])):
            node = json.loads(json.dumps(raw, ensure_ascii=False))
            poem, analysis_match = resolve_node_poem(
                poet, node, canonical_by_id, analysis_by_canonical_id
            )
            canonical_id = poem["source_poem_id"]
            work_id = str(analysis_match["work_id"])
            node["canonical_poem_id"] = canonical_id
            node["work_id"] = work_id
            node["evidence_layer"] = "canonical"
            node["poem_page_href"] = f"44_诗页.html#poem={canonical_id}"
            node["linked_poem"]["canonical_poem_id"] = canonical_id
            node["linked_poem"]["work_id"] = work_id
            node["poem_body"] = poem["body"]
            node["poem_imagery"] = poem_imagery_matches(poem["body"])
            node["composition_context"] = contexts_by_canonical_id.get(
                (poet, canonical_id)
            )
            nodes.append(node)

        imagery = imagery_counts(poems)
        emotions = emotion_counts(poems)
        source_counts = Counter(str(node["source_level"]) for node in nodes)
        poet_payload[poet] = {
            "name": poet,
            "dynasty": str(group.get("dynasty") or evidence_poems[0]["dynasty"]),
            "school": evidence_poems[0]["school"],
            "poem_count": len(poems),
            "analysis_count": len(poems),
            "canonical_evidence_count": len(evidence_poems),
            "node_count": len(nodes),
            "reviewed_context_count": sum(
                node["composition_context"] is not None for node in nodes
            ),
            "profile_note": PROFILE_NOTES[poet],
            "profile_tag": PROFILE_TAGS[poet],
            "life_summary": life_summary(poet, nodes, imagery, len(poems)),
            "imagery": imagery,
            "emotions": emotions,
            "source_counts": dict(source_counts),
            "nodes": nodes,
        }

    dynasty_counts = Counter(
        str(row.get("person_period") or row.get("dynasty") or "")
        for row in analysis_rows
    )
    canonical_evidence_count = len(canonical_rows)
    return {
        "corpus_source": corpus_source,
        "corpus_path": CORPUS_PATH,
        "analysis_count": len(analysis_rows),
        "canonical_evidence_count": canonical_evidence_count,
        "poets": list(TARGET_POETS),
        "profiles": poet_payload,
        "corpus": {
            "corpus_source": corpus_source,
            "corpus_path": CORPUS_PATH,
            "canonical_path": CANONICAL_PATH,
            "analysis_count": len(analysis_rows),
            "canonical_evidence_count": canonical_evidence_count,
            "poems": len(analysis_rows),
            "canonical_poems": canonical_evidence_count,
            "poets": len(
                {
                    str(row.get("poet") or row.get("author") or "")
                    for row in analysis_rows
                }
            ),
            "tang": dynasty_counts.get("唐", 0),
            "song": dynasty_counts.get("宋", 0),
            "transition": len(analysis_rows)
            - dynasty_counts.get("唐", 0)
            - dynasty_counts.get("宋", 0),
            "reviewed_nodes": sum(len(group.get("nodes", [])) for group in journey_payload.get("poets", [])),
            "reviewed_contexts": len(contexts_by_canonical_id),
        },
        "methodology": journey_payload.get("methodology", {}),
        "updated_at": str(journey_payload.get("updated_at") or ""),
    }


APP_TEMPLATE = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="description" content="诗行万里：唐宋诗人的行旅、生平处境、诗作意象与文本情感联动可视化。">
  <title>诗行万里 · 诗人生命痕迹</title>
  <link rel="icon" href="data:,">
  <script src="assets/pyecharts/v6/echarts.min.js"></script>
  <script src="assets/pyecharts/v6/maps/china.js"></script>
  <style>
    :root {
      --paper:#f2f4f0; --surface:#ffffff; --surface-soft:#f7f8f5;
      --ink:#202521; --muted:#6a726c; --line:#d7dcd6; --line-strong:#b9c1ba;
      --sidebar:#252b27; --sidebar-soft:#353d37; --cinnabar:#b64b3f;
      --jade:#26786e; --gold:#a87527; --blue:#426f94; --plum:#765b79;
      --danger:#a93d35; --radius:6px; --shadow:0 10px 28px rgba(30,40,33,.07);
    }
    * { box-sizing:border-box; }
    html { min-height:100%; scroll-behavior:smooth; }
    body {
      min-height:100%; margin:0; color:var(--ink); background-color:var(--paper);
      background-image:linear-gradient(rgba(45,54,48,.025) 1px,transparent 1px),linear-gradient(90deg,rgba(45,54,48,.025) 1px,transparent 1px);
      background-size:24px 24px; font-family:"Microsoft YaHei","PingFang SC","Segoe UI",sans-serif; letter-spacing:0;
    }
    button,a { font:inherit; }
    button { cursor:pointer; }
    a { color:inherit; }
    .app-shell { min-height:100vh; }
    .sidebar {
      position:fixed; inset:0 auto 0 0; z-index:20; width:224px; display:flex; flex-direction:column;
      padding:22px 14px 16px; color:#f5f7f4; background:var(--sidebar); border-right:1px solid #39413b;
    }
    .brand { display:flex; align-items:center; gap:12px; min-height:48px; padding:0 8px; text-decoration:none; }
    .seal { width:36px; height:36px; display:grid; place-items:center; flex:0 0 auto; color:#fff; background:var(--cinnabar); border:1px solid #cf7469; border-radius:4px; font-family:"KaiTi","STKaiti",serif; font-size:22px; }
    .brand-name { font-family:"KaiTi","STKaiti",serif; font-size:20px; line-height:1.1; }
    .brand-sub { margin-top:4px; color:#acb5ae; font-size:10px; }
    .nav-label { margin:30px 10px 9px; color:#838e86; font-size:10px; font-weight:700; }
    .nav-list { display:grid; gap:5px; }
    .nav-item { min-height:44px; display:grid; grid-template-columns:28px 1fr; align-items:center; gap:8px; padding:0 12px; color:#c7cec8; text-decoration:none; border:1px solid transparent; border-radius:5px; }
    .nav-item:hover,.nav-item:focus-visible { color:#fff; background:#303732; }
    .nav-item.active { color:#fff; background:var(--sidebar-soft); border-color:#48524a; }
    .nav-index { color:#829087; font-family:Consolas,monospace; font-size:10px; }
    .nav-item.active .nav-index { color:#e2948a; }
    .side-meta { margin-top:auto; padding:14px 10px 4px; color:#b0b8b2; font-size:11px; line-height:1.7; border-top:1px solid #3d463f; }
    .side-meta strong { display:block; color:#fff; font-size:17px; }
    .side-links { display:flex; flex-wrap:wrap; gap:8px 12px; margin-top:9px; }
    .side-links a { color:#c9d1cb; font-size:10px; text-underline-offset:3px; }
    .main-shell { min-width:0; margin-left:224px; }
    .topbar { position:sticky; top:0; z-index:15; min-height:62px; display:flex; align-items:center; justify-content:space-between; gap:16px; padding:10px 24px; background:rgba(255,255,255,.96); border-bottom:1px solid var(--line); }
    .crumb { color:var(--muted); font-size:12px; white-space:nowrap; }
    .crumb strong { color:var(--ink); }
    .poet-switch { display:flex; flex-wrap:wrap; justify-content:flex-end; gap:5px; padding:3px; background:#e8ece7; border:1px solid var(--line); border-radius:5px; }
    .poet-button { min-width:52px; height:31px; padding:0 11px; color:var(--muted); background:transparent; border:0; border-radius:3px; }
    .poet-button.is-active { color:#fff; background:var(--jade); font-weight:700; }
    main { padding:22px 24px 42px; }
    .page-head { display:flex; align-items:flex-end; justify-content:space-between; gap:18px; margin-bottom:17px; }
    .eyebrow { margin-bottom:6px; color:var(--cinnabar); font-size:11px; font-weight:800; }
    h1,h2,h3,p { margin-top:0; }
    h1 { margin-bottom:7px; font-family:"KaiTi","STKaiti",serif; font-size:32px; line-height:1.2; letter-spacing:0; }
    h2 { letter-spacing:0; }
    .page-intro { max-width:800px; margin-bottom:0; color:var(--muted); font-size:12px; line-height:1.75; }
    .quality-badge { min-height:30px; display:inline-flex; align-items:center; padding:0 10px; color:#704b14; background:#f7edd9; border:1px solid #dfc38c; border-radius:4px; font-size:11px; font-weight:700; white-space:nowrap; }
    .profile-banner { display:grid; grid-template-columns:minmax(0,1fr) auto; gap:18px; align-items:center; margin-bottom:16px; padding:17px 20px; background:var(--surface); border:1px solid var(--line); border-left:4px solid var(--cinnabar); border-radius:var(--radius); box-shadow:var(--shadow); }
    .poet-line { display:flex; align-items:baseline; gap:12px; flex-wrap:wrap; }
    .poet-name { font-family:"KaiTi","STKaiti",serif; font-size:29px; font-weight:700; }
    .poet-tags { color:var(--muted); font-size:12px; }
    .poet-thesis { margin:6px 0 0; color:#3e4741; font-size:12px; line-height:1.7; }
    .profile-score { min-width:360px; display:grid; grid-template-columns:repeat(4,minmax(72px,1fr)); text-align:center; }
    .score-cell { min-width:0; padding:4px 12px; border-left:1px solid var(--line); }
    .score-value { font-size:20px; font-weight:800; }
    .score-label { margin-top:4px; color:var(--muted); font-size:9px; }
    .workspace-grid { display:grid; grid-template-columns:minmax(0,1fr) 360px; gap:16px; align-items:stretch; }
    .panel { min-width:0; background:var(--surface); border:1px solid var(--line); border-radius:var(--radius); box-shadow:var(--shadow); overflow:hidden; }
    .panel-head { min-height:54px; display:flex; align-items:center; justify-content:space-between; gap:12px; padding:11px 15px; border-bottom:1px solid var(--line); }
    .panel-title { font-size:13px; font-weight:800; }
    .panel-meta { margin-top:3px; color:var(--muted); font-size:10px; }
    .legend { display:flex; flex-wrap:wrap; justify-content:flex-end; gap:11px; color:var(--muted); font-size:10px; }
    .legend span::before { content:""; width:8px; height:8px; display:inline-block; margin-right:5px; border-radius:50%; background:var(--jade); }
    .legend span:nth-child(2)::before { background:var(--cinnabar); }
    .chart { width:100%; height:500px; }
    .node-detail { min-height:554px; display:flex; flex-direction:column; }
    .detail-body { padding:16px; }
    .detail-kicker { color:var(--cinnabar); font-size:10px; font-weight:800; }
    .detail-title { margin:5px 0 4px; font-size:18px; line-height:1.45; }
    .detail-place { color:var(--muted); font-size:11px; }
    .event-copy { margin:14px 0 0; color:#3f4741; font-size:12px; line-height:1.75; }
    .detail-metrics { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); margin:15px 0; border:1px solid var(--line); }
    .detail-metric { min-width:0; padding:10px 7px; text-align:center; border-right:1px solid var(--line); }
    .detail-metric:last-child { border-right:0; }
    .detail-metric strong { display:block; font-size:17px; }
    .detail-metric span { display:block; margin-top:3px; color:var(--muted); font-size:9px; }
    .poem-evidence { margin:0; padding:12px 0 12px 13px; color:#303732; border-left:3px solid var(--cinnabar); font-family:"KaiTi","STKaiti",serif; font-size:18px; line-height:1.65; }
    .poem-title { margin-top:11px; font-size:12px; font-weight:800; }
    .background-note { margin:12px 0 0; padding:11px; color:#59635c; background:var(--surface-soft); border:1px solid var(--line); border-radius:4px; font-size:10px; line-height:1.7; }
    .source-row { display:flex; align-items:center; gap:8px; flex-wrap:wrap; margin-top:13px; color:var(--muted); font-size:10px; }
    .grade { width:24px; height:22px; display:inline-grid; place-items:center; color:#fff; background:var(--jade); border-radius:3px; font-weight:800; }
    .grade-C { background:var(--gold); }
    .source-row a { color:var(--jade); text-underline-offset:3px; }
    details.poem-full { margin-top:11px; border-top:1px solid var(--line); }
    details.poem-full summary { padding:10px 0; color:var(--jade); cursor:pointer; font-size:10px; font-weight:700; }
    .poem-body { margin:0; color:#4a534d; white-space:pre-wrap; font-family:"KaiTi","STKaiti",serif; font-size:15px; line-height:1.8; }
    .timeline-section { margin:16px 0; padding:15px 18px 12px; background:var(--surface); border:1px solid var(--line); border-radius:var(--radius); box-shadow:var(--shadow); }
    .timeline-head { display:flex; align-items:flex-start; justify-content:space-between; gap:16px; padding-bottom:11px; border-bottom:1px solid var(--line); }
    .section-title { margin:0; font-size:14px; line-height:1.4; }
    .section-meta { margin:4px 0 0; color:var(--muted); font-size:10px; line-height:1.55; }
    .timeline { --timeline-count:6; --timeline-line-inset:8.333%; position:relative; display:grid; grid-template-columns:repeat(var(--timeline-count),minmax(0,1fr)); margin-top:15px; padding:0 0 3px; }
    .timeline::before { content:""; position:absolute; z-index:0; top:40px; left:var(--timeline-line-inset); right:var(--timeline-line-inset); height:2px; background:var(--line-strong); }
    .timeline-button { position:relative; z-index:1; min-width:0; min-height:150px; display:grid; grid-template-rows:minmax(30px,auto) 22px auto auto auto; align-items:start; padding:0 5px 9px; color:var(--ink); text-align:center; background:transparent; border:0; border-radius:4px; }
    .timeline-button:hover { background:var(--surface-soft); }
    .timeline-button:focus-visible { outline:2px solid var(--jade); outline-offset:-2px; }
    .timeline-year { display:block; min-height:30px; color:var(--muted); font-size:10px; font-weight:800; line-height:1.45; }
    .timeline-marker { position:relative; z-index:2; width:15px; height:15px; display:block; justify-self:center; margin-top:2px; background:var(--surface); border:2px solid var(--jade); border-radius:50%; }
    .timeline-button.is-active .timeline-marker { background:var(--cinnabar); border-color:var(--cinnabar); box-shadow:0 0 0 4px #f3d9d4; }
    .timeline-place { display:block; min-width:0; margin-top:8px; color:#313933; font-size:12px; font-weight:800; line-height:1.45; }
    .timeline-label { display:block; min-width:0; margin-top:4px; color:var(--muted); font-size:10px; line-height:1.45; }
    .timeline-poem { display:block; min-width:0; margin-top:3px; color:var(--jade); font-family:"KaiTi","STKaiti",serif; font-size:11px; font-weight:700; line-height:1.45; }
    .timeline-button.is-active .timeline-year,.timeline-button.is-active .timeline-label { color:var(--cinnabar); }
    .timeline-button.is-active .timeline-place,.timeline-button.is-active .timeline-poem { color:#8f342c; }
    .period-analysis { margin-bottom:16px; }
    .period-analysis-body { padding:16px 18px 18px; }
    .period-overview { display:grid; grid-template-columns:minmax(0,1fr) minmax(190px,.38fr); gap:18px; align-items:start; padding-bottom:15px; border-bottom:1px solid var(--line); }
    .period-kicker { color:var(--cinnabar); font-size:10px; font-weight:800; }
    .period-heading { margin:4px 0 5px; font-family:"KaiTi","STKaiti",serif; font-size:21px; line-height:1.35; }
    .period-location { color:var(--muted); font-size:11px; line-height:1.6; }
    .period-status { padding:10px 12px; background:var(--surface-soft); border-left:3px solid var(--jade); }
    .period-status strong { display:block; color:#344038; font-size:12px; line-height:1.55; }
    .period-status span { display:block; margin-top:4px; color:var(--muted); font-size:10px; line-height:1.55; }
    .period-analysis-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); margin-top:2px; }
    .period-cell { min-width:0; padding:15px 16px 4px; border-right:1px solid var(--line); }
    .period-cell:first-child { padding-left:0; }
    .period-cell:last-child { padding-right:0; border-right:0; }
    .period-cell-title { margin:0 0 7px; color:var(--muted); font-size:10px; font-weight:800; }
    .period-cell-copy { margin:0; color:#3d4740; font-size:11px; line-height:1.75; }
    .period-text-evidence { display:block; margin-top:9px; padding-left:10px; color:#3a433d; border-left:2px solid var(--cinnabar); font-family:"KaiTi","STKaiti",serif; font-size:15px; line-height:1.65; }
    .period-imagery { display:flex; flex-wrap:wrap; gap:6px; }
    .period-imagery-token { display:inline-flex; align-items:baseline; gap:4px; min-height:25px; padding:3px 7px; color:#465048; background:var(--surface-soft); border:1px solid var(--line); border-radius:3px; font-size:10px; }
    .period-imagery-token b { color:var(--jade); font-family:"KaiTi","STKaiti",serif; font-size:13px; }
    .period-imagery-token em { color:var(--muted); font-style:normal; }
    .period-empty { color:var(--muted); font-size:11px; line-height:1.7; }
    .stage-comparison { display:grid; grid-template-columns:140px minmax(0,1fr); gap:16px; align-items:start; margin-top:15px; padding-top:15px; border-top:1px solid var(--line); }
    .stage-comparison-title { color:var(--muted); font-size:10px; font-weight:800; line-height:1.6; }
    .stage-comparison-copy { margin:0; color:#3d4740; font-size:11px; line-height:1.8; }
    .stage-comparison-copy strong { color:#8f342c; }
    .analysis-grid { display:grid; grid-template-columns:minmax(0,1.35fr) minmax(320px,.65fr); gap:16px; margin-top:16px; }
    .chart.medium { height:360px; }
    .insight-body { padding:15px; }
    .life-summary { margin:0 0 14px; color:#3f4841; font-size:12px; line-height:1.8; }
    .subhead { margin:15px 0 8px; color:var(--muted); font-size:10px; font-weight:800; }
    .token-band { display:flex; flex-wrap:wrap; gap:6px; }
    .token { min-height:28px; display:inline-flex; align-items:center; gap:6px; padding:0 8px; color:#465048; background:var(--surface-soft); border:1px solid var(--line); border-radius:3px; font-size:10px; }
    .token b { color:var(--jade); }
    .emotion-list { display:grid; gap:8px; }
    .emotion-row { display:grid; grid-template-columns:82px 1fr 24px; align-items:center; gap:8px; color:#4a534d; font-size:10px; }
    .emotion-track { height:7px; background:#e6eae5; overflow:hidden; }
    .emotion-fill { height:100%; background:var(--blue); }
    .method-note { margin-top:16px; padding:14px 16px; color:#5b5b4d; background:#f6f0df; border:1px solid #ddd0a9; border-left:4px solid var(--gold); font-size:11px; line-height:1.75; }
    .support-band { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:12px; margin-top:16px; }
    .support-link { min-height:96px; display:block; padding:14px 15px; text-decoration:none; background:var(--surface); border:1px solid var(--line); border-top:3px solid var(--jade); border-radius:var(--radius); box-shadow:var(--shadow); }
    .support-link:nth-child(2) { border-top-color:var(--cinnabar); }
    .support-link:nth-child(3) { border-top-color:var(--gold); }
    .support-link strong { display:block; font-size:13px; }
    .support-link span { display:block; margin-top:6px; color:var(--muted); font-size:10px; line-height:1.6; }
    footer { padding:22px 0 4px; color:var(--muted); font-size:10px; }
    @media (max-width:1180px) {
      .workspace-grid,.analysis-grid { grid-template-columns:1fr; }
      .node-detail { min-height:0; }
      .profile-score { min-width:320px; }
      .period-analysis-grid { grid-template-columns:repeat(2,minmax(0,1fr)); }
      .period-cell:nth-child(2) { padding-right:0; border-right:0; }
      .period-cell:nth-child(3) { padding-left:0; padding-right:0; border-top:1px solid var(--line); grid-column:1 / -1; }
    }
    @media (max-width:980px) {
      .sidebar { position:static; width:100%; padding:12px 14px; }
      .brand { min-height:42px; }
      .nav-label,.side-meta { display:none; }
      .nav-list { grid-template-columns:repeat(5,minmax(0,1fr)); margin-top:10px; }
      .nav-item { min-height:38px; grid-template-columns:1fr; text-align:center; padding:0 7px; font-size:11px; }
      .nav-index { display:none; }
      .main-shell { margin-left:0; }
      .topbar { position:static; }
      .profile-banner { grid-template-columns:1fr; }
      .profile-score { min-width:0; max-width:520px; }
      .score-cell:first-child { border-left:0; }
    }
    @media (max-width:700px) {
      .nav-list { grid-template-columns:repeat(2,minmax(0,1fr)); }
      .topbar { align-items:flex-start; flex-direction:column; padding:11px 12px; }
      .poet-switch { width:100%; justify-content:flex-start; }
      .poet-button { flex:1 1 52px; }
      main { padding:16px 11px 30px; }
      .page-head { align-items:flex-start; flex-direction:column; }
      h1 { font-size:27px; }
      .profile-banner { padding:15px; }
      .profile-score { grid-template-columns:repeat(2,minmax(0,1fr)); }
      .score-cell { border-left:0; border-top:1px solid var(--line); padding:10px 5px; }
      .chart { height:390px; }
      .chart.medium { height:340px; }
      .timeline-section { padding:14px 14px 12px; }
      .timeline-head { align-items:flex-start; flex-direction:column; gap:9px; }
      .timeline { display:block; margin-top:13px; padding:0; }
      .timeline::before { display:none; }
      .timeline-button { min-height:0; display:grid; grid-template-columns:36px minmax(0,1fr); grid-template-rows:auto auto auto auto; align-items:start; padding:0 0 16px; text-align:left; border-radius:3px; }
      .timeline-button:not(:last-child)::after { content:""; position:absolute; z-index:0; top:19px; bottom:-1px; left:17px; width:2px; background:var(--line-strong); }
      .timeline-button:last-child { padding-bottom:0; }
      .timeline-year { grid-column:2; grid-row:1; min-height:0; text-align:left; }
      .timeline-marker { grid-column:1; grid-row:1 / span 4; align-self:start; justify-self:center; margin-top:4px; }
      .timeline-place { grid-column:2; grid-row:2; margin-top:3px; }
      .timeline-label { grid-column:2; grid-row:3; margin-top:3px; }
      .timeline-poem { grid-column:2; grid-row:4; margin-top:3px; }
      .period-overview { grid-template-columns:1fr; gap:12px; }
      .period-analysis-grid { grid-template-columns:1fr; }
      .period-cell,.period-cell:first-child,.period-cell:nth-child(2),.period-cell:nth-child(3) { padding:14px 0; border-right:0; border-top:1px solid var(--line); grid-column:auto; }
      .period-cell:first-child { border-top:0; }
      .stage-comparison { grid-template-columns:1fr; gap:6px; }
      .support-band { grid-template-columns:1fr; }
    }
    @media (max-width:420px) {
      .detail-metrics { grid-template-columns:1fr; }
      .detail-metric { border-right:0; border-bottom:1px solid var(--line); }
      .detail-metric:last-child { border-bottom:0; }
      .emotion-row { grid-template-columns:74px 1fr 22px; }
    }
  </style>
</head>
<body>
  <div class="app-shell">
    <aside class="sidebar" aria-label="研究导航">
      <a class="brand" href="index.html">
        <span class="seal" aria-hidden="true">诗</span>
        <span><span class="brand-name">诗行万里</span><span class="brand-sub">唐宋诗人生命痕迹</span></span>
      </a>
      <div class="nav-label">研究视图</div>
      <nav class="nav-list">
        <a class="nav-item active" href="index.html"><span class="nav-index">01</span><span>生命痕迹</span></a>
        <a class="nav-item" href="17_同一意象的诗人情感差异.html"><span class="nav-index">02</span><span>意象比较</span></a>
        <a class="nav-item" href="16_唐宋诗歌创作活动中心迁移.html"><span class="nav-index">03</span><span>文化中心</span></a>
        <a class="nav-item" href="08_诗作检索.html"><span class="nav-index">04</span><span>诗作检索</span></a>
        <a class="nav-item" href="18_数据质量与来源覆盖.html"><span class="nav-index">05</span><span>数据质量</span></a>
        <a class="nav-item" href="20_诗人精神地形图.html"><span class="nav-index">06</span><span>精神地形</span></a>
        <a class="nav-item" href="44_诗页.html"><span class="nav-index">07</span><span>赏析诗页</span></a>
      </nav>
      <div class="side-meta">
        当前语料
        <strong><span id="sidePoets">--</span> 位诗人 · <span id="sidePoems">--</span> 首作品</strong>
        全作品状态 · 精选证据分层
        <div class="side-links">
          <a href="15_诗人行旅与生命情感.html">审核明细</a>
          <a href="29_参赛导航.html">参赛版作品集</a>
          <a href="20_诗人精神地形图.html">精神地形图（论证篇）</a>
          <a href="09_词典浏览.html">意象词典</a>
          <a href="00_主题数据库ER图.png">数据库 ER 图</a>
          <a href="manifest.json">交付清单</a>
        </div>
      </div>
    </aside>

    <div class="main-shell">
      <header class="topbar">
        <div class="crumb">诗行万里 / <strong>诗人生命痕迹</strong></div>
        <div id="poetSwitch" class="poet-switch" role="group" aria-label="选择诗人"></div>
      </header>

      <main>
        <section class="page-head">
          <div>
            <div class="eyebrow">LIFE TRACE · REVIEWED EVIDENCE</div>
            <h1>从行旅、诗作与意象读一位诗人的一生</h1>
            <p class="page-intro">文本画像聚合精选名家的全部作品；地图、编年、创作背景与原诗引句只使用可追溯的 canonical 精选证据，并随节点联动。</p>
          </div>
          <span class="quality-badge">全作品状态 · 精选证据</span>
        </section>

        <section class="profile-banner" aria-label="当前诗人画像">
          <div>
            <div class="poet-line"><span id="profileName" class="poet-name">--</span><span id="profileTags" class="poet-tags">--</span></div>
            <p id="profileNote" class="poet-thesis">--</p>
          </div>
          <div class="profile-score">
            <div class="score-cell"><div id="metricPoems" class="score-value">--</div><div class="score-label">全作品状态</div></div>
            <div class="score-cell"><div id="metricNodes" class="score-value">--</div><div class="score-label">审核节点</div></div>
            <div class="score-cell"><div id="metricContexts" class="score-value">--</div><div class="score-label">创作背景</div></div>
            <div class="score-cell"><div id="metricGrades" class="score-value">--</div><div class="score-label">A/B 级节点</div></div>
          </div>
        </section>

        <section class="workspace-grid">
          <article class="panel">
            <div class="panel-head">
              <div><div class="panel-title">行旅与创作坐标</div><div class="panel-meta">经纬度对应现代城市近似中心；连线只表示节点先后</div></div>
              <div class="legend"><span>审核节点</span><span>当前节点</span></div>
            </div>
            <div id="journeyMap" class="chart" role="img" aria-label="诗人行旅节点地图"></div>
          </article>

          <aside class="panel node-detail" aria-live="polite">
            <div class="panel-head"><div><div class="panel-title">节点证据</div><div id="detailSequence" class="panel-meta">--</div></div><span id="detailConfidence" class="quality-badge">--</span></div>
            <div id="detailBody" class="detail-body"></div>
          </aside>
        </section>

        <section class="timeline-section" aria-labelledby="timelineHeading">
          <div class="timeline-head">
            <div>
              <h2 id="timelineHeading" class="section-title">作诗时期轴</h2>
              <p class="section-meta">按审核节点的时间先后排列：阶段、生平事件与关联作品。</p>
            </div>
            <span id="timelineStatus" class="quality-badge">--</span>
          </div>
          <div id="timeline" class="timeline" aria-label="生平节点时间轴"></div>
        </section>

        <article class="panel period-analysis" aria-live="polite" aria-labelledby="periodAnalysisHeading">
          <div class="panel-head"><div><div id="periodAnalysisHeading" class="panel-title">当前作诗时期分析</div><div id="periodAnalysisMeta" class="panel-meta">--</div></div><span id="periodAnalysisGrade" class="quality-badge">--</span></div>
          <div id="periodAnalysisBody" class="period-analysis-body"></div>
        </article>

        <section class="analysis-grid">
          <article class="panel">
            <div class="panel-head"><div><div class="panel-title">生平处境与文本情感变化</div><div class="panel-meta">处境指数为项目人工编码，仅比较同一诗人的阶段变化</div></div><div class="legend"><span>处境指数</span><span>文本情感</span></div></div>
            <div id="emotionTrend" class="chart medium" role="img" aria-label="生平处境与文本情感变化曲线"></div>
          </article>
          <aside class="panel">
            <div class="panel-head"><div><div class="panel-title">全作品文本表现概括</div><div id="textProfileMeta" class="panel-meta">全作品状态的词典与规则命中</div></div></div>
            <div class="insight-body">
              <p id="lifeSummary" class="life-summary">--</p>
              <div class="subhead">高频意象</div>
              <div id="imageryTokens" class="token-band"></div>
              <div class="subhead">情感语境标签</div>
              <div id="emotionList" class="emotion-list"></div>
            </div>
          </aside>
        </section>

        <div class="method-note"><strong>双层口径：</strong>每位诗人的篇数、意象与情感规则统计来自全作品状态语料；审核行旅、编年、创作背景和原句来自 canonical 精选证据，并按稳定诗作 ID 精确链接。<br><strong>处境指数：</strong>项目根据战乱、贬谪、囚禁、贫病、丧亲和仕途受挫等已审核事件人工编码为 0–100；数值越高，只表示该诗人在所选节点中的处境越艰难。它不是心理测量，也不能用于诗人之间排名。</div>

        <section class="support-band" aria-label="辅助研究">
          <a class="support-link" href="17_同一意象的诗人情感差异.html"><strong>同一意象，跨诗人比较</strong><span>比较月、酒、舟、雁、雨在六位诗人作品中的局部语境差异。</span></a>
          <a class="support-link" href="16_唐宋诗歌创作活动中心迁移.html"><strong>唐宋创作活动中心迁移</strong><span>从审核创作地点观察精细样本中的活动重心变化。</span></a>
          <a class="support-link" href="08_诗作检索.html"><strong>回到原诗证据</strong><span>按诗人、朝代和关键词检索当前全部基础语料。</span></a>
        </section>
        <footer>生成时间：__GENERATED_AT__ · 数据版本：__DATA_UPDATED__ · 详细文件哈希见 manifest.json</footer>
      </main>
    </div>
  </div>

  <script id="appData" type="application/json">__APP_DATA__</script>
  <script>
    (function () {
      "use strict";
      const data = JSON.parse(document.getElementById("appData").textContent);
      const state = { poet: data.poets[0], nodeIndex: 0 };
      const charts = {
        map: echarts.init(document.getElementById("journeyMap"), null, { renderer: "canvas" }),
        trend: echarts.init(document.getElementById("emotionTrend"), null, { renderer: "canvas" })
      };
      const colors = { jade: "#26786e", red: "#b64b3f", gold: "#a87527", blue: "#426f94", grid: "#d7dcd6", ink: "#303732", muted: "#6a726c", area: "#eef1ed" };

      function esc(value) {
        const map = { "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;" };
        return String(value == null ? "" : value).replace(/[&<>\"']/g, function (ch) { return map[ch]; });
      }

      function profile() { return data.profiles[state.poet]; }
      function selectedNode() { return profile().nodes[state.nodeIndex]; }
      function pct(value) { return Math.round(Number(value || 0) * 100); }
      function signed(value) { const number = Number(value || 0); return (number > 0 ? "+" : "") + number.toFixed(2); }
      function contextBand(value) {
        const score = pct(value);
        if (score < 40) return "相对平稳";
        if (score < 60) return "处境承压";
        if (score < 80) return "明显困顿";
        return "高压处境";
      }

      function signedWhole(value) {
        const number = Math.round(Number(value || 0));
        return (number > 0 ? "+" : "") + number;
      }

      function direction(value) {
        const number = Number(value || 0);
        if (number > 0) return "up";
        if (number < 0) return "down";
        return "flat";
      }

      function backgroundText(node) {
        const context = node.composition_context;
        return context && context.source_note ? context.source_note : node.linked_poem.relation;
      }

      function compareAdjacentNodes(previous, current) {
        if (!previous) {
          return {
            title: "起始样本",
            detail: "这是该诗人所选审核轨迹的起始节点，尚无上一节点可作阶段比较。",
            conclusion: "当前解读以本节点的生平事件、作品关联与文本证据为限。"
          };
        }
        const pressureDelta = pct(current.life_context.external_pressure) - pct(previous.life_context.external_pressure);
        const valenceDelta = Number(current.linked_poem.text_emotion.valence) - Number(previous.linked_poem.text_emotion.valence);
        const intensityDelta = pct(current.linked_poem.text_emotion.intensity) - pct(previous.linked_poem.text_emotion.intensity);
        const pressureDirection = direction(pressureDelta);
        const valenceDirection = direction(valenceDelta);
        let conclusion = "处境与关联作品的文本倾向变化有限，需结合两处节点的具体事件和诗句阅读。";
        if (pressureDirection === "up" && valenceDirection === "down") {
          conclusion = "处境趋难，关联作品的文本倾向同步转向低沉。";
        } else if (pressureDirection === "up" && valenceDirection === "up") {
          conclusion = "处境趋难，但关联作品的文本倾向上扬，呈现反弹或调适性表达。";
        } else if (pressureDirection === "down" && valenceDirection === "up") {
          conclusion = "处境缓和与关联作品的文本转明同步。";
        } else if (pressureDirection === "down" && valenceDirection === "down") {
          conclusion = "处境有所缓和，但关联作品仍转向低沉，呈现不同步变化。";
        } else if (pressureDirection === "up") {
          conclusion = "处境趋难，关联作品的文本倾向基本持平。";
        } else if (pressureDirection === "down") {
          conclusion = "处境缓和，关联作品的文本倾向基本持平。";
        } else if (valenceDirection === "up") {
          conclusion = "处境指数基本持平，关联作品的文本倾向转明。";
        } else if (valenceDirection === "down") {
          conclusion = "处境指数基本持平，关联作品的文本倾向转低。";
        }
        return {
          title: "相邻审核节点比较",
          detail: "相较于上一节点“" + previous.life_context.label + "”（" + previous.year_label + "，《" + previous.linked_poem.title + "》），处境指数 " + pct(previous.life_context.external_pressure) + " 至 " + pct(current.life_context.external_pressure) + "（" + signedWhole(pressureDelta) + "）；文本倾向 " + signed(previous.linked_poem.text_emotion.valence) + " 至 " + signed(current.linked_poem.text_emotion.valence) + "（" + signed(valenceDelta) + "）；情感强度 " + pct(previous.linked_poem.text_emotion.intensity) + "% 至 " + pct(current.linked_poem.text_emotion.intensity) + "%（" + signedWhole(intensityDelta) + "%）。",
          conclusion: conclusion
        };
      }

      function renderPoetSwitch() {
        const root = document.getElementById("poetSwitch");
        root.innerHTML = data.poets.map(function (poet) {
          const active = poet === state.poet;
          return '<button type="button" class="poet-button' + (active ? ' is-active' : '') + '" data-poet="' + esc(poet) + '" aria-pressed="' + active + '">' + esc(poet) + '</button>';
        }).join("");
        Array.from(root.querySelectorAll("[data-poet]")).forEach(function (button) {
          button.addEventListener("click", function () {
            state.poet = button.getAttribute("data-poet");
            state.nodeIndex = 0;
            renderAll();
          });
        });
      }

      function renderProfile() {
        const row = profile();
        const ab = Number(row.source_counts.A || 0) + Number(row.source_counts.B || 0);
        document.getElementById("profileName").textContent = row.name;
        document.getElementById("profileTags").textContent = row.dynasty + " · " + row.school + " · " + row.profile_tag;
        document.getElementById("profileNote").textContent = row.profile_note;
        document.getElementById("metricPoems").textContent = Number(row.poem_count).toLocaleString("zh-CN");
        document.getElementById("metricNodes").textContent = row.node_count;
        document.getElementById("metricContexts").textContent = row.reviewed_context_count;
        document.getElementById("metricGrades").textContent = ab;
      }

      function renderMap() {
        const row = profile();
        const nodes = row.nodes;
        const route = nodes.map(function (node) { return [Number(node.longitude), Number(node.latitude)]; });
        const points = nodes.map(function (node, index) {
          return {
            name: node.id,
            value: [Number(node.longitude), Number(node.latitude), Math.round(Number(node.confidence) * 100)],
            nodeIndex: index,
            symbolSize: index === state.nodeIndex ? 18 : 11,
            symbolOffset: [((index % 3) - 1) * 4, (index % 2) * 4],
            itemStyle: { color: index === state.nodeIndex ? colors.red : colors.jade, borderColor: "#ffffff", borderWidth: 1.5 }
          };
        });
        charts.map.setOption({
          animationDurationUpdate: 360,
          tooltip: {
            trigger: "item", confine: true,
            formatter: function (params) {
              if (!params.data || params.data.nodeIndex == null) return row.name + " · 时间顺序连线";
              const node = nodes[params.data.nodeIndex];
              return '<strong>' + esc(node.year_label) + ' · ' + esc(node.place_historical) + '</strong><br>' + esc(node.event) + '<br>《' + esc(node.linked_poem.title) + '》';
            }
          },
          geo: {
            map: "china", roam: true, zoom: 1.08, center: [106, 33],
            label: { show: false },
            itemStyle: { areaColor: colors.area, borderColor: "#aeb8b0", borderWidth: .8 },
            emphasis: { itemStyle: { areaColor: "#e0e7e1" }, label: { show: false } }
          },
          series: [
            { name: "节点顺序", type: "lines", coordinateSystem: "geo", polyline: true, silent: true, data: [{ coords: route }], lineStyle: { color: colors.gold, width: 1.6, opacity: .72, type: "dashed" }, effect: { show: false } },
            { name: "审核节点", type: "scatter", coordinateSystem: "geo", data: points, zlevel: 2, label: { show: true, position: "right", color: colors.ink, fontSize: 10, formatter: function (params) { return params.data.nodeIndex === state.nodeIndex ? nodes[params.data.nodeIndex].place_historical : ""; } } }
          ]
        }, true);
        charts.map.off("click");
        charts.map.on("click", function (params) {
          if (params.data && params.data.nodeIndex != null) selectNode(params.data.nodeIndex);
        });
      }

      function renderTimeline() {
        const nodes = profile().nodes;
        const root = document.getElementById("timeline");
        root.style.setProperty("--timeline-count", String(nodes.length));
        root.style.setProperty("--timeline-line-inset", (50 / nodes.length).toFixed(3) + "%");
        document.getElementById("timelineStatus").textContent = "当前：第 " + (state.nodeIndex + 1) + " / " + nodes.length + " 节";
        root.innerHTML = nodes.map(function (node, index) {
          const active = index === state.nodeIndex;
          return '<button type="button" class="timeline-button' + (active ? ' is-active' : '') + '" data-node="' + index + '" aria-pressed="' + active + '" aria-label="第 ' + (index + 1) + ' 节，' + esc(node.year_label) + '，' + esc(node.life_context.label) + '，' + esc(node.place_historical) + '，《' + esc(node.linked_poem.title) + '》">' +
            '<span class="timeline-year">' + esc(node.year_label) + '</span>' +
            '<span class="timeline-marker" aria-hidden="true"></span>' +
            '<span class="timeline-place">' + esc(node.place_historical) + '</span>' +
            '<span class="timeline-label">' + esc(node.life_context.label) + '</span>' +
            '<span class="timeline-poem">《' + esc(node.linked_poem.title) + '》</span></button>';
        }).join("");
        Array.from(root.querySelectorAll("[data-node]")).forEach(function (button) {
          button.addEventListener("click", function () { selectNode(Number(button.getAttribute("data-node"))); });
        });
      }

      function renderPeriodAnalysis() {
        const node = selectedNode();
        const linked = node.linked_poem;
        const emotion = linked.text_emotion;
        const index = state.nodeIndex;
        const comparison = compareAdjacentNodes(profile().nodes[index - 1], node);
        const context = node.composition_context;
        const backgroundSource = context && context.source_name ? context.source_name : "节点作品关联说明";
        const imagery = Array.isArray(node.poem_imagery) ? node.poem_imagery : [];
        const imageryHtml = imagery.length
          ? imagery.map(function (item) {
              return '<span class="period-imagery-token"><b>' + esc(item.word) + '</b><em>' + esc(item.category) + ' · ' + item.count + ' 次</em></span>';
            }).join("")
          : '<span class="period-empty">该诗作未命中本项目意象词典。</span>';
        document.getElementById("periodAnalysisMeta").textContent = comparison.title + " · 仅比较相邻审核节点";
        document.getElementById("periodAnalysisGrade").textContent = node.source_level + " 级节点 · " + linked.relation_level + " 级关联";
        document.getElementById("periodAnalysisBody").innerHTML =
          '<div class="period-overview">' +
            '<div><div class="period-kicker">阶段定位</div><h2 class="period-heading">' + esc(node.life_context.label) + ' · 《' + esc(linked.title) + '》</h2><div class="period-location">' + esc(node.year_label) + ' · ' + esc(node.place_historical) + ' / ' + esc(node.place_modern) + '</div></div>' +
            '<div class="period-status"><strong>生平处境 ' + pct(node.life_context.external_pressure) + ' · ' + esc(contextBand(node.life_context.external_pressure)) + '</strong><span>文本倾向 ' + signed(emotion.valence) + ' · 情感强度 ' + pct(emotion.intensity) + '%</span></div>' +
          '</div>' +
          '<div class="period-analysis-grid">' +
            '<section class="period-cell"><h3 class="period-cell-title">生平处境</h3><p class="period-cell-copy">' + esc(node.event) + '</p><p class="period-cell-copy"><strong>处境依据：</strong>' + esc(node.life_context.reason) + '</p></section>' +
            '<section class="period-cell"><h3 class="period-cell-title">创作背景</h3><p class="period-cell-copy">' + esc(backgroundText(node)) + '</p><p class="period-cell-copy"><strong>依据来源：</strong>' + esc(backgroundSource) + '</p></section>' +
            '<section class="period-cell"><h3 class="period-cell-title">文本表现</h3><p class="period-cell-copy">关联作品标注为“' + esc(emotion.label) + '”，文本倾向 ' + signed(emotion.valence) + '，情感强度 ' + pct(emotion.intensity) + '%。</p><span class="period-text-evidence">' + esc(emotion.evidence) + '</span></section>' +
          '</div>' +
          '<div class="subhead">当前诗作意象</div><div class="period-imagery">' + imageryHtml + '</div>' +
          '<div class="stage-comparison"><div class="stage-comparison-title">' + esc(comparison.title) + '</div><p class="stage-comparison-copy">' + esc(comparison.detail) + '<br><strong>' + esc(comparison.conclusion) + '</strong></p></div>';
      }

      function renderDetail() {
        const node = selectedNode();
        const linked = node.linked_poem;
        const emotion = linked.text_emotion;
        const context = node.composition_context;
        const index = state.nodeIndex + 1;
        document.getElementById("detailSequence").textContent = profile().name + " · 第 " + index + " / " + profile().nodes.length + " 节";
        document.getElementById("detailConfidence").textContent = node.source_level + " 级 · " + pct(node.confidence) + "%";
        const background = context && context.source_note
          ? '<div class="background-note"><strong>创作背景：</strong>' + esc(context.source_note) + '</div>'
          : '<div class="background-note"><strong>作品关联：</strong>' + esc(linked.relation) + '</div>';
        const contextSource = context && context.source_url
          ? '<a href="' + esc(context.source_url) + '" target="_blank" rel="noopener noreferrer">创作背景来源</a>'
          : '';
        document.getElementById("detailBody").innerHTML =
          '<div class="detail-kicker">' + esc(node.year_label) + '</div>' +
          '<h2 class="detail-title">' + esc(node.life_context.label) + '</h2>' +
          '<div class="detail-place">' + esc(node.place_historical) + ' / ' + esc(node.place_modern) + '</div>' +
          '<p class="event-copy">' + esc(node.event) + '</p>' +
          '<div class="detail-metrics">' +
            '<div class="detail-metric"><strong>' + pct(node.life_context.external_pressure) + '</strong><span>处境指数 · ' + esc(contextBand(node.life_context.external_pressure)) + '</span></div>' +
            '<div class="detail-metric"><strong>' + signed(emotion.valence) + '</strong><span>文本倾向</span></div>' +
            '<div class="detail-metric"><strong>' + pct(emotion.intensity) + '</strong><span>情感强度</span></div>' +
          '</div>' +
          '<div class="poem-title">《' + esc(linked.title) + '》 · ' + esc(emotion.label) + '</div>' +
          '<blockquote class="poem-evidence">' + esc(emotion.evidence) + '</blockquote>' +
          '<div class="background-note"><strong>指数依据：</strong>' + esc(node.life_context.reason) + '</div>' +
          background +
          '<div class="source-row"><span class="grade grade-' + esc(node.source_level) + '">' + esc(node.source_level) + '</span><span>' + esc(node.source_name) + '</span><a href="' + esc(node.source_url) + '" target="_blank" rel="noopener noreferrer">节点来源</a>' + contextSource + '<a href="' + esc(node.poem_page_href) + '">译注赏析</a></div>' +
          '<details class="poem-full"><summary>查看收录原诗</summary><p class="poem-body">' + esc(node.poem_body) + '</p></details>';
      }

      function renderTrend() {
        const nodes = profile().nodes;
        charts.trend.setOption({
          animationDurationUpdate: 360,
          color: [colors.gold, colors.red, colors.blue],
          tooltip: {
            trigger: "axis", confine: true,
            formatter: function (items) {
              const index = items[0].dataIndex;
              const node = nodes[index];
              return '<strong>' + esc(node.year_label) + ' · ' + esc(node.life_context.label) + '</strong><br>' +
                '处境指数 ' + pct(node.life_context.external_pressure) + '（' + esc(contextBand(node.life_context.external_pressure)) + '）<br>' +
                '文本倾向 ' + signed(node.linked_poem.text_emotion.valence) + '<br>' +
                '情感强度 ' + pct(node.linked_poem.text_emotion.intensity) + '<br>《' + esc(node.linked_poem.title) + '》';
            }
          },
          legend: { top: 10, textStyle: { color: colors.muted, fontSize: 10 } },
          grid: { left: 48, right: 50, top: 54, bottom: 70 },
          xAxis: { type: "category", data: nodes.map(function (node) { return String(node.year); }), axisLine: { lineStyle: { color: "#aeb8b0" } }, axisLabel: { color: colors.muted, rotate: nodes.length > 6 ? 24 : 0, fontSize: 10 } },
          yAxis: [
            { type: "value", min: 0, max: 100, name: "指数", nameTextStyle: { color: colors.muted }, splitLine: { lineStyle: { color: colors.grid, type: "dashed" } }, axisLabel: { color: colors.muted, fontSize: 9 } },
            { type: "value", min: -1, max: 1, name: "倾向", nameTextStyle: { color: colors.muted }, splitLine: { show: false }, axisLabel: { color: colors.muted, fontSize: 9 } }
          ],
          series: [
            { name: "处境指数", type: "line", smooth: .24, data: nodes.map(function (node) { return pct(node.life_context.external_pressure); }), symbol: "circle", symbolSize: function (_v, params) { return params.dataIndex === state.nodeIndex ? 12 : 7; }, lineStyle: { width: 2.2 }, areaStyle: { opacity: .05 } },
            { name: "文本倾向", type: "line", yAxisIndex: 1, smooth: .24, data: nodes.map(function (node) { return Number(node.linked_poem.text_emotion.valence); }), symbol: "diamond", symbolSize: function (_v, params) { return params.dataIndex === state.nodeIndex ? 12 : 7; }, lineStyle: { width: 2.2 } },
            { name: "情感强度", type: "line", smooth: .24, data: nodes.map(function (node) { return pct(node.linked_poem.text_emotion.intensity); }), symbol: "triangle", symbolSize: function (_v, params) { return params.dataIndex === state.nodeIndex ? 12 : 7; }, lineStyle: { width: 1.6, type: "dashed" } }
          ]
        }, true);
        charts.trend.off("click");
        charts.trend.on("click", function (params) { if (params.dataIndex != null) selectNode(params.dataIndex); });
      }

      function renderTextProfile() {
        const row = profile();
        document.getElementById("textProfileMeta").textContent = Number(row.poem_count).toLocaleString("zh-CN") + " 首全作品状态的词典与规则命中";
        document.getElementById("lifeSummary").textContent = row.life_summary + row.profile_note;
        document.getElementById("imageryTokens").innerHTML = row.imagery.map(function (item) {
          return '<span class="token" title="' + esc(item.category) + '">' + esc(item.word) + '<b>' + item.count + '</b></span>';
        }).join("") || '<span class="token">暂无命中</span>';
        const max = Math.max.apply(null, row.emotions.map(function (item) { return item.count; }).concat([1]));
        document.getElementById("emotionList").innerHTML = row.emotions.map(function (item) {
          const width = Math.max(4, Math.round(item.count / max * 100));
          return '<div class="emotion-row"><span>' + esc(item.label) + '</span><span class="emotion-track"><span class="emotion-fill" style="width:' + width + '%"></span></span><b>' + item.count + '</b></div>';
        }).join("") || '<span class="token">暂无规则命中</span>';
      }

      function selectNode(index) {
        state.nodeIndex = Math.max(0, Math.min(Number(index), profile().nodes.length - 1));
        renderMap();
        renderTimeline();
        renderDetail();
        renderPeriodAnalysis();
        renderTrend();
      }

      function renderAll() {
        renderPoetSwitch();
        renderProfile();
        renderMap();
        renderTimeline();
        renderDetail();
        renderPeriodAnalysis();
        renderTrend();
        renderTextProfile();
      }

      document.getElementById("sidePoets").textContent = data.corpus.poets;
      document.getElementById("sidePoems").textContent = Number(data.corpus.poems).toLocaleString("zh-CN");
      window.addEventListener("resize", function () { charts.map.resize(); charts.trend.resize(); });
      renderAll();
    }());
  </script>
  <noscript>此页面需要启用 JavaScript 以呈现联动地图与时间曲线。</noscript>
</body>
</html>
"""


def render() -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    payload = build_payload()
    app_data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    generated_at = __import__("datetime").datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")
    html = (
        APP_TEMPLATE.replace("__APP_DATA__", app_data)
        .replace("__GENERATED_AT__", generated_at)
        .replace("__DATA_UPDATED__", str(payload.get("updated_at") or "未标注"))
    )
    OUT_HTML.write_text(html, encoding="utf-8", newline="\n")
    write_manifest()
    print(
        f"  [ok] saved {OUT_HTML}  "
        f"({len(TARGET_POETS)} 位重点诗人 / {payload['corpus']['reviewed_nodes']} 个审核节点 / "
        f"{payload['corpus']['poems']} 首基础语料)"
    )


if __name__ == "__main__":
    render()
