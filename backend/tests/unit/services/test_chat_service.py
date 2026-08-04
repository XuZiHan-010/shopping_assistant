"""ChatService 幂等状态机的单元测试。

§8.5 的五个分支各一条用例，用内存假件跑，不碰数据库。事务边界和唯一约束
竞态由 `tests/integration/services/test_chat_service.py` 在真实 PostgreSQL 上验。
"""

from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from app.agent.graph import AgentRunResult
from app.core.errors import (
    AppError,
    ErrorCode,
    IdempotencyKeyReusedError,
    MerchantScopeViolationError,
    RequestInProgressError,
)
from app.core.security import MerchantContext
from app.schemas.chat import ChatRequest
from app.services.chat_service import ChatService, _request_digest
from tests.support.agent import DeterministicAgent

MERCHANT_ID = UUID("00000000-0000-0000-0000-000000000041")
CONTEXT = MerchantContext(merchant_id=MERCHANT_ID)


class FakeSession:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


class FakeConversation:
    def __init__(self, merchant_id: UUID, title: str | None) -> None:
        self.id = uuid4()
        self.merchant_id = merchant_id
        self.title = title


class FakeMessage:
    def __init__(self, role: str, content: str) -> None:
        self.id = uuid4()
        self.role = role
        self.content = content


class FakeAnswer:
    def __init__(self, conversation_id: UUID, client_request_id: str, digest: str) -> None:
        self.id = uuid4()
        self.conversation_id = conversation_id
        self.client_request_id = client_request_id
        self.request_digest = digest
        self.processing_status = "PROCESSING"
        self.response_payload: dict[str, Any] | None = None
        self.error_payload: dict[str, Any] | None = None


class FakeConversationRepository:
    """只保留 ChatService 用到的方法，行为与真实 Repository 语义一致。"""

    def __init__(self) -> None:
        self.answers: dict[str, FakeAnswer] = {}
        self.messages: list[FakeMessage] = []
        self.conversations: dict[UUID, FakeConversation] = {}
        self.touched: list[UUID] = []
        self.raise_integrity_error_on_create = False

    async def create(self, merchant_id: UUID, title: str | None = None) -> FakeConversation:
        conversation = FakeConversation(merchant_id, title)
        self.conversations[conversation.id] = conversation
        return conversation

    async def get_for_merchant(
        self, conversation_id: UUID, merchant_id: UUID
    ) -> FakeConversation | None:
        conversation = self.conversations.get(conversation_id)
        if conversation is None or conversation.merchant_id != merchant_id:
            return None
        return conversation

    async def create_message(
        self, merchant_id: UUID, conversation_id: UUID, role: str, content: str
    ) -> FakeMessage:
        message = FakeMessage(role, content)
        self.messages.append(message)
        return message

    async def touch_conversation(self, merchant_id: UUID, conversation_id: UUID) -> None:
        self.touched.append(conversation_id)

    async def get_answer_by_client_request(
        self, merchant_id: UUID, client_request_id: str
    ) -> FakeAnswer | None:
        return self.answers.get(client_request_id)

    async def create_processing_answer(
        self,
        merchant_id: UUID,
        conversation_id: UUID,
        user_message_id: UUID | None,
        client_request_id: str,
        request_digest: str,
    ) -> FakeAnswer:
        if self.raise_integrity_error_on_create:
            raise IntegrityError("INSERT", {}, Exception("duplicate key"))
        answer = FakeAnswer(conversation_id, client_request_id, request_digest)
        self.answers[client_request_id] = answer
        return answer

    async def mark_answer_succeeded(
        self, answer: FakeAnswer, response_payload: dict[str, Any]
    ) -> None:
        answer.processing_status = "SUCCEEDED"
        answer.response_payload = response_payload
        answer.error_payload = None

    async def mark_answer_failed(
        self, answer: FakeAnswer, *, retryable: bool, error_payload: dict[str, Any]
    ) -> None:
        answer.processing_status = "FAILED_RETRYABLE" if retryable else "FAILED_FINAL"
        answer.error_payload = error_payload
        answer.response_payload = None

    async def reset_answer_processing(self, answer: FakeAnswer) -> None:
        answer.processing_status = "PROCESSING"
        answer.error_payload = None


class CountingAgent(DeterministicAgent):
    pass


class ExplodingAgent:
    def __init__(self, error: BaseException) -> None:
        self.error = error
        self.calls = 0

    async def run(self, message: str, session_id: UUID) -> AgentRunResult:
        self.calls += 1
        raise self.error


def build_service(
    agent: Any = None,
) -> tuple[ChatService, FakeConversationRepository, FakeSession, Any]:
    session = FakeSession()
    repository = FakeConversationRepository()
    resolved_agent = agent or CountingAgent()
    service = ChatService(session, repository, resolved_agent)  # type: ignore[arg-type]
    return service, repository, session, resolved_agent


def chat_request(message: str = "昨天总 GMV 是多少？", key: str = "req-1") -> ChatRequest:
    return ChatRequest(message=message, client_request_id=key)


