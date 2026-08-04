"""服务端预置的「猜你想问」。

每个业务域都有至少两组可轮换的追问；只有普通 CHAT 使用产品入口问题。
配置只包含产品问题，不参与模型决策，也不由模型生成。

每条问题都标注了它期望走的回答路径（§6.8）：数据型问题必须落在 B3 的指标、
维度和明细白名单之内，否则用户点一下就撞 `INVALID`。标注由
``tests/unit/services/test_suggested_questions.py`` 校验——改问题必然要改标注，
标注错了测试会直接失败。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final

from app.schemas.chat import AnswerMode, QuestionCategory


class QuestionKind(StrEnum):
    """预置问题期望走的回答路径。"""

    #: 走经营数据查询，必须声明白名单内的指标、维度或明细表。
    DATA = "DATA"
    #: 由知识库正文回答，不经过指标白名单。
    KNOWLEDGE = "KNOWLEDGE"
    #: 查商家自身资料，走 IDENTITY 模式而非指标查询。
    IDENTITY = "IDENTITY"


@dataclass(frozen=True)
class PresetQuestion:
    text: str
    kind: QuestionKind
    metric: str | None = None
    dimensions: tuple[str, ...] = ()
    detail: str | None = None


def _data(
    text: str,
    *,
    metric: str | None = None,
    dimensions: tuple[str, ...] = (),
    detail: str | None = None,
) -> PresetQuestion:
    return PresetQuestion(text, QuestionKind.DATA, metric, dimensions, detail)


def _knowledge(text: str) -> PresetQuestion:
    return PresetQuestion(text, QuestionKind.KNOWLEDGE)


def _identity(text: str) -> PresetQuestion:
    return PresetQuestion(text, QuestionKind.IDENTITY)


@dataclass(frozen=True)
class SuggestedQuestions:
    current: list[str] = field(default_factory=list)
    alternates: list[list[str]] = field(default_factory=list)


QuestionGroup = tuple[PresetQuestion, PresetQuestion, PresetQuestion]


#: CHAT 的入门问题组：让新用户看到助手能做什么，因此三条覆盖数据、知识和身份三类。
FOLLOWUP_POOLS: Final[tuple[QuestionGroup, ...]] = (
    (
        _data("昨天总 GMV 是多少？", metric="gmv"),
        _data("最近 7 天咨询工单量", metric="support_ticket_count", dimensions=("date",)),
        _knowledge("我要货品上架，具体规则有吗？"),
    ),
    (
        _data("最近 7 天退货量趋势", metric="return_count", dimensions=("date",)),
        _data("昨天退款金额是多少？", metric="refund_amount"),
        _data("按退款原因查看退款数量", metric="refund_count", dimensions=("refund_reason",)),
    ),
    (
        _data("查看商品上架明细", detail="products"),
        _data("成功订单量是多少？", metric="successful_order_count"),
        _identity("我的商家手机号是多少？"),
    ),
)


DOMAIN_FOLLOWUP_POOLS: Final[dict[QuestionCategory, tuple[QuestionGroup, ...]]] = {
    QuestionCategory.PLATFORM_RULE: (
        (
            _knowledge("商品上架需要哪些资质？"),
            _knowledge("商品审核被驳回后怎么处理？"),
            _knowledge("禁售商品规则有哪些？"),
        ),
        (
            _knowledge("商品发布前要完成哪些检查？"),
            _knowledge("特殊类目需要哪些额外材料？"),
            _knowledge("平台发货时效规则是什么？"),
        ),
    ),
    QuestionCategory.TRADE: (
        (
            _data("昨天总 GMV 是多少？", metric="gmv"),
            _data("最近 7 天订单量趋势", metric="order_count", dimensions=("date",)),
            _data("按商品查看订单明细", detail="orders", dimensions=("product",)),
        ),
        (
            _data("按类目对比成交 GMV", metric="gmv", dimensions=("category",)),
            _data("成功订单量是多少？", metric="successful_order_count"),
            _data("最近 7 天付款用户数变化", metric="paying_user_count", dimensions=("date",)),
        ),
    ),
    QuestionCategory.REFUND: (
        (
            _data("最近 7 天退款单量趋势", metric="refund_count", dimensions=("date",)),
            _data("按退款原因查看退款数量", metric="refund_count", dimensions=("refund_reason",)),
            _data("导出退款明细", detail="refunds"),
        ),
        (
            _data("最近 7 天退货量趋势", metric="return_count", dimensions=("date",)),
            _data("按退货原因查看退货数量", metric="return_count", dimensions=("return_reason",)),
            _data("退货率是多少？", metric="return_rate"),
        ),
    ),
    QuestionCategory.CS_TICKET: (
        (
            _data("最近 7 天咨询工单量", metric="support_ticket_count", dimensions=("date",)),
            _data(
                "按工单状态查看数量",
                metric="support_ticket_count",
                dimensions=("ticket_status",),
            ),
            _data("导出客服工单明细", detail="support_tickets"),
        ),
        (
            _data(
                "哪些工单仍待处理？",
                metric="support_ticket_count",
                dimensions=("ticket_status",),
            ),
            _data("最近 7 天工单量趋势", metric="support_ticket_count", dimensions=("date",)),
            _data("按日期查看工单明细", detail="support_tickets", dimensions=("date",)),
        ),
    ),
    # 理赔、优惠券、商家其他和供应链在 B4 第一批经营表里没有对应数据，
    # 因此这四个域只推荐知识型问题——推荐一个查不到数的问题等于制造一次 INVALID。
    QuestionCategory.COMPENSATION: (
        (
            _knowledge("赔付规则是什么？"),
            _knowledge("理赔申请需要哪些材料？"),
            _knowledge("理赔审核要多久？"),
        ),
        (
            _knowledge("哪些情况可以申请赔付？"),
            _knowledge("赔付金额怎么计算？"),
            _knowledge("理赔被驳回后怎么处理？"),
        ),
    ),
    QuestionCategory.COUPON: (
        (
            _knowledge("优惠券规则是什么？"),
            _knowledge("优惠券如何创建？"),
            _knowledge("优惠券可以叠加使用吗？"),
        ),
        (
            _knowledge("优惠券失效有哪些原因？"),
            _knowledge("优惠券成本怎么结算？"),
            _knowledge("优惠券投放有什么限制？"),
        ),
    ),
    QuestionCategory.GOODS: (
        (
            _data("查看商品上架明细", detail="products"),
            _data("按类目查看商品明细", detail="products", dimensions=("category",)),
            _knowledge("商品审核被驳回后怎么处理？"),
        ),
        (
            _data("按商品查看订单量", metric="order_count", dimensions=("product",)),
            _knowledge("商品上架需要哪些资质？"),
            _knowledge("禁售商品规则有哪些？"),
        ),
    ),
    QuestionCategory.MERCHANT_OTHER: (
        (
            _knowledge("保证金规则是什么？"),
            _knowledge("商家申诉流程是怎样的？"),
            _knowledge("商家处罚规则有哪些？"),
        ),
        (
            _knowledge("保证金可以退还吗？"),
            _knowledge("申诉需要准备哪些材料？"),
            _knowledge("违规扣分怎么恢复？"),
        ),
    ),
    QuestionCategory.IDENTITY: (
        (
            _identity("我的商家资料是什么？"),
            _identity("我的商家手机号是多少？"),
            _identity("店铺认证状态怎么查看？"),
        ),
        (
            _identity("我的店铺名称是什么？"),
            _knowledge("商家联系方式怎么修改？"),
            _knowledge("商家资料变更需要什么材料？"),
        ),
    ),
    QuestionCategory.SCM: (
        (
            _knowledge("入库流程是什么？"),
            _knowledge("出库需要哪些操作？"),
            _knowledge("商品质检规则是什么？"),
        ),
        (
            _knowledge("仓库异常如何处理？"),
            _knowledge("供应链履约规则是什么？"),
            _knowledge("发货时效怎么计算？"),
        ),
    ),
    QuestionCategory.UNKNOWN: (
        (
            _data("昨天总 GMV 是多少？", metric="gmv"),
            _data("最近 7 天订单量趋势", metric="order_count", dimensions=("date",)),
            _knowledge("我要货品上架，具体规则有吗？"),
        ),
        (
            _data("最近 7 天退货量趋势", metric="return_count", dimensions=("date",)),
            _data("最近 7 天咨询工单量", metric="support_ticket_count", dimensions=("date",)),
            _data("查看商品上架明细", detail="products"),
        ),
    ),
}


def _texts(group: Sequence[PresetQuestion]) -> list[str]:
    return [question.text for question in group]


def initial_suggestions() -> list[str]:
    """空状态展示的第一组产品入口问题。"""

    return _texts(FOLLOWUP_POOLS[0])


def pick(
    scenario_questions: Sequence[PresetQuestion],
    *,
    candidate_groups: Sequence[Sequence[PresetQuestion]] = FOLLOWUP_POOLS,
) -> SuggestedQuestions:
    """将当前组与其余候选组分开，确保「换一换」不会重复当前问题。"""

    current = _texts(scenario_questions)
    return SuggestedQuestions(
        current=current,
        alternates=[_texts(group) for group in candidate_groups if _texts(group) != current],
    )


def suggestions_for(category: QuestionCategory, answer_mode: AnswerMode) -> SuggestedQuestions:
    """按已验证的业务域选择追问组；普通聊天保留入口问题。"""

    pools = FOLLOWUP_POOLS if answer_mode is AnswerMode.CHAT else DOMAIN_FOLLOWUP_POOLS[category]
    return pick(pools[0], candidate_groups=pools)
