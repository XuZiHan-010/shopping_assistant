"""`ConversationRepository.create_processing_answer()` 的纯单元测试
（Finding 1，全分支复审）。

`answers.response_locale` 是 NOT NULL 且没有 `default=`/`server_default=`
的列（见 `app/models/answer.py`），只有真实 PostgreSQL 在 flush/commit 时
才会真正拒绝空值——本地 Docker/PostgreSQL 长期不可用，真正触发 CHECK/
NOT NULL 的集成测试见
`tests/integration/repositories/test_chat_repository.py::test_create_processing_answer_writes_a_check_constraint_valid_response_locale`。

这里用一个只实现 `add()`/`flush()` 的假 Session，绕开对真实数据库的依赖，
直接断言 `create_processing_answer()` 返回的 `Answer.response_locale` 在
方法返回时已经是 CHECK 约束允许的取值——这是即使没有真实基础设施也能在
这台机器上跑通的最小复现:改动前该属性是 `None`（模型没有 Python 端默认
值，`None` 不在 CHECK 允许的四个取值里），改动后是 `"und"`。
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from app.models.answer import Answer
from app.repositories.conversation import ConversationRepository

_VALID_RESPONSE_LOCALES = {"zh-CN", "en-US", "mixed", "und"}


class _FakeAsyncSession:
    """只实现 `create_processing_answer()` 实际用到的两个方法。"""

    def __init__(self) -> None:
        self.added: list[Any] = []

    def add(self, instance: Any) -> None:
        self.added.append(instance)

    async def flush(self) -> None:
        return None


@pytest.mark.asyncio
async def test_create_processing_answer_sets_a_check_constraint_valid_response_locale() -> None:
    session = _FakeAsyncSession()
    repository = ConversationRepository(session)  # type: ignore[arg-type]

    answer = await repository.create_processing_answer(
        uuid4(),
        uuid4(),
        uuid4(),
        "client-request-1",
        "c" * 64,
    )

    assert isinstance(answer, Answer)
    assert session.added == [answer]
    assert answer.response_locale is not None
    assert answer.response_locale in _VALID_RESPONSE_LOCALES
    # 写入这一刻回答正文还不存在，真实语言无从判断；`und`（undetermined）是
    # CHECK 约束里专门为这种场景保留的占位，`mark_answer_succeeded()` 之后
    # 才会用探测到的真实语言覆盖它——不能默认写 `zh-CN`,那会把英文/混合
    # 回答尚未生成前的这一刻错误地永久标成中文（如果后续失败,行会停留在
    # `FAILED_*`,`response_locale` 也不会再被覆盖）。
    assert answer.response_locale == "und"
