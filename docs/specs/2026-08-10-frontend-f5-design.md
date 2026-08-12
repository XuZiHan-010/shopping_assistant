# 前端 F5 设计说明：质量轨迹、反馈与无障碍基础

**日期**：2026-08-10（2026-08-10 第一轮评审后修订）
**阶段**：F5（`docs/frontend-development-plan.md` §F5）
**分支**：`feature/integrate-b7-f4`
**后端依赖**：B5（`quality_status`/`quality_attempts`/`quality_notes`/`analysis_sources`）、B6（`POST /api/answers/{answer_id}/feedback`），均已交付并集成到本分支

---

## 一、范围

本阶段交付三件事，**不改动任何后端代码**：

1. **质量轨迹展示**：把 B5 已经返回、但前端一直没消费的 `quality_status`/`quality_attempts`/`quality_notes`/`analysis_sources` 如实呈现在助手消息里。
2. **反馈交互**：采纳、点赞、点踩，接入 B6 的反馈端点，含乐观更新与失败处理。
3. **无障碍基础收口**：F0–F4 已完成绝大部分，本阶段主要是**用测试钉住**既有行为，并补新增 UI 的无障碍属性。

### 明确不做（YAGNI）

- 不新建 `QualityTrace.vue` 独立组件（`AGENTS.md` §7.4 原有此规划，本阶段按参考实现改为嵌入 `ChatMessage.vue`，需同步修订该表）。
- 不做反馈撤销（§2.3）。
- 不改后端、不改 OpenAPI、不重新生成 `generated.ts`/fixture。

---

## 二、关键决策与根因

本节记录的是**为什么**。以下四条都经过代码核实，理由必须留档，否则后续很容易被误读成疏漏而"顺手修好"，反而引入数据损坏或 R9 违规。

### 2.1 反馈只对本次会话内的实时轮次开放

**结论**：只有 `message.answer?.id` 存在时才渲染反馈按钮组。历史会话回填的消息**完全不显示**这组按钮（不是显示后禁用）。

**根因**：反馈端点要的是 `answer_id`，而**当前的会话详情查询与 API 载荷不提供它**：

- `backend/app/api/routes/chat.py::get_conversation` 只查 `messages` 表，装配 `ConversationMessage(id=message.id, ...)`——这个 `id` 是 `Message` 表主键，**不是** `Answer.id`；
- `ConversationDetailResponse` 的消息项没有任何 `answer_id` 字段。

按 `Message.id` 提交反馈，后端会按 `answer_id` 查不到对应回答，返回 404。

**这不是数据库层面的缺失**：`answers` 表有 `conversation_id`、`user_message_id` 和完整的 `response_payload`，数据完全可以关联，Phase B Task 8 本就计划从 `response_payload` 装配历史回答载荷。真正缺的是**查询与契约**——Task 8 扩载荷时顺带补 `answer_id` 即可，不需要迁移。

### 2.2 绝不在"旧状态未知"时提交完整状态

**结论**：反馈状态只在同一次会话生命周期内跟踪。Store 全程掌握真实状态，绝不会在不知道服务端已有状态的前提下发起覆盖式更新。

**根因**：`backend/app/services/feedback_service.py` 是**整条覆盖写入**，不读旧值合并：

```python
is_adopted=payload.is_adopted,
reaction=payload.reaction.value if payload.reaction else None,
```

于是"前端不知道旧状态"与"提交完整状态"两者不能安全共存。假设某条历史回答服务端已是"采纳 + 点赞"，前端刷新后状态为空：

- 用户点"点踩" → 提交 `{is_adopted: false, reaction: 'DISLIKE'}` → **意外撤销了采纳**；
- 用户点"采纳" → 提交 `{is_adopted: true, reaction: null}` → **意外清除了点赞**。

§2.1 的限制恰好同时消解了这个风险：反馈只对实时轮次开放，而实时轮次的反馈状态从 `undefined` 起步、全程由 Store 累积，每次提交时"当前完整状态"都是已知且准确的。

