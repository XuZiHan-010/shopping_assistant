"""草稿暂存（PRD M10，契约 §8.13）。

草稿是商家侧所有写操作的唯一出口（D9）。本模块只负责把草案**暂存**成 `STAGED` 行；
批准与应用在 `draft_apply.py`，且只能经审批路由——这里既不产生已批准状态，
也不提供任何把草稿直接变成生效变更的入口。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Final
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import Database
from app.models.after_sales import AfterSale
from app.models.analytics import Product
from app.models.drafts import Draft
from app.schemas.v2.drafts import (
    INITIAL_DRAFT_VERSION,
    DiffUnit,
    DraftDiff,
    DraftDiffEntry,
    DraftKind,
    DraftState,
    DraftSummary,
    GuardrailCheckResult,
)
from app.tools.types import DraftProposal, ToolContext

#: §8.13.1：草稿创建后 7 天过期。
DRAFT_TTL: Final = timedelta(days=7)
#: 起草者标签；账本按它区分「Agent 起草、商家批准」（§8.13.1 `LedgerActor`）。
AGENT_ACTOR: Final = "AGENT"


@dataclass(frozen=True)
class StagedDraft:
    draft_id: str
    target_version: int


class DraftRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def stage(
        self,
        *,
        merchant_id: UUID,
        kind: DraftKind,
        title: str,
        target_type: str,
        target_id: UUID,
        target_version: int,
        payload: dict[str, Any],
        guardrail_snapshot: dict[str, Any],
        created_by: str,
        now: datetime,
        batch_id: UUID | None = None,
    ) -> Draft:
        draft = Draft(
            merchant_id=merchant_id,
            kind=kind.value,
            title=title,
            target_type=target_type,
            target_id=target_id,
            target_version=target_version,
            draft_version=INITIAL_DRAFT_VERSION,
            state=DraftState.STAGED.value,
            payload=payload,
            guardrail_snapshot=guardrail_snapshot,
            created_by=created_by,
            expires_at=now + DRAFT_TTL,
            batch_id=batch_id,
        )
        self._session.add(draft)
        await self._session.flush()
        return draft


class DatabaseDraftSink:
    """`ToolGates` 的审批闸门落点：把 `DraftProposal` 写成一行 `STAGED` 草稿。

    变更基数由**服务端此刻读到的在库量**决定，不取模型给的数字：草案里的基数决定
    应用时拿什么去比对，让模型写它等于让模型决定复检能不能通过。
    """

    def __init__(self, database: Database) -> None:
        self._database = database

    async def stage(self, ctx: ToolContext, *, kind: DraftKind, proposal: DraftProposal) -> str:
        if kind is DraftKind.RESTOCK:
            return await self._stage_restock(ctx, proposal)
        if kind is DraftKind.PRICE_CHANGE:
            return await self._stage_price_change(ctx, proposal)
        if kind is DraftKind.COUPON:
            return await self._stage_coupon(ctx, proposal)
        if kind is DraftKind.CONTENT_CHANGE:
            return await self._stage_content_change(ctx, proposal)
        if kind is DraftKind.AFTER_SALE_DECISION:
            return await self._stage_after_sale(ctx, proposal)
        # 其余种类归阶段 B / 后续版本；缺省实现会让它们静默落成空草案。
        raise NotImplementedError(f"暂不支持的草稿种类：{kind.value}")

    async def _stage_restock(self, ctx: ToolContext, proposal: DraftProposal) -> str:
        merchant_id = ctx.session.merchant_id
        product_id = UUID(proposal.target.object_id)
        delta = int(str(proposal.changes["delta"]))
        async with self._database.session() as session:
            product = await _owned_product(session, merchant_id, product_id)
            from app.services.v2.chat_write_marker import mark_committed_write

            await mark_committed_write(session, ctx, tool_name="draft_restock")
            draft = await DraftRepository(session).stage(
                merchant_id=merchant_id,
                kind=DraftKind.RESTOCK,
                title=f"补货：{product.title} +{delta}",
                target_type="PRODUCT",
                target_id=product_id,
                target_version=product.stock_on_hand,
                payload={
                    "delta": delta,
                    "base_on_hand": product.stock_on_hand,
                    "product_title": product.title,
                },
                guardrail_snapshot=_snapshot_of(proposal),
                created_by=AGENT_ACTOR,
                now=datetime.now(UTC),
            )
            draft_id = str(draft.id)
            await session.commit()
        return draft_id

    async def _stage_price_change(self, ctx: ToolContext, proposal: DraftProposal) -> str:
        merchant_id = ctx.session.merchant_id
        product_id = UUID(proposal.target.object_id)
        new_price = Decimal(str(proposal.changes["new_price"]))
        async with self._database.session() as session:
            product = await _owned_product(session, merchant_id, product_id)
            from app.services.v2.chat_write_marker import mark_committed_write

            await mark_committed_write(session, ctx, tool_name="draft_price_change")
            draft = await DraftRepository(session).stage(
                merchant_id=merchant_id,
                kind=DraftKind.PRICE_CHANGE,
                title=f"调价：{product.title} → {new_price}",
                target_type="PRODUCT",
                target_id=product_id,
                # target_version 编码为价格基数（分）：与 PriceChangeHandler 的并发比对一致。
                target_version=int(product.price * 100),
                payload={
                    "base_price": str(product.price),
                    "new_price": str(new_price),
                    "product_title": product.title,
                },
                guardrail_snapshot=_snapshot_of(proposal),
                created_by=AGENT_ACTOR,
                now=datetime.now(UTC),
            )
            draft_id = str(draft.id)
            await session.commit()
        return draft_id

    async def _stage_coupon(self, ctx: ToolContext, proposal: DraftProposal) -> str:
        """券是新建对象，没有已存在的目标：预先分配 id，`target_version` 固定为 0。"""

        merchant_id = ctx.session.merchant_id
        coupon_id = uuid4()
        changes = proposal.changes
        async with self._database.session() as session:
            from app.services.v2.chat_write_marker import mark_committed_write

            await mark_committed_write(session, ctx, tool_name="draft_coupon")
            draft = await DraftRepository(session).stage(
                merchant_id=merchant_id,
                kind=DraftKind.COUPON,
                title=f"促销券：{changes['name']}",
                target_type="COUPON",
                target_id=coupon_id,
                target_version=0,
                payload=dict(changes),
                guardrail_snapshot=_snapshot_of(proposal),
                created_by=AGENT_ACTOR,
                now=datetime.now(UTC),
            )
            draft_id = str(draft.id)
            await session.commit()
        return draft_id

    async def _stage_content_change(self, ctx: ToolContext, proposal: DraftProposal) -> str:
        """商品内容起草；`batch_id` 是否非空由工具层决定（是否传了 `batch_key`）。"""

        merchant_id = ctx.session.merchant_id
        product_id = UUID(proposal.target.object_id)
        changes = dict(proposal.changes)
        raw_batch_id = changes.pop("batch_id", None)
        batch_id = UUID(str(raw_batch_id)) if raw_batch_id is not None else None
        async with self._database.session() as session:
            product = await _owned_product(session, merchant_id, product_id)
            from app.services.v2.chat_write_marker import mark_committed_write

            await mark_committed_write(session, ctx, tool_name="draft_content_change")
            draft = await DraftRepository(session).stage(
                merchant_id=merchant_id,
                kind=DraftKind.CONTENT_CHANGE,
                title=f"商品内容更新：{product.title}",
                target_type="PRODUCT",
                target_id=product_id,
                target_version=product.content_version,
                payload={**changes, "product_title": product.title},
                guardrail_snapshot=_snapshot_of(proposal),
                created_by=AGENT_ACTOR,
                now=datetime.now(UTC),
                batch_id=batch_id,
            )
            draft_id = str(draft.id)
            await session.commit()
        return draft_id

    async def _stage_after_sale(self, ctx: ToolContext, proposal: DraftProposal) -> str:
        from app.services.v2.draft_handlers.after_sale_decision import DecisionPayload

        merchant_id = ctx.session.merchant_id
        sale_id = UUID(proposal.target.object_id)
        payload = DecisionPayload.model_validate(proposal.changes)
        async with self._database.session() as session:
            sale = await session.scalar(select(AfterSale).where(
                AfterSale.id == sale_id, AfterSale.merchant_id == merchant_id
            ))
            if sale is None:
                raise LookupError("售后事项不属于当前商家")
            from app.services.v2.chat_write_marker import mark_committed_write

            await mark_committed_write(session, ctx, tool_name="draft_after_sale_decision")
            draft = await DraftRepository(session).stage(
                merchant_id=merchant_id,
                kind=DraftKind.AFTER_SALE_DECISION,
                title=f"售后决定：{payload.decision.value}",
                target_type="AFTER_SALE",
                target_id=sale_id,
                target_version=sale.state_version,
                payload=payload.model_dump(mode="json", exclude_none=True),
                guardrail_snapshot=_snapshot_of(proposal),
                created_by=AGENT_ACTOR,
                now=datetime.now(UTC),
            )
            draft_id = str(draft.id)
            await session.commit()
        return draft_id


def _snapshot_of(proposal: DraftProposal) -> dict[str, Any]:
    """草案自带的护栏快照；形状不对就存空字典，不把未知结构塞进账面数据。"""

    snapshot = proposal.changes.get("guardrail_snapshot")
    return dict(snapshot) if isinstance(snapshot, Mapping) else {}


def to_summary(draft: Draft) -> DraftSummary:
    """ORM 行 → 契约摘要（§8.13.1）。列表与应用响应共用它，避免两处各拼一份。"""

    return DraftSummary(
        id=str(draft.id),
        kind=DraftKind(draft.kind),
        state=DraftState(draft.state),
        title=draft.title,
        draft_version=draft.draft_version,
        target_version=draft.target_version,
        batch_id=str(draft.batch_id) if draft.batch_id is not None else None,
        created_at=draft.created_at,
        updated_at=draft.updated_at,
        expires_at=draft.expires_at,
    )


def restock_entry_id(draft: Draft) -> str:
    """补货草稿只有一个差异条目，条目 ID 由草稿 ID 派生，跨读取稳定。"""

    return f"{draft.id}:stock_on_hand"


def price_change_entry_id(draft: Draft) -> str:
    return f"{draft.id}:price"


def coupon_entry_id(draft: Draft) -> str:
    return f"{draft.id}:coupon"


def content_change_entry_id(draft: Draft) -> str:
    return f"{draft.id}:content"


def after_sale_entry_id(draft: Draft) -> str:
    return f"{draft.id}:decision"


def to_diff(draft: Draft) -> DraftDiff:
    kind = DraftKind(draft.kind)
    if kind is DraftKind.RESTOCK:
        return _restock_diff(draft)
    if kind is DraftKind.PRICE_CHANGE:
        return _price_change_diff(draft)
    if kind is DraftKind.COUPON:
        return _coupon_diff(draft)
    if kind is DraftKind.AFTER_SALE_DECISION:
        return _after_sale_diff(draft)
    if kind is DraftKind.CONTENT_CHANGE:
        return _content_change_diff(draft)
    raise AssertionError(f"to_diff 未实现的草稿种类：{kind.value}")


def _restock_diff(draft: Draft) -> DraftDiff:
    payload = draft.payload
    base = int(payload["base_on_hand"])
    delta = int(payload["delta"])
    return DraftDiff(
        entries=[
            DraftDiffEntry(
                entry_id=restock_entry_id(draft),
                target_type="PRODUCT",
                target_id=str(draft.target_id),
                field="stock_on_hand",
                unit=DiffUnit.COUNT,
                before=base,
                after=base + delta,
                #: 补货不是「应用时才算」的预览，是确定的加法（`is_preview` 只许售后决定用）。
                is_preview=False,
            )
        ]
    )


def _price_change_diff(draft: Draft) -> DraftDiff:
    payload = draft.payload
    base_cents = int(Decimal(str(payload["base_price"])) * 100)
    new_cents = int(Decimal(str(payload["new_price"])) * 100)
    return DraftDiff(
        entries=[
            DraftDiffEntry(
                entry_id=price_change_entry_id(draft),
                target_type="PRODUCT",
                target_id=str(draft.target_id),
                field="price",
                unit=DiffUnit.CENTS,
                before=base_cents,
                after=new_cents,
                is_preview=False,
            )
        ]
    )


def _coupon_diff(draft: Draft) -> DraftDiff:
    payload = draft.payload
    return DraftDiff(
        entries=[
            DraftDiffEntry(
                entry_id=coupon_entry_id(draft),
                target_type="COUPON",
                target_id=str(draft.target_id),
                field="state",
                unit=DiffUnit.TEXT,
                before=None,
                after=f"{payload['kind']}:{payload['name']}",
                is_preview=False,
            )
        ]
    )


def _after_sale_diff(draft: Draft) -> DraftDiff:
    payload = draft.payload
    entries = [DraftDiffEntry(
        entry_id=after_sale_entry_id(draft),
        target_type="AFTER_SALE", target_id=str(draft.target_id),
        field="decision", unit=DiffUnit.TEXT,
        before=None, after=str(payload["decision"]), is_preview=False,
    )]
    if payload.get("rule_reference"):
        entries.append(DraftDiffEntry(
            entry_id=f"{draft.id}:rule_reference",
            target_type="AFTER_SALE", target_id=str(draft.target_id),
            field="rule_reference", unit=DiffUnit.TEXT,
            before=None, after=str(payload["rule_reference"]), is_preview=False,
        ))
    if payload.get("sellable") is not None:
        entries.append(DraftDiffEntry(
            entry_id=f"{draft.id}:sellable",
            target_type="AFTER_SALE", target_id=str(draft.target_id),
            field="sellable", unit=DiffUnit.BOOL,
            before=None, after=bool(payload["sellable"]), is_preview=False,
        ))
    if payload.get("reply_text"):
        entries.append(DraftDiffEntry(
            entry_id=f"{draft.id}:reply_text",
            target_type="AFTER_SALE", target_id=str(draft.target_id),
            field="reply_text", unit=DiffUnit.TEXT,
            before=None, after=str(payload["reply_text"]), is_preview=False,
        ))
    if payload["decision"] == "REFUND":
        entries.append(DraftDiffEntry(
            entry_id=f"{draft.id}:refund-preview",
            target_type="AFTER_SALE", target_id=str(draft.target_id),
            field="refund_amount_cents", unit=DiffUnit.CENTS,
            before=None, after=None, is_preview=True,
        ))
    return DraftDiff(entries=entries)


def _content_change_diff(draft: Draft) -> DraftDiff:
    """每个改动的属性各占一条差异条目；批量起草拆成子草稿后每份天然只涉及一个商品。"""

    payload = draft.payload
    base_attributes = payload.get("base_attributes", {})
    entries = [
        DraftDiffEntry(
            entry_id=content_change_entry_id(draft),
            target_type="PRODUCT",
            target_id=str(draft.target_id),
            field="attributes",
            unit=DiffUnit.TEXT,
            before=", ".join(f"{k}={v}" for k, v in base_attributes.items())[:2000] or None,
            after=", ".join(
                f"{name}={entry['value']}" for name, entry in payload["attributes"].items()
            )[:2000]
            or None,
            is_preview=False,
        )
    ]
    return DraftDiff(entries=entries)


def snapshot_checks(draft: Draft) -> list[GuardrailCheckResult]:
    """起草时的护栏快照；仅供展示，不构成通过承诺（§8.13.2 不变量 4）。"""

    raw = draft.guardrail_snapshot.get("checks", [])
    if not isinstance(raw, list):
        return []
    return [GuardrailCheckResult.model_validate(item) for item in raw]


def snapshot_checked_at(draft: Draft) -> datetime:
    raw = draft.guardrail_snapshot.get("checked_at")
    if isinstance(raw, str):
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            pass
    return draft.created_at


async def _owned_product(session: AsyncSession, merchant_id: UUID, product_id: UUID) -> Product:
    product = (
        await session.execute(
            select(Product).where(Product.id == product_id, Product.merchant_id == merchant_id)
        )
    ).scalar_one_or_none()
    if product is None:
        # 闸门已经拦过不属于本店的商品；这里是最后一道，也保持同一个中性失败。
        raise LookupError("商品不属于当前商家")
    return product
