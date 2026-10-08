# N1 会话身份与租户隔离实施计划

> **给执行者：** 用 `superpowers:executing-plans` 逐任务推进。步骤用 `- [ ]` 复选框跟踪。
> **本计划不含任何 Git 提交步骤**——`AGENTS.md` R2 要求逐次授权。
>
> **执行状态（2026-09-23）：** 27 步的代码与测试均已完成；Astra 已完成 D1–D6 独立审核，
> 真实 PostgreSQL 并发、回滚、角色/租户隔离与时序哨兵通过。此前等待必审的 Task 1–5
> 复选框现据复审结果同步勾选，当前 **27 / 27**。证据见
> `plans/2026-09-22-n1-review-remediation.md`「Astra 完整审核记录」。

**目标：** 实现 D7 / D8 的会话模式身份：顾客访客会话、演示顾客绑定、商家 Token 换会话、
角色不可变、双重过滤、统一 403 非枚举响应、级联撤销与安全审计；并落地 PRD §11.2 的 5 条会话签发路由
（Task 7，2026-09-21 用户裁定并入），按 §8.0.1 同次完成 OpenAPI 导出、商家端生成类型与会话 Adapter。

**架构：** 会话是**凭证**不是标识符——高熵生成、哈希存储、可过期可注销可撤销。
顾客与商家**复用同一套会话基础设施，但角色、状态模型与路由依赖不同，不是可互换的凭证**（D8①）。新增 `app/core/session.py` 与 `app/repositories/session.py`，通过 FastAPI 依赖暴露
`SessionContext`（定义见 `docs/backend-development-plan.md` §6.9）。
v1 的 `MerchantContext` 与 Bearer 路径**保持不变**，两套并存直到 v2 前端切换完成。

**技术栈：** Python 3.12、FastAPI、Pydantic v2、SQLAlchemy 2、Alembic、pytest。

**规格来源：**
- `docs/specs/2026-09-18-anthropic-fusion-decisions.md` D7、D8、O1、O2
- `docs/PRD.md` §7.5（会话与身份状态机）、§9 SEC3、§12.1（安全硬门禁）
- `docs/backend-development-plan.md` §5.6、§6.9（`SessionContext`）
- `AGENTS.md` R5、R6、§8.3（鉴权类别表）

---

## 全局约束

- 面向开发者的新增内容一律中文（R1）；标识符英文。
- **不执行 Git 提交、发布或历史改写操作**（R2）；允许 `git status` / `git diff --check` 等只读检查。
  每个任务以验证命令收尾。
- **不调用真实 LLM**（R3）。本计划不触及模型调用路径。
- **不修改 `app/agent/graph.py`、`state.py`、`prefilter.py`**（冻结基线，§5.6）。
- **不修改 v1 的 `MerchantContext`、`resolve_demo_token` 与既有 Bearer 依赖**——
  v1 路由必须在整个 N1 期间保持可用（PRD §15 N1 回滚点）。
- 新配置沿用无前缀命名（R6）。

---

## 文件结构

| 文件 | 责任 | 操作 |
| --- | --- | --- |
| `backend/app/core/session.py` | 扩展契约计划已创建的唯一 `SessionRole`：会话 ID 生成、哈希、`SessionContext`、别名函数 | 修改 |
| `backend/app/core/config.py` | `SESSION_TTL_SECONDS`、`BUYER_ALIAS_SECRET` 与生产安全校验 | 修改 |
| `backend/app/models/session.py` | `agent_sessions` ORM | 新建 |
| `backend/app/models/provenance.py` | 对话来源状态与乐观锁版本 | 新建 |
| `backend/app/repositories/session.py` | 签发、解析、注销、级联撤销 | 新建 |
| `backend/app/repositories/provenance.py` | 来源状态读取、记录与并发重试 | 新建 |
| `backend/app/services/session_service.py` | 可信店铺解析、演示顾客绑定与购物车合并事务边界 | 新建 |
| `backend/app/services/resource_scope.py` | 一次固定查询形状的主体范围检查与统一 403 | 新建 |
| `backend/app/api/session_deps.py` | `require_customer_session` / `require_merchant_session` | 新建 |
| `backend/app/api/routes/v2/shop_sessions.py` | 顾客会话签发、演示顾客绑定、注销三条路由（Task 7） | 新建 |
| `backend/app/api/routes/v2/merchant_sessions.py` | 商家 Token 换会话、注销两条路由（Task 7） | 新建 |
| `backend/app/api/router.py` | 挂载 v2 会话路由（Task 7） | 修改 |
| `backend/tests/api/v2/test_session_routes.py` | 5 条会话路由的 HTTP 契约与跨角色门禁（Task 7） | 新建 |
| `docs/api.json`、`docs/api.md`、`frontend/src/api/generated.ts` | §8.0.1 同次导出与 codegen（Task 7） | 重新生成 |
| `frontend/src/api/adapters/session.ts` 及其 spec | 商家会话交换/注销 Adapter 与契约测试（Task 7） | 新建 |
| `backend/app/core/errors.py` | 同步契约计划的会话相关错误码 | 修改 |
| `backend/app/localization/error_messages.py` | 新码双语文案 | 修改 |
| `backend/app/repositories/audit.py`、`backend/app/repositories/protocols.py` | 跨角色、资源不可见与会话事件审计 | 修改 |
| `backend/migrations/versions/*_agent_sessions.py` | 建立会话与来源状态表、CHECK、不可变触发器 | 新建 |
| `backend/tests/unit/core/test_session.py` | 凭证生成与哈希 | 新建 |
| `backend/tests/integration/test_session_isolation.py` | **安全硬门禁用例** | 新建 |
| `backend/pyproject.toml` | 注册 `security_timing` marker，避免未登记 marker 漂移 | 修改 |
| `.env.example`、`docs/deployment.md`、`AGENTS.md` R6 | 新 Secret、TTL 与部署约束 | 修改 |
| `docs/backend-development-plan.md` §6.16 | Session Identity 模块契约 | 新增 |

**为什么单独建 `session_deps.py` 而不塞进 `dependencies.py`**：后者已有 350+ 行且承载全部 v1 依赖，
v2 会话是并存的另一套鉴权，混在一起会让"这个路由用哪套身份"难以一眼看清。

