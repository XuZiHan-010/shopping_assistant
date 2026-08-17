from __future__ import annotations

from datetime import date

from app.intent.whitelist import DIMENSION_WHITELIST, FILTER_WHITELIST, METRIC_WHITELIST
from app.schemas.chat import AnswerMode, QuestionCategory

# 业务日界固定为 Asia/Shanghai（Settings.require_business_timezone 强制），这里只是
# 把这件事告诉模型，不重新读配置——提示词模块不该依赖运行期配置。
BUSINESS_TIMEZONE_LABEL = "Asia/Shanghai"


def _values(enum: type[AnswerMode] | type[QuestionCategory]) -> str:
    return "|".join(member.value for member in enum)


# `QueryIntent` 是 extra="forbid"：少一个必填字段或多一个自造字段都会整条拒绝。
# 只写「输出完整 QueryIntent JSON」时，真实模型会按常识编出 intent/business_domain/
# metrics 这类字段，三次重试全部 ValidationError（2026-08-17 线上实测）。所以字段名、
# 类型和取值集合必须逐条写进提示词。
#
# 刻意不含 cross_business_plan_rejected / generated_metric_plan_rejected：它们是
# 校验器的内部状态（exclude=True），写进来等于邀请模型伪造拒绝标记。
OUTPUT_CONTRACT = (
    "输出必须是**单个 JSON 对象**，且只允许以下字段——多一个未列出的字段整条作废：\n"
    f"  answer_mode           必填  枚举，取值之一：{_values(AnswerMode)}\n"
    f"  category              必填  枚举，取值之一：{_values(QuestionCategory)}\n"
    "  analysis_requested    必填  布尔\n"
    "  metric                可选  单个字符串，不是数组\n"
    "  dimensions            可选  字符串数组\n"
    '  filters               可选  对象，不是数组，形如 {"筛选字段":"筛选值"}\n'
    '  date_range            可选  对象 {"start":"YYYY-MM-DD","end":"YYYY-MM-DD"}\n'
    "  sort                  可选  字符串\n"
    "  limit                 可选  整数\n"
    "  followup_reference    可选  布尔\n"
    "  needs_attachment      可选  布尔\n"
    "  cross_business_plan   可选  见上方跨业务说明\n"
    "  generated_metric_plan 可选  见上方生成指标说明\n"
    "不得输出 intent、business_domain、metrics 等上表之外的字段，"
    "也不得输出 JSON 以外的解释文字或 markdown 代码围栏。\n"
)

CLASSIFY_SYSTEM = "你是 Borough 商家 AI 助手的意图分类器。只输出 JSON。"
UNDERSTAND_SYSTEM = "你是 Borough 商家 AI 助手的结构化理解器。只输出 JSON，禁止 SQL。"


def classify_user_prompt(question: str, index_text: str) -> str:
    return (
        f"业务索引：\n{index_text}\n商家问题：{question}\n"
        "输出 answer_mode、category、intent_keywords JSON。"
    )


CROSS_BUSINESS_GUIDANCE = (
    "cross_business_plan \u4ec5\u5728\u7528\u6237\u660e\u786e\u8981\u6c42"
    "\u6309\u8ba2\u5355\u67e5\u770b\u5173\u8054\u9000\u6b3e\u6216\u5546\u54c1\u65f6\u53ef\u9009\u8f93\u51fa\uff0c"
    "\u683c\u5f0f\u4e3a {plan_type: ORDER_TO_REFUND|ORDER_TO_GOODS|"
    "ORDER_REFUND_GOODS, sub_order_no: \u8ba2\u5355\u53f7}\u3002"
    "\u4e0d\u5f97\u8f93\u51fa\u8868\u540d\u3001\u5217\u540d\u3001SQL\u3001"
    "join \u6761\u4ef6\u6216\u5176\u4ed6\u67e5\u8be2\u6807\u8bc6\u7b26\u3002\n"
)

GENERATED_METRIC_GUIDANCE = (
    "generated_metric_plan 仅在 answer_mode=METRIC 时可选输出；"
    "仅限类别 TRADE 或 REFUND：TRADE 使用固定成交聚合模板，"
    "REFUND 使用固定退款聚合模板。"
    "格式为 {name: 展示名称, unit: 单位, group_by?: spu_id|address_city_name, "
    "filter_column?: spu_id|address_city_name, filter_value?: 筛选值}。"
    "filter_column 与 filter_value 必须同时出现；没有 group_by 时仅允许按 "
    "address_city_name 筛选。不得输出 measure、自由公式、表名、列名、SQL "
    "或其他查询标识符。\n"
)


def understand_user_prompt(
    question: str, category: str, knowledge_text: str, *, today: date
) -> str:
    """`today` 必须由调用方按业务时区注入。

    模型没有时钟：不告诉它今天几号，「最近 7 天」这类相对表述只能靠猜。实测会返回
    一年多以前的合法区间，而 `validate_intent` 只钳制上界和跨度、不纠正历史区间，
    查询于是落在没有数据的时段上，表现为「查不到」而不是报错。
    """

    return (
        CROSS_BUSINESS_GUIDANCE
        + GENERATED_METRIC_GUIDANCE
        + OUTPUT_CONTRACT
        + (
            f"今天的业务日期是 {today.isoformat()}（{BUSINESS_TIMEZONE_LABEL}）。"
            "所有相对时间表述都以此为基准换算，date_range 不得晚于今天。\n"
            f"业务域：{category}\n业务知识：{knowledge_text}\n商家问题：{question}\n"
            f"metric 取值白名单={sorted(METRIC_WHITELIST)}；"
            f"dimensions 取值白名单={sorted(DIMENSION_WHITELIST)}；"
            f"filters 的键白名单={sorted(FILTER_WHITELIST)}；"
            "analysis_requested：仅当用户明确要求分析、解读、原因或建议时为 true，"
            "只要求查看明细时为 false。不得输出 SQL、表名或自由查询文本。"
        )
    )
