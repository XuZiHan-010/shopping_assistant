from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import InvalidRequestError
from app.models.merchant import Merchant
from app.repositories.conversation import ConversationRepository

MERCHANT_ONE_ID = UUID("00000000-0000-0000-0000-000000000001")
MERCHANT_TWO_ID = UUID("00000000-0000-0000-0000-000000000002")


async def insert_merchants(session: AsyncSession) -> None:
    session.add_all(
        [
            Merchant(
                id=MERCHANT_ONE_ID,
                merchant_code="borough-demo-100",
                display_name="Borough商家100",
            ),
            Merchant(
                id=MERCHANT_TWO_ID,
                merchant_code="borough-demo-101",
                display_name="Borough商家101",
            ),
        ]
    )
    await session.flush()


@pytest.mark.asyncio
async def test_repository_never_lists_or_reads_other_merchant_conversations(
    db_session: AsyncSession,
) -> None:
    await insert_merchants(db_session)
    repository = ConversationRepository(db_session)
    own = await repository.create(MERCHANT_ONE_ID, "本商家会话")
    other = await repository.create(MERCHANT_TWO_ID, "其他商家会话")
    await db_session.commit()

    rows = await repository.list_for_merchant(MERCHANT_ONE_ID, limit=20, offset=0)

    assert [row.id for row in rows] == [own.id]
    assert await repository.get_for_merchant(other.id, MERCHANT_ONE_ID) is None
    assert await repository.delete_for_merchant(other.id, MERCHANT_ONE_ID) is False


@pytest.mark.asyncio
async def test_repository_deletes_only_owned_conversation(
    db_session: AsyncSession,
) -> None:
    await insert_merchants(db_session)
    repository = ConversationRepository(db_session)
    own = await repository.create(MERCHANT_ONE_ID, "可删除会话")
    await db_session.commit()

    deleted = await repository.delete_for_merchant(own.id, MERCHANT_ONE_ID)
    await db_session.commit()

    assert deleted is True
    assert await repository.get_for_merchant(own.id, MERCHANT_ONE_ID) is None


@pytest.mark.asyncio
async def test_has_assistant_message_false_before_first_turn_completes(
    db_session: AsyncSession,
) -> None:
    """闸门首轮判定（`app.agent.prefilter`）依据此方法：新会话只有用户消息、
    尚无助手消息时必须走打分，不能被误判成「已有历史」而放行。"""

    await insert_merchants(db_session)
    repository = ConversationRepository(db_session)
    conversation = await repository.create(MERCHANT_ONE_ID, "闸门判定会话")
    await repository.create_message(MERCHANT_ONE_ID, conversation.id, "USER", "最近7天退货量")
    await db_session.commit()

    assert await repository.has_assistant_message(MERCHANT_ONE_ID, conversation.id) is False


@pytest.mark.asyncio
async def test_has_assistant_message_true_after_first_turn_completes(
    db_session: AsyncSession,
) -> None:
    await insert_merchants(db_session)
    repository = ConversationRepository(db_session)
    conversation = await repository.create(MERCHANT_ONE_ID, "闸门判定会话")
    await repository.create_message(MERCHANT_ONE_ID, conversation.id, "USER", "最近7天退货量")
    await repository.create_message(MERCHANT_ONE_ID, conversation.id, "ASSISTANT", "上一轮回答")
    await db_session.commit()

    assert await repository.has_assistant_message(MERCHANT_ONE_ID, conversation.id) is True


@pytest.mark.asyncio
async def test_has_assistant_message_never_crosses_merchants(
    db_session: AsyncSession,
) -> None:
    await insert_merchants(db_session)
    repository = ConversationRepository(db_session)
    conversation = await repository.create(MERCHANT_TWO_ID, "他人会话")
    await repository.create_message(MERCHANT_TWO_ID, conversation.id, "ASSISTANT", "他人回答")
    await db_session.commit()

    assert await repository.has_assistant_message(MERCHANT_ONE_ID, conversation.id) is False


