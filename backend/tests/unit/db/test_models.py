"""ORM 模型契约测试。"""

from __future__ import annotations


def test_merchant_memory_isolates_by_merchant_and_category() -> None:
    from app.models.knowledge import MerchantMemory

    table = MerchantMemory.__table__
    assert table.name == "merchant_memories"
    constraint_names = {constraint.name for constraint in table.constraints}
    assert "uq_merchant_memories_merchant_category" in constraint_names
    assert table.c.merchant_id.nullable is False
    assert table.c.category.nullable is False
    # 记忆按商家隔离：外键级联删除，商家注销时记忆一并消失。
    foreign_keys = {foreign_key.target_fullname for foreign_key in table.c.merchant_id.foreign_keys}
    assert foreign_keys == {"merchants.id"}
