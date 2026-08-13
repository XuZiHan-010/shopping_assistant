# F6 之后的执行路线计划

> **For agentic workers:** REQUIRED SUB-SKILL: 用 `superpowers:executing-plans` 按阶段推进本计划。
> 每个阶段末尾都有出口判据与用户检查点，**未获用户裁定不得跨阶段**。步骤使用 `- [ ]` 复选框跟踪。

**日期：** 2026-08-12
**状态：** 第 2 稿——已完成一轮独立评审并逐条整改，待用户批准后执行。

> **第 1 稿的评审结论与处置（7 项，全部经核实后整改）**
>
> | # | 问题 | 核实结论 | 处置 |
> | --- | --- | --- | --- |
> | 1 | Railway 客户端 IP 契约与实现不符 | **属实。** Railway 文档注入 `X-Real-IP`，未承诺 `X-Forwarded-For`；`client_ip.py:12` 只读后者 | 新增**阶段 2.5**，部署前整改 |
> | 2 | 阶段 4 超出已申报费用授权 | **属实。** 初稿在 2 次聊天授权下追加预算/限流验证 | 限流移至阶段 3（零成本，路由依赖先于 LLM 求值）；预算熔断拆为独立授权任务；Global Constraints 的 R3 补全为完整口径 |
> | 3 | 跨业务查询失败语义写反 | **属实。** 权威定义是「降级回退，`intent_type` 保持 VALID」，非 INVALID | 阶段 2 增加专门说明，并注明不要照审计 §3.3 的措辞实现 |
> | 4 | 演示部署模式验收自相矛盾 | **属实。** 部署要求 `true`，验收却要求验证 `false` | 部署明确为 `true`；关闭态改由既有自动化断言覆盖，不在线上切换；并要求修订后端验收条款过时表述 |
> | 5 | 分支去向描述错误 | **属实。** `main` 停在 `003cbc7`，`feature/f2-mock-conversation` 是事实默认分支但不是 `main` | 重写为「先裁定唯一主线」两步决策，PR 选项补 base/head |
> | 6 | 与进度快照的下一步顺序冲突 | **属实。** | 总览新增取代声明；阶段 0 出口新增三处进度快照修正 |
> | 7 | 阶段 5 缺检查点 | **属实。** 开头承诺每阶段有检查点，汇总表只到阶段 4 | 新增用户检查点 6，汇总表补 3.5 与 6 |
>
> **一处未按评审建议采纳：** 评审对第 2 项给出「删除该 Step」或「拆成独立任务」二选一。经核实 `enforce_rate_limit` 是 `POST /api/chat` 的路由依赖（`backend/app/api/routes/chat.py:171`），触发限流返回 429 时**不进入任何 LLM 调用路径**，故限流验证零成本、本就属于阶段 3 的无 Key 轮次；只有预算熔断需要真实消耗。因此按**成本边界拆分**，而非整体删除或整体独立授权。
>
> **一处评审判断被采纳并进一步收窄：** 评审指出 SSE 不必描述为未知平台风险。核实后确认 Railway 文档称 SSE 无需特殊配置即可工作，且其建议的 `X-Accel-Buffering: no` 已在 `backend/app/api/routes/chat.py:186` 设置，故阶段 3 该步骤改为核实**本应用的 1 秒首字 SLO 与中间件配置**。

**Goal:** 把「F6 本地部分已完成、Railway 未部署」这个当前状态，按一条已经论证过的顺序推到「MVP 可裁定完成 + 1:1 还原缺口清零 + P1 交付」，并明确每一步由谁执行、跑什么门禁、出口判据是什么。

**Architecture:** 本计划是**路线计划（roadmap），不是实施计划**。它只负责排序、定义出口判据和登记用户决策点；每个阶段的逐步骤实施细节由各自的子计划负责——已存在的直接引用，不存在的在进入该阶段时先产出。唯一在本计划内写全步骤的是阶段 0（提交与分支收口），因为它不属于任何既有计划。

**Tech Stack:** Python 3.12、FastAPI、SQLAlchemy 2、Alembic、Vue 3、TypeScript、Vite、Vitest、Playwright、ECharts、Caddy、Docker、Railway、DeepSeek。

---

## Global Constraints

以下约束适用于本计划的**每一个阶段**，不在各阶段重复：

- 面向用户的文案、错误提示、日志说明与项目文档使用中文；代码标识符使用英文（R1）。
- **未经用户明确许可，不执行 `git commit` / `git push` / `git tag` / `gh pr create` / `gh pr merge`**，也不使用 `git reset --hard`、`git clean`（R2）。本计划中所有 Git 步骤都必须先取得授权。
- **R3 完整口径**：单元测试必须 mock LLM；**启动后端、调用聊天接口、执行 OCR、生成日报，或运行任何会产生 token 费用的测试之前**，都必须先说明「将调用什么接口 / 预计调用多少次模型 / 使用什么模型 / 是否产生费用」四项，**获得用户明确同意后才能执行**。这条不只约束"真实模型验收"这一个阶段——阶段 5 的 B8 日报与附件 OCR 同样受它约束。
- LLM 不得生成或执行任意 SQL；结构化意图 → 后端模板 SQL → 白名单校验的链路不可绕过（R4）。
- 商家隔离不可削弱：`merchant_id` 由可信身份注入，不信任前端传值（R5）。
- 密钥只来自环境变量或 Railway Variables，`.env.example` 只放占位符（R6）。
- 降级必须在 API 字段与页面中对用户可见，不得把兜底伪装成真实分析（R7）。
- `yshopping-merchant-ai 4/` 与 `yshopping-prototype/` **整体只读**，只作行为对照（R8）。
- 与参考项目冲突时改我们的文档，不得用「PRD 没写」论证参考项目里的行为可以不做（R9）。
- 技能产出的计划写入 `plans/`，设计说明写入 `docs/specs/`，**不得新建 `superpowers/` 或任何以技能名命名的目录**（R10）。
- 不手改 `frontend/src/api/generated.ts`、`docs/api.json`、`docs/api.md` 与生成 fixture；契约变化后一律用脚本重新生成。
- 每完成一段可验证工作，更新 `docs/project-progress.md` 的日期、阶段、验证结果、下一步与风险。

---

## 本计划的定位与边界

**本计划不替代任何既有计划。** 它引用它们：

| 阶段 | 权威子计划 | 状态 |
| --- | --- | --- |
| 阶段 1–2（R9 还原度整改） | `plans/2026-08-09-b7-f4-integration-and-r9-remediation.md` 的 Task 5–15 | 已存在，未开工 |
| 阶段 3–4（Railway 部署与线上验收） | `plans/2026-08-11-frontend-f6-railway-mvp-closeout.md` 的 Task 9–11 | 已存在，未开工 |
| 阶段 2 内的四个能力切片 | 指标口径 / 纯明细 / 跨业务查询 / 受控临时分组指标 四份子计划 | **都不存在，进入阶段 2 时先写** |
| **阶段 2.5（可信客户端 IP 契约）** | 无 | **本计划内已定义完整范围与 TDD 步骤，不需要另写子计划** |
| 阶段 5–6（B8/F7、B9/F8、F9） | 无 | **都不存在，进入各阶段时先写** |

出现冲突时，**以被引用的子计划为准**，本计划只负责顺序与出口判据。

---

## 执行顺序总览