# ---------------------------------------------------------------------------
# Task 7（§8.6.3）：`list_messages_page()` 消息游标分页
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_messages_page_returns_pages_in_chronological_order_with_correct_boundaries(
    db_session: AsyncSession,
) -> None:
    """7 条消息、每页 5 条：第一页 5 条 + `has_more=True`，第二页剩余 2 条 +
    `has_more=False`；两页互不重叠、合并后覆盖全部 7 条，且页内按时间正序。

    不对内容顺序做逐条硬编码断言——同一批快速连续写入的消息可能落在同一个
    PostgreSQL 事务时间戳粒度内（`now()` 是事务级而不是语句级），逐条提交
    已经最大程度拉开时间差，但断言改用「页内非降序」与「两页合并=全集」这
    两个不依赖具体时钟粒度的结构性质，同样能证明分页边界正确。
    """

    await insert_merchants(db_session)
    repository = ConversationRepository(db_session)
    conversation = await repository.create(MERCHANT_ONE_ID, "分页会话")
    await db_session.commit()

    created_ids: list[UUID] = []
    for index in range(7):
        role = "USER" if index % 2 == 0 else "ASSISTANT"
        message = await repository.create_message(
            MERCHANT_ONE_ID, conversation.id, role, f"消息 {index}"
        )
        created_ids.append(message.id)
        await db_session.commit()

    first_page = await repository.list_messages_page(MERCHANT_ONE_ID, conversation.id, limit=5)

    assert len(first_page.messages) == 5
    assert first_page.has_more is True
    assert first_page.next_cursor is not None
    assert [m.created_at for m in first_page.messages] == sorted(
        m.created_at for m in first_page.messages
    )

    second_page = await repository.list_messages_page(
        MERCHANT_ONE_ID, conversation.id, limit=5, before=first_page.next_cursor
    )

    assert len(second_page.messages) == 2
    assert second_page.has_more is False
    assert second_page.next_cursor is None
    assert [m.created_at for m in second_page.messages] == sorted(
        m.created_at for m in second_page.messages
    )

    first_ids = {m.id for m in first_page.messages}
    second_ids = {m.id for m in second_page.messages}
    assert first_ids.isdisjoint(second_ids)
    assert first_ids | second_ids == set(created_ids)

    oldest_in_first_page = min(m.created_at for m in first_page.messages)
    newest_in_second_page = max(m.created_at for m in second_page.messages)
    assert newest_in_second_page <= oldest_in_first_page


@pytest.mark.asyncio
async def test_list_messages_page_resolves_pairing_split_across_a_page_boundary(
    db_session: AsyncSession,
) -> None:
    """回归测试：消息严格按 USER/ASSISTANT 交替写入，`limit` 为奇数时分页
    边界必然把某一轮拆到两页。4 条消息（2 轮）、`limit=3`：第一页是
    [ASSISTANT(轮1), USER(轮2), ASSISTANT(轮2)]，最早一条 ASSISTANT 的配对
    USER 落在更早、不在本页的那一条消息里。`list_messages_page()` 必须查到
    并带回这条边界 USER 消息的 id，且不应把它标记为"未解析"。
    """

    await insert_merchants(db_session)
    repository = ConversationRepository(db_session)
    conversation = await repository.create(MERCHANT_ONE_ID, "拆分会话")
    await db_session.commit()

    message_ids: list[UUID] = []
    for index in range(4):
        role = "USER" if index % 2 == 0 else "ASSISTANT"
        message = await repository.create_message(
            MERCHANT_ONE_ID, conversation.id, role, f"消息 {index}"
        )
        message_ids.append(message.id)
        await db_session.commit()

    page = await repository.list_messages_page(MERCHANT_ONE_ID, conversation.id, limit=3)

    assert [m.role for m in page.messages] == ["ASSISTANT", "USER", "ASSISTANT"]
    assert page.messages[0].id == message_ids[1]
    assert page.boundary_user_message_id == message_ids[0]
    assert page.boundary_pairing_unresolved is False

    # 续接边界之后的下一页只剩最早那条 USER 消息。
    second_page = await repository.list_messages_page(
        MERCHANT_ONE_ID, conversation.id, limit=3, before=page.next_cursor
    )
    assert [m.id for m in second_page.messages] == [message_ids[0]]
    assert second_page.has_more is False


