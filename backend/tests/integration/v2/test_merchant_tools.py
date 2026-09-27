"""商家工具面（模块 C Task 1–2）：只读告警与补货草稿，接真实 PostgreSQL。

这里证明的是审批闸门在**生产装配**下也成立：`draft_restock` 走完整条管线之后，
`products` 一行都没被改动，变更只落在 `drafts` 表里。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.session import SessionContext, SessionRole
from app.db.session import Database
from app.models.analytics import Product
from app.models.drafts import Draft
from app.models.promotion import GuardrailConfig
from app.repositories.audit import AuditRepository
from app.schemas.v2.drafts import DraftKind, DraftState
from app.services.v2.drafts import DatabaseDraftSink
from app.tools.errors import FatalToolError
from app.tools.gates import AuditRepositorySecurityAudit, DatabaseProvenanceStore, ToolGates
from app.tools.merchant import build_merchant_tools
from app.tools.registry import ToolRegistry
from app.tools.types import ToolContext, ToolOutcome
from tests.support.merchant_v2 import seed_product

pytestmark = pytest.mark.integration

PRINCIPAL_SECRET = b"integration-principal-secret"
CONVERSATION = "conv-merchant-1"


def _gates(database: Database) -> ToolGates:
    registry = ToolRegistry()
    for spec in build_merchant_tools(database):
        registry.register(spec)
    return ToolGates(
        registry,
        provenance=DatabaseProvenanceStore(database),
        principal_secret=PRINCIPAL_SECRET,
        audit=AuditRepositorySecurityAudit(AuditRepository(database)),
        drafts=DatabaseDraftSink(database),
    )


def _ctx(merchant_id: UUID, conversation: str = CONVERSATION) -> ToolContext:
    session = SessionContext(
        session_record_id=UUID("00000000-0000-0000-0000-00000000c001"),
        role=SessionRole.MERCHANT,
        merchant_id=merchant_id,
        buyer_key=None,
        shop_slug=None,
    )
    return ToolContext(session=session, conversation_id=conversation, request_id="req-tool-1")


async def _snapshot_products(session: AsyncSession) -> list[tuple[UUID, int, int]]:
    rows = (await session.execute(select(Product))).scalars().all()
    return sorted((row.id, row.stock_on_hand, row.stock_reserved) for row in rows)


async def _see_product(gates: ToolGates, ctx: ToolContext) -> None:
    """先调只读告警工具：补货草稿的商品必须是本对话里工具返回过的（来源闸门）。"""

    result = await gates.invoke(ctx, "get_inventory_alerts", {})
    assert result.ok


@pytest.mark.asyncio
async def test_draft_restock_does_not_touch_products(
    db_session: AsyncSession, merchant_one_id: UUID, integration_database: Database
) -> None:
    await db_session.commit()
    product = await seed_product(integration_database, merchant_one_id, on_hand=3)
    before = await _snapshot_products(db_session)
    gates = _gates(integration_database)
    ctx = _ctx(merchant_one_id)
    await _see_product(gates, ctx)

    result = await gates.invoke(ctx, "draft_restock", {"product_id": str(product), "delta": 60})

    assert result.ok and result.outcome is ToolOutcome.DRAFT_CREATED
    assert await _snapshot_products(db_session) == before
    drafts = (await db_session.execute(select(Draft))).scalars().all()
    assert len(drafts) == 1
    assert drafts[0].state == DraftState.STAGED.value
    assert drafts[0].kind == DraftKind.RESTOCK.value


@pytest.mark.asyncio
async def test_draft_records_change_base(
    db_session: AsyncSession, merchant_one_id: UUID, integration_database: Database
) -> None:
    """按增量起草，并记录起草时的在库量作为变更基数（D9⑧）。"""

    await db_session.commit()
    product = await seed_product(integration_database, merchant_one_id, on_hand=12)
    gates = _gates(integration_database)
    ctx = _ctx(merchant_one_id)
    await _see_product(gates, ctx)

    await gates.invoke(ctx, "draft_restock", {"product_id": str(product), "delta": 60})

    draft = (await db_session.execute(select(Draft))).scalars().one()
    assert draft.payload["delta"] == 60
    assert draft.payload["base_on_hand"] == 12
    assert draft.target_version == 12
    assert draft.target_id == product
    assert draft.draft_version == 1


@pytest.mark.asyncio
async def test_draft_expires_in_seven_days(
    db_session: AsyncSession, merchant_one_id: UUID, integration_database: Database
) -> None:
    await db_session.commit()
    product = await seed_product(integration_database, merchant_one_id, on_hand=12)
    gates = _gates(integration_database)
    ctx = _ctx(merchant_one_id)
    await _see_product(gates, ctx)

    await gates.invoke(ctx, "draft_restock", {"product_id": str(product), "delta": 60})

    draft = (await db_session.execute(select(Draft))).scalars().one()
    assert (
        timedelta(days=7) - timedelta(minutes=1)
        < draft.expires_at - datetime.now(UTC)
        <= timedelta(days=7)
    )


@pytest.mark.asyncio
async def test_restock_over_guardrail_is_rejected_with_a_fixable_reason(
    db_session: AsyncSession, merchant_one_id: UUID, integration_database: Database
) -> None:
    """护栏未通过是可修正错误：商家看得到原因码、当前限制与修正方法（O5、Q17）。"""

    await db_session.commit()
    product = await seed_product(integration_database, merchant_one_id, on_hand=3)
    async with integration_database.session() as session:
        session.add(
            GuardrailConfig(
                merchant_id=merchant_one_id,
                max_discount_rate=0,
                max_price_change_rate=0,
                max_restock_delta=100,
                updated_by="test",
            )
        )
        await session.commit()
    gates = _gates(integration_database)
    ctx = _ctx(merchant_one_id)
    await _see_product(gates, ctx)

    result = await gates.invoke(ctx, "draft_restock", {"product_id": str(product), "delta": 150})

    assert result.ok is False
    assert result.guardrail is not None
    assert result.guardrail.code == "RESTOCK_DELTA_EXCEEDS_LIMIT"
    assert "100" in (result.guardrail.current_limit or "")
    assert result.guardrail.remediation
    assert (await db_session.execute(select(Draft))).scalars().all() == []


@pytest.mark.asyncio
async def test_restock_for_an_unseen_product_is_fatal(
    db_session: AsyncSession, merchant_one_id: UUID, integration_database: Database
) -> None:
    """来源闸门：模型不能凭空说出一个商品 ID 就为它起草。"""

    await db_session.commit()
    product = await seed_product(integration_database, merchant_one_id, on_hand=3)
    gates = _gates(integration_database)

    with pytest.raises(FatalToolError):
        await gates.invoke(
            _ctx(merchant_one_id), "draft_restock", {"product_id": str(product), "delta": 60}
        )

    assert (await db_session.execute(select(Draft))).scalars().all() == []


@pytest.mark.asyncio
async def test_restock_for_another_merchants_product_is_fatal(
    db_session: AsyncSession,
    merchant_one_id: UUID,
    merchant_two_id: UUID,
    integration_database: Database,
) -> None:
    """R5：即使商品 ID 猜对了，也不属于当前商家。"""

    await db_session.commit()
    theirs = await seed_product(integration_database, merchant_two_id, on_hand=30)
    gates = _gates(integration_database)
    ctx = _ctx(merchant_one_id)
    await _see_product(gates, ctx)

    with pytest.raises(FatalToolError):
        await gates.invoke(ctx, "draft_restock", {"product_id": str(theirs), "delta": 60})

    assert (await db_session.execute(select(Draft))).scalars().all() == []


@pytest.mark.asyncio
async def test_alerts_tool_only_returns_own_shop(
    db_session: AsyncSession,
    merchant_one_id: UUID,
    merchant_two_id: UUID,
    integration_database: Database,
) -> None:
    await db_session.commit()
    mine = await seed_product(integration_database, merchant_one_id, on_hand=1)
    theirs = await seed_product(integration_database, merchant_two_id, on_hand=1)
    gates = _gates(integration_database)

    result = await gates.invoke(_ctx(merchant_one_id), "get_inventory_alerts", {})

    payload = result.payload
    assert isinstance(payload, dict)
    ids = {alert["product_id"] for alert in payload["alerts"]}
    assert str(mine) in ids and str(theirs) not in ids


@pytest.mark.asyncio
async def test_merchant_tools_are_not_on_the_customer_surface(
    integration_database: Database,
) -> None:
    registry = ToolRegistry()
    for spec in build_merchant_tools(integration_database):
        registry.register(spec)

    customer_surface = {spec.name for spec in registry.surface_for(SessionRole.CUSTOMER)}

    assert customer_surface == set()
