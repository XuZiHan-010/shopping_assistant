# N4 阶段总览：A / B / C 三阶段的划分、依赖、难度与出口标准

> **本文件是 N4 的总览，不是实施计划。** 它只回答四件事：N4 拆成哪几个阶段、每个阶段落在框架的哪一层、
> 难点在哪、怎样算完成。逐步骤的做法在各阶段自己的实施计划里；本文件与它们冲突时以实施计划为准，
> 并回头修正本文件。
> **进度只在 `docs/project-progress.md` 维护**；下文「状态快照」标注了日期，过期以进度快照为准。
> **本文件不含任何 Git 提交步骤**（R2），也不触发任何 LLM 调用（R3）。
> 写法仿照 `plans/2026-09-24-n3-module-roadmap.md`。
> **2026-09-28 修订**：D-N4-1 至 D-N4-3 已由用户裁定（采纳推荐方案），见 §六；阶段 0 的 N3 残项按最新进度快照更新。
> **2026-09-28 再修订（PRD §15「W」）**：用户裁定商家工作台界面重设计插在 N4 剩余任务之前，计划为 `plans/2026-09-28-merchant-workbench-redesign.md`。
> - N4 的两个商家端页面任务要等 W 对应任务完成后再做：B Task 9（记忆面板）等 W Task 5，C Task 6 的页面部分等 W Task 7。
> - N4 后端任务可以与 W 并行，唯一撞点是 `docs/api.json` 导出，按 §三规则 3 串行。
> - B Task 8（`shop/`）不受影响。
> - 依赖见 §三任务级依赖末尾几行。
> - **顾客端店面重设计 WS**（`plans/2026-09-28-shop-storefront-redesign.md`）同样与 N4 并行，撞点有四处，已写进 B Task 4、7、8 与下方规则：
>   - `docs/api.json` 导出；
>   - 顾客工具注册文件；
>   - 演示商品换名；
>   - B Task 8 的记忆页并入 WS 的动态抽屉。

**目标：** 给 N4（PRD §15「记忆、压缩与检索」）画一张可核对的地图：切成 A、B、C 三个阶段，
写清每阶段的范围、撞点与出口标准，并把 2026-09-21 预写的三份 N4 计划按 **N3 实际落地的代码**重新编组。

**规格来源：** `docs/PRD.md` §15 N4、A5–A7、A9、A11、C7、M11、M12、§7.6、E5、§12.4–§12.5；
`docs/backend-development-plan.md` §6.10、§6.12–§6.14、§8.14；`AGENTS.md` R2–R5、R7、§十一；
审查点见 `plans/2026-09-22-astra-checklist.md` §七。

---

## 一、总览表

| 阶段 | 框架层 | 实施计划（`plans/2026-09-21-*.md`） | 步骤 | 难度 | 收口 | 需 R3 授权 |
| --- | --- | --- | --- | --- | --- | --- |
| **0** 入口核对与 N3 收口 | 审查 + 裁定 | Astra「入口-N4」；N3 复审与出口残项（§四） | — | — | — | 否 |
| **A** 上下文与压缩 | Agent 内核：`agent/loop/`、两端 Chat 服务 | `n4-context-compaction` | 19 | 中高 | 多轮对话、E5 压缩报告 | 可选（两策略真实对比） |
| **B** 双端记忆 | 记忆领域 + outbox 任务 + 5 条路由 + 记忆 Skill + 两端记忆界面 | `n4-memory-pipeline` | 29 | 高（隐私 + 异步可靠性） | C7、M11、§12.4 记忆条、E5 记忆报告 | 可选（抽取模型选型） |
| **C** 混合检索 | 知识层：`app/knowledge/`、pgvector、索引版本、知识后台 | `n4-hybrid-retrieval` | 26 | 高（原子切换 + 部署约束） | S7 回归、E5 RAG 报告 | 可选（忠实度 / 引用正确率裁判） |
| | | | **74** | | | 默认零费用 |

