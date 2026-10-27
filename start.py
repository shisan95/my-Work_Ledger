#!/usr/bin/env python3
"""启动入口：启动本地服务并自动打开浏览器。

用法：
    python start.py                # 默认 http://127.0.0.1:8765
    python start.py --port 9000    # 指定端口
    python start.py --no-browser   # 不自动打开浏览器
"""
from __future__ import annotations

import argparse
import os
import sys
import threading
import time
import webbrowser

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)


def main() -> None:
    parser = argparse.ArgumentParser(description="工作任务台账管理软件")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址")
    parser.add_argument("--port", type=int, default=8765, help="监听端口")
    parser.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    args = parser.parse_args()

    import uvicorn

    from app.main import app  # noqa: 延后导入，确保 sys.path 已生效

    url = f"http://{args.host}:{args.port}"
    print("=" * 56)
    print("  工作任务台账管理软件")
    print(f"  访问地址： {url}")
    print(f"  数据文件： {os.path.join(BASE_DIR, 'data', 'tasks.db')}")
    print("  按 Ctrl+C 可停止服务")
    print("=" * 56)

    if not args.no_browser:
        def _open() -> None:
            time.sleep(1.2)
            try:
                webbrowser.open(url)
            except Exception:
                pass

        threading.Thread(target=_open, daemon=True).start()

    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
