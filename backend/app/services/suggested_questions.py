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

from app.localization.locales import SupportedLocale
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
    #: 中文展示文案，保持字段名与既有调用点（如
    #: `tests/unit/services/test_suggested_questions.py` 里的 `question.text`）
    #: 兼容——它一直就是默认展示语言 zh-CN 的文案，不需要改名。
    text: str
    kind: QuestionKind
    metric: str | None = None
    dimensions: tuple[str, ...] = ()
    detail: str | None = None
    #: 英文展示文案。人工维护的固定产品文案，不接入 LLM/LocalizationService——
    #: 与问题原文一样是「已知推荐问题」，必须走本地词典（Task 6 Step 6）。
    text_en: str = ""

    def localized_text(self, locale: SupportedLocale) -> str:
        return self.text_en if locale is SupportedLocale.EN_US else self.text


def _data(
    text: str,
    text_en: str,
    *,
    metric: str | None = None,
    dimensions: tuple[str, ...] = (),
    detail: str | None = None,
) -> PresetQuestion:
    return PresetQuestion(
        text=text,
        kind=QuestionKind.DATA,
        metric=metric,
        dimensions=dimensions,
        detail=detail,
        text_en=text_en,
    )


def _knowledge(text: str, text_en: str) -> PresetQuestion:
    return PresetQuestion(text=text, kind=QuestionKind.KNOWLEDGE, text_en=text_en)


def _identity(text: str, text_en: str) -> PresetQuestion:
    return PresetQuestion(text=text, kind=QuestionKind.IDENTITY, text_en=text_en)


@dataclass(frozen=True)
class SuggestedQuestions:
    current: list[str] = field(default_factory=list)
    alternates: list[list[str]] = field(default_factory=list)


QuestionGroup = tuple[PresetQuestion, PresetQuestion, PresetQuestion]


#: CHAT 的入门问题组：让新用户看到助手能做什么，因此三条覆盖数据、知识和身份三类。
FOLLOWUP_POOLS: Final[tuple[QuestionGroup, ...]] = (
    (
        _data("昨天总 GMV 是多少？", "What was total GMV yesterday?", metric="gmv"),
        _data(
            "最近 7 天咨询工单量",
            "Support ticket volume over the last 7 days",
            metric="support_ticket_count",
            dimensions=("date",),
        ),
        _knowledge("我要货品上架，具体规则有吗？", "What are the rules for listing a new product?"),
    ),
    (
        _data(
            "最近 7 天退货量趋势",
            "Return volume trend over the last 7 days",
            metric="return_count",
            dimensions=("date",),
        ),
        _data(
            "昨天退款金额是多少？",
            "What was the refund amount yesterday?",
            metric="refund_amount",
        ),
        _data(
            "按退款原因查看退款数量",
            "Refund count by refund reason",
            metric="refund_count",
            dimensions=("refund_reason",),
        ),
    ),
    (
        _data("查看商品上架明细", "View product listing details", detail="products"),
        _data(
            "成功订单量是多少？",
            "What is the successful order count?",
            metric="successful_order_count",
        ),
        _identity("我的商家手机号是多少？", "What is my merchant phone number?"),
    ),
)