步骤数按各计划复选框计数（`- [ ]` 与 `- [x]`），**含入口条件**。三份计划原合计 59 步（15 + 21 + 23），
2026-09-27 编组后为 73 步，增量来自 §二列出的缺口补齐；2026-09-28 裁定落地后为 74 步（B 增加 D-N4-2 的契约先行一步），
截至 2026-09-28 已勾选 14 步（见 §七）。

### 与 PRD §15 N4 各条的对应

| PRD N4 条目 | 阶段 |
| --- | --- |
| 顾客记忆（C7）与商家两层记忆（M11），含异步抽取与双重过滤（A6） | B |
| 记忆与个性化 Skill（C2 第 5 个，自 N3 移入） | B Task 6 |
| 上下文压缩两策略对比与生产选定（A5） | A |
| 混合召回 + pgvector + 索引原子切换（A7、M12、§7.6） | C |
| RAG、记忆、压缩三项专项评测报告（E5） | A Task 5、B Task 7、C Task 7，N4 收尾汇总 |

N4 要实现的 v2 路径是**双端记忆 5 条**（`GET/DELETE /shop/memories`、`PUT /shop/memory-preference`、
`GET/DELETE /merchant/memories`），全部在 B。2026-09-28 用 `docs/api.json` 对 PRD §11.2 预跑：PRD 50 条、已导出 44 条、
缺 6 条——即这 5 条加 N5 的 MCP 1 条；N3 的两条只读路径已于 2026-09-27 补齐。**N4 不得提前实现 MCP**。
（同日 PRD 按「W」补入 3 条商家只读路径，PRD 路径总数变为 53 条，这 3 条由 W 实现，不计入 N4。）

难度不是工作量。B 定为「高」，是因为记忆错了会**静默地错**：把助手的推测、顾客的手机号或健康信息写进长期存储，
单测照样全绿；outbox 丢任务或重复执行也不会报错。C 定为「高」，是因为索引切换的「一半新一半旧」只在并发下出现，
而且嵌入模型选型受 Railway 内存与镜像上限硬约束，超限就是部署失败。A 的代码量最小，
却要改 N2 以来最核心的 `runner.py`，并让 v2 第一次拥有多轮上下文（D-N4-1）——回放的旧回答若被当成事实来源，
错误同样是静默的。

---

## 二、为什么按这个方式切，以及编组时补上的缺口

### 与原计划的差异

原三份计划写于 2026-09-21，入口条件互相串联（记忆等 N3 全部完成、压缩等 N3 Skill、检索等 S7）。
按 N3 实际代码核对后：

1. **三个阶段互相没有功能依赖，可以并行。** 记忆、压缩、检索分别落在 `app/memory/`、`agent/loop/compaction/`、
   `app/knowledge/`，只在少数文件上相撞（见 §三并行规则），用串行规则处理即可，不需要排成一条链。
2. **压缩排在 A，是因为它要先解决「v2 根本没有多轮上下文」这个前提**（见下表第一行）。
   A 的 Task 0 一旦按裁定落地，B 的记忆注入与 A 的压缩都要在它之上装配提示词，所以 A、B 对两端 Chat 服务的改动必须串行。
3. **没有单独的 E5 阶段。** 三份专项报告各自在所属阶段产出；汇总与安全集里程碑切换放在 §五「N4 整体完成定义」。

这些都只是计划归属与顺序的变化，**不改 PRD 范围**。需要改 PRD 或契约的地方单列在 §六「裁定记录」。

### 按 N3 实际代码补上的缺口

