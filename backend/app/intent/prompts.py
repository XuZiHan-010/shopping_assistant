from __future__ import annotations

from app.intent.whitelist import DIMENSION_WHITELIST, FILTER_WHITELIST, METRIC_WHITELIST

CLASSIFY_SYSTEM = "你是 Borough 商家 AI 助手的意图分类器。只输出 JSON。"
UNDERSTAND_SYSTEM = "你是 Borough 商家 AI 助手的结构化理解器。只输出 JSON，禁止 SQL。"


def classify_user_prompt(question: str, index_text: str) -> str:
    return (
        f"业务索引：\n{index_text}\n商家问题：{question}\n"
        "输出 answer_mode、category、intent_keywords JSON。"
    )


def understand_user_prompt(question: str, category: str, knowledge_text: str) -> str:
    return (
        f"业务域：{category}\n业务知识：{knowledge_text}\n商家问题：{question}\n"
        f"输出完整 QueryIntent JSON；metric={sorted(METRIC_WHITELIST)}；"
        f"dimensions={sorted(DIMENSION_WHITELIST)}；filters={sorted(FILTER_WHITELIST)}；"
        "必须输出 analysis_requested 布尔值：仅当用户明确要求分析、解读、原因或建议时为 true，"
        "只要求查看明细时为 false。不得输出 SQL、表名或自由查询文本。"
    )
