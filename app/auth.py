"""本机账号与会话管理。

设计要点（单机单用户场景）：
- 首次启动创建本机账号（PBKDF2-SHA256 加盐存储，不存明文）；
- 会话令牌随机生成，仅保存其 SHA-256 摘要，写入 HttpOnly Cookie；
- 「记住我」30 天、否则 12 小时，均在使用中滑动续期；
- 登录失败按来源 IP 限速（5 次/10 分钟，锁 60 秒），防暴力尝试。
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from typing import Any, Dict, Optional, Tuple

from . import config

AUTH_PATH = os.path.join(config.DATA_DIR, "auth.json")
SESSIONS_PATH = os.path.join(config.DATA_DIR, "sessions.json")

COOKIE_NAME = "tl_session"
REMEMBER_DAYS = 30
SHORT_HOURS = 12
ITERATIONS = 200_000

USERNAME_MIN, USERNAME_MAX = 2, 32
PASSWORD_MIN = 6

LOCK = threading.RLock()
_FAILS: Dict[str, list] = {}
MAX_FAILS = 5
FAIL_WINDOW = 600
LOCK_SECONDS = 60


# ---------------------------------------------------------------- 工具
def _now() -> float:
    return time.time()


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _read_json(path: str, fallback: Any) -> Any:
    if not os.path.exists(path):
        return fallback
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return fallback


def _write_json(path: str, data: Any) -> None:
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), ITERATIONS
    ).hex()


# ---------------------------------------------------------------- 账号
def load_account() -> Optional[Dict[str, Any]]:
    data = _read_json(AUTH_PATH, None)
    return data if isinstance(data, dict) and data.get("hash") else None


def is_initialized() -> bool:
    return load_account() is not None


def account_public() -> Dict[str, Any]:
    acc = load_account() or {}
    return {
        "username": acc.get("username", ""),
        "display_name": acc.get("display_name") or acc.get("username", ""),
        "created_at": acc.get("created_at", ""),
    }


def _validate(username: str, password: str) -> None:
    if not (USERNAME_MIN <= len(username) <= USERNAME_MAX):
        raise ValueError(f"用户名需为 {USERNAME_MIN}-{USERNAME_MAX} 个字符")
    if any(ch in username for ch in " \t\r\n/\\<>\"'&="):
        raise ValueError("用户名不能包含空格或特殊字符")
    if len(password) < PASSWORD_MIN:
        raise ValueError(f"密码至少 {PASSWORD_MIN} 位")


def setup_account(username: str, password: str, display_name: str = "") -> Dict[str, Any]:
    """首次创建本机账号。已初始化时拒绝覆盖。"""
    with LOCK:
        if is_initialized():
            raise ValueError("本机账号已创建，请直接登录")
        username = (username or "").strip()
        _validate(username, password or "")
        salt = secrets.token_hex(16)
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        data = {
            "username": username,
            "display_name": (display_name or "").strip() or username,
            "salt": salt,
            "hash": _hash_password(password, salt),
            "iterations": ITERATIONS,
            "created_at": now,
            "updated_at": now,
        }
        _write_json(AUTH_PATH, data)
        return account_public()


def verify_credentials(username: str, password: str) -> bool:
    acc = load_account()
    if not acc:
        return False
    if not hmac.compare_digest(str(acc.get("username", "")), (username or "").strip()):
        return False
    calc = _hash_password(password or "", acc.get("salt", ""))
    return hmac.compare_digest(calc, acc.get("hash", ""))


def change_password(old_password: str, new_password: str) -> None:
    with LOCK:
        acc = load_account()
        if not acc:
            raise ValueError("本机账号尚未创建")
        if not verify_credentials(acc["username"], old_password):
            raise ValueError("当前密码不正确")
        if len(new_password or "") < PASSWORD_MIN:
            raise ValueError(f"新密码至少 {PASSWORD_MIN} 位")
        salt = secrets.token_hex(16)
        acc.update(
            salt=salt,
            hash=_hash_password(new_password, salt),
            updated_at=time.strftime("%Y-%m-%d %H:%M:%S"),
        )
        _write_json(AUTH_PATH, acc)
        destroy_all_sessions()


# ---------------------------------------------------------------- 登录限速
def lock_remaining(ip: str) -> int:
    """返回剩余锁定秒数（0 表示未锁定）。"""
    with LOCK:
        records = [t for t in _FAILS.get(ip, []) if _now() - t < FAIL_WINDOW]
        _FAILS[ip] = records
        if len(records) < MAX_FAILS:
            return 0
        left = int(LOCK_SECONDS - (_now() - records[-1]))
        return max(left, 0)


def record_failure(ip: str) -> None:
    with LOCK:
        _FAILS.setdefault(ip, []).append(_now())


def clear_failures(ip: str) -> None:
    with LOCK:
        _FAILS.pop(ip, None)


# ---------------------------------------------------------------- 会话
def _load_sessions() -> Dict[str, Any]:
    data = _read_json(SESSIONS_PATH, {})
    return data if isinstance(data, dict) else {}


def _save_sessions(data: Dict[str, Any]) -> None:
    _write_json(SESSIONS_PATH, data)


def _ttl(remember: bool) -> int:
    return int((REMEMBER_DAYS * 86400) if remember else (SHORT_HOURS * 3600))


def create_session(remember: bool = True, ua: str = "") -> Tuple[str, int]:
    """创建会话，返回 (明文令牌, 过期时间戳)。明文令牌只返回给客户端一次。"""
    token = secrets.token_urlsafe(32)
    expires = int(_now() + _ttl(remember))
    with LOCK:
        data = _load_sessions()
        # 顺手清理过期会话
        for key in [k for k, v in data.items() if v.get("expires", 0) < _now()]:
            data.pop(key, None)
        data[_sha256(token)] = {
            "username": (load_account() or {}).get("username", ""),
            "remember": bool(remember),
            "created": int(_now()),
            "expires": expires,
            "ua": (ua or "")[:200],
        }
        _save_sessions(data)
    return token, expires


def validate_session(token: str) -> Optional[Dict[str, Any]]:
    """校验会话；有效则滑动续期并返回会话信息。"""
    if not token:
        return None
    key = _sha256(token)
    with LOCK:
        data = _load_sessions()
        item = data.get(key)
        if not item:
            return None
        if item.get("expires", 0) < _now():
            data.pop(key, None)
            _save_sessions(data)
            return None
        # 滑动续期：剩余不足一半时延长
        ttl = _ttl(bool(item.get("remember")))
        if item["expires"] - _now() < ttl / 2:
            item["expires"] = int(_now() + ttl)
            data[key] = item
            _save_sessions(data)
        return {"username": item.get("username", ""), "remember": item.get("remember", True),
                "expires": item["expires"]}


def destroy_session(token: str) -> None:
    if not token:
        return
    with LOCK:
        data = _load_sessions()
        if data.pop(_sha256(token), None) is not None:
            _save_sessions(data)


def destroy_all_sessions() -> None:
    with LOCK:
        _save_sessions({})


def cookie_payload(token: str, remember: bool) -> Dict[str, Any]:
    """统一 Cookie 参数，登录与登出共用，保证属性一致。"""
    payload: Dict[str, Any] = {
        "key": COOKIE_NAME,
        "value": token,
        "httponly": True,
        "samesite": "lax",
        "path": "/",
    }
    if remember and token:
        payload["max_age"] = REMEMBER_DAYS * 86400
    return payload
