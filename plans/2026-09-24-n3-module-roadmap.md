# N3 阶段总览：A / B / C 三阶段的划分、依赖、难度与出口标准

> **本文件是 N3 的总览，不是实施计划。** 它只回答四件事：N3 拆成哪几个阶段、每个阶段落在框架的哪一层、
> 难点在哪、怎样算完成。逐步骤的做法在各阶段自己的实施计划里；本文件与它们冲突时以实施计划为准，
> 并回头修正本文件。
> **进度只在 `docs/project-progress.md` 维护**；下文「状态快照」标注了日期，过期以进度快照为准。
> **本文件不含任何 Git 提交步骤**（R2），也不触发任何 LLM 调用（R3）。
> 写法仿照 `plans/2026-09-22-n2-module-roadmap.md`。

**目标：** 让 N3（PRD §15「扩展 Skill」）的全部工作有一张可核对的地图：按依赖切成 A、B、C 三个阶段，
写清每阶段的范围、撞点与出口标准，并把 2026-09-21 预写的三份 N3 计划按**N2 实际落地的接口**重新编组。

**规格来源：** `docs/PRD.md` §15 N3、A4、C2、C6、C8、M2–M9、§7.2、S2、S4–S7；
`docs/backend-development-plan.md` §5.6、§6.9–§6.11、§8.11–§8.13；`AGENTS.md` R2–R5、R7、R8；
审查点见 `plans/2026-09-22-astra-checklist.md` §六。

---

## 一、总览表

| 阶段 | 框架层 | 实施计划（`plans/2026-09-21-*.md`） | 步骤 | 难度 | 收口场景 | 需 R3 授权 |
| --- | --- | --- | --- | --- | --- | --- |
| **0** 入口核对与 N2 收口 | 审查 | Astra「入口-N3」；N2 整改独立复审与 N2-1～N2-8 | — | — | — | 否 |
| **A** Skill 底座（✅ 完成，N3-1 2026-09-25 通过；20/20） | Agent 内核：`app/skills/`、`agent/loop/`、`services/v2/draft_apply.py` | `n3-skill-loader` | 20 | 中高 | — | 否 |
| **B** 售后闭环与顾客 Skill（✅ 完成，N3-2/3/4 2026-09-28 复审通过；41/41） | 售后领域 + 双端售后路由 + 顾客 Skill + 商家客服回复 Skill + 顾客信号 | `n3-customer-skills-and-after-sales` | 41 | 高（状态机 + 两阶段确认） | **S4** | 否（摘要真实生成另需 R3） |
| **C** 商家经营 Skill（✅ 完成，N3-4 2026-09-28 复审通过；34/34；S2/S5/S6/S7 后端与浏览器两层通过） | 6 个商家 Skill 的工具与服务 + 商家工作台补全 | `n3-merchant-skills` | 34 | 高（口径与护栏） | **S2、S5、S6、S7** | 否（简报真实生成另需 R3） |
| | | | **95** | | | 默认零费用 |

步骤数按各计划 `- [ ]` 复选框计数，**含入口条件**，排除页眉里说明用的 `` `- [ ]` ``。
三份计划原合计 67 步（10 + 26 + 31），本次编组后为 95 步，增量来自 §二列出的缺口补齐。

### 与 PRD §15 N3 各条的对应

| PRD N3 条目 | 阶段 |
| --- | --- |
| Skill 按需加载与冲突测试（A4） | A |
| 顾客端 Skill 完整化（C2）：搜索发现、选购研究、目标规划、售后服务 4 个 | B |
| 售后闭环（C6、S4）；商家售后决定统一走草稿审批（M9） | B |
| 商家·客服回复与信号（M9） | B（客服回复、售后类信号）+ C（内容缺口信号） |
| 商家·完整每日简报（M2）、归因与三指标口径（M3）、商品内容（M4）、促销（M6）、导出（M7）、口径问答（M8） | C |
| （PRD §15 N2 遗留）v2 运营助手页与 v1 分析助手是否合并，「在 N3 商家 Skill 迁完后另行评审」 | C 收尾 |

