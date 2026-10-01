"""订单摘要批量查询的商家边界：一次调用只能覆盖同一商家的订单（R5）。"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest

from app.services.v2.orders import last_event_times, order_leads


def _orders_of_two_merchants() -> list[Any]:
    return [SimpleNamespace(id=uuid4(), merchant_id=uuid4()) for _ in range(2)]


@pytest.mark.asyncio
@pytest.mark.parametrize("batch", [order_leads, last_event_times])
async def test_batches_refuse_orders_from_different_merchants(batch: Any) -> None:
    # 断言发生在访问数据库之前，所以不需要真实会话。
    with pytest.raises(AssertionError, match="同一商家"):
        await batch(cast(Any, None), _orders_of_two_merchants())


@pytest.mark.asyncio
@pytest.mark.parametrize("batch", [order_leads, last_event_times])
async def test_batches_skip_the_query_for_an_empty_page(batch: Any) -> None:
    assert await batch(cast(Any, None), []) == {}
