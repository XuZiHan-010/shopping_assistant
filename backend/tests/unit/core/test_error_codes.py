"""错误码契约哨兵。

后端发出的每个错误码都必须登记在 `docs/backend-development-plan.md` §14，
前端才能按码查表渲染（`docs/frontend-development-plan.md` §10）。
这两处曾经漂移过：实现用了 NOT_FOUND / METHOD_NOT_ALLOWED / HTTP_ERROR，
文档里一个都没有。这个测试就是为了让同类漂移在 CI 里立刻暴露。
"""

import re
from pathlib import Path

import pytest

from app.core.errors import AppError, ErrorCode

BACKEND_PLAN = Path(__file__).resolve().parents[3].parent / "docs" / "backend-development-plan.md"


def documented_error_codes() -> set[str]:
    """抽出计划 §14 代码块里登记的错误码。"""

    text = BACKEND_PLAN.read_text(encoding="utf-8")
    section = re.search(
        r"^## 14\. 后端错误码\s*$(.*?)^## 15\.",
        text,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert section is not None, "未找到 §14 后端错误码章节，文档结构可能变了"
    return set(re.findall(r"^([A-Z][A-Z_]{3,})$", section.group(1), flags=re.MULTILINE))


def test_every_emitted_code_is_documented() -> None:
    """枚举里的码必须在 §14 有登记。"""

    undocumented = {code.value for code in ErrorCode} - documented_error_codes()

    assert not undocumented, (
        f"以下错误码已在代码中使用但未登记到 §14：{sorted(undocumented)}。"
        "请更新 docs/backend-development-plan.md，并检查前端 §10 是否需要补展示规则。"
    )


def test_app_error_subclasses_use_the_enum() -> None:
    """禁止绕过枚举直写字符串码。"""

    def subclasses(cls: type[AppError]) -> list[type[AppError]]:
        found: list[type[AppError]] = []
        for sub in cls.__subclasses__():
            found.append(sub)
            found.extend(subclasses(sub))
        return found

    checked = 0
    for subclass in subclasses(AppError):
        try:
            error = subclass()  # type: ignore[call-arg]
        except TypeError:
            # 需要构造参数的子类跳过，由各自的用例覆盖。
            continue
        checked += 1
        assert isinstance(error.code, ErrorCode), (
            f"{subclass.__name__} 的 code 不是 ErrorCode 成员，"
            "错误码必须集中在 app.core.errors.ErrorCode 中定义"
        )

    assert checked > 0, "没有检查到任何 AppError 子类，测试自身可能已失效"


@pytest.mark.parametrize("code", list(ErrorCode))
def test_enum_value_matches_member_name(code: ErrorCode) -> None:
    """成员名与字面值保持一致，避免出现 name/value 不一致的隐形错码。"""

    assert code.value == code.name
