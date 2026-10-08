"""工具闸门单测夹具；替身与测试专用工具定义在 `tool_doubles.py`。"""

from __future__ import annotations

import logging

import pytest

from .tool_doubles import GateHarness, build_harness, reset_products


@pytest.fixture(autouse=True)
def reenable_security_logger() -> None:
    """`migrations/env.py` 的 `fileConfig` 默认禁用已存在的 logger：同一进程里只要有用例触发过
    alembic，安全日志就收不到，caplog 断言随跑序变化。与 `tests/unit/llm/conftest.py` 同一处理。
    """

    logging.getLogger("app.security.tools").disabled = False


@pytest.fixture
def harness() -> GateHarness:
    reset_products()
    return build_harness()