| 缺口 | 证据 | 补在 |
| --- | --- | --- |
| **v2 Chat 不传历史**：`LoopRequest` 有 `history` 字段，两端 Chat 服务构造请求时都没传，每一轮只有本轮用户消息；工具结果也不落库 | `app/agent/loop/runner.py:159`；`services/v2/merchant_chat.py:144`、`shop_chat.py:154` | **A Task 0**（按 D-N4-1 回放最近 6 轮文字，历史中的数字视为无来源）；**A Task 1 步骤 0**（跨回合锚点只能从 `messages.response_payload` 重建） |
| 记忆计划用 FastAPI `BackgroundTasks` 做异步抽取，与契约冲突 | 后端计划 §6.13：「不得用进程内 `BackgroundTasks` 冒充可靠异步交付」，要求 outbox + `FOR UPDATE SKIP LOCKED` | **B Task 3** 按契约重写（契约为准） |
| 记忆存储缺三处内部状态：outbox 任务表、总结层陈旧标记与依赖、顾客「记住我的偏好」开关 | `app/models/memory_v2.py` 只有三张主表；`rg memory_enabled app` 仅命中 Schema | **B Task 0**（先写 `docs/database.md` 再迁移） |
| §12.4 要求顾客可查看、删除、关闭记忆，计划里没有任何前端任务 | `shop/src/app/[shop_slug]/` 无记忆页；`frontend/src/views/` 无记忆视图 | **B Task 8**（`shop/`）、**B Task 9**（`frontend/`，D-N4-3 裁定做最小版） |
| 计划没有规定访客回合与记忆的关系；访客会话 `buyer_key` 为空，记忆路由拒绝访客 | `app/models/session.py:51`；契约 §8.14.4 `CUSTOMER_BINDING_REQUIRED` | **B Task 3**（D-N4-2：访客回合不抽取，绑定后不补抽）与步骤 1a 契约先行 |
| 注入的记忆既是用户相关内容，又源自顾客原话 | PRD A9（动态内容不打乱稳定前缀）、A11（外部文本围栏） | **B Task 4** 补一条：注入段在稳定前缀之后并围栏 |
| 本地库镜像 `postgres:16-alpine` 不含 pgvector | `docker-compose.yml:3` | **C Task 2 步骤 0**：换镜像后先跑全量回归，再做功能 |
| 检索计划假设的 `retrieve(...)` 函数不存在 | 实际入口 `KnowledgeRetrieval(...).load_domain(category, keywords)`，`app/knowledge/retrieval.py:200`；N3 `search_rules` 在 `tools/merchant/definitions.py:145` 调用 | **C 入口条件**与 Task 4 改为按实际签名锁定 |
| 知识后台要显示索引版本与陈旧状态，但没有字段契约 | 后端计划 §8.6.5 无对应字段 | **C Task 6 步骤 0**：契约先行，优先加在既有 `GET /api/admin/knowledge/tree` |
| S7 回归基准需要写明具体测试 | 2026-09-28 核对：后端 `tests/e2e/test_s7_definitions_loop.py` 与浏览器 `frontend/e2e/n3/merchant-skills.spec.ts` 均已存在并通过 | **C 入口条件**与 Task 7 步骤 1：两层都作为回归基准 |

---

## 三、依赖与执行顺序

### 阶段级依赖

```text
0 入口核对与 N3 收口 ──┬──→ A 上下文与压缩 ──┐
                       ├──→ B 双端记忆 ────────┼──→ N4 收尾（E5 汇总、安全集切到 N4）
                       └──→ C 混合检索 ────────┘
   A ‖ B ‖ C；A 与 B 在两端 Chat 服务上串行，B 与 C 在 Alembic 上串行
```

### 任务级依赖（比阶段级更精确，以此为准）

