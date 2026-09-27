"""DeepSeek OpenAI 兼容协议适配器；全部走 ``httpx.MockTransport``，零费用。"""

from __future__ import annotations

import httpx
import pytest

from app.core.config import Settings
from app.llm.client import (
    STRUCTURED_CALL_OPTIONS,
    LlmBudget,
    LlmBudgetExceededError,
    LlmCallOptions,
    LlmFailureKind,
    LlmMessage,
    LlmUnavailableError,
)
from app.llm.openai_adapter import OpenAiConverseAdapter
from tests.unit.llm._transport import (
    OPENAI_URL,
    SEARCH_TOOL,
    budget,
    hello,
    make_settings,
    recording_transport,
    request_body,
)


def _text_response(text: str = "好", **usage: int) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [{"finish_reason": "stop", "message": {"content": text}}],
            "usage": usage or {"total_tokens": 3, "prompt_tokens": 2, "completion_tokens": 1},
        },
    )


def _tool_call(call_id: str, name: str, arguments: str) -> dict[str, object]:
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": arguments}}


async def test_tool_call_response_is_mapped(settings: Settings) -> None:
    transport, seen = recording_transport(
        httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "tool_calls",
                        "message": {
                            "content": None,
                            "tool_calls": [_tool_call("c1", "search", '{"q":"壶"}')],
                        },
                    }
                ],
                "usage": {
                    "total_tokens": 88,
                    "prompt_tokens": 60,
                    "completion_tokens": 28,
                    "prompt_cache_hit_tokens": 40,
                    "prompt_cache_miss_tokens": 20,
                },
            },
        )
    )

    turn = await OpenAiConverseAdapter(settings, transport=transport).converse(
        messages=[LlmMessage(role="user", content="找个壶")],
        tools=[SEARCH_TOOL],
        budget=LlmBudget(max_calls=5, max_tokens=1000),
    )

    assert str(seen[0].url) == OPENAI_URL
    assert turn.stop_reason == "TOOL_USE"
    assert turn.text is None
    assert turn.tool_calls[0].call_id == "c1"
    assert turn.tool_calls[0].tool_name == "search"
    assert turn.tool_calls[0].arguments_json == '{"q":"壶"}'
    assert turn.tokens == 88 and turn.usage_known is True
    assert (turn.input_tokens, turn.output_tokens) == (60, 28)
    assert (turn.cache_hit_tokens, turn.cache_miss_tokens) == (40, 20)
    assert turn.degraded is False


async def test_text_response_is_mapped_to_end_turn(settings: Settings) -> None:
    transport, _ = recording_transport(_text_response("本店有 2 款"))

    turn = await OpenAiConverseAdapter(settings, transport=transport).converse(
        messages=hello(), tools=[], budget=budget()
    )

    assert (turn.stop_reason, turn.text, turn.tool_calls) == ("END_TURN", "本店有 2 款", [])


async def test_parallel_tool_calls_keep_their_order(settings: Settings) -> None:
    transport, _ = recording_transport(
        httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "tool_calls",
                        "message": {
                            "content": None,
                            "tool_calls": [
                                _tool_call("c1", "search", '{"q":"壶"}'),
                                _tool_call("c2", "search", '{"q":"杯"}'),
                            ],
                        },
                    }
                ],
                "usage": {},
            },
        )
    )

    turn = await OpenAiConverseAdapter(settings, transport=transport).converse(
        messages=hello(), tools=[SEARCH_TOOL], budget=budget()
    )

    assert [c.call_id for c in turn.tool_calls] == ["c1", "c2"]


async def test_missing_cache_fields_stay_none(settings: Settings) -> None:
    transport, _ = recording_transport(
        _text_response(total_tokens=3, prompt_tokens=2, completion_tokens=1)
    )

    turn = await OpenAiConverseAdapter(settings, transport=transport).converse(
        messages=hello(), tools=[], budget=budget()
    )

    assert turn.cache_hit_tokens is None and turn.cache_miss_tokens is None


async def test_invalid_cache_field_is_treated_as_unreported(settings: Settings) -> None:
    """缓存计量只是附带信息，一个坏字段不该把整次成功的响应判成损坏。"""

    transport, _ = recording_transport(
        httpx.Response(
            200,
            json={
                "choices": [{"finish_reason": "stop", "message": {"content": "好"}}],
                "usage": {
                    "total_tokens": 3,
                    "prompt_tokens": 2,
                    "completion_tokens": 1,
                    "prompt_cache_hit_tokens": "many",
                },
            },
        )
    )

    turn = await OpenAiConverseAdapter(settings, transport=transport).converse(
        messages=hello(), tools=[], budget=budget()
    )

    assert turn.degraded is False and turn.cache_hit_tokens is None


