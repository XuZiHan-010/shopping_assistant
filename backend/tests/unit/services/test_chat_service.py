"""ChatService 幂等状态机的单元测试。

§8.5 的五个分支各一条用例，用内存假件跑，不碰数据库。事务边界和唯一约束
竞态由 `tests/integration/services/test_chat_service.py` 在真实 PostgreSQL 上验。
"""

from datetime import date, datetime
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
from app.llm.client import LlmBudget
from app.localization.locales import SupportedLocale
from app.repositories.analytics import ResultColumn
from app.schemas.chat import (
    AnalysisSource,
    AnswerMode,
    ChatRequest,
    ChatResponse,
    ExportInfo,
    QualityStatus,
)
from app.services.chat_service import ChatService, _request_digest, _stored_response
from app.services.safe_query import ExportSpec, QueryResult
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
        self.last_elapsed_ms: int | None = None
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
        self,
        merchant_id: UUID,
        conversation_id: UUID,
        role: str,
        content: str,
        *,
        source_locale: str | None = None,
    ) -> FakeMessage:
        del source_locale
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
        self,
        answer: FakeAnswer,
        response_payload: dict[str, Any],
        *,
        elapsed_ms: int | None = None,
        response_locale: str | None = None,
    ) -> None:
        answer.processing_status = "SUCCEEDED"
        answer.response_payload = response_payload
        answer.error_payload = None
        answer.response_locale = response_locale
        self.last_elapsed_ms = elapsed_ms

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

    async def run(
        self,
        message: str,
        session_id: UUID,
        *,
        locale: SupportedLocale = SupportedLocale.ZH_CN,
    ) -> AgentRunResult:
        del locale
        self.calls += 1
        raise self.error


class TableOnlyAgent:
    """返回已由 ChatResponse 契约验证过的纯明细，用于测试持久化层。"""

    async def run(
        self,
        message: str,
        session_id: UUID,
        *,
        locale: SupportedLocale = SupportedLocale.ZH_CN,
    ) -> AgentRunResult:
        result = await DeterministicAgent().run(message, session_id, locale=locale)
        base = result.response.model_dump(mode="json")
        base.update(
            {
                "answer": "",
                "answer_mode": AnswerMode.DETAIL,
                "export": {
                    "id": str(uuid4()),
                    "url": "/api/exports/example",
                    "expires_at": "2026-08-12T00:00:00Z",
                },
                "recommendations": [],
            }
        )
        response = ChatResponse.model_validate(base)
        return AgentRunResult(response=response, steps=response.thinking_steps)


class GeneratedMetricAgent:
    async def run(
        self,
        message: str,
        session_id: UUID,
        *,
        locale: SupportedLocale = SupportedLocale.ZH_CN,
    ) -> AgentRunResult:
        result = await DeterministicAgent().run(message, session_id, locale=locale)
        response_data = result.response.model_dump(mode="json")
        response_data.update(
            {
                "quality_status": QualityStatus.NOT_RUN,
                "quality_notes": [],
                "analysis_sources": [AnalysisSource.DATABASE],
                "degraded": False,
                "degraded_reason": None,
                "data_rows": [{"spu_id": "SPU-1", "paid_amount": 100}],
                "total_rows": 1,
            }
        )
        response = ChatResponse.model_validate(response_data)
        query_result = QueryResult(
            columns=(
                ResultColumn("spu_id", "SPU ID", "DIMENSION"),
                ResultColumn("paid_amount", "成交金额", "METRIC"),
            ),
            rows=[{"spu_id": "SPU-1", "paid_amount": 100}],
            total_rows=1,
            truncated=False,
            source_tables=("orders", "order_items", "products"),
            plan_steps=("固定分组聚合",),
            export_spec=ExportSpec(
                table="generated_metric",
                columns=("spu_id", "paid_amount"),
                start=date(2026, 8, 1),
                end=date(2026, 8, 1),
                kind="generated_metric",
            ),
            notes=(),
            non_additive=True,
        )
        return AgentRunResult(
            response=response,
            steps=result.steps,
            query_result=query_result,
        )


