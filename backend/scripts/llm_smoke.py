"""DeepSeek 双协议真实冒烟脚本。

**本脚本会产生真实费用（AGENTS.md R3），默认不执行任何请求。**

- 不带 ``--yes``：只打印将要发生的调用计划就退出，不联网、不需要 ``LLM_API_KEY``；
- 带 ``--yes``：逐条打印将要发出的调用，然后才发出；
- 只允许授权范围内的端点与模型（``https://api.deepseek.com`` / ``deepseek-flash``），
  换模型、换端点、打开思考模式（``--thinking enabled``）都需要用户另行明确同意；
- 有硬性的总调用次数上限，超出即中止。

它不属于默认测试套件：不得被任何测试或生产代码导入。

用法（每种协议 12 次调用，合计 24 次；先运行不带 ``--yes`` 的版本核对计划）::

    cd backend
    uv run python -m scripts.llm_smoke --protocol openai
    uv run python -m scripts.llm_smoke --protocol openai --yes
    uv run python -m scripts.llm_smoke --protocol anthropic --yes

结果追加写入 ``docs/history/llm-smoke-<date>.md``：只含协议、模型、思考模式、调用次数、token 与
缓存字段原值、每个用例的通过 / 失败与原因。**不记录 API Key，不记录完整请求体。**
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal

import httpx
from pydantic import BaseModel, ValidationError

from app.core.config import Settings
from app.llm.client import (
    STRUCTURED_CALL_OPTIONS,
    LlmBudget,
    LlmCallOptions,
    LlmFailureKind,
    LlmMessage,
    LlmTurn,
    TextDelta,
    ToolSchema,
    TurnComplete,
)
from app.llm.deepseek import DeepSeekLlmClient

# ---- R3 授权范围：换其中任何一项都须重新取得用户同意 -------------------------------------
AUTHORIZED_BASE_URL = "https://api.deepseek.com"
AUTHORIZED_MODEL = "deepseek-flash"
MAX_OUTPUT_TOKENS = 512
PER_CASE_TOKEN_BUDGET = 8_000
# 认证失败用例故意使用的无效 Key：不是密钥，上游会在计费之前拒绝它。
INVALID_KEY = "invalid-key-for-smoke-test"

REPORT_DIR = Path(__file__).resolve().parents[2] / "docs" / "history"

Protocol = Literal["openai", "anthropic"]
Thinking = Literal["disabled", "enabled"]
Status = Literal["PASS", "FAIL", "OBSERVED"]


class LookupArgs(BaseModel):
    product_name: str


LOOKUP_TOOL = ToolSchema(
    name="lookup_stock",
    description="按商品名称查询库存数量",
    parameters=LookupArgs.model_json_schema(),
)


class SmokeAnswer(BaseModel):
    answer: str
    confidence: float


@dataclass
class TurnUsage:
    tokens: int
    input_tokens: int
    output_tokens: int
    usage_known: bool
    cache_hit_tokens: int | None
    cache_miss_tokens: int | None


@dataclass
class Outcome:
    status: Status
    detail: str
    usage: list[TurnUsage] = field(default_factory=list)


class CallMeter:
    """逐条打印将要发出的调用，并守住总次数上限。"""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.made = 0

    def before_call(self, label: str) -> None:
        if self.made >= self.limit:
            raise RuntimeError(f"已达计划调用次数上限 {self.limit}，中止而不是多发一次")
        self.made += 1
        print(f"  → 即将发出第 {self.made}/{self.limit} 次调用：{label}", flush=True)


@dataclass(frozen=True)
class HttpOutcome:
    status: int
    error_message: str | None  # 只取错误响应里的 message 字段，截断；不含请求内容


class StatusRecordingTransport(httpx.AsyncBaseTransport):
    """包一层传输，记下每次请求的真实状态码；错误响应额外记下上游的错误说明。

    适配器把上游失败折叠成 ``LlmFailureKind``（400 与 500 都是 ``HTTP_OTHER``），
    冒烟要回答「是不是真的 400」，所以必须在传输层看原始状态码。
    """

    def __init__(self, inner: httpx.AsyncBaseTransport) -> None:
        self._inner = inner
        self.log: list[HttpOutcome] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        response = await self._inner.handle_async_request(request)
        if response.status_code < 400:
            self.log.append(HttpOutcome(response.status_code, None))
            return response
        body = await response.aread()
        await response.aclose()
        self.log.append(HttpOutcome(response.status_code, _error_message(body)))
        return httpx.Response(
            response.status_code, headers=response.headers, content=body, request=request
        )

    async def aclose(self) -> None:
        # 适配器每次调用都新建并关闭 AsyncClient，client 关闭会连带关 transport；
        # 这里被多次调用共享，所以不跟着关，由 run_cases 结束时 close_inner()。
        return None

    async def close_inner(self) -> None:
        await self._inner.aclose()


def _error_message(body: bytes) -> str | None:
    try:
        parsed = json.loads(body)
    except ValueError:
        return None
    error = parsed.get("error") if isinstance(parsed, dict) else None
    message = error.get("message") if isinstance(error, dict) else None
    if not isinstance(message, str):
        return None
    return " ".join(message.split()).replace("|", "/")[:160]


@dataclass
class Context:
    client: DeepSeekLlmClient
    bad_key_client: DeepSeekLlmClient
    meter: CallMeter
    thinking: Thinking
    settings: Settings
    transport: StatusRecordingTransport
    usage: list[TurnUsage] = field(default_factory=list)

    def record(self, turn: LlmTurn) -> None:
        self.usage.append(
            TurnUsage(
                turn.tokens,
                turn.input_tokens,
                turn.output_tokens,
                turn.usage_known,
                turn.cache_hit_tokens,
                turn.cache_miss_tokens,
            )
        )


async def _ask(
    ctx: Context,
    label: str,
    messages: list[LlmMessage],
    *,
    tools: list[ToolSchema] | None = None,
    options: LlmCallOptions | None = None,
    client: DeepSeekLlmClient | None = None,
) -> LlmTurn:
    ctx.meter.before_call(label)
    turn = await (client or ctx.client).converse(
        messages=messages,
        tools=tools or [],
        budget=LlmBudget(max_calls=1, max_tokens=PER_CASE_TOKEN_BUDGET),
        options=options or LlmCallOptions(thinking=ctx.thinking),
    )
    ctx.record(turn)
    return turn


async def _ask_stream(
    ctx: Context, label: str, messages: list[LlmMessage], *, tools: list[ToolSchema] | None = None
) -> tuple[str, LlmTurn]:
    ctx.meter.before_call(label)
    deltas: list[str] = []
    final: LlmTurn | None = None
    async for event in ctx.client.converse_stream(
        messages=messages,
        tools=tools or [],
        budget=LlmBudget(max_calls=1, max_tokens=PER_CASE_TOKEN_BUDGET),
        options=LlmCallOptions(thinking=ctx.thinking),
    ):
        if isinstance(event, TextDelta):
            deltas.append(event.text)
        elif isinstance(event, TurnComplete):
            final = event.turn
    if final is None:
        raise RuntimeError("流没有以 TurnComplete 结束")
    ctx.record(final)
    return "".join(deltas), final


def _degraded(turn: LlmTurn) -> Outcome | None:
    if turn.degraded:
        return Outcome("FAIL", f"上游降级：{turn.failure_kind}")
    return None


def _first_tool_call_is_valid(turn: LlmTurn) -> str | None:
    """返回 None 表示合法；否则是失败原因。参数经 Pydantic 校验（R4）。"""

    if turn.stop_reason != "TOOL_USE" or not turn.tool_calls:
        return f"未得到工具调用（stop_reason={turn.stop_reason}）"
    call = turn.tool_calls[0]
    if call.tool_name != LOOKUP_TOOL.name:
        return f"工具名不符：{call.tool_name}"
    try:
        LookupArgs.model_validate_json(call.arguments_json)
    except ValidationError:
        return "工具参数未通过 Pydantic 校验"
    return None


# --------------------------------------------------------------------------- 用例


async def case_plain(ctx: Context) -> Outcome:
    turn = await _ask(
        ctx, "普通问答", [LlmMessage(role="user", content="用一句话说明什么是库存周转率。")]
    )
    if (failed := _degraded(turn)) is not None:
        return failed
    if turn.stop_reason != "END_TURN" or not turn.text:
        return Outcome("FAIL", f"未得到正文（stop_reason={turn.stop_reason}）")
    return Outcome("PASS", f"usage_known={turn.usage_known}")


async def case_structured(ctx: Context) -> Outcome:
    turn = await _ask(
        ctx,
        "结构化 JSON 输出",
        [
            LlmMessage(
                role="system",
                content=(
                    '只输出一个 JSON 对象，形如 {"answer": "<一句话>", '
                    '"confidence": <0 到 1 的数>}，不要输出任何其他文字。'
                ),
            ),
            LlmMessage(role="user", content="库存周转率越高越好吗？"),
        ],
        options=STRUCTURED_CALL_OPTIONS,
    )
    if (failed := _degraded(turn)) is not None:
        return failed
    try:
        SmokeAnswer.model_validate_json(turn.text or "")
    except ValidationError:
        # 如实记录：这是「该协议不靠 response_format 时输出是否是纯 JSON」的观测事实。
        return Outcome("FAIL", "输出不是可被 Pydantic 校验的纯 JSON")
    return Outcome("PASS", "输出通过 Pydantic 校验")


async def case_single_tool(ctx: Context) -> Outcome:
    turn = await _ask(
        ctx,
        "单工具调用",
        [LlmMessage(role="user", content="请查询商品「保温壶」的库存。")],
        tools=[LOOKUP_TOOL],
    )
    if (failed := _degraded(turn)) is not None:
        return failed
    problem = _first_tool_call_is_valid(turn)
    return Outcome("FAIL", problem) if problem else Outcome("PASS", "工具调用映射正确")


async def case_parallel_tools(ctx: Context) -> Outcome:
    turn = await _ask(
        ctx,
        "多工具并行",
        [LlmMessage(role="user", content="请同时查询「保温壶」和「马克杯」两个商品的库存。")],
        tools=[LOOKUP_TOOL],
    )
    if (failed := _degraded(turn)) is not None:
        return failed
    if turn.stop_reason != "TOOL_USE":
        return Outcome("FAIL", f"未得到工具调用（stop_reason={turn.stop_reason}）")
    if len(turn.tool_calls) < 2:
        return Outcome("FAIL", f"一次只返回了 {len(turn.tool_calls)} 个调用，没有并行")
    return Outcome("PASS", f"一次返回 {len(turn.tool_calls)} 个调用")


async def case_multi_round(ctx: Context) -> Outcome:
    """第 1 轮拿到工具调用 → 回填工具结果与推理内容 → 第 2 轮成功。"""

    messages = [LlmMessage(role="user", content="请查询商品「保温壶」的库存。")]
    first = await _ask(ctx, "多轮工具历史 · 第 1 轮", messages, tools=[LOOKUP_TOOL])
    if (failed := _degraded(first)) is not None:
        return failed
    if (problem := _first_tool_call_is_valid(first)) is not None:
        return Outcome("FAIL", f"第 1 轮：{problem}")
    messages.append(
        LlmMessage(
            role="assistant",
            content=first.text or "",
            tool_calls=first.tool_calls,
            reasoning=first.reasoning,
        )
    )
    messages.extend(
        LlmMessage(
            role="tool",
            content='{"product_name":"保温壶","stock":42}',
            tool_call_id=call.call_id,
        )
        for call in first.tool_calls
    )
    second = await _ask(ctx, "多轮工具历史 · 第 2 轮", messages, tools=[LOOKUP_TOOL])
    if (failed := _degraded(second)) is not None:
        return Outcome("FAIL", f"第 2 轮被拒或降级：{second.failure_kind}")
    replayed = "是" if first.reasoning is not None else "否（第 1 轮没有推理内容）"
    if second.stop_reason != "END_TURN":
        return Outcome("FAIL", f"第 2 轮 stop_reason={second.stop_reason}；推理回放：{replayed}")
    return Outcome("PASS", f"第 2 轮成功；推理回放：{replayed}")


async def case_stream_text(ctx: Context) -> Outcome:
    joined, final = await _ask_stream(
        ctx, "流式文本", [LlmMessage(role="user", content="用两句话介绍库存周转率。")]
    )
    if (failed := _degraded(final)) is not None:
        return failed
    if joined != (final.text or ""):
        return Outcome("FAIL", "增量拼接与最终文本不一致")
    return Outcome("PASS", f"增量拼接与最终文本一致；流式返回用量：{final.usage_known}")


async def case_stream_tool(ctx: Context) -> Outcome:
    _, final = await _ask_stream(
        ctx,
        "流式工具调用",
        [LlmMessage(role="user", content="请查询商品「保温壶」的库存。")],
        tools=[LOOKUP_TOOL],
    )
    if (failed := _degraded(final)) is not None:
        return failed
    problem = _first_tool_call_is_valid(final)
    if problem:
        return Outcome("FAIL", problem)
    return Outcome("PASS", f"参数分片拼接后可解析；流式返回用量：{final.usage_known}")


def _cache_prefix() -> str:
    # 确定性的长前缀，约 1,400 token（远超缓存命中所需的 1,024）。
    return "\n".join(
        f"Rule {i}: keep every answer factual, concise and consistent." for i in range(1, 121)
    )


async def case_cache(ctx: Context) -> Outcome:
    """两次请求共享同一段长前缀，记录第二次的缓存字段原值。"""

    system = LlmMessage(role="system", content=_cache_prefix())
    first = await _ask(
        ctx,
        "缓存计量 · 第 1 次（写入前缀）",
        [system, LlmMessage(role="user", content="回答：1+1")],
    )
    if (failed := _degraded(first)) is not None:
        return failed
    await asyncio.sleep(5)  # 上游缓存是尽力而为，构建需要片刻
    second = await _ask(
        ctx,
        "缓存计量 · 第 2 次（读取前缀）",
        [system, LlmMessage(role="user", content="回答：2+2")],
    )
    if (failed := _degraded(second)) is not None:
        return failed
    if second.cache_hit_tokens is None and second.cache_miss_tokens is None:
        return Outcome("OBSERVED", "上游未上报缓存字段（记为『未上报』，不是 0）")
    return Outcome(
        "PASS", f"上游上报了缓存字段：hit={second.cache_hit_tokens} miss={second.cache_miss_tokens}"
    )


async def case_auth_failure(ctx: Context) -> Outcome:
    turn = await _ask(
        ctx,
        "认证失败（故意使用无效 Key，上游在计费前拒绝）",
        [LlmMessage(role="user", content="你好")],
        client=ctx.bad_key_client,
    )
    if turn.failure_kind in {LlmFailureKind.HTTP_401, LlmFailureKind.HTTP_403}:
        return Outcome("PASS", f"映射为 {turn.failure_kind}")
    return Outcome("FAIL", f"未映射为认证失败：failure_kind={turn.failure_kind}")


async def case_invalid_request(ctx: Context) -> Outcome:
    """发送 tool_call_id 不存在的工具结果消息，期望被拒（400）。

    该期望依据官方文档推断。若上游没有报错，如实记为 FAIL 并写明，
    **不得**把「没报错」记成「错误分类可映射」；届时应换一个确定会被拒绝的受控请求。
    """

    turn = await _ask(
        ctx,
        "非法请求（不存在的 tool_call_id）",
        [
            LlmMessage(role="user", content="你好"),
            LlmMessage(role="tool", content="{}", tool_call_id="call_does_not_exist"),
        ],
    )
    if turn.failure_kind is LlmFailureKind.HTTP_OTHER:
        return Outcome("PASS", "上游拒绝，映射为 HTTP_OTHER")
    if not turn.degraded:
        return Outcome("FAIL", "上游没有拒绝这条非法请求：该用例的期望不成立，需换一个受控请求")
    return Outcome("FAIL", f"被降级但归类不是 HTTP_OTHER：{turn.failure_kind}")


@dataclass(frozen=True)
class Case:
    number: int
    title: str
    calls: int
    run: Callable[[Context], Awaitable[Outcome]]


ALL_CASES = (
    Case(1, "普通问答", 1, case_plain),
    Case(2, "结构化 JSON 输出", 1, case_structured),
    Case(3, "单工具调用", 1, case_single_tool),
    Case(4, "多工具并行", 1, case_parallel_tools),
    Case(5, "多轮工具历史", 2, case_multi_round),
    Case(6, "流式文本", 1, case_stream_text),
    Case(7, "流式工具调用", 1, case_stream_tool),
    Case(8, "缓存计量", 2, case_cache),
    Case(9, "错误分类：认证失败", 1, case_auth_failure),
    Case(10, "错误分类：非法请求", 1, case_invalid_request),
)


# ------------------------------------------------------------ 扩展用例（suite=extended）
#
# 回答基础冒烟之后仍只有文档依据的三件事；全部在思考模式 enabled 下跑（用例 15 除外）。


def _last_http(ctx: Context) -> HttpOutcome | None:
    return ctx.transport.log[-1] if ctx.transport.log else None


def _reasoning_note(turn: LlmTurn) -> str:
    return "捕获到推理内容" if turn.reasoning is not None else "未捕获推理内容"


async def case_reasoning_omitted(ctx: Context) -> Outcome:
    """第 1 轮拿到工具调用与推理内容；第 2 轮**故意不回放推理内容**，看上游是否真的拒绝。

    文档说思考模式下带 tools 的多轮请求缺了推理内容会 400。这里记录真实状态码与错误说明；
    上游接受了请求也如实记为 OBSERVED，不改写成通过。
    """

    messages = [LlmMessage(role="user", content="请查询商品「保温壶」的库存。")]
    first = await _ask(ctx, "省略推理内容 · 第 1 轮", messages, tools=[LOOKUP_TOOL])
    if (failed := _degraded(first)) is not None:
        return failed
    if (problem := _first_tool_call_is_valid(first)) is not None:
        return Outcome("FAIL", f"第 1 轮：{problem}")
    if first.reasoning is None:
        return Outcome("OBSERVED", "第 1 轮没有推理内容，无从测试「省略」；只发出了 1 次调用")
    messages.append(
        LlmMessage(role="assistant", content=first.text or "", tool_calls=first.tool_calls)
    )  # reasoning 故意不带
    messages.extend(
        LlmMessage(role="tool", content='{"stock":42}', tool_call_id=call.call_id)
        for call in first.tool_calls
    )
    second = await _ask(ctx, "省略推理内容 · 第 2 轮（不回放推理）", messages, tools=[LOOKUP_TOOL])
    http = _last_http(ctx)
    status = http.status if http else "未知"
    message = (http.error_message if http else None) or "无错误说明"
    if second.degraded:
        return Outcome(
            "PASS" if status == 400 else "OBSERVED",
            f"上游拒绝：HTTP {status}，{second.failure_kind}；错误说明：{message}",
        )
    return Outcome(
        "OBSERVED",
        f"上游**接受**了省略推理内容的请求（HTTP {status}，stop_reason={second.stop_reason}）："
        "与文档「会 400」不符，回放仍保留以防上游收紧",
    )


async def case_thinking_stream_text(ctx: Context) -> Outcome:
    joined, final = await _ask_stream(
        ctx, "思考模式 · 流式文本", [LlmMessage(role="user", content="用两句话介绍库存周转率。")]
    )
    if (failed := _degraded(final)) is not None:
        return failed
    if final.stop_reason != "END_TURN":
        return Outcome("FAIL", f"stop_reason={final.stop_reason}（推理可能耗尽了输出上限）")
    if joined != (final.text or ""):
        return Outcome("FAIL", "增量拼接与最终文本不一致（推理内容可能混进了正文）")
    return Outcome(
        "PASS", f"增量只含正文；{_reasoning_note(final)}；流式返回用量：{final.usage_known}"
    )


async def case_thinking_stream_tool(ctx: Context) -> Outcome:
    joined, final = await _ask_stream(
        ctx,
        "思考模式 · 流式工具调用",
        [LlmMessage(role="user", content="请查询商品「保温壶」的库存。")],
        tools=[LOOKUP_TOOL],
    )
    if (failed := _degraded(final)) is not None:
        return failed
    if (problem := _first_tool_call_is_valid(final)) is not None:
        return Outcome("FAIL", problem)
    return Outcome(
        "PASS",
        f"参数分片拼接后可解析；{_reasoning_note(final)}；正文增量 {len(joined)} 字；"
        f"流式返回用量：{final.usage_known}",
    )


async def case_thinking_parallel_tools(ctx: Context) -> Outcome:
    turn = await _ask(
        ctx,
        "思考模式 · 多工具并行",
        [LlmMessage(role="user", content="请同时查询「保温壶」和「马克杯」两个商品的库存。")],
        tools=[LOOKUP_TOOL],
    )
    if (failed := _degraded(turn)) is not None:
        return failed
    if turn.stop_reason != "TOOL_USE":
        return Outcome("FAIL", f"未得到工具调用（stop_reason={turn.stop_reason}）")
    for call in turn.tool_calls:
        try:
            LookupArgs.model_validate_json(call.arguments_json)
        except ValidationError:
            return Outcome("FAIL", f"调用 {call.call_id} 的参数未通过 Pydantic 校验")
    if len(turn.tool_calls) < 2:
        return Outcome("OBSERVED", f"只返回 {len(turn.tool_calls)} 个调用；{_reasoning_note(turn)}")
    return Outcome("PASS", f"一次返回 {len(turn.tool_calls)} 个调用；{_reasoning_note(turn)}")


async def case_anthropic_raw_stream_usage(ctx: Context) -> Outcome:
    """直接读 Anthropic 流式原始事件，记下每个带 usage 的事件及其 usage 对象（只有数字）。

    适配器按 message_start / message_delta 合并 usage，那是按标准形状写的 mock；这里看真实形状。
    两次请求共享同一段长前缀，第 2 次才会出现缓存命中。
    """

    observed: list[str] = []
    async with httpx.AsyncClient(
        base_url=ctx.settings.llm_base_url, timeout=60, transport=ctx.transport
    ) as client:
        for index, question in enumerate(("回答：5+5", "回答：6+6"), start=1):
            ctx.meter.before_call(f"Anthropic 原始流 usage · 第 {index} 次")
            events: list[str] = []
            async with client.stream(
                "POST",
                "/anthropic/v1/messages",
                headers={
                    "x-api-key": str(ctx.settings.llm_api_key),
                    "anthropic-version": "2023-06-01",
                },
                json={
                    "model": ctx.settings.llm_model,
                    "max_tokens": 64,
                    "stream": True,
                    "thinking": {"type": "disabled"},
                    "system": _cache_prefix(),
                    "messages": [{"role": "user", "content": question}],
                },
            ) as response:
                if response.status_code >= 400:
                    return Outcome("FAIL", f"第 {index} 次 HTTP {response.status_code}")
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    event = json.loads(line[5:])
                    usage = event.get("usage")
                    if usage is None and isinstance(event.get("message"), dict):
                        usage = event["message"].get("usage")
                    if usage is not None:
                        events.append(
                            f"{event.get('type')}="
                            + json.dumps(usage, ensure_ascii=False, sort_keys=True)
                        )
            observed.append(f"第 {index} 次：" + "；".join(events or ["无 usage 事件"]))
            await asyncio.sleep(3)
    return Outcome("OBSERVED", " / ".join(observed).replace("|", "/"))


EXTENDED_CASES = (
    Case(11, "思考模式 · 省略推理内容是否被拒", 2, case_reasoning_omitted),
    Case(12, "思考模式 · 流式文本", 1, case_thinking_stream_text),
    Case(13, "思考模式 · 流式工具调用", 1, case_thinking_stream_tool),
    Case(14, "思考模式 · 多工具并行", 1, case_thinking_parallel_tools),
    Case(15, "Anthropic 流式原始 usage 事件", 2, case_anthropic_raw_stream_usage),
)

Suite = Literal["basic", "extended"]
# 思考模式会先把输出额度花在推理上，512 容易被推理耗尽，扩展用例放宽到 1024。
EXTENDED_MAX_OUTPUT_TOKENS = 1024


def plan_for(
    thinking: Thinking, suite: Suite = "basic", protocol: Protocol = "openai"
) -> tuple[Case, ...]:
    """basic 下思考模式开启只跑多轮工具历史；extended 固定思考开启，用例 15 只对 anthropic 跑。"""

    if suite == "extended":
        return tuple(c for c in EXTENDED_CASES if c.number != 15 or protocol == "anthropic")
    if thinking == "enabled":
        return tuple(case for case in ALL_CASES if case.number == 5)
    return ALL_CASES


# --------------------------------------------------------------------------- 执行与报告


async def run_cases(
    settings: Settings,
    cases: tuple[Case, ...],
    *,
    thinking: Thinking,
    transport: httpx.AsyncBaseTransport | None = None,
) -> tuple[list[tuple[Case, Outcome]], int]:
    """返回用例结果与**实际发出的 HTTP 请求数**（以传输层记录为准，而不是计划数）。"""

    meter = CallMeter(sum(case.calls for case in cases))
    recording = StatusRecordingTransport(transport or httpx.AsyncHTTPTransport())
    ctx = Context(
        client=DeepSeekLlmClient(settings, transport=recording),
        bad_key_client=DeepSeekLlmClient(
            settings.model_copy(update={"llm_api_key": INVALID_KEY}), transport=recording
        ),
        meter=meter,
        thinking=thinking,
        settings=settings,
        transport=recording,
    )
    results: list[tuple[Case, Outcome]] = []
    try:
        for case in cases:
            print(f"用例 {case.number} · {case.title}（{case.calls} 次调用）", flush=True)
            ctx.usage = []
            try:
                outcome = await case.run(ctx)
            except Exception as error:  # 单个用例失败不应中断其余用例
                outcome = Outcome("FAIL", f"用例抛出 {type(error).__name__}: {error}")
            outcome.usage = list(ctx.usage)
            results.append((case, outcome))
            print(f"  = {outcome.status}：{outcome.detail}", flush=True)
    finally:
        await recording.close_inner()
    return results, len(recording.log)


def _cache_cell(value: int | None) -> str:
    return "未上报" if value is None else str(value)


def render_report(
    results: list[tuple[Case, Outcome]],
    *,
    protocol: Protocol,
    thinking: Thinking,
    model: str,
    planned_calls: int,
    made_calls: int,
    when: datetime,
    max_output_tokens: int = MAX_OUTPUT_TOKENS,
    suite: Suite = "basic",
) -> str:
    lines = [
        f"## {when:%Y-%m-%d %H:%M:%S} · protocol={protocol} · thinking={thinking} · model={model}"
        + (" · suite=extended" if suite == "extended" else ""),
        "",
        f"- 计划调用次数 / 实际发出：{planned_calls} / {made_calls}",
        f"- 单次输出上限：{max_output_tokens} token",
        f"- 用例结果：PASS {sum(o.status == 'PASS' for _, o in results)}"
        f" · OBSERVED {sum(o.status == 'OBSERVED' for _, o in results)}"
        f" · FAIL {sum(o.status == 'FAIL' for _, o in results)}",
        "",
        "| # | 用例 | 结果 | token（总/入/出） | 缓存 hit/miss（原值） | 说明 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for case, outcome in results:
        tokens = " ; ".join(f"{u.tokens}/{u.input_tokens}/{u.output_tokens}" for u in outcome.usage)
        cache = " ; ".join(
            f"{_cache_cell(u.cache_hit_tokens)}/{_cache_cell(u.cache_miss_tokens)}"
            for u in outcome.usage
        )
        lines.append(
            f"| {case.number} | {case.title} | {outcome.status} | {tokens or '—'} | "
            f"{cache or '—'} | {outcome.detail} |"
        )
    total = sum(u.tokens for _, o in results for u in o.usage)
    lines += ["", f"- 已知总 token：{total}（`usage_known=False` 的调用计为 0，可能低估）", ""]
    return "\n".join(lines)


def append_report(text: str, when: datetime) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORT_DIR / f"llm-smoke-{when:%Y-%m-%d}.md"
    if not path.exists():
        path.write_text(f"# DeepSeek 双协议真实冒烟记录 · {when:%Y-%m-%d}\n\n", encoding="utf-8")
    with path.open("a", encoding="utf-8") as handle:
        handle.write(text + "\n")
    return path


def build_settings(
    protocol: Protocol, thinking: Thinking, max_output_tokens: int = MAX_OUTPUT_TOKENS
) -> Settings:
    # 冒烟不连数据库，这两个必填项只是占位；LLM 相关取值仍读环境变量。
    return Settings(
        database_url="postgresql+psycopg://smoke:smoke@localhost/smoke",
        frontend_origin="http://localhost:5173",
        llm_protocol=protocol,
        llm_thinking=thinking,
        llm_max_output_tokens_per_call=max_output_tokens,
    )


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="DeepSeek 双协议真实冒烟（会产生真实费用）")
    parser.add_argument("--protocol", choices=["openai", "anthropic"], required=True)
    parser.add_argument(
        "--thinking",
        choices=["disabled", "enabled"],
        default="disabled",
        help="enabled 是另行授权的加跑，只跑多轮工具历史（--suite extended 时固定为 enabled）",
    )
    parser.add_argument(
        "--suite",
        choices=["basic", "extended"],
        default="basic",
        help="extended：省略推理是否被拒、思考模式流式与并行、Anthropic 原始流 usage（另行授权）",
    )
    parser.add_argument("--yes", action="store_true", help="确认发出真实请求；缺省只展示计划")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    protocol: Protocol = args.protocol
    suite: Suite = args.suite
    thinking: Thinking = "enabled" if suite == "extended" else args.thinking
    max_output = EXTENDED_MAX_OUTPUT_TOKENS if suite == "extended" else MAX_OUTPUT_TOKENS
    cases = plan_for(thinking, suite, protocol)
    planned = sum(case.calls for case in cases)
    settings = build_settings(protocol, thinking, max_output)

    print(f"接口：DeepSeek {protocol} 兼容协议（根地址 {settings.llm_base_url}）")
    print(f"模型：{settings.llm_model}；思考模式：{thinking}；用例集：{suite}")
    print(f"计划：{len(cases)} 个用例，最多 {planned} 次调用；单次输出上限 {max_output} token")
    for case in cases:
        print(f"  - 用例 {case.number}：{case.title}（{case.calls} 次）")
    if thinking == "enabled":
        print("注意：思考模式 enabled 的加跑需要用户另行明确同意。")
    if not args.yes:
        print("\n未加 --yes：以上只是计划，没有发出任何请求。")
        return 0

    if settings.llm_base_url.rstrip("/") != AUTHORIZED_BASE_URL:
        print(f"拒绝运行：LLM_BASE_URL 必须是 {AUTHORIZED_BASE_URL}（授权范围）", file=sys.stderr)
        return 2
    if settings.llm_model != AUTHORIZED_MODEL:
        print(f"拒绝运行：LLM_MODEL 必须是 {AUTHORIZED_MODEL}（授权范围）", file=sys.stderr)
        return 2
    if not settings.llm_api_key:
        print("拒绝运行：未配置 LLM_API_KEY（本脚本没有任何硬编码回退）", file=sys.stderr)
        return 2

    when = datetime.now()  # 报告里的本地时间戳，供人阅读
    results, made = asyncio.run(run_cases(settings, cases, thinking=thinking))
    report = render_report(
        results,
        protocol=protocol,
        thinking=thinking,
        model=settings.llm_model,
        planned_calls=planned,
        made_calls=made,
        when=when,
        max_output_tokens=max_output,
        suite=suite,
    )
    path = append_report(report, when)
    print(f"\n结果已写入 {path}")
    return 1 if any(outcome.status == "FAIL" for _, outcome in results) else 0


if __name__ == "__main__":
    sys.exit(main())
