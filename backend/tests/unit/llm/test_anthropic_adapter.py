"""DeepSeek Anthropic 兼容协议适配器；全部走 ``httpx.MockTransport``，零费用。

协议地址 ``https://api.deepseek.com/anthropic``；``LLM_BASE_URL`` 仍存根地址，
``/anthropic`` 由适配器内部拼接（AGENTS.md R3）。
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.core.config import Settings
from app.llm.anthropic_adapter import AnthropicConverseAdapter
from app.llm.client import (
    STRUCTURED_CALL_OPTIONS,
    LlmBudget,
    LlmBudgetExceededError,
    LlmCallOptions,
    LlmFailureKind,
    LlmMessage,
    LlmUnavailableError,
)
from tests.unit.llm._transport import (
    ANTHROPIC_URL,
    SEARCH_TOOL,
    budget,
    hello,
    make_settings,
    recording_transport,
    request_body,
)


def _message(
    content: list[dict[str, object]],
    stop_reason: str = "end_turn",
    usage: dict[str, object] | None = None,
) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "content": content,
            "stop_reason": stop_reason,
            "usage": {"input_tokens": 10, "output_tokens": 5} if usage is None else usage,
        },
    )


def _text_response(text: str = "好的") -> httpx.Response:
    return _message([{"type": "text", "text": text}])


def _tool_use(call_id: str, name: str, arguments: object) -> dict[str, object]:
    return {"type": "tool_use", "id": call_id, "name": name, "input": arguments}


async def test_system_goes_to_top_level_not_messages(settings: Settings) -> None:
    transport, seen = recording_transport(_text_response())

    await AnthropicConverseAdapter(settings, transport=transport).converse(
        messages=[
            LlmMessage(role="system", content="你是助手"),
            LlmMessage(role="user", content="你好"),
        ],
        tools=[],
        budget=LlmBudget(max_calls=5, max_tokens=1000),
    )

    assert str(seen[0].url) == ANTHROPIC_URL
    body = request_body(seen[0])
    assert body["system"] == "你是助手"
    messages = body["messages"]
    assert isinstance(messages, list)
    assert all(m["role"] != "system" for m in messages)


async def test_request_uses_api_key_header_and_version_not_bearer(settings: Settings) -> None:
    transport, seen = recording_transport(_text_response())

    await AnthropicConverseAdapter(settings, transport=transport).converse(
        messages=hello(), tools=[], budget=budget()
    )

    assert seen[0].headers["x-api-key"] == "test-key"
    assert seen[0].headers["anthropic-version"] == "2023-06-01"
    assert "authorization" not in seen[0].headers


async def test_total_tokens_is_summed_and_cache_defaults_to_none(settings: Settings) -> None:
    """Anthropic 格式没有 total_tokens，必须相加；文档未列缓存字段，未上报即 None。"""

    transport, _ = recording_transport(_text_response("x"))

    turn = await AnthropicConverseAdapter(settings, transport=transport).converse(
        messages=hello(), tools=[], budget=budget()
    )

    assert turn.tokens == 15 and turn.usage_known is True
    assert (turn.input_tokens, turn.output_tokens) == (10, 5)
    assert turn.cache_hit_tokens is None and turn.cache_miss_tokens is None


@pytest.mark.parametrize(
    "usage",
    [{"input_tokens": 10}, {"output_tokens": 5}, {}],
    ids=["only-input", "only-output", "empty"],
)
async def test_partial_usage_is_not_known(settings: Settings, usage: dict[str, object]) -> None:
    """总数要靠两个字段相加；缺一个就不能宣称用量已知，否则会少记成本。"""

    transport, _ = recording_transport(_message([{"type": "text", "text": "x"}], usage=usage))

    turn = await AnthropicConverseAdapter(settings, transport=transport).converse(
        messages=hello(), tools=[], budget=budget()
    )

    assert turn.usage_known is False


async def test_tool_use_block_is_mapped(settings: Settings) -> None:
    transport, _ = recording_transport(
        _message(
            [_tool_use("c1", "search", {"q": "壶"})],
            "tool_use",
            {"input_tokens": 1, "output_tokens": 1},
        )
    )

    turn = await AnthropicConverseAdapter(settings, transport=transport).converse(
        messages=hello(), tools=[SEARCH_TOOL], budget=budget()
    )

    assert turn.stop_reason == "TOOL_USE"
    assert turn.text is None
    assert turn.tool_calls[0].call_id == "c1" and turn.tool_calls[0].tool_name == "search"
    assert json.loads(turn.tool_calls[0].arguments_json) == {"q": "壶"}


async def test_tool_input_is_serialized_compactly_without_escaping_cjk(
    settings: Settings,
) -> None:
    """与 OpenAI 协议下的 ``'{"q":"壶"}'`` 保持同一形状，上层循环才察觉不到协议差异。"""

    transport, _ = recording_transport(
        _message([_tool_use("c1", "search", {"q": "壶"})], "tool_use")
    )

    turn = await AnthropicConverseAdapter(settings, transport=transport).converse(
        messages=hello(), tools=[SEARCH_TOOL], budget=budget()
    )

    assert turn.tool_calls[0].arguments_json == '{"q":"壶"}'


async def test_text_and_tool_use_in_one_turn_keep_both(settings: Settings) -> None:
    transport, _ = recording_transport(
        _message(
            [{"type": "text", "text": "我来查"}, _tool_use("c1", "search", {})],
            "tool_use",
        )
    )

    turn = await AnthropicConverseAdapter(settings, transport=transport).converse(
        messages=hello(), tools=[SEARCH_TOOL], budget=budget()
    )

    assert turn.text == "我来查" and turn.stop_reason == "TOOL_USE"
    assert turn.tool_calls[0].arguments_json == "{}"


async def test_parallel_tool_use_blocks_keep_their_order(settings: Settings) -> None:
    transport, _ = recording_transport(
        _message(
            [_tool_use("c1", "search", {"q": "壶"}), _tool_use("c2", "search", {"q": "杯"})],
            "tool_use",
        )
    )

    turn = await AnthropicConverseAdapter(settings, transport=transport).converse(
        messages=hello(), tools=[SEARCH_TOOL], budget=budget()
    )

    assert [c.call_id for c in turn.tool_calls] == ["c1", "c2"]


async def test_multiple_text_blocks_are_concatenated(settings: Settings) -> None:
    transport, _ = recording_transport(
        _message([{"type": "text", "text": "你"}, {"type": "text", "text": "好"}])
    )

    turn = await AnthropicConverseAdapter(settings, transport=transport).converse(
        messages=hello(), tools=[], budget=budget()
    )

    assert turn.text == "你好"


@pytest.mark.parametrize("stop_reason", ["end_turn", "stop_sequence"])
async def test_natural_stop_reasons_map_to_end_turn(settings: Settings, stop_reason: str) -> None:
    transport, _ = recording_transport(
        _message([{"type": "text", "text": "好"}], stop_reason=stop_reason)
    )

    turn = await AnthropicConverseAdapter(settings, transport=transport).converse(
        messages=hello(), tools=[], budget=budget()
    )

    assert turn.stop_reason == "END_TURN"


async def test_truncated_response_drops_tool_calls(settings: Settings) -> None:
    """max_tokens 时 tool_use 的 input 可能是半截的，交给上层只会被误执行。"""

    transport, _ = recording_transport(
        _message([_tool_use("c1", "search", {"q": "壶"})], "max_tokens")
    )

    turn = await AnthropicConverseAdapter(settings, transport=transport).converse(
        messages=hello(), tools=[SEARCH_TOOL], budget=budget()
    )

    assert turn.stop_reason == "MAX_TOKENS" and turn.tool_calls == []


async def test_thinking_blocks_are_captured_for_replay(settings: Settings) -> None:
    block = {"type": "thinking", "thinking": "先搜索", "signature": "sig-1"}
    transport, _ = recording_transport(
        _message([block, _tool_use("c1", "search", {"q": "壶"})], "tool_use")
    )

    turn = await AnthropicConverseAdapter(settings, transport=transport).converse(
        messages=hello(), tools=[SEARCH_TOOL], budget=budget()
    )

    assert turn.reasoning is not None and turn.reasoning.protocol == "anthropic"
    assert json.loads(turn.reasoning.payload) == [block]
    assert turn.text is None  # 思考块不是给用户看的正文


async def test_absent_thinking_yields_no_replay(settings: Settings) -> None:
    transport, _ = recording_transport(_text_response())

    turn = await AnthropicConverseAdapter(settings, transport=transport).converse(
        messages=hello(), tools=[], budget=budget()
    )

    assert turn.reasoning is None


async def test_budget_charged_before_request(settings: Settings) -> None:
    transport, seen = recording_transport()

    with pytest.raises(LlmBudgetExceededError):
        await AnthropicConverseAdapter(settings, transport=transport).converse(
            messages=hello(), tools=[], budget=LlmBudget(max_calls=0, max_tokens=1000)
        )

    assert seen == []


async def test_request_carries_required_max_tokens_capped_by_remaining_budget(
    settings: Settings,
) -> None:
    """Anthropic 协议的 max_tokens 是必填项；同样要按剩余预算收紧。"""

    transport, seen = recording_transport(_text_response())
    spent = LlmBudget(max_calls=5, max_tokens=1000, tokens=400)

    await AnthropicConverseAdapter(settings, transport=transport).converse(
        messages=hello(), tools=[], budget=spent
    )

    assert request_body(seen[0])["max_tokens"] == 600


async def test_successful_call_charges_the_summed_tokens(settings: Settings) -> None:
    transport, _ = recording_transport(_text_response())
    tracked = budget()

    await AnthropicConverseAdapter(settings, transport=transport).converse(
        messages=hello(), tools=[], budget=tracked
    )

    assert (tracked.calls, tracked.tokens) == (1, 15)


async def test_request_declares_tools_with_input_schema(settings: Settings) -> None:
    transport, seen = recording_transport(_text_response())

    await AnthropicConverseAdapter(settings, transport=transport).converse(
        messages=hello(), tools=[SEARCH_TOOL], budget=budget()
    )

    body = request_body(seen[0])
    assert body["model"] == settings.llm_model
    assert body["stream"] is False
    assert body["tools"] == [
        {
            "name": "search",
            "description": "搜索商品",
            "input_schema": SEARCH_TOOL.parameters,
        }
    ]


async def test_request_omits_tools_and_system_when_absent(settings: Settings) -> None:
    transport, seen = recording_transport(_text_response())

    await AnthropicConverseAdapter(settings, transport=transport).converse(
        messages=hello(), tools=[], budget=budget()
    )

    body = request_body(seen[0])
    assert "tools" not in body and "system" not in body


@pytest.mark.parametrize("configured", ["enabled", "disabled"])
async def test_thinking_mode_is_always_sent_explicitly(configured: str) -> None:
    transport, seen = recording_transport(_text_response())
    adapter = AnthropicConverseAdapter(make_settings(llm_thinking=configured), transport=transport)

    await adapter.converse(messages=hello(), tools=[], budget=budget())

    assert request_body(seen[0])["thinking"] == {"type": configured}


async def test_per_call_options_can_only_tighten_thinking() -> None:
    transport, seen = recording_transport(_text_response(), _text_response())
    closed = AnthropicConverseAdapter(make_settings(llm_thinking="disabled"), transport=transport)
    await closed.converse(
        messages=hello(), tools=[], budget=budget(), options=LlmCallOptions(thinking="enabled")
    )
    opened = AnthropicConverseAdapter(make_settings(llm_thinking="enabled"), transport=transport)
    await opened.converse(
        messages=hello(), tools=[], budget=budget(), options=LlmCallOptions(thinking="disabled")
    )

    assert request_body(seen[0])["thinking"] == {"type": "disabled"}
    assert request_body(seen[1])["thinking"] == {"type": "disabled"}


async def test_json_output_option_has_no_effect_on_this_protocol(settings: Settings) -> None:
    """Anthropic 协议没有 response_format；JSON 形状靠提示词与下游 Pydantic 校验保证。"""

    transport, seen = recording_transport(_text_response('{"a":1}'))

    await AnthropicConverseAdapter(settings, transport=transport).converse(
        messages=hello(), tools=[], budget=budget(), options=STRUCTURED_CALL_OPTIONS
    )

    assert "response_format" not in request_body(seen[0])


@pytest.mark.parametrize(
    "body",
    [
        {"content": "not-a-list", "stop_reason": "end_turn"},
        {"content": [{"type": "text", "text": "x"}]},
        {"content": [{"type": "text", "text": "x"}], "stop_reason": "refusal"},
        {"content": [], "stop_reason": "tool_use"},
        {"content": [{"type": "tool_use", "name": "s", "input": {}}], "stop_reason": "tool_use"},
        {"content": [{"type": "tool_use", "id": "c1", "input": {}}], "stop_reason": "tool_use"},
        {
            "content": [{"type": "tool_use", "id": "c1", "name": "s", "input": "raw"}],
            "stop_reason": "tool_use",
        },
        {"content": [{"type": "text"}], "stop_reason": "end_turn"},
        {"content": [], "stop_reason": "end_turn", "usage": "many"},
    ],
    ids=[
        "content-not-list",
        "no-stop-reason",
        "unsupported-stop-reason",
        "tool-stop-without-calls",
        "tool-use-without-id",
        "tool-use-without-name",
        "tool-input-not-object",
        "text-block-without-text",
        "usage-not-an-object",
    ],
)
async def test_malformed_payload_degrades_as_bad_payload(
    settings: Settings, body: dict[str, object]
) -> None:
    transport, _ = recording_transport(httpx.Response(200, json=body))

    turn = await AnthropicConverseAdapter(settings, transport=transport).converse(
        messages=hello(), tools=[SEARCH_TOOL], budget=budget()
    )

    assert turn.degraded is True
    assert turn.failure_kind is LlmFailureKind.BAD_PAYLOAD
    assert turn.stop_reason == "ERROR" and turn.tool_calls == [] and turn.text is None


@pytest.mark.parametrize(
    ("status", "kind", "usage_known"),
    [
        (401, LlmFailureKind.HTTP_401, True),
        (403, LlmFailureKind.HTTP_403, True),
        (429, LlmFailureKind.HTTP_429, False),
        (400, LlmFailureKind.HTTP_OTHER, False),
        (529, LlmFailureKind.HTTP_OTHER, False),
    ],
)
async def test_http_errors_map_to_known_failure_kinds(
    settings: Settings, status: int, kind: LlmFailureKind, usage_known: bool
) -> None:
    transport, _ = recording_transport(httpx.Response(status))

    turn = await AnthropicConverseAdapter(settings, transport=transport).converse(
        messages=hello(), tools=[], budget=budget()
    )

    assert turn.failure_kind is kind and turn.degraded is True
    assert turn.stop_reason == "ERROR"
    assert (turn.tokens, turn.usage_known) == (0, usage_known)


@pytest.mark.parametrize(
    ("error", "kind"),
    [
        (httpx.ReadTimeout("slow"), LlmFailureKind.TIMEOUT),
        (httpx.ConnectError("down"), LlmFailureKind.NETWORK),
    ],
)
async def test_transport_errors_map_to_known_failure_kinds(
    settings: Settings, error: Exception, kind: LlmFailureKind
) -> None:
    transport, _ = recording_transport(error)

    turn = await AnthropicConverseAdapter(settings, transport=transport).converse(
        messages=hello(), tools=[], budget=budget()
    )

    assert turn.failure_kind is kind


async def test_unconfigured_adapter_raises_before_any_request() -> None:
    transport, seen = recording_transport()
    adapter = AnthropicConverseAdapter(make_settings(llm_api_key=None), transport=transport)

    assert adapter.is_configured() is False
    with pytest.raises(LlmUnavailableError):
        await adapter.converse(messages=hello(), tools=[], budget=budget())
    assert seen == []


async def test_api_key_never_appears_in_failure_logs(
    settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    transport, _ = recording_transport(httpx.Response(401))

    with caplog.at_level("WARNING"):
        await AnthropicConverseAdapter(settings, transport=transport).converse(
            messages=hello(), tools=[], budget=budget()
        )

    assert "llm_upstream_failed" in caplog.text
    assert "test-key" not in caplog.text


# 2026-09-22 真实冒烟实测到的 usage 形状（同一段 1570 token 的前缀，第 2 次请求）：
# ``input_tokens`` 只含缓存**未命中**的部分，命中数另在 ``cache_read_input_tokens``。
_REAL_CACHED_USAGE = {
    "cache_creation_input_tokens": 0,
    "cache_read_input_tokens": 1408,
    "input_tokens": 162,
    "output_tokens": 1,
    "service_tier": "standard",
}


async def test_cache_read_tokens_are_counted_and_reported(settings: Settings) -> None:
    """input_tokens 不含命中部分：漏读 cache_read_input_tokens，缓存命中时 token 会被低估。"""

    transport, _ = recording_transport(
        _message([{"type": "text", "text": "6"}], usage=_REAL_CACHED_USAGE)
    )

    turn = await AnthropicConverseAdapter(settings, transport=transport).converse(
        messages=hello(), tools=[], budget=budget(max_tokens=5_000)
    )

    assert turn.tokens == 1571  # 1408 命中 + 162 未命中 + 1 输出
    assert (turn.input_tokens, turn.output_tokens) == (1570, 1)
    assert (turn.cache_hit_tokens, turn.cache_miss_tokens) == (1408, 162)
    assert turn.usage_known is True


async def test_cache_creation_tokens_count_as_uncached_input(settings: Settings) -> None:
    """写入缓存的 token 也是这次请求的输入，且不是命中：计入总数与未命中。"""

    usage = {
        "input_tokens": 100,
        "cache_creation_input_tokens": 50,
        "cache_read_input_tokens": 200,
        "output_tokens": 10,
    }
    transport, _ = recording_transport(_message([{"type": "text", "text": "x"}], usage=usage))

    turn = await AnthropicConverseAdapter(settings, transport=transport).converse(
        messages=hello(), tools=[], budget=budget()
    )

    assert (turn.input_tokens, turn.tokens) == (350, 360)
    assert (turn.cache_hit_tokens, turn.cache_miss_tokens) == (200, 150)


async def test_zero_cache_read_is_reported_as_zero_not_unreported(settings: Settings) -> None:
    """接口明确说命中 0，和「没有上报」是两回事：前者是 0，后者是 None。"""

    usage = {"input_tokens": 12, "cache_read_input_tokens": 0, "output_tokens": 3}
    transport, _ = recording_transport(_message([{"type": "text", "text": "x"}], usage=usage))

    turn = await AnthropicConverseAdapter(settings, transport=transport).converse(
        messages=hello(), tools=[], budget=budget()
    )

    assert (turn.cache_hit_tokens, turn.cache_miss_tokens) == (0, 12)
    assert turn.tokens == 15


async def test_invalid_cache_field_is_treated_as_unreported_not_a_broken_response(
    settings: Settings,
) -> None:
    usage = {"input_tokens": 12, "cache_read_input_tokens": "many", "output_tokens": 3}
    transport, _ = recording_transport(_message([{"type": "text", "text": "x"}], usage=usage))

    turn = await AnthropicConverseAdapter(settings, transport=transport).converse(
        messages=hello(), tools=[], budget=budget()
    )

    assert turn.degraded is False and turn.tokens == 15
    assert turn.cache_hit_tokens is None and turn.cache_miss_tokens is None


async def test_cached_call_charges_the_full_prompt_against_the_budget(settings: Settings) -> None:
    transport, _ = recording_transport(
        _message([{"type": "text", "text": "6"}], usage=_REAL_CACHED_USAGE)
    )
    tracked = budget(max_tokens=5_000)

    await AnthropicConverseAdapter(settings, transport=transport).converse(
        messages=hello(), tools=[], budget=tracked
    )

    assert tracked.tokens == 1571
