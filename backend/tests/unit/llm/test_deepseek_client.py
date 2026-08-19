from __future__ import annotations

import json

import httpx
import pytest

from app.core.config import Settings
from app.llm.client import (
    STRUCTURED_CALL_OPTIONS,
    LlmBudget,
    LlmBudgetExceededError,
    LlmFailureKind,
    LlmUnavailableError,
)
from app.llm.deepseek import DeepSeekLlmClient


def _settings(key: str | None) -> Settings:
    return Settings(
        database_url="postgresql+psycopg://u:p@localhost/db",
        frontend_origin="http://localhost:5173",
        llm_api_key=key,
    )


def _budget() -> LlmBudget:
    return LlmBudget(3, 1000)


def _ok_payload(content: str, usage: dict[str, int]) -> dict[str, object]:
    return {"choices": [{"message": {"content": content}}], "usage": usage}


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
async def test_structured_call_disables_thinking_and_requests_json() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(200, json=_ok_payload("{}", {"total_tokens": 1}))

    await DeepSeekLlmClient(_settings("key"), transport=httpx.MockTransport(handler)).complete(
        system="s", user="u", fallback="{}", budget=_budget(), options=STRUCTURED_CALL_OPTIONS
    )

    assert seen["thinking"] == {"type": "disabled"}
    assert seen["response_format"] == {"type": "json_object"}


@pytest.mark.asyncio
async def test_regular_call_and_disabled_flag_do_not_send_structured_provider_fields() -> None:
    seen: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, json=_ok_payload("{}", {"total_tokens": 1}))

    client = DeepSeekLlmClient(_settings("key"), transport=httpx.MockTransport(handler))
    await client.complete(system="s", user="u", fallback="{}", budget=_budget())
    disabled = Settings(
        database_url="postgresql+psycopg://u:p@localhost/db",
        frontend_origin="http://localhost:5173",
        llm_api_key="key",
        llm_disable_thinking_for_structured=False,
    )
    await DeepSeekLlmClient(disabled, transport=httpx.MockTransport(handler)).complete(
        system="s", user="u", fallback="{}", budget=_budget(), options=STRUCTURED_CALL_OPTIONS
    )

    assert all("thinking" not in payload and "response_format" not in payload for payload in seen)


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


@pytest.mark.asyncio
async def test_upstream_401_is_recorded_and_logged_not_silently_swallowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """401 被压成「模型没理解问题」会让排查完全跑偏。"""

    logged: list[tuple[str, dict[str, object]]] = []

    def record(event: str, **kwargs: object) -> None:
        logged.append((event, kwargs))

    monkeypatch.setattr("app.llm.deepseek.logger.warning", record)
    transport = httpx.MockTransport(lambda request: httpx.Response(401, json={"error": "bad key"}))
    client = DeepSeekLlmClient(_settings("key"), transport=transport)

    result = await client.complete(
        system="system secret", user="user secret", fallback="{}", budget=LlmBudget(2, 1000)
    )

    assert result.degraded is True
    assert result.failure_kind is LlmFailureKind.HTTP_401
    assert logged == [
        (
            "llm_upstream_failed",
            {
                "extra": {
                    "failure_kind": "HTTP_401",
                    "status_code": 401,
                    "model": "deepseek-v4-flash",
                }
            },
        )
    ]


@pytest.mark.asyncio
async def test_unlisted_http_status_uses_controlled_other_kind() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(503, json={"error": "down"}))

    result = await DeepSeekLlmClient(_settings("key"), transport=transport).complete(
        system="s", user="u", fallback="{}", budget=LlmBudget(2, 1000)
    )

    assert result.failure_kind is LlmFailureKind.HTTP_OTHER


@pytest.mark.asyncio
async def test_malformed_success_payload_is_controlled_bad_payload() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=[]))

    result = await DeepSeekLlmClient(_settings("key"), transport=transport).complete(
        system="s", user="u", fallback="{}", budget=LlmBudget(2, 1000)
    )

    assert result.degraded is True
    assert result.failure_kind is LlmFailureKind.BAD_PAYLOAD
    assert result.usage_known is False


@pytest.mark.asyncio
async def test_malformed_usage_is_controlled_bad_payload() -> None:
    payload = _ok_payload(content="回答", usage={"total_tokens": "unknown"})
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=payload))

    result = await DeepSeekLlmClient(_settings("key"), transport=transport).complete(
        system="s", user="u", fallback="{}", budget=LlmBudget(2, 1000)
    )

    assert result.degraded is True
    assert result.failure_kind is LlmFailureKind.BAD_PAYLOAD


@pytest.mark.asyncio
async def test_unenumerated_httpx_error_still_degrades_instead_of_escaping() -> None:
    """ProtocolError 等非枚举 HTTPError 不得逃出适配器变成 500。"""

    def raise_protocol_error(request: httpx.Request) -> httpx.Response:
        raise httpx.ProtocolError("bad chunk", request=request)

    result = await DeepSeekLlmClient(
        _settings("key"), transport=httpx.MockTransport(raise_protocol_error)
    ).complete(system="s", user="u", fallback="{}", budget=LlmBudget(2, 1000))

    assert result.degraded is True
    assert result.failure_kind is LlmFailureKind.NETWORK


@pytest.mark.asyncio
async def test_successful_response_with_empty_content_is_not_a_transport_failure() -> None:
    """合法 200 + 空正文应由质量循环重试，而不是伪装成上游故障。"""

    payload = _ok_payload(
        content="", usage={"prompt_tokens": 120, "completion_tokens": 0, "total_tokens": 120}
    )
    result = await DeepSeekLlmClient(
        _settings("key"),
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload)),
    ).complete(system="s", user="u", fallback='{"answer":"兜底"}', budget=LlmBudget(2, 1000))

    assert result.text == ""
    assert result.degraded is False
    assert result.failure_kind is None
    assert result.usage_known is True
    assert result.tokens == 120


@pytest.mark.asyncio
async def test_successful_response_with_incomplete_usage_marks_usage_unknown() -> None:
    payload = _ok_payload(content="回答", usage={"total_tokens": 120})
    result = await DeepSeekLlmClient(
        _settings("key"),
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload)),
    ).complete(system="s", user="u", fallback="{}", budget=LlmBudget(2, 1000))

    assert result.text == "回答"
    assert result.degraded is False
    assert result.usage_known is False
