"""清理过期未绑定访客会话留下的对话来源状态（计划 Task 6 的 Cron 清理）。

幂等短任务：只删除再也无法使用的来源状态，不删业务对话，不触碰已绑定或商家会话，
重复执行只会删 0 行。只需要 `DATABASE_URL` 与 `APP_ENV`，不需要任何 Web 服务密钥。
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from app.core.job_config import JobSettings
from app.core.runtime import configure_event_loop_policy
from app.db.session import Database
from app.repositories.provenance import ConversationProvenanceRepository


async def run_purge(settings: JobSettings, *, now: datetime | None = None) -> int:
    database = Database(settings)
    try:
        async with database.session() as session:
            deleted = await ConversationProvenanceRepository(
                session
            ).purge_expired_unbound_guests(now=now or datetime.now(UTC))
            await session.commit()
        return deleted
    finally:
        await database.dispose()


def main() -> None:
    configure_event_loop_policy()
    deleted = asyncio.run(run_purge(JobSettings()))
    print(f"purged_guest_provenance={deleted}")


if __name__ == "__main__":
    main()