| 下游 | 上游 | 说明 |
| --- | --- | --- |
| A、B、C 全部 | 阶段 0：N3 整体验收通过 | N4 要改 N3 刚建的 Chat 服务、工具注册表与 `search_rules`；未审先改会让 N3 的复审对不上版本 |
| A Task 0 步骤 2 | A Task 0 步骤 1（PRD A5 与契约 §8.8.3 / §8.9.3 先写入 D-N4-1） | D-N4-1 已于 2026-09-28 裁定，契约先行后再改代码 |
| A Task 1 步骤 0 | A Task 0 | 跨回合锚点来源取决于回放范围 |
| A Task 5 步骤 3（真实对比） | Astra N4-3 审过评测口径；R3 授权 | 指标与样本先固定再跑（清单 N4-3 审查点） |
| B Task 1–7 | B Task 0（迁移） | outbox 与总结陈旧标记是 Task 3、Task 5 的存储前提 |
| B Task 3 步骤 2 | B Task 3 步骤 1a（PRD C7 与 §6.13 先写入 D-N4-2） | 契约先行 |
| B Task 4 注入 | A Task 0（若已开工） | 两者都改两端 Chat 服务的提示词装配，串行；先完成的一方在进度快照写明装配顺序 |
| B Task 6（记忆 Skill） | B Task 4（`recall_preferences` 已注册）；N3 阶段 A 加载器 | Skill 只读，写入不经工具 |
| B Task 8（顾客记忆页） | B Task 4 三条顾客路由已导出 OpenAPI | 前端只从生成类型取字段形状 |
| B Task 9（商家记忆面板） | B Task 5 两条商家路由已导出 | D-N4-3 已裁定做最小版；它是 N4 第一个可砍项，砍掉时删除该 Task 并改 PRD M11 |
| C Task 2 步骤 1 起 | C Task 2 步骤 0（pgvector 镜像）与 C Task 1（关键词基线） | 没有基线就无法证明向量有收益 |
| C Task 3（嵌入选型） | Railway 实例余量数据（用户提供或授权读取） | 不得用本地机器数值替代 |
| C Task 7 步骤 1（S7 回归） | C Task 4 | 混合检索接入后重跑 |
| N4 收尾 | A Task 5、B Task 7、C Task 7 | 三份 E5 报告齐备（真实部分可为「待授权」） |
| B Task 9（商家记忆面板） | W Task 5（新外壳与 token） | 2026-09-28 PRD §15「W」：直接建在新外壳「运营」分组，不按旧样式先做 |
| C Task 6 页面部分 | W Task 7（管理分组与令牌入口） | 知识库已迁入「管理」分组；契约与后端部分不受限 |
| C Task 7 步骤 1 浏览器 S7 | W Task 6 步骤 3 | S7 浏览器用例以 W 改过入口后的版本为回归基准 |
| WS Task 10（动态抽屉「我记住的」） | B Task 8 | WS 迁移 B Task 8 的逻辑与测试；B Task 8 未完成时，由 WS 直接在抽屉里实现，B Task 8 视为由 WS 交付 |
| B Task 4 工具注册 ‖ WS Task 4 | 同改 `tools/customer/__init__.py` | 串行，后到者追加不覆盖 |

### 并行与冲突规则

1. **两端 Chat 服务与 `runner.py`**（`services/v2/shop_chat.py`、`merchant_chat.py`、`agent/loop/runner.py`）：
   A Task 0（历史回放）、A Task 4（压缩接入循环）、B Task 4 / 5（记忆注入）都会改。**一次只让一个执行者改这三份文件**，
   改前在进度快照登记。N2 的 S1、S3 与 N3 的 S2、S4 端到端测试是这三份文件的回归门槛。
2. **Alembic 链**：B Task 0 已新增记忆迁移至 `20260928_0044`（2026-09-28 核对时为唯一 head；后续以 `uv run alembic heads` 实时结果为准）。C Task 2（`vector` 扩展、分块表、索引版本表、
   `knowledge_documents` 源语言与版本）仍需新增迁移。创建前后都确认 `uv run alembic heads` 恰好一个 head，
   不得同时对同一测试库升降级。**C Task 2 步骤 0 换镜像会影响所有人的测试库**，换之前通知 A、B 暂停集成测试。
3. **`docs/api.json` 与生成类型**：B 新增 5 条 v2 路径，C Task 6 改知识后台响应字段，W Task 4 新增 3 条商家只读路径，WS Task 6 改顾客端商品列表参数与订单摘要字段，四者都会重写 `api.json`。
   导出串行化，一次只让一个执行者重写；`frontend/src/api/generated.ts` 与 `shop/src/api/generated.ts` 禁止手改。
4. **`app/core/config.py`**：A 加 `COMPACTION_STRATEGY` / `COMPACTION_TRIGGER_TOKENS`，B 加 `MEMORY_EXTRACTION_*`，
   C 加嵌入模型配置。`Settings` 的启动校验（尤其 `AGENT_LOOP_MAX_LLM_CALLS` 公式）改动后，三方都要跑一遍配置测试。
5. **评测目录**：A 写 `app/eval/datasets/compaction/`，B 写 `memory/`，C 写 `rag/`，互不相交。
   B 的 5 条新路由在 `security/` 登记越权用例（`introduced_in: N4`）。`tests/eval/test_security_gate.py` 的
   `CURRENT_MILESTONE` 目前是 `"N3"`：**N4 收尾再切到 `"N4"`，任何阶段都不得提前改**。
