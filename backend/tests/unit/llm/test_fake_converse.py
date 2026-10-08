"""``FakeLlmClient.converse()`` 的工具调用脚本。

这是 N2 全部循环测试的基础设施：没有它，工具循环的轮数上限、并行、致命错误终止
都没法在 CI 里零费用地验证。
"""

from __future__ import annotations

import pytest

from app.llm.client import (
    STRUCTURED_CALL_OPTIONS,
    LlmBudget,
    LlmBudgetExceededError,
    LlmMessage,
    LlmToolCall,
    LlmTurn,
    LlmUnavailableError,
    TextDelta,
    ToolSchema,
    TurnComplete,
)
from app.llm.fake import FakeLlmClient, FakeScriptExhaustedError


def _budget() -> LlmBudget:
    return LlmBudget(max_calls=10, max_tokens=1_000)


def _search_turn() -> LlmTurn:
    return LlmTurn(
        text=None,
        tool_calls=[LlmToolCall("c1", "search_products", '{"q":"壶"}')],
        stop_reason="TOOL_USE",
        tokens=20,
    )


def _answer_turn() -> LlmTurn:
    return LlmTurn(text="本店有 2 款…", tool_calls=[], stop_reason="END_TURN", tokens=30)


async def test_scripted_turns_are_returned_in_order() -> None:
    client = FakeLlmClient(turns=[_search_turn(), _answer_turn()])
    messages = [LlmMessage(role="user", content="找个壶")]

    first = await client.converse(messages=messages, tools=[], budget=_budget())
    second = await client.converse(messages=messages, tools=[], budget=_budget())

    assert first.stop_reason == "TOOL_USE" and first.tool_calls[0].tool_name == "search_products"
    assert second.stop_reason == "END_TURN" and second.text == "本店有 2 款…"


async def test_exhausted_script_fails_loudly_instead_of_inventing_a_turn() -> None:
    """脚本耗尽说明循环比测试预期多调了一次：静默编造回合会掩盖这个缺陷。"""

    client = FakeLlmClient(turns=[_answer_turn()])
    await client.converse(messages=[], tools=[], budget=_budget())

    with pytest.raises(FakeScriptExhaustedError, match="第 2 次"):
        await client.converse(messages=[], tools=[], budget=_budget())


def test_script_exhaustion_is_an_assertion_error_so_pytest_reports_it_as_a_failure() -> None:
    assert issubclass(FakeScriptExhaustedError, AssertionError)


async def test_calls_are_recorded_with_messages_tools_and_options() -> None:
    client = FakeLlmClient(turns=[_answer_turn()])
    tool = ToolSchema(name="search_products", description="搜索", parameters={"type": "object"})
    messages = [LlmMessage(role="user", content="找个壶")]

    await client.converse(
        messages=messages, tools=[tool], budget=_budget(), options=STRUCTURED_CALL_OPTIONS
    )

    (call,) = client.converse_calls
    assert call.messages == messages and call.tools == [tool]
    assert call.options == STRUCTURED_CALL_OPTIONS


async def test_recorded_messages_are_a_snapshot_not_a_live_reference() -> None:
    """循环会在两轮之间往同一个列表里追加消息；快照才能看出每一轮真正收到了什么。"""

    client = FakeLlmClient(turns=[_search_turn(), _answer_turn()])
    history = [LlmMessage(role="user", content="找个壶")]

    await client.converse(messages=history, tools=[], budget=_budget())
    history.append(LlmMessage(role="tool", content="{}", tool_call_id="c1"))
    await client.converse(messages=history, tools=[], budget=_budget())

    assert [len(c.messages) for c in client.converse_calls] == [1, 2]


async def test_calls_and_tokens_are_charged_against_the_budget() -> None:
    client = FakeLlmClient(turns=[_search_turn(), _answer_turn()])
    tracked = _budget()

    await client.converse(messages=[], tools=[], budget=tracked)
    await client.converse(messages=[], tools=[], budget=tracked)

    assert (tracked.calls, tracked.tokens) == (2, 50)


async def test_call_budget_stops_the_loop_like_the_real_adapters() -> None:
    client = FakeLlmClient(turns=[_answer_turn()])

    with pytest.raises(LlmBudgetExceededError):
        await client.converse(
            messages=[], tools=[], budget=LlmBudget(max_calls=0, max_tokens=1_000)
        )

    assert client.converse_calls == []  # 与真实适配器一样，预算耗尽时这次调用没有发生


async def test_unconfigured_client_raises_an_explicit_unavailable_error() -> None:
    client = FakeLlmClient(turns=[_answer_turn()], configured=False)

    with pytest.raises(LlmUnavailableError):
        await client.converse(messages=[], tools=[], budget=_budget())


async def test_scripted_degraded_turn_is_returned_untouched() -> None:
    degraded = LlmTurn(text=None, tool_calls=[], stop_reason="ERROR", tokens=0, degraded=True)
    client = FakeLlmClient(turns=[degraded])

    turn = await client.converse(messages=[], tools=[], budget=_budget())

    assert turn is degraded


async def test_stream_yields_the_text_then_the_final_turn() -> None:
    client = FakeLlmClient(turns=[_answer_turn()])

    events = [e async for e in client.converse_stream(messages=[], tools=[], budget=_budget())]

    assert events[0] == TextDelta(text="本店有 2 款…")
    assert isinstance(events[-1], TurnComplete) and events[-1].turn.text == "本店有 2 款…"
    assert len(events) == 2


async def test_stream_of_a_tool_call_turn_yields_no_text_delta() -> None:
    client = FakeLlmClient(turns=[_search_turn()])

    events = [e async for e in client.converse_stream(messages=[], tools=[], budget=_budget())]

    assert len(events) == 1 and isinstance(events[0], TurnComplete)


async def test_converse_and_complete_scripts_are_independent() -> None:
    """v1 用 responses、v2 用 turns；一个的消耗不能吃掉另一个的脚本。"""

    client = FakeLlmClient(responses=["v1 回答"], turns=[_answer_turn()])

    v1 = await client.complete(system="s", user="u", fallback="f", budget=_budget())
    v2 = await client.converse(messages=[], tools=[], budget=_budget())

    assert v1.text == "v1 回答" and v2.text == "本店有 2 款…"