---

## 前置依赖

**Task 1 必须在 `plans/2026-09-20-n1-v2-contract-freeze.md` 的 Task 1（共用组件）之后**——
契约任务先创建 `app.core.session.SessionRole` 这一唯一领域枚举，并完成 §8.7.2 错误码表；
本计划只扩展同一文件，不得重新定义 `SessionRole` 或第二套错误码。

其余任务不依赖契约计划。

**迁移链**：Task 2 与 Task 6 的迁移与数据迁移计划 M1–M8 共用一条线性 Alembic 链，
创建前后都要确认 `uv run alembic heads` 恰好一个 head；与数据迁移计划并行开发时，
两边不得共用同一个测试库做升降级（规则见数据迁移计划「迁移链与测试库规则」）。

---

### Task 1：会话凭证原语

会话 ID 是凭证，不是主键（D7③：高熵、可过期、可注销、可撤销）。**它的安全属性和密码同级**：高熵、不可枚举、库里存哈希。

**文件：**
- 创建：`backend/app/core/session.py`
- 创建：`backend/tests/unit/core/test_session.py`

**接口：**
- 消费：契约计划 Task 1 已定义的 `SessionRole`
- 产出：`SessionContext`、`SessionAlreadyBoundError`、`new_session_token()`、
  `token_fingerprint()`、`issuer_fingerprint()`、`buyer_alias()`。Task 2–6 全部从这里导入；
  `SessionRole` 继续由同一模块导出，但本任务不得重定义。

- [x] **步骤 1：写失败测试**

```python
import re
import pytest
from uuid import UUID
from app.core.session import (
    SessionContext, SessionRole, buyer_alias, issuer_fingerprint,
    new_session_token, token_fingerprint,
)

MID = UUID("00000000-0000-0000-0000-000000000100")
MID_A = UUID("00000000-0000-0000-0000-000000000101")
MID_B = UUID("00000000-0000-0000-0000-000000000102")
ALIAS_KEY = b"test-only-buyer-alias-key-32-bytes"


def test_token_is_high_entropy_and_urlsafe() -> None:
    t = new_session_token()
    assert len(t) >= 43                      # 32 字节 base64url ≈ 43 字符
    assert re.fullmatch(r"[A-Za-z0-9_-]+", t)


def test_tokens_are_unique() -> None:
    assert len({new_session_token() for _ in range(1000)}) == 1000


def test_fingerprint_is_stable_and_irreversible() -> None:
    t = new_session_token()
    assert token_fingerprint(t) == token_fingerprint(t)
    assert t not in token_fingerprint(t)      # 原值不得出现在指纹里
    assert len(token_fingerprint(t)) == 64    # sha256 hex


def test_issuer_fingerprint_is_stable_and_does_not_leak_token() -> None:
    demo_token = "test-only-merchant-login-token"
    assert issuer_fingerprint(demo_token) == issuer_fingerprint(demo_token)
    assert demo_token not in issuer_fingerprint(demo_token)
    assert len(issuer_fingerprint(demo_token)) == 64


def test_customer_context_requires_buyer_key_only_when_bound() -> None:
    guest = SessionContext(
        session_record_id=UUID(int=1), role=SessionRole.CUSTOMER,
        merchant_id=MID, buyer_key=None, shop_slug="borough-100",
    )
    assert guest.is_bound is False
    bound = SessionContext(
        session_record_id=UUID(int=1), role=SessionRole.CUSTOMER,
        merchant_id=MID, buyer_key="bk-1", shop_slug="borough-100",
    )
    assert bound.is_bound is True


def test_merchant_context_must_not_carry_buyer_key() -> None:
    """商家会话带 buyer_key 属于契约错误，构造即失败。"""
    with pytest.raises(ValueError):
        SessionContext(
            session_record_id=UUID(int=1), role=SessionRole.MERCHANT,
            merchant_id=MID, buyer_key="bk-1", shop_slug=None,
        )


def test_context_is_frozen() -> None:
    """角色不可变（PRD §7.5 不变量 4）——在类型层面就不允许改。"""
    ctx = SessionContext(
        session_record_id=UUID(int=1), role=SessionRole.MERCHANT,
        merchant_id=MID, buyer_key=None, shop_slug=None,
    )
    with pytest.raises(Exception):
        ctx.role = SessionRole.CUSTOMER          # type: ignore[misc]


def test_buyer_alias_is_stable_per_merchant() -> None:
    """D7⑤：同一顾客在同一店铺别名稳定。"""
    assert buyer_alias(ALIAS_KEY, MID_A, "bk-1") == buyer_alias(ALIAS_KEY, MID_A, "bk-1")


def test_buyer_alias_is_not_cross_linkable_between_merchants() -> None:
    """D7⑤：不同商家无法串联识别同一顾客——这是别名的全部意义。"""
    assert buyer_alias(ALIAS_KEY, MID_A, "bk-1") != buyer_alias(ALIAS_KEY, MID_B, "bk-1")


def test_buyer_alias_does_not_leak_buyer_key() -> None:
    alias = buyer_alias(ALIAS_KEY, MID_A, "bk-1")
    assert "bk-1" not in alias
    assert len(alias) <= 16          # 短别名，形如「本店顾客 #a41f」的后缀
```

- [x] **步骤 2：确认失败**

```powershell
cd backend; uv run pytest tests/unit/core/test_session.py -v
```

期望：`ModuleNotFoundError: No module named 'app.core.session'`。

- [x] **步骤 3：实现 `session.py`**

要点：

- `new_session_token()` 用 `secrets.token_urlsafe(32)`，统一得到约 256 位随机性与无前缀的
  URL-safe 格式；内部记录主键仍使用 UUID，但不得把内部 UUID 当外部凭证；
- `token_fingerprint(token)` 返回 `hashlib.sha256(token.encode()).hexdigest()`；
  **库里只存指纹，永不存原值**，这样数据库泄露不等于会话被盗用；
- `issuer_fingerprint(demo_token)` 同法，用于 D8⑤ 的级联撤销；
- `SessionContext` 用 `@dataclass(frozen=True, slots=True)`，持有内部 `session_record_id: UUID`，
  **不持有明文 `session_id` 凭证**，避免下游日志、异常和工具展示意外泄漏；
  `__post_init__` 里校验「商家会话不得带 `buyer_key`」并 `raise ValueError`；
