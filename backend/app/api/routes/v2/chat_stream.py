"""两端 v2 Chat 共用的 SSE 线协议（契约 §8.7.5、沿用 §8.4）。

顾客与商家 Chat 的事件集、心跳、开流前后错误语义完全相同，只是最终载荷模型不同；
放在一处，免得两条路由各写一份、日后只修了一边。这里只做**投影**：循环事件里只有
`ToolDisplay` 级别的信息，工具参数、结果行与 Prompt 全文结构上就进不来。
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable, Coroutine
from contextlib import suppress
from typing import Any, Final

import anyio
from fastapi import Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.types import Receive, Scope, Send

from app.agent.loop.runner import EventSink, LoopEvent, ToolCallFinished, ToolCallStarted
from app.core.errors import AppError, ErrorCode, ErrorResponse
from app.db.session import Database
from app.localization.error_messages import localize_error_message
from app.localization.locales import SupportedLocale
from app.repositories.audit import AuditRepository
from app.schemas.v2.common import SseEventName
from app.services.v2.drafts import DatabaseDraftSink
from app.tools.errors import FatalToolError
from app.tools.gates import AuditRepositorySecurityAudit, DatabaseProvenanceStore, ToolGates
from app.tools.registry import ToolRegistry
from app.tools.types import started_display

HEARTBEAT_SECONDS: Final = 15.0


class TurnStreamingResponse(StreamingResponse):
    """发送阶段断开也显式关闭回合生成器，先收尾再释放请求级数据库会话。"""

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            with anyio.CancelScope(shield=True):
                close = getattr(self.body_iterator, "aclose", None)
                if close is not None:
                    await close()


HEARTBEAT_FRAME: Final = b": keep-alive\n\n"
SSE_HEADERS: Final = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}

RunTurn = Callable[[EventSink | None], Coroutine[Any, Any, dict[str, Any]]]


def wants_json(request: Request) -> bool:
    return "application/json" in request.headers.get("accept", "").lower()


def encode(event: str, payload: BaseModel) -> bytes:
    data = json.dumps(payload.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":"))
    return f"event: {event}\ndata: {data}\n\n".encode()


def build_gates(request: Request, database: Database, principal_secret: bytes) -> ToolGates:
    """用进程启动时自检过的注册表装配闸门；这里不再临时注册工具。"""

    registry: ToolRegistry = request.app.state.tool_registry
    return ToolGates(
        registry,
        provenance=DatabaseProvenanceStore(database),
        principal_secret=principal_secret,
        audit=AuditRepositorySecurityAudit(AuditRepository(database)),
        drafts=DatabaseDraftSink(database),
    )


async def stream_turn(
    session: AsyncSession,
    run: RunTurn,
    *,
    cancel: asyncio.Event,
    final_model: type[BaseModel],
    locale: SupportedLocale,
    request_id: str,
) -> AsyncIterator[bytes]:
    """响应头一旦发出，后续失败只能走 `event: error`；流以 `turn_complete` 或 `error` 收尾。"""

    events: asyncio.Queue[LoopEvent] = asyncio.Queue()

    async def sink(event: LoopEvent) -> None:
        await events.put(event)

    async def finish_turn() -> dict[str, Any]:
        # 回合任务拥有提交：即使传输层断开，也先保存已完成部分供幂等重放。
        try:
            body = await run(sink)
            final_model.model_validate(body)
            await session.commit()
            return body
        except FatalToolError:
            await session.commit()
            raise
        except BaseException:
            await session.rollback()
            raise

    task = asyncio.create_task(finish_turn())
    pending: asyncio.Task[LoopEvent] | None = None
    try:
        while True:
            pending = asyncio.create_task(events.get())
            done, _ = await asyncio.wait(
                {task, pending},
                timeout=HEARTBEAT_SECONDS,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if pending in done:
                yield project(pending.result(), locale)
                continue
            pending.cancel()
            if task in done:
                break
            yield HEARTBEAT_FRAME

        # 回合结束后把队列里剩下的事件补发完，再发最终事件。
        while not events.empty():
            yield project(events.get_nowait(), locale)
        try:
            body = task.result()
        except AppError as exc:
            yield error_frame(exc.code, exc.message_params, locale, request_id, exc.retryable)
            return
        except Exception:
            yield error_frame(ErrorCode.INTERNAL_ERROR, None, locale, request_id, True)
            return
        yield encode(SseEventName.TURN_COMPLETE.value, final_model.model_validate(body))
    finally:
        cancel.set()
        # Starlette 的断开取消是 AnyIO cancel scope；屏蔽它直到同一会话的收尾完成。
        # 不能直接 cancel 回合：已开始的写工具必须完成，然后由循环看到 cancel 停止。
        with anyio.CancelScope(shield=True):
            if pending is not None:
                pending.cancel()
                with suppress(asyncio.CancelledError):
                    await pending
            with suppress(Exception, asyncio.CancelledError):
                await asyncio.shield(task)


def project(event: LoopEvent, locale: SupportedLocale) -> bytes:
    """循环事件 → 契约事件。只有脱敏展示信息能走到这里。"""

    if isinstance(event, ToolCallStarted):
        return encode(
            SseEventName.TOOL_CALL.value,
            started_display(event.tool_name, event.call_id, locale),
        )
    assert isinstance(event, ToolCallFinished)
    return encode(SseEventName.TOOL_RESULT.value, event.display.result_event(locale))


def error_frame(
    code: ErrorCode,
    params: Any,
    locale: SupportedLocale,
    request_id: str,
    retryable: bool,
) -> bytes:
    return encode(
        SseEventName.ERROR.value,
        ErrorResponse(
            code=code,
            message=localize_error_message(code, params, locale),
            request_id=request_id,
            retryable=retryable,
        ),
    )
