"""通用工具：日期解析与格式化、文本处理。

日期在数据库与接口中统一使用字符串 "YYYY-MM-DD HH:MM" 表示；
若只有日期没有时间，开始时间补 00:00，截止时间补 23:59（便于“当天不算逾期”）。
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Any, Optional

DATE_FMT = "%Y-%m-%d %H:%M"
DAY_FMT = "%Y-%m-%d"

_CANDIDATE_FMTS = [
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
    "%Y/%m/%d %H:%M:%S",
    "%Y/%m/%d %H:%M",
    "%Y/%m/%d",
    "%Y.%m.%d %H:%M",
    "%Y.%m.%d",
    "%Y年%m月%d日 %H:%M",
    "%Y年%m月%d日",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M",
    "%Y%m%d%H%M",
    "%Y%m%d",
]

# 只有日期、没有时刻的格式：解析后需要补默认时刻
_DATE_ONLY_FMTS = {
    "%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y年%m月%d日", "%Y%m%d",
}

_EXCEL_EPOCH = dt.datetime(1899, 12, 30)


def now_str() -> str:
    return dt.datetime.now().strftime(DATE_FMT)


def today_str() -> str:
    return dt.datetime.now().strftime(DAY_FMT)


def parse_datetime(value: Any, default_time: str = "00:00") -> str:
    """把任意来源的值解析为 "YYYY-MM-DD HH:MM"，失败返回空串。"""
    if value is None or value == "":
        return ""
    if isinstance(value, dt.datetime):
        return value.strftime(DATE_FMT)
    if isinstance(value, dt.date):
        return f"{value.strftime(DAY_FMT)} {default_time}"

    # Excel 序列号（单元格未转成日期时会出现）
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        num = float(value)
        if 20000 < num < 80000:
            return (_EXCEL_EPOCH + dt.timedelta(days=num)).strftime(DATE_FMT)
        value = str(int(num)) if float(value).is_integer() else str(value)

    text = str(value).strip()
    if not text:
        return ""

    # 2026-10-27 10:30:00.0 / 2026-10-27T10:30
    text = text.replace("T", " ").replace("　", " ").strip()
    text = re.sub(r"\.\d+$", "", text)  # 去掉秒的小数
    text = re.sub(r"\s+", " ", text)

    for fmt in _CANDIDATE_FMTS:
        try:
            parsed = dt.datetime.strptime(text, fmt)
        except ValueError:
            continue
        if fmt in _DATE_ONLY_FMTS:
            return f"{parsed.strftime(DAY_FMT)} {default_time}"
        return parsed.strftime(DATE_FMT)

    # 退而求其次：只抓出年月日
    m = re.search(r"(\d{4})[-/.年](\d{1,2})[-/.月](\d{1,2})", text)
    if m:
        y, mo, d = (int(x) for x in m.groups())
        try:
            base = dt.datetime(y, mo, d)
        except ValueError:
            return ""
        tm = re.search(r"(\d{1,2}):(\d{2})", text)
        if tm:
            base = base.replace(hour=int(tm.group(1)), minute=int(tm.group(2)))
            return base.strftime(DATE_FMT)
        return f"{base.strftime(DAY_FMT)} {default_time}"
    return ""


def parse_start(value: Any) -> str:
    return parse_datetime(value, default_time="00:00")


def parse_due(value: Any) -> str:
    return parse_datetime(value, default_time="23:59")


def to_dt(value: str) -> Optional[dt.datetime]:
    if not value:
        return None
    try:
        return dt.datetime.strptime(value, DATE_FMT)
    except ValueError:
        try:
            return dt.datetime.strptime(value, DAY_FMT)
        except ValueError:
            return None


def date_part(value: str) -> str:
    return value[:10] if value else ""


def time_part(value: str) -> str:
    return value[11:16] if len(value) >= 16 else ""


def is_all_day(value: str) -> bool:
    """00:00（开始）或 23:59（截止）视为“未指定具体时刻”。"""
    return time_part(value) in ("00:00", "23:59", "")


def display_date(value: str) -> str:
    """展示用：未指定时刻时只显示日期。"""
    if not value:
        return ""
    return date_part(value) if is_all_day(value) else f"{date_part(value)} {time_part(value)}"


def human_delta(value: str) -> str:
    """距离截止还有多久 / 已逾期多久。"""
    target = to_dt(value)
    if not target:
        return ""
    delta = target - dt.datetime.now()
    seconds = delta.total_seconds()
    abs_s = abs(seconds)
    days = int(abs_s // 86400)
    hours = int((abs_s % 86400) // 3600)
    minutes = int((abs_s % 3600) // 60)
    if days > 0:
        core = f"{days} 天" + (f" {hours} 小时" if hours else "")
    elif hours > 0:
        core = f"{hours} 小时" + (f" {minutes} 分钟" if minutes else "")
    else:
        core = f"{max(minutes, 0)} 分钟"
    return (f"已逾期 {core}" if seconds < 0 else f"剩余 {core}")


def slug(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "")).strip()


def safe_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dt.datetime, dt.date)):
        return parse_datetime(value)
    return str(value).strip()
