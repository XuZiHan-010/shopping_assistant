# 前端 F5：质量轨迹、反馈与无障碍基础实施计划

**状态：已执行完成（2026-08-11）**

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 按 `docs/specs/2026-08-10-frontend-f5-design.md` 完成质量轨迹、实时回答反馈与 P0 无障碍基础，并保持历史会话和后端契约边界不变。

**Architecture:** 反馈契约只在 Adapter 层转换，API 层封装请求，Pinia Store 维护乐观状态与请求生命周期，`ChatMessage.vue` 只负责展示和发出用户意图。质量轨迹和反馈都嵌入单条助手消息；历史消息因缺少完整回答载荷而不开放这些能力。

**Tech Stack:** Vue 3、TypeScript、Pinia、Vitest、Vue Test Utils、Playwright、Lucide Vue Next。

## Global Constraints

- 面向用户的文案全部使用中文；原始 `QualityStatus`、`AnalysisSource` 枚举不得直接出现在 UI。
- 不修改 `backend/`、OpenAPI、`frontend/src/api/generated.ts` 或生成 fixture。
- 不修改只读目录 `yshopping-merchant-ai 4/`；只将其作为行为基准。
- 反馈仅对 `message.answer?.id` 存在的实时回答开放；不得把 `Message.id` 当作 `Answer.id`。
- 采纳只允许置为 true；点赞与点踩可互换；同值点击成功后为 no-op，失败后同值点击必须重试。
- 反馈失败保留本地选择，不显示“已记录”；`feedbackPersisted` 一旦为 true 不再回退。
- 每个生产行为先写失败测试并确认失败原因，再写最小实现。
- 不执行 `git commit`、`git push`、`git tag` 或 PR 操作；每个任务结束只检查 diff 和测试。

---

### Task 1: 修正消息 ID 语义并定义反馈领域类型

**Files:**
- Modify: `frontend/src/types/chat.ts`
- Modify: `frontend/src/stores/chat.ts`
- Test: `frontend/src/stores/chat.spec.ts`

**Interfaces:**
- Produces: `FeedbackReaction`、`FeedbackState`、`FeedbackIntent`；`ChatMessage.messageId`、`feedback`、`feedbackPersisted`、`feedbackPending`、`feedbackError`。
- Invariant: 实时回答 ID 只保存在 `message.answer.id`；历史消息的后端消息 ID 只保存在 `message.messageId`。

- [x] **Step 1: 写消息 ID 语义的失败测试**

  在 `stores/chat.spec.ts` 增加两个断言：实时助手消息不再有含混的 `id` 字段，且 `answer.id` 存在；加载历史会话后每条消息的 `messageId` 等于会话详情中的消息 ID，历史助手消息没有 `answer`。

- [x] **Step 2: 运行测试并确认因 `messageId` 尚不存在而失败**

  Run: `npm run test -- src/stores/chat.spec.ts`

- [x] **Step 3: 写最小类型与映射实现**

  在 `types/chat.ts` 引用生成类型并增加：

  ```ts
  export type FeedbackReaction = components['schemas']['FeedbackReaction']

  export interface FeedbackState {
    isAdopted: boolean
    reaction: FeedbackReaction | null
  }

  export type FeedbackIntent =
    | { type: 'ADOPT' }
    | { type: 'REACT'; reaction: FeedbackReaction }
  ```

  将 `ChatMessage.id?: string` 改为 `messageId?: string`，并加入设计规格中的四个反馈字段。删除 `runRound()` 中的 `assistant.id = answer.id`，将历史映射的 `id: item.id` 改为 `messageId: item.id`。

- [x] **Step 4: 运行定向测试与类型检查**

  Run: `npm run test -- src/stores/chat.spec.ts && npm run typecheck`

- [x] **Step 5: 检查本任务 diff**

  Run: `git diff -- frontend/src/types/chat.ts frontend/src/stores/chat.ts frontend/src/stores/chat.spec.ts`

---

### Task 2: 实现反馈 Adapter 与 API 封装

**Files:**
- Modify: `frontend/src/api/adapters/chat.ts`
- Modify: `frontend/src/api/adapters/chat.spec.ts`
- Modify: `frontend/src/api/chat.ts`
- Modify: `frontend/src/api/chat.spec.ts`

