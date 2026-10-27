"""提醒引擎：到期提醒（自定义提前量）+ 逾期高亮 + 桌面通知。

- 后台线程按 settings.poll_seconds 轮询；
- 触发条件：任务开启提醒、状态属于 remind_statuses、截止时间已落在提醒窗口内；
- 每条任务只提醒一次（reminded_at），改期或改提前量后自动重新生效；
- “稍后提醒”写入 snooze_until，顺延期间不再打扰。
"""
from __future__ import annotations

import datetime as dt
import platform
import subprocess
import threading
import time
from typing import Any, Dict, List

from . import config, crud, db

_state = {"running": False, "thread": None, "last_check": "", "last_error": ""}


# ---------------------------------------------------------------- 计算
def is_remindable(task: Dict[str, Any], settings: Dict[str, Any]) -> bool:
    if not task.get("due_date"):
        return False
    if not task.get("remind_enabled", True):
        return False
    if task.get("status") not in settings.get("remind_statuses", []):
        return False
    if task.get("snooze_until"):
        s = _parse(task["snooze_until"])
        if s and s > dt.datetime.now():
            return False
    return True


def _parse(value: str):
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return dt.datetime.strptime(value, fmt)
        except (ValueError, TypeError):
            continue
    return None


def scan() -> Dict[str, List[Dict[str, Any]]]:
    """返回当前逾期任务与即将到期任务。"""
    settings = config.load_settings()
    now = dt.datetime.now()
    overdue: List[Dict[str, Any]] = []
    due_soon: List[Dict[str, Any]] = []

    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM tasks WHERE due_date != '' ORDER BY due_date ASC"
        ).fetchall()

    for row in rows:
        task = crud.task_to_dict(row, settings)
        due = _parse(task["due_date"])
        if not due:
            continue
        if due < now and not task["is_done"]:
            overdue.append(task)
        elif is_remindable(task, settings) and task.get("remind_at"):
            ra = _parse(task["remind_at"])
            if ra and ra <= now and due >= now:
                due_soon.append(task)
    return {"overdue": overdue, "due_soon": due_soon}


def pending_count() -> Dict[str, int]:
    r = scan()
    return {
        "overdue": len(r["overdue"]),
        "due_soon": len(r["due_soon"]),
        "total": len(r["overdue"]) + len(r["due_soon"]),
    }


# ---------------------------------------------------------------- 桌面通知
def notify(title: str, body: str) -> bool:
    """跨平台桌面通知：macOS 通知中心 / Linux notify-send / Windows 气泡。"""
    system = platform.system()
    try:
        if system == "Darwin":
            script = (
                'display notification "'
                + body.replace('"', "'")
                + '" with title "'
                + title.replace('"', "'")
                + '"'
            )
            subprocess.run(["osascript", "-e", script], timeout=8, check=False)
        elif system == "Linux":
            subprocess.run(["notify-send", title, body], timeout=8, check=False)
        elif system == "Windows":
            ps = (
                "[reflection.assembly]::loadwithpartialname('System.Windows.Forms');"
                "$n=New-Object System.Windows.Forms.NotifyIcon;"
                "$n.Icon=[System.Drawing.SystemIcons]::Information;"
                "$n.BalloonTipTitle='" + title.replace("'", "") + "';"
                "$n.BalloonTipText='" + body.replace("'", "") + "';"
                "$n.Visible=$true; $n.ShowBalloonTip(8000); Start-Sleep -s 8; $n.Dispose()"
            )
            subprocess.run(["powershell", "-NoProfile", "-Command", ps], timeout=15, check=False)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------- 后台循环
def _tick() -> None:
    settings = config.load_settings()
    try:
        result = scan()
    except Exception as exc:
        _state["last_error"] = str(exc)
        return
    _state["last_check"] = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _state["last_error"] = ""

    if not settings.get("desktop_notify", True):
        return

    for task in result["due_soon"]:
        if task.get("reminded_at"):
            continue
        lead = task.get("remind_lead_minutes")
        lead = settings.get("default_lead_minutes", 1440) if lead is None else lead
        notify(
            "任务即将到期",
            f"{task['name']}｜{config.lead_label(lead)}｜截止 {task['due_display']}",
        )
        crud.mark_reminded(task["id"])

    for task in result["overdue"]:
        if task.get("reminded_at"):
            continue
        notify("任务已逾期", f"{task['name']}｜截止 {task['due_display']}｜{task['delta_text']}")
        crud.mark_reminded(task["id"])


def _loop() -> None:
    while _state["running"]:
        try:
            _tick()
        except Exception as exc:  # 兜底，避免后台线程退出
            _state["last_error"] = str(exc)
        time.sleep(max(int(config.load_settings().get("poll_seconds", 60) or 60), 10))


def start() -> None:
    if _state["running"]:
        return
    _state["running"] = True
    t = threading.Thread(target=_loop, name="reminder-daemon", daemon=True)
    t.start()
    _state["thread"] = t


def stop() -> None:
    _state["running"] = False


def status() -> Dict[str, Any]:
    return {
        "running": _state["running"],
        "last_check": _state["last_check"],
        "last_error": _state["last_error"],
        "poll_seconds": config.load_settings().get("poll_seconds", 60),
    }
