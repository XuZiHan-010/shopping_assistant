# 项目进度快照

> 本文件只保留当前可继续开发的事实快照，不追加每日流水账。每次完成一段可验证工作后，更新日期、状态、验证结果、下一步和风险。

**最后更新：2026-08-04**

## 当前阶段

- 后端：**B0–B3 已收口**（B3 的 9 条验收逐条复核并有测试兜住，见「B3 收口」）；下一阶段为 B4 安全经营数据查询。
  B3 的改动**尚未提交**（等待用户授权 commit）。
- 前端：F0、F1、**F2「Mock 会话闭环」已完成——11 个 Task 全部交付，并完成一轮用户代码审查整改**。可进入 F3。
  分支 `feature/f2-mock-conversation`，**Task 9–11 与审查整改的改动尚未提交**（等待用户授权 commit）。
- **F3 尚无实施计划与设计文档**：`docs/frontend-development-plan.md` §F3 只有阶段级任务与验收清单，
  F1/F2 那种逐 Task 的 SDD 计划（`docs/superpowers/plans/`）与设计说明（`docs/superpowers/specs/`）都还没写。
- F1 遗留：1440×1000 的人工视觉比对因本地 Windows Computer Use helper 不可用而待补，
  不影响已通过的结构与几何验收。

## 已完成

- FastAPI 工程、演示商家身份、PostgreSQL 基础设施、会话与回答持久化；Chat JSON/SSE 双路径、幂等、跨商家审计和服务端推荐问题。
- 后端 B3：已完成 B4 共享契约的 9 条指标 Seed、知识文档迁移和 Wiki 导入、两层知识检索、三套查询白名单、Fake/DeepSeek LLM Client、两阶段结构化意图，以及替换 FakeAgent 的 LangGraph 13 节点问答图。规则回答会引用命中的知识正文及文档路径；未命中明确提示。LLM 未配置、不可用或单请求预算耗尽均返回可见降级，尚未发生真实 DeepSeek 调用。新增 `20260804_0004` 将已迁移数据库的旧 Seed 对齐至 B4 契约。
  收口时补齐的四项：日期区间按注入的 `today` 校验（未来截断、起止颠倒拒绝）、DeepSeek 请求携带 `max_tokens` 且预算耗尽不发请求、指标口径改由知识**正文**生成并把待核验文案透出到 `quality_notes`、预置推荐问题按 `DATA`/`KNOWLEDGE`/`IDENTITY` 标注并逐条校验白名单。
- 前端 F0：Vue 3 + TypeScript + Vite 工程、`/` 与 `/knowledge-base` 路由、OpenAPI Adapter、API 基础地址、全局错误区、Caddy 静态镜像与基础 E2E。
- 前端 F1：Borough 原创 logo、全局 Design Tokens 与基础样式、三栏主布局、桌面/平板/移动响应式、独立 `ChatComposer.vue`、`ConversationColumn.vue`、单实例 `MerchantSwitcher.vue` 和最小 Chat 重置状态。
- F1 复查整改：Enter 发送（Shift+Enter 换行并兼容输入法组合态）、顶层 `header` + 对话 `main` landmark、商家菜单外部点击/Escape 关闭与焦点归还、合法且实际切换商家才重置会话；附件控件在 F7 前明确禁用。
- F1 复查整改：实际应用间距、字号、控件和过渡 Design Tokens；小字号说明文本达到 WCAG AA 对比度；顶栏导航选择器改为专用类名，并补齐品牌图片固有尺寸与跳至对话主区的跳转链接。
- E2E 正式文件为 `e2e/assistant.spec.ts`、`e2e/responsive.spec.ts` 与 `e2e/conversation.spec.ts`。
- **前端 F2 Task 1–8**：fixture 镜像生成与漂移检查（含 `.gitattributes eol=lf`，同时修好既有 `codegen:check` 的 Windows CRLF 假阳性）、
  `readChatStream` SSE 增量解析器（按字节切块，可劈开 3 字节中文）、`ChatTransport` 接口与 Mock 传输层、
  `api/chat.ts` 端点封装（五个操作全部透传 `AbortSignal`）、Chat Store 消息状态机、取消/重试/流中断处理
  （`retryMessage` 带重入保护并返回 `boolean` 表示「已在途、拒绝重试」）、消息渲染与输入区接线、侧栏三面板。
