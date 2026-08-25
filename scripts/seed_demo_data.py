"""写入 Borough 演示商家基础数据。

这是仅限本机或本地 Compose 数据库的全量工具；线上经营数据唯一写入口为
`app.jobs.seed_demo_rolling` Cron。
"""

from __future__ import annotations

import argparse
import asyncio
from urllib.parse import urlparse

from app.core.config import AppEnvironment, get_settings
from app.core.runtime import configure_event_loop_policy
from app.db.session import Database
from app.services.seed_service import default_merchants, seed_demo_merchants

_LOCAL_DATABASE_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "postgres"})


def assert_local_database_url(database_url: str) -> None:
    """商家基础数据的全量 Seed 只允许连接本机或本地 Compose PostgreSQL。"""

    try:
        hostname = urlparse(database_url).hostname
    except ValueError as error:
        raise RuntimeError("全量演示 Seed 只能连接本机数据库") from error
    if hostname is None or hostname.lower() not in _LOCAL_DATABASE_HOSTS:
        raise RuntimeError("全量演示 Seed 只能连接本机数据库")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成 Borough 演示数据")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--dry-run", action="store_true", help="只展示计划，不写数据库")
    action.add_argument("--seed", action="store_true", help="写入数据库")
    parser.add_argument("--merchant-count", type=int, default=3)
    parser.add_argument("--days", type=int, default=180)
    parser.add_argument("--random-seed", type=int, default=20260730)
    return parser.parse_args()


async def run(args: argparse.Namespace) -> None:
    merchants = default_merchants(merchant_count=args.merchant_count)
    if args.dry_run:
        print(
            f"计划写入 {len(merchants)} 个演示商家；"
            f"经营数据天数 {args.days}、随机种子 {args.random_seed} 将在 B4 使用。"
        )
        for merchant in merchants:
            print(f"- {merchant.merchant_code}: {merchant.display_name} ({merchant.id})")
        return

    settings = get_settings()
    assert_local_database_url(settings.database_url)
    if settings.app_env is AppEnvironment.PRODUCTION:
        raise RuntimeError("生产环境禁止运行演示 Seed")

    database = Database(settings)
    try:
        async with database.session() as session:
            result = await seed_demo_merchants(session, merchants)
    finally:
        await database.dispose()
    print(f"演示商家 Seed 完成：新增 {result.created}，已存在 {result.existing}。")


def main() -> None:
    configure_event_loop_policy()
    asyncio.run(run(parse_args()))


if __name__ == "__main__":
    main()
