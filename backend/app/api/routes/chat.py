"""Chat、会话列表、详情与删除路由。"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import suppress
from typing import Annotated, Any
from uuid import UUID

import anyio
from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from structlog.stdlib import BoundLogger

from app.api.dependencies import (
    enforce_rate_limit,
    get_chat_service,
    get_conversation_localization,
    get_conversation_repository,
    get_conversation_scope_service,
    get_db_session,
    get_merchant_context,
    get_request_locale,
)
from app.core.errors import AppError, ErrorCode, ErrorResponse, error_responses
from app.core.security import MerchantContext
from app.llm.client import LlmBudget
from app.localization.error_messages import localize_error_message
from app.localization.locales import SupportedLocale
from app.localization.payloads import (
    collect_conversation_source_hashes,
    localize_conversation_detail,
    localize_conversation_summary,
)
from app.repositories.conversation import ConversationRepository
from app.repositories.localization import LocalizationRepository, LocalizationScope
from app.schemas.chat import (
    ChatRequest,
    ChatResponse,
    ConversationDetailResponse,
    ConversationListResponse,
    ThinkingStep,
)
from app.services.chat_service import ChatExecution, ChatService
from app.services.localization_service import LocalizationService
from app.services.merchant_scope import MerchantScopeService

router = APIRouter(tags=["chat"])

# §8.4：每 15 秒发一次注释心跳，避免反向代理按空闲超时切断长连接。
HEARTBEAT_SECONDS = 15.0
_HEARTBEAT_FRAME = b": keep-alive\n\n"


def _wants_json(request: Request) -> bool:
    return "application/json" in request.headers.get("accept", "").lower()


def _encode_sse(event: str, payload: ThinkingStep | ChatResponse | ErrorResponse) -> bytes:
    data = json.dumps(
        payload.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return f"event: {event}\ndata: {data}\n\n".encode()


async def _sse_body(
    service: ChatService,
    context: MerchantContext,
    payload: ChatRequest,
    request_id: str,
    logger: BoundLogger,
    locale: SupportedLocale = SupportedLocale.ZH_CN,
) -> AsyncIterator[bytes]:
    """SSE 主体。

    响应头在第一个字节之前就已发出，所以进入这里之后的任何失败都只能走
    `event: error`（§8.4）。认证和请求体校验发生在依赖与 FastAPI 校验阶段，
    仍由全局处理器返回普通 JSON 错误，不会进到这里。

    Task 6 Step 8：流内 `error.message` 必须按 `locale` 渲染，不能像过去
    那样直接透出 `exc.message`（那是异常构造时——往往是别的请求、别的
    locale——写入的整句，语言可能与这次请求的 `Accept-Language` 不符）。
    统一改成 `localize_error_message(exc.code, exc.message_params, locale)`，
    与普通 JSON 路径的全局异常处理器完全同一套渲染逻辑，只是这里没有
    Starlette 的异常处理管线可以复用，必须自己调用一次。
    """

    task = asyncio.create_task(
        service.submit(context, payload, request_id=request_id, locale=locale)
    )
    try:
        while True:
            done, _ = await asyncio.wait({task}, timeout=HEARTBEAT_SECONDS)
            if done:
                break
            yield _HEARTBEAT_FRAME

        try:
            execution = task.result()
        except AppError as exc:
            yield _encode_sse(
                "error",
                ErrorResponse(
                    code=exc.code,
                    message=localize_error_message(exc.code, exc.message_params, locale),
                    request_id=request_id,
                    details=exc.details,
                    retryable=exc.retryable,
                ),
            )
            return
        except Exception as exc:
            logger.exception(
                "chat_stream_failed",
                request_id=request_id,
                exception_type=type(exc).__name__,
            )
            yield _encode_sse(
                "error",
                ErrorResponse(
                    code=ErrorCode.INTERNAL_ERROR,
                    message=localize_error_message(ErrorCode.INTERNAL_ERROR, None, locale),
                    request_id=request_id,
                    retryable=True,
                ),
            )
            return

        for step in execution.steps:
            yield _encode_sse("step", step)
        yield _encode_sse("done", execution.response)
    finally:
        # 客户端提前断开时生成器会被关闭，别把 Agent 任务留在后台空跑。
        if not task.done():
            task.cancel()
            await _await_cleanup(task)


async def _await_cleanup(task: asyncio.Task[ChatExecution]) -> None:
    """等被取消的任务把 FAILED_RETRYABLE 提交完再放行。

    数据库 Session 由 yield 依赖在响应结束后关闭；生成器一返回，Starlette 就会
    继续走关闭流程，此时 ChatService 的清理写入可能落在正在关闭的 Session 上。
    Starlette 的取消域是电平触发的（每轮事件循环重新投递取消），所以必须显式屏蔽
    才能真的等到底，否则这里的 await 会被立刻打断。
    """

    with anyio.CancelScope(shield=True), suppress(asyncio.CancelledError):
        await task


@router.post(
    "/chat",
    response_model=ChatResponse,
    responses={
        # SSE 是默认路径，只声明 JSON 会让前端看不出这个端点是流式的。事件序列
        # 无法用 JSON Schema 精确表达，所以这里只声明媒体类型，把事件契约写进
        # description；三种事件的载荷类型（ThinkingStep / ChatResponse /
        # ErrorResponse）都已各自在 components.schemas 里，前端据此自行组 union。
        200: {
            "content": {
                "text/event-stream": {
                    "schema": {"type": "string"},
                    "example": (
                        "event: step\n"
                        'data: {"label":"识别商家与业务意图","node":"classify"}\n\n'
                        "event: done\n"
                        'data: {"id":"...","session_id":"...","answer":"..."}\n\n'
                    ),
                }
            },
            "description": (
                "默认返回 `text/event-stream`；请求头带 `Accept: application/json` 时返回"
                "普通 JSON。SSE 只发送 `step`、`done`、`error` 三种事件，流必须以 `done`"
                " 或 `error` 收尾。`step` 载荷是 `ThinkingStep`，`done` 载荷与 JSON 路径的"
                " `ChatResponse` 逐字段相同，`error` 载荷是 `ErrorResponse`。"
            ),
        },
        **error_responses(401, 403, 409, 422, 429, 503),
    },
)
async def post_chat(
    payload: ChatRequest,
    request: Request,
    context: Annotated[MerchantContext, Depends(get_merchant_context)],
    _: Annotated[None, Depends(enforce_rate_limit)],
    service: Annotated[ChatService, Depends(get_chat_service)],
    locale: Annotated[SupportedLocale, Depends(get_request_locale)],
) -> JSONResponse | StreamingResponse:
    """默认返回 SSE；明确请求 JSON 时返回与 done 同构的响应。

    `locale` 从 `Accept-Language` 解析而来（Task 2 的 `get_request_locale`）；
    `ChatRequest` 本身不带 locale 字段，显式传给 `ChatService.submit()`，图内
    节点只从强类型 `AgentState.locale` 读取（Task 6 Step 5）。
    """

    request_id = str(request.state.request_id)
    if _wants_json(request):
        execution = await service.submit(
            context, payload, request_id=request_id, locale=locale
        )
        return JSONResponse(content=execution.response.model_dump(mode="json"))
    return StreamingResponse(
        _sse_body(service, context, payload, request_id, request.app.state.logger, locale),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get(
    "/conversations",
    response_model=ConversationListResponse,
    responses=error_responses(401, 422),
)
async def list_conversations(
    context: Annotated[MerchantContext, Depends(get_merchant_context)],
    conversations: Annotated[ConversationRepository, Depends(get_conversation_repository)],
    locale: Annotated[SupportedLocale, Depends(get_request_locale)],
    localization: Annotated[
        tuple[LocalizationService, LlmBudget], Depends(get_conversation_localization)
    ],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ConversationListResponse:
    rows = await conversations.list_for_merchant(context.merchant_id, limit=limit, offset=offset)
    service, budget = localization
    items, degraded, degraded_reason = await localize_conversation_summary(
        service=service,
        budget=budget,
        merchant_id=context.merchant_id,
        conversations=rows,
        target_locale=locale,
    )
    return ConversationListResponse(
        items=items,
        limit=limit,
        offset=offset,
        localization_degraded=degraded,
        localization_degraded_reason=degraded_reason,
    )


@router.get(
    "/conversations/{conversation_id}",
    response_model=ConversationDetailResponse,
    responses=error_responses(401, 403, 404, 422),
)
async def get_conversation(
    conversation_id: UUID,
    request: Request,
    context: Annotated[MerchantContext, Depends(get_merchant_context)],
    conversations: Annotated[ConversationRepository, Depends(get_conversation_repository)],
    scope: Annotated[MerchantScopeService[Any], Depends(get_conversation_scope_service)],
    locale: Annotated[SupportedLocale, Depends(get_request_locale)],
    localization: Annotated[
        tuple[LocalizationService, LlmBudget], Depends(get_conversation_localization)
    ],
    message_limit: Annotated[int, Query(ge=1, le=50)] = 20,
    message_before: Annotated[str | None, Query()] = None,
) -> ConversationDetailResponse:
    """会话详情：消息按 `message_before` 游标分页（Task 7，§8.6.3），只翻译
    当前这一页——第一页固定取最新 `message_limit` 条,历史更早的内容要靠
    `next_message_cursor` 继续翻页才会被处理,不会因为打开一次会话就把整份
    历史一次性送进翻译预算。
    """

    conversation = await scope.require_conversation(
        context,
        conversation_id,
        request_id=str(request.state.request_id),
    )
    page = await conversations.list_messages_page(
        context.merchant_id,
        conversation.id,
        limit=message_limit,
        before=message_before,
    )
    answers_by_user_message = {
        answer.user_message_id: (answer, feedback)
        for answer, feedback in await conversations.list_succeeded_answers_for_conversation(
            context.merchant_id,
            conversation.id,
        )
        if answer.user_message_id is not None
    }
    service, budget = localization
    title, detail_messages, degraded, degraded_reason = await localize_conversation_detail(
        service=service,
        budget=budget,
        merchant_id=context.merchant_id,
        title=conversation.title,
        messages=page.messages,
        answers_by_user_message=answers_by_user_message,
        target_locale=locale,
    )
    return ConversationDetailResponse(
        id=conversation.id,
        title=title,
        messages=detail_messages,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        next_message_cursor=page.next_cursor,
        has_more_messages=page.has_more,
        localization_degraded=degraded,
        localization_degraded_reason=degraded_reason,
    )


@router.delete(
    "/conversations/{conversation_id}",
    status_code=204,
    responses=error_responses(401, 403, 404, 422),
)
async def delete_conversation(
    conversation_id: UUID,
    request: Request,
    context: Annotated[MerchantContext, Depends(get_merchant_context)],
    conversations: Annotated[ConversationRepository, Depends(get_conversation_repository)],
    scope: Annotated[MerchantScopeService[Any], Depends(get_conversation_scope_service)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> Response:
    """删除会话时把派生的机器翻译缓存清理放进同一事务（Task 7 Step 6）：
    删除前先按会话全部历史（标题、消息正文、已保存 Answer payload 的思考
    步骤/质量说明/降级原因）计算商家作用域的源哈希集合，删除会话（级联删
    messages/answers）后按这批哈希清理缓存，最后一次性提交。哈希若同时被
    该商家其它内容复用，删除缓存只会导致那部分内容之后重新翻译一次，不影
    响任何原始数据（`docs/backend-development-plan.md` §8.6.3 与 brief Step 6）。
    """

    conversation = await scope.require_conversation(
        context,
        conversation_id,
        request_id=str(request.state.request_id),
    )
    messages = await conversations.list_messages_for_conversation(
        context.merchant_id,
        conversation.id,
    )
    answers = [
        answer
        for answer, _ in await conversations.list_succeeded_answers_for_conversation(
            context.merchant_id,
            conversation.id,
        )
    ]
    source_hashes = collect_conversation_source_hashes(
        title=conversation.title,
        messages=messages,
        answers=answers,
    )
    await conversations.delete_for_merchant(conversation_id, context.merchant_id)
    if source_hashes:
        await LocalizationRepository(session).delete_machine_by_hashes(
            scope=LocalizationScope(kind="MERCHANT", merchant_id=context.merchant_id),
            source_hashes=list(source_hashes),
        )
    await session.commit()
    return Response(status_code=204)
