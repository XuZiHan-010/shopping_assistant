# N5 阶段总览：A / B / C / D 四阶段的划分、依赖、难度与出口标准

> **本文件是 N5 的总览，不是实施计划。** 它只回答四件事：N5 拆成哪几个阶段、每个阶段落在框架的哪一层、
> 难点在哪、怎样算完成。逐步骤的做法在各阶段自己的实施计划里；本文件与它们冲突时以实施计划为准，
> 并回头修正本文件。
> **进度只在 `docs/project-progress.md` 维护**；下文「状态快照」标注了日期，过期以进度快照为准。
> **本文件不含任何 Git 提交步骤**（R2），也不触发任何 LLM 调用（R3）；**也不授权任何 Railway 或生产操作**。
> 写法仿照 `plans/2026-09-24-n3-module-roadmap.md`。
> **2026-09-28 修订**：D-N5-1 至 D-N5-3 已由用户裁定（采纳推荐方案），见 §六；D-N5-2 的主体已随 N3 收尾完成，只剩复核。
> **2026-09-28 再修订（PRD §15「W」）**：商家工作台界面重设计插在 N4 剩余任务之前（`plans/2026-09-28-merchant-workbench-redesign.md`）。它对 N5 的影响：
> - B Task 3 步骤 3 的运维看板放进侧栏「管理」分组，复用 W 的管理员令牌入口；
> - D Task 1 路由对账以 PRD 当前 53 条路径为准，含 W 新增的 3 条；
> - D Task 7 在新界面上演示；
> - D Task 9 步骤 1a 以 W 改过入口后的 E2E 为准。
> 
> 各计划对应位置已同步。
>
> 同日另有**顾客端店面重设计 WS**（`plans/2026-09-28-shop-storefront-redesign.md`），它对 N5 的影响：
> - 不新增路径，只改顾客端商品列表参数与订单摘要字段，D Task 1 对账不受影响；
> - D Task 7 顾客端在新外壳上演示，商品图片未交付时如实演示“暂无图片”占位；
> - D Task 9 步骤 1a 复核的顾客端 E2E 以 WS Task 13 改过入口后的版本为准。

**目标：** 给 N5（PRD §15「MCP 与运维收尾」）画一张可核对的地图：切成 A、B、C、D 四个阶段，
写清每阶段的范围、撞点、**费用与生产变更点**与出口标准，并把 2026-09-21 预写的三份 N5 计划按
**N3 实际代码与 N4 编组结果**重新编组。N5 是最后一个里程碑，D 阶段的完成定义就是整条 N1–N5 路线的完成定义。

**规格来源：** `docs/PRD.md` §15 N5、A8、A9、§10.1–§10.4、§10.7、§11.1、§12 全节、§14、E1–E6、S8；
`docs/backend-development-plan.md` §6.9、§8.14.3；`AGENTS.md` R2、R3、R6、§三、§8.3、§十一；
`docs/deployment.md`；审查点见 `plans/2026-09-22-astra-checklist.md` §八。

---

## 一、总览表

| 阶段 | 框架层 | 实施计划（`plans/2026-09-21-*.md`） | 步骤 | 难度 | 收口 | 费用 / 生产变更 |
| --- | --- | --- | --- | --- | --- | --- |
| **0** 入口核对与 N4 收口 | 审查 + 裁定 | Astra「入口-N5」；N4 完成定义（N4 总览 §五） | — | — | — | 否 |
| **A** MCP 只读服务 | 协议入口：`app/mcp/`、凭证表与 CLI、`POST /api/v2/merchant/mcp` | `n5-mcp-readonly` | 14 | 高（鉴权顺序 + 即时撤销） | **S8** | 否 |
| **B** 预算、成本与可观测 | `app/llm/guard.py`、价格版本、`X-Request-Id`、看板 | `n5-budget-ops-and-railway` Task 1–3（含入口条件） | 10 | 中高（预算隔离） | §10.2、§10.4 | 否 |
| **C** Cron 与 Railway 部署 | `app/jobs/run_scheduled.py`、单一 Cron 配置、五服务上线、公开部署前置验收 | `n5-budget-ops-and-railway` Task 4–7 | 9 | 高（生产变更） | §10.7、公开部署前置条件 | **生产变更逐项同意**；配真实 Key 另需 R3 |
| **D** 全量评测与收口 | 路由对账、§12 验收矩阵、性能基准、E1–E6、演示、文档 | `n5-final-eval-and-closeout` | 35 | 中（量大）/ 高（真实性） | §12 全部、§10.1 | 性能基准需生产变更同意；真实评测需 R3 |
| | | | **68** | | | |

