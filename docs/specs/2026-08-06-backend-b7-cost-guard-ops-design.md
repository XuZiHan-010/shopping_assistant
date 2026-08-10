# B7·Railway、费用防护与 MVP 收口——补测试与剩余基础设施 设计文档

**日期**：2026-08-06
**分支**：`feature/b5-b6-answer-feedback-export`（在既有 worktree 中继续，不新开分支）
**对应计划**：`docs/backend-development-plan.md` §「B7 · Railway、费用防护与 MVP 收口」

## 1. 背景

B6 提交（`b494277`）顺带落地了 B7「LLM 费用与限流」「可信来源 IP」两节的大部分代码：
`app/llm/guard.py`（`LlmCostGuard`）、`app/core/rate_limit.py`（`SlidingWindowRateLimiter`）、
`app/core/client_ip.py`（`resolve_client_ip`）、`app/repositories/llm_budget.py`，均已接入
`main.py`/`dependencies.py`/`chat_service.py` 的运行时路径，`ruff`/`mypy` 全绿，但**零测试覆盖**。
Docker 优雅关闭、Railway 部署配置、`GET /api/admin/ops/status` 运维端点、结构化可观测性四节完全未开始。

详见 `docs/project-progress.md`「当前阶段」与 `docs/backend-development-plan.md` §B7 的 2026-08-06 提醒批注。

## 2. 目标与非目标

**目标**：按 §B7 清单补齐代码层面能做完的全部五块工作（见下），使 §B7 的复选框和「必测」用例可以逐条勾选。

**非目标**：
- 不实际执行 Railway 部署（创建项目、绑定域名、填真实密钥、`railway up`）——这需要用户的 Railway
  账号和真实凭证，本轮只产出配置文件（`railway.json`）和运维手册（`docs/deployment.md`），实际部署
  由用户自行执行。
- 不引入 Redis 或其他外部共享状态——继续遵守「MVP 无 Redis，限流/计数使用进程内实现，多实例下为
  近似值」的既有约束（`docs/backend-development-plan.md` §B7「LLM 费用与限流」）。
- 不新增多 worker/多进程支持——进程内单例（限流器、预算守卫、可观测性计数器）决定了 MVP 阶段保持
  单 worker 是正确选择，本轮只需把这个决策写清楚，不需要真的支持多进程共享状态。

## 3. 五块工作的详细设计

### 3.1 为已上线代码补测试

现状（已用 Explore 调研确认）：

| 模块 | 关键行为 | 现有测试 |
| --- | --- | --- |
| `app/llm/guard.py::LlmCostGuard` | 估算 token → 原子 `reserve` → 调用 → 按实际 token `reconcile`；预算耗尽抛 `LlmDailyBudgetExceededError` 并置位 `daily_cap_hit`；调用失败仍按估算值计费 | 无 |
| `app/core/rate_limit.py::SlidingWindowRateLimiter` | 按 `(token, ip)` 加盐哈希分桶的滑动窗口 | 无 |
| `app/core/client_ip.py::resolve_client_ip` | 不信任跳数为 0 时忽略 XFF；信任跳数 N 时取右起第 N 跳 | 无 |
| `app/repositories/llm_budget.py::LlmBudgetRepository` | `reserve` 用单条件 `UPDATE ... WHERE consumed+n<=budget RETURNING` 做原子扣减 | 无 |

新增测试文件（遵循现有目录约定，见 `backend/tests/` 现有分层）：

- `tests/unit/llm/test_guard.py`——用一个内存版 fake repository（不连真实 DB）覆盖：
  - 正常调用后 `reconcile` 差额，`record_usage` 写 `SUCCEEDED`；
  - `reserve` 返回 `None` → 抛 `LlmDailyBudgetExceededError`，`daily_cap_hit=True`，`record_usage`
    写一条 `BUDGET_REJECTED`（tokens=0）；
  - `inner.complete` 抛异常 → 按估算 token 记 `FAILED` 并重新抛出（对应「请求失败后已消耗的 token
    仍被计费记录」）；
  - `degraded=True` 且 `tokens==0` 的返回 → 记 `FAILED`，不触发 `reconcile`（避免用 0 冲掉已扣的估算值）。
