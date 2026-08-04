"""旧 Wiki 导入解析行为。"""

from __future__ import annotations

from pathlib import Path

from app.knowledge.wiki_import import parse_wiki_tree


def _build_tree(root: Path) -> None:
    (root / "index").mkdir(parents=True)
    (root / "index" / "README.md").write_text("# 业务索引\n交易 退货", encoding="utf-8")

    trade_flow = root / "业务" / "交易" / "业务流程"
    trade_flow.mkdir(parents=True)
    (trade_flow / "交易业务流程图.md").write_text(
        "适用范围：yshopping 商家订单分析。", encoding="utf-8"
    )

    trade_ddl = root / "业务" / "交易" / "ddl"
    trade_ddl.mkdir(parents=True)
    (trade_ddl / "交易表.md").write_text(
        "## `yshopping.dwm_trade_order_detail_di`", encoding="utf-8"
    )

    coupon_terms = root / "业务" / "优惠券" / "业务名词解释"
    coupon_terms.mkdir(parents=True)
    (coupon_terms / "优惠券名词.md").write_text("⚠️ 待团队补充", encoding="utf-8")


def test_parse_wiki_tree_excludes_legacy_ddl_documents(tmp_path: Path) -> None:
    """旧表结构若被导入，会让助手描述本项目不存在的数据表。"""

    _build_tree(tmp_path)

    assert not any("ddl" in entry.source_path for entry in parse_wiki_tree(tmp_path))


def test_parse_wiki_tree_rebrands_legacy_content(tmp_path: Path) -> None:
    """旧品牌残留会进入用户可见的知识与模型上下文。"""

    _build_tree(tmp_path)
    trade = next(
        entry for entry in parse_wiki_tree(tmp_path) if "交易业务流程图" in entry.source_path
    )

    assert "yshopping" not in trade.content.lower()
    assert "Borough" in trade.content


def test_parse_wiki_tree_marks_placeholder_documents_incomplete(tmp_path: Path) -> None:
    """丢失骨架标记会让后续回答把不完整资料伪装成正式知识。"""

    _build_tree(tmp_path)
    entries = parse_wiki_tree(tmp_path)

    coupon = next(entry for entry in entries if "优惠券名词" in entry.source_path)
    trade = next(entry for entry in entries if "交易业务流程图" in entry.source_path)
    assert coupon.is_complete is False
    assert trade.is_complete is True


def test_parse_wiki_tree_derives_categories_from_directories(tmp_path: Path) -> None:
    """错误分类会令两层检索将知识投递到错误业务域。"""

    _build_tree(tmp_path)
    categories = {entry.source_path: entry.category for entry in parse_wiki_tree(tmp_path)}

    assert categories["业务/交易/业务流程/交易业务流程图.md"] == "TRADE"
    assert categories["业务/优惠券/业务名词解释/优惠券名词.md"] == "COUPON"
    assert categories["index/README.md"] == "UNKNOWN"


def test_parse_wiki_tree_normalizes_source_paths_to_forward_slashes(tmp_path: Path) -> None:
    """Windows 反斜杠会破坏后续按路径进行的知识匹配。"""

    _build_tree(tmp_path)

    assert all("\\" not in entry.source_path for entry in parse_wiki_tree(tmp_path))
