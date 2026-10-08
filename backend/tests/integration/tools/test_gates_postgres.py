"""闸门接真实仓储：来源状态与安全审计都落在 PostgreSQL 上（§6.9 必测，N2-1）。

单测用内存替身证明闸门逻辑；这里证明 `DatabaseProvenanceStore` 与
`AuditRepositorySecurityAudit` 这两个生产适配器真的把隔离键和审计写对了。
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.session import SessionContext, SessionRole
from app.db.session import Database
from app.models.operations import AuditLog
from app.models.provenance import ConversationProvenance
from app.repositories.audit import AuditRepository
from app.tools.errors import FatalToolError
from app.tools.gates import AuditRepositorySecurityAudit, DatabaseProvenanceStore, ToolGates
from app.tools.registry import ToolRegistry
from app.tools.types import ToolContext
from tests.unit.tools.tool_doubles import (
    PRINCIPAL_SECRET,
    SPECS,
    RecordingDraftSink,
    reset_products,
)

pytestmark = pytest.mark.integration


def _gates(database: Database) -> ToolGates:
    registry = ToolRegistry()
    for spec in SPECS:
        registry.register(spec)
    return ToolGates(
        registry,
        provenance=DatabaseProvenanceStore(database),
        principal_secret=PRINCIPAL_SECRET,
        audit=AuditRepositorySecurityAudit(AuditRepository(database)),
        drafts=RecordingDraftSink(),
    )


def _customer(merchant_id: UUID) -> SessionContext:
    return SessionContext(
        session_record_id=uuid4(),
        role=SessionRole.CUSTOMER,
        merchant_id=merchant_id,
        buyer_key="buyer-secret-key",
        shop_slug="borough-100",
    )


def _ctx(session: SessionContext, conversation: str) -> ToolContext:
    return ToolContext(session=session, conversation_id=conversation, request_id="req-it-1")


async def test_object_seen_in_one_conversation_is_rejected_in_another(
    db_session: AsyncSession, merchant_one_id: UUID, integration_database: Database
) -> None:
    await db_session.commit()  # 适配器各开会话，商家行必须先提交才满足外键
    reset_products()
    gates = _gates(integration_database)
    buyer = _customer(merchant_one_id)

    seen = await gates.invoke(_ctx(buyer, "conv-a"), "get_product", {"product_id": "p-1"})
    assert seen.ok
    same = await gates.invoke(_ctx(buyer, "conv-a"), "set_cart_quantity", {"product_id": "p-1"})
    assert same.ok

    with pytest.raises(FatalToolError):
        await gates.invoke(_ctx(buyer, "conv-b"), "set_cart_quantity", {"product_id": "p-1"})

    rows = (await db_session.execute(select(ConversationProvenance))).scalars().all()
    assert {(r.conversation_id, r.object_type, r.object_id) for r in rows} == {
        ("conv-a", "PRODUCT", "p-1")
    }
    # 主体键是摘要，不是原始 buyer_key。
    assert all(r.principal_kind == "BOUND_PRINCIPAL" for r in rows)
    assert all("buyer-secret-key" not in r.principal_id for r in rows)

    audits = (
        (
            await db_session.execute(
                select(AuditLog).where(AuditLog.event_type == "TOOL_CALL_BLOCKED")
            )
        )
        .scalars()
        .all()
    )
    assert len(audits) == 1
    assert audits[0].merchant_id == merchant_one_id
    assert audits[0].resource_id == "set_cart_quantity"
    assert audits[0].event_metadata == {"gate": "provenance", "role": "CUSTOMER"}
    assert "buyer-secret-key" not in str(audits[0].event_metadata)
