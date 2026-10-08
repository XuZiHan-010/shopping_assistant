# N2 双端会话目录与回答反馈实施计划

> **给执行者：** 用 `superpowers:executing-plans` 逐任务推进。步骤用 `- [ ]` 复选框跟踪。
> **本计划不含任何 Git 提交步骤**（R2）。全程 Fake LLM，零费用。

**目标：** 实现两端会话目录（6 条路径）与商家回答反馈（1 条路径），并把 PRD M13
「回答反馈与猜你想问」迁入 v2，满足 PRD §12.4
「顾客端与商家端均可新建、浏览、跳转和删除自己的会话；移动端无横向溢出」。

**架构：** 两端会话目录逻辑**对称**——同一套游标分页、同一套归属检查（`require_owned()`），
只是会话角色与可见字段不同。因此共用一个服务层，路由按角色分开。

**技术栈：** FastAPI、SQLAlchemy 2、pytest；前端 `frontend/`（Vue）与 `shop/`（Next.js）。

**规格来源：** PRD M13、§11.2.2–§11.2.3、§12.4；契约计划 §8.7.4（游标分页）、
§8.8、§8.9、§8.14；会话计划 Task 5（`require_owned`）。

---

## 这份计划为什么存在

写完 N2–N5 的 14 份计划后，对 PRD §11.2 的 47 条路径逐条核对认领情况，发现 **7 条没有任何
实施计划认领**：两端会话目录 6 条、商家回答反馈 1 条。

同时核对 PRD §15 发现：**M13「回答反馈与猜你想问」原先没有被分配到任何里程碑**——
v1 已有这项能力（`services/feedback_service.py`、`services/suggested_questions.py`），
但 v2 迁移没有归属。本计划将它放在 N2，与会话目录一起交付，
**2026-09-21 用户裁定 M13 与双端会话目录归入 N2，已写入 PRD §15 N2**。

---

## 入口条件

- [x] `n2-trade-closed-loop` Task 6 与 `n2-merchant-drafts-and-inventory` Task 7 已完成：
      两端 Chat 路由已能创建会话与回答（2026-09-23 复核：`POST /api/v2/shop/chat` 与
      `POST /api/v2/merchant/chat` 均已落地，顾客对话按 `owner_kind / owner_id` 归属，迁移 0032）。
      上午核对时两者都未开工，Task 1 因此一度受阻，下午解锁后已完成，见 Task 1 注记；
- [x] 会话计划 Task 5 已完成：`require_owned()` 可用（`app/services/resource_scope.py`，
      2026-09-23 核对，Task 2 已实际复用）；
- [x] 契约计划 Task 2、3、8 已完成：§8.8、§8.9、§8.14 的会话目录与反馈字段已定
      （2026-09-23 核对，Task 2 的 `V2FeedbackRequest`/`V2FeedbackResponse` 已在
      `backend/app/schemas/v2/memory.py` 落地，与本计划描述一致）；
- [x] **核对契约中 `conversation_id` 与 `session_id` 的分名**（契约计划 §8.7.7），
      本计划的路径参数是 `conversation_id`，**与认证会话无关**（2026-09-23 核对：两个目录路由文件
      `session_id` 零命中）。（本条对 Task 1/会话目录才有意义；
      Task 2 反馈路由的路径参数是 `answer_id`，不涉及本条。）

**2026-09-23 执行发现（供后续执行者与 Astra 参考）：Task 2（商家回答反馈）实际不依赖上方第一条
入口条件。** 反馈路由只需要 `answer_id` 能解析出所属 `merchant_id`，与该回答是经 v1 Chat 还是 v2
Chat 产生无关——v1 `answers`/`feedback` 表已存在且不受 v2 Chat 路由是否落地影响。已在
Chat 路由均未开工的情况下独立完成 Task 2 并通过真实 PostgreSQL 测试，见
`docs/project-progress.md`「N2 模块 D 进展」。Task 1（会话目录）已在两条 Chat 路由落地后完成；
Task 3 已于 2026-09-24 随契约 §8.7.10 补字段完成（见下方 Task 3 段落）。

