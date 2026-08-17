"""两阶段意图识别的提示词。

契约的表达形式照搬参考项目 `LlmIntentAnalysisService`（R9）：**枚举取值表 + 完整
JSON 示例 + 编号约束**，系统提示词里显式禁止 Markdown。移植成两个独立提示词时这
一整套都丢了，2026-08-17 首次真实模型调用一次暴露两处后果——见各常量上方注释。

字段名沿用我方 `QueryIntent` 的 snake_case，不跟参考项目的 Java camelCase：那是内部
LLM 契约，`docs/backend-development-plan.md` §8 管的是对外 API 契约，两者互不影响。
"""

from __future__ import annotations

import json
from datetime import date

from app.intent.whitelist import DIMENSION_WHITELIST, FILTER_WHITELIST, METRIC_WHITELIST
from app.schemas.chat import AnswerMode, QuestionCategory

# 业务日界固定为 Asia/Shanghai（Settings.require_business_timezone 强制），这里只是
# 把这件事告诉模型，不重新读配置——提示词模块不该依赖运行期配置。
BUSINESS_TIMEZONE_LABEL = "Asia/Shanghai"

# 测试按这个标记抠出示例并真正校验它，避免示例悄悄和 schema 脱节。
EXAMPLE_MARKER = "输出示例："

# 参考项目系统提示词的原话是「必须只输出 JSON 对象，不要输出 Markdown」。少了这句，
# 模型很容易回 ```json 围栏，而 `IntentService._object` 是裸 json.loads，遇到围栏
# 直接返回 None——表现为静默降级，不是报错。
_NO_MARKDOWN = "必须只输出单个 JSON 对象，不要输出 Markdown 代码围栏或任何解释文字。"


def _values(enum: type[AnswerMode] | type[QuestionCategory]) -> str:
    return "|".join(member.value for member in enum)


def _example(payload: dict[str, object]) -> str:
    return f"{EXAMPLE_MARKER}\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n"


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
    "不得输出 intent、business_domain、metrics 等上表之外的字段。\n"
) + _example(
    {
        "answer_mode": "METRIC",
        "category": "REFUND",
        "analysis_requested": True,
        "metric": "return_count",
        "dimensions": ["date"],
        "date_range": {"start": "2026-08-11", "end": "2026-08-17"},
    }
)

CLASSIFY_SYSTEM = f"你是 Borough 商家 AI 助手的意图分类器。{_NO_MARKDOWN}"
UNDERSTAND_SYSTEM = (
    f"你是 Borough 商家 AI 助手的结构化理解器。{_NO_MARKDOWN}禁止输出 SQL、表名或列名。"
)


def classify_user_prompt(question: str, index_text: str) -> str:
    """第一阶段：判断业务域与回答模式，供第二阶段和知识正文检索使用。

    这一步是整条链路的闸门——它一失败，`IntentService.understand` 会因
    `llm_analyzed=False` 直接短路成 CHAT，第二阶段根本不执行。

    2026-08-17 线上实测：旧提示词只写「输出 answer_mode、category、intent_keywords
    JSON」，真实模型返回 answer_mode="trend_query"、category="退款退货域"。
    `_answer_mode` / `_category` 遇到非法值静默回落成 CHAT / UNKNOWN，不抛异常，
    于是整轮问答退化成兜底文案却没有任何异常信号。参考项目
    `LlmIntentAnalysisService.buildPrompt` 本来就逐个列出了可选值，移植时丢了。
    """

    return (
        f"业务索引：\n{index_text}\n商家问题：{question}\n\n"
        f"可选 answer_mode：{_values(AnswerMode)}\n"
        f"可选 category：{_values(QuestionCategory)}\n\n"
        "输出 JSON 字段：\n"
        "  answer_mode      必填  上面 answer_mode 可选值之一，原样照抄，不得自造\n"
        "  category         必填  上面 category 可选值之一，原样照抄，不得自造\n"
        "  intent_keywords  必填  字符串数组，问题里的业务关键词\n"
        "判断不了业务域时 category 填 UNKNOWN；不得译成中文，也不得另造名称。\n"
    ) + _example(
        {
            "answer_mode": "METRIC",
            "category": "REFUND",
            "intent_keywords": ["退货量", "趋势"],
        }
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
