# N1 v2 字段契约冻结实施计划

> **给执行者：** 本计划用 `superpowers:executing-plans` 逐任务推进。步骤用 `- [ ]` 复选框跟踪。
> **本计划不含任何 Git 提交步骤**——`AGENTS.md` R2 要求逐次授权，未授权时做完实现与验证直接汇报。

**目标：** 为 `docs/PRD.md` §11.2 的全部 47 条 v2 路径写出请求、响应、错误、幂等与 SSE 字段契约，
解除 `docs/backend-development-plan.md` §8.0.1 对 v2 路由实现的封锁。

**架构：** 先冻结全局共用组件（错误信封、会话头、幂等键、分页、SSE 事件、降级字段），
再按七组路径逐组补写 §8 章节与对应 Pydantic Schema 模块。每组的 Schema 是**无路由的纯模型**，
由 Schema 单测验证必填/可空/枚举/校验器行为；v2 路由与其 OpenAPI、前端类型同步不在本计划范围。
例外：Task 1 共享 ErrorCode 改变既有 v1 契约，须同步现有 OpenAPI、生成类型与错误处理映射。

**技术栈：** Markdown（`docs/backend-development-plan.md` §8）、Python 3.12 + Pydantic v2、pytest、Ruff、mypy。

**规格来源：**
- `docs/PRD.md` §7（状态机不变量）、§10（非功能）、§11（路径清单与传输契约）、§15（N1 里程碑）
- `docs/backend-development-plan.md` §8.0–§8.6（v1 既有契约体例与门槛）
- `docs/specs/2026-09-18-anthropic-fusion-decisions.md`（D 系列裁定）

---

## 全局约束

- **面向开发者的新增内容一律中文**（R1）；枚举值、字段名、标识符一律英文 snake_case。
- **不执行 `git commit` / `git push` / `git tag` / PR 操作**（R2）。每个任务以验证命令收尾，不以提交收尾。
- **不调用真实 LLM**（R3）。本计划全程只写文档与 Pydantic 模型，不触发任何模型调用。
- **字段命名沿用 v1 的结构约定**：单一扁平 snake_case，不引入 `reviewer.*` / `metric.*` 类嵌套对象。
- **`session_id` 与 `conversation_id` 是两个不同的东西，v2 必须分开**（见 §8.7.7）。
  v1 用 `session_id` 表示业务对话的语义**不带入 v2**：v2 的 `session_id` 只指认证会话。
- **金额**：数据库保持 `Decimal`（`Numeric(14, 2)`，单位元），**API 边界转换为整数分**；
  禁止在任何环节使用 `float`（见 §8.7.8）。
- **`merchant_id` 与 `buyer_key` 永不出现在任何 v2 请求体、查询参数或请求头中**（R5、PRD §7.5 不变量 2）。
  它们只由服务端从会话解析。任何契约表里出现这两个字段的请求侧定义，即为契约错误。
- **禁止在本计划内创建 FastAPI 路由、前端请求封装或修改 `frontend/src/api/generated.ts`**（§8.0.1）。
- **只读目录零交集**：不修改 `yshopping-merchant-ai 4/`、`yshopping-prototype/`、`vendor/`、
  `docs/history/`、2026-08 及更早的 `docs/specs/`（R8）。
- 时间字段一律 UTC ISO 8601；金额字段名一律以 `_cents` 结尾，契约表必须写明单位。

---

## 文件结构

| 文件 | 责任 | 操作 |
| --- | --- | --- |
| `docs/backend-development-plan.md` §8.7 | v2 共用契约组件（信封、会话、幂等、分页、SSE、降级、命名、金额、操作证据） | 新增章节 |
| `docs/backend-development-plan.md` §8.8–§8.14 | 七组路径的字段契约，每组一节 | 新增章节 |
| `docs/backend-development-plan.md` §8.0.1 | 门槛描述改为七组，登记 OpenAPI 时序与每组完成门槛 | 修改 |
| `docs/backend-development-plan.md` §14 | 登记本轮新增的 14 个错误码 | 修改 |
| `backend/app/core/errors.py:23` | 扩充 `ErrorCode` 枚举（**不新建枚举**） | 修改 |
| `backend/app/localization/error_messages.py` | 新错误码的中英文文案 | 修改 |
| `backend/tests/api/test_errors.py` | 错误码哨兵测试同步 | 修改 |
| `backend/app/core/session.py` | `SessionRole` 的唯一领域定义；后续身份计划在同一文件补充上下文与凭证原语 | 新建 |
| `backend/app/schemas/v2/__init__.py` | v2 Schema 包导出 | 新建 |
| `backend/app/schemas/v2/common.py` | 共用枚举、分页、错误、SSE 事件、降级混入 | 新建 |
| `backend/app/schemas/v2/shop_session.py` | 顾客会话与店铺公开浏览 | 新建 |
| `backend/app/schemas/v2/merchant_session.py` | 商家会话与商家对话目录 | 新建 |
| `backend/app/schemas/v2/trade.py` | 购物车、订单、履约事件 | 新建 |
| `backend/app/schemas/v2/after_sales.py` | 双端售后 | 新建 |
| `backend/app/schemas/v2/merchant_ops.py` | 当日简报、库存告警、顾客信号 | 新建 |
| `backend/app/schemas/v2/drafts.py` | 草稿审批与变更账本 | 新建 |
| `backend/app/schemas/v2/memory.py` | 双端记忆、反馈、MCP 入口 | 新建 |
| `backend/tests/unit/schemas/v2/test_*.py` | 每个模块一份 Schema 单测 | 新建 |
| `plans/2026-09-16-agent-business-loop-upgrade.md` | 头部加状态标注 | 修改 |
| `plans/2026-09-17-agent-business-loop-decisions.md` | 头部加状态标注 | 修改 |
| `docs/project-progress.md` | §四下一步与本轮验证 | 修改 |

**为什么 Schema 按业务域拆包而不按路径前缀拆**：售后同时被 `/shop/*` 和 `/merchant/*` 使用，
状态机是同一套（PRD §7.2）；按前缀拆会把同一个状态枚举复制两份，是典型的漂移来源。

**“字段契约已冻结”的判定标准：** §8.8–§8.14 中每条 `METHOD + PATH` 必须各自给出
鉴权头、路径/查询/请求体字段、响应字段、HTTP 状态、错误码、幂等语义，以及适用时的分页或 SSE 事件；
每个字段必须写明类型、必填性、可空性、范围/长度、单位、枚举和条件必填规则。
不得用“包含相关字段”“同 Task N”“按现有结构”等简写把设计决定留给执行者。
对应 Pydantic 模型与测试应逐字段映射这张表；表未完整时只能标记“契约设计中”，不能创建 Schema。

---

## 契约裁定（2026-09-20 用户已批准）

五项方向均已批准，但其中 A1、A2、A4、A5 附带了必须一并落实的修正；A4 与 A5 的**原始依据经核实有误**，
已在下表更正。执行时以本表的「依据与边界」列为准。

| # | 裁定 | 依据与边界 |
| --- | --- | --- |
| A1 | **批准**复用 v1 `ErrorResponse`。错误码**必须扩充 `app.core.errors.ErrorCode` 这一唯一枚举，不得另建 `V2ErrorCode`** | `backend/app/core/errors.py:23` 的 docstring 已明确「这是后端实际会发出的错误码的唯一出处——不要在别处直写字符串字面量」，且要求每个成员同时登记在后端计划 §14。另建枚举直接违反既有代码自己的契约 |
| A2 | **批准**请求体字段 `client_request_id`，不增加请求头。但**适用范围是白名单，不是「全部 v2 POST」** | `AGENTS.md` §十一的 CORS 允许头清单没有 `Idempotency-Key`。会话签发、MCP JSON-RPC 等端点不适用，须在 §8.7.3 逐条列出 |
| A3 | **批准**事件集 `step / tool_call / tool_result / turn_complete / error`，最终事件只能是 `turn_complete` 或 `error` | PRD §11.3 |
| A4 | **批准** v2 全量游标分页，不提供 offset | **原依据有误**：v1 会话列表实际是 `limit + offset`（`backend/app/schemas/chat.py:304`），只有会话详情的消息用游标（`next_message_cursor`，同文件 347 行）。因此这是**新约定而非沿用**，契约须额外定清排序键、tie-breaker、绑定、失效与重试语义 |
| A5 | **批准** API 边界使用整数分 | **原依据有误**：数据库实际是 `_MONEY = Numeric(14, 2)` 的 `Decimal` 元（`backend/app/models/analytics.py:32`，`OrderItem.item_amount` 等同此），**不存在既有整数分约定**。因此这是边界转换约定，须在契约中写明转换与舍入规则 |

以下是本计划为落实 PRD 而作出的**实现级设计选择**，不冒充 A1–A5 的用户原话：

- v2 继续暴露 `answer_mode`，但顾客端与商家端使用不同闭集枚举；这是 N1 字段契约选择，
  不是从 v1 自动继承；
- 顾客访客会话绑定演示身份时保留原高熵会话凭证，原地完成一次性绑定与购物车合并；
  这是对 PRD §7.5「访客会话 → 绑定」状态机的直接实现，可保证响应丢失后的幂等重试，
  不引入保存或重放明文新凭证的额外机制；
- `SessionRole` 的唯一事实源位于 `app.core.session`。API Schema 只能导入，不能再定义同名枚举。

### 执行期裁定（2026-09-21，执行者在用户授权下作出，可被用户推翻）

Task 3–8 写契约时，计划文字没有覆盖下列问题；执行者做了裁定，并已按 PRD → 契约 → 计划 → 索引的顺序同步。
这些**不是用户原话**，用户后续若有不同意见，按同一顺序改回。

| # | 问题 | 裁定 | 同步位置 |
| --- | --- | --- | --- |
| E1 | PRD §7.2 没有客服工单（`TICKET`）的结案路径，状态机无法走到终态 | 增加「待商家处理 → 已同意（即已处理）→ 关闭」，只限工单；退货退款、仅退款走该跳一律 `409` | PRD §7.2；契约 §8.11.2；`after_sales.py`；N3 售后计划 Task 4、Task 8 |
| E2 | 支付状态 `CLOSED` 没有对应事件，无法「由事件派生」；数据迁移计划 M3 已有「已关闭」事件而 PRD 没有 | PRD §7.1、C5 补入「已关闭」事件，契约事件类型 `ORDER_CLOSED` | PRD；契约 §8.10.2 |
| E3 | v2 反馈要区分「采纳」与「赞踩」且互不覆盖；N2 反馈计划用的字段与契约不一致 | 请求用 `kind: ADOPTION \| REACTION` 区分，响应返回两者当前完整状态；沿用 v1 `FeedbackReaction`（`LIKE` / `DISLIKE`） | 契约 §8.14；N2 反馈计划 Task 2 |
| E4 | N2 库存计划与 Vue 计划引入了契约没有的 `days_of_supply_note` | 删除：`days_of_supply = null` 已表示「未知 / 无近期销量」，契约 `extra="forbid"` 不接受额外字段 | N2 草稿与库存计划、N2 Vue 迁移计划 |
| E5 | 审批证据的绑定范围在 N2 草稿计划里少了 `target_version`、主体与勾选条目 | 以契约 §8.13 为准：`session_record_id + merchant_id + draft_id + draft_version + target_version`，请求摘要含 `accepted_entry_ids` | N2 草稿与库存计划 |
| E6 | N2 交易计划 Task 5 要求订单详情「同时返回事件数组」，与契约「详情不内嵌无界事件数组」冲突；支付/关闭胜者写哪种履约事件也未写明 | 以契约为准：详情只返回三维投影与价格快照，事件只走 `/events` 游标分页；支付写 `PAYMENT_CONFIRMED`，关闭写 `ORDER_CLOSED` | N2 交易计划 Task 5、竞争裁决表 |
| E7 | 其余设计选择（计划没规定） | 购物车 `DELETE` 返回 `200` + 完整购物车；草稿 apply 增加可选 `accepted_entry_ids` 以支持商品内容批量勾选（PRD M4）；关闭记忆确认字段为 `purge_confirmation: "yes"`（与 N4 计划一致）；当日简报尚未生成时 `GET` 返回 `404 NOT_FOUND`；MCP 白名单不含 `regenerate_brief`、`create_export`、`list_signals` | 契约 §8.10、§8.12–§8.14 |
| E8 | PRD S2、D11④ 要求「内容缺口信号」，契约 `CustomerSignalKind` 只有三种售后类信号，`SignalSourceRef` 只能指向售后 | 2026-09-21 补入 `CONTENT_GAP`；来源加 `PRODUCT`（必带 `content_version`）；内容缺口信号恰好一条来源且等于所指商品；售后类信号只接受 `AFTER_SALE` 来源；任何信号不指向顾客对话 | 契约 §8.12.1–§8.12.2；`merchant_ops.py`；`n3-merchant-skills` Task 7 |
| E9 | 访客购物车合并规则与调整可见性 PRD 未写 | 2026-09-21 用户裁定：同商品相加、单行上限 99、剔除不可售、超 50 行保留最新、合并后清空访客购物车；绑定响应加 `cart_adjusted: bool` | PRD C3；契约 §8.8.1；`shop_session.py`；`n2-trade-closed-loop` Task 2；`n2-shop-nextjs-app` |
| E10 | `CursorPage` 未约束 `has_more` 与 `next_cursor` 一致，可能出现 `has_more=true` 却无游标 | 2026-09-21 模块 A 审查补入：`has_more` 必须等于 `next_cursor` 非空；`next_cursor` 非空时 1–2048 字符 | 契约 §8.7；`common.py` |
| E11 | 契约 §8.8.1 写「图片主机白名单经 Pydantic context 注入」，实现改为服务层 `is_trusted_image_host`，契约未同步 | 以实现为准并回写契约：`response_model` 校验不传 context，按原写法外部图片会在响应阶段 500 | 契约 §8.8.1；`shop_session.py` |
| E12 | 复审发现图片白名单辅助函数只核对主机名，购物车图片也未复用商品图片规则 | 2026-09-22 修复：商品与购物车共用 `ImageUrl` 结构校验；白名单辅助函数先验证结构，再判定主机 | 契约 §8.8.1、§8.10.1；`shop_session.py`、`trade.py` 与反例测试 |
| E13 | 售后详情契约要求事件按时间与 ID 升序，Schema 只验证状态链 | 2026-09-22 修复：详情模型拒绝时间或同时间 ID 倒序 | 契约 §8.11.1；`after_sales.py` 与反例测试 |
| E14 | 售后详情最多 100 条事件，但补充信息往返此前无限制 | 2026-09-22 按最长结案链限定同一售后事项最多 47 次补充请求；第 48 次在写事件前返回 `409 ILLEGAL_STATE_TRANSITION`，详情模型与 N3 状态机共用计数判断 | PRD §7.2；契约 §8.11.2；`after_sales.py`；N3 售后计划 Task 4、Task 8 |