2026-09-24 划分阶段时，N3 尚缺 **9 条** v2 路径（当时用 `docs/api.json` 对 PRD §11.2 脚本比对得 8 条，
同日补入顾客补充说明 1 条）：售后 6 条（B）、顾客信号 2 条（B）、
`POST /merchant/briefs/daily/current/regenerate`（C）。2026-09-26 阶段 B 已实现并导出前 8 条。
其余未实现的 6 条（双端记忆 5 条、MCP 1 条）归 N4、N5，**N3 不得提前实现**。

难度不是工作量。B 定为「高」是因为售后状态机、退款上限与顾客两阶段确认**错了会静默地错**——
单测全绿时仍可能多退款或让聊天代替顾客确认；C 定为「高」是因为口径、护栏、导出范围错了就是对商家说假数字或放行越界调价。
A 的代码量最小，但 B、C 的 11 个 Skill 与 4 类新草稿都站在它上面。

---

## 二、为什么按这个方式切，以及编组时补上的缺口

### 与原计划的差异

原三份计划写于 2026-09-21，是「加载器 → 顾客 Skill 与售后 → 商家 7 个 Skill」一份对一份的顺序。
按 N2 实际代码核对后调整两处归属：

1. **商家「客服回复」Skill、售后类顾客信号与 S4 端到端从 C 移到 B。**
   原商家计划整份的入口条件写着「顾客计划 Task 4、Task 8 已完成」，但 7 个 Skill 里只有客服回复真正依赖售后状态机；
   其余 6 个被无谓地卡住（与 N2 草稿计划曾经的问题同类）。移动后：
   B 一个阶段就能把 S4 从顾客发起一路做到退款记录，C 的业绩、定价、导出、口径四项可以与 B 并行。
2. **内容缺口信号（`CONTENT_GAP`）留在 C。** 它的事实源是商品内容完整度规则（契约 §8.12，D11③④），
   与商品内容 Skill 同一批代码；B 只建顾客信号的查询服务、两条路由与 `list_signals` 工具，C 在其上追加这一类。

这两项都只是计划归属变化，**不改 PRD 范围、不改契约**。

### 按 N2 实际代码补上的缺口

| 缺口 | 证据 | 补在 |
| --- | --- | --- |
| 草稿应用事务写死只支持补货：`DraftApplyService.apply()` 直接调 `_apply_restock()`，其余种类抛 `NotImplementedError` | `backend/app/services/v2/draft_apply.py:98`、`:157` | **A Task 5**：改为按 `DraftKind` 分派处理器；B、C 各自注册 `AFTER_SALE_DECISION` 与 `CONTENT_CHANGE` / `PRICE_CHANGE` / `COUPON` |
| 工具循环没有 Skill 入口：`LoopRequest` 只有固定 `system_prompt`，**所有工具结果一律经 `fence()` 围栏** | `backend/app/agent/loop/runner.py:343`；两端 `SYSTEM_PROMPT` 为常量 | **A Task 6**：Skill 索引进稳定前缀；`load_skill` 结果走受信通道——§6.11 规定 Skill 正文不需要围栏，但只能由注册表产生 |
| 两端 Chat 服务还没接 Skill | `services/v2/shop_chat.py:36`、`merchant_chat.py:32` | **A Task 6** |
| 商品内容批量起草要用 `batch_id` 分组勾选批准，但 `drafts` 表、契约 §8.13 与 `DraftSummary` 都没有该字段 | `app/models/drafts.py`；`rg batch_id` 在 docs 与 schemas 零命中 | **C Task 3 步骤 0**：先补契约 §8.13 → Schema → 迁移，再写实现（契约先行） |
| 顾客界面确认证据还没有第二种用途：`approval_evidence.py` 只有 `draft-approval:v1`，结账未用确认证据 | `app/services/v2/approval_evidence.py:33` | **B Task 5**：复用同一验证器，新增用途 `customer-confirmation:v1` |
| 售后各跳由谁触发 PRD 未写：「已退款 / 已拒绝 → 关闭」无触发方；「待顾客补充信息 → 待商家处理」连顾客端接口都没有 | `docs/project-progress.md`「待决」；PRD §11.2.2 无补充信息路径 | **2026-09-24 用户裁定，已写入 PRD §7.2 / C6 / §11.2.2 与契约 §8.11**；B Task 4、7、8 据此重写 |

