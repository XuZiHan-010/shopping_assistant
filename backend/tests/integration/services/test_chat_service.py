"""ChatService 的 PostgreSQL 集成测试。

单元测试已经覆盖状态机分支，这里验的是只有真实数据库才能证伪的部分：事务边界、
唯一约束下的并发竞态、跨会话累积和商家隔离。
"""

import asyncio
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.fake_agent import FakeAgent, FakeAgentResult
from app.core.errors import (
    AppError,
    ErrorCode,
    IdempotencyKeyReusedError,
    MerchantScopeViolationError,
    RequestInProgressError,
)
from app.core.security import MerchantContext
from app.db.session import Database
from app.models.answer import Answer
from app.models.conversation import Conversation, Message
from app.models.merchant import Merchant
from app.models.operations import AuditLog
from app.repositories.audit import AuditRepository
from app.repositories.conversation import ConversationRepository
from app.schemas.chat import AnswerMode, ChatRequest
from app.services.chat_service import ChatService
from app.services.merchant_scope import MerchantScopeService

MERCHANT_ID = UUID("00000000-0000-0000-0000-000000000021")
OTHER_MERCHANT_ID = UUID("00000000-0000-0000-0000-000000000022")
CONTEXT = MerchantContext(merchant_id=MERCHANT_ID)
OTHER_CONTEXT = MerchantContext(merchant_id=OTHER_MERCHANT_ID)


class CountingFakeAgent(FakeAgent):
    def __init__(self) -> None:
        self.calls = 0

    async def run(self, message: str, session_id: UUID) -> FakeAgentResult:
        self.calls += 1
        return await super().run(message, session_id)


class SlowCountingAgent(FakeAgent):
    """把 Agent 拉长，好让两个并发请求真的在 INSERT 上撞车。"""

    def __init__(self) -> None:
        self.calls = 0

    async def run(self, message: str, session_id: UUID) -> FakeAgentResult:
        self.calls += 1
        await asyncio.sleep(0.2)
        return await super().run(message, session_id)


class ExplodingAgent:
    def __init__(self, error: BaseException) -> None:
        self.error = error

    async def run(self, message: str, session_id: UUID) -> FakeAgentResult:
        raise self.error


class BlockingAgent(FakeAgent):
    """卡在 Agent 内部，好让测试在「已启动但未完成」的时刻精确取消。"""

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.calls = 0

    async def run(self, message: str, session_id: UUID) -> FakeAgentResult:
        self.calls += 1
        self.started.set()
        await asyncio.Event().wait()
        return await super().run(message, session_id)


async def seed_merchants(session: AsyncSession) -> None:
    session.add_all(
        [
            Merchant(
                id=MERCHANT_ID,
                merchant_code="borough-service-100",
                display_name="Borough商家100",
            ),
            Merchant(
                id=OTHER_MERCHANT_ID,
                merchant_code="borough-service-101",
                display_name="Borough商家101",
            ),
        ]
    )
    await session.commit()


def build_service(session: AsyncSession, agent: object) -> ChatService:
    return ChatService(session, ConversationRepository(session), agent)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_succeeded_request_replays_saved_response_without_running_agent(
    db_session: AsyncSession,
) -> None:
    await seed_merchants(db_session)
    agent = CountingFakeAgent()
    service = build_service(db_session, agent)
    request = ChatRequest(message="最近7天退货量趋势", client_request_id="request-replay-1")

    first = await service.submit(CONTEXT, request, request_id="request-1")
    replay = await service.submit(CONTEXT, request, request_id="request-2")

    assert first.response == replay.response
    assert first.response.session_id == replay.response.session_id
    assert replay.replayed is True
    assert agent.calls == 1


@pytest.mark.asyncio
async def test_reused_key_with_different_message_is_rejected(
    db_session: AsyncSession,
) -> None:
    await seed_merchants(db_session)
    agent = CountingFakeAgent()
    service = build_service(db_session, agent)

    await service.submit(
        CONTEXT,
        ChatRequest(message="昨天总 GMV 是多少？", client_request_id="request-conflict"),
        request_id="request-1",
    )

    with pytest.raises(IdempotencyKeyReusedError):
        await service.submit(
            CONTEXT,
            ChatRequest(message="最近7天退货量趋势", client_request_id="request-conflict"),
            request_id="request-2",
        )

    assert agent.calls == 1


@pytest.mark.asyncio
async def test_processing_row_blocks_a_second_submission(
    db_session: AsyncSession,
) -> None:
    await seed_merchants(db_session)
    agent = CountingFakeAgent()
    service = build_service(db_session, agent)
    request = ChatRequest(message="昨天总 GMV 是多少？", client_request_id="request-processing")

    await service.submit(CONTEXT, request, request_id="request-1")
    answer = await db_session.scalar(select(Answer))
    assert answer is not None
    answer.processing_status = "PROCESSING"
    await db_session.commit()

    with pytest.raises(RequestInProgressError):
        await service.submit(CONTEXT, request, request_id="request-2")

    assert agent.calls == 1


