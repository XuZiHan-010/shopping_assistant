# N1 模块总览：五个模块的划分、依赖、难度与出口标准

> **本文件是 N1 的总览，不是实施计划。** 它只回答四件事：N1 拆成哪几个模块、每个模块落在框架的哪一层、
> 难点在哪、怎样算完成。逐步骤的做法仍在各模块自己的实施计划里；本文件与它们冲突时，以实施计划为准，
> 并回头修正本文件。
> **进度只在 `docs/project-progress.md` 维护**；下文「状态快照」标注了日期，过期以进度快照为准。
> **本计划不含任何 Git 提交步骤**（R2），也不触发任何 LLM 调用（R3）。
> 2026-09-23 的 N1 审查整改、CI 接线及验证限制见
> [`2026-09-22-n1-review-remediation.md`](2026-09-22-n1-review-remediation.md)。

**目标：** 让 N1（PRD §15「地基：契约、身份、数据与评测基线」）的全部工作有一张可核对的地图：
按框架层次切成模块 A–E，写清依赖、难度、真实费用点与出口标准，避免执行者在模块之间凭印象排序或重复建设。

**规格来源：** `docs/PRD.md` §15 N1；`docs/backend-development-plan.md` §5.6（分层增量）、§6.9–§6.15
（七个 Deep Module）、§8.7–§8.14（v2 契约）；`AGENTS.md` R2、R3、R5、R6。

---

## 一、总览表

| 模块 | 框架层 | 实施计划 | 步骤 | 难度 | 状态（2026-09-21） | 需 R3 授权 |
| --- | --- | --- | --- | --- | --- | --- |
| **0** 规划与架构边界 | 文档 | PRD、`AGENTS.md`、后端计划 §5.6 / §6.9–§6.15 | — | — | ✅ 完成 | 否 |
| **A** v2 契约 | 契约层：`docs/backend-development-plan.md` §8 + `backend/app/schemas/v2/` | `2026-09-20-n1-v2-contract-freeze.md` | 45 | 中 | ✅ 完成（见 §三·A） | 否 |
| **B** LLM 客户端与双协议适配 | 模型接入层：`backend/app/llm/` | `2026-09-21-n1-llm-client-and-adapters.md` | 25 | 中高 | ✅ 完成（2026-09-22，Task 6 真实冒烟共 42 次已执行） | **Task 6：已执行** |
| **C** 数据迁移与确定性种子 | 数据层：`backend/app/models/` + `backend/migrations/` + 种子脚本 | `2026-09-21-n1-data-migration-and-seeds.md` | 29 | 高 | ⬜ 计划复选框 0 / 29，代码已大量写入工作树但未完成验收（见 `docs/project-progress.md` §一） | 否 |
| **D** 会话身份与租户隔离 | 身份层：`backend/app/core/session.py` + 仓储 + API 依赖 + 服务 | `2026-09-21-n1-session-identity.md` | 27 | 高（安全核心） | 🟡 实现完成，待 Astra 审查（2026-09-22；勾选 12 / 27，Task 1–5 等必审 D1–D5） | 否 |
| **E** 评测骨架与安全硬门禁 | 评测层：`backend/app/eval/` + `backend/tests/eval/` | `2026-09-21-n1-eval-harness.md` | 20 | 中 | ⬜ 未开始 | **Task 7：真实模型评测** |
| | | | **146** | | 已勾选 **82 / 146**（A 45 + B 25 + D 12；D 另有 15 步代码已完成、待 Astra 必审后勾选；C 代码已写但未计入勾选，E 未开始） | 两处，互不覆盖 |

难度不是工作量：A 的工作量最大（47 条路径、七组契约），但每一步都是「写契约 → 写反例测试 → 写 Schema」的固定套路，
所以定为「中」。C、D 的难点是**错了会静默地错**（回填漏行、越权不报错），所以定为「高」。

### 与 PRD §15 N1 各条的对应