class _ExportService:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def create(self, **kwargs: object) -> ExportInfo:
        self.calls.append(kwargs)
        return ExportInfo(id=uuid4(), url="/api/exports/generated", expires_at=datetime(2026, 8, 2))


class _RecordingMemoryAgent:
    def __init__(self, repository: FakeConversationRepository) -> None:
        self._repository = repository
        self.calls: list[dict[str, object]] = []

    def submit(self, **kwargs: object) -> None:
        assert self._repository.messages[-1].role == "ASSISTANT"
        self.calls.append(kwargs)


class _FakeDisplayLocalizer:
    """Task 6：`displayed_user_message` 本地化专用测试替身。

    不模拟 `LocalizationService.localize_many()` 内部的恒等/词典/缓存级联，
    只按显式给定的映射表返回译文——`target_locale` 为 en-US 才查表，其余
    locale（如 zh-CN）原样返回源文本，粗粒度地还原真实服务"目标语言与源
    语言相同时不翻译"的行为，够用来验证 `ChatService` 这一层的调用与
    覆写逻辑，不重复测试 `LocalizationService` 自己的级联（那部分已经在
    `tests/unit/services/test_localization_service.py` 覆盖）。
    """

    def __init__(self, translations: dict[str, str]) -> None:
        self.calls = 0
        self._translations = translations

    async def localize_many(
        self,
        *,
        scope: object,
        items: object,
        target_locale: SupportedLocale,
        budget: object,
    ) -> dict[str, str]:
        self.calls += 1
        resolved: dict[str, str] = {}
        for item in items:  # type: ignore[attr-defined]
            if target_locale is SupportedLocale.EN_US:
                resolved[item.key] = self._translations.get(item.text, item.text)
            else:
                resolved[item.key] = item.text
        return resolved


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
async def test_successful_answer_registers_memory_after_assistant_message() -> None:
    session = FakeSession()
    repository = FakeConversationRepository()
    memory_agent = _RecordingMemoryAgent(repository)
    service = ChatService(session, repository, CountingAgent(), memory_agent=memory_agent)  # type: ignore[arg-type]

    execution = await service.submit(CONTEXT, chat_request(), request_id="memory-submit")

    assert execution.replayed is False
    assert memory_agent.calls[0]["question"] == "昨天总 GMV 是多少？"
    assert memory_agent.calls[0]["answer"] == execution.response.answer


@pytest.mark.asyncio
async def test_historical_metric_payload_replays_with_traceability_defaults() -> None:
    """历史 JSONB 在新契约下仍可重放，但不得虚构来源库表。"""

    result = await DeterministicAgent().run("昨天 GMV", uuid4())
    payload = result.response.model_dump(mode="json")
    for field in (
        "metric_sql_definition",
        "metric_dimensions",
        "metric_source_database",
        "metric_source_table",
        "metric_report_url",
        "metric_generated",
        "metric_notice",
    ):
        payload.pop(field)

    replayed = _stored_response(payload)

    assert replayed.metric_dimensions == []
    assert replayed.metric_sql_definition == ""
    assert replayed.metric_source_database == ""
    assert replayed.metric_source_table == ""
    assert replayed.metric_report_url is None
    assert replayed.metric_generated is False


