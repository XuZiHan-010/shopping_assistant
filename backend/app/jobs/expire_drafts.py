"""草稿过期清理（PRD M10，契约 §8.13.2）。

这个任务**不是**过期判定的依据：读取与应用路径各自会按 `expires_at` 自检，
清理只负责把陈旧的 `STAGED` 行批量收口，让列表和统计不再把它们算作待办。
两者顺序反过来（业务路径依赖任务跑过）会让「Cron 挂了」变成「过期草稿还能批准」。

接受 `now` 参数而不读墙钟：这样测试能确定性地跨过 7 天，任务也能被补跑。
Cron 接线在 `n5-budget-ops-and-railway`。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast

from sqlalchemy import CursorResult, update

from app.db.session import Database
from app.models.drafts import Draft
from app.schemas.v2.drafts import DraftState


async def expire_drafts(database: Database, *, now: datetime) -> int:
    """把已过期的 `STAGED` 草稿置为 `EXPIRED`，返回本次影响的行数。

    条件更新天然幂等：已经是终态的行不在 `WHERE` 里，重复跑只会返回 0。
    """

    async with database.session() as session:
        result = cast(
            "CursorResult[Any]",
            await session.execute(
                update(Draft)
                .where(Draft.state == DraftState.STAGED.value, Draft.expires_at <= now)
                .values(state=DraftState.EXPIRED.value)
            ),
        )
        await session.commit()
        return result.rowcount or 0