- `SessionAlreadyBoundError(RuntimeError)` 定义在本模块，Task 3 抛出、Task 4 转
  `409 SESSION_ALREADY_BOUND`；
- `buyer_alias(alias_key, merchant_id, buyer_key)` 实现 D7⑤，密钥显式注入而不是在纯函数内部
  隐式读取全局配置：
  `hmac.new(key, f"{merchant_id}:{buyer_key}", sha256).hexdigest()[:8]`，
  **key 按商家派生**（`hmac(BUYER_ALIAS_SECRET, merchant_id)`），这样不同商家对同一 `buyer_key`
  得到不同别名，无法串联。`BUYER_ALIAS_SECRET` 由 `Settings` 从环境变量读取（R6），不进代码；
  生产环境未配置或命中弱占位值时启动失败。该 Secret 的轮换会改变既有别名，本版不支持在线轮换，
  部署文档必须把它列为稳定持久配置。

本任务同步在 `Settings` 增加：

- `session_ttl_seconds: int = Field(default=86400, ge=300, le=2592000)`；
- `buyer_alias_secret: str | None`，生产环境必填且复用既有弱密钥检查；
- `demo_customer_identities: dict[str, str]`，由 `shop_slug` 映射服务端演示 `buyer_key`；它只供
  `SessionService` 使用，不通过演示身份入口或任何响应返回；
- `.env.example` 只放占位符，并同步 `AGENTS.md` R6 与 `docs/deployment.md`。

> **别名不是加密，是单向映射。** 它的作用是让商家能在自己店内识别"同一个人又来了"，
> 同时让两家商家拿各自的别名对不上账。不要试图从别名反解 `buyer_key`，也不要把它
> 当作可以公开的标识——它仍然是店内标识符，只是泄露后果比原值小。

- [x] **步骤 4：确认通过 + 静态检查**

```powershell
cd backend
uv run pytest tests/unit/core/test_session.py -v
uv run ruff check .; if ($?) { uv run mypy app }
```

期望：以上 10 个测试函数全部通过，ruff 与 mypy 全绿。

---

### Task 2：`agent_sessions` 表与迁移

**文件：**
- 创建：`backend/app/models/session.py`
- 修改：`backend/app/models/__init__.py`（导出新模型）
- 创建：`backend/migrations/versions/20260921_0017_agent_sessions.py`
  （修订号与链规则见数据迁移计划「迁移链与测试库规则」，两份计划共用一条线性链）

**接口：**
- 消费：Task 1 的 `SessionRole`
- 产出：`AgentSession` ORM

**表结构：**

| 列 | 类型 | 说明 |
| --- | --- | --- |
| `id` | UUID PK | 内部主键，**不是凭证** |
| `token_fingerprint` | `String(64)` UNIQUE NOT NULL | sha256(会话 ID)；**唯一索引，查询入口** |
| `role` | `String(16)` NOT NULL | `CUSTOMER` / `MERCHANT`，**建表后不允许 UPDATE** |
| `merchant_id` | UUID FK NOT NULL | 顾客会话存所属店铺的商家 |
| `buyer_key` | `String(64)` NULL | 仅顾客会话；访客为 `NULL` |
| `shop_slug` | `String(64)` NULL | 仅顾客会话 |
| `issuer_fingerprint` | `String(64)` NULL | 仅商家会话；D8⑤ 级联撤销用 |
| `created_at` / `updated_at` / `expires_at` | timestamptz NOT NULL | UTC；可变表按 §7.2 维护 `updated_at` |
| `revoked_at` | timestamptz NULL | 注销或被撤销 |

约束：

```sql
CHECK (role IN ('CUSTOMER','MERCHANT'))
CHECK (role <> 'MERCHANT' OR buyer_key IS NULL)      -- 商家会话不得有 buyer_key
CHECK (role <> 'MERCHANT' OR shop_slug IS NULL)
CHECK (role <> 'CUSTOMER' OR issuer_fingerprint IS NULL)
CHECK (role <> 'CUSTOMER' OR shop_slug IS NOT NULL)
CHECK (role <> 'MERCHANT' OR issuer_fingerprint IS NOT NULL)
```

索引：`token_fingerprint` UNIQUE；`(issuer_fingerprint)` 供级联撤销；
`(merchant_id, buyer_key)` 供顾客数据双重过滤连接。

- [x] **步骤 1：写 ORM 与迁移**

租户归属与签发来源在**数据库层**也要有保障：CHECK 约束只管单行取值，改不了
“签发后不得换角色、换店铺或换 issuer”。在迁移里加一个触发器：

```sql
CREATE OR REPLACE FUNCTION enforce_agent_session_identity_immutability() RETURNS trigger AS $$
BEGIN
  IF NEW.role IS DISTINCT FROM OLD.role THEN
    RAISE EXCEPTION 'agent_sessions.role 不可变（AGENTS.md §8.3）';
  END IF;
  IF NEW.merchant_id IS DISTINCT FROM OLD.merchant_id
     OR NEW.shop_slug IS DISTINCT FROM OLD.shop_slug
     OR NEW.issuer_fingerprint IS DISTINCT FROM OLD.issuer_fingerprint THEN
    RAISE EXCEPTION 'agent_sessions 的租户与签发来源不可变';
  END IF;
  IF OLD.buyer_key IS NOT NULL AND NEW.buyer_key IS DISTINCT FROM OLD.buyer_key THEN
    RAISE EXCEPTION '已绑定顾客会话不得切换 buyer_key';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_agent_session_identity_immutability
BEFORE UPDATE ON agent_sessions
FOR EACH ROW EXECUTE FUNCTION enforce_agent_session_identity_immutability();
```

**为什么不只靠应用层**：角色互换与会话跨商家改绑都是严重越权形态。
应用层的 frozen dataclass 只防住“这个进程里的代码”，触发器防住所有写入路径，
包括将来的修数据脚本和误操作。唯一允许的身份变化是顾客 `buyer_key: NULL → 服务端值` 一次。
迁移 downgrade 必须先删除 trigger，再删除 function 和表；升级—降级—再升级后不得残留对象。

