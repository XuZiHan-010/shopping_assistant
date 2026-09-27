# N2 商家端 Vue 客户端 v2 迁移实施计划

> **给执行者：** 用 `superpowers:executing-plans` 逐任务推进。步骤用 `- [ ]` 复选框跟踪。
> **本计划不含任何 Git 提交步骤**（R2）。全程 mock 后端或本地 Fake LLM 后端，零费用。

**目标：** 把现有 Vue 商家工作台从 v1 Bearer 直连迁移到 v2 会话模式，并新增 S3 所需的三块界面：
**审批界面**、库存告警、最小当日简报。v1 页面在切换完成前保持可用。

**架构：** 沿用既有单向字段流 `OpenAPI → generated.ts → adapters → types → Store → 组件`
（`AGENTS.md` §8.5），**组件不得直接消费 `generated.ts`**。会话 ID 与 Token 同级，
**只进内存与请求头**，沿用 `src/api/credentials.ts` 的 `AuthScope` 机制扩展，不另起一套。

**技术栈：** Vue 3、TypeScript、Pinia、vue-i18n、Vitest、Playwright。

**规格来源：** PRD M1、M5、M10、§7.5、§11.3；`AGENTS.md` §8.3、§8.4、§8.5、§十一；
`docs/frontend-development-plan.md`（身份、401、刷新恢复）；契约计划 §8.7、§8.9、§8.12、§8.13。

---

## 入口条件

- [x] `n2-merchant-drafts-and-inventory` 已完成，且其五项完成门槛含 **`docs/api.json` 已导出**
      v2 商家路由——本计划的 `npm run codegen` 读的就是它
      （2026-09-23 核实：Task 1–7、9 已完成，7 条商家路由已导出；Task 8 端到端仍卡在模块 B，
      不影响本计划要读的路由形状，详见 `.superpowers/sdd/2026-09-21-n2-merchant-vue-v2-migration/progress.md`）；
- [x] 会话计划已完成（含 Task 7 会话签发路由）：`POST /api/v2/merchant/sessions` 与 `DELETE /api/v2/merchant/sessions/current`
      可用，`frontend/src/api/adapters/session.ts` 已存在；
- [x] **核对契约计划 §8.9 / §8.12 / §8.13 与导出的 `docs/api.json` 一致**，
      不一致先修后端，**不在前端 Adapter 里打补丁吸收差异**
      （已核对 `InventoryAlert`、`DraftDetailResponse`、`DraftApplyRequest/Response`、`DailyBriefResponse`
      与 §8.12/§8.13 字段一致，无差异）。

---

## 全局约束

- 中文（R1）；**不执行 Git 操作**（R2）；**不调用真实 LLM**（R3）。
- **`generated.ts` 禁止手改**，只由 `npm run codegen` 生成，`codegen:check` 守护。
- **会话 ID、Token、审批证据只进内存**：不写 `localStorage` / `sessionStorage` / URL /
  日志 / 构建产物。`sessionStorage` 只允许存非敏感的商家标识（沿用现有 `MERCHANT_STORAGE_KEY`）。
- **前端不得把 `merchant_id` 当可信参数传给后端**（`docs/frontend-development-plan.md`）。
- 保留现有 7 个 TypeScript 基线错误的现状，**不新增**；若顺手修复须单独说明。
- 移动端对话区优先且**不得横向溢出**（M1）。

---

## 文件结构

| 文件 | 责任 |
| --- | --- |
| `frontend/src/api/credentials.ts` | 新增 `AuthScope = 'merchant-session'` → `X-Session-Id` |
| `frontend/src/api/generated.ts` | **由 codegen 重新生成**，不手改 |
| `frontend/src/api/adapters/session.ts` | 会话交换 Adapter |
| `frontend/src/api/adapters/drafts.ts` | 草稿列表、详情、应用、丢弃 |
| `frontend/src/api/adapters/inventory.ts` | 库存告警 |
| `frontend/src/api/adapters/brief.ts` | 最小简报 |
| `frontend/src/api/adapters/chatV2.ts` | v2 SSE 事件 → 领域事件 |
| `frontend/src/types/drafts.ts`、`inventory.ts`、`brief.ts` | 领域模型 |
| `frontend/src/stores/auth.ts` | 持有内存中的 `sessionId`；切换商家时销毁旧会话 |
| `frontend/src/stores/drafts.ts`、`inventory.ts` | 新 Store |
| `frontend/src/views/ApprovalView.vue` | **审批界面** |
| `frontend/src/views/InventoryView.vue` | 库存告警 |
| `frontend/src/views/TodayView.vue` | 最小简报 + 待批准草稿 |
| `frontend/src/router/index.ts` | 新增三条路由 |
| `frontend/e2e/s3-inventory-loop.spec.ts` | S3 浏览器 E2E |

