# 运维看板增加数据库（Neon）用量

日期：2026-11-19 · 状态：**A 层已在本地实施**。本次按 D1–D4 推荐方案执行，沿用管理员端点、可选容量上限与待办箱聚合。B 层延期。验证范围与结果见 `docs/project-progress.md` 文首。

## 一、背景

线上主库是外部 Neon PostgreSQL（`docs/deployment.md`）。当前没有任何地方能看到它的用量：

- `GET /api/admin/ops/status` 只返回 LLM 预算、成本、限流、降级、工具错误率和 p95（`backend/app/api/routes/admin.py`）；
- 代码里没有任何地方调用 `pg_database_size` 一类的函数；
- 只读运维看板 `frontend/src/components/ops/OpsStatusPanel.vue` 因此也没有数据库这一块。

已知会持续增长、目前没有清理任务的表：`messages`（聊天原文）、`memory_extraction_jobs`（处理完成的
`DONE` 行一直保留）。记忆卡片表本身有上限（固定的规范键 + 唯一约束），不会撑满库。

目标：管理员在运维看板上能看到库有多大、哪几张表最大、离上限还有多远、连接数，以及记忆待办箱有没有积压。

## 二、两层数据来源

| | A 层：用现有 `DATABASE_URL` 查系统目录 | B 层：调 Neon 管理 API |
| --- | --- | --- |
| 能看到 | 库的逻辑大小、各表大小与估算行数、连接数、记忆待办箱积压 | 和账单口径一致的存储与计算用量 |
| 新密钥 | 不需要 | 需要 `NEON_API_KEY`（R6 密钥） |
| 套餐限制 | 任何套餐都能用 | 用量 v2 接口 `/consumption_history/v2/projects` 只对 Launch、Scale、Business、Enterprise 等付费套餐开放；旧接口里的存储字段已弃用，固定返回 0 |
| 局限 | 不知道套餐上限，需要手动配置；逻辑大小不等于 Neon 计费存储（后者还包括历史与分支） | 新增外部依赖与出站调用；要改 AGENTS R6 与 §十一 |

**本计划的主体是 A 层。** B 层单列在第七节，是否做由 D1 裁定。

## 三、方案选择

| 编号 | 问题 | 推荐 |
| --- | --- | --- |
| D1 | 是否做 B 层（Neon API） | **先不做**。先确认 Neon 账号的套餐：免费套餐拿不到 v2 用量接口，做了也没有数据 |
| D2 | 新开一个端点，还是扩展 `ops/status` | **扩展 `ops/status`**，只新增字段。新开路径要先改 PRD §11 与 AGENTS §8.1，代价更大 |
| D3 | 存储上限从哪来 | 可选配置 `DATABASE_STORAGE_LIMIT_BYTES`（非密钥），按用户最新要求默认 1 GB（1073741824 字节，沿用看板 1024 进制），未设置或空白均使用默认值，可按套餐覆盖 |
| D4 | 是否顺带显示记忆待办箱积压 | **显示**。查询便宜，而且是唯一能看出后台抽取是否卡住的地方 |

下面按推荐方案写。裁定结果不同时，改对应任务即可。

## 四、契约（A 层）

先改 `docs/backend-development-plan.md` §9 B7「运维端点」节，再写代码。和前两次扩展一样，**只新增字段**，
既有字段语义不变，端点仍然**只允许管理员**访问（`VIEWER_TOKEN` 继续 403）。

### 4.1 `OpsStatusResponse` 新增字段

| 字段 | 类型 | 语义 |
| --- | --- | --- |
| `database_usage` | `DatabaseUsage \| null` | 本次请求时采集的数据库用量；采集失败时为 `null` |
| `database_usage_error` | `"TIMEOUT" \| "UNAVAILABLE" \| null` | 采集失败的原因码；成功时为 `null`。失败必须在页面上显示出来，不能显示成 0（同 R7 的原则） |

### 4.2 `DatabaseUsage`