- [x] **步骤 2：验证迁移可升可降**

```powershell
cd backend
uv run alembic upgrade head
uv run alembic downgrade -1
uv run alembic upgrade head
uv run alembic check
```

期望：四条全部成功，`alembic check` 无待生成变更。

- [x] **步骤 3：验证约束真的拦得住**

```powershell
cd backend; uv run pytest tests/integration/test_migrations.py -v
```

在该文件追加：商家带 `buyer_key`、顾客缺 `shop_slug`、商家缺 `issuer_fingerprint` 均违反 CHECK；
插入后 UPDATE `role` / `merchant_id` / `shop_slug` / `issuer_fingerprint`，以及已绑定后更换
`buyer_key` 均由触发器拒绝；首次 `buyer_key: NULL → 值` 必须允许。

---

### Task 3：会话签发、解析与注销

**文件：**
- 创建：`backend/app/repositories/session.py`
- 创建：`backend/app/services/session_service.py`
- 创建：`backend/tests/integration/repositories/test_session_repository.py`
- 创建：`backend/tests/unit/services/test_session_service.py`

**接口：**
- 消费：Task 1、Task 2
- 产出：

```python
class SessionRepository:
    async def issue_customer_guest(
        self, *, merchant_id: UUID, shop_slug: str, ttl_seconds: int | None = None,
    ) -> tuple[str, SessionContext]: ...
    async def bind_demo_customer(
        self, ctx: SessionContext, *, buyer_key: str,
    ) -> SessionContext: ...
    async def issue_merchant(
        self, mc: MerchantContext, *, issuer: str, ttl_seconds: int | None = None,
    ) -> tuple[str, SessionContext]: ...
    async def resolve(self, token: str) -> SessionContext | None: ...
    async def revoke(self, ctx: SessionContext) -> None: ...
    async def revoke_by_issuer(self, demo_token: str) -> int: ...
```

`SessionRepository` 只接受已经由服务端解析的 `merchant_id` / `buyer_key`。公开的 `shop_slug`
不能直接传到 Repository 决定租户；`SessionService.create_guest(shop_slug)` 必须先通过
`MerchantRepository` 把公开 slug 解析成可信商家，再调用 Repository。

`SessionService.bind_demo_customer(ctx)` 不接受请求体顾客 ID：它从演示模式配置解析当前店铺唯一的
服务端演示顾客 `buyer_key`，在同一个 `AsyncSession.begin()` 事务里锁定会话行、执行一次性绑定并调用
购物车合并端口。购物车合并的领域实现可以由交易任务提供，但本任务必须定义
`CartMergePort.merge_guest_into_buyer(...)` 协议与 Fake，证明失败时会话绑定也回滚。

`ttl_seconds` 省略时取配置默认（新增 `SESSION_TTL_SECONDS`，默认 `86400`）；
显式传值只用于测试构造过期会话。

`issue_merchant()` 实现 D8②：演示 Bearer Token **只用于换取会话**，此后 `merchant_id` 一律从会话解析。签发方法返回 `(明文会话 ID, SessionContext)`——**明文只在这一刻存在**，之后只剩指纹；
`SessionContext` 只保存内部 `session_record_id`。

### 规则

- `resolve()` 先计算 `token_fingerprint` 并按唯一索引查询；查询结果存在时再用
  `hmac.compare_digest(record.token_fingerprint, computed_fingerprint)` 做防御性最终比对；
- 过期、已注销、已撤销一律返回 `None`，调用方转 `401 SESSION_INVALID`——
  **三种情况对外不可区分**；
- `bind_demo_customer()` 是**一次性、事务性、幂等**的（D7⑥）：
  - 已绑定同一 `buyer_key` → 幂等返回，不报错；
  - 已绑定**不同** `buyer_key` → `409 SESSION_ALREADY_BOUND`；
  - 绑定与购物车合并在**同一事务**内完成，任一失败整体回滚；
- 并发绑定必须对会话行 `SELECT ... FOR UPDATE`，不得使用“先读后写”的竞态实现；
- `revoke_by_issuer()` 实现 D8⑤：撤销演示 Token 时，
  `UPDATE agent_sessions SET revoked_at=now() WHERE issuer_fingerprint=$1 AND revoked_at IS NULL`，
  返回受影响行数。该方法不能成为孤立 API：应用启动时以当前 `DEMO_MERCHANT_TOKENS` 集合与数据库
  现存 issuer 做一次对账，撤销已从配置移除的 issuer；同一进程内的受控配置刷新也调用同一服务。
  本版不新增公开撤销端点，环境变量变更经 Railway 重启生效。对账只比较指纹，不记录或回显原 Token。

- [x] **步骤 1：写失败测试**，至少覆盖：

```python
async def test_issued_token_is_not_stored_in_plaintext(repo, db) -> None:
    token, _ = await repo.issue_customer_guest(
        merchant_id=MERCHANT_ID, shop_slug="borough-100"
    )
    rows = (await db.execute(select(AgentSession))).scalars().all()
    dumped = str([r.__dict__ for r in rows])
    assert token not in dumped        # 明文永不落库


async def test_expired_revoked_and_missing_are_indistinguishable(repo) -> None:
    assert await repo.resolve("never-issued") is None
    t_exp, _ = await repo.issue_customer_guest(
        merchant_id=MERCHANT_ID, shop_slug="s", ttl_seconds=-1
    )
    assert await repo.resolve(t_exp) is None
    t_rev, ctx = await repo.issue_customer_guest(merchant_id=MERCHANT_ID, shop_slug="s")
    await repo.revoke(ctx)
    assert await repo.resolve(t_rev) is None


async def test_rebinding_same_buyer_is_idempotent(repo) -> None:
    _, ctx = await repo.issue_customer_guest(merchant_id=MERCHANT_ID, shop_slug="s")
    a = await repo.bind_demo_customer(ctx, buyer_key="bk-1")
    b = await repo.bind_demo_customer(a, buyer_key="bk-1")
    assert a.buyer_key == b.buyer_key


async def test_rebinding_different_buyer_is_rejected(repo) -> None:
    _, ctx = await repo.issue_customer_guest(merchant_id=MERCHANT_ID, shop_slug="s")
    bound = await repo.bind_demo_customer(ctx, buyer_key="bk-1")
    with pytest.raises(SessionAlreadyBoundError):
        await repo.bind_demo_customer(bound, buyer_key="bk-2")


async def test_revoking_demo_token_cascades(repo) -> None:
    """D8⑤：撤销 Token 时由它换取的全部会话同步失效。"""
    t1, _ = await repo.issue_merchant(MC, issuer="demo-token-A")
    t2, _ = await repo.issue_merchant(MC, issuer="demo-token-A")
    t3, _ = await repo.issue_merchant(MC, issuer="demo-token-B")
    assert await repo.revoke_by_issuer("demo-token-A") == 2
    assert await repo.resolve(t1) is None
    assert await repo.resolve(t2) is None
    assert await repo.resolve(t3) is not None
```