步骤数按各计划 `- [ ]` 复选框计数，**含入口条件**。三份计划原合计 65 步（13 + 18 + 34），本次编组后为 68 步。
`n5-budget-ops-and-railway` 一份计划拆给 B、C 两个阶段：前三个 Task 是纯本地代码，后四个 Task 起涉及 Railway，
**风险性质不同，出口与审查也分开**。

### 与 PRD §15 N5 各条的对应

| PRD N5 条目 | 阶段 |
| --- | --- |
| MCP 只读服务与可撤销受限凭证（A8） | A |
| 三级预算、看板、成本价格版本绑定（§10.2、§10.4） | B |
| Railway 五服务部署与 Cron 幂等任务（§10.7） | C |
| 全量评测报告、双端对外演示、文档收口 | D |

N5 只新增 **1 条** v2 路径 `POST /api/v2/merchant/mcp`（A）。2026-09-28 以 PRD §11.2 对 `docs/api.json` 预跑：
PRD 50 条、已导出 44 条、缺 6 条（N4 记忆 5、N5 MCP 1）、多 0 条。D Task 1 在收口时以 `app.routes` 重跑，
期望缺 0、多 0。

难度与 N4 不同：N5 的代码量不大，**危险来自「上线」与「宣称」两件事**。C 的每一步 Railway 操作都是生产变更，
错一步可能让真实 Key 暴露在没有熔断的公网实例上；D 的风险是把 Fake 结构验证、局部通过或待授权项写成「全量通过」——
`AGENTS.md` §三明确禁止，而这类错误恰好在收尾时最容易犯。

---

## 二、为什么按这个方式切，以及编组时补上的缺口

### 与原计划的差异

1. **`n5-budget-ops-and-railway` 拆成 B、C 两段。** Task 1–3（三级预算、价格版本、追踪 ID 与看板）全部可在本地用 Fake LLM
   与真实 PostgreSQL 完成；Task 4–7 从 Cron 分发器起一路走到 Railway 部署与公开前置验收。前者按普通开发节奏推进，
   后者每一步都要停下来征得同意。放在一个阶段里，会让「本地已全绿」被误读成「可以上线」。
2. **A 与 B、C 本地部分并行。** 原预算计划入口写「`n5-mcp-readonly` 已完成」，但两者没有代码依赖；
   只有 C 的 Railway 部署需要 MCP 一起上线。已放宽为「只卡 Task 5 步骤 4 与 Task 6」。
3. **D 保持一份计划不拆。** 它不新增功能，只证明前面的交付达标；拆开会让「矩阵里的证据」与「报告里的结论」分属两处而漂移。

### 按实际代码补上的缺口

