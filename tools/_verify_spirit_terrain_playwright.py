# -*- coding: utf-8 -*-
"""临时验证脚本：Playwright headless 打开 20 号页与 index.html，检查 console/横向溢出/canvas，截图。"""
from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8765"
ROOT = Path(__file__).resolve().parent.parent
SHOT = ROOT / "output" / "playwright" / "spirit_terrain_verify.png"
SHOT.parent.mkdir(parents=True, exist_ok=True)

PAGES = [
    ("20_诗人精神地形图.html", True),   # (path, expect canvas)
    ("index.html", False),
]
VIEWPORTS = [(1440, 900), (390, 844)]


def main() -> int:
    problems: list[str] = []
    with sync_playwright() as p:
        import os

        exe = None
        candidate = os.path.expandvars(
            r"%LOCALAPPDATA%\ms-playwright\chromium-1232\chrome-win64\chrome.exe"
        )
        if os.path.exists(candidate):
            exe = candidate
        browser = p.chromium.launch(executable_path=exe) if exe else p.chromium.launch()
        for path, expect_canvas in PAGES:
            for w, h in VIEWPORTS:
                ctx = browser.new_context(viewport={"width": w, "height": h})
                page = ctx.new_page()
                console_errors: list[str] = []
                page.on(
                    "console",
                    lambda msg, bucket=console_errors: bucket.append(msg.text)
                    if msg.type == "error"
                    else None,
                )
                page.on("pageerror", lambda err, bucket=console_errors: bucket.append(str(err)))
                page.goto(f"{BASE}/{path}", wait_until="networkidle", timeout=60000)
                page.wait_for_timeout(2500)

                overflow = page.evaluate(
                    "() => document.documentElement.scrollWidth - document.documentElement.clientWidth"
                )
                if overflow > 1:
                    problems.append(f"{path} @{w}px horizontal overflow {overflow}px")
                if console_errors:
                    problems.append(f"{path} @{w}px console errors: {console_errors[:5]}")

                if expect_canvas:
                    canvas_info = page.evaluate(
                        """() => {
                            const cs = Array.from(document.querySelectorAll('canvas'));
                            return cs.map(c => {
                                let blank = true;
                                try {
                                    const g = c.getContext('2d');
                                    if (g) {
                                        const d = g.getImageData(0, 0, Math.min(c.width, 400), Math.min(c.height, 400)).data;
                                        for (let i = 3; i < d.length; i += 4) {
                                            if (d[i] !== 0) { blank = false; break; }
                                        }
                                    } else { blank = false; }
                                } catch (e) { blank = false; }
                                return {w: c.width, h: c.height, blank};
                            });
                        }"""
                    )
                    if not canvas_info:
                        problems.append(f"{path} @{w}px no canvas found")
                    elif all(c["blank"] for c in canvas_info):
                        problems.append(f"{path} @{w}px all canvases blank")
                    print(f"  {path} @{w}px canvases: {canvas_info}")

                if path.startswith("20_") and (w, h) == (1440, 900):
                    page.screenshot(path=str(SHOT), full_page=False)
                    print(f"  screenshot saved: {SHOT}")
                print(f"[pass?] {path} @{w}px overflow={overflow} errors={len(console_errors)}")
                ctx.close()
        browser.close()

    if problems:
        print("[FAIL]")
        for x in problems:
            print(" -", x)
        return 1
    print("[ok] all playwright checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
