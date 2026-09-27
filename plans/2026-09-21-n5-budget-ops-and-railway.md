# N5 三级预算、运维看板与 Railway 部署实施计划

> **给执行者：** 用 `superpowers:executing-plans` 逐任务推进。步骤用 `- [ ]` 复选框跟踪。
> **本计划不含任何 Git 提交步骤**（R2）。
> **Railway 控制台操作、生产数据库迁移、把真实 `LLM_API_KEY` 配到公网实例，均属生产变更，
> 每一项执行前单独取得用户同意**（`AGENTS.md` §三）。真实 LLM 调用另受 R3 约束。

**目标：** 实现 PRD §10.2 三级预算与成本价格版本绑定、§10.4 运维看板与追踪 ID、
§10.7 Railway 五服务部署与 Cron 统一接线，达到**公开部署的前置条件**。

**架构：** 预算在既有 `app/llm/guard.py` 的全局日预算之上扩展角色与商家两级，
**不另起一套**。Cron 是**幂等短任务**，不是通用 Worker（Q34）。

**技术栈：** FastAPI、PostgreSQL（advisory lock）、Railway、Docker。

**规格来源：** PRD §10.2–§10.4、§10.7；`AGENTS.md` R3、R6、§十一；`docs/deployment.md`；
融合决策 Q23、Q34、Q37。

---

## 入口条件

> **预写计划不是已验证实现。** 本计划写于上游代码尚不存在时，文中引用的类名、函数签名、
> 工具名、表字段、错误码都是**当时的设计**。开工前逐项对照上游**实际落地**的接口；
> 不一致时先按 PRD → 契约 → 计划的顺序修正，**再动代码**，不得在实现里默默适配或绕过。

- [ ] N2–N4 全部计划已完成；
- [ ] `n5-mcp-readonly` 已完成——**只卡 Task 5 步骤 4（Railway 部署）与 Task 6**；Task 1–4 与 MCP 计划没有代码依赖，
      可并行（2026-09-27 编组放宽，见 `plans/2026-09-27-n5-module-roadmap.md` §三）；
- [ ] **逐条核对 `docs/deployment.md` 的现状**——本计划基于写作时的内容，
      部署文档可能在 N2–N4 期间被更新。

> **2026-09-27 编组核对**（见 `plans/2026-09-27-n5-module-roadmap.md` §二），开工前按此修正：
>
> 1. **看板前端文件已不存在**：`frontend/src/views/OpsDashboardView.vue` 随 2026-09-27 两页合并下线，
>    `/api/admin/ops/status` 目前没有任何前端消费方。Task 3 的前端载体属待裁定 D-N5-1（见 N5 总览 §六）。
> 2. **Cron 配置已有 3 份**，不是 2 份：`railway.cron.json`（`seed_demo_rolling`）、`railway.chatbi-cron.json`
>    （`chatbi_rollup`）、`railway.provenance-cron.json`（`purge_guest_provenance`，N2 新增）。
>    另有 `close_expired_orders`、`expire_drafts`、`rebuild_projections` 三个任务模块**没有任何调度配置**；
>    操作证据 nonce 清理**尚无任务模块**。Task 4 的任务表已按此补齐。
> 3. **`llm_usage` 已有 `request_id` 与 `purpose` 列**（`app/models/operations.py`），缺角色、价格版本与缓存命中 token；
>    `X-Request-Id` 目前只在 `app/main.py` 与安全评测工具中出现，未贯穿工具调用。
> 4. 既有 `LlmCostGuard` 只有全局日预算（`llm_daily_budget_tokens`），Task 1 的角色级、商家级都是新增。

---

## 全局约束

- 中文（R1）；**不执行 Git 操作**（R2）；**不调用真实 LLM**（R3）。
- **公开部署的三项前置条件**（`AGENTS.md` §十一）：基础限流、单请求 LLM 上限、每日预算熔断。
  **三项未全部验证前，不得把真实 `LLM_API_KEY` 部署到公网地址。**
