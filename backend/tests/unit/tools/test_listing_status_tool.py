"""`draft_listing_status` 的注册形状（不触库）：只给商家、只起草、不对 MCP 开放。"""

from __future__ import annotations

from typing import cast

import pytest
from pydantic import ValidationError

from app.db.session import Database
from app.schemas.v2.drafts import DraftKind
from app.services.v2.inventory_alerts import AlertRules
from app.tools.merchant.inventory import DraftListingStatusArgs, build_inventory_tools
from app.tools.registry import ToolRegistry
from app.tools.types import ToolRole, WritePolicy


def _spec():  # type: ignore[no-untyped-def]
    tools = build_inventory_tools(cast(Database, object()), rules=AlertRules())
    return next(tool for tool in tools if tool.name == "draft_listing_status")


def test_spec_is_merchant_only_draft_with_provenance_and_guardrail() -> None:
    spec = _spec()
    assert spec.roles == frozenset({ToolRole.MERCHANT})
    assert ToolRole.MCP_READONLY not in spec.roles
    assert spec.write_policy is WritePolicy.MERCHANT_DRAFT
    assert spec.parallelizable is False
    assert spec.draft_kind is DraftKind.LISTING_STATUS
    assert spec.guardrail is not None
    assert [(ref.arg, ref.object_type) for ref in spec.provenance_refs] == [
        ("product_id", "PRODUCT")
    ]
    assert "不会直接上下架" in spec.description and "审批界面" in spec.description


def test_spec_passes_registry_self_check_and_stays_off_mcp_surface() -> None:
    registry = ToolRegistry()
    for tool in build_inventory_tools(cast(Database, object()), rules=AlertRules()):
        registry.register(tool)
    assert "draft_listing_status" not in {t.name for t in registry.surface_for_mcp()}


def test_args_accept_only_pause_or_activate() -> None:
    assert DraftListingStatusArgs(product_id="p", action="PAUSE").action == "PAUSE"
    assert DraftListingStatusArgs(product_id="p", action="ACTIVATE").action == "ACTIVATE"
    with pytest.raises(ValidationError):
        DraftListingStatusArgs.model_validate({"product_id": "p", "action": "DELETE"})
    with pytest.raises(ValidationError):
        DraftListingStatusArgs.model_validate({"product_id": "p", "action": "PAUSE", "x": 1})
