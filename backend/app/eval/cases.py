"""评测用例模型：分层校验、skip 三件套、断言最少一条（E1、E2）。

`EvalCase` 是安全集与质量集共用的唯一用例形状。安全集额外受
`tests/eval/test_security_gate.py` 的零 skip、`introduced_in` 与路由覆盖
守卫约束，本模块只负责通用的加载与结构校验。
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

#: 真实对话须脱敏改写才可进入用例集（E1）；加载器按这三类形态粗筛，不追求
#: 严格的身份证校验位算法——宁可误报要求改写，也不放过明显的真实个人信息。
_PII_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"1[3-9]\d{9}"),
    re.compile(r"[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}"),
    re.compile(r"\d{17}[\dXx]"),
)


class Risk(StrEnum):
    SECURITY = "SECURITY"  # 进硬门禁
    FINANCIAL = "FINANCIAL"  # 金额、库存
    QUALITY = "QUALITY"  # 语言、引用


class AssertionType(StrEnum):
    HTTP_STATUS = "http_status"
    ERROR_CODE = "error_code"
    AUDIT_WRITTEN = "audit_written"
    NO_SIDE_EFFECT = "no_side_effect"
    #: 质量集专用：检查响应体某个字段的值（如 `answer_mode`/`degraded`）。
    #: 安全集不使用这一种——权限/存在性判定只用前四种。
    RESPONSE_FIELD = "response_field"


class CaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Assertion(CaseModel):
    """代码断言的统一形状；每种类型要求各自必填的字段（Task 2 步骤 2 + 质量集扩展）。"""

    type: AssertionType
    expected: str | int | bool | None = None
    event_type: str | None = None
    table: str | None = None
    where: dict[str, Any] | None = None
    #: `response_field` 专用：响应体里的点号路径，如 `answer_mode` 或 `metric_code`。
    path: str | None = None

    @model_validator(mode="after")
    def _shape_matches_type(self) -> Self:
        if self.type is AssertionType.HTTP_STATUS and not isinstance(self.expected, int):
            raise ValueError("http_status 断言需要整数 expected")
        if self.type is AssertionType.ERROR_CODE and not isinstance(self.expected, str):
            raise ValueError("error_code 断言需要字符串 expected")
        if self.type is AssertionType.AUDIT_WRITTEN and not self.event_type:
            raise ValueError("audit_written 断言需要 event_type")
        if self.type is AssertionType.NO_SIDE_EFFECT and not self.table:
            raise ValueError("no_side_effect 断言需要 table")
        if self.type is AssertionType.RESPONSE_FIELD and (not self.path or self.expected is None):
            raise ValueError("response_field 断言需要 path 与 expected")
        return self


class HttpRequest(CaseModel):
    """端点用例的一次真实 HTTP 调用（Task 2「端点用例」）。"""

    method: Literal["GET", "POST", "PUT", "DELETE", "PATCH"]
    path: str
    headers: dict[str, str] = Field(default_factory=dict)
    json_body: dict[str, Any] | None = Field(default=None, alias="json")
    query: dict[str, str] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class PrimitiveCall(CaseModel):
    """原语用例：按名称调用 `app/eval/primitives.py` 的白名单登记项（Task 2「原语用例」）。"""

    name: str
    args: dict[str, Any] = Field(default_factory=dict)


class EvalTurn(CaseModel):
    actor: str
    request: HttpRequest | None = None
    primitive: PrimitiveCall | None = None

    @model_validator(mode="after")
    def _exactly_one_action(self) -> Self:
        if (self.request is None) == (self.primitive is None):
            raise ValueError("每个 turn 必须且只能提供 request 或 primitive 之一")
        return self


class EvalCase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    role: Literal["CUSTOMER", "MERCHANT"]
    skill: str
    risk: Risk
    locale: Literal["zh-CN", "en-US"]
    turns: list[EvalTurn] = Field(min_length=1)
    assertions: list[Assertion] = Field(min_length=1)  # 至少一条代码断言（E2）
    rubric_id: str | None = None
    skip_reason: str | None = None
    skip_owner: str | None = None
    skip_deadline: date | None = None
    introduced_in: Literal["N1", "N2", "N3", "N4", "N5"] = "N1"
    form: Literal["ENDPOINT", "PRIMITIVE"] = "ENDPOINT"

    @model_validator(mode="after")
    def _http_locale_matches_case(self) -> Self:
        for turn in self.turns:
            if turn.request is None:
                continue
            values = [
                value
                for key, value in turn.request.headers.items()
                if key.lower() == "accept-language"
            ]
            # 评测标签是唯一语言来源；不接受 q 权重/别名掩盖实际分层。
            if len(values) > 1 or (values and values[0] != self.locale):
                raise ValueError("Accept-Language 必须唯一且与用例 locale 一致")
        return self

    @model_validator(mode="after")
    def _skip_triple_complete(self) -> Self:
        fields = (self.skip_reason, self.skip_owner, self.skip_deadline)
        present = [value is not None for value in fields]
        if any(present) and not all(present):
            raise ValueError(
                "skip 三件套（skip_reason/skip_owner/skip_deadline）必须同时出现或同时缺失"
            )
        return self

    @property
    def is_skipped(self) -> bool:
        return self.skip_reason is not None


class CoverageRequirement(CaseModel):
    """`validate_coverage()` 的最小分层要求：至少覆盖两端角色与两种显示语言（E1）。"""

    roles: frozenset[str] = frozenset({"CUSTOMER", "MERCHANT"})
    locales: frozenset[str] = frozenset({"zh-CN", "en-US"})


def _scan_for_pii(payload: str, *, case_id: str) -> None:
    for pattern in _PII_PATTERNS:
        if pattern.search(payload):
            raise ValueError(
                f"用例 {case_id} 疑似包含真实个人信息（手机号/邮箱/身份证形态），"
                "真实对话须脱敏改写后才可进入用例集"
            )


def load_cases(raw_cases: Iterable[Mapping[str, Any]]) -> list[EvalCase]:
    """校验并加载一批用例；skip 已过期或疑似含 PII 时整体加载失败。"""

    cases: list[EvalCase] = []
    today = date.today()
    for raw in raw_cases:
        case = EvalCase.model_validate(raw)
        if case.skip_deadline is not None and case.skip_deadline < today:
            raise ValueError(f"用例 {case.id} 的 skip 已过期（{case.skip_deadline}），请处理或续期")
        _scan_for_pii(case.model_dump_json(), case_id=case.id)
        cases.append(case)
    return cases


def load_cases_from_yaml(path: Path) -> list[EvalCase]:
    """加载单个 YAML 数据集文件；文件内容必须是用例对象的列表。"""

    data = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    if not isinstance(data, list):
        raise ValueError(f"{path} 顶层必须是用例列表")
    return load_cases(data)


def load_cases_from_directory(directory: Path) -> list[EvalCase]:
    """按文件名排序加载目录下全部 `*.yaml` 用例文件，结果顺序确定可复现。"""

    cases: list[EvalCase] = []
    for path in sorted(directory.glob("*.yaml")):
        cases.extend(load_cases_from_yaml(path))
    return cases


_DEFAULT_COVERAGE_REQUIREMENT = CoverageRequirement()


def validate_coverage(
    cases: Sequence[EvalCase],
    *,
    requirement: CoverageRequirement = _DEFAULT_COVERAGE_REQUIREMENT,
) -> None:
    """分层是约束不是标签：缺少必需的角色或语言层直接报错（E1）。"""

    present_roles = {case.role for case in cases}
    present_locales = {case.locale for case in cases}
    missing_roles = requirement.roles - present_roles
    missing_locales = requirement.locales - present_locales
    if missing_roles or missing_locales:
        missing = sorted(missing_roles) + sorted(missing_locales)
        raise ValueError(f"缺少分层：{missing}")


class CaseResult(BaseModel):
    """一条用例的执行结果；`summarize()` 的输入单元。"""

    case_id: str
    passed: bool
    skipped: bool = False
    failure_detail: str | None = None


class SummaryReport(BaseModel):
    total: int
    denominator: int
    passed: int
    skipped: int
    pass_rate: float


def summarize(results: Sequence[CaseResult]) -> SummaryReport:
    """分母是非 skip 用例数——skip 越多通过率越好看是最容易被无意识利用的指标漏洞。"""

    skipped_count = sum(1 for r in results if r.skipped)
    denominator = len(results) - skipped_count
    passed_count = sum(1 for r in results if r.passed and not r.skipped)
    pass_rate = (passed_count / denominator) if denominator else 1.0
    return SummaryReport(
        total=len(results),
        denominator=denominator,
        passed=passed_count,
        skipped=skipped_count,
        pass_rate=pass_rate,
    )
