"""两层知识检索的行为测试。"""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.knowledge.retrieval import KnowledgeRetrieval, strip_metric_suffix
from app.llm.client import LlmBudget
from app.localization.locales import SupportedLocale
from app.schemas.chat import QuestionCategory


class _FakeLocalizer:
    """跨语言召回测试专用：模拟 `LocalizationService.localize_many()` 的形状，
    按固定映射表返回译文，不真的调用任何模型。`calls` 计数用于断言相同问题
    命中缓存/已命中语料时不会重复发起「LLM 调用」。"""

    def __init__(self, translations: dict[str, str]) -> None:
        self.calls = 0
        self.received_texts: list[str] = []
        self._translations = translations

    async def localize_many(
        self, *, scope: object, items: object, target_locale: object, budget: object
    ) -> dict[str, str]:
        self.calls += 1
        resolved: dict[str, str] = {}
        for item in items:  # type: ignore[attr-defined]
            self.received_texts.append(item.text)
            translated = self._translations.get(item.text)
            if translated is not None:
                resolved[item.key] = translated
        return resolved


class _FakeDocument:
    def __init__(
        self,
        source_path: str,
        title: str,
        content: str,
        category: str = "TRADE",
        is_complete: bool = True,
    ) -> None:
        self.source_path = source_path
        self.title = title
        self.content = content
        self.category = category
        self.is_complete = is_complete
        self.status = "ACTIVE"


class _FakeRepository:
    def __init__(self, documents: list[_FakeDocument]) -> None:
        self._documents = documents

    async def list_active(self) -> list[_FakeDocument]:
        return self._documents


def _documents() -> list[_FakeDocument]:
    return [
        _FakeDocument("index/README.md", "业务索引", "交易 退货 优惠券 各域目录"),
        _FakeDocument("平台规则/rule.md", "平台规则", "上架规则与政策要求"),
        _FakeDocument("业务/交易/业务流程/交易流程.md", "交易流程", "下单 支付 履约 订单"),
        _FakeDocument("业务/退货/业务流程/退货流程.md", "退货流程", "退货 退款 售后"),
        _FakeDocument(
            "业务/优惠券/业务名词解释/优惠券名词.md",
            "优惠券名词",
            "优惠券 ⚠️ 待团队补充",
            category="COUPON",
            is_complete=False,
        ),
    ]


@pytest.mark.asyncio
async def test_index_retrieval_only_loads_index_and_rule_documents() -> None:
    """若索引层读取正文，分类阶段会把无关事实塞入模型上下文。"""

    result = await KnowledgeRetrieval(_FakeRepository(_documents())).load_index()

    assert [hit.source_path for hit in result.hits] == ["index/README.md", "平台规则/rule.md"]
    assert result.matched is True


@pytest.mark.asyncio
async def test_domain_retrieval_matches_domain_aliases() -> None:
    """漏掉别名会令相应业务域无法取得正文知识。"""

    result = await KnowledgeRetrieval(_FakeRepository(_documents())).load_domain(
        QuestionCategory.REFUND, ()
    )

    assert [hit.source_path for hit in result.hits] == ["业务/退货/业务流程/退货流程.md"]


@pytest.mark.asyncio
async def test_domain_retrieval_narrows_results_by_intent_keyword() -> None:
    """忽略意图关键词会让正文层返回整个领域的无关文档。"""

    retrieval = KnowledgeRetrieval(_FakeRepository(_documents()))

    hit = await retrieval.load_domain(QuestionCategory.TRADE, ("履约",))
    miss = await retrieval.load_domain(QuestionCategory.TRADE, ("赔付",))

    assert [item.source_path for item in hit.hits] == ["业务/交易/业务流程/交易流程.md"]
    assert miss.matched is False


@pytest.mark.asyncio
async def test_metric_suffix_is_stripped_before_keyword_matching() -> None:
    """若不剥离“量”，用户的退货量问题会错过只写“退货”的知识。"""

    result = await KnowledgeRetrieval(_FakeRepository(_documents())).load_domain(
        QuestionCategory.REFUND, ("退货量",)
    )

    assert [item.source_path for item in result.hits] == ["业务/退货/业务流程/退货流程.md"]


