"""压缩锚点：三项必保留信息（PRD A5，契约 §6.12，N4-A Task 1）。

压缩会删掉或改写早期消息，但下列三项丢了就会出错，所以**先抽出、压缩后回填**，
不指望压缩过程「记得保留」：

| 丢了 | 后果 |
| --- | --- |
| 调用记录 | 模型不知道前面拿到过哪些数，只能重查或编造 |
| 数据截至时间 | 指标回答必须带截至时间与定义版本（M3） |
| 草稿版本 | 批准绑定草案版本（D9⑦），模型不能引用一个已被修改的草稿 |

另保留知识检索命中文档的标题与出处：规则正文被清理后，模型仍知道依据出自哪篇文档。
调用记录的小标题不叫「工具来源」：2026-10-06 真实评测里模型照着这个标题把工具名写成了数据来源。

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
    ref: str = ""
    kind: str | None = None


@dataclass(frozen=True)
class DocumentRef:
    """知识检索命中的一篇文档：只留标题与出处，正文须重新检索。"""

    title: str
    citation: str
    ref: str = ""


#: 单次检索保留的文档出处上限；`search_rules` 最多返回 5 篇。
MAX_DOCUMENT_REFS: Final = 5


@dataclass(frozen=True)
class CompactionAnchors:
    tool_sources: tuple[ToolSourceRef, ...] = ()
    data_cutoffs: tuple[DataCutoff, ...] = ()
    draft_versions: tuple[DraftRef, ...] = ()
    documents: tuple[DocumentRef, ...] = ()

    def is_empty(self) -> bool:
        return not (
            self.tool_sources or self.data_cutoffs or self.draft_versions or self.documents
        )


def extract_anchors(results: Iterable[ToolResult]) -> CompactionAnchors:
    """按调用顺序抽取；同一调用只出现一次。"""

    sources: list[ToolSourceRef] = []
    cutoffs: list[DataCutoff] = []
    drafts: list[DraftRef] = []
    documents: list[DocumentRef] = []
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
            if draft_id is not None and type(version) is int and version > 0:
                drafts.append(
                    DraftRef(
                        draft_id=draft_id,
                        draft_version=version,
                        ref=f"{result.display.tool_name}#{result.display.call_id}",
                        kind=_text(payload.get("kind")),
                    )
                )
        documents.extend(
            _document_refs(payload, f"{result.display.tool_name}#{result.display.call_id}")
        )
    return CompactionAnchors(
        tool_sources=tuple(sources),
        data_cutoffs=tuple(cutoffs),
        draft_versions=tuple(drafts),
        documents=tuple(documents),
    )


def _document_refs(payload: Mapping[str, Any], ref: str) -> list[DocumentRef]:
    """知识检索结果里每篇的标题与出处；规则依据被清理后仍能引用出处。

    两种载荷形状：商家 `search_rules` 的 `hits[*].source_path` 与顾客 `get_shop_policy` 的
    `documents[*].citation`。只取这两个字段，正文不进锚点。
    """

    refs: list[DocumentRef] = []
    for list_key, citation_key in _DOCUMENT_SHAPES:
        raw = payload.get(list_key)
        if not isinstance(raw, Sequence) or isinstance(raw, str):
            continue
        for item in raw:
            if len(refs) >= MAX_DOCUMENT_REFS or not isinstance(item, Mapping):
                continue
            title, citation = _text(item.get("title")), _text(item.get(citation_key))
            if title is not None and citation is not None:
                refs.append(DocumentRef(title=title, citation=citation, ref=ref))
    return refs


_DOCUMENT_SHAPES: Final = (("hits", "source_path"), ("documents", "citation"))


_HEADINGS: Final[Mapping[SupportedLocale, Mapping[str, str]]] = {
    SupportedLocale.ZH_CN: {
        "title": (
            "【压缩锚点】以下是后端从本回合已成功返回的工具结果逐字段保留的记录，"
            "不是模型摘要，也不是重新查询。仅明细被清理；各行按原调用顺序排列，"
            "同一行的数值、数据来源、截至时间、定义版本属于同一次调用。"
            "引用指标时须一起保留这四项；数据来源写「数据来源」字段的值，工具名不是数据来源，"
            "调用编号不是草稿编号。"
            "未保留的明细须重新查询，草稿仍须由用户在界面审批："
        ),
        "sources": "已保留的调用记录",
        "documents": "知识文档出处（正文已清理，引用条款内容前须重新检索）",
        "citation": "出处",
        "metric_label": "指标",
        "cutoffs": "数据截至时间",
        "drafts": "草稿版本",
        "value": "结果值",
        "source_label": "数据来源",
        "cutoff_label": "截至时间",
        "version": "定义版本",
        "draft_version": "版本",
        "draft_id": "草稿编号",
        "draft_kind": "草稿类型",
    },
    SupportedLocale.EN_US: {
        "title": (
            "[Compaction anchors] These fields were retained by the backend from successful "
            "tool results in this turn, not generated by a model or a new query. Only details "
            "were pruned. Rows follow original call order; value, data source, cutoff and "
            "definition version on a row belong to the same call. Cite all four together for "
            "a metric; report the value of the data source field as the data source. "
            "A tool name is not a data source; a call ID is not a draft ID. "
            "Missing details require a new query. "
            "Drafts still require user approval in the interface:"
        ),
        "sources": "Retained calls",
        "documents": "Knowledge documents (text pruned; search again before quoting a clause)",
        "citation": "source",
        "metric_label": "metric",
        "cutoffs": "Data cutoff",
        "drafts": "Draft versions",
        "value": "value",
        "source_label": "data source",
        "cutoff_label": "data cutoff",
        "version": "definition version",
        "draft_version": "version",
        "draft_id": "draft ID",
        "draft_kind": "draft kind",
    },
}


def format_anchors(anchors: CompactionAnchors, locale: SupportedLocale) -> str:
    """确定性序列化（同一输入逐字节相同）；空锚点返回空串。不含围栏，见 `render_anchors`。"""

    if anchors.is_empty():
        return ""
    h = _HEADINGS[locale]
    lines = [h["title"]]
    cutoffs_by_ref = {cut.ref: cut for cut in anchors.data_cutoffs if cut.ref}
    drafts_by_ref = {draft.ref: draft for draft in anchors.draft_versions if draft.ref}
    linked_refs = {f"{ref.tool_name}#{ref.call_id}" for ref in anchors.tool_sources}
    if anchors.tool_sources:
        lines.append(f"{h['sources']}:")
        for ref in anchors.tool_sources:
            value = f" | {h['value']}={ref.value}" if ref.value is not None else ""
            cutoff = cutoffs_by_ref.get(f"{ref.tool_name}#{ref.call_id}")
            provenance = ""
            if cutoff is not None:
                provenance = "".join(
                    f" | {label}={item}"
                    for label, item in (
                        (h["metric_label"], cutoff.metric),
                        (h["source_label"], cutoff.source),
                        (h["cutoff_label"], cutoff.cutoff),
                        (h["version"], cutoff.definition_version),
                    )
                    if item is not None
                )
            draft = drafts_by_ref.get(f"{ref.tool_name}#{ref.call_id}")
            draft_fields = _draft_fields(draft, h) if draft is not None else ""
            lines.append(
                f"- {ref.tool_name}#{ref.call_id}: {ref.summary}{value}{provenance}{draft_fields}"
            )
    unlinked_cutoffs = [cut for cut in anchors.data_cutoffs if cut.ref not in linked_refs]
    if unlinked_cutoffs:
        lines.append(f"{h['cutoffs']}:")
        for cut in unlinked_cutoffs:
            version = _labelled(h["version"], cut.definition_version)
            extras = [part for part in (cut.source, version) if part]
            suffix = f" ({', '.join(extras)})" if extras else ""
            call_ref = f" [{cut.ref}]" if cut.ref else ""
            lines.append(f"- {cut.metric}{call_ref}: {cut.cutoff}{suffix}")
    unlinked_drafts = [draft for draft in anchors.draft_versions if draft.ref not in linked_refs]
    if unlinked_drafts:
        lines.append(f"{h['drafts']}:")
        for draft in unlinked_drafts:
            lines.append(f"- {draft.draft_id}: {h['draft_version']} {draft.draft_version}")
    if anchors.documents:
        lines.append(f"{h['documents']}:")
        for document in anchors.documents:
            call_ref = f" [{document.ref}]" if document.ref else ""
            lines.append(f"- {document.title}{call_ref}: {h['citation']}={document.citation}")
    return "\n".join(lines)


def _draft_fields(draft: DraftRef, headings: Mapping[str, str]) -> str:
    kind = f" | {headings['draft_kind']}={draft.kind}" if draft.kind else ""
    return (
        f" | {headings['draft_id']}={draft.draft_id}: "
        f"{headings['draft_version']} {draft.draft_version}{kind}"
    )


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
