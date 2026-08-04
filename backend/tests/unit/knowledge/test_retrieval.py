"""两层知识检索的行为测试。"""

from __future__ import annotations

import pytest

from app.knowledge.retrieval import KnowledgeRetrieval, strip_metric_suffix
from app.schemas.chat import QuestionCategory


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