- `tests/unit/core/test_rate_limit.py`——注入可控 fake clock：
  - 同一 key 在窗口内超过 `limit` 次返回 `False`；
  - 窗口滑出后旧记录被驱逐，允许新请求；
  - 不同 `(token, ip)` 对应独立桶，互不影响；
  - 达到 `max_keys` 时新 key 返回 `False`（软上限，不抛异常）。
- `tests/unit/core/test_client_ip.py`——构造 fake `Request`：
  - `trusted_proxy_hops=0` → 无论 `X-Forwarded-For` 是什么，返回 `request.client.host`；
  - `trusted_proxy_hops=1` 且直连 peer 在 `trusted_proxy_ips` 内 → 返回 XFF 链最右一跳；
  - 客户端在 XFF 里塞入任意数量的伪造前缀（如 `X-Forwarded-For: 9.9.9.9, 8.8.8.8, <real-proxy-appended-ip>`）
    → 仍然只取右起第 N 跳，伪造前缀不影响结果（这是「伪造转发头不能重置限流计数」的根因测试）；
  - 直连 peer 不在 `trusted_proxy_ips` 内 → 忽略 XFF，回退 socket 地址。
- `tests/integration/repositories/test_llm_budget_repository.py`（真实 Postgres，`migrated_postgres`/
  `db_session` fixture）——**§B7 明确要求的必测**：
  - 10 个并发 `reserve()`（`asyncio.gather`）逼近预算边界，断言放行数量与最终 `consumed_tokens` 都不
    超过 `budget`，且总放行数等于预算真正能容纳的请求数（不多不少，验证条件更新确实原子，不是宽松地
    "不超发但可能少发"）；
  - `reconcile` 多次调用后 `consumed_tokens` 收敛到实际值；
  - `GREATEST(consumed_tokens + delta, 0)` 在 delta 为负且已接近 0 时不会变成负数。
- `tests/api/test_rate_limit.py`（新文件，走真实 HTTP 客户端）——
  - `trusted_proxy_hops=0`（未信任任何代理，本地默认配置）时，同一连接对 `chat` 端点变换
    `X-Forwarded-For` 头发起超过 `rate_limit_per_minute` 次请求，第 N+1 次仍返回 `RATE_LIMITED`
    （证明伪造头无法绕过）；
  - 配置 `trusted_proxy_hops=1` 且请求方在信任名单内时，两个不同的「下游客户端」（不同 XFF 尾部
    地址）不共享同一限流桶（正向验证功能本身没坏）。

### 3.2 Docker 优雅关闭与 worker 数

- `backend/app/run.py`：给 `uvicorn.run(...)` 显式传入 `timeout_graceful_shutdown=<N 秒>`（建议 30s，
  略小于 Railway 默认的 SIGTERM→SIGKILL 宽限期），并在旁边写明这是为了让在途 SSE 流在关闭前有机会
  收尾，而不是无限等待或直接被杀。
- 单 worker：现状已是（`uvicorn.run` 未传 `workers`，默认为 1）。补一段代码注释 + `docs/deployment.md`
  中的一节，写清楚**为什么不加 worker**：`SlidingWindowRateLimiter`、`LlmCostGuard` 依赖的每日预算的
  「进程内估算-reserve」协调、以及新的可观测性计数器都是进程内状态；多 worker（同容器多进程）会让
  限流和预算判断各算各的，`LlmBudgetRepository.reserve` 虽然在 DB 层是原子的、预算不会真的超发，但
  限流计数会失真。这个决策记录本身满足"设置合理 worker 数量"这条验收，不需要真的引入多进程/共享存储。
- SIGTERM 信号驱动的优雅关闭属于进程级行为，不适合用 `pytest` 单测覆盖（需要真实起停子进程、发信号、
  在关闭窗口内保持一个流式连接打开）。设计上不假装用自动化测试覆盖它，而是在 `docs/deployment.md`
  里写一条手动验收步骤：本地 `docker run` 启动容器、发起一个长 SSE 请求、`docker stop` 触发 SIGTERM、
  确认该请求收到完整响应而非连接被截断。验收记录里会如实标注"手动验证"而非"自动化测试通过"。

### 3.3 结构化可观测性

