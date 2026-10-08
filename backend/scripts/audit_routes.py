"""路由覆盖对账：PRD §11.2 的路径清单 × FastAPI 真实路由表（N5 D Task 1）。

计划文档里的路径是缩写，文本匹配会漏报；这里直接读应用的路由表。三项检查：

1. PRD §11.2.2–§11.2.3 的每条 v2 路径都已实现（缺 0），代码里没有 PRD 之外的 v2 路径（多 0）；
2. PRD §11.2.1 的 v1 端点全部仍在（迁移期不废弃）；
3. PRD §11.2.4 移出本版的附件端点不存在。

用法（在 `backend/` 下）：`uv run python -m scripts.audit_routes`。有任何一项不满足时以非零码退出。
不连数据库、不调用 LLM。
"""

from __future__ import annotations

import re
import sys
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.routing import APIRoute

from app.core.config import Settings
from app.main import create_app

PRD = Path(__file__).resolve().parents[2] / "docs" / "PRD.md"
_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE"})
_ENTRY = re.compile(r"`(GET|POST|PUT|PATCH|DELETE) (/api/[^`\s]+)`")
_CONVERTER = re.compile(r":[a-z]+\}")

Route = tuple[str, str]

#: 不进 OpenAPI 的 v2 路由只允许这一条：MCP 入口对 GET 的显式 405（契约 §8.14.3）。
#: 它不是一条能力路径，但确实挂在路由表里；这里点名放行，其他隐藏路由一律算「多」。
HIDDEN_V2_ALLOWED: frozenset[Route] = frozenset({("GET", "/api/v2/merchant/mcp")})


@dataclass(frozen=True)
class RouteAudit:
    expected_v2: frozenset[Route]
    actual_v2: frozenset[Route]
    expected_v1: frozenset[Route]
    actual_other: frozenset[Route]
    removed: frozenset[Route]
    hidden_v2: frozenset[Route] = field(default_factory=frozenset)

    @property
    def missing_v2(self) -> frozenset[Route]:
        return self.expected_v2 - self.actual_v2

    @property
    def extra_v2(self) -> frozenset[Route]:
        return (self.actual_v2 - self.expected_v2) | (self.hidden_v2 - HIDDEN_V2_ALLOWED)

    @property
    def missing_v1(self) -> frozenset[Route]:
        return self.expected_v1 - self.actual_other

    @property
    def removed_still_present(self) -> frozenset[Route]:
        return self.removed & (self.actual_other | self.actual_v2)

    @property
    def clean(self) -> bool:
        return not (
            self.missing_v2 or self.extra_v2 or self.missing_v1 or self.removed_still_present
        )


def _section(prd: str, start: str, end: str) -> str:
    if prd.count(start) != 1 or prd.count(end) != 1:
        raise ValueError(f"PRD 小节标题不唯一或不存在：{start} / {end}")
    return prd.split(start)[1].split(end)[0]


def prd_routes(prd: str) -> tuple[frozenset[Route], frozenset[Route], frozenset[Route]]:
    """返回（v1 端点，v2 路径，移出本版的端点）；标题不存在时报错，而不是当成空清单通过。"""

    v1 = frozenset(_ENTRY.findall(_section(prd, "#### 11.2.1", "#### 11.2.2")))
    v2 = frozenset(_ENTRY.findall(_section(prd, "#### 11.2.2", "#### 11.2.4")))
    removed = frozenset(_ENTRY.findall(_section(prd, "#### 11.2.4", "### 11.3")))
    if not v1 or not v2 or not removed:
        raise ValueError("PRD §11.2 的路径清单解析为空，对账没有意义")
    return v1, v2, removed


def audit_settings() -> Settings:
    """与 OpenAPI 导出同一份固定配置：管理端路由按 ADMIN_TOKEN 条件挂载，必须带上。"""

    return Settings(
        _env_file=None,
        app_env="test",
        database_url="postgresql+psycopg://user:pass@localhost/test",
        frontend_origin="http://localhost:5173",
        admin_token="route-audit-admin-token",
    )


def served_routes(app: FastAPI) -> Iterator[tuple[str, str, bool]]:
    """应用实际挂载的每条（方法，完整路径，是否进 OpenAPI）。

    读的是路由表而不是 `app.openapi()`：隐藏路由（`include_in_schema=False`）不进 OpenAPI，
    而「代码里有没有 PRD 之外的路径」恰恰要把它们也算上。当前 FastAPI 把 `include_router`
    的子路由放在惰性结构里，顶层 `app.routes` 读不到有效路径，要经
    `effective_route_contexts()` 展开；
    直接挂在应用上的路由仍是 `APIRoute`。两种都认，结构再变时宁可报错也不当成空路由表通过。
    """

    seen = 0
    for route in app.routes:
        if isinstance(route, APIRoute):
            entries: Iterable[Any] = (route,)
        elif hasattr(route, "effective_route_contexts"):
            entries = route.effective_route_contexts()
        else:
            continue  # 文档页、静态挂载等非 API 路由
        for entry in entries:
            # `{document_path:path}` 这类转换器后缀只影响匹配方式，PRD 写的是 `{document_path}`。
            path = _CONVERTER.sub("}", entry.path)
            for method in set(entry.methods) & _METHODS:
                seen += 1
                yield method, path, bool(entry.include_in_schema)
    if seen == 0:
        raise RuntimeError("没有从应用路由表读到任何 API 路由，对账没有意义")


def audit(app: FastAPI, prd: str) -> RouteAudit:
    expected_v1, expected_v2, removed = prd_routes(prd)
    v2: set[Route] = set()
    hidden: set[Route] = set()
    other: set[Route] = set()
    for method, path, in_schema in served_routes(app):
        entry = (method, path)
        if not path.startswith("/api/v2/"):
            other.add(entry)
        elif in_schema:
            v2.add(entry)
        else:
            hidden.add(entry)
    return RouteAudit(
        expected_v2=expected_v2,
        actual_v2=frozenset(v2),
        expected_v1=expected_v1,
        actual_other=frozenset(other),
        removed=removed,
        hidden_v2=frozenset(hidden),
    )


def render(result: RouteAudit) -> str:
    lines = [
        f"v2：PRD {len(result.expected_v2)} 条；已实现 "
        f"{len(result.expected_v2 & result.actual_v2)}；缺 {len(result.missing_v2)}；"
        f"多 {len(result.extra_v2)}",
        f"v1：PRD {len(result.expected_v1)} 条；缺 {len(result.missing_v1)}",
        f"移出本版的端点：{len(result.removed)} 条；仍存在 {len(result.removed_still_present)}",
    ]
    for label, routes in (
        ("缺 v2", result.missing_v2),
        ("多 v2", result.extra_v2),
        ("缺 v1", result.missing_v1),
        ("不应存在", result.removed_still_present),
    ):
        lines.extend(f"  {label} {method} {path}" for method, path in sorted(routes))
    return "\n".join(lines)


def main() -> None:
    result = audit(create_app(audit_settings()), PRD.read_text(encoding="utf-8"))
    print(render(result))
    sys.exit(0 if result.clean else 1)


if __name__ == "__main__":
    main()
