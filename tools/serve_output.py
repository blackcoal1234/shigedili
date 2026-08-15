"""启动本地 HTTP 服务，稳定展示 output/index.html。"""
from __future__ import annotations

import argparse
import functools
import sys
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from socketserver import TCPServer


ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "output"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000


class OutputRequestHandler(SimpleHTTPRequestHandler):
    """给静态输出目录设置简洁日志和常用 UTF-8 响应头。"""

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, format: str, *args: object) -> None:
        sys.stdout.write(f"[serve] {self.address_string()} - {format % args}\n")


def validate_output_dir(directory: Path = OUTPUT_DIR) -> Path:
    directory = directory.resolve()
    if not directory.exists() or not directory.is_dir():
        raise SystemExit(f"缺少输出目录：{directory}")
    for required in ("index.html", "manifest.json"):
        if not (directory / required).exists():
            raise SystemExit(f"输出目录缺少 {required}，请先运行 python run_all.py --no-crawl")
    return directory


def handler_for(directory: Path) -> type[SimpleHTTPRequestHandler]:
    return functools.partial(OutputRequestHandler, directory=str(directory))  # type: ignore[return-value]


def create_server(host: str, port: int, directory: Path) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), handler_for(directory))


def bind_available_server(host: str, start_port: int, directory: Path, attempts: int = 20) -> ThreadingHTTPServer:
    for port in range(start_port, start_port + attempts):
        try:
            return create_server(host, port, directory)
        except OSError:
            continue
    raise SystemExit(f"{host}:{start_port}-{start_port + attempts - 1} 均不可用")


def server_url(server: TCPServer, path: str = "index.html") -> str:
    host, port = server.server_address[:2]
    safe_path = path.lstrip("/")
    return f"http://{host}:{port}/{safe_path}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=DEFAULT_HOST, help="监听地址，默认 127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="起始端口，默认 8000")
    parser.add_argument("--no-open", action="store_true", help="只打印 URL，不自动打开浏览器")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    directory = validate_output_dir()
    server = bind_available_server(args.host, args.port, directory)
    url = server_url(server)
    print(f"本地演示服务已启动：{url}")
    print("按 Ctrl+C 停止服务。")
    if not args.no_open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止本地演示服务。")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
