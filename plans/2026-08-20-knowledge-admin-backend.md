# 知识库维护后台（B9 + F8）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 1:1 复刻参考项目的 `WikiAdminService`（498 行）与 `WikiPathPolicy`（167 行），在 PostgreSQL 上提供团队知识库的目录树、文档 CRUD、业务域管理与乐观锁，并把 `KnowledgeBaseView.vue` 从占位页填成可用后台。

**Architecture:** `source_path` 字符串承载参考项目的虚拟目录层级（`index/*.md` 两段、`业务/{域}/{板块}/*.md` 四段、`memory/**` 只读）。路径策略把参考实现除符号链接外的全部校验搬到虚拟路径上；版本号沿用 SHA-256，目录版本由子节点摘要拼接后再摘要。管理员凭 `X-Admin-Token` 进入（不复用 `Authorization`）。记忆库在树中只读展示，任何写入路径直接 403。

**Tech Stack:** Python 3.12、FastAPI、SQLAlchemy 2 Async、Pydantic v2、pytest；Vue 3 + TypeScript + Vite、Pinia、Vitest

**Spec:** [docs/specs/2026-08-20-memory-and-knowledge-base-design.md](../docs/specs/2026-08-20-memory-and-knowledge-base-design.md)

## Global Constraints

- **R1**：面向用户的文案、注释、日志说明用中文；代码标识符用英文。
- **R2**：未经用户明确许可不得执行 `git commit` / `push` / `tag` / `gh pr create` / `gh pr merge`。**每个 Task 末尾的 commit 步骤须先取得用户许可**。
- **R3**：本计划**不含**任何真实模型调用。
- **R5**：团队知识对所有商家一致，不含商家数据；商家记忆按 `merchant_id` 隔离，后台只读且**不得跨商家展示**。
- **R8**：`yshopping-merchant-ai 4/` 整体只读。
- **R9**：参考项目是需求基准；本计划新增的三个业务域端点须同步补进 `AGENTS.md` §10.2 与 `docs/PRD.md` §11。
- **R10**：文档只写进 `plans/` 与 `docs/specs/`。
- **鉴权**：`/api/admin/*` **只认 `X-Admin-Token`**，绝不复用 `Authorization`（AGENTS.md §10.2.1）。`require_admin_token` 已存在于 `backend/app/api/dependencies.py:114`，直接复用，不新写。
- **未配置管理员令牌时整体不挂载路由**，与既有 `/api/admin/ops/status` 的处理一致（见 `backend/app/api/routes/admin.py`）。
- **前端安全**：管理员令牌**不得进入 URL、`localStorage` 或构建产物**，只存内存或 `sessionStorage`。`npm run check-no-secrets` 必须保持绿。
- **固定板块**：`BUSINESS_SECTIONS = ("业务流程", "业务名词解释", "ddl", "指标或调用指标平台mcp的skill")`，**顺序即展示顺序**，逐字对应参考实现。
- **保留字**：业务域名不得为 `index` / `memory` / `业务`，不得以 `.md` 结尾。
- **前置**：`plans/2026-08-20-memory-consolidation-agent.md` 必须先完成——本计划的 memory 只读分区需要 `merchant_memories` 表存在且有数据才能验收。

## 每个 Task 结束必跑的门禁

```powershell
cd backend
uv run pytest ; uv run ruff check . ; uv run ruff format --check . ; uv run mypy app

cd ../frontend
npm.cmd run typecheck ; npm.cmd run lint ; npm.cmd run format:check ; npm.cmd run codegen:check ; npm.cmd run fixtures:check ; npx.cmd vitest run
```

> PowerShell 5 不支持 `&&`，用 `;` 分开；`npm.ps1` 被安全策略拦截，一律用 `npm.cmd` / `npx.cmd`。

---

## File Structure

| 文件 | 职责 |
| --- | --- |
| `backend/app/knowledge/path_policy.py` | 虚拟路径校验与层级规则（复刻 `WikiPathPolicy`） |
| `backend/app/knowledge/versioning.py` | SHA-256 版本号与目录聚合版本 |
| `backend/app/repositories/knowledge_admin.py` | 后台专用读写，与检索用的 `KnowledgeRepository` 分开 |
| `backend/app/services/knowledge_admin_service.py` | 树装配、CRUD 编排、冲突判定 |
| `backend/app/schemas/knowledge.py` | 树节点、文档、业务域的 API 契约 |
| `backend/app/api/routes/knowledge.py` | `/api/admin/knowledge/*` 路由 |
| `backend/app/core/errors.py` | 追加 14 个知识库错误码 |
| `frontend/src/api/knowledge.ts` | 后台接口客户端（`X-Admin-Token` 装配点） |
| `frontend/src/stores/knowledge.ts` | 目录树、当前文档、令牌与冲突状态 |
| `frontend/src/views/KnowledgeBaseView.vue` | 后台页面（填实占位页，不新建文件、不改路由） |
| `frontend/src/components/knowledge/AdminTokenDialog.vue` | 临时授权对话框 |
| `frontend/src/components/knowledge/KnowledgeTree.vue` | 目录树 |
| `frontend/src/components/knowledge/DocumentEditor.vue` | Markdown 编辑器与冲突提示 |

---

## Task 1: 虚拟路径策略

**Files:**
- Create: `backend/app/knowledge/path_policy.py`
- Test: `backend/tests/unit/knowledge/test_path_policy.py`

**Interfaces:**
- Produces:
  - `BUSINESS_SECTIONS: tuple[str, ...]`、`RESERVED_DOMAIN_NAMES: frozenset[str]`
  - `KnowledgePathError(code: str, message: str, path: str, status_code: int)`
  - `normalize_virtual_path(raw: str) -> str`
  - `resolve_readable(raw: str) -> ResolvedPath`
  - `resolve_writable_document(raw: str) -> ResolvedPath`
  - `validate_domain_name(raw: str) -> str`
  - `ResolvedPath` dataclass：`virtual_path: str`、`read_only: bool`

