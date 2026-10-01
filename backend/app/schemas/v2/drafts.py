"""草稿审批与变更账本契约。批准是 apply 的入参，不是持久状态。"""

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

from app.schemas.v2.common import MAX_MONEY_CENTS, IdempotentWriteRequest

PublicId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
UtcDatetime = Annotated[AwareDatetime, AfterValidator(lambda value: value.astimezone(UTC))]
ApprovalEvidence = Annotated[
    str, StringConstraints(min_length=1, max_length=2048, pattern=r"^[A-Za-z0-9._~-]+$")
]
MAX_ENTRIES = 100
MAX_GUARDRAILS = 20
#: 新起草的草稿版本号。聊天工具只起草、不编辑，模型在回合内见到的草稿版本都是它
#: （D9⑦ 批准绑定版本）。
INITIAL_DRAFT_VERSION = 1


class DraftModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DraftState(StrEnum):
    STAGED = "STAGED"
    APPLIED = "APPLIED"
    DISCARDED = "DISCARDED"
    EXPIRED = "EXPIRED"


class DraftKind(StrEnum):
    RESTOCK = "RESTOCK"
    CONTENT_CHANGE = "CONTENT_CHANGE"
    PRICE_CHANGE = "PRICE_CHANGE"
    COUPON = "COUPON"
    AFTER_SALE_DECISION = "AFTER_SALE_DECISION"


class DraftSummary(DraftModel):
    id: PublicId
    kind: DraftKind
    state: DraftState
    title: str = Field(min_length=1, max_length=200)
    draft_version: int = Field(strict=True, ge=1)
    target_version: int = Field(strict=True, ge=0)
    #: N3 阶段 C：商品内容批量起草时，同一批次的子草稿共享同一个值；仅 `CONTENT_CHANGE`
    #: 可非空（契约 §8.13.1）。审批界面按 `batch_id` 分组展示、支持勾选批准。
    batch_id: PublicId | None = None
    created_at: UtcDatetime
    updated_at: UtcDatetime
    expires_at: UtcDatetime

    @model_validator(mode="after")
    def consistent_times(self) -> Self:
        if self.updated_at < self.created_at:
            raise ValueError("更新时间不得早于创建时间")
        if self.expires_at <= self.created_at:
            raise ValueError("过期时间必须晚于创建时间")
        return self

    @model_validator(mode="after")
    def batch_id_only_for_content_change(self) -> Self:
        if self.batch_id is not None and self.kind is not DraftKind.CONTENT_CHANGE:
            raise ValueError("batch_id 只能出现在 CONTENT_CHANGE 草稿上")
        return self


class DiffUnit(StrEnum):
    TEXT = "TEXT"
    COUNT = "COUNT"
    CENTS = "CENTS"
    BPS = "BPS"
    BOOL = "BOOL"


DiffText = Annotated[str, StringConstraints(max_length=2000)]
DiffValue = (
    DiffText | Annotated[int, Field(strict=True)] | Annotated[bool, Field(strict=True)] | None
)


def _value_matches_unit(value: DiffValue, unit: DiffUnit) -> bool:
    if value is None:
        return True
    if unit == DiffUnit.TEXT:
        return isinstance(value, str)
    if unit == DiffUnit.BOOL:
        return isinstance(value, bool)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return False
    return unit != DiffUnit.CENTS or value <= MAX_MONEY_CENTS


class DraftDiffEntry(DraftModel):
    entry_id: PublicId
    target_type: Literal["PRODUCT", "COUPON", "AFTER_SALE"]
    target_id: PublicId
    field: str = Field(min_length=1, max_length=100)
    unit: DiffUnit
    before: DiffValue
    after: DiffValue
    is_preview: bool

    @model_validator(mode="after")
    def value_matches_unit(self) -> Self:
        if not (
            _value_matches_unit(self.before, self.unit)
            and _value_matches_unit(self.after, self.unit)
        ):
            raise ValueError("差异值必须与单位一致")
        return self


class DraftDiff(DraftModel):
    entries: list[DraftDiffEntry] = Field(min_length=1, max_length=MAX_ENTRIES)

    @model_validator(mode="after")
    def unique_entries(self) -> Self:
        if len({entry.entry_id for entry in self.entries}) != len(self.entries):
            raise ValueError("差异条目不得重复")
        return self


