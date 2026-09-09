"""LocalizationService 的优先级级联、缓存与预算防护行为。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.llm.client import LlmBudget
from app.llm.fake import FakeLlmClient
from app.localization.locales import SourceLanguage, SupportedLocale
from app.repositories.localization import (
    LocalizationScope,
    ResourceLocalizationKey,
    ResourceLocalizationStatus,
    ResourceTranslationLookup,
)
from app.schemas.localization import LocalizeItem
from app.services.localization_service import LocalizationService

MERCHANT_ID = UUID("00000000-0000-0000-0000-000000000001")
EN_US = SupportedLocale.EN_US
ZH_CN = SupportedLocale.ZH_CN


@dataclass
class _MachineRow:
    translated_text: str
    source_language: SourceLanguage
    model: str


@dataclass
class _HumanRecord:
    translated_text: str
    source_hash: str
    source_version: int
    source_language: SourceLanguage


class FakeLocalizationRepository:
    """内存实现，覆盖 LocalizationService 实际调用的仓储方法子集。"""

    def __init__(self) -> None:
        self._machine: dict[tuple[Any, ...], _MachineRow] = {}
        self._human: dict[tuple[Any, ...], _HumanRecord] = {}
        self.upsert_machine_calls: list[dict[str, object]] = []
        self.upsert_human_calls: list[dict[str, object]] = []

    def _machine_key(
        self,
        *,
        scope_kind: str,
        merchant_id: UUID | None,
        source_hash: str,
        target_locale: SupportedLocale,
        prompt_version: str,
    ) -> tuple[Any, ...]:
        return (scope_kind, merchant_id, source_hash, str(target_locale), prompt_version)

    async def get_merchant_machine_many(
        self, *, merchant_id, source_hashes, target_locale, prompt_version
    ) -> dict[str, _MachineRow]:
        hits: dict[str, _MachineRow] = {}
        for source_hash in source_hashes:
            key = self._machine_key(
                scope_kind="MERCHANT",
                merchant_id=merchant_id,
                source_hash=source_hash,
                target_locale=target_locale,
                prompt_version=prompt_version,
            )
            if key in self._machine:
                hits[source_hash] = self._machine[key]
        return hits

    async def get_global_machine_many(
        self, *, source_hashes, target_locale, prompt_version
    ) -> dict[str, _MachineRow]:
        hits: dict[str, _MachineRow] = {}
        for source_hash in source_hashes:
            key = self._machine_key(
                scope_kind="GLOBAL",
                merchant_id=None,
                source_hash=source_hash,
                target_locale=target_locale,
                prompt_version=prompt_version,
            )
            if key in self._machine:
                hits[source_hash] = self._machine[key]
        return hits

    async def upsert_machine(
        self,
        *,
        merchant_id,
        source_hash,
        source_language,
        target_locale,
        translated_text,
        model,
        prompt_version="v1",
    ) -> _MachineRow:
        scope_kind = "MERCHANT" if merchant_id is not None else "GLOBAL"
        row = _MachineRow(
            translated_text=translated_text, source_language=source_language, model=model
        )
        self._machine[
            self._machine_key(
                scope_kind=scope_kind,
                merchant_id=merchant_id,
                source_hash=source_hash,
                target_locale=target_locale,
                prompt_version=prompt_version,
            )
        ] = row
        self.upsert_machine_calls.append(
            {
                "merchant_id": merchant_id,
                "source_hash": source_hash,
                "source_language": source_language,
                "target_locale": target_locale,
                "translated_text": translated_text,
                "model": model,
                "prompt_version": prompt_version,
            }
        )
        return row

    def _human_key(
        self, *, scope: LocalizationScope, key: ResourceLocalizationKey, target_locale
    ) -> tuple[Any, ...]:
        return (
            scope.kind,
            scope.merchant_id,
            key.resource_type,
            key.resource_id,
            key.field_name,
            str(target_locale),
        )

    async def get_current_resource_translation(
        self, *, scope, key, target_locale, current_source_hash, current_source_version
    ) -> ResourceTranslationLookup:
        record = self._human.get(self._human_key(scope=scope, key=key, target_locale=target_locale))
        if record is None:
            return ResourceTranslationLookup(status=ResourceLocalizationStatus.MISSING, record=None)
        if (
            record.source_hash == current_source_hash
            and record.source_version == current_source_version
        ):
            return ResourceTranslationLookup(
                status=ResourceLocalizationStatus.CURRENT, record=record
            )
        return ResourceTranslationLookup(status=ResourceLocalizationStatus.STALE, record=record)

    async def upsert_human(
        self,
        *,
        scope,
        key,
        target_locale,
        source_hash,
        source_version,
        source_language,
        translated_text,
    ) -> _HumanRecord:
        record = _HumanRecord(
            translated_text=translated_text,
            source_hash=source_hash,
            source_version=source_version,
            source_language=source_language,
        )
        self._human[self._human_key(scope=scope, key=key, target_locale=target_locale)] = record
        self.upsert_human_calls.append(
            {"scope": scope, "key": key, "target_locale": target_locale, "record": record}
        )
        return record


def _translation_response(pairs: dict[str, str]) -> str:
    return json.dumps({"items": [{"key": k, "text": v} for k, v in pairs.items()]})


@pytest.fixture
def repository() -> FakeLocalizationRepository:
    return FakeLocalizationRepository()


@pytest.fixture
def fake_llm() -> FakeLlmClient:
    return FakeLlmClient(responses=[])


def _service(
    repository: FakeLocalizationRepository,
    fake_llm: FakeLlmClient,
    *,
    max_batch_items: int = 20,
    max_batch_chars: int = 12_000,
) -> LocalizationService:
    return LocalizationService(
        repository,
        fake_llm,
        max_batch_items=max_batch_items,
        max_batch_chars=max_batch_chars,
        model="deepseek-v4-flash",
    )


@pytest.fixture
def service(
    repository: FakeLocalizationRepository, fake_llm: FakeLlmClient
) -> LocalizationService:
    return _service(repository, fake_llm)


@pytest.fixture
def merchant_scope() -> LocalizationScope:
    return LocalizationScope(kind="MERCHANT", merchant_id=MERCHANT_ID)


@pytest.fixture
def global_scope() -> LocalizationScope:
    return LocalizationScope(kind="GLOBAL", merchant_id=None)


def budget() -> LlmBudget:
    return LlmBudget(max_calls=4, max_tokens=12_000)


# ---------------------------------------------------------------------------
# 优先级级联：LLM 调用一次，第二次命中机器缓存。
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_localize_many_calls_fake_once_then_hits_cache(
    service: LocalizationService,
    fake_llm: FakeLlmClient,
    merchant_scope: LocalizationScope,
) -> None:
    fake_llm._responses.append(_translation_response({"answer": "Refund amount increased"}))
    items = [LocalizeItem(key="answer", text="退款金额上升")]

    first = await service.localize_many(
        scope=merchant_scope, items=items, target_locale=EN_US, budget=budget()
    )
    second = await service.localize_many(
        scope=merchant_scope, items=items, target_locale=EN_US, budget=budget()
    )

    assert first == second == {"answer": "Refund amount increased"}
    assert len(fake_llm.calls) == 1


# ---------------------------------------------------------------------------
# 恒等跳过：源语言等于目标语言、或 und 且仅含受保护 token。
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_identity_skip_when_source_language_equals_target_locale(
    service: LocalizationService, fake_llm: FakeLlmClient, merchant_scope: LocalizationScope
) -> None:
    items = [LocalizeItem(key="a", text="This store is already in English.")]

    result = await service.localize_many(
        scope=merchant_scope, items=items, target_locale=EN_US, budget=budget()
    )

    assert result == {"a": "This store is already in English."}
    assert fake_llm.calls == []


@pytest.mark.asyncio
async def test_mixed_source_language_is_not_skipped_and_reaches_the_llm(
    service: LocalizationService,
    fake_llm: FakeLlmClient,
    merchant_scope: LocalizationScope,
) -> None:
    """mixed 既不等于目标语言也不是纯技术 token，必须走完级联到 LLM 批量调用；
    不做本地分词，交给 prompts/localization.py 第 8 条指示模型自行只译非目标语言片段。"""

    from app.localization.locales import SourceLanguage, detect_source_language

    text = "退款金额 GMV 本周上升"
    assert detect_source_language(text) is SourceLanguage.MIXED

    fake_llm._responses.append(
        _translation_response({"a": "Refund amount GMV rose this week"})
    )
    items = [LocalizeItem(key="a", text=text)]

    result = await service.localize_many(
        scope=merchant_scope, items=items, target_locale=EN_US, budget=budget()
    )

    assert result == {"a": "Refund amount GMV rose this week"}
    assert len(fake_llm.calls) == 1


@pytest.mark.asyncio
async def test_und_with_only_protected_tokens_skips_llm(
    service: LocalizationService, fake_llm: FakeLlmClient, merchant_scope: LocalizationScope
) -> None:
    items = [LocalizeItem(key="a", text="https://example.com/orders/12345")]

    result = await service.localize_many(
        scope=merchant_scope, items=items, target_locale=EN_US, budget=budget()
    )

    assert result == {"a": "https://example.com/orders/12345"}
    assert fake_llm.calls == []


# ---------------------------------------------------------------------------
# 确定性词典优先，且不写机器缓存。
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_catalog_hit_skips_llm_and_does_not_write_machine_cache(
    service: LocalizationService,
    fake_llm: FakeLlmClient,
    merchant_scope: LocalizationScope,
    repository: FakeLocalizationRepository,
) -> None:
    items = [LocalizeItem(key="a", text="退款金额")]

    result = await service.localize_many(
        scope=merchant_scope, items=items, target_locale=EN_US, budget=budget()
    )

    assert result == {"a": "Refund amount"}
    assert fake_llm.calls == []
    assert repository.upsert_machine_calls == []


# ---------------------------------------------------------------------------
# 资源级人工译文：CURRENT 优先于缓存/LLM；STALE 不使用，继续走下面的级联。
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_current_human_translation_takes_priority_over_llm(
    service: LocalizationService,
    fake_llm: FakeLlmClient,
    merchant_scope: LocalizationScope,
    repository: FakeLocalizationRepository,
) -> None:
    resource_id = uuid4()
    await repository.upsert_human(
        scope=merchant_scope,
        key=ResourceLocalizationKey(
            resource_type="KNOWLEDGE_DOCUMENT", resource_id=resource_id, field_name="content"
        ),
        target_locale=EN_US,
        source_hash=__import__("hashlib").sha256("退货规则说明".encode()).hexdigest(),
        source_version=1,
        source_language=SourceLanguage.ZH_CN,
        translated_text="Return policy (human-reviewed)",
    )
    items = [
        LocalizeItem(
            key="a",
            text="退货规则说明",
            resource_type="KNOWLEDGE_DOCUMENT",
            resource_id=resource_id,
            field_name="content",
            source_version=1,
        )
    ]

    result = await service.localize_many(
        scope=merchant_scope, items=items, target_locale=EN_US, budget=budget()
    )

    assert result == {"a": "Return policy (human-reviewed)"}
    assert fake_llm.calls == []


@pytest.mark.asyncio
async def test_stale_human_translation_is_not_used_and_falls_through_to_llm(
    service: LocalizationService,
    fake_llm: FakeLlmClient,
    merchant_scope: LocalizationScope,
    repository: FakeLocalizationRepository,
) -> None:
    resource_id = uuid4()
    await repository.upsert_human(
        scope=merchant_scope,
        key=ResourceLocalizationKey(
            resource_type="KNOWLEDGE_DOCUMENT", resource_id=resource_id, field_name="content"
        ),
        target_locale=EN_US,
        source_hash="stale-hash-from-a-previous-version",
        source_version=1,
        source_language=SourceLanguage.ZH_CN,
        translated_text="Outdated human translation",
    )
    fake_llm._responses.append(_translation_response({"a": "Updated content, translated"}))
    items = [
        LocalizeItem(
            key="a",
            text="更新后的正文内容",
            resource_type="KNOWLEDGE_DOCUMENT",
            resource_id=resource_id,
            field_name="content",
            source_version=2,
        )
    ]

    result = await service.localize_many(
        scope=merchant_scope, items=items, target_locale=EN_US, budget=budget()
    )

    assert result == {"a": "Updated content, translated"}
    assert len(fake_llm.calls) == 1


# ---------------------------------------------------------------------------
# 批次上限：条目数/字符数超限时自动拆成多次调用。
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_batch_splits_by_max_batch_items(
    repository: FakeLocalizationRepository, fake_llm: FakeLlmClient, merchant_scope
) -> None:
    service = _service(repository, fake_llm, max_batch_items=2, max_batch_chars=12_000)
    # 刻意不含数字：数字会被占位符保护，而 Fake 的响应文本不会带上占位符，
    # 那样测的是「占位符校验拒绝」而不是这里要测的「按批次拆分调用次数」。
    words = ("苹果", "香蕉", "橙子", "葡萄", "西瓜")
    items = [LocalizeItem(key=f"k{i}", text=word) for i, word in enumerate(words)]
    fake_llm._responses.extend(
        [
            _translation_response({"k0": "text0", "k1": "text1"}),
            _translation_response({"k2": "text2", "k3": "text3"}),
            _translation_response({"k4": "text4"}),
        ]
    )

    result = await service.localize_many(
        scope=merchant_scope, items=items, target_locale=EN_US, budget=budget()
    )

    assert result == {f"k{i}": f"text{i}" for i in range(5)}
    assert len(fake_llm.calls) == 3


@pytest.mark.asyncio
async def test_single_item_exceeding_max_batch_chars_is_left_missing(
    repository: FakeLocalizationRepository, fake_llm: FakeLlmClient, merchant_scope
) -> None:
    service = _service(repository, fake_llm, max_batch_items=20, max_batch_chars=10)
    items = [LocalizeItem(key="too_long", text="这段中文文本长度超过了批次字符上限设定值")]

    result = await service.localize_many(
        scope=merchant_scope, items=items, target_locale=EN_US, budget=budget()
    )

    assert result == {}
    assert fake_llm.calls == []


# ---------------------------------------------------------------------------
# 校验失败/缺 key/预算耗尽：不抛整体异常，未完成的 key 缺席，绝不回退源中文。
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_key_in_llm_response_leaves_that_key_absent(
    repository: FakeLocalizationRepository, fake_llm: FakeLlmClient, merchant_scope
) -> None:
    service = _service(repository, fake_llm)
    items = [
        LocalizeItem(key="a", text="第一条正文"),
        LocalizeItem(key="b", text="第二条正文"),
    ]
    # 模型只回了 a，遗漏了 b。
    fake_llm._responses.append(_translation_response({"a": "First body"}))

    result = await service.localize_many(
        scope=merchant_scope, items=items, target_locale=EN_US, budget=budget()
    )

    assert result == {"a": "First body"}
    assert "b" not in result


@pytest.mark.asyncio
async def test_invalid_json_response_leaves_all_batch_items_missing_without_raising(
    repository: FakeLocalizationRepository, fake_llm: FakeLlmClient, merchant_scope
) -> None:
    service = _service(repository, fake_llm)
    items = [LocalizeItem(key="a", text="这段文本无法被正确翻译")]
    fake_llm._responses.append("这不是合法的 JSON")

    result = await service.localize_many(
        scope=merchant_scope, items=items, target_locale=EN_US, budget=budget()
    )

    assert result == {}


@pytest.mark.asyncio
async def test_degraded_llm_result_never_falls_back_to_source_chinese_text(
    repository: FakeLocalizationRepository, merchant_scope
) -> None:
    """降级响应的 fallback 绝不能被当成译文——尤其不能把源中文原样递给英文调用方。"""

    fake_llm = FakeLlmClient(behaviour="timeout")
    service = _service(repository, fake_llm)
    items = [LocalizeItem(key="a", text="这是原始中文正文")]

    result = await service.localize_many(
        scope=merchant_scope, items=items, target_locale=EN_US, budget=budget()
    )

    assert result == {}
    assert "这是原始中文正文" not in result.values()


@pytest.mark.asyncio
async def test_budget_exhaustion_stops_further_batches_without_raising(
    repository: FakeLocalizationRepository, merchant_scope
) -> None:
    fake_llm = FakeLlmClient(responses=[_translation_response({"k0": "ok"})])
    service = _service(repository, fake_llm, max_batch_items=1, max_batch_chars=12_000)
    words = ("独立文本甲", "独立文本乙", "独立文本丙")
    items = [LocalizeItem(key=f"k{i}", text=word) for i, word in enumerate(words)]
    tiny_budget = LlmBudget(max_calls=1, max_tokens=12_000)

    result = await service.localize_many(
        scope=merchant_scope, items=items, target_locale=EN_US, budget=tiny_budget
    )

    # 第一批消耗掉唯一的调用次数后，第二/三批必须安静缺席，不抛异常。
    assert result == {"k0": "ok"}
    assert len(fake_llm.calls) == 1


# ---------------------------------------------------------------------------
# 占位符保护：模型改写/丢弃受保护 token 时，该条目判定校验失败并缺席。
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_placeholder_token_tampering_drops_that_item(
    repository: FakeLocalizationRepository, merchant_scope
) -> None:
    # "订单 12345" 里的数字会被保护成占位符；模拟模型把占位符改没了。
    fake_llm = FakeLlmClient(responses=[_translation_response({"a": "Order number changed"})])
    service = _service(repository, fake_llm)
    items = [LocalizeItem(key="a", text="订单编号 12345 已更新")]

    result = await service.localize_many(
        scope=merchant_scope, items=items, target_locale=EN_US, budget=budget()
    )

    assert result == {}


# ---------------------------------------------------------------------------
# 对抗响应结构：额外字段/改写 key/新增条目必须被安全拒绝，不污染输出结构。
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_response_with_extra_top_level_field_is_rejected_as_a_whole_batch(
    repository: FakeLocalizationRepository, merchant_scope
) -> None:
    """`extra="forbid"` 必须让整批响应校验失败，而不是把额外字段悄悄吸收进来。"""

    hijacked = json.dumps(
        {
            "items": [{"key": "a", "text": "Hijacked translation"}],
            "secrets": "ADMIN_TOKEN=leaked",
        }
    )
    fake_llm = FakeLlmClient(responses=[hijacked])
    service = _service(repository, fake_llm)
    items = [LocalizeItem(key="a", text="正常正文")]

    result = await service.localize_many(
        scope=merchant_scope, items=items, target_locale=EN_US, budget=budget()
    )

    assert result == {}


@pytest.mark.asyncio
async def test_llm_response_item_with_extra_field_fails_the_whole_batch(
    repository: FakeLocalizationRepository, merchant_scope
) -> None:
    hijacked = json.dumps(
        {"items": [{"key": "a", "text": "ok", "role": "system"}]}
    )
    fake_llm = FakeLlmClient(responses=[hijacked])
    service = _service(repository, fake_llm)
    items = [LocalizeItem(key="a", text="正常正文")]

    result = await service.localize_many(
        scope=merchant_scope, items=items, target_locale=EN_US, budget=budget()
    )

    assert result == {}


@pytest.mark.asyncio
async def test_llm_response_with_unsolicited_extra_item_is_silently_ignored(
    repository: FakeLocalizationRepository, merchant_scope
) -> None:
    """模型自行"增加条目"时，多出来的 key 不会出现在结果里——我们只按请求的 key 取值。"""

    hijacked = json.dumps(
        {
            "items": [
                {"key": "a", "text": "Normal body"},
                {"key": "extra_injected_key", "text": "should never surface"},
            ]
        }
    )
    fake_llm = FakeLlmClient(responses=[hijacked])
    service = _service(repository, fake_llm)
    items = [LocalizeItem(key="a", text="正常正文")]

    result = await service.localize_many(
        scope=merchant_scope, items=items, target_locale=EN_US, budget=budget()
    )

    assert result == {"a": "Normal body"}
    assert "extra_injected_key" not in result


@pytest.mark.asyncio
async def test_llm_response_renaming_the_requested_key_leaves_original_key_missing(
    repository: FakeLocalizationRepository, merchant_scope
) -> None:
    """模型把 key 改名后，我们请求的原始 key 依然缺席，不会被冒名的新 key 顶替。"""

    hijacked = json.dumps({"items": [{"key": "renamed_by_model", "text": "ok"}]})
    fake_llm = FakeLlmClient(responses=[hijacked])
    service = _service(repository, fake_llm)
    items = [LocalizeItem(key="original_key", text="正常正文")]

    result = await service.localize_many(
        scope=merchant_scope, items=items, target_locale=EN_US, budget=budget()
    )

    assert result == {}


# ---------------------------------------------------------------------------
# GLOBAL 作用域与 purpose/model 落库。
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_global_scope_writes_global_machine_cache_without_merchant_id(
    repository: FakeLocalizationRepository, global_scope
) -> None:
    fake_llm = FakeLlmClient(responses=[_translation_response({"a": "Platform rule text"})])
    service = _service(repository, fake_llm)
    items = [LocalizeItem(key="a", text="平台规则正文")]

    result = await service.localize_many(
        scope=global_scope, items=items, target_locale=EN_US, budget=budget()
    )

    assert result == {"a": "Platform rule text"}
    assert repository.upsert_machine_calls[0]["merchant_id"] is None
    assert repository.upsert_machine_calls[0]["model"] == "deepseek-v4-flash"


# ---------------------------------------------------------------------------
# save_human_translation() 包一层 upsert_human()。
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_save_human_translation_wraps_repository_upsert_human(
    repository: FakeLocalizationRepository, fake_llm: FakeLlmClient, merchant_scope
) -> None:
    service = _service(repository, fake_llm)
    resource_id = uuid4()

    await service.save_human_translation(
        scope=merchant_scope,
        key=ResourceLocalizationKey(
            resource_type="MERCHANT_MEMORY", resource_id=resource_id, field_name="content"
        ),
        target_locale=EN_US,
        source_text="商家记忆正文",
        source_version=3,
        translated_text="Merchant memory content, reviewed",
    )

    assert len(repository.upsert_human_calls) == 1
    saved = repository.upsert_human_calls[0]["record"]
    assert saved.translated_text == "Merchant memory content, reviewed"
    assert saved.source_version == 3
    assert saved.source_language == SourceLanguage.ZH_CN
