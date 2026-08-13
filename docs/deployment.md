# Railway 部署与运维手册

本手册只描述部署操作；不会在本地或 Railway 自动写入真实密钥。

## 服务与构建

在同一个 Railway 项目中创建 PostgreSQL 和 Backend 两个 Service。Backend 的 Root Directory 为 `/backend`，使用其中的 `railway.json` 与 Dockerfile。将 Backend 的 `DATABASE_URL` 引用 PostgreSQL Service，例如 `${{Postgres.DATABASE_URL}}`。发布前的 `python -m alembic upgrade head` 由 `railway.json` 的 release command 执行一次，健康检查为 `/api/health`。

## 前端服务

在同一个 Railway 项目中创建 Frontend Service，并由用户在 Railway 控制台将其 Service Root 设为 `/frontend`。前端使用 Dockerfile 构建，镜像采用 Node 多阶段构建，最终运行镜像为 `caddy:2-alpine`；健康检查路径为 `/health.html`。

Caddy 不代理 `/api`。因此前端域名下不存在任何 API 路径，这是刻意的架构设计；浏览器应使用构建期注入的后端公网地址直接请求 API。

## Railway 配置文件路径

Railway 的 Config File Path 不跟随 Root Directory。即使 Service Root 已设为 `/frontend`，仍必须由用户在前端服务设置中显式填入 `/frontend/railway.json`；后端服务同理显式填入 `/backend/railway.json`。

不得省略此设置：否则两份 `railway.json` 都不会生效，前端健康检查以及后端的 `releaseCommand`（`alembic upgrade head`）都会静默失效。

## 前端环境变量

以下变量由用户在 Railway 前端服务中配置：

| 变量 | 必填 | 说明 |
| --- | --- | --- |
| `VITE_API_BASE_URL` | 是 | 后端公网地址，在**构建期**注入静态产物。修改后必须重新构建并部署前端；只改变量但不重新部署不会生效。 |
| `VITE_USE_MOCK` | 否 | 生产环境必须不设或设为 `false`。设为 `true` 会使镜像构建直接失败；Dockerfile 已声明对应的构建参数。 |

`VITE_` 前缀变量会内联进公开的静态产物，绝不能用来配置任何密钥、Token 或连接串。

## 演示部署模式

`DEMO_DEPLOYMENT_MODE=true` 是仅用于对外演示部署的显式开关。开启后，生产环境的 `/api/demo/merchants` 可访问，前端才能取得并选择演示商家身份；不开启时该端点关闭，前端无法选择商家。

可通过携带 `X-Admin-Token` 的 `/api/admin/ops/status` 查看当前演示部署模式。演示 Token 只授予演示数据访问权；商家数据隔离仍由后端强制注入 `merchant_id` 保证。

## 上线顺序

前端 API 地址在构建期固化，而后端 CORS 又必须获知前端 Origin；同时后端首次启动前已要求提供 `FRONTEND_ORIGIN`。因此，用户需在 Railway 控制台按以下顺序完成双侧部署：

1. 在首次部署后端前，为 `FRONTEND_ORIGIN` 填入一个精确、临时且非敏感的 Origin，或填入已预先绑定的前端域名。该值必须含协议，不含路径和尾斜杠，且不得为 `*`。
2. 部署后端。
3. 获取后端公网域名。
4. 以该域名作为 `VITE_API_BASE_URL` 构建并部署前端。
5. 获取前端实际公网域名。
6. 将后端 `FRONTEND_ORIGIN` 替换为此前端实际的精确 Origin（含协议、不含路径和尾斜杠）。
7. 重新部署后端，使精确 CORS 配置生效。

这不是可互换的顺序：首次后端启动需要一个有效的精确 Origin，前端又需要已部署后端的公网地址；待前端实际域名确定后，必须替换临时 Origin 并再次部署后端。

## 必填环境变量