**Interfaces:**
- Consumes: `FeedbackState`。
- Produces: `toFeedbackRequestPayload(state)`、`toFeedbackState(raw)`、`submitFeedback(answerId, state, signal)`。

- [x] **Step 1: 写 Adapter 失败测试**

  覆盖 `{ isAdopted: true, reaction: null }` → `{ is_adopted: true, reaction: null }`、响应反向映射，以及 LIKE/DISLIKE 往返一致。断言 `reaction: null` 是存在的字段而非 `undefined`。

- [x] **Step 2: 运行并确认导出函数缺失导致失败**

  Run: `npm run test -- src/api/adapters/chat.spec.ts`

- [x] **Step 3: 实现两个纯转换函数**

  ```ts
  export function toFeedbackRequestPayload(
    state: FeedbackState,
  ): components['schemas']['FeedbackRequest'] {
    return { is_adopted: state.isAdopted, reaction: state.reaction }
  }

  export function toFeedbackState(
    raw: components['schemas']['FeedbackResponse'],
  ): FeedbackState {
    return { isAdopted: raw.is_adopted, reaction: raw.reaction }
  }
  ```

- [x] **Step 4: 写 API 层失败测试**

  用捕获 `TransportRequest` 的测试传输断言路径 `/api/answers/answer-1/feedback`、`POST`、`auth: 'merchant'`、完整请求体；响应需经 Adapter 转成领域对象。另让传输抛 `AppError`，断言 `submitFeedback` 原样拒绝。

- [x] **Step 5: 运行并确认 `submitFeedback` 尚未导出而失败**

  Run: `npm run test -- src/api/chat.spec.ts`

- [x] **Step 6: 实现 API 封装**

  ```ts
  export async function submitFeedback(
    answerId: string,
    state: FeedbackState,
    signal: AbortSignal,
  ): Promise<FeedbackState> {
    const transport = await resolveTransport()
    const response = await transport(
      {
        path: `/api/answers/${answerId}/feedback`,
        method: 'POST',
        auth: 'merchant',
        body: toFeedbackRequestPayload(state),
      },
      signal,
    )
    return toFeedbackState(
      (await response.json()) as components['schemas']['FeedbackResponse'],
    )
  }
  ```

- [x] **Step 7: 运行两个测试文件与类型检查**

  Run: `npm run test -- src/api/adapters/chat.spec.ts src/api/chat.spec.ts && npm run typecheck`

---

### Task 3: 用 Pinia Store 管理反馈状态与并发

**Files:**
- Modify: `frontend/src/stores/chat.ts`
- Modify: `frontend/src/stores/chat.spec.ts`

**Interfaces:**
- Consumes: `submitFeedback`、`FeedbackIntent`。
- Produces: `sendFeedback(localId: string, intent: FeedbackIntent): Promise<void>`。

- [x] **Step 1: 写反馈状态机失败测试**

  在独立 `describe('回答反馈')` 中覆盖：ADOPT 后 REACT 保留采纳；LIKE/DISLIKE 互换；成功后同值再次点击不请求；缺 `answer.id` 与 `feedbackPending` 时不请求。

- [x] **Step 2: 写失败、重试与取消的失败测试**

  覆盖：失败保留本地状态且 `feedbackPersisted` 不为真；同一按钮失败后可重试；失败后点另一按钮会带上先前未确认改动；成功后 persisted 为粘性；请求前清旧错误；`reset()` 会 abort 在途反馈且不留下错误。

- [x] **Step 3: 运行并确认 `sendFeedback` 缺失导致失败**

  Run: `npm run test -- src/stores/chat.spec.ts`