---

## 三、依赖与执行顺序

### 阶段级依赖

```text
0 入口核对 ──→ A Skill 底座 ──┬──→ B 售后闭环与顾客 Skill（含 S4）──┐
                              │                                    ├──→ C Task 2（完整简报）、C Task 3 步骤 3（S2）
                              └──→ C Task 0、1、4、5、6 ───────────┘      C Task 8（工作台）、C Task 9（收尾）
   B ‖ C：C 的业绩洞察、定价促销、导出、口径问答与 B 并行
```

### 任务级依赖（比阶段级更精确，以此为准）

| 下游 | 上游 | 说明 |
| --- | --- | --- |
| A 全部 | N2 验收通过（整改独立复审、Astra N2-1～N2-8） | A 要改 `runner.py` 与 `draft_apply.py`，这两个文件正是 N2-1、N2-3 的审查对象；未审先改会让审查对不上版本 |
| B 全部、C 全部 | A Task 1–6 | Skill 正文要能加载；新草稿种类要能注册处理器 |
| B Task 8（`AFTER_SALE_DECISION` 处理器） | A Task 5 | 挂到分派表上 |
| B Task 11（售后类信号） | B Task 5（售后单能被创建） | 信号是售后记录的派生提醒 |
| B Task 13（S4 端到端） | B Task 5、8、10 | 顾客发起 → 商家起草 → 审批 → 寄回 → 收货 → 退款 |
| C Task 2（完整简报） | B Task 11（信号查询服务） | 简报的顾客信号区只读聚合结果 |
| C Task 3 步骤 3（S2） | B Task 11；C Task 7（内容缺口信号） | 信号基础设施在 B，`CONTENT_GAP` 在 C |
| C Task 8（工作台） | B Task 12（售后与信号区域已由 B 完成） | C 只补经营、商品与库存两块 |
| C Task 9 步骤 2（两页合并评审） | C Task 1–6 | PRD §15 N2：商家 Skill 迁完后才评审 |

### 并行与冲突规则

1. **`docs/api.json` 与两份生成类型是 B、C 的共同撞点**：导出串行化，一次只让一个执行者重写；
   `frontend/src/api/generated.ts` 与 `shop/src/api/generated.ts` 禁止手改。
2. **Alembic 链**：当前唯一 head `20260923_0034`。N3 已知只有 C Task 3 需要新增迁移（`drafts.batch_id`）；
   B 若在执行中发现需要迁移，同样先确认 `uv run alembic heads` 恰好一个 head，不得与 C 同时升降级同一测试库。
3. **草稿分派表**（A Task 5 产出）：B 注册 `AFTER_SALE_DECISION`，C 注册 `CONTENT_CHANGE`、`PRICE_CHANGE`、`COUPON`；
   任一种类只能有一个处理器，由分派表的启动自检拦截重复注册。
4. **工具注册表**：B、C 新增的工具都走 `build_tool_registry()` 自检；写能力一律 `MERCHANT_DRAFT` 或
   `CUSTOMER_CONFIRMATION`，不得为赶进度注册 `CUSTOMER_DIRECT` 写工具。
5. **Skill 目录**：B 写 `app/skills/customer/` 4 个 + `app/skills/merchant/customer-service-replies/`；
   C 写其余 6 个商家 Skill。两个阶段都**不改 A 的加载器**；要改先回 A 的计划。
6. **安全集** `app/eval/datasets/security/`：B、C 登记新路由的越权用例（`introduced_in: N3`）；
   `CURRENT_MILESTONE` 只在 N3 收尾改，**不得由任一阶段提前改**。
7. **推荐顺序：** 0 → A → B ‖（C Task 0、1、4、5、6）→ C Task 7、2、3 → C Task 8、9 → N3 收尾。

### 费用点

三份计划全程 Fake LLM，**默认零费用**。可选费用点只有两个，都不属于 N3 出口，执行前须按 R3 单独说明并取得同意：

- B Task 6 随单对话摘要的**真实生成**；
- C Task 2 完整每日简报的**真实生成**（定时预生成的 Cron 接线归 N5）。

