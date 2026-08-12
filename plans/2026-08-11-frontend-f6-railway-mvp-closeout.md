# F6「Railway 部署就绪」实施计划（第 2 稿）

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**状态：第 2 稿，待用户审阅。未开始执行。**

**Goal:** 让 Borough 商家助手具备可部署到 Railway 并完成线上验收的条件——补齐生产环境下的演示身份通路、修正会污染用量计数的预扣缺陷、把 ECharts 移出首屏网络路径、为生产构建加上 Mock 与密钥的机械防线，并给出可照做的部署手册与两轮线上验收清单。

**Architecture:** 分三段。**F6-0** 是两个后端前置切片，不做完 F6-B 无法执行。**F6-A** 是纯前端与构建配置，本地可完成。**F6-B** 依赖用户在 Railway 控制台操作。每项新增能力都落成可重复执行的门禁，而不是一次性人工观察。

**Tech Stack:** Python 3.12、FastAPI、Pydantic v2、SQLAlchemy 2、Vue 3、TypeScript、Vite、Vitest、Playwright、ECharts、Caddy、Docker、Railway。

## 出口范围的重要限定

**本计划的出口是「F6 完成 / Railway 部署就绪」，不是「MVP 完成」。** 完成本计划后**不得**把 `AGENTS.md` 或进度快照改成「MVP 完成」，理由有三条，每条都有据可查：

1. **还原度审计仍有未处理的红色缺口**，其中 `docs/yshopping-parity-audit.md` §3.6「思考过程只渲染最后一步」是纯前端缺口，本计划不解决它（它归 R9 阶段 B Task 8）。
2. **PRD 要求一次真实模型意图准确率评估**：`docs/PRD.md:101` 规定该指标 **≥ 90%**、是人工验收项，`docs/PRD.md:997` 把它列在 M4。两道手选问题得不出准确率。
3. **PRD §16 的完整出口**涵盖四业务域、规则问答、连续追问、预算熔断与限流，两次线上提问远不足以覆盖。

因此 Task 12 只产出**证据矩阵**，如实标注每条出口是「已验证 / 未验证 / 已裁定偏离」，把判断留给用户。

## Global Constraints

- 面向用户的文案、错误提示、日志与文档使用中文；代码标识符使用英文。
- 不修改只读目录 `yshopping-merchant-ai 4/`；只作行为对照。
- 不执行 `git commit`、`git push`、`git tag` 或 PR 操作（AGENTS.md R2）。每个任务以检查 diff 收尾。
- 不手改 `frontend/src/api/generated.ts`、`docs/api.json`、`docs/api.md` 与生成 fixture；契约变化后用脚本重新生成。
- 网络拓扑固定为「Backend 公开 + 严格 CORS」：前端容器不代理 `/api`；`VITE_API_BASE_URL` 缺失必须响亮失败。
- 真实 LLM 固定为 DeepSeek，模型 `deepseek-v4-flash`，`LLM_BASE_URL` 固定为 `https://api.deepseek.com`。
- **F6-0 与 F6-A 全程零 DeepSeek 网络请求。** F6-B 第一轮零网络请求；第二轮是 **2 次聊天请求、真实模型调用上限 12 次**（见 Task 12 的 R3 说明），执行前必须获得用户明确同意。
- 商家隔离不可削弱：新增的演示部署模式只放开**演示 Token → 演示商家**这一条既有通路，不得引入任何绕过 `merchant_id` 强制注入的路径。
- 每个生产行为先写失败测试并确认失败原因，再写最小实现。

---

## 一、第 1 稿的阻塞缺陷与本稿的处置

第 1 稿经评审发现 6 个阻塞缺陷，全部经代码或官方文档核实属实。本稿逐条处置：

| # | 缺陷 | 核实依据 | 本稿处置 |
| --- | --- | --- | --- |
| 1 | Railway 配置文件**不**跟随 Root Directory | Railway 官方文档原文：*"The Railway Config File does not follow the Root Directory path. You have to specify the absolute path for the railway.json or railway.toml file, for example: /backend/railway.toml"* | Task 10 明确要求在控制台把 Config File Path 分别设为 `/frontend/railway.json` 与 `/backend/railway.json`，并作为部署前置校验项 |
| 2 | 生产强制关演示端点，前端身份无来源 | `backend/app/core/config.py:112` 在 PRODUCTION 下硬置 `demo_merchants_endpoint_enabled = False`；`frontend/src/stores/auth.ts:19` 的 `loadMerchants()` 唯一来源就是该端点 | 按用户 2026-08-11 裁决，新增**显式演示部署模式**（Task 1），保留全部生产安全校验 |
| 3 | 「2 次真实调用」口径错误 | `llm_max_calls_per_request` 默认 **6**；单轮问答的调用点在 `app/intent/service.py:52`、`app/agent/graph.py:332`、`app/agent/graph.py:393` | 改为「2 次聊天请求，模型调用上限 12 次」，验收按 `llm_usage` 实际值核对，不再断言等于 2 |
| 4 | 「零调用」Fake 轮仍消耗预算与计数 | `LlmCostGuard.complete()` 先 `reserve()` 再触底层客户端；`LlmBudgetRepository.reserve` 的 SQL 含 `call_count = call_count + 1` | 先修后端（Task 2）：客户端未配置时直接拒绝、不进预扣 |
| 5 | `defineAsyncComponent` 首帧即触发 loader | 模板中 `<MetricChartPanel>` 无条件渲染，首次渲染即执行 loader；随后的 `requestIdleCallback` 只是命中同一个在飞 Promise | 改为显式挂载开关 `chartMountable`（Task 4），并用 Playwright 真实观测首屏网络请求作为证据 |
| 6 | Railway 传不进 `VITE_USE_MOCK` | `frontend/Dockerfile` 只声明 `ARG VITE_API_BASE_URL`（第 17 行） | Task 5 把 Dockerfile 纳入修改范围，显式声明该 ARG |

实施层同步修正：不再使用未安装的 `@pinia/testing`；脚本路径统一 `fileURLToPath`；`.env.production` 因命中 `frontend/.gitignore:12` 的 `.env.*` 而在 `git status` 中不可见，改用 `Test-Path` 校验；文档卫生检查排除 `AGENTS.md:257` 的参考项目只读路径；统一 `ADMIN_TOKEN` 的配置时点；门禁条数按实际列举。

## 二、现状核对（2026-08-11 实测，不要重做）

| F6 原清单条目 | 状态 | 证据 |
| --- | --- | --- |
| 前端容器不代理 `/api` | ✅ 完成 | `frontend/Caddyfile` 对 `/api/*` 显式 404 |
| `VITE_API_BASE_URL` 平台注入 | ✅ 完成 | `Dockerfile:17` ARG；`src/api/client.ts` 无同源回退 |
| 静态健康响应 | ✅ 完成 | `public/health.html` + Caddy 独立 handle |
| ECharts 按需引入 | ✅ 完成 | `useEChart.ts` 用 `echarts/core` + 显式 `use([...])` |
| 路由级代码分割 | ✅ 完成 | `/knowledge-base` 已 lazy；`/` 是首屏，eager 正确 |
| ECharts 独立 chunk | ✅ 完成 | `vite.config.ts` 已配 `manualChunks` |
| 长会话虚拟列表 | ✅ 明确不做 | F6 清单原文即「MVP 不提前实现」 |
| **ECharts 退出首屏网络路径** | ❌ 未完成 | `dist/index.html` 预加载 `echarts-*.js`（544K） |
| **生产构建关闭 Mock** | ⚠️ 仅事后扫描 | `mock:check` 挡不住 `VITE_USE_MOCK=true` |
| **构建产物无密钥检查** | ❌ 缺失 | 仅靠人工 |
| **前端 Railway 配置即代码** | ❌ 缺失 | 后端有 `backend/railway.json`，前端无 |

