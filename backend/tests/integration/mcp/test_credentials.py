"""MCP 凭证（N5 A Task 1；PRD A8、§12.5；契约 §8.14.3）。

凭证与会话同一安全等级：高熵、库里只存指纹、限定商家 / scope / 有效期、撤销即时生效。
「撤销后下一次请求立即失效」要求每次校验都查库——这里用真实 PostgreSQL 证明。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import Database
from app.mcp.credentials import InvalidMcpCredentialRequest, McpCredentialStore

pytestmark = pytest.mark.integration

NOW = datetime(2026, 10, 3, 8, 0, tzinfo=UTC)


class _Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
async def merchant(db_session: AsyncSession, merchant_one_id: UUID) -> UUID:
    # 凭证存储用自己的连接，夹具里的商家行必须先提交才看得见。
    await db_session.commit()
    return merchant_one_id


async def test_issued_token_verifies_to_its_merchant_and_scopes(
    integration_database: Database, merchant: UUID
) -> None:
    store = McpCredentialStore(integration_database)
    issued = await store.issue(
        merchant_id=merchant, scopes={"query_metrics"}, ttl=timedelta(hours=24)
    )

    principal = await store.verify(issued.token)

    assert principal is not None
    assert principal.merchant_id == merchant
    assert principal.scopes == frozenset({"query_metrics"})


async def test_revocation_takes_effect_on_next_verify(
    integration_database: Database, merchant: UUID
) -> None:
    store = McpCredentialStore(integration_database)
    issued = await store.issue(
        merchant_id=merchant, scopes={"query_metrics"}, ttl=timedelta(hours=24)
    )
    assert await store.verify(issued.token) is not None

    assert await store.revoke(issued.credential_id) is True

    assert await store.verify(issued.token) is None


async def test_revocation_is_visible_to_another_store_instance(
    integration_database: Database, merchant: UUID
) -> None:
    """撤销来自命令行进程，校验发生在 API 进程：两者不共享任何内存状态。"""

    api_side = McpCredentialStore(integration_database)
    cli_side = McpCredentialStore(integration_database)
    issued = await cli_side.issue(
        merchant_id=merchant, scopes={"query_metrics"}, ttl=timedelta(hours=1)
    )
    assert await api_side.verify(issued.token) is not None

    await cli_side.revoke(issued.credential_id)

    assert await api_side.verify(issued.token) is None


async def test_expired_credential_does_not_verify(
    integration_database: Database, merchant: UUID
) -> None:
    clock = _Clock(NOW)
    store = McpCredentialStore(integration_database, clock=clock)
    issued = await store.issue(
        merchant_id=merchant, scopes={"query_metrics"}, ttl=timedelta(hours=1)
    )

    clock.now = NOW + timedelta(hours=1)

    assert await store.verify(issued.token) is None


async def test_unknown_token_does_not_verify(
    integration_database: Database, merchant: UUID
) -> None:
    assert await McpCredentialStore(integration_database).verify("not-a-real-token") is None


async def test_token_stored_as_fingerprint_only(
    integration_database: Database, merchant: UUID
) -> None:
    store = McpCredentialStore(integration_database)
    issued = await store.issue(
        merchant_id=merchant, scopes={"query_metrics"}, ttl=timedelta(hours=24)
    )

    async with integration_database.session() as session:
        rows = (await session.execute(text("SELECT * FROM mcp_credentials"))).mappings().all()

    assert len(rows) == 1
    assert issued.token not in json.dumps([dict(row) for row in rows], default=str)


@pytest.mark.parametrize(
    "scopes",
    [set(), {"draft_restock"}, {"query_metrics", "create_export"}, {"list_signals"}],
)
async def test_scopes_must_be_non_empty_subset_of_whitelist(
    integration_database: Database, merchant: UUID, scopes: set[str]
) -> None:
    with pytest.raises(InvalidMcpCredentialRequest):
        await McpCredentialStore(integration_database).issue(
            merchant_id=merchant, scopes=scopes, ttl=timedelta(hours=24)
        )


@pytest.mark.parametrize("ttl", [timedelta(0), timedelta(hours=-1), timedelta(days=8)])
async def test_ttl_must_be_short_and_positive(
    integration_database: Database, merchant: UUID, ttl: timedelta
) -> None:
    with pytest.raises(InvalidMcpCredentialRequest):
        await McpCredentialStore(integration_database).issue(
            merchant_id=merchant, scopes={"query_metrics"}, ttl=ttl
        )


async def test_revoking_unknown_credential_returns_false(
    integration_database: Database, merchant: UUID
) -> None:
    assert await McpCredentialStore(integration_database).revoke(UUID(int=1)) is False
