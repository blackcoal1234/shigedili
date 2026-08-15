"""项目全局配置：MySQL 连接信息与路径常量。

数据库凭据只从环境变量读取，避免把本机密码提交到课程交付包。
"""
import os
import sys
from pathlib import Path

# 在 Windows 终端把 stdout/stderr 切到 UTF-8，避免 GBK 编码报错
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
OUTPUT_DIR = ROOT / "output"
DATA_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

MYSQL = dict(
    host=os.getenv("SHIXING_MYSQL_HOST", "127.0.0.1"),
    port=int(os.getenv("SHIXING_MYSQL_PORT", "3306")),
    user=os.getenv("SHIXING_MYSQL_USER", "root"),
    password=os.getenv("SHIXING_MYSQL_PASSWORD", ""),
    charset="utf8mb4",
)
DB_NAME = os.getenv("SHIXING_MYSQL_DATABASE", "shixing_wanli")