- [x] **Step 1: 写失败测试**

创建 `backend/tests/unit/knowledge/test_path_policy.py`：

```python
"""虚拟路径策略，逐条对应参考实现 WikiPathPolicy。

参考实现在真实文件系统上校验，我们在 source_path 字符串上校验。
除符号链接（数据库中不存在）外的每一条规则都必须保留——它们防的是
逻辑越权，与存储介质无关。
"""

from __future__ import annotations

import pytest

from app.knowledge.path_policy import (
    BUSINESS_SECTIONS,
    KnowledgePathError,
    normalize_virtual_path,
    resolve_readable,
    resolve_writable_document,
    validate_domain_name,
)


def test_business_sections_match_reference_verbatim_and_in_order() -> None:
    assert BUSINESS_SECTIONS == (
        "业务流程",
        "业务名词解释",
        "ddl",
        "指标或调用指标平台mcp的skill",
    )


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "/index/a.md",
        "index\\a.md",
        "../secret.md",
        "index/../../etc/passwd",
        "index/./a.md",
        "index/.hidden.md",
        "index/a\x00.md",
        "index/a\nb.md",
        "index/a:b.md",
        'index/a"b.md',
        "index/a|b.md",
        "index/ a.md",
        "x" * 513,
    ],
)
def test_malformed_paths_are_rejected(raw: str) -> None:
    with pytest.raises(KnowledgePathError) as excinfo:
        normalize_virtual_path(raw)
    assert excinfo.value.status_code == 400


def test_nfc_normalization_is_applied() -> None:
    # 组合字符与预组合字符必须归一到同一个路径，否则会出现两个"同名"文档
    decomposed = "index/你好́.md"
    assert normalize_virtual_path(decomposed) == normalize_virtual_path(
        __import__("unicodedata").normalize("NFC", decomposed)
    )


def test_readable_allows_index_business_and_memory() -> None:
    assert resolve_readable("index").read_only is False
    assert resolve_readable("业务/交易").read_only is False
    assert resolve_readable("memory").read_only is True
    assert resolve_readable("memory/merchants/abc/TRADE.md").read_only is True


def test_readable_rejects_paths_outside_the_three_roots() -> None:
    with pytest.raises(KnowledgePathError) as excinfo:
        resolve_readable("secrets/a.md")
    assert excinfo.value.code == "INVALID_WIKI_PATH"


def test_memory_is_never_writable() -> None:
    with pytest.raises(KnowledgePathError) as excinfo:
        resolve_writable_document("memory/merchants/abc/TRADE.md")
    assert excinfo.value.code == "WIKI_READ_ONLY"
    assert excinfo.value.status_code == 403


def test_writable_accepts_only_two_shapes() -> None:
    assert resolve_writable_document("index/目录.md").virtual_path == "index/目录.md"
    assert (
        resolve_writable_document("业务/交易/业务流程/下单.md").virtual_path
        == "业务/交易/业务流程/下单.md"
    )


@pytest.mark.parametrize(
    "raw",
    [
        "index/子目录/a.md",      # index 下不允许再分层
        "业务/交易/下单.md",        # 缺板块层
        "业务/交易/不存在板块/a.md",  # 板块不在白名单
        "业务/交易/业务流程/深层/a.md",  # 板块下不允许再分层
        "业务/交易/业务流程/a.txt",   # 非 .md
        "业务/交易/业务流程/.md",     # 文件名只有扩展名
    ],
)
def test_writable_rejects_wrong_shapes(raw: str) -> None:
    with pytest.raises(KnowledgePathError):
        resolve_writable_document(raw)


@pytest.mark.parametrize("name", ["index", "memory", "业务", "INDEX", "业务流程", "a.md"])
def test_reserved_domain_names_are_rejected(name: str) -> None:
    with pytest.raises(KnowledgePathError):
        validate_domain_name(name)


def test_valid_domain_name_is_returned_normalized() -> None:
    assert validate_domain_name("交易") == "交易"
```

- [x] **Step 2: 跑测试确认失败**

```powershell
cd backend
uv run pytest tests/unit/knowledge/test_path_policy.py -v
```

预期：`ModuleNotFoundError: No module named 'app.knowledge.path_policy'`

- [x] **Step 3: 实现路径策略**

创建 `backend/app/knowledge/path_policy.py`：