新增 `app/core/metrics.py::OperationalMetrics`（进程内、与现有 `SlidingWindowRateLimiter` 同等重量级，
不落库、重启归零，多实例下是近似值——与限流器共享同一份"进程内近似"约束，一并在文档中说明）：

```python
class OperationalMetrics:
    rate_limit_hits: int
    degraded_count: int
    error_code_counts: dict[str, int]
    route_durations: dict[str, RunningAverage]       # 路由耗时
    agent_node_durations: dict[str, RunningAverage]  # Agent 节点耗时
```

挂载点：`app.state.metrics = OperationalMetrics()`（`main.py`，与 `app.state.rate_limiter` 同级）。

接入点（均为已存在的单一收口处，不新增分散的埋点）：

- **请求耗时**：扩展 `main.py` 现有的 `request_id_middleware`（改名或就地加逻辑均可，实施计划里定），
  记录路由耗时到 `metrics.route_durations` 并输出一条结构化日志（route、status、duration_ms、
  request_id——不含请求体）。
- **Agent 节点耗时**：`app/agent/graph.py::_build_graph` 里统一包一层计时装饰（对 13 个
  `graph.add_node(...)` 调用做一次性包装，不逐个改节点方法体），写入
  `metrics.agent_node_durations[node_name]` 并输出结构化日志。
- **错误码计数**：`app/core/errors.py::handle_app_error`（唯一处理所有 `AppError` 子类的地方，天然覆盖
  `RATE_LIMITED`、`LLM_BUDGET_EXCEEDED` 等全部错误码）里 `metrics.error_code_counts[exc.code] += 1`。
- **限流命中数**：`dependencies.py::enforce_rate_limit` 抛 `RateLimitedError` 前
  `metrics.rate_limit_hits += 1`（错误码计数已经会算一次，这里单独再记一次是为了让"限流命中"作为独立
  语义字段直接暴露在运维端点里，不需要消费方从 `error_code_counts["RATE_LIMITED"]` 里反查）。
- **降级计数**：`chat_service.py` 中构造最终 `ChatResponse` 且 `degraded=True` 的唯一位置
  `metrics.degraded_count += 1`。
- **LLM 用量与预算剩余**：**不**新增进程内计数器，直接查询既有的 `llm_daily_budget` 表
  （`LlmBudgetRepository.snapshot()`）——这张表本来就是 Postgres 共享状态，多实例下天然正确，比再造一份
  进程内计数更准确也更简单。
- 全程不记录 Prompt 全文、请求体、Token 明文。

### 3.4 运维端点 `GET /api/admin/ops/status`

- 新文件 `app/api/routes/admin.py`。
- `main.py` 中**只在 `resolved_settings.admin_token` 非空时才 `include_router`**——未配置时该路由
  完全不存在，请求会落到 FastAPI 默认的 404，天然满足"未配置管理员令牌时端点整体关闭"，不需要额外
  逻辑伪装成关闭状态。
- 新依赖 `require_admin_token(request, settings)`（`app/api/dependencies.py`）：只读
  `X-Admin-Token`，**完全忽略 `Authorization`**（不注入 `MerchantContext`，该路由不依赖商家身份）；
  缺失 → 401（新增 `AdminTokenRequiredError`，复用现有 `ErrorCode.AUTH_REQUIRED`，消息文案改为
  管理员语境，不新增枚举值）；存在但不匹配 → 403（复用已有的 `AdminForbiddenError`，零新增代码）。
- 响应体（全部是系统级聚合，**不含任何商家标识**，从根源上满足"商家标识需脱敏/不返回商家名称"）：
  - 当日 token 用量、预算剩余（读 `llm_daily_budget` 当日快照）；
  - `rate_limit_hits`、`degraded_count`、`error_code_counts`；
  - 各 Agent 节点平均耗时。
  - 明确不包含：Token 明文、Prompt 内容、商家经营数据、完整请求正文、数据库连接串。
- 测试（`tests/api/test_admin_ops.py`）：未配置 `admin_token` 的 app 实例请求该路径 → 404；配置了但
  请求未带 `X-Admin-Token` → 401；带了错误值（用一个商家 `Authorization` 令牌放进
  `X-Admin-Token` 头，模拟"普通商家 Token"误用场景）→ 403；正确令牌 → 200 且响应体字符串中不出现
  `settings.llm_api_key`、`settings.database_url`、任何 Prompt 片段。

