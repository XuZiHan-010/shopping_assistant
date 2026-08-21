"""OpenAPI 契约哨兵。

前端类型从这份 OpenAPI 生成（`docs/frontend-development-plan.md` F0），所以 B2
的路径和 ChatResponse 字段一旦漂移，必须在这里立刻失败，而不是等前端编译报错。
"""

import json
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI

from app.main import create_app

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.export_openapi import (  # noqa: E402
    export_settings,
    render_openapi_json,
    render_openapi_markdown,
)

DOCS = REPO_ROOT / "docs"

# FastAPI 用形参名生成路径模板，所以是 {conversation_id} 而不是计划正文里的 {id}。
CONVERSATION_ITEM_PATH = "/api/conversations/{conversation_id}"


@pytest.fixture
def app() -> FastAPI:
    return create_app(export_settings())


def test_exported_docs_are_in_sync_with_the_application(app: FastAPI) -> None:
    """导出产物漂移哨兵。

    前端从 `docs/api.json` 生成类型，改了 Schema 却忘记重新导出，前端会拿着旧
    契约一路写下去直到接真实 API 才集中报错。这里让漂移立刻失败。
    """

    schema = app.openapi()
    stale = (
        "Schema 已变更但导出产物未更新，"
        "请在 backend/ 运行 uv run python ../scripts/export_openapi.py"
    )

    assert (DOCS / "api.json").read_text(encoding="utf-8") == render_openapi_json(schema), stale
    assert (DOCS / "api.md").read_text(encoding="utf-8") == render_openapi_markdown(schema), stale


def test_exported_json_is_machine_readable_without_unwrapping(app: FastAPI) -> None:
    """openapi-typescript 直接吃这个文件，不能包在 markdown 代码块里。"""

    raw = (DOCS / "api.json").read_text(encoding="utf-8")

    assert not raw.lstrip().startswith("#")
    assert "```" not in raw
    assert json.loads(raw)["openapi"].startswith("3.")


# 逐条对照 docs/backend-development-plan.md §8.0 的路由表「主要错误码」列。
# 这里硬编码而不是解析 Markdown 表格：表格解析一旦失配，失败信息会指向解析器
# 而不是漏声明的路由，反而更难查。改动 §8.0 时必须同步这里。
EXPECTED_ERROR_CODES: dict[tuple[str, str], set[str]] = {
    ("post", "/api/chat"): {"401", "403", "409", "422"},
    ("get", "/api/conversations"): {"401", "422"},
    ("get", CONVERSATION_ITEM_PATH): {"401", "403", "404", "422"},
    ("delete", CONVERSATION_ITEM_PATH): {"401", "403", "404", "422"},
    ("get", "/api/demo/merchants"): {"404"},
    ("get", "/api/metrics/{code}"): {"401", "404", "422"},
    ("get", "/api/ready"): {"503"},
    ("post", "/api/answers/{answer_id}/feedback"): {"401", "403", "404", "422"},
    ("get", "/api/exports/{export_id}"): {"403", "404", "410"},
}


def test_error_response_schema_is_exposed_to_the_frontend(app: FastAPI) -> None:
    """前端 §10 按 code 分支渲染错误，没有这个 schema 就只能手写类型。"""

    schemas = app.openapi()["components"]["schemas"]

    assert "ErrorResponse" in schemas
    assert set(schemas["ErrorResponse"]["properties"]) >= {
        "code",
        "message",
        "request_id",
        "details",
        "retryable",
    }
    assert "ErrorCode" in schemas


def test_every_route_declares_the_error_codes_it_can_emit(app: FastAPI) -> None:
    paths = app.openapi()["paths"]

    for (method, path), expected in EXPECTED_ERROR_CODES.items():
        declared = set(paths[path][method]["responses"])
        missing = expected - declared
        assert not missing, f"{method.upper()} {path} 未声明错误码 {sorted(missing)}（见 §8.0）"


def test_error_responses_reference_the_shared_error_schema(app: FastAPI) -> None:
    """声明了错误码还不够，body 必须指向 ErrorResponse 而不是别的形状。"""

    paths = app.openapi()["paths"]

    for (method, path), expected in EXPECTED_ERROR_CODES.items():
        for code in expected:
            content = paths[path][method]["responses"][code]["content"]
            schema = content["application/json"]["schema"]
            assert schema == {"$ref": "#/components/schemas/ErrorResponse"}, (
                f"{method.upper()} {path} 的 {code} 响应体不是 ErrorResponse"
            )


