"""压缩锚点（N4-A Task 1，PRD A5，契约 §6.12）：三项必保留信息先抽出、压缩后回填。

锚点只从**本回合**的工具结果抽取（Task 1 步骤 0 的结论：历史只回放文字，其中的数字按 D-N4-1
不是事实来源，模型须重新调用工具），按字段白名单取值，身份字段一概不进。
"""

from __future__ import annotations

from typing import Any

from app.agent.loop.compaction.anchors import (
    CompactionAnchors,
    DataCutoff,
    DraftRef,
    ToolSourceRef,
    extract_anchors,
    format_anchors,
    render_anchors,
)
from app.agent.loop.fencing import FENCE_NOTICE
from app.core.errors import ErrorCode
from app.localization.locales import SupportedLocale
from app.schemas.v2.common import ToolDisplayStatus
from app.tools.types import ToolDisplay, ToolOutcome, ToolResult

MERCHANT_UUID = "7d8f7a2e-1111-4a4a-9c9c-000000000001"


def _result(
    tool: str,
    call_id: str,
    payload: Any,
    *,
    ok: bool = True,
    outcome: ToolOutcome = ToolOutcome.SUCCEEDED,
    summary: str = "",
) -> ToolResult:
    return ToolResult(
        ok=ok,
        payload=payload,
        display=ToolDisplay(
            tool_name=tool,
            call_id=call_id,
            status=ToolDisplayStatus.SUCCEEDED if ok else ToolDisplayStatus.FAILED,
            duration_ms=1,
            row_count=None,
        ),
        reason_code=None if ok else ErrorCode.INVALID_REQUEST,
        outcome=outcome,
        summary=summary,
    )


def _metric(call_id: str = "c1") -> ToolResult:
    return _result(
        "query_metrics",
        call_id,
        {
            "metric": "gross_gmv",
            "value": "12345.00",
            "data_cutoff": "2026-09-21T09:00:00+00:00",
            "source": "REALTIME",
            "definition_version": "v3",
        },
        summary="gross_gmv 在 2026-09-14 至 2026-09-20 的查询已完成",
    )


def _draft(draft_id: str = "d-1") -> ToolResult:
    return _result(
        "draft_restock",
        "c2",
        {"draft_id": draft_id, "kind": "RESTOCK", "draft_version": 1},
        outcome=ToolOutcome.DRAFT_CREATED,
        summary="已起草补货：羊绒围巾 +20",
    )


def test_metric_result_yields_cutoff_and_source_with_value() -> None:
    anchors = extract_anchors([_metric()])

    assert anchors.data_cutoffs == (
        DataCutoff(
            metric="gross_gmv",
            cutoff="2026-09-21T09:00:00+00:00",
            source="REALTIME",
            definition_version="v3",
            ref="query_metrics#c1",
        ),
    )
    assert anchors.tool_sources == (
        ToolSourceRef(
            tool_name="query_metrics",
            call_id="c1",
            summary="gross_gmv 在 2026-09-14 至 2026-09-20 的查询已完成",
            value="12345.00",
        ),
    )


def test_draft_result_yields_draft_version() -> None:
    anchors = extract_anchors([_draft()])

    assert anchors.draft_versions == (
        DraftRef(draft_id="d-1", draft_version=1, ref="draft_restock#c2", kind="RESTOCK"),
    )


def test_failed_calls_and_skill_loads_are_not_anchors() -> None:
    from app.skills.spec import SkillSpec

    failed = _result("query_metrics", "c3", None, ok=False, outcome=ToolOutcome.REJECTED)
    skill = _result("load_skill", "c4", SkillSpec.__new__(SkillSpec))

    assert extract_anchors([failed, skill]) == CompactionAnchors()