class GuardrailCheckResult(DraftModel):
    """只表达业务护栏；安全闸门的内部规则名不出现在契约里。"""

    code: str = Field(min_length=1, max_length=64, pattern=r"^[A-Z][A-Z0-9_]*$")
    passed: bool
    current_limit: str | None = Field(min_length=1, max_length=200)
    remediation: str | None = Field(min_length=1, max_length=300)

    @model_validator(mode="after")
    def failure_explains_itself(self) -> Self:
        if not self.passed and (self.current_limit is None or self.remediation is None):
            raise ValueError("未通过的护栏必须给出当前限制与修正方法")
        return self


class DraftDetailResponse(DraftSummary):
    """`approval_evidence` 只供工作台 Adapter 消费，不得进入工具投影、SSE 或日志。"""

    diff: DraftDiff
    guardrail_checks: list[GuardrailCheckResult] = Field(max_length=MAX_GUARDRAILS)
    guardrails_checked_at: UtcDatetime
    approval_evidence: ApprovalEvidence | None
    approval_evidence_expires_at: UtcDatetime | None

    @model_validator(mode="after")
    def consistent_detail(self) -> Self:
        staged = self.state == DraftState.STAGED
        if staged != (self.approval_evidence is not None) or staged != (
            self.approval_evidence_expires_at is not None
        ):
            raise ValueError("批准证据仅在暂存草稿上成对出现")
        is_after_sale = self.kind == DraftKind.AFTER_SALE_DECISION
        for entry in self.diff.entries:
            if entry.is_preview and not is_after_sale:
                raise ValueError("仅售后决定草稿可包含应用时才计算的预览值")
            if is_after_sale and entry.unit == DiffUnit.CENTS and not entry.is_preview:
                raise ValueError("售后决定草稿中的金额只能是应用时计算的预览")
        return self


class DraftApplyRequest(IdempotentWriteRequest):
    draft_version: int = Field(strict=True, ge=1)
    target_version: int = Field(strict=True, ge=0)
    approval_evidence: ApprovalEvidence
    accepted_entry_ids: list[PublicId] | None = Field(
        default=None, min_length=1, max_length=MAX_ENTRIES
    )

    @model_validator(mode="after")
    def unique_accepted_entries(self) -> Self:
        if self.accepted_entry_ids is not None and len(set(self.accepted_entry_ids)) != len(
            self.accepted_entry_ids
        ):
            raise ValueError("批准条目不得重复")
        return self


class LedgerActor(DraftModel):
    actor_type: Literal["AGENT", "MERCHANT"]
    label: str = Field(min_length=1, max_length=120)


class ChangeLedgerEntry(DraftModel):
    id: PublicId
    draft_id: PublicId
    kind: DraftKind
    drafted_by: LedgerActor
    approved_by: LedgerActor
    approved_at: UtcDatetime
    applied_entry_ids: list[PublicId] = Field(min_length=1, max_length=MAX_ENTRIES)
    guardrail_results: list[GuardrailCheckResult] = Field(max_length=MAX_GUARDRAILS)

    @model_validator(mode="after")
    def consistent_entry(self) -> Self:
        if self.approved_by.actor_type != "MERCHANT":
            raise ValueError("批准者必须是商家")
        if len(set(self.applied_entry_ids)) != len(self.applied_entry_ids):
            raise ValueError("已应用条目不得重复")
        if not all(result.passed for result in self.guardrail_results):
            raise ValueError("已应用的变更不得带有未通过的护栏结果")
        return self


class DraftApplyResponse(DraftModel):
    draft: DraftSummary
    ledger_entry: ChangeLedgerEntry

    @model_validator(mode="after")
    def consistent_response(self) -> Self:
        if self.draft.state != DraftState.APPLIED:
            raise ValueError("应用成功后草稿必须是已应用状态")
        if self.ledger_entry.draft_id != self.draft.id or self.ledger_entry.kind != self.draft.kind:
            raise ValueError("账本条目必须指向同一草稿")
        return self


class VersionConflictDetail(DraftModel):
    scope: Literal["DRAFT", "TARGET"]


class DraftStateDetail(DraftModel):
    state: DraftState