| PRD N1 条目 | 模块 |
| --- | --- |
| 全部 v2 路径的字段契约，再生成 OpenAPI；字段未定前不写路由 | A（字段契约与 Schema）；OpenAPI 导出随各组路由实现（§8.0.1）——N1 内只有 D Task 7 的 5 条会话路由触发首次 v2 导出 |
| `LlmClient` 协议骨架，自动化验证只用 Fake LLM | B Task 1–5、7 |
| 两种 DeepSeek 接口的冒烟测试（R3，未授权则「待人工验收」） | B Task 6 |
| 会话模式身份（D7、D8）、双重过滤、统一 403、审计 | D（含 5 条会话签发路由，Task 7） |
| 数据迁移（§8.1）与确定性演示种子 | C |
| 评测骨架与关键安全集硬门禁（真实 PostgreSQL、零 skip） | E |
| LangGraph 基线冻结 | E Task 5 |
| 回滚点：旧端点与旧前端仍可用 | 全部模块的共同约束：`complete()`、`MerchantContext`、v1 路由与 `graph.py` 不动 |

---

## 二、依赖与执行顺序

### 模块级依赖

```text
0 规划 ──→ A 契约 ──┬──→ D 会话身份 ──┐
                    │                 ├──→ E 评测骨架
                    ├──→ C 数据迁移 ──┘
                    │
                    └── B LLM 客户端（不依赖 A 之外的任何模块，可与 C、D 并行）
```

### 任务级依赖（比模块级更精确，以此为准）

| 下游任务 | 上游 | 说明 |
| --- | --- | --- |
| D Task 1（会话凭证原语） | A Task 1 ✅ | 需要 `SessionRole` 与 14 个新增 `ErrorCode`，已满足 |
| D 其余任务 | 无 | 会话计划明确「其余任务不依赖契约计划」 |
| C Task 7（售后主记录）的枚举一致性测试 | A Task 5 ✅ | `AfterSaleState` / `AfterSaleType` 已落地，测试可直接对照 |
| C Task 8（幂等记录表） | A §8.7.3 ✅ | 五元组唯一域已冻结 |
| E Task 1、3、4、5、6 | 无 | 用例模型、执行器、报告、基线冻结、CI 接线不依赖身份与数据 |
| **E Task 2（关键安全集）** | **D Task 1–5、D Task 7、C 种子** | 越权用例要真实会话、`require_owned()`、统一 403，且依赖三家固定演示商家；`SEC-CROSS-001` 等用例直接 HTTP 调用会话签发路由 |
| E Task 3 的 LLM 裁判 | 无 | 用既有 `LlmClient` 接口 + `FakeLlmClient`，**不需要 B** |
| **E Task 7（真实模型质量评测）** | **B + R3 授权**；「与新循环对照」还需 N2 工具循环 | N1 内最多完成基线侧 |
| B 全部 | 无 | 只增不改 `complete()`，与其他模块零耦合 |

> 纠正一个早先的说法：「E 依赖 B、C、D」过粗。E 的**默认路径**（零费用、Fake LLM）只依赖 C、D；
> 只有 Task 7 的真实模型评测才需要 B。

### 并行与冲突规则

1. **B 与 C、D 可并行**，它们不共享代码。唯一的撞点是 `backend/app/core/config.py`：
   B Task 4–5（`LLM_PROTOCOL`、默认模型名迁移）与 D（`SESSION_TTL_SECONDS`、`BUYER_ALIAS_SECRET`）都会改它，
   并行时各自小步提交（R2 授权后）并先拉最新版本再改，不要各自持有一份过期副本。
2. **C 与 D 共用一条线性 Alembic 链**（修订号 `0017`–`0026`，规则见数据迁移计划「迁移链与测试库规则」）：
   创建迁移前后都确认 `uv run alembic heads` 恰好一个 head；已升级的迁移不再修改；
   **同一个测试库上不得有两个执行者同时升降级**，并行时各用各的库。
3. **E Task 2 必须等 D Task 1–5、Task 7 与 C 的种子就位**；在此之前可以先做 E 的其余任务。
4. 推荐顺序：先 **D 与 C 并行**（B 视人手穿插），最后 E。B 的 Task 6 与 E 的 Task 7 是费用点，
   **未取得 R3 授权时标记「待人工验收」，不阻塞其余工作，也不得宣称适配器已验证或质量评测已通过**。