**尚未裁定、留给 N3 入口条件核对的一项**：「已退款 → 关闭」「已拒绝 → 关闭」由谁触发（系统自动或商家草稿）。
契约允许这两跳并把事件 `actor` 留了 `SYSTEM` 值，但 PRD 没有写触发方，本计划不替 N3 决定。

---

## §8.0.1 六组划分的缺口（本计划已修正）

`docs/backend-development-plan.md` §8.0.1 把 v2 契约工作描述为「顾客会话、商家会话、交易/售后、
草稿审批、记忆与 MCP 六组」。按 PRD §11.2 逐条比对，这六组**漏掉 5 条商家端只读路径**：

```text
GET  /api/v2/merchant/briefs/daily/current
POST /api/v2/merchant/briefs/daily/current/regenerate
GET  /api/v2/merchant/inventory/alerts
GET  /api/v2/merchant/customer-signals
POST /api/v2/merchant/customer-signals/{signal_id}/ignore
```

本计划按**七组**切分，第七组即「商家经营只读面」。Task 1 会同步修正 §8.0.1 的表述。

### 七组与 47 条路径的对应

| 组 | §8 章节 | 路径数 | Schema 模块 |
| --- | --- | --- | --- |
| 1 · 顾客会话与店铺浏览 | §8.8 | 11 | `shop_session.py` |
| 2 · 商家会话与对话目录 | §8.9 | 6 | `merchant_session.py` |
| 3 · 交易：购物车与订单履约 | §8.10 | 9 | `trade.py` |
| 4 · 售后（双端） | §8.11 | 5 | `after_sales.py` |
| 5 · 商家经营只读面 | §8.12 | 5 | `merchant_ops.py` |
| 6 · 草稿审批与变更账本 | §8.13 | 4 | `drafts.py` |
| 7 · 记忆、反馈与 MCP | §8.14 | 7 | `memory.py` |
| | | **47** | |

---

## 任务依赖顺序

```text
Task 0（悬空计划处置，无依赖，可随时做）

Task 1（共用组件 + ErrorCode 扩充）── 所有后续任务都消费它
   ├── Task 2（组 1 顾客会话与店铺浏览）
   │      └── Task 4（组 3 交易）── 依赖 Task 2 的来源闸门与店铺商品定义
   │             └── Task 5（组 4 售后）── 依赖 Task 4 的订单与价格快照
   ├── Task 3（组 2 商家会话与对话目录）
   ├── Task 6（组 5 商家经营只读面）
   ├── Task 7（组 6 草稿审批）
   └── Task 8（组 7 记忆/反馈/MCP）

Task 9（全量自检与进度同步）── 依赖 Task 1–8
```

**Task 1 完成后可并行的是 Task 2、3、6、7、8；Task 4 等 Task 2，Task 5 再等 Task 4。**

硬顺序链：`Task 1 → Task 2 → Task 4 → Task 5`。

早先「Task 2/3/6/7/8 全部可并行」的说法不成立，已更正：Task 3 原本要消费 Task 2 的
`V2ChatResponse`，但两端 `answer_mode` 枚举不同；现已把共享字段下沉为
`common.V2ChatResponseBase`（§8.7.7），Task 3 因此不再依赖 Task 2。
Task 6 的精确库存字段只服务商家端，不再复用顾客侧库存档位，因此可与 Task 2、3、7、8 并行。

---

### Task 0：处置两份悬空计划

`plans/2026-09-16-agent-business-loop-upgrade.md` 与 `plans/2026-09-17-agent-business-loop-decisions.md`
写于 2026-09-20 新 PRD 之前，配套决策页四项 Q1–Q4 全部标注「待裁定」。其中 Q1（R9 的 1:1 基准是否
放宽）与 Q4（B7 九题验收是否作为前置门槛）的**前提已被新 PRD 与 AGENTS.md 取消**，不再需要裁定；
Q2（记忆召回边界）与 Q3（LLM 预算上限）仍然有效，但属于 N3/N4 范围，不阻塞 N1。

**文件：**
- 修改：`plans/2026-09-16-agent-business-loop-upgrade.md`（文件头部）
- 修改：`plans/2026-09-17-agent-business-loop-decisions.md`（文件头部）
- 修改：`docs/project-navigation.md`（计划索引节）

- [x] **步骤 1：给主计划加状态标注**

在 `plans/2026-09-16-agent-business-loop-upgrade.md` 的一级标题之后、`> **执行说明：**` 之前插入：

```markdown
> **状态（2026-09-20 登记）：** 本计划写于新 PRD 之前，**未实施**。其中「现有能力整改」部分
> （记忆污染、反馈衡量、证据传递）仍然有效，已并入 `docs/project-progress.md` §三的验证缺口清单；
> 「建议新增能力」部分的范围判定已由 `docs/PRD.md` §15 N1–N5 接管，不再由本计划定义需求。
> 当前阶段的主计划是 `plans/2026-09-20-n1-v2-contract-freeze.md`。
```

- [x] **步骤 2：给决策页加状态标注**

把 `plans/2026-09-17-agent-business-loop-decisions.md` 的 `**日期：**` 行整行替换为：

```markdown
**日期：** 2026-09-17　**状态（2026-09-20 更新）：** Q1 与 Q4 **已失效**——R9 的 1:1 基准含义已由
2026-09-20 的 `AGENTS.md` 取消，B7 九题验收已由 `docs/project-progress.md` §四第 8 条移出前置门槛，
两项均无需再裁定。Q2（记忆召回边界）与 Q3（LLM 预算上限）**仍待裁定**，顺延到 N3/N4，不阻塞 N1。
```

- [x] **步骤 3：同步导航索引**

在 `docs/project-navigation.md` 的计划索引节中，为这两份计划各补一句「已登记状态，不定义当前范围」，
并新增一行指向 `plans/2026-09-20-n1-v2-contract-freeze.md` 作为当前主计划。

- [x] **步骤 4：验证**

```powershell
rg -n "待裁定" plans/2026-09-17-agent-business-loop-decisions.md
```

期望：仅 Q2、Q3 两行命中；Q1、Q4 行不再含「待裁定」。

> `openspec/changes/add-question-prefilter-gate/` 的归档属于独立治理动作，不是 N1 契约冻结的前置条件，
> 不在本计划内顺带执行；如需归档，应另行使用 OpenSpec 归档流程并独立验证 delta spec 已同步。

```powershell
git diff --check
```

期望：无输出。

---

### Task 1：v2 共用契约组件

> **执行状态（2026-09-21）：Task 1 自查整改完成。** 共用 Schema 测试 43 passed；包含错误码、
> OpenAPI 哨兵的专项回归 107 passed；后端 unit 1068 passed，Ruff 与 mypy 通过。
> 已同步共享 ErrorCode 的生成产物与前端双语展示、运行时白名单；详细命令和验证限制见进度快照。

> **2026-09-21 自查整改：** 用户已要求直接修复。因唯一 `ErrorCode` 被既有 v1 路由引用，
> 本 Task 1 允许同步其造成的 `docs/api.json`、`docs/api.md` 和 `frontend/src/api/generated.ts`
> 枚举变化并跑 OpenAPI / codegen 哨兵；仍不新增 v2 路由、Adapter 或 v2 路径产物。
> §8.7 的工具摘要改为固定双语短句、状态闭集，`FALLBACK` 强制来源与整轮降级，
> 来源 Schema 不宣传 `ATTACHMENT`，幂等键与游标收紧边界，MCP 鉴权明确排除会话头。

这是所有后续任务消费的基础。**六项共用组件一次定清，后续任务只引用不重定义。**

**文件：**
- 修改：`docs/backend-development-plan.md` §8.0.1（六组 → 七组 + OpenAPI 时序 + 每组完成门槛）
- 创建：`docs/backend-development-plan.md` §8.7（在 §8.6 末尾之后、§9 之前插入）
- 修改：`docs/backend-development-plan.md` §14（登记新错误码）
- 修改：`backend/app/core/errors.py`（扩充 `ErrorCode`，**不新建枚举**）
- 修改：`backend/app/localization/error_messages.py` 的 `_MESSAGES`（新码的 zh-CN / en-US 文案）
- 修改：`backend/tests/api/test_errors.py`（哨兵测试）
- 创建：`backend/app/core/session.py`（本任务只放 `SessionRole`；身份计划随后扩展）
- 创建：`backend/app/schemas/v2/__init__.py`
- 创建：`backend/app/schemas/v2/common.py`
- 创建：`backend/tests/unit/schemas/v2/__init__.py`
- 创建：`backend/tests/unit/schemas/v2/test_common.py`

**接口：**
- 消费：`app.core.errors` 的既有 `ErrorResponse` 与 `ErrorCode`（**扩充 `ErrorCode`，不替换、不另建**）
- 产出：`app.core.session.SessionRole`，以及 `CursorPageRequest`、`CursorPage[T]`、
  `SseEventName`、`AnalysisSourceEntry`、`DegradationMixin`、`IdempotentWriteRequest`、`MoneyCents`、
  **`V2ChatResponseBase`**（Task 2 与 Task 3 各自继承，见 §8.7.7）。
  Task 2–8 从 `app.schemas.v2.common` 导入传输组件，从 `app.core.session` 导入 `SessionRole`，
  不在各自模块里重新定义。
- **不产出 `V2ErrorCode`。** 错误码只有 `app.core.errors.ErrorCode` 一个来源。

- [x] **步骤 1：修正 §8.0.1 的分组表述**

把 `docs/backend-development-plan.md` §8.0.1 第二段中的
「按顾客会话、商家会话、交易/售后、草稿审批、记忆与 MCP 六组逐项补齐字段契约」
替换为：

```markdown
按七组逐项补齐字段契约：顾客会话与店铺浏览、商家会话与对话目录、交易（购物车与订单履约）、
售后（双端）、商家经营只读面（当日简报、库存告警、顾客信号）、草稿审批与变更账本、
记忆与反馈与 MCP。七组合计覆盖 PRD §11.2 的全部 47 条路径；原「六组」表述遗漏了
`briefs/daily/current`、`briefs/daily/current/regenerate`、`inventory/alerts`、
`customer-signals`、`customer-signals/{signal_id}/ignore` 五条。
```

并在该节末尾追加一段 OpenAPI 时序说明：

```markdown
**OpenAPI 的生成时点：** 当前路由驱动的 OpenAPI 导出无法包含未被路由引用的 v2 Schema 和路径。
因此契约冻结的交付物是本章的字段定义，加上 `backend/app/schemas/v2/` 的 Pydantic 模型与其单测；
`docs/api.json`、`docs/api.md`、生成类型与 Adapter 在该组路由实现的**同一次变更内**同步。

这不放宽门槛，而是把门槛拆成前后两道。**每组路由的完成门槛必须同时满足**：

1. 本章对应小节的字段契约已写完（路由创建的前置条件）；
2. `uv run python -m scripts.export_openapi` 已重新导出 `docs/api.json` 与 `docs/api.md`；
3. `npm run codegen` 已重新生成 `frontend/src/api/generated.ts`，且 `npm run codegen:check` 通过；
4. 对应 Adapter 与 Adapter 契约测试已更新；
5. OpenAPI 快照/哨兵测试通过（`backend/tests/api/test_openapi_chat_contract.py` 同类）。

五项缺一，该组不得标记完成。
```

