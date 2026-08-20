"""后台与检索的边界。

后台可写团队知识、只读记忆；检索只读、不写。任一方向被打通，这里就红。
"""

from __future__ import annotations

import ast
from pathlib import Path


def test_retrieval_repository_has_no_write_methods() -> None:
    tree = ast.parse(Path("app/repositories/knowledge.py").read_text(encoding="utf-8"))
    names = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef)
    }
    assert not {"delete", "update_content", "move_prefix"} & names


def test_admin_service_never_writes_merchant_memories() -> None:
    source = Path("app/services/knowledge_admin_service.py").read_text(encoding="utf-8")
    # 记忆只读：后台服务不得引用记忆仓储的写方法。
    assert "MerchantMemoryRepository" not in source or "upsert" not in source


def test_admin_routes_do_not_accept_authorization_header() -> None:
    """管理员令牌不复用 Authorization（AGENTS.md §10.2.1）。"""

    source = Path("app/api/routes/knowledge.py").read_text(encoding="utf-8")
    assert "Authorization" not in source
    assert "require_admin_token" in source