@pytest.mark.asyncio
async def test_succeeded_request_replays_saved_response_without_running_agent() -> None:
    service, _, _, agent = build_service()
    request = chat_request()

    first = await service.submit(CONTEXT, request, request_id="r1")
    replay = await service.submit(CONTEXT, request, request_id="r2")

    assert first.replayed is False
    assert replay.replayed is True
    assert replay.response == first.response
    assert agent.calls == 1


@pytest.mark.asyncio
async def test_reused_key_with_different_digest_is_conflict() -> None:
    service, _, _, agent = build_service()

    await service.submit(CONTEXT, chat_request("昨天总 GMV 是多少？"), request_id="r1")

    with pytest.raises(IdempotencyKeyReusedError) as excinfo:
        await service.submit(CONTEXT, chat_request("最近7天退货量趋势"), request_id="r2")

    assert excinfo.value.code is ErrorCode.IDEMPOTENCY_KEY_REUSED
    assert excinfo.value.status_code == 409
    assert agent.calls == 1


@pytest.mark.asyncio
async def test_processing_request_is_rejected_without_rerunning_agent() -> None:
    service, repository, _, agent = build_service()
    request = chat_request()

    await service.submit(CONTEXT, request, request_id="r1")
    repository.answers[request.client_request_id].processing_status = "PROCESSING"

    with pytest.raises(RequestInProgressError) as excinfo:
        await service.submit(CONTEXT, request, request_id="r2")

    assert excinfo.value.status_code == 409
    assert excinfo.value.retryable is True
    assert agent.calls == 1


@pytest.mark.asyncio
async def test_retryable_failure_reuses_the_same_row_and_runs_again() -> None:
    boom = RuntimeError("agent down")
    service, repository, session, agent = build_service(ExplodingAgent(boom))
    request = chat_request()

    with pytest.raises(RuntimeError):
        await service.submit(CONTEXT, request, request_id="r1")

    stored = repository.answers[request.client_request_id]
    assert stored.processing_status == "FAILED_RETRYABLE"
    assert stored.error_payload == {
        "code": "INTERNAL_ERROR",
        "message": "演示回答暂时不可用，请稍后重试",
        "status_code": 500,
        "retryable": True,
    }
    assert session.rollbacks == 1

    # 换一个能正常回答的 Agent，同一 ID 重跑必须复用这一行而不是新建。
    healthy = CountingAgent()
    service_again = ChatService(session, repository, healthy)  # type: ignore[arg-type]
    execution = await service_again.submit(CONTEXT, request, request_id="r2")

    assert execution.replayed is False
    assert repository.answers[request.client_request_id] is stored
    assert stored.processing_status == "SUCCEEDED"
    assert healthy.calls == 1
    assert agent.calls == 1


@pytest.mark.asyncio
async def test_final_failure_replays_stored_error_without_running_agent() -> None:
    scope_error = MerchantScopeViolationError()
    service, repository, _, agent = build_service(ExplodingAgent(scope_error))
    request = chat_request()

    with pytest.raises(MerchantScopeViolationError):
        await service.submit(CONTEXT, request, request_id="r1")

    stored = repository.answers[request.client_request_id]
    assert stored.processing_status == "FAILED_FINAL"

    with pytest.raises(AppError) as excinfo:
        await service.submit(CONTEXT, request, request_id="r2")

    assert excinfo.value.code is ErrorCode.MERCHANT_SCOPE_VIOLATION
    assert excinfo.value.status_code == 403
    assert excinfo.value.message == "无权访问该商家资源"
    assert agent.calls == 1


@pytest.mark.asyncio
async def test_insert_race_reports_in_progress_instead_of_internal_error() -> None:
    """唯一约束冲突不能冒泡成 500，必须按 §8.5 转成 409。"""

    service, repository, _, agent = build_service()
    request = chat_request()
    digest = _request_digest(request)

    # 模拟另一个并发请求已抢先写入 PROCESSING 行。
    winner = FakeAnswer(uuid4(), request.client_request_id, digest)
    repository.raise_integrity_error_on_create = True
    repository.answers[request.client_request_id] = winner

    with pytest.raises(RequestInProgressError):
        await service.submit(CONTEXT, request, request_id="r2")

    assert agent.calls == 0


@pytest.mark.asyncio
async def test_insert_race_replays_when_winner_already_succeeded() -> None:
    service, repository, _, agent = build_service()
    request = chat_request()

    winner_execution = await service.submit(CONTEXT, request, request_id="r1")
    repository.raise_integrity_error_on_create = True

    replay = await service.submit(CONTEXT, request, request_id="r2")

    assert replay.replayed is True
    assert replay.response == winner_execution.response
    assert agent.calls == 1


@pytest.mark.asyncio
async def test_successful_turn_persists_both_messages_and_touches_conversation() -> None:
    service, repository, session, _ = build_service()

    execution = await service.submit(CONTEXT, chat_request(), request_id="r1")

    assert [message.role for message in repository.messages] == ["USER", "ASSISTANT"]
    assert repository.messages[1].content == execution.response.answer
    assert repository.touched == [execution.response.session_id]
    # 一次提交 PROCESSING 的可见状态，一次提交最终结果。
    assert session.commits == 2