**这不是巧合，是同一个约束的两个面**：没有 `answer_id` 的消息，其反馈状态也必然是未知的。两者一起放开或一起收紧，不能只放开一半。

**后续修复路径**（Phase B Task 8）：该任务扩会话详情载荷时，**必须同时**补 `answer_id` 与当前反馈状态。若只补 `answer_id` 而不补反馈状态，上述覆盖问题会立刻真实发生；那种情况下必须先把后端改成意图式合并（`is_adopted` 只允许 false→true，`reaction` 只在 LIKE/DISLIKE 间替换，未提供的字段不动）。这条约束需写进 Task 8 的契约与验收项（见 §10 切片 8）。

### 2.3 反馈是单向的，不支持撤销

**结论**：采纳一旦点亮不可取消；点赞/点踩可互相切换，但同一个再点一次不清空。

**根因**：与参考实现 `yshopping-merchant-ai 4/.../App.vue::nextFeedbackStatus` 一致（`if (payload.adopted) next.adopted = true`，只置位不清位）。PRD 与 §F5 验收项均未要求可撤销。按 R9，与参考实现一致的行为不需要额外理由。

### 2.4 提交失败时保留本地状态，不回滚

**结论**：请求失败时**保留**按钮选中态，另显示错误提示；「已记录」徽标只在服务端确认成功后出现。

**根因**：参考实现 `App.vue::handleFeedback` 的 catch 分支明写「保留本地反馈状态，网络恢复后用户仍可继续使用当前会话」，并且用独立的 `persisted` 标志承载「服务端确认」这一事实：

```js
const result = await sendFeedback(payload.id, payload)
if (message) message.feedbackStatus.persisted = Boolean(result.persisted || message.feedbackStatus.persisted)
```

这套设计是自洽的：**按钮选中态表达「用户的意图」，徽标表达「服务端的事实」**，两者分开，失败时既不丢用户的点击，也不谎称已保存。

**与我们自己文档的冲突及处置**：`docs/frontend-development-plan.md` §5.2 原写「乐观更新失败时回滚」，与参考实现正面冲突。按 R9（参考项目是需求基准，冲突时改我们的文档），用户于 2026-08-10 裁定**跟随参考实现**，该条验收项需同步改写（见 §10 切片 8）。

**我们的后端没有 `persisted` 字段**（`FeedbackResponse` 只有 `answer_id`/`is_adopted`/`reaction`），因此以「HTTP 200 成功返回」作为确认信号，在前端用 `feedbackPersisted` 布尔承载。跟随参考的**粘性**语义：一旦为 true 就不再置回 false——它表达的是「这条回答的反馈曾被服务端记录过」，不是「当前这一次成功了」。

---

## 三、数据模型

### 3.1 `ChatMessage` 的 id 语义修正

现状：`ChatMessage.id` 语义含混——实时路径写入 `Answer.id`（`stores/chat.ts:119`），历史路径写入 `Message.id`（`stores/chat.ts:261`）。**两处都在写，且是不同的 UUID 空间**，共用一个字段名正是 §2.1 那个 404 的直接来源。

改法（不引入新的重复真相源）：

```ts
export interface ChatMessage {
  localId: string
  /** 后端 `Message.id`，仅历史路径写入，用于历史消息的身份标识。 */
  messageId?: string
  // ...其余不变；不新增 answerId
}
```

**反馈一律使用 `message.answer?.id`**，不再单独存一份 `answerId`：

- `answer.id` 已是权威来源（`toChatAnswer` 从 `ChatResponse.id` 装配），再存一份就要额外维护同步不变量和对应测试；
- 历史消息本就没有 `answer` 对象（`loadConversation` 的映射不产出该字段），"没有 `answer` 就没有反馈按钮"因此自然成立，无需额外判断。

### 3.2 反馈相关类型