| 字段 | 类型 | 语义 |
| --- | --- | --- |
| `collected_at` | `datetime` | 采集时刻（UTC） |
| `database_size_bytes` | `int≥0` | `pg_database_size(current_database())`，逻辑大小 |
| `storage_limit_bytes` | `int>0 \| null` | 取自 `DATABASE_STORAGE_LIMIT_BYTES`，默认 1073741824；未设置或空白均使用默认值 |
| `storage_used_ratio` | `number \| null` | `database_size_bytes / storage_limit_bytes`；没有上限时为 `null`，不显示成 0% |
| `max_connections` | `int≥0` | `current_setting('max_connections')` |
| `connections_total` / `connections_active` | `int≥0` | `pg_stat_activity` 中本库的连接总数与 `state='active'` 的连接数 |
| `top_tables` | `TableUsage[]` | `public` schema 中按总大小（含索引与 TOAST）降序的前 10 张表 |
| `memory_outbox` | `MemoryOutboxStatus` | 记忆待办箱各状态的任务数 |

`TableUsage`：`table_name: str`、`total_bytes: int≥0`、`estimated_rows: int≥0 | null`
（取自 `pg_class.reltuples`，表从未 ANALYZE 时为 `-1`，此时返回 `null`）。

`MemoryOutboxStatus`：`pending`、`processing`、`failed`、`done`（均为 `int≥0`）、
`oldest_pending_age_seconds: int≥0 | null`（没有 `PENDING` 时为 `null`）。

### 4.3 禁止返回（沿用并加强）

- 不得返回连接串、主机名、端口、用户名、数据库名（`current_database()` 的值也不返回）；
- 不得返回任何表的行内容，只返回表名、字节数、估算行数；
- `pg_stat_activity` 只计数，不返回 `query`、`usename`、`client_addr` 等列。

## 五、实施任务（A 层）

### Task 1 · 文档先行（PRD → 契约）

- `docs/PRD.md` §10.4：「运维看板展示……」后补「数据库逻辑大小、主要表大小、连接数与记忆待办箱积压」，
  并补一句「`ops/status` 不返回连接串与数据库标识」；
- `docs/backend-development-plan.md` §9 B7「运维端点」节：新增「2026-11-19 扩展」小节，内容即本计划第四节；
- 验收：两份文档的字段名、类型和本计划一致；PRD §11 路径清单不变。

### Task 2 · 后端配置

- `backend/app/core/config.py`：新增 `database_storage_limit_bytes: int | None = Field(default=1024**3, gt=0)`；
- `.env.example` 加占位注释（非密钥，可留空）；
- 单测：未配置或空白时为 1073741824；支持正整数覆盖；配置成 0 或负数时启动失败。

### Task 3 · 后端仓库层

新建 `backend/app/repositories/database_usage.py`，提供
`DatabaseUsageRepository(database).collect(limit_bytes: int | None) -> DatabaseUsage`。

要求：

- 在一个**只读事务**里执行：`SET TRANSACTION READ ONLY` + `SET LOCAL statement_timeout = '2s'`；
- SQL 全部是固定文本，没有任何拼接，表数上限用绑定参数；
- 超时（`QueryCanceled`）映射为 `TIMEOUT`，其他数据库错误映射为 `UNAVAILABLE`。
  由路由层捕获后给出 `database_usage=None` 与对应原因码，**不让整个 `ops/status` 因此 500**。

参考 SQL：

```sql
-- 库大小与连接上限
SELECT pg_database_size(current_database()) AS database_size_bytes,
       current_setting('max_connections')::int AS max_connections;

-- 最大的表（只看普通表）
SELECT c.relname AS table_name,
       pg_total_relation_size(c.oid) AS total_bytes,
       CASE WHEN c.reltuples < 0 THEN NULL ELSE c.reltuples::bigint END AS estimated_rows
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind = 'r' AND n.nspname = 'public'
ORDER BY pg_total_relation_size(c.oid) DESC
LIMIT :limit;

-- 连接数（只计数）
SELECT count(*) AS connections_total,
       count(*) FILTER (WHERE state = 'active') AS connections_active
FROM pg_stat_activity
WHERE datname = current_database();

-- 记忆待办箱
SELECT status, count(*) AS n, min(created_at) AS oldest
FROM memory_extraction_jobs
GROUP BY status;
```

