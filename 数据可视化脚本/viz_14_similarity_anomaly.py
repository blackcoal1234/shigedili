"""可视化 14：文本相似推荐与流派异常发现。"""
from __future__ import annotations

import json
import math
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from html import escape
from pathlib import Path

import jieba
import pymysql
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.preprocessing import normalize


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config import DB_NAME, MYSQL, OUTPUT_DIR
from data.image_dict import lookup as lookup_image, words as image_words
from data.place_dict import aliases as place_aliases, lookup as lookup_place
from data.season_rules import detect_season
from viz_assets import inject_index_backlink


POEMS_JSON = ROOT / "data" / "poems.json"
OUTPUT_HTML = OUTPUT_DIR / "14_文本相似与异常发现.html"
MAX_RECOMMENDATIONS = 5
MAX_ANOMALIES_PER_SCHOOL = 8
MAX_TERMS_PER_POEM = 8
MAX_FEATURES = 1800
STOP_WORDS = {
    "一个",
    "一片",
    "万里",
    "不知",
    "不是",
    "人间",
    "今日",
    "何处",
    "千里",
    "无处",
    "无端",
    "春风",
    "明月",
    "相逢",
    "空山",
}


@dataclass
class PoemRecord:
    id: int
    title: str
    poet: str
    dynasty: str
    school: str
    season: str
    sentiment: float
    body_len: int
    body: str
    images: Counter[str] = field(default_factory=Counter)
    places: Counter[str] = field(default_factory=Counter)
    top_terms: list[str] = field(default_factory=list)

    def excerpt(self, length: int = 88) -> str:
        text = " ".join((self.body or "").split())
        return text[:length] + ("..." if len(text) > length else "")

    def to_json(self) -> dict[str, object]:
        return {
            "id": self.id,
            "title": self.title,
            "poet": self.poet,
            "dynasty": self.dynasty,
            "school": self.school,
            "season": self.season,
            "sentiment": round(self.sentiment, 3),
            "body_len": self.body_len,
            "body": self.body,
            "excerpt": self.excerpt(),
            "top_terms": self.top_terms,
            "images": image_rows(self.images, 8),
            "places": place_rows(self.places, 8),
        }


def conn():
    return pymysql.connect(
        **MYSQL,
        database=DB_NAME,
        connect_timeout=5,
        read_timeout=20,
        write_timeout=20,
        cursorclass=pymysql.cursors.DictCursor,
    )


def as_float(value: object) -> float:
    if value is None:
        return 0.0
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


def greedy_counts(text: str, tokens: list[str]) -> Counter[str]:
    """按长词优先贪心计数，避免短词重复吞掉长词。"""
    counts: Counter[str] = Counter()
    work = text or ""
    for token in tokens:
        count = work.count(token)
        if count:
            counts[token] += count
            work = work.replace(token, " " * len(token))
    return counts


def estimate_sentiment(image_counts: Counter[str]) -> float:
    total_weight = sum(image_counts.values())
    if not total_weight:
        return 0.0
    total = 0.0
    for word, count in image_counts.items():
        meta = lookup_image(word)
        if meta:
            total += float(meta["sentiment"]) * count
    return total / total_weight


def image_rows(counter: Counter[str], limit: int | None = None) -> list[dict[str, object]]:
    rows = []
    for word, count in counter.most_common(limit):
        meta = lookup_image(word) or {}
        rows.append(
            {
                "word": word,
                "count": int(count),
                "category": str(meta.get("category") or ""),
                "sentiment": float(meta.get("sentiment") or 0),
            }
        )
    return rows


def place_rows(counter: Counter[str], limit: int | None = None) -> list[dict[str, object]]:
    rows = []
    for alias, count in counter.most_common(limit):
        meta = lookup_place(alias) or {}
        rows.append(
            {
                "alias": alias,
                "count": int(count),
                "modern": str(meta.get("modern") or ""),
                "province": str(meta.get("province") or ""),
            }
        )
    return rows


def attach_database_features(poems: list[PoemRecord]) -> None:
    poem_by_id = {poem.id: poem for poem in poems}
    with conn() as c, c.cursor() as cur:
        cur.execute(
            """
            SELECT pm.poem_id, im.word, pi.freq
              FROM t_poem pm
              JOIN t_poem_image pi ON pi.poem_id = pm.poem_id
              JOIN t_image im ON im.image_id = pi.image_id
            """
        )
        for row in cur.fetchall():
            poem = poem_by_id.get(int(row["poem_id"]))
            if poem:
                poem.images[str(row["word"])] += int(row.get("freq") or 1)

        cur.execute(
            """
            SELECT pm.poem_id, pl.alias, pp.freq
              FROM t_poem pm
              JOIN t_poem_place pp ON pp.poem_id = pm.poem_id
              JOIN t_place pl ON pl.place_id = pp.place_id
            """
        )
        for row in cur.fetchall():
            poem = poem_by_id.get(int(row["poem_id"]))
            if poem:
                poem.places[str(row["alias"])] += int(row.get("freq") or 1)


