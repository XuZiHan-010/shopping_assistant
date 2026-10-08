"""PostgreSQL 约束测试共用的 SQLSTATE 断言。"""

from __future__ import annotations

from typing import Any

CHECK_VIOLATION = "23514"
UNIQUE_VIOLATION = "23505"
NOT_NULL_VIOLATION = "23502"
GENERATED_ALWAYS = "428C9"
RAISE_EXCEPTION = "P0001"


def assert_sqlstate(exc_info: Any, sqlstate: str, constraint: str | None = None) -> None:
    orig = exc_info.value.orig
    assert orig.sqlstate == sqlstate, (orig.sqlstate, str(orig))
    if constraint is not None:
        assert orig.diag.constraint_name == constraint, (orig.diag.constraint_name, str(orig))
