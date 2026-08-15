"""生成主题版数据库 ER 图（PNG + SVG）。"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

plt.rcParams["font.family"] = ["Microsoft YaHei", "SimHei", "sans-serif"]
plt.rcParams["axes.unicode_minus"] = False

GROUPS = {
    "核心文本": {
        "color": "#dbeafe",
        "border": "#2563eb",
        "tables": [
            ("t_poet", ["poet_id PK", "name", "dynasty", "poem_count"]),
            ("t_poem", ["poem_id PK", "poet_id FK", "title/body", "body_hash", "source_url"]),
        ],
    },
    "词典与基础关系": {
        "color": "#dcfce7",
        "border": "#16a34a",
        "tables": [
            ("t_place", ["place_id PK", "alias/modern", "lon/lat"]),
            ("t_image", ["image_id PK", "word", "category"]),
            ("t_emotion", ["emotion_id PK", "label"]),
            ("t_poem_place", ["poem_id FK", "place_id FK", "freq"]),
            ("t_poem_image", ["poem_id FK", "image_id FK", "freq"]),
        ],
    },
    "时空与生平": {
        "color": "#fef3c7",
        "border": "#d97706",
        "tables": [
            ("t_life_event", ["event_id PK", "poet_id FK", "year range", "event_type"]),
            ("t_journey_stop", ["stop_id PK", "poet_id FK", "event_id FK", "place/lon/lat"]),
            ("t_poem_context", ["context_id PK", "poem_id FK", "creation time/place"]),
        ],
    },
    "语境与证据": {
        "color": "#f3e8ff",
        "border": "#9333ea",
        "tables": [
            ("t_source", ["source_id PK", "source_name", "source_url"]),
            ("t_poem_emotion", ["poem_id FK", "emotion_id FK", "score/evidence"]),
            ("t_image_emotion", ["poem/image/emotion FK", "function_label", "evidence_line"]),
            ("t_claim_evidence", ["claim_id PK", "subject/predicate", "source_id FK"]),
        ],
    },
}

RELATIONS = [
    ("t_poet", "t_poem"),
    ("t_poet", "t_life_event"),
    ("t_poet", "t_journey_stop"),
    ("t_poem", "t_poem_place"),
    ("t_place", "t_poem_place"),
    ("t_poem", "t_poem_image"),
    ("t_image", "t_poem_image"),
    ("t_poem", "t_poem_context"),
    ("t_poem", "t_poem_emotion"),
    ("t_emotion", "t_poem_emotion"),
    ("t_poem", "t_image_emotion"),
    ("t_image", "t_image_emotion"),
    ("t_emotion", "t_image_emotion"),
    ("t_source", "t_life_event"),
    ("t_source", "t_journey_stop"),
    ("t_source", "t_poem_context"),
    ("t_source", "t_claim_evidence"),
]


def draw_table(ax, name: str, fields: list[str], x: float, y: float, color: str, border: str):
    width = 3.25
    height = 0.50 + 0.30 * len(fields)
    box = FancyBboxPatch(
        (x, y - height),
        width,
        height,
        boxstyle="round,pad=0.03,rounding_size=0.08",
        facecolor="white",
        edgecolor=border,
        linewidth=1.35,
        zorder=3,
    )
    ax.add_patch(box)
    header = FancyBboxPatch(
        (x, y - 0.48),
        width,
        0.48,
        boxstyle="round,pad=0.01,rounding_size=0.07",
        facecolor=color,
        edgecolor="none",
        zorder=4,
    )
    ax.add_patch(header)
    ax.text(
        x + 0.15,
        y - 0.24,
        name,
        va="center",
        fontsize=10.5,
        fontweight="bold",
        color=border,
        zorder=5,
    )
    for index, field in enumerate(fields):
        ax.text(
            x + 0.16,
            y - 0.67 - index * 0.30,
            field,
            va="center",
            fontsize=8.2,
            color="#334155",
            zorder=5,
        )
    return (x, y - height, x + width, y)


def center(box):
    return ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)


def anchor(box, target):
    cx, cy = center(box)
    tx, ty = target
    if abs(tx - cx) > abs(ty - cy):
        return (box[2], cy) if tx > cx else (box[0], cy)
    return (cx, box[3]) if ty > cy else (cx, box[1])


def render() -> None:
    fig, ax = plt.subplots(figsize=(18, 12))
    fig.patch.set_facecolor("#f8fafc")
    ax.set_facecolor("#f8fafc")
    ax.set_xlim(0, 18)
    ax.set_ylim(0, 12)
    ax.axis("off")
    ax.text(
        0.6,
        11.55,
        "诗行万里 · 主题版数据库 ER 图",
        fontsize=20,
        fontweight="bold",
        color="#0f172a",
    )
    ax.text(
        0.6,
        11.15,
        "明确分离诗中地点、创作地点、诗人到访地点，并为文学解释绑定来源与证据",
        fontsize=10.5,
        color="#475569",
    )

    x_positions = [0.6, 5.0, 9.4, 13.8]
    boxes: dict[str, tuple[float, float, float, float]] = {}
    for group_index, (group_name, group) in enumerate(GROUPS.items()):
        x = x_positions[group_index]
        ax.text(
            x,
            10.65,
            group_name,
            fontsize=11,
            fontweight="bold",
            color=group["border"],
        )
        y = 10.25
        for name, fields in group["tables"]:
            boxes[name] = draw_table(
                ax,
                name,
                fields,
                x,
                y,
                group["color"],
                group["border"],
            )
            y = boxes[name][1] - 0.30

    for source, target in RELATIONS:
        source_box = boxes[source]
        target_box = boxes[target]
        start = anchor(source_box, center(target_box))
        end = anchor(target_box, center(source_box))
        arrow = FancyArrowPatch(
            start,
            end,
            arrowstyle="-|>",
            mutation_scale=10,
            color="#94a3b8",
            linewidth=0.85,
            connectionstyle="arc3,rad=0.05",
            alpha=0.78,
            zorder=1,
        )
        ax.add_patch(arrow)

    ax.text(
        0.6,
        0.28,
        "PK 主键   FK 外键   MySQL 8.0   旧版 season/sentiment 仅作兼容，不用于主题核心结论",
        fontsize=9,
        color="#64748b",
    )
    png = OUTPUT_DIR / "00_主题数据库ER图.png"
    svg = OUTPUT_DIR / "00_主题数据库ER图.svg"
    plt.savefig(png, dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.savefig(svg, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    print(f"  [ok] saved {png}")
    print(f"  [ok] saved {svg}")


if __name__ == "__main__":
    render()
