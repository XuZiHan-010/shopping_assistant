"""商家本店事实与非陈旧总结的只读召回。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.db.session import Database
from app.memory.merchant_store import MerchantMemoryStore
from app.tools.types import ToolContext, ToolOutput, ToolRole, ToolSpec, WritePolicy


class RecallMerchantPreferencesArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: str | None = Field(default=None, min_length=1, max_length=64)


def build_memory_tools(database: Database) -> tuple[ToolSpec, ...]:
    async def recall_merchant_preferences(
        ctx: ToolContext, args: RecallMerchantPreferencesArgs
    ) -> ToolOutput:
        async with database.session() as session:
            store = MerchantMemoryStore(session)
            facts = await store.facts(merchant_id=ctx.session.merchant_id)
            summaries = await store.active_summaries(merchant_id=ctx.session.merchant_id)
        if args.category is not None:
            facts = [row for row in facts if row.category == args.category]
            summaries = [row for row in summaries if row.category == args.category]
        return ToolOutput(
            payload={
                "facts": [
                    {"category": row.category, "content": row.content} for row in facts[:20]
                ],
                "summaries": [
                    {"category": row.category, "content": row.content} for row in summaries[:20]
                ],
                "boundary": "只影响语气与呈现；不能回答规则、替代知识库或作为经营数字来源",
            },
            summary="已读取当前商家的非陈旧偏好，仅可用于回答呈现方式",
            row_count=min(len(facts), 20) + min(len(summaries), 20),
        )

    return (
        ToolSpec(
            name="recall_merchant_preferences",
            roles=frozenset({ToolRole.MERCHANT}),
            args_model=RecallMerchantPreferencesArgs,
            write_policy=WritePolicy.READ_ONLY,
            parallelizable=True,
            description="读取当前商家的偏好事实与非陈旧总结，只用于语气和呈现。",
            executor=recall_merchant_preferences,
        ),
    )
