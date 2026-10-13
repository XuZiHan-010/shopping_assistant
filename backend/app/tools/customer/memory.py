"""顾客本店偏好的受控只读召回工具。"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.db.session import Database
from app.memory.context import bounded_payload
from app.memory.customer_store import CustomerMemoryStore
from app.memory.owners import CustomerMemoryOwner
from app.tools.types import ToolContext, ToolOutput, ToolRole, ToolSpec, WritePolicy


class RecallPreferencesArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: str | None = Field(default=None, min_length=1, max_length=64)
    limit: int = Field(default=5, ge=1, le=20)


def build_memory_tools(database: Database) -> tuple[ToolSpec, ...]:
    async def recall_preferences(ctx: ToolContext, args: RecallPreferencesArgs) -> ToolOutput:
        owner = CustomerMemoryOwner.from_session(ctx.session)
        if owner is None:
            return ToolOutput(payload={"memories": []}, summary="当前访客没有可用记忆", row_count=0)
        async with database.session() as session:
            rows = await CustomerMemoryStore(session, owner).recall(
                at=datetime.now(UTC),
                limit=args.limit + 1,
                category=args.category,
                exclude_ids=tuple(set(ctx.memory_excluded_ids) | ctx.memory_seen_ids),
            )
        payload = bounded_payload(
            rows,
            limit=args.limit,
            max_chars=5000,
            exclude_ids=tuple(set(ctx.memory_excluded_ids) | ctx.memory_seen_ids),
        )
        ctx.memory_seen_ids.update(item["id"] for item in payload["memories"])
        return ToolOutput(
            payload=payload,
            summary="已读取当前顾客在本店尚未过期的偏好；本次明确需求优先",
            row_count=len(payload["memories"]),
        )

    return (
        ToolSpec(
            name="recall_preferences",
            roles=frozenset({ToolRole.CUSTOMER}),
            args_model=RecallPreferencesArgs,
            write_policy=WritePolicy.READ_ONLY,
            parallelizable=True,
            description="按类别读取当前已绑定顾客在本店的历史偏好；只用于个性化默认值。",
            executor=recall_preferences,
            grounds_numbers=False,
        ),
    )
