"""草稿审批与变更账本（PRD M10，契约 §8.13.3）。

四条路由，**没有第五条**：没有「批准」端点，也没有任何工具能走到这里。
批准是 `apply` 的入参，不是可以先置上、之后再复用的状态（§8.13.1 `DraftState` 没有 `APPROVED`）。

`GET /drafts/{draft_id}` 是审批证据的**唯一**签发点，因此它 `Cache-Control: no-store`，
并且每次读取都签发一枚新的一次性 nonce。
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BeforeValidator
from sqlalchemy import false as sa_false
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import (
    get_database,
    get_db_session,
    get_principal_secret,
    get_request_locale,
)
from app.api.session_deps import require_merchant_session
from app.api.v2_deps import get_approval_evidence_service, get_cursor_codec, merchant_cursor_scope
from app.core.errors import (
    ConfirmationRequiredError,
    DraftExpiredError,
    IllegalStateTransitionError,
    error_responses,
)
from app.core.session import SessionContext
from app.db.session import Database
from app.localization.locales import SupportedLocale
from app.models.drafts import Draft
from app.repositories.audit import AuditRepository
from app.repositories.v2.idempotency import IdempotencyRepository
from app.repositories.v2.operation_evidence import OperationEvidenceRepository
from app.schemas.v2.common import CursorPage
from app.schemas.v2.drafts import (
    DraftApplyRequest,
    DraftApplyResponse,
    DraftDetailResponse,
    DraftKind,
    DraftState,
    DraftSummary,
)
from app.services.resource_scope import ScopeLookupResult, require_owned
from app.services.v2.approval_evidence import ApprovalBinding, ApprovalEvidenceService
from app.services.v2.cursor import CursorCodec
from app.services.v2.draft_apply import DraftApplyService
from app.services.v2.drafts import snapshot_checked_at, snapshot_checks, to_diff, to_summary
from app.services.v2.idempotency import run_idempotent

router = APIRouter(prefix="/v2/merchant", tags=["v2-merchant-drafts"])

APPLY_OPERATION = "merchant.drafts.apply"
RESOURCE_TYPE = "draft"


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


def _request_id(request: Request) -> str:
    return str(getattr(request.state, "request_id", "unknown"))


async def _require_owned_draft(
    request: Request,
    session: AsyncSession,
    database: Database,
    ctx: SessionContext,
    draft_id: UUID,
) -> Draft:
    """归属检查是第 0 步：不属于本商家的草稿，连存在与否都不暴露（R5、O1）。"""

    async def fetch() -> ScopeLookupResult[Draft]:
        # 一次固定形状的查询：存在但不属于我、与根本不存在，走同样的代价与同样的响应。
        row = (
            await session.execute(select(Draft).where(Draft.id == draft_id))
        ).scalar_one_or_none()
        if row is None:
            return ScopeLookupResult(resource=None, target_exists=False)
        if row.merchant_id != ctx.merchant_id:
            return ScopeLookupResult(resource=None, target_exists=True)
        return ScopeLookupResult(resource=row, target_exists=True)

    return await require_owned(
        fetch,
        ctx=ctx,
        audits=AuditRepository(database),
        resource_type=RESOURCE_TYPE,
        resource_id=str(draft_id),
        request_id=_request_id(request),
    )


@router.get(
    "/drafts",
    response_model=CursorPage[DraftSummary],
    responses=error_responses(401, 403, 422, 503),
)
async def list_drafts(
    ctx: Annotated[SessionContext, Depends(require_merchant_session)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    codec: Annotated[CursorCodec, Depends(get_cursor_codec)],
    principal_secret: Annotated[bytes, Depends(get_principal_secret)],
    locale: Annotated[SupportedLocale, Depends(get_request_locale)],
    cursor: Annotated[str | None, Query(min_length=1, max_length=2048)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    state: DraftState = DraftState.STAGED,
    kind: DraftKind | None = None,
    batch_id: Annotated[str | None, Query(min_length=1, max_length=128)] = None,
) -> CursorPage[DraftSummary]:
    """只列本店草稿；排序 `created_at DESC, id DESC`，证据字段不出现在列表里。

    `batch_id`（N3 阶段 C）供审批界面按批次分组查看商品内容批量草稿；不是合法 UUID
    时按「该批次没有任何草稿」处理（结果为空），不是 422——`batch_id` 是从其他草稿的
    `batch_id` 字段原样复制来的查询参数，格式错误更可能是客户端传参笔误，不必致命。
    """

    statement = select(Draft).where(
        Draft.merchant_id == ctx.merchant_id, Draft.state == state.value
    )
    if kind is not None:
        statement = statement.where(Draft.kind == kind.value)
    if batch_id is not None:
        try:
            parsed_batch_id = UUID(batch_id)
        except ValueError:
            # 格式不对的 batch_id 必然查不到任何草稿：不能落成 `Draft.batch_id IS NULL`，
            # 那会意外匹配所有没有批次的草稿。false 是一个恒不成立的 WHERE 子句。
            statement = statement.where(sa_false())
        else:
            statement = statement.where(Draft.batch_id == parsed_batch_id)
    rows = list(
        (await session.execute(statement.order_by(Draft.created_at.desc(), Draft.id.desc())))
        .scalars()
        .all()
    )
    scope = merchant_cursor_scope(
        ctx,
        endpoint="merchant.drafts.list",
        resource="DRAFT",
        filters={
            "state": state.value,
            "kind": kind.value if kind else None,
            "batch_id": batch_id,
        },
        locale=locale,
        limit=limit,
        secret=principal_secret,
    )
    page = codec.page(
        rows,
        key=lambda draft: _sort_key(draft),
        scope=scope,
        cursor=cursor,
        now=datetime.now(UTC),
    )
    return CursorPage[DraftSummary](
        items=[to_summary(draft) for draft in page.items],
        next_cursor=page.next_cursor,
        has_more=page.has_more,
    )


def _sort_key(draft: Draft) -> tuple[str, ...]:
    """降序排列用「取反」的方式表达：游标比较统一按升序，键本身取补。"""

    return (_descending(draft.created_at.isoformat()), _descending(str(draft.id)))


def _descending(value: str) -> str:
    # keyset 分页统一按 `>` 比较；降序字段先按字符取补，让字典序与业务序一致。
    return "".join(chr(0x10FFFF - ord(char)) for char in value)


@router.get(
    "/drafts/{draft_id}",
    response_model=DraftDetailResponse,
    responses=error_responses(401, 403, 422, 503),
)
async def get_draft(
    draft_id: UUID,
    request: Request,
    response: Response,
    ctx: Annotated[SessionContext, Depends(require_merchant_session)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    database: Annotated[Database, Depends(get_database)],
    evidence: Annotated[ApprovalEvidenceService, Depends(get_approval_evidence_service)],
) -> DraftDetailResponse:
    """`STAGED` 草稿每次读取都签发一枚新的一次性证据；其余状态两个证据字段都是 null。"""

    draft = await _require_owned_draft(request, session, database, ctx, draft_id)
    _no_store(response)
    now = datetime.now(UTC)
    token: str | None = None
    expires_at: datetime | None = None
    if draft.state == DraftState.STAGED.value and now >= draft.expires_at:
        # §8.13.2：**读取**时也自检过期，并把状态迁过去。留着 STAGED 不迁，
        # 契约模型会要求给它签发证据，而过期草稿恰恰不能有证据。
        draft.state = DraftState.EXPIRED.value
        await session.commit()
        # `updated_at` 由 onupdate 产生，提交后是过期属性，序列化前先刷新。
        await session.refresh(draft)
    if draft.state == DraftState.STAGED.value:
        issued = evidence.issue(
            ApprovalBinding(
                session_record_id=str(ctx.session_record_id),
                merchant_id=str(ctx.merchant_id),
                draft_id=str(draft.id),
                draft_version=draft.draft_version,
                target_version=draft.target_version,
            ),
            now=now,
        )
        await OperationEvidenceRepository(session).register(
            purpose=evidence.purpose,
            nonce=issued.nonce,
            issued_at=now,
            expires_at=issued.expires_at,
        )
        await session.commit()
        token, expires_at = issued.token, issued.expires_at
    summary = to_summary(draft)
    return DraftDetailResponse(
        **summary.model_dump(),
        diff=to_diff(draft),
        guardrail_checks=snapshot_checks(draft),
        guardrails_checked_at=snapshot_checked_at(draft),
        approval_evidence=token,
        approval_evidence_expires_at=expires_at,
    )


#: 证据的合法字符集，与 §8.13.1 的 `ApprovalEvidence` 一致。
_EVIDENCE_CHARSET = re.compile(r"^[A-Za-z0-9._~-]{1,2048}$")


async def require_apply_scope(
    request: Request,
    draft_id: UUID,
    ctx: Annotated[SessionContext, Depends(require_merchant_session)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    database: Annotated[Database, Depends(get_database)],
) -> None:
    await _require_owned_draft(request, session, database, ctx, draft_id)


def _defer_evidence_validation(raw: Any) -> Any:
    """先校验业务输入；证据原值在 execute 中校验，使幂等重放先于证据检查。

    只给内部模型填合法占位符，保留请求原文；新操作绝不能用占位符进入应用服务。
    对外仍保留 DraftApplyRequest 的证据字段契约。
    """
    if isinstance(raw, dict):
        evidence = raw.get("approval_evidence")
        if not isinstance(evidence, str) or not _EVIDENCE_CHARSET.fullmatch(evidence):
            return {**raw, "approval_evidence": "invalid"}
    return raw


async def require_evidence_field(request: Request) -> None:
    """证据**缺失**必须和证据无效长得一样（§8.7.9）。

    如果交给 Pydantic 的必填校验，缺字段会得到 `INVALID_REQUEST`、带上
    「approval_evidence 是必填项」的 details，而伪造的证据得到中性的
    `CONFIRMATION_REQUIRED`——两者一比就知道服务端是在哪一步拒绝的。
    内部模型推迟该字段的校验；此守卫只在幂等 execute 分支读取原文，统一拒绝无效证据。
    """

    try:
        raw = await request.json()
    except ValueError:
        return  # 请求体本身就不是 JSON，交给常规校验报 INVALID_REQUEST
    if not isinstance(raw, dict):
        return
    evidence = raw.get("approval_evidence")
    if not isinstance(evidence, str) or not _EVIDENCE_CHARSET.fullmatch(evidence):
        raise ConfirmationRequiredError


@router.post(
    "/drafts/{draft_id}/apply",
    response_model=DraftApplyResponse,
    responses=error_responses(401, 403, 409, 422, 503),
)
async def apply_draft(
    draft_id: UUID,
    payload: Annotated[DraftApplyRequest, BeforeValidator(_defer_evidence_validation)],
    request: Request,
    response: Response,
    _owned: Annotated[None, Depends(require_apply_scope)],
    ctx: Annotated[SessionContext, Depends(require_merchant_session)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    database: Annotated[Database, Depends(get_database)],
    evidence: Annotated[ApprovalEvidenceService, Depends(get_approval_evidence_service)],
    principal_secret: Annotated[bytes, Depends(get_principal_secret)],
    locale: Annotated[SupportedLocale, Depends(get_request_locale)],
) -> Any:
    """步骤顺序固定：归属 → 幂等 → 锁草稿 → 证据 → 基数 → 护栏 → 写入（§8.7.9）。"""

    await _require_owned_draft(request, session, database, ctx, draft_id)
    _no_store(response)

    async def execute() -> dict[str, Any]:
        await require_evidence_field(request)
        service = DraftApplyService(
            session, database=database, evidence=evidence, ctx=ctx, locale=locale
        )
        result = await service.apply(draft_id, payload)
        return result.model_dump(mode="json")

    try:
        body = await run_idempotent(
            repo=IdempotencyRepository(session),
            ctx=ctx,
            secret=principal_secret,
            operation=APPLY_OPERATION,
            client_request_id=payload.client_request_id,
            # 请求摘要只取业务输入，排除短期证据（§8.7.3）。
            request_digest=_apply_digest(draft_id, payload),
            response_status=200,
            execute=execute,
        )
    except DraftExpiredError:
        # 唯一一条「失败仍要落盘」的路径：过期判定本身是状态迁移，必须留下来，
        # 否则下一次请求又要重新判一遍，且草稿会一直停在 STAGED（§8.13.2）。
        # 此时还没有消费任何证据，提交不会吃掉用户手里的那一份。
        await session.commit()
        raise
    await session.commit()
    return body


def _apply_digest(draft_id: UUID, payload: DraftApplyRequest) -> str:
    from hashlib import sha256

    entries = (
        "ALL"
        if payload.accepted_entry_ids is None
        else ",".join(sorted(set(payload.accepted_entry_ids)))
    )
    raw = f"{draft_id}:{payload.draft_version}:{payload.target_version}:{entries}"
    return sha256(raw.encode()).hexdigest()


@router.delete(
    "/drafts/{draft_id}",
    status_code=204,
    responses=error_responses(401, 403, 409, 422, 503),
)
async def discard_draft(
    draft_id: UUID,
    request: Request,
    ctx: Annotated[SessionContext, Depends(require_merchant_session)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    database: Annotated[Database, Depends(get_database)],
) -> None:
    """只允许 `STAGED → DISCARDED`；对已丢弃的草稿重复请求仍返回 204（DELETE 天然幂等）。"""

    draft = await _require_owned_draft(request, session, database, ctx, draft_id)
    # 读取归属后再锁定并刷新，避免并发 apply 后仍以旧的 STAGED 覆写终态。
    await session.refresh(draft, with_for_update=True)
    if draft.state == DraftState.DISCARDED.value:
        return
    if draft.state != DraftState.STAGED.value:
        raise IllegalStateTransitionError(details=[{"state": draft.state}])
    draft.state = DraftState.DISCARDED.value
    await session.commit()