- 数据库迁移**在发布阶段单独执行**，不由 Backend 或 Cron 实例并发执行（PRD §8.2、Q34）。
- CORS 只允许 `shop` 与 `merchant` 两个精确 Origin，**不使用 `*`**。
- `/api/admin/ops/status` 继续**禁止返回** Token、Prompt、经营数据与完整请求正文。

---

## Cron 任务的一条总原则

N2–N4 各计划顺延到这里的定时任务，全部遵守：

> **Cron 只负责清理，不负责正确性。**
> 任何"超时 / 过期"的判定，**都必须在业务读写路径上自行检查截止时间**；
> Cron 迟跑、漏跑、跳跑，业务结果都不能变。

这条原则已在以下计划中落实，本计划的 Task 4 **再逐项核对一遍**：

| 任务 | 业务路径上的自检 | 来源计划 |
| --- | --- | --- |
| 关闭超时订单 | 支付时检查 30 分钟截止 | `n2-trade-closed-loop` Task 4 |
| 草稿过期 | 应用时检查 `expires_at` | `n2-merchant-drafts-and-inventory` Task 4 |
| 操作证据 nonce 清理 | 消费时条件更新检查 `expires_at` | `n2-merchant-drafts-and-inventory` Task 3 |
| 顾客记忆 180 天过期 | 读取时过滤 | `n4-memory-pipeline` Task 4 |

Railway Cron 按 UTC 调度、不保证精确到秒、上一次未结束时可能跳过本次（`docs/deployment.md`）。
**依赖 Cron 准时的正确性设计，在 Railway 上必然出错。**

---

## 文件结构

| 文件 | 责任 |
| --- | --- |
| `backend/app/llm/guard.py` | 扩展为三级预算 |
| `backend/app/llm/pricing.py` | 模型价格版本表与成本计算 |
| `backend/app/models/*` | `llm_usage` 补价格版本、角色；新增 `model_price_versions` |
| `backend/app/core/tracing.py` | `X-Request-Id` 贯穿 |
| `backend/app/jobs/run_scheduled.py` | Cron 分发器 |
| `backend/app/api/routes/admin_ops.py` | 看板数据扩展 |
| 看板前端（原 `OpsDashboardView.vue` 已下线） | 载体按 D-N5-1 裁定；推荐新建只读 `frontend/src/views/OpsStatusView.vue`，走 `X-Admin-Token`（可用 `VIEWER_TOKEN`） |
| `backend/railway.cron.json` | 统一 Cron 配置 |
| `docs/deployment.md` | 五服务上线步骤 |

---

### Task 1：三级预算（§10.2、Q37）

在既有全局日预算之上增加两级，**三级同时生效，任一耗尽即熔断**：

| 级别 | 作用 | 耗尽后 |
| --- | --- | --- |
| 全局 | 整个平台每日上限（既有） | 全部 LLM 路径降级 |
| 角色 | 顾客 / 商家各自每日上限 | 该角色降级，另一角色不受影响 |
| 商家 | 单店每日上限 | 该店降级，其他店不受影响 |

**为什么需要角色级**：顾客端是公开的，流量不可控。若只有全局预算，
一波顾客流量就能耗尽预算，让所有商家的工作台一起降级。角色级把两端的风险隔开。

- 预算耗尽按既有 §8.5 规则归为 `FAILED_RETRYABLE`，跨日重置后同一 `client_request_id` 可重试；
- 预算检查在**发出请求前**完成（沿用 `deepseek.py` 先扣后发的做法）；
- **非对话调用同样计入三级预算**（2026-09-27 编组补充）：记忆抽取（N4）、压缩摘要（N4）、简报预生成（N3）
  按所属角色与商家计入角色级、商家级，并全部计入全局级。N4 的「记忆独立预算」只是**单次任务的调用上限**，
  不是游离在每日熔断之外的额度；`llm_usage.purpose` 已有，可直接区分来源。

