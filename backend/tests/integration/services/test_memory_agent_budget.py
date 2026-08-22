"""MemoryAgent 必须尊重每日 LLM 预算，而不是构造期的一次性快照。

回归覆盖：`MemoryAgent` 曾经把 `LlmCostGuard.daily_cap_hit` 在依赖注入阶段
（本轮聊天自己的 LLM 调用还没跑）读成一次性快照传进来，导致每日预算真的耗尽
之后，后台记忆沉淀仍会发起一次不受预算约束、也不计入 `llm_usage` 的模型调用。
现在改为在后台任务内部实时构造 `LlmCostGuard`，直接查真实的 `llm_daily_budget`
表，这里用真实 PostgreSQL 验证：预算已耗尽时沉淀必须落到确定性兜底文本，并且
必须在 `llm_usage` 留下 `BUDGET_REJECTED` 记录，而不是悄悄跳过或报错外溢。
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import AppEnvironment, Settings
from app.db.session import Database
from app.models.knowledge import MerchantMemory
from app.models.merchant import Merchant
from app.models.operations import LlmDailyBudget, LlmUsage
from app.prompts.memory import MEMORY_MARKER
from app.services.memory_agent import MemoryAgent


class _RecordingBackground:
    def __init__(self) -> None:
        self.tasks: list[tuple] = []

    def add_task(self, func, *args, **kwargs) -> None:
        self.tasks.append((func, args, kwargs))

    async def run_all(self) -> None:
        for func, args, kwargs in self.tasks:
            await func(*args, **kwargs)


def _settings() -> Settings:
    return Settings(
        app_env=AppEnvironment.TEST,
        database_url="postgresql+psycopg://user:pass@localhost/test",
        frontend_origin="http://localhost:5173",
        llm_api_key="test-key",
        llm_daily_budget_tokens=1_000,
        llm_max_output_tokens_per_call=200,
    )


@pytest.mark.asyncio
async def test_daily_budget_exhausted_falls_back_without_bypassing_guard(
    integration_database: Database,
) -> None:
    settings = _settings()
    merchant_id: UUID = uuid4()
    usage_date = datetime.now(UTC).astimezone(ZoneInfo(settings.business_timezone)).date()

    async with integration_database.session() as session:
        session.add(
            Merchant(
                id=merchant_id,
                merchant_code=f"memory-agent-budget-{merchant_id}",
                display_name="记忆预算回归商家",
            )
        )
        # 预算已耗尽：consumed_tokens 达到上限，任何正数 token 的预扣都会失败。
        # usage_date 有唯一约束、且是跨测试共享的「今天」，用 upsert 幂等写入，
        # 避免重复跑本文件时和上一次遗留的行撞唯一约束。
        await session.execute(
            insert(LlmDailyBudget)
            .values(
                usage_date=usage_date,
                consumed_tokens=settings.llm_daily_budget_tokens,
                call_count=1,
            )
            .on_conflict_do_update(
                constraint="uq_llm_daily_budget_usage_date",
                set_={"consumed_tokens": settings.llm_daily_budget_tokens},
            )
        )
        await session.commit()

    try:
        background = _RecordingBackground()
        agent = MemoryAgent(
            background=background,
            database=integration_database,
            settings=settings,
            merchant_id=merchant_id,
            merchant_display="记忆预算回归商家",
            request_id="memory-budget-regression",
        )

        agent.submit(
            category="TRADE",
            question="上月成交额",
            answer="上月成交额为 X",
            source_tables=["orders"],
            quality_notes=[],
            suggestions=[],
            export_id=None,
        )
        await background.run_all()

        async with integration_database.session() as session:
            memory = await _memory_for(session, merchant_id)
            assert memory is not None
            # 预算耗尽必须落到确定性兜底文本：真正调用模型会走 DeepSeekLlmClient
            # 打真实网络请求，这里没有配置 transport，一旦被误触发就会因网络错误
            # 而非预算错误失败——用兜底文本的标记和「更新时间」证明模型从未被调用。
            assert MEMORY_MARKER in memory.content
            assert "更新时间：" in memory.content

            usage_rows = await _usage_rows(session, merchant_id)
            assert len(usage_rows) == 1
            assert usage_rows[0].status == "BUDGET_REJECTED"
    finally:
        # 商家和记忆有唯一 UUID，天然不与其他测试冲突；但 llm_daily_budget 按
        # usage_date 全局共享，必须清回原状，不能让这条测试的耗尽状态漏到
        # 同一天跑的其他测试里。
        async with integration_database.session() as session:
            await session.execute(
                delete(LlmDailyBudget).where(LlmDailyBudget.usage_date == usage_date)
            )
            await session.commit()


async def _memory_for(session: AsyncSession, merchant_id: UUID) -> MerchantMemory | None:
    return await session.scalar(
        select(MerchantMemory).where(MerchantMemory.merchant_id == merchant_id)
    )


async def _usage_rows(session: AsyncSession, merchant_id: UUID) -> list[LlmUsage]:
    result = await session.execute(select(LlmUsage).where(LlmUsage.merchant_id == merchant_id))
    return list(result.scalars())
