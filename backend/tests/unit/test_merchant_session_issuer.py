"""签发 issuer 必须与鉴权解析的 Bearer token 保持一致。"""

import pytest
from starlette.requests import Request

from app.api.routes.v2.merchant_sessions import _raw_bearer_token


@pytest.mark.parametrize("scheme", ["Bearer", "bearer", "BEARER", "bEaReR"])
def test_bearer_issuer_is_case_insensitive(scheme: str) -> None:
    request = Request(
        {"type": "http", "headers": [(b"authorization", f"{scheme} demo-token".encode())]}
    )
    assert _raw_bearer_token(request) == "demo-token"
