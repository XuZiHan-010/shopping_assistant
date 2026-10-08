"""真实模型可能提出未知指标码，工具边界必须受控拒绝。"""

from __future__ import annotations

from typing import cast
from uuid import UUID

import pytest

from app.core.session import SessionContext, SessionRole
from app.db.session import Database
from app.tools.errors import FatalToolError
from app.tools.merchant.metrics import AttributeChangeArgs, build_metrics_tools
from app.tools.types import ToolContext


@pytest.mark.asyncio
async def test_attribute_change_rejects_unknown_metric_before_querying_database() -> None:
    tools = {
        tool.name: tool
        for tool in build_metrics_tools(
            cast(Database, object()), business_timezone="Asia/Shanghai"
        )
    }
    ctx = ToolContext(
        session=SessionContext(
            session_record_id=UUID(int=1),
            role=SessionRole.MERCHANT,
            merchant_id=UUID(int=2),
            buyer_key=None,
            shop_slug=None,
        ),
        conversation_id="synthetic",
        request_id="synthetic",
    )

    with pytest.raises(FatalToolError) as captured:
        await tools["attribute_change"].executor(
            ctx, AttributeChangeArgs(metric="net_sales", dimension="category")
        )
    assert captured.value.gate == "unknown_metric"


def test_attribute_change_schema_names_the_net_gmv_code() -> None:
    description = AttributeChangeArgs.model_json_schema()["properties"]["metric"]["description"]
    assert "net_gmv" in description