def load_from_database() -> list[PoemRecord]:
    with conn() as c, c.cursor() as cur:
        cur.execute(
            """
            SELECT pm.poem_id AS id,
                   pm.title,
                   pt.name AS poet,
                   pt.dynasty,
                   COALESCE(pt.school, '') AS school,
                   COALESCE(NULLIF(pm.season, ''), '未标') AS season,
                   pm.sentiment,
                   pm.body_len,
                   pm.body
              FROM t_poem pm
              JOIN t_poet pt ON pt.poet_id = pm.poet_id
             ORDER BY pm.poem_id
            """
        )
        rows = cur.fetchall()
    poems = [
        PoemRecord(
            id=int(row["id"]),
            title=str(row.get("title") or ""),
            poet=str(row.get("poet") or ""),
            dynasty=str(row.get("dynasty") or ""),
            school=str(row.get("school") or "未分流派"),
            season=str(row.get("season") or "未标"),
            sentiment=as_float(row.get("sentiment")),
            body_len=int(row.get("body_len") or len(str(row.get("body") or ""))),
            body=str(row.get("body") or ""),
        )
        for row in rows
    ]
    attach_database_features(poems)
    return poems


def load_from_poems_json(reason: Exception | None = None) -> list[PoemRecord]:
    if reason is not None:
        print(f"  [warn] 数据库读取失败，改用 poems.json 离线兜底：{reason}")
    records = json.loads(POEMS_JSON.read_text(encoding="utf-8"))
    image_tokens = image_words()
    place_tokens = place_aliases()
    poems: list[PoemRecord] = []
    for index, row in enumerate(records):
        title = str(row.get("title") or "")
        body = str(row.get("body") or "")
        text = f"{title}\n{body}"
        images = greedy_counts(body, image_tokens)
        places = greedy_counts(text, place_tokens)
        poems.append(
            PoemRecord(
                id=index,
                title=title,
                poet=str(row.get("poet") or row.get("author") or ""),
                dynasty=str(row.get("dynasty") or ""),
                school=str(row.get("school") or "未分流派"),
                season=detect_season(title, body) or "未标",
                sentiment=estimate_sentiment(images),
                body_len=len(body),
                body=body,
                images=images,
                places=places,
            )
        )
    return poems


def load_poems() -> list[PoemRecord]:
    try:
        poems = load_from_database()
        if poems:
            return poems
        raise RuntimeError("数据库没有诗作记录")
    except Exception as exc:
        return load_from_poems_json(exc)


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for token in jieba.lcut(text or ""):
        token = token.strip()
        if len(token) < 2:
            continue
        if token in STOP_WORDS:
            continue
        if token.isdigit():
            continue
        tokens.append(token)
    return tokens


def top_terms_for_row(matrix, feature_names, row_index: int, limit: int) -> list[str]:
    row = matrix.getrow(row_index)
    if row.nnz == 0:
        return []
    items = sorted(zip(row.indices, row.data), key=lambda item: float(item[1]), reverse=True)
    return [str(feature_names[index]) for index, _ in items[:limit]]


def term_overlap(a: list[str], b: list[str], limit: int = 6) -> list[str]:
    seen = set(b)
    return [term for term in a if term in seen][:limit]


def counter_overlap(a: Counter[str], b: Counter[str], limit: int = 6) -> list[str]:
    return [word for word, _ in (a & b).most_common(limit)]


def safe_score(value: float) -> float:
    if math.isnan(value) or math.isinf(value):
        return 0.0
    return round(max(0.0, min(1.0, float(value))), 4)


def build_recommendations(poems: list[PoemRecord], similarity) -> dict[str, list[dict[str, object]]]:
    result: dict[str, list[dict[str, object]]] = {}
    for row_index, poem in enumerate(poems):
        candidates = []
        for col_index, score in enumerate(similarity[row_index]):
            if row_index == col_index:
                continue
            other = poems[col_index]
            candidates.append((float(score), other))
        top = sorted(candidates, key=lambda item: item[0], reverse=True)[:MAX_RECOMMENDATIONS]
        rows = []
        for score, other in top:
            rows.append(
                {
                    "id": other.id,
                    "title": other.title,
                    "poet": other.poet,
                    "school": other.school,
                    "season": other.season,
                    "score": safe_score(score),
                    "common_terms": term_overlap(poem.top_terms, other.top_terms),
                    "common_images": counter_overlap(poem.images, other.images),
                    "common_places": counter_overlap(poem.places, other.places),
                    "season_match": poem.season == other.season and poem.season != "未标",
                    "sentiment_delta": round(abs(poem.sentiment - other.sentiment), 3),
                    "excerpt": other.excerpt(),
                }
            )
        result[str(poem.id)] = rows
    return result


def build_anomalies(poems: list[PoemRecord], matrix) -> dict[str, list[dict[str, object]]]:
    index_by_school: dict[str, list[int]] = defaultdict(list)
    for index, poem in enumerate(poems):
        if poem.school:
            index_by_school[poem.school].append(index)

    school_centroids = {}
    for school, indices in index_by_school.items():
        if len(indices) < 2:
            continue
        centroid = matrix[indices].mean(axis=0).A
        school_centroids[school] = normalize(centroid, norm="l2")

    result: dict[str, list[dict[str, object]]] = {}
    for school, indices in index_by_school.items():
        centroid = school_centroids.get(school)
        if centroid is None:
            continue
        rows = []
        for index in indices:
            poem = poems[index]
            own_similarity = float(cosine_similarity(matrix[index], centroid)[0][0])
            nearest_school = ""
            nearest_score = 0.0
            for other_school, other_centroid in school_centroids.items():
                if other_school == school:
                    continue
                score = float(cosine_similarity(matrix[index], other_centroid)[0][0])
                if score > nearest_score:
                    nearest_school = other_school
                    nearest_score = score
            rows.append(
                {
                    "id": poem.id,
                    "title": poem.title,
                    "poet": poem.poet,
                    "school": poem.school,
                    "season": poem.season,
                    "anomaly_score": safe_score(1 - own_similarity),
                    "center_similarity": safe_score(own_similarity),
                    "nearest_school": nearest_school,
                    "nearest_school_similarity": safe_score(nearest_score),
                    "top_terms": poem.top_terms[:6],
                    "top_images": image_rows(poem.images, 5),
                    "top_places": place_rows(poem.places, 5),
                    "sentiment": round(poem.sentiment, 3),
                    "excerpt": poem.excerpt(),
                    "explanation": explain_anomaly(poem, school, nearest_school, own_similarity, nearest_score),
                }
            )
        result[school] = sorted(rows, key=lambda item: float(item["anomaly_score"]), reverse=True)[
            :MAX_ANOMALIES_PER_SCHOOL
        ]
    return dict(sorted(result.items(), key=lambda item: item[0]))