**基线数字：** `index-*.js` 213K、`echarts-*.js` 544K、`index-*.css` 31K；Vitest 238 passed（25 文件）；Mock Playwright 25 passed；后端真实库 709 passed。

---

# 阶段 F6-0：后端前置切片

> 这两个切片必须先于 F6-B 完成。它们改 `backend/app/**`，是本计划中唯一触碰后端生产代码的部分。

### Task 1: 显式演示部署模式

**Files:**
- Modify: `backend/app/core/config.py`
- Modify: `backend/app/api/routes/admin.py`
- Test: `backend/tests/unit/core/test_config.py`
- Test: `backend/tests/api/test_demo_merchants.py`
- Test: `backend/tests/api/test_admin_ops.py`

**Interfaces:**
- Produces: `Settings.demo_deployment_mode: bool`（环境变量 `DEMO_DEPLOYMENT_MODE`，默认 `False`）。
- Invariant: 生产环境下演示端点**默认仍然关闭**；只有显式开启该开关才放行，且开启状态必须在运维端点可见。

**背景：** `config.py:112` 在 PRODUCTION 下硬置 `demo_merchants_endpoint_enabled = False`，而 `frontend/src/stores/auth.ts:19` 的 `loadMerchants()` 是前端获得商家身份的唯一来源。线上因此无法完成商家选择、刷新恢复与跨商家隔离验收。用户于 2026-08-11 裁决：保留全部生产安全校验，另加一个必须显式开启、且可被观测到的演示模式开关。

- [ ] **Step 1: 写配置层失败测试**

在 `backend/tests/unit/core/test_config.py` 增加：

```python
def test_production_keeps_demo_endpoint_closed_by_default() -> None:
    settings = make_settings(
        app_env=AppEnvironment.PRODUCTION,
        export_signing_secret="a-secure-export-signing-secret",
        demo_merchants_endpoint_enabled=True,
    )

    assert settings.demo_merchants_endpoint_enabled is False


def test_production_opens_demo_endpoint_only_with_explicit_deployment_mode() -> None:
    settings = make_settings(
        app_env=AppEnvironment.PRODUCTION,
        export_signing_secret="a-secure-export-signing-secret",
        demo_deployment_mode=True,
    )

    assert settings.demo_deployment_mode is True
    assert settings.demo_merchants_endpoint_enabled is True


def test_demo_deployment_mode_defaults_to_false() -> None:
    settings = make_settings(app_env=AppEnvironment.PRODUCTION,
                             export_signing_secret="a-secure-export-signing-secret")

    assert settings.demo_deployment_mode is False
```

第一条是防回归的关键：**默认必须仍然关闭**。少了它，后面的实现可以用「生产一律放行」蒙混过关。

- [ ] **Step 2: 运行并确认因字段不存在而失败**

Run: `uv run pytest tests/unit/core/test_config.py -q`

Expected: 因 `Settings` 无 `demo_deployment_mode` 字段而失败。

- [ ] **Step 3: 实现配置字段与放行逻辑**

在 `config.py` 的字段区（`demo_merchants_endpoint_enabled` 附近）加入：

```python
    # 生产环境默认关闭演示端点。演示部署（对外展示用）必须显式开启这一项，
    # 而不是靠把 APP_ENV 降级成非生产来绕过——后者会同时关掉导出签名密钥必填、
    # 管理员令牌必填等一整组生产校验。
    demo_deployment_mode: bool = False
```

把 `enforce_environment_safety` 中的硬置改为：

```python
        if self.app_env is AppEnvironment.PRODUCTION:
            self.demo_merchants_endpoint_enabled = self.demo_deployment_mode
```

其余生产校验（`EXPORT_SIGNING_SECRET` 必填与强度、`LLM_API_KEY` 需配 `ADMIN_TOKEN`、`ADMIN_TOKEN` 强度）保持原样，一行都不动。

- [ ] **Step 4: 运行确认通过**

Run: `uv run pytest tests/unit/core/test_config.py -q`

- [ ] **Step 5: 写运维端点可见性的失败测试**

演示模式在生产下开启是一个需要被看见的状态，不能只存在于环境变量里。

> **本步会打破一条既有测试，这是预期的。** `test_correct_token_returns_200_with_safe_payload` 用的是**穷尽键集**断言 `set(body) == {...}`（`tests/api/test_admin_ops.py:100`，7 个键）。新增字段必然让它失败——那正是这条断言的价值。**必须**把 `"demo_deployment_mode"` 加进该集合，**不得**把 `==` 改成 `<=` 或 `issubset` 来绕过：穷尽断言是防止运维端点悄悄多返回敏感字段的防线，削弱它等于拆掉防线。

该文件没有 `admin_client` 夹具，只有 `admin_app: FastAPI`（第 73 行），客户端在每个用例里内联构造。新增用例沿用同一形态，并另建一个开启演示模式的应用夹具：

```python
@pytest_asyncio.fixture
async def demo_mode_admin_app(migrated_postgres: str) -> AsyncIterator[FastAPI]:
    settings = Settings(
        app_env=AppEnvironment.TEST,
        database_url=migrated_postgres,
        frontend_origin="http://localhost:5173",
        admin_token=ADMIN_TOKEN,
        llm_daily_budget_tokens=5_000,
        demo_deployment_mode=True,
    )
    database = Database(settings)
    async with database.session() as session:
        await session.execute(text(TRUNCATE_ALL_TABLES))
        await session.execute(text("TRUNCATE TABLE llm_daily_budget CASCADE"))
        await session.commit()
    app = create_app(settings, database=database)
    yield app
    await database.dispose()


@pytest.mark.asyncio
async def test_ops_status_exposes_demo_deployment_mode(demo_mode_admin_app: FastAPI) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=demo_mode_admin_app), base_url="http://testserver"
    ) as client:
        response = await client.get("/api/admin/ops/status", headers={"X-Admin-Token": ADMIN_TOKEN})

    assert response.status_code == 200
    assert response.json()["demo_deployment_mode"] is True
    # 沿用既有的敏感字段防线，新增字段不得成为泄漏口。
    assert ADMIN_TOKEN not in response.text
    assert "postgresql" not in response.text.lower()


@pytest.mark.asyncio
async def test_ops_status_reports_demo_mode_off_by_default(admin_app: FastAPI) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=admin_app), base_url="http://testserver"
    ) as client:
        response = await client.get("/api/admin/ops/status", headers={"X-Admin-Token": ADMIN_TOKEN})

    assert response.json()["demo_deployment_mode"] is False
```

- [ ] **Step 6: 运行确认失败，再实现**

Run: `uv run pytest tests/api/test_admin_ops.py -q`

在 `admin.py` 的运维状态响应中加入 `demo_deployment_mode` 布尔字段。它是系统级配置状态，不含商家维度，不违反该端点「禁止返回商家数据」的约束。

- [ ] **Step 7: 补端点层测试**

在 `backend/tests/api/test_demo_merchants.py` 增加：生产 + 演示模式关闭时端点不可访问；生产 + 演示模式开启时端点返回服务端配置的演示商家。沿用该文件既有的 `FakeMerchantRepository` 覆盖写法。

Run: `uv run pytest tests/api/test_demo_merchants.py -q`

- [ ] **Step 8: 变异验证**

临时把 Step 3 的放行改回 `self.demo_merchants_endpoint_enabled = True`（即「生产一律放行」），确认 `test_production_keeps_demo_endpoint_closed_by_default` **真实失败**；立即还原并重跑确认通过。

Run: `git diff -- backend/app/core/config.py`（确认变异无残留）

- [ ] **Step 9: 同步契约产物与文档**