```python
"""知识库虚拟路径策略。

逐条复刻参考实现 ``WikiPathPolicy``。唯一不实现的是 ``ensureNoSymbolicLinks``
——数据库中不存在符号链接。其余校验全部保留：它们防的是逻辑越权
（越出允许的层级、冒用保留名、用 `..` 构造非法路径），与存储介质无关。
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Final

BUSINESS_SECTIONS: Final[tuple[str, ...]] = (
    "业务流程",
    "业务名词解释",
    "ddl",
    "指标或调用指标平台mcp的skill",
)
RESERVED_DOMAIN_NAMES: Final[frozenset[str]] = frozenset({"index", "memory", "业务"})

_MAX_PATH_LENGTH: Final[int] = 512
_MAX_SEGMENT_LENGTH: Final[int] = 120
_ILLEGAL_SEGMENT_CHARS: Final[re.Pattern[str]] = re.compile(r'[:*?"<>|]')


class KnowledgePathError(Exception):
    def __init__(self, code: str, message: str, path: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.path = path
        self.status_code = status_code


@dataclass(frozen=True)
class ResolvedPath:
    virtual_path: str
    read_only: bool


def _invalid(path: str, message: str) -> KnowledgePathError:
    return KnowledgePathError("INVALID_WIKI_PATH", message, path, 400)


def _normalize_segment(raw: str, label: str, path: str) -> str:
    if not raw or not raw.strip():
        raise _invalid(path, f"{label}不能为空")
    value = unicodedata.normalize("NFC", raw)
    if value != value.strip() or value in {".", ".."} or value.startswith("."):
        raise _invalid(path, f"{label}格式不合法")
    if len(value) > _MAX_SEGMENT_LENGTH or any(ch.isprintable() is False for ch in value):
        raise _invalid(path, f"{label}包含非法字符或长度过长")
    if _ILLEGAL_SEGMENT_CHARS.search(value):
        raise _invalid(path, f"{label}包含非法字符")
    return value


def normalize_virtual_path(raw: str) -> str:
    if not raw or not raw.strip():
        raise _invalid("", "路径不能为空")
    if "\\" in raw or raw.startswith("/") or any(not ch.isprintable() for ch in raw):
        raise _invalid(raw, "必须使用相对 POSIX 路径")
    normalized = unicodedata.normalize("NFC", raw)
    if len(normalized) > _MAX_PATH_LENGTH:
        raise _invalid("", "路径过长")
    segments = normalized.split("/")
    return "/".join(_normalize_segment(segment, "路径段", raw) for segment in segments)


def resolve_readable(raw: str) -> ResolvedPath:
    path = normalize_virtual_path(raw)
    if path == "memory" or path.startswith("memory/"):
        return ResolvedPath(path, True)
    if path in {"index", "业务"} or path.startswith(("index/", "业务/")):
        return ResolvedPath(path, False)
    raise _invalid(path, "只允许访问 index、业务或只读 memory 目录")


def resolve_writable_document(raw: str) -> ResolvedPath:
    path = normalize_virtual_path(raw)
    if path == "memory" or path.startswith("memory/"):
        raise KnowledgePathError("WIKI_READ_ONLY", "memory 为系统只读目录", path, 403)
    segments = path.split("/")
    index_document = len(segments) == 2 and segments[0] == "index"
    business_document = (
        len(segments) == 4 and segments[0] == "业务" and segments[2] in BUSINESS_SECTIONS
    )
    if not index_document and not business_document:
        raise _invalid(path, "文档只能位于 index 或业务域的固定板块下")
    if business_document:
        validate_domain_name(segments[1])
    _validate_markdown_name(segments[-1], path)
    return ResolvedPath(path, False)


def validate_domain_name(raw: str) -> str:
    name = _normalize_segment(raw, "业务域名称", raw)
    if name.lower() in RESERVED_DOMAIN_NAMES or name in BUSINESS_SECTIONS:
        raise _invalid(name, "业务域名称为保留名称")
    if name.lower().endswith(".md"):
        raise _invalid(name, "业务域名称不能使用文档扩展名")
    return name


def _validate_markdown_name(name: str, path: str) -> None:
    _normalize_segment(name, "文档名称", path)
    if not name.endswith(".md") or len(name) <= 3:
        raise KnowledgePathError("INVALID_FILE_TYPE", "只允许小写 .md 文档", path, 400)
```

- [x] **Step 4: 跑测试确认通过**

```powershell
cd backend
uv run pytest tests/unit/knowledge/test_path_policy.py -v
```

预期：全部 PASS。若 NFC 用例失败，检查 `_normalize_segment` 是否在长度检查**之前**归一化。

- [x] **Step 5: 跑门禁；按用户授权延后统一提交**

```bash
git add backend/app/knowledge/path_policy.py backend/tests/unit/knowledge/test_path_policy.py
git commit -m "feat: 知识库虚拟路径策略复刻参考实现除符号链接外的全部校验"
```

---

## Task 2: 版本号与目录聚合版本

**Files:**
- Create: `backend/app/knowledge/versioning.py`
- Test: `backend/tests/unit/knowledge/test_versioning.py`

**Interfaces:**
- Produces:
  - `document_version(content: str) -> str`（内容 UTF-8 字节的 SHA-256 十六进制）
  - `directory_version(virtual_path: str, children: Sequence[tuple[str, str]]) -> str`
  - `parse_if_match(raw: str | None) -> str | None`（剥 `W/` 前缀与包裹双引号）

- [x] **Step 1: 写失败测试**

```python
"""版本号计算，对应参考实现 WikiAdminService.digest / version。"""

from __future__ import annotations

import hashlib

from app.knowledge.versioning import directory_version, document_version, parse_if_match


def test_document_version_is_sha256_of_utf8_bytes() -> None:
    assert document_version("内容") == hashlib.sha256("内容".encode()).hexdigest()


def test_directory_version_changes_when_any_child_changes() -> None:
    before = directory_version("业务/交易", [("业务/交易/业务流程", "aaa")])
    after = directory_version("业务/交易", [("业务/交易/业务流程", "bbb")])
    assert before != after


def test_directory_version_is_order_stable() -> None:
    """子节点顺序由服务端固定，同一内容必须给出同一版本。"""

    children = [("a", "1"), ("b", "2")]
    assert directory_version("业务", children) == directory_version("业务", children)


def test_empty_directory_still_has_a_version() -> None:
    assert directory_version("业务/新域", []) != ""


def test_parse_if_match_strips_weak_prefix_and_quotes() -> None:
    assert parse_if_match('W/"abc"') == "abc"
    assert parse_if_match('"abc"') == "abc"
    assert parse_if_match("abc") == "abc"
    assert parse_if_match("  abc  ") == "abc"
    assert parse_if_match(None) is None
    assert parse_if_match("   ") is None
```

- [x] **Step 2: 跑测试确认失败**

```powershell
cd backend
uv run pytest tests/unit/knowledge/test_versioning.py -v
```

- [x] **Step 3: 实现**

创建 `backend/app/knowledge/versioning.py`：

```python
"""知识库乐观锁版本号。

参考实现 ``WikiAdminService``：文件版本是内容 SHA-256；目录版本把
``"directory:" + 虚拟路径`` 与各子节点 ``path:version`` 逐行拼接后再取 SHA-256。
两者都是十六进制小写串，响应中以 ETag 形式给出。
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence


def document_version(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def directory_version(virtual_path: str, children: Sequence[tuple[str, str]]) -> str:
    signature = f"directory:{virtual_path}"
    for child_path, child_version in children:
        signature += f"\n{child_path}:{child_version}"
    return hashlib.sha256(signature.encode("utf-8")).hexdigest()


def parse_if_match(raw: str | None) -> str | None:
    """剥掉 W/ 前缀与包裹的双引号，对应参考实现 requireVersion 的宽容解析。"""

    if raw is None or not raw.strip():
        return None
    candidate = raw.strip()
    if candidate.startswith("W/"):
        candidate = candidate[2:].strip()
    if len(candidate) >= 2 and candidate.startswith('"') and candidate.endswith('"'):
        candidate = candidate[1:-1]
    return candidate
```

