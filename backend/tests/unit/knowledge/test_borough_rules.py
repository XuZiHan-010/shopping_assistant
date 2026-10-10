"""Borough 自有的平台售后规则（2026-10-10 整改；真实评测 QLT-S4-001）。

规则文档只是把后端已经执行的判定写成可引用的条文：条款里的数字必须与代码一致，
文档要能被两端的规则检索找到，且不改动只读参考 Wiki 的镜像种子。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.eval.rag_e5 import _SeedRepository
from app.knowledge.borough_rules import AFTER_SALE_RULES_PATH, BOROUGH_RULE_DOCUMENTS
from app.knowledge.path_policy import resolve_writable_document
from app.knowledge.retrieval import KnowledgeRetrieval
from app.knowledge.wiki_seed import load_borough_rule_entries, load_wiki_seed_entries
from app.schemas.v2.after_sales import AfterSaleType
from app.services.v2.after_sale_eligibility import OrderFacts, check_eligibility
from app.tools.customer.catalog import _customer_visible
from app.tools.merchant.definitions import resolve_rule_search

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)
RULES = next(d for d in BOROUGH_RULE_DOCUMENTS if d.source_path == AFTER_SALE_RULES_PATH).content


def _delivered(ago: timedelta) -> OrderFacts:
    return OrderFacts(
        lifecycle_origin="V2",
        payment_status="PAID",
        fulfillment_status="DELIVERED",
        delivered_at=NOW - ago,
        already_in_progress=False,
        already_refunded=False,
    )


def test_rule_documents_are_complete_and_use_writable_paths() -> None:
    entries = load_borough_rule_entries()

    assert entries and all(entry.is_complete for entry in entries)
    assert all("待团队补充" not in entry.content for entry in entries)
    for entry in entries:
        resolve_writable_document(entry.source_path)  # 路径符合知识后台的写入规则，可被维护


def test_mirror_seed_is_untouched() -> None:
    mirror = load_wiki_seed_entries()

    assert len(mirror) == 21  # 镜像种子与 RAG 评测语料不变
    own = {entry.source_path for entry in load_borough_rule_entries()}
    assert not own & {entry.source_path for entry in mirror}


def test_application_window_clause_matches_the_eligibility_code() -> None:
    assert "签收后 7 天内" in RULES
    assert check_eligibility(_delivered(timedelta(days=7)), now=NOW).allowed is True
    expired = check_eligibility(_delivered(timedelta(days=7, seconds=1)), now=NOW)
    assert expired.allowed is False and expired.reason_code == "WINDOW_EXPIRED"


def test_undelivered_clause_matches_the_eligibility_code() -> None:
    facts = OrderFacts(
        lifecycle_origin="V2",
        payment_status="PAID",
        fulfillment_status="SHIPPED",
        delivered_at=None,
        already_in_progress=False,
        already_refunded=False,
    )

    eligibility = check_eligibility(facts, now=NOW)

    assert "尚未签收的订单不受理退货退款，可以申请仅退款或客服工单" in RULES
    assert eligibility.allowed_types == {AfterSaleType.REFUND_ONLY, AfterSaleType.TICKET}


def test_clauses_are_numbered_so_a_rejection_can_cite_them() -> None:
    for clause in ("第 2.2 条", "第 4.1 条", "第 4.3 条", "第 5.1 条", "第 5.4 条", "第 6.1 条"):
        assert clause in RULES
    assert "24 小时内" in RULES  # `first_response_due_at = created_at + 24h`


def test_rules_are_visible_to_customers() -> None:
    assert _customer_visible(AFTER_SALE_RULES_PATH)


@pytest.mark.parametrize("query", ["退货 审核 依据", "售后申请时限是多久", "拒绝售后要写什么依据"])
async def test_merchant_rule_search_ranks_the_written_rules_first(query: str) -> None:
    corpus = _SeedRepository([*load_wiki_seed_entries(), *load_borough_rule_entries()])

    output = await resolve_rule_search(query, retrieval=KnowledgeRetrieval(corpus))

    payload = output.payload
    assert isinstance(payload, dict) and payload["matched"] is True
    assert payload["hits"][0]["source_path"] == AFTER_SALE_RULES_PATH
