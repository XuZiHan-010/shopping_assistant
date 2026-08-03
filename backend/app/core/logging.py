"""结构化日志配置。"""

from __future__ import annotations

import logging
from typing import cast

import structlog
from structlog.stdlib import BoundLogger

from app.core.config import AppEnvironment, Settings


def configure_logging(settings: Settings) -> BoundLogger:
    """配置不包含 Prompt、Token 或经营数据的结构化应用日志。"""

    renderer: structlog.types.Processor
    if settings.app_env is AppEnvironment.PRODUCTION:
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=False)

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
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
