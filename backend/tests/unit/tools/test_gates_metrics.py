"""闸门为运维看板计数工具调用与失败（N5 B Task 3；PRD §10.4）。"""

from __future__ import annotations

from uuid import UUID

import pytest
from pydantic import BaseModel, ConfigDict

from app.core.metrics import OperationalMetrics
from app.core.session import SessionContext, SessionRole
from app.tools.errors import FatalToolError
from app.tools.gates import ToolGates
from app.tools.registry import build_tool_registry
from app.tools.types import ToolContext, ToolOutput, ToolRole, ToolSpec, WritePolicy

from .tool_doubles import PRINCIPAL_SECRET, InMemoryProvenance, RecordingAudit


class MetricArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    metric: str


async def read_metric(ctx: ToolContext, args: MetricArgs) -> ToolOutput:
    return ToolOutput(payload={"metric": args.metric}, summary="ok")


def _ctx() -> ToolContext:
    return ToolContext(
        session=SessionContext(
            session_record_id=UUID(int=1),
            role=SessionRole.MERCHANT,
            merchant_id=UUID(int=2),
            buyer_key=None,
            shop_slug=None,
        ),
        conversation_id="c",
        request_id="r",
    )


async def test_gates_count_successes_failures_and_blocks() -> None:
    metrics = OperationalMetrics()
    registry = build_tool_registry(
        (
            ToolSpec(
                name="read_metric",
                roles=frozenset({ToolRole.MERCHANT}),
                args_model=MetricArgs,
                write_policy=WritePolicy.READ_ONLY,
                parallelizable=True,
                description="读指标",
                executor=read_metric,
            ),
        )
    )
    gates = ToolGates(
        registry,
        provenance=InMemoryProvenance(),
        principal_secret=PRINCIPAL_SECRET,
        audit=RecordingAudit(),
        metrics=metrics,
    )

    assert (await gates.invoke(_ctx(), "read_metric", {"metric": "gmv"})).ok
    assert not (await gates.invoke(_ctx(), "read_metric", {"wrong": 1})).ok
    assert not (await gates.invoke(_ctx(), "no_such_tool", {})).ok
    with pytest.raises(FatalToolError):
        await gates.invoke(_ctx(), "read_metric", {"metric": "gmv", "merchant_id": "x"})

    assert (metrics.tool_calls_total, metrics.tool_errors_total) == (4, 3)
