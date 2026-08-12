from __future__ import annotations

from app.intent.whitelist import DIMENSION_WHITELIST, FILTER_WHITELIST, METRIC_WHITELIST

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


def understand_user_prompt(question: str, category: str, knowledge_text: str) -> str:
    return CROSS_BUSINESS_GUIDANCE + (
        f"业务域：{category}\n业务知识：{knowledge_text}\n商家问题：{question}\n"
        f"输出完整 QueryIntent JSON；metric={sorted(METRIC_WHITELIST)}；"
        f"dimensions={sorted(DIMENSION_WHITELIST)}；filters={sorted(FILTER_WHITELIST)}；"
        "必须输出 analysis_requested 布尔值：仅当用户明确要求分析、解读、原因或建议时为 true，"
        "只要求查看明细时为 false。不得输出 SQL、表名或自由查询文本。"
    )