async def test_missing_usage_is_unknown_not_zero_cost(settings: Settings) -> None:
    transport, _ = recording_transport(
        httpx.Response(
            200, json={"choices": [{"finish_reason": "stop", "message": {"content": "好"}}]}
        )
    )

    turn = await OpenAiConverseAdapter(settings, transport=transport).converse(
        messages=hello(), tools=[], budget=budget()
    )

    assert turn.usage_known is False and turn.tokens == 0


async def test_budget_charged_before_request(settings: Settings) -> None:
    """预算耗尽时不得发出请求——发出去就要付钱。"""

    transport, seen = recording_transport()

    with pytest.raises(LlmBudgetExceededError):
        await OpenAiConverseAdapter(settings, transport=transport).converse(
            messages=hello(), tools=[], budget=LlmBudget(max_calls=0, max_tokens=1000)
        )

    assert seen == []  # 关键断言


async def test_exhausted_token_budget_blocks_the_request(settings: Settings) -> None:
    transport, seen = recording_transport()
    spent = LlmBudget(max_calls=5, max_tokens=100, tokens=100)

    with pytest.raises(LlmBudgetExceededError):
        await OpenAiConverseAdapter(settings, transport=transport).converse(
            messages=hello(), tools=[], budget=spent
        )

    assert seen == []


async def test_request_caps_max_tokens_at_the_remaining_budget(settings: Settings) -> None:
    transport, seen = recording_transport(_text_response())
    spent = LlmBudget(max_calls=5, max_tokens=1000, tokens=400)

    await OpenAiConverseAdapter(settings, transport=transport).converse(
        messages=hello(), tools=[], budget=spent
    )

    assert request_body(seen[0])["max_tokens"] == 600


async def test_request_caps_max_tokens_at_the_per_call_limit() -> None:
    transport, seen = recording_transport(_text_response())
    adapter = OpenAiConverseAdapter(
        make_settings(llm_max_output_tokens_per_call=512), transport=transport
    )

    await adapter.converse(messages=hello(), tools=[], budget=budget(max_tokens=100_000))

    assert request_body(seen[0])["max_tokens"] == 512


async def test_successful_call_charges_the_reported_tokens(settings: Settings) -> None:
    transport, _ = recording_transport(
        _text_response(total_tokens=42, prompt_tokens=30, completion_tokens=12)
    )
    tracked = budget()

    await OpenAiConverseAdapter(settings, transport=transport).converse(
        messages=hello(), tools=[], budget=tracked
    )

    assert (tracked.calls, tracked.tokens) == (1, 42)


async def test_failed_call_still_counts_as_a_call_but_charges_no_tokens(settings: Settings) -> None:
    transport, _ = recording_transport(httpx.Response(500))
    tracked = budget()

    await OpenAiConverseAdapter(settings, transport=transport).converse(
        messages=hello(), tools=[], budget=tracked
    )

    assert (tracked.calls, tracked.tokens) == (1, 0)


async def test_malformed_arguments_are_passed_through_not_swallowed(settings: Settings) -> None:
    """畸形参数必须原样上交，由工具注册表拦下（R4）。"""

    transport, _ = recording_transport(
        httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "tool_calls",
                        "message": {
                            "content": None,
                            "tool_calls": [_tool_call("c1", "search", "{not json")],
                        },
                    }
                ],
                "usage": {},
            },
        )
    )

    turn = await OpenAiConverseAdapter(settings, transport=transport).converse(
        messages=hello(), tools=[SEARCH_TOOL], budget=budget()
    )

    assert turn.tool_calls[0].arguments_json == "{not json"  # 不解析、不吞异常
    assert turn.degraded is False


async def test_truncated_response_drops_tool_calls(settings: Settings) -> None:
    """finish_reason=length 时参数可能是半截的，交给上层只会被误执行。"""

    transport, _ = recording_transport(
        httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "length",
                        "message": {
                            "content": None,
                            "tool_calls": [_tool_call("c1", "search", '{"q":"')],
                        },
                    }
                ],
                "usage": {},
            },
        )
    )

    turn = await OpenAiConverseAdapter(settings, transport=transport).converse(
        messages=hello(), tools=[SEARCH_TOOL], budget=budget()
    )

    assert turn.stop_reason == "MAX_TOKENS" and turn.tool_calls == []