- [x] **Step 4: 实现最小状态机**

  引入 `submitFeedback` 与 `FeedbackIntent`，按下列核心判据实现：

  ```ts
  const current = message.feedback ?? { isAdopted: false, reaction: null }
  const next =
    intent.type === 'ADOPT'
      ? { ...current, isAdopted: true }
      : { ...current, reaction: intent.reaction }

  const unchanged =
    message.feedback?.isAdopted === next.isAdopted &&
    message.feedback?.reaction === next.reaction
  if (unchanged && !message.feedbackError) return
  ```

  请求 key 固定为 ``feedback:${localId}``；成功覆盖服务端状态并置 `feedbackPersisted = true`；非取消失败只写 `feedbackError`；finally 只在消息仍存在时清 pending，并用 `endTrackedRequest` 收尾。将 `sendFeedback` 加到 Store 返回值。

- [x] **Step 5: 运行定向测试并完成变异验证**

  Run: `npm run test -- src/stores/chat.spec.ts`

  临时移除 `&& !message.feedbackError`，只运行“失败后再点同一按钮”用例并确认失败；立即还原，再运行同一用例确认通过。用 `git diff` 确认无临时变异残留。

- [x] **Step 6: 检查 Store 定向回归**

  Run: `npm run test -- src/stores/chat.spec.ts src/components/chat/ConversationColumn.spec.ts`

---

### Task 4: 渲染完整质量轨迹并中文化来源

**Files:**
- Modify: `frontend/src/components/chat/ChatMessage.vue`
- Modify: `frontend/src/components/chat/ChatMessage.spec.ts`

**Interfaces:**
- Consumes: `message.answer.quality`。
- Produces: `role="group" aria-label="质量校验轨迹"` 的质量块、状态与来源穷尽映射。

- [x] **Step 1: 写质量轨迹失败测试**

  表驱动覆盖 PASSED、DEGRADED、FAILED、NOT_RUN；覆盖 attempts 0/1/2、notes 有无、来源顺序和中文文案，并断言 DOM 不出现 `RETRIED`、`DATABASE`、`FALLBACK` 等原始枚举。

- [x] **Step 2: 运行并确认质量轨迹尚未渲染而失败**

  Run: `npm run test -- src/components/chat/ChatMessage.spec.ts`

- [x] **Step 3: 实现穷尽映射和质量块**

  ```ts
  const QUALITY_LABELS: Record<QualityStatus, string> = {
    PASSED: '前后比对通过',
    DEGRADED: '校验未通过，已使用稳定兜底',
    FAILED: '前后比对未通过',
    NOT_RUN: '未执行校验',
  }

  const SOURCE_LABELS: Record<AnalysisSource, string> = {
    DATABASE: '经营数据',
    KNOWLEDGE: '知识库',
    ATTACHMENT: '附件',
    MEMORY: '商家记忆',
    FALLBACK: '兜底回答',
    NONE: '无外部来源',
  }
  ```

  在正文前渲染质量块；notes 用原生 `details/summary`；来源按原数组顺序全部输出。`degradeNotice.sources` 复用 `SOURCE_LABELS`，修掉原始枚举直出。

- [x] **Step 4: 运行组件测试和类型检查**

  Run: `npm run test -- src/components/chat/ChatMessage.spec.ts && npm run typecheck`

---

### Task 5: 添加反馈按钮、三态徽标与组件事件线

**Files:**
- Modify: `frontend/src/components/chat/ChatMessage.vue`
- Modify: `frontend/src/components/chat/ChatMessage.spec.ts`
- Modify: `frontend/src/components/chat/ConversationColumn.vue`
- Modify: `frontend/src/components/chat/ConversationColumn.spec.ts`

**Interfaces:**
- Consumes: `ChatMessage.feedback*`、`FeedbackIntent`、`chatStore.sendFeedback`。
- Produces: `ChatMessage` 的 `feedback` emit；三枚可访问按钮与保存状态。

- [x] **Step 1: 写反馈 UI 失败测试**

  覆盖：无 `answer.id` 不渲染组；三个按钮分别 emit ADOPT/LIKE/DISLIKE；`aria-pressed` 与选中态一致；pending 时全禁用并显示“保存中”；本地 feedback 未确认不显示“已记录”；persisted 后显示“已记录”；错误提示可见且按钮保持选中。

- [x] **Step 2: 运行并确认反馈组尚不存在而失败**

  Run: `npm run test -- src/components/chat/ChatMessage.spec.ts`