def explain_anomaly(
    poem: PoemRecord,
    school: str,
    nearest_school: str,
    own_similarity: float,
    nearest_score: float,
) -> str:
    parts = [
        f"它与「{school}」中心的文本相似度为 {safe_score(own_similarity):.2f}",
    ]
    if nearest_school:
        parts.append(f"同时更接近「{nearest_school}」中心（{safe_score(nearest_score):.2f}）")
    if poem.top_terms:
        parts.append("高权重词为：" + "、".join(poem.top_terms[:4]))
    if poem.images:
        parts.append("主要意象为：" + "、".join(word for word, _ in poem.images.most_common(4)))
    return "；".join(parts) + "。"


def build_payload() -> dict[str, object]:
    poems = load_poems()
    if not poems:
        raise RuntimeError("没有可用于文本相似分析的诗作数据")

    corpus = [f"{poem.title}\n{poem.body}" for poem in poems]
    vectorizer = TfidfVectorizer(tokenizer=tokenize, token_pattern=None, max_features=MAX_FEATURES)
    matrix = vectorizer.fit_transform(corpus)
    feature_names = vectorizer.get_feature_names_out()
    for index, poem in enumerate(poems):
        poem.top_terms = top_terms_for_row(matrix, feature_names, index, MAX_TERMS_PER_POEM)

    similarity = cosine_similarity(matrix)
    return {
        "summary": {
            "poem_count": len(poems),
            "poet_count": len({poem.poet for poem in poems if poem.poet}),
            "school_count": len({poem.school for poem in poems if poem.school}),
            "feature_count": int(matrix.shape[1]),
            "algorithm": "jieba + scikit-learn TfidfVectorizer + cosine_similarity",
        },
        "poems": [poem.to_json() for poem in poems],
        "recommendations": build_recommendations(poems, similarity),
        "anomalies": build_anomalies(poems, matrix),
    }


def render_stat_cards(summary: dict[str, object]) -> str:
    items = (
        ("诗作数量", summary.get("poem_count", 0)),
        ("诗人数量", summary.get("poet_count", 0)),
        ("流派数量", summary.get("school_count", 0)),
        ("TF-IDF 特征", summary.get("feature_count", 0)),
    )
    return "\n".join(
        f"""
        <div class="stat-card">
            <span>{escape(label)}</span>
            <strong>{escape(str(value))}</strong>
        </div>
        """
        for label, value in items
    )


