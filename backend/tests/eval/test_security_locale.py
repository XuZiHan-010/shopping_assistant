"""安全评测必须真正执行声明的语言，包括前置 turn。"""

import json
from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from fastapi import Request, Response
from pydantic import ValidationError

from app.core.config import AppEnvironment, Settings
from app.core.errors import AppError, ErrorCode
from app.db.session import Database
from app.eval.cases import EvalCase
from app.eval.security_harness import SecurityHarness
from app.main import create_app


def locale_case(locale: str, headers: dict[str, str] | None = None) -> EvalCase:
    return EvalCase.model_validate(
        {
            "id": "SEC-LOCALE-TEST",
            "role": "CUSTOMER",
            "skill": "session",
            "risk": "SECURITY",
            "locale": locale,
            "turns": [
                {
                    "actor": "anonymous",
                    "request": {
                        "method": "GET",
                        "path": "/probe",
                        "headers": headers or {},
                    },
                }
                for _ in range(2)
            ],
            "assertions": [{"type": "http_status", "expected": 403}],
        }
    )


@pytest.mark.parametrize("locale", ["zh-CN", "en-US"])
async def test_case_locale_reaches_every_http_turn(
    locale: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(
        app_env=AppEnvironment.TEST,
        llm_api_key=None,
        database_url="postgresql+psycopg://test@127.0.0.1:1/test",
        frontend_origin="http://localhost:5173",
    )
    database = Database(settings)
    app = create_app(settings, database=database)
    seen: list[str | None] = []
    messages: list[str] = []

    @app.middleware("http")
    async def capture_response(
        request: Request, call_next: Callable[[Request], Awaitable[Any]]
    ) -> Response:
        response = await call_next(request)
        body = b"".join([chunk async for chunk in response.body_iterator])
        messages.append(json.loads(body)["message"])
        return Response(body, status_code=response.status_code, headers=dict(response.headers))

    @app.get("/probe", status_code=403)
    async def probe(request: Request) -> dict[str, str]:
        seen.append(request.headers.get("accept-language"))
        raise AppError(code=ErrorCode.SESSION_ROLE_MISMATCH, message="内部说明", status_code=403)

    harness = SecurityHarness(app, database, merchants={})

    async def no_audits(_request_id: str) -> list[dict[str, Any]]:
        return []

    monkeypatch.setattr(harness, "_audit_events", no_audits)
    try:
        result = await harness.run(locale_case(locale))
        assert result.passed, result.failure_detail
        # 结果带上被断言的那次请求的追踪 ID，报告条目据此可回查审计与用量行（PRD §10.4）。
        assert result.request_id.startswith("eval-") and result.request_id.endswith("-t1")
        assert seen == [locale, locale]
        expected = {
            "zh-CN": "当前会话无权执行此操作",
            "en-US": "This session is not permitted to perform this operation.",
        }[locale]
        assert messages == [expected, expected]
    finally:
        await database.dispose()


@pytest.mark.parametrize("header", ["Accept-Language", "accept-language", "ACCEPT-LANGUAGE"])
def test_conflicting_explicit_language_is_rejected(header: str) -> None:
    with pytest.raises(ValidationError, match="locale"):
        locale_case("en-US", {header: "zh-CN"})


def test_matching_language_header_is_allowed() -> None:
    assert locale_case("en-US", {"accept-language": "en-US"}).locale == "en-US"


def test_case_insensitive_duplicate_language_headers_are_rejected() -> None:
    with pytest.raises(ValidationError, match="locale"):
        locale_case("en-US", {"accept-language": "en-US", "Accept-Language": "en-US"})