---

## 三、模块详情

### 模块 0 · 规划与架构边界 ✅

- **内容：** PRD 接管产品范围；`AGENTS.md`、前后端计划与索引同步；后端计划 §5.6（分层增量、与冻结 LangGraph 并存）
  与 §6.9–§6.15（工具注册表、工具循环、Skill 加载器、上下文压缩、记忆管线、混合召回、评测运行器）。
- **性质：** 纯文档，无代码。它管 N2–N5 全程，不是 N1 独有。

### 模块 A · v2 契约层 ✅

- **框架层与落点：** 文档 `docs/backend-development-plan.md` §8.7–§8.14；代码 `backend/app/schemas/v2/`
  （`common.py` + `shop_session` / `merchant_session` / `trade` / `after_sales` / `merchant_ops` / `drafts` / `memory` 七个业务模块）；
  测试 `backend/tests/unit/schemas/v2/`。
- **交付物边界：** 字段契约 + 纯 Pydantic 模型 + Schema 单测。**不含**路由、OpenAPI 导出、生成类型与 Adapter——
  它们按 §8.0.1 随各组路由实现的同一次变更完成。
- **难度「中」的依据：** 量大但套路固定。真正的难点是把 PRD 的状态机不变量落成字段与校验：
  订单支付/履约分维、售后迁移表（按类型限定）、草稿「不存在已批准状态」、审批证据两阶段提交、金额整数分与舍入顺序。
- **出口标准（均已满足）：**
  1. PRD §11.2 的 47 条路径在 §8.8–§8.14 逐条出现，脚本核对 47/47、无多余路径；
  2. `backend/app/schemas/v2/` 无 `merchant_id` / `buyer_key` / `attachment_ids` / `float`、无自建错误码枚举、
     `session_id` 只在两个会话模块；
  3. 带 `client_request_id` 的请求模型与 §8.7.3 白名单逐一对应，全部模型 `extra="forbid"`；
  4. v2 Schema 单测 **285 passed**（2026-09-22 修复复测）；此前变异检验删除 93 处校验拒绝语句，**93/93 被杀死**（首轮 77/93，补 27 项用例后清零）；
  5. 后端全量 **1687 passed / 0 skipped**（2026-09-21，真实 PostgreSQL，`REQUIRE_INTEGRATION_DB=1`）。2026-09-22 的 A 修复尚未取得稳定的后端全量复测结果，见 `docs/project-progress.md`。
- **执行期裁定：** 契约计划「执行期裁定」E1–E14 记录了计划文字没覆盖、由执行者在用户授权下裁定的事项
  （客服工单结案路径、「已关闭」履约事件、反馈 `kind` / `reaction`、库存告警去掉 `days_of_supply_note` 等），
  已按 PRD → 契约 → 计划 → 索引同步，可被用户推翻。
- **遗留一项，不属于 A，留给 N3 入口条件：** 「已退款 → 关闭」「已拒绝 → 关闭」由谁触发。PRD 没写触发方，不替 N3 决定。
- **同期发现的计划缺口（不属于 A，2026-09-21 用户已裁定并补入计划）：** 47 条路径里曾有 **8 条没有任何计划负责实现后端路由**。
  现归属：5 条会话签发路由 → 会话计划 **Task 7**（模块 D）；顾客端 `GET /shop/after-sales` 列表与详情 →
  `n3-customer-skills-and-after-sales` Task 7；商家端 `GET /merchant/customer-signals` 列表 → `n3-merchant-skills` Task 7。
  47 条路径现全部有实现方。
- **A 完成不等于 v2 功能存在。** 现在没有任何 v2 路由。

### 模块 B · LLM 客户端与双协议适配

- **框架层与落点：** 模型接入层 `backend/app/llm/`：扩展 `client.py`（`LlmMessage` / `ToolSchema` / `LlmToolCall` / `LlmTurn` / `converse()`，
  **只增不改**）；新建 `openai_adapter.py`、`anthropic_adapter.py`；`fake.py` 补脚本化 `converse()`；`config.py` 加 `LLM_PROTOCOL`。