---

### Task 1：会话凭证作用域

**文件：** `src/api/credentials.ts`、`src/api/credentials.spec.ts`

- `AuthScope` 新增 `'merchant-session'`，`buildAuthHeaders('merchant-session')` 返回
  `{ 'X-Session-Id': <内存中的 sessionId> }`；
- **每个端点只属于一个作用域**（`AGENTS.md` §8.3「前端不做有什么加什么」）：
  `POST /api/v2/merchant/sessions` 用 `'merchant'`（Bearer），其余 v2 商家端点用
  `'merchant-session'`，两者**不同时出现**在同一请求上。

- [x] **步骤 1：写失败测试**

```ts
it('merchant-session 作用域只带 X-Session-Id，不带 Authorization', () => {
  setCredentialProvider(() => ({ merchantToken: 'tk', sessionId: 'sid' }))
  const h = buildAuthHeaders('merchant-session')
  expect(h).toEqual({ 'X-Session-Id': 'sid' })
  expect(h).not.toHaveProperty('Authorization')
})

it('会话缺失时拒绝构造请求头，而不是发出注定 401 的请求', () => {
  setCredentialProvider(() => ({ merchantToken: 'tk' }))
  expect(() => buildAuthHeaders('merchant-session')).toThrow()
})
```

- [x] **步骤 2：确认失败 → 实现 → 确认通过**

```powershell
cd frontend; npm run test -- src/api/credentials.spec.ts
```

---

### Task 2：会话交换与切换商家

**文件：** `src/stores/auth.ts` 及其 spec；`src/api/adapters/session.ts` 由会话计划 Task 7 创建，本任务只在需要时扩展，不重建

> 2026-09-21：会话签发路由、商家会话 Adapter 与契约测试已并入 N1 会话计划 Task 7。开工前核对该 Adapter 实际导出的函数与
> 领域类型，本任务负责 Store 接入、切换商家与 401 恢复流程。

### 规则

- 选定演示商家 → 用 Bearer Token 调 `POST /api/v2/merchant/sessions` → `sessionId` 进内存；
- **切换商家**：先 `DELETE /sessions/current` 注销旧会话，**清空所有 Store**（会话目录、
  侧栏、草稿、库存），再换取新会话。**绝不在同一 `X-Session-Id` 下改商家**；
- **刷新恢复**：`sessionId` 只在内存，刷新即丢失。按既有做法重新取演示商家列表、
  用 `sessionStorage` 里的商家标识选回同一商家、**重新换取新会话**；
- **401 处理**：`SESSION_INVALID` 时清理内存会话，重新换取一次；仍失败则按既有规则
  打开商家切换器并提示，**保留未发送的输入内容**。

- [x] **步骤 1：写失败测试**

```ts
it('切换商家时先注销旧会话并清空所有 Store', async () => {
  await auth.selectAndOpenSession(M_A)
  drafts.items = [draftOf(M_A)]
  await auth.selectAndOpenSession(M_B)
  expect(api.deleteCurrentSession).toHaveBeenCalledWith(/* 旧 sid */)
  expect(drafts.items).toEqual([])
})

it('sessionId 不落任何持久化存储', async () => {
  await auth.selectAndOpenSession(M_A)
  const dump = JSON.stringify({ ...localStorage }) + JSON.stringify({ ...sessionStorage })
  expect(dump).not.toContain(auth.sessionIdForTest())
})

it('SESSION_INVALID 时自动重新换取一次，不直接弹切换器', async () => {
  api.listDrafts.mockRejectedValueOnce(apiError('SESSION_INVALID', 401))
  await drafts.load()
  expect(api.openMerchantSession).toHaveBeenCalledTimes(2)
})
```

- [x] **步骤 2：确认失败 → 实现 → 确认通过**

---

### Task 3：生成类型与 Adapter

- [x] **步骤 1：重新生成**

```powershell
cd frontend; npm run codegen; npm run codegen:check
```

- [x] **步骤 2：为草稿、库存、简报各写 Adapter 与契约测试**

Adapter 是 wire 格式与领域模型之间的唯一翻译点。两条必须的转换：

