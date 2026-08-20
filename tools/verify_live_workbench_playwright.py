# -*- coding: utf-8 -*-
"""线上工作台体检：http://47.114.77.134:3000 —— 目录加载/控制台/诗史问答实测。"""
from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = "http://47.114.77.134:3000/"
SHOT = Path("output/playwright/live_workbench")
ROOT = Path(__file__).resolve().parent.parent
SHOT_DIR = ROOT / SHOT
SHOT_DIR.mkdir(parents=True, exist_ok=True)
CHROMIUM = Path.home() / "AppData" / "Local" / "ms-playwright" / "chromium-1232" / "chrome-win64" / "chrome.exe"


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    with sync_playwright() as pw:
        launch = {"executable_path": str(CHROMIUM)} if CHROMIUM.exists() else {}
        browser = pw.chromium.launch(**launch)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append("PAGEERROR: " + str(e)[:200]))
        page.on("console", lambda m: errors.append("CONSOLE-ERR: " + m.text[:200]) if m.type == "error" else None)

        page.goto(URL, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(9000)

        body = page.locator("body").inner_text()
        loading = "正在建立" in body
        print("[catalog] 加载态残留:", loading)
        print("[catalog] 页面文本样本:", body[:180].replace("\n", " | "))

        # 诗人目录条目数（尝试常见结构）
        for sel in ("select option", "li[data-poet]", "[class*=poet] button", "button[class*=poet]"):
            n = page.locator(sel).count()
            if n:
                print(f"[catalog] 「{sel}」命中 {n} 个")
                break
        page.screenshot(path=str(SHOT_DIR / "01_首页.png"))

        # 打开诗史问答
        try:
            page.click("[aria-label='Open Chat']", timeout=8000)
            page.wait_for_timeout(1500)
            page.fill("[data-testid='copilot-chat-textarea']", "李白在哪些地方写过诗？请简要回答。")
            page.click("[data-testid='copilot-send-button']")
            print("[chat] 已发送问题，等待回答…")
            page.wait_for_timeout(45000)
            chat_text = page.locator(".copilotKitMessages").inner_text()
            print("[chat] 回答片段:", chat_text[-600:].replace("\n", " | "))
            page.screenshot(path=str(SHOT_DIR / "02_问答.png"))
            degraded = ("degraded" in chat_text.lower()) or ("降级" in chat_text) or ("无法" in chat_text and "密钥" in chat_text)
            print("[chat] 疑似降级回复:", degraded)
        except Exception as e:
            print("[chat] 测试失败:", str(e)[:200])

        print("[console] 错误数:", len(errors))
        for e in errors[:6]:
            print("   ", e)
        browser.close()


if __name__ == "__main__":
    main()
