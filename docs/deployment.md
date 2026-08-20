# Railway 部署与运维手册

本手册只描述部署操作；不会在本地或 Railway 自动写入真实密钥。

## 服务与构建

在同一个 Railway 项目中创建 PostgreSQL 和 Backend 两个 Service。Backend 的 Root Directory 为 `/backend`，使用其中的 `railway.json` 与 Dockerfile。将 Backend 的 `DATABASE_URL` 引用 PostgreSQL Service，例如 `${{Postgres.DATABASE_URL}}`。发布前的 `python -m alembic upgrade head` 由 `railway.json` 的 `deploy.preDeployCommand` 执行一次，健康检查为 `/api/health`。

字段名必须是 `preDeployCommand`：Railway 的配置 schema 里**没有** `releaseCommand`，写成后者不会报错，只会被静默忽略，导致迁移从不执行、线上库始终缺表。

## 前端服务

在同一个 Railway 项目中创建 Frontend Service，并由用户在 Railway 控制台将其 Service Root 设为 `/frontend`。前端使用 Dockerfile 构建，镜像采用 Node 多阶段构建，最终运行镜像为 `caddy:2-alpine`；健康检查路径为 `/health.html`。

Caddy 不代理 `/api`。因此前端域名下不存在任何 API 路径，这是刻意的架构设计；浏览器应使用构建期注入的后端公网地址直接请求 API。

## Railway 配置文件路径

Railway 的 Config File Path 不跟随 Root Directory。即使 Service Root 已设为 `/frontend`，仍必须由用户在前端服务设置中显式填入 `/frontend/railway.json`；后端服务同理显式填入 `/backend/railway.json`。

不得省略此设置：否则两份 `railway.json` 都不会生效，前端健康检查以及后端的 `preDeployCommand`（`alembic upgrade head`）都会静默失效。

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
| `LLM_DAILY_BUDGET_TOKENS` | **全局**每日模型 token 预算——`llm_daily_budget` 表只按 `usage_date` 聚合，不分商家、不分访客，公开演示时所有人共用这一个池子，它是唯一的总量闸门。默认 `500000` = 单请求上限 `25000` × 20，最坏情况也保证 20 个完整问题；按真实模型实测（每问约 6000 token）实际约 80 个。耗尽后所有人收到 `LLM_BUDGET_EXCEEDED` 的可见降级，不会静默继续扣费。 |
| `LLM_MAX_OUTPUT_TOKENS_PER_CALL` | 默认 `4096`。**推理模型不得低于此值**：`deepseek-v4-flash` 单次结构化意图的 `reasoning_tokens` 就要 1400–2200，设为 1024 时正文返回空串，三次重试全废、回落 CHAT 模式——每次提问真实扣费却只得到兜底文案。这是上限不是花费。 |
| `MAX_LLM_TOKENS_PER_REQUEST` | 默认 `25000`，覆盖一轮问答最坏 10 次模型请求。 |
| `MAX_LLM_CALLS_PER_REQUEST` | 默认 `10`。最坏调用路径为 classify 2（业务关键词收到 `INVALID/UNKNOWN` 时重试 1 次）+ understand 3（意图服务自带 2 次重试）+ 指标口径 1 + （回答生成 + 独立复核）× 2 = 10 次，四个调用点共用同一个单请求预算。设低于 10 会让意图重试把质量循环挤成「预算耗尽」降级，把排查方向带偏。 |
| `QUALITY_MAX_ATTEMPTS` | 回答质量循环的最大轮次，代码支持 1–3，默认 `2`。与 `MAX_LLM_CALLS_PER_REQUEST` 联动：每加一轮最多多 2 次模型请求；若设为 `3`，完整最坏路径为 12 次，必须同步提高调用上限。 |
| `LLM_TIMEOUT_SECONDS` | 默认 `90`。推理模型出一次意图耗时明显；超时会被 `DeepSeekLlmClient` 吞成 fallback + degraded，表现为「模型没理解」而不是「超时」，很难查。 |

现有代码已强制精确 CORS、生产 JSON 日志、`create_app()` 不启用 Debug，以及数据库连接重试。B8 附件功能尚未实现，不得把正式附件写入容器临时磁盘。

### Railway 转发头信任策略与回退条件

本项目在 Railway 生产环境使用 `TRUSTED_PROXY_HOPS=1`、留空 `TRUSTED_PROXY_IPS`。留空时，`resolve_client_ip()` 中的 `trusted_proxy_ips and ...` 短路，跳过对直连 peer 的可信判定，即信任任何 peer 送来的转发头。

采用此策略的原因是 Railway 不发布稳定的边界代理地址；静态白名单会在重新部署后静默过期，函数随后返回 peer，令限流无声退化。该策略成立的前提是 Railway 容器没有公网直连入口，公网流量只能经 Railway 边界代理进入。

