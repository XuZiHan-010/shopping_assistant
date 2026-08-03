from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import MerchantScopeViolationError
from app.core.security import MerchantContext
from app.db.session import Database
from app.models.merchant import Merchant
from app.models.operations import AuditLog
from app.repositories.audit import AuditRepository
from app.repositories.conversation import ConversationRepository
from app.services.merchant_scope import MerchantScopeService

MERCHANT_ONE_ID = UUID("00000000-0000-0000-0000-000000000001")
MERCHANT_TWO_ID = UUID("00000000-0000-0000-0000-000000000002")


@pytest.mark.asyncio
async def test_cross_merchant_access_persists_audit_in_independent_transaction(
    db_session: AsyncSession,
    integration_database: Database,
) -> None:
    db_session.add_all(
        [
            Merchant(
                id=MERCHANT_ONE_ID,
                merchant_code="borough-demo-100",
                display_name="Borough商家100",
            ),
            Merchant(
                id=MERCHANT_TWO_ID,
                merchant_code="borough-demo-101",
                display_name="Borough商家101",
            ),
        ]
    )
    # 必须先落库再建会话：模型之间没有 relationship（仓储一律显式传
    # merchant_id，避免跨商家的隐式懒加载），SQLAlchemy 因此不知道
    # conversations 依赖 merchants，flush 顺序会退化成按表名排序，
    # 先插会话再插商家就会撞外键。
    await db_session.flush()

    conversations = ConversationRepository(db_session)
    other = await conversations.create(MERCHANT_TWO_ID, "其他商家会话")
    await db_session.commit()
    # 在 expire_all 之前取出主键快照：过期后再访问 ORM 属性会触发惰性刷新，
    # 异步 Session 下同步属性访问无法发起 IO，会抛 MissingGreenlet。
    other_id = other.id
    service = MerchantScopeService(
        conversations,
        AuditRepository(integration_database),
    )

    with pytest.raises(MerchantScopeViolationError):
        await service.require_conversation(
            MerchantContext(merchant_id=MERCHANT_ONE_ID),
            other_id,
            request_id="request-audit-1",
        )

    # 过期本会话的全部身份映射，强制审计记录从数据库重新读取，
    # 以此证明它是在独立事务里提交的，而不是当前事务的未提交数据。
    db_session.expire_all()
    audit = await db_session.scalar(
        select(AuditLog).where(AuditLog.request_id == "request-audit-1")
    )
    assert audit is not None
    assert audit.merchant_id == MERCHANT_ONE_ID
    assert audit.resource_id == str(other_id)
