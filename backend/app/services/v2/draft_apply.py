"""草稿应用事务（PRD §7.3、契约 §8.13.2、§8.7.9）——模块 C 的核心。

事务内的步骤顺序是**固定的**，不为了方便调整：

```text
0. 归属检查（路由层 require_owned）：不属于本商家 → 403，不进入后续
1. 幂等查询：命中 → 原样返回第一次结果（网络重试不是重放）
BEGIN
  2. SELECT ... FOR UPDATE：状态必须 STAGED；已过期 → 同事务内置为 EXPIRED 并 409
  3. 草案版本比对 → 409 VERSION_CONFLICT(DRAFT)
  4. 验证并消费审批证据 → 422 CONFIRMATION_REQUIRED
  5. 目标对象复检 → 409 VERSION_CONFLICT(TARGET)          ┐
  6. 按当时生效的护栏复检 → 422 GUARDRAIL_REJECTED           ├ 按草稿种类分派给处理器
  7. 条件写入 → 追加领域事件                                  ┘（`draft_handlers/`）
  8. 草稿置 APPLIED → 写账本
COMMIT
```

第 5–7 步由按种类注册的处理器执行（N3 阶段 A Task 5）：骨架只写这一份，B、C 新增的草稿种类
只注册处理器，不再各抄一份骨架。处理器拿到的请求里没有证据字段，不提交事务、不推进状态。
表里没有该种类是部署缺陷，不是用户错误：抛 `RuntimeError`（→ 500），且在消费证据之前抛。

第 4–7 步任一不过就整体回滚：**证据消费随之回滚，草稿保持 `STAGED`**。
如果证据在另一个事务里消费，就会出现"证据作废了但业务没生效"，用户只能重新取证据。

**失败不推进状态**（PRD §7.3 不变量 3）：这里没有"处理中"这类中间态可以忘记改回去。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import (
    DraftExpiredError,
    IllegalStateTransitionError,
    VersionConflictError,
)
from app.core.session import SessionContext
from app.db.session import Database
from app.localization.locales import SupportedLocale
from app.models.drafts import ChangeLedger, Draft
from app.repositories.v2.operation_evidence import OperationEvidenceRepository
from app.schemas.v2.drafts import (
    ChangeLedgerEntry,
    DraftApplyRequest,
    DraftApplyResponse,
    DraftKind,
    DraftState,
    LedgerActor,
)
from app.services.v2.approval_evidence import ApprovalBinding, ApprovalEvidenceService
from app.services.v2.draft_handlers import (
    DraftHandler,
    HandlerRequest,
    HandlerResult,
    default_handler_table,
)
from app.services.v2.drafts import AGENT_ACTOR, to_summary

#: 分派表在导入期构建并自检（重复注册、已开放种类缺处理器都让服务起不来）。
HANDLERS: Final[Mapping[DraftKind, DraftHandler]] = default_handler_table()


@dataclass(frozen=True)
class ApplyActors:
    """谁起草、谁批准。批准者永远是当前商家会话，不接受请求体自报。"""

    drafted_by: LedgerActor
    approved_by: LedgerActor


class DraftApplyService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        database: Database,
        evidence: ApprovalEvidenceService,
        ctx: SessionContext,
        locale: SupportedLocale = SupportedLocale.ZH_CN,
        handlers: Mapping[DraftKind, DraftHandler] | None = None,
    ) -> None:
        self._session = session
        self._database = database
        self._evidence = evidence
        self._ctx = ctx
        self._locale = locale
        self._handlers = HANDLERS if handlers is None else handlers

    async def apply(
        self, draft_id: UUID, payload: DraftApplyRequest, *, now: datetime | None = None
    ) -> DraftApplyResponse:
        moment = now or datetime.now(UTC)
        draft = await self._lock(draft_id)
        self._check_state(draft, moment)
        await self._check_expiry(draft, moment)
        if draft.draft_version != payload.draft_version:
            raise VersionConflictError(scope="DRAFT")
        handler = self._handler(draft)
        await self._consume_evidence(draft, payload, moment)
        result = await handler.apply(
            self._session,
            self._ctx,
            draft,
            _handler_request(payload),
            now=moment,
            locale=self._locale,
        )
        ledger = await self._record_applied(draft, result, moment)
        return self._response(draft, ledger, result, moment)

    # --- 步骤 --------------------------------------------------------------------

    async def _lock(self, draft_id: UUID) -> Draft:
        """锁住草稿行：并发的第二个请求要等第一个提交后才能读到新状态。

        `populate_existing=True` 是必须的：路由层的归属检查已经用同一个 Session 读过一次这个
        草稿（见 `merchant_drafts.py` 的 `require_owned()`），身份映射里已经有一个 `Draft` 对象。
        没有这个选项时，`FOR UPDATE` 拿到锁后仍会返回身份映射里的旧属性，而不是解锁后数据库里
        的最新值——另一个事务把状态改成 `DISCARDED` 并提交后，这里读到的还会是旧的 `STAGED`，
        导致已丢弃的草稿被重新应用。
        """

        draft = (
            await self._session.execute(
                select(Draft)
                .where(Draft.id == draft_id, Draft.merchant_id == self._ctx.merchant_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if draft is None:
            # 归属检查已在路由层做过；走到这里说明并发删除，对外仍是同一中性结构。
            raise IllegalStateTransitionError(details=[{"state": DraftState.DISCARDED.value}])
        return draft

    def _check_state(self, draft: Draft, now: datetime) -> None:
        del now
        if draft.state != DraftState.STAGED.value:
            raise IllegalStateTransitionError(details=[{"state": draft.state}])

    async def _check_expiry(self, draft: Draft, now: datetime) -> None:
        """过期由业务路径自检，不依赖清理任务是否已跑（§8.13.2）。

        状态迁移写在**当前事务**里，由路由在抛出 409 之前提交（见 `apply_draft`）：
        不能开第二个连接去改，那一行此刻正被本事务的 `FOR UPDATE` 锁着，
        另一个连接只会一直等到超时。这一步之前还没有消费任何证据，提交是安全的。
        """

        if now < draft.expires_at:
            return
        draft.state = DraftState.EXPIRED.value
        await self._session.flush()
        raise DraftExpiredError

    async def _consume_evidence(
        self, draft: Draft, payload: DraftApplyRequest, now: datetime
    ) -> None:
        binding = ApprovalBinding(
            session_record_id=str(self._ctx.session_record_id),
            merchant_id=str(self._ctx.merchant_id),
            draft_id=str(draft.id),
            draft_version=draft.draft_version,
            target_version=payload.target_version,
        )
        verified = self._evidence.verify(payload.approval_evidence, binding, now=now)
        consumed = await OperationEvidenceRepository(self._session).consume(
            purpose=self._evidence.purpose, nonce=verified.nonce, now=now
        )
        if not consumed:
            self._evidence.reject_consumed()

    def _handler(self, draft: Draft) -> DraftHandler:
        """查分派表；未注册的种类是部署缺陷（→ 500），在消费证据之前失败。"""

        try:
            return self._handlers[DraftKind(draft.kind)]
        except (KeyError, ValueError):
            raise RuntimeError(f"草稿种类 {draft.kind} 没有注册处理器") from None

    async def _record_applied(
        self, draft: Draft, result: HandlerResult, now: datetime
    ) -> ChangeLedger:
        draft.state = DraftState.APPLIED.value
        ledger = ChangeLedger(
            merchant_id=self._ctx.merchant_id,
            draft_id=draft.id,
            drafted_by=draft.created_by,
            approved_by=self._approver(),
            approved_at=now,
            guardrail_results={
                "checks": [check.model_dump(mode="json") for check in result.checks]
            },
            result=result.ledger_result,
        )
        self._session.add(ledger)
        await self._session.flush()
        # `updated_at` 由数据库的 onupdate 产生，flush 后是过期属性；显式刷新，
        # 否则序列化响应时会在异步上下文外触发一次同步取值。
        await self._session.refresh(draft)
        return ledger

    # --- 输出 --------------------------------------------------------------------

    def _approver(self) -> str:
        """批准者是当前商家会话；展示名不含会话或 Token 标识（§8.13.1）。"""

        return "MERCHANT"

    def _response(
        self,
        draft: Draft,
        ledger: ChangeLedger,
        result: HandlerResult,
        now: datetime,
    ) -> DraftApplyResponse:
        return DraftApplyResponse(
            draft=to_summary(draft),
            ledger_entry=ChangeLedgerEntry(
                id=str(ledger.id),
                draft_id=str(draft.id),
                kind=DraftKind(draft.kind),
                drafted_by=LedgerActor(
                    actor_type="AGENT" if draft.created_by == AGENT_ACTOR else "MERCHANT",
                    label=_actor_label(draft.created_by),
                ),
                approved_by=LedgerActor(actor_type="MERCHANT", label="商家"),
                approved_at=now,
                applied_entry_ids=list(result.applied_entry_ids),
                guardrail_results=result.checks,
            ),
        )


def _handler_request(payload: DraftApplyRequest) -> HandlerRequest:
    """去掉证据与幂等键：处理器在结构上就拿不到证据。"""

    return HandlerRequest(
        draft_version=payload.draft_version,
        target_version=payload.target_version,
        accepted_entry_ids=(
            None if payload.accepted_entry_ids is None else tuple(payload.accepted_entry_ids)
        ),
    )


def _actor_label(created_by: str) -> str:
    return "经营助手" if created_by == AGENT_ACTOR else "商家"


def serialize(response: DraftApplyResponse) -> dict[str, Any]:
    """幂等记录里存的是可直接回放的响应体。"""

    return response.model_dump(mode="json")
