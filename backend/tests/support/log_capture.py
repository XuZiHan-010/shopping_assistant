"""日志断言的测试辅助。"""

from __future__ import annotations

import logging

APP_LOGGER_NAME = "borough_backend"


def reenable_app_logger() -> None:
    """`migrations/env.py` 调用 `logging.config.fileConfig`
    （默认 `disable_existing_loggers=True`）。同一进程里跑过迁移测试后，
    已存在的应用 logger 会被全局置 `disabled=True`，caplog 收不到日志，断言变得跑序相关。
    生产环境迁移在独立进程执行，不受影响；这里只做测试内的防御性重置
    （同 `tests/unit/llm/conftest.py`、`tests/unit/agent/test_prefilter_logging.py`）。
    """

    logging.getLogger(APP_LOGGER_NAME).disabled = False