Run: `uv run python ../scripts/export_openapi.py`

Run（在 `frontend/`）: `npm run codegen && npm run codegen:check`

在 `.env.example` 增加 `DEMO_DEPLOYMENT_MODE=false` 一行并注明「仅对外演示部署时显式开启」。在 `docs/backend-development-plan.md` 的配置章节登记该字段。

- [ ] **Step 10: 后端定向回归与 diff**

Run: `uv run pytest -q tests/unit/core tests/api/test_demo_merchants.py tests/api/test_admin_ops.py`

Run: `git diff -- backend/ .env.example docs/`

---

### Task 2: 修正未配置客户端时的预算预扣

**Files:**
- Modify: `backend/app/llm/guard.py`
- Test: `backend/tests/unit/llm/test_guard.py`

**Interfaces:**
- Invariant: 底层 LLM 客户端未配置时，`LlmCostGuard.complete()` 不得预扣预算、不得递增 `call_count`。

**背景：** `LlmCostGuard.complete()` 先估算 token 再 `await self._repository.reserve(...)`，**之后**才触达底层客户端；而 `LlmBudgetRepository.reserve` 的 SQL 含 `call_count = call_count + 1`。因此线上未配置 `LLM_API_KEY` 时，虽然不会产生任何 DeepSeek 网络请求，但每一次提问仍会消耗当日预算并推高运维端点的调用计数——F6-B 第一轮的「零调用」口径会因此失真，还会污染第二轮的用量核对。

- [ ] **Step 1: 写失败测试**

该文件已有可直接复用的 `FakeLlmBudgetRepository`（含 `reserve_calls`、`reconcile_calls`、`record_usage_calls` 三个记录列表）与 `_settings()` 辅助函数，**不需要**新建替身。但它的 `StubInnerClient.is_configured()` 是写死的 `True`，所以未配置场景要用应用自己的 `FakeLlmClient`。

在 `backend/tests/unit/llm/test_guard.py` 增加：

```python
@pytest.mark.asyncio
async def test_complete_does_not_reserve_budget_when_inner_client_unconfigured() -> None:
    repository = FakeLlmBudgetRepository(reserve_returns=[])
    guard = LlmCostGuard(
        FakeLlmClient(configured=False),
        repository,
        _settings(),
        request_id="req-unconfigured",
        merchant_id=MERCHANT_ID,
    )
    budget = LlmBudget(max_calls=6, max_tokens=1_000)

    with pytest.raises(LlmUnavailableError):
        await guard.complete(system="s", user="u", fallback="f", budget=budget)

    assert repository.reserve_calls == []
    assert repository.record_usage_calls == []
```

`reserve_returns=[]` 是刻意的：修好之后 `reserve` 一次都不该被调用，若实现仍去预扣，`pop(0)` 会因空列表抛 `IndexError`，测试同样失败——多一层保险。

需要新增的导入：`from app.llm.client import LlmUnavailableError`（若该文件尚未导入）与 `from app.llm.fake import FakeLlmClient`。`LlmBudget` 该文件已导入。构造参数以 `app/api/dependencies.py:141` 的真实调用形态为准：位置参数依次是内层客户端、仓储、settings，其后是 `request_id` 与 `merchant_id` 关键字。

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/unit/llm/test_guard.py -q`

Expected: `reserve_calls` 非空——证明预扣确实发生在可用性判断之前。

- [ ] **Step 3: 实现最小修复**

在 `LlmCostGuard.complete()` 的最开头、任何估算与预扣之前加入：

```python
        if not self._inner.is_configured():
            # 客户端没配置就不可能产生真实用量。放到预扣之后判断会让每次提问
            # 都白扣一次预算并推高 call_count，使「未配置 Key」的部署无法用
            # 运维计数区分「真的没调用」和「调用了但失败」。
            raise LlmUnavailableError("LLM 客户端未配置")
```

- [ ] **Step 4: 运行确认通过并检查未破坏既有行为**

Run: `uv run pytest tests/unit/llm/test_guard.py -q`

Run: `uv run pytest -q tests/unit/llm tests/api/test_chat.py`

Expected: 既有的「预扣后回填」「失败仍计费」两条测试仍通过——它们用的是**已配置**的 fake 客户端，不受本改动影响。若它们失败，说明改动位置太靠前或判断写反。

- [ ] **Step 5: 真实库回归**

Run（PowerShell，容器为 `borough-int-postgres`）:

```powershell
Set-Location 'd:\vscode html\merchant_assistant\backend'
$env:REQUIRE_INTEGRATION_DB = '1'
$env:TEST_DATABASE_URL = 'postgresql+psycopg://borough:borough_local@127.0.0.1:55442/borough_integrate_test'
uv run pytest -q
Write-Host "PYTEST_EXIT=$LASTEXITCODE"
```

Expected: 通过数不低于基线 709（Task 1 与 Task 2 各自新增用例后应更高），0 failed、0 skipped。

- [ ] **Step 6: 后端静态门禁与 diff**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy app`

Run: `git diff -- backend/`

---

## 阶段 F6-0 出口

- 生产环境默认仍关闭演示端点，只有显式 `DEMO_DEPLOYMENT_MODE=true` 才放行，且状态在运维端点可见；
- 未配置 LLM 客户端时不再预扣预算、不再推高 `call_count`；
- 后端真实库回归通过数不低于 709，0 failed / 0 skipped；`ruff`/`format`/`mypy app` 全绿；
- OpenAPI 与 `generated.ts` 已重新生成且 `codegen:check` 通过；
- 全程零 DeepSeek 网络请求。

---

# 阶段 F6-A：前端与构建配置

### Task 3: 首屏网络证据（先立证据，再改实现）

> **执行修订（2026-08-11）：** 原命令使用 `playwright.config.ts` 的 Vite 开发服务器，开发服务器不会产生生产构建的 `/assets/echarts-*.js` 文件名，导致本任务的正则无法观测到计划要验证的 chunk。经实际复现后，本任务改为新增独立的生产构建预览 Playwright 配置与 `test:e2e:first-paint` 脚本；该脚本必须先 `build` 再 `vite preview`，并在相同 Mock 环境变量下运行本用例。原始 `test:e2e` 仍使用开发服务器，不改变既有 E2E 的速度与职责。

**Files:**
- Create: `frontend/e2e/first-paint.spec.ts`

**Interfaces:**
- Produces: 一条真实观测首屏网络请求的 Playwright 断言，作为 Task 4 的验收依据。

**为什么先做这个：** 静态检查 `dist/index.html` 有没有 `modulepreload` 只能证明**预加载提示**不存在，证明不了首屏**不发起**该请求。唯一可信的证据是真实浏览器里的网络观测。先把证据立起来，Task 4 的改动才有可判定的成败。

- [ ] **Step 1: 写首屏网络断言**

创建 `frontend/e2e/first-paint.spec.ts`：

```ts
import { expect, test } from '@playwright/test'

test('首屏不请求 ECharts chunk', async ({ page }) => {
  const requested: string[] = []
  page.on('request', (request) => {
    const url = request.url()
    if (/\/assets\/echarts-[^/]*\.js$/.test(url)) requested.push(url)
  })

  await page.goto('/')
  // 等到首屏真正就绪，确保该发的请求都已发出，而不是抢在加载前断言。
  // quick-question 是既有 e2e 用来确认首屏可交互的同一个 testid。
  await expect(page.getByTestId('quick-question').first()).toBeVisible()

  expect(requested).toEqual([])
})
```

选择器沿用 `e2e/conversation.spec.ts:17` 的 `getByTestId('quick-question')`，**不要**新造 testid。用它而不是 `getByRole('textbox')`：推荐问题由服务端下发，它可见就说明首屏数据链路已经跑完一轮，比输入框可见更能代表「首屏该发的请求都发完了」。