- **任务：** 1 协议扩展 → 2 OpenAI 适配器 → 3 Anthropic 适配器 → 4 协议选择开关 → 5 默认模型名迁移
  （`deepseek-chat` / `deepseek-v4-flash` → `deepseek-flash`）→ **6 真实冒烟（R3）** → 7 契约补写与自检。
- **难度「中高」的依据：**
  - 流式 `converse_stream()` 的增量解析（两种协议的事件形状不同）；
  - 多轮工具调用历史的请求体序列化，以及 `reasoning_content` 的回放与协议绑定；
  - 缓存计量字段：提供方未上报时必须是 `None`，不得当 0；
  - `LLM_THINKING` 必须显式配置，不依赖提供方默认值。
- **出口标准：** Task 1–5、7 全绿且**零费用**（`httpx.MockTransport`，不新增 `respx`）；`complete()` 签名与行为不变，
  v1 全部测试仍绿；`.env.example`、`config.py`、README 与相关测试的默认模型名一致迁移。
  **Task 6 不在出口内**：未授权时标「待人工验收」。
- **R3：** Task 6 = 两种协议各 12 次、合计 **24 次**真实调用（流式、多轮工具历史、缓存计量），模型 `deepseek-flash`，会产生费用。
  执行前必须先向用户说明接口、次数、模型、费用并取得明确同意；授权范围之外（换模型、加次数）须重新取得同意。

### 模块 C · 数据迁移与确定性种子

- **框架层与落点：** 数据层。ORM 在 `backend/app/models/`（`analytics.py` 扩列；新建 `events.py`、`after_sales.py`、`drafts.py`、
  `promotion.py`、`memory_v2.py`、`idempotency.py`）；迁移在 `backend/migrations/versions/`；`app/domain/order_status_mapping.py`
  与 `app/jobs/rebuild_projections.py`；种子 `app/analytics/demo_data.py` 与 `scripts/seed_demo_scenarios.py`；`docs/database.md` 同步。
- **任务：** M1 商品扩列 → M2 订单三维投影与价格快照 → M3 事件账本三表 → M4 草稿与变更账本 → M5 优惠券与护栏 →
  M6 记忆两层 / 顾客信号 / 当日简报 → M7 售后主记录 → M8 幂等记录表 → 9 确定性种子 → 10 自检与文档同步。
- **难度「高」的依据：**
  - **既有行回填**：线上演示库已有 v1 订单，只在空库上跑通的迁移不算完成；映射无法唯一确定的行必须让迁移中止，而不是猜；
  - **追加写由数据库保证**（不可变触发器），不是靠应用层自觉；
  - **可售量不建列**，由「在库 − 占用」派生，避免第二事实源；
  - 约束测试必须断言具体的 SQLSTATE 与约束名（`DBAPIError`），禁止 `pytest.raises(Exception)` 这类恒绿写法；
  - 升级 → 降级 → 再升级的往返测试。
- **出口标准：** `alembic heads` 恰好一个；M1–M8 每批独立可升降级；既有行回填与回滚往返测试通过；
  种子确定性可复现（同一 seed 两次运行字节一致，演示商家恒为 3 家）；S1–S4 所需样本齐全；
  数据库枚举与契约枚举逐字一致（`test_db_enums_equal_contract_enums`）；`docs/database.md` 同步。
- **R3：** 无。只在可丢弃本地测试库操作，沿用 `assert_local_database_url()` 守卫。
- **本机前置：** 需要本地 PostgreSQL 测试库（`docker compose -p borough up -d postgres`，端口 55432）。

### 模块 D · 会话身份与租户隔离

- **框架层与落点：** 身份层。`backend/app/core/session.py`（在 A 已建的 `SessionRole` 之上加凭证原语、哈希、`SessionContext`、别名函数）；
  `models/session.py`、`models/provenance.py`；`repositories/session.py`、`repositories/provenance.py`；
  `services/session_service.py`、`services/resource_scope.py`；`api/session_deps.py`；审计与错误码同步；
  迁移 `agent_sessions` 与来源状态表。
