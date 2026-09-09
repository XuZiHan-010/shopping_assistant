"""知识库维护后台的 API 契约。"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.localization.locales import SupportedLocale
from app.schemas.chat import QuestionCategory

#: 文档人工译文的读取结果分类（Task 8 Step 4）：
#: - ``SOURCE``：请求语言与源语言一致，或未指定 ``content_locale``，`content`
#:   就是源正文本身，不涉及任何译文；
#: - ``CURRENT``：命中一份与当前源版本匹配的人工译文；
#: - ``STALE``：存在人工译文但源内容已变化（源哈希/版本不匹配），`content`
#:   回退为源正文，不把过期译文当成当前内容返回（R7）；
#: - ``MISSING``：从未保存过该目标语言的人工译文，同样回退为源正文。
TranslationStatus = Literal["SOURCE", "CURRENT", "STALE", "MISSING"]

#: 文档正文/记忆内容实际使用的语言标注；`content_locale` 用它而不是
#: `SupportedLocale`，因为源内容本身可以是 `mixed`/`und`（比如夹杂 SKU 编码
#: 的中文说明），不能勉强套进只有 zh-CN/en-US 两个值的显示语言枚举。
ContentLanguage = Literal["zh-CN", "en-US", "mixed", "und"]


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
    """`is_source_version=true`（默认）更新源标题/正文本身；`false` 改为保存
    一份人工译文，此时必须显式提供 `content_locale`——源语言可以是
    `mixed`/`und`，不能靠"等于源语言之外的那个"推断目标语言（Task 8 Step 4）。
    """

    content: str
    is_source_version: bool = True
    content_locale: SupportedLocale | None = None

    @model_validator(mode="after")
    def _content_locale_required_for_translation(self) -> KnowledgeDocumentUpdateRequest:
        if not self.is_source_version and self.content_locale is None:
            raise ValueError("is_source_version=false 时必须提供 content_locale")
        return self


class KnowledgeDocumentResponse(BaseModel):
    path: str
    content: str
    read_only: bool
    version: str
    #: `content` 实际使用的语言（源语言本身，或命中的人工译文目标语言）。
    content_locale: ContentLanguage
    #: `content` 相对请求方指定的 `content_locale`（若提供）处于什么状态；
    #: 未指定或与源语言一致时恒为 `SOURCE`。
    translation_status: TranslationStatus


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
