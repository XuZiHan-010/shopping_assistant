"""两个协议适配器共用的预算、失败分类、用量解析与 SSE 行解析。

只放两种协议**完全相同**的逻辑；凡是随协议而异的（请求体、响应形状、用量字段）
留在各自的适配器里。
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from typing import Literal

import httpx

from app.core.config import Settings
from app.llm.client import (
    LlmBudget,
    LlmBudgetExceededError,
    LlmCallOptions,
    LlmFailureKind,
    LlmProtocolName,
    LlmTurn,
    LlmUnavailableError,
)

logger = logging.getLogger(__name__)


class StreamTruncatedError(RuntimeError):
    """流在收到结束标记前就断了。"""


class StreamErrorEvent(RuntimeError):
    """上游在流中途发来了显式的错误事件（如 ``overloaded_error``）。"""


@dataclass(frozen=True)
class TokenUsage:
    tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    known: bool = False
    # None = 提供方未上报，不等于 0。
    cache_hit_tokens: int | None = None
    cache_miss_tokens: int | None = None


def require_configured(settings: Settings) -> None:
    if not settings.llm_api_key:
        raise LlmUnavailableError("未配置 LLM_API_KEY")


def reserve_call(settings: Settings, budget: LlmBudget) -> int:
    """先扣后发：扣一次调用配额，并返回本次请求的 ``max_tokens``。

    事后记账挡不住一次超支：预算耗尽时这次调用照样要付钱。因此先在本地拦截，
    再把剩余额度作为 ``max_tokens`` 随请求发出，让上限对上游同样生效。
    ``max_tokens`` 限制的是生成部分，而预算按总 token 记，所以这是上界而非精确等式。
    """

    budget.charge_call()
    remaining = budget.max_tokens - budget.tokens
    if remaining <= 0:
        raise LlmBudgetExceededError(f"单请求 LLM token 已达上限 {budget.max_tokens}")
    return min(remaining, settings.llm_max_output_tokens_per_call)


def effective_thinking(
    settings: Settings, options: LlmCallOptions
) -> Literal["enabled", "disabled"]:
    """``LLM_THINKING`` 是上限：单次调用只能把它收紧，不能越过它放开。"""

    if settings.llm_thinking == "enabled" and options.thinking == "enabled":
        return "enabled"
    return "disabled"


def classify_upstream_error(error: Exception) -> tuple[LlmFailureKind, int | None]:
    """把上游异常归入既有的 ``LlmFailureKind``，并带回 HTTP 状态码（若有）。"""

    if isinstance(error, httpx.HTTPStatusError):
        status = error.response.status_code
        kind = {
            401: LlmFailureKind.HTTP_401,
            403: LlmFailureKind.HTTP_403,
            429: LlmFailureKind.HTTP_429,
        }.get(status, LlmFailureKind.HTTP_OTHER)
        return kind, status
    if isinstance(error, httpx.TimeoutException):
        return LlmFailureKind.TIMEOUT, None
    if isinstance(error, httpx.NetworkError):
        return LlmFailureKind.NETWORK, None
    if isinstance(error, ValueError):
        return LlmFailureKind.BAD_PAYLOAD, None
    if isinstance(error, StreamErrorEvent):
        return LlmFailureKind.HTTP_OTHER, None
    # 其余 ``httpx.HTTPError``（如对端提前关闭连接）与 ``StreamTruncatedError`` 都是传输层故障。
    return LlmFailureKind.NETWORK, None


def failed_turn(
    settings: Settings,
    protocol: LlmProtocolName,
    kind: LlmFailureKind,
    status_code: int | None = None,
    *,
    text: str | None = None,
) -> LlmTurn:
    """上游失败的降级回合；``text`` 只用于流中途断开时保留已经展示给用户的部分。"""

    logger.warning(
        "llm_upstream_failed",
        extra={
            "failure_kind": kind.value,
            "status_code": status_code,
            "model": settings.llm_model,
            "protocol": protocol,
        },
    )
    return LlmTurn(
        text=text,
        tool_calls=[],
        stop_reason="ERROR",
        tokens=0,
        degraded=True,
        failure_kind=kind,
        # 认证失败被上游拒绝在计费之前，「零消耗」是已知事实。
        usage_known=kind in {LlmFailureKind.HTTP_401, LlmFailureKind.HTTP_403},
    )


def usage_int(usage: Mapping[object, object], key: str) -> int:
    """必填用量字段：缺省按 0，形状不对即视为响应损坏。"""

    value = usage.get(key, 0)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"响应 usage.{key} 无效")
    return value


def optional_usage_int(usage: Mapping[object, object], key: str) -> int | None:
    """附带的用量字段（如缓存计量）：没有或不合法都记 None，不连累整次成功的响应。"""

    value = usage.get(key)
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None


async def iter_sse_data(response: httpx.Response) -> AsyncIterator[str]:
    """逐条产出 SSE 的 ``data:`` 载荷；``event:`` 行与注释行忽略（载荷里已带 type）。"""

    async for line in response.aiter_lines():
        if line.startswith("data:"):
            data = line[5:].strip()
            if data:
                yield data
