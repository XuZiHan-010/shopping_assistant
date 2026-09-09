"""稳定错误码到双语用户提示的唯一映射。

`AppError` 及内建异常处理器只携带稳定 `code` 与受控 `message_params`；
对外展示的 `message` 一律由这里根据请求 `SupportedLocale` 渲染，禁止在
处理器里为英语请求直接复用中文原句，也禁止把框架原始异常文案透传给
调用方（`docs/backend-development-plan.md` §8.6.1）。

本模块只依赖 `app.localization.locales`，不导入 `app.core.errors`——两个
模块相互 import 会成环。调用方可以直接传 `ErrorCode` 成员当 `code`：
`StrEnum` 成员的哈希与相等性都退化到其字符串值，字典按值查找与传等价
字符串完全一致。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.localization.locales import SupportedLocale

_ZH = SupportedLocale.ZH_CN
_EN = SupportedLocale.EN_US

# 每个 `ErrorCode` 成员的通用双语文案。同一个码可能被多处业务复用
# （例如知识库维护后台里 WIKI_NODE_EXISTS 同时表示"文档已存在"和"业务域
# 已存在"），这里保留跨场景都成立的通用措辞；需要按具体资源细化措辞的码
# （AUTH_REQUIRED / NOT_FOUND）改走下面的 `message_params` 占位符。
_MESSAGES: dict[str, dict[SupportedLocale, str]] = {
    "AUTH_REQUIRED": {
        _ZH: "请提供有效的{audience}访问凭证",
        _EN: "Please provide a valid {audience} access token.",
    },
    "MERCHANT_SCOPE_VIOLATION": {
        _ZH: "无权访问该商家资源",
        _EN: "You do not have permission to access this merchant's resources.",
    },
    "NOT_FOUND": {
        _ZH: "{resource_name}不存在",
        _EN: "{resource_name} was not found.",
    },
    "METHOD_NOT_ALLOWED": {
        _ZH: "请求方法不被允许",
        _EN: "This HTTP method is not allowed for this endpoint.",
    },
    "INVALID_REQUEST": {
        _ZH: "请求参数不合法",
        _EN: "The request parameters are invalid.",
    },
    "IDEMPOTENCY_KEY_REUSED": {
        _ZH: "该请求标识已用于不同内容，请生成新的请求标识",
        _EN: (
            "This request id was already used for different content. "
            "Please generate a new request id."
        ),
    },
    "REQUEST_IN_PROGRESS": {
        _ZH: "该请求正在处理中，请稍后重试",
        _EN: "This request is still being processed. Please try again later.",
    },
    "DAILY_REPORT_FEEDBACK_CONFLICT": {
        _ZH: "该日报已有商家反馈，不能重算替换",
        _EN: "This daily report already has merchant feedback and cannot be recomputed.",
    },
    "DATA_SOURCE_UNAVAILABLE": {
        _ZH: "数据服务暂时不可用，请稍后重试",
        _EN: "The data service is temporarily unavailable. Please try again later.",
    },
    "EXPORT_LINK_EXPIRED": {
        _ZH: "导出链接已过期，请重新发起查询后下载",
        _EN: "This export link has expired. Please re-run the query and download again.",
    },
    "RATE_LIMITED": {
        _ZH: "请求过于频繁，请稍后重试",
        _EN: "Too many requests. Please try again later.",
    },
    "LLM_BUDGET_EXCEEDED": {
        _ZH: "今日模型用量已达上限，请稍后重试",
        _EN: "Today's model usage limit has been reached. Please try again later.",
    },
    "FORBIDDEN": {
        _ZH: "无权执行该操作",
        _EN: "You do not have permission to perform this action.",
    },
    "HTTP_ERROR": {
        _ZH: "请求处理失败",
        _EN: "The request could not be processed.",
    },
    "INTERNAL_ERROR": {
        _ZH: "服务暂时不可用，请稍后重试",
        _EN: "The service is temporarily unavailable. Please try again later.",
    },
    "INVALID_WIKI_PATH": {
        _ZH: "知识库路径不合法",
        _EN: "This knowledge base path is invalid.",
    },
    "WIKI_READ_ONLY": {
        _ZH: "该知识库节点为只读",
        _EN: "This knowledge base node is read-only.",
    },
    "INVALID_FILE_TYPE": {
        _ZH: "只允许读取 Markdown 文档",
        _EN: "Only Markdown documents are supported.",
    },
    "INVALID_WIKI_PARENT": {
        _ZH: "上级目录不合法",
        _EN: "The parent directory is invalid.",
    },
    "WIKI_NODE_EXISTS": {
        _ZH: "同名节点已存在",
        _EN: "A node with this name already exists.",
    },
    "WIKI_NODE_NOT_FOUND": {
        _ZH: "知识库节点不存在",
        _EN: "This knowledge base node was not found.",
    },
    "WIKI_DIRECTORY_NOT_EMPTY": {
        _ZH: "目录非空，无法删除",
        _EN: "This directory is not empty and cannot be deleted.",
    },
    "WIKI_VERSION_REQUIRED": {
        _ZH: "缺少 If-Match 版本",
        _EN: "An If-Match version header is required.",
    },
    "WIKI_VERSION_CONFLICT": {
        _ZH: "版本已被其他维护者更新，请刷新后重试",
        _EN: "This version has been updated by another maintainer. Please refresh and try again.",
    },
    "WIKI_DOCUMENT_TOO_LARGE": {
        _ZH: "文档超过大小限制",
        _EN: "This document exceeds the size limit.",
    },
    "INVALID_WIKI_ENCODING": {
        _ZH: "文档编码不受支持",
        _EN: "This document encoding is not supported.",
    },
    "INVALID_WIKI_CONTENT": {
        _ZH: "文档内容不合法",
        _EN: "This document content is invalid.",
    },
    "WIKI_IO_ERROR": {
        _ZH: "知识库读写失败",
        _EN: "Knowledge base read/write failed.",
    },
}

# 未登记的码（理论上不应该出现——见 `tests/unit/core/test_error_codes.py`
# 的登记哨兵）也不能让异常处理器再抛出一个新异常，兜底成通用文案。
_FALLBACK: dict[SupportedLocale, str] = {
    _ZH: "请求处理失败，请稍后重试",
    _EN: "The request could not be processed. Please try again later.",
}

_AUDIENCE_LABELS: dict[str, dict[SupportedLocale, str]] = {
    "merchant": {_ZH: "商家", _EN: "merchant"},
    "admin": {_ZH: "管理员", _EN: "administrator"},
}

# 目前代码里 `ResourceNotFoundError` 全部调用点使用的资源名（见
# `app/api/routes/reports.py`、`app/api/routes/knowledge.py`、
# `app/api/routes/metrics.py`、`app/services/chat_service.py`、
# `app/services/export_service.py`、`app/services/feedback_service.py`、
# `app/services/merchant_scope.py`）。新增资源类型时需要在这里补一行，
# 否则会命中下面的兜底默认值——兜底值本身也是双语的，不会泄漏中文。
_RESOURCE_NAME_LABELS: dict[str, dict[SupportedLocale, str]] = {
    "商家": {_ZH: "商家", _EN: "merchant"},
    "指标口径": {_ZH: "指标口径", _EN: "metric definition"},
    "会话": {_ZH: "会话", _EN: "conversation"},
    "导出文件": {_ZH: "导出文件", _EN: "export file"},
    "回答": {_ZH: "回答", _EN: "answer"},
}

_DEFAULT_RESOURCE_NAME: dict[SupportedLocale, str] = {
    _ZH: "请求的资源",
    _EN: "The requested resource",
}


def _resolve_audience(raw_value: Any, locale: SupportedLocale) -> str:
    label = _AUDIENCE_LABELS.get(str(raw_value), _AUDIENCE_LABELS["merchant"])
    return label[locale]


def _resolve_resource_name(raw_value: Any, locale: SupportedLocale) -> str:
    label = _RESOURCE_NAME_LABELS.get(str(raw_value))
    if label is None:
        # 未登记的资源名：不把原始字面量（可能是中文）直接拼进目标语言
        # 句子，退回通用措辞，保证英文响应永远不会混入汉字。
        return _DEFAULT_RESOURCE_NAME[locale]
    return label[locale]


_PARAM_RESOLVERS = {
    "audience": _resolve_audience,
    "resource_name": _resolve_resource_name,
}


def localize_error_message(
    code: Any,
    params: Mapping[str, Any] | None,
    locale: SupportedLocale,
) -> str:
    """按错误码与受控参数渲染指定语言的对外提示。

    `code` 接受 `ErrorCode` 成员或等价字符串。未登记的码使用通用兜底
    文案而不是抛出异常，保证异常处理器本身不会因为遇到陌生码而产生新的
    未处理异常。
    """

    templates = _MESSAGES.get(str(code), _FALLBACK)
    template = templates[locale]

    resolved: dict[str, str] = {}
    for name, raw_value in (params or {}).items():
        resolver = _PARAM_RESOLVERS.get(name)
        resolved[name] = resolver(raw_value, locale) if resolver else str(raw_value)

    if "resource_name" not in resolved and "{resource_name}" in template:
        resolved["resource_name"] = _DEFAULT_RESOURCE_NAME[locale]
    if "audience" not in resolved and "{audience}" in template:
        resolved["audience"] = _AUDIENCE_LABELS["merchant"][locale]

    return template.format(**resolved) if resolved else template


# Pydantic 校验错误的 `type` → 双语字段级提示。只映射受控的错误类型
# 短语，不回传 `error["msg"]` 里 pydantic-core 生成的原始英文/中文长句
# （`docs/backend-development-plan.md` §8.6.1）。
_VALIDATION_TYPE_MESSAGES: dict[str, dict[SupportedLocale, str]] = {
    "missing": {_ZH: "缺少必填字段", _EN: "This field is required."},
    "uuid_parsing": {_ZH: "不是合法的 UUID", _EN: "Must be a valid UUID."},
    "int_parsing": {_ZH: "不是合法的整数", _EN: "Must be a valid integer."},
    "int_type": {_ZH: "字段类型必须是整数", _EN: "Must be an integer."},
    "float_parsing": {_ZH: "不是合法的数字", _EN: "Must be a valid number."},
    "string_type": {_ZH: "字段类型必须是字符串", _EN: "Must be a string."},
    "string_too_short": {_ZH: "字段长度过短", _EN: "This value is too short."},
    "string_too_long": {_ZH: "字段长度过长", _EN: "This value is too long."},
    "value_error": {_ZH: "字段取值不合法", _EN: "This value is invalid."},
    "greater_than_equal": {_ZH: "取值过小", _EN: "This value is too small."},
    "less_than_equal": {_ZH: "取值过大", _EN: "This value is too large."},
    "greater_than": {_ZH: "取值过小", _EN: "This value is too small."},
    "less_than": {_ZH: "取值过大", _EN: "This value is too large."},
    "enum": {_ZH: "取值不在允许范围内", _EN: "This value is not one of the allowed options."},
    "json_invalid": {_ZH: "请求体不是合法 JSON", _EN: "Request body is not valid JSON."},
    "bool_parsing": {_ZH: "不是合法的布尔值", _EN: "Must be a valid boolean."},
}

_VALIDATION_TYPE_FALLBACK: dict[SupportedLocale, str] = {
    _ZH: "字段校验失败",
    _EN: "Field validation failed.",
}


def localize_validation_detail_message(error_type: str, locale: SupportedLocale) -> str:
    """按 Pydantic 校验错误类型渲染字段级提示。"""

    table = _VALIDATION_TYPE_MESSAGES.get(error_type, _VALIDATION_TYPE_FALLBACK)
    return table[locale]
