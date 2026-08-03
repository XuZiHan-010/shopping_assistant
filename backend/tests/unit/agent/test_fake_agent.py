"""B2 Fake Agent 测试。

场景数据 1:1 对照 `yshopping-prototype/app.js` 的 `scenarios`，路由对照
`chooseScenario`。断言里的数值和文案都是从原型复制过来的，**不要从实现反向抄**——
反向抄会让这些测试失去对齐能力。
"""

from uuid import uuid4

import pytest

from app.agent.fake_agent import FALLBACK_REASON, FakeAgent
from app.schemas.chat import AnalysisSource, AnswerMode, QualityStatus, QuestionCategory
from app.services.suggested_questions import FOLLOWUP_POOLS

pytestmark = pytest.mark.asyncio

PROTOTYPE_DATES = ["07-22", "07-23", "07-24", "07-25", "07-26", "07-27", "07-28"]
ALL_POOL_QUESTIONS = sorted({question for pool in FOLLOWUP_POOLS for question in pool})


# --- 四个预置场景 --------------------------------------------------------


async def test_refund_scenario_matches_the_prototype() -> None:
    response = (await FakeAgent().run("最近7天退货量趋势", uuid4())).response

    assert response.answer_mode is AnswerMode.METRIC
    assert response.category is QuestionCategory.REFUND
    assert response.metric_display_name == "退货量"
    assert response.metric_unit == "单"
    assert response.metric_definition == "统计周期内创建的有效退货退款单数量，按退货单去重。"
    assert response.metric_owner == "售后数据组"
    assert response.metric_source == "指标资产库"
    assert response.data_rows is not None
    assert [row["value"] for row in response.data_rows] == [32, 28, 35, 41, 39, 53, 61]
    assert [row["date"] for row in response.data_rows] == PROTOTYPE_DATES
    assert response.total_rows == 7
    assert response.truncated is False
    assert response.recommendations is not None
    assert [item.title for item in response.recommendations] == [
        "定位高退货商品",
        "检查履约与描述",
    ]
    assert response.suggestions == [
        "按商品查看退货量排行",
        "这些退货的主要原因是什么？",
        "导出最近7天退货明细",
    ]
    assert "289 单" in response.answer
    assert "90.6%" in response.answer


async def test_gmv_scenario_matches_the_prototype() -> None:
    response = (await FakeAgent().run("昨天总 GMV 是多少？", uuid4())).response

    assert response.answer_mode is AnswerMode.METRIC
    assert response.category is QuestionCategory.TRADE
    assert response.metric_display_name == "总 GMV 金额"
    assert response.metric_unit == "元"
    assert response.metric_definition == "统计周期内已提交订单的商品金额合计，不扣除退款金额。"
    assert response.metric_owner == "交易数据组"
    assert response.metric_source == "指标平台"
    assert response.data_rows is not None
    assert [row["value"] for row in response.data_rows] == [
        186420,
        203510,
        198760,
        228390,
        219850,
        241680,
        256920,
    ]
    assert [row["date"] for row in response.data_rows] == PROTOTYPE_DATES
    assert response.recommendations is not None
    assert [item.title for item in response.recommendations] == [
        "承接增长流量",
        "复盘周末转化",
    ]
    assert response.suggestions == [
        "昨天成交订单有多少？",
        "按品类拆分昨天 GMV",
        "查看最近7天客单价趋势",
    ]
    assert "¥256,920" in response.answer
    assert "客单价约 ¥200.09" in response.answer