说明：这四条都只读系统目录或聚合计数，不需要额外授予数据库权限。经 Neon 连接池代理连接时，
`pg_stat_activity` 反映的是计算节点上的后端连接，不等于浏览器侧的并发数，看板文案要写明。

### Task 4 · 路由与 Schema

- `backend/app/api/routes/admin.py`：新增 `TableUsage`、`MemoryOutboxStatus`、`DatabaseUsage` 三个模型，
  在 `OpsStatusResponse` 末尾加两个字段；`ops_status()` 调用仓库层，捕获失败并填写原因码；
- `storage_used_ratio` 在路由层计算，没有上限时为 `None`。

### Task 5 · 后端测试

- **仓库集成测试**（一次性 pgvector 测试库，沿用现有集成测试夹具）：
  - 所有数值非负；`top_tables` 不超过 10 行，按 `total_bytes` 降序，包含 `messages`；
  - 插入 2 条 `PENDING`、1 条 `FAILED` 任务后，计数与 `oldest_pending_age_seconds` 正确；
  - 把超时设得极小或 mock 成 `QueryCanceled` 时，返回 `TIMEOUT`。
- **API 测试**（扩展 `backend/tests/api/test_admin_ops.py`）：
  - 管理员 200，包含 `database_usage`；`VIEWER_TOKEN` 仍为 403；无令牌 401；
  - 响应体不含 `postgresql`、测试库主机名、用户名和数据库名（沿用现有的敏感字样断言并补充）；
  - 仓库层抛错时，200 + `database_usage=null` + 对应原因码，其余字段照常返回；
  - 配置上限时比例正确，未配置时为 `null`。
- 全程不涉及 LLM，不需要 R3 审批。

### Task 6 · OpenAPI 与生成类型

- 导出 OpenAPI，更新 `docs/api.json` 与 `docs/api.md`；
- 运行两端 codegen 更新 `generated.ts`，两端 `codegen:check` 必须通过；`generated.ts` 不手改。

### Task 7 · 前端

字段只按这条链流动：`generated.ts → api/adapters/adminOps.ts → types/opsStatus.ts → OpsStatusPanel.vue`。

- `types/opsStatus.ts`：新增 `DatabaseUsage`、`TableUsage`、`MemoryOutboxStatus`（camelCase）；
  `OpsStatus` 加 `databaseUsage: DatabaseUsage | null`、`databaseUsageError: 'TIMEOUT' | 'UNAVAILABLE' | null`；
- `adminOps.ts`：映射新字段，`null` 原样透传，字节数不在 Adapter 里格式化；
- `OpsStatusPanel.vue`：在「运行状态」之后新增一块「数据库」卡片：
  - 大小用 KB / MB / GB 显示；有上限时显示进度条与百分比，**≥80% 用警告色，≥95% 用危险色**；
  - 卡片说明写明「逻辑大小，不等于 Neon 计费存储；套餐上限以 Neon 控制台为准」；
  - 最大表做成表格：表名、大小、估算行数（`null` 显示「暂无」）；
  - 连接数显示「活跃 / 总数 / 上限」；
  - 记忆待办箱显示四个计数和最老待处理时长；`failed > 0` 或最老待处理超过 30 分钟时高亮；
  - `databaseUsage === null` 时显示「数据库用量读取失败（超时 / 不可用）」，不显示成 0；
- `i18n/locales/zh-CN.ts`、`en-US.ts` 补文案（R1：两种显示语言都要有）；
- 测试：`adminOps.spec.ts` 覆盖映射与 `null`；`OpsStatusView.spec.ts` 或 Panel 测试覆盖正常、
  有上限且超过 80%、无上限、读取失败四种状态。