**2026-09-23 Task 1 执行中发现的缺口（已按用户裁定修复）：上面「与该回答是经 v1 还是 v2 Chat 产生无关」
的前提曾不成立**——v2 Chat 回答 `id` 现场生成、不写 `answers` 表，而 `feedback.answer_id` 外键指向
`answers.id`，对任何 v2 回答提交反馈都会 403。用户裁定按「v2 回答写入 `answers`」修复（迁移 `20260923_0034`）：
`answers.surface` 标记 v2 行，v1 唯一索引收窄为只约束 v1 行；`record_turn()` 同事务写回答行；商家反馈只接受 v1 与
`MERCHANT` 回答；Chat BI 暂只统计 v1（其口径按 v1 回答结构解析，v2 接入需先定口径）。修复中同时发现并堵住一处
既有 R5 泄露：v1 `/api/conversations` 只按 `merchant_id` 过滤，商家可经 v1 目录列出并读取本店顾客的 v2 对话；
现 v1 仓储只认 `surface IS NULL AND owner_kind IS NULL` 的对话。测试：`tests/integration/v2/test_v2_answer_persistence.py` 8 例。

---

## 全局约束

- 中文（R1）；**不执行 Git 操作**（R2）；**不调用真实 LLM**（R3）。
- 跨主体访问一律 `403 RESOURCE_FORBIDDEN`，与"不存在"逐字段一致（会话计划 Task 5）。
- 列表一律游标分页，排序键与 tie-breaker 按契约计划 §8.7.4。
- **采纳与赞踩是不同语义，不得互相覆盖**（M13、Q12）。

---

## 覆盖路径

```text
GET    /api/v2/shop/conversations
GET    /api/v2/shop/conversations/{conversation_id}
DELETE /api/v2/shop/conversations/{conversation_id}
GET    /api/v2/merchant/conversations
GET    /api/v2/merchant/conversations/{conversation_id}
DELETE /api/v2/merchant/conversations/{conversation_id}
POST   /api/v2/merchant/answers/{answer_id}/feedback
```

---

## 文件结构

| 文件 | 责任 |
| --- | --- |
| `backend/app/services/v2/conversations.py` | 两端共用：列表、详情、删除 |
| `backend/app/api/routes/v2/shop_conversations.py` | 顾客三条路由 |
| `backend/app/api/routes/v2/merchant_conversations.py` | 商家三条路由 |
| `backend/app/api/routes/v2/merchant_feedback.py` | 反馈 |
| `backend/app/services/v2/suggestions.py` | 猜你想问（复用 v1 候选生成） |
| `frontend/src/components/chat/ConversationSidebar.vue` | 商家端会话侧栏迁移 v2 |
| `shop/src/app/[shop_slug]/assistant/conversations/` | 顾客端会话目录 |

---

### Task 1：会话目录服务与路由

**2026-09-23 已完成**（上午受阻于两端 Chat 路由未落地；下午两条路由落地后开工）。
实现与验证见 `docs/project-progress.md`「N2 模块 D 进展」。落地时补的存储决定（迁移 `20260923_0033`）：

- `conversations.surface`（`SHOP` / `MERCHANT`）：v1 对话与 v2 商家对话同样 `owner_kind IS NULL`，
  不打标记就分不开；v1 历史回答是 v1 结构，拼不出 v2 详情要求的完整响应，**因此 v1 历史对话不进入 v2 目录**；
- `conversations.deleted_at`：软删除；
- `messages.response_payload`：助手消息存完整最终响应，详情的 `answer` 与 Chat 响应逐字段相同；
  两端 Chat 服务改为经 `services/v2/conversations.record_turn()` 写消息（显式时间戳保证「先问后答」，
  并推进对话 `updated_at`）。

**与本节下方测试草图的一处差异，以契约为准**：契约 §8.8.2 / §8.9.2 规定删除「删除后再次请求统一 403」，
所以第二次 `DELETE` 返回 403 而不是 200/204；幂等体现在不产生第二次副作用。

- 列表：游标分页，**只列本主体的会话**（顾客按 `merchant_id + buyer_key`，商家按 `merchant_id`）；
- 详情：消息按时间正序，沿用 v1 详情的消息游标机制；
- 删除：软删除，**幂等**；删除后该会话的来源状态随之失效（O2——来源状态按对话隔离）；
- 访客会话（未绑定演示顾客）只能看到**本认证会话内**创建的对话。

- [x] **步骤 1：写失败测试**（`backend/tests/integration/v2/test_conversations.py`，15 例，真实 PostgreSQL）

