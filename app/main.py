"""FastAPI 应用入口：REST 接口 + 静态页面托管 + 提醒后台线程。"""
from __future__ import annotations

import os
import tempfile
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import config, crud, db, exporter, fields, ics, importer, reminders

WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    reminders.start()
    _refresh_ics()
    yield
    reminders.stop()


app = FastAPI(title="工作任务台账管理", version="1.0.0", lifespan=lifespan)


def _refresh_ics() -> None:
    """数据变动后自动刷新系统日历同步文件。"""
    try:
        settings = config.load_settings()
        if settings.get("auto_export_ics", True):
            ics.write_ics(crud.list_all(), settings.get("ics_path"))
    except Exception:
        pass


def _filter_params(
    q: str = "",
    owner: Optional[List[str]] = Query(default=None),
    status: Optional[List[str]] = Query(default=None),
    priority: Optional[List[str]] = Query(default=None),
    start_from: str = "",
    start_to: str = "",
    due_from: str = "",
    due_to: str = "",
    overdue_only: bool = False,
    due_soon_only: bool = False,
    remind_only: bool = False,
    page: int = 1,
    page_size: int = 0,
) -> Dict[str, Any]:
    """列表筛选参数。排序由服务端固定（截止日期升序），不再支持手动排序。"""
    return {
        "q": q, "owner": owner, "status": status, "priority": priority,
        "start_from": start_from, "start_to": start_to,
        "due_from": due_from, "due_to": due_to,
        "overdue_only": overdue_only, "due_soon_only": due_soon_only,
        "remind_only": remind_only, "page": page, "page_size": page_size,
    }


# ---------------------------------------------------------------- 字段
@app.get("/api/fields")
def api_fields():
    registry = fields.get_registry()
    return {
        "fields": registry,
        "list_fields": [f for f in registry if f.get("inList")],
        "editable_fields": [f["key"] for f in registry if f.get("editable") and f.get("inList")],
        "lead_options": config.LEAD_OPTIONS,
    }


@app.get("/api/options")
def api_options():
    return crud.options()


@app.get("/api/stats")
def api_stats():
    return crud.stats()


# ---------------------------------------------------------------- 任务 CRUD
@app.get("/api/tasks")
def api_list_tasks(
    q: str = "",
    owner: Optional[List[str]] = Query(default=None),
    status: Optional[List[str]] = Query(default=None),
    priority: Optional[List[str]] = Query(default=None),
    start_from: str = "",
    start_to: str = "",
    due_from: str = "",
    due_to: str = "",
    overdue_only: bool = False,
    due_soon_only: bool = False,
    remind_only: bool = False,
    page: int = 1,
    page_size: int = 0,
):
    params = _filter_params(**locals())
    return crud.list_tasks(params)