- [x] **Step 4: 跑测试确认通过与门禁；按用户授权延后统一提交**

```powershell
cd backend
uv run pytest tests/unit/knowledge/test_versioning.py -v
```

```bash
git add backend/app/knowledge/versioning.py backend/tests/unit/knowledge/test_versioning.py
git commit -m "feat: 知识库文档与目录版本号复刻参考实现的 SHA-256 聚合规则"
```

---

## Task 3: 后台仓储

**Files:**
- Create: `backend/app/repositories/knowledge_admin.py`
- Test: `backend/tests/integration/repositories/test_knowledge_admin_repository.py`

**Interfaces:**
- Produces: `KnowledgeAdminRepository(session)`，方法
  - `async def list_paths(prefix: str) -> list[KnowledgeDocument]`
  - `async def get_by_path(virtual_path: str) -> KnowledgeDocument | None`
  - `async def find_case_insensitive(parent: str, name: str) -> KnowledgeDocument | None`
  - `async def create(*, virtual_path: str, category: str, title: str, content: str) -> KnowledgeDocument`
  - `async def update_content(document: KnowledgeDocument, content: str) -> KnowledgeDocument`
  - `async def delete(document: KnowledgeDocument) -> None`
  - `async def move_prefix(old_prefix: str, new_prefix: str) -> int`
  - `async def count_under(prefix: str) -> int`

- [x] **Step 1: 写失败测试**

```python
"""后台仓储：前缀查询、大小写冲突、批量改前缀。"""

from __future__ import annotations

import pytest

from app.repositories.knowledge_admin import KnowledgeAdminRepository

pytestmark = pytest.mark.integration


async def test_list_paths_filters_by_prefix(db_session) -> None:
    repository = KnowledgeAdminRepository(db_session)
    await repository.create(
        virtual_path="业务/交易/业务流程/下单.md", category="TRADE", title="下单", content="a"
    )
    await repository.create(
        virtual_path="业务/退货/业务流程/退货.md", category="REFUND", title="退货", content="b"
    )
    await db_session.flush()

    rows = await repository.list_paths("业务/交易/")

    assert [r.source_path for r in rows] == ["业务/交易/业务流程/下单.md"]


async def test_find_case_insensitive_detects_conflict(db_session) -> None:
    """参考实现 rejectCaseInsensitiveConflict：大小写不同的同名节点视为冲突。"""

    repository = KnowledgeAdminRepository(db_session)
    await repository.create(
        virtual_path="index/Readme.md", category="UNKNOWN", title="Readme", content="a"
    )
    await db_session.flush()

    assert await repository.find_case_insensitive("index", "readme.md") is not None
    assert await repository.find_case_insensitive("index", "other.md") is None


async def test_move_prefix_rewrites_every_descendant(db_session) -> None:
    repository = KnowledgeAdminRepository(db_session)
    for section in ("业务流程", "业务名词解释"):
        await repository.create(
            virtual_path=f"业务/旧域/{section}/a.md",
            category="TRADE",
            title="a",
            content="x",
        )
    await db_session.flush()

    moved = await repository.move_prefix("业务/旧域/", "业务/新域/")
    await db_session.flush()

    assert moved == 2
    assert await repository.count_under("业务/旧域/") == 0
    assert await repository.count_under("业务/新域/") == 2


async def test_update_content_bumps_version(db_session) -> None:
    repository = KnowledgeAdminRepository(db_session)
    document = await repository.create(
        virtual_path="index/a.md", category="UNKNOWN", title="a", content="v1"
    )
    await db_session.flush()

    await repository.update_content(document, "v2")
    await db_session.flush()

    assert document.content == "v2"
    assert document.version == 2
```

- [x] **Step 2: 跑测试确认失败，Step 3: 实现仓储**

创建 `backend/app/repositories/knowledge_admin.py`。要点：

- 与检索用的 `KnowledgeRepository` **分开**——检索只读 ACTIVE 文档且不关心层级，后台要按前缀查、要改路径，两者的查询形态没有交集，合并会让检索侧暴露写方法（Task 8 的不变量测试会拦住）；
- `find_case_insensitive` 用 `func.lower(KnowledgeDocument.source_path) == f"{parent}/{name}".lower()`；
- `move_prefix` 用 `update(...).where(source_path.like(f"{old}%")).values(source_path=func.replace(...))`，返回 `result.rowcount`；
- `create` 写入 `status="ACTIVE"`、`source="ADMIN"`、`is_complete=True`。

- [x] **Step 4: 跑测试确认通过与门禁；按用户授权延后统一提交**

```powershell
cd backend
$env:REQUIRE_INTEGRATION_DB = "1"
uv run pytest tests/integration/repositories/test_knowledge_admin_repository.py -v
```

```bash
git add backend/app/repositories/knowledge_admin.py backend/tests/integration/repositories/test_knowledge_admin_repository.py
git commit -m "feat: 知识库后台仓储支持前缀查询、大小写冲突检测与批量改前缀"
```

---

## Task 4: 契约与目录树端点

**Files:**
- Create: `backend/app/schemas/knowledge.py`
- Create: `backend/app/services/knowledge_admin_service.py`
- Create: `backend/app/api/routes/knowledge.py`
- Modify: `backend/app/api/router.py`
- Test: `backend/tests/api/test_knowledge_tree.py`

**Interfaces:**
- Produces:
  - `KnowledgeTreeNode`：`name`、`path`、`node_type`（`"directory" | "document"`）、`read_only: bool`、`size: int`、`version: str`、`children: list[KnowledgeTreeNode]`
  - `KnowledgeTreeResponse`：`roots: list[KnowledgeTreeNode]`
  - `GET /api/admin/knowledge/tree`

