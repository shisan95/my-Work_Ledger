"""任务数据访问层：增删改查、筛选、排序、分页、统计。"""
from __future__ import annotations

import datetime as dt
import re
from typing import Any, Dict, List, Optional, Tuple

from . import config, db, fields
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
    "name", "work_content", "owner", "priority", "status", "start_date", "due_date", "remark",
    "remind_enabled", "remind_lead_minutes", "reminded_at", "snooze_until",
}

# ---------------------------------------------------------------- 多值字段
_MULTI_SPLIT = re.compile(r"[|,，、;；/\n]+")


def split_multi(value: Any) -> List[str]:
    """把多值字段（如 "进行中|已完成"）拆成去重后的列表。"""
    if isinstance(value, (list, tuple, set)):
        parts = [str(v) for v in value]
    else:
        parts = _MULTI_SPLIT.split(str(value or ""))
    out: List[str] = []
    for p in parts:
        p = p.strip()
        if p and p not in out:
            out.append(p)
    return out


def join_multi(values: Any, allowed: Optional[List[str]] = None) -> str:
    """把多值选项规范化为存储字符串。

    指定 allowed 时按 options 顺序排列并丢弃非法值（合法性由 validate 先行校验）。
    """
    items = split_multi(values)
    if allowed:
        items = [v for v in allowed if v in items]
    return "|".join(items)


def validate_status(raw: Any) -> None:
    """校验状态取值：非法选项直接报错，避免静默丢弃用户输入。"""
    invalid = [v for v in split_multi(raw) if v not in fields.STATUS_OPTIONS]
    if invalid:
        raise ValueError(f"完成状态包含无效选项：{'、'.join(invalid)}")


def normalize_status(value: Any, default: str = "") -> str:
    """规范化完成状态：支持单值或多值（数组/分隔字符串）。"""
    text = join_multi(value, fields.STATUS_OPTIONS)
    return text or default


def status_list_of(status: Any) -> List[str]:
    return split_multi(status)


def _status_like(value: str) -> str:
    """多值字段的 LIKE 模式：'|进行中|' 匹配 '未开始|进行中'。"""
    return f"%|{value}|%"