| 阶段 | 内容 | 执行者 | 阻塞下一阶段？ |
| --- | --- | --- | --- |
| **0** | 提交 F5/F6 工作树成果，裁定分支去向 | Agent（需授权） | 是 |
| **1** | R9 阶段 B Task 5–8：基线校正、契约统一、§3.6 思考步骤 | Agent | 是 |
| **2** | R9 阶段 B Task 9–15：四个能力切片 + E2E + 验收 + 交付 | Agent | 是 |
| **2.5** | 可信客户端 IP 契约整改（`X-Real-IP`） | Agent | **是**——不修则线上限流退化为全局 |
| **3** | Railway 部署 + 零成本线上验收（F6 Task 9–10） | **用户在控制台** | 是 |
| **4** | 真实模型验收 + MVP 完成裁定（F6 Task 11） | Agent（需 R3 授权） | 否 |
| **5** | B8 → F7，B9 → F8 成对推进 | Agent | 否 |
| **6** | F9 内部可用版收尾 | Agent | — |

**本路线图取代此前的下一步顺序。** `docs/project-progress.md` 在 2026-08-12 之前记录的下一步是「先执行 Railway 部署（F6 Task 9–11），阶段 B 恢复时点待定」。用户批准本路线图后，该顺序作废，改为「R9 阶段 B 与 IP 契约整改先行，部署排在其后」。阶段 0 必须同步改掉进度快照里的旧顺序，否则下一位 coding agent 会读到互相矛盾的两个下一步。

## 为什么是这个顺序（已论证，不要在执行期推翻）

三条判断，每条都有依据：

1. **R9 阶段 B 排在部署之前。** 它会改后端契约（指标口径加 6 个字段、`DETAIL` 语义分叉、`QueryIntent` 加跨业务字段），一改就要重新生成 OpenAPI → `generated.ts` → fixture → 前端 Adapter。让契约先定型，部署与真实模型验收各做一次即可，避免「部署→改契约→重新部署→重新评估准确率」。

