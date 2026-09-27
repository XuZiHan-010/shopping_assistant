"""可信店铺解析、演示顾客绑定与购物车合并事务边界（D7/D8）。"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import (
    ResourceForbiddenError,
    ResourceNotFoundError,
    SessionAlreadyBoundConflictError,
)
from app.core.security import MerchantContext
from app.core.session import SessionAlreadyBoundError, SessionContext
from app.repositories.merchant import MerchantRepository
from app.repositories.session import SessionRepository


class CartMergePort(Protocol):
    """把访客购物车合并进已绑定顾客的领域实现，本计划只定义端口不实现。

    真实实现由 `n2-trade-closed-loop` 提供（购物车表届时才存在）。
    """

    async def merge_guest_into_buyer(
        self,
        *,
        session: AsyncSession,
        merchant_id: UUID,
        buyer_key: str,
        guest_session_id: UUID,
    ) -> bool:
        """返回 `True` 表示合并发生了数量截顶/剔除/截断等调整（`cart_adjusted`）。"""
        ...


class EmptyCartMerge:
    """N1 生产装配：购物车表尚不存在，恒返回"无可合并项"，不伪造合并成功。"""

    async def merge_guest_into_buyer(
        self,
        *,
        session: AsyncSession,
        merchant_id: UUID,
        buyer_key: str,
        guest_session_id: UUID,
    ) -> bool:
        return False


class SessionService:
    """顾客侧会话用例：把公开输入（`shop_slug`）转成服务端已验证的身份。"""

    def __init__(
        self,
        session: AsyncSession,
        *,
        merchants: MerchantRepository,
        sessions: SessionRepository,
        cart_merge: CartMergePort,
        demo_customer_identities: dict[str, str],
    ) -> None:
        self._session = session
        self._merchants = merchants
        self._sessions = sessions
        self._cart_merge = cart_merge
        self._demo_customer_identities = demo_customer_identities

    async def create_guest(self, shop_slug: str) -> tuple[str, SessionContext]:
        """未知 `shop_slug` 统一按 `RESOURCE_FORBIDDEN` 拒绝，不泄露店铺是否存在。"""

        merchant_id = await self._merchants.get_active_by_shop_slug(shop_slug)
        if merchant_id is None:
            raise ResourceForbiddenError
        return await self._sessions.issue_customer_guest(
            merchant_id=merchant_id, shop_slug=shop_slug
        )

    async def bind_demo_customer(self, ctx: SessionContext) -> tuple[SessionContext, bool]:
        """服务端从配置解析当前店铺唯一的演示顾客身份，请求体不携带任何身份字段。

        绑定与购物车合并共用调用方传入的同一个 `AsyncSession`（同一事务）；
        任一环节抛出异常都会让外层请求事务整体回滚，不会出现"已绑定但购物车
        未合并"的中间态。仓储身份冲突转换为公开的 409 契约。
        """

        buyer_key = self._demo_customer_identities.get(ctx.shop_slug or "")
        if buyer_key is None:
            # 演示模式关闭或当前店铺未配置演示顾客，对外统一"资源不存在"，
            # 不区分这两种原因（同一段文案，见契约 §8.8.2）。
            raise ResourceNotFoundError("demo customer identity")

        try:
            bound, newly_bound = await self._sessions.bind_demo_customer_once(
                ctx, buyer_key=buyer_key
            )
        except SessionAlreadyBoundError as exc:
            raise SessionAlreadyBoundConflictError from exc
        if not newly_bound:
            # 幂等重绑：身份未变化，不重复触发购物车合并。
            return bound, False

        cart_adjusted = await self._cart_merge.merge_guest_into_buyer(
            session=self._session,
            merchant_id=bound.merchant_id,
            buyer_key=buyer_key,
            guest_session_id=ctx.session_record_id,
        )
        return bound, cart_adjusted

    async def issue_merchant(
        self, mc: MerchantContext, *, issuer: str
    ) -> tuple[str, SessionContext]:
        return await self._sessions.issue_merchant(mc, issuer=issuer)

    async def revoke(self, ctx: SessionContext) -> None:
        await self._sessions.revoke(ctx)
