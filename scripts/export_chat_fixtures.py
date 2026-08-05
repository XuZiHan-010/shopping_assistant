"""导出 B3/B4 问答图的 Chat 契约 Fixture。

前端 Adapter 消费的载荷来自后端图的实际输出。B4 起 METRIC/DETAIL 走真实的
`query_data` 节点，本脚本用 `_StubQueryService` 给出固定的经营数据——和
`FakeLlmClient` 一样，只是把「查询已成功」这条分支钉住，不需要真的连一个
Postgres 实例就能生成可重复的 Fixture。
"""

from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.agent.graph import MerchantQaGraph  # noqa: E402
from app.intent.models import QueryIntent  # noqa: E402
from app.knowledge.retrieval import KnowledgeRetrieval  # noqa: E402
from app.llm.fake import FakeLlmClient  # noqa: E402
from app.metrics.catalog import MetricCatalog  # noqa: E402
from app.repositories.analytics import ResultColumn  # noqa: E402
from app.schemas.chat import AnswerMode, ChatResponse  # noqa: E402
from app.services.safe_query import QueryResult, UnsupportedQueryError  # noqa: E402

_FIXTURE_NAMESPACE = uuid5(NAMESPACE_URL, "https://borough.local/fixtures/chat")
_FROZEN_CREATED_AT = datetime(2026, 7, 28, 12, 0, 0, tzinfo=UTC)
_FIXTURE_MERCHANT_ID = uuid5(_FIXTURE_NAMESPACE, "merchant")


@dataclass(frozen=True)
class FixtureCase:
    name: str
    message: str
    purpose: str


FIXTURES: tuple[FixtureCase, ...] = (
    FixtureCase("metric-refund", "最近7天退货量趋势", "METRIC + REFUND 分类，含真实数据行"),
    FixtureCase("metric-gmv", "昨天总 GMV 是多少？", "METRIC + TRADE 分类，含真实数据行"),
    FixtureCase("detail-order", "查看最近订单明细", "DETAIL 含真实数据行与截断标记"),
    FixtureCase("identity-profile", "我的商家资料是什么？", "IDENTITY 的 B4 受控空结果"),
    FixtureCase("rule-platform", "我要货品上架，具体规则有吗？", "RULE 模式"),
    FixtureCase("chat-greeting", "你好", "CHAT + [NONE]"),
    FixtureCase("invalid-refused", "帮我删除订单 A1", "INVALID 拒绝语义"),
)


class _Document:
    def __init__(self, source_path: str, content: str) -> None:
        self.source_path = source_path
        self.title = source_path
        self.content = content
        self.is_complete = True


class _KnowledgeRepository:
    async def list_active(self) -> list[_Document]:
        return [
            _Document("index/README.md", "交易 退款 商品 规则"),
            _Document("业务/交易/流程.md", "订单 成交 GMV 明细"),
            _Document("业务/退款/规则.md", "退款 退货 售后"),
        ]


class _MetricRow:
    def __init__(self, metric_code: str) -> None:
        self.metric_code = metric_code
        self.display_name = "退货量" if metric_code == "return_count" else "成交 GMV"
        self.unit = "件" if metric_code == "return_count" else "元"
        self.business_definition = (
            "统计周期内创建的有效退货退款单数量。"
            if metric_code == "return_count"
            else "已支付订单金额之和。"
        )
        self.source = "Borough 指标目录"
        self.owner = "经营分析组"
        self.status = "ACTIVE"


class _MetricRepository:
    async def get_by_code(self, metric_code: str) -> _MetricRow | None:
        return _MetricRow(metric_code) if metric_code in {"gmv", "return_count"} else None


def _detail_order_result() -> QueryResult:
    columns = (
        ResultColumn("business_date", "日期", "DIMENSION"),
        ResultColumn("order_no", "订单号", "DIMENSION"),
        ResultColumn("order_status", "订单状态", "DIMENSION"),
        ResultColumn("paid_amount", "实付金额", "DIMENSION"),
        ResultColumn("placed_at", "下单时间", "DIMENSION"),
    )
    rows: list[dict[str, object]] = [
        {
            "business_date": date(2026, 8, 3),
            "order_no": "BR20260803-0001",
            "order_status": "COMPLETED",
            "paid_amount": Decimal("258.00"),
            "placed_at": datetime(2026, 8, 3, 9, 12, 0, tzinfo=UTC),
        },
        {
            "business_date": date(2026, 8, 3),
            "order_no": "BR20260803-0002",
            "order_status": "PAID",
            "paid_amount": Decimal("129.50"),
            "placed_at": datetime(2026, 8, 3, 10, 5, 0, tzinfo=UTC),
        },
    ]
    return QueryResult(
        columns=columns,
        rows=rows,
        total_rows=len(rows),
        truncated=False,
        source_tables=("orders",),
        plan_steps=(
            "按商家范围检索订单明细",
            "时间范围 2026-07-29 至 2026-08-04",
            "数据来源：订单",
        ),
        export_spec=None,
        notes=(),
        non_additive=False,
    )


