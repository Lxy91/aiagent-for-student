"""Bounded diagnostics for an authenticated user's own execution stream."""

import json
import re
from typing import Any

from app.core.errors import AppError

_SECRET_KEYS = {
    "authorization",
    "api_key",
    "apikey",
    "access_token",
    "refresh_token",
    "password",
    "secret",
    "token",
    "cookie",
    "set-cookie",
    "confirmation_token",
}
_SECRET_TEXT = re.compile(
    r"(?i)(bearer\s+)[\w.\-]+|"
    r"((?:api[_-]?key|access_token|refresh_token|password|secret|token)=)[^\s&\"'<>]+"
)


def safe_debug(value: Any, *, depth: int = 0) -> Any:
    if depth > 12:
        return "[嵌套内容已省略]"
    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]"
            if str(key).lower() in _SECRET_KEYS
            else safe_debug(item, depth=depth + 1)
            for key, item in value.items()
            if key != "reasoning_content"
        }
    if isinstance(value, (list, tuple)):
        return [safe_debug(item, depth=depth + 1) for item in value]
    if isinstance(value, str):
        if value.lstrip().startswith(("{", "[")):
            try:
                parsed = json.loads(value)
            except (ValueError, TypeError):
                pass
            else:
                return json.dumps(safe_debug(parsed, depth=depth + 1), ensure_ascii=False)
        redacted = _SECRET_TEXT.sub(lambda match: (match[1] or match[2]) + "[REDACTED]", value)
        return redacted[:24000] + ("\n[诊断文本已截断]" if len(redacted) > 24000 else "")
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return safe_debug(str(value), depth=depth + 1)


def error_diagnostic(exc: AppError) -> dict:
    cause = exc.__cause__
    return safe_debug(
        {
            "code": exc.code,
            "message": exc.message,
            "status": exc.status_code,
            "retryable": exc.retryable,
            "details": exc.details,
            "cause": {"type": type(cause).__name__, "message": str(cause)} if cause else None,
        }
    )
