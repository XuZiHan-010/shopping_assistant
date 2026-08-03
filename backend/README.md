# Borough 商家 AI 助手后端

后端采用 Python 3.12、FastAPI 与 PostgreSQL。目前已完成 B0 工程骨架和 B1
数据库、迁移、演示 Token、可信商家上下文与隔离基础设施。

## 本地环境

在 `backend/` 中执行：

```powershell
uv sync
$env:DATABASE_URL='postgresql+psycopg://borough:borough_local@127.0.0.1:55432/borough_test'
$env:FRONTEND_ORIGIN='http://localhost:5173'
$env:DEMO_MERCHANT_TOKENS='{"merchant-100-token":"00000000-0000-0000-0000-000000000001","merchant-101-token":"00000000-0000-0000-0000-000000000002","merchant-102-token":"00000000-0000-0000-0000-000000000003"}'
uv run alembic upgrade head
uv run python -m app.run
```

可访问：

```text
GET http://127.0.0.1:8000/api/health
GET http://127.0.0.1:8000/api/ready
GET http://127.0.0.1:8000/api/demo/merchants
```

`/api/health` 不访问数据库或 LLM；`/api/ready` 只执行 `SELECT 1`。

## 测试

单元与 API 测试：

```powershell
uv run ruff check .
uv run ruff format --check .
uv run mypy app
uv run pytest tests/unit tests/api
```

PostgreSQL 集成测试必须连接名称以 `_test` 结尾的真实 PostgreSQL 数据库，不使用
SQLite。在仓库根目录启动测试库：

```powershell
docker-compose -p borough up -d postgres   # 无 compose 插件时用 docker compose
uv run pytest tests/integration -v
```

测试库默认 `127.0.0.1:55432`，可用 `TEST_DATABASE_URL` 覆盖。

**CI 必须设 `REQUIRE_INTEGRATION_DB=1`。** 测试库不可达时默认会自动跳过——本地开发方便，
但在 CI 里意味着 postgres 起不来也全绿，而商家隔离、迁移和 Seed 的验收全在这些用例里。
开启后库连不上会硬失败：

```powershell
$env:REQUIRE_INTEGRATION_DB = "1"; uv run pytest
```

### Windows 注意

psycopg 的异步模式跑不了 Windows 默认的 `ProactorEventLoop`。入口已各自处理
（见 `app/core/runtime.py`），但**新增入口时必须显式选择事件循环**，否则会连不上
数据库而表现为 `/api/ready` 返回 503：

- `asyncio.run()` 类脚本 → 先调 `configure_event_loop_policy()`；
- uvicorn 服务 → 传 `loop=loop_factory()`，它**不看**全局策略。

所有自动化测试均不调用真实 LLM，也不产生模型费用。

## DeepSeek LLM 配置

真实 LLM Adapter 在 B3 实现；提供商已固定为 DeepSeek 的 OpenAI 兼容 Chat Completions API。
示例配置在仓库根目录 `.env.example`：

```text
LLM_API_KEY=<deepseek-api-key>
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-v4-flash
LLM_ENABLED=false
```

`LLM_API_KEY` 只能通过未纳入版本控制的环境变量或 Railway Variables 提供。`deepseek-v4-flash`
是 MVP 默认模型；需要使用 `deepseek-v4-pro` 前，必须完成费用评估和真实模型离线验收。
`deepseek-chat` 与 `deepseek-reasoner` 已弃用，不得配置。即使配置完成，也不得在未取得用户
明确同意前发起真实 DeepSeek 调用。

## 演示 Seed

从仓库根目录执行：

```powershell
uv run --project backend python scripts/seed_demo_data.py --dry-run
uv run --project backend python scripts/seed_demo_data.py --seed
```

B1 只写入三个虚构商家；180 天经营数据将在 B4 增加。Token 只从环境变量读取，
不会写入数据库。