| 缺口 | 证据 | 补在 |
| --- | --- | --- |
| MCP 白名单 7 个工具中 `attribute_change` 未标 `MCP_READONLY` | 契约 §8.14.3；`app/tools/merchant/metrics.py:164` 只有 `ToolRole.MERCHANT`；`registry.surface_for_mcp()` 已存在（`app/tools/registry.py:99`） | **A Task 0**：补角色，并用「白名单与注册表双向相等」的测试防止以后漂移；MCP 输出不含 `chart_data` |
| **看板前端已不存在**：`OpsDashboardView.vue` 随 2026-09-27 两页合并下线（工作树删除，尚未提交） | `frontend/src/views/` 无该文件；`/api/admin/ops/status` 无前端消费方 | **B Task 3 步骤 3**：按 **D-N5-1** 新建只读 `OpsStatusView.vue` |
| **PRD 内部冲突**：§14 需求迁移表写「Chat BI 运维看板 · 保留并扩展 · §10.4」，但 §15 N2 的两页合并裁定下线了承载它的页面与 Chat BI 组件 | `docs/PRD.md` §14、§15 N2 | **D-N5-1** 已裁定：B Task 3 步骤 3 的第一件事是改 PRD §14 这一行，再写页面 |
| 三级预算、价格版本都是新增：`LlmCostGuard` 只有全局日预算；`llm_usage` 已有 `request_id` 与 `purpose`，缺角色、价格版本、缓存命中 token | `app/llm/guard.py`；`app/models/operations.py` | **B Task 1–2**；Task 1 补一条：记忆抽取、压缩摘要、简报预生成这些**非对话调用同样计入三级预算** |
| `X-Request-Id` 只出现在 `app/main.py` 与安全评测工具，未贯穿工具调用与 `llm_usage` 写入路径 | `rg X-Request-Id app` | **B Task 3** |
| Cron 配置已有 **3 份**（原计划写 2 份）；`close_expired_orders`、`expire_drafts`、`rebuild_projections` 有任务模块但无调度；操作证据 nonce 清理**连任务模块都没有**；N4 新增 outbox 排空、记忆过期、总结重建、索引构建 | `backend/railway*.json`；`app/jobs/` | **C Task 4** 任务表已补齐 |
| Railway Postgres 需要 pgvector；本地镜像由 N4 C Task 2 步骤 0 切换 | `docker-compose.yml`；N4 总览 §二 | **C Task 5**：上线顺序第一步「postgres 启用扩展」先确认 Railway 方案支持 |
| 两页合并时整份删除 4 份前端 E2E（`conversation.spec.ts` 13 例、`ops-dashboard.spec.ts`、`localization.spec.ts`、`real-api/analytics.spec.ts` 8 例），原因是 v2 层缺少 fetch Mock 基础设施 | `docs/project-progress.md` 2026-09-27 | **D-N5-2**：会话目录 5 例、双语 2 例已于 2026-09-27 用 `e2e/support/v2MerchantMock.ts` 重建；`ops-dashboard.spec.ts` 随新看板重写；`real-api/analytics.spec.ts` 不在浏览器层重建。剩余复核在 N4 阶段 0 与 **D Task 9 步骤 1a** |
| 收口复核表只列了 2026-09-21 的 7 项裁定，此后又有 5 项 | `n5-final-eval-and-closeout` Task 9 | **D Task 9** 已补录，含 D-N4-1 至 D-N5-3 六项裁定 |

---

## 三、依赖与执行顺序

### 阶段级依赖

```text
0 入口核对与 N4 收口 ──┬──→ A MCP 只读 ─────────────────────┐
                       ├──→ B 预算、成本与可观测 ──┐         ├──→ C Task 5 步骤 4 部署 → C Task 6 前置验收 ──→ D
                       └──→ C Task 4（Cron 分发器）┴─────────┘
   A ‖ B ‖ C Task 4（本地）；部署之后一切串行
```

### 任务级依赖（比阶段级更精确，以此为准）

| 下游 | 上游 | 说明 |
| --- | --- | --- |
| A、B、C、D 全部 | 阶段 0：N4 整体完成（N4 总览 §五） | PRD 里程碑顺序；也保证 C Task 4 要接线的 N4 任务模块已存在 |
| A Task 1 起 | A Task 0；开工当天核对 MCP SDK 对 `2026-07-28` 的支持 | SDK 默认旧协议时必须显式配置版本，并保留握手被拒的反例测试 |
| B Task 3 步骤 3（看板前端） | PRD §14 先改（D-N5-1 已裁定） | 契约先行，再写页面 |
| C Task 4 | N4 B Task 3、4、5（outbox 排空、记忆过期、总结重建）与 N4 C（索引构建）的任务模块 | 分发器只调度已存在的模块 |
| C Task 5 步骤 3（本地 compose 跑 S1–S8） | A Task 4（S8）；N3、N4 的场景测试 | S8 在 A 之前无法跑 |
| C Task 5 步骤 4（Railway 部署） | A、B、C Task 4 全部完成；**用户逐项同意** | 顺序：postgres 启用扩展 → 单独执行迁移 → backend → cron → shop / merchant |
| C Task 6（公开部署前置验收） | B Task 1（三级预算）；C Task 5 步骤 4 | 三项全过才可请求配置真实 Key |
| 配置真实 `LLM_API_KEY` | C Task 6 三项全过；**生产变更同意 + R3 同意，两项都要** | `AGENTS.md` §十一 |
| D Task 3（性能基准） | 部署完成；Railway 基准环境**另行同意**（生产变更） | 聊天相关指标用 Fake LLM 测系统开销 |
| D Task 4 步骤 4（真实模型评测） | R3 授权 | 未授权则报告写明「真实模型质量未评测」 |
| D Task 7（对外演示） | 部署完成 | 演示脚本按 S1–S8 组织 |
| D Task 8（v1 退役准备） | D Task 1、2 | 只准备清单与公告，**不删除任何 v1 代码**；是否退役由用户决定 |