- [x] **步骤 2：写 §8.7 共用契约组件**

在 §8.6 末尾之后插入新章节，包含以下**九**小节。字段表体例与 §8.2 一致（字段 / 类型 / 可为 null / 说明）。

**§8.7.1 会话与角色**

```markdown
顾客与商家会话端点使用请求头 `X-Session-Id: <session id>`；公开端点不需要此头，
创建商家会话使用演示 Bearer Token（AGENTS.md §8.3）；
MCP 只接受独立 `Authorization: Bearer <MCP access token>`，不接受会话头。会话记录包含
**不可变角色** `SessionRole = CUSTOMER | MERCHANT`（PRD §7.5 不变量 4）。

| 场景 | 状态码 | `code` |
| --- | --- | --- |
| 缺 `X-Session-Id` | 401 | `SESSION_REQUIRED` |
| 会话不存在、已过期、已注销或已被撤销 | 401 | `SESSION_INVALID` |
| 角色不符（顾客会话调商家端点，或反之） | 403 | `SESSION_ROLE_MISMATCH` |
| 顾客角色正确但仍是访客，端点要求已绑定身份 | 403 | `CUSTOMER_BINDING_REQUIRED` |
| 目标对象不存在，或存在但不属于当前主体 | **403** | `RESOURCE_FORBIDDEN` |

最后一行是**非枚举要求**。**状态码是 403 不是 404**——这是 O1 裁定、D7⑦ 与 `AGENTS.md` R5
的一致要求（"目标不存在与目标不属于当前主体使用相同公开错误结构，不得泄露对象存在性"）。

一致性要求比"同一个状态码"更严，PRD §12.1 要求响应**逐字段一致**：

- 同一 `code`（`RESOURCE_FORBIDDEN`，**不叫** `*_NOT_FOUND`——名字本身不得暗示存在性）；
- 同一段 `message`，且不含对象类型、ID 或任何可区分线索；
- `details` 为**空数组 `[]`**（`ErrorResponse.details` 的类型是 `list[dict[str, Any]]`，不是对象）；
- **响应耗时一致**：不得出现"不存在快、越权慢"的时序差（O1 明确点名"耗时"）。
  实现约束登记见 `plans/2026-09-21-n1-session-identity.md`。

内部日志可以区分两者原因，对外一律不可区分。角色不符与跨主体访问一律写 `audit_logs`。
```

**§8.7.2 错误信封与新增错误码**

沿用 §8.3 的 `ErrorResponse`。**错误码扩充 `app.core.errors.ErrorCode` 这一唯一枚举**——
该文件的 docstring 已规定「这是后端实际会发出的错误码的唯一出处」，新建 `V2ErrorCode`
会直接违反它，并让前端的按码查表出现两张表。本轮新增 14 个成员：

| `code` | HTTP | `retryable` | 触发场景 |
| --- | --- | --- | --- |
| `SESSION_REQUIRED` | 401 | `false` | 缺会话头 |
| `SESSION_INVALID` | 401 | `false` | 会话失效、过期、注销或被撤销 |
| `SESSION_ROLE_MISMATCH` | 403 | `false` | 跨角色访问 |
| `CUSTOMER_BINDING_REQUIRED` | 403 | `false` | 顾客角色正确但当前仍是访客，端点要求已绑定演示顾客 |
| `SESSION_ALREADY_BOUND` | 409 | `false` | 已绑定会话试图切换到另一个服务端顾客身份；同一身份重试幂等成功 |
| `RESOURCE_FORBIDDEN` | **403** | `false` | 不存在或不属于当前主体（非枚举，逐字段一致） |
| `PRODUCT_NOT_IN_SCOPE` | 403 | `false` | 商品不属于本店或未通过来源闸门 |
| `INSUFFICIENT_STOCK` | 409 | `false` | 可售量不足（PRD §7.4 不变量 1） |
| `ILLEGAL_STATE_TRANSITION` | 409 | `false` | 非法状态迁移（PRD §7.1 不变量 2） |
| `VERSION_CONFLICT` | 409 | `false` | 草案版本或目标对象版本不匹配；同一请求盲重试无效，须刷新后重新确认 |
| `DRAFT_EXPIRED` | 409 | `false` | 草稿已过期 |
| `GUARDRAIL_REJECTED` | 422 | `false` | 护栏预检不通过 |
| `CONFIRMATION_REQUIRED` | 422 | `false` | 必须提交证据的写操作缺失证据，或提交的证据无效/过期/已消费；售后首次预检返回 200 challenge，不用此错误 |
| `INVALID_CURSOR` | 422 | `false` | 游标不可解析、已失效或与当前主体/资源不匹配 |

`IDEMPOTENCY_KEY_REUSED`（409）与 `REQUEST_IN_PROGRESS`（409，`retryable=true`）
**已存在于 `ErrorCode`**，v2 直接沿用 §8.5 语义，不重复登记。
`RATE_LIMITED`、`LLM_BUDGET_EXCEEDED`、`DATA_SOURCE_UNAVAILABLE` 同理。

新码的三处同步是硬要求：后端计划 §14 的错误码表、`error_messages.py` 的 `_MESSAGES`
（zh-CN 与 en-US 各一条）、`backend/tests/api/test_errors.py` 的哨兵测试。

**§8.7.3 幂等写契约与适用白名单**

`client_request_id` 长度 1–128，只允许 ASCII 字母、数字、`.`、`_`、`:`、`-`，且首字符必须是字母或数字；
拒绝空白、换行和控制字符。客户端生成 UUID 等稳定请求标识，网络重试复用同一值。

沿用 §8.5 的处理状态与重复提交规则，但 v2 幂等记录必须以
`role + 主体稳定摘要 + merchant_id + 端点操作 + client_request_id` 为唯一域，不能直接复用 v1
`answers(merchant_id, client_request_id)` 的索引；否则不同顾客碰巧使用同一客户端 ID 会互相冲突。
请求摘要只取规范化后的**业务输入**，排除 `confirmation_token` / `approval_evidence` 等短期证据；
同一 ID 改变业务输入仍返回 `409 IDEMPOTENCY_KEY_REUSED`。状态、请求摘要、终态响应与业务写入须由
同一数据库事务或可恢复状态机保证；具体表/索引是对应写路由上线前置，不属于本次 Schema 冻结已实现事项。
承载表是 `idempotency_records`，由数据迁移计划 M8 创建，唯一约束即上述五元组；**业务表上不另设
`(merchant_id, client_request_id)` 之类的窄唯一索引**，否则会重新引入跨顾客误判冲突（2026-09-21 N1 计划审查补全）。
传输仍用**请求体字段 `client_request_id`，不引入新请求头**（裁定 A2）。

适用范围是**白名单，不是「全部 POST」**：

| 携带 `client_request_id` | 不携带 | 不携带的理由 |
| --- | --- | --- |
| `POST /shop/orders` | `POST /shop/sessions` | 会话签发；请求体只含 `shop_slug` |
| `POST /shop/orders/{id}/pay` | `POST /shop/sessions/demo-customer` | 同一服务端身份重复绑定幂等返回；试图切换到不同身份才返回 `409 SESSION_ALREADY_BOUND` |
| `POST /shop/orders/{id}/cancel` | `POST /merchant/sessions` | 会话签发；请求体为空对象 |
| `POST /shop/after-sales` | `POST /merchant/mcp` | MCP 本版只暴露只读工具，不存在写副作用；JSON-RPC `id` 只做请求/响应关联，不承担幂等 |
| `POST /merchant/briefs/daily/current/regenerate` | `PUT /shop/cart/items/{product_id}` | 设置绝对数量而非增量，按资源语义天然幂等 |
| `POST /merchant/customer-signals/{id}/ignore` | `PUT /shop/memory-preference` | 设置绝对状态，天然幂等 |
| `POST /merchant/drafts/{id}/apply` | 全部 `DELETE` 端点 | 天然幂等 |
| `POST /merchant/answers/{id}/feedback` | | |
| `POST /shop/chat` | | |
| `POST /merchant/chat` | | |

白名单之外的端点**不得**声明 `client_request_id`；白名单之内的**必须**声明。

两个 Chat 端点沿用 §8.5 聊天重试幂等（五种状态分支、并发重复提交只产生一次 LLM 调用、断开后凭 ID
取回、预算耗尽/限流为 `FAILED_RETRYABLE` 且重试不调用 LLM）与 §8.6.4 的 locale 重放规则，但：

- 唯一域按本节五元组，承载于 `idempotency_records`；**不复用** v1 `answers(merchant_id, client_request_id)`
  索引，否则同店不同顾客会互相冲突；
- `request_digest` 取规范化后的 `message` 与 `conversation_id`；v2 无附件字段，摘要不含 `attachment_ids`。

（2026-09-21 执行核对补全：原白名单漏列 Chat，与 Task 2 不变量 3 冲突。）
新增 v2 写端点时同步更新本表。

**§8.7.4 游标分页**

v2 列表端点一律游标分页，不提供 offset（裁定 A4）。**这是新约定**：v1 会话列表用的是
`limit + offset`，只有会话详情的消息用游标，两者不构成先例。

请求：`cursor: str | null`（省略表示首页；提供时长度 1–2048）、`limit: int`（1–100，默认 20）。
响应：`items: list[T]`、`next_cursor: str | null`（`null` 表示末页）、`has_more: bool`。

契约必须为每个列表端点定清下列五项，缺一即为契约不完整：

1. **稳定排序键**：主排序字段与方向（默认 `created_at DESC`）。排序键必须在数据库有索引。
2. **tie-breaker**：同分值时的次级排序键，固定用主键 `id` 降序。
   缺 tie-breaker 会让同一时间戳的多条记录在翻页时重复或丢失。
3. **游标绑定**：游标编码里必须包含**主体标识**（会话解析出的 role、`merchant_id` /
   `buyer_key` 摘要）、端点资源类型、`shop_slug`、筛选条件、排序方式与 locale 的规范化摘要。
   公开列表至少绑定 `shop_slug + 资源类型 + 筛选/排序`。跨主体、跨资源或跨查询形状复用游标
   返回 `422 INVALID_CURSOR`，**不返回数据**，并写审计。
4. **签名与失效规则**：游标是不透明的版本化签名字符串，载荷至少含版本、查询绑定摘要、
   最后一条排序键、签发时间与过期时间。服务端用 `EXPORT_SIGNING_SECRET` 派生独立的
   `cursor:v1` HMAC 子密钥，禁止直接复用裸密钥或接受未签名 base64。签名失败、载荷被修改或游标
   超过 24 小时，返回 `422 INVALID_CURSOR`。锚点记录在两页之间被删除**不使游标失效**：keyset
   分页直接按游标携带的排序键继续查询，不为确认锚点存在而追加探测查询。
5. **重试语义**：`INVALID_CURSOR` 的 `retryable=false`——重试同一游标不会成功，
   客户端必须从首页重取。`VERSION_CONFLICT` 同样是 `retryable=false`：它要求先刷新、重新确认，
   不是对原请求自动重试。

**§8.7.5 v2 SSE 事件契约**

`tool_call` / `tool_result` 的 `status` 仅允许 `STARTED | RUNNING | SUCCEEDED | DEGRADED | FAILED | UNAVAILABLE`；
`summary` 仅允许 `正在处理 | 处理完成 | 暂时不可用 | 处理失败` 与对应英语
`Processing | Completed | Unavailable | Failed`。任意工具参数、结果与模型原文不能直接作为摘要。
工具名须匹配 `^[a-z][a-z0-9_]{0,63}$`，调用 ID 须匹配 `^[A-Za-z0-9_-]{1,64}$`；
后端仍须按注册表白名单校验工具名。动态业务摘要以后须先定义受控投影与脱敏反例测试，再扩充闭集。

| 事件 | 载荷 | 与 v1 的关系 |
| --- | --- | --- |
| `step` | `{ label, node }` | **与 v1 同名同构**，迁移适配层直通 |
| `tool_call` | `{ tool_name, call_id, status, summary }` | v2 新增 |
| `tool_result` | `{ call_id, status, duration_ms, row_count, summary }` | v2 新增 |
| `turn_complete` | 完整 `ShopChatResponse` 或 `MerchantChatResponse` | **取代 v1 `done`**，载荷唯一 |
| `error` | 标准 `ErrorResponse` | **与 v1 同名同构** |

线协议（响应头、空行分隔、单行紧凑 JSON、15 秒 `: keep-alive` 心跳、事件名只放 `event:` 字段、
`Accept: application/json` 走非流式、头发送前后的错误语义差异）**完全沿用 §8.4**，本节不重复定义。

