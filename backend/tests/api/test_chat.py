"""Chat HTTP 与 SSE 契约测试。

分两层：
- 传输层用替身服务，专测 §8.4 的分帧、心跳、收尾和错误语义；
- 端到端层接真实 PostgreSQL 与真实 ChatService，证明路由确实接对了线。
"""

import asyncio
import json
import random
from collections.abc import Iterator
from uuid import UUID, uuid4

import anyio
import pytest
import structlog
from httpx import ASGITransport, AsyncClient

from app.agent.fake_agent import FakeAgent
from app.api.dependencies import get_chat_service
from app.api.routes import chat as chat_route
from app.core.config import Settings
from app.core.errors import IdempotencyKeyReusedError
from app.core.security import MerchantContext
from app.main import create_app
from app.schemas.chat import ChatRequest
from app.services.chat_service import ChatExecution
from tests.conftest import MERCHANT_ONE_AUTH

pytestmark = pytest.mark.asyncio

MERCHANT_ID = UUID("00000000-0000-0000-0000-000000000031")
SESSION_ID = UUID("00000000-0000-0000-0000-000000000032")
AUTH = {"Authorization": "Bearer merchant-token"}


class StubChatService:
    """可控替身：延迟、异常和重放都由测试指定。"""

    def __init__(self, *, delay: float = 0.0, error: BaseException | None = None) -> None:
        self._agent = FakeAgent()
        self._delay = delay
        self._error = error
        self._executions: dict[str, ChatExecution] = {}
        self.calls = 0

    async def submit(
        self,
        context: MerchantContext,
        request: ChatRequest,
        *,
        request_id: str,
    ) -> ChatExecution:
        del context, request_id
        self.calls += 1
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._error is not None:
            raise self._error
        existing = self._executions.get(request.client_request_id)
        if existing is not None:
            return existing
        result = await self._agent.run(request.message, request.session_id or SESSION_ID)
        execution = ChatExecution(response=result.response, steps=result.steps, replayed=False)
        self._executions[request.client_request_id] = execution
        return execution


class CancelAwareService:
    """模拟真实 ChatService：被取消时先把终态落库，再把 CancelledError 抛上去。"""

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.cleanup_started = False
        self.cleanup_finished = False

    async def submit(
        self,
        context: MerchantContext,
        request: ChatRequest,
        *,
        request_id: str,
    ) -> ChatExecution:
        del context, request, request_id
        self.started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cleanup_started = True
            # 代表 rollback + mark_answer_failed + commit 这几次数据库往返。
            await asyncio.sleep(0.05)
            self.cleanup_finished = True
            raise
        raise AssertionError("submit 不应该正常返回")


def stub_settings() -> Settings:
    return Settings(
        app_env="test",
        database_url="postgresql+psycopg://user:pass@localhost/test",
        frontend_origin="http://localhost:5173",
        demo_merchant_tokens={"merchant-token": MERCHANT_ID},
    )


async def stub_client(service: object | None = None) -> tuple[AsyncClient, object]:
    app = create_app(stub_settings())
    resolved = service or StubChatService()
    app.dependency_overrides[get_chat_service] = lambda: resolved
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")
    return client, app


def parse_sse(body: str) -> list[tuple[str, object]]:
    """把字节流解析成 (event, data) 序列；注释帧（心跳）不算业务事件。"""

    events: list[tuple[str, object]] = []
    for block in body.split("\n\n"):
        lines = [line for line in block.split("\n") if line]
        if not lines or all(line.startswith(":") for line in lines):
            continue
        name = next(line[len("event: ") :] for line in lines if line.startswith("event: "))
        data = next(line[len("data: ") :] for line in lines if line.startswith("data: "))
        events.append((name, json.loads(data)))
    return events


def heartbeat_count(body: str) -> int:
    return body.count(": keep-alive\n\n")