### Task 8 · 文档收尾

- `docs/deployment.md`：变量表加 `DATABASE_STORAGE_LIMIT_BYTES`，说明按 Neon 套餐手填、可留空；
- `docs/project-navigation.md`：§八 计划清单登记本文件；文件职责表登记 `repositories/database_usage.py`；
- `docs/project-progress.md`：完成后更新当前阶段、验证结果与风险。

## 六、验收

| 项 | 命令或证据 |
| --- | --- |
| 后端 | `uv run ruff check .`、`uv run mypy`、`uv run pytest`（至少本次相关单测、API 测试与集成测试，注明是否全量） |
| 前端 | `npm run test`、`npm run typecheck`、改动文件的 ESLint / Prettier、`npm run build`、`npm run codegen:check` |
| 顾客端 | `codegen:check`（只更新生成类型，不改界面） |
| 安全 | API 测试断言响应不含连接串、主机名、用户名、数据库名；`VIEWER_TOKEN` 403 |
| 降级可见 | 仓库层失败时看板显示失败原因，不显示 0 |
| LLM | 全程不调用；无需 R3 审批 |

**不在本次验收内**：对线上 Neon 执行任何写操作、线上部署、Git 提交（R2）。上线后在线上看板核对一次数字，
并和 Neon 控制台的存储数对比，确认差异在预期之内（逻辑大小小于计费存储属于正常）。

## 七、B 层：Neon 管理 API（仅在 D1 选「做」时执行）

前置条件：

1. 用户在 Neon 控制台确认套餐支持用量 v2 接口；
2. 用户自行创建 API Key（建议用项目级或组织级的只读用途 Key），放进 Railway Variables；
3. **先改 AGENTS.md**：R6 密钥清单新增 `NEON_API_KEY [可选]` 与 `NEON_PROJECT_ID`；
   §十一 写明 Backend 会出站调用 `console.neon.tech`。这属于稳定约束变化，按 §十二 维护。

设计要点：

- 只在后端调用，`Authorization: Bearer <NEON_API_KEY>`，超时 3 秒；Key 绝不下发前端、不进日志；
- 进程内缓存 15 分钟，避免每次刷新看板都调外部接口（按官方文档，查询用量不会唤醒计算节点）；
- 契约新增 `neon_consumption: NeonConsumption | null` 与
  `neon_consumption_status: "NOT_CONFIGURED" | "OK" | "PLAN_UNSUPPORTED" | "UPSTREAM_ERROR"`；
- **`NeonConsumption` 的具体字段在实施前按官方 API 文档核对后再写进契约**，本计划不预先写死。
  已知存储相关指标包括 `root_branch_bytes_month`、`child_branch_bytes_month`、`instant_restore_bytes_month`、
  `snapshot_storage_bytes_month`；
- 测试一律 mock HTTP，不在自动化测试里访问真实 Neon。

## 八、风险与限制

- 逻辑大小和 Neon 计费存储口径不同，只能用来看趋势，不能拿来对账单；
- 每次刷新看板都会连库查询。Neon 计算节点空闲挂起时，会被这次查询唤醒，计入计算时长；看板是管理员手动刷新，
  影响很小，但不要给它加自动轮询；
- `pg_stat_activity` 经连接池代理后只反映计算节点侧的连接；
- 本计划**只观测、不治理**：`memory_extraction_jobs` 的 `DONE` 行清理、`messages` 的保留策略需要另立计划，
  这涉及数据保留的产品决策，不在本次范围。

## 九、建议分工

按个人规则：主 Agent（Opus）负责契约文档（Task 1）和最终验收；后端 Task 2–5 与前端 Task 7
各交给一个 Sonnet 子代理。两者改动的文件不重叠，可以在 Task 6 生成类型之后并行。
派发时须写明 R2（不提交）、R3（不调真实 LLM）、R8（不改只读目录）。