未授权时保持「待人工验收」，**不得把 Fake LLM 结果说成摘要或简报质量已验证**。

---

## 四、阶段详情

### 阶段 0 · 入口核对与 N2 收口

- **内容：**
  1. N2 收口：整改计划 Task 5 的独立复审、Astra N2-1～N2-8 与前置 N1 待审项（见 `docs/project-progress.md` 顶部）；
  2. Astra「入口-N3」：逐份核对三份 N3 计划的入口条件与 N2 实际接口，发现不一致按 PRD → 契约 → 计划 → 索引修正；
- **性质：** 只读审查 + 必要的计划修正，无业务代码。

### 阶段 A · Skill 底座（`n3-skill-loader`）

- **落点：** 新建 `backend/app/skills/`（`loader.py`、`registry.py`、`tool.py`、两个样例 Skill）；
  改 `agent/loop/runner.py`（受信 Skill 通道、单回合加载上限）、`services/v2/shop_chat.py` / `merchant_chat.py`（索引进前缀）、
  `services/v2/draft_apply.py`（按种类分派）；`config.py` 加 `SKILL_MAX_CHARS`、`SKILL_MAX_PER_TURN`。
- **任务：** 1 解析与校验 → 2 白名单目录与路径逃逸 → 3 索引与按需加载 → 4 冲突与回归框架 →
  **5 草稿应用按种类分派** → **6 `load_skill` 受信通道与两端 Chat 接线** → 7 自检。
- **难度「中高」的依据：**
  - 路径逃逸与不安全 YAML 是注入面（Astra N3-1 必审）；
  - `load_skill` 的结果**不能**像其他工具结果那样围栏，否则 Skill 被当成数据；但**只有**注册表产出的 Skill 能绕过围栏，
    其他工具返回的文本即便伪造 `<skill>` 标记也必须照常围栏；
  - 分派重构不得改变补货草稿的任何行为，N2 的审批测试要原样通过。
- **出口标准：** Task 1–7 全绿、零费用；N2 草稿审批与 S3 测试零回归；两端 Chat 在不加载 Skill 时行为与 N2 相同；
  Astra **N3-1** 必审通过、**N3-5** 抽审完成。
- **本阶段不做：** 任何业务 Skill 正文、任何新草稿种类的处理器。

### 阶段 B · 售后闭环与顾客 Skill（`n3-customer-skills-and-after-sales`）

- **落点：** `app/skills/customer/` 4 个 Skill、`app/skills/merchant/customer-service-replies/`；
  `services/v2/after_sale_eligibility.py`、`refund_calc.py`、`after_sale_machine.py`、`conversation_summary.py`、
  `customer_signals.py`、`draft_handlers/after_sale_decision.py`；`tools/customer/after_sale.py`、`tools/merchant/after_sale.py`、
  `tools/merchant/signals.py`；路由 `shop_after_sales.py`、`merchant_after_sales.py`、`merchant_signals.py`；
  `shop/src/app/[shop_slug]/after-sales/`；`frontend/src/views/AfterSalesView.vue`、`SignalsView.vue`；
  `tests/e2e/test_s4_after_sale_loop.py`。
- **覆盖路径：** 售后 6 条（含顾客补充说明）+ 顾客信号 2 条。
- **任务：** 1 四个顾客 Skill → 2 发起条件 → 3 退款计算 → **4 售后状态机** → **5 顾客两阶段确认** → 6 随单摘要 →
  7 双端售后只读路由 → 8 售后决定草稿处理器 → 9 顾客售后页 → **10 商家客服回复 Skill** → 11 售后类顾客信号 →
  12 商家售后与信号界面 → **13 S4 端到端** → 14 自检。
- **难度「高」的依据：** 状态机按类型限定迁移并有 47 次补充信息上限；退款只按快照、逐行舍入、单行累计封顶；
  确认令牌 Agent 拿不到；商家侧永远只有 `buyer_alias`；商家详情读取先写查看审计。
- **出口标准：** S4 后端端到端通过；状态机非法迁移用补集参数化测试；8 条路由导出并有越权安全用例；
  Astra **N3-2、N3-3** 必审通过，**N3-4** 中客服回复部分通过。