**契约命名**：沿用本项目的扁平 snake_case 约定（AGENTS.md §10.4），`type` 改名 `node_type` 避开 Python 关键字与 TS 保留习惯。

- [x] **Step 1: 写失败测试**

```python
"""目录树：三个根、固定板块顺序、memory 只读。"""

from __future__ import annotations


async def test_tree_returns_three_roots_in_fixed_order(admin_client) -> None:
    response = await admin_client.get("/api/admin/knowledge/tree")

    assert response.status_code == 200
    roots = response.json()["roots"]
    assert [r["path"] for r in roots] == ["index", "业务", "memory"]


async def test_memory_root_is_read_only(admin_client) -> None:
    roots = (await admin_client.get("/api/admin/knowledge/tree")).json()["roots"]
    memory = next(r for r in roots if r["path"] == "memory")

    assert memory["read_only"] is True


async def test_business_sections_follow_reference_order(admin_client, seeded_domain) -> None:
    roots = (await admin_client.get("/api/admin/knowledge/tree")).json()["roots"]
    business = next(r for r in roots if r["path"] == "业务")
    domain = business["children"][0]

    assert [c["name"] for c in domain["children"]] == [
        "业务流程",
        "业务名词解释",
        "ddl",
        "指标或调用指标平台mcp的skill",
    ]


async def test_tree_requires_admin_token(client) -> None:
    assert (await client.get("/api/admin/knowledge/tree")).status_code == 401


async def test_merchant_token_is_rejected(client, demo_token) -> None:
    """管理员令牌不复用 Authorization——商家 Token 调管理接口必须失败。"""

    response = await client.get(
        "/api/admin/knowledge/tree",
        headers={"Authorization": f"Bearer {demo_token}"},
    )

    assert response.status_code == 401
```

- [x] **Step 2–4: 跑失败 → 实现 → 跑通过**

实现要点：

- 服务层从 `list_paths("index/")`、`list_paths("业务/")` 装配树，**目录节点由路径推导**（数据库里只有文档行，没有目录行）；
- 业务域下的四个板块**无论有没有文档都要出现**，顺序按 `BUSINESS_SECTIONS`，对应参考实现 `comparePaths` 按下标排序；
- 同层内目录在前、文档在后，同类按名称不区分大小写排序；
- memory 根从 `merchant_memories` 装配，`read_only=True`，且**按当前请求的管理员视角展示全部商家的记忆目录，不展示记忆正文以外的商家隐私字段**；
- 版本用 Task 2 的 `document_version` / `directory_version`；
- 路由用 `Depends(require_admin_token)`；未配置 `ADMIN_TOKEN` 时**整个 router 不挂载**（照抄 `backend/app/api/routes/admin.py` 的既有写法）。

- [x] **Step 5: 跑门禁；按用户授权延后统一提交**

```bash
git add backend/app/schemas/knowledge.py backend/app/services/knowledge_admin_service.py backend/app/api/routes/knowledge.py backend/app/api/router.py backend/tests/api/test_knowledge_tree.py
git commit -m "feat: 知识库目录树端点按参考实现固定三根与四板块顺序"
```

---

## Task 5: 文档 CRUD 与乐观锁

**Files:**
- Modify: `backend/app/api/routes/knowledge.py`
- Modify: `backend/app/services/knowledge_admin_service.py`
- Modify: `backend/app/core/errors.py`
- Test: `backend/tests/api/test_knowledge_documents.py`

**Interfaces:**
- Produces:
  - `GET /api/admin/knowledge/documents/{id}`（`id` 为 URL 编码的虚拟路径）
  - `POST /api/admin/knowledge/documents`
  - `PUT /api/admin/knowledge/documents/{id}`
  - `DELETE /api/admin/knowledge/documents/{id}`
  - 响应头 `ETag: "<version>"`

- [x] **Step 1: 写失败测试**

```python
"""文档 CRUD 与 428/412 乐观锁。"""

from __future__ import annotations

import pytest


async def test_create_returns_etag(admin_client) -> None:
    response = await admin_client.post(
        "/api/admin/knowledge/documents",
        json={"path": "index/新文档.md", "content": "# 标题"},
    )

    assert response.status_code == 201
    assert response.headers["etag"].startswith('"')


async def test_create_rejects_duplicate(admin_client, existing_document) -> None:
    response = await admin_client.post(
        "/api/admin/knowledge/documents",
        json={"path": existing_document, "content": "x"},
    )

    assert response.status_code == 409
    assert response.json()["code"] == "WIKI_NODE_EXISTS"


async def test_create_rejects_case_insensitive_duplicate(admin_client) -> None:
    await admin_client.post(
        "/api/admin/knowledge/documents", json={"path": "index/Readme.md", "content": "a"}
    )
    response = await admin_client.post(
        "/api/admin/knowledge/documents", json={"path": "index/readme.md", "content": "b"}
    )

    assert response.status_code == 409


async def test_update_without_if_match_returns_428(admin_client, existing_document) -> None:
    """参考实现 requireVersion：缺 If-Match 返回 428，不是 400 也不是 412。"""

    response = await admin_client.put(
        f"/api/admin/knowledge/documents/{existing_document}",
        json={"content": "新内容"},
    )

    assert response.status_code == 428
    assert response.json()["code"] == "WIKI_VERSION_REQUIRED"


async def test_update_with_stale_if_match_returns_412(admin_client, existing_document) -> None:
    response = await admin_client.put(
        f"/api/admin/knowledge/documents/{existing_document}",
        json={"content": "新内容"},
        headers={"If-Match": '"deadbeef"'},
    )

    assert response.status_code == 412
    assert response.json()["code"] == "WIKI_VERSION_CONFLICT"


async def test_update_with_weak_etag_is_accepted(admin_client, existing_document) -> None:
    current = (await admin_client.get(
        f"/api/admin/knowledge/documents/{existing_document}"
    )).headers["etag"]

    response = await admin_client.put(
        f"/api/admin/knowledge/documents/{existing_document}",
        json={"content": "新内容"},
        headers={"If-Match": f"W/{current}"},
    )

    assert response.status_code == 200


async def test_content_with_nul_is_rejected(admin_client) -> None:
    response = await admin_client.post(
        "/api/admin/knowledge/documents",
        json={"path": "index/坏文档.md", "content": "a\x00b"},
    )

    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_WIKI_CONTENT"


async def test_oversized_content_is_rejected(admin_client, settings) -> None:
    response = await admin_client.post(
        "/api/admin/knowledge/documents",
        json={"path": "index/大文档.md", "content": "x" * (settings.knowledge_max_document_bytes + 1)},
    )

    assert response.status_code == 413
    assert response.json()["code"] == "WIKI_DOCUMENT_TOO_LARGE"


async def test_writing_into_memory_is_forbidden(admin_client) -> None:
    """防污染的 API 侧强制：记忆库永远不可写。"""

    response = await admin_client.post(
        "/api/admin/knowledge/documents",
        json={"path": "memory/merchants/abc/TRADE.md", "content": "x"},
    )

    assert response.status_code == 403
    assert response.json()["code"] == "WIKI_READ_ONLY"


async def test_delete_requires_if_match(admin_client, existing_document) -> None:
    assert (
        await admin_client.delete(f"/api/admin/knowledge/documents/{existing_document}")
    ).status_code == 428
```