- **前端 F2 Task 9**：Auth Store（演示商家列表、`sessionStorage` 只存 `selected_demo_merchant_key`、刷新恢复、
  标识失效时回退默认商家并提示），`AssistantView` 的硬编码商家名已删除。
- **前端 F2 Task 10**：`ConversationNav.vue` 轮次目录（两轮起显示，点击切换侧栏内容）、
  `ConversationDrawer.vue` 历史会话抽屉（载入、删除、Escape 关闭、焦点归还），
  Chat Store 追加 `conversations` / `loadConversations` / `loadConversation` / `removeConversation`。
- **前端 F2 Task 11**：`e2e/conversation.spec.ts` 会话闭环 E2E（收口时 7 条，审查整改后 9 条）、
  Playwright 显式注入 `VITE_USE_MOCK=true`、`npm run mock:check` 生产产物 fixture 泄漏检查，
  以及本文件与 `docs/frontend-development-plan.md` 的同步。
- **F2 补齐的两项计划外任务**：`docs/frontend-development-plan.md` §F2 要求的「输入框自适应高度」与
  「自动滚动但不抢用户滚动」在 11 个 SDD Task 中没有对应条目，实测也确未实现，已在收口时补上并加测试。

## 用户代码审查整改（2026-08-04，F2 收口后）

14 条清单核实后:**12 条确认成立并已修 10 条**,1 条改定位,1 条本地无法验证。

已修（均带测试）:

- **P0 并发恢复**:`onMounted` 改为 `await authStore.restore()` 之后再拉会话列表。F2 的 Mock 不校验身份所以看不出差别——正因为看不出,更要现在定死,否则 F3 的会话请求会赶在 Token 就绪前发出而 401。
- **P0 降级标识（R7 + 前端方案 §10）**:`ChatMessage` 新增降级提示,展示 `degradedReason` 与 `analysis_sources`。此前 `degraded` / `quality` / `sources` 在全部组件里**零引用**,页面把 ¥256,920 当真实经营数据展示。
- **P0 商家隔离（演示级）**:新增 `resetTransportCache()` 与 `clearConversations()`,切商家时一并调用。**真正的隔离必须由服务端按 Token 过滤,F3 补上,不能靠前端自觉。**
- **P1 并发发送**:`submitMessage` 返回 `boolean` 并在 `isBusy` 时拒绝,输入区同步禁用发送。此前 `isBusy` 有定义但零消费者,两轮并发会各自开会话。
- **P1 商家名截断**:实测 1440px 下 `scrollWidth 107 / clientWidth 81`,顶栏列宽 118–145px 放宽到 150–175px,并加 E2E 断言。
- **P1 快速问题**:改为 4 个带分类眉标的入口,对齐 Prototype 四宫格;移出「帮我修改订单金额」与兜底「你好」——**推荐一个设计上就要被拒绝的请求等于教用户踩线**。
- **P1 轮次选中 + 键盘可达**:移除 `<article>` 整卡 click,改为仅助手 complete 轮次渲染真正的 `<button>`,带 `aria-current`。一次修掉「点用户消息选错轮次」与「不可聚焦」两条。
- **P1 删除确认**:两步删除 + 失败提示。此前模板里是游离 Promise,失败只留一条未处理拒绝。
- **P2 顶栏对比度**:`.brand-title p` 改用 `--color-text-secondary`。

改定位的一条:**图表领域类型过宽不是前端缺陷。** `docs/api.json` 的 `Visualization.type` 就是 `string | null`、`allowed_types` 就是 `string[]`,契约本身没有枚举。前端窄化等于凭空发明后端不保证的约束,违反 §5.0（Adapter 不得编造）。**修法是在后端契约加枚举,`codegen` 自动传导,前端一行不用改。**

按用户裁定推迟:CI 工作流、图表枚举（后端契约）、Docker 实测、整体视觉还原。

## F2 的边界与遗留

- **Mock 只在传输层**。载荷是后端 FakeAgent 的真实输出（`docs/fixtures/chat/` 的镜像），
  `sse.ts`、`api/chat.ts`、Adapter 与两个 Store 走的都是真实代码路径。
  **`api/chat.ts` 已在 F2 建立，F3 只替换 `api/transport.ts` 的实现与错误码分支，不要重新创建端点封装。**
- `src/api/mock/scenarios.ts` 从 Task 7 起是应用代码（`ConversationColumn` 静态引用快速问题文本），
  会进生产产物；进不去的是 fixture 载荷。F3 接入服务端推荐问题后应删掉这个静态引用。