| 变量 | 用途与约束 |
| --- | --- |
| `APP_ENV=production` | 生产环境默认自动关闭演示商家端点；仅当显式设置 `DEMO_DEPLOYMENT_MODE=true` 时例外。 |
| `DATABASE_URL` | 引用 Railway PostgreSQL，不手填连接串。 |
| `FRONTEND_ORIGIN` | 精确 Origin；不得为 `*` 或含路径、查询、凭据。 |
| `DEMO_DEPLOYMENT_MODE=true` | 对外演示时必填；显式允许生产环境访问 `/api/demo/merchants`。非演示生产部署不设置或设为 `false`，端点保持关闭。 |
| `LLM_API_KEY` | DeepSeek 密钥；配置时必须同时配置 `ADMIN_TOKEN`。 |
| `ADMIN_TOKEN` | 运维端点凭据，生产环境至少 16 字符且非占位值。 |
| `EXPORT_SIGNING_SECRET` | CSV 导出签名密钥，生产环境必填且非占位值。 |
| `TRUSTED_PROXY_HOPS=1` | Railway 单层代理。 |
| `TRUSTED_PROXY_IPS` | **留空，不填任何值。** Railway 不发布稳定的边界代理地址；配置具体值会在重新部署后静默失效并导致限流退化，因此本项目明确不配置该变量。 |
| `RATE_LIMIT_PER_MINUTE` | 单 Token 与可信 IP 的每分钟上限。 |
| `LLM_DAILY_BUDGET_TOKENS` | 每日模型 token 预算。 |

现有代码已强制精确 CORS、生产 JSON 日志、`create_app()` 不启用 Debug，以及数据库连接重试。B8 附件功能尚未实现，不得把正式附件写入容器临时磁盘。

### Railway 转发头信任策略与回退条件

本项目在 Railway 生产环境使用 `TRUSTED_PROXY_HOPS=1`、留空 `TRUSTED_PROXY_IPS`。留空时，`resolve_client_ip()` 中的 `trusted_proxy_ips and ...` 短路，跳过对直连 peer 的可信判定，即信任任何 peer 送来的转发头。

采用此策略的原因是 Railway 不发布稳定的边界代理地址；静态白名单会在重新部署后静默过期，函数随后返回 peer，令限流无声退化。该策略成立的前提是 Railway 容器没有公网直连入口，公网流量只能经 Railway 边界代理进入。

因此上线后必须完成「转发头伪造验收」：经 Railway 公网域名，使用同一演示 Token，连续发送超过 `RATE_LIMIT_PER_MINUTE` 的请求，并在每次请求中更换 `X-Real-IP`；超限后仍必须返回 429。再以 `X-Forwarded-For` 重复同一测试。记录 429 的实际触发次序。该验收不需要 LLM Key，费用为零。

若任一伪造头能够获得新限流桶（超限后未返回 429），立即将 Railway 配置改为 `TRUSTED_PROXY_HOPS=0`，接受限流收敛为按 Token 的已知可用性限制，并在 `docs/project-progress.md` 记录；后续在 F6 之后改用「按 XFF 最右跳解析」或引入 Redis 限流解决。在得到该实测证据前，不得宣告线上部署验收通过。

## 运维验收

- 确认 `/api/health` 持续正常，重启 Backend 后数据仍在 PostgreSQL 中。
- 非演示生产部署中，确认 `/api/demo/merchants` 不可用；对外演示部署中（`DEMO_DEPLOYMENT_MODE=true`），确认该端点可用且只返回服务端配置的演示商家。
- 超额频率返回 `RATE_LIMITED`；达到模型日预算后显示明确降级。
- `GET /api/admin/ops/status` 仅接受 `X-Admin-Token`，不得返回 Token、Prompt、商家数据或连接串。
- 本地或预发做一次 SIGTERM 验收：发起长 SSE 请求后执行 `docker stop <container-id>`，确认连接以 `done` 或 `error` 收尾，容器在 `backend/app/run.py::GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS`（30 秒）内退出。

## 单 worker 与多实例限制

容器保持单 worker。限流器、运行时可观测性计数与预算估算协调均为进程内状态；多 worker 会使限流与指标失真。`LlmBudgetRepository.reserve` 的数据库条件更新仍可防止预算超发，但多个 Backend 副本只会产生近似的限流与运维计数。需要多副本前，应先引入共享状态存储。