- **本阶段不做：** 记忆与个性化 Skill（N4）、换货（D15）、真实退款渠道、内容缺口信号（C）。

### 阶段 C · 商家经营 Skill（`n3-merchant-skills`）

- **落点：** `app/skills/merchant/` 6 个 Skill；`tools/merchant/`（`metrics.py`、`brief.py`、`content.py`、`pricing.py`、
  `export.py`、`definitions.py`）；`services/v2/attribution.py`、`daily_brief.py` 扩展、`content_completeness.py`、
  `draft_handlers/content_change.py`、`price_change.py`、`coupon.py`；`merchant_brief.py` 新增重新生成路由；
  `drafts.batch_id` 迁移；Vue 经营区与商品库存区；`tests/e2e/test_s2_*`、`test_s5_*`、`test_s6_*`、`test_s7_*`。
- **任务：** 0 Skill 文件 → 1 业绩洞察与归因 → 2 完整每日简报 → 3 商品内容（含 `batch_id` 契约先行）→ 4 定价与促销 →
  5 明细导出 → 6 规则与指标口径 → 7 内容缺口信号 → 8 商家工作台补全 → 9 自检与两页合并评审。
- **难度「高」的依据：** 模型不写 SQL、不定口径、不产生图表点（R4）；等长可比周期与实时/汇总边界不重不漏；
  护栏（实付不低于原价 80%、无最低售价不放行调价）在应用时复检；导出明细不进模型上下文。
- **出口标准：** S2、S5、S6、S7 后端与浏览器各自通过（S7 用关键词检索跑通，N4 回归）；v1 服务复用零回归；
  Astra **N3-4** 中导出与口径部分通过。
- **本阶段不做：** 营销活动（D4）、商家两层记忆（N4）、混合检索（N4）、简报 Cron（N5）、异步导出。

---

## 五、N3 整体完成定义

N3 完成当且仅当：

1. A、B、C 各自满足出口标准，Astra N3-1～N3-4 必审通过、N3-5 抽审完成；
2. S2、S4、S5、S6、S7 在后端端到端与浏览器 E2E 两层通过（S4 浏览器层覆盖顾客发起与商家审批两端）；
3. 顾客 4 个 + 商家 7 个 Skill 共 11 个，每个都有 `cases.yaml`（正确触发 ×2、误触发 ×1、边界反例 ×1）并通过；C Task 0 的跨阶段冲突用例通过；
4. 上述 9 条 N3 路径全部实现并导出到 `docs/api.json`，无多余路径；新路由的越权用例已登记，关键安全集零失败；
5. 后端全量在 `REQUIRE_INTEGRATION_DB=1` 下零失败、零 skip，`ruff check .`、`mypy app` 通过；两个前端单测、
   `codegen:check`、类型检查与构建通过；
6. v1 回滚点完好：v1 路由、`graph.py`、v1 分析助手页仍可用；N2 的 S1、S3 零回归；
7. 两个可选费用点要么按授权执行并记录，要么标「待人工验收」；
8. `docs/project-progress.md`、`docs/project-navigation.md` 已更新。

**N3 不包含：** 记忆与个性化 Skill、双端记忆路由、上下文压缩、混合召回（N4）；MCP、Cron 接线、Railway 部署（N5）。

---

## 六、状态快照与维护规则

- 截至 **2026-09-28**：**N3 整体验收通过（附条件：三个可选费用点待 R3 人工验收）**。A 20/20、B 41/41、C 34/34；
  N3-1～N3-5 全部通过；§五 八条逐条证据见 `docs/project-progress.md` 2026-09-28 N3 验收记录。
- 截至 **2026-09-24 晚**：N2 独立复审已完成；**阶段 A 实现完成**（19 / 20，唯一未勾的是入口条件「Astra 入口-N3」，用户指示直接开工），待 Astra **N3-1** 必审、**N3-5** 抽审；B、C 未开始。总勾选 20 / 95（A 19 + B 入口条件「触发方已裁定」1）。
- 阶段完成后：先在该阶段的实施计划里勾选步骤，再更新 `docs/project-progress.md`，最后回到本文件更新 §一。
  **不要只改本文件。**
- 某阶段计划新增或删减步骤时，同步本文件 §一 的步骤数。