- [x] **Step 3: 实现反馈 UI**

  在 `defineEmits` 增加 `feedback: [localId: string, intent: FeedbackIntent]`。用 Lucide 图标和可见中文文案渲染采纳、点赞、点踩；组使用 `role="group"`、`aria-label="回答反馈"`，按钮使用设计规格中的 `aria-label` 和 `aria-pressed`。状态与错误容器使用 `aria-live="polite"`。

- [x] **Step 4: 写事件线失败测试并连接 Store**

  在 `ConversationColumn.spec.ts` 从子组件 emit `feedback`，断言最终状态或请求被触发。随后在模板增加：

  ```vue
  @feedback="chatStore.sendFeedback"
  ```

- [x] **Step 5: 运行组件链路回归**

  Run: `npm run test -- src/components/chat/ChatMessage.spec.ts src/components/chat/ConversationColumn.spec.ts src/stores/chat.spec.ts`

---

### Task 6: 固化无障碍基线并增加键盘全流程

**Files:**
- Modify: `frontend/src/components/chat/ChatMessage.spec.ts`
- Modify: `frontend/src/components/chat/ConversationColumn.spec.ts`
- Modify: `frontend/e2e/conversation.spec.ts`

**Interfaces:**
- Produces: P0 无障碍回归测试与“提问 → 阅读回答 → 反馈”键盘 E2E。

- [x] **Step 1: 补单元级无障碍断言**

  断言质量组、反馈组、三个图标按钮、`aria-pressed`、`aria-live`、原生 details，以及既有可键盘选中轮次的 button 语义。

- [x] **Step 2: 运行单元测试并修复仅由新增 UI 引入的问题**

  Run: `npm run test -- src/components/chat/ChatMessage.spec.ts src/components/chat/ConversationColumn.spec.ts`

- [x] **Step 3: 写键盘 E2E**

  仅用键盘聚焦输入框、输入问题、提交；等待回答完成；连续 Tab 到“采纳本轮回答”，按 Enter；断言按钮 `aria-pressed="true"` 且“已记录”出现。不得用鼠标 click 绕过键盘路径。

- [x] **Step 4: 运行单条 Playwright 并确认通过**

  Run: `npm run test:e2e -- --grep "键盘.*反馈"`

---

### Task 7: 同步权威文档并执行 F5 全量验收

**Files:**
- Modify: `docs/frontend-development-plan.md`
- Modify: `AGENTS.md`
- Modify: `plans/2026-08-09-b7-f4-integration-and-r9-remediation.md`
- Modify: `docs/yshopping-parity-audit.md`
- Modify: `docs/project-progress.md`

**Interfaces:**
- Consumes: 前六项的实际实现与 fresh verification 输出。
- Produces: 与参考行为、当前代码和 F5 完成状态一致的文档快照。

- [x] **Step 1: 先运行前端全量门禁**

  Run: `npm run lint`

  Run: `npm run format:check`

  Run: `npm run codegen:check`

  Run: `npm run fixtures:check`

  Run: `npm run mock:check`

  Run: `npm run typecheck`

  Run: `npm run test`

  Run: `npm run build`

  Run: `npm run test:e2e`

- [x] **Step 2: 按实测结果同步文档**

  将前端方案的“失败回滚”改为“失败保留本地状态并提示，已记录以服务端确认为准”；勾选实际通过的 F5 项。更新 `AGENTS.md` 组件索引、Phase B Task 8 契约约束、还原度审计边界和项目进度快照。不得先写“已完成”再补验证。

- [x] **Step 3: 运行文档卫生和最终前端门禁**

  Run: `rg -n "乐观更新失败时回滚|QualityTrace.vue|FALLBACK" docs/frontend-development-plan.md AGENTS.md frontend/src/components/chat/ChatMessage.vue`

  Run: `npm run lint && npm run format:check && npm run typecheck && npm run test && npm run build`

- [x] **Step 4: 检查最终范围**

  Run: `git status --short`

  Run: `git diff --stat`

  确认没有 `backend/`、`frontend/src/api/generated.ts`、fixture 或只读参考目录改动；保留用户在 `docs/specs/2026-08-10-frontend-f5-design.md` 中已有的未提交修订。