```python
async def test_customer_cannot_list_other_customers_conversations(client) -> None:
    await chat(client, headers=CUSTOMER_A)
    items = (await client.get("/api/v2/shop/conversations", headers=CUSTOMER_B)).json()["items"]
    assert items == []


async def test_foreign_conversation_detail_indistinguishable_from_missing(client) -> None:
    missing = await client.get(f"/api/v2/merchant/conversations/{uuid4()}", headers=M_A)
    foreign = await client.get(f"/api/v2/merchant/conversations/{CONV_OF_M_B}", headers=M_A)
    assert missing.status_code == foreign.status_code == 403
    assert strip_request_id(missing.json()) == strip_request_id(foreign.json())


async def test_delete_is_idempotent_and_clears_provenance(client, provenance) -> None:
    cid = await chat_and_see_product(client, P, headers=CUSTOMER_A)
    for _ in range(2):
        assert (await client.delete(f"/api/v2/shop/conversations/{cid}",
                                    headers=CUSTOMER_A)).status_code in {200, 204}
    assert not await provenance.has(conversation=cid, object_id=P)


async def test_customer_route_rejects_merchant_session(client) -> None:
    r = await client.get("/api/v2/shop/conversations", headers=M_A)
    assert r.status_code == 403 and r.json()["code"] == "SESSION_ROLE_MISMATCH"
```

- [x] **步骤 2：确认失败 → 实现 → 确认通过 → 五项完成门槛**（2026-09-23：先 404 失败；
      实现后 15 passed；变异检查确认排序与删除后不可续写两条测试能抓到回退；
      另登记 SEC-CROSS-006~011 覆盖 6 条新路由）

---

### Task 2：回答反馈（M13）

**2026-09-23 已完成**（不依赖入口条件第一条，理由见上方「执行发现」）：路由、服务、v2 幂等
基础设施、迁移与 9 例真实 PostgreSQL 测试均已落地，验证结果见
`docs/project-progress.md`「N2 模块 D 进展」。

`POST /api/v2/merchant/answers/{answer_id}/feedback`。

- **采纳**与**点赞 / 点踩**是两种独立语义，**互不覆盖**——采纳一条回答不等于赞它，
  点踩也不撤销采纳。契约 §8.14 用 `kind: ADOPTION | REACTION` 区分：`ADOPTION` 只带 `adopted`，
  `REACTION` 只带 `reaction`（`LIKE` / `DISLIKE`，`null` 表示撤销）与可选 `reason`；响应
  `V2FeedbackResponse` 总是返回两者的当前完整状态；
- 点踩可附可选原因（原因只能附着在赞踩上）；
- 只能对本商家会话里的回答反馈，越权 `403`；
- 按 `client_request_id` 幂等；
- 点踩与降级样本将来进入 E6 线上反馈回流（`n5-final-eval-and-closeout`），
  **本任务只负责记录，不自动进入评测集**。

- [x] **步骤 1：写失败测试**（2026-09-24 核对：已随 2026-09-23 实现落地，只是未勾选——
      `tests/api/v2/test_merchant_feedback.py::test_adoption_and_reaction_do_not_overwrite_each_other`
      与 `tests/unit/schemas/v2/test_memory.py` 同名用例；真实 PostgreSQL 复跑通过）

```python
async def test_adoption_and_vote_do_not_overwrite_each_other(client) -> None:
    await feedback(client, A, {"kind": "ADOPTION", "adopted": True})
    await feedback(client, A, {"kind": "REACTION", "reaction": "DISLIKE", "reason": "数字不对"})
    fb = await get_feedback(A)
    assert fb.adopted is True and fb.reaction == "DISLIKE"
```

- [x] **步骤 2：确认失败 → 实现 → 确认通过 → 五项完成门槛**（2026-09-23，真实 PostgreSQL，
      9 例；ruff/mypy 全绿；OpenAPI/生成类型已重新导出）

---

### Task 3：猜你想问（M13）

**2026-09-24 已完成**（此前受阻于契约缺字段与顾客问题库缺失；用户未给内容方向，按「继续」授权自行拟定并
在账本留了裁定，供审阅）。

- 契约：`docs/backend-development-plan.md` §8.7.10 新增 `suggestions` / `suggestion_alternates`
  （`V2ChatResponseBase`，可选、默认 `[]`，与 v1 同名同形；至多 3 条 / 5 组，备选不得重复当前组）；
  OpenAPI、`docs/api.md`、`frontend/src/api/generated.ts` 已重新导出，`codegen:check` 通过；
- 服务：`backend/app/services/v2/suggestions.py`，候选全部由后端生成；每条问题标注回答它的工具，测试逐条
  核对该工具在**当前角色**的真实工具面上（顾客端只含 `search_products` / `get_product` /
  `get_shop_policy` / `set_cart_item` 答得了的问题，商家端只含 `get_inventory_alerts` / `draft_restock`，
  两端候选互不相交）；
