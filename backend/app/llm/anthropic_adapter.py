"""DeepSeek Anthropic 兼容协议的 ``converse()`` / ``converse_stream()``。

协议地址 ``https://api.deepseek.com/anthropic``。``LLM_BASE_URL`` 仍存根地址，
``/anthropic`` 由本适配器内部拼接（AGENTS.md R3）。测试仅使用 ``httpx.MockTransport``。

与 OpenAI 协议的差异全部在这里吸收，让 ``LlmTurn`` 在两种协议下形状完全一致：

- system 是顶层参数，不在 ``messages`` 里；
- 工具调用是 ``content[]`` 里 ``type="tool_use"`` 的块，``input`` 是对象——本适配器把它序列化回
  字符串放进 ``arguments_json``（唯一允许适配器碰参数的地方，只做序列化，不做校验）；
- 用量是 ``input_tokens`` + ``output_tokens``，**没有 total**，要自己相加；
- 官方文档未列缓存用量字段，但 2026-09-22 真实冒烟实测（原始 ``usage`` 对象）：接口上报
  ``cache_read_input_tokens`` / ``cache_creation_input_tokens``，且 ``input_tokens``
  **不含**命中部分，总输入要三者相加（见 ``_usage_from``）。未上报这些字段时缓存计量仍是 ``None``。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping, Sequence

import httpx

from app.core.config import Settings
from app.llm.adapter_support import (
    StreamErrorEvent,
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

_PATH = "/anthropic/v1/messages"
_ANTHROPIC_VERSION = "2023-06-01"
_THINKING_BLOCK_TYPES = ("thinking", "redacted_thinking")


def _compact_json(value: object) -> str:
    # 与 OpenAI 协议下常见的紧凑写法一致，上层循环拿到的参数串才不因协议而异。
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _thinking_blocks(reasoning: ReasoningReplay) -> list[dict[str, object]]:
    if reasoning.protocol != "anthropic":
        raise ValueError(
            f"推理内容来自 {reasoning.protocol} 协议，无法回放给 anthropic 协议；"
            "切换协议时应新开对话"
        )
    try:
        blocks = json.loads(reasoning.payload)
    except ValueError:
        blocks = None
    if not isinstance(blocks, list) or not all(isinstance(b, dict) for b in blocks):
        raise ValueError("anthropic 协议的推理回放必须是 thinking 块的 JSON 数组")
    return blocks


def _tool_use_block(call: LlmToolCall) -> dict[str, object]:
    try:
        arguments = json.loads(call.arguments_json)
    except ValueError:
        arguments = None
    if not isinstance(arguments, dict):
        raise ValueError(
            f"工具调用 {call.call_id} 的参数不是 JSON 对象，无法回放为 anthropic 的 tool_use.input"
        )
    return {"type": "tool_use", "id": call.call_id, "name": call.tool_name, "input": arguments}


def serialize_anthropic_messages(
    messages: Sequence[LlmMessage],
) -> tuple[str | None, list[dict[str, object]]]:
    """把协议无关的消息历史转成 ``(顶层 system, messages)``。

    - system 消息不进 ``messages``，多条用空行连接；
    - 同一轮的多个工具结果合并进**同一条** user 消息（Anthropic 要求角色交替）；
    - assistant 的 thinking 块排在最前，随后是文本，再是 tool_use 块，与 API 返回的顺序一致。
    """

    system_parts: list[str] = []
    serialized: list[dict[str, object]] = []
    pending_results: list[dict[str, object]] = []

    def flush_results() -> None:
        if pending_results:
            serialized.append({"role": "user", "content": list(pending_results)})
            pending_results.clear()

    for message in messages:
        if message.role == "tool":
            pending_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": message.tool_call_id,
                    "content": message.content,
                }
            )
            continue
        flush_results()
        if message.role == "system":
            system_parts.append(message.content)
        elif message.role == "assistant":
            blocks: list[dict[str, object]] = []
            if message.reasoning is not None:
                blocks.extend(_thinking_blocks(message.reasoning))
            if message.content:
                blocks.append({"type": "text", "text": message.content})
            blocks.extend(_tool_use_block(call) for call in message.tool_calls or [])
            if len(blocks) == 1 and blocks[0]["type"] == "text":
                serialized.append({"role": "assistant", "content": message.content})
            else:
                serialized.append({"role": "assistant", "content": blocks})
        else:
            serialized.append({"role": "user", "content": message.content})
    flush_results()
    return ("\n\n".join(system_parts) if system_parts else None), serialized


def _tool_payload(tool: ToolSchema) -> dict[str, object]:
    return {"name": tool.name, "description": tool.description, "input_schema": tool.parameters}


_REQUIRED_USAGE_KEYS = ("input_tokens", "output_tokens")
# 缓存计量只是附带信息：非法值按「未上报」处理，不因此判整次响应损坏。
_CACHE_USAGE_KEYS = ("cache_read_input_tokens", "cache_creation_input_tokens")


def _merge_usage(current: dict[str, int], raw: object) -> None:
    """流里用量分两处到达（message_start 与 message_delta），逐字段覆盖式合并。"""

    if raw is None:
        return
    if not isinstance(raw, Mapping):
        raise ValueError("响应 usage 形状无效")
    for key in _REQUIRED_USAGE_KEYS:
        if key in raw:
            current[key] = usage_int(raw, key)
    for key in _CACHE_USAGE_KEYS:
        cached = optional_usage_int(raw, key)
        if cached is not None:
            current[key] = cached


def _usage_from(fields: Mapping[str, int]) -> TokenUsage:
    """把 Anthropic 的用量折算成与 OpenAI 协议一致的口径。

    2026-09-22 真实冒烟实测：``input_tokens`` **只含缓存未命中的部分**，命中数另在
    ``cache_read_input_tokens``（同一段 1570 token 的提示：``input_tokens=162``、
    ``cache_read_input_tokens=1408``，与 OpenAI 协议的 ``prompt_tokens=1570`` 吻合）。
    因此总输入 = ``input_tokens`` + 写入缓存 + 命中缓存；只读 ``input_tokens`` 会在命中缓存时低估。
    """

    uncached = fields.get("input_tokens", 0)
    written = fields.get("cache_creation_input_tokens", 0)
    read = fields.get("cache_read_input_tokens")
    total_input = uncached + written + (read or 0)
    output_tokens = fields.get("output_tokens", 0)
    return TokenUsage(
        # Anthropic 格式没有 total_tokens，必须自己相加。
        tokens=total_input + output_tokens,
        input_tokens=total_input,
        output_tokens=output_tokens,
        # 缺任何一项，总数就是残缺的：不能宣称用量已知，否则会少记成本。
        known=all(key in fields for key in _REQUIRED_USAGE_KEYS),
        # 接口明确上报了命中数才算上报；写入缓存的部分不是命中，归入未命中。
        cache_hit_tokens=read,
        cache_miss_tokens=uncached + written if read is not None else None,
    )


def _parse_usage(raw: object) -> TokenUsage:
    fields: dict[str, int] = {}
    _merge_usage(fields, raw)
    return _usage_from(fields)


def _build_turn(
    *,
    stop_reason_raw: object,
    text_parts: list[str],
    tool_calls: list[LlmToolCall],
    thinking: list[dict[str, object]],
    usage: TokenUsage,
) -> LlmTurn:
    stop_reason: LlmStopReason
    if stop_reason_raw == "max_tokens":
        # tool_use 的 input 可能是半截的，交给上层只会被误执行。
        stop_reason, tool_calls = "MAX_TOKENS", []
    elif stop_reason_raw == "tool_use" and not tool_calls:
        raise ValueError("stop_reason=tool_use 但没有 tool_use 块")
    elif stop_reason_raw in ("end_turn", "stop_sequence", "tool_use"):
        stop_reason = "TOOL_USE" if tool_calls else "END_TURN"
    else:
        raise ValueError(f"不支持的 stop_reason: {stop_reason_raw!r}")
    text: str | None = "".join(text_parts)
    if stop_reason != "END_TURN" and not text:
        text = None
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
        reasoning=ReasoningReplay("anthropic", _compact_json(thinking)) if thinking else None,
    )


def _turn_from_body(body: object) -> LlmTurn:
    if not isinstance(body, Mapping):
        raise ValueError("响应顶层不是对象")
    content = body.get("content")
    if not isinstance(content, list):
        raise ValueError("响应 content 形状无效")
    text_parts: list[str] = []
    tool_calls: list[LlmToolCall] = []
    thinking: list[dict[str, object]] = []
    for block in content:
        if not isinstance(block, Mapping):
            raise ValueError("响应 content 块形状无效")
        kind = block.get("type")
        if kind == "text":
            text = block.get("text")
            if not isinstance(text, str):
                raise ValueError("text 块缺少 text")
            text_parts.append(text)
        elif kind == "tool_use":
            call_id, name, arguments = block.get("id"), block.get("name"), block.get("input")
            if not isinstance(call_id, str) or not call_id or not isinstance(name, str) or not name:
                raise ValueError("tool_use 块缺少 id 或 name")
            if not isinstance(arguments, Mapping):
                raise ValueError("tool_use 块的 input 不是对象")
            tool_calls.append(LlmToolCall(call_id, name, _compact_json(arguments)))
        elif kind in _THINKING_BLOCK_TYPES:
            thinking.append(dict(block))
    return _build_turn(
        stop_reason_raw=body.get("stop_reason"),
        text_parts=text_parts,
        tool_calls=tool_calls,
        thinking=thinking,
        usage=_parse_usage(body.get("usage")),
    )


class _Block:
    """流里一个 content block 的累积状态；类型由 start 事件或首个增量确定。"""

    def __init__(self, kind: str) -> None:
        self.kind = kind
        self.text = ""
        self.thinking = ""
        self.signature = ""
        self.call_id = ""
        self.name = ""
        self.initial_input: object = None
        self.json_parts: list[str] = []
        self.redacted_thinking: dict[str, object] | None = None


class _StreamState:
    def __init__(self) -> None:
        self.text_parts: list[str] = []
        self._blocks: dict[int, _Block] = {}
        self._usage: dict[str, int] = {}
        self._stop_reason: object = None
        self._message_stopped = False

    @property
    def text(self) -> str:
        return "".join(self.text_parts)

    @property
    def message_stopped(self) -> bool:
        return self._message_stopped

    def _block(self, index: object, kind: str) -> _Block:
        if not isinstance(index, int):
            raise ValueError("流式事件缺少 index")
        return self._blocks.setdefault(index, _Block(kind))

    def feed(self, data: str) -> str | None:
        """处理一个 ``data:`` 载荷，返回需要立即产出的文本增量（若有）。"""

        event = json.loads(data)
        if not isinstance(event, Mapping):
            raise ValueError("流式事件顶层不是对象")
        kind = event.get("type")
        if kind == "error":
            raise StreamErrorEvent("上游在流中途返回了错误事件")
        if kind == "message_start":
            message = event.get("message")
            if isinstance(message, Mapping):
                _merge_usage(self._usage, message.get("usage"))
        elif kind == "message_delta":
            delta = event.get("delta")
            if isinstance(delta, Mapping) and delta.get("stop_reason") is not None:
                self._stop_reason = delta["stop_reason"]
            _merge_usage(self._usage, event.get("usage"))
        elif kind == "content_block_start":
            self._start_block(event)
        elif kind == "content_block_delta":
            return self._apply_delta(event)
        elif kind == "message_stop":
            self._message_stopped = True
        return None

    def _start_block(self, event: Mapping[str, object]) -> None:
        start = event.get("content_block")
        if not isinstance(start, Mapping) or not isinstance(start.get("type"), str):
            raise ValueError("content_block_start 形状无效")
        block = self._block(event.get("index"), str(start["type"]))
        block.kind = str(start["type"])
        if isinstance(start.get("id"), str):
            block.call_id = str(start["id"])
        if isinstance(start.get("name"), str):
            block.name = str(start["name"])
        block.initial_input = start.get("input")
        if block.kind == "redacted_thinking":
            block.redacted_thinking = dict(start)

    def _apply_delta(self, event: Mapping[str, object]) -> str | None:
        delta = event.get("delta")
        if not isinstance(delta, Mapping):
            raise ValueError("content_block_delta 形状无效")
        kind = delta.get("type")
        index = event.get("index")
        if kind == "text_delta" and isinstance(delta.get("text"), str):
            text = str(delta["text"])
            self._block(index, "text").text += text
            if text:
                self.text_parts.append(text)
                return text
        elif kind == "thinking_delta" and isinstance(delta.get("thinking"), str):
            self._block(index, "thinking").thinking += str(delta["thinking"])
        elif kind == "signature_delta" and isinstance(delta.get("signature"), str):
            self._block(index, "thinking").signature += str(delta["signature"])
        elif kind == "input_json_delta" and isinstance(delta.get("partial_json"), str):
            self._block(index, "tool_use").json_parts.append(str(delta["partial_json"]))
        return None

    def finish(self) -> LlmTurn:
        if not self._message_stopped or self._stop_reason is None:
            raise StreamTruncatedError("流在结束标记前断开")
        tool_calls: list[LlmToolCall] = []
        thinking: list[dict[str, object]] = []
        for _, block in sorted(self._blocks.items()):
            if block.kind == "tool_use":
                if not block.call_id or not block.name:
                    raise ValueError("流式 tool_use 块缺少 id 或 name")
                if block.json_parts:
                    arguments = "".join(block.json_parts)
                elif isinstance(block.initial_input, Mapping):
                    arguments = _compact_json(block.initial_input)
                else:
                    arguments = "{}"
                tool_calls.append(LlmToolCall(block.call_id, block.name, arguments))
            elif block.kind == "thinking":
                entry: dict[str, object] = {"type": "thinking", "thinking": block.thinking}
                if block.signature:
                    entry["signature"] = block.signature
                thinking.append(entry)
            elif block.kind == "redacted_thinking" and block.redacted_thinking is not None:
                thinking.append(block.redacted_thinking)
        return _build_turn(
            stop_reason_raw=self._stop_reason,
            text_parts=self.text_parts,
            tool_calls=tool_calls,
            thinking=thinking,
            usage=_usage_from(self._usage),
        )


class AnthropicConverseAdapter:
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
        return {
            "x-api-key": str(self._settings.llm_api_key),
            "anthropic-version": _ANTHROPIC_VERSION,
        }

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
        system, serialized = serialize_anthropic_messages(messages)
        payload: dict[str, object] = {
            "model": self._settings.llm_model,
            "messages": serialized,
            "stream": stream,
            "max_tokens": reserve_call(self._settings, budget),
            # 每次都显式发送，不依赖提供方默认值。该接口对思考参数的支持以真实冒烟为准。
            "thinking": {"type": effective_thinking(self._settings, options)},
        }
        if system is not None:
            payload["system"] = system
        if tools:
            payload["tools"] = [_tool_payload(tool) for tool in tools]
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
            return failed_turn(self._settings, "anthropic", kind, status)
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
                    delta = state.feed(data)
                    if state.message_stopped:
                        break
                    if delta is not None:
                        yield TextDelta(text=delta)
            turn = state.finish()
        except (httpx.HTTPError, ValueError, StreamTruncatedError, StreamErrorEvent) as error:
            kind, status = classify_upstream_error(error)
            turn = failed_turn(self._settings, "anthropic", kind, status, text=state.text or None)
        if not turn.degraded:
            budget.charge(turn.tokens)
        yield TurnComplete(turn=turn)