`tool_call` / `tool_result` 的 `summary` 只含可公开展示的摘要（PRD §11.3）：
**不得**包含原始参数、SQL、完整结果行、Prompt 全文或任何未脱敏的顾客标识。

流的最后一个事件必须是 `turn_complete` 或 `error` 之一，互斥。

**§8.7.6 降级披露字段**

R7 的六个字段在 v2 保持同名：`analysis_sources`、`thinking_steps`、`quality_status`、
`quality_notes`、`degraded`、`degraded_reason`。v2 新增区分**整轮降级与单来源降级**（PRD §11.3）：
`analysis_sources` 的每个元素从字符串升为对象 `{ source, degraded, degraded_reason }`，
顶层 `degraded` 表示整轮是否降级。**顶层 `degraded=false` 时允许存在单个来源 `degraded=true`。**
`source` 使用现有 `app.schemas.chat.AnalysisSource` 成员构成的 v2 字面值子集，
运行时和 JSON Schema 都拒绝已移出本版的 `ATTACHMENT`；
`NONE` 只能单独出现。单来源 `degraded=true` 时该元素的 `degraded_reason` 必须为非空字符串，
否则必须为 `null`。顶层也遵守同一成对规则：`degraded=true` 必须给出非空原因，`false` 必须为 `null`。
`FALLBACK` 来源自身与整轮都必须标为降级并给出原因，不能作为未降级的模型分析返回。

**§8.7.7 `session_id` 与 `conversation_id` 的命名冻结**

v1 用 `session_id` 表示业务对话（`AGENTS.md` §8.5：「会话标识统一为 `session_id`，
不存在 `conversation_id`」）。v2 同时存在**两个**不同的东西，继续复用一个名字会让
认证凭证和业务对话在契约、日志和前端 Store 里混为一谈：

| 名字 | 含义 | 出现位置 |
| --- | --- | --- |
| `session_id` | **认证会话凭证**：高熵、可过期、可注销、可撤销，带不可变角色 | 会话创建响应体；请求头 `X-Session-Id` 的取值 |
| `conversation_id` | **业务对话标识**：一次会话内可以有多个对话 | Chat 请求与响应；对话目录列表与详情；`DELETE /conversations/{conversation_id}` |

约束：

- **v2 的 Chat 请求体不含 `session_id`**——认证会话只走请求头。续接已有对话传 `conversation_id`，
  为空表示新建对话。
- **v2 的 Chat 响应体不含 `session_id`**，只含 `conversation_id`。
- `session_id` 只出现在 `POST /shop/sessions` 与 `POST /merchant/sessions` 的响应体里。
- **`AGENTS.md` §8.5 的「不存在 `conversation_id`」只约束 v1 契约。** 本节是 v2 的有意分歧，
  §8.7.7 必须写明这一点，避免后来者把它当成不一致去「修正」。v1 路径不受本节影响。

`V2ChatResponseBase` 定义在 `common.py`，含 `id`、`conversation_id`、`answer`、`tool_calls`
与 §8.7.6 的全部降级字段，**但不含 `answer_mode`**——两端枚举不同，由各自模块定义
（`ShopChatResponse` 用 `ShopAnswerMode`，`MerchantChatResponse` 用 `MerchantAnswerMode`）。
这样 Task 2 与 Task 3 都只依赖 Task 1，互不依赖。

**§8.7.8 金额表示与转换**

数据库保持 `Decimal`（`_MONEY = Numeric(14, 2)`，单位**元**）；**API 边界转换为整数分**（裁定 A5）。

- API 字段类型是 `int`，字段名以 `_cents` 结尾，**禁止 `float`**——
  包括禁止在转换过程中经过 `float`（`int(float(d) * 100)` 会引入舍入误差，必须用
  `int(d.quantize(Decimal("0.01")) * 100)`）。
- **折扣与汇总的舍入顺序是契约的一部分**：先按**订单行**各自四舍五入到分，再对行结果求和；
  不得先汇总再舍入。两种顺序在多行折扣下会差几分，而退款上限校验依赖行金额
  （PRD §7.2 不变量 2），顺序不固定就会出现「逐行都合法、合计却超额」。
- 舍入模式固定为 `ROUND_HALF_UP`。
- **安全整数范围**：`Numeric(14, 2)` 的上界是 `999999999999.99` 元，即 `99999999999999` 分
  （约 1.0e14），小于 JavaScript 的 `Number.MAX_SAFE_INTEGER`（约 9.007e15），
  因此整数分可以安全地用 JSON number 传输，不需要字符串编码。契约须写明这条推导，
  以免后来者在没有依据的情况下改成字符串。

**§8.7.9 界面操作证据的通用语义**

`confirmation_token` 与 `approval_evidence` 都是服务端签发的 opaque token，不是前端自行拼接的布尔值：

- 从现有 `EXPORT_SIGNING_SECRET` 分别派生 `customer-confirmation:v1` 与 `draft-approval:v1` HMAC 子密钥，
  禁止直接复用裸密钥；载荷必须含版本、用途、主体/资源/请求绑定、nonce、签发与过期时间；
- 有效期不超过 10 分钟；nonce 必须在数据库中持久化，并与业务写入在**同一事务**中原子消费，
  不能只靠进程内集合，否则多实例或重启后可重放；日志、SSE 与错误详情不得回显 token；
- 处理顺序固定为：先按 `client_request_id` 查幂等结果；命中则原样返回第一次结果；未命中才验证并消费证据。
  因此网络重试不会被误判为重放，而同一证据换一个 `client_request_id` 再用会返回
  `422 CONFIRMATION_REQUIRED`，且不产生第二次业务写入；业务请求摘要排除该短期 token，
  同键重试的摘要比较以业务字段为准；
- 缺失、签名错误、过期、用途/主体/资源/请求不匹配或已消费，对外都使用同一中性错误结构，
  不披露具体失败原因；内部安全审计可记录原因枚举，但不得记录 token 原值。

实现售后创建或草稿应用之前，数据库迁移必须建立按用途/nonce 唯一的操作证据消费表，明确过期清理；
仅有 Pydantic 字段和签名函数不构成“防重放已完成”。该表属于对应业务路由的实现前置，
不把尚未上线的写端点所需表伪装成 N1 契约任务已经落地。

证据必须有契约内可实现的签发来源，不能写成“由界面自行签发”：售后创建采用同一路径两阶段提交——
第一次 `POST /shop/after-sales` 不带 token 时只做确定性预检，不写业务数据，并返回
`200 AfterSaleConfirmationChallenge`（`confirmation_token`、过期时间、供人核对的脱敏摘要）；
该响应必须 `Cache-Control: no-store`，且不得进入 Agent/MCP 工具投影。界面展示摘要并由用户确认后，
用**同一个** `client_request_id` 加 token 重交；
第一次 challenge 响应不登记为终态幂等结果。缺失 token 不返回普通校验错误；无效或已消费 token
才返回 `422 CONFIRMATION_REQUIRED`。草稿则由工作台读取 `GET /merchant/drafts/{draft_id}` 时
取得绑定当前版本的 `approval_evidence` 与过期时间；该 GET 必须 `Cache-Control: no-store`，
重复读取可签发多个短期 nonce，但每个只能消费一次，未消费的过期记录由 Cron 清理。
Agent 工具结果、MCP、SSE、日志和审计元数据均不得
获得或回显这两类证据；后端不能靠 User-Agent、Referer 或前端自报字段判断“来自界面”。

- [x] **步骤 3：扩充 `ErrorCode` 并同步三处登记**

先写失败测试，追加到 `backend/tests/api/test_errors.py`：

```python
V2_NEW_CODES = {
    "SESSION_REQUIRED", "SESSION_INVALID", "SESSION_ROLE_MISMATCH", "CUSTOMER_BINDING_REQUIRED",
    "SESSION_ALREADY_BOUND",
    "RESOURCE_FORBIDDEN", "PRODUCT_NOT_IN_SCOPE", "INSUFFICIENT_STOCK",
    "ILLEGAL_STATE_TRANSITION", "VERSION_CONFLICT", "DRAFT_EXPIRED",
    "GUARDRAIL_REJECTED", "CONFIRMATION_REQUIRED", "INVALID_CURSOR",
}


def test_v2_codes_registered_in_single_enum() -> None:
    from app.core.errors import ErrorCode
    assert V2_NEW_CODES <= {c.value for c in ErrorCode}


def test_every_v2_code_has_both_locales() -> None:
    """新码必须有 zh-CN 与 en-US 文案，不能落到 _FALLBACK。"""
    from app.localization.error_messages import _MESSAGES
    from app.localization.locales import SupportedLocale
    for code in V2_NEW_CODES:
        assert code in _MESSAGES, f"{code} 缺少本地化文案"
        assert set(_MESSAGES[code]) == set(SupportedLocale), f"{code} 语言不全"


def test_every_v2_code_registered_in_section_14() -> None:
    """后端计划 §14 是错误码的人读登记处，errors.py 的 docstring 要求同步。"""
    from pathlib import Path
    doc = Path(__file__).resolve().parents[3] / "docs" / "backend-development-plan.md"
    text = doc.read_text(encoding="utf-8")
    section = text.split("## 14. 后端错误码")[1].split("## 15.")[0]
    for code in V2_NEW_CODES:
        assert code in section, f"{code} 未登记在 §14"
```

确认三条测试失败后，依次改：`backend/app/core/errors.py` 的 `ErrorCode`（**追加成员，
不改动既有成员，不新建枚举**）→ `error_messages.py` 的 `_MESSAGES`（每码两种语言）
→ 后端计划 §14 的错误码表（按 §8.7.2 的表格内容登记）。

再次运行：

```powershell
cd backend; uv run pytest tests/api/test_errors.py -v
```

期望：新增三条全部通过，**既有用例无一回归**。

- [x] **步骤 4：写 `common.py` 的失败测试**

创建 `backend/tests/unit/schemas/v2/test_common.py`：

```python
import pytest
from pydantic import ValidationError

from app.schemas.v2.common import (
    AnalysisSourceEntry,
    CursorPageRequest,
    DegradationMixin,
    IdempotentWriteRequest,
    SseEventName,
    V2ChatResponseBase,
)
from app.core.session import SessionRole


def test_cursor_limit_rejects_out_of_range() -> None:
    with pytest.raises(ValidationError):
        CursorPageRequest(limit=0)
    with pytest.raises(ValidationError):
        CursorPageRequest(limit=101)


def test_cursor_defaults_to_first_page() -> None:
    page = CursorPageRequest()
    assert page.cursor is None
    assert page.limit == 20


def test_idempotent_write_requires_client_request_id() -> None:
    with pytest.raises(ValidationError):
        IdempotentWriteRequest()


def test_idempotent_write_rejects_merchant_id() -> None:
    """R5：请求侧永不接受 merchant_id / buyer_key。"""
    with pytest.raises(ValidationError):
        IdempotentWriteRequest(client_request_id="r1", merchant_id="m1")


def test_turn_level_pass_allows_single_degraded_source() -> None:
    payload = DegradationMixin(
        analysis_sources=[
            AnalysisSourceEntry(source="DATABASE", degraded=False, degraded_reason=None),
            AnalysisSourceEntry(source="KNOWLEDGE", degraded=True, degraded_reason="UPSTREAM"),
        ],
        degraded=False,
        degraded_reason=None,
        quality_status="NOT_RUN",
        quality_attempts=0,
        quality_notes=[],
    )
    assert payload.degraded is False
    assert payload.analysis_sources[1].degraded is True


def test_quality_notes_defaults_to_empty_list_not_none() -> None:
    payload = DegradationMixin(
        analysis_sources=[AnalysisSourceEntry(source="NONE", degraded=False, degraded_reason=None)],
        degraded=False,
        degraded_reason=None,
        quality_status="NOT_RUN",
        quality_attempts=0,
    )
    assert payload.quality_notes == []


def test_degraded_reason_must_match_degraded_flag() -> None:
    with pytest.raises(ValidationError):
        AnalysisSourceEntry(source="DATABASE", degraded=True, degraded_reason=None)
    with pytest.raises(ValidationError):
        DegradationMixin(
            analysis_sources=[
                AnalysisSourceEntry(source="DATABASE", degraded=False, degraded_reason=None)
            ],
            degraded=False,
            degraded_reason="unexpected",
            quality_status="NOT_RUN",
            quality_attempts=0,
        )


def test_none_source_must_be_exclusive() -> None:
    with pytest.raises(ValidationError):
        DegradationMixin(
            analysis_sources=[
                AnalysisSourceEntry(source="NONE", degraded=False, degraded_reason=None),
                AnalysisSourceEntry(source="DATABASE", degraded=False, degraded_reason=None),
            ],
            degraded=False,
            degraded_reason=None,
            quality_status="NOT_RUN",
            quality_attempts=0,
        )


def test_v2_rejects_removed_attachment_source() -> None:
    with pytest.raises(ValidationError):
        AnalysisSourceEntry(source="ATTACHMENT", degraded=False, degraded_reason=None)


def test_sse_event_names_match_contract() -> None:
    assert {e.value for e in SseEventName} == {
        "step",
        "tool_call",
        "tool_result",
        "turn_complete",
        "error",
    }


def test_session_role_is_closed_enum() -> None:
    assert {r.value for r in SessionRole} == {"CUSTOMER", "MERCHANT"}


def test_chat_base_has_conversation_id_not_session_id() -> None:
    """§8.7.7：认证会话与业务对话分名。"""
    fields = V2ChatResponseBase.model_fields
    assert "conversation_id" in fields
    assert "session_id" not in fields


def test_chat_base_leaves_answer_mode_to_subclasses() -> None:
    """两端枚举不同，基类不定义 answer_mode，避免 Task 3 依赖 Task 2。"""
    assert "answer_mode" not in V2ChatResponseBase.model_fields


def test_money_conversion_never_passes_through_float() -> None:
    from decimal import Decimal
    from app.schemas.v2.common import yuan_to_cents
    assert yuan_to_cents(Decimal("1.005")) == 101   # ROUND_HALF_UP
    assert yuan_to_cents(Decimal("0.07")) == 7      # float 路径会得到 6
    assert yuan_to_cents(Decimal("999999999999.99")) == 99999999999999


def test_money_upper_bound_is_js_safe() -> None:
    """Numeric(14,2) 上界换算成分后仍小于 Number.MAX_SAFE_INTEGER。"""
    assert 99999999999999 < 9007199254740991
```