### 并行与冲突规则

1. **Alembic 链**：A（`mcp_credentials`）与 B（`model_price_versions`、`llm_usage` 新列、价格表追加写触发器）各自新增迁移。
   创建前后确认 `uv run alembic heads` 恰好一个 head。**生产库迁移只在 C Task 5 步骤 4 第二项执行一次**，
   不由 backend 或 cron 启动时自动执行（C Task 7 自检）。
2. **`docs/api.json` 与生成类型**：A 新增 MCP 路径，B 可能扩展 `/api/admin/ops/status` 响应。导出串行化；
   两份 `generated.ts` 禁止手改。MCP 入口的请求 / 响应用 SDK 协议类型，**不另造信封模型**（契约 §8.14.3）。
3. **`app/main.py` 与中间件**：B 的追踪 ID 贯穿与 A 的 MCP 路由鉴权都会动应用装配。MCP 路由**不得挂上 `X-Session-Id` 依赖**，
   追踪中间件也不得在鉴权前解析 MCP 正文。两者串行改，改后同时跑 A 的鉴权顺序测试与 B 的追踪测试。
4. **`docs/deployment.md`**：由 C 统一改写。A 的凭证 CLI 用法、B 的新环境变量（三级预算上限等）以要点交给 C，
   不在 C 改写期间并行编辑同一文件。
5. **安全集**：A 登记 S8「撤销后仍可调用即失败」（`introduced_in: N5`）。`CURRENT_MILESTONE` 在 N4 收尾切到 `"N4"`，
   **只在 D 阶段收尾切到 `"N5"`**。
6. **Railway 控制台**：只有 C 的执行者操作，每一项执行前单独取得用户同意，执行结果写进 `docs/history/deploy-preflight-<date>.md`。
   **同意是按次的**：同意「部署 backend」不延伸到「配置真实 Key」。
7. **推荐顺序：** 0 →（A ‖ B ‖ C Task 4）→ C Task 5 步骤 1–3 → 【同意】C Task 5 步骤 4 → C Task 6 →
   【同意 + R3】真实 Key → D（Task 1、2、5、6、9 可先在本地做；Task 3、4、7 等部署与授权）。

**提速方案（D-N5-3 已裁定：默认不启用）：** A 只依赖 N3 的商家只读工具，功能上不依赖 N4，但 A 与 N4-A 都由 Opus 负责，
提前会让 MCP 与改 `runner.py` 的 N4-A 抢同一个执行者。因此**默认按里程碑顺序**。用户提出时间节点（例如求职演示日期）时，
启用预先定好的折中：**Opus 完成 N4-A 后立即接做 N5-A**，与 Sol、Sonnet 收尾 N4-B、N4-C 并行；里程碑验收仍在 N4 之后，
Astra 审查编号与批次不变。启用时只需在进度快照登记，不必重新编组。

### 费用点与生产变更点

| 类型 | 事项 | 所在任务 | 未同意时 |
| --- | --- | --- | --- |
| 生产变更 | 创建 Railway 五服务、`frontend` 改名 `merchant`、启用 pgvector、执行生产迁移、部署 | C Task 5 步骤 4 | 停在「本地配置与文档写完、compose 跑通」 |
| 生产变更 | 公开部署前置验收（经公网域名打限流、打熔断） | C Task 6 步骤 1 | 前置条件标「未验收」，**不得配置真实 Key** |
| 生产变更 + R3 | 在公网实例配置真实 `LLM_API_KEY` | C Task 6 步骤 2 | 公网实例只跑 Fake LLM |
| 生产变更 | Railway 基准环境部署与灌数 | D Task 3 步骤 2 | 性能报告标「未执行」，不用本地数字替代 |
| R3 | 真实模型全量评测、LLM 裁判 | D Task 4 步骤 4 | 报告写明「真实模型质量未评测」 |
| R3 | 每日简报预生成 Cron（默认关闭） | C Task 4 | 保持关闭 |
| 生产变更 | 线上签发 MCP 凭证 | A 之后（计划只在本地测试库签发） | 线上不签发 |