- **订单与售后问题不进候选**：N2 里它们由页面回答，对话没有对应工具，推荐等于制造一次拒答；N3 补工具再加；
- 「模型只排序」：`constrain_rewrite()` 要求排序结果仍属本角色候选集合、条数一致、互不重复，否则回退原候选；
  **N2 未把任何模型接到这一步**（不增加每轮 LLM 调用），只有校验函数与测试；
- 两端 Chat 服务把候选写进响应，随 `record_turn()` 落盘，详情接口读回逐字段相同；降级回答照常带候选，
  降级字段不变（R7）。

- [x] **步骤 1：写失败测试**——顾客端候选不含商家工具能回答的问题；改写不通过校验时回退
      （`tests/unit/services/v2/test_suggestions.py` 90 例、`tests/unit/schemas/v2/test_common.py` 新增 11 例、
      `tests/integration/v2/test_suggestions_in_chat.py` 6 例）
- [x] **步骤 2：确认失败 → 实现 → 确认通过**（RED：导入失败 / 响应无候选；GREEN：全部通过）

---

### Task 4：两端界面

- 商家端：把现有 v1 会话侧栏迁到 v2 Adapter（`n2-merchant-vue-v2-migration` 的会话凭证作用域）；
- 顾客端：新增会话目录页，支持新建、浏览、跳转历史轮次、删除；
- **两端移动端无横向溢出**（PRD §12.4、M1）。

> **本任务的局部前置（2026-09-22 用户裁定补入）：** Task 1–3 只依赖上方入口条件，可在两个前端工程就位前完成；
> 本任务要改两端界面，须等前端工程与会话凭证就位。

- [x] **前置：`n2-merchant-vue-v2-migration` Task 1–2 与 `n2-shop-nextjs-app` Task 1–2 已完成**——
      商家端 `merchant-session` 凭证作用域与会话交换可用，`shop/` 工程与顾客会话凭证可用；未完成时停在此处
      （2026-09-24 核对：两份计划均已全部勾选）
- [x] **步骤 1：写组件测试**——删除后列表移除且当前会话若被删则回到新建态
      （顾客端见下方「2026-09-24 执行记录」；商家端按用户裁定改做 Task 4B 的 v2 运营助手页）
- [x] **步骤 2：Playwright 响应式检查**——在 375px 宽度下断言 `document.documentElement.scrollWidth
      <= window.innerWidth`，两端各一条（顾客端 `shop/e2e/conversations-responsive.spec.ts`；
      商家端 `frontend/e2e/s3/ops-assistant-responsive.spec.ts`）

**2026-09-24 执行记录（顾客端完成，商家端受阻）：**

- 顾客端：目录做成导购页内的面板（`shop/src/app/[shop_slug]/assistant/conversations/ConversationDirectory.tsx`），
  不另开路由——会话凭证只在内存，整页跳转会换成新访客会话；本步测试针对的「当前对话被删回到新建态」也只在同页成立。
  Adapter `shop/src/api/adapters/conversations.ts`（历史回答复用 Chat 的 `toChatTurn`），门面 `shop/src/api/conversationsApi.ts`
  （消息按 `created_at ASC` 逐页取完，上限 1000 条并如实提示）。**主体变化（访客绑定演示顾客、切换身份）时回到新建态**：
  对话归属按主体（`principal_owner`），绑定后原访客对话续聊会被 403。组件测试 13 例 + Adapter 2 例（RED→GREEN，
  两处关键分支做过变异检验）；375px Playwright `shop/e2e/conversations-responsive.spec.ts` 走完新建/浏览/跳转/删除，
  **首跑抓到既有缺陷**：聊天气泡缺 `overflow-wrap`，无空格长串把页面撑到 900px，已在 `globals.css` 修复。
- 商家端**未迁移**：Vue 商家对话仍走 v1 `POST /api/chat`，而按 Task 1 的存储决定 v1 对话不进入 v2 目录——只把侧栏换成
  v2 Adapter，列表会是空的，点开的 v2 对话也无法用 v1 Chat 续聊。它依赖模块 E 留下的未决项
  「Vue 端 v2 对话界面是否纳入 N2」，需用户裁定后再做。商家端 375px 检查同样待裁定后补
  （另注：模块 E 记录 v1 顶栏在 561/580px 即溢出，届时须一并处理）。
