"""Chat 一轮请求的应用服务与幂等控制。"""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.fake_agent import FakeAgentResult
from app.core.errors import (
    AppError,
    ErrorCode,
    IdempotencyKeyReusedError,
    RequestInProgressError,
    ResourceNotFoundError,
)
from app.core.security import MerchantContext
from app.models.answer import Answer
from app.models.conversation import Conversation
from app.repositories.conversation import ConversationRepository
from app.schemas.chat import ChatRequest, ChatResponse, ThinkingStep
from app.services.merchant_scope import MerchantScopeService

# §8.5：请求本身有问题时重试没有意义，落 FAILED_FINAL；其余按瞬时故障处理，
# 允许同一 client_request_id 重跑。限流和预算耗尽也属于可重试，不在此列。
_FINAL_STATUS_CODES = frozenset({400, 403, 404, 413, 415, 422})


class ChatAgentProtocol(Protocol):
    async def run(self, message: str, session_id: UUID) -> FakeAgentResult: ...


@dataclass(frozen=True)
class ChatExecution:
    response: ChatResponse
    steps: list[ThinkingStep]
    replayed: bool


class ChatService:
    """在可信商家范围内持久化一轮聊天并执行 B2 Fake Agent。"""

    def __init__(
        self,
        session: AsyncSession,
        conversations: ConversationRepository,
        agent: ChatAgentProtocol,
        scope_service: MerchantScopeService[Conversation] | None = None,
    ) -> None:
        self._session = session
        self._conversations = conversations
        self._agent = agent
        self._scope_service = scope_service

    async def submit(
        self,
        context: MerchantContext,
        request: ChatRequest,
        *,
        request_id: str,
    ) -> ChatExecution:
        digest = _request_digest(request)
        existing = await self._conversations.get_answer_by_client_request(
            context.merchant_id,
            request.client_request_id,
        )
        if existing is not None:
            replay = _dispatch_existing(existing, digest)
            if replay is not None:
                return replay
            # FAILED_RETRYABLE：复用同一行并置回 PROCESSING 后重跑。
            await self._conversations.reset_answer_processing(existing)
            await self._session.commit()
            return await self._run_agent(context, request, existing.conversation_id, existing)

        try:
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
            return await self._resolve_race(context, request, digest)

        return await self._run_agent(context, request, conversation_id, answer)

    async def _resolve_race(
        self,
        context: MerchantContext,
        request: ChatRequest,
        digest: str,
    ) -> ChatExecution:
        raced = await self._conversations.get_answer_by_client_request(
            context.merchant_id,
            request.client_request_id,
        )
        if raced is None:
            # 唯一键之外的完整性冲突，不属于幂等竞态，交给全局处理器。
            raise AppError(
                code=ErrorCode.INTERNAL_ERROR,
                message="服务暂时不可用，请稍后重试",
                status_code=500,
                retryable=True,
            )
        replay = _dispatch_existing(raced, digest)
        if replay is not None:
            return replay
        # 对方刚落 FAILED_RETRYABLE：让调用方按 409 重试，避免两边同时重跑。
        raise RequestInProgressError

    async def _run_agent(
        self,
        context: MerchantContext,
        request: ChatRequest,
        conversation_id: UUID,
        answer: Answer,
    ) -> ChatExecution:
        try:
            result = await self._agent.run(request.message, conversation_id)
            response = result.response.model_copy(
                update={
                    "id": answer.id,
                    "session_id": conversation_id,
                    "thinking_steps": result.steps,
                }
            )
            await self._conversations.create_message(
                context.merchant_id,
                conversation_id,
                "ASSISTANT",
                response.answer,
            )
            await self._conversations.touch_conversation(context.merchant_id, conversation_id)
            await self._conversations.mark_answer_succeeded(
                answer,
                response.model_dump(mode="json"),
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


def _dispatch_existing(existing: Answer, digest: str) -> ChatExecution | None:
    """按 §8.5 处理已有幂等记录；返回 None 表示需要复用该行重跑。"""

    if existing.request_digest != digest:
        raise IdempotencyKeyReusedError
    if existing.processing_status == "PROCESSING":
        raise RequestInProgressError
    if existing.processing_status == "SUCCEEDED":
        response = _stored_response(existing.response_payload)
        return ChatExecution(response=response, steps=response.thinking_steps, replayed=True)
    if existing.processing_status == "FAILED_FINAL":
        raise _stored_error(existing.error_payload)
    return None


def _request_digest(request: ChatRequest) -> str:
    payload = {
        "message": request.message,
        "attachment_ids": sorted(str(item) for item in request.attachment_ids),
    }
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, AppError):
        return exc.status_code not in _FINAL_STATUS_CODES
    return True


def _failure_payload(exc: BaseException) -> dict[str, Any]:
    """只保存可安全回放给调用方的字段，绝不写入异常文本或堆栈。"""

    if isinstance(exc, AppError):
        return {
            "code": exc.code.value,
            "message": exc.message,
            "status_code": exc.status_code,
            "retryable": exc.retryable,
        }
    if isinstance(exc, asyncio.CancelledError):
        return {
            "code": ErrorCode.INTERNAL_ERROR.value,
            "message": "回答已中断，请用同一请求标识重试",
            "status_code": 500,
            "retryable": True,
        }
    return {
        "code": ErrorCode.INTERNAL_ERROR.value,
        "message": "演示回答暂时不可用，请稍后重试",
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
    return ChatResponse.model_validate(payload)


def _stored_error(payload: dict[str, Any] | None) -> AppError:
    if payload is None:
        return AppError(
            code=ErrorCode.INTERNAL_ERROR,
            message="请求处理失败",
            status_code=500,
        )
    return AppError(
        code=ErrorCode(str(payload.get("code", ErrorCode.INTERNAL_ERROR))),
        message=str(payload.get("message", "请求处理失败")),
        status_code=int(payload.get("status_code", 500)),
        retryable=bool(payload.get("retryable", False)),
    )
