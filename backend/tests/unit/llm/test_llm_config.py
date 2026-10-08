"""`LLM_PROTOCOL` / `LLM_THINKING` 配置开关的默认值与取值范围。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def _settings(**overrides: object) -> Settings:
    return Settings(
        database_url="postgresql+psycopg://u:p@localhost/db",
        frontend_origin="http://localhost:5173",
        **overrides,  # type: ignore[arg-type]
    )


def test_protocol_defaults_to_openai() -> None:
    """现有 v1 链路已在用 OpenAI 兼容协议；切换必须有真实冒烟的实测依据。"""

    assert _settings().llm_protocol == "openai"


def test_thinking_defaults_to_disabled() -> None:
    """官方默认开启思考模式，成本、延迟与回放要求都不同；我们显式默认关闭。"""

    assert _settings().llm_thinking == "disabled"


@pytest.mark.parametrize("protocol", ["openai", "anthropic"])
def test_protocol_accepts_the_two_supported_values(protocol: str) -> None:
    assert _settings(llm_protocol=protocol).llm_protocol == protocol


def test_protocol_rejects_unknown_values() -> None:
    with pytest.raises(ValidationError):
        _settings(llm_protocol="gemini")


@pytest.mark.parametrize("thinking", ["enabled", "disabled"])
def test_thinking_accepts_the_two_supported_values(thinking: str) -> None:
    assert _settings(llm_thinking=thinking).llm_thinking == thinking


def test_thinking_rejects_unknown_values() -> None:
    with pytest.raises(ValidationError):
        _settings(llm_thinking="auto")