def test_anchors_never_carry_identity_fields() -> None:
    leaky = _result(
        "query_metrics",
        "c5",
        {
            "metric": "gross_gmv",
            "value": "1",
            "data_cutoff": "2026-09-21T09:00:00+00:00",
            "source": "REALTIME",
            "definition_version": "v3",
            "merchant_id": MERCHANT_UUID,
            "buyer_key": "bk-secret",
        },
    )

    anchors = extract_anchors([leaky])
    rendered = render_anchors(anchors, SupportedLocale.ZH_CN)

    for text in (repr(anchors), rendered):
        assert "merchant_id" not in text and MERCHANT_UUID not in text
        assert "buyer_key" not in text and "bk-secret" not in text


def test_rendered_anchors_are_fenced_and_deterministic() -> None:
    anchors = extract_anchors([_metric(), _draft()])

    rendered = render_anchors(anchors, SupportedLocale.ZH_CN)

    assert FENCE_NOTICE in rendered  # 源自工具结果，照常按外部文本围栏（A11）
    assert "2026-09-21T09:00:00+00:00" in rendered and "v3" in rendered
    assert "d-1" in rendered and "12345.00" in rendered
    # 围栏 ID 每次随机（防伪造闭合）；围栏内的正文必须确定性序列化，便于测试与提示词缓存（A9）。
    body = format_anchors(anchors, SupportedLocale.ZH_CN)
    assert body in rendered
    assert body == format_anchors(extract_anchors([_metric(), _draft()]), SupportedLocale.ZH_CN)


def test_metric_value_and_its_provenance_share_one_source_line() -> None:
    anchors = extract_anchors([_metric()])

    for locale in (SupportedLocale.ZH_CN, SupportedLocale.EN_US):
        line = next(
            line
            for line in format_anchors(anchors, locale).splitlines()
            if line.startswith("- query_metrics#c1:")
        )
        for expected in ("12345.00", "REALTIME", "2026-09-21T09:00:00+00:00", "v3"):
            assert expected in line


def test_empty_anchors_render_nothing() -> None:
    assert render_anchors(CompactionAnchors(), SupportedLocale.ZH_CN) == ""


def test_cutoff_line_names_its_call_so_value_and_version_link_up() -> None:
    """同一次调用的来源、数值、截至时间和定义版本必须并排，且不同调用不混淆。"""

    body = format_anchors(extract_anchors([_metric("c1"), _metric("c7")]), SupportedLocale.ZH_CN)

    cutoff_lines = [line for line in body.splitlines() if "2026-09-21T09:00:00+00:00" in line]
    assert len(cutoff_lines) == 2
    assert "query_metrics#c1" in cutoff_lines[0] and "v3" in cutoff_lines[0]
    assert "query_metrics#c7" in cutoff_lines[1]


def test_each_draft_stays_linked_to_its_own_call_and_kind() -> None:
    """多个草稿不能只留下游离 ID/版本列表，导致把补货草稿当作优惠券。"""
    results = [
        _result(
            "draft_restock",
            "c2",
            {"draft_id": "restock-1", "draft_version": 2, "kind": "RESTOCK"},
            outcome=ToolOutcome.DRAFT_CREATED,
        ),
        _result(
            "draft_coupon",
            "c8",
            {"draft_id": "coupon-1", "draft_version": 7, "kind": "COUPON"},
            outcome=ToolOutcome.DRAFT_CREATED,
        ),
    ]
    for locale in SupportedLocale:
        body = format_anchors(extract_anchors(results), locale)
        restock = next(line for line in body.splitlines() if line.startswith("- draft_restock#c2:"))
        coupon = next(line for line in body.splitlines() if line.startswith("- draft_coupon#c8:"))
        assert "restock-1" in restock and "2" in restock and "RESTOCK" in restock
        assert "coupon-1" not in restock
        assert "coupon-1" in coupon and "7" in coupon and "COUPON" in coupon
        assert "restock-1" not in coupon


def test_boolean_draft_version_is_not_a_valid_anchor() -> None:
    result = _result(
        "draft_coupon",
        "c1",
        {"draft_id": "d-1", "draft_version": True},
        outcome=ToolOutcome.DRAFT_CREATED,
    )
    assert extract_anchors([result]).draft_versions == ()
