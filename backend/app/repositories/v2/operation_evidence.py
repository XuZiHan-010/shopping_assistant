"""操作证据 nonce 的登记、消费与清理（契约 §8.7.9）。

消费是**一条带条件的 UPDATE**，不是「先查再改」：后者在并发下会两个请求都读到
`consumed_at IS NULL`，然后都认为自己赢了。这里以影响行数为唯一判据，0 行即拒绝。

本仓储不自己提交。消费必须由调用方与业务写入放在同一个事务里，业务失败时随之回滚。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast

from sqlalchemy import CursorResult, delete, insert, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.operations import OperationEvidenceNonce


class OperationEvidenceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def register(
        self, *, purpose: str, nonce: str, issued_at: datetime, expires_at: datetime
    ) -> None:
        await self._session.execute(
            insert(OperationEvidenceNonce).values(
                purpose=purpose, nonce=nonce, issued_at=issued_at, expires_at=expires_at
            )
        )

    async def consume(self, *, purpose: str, nonce: str, now: datetime) -> bool:
        """消费成功返回 True；不存在、已消费或已过期都返回 False（对外不可区分）。"""

        result = cast(
            "CursorResult[Any]",
            await self._session.execute(
                update(OperationEvidenceNonce)
                .where(
                    OperationEvidenceNonce.purpose == purpose,
                    OperationEvidenceNonce.nonce == nonce,
                    OperationEvidenceNonce.consumed_at.is_(None),
                    OperationEvidenceNonce.expires_at > now,
                )
                .values(consumed_at=now)
            ),
        )
        return result.rowcount == 1

    async def purge_expired(self, *, now: datetime) -> int:
        """清理已过期的记录；接受 `now` 参数，不读墙钟（Cron 接线在 N5）。"""

        result = cast(
            "CursorResult[Any]",
            await self._session.execute(
                delete(OperationEvidenceNonce).where(OperationEvidenceNonce.expires_at <= now)
            ),
        )
        return result.rowcount or 0
