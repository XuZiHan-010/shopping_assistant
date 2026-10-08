"""对话来源状态：一个对话取得的对象访问资格不得扩散到其他对话（D8④/O2）。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import ColumnElement, String, delete, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.session import SessionRole
from app.models.provenance import ConversationProvenance
from app.models.session import AgentSession

#: 版本冲突后的最多重读次数（计划 Task 6：最多重试 3 次）。
MAX_RETRIES = 3


class ProvenanceWriteConflictError(RuntimeError):
    """同一来源记录连续版本冲突，超过重试上限。"""


class ConversationProvenanceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(
        self,
        *,
        principal_kind: str,
        principal_id: str,
        merchant_id: UUID,
        conversation_id: str,
        object_type: str,
        object_id: str,
    ) -> None:
        """记录"这个主体在这个对话里见过这个对象"，重复记录只续期不重复插入。

        按计划 Task 6 用版本号条件更新防并发覆盖：读当前 `version`，再
        `UPDATE ... WHERE version = 读到的值`；被别人抢先改过则重读，最多重试
        `MAX_RETRIES` 次，仍失败就抛 `ProvenanceWriteConflictError`，不做无限循环或盲写。
        首次写入用 `ON CONFLICT DO NOTHING`，与并发首写撞唯一键时同样转入重读。
        """

        scope = (
            ConversationProvenance.principal_kind == principal_kind,
            ConversationProvenance.principal_id == principal_id,
            ConversationProvenance.merchant_id == merchant_id,
            ConversationProvenance.conversation_id == conversation_id,
            ConversationProvenance.object_type == object_type,
            ConversationProvenance.object_id == object_id,
        )
        for _ in range(MAX_RETRIES + 1):
            now = datetime.now(UTC)
            expected = await self._current_version(scope)
            if expected is None:
                inserted = await self._session.execute(
                    pg_insert(ConversationProvenance)
                    .values(
                        id=uuid4(),
                        principal_kind=principal_kind,
                        principal_id=principal_id,
                        merchant_id=merchant_id,
                        conversation_id=conversation_id,
                        object_type=object_type,
                        object_id=object_id,
                        version=1,
                        first_seen_at=now,
                        last_seen_at=now,
                    )
                    .on_conflict_do_nothing(constraint="uq_conversation_provenance_scope")
                    .returning(ConversationProvenance.id)
                )
                if inserted.scalar_one_or_none() is not None:
                    await self._session.flush()
                    return
                continue
            updated = cast(
                "CursorResult[Any]",
                await self._session.execute(
                    update(ConversationProvenance)
                    .where(*scope, ConversationProvenance.version == expected)
                    .values(version=expected + 1, last_seen_at=now)
                ),
            )
            if updated.rowcount == 1:
                await self._session.flush()
                return
        raise ProvenanceWriteConflictError

    async def _current_version(self, scope: tuple[ColumnElement[bool], ...]) -> int | None:
        return (
            await self._session.execute(select(ConversationProvenance.version).where(*scope))
        ).scalar_one_or_none()

    async def has(
        self,
        *,
        principal_kind: str,
        principal_id: str,
        merchant_id: UUID,
        conversation_id: str,
        object_type: str,
        object_id: str,
    ) -> bool:
        row = (
            await self._session.execute(
                select(ConversationProvenance.id).where(
                    ConversationProvenance.principal_kind == principal_kind,
                    ConversationProvenance.principal_id == principal_id,
                    ConversationProvenance.merchant_id == merchant_id,
                    ConversationProvenance.conversation_id == conversation_id,
                    ConversationProvenance.object_type == object_type,
                    ConversationProvenance.object_id == object_id,
                )
            )
        ).scalar_one_or_none()
        return row is not None

    async def purge_expired_unbound_guests(self, *, now: datetime) -> int:
        """删除已过期且从未绑定身份的访客会话留下的来源状态，返回删除行数。

        这类会话再也无法被解析（过期即 `SESSION_INVALID`），也没有可继承它的已绑定
        主体，其来源状态已不可能再被使用。已绑定会话与商家会话不在此列：会话注销不删除
        业务对话（计划 Task 6）。
        """

        # 访客的 principal_id 就是 `str(session_record_id)`，与 PostgreSQL 的 uuid::text 同形。
        expired_guests = select(AgentSession.id.cast(String)).where(
            AgentSession.role == SessionRole.CUSTOMER.value,
            AgentSession.buyer_key.is_(None),
            AgentSession.expires_at <= now,
        )
        result = cast(
            "CursorResult[Any]",
            await self._session.execute(
                delete(ConversationProvenance).where(
                    ConversationProvenance.principal_kind == "GUEST_SESSION",
                    ConversationProvenance.principal_id.in_(expired_guests),
                )
            ),
        )
        await self._session.flush()
        return result.rowcount or 0

    async def delete_for_conversation(
        self,
        *,
        principal_kind: str,
        principal_id: str,
        merchant_id: UUID,
        conversation_id: str,
    ) -> None:
        """删除对话时同事务清空其来源状态；调用方负责事务边界。"""

        await self._session.execute(
            delete(ConversationProvenance).where(
                ConversationProvenance.principal_kind == principal_kind,
                ConversationProvenance.principal_id == principal_id,
                ConversationProvenance.merchant_id == merchant_id,
                ConversationProvenance.conversation_id == conversation_id,
            )
        )
        await self._session.flush()
