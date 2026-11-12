"""全局配置与本地设置持久化。

所有数据默认存放在项目根目录下的 data/ 目录，便于整体备份与迁移。
"""
from __future__ import annotations

import json
import os
import threading
from typing import Any, Dict

# ---------------------------------------------------------------- 目录与路径
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
BACKUP_DIR = os.path.join(DATA_DIR, "backups")
DB_PATH = os.path.join(DATA_DIR, "tasks.db")
SETTINGS_PATH = os.path.join(DATA_DIR, "settings.json")
DEFAULT_ICS_PATH = os.path.join(DATA_DIR, "任务台账.ics")

for _d in (DATA_DIR, BACKUP_DIR):
    os.makedirs(_d, exist_ok=True)

# ---------------------------------------------------------------- 默认设置
DEFAULT_SETTINGS: Dict[str, Any] = {
    # 默认提醒提前量（分钟）。1440 = 提前 1 天
    "default_lead_minutes": 1440,
    # 是否弹出系统桌面通知
    "desktop_notify": True,
    # 后台轮询提醒的间隔（秒）
    "poll_seconds": 60,
    # 点击“稍后提醒”后的顺延分钟数
    "snooze_minutes": 30,
    # 数据变动后自动重新生成 .ics 日历文件
    "auto_export_ics": True,
    # 系统日历同步文件的位置
    "ics_path": DEFAULT_ICS_PATH,
    # 只有这些状态的任务参与到期提醒（已完成的任务不再打扰）
    "remind_statuses": ["未开始", "进行中", "已搁置"],
    # 视为“已完结”的状态，逾期判断时会被排除
    "done_status": "已完成",
    # 列表默认每页条数
    "page_size": 20,
    # 自定义状态颜色（状态名 -> #RRGGBB，缺省使用前端内置配色）
    "status_colors": {},
}

_LOCK = threading.Lock()


def _merge(base: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(base)
    for k, v in (patch or {}).items():
        if k in DEFAULT_SETTINGS:
            out[k] = v
    return out


def load_settings() -> Dict[str, Any]:
    """读取本地设置，缺失项自动回落为默认值。"""
    data: Dict[str, Any] = {}
    if os.path.exists(SETTINGS_PATH):
        try:
            with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f) or {}
        except Exception:
            data = {}
    return _merge(DEFAULT_SETTINGS, data)


def save_settings(patch: Dict[str, Any]) -> Dict[str, Any]:
    """合并并写回设置文件，返回最新设置。"""
    with _LOCK:
        current = load_settings()
        new = _merge(current, patch)
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(new, f, ensure_ascii=False, indent=2)
        return new


# ---------------------------------------------------------------- 提醒提前量选项
LEAD_OPTIONS = [
    {"minutes": 0, "label": "到期时"},
    {"minutes": 10, "label": "提前 10 分钟"},
    {"minutes": 30, "label": "提前 30 分钟"},
    {"minutes": 60, "label": "提前 1 小时"},
    {"minutes": 120, "label": "提前 2 小时"},
    {"minutes": 360, "label": "提前 6 小时"},
    {"minutes": 720, "label": "提前 12 小时"},
    {"minutes": 1440, "label": "提前 1 天"},
    {"minutes": 2880, "label": "提前 2 天"},
    {"minutes": 4320, "label": "提前 3 天"},
    {"minutes": 10080, "label": "提前 1 周"},
]


def lead_label(minutes: int | None) -> str:
    for opt in LEAD_OPTIONS:
        if opt["minutes"] == minutes:
            return opt["label"]
    if minutes is None:
        return "跟随全局默认"
    if minutes % 1440 == 0:
        return f"提前 {minutes // 1440} 天"
    if minutes % 60 == 0:
        return f"提前 {minutes // 60} 小时"
    return f"提前 {minutes} 分钟"