```ts
/** 直接引用生成类型，不复制枚举字面量——后端改了这里会在 typecheck 阶段报错。 */
export type FeedbackReaction = components['schemas']['FeedbackReaction'] // 'LIKE' | 'DISLIKE'

/** 某条回答的完整反馈状态。与后端 `FeedbackResponse` 一一对应。 */
export interface FeedbackState {
  isAdopted: boolean
  reaction: FeedbackReaction | null
}

/**
 * 用户的单次点击意图，不是完整状态。
 * 用判别联合而非可选字段对象，调用方无法表达"撤销"这种本设计不支持的语义。
 */
export type FeedbackIntent = { type: 'ADOPT' } | { type: 'REACT'; reaction: FeedbackReaction }
```

`ChatMessage` 新增四个字段：

| 字段 | 类型 | 语义 |
| --- | --- | --- |
| `feedback` | `FeedbackState \| undefined` | 本地反馈状态（用户意图）。`undefined` = 本次会话内尚未反馈过。 |
| `feedbackPersisted` | `boolean \| undefined` | 服务端已确认。**粘性**，一旦 true 不再置回（§2.4）。「已记录」徽标只看它。 |
| `feedbackPending` | `boolean \| undefined` | 有反馈请求在途。Store 与按钮各自检查，不只靠 UI 禁用。 |
| `feedbackError` | `AppError \| undefined` | 上次反馈失败的归一化错误。存 `AppError` 而非字符串，与 `ChatMessage.error` 同款——文案由 `describeError` 在展示处生成。 |

`QualityTrace` 类型已经齐全，本阶段只是开始消费它，不改类型。

---

## 四、API 与 Adapter 层

字段转换必须收进 Adapter——这是项目既定的唯一转换路径（前端方案 §5.0、§11，以及 `AGENTS.md` §7.5「每个 Adapter 配契约测试」），`api/chat.ts` 不得自行拼 snake_case 字段。

`frontend/src/api/adapters/chat.ts` 新增两个函数，与既有 `toQuality`/`toExport` 同款风格：

```ts
/** 领域模型 → 请求载荷。 */
export function toFeedbackRequestPayload(
  state: FeedbackState,
): components['schemas']['FeedbackRequest']

/** 响应载荷 → 领域模型。 */
export function toFeedbackState(
  raw: components['schemas']['FeedbackResponse'],
): FeedbackState
```

`frontend/src/api/chat.ts` 新增：

```ts
export async function submitFeedback(
  answerId: string,
  state: FeedbackState,
  signal: AbortSignal,
): Promise<FeedbackState>
```

内部走既有 `resolveTransport()`，`auth: 'merchant'`，`POST /api/answers/${answerId}/feedback`，请求体与响应解析都调上面两个转换函数。错误沿用现有机制（transport 层已负责把 HTTP 错误转成 `AppError`）。

**注意**：请求体发的是**完整状态**（`is_adopted` 与 `reaction` 都发），因为后端是覆盖写入。这只在调用方确实掌握完整状态时才安全——§2.1/§2.2 的限制正是为此存在。

---

## 五、Store 层

### 5.1 `sendFeedback` 流程

```ts
async function sendFeedback(localId: string, intent: FeedbackIntent): Promise<void>
```

1. **定位与守卫**：找到消息；`role !== 'assistant'`、缺 `message.answer?.id`、或 `feedbackPending` 为真 → 直接返回。Store 自己兜底，不依赖按钮禁用（按钮禁用只是体验，不是正确性保证）。
2. **合并出下一个完整状态**：以 `message.feedback ?? { isAdopted: false, reaction: null }` 为基准，按 §2.3 的单向语义应用 `intent`——`ADOPT` 置 `isAdopted = true`；`REACT` 把 `reaction` 换成新值。
3. **no-op 短路（含失败重试例外）**：若 `next` 与当前 `feedback` 相等 **且 `feedbackError` 为空**，直接返回，不发请求。`feedbackError` 非空时必须放行——见 §5.2。
4. **乐观写入**：`message.feedback = next`；`message.feedbackPending = true`；`message.feedbackError = undefined`（清掉上次失败的残留，否则新请求进行中还挂着旧错误提示）。**不动 `feedbackPersisted`**。
5. **发起请求**：复用既有 `beginTrackedRequest(\`feedback:${localId}\`)`。命名 key 让 `reset()`（切换商家、打开历史会话）能中止在途的反馈请求，避免响应比 reset 晚到、把状态写回一个已经不存在的消息上。
6. **收尾**：
   - 成功 → 用服务端返回值覆盖确认 `message.feedback`；`message.feedbackPersisted = true`；
   - 失败 → **保留** `message.feedback`（§2.4，不回滚）；`message.feedbackError = toAppError(raw)`；`feedbackPersisted` 保持原值；
   - `CANCELLED` 错误静默处理（与 `loadConversation` 既有做法一致，取消不是用户可感知的错误），且不写 `feedbackError`；
   - 三种情况都清 `feedbackPending`、调 `endTrackedRequest`。

