"""草稿处理器协议与分派表（N3 阶段 A Task 5，契约 §8.13.2）。

`DraftApplyService` 只保留一份事务骨架（锁 → 状态 → 过期 → 草案版本 → 证据 → 置 APPLIED → 账本）；
第 5–7 步——目标对象复检、按当时生效的护栏复检、条件写入与领域事件——随草稿种类不同，
由这里注册的处理器执行。B 注册 `AFTER_SALE_DECISION`，C 注册 `CONTENT_CHANGE` / `PRICE_CHANGE` /
`COUPON`；如果各自再抄一份骨架，证据消费与回滚顺序迟早分叉。

处理器的三条硬约束：

- **不得提交事务**：提交由路由在整个应用成功后统一做，处理器失败时证据消费随之回滚；
- **不得消费证据**：证据在骨架里验证并消费，处理器拿到的 `HandlerRequest` 在结构上就没有证据字段；
- **不得推进草稿状态、不得写账本**：两者由骨架在处理器成功返回后统一写。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Literal, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.session import SessionContext
from app.localization.locales import SupportedLocale
from app.models.drafts import Draft
from app.schemas.v2.drafts import DraftKind, GuardrailCheckResult

#: 已开放的草稿种类：启动自检保证它们都有处理器。B、C 注册处理器时同步加入对应种类。
ENABLED_DRAFT_KINDS: Final = frozenset(
    {
        DraftKind.RESTOCK,
        DraftKind.PRICE_CHANGE,
        DraftKind.COUPON,
        DraftKind.AFTER_SALE_DECISION,
        DraftKind.CONTENT_CHANGE,
    }
)


@dataclass(frozen=True)
class HandlerRequest:
    """`DraftApplyRequest` 去掉审批证据与幂等键后的业务输入。

    用专用类型而不是 `model_copy(update={"approval_evidence": None})`：后者得到的仍是
    `DraftApplyRequest`，证据字段依然存在（只是为空），还违反它「证据必填」的契约。
    """

    draft_version: int
    target_version: int
    accepted_entry_ids: tuple[str, ...] | None


#: `applied_entry_ids` 的条数上限，与契约 §8.13 `ChangeLedgerEntry` 一致。
_MAX_APPLIED_ENTRIES: Final = 100


@dataclass(frozen=True)
class HandlerResult:
    """处理器的成功结果。构造时即核对契约：处理器写错当场失败，不等到序列化响应才暴露。"""

    checks: list[GuardrailCheckResult]  # 按当时生效护栏复检的结果
    applied_entry_ids: list[str]  # 进入账本 applied_entry_ids 的公开 ID，1–100 项、不重复
    #: 骨架总是把草稿置 APPLIED，账本结果只能与之一致；失败必须抛异常回滚，而不是返回别的结果值。
    ledger_result: Literal["APPLIED"] = "APPLIED"

    def __post_init__(self) -> None:
        if self.ledger_result != "APPLIED":
            raise ValueError("HandlerResult.ledger_result 只能是 APPLIED；失败请抛异常回滚")
        entries = self.applied_entry_ids
        if not 1 <= len(entries) <= _MAX_APPLIED_ENTRIES or len(set(entries)) != len(entries):
            raise ValueError(
                f"HandlerResult.applied_entry_ids 须为 1–{_MAX_APPLIED_ENTRIES} 个不重复的 ID"
            )


class DraftHandler(Protocol):
    kind: DraftKind

    async def apply(
        self,
        session: AsyncSession,
        ctx: SessionContext,
        draft: Draft,
        request: HandlerRequest,
        *,
        now: datetime,
        locale: SupportedLocale,
    ) -> HandlerResult:
        """第 5–7 步：目标版本复检、护栏复检、条件写入与领域事件。不得提交事务、不得消费证据。"""
        ...


def build_handler_table(handlers: Iterable[DraftHandler]) -> Mapping[DraftKind, DraftHandler]:
    """同一种类注册两次 → 启动失败。"""

    table: dict[DraftKind, DraftHandler] = {}
    for handler in handlers:
        if handler.kind in table:
            raise ValueError(f"草稿种类 {handler.kind.value} 的处理器重复注册")
        table[handler.kind] = handler
    return table


def check_enabled(table: Mapping[DraftKind, DraftHandler]) -> None:
    """已开放的种类缺处理器是部署缺陷：在启动期失败，而不是等商家点「批准」时才 500。"""

    missing = sorted(kind.value for kind in ENABLED_DRAFT_KINDS if kind not in table)
    if missing:
        raise RuntimeError(f"已开放的草稿种类缺少处理器：{', '.join(missing)}")


def default_handlers() -> tuple[DraftHandler, ...]:
    from app.services.v2.draft_handlers.after_sale_decision import AfterSaleDecisionHandler
    from app.services.v2.draft_handlers.content_change import ContentChangeHandler
    from app.services.v2.draft_handlers.coupon import CouponHandler
    from app.services.v2.draft_handlers.price_change import PriceChangeHandler
    from app.services.v2.draft_handlers.restock import RestockHandler

    return (
        RestockHandler(),
        PriceChangeHandler(),
        CouponHandler(),
        AfterSaleDecisionHandler(),
        ContentChangeHandler(),
    )


def default_handler_table() -> Mapping[DraftKind, DraftHandler]:
    table = build_handler_table(default_handlers())
    check_enabled(table)
    return table
