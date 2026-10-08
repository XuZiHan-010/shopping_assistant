"""记忆存储主体守卫（N4-1①：仓储方法签名不接受调用方传入主体，只接受已解析的会话上下文）。"""

from __future__ import annotations

import inspect
import re
from pathlib import Path
from uuid import uuid4

import pytest

from app.core.session import SessionContext, SessionRole
from app.memory.customer_store import CustomerMemoryStore
from app.memory.merchant_store import MerchantMemoryStore
from app.memory.owners import CustomerMemoryOwner, MerchantMemoryOwner

APP_ROOT = Path(__file__).resolve().parents[3] / "app"
MERCHANT = uuid4()


def _ctx(role: SessionRole, buyer_key: str | None) -> SessionContext:
    return SessionContext(
        session_record_id=uuid4(), role=role, merchant_id=MERCHANT,
        buyer_key=buyer_key, shop_slug="shop" if role is SessionRole.CUSTOMER else None,
    )


def test_owner_cannot_be_constructed_directly() -> None:
    with pytest.raises(TypeError):
        CustomerMemoryOwner(MERCHANT, "buyer")
    with pytest.raises(TypeError):
        MerchantMemoryOwner(MERCHANT)


def test_owner_follows_session_role_and_binding() -> None:
    assert CustomerMemoryOwner.from_session(_ctx(SessionRole.CUSTOMER, None)) is None  # 访客
    assert CustomerMemoryOwner.from_session(_ctx(SessionRole.MERCHANT, None)) is None
    assert MerchantMemoryOwner.from_session(_ctx(SessionRole.CUSTOMER, "buyer")) is None
    bound = CustomerMemoryOwner.from_session(_ctx(SessionRole.CUSTOMER, "buyer"))
    assert bound is not None and (bound.merchant_id, bound.buyer_key) == (MERCHANT, "buyer")


@pytest.mark.parametrize("store", [CustomerMemoryStore, MerchantMemoryStore])
def test_store_methods_take_no_principal_parameters(store: type) -> None:
    for name, member in inspect.getmembers(store, inspect.iscoroutinefunction):
        if name.startswith("_"):
            continue
        params = set(inspect.signature(member).parameters)
        assert not params & {"merchant_id", "buyer_key"}, f"{store.__name__}.{name}"


def test_store_rejects_anything_but_an_owner() -> None:
    with pytest.raises(TypeError):
        CustomerMemoryStore(object(), MERCHANT)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        MerchantMemoryStore(object(), MERCHANT)  # type: ignore[arg-type]


def test_non_session_factories_are_only_used_by_jobs() -> None:
    """`from_verified_turn` / `from_maintenance_row` 只能由已三方核对或读库内行的后台任务使用。"""

    pattern = re.compile(r"\.(from_verified_turn|from_maintenance_row)\(")
    offenders = [
        str(path.relative_to(APP_ROOT))
        for path in APP_ROOT.rglob("*.py")
        if path.relative_to(APP_ROOT).parts[0] != "jobs"
        and path.name != "owners.py"
        and pattern.search(path.read_text(encoding="utf-8"))
    ]
    assert offenders == []


def test_owner_cannot_be_rewritten_after_creation() -> None:
    """复审 F5：主体只读，`dataclasses.replace` 不能借信任令牌复制出另一个主体。"""

    import dataclasses

    owner = CustomerMemoryOwner.from_session(_ctx(SessionRole.CUSTOMER, "buyer"))
    assert owner is not None
    with pytest.raises(TypeError):
        dataclasses.replace(owner, buyer_key="someone-else")  # type: ignore[type-var]
    with pytest.raises(AttributeError):
        owner.buyer_key = "someone-else"  # type: ignore[misc]
    assert "buyer" not in repr(owner)  # 不在日志里打印身份原值


def test_trust_token_is_not_used_outside_owners_module() -> None:
    offenders = [
        str(path.relative_to(APP_ROOT))
        for path in APP_ROOT.rglob("*.py")
        if path.name != "owners.py" and "_TRUSTED" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []
