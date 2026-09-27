"""SSE 实际取消路径必须收束回合，并保存可重放结果。"""

import asyncio
from unittest.mock import AsyncMock

import pytest
from pydantic import BaseModel

from app.agent.loop.runner import ToolCallStarted, run_loop
from app.api.routes.v2.chat_stream import TurnStreamingResponse, stream_turn
from app.llm.fake import FakeLlmClient
from app.localization.locales import SupportedLocale
from tests.unit.agent.loop import loop_doubles as doubles


class FinalBody(BaseModel):
    answer: str


@pytest.mark.asyncio
async def test_disconnect_signals_turn_and_waits_for_persistence() -> None:
    cancel = asyncio.Event()
    started = asyncio.Event()
    finished = asyncio.Event()
    session = AsyncMock()

    async def run(sink):  # type: ignore[no-untyped-def]
        started.set()
        await cancel.wait()
        finished.set()
        return {"answer": "partial"}

    stream = stream_turn(
        session,
        run,
        cancel=cancel,
        final_model=FinalBody,
        locale=SupportedLocale.ZH_CN,
        request_id="test",
    )
    consumer = asyncio.create_task(anext(stream))
    await asyncio.wait_for(started.wait(), timeout=2)
    consumer.cancel()
    with pytest.raises(asyncio.CancelledError):
        await consumer
    assert cancel.is_set() and finished.is_set()
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_disconnect_while_sending_frame_settles_before_response_returns():
    cancel = asyncio.Event()
    body_started = asyncio.Event()
    session = AsyncMock()

    async def run(sink):
        await sink(ToolCallStarted(tool_name="slow_write", call_id="c1"))
        await cancel.wait()
        return {"answer": "partial"}

    async def send(message):
        if message["type"] == "http.response.body":
            body_started.set()
            await asyncio.Event().wait()

    async def receive():
        await body_started.wait()
        return {"type": "http.disconnect"}

    stream = stream_turn(
        session,
        run,
        cancel=cancel,
        final_model=FinalBody,
        locale=SupportedLocale.ZH_CN,
        request_id="blocked-send",
    )
    response = TurnStreamingResponse(stream)
    try:
        await asyncio.wait_for(
            response({"type": "http", "asgi": {"spec_version": "2.3"}}, receive, send), 2
        )
        assert cancel.is_set()
        session.commit.assert_awaited_once()
    finally:
        await stream.aclose()


@pytest.mark.asyncio
async def test_invalid_response_rolls_back_before_success_commit() -> None:
    session = AsyncMock()

    async def run(sink):  # type: ignore[no-untyped-def]
        return {"wrong": "shape"}

    events = [
        frame
        async for frame in stream_turn(
            session,
            run,
            cancel=asyncio.Event(),
            final_model=FinalBody,
            locale=SupportedLocale.ZH_CN,
            request_id="test",
        )
    ]
    assert b"event: error" in events[-1]
    session.commit.assert_not_awaited()
    session.rollback.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_name", ["slow_read", "slow_write"])
@pytest.mark.parametrize("batch_size", [1, 2])
async def test_disconnect_settles_real_loop_tools(tool_name, batch_size, monkeypatch):
    probe = doubles.ToolProbe()
    monkeypatch.setattr(doubles, "PROBE", probe)
    cancel = asyncio.Event()
    session = AsyncMock()
    gates, _ = doubles.build_gates()
    request = doubles.customer_request()
    fake = FakeLlmClient(
        turns=[
            doubles.tool_use_turn(*(doubles.call(tool_name, label="x") for _ in range(batch_size)))
        ]
    )
    outcomes = []

    async def run(sink):
        result = await run_loop(
            request,
            llm=fake,
            gates=gates,
            tools=gates.registry.schemas_for(request.context.session.role),
            limits=doubles.limits(),
            on_event=sink,
            cancel=cancel,
        )
        outcomes.append(result)
        return {"answer": result.answer}

    async def consume():
        async for _ in stream_turn(
            session,
            run,
            cancel=cancel,
            final_model=FinalBody,
            locale=SupportedLocale.ZH_CN,
            request_id="disconnect-tools",
        ):
            pass

    consumer = asyncio.create_task(consume())
    await asyncio.wait_for(probe.first_started.wait(), timeout=2)
    consumer.cancel()
    with pytest.raises(asyncio.CancelledError):
        await consumer
    assert probe.active == 0
    assert probe.finished == (["x"] if tool_name == "slow_write" else [])
    assert len(fake.converse_calls) == 1
    assert outcomes[0].stop_reason == "CANCELLED"
    assert len(outcomes[0].tool_calls) == (1 if tool_name == "slow_write" else 0)
    session.commit.assert_awaited_once()
