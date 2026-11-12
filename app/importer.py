"""表格导入：支持 .xlsx / .xlsm / .csv，自动识别表头并映射字段。

未知列会自动注册为自定义字段，界面列表与表单随之扩展。
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import os
from typing import Any, Dict, List, Tuple

from . import crud, db, fields
from .utils import parse_due, parse_start, safe_str

SUPPORTED_EXT = (".xlsx", ".xlsm", ".csv")


def read_table(path: str) -> Tuple[List[str], List[List[Any]]]:
    """读取表格，返回 (表头, 数据行)。自动跳过表头之前的空行。"""
    ext = os.path.splitext(path)[1].lower()
    if ext not in SUPPORTED_EXT:
        raise ValueError(f"不支持的文件类型：{ext}，请上传 .xlsx / .xlsm / .csv")

    if ext == ".csv":
        return _read_csv(path)

    from openpyxl import load_workbook

    wb = load_workbook(path, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    return _split_header(rows)


def _read_csv(path: str) -> Tuple[List[str], List[List[Any]]]:
    raw = open(path, "rb").read()
    for enc in ("utf-8-sig", "utf-8", "gbk", "gb18030"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode("utf-8", errors="ignore")
    reader = csv.reader(io.StringIO(text))
    return _split_header([tuple(r) for r in reader])


def _split_header(rows: List[Any]) -> Tuple[List[str], List[List[Any]]]:
    header: List[str] = []
    data: List[List[Any]] = []
    for idx, row in enumerate(rows):
        cells = [("" if c is None else str(c).strip()) for c in row]
        if not any(cells):
            continue
        if not header:
            header = cells
            continue
        data.append(list(row))
    return header, data


def preview(path: str) -> Dict[str, Any]:
    """导入前预览：列映射关系、样例数据、未识别的列。"""
    header, data = read_table(path)
    mapping, custom_cols = _map_header(header)
    return {
        "file": os.path.basename(path),
        "header": header,
        "mapping": mapping,
        "custom_columns": custom_cols,
        "total": len(data),
        "sample": [[safe_str(c) for c in row] for row in data[:5]],
    }


def _map_header(header: List[str]) -> Tuple[List[Dict[str, Any]], List[str]]:
    mapping = []
    custom_cols = []
    for i, h in enumerate(header):
        key = fields.match_field(h)
        if key:
            mapping.append({"index": i, "header": h, "field": key, "label": _label_of(key)})
        elif h:
            custom_cols.append(h)
            mapping.append({"index": i, "header": h, "field": f"extra:{h}", "label": h,
                            "custom": True})
    return mapping, custom_cols


def _label_of(key: str) -> str:
    for f in fields.BASE_FIELDS:
        if f["key"] == key:
            return f["label"]
    return key


def _register_custom(custom_cols: List[str]) -> None:
    for col in custom_cols:
        db.upsert_custom_field(col, col, "text")


def _row_to_payload(header: List[str], row: List[Any]) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    for i, h in enumerate(header):
        if not h or i >= len(row):
            continue
        key = fields.match_field(h) or f"extra:{h}"
        value = row[i]
        if key == "start_date":
            payload["start_date"] = parse_start(value)
        elif key == "due_date":
            payload["due_date"] = parse_due(value)
        else:
            payload[key] = safe_str(value)
    return payload


def import_file(path: str, mode: str = "append") -> Dict[str, Any]:
    """执行导入。

    mode: append=追加  |  replace=清空后导入  |  update=按任务名称覆盖已有记录
    """
    header, data = read_table(path)
    if not header:
        return {"inserted": 0, "updated": 0, "skipped": 0, "custom_columns": [], "message": "未识别到表头"}

    _, custom_cols = _map_header(header)
    _register_custom(custom_cols)

    if mode not in ("append", "replace", "update"):
        mode = "append"

    if mode == "replace":
        db.backup("before-replace")
        crud.clear_all()

    inserted = updated = skipped = 0
    if mode == "update":
        with db.get_conn() as conn:
            existing = {r["name"]: r["id"] for r in conn.execute("SELECT id, name FROM tasks WHERE deleted_at IS NULL").fetchall()}
    else:
        existing = {}

    for row in data:
        if not any(c is not None and str(c).strip() != "" for c in row):
            skipped += 1
            continue
        payload = _row_to_payload(header, row)
        if not payload.get("name"):
            skipped += 1
            continue
        if mode == "update" and payload["name"] in existing:
            crud.update_task(existing[payload["name"]], payload)
            updated += 1
        else:
            crud.create_task(payload)
            inserted += 1

    return {
        "inserted": inserted,
        "updated": updated,
        "skipped": skipped,
        "mode": mode,
        "custom_columns": custom_cols,
        "message": f"导入完成：新增 {inserted} 条"
        + (f"，更新 {updated} 条" if updated else "")
        + (f"，跳过 {skipped} 行" if skipped else ""),
    }
