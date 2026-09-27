from __future__ import annotations

import logging

import pytest

from app.core.config import Settings
from tests.unit.llm._transport import make_settings

# 会在失败时写 `llm_upstream_failed` 的 logger；测试用 caplog 断言这条日志不含密钥。
_LLM_LOGGERS = ("app.llm.adapter_support", "app.llm.deepseek")


@pytest.fixture(autouse=True)
def reenable_llm_loggers() -> None:
    """`migrations/env.py` 调用 `logging.config.fileConfig`（默认
    `disable_existing_loggers=True`）。同一进程里只要有任何用例触发过 alembic，此前已创建的
    logger 就被全局置 `disabled=True`，caplog 收不到日志——日志断言随之变得跑序相关：
    单独跑通过，全量套件里失败。这是测试基础设施的既有环境问题（`test_prefilter_logging.py`
    对 `app.agent.graph` 做过同样的防御性重置），这里统一处理，不让每个用例各写一遍。
    """

    for name in _LLM_LOGGERS:
        logging.getLogger(name).disabled = False


@pytest.fixture
def settings() -> Settings:
    """已配置 `LLM_API_KEY` 的默认设置：openai 协议、思考模式关闭。"""

    return make_settings()