6. **记忆与检索的单向边界**：B 的 `app/memory/` 不得写 `knowledge_documents`，C 的检索不得读记忆表作为团队知识。
   v1 `retrieval.py` 里现有的「记忆兜底」分支（`KnowledgeSource.MEMORY_FALLBACK`）只服务 v1 冻结链路，C 演进时不扩到 v2。
7. **推荐顺序：** 0 →（A Task 0–3 ‖ B Task 0–3 ‖ C Task 1–2）→ B Task 4–6 → A Task 4 →
   （B Task 8、9 ‖ C Task 3–6）→ A Task 5、B Task 7、C Task 7 → N4 收尾。

### 费用点与生产变更点

三份计划的自动化验证全程 Fake LLM，**默认零费用**。本地嵌入模型推理不是 LLM 调用，不计费。
可选费用点共三处，**都不是 N4 开发出口，但决定 PRD §12.5 的三条质量项能否标「通过」**：

| 费用点 | 所在任务 | 未授权时 |
| --- | --- | --- |
| 记忆抽取模型选型评测（≥40 条 × 每条 1 次抽取） | B Task 7 步骤 3–4 | 抽取模型不得宣称已选定；§12.5「敏感信息误写率有量化报告」标「待授权」 |
| 压缩两策略真实对比 | A Task 5 步骤 3 | 默认选 `TOOL_RESULT_PRUNING`，进度快照写明「未经真实模型对比，暂按保守默认」 |
| RAG 忠实度与引用正确率的 LLM 裁判 | C Task 1 步骤 2、C Task 7 步骤 3 | 只报 Recall@k 与 MRR / nDCG；§12.5「引用正确率有可比报告」标「待授权」 |

**建议合并成一次 R3 申请**：三份评测集与口径都经 Astra 审过（批次见分工文件）后，一次列出接口、模型、
每项条数、调用次数与费用上限，由用户一次决定。**泛化的「执行 N4 计划」不构成费用授权。**

生产变更点只有一处：C Task 3 步骤 1 需要 Railway 实例的内存与镜像余量。读取控制台数据须用户提供或单独授权；
若所有候选模型都超出余量，**停下报告**，不自行决定升级 Railway 方案（那是成本决策）。

---

## 四、阶段详情

### 阶段 0 · 入口核对与 N3 收口（2026-09-28 已完成，余两项待用户确认）

- **已完成：**
  1. **N3 整体验收通过**（附条件：三个可选费用点待 R3 人工验收），见 `docs/project-progress.md` 2026-09-28 N3 验收记录：
     F1–F4 整改后复审通过；N3-2 至 N3-5 已勾选（Opus 复审；N3-2、N3-3、N3-5 的实现者非复审会话，N3-4 下载审计为自审）；
     `CURRENT_MILESTONE` 已切到 `"N3"`；
  2. **Astra「入口-N4」有条件通过**（2026-09-28 Opus，见 `plans/2026-09-22-astra-checklist.md` §八）；
  3. **D-N5-2 剩余复核**（2026-09-28）：顾客端 `shop/e2e/conversations-responsive.spec.ts` 在 375px 覆盖新建、浏览、跳转、删除；
     商家端缺「新建对话」按钮的任何测试，已补 `frontend/e2e/ops-assistant-conversation.spec.ts` 一例（变异检验：
     按钮处理器改为空操作时该例失败），Mock E2E 24 passed；§10.6 缺译回退标记由 `shop/src/components/components.test.tsx`
     两例组件测试覆盖，不另补浏览器用例；
  4. **验收复跑**（2026-09-28 本会话）：`ruff`、`mypy app`（267 文件）通过；商家端单测 506 passed、顾客端 93 passed，
     两端 typecheck 与 `codegen:check` 通过。后端全量首轮 3947 passed / 4 skipped / 2 errors，两项 error 均为测试夹具
     `postgres_app` 清表时 `statement timeout`，单独重跑 31 passed；根因是 7 处清表调用中只有 `db_session` 取消了会话超时，
     已统一为 `tests/postgres.py::truncate_all_tables()`。修复后全量复跑结果见 §七。