@pytest.mark.asyncio
async def test_retryable_failure_is_persisted_and_the_same_row_is_reused(
    db_session: AsyncSession,
) -> None:
    await seed_merchants(db_session)
    request = ChatRequest(message="昨天总 GMV 是多少？", client_request_id="request-retry")
    failing = build_service(db_session, ExplodingAgent(RuntimeError("agent down")))

    with pytest.raises(RuntimeError):
        await failing.submit(CONTEXT, request, request_id="request-1")

    answer = await db_session.scalar(select(Answer))
    assert answer is not None
    assert answer.processing_status == "FAILED_RETRYABLE"
    assert answer.error_payload is not None
    assert answer.error_payload["code"] == "INTERNAL_ERROR"
    # 失败详情不得泄露内部异常文本。
    assert "agent down" not in str(answer.error_payload)
    # 失败回滚不能把已提交的 USER 消息一起吞掉。
    user_messages = list(await db_session.scalars(select(Message)))
    assert [message.role for message in user_messages] == ["USER"]

    agent = CountingFakeAgent()
    healthy = build_service(db_session, agent)
    execution = await healthy.submit(CONTEXT, request, request_id="request-2")

    answers = list(await db_session.scalars(select(Answer)))
    assert len(answers) == 1
    assert answers[0].id == execution.response.id
    assert answers[0].processing_status == "SUCCEEDED"
    assert agent.calls == 1


@pytest.mark.asyncio
async def test_final_failure_replays_the_stored_error(
    db_session: AsyncSession,
) -> None:
    await seed_merchants(db_session)
    request = ChatRequest(message="昨天总 GMV 是多少？", client_request_id="request-final")
    failing = build_service(db_session, ExplodingAgent(MerchantScopeViolationError()))

    with pytest.raises(MerchantScopeViolationError):
        await failing.submit(CONTEXT, request, request_id="request-1")

    answer = await db_session.scalar(select(Answer))
    assert answer is not None
    assert answer.processing_status == "FAILED_FINAL"

    agent = CountingFakeAgent()
    retried = build_service(db_session, agent)
    with pytest.raises(AppError) as excinfo:
        await retried.submit(CONTEXT, request, request_id="request-2")

    assert excinfo.value.code is ErrorCode.MERCHANT_SCOPE_VIOLATION
    assert excinfo.value.status_code == 403
    assert agent.calls == 0


@pytest.mark.asyncio
async def test_concurrent_submissions_run_the_agent_once(
    db_session: AsyncSession,
    integration_database: Database,
) -> None:
    """§8.5：同一 client_request_id 并发提交两次，只允许一次 Agent 调用。"""

    await seed_merchants(db_session)
    request = ChatRequest(message="昨天总 GMV 是多少？", client_request_id="request-concurrent")
    agent = SlowCountingAgent()

    async def submit(tag: str) -> object:
        async with integration_database.session() as session:
            service = build_service(session, agent)
            try:
                return await service.submit(CONTEXT, request, request_id=tag)
            except AppError as exc:
                return exc

    first, second = await asyncio.gather(submit("request-1"), submit("request-2"))

    outcomes = [first, second]
    losers = [item for item in outcomes if isinstance(item, AppError)]
    winners = [item for item in outcomes if not isinstance(item, AppError)]

    assert agent.calls == 1
    assert len(winners) == 1
    assert len(losers) == 1
    # 输的一方必须拿到 409，而不是唯一约束冒泡出来的 500。
    assert losers[0].status_code == 409
    assert losers[0].code is ErrorCode.REQUEST_IN_PROGRESS

    async with integration_database.session() as session:
        answers = list(await session.scalars(select(Answer)))
    assert len(answers) == 1


@pytest.mark.asyncio
async def test_cancelled_stream_lands_the_answer_in_a_retryable_state(
    db_session: AsyncSession,
) -> None:
    """客户端断开：§8.5 把「流中断」归为 FAILED_RETRYABLE，不能把行留在 PROCESSING。"""

    await seed_merchants(db_session)
    request = ChatRequest(message="昨天总 GMV 是多少？", client_request_id="request-cancel")
    blocking = BlockingAgent()
    service = build_service(db_session, blocking)

    task = asyncio.create_task(service.submit(CONTEXT, request, request_id="request-1"))
    await asyncio.wait_for(blocking.started.wait(), timeout=5)

    # Agent 已经启动，PROCESSING 行也已提交——正是断线最容易踩到的时刻。
    async with db_session.begin_nested():
        in_flight = await db_session.scalar(select(Answer))
    assert in_flight is not None
    assert in_flight.processing_status == "PROCESSING"

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    await db_session.rollback()
    answer = await db_session.scalar(select(Answer))
    assert answer is not None
    assert answer.processing_status == "FAILED_RETRYABLE"
    assert answer.error_payload is not None
    assert answer.error_payload["retryable"] is True
    assert answer.response_payload is None

    # 中断不能留下助手侧的半成品消息。
    messages = list(await db_session.scalars(select(Message)))
    assert [message.role for message in messages] == ["USER"]

    # 同一 client_request_id 必须能重新执行，而不是被 409 永久锁死。
    agent = CountingFakeAgent()
    resumed = build_service(db_session, agent)
    execution = await resumed.submit(CONTEXT, request, request_id="request-2")

    assert execution.replayed is False
    assert agent.calls == 1
    assert blocking.calls == 1
    answers = list(await db_session.scalars(select(Answer)))
    assert len(answers) == 1
    assert answers[0].processing_status == "SUCCEEDED"
    assert answers[0].id == execution.response.id


