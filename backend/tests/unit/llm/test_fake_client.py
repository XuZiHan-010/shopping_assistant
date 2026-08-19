"""Fake LLM 与单请求预算行为。"""

from __future__ import annotations

import pytest

from app.llm.client import (
    STRUCTURED_CALL_OPTIONS,
    LlmBudget,
    LlmBudgetExceededError,
    LlmUnavailableError,
)
from app.llm.fake import FakeLlmClient


def _budget() -> LlmBudget:
    return LlmBudget(max_calls=3, max_tokens=1_000)


@pytest.mark.asyncio
async def test_normal_fake_client_returns_the_configured_response() -> None:
    """若替身不能返回预置文本，意图服务测试无法覆盖确定性路径。"""

    result = await FakeLlmClient(responses=['{"answer_mode": "METRIC"}']).complete(
        system="s", user="u", fallback="fb", budget=_budget()
    )

    assert result.text == '{"answer_mode": "METRIC"}'
    assert result.degraded is False


@pytest.mark.asyncio
async def test_fake_client_records_call_options() -> None:
    client = FakeLlmClient(responses=["ok"])

    await client.complete(
        system="s",
        user="u",
        fallback="fb",
        budget=_budget(),
        options=STRUCTURED_CALL_OPTIONS,
    )

    assert client.call_options == [STRUCTURED_CALL_OPTIONS]


@pytest.mark.asyncio
async def test_invalid_json_is_returned_for_the_caller_to_validate() -> None:
    """吞掉非法 JSON 会使调用方的重试逻辑得不到覆盖。"""

    result = await FakeLlmClient(behaviour="invalid_json").complete(
        system="s", user="u", fallback="fb", budget=_budget()
    )

    assert result.text == "这不是 JSON"
    assert result.degraded is False


@pytest.mark.asyncio
@pytest.mark.parametrize("behaviour", ["timeout", "empty"])
async def test_unusable_output_falls_back_with_visible_degradation(behaviour: str) -> None:
    """超时或空响应若隐藏降级，用户会误以为内容来自真实模型。"""

    result = await FakeLlmClient(behaviour=behaviour).complete(  # type: ignore[arg-type]
        system="s", user="u", fallback="兜底回答", budget=_budget()
    )

    assert result.text == "兜底回答"
    assert result.degraded is True


@pytest.mark.asyncio
async def test_unconfigured_client_raises_an_explicit_unavailable_error() -> None:
    """未配置客户端若静默调用，生产环境可能在没有密钥时异常失败。"""

    client = FakeLlmClient(configured=False)

    assert client.is_configured() is False
    with pytest.raises(LlmUnavailableError):
        await client.complete(system="s", user="u", fallback="fb", budget=_budget())


@pytest.mark.asyncio
async def test_call_budget_rejects_a_call_beyond_the_limit() -> None:
    """忽略调用次数预算会使有限重试突破单请求成本上限。"""

    client = FakeLlmClient(responses=["ok"] * 5)
    budget = LlmBudget(max_calls=2, max_tokens=1_000)
    await client.complete(system="s", user="u", fallback="fb", budget=budget)
    await client.complete(system="s", user="u", fallback="fb", budget=budget)

    with pytest.raises(LlmBudgetExceededError):
        await client.complete(system="s", user="u", fallback="fb", budget=budget)


def test_token_budget_rejects_a_charge_beyond_the_limit() -> None:
    """忽略 token 预算会绕过成本熔断。"""

    budget = LlmBudget(max_calls=10, max_tokens=100)
    budget.charge(60)

    with pytest.raises(LlmBudgetExceededError):
        budget.charge(60)
