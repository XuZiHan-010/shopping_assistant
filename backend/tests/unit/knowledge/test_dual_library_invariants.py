"""双库防污染的不变量。

团队人工知识和商家记忆只允许单向读取回退，不能互相写入。
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import app.services.memory_service as memory_service_module
from app.prompts.memory import MEMORY_MARKER


def test_memory_service_never_touches_knowledge_documents() -> None:
    """写侧的记忆服务不得引用团队知识库模型或仓储。"""

    source = inspect.getsource(memory_service_module)

    assert "KnowledgeDocument" not in source
    assert "KnowledgeRepository" not in source


def test_memory_agent_never_touches_knowledge_documents() -> None:
    source = Path("app/services/memory_agent.py").read_text(encoding="utf-8")

    assert "KnowledgeDocument" not in source
    assert "KnowledgeRepository" not in source


def test_knowledge_repository_exposes_no_memory_write_path() -> None:
    """团队知识仓储不得提供记忆写入方法。"""

    source = Path("app/repositories/knowledge.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    method_names = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef)
    }

    assert not any("memor" in name.lower() for name in method_names)


def test_marker_constant_matches_reference_literal() -> None:
    """历史记忆的兼容标记必须保持与参考实现一致。"""

    assert MEMORY_MARKER == "本轮自动沉淀"