@pytest.mark.asyncio
async def test_cancellation_before_the_agent_starts_leaves_no_orphan_row(
    db_session: AsyncSession,
    integration_database: Database,
) -> None:
    """取消发生在 PROCESSING 提交之前时，不应留下任何半条记录。"""

    await seed_merchants(db_session)
    request = ChatRequest(message="昨天总 GMV 是多少？", client_request_id="request-cancel-early")

    async with integration_database.session() as session:
        service = build_service(session, CountingFakeAgent())
        task = asyncio.create_task(service.submit(CONTEXT, request, request_id="request-1"))
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    async with integration_database.session() as session:
        assert list(await session.scalars(select(Answer))) == []
        assert list(await session.scalars(select(Message))) == []


@pytest.mark.asyncio
async def test_follow_up_turn_accumulates_in_the_same_conversation(
    db_session: AsyncSession,
) -> None:
    await seed_merchants(db_session)
    service = build_service(db_session, CountingFakeAgent())

    first = await service.submit(
        CONTEXT,
        ChatRequest(message="昨天总 GMV 是多少？", client_request_id="turn-1"),
        request_id="request-1",
    )
    second = await service.submit(
        CONTEXT,
        ChatRequest(
            message="最近7天退货量趋势",
            session_id=first.response.session_id,
            client_request_id="turn-2",
        ),
        request_id="request-2",
    )

    assert second.response.session_id == first.response.session_id
    conversations = list(await db_session.scalars(select(Conversation)))
    assert len(conversations) == 1
    messages = list(
        await db_session.scalars(select(Message).order_by(Message.created_at, Message.id))
    )
    assert [message.role for message in messages] == [
        "USER",
        "ASSISTANT",
        "USER",
        "ASSISTANT",
    ]
    assert conversations[0].updated_at > conversations[0].created_at


@pytest.mark.asyncio
async def test_another_merchant_cannot_continue_a_foreign_conversation(
    db_session: AsyncSession,
    integration_database: Database,
) -> None:
    await seed_merchants(db_session)
    owner_service = build_service(db_session, CountingFakeAgent())
    owned = await owner_service.submit(
        CONTEXT,
        ChatRequest(message="昨天总 GMV 是多少？", client_request_id="owner-turn"),
        request_id="request-1",
    )

    conversations = ConversationRepository(db_session)
    intruder = ChatService(
        db_session,
        conversations,
        CountingFakeAgent(),
        MerchantScopeService(conversations, AuditRepository(integration_database)),
    )

    with pytest.raises(MerchantScopeViolationError):
        await intruder.submit(
            OTHER_CONTEXT,
            ChatRequest(
                message="昨天总 GMV 是多少？",
                session_id=owned.response.session_id,
                client_request_id="intruder-turn",
            ),
            request_id="request-2",
        )

    async with integration_database.session() as session:
        audits = list(await session.scalars(select(AuditLog)))
    assert len(audits) == 1
    assert audits[0].event_type == "MERCHANT_SCOPE_VIOLATION"
    assert audits[0].merchant_id == OTHER_MERCHANT_ID


@pytest.mark.asyncio
async def test_unknown_session_id_is_not_reported_as_scope_violation(
    db_session: AsyncSession,
) -> None:
    await seed_merchants(db_session)
    service = build_service(db_session, CountingFakeAgent())

    with pytest.raises(AppError) as excinfo:
        await service.submit(
            CONTEXT,
            ChatRequest(
                message="昨天总 GMV 是多少？",
                session_id=uuid4(),
                client_request_id="missing-session",
            ),
            request_id="request-1",
        )

    assert excinfo.value.code is ErrorCode.NOT_FOUND
    assert excinfo.value.status_code == 404


@pytest.mark.asyncio
async def test_stored_payload_round_trips_through_the_database(
    db_session: AsyncSession,
) -> None:
    await seed_merchants(db_session)
    service = build_service(db_session, CountingFakeAgent())
    request = ChatRequest(message="最近7天退货量趋势", client_request_id="request-payload")

    original = await service.submit(CONTEXT, request, request_id="request-1")
    replay = await service.submit(CONTEXT, request, request_id="request-2")

    assert original.response.answer_mode is AnswerMode.METRIC
    assert replay.response.model_dump(mode="json") == original.response.model_dump(mode="json")
    assert replay.steps == original.steps