N5 所有本地开发与自动化验证零费用。**上表每一项都要单独取得同意，并写明次数与费用上限；「执行 N5 计划」不构成其中任何一项的授权。**

---

## 四、阶段详情

### 阶段 0 · 入口核对与 N4 收口

- **内容：**
  1. **N4 收口**：N4 总览 §五 的 8 项完成定义，含 `CURRENT_MILESTONE` 切到 `"N4"`、E5 三份报告、四层同步 D-N4-1 至 D-N4-3；
  2. **Astra「入口-N5」**：逐份核对三份 N5 计划入口条件与 N4 **最终**接口（本次编组已预核对，见 §二）。
- **性质：** 审查，无 N5 业务代码。D-N5-1 至 D-N5-3 已裁定，不再阻塞。

### 阶段 A · MCP 只读服务（`n5-mcp-readonly`）

- **落点：** 新建 `app/mcp/`（`credentials.py`、`server.py`）；`models/mcp_credential.py` 与迁移；`scripts/mcp_credentials.py`（issue / revoke / list）；
  路由 `api/routes/v2/merchant_mcp.py`；`tests/integration/mcp/test_standard_client.py`。
- **覆盖路径：** `POST /api/v2/merchant/mcp`（GET 返回 405）。
- **任务：** **0 工具面与契约对齐**（`attribute_change` 补角色）→ **1 凭证**（CLI 签发、指纹存储、即时撤销）→
  **2 协议头与鉴权顺序** → 3 工具面投影 → **4 标准客户端集成测试与 S8** → 5 自检。
- **难度「高」的依据：**
  - 鉴权必须在解析 JSON-RPC 正文**之前**：未认证请求连解析器都碰不到；
  - 撤销后下一次请求立即 401，校验结果**一秒都不能缓存**；
  - 协议固定 `2026-07-28`，不实现旧 `initialize`，不接收也不签发 `Mcp-Session-Id`；SDK 若默认旧协议，Mock 测试会跟着错；
  - `merchant_id` 只从凭证解析，与商家会话走同一注入路径；审批证据、确认令牌、完整明细、`chart_data` 一律不外发。
- **出口标准：** S8 标准客户端集成测试通过：MCP 与工作台的同一指标**数值、截至时间、定义版本逐项一致**，撤销后 401；
  白名单与注册表双向相等；无任何凭证 HTTP 路径；Astra **N5-1、N5-2** 必审通过。
- **本阶段不做：** MCP 写工具、顾客侧 MCP、商家自助凭证页、完整 OAuth 授权流程（A8）。

### 阶段 B · 预算、成本与可观测（`n5-budget-ops-and-railway` Task 1–3）

- **落点：** `app/llm/guard.py` 扩展为全局 / 角色 / 商家三级；`app/llm/pricing.py`、`model_price_versions` 表（追加写触发器）；
  `llm_usage` 补角色、价格版本、缓存命中 token；`app/core/tracing.py`；`api/routes/admin_ops.py` 看板数据；看板前端（D-N5-1）。
- **任务：** **1 三级预算**（含非对话调用归属）→ **2 成本绑定价格版本** → 3 追踪 ID 与看板（含**步骤 3 看板前端**）。
- **难度「中高」的依据：**
  - 角色级的意义是**顾客端公开流量不能拖垮商家工作台**，商家级是一家店不能耗尽另一家；测试要证明隔离，而不只是「能扣减」；
  - 预算检查在发请求**之前**，耗尽时 HTTP 请求数为 0；
  - 成本在写入时按当时价格版本算好并存储，价格变动只追加新行，历史成本不重算；价格数值从 DeepSeek 官方文档核实（O7），**不得凭记忆填写**；
  - `/api/admin/ops/status` 的四类禁止返回项（Token、Prompt、经营数据、完整请求正文）扩展看板后仍不得出现。
- **出口标准：** Task 1–3 全绿、零费用；三级隔离、先查后发、价格追加写、追踪 ID 贯穿到 `llm_usage` 各有测试；
  `OpsStatusView.vue` 落地且只读，PRD §14 已改；Astra **N5-3** 中预算部分通过。
