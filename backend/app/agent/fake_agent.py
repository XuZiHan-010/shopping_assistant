"""供 B2 UI 联调使用的确定性 Fake Agent。

场景数据 1:1 照搬 `yshopping-prototype/app.js` 的 `scenarios`，路由照搬
`chooseScenario`（**包括「未命中就回 GMV」这个兜底**）。参考实现的真实意图识别
是纯 LLM 的（`IntentService.java`：「不再调用任何关键词分类器」），关键词规则只
存在于原型演示里，所以原型就是 B2 阶段唯一的行为依据。B3 接入真实 Graph 与
Fake LLM 后本模块退役。

两处刻意不照搬原型：

1. **降级标记**。原型是纯静态 HTML，写「已记录」「前后比对通过」没有欺骗性；
   我们有真实后端和数据库，把硬编码数字标成真实查询结果就是撒谎（AGENTS.md R7）。
   因此保留 ``FALLBACK`` / ``degraded=True`` / ``DEGRADED``，思考步骤也不宣称
   查过数据库或知识库。
2. **危险写操作拒绝**。原型碰不到数据库，没有这个分支；我们连着真实库，必须拒绝。

不产生 ``AnswerMode.DETAIL``：DETAIL 按 §8.2 必须携带可下载的 ``export``，
受控导出属于 B6。原型 detail 场景的全部可见内容（表格、总数、截断、图表）
用 ``METRIC`` 就能装下。
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

from app.schemas.chat import (
    AnalysisSource,
    AnswerMode,
    ChatResponse,
    MetricStatus,
    QualityStatus,
    QueryPlanSummary,
    QuestionCategory,
    Recommendation,
    ThinkingStep,
    Visualization,
)
from app.services.suggested_questions import initial_suggestions, pick

FALLBACK_REASON = "当前为演示规则结果，未查询经营数据库"

DataRow = dict[str, str | int]


def _steps(*, has_data: bool) -> list[ThinkingStep]:
    """原型 answerMarkup 的三步思考轨迹（app.js:188-192）。

    原型第二步写的是「读取业务口径并查询 Doris 数据」/「检索平台规则知识库」。
    我们两样都没做，照抄就是伪造来源，所以只保留结构与语气。
    """

    middle = "读取业务口径并整理演示数据" if has_data else "整理演示规则说明"
    return [
        ThinkingStep(label="识别商家与业务意图", node="classify"),
        ThinkingStep(label=middle, node="compose"),
        ThinkingStep(label="整理结论与可执行建议", node="suggest_questions"),
    ]


@dataclass(frozen=True)
class FakeAgentResult:
    response: ChatResponse
    steps: list[ThinkingStep]


@dataclass(frozen=True)
class _MetricScenario:
    category: QuestionCategory
    metric_code: str
    display_name: str
    unit: str
    definition: str
    source: str
    owner: str
    answer: str
    rows: list[DataRow]
    total_rows: int
    truncated: bool
    dimension_key: str
    metric_key: str
    recommendations: list[Recommendation]
    suggestions: list[str]


@dataclass(frozen=True)
class _RuleScenario:
    category: QuestionCategory
    answer: str
    note: str
    recommendations: list[Recommendation]
    suggestions: list[str]


def _trend_rows(values: list[int]) -> list[DataRow]:
    dates = ["07-22", "07-23", "07-24", "07-25", "07-26", "07-27", "07-28"]
    return [{"date": date, "value": value} for date, value in zip(dates, values, strict=True)]


_REFUND = _MetricScenario(
    category=QuestionCategory.REFUND,
    metric_code="return_count",
    display_name="退货量",
    unit="单",
    definition="统计周期内创建的有效退货退款单数量，按退货单去重。",
    source="指标资产库",
    owner="售后数据组",
    answer=(
        "近 7 天退货量共 289 单，日均 41.3 单。7 月 28 日达到 61 单，"
        "较 7 月 22 日上升 90.6%。从趋势看，最近两日增长明显，"
        "需要优先排查高退货商品和退款原因。"
    ),
    rows=_trend_rows([32, 28, 35, 41, 39, 53, 61]),
    total_rows=7,
    truncated=False,
    dimension_key="date",
    metric_key="value",
    recommendations=[
        Recommendation(
            title="定位高退货商品",
            evidence="最近两日退货量连续上升，7 月 28 日达到周期峰值。",
            action="按商品和退款原因拆分，优先处理贡献前 20% 的 SKU。",
        ),
        Recommendation(
            title="检查履约与描述",
            evidence="尺码不符、描述差异通常会驱动退货集中增长。",
            action="复核重点商品详情页，并抽查最近三日发货与质检记录。",
        ),
    ],
    suggestions=["按商品查看退货量排行", "这些退货的主要原因是什么？", "导出最近7天退货明细"],
)

_GMV = _MetricScenario(
    category=QuestionCategory.TRADE,
    metric_code="gmv",
    display_name="总 GMV 金额",
    unit="元",
    definition="统计周期内已提交订单的商品金额合计，不扣除退款金额。",
    source="指标平台",
    owner="交易数据组",
    answer=(
        "昨天总 GMV 为 ¥256,920，较前一天增长 6.3%。最近 7 天 GMV 整体呈上升趋势，"
        "其中周末增长最明显；成交订单 1,284 单，客单价约 ¥200.09。"
    ),
    rows=_trend_rows([186420, 203510, 198760, 228390, 219850, 241680, 256920]),
    total_rows=7,
    truncated=False,
    dimension_key="date",
    metric_key="value",
    recommendations=[
        Recommendation(
            title="承接增长流量",
            evidence="GMV 连续两日增长，昨天达到近 7 日最高值。",
            action="保持高转化商品库存，并为前 20 个热销 SKU 设置库存预警。",
        ),
        Recommendation(
            title="复盘周末转化",
            evidence="周末 GMV 增幅高于工作日，存在可复用的流量窗口。",
            action="对比渠道、券活动与客单价，沉淀下一周期促销方案。",
        ),
    ],
    suggestions=["昨天成交订单有多少？", "按品类拆分昨天 GMV", "查看最近7天客单价趋势"],
)

_ORDER_DETAIL = _MetricScenario(
    category=QuestionCategory.TRADE,
    metric_code="order_pay_amount",
    display_name="订单支付金额",
    unit="元",
    definition="用户在订单层面实际支付的金额，已扣除优惠但不扣除后续退款。",
    # 原型写的是「Doris 字段注释」；Doris 是参考实现的 OLAP 库，属技术实现细节。
    source="数据字段注释",
    owner="交易数据组",
    answer=(
        "已整理最近订单明细，共 327 条。当前展示最新 7 条，"
        "包含订单号、商品、支付金额、状态与下单时间。"
        # 原型此处是「完整结果可下载 CSV。」；受控导出属于 B6，现在没有下载入口，
        # 照抄会给出一个点不开的承诺。
        "完整结果导出将在后续版本提供。"
    ),
    rows=[
        {
            "order_id": "YS20260728100300",
            "product_name": "复古跑鞋 Pro",
            "pay_amount": "¥179.00",
            "order_status": "交易成功",
            "ordered_at": "07-28 18:42",
        },
        {
            "order_id": "YS20260728100299",
            "product_name": "轻量通勤双肩包",
            "pay_amount": "¥269.00",
            "order_status": "已发货",
            "ordered_at": "07-28 18:31",
        },
        {
            "order_id": "YS20260728100298",
            "product_name": "棉质宽松短袖",
            "pay_amount": "¥128.00",
            "order_status": "交易成功",
            "ordered_at": "07-28 18:16",
        },
        {
            "order_id": "YS20260728100297",
            "product_name": "机械腕表 Classic",
            "pay_amount": "¥459.00",
            "order_status": "待发货",
            "ordered_at": "07-28 17:58",
        },
        {
            "order_id": "YS20260728100296",
            "product_name": "城市机能帽",
            "pay_amount": "¥89.00",
            "order_status": "交易成功",
            "ordered_at": "07-28 17:45",
        },
        {
            "order_id": "YS20260728100295",
            "product_name": "牛皮乐福鞋",
            "pay_amount": "¥329.00",
            "order_status": "已发货",
            "ordered_at": "07-28 17:27",
        },
        {
            "order_id": "YS20260728100294",
            "product_name": "针织开衫",
            "pay_amount": "¥199.00",
            "order_status": "交易成功",
            "ordered_at": "07-28 17:03",
        },
    ],
    total_rows=327,
    truncated=True,
    dimension_key="order_id",
    metric_key="pay_amount",
    recommendations=[
        Recommendation(
            title="关注待发货订单",
            evidence="最新订单中仍存在待发货记录。",
            action="优先核对临近承诺发货时效的订单，避免催单与赔付。",
        ),
        Recommendation(
            title="识别高客单商品",
            evidence="腕表、鞋履订单金额高于样本均值。",
            action="将高客单商品纳入重点客服与售后跟踪。",
        ),
    ],
    suggestions=["只看待发货订单", "导出全部订单明细", "按商品统计订单量"],
)

_PLATFORM_RULE = _RuleScenario(
    category=QuestionCategory.PLATFORM_RULE,
    answer=(
        "货品上架需要完成「资料完整性、类目资质、价格与描述、平台审核」四项检查。\n\n"
        "1. 商品标题、主图、规格、品牌与类目必须完整；\n"
        "2. 特殊类目需提交对应资质，品牌商品需提供授权链路；\n"
        "3. 售价、库存、运费模板和售后说明必须有效；\n"
        "4. 禁止使用绝对化宣传、站外引流或与实物不符的描述。\n\n"
        "提交后会依次经过内容审核与风控审核，通过后即可上架。"
    ),
    note="当前回答未检索正式知识库。",
    recommendations=[
        Recommendation(
            title="先做资料自检",
            evidence="完整资料可以减少审核打回与重复修改。",
            action="准备标题、图片、规格、价格、库存和售后说明后再提交。",
        ),
        Recommendation(
            title="核对类目资质",
            evidence="特殊类目和品牌商品存在额外准入要求。",
            action="先确认目标类目的资质清单与授权有效期。",
        ),
    ],
    suggestions=["我的商品为什么审核不通过？", "查看商品上架明细", "哪些类目需要特殊资质？"],
)

# yshopping-prototype/app.js chooseScenario()：顺序即优先级，未命中一律回 GMV。
_REFUND_KEYWORDS = ("退货", "退款", "售后")
_ORDER_DETAIL_KEYWORDS = ("订单明细", "订单列表", "最近订单", "导出")
_RULE_KEYWORDS = ("上架", "规则", "资质", "审核")

# 参考 client.js mockChat 的问候判定，锚定在开头。
_GREETING_PREFIXES = ("你好", "您好", "在吗", "嗨", "hi", "hello", "hey")

# 原型没有这个分支——它是纯前端演示，碰不到数据库。B2 连着真实库，必须前置拦截。
_DANGEROUS_KEYWORDS = (
    "修改订单",
    "删除订单",
    "取消订单",
    "修改商品",
    "删除商品",
    "修改退款",
    "修改价格",
    "改价",
    "下架商品",
    "帮我下单",
)


class FakeAgent:
    """无需网络和 LLM 的 B2 临时回答器。"""

    async def run(self, message: str, session_id: UUID) -> FakeAgentResult:
        response = self._respond(message.strip(), session_id)
        return FakeAgentResult(response=response, steps=response.thinking_steps)

    def _respond(self, message: str, session_id: UUID) -> ChatResponse:
        lowered = message.lower()
        if any(keyword in lowered for keyword in _DANGEROUS_KEYWORDS):
            return self._refused_response(session_id)
        if lowered.startswith(_GREETING_PREFIXES):
            return self._chat_response(session_id)
        if any(keyword in lowered for keyword in _REFUND_KEYWORDS):
            return self._metric_response(session_id, _REFUND)
        if any(keyword in lowered for keyword in _ORDER_DETAIL_KEYWORDS):
            return self._metric_response(session_id, _ORDER_DETAIL)
        if any(keyword in lowered for keyword in _RULE_KEYWORDS):
            return self._rule_response(session_id, _PLATFORM_RULE)
        return self._metric_response(session_id, _GMV)

    def _metric_response(self, session_id: UUID, scenario: _MetricScenario) -> ChatResponse:
        suggestions = pick(scenario.suggestions)
        return ChatResponse(
            id=uuid4(),
            session_id=session_id,
            answer=scenario.answer,
            answer_mode=AnswerMode.METRIC,
            category=scenario.category,
            thinking_steps=_steps(has_data=True),
            quality_status=QualityStatus.DEGRADED,
            quality_attempts=0,
            quality_notes=["当前回答使用演示规则，不代表真实经营数据分析。"],
            analysis_sources=[AnalysisSource.FALLBACK],
            degraded=True,
            degraded_reason=FALLBACK_REASON,
            suggestions=suggestions.current,
            suggestion_alternates=suggestions.alternates,
            query_plan=QueryPlanSummary(summary="演示查询计划，未执行数据库查询。"),
            metric_code=scenario.metric_code,
            metric_display_name=scenario.display_name,
            metric_unit=scenario.unit,
            metric_definition=scenario.definition,
            metric_source=scenario.source,
            metric_owner=scenario.owner,
            metric_status=MetricStatus.UNVERIFIED,
            data_rows=list(scenario.rows),
            total_rows=scenario.total_rows,
            truncated=scenario.truncated,
            visualization=Visualization(
                enabled=True,
                type="line",
                allowed_types=["line", "bar"],
                title=f"{scenario.display_name}演示趋势",
                dimension_key=scenario.dimension_key,
                metric_key=scenario.metric_key,
                unit=scenario.unit,
                data=list(scenario.rows),
            ),
            recommendations=list(scenario.recommendations),
        )

    def _rule_response(self, session_id: UUID, scenario: _RuleScenario) -> ChatResponse:
        suggestions = pick(scenario.suggestions)
        return ChatResponse(
            id=uuid4(),
            session_id=session_id,
            answer=scenario.answer,
            answer_mode=AnswerMode.RULE,
            category=scenario.category,
            thinking_steps=_steps(has_data=False),
            quality_status=QualityStatus.DEGRADED,
            quality_attempts=0,
            quality_notes=[scenario.note],
            analysis_sources=[AnalysisSource.FALLBACK],
            degraded=True,
            degraded_reason=FALLBACK_REASON,
            suggestions=suggestions.current,
            suggestion_alternates=suggestions.alternates,
            recommendations=list(scenario.recommendations),
        )

    def _chat_response(self, session_id: UUID) -> ChatResponse:
        return self._no_source_response(
            session_id,
            answer=(
                "您好，我是 Borough 商家 AI 助手，有任何经营、订单、退货、客服、赔付、"
                "优惠券、商品或商家资料问题都可以问我。"
            ),
            answer_mode=AnswerMode.CHAT,
        )

    def _refused_response(self, session_id: UUID) -> ChatResponse:
        return self._no_source_response(
            session_id,
            answer=(
                "我无法执行修改、删除或影响订单和商品数据的操作，只能帮你查询和分析。"
                "你可以换成查看类问题再问一次。"
            ),
            answer_mode=AnswerMode.INVALID,
        )

    def _no_source_response(
        self,
        session_id: UUID,
        *,
        answer: str,
        answer_mode: AnswerMode,
    ) -> ChatResponse:
        return ChatResponse(
            id=uuid4(),
            session_id=session_id,
            answer=answer,
            answer_mode=answer_mode,
            category=QuestionCategory.UNKNOWN,
            thinking_steps=_steps(has_data=False),
            quality_status=QualityStatus.NOT_RUN,
            quality_attempts=0,
            quality_notes=[],
            analysis_sources=[AnalysisSource.NONE],
            degraded=False,
            degraded_reason=None,
            suggestions=initial_suggestions(),
            suggestion_alternates=[],
        )