- [x] **Step 2–4: 跑失败 → 实现 → 跑通过**

实现要点：

- 新增配置项 `knowledge_max_document_bytes`（`app/core/config.py`，默认 `262_144`，即 256 KiB）并写进 `.env.example`；
- 错误码在 `app/core/errors.py` 追加，映射到设计说明 §2.5 列出的 14 个；`SYMLINK_NOT_ALLOWED` 不实现（无对应物），其余 13 个全部实现；
- `KnowledgePathError` 在路由层统一转成 `ErrorResponse`，保持既有错误契约的扁平字段；
- 创建时校验父层存在：`业务/{域}/{板块}/` 的域必须已存在，否则 400 `INVALID_WIKI_PARENT`；
- 内容含 `\x00` → 400 `INVALID_WIKI_CONTENT`；超长 → 413；
- 每次写入后重算并回写 `ETag`。

- [x] **Step 5: 跑门禁；按用户授权延后统一提交**

```bash
git add backend/app/api/routes/knowledge.py backend/app/services/knowledge_admin_service.py backend/app/core/errors.py backend/app/core/config.py .env.example backend/tests/api/test_knowledge_documents.py
git commit -m "feat: 知识库文档 CRUD 复刻 428/412 乐观锁与大小写冲突拒绝"
```

---

## Task 6: 业务域三端点与文档补齐

**Files:**
- Modify: `backend/app/api/routes/knowledge.py`
- Modify: `backend/app/services/knowledge_admin_service.py`
- Modify: `AGENTS.md`（§10.2）
- Modify: `docs/PRD.md`（§11）
- Test: `backend/tests/api/test_knowledge_domains.py`

**这三个端点参考项目有、我方接口清单没有。按 R9 判定为「我们缺了要补」，本 Task 同时改文档。**

**Interfaces:**
- Produces:
  - `POST /api/admin/knowledge/business-domains`（建域，自动建齐四个板块）
  - `PUT /api/admin/knowledge/business-domains`（改名，需 `If-Match`）
  - `DELETE /api/admin/knowledge/business-domains`（删域，需 `If-Match` + `recursive` 保护）

- [x] **Step 1: 写失败测试**

```python
"""业务域管理：建域建齐四板块、改名连带文档、删域的 recursive 保护。"""

from __future__ import annotations


async def test_create_domain_creates_all_four_sections(admin_client) -> None:
    response = await admin_client.post(
        "/api/admin/knowledge/business-domains", json={"name": "新业务"}
    )

    assert response.status_code == 201
    assert [c["name"] for c in response.json()["children"]] == [
        "业务流程",
        "业务名词解释",
        "ddl",
        "指标或调用指标平台mcp的skill",
    ]


async def test_create_domain_rejects_reserved_name(admin_client) -> None:
    response = await admin_client.post(
        "/api/admin/knowledge/business-domains", json={"name": "memory"}
    )

    assert response.status_code == 400


async def test_rename_moves_every_descendant_document(admin_client, domain_with_document) -> None:
    version = domain_with_document["version"]
    response = await admin_client.put(
        "/api/admin/knowledge/business-domains",
        params={"name": "旧域"},
        json={"new_name": "新域"},
        headers={"If-Match": f'"{version}"'},
    )

    assert response.status_code == 200
    tree = (await admin_client.get("/api/admin/knowledge/tree")).json()
    business = next(r for r in tree["roots"] if r["path"] == "业务")
    assert [d["name"] for d in business["children"]] == ["新域"]


async def test_delete_non_empty_domain_without_recursive_returns_409(
    admin_client, domain_with_document
) -> None:
    response = await admin_client.delete(
        "/api/admin/knowledge/business-domains",
        params={"name": "旧域"},
        headers={"If-Match": f'"{domain_with_document["version"]}"'},
    )

    assert response.status_code == 409
    assert response.json()["code"] == "WIKI_DIRECTORY_NOT_EMPTY"


async def test_delete_with_recursive_removes_documents(
    admin_client, domain_with_document
) -> None:
    response = await admin_client.delete(
        "/api/admin/knowledge/business-domains",
        params={"name": "旧域", "recursive": "true"},
        headers={"If-Match": f'"{domain_with_document["version"]}"'},
    )

    assert response.status_code == 204
```

- [x] **Step 2–4: 跑失败 → 实现 → 跑通过**

实现要点：