### 5.2 最易出错处：失败后无法重试

第 3 步的 no-op 短路与第 6 步的"失败不回滚"**会互相作用产生一个隐蔽 bug**：

失败后 `message.feedback` 保留着用户想要的状态。用户看到错误提示，很自然会**再点同一个按钮重试**——此时第 2 步算出的 `next` 与当前 `feedback` 完全相等，若 no-op 短路不加例外，就会直接返回，表现为「点了没反应」，且用户没有任何其他途径能重发这次反馈。

因此 no-op 短路必须带 `&& !message.feedbackError` 的例外。这条要有独立测试：**失败后再点同一按钮，断言 API 被再次调用**。

这是本阶段最容易写错、且最难被弱测试发现的一处——只测"同值点两次不发请求"会让这个 bug 完美通过。因此该行为要做**变异验证**：实现完成后，临时删掉 `&& !message.feedbackError`，对应测试必须真实失败；确认后还原并用 `git diff` 核对无残留。

本项目已有两次"测试写了但测不出回归"的先例（B4 跨商家隔离用例曾用两个空集合互相比较、B4 商品明细时间窗），这一步不省。

### 5.3 失败后再改其他按钮

失败后 `message.feedback` 保留未确认状态；用户若接着点**另一个**按钮，第 2 步会以这份未确认状态为基准合并，因此重发的请求**自然包含之前那次失败的改动**。这与参考实现行为一致，是期望结果，不是缺陷。需有测试覆盖，避免后续有人"修复"成以服务端最后确认值为基准。

---

## 六、组件层

### 6.1 位置

全部嵌入 `frontend/src/components/chat/ChatMessage.vue`，与参考实现版式一致，也与 `docs/yshopping-parity-audit.md` 登记的位置一致：

```
┌──────────────────────────────┐
│ [执行完成] 思考步骤           │  ← 已有（Phase B Task 8 会补历史态）
│ ────────────────────────     │
│ ✓ 前后比对通过  经过 2 次校验 │  ← 新增：质量轨迹
│   ▸ 查看校验记录              │
│   [经营数据] [知识库]         │  ← 新增：来源徽标（中文）
│ ────────────────────────     │
│ ⚠ 演示数据 ...                │  ← 已有：降级强提示
│ 正文……                        │
│ ────────────────────────     │
│ [已记录] [采纳] [👍] [👎]     │  ← 新增：反馈操作
└──────────────────────────────┘
```

### 6.2 质量轨迹块

只要 `message.answer` 存在就渲染，**`NOT_RUN` 也如实显示**，不隐藏。隐藏"未执行校验"会让未经校验的回答看起来和通过校验的一样可信，与 AGENTS R7 一贯的如实展示要求相悖。

**历史消息不渲染质量轨迹**：`loadConversation` 装配历史消息时不产出 `answer` 对象（后端会话详情本就不返回质量载荷），因此条件自然不成立。这与 §2.1 的反馈按钮限制是同一个后端缺口的两种表现，同归 Phase B Task 8——届时会话详情补上载荷后，两处**无需改动组件逻辑**即可自动生效。

状态文案（穷尽 `QualityStatus`，用 `Record<QualityStatus, string>` 保证后端新增状态时 typecheck 报错）：

