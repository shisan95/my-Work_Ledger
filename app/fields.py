"""字段体系：由表格列自动派生数据结构与界面表单。

设计要点
1. BASE_FIELDS 依据你提供的《任务汇总》表头生成（任务名称/任务划分/完成状态/
   开始时间/结束时间/备注）。其中“任务划分”是四象限优先级。
2. 需求中要求“按负责人筛选”，原表没有该列，因此系统补充 owner 字段（可留空）。
3. 导入任意新表格时，未知列会自动注册为自定义字段（存 extra_json），
   并自动生成列表列与表单控件 —— 无需改代码。
4. 列表采用固定排序（截止日期升序，空日期排最后），不再提供手动排序；
   列表中的字段支持直接点击进行内联编辑（editable 标记）。
"""
from __future__ import annotations

from typing import Any, Dict, List

from .db import list_custom_fields

# ---------------------------------------------------------------- 基础字段
# editable: 是否支持在列表里点击单元格直接编辑
BASE_FIELDS: List[Dict[str, Any]] = [
    {
        "key": "name",
        "label": "任务名称",
        "type": "text",
        "required": True,
        "maxlength": 200,
        "inList": True,
        "filter": True,
        "editable": True,
        "width": 280,
        "placeholder": "请输入任务名称",
        "origin": "表格列",
    },
    {
        "key": "owner",
        "label": "负责人",
        "type": "text",
        "required": False,
        "maxlength": 50,
        "inList": True,
        "filter": True,
        "editable": True,
        "width": 110,
        "placeholder": "原表无此列，可按需要填写",
        "origin": "系统补充",
    },
    {
        "key": "priority",
        "label": "任务划分",
        "type": "select",
        "options": ["重要且紧急", "重要不紧急", "不重要紧急", "不重要不紧急"],
        "required": False,
        "inList": True,
        "filter": True,
        "editable": True,
        "width": 130,
        "placeholder": "请选择优先级象限",
        "origin": "表格列",
        "hint": "按重要/紧急四象限划分",
    },
    {
        "key": "status",
        "label": "完成状态",
        "type": "select",
        "options": ["未开始", "进行中", "已完成", "已搁置"],
        "required": False,
        "inList": True,
        "filter": True,
        "editable": True,
        "width": 110,
        "placeholder": "请选择状态",
        "origin": "表格列",
    },
    {
        "key": "start_date",
        "label": "开始时间",
        "type": "date",
        "required": False,
        "inList": True,
        "filter": True,
        "editable": True,
        "width": 150,
        "origin": "表格列",
    },
    {
        "key": "due_date",
        "label": "结束时间",
        "type": "date",
        "required": False,
        "inList": True,
        "filter": True,
        "editable": True,
        "width": 150,
        "origin": "表格列",
        "hint": "截止日期，用于日历展示与到期提醒",
    },
    {
        "key": "remark",
        "label": "备注",
        "type": "textarea",
        "required": False,
        "maxlength": 2000,
        "inList": True,
        "filter": False,
        "editable": True,
        "width": 240,
        "placeholder": "进展备注、说明等",
        "origin": "表格列",
    },
]

# 非列表/表单基础字段（提醒设置）
REMIND_FIELDS: List[Dict[str, Any]] = [
    {
        "key": "remind_enabled",
        "label": "开启提醒",
        "type": "switch",
        "default": True,
        "inList": False,
    },
    {
        "key": "remind_lead_minutes",
        "label": "提醒提前量",
        "type": "lead",
        "default": None,
        "inList": False,
        "hint": "留空表示跟随全局默认",
    },
]

# ---------------------------------------------------------------- 表头别名映射
# 归一化后的表头 -> 字段 key
ALIASES: Dict[str, str] = {
    # 任务名称
    "任务名称": "name", "任务名": "name", "任务": "name", "事项": "name", "标题": "name",
    "任务标题": "name", "工作内容": "name", "name": "name", "title": "name", "task": "name",
    # 负责人
    "负责人": "owner", "责任人": "owner", "经办人": "owner", "执行人": "owner",
    "负责人员": "owner", "责任人姓名": "owner", "owner": "owner", "assignee": "owner",
    # 优先级 / 任务划分
    "任务划分": "priority", "优先级": "priority", "重要程度": "priority", "紧急程度": "priority",
    "重要紧急": "priority", "象限": "priority", "四象限": "priority", "priority": "priority",
    # 状态
    "完成状态": "status", "状态": "status", "任务状态": "status", "进度状态": "status",
    "完成情况": "status", "status": "status", "state": "status",
    # 开始
    "开始时间": "start_date", "开始日期": "start_date", "起始时间": "start_date",
    "启动时间": "start_date", "开始": "start_date", "startdate": "start_date", "start": "start_date",
    # 截止
    "结束时间": "due_date", "结束日期": "due_date", "截止时间": "due_date", "截止日期": "due_date",
    "到期时间": "due_date", "到期日期": "due_date", "完成时限": "due_date", "deadline": "due_date",
    "要求完成时间": "due_date", "交付时间": "due_date", "duedate": "due_date", "end": "due_date",
    # 备注
    "备注": "remark", "进展备注": "remark", "进展": "remark", "说明": "remark", "描述": "remark",
    "任务描述": "remark", "remark": "remark", "description": "remark", "comment": "remark",
}

_PUNCT = " \t\r\n()（）[]【】/\\-_.:：,，、*·"


def normalize_header(text: str) -> str:
    """归一化表头：去空白与常见标点，便于别名匹配。"""
    s = str(text or "").strip()
    for ch in _PUNCT:
        s = s.replace(ch, "")
    return s.lower()


def match_field(header: str) -> str:
    """返回表头对应的字段 key，未识别返回空串。"""
    if not header:
        return ""
    norm = normalize_header(header)
    if not norm:
        return ""
    if norm in ALIASES:
        return ALIASES[norm]
    # 包含式匹配：例如 “任务开始时间” -> start_date
    for raw, key in ALIASES.items():
        r = normalize_header(raw)
        if len(r) >= 2 and (r in norm or norm in r):
            return key
    return ""


def field_by_key(key: str) -> Dict[str, Any] | None:
    for f in BASE_FIELDS:
        if f["key"] == key:
            return f
    return None


def base_field_by_label(label: str):
    for f in BASE_FIELDS:
        if f["label"] == label:
            return f
    return None


def get_registry() -> List[Dict[str, Any]]:
    """完整字段注册表 = 基础字段 + 导入时自动发现的自定义字段。"""
    fields = [dict(f) for f in BASE_FIELDS]
    try:
        customs = list_custom_fields()
    except Exception:
        customs = []
    for c in customs:
        fields.append(
            {
                "key": f"extra:{c['key']}",
                "label": c["label"],
                "type": c.get("type", "text"),
                "options": c.get("options") or None,
                "required": False,
                "inList": True,
                "filter": False,
                "editable": True,
                "width": 160,
                "origin": "导入新增",
                "custom": True,
            }
        )
    return fields


def list_fields() -> List[Dict[str, Any]]:
    return [f for f in get_registry() if f.get("inList")]


def editable_fields() -> List[Dict[str, Any]]:
    return [f for f in get_registry() if f.get("editable") and f.get("inList")]