@pytest.mark.asyncio
async def test_no_knowledge_is_an_explicit_unmatched_result() -> None:
    """静默返回空文本会让调用方把没有依据的回答当成知识结果。"""

    result = await KnowledgeRetrieval(_FakeRepository([])).load_domain(QuestionCategory.SCM, ())

    assert result.matched is False
    assert result.hits == ()
    assert result.text == ""


@pytest.mark.asyncio
async def test_incomplete_hits_are_exposed_to_the_answer_layer() -> None:
    """丢失骨架文档标记会让后续回答隐藏资料不完整的事实。"""

    result = await KnowledgeRetrieval(_FakeRepository(_documents())).load_domain(
        QuestionCategory.COUPON, ()
    )

    assert result.has_incomplete is True


@pytest.mark.asyncio
async def test_knowledge_text_is_limited_to_the_retrieval_budget() -> None:
    """缺少长度上限会让单篇长知识耗尽模型上下文。"""

    long_document = _FakeDocument("业务/交易/长文.md", "长文", "订单" + "凑" * 30_000)
    result = await KnowledgeRetrieval(_FakeRepository([long_document])).load_domain(
        QuestionCategory.TRADE, ()
    )

    from app.knowledge.domains import MAX_KNOWLEDGE_CHARS

    assert len(result.text) <= MAX_KNOWLEDGE_CHARS


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("退货量", "退货"), ("成交金额", "成交"), ("订单数", "订单"), ("退货", "退货"), ("量", "量")],
)
def test_strip_metric_suffix(raw: str, expected: str) -> None:
    """错误的词尾剥离会改变知识召回范围。"""

    assert strip_metric_suffix(raw) == expected


def _goods_documents() -> list[_FakeDocument]:
    """同域三篇：一篇真正相关，两篇是「只共享泛业务词」的干扰文档。

    2026-08-22 真实模型验收里「商品上架有哪些规则要求」零命中；排查时提出的
    「复合词二元拆分」方案会让「商品」命中全部三篇，把关键词过滤退化成空过滤。
    干扰文档因此是本组测试的必要组成，不能只留正例。
    """

    return [
        _FakeDocument(
            "业务/商品/业务性质介绍/商品规则.md",
            "商品规则",
            "上架需提供资质与类目信息。",
            category="GOODS",
        ),
        _FakeDocument(
            "业务/商品/业务性质介绍/商品定价.md",
            "商品定价",
            "定价策略与折扣区间说明。",
            category="GOODS",
        ),
        _FakeDocument(
            "业务/商品/业务性质介绍/商品库存.md",
            "商品库存",
            "库存同步与预占逻辑。",
            category="GOODS",
        ),
    ]


@pytest.mark.asyncio
async def test_compound_question_recalls_the_relevant_rule_document() -> None:
    """复合问法必须能召回真正回答它的那篇，否则内置推荐问题点进去就是未命中。"""

    result = await KnowledgeRetrieval(_FakeRepository(_goods_documents())).load_domain(
        QuestionCategory.GOODS, ("商品上架", "规则要求")
    )

    assert [hit.source_path for hit in result.hits] == ["业务/商品/业务性质介绍/商品规则.md"]


@pytest.mark.asyncio
async def test_compound_question_excludes_same_domain_distractors() -> None:
    """只共享泛业务词「商品」的同域文档不得被召回，否则过滤等于没做。"""

    result = await KnowledgeRetrieval(_FakeRepository(_goods_documents())).load_domain(
        QuestionCategory.GOODS, ("商品上架", "规则要求")
    )

    paths = {hit.source_path for hit in result.hits}
    assert "业务/商品/业务性质介绍/商品定价.md" not in paths
    assert "业务/商品/业务性质介绍/商品库存.md" not in paths