- [ ] **步骤 1：写失败测试**

```python
async def test_customer_traffic_cannot_exhaust_merchant_budget(guard) -> None:
    await exhaust(guard, role="CUSTOMER")
    assert await guard.allow(role="MERCHANT", merchant=M) is True


async def test_one_shop_cannot_exhaust_another(guard) -> None:
    await exhaust(guard, role="MERCHANT", merchant=M_A)
    assert await guard.allow(role="MERCHANT", merchant=M_B) is True


async def test_global_exhaustion_stops_everything(guard) -> None:
    await exhaust(guard, level="GLOBAL")
    assert await guard.allow(role="CUSTOMER", merchant=M) is False
    assert await guard.allow(role="MERCHANT", merchant=M) is False


async def test_budget_checked_before_request_sent(guard, spy_http) -> None:
    await exhaust(guard, role="MERCHANT", merchant=M)
    with pytest.raises(LlmDailyBudgetExceededError):
        await call_llm(role="MERCHANT", merchant=M)
    assert spy_http.request_count == 0
```

- [ ] **步骤 2：确认失败 → 实现 → 确认通过**

---

### Task 2：成本绑定价格版本（§10.2）

**成本按调用当时的价格版本计算，不用当前价格回算历史**。

- 新表 `model_price_versions`：`id`、`model`、`input_price_per_mtok`、`output_price_per_mtok`、
  `cache_hit_price_per_mtok`、`effective_from`；价格以 `Decimal` 存储；
- `llm_usage` 每行记录 `price_version_id`，**成本在写入时算好并存储**，查询时不重算；
- 价格变动时**新增一行版本**，不修改旧行；
- 缓存命中 token 单独记录（A9 的计量部分），**缓存不作为正确性依赖**（Q23）。

- [ ] **步骤 1：写失败测试**

```python
async def test_historical_cost_unchanged_after_price_update(db) -> None:
    await record_usage(tokens_in=1000, at=DAY1)            # 按 v1 价格
    cost_before = await total_cost(db, day=DAY1)
    await add_price_version(model="deepseek-flash", input_price="9.99", effective_from=DAY2)
    assert await total_cost(db, day=DAY1) == cost_before


async def test_price_rows_are_append_only(db) -> None:
    with pytest.raises(Exception):
        await db.execute("UPDATE model_price_versions SET input_price_per_mtok = 0")
```

价格表同样用 `BEFORE UPDATE OR DELETE` 触发器强制追加写——理由与事件账本相同。

- [ ] **步骤 2：确认失败 → 实现 → 确认通过**

**价格数值从 DeepSeek 官方文档核实后录入**（O7：核实官方文档零费用），并在迁移注释里写明
核实日期与出处。**不得凭记忆填写价格**。

---

### Task 3：追踪 ID 与运维看板（§10.4）

- `X-Request-Id` 贯穿**前端 → 后端 → 工具调用 → 评测报告**：前端生成，后端缺失时补生成，
  写入每条日志、每个 `ToolDisplay`、每条 `llm_usage`、每份评测报告条目；
- 看板展示：**三级预算余量**、限流命中、降级计数（按整轮与单来源分开）、工具错误率、p95 延迟、
  缓存命中率与节省 token；
- `/api/admin/ops/status` 的禁止返回项保持不变。

- [ ] **步骤 1：写失败测试**

```python
async def test_request_id_propagates_to_tool_and_usage_rows(client, db) -> None:
    await chat(client, headers={"X-Request-Id": "trace-abc"})
    assert (await latest(db, "llm_usage")).request_id == "trace-abc"


async def test_ops_status_never_leaks_forbidden_fields(client) -> None:
    body = json.dumps((await client.get("/api/admin/ops/status", headers=ADMIN)).json())
    for leak in (DEMO_TOKEN, "system_prompt", "gross_gmv", SESSION_ID):
        assert leak not in body
```