因此上线后必须完成「转发头伪造验收」：经 Railway 公网域名，使用同一演示 Token，连续发送超过 `RATE_LIMIT_PER_MINUTE` 的请求，并在每次请求中更换 `X-Real-IP`；超限后仍必须返回 429。再以 `X-Forwarded-For` 重复同一测试。记录 429 的实际触发次序。该验收不需要 LLM Key，费用为零。

若任一伪造头能够获得新限流桶（超限后未返回 429），立即将 Railway 配置改为 `TRUSTED_PROXY_HOPS=0`，接受限流收敛为按 Token 的已知可用性限制，并在 `docs/project-progress.md` 记录；后续在 F6 之后改用「按 XFF 最右跳解析」或引入 Redis 限流解决。在得到该实测证据前，不得宣告线上部署验收通过。

## 演示数据的每日滚动

演示库的经营数据有两个写入入口，**互斥**，不得同时生效：

| 入口 | 用途 | 触发方式 |
| --- | --- | --- |
| `python -m app.jobs.seed_demo_rolling` | 唯一常态入口：补齐所有漏跑业务日、清理 180 天窗口外事实，历史分区一行不改写。 | 独立 Cron Service，每日 `10 16 * * *`（UTC，等于 Asia/Shanghai 00:10） |
| `backend/scripts/seed_demo_analytics.py --force-full-rebuild` | 一次性整体重置：先 DELETE 六张经营表该商家全部行再重写。 | 仅人工执行，且必须先停用或跳过一次 Cron |

全量重灌会连同已落库 `answers` 引用的数据依据一起抹掉，因此它已改为必须显式传 `--force-full-rebuild`，缺参数时直接非零退出。

滚动任务的护栏（任一不满足即在写入前失败）：

- `ALLOW_DEMO_DATA_REFRESH=true` 必须显式设置。它是**非密钥但高风险的写权限**，默认 false，绝不下发给前端或写进构建产物；
- 数据库里的商家 UUID 集合必须与三个固定演示商家**精确相等**，多一个少一个都拒绝。真实商家数据库永远不得配置该 Cron Service；
- 校验、追加与窗口清理在同一事务内完成，入口先取 `pg_advisory_xact_lock`，两个实例同时触发时第二个等待而不是交叉写入；
- 只读取 `DATABASE_URL`、`APP_ENV`、`ALLOW_DEMO_DATA_REFRESH`、`BUSINESS_TIMEZONE` 四个变量（`app/core/seed_config.py` 的 `SeedSettings`），**不注入** `LLM_API_KEY`、`ADMIN_TOKEN`、`EXPORT_SIGNING_SECRET`、`FRONTEND_ORIGIN`；
- 随机基线为 `DEMO_ANALYTICS_SEED_BASE = 20260804`，第 i 个演示商家用 `BASE + i`，与全量重灌脚本共用同一常量。

任务本身不跑 Alembic 迁移：启用前先确认同环境 Backend 已迁移到位并通过 `/api/ready`，缺表时任务必须失败退出而不是自动修库。Railway Cron 按 UTC 调度、不保证精确到秒，上一次未结束时可能跳过本次，因此漏跑追赶是正确性要求而非容错优化。

已新增 `backend/railway.cron.json`（无 `healthcheckPath`、无 `preDeployCommand`、`restartPolicyType: NEVER`），不复用 `backend/railway.json`。**Cron Service 尚未创建。** 创建 Service、配置上述四个变量与手工触发首次执行均为 Railway 控制台操作；完成后必须按本节的验收项核对。

## 运维验收

- 确认 `/api/health` 持续正常，重启 Backend 后数据仍在 PostgreSQL 中。
- 非演示生产部署中，确认 `/api/demo/merchants` 不可用；对外演示部署中（`DEMO_DEPLOYMENT_MODE=true`），确认该端点可用且只返回服务端配置的演示商家。
- 超额频率返回 `RATE_LIMITED`；达到模型日预算后显示明确降级。
- `GET /api/admin/ops/status` 仅接受 `X-Admin-Token`，不得返回 Token、Prompt、商家数据或连接串。
- 本地或预发做一次 SIGTERM 验收：发起长 SSE 请求后执行 `docker stop <container-id>`，确认连接以 `done` 或 `error` 收尾，容器在 `backend/app/run.py::GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS`（30 秒）内退出。

## 单 worker 与多实例限制

容器保持单 worker。限流器、运行时可观测性计数与预算估算协调均为进程内状态；多 worker 会使限流与指标失真。`LlmBudgetRepository.reserve` 的数据库条件更新仍可防止预算超发，但多个 Backend 副本只会产生近似的限流与运维计数。需要多副本前，应先引入共享状态存储。