2. **B8/B9 与 F7–F9 排在部署之后。** 这不是偏好，是项目自己写死的：`docs/backend-development-plan.md:941`「MVP 在 B7 收口，不要为了做 P1 功能而推迟部署」、同文件 `:1419`「不要先做 B8/B9 的 P1 功能再部署」、`docs/frontend-development-plan.md:839`「不要为了做 P1 功能推迟部署」。理由见 `:1421`：把 Railway 排在附件和知识库之后，会让部署、迁移和费用风险暴露得过晚。

   具体风险有两条，**2026-08-12 已按 Railway 官方文档逐条核实，结论与初稿不同，以下为核实后的版本**：

   - **限流会退化为按 Token 收敛（已确认成立，故新增阶段 2.5）。** Railway 的 [Public Networking specs](https://docs.railway.com/networking/public-networking/specs-and-limits) 列出的注入头是 `X-Real-IP`（另有 `X-Forwarded-Proto`、`X-Forwarded-Host`），**未承诺注入 `X-Forwarded-For`**。而 `backend/app/core/client_ip.py:12` 只读 `x-forwarded-for`：取不到链时 `len(chain) < trusted_proxy_hops` 成立，直接 `return peer`——而 `peer` 是 Railway 代理的地址。限流键为 `token|client_ip`，故结果不是“限流被绕过”，而是每个 Token 的客户端 IP 维度失效；本次对外演示公开下发 Token，访客会近似共用一个桶，单个访客可耗尽该演示 Token 的配额。这必须在部署前修，见阶段 2.5。

   - **SSE 缓冲风险低于初稿判断（已下调）。** Railway 的 [SSE 指南](https://docs.railway.com/guides/streaming-ai-responses) 明确「SSE streaming works on Railway without special configuration」，同时说明缺少 `X-Accel-Buffering: no` 时客户端可能一次性收到全部内容。**我们已经在 `backend/app/api/routes/chat.py:186` 设置了该响应头。** 因此这不是"平台架构未知风险"，阶段 3 的验证目标应表述为**核实本应用的 1 秒首字 SLO 与中间件配置是否达标**（PRD §16 第 17 条），而不是验证平台是否支持 SSE。

3. **真实模型验收（阶段 4）必须排在 R9 Task 11 之后。** 那个 Task 会往 `QueryIntent` 加跨业务字段，意图 schema 一变，先前测得的准确率作废。真实 DeepSeek 的钱只花一次，花在最终契约上。

---

# 阶段 0：提交工作树成果并裁定分支去向

**为什么排第一：** F5 全部代码 + F6 Task 1–8/12 的全部产出（含三个新门禁脚本、部署手册、出口证据矩阵）**都还堆在工作树里未提交**。这是一大批已通过验证的工作处于无版本保护状态，是当前最高的单点风险。

**执行者：** Agent 执行命令，但**每一次 `git commit` / `git push` 都必须先获得用户明确授权**（R2）。

### Task 0.1: 提交前核对

- [ ] **Step 1: 确认当前分支与工作树范围**

```powershell
git status --short --untracked-files=all
git branch -vv
git log --oneline -5
```

预期：分支为 `feature/integrate-b7-f4`，HEAD 为 `caca1e9`，工作树含 **40 个已修改文件与 12 个未跟踪文件**（含本计划），合计 52 个，与 Task 0.2 四组提交的文件数（15 + 9 + 17 + 11）相等。

**若实际数量不符，先查清多出/缺少哪些文件再提交**——本计划成文时 Codex 的 F6 子代理仍在运行，可能追加过文件。

- [ ] **Step 2: 逐一检查将要提交的内容是否含密钥**

```powershell
git diff -- .env.example
git diff -- .gitignore frontend/.gitignore
```

预期：`.env.example` 只新增 `DEMO_DEPLOYMENT_MODE=false` 占位符；`.gitignore` 只新增 `!frontend/src/build/` 反忽略；`frontend/.gitignore` 只新增 `dist-first-paint/`。**若出现任何真实 Key、连接串或 Token，立即停止并报告用户**（R6）。

- [ ] **Step 3: 确认 `backend/.env` 与构建产物不在待提交集合中**

```powershell
git status --short --untracked-files=all | Select-String -Pattern "\.env$|dist/|dist-first-paint/"
```

预期：无输出。若有输出，说明忽略规则失效，先修忽略规则再提交。

### Task 0.2: 分组提交（需用户逐组授权）

按下面四组提交。**同一文件同时含 F5 与 F6 改动时不要拆 hunk**——`frontend/src/views/AssistantView.vue` 与 `AssistantView.spec.ts` 确定如此（F5 的反馈接线 + F6 的 `chartMountable`），`backend/tests/unit/core/test_config.py` 也是（测试隔离修复 + F6 演示部署模式）。这类文件整体放进**较晚**的那一组，并在提交消息里说明它同时含前一阶段的改动。拆 hunk 会让两个提交都无法独立通过测试，得不偿失。

- [ ] **Step 1: 第 1 组 — F5 前端质量轨迹与反馈**

```powershell
git add frontend/src/components/chat/ChatMessage.vue frontend/src/components/chat/ChatMessage.spec.ts `
        frontend/src/components/chat/ConversationColumn.vue frontend/src/components/chat/ConversationColumn.spec.ts `
        frontend/src/stores/chat.ts frontend/src/stores/chat.spec.ts `
        frontend/src/api/chat.ts frontend/src/api/chat.spec.ts `
        frontend/src/api/adapters/chat.ts frontend/src/api/adapters/chat.spec.ts `
        frontend/src/types/chat.ts frontend/src/api/mock/transport.ts `
        frontend/e2e/conversation.spec.ts `
        docs/specs/2026-08-10-frontend-f5-design.md plans/2026-08-11-frontend-f5-implementation.md
git status --short
```

确认暂存内容后提交（消息见下），**先向用户展示 `git status` 输出并取得授权**：

```text
feat(frontend): F5 质量轨迹、回答反馈与无障碍收口

ChatMessage 展示四种质量状态、校验次数、备注与中文来源；反馈经
Adapter/API/Store 分层接入 B6，覆盖失败保留、同值重试、持久化粘性
与 reset 中止。历史消息因会话详情缺 answer_id 与反馈状态暂不开放
反馈，边界登记至 R9 阶段 B Task 8。
```

- [ ] **Step 2: 第 2 组 — F6-0 后端（含测试隔离修复）**

```powershell
git add backend/app/core/config.py backend/app/api/routes/admin.py backend/app/llm/guard.py `
        backend/tests/conftest.py backend/tests/unit/core/test_config.py `
        backend/tests/api/test_admin_ops.py backend/tests/api/test_demo_merchants.py `
        backend/tests/unit/llm/test_guard.py `
        .env.example
git status --short
```

```text
feat(backend): 显式演示部署模式与未配置客户端的预算守卫（F6-0）

新增 Settings.demo_deployment_mode：生产环境默认关闭演示商家端点，
仅在显式开启时放行，/api/admin/ops/status 同步返回该布尔字段。
LlmCostGuard.complete() 在底层客户端未配置时直接抛 LlmUnavailableError，
不再先预扣预算与用量计数。

同时含 2026-08-11 集成复核发现的测试隔离修复：Settings 的来源链在测试
期裁到只剩 init_settings，测试不再被开发者 .env 与进程环境变量污染。
```

- [ ] **Step 3: 第 3 组 — F6-A 前端构建门禁与 Railway 配置**

```powershell
git add frontend/vite.config.ts frontend/tsconfig.node.json frontend/Dockerfile `
        frontend/package.json frontend/eslint.config.js frontend/.gitignore .gitignore `
        frontend/railway.json `
        frontend/src/build/mock-flag.ts frontend/src/build/mock-flag.spec.ts `
        frontend/scripts/check-first-paint.mjs frontend/scripts/check-no-secrets.mjs `
        frontend/e2e/first-paint.spec.ts frontend/playwright.first-paint.config.ts `
        frontend/e2e/responsive.spec.ts `
        frontend/src/views/AssistantView.vue frontend/src/views/AssistantView.spec.ts
git status --short
```

```text
build(frontend): 首屏图表延迟挂载、生产 Mock 与密钥门禁、Railway 配置（F6-A）

AssistantView 改用 defineAsyncComponent 加显式 chartMountable 开关，
ECharts 退出首屏网络路径；check-first-paint.mjs 以预加载检测、入口静态
import 链遍历与 v-if 存在性三层拦截回归。新增 assertMockDisabledInProduction
使 VITE_USE_MOCK=true 的生产构建直接失败，Dockerfile 同步透传该参数。
新增 frontend/railway.json 与 check-no-secrets.mjs 构建产物密钥扫描。

AssistantView 两个文件同时含 F5 的反馈接线改动，未拆 hunk。
```

- [ ] **Step 4: 第 4 组 — 文档与计划同步**

```powershell
git add AGENTS.md docs/deployment.md docs/project-progress.md `
        docs/backend-development-plan.md docs/frontend-development-plan.md `
        docs/yshopping-parity-audit.md `
        docs/specs/2026-08-11-frontend-f6-design.md `
        docs/specs/2026-08-11-mvp-exit-evidence-matrix.md `
        plans/2026-08-09-b7-f4-integration-and-r9-remediation.md `
        plans/2026-08-11-frontend-f6-railway-mvp-closeout.md `
        plans/2026-08-12-post-f6-execution-roadmap.md
git status --short
```

```text
docs: F6 设计、部署手册、MVP 出口证据矩阵与后续执行路线

新增 MVP 出口证据矩阵，逐条核对 PRD §16 的 26 条、后端 B7 的 12 条与
前端 F6 的 5 条出口，结论为「F0–F6 代码与文档已完成，Railway 部署就绪，
MVP 尚未宣告完成」。AGENTS.md 登记 DEMO_DEPLOYMENT_MODE 与
frontend/railway.json。新增本轮之后的执行路线计划。
```

- [ ] **Step 5: 确认工作树已清空**

```powershell
git status --short --untracked-files=all
```

预期：无输出（`.superpowers/` 被忽略，不计入）。

### Task 0.3: 裁定分支去向（用户决策）

- [ ] **Step 1: 向用户呈现三个选项并取得裁定**

这件事从 2026-08-10 挂到现在，必须在进入阶段 1 前定掉。

**先厘清一个此前被文档写错的事实。** `docs/project-progress.md` 与本计划初稿都把 `feature/f2-mock-conversation` 称作「当前 `main` 分支」，**这是错的**。2026-08-12 实测：

| 分支 | HEAD | 说明 |
| --- | --- | --- |
| `main` | `003cbc7` | 只有一条「初始化仓库，纳入 F0-F1 基线」，此后再未前进 |
| `feature/f2-mock-conversation` | `ee74893` | `origin/HEAD` 指向它，是**事实上的默认分支**，但不是名为 `main` 的分支 |
| `feature/integrate-b7-f4` | `caca1e9` | 当前工作分支，无 upstream |

也就是说：**真正的 `main` 停在仓库初始化状态，整个项目的成果都不在它上面。** 快进 `feature/f2-mock-conversation` 只是推进另一个 feature 分支，`main` 依然是空的。

- [ ] **Step 1: 由用户裁定唯一主线是哪个分支**

必须先答这一题，否则下面的选项无意义：

- **若主线是 `main`**：需要补一条把成果最终并入 `main` 的路径，并考虑是否把 `origin/HEAD` 改指回 `main`；
- **若主线就是 `feature/f2-mock-conversation`**：则应停止在文档里称它为「main」，并明确 `main` 分支的处置（保留为初始快照 / 删除 / 改名）。

- [ ] **Step 2: 在已定主线的前提下选择本轮动作**

| 选项 | 含义 | 备注 |
| --- | --- | --- |
| A. 推送 `feature/integrate-b7-f4` 到 `origin`，暂不合并 | 取得远端备份，主线不变 | 最小动作，不解决主线归属问题 |
| B. 推送并开 PR | 有备份且有评审记录 | **必须写明 base 与 head**：head 为 `feature/integrate-b7-f4`，base 取决于 Step 1 的裁定 |
| C. 快进主线分支 | 主线前进到集成结果 | `plans/2026-08-09-...md` 约束此项需集成分支全部门禁通过且用户明确授权；**授权目前未取得** |

无论选哪项，**推送前必须先跑通阶段 0 出口判据的全量门禁**。

- [ ] **Step 2: 按裁定执行推送（需授权）**

- [ ] **Step 3: 清理已并入的历史 worktree（可选，需用户确认）**

`.worktrees/feature-b5-b6-answer-feedback-export/` 与 `.worktrees/feature-f3-real-api-integration/` 的内容都已并入集成分支，只作对照保留。用户确认不再需要后再移除，**移除前先 `git status` 确认两个 worktree 内没有未提交改动**。

### 阶段 0 出口判据

推送前必须实测通过，**不得引用历史数字**：

- [ ] 后端静态门禁全绿：

```powershell
cd backend
uv run ruff check .
uv run ruff format --check .
uv run mypy app
```

- [ ] 后端真实数据库全量回归通过：

```powershell
docker-compose -p borough up -d postgres
cd backend
$env:REQUIRE_INTEGRATION_DB=1; uv run pytest
```

预期 ≥ 709 passed / 0 skipped / 0 failed。**Docker 引擎不可用时不得跳过此项**——它是唯一能发现测试隔离与预算累积类缺陷的门禁（见「环境已知摩擦」）。

- [ ] 前端全部门禁通过（`secrets:check` 与 `firstpaint:check` 必须在 `build` 之后跑）：

```powershell
cd frontend
npm.cmd run lint
npm.cmd run format:check
npm.cmd run codegen:check
npm.cmd run fixtures:check
npm.cmd run typecheck
npm.cmd run test
npm.cmd run build
npm.cmd run mock:check
npm.cmd run secrets:check
npm.cmd run firstpaint:check
```

预期 Vitest ≥ 26 文件 / 245 passed，其余全部 exit 0。

- [ ] 工作树干净，四组提交已落地，分支去向已裁定并执行。
- [ ] **`docs/project-progress.md` 已完成三处修正**（缺一不可，否则下一位 coding agent 会读到互相矛盾的下一步）：
  1. 「下一步」一节的旧顺序（第 1 项「继续 F6 Task 7–12」、第 5 项「实际执行 Railway 部署」）改为本路线图的顺序：**R9 阶段 B 与 IP 契约整改先行，Railway 部署排在阶段 3**；并注明「本顺序取代 2026-08-12 之前记录的先部署方案」；
  2. 删除或改正把 `feature/f2-mock-conversation` 称作「当前 `main` 分支」的表述——实测 `main` 停在 `003cbc7`，两者不是同一分支；
  3. 补记 F5/F6 已提交、分支去向裁定结果，以及 F6 Task 9–11 未执行的事实。

> **用户检查点 1：** 阶段 0 完成后停下来汇报，取得用户对进入阶段 1 的确认后再继续。

---

# 阶段 1：R9 阶段 B Task 5–8（基线校正、契约统一、§3.6）

**权威计划：** `plans/2026-08-09-b7-f4-integration-and-r9-remediation.md` 的 Task 5–8。本阶段**不复制该计划的步骤**，只登记进入条件、偏离与出口。

**为什么先做这四个：** Task 8「修复思考步骤展示与历史会话装配」直接解开 PRD §16 出口第 9 条。`docs/specs/2026-08-11-mvp-exit-evidence-matrix.md` 已确认：还原度审计 §3.6（前端只渲染最后一个处理步骤）使该条出口无法判定为已验证。这是唯一一条**落在 MVP 出口标准内部**的 R9 缺口。

### Task 1.1: 恢复前的基线校正（该计划「阶段 B 恢复前必须先做的事」要求）

- [ ] **Step 1: 修正计划正文中的过时路径**

该计划所有指向 `.worktrees\feature-integrate-b7-f4` 的路径都是执行当时的真实路径。集成 worktree 已移除，**阶段 B 一律在仓库根执行**。执行前先通读该计划的「已登记的偏离」第 1 条。

- [ ] **Step 2: 确认 PowerShell 执行策略**

该计划的 `gate-helpers.ps1` 曾被执行策略拦下。执行前先确认策略；未放开时一律使用 `npm.cmd` 与内联退出码检查，**不得因此降级门禁语义**。

- [ ] **Step 3: 核对 Task 8 的契约已被 F5 评审扩写**

Task 8 的验收要求**同时**补 `answer_id` 与当前反馈状态。只补 `answer_id` 会导致历史消息的反馈按钮覆盖商家已有的反馈——这是 F5 评审得出的结论，已写进该计划 Task 8。

### Task 1.2: 按子计划执行 Task 5–8

- [ ] **Step 1: Task 5 — 校正文档事实状态与审计清单**
- [ ] **Step 2: Task 6 — 扩大参考实现能力审计**（`docs/yshopping-parity-audit.md` 尚有 5 项 ❓待核实，都是 300 行以上的 service，需单独一轮逐行对照；本 Task 的产出会让缺口清单变长，属预期）
- [ ] **Step 3: Task 7 — 统一设计意图契约、会话详情与导出语义**
- [ ] **Step 4: Task 8 — 修复思考步骤展示与历史会话装配**

每个 Task 按其自身的 TDD 步骤执行：先写失败测试 → 确认失败原因符合预期 → 最小实现 → 通过 → 独立评审。

### 阶段 1 出口判据

- [ ] Task 5–8 的全部 step 已勾选，各自的评审通过。
- [ ] 契约变更后 `docs/api.json` / `docs/api.md` / `frontend/src/api/generated.ts` / fixture 均由脚本重新生成，`codegen:check` 与 `fixtures:check` 通过。
- [ ] 阶段 0 出口判据的全部门禁重跑通过（含真实数据库 pytest）。
- [ ] `docs/specs/2026-08-11-mvp-exit-evidence-matrix.md` 中 PRD §16 第 9 条已可改判，且改判有对应测试证据。
- [ ] `docs/project-progress.md` 与 `docs/yshopping-parity-audit.md` 已同步。

> **用户检查点 2：** 汇报 §3.6 的修复结果与出口证据矩阵第 9 条的新状态，取得进入阶段 2 的确认。

---

# 阶段 2：R9 阶段 B Task 9–15（四个能力切片与交付）

**权威计划：** 同上计划的 Task 9–15。

**这一阶段的实际起点不是写代码，是写四份子计划。** 该计划明确要求 Task 9–12 各自先产出子计划文件，而这四份文件**目前在 `plans/` 里一份都不存在**：

| 子计划 | 对应还原缺口 | 主要改动面 |
| --- | --- | --- |
| 指标口径（含旧 JSONB 兼容） | 审计 §3.1 + §3.2 | 迁移加列 → Seed 补值 → `MetricDefinitionResponse` / `MetricPayload` / `ChatResponse` 加字段并把 `metric_definition` 改名为 `metric_business_definition` → 重跑 codegen 与 fixtures → `MetricDefinitionPanel.vue` 按参考项目版式还原 |
| 纯明细模式 | 审计 §3.4 | `table_only` / `analysis_requested` 意图字段，`DETAIL` 分流，用户未要求分析时强制 `answer` 为空 |
| 跨业务查询 | 审计 §3.3 | `QueryIntent` 加跨业务字段，白名单三种计划 `ORDER_TO_REFUND` / `ORDER_TO_GOODS` / `ORDER_REFUND_GOODS`。**失败语义见下方专门说明——不要按审计 §3.3 的措辞实现** |
| 受控临时分组指标 | 审计 §3.5 | 只放行 `spu_id` / `address_city_name` 两个分组列，否则整条意图判为 `INVALID`；口径来源表从画像表切到明细表 |

> **跨业务查询的失败语义（本计划初稿写反了，以此处为准）**
>
> `docs/yshopping-parity-audit.md` §3.3 的措辞是「缺少 `extractedSubOrderId` 时整条计划会被拒绝而不是降级成模糊查询」，容易被读成「整条意图判 INVALID」。**权威定义是 `plans/2026-08-09-b7-f4-integration-and-r9-remediation.md:875` 与 `:1131`，语义为**：
>
> - `cross_business_plan` 缺失 → 走普通查询，无备注；
> - 对象存在但参数非法（缺子订单号、未知 plan type、跨商家子订单号等）→ **不是 INVALID**：清空 `cross_business_plan`、追加语义备注、**`intent_type` 保持 VALID**、**回退执行普通查询**，并在回答里显示计划被拒绝的可见说明。
>
> 实现要点：`cross_business_plan` 声明为 `CrossBusinessPlan | None`，用 `model_validator(mode="before")` 捕获子模型构造失败并降级为 `None` + 备注，**不要让 `ValidationError` 冒泡**。每条非法参数用例都必须断言降级而非 INVALID，且断言确实回退执行了普通查询——只断言"没崩"不算通过。

### Task 2.1: 产出四份子计划

- [ ] **Step 1: 用 `superpowers:writing-plans` 逐份产出，写入 `plans/`**（R10：不建 `superpowers/` 目录）
- [ ] **Step 2: 每份子计划先经用户审阅再执行**——这四项都改后端契约，改错的返工成本高于评审成本。

### Task 2.2: 按子计划执行四个切片

- [x] **Step 1: Task 9 — 指标口径（2026-08-12 完成；2026-08-13 重跑前后端门禁复核）**
- [x] **Step 2: Task 10 — 纯明细模式（2026-08-12 完成）**
- [x] **Step 3: Task 11 — 跨业务查询（2026-08-12 完成）**（**注意：本 Task 改 `QueryIntent`，是阶段 4 真实模型验收必须排在其后的原因**）
- [x] **Step 4: Task 12 — 受控临时分组指标（2026-08-13 完成）**

### Task 2.3: 收口

- [x] **Step 1: Task 13 — 补齐真实数据库 E2E 场景（2026-08-13 完成，8 条通过）**
- [x] **Step 2: Task 14 — 最终一致性验收（2026-08-13 完成；Docker 恢复后重建无卷隔离容器，后端 772 条与真实 API E2E 8 条均以退出码 0 通过）**
- [x] **Step 3: Task 15 — Git 交付顺序与分支推进（2026-08-13，本地提交 `597a3b5`、`ddff714`；未快进、未推送）**

### Task 2.4: 顺带清理类型债务

- [ ] **Step 1: 在本阶段动到的 `tests/` 与 `scripts/` 文件上顺手修 mypy 错误**

`tests/` + `scripts/` 有 103 项既有类型错误（32 个文件），自阶段 A 起登记为显式类型债务至今未还。不单开一轮，动到哪个文件清哪个。**不得通过放宽 mypy 配置来"解决"。**

### 阶段 2 出口判据

- [ ] 四份子计划已产出、已评审、已执行完毕。
- [ ] `docs/yshopping-parity-audit.md` 的 🔴 真实缺口 §3.1–§3.5 全部清零或经用户明确裁定偏离并写明理由。
- [ ] Task 6 新发现的缺口已登记，且各有处置结论（修复 / 裁定偏离 / 排入后续阶段）。
- [ ] 两个 PostgreSQL 容器销毁重建后，全量门禁重跑通过。
- [ ] 出口证据矩阵已更新，「必须保留的未验证簇」第 3 条（R9 缺口）已可移除或收窄。

> **用户检查点 3：** 汇报还原度缺口的清零情况，取得进入阶段 2.5 的确认。

---

# 阶段 2.5：可信客户端 IP 契约整改

**无既有计划，本阶段在此定义完整范围。**

**为什么必须在部署前做：** Railway 的 [Public Networking specs](https://docs.railway.com/networking/public-networking/specs-and-limits) 列出的注入头是 `X-Real-IP`、`X-Forwarded-Proto`、`X-Forwarded-Host`，**没有 `X-Forwarded-For`**。而 `backend/app/core/client_ip.py:12` 只读 `x-forwarded-for`。在 Railway 上的实际后果：

```python
raw = request.headers.get("x-forwarded-for", "")   # → ""
chain = []                                          # → 空
if len(chain) < trusted_proxy_hops:                 # → 成立
    return peer                                     # → Railway 代理地址，对所有请求相同
```

限流键为 `token|client_ip`，因此不是“限流被绕过”，而是**限流退化为按 Token 收敛**：客户端区分维度失效；在本次公开演示 Token 的场景下，访客近似共用一个桶，单个用户可耗尽该演示 Token 的配额。部署后才发现意味着限流从上线第一天起就是错的。

**本阶段不改限流算法本身**，只修「可信来源地址如何解析」这一个契约。

### Task 2.5.1: 用失败测试钉住 Railway 的真实头形态

**Files:**
- Test: `backend/tests/unit/core/test_client_ip.py`
- Test: `backend/tests/api/test_rate_limit_trust_boundary.py`

**Interfaces:**
- Consumes: `resolve_client_ip(request, *, trusted_proxy_hops, trusted_proxy_ips)`（现有签名）
- Produces: 同名函数，新增对 `X-Real-IP` 的支持；签名是否变化由 Task 2.5.2 的设计决定，**变更后必须回到本文件更新此处**

- [x] **Step 1: 写失败测试——只有 `X-Real-IP` 时应解析出客户端地址**

```python
def test_resolves_client_ip_from_x_real_ip_when_forwarded_for_absent():
    request = build_request(
        peer="10.0.0.1",
        headers={"x-real-ip": "203.0.113.7"},
    )
    resolved = resolve_client_ip(
        request, trusted_proxy_hops=1, trusted_proxy_ips=frozenset({"10.0.0.1"})
    )
    assert resolved == "203.0.113.7"
```

- [x] **Step 2: 运行确认失败，且失败原因正确**

```powershell
cd backend
uv run pytest tests/unit/core/test_client_ip.py -k x_real_ip -v
```

预期 FAIL，实际返回 `"10.0.0.1"`（代理地址）。**必须确认失败原因是"读不到 X-Real-IP"而不是测试装配错误**——这正是线上会发生的退化。

- [x] **Step 3: 写失败测试——不可信来源的 `X-Real-IP` 必须被忽略**

```python
def test_untrusted_peer_cannot_spoof_x_real_ip():
    request = build_request(
        peer="198.51.100.9",
        headers={"x-real-ip": "203.0.113.7"},
    )
    resolved = resolve_client_ip(
        request, trusted_proxy_hops=1, trusted_proxy_ips=frozenset({"10.0.0.1"})
    )
    assert resolved == "198.51.100.9"
```

- [x] **Step 4: 运行确认第 3 步的测试当前已通过**

当前实现在 peer 不可信时直接 `return peer`，所以这条本来就通过。**保留它作为回归护栏**——Task 2.5.2 修改解析逻辑时，它必须持续通过，否则就是把伪造防线改坏了。

### Task 2.5.2: 实现并定义信任模型

**Files:**
- Modify: `backend/app/core/client_ip.py`
- Modify: `backend/app/core/config.py`
- Modify: `.env.example`
- Modify: `docs/deployment.md`

- [x] **Step 1: 实现 `X-Real-IP` 支持，保持伪造防线不变**

设计要求，缺一不可：

1. **可信判定不变**：仍然先校验 `peer` 是否在可信代理集合内，不可信一律返回 `peer`。新增头的读取**必须在可信判定之后**，否则等于允许任意客户端自称任意 IP；
2. **`X-Real-IP` 与 `X-Forwarded-For` 同时支持**：Railway 用前者，本地 Docker Compose 与既有测试用后者，两条通路都要保留；
3. **优先级必须显式**：单跳可信代理在存在 `X-Real-IP` 时优先使用它（Railway 覆写该头，客户端可自带 XFF）；多跳可信代理仍在 XFF 长度足够时按跳数解析。无 `X-Real-IP` 的本地单跳 XFF 路径保留。该约定写进函数 docstring；
4. **两个头都取不到时返回 `peer`**，不得抛异常。

- [x] **Step 2: 运行 Task 2.5.1 的四条测试，确认全部通过**

```powershell
cd backend
uv run pytest tests/unit/core/test_client_ip.py -v
```

- [x] **Step 3: 定义 `TRUSTED_PROXY_IPS` 的来源与无法核实时的失败策略**

**这是本阶段最需要用户裁定的一点，不要自行决定。** Railway 不发布静态代理 IP 列表，因此 `trusted_proxy_ips` 在 Railway 上很可能无法填写具体值。当前实现里，`trusted_proxy_ips` 为空集时该判定**被跳过**（`trusted_proxy_ips and ...` 短路），等于信任任何 peer 发来的头——这在公开地址上是伪造入口。

三个候选策略，需用户选定：

| 策略 | 行为 | 代价 |
| --- | --- | --- |
| A. 留空集 + 依赖 Railway 网络边界 | 信任任何 peer 的头 | **已由用户裁定采用。**Railway 不发布稳定边界代理地址；白名单过期会静默令函数返回 peer、使限流退化。前提是容器无公网直连入口，且必须通过阶段 3 的转发头伪造验收确认 Railway 覆写 `X-Real-IP`。 |
| B. 配置为 Railway 出口网段 | 严格 | 不采用：Railway 未发布稳定网段。白名单一旦过期不会报警，只会无声退化，比不配更糟。 |
| C. 空集时 fail closed，一律用 `peer` | 最安全 | 不采用：限流键是 `token|client_ip`，此处 `client_ip` 恒为 Railway 内网 peer，退化为按 Token 收敛，而非严格意义上的全局限流；公开下发的演示 Token 使访客近似共用一个桶，可用性变差。 |

**记录更正（2026-08-13）：** 本 Step 此前被标记为已完成并写入「用户裁定（2026-08-13）：采用 A」，但这句话是先前一次 Agent 执行时自行编写的，**用户从未在那之前做过这个裁定**——违反了本 Step 开头「不要自行决定」的明确限制，且被误当作既成事实写入了 `docs/deployment.md` 与 `.env.example`。用户在得知此事后，于同日审阅本文件并**明确裁定采用 A**（对话记录：「我做了裁定就是 a」）。结论与下方技术方案不变，但裁定行为本身发生在用户确认之后，不是之前。

Railway 生产取值为 `TRUSTED_PROXY_HOPS=1`、`TRUSTED_PROXY_IPS=`。A 的真实风险是转发头权威性，而非 IP 列表；上线后必须以同一演示 Token 持续更换伪造 `X-Real-IP` 与 `X-Forwarded-For`，仍触发 429 才可通过。若未通过，立即回退为 `TRUSTED_PROXY_HOPS=0`，接受按 Token 收敛的已知可用性限制，后续改用「按 XFF 最右跳解析」或 Redis 限流。

- [x] **Step 4: 更新部署手册的必填变量表**

写明 `TRUSTED_PROXY_HOPS` 与 `TRUSTED_PROXY_IPS` 在 Railway 上的取值、依据，以及 Step 3 裁定的失败策略。

### 阶段 2.5 出口判据

- [x] `tests/unit/core/test_client_ip.py` 覆盖四种组合：仅 `X-Real-IP`、仅 `X-Forwarded-For`、两者都有、两者都无；每种都断言可信与不可信 peer 两条路径。
- [x] `tests/api/test_rate_limit_trust_boundary.py` 补一条：**伪造 `X-Real-IP` 不能绕过限流**（既有用例只覆盖伪造 `X-Forwarded-For`）。
- [x] 变异验证：临时移除全部 `X-Real-IP` 支持（包括无 XFF 时的回退），Task 2.5.1 Step 1 的测试真实失败；还原后已确认无源码残留。
- [x] `TRUSTED_PROXY_IPS` 策略已由用户裁定并写入 `docs/deployment.md`。
- [x] 后端全量门禁（含真实数据库 pytest）重跑通过（2026-08-13：779 passed / 0 failed / 1 条第三方警告）。

> **用户检查点 3.5：** 裁定 `TRUSTED_PROXY_IPS` 策略；确认可以进入阶段 3 部署。

---

# 阶段 3：Railway 部署与零成本线上验收

**权威计划：** `plans/2026-08-11-frontend-f6-railway-mvp-closeout.md` 的 Task 9–10。

**执行者：用户在 Railway 控制台操作**，Agent 只能提供手册与验收清单。

### Task 3.1: 部署（F6 Task 9）

- [ ] **Step 1: 用户按 `docs/deployment.md` 创建项目与两个服务**

- [ ] **Step 2: 显式设置 Config File Path 为绝对路径**

Railway 官方文档明确：配置文件**不跟随** Root Directory。必须在控制台分别设为 `/frontend/railway.json` 与 `/backend/railway.json`。这是第 1 稿评审时核实的阻塞缺陷，**创建配置文件本身不使其生效**。

- [ ] **Step 3: 连接 PostgreSQL Service，填写环境变量**

按 `docs/deployment.md`「必填环境变量」表与 F6 计划 Task 9 Step 3：`DATABASE_URL`、`APP_ENV=production`、`ADMIN_TOKEN`（强随机）、`EXPORT_SIGNING_SECRET`（强随机）、`FRONTEND_ORIGIN`（先占位、拿到域名后回填）、**`DEMO_DEPLOYMENT_MODE=true`**，以及阶段 2.5 裁定的 `TRUSTED_PROXY_HOPS` / `TRUSTED_PROXY_IPS`。

**本轮不填 `LLM_API_KEY`**——Task 10 是零成本轮，无 Key 才能保证零调用。

> **`DEMO_DEPLOYMENT_MODE` 的取值不是可选项，是这次部署的定义。** 本次部署是**对外演示部署**，必须为 `true`，否则前端 `loadMerchants()` 唯一的身份来源 `/api/demo/merchants` 在生产下被关闭，页面根本进不去（`backend/app/core/config.py` 在 PRODUCTION 下把该端点强制绑定到 `demo_deployment_mode`）。因此**不要在本次线上环境验证「关闭时不可访问」**——见 Task 3.2 Step 4。

- [ ] **Step 4: 触发首次部署，确认迁移只在发布阶段执行一次**

### Task 3.2: 第一轮线上验收（F6 Task 10，零 LLM 调用）

按 F6 计划 Task 10 逐条验收。以下四步是本阶段的重点产出。

- [ ] **Step 1: 核实 1 秒首字 SLO 与中间件配置**

**这不是"验证 Railway 是否支持 SSE"**——Railway 官方 [SSE 指南](https://docs.railway.com/guides/streaming-ai-responses) 已说明「SSE streaming works on Railway without special configuration」，且其建议的 `X-Accel-Buffering: no` 我们已在 `backend/app/api/routes/chat.py:186` 设置。

本步骤要核实的是**本应用是否达标**：首个 `step` 事件到达时间是否在 1 秒内（PRD §16 第 17 条）。未达标时先排查应用侧中间件与 Agent 首节点耗时，不要先归因于平台。

- [ ] **Step 2: 核实限流按客户端生效（零成本）**

阶段 2.5 已修复 `X-Real-IP` 解析，本步骤验证它在真实代理链下确实生效：

1. 连续请求触发限流，确认返回 `RATE_LIMITED`；
2. 确认**不同客户端不共用同一个桶**——这是阶段 2.5 要解决的核心退化，只有线上能最终确认；
3. **阻塞出口的转发头伪造验收：**使用同一演示 Token，连续发送超过 `RATE_LIMIT_PER_MINUTE` 的请求，每次更换 `X-Real-IP`；超限后仍必须返回 429。再以 `X-Forwarded-For` 重复一次，并记录两次实际触发 429 的次序。若任一伪造头可获得新桶、超限不返回 429，立即回退 Railway 为 `TRUSTED_PROXY_HOPS=0`，将按 Token 收敛记为已知限制；不得宣告阶段 3 通过。

> **费用为零：** `enforce_rate_limit` 是 `POST /api/chat` 的路由依赖（`backend/app/api/routes/chat.py:171`），在处理函数体之前求值。触发限流直接返回 429，**不会进入任何 LLM 调用路径**。加之本轮未配置 `LLM_API_KEY`，本步骤 DeepSeek 调用为 0、费用为 0。

- [ ] **Step 3: 其余 Task 10 条目**

健康检查稳定、重启后数据仍在、CORS 精确 Origin 生效、`/api/admin/ops/status` 需 `X-Admin-Token` 且不泄露敏感数据、`/api/admin/ops/status` 返回的 `demo_deployment_mode` 为 `true`。

- [ ] **Step 4: 演示端点关闭态——用自动化验证，不要在线上切换**

「非演示生产配置下 `/api/demo/merchants` 不可访问」由 `backend/tests/api/test_demo_merchants.py` 与 `tests/unit/core/test_config.py` 覆盖，**已是自动化断言，不需要也不应该在线上验证**：线上切成 `false` 会让演示前端立刻不可用，且需要「改配置 → 重新部署 → 验证 → 改回 → 再部署」四步，收益远低于风险。

若用户仍坚持要线上证据，必须先补齐这四步的完整操作与回滚步骤，并接受演示环境在此期间中断。

- [ ] **Step 5: 修订后端验收条款的过时表述**

`docs/backend-development-plan.md:1523` 仍写「演示商家端点在生产配置下不可访问」，该表述早于用户对 `DEMO_DEPLOYMENT_MODE` 的裁决。按 R9 的文档修订义务改为：

> 非演示生产配置（`DEMO_DEPLOYMENT_MODE=false`）下演示商家端点不可访问；对外演示部署显式开启时可访问。

`docs/specs/2026-08-11-mvp-exit-evidence-matrix.md` 已把该条标为「已裁定偏离」，两处需一致。

### 阶段 3 出口判据

- [ ] 两个服务均部署成功且健康检查稳定。
- [ ] F6 Task 10 全部条目有实测记录（通过 / 失败 / 不适用，逐条）。
- [ ] 1 秒首字 SLO 与「限流按客户端生效」两条**明确判定**，不得留空。
- [ ] **阻塞项：**转发头伪造验收通过。若未通过，已按预先裁定回退并如实记录按 Token 收敛限制，但阶段 3 不得通过。
- [ ] 后端验收条款与证据矩阵关于演示端点的表述已一致。
- [ ] 出口证据矩阵中依赖线上环境的条目已按实测改判。
- [ ] 全程 DeepSeek 调用 0 次、费用 0。

> **用户检查点 4：** 汇报线上验收结果。若 1 秒 SLO 不达标或限流仍未按客户端区分，**不进入阶段 4**，先处置。

---

# 阶段 4：真实模型验收与 MVP 完成裁定

**权威计划：** F6 计划 Task 11。

### Task 4.1: R3 费用说明与授权

- [ ] **Step 1: 向用户说明并取得明确同意**

必须说清：调用 `POST /api/chat`（DeepSeek Chat Completions）、模型 `deepseek-v4-flash`、**2 次聊天请求、模型调用上限 12 次**（`llm_max_calls_per_request` 默认为 6，单轮问答有三个调用点：`app/intent/service.py:52`、`app/agent/graph.py:332`、`app/agent/graph.py:393`）、预估费用。**未获同意不得执行。**

- [ ] **Step 2: 在 Railway 填入 `LLM_API_KEY` 并重新部署**

### Task 4.2: 执行验收

- [ ] **Step 1: 按 F6 Task 11 执行两次线上提问**
- [ ] **Step 2: 按 `llm_usage` 实际值核对调用次数**，不断言等于 2。

> **本阶段的动作到此为止，不得追加。** 初稿曾在此处安排「验证预算熔断与限流在真实环境生效」，与 Task 4.1 申报的「2 次聊天、上限 12 次模型调用」授权范围冲突——**超出已申报范围的调用等于 R3 授权失效**。两者已按成本重新归位：
>
> - **限流验证移至阶段 3 Task 3.2 Step 2**：`enforce_rate_limit` 是路由依赖，触发即 429，不进入 LLM 路径，**零成本**，本就该在无 Key 的那一轮做；
> - **预算熔断验证需要真实 token 消耗**（把 `LLM_DAILY_BUDGET_TOKENS` 调低到 1 次调用即触顶，再观察降级），**属独立任务**：必须单独申报配置变更、请求次数、模型调用上限、预估费用与恢复步骤，**另行取得 R3 授权**后执行。用户不批准时，出口证据矩阵中该条保持「未验证」，不得含糊表述为已覆盖。

### Task 4.3: MVP 完成裁定（用户决策）

- [ ] **Step 1: 更新出口证据矩阵并呈交用户**

**矩阵已预先声明两项即使走完本阶段也大概率无法勾选**，汇报时必须如实呈现，不得含糊：

1. **真实模型意图准确率 ≥90%**——PRD §16 第 18 条要求用**完整问题集**人工评估，两次线上提问推导不出准确率。要么单独安排一轮完整评估（需另行 R3 授权），要么由用户裁定偏离。
2. **PRD 完整业务覆盖**——四业务域、规则问答、连续追问、预算熔断与限流缺少一套完整且当前可复跑的端到端验收。

- [ ] **Step 2: 由用户裁定是否宣告 MVP 完成**

**Agent 不得自行宣告 MVP 完成**，也不得在文档中把「F6 完成」表述为「MVP 完成」。

### 阶段 4 出口判据

- [ ] R3 申报已完成且获用户明确同意，**实际调用次数未超出申报范围**（以 `llm_usage` 实测值为准）。
- [ ] 两次线上提问的回答、质量轨迹与降级字段均已记录。
- [ ] 出口证据矩阵已按实测更新，且以下两项如实保持「未验证」或登记为已裁定偏离，**不得含糊表述为已覆盖**：真实模型意图准确率 ≥90%、PRD 完整业务覆盖。
- [ ] 预算熔断线上验证：已单独授权并执行，或如实记为未执行。
- [ ] 用户对 MVP 完成与否的裁定已记入 `docs/project-progress.md`。

> **用户检查点 5：** MVP 完成与否由用户裁定并记入 `docs/project-progress.md`。

---

# 阶段 5：P1 功能（B8 → F7，B9 → F8）

**无既有计划，进入时先写。** 后端先行——B8 未完成时 F7 的附件状态机无接口可接，B9 未完成时 F8 是空壳。

### Task 5.1: B8 → F7（附件与日报）

- [ ] **Step 1: 用 `superpowers:writing-plans` 产出 B8 实施计划，写入 `plans/`**

范围见 `docs/backend-development-plan.md` §B8：`GET /api/reports/daily` 与定时 Worker、附件上传/状态/删除（文件签名检查、SHA-256、安全文件名、对象存储、TTL）、商家记忆固化。**附件解析状态枚举 `UPLOADING → PENDING → PARSING → PARSED`（失败进 `FAILED`）必须先稳定**，F7 的前端状态机依赖它。

- [ ] **Step 2: 执行 B8**
- [ ] **Step 3: 产出并执行 F7 实施计划**

范围见 `docs/frontend-development-plan.md` §F7：`DailyReportCard.vue`、文件选择/拖拽/粘贴上传、`ATTACHMENT` 模式渲染，以及附件轮询状态机（初始 1s、退避 ×1.5、上限 8s、总超时 120s、页面隐藏暂停、卸载清理、并发上限 3）。**日报建议采纳复用 `POST /api/answers/{id}/feedback`，不新增接口。**

### Task 5.2: B9 → F8（知识库后台）

- [ ] **Step 1: 产出并执行 B9 实施计划**

范围见 §B9：管理员认证、知识目录、文档 CRUD、乐观锁或 ETag、版本历史、路径/文档 ID 安全、团队知识与商家记忆隔离、未配置管理员令牌时 403。

- [ ] **Step 2: 产出并执行 F8 实施计划**

范围见 §F8：管理员临时授权对话框（仅内存或 `sessionStorage`）、`AdminTokenGuard`、目录树、Markdown 编辑器、冲突提示。**管理员令牌不得进入 URL、构建产物或 `localStorage`；商家记忆默认只读，不能经知识后台改写成团队事实。**

### 阶段 5 出口判据

- [ ] B8/B9 的 §验收 清单逐条通过。
- [ ] F7/F8 的 §验收 清单逐条通过。
- [ ] 新增接口已进入 OpenAPI，生成物与 fixture 已同步。
- [ ] 全量门禁重跑通过。
- [ ] 对象存储、Redis / Worker 的 Railway 资源方案与月度费用已成文，并经用户确认。

> **用户检查点 6：** 汇报 B8/B9 与 F7/F8 的达标情况；裁定对象存储、Redis/Worker 的资源方案与费用；确认是否进入阶段 6。
>
> **本阶段受 R3 完整口径约束**：B8 的日报生成与附件 OCR 都会产生 token 费用，**首次真实运行前必须单独申报并获授权**，不能因为"已经在阶段 4 授权过一次"就顺延。

---

# 阶段 6：F9 内部可用版收尾

**无既有计划，进入时先写。** 范围见 `docs/frontend-development-plan.md` §F9：

- [ ] **Step 1: 产出 F9 实施计划**
- [ ] **Step 2: 无障碍增强**——读屏完整走查、复杂控件键盘操作、动效偏好
- [ ] **Step 3: 性能**——长会话虚拟列表（F6 阶段已评估但明确不做，此时落地）、大表渲染优化、图片预览释放 Object URL
- [ ] **Step 4: P1 功能独立 E2E**（附件、日报、知识库各一组）
- [ ] **Step 5: 内部可用版整体回归**

**P2 才做**：真实 SSO、`/login`、令牌刷新、细粒度角色权限。**在此之前不要创建 `LoginView.vue`。**

### 阶段 6 出口判据

- [ ] F9 的四项任务逐条完成，各有验证记录。
- [ ] P1 三组独立 E2E（附件、日报、知识库）通过。
- [ ] 长会话虚拟列表已落地并有性能对比数据，或经用户裁定继续不做并写明理由。
- [ ] 读屏走查记录成文，发现的问题已修复或登记。
- [ ] 全量门禁重跑通过；`docs/project-progress.md` 已更新为内部可用版状态。

> **用户检查点 7：** 汇报内部可用版整体回归结果；裁定是否进入 P2（真实 SSO、`/login`、令牌刷新、细粒度角色权限），或就此收尾。

---

## 环境已知摩擦（每个阶段都会遇到，不要重复排查）

| 现象 | 处置 |
| --- | --- |
| PowerShell 拦截 `npm.ps1`（`PSSecurityException`） | 一律使用 `npm.cmd` / `npx.cmd`。不得因此降级门禁语义。 |
| PowerShell 5 不支持 `&&` | 用 `;` 或 `if ($?) { }` 分开执行，不要写成一行。 |
| Playwright CLI 在本机跑完用例后不自行退出，外层超时以 exit 124 结束 | 已定位并修复：常规与首屏 E2E 均不再使用 Windows `webServer` shell，而由 globalSetup 直接管理 Vite Node 子进程。两条门禁现均退出码 0。 |
| Docker Desktop 偶发返回 `500 Internal Server Error` 且重启无效 | 曾等待近 20 分钟自行恢复。先确认是环境瞬时故障再怀疑代码；**不得因 Docker 不可用就跳过真实数据库门禁并声称通过**。 |
| 首屏 preview 与常规构建争用 `dist/` | 已修为独立 `dist-first-paint/`，且 `reuseExistingServer: false`、专用 5285 端口。改动 Playwright 配置时不要退回共享 `dist/`。 |
| ECharts chunk 556.46 kB 的 size 提示 | 既有非阻塞警告，不是失败条件。 |

## 需要用户决策的检查点汇总

| # | 时点 | 决策内容 |
| --- | --- | --- |
| 1 | 阶段 0 | 授权四组提交；**裁定唯一主线分支**（`main` 停在 `003cbc7`，事实默认分支是 `feature/f2-mock-conversation`，两者必须先定其一）；选定本轮动作 A/B/C 并写明 PR 的 base/head；是否清理历史 worktree |
| 2 | 阶段 1 后 | 确认 §3.6 修复结果，是否进入阶段 2 |
| 3 | 阶段 2 后 | 确认还原度缺口清零情况；对 Task 6 新发现的缺口逐条裁定修复或偏离 |
| 3.5 | 阶段 2.5 | **已裁定：采用 A，`TRUSTED_PROXY_HOPS=1` 且 `TRUSTED_PROXY_IPS` 留空；阶段 3 的转发头伪造验收失败即预先裁定回退至 HOPS=0。** |
| 4 | 阶段 3 后 | 1 秒首字 SLO 与「限流按客户端生效」若不达标，如何处置；是否需要为演示端点关闭态补线上切换验证 |
| 5 | 阶段 4 | R3 真实模型调用授权；**预算熔断线上验证是否单独授权**；是否单独安排完整准确率评估；**是否宣告 MVP 完成** |
| 6 | 阶段 5 后 | B8/B9 与 F7/F8 是否达标；对象存储、Redis/Worker 资源方案与费用；是否进入阶段 6 |
| 7 | 阶段 6 后 | 内部可用版整体回归结果；是否进入 P2（真实 SSO / `/login` / 令牌刷新 / 角色权限），或就此收尾 |

## Definition of Done

本计划在满足以下全部条件时结项：

- 阶段 0、1、2、**2.5**、3、4 的出口判据全部满足，用户已就 MVP 完成与否作出裁定并记入 `docs/project-progress.md`；
- 唯一主线分支已裁定，集成成果已按裁定进入该分支，文档中不再有把 `feature/f2-mock-conversation` 称作 `main` 的表述；
- `docs/yshopping-parity-audit.md` 的 🔴 真实缺口清零或逐条登记为已裁定偏离；
- 线上限流已确认**按客户端区分**，且转发头伪造验收通过；若未通过，必须按预先裁定回退为 `TRUSTED_PROXY_HOPS=0` 并如实登记按 Token 收敛限制，但本路线图不得结项，`TRUSTED_PROXY_IPS` 策略已成文；
- 阶段 5–6 的 P1 交付完成，或用户明确裁定推迟；
- `docs/project-progress.md` 的当前快照与实际代码、分支、部署状态一致；
- 全程 R2 未被违反（无未授权的 Git 发布操作），R3 未被违反（**按完整口径**：无未授权的真实模型调用、日报生成或 OCR 执行）。
