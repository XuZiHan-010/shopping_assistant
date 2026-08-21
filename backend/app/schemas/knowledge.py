"""知识库维护后台的 API 契约。"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.chat import QuestionCategory


class KnowledgeTreeNode(BaseModel):
    """虚拟知识库树的一个目录或文档节点。"""

    name: str
    path: str
    node_type: Literal["directory", "document"]
    read_only: bool
    size: int = Field(ge=0)
    version: str
    children: list[KnowledgeTreeNode] = Field(default_factory=list)


class KnowledgeTreeResponse(BaseModel):
    roots: list[KnowledgeTreeNode]


class KnowledgeDocumentRequest(BaseModel):
    path: str
    content: str


class KnowledgeDocumentUpdateRequest(BaseModel):
    content: str


class KnowledgeDocumentResponse(BaseModel):
    path: str
    content: str
    read_only: bool
    version: str


class BusinessDomainRequest(BaseModel):
    name: str


class BusinessDomainRenameRequest(BaseModel):
    new_name: str


class MemoryCompressRequest(BaseModel):
    """管理员手动重压某商家某分类的记忆。

    对应参考项目 ``WikiCompressRequest``：``manual_markdown`` 是人工补充内容，
    压缩时优先保留（见 ``app/prompts/memory.py`` 的提示词第 3 条）。
    """

    merchant_id: UUID
    category: QuestionCategory
    manual_markdown: str = Field(default="", max_length=20_000)


class MemoryCompressResponse(BaseModel):
    merchant_id: UUID
    category: QuestionCategory
    content: str
    history_rows: int
    degraded: bool
    degraded_reason: str | None