- **待用户决定**：Mock 时序实测首个 step 约 127–130ms（远低于 1 秒要求）；完整一轮在 B3 之后
  **超过 5 秒**——mock 按字节分块、逐块 sleep 12ms，耗时随载荷线性增长，而 B3 把步骤从 3 个增加到 13 个。
  未改 mock 默认值（F3 换真实传输后它只影响 E2E），改为在 `e2e/assistant.spec.ts` 显式声明等待上限。
  若要更快的演示节奏，调 `stepDelayMs` 即可。
- `--color-text-muted`（#8a95a7，本页背景上实测约 2.8–3.0:1）是个陷阱 token：名字像次要正文用，
  实际只适合大字号或纯装饰。三个侧栏面板、`ConversationDrawer` 与顶栏说明文字都已改用
  `--color-text-secondary`（约 5.8:1）。该 token 在 `src/` 里现在只剩一处用途——
  `ChatComposer` 的**禁用态**附件按钮，WCAG 1.4.3 明确豁免禁用控件，这一处合规。
  **后续若要把它用在任何可读文本上，先量对比度。**
- 完整任务账本见 `.superpowers/sdd/2026-08-03-frontend-f2-mock-conversation/progress.md`，
  含 Task 9/10 发现的两处计划缺陷与三处有意偏差。

## F3 开工前需要知道的现状（2026-08-04 实测）

`docs/frontend-development-plan.md` §F3 的任务清单里，**多数条目已由 F0/F2 交付**，
真正剩下的是鉴权与错误处理。开工前先按下面这份现状核对，不要照着清单重做一遍：

- 已交付：`api/chat.ts`（F2）、会话列表与详情（F2）、`client_request_id`（F2）、
  请求取消（F2）、保存 `session_id`（F2）、`generated.ts` 与 `codegen:check`（F0）。
- `src/api/client.ts` 目前**只有基础地址解析**；HTTP 客户端、鉴权头装配、统一 `AppError`
  和 401/403/409/410/422/429/5xx 分支都还没写——这才是 F3 的主体。
- **P0 六种模式的 fixture 已由 B3 补齐**：`metric-order-detail.json`（`answer_mode` 名不副实）已删除，
  改为 `detail-order.json` 与 `identity-profile.json`，七个 fixture 覆盖
  `METRIC`/`DETAIL`/`RULE`/`IDENTITY`/`CHAT`/`INVALID` 全部六种，后端有哨兵测试钉住这一点。
  F3 可以直接把 Adapter 契约测试从 4 种补到 6 种，不需要再等后端导出。

## B3 收口（2026-08-04）

计划 §B3 的 9 条验收逐条复核，每条都有测试兜住（不是转述，均实跑）：

| 验收 | 证据 |
| --- | --- |
| 六类问题正确路由 | `tests/api/test_chat_fixtures.py` 用真实问答图导出七个 fixture 并断言覆盖六种 `answer_mode`；`tests/unit/agent/test_graph.py` 另覆盖 METRIC/DETAIL/RULE/CHAT 四条链路 |
| 拒绝 SQL 字符串 | `test_sql_in_metric_is_rejected`、`test_sql_metric_becomes_invalid` |
| 拒绝中文指标名 | `test_non_metric_code_name_is_rejected` |
| 非白名单指标与维度不进查询 | `test_non_whitelisted_dimension_is_rejected`、`test_non_whitelisted_filter_is_rejected`、`test_metric_whitelist_matches_metric_seed` |
| 索引层不加载正文、正文层只取命中域 | `test_index_retrieval_only_loads_index_and_rule_documents`、`test_domain_retrieval_matches_domain_aliases` |
| 知识回答包含来源 | `test_graph_rule_answer_uses_knowledge_content_and_source`（正文含文档路径且 `analysis_sources=["KNOWLEDGE"]`） |
| 未命中明确返回未命中 | `test_graph_rule_answer_explicitly_reports_knowledge_miss`、`test_no_knowledge_is_an_explicit_unmatched_result` |
| 超出调用次数或 token 上限显式降级 | `test_graph_marks_budget_exhaustion_as_visible_chat_degradation`、`test_graph_marks_unconfigured_llm_as_visible_chat_degradation` |
| Fake LLM 覆盖四种行为 | `test_normal_fake_client_returns_the_configured_response`、`test_invalid_json_is_returned_for_the_caller_to_validate`、`test_unusable_output_falls_back_with_visible_degradation[timeout/empty]` |

