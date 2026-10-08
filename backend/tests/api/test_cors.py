"""跨域预检行为测试。

断言的是中间件的实际放行结果，不是 `_ALLOWED_HEADERS` 常量本身——
后者只会把实现照抄一遍，改错了测试也跟着错。
"""

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from app.core.config import AppEnvironment, Settings
from app.main import create_app

ALLOWED_ORIGIN = "http://localhost:5173"


async def _preflight(client: AsyncClient, header: str, *, origin: str = ALLOWED_ORIGIN):
    return await client.options(
        "/api/health",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": header,
        },
    )


@pytest.mark.parametrize(
    "header",
    [
        "Authorization",
        "X-Admin-Token",
        "X-Session-Id",
        "Accept",
        "Content-Type",
        "X-Request-Id",
    ],
)
async def test_preflight_allows_contract_headers(client: AsyncClient, header: str) -> None:
    """契约要求的请求头都必须通过预检（AGENTS.md §八）。

    `X-Admin-Token` 是 P0 运维端点的凭证载体：漏掉它，B7 的
    `/api/admin/ops/status` 会被浏览器在预检阶段直接挡掉。`X-Session-Id`
    是 N1 起 v2 顾客/商家会话的凭证载体，同样不能被预检挡在门外。
    """

    response = await _preflight(client, header)

    assert response.status_code == 200
    allowed = response.headers["access-control-allow-headers"].lower()
    assert header.lower() in allowed


async def test_preflight_rejects_unlisted_header(client: AsyncClient) -> None:
    """未登记的请求头不应被放行，避免 allow_headers 退化成通配。"""

    response = await _preflight(client, "X-Unexpected-Header")

    assert response.status_code == 400


async def test_preflight_rejects_foreign_origin(client: AsyncClient) -> None:
    """CORS 只允许精确 Origin，其他站点不得通过预检。"""

    response = await _preflight(
        client,
        "Authorization",
        origin="http://evil.example.com",
    )

    assert response.status_code == 400


SHOP_ORIGIN = "http://localhost:3000"


def _settings(**overrides: object) -> Settings:
    return Settings(
        app_env=AppEnvironment.TEST,
        database_url="postgresql+psycopg://user:pass@localhost/test",
        frontend_origin="http://localhost:5173",
        rate_limit_per_minute=1000,
        **overrides,  # type: ignore[arg-type]
    )


async def _shop_preflight(settings: Settings, origin: str) -> int:
    async with AsyncClient(
        transport=ASGITransport(app=create_app(settings)), base_url="http://testserver"
    ) as shop_client:
        response = await shop_client.options(
            "/api/health",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "X-Session-Id",
            },
        )
    return response.status_code


async def test_shop_origin_allowed_when_configured() -> None:
    """顾客端（shop）与商家端是两个精确 Origin，都要能通过预检。"""

    settings = _settings(shop_origin=SHOP_ORIGIN)

    assert await _shop_preflight(settings, SHOP_ORIGIN) == 200
    assert await _shop_preflight(settings, ALLOWED_ORIGIN) == 200


async def test_shop_origin_not_allowed_when_unconfigured() -> None:
    assert await _shop_preflight(_settings(), SHOP_ORIGIN) == 400


async def test_shop_origin_does_not_open_other_origins() -> None:
    settings = _settings(shop_origin=SHOP_ORIGIN)

    assert await _shop_preflight(settings, "http://evil.example.com") == 400


@pytest.mark.parametrize("bad", ["*", "http://localhost:3000/path", "http://user:pw@localhost:3000"])
def test_shop_origin_must_be_exact_origin(bad: str) -> None:
    with pytest.raises(ValidationError):
        _settings(shop_origin=bad)
