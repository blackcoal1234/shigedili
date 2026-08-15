"""一键执行主题版：爬虫 -> MySQL -> Python 可视化 -> 离线总入口。"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

THEME_VIZ_SCRIPTS = (
    "viz_00_er_diagram.py",
    "viz_08_poem_browser.py",
    "viz_09_dictionary_browser.py",
    "viz_15_journey_emotion.py",
    "viz_16_literary_centers.py",
    "viz_17_imagery_emotion_compare.py",
    "viz_18_data_quality.py",
    "viz_20_spirit_terrain.py",
    "viz_30_competition_home.py",
    "viz_31_gaze_compass.py",
    "viz_32_dual_map.py",
    "viz_33_year759.py",
    "viz_34_char_fingerprint.py",
    "viz_35_solitude_hyperbole.py",
    "viz_36_age_align.py",
    "viz_37_soundscape.py",
    "viz_38_imagery_tide.py",
    "viz_39_first_person_lives.py",
    # 导航页会检查全部参赛展项目标，因此在 30-39 之后生成。
    "viz_29_competition_index.py",
    # 生命痕迹首页收尾，并按 viz_99 的清单统一刷新 manifest。
    "viz_19_life_trace_app.py",
)

LEGACY_OUTPUTS = (
    "01_诗人足迹.html",
    "02_意象共现.html",
    "03_诗人产出.html",
    "04_流派词云.png",
    "04_词云_豪放派.png",
    "04_词云_婉约派.png",
    "04_词云_山水田园.png",
    "04_词云_边塞派.png",
    "05_情感分布.html",
    "06_总览看板.html",
    "07_四季词摘选.html",
    "10_诗人对比.html",
    "11_流派画像.html",
    "12_市级诗歌地图.html",
    "13_诗词白话翻译.html",
    "14_文本相似与异常发现.html",
)


def step(title: str) -> None:
    print(f"\n==== {title} ====")


def run_python(path: Path, *args: str) -> None:
    subprocess.run([sys.executable, str(path), *args], cwd=ROOT, check=True)


def cleanup_legacy_outputs() -> int:
    output_dir = ROOT / "output"
    removed = 0
    for name in LEGACY_OUTPUTS:
        path = output_dir / name
        if path.exists():
            path.unlink()
            removed += 1
    return removed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recrawl", action="store_true", help="强制重新抓取全部种子诗人")
    parser.add_argument("--no-crawl", action="store_true", help="直接使用 data/poems.json")
    parser.add_argument("--reset-db", action="store_true", help="删除并重建项目数据库表")
    parser.add_argument(
        "--skip-db",
        action="store_true",
        help="不连接 MySQL；新主题页面和证据工具从 JSON/CSV 离线生成",
    )
    parser.add_argument(
        "--keep-legacy-output",
        action="store_true",
        help="保留旧版生成文件，但旧页面仍不会进入新版总入口",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    poems_json = ROOT / "data" / "poems.json"

    step("Step 1/4  Python 爬虫")
    if args.no_crawl or (poems_json.exists() and not args.recrawl):
        print(f"  [skip] 使用已有语料：{poems_json}")
    else:
        run_python(ROOT / "爬虫脚本" / "spider_gushiwen.py")

    step("Step 2/4  MySQL 主题数据")
    if args.skip_db:
        print("  [skip] 离线构建模式，不连接 MySQL")
    else:
        db_args = ("--reset",) if args.reset_db else ()
        run_python(ROOT / "数据库操作脚本及数据库SQL" / "db_init.py", *db_args)

    step("Step 3/4  清理非主题输出")
    if args.keep_legacy_output:
        print("  [skip] 按参数保留旧输出")
    else:
        removed = cleanup_legacy_outputs()
        print(f"  [ok] 移除 {removed} 个旧版输出")

    step("Step 4/4  Python 主题可视化")
    viz_dir = ROOT / "数据可视化脚本"
    for script_name in THEME_VIZ_SCRIPTS:
        path = viz_dir / script_name
        if not path.exists():
            raise FileNotFoundError(f"缺少主题脚本：{path}")
        print(f"\n[viz] {script_name}")
        run_python(path)

    step("OK 主题版已生成")
    print(f"  总入口：{ROOT / 'output' / 'index.html'}")
    print("  本地展示：python tools/serve_output.py")


if __name__ == "__main__":
    main()