@pytest.mark.asyncio
async def test_compound_recall_is_ranked_and_capped() -> None:
    """命中过多时按相关性取前若干篇，标题与路径命中应排在只有正文命中的前面。"""

    documents = [
        _FakeDocument("业务/商品/上架规则.md", "上架规则", "商品上架规则总览。", category="GOODS"),
        _FakeDocument("业务/商品/审核规范.md", "审核规范", "商品上架审核标准。", category="GOODS"),
        _FakeDocument(
            "业务/商品/类目要求.md", "类目要求", "商品上架的类目规则。", category="GOODS"
        ),
        _FakeDocument(
            "业务/商品/资质说明.md", "资质说明", "商品上架需要的规则资质。", category="GOODS"
        ),
    ]

    result = await KnowledgeRetrieval(_FakeRepository(documents)).load_domain(
        QuestionCategory.GOODS, ("商品上架", "规则要求")
    )

    assert len(result.hits) == 3
    assert result.hits[0].source_path == "业务/商品/上架规则.md"


@pytest.mark.asyncio
async def test_platform_rule_keeps_whole_library_rule_view() -> None:
    """D2 裁定：PLATFORM_RULE 的全库规则视图与参考项目等价，加锁防回归。

    参考 `WikiMemoryService.java:276` 在 categoryKeywords() 之前 return，按
    「路径含 rule 或 路径+正文含 规则/政策/平台要求」扫描全库；我方 domains.py
    的 PLATFORM_RULE 别名正是同样四个词，且豁免索引路径排除。
    """

    documents = [
        _FakeDocument("index/README.md", "业务索引", "各域目录", category="UNKNOWN"),
        _FakeDocument(
            "平台规则/rule.md", "平台规则", "平台要求与政策说明。", category="PLATFORM_RULE"
        ),
        _FakeDocument("业务/交易/交易流程.md", "交易流程", "下单 支付 履约", category="TRADE"),
    ]

    result = await KnowledgeRetrieval(_FakeRepository(documents)).load_domain(
        QuestionCategory.PLATFORM_RULE, ()
    )

    assert "平台规则/rule.md" in {hit.source_path for hit in result.hits}


# --- Task 6：跨语言知识召回 ------------------------------------------------


def _listing_requirement_documents() -> list[_FakeDocument]:
    """只有中文语料——英文关键词按原文检索必然零命中，必须靠查询规范化才能召回。"""

    return [
        _FakeDocument(
            "业务/商品/业务性质介绍/商品规则.md",
            "商品规则",
            "商品上架需提供资质与类目信息。",
            category="GOODS",
        ),
        _FakeDocument(
            "业务/商品/业务性质介绍/商品定价.md",
            "商品定价",
            "定价策略与折扣区间说明。",
            category="GOODS",
        ),
    ]


@pytest.mark.asyncio
async def test_cross_language_retrieval_recalls_a_chinese_document_for_english_question() -> None:
    """英语问题命中中文语料失败时，额外发起一次查询规范化译文重试召回。

    断言 `retrieval_queries`（这里是方法返回的 queries 列表）同时包含英语
    原问题和 Fake 返回的中文检索查询，最终命中的文档与直接用中文关键词检索
    出的文档相同，原问题文本本身完全未被改写。
    """

    question = "What are the product listing requirements?"
    normalized_query = "商品上架规则要求"
    localizer = _FakeLocalizer({question: normalized_query})
    retrieval = KnowledgeRetrieval(
        _FakeRepository(_listing_requirement_documents()),
        merchant_id=uuid4(),
        localizer=localizer,
    )

    result, queries = await retrieval.load_domain_with_cross_language_retrieval(
        QuestionCategory.GOODS,
        # 英文关键词对纯中文语料完全不命中——注意不能传 `()`：GOODS 域文档本身
        # 靠 `DOMAIN_KEYWORDS` 别名就会全部匹配，空关键词根本不会触发缩窄，
        # 会让"第一次检索"看起来像是命中了，掩盖跨语言重试要验证的行为。
        ("product listing requirements",),
        question=question,
        locale=SupportedLocale.EN_US,
        budget=LlmBudget(4, 4_000),
    )

    assert result.matched is True
    assert [hit.source_path for hit in result.hits] == ["业务/商品/业务性质介绍/商品规则.md"]
    assert queries == [question, normalized_query]
    # 原问题文本必须原样未被改写——规范化译文只用于这一次检索匹配。
    assert queries[0] == question
    assert localizer.calls == 1

    # 用中文关键词直接检索，命中的文档必须与跨语言路径命中的文档完全相同，
    # 证明规范化译文确实复用了同一套匹配逻辑，不是另一条独立通道。
    direct = await retrieval.load_domain(QuestionCategory.GOODS, (normalized_query,))
    assert [hit.source_path for hit in direct.hits] == [hit.source_path for hit in result.hits]


