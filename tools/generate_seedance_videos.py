# -*- coding: utf-8 -*-
"""Seedance 开卷视频生成器：调火山方舟 API 生成四章开卷动画并落入槽位目录。

用法（三步）：
  1) 注册火山引擎 https://www.volcengine.com → 实名认证 → 开通「火山方舟」
     （控制台内按引导开通 Doubao/Seedance 模型服务并充值，视频按秒计费）；
  2) 火山方舟控制台「API Key 管理」创建密钥（volc- 开头），设环境变量：
       Windows(Git Bash):  export ARK_API_KEY=volc-xxxxxxxx
       Windows(PowerShell): $env:ARK_API_KEY="volc-xxxxxxxx"
  3) 运行本脚本：
       python tools/generate_seedance_videos.py --only 2      # 先试巴蜀(S14)一支
       python tools/generate_seedance_videos.py               # 生成全部缺失章
     生成后自动落位 output/assets/seedance/ch{n}.mp4，再跑：
       python tools/build_seedance_slots.py
       python 数据可视化脚本/viz_40_shanhe_quest.py
     开卷卡即从水墨底升级为视频（无需改任何代码）。

接口（火山方舟内容生成任务，详见官方文档 82379/1520757）：
  POST https://ark.cn-beijing.volces.com/api/v3/contents/generations/tasks
  GET  .../tasks/{id}   → status=succeeded 后取 content.video_url（有时效，立即下载）

模型：默认 doubao-seedance-1-0-lite-t2v-250428（文生视频，便宜快速）；
     可用 --model 换 pro 或控制台里更新的 Seedance 2.x 型号。
参数：prompt 尾部追加 --resolution/--duration/--ratio/--fps 指令；
     本项目开卷设计为 8 秒 16:9 无缝循环，故默认 --duration 8 --ratio 16:9。
"""
from __future__ import annotations

import argparse
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from build_seedance_slots import CHAPTER_SCENES  # noqa: E402  prompt 全文内嵌于此

OUT_DIR = ROOT / "output" / "assets" / "seedance"
API_TASKS = "https://ark.cn-beijing.volces.com/api/v3/contents/generations/tasks"

DEFAULT_MODEL = "doubao-seedance-1-0-lite-t2v-250428"
DEFAULT_PARAMS = "--ratio 16:9 --duration 8 --fps 24 --resolution 720p"
POLL_INTERVAL = 10
MAX_WAIT_S = 900


def request_json(url: str, api_key: str, method: str = "GET", body: dict | None = None) -> dict:
    data = None
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    if body is not None:
        import json as _json
        data = _json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=60) as r:
        import json as _json
        return _json.loads(r.read().decode("utf-8"))


def download(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "shixing-wanli/1.0"})
    with urllib.request.urlopen(req, timeout=120) as r, open(dest, "wb") as f:
        while True:
            chunk = r.read(1 << 16)
            if not chunk:
                break
            f.write(chunk)


def generate_one(scene: dict, api_key: str, model: str, params: str) -> Path | None:
    n = scene["n"]
    dest = OUT_DIR / f"ch{n}.mp4"
    if dest.exists() and dest.stat().st_size > 1024:
        print(f"[skip] ch{n} 已存在（{dest.stat().st_size} bytes）")
        return dest
    prompt = scene["prompt"] + " " + params
    body = {"model": model, "content": [{"type": "text", "text": prompt}]}
    print(f"[task] ch{n} 《{scene['scene_name']}》 模型 {model}")
    resp = request_json(API_TASKS, api_key, "POST", body)
    task_id = resp.get("id")
    if not task_id:
        print(f"[fail] 创建任务失败：{resp}")
        return None
    print(f"[poll] 任务 {task_id}")
    waited = 0
    while waited < MAX_WAIT_S:
        time.sleep(POLL_INTERVAL)
        waited += POLL_INTERVAL
        try:
            st = request_json(f"{API_TASKS}/{task_id}", api_key)
        except Exception as e:
            print(f"  [warn] 查询失败重试：{e}")
            continue
        status = st.get("status")
        if status == "succeeded":
            video_url = None
            content = st.get("content") or {}
            video_url = content.get("video_url")
            if not video_url:
                for item in content.get("parts", []) if isinstance(content, dict) else []:
                    video_url = (item or {}).get("video_url") or video_url
            if not video_url:
                print(f"[fail] 任务成功但未取到 video_url：{st}")
                return None
            OUT_DIR.mkdir(parents=True, exist_ok=True)
            download(video_url, dest)
            print(f"[done] ch{n} -> {dest} ({dest.stat().st_size} bytes)")
            return dest
        if status in ("failed", "cancelled"):
            print(f"[fail] 任务 {status}：{st.get('error') or st}")
            return None
        print(f"  … {status or 'running'}（{waited}s）")
    print(f"[fail] ch{n} 超时（{MAX_WAIT_S}s）")
    return None


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--api-key", default=None, help="火山方舟 API Key（缺省读环境变量 ARK_API_KEY）")
    ap.add_argument("--model", default=DEFAULT_MODEL, help=f"模型 ID（默认 {DEFAULT_MODEL}）")
    ap.add_argument("--params", default=DEFAULT_PARAMS, help="生成参数指令串")
    ap.add_argument("--only", type=int, choices=[1, 2, 3, 4], help="只生成指定章（1两京 2巴蜀 3江南 4荆楚）")
    args = ap.parse_args()

    import os
    api_key = args.api_key or os.environ.get("ARK_API_KEY", "")
    if not api_key:
        raise SystemExit(
            "[failed] 缺少 API Key：在火山方舟控制台创建后，设环境变量 ARK_API_KEY，"
            "或用 --api-key 传入。"
        )

    targets = [s for s in CHAPTER_SCENES if args.only is None or s["n"] == args.only]
    done = 0
    for scene in targets:
        if generate_one(scene, api_key, args.model, args.params):
            done += 1
    print(f"\n完成 {done}/{len(targets)}。下一步：")
    print("  python tools/build_seedance_slots.py")
    print("  python 数据可视化脚本/viz_40_shanhe_quest.py")


if __name__ == "__main__":
    main()