- **建域在数据库里没有「空目录」**——参考实现建的是四个空文件夹。我方在四个板块下各写一篇占位说明文档（`is_complete=False`），使目录树能显示板块且检索层能如实告知「资料尚未完整」。这一处差异须登记进 parity-audit §5；
- 改名 = `move_prefix("业务/旧/", "业务/新/")`，在同一事务内完成；
- 删域先 `count_under`，非空且未传 `recursive=true` → 409。

- [x] **Step 5: 补文档**

`AGENTS.md` §10.2 的 P1 接口清单追加三行；`docs/PRD.md` §11 同步。两处都注明「参考项目已有、我方原清单缺失，按 R9 补入」。

- [x] **Step 6: 跑门禁；按用户授权延后统一提交**

```bash
git add backend/app/api/routes/knowledge.py backend/app/services/knowledge_admin_service.py AGENTS.md docs/PRD.md backend/tests/api/test_knowledge_domains.py
git commit -m "feat: 补齐参考项目的业务域三端点并按 R9 同步接口清单"
```

---

## Task 7: OpenAPI 与前端类型生成

**Files:**
- Modify: `docs/api.md`、`docs/api.json`
- Modify: `frontend/src/api/generated.ts`
- Create: `frontend/src/api/adapters/knowledge.ts`
- Test: `frontend/src/api/adapters/knowledge.spec.ts`

- [x] **Step 1: 重新导出 OpenAPI**

```powershell
cd backend
uv run python ../scripts/export_openapi.py
```

- [x] **Step 2: 重新生成前端类型**

```powershell
cd frontend
npm.cmd run codegen
npm.cmd run codegen:check
```

预期：`codegen:check` 绿。`generated.ts` 是**提交进仓库的生成产物，禁止手改**。

- [x] **Step 3: 写 Adapter 契约测试并实现 Adapter**

组件**不得直接消费 `generated.ts`**（AGENTS.md §7.5）。新建 `adapters/knowledge.ts` 把生成类型转成前端领域模型，并配契约测试断言字段映射完整、`read_only` 不丢。

- [x] **Step 4: 按用户此前授权延后至全部 Task 完成后统一提交**

```bash
git add docs/api.md docs/api.json frontend/src/api/generated.ts frontend/src/api/adapters/
git commit -m "feat: 导出知识库后台契约并新增生成类型到领域模型的 Adapter"
```

---

## Task 8: 后台不得污染检索侧的不变量

**Files:**
- Test: `backend/tests/unit/knowledge/test_admin_boundaries.py`

- [x] **Step 1: 写不变量测试**

```python
"""后台与检索的边界。

后台可写团队知识、只读记忆；检索只读、不写。任一方向被打通，这里就红。
"""

from __future__ import annotations

import ast
from pathlib import Path


def test_retrieval_repository_has_no_write_methods() -> None:
    tree = ast.parse(Path("app/repositories/knowledge.py").read_text(encoding="utf-8"))
    names = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef)
    }
    assert not {"delete", "update_content", "move_prefix"} & names


def test_admin_service_never_writes_merchant_memories() -> None:
    source = Path("app/services/knowledge_admin_service.py").read_text(encoding="utf-8")
    # 记忆只读：后台服务不得引用记忆仓储的写方法
    assert "MerchantMemoryRepository" not in source or "upsert" not in source


def test_admin_routes_do_not_accept_authorization_header() -> None:
    """管理员令牌不复用 Authorization（AGENTS.md §10.2.1）。"""

    source = Path("app/api/routes/knowledge.py").read_text(encoding="utf-8")
    assert "Authorization" not in source
    assert "require_admin_token" in source
```

- [x] **Step 2: 跑测试；按用户此前授权延后至全部 Task 完成后统一提交**

```bash
git add backend/tests/unit/knowledge/test_admin_boundaries.py
git commit -m "test: 固化知识库后台与检索侧的读写边界"
```

---

## Task 9: 前端授权对话框与目录树

**Files:**
- Create: `frontend/src/components/knowledge/AdminTokenDialog.vue`
- Create: `frontend/src/components/knowledge/KnowledgeTree.vue`
- Create: `frontend/src/api/knowledge.ts`
- Create: `frontend/src/stores/knowledge.ts`
- Modify: `frontend/src/views/KnowledgeBaseView.vue`
- Test: `frontend/src/stores/knowledge.spec.ts`、`frontend/src/components/knowledge/AdminTokenDialog.spec.ts`

**安全硬约束**：令牌只存内存或 `sessionStorage`，**不得进 URL、`localStorage` 或构建产物**。

- [x] **Step 1: 写失败测试**

```ts
import { describe, expect, it } from 'vitest'

import { useKnowledgeStore } from '@/stores/knowledge'

describe('知识库后台令牌', () => {
  it('令牌不写入 localStorage', () => {
    const store = useKnowledgeStore()
    store.setAdminToken('secret-token')

    expect(localStorage.getItem('adminToken')).toBeNull()
    expect(JSON.stringify(localStorage)).not.toContain('secret-token')
  })

  it('令牌走 X-Admin-Token 而不是 Authorization', async () => {
    const store = useKnowledgeStore()
    store.setAdminToken('secret-token')

    const headers = store.adminHeaders()

    expect(headers['X-Admin-Token']).toBe('secret-token')
    expect(headers.Authorization).toBeUndefined()
  })

  it('未授权时不发起任何请求', async () => {
    const store = useKnowledgeStore()

    await expect(store.loadTree()).rejects.toThrow(/未授权/)
  })

  it('登出清空令牌与树', () => {
    const store = useKnowledgeStore()
    store.setAdminToken('secret-token')
    store.signOut()

    expect(store.adminToken).toBe('')
    expect(store.roots).toEqual([])
  })
})
```

- [x] **Step 2–4: 跑失败 → 实现 → 跑通过**

`KnowledgeBaseView.vue` 在占位文件内填实现（**不新建文件、不改路由**，占位注释已明确要求）：未授权时渲染 `AdminTokenDialog`，授权后渲染 `KnowledgeTree` + `DocumentEditor` 两栏。

- [x] **Step 5: 跑密钥扫描门禁**