- [ ] **Step 2: 运行并确认它现在就失败**

Run: `npm run test:e2e -- --grep "首屏不请求"`

Expected: **失败**，`requested` 非空。这一步至关重要——它证明这条测试确实能观测到问题；若它现在就通过，说明选择器等得太早或正则写错，先修测试再继续。

- [ ] **Step 3: 检查本任务 diff**

Run: `git diff -- frontend/e2e`

---

### Task 4: 用显式挂载开关把 ECharts 移出首屏

**Files:**
- Modify: `frontend/src/views/AssistantView.vue`
- Modify: `frontend/src/views/AssistantView.spec.ts`
- Create: `frontend/scripts/check-first-paint.mjs`
- Modify: `frontend/package.json`

**Interfaces:**
- Consumes: Task 3 的首屏网络断言。
- Produces: `npm run firstpaint:check`（静态兜底门禁）。
- Invariant: `MetricChartPanel.vue` 组件自身不改，其直接消费者（`InsightPanels.spec.ts` 三条用例）无需改动。

**设计要点：** `defineAsyncComponent` 的 loader 在组件**首次渲染**时就会执行。模板里 `<MetricChartPanel>` 是无条件渲染的，所以单纯换成异步组件根本不会延迟请求——第 1 稿在这里是错的。必须用 `v-if` 显式控制挂载时机。

- [ ] **Step 1: 写挂载开关的失败测试**

在 `src/views/AssistantView.spec.ts` 增加（沿用该文件 `beforeEach` 里 `createPinia()` + `setActivePinia()` 建好的 `pinia`，以及既有 mount 调用的 `stubs` 写法；**本项目未安装 `@pinia/testing`，不要用 `createTestingPinia`**）：

```ts
it('首屏只渲染图表占位，不挂载图表面板', () => {
  const wrapper = mount(AssistantView, {
    global: { plugins: [pinia], stubs: { RouterLink: { template: '<a><slot /></a>' } } },
  })

  const placeholder = wrapper.find('[data-testid="chart-placeholder"]')
  expect(placeholder.exists()).toBe(true)
  expect(placeholder.attributes('aria-busy')).toBe('false')
  expect(wrapper.find('[data-testid="chart-empty"]').exists()).toBe(false)
})

it('空闲回调触发后挂载图表面板', async () => {
  let idleCallback: (() => void) | undefined
  vi.stubGlobal('requestIdleCallback', (cb: () => void) => {
    idleCallback = cb
    return 1
  })

  const wrapper = mount(AssistantView, {
    global: { plugins: [pinia], stubs: { RouterLink: { template: '<a><slot /></a>' } } },
  })

  expect(idleCallback).toBeTypeOf('function')
  idleCallback!()
  await flushPromises()

  expect(wrapper.find('[data-testid="chart-empty"]').exists()).toBe(true)
  vi.unstubAllGlobals()
})

it('不支持 requestIdleCallback 时回退到定时器', () => {
  vi.stubGlobal('requestIdleCallback', undefined)
  const setTimeoutSpy = vi.spyOn(globalThis, 'setTimeout')

  mount(AssistantView, {
    global: { plugins: [pinia], stubs: { RouterLink: { template: '<a><slot /></a>' } } },
  })

  expect(setTimeoutSpy).toHaveBeenCalled()
  setTimeoutSpy.mockRestore()
  vi.unstubAllGlobals()
})
```

占位态的 `aria-busy` 是 `"false"`：首屏并没有在加载图表，谎报忙碌会让屏幕阅读器等待一个不会到来的更新。

- [ ] **Step 2: 运行确认失败**

Run: `npm run test -- src/views/AssistantView.spec.ts`

Expected: 因 `chart-placeholder` 不存在而失败。

- [ ] **Step 3: 实现挂载开关**

删除 `AssistantView.vue` 第 6 行的静态导入 `import MetricChartPanel from '@/components/insights/MetricChartPanel.vue'`。

第 3 行已有 `import { computed, onMounted, ref, watch } from 'vue'`——**扩这一行**，不要新增第二条 vue 导入（`onMounted`、`ref`、`computed`、`watch` 都已在其中，只需补 `defineAsyncComponent`）：

```ts
import { computed, defineAsyncComponent, onMounted, ref, watch } from 'vue'
```

在 `<script setup>` 中加入：

```ts
const MetricChartPanel = defineAsyncComponent(
  () => import('@/components/insights/MetricChartPanel.vue'),
)

// defineAsyncComponent 的 loader 在组件首次渲染时就会执行，所以单靠它无法延迟
// 请求——必须用 v-if 控制挂载时机。首屏先渲染静态占位，等空闲时段或真的来了
// 带图表的回答再挂载，让 544K 的 ECharts 退出首屏网络路径。
const chartMountable = ref(false)

function mountChartPanel(): void {
  chartMountable.value = true
}

onMounted(() => {
  if (typeof requestIdleCallback === 'function') {
    requestIdleCallback(mountChartPanel)
  } else {
    // Safari 较老版本没有 requestIdleCallback。
    setTimeout(mountChartPanel, 1000)
  }
})

// 空闲回调还没轮到就先来了图表回答时，立刻挂载，不要让用户等空闲。
watch(
  () => chatStore.currentAnswer?.chart,
  (chart) => {
    if (chart) mountChartPanel()
  },
)
```

`chatStore` 沿用该文件既有的 store 实例名，不要新建。

模板中把原来的 `<MetricChartPanel :answer="chatStore.currentAnswer" />` 替换为：

```vue
<MetricChartPanel v-if="chartMountable" :answer="chatStore.currentAnswer" />
<section
  v-else
  class="chart-panel"
  aria-label="指标图表"
  aria-busy="false"
  data-testid="chart-placeholder"
>
  <p>发起可视化类问题后，这里会显示图表。</p>
</section>
```

占位文案与 `MetricChartPanel` 空态的既有文案保持一致，避免用户在两种状态间看到措辞跳变。

- [ ] **Step 4: 运行单测确认通过**

Run: `npm run test -- src/views/AssistantView.spec.ts src/components/insights/InsightPanels.spec.ts`

Expected: 全部通过。`InsightPanels.spec.ts` 直接 mount `MetricChartPanel`，不经过 `AssistantView`，不应受影响——若它失败，说明改动误伸进了组件内部。

- [ ] **Step 5: 运行 Task 3 的首屏证据，确认由红转绿**

Run: `npm run test:e2e -- --grep "首屏不请求"`

Expected: 通过。这是本任务成立的**唯一**充分证据。

- [ ] **Step 6: 确认图表功能未被破坏**

Run: `npm run test:e2e`

Expected: 25 条既有用例仍通过，其中 `conversation.spec.ts` 的 4 处图表断言必须仍然成立。若出现偶发失败，**不得**加固定 `waitForTimeout` 掩盖，改为等待具体元素可见。

- [ ] **Step 7: 加静态兜底门禁**

创建 `frontend/scripts/check-first-paint.mjs`（路径处理沿用既有 4 个脚本统一的 `fileURLToPath` 写法，**不要**用 `new URL().pathname`——在 Windows 上它会得到 `/D:/...` 这种打不开的路径）：