- **待用户确认（不阻塞 A、B 开工）：**
  - **Railway Postgres 能否启用 `vector` 扩展**——只阻塞 C（混合检索），A、B 可先开工；
  - `plans/2026-09-27-n4-assignment-and-review.md` 的拟定分工。
- **性质：** 审查 + N3 收尾，无 N4 业务代码。

### 阶段 A · 上下文与压缩（`n4-context-compaction`）

- **落点：** 两端 Chat 服务（历史回放）；新建 `agent/loop/compaction/`（`anchors.py`、`pruning.py`、`summarization.py`）；
  `runner.py` 回合前估算 token 并触发压缩；`config.py` 加 `COMPACTION_STRATEGY`、`COMPACTION_TRIGGER_TOKENS`；
  `app/eval/datasets/compaction/`。
- **任务：** **0 多轮历史回放**（D-N4-1：最近 6 轮文字、历史数字无来源）→ 1 锚点（含**步骤 0 跨回合锚点来源**）→ 2 工具结果清理 → 3 摘要压缩 →
  4 接入循环 → 5 E5 压缩评测与生产选型 → 6 自检。
- **难度「中高」的依据：**
  - 压缩是**结构感知**的：工具来源、数据截至时间、草稿版本三项靠「抽出 → 压缩 → 回填」保留，不靠摘要质量；
  - 历史回合的工具结果没有落库，跨回合锚点只能从 `response_payload` 的持久化字段重建，字段不够就得先补契约；
  - 摘要与回放的旧回答都是模型生成内容，下游确定性校验必须拒绝它们作为数字来源（A5、D-N4-1），否则会静默地把模型编的数字当成事实；
  - 改 `runner.py` 不得回归 N2 的五类上限测试、N3 的 Skill 受信通道。
- **出口标准：** Task 0–6 全绿、零费用；第二轮能引用第一轮内容；三项锚点在两种策略下都无损；摘要与历史回答中的数字都被下游拒绝；
  压缩时有 SSE `step` 事件；`COMPACTION_MAX_CALLS` 配错时启动失败；N2 / N3 场景测试零回归；
  生产策略已选定并写入后端计划 §6.12（真实对比或保守默认，二者必居其一且如实记录）；Astra **N4-3** 抽审完成。
- **本阶段不做：** 跨会话长期记忆（B）、提示词缓存命中率（N5）。

### 阶段 B · 双端记忆（`n4-memory-pipeline`）

- **落点：** 新建 `app/memory/`（`extractor.py`、`filters.py`、`customer_store.py`、`merchant_store.py`、`summary_rebuild.py`、
  `pipeline.py`）；`app/jobs/drain_memory_outbox.py`、`purge_expired_customer_memory.py`；工具 `recall_preferences`、
  `recall_merchant_preferences`；`app/skills/customer/memory-personalization/`；路由 `shop_memory.py`、`merchant_memory.py`；
  Task 0 迁移；`shop/src/app/[shop_slug]/memories/`；`frontend/src/views/MerchantMemoryView.vue`（最小版，第一个可砍项）。
- **覆盖路径：** 双端记忆 5 条。
- **任务：** **0 迁移补齐** → **1 双重过滤** → 2 抽取规则 → **3 outbox 异步管线** → 4 顾客记忆 → 5 商家两层记忆 →
  6 记忆与个性化 Skill → 7 E5 记忆评测与抽取模型选型 → **8 顾客端记忆页** → **9 商家端记忆面板（最小版）** → 10 自检。
- **难度「高」的依据：**
  - 抽取器必须**按发言者过滤**：模型提议写入的内容若只来自助手的推测，也不能写（Task 2 第一条测试）；
  - 访客回合不入 outbox、绑定后不补抽（D-N4-2），判定以回合落库时的会话状态为准；
  - 双重过滤的第二道防的是合并、规范化**之后**重新拼出的敏感信息；
  - outbox 要在并发排空、租约过期、重试超限三种情况下都不丢、不重；
  - 180 天过期在**读取路径**判定，「仅被读取不续期」；Cron 迟跑或漏跑都不能让过期记忆被召回；
  - 商家总结层删事实后必须标陈旧并停止注入，重建前不得继续影响回答；
  - 记忆永远不能成为经营数字来源（Task 5 第三条测试）。
