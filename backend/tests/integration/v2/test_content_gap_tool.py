"""顾客工具 `get_product_attribute` 触发内容缺口信号计数（N3 阶段 C Task 7，PRD D11③④）。

必填属性缺失时既要回答"缺失"、又要让 `CONTENT_GAP` 信号 +1；非必填属性缺失只回答，
不计数；商品内容更新（`content_version` 递增）后重新提问同一属性，若缺口已补则不再计数。
事实源与 Task 3（商品内容起草）共用同一份 `content_completeness.py` 必填清单，
两处判断"是否算缺口"不允许出现分歧。
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import Database
from app.models.analytics import Product
from app.models.memory_v2 import CustomerSignal
from app.repositories.audit import AuditRepository
from app.services.v2.drafts import DatabaseDraftSink
from app.tools.customer import build_customer_tools
from app.tools.gates import AuditRepositorySecurityAudit, DatabaseProvenanceStore, ToolGates
from app.tools.registry import ToolRegistry
from app.tools.types import ToolContext
from tests.support.trade import SHOP, bound_context

pytestmark = pytest.mark.integration

PRINCIPAL_SECRET = b"content-gap-tests-principal-secret-0123"
CONVERSATION = "conv-customer-content-gap-1"


def _gates(database: Database) -> ToolGates:
    registry = ToolRegistry()
    for spec in build_customer_tools(database):
        registry.register(spec)
    return ToolGates(
        registry,
        provenance=DatabaseProvenanceStore(database),
        principal_secret=PRINCIPAL_SECRET,
        audit=AuditRepositorySecurityAudit(AuditRepository(database)),
        drafts=DatabaseDraftSink(database),
    )


async def _seed_product(
    database: Database, merchant_id: UUID, *, category: str, attributes: dict[str, dict[str, str]],
    content_version: int = 1,
) -> UUID:
    product_id = uuid4()
    async with database.session() as session:
        session.add(Product(
            id=product_id, merchant_id=merchant_id, business_date="2026-09-20",
            product_code=f"gap-tool-{product_id.hex[:10]}", title="商品", category=category,
            price=Decimal("10.00"), status="ONLINE", listed_at="2026-09-20T00:00:00+00:00",
            stock_on_hand=5, stock_reserved=0, content_version=content_version,
            attributes=attributes,
        ))
        await session.commit()
    return product_id


def _ctx(merchant_id: UUID, buyer_key: str) -> ToolContext:
    session = bound_context(merchant_id, buyer_key, shop_slug=SHOP)
    return ToolContext(
        session=session, conversation_id=CONVERSATION, request_id="req-content-gap-1"
    )


async def _signal(database: Database, merchant_id: UUID, product_id: UUID) -> CustomerSignal | None:
    async with database.session() as session:
        return await session.scalar(select(CustomerSignal).where(
            CustomerSignal.merchant_id == merchant_id,
            CustomerSignal.kind == "CONTENT_GAP",
            CustomerSignal.product_id == product_id,
        ))


@pytest.mark.asyncio
async def test_missing_required_attribute_counts_content_gap(
    integration_database: Database, merchant_one_id: UUID, db_session: AsyncSession
) -> None:
    await db_session.commit()
    product_id = await _seed_product(
        integration_database, merchant_one_id, category="女装", attributes={},
    )
    gates = _gates(integration_database)
    ctx = _ctx(merchant_one_id, "buyer-content-gap-1")

    result = await gates.invoke(
        ctx, "get_product_attribute", {"product_id": str(product_id), "attribute": "产地"}
    )

    assert result.ok
    assert result.payload["value"] is None
    row = await _signal(integration_database, merchant_one_id, product_id)
    assert row is not None
    assert row.count == 1
    assert row.derived_from == [
        {"source_type": "PRODUCT", "source_id": str(product_id), "content_version": 1}
    ]


@pytest.mark.asyncio
async def test_optional_attribute_missing_does_not_count(
    integration_database: Database, merchant_one_id: UUID, db_session: AsyncSession
) -> None:
    await db_session.commit()
    product_id = await _seed_product(
        integration_database, merchant_one_id, category="女装", attributes={},
    )
    gates = _gates(integration_database)
    ctx = _ctx(merchant_one_id, "buyer-content-gap-2")

    result = await gates.invoke(
        ctx, "get_product_attribute", {"product_id": str(product_id), "attribute": "包装颜色"}
    )

    assert result.ok
    assert result.payload["value"] is None
    assert await _signal(integration_database, merchant_one_id, product_id) is None


@pytest.mark.asyncio
async def test_present_attribute_returns_value_and_does_not_count(
    integration_database: Database, merchant_one_id: UUID, db_session: AsyncSession
) -> None:
    await db_session.commit()
    product_id = await _seed_product(
        integration_database, merchant_one_id, category="女装",
        attributes={"产地": {"value": "浙江", "source_type": "MERCHANT_FILLED"}},
    )
    gates = _gates(integration_database)
    ctx = _ctx(merchant_one_id, "buyer-content-gap-3")

    result = await gates.invoke(
        ctx, "get_product_attribute", {"product_id": str(product_id), "attribute": "产地"}
    )

    assert result.ok
    assert result.payload["value"] == "浙江"
    assert await _signal(integration_database, merchant_one_id, product_id) is None


@pytest.mark.asyncio
async def test_gap_stops_counting_after_content_updated_to_fill_it(
    integration_database: Database, merchant_one_id: UUID, db_session: AsyncSession
) -> None:
    """更新前的那一次已经计数；更新后属性已补，同一版本下重复提问不再产生新的缺口计数。"""

    await db_session.commit()
    product_id = await _seed_product(
        integration_database, merchant_one_id, category="女装", attributes={},
    )
    gates = _gates(integration_database)
    ctx = _ctx(merchant_one_id, "buyer-content-gap-4")
    await gates.invoke(
        ctx, "get_product_attribute", {"product_id": str(product_id), "attribute": "产地"}
    )

    async with integration_database.session() as session:
        product = await session.get(Product, product_id)
        assert product is not None
        product.attributes = {"产地": {"value": "云南", "source_type": "MERCHANT_FILLED"}}
        product.content_version = 2
        await session.commit()

    result = await gates.invoke(
        ctx, "get_product_attribute", {"product_id": str(product_id), "attribute": "产地"}
    )

    assert result.payload["value"] == "云南"
    row = await _signal(integration_database, merchant_one_id, product_id)
    assert row is not None
    assert row.count == 1  # 更新前的那一次，更新后不再增加


@pytest.mark.asyncio
async def test_content_gap_signal_never_stores_question_text(
    integration_database: Database, merchant_one_id: UUID, db_session: AsyncSession
) -> None:
    await db_session.commit()
    product_id = await _seed_product(
        integration_database, merchant_one_id, category="女装", attributes={},
    )
    gates = _gates(integration_database)
    ctx = _ctx(merchant_one_id, "buyer-content-gap-5")

    await gates.invoke(
        ctx, "get_product_attribute", {"product_id": str(product_id), "attribute": "产地"}
    )

    row = await _signal(integration_database, merchant_one_id, product_id)
    assert row is not None
    assert "产地" not in str(row.derived_from)
