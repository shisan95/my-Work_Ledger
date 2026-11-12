"""FastAPI 应用入口：REST 接口 + 静态页面托管 + 提醒后台线程 + 本机登录鉴权。"""
from __future__ import annotations

import os
import signal
import tempfile
import threading
import time
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import auth, config, crud, db, exporter, fields, ics, importer, reminders, utils

WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")
APP_VERSION = "1.6.3"

# 无需登录即可访问的接口：健康检查、登录相关、日历订阅源（供系统日历直接拉取）
PUBLIC_API_PATHS = {
    "/api/ping",
    "/api/auth/status",
    "/api/auth/setup",
    "/api/auth/login",
    "/api/calendar/feed.ics",
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    reminders.start()
    _refresh_ics()
    yield
    reminders.stop()


app = FastAPI(title="工作任务台账管理", version=APP_VERSION, lifespan=lifespan)


@app.middleware("http")
async def auth_guard(request: Request, call_next):
    """保护除白名单外的所有 /api 接口；无效会话一律返回 401，由前端跳转登录页。"""
    path = request.url.path
    if path.startswith("/api/") and path not in PUBLIC_API_PATHS:
        token = request.cookies.get(auth.COOKIE_NAME, "")
        session = auth.validate_session(token)
        if not session:
            return JSONResponse({"detail": "未登录或登录已过期"}, status_code=401)
        request.state.user = session
    return await call_next(request)



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
    trashed: bool = False,
) -> Dict[str, Any]:
    """列表筛选参数。排序由服务端固定（截止日期升序），不再支持手动排序。"""
    return {
        "q": q, "owner": owner, "status": status, "priority": priority,
        "start_from": start_from, "start_to": start_to,
        "due_from": due_from, "due_to": due_to,
        "overdue_only": overdue_only, "due_soon_only": due_soon_only,
        "remind_only": remind_only, "page": page, "page_size": page_size,
        "trashed": trashed,
    }


# ---------------------------------------------------------------- 启动与登录
@app.get("/api/ping")
def api_ping():
    """健康检查（免登录）：供启动器与启动页判断本地服务是否就绪。"""
    return {
        "ok": True,
        "app": "task-ledger",
        "version": APP_VERSION,
        "initialized": auth.is_initialized(),
    }


@app.get("/api/auth/status")
def api_auth_status(request: Request):
    """登录状态判断：未创建账号 / 未登录 / 已登录。"""
    initialized = auth.is_initialized()
    token = request.cookies.get(auth.COOKIE_NAME, "")
    session = auth.validate_session(token) if token else None
    return {
        "initialized": initialized,
        "authenticated": bool(session),
        "user": auth.account_public() if session else None,
        "expires": session.get("expires") if session else None,
        "remember": session.get("remember") if session else None,
    }


@app.post("/api/auth/setup")
def api_auth_setup(payload: Dict[str, Any]):
    """首次启动：创建本机账号并直接登录。"""
    if auth.is_initialized():
        raise HTTPException(400, "本机账号已创建，请直接登录")
    try:
        user = auth.setup_account(
            str((payload or {}).get("username", "")),
            str((payload or {}).get("password", "")),
            str((payload or {}).get("display_name", "")),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    remember = bool((payload or {}).get("remember", True))
    token, expires = auth.create_session(remember)
    resp = JSONResponse({"ok": True, "user": user, "expires": expires})
    resp.set_cookie(**auth.cookie_payload(token, remember))
    return resp


@app.post("/api/auth/login")
def api_auth_login(payload: Dict[str, Any], request: Request):
    if not auth.is_initialized():
        raise HTTPException(400, "本机账号尚未创建")

    ip = (request.client.host if request.client else "") or "local"
    left = auth.lock_remaining(ip)
    if left > 0:
        raise HTTPException(429, f"尝试次数过多，请 {left} 秒后重试")

    username = str((payload or {}).get("username", "")).strip()
    password = str((payload or {}).get("password", ""))
    remember = bool((payload or {}).get("remember", True))

    if not auth.verify_credentials(username, password):
        auth.record_failure(ip)
        raise HTTPException(401, "用户名或密码不正确")

    auth.clear_failures(ip)
    token, expires = auth.create_session(remember, request.headers.get("user-agent", ""))
    resp = JSONResponse({"ok": True, "user": auth.account_public(), "expires": expires})
    resp.set_cookie(**auth.cookie_payload(token, remember))
    return resp


@app.post("/api/auth/logout")
def api_auth_logout(request: Request):
    """退出登录：销毁服务端会话并清除 Cookie。"""
    auth.destroy_session(request.cookies.get(auth.COOKIE_NAME, ""))
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(key=auth.COOKIE_NAME, path="/")
    return resp


@app.post("/api/auth/password")
def api_auth_password(payload: Dict[str, Any]):
    try:
        auth.change_password(
            str((payload or {}).get("old_password", "")),
            str((payload or {}).get("new_password", "")),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"ok": True, "message": "密码已更新，请重新登录"}


@app.post("/api/app/quit")
def api_app_quit():
    """退出应用：清理全部会话后优雅关闭本地服务。"""
    auth.destroy_all_sessions()

    def _shutdown() -> None:
        time.sleep(0.5)  # 留出时间把响应送达前端
        try:
            os.kill(os.getpid(), signal.SIGTERM)
        except Exception:
            os._exit(0)

    threading.Thread(target=_shutdown, daemon=True).start()
    resp = JSONResponse({"ok": True, "message": "本地服务已退出"})
    resp.delete_cookie(key=auth.COOKIE_NAME, path="/")
    return resp


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


@app.get("/api/report/weekly")
def api_report_weekly():
    """本周周报数据：新增 / 完成 / 本周到期 / 逾期（口径见返回结构注释）。"""
    import datetime as dt
    settings = config.load_settings()
    done = settings.get("done_status", "已完成")
    today = dt.date.today()
    monday = today - dt.timedelta(days=today.weekday())
    week_start = f"{monday.isoformat()} 00:00"
    week_end = f"{(monday + dt.timedelta(days=6)).isoformat()} 23:59"
    now = utils.now_str()

    with db.get_conn() as conn:
        created = conn.execute(
            "SELECT * FROM tasks WHERE deleted_at IS NULL AND created_at >= ? AND created_at <= ? ORDER BY created_at ASC",
            (week_start, week_end)).fetchall()
        completed = conn.execute(
            "SELECT * FROM tasks WHERE deleted_at IS NULL AND updated_at >= ? AND updated_at <= ? "
            "AND ('|' || status || '|') LIKE ? ORDER BY updated_at ASC",
            (week_start, week_end, f"%|{done}|%")).fetchall()
        due = conn.execute(
            "SELECT * FROM tasks WHERE deleted_at IS NULL AND due_date != '' AND due_date >= ? AND due_date <= ? "
            "ORDER BY due_date ASC", (week_start, week_end)).fetchall()
        overdue = conn.execute(
            "SELECT * FROM tasks WHERE deleted_at IS NULL AND due_date != '' AND due_date < ? "
            "AND ('|' || status || '|') NOT LIKE ? ORDER BY due_date ASC",
            (now, f"%|{done}|%")).fetchall()

    def brief(rows):
        return [{
            "id": r["id"], "name": r["name"],
            "status_list": crud.status_list_of(r["status"]),
            "due_display": utils.display_date(r["due_date"] or ""),
        } for r in rows]

    return {
        "week_start": monday.isoformat(),
        "week_end": (monday + dt.timedelta(days=6)).isoformat(),
        "created": brief(created),
        "completed": brief(completed),
        "due": brief(due),
        "overdue": brief(overdue),
    }


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
    trashed: bool = False,
):
    params = _filter_params(**locals())
    data = crud.list_tasks(params)
    data["trash_count"] = crud.trash_count()
    return data


