"""v2 幂等记录仓储（契约 §8.7.3）：`idempotency_records` 的唯一读写入口。"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.idempotency import IdempotencyRecord


class IdempotencyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find(
        self,
        *,
        role: str,
        principal_digest: str,
        merchant_id: UUID,
        operation: str,
        client_request_id: str,
    ) -> IdempotencyRecord | None:
        statement = select(IdempotencyRecord).where(
            IdempotencyRecord.role == role,
            IdempotencyRecord.principal_digest == principal_digest,
            IdempotencyRecord.merchant_id == merchant_id,
            IdempotencyRecord.operation == operation,
            IdempotencyRecord.client_request_id == client_request_id,
        )
        return (await self._session.execute(statement)).scalar_one_or_none()

    async def try_create_processing(self, record: IdempotencyRecord) -> IdempotencyRecord | None:
        """在嵌套事务里尝试插入 `PROCESSING` 行；与并发请求撞唯一域时返回 `None`。

        调用方在拿到 `None` 后应重新 `find()` 走已存在分支，而不是把并发竞态
        当成异常抛给用户——两个并发的相同 `client_request_id` 应该落到同一条
        幂等记录，而不是一个成功一个 500。
        """

        try:
            async with self._session.begin_nested():
                self._session.add(record)
                await self._session.flush()
        except IntegrityError:
            return None
        return record

    async def mark_succeeded(
        self,
        record: IdempotencyRecord,
        *,
        response_status: int,
        response_body: dict[str, Any],
    ) -> None:
        record.status = "SUCCEEDED"
        record.response_status = response_status
        record.response_body = response_body
        await self._session.flush()

    async def mark_failed(
        self,
        record: IdempotencyRecord,
        *,
        retryable: bool,
        response_status: int | None = None,
        response_body: dict[str, Any] | None = None,
    ) -> None:
        record.status = "FAILED_RETRYABLE" if retryable else "FAILED_FINAL"
        record.response_status = response_status
        record.response_body = response_body
        await self._session.flush()
