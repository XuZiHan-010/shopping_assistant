"""清理已过期的界面操作证据 nonce 及其售后确认摘要快照（契约 §8.7.9；N5 C Task 4）。

这个任务**不是**过期判定的依据：消费 nonce 是一条带 `expires_at > now` 条件的 UPDATE
（`OperationEvidenceRepository.consume`），过期的证据即使还在表里也消费不了。
清理只负责不让两张表无限增长；Cron 迟跑、漏跑，业务结果都不变。

`after_sale_challenge_previews` 没有自己的过期时间，它与 nonce 同一个事务写入、共用 nonce
作主键：nonce 行被清掉之后，对应的摘要快照再也不可能被读取，随同一事务删除。

接受 `now` 参数而不读墙钟。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast

from sqlalchemy import CursorResult, delete, select

from app.db.session import Database
from app.models.after_sales import AfterSaleChallengePreview
from app.models.operations import OperationEvidenceNonce
from app.repositories.v2.operation_evidence import OperationEvidenceRepository


async def purge_operation_evidence(database: Database, *, now: datetime) -> tuple[int, int]:
    """返回（删除的 nonce 数，删除的摘要快照数）；重复执行只会返回 (0, 0)。"""

    async with database.session() as session:
        nonces = await OperationEvidenceRepository(session).purge_expired(now=now)
        previews = cast(
            "CursorResult[Any]",
            await session.execute(
                delete(AfterSaleChallengePreview).where(
                    AfterSaleChallengePreview.nonce.not_in(select(OperationEvidenceNonce.nonce))
                )
            ),
        )
        await session.commit()
        return nonces, previews.rowcount or 0
