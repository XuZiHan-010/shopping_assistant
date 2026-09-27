"""完整每日简报的排序规则与三源汇总（N3 阶段 C Task 2，PRD M2、D18）。

`rank_brief_items()` 与 `build_full_brief()` 都是纯函数——不接数据库、不接工具，
四个数据源各自的查询早在各自服务里验证过（`inventory_alerts.py`、`customer_signals.py`、
草稿列表）。本文件只测排序规则与"从三源事实组装成简报响应"这一层拼接逻辑本身。

**本次不实现 `METRIC_CHANGE`（指标异常变化）源**：需要新设计一套异常阈值规则，
计划步骤 1 的测试列表也没有对应断言，留给后续单独提议（2026-09-26 裁定）。
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

from app.models.drafts import Draft
from app.models.memory_v2 import CustomerSignal as SignalRow
from app.schemas.v2.merchant_ops import (
    DailyBriefItemKind,
    InventoryAlert,
    InventoryAlertKind,
)
from app.services.v2.daily_brief import (
    REGENERATE_COOLDOWN_SECONDS,
    BriefCandidate,
    build_full_brief,
    is_in_regenerate_cooldown,
    rank_brief_items,
)

NOW = datetime(2026, 9, 26, 12, tzinfo=UTC)


def _candidate(
    *, amount_cents: int | None = None, deadline: datetime | None = None, label: str = "x"
) -> BriefCandidate:
    return BriefCandidate(
        kind="INVENTORY_ALERT", title=label, evidence="证据", amount_cents=amount_cents,
        next_action_prompt=None, deadline=deadline,
    )


def test_higher_amount_ranks_first_among_known_amounts() -> None:
    items = [
        _candidate(amount_cents=100, label="小"),
        _candidate(amount_cents=5000, label="大"),
    ]
    ranked = rank_brief_items(items, now=NOW)
    assert [item.title for item in ranked] == ["大", "小"]


def test_unknown_amount_is_not_sunk_to_bottom() -> None:
    """D18③：金额未知不自动排到末尾——保持在候选列表里原有的相对位置，
    不因为排序函数「不知道往哪排」就默认丢到最后一名。"""

    items = [
        _candidate(amount_cents=5000, label="大额"),
        _candidate(amount_cents=None, label="未知"),
        _candidate(amount_cents=100, label="小额"),
    ]
    ranked = rank_brief_items(items, now=NOW)
    assert ranked[-1].title != "未知"


def test_hard_deadline_can_outrank_amount() -> None:
    """D18③：硬时限可置顶——2 小时后过期的草稿即使金额小，也排在金额大但无时限的前面。"""

    items = [
        _candidate(amount_cents=90000, label="大额无时限"),
        _candidate(amount_cents=200, deadline=NOW + timedelta(hours=2), label="小额有时限"),
    ]
    ranked = rank_brief_items(items, now=NOW)
    assert ranked[0].title == "小额有时限"


def test_multiple_deadlines_rank_by_urgency() -> None:
    items = [
        _candidate(deadline=NOW + timedelta(hours=10), label="较松"),
        _candidate(deadline=NOW + timedelta(hours=1), label="紧急"),
    ]
    ranked = rank_brief_items(items, now=NOW)
    assert [item.title for item in ranked] == ["紧急", "较松"]


def test_expired_deadline_is_still_most_urgent() -> None:
    """已经过期的时限（数据同步延迟等原因导致）仍然算最紧急，不应该被排到后面。"""

    items = [
        _candidate(amount_cents=100000, label="大额无时限"),
        _candidate(deadline=NOW - timedelta(hours=1), label="已过期"),
    ]
    ranked = rank_brief_items(items, now=NOW)
    assert ranked[0].title == "已过期"


def test_rank_is_assigned_from_one_and_contiguous() -> None:
    items = [_candidate(amount_cents=1), _candidate(amount_cents=2), _candidate(amount_cents=3)]
    ranked = rank_brief_items(items, now=NOW)
    assert [item.rank for item in ranked] == [1, 2, 3]


def _alert(product_name: str = "商品") -> InventoryAlert:
    return InventoryAlert(
        id=str(uuid4()), kind=InventoryAlertKind.LOW_STOCK, product_id=str(uuid4()),
        product_name=product_name, stock_on_hand=3, stock_reserved=0, stock_available=3,
        low_stock_threshold=5, sold_last_30d=10, days_of_supply=9,
    )


def _draft(title: str = "草稿", expires_at: datetime | None = None) -> Draft:
    return Draft(
        merchant_id=uuid4(), kind="RESTOCK", title=title, target_type="PRODUCT",
        target_id=uuid4(), target_version=1, draft_version=1, state="STAGED",
        payload={}, guardrail_snapshot={}, created_by="agent",
        expires_at=expires_at or NOW + timedelta(days=1),
    )


def _signal(product_name: str = "商品", count: int = 1) -> SignalRow:
    return SignalRow(
        merchant_id=uuid4(), kind="CONTENT_GAP", product_id=uuid4(), product_name=product_name,
        signal_date=date(2026, 9, 26), count=count,
        derived_from=[{"source_type": "PRODUCT", "source_id": "p1", "content_version": 1}],
        is_ignored=False,
    )


def test_build_full_brief_combines_three_sources() -> None:
    brief = build_full_brief(
        alerts=[_alert()], drafts=[_draft()], signals=[_signal()], now=NOW,
    )
    kinds = {item.kind for item in brief.items}
    assert kinds == {
        DailyBriefItemKind.INVENTORY_ALERT, DailyBriefItemKind.PENDING_DRAFT,
        DailyBriefItemKind.CUSTOMER_SIGNAL,
    }


def test_build_full_brief_collapses_beyond_six_items() -> None:
    alerts = [_alert(product_name=f"商品{i}") for i in range(8)]
    brief = build_full_brief(alerts=alerts, drafts=[], signals=[], now=NOW)
    assert len(brief.items) == 6
    assert brief.collapsed_count == 2


def test_pending_draft_deadline_is_its_expiry() -> None:
    """草稿的硬时限就是它的过期时间——快过期的草稿应该排到前面。"""

    soon = _draft(title="快过期", expires_at=NOW + timedelta(hours=1))
    later = _draft(title="不急", expires_at=NOW + timedelta(days=10))
    brief = build_full_brief(alerts=[], drafts=[later, soon], signals=[], now=NOW)
    assert brief.items[0].title.startswith("待批准：快过期")


def test_full_brief_never_leaks_buyer_identifiers() -> None:
    """D18⑦：顾客信号只用聚合结果，简报响应里不出现 buyer_key 或顾客别名。"""

    brief = build_full_brief(alerts=[], drafts=[], signals=[_signal()], now=NOW)
    dumped = brief.model_dump_json()
    assert "buyer_key" not in dumped and "buyer" not in dumped.lower()


def test_full_brief_carries_business_timezone_and_timestamps() -> None:
    brief = build_full_brief(alerts=[], drafts=[], signals=[], now=NOW, timezone="Asia/Shanghai")
    assert brief.business_timezone == "Asia/Shanghai"
    assert brief.generated_at == NOW
    assert brief.data_as_of == NOW


def test_no_prior_brief_is_never_in_cooldown() -> None:
    """从未生成过（`last_generated_at=None`）不在冷却期内——不能生成的是重复请求，
    不是首次请求。"""

    assert is_in_regenerate_cooldown(None, now=NOW) is False


def test_just_generated_is_in_cooldown() -> None:
    assert is_in_regenerate_cooldown(NOW, now=NOW) is True


def test_cooldown_expires_after_window() -> None:
    last = NOW - timedelta(seconds=REGENERATE_COOLDOWN_SECONDS + 1)
    assert is_in_regenerate_cooldown(last, now=NOW) is False


def test_cooldown_boundary_is_inclusive_of_the_window() -> None:
    last = NOW - timedelta(seconds=REGENERATE_COOLDOWN_SECONDS)
    assert is_in_regenerate_cooldown(last, now=NOW) is False
