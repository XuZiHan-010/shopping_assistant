"""导出 B3 问答图的 Chat 契约 Fixture。

前端 Adapter 消费的载荷来自后端图的实际输出；DETAIL 是 B4 查询节点的受控空结果，
用于在 B4 完成前固定其契约形状。
"""

from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.agent.graph import MerchantQaGraph  # noqa: E402
from app.knowledge.retrieval import KnowledgeRetrieval  # noqa: E402
from app.llm.fake import FakeLlmClient  # noqa: E402
from app.metrics.catalog import MetricCatalog  # noqa: E402
from app.schemas.chat import ChatResponse  # noqa: E402

_FIXTURE_NAMESPACE = uuid5(NAMESPACE_URL, "https://borough.local/fixtures/chat")
_FROZEN_CREATED_AT = datetime(2026, 7, 28, 12, 0, 0, tzinfo=UTC)


@dataclass(frozen=True)
class FixtureCase:
    name: str
    message: str
    purpose: str


FIXTURES: tuple[FixtureCase, ...] = (
    FixtureCase("metric-refund", "最近7天退货量趋势", "METRIC 受控降级"),
    FixtureCase("metric-gmv", "昨天总 GMV 是多少？", "METRIC + TRADE 分类"),
    FixtureCase("detail-order", "查看最近订单明细", "DETAIL 的 B4 受控空结果"),
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


def fixtures_dir() -> Path:
    return ROOT / "docs" / "fixtures" / "chat"


def _llm_responses(case: FixtureCase) -> list[str]:
    if case.name.startswith("metric"):
        category = "REFUND" if case.name == "metric-refund" else "TRADE"
        metric = "return_count" if case.name == "metric-refund" else "gmv"
        return [
            json.dumps({"answer_mode": "METRIC", "category": category, "intent_keywords": [metric]}),
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
    return json.dumps(response.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def render_readme() -> str:
    rows = "\n".join(f"| `{case.name}.json` | {case.message} | {case.purpose} |" for case in FIXTURES)
    return f"""# Chat 契约 Fixture

> 本目录由 `scripts/export_chat_fixtures.py` 生成，请勿手改。除 `DETAIL` 的 B4 受控空结果外，
> 载荷均来自 B3 `MerchantQaGraph` 在 `FakeLlmClient` 下的真实输出。

| 文件 | 触发问题 | 验证点 |
| --- | --- | --- |
{rows}
"""


async def main_async() -> None:
    target = fixtures_dir()
    target.mkdir(parents=True, exist_ok=True)
    for case in FIXTURES:
        (target / f"{case.name}.json").write_text(render_fixture_json(await build_fixture(case)), encoding="utf-8")
    (target / "README.md").write_text(render_readme(), encoding="utf-8")


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