- **任务：** 1 会话凭证原语 → 2 `agent_sessions` 表与迁移 → 3 签发、解析与注销 → 4 FastAPI 依赖与角色守卫 →
  5 统一 403 非枚举响应 → 6 来源状态隔离（O2）→ **7 会话签发路由与 §8.0.1 同步**（2026-09-21 并入）→ 8 契约补写与自检。
- **N1 内唯一的 v2 路由：** Task 7 落地 5 条会话签发路由（`POST/DELETE /shop/sessions*`、`POST/DELETE /merchant/sessions*`），
  同次完成 OpenAPI 导出、商家端 `generated.ts` 与 `adapters/session.ts`。购物车合并在 N1 只接端口（生产装配 `EmptyCartMerge`），
  由 `n2-trade-closed-loop` Task 2 换成真实实现；顾客端 `shop/` 的生成类型与 Adapter 由 `n2-shop-nextjs-app` 建工程时生成。
- **难度「高（安全核心）」的依据：**
  - 会话是**凭证**：高熵、哈希存储、可过期、可注销、可撤销，且不可变角色；
  - **统一 403 非枚举**：目标不存在与目标不属于当前主体必须逐字段一致，且**耗时一致**（独立时序哨兵测试，`security_timing` marker）；
  - 演示 Token 撤销级联使其换取的全部会话失效；
  - 访客绑定演示顾客：保留原凭证、事务内幂等合并购物车，试图改绑另一身份返回 `409 SESSION_ALREADY_BOUND`；
  - 来源状态按「登录主体 + 店铺 + 对话」隔离并带版本号防并发覆盖；
  - v1 的 `MerchantContext` 与 Bearer 路径**保持不变**，两套并存直到 v2 前端切换。
- **出口标准：** 会话隔离的安全硬门禁用例通过（真实 PostgreSQL、零 skip）：商家会话调顾客端点、顾客会话调商家端点、
  跨商家、跨顾客一律 403 且写审计；5 条会话签发路由满足 §8.0.1 五项完成门槛（`docs/api.json` 只新增这 5 条 v2 路径、
  `codegen:check` 通过、商家会话 Adapter 契约测试与 OpenAPI 哨兵通过），签发/绑定响应带 `Cache-Control: no-store`；`.env.example`、`docs/deployment.md`、`AGENTS.md` R6 的新 Secret 与 TTL 同步；
  生产环境缺少或使用弱 `BUYER_ALIAS_SECRET` 时启动失败。
- **R3：** 无。
- **撞点：** `config.py` 与 B 共改；迁移链与 C 共用（见 §二）。
- **状态（2026-09-22）：🟡 实现完成，待 Astra 审查。** 27 步代码与测试均已完成；Task 1–5 属于 Astra 必审项 D1–D5，
  按审查清单规则审查通过前不勾选，当前勾选 12 / 27。本轮补齐了此前遗漏的启动对账（D3）、日志 `X-Session-Id`
  脱敏、5 条 v2 路径专用 OpenAPI 哨兵，以及来源状态版本号条件更新与过期访客清理 Cron。 迁移号最终落在 `0025`/`0026`（C 已占用
  `0017`–`0024`，与计划文字写的 `0017`/`0018` 不同，以 `uv run alembic heads` 实测为准）。5 条 v2 会话路由已挂载、
  `docs/api.json` 只新增这 5 条路径、`frontend/src/api/generated.ts` 已重新生成并通过 `codegen:check`、
  商家会话 Adapter（`frontend/src/api/adapters/session.ts`）与契约测试已落地。安全硬门禁（统一 403 非枚举、
  独立 `security_timing` 时序哨兵、双重过滤、来源状态隔离）均在真实 PostgreSQL 上验证通过。
  详见 `docs/project-progress.md` §一「模块 D」与「2026-09-22 模块 D 进展」。

### 模块 E · 评测骨架与关键安全集硬门禁

