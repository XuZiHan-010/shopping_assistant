"""过期订单批处理：单笔故障不能饿死同批后续订单。"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.jobs import close_expired_orders as job


@pytest.mark.asyncio
async def test_one_failed_order_does_not_block_later_orders(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempted: list[int] = []
    committed: list[int] = []

    class Session:
        def __init__(self, order_id: int | None) -> None:
            self.order_id = order_id

        async def __aenter__(self) -> Session:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def execute(self, _query: object) -> object:
            return SimpleNamespace(all=lambda: [(1, "shop"), (2, "shop")])

        async def commit(self) -> None:
            assert self.order_id is not None
            committed.append(self.order_id)

    class Database:
        def __init__(self) -> None:
            self.calls = 0

        def session(self) -> Session:
            self.calls += 1
            return Session(None if self.calls == 1 else self.calls - 1)

    async def close_order(_session: Session, *, order_id: int, **_kwargs: object) -> bool:
        attempted.append(order_id)
        if order_id == 1:
            raise RuntimeError("first order failed")
        return True

    monkeypatch.setattr(job, "close_order", close_order)

    with pytest.raises(RuntimeError, match="expired order close failures"):
        await job.close_expired_orders(Database(), now=datetime(2026, 10, 5, tzinfo=UTC))  # type: ignore[arg-type]

    assert attempted == [1, 2]
    assert committed == [2]