- **本阶段不做：** 任何 Railway 操作；Redis（仅在多实例共享限流有证据时另行评审）。

### 阶段 C · Cron 与 Railway 部署（`n5-budget-ops-and-railway` Task 4–7）

- **落点：** `app/jobs/run_scheduled.py`（单一分发器，advisory lock、接受 `now`、漏跑追赶、单任务失败不阻塞）；
  nonce 清理任务模块；三份 Cron 配置合并为 `backend/railway.cron.json`；`docs/deployment.md` 五服务拓扑与上线顺序；
  `docs/history/deploy-preflight-<date>.md`。
- **任务：** **4 Cron 统一接线**（含「Cron 只负责清理」逐项核对）→ **5 Railway 五服务**（步骤 4 需同意）→
  **6 公开部署前置条件验收** → 7 自检（任务不读墙钟、启动不自动迁移）。
- **难度「高」的依据：**
  - Railway Cron 按 UTC 调度、不保证准时、上一次未结束可能跳过；**任何过期判定都必须在业务路径自检**，Cron 迟跑漏跑结果不变；
  - 两个分发器实例重叠时同一任务只执行一次；
  - 生产迁移只执行一次，不由任何实例启动时自动执行；
  - 限流验收必须**每次更换 `X-Real-IP` 与 `X-Forwarded-For`**，证明后端不采信客户端转发头；
  - 三项前置条件任一未过，真实 Key 就不能进公网实例。
- **出口标准：** 本地 `docker compose` 起全部服务，S1–S8 Fake LLM E2E 通过；分发器的重叠、失败隔离、追赶各有测试；
  经同意完成部署后，三项前置条件在公网域名上逐项验收并记录；是否配置真实 Key 及对应两项授权如实记入进度快照；
  Astra **N5-3** 中前置条件部分通过、**N5-4** 抽审完成。
- **本阶段不做：** 通用 Worker、对象存储、Doris；全量评测与演示（D）。

### 阶段 D · 全量评测与收口（`n5-final-eval-and-closeout`）

- **落点：** `backend/scripts/audit_routes.py`；`docs/specs/<date>-n5-acceptance-matrix.md`；`docs/history/perf/`；
  `docs/history/eval/n5-full-report.md`；E6 回流脚本与互斥测试；`docs/demo-script.md`；v1 退役就绪清单与弃用公告草稿；
  `docs/project-progress.md`、`docs/project-navigation.md` 最终快照。
- **任务：** 1 路由覆盖对账 → **2 PRD §12 验收矩阵**（§12.1 任一未过即停止收口）→ 3 §10.1 性能基准 →
  **4 E1–E5 全量评测报告** → 5 E6 线上反馈回流 → 6 冻结基线最终对照 → 7 双端对外演示 → 8 v1 退役准备（不执行退役）→
  **9 文档收口与一致性复核**（含**步骤 1a 前端 E2E 缺口复核**）。
- **难度的依据：** 代码量小，风险在**宣称**：
  - 矩阵每一格都要指向可运行证据，状态只有「通过 / 未通过 / 待授权 / 未执行」四种，不允许「基本满足」；
  - 时序侧信道阈值（各 500 次、中位数差 ≤ 10ms、p95 比值 0.8–1.25）必须在本地独占测试库上跑并记录机器配置；
  - Fake LLM 的结构验证不能写成质量验证；评测集 `skip` 不计入分母；
  - 调优集与最终测试集按案例指纹互斥，回流脚本不得写评测集。
- **出口标准：** 即 `n5-final-eval-and-closeout`「完成的定义」：路由对账缺 0、多 0；§12.1 全部通过；
  性能报告附原始统计；评测报告区分 Fake 与真实；全部裁定四层一致。Astra **N5-5** 抽审完成。
- **本阶段不做：** 新功能；删除 v1 代码（交用户决定）。

---

## 五、N5 整体完成定义（= N1–N5 路线完成定义）

N5 完成当且仅当：