def test_fastapi_default_validation_shape_is_fully_replaced(app: FastAPI) -> None:
    """实际返回的 422 是 ErrorResponse；契约里不能再留 FastAPI 的默认形状。"""

    document = json.dumps(app.openapi())

    assert "HTTPValidationError" not in document
    assert "ValidationError" not in document


def test_chat_declares_both_transports(app: FastAPI) -> None:
    """SSE 是默认路径，只声明 JSON 会让前端看不出这个端点是流式的。"""

    content = app.openapi()["paths"]["/api/chat"]["post"]["responses"]["200"]["content"]

    assert set(content) == {"application/json", "text/event-stream"}
    assert content["application/json"]["schema"] == {"$ref": "#/components/schemas/ChatResponse"}


def test_openapi_exposes_b2_chat_and_conversation_contract(app: FastAPI) -> None:
    schema = app.openapi()

    assert set(schema["paths"]) >= {
        "/api/chat",
        "/api/conversations",
        CONVERSATION_ITEM_PATH,
    }
    assert set(schema["paths"]["/api/chat"]) == {"post"}
    assert set(schema["paths"][CONVERSATION_ITEM_PATH]) == {"get", "delete"}
    assert "204" in schema["paths"][CONVERSATION_ITEM_PATH]["delete"]["responses"]


def test_chat_response_uses_session_id_and_never_conversation_id(app: FastAPI) -> None:
    properties = app.openapi()["components"]["schemas"]["ChatResponse"]["properties"]

    assert "session_id" in properties
    assert "conversation_id" not in properties


def test_chat_response_declares_every_always_present_field(app: FastAPI) -> None:
    """§8.2 的「始终必填」清单：键必须存在，值可以为 null。"""

    schema = app.openapi()["components"]["schemas"]["ChatResponse"]

    assert set(schema["required"]) >= {
        "id",
        "session_id",
        "answer",
        "answer_mode",
        "category",
        "quality_status",
        "quality_attempts",
        "analysis_sources",
        "degraded",
        "degraded_reason",
    }
    assert set(schema["properties"]) >= {
        "thinking_steps",
        "quality_notes",
        "suggestions",
        "suggestion_alternates",
        "created_at",
    }


def test_openapi_exposes_admin_knowledge_routes_but_not_unimplemented_merchant_routes(
    app: FastAPI,
) -> None:
    paths = set(app.openapi()["paths"])

    assert not {path for path in paths if path.startswith("/api/attachments")}
    # R9 已裁定撤回商家自助记忆 API；这是永久契约，不是暂未实现的临时守卫。
    assert not {path for path in paths if path.startswith("/api/memories")}
    assert "/api/admin/knowledge/tree" in paths
    assert "/api/admin/knowledge/documents/{document_path}" in paths
    assert "/api/admin/knowledge/business-domains" in paths


def test_b6_feedback_and_export_routes_are_exposed(app: FastAPI) -> None:
    """B6 上线后这两条路由必须存在；FastAPI 用形参名生成路径模板，是
    `{export_id}`/`{answer_id}` 而不是计划正文里的 `{id}`（同 `CONVERSATION_ITEM_PATH`）。
    """

    paths = app.openapi()["paths"]

    assert "post" in paths["/api/answers/{answer_id}/feedback"]
    assert "get" in paths["/api/exports/{export_id}"]


def test_enums_match_the_documented_values(app: FastAPI) -> None:
    schemas = app.openapi()["components"]["schemas"]

    assert schemas["AnswerMode"]["enum"] == [
        "METRIC",
        "DETAIL",
        "RULE",
        "IDENTITY",
        "CHAT",
        "INVALID",
        "ATTACHMENT",
    ]
    assert schemas["QualityStatus"]["enum"] == ["PASSED", "DEGRADED", "FAILED", "NOT_RUN"]
    assert schemas["AnalysisSource"]["enum"] == [
        "DATABASE",
        "KNOWLEDGE",
        "ATTACHMENT",
        "MEMORY",
        "FALLBACK",
        "NONE",
    ]
    # §8.2 明确写了 QualityStatus 没有 RETRIED，重试次数由 quality_attempts 表达。
    assert "RETRIED" not in schemas["QualityStatus"]["enum"]
