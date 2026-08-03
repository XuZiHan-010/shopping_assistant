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