- [x] **步骤 5：确认测试失败**

```powershell
cd backend; uv run pytest tests/unit/schemas/v2/test_common.py -v
```

期望：`ModuleNotFoundError: No module named 'app.schemas.v2'`。

- [x] **步骤 6：实现 `common.py`**

创建 `backend/app/schemas/v2/__init__.py`（空文件即可）与 `backend/app/schemas/v2/common.py`。
要点：

- 先创建 `backend/app/core/session.py`，只定义 `SessionRole(StrEnum)`；这是领域唯一事实源。
  `common.py` 导入它，**不得**再定义同名枚举，也不定义任何错误码枚举；
- `MoneyCents = Annotated[int, Field(ge=0, le=99999999999999)]`，模块顶部注释写明单位是**分**，
  上界取 `Numeric(14, 2)` 的上界换算值（见 §8.7.8）；
- `yuan_to_cents(value: Decimal) -> int` 与 `cents_to_yuan(value: int) -> Decimal`：
  用 `Decimal.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)`，**中途不得出现 `float`**；
- `CursorPageRequest`：`cursor: str | None = Field(default=None, min_length=1, max_length=2048)`、
  `limit: int = Field(default=20, ge=1, le=100)`；
- `CursorPage` 用 `Generic[T]` + `model_config = ConfigDict(extra="forbid")`，
  含 `items`、`next_cursor`、`has_more`；
- `IdempotentWriteRequest`：`client_request_id` 使用 §8.7.3 的长度与字符闭集，
  `model_config = ConfigDict(extra="forbid")`——`extra="forbid"` 是让
  `test_idempotent_write_rejects_merchant_id` 通过的机制，也是 R5 在 Schema 层的强制点；
- `AnalysisSourceEntry`：`source` 为现有 `AnalysisSource` 成员的 v2 字面值子集、
  `degraded: bool`、`degraded_reason: str | None`；运行时与 JSON Schema 均拒绝 `ATTACHMENT`，
  并校验 `degraded` 与原因成对、`FALLBACK` 必须降级；
- `DegradationMixin`：`analysis_sources: list[AnalysisSourceEntry] = Field(min_length=1)`、
  `thinking_steps: list[ThinkingStep] = Field(default_factory=list)`、`quality_status`、
  `quality_attempts: int = Field(ge=0, le=3)`、
  `quality_notes: list[str] = Field(default_factory=list)`、`degraded: bool`、
  `degraded_reason: str | None`。校验 `NONE` 独占、`FALLBACK` 整轮降级以及顶层原因成对；

- `V2ChatResponseBase`：`id`、`conversation_id`、`answer`、`tool_calls`、`created_at`
  加上 `DegradationMixin` 的全部字段；**不含 `answer_mode`，不含 `session_id`**（§8.7.7）。

**全部 v2 请求模型都必须设 `extra="forbid"`。** 默认的 `extra="ignore"` 会让前端误传的
`merchant_id` 被静默丢弃而不是报错——静默丢弃意味着这类越权尝试在测试里不可见。

**但 `extra="forbid"` 只保证校验失败返回 422，它不会产生任何安全审计。**
把「拒绝」等同于「已记录」是错的。因此本计划登记一条**实现期约束**，由后续路由任务承接：

> 在 `RequestValidationError` 的全局处理器（`backend/app/core/errors.py`）中，
> 检测被拒绝的 extra 字段名；命中 `merchant_id`、`buyer_key`、`shop_slug` 等身份/租户类字段时，
> 显式写一条 `audit_logs`，记录会话主体、端点、被拒字段名（**不记录字段值**）。
> 没有这一步，越权尝试只会变成一条普通的 422 访问日志。

- [x] **步骤 7：确认测试通过**

```powershell
cd backend; uv run pytest tests/unit/schemas/v2/test_common.py -v
```

期望：以上 15 个测试函数全部通过。

- [x] **步骤 8：静态检查**

```powershell
cd backend; uv run ruff check .; if ($?) { uv run mypy app }
```

期望：两者均无错误。

---

### Task 2：组 1 · 顾客会话与店铺浏览（11 条）

**覆盖路径：**

```text
POST   /api/v2/shop/sessions                              公开
POST   /api/v2/shop/sessions/demo-customer                顾客会话
DELETE /api/v2/shop/sessions/current                      顾客会话
GET    /api/v2/shop/stores/{shop_slug}                    公开
GET    /api/v2/shop/stores/{shop_slug}/products           公开
GET    /api/v2/shop/stores/{shop_slug}/products/{product_id}  公开
GET    /api/v2/shop/stores/{shop_slug}/coupons            公开
POST   /api/v2/shop/chat                                  顾客会话，默认 SSE
GET    /api/v2/shop/conversations                         顾客会话
GET    /api/v2/shop/conversations/{conversation_id}       顾客会话
DELETE /api/v2/shop/conversations/{conversation_id}       顾客会话
```

**文件：**
- 创建：`docs/backend-development-plan.md` §8.8
- 创建：`backend/app/schemas/v2/shop_session.py`
- 创建：`backend/tests/unit/schemas/v2/test_shop_session.py`

**接口：**
- 消费：`common.py` 的共用传输组件（含 `V2ChatResponseBase`），以及 `app.core.session.SessionRole`
- 产出：`ShopSessionCreateRequest/Response`、`DemoCustomerBindRequest/Response`、
  `StoreProfileResponse`、`ProductSummary`、`ProductDetailResponse`、`CouponSummary`、
  `ShopChatRequest`、`ShopAnswerMode`、`ShopChatResponse`（继承 `V2ChatResponseBase`）、
  `ShopConversationSummary`、`ShopConversationDetailResponse`
- **Task 3 不消费本任务的任何产出。** 两端的聊天响应各自继承 `common.V2ChatResponseBase`，
  不互相引用（§8.7.7）。

**必须在契约中写死的不变量**（来源 PRD §7.5）：

1. `POST /sessions` 请求体只含 `shop_slug`，响应含 `session_id`、`role="CUSTOMER"`、`expires_at`；
   **响应不得含 `merchant_id`**——`shop_slug` 到 `merchant_id` 的映射只在服务端。
2. `POST /sessions/demo-customer` 是**一次性且幂等**的操作：服务端根据当前店铺选择演示顾客身份，
   请求体不得携带 `buyer_key` 或顾客 ID；已绑定到同一身份时返回当前绑定结果且不得重复合并购物车，
   试图切换到不同身份才返回 `409 SESSION_ALREADY_BOUND`。绑定保留原高熵 `session_id`，并与匿名购物车
   合并在同一事务内完成（不变量 3：已绑定顾客的购物车不得切换归属）。
   该端点仅在 `DEMO_DEPLOYMENT_MODE=true` 时可用，关闭时返回统一的公开不可用响应。
3. `POST /chat` 的请求体含 `message`、**`conversation_id: str | null`**、`client_request_id`，
   **不含 `session_id`**（认证会话只走请求头，§8.7.7），**不含 `attachment_ids`**
   （§8.0.1 禁止把附件字段带入 v2）。
4. `ShopChatResponse` 继承 `V2ChatResponseBase`，只补 `answer_mode: ShopAnswerMode`。
   相对 v1 `ChatResponse` 的变化：去掉 `attachment_ids` 相关字段与 `ATTACHMENT` 枚举值，
   `session_id` 换成 `conversation_id`，`analysis_sources` 升为 `list[AnalysisSourceEntry]`
   （§8.7.6），新增 `tool_calls` 摘要数组。
5. `ShopAnswerMode` 收窄为 `SHOP_GUIDE | ORDER | AFTER_SALE | CHAT | INVALID`
   （顾客端同样需要区分「可回答」与「拒绝」，故保留 `answer_mode`），
   §8.8 须给出与 v1 `AnswerMode` 的迁移映射表。
6. `ProductSummary` / `ProductDetailResponse` 只暴露
   `stock_band = IN_STOCK | LOW_STOCK | OUT_OF_STOCK`，不得出现任何精确库存数量；
   `ProductDetailResponse` 的价格使用 `price_cents`，图片 URL 只允许演示静态资源或允许名单内 HTTPS。

- [x] **步骤 1：写 §8.8 字段契约**

按 §8.2 的表格体例，为 11 条路径逐条写出：请求字段表、响应字段表、错误码清单、
（`/chat` 额外）SSE 事件适用性说明。每条路径的错误码必须是 §8.7.2 表格里的码，出现新码须先加进 §8.7.2。

- [x] **步骤 2：写 Schema 失败测试**

创建 `backend/tests/unit/schemas/v2/test_shop_session.py`，至少覆盖：

```python
def test_session_create_rejects_merchant_id() -> None:
    """公开端点也不接受 merchant_id：只认 shop_slug。"""
    with pytest.raises(ValidationError):
        ShopSessionCreateRequest(shop_slug="borough-100", merchant_id="m1")


def test_session_response_has_no_merchant_id_field() -> None:
    assert "merchant_id" not in ShopSessionCreateResponse.model_fields


def test_shop_chat_request_rejects_attachment_ids() -> None:
    """v2 不继承 v1 的附件字段。"""
    with pytest.raises(ValidationError):
        ShopChatRequest(message="你好", client_request_id="r1", attachment_ids=[])


def test_shop_chat_request_rejects_session_id_in_body() -> None:
    """§8.7.7：认证会话只走请求头，请求体里出现 session_id 一律拒绝。"""
    with pytest.raises(ValidationError):
        ShopChatRequest(message="你好", client_request_id="r1", session_id="s1")


def test_shop_chat_request_accepts_null_conversation_id_for_new_thread() -> None:
    req = ShopChatRequest(message="你好", client_request_id="r1")
    assert req.conversation_id is None


def test_shop_chat_answer_mode_excludes_attachment() -> None:
    assert "ATTACHMENT" not in {m.value for m in ShopAnswerMode}


def test_chat_response_requires_at_least_one_analysis_source() -> None:
    """analysis_sources 是有序数组且至少一个元素；CHAT / INVALID 填 NONE，不得为空。"""
    with pytest.raises(ValidationError):
        ShopChatResponse(
            id="a1",
            conversation_id="c1",
            answer="你好",
            answer_mode="CHAT",
            analysis_sources=[],
            quality_status="NOT_RUN",
            quality_attempts=0,
            degraded=False,
            degraded_reason=None,
            created_at="2026-09-20T00:00:00Z",
        )


def test_shop_chat_response_uses_conversation_id_only() -> None:
    """§8.7.7：认证凭证不出现在聊天响应里。"""
    fields = ShopChatResponse.model_fields
    assert "conversation_id" in fields
    assert "session_id" not in fields
```

- [x] **步骤 3：确认失败 → 实现 `shop_session.py` → 确认通过**

```powershell
cd backend; uv run pytest tests/unit/schemas/v2/test_shop_session.py -v
```

先确认 `ImportError`，实现后确认全绿。

- [x] **步骤 4：交叉检查路径覆盖**

```powershell
cd "d:/vscode html/merchant_assistant"
rg -n "/api/v2/shop/(sessions|stores|chat|conversations)" docs/backend-development-plan.md
```

期望：上表 11 条路径全部在 §8.8 出现，一条不缺。

---

### Task 3：组 2 · 商家会话与对话目录（6 条）

**覆盖路径：**