- **金额**：API 是整数分（契约计划 §8.7.8），领域模型保持整数分，**只在渲染层**用
  `utils/localizedFormat.ts` 格式化为元。任何地方都不得出现 `cents / 100` 后再参与计算——
  浮点在这里是真实的 bug 来源；
- **库存告警的 `days_of_supply: null`** 映射为领域枚举 `'UNKNOWN_NO_RECENT_SALES'`，
  **不得映射成 `0` 或 `Infinity`**（M5：不产生伪精确值）。

```ts
it('可售天数为 null 时映射为「未知」而不是 0', () => {
  const a = toInventoryAlert({ ...wireAlert, days_of_supply: null, sold_last_30d: 0 })
  expect(a.daysOfSupply).toEqual({ kind: 'unknown' })
})

it('Adapter 不对金额做浮点除法', () => {
  const src = readFileSync('src/api/adapters/drafts.ts', 'utf-8')
  expect(src).not.toMatch(/_cents\s*\/\s*100/)
})
```

- [x] **步骤 3：确认失败 → 实现 → 确认通过**

---

### Task 4：审批界面——本计划的核心

**文件：** `src/views/ApprovalView.vue`、`src/stores/drafts.ts` 及其 spec

**这是商家端所有写操作的唯一出口**（D9）。它也是审批证据唯一的合法消费者
（契约计划 §8.7.9）。

### 界面必须展示（M10、§8.13）

- 完整 diff：每个字段的旧值 → 新值；
- 草案版本、目标对象版本 / 变更基数；
- 护栏预检结果，并**标注"应用时将按当时配置重新检查"**——预检快照不是承诺；
- 起草者（Skill 名）、暂存时间、剩余有效期。

### 审批证据的前端处理

- 进入详情页时从 `GET /drafts/{draft_id}` 取得 `approval_evidence`，**只存组件内存**，
  **不进 Pinia Store**（Store 会被 devtools 与持久化插件看到）；
- 点击"批准并应用"时随请求提交，同时生成 `client_request_id`；
  **网络重试复用同一 `client_request_id`**（契约计划 §8.7.9：先查幂等再验证证据）；
- 收到 `422 CONFIRMATION_REQUIRED`：**重新拉取详情**取新证据，提示"草稿已变化或确认已过期，
  请核对后重新批准"，**不自动重试**——自动重试等于替用户重新批准了一个他没看过的版本；
- 收到 `409 VERSION_CONFLICT`（变更基数不符）：提示"库存已变化"，引导重新起草；
- 收到 `422 GUARDRAIL_REJECTED`：展示原因码对应的**当前限制与修正方法**（O5）；
- 护栏不通过的草稿，批准按钮禁用。

- [x] **步骤 1：写失败测试**

```ts
it('审批证据不进入 Pinia Store', async () => {
  const w = mountApproval({ draftId: D })
  await flushPromises()
  expect(JSON.stringify(useDraftsStore().$state)).not.toContain(EVIDENCE)
})

it('网络重试复用同一 client_request_id', async () => {
  api.applyDraft.mockRejectedValueOnce(networkError()).mockResolvedValueOnce(ok())
  await clickApprove()
  const ids = api.applyDraft.mock.calls.map((c) => c[0].clientRequestId)
  expect(new Set(ids).size).toBe(1)
})

it('CONFIRMATION_REQUIRED 时重新拉取详情且不自动重试应用', async () => {
  api.applyDraft.mockRejectedValueOnce(apiError('CONFIRMATION_REQUIRED', 422))
  await clickApprove()
  expect(api.getDraft).toHaveBeenCalledTimes(2)
  expect(api.applyDraft).toHaveBeenCalledTimes(1)
})

it('护栏不通过时批准按钮禁用', async () => {
  const w = mountApproval({ draft: draftWith({ guardrailsPassed: false }) })
  expect(w.get('[data-test=approve]').attributes('disabled')).toBeDefined()
})
```

- [x] **步骤 2：确认失败 → 实现 → 确认通过**

---

### Task 5：库存告警与最小简报视图

**文件：** `src/views/InventoryView.vue`、`src/views/TodayView.vue`

- 库存表展示在库、占用、可售、30 天销量、可售天数、告警类型；
  可售天数为「未知」时显示「未知 / 无近期销量」，**不显示数字**；
- 最小简报展示**数据截至时间**与**生成时间**；来源标注为确定性规则时，
  **界面不得出现"AI 分析"字样**（R7）；