```js
// F6：ECharts 必须留在首屏关键路径之外。
// 这是静态兜底：真正的证据是 e2e/first-paint.spec.ts 的网络观测。
// 两层都留着——e2e 证明行为，本脚本在不跑浏览器的门禁里快速拦回归。
import { readFileSync, readdirSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const frontendRoot = resolve(fileURLToPath(new URL('..', import.meta.url)))
const distDir = join(frontendRoot, 'dist')
const html = readFileSync(join(distDir, 'index.html'), 'utf8')

const echartsChunks = readdirSync(join(distDir, 'assets')).filter(
  (name) => name.startsWith('echarts-') && name.endsWith('.js'),
)

if (echartsChunks.length === 0) {
  console.error('未找到独立的 echarts chunk，manualChunks 配置可能已失效')
  process.exit(1)
}

const preloaded = echartsChunks.filter((name) => html.includes(name))

if (preloaded.length > 0) {
  console.error(`index.html 仍在首屏预加载 ECharts：${preloaded.join(', ')}`)
  console.error('检查 AssistantView.vue 是否把 MetricChartPanel 改回了无条件渲染。')
  process.exit(1)
}

console.log('index.html 未预加载 ECharts chunk')
```

在 `package.json` 的 `scripts` 加入：

```json
"firstpaint:check": "node scripts/check-first-paint.mjs"
```

- [ ] **Step 8: 变异验证两层证据都会失败**

临时把模板改回无条件渲染 `<MetricChartPanel :answer="chatStore.currentAnswer" />`，重新构建后：

Run: `npm run build && npm run firstpaint:check`（**必须失败**）

Run: `npm run test:e2e -- --grep "首屏不请求"`（**必须失败**）

立即还原，重跑两者确认恢复通过。

Run: `git diff -- frontend/src/views/AssistantView.vue`（确认变异无残留）

- [ ] **Step 9: 记录首屏体积变化**

Run: `npm run build`

记录 `dist/index.html` 的 modulepreload 列表与各 chunk 大小，与基线（index 213K / echarts 544K 被预加载）对比。**只记录机械事实，不承诺 FCP 改善数值**——真实网络下的收益要等部署后才能测。

- [ ] **Step 10: 检查本任务 diff**

Run: `git diff -- frontend/src/views frontend/scripts frontend/package.json`

---

### Task 5: 生产构建的 Mock 硬防线（含 Dockerfile 通路）

**Files:**
- Create: `frontend/src/build/mock-flag.ts`
- Create: `frontend/src/build/mock-flag.spec.ts`
- Modify: `frontend/vite.config.ts`
- Modify: `frontend/tsconfig.node.json`
- Modify: `frontend/Dockerfile`

**Interfaces:**
- Produces: `assertMockDisabledInProduction(mode: string, env: Record<string, string | undefined>): void`

**为什么放在 `src/build/` 而不是 `scripts/`：** `scripts/` 不在 `tsconfig.vitest.json` 的 `include`（当前只有 `src/**/*.ts`、`src/**/*.vue`、`env.d.ts`）里，也不在 Vitest 的 `include`（`src/**/*.spec.ts`）里。放进 `src/build/` 则两者都自动覆盖，无需改 Vitest 配置。它不会进产物——应用代码不导入它，只有 `vite.config.ts` 导入，Step 6 会机械核实这一点。

- [ ] **Step 1: 写纯函数的失败测试**

创建 `frontend/src/build/mock-flag.spec.ts`：

```ts
import { describe, expect, it } from 'vitest'

import { assertMockDisabledInProduction } from './mock-flag'

describe('assertMockDisabledInProduction', () => {
  it('生产模式下开启 Mock 必须抛错', () => {
    expect(() => assertMockDisabledInProduction('production', { VITE_USE_MOCK: 'true' })).toThrow(
      /VITE_USE_MOCK/,
    )
  })

  it('生产模式下未开启 Mock 时放行', () => {
    expect(() => assertMockDisabledInProduction('production', {})).not.toThrow()
    expect(() =>
      assertMockDisabledInProduction('production', { VITE_USE_MOCK: 'false' }),
    ).not.toThrow()
  })

  it('开发模式下开启 Mock 是正常用法，不得拦截', () => {
    expect(() =>
      assertMockDisabledInProduction('development', { VITE_USE_MOCK: 'true' }),
    ).not.toThrow()
  })

  it('只认精确的 true，与 transport.ts 的判定保持一致', () => {
    expect(() =>
      assertMockDisabledInProduction('production', { VITE_USE_MOCK: 'TRUE' }),
    ).not.toThrow()
    expect(() => assertMockDisabledInProduction('production', { VITE_USE_MOCK: '1' })).not.toThrow()
  })
})
```

最后一条刻意钉住「只认精确 `true`」：`src/api/transport.ts::isMockEnabled()` 判的就是 `=== 'true'`，防线判定必须与它一致，否则会出现「防线放行但运行时启用」的错配。

- [ ] **Step 2: 运行确认失败**

Run: `npm run test -- src/build/mock-flag.spec.ts`

Expected: 因模块不存在而失败。若报「零个测试被收集」，说明文件位置不对，先修位置。

- [ ] **Step 3: 实现纯函数**

创建 `frontend/src/build/mock-flag.ts`：

```ts
/**
 * 生产构建禁止启用 Mock 传输。
 *
 * 为什么不靠 `mock:check`：那个脚本扫的是 dist 里有没有 fixture 载荷，而
 * `VITE_USE_MOCK=true` 只是让 `src/api/transport.ts::isMockEnabled()` 返回 true，
 * mock 传输层代码本身未必包含可被识别的 fixture 字符串——事后扫描会漏。
 * 这里在配置解析阶段就让构建非零退出。
 *
 * 本模块只被 vite.config.ts 导入，不进应用产物。
 */
export function assertMockDisabledInProduction(
  mode: string,
  env: Record<string, string | undefined>,
): void {
  if (mode !== 'production') return
  // 判定标准必须与 src/api/transport.ts::isMockEnabled() 完全一致。
  if (env.VITE_USE_MOCK === 'true') {
    throw new Error(
      '生产构建禁止启用 Mock：检测到 VITE_USE_MOCK=true。' +
        '生产环境必须连真实后端，请移除该变量或设为 false。',
    )
  }
}
```

- [ ] **Step 4: 运行确认通过**

Run: `npm run test -- src/build/mock-flag.spec.ts`

- [ ] **Step 5: 接进 Vite 配置并纳入类型门禁**

把 `vite.config.ts` 改为函数式配置：

```ts
import { loadEnv } from 'vite'
// 从 vitest/config 导入 defineConfig 才认 test 字段；vite 的 defineConfig 不接受它。
import { defineConfig } from 'vitest/config'

import { assertMockDisabledInProduction } from './src/build/mock-flag'

export default defineConfig(({ mode }) => {
  assertMockDisabledInProduction(mode, loadEnv(mode, process.cwd(), 'VITE_'))

  return {
    // …现有 plugins / resolve / build / test 配置原样搬入，不做其他改动
  }
})
```

**`loadEnv` 必须从 `vite` 导入。** 已实测 `vitest/config` 的导出里没有 `loadEnv`（只有 `defineConfig`、`mergeConfig`、`configDefaults` 等），写错会直接报导出缺失。

`vite.config.ts` 属于 `tsconfig.node.json`（`include: ["vite.config.ts", "playwright.config.ts"]`），而被它导入的 `src/build/mock-flag.ts` 不在该工程内，`composite: true` 下会报「文件不在项目文件列表中」。把 `tsconfig.node.json` 的 include 改为：

```json
  "include": ["vite.config.ts", "playwright.config.ts", "src/build/mock-flag.ts"]
```

- [ ] **Step 6: 确认类型门禁通过且模块未进产物**

Run: `npm run typecheck`

Run: `npm run build`

Run: `rg -c "生产构建禁止启用 Mock" dist/` —— **必须零命中**（rg 无命中时退出码为 1，属预期）。命中说明该模块被打进了产物，检查是否有应用代码误导入它。

- [ ] **Step 7: 让 Dockerfile 能收到该变量**