- [x] **步骤 2：确认失败 → 实现 → 确认通过**

```powershell
cd backend
uv run pytest tests/integration/repositories/test_session_repository.py -v
uv run pytest tests/unit/services/test_session_service.py -v
```

服务测试还必须覆盖：`shop_slug` 不存在时不创建会话、请求体不能覆盖身份、并发绑定不同身份只有一方
生效、购物车合并失败时 `buyer_key` 保持 `NULL`、同一身份重试不重复合并。

---

### Task 4：FastAPI 依赖与角色守卫

**文件：**
- 创建：`backend/app/api/session_deps.py`（含 `get_session_repository` 依赖工厂）
- 修改：`backend/app/core/errors.py`（若契约计划 Task 1 尚未加这些码，在此补）
- 修改：`backend/app/localization/error_messages.py`
- 修改：`backend/app/repositories/audit.py`、`backend/app/repositories/protocols.py`

**管理员不进会话体系**（D8⑥⑦）：`/api/admin/*` 继续只认 `X-Admin-Token`，
`VIEWER_TOKEN` 只读范围不变。本任务**不得**给管理端点加会话依赖，
也不得让 `X-Session-Id` 在管理端点上产生任何效果。

**接口：**
- 产出：`require_customer_session`、`require_merchant_session`、`require_bound_customer_session`

```python
async def require_customer_session(
    session_id: Annotated[str | None, Header(alias="X-Session-Id")] = None,
    repo: SessionRepository = Depends(get_session_repository),
) -> SessionContext:
    """顾客会话守卫。角色不符一律 403 + 审计，不降级为 401。"""
```

### 规则

- 缺头 → `401 SESSION_REQUIRED`；解析失败 → `401 SESSION_INVALID`；
- **角色不符 → `403 SESSION_ROLE_MISMATCH` + 写 `audit_logs`**（D8③），
  绝不因为"反正也没权限"就返回 401——401 意味着"换个凭证再来"，
  403 才是"你这个身份不该碰这里"，两者的审计含义完全不同；
- `require_bound_customer_session` 在顾客会话基础上要求 `is_bound`，
  未绑定返回单独的稳定 403 语义，**不得复用 `SESSION_ROLE_MISMATCH`**——访客和已绑定顾客的
  role 都是 `CUSTOMER`。契约计划若尚无合适错误码，先在 §8.7.2 增加
  `CUSTOMER_BINDING_REQUIRED`，再同步唯一 `ErrorCode` 与双语文案；
- 依赖**不接受**任何来自请求体、查询参数或其他请求头的 `merchant_id` / `buyer_key`（D7②：顾客端不得提交或覆盖 `buyer_key`，模型也不能决定身份）。
- 审计使用内部 `session_record_id`、角色、当前商家、端点、结果码与 request ID；不得记录明文
  `X-Session-Id`、`buyer_key`、请求正文或被拒字段值。
- 会话签发/绑定响应必须带 `Cache-Control: no-store`；结构化日志、异常上下文与 tracing baggage
  对 `X-Session-Id` 做全量脱敏。该响应头与脱敏测试在 Task 7 创建路由时作为完成门槛登记。

- [x] **步骤 1：写失败测试** — 缺头 401、乱填 401、顾客调商家 403+审计、
  商家调顾客 403+审计、未绑定顾客调演示顾客端点 `CUSTOMER_BINDING_REQUIRED`，以及审计中不含
  明文 session token / `buyer_key`。

- [x] **步骤 2：确认失败 → 实现 → 确认通过**

- [x] **步骤 3：验证 v1 未受影响**

```powershell
cd backend; uv run pytest tests/api/ -v
```

期望：既有 API 测试**全绿，零回归**。v1 的 Bearer 路径不得因本任务改变行为。

---

### Task 5：统一 403 非枚举响应

**这是 PRD §12.1 的安全硬门禁，零失败才算通过。**

**文件：**
- 创建：`backend/app/services/resource_scope.py`
- 创建：`backend/tests/integration/test_session_isolation.py`
- 创建：`backend/tests/support/scope_probe.py`（仅测试用 FastAPI 探针与临时表 Repository）

### 规则

由于订单、草稿和售后 v2 路由不在本计划实现，当前门禁使用 `tests/support/scope_probe.py`：它挂载
一个仅测试可见的 `/scope-probe/{id}` 路由，调用真实 `require_owned()`、真实异常处理器和真实 PostgreSQL
临时表。探针模块不得被 `app/` 导入或进入生产路由；业务端点落地时仍须追加真实端点门禁。

「目标不存在」与「目标存在但不属于当前主体」必须**逐字段一致**（O1、D7⑦、AGENTS.md R5）：

| 维度 | 要求 |
| --- | --- |
| HTTP 状态码 | **403**（不是 404） |
| `code` | `RESOURCE_FORBIDDEN`——**名字不得暗示存在性**，不叫 `*_NOT_FOUND` |
| `message` | 同一段文本，不含对象类型、ID 或任何可区分线索 |
| `details` | `[]` |
| **响应耗时** | 两条路径耗时不得出现系统性差异 |

耗时那条是 O1 明确点名的。实现约束：

- **两条路径都必须完整执行同一次查询**。不允许"先查存在性、不存在就早退"——
  早退路径天然更快，构成时序侧信道；
- 统一走 `resource_scope.require_owned()`：Repository 用**一条固定形状 SQL**同时返回
  `resource` 与仅供审计的 `target_exists`；不得先查存在性再做第二次主体查询；
