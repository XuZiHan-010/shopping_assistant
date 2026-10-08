"""顾客导购 Chat（PRD C2，契约 §8.8.2–§8.8.3）：`POST /api/v2/shop/chat`，默认 SSE。

访客与已绑定顾客都可以用。事件集与商家 Chat 相同（`tool_call` / `tool_result` / `turn_complete` /
`error`），线协议在 `chat_stream`；流以 `turn_complete` 或 `error` 之一收尾。
幂等域按 §8.7.3 五元组：同店不同顾客用同一个 `client_request_id` 互不影响。

**这条路由没有下单能力**：顾客工具面支持导购、购物车和售后预览，不含订单提交或支付。
"""

from __future__ import annotations

import asyncio
from hashlib import sha256
from typing import Annotated, Any, Final

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.loop.limits import LoopLimits
from app.agent.loop.runner import EventSink
from app.api.dependencies import (
    build_guarded_llm,
    enforce_keyed_rate_limit,
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
from app.api.routes.v2.shop_conversations import Directory
from app.api.session_deps import require_customer_session
from app.core.config import Settings
from app.core.errors import error_responses
from app.core.session import SessionContext
from app.db.session import Database
from app.localization.locales import SupportedLocale
from app.repositories.v2.idempotency import IdempotencyRepository
from app.schemas.v2.shop_session import ShopChatRequest, ShopChatResponse
from app.services.v2.idempotency import run_idempotent
from app.services.v2.shop_chat import ShopChatService
from app.tools.errors import FatalToolError

router = APIRouter(prefix="/v2/shop", tags=["v2-shop-chat"])

CHAT_OPERATION: Final = "shop.chat"


@router.post(
    "/chat",
    response_model=ShopChatResponse,
    responses={
        200: {
            "content": {
                "text/event-stream": {
                    "schema": {"type": "string"},
                    "example": (
                        "event: tool_call\n"
                        'data: {"tool_name":"search_products","call_id":"c1",'
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
                "与 JSON 路径的 `ShopChatResponse` 逐字段相同。"
            ),
        },
        **error_responses(401, 403, 409, 422, 429, 503),
    },
)
async def post_shop_chat(
    payload: ShopChatRequest,
    request: Request,
    directory: Directory,
    ctx: Annotated[SessionContext, Depends(require_customer_session)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    database: Annotated[Database, Depends(get_database)],
    settings: Annotated[Settings, Depends(get_app_settings)],
    principal_secret: Annotated[bytes, Depends(get_principal_secret)],
    locale: Annotated[SupportedLocale, Depends(get_request_locale)],
) -> JSONResponse | StreamingResponse:
    enforce_keyed_rate_limit(request, settings, key=f"v2-chat:{ctx.role}:{ctx.session_record_id}")
    if payload.conversation_id is not None:
        await directory.require(payload.conversation_id)
    request_id = str(getattr(request.state, "request_id", "unknown"))
    cancel = asyncio.Event()
    llm = build_guarded_llm(
        settings, database, request_id=request_id, merchant_id=ctx.merchant_id, role=ctx.role
    )
    service = ShopChatService(
        session,
        llm=llm,
        gates=build_gates(request, database, principal_secret),
        limits=LoopLimits.from_settings(settings),
        ctx=ctx,
        locale=locale,
        principal_secret=principal_secret,
        skills=request.app.state.skill_registry,
        history_turns=settings.chat_history_max_turns,
        metrics=request.app.state.metrics,
    )

    async def run(on_event: EventSink | None = None) -> dict[str, Any]:
        async def execute() -> dict[str, Any]:
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

        # 同一 `client_request_id` 重试返回第一次结果，并发重复提交只产生一次模型调用。
        return await run_idempotent(
            repo=IdempotencyRepository(session),
            ctx=ctx,
            secret=principal_secret,
            operation=CHAT_OPERATION,
            client_request_id=payload.client_request_id,
            request_digest=_digest(payload),
            response_status=200,
            execute=execute,
        )

    if wants_json(request):
        try:
            body = await run()
        except FatalToolError:
            await session.commit()
            raise
        await session.commit()
        return JSONResponse(content=body)
    return TurnStreamingResponse(
        stream_turn(
            session,
            run,
            cancel=cancel,
            final_model=ShopChatResponse,
            locale=locale,
            request_id=request_id,
        ),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


def _digest(payload: ShopChatRequest) -> str:
    """§8.7.3：摘要取规范化后的 `message` 与 `conversation_id`。"""

    raw = f"{payload.message}\u0000{payload.conversation_id or ''}"
    return sha256(raw.encode()).hexdigest()