`frontend/Dockerfile` 当前只声明 `ARG VITE_API_BASE_URL`（第 17 行）。Railway 的 Docker 构建变量**只有在 Dockerfile 中声明为 `ARG` 才可用**，否则防线在镜像构建里根本看不到 `VITE_USE_MOCK`，Task 9 手册里「设为 true 会让构建失败」的说明就不成立。在 `ARG VITE_API_BASE_URL` 之后补：

```dockerfile
# 刻意声明这个 ARG：不是为了让生产开启 Mock，而是让 src/build/mock-flag.ts
# 的防线在镜像构建里也能看到它。不声明的话，误配 VITE_USE_MOCK=true 会被
# 静默忽略，防线形同虚设。
ARG VITE_USE_MOCK
ENV VITE_USE_MOCK=$VITE_USE_MOCK
```

- [ ] **Step 8: 端到端确认防线在本地与镜像里都生效**

Run: `npm run build`（不带变量，必须成功）

Run（PowerShell，必须**失败**并打印中文提示）：

```powershell
Set-Location 'd:\vscode html\merchant_assistant\frontend'
$env:VITE_USE_MOCK = 'true'
npm.cmd run build
Write-Host "EXPECT_NONZERO=$LASTEXITCODE"
```

Run（镜像构建路径，必须**失败**）：

```powershell
Set-Location 'd:\vscode html\merchant_assistant\frontend'
docker build --build-arg VITE_API_BASE_URL=https://example.invalid --build-arg VITE_USE_MOCK=true -t borough-frontend-mockcheck .
Write-Host "EXPECT_NONZERO=$LASTEXITCODE"
```

> PowerShell 里 `$env:X = ''` 等同于删除变量；本工具的 shell 状态不跨调用保留，因此无需显式清理，换一次调用即可。

- [ ] **Step 9: 确认既有门禁未被波及**

Run: `npm run test && npm run typecheck && npm run build && npm run mock:check`

- [ ] **Step 10: 检查本任务 diff**

Run: `git diff -- frontend/vite.config.ts frontend/tsconfig.node.json frontend/Dockerfile frontend/src/build`

---

### Task 6: 前端 Railway 配置与构建产物密钥防线

**Files:**
- Create: `frontend/railway.json`
- Create: `frontend/scripts/check-no-secrets.mjs`
- Modify: `frontend/package.json`

**Interfaces:**
- Produces: `npm run secrets:check`

> **注意：** 创建 `railway.json` **不等于**它会生效。Railway 官方文档明确：配置文件路径不跟随 Root Directory，必须在控制台显式指定绝对路径。该动作在 Task 10 Step 2，两者缺一不可。

- [ ] **Step 1: 写 Railway 配置**

创建 `frontend/railway.json`（与 `backend/railway.json` 同构；后端已确立的做法是配置文件放在各自 Service Root 下，不是仓库根的 `railway/` 目录）：

```json
{
  "$schema": "https://railway.app/railway.schema.json",
  "build": {
    "builder": "DOCKERFILE",
    "dockerfilePath": "Dockerfile"
  },
  "deploy": {
    "healthcheckPath": "/health.html",
    "healthcheckTimeout": 30,
    "restartPolicyType": "ON_FAILURE",
    "restartPolicyMaxRetries": 3
  }
}
```

与后端的差异及理由：`healthcheckPath` 指向 `Caddyfile` 里独立处理、不参与 SPA 回退的 `/health.html`；**没有** `releaseCommand`——静态前端没有迁移步骤。

- [ ] **Step 2: 写密钥扫描门禁**

创建 `frontend/scripts/check-no-secrets.mjs`（路径处理沿用既有脚本的 `fileURLToPath` 写法）：

```js
// F6：构建产物不得包含任何密钥。
// VITE_ 前缀变量会被内联进静态产物，一旦有人误把密钥写成 VITE_ 变量，
// 它就会公开在 CDN 上。让这类错误在门禁里失败，而不是上线后才发现。
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const frontendRoot = resolve(fileURLToPath(new URL('..', import.meta.url)))
const distDir = join(frontendRoot, 'dist')

const PATTERNS = [
  { name: 'DeepSeek API Key', re: /\bsk-[A-Za-z0-9]{16,}\b/ },
  { name: 'PostgreSQL 连接串', re: /postgres(?:ql)?(?:\+\w+)?:\/\/[^\s"']+:[^\s"']+@/ },
  { name: '演示商家 Token 映射', re: /DEMO_MERCHANT_TOKENS/ },
  { name: '管理员令牌', re: /ADMIN_TOKEN/ },
  { name: '导出签名密钥', re: /EXPORT_SIGNING_SECRET/ },
]

function* walk(dir) {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry)
    if (statSync(full).isDirectory()) yield* walk(full)
    else yield full
  }
}

const hits = []
for (const file of walk(distDir)) {
  if (!/\.(js|css|html|json|map)$/.test(file)) continue
  const content = readFileSync(file, 'utf8')
  for (const { name, re } of PATTERNS) {
    if (re.test(content)) hits.push(`${name} → ${file.slice(distDir.length + 1)}`)
  }
}

if (hits.length > 0) {
  console.error('构建产物中检出疑似密钥：')
  for (const hit of hits) console.error(`  ${hit}`)
  process.exit(1)
}

console.log('构建产物未检出密钥形态字符串')
```

在 `package.json` 的 `scripts` 加入：

```json
"secrets:check": "node scripts/check-no-secrets.mjs"
```

- [ ] **Step 3: 运行门禁确认当前产物干净**

Run: `npm run build && npm run secrets:check`

- [ ] **Step 4: 变异验证门禁真的会命中**

临时创建 `frontend/.env.production`，写入一行 `VITE_LEAKED_KEY=sk-0123456789abcdef0123456789abcdef`，并在 `src/api/client.ts` 顶部临时加 `console.debug(import.meta.env.VITE_LEAKED_KEY)` 让它真的被内联；重新构建后跑门禁，**必须失败并指出命中文件**。

随后删除该文件与临时代码，重新构建确认恢复通过。

**校验残留必须用 `Test-Path`，不能用 `git status`**——`frontend/.gitignore:12` 的 `.env.*` 会让 `.env.production` 在 `git status` 中完全不可见：

```powershell
Set-Location 'd:\vscode html\merchant_assistant'
if (Test-Path 'frontend/.env.production') { throw '临时密钥文件未删除' } else { Write-Host 'OK：无残留' }
```

Run: `git diff -- frontend/src/api/client.ts`（确认临时代码已还原）

- [ ] **Step 5: 检查本任务 diff**

Run: `git diff -- frontend/railway.json frontend/scripts frontend/package.json`

---

### Task 7: 文档同步与 F6-A 全量验收

**Files:**
- Modify: `AGENTS.md`
- Modify: `docs/frontend-development-plan.md`
- Modify: `docs/project-progress.md`

- [ ] **Step 1: 先跑全量门禁，拿到真实数字再写文档**

逐条执行，任一条非零退出即停止并修复。**共 13 条**：

Run: `npm run lint`

Run: `npm run format:check`

Run: `npm run codegen:check`

Run: `npm run fixtures:check`

Run: `npm run typecheck`

Run: `npm run test`

Run: `npm run build`

Run: `npm run mock:check`

Run: `npm run firstpaint:check`

Run: `npm run secrets:check`

Run: `npm run test:e2e`