async def test_order_detail_scenario_matches_the_prototype() -> None:
    """原型 detail 场景走 METRIC：DETAIL 必须带可下载的 export，那是 B6。"""

    response = (await FakeAgent().run("查看最近订单明细", uuid4())).response

    assert response.answer_mode is AnswerMode.METRIC
    assert response.category is QuestionCategory.TRADE
    assert response.metric_display_name == "订单支付金额"
    assert response.metric_unit == "元"
    assert response.export is None
    assert response.data_rows is not None
    assert len(response.data_rows) == 7
    assert response.total_rows == 327
    assert response.truncated is True
    assert response.data_rows[0] == {
        "order_id": "YS20260728100300",
        "product_name": "复古跑鞋 Pro",
        "pay_amount": "¥179.00",
        "order_status": "交易成功",
        "ordered_at": "07-28 18:42",
    }
    assert response.data_rows[-1]["order_id"] == "YS20260728100294"
    assert response.suggestions == [
        "只看待发货订单",
        "导出全部订单明细",
        "按商品统计订单量",
    ]


async def test_rule_scenario_matches_the_prototype() -> None:
    response = (await FakeAgent().run("我要货品上架，具体规则有吗？", uuid4())).response

    assert response.answer_mode is AnswerMode.RULE
    assert response.category is QuestionCategory.PLATFORM_RULE
    assert response.data_rows is None
    assert response.metric_code is None
    assert response.recommendations is not None
    assert [item.title for item in response.recommendations] == ["先做资料自检", "核对类目资质"]
    assert response.suggestions == [
        "我的商品为什么审核不通过？",
        "查看商品上架明细",
        "哪些类目需要特殊资质？",
    ]
    assert "资料完整性、类目资质、价格与描述、平台审核" in response.answer
    assert "禁止使用绝对化宣传" in response.answer


# --- 路由 ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("最近7天退货量趋势", QuestionCategory.REFUND),
        ("昨天退款金额是多少？", QuestionCategory.REFUND),
        ("售后单怎么处理", QuestionCategory.REFUND),
        ("查看最近订单明细", QuestionCategory.TRADE),
        ("导出全部订单明细", QuestionCategory.TRADE),
        ("我要货品上架，具体规则有吗？", QuestionCategory.PLATFORM_RULE),
        ("哪些类目需要特殊资质？", QuestionCategory.PLATFORM_RULE),
        ("我的商品为什么审核不通过？", QuestionCategory.PLATFORM_RULE),
        ("昨天总 GMV 是多少？", QuestionCategory.TRADE),
    ],
)
async def test_routing_matches_the_prototype_keywords(
    message: str, expected: QuestionCategory
) -> None:
    response = (await FakeAgent().run(message, uuid4())).response

    assert response.category is expected


@pytest.mark.parametrize(
    "message",
    ["我想查看保证金", "查看优惠券明细", "我的商家手机号是多少？", "帮我看看物流时效"],
)
async def test_unmatched_questions_fall_back_to_the_gmv_scenario(message: str) -> None:
    """原型 chooseScenario 的兜底是 scenarios.gmv，不是「答不上来」。"""

    response = (await FakeAgent().run(message, uuid4())).response

    assert response.answer_mode is AnswerMode.METRIC
    assert response.category is QuestionCategory.TRADE
    assert response.metric_display_name == "总 GMV 金额"


@pytest.mark.parametrize("question", ALL_POOL_QUESTIONS)
async def test_every_pool_question_gets_a_scenario_answer(question: str) -> None:
    """轮换池里的问题点进去都要有场景回答，不能出现空白或拒绝。"""

    response = (await FakeAgent().run(question, uuid4())).response

    assert response.answer_mode in {AnswerMode.METRIC, AnswerMode.RULE}
    assert response.answer


# --- 问候与危险写操作 ----------------------------------------------------


@pytest.mark.parametrize("message", ["你好", "您好", "hi", "Hello", "在吗", "嗨"])
async def test_greeting_returns_chat_without_fake_source(message: str) -> None:
    response = (await FakeAgent().run(message, uuid4())).response

    assert response.answer_mode is AnswerMode.CHAT
    assert response.category is QuestionCategory.UNKNOWN
    assert response.analysis_sources == [AnalysisSource.NONE]
    assert response.degraded is False
    assert response.quality_status is QualityStatus.NOT_RUN
    assert response.suggestions == list(FOLLOWUP_POOLS[0])


