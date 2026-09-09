"""本地化批量翻译的 Pydantic 契约。

分两类：
- `LocalizeItem` 是调用方（Task 5-8 的各个消费点）传给
  `LocalizationService.localize_many()` 的输入 DTO；
- `LlmLocalizedItem`/`LlmLocalizationBatchResponse` 是校验模型批量翻译输出的
  严格 JSON 契约——`extra="forbid"` 确保模型多塞的任何字段都会让整条校验
  失败，而不是被静默吸收进某个宽松的 `dict[str, Any]`。
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.localization.locales import SupportedLocale

ResourceType = Literal["KNOWLEDGE_DOCUMENT", "MERCHANT_MEMORY"]
ResourceFieldName = Literal["title", "content"]


class LocalizeItem(BaseModel):
    """一条待本地化文本。

    `resource_type`/`resource_id`/`field_name` 三者必须同时提供或同时为空：
    同时提供时，`LocalizationService` 会先按资源当前版本查找人工译文
    （优先于机器缓存）；同时为空表示这是即时文本（如单轮问答的回答正文），
    不参与资源级人工译文优先级，直接走词典/机器缓存/LLM 批量翻译路径。
    """

    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1, max_length=128)
    text: str = Field(max_length=20_000)
    resource_type: ResourceType | None = None
    resource_id: UUID | None = None
    field_name: ResourceFieldName | None = None
    #: 资源当前版本号，用于比对人工译文是否 STALE；即时文本不携带资源信息时
    #: 保持默认值即可，不参与任何比对。
    source_version: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def _require_resource_fields_together(self) -> LocalizeItem:
        provided = (
            self.resource_type is not None,
            self.resource_id is not None,
            self.field_name is not None,
        )
        if any(provided) and not all(provided):
            raise ValueError(
                "resource_type/resource_id/field_name 必须同时提供或同时为空"
            )
        return self


class LocalizeBatchRequest(BaseModel):
    """未来 P1 本地化 API 端点的请求形状；本任务只在服务层内部复用其字段定义。"""

    model_config = ConfigDict(extra="forbid")

    items: list[LocalizeItem] = Field(min_length=1)
    target_locale: SupportedLocale


class LlmLocalizedItem(BaseModel):
    """批量翻译响应里的单条条目；`extra="forbid"` 拒绝模型塞入的任何额外字段。"""

    model_config = ConfigDict(extra="forbid")

    key: str
    text: str


class LlmLocalizationBatchResponse(BaseModel):
    """批量翻译调用的严格 JSON 响应契约：只允许 `{"items": [...]}`。"""

    model_config = ConfigDict(extra="forbid")

    items: list[LlmLocalizedItem]
