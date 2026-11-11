"""SQLite 本地持久化：建库、建表、轻量迁移。"""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional

from .config import DB_PATH

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    name                TEXT NOT NULL DEFAULT '',
    work_content        TEXT NOT NULL DEFAULT '',
    owner               TEXT NOT NULL DEFAULT '',
    priority            TEXT NOT NULL DEFAULT '',
    status              TEXT NOT NULL DEFAULT '未开始',
    start_date          TEXT NOT NULL DEFAULT '',
    due_date            TEXT NOT NULL DEFAULT '',
    remark              TEXT NOT NULL DEFAULT '',
    remind_enabled      INTEGER NOT NULL DEFAULT 1,
    remind_lead_minutes INTEGER,
    reminded_at         TEXT NOT NULL DEFAULT '',
    snooze_until        TEXT NOT NULL DEFAULT '',
    extra_json          TEXT NOT NULL DEFAULT '{}',
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS custom_fields (
    key     TEXT PRIMARY KEY,
    label   TEXT NOT NULL,
    type    TEXT NOT NULL DEFAULT 'text',
    options TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS meta (
    k TEXT PRIMARY KEY,
    v TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_tasks_due     ON tasks(due_date);
CREATE INDEX IF NOT EXISTS idx_tasks_status  ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_owner   ON tasks(owner);
CREATE INDEX IF NOT EXISTS idx_tasks_start   ON tasks(start_date);
"""

_WRITE_LOCK = threading.Lock()


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    """获取数据库连接（上下文管理器）。

    注意：sqlite3.Connection 自身作为上下文管理器时只提交/回滚事务、
    并不会关闭连接，长期运行会泄漏文件描述符，最终导致
    "unable to open database file"（进程表现为假死）。此处保证退出时关闭。
    """
    conn = sqlite3.connect(DB_PATH, timeout=15, check_same_thread=False)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with _WRITE_LOCK, get_conn() as conn:
        conn.executescript(_SCHEMA)
        _migrate(conn)
        conn.commit()


def _migrate(conn: sqlite3.Connection) -> None:
    """轻量迁移：补列 + 旧字段数据转存。

    v1.4.0 起「负责人」字段被「详细工作内容情况」(work_content) 取代，
    旧数据一次性转入新字段，避免信息丢失（可用 meta 标记保证只执行一次）。
    """
    cols = {r[1] for r in conn.execute("PRAGMA table_info(tasks)").fetchall()}
    if "work_content" not in cols:
        conn.execute("ALTER TABLE tasks ADD COLUMN work_content TEXT NOT NULL DEFAULT ''")
    done = conn.execute("SELECT v FROM meta WHERE k='migrated_work_content'").fetchone()
    if not done:
        conn.execute(
            "UPDATE tasks SET work_content = owner WHERE owner <> '' AND work_content = ''"
        )
        conn.execute(
            "INSERT INTO meta(k,v) VALUES('migrated_work_content','1') "
            "ON CONFLICT(k) DO UPDATE SET v='1'"
        )


# ---------------------------------------------------------------- 自定义字段
def list_custom_fields() -> List[Dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT key, label, type, options FROM custom_fields ORDER BY rowid"
        ).fetchall()
    out = []
    for r in rows:
        opts = r["options"]
        out.append(
            {
                "key": r["key"],
                "label": r["label"],
                "type": r["type"],
                "options": [x for x in opts.split("|") if x] if opts else [],
            }
        )
    return out


def upsert_custom_field(key: str, label: str, ftype: str = "text", options: Optional[List[str]] = None) -> None:
    with _WRITE_LOCK, get_conn() as conn:
        conn.execute(
            "INSERT INTO custom_fields(key,label,type,options) VALUES(?,?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET label=excluded.label, type=excluded.type, options=excluded.options",
            (key, label, ftype, "|".join(options or [])),
        )
        conn.commit()


# ---------------------------------------------------------------- meta
def get_meta(k: str, default: str = "") -> str:
    with get_conn() as conn:
        row = conn.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
    return row["v"] if row else default


def set_meta(k: str, v: str) -> None:
    with _WRITE_LOCK, get_conn() as conn:
        conn.execute(
            "INSERT INTO meta(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
            (k, v),
        )
        conn.commit()


# ---------------------------------------------------------------- 备份
def backup(tag: str = "") -> str:
    """把当前数据库复制一份到 data/backups/，返回备份文件路径。"""
    import datetime as dt
    import os
    import shutil

    from .config import BACKUP_DIR

    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    name = f"tasks-{stamp}{('-' + tag) if tag else ''}.db"
    target = os.path.join(BACKUP_DIR, name)
    with _WRITE_LOCK:
        src = sqlite3.connect(DB_PATH)
        dst = sqlite3.connect(target)
        src.backup(dst)
        dst.close()
        src.close()
    # 只保留最近 10 份备份
    files = sorted(
        (os.path.join(BACKUP_DIR, f) for f in os.listdir(BACKUP_DIR) if f.endswith(".db")),
        key=os.path.getmtime,
        reverse=True,
    )
    for f in files[10:]:
        try:
            os.remove(f)
        except OSError:
            pass
    return target


def decode_extra(raw: str) -> Dict[str, Any]:
    try:
        return json.loads(raw or "{}")
    except Exception:
        return {}
