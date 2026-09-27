"""多轮工具历史的请求体。

单轮 mock 只证明「能解析一次响应」，证明不了「第二轮请求发得对」——而思考模式下
第二轮须按文档回传 ``reasoning_content``（文档称缺了会 400；2026-09-22 实测未被拒，
但回放仍是契约）。所以这里专测**出站请求体**。
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.core.config import Settings
from app.llm.anthropic_adapter import AnthropicConverseAdapter, serialize_anthropic_messages
from app.llm.client import LlmMessage, LlmToolCall, ReasoningReplay
from app.llm.openai_adapter import OpenAiConverseAdapter, serialize_openai_messages
from tests.unit.llm._transport import (
    SEARCH_TOOL,
    budget,
    recording_transport,
    request_body,
)


def _ok_openai() -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [{"finish_reason": "stop", "message": {"content": "找到了"}}],
            "usage": {"total_tokens": 3, "prompt_tokens": 2, "completion_tokens": 1},
        },
    )


def _search_round(reasoning: ReasoningReplay | None) -> list[LlmMessage]:
    return [
        LlmMessage(role="user", content="找个壶"),
        LlmMessage(
            role="assistant",
            content="",
            tool_calls=[LlmToolCall("c1", "search", '{"q":"壶"}')],
            reasoning=reasoning,
        ),
        LlmMessage(role="tool", content='{"items":[]}', tool_call_id="c1"),
    ]


# --------------------------------------------------------------------- OpenAI


async def test_openai_second_round_replays_tool_calls_results_and_reasoning(
    settings: Settings,
) -> None:
    transport, seen = recording_transport(_ok_openai())

    await OpenAiConverseAdapter(settings, transport=transport).converse(
        messages=_search_round(ReasoningReplay("openai", "先搜索商品")),
        tools=[SEARCH_TOOL],
        budget=budget(),
    )

    messages = request_body(seen[0])["messages"]
    assert isinstance(messages, list)
    assistant = messages[1]
    assert assistant["tool_calls"][0]["id"] == "c1"
    assert assistant["tool_calls"][0]["type"] == "function"
    assert assistant["tool_calls"][0]["function"]["name"] == "search"
    assert assistant["tool_calls"][0]["function"]["arguments"] == '{"q":"壶"}'  # 原串，不重新序列化
    assert assistant["reasoning_content"] == "先搜索商品"  # 按文档必须回传
    assert messages[2] == {"role": "tool", "tool_call_id": "c1", "content": '{"items":[]}'}


def test_reasoning_from_other_protocol_is_rejected() -> None:
    """推理回放绑定协议：Anthropic 的 thinking 块 JSON 塞进 OpenAI 的 reasoning_content，
    上游无法解读。"""

    with pytest.raises(ValueError, match="协议"):
        serialize_openai_messages(
            [
                LlmMessage(
                    role="assistant", content="x", reasoning=ReasoningReplay("anthropic", "{}")
                )
            ]
        )


def test_openai_assistant_tool_call_turn_sends_null_content() -> None:
    """原样回放 API 自己返回的形状：带工具调用而没有正文时，content 是 null。"""

    (_, assistant, _) = serialize_openai_messages(_search_round(None))

    assert assistant["content"] is None


def test_openai_plain_assistant_turn_has_no_tool_or_reasoning_keys() -> None:
    (message,) = serialize_openai_messages([LlmMessage(role="assistant", content="你好")])

    assert message == {"role": "assistant", "content": "你好"}


def test_openai_empty_tool_calls_list_is_the_same_as_none() -> None:
    (message,) = serialize_openai_messages(
        [LlmMessage(role="assistant", content="你好", tool_calls=[])]
    )

    assert "tool_calls" not in message


def test_openai_parallel_tool_results_stay_separate_messages() -> None:
    serialized = serialize_openai_messages(
        [
            LlmMessage(role="tool", content="a", tool_call_id="c1"),
            LlmMessage(role="tool", content="b", tool_call_id="c2"),
        ]
    )

    assert [m["tool_call_id"] for m in serialized] == ["c1", "c2"]


def test_openai_system_and_user_messages_pass_through() -> None:
    serialized = serialize_openai_messages(
        [LlmMessage(role="system", content="你是助手"), LlmMessage(role="user", content="你好")]
    )

    assert serialized == [
        {"role": "system", "content": "你是助手"},
        {"role": "user", "content": "你好"},
    ]


def test_openai_replays_malformed_arguments_verbatim() -> None:
    """历史里的畸形参数是模型当时真实产出的，回放必须保持原样，不替它「修好」。"""

    (message,) = serialize_openai_messages(
        [LlmMessage(role="assistant", content="", tool_calls=[LlmToolCall("c1", "s", "{bad")])]
    )

    assert json.dumps(message["tool_calls"][0]["function"]["arguments"]) == '"{bad"'


async def test_serialization_errors_surface_before_any_budget_is_spent(
    settings: Settings,
) -> None:
    """本地的构造错误是调用方的 bug，不应被吞成「上游降级」，更不该白扣一次配额。"""

    transport, seen = recording_transport()
    tracked = budget()

    with pytest.raises(ValueError, match="协议"):
        await OpenAiConverseAdapter(settings, transport=transport).converse(
            messages=[
                LlmMessage(
                    role="assistant", content="x", reasoning=ReasoningReplay("anthropic", "[]")
                )
            ],
            tools=[],
            budget=tracked,
        )

    assert seen == [] and tracked.calls == 0


# ------------------------------------------------------------------ Anthropic


def _anthropic_thinking(signature: str = "sig-1") -> ReasoningReplay:
    block = {"type": "thinking", "thinking": "先搜索商品", "signature": signature}
    return ReasoningReplay("anthropic", json.dumps([block]))


def _ok_anthropic() -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "content": [{"type": "text", "text": "找到了"}],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 2, "output_tokens": 1},
        },
    )


async def test_anthropic_second_round_sends_tool_result_blocks_and_thinking(
    settings: Settings,
) -> None:
    """多轮：assistant 的 thinking 与 tool_use 块、user 的 tool_result 块，按原样回放。"""

    transport, seen = recording_transport(_ok_anthropic())

    await AnthropicConverseAdapter(settings, transport=transport).converse(
        messages=_search_round(_anthropic_thinking()), tools=[SEARCH_TOOL], budget=budget()
    )

    messages = request_body(seen[0])["messages"]
    assert isinstance(messages, list)
    assistant_blocks = messages[1]["content"]
    assert messages[1]["role"] == "assistant"
    assert assistant_blocks[0] == {
        "type": "thinking",
        "thinking": "先搜索商品",
        "signature": "sig-1",
    }
    assert {
        "type": "tool_use",
        "id": "c1",
        "name": "search",
        "input": {"q": "壶"},
    } in assistant_blocks
    assert messages[2]["role"] == "user"
    assert messages[2]["content"][0] == {
        "type": "tool_result",
        "tool_use_id": "c1",
        "content": '{"items":[]}',
    }


def test_anthropic_reasoning_from_other_protocol_is_rejected() -> None:
    with pytest.raises(ValueError, match="协议"):
        serialize_anthropic_messages(
            [LlmMessage(role="assistant", content="x", reasoning=ReasoningReplay("openai", "想"))]
        )


@pytest.mark.parametrize("payload", ["not json", '{"type":"thinking"}', "[1, 2]"])
def test_anthropic_reasoning_payload_must_be_a_list_of_blocks(payload: str) -> None:
    with pytest.raises(ValueError, match="thinking"):
        serialize_anthropic_messages(
            [
                LlmMessage(
                    role="assistant", content="x", reasoning=ReasoningReplay("anthropic", payload)
                )
            ]
        )


def test_anthropic_parallel_tool_results_merge_into_one_user_message() -> None:
    """Anthropic 要求角色交替：同一轮的多个工具结果必须放进同一条 user 消息。"""

    _, messages = serialize_anthropic_messages(
        [
            LlmMessage(role="user", content="找壶和杯"),
            LlmMessage(
                role="assistant",
                content="",
                tool_calls=[
                    LlmToolCall("c1", "search", '{"q":"壶"}'),
                    LlmToolCall("c2", "search", '{"q":"杯"}'),
                ],
            ),
            LlmMessage(role="tool", content="a", tool_call_id="c1"),
            LlmMessage(role="tool", content="b", tool_call_id="c2"),
        ]
    )

    assert [m["role"] for m in messages] == ["user", "assistant", "user"]
    assert [b["tool_use_id"] for b in messages[2]["content"]] == ["c1", "c2"]


def test_anthropic_assistant_text_precedes_tool_use_blocks() -> None:
    _, messages = serialize_anthropic_messages(
        [
            LlmMessage(
                role="assistant",
                content="我来查",
                tool_calls=[LlmToolCall("c1", "search", "{}")],
            )
        ]
    )

    assert [b["type"] for b in messages[0]["content"]] == ["text", "tool_use"]


def test_anthropic_plain_assistant_turn_stays_a_string() -> None:
    _, messages = serialize_anthropic_messages([LlmMessage(role="assistant", content="你好")])

    assert messages == [{"role": "assistant", "content": "你好"}]


def test_anthropic_multiple_system_messages_are_joined_at_top_level() -> None:
    system, messages = serialize_anthropic_messages(
        [
            LlmMessage(role="system", content="甲"),
            LlmMessage(role="user", content="你好"),
            LlmMessage(role="system", content="乙"),
        ]
    )

    assert system == "甲\n\n乙"
    assert [m["role"] for m in messages] == ["user"]


def test_anthropic_without_system_messages_returns_none() -> None:
    system, _ = serialize_anthropic_messages([LlmMessage(role="user", content="你好")])

    assert system is None


@pytest.mark.parametrize("arguments", ["{bad", "[1]", '"text"'])
def test_anthropic_tool_use_input_must_be_a_json_object(arguments: str) -> None:
    """Anthropic 的 ``input`` 只能是对象；历史里放不进去的参数不能悄悄改写成别的东西。"""

    with pytest.raises(ValueError, match="tool_use"):
        serialize_anthropic_messages(
            [
                LlmMessage(
                    role="assistant",
                    content="",
                    tool_calls=[LlmToolCall("c1", "search", arguments)],
                )
            ]
        )
