"""上游工具调用 ID 必须先于 SSE 事件和工具执行通过公开契约校验。"""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.agent.loop.runner import ToolCallFinished, ToolCallStarted, run_loop
from app.api.routes.v2.chat_stream import project
from app.llm.client import LlmToolCall
from app.llm.fake import FakeLlmClient
from app.localization.locales import SupportedLocale
from app.services.quality_types import DegradeReason
from app.services.v2.shop_chat import ShopChatService

from .loop_doubles import PROBE, build_gates, customer_request, limits, tool_use_turn


@pytest.mark.parametrize("bad_id", ["bad.id", "x" * 65, ""])
async def test_invalid_upstream_call_id_degrades_json_response(bad_id: str) -> None:
    request = customer_request()
    gates, _ = build_gates()
    probe_before = list(PROBE.started)
    llm = FakeLlmClient(
        turns=[
            tool_use_turn(
                LlmToolCall(call_id=bad_id, tool_name="slow_read", arguments_json='{"label":"x"}')
            )
        ]
    )

    outcome = await run_loop(
        request,
        llm=llm,
        gates=gates,
        tools=gates.registry.schemas_for(request.context.session.role),
        limits=limits(),
    )
    response = ShopChatService(
        None,  # type: ignore[arg-type]  # 只调用无数据库依赖的响应投影
        llm=llm,
        gates=gates,
        limits=limits(),
        ctx=request.context.session,
    )._to_response(outcome, uuid4())

    assert outcome.stop_reason == "UPSTREAM"
    assert outcome.degraded_reason is DegradeReason.UPSTREAM
    assert response.degraded is True
    assert response.degraded_reason == "UPSTREAM"
    assert response.answer.strip()
    assert response.quality_notes
    assert response.tool_calls == []
    assert PROBE.started == probe_before


@pytest.mark.parametrize("bad_id", ["bad.id", "x" * 65])
async def test_invalid_id_prevents_all_events_and_execution_in_same_batch(bad_id: str) -> None:
    request = customer_request()
    gates, _ = build_gates()
    probe_before = list(PROBE.started)
    frames: list[bytes] = []

    async def sink(event: ToolCallStarted | ToolCallFinished) -> None:
        frames.append(project(event, SupportedLocale.ZH_CN))

    outcome = await run_loop(
        request,
        llm=FakeLlmClient(
            turns=[
                tool_use_turn(
                    LlmToolCall(
                        call_id="good_1", tool_name="slow_read", arguments_json='{"label":"ok"}'
                    ),
                    LlmToolCall(
                        call_id=bad_id, tool_name="slow_read", arguments_json='{"label":"bad"}'
                    ),
                )
            ]
        ),
        gates=gates,
        tools=gates.registry.schemas_for(request.context.session.role),
        limits=limits(),
        on_event=sink,
    )

    assert outcome.stop_reason == "UPSTREAM"
    assert outcome.tool_calls == []
    assert frames == []
    assert PROBE.started == probe_before