```text
POST   /api/v2/merchant/sessions                            商家登录 Token（唯一使用 Bearer 的 v2 端点）
DELETE /api/v2/merchant/sessions/current                    商家会话
POST   /api/v2/merchant/chat                                商家会话，默认 SSE
GET    /api/v2/merchant/conversations                        商家会话
GET    /api/v2/merchant/conversations/{conversation_id}      商家会话
DELETE /api/v2/merchant/conversations/{conversation_id}      商家会话
```

**文件：**
- 创建：`docs/backend-development-plan.md` §8.9
- 创建：`backend/app/schemas/v2/merchant_session.py`
- 创建：`backend/tests/unit/schemas/v2/test_merchant_session.py`

**接口：**
- 消费：**只消费 `common.py`**（含 `V2ChatResponseBase`）。**不依赖 Task 2。**
- 产出：`MerchantSessionCreateRequest/Response`、`MerchantChatRequest`、`MerchantAnswerMode`、
  `MerchantChatResponse`（继承 `V2ChatResponseBase`）、
  `MerchantConversationSummary`、`MerchantConversationDetailResponse`

**必须在契约中写死的不变量：**

1. `POST /sessions` 的身份**只来自 `Authorization: Bearer <演示 Token>`**，请求体为空对象。
   响应含 `session_id`、`role="MERCHANT"`、`expires_at`、`merchant_display_name`，
   **不含 `merchant_id`**。
2. **Token 撤销级联**（PRD §7.5 不变量 5）：撤销演示 Token 时由它换取的全部现存会话同步失效。
   契约层的体现是 `DELETE /sessions/current` 之外还需在 §8.9 写明：会话失效一律返回
   `401 SESSION_INVALID`，客户端据此重新走 `POST /sessions`。
3. `MerchantAnswerMode` 保留 v1 六值 `METRIC | DETAIL | RULE | IDENTITY | CHAT | INVALID`，
   **移除 `ATTACHMENT`**，并在 §8.9 给出与 v1 `AnswerMode` 的一一映射。
4. `POST /chat` 的请求体含 `message`、**`conversation_id: str | null`**、`client_request_id`，
   **不含 `session_id`**（认证会话只走请求头，§8.7.7），**不含 `attachment_ids`**
   （§8.0.1 禁止把附件字段带入 v2）；幂等语义见 §8.7.3 白名单下的 Chat 说明。

- [x] **步骤 1：写 §8.9 字段契约**（体例同 Task 2 步骤 1）

- [x] **步骤 2：写失败测试**，至少覆盖：

```python
def test_merchant_session_create_request_is_empty_body() -> None:
    """身份只来自 Bearer，请求体不接受任何身份字段。"""
    with pytest.raises(ValidationError):
        MerchantSessionCreateRequest(merchant_id="m1")


def test_merchant_session_response_exposes_display_name_not_id() -> None:
    fields = MerchantSessionCreateResponse.model_fields
    assert "merchant_display_name" in fields
    assert "merchant_id" not in fields


def test_merchant_answer_mode_drops_attachment() -> None:
    assert {m.value for m in MerchantAnswerMode} == {
        "METRIC", "DETAIL", "RULE", "IDENTITY", "CHAT", "INVALID",
    }


def test_merchant_chat_request_requires_client_request_id() -> None:
    with pytest.raises(ValidationError):
        MerchantChatRequest(message="今天销售额")
    req = MerchantChatRequest(message="今天销售额", client_request_id="r1")
    assert req.conversation_id is None


def test_merchant_chat_request_rejects_session_and_attachments() -> None:
    with pytest.raises(ValidationError):
        MerchantChatRequest(message="今天销售额", client_request_id="r1", session_id="s1")
    with pytest.raises(ValidationError):
        MerchantChatRequest(message="今天销售额", client_request_id="r1", attachment_ids=[])
```

- [x] **步骤 3：确认失败 → 实现 → 确认通过**

```powershell
cd backend; uv run pytest tests/unit/schemas/v2/test_merchant_session.py -v
```

- [x] **步骤 4：跨角色对称性检查**

```powershell
cd backend
uv run python -c "from app.schemas.v2 import shop_session as s, merchant_session as m; print(sorted(set(s.ShopConversationSummary.model_fields) ^ set(m.MerchantConversationSummary.model_fields)))"
```

期望：差集只含双方**有意**不同的字段（如顾客侧的 `shop_slug`、商家侧的 `buyer_alias`）。
出现 `merchant_id` 或 `buyer_key` 即为契约错误，必须修掉。

---

### Task 4：组 3 · 交易：购物车与订单履约（9 条）

**依赖 Task 2**（来源闸门与会话定义）。**Task 5 依赖本任务；Task 6 只依赖 Task 1。**

**覆盖路径：**

```text
GET    /api/v2/shop/cart                            顾客会话
PUT    /api/v2/shop/cart/items/{product_id}         顾客会话（幂等设置数量）
DELETE /api/v2/shop/cart/items/{product_id}         顾客会话
POST   /api/v2/shop/orders                          演示顾客会话
GET    /api/v2/shop/orders                          演示顾客会话
GET    /api/v2/shop/orders/{order_id}               演示顾客会话
GET    /api/v2/shop/orders/{order_id}/events        演示顾客会话
POST   /api/v2/shop/orders/{order_id}/pay           演示顾客会话
POST   /api/v2/shop/orders/{order_id}/cancel        演示顾客会话
```

**文件：**
- 创建：`docs/backend-development-plan.md` §8.10
- 创建：`backend/app/schemas/v2/trade.py`
- 创建：`backend/tests/unit/schemas/v2/test_trade.py`

**接口：**
- 消费：`common.py`
- 产出：`PaymentStatus`、`FulfillmentStatus`、`OrderAfterSaleProjection`、`StockBand`、
  `CartResponse`、`CartItem`、
  `CartItemSetRequest`、`OrderCreateRequest`、`OrderSummary`、`OrderDetailResponse`、
  `OrderItemPriceSnapshot`、`FulfillmentEvent`、`FulfillmentEventPage`、`OrderPayRequest`、
  `OrderCancelRequest`。**Task 5 消费 `OrderDetailResponse` 与 `OrderItemPriceSnapshot`。**

**必须在契约中写死的不变量**（来源 PRD §7.1、§7.4）：

1. **支付与履约是两个独立字段，不合并**（§7.1 D14⑥）：

```text
PaymentStatus      = PENDING | PAID | CLOSED
FulfillmentStatus  = NOT_SHIPPED | SHIPPED | IN_TRANSIT | OUT_FOR_DELIVERY | DELIVERED
```

   `OrderAfterSaleProjection = NONE | ACTIVE | CLOSED` 只是订单级聚合投影，不与 Task 5 的
   `AfterSaleState` 混用。事件表才是事实源（§7.1 不变量 1）。`OrderDetailResponse` 返回三维投影，
   **不内嵌无界 `events` 数组**；履约事件只由独立的 `/orders/{order_id}/events` 游标分页响应提供。
   §8.10 写明「投影由事件重算，客户端不得据投影推断事件缺失」。

2. **顾客侧只暴露库存档位**：购物车、订单与公开商品响应只含
   `stock_band = IN_STOCK | LOW_STOCK | OUT_OF_STOCK`，不得返回 `stock_on_hand`、
   `stock_reserved`、`stock_available` 具体数量（PRD §3.1、D5）。精确库存三元组只在 Task 6
   的商家库存告警响应中出现；所有库存值仍由后端确定性计算，客户端不可写。

3. `POST /orders` 的响应必须包含**完整价格快照**（`OrderItemPriceSnapshot`：
   `unit_price_cents`、`discount_cents`、`line_total_cents`）——Task 5 的退款金额上限直接依赖它
   （§7.2 不变量 2：单行累计退款不得超过该行快照金额）。

4. `PUT /cart/items/{product_id}` 设置**绝对数量**而非增量，故天然幂等，不带 `client_request_id`；
   `quantity=0` 等价于删除。商品未通过本对话来源闸门时返回 `403 PRODUCT_NOT_IN_SCOPE`。

5. `POST /orders` 与 `POST /pay` 与 `POST /cancel` 全部携带 `client_request_id`。
   `pay` 与 `cancel` 的并发互斥（§7.1 不变量 4）在契约层表现为：败者返回
   `409 ILLEGAL_STATE_TRANSITION`，且 `details` 只含当前 `payment_status`，不含任何内部锁信息。

- [x] **步骤 1：写 §8.10 字段契约**，含上述五项不变量的显式条文。

- [x] **步骤 2：写失败测试**

```python
def test_payment_and_fulfillment_are_separate_enums() -> None:
    assert {s.value for s in PaymentStatus} == {"PENDING", "PAID", "CLOSED"}
    assert {s.value for s in FulfillmentStatus} == {
        "NOT_SHIPPED", "SHIPPED", "IN_TRANSIT", "OUT_FOR_DELIVERY", "DELIVERED",
    }
    assert not ({s.value for s in PaymentStatus} & {s.value for s in FulfillmentStatus})


def test_cart_item_set_request_has_no_idempotency_key() -> None:
    """PUT 设置绝对数量，天然幂等，不带 client_request_id。"""
    assert "client_request_id" not in CartItemSetRequest.model_fields


def test_cart_item_quantity_zero_is_allowed() -> None:
    assert CartItemSetRequest(quantity=0).quantity == 0


def test_customer_trade_contract_exposes_stock_band_not_quantities() -> None:
    """顾客只见三档，不见精确库存。"""
    assert "stock_band" in CartItem.model_fields
    assert not {"stock_on_hand", "stock_reserved", "stock_available"} & set(
        CartItem.model_fields
    )
    with pytest.raises(ValidationError):
        OrderCreateRequest(client_request_id="r1", stock_available=99)


def test_order_item_carries_full_price_snapshot() -> None:
    fields = OrderItemPriceSnapshot.model_fields
    assert {"unit_price_cents", "discount_cents", "line_total_cents"} <= set(fields)


def test_order_detail_exposes_projections_but_events_use_separate_page() -> None:
    fields = OrderDetailResponse.model_fields
    assert {"payment_status", "fulfillment_status", "after_sale_status"} <= set(fields)
    assert "events" not in fields
    assert "items" in FulfillmentEventPage.model_fields
```

- [x] **步骤 3：确认失败 → 实现 `trade.py` → 确认通过**

```powershell
cd backend; uv run pytest tests/unit/schemas/v2/test_trade.py -v
```

- [x] **步骤 4：状态机条文核对**

逐条打开 `docs/PRD.md` §7.1 的 6 条不变量与 §7.4 的 4 条不变量，确认每一条在 §8.10 都能找到
对应的字段定义或错误码条文。不能落到契约上的（例如「事务内原子完成」这类纯实现约束），
在 §8.10 末尾的「实现期约束」小节列出，标注由路由实现任务承接，**不得静默丢弃**。

---

### Task 5：组 4 · 售后（双端，5 条）

**依赖 Task 4。**

**覆盖路径：**

```text
POST /api/v2/shop/after-sales                          演示顾客会话
GET  /api/v2/shop/after-sales                          演示顾客会话
GET  /api/v2/shop/after-sales/{after_sale_id}          演示顾客会话
GET  /api/v2/merchant/after-sales                      商家会话
GET  /api/v2/merchant/after-sales/{after_sale_id}      商家会话
```

**文件：**
- 创建：`docs/backend-development-plan.md` §8.11
- 创建：`backend/app/schemas/v2/after_sales.py`
- 创建：`backend/tests/unit/schemas/v2/test_after_sales.py`

**接口：**
- 消费：`common.py`；`trade.py` 的 `OrderItemPriceSnapshot`
- 产出：`AfterSaleType`、`AfterSaleState`、`AfterSaleCreateRequest`、`AfterSaleSummary`、
  `AfterSaleConfirmationChallenge`、`CustomerAfterSaleDetailResponse`、
  `MerchantAfterSaleDetailResponse`、`AfterSaleEvent`

`after_sale_id` 指售后主记录 `after_sales.id`（PRD §8.1，数据迁移计划 M7）；`refunds` / `returns` 只是它名下的
资金 / 货品动作记录，工单以唯一外键挂在它上面，均不单独作为 `after_sale_id` 暴露。

**必须在契约中写死的不变量**（来源 PRD §7.2）：

1. 状态枚举与允许迁移：

```text
AfterSaleState = PENDING_MERCHANT | APPROVED | REJECTED | AWAITING_RETURN
               | RECEIVED | REFUNDED | AWAITING_CUSTOMER_INFO | CLOSED
AfterSaleType  = RETURN_REFUND | REFUND_ONLY | TICKET
```

   §8.11 必须附一张**允许迁移表**（源状态 → 允许的目标状态），非法迁移返回
   `409 ILLEGAL_STATE_TRANSITION`。

2. **发起条件由后端判定，模型不得决定**（不变量 1）：`AfterSaleCreateRequest`
   **不含**任何「是否符合发起条件」的客户端断言字段。

