"""知识库维护后台的 API 契约。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


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