async def test_tool_calls_win_over_a_plain_stop_finish_reason(settings: Settings) -> None:
    transport, _ = recording_transport(
        httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": None,
                            "tool_calls": [_tool_call("c1", "search", "{}")],
                        },
                    }
                ],
                "usage": {},
            },
        )
    )

    turn = await OpenAiConverseAdapter(settings, transport=transport).converse(
        messages=hello(), tools=[SEARCH_TOOL], budget=budget()
    )

    assert turn.stop_reason == "TOOL_USE"


async def test_null_content_on_stop_becomes_empty_text_not_a_crash(settings: Settings) -> None:
    transport, _ = recording_transport(
        httpx.Response(
            200, json={"choices": [{"finish_reason": "stop", "message": {"content": None}}]}
        )
    )

    turn = await OpenAiConverseAdapter(settings, transport=transport).converse(
        messages=hello(), tools=[], budget=budget()
    )

    assert (turn.stop_reason, turn.text) == ("END_TURN", "")


@pytest.mark.parametrize(
    "body",
    [
        {"choices": []},
        {"choices": [{"finish_reason": "stop"}]},
        {"choices": [{"finish_reason": "content_filter", "message": {"content": "x"}}]},
        {"choices": [{"finish_reason": "tool_calls", "message": {"content": None}}]},
        {
            "choices": [
                {
                    "finish_reason": "tool_calls",
                    "message": {"tool_calls": [{"id": "c1", "function": {"arguments": "{}"}}]},
                }
            ]
        },
        {"choices": [{"finish_reason": "stop", "message": {"content": "x"}}], "usage": "many"},
    ],
    ids=[
        "no-choices",
        "no-message",
        "unsupported-finish-reason",
        "tool-finish-without-calls",
        "tool-call-without-name",
        "usage-not-an-object",
    ],
)
async def test_malformed_payload_degrades_as_bad_payload(
    settings: Settings, body: dict[str, object]
) -> None:
    transport, _ = recording_transport(httpx.Response(200, json=body))

    turn = await OpenAiConverseAdapter(settings, transport=transport).converse(
        messages=hello(), tools=[SEARCH_TOOL], budget=budget()
    )

    assert turn.degraded is True
    assert turn.failure_kind is LlmFailureKind.BAD_PAYLOAD
    assert turn.stop_reason == "ERROR" and turn.tool_calls == [] and turn.text is None


async def test_non_json_body_degrades_as_bad_payload(settings: Settings) -> None:
    transport, _ = recording_transport(httpx.Response(200, content=b"<html>oops</html>"))

    turn = await OpenAiConverseAdapter(settings, transport=transport).converse(
        messages=hello(), tools=[], budget=budget()
    )

    assert turn.failure_kind is LlmFailureKind.BAD_PAYLOAD


@pytest.mark.parametrize(
    ("status", "kind", "usage_known"),
    [
        (401, LlmFailureKind.HTTP_401, True),
        (403, LlmFailureKind.HTTP_403, True),
        (429, LlmFailureKind.HTTP_429, False),
        (400, LlmFailureKind.HTTP_OTHER, False),
        (500, LlmFailureKind.HTTP_OTHER, False),
    ],
)
async def test_http_errors_map_to_known_failure_kinds(
    settings: Settings, status: int, kind: LlmFailureKind, usage_known: bool
) -> None:
    transport, _ = recording_transport(httpx.Response(status))

    turn = await OpenAiConverseAdapter(settings, transport=transport).converse(
        messages=hello(), tools=[], budget=budget()
    )

    assert turn.failure_kind is kind
    assert turn.degraded is True
    assert turn.stop_reason == "ERROR"
    assert (turn.tokens, turn.usage_known) == (0, usage_known)


@pytest.mark.parametrize(
    ("error", "kind"),
    [
        (httpx.ReadTimeout("slow"), LlmFailureKind.TIMEOUT),
        (httpx.ConnectError("down"), LlmFailureKind.NETWORK),
        (httpx.RemoteProtocolError("cut"), LlmFailureKind.NETWORK),
    ],
)
async def test_transport_errors_map_to_known_failure_kinds(
    settings: Settings, error: Exception, kind: LlmFailureKind
) -> None:
    transport, _ = recording_transport(error)

    turn = await OpenAiConverseAdapter(settings, transport=transport).converse(
        messages=hello(), tools=[], budget=budget()
    )

    assert turn.failure_kind is kind and turn.degraded is True


async def test_unconfigured_adapter_raises_before_any_request() -> None:
    transport, seen = recording_transport()
    adapter = OpenAiConverseAdapter(make_settings(llm_api_key=None), transport=transport)

    assert adapter.is_configured() is False
    with pytest.raises(LlmUnavailableError):
        await adapter.converse(messages=hello(), tools=[], budget=budget())
    assert seen == []


