"""180 天演示经营数据的纯生成逻辑。

只产出普通字典，不碰数据库也不 import ORM——Seed 的性质要能在没有
PostgreSQL 的机器上被测试覆盖。随机数固定种子，保证同一天的演示数据可复现。
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo

BUSINESS_TIMEZONE = ZoneInfo("Asia/Shanghai")

_CATEGORIES = ("女装", "男装", "鞋靴", "家居", "美妆")
_ORDER_STATUSES = ("CREATED", "PAID", "SHIPPED", "COMPLETED", "CANCELLED", "CLOSED")
_REFUND_REASONS = ("商品质量问题", "尺码不合适", "发货太慢", "拍错了", "不想要了")
_RETURN_REASONS = ("商品质量问题", "尺码不合适", "与描述不符", "包装破损")
_RETURN_STATUSES = ("REQUESTED", "APPROVED", "RECEIVED", "COMPLETED", "REJECTED")
_LOGISTICS_STATUSES = ("PENDING", "SHIPPED", "DELIVERED", "LOST")
_TICKET_STATUSES = ("OPEN", "PENDING", "RESOLVED", "CLOSED")
_TICKET_REASONS = ("物流查询", "退款进度", "商品咨询", "投诉建议")
_CITIES = ("杭州市", "深圳市", "广州市", "成都市", "武汉市")
DEMO_CATALOG_EPOCH = date(2026, 1, 1)
#: 演示经营数据的随机基线：第 i 个演示商家用 BASE + i。
#: 全量重灌脚本与每日滚动 Job 必须共用它，否则新旧两段历史会落在两条随机序列上。
DEMO_ANALYTICS_SEED_BASE = 20260804


@dataclass(frozen=True)
class DemoDataset:
    products: list[dict[str, object]]
    orders: list[dict[str, object]]
    order_items: list[dict[str, object]]
    refunds: list[dict[str, object]]
    returns: list[dict[str, object]]
    tickets: list[dict[str, object]]


def _utc_moment(business_day: date, hour: int, minute: int) -> datetime:
    """把业务时区的时刻转成 UTC 存储值。"""

    local = datetime.combine(business_day, time(hour, minute), tzinfo=BUSINESS_TIMEZONE)
    return local.astimezone(ZoneInfo("UTC"))


def _money(value: float) -> Decimal:
    return Decimal(f"{value:.2f}")


def _row_id(rng: random.Random) -> UUID:
    """从种子化的 rng 派生主键，而不是 uuid4()。

    uuid4() 读系统熵源，同一 seed 两次调用会得到不同的 id——这与「同一 seed
    产出同一批数据」的确定性要求直接冲突，所以主键也必须从 rng 派生。
    """

    return UUID(int=rng.getrandbits(128), version=4)


def _day_rng(merchant_id: UUID, business_day: date, seed: int) -> random.Random:
    """同一商家同一业务日使用固定随机序列，与生成窗口无关。"""

    return random.Random(f"{seed}:{merchant_id}:{business_day.isoformat()}")


def build_demo_catalog(*, merchant_id: UUID, seed: int) -> list[dict[str, object]]:
    """生成稳定的商品目录，绝不随事实窗口或业务日改变。"""

    rng = random.Random(f"{seed}:{merchant_id}:catalog")
    products: list[dict[str, object]] = []
    for index in range(24):
        listed_day = DEMO_CATALOG_EPOCH + timedelta(days=rng.randrange(180))
        products.append(
            {
                "id": _row_id(rng),
                "merchant_id": merchant_id,
                "business_date": listed_day,
                "product_code": f"SKU{index:04d}",
                "spu_id": f"SPU{index:04d}",
                "title": f"演示商品 {index + 1:02d}",
                "category": _CATEGORIES[index % len(_CATEGORIES)],
                "price": _money(rng.uniform(39, 899)),
                "status": "ONLINE" if index % 8 else "AUDITING",
                "listed_at": _utc_moment(listed_day, 10, 0),
            }
        )
    return products


def build_demo_dataset(
    *,
    merchant_id: UUID,
    end_date: date,
    days: int = 180,
    seed: int,
    catalog: list[dict[str, object]] | None = None,
) -> DemoDataset:
    start_date = end_date - timedelta(days=days - 1)
    products = (
        catalog if catalog is not None else build_demo_catalog(merchant_id=merchant_id, seed=seed)
    )

    orders: list[dict[str, object]] = []
    order_items: list[dict[str, object]] = []
    refunds: list[dict[str, object]] = []
    returns: list[dict[str, object]] = []
    tickets: list[dict[str, object]] = []

    for offset in range(days):
        business_day = start_date + timedelta(days=offset)
        rng = _day_rng(merchant_id, business_day, seed)
        ticket_sequence = 0
        # 周末单量略高，让「最近 7 天趋势」这类问题有可见的形状。
        daily_orders = rng.randrange(6, 14) + (3 if business_day.weekday() >= 5 else 0)

        for sequence in range(daily_orders):
            status = _ORDER_STATUSES[rng.randrange(len(_ORDER_STATUSES))]
            paid = status in {"PAID", "SHIPPED", "COMPLETED"}
            order_id = _row_id(rng)
            item_count = rng.randrange(1, 4)
            item_rows: list[dict[str, object]] = []
            total = Decimal("0.00")

            for _ in range(item_count):
                product = products[rng.randrange(len(products))]
                quantity = rng.randrange(1, 4)
                amount = Decimal(str(product["price"])) * quantity
                total += amount
                item_rows.append(
                    {
                        "id": _row_id(rng),
                        "merchant_id": merchant_id,
                        # 订单项跟着订单的下单日，退货率的分母才对得上同期口径。
                        "business_date": business_day,
                        "order_id": order_id,
                        "product_id": product["id"],
                        "quantity": quantity,
                        "item_amount": amount,
                    }
                )

            orders.append(
                {
                    "id": order_id,
                    "merchant_id": merchant_id,
                    "business_date": business_day,
                    "order_no": f"NO{business_day:%Y%m%d}{sequence:03d}",
                    "buyer_key": f"buyer-{rng.randrange(1, 240):03d}",
                    "address_city_name": _CITIES[rng.randrange(len(_CITIES))],
                    "order_status": status,
                    "total_amount": total,
                    "paid_amount": total if paid else Decimal("0.00"),
                    "placed_at": _utc_moment(business_day, rng.randrange(0, 24), rng.randrange(60)),
                    "paid_at": _utc_moment(business_day, 12, 0) if paid else None,
                }
            )
            order_items.extend(item_rows)

            if not paid:
                continue

            # 三类售后样本按固定比例产出，保证「只退款」「只退货」「退货并退款」都存在。
            draw = rng.random()
            item = item_rows[0]
            # 售后事件与来源订单同日：这样一个业务日的全部事实自成一个分区，既让同一天
            # 无论在哪个窗口里生成都完全一致（滚动 Seed 的前提），也让按业务日清理窗口外
            # 数据时不会留下指向已删订单的悬空外键。代价是不再模拟跨日退款延迟。
            refund_day = business_day
            if draw < 0.08:
                refunds.append(_refund_row(merchant_id, item, refund_day, rng))
            elif draw < 0.14:
                returns.append(_return_row(merchant_id, item, refund_day, rng))
            elif draw < 0.20:
                refunds.append(_refund_row(merchant_id, item, refund_day, rng))
                returns.append(_return_row(merchant_id, item, refund_day, rng))

            if rng.random() < 0.10:
                ticket_day = business_day
                tickets.append(
                    {
                        "id": _row_id(rng),
                        "merchant_id": merchant_id,
                        "business_date": ticket_day,
                        "ticket_no": f"TK{ticket_day:%Y%m%d}{ticket_sequence:04d}",
                        "order_id": order_id,
                        "ticket_status": _TICKET_STATUSES[rng.randrange(len(_TICKET_STATUSES))],
                        "ticket_reason": _TICKET_REASONS[rng.randrange(len(_TICKET_REASONS))],
                        "opened_at": _utc_moment(ticket_day, rng.randrange(9, 21), 0),
                    }
                )
                ticket_sequence += 1

    return DemoDataset(products, orders, order_items, refunds, returns, tickets)


def _refund_row(
    merchant_id: UUID,
    item: dict[str, object],
    business_day: date,
    rng: random.Random,
) -> dict[str, object]:
    status = "REFUNDED" if rng.random() < 0.8 else "PENDING"
    return {
        "id": _row_id(rng),
        "merchant_id": merchant_id,
        "business_date": business_day,
        "order_item_id": item["id"],
        "refund_amount": Decimal(str(item["item_amount"])),
        "refund_reason": _REFUND_REASONS[rng.randrange(len(_REFUND_REASONS))],
        "refund_status": status,
        "refunded_at": _utc_moment(business_day, 15, 0) if status == "REFUNDED" else None,
    }


def _return_row(
    merchant_id: UUID,
    item: dict[str, object],
    business_day: date,
    rng: random.Random,
) -> dict[str, object]:
    status = _RETURN_STATUSES[rng.randrange(len(_RETURN_STATUSES))]
    return {
        "id": _row_id(rng),
        "merchant_id": merchant_id,
        "business_date": business_day,
        "order_item_id": item["id"],
        "return_quantity": item["quantity"],
        "return_reason": _RETURN_REASONS[rng.randrange(len(_RETURN_REASONS))],
        "return_status": status,
        "logistics_status": _LOGISTICS_STATUSES[rng.randrange(len(_LOGISTICS_STATUSES))],
        "returned_at": _utc_moment(business_day, 16, 0) if status != "REQUESTED" else None,
    }
