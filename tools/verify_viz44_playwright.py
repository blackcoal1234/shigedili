# -*- coding: utf-8 -*-
"""viz_44 赏析诗页 · Playwright 验收：深链路由、分层徽章、在线译注、
导读卡诚实徽章、意象高亮、诗签收藏、筛选与上一首/下一首、控制台零错误。"""
from __future__ import annotations

import json
import sys
from contextlib import contextmanager
from pathlib import Path
from threading import Thread
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright
from serve_output import create_server, server_url

ROOT = Path(__file__).resolve().parent.parent
PAGE_URL = (ROOT / "output" / "44_诗页.html").as_uri()
SHOT_DIR = ROOT / "output" / "playwright" / "viz44"
SHOT_DIR.mkdir(parents=True, exist_ok=True)
CHROMIUM = Path.home() / "AppData" / "Local" / "ms-playwright" / "chromium-1232" / "chrome-win64" / "chrome.exe"

CHECKS: list[str] = []
RICH_API_URL = "http://127.0.0.1:8123/knowledge/rich-guide"
EXPECTED_503_CONSOLE = "Failed to load resource: the server responded with a status of 503 (Service Unavailable)"


def ok(msg: str) -> None:
    CHECKS.append(msg)
    print("  [ok]", msg)


@contextmanager
def temporary_output_server():
    server = create_server("127.0.0.1", 0, ROOT / "output")
    thread = Thread(target=server.serve_forever, name="viz44-static-http", daemon=True)
    thread.start()
    try:
        yield server_url(server, "44_诗页.html")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        if thread.is_alive():
            raise RuntimeError("viz44 临时静态 HTTP server 未停止")


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    with temporary_output_server() as http_page_url, sync_playwright() as pw:
        parsed_page_url = urlsplit(http_page_url)
        http_origin = f"{parsed_page_url.scheme}://{parsed_page_url.netloc}"
        launch_kwargs = {"executable_path": str(CHROMIUM)} if CHROMIUM.exists() else {}
        browser = pw.chromium.launch(**launch_kwargs)
        page = browser.new_page(viewport={"width": 1180, "height": 900})
        page_errors: list[str] = []
        console_errors: list[str] = []
        unexpected_http_requests: list[str] = []
        unexpected_http_failures: list[str] = []
        api_responses: list[tuple[int, str]] = []
        rich_api = {"mode": "unavailable", "poem_ids": [], "methods": [], "origins": []}

        def record_console(message) -> None:
            if message.type == "error":
                console_errors.append(message.text)

        def record_response(response) -> None:
            if response.url == RICH_API_URL:
                api_responses.append(
                    (response.status, response.headers.get("access-control-allow-origin", ""))
                )
            elif response.status >= 400 and response.url.startswith(("http://", "https://")):
                unexpected_http_failures.append(f"{response.status} {response.url}")

        page.on("pageerror", lambda e: page_errors.append(str(e)))
        page.on("console", record_console)
        page.on("response", record_response)

        def guard_and_fulfill(route) -> None:
            request = route.request
            if not request.url.startswith(("http://", "https://")):
                route.continue_()
                return
            if request.url.startswith(http_origin + "/"):
                route.continue_()
                return
            if request.url != RICH_API_URL:
                unexpected_http_requests.append(request.url)
                route.abort("blockedbyclient")
                return

            rich_api["methods"].append(request.method)
            rich_api["origins"].append(request.headers.get("origin"))
            cors_headers = {
                "Access-Control-Allow-Origin": http_origin,
                "Access-Control-Allow-Headers": "Content-Type",
                "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                "Vary": "Origin",
            }
            if request.method == "OPTIONS":
                route.fulfill(status=204, headers=cors_headers, body="")
                return
            assert request.method == "POST", f"rich-guide 请求方法异常：{request.method}"
            payload = request.post_data_json
            poem_id = payload.get("poem_id") if isinstance(payload, dict) else None
            rich_api["poem_ids"].append(poem_id)
            if rich_api["mode"] == "unavailable":
                route.fulfill(
                    status=503,
                    headers={**cors_headers, "Content-Type": "application/json"},
                    body=json.dumps({"status": "unavailable", "reason": "missing_env"}),
                )
                return
            if rich_api["mode"] == "knowledge_missing":
                route.fulfill(
                    status=503,
                    headers={**cors_headers, "Content-Type": "application/json"},
                    body=json.dumps(
                        {"status": "unavailable", "reason": "knowledge_base_missing"}
                    ),
                )
                return
            is_hand = rich_api["mode"] == "hand"
            route.fulfill(
                status=200,
                headers={**cors_headers, "Content-Type": "application/json"},
                body=json.dumps(
                    {
                        "status": "exists" if is_hand else "generated",
                        "source": "hand" if is_hand else "llm",
                        "batch": "batch_browser_hand_007" if is_hand else "batch_browser_llm_008",
                        "item": {
                            "poem_id": poem_id,
                            "story": "浏览器验收：手写译注已即时载入。" if is_hand else "浏览器验收：模型译注已即时载入。",
                            "notes": [
                                {
                                    "original": "浏览器验收原句",
                                    "translation": "浏览器验收译文",
                                    "annotations": ["浏览器验收注释"],
                                }
                            ],
                            "ap": ["浏览器验收赏析要点"],
                            "hw": is_hand,
                        },
                    },
                    ensure_ascii=False,
                ),
            )

        page.route("**/*", guard_and_fulfill)

        # 1. 默认进入：统计头 + 默认诗渲染
        page.goto(PAGE_URL, wait_until="load")
        page.wait_for_timeout(1200)
        stats = page.locator("#stats").inner_text()
        meta = page.evaluate("window.POEM_PAGE_DATA.meta")
        expected_poems = f"{meta['poems']:,}"
        expected_rich = str(meta.get("assistant_rich", 0))
        expected_llm = str(meta.get("rich_llm", 0))
        assert expected_poems in stats and "导读卡" in stats, f"统计头异常：{stats[:60]}"
        assert f"译注赏析 {expected_rich}" in stats and f"模型 {expected_llm}" in stats, (
            f"预生成统计异常：{stats}"
        )
        assert page.locator("h2.ptitle").count() == 1, "默认诗未渲染"
        ok(f"默认进入渲染：{stats[:52]}…")

        # 2. 核验层深链：早发白帝城（人工核验 A/B + 审核背景 + 证据来源）
        page.goto(PAGE_URL + "#poem=0f81015a040c", wait_until="load")
        page.wait_for_timeout(600)
        assert "早发白帝城" in page.locator("h2.ptitle").inner_text(), "核验层深链失败"
        badges = page.locator(".tier").all_inner_texts()
        assert any("人工核验" in b for b in badges), f"缺人工核验徽章：{badges}"
        assert page.locator('h3:has-text("审核创作背景")').count() >= 1, "核验层应有审核创作背景区"
        assert page.locator(".src").count() >= 1, "核验层应有证据来源"
        page.screenshot(path=str(SHOT_DIR / "01_核验层_早发白帝城.png"))
        ok("深链 #poem= → 人工核验 A/B 徽章 + 审核背景 + 证据来源")

        # 2.5 助手续写层：译注赏析（早发白帝城属 batch_001）
        ag_heads = page.locator('h3:has-text("助手续写")')
        assert ag_heads.count() == 1, "缺少助手续写区"
        ag_badge = page.locator(".ag .honesty").inner_text()
        assert "助手撰写" in ag_badge and "非人工考据" in ag_badge, f"助手续写徽章异常：{ag_badge}"
        lnotes = page.locator(".ag .lnote").count()
        assert lnotes >= 2, f"助手续写逐句条目不足：{lnotes}"
        assert page.locator(".ag .la").count() >= 2, "助手续写注释不足"
        assert "batch_001" in page.locator(".ag-note").inner_text(), "助手续写缺批次标注"
        page.screenshot(path=str(SHOT_DIR / "04_助手续写_译注赏析.png"))
        ok(f"助手续写·译注赏析：徽章 + 逐句 {lnotes} 组 + 批次标注")

        # 2.6 静态 LLM 层：预生成批次已接入数据资产，标题与徽章不得冒充手写
        page.goto(PAGE_URL + "#poem=63d3ff8f6b61", wait_until="load")
        page.wait_for_timeout(600)
        assert "宿建德江" in page.locator("h2.ptitle").inner_text(), "LLM 预生成深链失败"
        assert "AI 预生成 · 译注赏析" in page.locator("section:has(.ag) h3").inner_text(), "LLM 静态标题错误"
        assert "模型生成 · 非人工考据" in page.locator(".ag .honesty").inner_text(), "LLM 静态徽章错误"
        assert page.locator(".ag .lnote").count() >= 2, "LLM 静态逐句条目不足"
        assert "batch_auto_001" in page.locator(".ag-note").inner_text(), "LLM 静态批次错误"
        page.locator("section:has(.ag)").screenshot(
            path=str(SHOT_DIR / "07_AI预生成_宿建德江.png")
        )
        ok("AI 预生成静态接入：独立标题 + 模型徽章 + 批次与逐句内容")

        # 3. 规则晋级层：虚线推定徽章、无审核背景、意象高亮
        page.goto(PAGE_URL + "#poem=0798fb9e75a7", wait_until="load")
        page.wait_for_timeout(600)
        badges = page.locator(".tier").all_inner_texts()
        assert any("规则晋级" in b for b in badges), f"缺规则晋级徽章：{badges}"
        tier_cls = page.locator(".tier").first.get_attribute("class") or ""
        assert "rule" in tier_cls, f"规则层应为虚线样式：{tier_cls}"
        assert page.locator('h3:has-text("审核创作背景")').count() == 0, "规则层不应有审核背景"
        marks = page.locator("mark.im").count()
        assert marks > 0, "意象高亮缺失"
        page.screenshot(path=str(SHOT_DIR / "02_规则层_意象高亮.png"))
        ok(f"规则晋级「推定」虚线徽章 + 无审核背景 + 意象高亮 {marks} 处")

        # 4. 导读卡诚实徽章：按数据实际的 provenance（助手撰写 / 模型生成）显示，一律带非人工考据
        page.goto(PAGE_URL + "#poem=11ad2a984cb5", wait_until="load")
        page.wait_for_timeout(500)
        badge = page.locator(".honesty").first.inner_text()
        hw = page.evaluate("window.POEM_PAGE_DATA.poems.find(function(p){return p.id==='11ad2a984cb5';}).gd.hw")
        expect_badge = "助手撰写" if hw else "模型生成"
        assert expect_badge in badge and "非人工考据" in badge, f"导读卡徽章与 provenance 不符：{badge} (hw={hw})"
        page.goto(PAGE_URL + "#poem=07b77cd35cf3", wait_until="load")
        page.wait_for_timeout(500)
        badge = page.locator(".honesty").first.inner_text()
        assert "非人工考据" in badge, f"导读卡徽章异常：{badge}"
        dims = page.locator(".chip").count()
        assert dims >= 3, f"维度 chips 过少：{dims}"
        page.screenshot(path=str(SHOT_DIR / "03_助手导读卡_维度.png"))
        ok("导读卡诚实徽章（模型生成 / 助手撰写 · 非人工考据）+ 文本维度 chips")

        # 5. 诗签收藏：星标 → localStorage → 只看诗签
        page.click("#starBtn")
        page.wait_for_timeout(300)
        favs = page.evaluate("JSON.parse(localStorage.getItem('poemPageFavs') || '[]')")
        assert "07b77cd35cf3" in favs, f"诗签未写入 localStorage：{favs}"
        assert "已入诗签" in page.locator("#starBtn").inner_text(), "星标状态未刷新"
        page.check("#favOnly")
        page.wait_for_timeout(400)
        cnt = page.locator(".pitem").count()
        assert cnt == 1, f"只看诗签应为 1 首，实际 {cnt}"
        ok("收藏诗签写入本机 localStorage，「只看诗签」过滤生效")
        page.uncheck("#favOnly")
        page.wait_for_timeout(300)

        # 6. 搜索与诗人筛选
        page.fill("#search", "白帝城")
        page.wait_for_timeout(500)
        listed = page.locator(".pitem").count()
        assert 1 <= listed <= 80, f"搜索结果异常：{listed}"
        page.fill("#search", "")
        page.wait_for_timeout(300)
        page.goto(PAGE_URL + "#poet=李白", wait_until="load")
        page.wait_for_timeout(600)
        metas = page.locator(".pitem .pm").all_inner_texts()
        assert metas and all(m.startswith("李白") for m in metas[:5]), f"诗人深链异常：{metas[:3]}"
        ok(f"关键词过滤 {listed} 首；#poet= 深链列表全部为该诗人")

        # 7. 上一首 / 下一首
        page.click("#nextBtn")
        page.wait_for_timeout(400)
        assert "#poem=" in page.url, "下一首未切换 hash"
        title1 = page.locator("h2.ptitle").inner_text()
        page.click("#prevBtn")
        page.wait_for_timeout(400)
        title2 = page.locator("h2.ptitle").inner_text()
        assert title1 != title2, "上一首/下一首未换诗"
        ok("上一首 / 下一首在当前列表内切换")

        no_ag_ids = page.evaluate(
            "window.POEM_PAGE_DATA.poems.filter(function(p){return !p.ag;}).slice(0, 2).map(function(p){return p.id;})"
        )
        assert len(no_ag_ids) >= 2, f"在线译注验收至少需要两首无 ag 诗，实际 {len(no_ag_ids)}"
        page.goto(PAGE_URL + "#poem=" + no_ag_ids[0], wait_until="load")
        page.click("#genBtn")
        offline_note = page.locator("#genNote").inner_text()
        assert "file://" in offline_note and "serve_output.py" in offline_note, f"file:// 指引不明确：{offline_note}"
        assert not rich_api["methods"], f"file:// 不应发起 rich-guide 请求：{rich_api['methods']}"
        assert not page_errors and not console_errors, f"file:// 控制台错误：{(page_errors + console_errors)[:3]}"
        assert not unexpected_http_requests, f"file:// 出现外部 HTTP(S) 请求：{unexpected_http_requests[:3]}"
        ok("控制台零错误")

        # 8. 在线章节：必须从临时 HTTP origin 打开，精确 CORS；不允许 Origin=null 或外部网络
        page.goto(http_page_url, wait_until="load")
        page.wait_for_timeout(400)
        no_ag_id, llm_id = no_ag_ids
        page.goto(http_page_url + "#poem=" + no_ag_id, wait_until="load")
        no_ag_title = page.locator("h2.ptitle").inner_text()
        page.click("#genBtn")
        note = page.locator("#genNote")
        note.wait_for(state="visible")
        assert "未配置密钥" in note.inner_text() and "生成不可用" in note.inner_text(), f"503 降级提示不明确：{note.inner_text()}"
        assert page.locator("h2.ptitle").inner_text() == no_ag_title, "503 后当前诗页未继续渲染"
        assert page.locator("#poemBody").count() == 1, "503 后原诗区域消失"
        assert page.locator("#genBtn").is_enabled(), "503 后在线生成按钮未恢复可点击"
        page.screenshot(path=str(SHOT_DIR / "05_在线译注_503降级.png"))
        ok("HTTP 在线译注 503 missing_env：明确降级提示 + 页面保留 + 按钮恢复")

        rich_api["mode"] = "knowledge_missing"
        page.click("#genBtn")
        assert "尚未构建诗词知识库" in note.inner_text(), (
            f"knowledge_base_missing 提示失真：{note.inner_text()}"
        )
        assert page.locator("h2.ptitle").inner_text() == no_ag_title, "知识库缺失后当前诗页未继续渲染"
        assert page.locator("#genBtn").is_enabled(), "知识库缺失后在线生成按钮未恢复"
        ok("HTTP 在线译注 503 knowledge_base_missing：准确提示 + 页面保留")

        rich_api["mode"] = "hand"
        page.click("#genBtn")
        page.locator(".ag .honesty").wait_for(state="visible")
        assert rich_api["poem_ids"] == [no_ag_id, no_ag_id, no_ag_id], f"POST poem_id 不正确：{rich_api['poem_ids']}"
        assert "浏览器验收：手写译注已即时载入。" in page.locator(".ag").inner_text(), "existing hand 未当场渲染"
        assert "助手撰写 · 非人工考据" in page.locator(".ag .honesty").inner_text(), "hand provenance 徽章错误"
        assert "助手续写 · 译注赏析" in page.locator("section:has(.ag) h3").inner_text(), "hand 标题错误"
        assert "batch_browser_hand_007" in page.locator(".ag-note").inner_text(), "未保留 hand 真实 batch"
        page.screenshot(path=str(SHOT_DIR / "06_在线译注_existing_hand.png"))

        rich_api["mode"] = "llm"
        page.goto(http_page_url + "#poem=" + llm_id, wait_until="load")
        page.click("#genBtn")
        page.locator(".ag .honesty").wait_for(state="visible")
        assert rich_api["poem_ids"][-1] == llm_id, f"generated llm poem_id 不正确：{rich_api['poem_ids'][-1]}"
        assert "模型生成 · 非人工考据" in page.locator(".ag .honesty").inner_text(), "llm provenance 徽章错误"
        assert "AI 预生成 · 译注赏析" in page.locator("section:has(.ag) h3").inner_text(), "llm 标题错误"
        assert "batch_browser_llm_008" in page.locator(".ag-note").inner_text(), "未保留 llm 真实 batch"

        expected_503_responses = [item for item in api_responses if item[0] == 503]
        expected_503_console = [text for text in console_errors if text == EXPECTED_503_CONSOLE]
        other_console_errors = [text for text in console_errors if text != EXPECTED_503_CONSOLE]
        assert len(expected_503_responses) == 2, f"rich-guide 503 响应记录异常：{api_responses}"
        assert len(expected_503_console) <= len(expected_503_responses), f"未绑定的 503 控制台诊断：{expected_503_console}"
        assert not other_console_errors and not page_errors, f"在线章节控制台错误：{(page_errors + other_console_errors)[:3]}"
        assert not unexpected_http_failures, f"出现其他 HTTP 失败：{unexpected_http_failures[:3]}"
        assert not unexpected_http_requests, f"出现外部 HTTP(S) 请求：{unexpected_http_requests[:3]}"
        assert rich_api["origins"] and all(origin == http_origin for origin in rich_api["origins"]), f"rich-guide Origin 不正确：{rich_api['origins']}"
        assert all(method in ("OPTIONS", "POST") for method in rich_api["methods"]), f"rich-guide 方法异常：{rich_api['methods']}"
        assert rich_api["methods"].count("POST") == 4, f"rich-guide POST 次数异常：{rich_api['methods']}"
        assert api_responses and all(cors == http_origin for _, cors in api_responses), f"CORS 未精确回显 origin：{api_responses}"
        ok("HTTP 在线译注：精确 Origin/CORS + hand/llm provenance + 网络守卫")

        browser.close()

    print(f"\n viz_44 赏析诗页验收：{len(CHECKS)} 项全部通过；截图在 {SHOT_DIR.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