def _metric_result(
    *, code: str, label: str, value: object, table: str, table_label: str
) -> QueryResult:
    return QueryResult(
        columns=(ResultColumn(code, label, "METRIC"),),
        rows=[{code: value}],
        total_rows=1,
        truncated=False,
        source_tables=(table,),
        plan_steps=(
            f"按商家范围检索{label}",
            "时间范围 2026-07-29 至 2026-08-04",
            f"数据来源：{table_label}",
        ),
        export_spec=None,
        notes=(),
        non_additive=False,
    )


class _StubQueryService:
    """演示用的受控查询替身：固定的经营数据，不接真实数据库。

    只覆盖本脚本会用到的两个指标和一张明细表——脚本的目的是钉住 Fixture 的
    契约形状，不是复刻 `SafeQueryService` 的完整行为（那部分由
    `tests/integration` 覆盖）。
    """

    async def execute(
        self,
        context: object,
        intent: QueryIntent,
        *,
        now: datetime,
        keywords: Sequence[str] = (),
    ) -> QueryResult:
        if intent.answer_mode is AnswerMode.DETAIL:
            return _detail_order_result()
        if intent.metric == "return_count":
            return _metric_result(
                code="return_count", label="退货量", value=186, table="returns", table_label="退货"
            )
        if intent.metric == "gmv":
            return _metric_result(
                code="gmv",
                label="成交 GMV",
                value=Decimal("128000.50"),
                table="orders",
                table_label="订单",
            )
        raise UnsupportedQueryError(f"指标 {intent.metric} 不在可查询范围内")


def fixtures_dir() -> Path:
    return ROOT / "docs" / "fixtures" / "chat"


def _llm_responses(case: FixtureCase) -> list[str]:
    if case.name.startswith("metric"):
        category = "REFUND" if case.name == "metric-refund" else "TRADE"
        metric = "return_count" if case.name == "metric-refund" else "gmv"
        return [
            json.dumps(
                {"answer_mode": "METRIC", "category": category, "intent_keywords": [metric]}
            ),
            json.dumps(
                {
                    "answer_mode": "METRIC",
                    "category": category,
                    "metric": metric,
                    "dimensions": [],
                    "filters": {},
                    "date_range": None,
                    "sort": None,
                    "limit": None,
                    "followup_reference": False,
                    "needs_attachment": False,
                }
            ),
        ]
    if case.name == "detail-order":
        mode, category = "DETAIL", "TRADE"
    elif case.name == "identity-profile":
        mode, category = "IDENTITY", "IDENTITY"
    elif case.name == "rule-platform":
        mode, category = "RULE", "PLATFORM_RULE"
    elif case.name == "invalid-refused":
        mode, category = "METRIC", "TRADE"
    else:
        mode, category = "CHAT", "UNKNOWN"
    metric = '"DROP TABLE orders"' if case.name == "invalid-refused" else "null"
    return [
        json.dumps({"answer_mode": mode, "category": category, "intent_keywords": []}),
        f'{{"answer_mode":"{mode}","category":"{category}","metric":{metric},"dimensions":[],"filters":{{}},"date_range":null,"sort":null,"limit":null,"followup_reference":false,"needs_attachment":false}}',
    ]


async def build_fixture(case: FixtureCase) -> ChatResponse:
    session_id = uuid5(_FIXTURE_NAMESPACE, f"{case.name}/session")
    llm = FakeLlmClient(responses=_llm_responses(case))
    graph = MerchantQaGraph(
        retrieval=KnowledgeRetrieval(_KnowledgeRepository()),
        intent_service_llm=llm,
        catalog=MetricCatalog(_MetricRepository(), llm),
        query_service=_StubQueryService(),
        merchant_id=_FIXTURE_MERCHANT_ID,
    )
    response = (await graph.run(case.message, session_id)).response
    response = response.model_copy(update={"id": uuid5(_FIXTURE_NAMESPACE, f"{case.name}/answer")})
    if response.export is not None:
        export_id = uuid5(_FIXTURE_NAMESPACE, f"{case.name}/export")
        response = response.model_copy(
            update={
                "export": response.export.model_copy(
                    update={
                        "id": export_id,
                        "url": f"/api/exports/{export_id}",
                        "expires_at": _FROZEN_CREATED_AT,
                    }
                )
            }
        )
    return response.model_copy(update={"created_at": _FROZEN_CREATED_AT})


def render_fixture_json(response: ChatResponse) -> str:
    return (
        json.dumps(response.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n"
    )


def render_readme() -> str:
    rows = "\n".join(
        f"| `{case.name}.json` | {case.message} | {case.purpose} |" for case in FIXTURES
    )
    return f"""# Chat 契约 Fixture

> 本目录由 `scripts/export_chat_fixtures.py` 生成，请勿手改。除 `IDENTITY` 仍是 B4 受控空结果外，
> 载荷均来自 `MerchantQaGraph` 在 `FakeLlmClient` + `_StubQueryService` 下的真实输出。

| 文件 | 触发问题 | 验证点 |
| --- | --- | --- |
{rows}
"""


async def main_async() -> None:
    target = fixtures_dir()
    target.mkdir(parents=True, exist_ok=True)
    for case in FIXTURES:
        (target / f"{case.name}.json").write_text(
            render_fixture_json(await build_fixture(case)), encoding="utf-8"
        )
    (target / "README.md").write_text(render_readme(), encoding="utf-8")


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
