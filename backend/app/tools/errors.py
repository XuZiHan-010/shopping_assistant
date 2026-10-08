"""工具调用的两类失败（§6.9、A3、O5）。

用两种异常而不是一个带 flag 的异常，是为了让「把致命错误当普通错误处理」在类型层面就写不出来：

- `FatalToolError`：工具面、身份参数、来源 / 选项闸门。所有角色只见中性说明，
  终止整个回合（HTTP 403）；
- `GuardrailRejection`：护栏闸门。给出原因码 + 当前限制 + 修正方法，
  转成 `ToolResult(ok=False)` 交还模型。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.core.errors import AppError, ErrorCode
from app.schemas.v2.drafts import GuardrailCheckResult

if TYPE_CHECKING:
    from app.tools.types import ToolDisplay

#: 与 `ResourceForbiddenError` 同一句：「不存在」「不属于你」「被安全闸门拦下」对外不可区分（R5）。
_NEUTRAL_MESSAGE = "无权访问该资源"


class FatalToolError(AppError):
    """身份、权限、安全拦截。对外只有中性说明，闸门名与规则只进安全日志。

    `gate` / `detail` 只供 `app.tools.gates` 写安全日志与审计，不出现在 `str()`、
    `public_message` 或 HTTP 响应里。
    """

    def __init__(self, *, gate: str, tool_name: str, detail: str) -> None:
        super().__init__(
            code=ErrorCode.RESOURCE_FORBIDDEN,
            message=_NEUTRAL_MESSAGE,
            status_code=403,
        )
        self.gate = gate
        self.tool_name = tool_name
        self.detail = detail
        #: 由主循环在抛出前填入：本回合在致命错误之前已完成的工具调用与 LLM 调用数，
        #: 供路由层把已完成的部分落库（§6.10）。只含 `ToolDisplay`，不含 payload。
        self.completed_tool_calls: tuple[ToolDisplay, ...] = ()
        self.llm_calls = 0

    @property
    def public_message(self) -> str:
        return self.message

    def __repr__(self) -> str:
        return f"FatalToolError({_NEUTRAL_MESSAGE!r})"


class GuardrailRejection(Exception):
    """业务护栏未通过：授权主体可见公开规则码、当前限制与修正方法。"""

    def __init__(self, *, code: str, current_limit: str, remediation: str) -> None:
        # 先经契约模型校验：规则码格式、长度与「未通过必须自我说明」由 §8.7 的同一个模型把关。
        self.check = GuardrailCheckResult(
            code=code, passed=False, current_limit=current_limit, remediation=remediation
        )
        super().__init__(code)