- [ ] **步骤 2：确认失败 → 实现 → 确认通过**
- [ ] **步骤 3：看板前端按 D-N5-1 裁定落地**（2026-09-27 编组新增）——组件测试断言页面不渲染 Token、Prompt、
      经营数据或请求正文；`VIEWER_TOKEN` 只读访问正常，写操作按钮不存在；`npm run test`、`typecheck`、`build` 通过

---

### Task 4：Cron 统一接线

PRD §10.7 定义**一个** `cron` 服务。仓库已有 `railway.cron.json`（演示数据滚动）、
`railway.chatbi-cron.json`（Chat BI 汇总）与 `railway.provenance-cron.json`（访客来源状态清理）三份配置，
**均尚未在 Railway 创建**；三份合并为一份指向分发器。

**做法：单一分发器**。`cron` 服务每 5 分钟运行 `python -m app.jobs.run_scheduled`，
分发器依次检查每个任务是否到期，到期则执行。每个任务：

- **幂等、可重入、短任务**（Q34）；
- 用 **PostgreSQL advisory lock** 防止重叠执行——Railway 上一次没跑完时可能再起一次；
- 接受 `now` 参数，**不读墙钟**；
- 支持**漏跑追赶**（`docs/deployment.md`：追赶是正确性要求）；
- 失败只记录并继续下一个任务，**一个任务失败不阻塞其他任务**。

| 任务 | 频率 | 来源计划 |
| --- | --- | --- |
| 演示数据滚动 `seed_demo_rolling` | 每日 | 既有 |
| Chat BI 汇总 `chatbi_rollup` | 每日 | 既有 |
| 本地化缓存清理 `purge_expired_machine` | 每日 | 既有，**至今无调用方**（进度快照风险项） |
| 访客来源状态清理 `purge_guest_provenance` | 每日 | 既有（N2 顾客端），已有独立 Cron 配置，并入分发器 |
| 关闭超时订单 `close_expired_orders` | 每 5 分钟 | `n2-trade-closed-loop`；任务模块已存在，无调度配置 |
| 草稿过期 `expire_drafts` | 每小时 | `n2-merchant-drafts-and-inventory`；任务模块已存在，无调度配置 |
| 操作证据 nonce 清理 | 每小时 | `n2-merchant-drafts-and-inventory`；**尚无任务模块**，本 Task 新建 |
| 订单投影漂移检查 `rebuild_projections` | 每日（只报告不修复） | 既有（N2）；是否纳入定时属可选，纳入则只写报告 |
| 记忆抽取 outbox 排空 `drain_memory_outbox` | 每 5 分钟 | `n4-memory-pipeline` Task 3；**调用 LLM，走记忆独立预算**；真实 Key 未授权时 Fake 或关闭 |
| 顾客记忆过期清理 | 每日 | `n4-memory-pipeline` |
| 商家记忆总结重建 | 每小时 | `n4-memory-pipeline` |
| 索引构建 | 按需（文档变更后） | `n4-hybrid-retrieval` |
| 每日简报预生成 | 每日 | `n3-merchant-skills`，**默认关闭** |

最后一行：简报预生成会调用 LLM，**默认关闭**（D18⑩）；开启即产生真实费用，属 R3 范围。

- [ ] **步骤 1：写失败测试**

```python
async def test_overlapping_runs_do_not_double_execute(db_pool) -> None:
    await asyncio.gather(run_scheduled(now=T), run_scheduled(now=T))
    assert await executions_of("close_expired_orders", at=T) == 1


async def test_one_failing_job_does_not_block_others(monkeypatch) -> None:
    monkeypatch.setattr(jobs, "chatbi_rollup", raising(RuntimeError))
    report = await run_scheduled(now=T)
    assert report["chatbi_rollup"] == "FAILED"
    assert report["close_expired_orders"] == "OK"


async def test_missed_days_are_caught_up(db) -> None:
    await set_last_run("chatbi_rollup", day=T - timedelta(days=3))
    await run_scheduled(now=T)
    assert await rollup_days(db) >= {T - timedelta(days=2), T - timedelta(days=1)}


def test_brief_pregeneration_disabled_by_default() -> None:
    assert "daily_brief" not in due_jobs(Settings(), now=T)
```

