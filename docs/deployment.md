# Railway 部署与运维手册

本手册只描述部署操作；不会在本地或 Railway 自动写入真实密钥。

## 服务与构建

在同一个 Railway 项目中创建 PostgreSQL 和 Backend 两个 Service。Backend 的 Root Directory 为 `/backend`，使用其中的 `railway.json` 与 Dockerfile。将 Backend 的 `DATABASE_URL` 引用 PostgreSQL Service，例如 `${{Postgres.DATABASE_URL}}`。发布前的 `python -m alembic upgrade head` 由 `railway.json` 的 release command 执行一次，健康检查为 `/api/health`。

## 必填环境变量

| 变量 | 用途与约束 |
| --- | --- |
| `APP_ENV=production` | 生产环境，自动关闭演示商家端点。 |
| `DATABASE_URL` | 引用 Railway PostgreSQL，不手填连接串。 |
| `FRONTEND_ORIGIN` | 精确 Origin；不得为 `*` 或含路径、查询、凭据。 |
| `LLM_API_KEY` | DeepSeek 密钥；配置时必须同时配置 `ADMIN_TOKEN`。 |
| `ADMIN_TOKEN` | 运维端点凭据，生产环境至少 16 字符且非占位值。 |
| `EXPORT_SIGNING_SECRET` | CSV 导出签名密钥，生产环境必填且非占位值。 |
| `TRUSTED_PROXY_HOPS=1` | Railway 单层代理。 |
| `TRUSTED_PROXY_IPS` | 经核实的 Railway 代理直连 IP，逗号分隔。 |
| `RATE_LIMIT_PER_MINUTE` | 单 Token 与可信 IP 的每分钟上限。 |
| `LLM_DAILY_BUDGET_TOKENS` | 每日模型 token 预算。 |

现有代码已强制精确 CORS、生产 JSON 日志、`create_app()` 不启用 Debug，以及数据库连接重试。B8 附件功能尚未实现，不得把正式附件写入容器临时磁盘。

## 运维验收

- 确认 `/api/health` 持续正常，重启 Backend 后数据仍在 PostgreSQL 中。
- 确认生产环境 `/api/demo/merchants` 不可用。
- 超额频率返回 `RATE_LIMITED`；达到模型日预算后显示明确降级。
- `GET /api/admin/ops/status` 仅接受 `X-Admin-Token`，不得返回 Token、Prompt、商家数据或连接串。
- 本地或预发做一次 SIGTERM 验收：发起长 SSE 请求后执行 `docker stop <container-id>`，确认连接以 `done` 或 `error` 收尾，容器在 `backend/app/run.py::GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS`（30 秒）内退出。

## 单 worker 与多实例限制

容器保持单 worker。限流器、运行时可观测性计数与预算估算协调均为进程内状态；多 worker 会使限流与指标失真。`LlmBudgetRepository.reserve` 的数据库条件更新仍可防止预算超发，但多个 Backend 副本只会产生近似的限流与运维计数。需要多副本前，应先引入共享状态存储。
