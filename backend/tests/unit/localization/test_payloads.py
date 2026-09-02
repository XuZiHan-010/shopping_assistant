"""会话历史按页本地化（Task 7，§8.6.3）：`localize_conversation_summary()` /
`localize_conversation_detail()` 的单元验收，全部用内存假 `LocalizationService`
替身，不接触数据库或真实 LLM。

真实分页边界（第一页取最新 N 条、`has_more_messages`、游标跨会话/跨商家
校验）在 `tests/integration/repositories/test_conversation_repository.py` 与
`tests/unit/repositories/test_conversation_cursor.py` 里覆盖；本文件只覆盖
"给定当前页数据后如何翻译、如何按条目降级、翻译顺序是否符合可见优先级"。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from app.llm.client import LlmBudget
from app.localization.locales import SupportedLocale
from app.localization.payloads import (
    localize_conversation_detail,
    localize_conversation_summary,
)
from app.models.answer import Answer, Feedback
from app.models.conversation import Conversation, Message
from app.repositories.localization import LocalizationScope
from app.schemas.localization import LocalizeItem

EN_US = SupportedLocale.EN_US
MERCHANT_ID = uuid4()
_NOW = datetime(2026, 8, 31, 12, 0, 0, tzinfo=UTC)


class FakeLocalizationService:
    """记录每次调用收到的 `scope`/`items`,只按预置字典回填翻译结果——未登记
    的 key 缺席,与真实 `LocalizationService` 遇到预算耗尽/校验失败时的行为
    完全一致（缺席而不是回退成原文）。"""

    def __init__(self, translations: dict[str, str] | None = None) -> None:
        self._translations = translations or {}
        self.received_items: list[LocalizeItem] = []
        self.received_scopes: list[LocalizationScope] = []
        self.calls = 0

    async def localize_many(
        self,
        *,
        scope: LocalizationScope,
        items: Sequence[LocalizeItem],
        target_locale: SupportedLocale,
        budget: LlmBudget,
    ) -> dict[str, str]:
        del target_locale, budget
        self.calls += 1
        self.received_scopes.append(scope)
        self.received_items.extend(items)
        return {
            item.key: self._translations[item.key]
            for item in items
            if item.key in self._translations
        }


def _budget() -> LlmBudget:
    return LlmBudget(max_calls=4, max_tokens=12_000)


def _conversation(title: str | None, *, conversation_id: UUID | None = None) -> Conversation:
    return Conversation(
        id=conversation_id or uuid4(),
        merchant_id=MERCHANT_ID,
        title=title,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _message(role: str, content: str, *, message_id: UUID | None = None) -> Message:
    return Message(
        id=message_id or uuid4(),
        merchant_id=MERCHANT_ID,
        conversation_id=uuid4(),
        role=role,
        content=content,
        created_at=_NOW,
        source_locale="zh-CN",
    )


def _answer(response_payload: dict[str, object], *, answer_id: UUID | None = None) -> Answer:
    return Answer(
        id=answer_id or uuid4(),
        merchant_id=MERCHANT_ID,
        conversation_id=uuid4(),
        client_request_id=str(uuid4()),
        request_digest="digest",
        processing_status="SUCCEEDED",
        response_payload=response_payload,
        response_locale="zh-CN",
    )


def _passed_payload(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "answer_mode": "METRIC",
        "thinking_steps": [],
        "quality_status": "PASSED",
        "quality_attempts": 1,
        "quality_notes": [],
        "degraded": False,
        "degraded_reason": None,
        "total_rows": 1,
        "truncated": False,
        "data_rows": [{"col_a": 1}],
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# 会话列表
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_summary_translates_titles_for_exactly_the_given_page() -> None:
    conversation_one = _conversation("标题一")
    conversation_two = _conversation("标题二")
    fake = FakeLocalizationService(
        {
            f"title:{conversation_one.id}": "Title One",
            f"title:{conversation_two.id}": "Title Two",
        }
    )

    summaries, degraded, reason = await localize_conversation_summary(
        service=fake,
        budget=_budget(),
        merchant_id=MERCHANT_ID,
        conversations=[conversation_one, conversation_two],
        target_locale=EN_US,
    )

    assert [item.title for item in summaries] == ["Title One", "Title Two"]
    assert degraded is False
    assert reason is None
    # 只处理调用方给的这两条,不会自行多查其它会话的标题。
    assert {item.key for item in fake.received_items} == {
        f"title:{conversation_one.id}",
        f"title:{conversation_two.id}",
    }
    assert fake.received_scopes[0] == LocalizationScope(kind="MERCHANT", merchant_id=MERCHANT_ID)


@pytest.mark.asyncio
async def test_summary_placeholders_missing_titles_and_never_leaks_source_text() -> None:
    conversation = _conversation("未翻译标题")
    fake = FakeLocalizationService({})  # 什么都不返回,模拟预算耗尽/LLM 不可用

    summaries, degraded, reason = await localize_conversation_summary(
        service=fake,
        budget=_budget(),
        merchant_id=MERCHANT_ID,
        conversations=[conversation],
        target_locale=EN_US,
    )

    assert summaries[0].title == "Translation unavailable — retry"
    assert summaries[0].title != conversation.title
    assert degraded is True
    assert reason is not None


@pytest.mark.asyncio
async def test_summary_skips_conversations_without_a_title() -> None:
    conversation = _conversation(None)
    fake = FakeLocalizationService({})

    summaries, degraded, _ = await localize_conversation_summary(
        service=fake,
        budget=_budget(),
        merchant_id=MERCHANT_ID,
        conversations=[conversation],
        target_locale=EN_US,
    )

    assert summaries[0].title is None
    assert degraded is False
    assert fake.received_items == []


# ---------------------------------------------------------------------------
# 会话详情
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detail_translates_content_and_whitelisted_structured_fields_only() -> None:
    user_message = _message("USER", "最近7天退款金额")
    answer = _answer(
        _passed_payload(
            thinking_steps=[{"label": "识别业务意图", "node": "classify"}],
            quality_notes=["数据来自过去 7 天"],
        )
    )
    feedback = Feedback(
        merchant_id=MERCHANT_ID, answer_id=answer.id, is_adopted=True, reaction="LIKE"
    )
    assistant_message = _message("ASSISTANT", "过去 7 天退款金额合计 1200 元")

    translations = {
        "title": "Refund overview",
        f"message:{user_message.id}:content": "Refund amount over the last 7 days",
        f"message:{assistant_message.id}:content": "Total refunds over the last 7 days: 1200 yuan",
        f"message:{assistant_message.id}:step:0": "Identify business intent",
        f"message:{assistant_message.id}:note:0": "Data covers the last 7 days",
    }
    fake = FakeLocalizationService(translations)

    title, messages, degraded, reason = await localize_conversation_detail(
        service=fake,
        budget=_budget(),
        merchant_id=MERCHANT_ID,
        title="退款概览",
        messages=[user_message, assistant_message],
        answers_by_user_message={user_message.id: (answer, feedback)},
        target_locale=EN_US,
    )

    assert title == "Refund overview"
    assert degraded is False
    assert reason is None
    assert messages[0].content == "Refund amount over the last 7 days"
    assistant_payload = messages[1].answer_payload
    assert assistant_payload is not None
    assert messages[1].content == "Total refunds over the last 7 days: 1200 yuan"
    assert assistant_payload.thinking_steps[0].label == "Identify business intent"
    # `node` 是机内部路由键,不在翻译白名单里,必须原样保留。
    assert assistant_payload.thinking_steps[0].node == "classify"
    assert assistant_payload.quality_notes[0] == "Data covers the last 7 days"
    # 物理列名、枚举协议值、数值一律不翻译。
    assert assistant_payload.columns == ["col_a"]
    assert assistant_payload.answer_mode.value == "METRIC"
    assert assistant_payload.total_rows == 1
    assert assistant_payload.is_adopted is True
    assert assistant_payload.reaction is not None
    assert assistant_payload.reaction.value == "LIKE"


@pytest.mark.asyncio
async def test_detail_placeholders_missing_items_and_flags_degraded_without_leaking_source() -> (
    None
):
    user_message = _message("USER", "上一周的退货率")
    fake = FakeLocalizationService({})  # 全部缺席

    title, messages, degraded, reason = await localize_conversation_detail(
        service=fake,
        budget=_budget(),
        merchant_id=MERCHANT_ID,
        title="退货概览",
        messages=[user_message],
        answers_by_user_message={},
        target_locale=EN_US,
    )

    assert title == "Translation unavailable — retry"
    assert title != "退货概览"
    assert messages[0].content == "Translation unavailable — retry"
    assert messages[0].content != user_message.content
    assert degraded is True
    assert reason is not None


@pytest.mark.asyncio
async def test_detail_leaves_empty_assistant_content_untouched() -> None:
    """纯 DETAIL 回答的 `answer` 是精确空串（R7 之外的既有契约）,空字符串没
    有可翻译内容,不应该被当成"缺席条目"打上占位符或计入降级。"""

    user_message = _message("USER", "导出订单明细")
    assistant_message = _message("ASSISTANT", "")
    fake = FakeLocalizationService({})

    _, messages, degraded, _ = await localize_conversation_detail(
        service=fake,
        budget=_budget(),
        merchant_id=MERCHANT_ID,
        title=None,
        messages=[user_message, assistant_message],
        answers_by_user_message={},
        target_locale=EN_US,
    )

    assert messages[1].content == ""
    # 空正文本身也没被送去翻译。
    empty_content_key = f"message:{assistant_message.id}:content"
    assert all(item.key != empty_content_key for item in fake.received_items)
    # user_message 仍然缺席(未登记翻译),所以整体依然降级——只是空串那一条不算。
    assert degraded is True


@pytest.mark.asyncio
async def test_detail_prioritizes_latest_turn_then_title_then_older_content() -> None:
    """预算先花在用户当下看得见的地方（brief Step 4 原文顺序）：
    最新一轮（正文 + 结构化附属字段）→ 会话标题 → 较早消息正文 → 较早消息
    的结构化附属字段。"""

    user_one = _message("USER", "较早的问题")
    assistant_one = _message("ASSISTANT", "较早的回答")
    answer_one = _answer(_passed_payload(quality_notes=["较早说明"]))
    user_two = _message("USER", "最新的问题")
    assistant_two = _message("ASSISTANT", "最新的回答")
    answer_two = _answer(_passed_payload(quality_notes=["最新说明"]))

    fake = FakeLocalizationService({})  # 内容不重要,只关心调用顺序

    await localize_conversation_detail(
        service=fake,
        budget=_budget(),
        merchant_id=MERCHANT_ID,
        title="会话标题",
        messages=[user_one, assistant_one, user_two, assistant_two],
        answers_by_user_message={
            user_one.id: (answer_one, None),
            user_two.id: (answer_two, None),
        },
        target_locale=EN_US,
    )

    keys = [item.key for item in fake.received_items]
    assert keys == [
        f"message:{assistant_two.id}:content",
        f"message:{assistant_two.id}:note:0",
        "title",
        f"message:{user_two.id}:content",
        f"message:{assistant_one.id}:content",
        f"message:{user_one.id}:content",
        f"message:{assistant_one.id}:note:0",
    ]


@pytest.mark.asyncio
async def test_detail_only_processes_the_page_it_is_given_not_the_full_history() -> None:
    """核心预算护栏：即使这两条消息实际上只是一个 40 条消息会话里的一页,
    本函数也只会看到、只会翻译调用方传进来的这两条——它没有任何途径去多查
    更多历史。这正是"打开 40 条消息的会话不会一次性把整份历史送进翻译预算"
    在 payloads 这一层的证明；分页本身（Repository 每次最多吐出
    `message_limit` 条）在 `tests/integration/repositories/
    test_conversation_repository.py` 与 `tests/unit/repositories/
    test_conversation_cursor.py` 里验收。"""

    page = [_message("USER", "第 21 条消息"), _message("ASSISTANT", "第 22 条消息")]
    fake = FakeLocalizationService({})

    await localize_conversation_detail(
        service=fake,
        budget=_budget(),
        merchant_id=MERCHANT_ID,
        title=None,
        messages=page,
        answers_by_user_message={},
        target_locale=EN_US,
    )

    assert fake.calls == 1
    assert {item.key for item in fake.received_items} == {
        f"message:{page[0].id}:content",
        f"message:{page[1].id}:content",
    }