| `quality_status` | 文案 |
| --- | --- |
| `PASSED` | 前后比对通过 |
| `DEGRADED` | 校验未通过，已使用稳定兜底 |
| `FAILED` | 前后比对未通过 |
| `NOT_RUN` | 未执行校验 |

**尝试次数**：`attempts > 0` 即显示"经过 N 次校验"（`attempts === 1` 也显示）。§F5 验收项要求"展示 Reviewer 尝试次数"，参考实现同样是非零即显示；只在 `> 1` 时显示会漏掉 1 次校验的情形。**不出现 `RETRIED` 状态**——"重试后通过"渲染为 `PASSED` + "经过 2 次校验"。

**来源徽标**：按数组顺序全部展示，不去重不排序。文案用穷尽映射转中文（R1 要求面向用户内容使用中文，直接渲染 `DATABASE`/`NONE` 等原始枚举违反该规则）：

| `AnalysisSource` | 文案 |
| --- | --- |
| `DATABASE` | 经营数据 |
| `KNOWLEDGE` | 知识库 |
| `ATTACHMENT` | 附件 |
| `MEMORY` | 商家记忆 |
| `FALLBACK` | 兜底回答 |
| `NONE` | 无外部来源 |

同一张映射表也用于修正既有的 `degradeNotice`——它当前直接把 `quality.sources` 顿号拼接输出（会显示 "FALLBACK"），是存量 R1 问题，本阶段顺带修掉。

`notes` 非空时用原生 `<details><summary>查看校验记录</summary>`，天然可键盘访问。

**与既有降级提示的关系**：`degradeNotice`（黄色强提示条）保留，两者不合并。质量轨迹负责"如实记录执行轨迹"，降级提示负责"这条数据不可全信"的强提醒，受众与紧迫度不同。§F5 验收项"降级回答清晰可见，不只在 tooltip 里"由既有的 `degradeNotice` 满足。

### 6.3 反馈按钮组

- 渲染条件：`message.answer?.id` 存在。历史消息因此完全不渲染（§2.1）。
- 三个按钮：采纳（点亮后文案变"已采纳"）、点赞、点踩。选中态由 `message.feedback` 决定（用户意图）。
- **状态徽标三态**（§2.4，徽标表达服务端事实，不是本地状态）：
  - `feedbackPending` → "保存中"；
  - 否则 `feedbackPersisted` → "已记录"；
  - 否则不显示徽标。

  **不得**用 `feedback !== undefined` 作为"已记录"的条件——那会在请求在途时谎报已保存。
- `feedbackPending` 时三个按钮 `disabled`。
- `feedbackError` 时在按钮下方一行内联提示，文案取 `describeError(error).title`，容器 `aria-live="polite"`；此时按钮**保持选中态**且可再次点击重试（§5.2）。
- 事件线：`ChatMessage` emit `feedback: [localId, intent]` → `ConversationColumn` 模板里 `@feedback="chatStore.sendFeedback"` 直连，与既有 `@cancel`/`@select` 同款，不加包装函数。

---

## 七、无障碍

### 7.1 实测基线：F0–F4 已完成绝大部分

对 `frontend/src/components/`、`frontend/src/views/` 实测（2026-08-10），§F5 第 5.3 节的 P0 清单现状：