1. A、B、C、D 各自满足出口标准，Astra N5-1、N5-2、N5-3 必审通过，N5-4、N5-5 抽审完成；
2. 路由对账以 `app.routes` 为准：PRD §11.2 的 v2 路径**缺 0、多 0**；附件三个端点不存在；v1 端点全部仍在；
3. PRD §12.1 安全与隔离**全部通过**；§12.2–§12.6 每条状态如实，「待授权」「未执行」单独列出；
4. S1–S8 八条主场景按 §12.2 规定的层级各有可重复证据（S1–S4 浏览器 E2E、S5–S7 工作台 E2E、S8 标准 MCP 客户端）；
5. 公开部署前置条件三项已在公网验收；真实 Key 是否配置、依据哪两项授权，如实记录；
6. 性能报告与全量评测报告存在，写明数据快照、并发数、版本、原始统计，以及哪些是 Fake、哪些是真实模型；
7. `CURRENT_MILESTONE` 为 `"N5"`，关键安全集零失败；冻结基线 `test_frozen_graph_nodes_unchanged` 仍通过，`graph.py` 未部署到生产；
8. 前端 E2E 缺口按 D-N5-2 处置完毕：D Task 9 步骤 1a 的四行各有落点（已重建 / 已重写 / 列出替代证据文件），没有被静默略过；
9. 所有裁定（D Task 9 两张表）在 PRD、契约、实现与测试中一致；`docs/project-progress.md`、`docs/project-navigation.md` 为最终快照；
   仅当稳定约束变化时更新 `AGENTS.md`；`git status --porcelain vendor/ "yshopping-merchant-ai 4/" yshopping-prototype/` 无输出（R8）。

任何一项不成立时，在进度快照中**如实写明缺什么**，不宣称 N1–N5 全量完成。

---

## 六、裁定记录（2026-09-28 用户采纳推荐方案）

原「待裁定」三项已由用户裁定，**PRD 已于 2026-09-28 同步**（§14 Chat BI 运维看板一行、§15 N5），前端计划同步第 15 条。
本节只记录结论与落点，权威定义以 PRD 为准。

| 编号 | 问题 | 裁定 | 落点 |
| --- | --- | --- | --- |
| **D-N5-1** | 运维看板的前端载体（PRD §14「Chat BI 运维看板保留并扩展」与 2026-09-27 下线 `OpsDashboardView.vue` 冲突） | **新建只读管理员页 `OpsStatusView.vue`**：一页合并 Chat BI 概览与 §10.4 指标；走 `X-Admin-Token`，`VIEWER_TOKEN` 只读；不恢复旧页，旧页只用 `git show HEAD:` 只读参考；范围为表格加至多两张趋势图 | 先改 PRD §14 与 `docs/frontend-development-plan.md`；`n5-budget-ops-and-railway` Task 3 步骤 3 |
| **D-N5-2** | 两页合并时删除的 4 份前端 E2E | **会话目录与双语用轻量 `page.route` 类型化打桩重建**（2026-09-27 已完成 5 + 2 例，`e2e/support/v2MerchantMock.ts`）；`ops-dashboard.spec.ts` 随新看板重写为 `ops-status.spec.ts`；`real-api/analytics.spec.ts` **不在浏览器层重建**，以后端集成、`tests/e2e/` 场景与安全集为替代证据；**剩余复核提前到 N4 阶段 0**（§12.4 逐条对照、§10.6 缺译文回退标注），不等到 N5 | N4 总览阶段 0；`n5-final-eval-and-closeout` Task 9 步骤 1a |
| **D-N5-3** | A（MCP）是否提前 | **默认不提前**；用户提出时间节点时启用折中「Opus 完成 N4-A 后接做 N5-A」（§三） | 排期，不改 PRD |

**后置裁定（不在开工前决定）：** v1 端点是否退役、何时退役，由 D Task 8 产出就绪清单与弃用公告草稿后交用户决定。

---

## 七、状态快照与维护规则

- 截至 **2026-09-28**：N5 未开工，三份计划 0 / 68。阶段 0 阻塞在 N4 完成（N4 本身阻塞在 N3 独立验收）；
  D-N5-1 至 D-N5-3 已裁定；分工见 `plans/2026-09-27-n5-assignment-and-review.md`（待用户确认）。
- 阶段完成后：先在该阶段的实施计划里勾选步骤，再更新 `docs/project-progress.md`，最后回到本文件更新 §一。
  **不要只改本文件。**
- 某阶段计划新增或删减步骤时，同步本文件 §一 的步骤数。
