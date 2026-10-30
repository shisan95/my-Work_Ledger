#!/bin/bash
# 停止任务台账后台服务（双击运行）
set -u
cd "$(dirname "$0")"
PORT="${TASK_LEDGER_PORT:-8765}"

stopped=0
if [ -f "data/server.pid" ]; then
  PID=$(cat data/server.pid)
  if kill "$PID" 2>/dev/null; then stopped=1; fi
  rm -f data/server.pid
fi
# 兜底：结束占用端口的残留进程
PIDS=$(lsof -ti tcp:"$PORT" 2>/dev/null)
if [ -n "$PIDS" ]; then
  kill $PIDS 2>/dev/null
  sleep 1
  kill -9 $PIDS 2>/dev/null
  stopped=1
fi

if [ "$stopped" = "1" ]; then
  MSG="任务台账服务已停止"
else
  MSG="任务台账服务未在运行"
fi
echo "$MSG"
osascript -e "display notification \"$MSG\" with title \"任务台账\"" 2>/dev/null
exit 0