- `resource is None` 时统一写审计并抛同一个 `ResourceForbiddenError`。审计可以把原因最小化记录为
  `MISSING` / `FOREIGN`，但原因不得进入异常、响应或普通访问日志；
- 若某 Repository 无法在单条固定查询中安全区分原因，审计统一记录 `NOT_VISIBLE`，不得为了细分日志
  增加热路径探测。

```python
@dataclass(frozen=True)
class ScopeLookupResult[T]:
    resource: T | None
    target_exists: bool | None  # None 表示该仓储只知道 NOT_VISIBLE


async def require_owned[T](
    fetch: Callable[[], Awaitable[ScopeLookupResult[T]]],
    *,
    ctx: SessionContext,
    audits: AuditRepositoryProtocol,
    resource_type: str,
    resource_id: str,
    request_id: str,
) -> T:
    """一次固定查询定生死；对外统一 403，不二次探测存在性。"""
```

- [x] **步骤 1：写安全硬门禁测试**

```python
async def test_missing_and_foreign_resources_are_field_identical(scope_probe_client) -> None:
    """测试专用探针走真实异常处理器；业务 v2 路由落地后复制为端到端门禁。"""
    headers = {**CUSTOMER_A, "X-Request-Id": "scope-parity-probe"}
    missing = await scope_probe_client.get(f"/scope-probe/{MISSING_ID}", headers=headers)
    foreign = await scope_probe_client.get(f"/scope-probe/{FOREIGN_ID}", headers=headers)
    assert missing.status_code == foreign.status_code == 403
    assert missing.json() == foreign.json()          # 同 request_id 下逐字段一致
    assert missing.json()["code"] == "RESOURCE_FORBIDDEN"
    assert missing.json()["details"] == []


async def test_cross_merchant_access_is_forbidden_and_audited(scope_probe_client, db) -> None:
    resp = await scope_probe_client.get(
        f"/scope-probe/{FOREIGN_ID}", headers={**MERCHANT_A, "X-Request-Id": "audit-probe"}
    )
    assert resp.status_code == 403
    rows = (
        await db.execute(select(AuditLog).where(AuditLog.event_type == "RESOURCE_SCOPE_VIOLATION"))
    ).scalars().all()
    assert len(rows) == 1
    metadata = str(rows[0].event_metadata)
    assert RAW_SESSION_TOKEN not in metadata
    assert BUYER_A_KEY not in metadata


async def test_customer_queries_always_double_filter(scope_probe_repository) -> None:
    """D7①：订单、退款、售后强制 merchant_id + buyer_key 双重过滤。"""
    rows = await scope_probe_repository.list_for_customer(
        merchant_id=MERCHANT_A_ID, buyer_key=BUYER_A_KEY
    )
    ids = {row.id for row in rows}
    assert ORDER_OF_CUSTOMER_B not in ids
    assert ORDER_OF_SAME_BUYER_OTHER_SHOP not in ids   # 跨店也要挡
```

- [x] **步骤 2：时序一致性检查**

```python
import os


@pytest.mark.security_timing
@pytest.mark.skipif(
    os.getenv("REQUIRE_SECURITY_TIMING") != "1",
    reason="时序哨兵只在独占 PostgreSQL 的 security-timing job 中运行",
)
async def test_no_timing_side_channel(scope_probe_client) -> None:
    """PRD §12.1：独占 PostgreSQL 中各 500 次，中位数差 <=10ms，p95 比 0.8–1.25。"""
    import statistics
    import time

    async def one(url: str) -> float:
        t0 = time.perf_counter_ns()
        response = await scope_probe_client.get(url, headers=CUSTOMER_A)
        assert response.status_code == 403
        return (time.perf_counter_ns() - t0) / 1_000_000

    # 先预热相同查询计划，再交替采样，降低连接池、缓存和机器漂移造成的偏差。
    for _ in range(20):
        await one(MISSING_URL)
        await one(FOREIGN_URL)

    missing_ms: list[float] = []
    foreign_ms: list[float] = []
    for _ in range(500):
        missing_ms.append(await one(MISSING_URL))
        foreign_ms.append(await one(FOREIGN_URL))

    median_delta = abs(statistics.median(missing_ms) - statistics.median(foreign_ms))
    missing_p95 = statistics.quantiles(missing_ms, n=100)[94]
    foreign_p95 = statistics.quantiles(foreign_ms, n=100)[94]
    assert median_delta <= 10.0
    assert 0.8 <= missing_p95 / foreign_p95 <= 1.25
```

这仍是工程回归门禁，不是密码学常量时间证明。测试必须运行在本地独占 PostgreSQL 与固定连接池配置下，
由单独的 `security-timing` CI job 设置 `REQUIRE_INTEGRATION_DB=1` 执行；该 job 不允许 skip / xfail。
在 `backend/pyproject.toml` 登记 `security_timing` marker；专用 job 还必须设置
`REQUIRE_SECURITY_TIMING=1`，并用 `pytest -rs` 检查该用例没有被跳过。仓库尚未落地 CI 配置时，
先把下方命令作为 N1 本地发布门禁，**不得把“计划要求有 job”误报为“CI 已存在”**。
普通共享 CI 的抖动结果不得替代此门禁。订单、草稿和售后 v2 路由各自落地时，必须把同一套断言复制到
真实端点；测试探针通过不能替代业务路由验收。

- [x] **步骤 3：确认失败 → 实现 → 确认通过**

```powershell
cd backend
$env:REQUIRE_INTEGRATION_DB=1
uv run pytest tests/integration/test_session_isolation.py -v -m "not security_timing"
$env:REQUIRE_SECURITY_TIMING=1
uv run pytest tests/integration/test_session_isolation.py -v -rs -m security_timing
```

期望：全部通过，**零失败**。这是硬门禁，不允许 skip 或 xfail。

---

### Task 6：来源状态隔离（O2）

对应 D8④ / O2：**一个对话取得的对象访问资格不得扩散到其他对话。**

