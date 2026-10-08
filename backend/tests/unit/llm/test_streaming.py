"""两协议的流式解析；全部走 ``httpx.MockTransport``，零费用。

流式请求是否要带 ``stream_options.include_usage`` 才能拿到用量、DeepSeek 是否支持，
以真实冒烟为准；这里末尾的用量块只是按 OpenAI 格式写的预期。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx
import pytest

from app.core.config import Settings
from app.llm.anthropic_adapter import AnthropicConverseAdapter
from app.llm.client import (
    LlmBudgetExceededError,
    LlmFailureKind,
    LlmStreamEvent,
    LlmTurn,
    TextDelta,
    TurnComplete,
)
from app.llm.openai_adapter import OpenAiConverseAdapter
from tests.unit.llm._transport import (
    ANTHROPIC_URL,
    OPENAI_URL,
    SEARCH_TOOL,
    budget,
    hello,
    recording_transport,
    request_body,
    sse,
)


async def _collect(stream: object) -> list[LlmStreamEvent]:
    return [event async for event in stream]  # type: ignore[attr-defined]


def _text(events: list[LlmStreamEvent]) -> str:
    return "".join(e.text for e in events if isinstance(e, TextDelta))


def _final(events: list[LlmStreamEvent]) -> LlmTurn:
    """流以且仅以一个 TurnComplete 结束。"""

    assert isinstance(events[-1], TurnComplete)
    assert sum(isinstance(e, TurnComplete) for e in events) == 1
    return events[-1].turn


# --------------------------------------------------------------------- OpenAI


async def test_openai_stream_text_deltas_and_final_usage(settings: Settings) -> None:
    transport, seen = recording_transport(
        sse(
            'data: {"choices":[{"delta":{"content":"你"}}]}',
            'data: {"choices":[{"delta":{"content":"好"},"finish_reason":"stop"}]}',
            'data: {"choices":[],"usage":{"total_tokens":9,"prompt_tokens":7,"completion_tokens":2,'
            '"prompt_cache_hit_tokens":5,"prompt_cache_miss_tokens":2}}',
            "data: [DONE]",
        )
    )

    events = await _collect(
        OpenAiConverseAdapter(settings, transport=transport).converse_stream(
            messages=hello(), tools=[], budget=budget()
        )
    )

    assert _text(events) == "你好"
    final = _final(events)
    assert final.stop_reason == "END_TURN"
    assert final.text == "你好" and final.tokens == 9 and final.usage_known is True
    assert (final.input_tokens, final.output_tokens) == (7, 2)
    assert final.cache_hit_tokens == 5 and final.cache_miss_tokens == 2
    body = request_body(seen[0])
    assert str(seen[0].url) == OPENAI_URL
    assert body["stream"] is True
    assert body["stream_options"] == {"include_usage": True}


async def test_openai_stream_assembles_tool_call_fragments(settings: Settings) -> None:
    transport, _ = recording_transport(
        sse(
            'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"c1",'
            '"function":{"name":"search","arguments":"{\\"q\\":"}}]}}]}',
            'data: {"choices":[{"delta":{"tool_calls":[{"index":0,'
            '"function":{"arguments":"\\"壶\\"}"}}]},"finish_reason":"tool_calls"}]}',
            "data: [DONE]",
        )
    )

    events = await _collect(
        OpenAiConverseAdapter(settings, transport=transport).converse_stream(
            messages=hello(), tools=[SEARCH_TOOL], budget=budget()
        )
    )

    assert not any(isinstance(e, TextDelta) for e in events)  # 工具调用不产出增量
    final = _final(events)
    assert final.stop_reason == "TOOL_USE"
    assert final.tool_calls[0].call_id == "c1"
    assert final.tool_calls[0].tool_name == "search"
    assert final.tool_calls[0].arguments_json == '{"q":"壶"}'


async def test_openai_stream_keeps_parallel_tool_calls_apart_by_index(settings: Settings) -> None:
    transport, _ = recording_transport(
        sse(
            'data: {"choices":[{"delta":{"tool_calls":['
            '{"index":0,"id":"c1","function":{"name":"search","arguments":"{\\"q\\":\\"壶\\"}"}},'
            '{"index":1,"id":"c2","function":{"name":"search","arguments":"{\\"q\\":"}}]}}]}',
            'data: {"choices":[{"delta":{"tool_calls":[{"index":1,'
            '"function":{"arguments":"\\"杯\\"}"}}]},"finish_reason":"tool_calls"}]}',
            "data: [DONE]",
        )
    )

    events = await _collect(
        OpenAiConverseAdapter(settings, transport=transport).converse_stream(
            messages=hello(), tools=[SEARCH_TOOL], budget=budget()
        )
    )

    calls = _final(events).tool_calls
    assert [(c.call_id, c.arguments_json) for c in calls] == [
        ("c1", '{"q":"壶"}'),
        ("c2", '{"q":"杯"}'),
    ]


async def test_openai_stream_with_text_then_tool_call(settings: Settings) -> None:
    transport, _ = recording_transport(
        sse(
            'data: {"choices":[{"delta":{"content":"我来查"}}]}',
            'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"c1",'
            '"function":{"name":"search","arguments":"{}"}}]},"finish_reason":"tool_calls"}]}',
            "data: [DONE]",
        )
    )

    events = await _collect(
        OpenAiConverseAdapter(settings, transport=transport).converse_stream(
            messages=hello(), tools=[SEARCH_TOOL], budget=budget()
        )
    )

    assert _text(events) == "我来查"
    final = _final(events)
    assert final.text == "我来查" and final.stop_reason == "TOOL_USE"


async def test_openai_stream_reasoning_is_captured_but_not_streamed_as_text(
    settings: Settings,
) -> None:
    transport, _ = recording_transport(
        sse(
            'data: {"choices":[{"delta":{"reasoning_content":"先"}}]}',
            'data: {"choices":[{"delta":{"reasoning_content":"想"}}]}',
            'data: {"choices":[{"delta":{"content":"好"},"finish_reason":"stop"}]}',
            "data: [DONE]",
        )
    )

    events = await _collect(
        OpenAiConverseAdapter(settings, transport=transport).converse_stream(
            messages=hello(), tools=[], budget=budget()
        )
    )

    assert _text(events) == "好"  # 推理内容不是给用户看的正文
    final = _final(events)
    assert final.reasoning is not None
    assert (final.reasoning.protocol, final.reasoning.payload) == ("openai", "先想")


async def test_openai_stream_without_usage_chunk_reports_unknown_usage(
    settings: Settings,
) -> None:
    transport, _ = recording_transport(
        sse(
            'data: {"choices":[{"delta":{"content":"好"},"finish_reason":"stop"}]}',
            "data: [DONE]",
        )
    )

    events = await _collect(
        OpenAiConverseAdapter(settings, transport=transport).converse_stream(
            messages=hello(), tools=[], budget=budget()
        )
    )

    final = _final(events)
    assert final.usage_known is False and final.tokens == 0 and final.degraded is False


async def test_openai_stream_charges_tokens_once_at_the_end(settings: Settings) -> None:
    transport, _ = recording_transport(
        sse(
            'data: {"choices":[{"delta":{"content":"好"},"finish_reason":"stop"}]}',
            'data: {"choices":[],"usage":{"total_tokens":9,'
            '"prompt_tokens":7,"completion_tokens":2}}',
            "data: [DONE]",
        )
    )
    tracked = budget()

    await _collect(
        OpenAiConverseAdapter(settings, transport=transport).converse_stream(
            messages=hello(), tools=[], budget=tracked
        )
    )

    assert (tracked.calls, tracked.tokens) == (1, 9)


async def test_stream_cut_midway_drops_partial_tool_calls(settings: Settings) -> None:
    transport, _ = recording_transport(
        sse(
            'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"c1",'
            '"function":{"name":"search","arguments":"{\\"q"}}]}}]}'
        )
    )

    events = await _collect(
        OpenAiConverseAdapter(settings, transport=transport).converse_stream(
            messages=hello(), tools=[SEARCH_TOOL], budget=budget()
        )
    )

    final = _final(events)
    assert final.stop_reason == "ERROR" and final.degraded and final.tool_calls == []
    assert final.failure_kind is LlmFailureKind.NETWORK


async def test_stream_cut_midway_keeps_the_text_already_shown(settings: Settings) -> None:
    """文本增量已经交给用户了；降级结果保留它，让调用方与界面上看到的一致。"""

    transport, _ = recording_transport(sse('data: {"choices":[{"delta":{"content":"你"}}]}'))

    events = await _collect(
        OpenAiConverseAdapter(settings, transport=transport).converse_stream(
            messages=hello(), tools=[], budget=budget()
        )
    )

    assert _text(events) == "你"
    final = _final(events)
    assert final.stop_reason == "ERROR" and final.degraded and final.text == "你"


@pytest.mark.parametrize("finish_reason", ["stop", "tool_calls", "length"])
async def test_openai_stream_requires_done_after_finish_reason(
    settings: Settings, finish_reason: str
) -> None:
    transport, _ = recording_transport(
        sse(
            'data: {"choices":[{"delta":{"content":"我来查"}}]}',
            "data: "
            + json.dumps(
                {
                    "choices": [
                        {
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "id": "c1",
                                        "function": {
                                            "name": "search",
                                            "arguments": "{}",
                                        },
                                    }
                                ]
                            },
                            "finish_reason": finish_reason,
                        }
                    ]
                }
            ),
        )
    )
    events = await _collect(
        OpenAiConverseAdapter(settings, transport=transport).converse_stream(
            messages=hello(), tools=[SEARCH_TOOL], budget=budget()
        )
    )
    final = _final(events)
    assert final.stop_reason == "ERROR"
    assert final.degraded and final.failure_kind is LlmFailureKind.NETWORK
    assert final.tool_calls == []
    assert final.text == _text(events) == "我来查"


async def test_stream_malformed_chunk_degrades_as_bad_payload(settings: Settings) -> None:
    transport, _ = recording_transport(sse("data: {not json"))

    events = await _collect(
        OpenAiConverseAdapter(settings, transport=transport).converse_stream(
            messages=hello(), tools=[], budget=budget()
        )
    )

    final = _final(events)
    assert final.failure_kind is LlmFailureKind.BAD_PAYLOAD and final.tool_calls == []


async def test_stream_http_error_yields_a_single_degraded_turn(settings: Settings) -> None:
    transport, _ = recording_transport(httpx.Response(429))

    events = await _collect(
        OpenAiConverseAdapter(settings, transport=transport).converse_stream(
            messages=hello(), tools=[], budget=budget()
        )
    )

    assert len(events) == 1
    final = _final(events)
    assert final.failure_kind is LlmFailureKind.HTTP_429 and final.degraded is True


async def test_stream_timeout_yields_a_single_degraded_turn(settings: Settings) -> None:
    transport, _ = recording_transport(httpx.ReadTimeout("slow"))

    events = await _collect(
        OpenAiConverseAdapter(settings, transport=transport).converse_stream(
            messages=hello(), tools=[], budget=budget()
        )
    )

    assert _final(events).failure_kind is LlmFailureKind.TIMEOUT


async def test_stream_budget_is_checked_before_the_request(settings: Settings) -> None:
    transport, seen = recording_transport()

    with pytest.raises(LlmBudgetExceededError):
        await _collect(
            OpenAiConverseAdapter(settings, transport=transport).converse_stream(
                messages=hello(), tools=[], budget=budget(max_calls=0)
            )
        )

    assert seen == []


# ------------------------------------------------------------------ Anthropic


def _event(name: str, payload: str) -> str:
    return f"event: {name}\ndata: {payload}"


_MESSAGE_START = _event(
    "message_start",
    '{"type":"message_start","message":{"usage":{"input_tokens":7,"output_tokens":0}}}',
)
_MESSAGE_STOP = _event("message_stop", '{"type":"message_stop"}')
_TOOL_USE_START = _event(
    "content_block_start",
    '{"type":"content_block_start","index":0,"content_block":'
    '{"type":"tool_use","id":"c1","name":"search","input":{}}}',
)


def _text_delta(text: str, index: int = 0) -> str:
    return _event(
        "content_block_delta",
        f'{{"type":"content_block_delta","index":{index},'
        f'"delta":{{"type":"text_delta","text":"{text}"}}}}',
    )


def _json_delta(fragment: str) -> str:
    return _event(
        "content_block_delta",
        '{"type":"content_block_delta","index":0,"delta":'
        f'{{"type":"input_json_delta","partial_json":{json.dumps(fragment)}}}}}',
    )


def _message_delta(stop_reason: str, output_tokens: int) -> str:
    return _event(
        "message_delta",
        f'{{"type":"message_delta","delta":{{"stop_reason":"{stop_reason}"}},'
        f'"usage":{{"output_tokens":{output_tokens}}}}}',
    )


@pytest.mark.parametrize("stop_reason", ["end_turn", "tool_use", "max_tokens"])
async def test_anthropic_stream_requires_message_stop_after_stop_reason(
    settings: Settings, stop_reason: str
) -> None:
    transport, _ = recording_transport(
        sse(
            _MESSAGE_START,
            _TOOL_USE_START,
            _json_delta("{}"),
            _text_delta("我来查", index=1),
            _message_delta(stop_reason, 3),
        )
    )
    events = await _collect(
        AnthropicConverseAdapter(settings, transport=transport).converse_stream(
            messages=hello(), tools=[SEARCH_TOOL], budget=budget()
        )
    )
    final = _final(events)
    assert final.stop_reason == "ERROR"
    assert final.degraded and final.failure_kind is LlmFailureKind.NETWORK
    assert final.tool_calls == []
    assert final.text == _text(events) == "我来查"


async def test_anthropic_stream_preserves_redacted_thinking_like_nonstream(
    settings: Settings,
) -> None:
    redacted = {"type": "redacted_thinking", "data": "opaque+/encrypted=="}
    transport, _ = recording_transport(
        sse(
            _MESSAGE_START,
            _event(
                "content_block_start",
                json.dumps(
                    {
                        "type": "content_block_start",
                        "index": 0,
                        "content_block": redacted,
                    }
                ),
            ),
            _event("content_block_stop", '{"type":"content_block_stop","index":0}'),
            _text_delta("好", index=1),
            _message_delta("end_turn", 2),
            _MESSAGE_STOP,
        ),
        httpx.Response(
            200,
            json={
                "content": [redacted, {"type": "text", "text": "好"}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 7, "output_tokens": 2},
            },
        ),
    )
    adapter = AnthropicConverseAdapter(settings, transport=transport)
    events = await _collect(adapter.converse_stream(messages=hello(), tools=[], budget=budget()))
    nonstream = await adapter.converse(messages=hello(), tools=[], budget=budget())
    final = _final(events)
    assert _text(events) == final.text == "好"
    assert final.reasoning is not None
    assert final.reasoning.protocol == "anthropic"
    assert json.loads(final.reasoning.payload) == [
        {"type": "redacted_thinking", "data": "opaque+/encrypted=="}
    ]
    assert final.reasoning == nonstream.reasoning


async def test_anthropic_stream_events_are_assembled(settings: Settings) -> None:
    transport, seen = recording_transport(
        sse(
            _MESSAGE_START,
            _text_delta("你"),
            _text_delta("好"),
            _message_delta("end_turn", 2),
            _MESSAGE_STOP,
        )
    )

    events = await _collect(
        AnthropicConverseAdapter(settings, transport=transport).converse_stream(
            messages=hello(), tools=[], budget=budget()
        )
    )

    assert _text(events) == "你好"
    final = _final(events)
    assert final.stop_reason == "END_TURN" and final.text == "你好"
    assert final.tokens == 9 and final.usage_known is True
    assert (final.input_tokens, final.output_tokens) == (7, 2)
    assert final.cache_hit_tokens is None
    assert str(seen[0].url) == ANTHROPIC_URL
    assert request_body(seen[0])["stream"] is True


@pytest.mark.parametrize("tail", ["read_error", "extra_text"])
async def test_anthropic_message_stop_finishes_without_reading_transport_tail(
    settings: Settings, tail: str
) -> None:
    class StreamWithTail(httpx.AsyncByteStream):
        tail_consumed = False
        closed = False

        async def __aiter__(self) -> AsyncIterator[bytes]:
            for event in (
                _MESSAGE_START,
                _text_delta("我来查", index=1),
                _TOOL_USE_START,
                _json_delta("{}"),
                _message_delta("tool_use", 3),
                _MESSAGE_STOP,
            ):
                yield f"{event}\n\n".encode()
            self.tail_consumed = True
            if tail == "read_error":
                raise httpx.ReadError("终止事件后的连接错误")
            yield f"{_text_delta('不应读取', index=1)}\n\n".encode()

        async def aclose(self) -> None:
            self.closed = True

    stream = StreamWithTail()
    transport, _ = recording_transport(
        httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=stream)
    )
    tracked = budget()
    events = await _collect(
        AnthropicConverseAdapter(settings, transport=transport).converse_stream(
            messages=hello(), tools=[SEARCH_TOOL], budget=tracked
        )
    )
    final = _final(events)
    assert final.stop_reason == "TOOL_USE" and not final.degraded
    assert final.text == _text(events) == "我来查"
    assert [(call.call_id, call.tool_name, call.arguments_json) for call in final.tool_calls] == [
        ("c1", "search", "{}")
    ]
    assert final.tokens == tracked.tokens == 10
    assert tracked.calls == 1
    assert not stream.tail_consumed
    assert stream.closed


async def test_anthropic_stream_assembles_tool_use_input_fragments(settings: Settings) -> None:
    transport, _ = recording_transport(
        sse(
            _MESSAGE_START,
            _TOOL_USE_START,
            _json_delta('{"q":'),
            _json_delta('"壶"}'),
            _event("content_block_stop", '{"type":"content_block_stop","index":0}'),
            _message_delta("tool_use", 12),
            _MESSAGE_STOP,
        )
    )

    events = await _collect(
        AnthropicConverseAdapter(settings, transport=transport).converse_stream(
            messages=hello(), tools=[SEARCH_TOOL], budget=budget()
        )
    )

    assert not any(isinstance(e, TextDelta) for e in events)  # 工具调用不产出增量
    final = _final(events)
    assert final.stop_reason == "TOOL_USE"
    assert final.tool_calls[0].call_id == "c1" and final.tool_calls[0].tool_name == "search"
    assert final.tool_calls[0].arguments_json == '{"q":"壶"}'


async def test_anthropic_stream_keeps_parallel_tool_use_blocks_apart_by_index(
    settings: Settings,
) -> None:
    """一轮两个工具调用，两块的输入分片**交错**到达：必须按 index 归并，不能串到一起。"""

    def start(index: int, call_id: str) -> str:
        return _event(
            "content_block_start",
            f'{{"type":"content_block_start","index":{index},"content_block":'
            f'{{"type":"tool_use","id":"{call_id}","name":"search","input":{{}}}}}}',
        )

    def fragment(index: int, partial: str) -> str:
        return _event(
            "content_block_delta",
            f'{{"type":"content_block_delta","index":{index},"delta":'
            f'{{"type":"input_json_delta","partial_json":{json.dumps(partial)}}}}}',
        )

    transport, _ = recording_transport(
        sse(
            _MESSAGE_START,
            start(0, "c1"),
            start(1, "c2"),
            fragment(0, '{"q":'),
            fragment(1, '{"q":'),
            fragment(1, '"杯"}'),
            fragment(0, '"壶"}'),
            _message_delta("tool_use", 20),
            _MESSAGE_STOP,
        )
    )

    events = await _collect(
        AnthropicConverseAdapter(settings, transport=transport).converse_stream(
            messages=hello(), tools=[SEARCH_TOOL], budget=budget()
        )
    )

    calls = _final(events).tool_calls
    assert [(c.call_id, c.arguments_json) for c in calls] == [
        ("c1", '{"q":"壶"}'),
        ("c2", '{"q":"杯"}'),
    ]
    assert not any(isinstance(e, TextDelta) for e in events)


async def test_anthropic_stream_tool_use_without_input_fragments_uses_empty_object(
    settings: Settings,
) -> None:
    transport, _ = recording_transport(
        sse(_MESSAGE_START, _TOOL_USE_START, _message_delta("tool_use", 3), _MESSAGE_STOP)
    )

    events = await _collect(
        AnthropicConverseAdapter(settings, transport=transport).converse_stream(
            messages=hello(), tools=[SEARCH_TOOL], budget=budget()
        )
    )

    assert _final(events).tool_calls[0].arguments_json == "{}"


async def test_anthropic_stream_thinking_is_captured_but_not_streamed_as_text(
    settings: Settings,
) -> None:
    def thinking_event(delta: str) -> str:
        return _event(
            "content_block_delta",
            f'{{"type":"content_block_delta","index":0,"delta":{delta}}}',
        )

    transport, _ = recording_transport(
        sse(
            _MESSAGE_START,
            _event(
                "content_block_start",
                '{"type":"content_block_start","index":0,"content_block":'
                '{"type":"thinking","thinking":""}}',
            ),
            thinking_event('{"type":"thinking_delta","thinking":"先"}'),
            thinking_event('{"type":"thinking_delta","thinking":"想"}'),
            thinking_event('{"type":"signature_delta","signature":"sig-9"}'),
            _text_delta("好", index=1),
            _message_delta("end_turn", 4),
            _MESSAGE_STOP,
        )
    )

    events = await _collect(
        AnthropicConverseAdapter(settings, transport=transport).converse_stream(
            messages=hello(), tools=[], budget=budget()
        )
    )

    assert _text(events) == "好"  # 思考内容不是给用户看的正文
    final = _final(events)
    assert final.reasoning is not None and final.reasoning.protocol == "anthropic"
    assert json.loads(final.reasoning.payload) == [
        {"type": "thinking", "thinking": "先想", "signature": "sig-9"}
    ]


async def test_anthropic_stream_charges_tokens_once_at_the_end(settings: Settings) -> None:
    transport, _ = recording_transport(
        sse(_MESSAGE_START, _text_delta("好"), _message_delta("end_turn", 2), _MESSAGE_STOP)
    )
    tracked = budget()

    await _collect(
        AnthropicConverseAdapter(settings, transport=transport).converse_stream(
            messages=hello(), tools=[], budget=tracked
        )
    )

    assert (tracked.calls, tracked.tokens) == (1, 9)


async def test_anthropic_stream_cut_midway_drops_partial_tool_calls(settings: Settings) -> None:
    transport, _ = recording_transport(sse(_MESSAGE_START, _TOOL_USE_START, _json_delta('{"q')))

    events = await _collect(
        AnthropicConverseAdapter(settings, transport=transport).converse_stream(
            messages=hello(), tools=[SEARCH_TOOL], budget=budget()
        )
    )

    final = _final(events)
    assert final.stop_reason == "ERROR" and final.degraded and final.tool_calls == []
    assert final.failure_kind is LlmFailureKind.NETWORK


async def test_anthropic_stream_cut_midway_keeps_the_text_already_shown(
    settings: Settings,
) -> None:
    transport, _ = recording_transport(sse(_MESSAGE_START, _text_delta("你")))

    events = await _collect(
        AnthropicConverseAdapter(settings, transport=transport).converse_stream(
            messages=hello(), tools=[], budget=budget()
        )
    )

    final = _final(events)
    assert _text(events) == "你" and final.text == "你" and final.degraded


async def test_anthropic_stream_error_event_degrades_as_http_other(settings: Settings) -> None:
    transport, _ = recording_transport(
        sse(
            _MESSAGE_START,
            _event(
                "error",
                '{"type":"error","error":{"type":"overloaded_error","message":"busy"}}',
            ),
        )
    )

    events = await _collect(
        AnthropicConverseAdapter(settings, transport=transport).converse_stream(
            messages=hello(), tools=[], budget=budget()
        )
    )

    final = _final(events)
    assert final.failure_kind is LlmFailureKind.HTTP_OTHER and final.degraded


async def test_anthropic_stream_ignores_ping_events(settings: Settings) -> None:
    transport, _ = recording_transport(
        sse(
            _MESSAGE_START,
            _event("ping", '{"type":"ping"}'),
            _text_delta("好"),
            _message_delta("end_turn", 1),
            _MESSAGE_STOP,
        )
    )

    events = await _collect(
        AnthropicConverseAdapter(settings, transport=transport).converse_stream(
            messages=hello(), tools=[], budget=budget()
        )
    )

    assert _final(events).text == "好"


async def test_anthropic_stream_http_error_yields_a_single_degraded_turn(
    settings: Settings,
) -> None:
    transport, _ = recording_transport(httpx.Response(401))

    events = await _collect(
        AnthropicConverseAdapter(settings, transport=transport).converse_stream(
            messages=hello(), tools=[], budget=budget()
        )
    )

    assert len(events) == 1
    assert _final(events).failure_kind is LlmFailureKind.HTTP_401


async def test_anthropic_stream_counts_cache_read_tokens_from_message_start(
    settings: Settings,
) -> None:
    """流式也一样：message_start 里的 input_tokens 不含命中部分，命中数要一并计入。"""

    start = _event(
        "message_start",
        '{"type":"message_start","message":{"usage":{"input_tokens":162,'
        '"cache_creation_input_tokens":0,"cache_read_input_tokens":1408,"output_tokens":0}}}',
    )
    transport, _ = recording_transport(
        sse(start, _text_delta("6"), _message_delta("end_turn", 1), _MESSAGE_STOP)
    )

    events = await _collect(
        AnthropicConverseAdapter(settings, transport=transport).converse_stream(
            messages=hello(), tools=[], budget=budget(max_tokens=5_000)
        )
    )

    final = _final(events)
    assert final.tokens == 1571 and (final.input_tokens, final.output_tokens) == (1570, 1)
    assert (final.cache_hit_tokens, final.cache_miss_tokens) == (1408, 162)


async def test_anthropic_stream_with_the_real_usage_event_shape(settings: Settings) -> None:
    """2026-09-22 读原始流实测：message_delta 带的是**完整** usage（含输入与缓存），不只 output。

    两个事件的 usage 都原样取自真实响应。适配器按字段覆盖合并，结果须与非流式同一请求一致。
    """

    usage_start = (
        '{"cache_creation_input_tokens":0,"cache_read_input_tokens":1408,'
        '"input_tokens":162,"output_tokens":0,"service_tier":"standard"}'
    )
    usage_delta = (
        '{"cache_creation_input_tokens":0,"cache_read_input_tokens":1408,'
        '"input_tokens":162,"output_tokens":1,"service_tier":"standard"}'
    )
    transport, _ = recording_transport(
        sse(
            _event(
                "message_start",
                f'{{"type":"message_start","message":{{"usage":{usage_start}}}}}',
            ),
            _text_delta("10"),
            _event(
                "message_delta",
                '{"type":"message_delta","delta":{"stop_reason":"end_turn"},'
                f'"usage":{usage_delta}}}',
            ),
            _MESSAGE_STOP,
        )
    )

    events = await _collect(
        AnthropicConverseAdapter(settings, transport=transport).converse_stream(
            messages=hello(), tools=[], budget=budget(max_tokens=5_000)
        )
    )

    final = _final(events)
    assert final.tokens == 1571 and (final.input_tokens, final.output_tokens) == (1570, 1)
    assert (final.cache_hit_tokens, final.cache_miss_tokens) == (1408, 162)
    assert final.usage_known is True


async def test_anthropic_stream_budget_is_checked_before_the_request(settings: Settings) -> None:
    transport, seen = recording_transport()

    with pytest.raises(LlmBudgetExceededError):
        await _collect(
            AnthropicConverseAdapter(settings, transport=transport).converse_stream(
                messages=hello(), tools=[], budget=budget(max_calls=0)
            )
        )

    assert seen == []
