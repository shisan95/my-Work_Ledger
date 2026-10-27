"""表格导出：把当前任务（可按筛选条件）导出为 .xlsx / .csv，并提供导入模板。"""
from __future__ import annotations

import csv
import io
import os
from typing import Any, Dict, List

from . import fields
from .utils import date_part, time_part, is_all_day, today_str

HEADER_STYLE_FILL = "DDEBF7"


def _columns(registry: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    order = ["name", "owner", "priority", "status", "start_date", "due_date", "remark"]
    cols = [f for k in order for f in registry if f["key"] == k]
    cols += [f for f in registry if f.get("custom")]
    return cols


def _cell_value(field: Dict[str, Any], task: Dict[str, Any]) -> str:
    key = field["key"]
    value = task.get(key, "")
    if key in ("start_date", "due_date"):
        if not value:
            return ""
        return date_part(value) if is_all_day(value) else f"{date_part(value)} {time_part(value)}"
    return "" if value is None else str(value)


def to_csv_bytes(tasks: List[Dict[str, Any]]) -> bytes:
    registry = fields.get_registry()
    cols = _columns(registry)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([c["label"] for c in cols])
    for t in tasks:
        writer.writerow([_cell_value(c, t) for c in cols])
    # BOM 让 Excel 正确识别 UTF-8
    return b"\xef\xbb\xbf" + buf.getvalue().encode("utf-8")


def to_xlsx_bytes(tasks: List[Dict[str, Any]]) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    registry = fields.get_registry()
    cols = _columns(registry)

    wb = Workbook()
    ws = wb.active
    ws.title = "任务台账"

    head_font = Font(bold=True, color="1F2328", size=11)
    head_fill = PatternFill("solid", fgColor=HEADER_STYLE_FILL)

    ws.append([c["label"] for c in cols])
    for i in range(1, len(cols) + 1):
        cell = ws.cell(row=1, column=i)
        cell.font = head_font
        cell.fill = head_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")
        width = max(10, min(int(cols[i - 1].get("width", 140) / 8), 46))
        ws.column_dimensions[get_column_letter(i)].width = width

    for t in tasks:
        ws.append([_cell_value(c, t) for c in cols])

    ws.freeze_panes = "A2"
    if len(tasks) > 0:
        ws.auto_filter.ref = f"A1:{get_column_letter(len(cols))}{len(tasks) + 1}"
    for row in ws.iter_rows(min_row=2, max_row=len(tasks) + 1):
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def template_bytes(fmt: str = "xlsx") -> bytes:
    """生成带表头与示例行的导入模板。"""
    demo = [
        {
            "name": "示例：业务系统代码审计",
            "owner": "张三",
            "priority": "重要且紧急",
            "status": "进行中",
            "start_date": f"{today_str()} 00:00",
            "due_date": f"{today_str()} 23:59",
            "remark": "进展备注示例",
        }
    ]
    if fmt == "csv":
        return to_csv_bytes(demo)
    return to_xlsx_bytes(demo)


def build_filename(prefix: str, fmt: str) -> str:
    return f"{prefix}-{today_str()}.{fmt}"