| §5.3 要求 | 现状 | 证据 |
| --- | --- | --- |
| 图标按钮有 `aria-label` | ✅ 已有 | `ConversationDrawer` 5 处、`AssistantView` 4 处、`ChatMessage` 4 处、`ChatComposer` 3 处等 |
| 错误与加载状态用 `aria-live` | ✅ 已有 | `ChatMessage` 3 处（运行中/取消/错误）、`ConversationColumn` 1 处（重试提示） |
| 对话新增内容可被辅助技术感知 | ✅ 已有 | 同上，`role="status"` + `aria-live="polite"` |
| 表格有表头 | ✅ 已有 | `DetailTable.vue:64`、`MetricChartPanel.vue:82-83`，均为 `<th scope="col">` |
| 图表有文本摘要 | ✅ 已有 | `MetricChartPanel` 的 `chart-summary` + `<details>` 可访问数据表，已有测试覆盖 |
| 模态框管理焦点 | ✅ 已有 | `ConversationDrawer` 打开时移入焦点；`AssistantView::closeDrawer` 归还焦点给触发器 |
| 颜色对比 + 颜色非唯一编码 | ✅ 已有 | `AssistantView` 样式中有明确的对比度决策记录（弃用 `--color-text-muted`，因其在本页背景上仅约 2.8–3.0:1） |
| 键盘关闭目录和弹窗 | ✅ 已有 | `ConversationDrawer.vue:74` `@keydown.esc`；`MerchantSwitcher.vue:29` 文档级 Escape 监听 |

**结论**：无障碍不是本阶段的实现工作，而是**验证与固化**工作。这个事实要如实写进进度文档，不能把 F0–F4 已交付的成果重新计入 F5 的工作量。

### 7.2 本阶段的无障碍增量

只针对新增 UI：

- 质量轨迹块：`role="group"` + `aria-label="质量校验轨迹"`；折叠用原生 `<details>`。
- 反馈按钮组：`role="group"` + `aria-label="回答反馈"`；三个按钮各有 `aria-label`（"采纳本轮回答"/"给本轮回答点赞"/"给本轮回答点踩"），用 `aria-pressed` 反映选中态；徽标与错误提示容器 `aria-live="polite"`。
- 来源徽标：颜色不是唯一编码——每个徽标都带中文可读文本（§6.2）。

补测试钉住 §7.1 中尚无测试覆盖的既有行为（避免后续重构悄悄回退），但不改这些组件的实现。

---

## 八、测试策略

### `api/adapters/chat.spec.ts`（Adapter 契约测试，`AGENTS.md` §7.5 强制）

- `toFeedbackRequestPayload`：camelCase → snake_case 字段名正确；`reaction: null` 如实输出 `null`，不被省略或转成 `undefined`；
- `toFeedbackState`：snake_case → camelCase；`reaction: null` 正确映射；
- 两个方向往返一致（round-trip）。

### `api/chat.spec.ts`（API 层）

- 路径为 `/api/answers/{answerId}/feedback`、方法 `POST`、`auth: 'merchant'`；
- 请求体是**完整状态**（`is_adopted` 与 `reaction` 同时存在）；
- 后端错误如实传播为 `AppError`，不被吞掉。

### `components/chat/ChatMessage.spec.ts`

- 四种 `quality_status` 各自的文案；
- `attempts === 0` 不显示次数、`=== 1` 显示"经过 1 次校验"、`=== 2` 显示"经过 2 次校验"；且**不出现** `RETRIED` 字样；
- `analysisSources` 全部展示、顺序与数组一致、**显示中文**且不出现原始枚举字面量；
- `notes` 非空时可展开，为空时不渲染折叠块；
- `NOT_RUN` 不被隐藏；
- **`message.answer?.id` 缺失时不渲染反馈按钮组**（§2.1 的 UI 侧防线）；
- 三个按钮点击各自 emit 正确的 `FeedbackIntent`；
- `feedbackPending` 时三者禁用且徽标显示"保存中"；
- **`feedback` 已设置但 `feedbackPersisted` 为假时，不显示"已记录"**（§2.4 的核心防线）；
- `feedbackPersisted` 为真时显示"已记录"。

### `stores/chat.spec.ts`

- `ADOPT` 后再 `REACT`，`isAdopted` 保持 true（钉住 §2.2 的覆盖问题）；
- `REACT` 在 LIKE/DISLIKE 间切换；
- 同值再点一次为 no-op，**断言 API 未被再次调用**；
- **失败后再点同一按钮，断言 API 被再次调用**（§5.2 的变异验证目标）；
- 失败时**不回滚** `feedback`、不置 `feedbackPersisted`、记录 `feedbackError`（§2.4）；
- 失败后改点另一个按钮，重发请求包含之前失败的改动（§5.3）；
- 成功后 `feedbackPersisted` 为真，且后续失败不把它置回假（粘性语义）；
- 请求前清掉旧 `feedbackError`；
- 缺 `message.answer?.id` 时不发请求；
- `feedbackPending` 为真时重入被拒；
- `reset()` 中止在途反馈请求。