后端两条（容器 `borough-int-postgres`，含 F6-0 的改动）：

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy app`

Run: `REQUIRE_INTEGRATION_DB=1` 的真实库 `uv run pytest`（PowerShell 写法见 Task 2 Step 5）

- [ ] **Step 2: 修正 `AGENTS.md` 的路径事实**

§六 目标目录树：把仓库根的 `railway/` 段落改为反映实际做法——配置随各自 Service Root，即 `backend/railway.json` 与 `frontend/railway.json`，删除 `railway/frontend.json`、`railway/backend.json`、`railway/worker.json` 三行。

§十四：末尾「详细步骤写入 `docs/deploy-railway.md`」改为 `docs/deployment.md`（B7 实际产出的是后者）；第 498 行目录树里的 `deploy-railway.md` 与第 1024 行「修改部署」表格里的引用一并改掉。

**第 257 行不得改动**——那是 `yshopping-merchant-ai 4/yshopping-merchant-ai/docs/deploy-railway.md`，参考项目的真实只读路径，改它违反 R8。

§七.5 前端文件索引补入 `frontend/scripts/check-first-paint.mjs` 与 `frontend/scripts/check-no-secrets.mjs` 两行，与既有 `check-generated.mjs` 条目并列。

§十六 或对应位置登记 `DEMO_DEPLOYMENT_MODE` 环境变量。

- [ ] **Step 3: 按实测结果更新前端方案 F6 章节**

在 `docs/frontend-development-plan.md` §F6：勾选已完成项；「路由级代码分割」补注 `/` 是首屏故意 eager，真正收益来自图表面板的显式挂载开关，由 `e2e/first-paint.spec.ts` 与 `firstpaint:check` 两层守住；「长会话评估虚拟列表」保持未勾并注明「已评估，MVP 明确不做」；「验收（MVP 出口）」整节保持未勾，注明依赖 F6-B。

- [ ] **Step 4: 更新进度快照**

在 `docs/project-progress.md` 写入 F6-0 与 F6-A 的实测数字、新增门禁脚本、两次变异验证结论，以及**本计划出口是「Railway 部署就绪」而非「MVP 完成」**的限定。

- [ ] **Step 5: 文档卫生检查**

Run: `rg -n "railway/frontend\.json|railway/backend\.json" AGENTS.md docs/` —— 必须零命中。

Run: `rg -n "deploy-railway\.md" AGENTS.md docs/` —— **预期恰好 1 处命中**，即 `AGENTS.md:257` 的参考项目只读路径。多于 1 处说明 Step 2 有遗漏；等于 0 处说明误删了参考项目路径，必须还原。

- [ ] **Step 6: 检查最终范围**

Run: `git status --short`

Run: `git diff --stat`

---

## 阶段 F6-A 出口

- `e2e/first-paint.spec.ts` 通过，且变异验证证明它会失败；
- `VITE_USE_MOCK=true` 时本地构建与 `docker build` 均非零退出；
- `secrets:check` 通过且变异验证证明它会命中；
- `frontend/railway.json` 存在；
- 13 项门禁全绿，Vitest 与 Playwright 通过数不低于基线；
- 文档卫生检查：`railway/*.json` 零命中，`deploy-railway.md` 恰好 1 处（参考项目路径）；
- 全程零 DeepSeek 网络请求。

---

# 阶段 F6-B：Railway 部署与线上验收

### Task 8: 编写部署手册

**Files:**
- Modify: `docs/deployment.md`

- [ ] **Step 1: 追加「前端服务」一节**

覆盖：Service Root `/frontend`；Builder 为 Dockerfile；健康检查 `/health.html`；镜像为 Node 多阶段 → `caddy:2-alpine`；Caddy 不代理 `/api`，**前端域名下不存在任何 API 路径**是刻意设计。

- [ ] **Step 2: 追加「Railway 配置文件路径」一节**

必须写明并解释：

> Railway 的 Config File Path **不跟随** Root Directory。即使 Service Root 设为 `/frontend`，也必须在服务设置里把 Config File Path 显式填成 `/frontend/railway.json`；后端同理填 `/backend/railway.json`。不做这一步，两份 `railway.json` 都不会生效——健康检查与后端的 `releaseCommand`（`alembic upgrade head`）都会静默失效。

- [ ] **Step 3: 追加「前端环境变量」一节**

| 变量 | 必填 | 说明 |
| --- | --- | --- |
| `VITE_API_BASE_URL` | 是 | 后端公网地址，**构建期**注入静态产物。改这个值必须重新构建，只改变量不重新部署不生效。 |
| `VITE_USE_MOCK` | 否 | 生产必须不设或设为 `false`。设为 `true` 会让镜像构建直接失败（Dockerfile 已声明对应 ARG）。 |

- [ ] **Step 4: 追加「演示部署模式」一节**

写明：`DEMO_DEPLOYMENT_MODE=true` 是**对外演示部署专用**的显式开关，开启后 `/api/demo/merchants` 在生产环境下可访问，前端才能获得商家身份；不开启时该端点关闭，前端将无法选择商家。开启状态可在 `/api/admin/ops/status` 查看。演示 Token 只授予演示数据访问权，商家隔离仍由后端强制注入 `merchant_id` 保证。

- [ ] **Step 5: 追加「上线顺序」一节**

明确顺序与理由：部署后端 → 拿到后端域名 → 以该域名为 `VITE_API_BASE_URL` 构建前端 → 拿到前端域名 → 回填后端 `FRONTEND_ORIGIN`（精确 Origin，含协议、不含路径与尾斜杠）→ 后端重新部署。前端地址在构建期固化、后端 CORS 需要前端地址，两者互相依赖，各需部署一次。

- [ ] **Step 6: 检查本任务 diff**

Run: `git diff -- docs/deployment.md`

---

### Task 9: 用户在 Railway 控制台完成部署

> 本任务全部由用户执行。coding agent 只负责核对结果。

- [ ] **Step 1: 创建服务并设置 Root Directory**

后端 Service Root `/backend`，前端 Service Root `/frontend`，并创建 PostgreSQL Service。

- [ ] **Step 2: 显式设置两个 Config File Path**

后端填 `/backend/railway.json`，前端填 `/frontend/railway.json`。**这一步不能省**，理由见 Task 8 Step 2。

- [ ] **Step 3: 填写后端环境变量（第一轮：不配 LLM Key）**

`DATABASE_URL`（引用 PostgreSQL Service）、`APP_ENV=production`、`ADMIN_TOKEN`（强随机）、`EXPORT_SIGNING_SECRET`（强随机）、`FRONTEND_ORIGIN`（前端域名，第一次部署时可先留占位、拿到域名后回填）、`DEMO_DEPLOYMENT_MODE=true`。

**`LLM_API_KEY` 本轮不填**——第一轮验收要求零 DeepSeek 网络请求。

- [ ] **Step 4: 部署并回填 CORS**

按 Task 8 Step 5 的顺序完成两侧部署与 `FRONTEND_ORIGIN` 回填。

---

### Task 10: 第一轮线上验收（无 LLM Key，零网络请求）

> **费用口径（精确）：** 后端未配置 `LLM_API_KEY` 时走 `FakeLlmClient(configured=False)`，**DeepSeek 网络请求 0 次、费用 0**。经 F6-0 Task 2 修复后，`call_count` 与当日预算也不再被这些失败调用消耗；若 F6-0 Task 2 未先完成，则本轮会污染运维计数，**不得**在此情况下执行本任务。

- [ ] **Step 1: 核对前置**

确认 F6-0 两个切片均已完成并部署；确认 `LLM_API_KEY` 未配置；确认 `DEMO_DEPLOYMENT_MODE=true`。

- [ ] **Step 2: 验静态与健康**

`https://<前端域名>/health.html` 返回 200；`https://<前端域名>/api/anything` 返回 404 与中文提示，**不是** `index.html`。

- [ ] **Step 3: 验演示身份通路**

`/api/demo/merchants` 可访问并返回服务端配置的演示商家；前端能列出并选择商家。这一条直接验证 F6-0 Task 1 在真实生产配置下生效。

- [ ] **Step 4: 验 CORS 精确 Origin**

DevTools Network 检查预检：`Access-Control-Allow-Origin` 为前端域名精确值、**不得**为 `*`；允许头含 `Authorization`、`Accept`、`Content-Type`、`X-Request-Id`。

- [ ] **Step 5: 验跨域 SSE 确实流式**

提问后确认 `/api/chat` 响应类型为 `text/event-stream`，且**首个阶段标签在 1 秒内出现在界面上**。这是 MVP 出口里唯一无法在本地 mock 环境证明的条目。

- [ ] **Step 6: 验降级可见性（R7）**

确认回答明确显示降级状态与原因。本轮所有回答都走降级路径，正好把这条验透。

- [ ] **Step 7: 验会话、隔离与响应式**

刷新后能重新选回商家并恢复会话；切换商家后看不到上一个商家的会话；360px 与 1440px 视口可用、无横向滚动。

- [ ] **Step 8: 核对运维计数确为零**

携 `X-Admin-Token` 请求 `/api/admin/ops/status`，确认当日 `llm_calls_today` 与 token 用量**仍为 0**，且 `demo_deployment_mode` 为 `true`。这同时验证了 F6-0 Task 2 的修复在真实部署里生效。

- [ ] **Step 9: 记录本轮结论**

写入 `docs/project-progress.md`，明确标注「本轮无 LLM Key，图表、明细表格与签名导出未验证，留待第二轮」。

---

### Task 11: 第二轮线上验收（真实 DeepSeek）

**前置：** 第一轮全部通过。

> **R3 费用说明——执行前必须向用户复述并获得明确同意：**
>
> - 接口：线上 `POST /api/chat`
> - 模型：`deepseek-v4-flash`
> - **聊天请求：2 次**（一次 METRIC 验图表，一次 DETAIL 验表格与签名导出）
> - **真实模型调用：上限 12 次。** 每次成功问答通常包含结构化理解、回答生成、Reviewer 三类调用（`app/intent/service.py:52`、`app/agent/graph.py:332`、`app/agent/graph.py:393`），Reviewer 不通过时还会再生成再审核；单请求上限由 `llm_max_calls_per_request` 限定为 **6**（`app/core/config.py`）。因此 2 次请求的调用数通常约 8 次、最坏 12 次。
> - 为什么不能只提一次问：导出记录只在 DETAIL 成功且未降级时创建，图表只在 METRIC 回答中产生，一次提问覆盖不了两条路径。
> - 费用：按 `deepseek-v4-flash` 单价计极低，但**不为零**。

- [ ] **Step 1: 补配 `LLM_API_KEY`**

`ADMIN_TOKEN` 在 Task 9 Step 3 已配置，因此本步只需新增 `LLM_API_KEY`。后端配置校验规定「生产环境配置 `LLM_API_KEY` 时必须设置 `ADMIN_TOKEN`」——该前提已满足，服务不会因此拒绝启动。

- [ ] **Step 2: 记录调用前的用量基线**

携 `X-Admin-Token` 请求 `/api/admin/ops/status`，记录 `llm_calls_today` 与 token 用量的**起始值**。第一轮之后这两个值应为 0；若不为 0，先查明原因再继续。

- [ ] **Step 3: 第 1 次聊天请求——验 METRIC 图表**

提一个指标类问题，确认：回答非降级、图表渲染、图表文本摘要非空、质量轨迹显示真实的 `quality_status` 与校验次数。

- [ ] **Step 4: 第 2 次聊天请求——验 DETAIL 表格与签名导出**

提一个明细类问题，确认：表格渲染且有表头、行数说明正确、CSV 下载链接可点击并能真实下载到文件。

- [ ] **Step 5: 验反馈闭环**

对任一真实回答执行采纳与点赞，确认显示「已记录」，刷新后仍在。此步不产生模型调用。

- [ ] **Step 6: 按实际用量核对，不做等值断言**

再次请求 `/api/admin/ops/status`，计算与 Step 2 基线的差值。**断言为「差值 ≤ 12」而不是「等于 2」**，并把实际数字如实记入验收记录。若差值超过 12，说明单请求上限未生效，属真实缺陷，须停下来排查。

- [ ] **Step 7: 记录本轮结论**

写入 `docs/project-progress.md`，包含真实调用次数、token 用量与实际费用估算。

---

### Task 12: 产出出口证据矩阵

**Files:**
- Create: `docs/specs/2026-08-11-mvp-exit-evidence-matrix.md`
- Modify: `docs/project-progress.md`
- Modify: `AGENTS.md`

**Interfaces:**
- Produces: 一张逐条对照的证据表，供用户判断 MVP 是否可宣告完成。

- [ ] **Step 1: 建立证据矩阵**

对 `docs/PRD.md` §16 的每一条出口、`docs/backend-development-plan.md` §B7 与 `docs/frontend-development-plan.md` §F6 的「验收（MVP 出口）」逐条列出，每行标注：条目 / 状态（已验证 / 未验证 / 已裁定偏离）/ 证据（命令输出、截图或测试名）/ 缺口说明。

- [ ] **Step 2: 登记已知未覆盖项**

至少必须如实列出以下三项为「未验证」：

1. **真实模型意图准确率 ≥ 90%**（`docs/PRD.md:101`、`docs/PRD.md:997`）——两次线上提问得不出准确率，需要跑完整问题集并人工评估，属独立工作。
2. **PRD §16 的四业务域、规则问答、连续追问、预算熔断与限流完整覆盖**——两次提问远不足以证明。
3. **还原度审计的未处理缺口**，逐条引用 `docs/yshopping-parity-audit.md`，其中 §3.6「思考过程只渲染最后一步」是纯前端缺口，归 R9 阶段 B Task 8。

- [ ] **Step 3: 更新 `AGENTS.md` 与进度快照**

阶段状态写为「**前端 F0–F6 完成，Railway 部署就绪**」。**不得**写「MVP 完成」——依据是 Step 2 的三项未验证。是否宣告 MVP 完成由用户在看过证据矩阵后决定。

- [ ] **Step 4: 检查本任务 diff**

Run: `git status --short`

Run: `git diff --stat`

---

## 风险与已知边界

1. **F6-0 触碰后端生产代码。** 两个切片都有变异验证与真实库回归兜底，但它们改的是配置校验与费用守卫两处敏感位置，评审时应重点看「默认仍然关闭」和「既有预扣回填行为未变」两条不变量。
2. **演示部署模式扩大了生产环境的可访问面。** 它只放开既有的演示 Token 通路，不引入新的身份来源；但一旦误开在真实商业部署上，演示商家数据会对外可见。因此默认关闭、显式开启、运维端点可见三条缺一不可。
3. **第一轮验收下 `quality_status` 与 `analysis_sources` 全程是降级值**，不能据此判断 Reviewer 链路正常。
4. **异步挂载可能波及既有 e2e。** `conversation.spec.ts` 有 4 处图表断言、`real-api/analytics.spec.ts` 有 4 处。出现偶发失败**不得**用固定 `waitForTimeout` 掩盖。
5. **首屏收益未在真机网络上测量。** 本计划只保证「首屏不请求 echarts chunk」这一机械事实，不承诺 FCP 数值。
6. **F6-B 的开始时点完全取决于用户**，计划内不设时间承诺。

## 明确不做（YAGNI）

- 长会话虚拟列表——F6 原清单即写明 MVP 不做；
- 路由级进一步拆分——`/` 是首屏，eager 正确；`/knowledge-base` 已 lazy；
- ECharts 按需引入、Caddy 缓存策略、`/api` 不代理、`manualChunks`——均已完成，见「现状核对」；
- 真实模型意图准确率评估——独立工作，只在证据矩阵里登记为未验证；
- 还原度审计的其余缺口——归 R9 阶段 B；
- 前端 CDN、多区域部署、构建缓存优化——不在出口内。
