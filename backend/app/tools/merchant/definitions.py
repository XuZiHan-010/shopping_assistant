"""规则与指标口径问答工具（N3 阶段 C Task 6，PRD M8、S7，Astra N3-4 必审）。

两个只读工具：`get_metric_definition`（复用 v1 指标口径的前两层：正式指标目录、字段注释，
签名与 `app.metrics.catalog.MetricCatalog` 对齐）、`search_rules`（复用 v1
`KnowledgeRetrieval.load_domain()` 按关键词检索）。

**`get_metric_definition` 不触发第三层（LLM 生成候选口径）**：v1 `MetricCatalog.resolve()`
在前两层未命中时会调用 LLM 生成一份"仅供参考"的候选定义，那是真实/可能产生费用的调用（R3），
本工具面默认零费用，未命中时直接标 `UNVERIFIED`，不静默升级成一次真实模型调用。

**回答必须引用知识库文档**（M8）：`search_rules` 的结果结构里带 `source_path`，
调用方（Prompt/Skill）据此要求模型在回答中注明引用来源，工具本身不组织自然语言。

**受控 SQL 口径只供人核对，不回流执行**（R4）：`sql_definition` 只是从受控资产读出的
一段文本，原样透传，本工具从不运行这段 SQL。
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from app.agent.prefilter import tokenize
from app.db.session import Database
from app.knowledge.retrieval import KnowledgeRetrieval
from app.metrics.caliber import METRIC_CALIBER_VERSION, VERSIONED_TRADE_METRICS
from app.metrics.field_comments import find_field_comment
from app.repositories.knowledge import KnowledgeRepository
from app.repositories.metric import MetricRepository
from app.schemas.chat import QuestionCategory
from app.tools.types import ToolContext, ToolOutput, ToolRole, ToolSpec, WritePolicy


class _MetricRowLike(Protocol):
    metric_code: str
    display_name: str
    unit: str
    business_definition: str
    sql_definition: str
    owner: str
    status: str
    dimensions: list[str]
    source_database: str
    source_table: str
    report_url: str | None
    updated_at: datetime


class _MetricRepositoryLike(Protocol):
    async def get_by_code(self, metric_code: str) -> _MetricRowLike | None: ...


class GetMetricDefinitionArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metric_code: str = Field(min_length=1, max_length=64)


class SearchRulesArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=200)


def _unverified_payload(metric_code: str) -> dict[str, object]:
    return {
        "metric_code": metric_code,
        "display_name": metric_code,
        "unit": "",
        "business_definition": "",
        "sql_definition": "",
        "status": "UNVERIFIED",
        "generated": False,
        "owner": "",
        "source_database": "",
        "source_table": "",
        "dimensions": [],
        "report_url": None,
        "definition_version": None,
    }


async def resolve_metric_definition(
    metric_code: str, *, metric_repository: _MetricRepositoryLike
) -> ToolOutput:
    """供 `build_definitions_tools()` 与单测共用的解析逻辑：只读前两层受控资产。"""

    row = await metric_repository.get_by_code(metric_code)
    if row is not None:
        return ToolOutput(
            payload={
                "metric_code": row.metric_code,
                "display_name": row.display_name,
                "unit": row.unit,
                "business_definition": row.business_definition,
                "sql_definition": row.sql_definition,
                "status": row.status,
                "generated": False,
                "owner": row.owner,
                "source_database": row.source_database,
                "source_table": row.source_table,
                "dimensions": list(row.dimensions),
                "report_url": row.report_url,
                "definition_version": (
                    METRIC_CALIBER_VERSION
                    if row.metric_code in VERSIONED_TRADE_METRICS
                    else row.updated_at.isoformat()
                ),
            },
            summary=f"已找到指标「{row.display_name}」的口径定义",
            row_count=1,
        )
    comment = find_field_comment(metric_code)
    if comment is not None:
        return ToolOutput(
            payload={
                "metric_code": metric_code,
                "display_name": metric_code,
                "unit": "",
                "business_definition": comment.business_definition,
                "sql_definition": comment.sql_definition,
                "status": "UNVERIFIED",
                "generated": False,
                "owner": "字段注释",
                "source_database": comment.source_database,
                "source_table": comment.source_table,
                "dimensions": list(comment.dimensions),
                "report_url": None,
                "definition_version": None,
            },
            summary=f"指标 {metric_code} 命中字段注释，标注为待核验",
            row_count=1,
        )
    return ToolOutput(
        payload=_unverified_payload(metric_code),
        summary=f"指标 {metric_code} 未命中正式指标资产，标注为待核验",
        row_count=0,
    )


async def resolve_rule_search(query: str, *, retrieval: KnowledgeRetrieval) -> ToolOutput:
    keywords = tokenize(query)
    result = await retrieval.load_domain(QuestionCategory.PLATFORM_RULE, keywords)
    hits = [
        {"source_path": hit.source_path, "title": hit.title, "content": hit.content}
        for hit in result.hits
    ]
    return ToolOutput(
        payload={"matched": result.matched, "hits": hits},
        summary=(
            f"命中 {len(hits)} 篇平台规则文档" if result.matched else "未在知识库中找到相关规则"
        ),
        row_count=len(hits),
    )


def build_definitions_tools(database: Database) -> tuple[ToolSpec, ...]:
    async def get_metric_definition(ctx: ToolContext, args: GetMetricDefinitionArgs) -> ToolOutput:
        del ctx
        async with database.session() as session:
            return await resolve_metric_definition(
                args.metric_code, metric_repository=MetricRepository(session)
            )

    async def search_rules(ctx: ToolContext, args: SearchRulesArgs) -> ToolOutput:
        del ctx
        async with database.session() as session:
            retrieval = KnowledgeRetrieval(KnowledgeRepository(session))
            return await resolve_rule_search(args.query, retrieval=retrieval)

    return (
        ToolSpec(
            name="get_metric_definition",
            roles=frozenset({ToolRole.MERCHANT, ToolRole.MCP_READONLY}),
            args_model=GetMetricDefinitionArgs,
            write_policy=WritePolicy.READ_ONLY,
            parallelizable=True,
            description=(
                "查询某个指标的正式口径定义，包含业务口径与受控 SQL 口径（仅供核对，"
                "不会被执行）、定义更新时间版本、单位、来源层级、负责人与可用维度。"
                "未命中正式资产时标注待核验且无正式版本。"
            ),
            executor=get_metric_definition,
        ),
        ToolSpec(
            name="search_rules",
            roles=frozenset({ToolRole.MERCHANT, ToolRole.MCP_READONLY}),
            args_model=SearchRulesArgs,
            write_policy=WritePolicy.READ_ONLY,
            parallelizable=True,
            description="按关键词检索平台规则与业务知识库文档，回答须引用命中的文档。",
            executor=search_rules,
        ),
    )