@pytest.mark.parametrize("message", ["帮我修改订单金额", "删除订单 A1", "帮我下单一件"])
async def test_write_operations_are_refused(message: str) -> None:
    """原型没有这个分支（它碰不到数据库），我们连着真实库，必须拒绝。"""

    response = (await FakeAgent().run(message, uuid4())).response

    assert response.answer_mode is AnswerMode.INVALID
    assert response.analysis_sources == [AnalysisSource.NONE]
    assert response.degraded is False
    assert "无法执行修改" in response.answer


async def test_write_refusal_wins_over_a_greeting_prefix() -> None:
    response = (await FakeAgent().run("你好，帮我删除订单 A1", uuid4())).response

    assert response.answer_mode is AnswerMode.INVALID


# --- 降级标记（不随 1:1 放弃） ------------------------------------------


@pytest.mark.parametrize(
    "message",
    [
        "最近7天退货量趋势",
        "昨天总 GMV 是多少？",
        "查看最近订单明细",
        "我要货品上架，具体规则有吗？",
    ],
)
async def test_scenario_answers_are_always_marked_as_degraded(message: str) -> None:
    """原型显示「前后比对通过」，但我们的数字是硬编码的，不能标成真实结果。"""

    response = (await FakeAgent().run(message, uuid4())).response

    assert response.analysis_sources == [AnalysisSource.FALLBACK]
    assert response.degraded is True
    assert response.degraded_reason == FALLBACK_REASON
    assert response.quality_status is QualityStatus.DEGRADED
    assert response.quality_attempts == 0


async def test_thinking_steps_never_claim_a_database_or_knowledge_lookup() -> None:
    agent = FakeAgent()

    for message in ("最近7天退货量趋势", "我要货品上架，具体规则有吗？"):
        result = await agent.run(message, uuid4())
        labels = " ".join(step.label for step in result.steps)
        assert "Doris" not in labels
        assert "查询经营数据" not in labels
        assert "知识库" not in labels


async def test_steps_use_the_prototype_node_sequence() -> None:
    result = await FakeAgent().run("最近7天退货量趋势", uuid4())

    assert [step.node for step in result.steps] == ["classify", "compose", "suggest_questions"]
    assert result.steps[0].label == "识别商家与业务意图"
    assert result.steps[-1].label == "整理结论与可执行建议"


# --- 安全与确定性 --------------------------------------------------------


async def test_fake_agent_steps_do_not_expose_sql_or_rows() -> None:
    result = await FakeAgent().run("查看最近订单明细", uuid4())

    assert all("SELECT" not in step.label.upper() for step in result.steps)
    assert all("{" not in step.label for step in result.steps)


async def test_steps_are_not_shared_between_responses() -> None:
    agent = FakeAgent()

    first = await agent.run("你好", uuid4())
    second = await agent.run("你好", uuid4())

    assert first.steps == second.steps
    assert all(a is not b for a, b in zip(first.steps, second.steps, strict=True))


async def test_response_is_deterministic_apart_from_the_generated_id() -> None:
    agent = FakeAgent()
    session_id = uuid4()

    first = await agent.run("最近7天退货量趋势", session_id)
    second = await agent.run("最近7天退货量趋势", session_id)

    assert first.response.model_dump(exclude={"id", "created_at"}) == second.response.model_dump(
        exclude={"id", "created_at"}
    )


async def test_agent_never_produces_detail_mode_in_b2() -> None:
    """DETAIL 必须携带可下载的 export，那是 B6；B2 不能伪造下载链接。"""

    agent = FakeAgent()

    for question in [*ALL_POOL_QUESTIONS, "导出最近订单", "查看最近订单明细"]:
        result = await agent.run(question, uuid4())
        assert result.response.answer_mode is not AnswerMode.DETAIL
        assert result.response.export is None