@pytest.mark.asyncio
async def test_list_messages_page_flags_unresolved_pairing_when_no_preceding_message_exists(
    db_session: AsyncSession,
) -> None:
    """防御性用例：正常写路径（`ChatService`）永远先写 USER 再写 ASSISTANT，
    因此某会话的第一条消息是 ASSISTANT 属于数据异常，理论上不会发生。但
    Repository 遇到这种情况时必须显式标记为「未解析」，而不是假装配对成功
    或者悄悄返回一个空的 `answer_payload`（协调者要求：绝不允许静默丢数据）。
    """

    await insert_merchants(db_session)
    repository = ConversationRepository(db_session)
    conversation = await repository.create(MERCHANT_ONE_ID, "异常会话")
    await db_session.commit()
    await repository.create_message(MERCHANT_ONE_ID, conversation.id, "ASSISTANT", "孤立回答")
    await db_session.commit()

    page = await repository.list_messages_page(MERCHANT_ONE_ID, conversation.id, limit=10)

    assert page.boundary_user_message_id is None
    assert page.boundary_pairing_unresolved is True


@pytest.mark.asyncio
async def test_list_messages_page_with_forty_messages_only_returns_the_requested_page_size(
    db_session: AsyncSession,
) -> None:
    """预算护栏在 Repository 这一层的证明：40 条消息的会话，`limit=20` 永远
    只吐出 20 条 + `has_more=True`，不会因为历史条数多就多返回,也不会把整份
    历史一次性交给上层去翻译。"""

    await insert_merchants(db_session)
    repository = ConversationRepository(db_session)
    conversation = await repository.create(MERCHANT_ONE_ID, "长会话")
    await db_session.commit()
    for index in range(40):
        role = "USER" if index % 2 == 0 else "ASSISTANT"
        await repository.create_message(MERCHANT_ONE_ID, conversation.id, role, f"消息 {index}")
        await db_session.commit()

    first_page = await repository.list_messages_page(MERCHANT_ONE_ID, conversation.id, limit=20)

    assert len(first_page.messages) == 20
    assert first_page.has_more is True
    assert first_page.next_cursor is not None


@pytest.mark.asyncio
async def test_list_messages_page_cursor_is_scoped_to_merchant_and_conversation(
    db_session: AsyncSession,
) -> None:
    """§8.6.3 原文：「游标必须绑定可信 `merchant_id` + `conversation_id`，
    跨商家或跨会话复用返回稳定错误码」——本测试直接复用另一会话/另一商家的
    有效游标，断言两种复用都稳定抛 `InvalidRequestError`（422），而不是静默
    返回空页或错误的一页。"""

    await insert_merchants(db_session)
    repository = ConversationRepository(db_session)
    conversation_a = await repository.create(MERCHANT_ONE_ID, "会话 A")
    conversation_b = await repository.create(MERCHANT_ONE_ID, "会话 B")
    await db_session.commit()
    await repository.create_message(MERCHANT_ONE_ID, conversation_a.id, "USER", "A 的第一条")
    await db_session.commit()
    await repository.create_message(MERCHANT_ONE_ID, conversation_a.id, "USER", "A 的第二条")
    await db_session.commit()

    page = await repository.list_messages_page(MERCHANT_ONE_ID, conversation_a.id, limit=1)
    assert page.has_more is True
    cursor = page.next_cursor
    assert cursor is not None

    with pytest.raises(InvalidRequestError):
        await repository.list_messages_page(
            MERCHANT_ONE_ID, conversation_b.id, limit=1, before=cursor
        )
    with pytest.raises(InvalidRequestError):
        await repository.list_messages_page(
            MERCHANT_TWO_ID, conversation_a.id, limit=1, before=cursor
        )

    # 正确作用域下同一个游标仍然可以正常翻页。
    same_scope = await repository.list_messages_page(
        MERCHANT_ONE_ID, conversation_a.id, limit=1, before=cursor
    )
    assert same_scope.has_more is False
    assert len(same_scope.messages) == 1


@pytest.mark.asyncio
async def test_list_messages_page_rejects_a_garbage_cursor(
    db_session: AsyncSession,
) -> None:
    await insert_merchants(db_session)
    repository = ConversationRepository(db_session)
    conversation = await repository.create(MERCHANT_ONE_ID, "会话")
    await db_session.commit()

    with pytest.raises(InvalidRequestError):
        await repository.list_messages_page(
            MERCHANT_ONE_ID, conversation.id, limit=1, before="not-a-real-cursor"
        )
