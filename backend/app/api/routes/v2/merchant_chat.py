"""商家 Chat（PRD A2、契约 §8.7.5）：`POST /api/v2/merchant/chat`，默认 SSE。

事件契约与 v1 不同：`tool_call` / `tool_result` 是 v2 新增，`turn_complete` 取代 `done`，
且流必须以 `turn_complete` 或 `error` 之一收尾。工具展示里只有固定短句，
工具参数、结果行与 Prompt 全文一律进不去（§8.7.5 的模型结构上就不接受）。

**这条路由没有批准能力**：商家工具面只有 `get_inventory_alerts` 与 `draft_restock`，
模型即使声称已经批准，草稿也仍是 `STAGED`（D9①）。
"""

from __future__ import annotations

import asyncio
from typing import Annotated, Any, Final

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.loop.limits import LoopLimits
from app.api.dependencies import (
    build_guarded_llm,
    get_app_settings,
    get_database,
    get_db_session,
    get_principal_secret,
    get_request_locale,
)
from app.api.routes.v2.chat_stream import (
    SSE_HEADERS,
    TurnStreamingResponse,
    build_gates,
    stream_turn,
    wants_json,
)
from app.api.routes.v2.merchant_conversations import Directory
from app.api.session_deps import require_merchant_session
from app.core.config import Settings
from app.core.errors import error_responses
from app.core.session import SessionContext
from app.db.session import Database
from app.llm.client import ConversationalLlmClient
from app.localization.locales import SupportedLocale
from app.repositories.v2.idempotency import IdempotencyRepository
from app.schemas.v2.merchant_session import MerchantChatRequest, MerchantChatResponse
from app.services.v2.idempotency import run_idempotent
from app.services.v2.merchant_chat import MerchantChatService
from app.skills.registry import SkillRegistry
from app.tools.errors import FatalToolError
from app.tools.gates import ToolGates

router = APIRouter(prefix="/v2/merchant", tags=["v2-merchant-chat"])

CHAT_OPERATION: Final = "merchant.chat"


def _service(
    session: AsyncSession,
    *,
    llm: ConversationalLlmClient,
    gates: ToolGates,
    settings: Settings,
    ctx: SessionContext,
    locale: SupportedLocale,
    principal_secret: bytes,
    skills: SkillRegistry | None = None,
) -> MerchantChatService:
    return MerchantChatService(
        session,
        llm=llm,
        gates=gates,
        limits=LoopLimits.from_settings(settings),
        ctx=ctx,
        locale=locale,
        principal_secret=principal_secret,
        skills=skills,
        history_turns=settings.chat_history_max_turns,
    )


@router.post(
    "/chat",
    response_model=MerchantChatResponse,
    responses={
        200: {
            "content": {
                "text/event-stream": {
                    "schema": {"type": "string"},
                    "example": (
                        "event: tool_call\n"
                        'data: {"tool_name":"get_inventory_alerts","call_id":"c1",'
                        '"status":"STARTED","summary":"正在处理"}\n\n'
                        "event: turn_complete\n"
                        'data: {"id":"...","conversation_id":"...","answer":"..."}\n\n'
                    ),
                }
            },
            "description": (
                "默认返回 `text/event-stream`；`Accept: application/json` 时返回普通 JSON。"
                "事件为 `tool_call`、`tool_result`、`turn_complete`、`error`，"
                "流以 `turn_complete` 或 `error` 收尾，两者互斥。`turn_complete` 的载荷"
                "与 JSON 路径的 `MerchantChatResponse` 逐字段相同。"
            ),
        },
        **error_responses(401, 403, 409, 422, 429, 503),
    },
)
async def post_merchant_chat(
    payload: MerchantChatRequest,
    request: Request,
    directory: Directory,
    ctx: Annotated[SessionContext, Depends(require_merchant_session)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    database: Annotated[Database, Depends(get_database)],
    settings: Annotated[Settings, Depends(get_app_settings)],
    principal_secret: Annotated[bytes, Depends(get_principal_secret)],
    locale: Annotated[SupportedLocale, Depends(get_request_locale)],
) -> JSONResponse | StreamingResponse:
    if payload.conversation_id is not None:
        await directory.require(payload.conversation_id)
    request_id = str(getattr(request.state, "request_id", "unknown"))
    cancel = asyncio.Event()
    llm = build_guarded_llm(settings, database, request_id=request_id, merchant_id=ctx.merchant_id)
    gates = build_gates(request, database, principal_secret)
    service = _service(
        session,
        skills=request.app.state.skill_registry,
        llm=llm,
        gates=gates,
        settings=settings,
        ctx=ctx,
        locale=locale,
        principal_secret=principal_secret,
    )

    async def execute(on_event: Any = None) -> dict[str, Any]:
        turn = await service.run(
            payload.message,
            conversation_id=payload.conversation_id,
            request_id=request_id,
            client_request_id=payload.client_request_id,
            request_digest=_digest(payload),
            on_event=on_event,
            cancel=cancel,
        )
        return turn.response.model_dump(mode="json")

    if wants_json(request):
        try:
            body = await _run_once(session, ctx, payload, principal_secret, execute)
        except FatalToolError:
            await session.commit()
            raise
        await session.commit()
        return JSONResponse(content=body)
    return TurnStreamingResponse(
        stream_turn(
            session,
            lambda sink: _run_once(session, ctx, payload, principal_secret, execute, sink),
            cancel=cancel,
            final_model=MerchantChatResponse,
            locale=locale,
            request_id=request_id,
        ),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


async def _run_once(
    session: AsyncSession,
    ctx: SessionContext,
    payload: MerchantChatRequest,
    principal_secret: bytes,
    execute: Any,
    on_event: Any = None,
) -> dict[str, Any]:
    """同一 `client_request_id` 重试返回第一次结果，并发重复提交只产生一次模型调用。"""

    return await run_idempotent(
        repo=IdempotencyRepository(session),
        ctx=ctx,
        secret=principal_secret,
        operation=CHAT_OPERATION,
        client_request_id=payload.client_request_id,
        request_digest=_digest(payload),
        response_status=200,
        execute=lambda: execute(on_event),
    )


def _digest(payload: MerchantChatRequest) -> str:
    from hashlib import sha256

    raw = f"{payload.message}\u0000{payload.conversation_id or ''}"
    return sha256(raw.encode()).hexdigest()