- **框架层与落点：** 评测层。`backend/app/eval/`（`cases.py`、`runner.py`、`graders/assertions.py`、`graders/llm_judge.py`、
  `report.py`、`datasets/security/*.yaml`、`datasets/quality/*.yaml`、`baseline/FROZEN.md`）；`backend/tests/eval/`。
  **`app/eval/` 可以 import 生产模块，但不得被任何生产模块 import**，有一条扫描测试守这条线。
- **任务：** 1 用例模型与分层校验 → 2 关键安全集 → 3 执行器与三层评分 → 4 报告与脱敏 → 5 冻结 LangGraph 基线（O4）→
  6 CI 接线与隔离扫描 → **7 真实模型质量评测（R3）**。
- **难度「中」的依据：** 骨架本身不深，关键是**防假绿**：
  - 用例带 `introduced_in`，N1 只登记已存在的被测对象（跨租户、SQL 注入意图、身份覆盖、`buyer_key` 伪造四类，每类 ≥3 条、合计 ≥12 条）；
    越权审批、模型自批、提示词注入三类随 N2 路由交付，N2 验收前七类补齐；`CURRENT_MILESTONE` 只能由里程碑收尾任务改；
  - 门禁运行强制真实数据库，**缺库时整批 skip 也显示为绿是不允许的**——零 skip 钩子；
  - 权限、金额、状态迁移、工具参数一律由代码断言裁定，安全用例一条 LLM 裁判都不用；
  - 分层质量集按 Skill、角色、风险、语言分层，分层是可校验的约束而不是标签。
- **出口标准：** 安全集门禁在真实 PostgreSQL 上零 skip、零失败；`app/eval/` 单向依赖扫描通过；LangGraph 12 节点基线与依赖哈希已冻结；
  评测报告不含隐私与密钥。
- **R3：** Task 7 真实模型质量评测需另行授权，**不加入默认测试套件**；其中「与新循环对照」要等 N2 工具循环存在。

---

## 四、N1 整体完成定义

N1 完成当且仅当：

1. A–E 五个模块各自满足上面的出口标准；
2. 后端全量测试在真实 PostgreSQL、`REQUIRE_INTEGRATION_DB=1` 下**零失败、零 skip**，`ruff check .` 与 `mypy app` 通过；
3. 关键安全集四类（≥12 条）作为硬门禁在 CI 可跑；
4. v1 回滚点完好：v1 路由、`complete()`、`MerchantContext`、`graph.py` 未被改动语义；
5. 两个 R3 项要么已按授权范围执行并记录结果，要么明确标记「待人工验收」——**不得把待人工验收说成已验证**；
6. `docs/project-progress.md` 已记录当前阶段、验证结果、下一步与风险，`docs/project-navigation.md` 已登记新增文件。

**N1 不包含：** 除 5 条会话签发路由（模块 D Task 7，连同其 OpenAPI 导出、商家端生成类型与会话 Adapter）以外的任何
v2 路由、OpenAPI 导出、生成类型、前端 Adapter，以及 Next.js 顾客端——它们属于 N2 及之后。

---

## 五、状态快照与维护规则

- 本节状态截至 **2026-09-22**：模块 0、A、B 完成；D 实现完成、待 Astra 审查（勾选 12 / 27）；C 代码已写入工作树但未完成验收（计划复选框仍 0 / 29）；
  E 未开始；总勾选 82 / 146（D 并入会话签发路由后总步骤数由 141 调整为 146）。
- 模块完成后：先在该模块的实施计划里勾选步骤，再更新 `docs/project-progress.md` 的日期、验证结果、下一步与风险，
  最后回到本文件更新 §一 的状态列与出口标准的达成情况。**不要只改本文件。**
- 某模块的实施计划新增或删减步骤时，同步本文件 §一 的步骤数；步骤数以各实施计划的复选框计数为准
  （统计时排除计划页眉里说明用的 `` `- [ ]` ``，此前误算过一次）。
- 计划范围发生变化时，仍按 PRD → 契约 → 前后端计划 → 索引的顺序同步，本文件属于最后一层。
