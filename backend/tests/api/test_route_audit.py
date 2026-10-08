"""路由覆盖对账（N5 D Task 1）：PRD §11.2 × 应用真实路由表，缺 0、多 0。

对账脚本本身也要能报出问题，所以另有三条反例：缺一条、多一条、隐藏路由。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI

from app.main import create_app

# 按文件路径加载：全量收集时 `scripts` 这个包名会被仓库根目录的同名目录遮蔽。
_path = Path(__file__).resolve().parents[2] / "scripts" / "audit_routes.py"
_spec = importlib.util.spec_from_file_location("borough_audit_routes_for_test", _path)
assert _spec is not None and _spec.loader is not None
_audit_module = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _audit_module  # dataclass 解析注解时要能按模块名找到它
_spec.loader.exec_module(_audit_module)

PRD = _audit_module.PRD
audit = _audit_module.audit
audit_settings = _audit_module.audit_settings
prd_routes = _audit_module.prd_routes
render = _audit_module.render


@pytest.fixture(scope="module")
def app() -> FastAPI:
    return create_app(audit_settings())


@pytest.fixture(scope="module")
def prd() -> str:
    return PRD.read_text(encoding="utf-8")


def test_every_prd_v2_path_is_implemented_and_nothing_else(app: FastAPI, prd: str) -> None:
    result = audit(app, prd)

    assert result.missing_v2 == frozenset(), render(result)
    assert result.extra_v2 == frozenset(), render(result)
    assert len(result.expected_v2) >= 53


def test_v1_endpoints_are_all_still_served(app: FastAPI, prd: str) -> None:
    # PRD §11.1：迁移期不废弃 v1 端点。
    result = audit(app, prd)

    assert result.missing_v1 == frozenset(), render(result)
    assert ("POST", "/api/chat") in result.expected_v1


def test_removed_attachment_endpoints_do_not_exist(app: FastAPI, prd: str) -> None:
    result = audit(app, prd)

    assert {path for _, path in result.removed} == {
        "/api/attachments",
        "/api/attachments/{attachment_id}",
    }
    assert result.removed_still_present == frozenset()
    assert result.clean


def test_audit_reports_a_missing_and_an_extra_path(app: FastAPI, prd: str) -> None:
    """PRD 多写一条 → 报缺；PRD 少写一条 → 报多。"""

    coupons = "| `GET /api/v2/merchant/coupons` |"
    assert prd.count(coupons) == 1
    doctored = prd.replace(coupons, "| `GET /api/v2/merchant/not-implemented` |")

    result = audit(app, doctored)

    assert result.missing_v2 == frozenset({("GET", "/api/v2/merchant/not-implemented")})
    assert result.extra_v2 == frozenset({("GET", "/api/v2/merchant/coupons")})
    assert not result.clean
    assert "缺 v2 GET /api/v2/merchant/not-implemented" in render(result)


def test_a_dropped_v1_endpoint_is_reported(app: FastAPI, prd: str) -> None:
    health = "| `GET /api/health` |"
    assert prd.count(health) == 1

    result = audit(app, prd.replace(health, "| `GET /api/health-gone` |"))

    assert result.missing_v1 == frozenset({("GET", "/api/health-gone")})
    assert not result.clean


def test_hidden_v2_routes_count_as_extra_unless_allowlisted(prd: str) -> None:
    app = create_app(audit_settings())

    @app.post("/api/v2/merchant/mcp/credentials", include_in_schema=False)
    async def hidden() -> dict[str, str]:
        return {}

    result = audit(app, prd)

    assert ("POST", "/api/v2/merchant/mcp/credentials") in result.extra_v2
    # MCP 入口对 GET 的显式 405 是点名放行的唯一隐藏路由。
    assert ("GET", "/api/v2/merchant/mcp") not in result.extra_v2


def test_missing_prd_section_is_an_error_not_an_empty_pass() -> None:
    with pytest.raises(ValueError, match="小节标题"):
        prd_routes("# 没有路径清单的文档")
