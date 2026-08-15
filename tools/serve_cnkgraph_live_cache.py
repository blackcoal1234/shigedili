"""启动 CNKGraph 当场现爬本地服务。

页面通过本机 HTTP API 请求当前诗人的 CNKGraph 生平页；服务端复用
Playwright 持久浏览器会话，便于人工微信登录后继续采集并写入本地缓存。
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from importlib import import_module
from pathlib import Path
from socketserver import TCPServer
from typing import Any
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.collect_cnkgraph_poet_life import (  # noqa: E402
    DEFAULT_OUTPUT,
    DEFAULT_PROFILE_DIR,
    FetchResult,
    cache_record,
    html_to_text,
    is_login_page,
    load_existing_cache,
    source_url_for_poet,
    write_cache,
)


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8131
ALLOWED_ORIGIN_HOSTS = {"127.0.0.1", "localhost"}


def is_allowed_origin(origin: str | None) -> bool:
    """只允许本地页面和 file:// 页面访问现爬服务。"""
    if not origin:
        return True
    if origin == "null":
        return True
    parsed = urlparse(origin)
    return parsed.scheme in {"http", "https"} and parsed.hostname in ALLOWED_ORIGIN_HOSTS


def cors_origin_value(origin: str | None) -> str:
    if origin == "null":
        return "null"
    if origin and is_allowed_origin(origin):
        return origin
    return "*"


class LiveCnkgraphCollector:
    """复用持久浏览器会话采集单个诗人生平页。"""

    def __init__(
        self,
        profile_dir: Path = DEFAULT_PROFILE_DIR,
        timeout: float = 25.0,
        browser_executable: Path | None = None,
    ) -> None:
        self.profile_dir = profile_dir
        self.timeout = max(1.0, timeout)
        self.browser_executable = browser_executable
        self._playwright: Any = None
        self._context: Any = None
        self._page: Any = None

    @property
    def initialized(self) -> bool:
        return self._context is not None and self._page is not None

    def _ensure_browser(self) -> None:
        if self.initialized:
            return
        try:
            sync_playwright = import_module("playwright.sync_api").sync_playwright
        except ImportError as exc:
            raise RuntimeError("未安装 playwright，无法启动 CNKGraph 登录采集浏览器") from exc

        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self._playwright = sync_playwright().start()
        launch_options: dict[str, object] = {
            "headless": False,
            "viewport": {"width": 1280, "height": 860},
        }
        if self.browser_executable:
            launch_options["executable_path"] = str(self.browser_executable)
        self._context = self._playwright.chromium.launch_persistent_context(
            str(self.profile_dir),
            **launch_options,
        )
        self._page = self._context.new_page()

    def collect_poet(self, poet: str, force: bool = False) -> dict[str, object]:
        self._ensure_browser()
        url = source_url_for_poet(poet)
        try:
            self._page.goto(url, wait_until="networkidle", timeout=int(self.timeout * 1000))
            body = self._page.content()
            final_url = self._page.url
            if is_login_page(final_url, body):
                result = FetchResult(url=final_url, status="needs_login", body=body, note="需要微信登录")
            else:
                result = FetchResult(url=final_url, status="ok", body=body)
        except Exception as exc:  # Playwright 异常类型较多，统一转成缓存状态。
            result = FetchResult(url=url, status="fetch_failed", note=str(exc))
        return cache_record(poet, result)

    def close(self) -> None:
        if self._context is not None:
            self._context.close()
            self._context = None
            self._page = None
        if self._playwright is not None:
            self._playwright.stop()
            self._playwright = None


class LiveCacheServer(HTTPServer):
    """携带缓存路径、采集器和串行锁的 HTTPServer。"""

    def __init__(
        self,
        server_address: tuple[str, int],
        handler_class: type[BaseHTTPRequestHandler],
        cache_path: Path,
        collector: object,
    ) -> None:
        super().__init__(server_address, handler_class)
        self.cache_path = cache_path
        self.collector = collector
        self.collect_lock = threading.Lock()

    def server_close(self) -> None:
        close = getattr(self.collector, "close", None)
        if callable(close):
            close()
        super().server_close()


def cache_poet_count(cache_path: Path) -> int:
    cache = load_existing_cache(cache_path)
    poets = cache.get("poets")
    return len(poets) if isinstance(poets, dict) else 0


def update_cache(cache_path: Path, poet: str, record: dict[str, object]) -> None:
    cache = load_existing_cache(cache_path)
    poets = cache.setdefault("poets", {})
    if not isinstance(poets, dict):
        poets = {}
        cache["poets"] = poets
    poets[poet] = record
    cache["source"] = "https://cnkgraph.com/Map/PoetLife"
    write_cache(cache_path, cache)


def cached_ok_record(cache_path: Path, poet: str) -> dict[str, object] | None:
    cache = load_existing_cache(cache_path)
    poets = cache.get("poets")
    if not isinstance(poets, dict):
        return None
    record = poets.get(poet)
    if isinstance(record, dict) and record.get("status") == "ok":
        return record
    return None


