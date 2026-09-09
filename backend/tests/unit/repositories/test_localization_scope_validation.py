"""`LocalizationRepository._validate_scope()` 的纯函数级校验（Finding 3，
全分支复审）。

`upsert_machine()` 和 `upsert_human()` 都把作用域拼进
`index_where=text(f"scope_kind = '{scope_kind}'")`，不是绑定参数——虽然
`ScopeKind = Literal["MERCHANT", "GLOBAL"]` 在类型检查层已经限定取值，
但类型标注不构成运行时保证，`_validate_scope()` 之前只校验 `kind` 与
`merchant_id` 的配对，没有先校验 `kind` 本身只能是这两个字面量之一。这里
不需要数据库：`_validate_scope()` 是纯函数，真正接数据库的作用域反例见
`tests/integration/repositories/test_localization_repository.py` 里的
`test_localization_scope_rejects_merchant_without_merchant_id` 等用例。
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.repositories.localization import LocalizationScope, _validate_scope


def test_validate_scope_accepts_merchant_with_merchant_id() -> None:
    _validate_scope(LocalizationScope(kind="MERCHANT", merchant_id=uuid4()))


def test_validate_scope_accepts_global_without_merchant_id() -> None:
    _validate_scope(LocalizationScope(kind="GLOBAL", merchant_id=None))


def test_validate_scope_rejects_merchant_without_merchant_id() -> None:
    with pytest.raises(ValueError, match="merchant_id"):
        _validate_scope(LocalizationScope(kind="MERCHANT", merchant_id=None))


def test_validate_scope_rejects_global_with_merchant_id() -> None:
    with pytest.raises(ValueError, match="merchant_id"):
        _validate_scope(LocalizationScope(kind="GLOBAL", merchant_id=uuid4()))


def test_validate_scope_rejects_a_stray_third_kind_value() -> None:
    """静态类型标注挡不住绕过类型检查构造出的第三个取值——这条测试直接从
    运行时角度确认它会被拒绝，而不是被原样拼进 `index_where` 的 SQL 里。
    构造方式模拟"某处绕过 mypy"（比如从不受信的反序列化路径构造），不依赖
    `# type: ignore`。"""

    scope = LocalizationScope.__new__(LocalizationScope)
    object.__setattr__(scope, "kind", "DROP TABLE machine_translation_cache; --")
    object.__setattr__(scope, "merchant_id", None)

    with pytest.raises(ValueError, match=r"未知的 LocalizationScope\.kind"):
        _validate_scope(scope)