- **出口标准：** 5 条路由导出并各有越权用例；§12.4 顾客记忆条目在后端与 `shop` 浏览器两层可验证；
  `rg BackgroundTasks app/memory app/services/v2` 零命中；v1 `merchant_memories` 未被迁入（PRD §14）；
  记忆与个性化 Skill 上线，有 `cases.yaml`，补齐 PRD C2 的第 5 个 Skill；Astra **N4-1、N4-2** 必审通过。
- **本阶段不做：** 迁移 v1 商家记忆、顾客侧总结型画像（D16）、Railway Cron 接线（N5 Task 4）。

### 阶段 C · 混合检索（`n4-hybrid-retrieval`）

- **落点：** 演进 `app/knowledge/retrieval.py`（入口签名不变）；新建 `embedding.py`、`index_versions.py`、`fusion.py`；
  `models/knowledge.py` 与迁移（`vector` 扩展、分块、索引版本、源语言与版本字段）；`app/jobs/build_index.py`；
  `docker-compose.yml` 与集成测试库镜像；知识后台索引状态字段与 `KnowledgeBaseView.vue`；
  `app/eval/datasets/rag/`；`docs/history/eval/rag-baseline.md`、`rag-hybrid.md`。
- **任务：** **1 关键词基线（先量再改）** → **2 索引版本状态机**（含**步骤 0 pgvector 镜像**）→ 3 嵌入模型选型 →
  4 混合召回与 RRF 融合 → 5 重排（须证明收益才保留）→ 6 知识后台接入（含**步骤 0 契约先行**）→
  7 S7 回归与 E5 报告 → 8 自检。
- **难度「高」的依据：**
  - 原子切换 = **单事务改一行「当前生效版本」指针**，不是逐行更新分块；并发查询在切换瞬间只能看到完整的一个版本；
  - 验证阶段 Recall@5 低于上一版 95% 就不切换；无旧版本时降级为关键词检索，并在单来源降级字段上如实标注（R7）；
  - 嵌入模型必须在 backend 进程里（本版无 Worker），选型上限就是 Railway 余量；
  - 重排没有 nDCG@5 ≥ 3 个百分点的提升就**删代码**，不以「以后可能有用」保留。
- **出口标准：** S7 在混合检索下回归通过；混合检索的 Recall@5 与 MRR 优于关键词基线，否则不上线并报告原因；
  `rg "UPDATE knowledge_chunks" app/` 零命中；`docs/deployment.md` 写明 pgvector 启用步骤与镜像 / 内存增量；
  Astra **N4-4** 抽审完成。
- **本阶段不做：** 商家可维护的店铺级知识（M1）、索引构建的 Cron 接线（N5）、付费嵌入 API（除非 Task 3 证明本地不可行且按 R3 授权）。

---

## 五、N4 整体完成定义

N4 完成当且仅当：

1. A、B、C 各自满足出口标准，Astra N4-1、N4-2 必审通过，N4-3、N4-4 抽审完成；
2. 双端记忆 5 条路径全部实现并导出到 `docs/api.json`，无多余路径；新路由越权用例已登记，关键安全集零失败；
   `CURRENT_MILESTONE` 在 N4 收尾时切到 `"N4"`；
3. E5 三份专项报告存在（压缩、记忆、RAG），每份写明哪些是 Fake 结构验证、哪些是真实模型评测；
   未授权的真实部分标「待授权」，**不得把 Fake 结果称为质量已验证**；
4. PRD §12.4 记忆一条、§12.5 压缩 / 记忆 / 混合召回三条逐项有证据或如实标注待授权；
5. 后端全量在 `REQUIRE_INTEGRATION_DB=1`（带 pgvector 的镜像）下零失败、零 skip（本机 Windows 符号链接权限类跳过除外，须逐条列出），
   `ruff check .`、`mypy app` 通过；两个前端单测、`codegen:check`、类型检查与构建通过；
