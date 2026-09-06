"""会话列表/详情响应的按页本地化 payload 组装（Task 7，§8.6.3）。

只负责把 Repository 已经取到的**当前这一页**数据，转换成携带目标语言展示
文案的响应对象；不重新实现 `LocalizationService` 的级联判定逻辑（词典/资源
人工译文/机器缓存/LLM 批量翻译的优先级完全交给它），也绝不翻译当前页之外
的任何内容——一个 40 条消息的会话还要拆出正文、思考步骤、质量说明和降级
原因，几百个条目是常态，"打开历史就把整份会话翻一遍"会直接撑爆单请求的
`Settings.localization_max_calls_per_request` / `localization_max_tokens_per_request`
预算。

翻译白名单（Step 5）：消息正文、思考步骤标签、质量说明、降级原因、会话
标题。不翻译：`thinking_steps[].node`（机内部路由键）、`columns`（物理列
名）、`total_rows`/`truncated`（数值/布尔）、`answer_mode`/`quality_status`/
`reaction`（枚举协议值）、`answer_id`（ID）——这些字段在
`ConversationAnswerPayload`/`ConversationSummary` 里原样保留，本模块不触碰。

超预算按条目降级，不整页失败：未能在预算内完成翻译的条目默认返回目标语言
占位文案（R7）。**例外**见 `_degrade_shows_original()`：源语言是 `und`
（没有可翻译的自然语言内容）总是展示原文；源语言是 `mixed` 时只在文本的
"主体语言"（`dominant_script()`，按汉字/英文字母数量粗略判定）与目标展示
语言一致时才展示原文——比如中文问题里夹杂 "GMV" 这类英文缩写，对中文读者
展示原文仍然可读，翻译失败时展示占位文案反而会把用户自己说的话隐藏掉；但
一句以英文缩写开头、其余全是中文的系统提示文案，对英文读者展示原文毫无
意义，仍然展示占位文案。源语言精确等于目标语言，或明确是目标语言之外的
**另一种**受支持语言（`zh-CN` 源配 `en-US` 目标，反之亦然）时都不触发这条
例外——前者在 `LocalizationService.localize_many()` 里已经原样返回，不算
降级；后者展示占位文案，避免把未翻译的外语内容误当成已完成翻译静默展示给
读者。调用方据此把 `localization_degraded`/`localization_degraded_reason`
置入响应，前端对同一游标/分页参数重新 GET 即为重试，已成功条目命中机器
缓存不会重复调用模型。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol
from uuid import UUID

from app.llm.client import LlmBudget
from app.localization.locales import (
    SourceLanguage,
    SupportedLocale,
    detect_source_language,
    dominant_script,
    hash_source_text,
)
from app.models.answer import Answer, Feedback
from app.models.conversation import Conversation, Message
from app.repositories.localization import LocalizationScope
from app.schemas.chat import (
    ConversationAnswerPayload,
    ConversationMessage,
    ConversationSummary,
    ThinkingStep,
)
from app.schemas.localization import LocalizeItem

_ZH = SupportedLocale.ZH_CN
_EN = SupportedLocale.EN_US

#: 未能在预算内完成翻译的条目使用的目标语言占位文案（§8.6.3 举例原文）。
#: 绝不是源语言原文——占位文案本身就是"翻译暂不可用"的显式声明,前端据此
#: 提供"重试翻译"入口,而不是把它当成一句正常回答渲染。
_UNAVAILABLE_PLACEHOLDER: dict[SupportedLocale, str] = {
    _ZH: "翻译暂不可用，请重试",
    _EN: "Translation unavailable — retry",
}

_DEGRADED_REASON: dict[SupportedLocale, str] = {
    _ZH: "本页部分内容未能在预算内完成翻译，可使用相同分页参数重新获取以重试",
    _EN: (
        "Some content on this page could not be translated within the request "
        "budget. Retry by fetching the same page again."
    ),
}

#: `MessagePage.boundary_pairing_unresolved=True` 时使用——分页边界正好把
#: 一轮 USER/ASSISTANT 拆到两页，且跨页续接查询也没能确认配对（数据异常，
#: 正常写路径下不会出现）。与 `_DEGRADED_REASON` 分开一条文案，是因为这不是
#: "翻译没跟上"，而是这页最早一条回答的思考步骤/质量说明等结构化内容确实
#: 缺失——比翻译占位符更严重，因此在两者都发生时优先展示这一条。
_PAIRING_UNRESOLVED_REASON: dict[SupportedLocale, str] = {
    _ZH: "本页最早一条回答未能关联到对应的提问，其思考步骤等详情可能缺失",
    _EN: (
        "The oldest reply on this page could not be linked to its original "
        "question; some of its detail (such as reasoning steps) may be missing."
    ),
}


class LocalizationServiceLike(Protocol):
    """只声明本模块用到的 `LocalizationService.localize_many()` 形状,方便
    测试用内存假实现替身,不强制依赖真实仓储/LLM 客户端。"""

    async def localize_many(
        self,
        *,
        scope: LocalizationScope,
        items: Sequence[LocalizeItem],
        target_locale: SupportedLocale,
        budget: LlmBudget,
    ) -> dict[str, str]: ...


def _placeholder(target_locale: SupportedLocale) -> str:
    return _UNAVAILABLE_PLACEHOLDER[target_locale]


def _degrade_shows_original(original: str, target_locale: SupportedLocale) -> bool:
    """降级时是否展示原文而不是占位文案。

    `und`（没有可翻译的自然语言内容，比如纯 ID/数字）总是展示原文。

    `mixed` 只在文本的"主体语言"（`dominant_script()`）与目标展示语言一致
    时才展示原文——比如中文问题夹了个 "GMV"，对中文读者展示原文仍然可读；
    但一句以 "LLM" 开头、其余全是中文的系统提示文案，对英文读者展示原文
    毫无意义，这种情况仍然展示占位文案。不按这个方向区分的话，任何只夹了
    一两个英文缩写的纯中文系统文案，在英文请求下翻译失败时都会整句展示
    中文原文，而不是一句清楚说"翻译暂不可用"的占位文案。

    源语言精确等于目标语言的情况不会走到这里——级联在
    `LocalizationService.localize_many()` 里已经原样返回，不算降级。源语言
    明确是目标语言之外的**另一种**受支持语言（`zh-CN` 源配 `en-US` 目标，
    反之亦然）时也展示占位文案，不触发这条例外。
    """

    source_language = detect_source_language(original)
    if source_language is SourceLanguage.UND:
        return True
    if source_language is SourceLanguage.MIXED:
        return dominant_script(original) == target_locale
    return False


class _Resolver:
    """包一层 `resolved` 字典的取值逻辑：空源文本直接原样返回（没有可翻译
    内容，不算降级）；非空源文本缺席时按 `_degrade_shows_original()` 决定
    返回原文还是占位文案——**只有真正展示占位文案才记一次降级**：展示原文
    时读者看到的是完整、可读的内容，没有任何东西需要"重试"，`degraded`/
    `localization_degraded_reason` 继续置位只会让前端展示一条没有实际意义
    的重试提示。"""

    def __init__(self, resolved: Mapping[str, str], target_locale: SupportedLocale) -> None:
        self._resolved = resolved
        self._target_locale = target_locale
        self.degraded = False

    def resolve(self, key: str, original: str) -> str:
        if not original:
            return original
        translated = self._resolved.get(key)
        if translated is None:
            if _degrade_shows_original(original, self._target_locale):
                return original
            self.degraded = True
            return _placeholder(self._target_locale)
        return translated


# ---------------------------------------------------------------------------
# 会话列表
# ---------------------------------------------------------------------------


async def localize_conversation_summary(
    *,
    service: LocalizationServiceLike,
    budget: LlmBudget,
    merchant_id: UUID,
    conversations: Sequence[Conversation],
    target_locale: SupportedLocale,
) -> tuple[list[ConversationSummary], bool, str | None]:
    """只翻译 `conversations`（当前 `limit`/`offset` 页）里的会话标题。

    调用方传入多少条,这里就只处理这些条——不会自行去查更多会话,也不会
    因为标题重复而做跨请求缓存以外的额外优化（机器缓存本身已经按
    `source_hash` 去重命中）。
    """

    items = [
        LocalizeItem(key=f"title:{row.id}", text=row.title) for row in conversations if row.title
    ]
    resolved: dict[str, str] = {}
    if items:
        resolved = await service.localize_many(
            scope=LocalizationScope(kind="MERCHANT", merchant_id=merchant_id),
            items=items,
            target_locale=target_locale,
            budget=budget,
        )

    resolver = _Resolver(resolved, target_locale)
    summaries = [
        ConversationSummary(
            id=row.id,
            title=resolver.resolve(f"title:{row.id}", row.title) if row.title else row.title,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
        for row in conversations
    ]
    reason = _DEGRADED_REASON[target_locale] if resolver.degraded else None
    return summaries, resolver.degraded, reason


# ---------------------------------------------------------------------------
# 会话详情：脱敏装配（从 `app.api.routes.chat` 迁入,保持既有规则不变）
# ---------------------------------------------------------------------------


def _history_columns(payload: dict[str, Any]) -> list[str]:
    """从保存的结果提取列名,不把任何明细值回传给历史会话。"""

    rows = payload.get("data_rows")
    if not isinstance(rows, list):
        return []

    columns: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        for column in row:
            if isinstance(column, str) and column not in columns:
                columns.append(column)
    return columns


def _history_answer_payload(
    answer_id: UUID,
    payload: dict[str, Any] | None,
    *,
    is_adopted: bool,
    reaction: str | None,
) -> ConversationAnswerPayload | None:
    """把已保存 ChatResponse 装配为可回放且不含敏感行的历史摘要。"""

    if payload is None:
        return None
    return ConversationAnswerPayload(
        answer_id=answer_id,
        answer_mode=payload["answer_mode"],
        thinking_steps=payload.get("thinking_steps", []),
        quality_status=payload["quality_status"],
        quality_attempts=payload["quality_attempts"],
        quality_notes=payload.get("quality_notes", []),
        degraded=payload["degraded"],
        degraded_reason=payload.get("degraded_reason"),
        is_adopted=is_adopted,
        reaction=reaction,
        columns=_history_columns(payload),
        total_rows=payload.get("total_rows"),
        truncated=payload.get("truncated"),
    )


def _assemble_detail_messages(
    messages: Sequence[Message],
    answers_by_user_message: Mapping[UUID, tuple[Answer, Feedback | None]],
    *,
    carried_last_user_message_id: UUID | None = None,
) -> list[ConversationMessage]:
    """按 USER→ASSISTANT 配对装配历史消息。

    `carried_last_user_message_id` 是跨页续接的起点（Task 7 分页缺陷修复）：
    `message_limit` 为奇数时，某一页最早一条可能是 ASSISTANT，而它配对的
    USER 消息落在更早的一页、不在这次传入的 `messages` 里。调用方
    （`localize_conversation_detail()`）从
    `ConversationRepository.list_messages_page()` 额外查到这个 id 后传进来，
    这里就不再把 `last_user_message_id` 无条件初始化成 `None`——否则这一页
    最早的 ASSISTANT 消息会因为"本页内找不到同页的配对 USER"而整段丢失
    `answer_payload`（思考步骤、质量说明等），而不是真的没有配对。
    """

    last_user_message_id: UUID | None = carried_last_user_message_id
    detail_messages: list[ConversationMessage] = []
    for message in messages:
        if message.role == "USER":
            last_user_message_id = message.id
        history_payload = None
        if message.role == "ASSISTANT" and last_user_message_id is not None:
            matched = answers_by_user_message.get(last_user_message_id)
            if matched is not None:
                answer, feedback = matched
                history_payload = _history_answer_payload(
                    answer.id,
                    answer.response_payload,
                    is_adopted=feedback.is_adopted if feedback is not None else False,
                    reaction=feedback.reaction if feedback is not None else None,
                )
        detail_messages.append(
            ConversationMessage(
                id=message.id,
                role=message.role,
                content=message.content,
                created_at=message.created_at,
                answer_payload=history_payload,
            )
        )
    return detail_messages


# ---------------------------------------------------------------------------
# 会话详情：翻译
# ---------------------------------------------------------------------------


def _add_structured_items(
    items: list[LocalizeItem], message_id: UUID, payload: ConversationAnswerPayload
) -> None:
    for index, step in enumerate(payload.thinking_steps):
        if step.label:
            items.append(LocalizeItem(key=f"message:{message_id}:step:{index}", text=step.label))
    for index, note in enumerate(payload.quality_notes):
        if note:
            items.append(LocalizeItem(key=f"message:{message_id}:note:{index}", text=note))
    if payload.degraded_reason:
        items.append(
            LocalizeItem(
                key=f"message:{message_id}:degraded_reason", text=payload.degraded_reason
            )
        )


def _resolve_structured_payload(
    resolver: _Resolver, message_id: UUID, payload: ConversationAnswerPayload
) -> ConversationAnswerPayload:
    steps = [
        ThinkingStep(
            label=resolver.resolve(f"message:{message_id}:step:{index}", step.label),
            node=step.node,
        )
        for index, step in enumerate(payload.thinking_steps)
    ]
    notes = [
        resolver.resolve(f"message:{message_id}:note:{index}", note)
        for index, note in enumerate(payload.quality_notes)
    ]
    degraded_reason = (
        resolver.resolve(f"message:{message_id}:degraded_reason", payload.degraded_reason)
        if payload.degraded_reason
        else payload.degraded_reason
    )
    return payload.model_copy(
        update={
            "thinking_steps": steps,
            "quality_notes": notes,
            "degraded_reason": degraded_reason,
        }
    )


async def localize_conversation_detail(
    *,
    service: LocalizationServiceLike,
    budget: LlmBudget,
    merchant_id: UUID,
    title: str | None,
    messages: Sequence[Message],
    answers_by_user_message: Mapping[UUID, tuple[Answer, Feedback | None]],
    target_locale: SupportedLocale,
    boundary_user_message_id: UUID | None = None,
    boundary_pairing_unresolved: bool = False,
) -> tuple[str | None, list[ConversationMessage], bool, str | None]:
    """装配并翻译**当前这一页**的会话详情。

    `messages` 必须已经是 Repository 分页之后的结果（`ConversationRepository
    .list_messages_page()` 返回的那一页,时间正序）——本函数不会、也没有能力
    再去多查一条历史之外的消息,预算范围与"当前页"严格重合。

    `boundary_user_message_id` / `boundary_pairing_unresolved` 原样转发自
    `MessagePage`（分页边界拆开 USER/ASSISTANT 配对的修复，见其字段文档）：
    前者让这一页最早的 ASSISTANT 消息仍能正确挂上 `answer_payload`；后者为
    `True` 时说明续接也没能确认配对，装配结果会把该消息的 `answer_payload`
    留空——此时函数强制把返回的 `degraded` 置为 `True` 并给出专门的
    `reason`，绝不让这种数据缺失在响应里悄无声息。

    翻译顺序按可见优先级（§8.6.3 Step 4 原文）：
    最新一轮（该页最后一条消息的正文 + 结构化附属字段）→ 会话标题 →
    较早消息正文 → 较早消息的结构化附属字段。同一次请求的 LLM 调用次数/
    token 预算是硬上限,批次靠前的条目优先被翻译成功,因此这个顺序直接决定
    了预算耗尽时哪些内容先降级——始终是用户最不容易立刻看到的部分（更早
    消息的思考步骤/质量说明）先降级,而不是随机哪条先丢。
    """

    assembled = _assemble_detail_messages(
        messages,
        answers_by_user_message,
        carried_last_user_message_id=boundary_user_message_id,
    )

    items: list[LocalizeItem] = []
    if assembled:
        latest = assembled[-1]
        if latest.content:
            items.append(LocalizeItem(key=f"message:{latest.id}:content", text=latest.content))
        if latest.answer_payload is not None:
            _add_structured_items(items, latest.id, latest.answer_payload)

    if title:
        items.append(LocalizeItem(key="title", text=title))

    earlier = assembled[:-1] if assembled else []
    for message in reversed(earlier):
        if message.content:
            items.append(LocalizeItem(key=f"message:{message.id}:content", text=message.content))
    for message in reversed(earlier):
        if message.answer_payload is not None:
            _add_structured_items(items, message.id, message.answer_payload)

    resolved: dict[str, str] = {}
    if items:
        resolved = await service.localize_many(
            scope=LocalizationScope(kind="MERCHANT", merchant_id=merchant_id),
            items=items,
            target_locale=target_locale,
            budget=budget,
        )

    resolver = _Resolver(resolved, target_locale)
    translated_title = resolver.resolve("title", title) if title else title

    translated_messages: list[ConversationMessage] = []
    for message in assembled:
        content = resolver.resolve(f"message:{message.id}:content", message.content)
        payload = message.answer_payload
        if payload is not None:
            payload = _resolve_structured_payload(resolver, message.id, payload)
        translated_messages.append(
            message.model_copy(update={"content": content, "answer_payload": payload})
        )

    degraded = resolver.degraded or boundary_pairing_unresolved
    if boundary_pairing_unresolved:
        # 数据缺失比翻译占位符更严重，两者都发生时优先展示这一条原因。
        reason = _PAIRING_UNRESOLVED_REASON[target_locale]
    elif resolver.degraded:
        reason = _DEGRADED_REASON[target_locale]
    else:
        reason = None
    return translated_title, translated_messages, degraded, reason


# ---------------------------------------------------------------------------
# 会话删除：派生缓存清理所需的源哈希采集（Step 6）
# ---------------------------------------------------------------------------


def collect_conversation_source_hashes(
    *,
    title: str | None,
    messages: Sequence[Message],
    answers: Sequence[Answer],
) -> set[str]:
    """删除会话前,按本模块的翻译白名单计算需要清理的机器缓存源哈希集合。

    覆盖范围与 `localize_conversation_detail()` 会翻译的字段严格一致：
    会话标题、全部消息正文（不止当前页——删除是对整个会话的一次性操作,
    必须清理这个会话产生过的全部缓存,不能只清最近打开过的那一页）、以及
    每个已保存 Answer payload 的思考步骤标签/质量说明/降级原因。

    返回的哈希如果同时被同一商家的其它内容复用（哈希本身只由源文本决定,
    与它出现在哪个会话无关）,删除缓存只会导致那部分内容之后重新翻译一次,
    不影响任何原始数据的正确性（Step 6 原文）。
    """

    hashes: set[str] = set()
    if title:
        hashes.add(hash_source_text(title))
    for message in messages:
        if message.content:
            hashes.add(hash_source_text(message.content))
    for answer in answers:
        payload = answer.response_payload
        if not payload:
            continue
        for step in payload.get("thinking_steps", []) or []:
            label = step.get("label") if isinstance(step, dict) else None
            if label:
                hashes.add(hash_source_text(label))
        for note in payload.get("quality_notes", []) or []:
            if isinstance(note, str) and note:
                hashes.add(hash_source_text(note))
        degraded_reason = payload.get("degraded_reason")
        if isinstance(degraded_reason, str) and degraded_reason:
            hashes.add(hash_source_text(degraded_reason))
    return hashes
