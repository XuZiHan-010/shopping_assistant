"""Chat BI 日汇总的可重跑物化任务。"""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, date, datetime, timedelta

from app.analytics.dates import business_today
from app.core.config import Settings
from app.core.runtime import configure_event_loop_policy
from app.db.session import Database
from app.repositories.chatbi import ChatBiRepository

DEFAULT_WINDOW_DAYS = 7


def default_window(settings: Settings) -> tuple[date, date]:
    end = business_today(datetime.now(UTC), timezone=settings.business_timezone)
    return end - timedelta(days=DEFAULT_WINDOW_DAYS - 1), end


async def run_rollup(settings: Settings, *, start_date: date, end_date: date) -> int:
    if start_date > end_date:
        raise ValueError("start_date 不得晚于 end_date")
    database = Database(settings)
    try:
        return await ChatBiRepository(
            database, business_timezone=settings.business_timezone
        ).rollup_range(start_date=start_date, end_date=end_date)
    finally:
        await database.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="重算 Chat BI 日粒度汇总")
    parser.add_argument("--start-date", type=date.fromisoformat)
    parser.add_argument("--end-date", type=date.fromisoformat)
    args = parser.parse_args()
    configure_event_loop_policy()
    settings = Settings()
    start, end = default_window(settings)
    asyncio.run(
        run_rollup(settings, start_date=args.start_date or start, end_date=args.end_date or end)
    )


if __name__ == "__main__":
    main()