6. 回滚点完好：v1 路由、`graph.py`、v1 知识检索路径仍可用；N2 的 S1、S3 与 N3 的 S2、S4–S7 零回归；
7. D-N4-1 至 D-N4-3 的裁定在 PRD、契约、实现与测试中一致（PRD、契约、计划、索引四层已于 2026-09-28 同步，收尾时复核实现与测试）；
8. `docs/project-progress.md`、`docs/project-navigation.md`、`docs/database.md`、`docs/deployment.md` 已更新。

**N4 不包含：** MCP、三级预算、看板、Cron 接线、Railway 部署、全量评测报告（N5）。

---

## 六、裁定记录（2026-09-28 用户采纳推荐方案）

原「待裁定」三项已由用户裁定，**PRD 与契约已于 2026-09-28 同步**（PRD A5、C7、M11、§15 N4；
后端计划 §6.10、§6.12、§6.13、§8.8.3、§8.9.3）。本节只记录结论与落点，权威定义以 PRD 与契约为准。

| 编号 | 问题 | 裁定 | 落点（先改 PRD / 契约，再改代码） |
| --- | --- | --- | --- |
| **D-N4-1** | v2 Chat 是否回放多轮历史 | **回放同一会话最近 6 轮的用户与助手文字**（`CHAT_HISTORY_MAX_TURNS`，E5 后可调）；顾客原话照常围栏；不回放工具结果与推理内容；**回放的助手旧回答属模型生成内容，其中的数字视为无来源** | PRD A5；契约 §8.8.3 / §8.9.3、§6.10；`n4-context-compaction` Task 0 |
| **D-N4-2** | 访客对话绑定后是否补抽记忆 | **不补抽**：访客回合不追加 outbox；只有绑定之后的回合进入抽取；记忆关闭期间的回合同样不抽取 | PRD C7；后端计划 §6.13；`n4-memory-pipeline` Task 3（步骤 1a 契约先行） |
| **D-N4-3** | N4 是否做商家端记忆面板 | **做最小版**：事实层列表与逐条删除，总结层只读；**列为 N4 第一个可砍项**，砍掉时改 PRD M11 为「本版仅 API」 | `n4-memory-pipeline` Task 9；PRD 无需改（除非被砍） |

## 七、状态快照与维护规则

- 截至 **2026-10-02（N4 收尾）**：三份计划 **74 / 74**（A 19、B 29、C 26），`CURRENT_MILESTONE = "N4"`；Astra N4-1、N4-2 必审通过，
  N4-3 锚点部分通过、③压缩评测口径冻结后真实重跑待 R3，N4-4 有条件通过并整改；§五完成定义第 3、4 项中未授权的真实部分如实标「待授权」
  （压缩冻结重跑、混合检索裁判复测约 128 次、记忆抽取复测约 40 次，均 `deepseek-flash`）。后端全量 4405 passed / 4 skipped / 0 failed。
  D-N4-1～3 在 PRD、契约、实现与测试中一致。详见 `docs/project-progress.md` 2026-10-02 快照；N5 见 `plans/2026-09-27-n5-module-roadmap.md`。
- 截至 2026-09-28（历史）：N4 已开工，三份计划 14 / 74——入口条件 10 步（入口-N4 核对时勾选）、契约先行 3 步，
  以及 A Task 0（多轮历史回放）实现完成。阶段 0 已完成（见 §四）；
  修复清表夹具后的后端全量已闭合：本会话与 Codex 各自复跑均为 **3953 passed / 4 skipped / 0 failed / 0 errors**
  （含 Codex 同期的满减券护栏修复，见 `docs/project-progress.md` 2026-09-28 首条）。
  待用户确认：Railway Postgres 能否启用 `vector`（只阻塞 C）、N4 分工（`plans/2026-09-27-n4-assignment-and-review.md`）。
- 阶段完成后：先在该阶段的实施计划里勾选步骤，再更新 `docs/project-progress.md`，最后回到本文件更新 §一。
  **不要只改本文件。**
- 某阶段计划新增或删减步骤时，同步本文件 §一 的步骤数。