@app.get("/api/tasks/{task_id}")
def api_get_task(task_id: int):
    task = crud.get_task(task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    return task


@app.get("/api/tasks/{task_id}/history")
def api_task_history(task_id: int):
    if crud.get_raw(task_id) is None:
        raise HTTPException(404, "任务不存在")
    return {"items": crud.list_history(task_id)}


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
def api_delete_task(task_id: int, hard: bool = False):
    if hard:
        if not crud.purge_task(task_id):
            raise HTTPException(404, "任务不存在或不在回收站中")
    else:
        if not crud.delete_task(task_id):
            raise HTTPException(404, "任务不存在")
    _refresh_ics()
    return {"ok": True}


@app.post("/api/tasks/bulk-update")
async def api_bulk_update(payload: Dict[str, Any]):
    ids = [int(i) for i in payload.get("ids", []) if str(i).isdigit()]
    patch = payload.get("patch") or {}
    try:
        count = crud.bulk_update(ids, patch)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    _refresh_ics()
    return {"ok": True, "updated": count}


@app.post("/api/trash/restore")
async def api_trash_restore(payload: Dict[str, Any]):
    ids = [int(i) for i in payload.get("ids", []) if str(i).isdigit()]
    if not ids:
        raise HTTPException(400, "未选择要恢复的任务")
    count = crud.restore_many(ids)
    _refresh_ics()
    return {"ok": True, "restored": count}


@app.post("/api/trash/purge")
async def api_trash_purge(payload: Dict[str, Any]):
    db.backup("before-purge")
    ids = [int(i) for i in payload.get("ids", []) if str(i).isdigit()]
    if not ids:
        raise HTTPException(400, "未选择要彻底删除的任务")
    count = crud.purge_many(ids)
    _refresh_ics()
    return {"ok": True, "purged": count}


@app.post("/api/trash/empty")
def api_trash_empty():
    db.backup("before-empty-trash")
    count = crud.empty_trash()
    _refresh_ics()
    return {"ok": True, "purged": count}


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
        "flat": True,   # 导出包含子任务（平铺）
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
            "SELECT * FROM tasks WHERE deleted_at IS NULL AND "
            "(due_date != '' AND due_date >= ? AND due_date <= ?) OR "
            "(start_date != '' AND start_date >= ? AND start_date <= ? AND deleted_at IS NULL) OR "
            "(start_date != '' AND start_date <= ? AND (due_date = '' OR due_date >= ?) AND deleted_at IS NULL) "
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
# 本地单机应用：静态资源禁用强缓存，浏览器每次协商校验（ETag），
# 避免升级后仍加载旧版 JS/CSS 导致前端报错（如 API.ping is not a function）。


@app.middleware("http")
async def _no_strong_cache(request, call_next):
    response = await call_next(request)
    path = request.url.path
    if not path.startswith("/api/") and (
        path == "/"
        or path.endswith((".html", ".css", ".js", ".png", ".svg", ".ico"))
    ):
        response.headers["Cache-Control"] = "no-cache"
    return response


app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
