"""N3 阶段 C Task 6：规则与指标口径问答工具（`get_metric_definition`、`search_rules`）。

只测 `resolve_metric_definition`/`resolve_rule_search` 这两个纯函数（`build_definitions_tools`
只是把它们接到真实 `Database`/仓储上，接线本身由 app 启动自检与集成测试覆盖）。
`get_metric_definition` 只读前两层受控资产，**不触发 LLM 生成候选口径**（R3：真实/可能产生
费用的调用需要单独审批，工具面默认零费用）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest

from app.knowledge.retrieval import KnowledgeRetrieval
from app.tools.merchant.definitions import resolve_metric_definition, resolve_rule_search


@dataclass
class _FakeMetricRow:
    metric_code: str
    display_name: str
    unit: str
    business_definition: str
    sql_definition: str
    owner: str
    status: str
    dimensions: list[str] = field(default_factory=list)
    source_database: str = ""
    source_table: str = ""
    report_url: str | None = None
    updated_at: datetime = datetime(2026, 9, 27, tzinfo=UTC)


class _FakeMetricRepository:
    def __init__(self, rows: dict[str, _FakeMetricRow]) -> None:
        self._rows = rows

    async def get_by_code(self, metric_code: str) -> _FakeMetricRow | None:
        return self._rows.get(metric_code)


class _FakeDocument:
    def __init__(self, source_path: str, title: str, content: str) -> None:
        self.source_path = source_path
        self.title = title
        self.content = content
        self.is_complete = True
        self.status = "ACTIVE"


class _FakeKnowledgeRepository:
    def __init__(self, documents: list[_FakeDocument]) -> None:
        self._documents = documents

    async def list_active(self) -> list[_FakeDocument]:
        return self._documents


@pytest.mark.asyncio
async def test_sql_caliber_is_display_only_and_never_executed() -> None:
    """R4：SQL 口径只供人核对——这里断言仓储层的返回值原样透传，没有被拿去跑 SQL。"""

    rows = {
        "net_gmv": _FakeMetricRow(
            metric_code="net_gmv",
            display_name="净成交额",
            unit="元",
            business_definition="毛成交额减去退款金额",
            sql_definition="SUM(gross_gmv) - SUM(refund_amount)",
            owner="经营分析组",
            status="ACTIVE",
        )
    }
    result = await resolve_metric_definition(
        "net_gmv", metric_repository=_FakeMetricRepository(rows)
    )
    assert result.payload["sql_definition"] == "SUM(gross_gmv) - SUM(refund_amount)"
    assert result.payload["business_definition"] == "毛成交额减去退款金额"
    assert result.payload["definition_version"] == "n3-metric-caliber-v1"


@pytest.mark.asyncio
async def test_unverified_metric_is_labelled_not_generated() -> None:
    """未命中正式目录且未命中字段注释时标 UNVERIFIED，且不触发 LLM 生成候选口径。"""

    result = await resolve_metric_definition(
        "some_field_comment_metric", metric_repository=_FakeMetricRepository({})
    )
    assert result.payload["status"] == "UNVERIFIED"
    assert result.payload["generated"] is False


@pytest.mark.asyncio
async def test_field_comment_hit_is_also_labelled_unverified() -> None:
    """字段注释是二级降级资产，不是正式指标目录；命中它同样要标 UNVERIFIED（不是 ACTIVE）。"""

    result = await resolve_metric_definition("gmv", metric_repository=_FakeMetricRepository({}))
    assert result.payload["status"] == "UNVERIFIED"
    assert result.payload["business_definition"]  # 字段注释确实提供了业务口径
    assert result.payload["generated"] is False


@pytest.mark.asyncio
async def test_metric_definition_shows_business_and_sql_caliber_side_by_side() -> None:
    rows = {
        "gross_gmv": _FakeMetricRow(
            metric_code="gross_gmv",
            display_name="成交总额（毛）",
            unit="元",
            business_definition="已支付订单实付金额之和",
            sql_definition="SUM(orders.paid_amount)",
            owner="经营分析组",
            status="ACTIVE",
            dimensions=["date", "product"],
            source_database="public",
            source_table="orders",
        )
    }
    result = await resolve_metric_definition(
        "gross_gmv", metric_repository=_FakeMetricRepository(rows)
    )
    payload = result.payload
    assert payload["business_definition"] and payload["sql_definition"]
    assert payload["unit"] == "元"
    assert payload["owner"] == "经营分析组"
    assert payload["source_table"] == "orders"
    assert payload["dimensions"] == ["date", "product"]


@pytest.mark.asyncio
async def test_search_rules_cites_matched_document() -> None:
    docs = [
        _FakeDocument("平台规则/after_sale.md", "售后规则", "退货运费由平台承担，商家不需垫付。")
    ]
    retrieval = KnowledgeRetrieval(_FakeKnowledgeRepository(docs))
    result = await resolve_rule_search("退货运费谁出", retrieval=retrieval)
    assert result.payload["matched"] is True
    assert any(hit["source_path"] == "平台规则/after_sale.md" for hit in result.payload["hits"])


@pytest.mark.asyncio
async def test_search_rules_reports_no_match_honestly() -> None:
    retrieval = KnowledgeRetrieval(_FakeKnowledgeRepository([]))
    result = await resolve_rule_search("平台在月球上开店吗", retrieval=retrieval)
    assert result.payload["matched"] is False
    assert result.payload["hits"] == []


def test_get_metric_definition_rejects_empty_code() -> None:
    from pydantic import ValidationError

    from app.tools.merchant.definitions import GetMetricDefinitionArgs

    with pytest.raises(ValidationError):
        GetMetricDefinitionArgs(metric_code="")


def test_search_rules_rejects_empty_query() -> None:
    from pydantic import ValidationError

    from app.tools.merchant.definitions import SearchRulesArgs

    with pytest.raises(ValidationError):
        SearchRulesArgs(query="")