```powershell
cd frontend
npm.cmd run build
npm.cmd run check-no-secrets
```

预期：绿。若红，检查是否有测试令牌被写进了源码常量。

- [x] **Step 6: 按用户此前授权延后至全部 Task 完成后统一提交**

```bash
git add frontend/src/components/knowledge/ frontend/src/api/knowledge.ts frontend/src/stores/knowledge.ts frontend/src/views/KnowledgeBaseView.vue frontend/src/stores/knowledge.spec.ts
git commit -m "feat: 知识库后台授权对话框与目录树，令牌只存内存不进构建产物"
```

---

## Task 10: 前端编辑器与冲突提示

**Files:**
- Create: `frontend/src/components/knowledge/DocumentEditor.vue`
- Test: `frontend/src/components/knowledge/DocumentEditor.spec.ts`

- [x] **Step 1: 写失败测试**

```ts
import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'

import DocumentEditor from '@/components/knowledge/DocumentEditor.vue'

describe('知识文档编辑器', () => {
  it('memory 文档只读且不显示保存按钮', () => {
    const wrapper = mount(DocumentEditor, {
      props: { document: { path: 'memory/merchants/abc/TRADE.md', content: 'x', readOnly: true, version: 'v1' } },
    })

    expect(wrapper.find('textarea').attributes('readonly')).toBeDefined()
    expect(wrapper.find('[data-testid="save"]').exists()).toBe(false)
  })

  it('412 冲突时提示重新加载且不丢失用户输入', async () => {
    const wrapper = mount(DocumentEditor, {
      props: { document: { path: 'index/a.md', content: '原文', readOnly: false, version: 'v1' } },
    })
    await wrapper.find('textarea').setValue('我改的内容')
    await wrapper.vm.handleConflict()

    expect(wrapper.text()).toContain('已被其他维护者修改')
    expect(wrapper.find('textarea').element.value).toBe('我改的内容')
  })

  it('保存时带上当前版本作为 If-Match', async () => {
    const calls: Array<Record<string, string>> = []
    const wrapper = mount(DocumentEditor, {
      props: {
        document: { path: 'index/a.md', content: '原文', readOnly: false, version: 'v1' },
        save: async (_: string, headers: Record<string, string>) => { calls.push(headers) },
      },
    })
    await wrapper.find('[data-testid="save"]').trigger('click')

    expect(calls[0]['If-Match']).toBe('"v1"')
  })
})
```

- [x] **Step 2–4: 跑失败 → 实现 → 跑通过**

冲突提示必须**保留用户已输入的内容**——直接覆盖等于丢失维护者的工作。

- [x] **Step 5: 按用户此前授权延后至全部 Task 完成后统一提交**

```bash
git add frontend/src/components/knowledge/DocumentEditor.vue frontend/src/components/knowledge/DocumentEditor.spec.ts
git commit -m "feat: 知识文档编辑器支持只读记忆与 412 冲突不丢输入"
```

---

## Task 11: 端到端与文档收口

**Files:**
- Create: `frontend/e2e/knowledge-base.spec.ts`
- Modify: `docs/yshopping-parity-audit.md`、`docs/project-progress.md`、`AGENTS.md`

- [x] **Step 1: 写 E2E**

一组用例覆盖：未授权进不去 → 输入令牌进入 → 目录树可见三个根 → 打开文档 → 编辑保存成功 → memory 文档不可编辑。

```powershell
cd frontend
npx.cmd playwright test e2e/knowledge-base.spec.ts
```

- [x] **Step 2: 结清 parity-audit 挂账**

`docs/yshopping-parity-audit.md` §6 中 `WikiAdminService`（498 行）一行移出「待核实」，在 §9 追加能力行；§5 追加两条偏离：

- **5.6 建业务域写占位文档而非空目录**——数据库中不存在空目录，四个板块各写一篇 `is_complete=False` 的占位说明，使目录树可显示且检索层能如实提示资料未完整；
- **5.7 不实现 `SYMLINK_NOT_ALLOWED`**——数据库中不存在符号链接；其余 13 个错误码全部实现。

- [x] **Step 3: 更新 AGENTS.md 与进度快照**

- §7.2 `KnowledgeBaseView.vue` 由 [P1 未实现] 改为已实现；
- §8.2 路由表 `routes/knowledge.py` 状态更新；
- `docs/project-progress.md` 更新日期、P1 状态（知识库后台已实现）、下一步与风险。

- [x] **Step 4: 跑全量门禁；按用户此前授权统一提交**

```bash
git add frontend/e2e/knowledge-base.spec.ts docs/ AGENTS.md
git commit -m "docs: 结清知识库后台还原度挂账并更新进度快照"
```

---

## 出口判据

- [x] 后端全量门禁在真实 PostgreSQL 上通过，`ruff` / `mypy app` 全绿。
- [x] 前端 `typecheck` / `lint` / `format:check` / `codegen:check` / `fixtures:check` / `vitest` / `check-no-secrets` 全绿。
- [x] 路径策略的 13 条校验各有测试；`SYMLINK_NOT_ALLOWED` 已登记为不实现。
- [x] 缺 `If-Match` 返回 **428**、版本不匹配返回 **412**，两条各有测试（不得退化成 400）。
- [x] 写入 `memory/**` 返回 **403 `WIKI_READ_ONLY`**，有测试。
- [x] 商家 Token 调 `/api/admin/knowledge/*` 被拒，有测试。
- [x] 未配置 `ADMIN_TOKEN` 时整个 router 不挂载，有测试。
- [x] 大小写不同的同名文档被拒，有测试。
- [x] 业务域三端点已补进 `AGENTS.md` §10.2 与 `docs/PRD.md` §11。
- [x] E2E 一组用例通过。
- [x] parity-audit 中 `WikiAdminService` 不再挂在「待核实」。

**不在本计划范围**：`GET/PATCH/DELETE /api/memories` 三个商家自助记忆端点（商家 Token，独立切片）；知识库版本历史与回滚（参考项目也没有）；附件与日报（B8/F7）。
