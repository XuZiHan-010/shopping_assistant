"""商家会话与对话目录契约；只消费共用组件，不依赖顾客端模块。"""

from datetime import UTC
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from app.core.session import SessionRole
from app.schemas.chat import AnalysisSource, Visualization
from app.schemas.feedback import FeedbackReaction
from app.schemas.v2.common import CursorPage, IdempotentWriteRequest, ShopSlug, V2ChatResponseBase

PublicId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
UtcDatetime = Annotated[AwareDatetime, AfterValidator(lambda value: value.astimezone(UTC))]
SessionToken = Annotated[
    str, StringConstraints(min_length=43, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
]


class MerchantModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MerchantSessionCreateRequest(MerchantModel):
    """身份只来自 Bearer 演示 Token，请求体为空对象。"""


class MerchantSessionCreateResponse(MerchantModel):
    session_id: SessionToken
    role: Literal[SessionRole.MERCHANT]
    expires_at: UtcDatetime
    merchant_display_name: str = Field(min_length=1, max_length=120)
    #: 本店顾客端店铺标识（D-N5-4）：只供「顾客视角」拼新标签链接；从已验证会话解析，不接受传入。
    shop_slug: ShopSlug


class MerchantChatRequest(IdempotentWriteRequest):
    message: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
    conversation_id: PublicId | None = None


class MerchantAnswerMode(StrEnum):
    METRIC = "METRIC"
    DETAIL = "DETAIL"
    RULE = "RULE"
    IDENTITY = "IDENTITY"
    CHAT = "CHAT"
    INVALID = "INVALID"


class MerchantChatResponse(V2ChatResponseBase):
    answer_mode: MerchantAnswerMode
    #: 本回合是否有可画的指标结果，及数据点本身（PRD M3，契约 §8.7.11）；默认
    #: `enabled=false`。只有本回合调用了 `query_metrics`/`attribute_change` 且返回可画
    #: 结果时才为 `true`；降级回答（`degraded=true`）恒为 `false`（R7）。
    visualization: Visualization = Field(default_factory=lambda: Visualization(enabled=False))

    @model_validator(mode="after")
    def conversational_source(self) -> Self:
        if self.answer_mode in {MerchantAnswerMode.CHAT, MerchantAnswerMode.INVALID} and (
            len(self.analysis_sources) != 1
            or self.analysis_sources[0].source != AnalysisSource.NONE
        ):
            raise ValueError("普通对话与拒答只使用 NONE 来源")
        return self

    @model_validator(mode="after")
    def degraded_never_shows_a_chart(self) -> Self:
        if self.degraded and self.visualization.enabled:
            raise ValueError("降级回答不得展示图表（R7）")
        return self


class MerchantConversationSummary(MerchantModel):
    id: PublicId
    title: str = Field(min_length=1, max_length=200)
    created_at: UtcDatetime
    updated_at: UtcDatetime


class MerchantConversationFeedbackState(MerchantModel):
    adopted: bool
    reaction: FeedbackReaction | None
    reason: Annotated[str, StringConstraints(min_length=1, max_length=500)] | None

    @model_validator(mode="after")
    def reason_requires_reaction(self) -> Self:
        if self.reason is not None and self.reaction is None:
            raise ValueError("原因必须附着在赞踩上")
        return self


class MerchantConversationMessage(MerchantModel):
    id: PublicId
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=20000)
    created_at: UtcDatetime
    answer: MerchantChatResponse | None
    feedback: MerchantConversationFeedbackState | None

    @model_validator(mode="after")
    def answer_matches_message(self) -> Self:
        if self.role == "user" and (self.answer is not None or self.feedback is not None):
            raise ValueError("商家消息不得携带最终回答或反馈")
        if self.role == "assistant" and (
            self.answer is None or self.feedback is None or self.content != self.answer.answer
        ):
            raise ValueError("助手消息必须与完整回答及反馈一致")
        return self


class MerchantConversationDetailResponse(MerchantModel):
    conversation: MerchantConversationSummary
    messages: CursorPage[MerchantConversationMessage]
