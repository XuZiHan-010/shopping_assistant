"""安全审计写入，使用独立事务避免被业务回滚吞掉。"""

from __future__ import annotations

from uuid import UUID

from app.db.session import Database
from app.models.operations import AuditLog


class AuditRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def record_scope_violation(
        self,
        *,
        actor_merchant_id: UUID,
        resource_type: str,
        resource_id: str,
        request_id: str,
    ) -> None:
        async with self._database.session() as session:
            session.add(
                AuditLog(
                    merchant_id=actor_merchant_id,
                    event_type="MERCHANT_SCOPE_VIOLATION",
                    resource_type=resource_type,
                    resource_id=resource_id,
                    request_id=request_id,
                    event_metadata={},
                )
            )
            await session.commit()

    async def record_admin_action(
        self,
        *,
        merchant_id: UUID,
        event_type: str,
        resource_type: str,
        resource_id: str,
        request_id: str,
        metadata: dict[str, str] | None = None,
    ) -> None:
        """记录管理员对某个商家资源的写操作。

        管理员令牌可以跨商家写入，这类操作必须留痕才能事后追责（R5）；
        与越权审计一样使用独立事务，避免业务回滚把审计一起吞掉。
        """

        async with self._database.session() as session:
            session.add(
                AuditLog(
                    merchant_id=merchant_id,
                    event_type=event_type,
                    resource_type=resource_type,
                    resource_id=resource_id,
                    request_id=request_id,
                    event_metadata=metadata or {},
                )
            )
            await session.commit()
