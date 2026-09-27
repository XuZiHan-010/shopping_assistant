"""工具注册表的类型定义（§6.9「输出」）。

`ToolRole` / `WritePolicy` / `ToolSpec` / `ToolResult` / `ToolDisplay` 五个名字按 §6.9 定稿；
其余类型与追加字段是 N2 落地时的补充，已回写到 §6.9「N2 落地补充」。

`ToolDisplay` 是唯一允许进 SSE 的部分，它的字段与 §8.7.5 的 `ToolCallDisplay` / `ToolResultDisplay`
一一对应：状态只用封闭的 `ToolDisplayStatus`，摘要只用契约固定的双语短句——**结构上就放不进**
工具参数、SQL 或结果行。工具自己写的说明（`ToolResult.summary`）只给模型看。
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final, cast

from pydantic import BaseModel

from app.core.errors import ErrorCode
from app.core.session import SessionContext
from app.localization.locales import SupportedLocale
from app.schemas.v2.common import (
    PublicToolSummary,
    ToolCallDisplay,
    ToolDisplayStatus,
    ToolResultDisplay,
)
from app.schemas.v2.drafts import DraftKind, GuardrailCheckResult


class ToolRole(StrEnum):
    CUSTOMER = "CUSTOMER"
    MERCHANT = "MERCHANT"
    MCP_READONLY = "MCP_READONLY"  # 商家工具集的只读子集，见 A8


class WritePolicy(StrEnum):
    READ_ONLY = "READ_ONLY"
    CUSTOMER_DIRECT = "CUSTOMER_DIRECT"  # 购物车绝对数量等天然幂等写
    CUSTOMER_CONFIRMATION = "CUSTOMER_CONFIRMATION"  # 下单、售后等界面确认证据
    MERCHANT_DRAFT = "MERCHANT_DRAFT"  # 商家经营变更只生成草稿


class ToolOutcome(StrEnum):
    """一次调用的内部结局；比对外的 `ToolDisplayStatus` 细，只供后端与模型消费。"""

    SUCCEEDED = "SUCCEEDED"
    DRAFT_CREATED = "DRAFT_CREATED"
    AWAITING_CONFIRMATION = "AWAITING_CONFIRMATION"
    REJECTED = "REJECTED"  # 业务护栏未通过
    INVALID_ARGUMENTS = "INVALID_ARGUMENTS"  # 参数校验失败或工具名不存在


#: 内部结局 → 契约公开状态。草稿与待确认对顾客 / 商家而言都是「这一步处理完了」。
DISPLAY_STATUS: Final[Mapping[ToolOutcome, ToolDisplayStatus]] = {
    ToolOutcome.SUCCEEDED: ToolDisplayStatus.SUCCEEDED,
    ToolOutcome.DRAFT_CREATED: ToolDisplayStatus.SUCCEEDED,
    ToolOutcome.AWAITING_CONFIRMATION: ToolDisplayStatus.SUCCEEDED,
    ToolOutcome.REJECTED: ToolDisplayStatus.FAILED,
    ToolOutcome.INVALID_ARGUMENTS: ToolDisplayStatus.FAILED,
}

#: §8.7.5 允许的固定短句，按语言取值；由契约模型的校验器再核一次。
_PUBLIC_SUMMARY: Final[Mapping[ToolDisplayStatus, Mapping[SupportedLocale, str]]] = {
    ToolDisplayStatus.STARTED: {
        SupportedLocale.ZH_CN: "正在处理",
        SupportedLocale.EN_US: "Processing",
    },
    ToolDisplayStatus.RUNNING: {
        SupportedLocale.ZH_CN: "正在处理",
        SupportedLocale.EN_US: "Processing",
    },
    ToolDisplayStatus.SUCCEEDED: {
        SupportedLocale.ZH_CN: "处理完成",
        SupportedLocale.EN_US: "Completed",
    },
    ToolDisplayStatus.DEGRADED: {
        SupportedLocale.ZH_CN: "暂时不可用",
        SupportedLocale.EN_US: "Unavailable",
    },
    ToolDisplayStatus.UNAVAILABLE: {
        SupportedLocale.ZH_CN: "暂时不可用",
        SupportedLocale.EN_US: "Unavailable",
    },
    ToolDisplayStatus.FAILED: {SupportedLocale.ZH_CN: "处理失败", SupportedLocale.EN_US: "Failed"},
}

_TOOL_NAME: Final = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
UNKNOWN_TOOL_NAME: Final = "unknown_tool"


def public_summary(status: ToolDisplayStatus, locale: SupportedLocale) -> PublicToolSummary:
    return cast(PublicToolSummary, _PUBLIC_SUMMARY[status][locale])


def display_tool_name(name: str) -> str:
    """模型可能编出任意工具名；不合契约格式的一律显示为占位名，不把模型文本带进 SSE。"""

    return name if _TOOL_NAME.fullmatch(name) else UNKNOWN_TOOL_NAME


@dataclass(frozen=True)
class ToolContext:
    """executor 与闸门唯一的身份来源：可信身份只从这里读，绝不从模型参数读。"""

    session: SessionContext
    conversation_id: str
    request_id: str
    locale: SupportedLocale = SupportedLocale.ZH_CN
    # 仅 Chat 路由填入；工具写入事务据此留下可恢复的请求级提交标记。
    client_request_id: str | None = None
    request_digest: str | None = None
    principal_digest: str | None = None
    tool_call_id: str | None = None


@dataclass(frozen=True)
class ObjectRef:
    """工具返回给本对话的对象；来源闸门据此判断「本对话见过它」。"""

    object_type: str
    object_id: str


@dataclass(frozen=True)
class ToolOutput:
    """`READ_ONLY` / `CUSTOMER_DIRECT` 工具的执行结果。"""

    payload: object
    summary: str  # 给模型看的说明；不进 SSE
    row_count: int | None = None
    produced: tuple[ObjectRef, ...] = ()
    #: 图表用的完整数据点（N3 阶段 C，契约 §6.9 落地补充）；**不经 `_tool_message()`
    #: 序列化，模型看不到**，只供 `LoopOutcome.tool_results` 的后端消费方读取。
    #: `payload` 与 `chart_data` 分工：前者是给模型引用的汇总数字，后者是给图表用的
    #: 完整序列——把完整序列塞进 `payload` 会让模型看到全部数据点，既拉高 token
    #: 消耗又违背"模型不产生图表数据点"的精神（即使不生成也不该看到）。
    chart_data: object | None = None


@dataclass(frozen=True)
class DraftProposal:
    """`MERCHANT_DRAFT` 工具只能产出草案；落草稿行由审批闸门经草稿端口完成。"""

    target: ObjectRef
    changes: Mapping[str, object]
    summary: str


@dataclass(frozen=True)
class ConfirmationPreview:
    """`CUSTOMER_CONFIRMATION` 工具只能产出预览；写入走带界面确认证据的端点。"""

    payload: object
    summary: str
    produced: tuple[ObjectRef, ...] = ()


@dataclass(frozen=True)
class ToolDisplay:
    """唯一允许进 SSE 的部分，字段与 §8.7.5 一一对应；没有任何自由文本字段。"""

    tool_name: str
    call_id: str
    status: ToolDisplayStatus
    duration_ms: int
    row_count: int | None

    def call_event(self, locale: SupportedLocale) -> ToolCallDisplay:
        """`tool_call` 事件载荷（调用开始）。"""

        return started_display(self.tool_name, self.call_id, locale)

    def result_event(self, locale: SupportedLocale) -> ToolResultDisplay:
        """`tool_result` 事件载荷；经契约模型校验，状态与短句必须匹配。"""

        return ToolResultDisplay(
            call_id=self.call_id,
            status=self.status,
            duration_ms=self.duration_ms,
            row_count=self.row_count,
            summary=public_summary(self.status, locale),
        )


def started_display(tool_name: str, call_id: str, locale: SupportedLocale) -> ToolCallDisplay:
    return ToolCallDisplay(
        tool_name=display_tool_name(tool_name),
        call_id=call_id,
        status=ToolDisplayStatus.STARTED,
        summary=public_summary(ToolDisplayStatus.STARTED, locale),
    )


@dataclass(frozen=True)
class ToolResult:
    # §6.9 定稿字段
    ok: bool
    payload: object | None  # 结构化结果，供后端确定性代码消费，永不进 SSE
    display: ToolDisplay
    reason_code: ErrorCode | None  # 失败时的公开稳定原因码，不用自由字符串
    # N2 追加字段：都不进 SSE
    outcome: ToolOutcome = ToolOutcome.SUCCEEDED
    summary: str = ""  # 工具给模型的说明
    #: 仅护栏未通过时存在：公开规则码、当前限制与修正方法（O5、Q17），交给模型转述给商家。
    guardrail: GuardrailCheckResult | None = None
    #: 图表用的完整数据点（N3 阶段 C）；不进 SSE，也不进 `_tool_message()` 序列化——
    #: 模型看不到，只供 `LoopOutcome.tool_results` 的后端消费方读取。见 `ToolOutput.chart_data`。
    chart_data: object | None = None


@dataclass(frozen=True)
class ProvenanceRef:
    """声明某个参数引用的对象必须先在本对话由工具返回过。

    参数值可以是单个字符串或字符串列表（批量引用时逐个检查）。
    """

    arg: str
    object_type: str


#: 选项闸门的合法值来源：`{参数名: 后端给出的合法取值集合}`。
OptionSource = Callable[[ToolContext], Awaitable[Mapping[str, frozenset[str]]]]
#: 护栏：不通过时抛 `GuardrailRejection`，通过时什么也不返回。
Guardrail = Callable[[ToolContext, Any], Awaitable[None]]
ToolExecutor = Callable[
    [ToolContext, Any], Awaitable[ToolOutput | DraftProposal | ConfirmationPreview]
]


@dataclass(frozen=True)
class ToolSpec:
    # §6.9 定稿字段
    name: str
    roles: frozenset[ToolRole]
    args_model: type[BaseModel]  # 必须是 Pydantic 模型，extra="forbid"
    write_policy: WritePolicy
    parallelizable: bool
    # N2 追加字段
    description: str
    executor: ToolExecutor
    provenance_refs: tuple[ProvenanceRef, ...] = ()
    option_source: OptionSource | None = None
    guardrail: Guardrail | None = None
    draft_kind: DraftKind | None = None
