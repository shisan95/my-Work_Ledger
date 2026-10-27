"""任务数据访问层：增删改查、筛选、排序、分页、统计。"""
from __future__ import annotations

import datetime as dt
from typing import Any, Dict, List, Optional, Tuple

from . import config, db
from .utils import (
    DATE_FMT,
    date_part,
    display_date,
    human_delta,
    now_str,
    parse_due,
    parse_start,
    safe_str,
    to_dt,
)

CORE_KEYS = {
    "name", "owner", "priority", "status", "start_date", "due_date", "remark",
    "remind_enabled", "remind_lead_minutes", "reminded_at", "snooze_until",
}


# ---------------------------------------------------------------- 行 -> 字典
def task_to_dict(row: Any, settings: Dict[str, Any] | None = None) -> Dict[str, Any]:
    settings = settings or config.load_settings()
    extra = db.decode_extra(row["extra_json"])
    due = row["due_date"] or ""
    status = row["status"] or ""
    done = status == settings.get("done_status", "已完成")

    lead = row["remind_lead_minutes"]
    lead = settings.get("default_lead_minutes", 1440) if lead is None else lead
    remind_at = ""
    due_dt = to_dt(due)
    if due_dt is not None and row["remind_enabled"]:
        remind_at = (due_dt - dt.timedelta(minutes=int(lead or 0))).strftime(DATE_FMT)

    overdue = bool(due_dt and due_dt < dt.datetime.now() and not done)
    due_soon = False
    if due_dt and not done and not overdue and remind_at:
        ra = to_dt(remind_at)
        due_soon = bool(ra and ra <= dt.datetime.now())

    data: Dict[str, Any] = {
        "id": row["id"],
        "name": row["name"],
        "owner": row["owner"],
        "priority": row["priority"],
        "status": status,
        "start_date": row["start_date"],
        "due_date": due,
        "remark": row["remark"],
        "remind_enabled": bool(row["remind_enabled"]),
        "remind_lead_minutes": row["remind_lead_minutes"],
        "remind_at": remind_at,
        "remind_label": config.lead_label(row["remind_lead_minutes"]),
        "reminded_at": row["reminded_at"],
        "snooze_until": row["snooze_until"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "start_display": display_date(row["start_date"]),
        "due_display": display_date(due),
        "due_date_only": date_part(due),
        "is_overdue": overdue,
        "is_due_soon": due_soon,
        "is_done": done,
        "delta_text": (human_delta(due) if (due and not done) else ""),
    }
    for k, v in extra.items():
        data[f"extra:{k}"] = v
    return data


# ---------------------------------------------------------------- 查询
def _build_where(params: Dict[str, Any]) -> Tuple[str, List[Any]]:
    clauses: List[str] = []
    args: List[Any] = []

    q = (params.get("q") or "").strip()
    if q:
        clauses.append("(name LIKE ? OR owner LIKE ? OR remark LIKE ? OR priority LIKE ?)")
        like = f"%{q}%"
        args += [like, like, like, like]

    for key in ("owner", "status", "priority"):
        values = params.get(key)
        if isinstance(values, str):
            values = [values] if values else []
        values = [v for v in (values or []) if v]
        if values:
            clauses.append(f"{key} IN ({','.join('?' * len(values))})")
            args += values

    if params.get("start_from"):
        clauses.append("(start_date != '' AND start_date >= ?)")
        args.append(params["start_from"])
    if params.get("start_to"):
        clauses.append("(start_date != '' AND start_date <= ?)")
        args.append(f"{params['start_to']} 23:59")
    if params.get("due_from"):
        clauses.append("(due_date != '' AND due_date >= ?)")
        args.append(f"{params['due_from']} 00:00")
    if params.get("due_to"):
        clauses.append("(due_date != '' AND due_date <= ?)")
        args.append(f"{params['due_to']} 23:59")

    if params.get("overdue_only"):
        settings = config.load_settings()
        done = settings.get("done_status", "已完成")
        clauses.append("(due_date != '' AND due_date < ? AND status != ?)")
        args += [now_str(), done]
    if params.get("due_soon_only"):
        clauses.append("(due_date != '' AND due_date >= ? AND remind_enabled = 1)")
        args.append(now_str())
    if params.get("remind_only"):
        clauses.append("remind_enabled = 1")

    return (" WHERE " + " AND ".join(clauses)) if clauses else "", args


SORTABLE = {
    "name", "owner", "priority", "status", "start_date", "due_date",
    "created_at", "updated_at", "id", "remark",
}


def list_tasks(params: Dict[str, Any]) -> Dict[str, Any]:
    settings = config.load_settings()
    where, args = _build_where(params)

    sort = params.get("sort") or "due_date"
    if sort not in SORTABLE:
        sort = "due_date"
    order = "DESC" if str(params.get("order", "asc")).lower() == "desc" else "ASC"
    # 空值恒排在最后，避免列表头部一片空白
    order_sql = f"ORDER BY CASE WHEN {sort} IS NULL OR {sort}='' THEN 1 ELSE 0 END, {sort} {order}"

    page = max(int(params.get("page") or 1), 1)
    page_size = int(params.get("page_size") or settings.get("page_size") or 20)
    if page_size == -1:
        page_size = 100000

    with db.get_conn() as conn:
        total = conn.execute(f"SELECT COUNT(*) AS c FROM tasks{where}", args).fetchone()["c"]
        rows = conn.execute(
            f"SELECT * FROM tasks{where} {order_sql} LIMIT ? OFFSET ?",
            args + [page_size, (page - 1) * page_size],
        ).fetchall()

    items = [task_to_dict(r, settings) for r in rows]
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "page_count": (total + page_size - 1) // page_size if page_size > 0 else 1,
    }


