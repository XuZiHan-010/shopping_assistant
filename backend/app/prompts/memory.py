"""记忆压缩提示词。"""

from __future__ import annotations

from datetime import datetime

MEMORY_MARKER = "本轮自动沉淀"

MEMORY_SYSTEM_PROMPT = "你是 Borough 商家 AI 助手的独立记忆整理员。"

_PROMPT_TEMPLATE = """请把以下 Borough 商家 AI 助手历史问答压缩成可复用的记忆。
这是独立的历史记忆库，不得修改或假设人工维护的业务知识库。
要求：
1. 只沉淀当前商家、当前业务分类的用户意图、可用表、字段、口径和推荐回复话术。
2. 信息要短、准、可复用，不要编造数据库字段。
3. 如果人工补充内容存在，优先保留人工补充。
4. 不得引用、推测或合并其他商家和其他业务分类的信息。

商家：{merchant_display}
分类：{category}

人工补充：
{manual_markdown}

历史问答：
{history}
"""


def build_memory_prompt(
    *,
    merchant_display: str,
    category: str,
    manual_markdown: str,
    history: list[dict[str, object]],
) -> str:
    return _PROMPT_TEMPLATE.format(
        merchant_display=merchant_display,
        category=category,
        manual_markdown=manual_markdown,
        history=history,
    )


def build_fallback_memory(
    *,
    category: str,
    manual_markdown: str,
    now: datetime | None = None,
) -> str:
    """LLM 不可用时生成确定性记忆文本。"""

    timestamp = (now or datetime.now()).strftime("%Y-%m-%d %H:%M:%S")
    return f"# {category}\n\n## {MEMORY_MARKER}\n\n{manual_markdown}\n\n更新时间：{timestamp}\n"