- **2026-09-24 用户裁定**：N2 内补商家端 v2 对话界面，做成**独立 v2 运营助手页**，与 v1 分析助手并存（已写入 PRD §15 N2）。
  商家端部分改按下方 Task 4B 执行；v1 `AssistantView` 与 `ConversationDrawer` 不改（v1 顶栏窄屏溢出仍归 v1 页面，
  不在本任务内）。

### Task 4B：商家端 v2 运营助手页（2026-09-24 用户裁定补入）

**为什么不直接替换 v1 对话页**：N2 的 v2 商家工具只有 `get_inventory_alerts` / `draft_restock`；指标、明细、规则、图表、导出
要到 N3 才迁入 v2。替换会让商家演示在 N2–N3 之间整体回退。

| 文件 | 责任 |
| --- | --- |
| `frontend/src/api/adapters/merchantConversations.ts` | v2 会话目录（列表 / 逐页取完历史 / 删除）、Chat 流与回答反馈；带 `Accept-Language` |
| `frontend/src/stores/opsChat.ts` | 当前对话、消息、目录、预填输入与回答反馈；`registerSessionScopedReset` 换商家即清空 |
| `frontend/src/views/OpsAssistantView.vue` | 路由 `/ops-assistant`；能力范围说明、工具行（只名称与状态摘要）、降级可见（R7）、猜你想问、回答采纳与赞踩 |
| `frontend/src/components/opsChat/OpsConversationList.vue` | v2 会话目录侧栏：新建、打开、删除、加载更多 |
| `frontend/src/views/TodayView.vue` | 条目下一步动作：保留 `fill-input` 事件，另把问题写入 `opsChat` 预填并跳到运营助手页，**不代为发送** |
| `frontend/src/i18n/locales/{zh-CN,en-US}.ts` | 新文案双语 |
| `frontend/e2e/s3/ops-assistant-responsive.spec.ts` | 真实后端 + 脚本化模型；375px 走完新建 / 浏览 / 跳转 / 删除并断言无横向溢出 |

- [x] **步骤 1：Adapter 与 Store 失败测试 → 实现**——历史回答经 `parseFinalResponse`；删除当前对话回到新建态；
      换商家（会话作用域重置）清空对话与目录；续聊带 `conversation_id`，新建不带
      （2026-09-24：Adapter 5 例、Store 9 例；另覆盖「换商家发生在回答途中，迟到回答不写回」，变异检验能抓到）
- [x] **步骤 2：视图与侧栏组件测试 → 实现**——删除后列表移除且当前会话若被删则回到新建态；降级原因可见；工具行不含参数；
      简报动作只预填不发送（2026-09-24：视图 8 例、TodayView 新增 1 例；自查补出中文输入法选词回车误发送，先红后绿）
- [x] **步骤 3：Playwright 375px**（`npm run test:e2e:s3`，一次性库 `*_s3_e2e_test`）——`scrollWidth <= innerWidth`
      （2026-09-24：与 S3 闭环同跑 2 passed；去掉气泡 `overflow-wrap` 后该用例报 958px 失败，检查有效）
- [x] **步骤 4：前端全量 `npm run test`、`typecheck`、`lint`、`build`**（2026-09-24：670 passed，其余 0 错误；
      两处 locale 文件的 Prettier 提示是既有行，模块 E 已登记，未改）
- [x] **步骤 5：补齐 v2 回答反馈界面及历史状态**（2026-09-24）——当前和历史回答均支持采纳、赞踩、可选原因；
      采纳与赞踩单独提交，使用服务端完整回执更新状态；错误可重试，换商家后旧回执不回写。
      商家会话详情按当前 `merchant_id`、对话和 `MERCHANT` surface 批量返回页内反馈状态，重新打开可正确显示已保存选择。
      独立 PostgreSQL 定向 118 passed；前端定向 27 passed；OpenAPI、两端生成类型、类型检查与 lint 一致。

---

### Task 5：自检

```powershell
cd backend
rg -n "session_id" app/api/routes/v2/*conversations*.py
uv run pytest; uv run ruff check .; uv run mypy app
```

第一条期望零命中——会话目录的路径参数与响应字段都是 `conversation_id`（契约计划 §8.7.7），
出现 `session_id` 说明把认证会话与业务对话混用了。

更新 `docs/project-progress.md`：会话目录与反馈完成情况（归属依据：PRD §15 N2，2026-09-21 用户裁定）。

---

## 本计划明确不做的事

| 不做 | 归属 |
| --- | --- |
| 顾客侧回答反馈 | PRD §11.2.2 未列顾客反馈路径，不做 |
| 反馈自动进入评测集 | 不做（E6：须人工决定） |