一处口径说明：「索引层不加载正文」指**不加载业务正文**——索引层仍会读取 `index`/`rule`/`目录`
这三类目录文档自身的内容，这与设计 §6.1 一致，作用是给模型提供拆词词汇。

### 收口时修掉的既有问题

- **`e2e/assistant.spec.ts` 的整轮问答用例卡在断言窗口边界**。Mock 传输层按字节分块、逐块 sleep 12ms，
  一轮耗时随载荷线性增长；B3 把步骤从 3 个增加到 13 个之后，一轮要 5 秒以上，正好越过 Playwright
  默认的 5 秒 expect 超时，稳定失败（3/3）。已在该断言上显式声明 15 秒上限并写明原因，未改 mock 默认节奏。
- **`GENERATED_NOTICE` 从未到达用户**。指标目录第三级生成的候选口径带「仅供参考，请以正式口径为准」文案，
  但响应组装时被丢弃，用户会把模型猜的口径当成正式口径（设计 §8 明确要求展示）。已透出到 `quality_notes`。
- **四个业务域推荐了查不到数的问题**。理赔、优惠券、商家其他、供应链在 B4 第一批经营表里没有数据，
  原配置却推荐「查看优惠券明细」这类数据型问题，点击必撞 `INVALID`（违反 §6.8）。已改为只推荐知识型问题，
  原型入口组里的「我想查看保证金」「查看优惠券明细」按同一理由替换（9 条原型问题保留 7 条）。
  **这是一处产品取舍**：§6.8「推荐问题必须落在白名单内」优先于与 Prototype 的 1:1 对齐；
  四个域补齐经营表后可改回数据型。

## 最近验证

- 2026-08-04（B3 收口，实跑非转述）：后端 `ruff check`、`ruff format --check`、`mypy`（60 个源文件）
  全绿，**pytest 440 passed**（收口前 259；新增主要来自逐条参数化的预置问题白名单校验、
  日期边界、DeepSeek 预算与问答图行为用例）。
- 2026-08-04（B3 收口）：前端 **Vitest 118 passed / 15 files**、**Playwright 19 passed**，
  `fixtures:check`、`codegen:check`、`lint`、`format:check` 均无漂移
  （fixture 与前端镜像已随预置问题改动重新导出）。
- 2026-08-04（审查整改后，实跑复验非转述）：**八条门禁全绿**——
  `lint`、`format:check`、`fixtures:check`、`codegen:check`、`mock:check`、`typecheck`、`test`、`build`。
- 2026-08-04：前端 Vitest **117 passed / 15 files**；在 F1 的 50 项之上新增 SSE 解析、Mock 传输、端点封装、
  Chat Store 状态机、取消与重试、侧栏三面板、Auth Store、历史会话抽屉、轮次目录、输入框自适应高度、
  自动滚动不抢滚动，以及审查整改带来的降级标识、并发提交守卫、轮次选中可键盘操作、
  删除二次确认与失败提示、身份先于会话加载。
- 2026-08-04：Playwright **19 passed**（F1 的 10 项 + F2 的 9 项）。新增覆盖：快速问题一轮问答且
  1 秒内出现阶段标签、连续两轮的目录切换、切换商家清空会话、刷新后选回同一商家、停止按钮真正中断
  且文案不说「出错」、跨 560px 断点选中商家不丢失、删除会话需二次确认后才移除、
  演示数据在回答卡片上有明确标识、桌面宽度下商家名不被截断。
- 2026-08-04：生产构建不含 fixture 载荷，且 Mock chunk 根本不被产出（`VITE_USE_MOCK` 未设时
  `isMockEnabled()` 折叠为常量 false，动态 import 被整体摇掉）。该检查已做双向验证：
  `VITE_USE_MOCK=true` 构建时 `mock:check` 以退出码 1 失败并指出泄漏文件。
- 说明：在当前 Windows shell 中，Playwright 自启 Vite 后的子进程回收会使命令超时；
  复用受控本地 Vite 后，19 项 E2E 在 13 秒内通过并正常退出。未改动项目的 Playwright 配置。

## F2 收口时修掉的既有问题

- **`e2e/responsive.spec.ts` 的 WCAG AA 用例自 Task 8 起就是坏的**：它按 `.side-empty p` 选取侧栏说明文字，
  而 Task 8 用三个真实面板取代了 F1 的占位结构，该类名已不存在，选择器只剩 1 个元素匹配（期望 3）。
  Task 8 的七条门禁不含 `test:e2e`，所以一直没暴露。已改为按 `data-testid` 选取三个面板的空态，
  覆盖 7 个元素，全部 ≥ 4.5:1。