**文件：**
- 创建：`backend/app/models/provenance.py`
- 创建：`backend/app/repositories/provenance.py`
- 创建：`backend/migrations/versions/20260921_0018_conversation_provenance.py`
  （**单独一个修订，不回头改 `0017`**——执行过 `upgrade` 的迁移不再修改，见数据迁移计划的链规则）
- 创建：`backend/tests/integration/repositories/test_provenance.py`

### 规则

- 表 `conversation_provenance` 的唯一键是
  `(principal_kind, principal_id, merchant_id, conversation_id, object_type, object_id)`；
  `principal_id` 使用内部 `session_record_id`（访客）或稳定主体摘要（已绑定顾客/商家），不得保存明文
  session token 或原始 `buyer_key`；`object_type` 防止不同资源类型恰好同 ID 时串权；
- 每行还包含 `version`、`first_seen_at`、`last_seen_at`，全部经营与主体字段非空；
- 带**版本号**防并发覆盖：写入用条件更新（`WHERE version = $expected`），
  失败则重读并最多重试 3 次，不做无限循环或盲写；
- 新建对话时来源状态**从空开始**；
- 登录会话只负责身份认证，**不携带任何对象访问资格**。
- 删除对话时同事务删除其来源状态；会话注销不删除业务对话，但访客会话过期且没有绑定身份时，
  由 Cron 清理其不可再使用的来源状态。

- [x] **步骤 1：写失败测试**

```python
async def test_provenance_does_not_leak_across_conversations(repo) -> None:
    await repo.record(principal=P, shop="s1", conversation="c1", object_type="PRODUCT", object_id="p-9")
    assert await repo.has(principal=P, shop="s1", conversation="c1", object_type="PRODUCT", object_id="p-9")
    assert not await repo.has(principal=P, shop="s1", conversation="c2", object_type="PRODUCT", object_id="p-9")


async def test_provenance_does_not_leak_across_shops(repo) -> None:
    await repo.record(principal=P, shop="s1", conversation="c1", object_type="PRODUCT", object_id="p-9")
    assert not await repo.has(principal=P, shop="s2", conversation="c1", object_type="PRODUCT", object_id="p-9")


async def test_provenance_does_not_collide_across_object_types(repo) -> None:
    await repo.record(principal=P, shop="s1", conversation="c1", object_type="PRODUCT", object_id="same")
    assert not await repo.has(
        principal=P, shop="s1", conversation="c1", object_type="ORDER", object_id="same"
    )


async def test_concurrent_write_is_resolved_by_version(repo) -> None:
    await asyncio.gather(
        repo.record(principal=P, shop="s1", conversation="c1", object_type="PRODUCT", object_id="p-1"),
        repo.record(principal=P, shop="s1", conversation="c1", object_type="PRODUCT", object_id="p-2"),
    )
    assert await repo.has(principal=P, shop="s1", conversation="c1", object_type="PRODUCT", object_id="p-1")
    assert await repo.has(principal=P, shop="s1", conversation="c1", object_type="PRODUCT", object_id="p-2")
```

- [x] **步骤 2：确认失败 → 实现 → 确认通过**

```powershell
cd backend; $env:REQUIRE_INTEGRATION_DB=1; uv run pytest tests/integration/repositories/test_provenance.py -v
```

---

### Task 7：会话签发路由与 §8.0.1 同步

**2026-09-21 用户裁定并入本计划。** 此前本计划只产出仓储、服务与依赖守卫，5 条会话签发路由没有任何计划负责实现，
而 N1 评测计划 Task 2 的 `SEC-CROSS-001` 要真实 HTTP 调用 `POST /api/v2/shop/sessions/demo-customer`，
N2 两份前端计划也把这些路由写成入口条件。这 5 条是 **N1 内唯一落地的 v2 路由**；其余 v2 路由仍归 N2 及之后。

**前置：** Task 1–5 已完成；字段契约 §8.8.2 / §8.9.2 已冻结（模块 A），满足 §8.0.1 的路由创建前置条件。

**路由（字段、状态码与错误码逐字以契约为准，不在本计划复写）：**

| 方法与路径 | 契约 | 依赖 / 服务 |
| --- | --- | --- |
| `POST /api/v2/shop/sessions` | §8.8.2 | 公开；`SessionService.create_guest(shop_slug)` |
| `POST /api/v2/shop/sessions/demo-customer` | §8.8.2 | `require_customer_session`；`SessionService.bind_demo_customer(ctx)` |
| `DELETE /api/v2/shop/sessions/current` | §8.8.2 | `require_customer_session`；`SessionRepository.revoke` |
| `POST /api/v2/merchant/sessions` | §8.9.2 | v1 既有演示 Token 解析（不改其行为）；`SessionRepository.issue_merchant` |
| `DELETE /api/v2/merchant/sessions/current` | §8.9.2 | `require_merchant_session`；`SessionRepository.revoke` |

### 规则

- 请求/响应模型只用 `app.schemas.v2.shop_session` / `merchant_session` 已有模型，**不新建第二套 Schema**；
- 签发与绑定响应带 `Cache-Control: no-store`（Task 4 规则）；
- `POST /shop/sessions` 与 `POST /merchant/sessions` 接入既有 `enforce_rate_limit`，超限返回 `429 RATE_LIMITED`；
- `demo-customer` 在 `DEMO_DEPLOYMENT_MODE=false` 时返回契约规定的 `404 NOT_FOUND`，不泄露演示身份是否存在；
- **购物车合并在 N1 只接端口**：购物车表要到 `n2-trade-closed-loop` 才存在。本任务在生产装配中注入
  `EmptyCartMerge`（显式命名，只返回“无可合并项”，不伪造成功合并的数据），并用依赖注入暴露端口；
  `n2-trade-closed-loop` Task 2 负责换成真实实现。**不得在路由里内联合并逻辑**；`EmptyCartMerge` 恒返回
  `cart_adjusted=false`，绑定响应按契约 §8.8.1 带该字段；
- 路由只从 `SessionContext` 读身份，请求体、查询参数、其他请求头中的 `merchant_id` / `buyer_key` 一律拒绝（`extra="forbid"` 已保证）；
- v1 `MerchantContext`、`resolve_demo_token` 与 v1 路由行为不变。

