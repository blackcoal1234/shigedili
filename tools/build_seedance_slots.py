# -*- coding: utf-8 -*-
"""Seedance 开卷视频槽位：章节开卷卡的数据底座 + 生成清单。

作用：
  1. 把《诗行万里》四章（山河证道）与 Seedance 精选场景一一对位，
     prompt 全文来自项目四轮场景抽签文档（本工具内嵌，仓库自含）；
  2. 扫描 output/assets/seedance/ 下已生成的视频（ch1.mp4…ch4.mp4，
     可选 ch1_poster.jpg 首帧），写出 output/assets/competition/chapter_intros.json；
     viz_40 构建时读取——有视频则开卷卡播视频，无则降级为水墨底开卷卡
     （章印 + 主题句 + 场景占位说明），保证零资产也可运行；
  3. 同步生成 docs/Seedance_开卷视频生成清单.md：待生成清单、命名约定、接入步骤。

命名约定：output/assets/seedance/ch{n}.mp4（n=章序），首帧 ch{n}_poster.jpg。
生成后重跑本工具 + 数据可视化脚本/viz_40_shanhe_quest.py 即自动接入。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEEDANCE_DIR = ROOT / "output" / "assets" / "seedance"
OUT_JSON = ROOT / "output" / "assets" / "competition" / "chapter_intros.json"
OUT_DOC = ROOT / "docs" / "Seedance_开卷视频生成清单.md"

# 章节对位（scene prompt 内嵌自 Seedance_场景抽签_*.md，第三/二/一轮）
CHAPTER_SCENES = [
    {
        "chapter_id": "ch1", "chapter": "两京·朔方", "n": 1,
        "scene": "S25", "scene_name": "长安旧梦·夜郎江影",
        "poem_line": "昔在长安醉花柳，五侯七贵同杯酒。",
        "why": "现实（流放江夜）与旧梦（长安繁华）双层叠影，正对「都城气象与北地风霜」的今昔命题。",
        "prompt": (
            "8秒，16:9，单镜头无缝循环，古雅水墨淡彩，宣纸纤维与墨色晕染清晰。"
            "流放江夜为现实底层：冷青江水、孤舟残影、远山细雨；长安旧梦以暖金叠影浮现："
            "花柳、章台飞檐、酒杯流光、骏马疾驰留下的金鞭弧光，人物仅为模糊墨迹与衣袂残影，"
            "无清晰面孔。画面右侧35%始终留作HTML诗句净区，仅保留淡宣纸纹理。"
            "0–1秒冷月映江，墨波轻荡；1–2秒水中暖金灯影渗出；2–3秒花柳与楼阁叠现；"
            "3–4秒数只酒杯光影相碰；4–5秒少年红衣色痕掠过；5–6秒马蹄墨点与金鞭弧光横穿旧梦；"
            "6–7秒繁华被江风吹散；7–8秒暖影沉回水中，月、波纹及墨晕复归首帧。"
            "镜头仅缓慢呼吸漂移，无切换。禁止清晰人物、五官、现代物件、文字、题字、字幕、"
            "印章、Logo、水印、边框、写实3D、霓虹、高饱和、镜头跳切、闪烁、突变、净区侵入。"
        ),
    },
    {
        "chapter_id": "ch2", "chapter": "巴蜀", "n": 2,
        "scene": "S14", "scene_name": "彩云白帝·轻舟万山",
        "poem_line": "朝辞白帝彩云间，千里江陵一日还。",
        "why": "白帝城—夔门即本章题眼《早发白帝城》，轻舟万山直接对应蜀道与峡江地理。",
        "prompt": (
            "16:9，8秒，单镜头，低饱和宣纸水墨。清晨夔州白帝城隐在左上彩云与峭壁间，"
            "长江自万重青灰峡山中纵深展开；右侧约35%保持淡宣纸稳定留白，供HTML诗句叠加，"
            "全程无物体穿越。0–1秒薄雾横过江面；1–2秒一叶无清晰人物的墨色轻舟入画；"
            "2–3秒水纹与两岸山影向后流动；3–4秒轻舟穿过峡口，远山层层展开；4–5秒林梢轻颤，"
            "以墨点涟漪暗示猿啼；5–6秒舟行加速，飞白水痕增强速度感；6–7秒群山快速叠退，"
            "镜头仍平稳滑行、无晃动；7–8秒薄雾覆舟，水墨晕染回到首帧雾形与构图，首尾无缝循环。"
            "无清晰人物、文字、题字、印章、Logo、水印；避免镜头抖动、骤变、过饱和、写实塑料感。"
        ),
    },
    {
        "chapter_id": "ch3", "chapter": "江南", "n": 3,
        "scene": "S09", "scene_name": "西湖晴雨·淡妆浓抹",
        "poem_line": "水光潋滟晴方好，山色空蒙雨亦奇。",
        "why": "《饮湖上初晴后雨》在本章题内，晴雨两态即「烟雨水乡的另一极」。",
        "prompt": (
            "16:9诗词网页动态背景，8秒，单镜头固定机位，宋代水墨淡彩绘于温润宣纸。"
            "西湖横展，左下近岸以浅墨勾勒荷叶与石岸，远山层叠隐入烟水；中央偏右保留45%均匀浅色"
            "雾面留白，供HTML诗句稳定叠加，全程无物体穿越。0–1秒：晴光柔和，湖面细碎银青波纹"
            "缓慢潋滟；1–2秒：淡云舒卷，极细斜雨自然落下，整体曝光不变；2–4秒：雨雾漫过远山，"
            "青灰墨色湿润晕染，山形空蒙若隐；4–6秒：雨丝渐止，近岸墨色稍浓，湖面映出淡赭与柔青，"
            "呈「淡妆浓抹」；6–8秒：雾气徐退，水光恢复首帧状态，云、波纹与墨晕无缝回环。"
            "运动舒缓、克制、诗意，纸纹稳定，光线连续无闪烁。禁止人物、船只、建筑特写、飞鸟、"
            "文字、书法、印章、标志、水印；禁止镜头切换、推拉摇移、强光斑、骤变天气、高对比、"
            "画面抖动、元素变形、噪点闪烁。"
        ),
    },
    {
        "chapter_id": "ch4", "chapter": "荆楚·江右", "n": 4,
        "scene": "S31", "scene_name": "雪泥鸿爪",
        "poem_line": "人生到处知何似，应似飞鸿踏雪泥。",
        "why": "「雪泥鸿爪」作于本章黄州贬所脉络（渑池怀旧题脉），偶然留痕正对贬谪者的江湖。",
        "prompt": (
            "16:9，8秒，单镜头无缝循环，水墨宣纸质感，无人物。雪后浅泥横陈，墨色飞鸿掠过，"
            "仅投下淡影与偶然爪痕；右上保留35%低纹理HTML净区。0–1秒薄雪静覆；1–2秒微风卷雪；"
            "2–3秒鸿影入画；3–4秒轻踏留爪；4–5秒振翅离地；5–6秒鸿影远逝；6–7秒新雪淡覆痕迹；"
            "7–8秒风雪复原首帧。镜头固定，留白克制，墨晕细腻。禁止人物、文字、题字、印章、Logo、"
            "水印、边框；禁止卡通、艳色、现代物件、镜头切换、抖动、闪烁、突变、鸟形畸变。"
        ),
    },
]


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    SEEDANCE_DIR.mkdir(parents=True, exist_ok=True)
    slots = []
    ready = 0
    for scene in CHAPTER_SCENES:
        n = scene["n"]
        video_path = SEEDANCE_DIR / f"ch{n}.mp4"
        poster_path = SEEDANCE_DIR / f"ch{n}_poster.jpg"
        has_video = video_path.exists() and video_path.stat().st_size > 1024
        has_poster = poster_path.exists() and poster_path.stat().st_size > 1024
        ready += int(has_video)
        slots.append(
            {
                "chapter_id": scene["chapter_id"],
                "chapter": scene["chapter"],
                "scene": scene["scene"],
                "scene_name": scene["scene_name"],
                "poem_line": scene["poem_line"],
                "video": f"assets/seedance/ch{n}.mp4" if has_video else None,
                "poster": f"assets/seedance/ch{n}_poster.jpg" if has_poster else None,
            }
        )

    data = {
        "meta": {
            "n_slots": len(slots),
            "n_videos_ready": ready,
            "policy": (
                "开卷卡优先播放已生成视频；无视频时降级为水墨底开卷卡（章印+主题句+场景占位说明），"
                "保证零资产可运行。视频命名 ch{n}.mp4 / 首帧 ch{n}_poster.jpg，"
                "放入 output/assets/seedance/ 后重跑本工具与 viz_40 自动接入。"
            ),
            "generated_by": "tools/build_seedance_slots.py",
        },
        "slots": slots,
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"), allow_nan=False)

    # ---- 生成清单文档 ----
    lines = [
        "# Seedance 开卷视频生成清单",
        "",
        "> 由 tools/build_seedance_slots.py 生成；四章对位与 prompt 全文内嵌于该脚本。",
        "> 视频就位后重跑 `python tools/build_seedance_slots.py && python 数据可视化脚本/viz_40_shanhe_quest.py` 即自动接入。",
        ">",
        "> **一键生成**：设好 `ARK_API_KEY`（火山方舟控制台创建）后运行",
        "> `python tools/generate_seedance_videos.py --only 2`（先试巴蜀一支），满意后去掉 --only 生成全部。",
        "> 模型默认 doubao-seedance-1-0-lite-t2v（可用 --model 换 pro / Seedance 2.x）。",
        "",
        "## 一、章节开卷（山河证道 viz_40）——优先级最高",
        "",
        "| 章 | 场景 | 目标文件 | 状态 | 对位理由 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for scene, slot in zip(CHAPTER_SCENES, slots):
        status = "✅ 已就位" if slot["video"] else "⬜ 待生成"
        lines.append(
            f"| {scene['chapter']} | {scene['scene']}《{scene['scene_name']}》 | "
            f"assets/seedance/ch{scene['n']}.mp4 | {status} | {scene['why']} |"
        )
    lines += ["", "### Prompt 全文（逐字复制生成）", ""]
    for scene in CHAPTER_SCENES:
        lines += [
            f"#### ch{scene['n']} · {scene['chapter']} · {scene['scene']}《{scene['scene_name']}》",
            "",
            f"适配诗句：{scene['poem_line']}",
            "",
            "```text",
            scene["prompt"],
            "```",
            "",
        ]
    lines += [
        "## 二、页面级精选（其余 13 支）",
        "",
        "按《Seedance_项目页面适配精选》的优先级执行（主视觉骨架 6 支 → 专题匹配 6 支 → 联动底图 5 支），",
        "本清单不重复收录 prompt，见项目根目录《Seedance_项目页面适配精选.md》。",
        "",
        "## 三、验收要点",
        "",
        "- 无缝循环、首尾同帧；留白区（约 35-45%）亮度纹理稳定，供诗句叠加；",
        "- 不遮挡地图、图表与证据卡；无文字、题字、印章、水印；",
        "- 单支不达标即降级为静态首帧 + CSS 缓动，不阻塞发布。",
        "",
    ]
    OUT_DOC.write_text("\n".join(lines), encoding="utf-8")

    print("OK  ->", OUT_JSON)
    print("OK  ->", OUT_DOC)
    print(f"开卷槽位 {len(slots)} | 视频就位 {ready}/{len(slots)}（无视频时开卷卡自动降级为水墨底）")


if __name__ == "__main__":
    main()
