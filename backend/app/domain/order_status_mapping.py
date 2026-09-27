"""v1 兼容状态与 v2 订单投影之间的确定性映射。"""

from __future__ import annotations

LEGACY_ORDER_STATUSES = ("CREATED", "PAID", "SHIPPED", "COMPLETED", "CANCELLED", "CLOSED")

FROM_LEGACY_TABLE: dict[str, tuple[str, str, str | None]] = {
    "CREATED": ("PENDING", "NOT_SHIPPED", None),
    "PAID": ("PAID", "NOT_SHIPPED", None),
    "SHIPPED": ("PAID", "SHIPPED", None),
    "COMPLETED": ("PAID", "DELIVERED", None),
    "CANCELLED": ("CLOSED", "NOT_SHIPPED", "CUSTOMER_CANCEL"),
    "CLOSED": ("CLOSED", "NOT_SHIPPED", "TIMEOUT"),
}

# 存储值已经进入历史迁移和事件账本，不重写；API 使用 §8.10 的冻结词汇。
# 新订单写入先 from_api，订单响应组装先 to_api，不让传输枚举直接进入存储映射。
_CLOSE_REASON_TO_API = {
    "CUSTOMER_CANCEL": "USER_CANCELLED",
    "TIMEOUT": "PAYMENT_TIMEOUT",
}
_CLOSE_REASON_FROM_API = {public: stored for stored, public in _CLOSE_REASON_TO_API.items()}


def close_reason_to_api(stored: str | None) -> str | None:
    """将数据库/账本关闭原因转为公开契约值；未知值不能静默下发。"""
    if stored is None:
        return None
    try:
        return _CLOSE_REASON_TO_API[stored]
    except KeyError:
        raise ValueError("未知的订单关闭原因存储值") from None


def close_reason_from_api(public: str | None) -> str | None:
    """将公开关闭原因转为数据库/账本值，供确定性订单服务使用。"""
    if public is None:
        return None
    try:
        return _CLOSE_REASON_FROM_API[public]
    except KeyError:
        raise ValueError("未知的订单关闭原因契约值") from None


def from_legacy_status(status: str) -> tuple[str, str, str | None]:
    """只用于历史回填；未知状态不能被猜测。"""
    return FROM_LEGACY_TABLE[status]


def to_legacy_status(
    payment_status: str, fulfillment_status: str, close_reason: str | None = None
) -> str:
    """从数据库 v2 投影派生 v1 兼容状态；close_reason 是存储值。"""
    if payment_status == "PENDING" and fulfillment_status == "NOT_SHIPPED" and close_reason is None:
        return "CREATED"
    if payment_status == "PAID" and close_reason is None:
        if fulfillment_status == "NOT_SHIPPED":
            return "PAID"
        if fulfillment_status in {"SHIPPED", "IN_TRANSIT", "OUT_FOR_DELIVERY"}:
            return "SHIPPED"
        if fulfillment_status == "DELIVERED":
            return "COMPLETED"
    if payment_status == "CLOSED" and fulfillment_status == "NOT_SHIPPED":
        if close_reason == "CUSTOMER_CANCEL":
            return "CANCELLED"
        if close_reason == "TIMEOUT":
            return "CLOSED"
    raise ValueError("非法订单投影组合")
