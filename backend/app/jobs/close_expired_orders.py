"""30 分钟未支付订单的清理任务（PRD §7.1、C4，交易计划 Task 4）。

这个任务**不是**超时判定的依据：支付路径自己按 `pay_by` 判定（`payment.expire_if_due`），
任务只负责把没人再来碰的过期订单关闭并释放占用。两者用同一个条件更新抢状态，只有一方生效。

接受 `now` 参数而不读墙钟：测试能确定性地跨过 30 分钟，N5 的 Cron 追赶漏跑时行为也可预测。
每个订单单独一个事务：一单失败不影响其它单，已关闭的单也不会因为后面的失败被回滚。
Cron 接线在 `n5-budget-ops-and-railway`。
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime
from typing import Final

from sqlalchemy import select

from app.core.job_config import JobSettings
from app.core.runtime import configure_event_loop_policy
from app.db.session import Database
from app.models.analytics import Order
from app.services.v2.orders import PAYMENT_WINDOW, V2_ORIGIN
from app.services.v2.payment import close_order

BATCH_SIZE: Final = 500


async def close_expired_orders(database: Database, *, now: datetime) -> int:
    """关闭 `placed_at ≤ now − 30min` 的 v2 待支付订单，返回本次关闭数；补跑只会返回 0。"""

    async with database.session() as session:
        candidates = (
            await session.execute(
                select(Order.id, Order.merchant_id)
                .where(
                    Order.payment_status == "PENDING",
                    Order.lifecycle_origin == V2_ORIGIN,
                    Order.placed_at <= now - PAYMENT_WINDOW,
                )
                .order_by(Order.placed_at, Order.id)
                .limit(BATCH_SIZE)
            )
        ).all()
    closed = 0
    failed = 0
    for order_id, merchant_id in candidates:
        try:
            async with database.session() as session:
                changed = await close_order(
                    session, merchant_id=merchant_id, order_id=order_id, reason="TIMEOUT", now=now
                )
                await session.commit()
                if changed:
                    closed += 1
        except Exception:
            failed += 1
    if failed:
        # 成功行已经各自提交；整体仍须失败，保留 Cron 时间片供下次重试。
        raise RuntimeError("expired order close failures")
    return closed


async def _run_cli() -> int:
    database = Database(JobSettings())
    try:
        return await close_expired_orders(database, now=datetime.now(UTC))
    finally:
        await database.dispose()


def main() -> None:
    argparse.ArgumentParser(description="关闭超过 30 分钟未支付的 v2 订单并释放占用").parse_args()
    configure_event_loop_policy()
    print(f"closed={asyncio.run(_run_cli())}")


if __name__ == "__main__":
    main()