DOMAIN_FOLLOWUP_POOLS: Final[dict[QuestionCategory, tuple[QuestionGroup, ...]]] = {
    QuestionCategory.PLATFORM_RULE: (
        (
            _knowledge(
                "商品上架需要哪些资质？", "What qualifications are needed to list a product?"
            ),
            _knowledge(
                "商品审核被驳回后怎么处理？", "What should I do if product review is rejected?"
            ),
            _knowledge("禁售商品规则有哪些？", "What are the prohibited product rules?"),
        ),
        (
            _knowledge(
                "商品发布前要完成哪些检查？", "What checks are needed before publishing a product?"
            ),
            _knowledge(
                "特殊类目需要哪些额外材料？",
                "What extra materials are needed for special categories?",
            ),
            _knowledge("平台发货时效规则是什么？", "What are the platform's shipping time rules?"),
        ),
    ),
    QuestionCategory.TRADE: (
        (
            _data("昨天总 GMV 是多少？", "What was total GMV yesterday?", metric="gmv"),
            _data(
                "最近 7 天订单量趋势",
                "Order volume trend over the last 7 days",
                metric="order_count",
                dimensions=("date",),
            ),
            _data(
                "按商品查看订单明细",
                "View order details by product",
                detail="orders",
                dimensions=("product",),
            ),
        ),
        (
            _data(
                "按类目对比成交 GMV",
                "Compare GMV by category",
                metric="gmv",
                dimensions=("category",),
            ),
            _data(
                "成功订单量是多少？",
                "What is the successful order count?",
                metric="successful_order_count",
            ),
            _data(
                "最近 7 天付款用户数变化",
                "Paying user count trend over the last 7 days",
                metric="paying_user_count",
                dimensions=("date",),
            ),
        ),
    ),
    QuestionCategory.REFUND: (
        (
            _data(
                "最近 7 天退款单量趋势",
                "Refund order volume trend over the last 7 days",
                metric="refund_count",
                dimensions=("date",),
            ),
            _data(
                "按退款原因查看退款数量",
                "Refund count by refund reason",
                metric="refund_count",
                dimensions=("refund_reason",),
            ),
            _data("导出退款明细", "Export refund details", detail="refunds"),
        ),
        (
            _data(
                "最近 7 天退货量趋势",
                "Return volume trend over the last 7 days",
                metric="return_count",
                dimensions=("date",),
            ),
            _data(
                "按退货原因查看退货数量",
                "Return count by return reason",
                metric="return_count",
                dimensions=("return_reason",),
            ),
            _data("退货率是多少？", "What is the return rate?", metric="return_rate"),
        ),
    ),
    QuestionCategory.CS_TICKET: (
        (
            _data(
                "最近 7 天咨询工单量",
                "Support ticket volume over the last 7 days",
                metric="support_ticket_count",
                dimensions=("date",),
            ),
            _data(
                "按工单状态查看数量",
                "Ticket count by ticket status",
                metric="support_ticket_count",
                dimensions=("ticket_status",),
            ),
            _data("导出客服工单明细", "Export support ticket details", detail="support_tickets"),
        ),
        (
            _data(
                "哪些工单仍待处理？",
                "Which tickets are still pending?",
                metric="support_ticket_count",
                dimensions=("ticket_status",),
            ),
            _data(
                "最近 7 天工单量趋势",
                "Ticket volume trend over the last 7 days",
                metric="support_ticket_count",
                dimensions=("date",),
            ),
            _data(
                "按日期查看工单明细",
                "View ticket details by date",
                detail="support_tickets",
                dimensions=("date",),
            ),
        ),
    ),
    # 理赔、优惠券、商家其他和供应链在 B4 第一批经营表里没有对应数据，
    # 因此这四个域只推荐知识型问题——推荐一个查不到数的问题等于制造一次 INVALID。
    QuestionCategory.COMPENSATION: (
        (
            _knowledge("赔付规则是什么？", "What are the compensation rules?"),
            _knowledge(
                "理赔申请需要哪些材料？", "What materials are needed for a compensation claim?"
            ),
            _knowledge("理赔审核要多久？", "How long does compensation review take?"),
        ),
        (
            _knowledge("哪些情况可以申请赔付？", "In what situations can I claim compensation?"),
            _knowledge("赔付金额怎么计算？", "How is the compensation amount calculated?"),
            _knowledge(
                "理赔被驳回后怎么处理？",
                "What should I do if a compensation claim is rejected?",
            ),
        ),
    ),
    QuestionCategory.COUPON: (
        (
            _knowledge("优惠券规则是什么？", "What are the coupon rules?"),
            _knowledge("优惠券如何创建？", "How do I create a coupon?"),
            _knowledge("优惠券可以叠加使用吗？", "Can coupons be stacked?"),
        ),
        (
            _knowledge("优惠券失效有哪些原因？", "Why do coupons become invalid?"),
            _knowledge("优惠券成本怎么结算？", "How is coupon cost settled?"),
            _knowledge(
                "优惠券投放有什么限制？", "What are the restrictions on issuing coupons?"
            ),
        ),
    ),
    QuestionCategory.GOODS: (
        (
            _data("查看商品上架明细", "View product listing details", detail="products"),
            _data(
                "按类目查看商品明细",
                "View product details by category",
                detail="products",
                dimensions=("category",),
            ),
            _knowledge(
                "商品审核被驳回后怎么处理？", "What should I do if product review is rejected?"
            ),
        ),
        (
            _data(
                "按商品查看订单量",
                "View order count by product",
                metric="order_count",
                dimensions=("product",),
            ),
            _knowledge(
                "商品上架需要哪些资质？", "What qualifications are needed to list a product?"
            ),
            _knowledge("禁售商品规则有哪些？", "What are the prohibited product rules?"),
        ),
    ),
    QuestionCategory.MERCHANT_OTHER: (
        (
            _knowledge("保证金规则是什么？", "What are the deposit rules?"),
            _knowledge("商家申诉流程是怎样的？", "What is the merchant appeal process?"),
            _knowledge("商家处罚规则有哪些？", "What are the merchant penalty rules?"),
        ),
        (
            _knowledge("保证金可以退还吗？", "Can the deposit be refunded?"),
            _knowledge("申诉需要准备哪些材料？", "What materials are needed for an appeal?"),
            _knowledge("违规扣分怎么恢复？", "How can violation points be restored?"),
        ),
    ),
    QuestionCategory.IDENTITY: (
        (
            _identity("我的商家资料是什么？", "What is my merchant profile?"),
            _identity("我的商家手机号是多少？", "What is my merchant phone number?"),
            _identity(
                "店铺认证状态怎么查看？", "How do I check my store's verification status?"
            ),
        ),
        (
            _identity("我的店铺名称是什么？", "What is my store name?"),
            _knowledge(
                "商家联系方式怎么修改？", "How do I update my merchant contact information?"
            ),
            _knowledge(
                "商家资料变更需要什么材料？",
                "What materials are needed to change merchant information?",
            ),
        ),
    ),
    QuestionCategory.SCM: (
        (
            _knowledge("入库流程是什么？", "What is the inbound (warehousing) process?"),
            _knowledge("出库需要哪些操作？", "What steps are needed for outbound shipping?"),
            _knowledge("商品质检规则是什么？", "What are the product quality inspection rules?"),
        ),
        (
            _knowledge("仓库异常如何处理？", "How do I handle warehouse exceptions?"),
            _knowledge(
                "供应链履约规则是什么？", "What are the supply chain fulfillment rules?"
            ),
            _knowledge("发货时效怎么计算？", "How is shipping lead time calculated?"),
        ),
    ),
    QuestionCategory.UNKNOWN: (
        (
            _data("昨天总 GMV 是多少？", "What was total GMV yesterday?", metric="gmv"),
            _data(
                "最近 7 天订单量趋势",
                "Order volume trend over the last 7 days",
                metric="order_count",
                dimensions=("date",),
            ),
            _knowledge(
                "我要货品上架，具体规则有吗？", "What are the rules for listing a new product?"
            ),
        ),
        (
            _data(
                "最近 7 天退货量趋势",
                "Return volume trend over the last 7 days",
                metric="return_count",
                dimensions=("date",),
            ),
            _data(
                "最近 7 天咨询工单量",
                "Support ticket volume over the last 7 days",
                metric="support_ticket_count",
                dimensions=("date",),
            ),
            _data("查看商品上架明细", "View product listing details", detail="products"),
        ),
    ),
}


