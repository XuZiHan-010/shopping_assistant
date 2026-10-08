import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_unknown_route_uses_safe_error_contract(client: AsyncClient) -> None:
    response = await client.get("/api/not-found")

    payload = response.json()
    assert response.status_code == 404
    assert payload["code"] == "NOT_FOUND"
    assert payload["message"] == "请求的资源不存在"
    assert payload["request_id"]
    assert payload["details"] == []
    assert payload["retryable"] is False


@pytest.mark.asyncio
async def test_invalid_request_id_is_replaced(client: AsyncClient) -> None:
    response = await client.get("/api/health", headers={"X-Request-Id": "invalid request id"})

    request_id = response.headers["X-Request-Id"]
    assert request_id != "invalid request id"
    assert len(request_id) == 36


V2_NEW_CODES = {
    "SESSION_REQUIRED",
    "SESSION_INVALID",
    "SESSION_ROLE_MISMATCH",
    "CUSTOMER_BINDING_REQUIRED",
    "SESSION_ALREADY_BOUND",
    "RESOURCE_FORBIDDEN",
    "PRODUCT_NOT_IN_SCOPE",
    "INSUFFICIENT_STOCK",
    "ILLEGAL_STATE_TRANSITION",
    "VERSION_CONFLICT",
    "DRAFT_EXPIRED",
    "GUARDRAIL_REJECTED",
    "CONFIRMATION_REQUIRED",
    "INVALID_CURSOR",
}


def test_v2_codes_registered_in_single_enum() -> None:
    from app.core.errors import ErrorCode

    assert {c.value for c in ErrorCode} >= V2_NEW_CODES


def test_every_v2_code_has_both_locales() -> None:
    """新码必须有 zh-CN 与 en-US 文案，不能落到 _FALLBACK。"""
    from app.localization.error_messages import _MESSAGES
    from app.localization.locales import SupportedLocale

    for code in V2_NEW_CODES:
        assert code in _MESSAGES, f"{code} 缺少本地化文案"
        assert set(_MESSAGES[code]) == set(SupportedLocale), f"{code} 语言不全"


def test_every_v2_code_registered_in_section_14() -> None:
    """后端计划 §14 是错误码的人读登记处，errors.py 的 docstring 要求同步。"""
    from pathlib import Path

    doc = Path(__file__).resolve().parents[3] / "docs" / "backend-development-plan.md"
    text = doc.read_text(encoding="utf-8")
    section = text.split("## 14. 后端错误码")[1].split("## 15.")[0]
    for code in V2_NEW_CODES:
        assert code in section, f"{code} 未登记在 §14"
