"""商家只读顾客信号工具，与工作台共用查询服务。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.db.session import Database
from app.services.v2.customer_signals import list_signals, to_signal
from app.tools.types import ToolContext, ToolOutput, ToolRole, ToolSpec, WritePolicy


class ListSignalsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    include_ignored: bool = False


def build_signal_tools(database: Database) -> tuple[ToolSpec, ...]:
    async def execute(ctx: ToolContext, args: ListSignalsArgs) -> ToolOutput:
        async with database.session() as session:
            rows = await list_signals(
                session, ctx.session, include_ignored=args.include_ignored
            )
            items = [to_signal(row).model_dump(mode="json") for row in rows[:20]]
        return ToolOutput(
            payload={"items": items}, summary=f"本店有 {len(items)} 条顾客信号",
            row_count=len(items),
        )

    return (ToolSpec(
        name="list_signals", roles=frozenset({ToolRole.MERCHANT}),
        args_model=ListSignalsArgs, write_policy=WritePolicy.READ_ONLY,
        parallelizable=True, description="查询本店派生顾客信号，不包含顾客身份。",
        executor=execute,
    ),)