def _texts(
    group: Sequence[PresetQuestion], locale: SupportedLocale = SupportedLocale.ZH_CN
) -> list[str]:
    return [question.localized_text(locale) for question in group]


def initial_suggestions(locale: SupportedLocale = SupportedLocale.ZH_CN) -> list[str]:
    """空状态展示的第一组产品入口问题。

    `locale` 默认 zh-CN，保持既有零参数调用点行为不变；这批文案是人工维护的
    固定产品问法，按本地词典（`text`/`text_en` 两个固定字段）直接查表选取，
    不接入 LocalizationService/LLM——属于「已知推荐问题必须走本地词典」
    （Task 6 Step 6）。
    """

    return _texts(FOLLOWUP_POOLS[0], locale)


def pick(
    scenario_questions: Sequence[PresetQuestion],
    *,
    candidate_groups: Sequence[Sequence[PresetQuestion]] = FOLLOWUP_POOLS,
    locale: SupportedLocale = SupportedLocale.ZH_CN,
) -> SuggestedQuestions:
    """将当前组与其余候选组分开，确保「换一换」不会重复当前问题。"""

    current = _texts(scenario_questions, locale)
    return SuggestedQuestions(
        current=current,
        alternates=[
            _texts(group, locale) for group in candidate_groups if _texts(group, locale) != current
        ],
    )


def suggestions_for(
    category: QuestionCategory,
    answer_mode: AnswerMode,
    locale: SupportedLocale = SupportedLocale.ZH_CN,
) -> SuggestedQuestions:
    """按已验证的业务域选择追问组；普通聊天保留入口问题。"""

    pools = FOLLOWUP_POOLS if answer_mode is AnswerMode.CHAT else DOMAIN_FOLLOWUP_POOLS[category]
    return pick(pools[0], candidate_groups=pools, locale=locale)
