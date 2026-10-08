"""结构化日志配置。"""

from __future__ import annotations

import logging
from collections.abc import Mapping, MutableMapping
from typing import Any, cast

import structlog
from structlog.stdlib import BoundLogger

from app.core.config import AppEnvironment, Settings

REDACTED = "[REDACTED]"

# 键名统一小写、`-` 归一为 `_` 后比较，`X-Session-Id`、`x_session_id` 都会命中。
# 这里只放凭证类键：v1 的 `session_id` 是对话 ID，不是凭证，不在此列。
_SENSITIVE_KEYS = frozenset(
    {
        "x_session_id",
        "session_token",
        "authorization",
        "x_admin_token",
        "cookie",
        "set_cookie",
    }
)


def _is_sensitive_key(key: object) -> bool:
    return isinstance(key, str) and key.lower().replace("-", "_") in _SENSITIVE_KEYS


def _redact(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            key: REDACTED if _is_sensitive_key(key) else _redact(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        # 请求头常以 `[(name, value), ...]` 形式出现（ASGI scope、httpx Headers.items()）。
        redacted = [
            (item[0], REDACTED)
            if isinstance(item, tuple) and len(item) == 2 and _is_sensitive_key(_as_str(item[0]))
            else _redact(item)
            for item in value
        ]
        return type(value)(redacted) if isinstance(value, tuple) else redacted
    return value


def _as_str(value: object) -> object:
    return value.decode("latin-1") if isinstance(value, bytes) else value


def redact_sensitive_values(
    _logger: object, _method_name: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """把会话、Bearer、管理员令牌等凭证替换成占位符，包括嵌套的请求头结构。

    `X-Session-Id` 明文等同于会话本身，一旦进日志，拿到日志的人就能冒充该会话
    （`plans/2026-09-21-n1-session-identity.md` Task 4）。
    """

    for key in list(event_dict):
        event_dict[key] = REDACTED if _is_sensitive_key(key) else _redact(event_dict[key])
    return event_dict


def configure_logging(settings: Settings) -> BoundLogger:
    """配置不包含 Prompt、Token 或经营数据的结构化应用日志。"""

    renderer: structlog.types.Processor
    if settings.app_env is AppEnvironment.PRODUCTION:
        renderer = structlog.processors.JSONRenderer()
    else:
        # 固定纯文本异常栈：rich 的默认格式化会打印局部变量，而守卫依赖的局部变量
        # 里就有明文 `X-Session-Id`。
        renderer = structlog.dev.ConsoleRenderer(
            colors=False, exception_formatter=structlog.dev.plain_traceback
        )

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            redact_sensitive_values,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            renderer,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    return cast(BoundLogger, structlog.get_logger("borough_backend"))
