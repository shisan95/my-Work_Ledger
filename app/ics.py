"""系统日历联动：生成标准 .ics 日历文件（含 VALARM 提醒）。

生成的 .ics 可：
1. 直接双击导入 macOS「日历」/ Outlook / 手机日历；
2. 也可以用 /api/calendar/feed.ics 作为订阅地址，实现持续同步。
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Dict, List

from . import config
from .utils import date_part, is_all_day, time_part, to_dt

CAL_NAME = "工作任务台账"


def _escape(text: str) -> str:
    s = str(text or "")
    s = s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
    return s.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\\n")


def _fold(line: str) -> str:
    """RFC5545 行折叠：单行不超过 75 字节。"""
    raw = line.encode("utf-8")
    if len(raw) <= 73:
        return line
    out, cur = [], b""
    for ch in line:
        b = ch.encode("utf-8")
        if len(cur) + len(b) > 73:
            out.append(cur)
            cur = b"\x20" + b
        else:
            cur += b
    out.append(cur)
    return "\r\n".join(x.decode("utf-8") for x in out)


def _stamp(d: dt.datetime) -> str:
    return d.strftime("%Y%m%dT%H%M%S")


def build_ics(tasks: List[Dict[str, Any]], settings: Dict[str, Any] | None = None) -> str:
    settings = settings or config.load_settings()
    default_lead = int(settings.get("default_lead_minutes", 1440) or 0)
    now = dt.datetime.now()

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//WorkBuddy//TaskLedger//CN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:" + _escape(CAL_NAME),
        "X-WR-TIMEZONE:Asia/Shanghai",
        "REFRESH-INTERVAL;VALUE=DURATION:PT30M",
    ]

    for t in tasks:
        due = t.get("due_date") or ""
        start = t.get("start_date") or ""
        if not due and not start:
            continue

        start_dt = to_dt(start) if start else None
        due_dt = to_dt(due) if due else None
        if due_dt is None:
            due_dt = start_dt
        if start_dt is None:
            start_dt = due_dt

        uid = f"task-{t['id']}@task-ledger.local"
        summary = t.get("name") or "未命名任务"
        if t.get("status"):
            summary = f"[{t['status']}] {summary}"

        lines.append("BEGIN:VEVENT")
        lines.append(f"UID:{uid}")
        lines.append("DTSTAMP:" + _stamp(now) + "Z")
        lines.append("CLASS:PUBLIC")

        if is_all_day(due) and is_all_day(start):
            lines.append("DTSTART;VALUE=DATE:" + date_part(start).replace("-", ""))
            end = due_dt + dt.timedelta(days=1)
            lines.append("DTEND;VALUE=DATE:" + end.strftime("%Y%m%d"))
        else:
            lines.append("DTSTART:" + start_dt.strftime("%Y%m%dT%H%M%S"))
            lines.append("DTEND:" + due_dt.strftime("%Y%m%dT%H%M%S"))

        lines.append("SUMMARY:" + _escape(summary))

        desc_parts = []
        if t.get("owner"):
            desc_parts.append(f"负责人：{t['owner']}")
        if t.get("priority"):
            desc_parts.append(f"任务划分：{t['priority']}")
        if t.get("status"):
            desc_parts.append(f"完成状态：{t['status']}")
        if due:
            desc_parts.append("截止时间：" + (date_part(due) + (f" {time_part(due)}" if not is_all_day(due) else "")))
        if t.get("remark"):
            desc_parts.append("备注：" + t["remark"])
        lines.append("DESCRIPTION:" + _escape("\n".join(desc_parts)))

        if t.get("priority"):
            lines.append("CATEGORIES:" + _escape(t["priority"]))
        lines.append("TRANSP:TRANSPARENT")

        # 提醒：与系统日历联动，日历端也会弹出提醒
        if t.get("remind_enabled", True) and due:
            lead = t.get("remind_lead_minutes")
            lead = default_lead if lead is None else int(lead)
            if lead >= 1440 and lead % 1440 == 0:
                trigger = f"-P{lead // 1440}D"
            elif lead >= 60 and lead % 60 == 0:
                trigger = f"-PT{lead // 60}H"
            else:
                trigger = f"-PT{max(lead, 0)}M"
            lines.append("BEGIN:VALARM")
            lines.append("ACTION:DISPLAY")
            lines.append(f"TRIGGER:{trigger}")
            lines.append("DESCRIPTION:" + _escape(f"任务提醒：{t.get('name', '')}"))
            lines.append("END:VALARM")

        lines.append("END:VEVENT")

    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(x) for x in lines) + "\r\n"


def write_ics(tasks: List[Dict[str, Any]], path: str | None = None) -> str:
    settings = config.load_settings()
    target = path or settings.get("ics_path") or config.DEFAULT_ICS_PATH
    directory = target.rsplit("/", 1)[0]
    if directory:
        import os

        os.makedirs(directory, exist_ok=True)
    content = build_ics(tasks, settings)
    with open(target, "w", encoding="utf-8") as f:
        f.write(content)
    return target


def open_in_system_calendar(path: str) -> str:
    """用系统默认程序打开 .ics（macOS 会唤起「日历」导入面板）。"""
    import platform
    import subprocess

    system = platform.system()
    try:
        if system == "Darwin":
            subprocess.Popen(["open", path])
        elif system == "Windows":
            os_startfile = getattr(__import__("os"), "startfile", None)
            if os_startfile:
                os_startfile(path)
        else:
            subprocess.Popen(["xdg-open", path])
        return "已调用系统默认程序打开日历文件"
    except Exception as exc:  # pragma: no cover
        return f"打开失败：{exc}"