3. **界面确认证据**（不变量 6）：`AfterSaleCreateRequest.confirmation_token` 为
   `str | null = null`；缺失时按 §8.7.9 返回 `200 AfterSaleConfirmationChallenge`，而不是让
   Pydantic 在路由前吞成普通 422。`POST /shop/after-sales` 的 `200` challenge 与实际创建成功的
   `201 AfterSaleSummary` 是两个互斥响应分支，OpenAPI/Adapter 必须分辨。
   契约必须注明：token 只能由服务端预检响应签发，**聊天中的确认不生效**，Agent 不得代为生成。
   token 必须服务端签名、一次性、短期有效，
   并绑定 `session_record_id + merchant_id + buyer_key 摘要 + order_id + 售后类型 + 请求摘要`；
   签发、持久化消费与幂等处理顺序统一遵守 §8.7.9；不得重复创建单据。

4. **双端响应结构不对称且必须不对称**：商家侧 `MerchantAfterSaleDetailResponse` 的顾客标识
   只能是**店铺级脱敏别名** `buyer_alias`（R5）。读取商家详情必须在返回前写查看审计，
   但审计属于服务端副作用，响应不暴露内部 `audit_id`。顾客侧不含 `buyer_alias`。

5. 退款金额上限：`AfterSaleSummary.refund_amount_cents` 的契约说明必须写明
   「由后端按 `OrderItemPriceSnapshot.line_total_cents` 计算，单行累计不超过快照金额；
   客户端提交任何金额字段一律**拒绝并返回 `422 INVALID_REQUEST`**」——
   因此 `AfterSaleCreateRequest` **不含金额字段**，且因 `extra="forbid"` 而拒绝。
   **措辞必须是「拒绝」而不是「忽略」**：`extra="forbid"` 的行为是校验失败，
   写成「忽略」会与实现相矛盾，并诱导后来者改回 `extra="ignore"`。
   多行退款的分摊按 §8.7.8 的舍入顺序（先逐行舍入到分，再求和）。

- [x] **步骤 1：写 §8.11 字段契约**，含上述五项与允许迁移表。

- [x] **步骤 2：写失败测试**

```python
def test_after_sale_create_rejects_client_supplied_amount() -> None:
    """退款金额由后端按价格快照算，客户端不得提交。"""
    with pytest.raises(ValidationError):
        AfterSaleCreateRequest(
            client_request_id="r1",
            order_id="o1",
            after_sale_type="REFUND_ONLY",
            confirmation_token="t1",
            refund_amount_cents=99999,
        )


def test_after_sale_create_can_enter_confirmation_challenge_phase() -> None:
    request = AfterSaleCreateRequest(
        client_request_id="r1", order_id="o1", after_sale_type="REFUND_ONLY",
    )
    assert request.confirmation_token is None


def test_confirmation_challenge_is_distinct_from_created_after_sale() -> None:
    assert {"confirmation_token", "expires_at", "summary"} <= set(
        AfterSaleConfirmationChallenge.model_fields
    )
    assert "confirmation_token" not in AfterSaleSummary.model_fields


def test_merchant_detail_uses_alias_never_buyer_key() -> None:
    fields = MerchantAfterSaleDetailResponse.model_fields
    assert "buyer_alias" in fields
    assert "buyer_key" not in fields
    assert "viewed_audit_id" not in fields


def test_customer_detail_has_no_alias_or_audit_fields() -> None:
    fields = CustomerAfterSaleDetailResponse.model_fields
    assert "buyer_alias" not in fields
    assert "viewed_audit_id" not in fields
```

- [x] **步骤 3：确认失败 → 实现 → 确认通过**

```powershell
cd backend; uv run pytest tests/unit/schemas/v2/test_after_sales.py -v
```

- [x] **步骤 4：迁移表完备性检查**

把 PRD §7.2 的四条迁移链逐条对照 §8.11 的迁移表，确认每条链的每一跳都在表内，
且表内不存在 PRD 未列出的额外跳转。多出来的跳转是扩大范围，必须删掉或先改 PRD。

---

### Task 6：组 5 · 商家经营只读面（5 条）

**依赖 Task 1，不依赖 Task 4。** 顾客侧只暴露库存档位；本任务独立定义商家可见的精确库存三元组。
这一组是 §8.0.1 原「六组」遗漏的部分。

**覆盖路径：**

```text
GET  /api/v2/merchant/briefs/daily/current                     商家会话
POST /api/v2/merchant/briefs/daily/current/regenerate          商家会话（限流 + 幂等）
GET  /api/v2/merchant/inventory/alerts                         商家会话
GET  /api/v2/merchant/customer-signals                         商家会话
POST /api/v2/merchant/customer-signals/{signal_id}/ignore      商家会话
```

**文件：**
- 创建：`docs/backend-development-plan.md` §8.12
- 创建：`backend/app/schemas/v2/merchant_ops.py`
- 创建：`backend/tests/unit/schemas/v2/test_merchant_ops.py`

**接口：**
- 消费：`common.py`
- 产出：`DailyBriefResponse`、`BriefRegenerateRequest`、`InventoryAlert`、`InventoryAlertKind`、
  `CustomerSignal`、`CustomerSignalKind`、`SignalIgnoreRequest`

**必须在契约中写死的不变量：**

1. **当日简报是有版本的**（PRD §11.2.3「限流、幂等地替换当日简报版本」）：
   `DailyBriefResponse` 含 `brief_version`、`generated_at`、`business_date`。
   `regenerate` 携带 `client_request_id`；触发限流返回 `429 RATE_LIMITED`，
   按 §8.5 归为 `FAILED_RETRYABLE`。
2. **简报可能是降级产物**：`DailyBriefResponse` 必须混入 §8.7.6 的降级字段。
   R7 的核心是「不得把规则兜底包装成真实模型分析」——当简报由确定性规则生成而非模型生成时，
   `analysis_sources` 必须如实标注，不得填 `LLM`。
   **N2 的最小简报**（PRD §15 N2，2026-09-21 用户裁定）只汇总库存告警与待批准草稿、不调用 LLM，
   正是这种情形；同一响应结构在 N3 扩展为完整 M2，字段不变，只是来源与条目变多。
3. **顾客信号是派生提醒，不是事实源**（PRD §8.1）：`CustomerSignal` 必须含
   `derived_from`（指向事实来源的 ID 与类型）与 `is_ignored`。契约须注明忽略信号
   **不改变任何事实数据**，只写忽略记录与原因。
4. `SignalIgnoreRequest` 必含 `reason`（非空字符串）与 `client_request_id`。
5. 库存告警三类：`LOW_STOCK | OUT_OF_STOCK | SLOW_MOVING`。商家响应可含
   `stock_on_hand` / `stock_reserved` / `stock_available`，并验证
   `stock_available = stock_on_hand - stock_reserved`；这些精确数量不得进入 Task 2/4 的顾客响应。

- [x] **步骤 1：写 §8.12 字段契约**

- [x] **步骤 2：写失败测试**

```python
def test_brief_carries_version_and_business_date() -> None:
    fields = DailyBriefResponse.model_fields
    assert {"brief_version", "generated_at", "business_date"} <= set(fields)


def test_brief_includes_degradation_fields() -> None:
    """R7：简报也必须披露降级。"""
    fields = DailyBriefResponse.model_fields
    assert {"analysis_sources", "degraded", "degraded_reason", "quality_status"} <= set(fields)


def test_signal_ignore_requires_reason() -> None:
    with pytest.raises(ValidationError):
        SignalIgnoreRequest(client_request_id="r1")
    with pytest.raises(ValidationError):
        SignalIgnoreRequest(client_request_id="r1", reason="")


def test_signal_declares_derived_source() -> None:
    assert "derived_from" in CustomerSignal.model_fields


def test_inventory_alert_reuses_trade_stock_field_names() -> None:
    """库存字段命名只有一套，Task 4 定义，本组复用。"""
    assert {"stock_on_hand", "stock_reserved", "stock_available"} <= set(InventoryAlert.model_fields)


def test_inventory_alert_kinds_are_closed() -> None:
    assert {k.value for k in InventoryAlertKind} == {"LOW_STOCK", "OUT_OF_STOCK", "SLOW_MOVING"}
```

- [x] **步骤 3：确认失败 → 实现 → 确认通过**

```powershell
cd backend; uv run pytest tests/unit/schemas/v2/test_merchant_ops.py -v
```

---

### Task 7：组 6 · 草稿审批与变更账本（4 条）

**覆盖路径：**

```text
GET    /api/v2/merchant/drafts                      商家会话
GET    /api/v2/merchant/drafts/{draft_id}           商家会话
POST   /api/v2/merchant/drafts/{draft_id}/apply     商家会话
DELETE /api/v2/merchant/drafts/{draft_id}           商家会话
```

**文件：**
- 创建：`docs/backend-development-plan.md` §8.13
- 创建：`backend/app/schemas/v2/drafts.py`
- 创建：`backend/tests/unit/schemas/v2/test_drafts.py`

**接口：**
- 消费：`common.py`
- 产出：`DraftState`、`DraftKind`、`DraftSummary`、`DraftDetailResponse`、`DraftDiff`、
  `GuardrailCheckResult`、`DraftApplyRequest`、`DraftApplyResponse`、`ChangeLedgerEntry`

**必须在契约中写死的不变量**（来源 PRD §7.3，**七条不变量逐条落地**）：

1. `DraftState = STAGED | APPLIED | DISCARDED | EXPIRED`。
   **不存在 `APPROVED` 状态**（不变量 1）——批准不是可被后续请求复用的持久状态，
   而是 apply 事务的一个入参。契约里出现 `APPROVED` 即为错误。

   `DraftKind` 取值封闭：

   ```text
   RESTOCK | CONTENT_CHANGE | PRICE_CHANGE | COUPON | AFTER_SALE_DECISION
   ```

   `AFTER_SALE_DECISION` 承载商家售后决定（同意、拒绝、要求补充、确认收货含可售判定、退款）
   与随附回复——**PRD M9 裁定（2026-09-21）商家售后决定统一走草稿审批**，§11.2.3 无售后直接写端点。
   其 payload **不得含任何金额字段**，退款金额在应用时按价格快照计算（PRD §7.2 不变量 2）；
   `DraftDetailResponse` 的 diff 中金额只作为**应用时将计算的预览**展示，并标注以应用结果为准。
2. **批准绑定草案版本**（不变量 2）：`DraftApplyRequest` 必含 `draft_version`，
   与服务端当前版本不符返回 `409 VERSION_CONFLICT`（`retryable=false`，客户端须重取、重新确认后发新请求）。
3. **目标对象版本校验**（不变量 3）：`DraftApplyRequest` 必含 `target_version`，
   不匹配同样返回 `409 VERSION_CONFLICT`，且草稿**保持 `STAGED`** 不变。
   契约必须写明这一点：失败不推进状态。
4. **应用时重查护栏**（不变量 4）：`DraftDetailResponse.guardrail_checks` 是**预检快照**，
   契约须注明它仅供展示，apply 时按当时生效配置重查；重查不过返回 `422 GUARDRAIL_REJECTED`。
5. **幂等**（不变量 5）：`DraftApplyRequest` 含 `client_request_id`。
6. **批准只能来自审批界面**（不变量 6）：`DraftApplyRequest` 必含 `approval_evidence`
   （服务端签发、工作台界面提交）。证据必须是服务端签名、一次性、短期有效的 opaque token，绑定
   `session_record_id + merchant_id + draft_id + draft_version + target_version`；签发、持久化消费与
   幂等处理顺序统一遵守 §8.7.9。同一 `client_request_id` 重试返回第一次结果；证据换新请求 ID
   重放返回 `422 CONFIRMATION_REQUIRED`。Agent 与 MCP 均不得获得签发工具或生成该证据。
   `DraftDetailResponse` 必含仅供工作台 Adapter 消费的 `approval_evidence` 与
   `approval_evidence_expires_at`；这两个字段不得进入 Agent/MCP 工具投影或 SSE。
7. **变更账本**（不变量 7）：`DraftApplyResponse.ledger_entry` 含 `drafted_by`、`approved_by`、
   `approved_at`、`guardrail_results`。

- [x] **步骤 1：写 §8.13 字段契约**，含上述七条与允许迁移表。

- [x] **步骤 2：写失败测试**

```python
def test_draft_state_has_no_approved_value() -> None:
    """PRD §7.3 不变量 1：不存在可复用的『已批准』状态。"""
    assert {s.value for s in DraftState} == {"STAGED", "APPLIED", "DISCARDED", "EXPIRED"}


def test_apply_requires_both_versions() -> None:
    for missing in ("draft_version", "target_version"):
        kwargs = {
            "client_request_id": "r1",
            "draft_version": 3,
            "target_version": 7,
            "approval_evidence": "e1",
        }
        kwargs.pop(missing)
        with pytest.raises(ValidationError):
            DraftApplyRequest(**kwargs)


def test_apply_requires_approval_evidence() -> None:
    with pytest.raises(ValidationError):
        DraftApplyRequest(
            client_request_id="r1", draft_version=3, target_version=7,
        )


def test_draft_detail_issues_version_bound_approval_evidence() -> None:
    fields = DraftDetailResponse.model_fields
    assert {"approval_evidence", "approval_evidence_expires_at"} <= set(fields)


def test_ledger_entry_records_both_actors() -> None:
    fields = ChangeLedgerEntry.model_fields
    assert {"drafted_by", "approved_by", "approved_at", "guardrail_results"} <= set(fields)
```