- [x] **步骤 1：写失败测试**（`tests/api/v2/test_session_routes.py`，真实 PostgreSQL）——至少覆盖：
  5 条路由的成功状态码与响应字段；签发/绑定响应含 `Cache-Control: no-store`；注销后同一凭证 `401 SESSION_INVALID`；
  商家会话调 `POST /shop/sessions/demo-customer`、顾客会话调 `DELETE /merchant/sessions/current` 均 `403 SESSION_ROLE_MISMATCH`
  且写审计、无副作用；改绑不同身份 `409 SESSION_ALREADY_BOUND`；未知 `shop_slug` 不创建会话；
  请求体携带 `merchant_id` / `buyer_key` 返回 422；演示模式关闭时 `demo-customer` 返回 404；
  日志与审计中不出现明文 `X-Session-Id`；撤销演示 Token 后其换取的商家会话 401。

- [x] **步骤 2：确认失败 → 实现路由并在 `app/api/router.py` 挂载 → 确认通过**

```powershell
cd backend; $env:REQUIRE_INTEGRATION_DB=1; uv run pytest tests/api/v2/test_session_routes.py -v
```

- [x] **步骤 3：§8.0.1 门槛 2–3：导出 OpenAPI 并重新生成类型**

```powershell
cd backend; uv run python ../scripts/export_openapi.py   # 仓库根没有 pyproject.toml，必须从 backend 运行
cd ../frontend; npm run codegen; npm run codegen:check
```

期望：`docs/api.json` 新增且只新增这 5 条 v2 路径；v1 路径与 Schema 无差异；`codegen:check` 通过。
`shop/` 顾客端工程要到 N2 才创建，其生成类型由 `n2-shop-nextjs-app` 建工程时从同一份 `docs/api.json` 生成，本任务不建。

- [x] **步骤 4：§8.0.1 门槛 4：商家会话 Adapter**

新建 `frontend/src/api/adapters/session.ts` 与 spec：只封装 `POST /merchant/sessions`（Bearer）与
`DELETE /merchant/sessions/current`（`X-Session-Id`），把 `generated.ts` 类型转成领域类型，契约测试覆盖成功与
`401 AUTH_REQUIRED` / `SESSION_INVALID` 的错误映射。**不接 Store、不改页面**——Store 接入与切换商家流程属于
`n2-merchant-vue-v2-migration` Task 2。

```powershell
cd frontend; npm run test -- src/api/adapters/session.spec.ts
```

- [x] **步骤 5：§8.0.1 门槛 5 与安全用例登记**

新增 OpenAPI 哨兵测试（`backend/tests/api/test_openapi_chat_contract.py` 同类）：5 条路径的方法、鉴权头与
响应模型名固定。确认 N1 评测计划 Task 2 中以这些路由为目标的用例（如 `SEC-CROSS-001`）引用的路径与本任务一致，
**PRD §15 N1 要求 v2 路由上线时同时登记安全用例**。

```powershell
cd backend; uv run pytest tests/api/ -v
```

期望：全绿，v1 API 测试零回归。

---

### Task 8：契约补写与自检

- [x] **步骤 1：在 `docs/backend-development-plan.md` 新增 §6.16 Session Identity**

按 §6.1 的 `输入 / 输出 / 规则 / 必测` 体例，把本计划的接口、状态机与不变量写成模块契约。
**放在 §6.15 之后、§7 之前，不改动 §7 及以后的编号。**

- [x] **步骤 2：禁用模式扫描**

```powershell
cd backend
rg -n "merchant_id|buyer_key" app/api/session_deps.py
```

期望：只出现在从 `SessionContext` 读取的位置，**不出现在任何 `Header(...)` /
`Query(...)` / 请求体模型中**。

```powershell
rg -n "404" app/services/resource_scope.py
```

期望：零命中（非枚举响应一律 403）。

```powershell
rg -n "BUYER_ALIAS_SECRET|buyer_alias_secret" app/ ../.env.example
```

期望：只在 Settings、显式依赖注入与占位文档处出现，**无硬编码默认值**（R6）。生产环境未配置时
启动即失败，不得回退到固定字符串——那等于所有部署共用同一个别名空间，别名的隔离意义随之消失。

```powershell
rg -n "X-Session-Id|session_id" app/core/logging.py app/api/ app/services/ | rg -n "log|event|metadata|exception"
```

逐条检查命中：不得把凭证值写入日志、审计 metadata、异常消息或 tracing；只允许读取 Header、
设置 `Cache-Control: no-store` 以及返回签发响应字段。

- [x] **步骤 3：全量回归**

```powershell
cd backend
uv run pytest
uv run ruff check .
uv run mypy app
```

期望：不低于 2026-09-09 基线的 **1128 passed**，新增用例计入增量，**v1 零回归**。

- [x] **步骤 4：真实数据库验证**

```powershell
cd backend; $env:REQUIRE_INTEGRATION_DB=1; uv run pytest tests/integration/ -v
```

期望：全绿。触发器与 CHECK 约束只有在真实 PostgreSQL 上才生效，
**Fake 仓储测试通过不代表约束有效**——这是 `docs/project-progress.md` 记录过的教训。

- [x] **步骤 5：更新进度快照**

替换 `docs/project-progress.md` 的当前验证快照，记录：已实现的会话能力、安全硬门禁用例数与通过情况、
**未执行 Git 提交、发布或历史改写操作**、**未调用真实 LLM**。不得追加每日流水账。

---

## 本计划明确不做的事

| 不做 | 归属 |
| --- | --- |
| v2 业务路由（订单、购物车、草稿等）；本计划只落地 5 条会话签发路由（Task 7） | 各组路由实现任务 |
| 购物车合并的具体实现 | `n2-trade-closed-loop` Task 2（本计划只定义端口、事务边界与幂等语义，生产装配 `EmptyCartMerge`） |
| 顾客端 `shop/` 生成类型与会话 Adapter | `n2-shop-nextjs-app`（建工程时从同一份 `docs/api.json` 生成） |
| 商家端会话 Store、切换商家流程与页面接入 | `n2-merchant-vue-v2-migration` Task 2 |
| 下线 v1 的 Bearer 路径 | v2 前端切换完成后 |
| 真实 SSO、账号密码、JWT | 不在本版范围（D7④） |
| MCP 凭证 | N5（独立凭证体系，不复用会话） |
