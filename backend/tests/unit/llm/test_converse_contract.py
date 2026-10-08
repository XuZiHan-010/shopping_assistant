"""`converse()` 协议层契约：数据类的构造期不变量与 v1 `complete()` 的稳定性。

这里只测 `app/llm/client.py` 的纯数据与协议，不涉及任何适配器或网络。
"""

from __future__ import annotations

import dataclasses
import inspect

import pytest

from app.llm.client import (
    LlmClient,
    LlmMessage,
    LlmToolCall,
    LlmTurn,
    ReasoningReplay,
    TextDelta,
    ToolSchema,
    TurnComplete,
)


def test_tool_message_requires_call_id() -> None:
    with pytest.raises(ValueError, match="tool_call_id"):
        LlmMessage(role="tool", content="{}")


def test_tool_message_with_call_id_is_accepted() -> None:
    message = LlmMessage(role="tool", content="{}", tool_call_id="c1")
    assert message.tool_call_id == "c1"


def test_tool_call_keeps_arguments_as_raw_string() -> None:
    """适配器不解析参数——解析与校验属于工具注册表（R4）。"""

    tc = LlmToolCall(call_id="c1", tool_name="search", arguments_json='{"q":1}')

    assert isinstance(tc.arguments_json, str)
    assert not hasattr(tc, "arguments")


def test_turn_with_tool_use_must_carry_tool_calls() -> None:
    with pytest.raises(ValueError, match="TOOL_USE"):
        LlmTurn(text=None, tool_calls=[], stop_reason="TOOL_USE", tokens=10)


def test_turn_with_end_turn_must_carry_text() -> None:
    with pytest.raises(ValueError, match="END_TURN"):
        LlmTurn(text=None, tool_calls=[], stop_reason="END_TURN", tokens=10)


def test_end_turn_with_empty_text_is_still_a_text_turn() -> None:
    """空串是「模型返回了空内容」，由调用方降级；`None` 才是「根本没有文本」。"""

    turn = LlmTurn(text="", tool_calls=[], stop_reason="END_TURN", tokens=1)

    assert turn.text == ""


def test_max_tokens_and_error_turns_need_no_text() -> None:
    assert LlmTurn(text=None, tool_calls=[], stop_reason="MAX_TOKENS", tokens=1).text is None
    assert LlmTurn(text=None, tool_calls=[], stop_reason="ERROR", tokens=0).text is None


def test_unreported_cache_usage_is_none_not_zero() -> None:
    """缓存未上报记 None：记成 0 会让成本估算误以为全部未命中。"""

    turn = LlmTurn(text="x", tool_calls=[], stop_reason="END_TURN", tokens=1)

    assert turn.cache_hit_tokens is None
    assert turn.cache_miss_tokens is None


def test_turn_defaults_describe_a_healthy_unmetered_turn() -> None:
    turn = LlmTurn(text="x", tool_calls=[], stop_reason="END_TURN", tokens=1)

    assert turn.degraded is False
    assert turn.failure_kind is None
    assert turn.usage_known is False
    assert turn.reasoning is None


def test_reasoning_replay_is_bound_to_a_protocol() -> None:
    replay = ReasoningReplay(protocol="openai", payload="先搜索商品")

    assert (replay.protocol, replay.payload) == ("openai", "先搜索商品")


def test_data_classes_are_immutable() -> None:
    """消息历史会被多轮循环反复回放，被就地改写会让回放与真实响应对不上。"""

    message = LlmMessage(role="user", content="x")
    with pytest.raises(dataclasses.FrozenInstanceError):
        message.content = "y"  # type: ignore[misc]


def test_stream_events_carry_text_or_the_final_turn() -> None:
    turn = LlmTurn(text="好", tool_calls=[], stop_reason="END_TURN", tokens=1)

    assert TextDelta(text="好").text == "好"
    assert TurnComplete(turn=turn).turn is turn


def test_tool_schema_carries_json_schema_parameters() -> None:
    schema = ToolSchema(
        name="search", description="搜索商品", parameters={"type": "object", "properties": {}}
    )

    assert schema.parameters["type"] == "object"


def test_existing_complete_signature_unchanged() -> None:
    """v1 的既有测试依赖它，签名不得变动。"""

    sig = inspect.signature(LlmClient.complete)

    assert list(sig.parameters) == ["self", "system", "user", "fallback", "budget", "options"]


def test_v1_protocol_gains_no_new_required_method() -> None:
    """`LlmCostGuard` 等 v1 实现按结构满足 `LlmClient`；给它加方法会让它们全部失去资格。

    工具调用能力由子协议承载，见 `ConversationalLlmClient`。
    """

    members = {name for name in dir(LlmClient) if not name.startswith("_")}

    assert members == {"is_configured", "complete"}