- [x] **步骤 3：确认失败 → 实现 → 确认通过**

```powershell
cd backend; uv run pytest tests/unit/schemas/v2/test_drafts.py -v
```

---

### Task 8：组 7 · 记忆、反馈与 MCP（7 条）

**覆盖路径：**

```text
GET    /api/v2/shop/memories                                演示顾客会话
DELETE /api/v2/shop/memories/{memory_id}                    演示顾客会话
PUT    /api/v2/shop/memory-preference                       演示顾客会话
GET    /api/v2/merchant/memories                            商家会话
DELETE /api/v2/merchant/memories/{memory_id}                商家会话
POST   /api/v2/merchant/answers/{answer_id}/feedback        商家会话
POST   /api/v2/merchant/mcp                                 MCP 独立凭证
```

**文件：**
- 创建：`docs/backend-development-plan.md` §8.14
- 创建：`backend/app/schemas/v2/memory.py`
- 创建：`backend/tests/unit/schemas/v2/test_memory.py`

**接口：**
- 消费：`common.py`
- 产出：`CustomerMemoryItem`、`MerchantMemoryItem`、`MemoryLayer`、`MemoryPreferenceRequest`、
  `MemoryPreferenceResponse`、`V2FeedbackRequest`、`FeedbackKind`；MCP 信封优先复用所选官方 SDK
  的协议类型，不另造与标准漂移的 `McpEndpointContract`

**必须在契约中写死的不变量：**

1. **商家记忆分两层**（PRD §8.1：`merchant_memories` 拆为事实层与总结层）：
   `MemoryLayer = FACT | SUMMARY`。`FACT` 层必含 `source_ref`（来源引用）；
   删除事实来源触发总结重建——契约须注明 `DELETE /merchant/memories/{id}` 的响应含
   `summary_rebuild_scheduled: bool`。
2. **顾客记忆按顾客 + 店铺双重隔离**（R5）：`CustomerMemoryItem` 含 `shop_slug`
   与 `last_confirmed_at`，**不含** `buyer_key` 与 `merchant_id`。
3. **关闭记忆须显式确认并清空**（PRD §11.2.2）：`MemoryPreferenceRequest` 含
   `enabled: bool`；当 `enabled=false` 时 `purge_confirmation` 必填，缺失返回
   `422 CONFIRMATION_REQUIRED`。这是条件必填，须用 `model_validator` 实现而非无条件必填。
4. **MCP 是只读的，并固定协议版本 `2026-07-28`**：§8.14 必须列出 MCP 工具白名单，
   全部只读；采用无协议会话的 Streamable HTTP，不实现旧版 `initialize` / `initialized`，
   不接收或签发 `Mcp-Session-Id`。请求必须校验 `MCP-Protocol-Version: 2026-07-28`、
   `Mcp-Method`、`Mcp-Name` 与 JSON-RPC 2.0 正文的一致性。
   MCP **不接受 `X-Session-Id`**，只认 `Authorization: Bearer <MCP access token>` 形式的独立、
   短期、可撤销且限定商家与 scope 的凭证（`AGENTS.md` §8.3）。
   **凭证签发与撤销（PRD A8，2026-09-21 用户裁定）只经后端命令行脚本，契约中不存在签发、
   撤销或查询凭证的 HTTP 路径**；原值只在签发时展示一次，库中只存哈希，
   撤销后下一次请求即 401，校验结果不缓存。缺失或无效 MCP 凭证在解析
   JSON-RPC 前返回 HTTP 401，并带 `WWW-Authenticate`；协议解析后的方法、参数与工具错误使用
   JSON-RPC error，不包装成普通 v2 `ErrorResponse`。必须用标准 MCP 客户端做无 LLM 集成测试。
   协议依据固定为官方发布说明：`https://blog.modelcontextprotocol.io/posts/2026-07-28/`；
   实施时若 SDK 仍默认旧协议，必须显式配置版本并增加握手被拒绝的反例测试。
5. **团队知识与商家记忆单向边界**：§8.14 须重申记忆**绝不升级写回团队知识库**，
   契约层不提供任何「提升为团队知识」的字段或端点。

- [x] **步骤 1：写 §8.14 字段契约**

- [x] **步骤 2：写失败测试**

```python
def test_customer_memory_isolated_by_shop_without_raw_identifiers() -> None:
    fields = CustomerMemoryItem.model_fields
    assert {"shop_slug", "last_confirmed_at"} <= set(fields)
    assert "buyer_key" not in fields
    assert "merchant_id" not in fields


def test_disabling_memory_requires_purge_confirmation() -> None:
    with pytest.raises(ValidationError):
        MemoryPreferenceRequest(enabled=False)
    ok = MemoryPreferenceRequest(enabled=False, purge_confirmation="yes")
    assert ok.purge_confirmation == "yes"


def test_enabling_memory_does_not_require_confirmation() -> None:
    """条件必填，不是无条件必填。"""
    assert MemoryPreferenceRequest(enabled=True).purge_confirmation is None


def test_fact_layer_requires_source_ref() -> None:
    with pytest.raises(ValidationError):
        MerchantMemoryItem(layer="FACT", content="x")


def test_memory_contract_has_no_promotion_to_team_knowledge() -> None:
    """团队知识与记忆是单向边界。"""
    all_fields = set(MerchantMemoryItem.model_fields) | set(CustomerMemoryItem.model_fields)
    assert not any("promote" in f or "team_knowledge" in f for f in all_fields)
```

- [x] **步骤 3：确认失败 → 实现 → 确认通过**

```powershell
cd backend; uv run pytest tests/unit/schemas/v2/test_memory.py -v
```

---

### Task 9：全量自检与进度同步

**文件：**
- 修改：`docs/project-progress.md`（§一、§四、新增本轮验证结果）

- [x] **步骤 1：路径覆盖完备性检查**

把 PRD §11.2.2 与 §11.2.3 的 47 条路径提取出来，逐条确认在 §8.8–§8.14 中出现：

```powershell
cd "d:/vscode html/merchant_assistant"
$prd = (Select-String -Path docs/PRD.md -Pattern '`(GET|POST|PUT|DELETE) (/api/v2/\S+)`' -AllMatches).Matches | ForEach-Object { "$($_.Groups[1].Value) $($_.Groups[2].Value)" } | Sort-Object -Unique
$contract = (Get-Content docs/backend-development-plan.md -Raw) -split '## 8.8' | Select-Object -Last 1
$plan = [regex]::Matches($contract, '(GET|POST|PUT|DELETE)\s+(/api/v2/[^\s`|]+)') | ForEach-Object { "$($_.Groups[1].Value) $($_.Groups[2].Value)" } | Sort-Object -Unique
$missing = Compare-Object $prd $plan -PassThru | Where-Object SideIndicator -eq '<='
if ($missing) { $missing } else { "全部 47 条路径已覆盖" }
```

期望：输出「全部 47 条路径已覆盖」。有遗漏则回到对应任务补写。

- [x] **步骤 2：禁用字段与禁用构造扫描**

```powershell
cd backend
rg -n "merchant_id|buyer_key|attachment_ids" app/schemas/v2/
```

期望：**零命中**。任何一处命中都是 R5 或附件延期约束的破口，必须修掉后重跑。

```powershell
rg -n "V2ErrorCode|class ErrorCode" app/schemas/v2/
```

期望：**零命中**（裁定 A1：错误码只有 `app.core.errors.ErrorCode` 一个来源）。

```powershell
rg -n "\bfloat\b" app/schemas/v2/
```

期望：**零命中**（§8.7.8 禁止 float）。

```powershell
rg -n "session_id" app/schemas/v2/ | rg -v "shop_session.py|merchant_session.py"
```

期望：**零命中**——`session_id` 只允许出现在两个会话模块的签发响应里，
其余模块一律用 `conversation_id`（§8.7.7）。

- [x] **步骤 2b：幂等白名单一致性**

逐条比对 §8.7.3 的白名单与实际 Schema：白名单内的 Request 模型必须有 `client_request_id`，
白名单外的必须没有。

```powershell
cd backend
uv run python -c "
import pkgutil, importlib, inspect
from pydantic import BaseModel
import app.schemas.v2 as pkg
have = []
for m in pkgutil.iter_modules(pkg.__path__):
    mod = importlib.import_module(f'app.schemas.v2.{m.name}')
    for name, obj in inspect.getmembers(mod, inspect.isclass):
        if issubclass(obj, BaseModel) and obj.__module__ == mod.__name__:
            if 'client_request_id' in obj.model_fields:
                have.append(name)
print(sorted(have))
"
```

把输出与 §8.7.3 白名单左列逐条对照，多一个少一个都要查明原因。

- [x] **步骤 3：`extra="forbid"` 覆盖检查**

```powershell
cd backend
uv run python -c "
import pkgutil, importlib, inspect
from pydantic import BaseModel
import app.schemas.v2 as pkg
bad = []
for m in pkgutil.iter_modules(pkg.__path__):
    mod = importlib.import_module(f'app.schemas.v2.{m.name}')
    for name, obj in inspect.getmembers(mod, inspect.isclass):
        if issubclass(obj, BaseModel) and obj.__module__ == mod.__name__:
            if name.endswith('Request') and obj.model_config.get('extra') != 'forbid':
                bad.append(f'{mod.__name__}.{name}')
print(bad or '全部 Request 模型已设 extra=forbid')
"
```

期望：输出「全部 Request 模型已设 extra=forbid」。

- [x] **步骤 4：全量测试与静态检查**

```powershell
cd backend
uv run pytest tests/unit/schemas/v2/ -v
uv run ruff check .
uv run mypy app
```

期望：三条全绿。**同时跑一次既有全量回归**，确认新增包没有破坏 v1：

```powershell
cd backend; uv run pytest
```

期望：不低于 2026-09-09 基线的 1128 passed，新增 Schema 测试计入增量。
**若有失败，先按 `superpowers:systematic-debugging` 定位，不得把失败归因为「既有基线问题」而跳过。**

- [x] **步骤 5：Markdown 卫生检查**

```powershell
cd "d:/vscode html/merchant_assistant"; git diff --check
```

期望：无输出。

- [x] **步骤 6：更新进度快照**

修改 `docs/project-progress.md`：

- §一「当前阶段」：把「v2 字段契约……尚未开始」改为「§8.7–§8.14 已冻结 47 条路径的字段契约，
  Pydantic Schema 与 Schema 单测已落地；v2 路由、对应 OpenAPI、生成类型与 Adapter 尚未开始；共享 ErrorCode 的既有 v1 产物已同步」；
- §四「下一步」：删除第 1 条（已完成），把第 2 条「实现 N1 会话与隔离地基」提为第 1 条，
  并注明它现在可以开工——§8.8 与 §8.9 的契约已解除 §8.0.1 的封锁；
- 替换当前验证快照，记录步骤 1–5 的实际输出、测试通过数、**未执行 Git 提交、发布或历史改写操作**、
  **未调用真实 LLM**。

- [x] **步骤 7：汇报**

汇报已完成的七组契约、Schema 模块与测试数，明确列出**未完成项**：
v2 路径 OpenAPI 导出、对应生成类型、Adapter、全部 v2 路由实现、
以及 `plans/2026-09-17-agent-business-loop-decisions.md` 仍待裁定的 Q2 与 Q3。

**不得**把契约冻结说成 v2 功能已实现。

---

## 本计划明确不做的事

| 不做 | 归属 |
| --- | --- |
| 创建任何 FastAPI v2 路由 | N1 会话地基任务（本计划完成后解锁） |
| v2 路径 OpenAPI、生成类型、Adapter、快照 | 各组路由实现的同一次变更；五项完成门槛见 §8.0.1。Task 1 共享 ErrorCode 影响既有 v1 的生成产物与错误映射须立即同步 |
| 在验证异常处理器里写越权字段审计 | 路由实现任务（Task 1 步骤 6 已登记为实现期约束） |
| 数据库迁移与新表创建 | N1 数据地基任务（PRD §8.1） |
| `LlmClient` 协议骨架与 DeepSeek 双适配器 | N1 模型抽象任务（真实冒烟调用需 R3 授权） |
| 把 `deepseek-v4-flash` 迁到 `deepseek-flash` | `plans/2026-09-21-n1-llm-client-and-adapters.md` Task 5 |
| 评测骨架 E1–E4 | N1 评测基线任务 |
| Next.js 顾客端工程 | N2 开工前的独立计划 |
| 裁定 Q2（记忆召回边界）与 Q3（LLM 预算上限） | N3 / N4 |
