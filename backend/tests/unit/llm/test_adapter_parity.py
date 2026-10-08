"""两个适配器喂等价响应，产出的 ``LlmTurn`` 必须逐字段相等。

这条测试的价值在于：将来换协议时，上层循环不该察觉任何差异。**但它只证明两个适配器对
「我们以为的响应格式」解析一致，不证明两个真实接口行为等价**——尤其是多轮工具历史，
文档称 OpenAI 兼容接口在思考模式下缺少 ``reasoning_content`` 会 400（实测未复现）。
两协议是否都能跑通多轮工具调用，只能由真实冒烟回答，未实测前不得宣称等价。

``reasoning`` 与缓存字段按协议而异，不纳入逐字段比较，只在各自的测试里断言。
"""

from __future__ import annotations

import httpx

from app.core.config import Settings
from app.llm.anthropic_adapter import AnthropicConverseAdapter
from app.llm.client import LlmStreamEvent, LlmTurn, TurnComplete
from app.llm.openai_adapter import OpenAiConverseAdapter
from tests.unit.llm._transport import SEARCH_TOOL, budget, hello, recording_transport, sse

_COMPARED = (
    "text",
    "tool_calls",
    "stop_reason",
    "tokens",
    "input_tokens",
    "output_tokens",
    "usage_known",
    "degraded",
    "failure_kind",
)


def _shape(turn: LlmTurn) -> dict[str, object]:
    return {name: getattr(turn, name) for name in _COMPARED}


def _final(events: list[LlmStreamEvent]) -> LlmTurn:
    assert isinstance(events[-1], TurnComplete)
    return events[-1].turn


async def test_single_turn_text_is_identical_across_protocols(settings: Settings) -> None:
    openai, _ = recording_transport(
        httpx.Response(
            200,
            json={
                "choices": [{"finish_reason": "stop", "message": {"content": "本店有 2 款"}}],
                "usage": {"total_tokens": 15, "prompt_tokens": 10, "completion_tokens": 5},
            },
        )
    )
    anthropic, _ = recording_transport(
        httpx.Response(
            200,
            json={
                "content": [{"type": "text", "text": "本店有 2 款"}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 10, "output_tokens": 5},
            },
        )
    )

    a = await OpenAiConverseAdapter(settings, transport=openai).converse(
        messages=hello(), tools=[], budget=budget()
    )
    b = await AnthropicConverseAdapter(settings, transport=anthropic).converse(
        messages=hello(), tools=[], budget=budget()
    )

    assert _shape(a) == _shape(b)


async def test_single_turn_tool_call_is_identical_across_protocols(settings: Settings) -> None:
    openai, _ = recording_transport(
        httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "tool_calls",
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "c1",
                                    "type": "function",
                                    "function": {"name": "search", "arguments": '{"q":"壶"}'},
                                }
                            ],
                        },
                    }
                ],
                "usage": {"total_tokens": 30, "prompt_tokens": 20, "completion_tokens": 10},
            },
        )
    )
    anthropic, _ = recording_transport(
        httpx.Response(
            200,
            json={
                "content": [
                    {"type": "tool_use", "id": "c1", "name": "search", "input": {"q": "壶"}}
                ],
                "stop_reason": "tool_use",
                "usage": {"input_tokens": 20, "output_tokens": 10},
            },
        )
    )

    a = await OpenAiConverseAdapter(settings, transport=openai).converse(
        messages=hello(), tools=[SEARCH_TOOL], budget=budget()
    )
    b = await AnthropicConverseAdapter(settings, transport=anthropic).converse(
        messages=hello(), tools=[SEARCH_TOOL], budget=budget()
    )

    assert _shape(a) == _shape(b)


async def test_streamed_text_is_identical_across_protocols(settings: Settings) -> None:
    openai, _ = recording_transport(
        sse(
            'data: {"choices":[{"delta":{"content":"你"}}]}',
            'data: {"choices":[{"delta":{"content":"好"},"finish_reason":"stop"}]}',
            'data: {"choices":[],"usage":{"total_tokens":9,"prompt_tokens":7,'
            '"completion_tokens":2}}',
            "data: [DONE]",
        )
    )
    anthropic, _ = recording_transport(
        sse(
            'event: message_start\ndata: {"type":"message_start","message":'
            '{"usage":{"input_tokens":7,"output_tokens":0}}}',
            'event: content_block_delta\ndata: {"type":"content_block_delta","index":0,'
            '"delta":{"type":"text_delta","text":"你"}}',
            'event: content_block_delta\ndata: {"type":"content_block_delta","index":0,'
            '"delta":{"type":"text_delta","text":"好"}}',
            'event: message_delta\ndata: {"type":"message_delta","delta":'
            '{"stop_reason":"end_turn"},"usage":{"output_tokens":2}}',
            'event: message_stop\ndata: {"type":"message_stop"}',
        )
    )

    a = _final(
        [
            e
            async for e in OpenAiConverseAdapter(settings, transport=openai).converse_stream(
                messages=hello(), tools=[], budget=budget()
            )
        ]
    )
    b = _final(
        [
            e
            async for e in AnthropicConverseAdapter(settings, transport=anthropic).converse_stream(
                messages=hello(), tools=[], budget=budget()
            )
        ]
    )

    assert _shape(a) == _shape(b)


async def test_cached_prompt_usage_is_identical_across_protocols(settings: Settings) -> None:
    """同一段提示、同一次缓存命中，两协议报出的用量必须折算成同样的数字。

    数值取自 2026-09-22 的真实冒烟：OpenAI 报 prompt 1570（命中 1408 / 未命中 162），
    Anthropic 报 input_tokens=162 + cache_read_input_tokens=1408。
    """

    openai, _ = recording_transport(
        httpx.Response(
            200,
            json={
                "choices": [{"finish_reason": "stop", "message": {"content": "6"}}],
                "usage": {
                    "total_tokens": 1571,
                    "prompt_tokens": 1570,
                    "completion_tokens": 1,
                    "prompt_cache_hit_tokens": 1408,
                    "prompt_cache_miss_tokens": 162,
                },
            },
        )
    )
    anthropic, _ = recording_transport(
        httpx.Response(
            200,
            json={
                "content": [{"type": "text", "text": "6"}],
                "stop_reason": "end_turn",
                "usage": {
                    "input_tokens": 162,
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 1408,
                    "output_tokens": 1,
                },
            },
        )
    )

    a = await OpenAiConverseAdapter(settings, transport=openai).converse(
        messages=hello(), tools=[], budget=budget(max_tokens=5_000)
    )
    b = await AnthropicConverseAdapter(settings, transport=anthropic).converse(
        messages=hello(), tools=[], budget=budget(max_tokens=5_000)
    )

    assert _shape(a) == _shape(b)
    assert (a.cache_hit_tokens, a.cache_miss_tokens) == (b.cache_hit_tokens, b.cache_miss_tokens)


async def test_http_429_is_identical_across_protocols(settings: Settings) -> None:
    openai, _ = recording_transport(httpx.Response(429))
    anthropic, _ = recording_transport(httpx.Response(429))

    a = await OpenAiConverseAdapter(settings, transport=openai).converse(
        messages=hello(), tools=[], budget=budget()
    )
    b = await AnthropicConverseAdapter(settings, transport=anthropic).converse(
        messages=hello(), tools=[], budget=budget()
    )

    assert _shape(a) == _shape(b)