- **两处 fire-and-forget 的未处理 Promise 拒绝**：`onMounted` 里的 `authStore.restore()` 与
  `chatStore.loadConversations()` 失败时只在控制台留一行红字，界面分别停在「加载中」和「暂无历史会话」，
  把加载失败伪装成正常空态。已分别在 Store 内与调用点接住，转成 F0 全局错误区的可见提示。

## 下一步

1. 用户授权后提交 F2 Task 9–11、审查整改与**后端 B3**的改动（同一工作树里两段工作叠在一起，
   提交时需要先决定是拆成两个提交还是合并），并决定是否合并 `feature/f2-mock-conversation`。
2. 确认演示节奏，决定是否调整 Mock 的 `chunkSizes` / `stepDelayMs` 默认值（B3 之后一轮 >5s）。
3. **前端 F3「API 契约与真实会话接入」**——下一个前端阶段。落点是 `api/transport.ts` 的真实实现、
   `Authorization` 头装配与 401/403/409/422 错误码分支；`api/chat.ts`、`sse.ts`、Adapter、两个 Store
   与全部组件都不重写。**动手前需要先写 F3 的设计说明与逐 Task 实施计划**（F1/F2 都有，F3 还没有）。
   F3 必须清掉的两件 F2 遗留：会话历史按 Token 在服务端隔离（前端目前只有演示级隔离）；
   `Authorization` 头装配后复核「身份先于会话请求」的顺序确实生效。
4. 审查清单中推迟的四项里还剩三项：CI 工作流（需先定分支保护与触发策略）、
   Docker 镜像实测（需本机 daemon）、整体视觉还原（依赖下一条的人工比对）。
   `Visualization.type` / `allowed_types` 的枚举已在 B3 落地（`ChartType`，经 `codegen` 传导到前端）。
5. 在本地浏览器 helper 可用时，补做 1440×1000 Borough 页面与只读 Prototype 的一次性人工视觉核对，并将结论回写本文件。
6. 后端 B4：实现订单、退款、商品与工单数据表、180 天演示数据、Analytics Repository 和受控 SQL 查询；首次真实 DeepSeek 调用前，仍必须取得用户对模型、调用次数和费用的明确同意。

## 风险与约束

- 未获明确同意不得调用真实 DeepSeek API、OCR 或日报生成；单元测试必须 mock LLM。
- 商家身份只能由 Bearer Token 解析；前端不得传递或信任 `merchant_id`。
- `yshopping-merchant-ai 4/` 与 `yshopping-prototype/` 只读；新代码与品牌资产必须使用 Borough。
- F1 尚待补充一次人工视觉比对；自动化几何、无障碍焦点和减少动画验收已通过。
- 单任务验证清单必须包含 `format:check` **与 `test:e2e`**——前者的缺失让格式漂移累积到 Task 8，
  后者的缺失让坏掉的对比度 E2E 一路潜伏到 F2 收口。

## 关键入口

- `AGENTS.md`：项目规则、目录与开发顺序。
- `docs/PRD.md`：产品范围与验收标准。
- `docs/frontend-development-plan.md`：F0–F9 前端阶段计划。
- `docs/backend-development-plan.md`：后端阶段与 API/SSE 契约。
- `frontend/src/views/AssistantView.vue`：三栏主页面。
- `frontend/src/api/transport.ts`：Mock 与真实实现的唯一分叉点，F3 的落点。
- `frontend/e2e/`：`assistant.spec.ts`、`responsive.spec.ts`、`conversation.spec.ts`。
- `docs/superpowers/plans/` 与 `docs/superpowers/specs/`：各阶段的实施计划与设计说明，
  含 F1（`2026-08-03-frontend-f1-visual-layout.md`）与 F2（`2026-08-03-frontend-f2-mock-conversation.md`，11 个 Task）。
  注意 F0 的计划单独放在根目录 `plans/`，其余都在 `docs/superpowers/plans/`。
- `.superpowers/sdd/<阶段>/progress.md`：SDD 任务账本，逐 Task 记录审查结论、修复轮次和延后项，
  比本快照细。**判断阶段进度以 git log 和该账本为准，计划文件的复选框不可信**——
  `2026-07-30-backend-b0-b1.md` 与 `2026-07-31-backend-b2-chat-api.md` 一个勾都没打，但两阶段早已交付。
