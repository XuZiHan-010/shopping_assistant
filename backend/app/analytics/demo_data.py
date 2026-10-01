"""180 天演示经营数据的纯生成逻辑。

只产出普通字典，不碰数据库也不 import ORM——Seed 的性质要能在没有
PostgreSQL 的机器上被测试覆盖。随机数固定种子，保证同一天的演示数据可复现。
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Final, cast
from uuid import NAMESPACE_URL, UUID, uuid5
from zoneinfo import ZoneInfo

from app.domain.order_status_mapping import from_legacy_status

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
class _DemoProduct:
    title: str
    price: int
    description: str
    material_or_benefit: str
    origin: str
    specification_key: str
    specification_value: str


# 来源：frontend/prototypes/borough-shop-redesign.html RAW；属性键按 WS 规格规范化。
_DEMO_PRODUCTS: Final[tuple[_DemoProduct, ...]] = (
    _DemoProduct(
        "真丝印花半裙", 569, "真丝印花，A 字及踝。", "100% 桑蚕丝", "浙江杭州", "尺码", "S–L"
    ),
    _DemoProduct(
        "牛津纺长袖衬衫",
        239,
        "纯棉牛津纺，微挺括，领尖可扣。",
        "100% 棉",
        "浙江杭州",
        "尺码",
        "S–XXL",
    ),
    _DemoProduct(
        "手工缝线切尔西靴",
        699,
        "牛皮鞋面，固特异缝线，鞋底可更换。",
        "头层牛皮",
        "广东东莞",
        "尺码",
        "35–44",
    ),
    _DemoProduct(
        "粗陶手作咖啡杯（两只装）",
        128,
        "手拉坯粗陶，哑光釉，每只略有不同。",
        "粗陶",
        "福建厦门",
        "容量",
        "280ml ×2",
    ),
    _DemoProduct(
        "燕麦舒缓保湿面霜", 159, "温和保湿，适合敏感肌。", "舒缓保湿", "上海", "规格", "50ml"
    ),
    _DemoProduct(
        "亚麻宽松开衫",
        329,
        "水洗亚麻，落肩宽松，春秋外搭。",
        "100% 亚麻",
        "浙江杭州",
        "尺码",
        "S–XL",
    ),
    _DemoProduct(
        "水洗帆布工装夹克",
        459,
        "水洗帆布，四个贴袋，越穿越软。",
        "棉帆布",
        "浙江杭州",
        "尺码",
        "M–XXL",
    ),
    _DemoProduct(
        "复古德训运动鞋", 389, "麂皮拼接，橡胶生胶底。", "麂皮 + 牛皮", "广东东莞", "尺码", "35–45"
    ),
    _DemoProduct(
        "橡木砧板", 199, "整块白橡木，食品级木蜡油。", "白橡木", "福建厦门", "尺寸", "40×28cm"
    ),
    _DemoProduct(
        "玫瑰果油修护精华", 219, "冷压玫瑰果油，修护干燥肌。", "修护、滋润", "上海", "规格", "30ml"
    ),
    _DemoProduct(
        "羊毛混纺高领毛衣",
        399,
        "细针高领，贴身也不扎。",
        "70% 羊毛 30% 锦纶",
        "浙江杭州",
        "尺码",
        "S–L",
    ),
    _DemoProduct(
        "美利奴羊毛针织开衫",
        529,
        "美利奴羊毛，V 领，贝壳扣。",
        "100% 美利奴羊毛",
        "浙江杭州",
        "尺码",
        "M–XXL",
    ),
    _DemoProduct(
        "软底乐福鞋", 459, "软底一脚蹬，轻便，久坐不累。", "羊皮", "广东东莞", "尺码", "35–44"
    ),
    _DemoProduct(
        "亚麻格纹桌布", 169, "亚麻格纹，可机洗。", "100% 亚麻", "福建厦门", "尺寸", "140×180cm"
    ),
    _DemoProduct(
        "苦橙花淡香水", 399, "苦橙花与白麝香，清淡不闷。", "柑橘花香调", "上海", "规格", "50ml"
    ),
    _DemoProduct(
        "高腰直筒牛仔裤",
        299,
        "高腰直筒，12oz 牛仔布，微弹。",
        "98% 棉 2% 氨纶",
        "浙江杭州",
        "尺码",
        "24–31",
    ),
    _DemoProduct(
        "格纹羊绒围巾", 489, "纯羊绒格纹，长 180cm。", "100% 羊绒", "浙江杭州", "尺码", "180×30cm"
    ),
    _DemoProduct(
        "防泼水徒步短靴",
        629,
        "防泼水鞋面，大底抓地。",
        "防泼水尼龙 + 牛皮",
        "广东东莞",
        "尺码",
        "36–45",
    ),
    _DemoProduct(
        "无花果雪松香氛蜡烛",
        149,
        "无花果叶与雪松，燃烧约 45 小时。",
        "大豆蜡",
        "福建厦门",
        "规格",
        "220g",
    ),
    _DemoProduct(
        "氨基酸温和洁面乳",
        89,
        "氨基酸表活，无皂基，洗后不紧绷。",
        "温和清洁",
        "上海",
        "规格",
        "120ml",
    ),
    _DemoProduct(
        "法式碎花连衣裙", 459, "碎花印花，V 领系带，及膝。", "100% 粘胶", "浙江杭州", "尺码", "XS–L"
    ),
    _DemoProduct(
        "修身斜纹休闲裤",
        279,
        "修身斜纹棉，微弹，九分长。",
        "97% 棉 3% 氨纶",
        "浙江杭州",
        "尺码",
        "28–36",
    ),
    _DemoProduct(
        "羊皮芭蕾平底鞋", 399, "软羊皮，可折叠，鞋底防滑。", "羊皮", "广东东莞", "尺码", "34–40"
    ),
    _DemoProduct(
        "羊毛混纺沙发毯",
        359,
        "羊毛混纺，流苏收边。",
        "60% 羊毛 40% 腈纶",
        "福建厦门",
        "尺寸",
        "130×170cm",
    ),
)


@dataclass(frozen=True)
class DemoDataset:
    products: list[dict[str, object]]
    orders: list[dict[str, object]]
    order_items: list[dict[str, object]]
    refunds: list[dict[str, object]]
    returns: list[dict[str, object]]
    tickets: list[dict[str, object]]
    inventory_events: list[dict[str, object]]
    fulfillment_events: list[dict[str, object]]


def _event_row(
    *,
    merchant_id: UUID,
    subject_id: UUID,
    event_type: str,
    occurred_at: datetime,
    dedupe_key: str,
    payload: dict[str, object],
) -> dict[str, object]:
    return {
        "id": uuid5(NAMESPACE_URL, f"borough-demo:{merchant_id}:{dedupe_key}"),
        "merchant_id": merchant_id,
        "subject_id": subject_id,
        "event_type": event_type,
        "occurred_at": occurred_at,
        "dedupe_key": dedupe_key,
        "payload": payload,
        "created_at": occurred_at,
    }


def _legacy_fulfillment_events(order: dict[str, object]) -> list[dict[str, object]]:
    """与 M3 历史回填使用相同状态、时间及推定标记。"""

    merchant_id = cast(UUID, order["merchant_id"])
    order_id = cast(UUID, order["id"])
    placed_at = cast(datetime, order["placed_at"])
    paid_at = order["paid_at"]
    status = order["order_status"]
    events = []

    def add(
        event_type: str,
        occurred_at: datetime,
        *,
        inferred: bool = False,
        close_reason: str | None = None,
    ) -> None:
        payload: dict[str, object] = {"origin": "LEGACY_V1_BACKFILL"}
        if inferred:
            payload["time_inferred"] = True
        if close_reason is not None:
            payload["close_reason"] = close_reason
        events.append(
            _event_row(
                merchant_id=merchant_id,
                subject_id=order_id,
                event_type=event_type,
                occurred_at=occurred_at,
                dedupe_key=f"legacy:{order_id}:{event_type}",
                payload=payload,
            )
        )

    add("ORDER_PLACED", placed_at)
    if status in {"PAID", "SHIPPED", "COMPLETED"}:
        assert isinstance(paid_at, datetime)
        add("PAYMENT_CONFIRMED", paid_at)
    if status in {"SHIPPED", "COMPLETED"}:
        assert isinstance(paid_at, datetime)
        add("SHIPPED", paid_at + timedelta(hours=6), inferred=True)
    if status == "COMPLETED":
        assert isinstance(paid_at, datetime)
        add("DELIVERED", paid_at + timedelta(days=3), inferred=True)
    if status in {"CANCELLED", "CLOSED"}:
        add(
            "ORDER_CLOSED",
            placed_at + timedelta(minutes=30),
            inferred=True,
            close_reason=cast(str, order["close_reason"]),
        )
    return events


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
        listed_at = _utc_moment(listed_day, 10, 0)
        item = _DEMO_PRODUCTS[index]
        values = {
            "功效" if index % 5 == 4 else "材质": item.material_or_benefit,
            "产地": item.origin,
            item.specification_key: item.specification_value,
        }
        if index % 5 == 4:
            values["保质期"] = "未开封 36 个月，开封后 12 个月"
        if index == 2:
            del values["产地"]
        attributes = {
            key: {"value": value, "source": "DEMO", "updated_at": listed_at.isoformat()}
            for key, value in values.items()
        }
        description = item.description + "尺码与保养信息经店家核对。"
        if index == 0:
            description += (
                "这款半裙采用轻盈的桑蚕丝面料，日常穿着时请避免与尖锐物摩擦。"
                "清洗前先查看洗护标签，建议使用适合真丝的温和清洁方式，平铺或悬挂晾干。"
                "搭配衬衫或针织上衣均可，具体尺码请以商品属性和实际试穿感受为准。"
            )
        if index == 4:
            description = "简短说明。"
        product_id = _row_id(rng)
        # 保留旧价格的随机调用，防止后续商品主键和上架日期漂移。
        rng.uniform(39, 899)
        products.append(
            {
                "id": product_id,
                "merchant_id": merchant_id,
                "business_date": listed_day,
                "product_code": f"SKU{index:04d}",
                "spu_id": f"SPU{index:04d}",
                "title": item.title,
                "category": _CATEGORIES[index % len(_CATEGORIES)],
                "price": Decimal(item.price),
                "status": "ONLINE" if index % 8 else "AUDITING",
                "listed_at": listed_at,
                "short_description": item.description,
                "detail_description": description,
                "attributes": attributes,
                "image_url": None if index == 5 else f"/demo/products/{index + 1:02d}.webp",
                "stock_on_hand": 3 if index == 3 else 100,
                "stock_reserved": 0,
                "low_stock_threshold": 5,
                "content_version": 1,
                "source_locale": "zh-CN",
                "created_at": listed_at,
                "updated_at": listed_at,
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
    inventory_events = [
        _event_row(
            merchant_id=merchant_id,
            subject_id=cast(UUID, product["id"]),
            event_type="INITIAL_STOCK",
            occurred_at=cast(datetime, product["listed_at"]),
            dedupe_key=f"demo:initial-stock:{product['id']}",
            payload={"quantity": product["stock_on_hand"], "origin": "DEMO_SEED"},
        )
        for product in products
    ]
    fulfillment_events: list[dict[str, object]] = []

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
                        "unit_price": product["price"],
                        "discount_amount": Decimal("0.00"),
                        "line_total": amount,
                    }
                )

            placed_at = _utc_moment(business_day, rng.randrange(0, 11), rng.randrange(60))
            for item_row in item_rows:
                item_row["created_at"] = placed_at
            payment_status, fulfillment_status, close_reason = from_legacy_status(status)
            order = {
                "id": order_id,
                "merchant_id": merchant_id,
                "business_date": business_day,
                "order_no": f"NO{business_day:%Y%m%d}{sequence:03d}",
                "buyer_key": f"buyer-{rng.randrange(1, 240):03d}",
                "address_city_name": _CITIES[rng.randrange(len(_CITIES))],
                "order_status": status,
                "total_amount": total,
                "paid_amount": total if paid else Decimal("0.00"),
                "placed_at": placed_at,
                "paid_at": _utc_moment(business_day, 12, 0) if paid else None,
                "payment_status": payment_status,
                "fulfillment_status": fulfillment_status,
                "after_sale_status": "NONE",
                "close_reason": close_reason,
                "lifecycle_origin": "LEGACY_V1",
                "source_timezone": "Asia/Shanghai",
                "created_at": placed_at,
                "updated_at": placed_at,
            }
            orders.append(order)
            fulfillment_events.extend(_legacy_fulfillment_events(order))
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
                opened_at = _utc_moment(ticket_day, rng.randrange(9, 21), 0)
                tickets.append(
                    {
                        "id": _row_id(rng),
                        "merchant_id": merchant_id,
                        "business_date": ticket_day,
                        "ticket_no": f"TK{ticket_day:%Y%m%d}{ticket_sequence:04d}",
                        "order_id": order_id,
                        "ticket_status": _TICKET_STATUSES[rng.randrange(len(_TICKET_STATUSES))],
                        "ticket_reason": _TICKET_REASONS[rng.randrange(len(_TICKET_REASONS))],
                        "opened_at": opened_at,
                        "created_at": opened_at,
                        "updated_at": opened_at,
                    }
                )
                ticket_sequence += 1

    return DemoDataset(
        products,
        orders,
        order_items,
        refunds,
        returns,
        tickets,
        inventory_events,
        fulfillment_events,
    )


def _refund_row(
    merchant_id: UUID,
    item: dict[str, object],
    business_day: date,
    rng: random.Random,
) -> dict[str, object]:
    status = "REFUNDED" if rng.random() < 0.8 else "PENDING"
    occurred_at = _utc_moment(business_day, 15, 0)
    return {
        "id": _row_id(rng),
        "merchant_id": merchant_id,
        "business_date": business_day,
        "order_item_id": item["id"],
        "refund_amount": Decimal(str(item["item_amount"])),
        "refund_reason": _REFUND_REASONS[rng.randrange(len(_REFUND_REASONS))],
        "refund_status": status,
        "refunded_at": occurred_at if status == "REFUNDED" else None,
        "created_at": occurred_at,
    }


def _return_row(
    merchant_id: UUID,
    item: dict[str, object],
    business_day: date,
    rng: random.Random,
) -> dict[str, object]:
    status = _RETURN_STATUSES[rng.randrange(len(_RETURN_STATUSES))]
    occurred_at = _utc_moment(business_day, 16, 0)
    return {
        "id": _row_id(rng),
        "merchant_id": merchant_id,
        "business_date": business_day,
        "order_item_id": item["id"],
        "return_quantity": item["quantity"],
        "return_reason": _RETURN_REASONS[rng.randrange(len(_RETURN_REASONS))],
        "return_status": status,
        "logistics_status": _LOGISTICS_STATUSES[rng.randrange(len(_LOGISTICS_STATUSES))],
        "returned_at": occurred_at if status != "REQUESTED" else None,
        "created_at": occurred_at,
    }