@pytest.mark.asyncio
async def test_cross_language_retrieval_never_overwrites_knowledge_content() -> None:
    """规范化译文只用于检索匹配，绝不写回知识库内容——命中文档的标题/正文必须
    是原始中文，不会被英文问题或英文译文污染。"""

    question = "What are the product listing requirements?"
    localizer = _FakeLocalizer({question: "商品上架规则要求"})
    retrieval = KnowledgeRetrieval(
        _FakeRepository(_listing_requirement_documents()),
        merchant_id=uuid4(),
        localizer=localizer,
    )

    result, _ = await retrieval.load_domain_with_cross_language_retrieval(
        QuestionCategory.GOODS,
        ("product listing requirements",),
        question=question,
        locale=SupportedLocale.EN_US,
        budget=LlmBudget(4, 4_000),
    )

    assert result.hits[0].title == "商品规则"
    assert result.hits[0].content == "商品上架需提供资质与类目信息。"
    assert "requirements" not in result.text.lower()


@pytest.mark.asyncio
async def test_cross_language_retrieval_skips_the_extra_call_when_already_matched() -> None:
    """已经命中就没必要多花一次查询规范化调用——最多增加 1 次的约束里，
    「不必要时是 0 次」同样重要。"""

    localizer = _FakeLocalizer({"any": "any"})
    retrieval = KnowledgeRetrieval(
        _FakeRepository(_documents()), merchant_id=uuid4(), localizer=localizer
    )

    result, queries = await retrieval.load_domain_with_cross_language_retrieval(
        QuestionCategory.REFUND,
        (),
        question="What is the return process?",
        locale=SupportedLocale.EN_US,
        budget=LlmBudget(4, 4_000),
    )

    assert result.matched is True
    assert queries == ["What is the return process?"]
    assert localizer.calls == 0


@pytest.mark.asyncio
async def test_cross_language_retrieval_does_not_trigger_for_a_same_language_miss() -> None:
    """中文问题在中文语料里未命中，属于真正的未命中，不该触发任何翻译调用。"""

    localizer = _FakeLocalizer({})
    retrieval = KnowledgeRetrieval(
        _FakeRepository(_documents()), merchant_id=uuid4(), localizer=localizer
    )

    result, queries = await retrieval.load_domain_with_cross_language_retrieval(
        QuestionCategory.SCM,
        (),
        question="供应链的入库流程是什么",
        locale=SupportedLocale.ZH_CN,
        budget=LlmBudget(4, 4_000),
    )

    assert result.matched is False
    assert queries == ["供应链的入库流程是什么"]
    assert localizer.calls == 0


@pytest.mark.asyncio
async def test_cross_language_retrieval_gives_up_quietly_when_the_localizer_has_nothing() -> None:
    """规范化调用本身失败/降级（Fake 对该问题没有译文）时按未命中原样返回，
    不抛异常，也不会假装命中。"""

    localizer = _FakeLocalizer({})  # 空映射：模拟翻译调用失败/降级
    retrieval = KnowledgeRetrieval(
        _FakeRepository(_listing_requirement_documents()),
        merchant_id=uuid4(),
        localizer=localizer,
    )

    result, queries = await retrieval.load_domain_with_cross_language_retrieval(
        QuestionCategory.GOODS,
        ("product listing requirements",),
        question="What are the product listing requirements?",
        locale=SupportedLocale.EN_US,
        budget=LlmBudget(4, 4_000),
    )

    assert result.matched is False
    assert queries == ["What are the product listing requirements?"]
    assert localizer.calls == 1
