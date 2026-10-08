"""草稿应用按种类分派（N3 阶段 A Task 5）——分派表本身的单测。

骨架（锁 → 状态 → 过期 → 草案版本 → 证据）只写一份；第 5–7 步（目标复检、护栏复检、条件写入与
领域事件）交给按种类注册的处理器。B、C 往表里加 `AFTER_SALE_DECISION` / `CONTENT_CHANGE` /
`PRICE_CHANGE` / `COUPON` 时，重复注册与漏注册都在启动期失败。
"""

from __future__ import annotations

from dataclasses import fields

import pytest

from app.schemas.v2.drafts import DraftKind
from app.services.v2 import draft_apply
from app.services.v2.draft_handlers import (
    ENABLED_DRAFT_KINDS,
    HandlerRequest,
    HandlerResult,
    build_handler_table,
    check_enabled,
    default_handler_table,
    default_handlers,
)
from app.services.v2.draft_handlers.restock import RestockHandler


def test_duplicate_handler_registration_fails() -> None:
    with pytest.raises(ValueError, match="RESTOCK"):
        build_handler_table([RestockHandler(), RestockHandler()])


def test_every_enabled_kind_has_a_handler() -> None:
    table = build_handler_table(default_handlers())
    assert set(table) >= ENABLED_DRAFT_KINDS


def test_missing_handler_for_enabled_kind_fails_self_check() -> None:
    with pytest.raises(RuntimeError, match="RESTOCK"):
        check_enabled(build_handler_table([]))


def test_restock_price_change_and_coupon_are_enabled() -> None:
    """N3 阶段 C 注册了 PRICE_CHANGE、COUPON；阶段 B 的 AFTER_SALE_DECISION 由 B 自己加入。"""
    assert {DraftKind.RESTOCK, DraftKind.PRICE_CHANGE, DraftKind.COUPON} <= ENABLED_DRAFT_KINDS


def test_apply_service_uses_the_self_checked_default_table() -> None:
    assert set(draft_apply.HANDLERS) == set(default_handler_table())
    assert isinstance(draft_apply.HANDLERS[DraftKind.RESTOCK], RestockHandler)


def test_handler_request_has_no_evidence_field() -> None:
    """证据在骨架里消费；处理器的请求类型在结构上就放不进证据。"""
    assert {f.name for f in fields(HandlerRequest)} == {
        "draft_version",
        "target_version",
        "accepted_entry_ids",
    }


def test_skeleton_no_longer_hardcodes_restock() -> None:
    import inspect

    source = inspect.getsource(draft_apply)
    assert "_apply_restock" not in source
    assert "NotImplementedError" not in source
    assert "restock_entry_id" not in source


def test_handler_result_must_be_an_applied_result() -> None:
    """骨架无论如何都把草稿置 APPLIED；账本结果若是别的值，两条记录就互相矛盾。"""
    with pytest.raises(ValueError, match="APPLIED"):
        HandlerResult(checks=[], applied_entry_ids=["e1"], ledger_result="FAILED")


@pytest.mark.parametrize("entries", [[], ["e1", "e1"], [f"e{i}" for i in range(101)]])
def test_handler_result_entry_ids_follow_the_ledger_contract(entries: list[str]) -> None:
    """契约 §8.13：`applied_entry_ids` 1–100 项、不重复；处理器写错时当场失败，不等到序列化响应。"""
    with pytest.raises(ValueError, match="applied_entry_ids"):
        HandlerResult(checks=[], applied_entry_ids=entries)
