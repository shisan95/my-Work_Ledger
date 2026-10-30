#!/bin/bash
# 构建 TaskLedger.app：生成图标 → 打包 .icns → 校验捆绑包
# 用法：./scripts/make_app.sh   （在项目根目录执行）
set -e
cd "$(dirname "$0")/.."
PY="${PYTHON:-.venv/bin/python}"
command -v iconutil >/dev/null || { echo "需要 macOS 的 iconutil"; exit 1; }

echo "① 生成图标…"
rm -rf /tmp/tl.iconset
"$PY" scripts/make_icon.py /tmp/tl.iconset

echo "② 打包 .icns…"
mkdir -p TaskLedger.app/Contents/Resources
iconutil -c icns /tmp/tl.iconset -o ./icon.icns
mv ./icon.icns TaskLedger.app/Contents/Resources/icon.icns
rm -rf /tmp/tl.iconset

echo "③ 赋予执行权限并校验…"
chmod +x TaskLedger.app/Contents/MacOS/TaskLedger
plutil -lint TaskLedger.app/Contents/Info.plist

echo "完成：TaskLedger.app（可移到桌面或「应用程序」使用）"
