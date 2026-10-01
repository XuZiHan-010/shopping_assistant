"""压缩锚点：三项必保留信息（PRD A5，契约 §6.12，N4-A Task 1）。

压缩会删掉或改写早期消息，但下列三项丢了就会出错，所以**先抽出、压缩后回填**，
不指望压缩过程「记得保留」：

| 丢了 | 后果 |
| --- | --- |
| 工具来源 | 模型不知道前面拿到过哪些数，只能重查或编造 |
| 数据截至时间 | 指标回答必须带截至时间与定义版本（M3） |
| 草稿版本 | 批准绑定草案版本（D9⑦），模型不能引用一个已被修改的草稿 |

来源范围：**只取本回合的工具结果**。历史回合只回放文字，已落库的响应里只有工具名、调用 ID 与
通用状态短句，没有数值、截至时间或草稿版本；而按 D-N4-1，历史里的数字本来就不是事实来源，
模型须重新调用工具——所以跨回合锚点既无从重建，也不需要（Task 1 步骤 0 的结论）。

安全约束：

- 按**字段白名单**取值，不整段转存 payload——身份字段（商家 ID、顾客键）一概不进；
- 失败的调用与受信 Skill（`SkillSpec`）不是锚点：前者没有数据，后者是做法说明不是事实；
- 锚点源自工具结果，回填进提示词时照常按外部文本围栏（A11）。

锚点只影响**模型看得到什么**；回答里数字的确定性校验始终读完整的 `ToolResult` 列表，不读消息，
不会因压缩而放宽。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from app.agent.loop.fencing import fence
from app.localization.locales import SupportedLocale
from app.skills.spec import SkillSpec
from app.tools.types import ToolOutcome, ToolResult


@dataclass(frozen=True)
class ToolSourceRef:
    """某次工具调用的来源引用：工具名、调用 ID、工具给模型的说明，以及单值结果（若有）。"""

    tool_name: str
    call_id: str
    summary: str
    value: str | None = None


@dataclass(frozen=True)
class DataCutoff:
    metric: str
    cutoff: str
    source: str | None
    definition_version: str | None
    #: 产出这条截至时间的调用（「工具名#call_id」），与工具来源里带数值的那一行同键：
    #: 否则模型无法确认某个数值按哪个定义版本算（2026-09-30 E5 真实对比发现）。
    ref: str = ""


@dataclass(frozen=True)
class DraftRef:
    draft_id: str
    draft_version: int


@dataclass(frozen=True)
class CompactionAnchors:
    tool_sources: tuple[ToolSourceRef, ...] = ()
    data_cutoffs: tuple[DataCutoff, ...] = ()
    draft_versions: tuple[DraftRef, ...] = ()

    def is_empty(self) -> bool:
        return not (self.tool_sources or self.data_cutoffs or self.draft_versions)


def extract_anchors(results: Iterable[ToolResult]) -> CompactionAnchors:
    """按调用顺序抽取；同一调用只出现一次。"""

    sources: list[ToolSourceRef] = []
    cutoffs: list[DataCutoff] = []
    drafts: list[DraftRef] = []
    for result in results:
        if not result.ok or isinstance(result.payload, SkillSpec):
            continue
        payload = result.payload if isinstance(result.payload, Mapping) else {}
        sources.append(
            ToolSourceRef(
                tool_name=result.display.tool_name,
                call_id=result.display.call_id,
                summary=result.summary,
                value=_text(payload.get("value")),
            )
        )
        cutoff = _text(payload.get("data_cutoff"))
        if cutoff is not None:
            cutoffs.append(
                DataCutoff(
                    metric=_text(payload.get("metric")) or result.display.tool_name,
                    cutoff=cutoff,
                    source=_text(payload.get("source")),
                    definition_version=_text(payload.get("definition_version")),
                    ref=f"{result.display.tool_name}#{result.display.call_id}",
                )
            )
        if result.outcome is ToolOutcome.DRAFT_CREATED:
            draft_id = _text(payload.get("draft_id"))
            version = payload.get("draft_version")
            if draft_id is not None and isinstance(version, int):
                drafts.append(DraftRef(draft_id=draft_id, draft_version=version))
    return CompactionAnchors(
        tool_sources=tuple(sources), data_cutoffs=tuple(cutoffs), draft_versions=tuple(drafts)
    )


_HEADINGS: Final[Mapping[SupportedLocale, Mapping[str, str]]] = {
    SupportedLocale.ZH_CN: {
        "title": "【压缩锚点】较早的工具结果已清理或摘要，以下关键信息仍然有效：",
        "sources": "工具来源",
        "cutoffs": "数据截至时间",
        "drafts": "草稿版本",
        "value": "结果值",
        "version": "定义版本",
        "draft_version": "版本",
    },
    SupportedLocale.EN_US: {
        "title": (
            "[Compaction anchors] Earlier tool results were pruned or summarized; "
            "the following facts still hold:"
        ),
        "sources": "Tool sources",
        "cutoffs": "Data cutoff",
        "drafts": "Draft versions",
        "value": "value",
        "version": "definition version",
        "draft_version": "version",
    },
}


def format_anchors(anchors: CompactionAnchors, locale: SupportedLocale) -> str:
    """确定性序列化（同一输入逐字节相同）；空锚点返回空串。不含围栏，见 `render_anchors`。"""

    if anchors.is_empty():
        return ""
    h = _HEADINGS[locale]
    lines = [h["title"]]
    if anchors.tool_sources:
        lines.append(f"{h['sources']}:")
        for ref in anchors.tool_sources:
            value = f" | {h['value']}={ref.value}" if ref.value is not None else ""
            lines.append(f"- {ref.tool_name}#{ref.call_id}: {ref.summary}{value}")
    if anchors.data_cutoffs:
        lines.append(f"{h['cutoffs']}:")
        for cut in anchors.data_cutoffs:
            version = _labelled(h["version"], cut.definition_version)
            extras = [part for part in (cut.source, version) if part]
            suffix = f" ({', '.join(extras)})" if extras else ""
            call_ref = f" [{cut.ref}]" if cut.ref else ""
            lines.append(f"- {cut.metric}{call_ref}: {cut.cutoff}{suffix}")
    if anchors.draft_versions:
        lines.append(f"{h['drafts']}:")
        for draft in anchors.draft_versions:
            lines.append(f"- {draft.draft_id}: {h['draft_version']} {draft.draft_version}")
    return "\n".join(lines)


def render_anchors(anchors: CompactionAnchors, locale: SupportedLocale) -> str:
    """回填进提示词的形式：确定性正文外包一层围栏（锚点源自工具结果，A11）。"""

    body = format_anchors(anchors, locale)
    return fence(body, source="compaction:anchors") if body else ""


def _text(value: Any) -> str | None:
    if value is None or (isinstance(value, (Mapping, Sequence)) and not isinstance(value, str)):
        return None
    return str(value)


def _labelled(label: str, value: str | None) -> str | None:
    return f"{label} {value}" if value else None
