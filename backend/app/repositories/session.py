"""会话凭证的签发、解析、注销与级联撤销（D7/D8）。"""

from __future__ import annotations

import hmac
from collections.abc import Collection
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import ColumnElement, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import MerchantContext
from app.core.session import (
    SessionAlreadyBoundError,
    SessionContext,
    SessionRole,
    issuer_fingerprint,
    new_session_token,
    token_fingerprint,
)
from app.models.session import AgentSession


def _context_from_row(row: AgentSession) -> SessionContext:
    return SessionContext(
        session_record_id=row.id,
        role=SessionRole(row.role),
        merchant_id=row.merchant_id,
        buyer_key=row.buyer_key,
        shop_slug=row.shop_slug,
        expires_at=row.expires_at,
    )


class SessionRepository:
    """只接受服务端已解析的 `merchant_id` / `buyer_key`，不信任调用方传来的公开值。"""

    def __init__(self, session: AsyncSession, *, default_ttl_seconds: int) -> None:
        self._session = session
        self._default_ttl_seconds = default_ttl_seconds

    def _expires_at(self, ttl_seconds: int | None) -> datetime:
        ttl = self._default_ttl_seconds if ttl_seconds is None else ttl_seconds
        return datetime.now(UTC) + timedelta(seconds=ttl)

    async def issue_customer_guest(
        self,
        *,
        merchant_id: UUID,
        shop_slug: str,
        ttl_seconds: int | None = None,
    ) -> tuple[str, SessionContext]:
        token = new_session_token()
        record_id = uuid4()
        expires_at = self._expires_at(ttl_seconds)
        self._session.add(
            AgentSession(
                id=record_id,
                token_fingerprint=token_fingerprint(token),
                role=SessionRole.CUSTOMER.value,
                merchant_id=merchant_id,
                buyer_key=None,
                shop_slug=shop_slug,
                issuer_fingerprint=None,
                expires_at=expires_at,
            )
        )
        await self._session.flush()
        return token, SessionContext(
            session_record_id=record_id,
            role=SessionRole.CUSTOMER,
            merchant_id=merchant_id,
            buyer_key=None,
            shop_slug=shop_slug,
            expires_at=expires_at,
        )

    async def issue_merchant(
        self,
        mc: MerchantContext,
        *,
        issuer: str,
        ttl_seconds: int | None = None,
    ) -> tuple[str, SessionContext]:
        token = new_session_token()
        record_id = uuid4()
        expires_at = self._expires_at(ttl_seconds)
        self._session.add(
            AgentSession(
                id=record_id,
                token_fingerprint=token_fingerprint(token),
                role=SessionRole.MERCHANT.value,
                merchant_id=mc.merchant_id,
                buyer_key=None,
                shop_slug=None,
                issuer_fingerprint=issuer_fingerprint(issuer),
                expires_at=expires_at,
            )
        )
        await self._session.flush()
        return token, SessionContext(
            session_record_id=record_id,
            role=SessionRole.MERCHANT,
            merchant_id=mc.merchant_id,
            buyer_key=None,
            shop_slug=None,
            expires_at=expires_at,
        )

    async def bind_demo_customer(self, ctx: SessionContext, *, buyer_key: str) -> SessionContext:
        bound, _ = await self.bind_demo_customer_once(ctx, buyer_key=buyer_key)
        return bound

    async def bind_demo_customer_once(
        self, ctx: SessionContext, *, buyer_key: str
    ) -> tuple[SessionContext, bool]:
        """一次性、幂等绑定：同一 `buyer_key` 重试直接返回，不同 `buyer_key` 拒绝。

        调用方必须已经处于一个事务中（FastAPI 请求级 `AsyncSession` 在首条语句时
        自动开启），`with_for_update()` 让并发绑定请求在这一行上排队，不会出现
        两个请求都读到"未绑定"再各自写入的竞态。
        """

        row = (
            await self._session.execute(
                select(AgentSession)
                .where(AgentSession.id == ctx.session_record_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one()
        if row.buyer_key is not None:
            if row.buyer_key == buyer_key:
                return _context_from_row(row), False
            raise SessionAlreadyBoundError
        await self._session.execute(
            update(AgentSession).where(AgentSession.id == row.id).values(buyer_key=buyer_key)
        )
        await self._session.flush()
        return SessionContext(
            session_record_id=row.id,
            role=SessionRole(row.role),
            merchant_id=row.merchant_id,
            buyer_key=buyer_key,
            shop_slug=row.shop_slug,
            expires_at=row.expires_at,
        ), True

    async def resolve(self, token: str) -> SessionContext | None:
        fingerprint = token_fingerprint(token)
        row = (
            await self._session.execute(
                select(AgentSession).where(AgentSession.token_fingerprint == fingerprint)
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        # 索引查询已经按指纹相等匹配；这里再做一次防御性常量时间比对，
        # 不依赖索引扫描本身的比较方式满足这条安全属性。
        if not hmac.compare_digest(row.token_fingerprint, fingerprint):
            return None
        if row.revoked_at is not None:
            return None
        if row.expires_at <= datetime.now(UTC):
            return None
        return _context_from_row(row)

    async def revoke(self, ctx: SessionContext) -> None:
        await self._session.execute(
            update(AgentSession)
            .where(AgentSession.id == ctx.session_record_id, AgentSession.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        )
        await self._session.flush()

    async def revoke_by_issuer(self, demo_token: str) -> int:
        """D8⑤：撤销演示 Token 时，由它换取的全部会话同步失效。"""

        return await self._revoke_where(
            AgentSession.issuer_fingerprint == issuer_fingerprint(demo_token)
        )

    async def revoke_unlisted_issuers(self, active_fingerprints: Collection[str]) -> int:
        """撤销 issuer 已不在当前配置里的全部未撤销商家会话，返回撤销行数。

        被移除的演示 Token 原文已经拿不到了，所以对账只能按指纹集合比较；
        集合为空表示没有任何合法 issuer，全部商家会话都应失效。顾客会话没有
        issuer，不受影响。
        """

        return await self._revoke_where(
            AgentSession.issuer_fingerprint.is_not(None),
            AgentSession.issuer_fingerprint.not_in(list(active_fingerprints)),
        )

    async def _revoke_where(self, *criteria: ColumnElement[bool]) -> int:
        result = cast(
            "CursorResult[Any]",
            await self._session.execute(
                update(AgentSession)
                .where(*criteria, AgentSession.revoked_at.is_(None))
                .values(revoked_at=datetime.now(UTC))
            ),
        )
        await self._session.flush()
        return result.rowcount or 0