# ---------------------------------------------------------------- 行 -> 字典
def task_to_dict(row: Any, settings: Dict[str, Any] | None = None) -> Dict[str, Any]:
    settings = settings or config.load_settings()
    extra = db.decode_extra(row["extra_json"])
    due = row["due_date"] or ""
    status = row["status"] or ""
    status_list = status_list_of(status)
    done_status = settings.get("done_status", "已完成")
    done = done_status in status_list

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

    keys = row.keys()
    content = row["work_content"] if "work_content" in keys else ""

    data: Dict[str, Any] = {
        "id": row["id"],
        "name": row["name"],
        "work_content": content,
        "priority": row["priority"],
        "status": status,
        "status_list": status_list,
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
        clauses.append(
            "(name LIKE ? OR work_content LIKE ? OR remark LIKE ? OR priority LIKE ?)"
        )
        like = f"%{q}%"
        args += [like, like, like, like]

    # 状态为多值字段：任一选中值命中即匹配
    status_values = params.get("status")
    if isinstance(status_values, str):
        status_values = [status_values] if status_values else []
    status_values = [v for v in (status_values or []) if v]
    if status_values:
        ors = []
        for v in status_values:
            ors.append("('|' || status || '|') LIKE ?")
            args.append(_status_like(v))
        clauses.append("(" + " OR ".join(ors) + ")")

    priority_values = params.get("priority")
    if isinstance(priority_values, str):
        priority_values = [priority_values] if priority_values else []
    priority_values = [v for v in (priority_values or []) if v]
    if priority_values:
        clauses.append(f"priority IN ({','.join('?' * len(priority_values))})")
        args += priority_values

    # 兼容旧客户端可能传入的 owner 过滤（字段已下线，仍按名称/内容模糊匹配）
    owner_values = params.get("owner")
    if isinstance(owner_values, str):
        owner_values = [owner_values] if owner_values else []
    owner_values = [v for v in (owner_values or []) if v]
    if owner_values:
        ors = []
        for v in owner_values:
            ors.append("(work_content LIKE ? OR name LIKE ?)")
            args += [f"%{v}%", f"%{v}%"]
        clauses.append("(" + " OR ".join(ors) + ")")

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
        clauses.append("(due_date != '' AND due_date < ? AND ('|' || status || '|') NOT LIKE ?)")
        args += [now_str(), _status_like(done)]
    if params.get("due_soon_only"):
        clauses.append("(due_date != '' AND due_date >= ? AND remind_enabled = 1)")
        args.append(now_str())
    if params.get("remind_only"):
        clauses.append("remind_enabled = 1")

    return (" WHERE " + " AND ".join(clauses)) if clauses else "", args


# 列表采用固定排序：截止日期升序，无截止日期的排在最后，同日期按创建时间倒序
FIXED_ORDER = (
    "ORDER BY CASE WHEN due_date IS NULL OR due_date='' THEN 1 ELSE 0 END, "
    "due_date ASC, created_at DESC"
)


def list_tasks(params: Dict[str, Any]) -> Dict[str, Any]:
    settings = config.load_settings()
    where, args = _build_where(params)

    page = max(int(params.get("page") or 1), 1)
    page_size = int(params.get("page_size") or settings.get("page_size") or 20)
    if page_size == -1:
        page_size = 100000

    with db.get_conn() as conn:
        total = conn.execute(f"SELECT COUNT(*) AS c FROM tasks{where}", args).fetchone()["c"]
        rows = conn.execute(
            f"SELECT * FROM tasks{where} {FIXED_ORDER} LIMIT ? OFFSET ?",
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


def validate_task_values(
    name: str, work_content: str, remark: str, start_date: str, due_date: str,
    status: str = "",
) -> None:
    """基础校验（前端会先校验一次，这里做兜底）。失败抛出 ValueError。"""
    if not str(name or "").strip():
        raise ValueError("任务名称不能为空")
    if len(str(name).strip()) > 200:
        raise ValueError("任务名称不能超过 200 个字")
    if len(str(work_content or "")) > 2000:
        raise ValueError("详细工作内容情况不能超过 2000 个字")
    if len(str(remark or "")) > 2000:
        raise ValueError("备注不能超过 2000 个字")
    if start_date and due_date and start_date[:10] > due_date[:10]:
        raise ValueError("开始时间不能晚于结束时间")
    invalid = [v for v in split_multi(status) if v not in fields.STATUS_OPTIONS]
    if invalid:
        raise ValueError(f"完成状态包含无效选项：{'、'.join(invalid)}")


def create_task(payload: Dict[str, Any]) -> Dict[str, Any]:
    core, extra = _split_payload(payload)
    now = now_str()
    validate_status(core.get("status"))
    record = {
        "name": safe_str(core.get("name")),
        "work_content": safe_str(core.get("work_content")),
        "priority": safe_str(core.get("priority")),
        "status": normalize_status(core.get("status"), default="未开始"),
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
    validate_task_values(
        record["name"], record["work_content"], record["remark"],
        record["start_date"], record["due_date"], record["status"],
    )
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

    fields_map: Dict[str, Any] = {}
    for key in ("name", "work_content", "priority", "remark"):
        if key in core:
            fields_map[key] = safe_str(core.get(key))
    if "status" in core:
        validate_status(core.get("status"))
        fields_map["status"] = normalize_status(core.get("status"))
    if "start_date" in core:
        fields_map["start_date"] = parse_start(core.get("start_date"))
    if "due_date" in core:
        new_due = parse_due(core.get("due_date"))
        fields_map["due_date"] = new_due
        if new_due != row["due_date"]:
            fields_map["reminded_at"] = ""   # 改期后重新提醒
            fields_map["snooze_until"] = ""
    if "remind_enabled" in core:
        fields_map["remind_enabled"] = 1 if core.get("remind_enabled") else 0
    if "remind_lead_minutes" in core:
        fields_map["remind_lead_minutes"] = _as_int(core.get("remind_lead_minutes"))
        fields_map["reminded_at"] = ""
    if "reminded_at" in core:
        fields_map["reminded_at"] = safe_str(core.get("reminded_at"))
    if "snooze_until" in core:
        fields_map["snooze_until"] = safe_str(core.get("snooze_until"))
    if extra:
        fields_map["extra_json"] = _dump(merged_extra)

    if not fields_map:
        return get_task(task_id)

    validate_task_values(
        fields_map.get("name", row["name"]),
        fields_map.get("work_content", row["work_content"] if "work_content" in row.keys() else ""),
        fields_map.get("remark", row["remark"]),
        fields_map.get("start_date", row["start_date"]),
        fields_map.get("due_date", row["due_date"]),
        fields_map.get("status", row["status"]),
    )

    fields_map["updated_at"] = now_str()
    set_sql = ",".join(f"{k}=?" for k in fields_map)
    with db._WRITE_LOCK, db.get_conn() as conn:
        conn.execute(f"UPDATE tasks SET {set_sql} WHERE id=?", list(fields_map.values()) + [task_id])
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
    """筛选项：状态取固定选项（多值字段），划分取已有数据去重。"""
    with db.get_conn() as conn:
        priorities = [r[0] for r in conn.execute(
            "SELECT DISTINCT priority FROM tasks WHERE priority != '' ORDER BY priority").fetchall()]
    return {
        "status": list(fields.STATUS_OPTIONS),
        "priority": priorities,
        "owner": [],   # 负责人字段已下线，保留空数组兼容旧客户端
    }


def stats() -> Dict[str, Any]:
    settings = config.load_settings()
    done = settings.get("done_status", "已完成")
    now = now_str()
    with db.get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) c FROM tasks").fetchone()["c"]
        status_rows = [r[0] for r in conn.execute("SELECT status FROM tasks").fetchall()]
        by_priority = {r[0]: r[1] for r in conn.execute(
            "SELECT priority, COUNT(*) FROM tasks WHERE priority != '' GROUP BY priority").fetchall()}
        filled = conn.execute(
            "SELECT COUNT(*) c FROM tasks WHERE work_content != ''").fetchone()["c"]
        overdue = conn.execute(
            "SELECT COUNT(*) c FROM tasks WHERE due_date != '' AND due_date < ? "
            "AND ('|' || status || '|') NOT LIKE ?",
            (now, _status_like(done))).fetchone()["c"]
        no_due = conn.execute("SELECT COUNT(*) c FROM tasks WHERE due_date = ''").fetchone()["c"]
        week_tasks = conn.execute(
            "SELECT COUNT(*) c FROM tasks WHERE due_date != '' AND due_date >= ? AND due_date <= ?",
            (now, (dt.datetime.now() + dt.timedelta(days=7)).strftime(DATE_FMT)),
        ).fetchone()["c"]

    # 多选状态：同一任务在每个勾选状态中分别计数
    by_status: Dict[str, int] = {}
    done_count = 0
    for raw in status_rows:
        items = status_list_of(raw) or ["未填写"]
        if done in items:
            done_count += 1
        for s in items:
            by_status[s] = by_status.get(s, 0) + 1

    return {
        "total": total,
        "by_status": by_status,
        "by_priority": by_priority,
        "work_content": {"已填写": filled, "未填写": total - filled},
        "overdue": overdue,
        "no_due": no_due,
        "week": week_tasks,
        "done": done_count,
        "done_rate": round(done_count / total * 100, 1) if total else 0,
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