- [ ] **步骤 2：确认失败 → 实现 → 确认通过**
- [ ] **步骤 3：逐项核对「Cron 只负责清理」原则**——对上表每个带过期语义的任务，
      确认其来源计划中存在"业务路径自检截止时间"的测试，并在本地关闭 Cron 的情况下跑一遍

---

### Task 5：Railway 五服务

| Service | Root | 说明 |
| --- | --- | --- |
| `shop` | `/shop` | `n2-shop-nextjs-app` 已备好 Dockerfile |
| `merchant` | `/frontend` | 由现有 `frontend` Service **改名**（`AGENTS.md` §十一） |
| `backend` | `/backend` | FastAPI，监听 `PORT` |
| `postgres` | Railway Database | **启用 `vector` 扩展**（N4） |
| `cron` | `/backend` | `railway.cron.json`，无健康检查，`restartPolicyType: NEVER` |

**本任务在本地写完全部配置与文档；每一项 Railway 控制台操作执行前单独征得同意。**

- [ ] **步骤 1：写配置**——三份既有 Cron 配置合并为一份，指向分发器
- [ ] **步骤 2：更新 `docs/deployment.md`**——五服务拓扑、上线顺序、变量清单、
      pgvector 启用、`merchant` 改名步骤
- [ ] **步骤 3：本地 `docker compose` 起全部服务，跑一遍 S1–S8 的 Fake LLM E2E**
- [ ] **步骤 4：请求用户授权后执行 Railway 部署**，顺序：
      postgres 启用扩展 → **单独执行迁移** → backend → cron → shop / merchant

**迁移只在步骤 4 的第二项执行一次**，不让 backend 或 cron 在启动时自动迁移。

---

### Task 6：公开部署前置条件验收

**三项全部通过才允许配置真实 `LLM_API_KEY`**。每项验收零费用。

| 前置条件 | 验收方式 |
| --- | --- |
| 基础限流 | 经公网域名连续请求超过 `RATE_LIMIT_PER_MINUTE`，**每次更换 `X-Real-IP` 与 `X-Forwarded-For`**，超限后仍返回 429（`docs/deployment.md`「转发头伪造验收」） |
| 单请求 LLM 上限 | `AGENT_LOOP_MAX_LLM_CALLS` 与 v1 `MAX_LLM_CALLS_PER_REQUEST` 在生产配置中生效，Fake 注入下触顶返回降级 |
| 每日预算熔断 | 三级预算各设极小值，确认熔断生效且降级对用户可见 |

- [ ] **步骤 1：逐项执行并记录结果**到 `docs/history/deploy-preflight-<date>.md`
- [ ] **步骤 2：三项全过后，向用户报告并请求配置真实 Key 的授权**——
      这一步同时属于生产变更与 R3 范围，**两项授权都要有**

---

### Task 7：自检

```powershell
cd backend
rg -n "datetime.now\(\)|date.today\(\)" app/jobs/
rg -n "alembic upgrade" railway*.json Dockerfile
uv run pytest; uv run ruff check .; uv run mypy app
```

第一条期望零命中（任务不读墙钟）；第二条期望零命中（**启动时不自动迁移**）。

更新 `docs/project-progress.md`：三级预算、价格版本、Cron 接线、部署状态、
**前置条件验收结果**、是否已配置真实 Key 及对应授权记录。

---

## 本计划明确不做的事

| 不做 | 归属 |
| --- | --- |
| 通用 Worker、对象存储、Redis | 本版不建（Q34）；Redis 仅在多实例共享限流有证据时另行评审 |
| Doris | 未达引入条件（`AGENTS.md` §七） |
| 全量评测报告与对外演示 | `n5-final-eval-and-closeout` |