### Playwright（Mock）

新增一条**键盘全流程**场景，覆盖 §F5 验收项"键盘可完成提问 → 阅读回答 → 反馈全流程"：仅用键盘提问、Tab 到反馈按钮、Enter 触发采纳、断言徽标出现。不能只靠"跑现有 Mock Playwright 通过"充数。

### 门禁

前端全量：`lint`、`format:check`、`codegen:check`、`fixtures:check`、`mock:check`、`typecheck`、`test`、`build`，加 Mock Playwright。

基线（阶段 A 实测）：Vitest **206 passed**、Mock Playwright **24 passed**，只能升不能降。

因不动后端、不改 OpenAPI，`codegen:check`/`fixtures:check` 应当**零漂移**——若报漂移，说明误改了不该改的文件，是有效告警。后端测试与真实库 E2E 本阶段不需要重跑。

---

## 九、已知边界

以下三项是本阶段有意留下的边界，需同步登记进 `docs/yshopping-parity-audit.md`：

1. **历史会话既不显示反馈按钮、也不显示质量轨迹**，根因是会话详情查询与 API 载荷不返回助手回答载荷（§2.1、§6.2）。修复归 Phase B Task 8，且**必须连带**处理 §2.2 记录的覆盖风险。
2. **反馈状态不跨会话保留**。同一条回答在本次会话内的状态准确；重新打开该会话后按钮不再出现（因 §2.1），因此不存在"状态显示错误"的窗口。
3. **反馈不可撤销**（§2.3），与参考实现一致。

---

## 十、实施切片

| # | 内容 | 备注 |
| --- | --- | --- |
| 1 | `ChatMessage.id` → `messageId`；确认两处写入点（`stores/chat.ts:119`、`:261`）改造正确 | 反馈改用 `message.answer?.id`，不新增字段 |
| 2 | 类型定义 + Adapter 双向转换 + **Adapter 契约测试** | |
| 3 | `api/chat.ts::submitFeedback` + **API 层测试** | |
| 4 | Store 的 `sendFeedback` | **最高风险切片**，含 §5.2 的变异验证 |
| 5 | 质量轨迹块（含状态/来源两张中文映射表，顺带修 `degradeNotice` 的存量 R1 问题） | |
| 6 | 反馈按钮组 + 三态徽标 + 事件线 | |
| 7 | 无障碍验证与补测 + 键盘 Playwright 场景 | 以固化既有行为为主（§7.1） |
| 8 | 文档同步 | 见下表 |

### 切片 8 的文档同步范围

| 文件 | 改什么 |
| --- | --- |
| `docs/frontend-development-plan.md` §5.2 | 「乐观更新失败时回滚」→ 按 §2.4 改为「失败时保留本地状态并提示；已记录徽标以服务端确认为准」（R9 裁定，2026-08-10） |
| `docs/frontend-development-plan.md` §F5 | 勾选已完成验收项 |
| `AGENTS.md` §7.4 | `QualityTrace.vue` 那行改为「质量轨迹与反馈嵌入 `ChatMessage.vue`，不独立成组件」 |
| `plans/2026-08-09-b7-f4-integration-and-r9-remediation.md` Task 7 Step 4 / Task 8 | 会话详情契约补 `answer_id` 与当前反馈状态，并写明 §2.2 的覆盖风险约束 |
| `docs/yshopping-parity-audit.md` | 质检块与反馈操作改为已实现；登记 §9 三条边界 |
| `docs/project-progress.md` | F5 阶段快照与实测通过数 |

每片先写失败测试再实现，逐片跑定向测试，最后跑全量门禁。
