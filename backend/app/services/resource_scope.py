"""统一的越权判定：目标不存在与目标不属于当前主体走同一条 403 路径（R5、O1）。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from app.core.errors import ResourceForbiddenError
from app.core.session import SessionContext
from app.repositories.protocols import AuditRepositoryProtocol


@dataclass(frozen=True)
class ScopeLookupResult[T]:
    """一次固定形状查询的结果：`resource` 决定放行，`target_exists` 只供审计。"""

    resource: T | None
    #: `True`——目标存在但不属于当前主体；`False`——目标确实不存在；
    #: `None`——该仓储只能判定"不可见"，无法进一步区分原因。
    target_exists: bool | None


async def require_owned[T](
    fetch: Callable[[], Awaitable[ScopeLookupResult[T]]],
    *,
    ctx: SessionContext,
    audits: AuditRepositoryProtocol,
    resource_type: str,
    resource_id: str,
    request_id: str,
) -> T:
    """一次固定查询定生死；对外统一 403，不二次探测存在性。

    `fetch()` 必须是**唯一**一次数据库往返，且不存在与不属于当前主体两条路径
    要执行完全相同形状的查询——不允许"先查存在性、不存在就早退"，那样的早退
    路径天然更快，会构成时序侧信道（PRD §12.1）。
    """

    result = await fetch()
    if result.resource is not None:
        return result.resource

    if result.target_exists is True:
        reason = "FOREIGN"
    elif result.target_exists is False:
        reason = "MISSING"
    else:
        reason = "NOT_VISIBLE"

    await audits.record_event(
        merchant_id=ctx.merchant_id,
        event_type="RESOURCE_SCOPE_VIOLATION",
        resource_type=resource_type,
        resource_id=resource_id,
        request_id=request_id,
        metadata={"reason": reason},
    )
    raise ResourceForbiddenError
