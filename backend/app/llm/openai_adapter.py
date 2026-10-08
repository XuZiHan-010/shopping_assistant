"""DeepSeek OpenAI 兼容协议的 ``converse()`` / ``converse_stream()``。

根地址 ``LLM_BASE_URL``（``https://api.deepseek.com``），端点 ``/chat/completions``。
测试仅使用 ``httpx.MockTransport``，生产不传 ``transport``。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping, Sequence

import httpx

from app.core.config import Settings
from app.llm.adapter_support import (
    StreamTruncatedError,
    TokenUsage,
    classify_upstream_error,
    effective_thinking,
    failed_turn,
    iter_sse_data,
    optional_usage_int,
    require_configured,
    reserve_call,
    usage_int,
)
from app.llm.client import (
    DEFAULT_LLM_CALL_OPTIONS,
    LlmBudget,
    LlmCallOptions,
    LlmMessage,
    LlmStopReason,
    LlmStreamEvent,
    LlmToolCall,
    LlmTurn,
    ReasoningReplay,
    TextDelta,
    ToolSchema,
    TurnComplete,
)

_PATH = "/chat/completions"


def serialize_openai_messages(messages: Sequence[LlmMessage]) -> list[dict[str, object]]:
    """把协议无关的消息历史转成 OpenAI 格式。

    工具调用参数按原串回放，不重新序列化——历史里的畸形参数是模型当时真实产出的，
    回放必须与上一轮响应逐字一致。
    """

    serialized: list[dict[str, object]] = []
    for message in messages:
        if message.role == "tool":
            serialized.append(
                {"role": "tool", "tool_call_id": message.tool_call_id, "content": message.content}
            )
        elif message.role == "assistant":
            # 带工具调用而没有正文时发 null：这正是 API 自己返回的形状。
            content = (message.content or None) if message.tool_calls else message.content
            entry: dict[str, object] = {"role": "assistant", "content": content}
            if message.tool_calls:
                entry["tool_calls"] = [
                    {
                        "id": call.call_id,
                        "type": "function",
                        "function": {"name": call.tool_name, "arguments": call.arguments_json},
                    }
                    for call in message.tool_calls
                ]
            if message.reasoning is not None:
                if message.reasoning.protocol != "openai":
                    raise ValueError(
                        f"推理内容来自 {message.reasoning.protocol} 协议，无法回放给 openai 协议；"
                        "切换协议时应新开对话"
                    )
                # 文档要求回传；2026-09-22 实测省略也未被拒，仍回传以防上游收紧。
                entry["reasoning_content"] = message.reasoning.payload
            serialized.append(entry)
        else:
            serialized.append({"role": message.role, "content": message.content})
    return serialized


def _tool_payload(tool: ToolSchema) -> dict[str, object]:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
        },
    }


def _parse_usage(raw: object) -> TokenUsage:
    if raw is None:
        return TokenUsage()
    if not isinstance(raw, Mapping):
        raise ValueError("响应 usage 形状无效")
    return TokenUsage(
        tokens=usage_int(raw, "total_tokens"),
        input_tokens=usage_int(raw, "prompt_tokens"),
        output_tokens=usage_int(raw, "completion_tokens"),
        known={"total_tokens", "prompt_tokens", "completion_tokens"} <= raw.keys(),
        cache_hit_tokens=optional_usage_int(raw, "prompt_cache_hit_tokens"),
        cache_miss_tokens=optional_usage_int(raw, "prompt_cache_miss_tokens"),
    )


def _parse_tool_call(raw: object) -> LlmToolCall:
    if not isinstance(raw, Mapping):
        raise ValueError("tool_calls 元素形状无效")
    function = raw.get("function")
    call_id = raw.get("id")
    if not isinstance(function, Mapping) or not isinstance(call_id, str) or not call_id:
        raise ValueError("tool_calls 元素缺少 id 或 function")
    name = function.get("name")
    arguments = function.get("arguments")
    if not isinstance(name, str) or not name:
        raise ValueError("tool_calls 元素缺少工具名")
    if not isinstance(arguments, str):
        raise ValueError("tool_calls 元素的 arguments 不是字符串")
    return LlmToolCall(call_id=call_id, tool_name=name, arguments_json=arguments)


def _build_turn(
    *,
    finish_reason: object,
    text: str | None,
    tool_calls: list[LlmToolCall],
    reasoning: str | None,
    usage: TokenUsage,
) -> LlmTurn:
    stop_reason: LlmStopReason
    if finish_reason == "length":
        # 参数可能是半截的，交给上层只会被误执行。
        stop_reason, tool_calls = "MAX_TOKENS", []
    elif finish_reason == "tool_calls" and not tool_calls:
        raise ValueError("finish_reason=tool_calls 但没有工具调用")
    elif finish_reason in ("stop", "tool_calls"):
        stop_reason = "TOOL_USE" if tool_calls else "END_TURN"
    else:
        raise ValueError(f"不支持的 finish_reason: {finish_reason!r}")
    if stop_reason == "END_TURN" and text is None:
        text = ""  # 模型返回了空内容：交给调用方降级，而不是让 LlmTurn 的构造报错
    elif stop_reason == "TOOL_USE":
        text = text or None  # 工具调用回合没有正文时统一为 None
    return LlmTurn(
        text=text,
        tool_calls=tool_calls,
        stop_reason=stop_reason,
        tokens=usage.tokens,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        usage_known=usage.known,
        cache_hit_tokens=usage.cache_hit_tokens,
        cache_miss_tokens=usage.cache_miss_tokens,
        reasoning=ReasoningReplay("openai", reasoning) if reasoning else None,
    )


def _turn_from_body(body: object) -> LlmTurn:
    if not isinstance(body, Mapping):
        raise ValueError("响应顶层不是对象")
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], Mapping):
        raise ValueError("响应 choices 形状无效")
    choice = choices[0]
    message = choice.get("message")
    if not isinstance(message, Mapping):
        raise ValueError("响应 message 形状无效")
    content = message.get("content")
    if content is not None and not isinstance(content, str):
        raise ValueError("响应 message.content 形状无效")
    reasoning = message.get("reasoning_content")
    raw_calls = message.get("tool_calls")
    if raw_calls is not None and not isinstance(raw_calls, list):
        raise ValueError("响应 tool_calls 形状无效")
    return _build_turn(
        finish_reason=choice.get("finish_reason"),
        text=content,
        tool_calls=[_parse_tool_call(item) for item in raw_calls or []],
        reasoning=reasoning if isinstance(reasoning, str) else None,
        usage=_parse_usage(body.get("usage")),
    )


class _StreamState:
    """累积一次流式响应；工具调用的参数分片按 ``index`` 在这里拼完。"""

    def __init__(self) -> None:
        self.text_parts: list[str] = []
        self._reasoning_parts: list[str] = []
        self._calls: dict[int, dict[str, str]] = {}
        self._finish_reason: object = None
        self._usage = TokenUsage()

    @property
    def text(self) -> str:
        return "".join(self.text_parts)

    def feed(self, data: str) -> str | None:
        """处理一个 ``data:`` 载荷，返回需要立即产出的文本增量（若有）。"""

        chunk = json.loads(data)
        if not isinstance(chunk, Mapping):
            raise ValueError("流式分片顶层不是对象")
        if chunk.get("usage") is not None:
            self._usage = _parse_usage(chunk["usage"])
        choices = chunk.get("choices")
        if not isinstance(choices, list) or not choices:
            return None
        choice = choices[0]
        if not isinstance(choice, Mapping):
            raise ValueError("流式分片 choices 形状无效")
        if choice.get("finish_reason") is not None:
            self._finish_reason = choice["finish_reason"]
        delta = choice.get("delta")
        if not isinstance(delta, Mapping):
            return None
        reasoning = delta.get("reasoning_content")
        if isinstance(reasoning, str):
            self._reasoning_parts.append(reasoning)
        for fragment in delta.get("tool_calls") or []:
            self._feed_tool_call(fragment)
        content = delta.get("content")
        if isinstance(content, str) and content:
            self.text_parts.append(content)
            return content
        return None

    def _feed_tool_call(self, fragment: object) -> None:
        if not isinstance(fragment, Mapping) or not isinstance(fragment.get("index"), int):
            raise ValueError("流式 tool_calls 分片形状无效")
        slot = self._calls.setdefault(fragment["index"], {"id": "", "name": "", "arguments": ""})
        if isinstance(fragment.get("id"), str):
            slot["id"] = fragment["id"]
        function = fragment.get("function")
        if isinstance(function, Mapping):
            if isinstance(function.get("name"), str):
                slot["name"] = function["name"]
            if isinstance(function.get("arguments"), str):
                slot["arguments"] += function["arguments"]

    def finish(self) -> LlmTurn:
        if self._finish_reason is None:
            raise StreamTruncatedError("流在结束标记前断开")
        calls = [
            _parse_tool_call(
                {
                    "id": slot["id"],
                    "function": {"name": slot["name"], "arguments": slot["arguments"]},
                }
            )
            for _, slot in sorted(self._calls.items())
        ]
        return _build_turn(
            finish_reason=self._finish_reason,
            text=self.text or None,
            tool_calls=calls,
            reasoning="".join(self._reasoning_parts) or None,
            usage=self._usage,
        )


class OpenAiConverseAdapter:
    def __init__(
        self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._settings, self._transport = settings, transport

    def is_configured(self) -> bool:
        return bool(self._settings.llm_api_key)

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self._settings.llm_base_url,
            timeout=self._settings.llm_timeout_seconds,
            transport=self._transport,
        )

    def _headers(self) -> dict[str, str]:
        return {"authorization": f"Bearer {self._settings.llm_api_key}"}

    def _prepare(
        self,
        messages: list[LlmMessage],
        tools: list[ToolSchema],
        budget: LlmBudget,
        options: LlmCallOptions,
        *,
        stream: bool,
    ) -> dict[str, object]:
        require_configured(self._settings)
        # 序列化放在扣预算之前：本地的构造错误是调用方的 bug，不该白扣一次配额。
        serialized = serialize_openai_messages(messages)
        payload: dict[str, object] = {
            "model": self._settings.llm_model,
            "messages": serialized,
            "stream": stream,
            "max_tokens": reserve_call(self._settings, budget, options),
            # 每次都显式发送：官方默认开启思考模式，不发就会随提供方默认值漂移。
            "thinking": {"type": effective_thinking(self._settings, options)},
        }
        if tools:
            payload["tools"] = [_tool_payload(tool) for tool in tools]
        if options.json_output:
            payload["response_format"] = {"type": "json_object"}
        if stream:
            payload["stream_options"] = {"include_usage": True}
        return payload

    async def converse(
        self,
        *,
        messages: list[LlmMessage],
        tools: list[ToolSchema],
        budget: LlmBudget,
        options: LlmCallOptions = DEFAULT_LLM_CALL_OPTIONS,
    ) -> LlmTurn:
        payload = self._prepare(messages, tools, budget, options, stream=False)
        try:
            async with self._client() as client:
                response = await client.post(_PATH, json=payload, headers=self._headers())
                response.raise_for_status()
                body = response.json()
            turn = _turn_from_body(body)
        except (httpx.HTTPError, ValueError) as error:
            kind, status = classify_upstream_error(error)
            return failed_turn(self._settings, "openai", kind, status)
        budget.charge(turn.tokens)
        return turn

    async def converse_stream(
        self,
        *,
        messages: list[LlmMessage],
        tools: list[ToolSchema],
        budget: LlmBudget,
        options: LlmCallOptions = DEFAULT_LLM_CALL_OPTIONS,
    ) -> AsyncIterator[LlmStreamEvent]:
        payload = self._prepare(messages, tools, budget, options, stream=True)
        state = _StreamState()
        turn: LlmTurn | None = None
        try:
            async with (
                self._client() as client,
                client.stream("POST", _PATH, json=payload, headers=self._headers()) as response,
            ):
                response.raise_for_status()
                async for data in iter_sse_data(response):
                    if data == "[DONE]":
                        break
                    delta = state.feed(data)
                    if delta is not None:
                        yield TextDelta(text=delta)
                else:
                    raise StreamTruncatedError("流在 [DONE] 前断开")
            turn = state.finish()
        except (httpx.HTTPError, ValueError, StreamTruncatedError) as error:
            kind, status = classify_upstream_error(error)
            turn = failed_turn(self._settings, "openai", kind, status, text=state.text or None)
        if not turn.degraded:
            budget.charge(turn.tokens)
        yield TurnComplete(turn=turn)
