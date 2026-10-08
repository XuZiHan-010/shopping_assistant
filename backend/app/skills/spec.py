"""`SkillSpec`（§6.11）：注册表产出的唯一 Skill 形状。

工具循环据 `ToolResult.payload` 的**类型**是否为 `SkillSpec` 决定能否免围栏（Task 6），
所以这个类型单独成模块：循环只需要认得它，不需要依赖加载实现。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from app.tools.types import ToolRole

#: 受信通道只认这个工具名（与 payload 类型同时成立才免围栏）。
LOAD_SKILL_TOOL: Final = "load_skill"


class SkillLoadError(ValueError):
    """Skill 格式不合法、越界或超限；启动期抛出时阻止服务带病运行。"""


@dataclass(frozen=True)
class SkillSpec:
    # §6.11 定稿字段
    name: str
    version: str  # 版本化（A4）；frontmatter 里的整数也按字符串保存
    roles: frozenset[ToolRole]
    body: str  # 只读白名单资源
    max_chars: int
    # N3 追加字段：索引要展示描述；来源说明是 R8 对复用蓝图的要求
    description: str
    source: str


def render_skill_message(spec: SkillSpec) -> str:
    """受信 Skill 消息的固定格式；只由工具循环在确认来源后调用。"""

    return f'<skill name="{spec.name}" version="{spec.version}">\n{spec.body}\n</skill>'
