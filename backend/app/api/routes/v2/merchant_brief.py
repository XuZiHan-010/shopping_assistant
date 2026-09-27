"""当日简报（PRD M2 完整集，契约 §8.12.2、§8.12.3）：读取与限流重新生成。

`GET /current` 优先读已存储的当日简报；尚无存储时现算并以 `SCHEDULED` 落为第 1 版
再返回（不返回 404——定时任务默认关闭，若严格 404 商家在首次手动重新生成前将永远
看不到任何简报，2026-09-26 修正契约措辞）。`POST /regenerate` 走幂等 + 冷却双重限制：
同一 `client_request_id` 重放直接回放首次结果（§8.7.3）；冷却期内的新请求返回
429（D18⑨），不产生新版本，也不做任何工具或模型调用。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db_session, get_principal_secret
from app.api.session_deps import require_merchant_session
from app.core.errors import RateLimitedError, error_responses
from app.core.session import SessionContext
from app.models.drafts import Draft
from app.repositories.v2.daily_brief import DailyBriefRepository
from app.repositories.v2.idempotency import IdempotencyRepository
from app.repositories.v2.inventory import InventoryReadRepository
from app.schemas.v2.drafts import DraftState
from app.schemas.v2.merchant_ops import (
    MAX_BRIEF_ITEMS,
    BriefRegenerateRequest,
    DailyBriefResponse,
)
from app.services.v2.customer_signals import list_signals
from app.services.v2.daily_brief import (
    build_full_brief,
    business_date_for,
    is_in_regenerate_cooldown,
)
from app.services.v2.idempotency import run_idempotent
from app.services.v2.inventory_alerts import AlertRules, alerts_for

router = APIRouter(prefix="/v2/merchant", tags=["v2-merchant-brief"])


async def _current_facts(
    session: AsyncSession, ctx: SessionContext, *, now: datetime
) -> DailyBriefResponse:
    """按 D18① 现算：事实只来自本轮授权工具结果，昨天的简报本身不进数字来源。"""

    facts = await InventoryReadRepository(session).facts_for_merchant(ctx.merchant_id, now=now)
    alerts = alerts_for(facts, rules=AlertRules(), now=now)
    drafts = list(
        (
            await session.execute(
                select(Draft)
                .where(
                    Draft.merchant_id == ctx.merchant_id,
                    Draft.state == DraftState.STAGED.value,
                    Draft.expires_at > now,
                )
                .order_by(Draft.created_at.desc(), Draft.id.desc())
                .limit(MAX_BRIEF_ITEMS * 2)
            )
        )
        .scalars()
        .all()
    )
    signals = await list_signals(session, ctx)
    return build_full_brief(alerts=alerts, drafts=drafts, signals=signals, now=now)


@router.get(
    "/briefs/daily/current",
    response_model=DailyBriefResponse,
    responses=error_responses(401, 403, 422, 503),
)
async def get_current_brief(
    ctx: Annotated[SessionContext, Depends(require_merchant_session)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> DailyBriefResponse:
    now = datetime.now(UTC)
    repo = DailyBriefRepository(session)
    business_date = business_date_for(now)
    await repo.lock_business_day(ctx.merchant_id, business_date=business_date)
    stored = await repo.get_current(ctx.merchant_id, business_date=business_date)
    if stored is not None:
        return DailyBriefResponse.model_validate(stored.payload)

    brief = await _current_facts(session, ctx, now=now)
    row = await repo.stage_or_replace(ctx.merchant_id, business_date=business_date, response=brief)
    await session.commit()
    return DailyBriefResponse.model_validate(row.payload)


@router.post(
    "/briefs/daily/current/regenerate",
    response_model=DailyBriefResponse,
    responses=error_responses(401, 403, 409, 422, 429, 503),
)
async def regenerate_current_brief(
    payload: BriefRegenerateRequest,
    request: Request,
    ctx: Annotated[SessionContext, Depends(require_merchant_session)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    secret: Annotated[bytes, Depends(get_principal_secret)],
) -> DailyBriefResponse:
    del request
    now = datetime.now(UTC)
    repo = DailyBriefRepository(session)
    business_date = business_date_for(now)

    async def execute() -> dict[str, object]:
        await repo.lock_business_day(ctx.merchant_id, business_date=business_date)
        existing = await repo.get_current(ctx.merchant_id, business_date=business_date)
        # 冷却只限制"连续点击重新生成"本身：`GET /current` 的隐式首次生成
        # （`trigger=SCHEDULED`）不消耗冷却额度，否则商家进页面自动生成第 1 版后
        # 立刻手动点一次重新生成会被凭空拒绝——那不是用户在滥用重新生成。
        last_regenerated_at = (
            existing.generated_at
            if existing is not None and existing.payload.get("trigger") == "REGENERATED"
            else None
        )
        if is_in_regenerate_cooldown(last_regenerated_at, now=now):
            raise RateLimitedError
        brief = await _current_facts(session, ctx, now=now)
        regenerated = brief.model_copy(update={"trigger": "REGENERATED"})
        row = await repo.stage_or_replace(
            ctx.merchant_id, business_date=regenerated.business_date, response=regenerated
        )
        # 用落库后的 `row.payload`（已经过仓储层用真实版本号覆盖）而不是重新序列化
        # `regenerated` 本身——两处各自维护一份版本号正是之前那个真实 bug 的根源，
        # 这里改成只读仓储层写回的唯一事实来源，不再有第二份可能失步的拷贝。
        await session.flush()
        return row.payload

    body = await run_idempotent(
        repo=IdempotencyRepository(session), ctx=ctx, secret=secret,
        operation="merchant.briefs.daily.regenerate", client_request_id=payload.client_request_id,
        request_digest="regenerate", response_status=200, execute=execute,
    )
    await session.commit()
    return DailyBriefResponse.model_validate(body)