@app.get("/api/tasks/{task_id}")
def api_get_task(task_id: int):
    task = crud.get_task(task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    return task


@app.post("/api/tasks")
async def api_create_task(payload: Dict[str, Any]):
    try:
        task = crud.create_task(payload)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    _refresh_ics()
    return task


@app.put("/api/tasks/{task_id}")
async def api_update_task(task_id: int, payload: Dict[str, Any]):
    try:
        task = crud.update_task(task_id, payload)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if not task:
        raise HTTPException(404, "任务不存在")
    _refresh_ics()
    return task


@app.delete("/api/tasks/{task_id}")
def api_delete_task(task_id: int):
    if not crud.delete_task(task_id):
        raise HTTPException(404, "任务不存在")
    _refresh_ics()
    return {"ok": True}


@app.post("/api/tasks/bulk-delete")
async def api_bulk_delete(payload: Dict[str, Any]):
    ids = [int(i) for i in payload.get("ids", []) if str(i).isdigit()]
    count = crud.bulk_delete(ids)
    _refresh_ics()
    return {"ok": True, "deleted": count}


@app.post("/api/tasks/clear")
def api_clear():
    db.backup("before-clear")
    count = crud.clear_all()
    _refresh_ics()
    return {"ok": True, "deleted": count}


# ---------------------------------------------------------------- 导入 / 导出
@app.post("/api/import")
async def api_import(file: UploadFile = File(...), mode: str = Form("append")):
    suffix = os.path.splitext(file.filename or "")[1].lower()
    if suffix not in importer.SUPPORTED_EXT:
        raise HTTPException(400, f"仅支持 {', '.join(importer.SUPPORTED_EXT)} 文件")
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name
    try:
        try:
            preview = importer.preview(tmp_path)
        except Exception as exc:
            raise HTTPException(400, f"文件解析失败：{exc}")
        result = importer.import_file(tmp_path, mode)
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
    result["mapping"] = preview.get("mapping", [])
    _refresh_ics()
    return result


@app.post("/api/import/preview")
async def api_import_preview(file: UploadFile = File(...)):
    suffix = os.path.splitext(file.filename or "")[1].lower()
    if suffix not in importer.SUPPORTED_EXT:
        raise HTTPException(400, f"仅支持 {', '.join(importer.SUPPORTED_EXT)} 文件")
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name
    try:
        return importer.preview(tmp_path)
    except Exception as exc:
        raise HTTPException(400, f"文件解析失败：{exc}")
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass


@app.get("/api/export")
def api_export(
    format: str = "xlsx",
    q: str = "",
    owner: Optional[List[str]] = Query(default=None),
    status: Optional[List[str]] = Query(default=None),
    priority: Optional[List[str]] = Query(default=None),
    start_from: str = "",
    start_to: str = "",
    due_from: str = "",
    due_to: str = "",
    overdue_only: bool = False,
):
    params = {
        "q": q, "owner": owner, "status": status, "priority": priority,
        "start_from": start_from, "start_to": start_to,
        "due_from": due_from, "due_to": due_to, "overdue_only": overdue_only,
    }
    tasks = crud.list_all(params)
    fmt = (format or "xlsx").lower()
    if fmt == "csv":
        data = exporter.to_csv_bytes(tasks)
        media = "text/csv; charset=utf-8"
    else:
        data = exporter.to_xlsx_bytes(tasks)
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    filename = exporter.build_filename("任务台账导出", fmt)
    return Response(
        content=data,
        media_type=media,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )


@app.get("/api/export/template")
def api_export_template(format: str = "xlsx"):
    fmt = (format or "xlsx").lower()
    data = exporter.template_bytes(fmt)
    if fmt == "csv":
        media = "text/csv; charset=utf-8"
    else:
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    name = f"任务台账导入模板.{fmt}"
    return Response(
        content=data,
        media_type=media,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"},
    )


# ---------------------------------------------------------------- 日历
@app.get("/api/calendar/month")
def api_calendar_month(year: int, month: int):
    """返回指定月份的任务，按日期分组，供日历视图渲染。"""
    import calendar
    import datetime as dt

    year, month = int(year), int(month)
    last = calendar.monthrange(year, month)[1]
    start = f"{year:04d}-{month:02d}-01 00:00"
    end = f"{year:04d}-{month:02d}-{last:02d} 23:59"

    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM tasks WHERE "
            "(due_date != '' AND due_date >= ? AND due_date <= ?) OR "
            "(start_date != '' AND start_date >= ? AND start_date <= ?) OR "
            "(start_date != '' AND start_date <= ? AND (due_date = '' OR due_date >= ?)) "
            "ORDER BY due_date ASC, start_date ASC",
            (start, end, start, end, start, start),
        ).fetchall()

    settings = config.load_settings()
    by_date: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        task = crud.task_to_dict(row, settings)
        days = set()
        if task["start_date"]:
            days.add(task["start_date"][:10])
        if task["due_date"]:
            days.add(task["due_date"][:10])
        for d in days:
            if d[:7] == f"{year:04d}-{month:02d}":
                by_date.setdefault(d, []).append(task)
    return {"year": year, "month": month, "days": by_date}


@app.get("/api/calendar/ics")
def api_calendar_ics():
    """下载 .ics 文件（用于导入系统日历）。"""
    path = ics.write_ics(crud.list_all())
    return FileResponse(
        path,
        media_type="text/calendar; charset=utf-8",
        filename="任务台账.ics",
    )


@app.get("/api/calendar/feed.ics")
def api_calendar_feed():
    """日历订阅源：可在系统日历中作为订阅地址持续同步。"""
    content = ics.build_ics(crud.list_all())
    return Response(content=content.encode("utf-8"), media_type="text/calendar; charset=utf-8")


@app.post("/api/calendar/sync")
def api_calendar_sync():
    """生成并调用系统默认程序打开 .ics（macOS 会唤起「日历」导入）。"""
    path = ics.write_ics(crud.list_all())
    msg = ics.open_in_system_calendar(path)
    return {"ok": True, "path": path, "message": msg}


# ---------------------------------------------------------------- 提醒
@app.get("/api/reminders/check")
def api_reminders_check():
    result = reminders.scan()
    return {
        "overdue": result["overdue"],
        "due_soon": result["due_soon"],
        "count": reminders.pending_count(),
        "daemon": reminders.status(),
    }


@app.post("/api/reminders/snooze/{task_id}")
async def api_snooze(task_id: int, payload: Dict[str, Any] | None = None):
    import datetime as dt

    settings = config.load_settings()
    minutes = int((payload or {}).get("minutes") or settings.get("snooze_minutes", 30))
    until = (dt.datetime.now() + dt.timedelta(minutes=minutes)).strftime("%Y-%m-%d %H:%M")
    task = crud.update_task(task_id, {"snooze_until": until, "reminded_at": ""})
    if not task:
        raise HTTPException(404, "任务不存在")
    return {"ok": True, "snooze_until": until, "task": task}


@app.post("/api/reminders/test")
def api_test_notify():
    ok = reminders.notify("任务台账提醒测试", "如果你看到这条通知，说明桌面提醒已正常工作")
    return {"ok": ok}


# ---------------------------------------------------------------- 设置
@app.get("/api/settings")
def api_get_settings():
    return {"settings": config.load_settings(), "daemon": reminders.status()}


@app.put("/api/settings")
async def api_put_settings(payload: Dict[str, Any]):
    settings = config.save_settings(payload or {})
    _refresh_ics()
    return {"settings": settings}


@app.post("/api/system/backup")
def api_backup():
    path = db.backup("manual")
    return {"ok": True, "path": path}


# ---------------------------------------------------------------- 静态页面
app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
