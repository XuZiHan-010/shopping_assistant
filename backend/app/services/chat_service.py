"""Chat 一轮请求的应用服务与幂等控制。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from time import monotonic
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.graph import AgentRunResult
from app.core.errors import (
    AppError,
    DailyBudgetExhaustedError,
    ErrorCode,
    IdempotencyKeyReusedError,
    RequestInProgressError,
    ResourceNotFoundError,
)
from app.core.metrics import OperationalMetrics
from app.core.security import MerchantContext
from app.llm.client import LlmBudget
from app.llm.guard import CostGuardProtocol
from app.localization.catalog import localize_catalog_value
from app.localization.error_messages import localize_error_message
from app.localization.locales import SupportedLocale
from app.metrics.report_url import upgrade_payload
from app.models.answer import Answer
from app.models.conversation import Conversation
from app.repositories.conversation import ConversationRepository
from app.repositories.localization import LocalizationScope
from app.schemas.chat import AnswerMode, ChatRequest, ChatResponse, ThinkingStep
from app.schemas.localization import LocalizeItem
from app.services.export_service import ExportService
from app.services.merchant_scope import MerchantScopeService
from app.services.quality_loop import _MSG_DAILY_BUDGET_EXCEEDED
from app.services.safe_query import QueryResult

logger = logging.getLogger(__name__)

# §8.5：请求本身有问题时重试没有意义，落 FAILED_FINAL；其余按瞬时故障处理，
# 允许同一 client_request_id 重跑。限流和预算耗尽也属于可重试，不在此列。
_FINAL_STATUS_CODES = frozenset({400, 403, 404, 413, 415, 422})


class ChatAgentProtocol(Protocol):
    async def run(
        self,
        message: str,
        session_id: UUID,
        *,
        locale: SupportedLocale = SupportedLocale.ZH_CN,
    ) -> AgentRunResult: ...


class MemoryAgentProtocol(Protocol):
    def submit(
        self,
        *,
        category: str,
        question: str,
        answer: str,
        source_tables: list[str],
        quality_notes: list[str],
        suggestions: list[str],
        export_id: str | None,
        locale: SupportedLocale = SupportedLocale.ZH_CN,
    ) -> None: ...


class LocalizationServiceLike(Protocol):
    """`displayed_user_message` 本地化专用：只声明用到的
    `LocalizationService.localize_many()` 形状，测试可以用内存假实现替身。"""

    async def localize_many(
        self,
        *,
        scope: LocalizationScope,
        items: Sequence[LocalizeItem],
        target_locale: SupportedLocale,
        budget: LlmBudget,
    ) -> dict[str, str]: ...


@dataclass(frozen=True)
class ChatExecution:
    response: ChatResponse
    steps: list[ThinkingStep]
    replayed: bool


class ChatService:
    """在可信商家范围内持久化一轮聊天并执行受控问答图。"""

    def __init__(
        self,
        session: AsyncSession,
        conversations: ConversationRepository,
        agent: ChatAgentProtocol,
        scope_service: MerchantScopeService[Conversation] | None = None,
        export_service: ExportService | None = None,
        cost_guard: CostGuardProtocol | None = None,
        budget_gate: CostGuardProtocol | None = None,
        metrics: OperationalMetrics | None = None,
        memory_agent: MemoryAgentProtocol | None = None,
        localization_service: LocalizationServiceLike | None = None,
        localization_budget: LlmBudget | None = None,
    ) -> None:
        self._session = session
        self._conversations = conversations
        self._agent = agent
        self._scope_service = scope_service
        self._export_service = export_service
        self._cost_guard = cost_guard
        self._budget_gate = budget_gate
        self._metrics = metrics
        self._memory_agent = memory_agent
        self._localization_service = localization_service
        #: 与 `MerchantQaGraph` 内部跨语言检索用的预算是两个独立对象——各自
        #: 最多花掉 `Settings.localization_max_calls_per_request` 的一部分，
        #: 互不挤占；两者都在 `api/dependencies.py` 按同一请求构造一次。
        self._localization_budget = localization_budget or LlmBudget(0, 0)

    async def submit(
        self,
        context: MerchantContext,
        request: ChatRequest,
        *,
        request_id: str,
        locale: SupportedLocale = SupportedLocale.ZH_CN,
    ) -> ChatExecution:
        digest = _request_digest(request)
        existing = await self._conversations.get_answer_by_client_request(
            context.merchant_id,
            request.client_request_id,
        )
        if existing is not None:
            replay = _dispatch_existing(existing, digest, locale)
            if replay is not None:
                return await self._with_displayed_message(context, request, replay, locale)
            await self._require_daily_budget()
            # FAILED_RETRYABLE：复用同一行并置回 PROCESSING 后重跑。
            await self._conversations.reset_answer_processing(existing)
            await self._session.commit()
            return await self._run_agent(
                context, request, existing.conversation_id, existing, locale
            )

        try:
            await self._require_daily_budget()
            conversation_id = await self._resolve_conversation(context, request, request_id)
            user_message = await self._conversations.create_message(
                context.merchant_id,
                conversation_id,
                "USER",
                request.message,
            )
            answer = await self._conversations.create_processing_answer(
                context.merchant_id,
                conversation_id,
                user_message.id,
                request.client_request_id,
                digest,
            )
            await self._session.commit()
        except IntegrityError:
            # 并发提交同一 client_request_id：SELECT 查不到时两边都会走到 INSERT，
            # 由 uq_answers_merchant_client_request 裁决，输的一方按已有状态答复，
            # 绝不重跑 Agent（§8.5「并发提交两次只产生一次调用」）。
            await self._session.rollback()
            return await self._resolve_race(context, request, digest, locale)

        return await self._run_agent(context, request, conversation_id, answer, locale)

    async def _with_displayed_message(
        self,
        context: MerchantContext,
        request: ChatRequest,
        replay: ChatExecution,
        locale: SupportedLocale,
    ) -> ChatExecution:
        """幂等重放（§8.5 `SUCCEEDED` 分支）：业务事实完全复用存量 Answer，
        只把用户本轮问题的展示副本按**这次重放请求**的 locale 重新渲染。

        不重新本地化整份历史回答正文——那是"翻看历史会话"的场景（Task 7/8：
        `GET /api/conversations/{id}`），与"同一个 `client_request_id` 被重放"
        是两件事：`POST /api/chat` 幂等重放本身是罕见的客户端重试路径，
        `displayed_user_message` 是这条路径上唯一必须"当场"随 locale 变化的
        字段（Step 9 原文「本地化显示副本」——单数、指用户消息，不是整份回答）。
        """

        displayed = await self._localize_display_message(context, request.message, locale)
        response = replay.response.model_copy(update={"displayed_user_message": displayed})
        return ChatExecution(response=response, steps=replay.steps, replayed=True)

    async def _localize_display_message(
        self,
        context: MerchantContext,
        message: str,
        locale: SupportedLocale,
    ) -> str:
        if self._localization_service is None:
            return message
        try:
            resolved = await self._localization_service.localize_many(
                scope=LocalizationScope(kind="MERCHANT", merchant_id=context.merchant_id),
                items=[LocalizeItem(key="displayed_user_message", text=message)],
                target_locale=locale,
                budget=self._localization_budget,
            )
        except Exception:
            # 本地化失败不该让整轮聊天失败——这只是用户自己问题的展示副本，
            # 原样回显源文本仍然可读，比让整个请求 500 更好（R7 的降级精神，
            # 但这个字段本身不参与 ChatResponse.degraded，因为它不是业务分析）。
            logger.warning("本地化用户消息展示副本失败，回退为原文", exc_info=True)
            return message
        return resolved.get("displayed_user_message", message)

    async def _resolve_race(
        self,
        context: MerchantContext,
        request: ChatRequest,
        digest: str,
        locale: SupportedLocale,
    ) -> ChatExecution:
        raced = await self._conversations.get_answer_by_client_request(
            context.merchant_id,
            request.client_request_id,
        )
        if raced is None:
            # 唯一键之外的完整性冲突，不属于幂等竞态，交给全局处理器。
            raise AppError(
                code=ErrorCode.INTERNAL_ERROR,
                message=localize_error_message(ErrorCode.INTERNAL_ERROR, None, locale),
                status_code=500,
                retryable=True,
            )
        replay = _dispatch_existing(raced, digest, locale)
        if replay is not None:
            return await self._with_displayed_message(context, request, replay, locale)
        # 对方刚落 FAILED_RETRYABLE：让调用方按 409 重试，避免两边同时重跑。
        raise RequestInProgressError

    async def _run_agent(
        self,
        context: MerchantContext,
        request: ChatRequest,
        conversation_id: UUID,
        answer: Answer,
        locale: SupportedLocale,
    ) -> ChatExecution:
        try:
            started_at = monotonic()
            result = await self._agent.run(request.message, conversation_id, locale=locale)
            displayed = await self._localize_display_message(context, request.message, locale)
            response = result.response.model_copy(
                update={
                    "id": answer.id,
                    "session_id": conversation_id,
                    "thinking_steps": result.steps,
                    "displayed_user_message": displayed,
                }
            )
            if (
                result.query_result is not None
                and result.query_result.export_spec is not None
                and (
                    response.answer_mode is AnswerMode.DETAIL
                    or result.query_result.export_spec.kind == "generated_metric"
                )
                and not response.degraded
            ):
                if self._export_service is None:
                    raise AppError(
                        code=ErrorCode.DATA_SOURCE_UNAVAILABLE,
                        message=localize_error_message(
                            ErrorCode.DATA_SOURCE_UNAVAILABLE, None, locale
                        ),
                        status_code=503,
                        retryable=True,
                    )
                export = await self._export_service.create(
                    merchant_id=context.merchant_id,
                    answer_id=answer.id,
                    spec=result.query_result.export_spec,
                    locale=locale,
                )
                response = response.model_copy(update={"export": export})
            if self._cost_guard is not None and self._cost_guard.daily_cap_hit:
                if result.query_result is None:
                    raise DailyBudgetExhaustedError
                # Finding 4（全分支复审）：这句提示过去在这里独立重复了一份字面量,
                # 与 `quality_loop._MSG_DAILY_BUDGET_EXCEEDED` 只靠"两处手动保持
                # 一致"维系——任一侧改词都会让另一侧在 `en-US` 下查不到译文,
                # 静默 fallback 回中文原句。直接复用同一个常量,漂移在这里就
                # 不再可能发生。
                fallback_reason = _MSG_DAILY_BUDGET_EXCEEDED
                response = response.model_copy(
                    update={
                        "degraded": True,
                        "degraded_reason": response.degraded_reason
                        or (
                            fallback_reason
                            if locale is SupportedLocale.ZH_CN
                            else localize_catalog_value(fallback_reason, locale)
                            or fallback_reason
                        ),
                    }
                )
            if self._metrics is not None and response.degraded:
                self._metrics.degraded_count += 1
            # 历史详情从 ASSISTANT message 装配 Answer payload。纯明细正文虽为空，
            # 仍必须保存该消息，前端据 payload 展示表格而不会渲染空正文卡片。
            await self._conversations.create_message(
                context.merchant_id,
                conversation_id,
                "ASSISTANT",
                response.answer,
            )
            if self._memory_agent is not None:
                self._memory_agent.submit(
                    category=response.category.value
                    if response.category is not None
                    else "UNKNOWN",
                    question=request.message,
                    answer=response.answer,
                    source_tables=_queried_tables(result.query_result),
                    quality_notes=list(response.quality_notes),
                    suggestions=list(response.suggestions),
                    export_id=str(response.export.id) if response.export is not None else None,
                    locale=locale,
                )
            await self._conversations.touch_conversation(context.merchant_id, conversation_id)
            await self._conversations.mark_answer_succeeded(
                answer,
                response.model_dump(mode="json"),
                elapsed_ms=int((monotonic() - started_at) * 1000),
                response_locale=locale.value,
            )
            await self._session.commit()
            return ChatExecution(response=response, steps=result.steps, replayed=False)
        except asyncio.CancelledError as exc:
            # 客户端断开会取消这个任务。CancelledError 继承 BaseException，不会落进
            # 下面的 except Exception——漏掉这一支，已提交且对外可见的 PROCESSING 行
            # 就永远留在原地，同一 client_request_id 之后只会拿到 REQUEST_IN_PROGRESS。
            # §8.5 把「流中断」明确归为 FAILED_RETRYABLE，这里必须落终态再往上抛。
            await self._abort(answer, exc)
            raise
        except Exception as exc:
            await self._abort(answer, exc)
            raise

    async def _abort(self, answer: Answer, exc: BaseException) -> None:
        """把半途失败的回答落成终态，只写可安全回放的字段。"""

        await self._session.rollback()
        await self._conversations.mark_answer_failed(
            answer,
            retryable=_is_retryable(exc),
            error_payload=_failure_payload(exc),
        )
        await self._session.commit()

    async def _resolve_conversation(
        self,
        context: MerchantContext,
        request: ChatRequest,
        request_id: str,
    ) -> UUID:
        """解析目标会话。

        跨商家 session_id 在这里就抛 403，此时还没有 answers 行可标记
        FAILED_FINAL——`conversation_id` 是 NOT NULL 外键，行只能在会话确定之后
        才建。重试仍会稳定拿到同一个 403，用户可见结果与落终态一致。
        """

        if request.session_id is None:
            conversation = await self._conversations.create(
                context.merchant_id,
                request.message[:80],
            )
            return conversation.id
        if self._scope_service is not None:
            conversation = await self._scope_service.require_conversation(
                context,
                request.session_id,
                request_id=request_id,
            )
            return conversation.id
        existing_conversation = await self._conversations.get_for_merchant(
            request.session_id,
            context.merchant_id,
        )
        if existing_conversation is None:
            raise ResourceNotFoundError("会话")
        return existing_conversation.id

    async def _require_daily_budget(self) -> None:
        if self._budget_gate is not None and await self._budget_gate.remaining() <= 0:
            raise DailyBudgetExhaustedError


def _dispatch_existing(
    existing: Answer, digest: str, locale: SupportedLocale
) -> ChatExecution | None:
    """按 §8.5 处理已有幂等记录；返回 None 表示需要复用该行重跑。

    Task 6 Step 9：三个分支语义不因 `locale` 改变——`PROCESSING` 无论重放
    请求用什么语言都必须抛 409（绝不放宽成"每种语言各允许一次在飞请求"，
    否则同一轮问答会被允许并发跑两次）；`FAILED_FINAL` 从持久化的稳定
    `code + message_params` 按**当前**请求 locale 重新渲染 message，不持久化、
    不重放旧语言整句；`SUCCEEDED` 只在这里判定"可以复用"，`displayed_user_message`
    按当前 locale 的重新赋值交给调用方 `ChatService._with_displayed_message()`
    做，本函数保持纯粹的"读存量记录、按状态机分发"，不接触本地化服务。
    """

    if existing.request_digest != digest:
        raise IdempotencyKeyReusedError
    if existing.processing_status == "PROCESSING":
        raise RequestInProgressError
    if existing.processing_status == "SUCCEEDED":
        response = _stored_response(existing.response_payload)
        return ChatExecution(response=response, steps=response.thinking_steps, replayed=True)
    if existing.processing_status == "FAILED_FINAL":
        raise _stored_error(existing.error_payload, locale)
    return None


def _request_digest(request: ChatRequest) -> str:
    payload = {
        "message": request.message,
        "attachment_ids": sorted(str(item) for item in request.attachment_ids),
    }
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _queried_tables(query_result: QueryResult | None) -> list[str]:
    """返回本轮回答实际查询的经营表。"""

    if query_result is None:
        return []
    return list(query_result.source_tables)


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, AppError):
        return exc.status_code not in _FINAL_STATUS_CODES
    return True


def _failure_payload(exc: BaseException) -> dict[str, Any]:
    """只保存可安全回放给调用方的字段，绝不写入异常文本或堆栈。

    Task 6：只持久化稳定的 `code` + 受控 `message_params`，不再持久化某个
    请求当时渲染出来的整句 `message`——那句话的语言只属于当时那次请求，
    `FAILED_FINAL` 重放时必须按**重放请求自己的** locale 重新渲染
    （`_stored_error()` 消费这里的 `message_params`，见其 docstring）。
    """

    if isinstance(exc, AppError):
        return {
            "code": exc.code.value,
            "message_params": exc.message_params,
            "status_code": exc.status_code,
            "retryable": exc.retryable,
        }
    # 非 AppError（`CancelledError` 或其它未预期异常）统一归为
    # `INTERNAL_ERROR`，不持久化任何异常文本或堆栈（R4/R7）。措辞交给
    # `localize_error_message()` 按重放请求的 locale 渲染通用双语文案——
    # 这两种情形过去各自硬编码一句只有中文的定制说明，改成「稳定 code +
    # message_params」机制后统一折叠进同一条通用 `INTERNAL_ERROR` 文案，
    # 是这次改动有意为之的简化，换来的是消息语言与重放请求 locale 一致。
    return {
        "code": ErrorCode.INTERNAL_ERROR.value,
        "message_params": {},
        "status_code": 500,
        "retryable": True,
    }


def _stored_response(payload: dict[str, Any] | None) -> ChatResponse:
    if payload is None:
        raise AppError(
            code=ErrorCode.INTERNAL_ERROR,
            message="已保存回答不完整，请稍后重试",
            status_code=500,
            retryable=True,
        )
    return ChatResponse.model_validate(upgrade_payload(payload))


def _stored_error(payload: dict[str, Any] | None, locale: SupportedLocale) -> AppError:
    """从持久化的稳定 `code` + `message_params` 重建同一业务错误。

    `message` 按**这次调用传入的** `locale` 渲染——同一条 `FAILED_FINAL` 记录
    先用中文重放、再用英文重放，`code`/`message_params` 逐字不变（同一份业务
    事实），只有这里选取的语言不同（Task 6 Step 9）。全局异常处理器
    （`app.core.errors.handle_app_error`）和修复后的 SSE `error` 事件都只认
    `exc.code`/`exc.message_params` 重新渲染 `message`，这里传入的值仅用于
    未经过这两条渠道、直接读取 `exc.message` 的极少数调用点（防御性兜底）。
    """

    if payload is None:
        return AppError(
            code=ErrorCode.INTERNAL_ERROR,
            message=localize_error_message(ErrorCode.INTERNAL_ERROR, None, locale),
            status_code=500,
        )
    code = ErrorCode(str(payload.get("code", ErrorCode.INTERNAL_ERROR)))
    # 兼容一种过渡态：本任务落地前写入的 `FAILED_FINAL` 行仍是旧形状
    # （只有整句 `message`，没有 `message_params`）——这类演示环境的存量数据
    # 极少见，缺失时按空参数处理，退回该 code 的通用双语文案，而不是抛异常
    # 或原样透出旧语言整句。
    message_params = payload.get("message_params") or {}
    return AppError(
        code=code,
        message=localize_error_message(code, message_params, locale),
        status_code=int(payload.get("status_code", 500)),
        retryable=bool(payload.get("retryable", False)),
        message_params=message_params,
    )