### 3.5 Railway 配置 + 部署手册

- `backend/railway.json`（Railway 配置即代码，优先于纯 Dashboard 手动配置，便于未来重建）：
  - `build`：指向 `backend/Dockerfile`；
  - `deploy.healthcheckPath`: `/api/health`；
  - `deploy.releaseCommand`: 运行 `alembic upgrade head`（Railway 的 release command 语义是"新实例
    接流量前执行一次"，天然满足"Migration 只执行一次"且不需要额外的分布式锁）；
  - `deploy.restartPolicyType`。
- `docs/deployment.md`（新文档，给"新的 coding agent 或人类都能重复完成部署"用，对应 PRD §16 第 26 条）：
  - 两个 Railway Service（Backend Root `/backend`、PostgreSQL）及 `DATABASE_URL` 引用方式；
  - 必需环境变量清单：`LLM_API_KEY`、`ADMIN_TOKEN`、`EXPORT_SIGNING_SECRET`、`FRONTEND_ORIGIN`、
    `APP_ENV=production`、`TRUSTED_PROXY_HOPS=1`、`RATE_LIMIT_PER_MINUTE`、
    `LLM_DAILY_BUDGET_TOKENS` 等，逐项写明用途和从哪本文档能查到取值约束（`config.py` 的字段校验）；
  - 确认现有代码已满足、不需要重复实现的几项：CORS 精确 Origin（`frontend_origin` 校验器已拒绝 `*`
    与非法格式）、生产日志走 JSON（`configure_logging` 已按 `app_env` 切换）、生产关闭 Debug（补一条
    回归测试断言 `create_app()` 从不以 `debug=True` 构造 `FastAPI(...)`，机械钉住这条，而不是仅靠文档
    承诺）、数据库连接重试（`Database.connect_with_retry()` 已存在）；
  - 确认容器临时磁盘不保存正式附件：当前 B8 附件功能未开始，代码里没有任何写本地磁盘的附件逻辑，
    此项在本阶段是可验证的既成事实，文档里写明并标注"进入 B8 时需重新审计"；
  - 手动验收步骤清单（对应 §B7「验收（MVP 出口）」的每一条），包括本节 3.2 提到的 SIGTERM 手动验证。

## 4. 收尾项

- `backend/tests/unit/agent/test_stage_reference_hygiene.py` 的 `CURRENT_STAGE` 从 `"B6"` 改为
  `"B7"`（该文件自身注释和 `docs/project-progress.md` 都要求合并本阶段时更新，否则文案卫生防线会
  继续放过指向 B7 的过期前向引用）。
- 完成前起 `docker-compose -p borough up -d postgres`，跑一次
  `REQUIRE_INTEGRATION_DB=1 pytest`，确认新增的真实 Postgres 用例（3.1 节的并发预算测试等）和此前
  因缺库被跳过的用例全部通过——这是上一轮遗留、尚未执行的验证步骤，本轮一并补上。

## 5. 测试策略总览

| 层级 | 新增文件 | 依赖 |
| --- | --- | --- |
| 单元 | `test_guard.py`、`test_rate_limit.py`、`test_client_ip.py` | 无需数据库 |
| 集成（真实 Postgres） | `test_llm_budget_repository.py` | `migrated_postgres`/`db_session` fixture |
| API | `test_rate_limit.py`（新）、`test_admin_ops.py`（新） | `client`/`postgres_client` fixture |
| 回归 | `create_app()` 从不 `debug=True` | 无需数据库 |

不新增前端相关测试（B7 全部是后端范围）。

## 6. 风险与已知限制

- 进程内限流/预算估算/可观测性计数器在多实例部署下互不同步，只是近似值——这是 MVP 阶段"无 Redis"
  约束的直接后果，已在 `docs/deployment.md` 里写清楚，不在本轮试图解决。
- SIGTERM 优雅关闭无法自动化测试，依赖手动验收记录。
- Railway 实际部署本身（创建项目、真实密钥、验证公网可访问）不在本轮交付范围内，需要用户持有账号
  凭证后自行执行；本轮只保证"文档和配置足够让部署一次做对"。