def status_message(record: dict[str, object]) -> str:
    status = str(record.get("status") or "unknown")
    detail = str(record.get("note") or record.get("parse_note") or "").strip()
    if status == "ok":
        return "CNKGraph 缓存已更新。"
    if status == "needs_login":
        return "请在弹出的 CNKGraph 浏览器完成微信登录后重试。"
    if status == "parse_failed":
        return "CNKGraph 页面已返回，但本地解析失败。" + (f"原因：{detail}" if detail else "")
    return "CNKGraph 采集失败。" + (f"原因：{detail}" if detail else "请稍后重试。")


class LiveCacheRequestHandler(BaseHTTPRequestHandler):
    server: LiveCacheServer

    def end_headers(self) -> None:
        origin = self.headers.get("Origin")
        self.send_header("Access-Control-Allow-Origin", cors_origin_value(origin))
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, format: str, *args: object) -> None:
        sys.stdout.write(f"[cnkgraph-live] {self.address_string()} - {format % args}\n")

    def reject_disallowed_origin(self) -> bool:
        origin = self.headers.get("Origin")
        if is_allowed_origin(origin):
            return False
        self.send_json(403, {"status": "forbidden", "message": "只允许本机页面访问 CNKGraph 现爬服务"})
        return True

    def send_json(self, status: int, payload: dict[str, object]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:
        if self.reject_disallowed_origin():
            return
        self.send_response(204)
        self.end_headers()

    def do_GET(self) -> None:
        if self.reject_disallowed_origin():
            return
        if urlparse(self.path).path != "/api/cnkgraph/status":
            self.send_json(404, {"status": "not_found", "message": "接口不存在"})
            return
        initialized = bool(getattr(self.server.collector, "initialized", False))
        self.send_json(
            200,
            {
                "status": "ok",
                "cachePoetCount": cache_poet_count(self.server.cache_path),
                "browserInitialized": initialized,
            },
        )

    def do_POST(self) -> None:
        if self.reject_disallowed_origin():
            return
        if urlparse(self.path).path != "/api/cnkgraph/poet-life":
            self.send_json(404, {"status": "not_found", "message": "接口不存在"})
            return
        try:
            length = int(self.headers.get("Content-Length") or "0")
            raw = self.rfile.read(length).decode("utf-8")
            payload = json.loads(raw) if raw else {}
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            self.send_json(400, {"status": "bad_request", "message": "请求体必须是 JSON"})
            return

        poet = str(payload.get("poet") or "").strip() if isinstance(payload, dict) else ""
        force = bool(payload.get("force")) if isinstance(payload, dict) else False
        if not poet:
            self.send_json(400, {"status": "bad_request", "message": "缺少 poet"})
            return

        with self.server.collect_lock:
            record = None if force else cached_ok_record(self.server.cache_path, poet)
            if record is None:
                collect = getattr(self.server.collector, "collect_poet")
                record = collect(poet, force=force)
                update_cache(self.server.cache_path, poet, record)

        status = str(record.get("status") or "unknown")
        self.send_json(
            200,
            {
                "status": status,
                "poet": poet,
                "record": record,
                "message": status_message(record),
            },
        )


def create_server(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    cache_path: Path = DEFAULT_OUTPUT,
    collector: object | None = None,
) -> LiveCacheServer:
    live_collector = collector if collector is not None else LiveCnkgraphCollector()
    return LiveCacheServer((host, port), LiveCacheRequestHandler, Path(cache_path), live_collector)


def bind_available_server(
    host: str,
    start_port: int,
    cache_path: Path,
    collector: object | None = None,
    attempts: int = 20,
) -> LiveCacheServer:
    for port in range(start_port, start_port + attempts):
        try:
            return create_server(host=host, port=port, cache_path=cache_path, collector=collector)
        except OSError:
            continue
    raise SystemExit(f"{host}:{start_port}-{start_port + attempts - 1} 均不可用")


def server_url(server: TCPServer) -> str:
    host, port = server.server_address[:2]
    return f"http://{host}:{port}/api/cnkgraph/status"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=DEFAULT_HOST, help="监听地址，默认 127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="起始端口，默认 8131")
    parser.add_argument("--cache", default=str(DEFAULT_OUTPUT), help="CNKGraph 缓存 JSON 路径")
    parser.add_argument("--profile-dir", default=str(DEFAULT_PROFILE_DIR), help="Playwright 用户数据目录")
    parser.add_argument("--browser-executable", default="", help="可选浏览器可执行文件路径，例如 msedge.exe")
    parser.add_argument("--timeout", type=float, default=25.0, help="单页采集超时秒数")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    collector = LiveCnkgraphCollector(
        profile_dir=Path(args.profile_dir),
        timeout=max(1.0, args.timeout),
        browser_executable=Path(args.browser_executable) if args.browser_executable else None,
    )
    server = bind_available_server(
        host=args.host,
        start_port=args.port,
        cache_path=Path(args.cache),
        collector=collector,
    )
    print(f"CNKGraph 现爬服务已启动：{server_url(server)}")
    print("页面按钮会在首次采集时打开持久浏览器；请在弹出的 CNKGraph 页面完成微信登录。")
    print("按 Ctrl+C 停止服务。")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止 CNKGraph 现爬服务。")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
