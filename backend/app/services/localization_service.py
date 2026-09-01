"""受费用保护的批量本地化服务。

`localize_many()` 按 §3.2 定义的优先级依次尝试，命中越靠前的分支，成本越
低、确定性越强：

```text
源语言精确等于目标语言 -> 原文
源语言为 und 且仅含受保护技术 token -> 原文
源语言为 mixed          -> 只翻译非目标语言自然文本片段（交给 LLM 批量调用，
                            由 prompts/localization.py 的系统提示词第 8 条
                            要求模型自行保留已经是目标语言的片段，不做本地
                            分词/NLP 切分）
确定性词典命中       -> 词典结果（app.localization.catalog，零 LLM）
当前资源人工版本命中 -> 按资源 ID/字段/源版本返回人工译文
机器缓存命中         -> 机器译文
仍缺失               -> 单次批量 LLM 调用 -> 校验 key 完整 -> 缓存
```

任何一步失败（校验失败、缺 key、超字符上限、预算耗尽）都不抛整体异常：
返回已经完成的 key，未完成的 key 从结果字典里缺席。**任何情况下都不把源
中文原样当作译文返回给要求英文的调用方**——机器缓存未命中且 LLM 调用失败
或降级时，该 key 直接缺席，而不是退回 `item.text`。
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from pydantic import ValidationError

from app.llm.client import (
    STRUCTURED_CALL_OPTIONS,
    LlmBudget,
    LlmBudgetError,
    LlmClient,
    LlmUnavailableError,
)
from app.localization.catalog import localize_catalog_value
from app.localization.locales import SourceLanguage, SupportedLocale, detect_source_language
from app.prompts.localization import (
    LOCALIZATION_PROMPT_VERSION,
    LOCALIZATION_SYSTEM_PROMPT,
    ProtectedItem,
    build_localization_user_prompt,
)
from app.repositories.localization import LocalizationScope, ResourceLocalizationKey
from app.schemas.localization import LlmLocalizationBatchResponse, LocalizeItem

# ---------------------------------------------------------------------------
# 占位符保护：调用 LLM 前把 URL、SQL、代码/ID 记号和数字换成不可解释的占位
# token，恢复时校验 token 集合完全一致，防止模型悄悄改写或丢弃这些片段。
# ---------------------------------------------------------------------------

_PLACEHOLDER_TEMPLATE = "〖T{index}〗"
_PLACEHOLDER_PATTERN = re.compile(r"〖T\d+〗")

#: 单趟组合正则：URL/SQL 子句/数字/代码记号四选一，在原文上只扫描一遍。
#: 不能像 `app.localization.locales` 那样分成四趟顺序 `.sub()`——那样后一趟
#: 会重新扫描前一趟刚插入的占位符文本本身（`〖T0〗` 里的 "T0" 会被误判成
#: 一个新的代码记号，产生嵌套占位符），单趟组合正则从根上避免这个问题。
_PROTECT_PATTERN = re.compile(
    r"(?P<sql>\bselect\b.*?\bfrom\b\s+[A-Za-z_][\w.]*(?:\s+where\b[^\n;]*)?)"
    r"|(?P<url>https?://\S+)"
    r"|(?P<number>\d+)"
    r"|(?P<code>[A-Za-z_][A-Za-z0-9_]*)",
    re.IGNORECASE,
)
_SQL_KEYWORDS = {
    "SELECT",
    "FROM",
    "WHERE",
    "INSERT",
    "UPDATE",
    "DELETE",
    "JOIN",
    "GROUP",
    "ORDER",
    "INTO",
    "VALUES",
    "LIMIT",
    "INNER",
    "LEFT",
    "RIGHT",
    "OUTER",
    "DISTINCT",
    "HAVING",
    "UNION",
    "DROP",
    "TABLE",
    "SUM",
    "COUNT",
    "AVG",
    "MAX",
    "MIN",
}


@dataclass(frozen=True)
class _Protected:
    text: str
    tokens: dict[str, str]


def _protect(text: str) -> _Protected:
    """把 URL、SQL 子句、代码/ID 记号和数字替换成占位符，返回映射表。

    `code` 分支命中的只是"形状像标识符的词"（`[A-Za-z_][A-Za-z0-9_]*`），
    还需要再判断它是不是真正需要保护的代码/ID（含下划线、含数字、或本身是
    SQL 关键字）——普通英文单词（如 "please"、"translate"）不保护，留给
    模型正常翻译。
    """

    tokens: dict[str, str] = {}

    def _replace(match: re.Match[str]) -> str:
        code = match.group("code")
        if code is not None and not (
            "_" in code or any(ch.isdigit() for ch in code) or code.upper() in _SQL_KEYWORDS
        ):
            return code
        placeholder = _PLACEHOLDER_TEMPLATE.format(index=len(tokens))
        tokens[placeholder] = match.group(0)
        return placeholder

    protected_text = _PROTECT_PATTERN.sub(_replace, text)
    return _Protected(text=protected_text, tokens=tokens)


def _restore(text: str, tokens: dict[str, str]) -> str | None:
    """恢复占位符；模型返回的占位符集合与发送时不一致则判定校验失败。"""

    found = set(_PLACEHOLDER_PATTERN.findall(text))
    if found != set(tokens):
        return None
    restored = text
    for placeholder, original in tokens.items():
        restored = restored.replace(placeholder, original)
    return restored


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _only_protected_tokens(text: str) -> bool:
    """`und` 时判定是否"仅含受保护技术 token"：保护后不剩任何非空白字符。"""

    protected = _protect(text)
    stripped = _PLACEHOLDER_PATTERN.sub("", protected.text)
    return stripped.strip() == ""


# ---------------------------------------------------------------------------
# 仓储 Protocol：只声明本服务实际用到的方法，方便测试用内存假仓储替身，
# 不强制依赖 SQLAlchemy Session。
# ---------------------------------------------------------------------------


class _LocalizationRepositoryLike(Protocol):
    async def get_merchant_machine_many(
        self,
        *,
        merchant_id: UUID,
        source_hashes: Sequence[str],
        target_locale: SupportedLocale,
        prompt_version: str,
    ) -> dict[str, object]: ...

    async def get_global_machine_many(
        self,
        *,
        source_hashes: Sequence[str],
        target_locale: SupportedLocale,
        prompt_version: str,
    ) -> dict[str, object]: ...

    async def upsert_machine(
        self,
        *,
        merchant_id: UUID | None,
        source_hash: str,
        source_language: SourceLanguage,
        target_locale: SupportedLocale,
        translated_text: str,
        model: str,
        prompt_version: str = "v1",
    ) -> object: ...

    async def get_current_resource_translation(
        self,
        *,
        scope: LocalizationScope,
        key: ResourceLocalizationKey,
        target_locale: SupportedLocale,
        current_source_hash: str,
        current_source_version: int,
    ) -> object: ...

    async def upsert_human(
        self,
        *,
        scope: LocalizationScope,
        key: ResourceLocalizationKey,
        target_locale: SupportedLocale,
        source_hash: str,
        source_version: int,
        source_language: SourceLanguage,
        translated_text: str,
    ) -> object: ...


@dataclass(frozen=True)
class _PendingItem:
    """已经过恒等/词典/资源检查，仍需要走缓存或 LLM 的条目。"""

    key: str
    text: str
    source_hash: str
    source_language: SourceLanguage
    protected: _Protected


class LocalizationService:
    def __init__(
        self,
        repository: _LocalizationRepositoryLike,
        llm: LlmClient,
        *,
        max_batch_items: int,
        max_batch_chars: int,
        model: str,
    ) -> None:
        self._repository = repository
        self._llm = llm
        self._max_batch_items = max_batch_items
        self._max_batch_chars = max_batch_chars
        self._model = model

    async def localize_many(
        self,
        *,
        scope: LocalizationScope,
        items: Sequence[LocalizeItem],
        target_locale: SupportedLocale,
        budget: LlmBudget,
    ) -> dict[str, str]:
        resolved: dict[str, str] = {}
        pending: list[_PendingItem] = []

        for item in items:
            source_language = detect_source_language(item.text)

            # 1. 源语言精确等于目标语言 -> 原文。
            if str(source_language) == str(target_locale):
                resolved[item.key] = item.text
                continue

            # 2. 源语言为 und 且仅含受保护技术 token -> 原文（没有可翻译内容）。
            if source_language is SourceLanguage.UND and _only_protected_tokens(item.text):
                resolved[item.key] = item.text
                continue

            # 3. mixed 不单独处理：混入下方的词典/资源/缓存/LLM 级联，由 LLM
            #    自己按系统提示词第 8 条只翻译非目标语言片段。

            # 4. 确定性词典命中 -> 词典结果，零 LLM。
            catalog_hit = localize_catalog_value(item.text, target_locale)
            if catalog_hit is not None:
                resolved[item.key] = catalog_hit
                continue

            # 5. 当前资源人工版本命中 -> 人工译文优先于机器缓存。
            if item.resource_type is not None and item.resource_id is not None:
                assert item.field_name is not None
                lookup = await self._repository.get_current_resource_translation(
                    scope=scope,
                    key=ResourceLocalizationKey(
                        resource_type=item.resource_type,
                        resource_id=item.resource_id,
                        field_name=item.field_name,
                    ),
                    target_locale=target_locale,
                    current_source_hash=_hash_text(item.text),
                    current_source_version=item.source_version,
                )
                if str(getattr(lookup, "status", "")) == "CURRENT":
                    record = lookup.record  # type: ignore[attr-defined]
                    resolved[item.key] = record.translated_text
                    continue

            pending.append(
                _PendingItem(
                    key=item.key,
                    text=item.text,
                    source_hash=_hash_text(item.text),
                    source_language=source_language,
                    protected=_protect(item.text),
                )
            )

        if not pending:
            return resolved

        # 6. 机器缓存命中 -> 机器译文（单次批量查询覆盖全部剩余条目）。
        cache_hits = await self._fetch_machine_cache(
            scope=scope, pending=pending, target_locale=target_locale
        )
        still_pending: list[_PendingItem] = []
        for pending_item in pending:
            cached = cache_hits.get(pending_item.source_hash)
            if cached is not None:
                resolved[pending_item.key] = cached
            else:
                still_pending.append(pending_item)

        if not still_pending:
            return resolved

        # 7. 仍缺失 -> 分批调用 LLM，逐条校验，成功的写入缓存。
        await self._translate_via_llm(
            scope=scope,
            pending=still_pending,
            target_locale=target_locale,
            budget=budget,
            resolved=resolved,
        )
        return resolved

    async def _fetch_machine_cache(
        self,
        *,
        scope: LocalizationScope,
        pending: Sequence[_PendingItem],
        target_locale: SupportedLocale,
    ) -> dict[str, str]:
        hashes = [item.source_hash for item in pending]
        if scope.kind == "MERCHANT":
            assert scope.merchant_id is not None
            rows = await self._repository.get_merchant_machine_many(
                merchant_id=scope.merchant_id,
                source_hashes=hashes,
                target_locale=target_locale,
                prompt_version=LOCALIZATION_PROMPT_VERSION,
            )
        else:
            rows = await self._repository.get_global_machine_many(
                source_hashes=hashes,
                target_locale=target_locale,
                prompt_version=LOCALIZATION_PROMPT_VERSION,
            )
        return {source_hash: row.translated_text for source_hash, row in rows.items()}  # type: ignore[attr-defined]

    async def _translate_via_llm(
        self,
        *,
        scope: LocalizationScope,
        pending: Sequence[_PendingItem],
        target_locale: SupportedLocale,
        budget: LlmBudget,
        resolved: dict[str, str],
    ) -> None:
        for batch in self._batches(pending):
            protected_items = [
                ProtectedItem(key=item.key, protected_text=item.protected.text) for item in batch
            ]
            user_prompt = build_localization_user_prompt(
                items=protected_items, target_locale=target_locale
            )
            try:
                result = await self._llm.complete(
                    system=LOCALIZATION_SYSTEM_PROMPT,
                    user=user_prompt,
                    fallback="",
                    budget=budget,
                    options=STRUCTURED_CALL_OPTIONS,
                )
            except (LlmBudgetError, LlmUnavailableError):
                # 预算或可用性是结构性问题，后续批次大概率同样失败；
                # 停止尝试，已解析的 key 保留，未解析的 key 缺席。
                return

            if result.degraded or not result.text.strip():
                # 降级/空响应绝不能把 fallback 当译文使用——本批全部缺席，
                # 继续尝试下一批（这批失败不代表后面一定也失败）。
                continue

            try:
                payload = json.loads(result.text)
                response = LlmLocalizationBatchResponse.model_validate(payload)
            except (json.JSONDecodeError, ValidationError):
                continue

            translated_by_key = {row.key: row.text for row in response.items}

            for item in batch:
                translated = translated_by_key.get(item.key)
                if translated is None:
                    continue
                restored = _restore(translated, item.protected.tokens)
                if restored is None:
                    # 占位符集合对不上：模型改写或丢弃了受保护片段，判定校验失败。
                    continue
                resolved[item.key] = restored
                await self._repository.upsert_machine(
                    merchant_id=scope.merchant_id,
                    source_hash=item.source_hash,
                    source_language=item.source_language,
                    target_locale=target_locale,
                    translated_text=restored,
                    model=self._model,
                    prompt_version=LOCALIZATION_PROMPT_VERSION,
                )

    def _batches(self, pending: Sequence[_PendingItem]) -> list[list[_PendingItem]]:
        batches: list[list[_PendingItem]] = []
        current: list[_PendingItem] = []
        current_chars = 0
        for item in pending:
            item_chars = len(item.protected.text)
            if item_chars > self._max_batch_chars:
                # 单条本身就超过批次字符上限，永远凑不成一批，直接跳过
                # （缺席，不抛异常）。
                continue
            if current and (
                len(current) >= self._max_batch_items
                or current_chars + item_chars > self._max_batch_chars
            ):
                batches.append(current)
                current = []
                current_chars = 0
            current.append(item)
            current_chars += item_chars
        if current:
            batches.append(current)
        return batches

    async def save_human_translation(
        self,
        *,
        scope: LocalizationScope,
        key: ResourceLocalizationKey,
        target_locale: SupportedLocale,
        source_text: str,
        source_version: int,
        translated_text: str,
    ) -> object:
        """管理端保存人工确认译文；直接包一层 `upsert_human()`，
        `source_hash`/`source_language` 由当前源文本重新派生，不信任调用方
        传入的历史快照。"""

        return await self._repository.upsert_human(
            scope=scope,
            key=key,
            target_locale=target_locale,
            source_hash=_hash_text(source_text),
            source_version=source_version,
            source_language=detect_source_language(source_text),
            translated_text=translated_text,
        )
