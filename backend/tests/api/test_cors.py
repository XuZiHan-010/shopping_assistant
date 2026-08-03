"""跨域预检行为测试。

断言的是中间件的实际放行结果，不是 `_ALLOWED_HEADERS` 常量本身——
后者只会把实现照抄一遍，改错了测试也跟着错。
"""

import pytest
from httpx import AsyncClient

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
    ["Authorization", "X-Admin-Token", "Accept", "Content-Type", "X-Request-Id"],
)
async def test_preflight_allows_contract_headers(client: AsyncClient, header: str) -> None:
    """契约要求的五个请求头都必须通过预检。

    `X-Admin-Token` 是 P0 运维端点的凭证载体（AGENTS.md §10.2.1）：
    漏掉它，B7 的 `/api/admin/ops/status` 会被浏览器在预检阶段直接挡掉。
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
