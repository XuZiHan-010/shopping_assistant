"""``LLM_PROTOCOL`` 开关：``DeepSeekLlmClient`` 把 ``converse*`` 委派给选定的适配器。"""

from __future__ import annotations

import httpx
import pytest

from app.llm.client import LlmUnavailableError, TextDelta, TurnComplete
from app.llm.deepseek import DeepSeekLlmClient
from tests.unit.llm._transport import (
    ANTHROPIC_URL,
    OPENAI_URL,
    budget,
    hello,
    make_settings,
    recording_transport,
    sse,
)

_OPENAI_OK = {
    "choices": [{"finish_reason": "stop", "message": {"content": "好"}}],
    "usage": {"total_tokens": 3, "prompt_tokens": 2, "completion_tokens": 1},
}
_ANTHROPIC_OK = {
    "content": [{"type": "text", "text": "好"}],
    "stop_reason": "end_turn",
    "usage": {"input_tokens": 2, "output_tokens": 1},
}


async def test_default_protocol_is_openai() -> None:
    transport, seen = recording_transport(httpx.Response(200, json=_OPENAI_OK))

    turn = await DeepSeekLlmClient(make_settings(), transport=transport).converse(
        messages=hello(), tools=[], budget=budget()
    )

    assert str(seen[0].url) == OPENAI_URL
    assert turn.text == "好"


async def test_anthropic_protocol_routes_to_the_anthropic_endpoint() -> None:
    transport, seen = recording_transport(httpx.Response(200, json=_ANTHROPIC_OK))

    turn = await DeepSeekLlmClient(
        make_settings(llm_protocol="anthropic"), transport=transport
    ).converse(messages=hello(), tools=[], budget=budget())

    assert str(seen[0].url) == ANTHROPIC_URL
    assert seen[0].headers["x-api-key"] == "test-key"
    assert turn.text == "好"


async def test_stream_follows_the_protocol_switch_too() -> None:
    transport, seen = recording_transport(
        sse(
            'data: {"choices":[{"delta":{"content":"好"},"finish_reason":"stop"}]}',
            "data: [DONE]",
        )
    )

    events = [
        e
        async for e in DeepSeekLlmClient(make_settings(), transport=transport).converse_stream(
            messages=hello(), tools=[], budget=budget()
        )
    ]

    assert str(seen[0].url) == OPENAI_URL
    assert isinstance(events[0], TextDelta) and isinstance(events[-1], TurnComplete)


async def test_anthropic_stream_routes_to_the_anthropic_endpoint() -> None:
    transport, seen = recording_transport(
        sse(
            'event: message_start\ndata: {"type":"message_start","message":'
            '{"usage":{"input_tokens":1,"output_tokens":0}}}',
            'event: message_delta\ndata: {"type":"message_delta","delta":'
            '{"stop_reason":"end_turn"},"usage":{"output_tokens":1}}',
        )
    )

    events = [
        e
        async for e in DeepSeekLlmClient(
            make_settings(llm_protocol="anthropic"), transport=transport
        ).converse_stream(messages=hello(), tools=[], budget=budget())
    ]

    assert str(seen[0].url) == ANTHROPIC_URL
    assert isinstance(events[-1], TurnComplete)


async def test_complete_is_unaffected_by_the_protocol_switch() -> None:
    """v1 链路继续走 OpenAI 兼容的 /chat/completions，不随 LLM_PROTOCOL 漂移。"""

    transport, seen = recording_transport(
        httpx.Response(200, json={"choices": [{"message": {"content": "回答"}}], "usage": {}})
    )

    result = await DeepSeekLlmClient(
        make_settings(llm_protocol="anthropic"), transport=transport
    ).complete(system="s", user="u", fallback="f", budget=budget())

    assert str(seen[0].url) == OPENAI_URL
    assert result.text == "回答"


async def test_unconfigured_client_raises_before_any_request() -> None:
    transport, seen = recording_transport()
    client = DeepSeekLlmClient(make_settings(llm_api_key=None), transport=transport)

    with pytest.raises(LlmUnavailableError):
        await client.converse(messages=hello(), tools=[], budget=budget())
    assert seen == []