- 简报条目的动作按钮**只把问题填入输入框，不发送、不批准、不执行**（D18④）。

- [x] **步骤 1：写失败测试**——含"动作按钮不触发任何请求"与"确定性来源不显示 AI 字样"。
- [x] **步骤 2：确认失败 → 实现 → 确认通过**

---

### Task 6：v2 Chat 与 SSE 迁移适配

**文件：** `src/api/adapters/chatV2.ts`、`src/api/sse.ts`

v2 事件集（契约计划 §8.7.5）：`step` / `tool_call` / `tool_result` / `turn_complete` / `error`。
**`turn_complete` 取代 v1 的 `done`**，`step` 与 `error` 同名同构。

- 建立**迁移适配层**：v1 `done` 与 v2 `turn_complete` 映射到同一个领域事件，
  **前端只保留一处最终响应解析**（PRD §11.3）；
- `tool_call` / `tool_result` 渲染工具名、状态、耗时、行数，**不渲染任何参数或结果行**；
- 降级按**整轮 vs 单来源**分别展示（契约计划 §8.7.6）：整轮 `degraded=false` 但某来源降级时，
  只在该来源旁标注，不把整条回答标成"已降级"。

- [x] **步骤 1：写失败测试**

```ts
it('v1 done 与 v2 turn_complete 走同一解析函数', () => {
  const spy = vi.spyOn(parser, 'parseFinalResponse')
  feed(v1Stream('done')); feed(v2Stream('turn_complete'))
  expect(spy).toHaveBeenCalledTimes(2)
})

it('单来源降级不把整轮标为降级', () => {
  const vm = toTurnView({ degraded: false, analysis_sources: [
    { source: 'DATABASE', degraded: false }, { source: 'KNOWLEDGE', degraded: true } ] })
  expect(vm.turnDegraded).toBe(false)
  expect(vm.sources.find((s) => s.source === 'KNOWLEDGE')?.degraded).toBe(true)
})
```

- [x] **步骤 2：确认失败 → 实现 → 确认通过**

---

### Task 7：S3 浏览器 E2E

**文件：** `frontend/e2e/s3-inventory-loop.spec.ts`

沿用 `frontend/scripts/e2e-process.mjs` 的子进程管理（**不退回 Playwright 自带的
`webServer`**——`docs/project-progress.md` 记录过原因）。后端使用本地 Fake LLM。

```text
打开今日页 → 简报出现低库存条目 → 在对话里让 Agent 起草补货
→ 进入审批页核对 diff → 批准 → 库存页可售恢复
→ 切到顾客端公开接口断言档位恢复为 IN_STOCK
```

- [x] **步骤 1：编排 E2E**（2026-09-23 全部落地，见 `e2e/s3/s3-inventory-loop.spec.ts`、
      `npm run test:e2e:s3`。末步经 `n2-trade-closed-loop` Task 1 的公开商品接口断言：起点
      `LOW_STOCK`、聊天「批准」后仍 `LOW_STOCK`、审批应用后 `IN_STOCK`，且响应里没有库存数量字段。
      对话一步由测试进程调真实 `POST /api/v2/merchant/chat` 并用生产
      `readMerchantChatStream` 解析，原因是 Vue 端尚无 v2 对话界面，详见执行台账）
- [x] **步骤 2：补一条反例**——在对话里输入"批准那个补货"，断言草稿仍为暂存

---

### Task 8：自检

```powershell
cd frontend
npm run codegen:check
npm run lint
npm run typecheck
npm run test
npm run secrets:check
npm run test:e2e
```

- `typecheck` 错误数**不得多于基线的 7 个**；
- `secrets:check` 必须通过——会话 ID 与证据不得进构建产物；

```powershell
rg -n "localStorage|sessionStorage" src/ --glob '!*.spec.ts'
```

逐条确认命中处只存非敏感商家标识。

更新 `docs/project-progress.md`：S3 浏览器 E2E 状态、typecheck 错误数、未执行 Git。

---

## 本计划明确不做的事

| 不做 | 归属 |
| --- | --- |
| 下线 v1 页面与 Bearer 直连 | v2 全面切换且契约测试通过后，另行评审 |
| 经营洞察、售后、顾客信号、记忆页面 | N3 / N4 对应计划 |
| MCP 凭证管理界面 | **不做**（PRD A8，2026-09-21 用户裁定：凭证只经后端命令行脚本签发与撤销） |
| 顾客端 | `n2-shop-nextjs-app` |