def chunked(payload: bytes, seed: int = 7) -> Iterator[bytes]:
    """按随机边界切块，可能切断 UTF-8 多字节字符和事件中部。"""

    rng = random.Random(seed)
    index = 0
    while index < len(payload):
        size = rng.randint(1, 9)
        yield payload[index : index + size]
        index += size


# --- 传输层 -------------------------------------------------------------


async def test_json_chat_equals_sse_done_payload() -> None:
    client, app = await stub_client()
    payload = {"message": "最近7天退货量趋势", "client_request_id": "request-chat-1"}

    async with client:
        json_response = await client.post(
            "/api/chat",
            headers={**AUTH, "Accept": "application/json"},
            json=payload,
        )
        sse_response = await client.post("/api/chat", headers=AUTH, json=payload)

    assert json_response.status_code == 200
    assert json_response.headers["content-type"].startswith("application/json")
    assert sse_response.headers["content-type"] == "text/event-stream; charset=utf-8"
    assert sse_response.headers["cache-control"] == "no-cache"
    assert sse_response.headers["x-accel-buffering"] == "no"

    events = parse_sse(sse_response.text)
    assert [name for name, _ in events][-1] == "done"
    assert [name for name, _ in events].count("step") >= 1
    assert events[-1][1] == json_response.json()
    await app.state.database.dispose()


async def test_sse_step_events_carry_only_label_and_node() -> None:
    client, app = await stub_client()

    async with client:
        response = await client.post(
            "/api/chat",
            headers=AUTH,
            json={"message": "最近7天退货量趋势", "client_request_id": "request-chat-steps"},
        )

    steps = [data for name, data in parse_sse(response.text) if name == "step"]
    assert steps
    for step in steps:
        assert set(step) == {"label", "node"}
        assert "SELECT" not in str(step).upper()
    await app.state.database.dispose()


async def test_sse_data_lines_never_span_multiple_lines() -> None:
    client, app = await stub_client()

    async with client:
        response = await client.post(
            "/api/chat",
            headers=AUTH,
            json={"message": "最近7天退货量趋势", "client_request_id": "request-chat-frame"},
        )

    for line in response.text.split("\n"):
        if line.startswith("data: "):
            json.loads(line[len("data: ") :])
    await app.state.database.dispose()


