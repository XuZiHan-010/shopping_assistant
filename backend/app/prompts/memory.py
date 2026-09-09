"""记忆压缩提示词。"""

from __future__ import annotations

from datetime import datetime

from app.localization.locales import SupportedLocale

MEMORY_MARKER = "本轮自动沉淀"

_MEMORY_SYSTEM_PROMPT_ZH = "你是 Borough 商家 AI 助手的独立记忆整理员。"
_MEMORY_SYSTEM_PROMPT_EN = (
    "You are the independent memory consolidator for the Borough merchant AI assistant."
)

MEMORY_SYSTEM_PROMPT = _MEMORY_SYSTEM_PROMPT_ZH

_MEMORY_SYSTEM_PROMPTS: dict[SupportedLocale, str] = {
    SupportedLocale.ZH_CN: _MEMORY_SYSTEM_PROMPT_ZH,
    SupportedLocale.EN_US: _MEMORY_SYSTEM_PROMPT_EN,
}


def build_memory_system_prompt(locale: SupportedLocale = SupportedLocale.ZH_CN) -> str:
    return _MEMORY_SYSTEM_PROMPTS[locale]


_PROMPT_TEMPLATE_ZH = """请把以下 Borough 商家 AI 助手历史问答压缩成可复用的记忆。
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

_PROMPT_TEMPLATE_EN = """Compress the following Borough merchant AI assistant Q&A history into
reusable memory, written in English.
This is an independent historical memory store — never modify or assume the contents of
the human-maintained business knowledge base.
Requirements:
1. Only retain user intent, available tables/fields, metric definitions, and recommended
   reply phrasing for the current merchant and current business category.
2. Keep it short, accurate, and reusable — never invent database fields.
3. If manually supplied content exists, prefer it over anything else.
4. Never cite, infer, or merge information from other merchants or other business
   categories.

Merchant: {merchant_display}
Category: {category}

Manual notes:
{manual_markdown}

Q&A history:
{history}
"""

_PROMPT_TEMPLATES: dict[SupportedLocale, str] = {
    SupportedLocale.ZH_CN: _PROMPT_TEMPLATE_ZH,
    SupportedLocale.EN_US: _PROMPT_TEMPLATE_EN,
}


def build_memory_prompt(
    *,
    merchant_display: str,
    category: str,
    manual_markdown: str,
    history: list[dict[str, object]],
    locale: SupportedLocale = SupportedLocale.ZH_CN,
) -> str:
    return _PROMPT_TEMPLATES[locale].format(
        merchant_display=merchant_display,
        category=category,
        manual_markdown=manual_markdown,
        history=history,
    )


_UPDATED_AT_LABELS: dict[SupportedLocale, str] = {
    SupportedLocale.ZH_CN: "更新时间",
    SupportedLocale.EN_US: "Updated at",
}


def build_fallback_memory(
    *,
    category: str,
    manual_markdown: str,
    now: datetime | None = None,
    locale: SupportedLocale = SupportedLocale.ZH_CN,
) -> str:
    """LLM 不可用时生成确定性记忆文本。"""

    timestamp = (now or datetime.now()).strftime("%Y-%m-%d %H:%M:%S")
    label = _UPDATED_AT_LABELS[locale]
    return f"# {category}\n\n## {MEMORY_MARKER}\n\n{manual_markdown}\n\n{label}：{timestamp}\n"
