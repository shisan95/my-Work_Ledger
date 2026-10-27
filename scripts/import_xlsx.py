#!/usr/bin/env python3
"""把 Excel/CSV 任务表批量导入本地台账（命令行方式，适合首次建库）。

用法：
    python scripts/import_xlsx.py ~/Downloads/任务汇总.xlsx
    python scripts/import_xlsx.py 任务.xlsx --mode replace   # 清空后导入
    python scripts/import_xlsx.py 任务.xlsx --mode update    # 按任务名称覆盖
"""
from __future__ import annotations

import argparse
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from app import db, importer  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="导入任务表到本地台账")
    parser.add_argument("path", help="表格文件路径（.xlsx/.xlsm/.csv）")
    parser.add_argument("--mode", default="append", choices=["append", "update", "replace"],
                        help="导入方式：append 追加 / update 按名称覆盖 / replace 清空后导入")
    args = parser.parse_args()

    if not os.path.exists(args.path):
        print(f"文件不存在：{args.path}")
        sys.exit(1)

    db.init_db()
    pv = importer.preview(args.path)
    print(f"文件：{pv['file']}，共 {pv['total']} 行")
    print("列映射：")
    for m in pv["mapping"]:
        flag = "（新增字段）" if m.get("custom") else ""
        print(f"  {m['header']}  ->  {m['label']}{flag}")

    result = importer.import_file(args.path, args.mode)
    print("\n" + result["message"])
    print(f"数据库：{db.DB_PATH}")


if __name__ == "__main__":
    main()
