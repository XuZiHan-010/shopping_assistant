"""Chat Repository 的 PostgreSQL 集成测试。"""

from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.merchant import Merchant
from app.repositories.conversation import ConversationRepository

MERCHANT_ONE_ID = UUID("00000000-0000-0000-0000-000000000011")
MERCHANT_TWO_ID = UUID("00000000-0000-0000-0000-000000000012")


async def _insert_merchants(session: AsyncSession) -> None:
    session.add_all(
        [
            Merchant(
                id=MERCHANT_ONE_ID,
                merchant_code="borough-chat-100",
                display_name="Borough商家100",
            ),
            Merchant(
                id=MERCHANT_TWO_ID,
                merchant_code="borough-chat-101",
                display_name="Borough商家101",
            ),
        ]
    )
    await session.flush()


@pytest.mark.asyncio
async def test_answer_idempotency_lookup_is_scoped_to_merchant(
    db_session: AsyncSession,
) -> None:
    await _insert_merchants(db_session)
    repository = ConversationRepository(db_session)
    conversation = await repository.create(MERCHANT_ONE_ID, "商家一会话")
    message = await repository.create_message(MERCHANT_ONE_ID, conversation.id, "USER", "昨天 GMV")
    answer = await repository.create_processing_answer(
        MERCHANT_ONE_ID,
        conversation.id,
        message.id,
        "request-1",
        "a" * 64,
    )
    await db_session.commit()

    own = await repository.get_answer_by_client_request(MERCHANT_ONE_ID, "request-1")
    other = await repository.get_answer_by_client_request(MERCHANT_TWO_ID, "request-1")

    assert own is not None
    assert own.id == answer.id
    assert other is None


@pytest.mark.asyncio
async def test_create_processing_answer_writes_a_check_constraint_valid_response_locale(
    db_session: AsyncSession,
) -> None:
    """全分支复审 Finding 1：`answers.response_locale` 是 NOT NULL 且没有
    `default=`/`server_default=` 的列（见 `app/models/answer.py`），
    `create_processing_answer()` 是它在每一轮聊天/日报生成里的第一个写入点
    （`ChatService`/`ReportService` 都先调用它再流式生成回答）。这里如果没有
    显式写 `response_locale`，`await db_session.commit()` 会在真实
    PostgreSQL 上直接因 NOT NULL 违例失败——历史上从未被捕获，是因为本地
    Docker/PostgreSQL 长期不可用，这条路径此前一直被跳过而不是通过。
    这条测试显式提交（而不是只 flush）以触发约束检查，并确认落库取值落在
    `ck_answers_response_locale` 允许的集合内：写入这一刻回答正文还不存在，
    真实语言也就无从判断，因此用 CHECK 约束里专门为这种"尚未确定"场景保留
    的 `und`（undetermined）占位，`mark_answer_succeeded()` 之后会用探测到
    的真实语言覆盖它。
    """

    await _insert_merchants(db_session)
    repository = ConversationRepository(db_session)
    conversation = await repository.create(MERCHANT_ONE_ID, "商家一会话")
    message = await repository.create_message(
        MERCHANT_ONE_ID, conversation.id, "USER", "退款金额趋势"
    )

    answer = await repository.create_processing_answer(
        MERCHANT_ONE_ID,
        conversation.id,
        message.id,
        "request-locale-check",
        "b" * 64,
    )
    # flush（create_processing_answer 内部已做）不会触发 CHECK/NOT NULL 之外
    # 更早暴露的问题；commit 才是 Finding 1 描述的失败会真正出现的地方。
    await db_session.commit()

    assert answer.response_locale in {"zh-CN", "en-US", "mixed", "und"}
    assert answer.response_locale == "und"
