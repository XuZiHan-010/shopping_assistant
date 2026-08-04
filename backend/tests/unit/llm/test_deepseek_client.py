from __future__ import annotations

import json

import httpx
import pytest

from app.core.config import Settings
from app.llm.client import LlmBudget, LlmBudgetExceededError, LlmUnavailableError
from app.llm.deepseek import DeepSeekLlmClient


def _settings(key: str | None) -> Settings:
    return Settings(
        database_url="postgresql+psycopg://u:p@localhost/db",
        frontend_origin="http://localhost:5173",
        llm_api_key=key,
    )


def _budget() -> LlmBudget:
    return LlmBudget(3, 1000)


def test_unconfigured_is_false() -> None:
    assert not DeepSeekLlmClient(_settings(None)).is_configured()


@pytest.mark.asyncio
async def test_unconfigured_raises() -> None:
    with pytest.raises(LlmUnavailableError):
        await DeepSeekLlmClient(_settings(None)).complete(
            system="s", user="u", fallback="f", budget=_budget()
        )


@pytest.mark.asyncio
async def test_mock_transport_uses_openai_path_and_bearer() -> None:
    seen: dict[str, str] = {}

    def handler(r: httpx.Request) -> httpx.Response:
        seen.update(url=str(r.url), auth=r.headers["authorization"])
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "回答"}}], "usage": {"total_tokens": 42}}
        )

    result = await DeepSeekLlmClient(
        _settings("key"), transport=httpx.MockTransport(handler)
    ).complete(system="s", user="u", fallback="f", budget=_budget())
    assert (result.text, result.tokens, result.degraded) == ("回答", 42, False)
    assert seen["url"].endswith("/chat/completions")
    assert seen["auth"] == "Bearer key"


@pytest.mark.asyncio
async def test_request_caps_max_tokens_at_the_remaining_budget() -> None:
    """只在事后记账无法阻止单次调用超支：上限必须随请求发出去。"""

    seen: dict[str, object] = {}

    def handler(r: httpx.Request) -> httpx.Response:
        seen.update(json.loads(r.content))
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "回答"}}], "usage": {"total_tokens": 10}}
        )

    budget = LlmBudget(3, 1000)
    budget.charge(400)

    await DeepSeekLlmClient(_settings("key"), transport=httpx.MockTransport(handler)).complete(
        system="s", user="u", fallback="f", budget=budget
    )

    assert seen["max_tokens"] == 600


@pytest.mark.asyncio
async def test_exhausted_token_budget_does_not_reach_the_network() -> None:
    """预算已耗尽仍发请求会产生一次无论如何都要付钱的调用。"""

    def handler(r: httpx.Request) -> httpx.Response:  # pragma: no cover - 不应被调用
        raise AssertionError("预算耗尽后不应发起请求")

    budget = LlmBudget(3, 1000)
    budget.charge(1000)

    with pytest.raises(LlmBudgetExceededError):
        await DeepSeekLlmClient(_settings("key"), transport=httpx.MockTransport(handler)).complete(
            system="s", user="u", fallback="f", budget=budget
        )