def list_all(params: Dict[str, Any] | None = None) -> List[Dict[str, Any]]:
    params = dict(params or {})
    params["page_size"] = -1
    return list_tasks(params)["items"]


def get_task(task_id: int) -> Optional[Dict[str, Any]]:
    with db.get_conn() as conn:
        row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    return task_to_dict(row) if row else None


def get_raw(task_id: int):
    with db.get_conn() as conn:
        return conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()


# ---------------------------------------------------------------- 写入
def _split_payload(payload: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """拆成核心字段与自定义字段(extra)。"""
    core: Dict[str, Any] = {}
    extra: Dict[str, Any] = {}
    for k, v in payload.items():
        if k.startswith("extra:"):
            extra[k[6:]] = safe_str(v)
        elif k in CORE_KEYS:
            core[k] = v
    return core, extra


def create_task(payload: Dict[str, Any]) -> Dict[str, Any]:
    core, extra = _split_payload(payload)
    now = now_str()
    record = {
        "name": safe_str(core.get("name")),
        "owner": safe_str(core.get("owner")),
        "priority": safe_str(core.get("priority")),
        "status": safe_str(core.get("status")) or "未开始",
        "start_date": parse_start(core.get("start_date")),
        "due_date": parse_due(core.get("due_date")),
        "remark": safe_str(core.get("remark")),
        "remind_enabled": 1 if core.get("remind_enabled", True) else 0,
        "remind_lead_minutes": _as_int(core.get("remind_lead_minutes")),
        "reminded_at": "",
        "snooze_until": "",
        "extra_json": _dump(extra),
        "created_at": now,
        "updated_at": now,
    }
    cols = ",".join(record.keys())
    marks = ",".join("?" * len(record))
    with db._WRITE_LOCK, db.get_conn() as conn:
        cur = conn.execute(f"INSERT INTO tasks({cols}) VALUES({marks})", list(record.values()))
        conn.commit()
        tid = cur.lastrowid
    return get_task(tid)


def update_task(task_id: int, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    row = get_raw(task_id)
    if row is None:
        return None
    core, extra = _split_payload(payload)

    merged_extra = db.decode_extra(row["extra_json"])
    merged_extra.update(extra)

    fields: Dict[str, Any] = {}
    for key in ("name", "owner", "priority", "status", "remark"):
        if key in core:
            fields[key] = safe_str(core.get(key))
    if "start_date" in core:
        fields["start_date"] = parse_start(core.get("start_date"))
    if "due_date" in core:
        new_due = parse_due(core.get("due_date"))
        fields["due_date"] = new_due
        if new_due != row["due_date"]:
            fields["reminded_at"] = ""   # 改期后重新提醒
            fields["snooze_until"] = ""
    if "remind_enabled" in core:
        fields["remind_enabled"] = 1 if core.get("remind_enabled") else 0
    if "remind_lead_minutes" in core:
        fields["remind_lead_minutes"] = _as_int(core.get("remind_lead_minutes"))
        fields["reminded_at"] = ""
    if "reminded_at" in core:
        fields["reminded_at"] = safe_str(core.get("reminded_at"))
    if "snooze_until" in core:
        fields["snooze_until"] = safe_str(core.get("snooze_until"))
    if extra:
        fields["extra_json"] = _dump(merged_extra)

    if not fields:
        return get_task(task_id)

    fields["updated_at"] = now_str()
    set_sql = ",".join(f"{k}=?" for k in fields)
    with db._WRITE_LOCK, db.get_conn() as conn:
        conn.execute(f"UPDATE tasks SET {set_sql} WHERE id=?", list(fields.values()) + [task_id])
        conn.commit()
    return get_task(task_id)


def delete_task(task_id: int) -> bool:
    with db._WRITE_LOCK, db.get_conn() as conn:
        cur = conn.execute("DELETE FROM tasks WHERE id=?", (task_id,))
        conn.commit()
    return cur.rowcount > 0


def bulk_delete(ids: List[int]) -> int:
    if not ids:
        return 0
    marks = ",".join("?" * len(ids))
    with db._WRITE_LOCK, db.get_conn() as conn:
        cur = conn.execute(f"DELETE FROM tasks WHERE id IN ({marks})", ids)
        conn.commit()
    return cur.rowcount


def clear_all() -> int:
    with db._WRITE_LOCK, db.get_conn() as conn:
        cur = conn.execute("DELETE FROM tasks")
        conn.commit()
    return cur.rowcount


def mark_reminded(task_id: int) -> None:
    with db._WRITE_LOCK, db.get_conn() as conn:
        conn.execute("UPDATE tasks SET reminded_at=? WHERE id=?", (now_str(), task_id))
        conn.commit()


# ---------------------------------------------------------------- 选项与统计
def options() -> Dict[str, List[str]]:
    with db.get_conn() as conn:
        owners = [r[0] for r in conn.execute(
            "SELECT DISTINCT owner FROM tasks WHERE owner != '' ORDER BY owner").fetchall()]
        statuses = [r[0] for r in conn.execute(
            "SELECT DISTINCT status FROM tasks WHERE status != '' ORDER BY status").fetchall()]
        priorities = [r[0] for r in conn.execute(
            "SELECT DISTINCT priority FROM tasks WHERE priority != '' ORDER BY priority").fetchall()]
    return {"owner": owners, "status": statuses, "priority": priorities}


def stats() -> Dict[str, Any]:
    settings = config.load_settings()
    done = settings.get("done_status", "已完成")
    now = now_str()
    with db.get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) c FROM tasks").fetchone()["c"]
        by_status = {r[0]: r[1] for r in conn.execute(
            "SELECT status, COUNT(*) FROM tasks GROUP BY status").fetchall()}
        by_priority = {r[0]: r[1] for r in conn.execute(
            "SELECT priority, COUNT(*) FROM tasks WHERE priority != '' GROUP BY priority").fetchall()}
        by_owner = {r[0]: r[1] for r in conn.execute(
            "SELECT owner, COUNT(*) FROM tasks WHERE owner != '' GROUP BY owner ORDER BY 2 DESC").fetchall()}
        overdue = conn.execute(
            "SELECT COUNT(*) c FROM tasks WHERE due_date != '' AND due_date < ? AND status != ?",
            (now, done)).fetchone()["c"]
        no_due = conn.execute("SELECT COUNT(*) c FROM tasks WHERE due_date = ''").fetchone()["c"]
        week_tasks = conn.execute(
            "SELECT COUNT(*) c FROM tasks WHERE due_date != '' AND due_date >= ? AND due_date <= ?",
            (now, (dt.datetime.now() + dt.timedelta(days=7)).strftime(DATE_FMT)),
        ).fetchone()["c"]
    return {
        "total": total,
        "by_status": by_status,
        "by_priority": by_priority,
        "by_owner": by_owner,
        "overdue": overdue,
        "no_due": no_due,
        "week": week_tasks,
        "done": by_status.get(done, 0),
        "done_rate": round(by_status.get(done, 0) / total * 100, 1) if total else 0,
    }


# ---------------------------------------------------------------- 内部工具
def _as_int(v: Any) -> Optional[int]:
    if v is None or v == "":
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _dump(extra: Dict[str, Any]) -> str:
    import json

    return json.dumps(extra or {}, ensure_ascii=False)