async def test_stream_emits_heartbeat_while_waiting_and_still_ends_with_done(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(chat_route, "HEARTBEAT_SECONDS", 0.02)
    client, app = await stub_client(StubChatService(delay=0.12))

    async with client:
        response = await client.post(
            "/api/chat",
            headers=AUTH,
            json={"message": "最近7天退货量趋势", "client_request_id": "request-chat-beat"},
        )

    assert heartbeat_count(response.text) >= 1
    names = [name for name, _ in parse_sse(response.text)]
    assert names[-1] == "done"
    assert names.count("done") == 1
    await app.state.database.dispose()


async def test_client_disconnect_waits_for_the_service_cleanup_to_finish(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """生成器不能一取消就返回。

    数据库 Session 由 yield 依赖在响应结束后关闭，提前放行会让 ChatService 的
    FAILED_RETRYABLE 写入落在正在关闭的 Session 上，PROCESSING 行就此残留。
    """

    monkeypatch.setattr(chat_route, "HEARTBEAT_SECONDS", 0.01)
    service = CancelAwareService()
    stream = chat_route._sse_body(
        service,
        MerchantContext(merchant_id=MERCHANT_ID),
        ChatRequest(message="最近7天退货量趋势", client_request_id="request-chat-abort"),
        "request-abort",
        structlog.get_logger(),
    )

    assert await stream.__anext__() == b": keep-alive\n\n"
    await service.started.wait()

    await stream.aclose()

    assert service.cleanup_started is True
    assert service.cleanup_finished is True


async def test_cleanup_finishes_even_inside_a_cancelled_cancel_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """复现真实断连：生成器在一个已取消的 anyio 取消域里被关闭。

    Starlette 的取消域是电平触发的：域一旦取消，域内每个 await 都会重新
    抛 CancelledError。没有 shield 时，`_await_cleanup` 里的 await 会被立刻打断，
    ChatService 的 FAILED_RETRYABLE 写入就会落在正在关闭的 Session 上。
    """

    monkeypatch.setattr(chat_route, "HEARTBEAT_SECONDS", 0.01)
    service = CancelAwareService()
    stream = chat_route._sse_body(
        service,
        MerchantContext(merchant_id=MERCHANT_ID),
        ChatRequest(message="最近7天退货量趋势", client_request_id="request-chat-scope"),
        "request-scope",
        structlog.get_logger(),
    )

    assert await stream.__anext__() == b": keep-alive\n\n"
    await service.started.wait()

    with anyio.CancelScope() as scope:
        scope.cancel()
        await stream.aclose()

    assert service.cleanup_finished is True


async def test_service_failure_after_headers_becomes_an_error_event() -> None:
    client, app = await stub_client(StubChatService(error=IdempotencyKeyReusedError()))

    async with client:
        response = await client.post(
            "/api/chat",
            headers=AUTH,
            json={"message": "最近7天退货量趋势", "client_request_id": "request-chat-error"},
        )

    # 响应头已经发出，所以 HTTP 状态码只能是 200，错误走 event: error。
    assert response.status_code == 200
    events = parse_sse(response.text)
    assert [name for name, _ in events] == ["error"]
    assert events[0][1]["code"] == "IDEMPOTENCY_KEY_REUSED"
    assert events[0][1]["request_id"]
    await app.state.database.dispose()


async def test_unexpected_failure_reports_a_safe_error_event() -> None:
    client, app = await stub_client(StubChatService(error=RuntimeError("secret internals")))

    async with client:
        response = await client.post(
            "/api/chat",
            headers=AUTH,
            json={"message": "最近7天退货量趋势", "client_request_id": "request-chat-boom"},
        )

    events = parse_sse(response.text)
    assert [name for name, _ in events] == ["error"]
    assert events[0][1]["code"] == "INTERNAL_ERROR"
    assert events[0][1]["retryable"] is True
    assert "secret internals" not in response.text
    await app.state.database.dispose()


async def test_json_path_keeps_http_error_semantics() -> None:
    client, app = await stub_client(StubChatService(error=IdempotencyKeyReusedError()))

    async with client:
        response = await client.post(
            "/api/chat",
            headers={**AUTH, "Accept": "application/json"},
            json={"message": "最近7天退货量趋势", "client_request_id": "request-chat-409"},
        )

    assert response.status_code == 409
    assert response.json()["code"] == "IDEMPOTENCY_KEY_REUSED"
    await app.state.database.dispose()


async def test_chat_authentication_failure_happens_before_stream_start() -> None:
    client, app = await stub_client()

    async with client:
        response = await client.post(
            "/api/chat",
            json={"message": "你好", "client_request_id": "request-chat-2"},
        )

    assert response.status_code == 401
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["code"] == "AUTH_REQUIRED"
    await app.state.database.dispose()


async def test_invalid_request_body_is_rejected_before_stream_start() -> None:
    client, app = await stub_client()

    async with client:
        empty_message = await client.post(
            "/api/chat",
            headers=AUTH,
            json={"message": "   ", "client_request_id": "request-chat-3"},
        )
        with_attachment = await client.post(
            "/api/chat",
            headers=AUTH,
            json={
                "message": "你好",
                "client_request_id": "request-chat-4",
                "attachment_ids": [str(uuid4())],
            },
        )

    for response in (empty_message, with_attachment):
        assert response.status_code == 422
        assert response.headers["content-type"].startswith("application/json")
        assert response.json()["code"] == "INVALID_REQUEST"
    await app.state.database.dispose()


async def test_stream_survives_being_split_on_random_byte_boundaries() -> None:
    """§8.4 必测：客户端必须能按字节流累积解析，不能假设一次读到一个完整事件。"""

    client, app = await stub_client()

    async with client:
        response = await client.post(
            "/api/chat",
            headers=AUTH,
            json={"message": "最近7天退货量趋势", "client_request_id": "request-chat-chunk"},
        )

    raw = response.content
    assert "退货" in raw.decode("utf-8")

    buffer = b""
    decoded_blocks: list[str] = []
    for chunk in chunked(raw):
        buffer += chunk
        while b"\n\n" in buffer:
            block, buffer = buffer.split(b"\n\n", 1)
            decoded_blocks.append(block.decode("utf-8"))

    assert buffer == b""
    reassembled = "".join(f"{block}\n\n" for block in decoded_blocks)
    assert reassembled == raw.decode("utf-8")
    assert parse_sse(reassembled) == parse_sse(raw.decode("utf-8"))
    await app.state.database.dispose()


# --- 端到端（真实 ChatService + PostgreSQL） -----------------------------


async def test_end_to_end_chat_persists_and_replays_by_client_request_id(
    postgres_client: AsyncClient,
) -> None:
    payload = {"message": "最近7天退货量趋势", "client_request_id": "e2e-1"}
    headers = {**MERCHANT_ONE_AUTH, "Accept": "application/json"}

    first = await postgres_client.post("/api/chat", headers=headers, json=payload)
    replay = await postgres_client.post("/api/chat", headers=headers, json=payload)

    assert first.status_code == 200
    assert replay.status_code == 200
    assert replay.json() == first.json()
    assert first.json()["answer_mode"] == "METRIC"
    assert first.json()["analysis_sources"] == ["FALLBACK"]
    assert first.json()["degraded"] is True


async def test_end_to_end_reused_key_with_new_message_conflicts(
    postgres_client: AsyncClient,
) -> None:
    headers = {**MERCHANT_ONE_AUTH, "Accept": "application/json"}
    await postgres_client.post(
        "/api/chat",
        headers=headers,
        json={"message": "昨天总 GMV 是多少？", "client_request_id": "e2e-conflict"},
    )

    response = await postgres_client.post(
        "/api/chat",
        headers=headers,
        json={"message": "最近7天退货量趋势", "client_request_id": "e2e-conflict"},
    )

    assert response.status_code == 409
    assert response.json()["code"] == "IDEMPOTENCY_KEY_REUSED"


async def test_end_to_end_sse_matches_the_json_payload(
    postgres_client: AsyncClient,
) -> None:
    stream = await postgres_client.post(
        "/api/chat",
        headers=MERCHANT_ONE_AUTH,
        json={"message": "昨天总 GMV 是多少？", "client_request_id": "e2e-sse"},
    )
    replay = await postgres_client.post(
        "/api/chat",
        headers={**MERCHANT_ONE_AUTH, "Accept": "application/json"},
        json={"message": "昨天总 GMV 是多少？", "client_request_id": "e2e-sse"},
    )

    events = parse_sse(stream.text)
    assert [name for name, _ in events][-1] == "done"
    assert events[-1][1] == replay.json()


async def test_end_to_end_stream_stays_readable_as_an_async_byte_stream(
    postgres_client: AsyncClient,
) -> None:
    received: list[bytes] = []
    async with postgres_client.stream(
        "POST",
        "/api/chat",
        headers=MERCHANT_ONE_AUTH,
        json={"message": "最近7天退货量趋势", "client_request_id": "e2e-stream"},
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/event-stream; charset=utf-8"
        async for chunk in response.aiter_bytes():
            received.append(chunk)

    events = parse_sse(b"".join(received).decode("utf-8"))
    assert [name for name, _ in events][-1] == "done"
    assert events[-1][1]["answer_mode"] == "METRIC"
    assert events[-1][1]["category"] == "REFUND"