@pytest.mark.asyncio
async def test_generated_metric_with_a_verified_export_spec_gets_a_signed_link() -> None:
    session = FakeSession()
    repository = FakeConversationRepository()
    exports = _ExportService()
    service = ChatService(
        session,
        repository,
        GeneratedMetricAgent(),
        export_service=exports,  # type: ignore[arg-type]
    )

    execution = await service.submit(CONTEXT, chat_request(), request_id="generated-export")

    assert len(exports.calls) == 1
    assert execution.response.export is not None
    assert execution.response.export.url == "/api/exports/generated"


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
    # Task 6：只持久化稳定的 code + message_params，不再持久化某次请求当时
    # 渲染出来的整句 message——`FAILED_FINAL` 重放时必须能按重放请求自己的
    # locale 重新渲染（见 `_stored_error()`），持久化整句会锁死第一次的语言。
    assert stored.error_payload == {
        "code": "INTERNAL_ERROR",
        "message_params": {},
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


@pytest.mark.asyncio
async def test_table_only_turn_persists_an_assistant_message_for_history_replay() -> None:
    """历史详情只从助手消息装配 Answer payload，纯表格轮次也必须可重放。"""

    service, repository, _, _ = build_service(TableOnlyAgent())

    execution = await service.submit(CONTEXT, chat_request(key="table-only-1"), request_id="r1")

    assert execution.response.answer == ""
    assert [message.role for message in repository.messages] == ["USER", "ASSISTANT"]
    assert repository.messages[1].content == ""
    stored = repository.answers["table-only-1"]
    assert stored.processing_status == "SUCCEEDED"
    assert stored.response_payload is not None
    assert stored.response_payload["answer"] == ""


@pytest.mark.asyncio
async def test_finalized_degraded_response_increments_metrics() -> None:
    from app.core.metrics import OperationalMetrics

    session = FakeSession()
    repository = FakeConversationRepository()
    metrics = OperationalMetrics()
    service = ChatService(
        session,  # type: ignore[arg-type]
        repository,
        CountingAgent(),
        metrics=metrics,
    )

    await service.submit(CONTEXT, chat_request(key="req-degraded-1"), request_id="req-1")

    assert metrics.degraded_count == 1


@pytest.mark.asyncio
async def test_successful_turn_records_elapsed_ms() -> None:
    """删除耗时透传时，本测试应失败，防止思考时长指标失去事实来源。"""
    service, repository, _, _ = build_service()

    await service.submit(CONTEXT, chat_request(key="elapsed-ms-1"), request_id="r1")

    assert repository.last_elapsed_ms is not None
    assert repository.last_elapsed_ms >= 0


# --- Task 6：locale 贯穿与幂等语义 ------------------------------------------


@pytest.mark.asyncio
async def test_failed_final_replay_renders_a_localized_message_but_runs_the_agent_once() -> None:
    """Step 9 核心断言：同一失败 `client_request_id` 先中文、后英语重放，
    `code` 相同、`message` 语言不同，业务执行次数仍为 1。

    `FAILED_FINAL` 只持久化稳定的 `code` + `message_params`（Task 6 之前会
    连整句中文 `message` 一起存死）；重放时 `_stored_error()` 按**这次重放
    请求自己的** `locale` 现场渲染 `message`，绝不重放旧语言整句。
    """

    scope_error = MerchantScopeViolationError()
    service, repository, _, agent = build_service(ExplodingAgent(scope_error))
    request = chat_request()

    with pytest.raises(MerchantScopeViolationError):
        await service.submit(CONTEXT, request, request_id="r1", locale=SupportedLocale.ZH_CN)

    stored = repository.answers[request.client_request_id]
    assert stored.processing_status == "FAILED_FINAL"

    with pytest.raises(AppError) as zh_excinfo:
        await service.submit(CONTEXT, request, request_id="r2", locale=SupportedLocale.ZH_CN)
    with pytest.raises(AppError) as en_excinfo:
        await service.submit(CONTEXT, request, request_id="r3", locale=SupportedLocale.EN_US)

    assert zh_excinfo.value.code is ErrorCode.MERCHANT_SCOPE_VIOLATION
    assert en_excinfo.value.code is ErrorCode.MERCHANT_SCOPE_VIOLATION
    assert zh_excinfo.value.status_code == en_excinfo.value.status_code == 403
    assert zh_excinfo.value.message == "无权访问该商家资源"
    assert (
        en_excinfo.value.message
        == "You do not have permission to access this merchant's resources."
    )
    assert zh_excinfo.value.message != en_excinfo.value.message
    # 只有第一次真正触发过 Agent（并让它抛出异常）；两次重放都是纯读取分发，
    # 一次都没有再调用 Agent。
    assert agent.calls == 1


@pytest.mark.asyncio
async def test_processing_request_is_still_rejected_when_replayed_in_a_different_locale() -> None:
    """不得为了支持切换语言而放宽 `PROCESSING` 分支——那等于允许同一轮问答
    并发跑两次。无论重放请求用哪种语言，`PROCESSING` 都必须是 409。"""

    service, repository, _, agent = build_service()
    request = chat_request()

    await service.submit(CONTEXT, request, request_id="r1", locale=SupportedLocale.ZH_CN)
    repository.answers[request.client_request_id].processing_status = "PROCESSING"

    with pytest.raises(RequestInProgressError) as excinfo:
        await service.submit(CONTEXT, request, request_id="r2", locale=SupportedLocale.EN_US)

    assert excinfo.value.status_code == 409
    assert excinfo.value.retryable is True
    assert agent.calls == 1


@pytest.mark.asyncio
async def test_succeeded_replay_relocalizes_only_the_displayed_user_message() -> None:
    """`SUCCEEDED` 重放复用同一份业务事实（Agent 只跑一次），但
    `displayed_user_message` 必须按**这次重放请求自己的** locale 重新渲染，
    不能沿用第一次生成时的语言。"""

    localizer = _FakeDisplayLocalizer({"昨天总 GMV 是多少？": "What was total GMV yesterday?"})
    session = FakeSession()
    repository = FakeConversationRepository()
    agent = CountingAgent()
    service = ChatService(
        session,  # type: ignore[arg-type]
        repository,
        agent,
        localization_service=localizer,  # type: ignore[arg-type]
        localization_budget=LlmBudget(4, 4_000),
    )
    request = chat_request()

    zh = await service.submit(CONTEXT, request, request_id="r1", locale=SupportedLocale.ZH_CN)
    en = await service.submit(CONTEXT, request, request_id="r2", locale=SupportedLocale.EN_US)

    assert zh.replayed is False
    assert en.replayed is True
    assert zh.response.displayed_user_message == "昨天总 GMV 是多少？"
    assert en.response.displayed_user_message == "What was total GMV yesterday?"
    # 除了 displayed_user_message，其余业务事实必须逐字相同——同一份 Answer。
    assert zh.response.model_dump(mode="json", exclude={"displayed_user_message"}) == (
        en.response.model_dump(mode="json", exclude={"displayed_user_message"})
    )
    assert agent.calls == 1
    assert localizer.calls >= 1


def test_request_digest_is_a_pure_function_of_message_and_attachments_only() -> None:
    """`_request_digest()` 继续只散列消息和附件，不接受也不读取 locale——
    `ChatRequest` 本身也不带 locale 字段（Task 6 明确不引入第二个真源）。
    同一问题在两种语言的请求下必须落到同一个摘要，幂等判定才不会因为
    `Accept-Language` 不同就把同一个 `client_request_id` 误判成"内容变了"。
    """

    same_message_different_key_a = chat_request(message="昨天总 GMV 是多少？", key="digest-a")
    same_message_different_key_b = chat_request(message="昨天总 GMV 是多少？", key="digest-b")
    different_message = chat_request(message="最近7天退货量趋势", key="digest-a")

    # client_request_id 不参与摘要：同一问题不同请求标识落到同一个摘要。
    assert _request_digest(same_message_different_key_a) == _request_digest(
        same_message_different_key_b
    )
    # 消息本身变化时摘要必须不同，否则幂等键复用检测（IDEMPOTENCY_KEY_REUSED）
    # 会形同虚设。
    assert _request_digest(different_message) != _request_digest(same_message_different_key_a)