async def test_request_uses_bearer_auth_model_and_tool_format(settings: Settings) -> None:
    transport, seen = recording_transport(_text_response())

    await OpenAiConverseAdapter(settings, transport=transport).converse(
        messages=hello(), tools=[SEARCH_TOOL], budget=budget()
    )

    assert seen[0].headers["authorization"] == "Bearer test-key"
    body = request_body(seen[0])
    assert body["model"] == settings.llm_model
    assert body["stream"] is False
    assert body["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "search",
                "description": "搜索商品",
                "parameters": SEARCH_TOOL.parameters,
            },
        }
    ]


async def test_request_omits_tools_when_none_are_given(settings: Settings) -> None:
    """空 ``tools`` 数组会被部分上游拒绝，没有工具时整个键都不发。"""

    transport, seen = recording_transport(_text_response())

    await OpenAiConverseAdapter(settings, transport=transport).converse(
        messages=hello(), tools=[], budget=budget()
    )

    assert "tools" not in request_body(seen[0])


@pytest.mark.parametrize("configured", ["enabled", "disabled"])
async def test_thinking_mode_is_always_sent_explicitly(configured: str) -> None:
    """官方默认开启思考模式，不显式发送就会随提供方默认值漂移。"""

    transport, seen = recording_transport(_text_response())
    adapter = OpenAiConverseAdapter(make_settings(llm_thinking=configured), transport=transport)

    await adapter.converse(messages=hello(), tools=[], budget=budget())

    assert request_body(seen[0])["thinking"] == {"type": configured}


async def test_per_call_options_can_only_tighten_thinking() -> None:
    """配置关闭时，单次调用不能越过它把思考模式打开；配置开启时可单次关闭。"""

    transport, seen = recording_transport(_text_response(), _text_response())
    closed = OpenAiConverseAdapter(make_settings(llm_thinking="disabled"), transport=transport)
    await closed.converse(
        messages=hello(), tools=[], budget=budget(), options=LlmCallOptions(thinking="enabled")
    )
    opened = OpenAiConverseAdapter(make_settings(llm_thinking="enabled"), transport=transport)
    await opened.converse(
        messages=hello(), tools=[], budget=budget(), options=LlmCallOptions(thinking="disabled")
    )

    assert request_body(seen[0])["thinking"] == {"type": "disabled"}
    assert request_body(seen[1])["thinking"] == {"type": "disabled"}


async def test_json_output_option_requests_json_object_format(settings: Settings) -> None:
    transport, seen = recording_transport(_text_response('{"a":1}'))

    await OpenAiConverseAdapter(settings, transport=transport).converse(
        messages=hello(), tools=[], budget=budget(), options=STRUCTURED_CALL_OPTIONS
    )

    assert request_body(seen[0])["response_format"] == {"type": "json_object"}


async def test_plain_call_does_not_request_json_format(settings: Settings) -> None:
    transport, seen = recording_transport(_text_response())

    await OpenAiConverseAdapter(settings, transport=transport).converse(
        messages=hello(), tools=[], budget=budget()
    )

    assert "response_format" not in request_body(seen[0])


async def test_reasoning_content_is_captured_for_replay(settings: Settings) -> None:
    transport, _ = recording_transport(
        httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "tool_calls",
                        "message": {
                            "content": None,
                            "reasoning_content": "先搜索商品",
                            "tool_calls": [_tool_call("c1", "search", '{"q":"壶"}')],
                        },
                    }
                ],
                "usage": {},
            },
        )
    )

    turn = await OpenAiConverseAdapter(settings, transport=transport).converse(
        messages=hello(), tools=[SEARCH_TOOL], budget=budget()
    )

    assert turn.reasoning is not None
    assert (turn.reasoning.protocol, turn.reasoning.payload) == ("openai", "先搜索商品")


async def test_absent_reasoning_content_yields_no_replay(settings: Settings) -> None:
    transport, _ = recording_transport(_text_response())

    turn = await OpenAiConverseAdapter(settings, transport=transport).converse(
        messages=hello(), tools=[], budget=budget()
    )

    assert turn.reasoning is None


async def test_api_key_never_appears_in_failure_logs(
    settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    transport, _ = recording_transport(httpx.Response(401))

    with caplog.at_level("WARNING"):
        await OpenAiConverseAdapter(settings, transport=transport).converse(
            messages=hello(), tools=[], budget=budget()
        )

    assert "llm_upstream_failed" in caplog.text
    assert "test-key" not in caplog.text
