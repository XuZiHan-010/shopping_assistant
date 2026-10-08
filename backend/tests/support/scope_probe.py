"""仅测试可见的越权探针：真实 `require_owned()`、真实异常处理器、真实 PostgreSQL。

订单、草稿和售后等 v2 业务路由不在 N1 D 计划内实现，本模块借用既有 `products` /
`orders` 表证明 `resource_scope.require_owned()` 与双重过滤这两条安全属性可以被
测试覆盖。**本模块不得被 `app/` 导入，也不得挂进生产路由**；业务 v2 路由各自
落地时，必须把同一套断言复制到真实端点，这里的探针通过不能替代业务路由验收。
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db_session
from app.api.session_deps import get_session_audit_repository, require_merchant_session
from app.core.session import SessionContext
from app.models.analytics import Order, Product
from app.repositories.audit import AuditRepository
from app.services.resource_scope import ScopeLookupResult, require_owned


class ScopeProbeRepository:
    """临时表 Repository：复用既有 `products` / `orders` 表做真实约束验证。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def fetch_product_for_merchant(
        self, product_id: UUID, merchant_id: UUID
    ) -> ScopeLookupResult[Product]:
        """一条固定形状 SQL：无论缺失还是跨商家都只做一次按主键的查询。"""

        row = (
            await self._session.execute(select(Product).where(Product.id == product_id))
        ).scalar_one_or_none()
        if row is None:
            return ScopeLookupResult(resource=None, target_exists=False)
        if row.merchant_id != merchant_id:
            return ScopeLookupResult(resource=None, target_exists=True)
        return ScopeLookupResult(resource=row, target_exists=True)

    async def list_orders_for_customer(self, *, merchant_id: UUID, buyer_key: str) -> list[Order]:
        """D7①：订单查询强制 `merchant_id` + `buyer_key` 双重过滤，跨店也要挡。"""

        rows = (
            (
                await self._session.execute(
                    select(Order).where(
                        Order.merchant_id == merchant_id, Order.buyer_key == buyer_key
                    )
                )
            )
            .scalars()
            .all()
        )
        return list(rows)


def mount_scope_probe(app: FastAPI) -> None:
    """把 `/scope-probe/{resource_id}` 挂到给定的测试用 FastAPI 应用上。"""

    @app.get("/scope-probe/{resource_id}")
    async def scope_probe(
        request: Request,
        resource_id: UUID,
        ctx: Annotated[SessionContext, Depends(require_merchant_session)],
        session: Annotated[AsyncSession, Depends(get_db_session)],
        audits: Annotated[AuditRepository, Depends(get_session_audit_repository)],
    ) -> dict[str, str]:
        repo = ScopeProbeRepository(session)
        product = await require_owned(
            lambda: repo.fetch_product_for_merchant(resource_id, ctx.merchant_id),
            ctx=ctx,
            audits=audits,
            resource_type="product",
            resource_id=str(resource_id),
            request_id=str(request.state.request_id),
        )
        return {"id": str(product.id)}