def render_html(payload: dict[str, object]) -> str:
    data_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    summary = payload["summary"]
    stat_cards = render_stat_cards(summary if isinstance(summary, dict) else {})
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>诗行万里 · 文本相似与异常发现</title>
    <style>
    :root {{
        --bg: #eef2f0;
        --panel: #fffdf7;
        --ink: #18212f;
        --muted: #667085;
        --soft: #f6f4ec;
        --line: #d8ddd3;
        --line-strong: #bac4b8;
        --blue: #2454a6;
        --green: #14746f;
        --orange: #b45309;
        --red: #b42318;
        --shadow: 0 18px 42px rgba(24, 33, 47, 0.10);
    }}
    * {{ box-sizing: border-box; }}
    body {{
        margin: 0;
        min-height: 100vh;
        background:
            linear-gradient(#dbe3dc 1px, transparent 1px),
            linear-gradient(90deg, #dbe3dc 1px, transparent 1px),
            var(--bg);
        background-size: 28px 28px;
        color: var(--ink);
        font-family: "Microsoft YaHei", "PingFang SC", Arial, sans-serif;
    }}
    .app-shell {{
        width: min(1460px, calc(100vw - 28px));
        margin: 0 auto;
        padding: 18px 0 34px;
    }}
    .workspace-hero {{
        display: grid;
        grid-template-columns: minmax(0, 1fr) minmax(360px, 440px);
        gap: 12px;
        align-items: stretch;
        margin-bottom: 12px;
    }}
    .briefing, .panel {{
        border: 1px solid var(--line-strong);
        border-radius: 8px;
        background: rgba(255, 253, 247, 0.96);
        box-shadow: var(--shadow);
    }}
    .briefing {{
        min-height: 172px;
        padding: 20px 22px;
    }}
    .eyebrow {{
        display: inline-flex;
        align-items: center;
        min-height: 24px;
        padding: 0 9px;
        border: 1px solid var(--line);
        border-radius: 999px;
        background: #ffffff;
        color: var(--green);
        font-size: 12px;
        font-weight: 900;
    }}
    h1 {{
        margin: 14px 0 0;
        font-size: 34px;
        line-height: 1.15;
        letter-spacing: 0;
    }}
    .subtitle {{
        margin: 12px 0 0;
        max-width: 860px;
        color: var(--muted);
        line-height: 1.8;
        font-size: 14px;
    }}
    .stats {{
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 8px;
        padding: 10px;
    }}
    .stat-card {{
        min-height: 74px;
        border: 1px solid var(--line);
        border-radius: 8px;
        padding: 11px 12px;
        background: #ffffff;
    }}
    .stat-card span {{
        display: block;
        color: var(--muted);
        font-size: 12px;
        font-weight: 700;
    }}
    .stat-card strong {{
        display: block;
        margin-top: 8px;
        font-size: 24px;
        line-height: 1;
    }}
    .mining-workbench {{
        display: grid;
        grid-template-columns: 320px minmax(0, 1fr) 360px;
        gap: 12px;
        align-items: start;
    }}
    .panel {{
        padding: 16px;
    }}
    .panel h2 {{
        margin: 0;
        font-size: 18px;
        line-height: 1.25;
    }}
    .section-kicker {{
        margin: 4px 0 0;
        color: var(--muted);
        font-size: 12px;
        font-weight: 800;
    }}
    .hint {{
        margin: 10px 0 14px;
        color: var(--muted);
        font-size: 13px;
        line-height: 1.7;
    }}
    .sample-rail {{
        position: sticky;
        top: 12px;
    }}
    .controls {{
        display: grid;
        gap: 10px;
        margin-bottom: 12px;
    }}
    .control-label {{
        display: grid;
        gap: 6px;
        color: var(--muted);
        font-size: 12px;
        font-weight: 800;
    }}
    input, select {{
        width: 100%;
        min-height: 42px;
        border: 1px solid var(--line-strong);
        border-radius: 8px;
        padding: 8px 10px;
        font: inherit;
        font-size: 13px;
        color: var(--ink);
        background: #ffffff;
        outline: none;
    }}
    input:focus, select:focus {{
        border-color: var(--blue);
        box-shadow: 0 0 0 3px rgba(36, 84, 166, 0.12);
    }}
    .selected-poem {{
        border: 1px solid var(--line);
        border-radius: 8px;
        padding: 13px;
        background: var(--soft);
    }}
    .selected-poem h3, .item h3 {{
        margin: 0;
        font-size: 16px;
        line-height: 1.35;
    }}
    .result-column {{
        min-height: 620px;
    }}
    .result-column .list {{
        display: grid;
        gap: 10px;
    }}
    .evidence-column {{
        position: sticky;
        top: 12px;
    }}
    .meta {{
        display: flex;
        flex-wrap: wrap;
        gap: 6px;
        margin: 9px 0;
    }}
    .tag {{
        display: inline-flex;
        align-items: center;
        min-height: 23px;
        border: 1px solid rgba(36, 84, 166, 0.16);
        border-radius: 999px;
        padding: 2px 8px;
        background: #eef4ff;
        color: var(--blue);
        font-size: 12px;
        font-weight: 800;
    }}
    .tag.green {{
        border-color: rgba(20, 116, 111, 0.18);
        background: #e9f7f4;
        color: var(--green);
    }}
    .tag.orange {{
        border-color: rgba(180, 83, 9, 0.18);
        background: #fff4df;
        color: var(--orange);
    }}
    .excerpt {{
        color: var(--muted);
        font-size: 13px;
        line-height: 1.78;
        margin: 8px 0 0;
    }}
    .list {{
        display: grid;
        gap: 10px;
    }}
    .item {{
        border: 1px solid var(--line);
        border-radius: 8px;
        padding: 13px;
        background: #ffffff;
    }}
    .item-head {{
        display: flex;
        justify-content: space-between;
        gap: 12px;
        align-items: flex-start;
    }}
    .similarity-score, .anomaly-score {{
        flex: none;
        min-width: 74px;
        text-align: right;
        font-size: 20px;
        font-weight: 900;
        color: var(--blue);
    }}
    .anomaly-score {{
        color: var(--red);
    }}
    .score-bar {{
        height: 7px;
        border-radius: 999px;
        background: #e5e7eb;
        overflow: hidden;
        margin-top: 10px;
    }}
    .score-bar i {{
        display: block;
        height: 100%;
        width: 0%;
        background: var(--green);
    }}
    .anomaly-board {{
        margin-top: 12px;
    }}
    .anomaly-board .list {{
        grid-template-columns: repeat(2, minmax(0, 1fr));
    }}
    .tabs {{
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
        margin: 12px 0;
        padding-bottom: 10px;
        border-bottom: 1px solid var(--line);
    }}
    .tabs button {{
        border: 1px solid var(--line-strong);
        border-radius: 999px;
        padding: 7px 12px;
        background: #ffffff;
        color: var(--muted);
        cursor: pointer;
        font-weight: 800;
    }}
    .tabs button.active {{
        color: #ffffff;
        border-color: var(--green);
        background: var(--green);
    }}
    .explain-block {{
        border: 1px solid var(--line);
        border-radius: 8px;
        padding: 12px;
        margin: 10px 0;
        background: #ffffff;
    }}
    .explain-block strong {{
        display: block;
        font-size: 14px;
    }}
    .explain-block p {{
        margin: 6px 0 0;
        color: var(--muted);
        font-size: 13px;
        line-height: 1.7;
    }}
    .empty {{
        border: 1px dashed var(--line-strong);
        border-radius: 8px;
        padding: 18px;
        color: var(--muted);
        text-align: center;
        background: #ffffff;
    }}
    @media (max-width: 1180px) {{
        .workspace-hero, .mining-workbench {{
            grid-template-columns: 1fr;
        }}
        .sample-rail, .evidence-column {{
            position: static;
        }}
        .anomaly-board .list {{
            grid-template-columns: 1fr;
        }}
    }}
    @media (max-width: 680px) {{
        .app-shell {{
            width: min(100vw - 18px, 1460px);
            padding-top: 10px;
        }}
        .stats {{
            grid-template-columns: 1fr;
        }}
        h1 {{
            font-size: 28px;
        }}
    }}

    /* Case-file redesign: deliberately separate from the visual language of the other pages. */
    body {{
        color: #e8e3d6;
        background:
            radial-gradient(circle at 18px 18px, rgba(255,255,255,0.08) 1px, transparent 1px),
            linear-gradient(135deg, #101111, #252725 52%, #151616);
        background-size: 36px 36px, auto;
        font-family: "Microsoft YaHei", "PingFang SC", Arial, sans-serif;
    }}
    .forensic-shell {{
        width: min(1500px, calc(100vw - 30px));
        margin: 0 auto;
        padding: 20px 0 36px;
    }}
    .case-header {{
        position: relative;
        min-height: 214px;
        margin-bottom: 16px;
        padding: 24px 28px;
        border: 1px solid rgba(243, 234, 213, 0.22);
        border-radius: 2px;
        background: linear-gradient(135deg, rgba(243, 234, 213, 0.10), rgba(255,255,255,0.03));
        overflow: hidden;
    }}
    .case-header::before {{
        content: "TF-IDF / COSINE";
        position: absolute;
        right: 22px;
        top: 18px;
        padding: 8px 12px;
        border: 2px solid rgba(179, 38, 30, 0.72);
        color: rgba(255, 212, 203, 0.86);
        font-family: Consolas, "Courier New", monospace;
        font-size: 14px;
        font-weight: 900;
        transform: rotate(5deg);
    }}
    .case-id {{
        display: inline-flex;
        align-items: center;
        min-height: 26px;
        padding: 0 10px;
        border: 1px solid rgba(243, 234, 213, 0.38);
        color: #f9d56e;
        font-family: Consolas, "Courier New", monospace;
        font-size: 12px;
        font-weight: 900;
        letter-spacing: 0.08em;
    }}
    .case-header h1 {{
        max-width: 880px;
        margin: 18px 0 0;
        color: #fff6dc;
        font-size: 46px;
        line-height: 1.05;
    }}
    .case-header .subtitle {{
        max-width: 850px;
        color: #d2c8b5;
    }}
    .case-header .stats {{
        position: absolute;
        right: 24px;
        bottom: 20px;
        width: min(430px, calc(100% - 48px));
        grid-template-columns: repeat(4, minmax(0, 1fr));
        gap: 1px;
        padding: 0;
        border: 1px solid rgba(243, 234, 213, 0.32);
        background: rgba(243, 234, 213, 0.32);
    }}
    .case-header .stat-card {{
        min-height: 74px;
        border: 0;
        border-radius: 0;
        padding: 10px;
        background: rgba(17, 19, 19, 0.84);
        box-shadow: none;
    }}
    .case-header .stat-card span {{
        color: #bdb39f;
        font-size: 11px;
        font-weight: 900;
    }}
    .case-header .stat-card strong {{
        color: #fff6dc;
        font-family: Consolas, "Courier New", monospace;
        font-size: 22px;
    }}
    .case-file-layout {{
        display: grid;
        grid-template-columns: 300px minmax(0, 1fr) 340px;
        gap: 16px;
        align-items: start;
    }}
    .dossier-strip {{
        position: sticky;
        top: 14px;
        padding: 15px;
        border-radius: 2px;
        background: #f3ead5;
        color: #24201a;
        box-shadow: 8px 10px 0 rgba(0, 0, 0, 0.38);
        transform: rotate(-0.6deg);
    }}
    .evidence-ledger {{
        padding: 14px;
        border: 1px solid rgba(243, 234, 213, 0.26);
        border-radius: 2px;
        background: #171919;
        box-shadow: inset 0 0 0 1px rgba(255,255,255,0.03);
    }}
    .forensic-notes {{
        position: sticky;
        top: 14px;
        padding: 15px;
        border-radius: 2px;
        background: #efe0b7;
        color: #24201a;
        box-shadow: -8px 10px 0 rgba(0, 0, 0, 0.36);
        transform: rotate(0.7deg);
    }}
    .outlier-wall {{
        margin-top: 16px;
        padding: 16px;
        border: 1px solid rgba(243, 234, 213, 0.24);
        border-radius: 2px;
        background: rgba(10, 11, 11, 0.72);
    }}
    .evidence-ledger h2,
    .outlier-wall h2 {{
        color: #fff6dc;
    }}
    .case-file-layout .section-kicker,
    .outlier-wall .section-kicker {{
        color: #f5c451;
        font-family: Consolas, "Courier New", monospace;
        letter-spacing: 0.08em;
        text-transform: uppercase;
    }}
    .dossier-strip .section-kicker,
    .forensic-notes .section-kicker {{
        color: #b3261e;
    }}
    .dossier-strip .hint,
    .forensic-notes .hint {{
        color: #746b5c;
        opacity: 1;
    }}
    .dossier-strip input,
    .dossier-strip select {{
        border: 2px solid rgba(36, 32, 26, 0.42);
        border-radius: 0;
        background: #fff9e8;
        color: #24201a;
    }}
    .dossier-strip input:focus,
    .dossier-strip select:focus {{
        border-color: #b3261e;
        box-shadow: 0 0 0 3px rgba(179, 38, 30, 0.12);
    }}
    .selected-poem {{
        position: relative;
        border: 1px dashed rgba(36, 32, 26, 0.46);
        border-radius: 0;
        background: #fff8e4;
        color: #24201a;
    }}
    .selected-poem::before {{
        content: "CURRENT SAMPLE";
        position: absolute;
        right: 10px;
        top: -10px;
        padding: 2px 7px;
        background: #b3261e;
        color: #fff8e4;
        font-family: Consolas, "Courier New", monospace;
        font-size: 10px;
        font-weight: 900;
    }}
    .evidence-ledger .list,
    .outlier-wall .list {{
        display: grid;
        gap: 11px;
    }}
    .item {{
        position: relative;
        border: 1px solid rgba(243, 234, 213, 0.28);
        border-left: 6px solid #f5c451;
        border-radius: 0;
        padding: 13px 13px 13px 15px;
        background: #222524;
        color: #f1eadb;
        box-shadow: none;
    }}
    .recommendation-item::before {{
        content: "MATCH";
        position: absolute;
        right: 10px;
        top: 8px;
        color: rgba(245, 196, 81, 0.65);
        font-family: Consolas, "Courier New", monospace;
        font-size: 10px;
        font-weight: 900;
    }}
    .anomaly-item {{
        border-left-color: #b3261e;
        background: #251d1b;
    }}
    .item-head {{
        padding-right: 48px;
    }}
    .similarity-score,
    .anomaly-score {{
        color: #f5c451;
        font-family: Consolas, "Courier New", monospace;
        font-size: 22px;
    }}
    .anomaly-score {{
        color: #ff8a7a;
    }}
    .score-bar {{
        height: 8px;
        border-radius: 0;
        background: rgba(243, 234, 213, 0.14);
    }}
    .score-bar i {{
        background: repeating-linear-gradient(90deg, #f5c451 0 10px, #d79c20 10px 14px);
    }}
    .tag {{
        border-radius: 0;
        background: #fff0bd;
        color: #4a3a1a;
    }}
    .item .tag {{
        border-color: rgba(243, 234, 213, 0.26);
        background: rgba(243, 234, 213, 0.13);
        color: #f0dfb9;
    }}
    .item .tag.green {{
        background: rgba(47, 111, 78, 0.16);
        color: #8fe0b3;
    }}
    .item .tag.orange {{
        background: rgba(184, 130, 22, 0.18);
        color: #ffd27d;
    }}
    .forensic-notes .explain-block {{
        margin: 12px 0;
        padding: 10px 10px 10px 14px;
        border: 0;
        border-left: 4px solid #b3261e;
        border-radius: 0;
        background: rgba(255, 248, 228, 0.70);
    }}
    .forensic-notes .explain-block p {{
        color: #746b5c;
    }}
    .tabs {{
        border-bottom: 1px solid rgba(243, 234, 213, 0.22);
    }}
    .tabs button {{
        border: 1px solid rgba(243, 234, 213, 0.30);
        border-radius: 0;
        background: transparent;
        color: #d9cdb7;
    }}
    .tabs button.active {{
        border-color: #b3261e;
        background: #b3261e;
        color: #fff8e4;
    }}
    .outlier-wall .list {{
        grid-template-columns: repeat(3, minmax(0, 1fr));
    }}
    @media (max-width: 1260px) {{
        .case-file-layout {{
            grid-template-columns: 1fr;
        }}
        .dossier-strip,
        .forensic-notes {{
            position: static;
            transform: none;
        }}
        .outlier-wall .list {{
            grid-template-columns: 1fr;
        }}
        .case-header .stats {{
            position: static;
            width: 100%;
            margin-top: 18px;
        }}
    }}
    @media (max-width: 720px) {{
        .forensic-shell {{
            width: min(100vw - 18px, 1500px);
            padding-top: 10px;
        }}
        .case-header {{
            padding: 18px;
        }}
        .case-header h1 {{
            font-size: 32px;
        }}
        .case-header .stats {{
            grid-template-columns: repeat(2, minmax(0, 1fr));
        }}
    }}
    </style>
</head>
<body>
    <main class="forensic-shell">
        <section class="case-header">
            <span class="case-id">CASE 14 / 文本取证实验室</span>
            <h1>诗行万里 · 文本相似与异常发现</h1>
            <p class="subtitle">
                基于 jieba 分词、TF-IDF 特征和余弦相似度，自动发现诗作之间的文本近邻，
                并计算每首诗偏离本流派中心的程度。意象、地名、季节和情感只用于解释结果，不混入相似度权重。
            </p>
            <div class="stats">
                {stat_cards}
            </div>
        </section>

        <section class="case-file-layout">
            <aside class="dossier-strip">
                <h2>样本卷宗</h2>
                <p class="section-kicker">Poem Dossier</p>
                <p class="hint">从诗题、诗人、流派或关键词定位样本，右侧实时更新近邻推荐和解释证据。</p>
                <div class="controls">
                    <label class="control-label" for="queryInput">
                        搜索样本
                        <input id="queryInput" type="search" placeholder="搜索诗题、诗人、流派或关键词">
                    </label>
                    <label class="control-label" for="poemSelect">
                        当前诗作
                        <select id="poemSelect" aria-label="选择诗作"></select>
                    </label>
                </div>
                <div id="selectedPoemPanel" class="selected-poem"></div>
            </aside>

            <div class="evidence-ledger">
                <h2>相似诗推荐</h2>
                <p class="section-kicker">Top 5 Text Matches</p>
                <p class="hint">按 TF-IDF 余弦相似度排序，列出最接近当前样本的 5 首作品。</p>
                <div id="recommendationList" class="list"></div>
            </div>

            <aside class="forensic-notes">
                <h2>算法解释</h2>
                <p class="section-kicker">Forensic Notes</p>
                <p class="hint">这里把黑盒分数拆成可读证据，方便答辩时说明“为什么相似”和“为什么异常”。</p>
                <div id="explainPanel"></div>
            </aside>
        </section>

        <section class="outlier-wall">
            <h2>流派异常发现</h2>
            <p class="section-kicker">Outlier Wall</p>
            <p class="hint">每个流派计算一个 TF-IDF 中心向量。诗作离本流派中心越远，异常分越高；如果它更接近其他流派中心，页面会给出对照流派。</p>
            <div id="schoolTabs" class="tabs"></div>
            <div id="anomalyList" class="list"></div>
        </section>
    </main>

    <script>
    window.SIMILARITY_ANOMALY_DATA = {data_json};
    </script>
    <script>
    (function () {{
        var data = window.SIMILARITY_ANOMALY_DATA || {{}};
        var poems = data.poems || [];
        var poemById = Object.create(null);
        poems.forEach(function (poem) {{ poemById[String(poem.id)] = poem; }});
        var selectedSchool = Object.keys(data.anomalies || {{}})[0] || "";

        function el(id) {{ return document.getElementById(id); }}
        function escapeHtml(value) {{
            return String(value == null ? "" : value)
                .replace(/&/g, "&amp;")
                .replace(/</g, "&lt;")
                .replace(/>/g, "&gt;")
                .replace(/"/g, "&quot;")
                .replace(/'/g, "&#39;");
        }}
        function tags(items, className, key) {{
            if (!items || !items.length) return '<span class="tag">无</span>';
            return items.slice(0, 6).map(function (item) {{
                var text = typeof item === "string" ? item : (item[key] || item.word || item.alias || "");
                return '<span class="tag ' + (className || "") + '">' + escapeHtml(text) + '</span>';
            }}).join("");
        }}
        function scoreBar(score) {{
            var pct = Math.max(0, Math.min(100, Math.round(Number(score || 0) * 100)));
            return '<div class="score-bar"><i style="width:' + pct + '%"></i></div>';
        }}
        function poemLabel(poem) {{
            return '《' + poem.title + '》 ' + poem.poet + ' · ' + poem.school;
        }}
        function filteredPoems() {{
            var q = String(el("queryInput").value || "").trim().toLowerCase();
            if (!q) return poems;
            return poems.filter(function (poem) {{
                return [poem.title, poem.poet, poem.school, poem.season, poem.body, (poem.top_terms || []).join(" ")]
                    .join(" ").toLowerCase().indexOf(q) >= 0;
            }});
        }}
        function fillSelect(keepId) {{
            var select = el("poemSelect");
            var rows = filteredPoems().slice(0, 200);
            if (!rows.length) {{
                select.innerHTML = '<option value="">没有匹配诗作</option>';
                return "";
            }}
            var keep = rows.some(function (poem) {{ return String(poem.id) === String(keepId); }}) ? String(keepId) : String(rows[0].id);
            select.innerHTML = rows.map(function (poem) {{
                return '<option value="' + escapeHtml(poem.id) + '">' + escapeHtml(poemLabel(poem)) + '</option>';
            }}).join("");
            select.value = keep;
            return keep;
        }}
        function renderSelected(poem) {{
            if (!poem) {{
                el("selectedPoemPanel").innerHTML = '<div class="empty">请选择一首诗</div>';
                return;
            }}
            el("selectedPoemPanel").innerHTML =
                '<h3>《' + escapeHtml(poem.title) + '》 ' + escapeHtml(poem.poet) + '</h3>' +
                '<div class="meta">' +
                    '<span class="tag">' + escapeHtml(poem.dynasty) + '</span>' +
                    '<span class="tag green">' + escapeHtml(poem.school) + '</span>' +
                    '<span class="tag orange">' + escapeHtml(poem.season) + '</span>' +
                    '<span class="tag">情感 ' + escapeHtml(poem.sentiment) + '</span>' +
                '</div>' +
                '<p class="excerpt">' + escapeHtml(poem.excerpt || poem.body || "") + '</p>' +
                '<div class="meta">' + tags(poem.top_terms, "", "word") + '</div>';
        }}
        function renderRecommendations(poem) {{
            var rows = poem ? (data.recommendations || {{}})[String(poem.id)] || [] : [];
            if (!rows.length) {{
                el("recommendationList").innerHTML = '<div class="empty">暂无推荐结果</div>';
                return;
            }}
            el("recommendationList").innerHTML = rows.map(function (row) {{
                var evidence = []
                    .concat((row.common_terms || []).map(function (x) {{ return "词：" + x; }}))
                    .concat((row.common_images || []).map(function (x) {{ return "意象：" + x; }}))
                    .concat((row.common_places || []).map(function (x) {{ return "地名：" + x; }}));
                if (row.season_match) evidence.push("同季节");
                return '<article class="item recommendation-item">' +
                    '<div class="item-head">' +
                        '<div><h3>《' + escapeHtml(row.title) + '》 ' + escapeHtml(row.poet) + '</h3>' +
                        '<div class="meta"><span class="tag green">' + escapeHtml(row.school) + '</span><span class="tag orange">' + escapeHtml(row.season) + '</span></div></div>' +
                        '<div class="similarity-score">' + Math.round(Number(row.score) * 100) + '%</div>' +
                    '</div>' +
                    scoreBar(row.score) +
                    '<p class="excerpt">' + escapeHtml(row.excerpt || "") + '</p>' +
                    '<div class="meta">' + tags(evidence, "", "word") + '</div>' +
                    '<p class="excerpt">情感差值：' + escapeHtml(row.sentiment_delta) + '</p>' +
                '</article>';
            }}).join("");
        }}
        function renderExplain(poem) {{
            if (!poem) {{
                el("explainPanel").innerHTML = '<div class="empty">暂无解释</div>';
                return;
            }}
            var rec = ((data.recommendations || {{}})[String(poem.id)] || [])[0];
            var common = rec ? (rec.common_terms || []).concat(rec.common_images || []).concat(rec.common_places || []) : [];
            el("explainPanel").innerHTML =
                '<div class="explain-block"><strong>文本相似</strong><p>jieba 分词后进入 TfidfVectorizer，使用 cosine_similarity 计算诗作之间的余弦相似度。</p></div>' +
                '<div class="explain-block"><strong>当前诗关键词</strong><p>' + escapeHtml((poem.top_terms || []).join("、") || "无") + '</p></div>' +
                '<div class="explain-block"><strong>共同关键词</strong><p>' + escapeHtml(common.join("、") || "推荐项与当前诗暂无显著共同证据") + '</p></div>' +
                '<div class="explain-block"><strong>结构化证据</strong><p>共同意象、地名、季节和情感差异只用于解释，不参与最终相似度权重。</p></div>';
        }}
        function selectPoem(nextId) {{
            var poem = poemById[String(nextId)] || poems[0];
            if (!poem) return;
            el("poemSelect").value = String(poem.id);
            renderSelected(poem);
            renderRecommendations(poem);
            renderExplain(poem);
        }}
        function renderSchoolTabs() {{
            var schools = Object.keys(data.anomalies || {{}});
            el("schoolTabs").innerHTML = schools.map(function (school) {{
                return '<button type="button" data-school="' + escapeHtml(school) + '" class="' + (school === selectedSchool ? "active" : "") + '">' + escapeHtml(school) + '</button>';
            }}).join("");
            Array.prototype.forEach.call(el("schoolTabs").querySelectorAll("button"), function (button) {{
                button.addEventListener("click", function () {{
                    selectedSchool = button.getAttribute("data-school") || "";
                    renderSchoolTabs();
                    renderAnomalies();
                }});
            }});
        }}
        function renderAnomalies() {{
            var rows = (data.anomalies || {{}})[selectedSchool] || [];
            if (!rows.length) {{
                el("anomalyList").innerHTML = '<div class="empty">暂无异常结果</div>';
                return;
            }}
            el("anomalyList").innerHTML = rows.map(function (row) {{
                return '<article class="item anomaly-item">' +
                    '<div class="item-head">' +
                        '<div><h3>《' + escapeHtml(row.title) + '》 ' + escapeHtml(row.poet) + '</h3>' +
                        '<div class="meta"><span class="tag green">' + escapeHtml(row.school) + '</span><span class="tag orange">' + escapeHtml(row.season) + '</span><span class="tag">接近：' + escapeHtml(row.nearest_school || "无") + '</span></div></div>' +
                        '<div class="anomaly-score">' + Math.round(Number(row.anomaly_score) * 100) + '%</div>' +
                    '</div>' +
                    scoreBar(row.anomaly_score) +
                    '<p class="excerpt">' + escapeHtml(row.explanation || "") + '</p>' +
                    '<div class="meta">' + tags(row.top_terms || [], "", "word") + tags(row.top_images || [], "green", "word") + tags(row.top_places || [], "orange", "alias") + '</div>' +
                '</article>';
            }}).join("");
        }}
        var initialized = false;
        function init() {{
            if (initialized) return;
            initialized = true;
            var firstId = fillSelect(poems[0] && poems[0].id);
            selectPoem(firstId);
            renderSchoolTabs();
            renderAnomalies();
            el("queryInput").addEventListener("input", function () {{
                var nextId = fillSelect(el("poemSelect").value);
                selectPoem(nextId);
            }});
            el("poemSelect").addEventListener("change", function () {{
                selectPoem(this.value);
            }});
        }}
        document.addEventListener("DOMContentLoaded", init);
        if (document.readyState !== "loading") init();
    }})();
    </script>
</body>
</html>
"""
    return inject_index_backlink(html)


def render() -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    payload = build_payload()
    OUTPUT_HTML.write_text(render_html(payload), encoding="utf-8")
    print(
        f"  [ok] saved {OUTPUT_HTML} "
        f"({payload['summary']['poem_count']} 首诗 / {payload['summary']['feature_count']} 个 TF-IDF 特征)"
    )


if __name__ == "__main__":
    render()
