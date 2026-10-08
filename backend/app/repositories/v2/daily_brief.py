"""完整每日简报的版本化存储（N3 阶段 C Task 2，PRD M2、D18⑥⑨）。

一商家一营业日一份（`uq_daily_briefs_merchant_date`），重新生成是版本替换，不是新增行。
唯一约束只能保证不出现两行；并发重新生成还需要**事务级锁**才能保证 5 个并发请求恰好
产生 1 个新版本，不是竞态下的任意中间状态——与 `services/v2/customer_signals.py` 同样的
"advisory lock 串行化 + 唯一索引兜底"模式。
"""

from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.memory_v2 import DailyBrief
from app.schemas.v2.merchant_ops import DailyBriefResponse


class DailyBriefRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def lock_business_day(self, merchant_id: UUID, *, business_date: date) -> None:
        """在检查当前版本和冷却前取得同一事务锁，避免检查后并发写入。"""

        key = f"{merchant_id}:daily_brief:{business_date.isoformat()}"
        await self._session.scalar(
            select(func.pg_advisory_xact_lock(func.hashtextextended(key, 0)))
        )

    async def get_current(
        self, merchant_id: UUID, *, business_date: date
    ) -> DailyBrief | None:
        row: DailyBrief | None = await self._session.scalar(
            select(DailyBrief).where(
                DailyBrief.merchant_id == merchant_id,
                DailyBrief.business_date == business_date,
            )
        )
        return row

    async def stage_or_replace(
        self, merchant_id: UUID, *, business_date: date, response: DailyBriefResponse
    ) -> DailyBrief:
        """首次生成插入第 1 版；已存在时替换为下一个版本号，不新增行。

        调用方必须自行 `commit()`；本方法只负责事务内的锁定与写入顺序，不提交事务，
        以便与调用方其余写入（若有）共享同一次提交边界。
        """

        # 事务级锁把并发重新生成串行化：同一 (merchant_id, business_date) 的并发写入
        # 排队执行，唯一索引提供第二道数据库约束（与 customer_signals.py 同一模式）。
        await self.lock_business_day(merchant_id, business_date=business_date)
        row = await self._session.scalar(
            select(DailyBrief).where(
                DailyBrief.merchant_id == merchant_id,
                DailyBrief.business_date == business_date,
            ).with_for_update()
        )
        if row is None:
            new_version = response.brief_version
            row = DailyBrief(
                merchant_id=merchant_id, business_date=business_date,
                brief_version=new_version, payload={}, generated_at=response.generated_at,
            )
            self._session.add(row)
        else:
            new_version = row.brief_version + 1
            row.brief_version = new_version
            row.generated_at = response.generated_at
        # `payload` 里的 `brief_version` 必须与刚算出的 `row.brief_version` 一致——
        # 调用方传入的 `response.brief_version` 只是生成时的占位值（调用方在写入前
        # 还不知道真实版本号），序列化必须在这里、用真实版本号覆盖之后才做，
        # 不能直接把调用方传入的 `response` 原样序列化（真实发现的 bug，2026-09-26）。
        row.payload = response.model_copy(update={"brief_version": new_version}).model_dump(
            mode="json"
        )
        await self._session.flush()
        return row
