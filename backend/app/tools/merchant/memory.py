"""商家本店事实与非陈旧总结的只读召回。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.db.session import Database
from app.memory.context import bounded_payload
from app.memory.merchant_store import MerchantMemoryStore
from app.memory.owners import MerchantMemoryOwner
from app.tools.types import ToolContext, ToolOutput, ToolRole, ToolSpec, WritePolicy


class RecallMerchantPreferencesArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: str | None = Field(default=None, min_length=1, max_length=64)


def build_memory_tools(database: Database) -> tuple[ToolSpec, ...]:
    async def recall_merchant_preferences(
        ctx: ToolContext, args: RecallMerchantPreferencesArgs
    ) -> ToolOutput:
        owner = MerchantMemoryOwner.from_session(ctx.session)
        if owner is None:  # 工具面只给商家角色；防御性返回空，不读任何商家记忆
            return ToolOutput(
                payload={"facts": [], "summaries": []}, summary="无可用记忆", row_count=0
            )
        async with database.session() as session:
            store = MerchantMemoryStore(session, owner)
            facts = await store.facts(
                category=args.category,
                limit=21,
                exclude_ids=tuple(set(ctx.memory_excluded_ids) | ctx.memory_seen_ids),
            )
        payload = bounded_payload(
            facts,
            max_chars=5000,
            exclude_ids=tuple(set(ctx.memory_excluded_ids) | ctx.memory_seen_ids),
        )
        ctx.memory_seen_ids.update(item["id"] for item in payload["memories"])
        # 按需读取事实正文；总结是同一事实的派生副本，仅在记忆面板展示，避免重复加载。
        payload["facts"] = payload.pop("memories")
        payload["summaries"] = []
        return ToolOutput(
            payload=payload,
            summary="已读取当前商家的非陈旧偏好，仅可用于回答呈现方式",
            row_count=len(payload["facts"]),
        )

    return (
        ToolSpec(
            name="recall_merchant_preferences",
            roles=frozenset({ToolRole.MERCHANT}),
            args_model=RecallMerchantPreferencesArgs,
            write_policy=WritePolicy.READ_ONLY,
            parallelizable=True,
            description="按上下文目录中的类别读取尚未展示的商家偏好事实，只用于语气和呈现。",
            executor=recall_merchant_preferences,
            grounds_numbers=False,
        ),
    )
