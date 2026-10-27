#!/bin/bash
# 一键启动脚本（macOS / Linux）
set -e
cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  echo "首次运行，正在创建虚拟环境并安装依赖…"
  python3 -m venv .venv
  .venv/bin/pip install --upgrade pip -q
  .venv/bin/pip install -r requirements.txt
fi

exec .venv/bin/python start.py "$@"
