# 项目进度快照

> **2026-09-27 当前状态：N3 阶段 C 开发与 S2/S5/S6/S7 双层场景已收口，等待 N3-4 独立复审及真实模型人工质量验收。**
> 商家只读商品内容/优惠券游标接口已按 PRD → §8 契约 → OpenAPI/双端生成类型接入；`/inventory` 展示
> 内容缺口、库存告警和券状态/优惠幅度。净成交额类目归因已修正为后端按类目查询毛成交额与退款额再相减，
> 退款与商品类目的关联路径加了租户条件。正式指标口径工具返回资产更新时间作为定义版本。
> S2、S5、S6、S7 的后端真实 PostgreSQL + Fake LLM 场景、双端浏览器工作台场景均已通过；
> 浏览器套件为 `frontend/npm run test:e2e:n3`（4 passed），使用可清空的一次性库，不调用真实 LLM。
> 前端单测 506 passed、类型检查/lint/codegen 检查/构建通过；后端 Ruff/mypy 通过，
> 后端全量集成套件正在重跑（首次在第 69 项清表遇到数据库 `statement timeout`，该项单独重跑通过）。
> **下一步：** 记录全量回归结果，完成 N3-4 独立复审；简报真实生成与真实模型意图/措辞质量仍须另按 R3 取得费用授权。
> 未执行 Git 发布操作，也未修改只读参考目录。

> **2026-09-27：N4、N5 阶段划分与计划编组完成（纯文档，未改代码）。**
> 新增 `plans/2026-09-27-n4-module-roadmap.md`（A 上下文与压缩 / B 双端记忆 / C 混合检索，共 73 步）、
> `plans/2026-09-27-n5-module-roadmap.md`（A MCP / B 预算与可观测 / C Cron 与部署 / D 全量评测与收口，共 68 步），
> 以及两份分工与 Astra 审查排期（分工为拟定方案，待用户确认）。六份 2026-09-21 预写计划已按实际代码回改：
> **记忆异步抽取改为 outbox**（原计划的 `BackgroundTasks` 与后端计划 §6.13 冲突）；补记忆迁移与两端记忆界面（PRD §12.4）；
> 压缩计划补「多轮历史回放」前置（**v2 两端 Chat 目前不传 `history`**）；检索计划补 pgvector 镜像（本地为 `postgres:16-alpine`）
> 与实际入口 `KnowledgeRetrieval.load_domain`；MCP 计划补 `attribute_change` 缺 `MCP_READONLY` 角色；
> 预算计划记录看板页已随两页合并下线、Cron 配置实有 3 份及 nonce 清理任务缺失；收口计划补录后续 5 项裁定与 E2E 缺口复核。
> **待用户裁定**：D-N4-1 多轮历史回放、D-N4-2 访客对话是否补抽取记忆、D-N4-3 商家记忆面板；
> D-N5-1 看板载体（PRD §14「Chat BI 运维看板保留并扩展」与 09-27 下线冲突）、D-N5-2 已删 E2E 的处置、D-N5-3 MCP 是否提前。
> **前置链不变**：N3 仍未通过整体验收（F1–F4 待复审、Astra N3-2 至 N3-4、S5–S7 工作台 E2E、2 条 N3 路径），N4 不开工。
> 未调用 LLM，未执行 Git 操作。

> **2026-09-27：N3 阶段 C Task 9 步骤 2 用户裁定「选项 C」执行完成——图表可视化补齐
> + v1/v2 两页合并，阶段 C 主体收口。**
> **裁定**：三选项中选 C——先补 `query_metrics`/`attribute_change` 的 ECharts 趋势可视化，
> 再执行两页合并。
> **图表可视化**（契约先行）：`docs/PRD.md` §15 N2 追加裁定记录；
> `docs/backend-development-plan.md` 新增 §8.7.11（`MerchantChatResponse.visualization`
> 完整契约）；后端新增 `AttributionService.query_metrics_series()`（逐日序列+缺失日补零，
> `net_gmv` 逐日相减）、`app/services/v2/visualization.py`（折线/柱图构造）、
> `ToolOutput`/`ToolResult.chart_data` 字段（模型不可见，`_tool_message()` 序列化白名单
> 天然排除，R4：模型不产生也不"看到"图表数据点）、`query_metrics`/`attribute_change`
> 工具接入、`MerchantChatResponse.visualization` 字段 + R7 降级校验（降级轮次强制
> `enabled=false`）；前端复用 v1 既有 `MetricChartPanel.vue`（props 收窄为纯 `chart`）。
> 全量后端回归 **3927 passed，4 skipped**（跳过均为环境限制，与本次改动无关）；前端
> `npm run test` 504 passed，`vue-tsc`/`eslint`/`build`/`codegen:check` 全绿。
> **两页合并**：`/` 路由从 v1 `AssistantView` 切到 v2 `OpsAssistantView`；v1 前端专属文件
> 下线（`AssistantView.vue`/`OpsDashboardView.vue` 及其 Chat BI 组件、Store、API Adapter，
> 约 30 个文件）；v1 **后端**（`graph.py` 冻结基线、`POST /api/chat` 等）不受影响，按
> AGENTS.md 既有约束继续保留为评测基线。
> **过程中发现并修复两处评审遗漏的功能缺口**（均属于"v2 已达到或超过 v1"这个评审结论
> 未覆盖到的维度，不是本次引入的新回归）：① 商家切换器（`MerchantSwitcher.vue`）一度
> 被误判为 v1 专属死代码删除，实为必需的身份切换入口，已恢复并接入 `OpsAssistantView`，
> 补了"冷启动无预置身份仍能自愈"的专项测试；② 语言切换器（`LanguageSwitcher.vue`）
> 此前只有 v1 `AssistantView` 挂载，合并后 `/` 曾短暂失去语言切换入口，已补齐；同时
> 补齐了合并后缺失的知识库导航入口（`/knowledge-base` 曾变成孤儿路由）。
> **E2E 测试处理**（用户逐项裁定）：`assistant.spec.ts`/`isolation.spec.ts`/
> `responsive.spec.ts`/`first-paint.spec.ts` 改写为验证 v2 页面等价场景（用
> `page.route` 直接 mock 两个 v2 端点）；`conversation.spec.ts`（13例）、
> `ops-dashboard.spec.ts`、`localization.spec.ts`（725行）、`real-api/analytics.spec.ts`
> （8例）整份删除，登记为验证缺口——v2 层没有等价于 v1 Mock 传输层的细粒度 fixture
> 打桩基础设施，重建这些场景需要先补基础设施，超出本次范围。Mock E2E 套件（16例）
> 全部通过；顺手修复了 `playwright.config.ts` 遗漏 `**/s4/**` 的 `testIgnore`（既有配置
> 疏漏，与本次改动无关）。S3 真实后端套件因本地 PostgreSQL 端口 55451 未起服务无法验证
> （环境限制，非代码问题）。
> **文档同步**：`docs/PRD.md` §15、`docs/backend-development-plan.md` §6.9/§8.7.11、
> `docs/project-navigation.md`（页面/组件/Store/API 清单同步下线与新增，E2E 验证缺口
> 登记）已同步；SDD 台账 `.superpowers/sdd/2026-09-21-n3-merchant-skills/progress.md`
> 已记录图表可视化部分，两页合并部分待补。
> 全程 Fake LLM，零真实调用（R3）；未做任何 Git 提交/发布操作（R2）。
> **仍待处理**：`api/chat.ts` 内部死代码（`submitFeedback` 等，仅整文件级已清理，
> 函数级死代码留待后续）；v2 层 fetch Mock 基础设施缺失（阻塞前述 E2E 缺口的补齐）。

> **2026-09-26：N3 阶段 C【商家经营 Skill】Task 8（前端补全，部分）与 Task 9
> 步骤 2（v1/v2 两页合并评审）推进完成。**
> **Task 8**：按优先级完成两个子任务——① 审批界面支持按 `batch_id` 分组 + 勾选批准
> （新页面 `ApprovalListView.vue`，此前审批页完全孤立无入口）；② 完整简报展示扩展
> （`TodayView.vue` 加"重新生成"按钮，冷却期按与后端一致的规则自动禁用/启用）。
> 另两个子任务（商品与库存区的内容完整度/促销与券展示、经营图表区）**如实登记为
> 受阻**：均缺少对应的商家端 v2 只读 REST 端点（`get_product_content`、
> `list_coupons`、`query_metrics`、`attribute_change` 目前都只是聊天工具），
> 新建这类端点超出前端补全本身范围；经营图表区还与两页合并评审结论直接相关，
> 现在新建可能与评审结果冲突，留待裁定后处理。
> **Task 9 步骤 2**：产出评审文档
> `docs/specs/2026-09-26-merchant-assistant-page-merge-review.md`（同步发布为
> Claude Docs 供在线批注），逐项对照 v1 分析助手与 v2 运营助手的能力覆盖：
> v2 在导出/反馈/简报/审批四项已超过或等于 v1，规则问答对等，**唯一明确的实质性
> 差距是 v2 缺少 ECharts 图表可视化**（分类下钻需要一次参数核实但可能只是接口
> 传参问题）。给出三个选项（现在合并/现在合并接受过渡态/先补图表再评审）交用户
> 裁定，**未执行任何合并**。
> **验证**：前端全量 `npm run test` 690 passed（66 个测试文件）；`vue-tsc --noEmit`
> 0 错误；`eslint`（改动文件）0 错误；`npm run build` 成功。全程 Fake LLM，
> 未做任何 Git 操作。详见 `.superpowers/sdd/2026-09-21-n3-merchant-skills/progress.md`。

> **2026-09-26：N3 独立审查发现的 F1–F4 已整改，N3 整体仍待验收。**
> 已补导出日期/行数硬限制与超限拒绝、售后聊天预览历史退款扣减、已消费确认令牌的契约错误，
> 并使 44 条 Skill 用例及 27 个真实 Skill 组合可在 Fake LLM 工具循环中执行。
> 定向回归 **241 passed / 3 skipped / 0 failed**，`ruff check .` 与 `mypy app` 通过；
> 跳过项均为本机 Windows 符号链接权限。详细问题、修复与限制见
> `plans/2026-09-26-n3-independent-review.md`。下一步仍是阶段 C 出口、浏览器场景及
> 真实模型意图质量验收；真实调用须另按 R3 授权。未调用真实 LLM，未执行 Git 发布操作。

> **2026-09-26：N3 阶段 C【商家经营 Skill】Task 3（全部步骤）与 Task 7（内容缺口信号）
> 补做完成，收口 S2 场景。**
> 前置条件（阶段 B Task 11 顾客信号服务）已就绪后接续开工。交付：`derive_content_gap_signal()`
> （顾客信号服务追加 `CONTENT_GAP` 分支）、顾客工具 `get_product_attribute`（触发信号计数）、
> `tests/e2e/test_s2_content_gap_loop.py`（S2 端到端：顾客问缺失属性 → 信号计数 → 商家起草
> 补充 → 审批应用 → 顾客端再问能回答 → 信号不再计数）。
> **过程中发现并修复两个跨任务真实缺陷**（写 S2 端到端测试首次跑通"起草-应用-顾客再读"
> 完整链路时暴露，此前无测试触及）：`content_completeness.missing_required_attributes()`
> 把 `Product.attributes`（Mapping 结构）当裸字符串处理，直接报错；
> `ContentChangeHandler.apply()` 把商家起草应用后的属性值写成裸字符串，丢失 Mapping 结构，
> 导致该属性此后被顾客端与本地化服务同时误判为"缺失"。经用户裁定统一为 Mapping 结构
> （`source`/`source_type` 两键并存，分别服务本地化判断与 D11 可信来源分类），两处已修复
> 并补充回归测试。按用户裁定，"商家简报出现该信号"这一断言改用信号列表 API 验证
> （完整简报正文渲染属于本计划 Task 2，未做，工作量独立且含 R3 相关真实调用开关）。
> **验证**：`test_s2_content_gap_loop.py` 1 passed；关联回归（e2e + 内容变更草稿 + 内容缺口
> 信号/工具 + 本地化仓储 + shop chat 等）**969 passed**；`ruff check`、`mypy`（4 个改动源文件）
> 全绿。全程 Fake LLM，零真实调用；未做任何 Git 操作。
> **仍待推进**：Task 2（完整每日简报，前置已满足）、Task 8（商家工作台前端，部分仍需阶段 B
> 售后/信号 UI 区）、Task 9 步骤 2（双页合并评审）与步骤 3（同步文档，本次已部分完成）。
> 详见 `.superpowers/sdd/2026-09-21-n3-merchant-skills/progress.md`。

> **2026-09-26：N3 阶段 B「售后闭环与顾客 Skill」开发与自动化验证完成，待独立审查。**
> 交付 4 个顾客 Skill、商家客服回复 Skill、按类型与触发方约束的售后状态机、快照退款计算、顾客两阶段确认、
> 随单摘要与补充说明、商家审批决定与事务内客服回复、售后类顾客信号、双端售后页面及 8 条 v2 路由。
> S4 后端真实 PostgreSQL + 脚本化 Fake LLM 端到端、顾客和商家浏览器 E2E 均已通过；
> 状态机 659 项组合测试、8 条新增跨角色安全用例、商家端 677 项与顾客端 93 项全量单测通过；
> 顾客端预检被拒时显示平台依据条款（中英双语）。
> 后端单测全量 **2787 passed / 3 skipped**（跳过均为本机 Windows 符号链接权限限制）。
> 两端 `typecheck`、`lint`、`codegen:check`、生产构建通过；后端 `ruff check .`、`mypy app`（263 文件）通过，
> Alembic `check` 无待生成操作。后端完整 `REQUIRE_INTEGRATION_DB=1 uv run pytest -x --tb=short -q`
> **3784 passed / 4 skipped / 0 failed（1007.81 秒）**；1 项跳过为需独占 PostgreSQL 的既有安全时序哨兵，
> 3 项为本机 Windows 符号链接权限限制。
> **下一步：** 独立审查 `入口-N3`、`N3-2`、`N3-3`、`N3-4`，
> 复核 `N3-5` 的 11 Skill 实际组合。真实 LLM 摘要质量属于 R3 单独授权的人工验收，当前待验。
> 全程未调用真实 LLM、未执行 Git 发布操作；既有 `vendor/` 快照未改动。

> **2026-09-25：N3 阶段 C【商家经营 Skill】（`plans/2026-09-21-n3-merchant-skills.md`）
> Task 0/1/3(步骤0-2)/4/5/6 实现完成，Task 9 步骤 1（全量回归自检）完成。**
> Task 3 步骤 3、Task 7、Task 8 部分此前阻塞在阶段 B；B 已提供顾客信号服务与售后 UI，待 C 接入并验证；
> Task 9 步骤 2（双页合并评审）与步骤 3（同步进度文档）待推进。
>
> **交付**：6 个商家 Skill（业绩洞察/库存运营/商品内容/定价促销/明细导出/规则口径，
> `app/skills/merchant/`，前 4 个改编自 `vendor/anthropic-commerce-agents@fd4d592`，
> 后 2 个 Borough 自撰）；`gross_gmv`/`net_gmv` 指标口径与归因服务（`AttributionService`）；
> 定价促销护栏（`check_price_change`/`check_coupon`）与对应 `PriceChangeHandler`/
> `CouponHandler`；明细导出工具 `create_export`（解决 `export_files.answer_id` 时序问题，
> 改为可空列 + 回填迁移）；规则/指标口径问答工具（`get_metric_definition`/`search_rules`，
> 零 LLM 调用即可作答）；商品内容起草 `draft_content_change` + `ContentChangeHandler` +
> 批量拆子草稿（`batch_id` 用 `uuid5(conversation_id, batch_key)` 确定性派生，契约
> `docs/backend-development-plan.md` §8.13.1–§8.13.3 已先行同步）。
>
> **验证**：本计划新增全部 231 个测试单独运行 **231 passed / 3 skipped**（跳过均为
> Windows 符号链接权限限制，与本计划代码无关）；`ruff check .`、`mypy app`（260 文件）
> 全绿；`git status --porcelain vendor/` 确认零改动（R8）。全量套件因阶段 B 并行推进
> 存在瞬时中间状态（路由/Schema 未完全收尾）暂不能一次跑绿，已用精确范围验证证明
> 本计划代码本身干净；过程中发现并修复一处真实遗漏（`batch_id` 查询参数未同步进
> `test_openapi_session_contract.py` 的 `QUERY_PARAMS` 哨兵）。全程 Fake LLM，零费用，
> 未做任何 Git 操作。完整过程记录见
> `.superpowers/sdd/2026-09-21-n3-merchant-skills/progress.md`。

> **2026-09-25：N3 阶段 A 的 Astra 必审 / 抽审完成，N3-1、N3-5 均通过。**
> 审查范围：`app/skills/loader.py`（Task 2 白名单目录与路径逃逸）、`app/skills/registry.py`（Task 4 冲突裁决）、
> 顺带核对 `agent/loop/runner.py` 受信通道判定与 `services/v2/draft_handlers/`（Task 5 分派表）。
> **N3-1【必审】通过**：11 个路径逃逸用例（`../`、绝对路径、编码绕过、跨角色、空字节等）用独立脚本重新核对
> `NAME_PATTERN` 正则，确认全部在白名单格式层被结构性拒绝，不只是信任测试断言；对 `reject_links()` 做了
> 变异测试（函数体替换为空判断）证实符号链接/junction 有双层防御——第一层 `is_symlink()`/`is_junction()`
> 失效后，第二层 `resolve()` 后 `is_relative_to(resolved_root)` 仍会拦截，junction 用例在本机 Windows
> 实际执行（不需管理员权限）并通过；变异实验后已将 `loader.py` 改回原状，复跑 `tests/unit/skills/` 确认
> 无残留改动。受信通道判定（`runner.py::tool_content()`）同时核对工具名、`result.ok`、
> `isinstance(payload, SkillSpec)`、角色归属四者，结构上无法被其他工具伪造 `<skill>` 标记绕过围栏。
> **N3-5【抽审】有条件通过**：裁决顺序固定写在静态提示、不依赖 Skill 正文，越界指令换不来新工具能力、
> 两个互斥 Skill 加载互不覆盖，均有脚本化 LLM 用例验证；**条件**：11 个 Skill 的真实业务组合尚不存在
> （B/C 阶段未开工），"覆盖 11 个 Skill 组合"目前只在框架层面成立，B/C 落地 `cases.yaml` 后需补一次
> 真实组合回归复核。
> **验证**：`uv run pytest tests/unit/skills/ tests/unit/services/v2/test_draft_dispatch.py -q`
> **104 passed / 3 skipped**（3 条因本机 Windows 无符号链接创建权限 skip，与既有记录一致）；
> `ruff check app/skills/ app/services/v2/draft_handlers/ app/agent/loop/runner.py`、
> `mypy app/skills/ app/services/v2/draft_handlers/`（7 源文件）全绿。
> 结论已写入 `plans/2026-09-22-astra-checklist.md`（N3-1、N3-5 勾选）与
> `plans/2026-09-24-n3-assignment-and-review.md`（阶段 A 状态行）。
> **未覆盖**：Linux/CI 环境符号链接用例本次未重新实跑（09-24 已做过，未重复）；`入口-N3`
> （核对三份 N3 计划入口条件，范围比 N3-1/N3-5 更广）仍未做，不在本次审查范围内；
> N3-2/N3-3/N3-4（阶段 B/C 对应审查项）待实现者开工后才能审。
> 全程只读审查（未改动生产代码，仅变异测试临时改动后已复原）；未做任何 Git 操作；零 LLM 调用。

> **2026-09-24 晚：N3 阶段 A（Skill 底座，`plans/2026-09-21-n3-skill-loader.md`）实现完成，待 Astra N3-1 必审 / N3-5 抽审。**
> 计划 19 / 20 勾选；唯一未勾的是入口条件「Astra 入口-N3」（用户指示直接开工，实现者已自查 N2 实际形状与计划一致）。
> 交付：`backend/app/skills/`（`spec.py`、`loader.py`、`registry.py`、`tool.py`；白名单目录 `customer/`、`merchant/` 当前为空）、
> `app/eval/skill_cases.py`（`cases.yaml` 回归框架）、`services/v2/draft_handlers/`（协议、分派表、`RestockHandler`），
> `draft_apply.py` 只留骨架；`runner.py` 加 `load_skill` 受信通道（工具名 + 成功 + `SkillSpec` 类型 + 角色四者同时成立才免围栏）
> 与单回合加载上限（名字不在索引里由护栏交还模型，不致命）；两端 Chat 提示 = 原常量 + 本端索引（索引为空时逐字节等于 N2，不注册 `load_skill`）；
> 配置 `SKILL_MAX_CHARS`（8000）、`SKILL_MAX_PER_TURN`（3）。**B、C 须按 `HandlerRequest` / `HandlerResult` 签名实现处理器**，
> 并同步把新种类加进 `ENABLED_DRAFT_KINDS`；C 放入商家 Skill 后，`test_merchant_surface_has_no_apply_or_approve_tool`
> 的工具面集合需加入 `load_skill`。契约 §6.11「N3 阶段 A 落地补充」、§8.13.2「按种类分派」已同步。
> **验证：** 真实 PostgreSQL 全量 `REQUIRE_INTEGRATION_DB=1 uv run pytest`（1014 秒）**2966 passed / 4 failed / 4 skipped**：
> 1 条是本阶段引入（生产代码 import 了 `app.eval`），已把回归框架移入 `app/eval/skill_cases.py` 并复跑通过；
> 另 3 条来自**并行会话**在 22:29–22:49 对 `tests/eval/attack_llm.py`（`verify()` 改为 async，而 `test_security_attack_probe.py`
> 仍同步调用）与 `services/v2/catalog.py` 的进行中改动，不在本阶段范围——`shop_catalog` 那条复跑已通过，探针 2 条仍失败，归对方处理。
> 本阶段相关：Skill / 循环 / 工具 / 隔离单测 **252 passed / 3 skipped**（3 条符号链接用例在本机 Windows 无权限 skip，Linux CI 有效；
> Windows junction 用例实跑并做过变异核对）；N2 零回归 `test_draft_apply` + `test_approval_evidence_db` + S3 **45 passed**（文件未改）；
> `ruff check .`、`mypy app`（240 文件）通过。**环境风险：** 本机磁盘 fsync 慢，夹具 TRUNCATE 约 0.8 秒/次，
> 一次回归运行出现过 TRUNCATE 语句超时 / 死锁（同批文件单独复跑 51 passed），属环境抖动。
> **2026-09-25 补做系统自查并整改 6 项**（均先写失败测试再修）：① Skill 名字拼错原会走选项闸门致命错误、整轮 403
> 并写安全审计 → 改由护栏 `SKILL_NOT_IN_INDEX` 交还模型，回合继续；② Skill 正文里的示例数字原会为回答数字「作证」、
> 可绕过 R4 数字校验 → 校验不再把 Skill 正文当来源；③ `HandlerResult` 构造时核对 `ledger_result=APPLIED` 与
> `applied_entry_ids` 1–100 不重复；④ 未加引号的小数版本号给出加引号提示；⑤ `skill_cases` 接受 `max_chars`；
> ⑥ 加载器文档不再声称检查根目录上级链接。整改后 Skill / 循环 / 工具 / 分派单测 **269 passed / 3 skipped**，
> 草稿应用、分派、审批证据、S1 / S3 端到端、两端 Chat 集成与评测集 **214 passed**，`ruff check .`、`mypy app` 通过。
> 符号链接用例已在 Linux 容器（`python:3.12-slim`，仓库只读挂载、`uv sync --frozen`）实跑：`tests/unit/skills` **95 passed /
> 1 skipped**（仅 Windows 专属 junction 用例），并做变异核对（去掉链接检查 → 3 条符号链接用例全部失败），证明用例有效。
> A 自有的 22 个文件已通过 `ruff format --check`。
> **整改后全量**（`REQUIRE_INTEGRATION_DB=1 uv run pytest`，758 秒）：**2978 passed / 2 failed / 4 skipped**；
> 2 个失败均为 `test_security_attack_probe`（并行会话把 `tests/eval/attack_llm.py` 的 `verify()` 改成 async 后测试仍同步调用），不属于阶段 A。
> 未派独立审查子代理；独立审查按分工由 Astra 批次 1 执行。全程 Fake LLM，零费用，未做任何 Git 操作。

> **2026-09-25 N2 审核问题：代码修复、合并后全量数据库回归与独占安全时序验证完成；审查整改验收通过。**
> 在原七类问题和独立复审修复之外，本轮又修复工具循环展示未验证的模型残文、每日 LLM 预算耗尽提示错误、
> 非法上游 `tool_call_id` 导致 SSE 崩溃、审批证据与 `accepted_entry_ids` 绑定错误及错误选择可应用、
> 顾客端跨店会话创建竞态、写工具提交后 Chat 失败/回执提交失败时重试可能重复写入，以及幂等竞争分支未回放
> `FAILED_FINAL`。写操作现与请求级提交标记在同一事务保存，重试可安全降级收尾；相关故障注入测试已通过。
> 此后又补齐三项：C9 商品列表/详情按显示语言读取本商家未过期的译文缓存，逐字段标注机器译文或源文回退；
> 商家 v2 运营助手接入采纳、赞踩和可选原因，历史会话按商家/对话范围恢复已保存反馈；N2-7 安全注入
> 改打真实写工具并断言具体闸门、自批先起草真实待审批草稿。三项分别在独立真实 PostgreSQL 库定向通过
> （C9 商品/Schema/OpenAPI **130 passed**，反馈/会话/OpenAPI **118 passed**，安全门禁 **58 passed**）。
> 最新无数据库后端单元 **2044 passed / 3 skipped / 0 failed**（3 项为 Windows 符号链接权限限制）；
> 商家端单元 **675 passed**、顾客端 **89 passed**；两端类型检查、lint、构建和 `codegen:check` 通过；
> `ruff check .`、`mypy app`（240 文件）通过。Docker 恢复后在新建独立 PostgreSQL 测试库完成合并后
> 全量回归 **2979 passed / 4 skipped / 0 failed**（845.22 秒）；其中 1 项为时序哨兵在常规套件中跳过，
> 已独占另跑 **1 passed**，其余 3 项因本机 Windows 无符号链接创建权限跳过。空库迁移至单一 head
> `20260923_0034`，`alembic check` 无待生成操作；`git diff --check` 通过（只有换行符转换提示）。
> 公开商品 GET 不调用付费模型，缓存缺失时如实回退源文；尚无商品译文自动生成入口。顾客端其他页面的
> 全站双语文案不属于这次 C9 商品链路修改；Railway 部署仍按 N5 计划。下一步按 N3 既定阶段推进，
> N2 产品整体验收仍按对应计划单独判定。全程 Fake/脚本化模型，无真实 LLM 调用，未做 Git 发布。

> **2026-09-24 N2 独立复审（Astra 角色）完成，发现的问题已全部修复，N2 审查通过。**
> 审查范围：N1 前置项 B1–B4、D1–D6、E1–E3 的证据有效性复核 + N2-1 至 N2-8 + 入口-N2，
> 按 `plans/2026-09-22-astra-checklist.md` §九模板逐项出具结论（首次尝试因会话额度限流中断于 N2-1，
> 额度重置后完整重跑）。
> **结论：** N1 前置项与 N2-1、N2-5、N2-6、N2-8 通过；N2-2、N2-3、N2-4、N2-7、入口-N2、E3 有条件通过。
> 审查过程中发现工作树在 17:15 之后又有改动落入（`chat_write_marker.py`、`idempotency.py`、两端 Chat
> 服务与路由），导致 4 个测试失败（`test_merchant_chat.py::test_fatal_after_committed_draft_persists_terminal_receipt`、
> `test_shop_chat.py::test_fatal_after_committed_cart_write_persists_terminal_receipt` 各 2 组参数化）与
> `ruff check .` 11 处格式错误；经核实均为**测试查询没有按 `operation` 过滤**导致取到同一
> `client_request_id` 下的另一行记录，不是产品缺陷。
> **另发现一处真实并发缺陷（不在整改计划七类问题内）**：`draft_apply.py` 的 `_lock()` 用
> `SELECT ... FOR UPDATE` 但未加 `populate_existing=True`；若调用方在加锁前已用同一 `Session`
> 持有过这个 `Draft` 对象（路由层的归属检查正是如此），`FOR UPDATE` 解锁后返回的仍是身份映射里的
> 旧属性，另一事务把状态改成 `DISCARDED` 并提交后这里读到的还是旧的 `STAGED`——已丢弃的草稿会被
> 重新应用。此前的并发测试之所以没抓到，是因为没有代码持续持有那个旧对象、被 CPython 立即回收。
> **用户裁定（2026-09-24，均选择推荐方案）**：`CURRENT_MILESTONE` 提前被改为 `"N2"` → 保留不回退；
> 4 个失败测试与 ruff 错误 → 现在直接修，算 N2 整改的一部分；`_lock()` 并发缺陷 → 现在就修，
> 算 N2 收尾的一部分。三项均已修复：
> - 两处失败测试改为按 `operation` 过滤（`CHAT_OPERATION` 常量），ruff 全部机械格式问题已清（`ruff check .` 全绿）；
> - `_lock()` 加 `execution_options(populate_existing=True)`（沿用 `orders.py`/`payment.py` 已有模式）；
>   新增回归测试 `test_lock_refreshes_stale_identity_map_entry`，已验证**修复前失败、修复后通过**，
>   且不影响 `test_draft_apply.py` 其余 35 项（全部通过）；
> - `app/core/errors.py` 里未被使用的 `IdempotentReplay` 死代码（Astra 发现进度文档描述与实际修复机制不符）已删除，
>   实际生效的修复是 `merchant_drafts.py` 的 `BeforeValidator` + `require_evidence_field()`，与之前记录一致但表述已更正。
> **最终验证**（一次性库，`REQUIRE_INTEGRATION_DB=1 uv run pytest -m "not security_timing"`，713 秒）：
> **2861 passed / 0 failed / 1 deselected**（deselected 为需独占库的 `security_timing` 时序哨兵，本轮未跑）；
> `ruff check .` 全绿；`uv run mypy app` 232 个文件通过；`alembic heads` 单一 head `20260923_0034`；
> 商家端 `npm run codegen:check` / `lint` / `typecheck` 通过、单元测试 **670 passed**；`shop/` 的
> `codegen:check` / `tokens:check` / `eslint .` / `tsc --noEmit` 通过、单元测试 **84 passed**。
> **N2-1 至 N2-8、入口-N2、E3 全部勾选通过**（见 `plans/2026-09-22-astra-checklist.md` §五）；
> [N2 整改计划](../plans/2026-09-24-n2-review-remediation.md) Task 1–5 全部完成，**整改验收通过**。
> 当时的非阻塞建议：N2-7 安全用例攻击强度与 `security_timing` 独占库补跑；两项已按上方 2026-09-25 状态补齐。
> 全程 Fake/脚本化模型，零真实 LLM 调用，未做 Git 提交或发布操作。

> **2026-09-24 N3 划分为阶段 A / B / C，三份计划已按 N2 实际代码重排（只改计划，未写代码）。** 总览
> [n3-module-roadmap](../plans/2026-09-24-n3-module-roadmap.md)：A Skill 底座（`n3-skill-loader`，20 步）、
> B 售后闭环与顾客 Skill（`n3-customer-skills-and-after-sales`，41 步，收口 S4）、
> C 商家经营 Skill（`n3-merchant-skills`，34 步，收口 S2、S5、S6、S7）。与原计划的差异：客服回复 Skill、售后类信号、
> 商家售后界面与 S4 由 C 移入 B，C 的业绩 / 定价 / 导出 / 口径可与 B 并行。核对 N2 代码补出三处缺口：
> 草稿应用事务写死只支持补货（`draft_apply.py`）→ A Task 5 改为按种类分派；工具循环对所有工具结果一律围栏、无 Skill 入口 →
> A Task 6；`batch_id` 不在契约与 `drafts` 表 → C Task 3 契约先行。
> **售后 PRD 缺口已由用户裁定并写入（2026-09-24）**：售后后续唯一且无需决定的跳（退货同意 → 待寄回、工单同意 → 关闭、
> 已退款 / 已拒绝 → 关闭）由系统同事务续跳；「待顾客补充信息 → 待商家处理」原先连顾客接口都没有，新增
> `POST /api/v2/shop/after-sales/{after_sale_id}/supplements`（PRD §7.2、C6、§11.2.2；契约 §8.7.3、§8.11.1–§8.11.3）。
> PRD §11.2 由 47 条路径变为 **48 条**；`app/schemas/v2/after_sales.py` 尚未同步新模型，归 B Task 7 步骤 0。
> N3 开工仍以 N2 验收（独立复审与 Astra N2 审查）为前提；该前提已满足（见下方 N2 独立复审条目）。
> **分工与审查排期已建立**：[n3-assignment-and-review](../plans/2026-09-24-n3-assignment-and-review.md)——
> A、C 交 Opus，B 交 Sol，B/C 内前端任务分别交 Sonnet（`frontend/`）与 Terra（`shop/`），均沿用各自在
> N2 建立的地基；Astra 共需 6 次审查会话（N3-1 至 N3-5，按批次合并）。三份实施计划均未开工。

> **2026-09-24 N2 审查整改 Task 1–4 验证完成（真实 PostgreSQL），Task 5 除独立复审外完成**
> （计划 [N2 整改计划](../plans/2026-09-24-n2-review-remediation.md)；**未做 Git 提交**）。
> 验收中额外发现并修复两处缺陷（均不在整改计划原定七类问题内）：
> ① `tests/integration/v2/test_approval_evidence_db.py` 的跨进程 nonce 测试用 `asyncio` 子进程，
>   Windows 下项目固定的事件循环不支持子进程传输，改为线程内 `subprocess.run` 并补子进程事件循环策略；
> ② 审批应用端点（`POST /merchant/drafts/{id}/apply`）违反 §8.7.9「先查幂等命中，未命中才验证证据」：
>   证据格式校验在依赖阶段先于幂等查询执行，导致同一 `client_request_id` 换成缺失/格式错误证据重试时
>   被误判为新请求而拒绝，未能原样回放首次成功结果；实际修复是在 `app/api/routes/v2/merchant_drafts.py`
>   用 `BeforeValidator`（`_defer_evidence_validation`）把缺失或格式不对的证据替换成占位符，让请求能先走到
>   幂等查询，未命中时再由 `require_evidence_field()` 读取原始请求体统一中性拒绝；补正例与反例测试
>   （换请求标识、换业务输入时证据无效仍中性拒绝）。
>   **2026-09-24 Astra 独立复审发现**：`app/core/errors.py` 里另有一个 `IdempotentReplay` 异常类与处理器，
>   全仓没有任何地方抛出它，是本轮遗留的死代码，与上面的实际修复机制无关；已删除，无回归。
> 另补齐整改 Task 4 遗漏的测试：他人的 / 不存在的 / 格式不对的 `conversation_id`（含流式请求）统一 403、
> 响应体逐字段一致、零模型调用、均写 `RESOURCE_SCOPE_VIOLATION` 审计。
>
> **验证结果**（两次独立一次性库 `borough_accept_test`、`borough_accept2_test`，`REQUIRE_INTEGRATION_DB=1`，
> `-m "not security_timing"`）：修复前 2830 passed / 2 failed / 1 error；修复后**复跑 2834 passed / 0 failed**
> （20 分 31 秒）；`ruff check` 全绿；`mypy` 231 个文件通过；`alembic check` 无新增操作、单一 head `20260923_0034`；
> 前端 `codegen:check` 一致、`typecheck` 0 错误、`lint` 通过、单元 647 passed；`shop/` 单元 67 passed、
> `codegen:check` / `tokens:check` 一致、`eslint` / `tsc` 0 错误、`next build` 通过、浏览器 E2E 4 passed；
> 镜像构建成功无跨目录读取。全程 Fake / 脚本化模型，零真实 LLM 调用，零费用。
> 此前模块 D 快照里记录的「后端全量 2828 passed / 5 failed，`test_eval_skip_gate` 4 例疑因整改改动失败」
> 已被本次复跑取代——该目录单独重跑 5 passed，未复现；判断为整改期间的瞬时/顺序相关状态，不是遗留缺陷。
> **仍未完成**：独立复审（整改计划 Task 5 要求，本次只做了自审）；`security_timing` 时序哨兵（需独占库，未跑）；
> Astra N2-1～N2-8 及前置 N1 B1–B4/D1–D6/E1–E3、入口-N2 均未审查——**这是当前 N2 收口的唯一阻塞**。
> 改动的 `merchant_drafts.py`、`core/errors.py` 属于审批安全路径，审查时对应 N2-3。

> **2026-09-24 N2 模块 D【会话目录与反馈】Task 1–5 全部完成**（计划
> [n2-conversations-and-feedback](../plans/2026-09-21-n2-conversations-and-feedback.md) Task 4 / 4B；**未做 Git 提交**）。
> **用户裁定（已写入 PRD §15 N2）**：商家端新增独立 **v2 运营助手页** `/ops-assistant`（v2 Chat + v2 会话目录侧栏），与 v1 分析助手并存、
> v1 页面不改——N2 的 v2 商家工具只有库存告警与补货草稿，直接替换会让指标 / 明细 / 规则 / 图表 / 导出在 N3 前整体回退。
> 这也补上了模块 E 遗留的「Vue 端没有 v2 对话界面」：今日简报条目动作现在把问题预填到该页并跳转（只填不发）。
> - 顾客端：会话目录嵌在导购页（新建 / 浏览 / 打开历史 / 删除；删当前对话或身份变化后回到新建态）。`shop/` 单元 **82 passed**，
>   `tsc` / `eslint` 0 错误，`next build` 通过，Playwright **5 passed**（S1 ×4 + 375px 会话目录）；首跑抓到既有缺陷：气泡无空格长串撑到 900px，已修。
> - 商家端：前端单元 **670 passed**（新增 23），`typecheck` / `eslint` 0 错误，`build` 与 `codegen:check` 通过；S3 Playwright **2 passed**
>   （原 S3 闭环 + 新增 375px 运营助手用例；去掉气泡折行后报 958px，检查有效）。自查补出中文输入法选词回车误发送，已修。
> - 后端未改：模块 D 相关测试真实 PostgreSQL **152 passed**，ruff / mypy（231 文件）通过，`session_id` 自检零命中；
>   后端全量（一次性库）**2828 passed / 5 failed**，5 个失败都不在模块 D：`test_draft_apply` 网络重试（整改计划在办项）与
>   `test_eval_skip_gate` 4 例（有无集成库环境变量都失败，疑为整改中的 `tests/eval` 改动所致），未处理。全程脚本化模型，零费用。
> - **仍未做**：v2 回答的采纳 / 赞踩按钮（后端路由已在 Task 2 落地，界面未接）；v1 顶栏窄屏溢出（v1 页面，不在本任务内）。

> **2026-09-24 N2 模块 F【顾客端 Next.js `shop/`】Task 1–9 代码与本地验证完成**（由本会话内联执行，计划见
> [n2-shop-nextjs-app](../plans/2026-09-21-n2-shop-nextjs-app.md)；**未做 Git 提交**）。`shop/` 单元 **67 passed**，`codegen:check` /
> `tokens:check` 一致（并已故意改坏副本验证会挡），`eslint` / `tsc --noEmit` 0 错误，`next build` 通过；
> **S1 浏览器 E2E 4 passed**（主流程 + 刷新①未绑定访客 + 刷新②已绑定重绑恢复 + 越权订单页与「不存在」逐字一致），
> 后端为真实代码 + 真实 PostgreSQL（一次性库 `borough_s1_e2e_test`）+ 脚本化 Fake LLM，零费用。
> 镜像 `docker build --no-cache` 成功、无 `docs/` / `frontend/` 跨目录读取，容器按 `PORT` 监听且 `/health` 200。
> Backend 新增可选 `SHOP_ORIGIN`（CORS 两个精确 Origin，禁 `*`），CORS 用例 14 passed，`tests/api` + `tests/unit` 2320 passed。
> **本阶段记录的后续状态已更新于顶部**：C9 商品译文标注与 Astra N2-8 抽审已完成；Railway 服务仍归
> `n5-budget-ops-and-railway`，浏览器 E2E 仍需一次性 PostgreSQL 库，未纳入 CI 的无库 job。
> 会话凭证导出名与目录结构见 [project-navigation §4.7](project-navigation.md)。
> 模块 D Task 4 顾客端已据此接入（见上条）。


> **2026-09-23 N1 审核最新结论：18/18 已审，E1 整改已获 Astra 独立复审通过。**
> 语言传递、真实对象登记及门禁反向测试已修复；评测集 99 项通过、新增测试独立复审 18 项通过。
> **审核与整改已完成，但 N1 最终验收尚未完成。** 最新 N1＋v1 回归 2195 passed / 6 failed / 0 skipped，
> 六项失败发生在 N2 新迁移 0031 降级删除不存在的 title_snapshot；前端全量 646 passed / 1 路由超时。
> 全仓回归还曾被并行新增 N2 结账测试的模块缺失中断。下一步须稳定并行工作树、以新库重跑最终回归；
> N2 `LlmCostGuard.converse()` 丢失未知 usage 状态的问题另交 N2 整改，不混入 N1 适配器结论。
> 先前审核结果 2435 passed / 1 failed 已不是最新验收结果；不得混用不同工作树时点的数据。
> 逐项证据与限制见 [N1 审核记录](../plans/2026-09-22-n1-review-remediation.md)「E1 整改复审与最终验收停点」。

> 本文件只保留**当前可继续开发的事实快照**，不追加每日流水账。
> 2026-09-16 之前的完整历史记录（逐轮验证数据、裁定过程、已修复缺陷清单）已整体归档到
> [`docs/history/project-progress-before-2026-09-16-remediation.md`](history/project-progress-before-2026-09-16-remediation.md)，
> 需要追溯某次验证的原始数据时读那份文件。

**最后更新：2026-09-27（**N3 阶段 C Task 9 步骤 2 用户裁定「选项 C」执行完成——图表
可视化补齐 + v1/v2 两页合并，阶段 C 主体收口，详见本文件顶部最新快照**）**
此前（2026-09-23）：**N2 模块 D【会话目录与反馈】Task 1（双端会话目录）完成**：6 条路由（`GET/GET/DELETE /api/v2/{shop,merchant}/conversations[/{conversation_id}]`）、共用服务 `services/v2/conversations.py`、迁移 `20260923_0033`（`conversations.surface / deleted_at`、`messages.response_payload`），两端 Chat 改为落盘完整回答；新增 15 例集成测试与 SEC-CROSS-006~011。后端全量 **2664 passed / 3 failed / 1 skipped**，3 个失败均为登记类哨兵（OpenAPI 未重新导出、v2 路径未登记、安全用例在全量开跑后才补登），修复后这 3 个文件与相关集成测试复跑 **192 passed**；ruff / mypy 全绿；`codegen:check`、前端 `typecheck` 通过。随后按用户裁定修复 v2 回答反馈缺口（迁移 `20260923_0034`，v2 回答落 `answers`），并堵住 v1 会话目录可读本店顾客对话的既有 R5 泄露，见 §四「N2 模块 D 进展」。修复后后端全量 **2692 passed / 1 failed / 1 skipped**，唯一失败是断言 `answers` 整表唯一约束的旧元数据测试（约束按裁定改为只约束 v1 行的部分唯一索引），已改为断言新形状；随后元数据测试与迁移、v2 集成、v1 会话/反馈、Chat BI 相关测试复跑 **171 + 4 passed**，ruff / mypy 全绿。全程 Fake LLM，无 Git 操作）**
此前（2026-09-23）：**N2 模块 C【商家草稿审批与库存运营】Task 8（S3 端到端）完成，模块 C 现 Task 1–9 全部完成**：
前置条件（模块 B 的真实占库/实扣）已满足，解除此前的入口阻塞；新增 `tests/e2e/test_s3_inventory_loop.py`
（Fake LLM、真实 PostgreSQL）编排「顾客下单支付 → 可售降到阈值以下 → 最小简报出现低库存条目 →
商家 Agent 起草补货 → 审批界面批准应用 → 顾客端档位从 LOW_STOCK 恢复为 IN_STOCK」全链路，最后一步经
顾客端公开浏览接口断言，证明两端共享同一份库存事实；新增质量评测登记
`app/eval/datasets/quality/scenarios/n2_s3_inventory_restock.yaml`（`QLT-S3-001`/`QLT-S3-002`）与配套结构性
校验测试。详见 §四「N2 模块 C（商家草稿审批与库存运营）进展」。
后端全量（本人一次性库，`REQUIRE_INTEGRATION_DB=1`）**2652 passed / 1 skipped / 0 failed**
（跳过的是需 `REQUIRE_SECURITY_TIMING=1` 独占库的时序哨兵，本轮未另跑）；ruff（改动文件）/ mypy
（`tests/e2e/test_s3_inventory_loop.py`）通过；两项扫描零命中（`UPDATE products` 只在
`draft_apply.py`/`checkout.py`/`payment.py`；`app/tools/` 不含审批证据）。全程 Fake LLM，
无真实 LLM 调用，无 Git 操作）**
此前（2026-09-23）：**N2 模块 B【顾客端交易闭环】Task 0–8 全部完成**：购物车与访客合并、结账占库、模拟支付 / 取消 / 超时关闭竞争、订单列表 / 详情 / 履约事件、顾客导购工具与 `POST /api/v2/shop/chat`、S1 后端 E2E；新增迁移 0030–0032；详见 §四「N2 模块 B Task 0、2–8 进展」。后端全量（一次性库，`REQUIRE_INTEGRATION_DB=1`，`-m "not security_timing"`）**2649 passed / 0 failed**；并发与幂等测试在真实 PostgreSQL 上跑；ruff（本轮改动文件）/ mypy（227 文件）全绿；前端 `typecheck` 0 错误、`codegen:check` 一致。全程 Fake LLM，无真实 LLM 调用，无 Git 操作**
此前（2026-09-23）：**N2 模块 E【商家端 Vue v2 迁移】18 / 18 完成；N2 模块 B Task 1【顾客端公开浏览】完成**
（为解锁 E Task 7 末步由 Opus 接手，B 其余任务未开始）；详见 §四「N2 模块 E 进展」「N2 模块 B Task 1 进展」。
前端 **647 passed**、`npm run typecheck` **0 errors**、lint 0、`codegen:check` / `build` / `secrets:check` 通过；
`npm run test:e2e:s3` **1 passed（无 fixme）**；默认 Mock E2E 37 passed / 4 failed（**4 条均为 HEAD 既有失败**，
已用 HEAD 临时 worktree 复现确认）。后端全量（本人一次性库，Bash 下运行）**2490 passed / 1 个已知且刻意接受的红测试**（同下）；
ruff / mypy（213 文件）全绿。全程 Fake/脚本化 LLM，无真实 LLM 调用，无 Git 操作）**
此前（2026-09-23）：**N2 模块 C【商家草稿审批与库存运营】Task 1–7 与 Task 9 完成并验证**；
Task 8（S3 端到端）按计划裁定停在前置条件——`n2-trade-closed-loop`（模块 B）尚未开工，
`app/services/v2/checkout.py`、`payment.py`、`app/tools/customer/` 与 shop 侧交易路由都不存在，
不得用直接改库存的捷径代替真实下单链路；详见 §四「N2 模块 C 进展」。
后端全量 **2431 passed / 1 skipped / 1 个已知且刻意接受的红测试**
（`test_no_case_is_introduced_ahead_of_its_milestone`，模块 D 已登记的过渡态，本轮新增 9 条 N2 用例同属该态）；
ruff / mypy（208 文件）全绿；前端 **593 passed**、`vue-tsc --noEmit` 通过、`codegen:check` 通过；
`docs/api.json` 已补齐 7 条 v2 商家路径。全程 Fake LLM，无真实 LLM 调用，无 Git 操作）**
此前（2026-09-23）：N2 模块 D【会话目录与反馈】Task 2（商家回答反馈）完成并验证；
Task 1（会话目录）与 Task 3 顾客侧当时按入口条件核实为受阻（两端 Chat 路由不存在）——
**其中商家 Chat 路由已由本轮模块 C Task 7 落地**，模块 D 可据此重新评估 Task 1；
此前（2026-09-22）：N2 模块 A【工具注册表与工具循环】开发完成，等待审查：Task 1–6 全部实现并验证（10 / 20 步已勾选，其余 10 步全部是等审查的勾选：入口 3 条待 N1 B/D/E 审查，Task 2–4 待 Astra N2-1/N2-2），注入用例登记移交交易计划 Task 8，详见 §四「N2 模块 A 进展」；后端全量 2268 passed / 1 skipped（自查整改后）；
此前：模块 C【数据迁移与确定性种子】29 / 29 步完成，C1–C5 独立复审通过；
**遗留的 2 个测试失败已由 Codex 收口**（三商家种子重复确定性、可售量派生不可超卖，均已转绿，
Sonnet 本轮复核确认）；
**模块 B 此前被 C 阻塞的「全量回归」验收条件已随 C 收口解除**，B1–B4 已于 2026-09-23 审查通过
（计划 25/25 步已全部完成）；
模块 D 的 D1–D6 已于 2026-09-23 审查通过，实施计划原勾选数 12 / 27 不作为最新审核状态；
**模块 E【评测骨架】Task 1–6 完成，Task 7 步骤 1–2 已按 R3 授权执行**——
安全硬门禁在 N1 即可跑，13 条 N1 用例（CROSS/SQLI/IDENTITY/BUYERKEY 各 ≥3）零失败，
E1–E3 已审，E2/E3 通过、E1 待整改复审；Task 7 步骤 1–2 用 6 条真实 `deepseek-flash` 质量用例（8 次真实调用）
跑通 v1 冻结基线，发现两项基线自身缺陷（详见下文），步骤 3 与新工具循环对照仍待 N2；
**本轮（模块 C 收口 + 模块 E）真实 PostgreSQL 后端全量复测 2062 passed / 1 个时序哨兵按标记跳过**，
该哨兵在独占库另跑 1 passed，ruff/mypy 全绿，`ruff format --check .` 尚有 38 个文件未格式化）**

---

## 一、当前阶段

**既有基线已完成并上线**：后端 B0–B7、前端 F0–F6，以及日报、知识库维护后台、商家记忆、
Chat BI 和中英双语本地化已经落地。B/F 与 P0/P1/P2 现在只用于追溯旧实施记录，
**不再表示当前优先级或产品路线图**。

**当前处于 N1（契约与安全地基）**：2026-09-20 新 PRD 已接管产品范围，目标从单一商家 Data Agent
扩展为同一平台上的顾客端 Agent 与商家端 Agent。

已完成的是**规划层**：PRD、`AGENTS.md`、前后端计划与索引文档的语义同步（2026-09-20），
以及 N 路线的**架构边界层**——`docs/backend-development-plan.md` §5.6（分层增量、与冻结
LangGraph 的并存关系、新模块依赖方向）与 §6.9–§6.15（工具注册表、工具循环、Skill 加载器、
上下文压缩、记忆管线、混合召回、评测运行器七个 Deep Module）（2026-09-21）。

**契约冻结 Task 1 已完成并通过验证（2026-09-21 复核）**：§8.7 共用契约、唯一 `SessionRole`、共用 Schema、
14 个新增错误码及双语文案已落地。因共享 `ErrorCode` 会改变 v1 OpenAPI，已同步 `docs/api.json`、
`docs/api.md` 与 `frontend/src/api/generated.ts`（不含 v2 路径与 Adapter），OpenAPI 哨兵与
`codegen:check` 均通过。Chat 幂等白名单遗漏已修正（`POST /shop/chat`、`POST /merchant/chat` 纳入 §8.7.3，
Task 3 补 `MerchantChatRequest` 不变量与测试）。
自查整改已补齐：FALLBACK 强制降级、工具摘要固定安全短句与状态闭集、来源 Schema 排除附件、
幂等键与游标边界、MCP 鉴权例外；前端同步新增错误码双语文案和运行时白名单，
白名单由完整 Record 与 OpenAPI 全枚举测试共同防止漏项。
**模块 A（N1 v2 契约层）已完成（2026-09-21）**：契约计划 45 / 45 步全部勾选。`docs/backend-development-plan.md`
§8.7–§8.14 七组字段契约已冻结，PRD §11.2 的 47 条路径逐条覆盖（脚本核对 47/47，无多余路径）；`backend/app/schemas/v2/`
七个业务模块与共用 `common.py` 及其单测已落地（2026-09-22 v2 Schema 单测 **285 passed**；此前 93 处校验拒绝语句的变异检验 93/93 杀死，见 §二）。
**这不等于 v2 功能已实现**：v2 路由、OpenAPI 导出、生成类型与 Adapter 尚未开始，按 §8.0.1 随各组路由实现的
同一次变更完成；N1 内唯一规划落地的 v2 路由是模块 D Task 7 的 5 条会话签发路由（2026-09-21 用户裁定并入）。模块 A 的收口与复审修复记录（执行期裁定 E1–E14、下游计划对齐）见 §四「模块 A 收口记录」。

**N1 总览已建立**：`plans/2026-09-21-n1-module-roadmap.md` 把 N1 划分为模块 0 与 A–E，写明各自所在框架层、难度、
任务级依赖、出口标准与费用点；执行顺序与状态见 §四「N1 五个模块与执行顺序」。

**N1 整体仍未完成**：模块 A 45 步已完成；**模块 B 完成 25 / 25 步**（2026-09-22，见 §四「模块 B 进展」）；
**模块 D（会话身份与租户隔离）实现完成，D1–D6 审查通过**（2026-09-23，见下方独立段落）；
**模块 C（数据迁移与确定性种子）已完成 29 / 29 步并通过 C1–C5 独立复审**（2026-09-22）：
迁移 `20260922_0017`–`0024`（M1–M8 八份）、`app/models/` 下的 `events` / `drafts` / `promotion` / `memory_v2` / `after_sales` / `idempotency`、
`app/domain/order_status_mapping.py`、`app/jobs/rebuild_projections.py`、`scripts/seed_demo_scenarios.py`、`docs/database.md`，
以及 PostgreSQL 约束、既有行回填、种子确定性测试。迁移从 base 降级再升至唯一 head `20260922_0026`、
`alembic check` 均通过；三商家 180 天全量重灌写入 31383 行，S1–S4 场景首次写入 36 行、重复写入 0 行，
投影重算检查 5659 单且零漂移。`idempotency_records` 的主体摘要复用 `app/core/session.py` 共用函数；
C 不创建 D 所属的 `agent_sessions` 或来源状态表。
**模块 D（会话身份与租户隔离）实现完成，D1–D6 审查通过（2026-09-23）**：`plans/2026-09-21-n1-session-identity.md`
27 步的代码与测试均已完成。Task 1–5 属于 `plans/2026-09-22-astra-checklist.md` 的**必审**项 D1–D5，按清单规则
审查通过前不勾选，因此计划当前勾选 **12 / 27**（Task 6–8）；抽审项 D6 在里程碑验收前集中审。
**上述勾选与待审安排是 2026-09-22 的记录；最新 D1–D6 均已通过，不能据旧勾选数判断仍未审。**

- Task 1（会话凭证原语）沿用此前已提前写入工作树的 `backend/app/core/session.py`
  （`SessionContext`、`SessionAlreadyBoundError`、`new_session_token`/`token_fingerprint`/`issuer_fingerprint`/`buyer_alias`），
  本轮新增 `expires_at: datetime | None` 字段供签发/绑定响应回显，12 个既有单测 + 复核全部通过；
- Task 2：新建 `agent_sessions` 表（迁移 `20260922_0025`，紧接模块 C 的 `0024`），角色/租户/`issuer_fingerprint`
  由 CHECK 约束 + `BEFORE UPDATE` 触发器双重强制不可变，仅允许 `buyer_key: NULL → 值` 一次性写入；
- Task 3：`SessionRepository` + `SessionService`（`create_guest`、`bind_demo_customer`、`issue_merchant`、`revoke`、
  `revoke_by_issuer`），`CartMergePort` 端口 + `EmptyCartMerge` 生产装配；**启动对账**（Astra D3）：
  `app/services/session_reconciliation.py` 在 lifespan 中先于其他启动任务执行，按指纹集合与当前
  `DEMO_MERCHANT_TOKENS` 比较并撤销已移除 issuer 换出的商家会话（`SessionRepository.revoke_unlisted_issuers`），
  只记录撤销行数，不记录 Token 或指纹；对账失败即中止启动（fail-closed）；并发绑定不同身份只有一方生效
  （真实行锁验证）、购物车合并失败时整体回滚、幂等重绑不重复合并均有真实 PostgreSQL 测试覆盖；
- Task 4：`backend/app/api/session_deps.py`（`require_customer_session` / `require_merchant_session` /
  `require_bound_customer_session`），角色不符统一 `403 SESSION_ROLE_MISMATCH` 并写审计，v1 API 215 项零回归；
- Task 5（安全硬门禁）：`app/services/resource_scope.py` 的 `require_owned()` 用**单条固定形状查询**同时判定
  存在性与归属，`tests/support/scope_probe.py` 探针 + `tests/integration/test_session_isolation.py` 证明
  「目标不存在」与「目标属于他人」响应体逐字段一致、双重过滤（`merchant_id` + `buyer_key`）生效；
  独立 `security_timing` 门禁（`REQUIRE_SECURITY_TIMING=1`）实测中位数差与 p95 比值均在阈值内，**首轮即通过**；
- Task 6：`conversation_provenance` 表（迁移 `20260922_0026`）+ `ConversationProvenanceRepository`，
  按计划用**版本号条件更新**（`UPDATE ... WHERE version = 读到的值`，冲突重读、最多重试 3 次，超限抛
  `ProvenanceWriteConflictError`，不盲写），不跨对话/店铺/对象类型扩散；过期且未绑定的访客会话留下的来源状态由
  `python -m app.jobs.purge_guest_provenance` 清理（`backend/railway.provenance-cron.json`，**Railway Cron Service 尚未创建**）；
- Task 7（**N1 内唯一落地的 v2 路由**）：`POST/DELETE /api/v2/shop/sessions*`、
  `POST/DELETE /api/v2/merchant/sessions*` 共 5 条，`docs/api.json` 精确新增且只新增这 5 条路径，
  `frontend/src/api/generated.ts` 已重新生成并通过 `codegen:check`；新增
  `frontend/src/api/adapters/session.ts`（+ 5 个契约测试），覆盖成功路径与 `401`/`403` 错误映射，
  刻意**不接 Store、不改页面**（留给 `n2-merchant-vue-v2-migration`）；新增
  `tests/api/v2/test_openapi_session_contract.py` 专用哨兵，钉死 5 条路径的方法、鉴权头、请求/响应模型名与错误码，
  并断言 N1 不存在其他 v2 路径；`app/core/logging.py` 新增 `redact_sensitive_values` 处理器，对
  `X-Session-Id`/`Authorization`/`X-Admin-Token` 等凭证键（含嵌套请求头）全量脱敏，开发环境异常栈固定为纯文本、
  不打印局部变量；路由测试断言日志与审计中都不出现明文会话 ID（本项目未接 tracing，tracing baggage 无对象可脱敏）；
- Task 8：新增 `docs/backend-development-plan.md` §6.16 Session Identity；CORS 允许头补上
  `X-Session-Id`（`app/main.py` `_ALLOWED_HEADERS`，`tests/api/test_cors.py` 同步）；禁用模式扫描
  （`merchant_id`/`buyer_key` 不出现在 Header/Query/Body、`resource_scope.py` 无 404、
  `BUYER_ALIAS_SECRET` 无硬编码默认值、日志/审计无明文会话凭证）全部通过。

**验证证据**（2026-09-22 补齐缺口后复测）：`REQUIRE_INTEGRATION_DB=1 uv run pytest -m "not security_timing"`（真实 PostgreSQL）全量
**2013 passed / 2 failed / 1 deselected**（补齐前为 1984 passed，新增 29 项）
（deselected 是需要 `REQUIRE_SECURITY_TIMING=1` 单独运行的时序哨兵，已单独验证通过）；2 个失败
（`test_demo_determinism.py::test_three_merchant_seed_is_repeatable_in_postgres`、
`test_n1_c_core_migrations.py::test_product_stock_is_derived_and_cannot_oversell`）**均属于模块 C**，
与本次改动的文件无关（`git status` 显示两个测试文件与 `app/models/analytics.py`/`app/analytics/demo_data.py`
在本轮开工前已是 C 写入的既有改动），留给模块 C 自己的验收收口，不在本轮范围内修复。
`uv run ruff check .` 与 `uv run mypy`（166 个源文件）全绿；时序哨兵复测 1 passed；新加的日志断言在迁移测试之后运行也能通过
（迁移测试会调用 alembic 的 `fileConfig`，把已存在的 logger 全部禁用，测试里用 `tests/support/log_capture.py` 重新启用）；前端 `npx vue-tsc --noEmit`、
`npx eslint`、`npm run codegen:check` 与全量 `npm run test`（**52 files / 582 passed**）均通过。
**未执行任何 Git 提交、发布或历史改写操作**（R2）；**未调用真实 LLM**（R3）。

**模块 C 遗留的 2 个失败已由 Codex 收口（2026-09-22，与模块 E 并行）**：上面记录的两个失败
（三商家种子重复运行确定性、可售量派生不可超卖）现已转绿，本轮（Sonnet）复核时确认。
随附的模型层改动（`app/models/analytics.py`）把 `Product`/`Order`/`OrderItem`/`Refund` 补齐到
迁移已声明的完整约束集：`stock_available` 改为 `Computed("stock_on_hand - stock_reserved")`
持久化生成列（不建独立事实源）、库存与内容版本的非负/一致性 CHECK、订单
`payment_status`/`fulfillment_status`/`close_reason`/`lifecycle_origin` 的枚举与状态一致性
CHECK（含旧版状态到新五态的映射一致性约束）、订单明细的金额快照一致性 CHECK。
`app/jobs/seed_demo_rolling.py`、`scripts/seed_demo_analytics.py` 同步改动以匹配新增列与约束。
复核证据：`tests/integration/test_demo_determinism.py::test_three_merchant_seed_is_repeatable_in_postgres`
与 `tests/integration/test_n1_c_core_migrations.py::test_product_stock_is_derived_and_cannot_oversell`
单独重跑 **2 passed**；`alembic heads` 仍是唯一 head `20260922_0026`；纳入下方今日全量回归
（**2062 passed**）。本条目由 Sonnet 复核记录，具体改动由 Codex 完成，未在本轮重新逐行审查
Codex 的实现细节，只验证了对外可观察行为（测试通过、约束生效、迁移链完整）。

**模块 E（评测骨架）Task 1–6 实现完成，Task 7 步骤 1–2 已按 R3 授权执行；2026-09-23 E2/E3 审查通过，E1 不通过**：
`plans/2026-09-21-n1-eval-harness.md`。Task 7 步骤 3（与冻结基线对照）需等 N2 工具循环存在
才能执行，本轮未做，如实标记，不得记为完成。按清单规则，E1–E3 审查通过前不当作已验收。

- Task 1：`app/eval/cases.py`（`EvalCase`/`Assertion`/`load_cases()`/`validate_coverage()`/
  `summarize()`）；skip 三件套齐全性、skip 过期加载即失败、分层（角色 × 语言）是可校验约束、
  每条用例至少一条代码断言、加载器扫描手机号/邮箱/身份证形态字符串，均有单测覆盖；
- Task 2（**N1 唯一必须立刻可跑的评测**）：`app/eval/primitives.py`（白名单原语，
  `require_owned()` 跨商家探针、`SafeQueryService` 注入拒绝、`SessionRepository` 绑定不变量）、
  `app/eval/security_harness.py`（真实 ASGI + 真实 PostgreSQL + 原语的统一调度，断言只针对
  「最后一轮」，前置 setup 轮次不计入 `no_side_effect` 快照）、`app/eval/graders/assertions.py`
  （`http_status`/`error_code`/`audit_written`/`no_side_effect` 四种断言）、
  `app/eval/datasets/security/*.yaml`（CROSS 4 条、SQLI 3 条、IDENTITY 3 条、BUYERKEY 3 条，
  共 13 条，四类均 ≥3）、`tests/eval/test_security_gate.py` + `tests/eval/conftest.py`（零 skip 钩子）。
  **门禁本身按计划步骤 5 逐项验证过会真的挡**：把一条用例期望值改错→整体失败；不设
  `REQUIRE_INTEGRATION_DB` 指向不可达数据库→零 skip 钩子把 skip 转成失败（真实 exit code 1）；
  临时注册一个未登记用例的 v2 路由→路由覆盖守卫失败（并据此发现并补齐了一个真实覆盖缺口：
  `DELETE /api/v2/shop/sessions/current` 此前没有端点级安全用例，已补 `SEC-CROSS-004`）；
  三项验证完成后全部改回，复测 19 passed。路由覆盖守卫的枚举方式改用 `app.openapi()`
  而不是遍历 `app.routes`——当前 FastAPI 版本把 `include_router` 的子路由折叠进内部
  `_IncludedRouter`/`_EffectiveRouteContext` 惰性结构，`app.routes` 顶层已经读不出子路由的
  有效路径，这个改动本身是本轮排查中发现并修正的；
- Task 3：`app/eval/runner.py`（`QualityRunner`）+ `app/eval/graders/llm_judge.py`
  （`grade_with_rubric()`）。代码断言先跑，失败直接短路、不调用裁判（单测断言
  `fake_judge.call_count == 0`）；裁判函数签名结构上不接受候选实现身份参数，
  不是靠调用方小心不传；
- Task 4：`app/eval/report.py`（`render_report()`）。门禁结论只由 `security_results` 决定，
  随机攻击集只报告置信区间；渲染时过滤密钥环境变量的当前取值、手机号形态字符串，
  以及 `buyer_key`/`session_id` 等字段名本身（不只是值）；
- Task 5：`app/eval/baseline/FROZEN.md` 记录冻结点（`graph.py` blob 哈希、12 节点、
  `langgraph==0.6.11`、`DEMO_ANALYTICS_SEED_BASE=20260804`）+
  `tests/eval/test_baseline_freeze.py` 护栏测试；
- Task 6：`tests/eval/test_isolation.py` 用真实扫描测试（不只是手跑 `rg`）断言
  `app/eval/` 不被任何生产模块 import，并用临时注入违规 import 验证过会真的失败；
  `rg -n "api.deepseek.com" app/eval/ tests/eval/` 零命中。

**上述改绑错误码缺口已在 N1 审查整改中修复（2026-09-23）**：服务层将仓储
`SessionAlreadyBoundError` 转为 409 `SESSION_ALREADY_BOUND`，API 回归覆盖身份变化路径。
`SEC-BUYERKEY-003` 继续只验证仓储层不变量，HTTP 证据见会话路由测试；
完整整改与验证边界见 `plans/2026-09-22-n1-review-remediation.md`。

**Task 7 步骤 1–2（真实模型质量评测，2026-09-22 按 R3 取得用户明确同意后执行）**：
新增 `app/eval/datasets/quality/n1_baseline_quality.yaml`（6 条，`introduced_in: N1`，
问题文本全部取自既有 FakeLLM 测试里已验证会通过零 LLM 前置闸门的真实用例，locale 差异
只通过 `Accept-Language` 控制）与 `scripts/eval_quality_smoke.py`（R3 双段式：默认只打印计划，
`--yes` 才真实发出；硬编码 `deepseek-flash` + `https://api.deepseek.com` 并**强制覆盖**
`.env` 当时配置的已退役别名 `deepseek-v4-flash`，不信任环境取值；总调用次数硬顶）。
授权范围：模型 `deepseek-flash`、最多 66 次调用、预计费用 ¥1 以内、上限 ¥10。
**实际发出 8 次真实调用**（远低于上限），跑的是 v1 冻结商家 Chat 基线（当前唯一现成的真实
端到端链路，v2 工具循环不存在，步骤 3 的对照评测留给 N2）。
6 条用例 1 通过 / 5 失败，**发现两类基线自身的真实缺陷**（按 O4 不修复，只记录为基线特征）：
① CHAT 问候语路径产出内部占位文案而非真正问候语（中文「已完成结构化理解。」、
英文「Structured understanding complete.」，`degraded=false`，即真实生成路径产出，
不是模型降级）；② 显示语言与消息语言不一致时（`Accept-Language: en-US` 配中文消息）
分类会判定为 INVALID 并拒答，且同一退款金额问题即使中英文一致也被拒答，说明该问法本不在
基线已覆盖范围内。原始报告（含标题标签的事后更正说明）见
`docs/history/eval/n1-quality-baseline-2026-09-22.md`。
执行过程中修了一个本脚本自身的 bug（非生产代码）：`_ensure_demo_merchants()` 最初只补齐缺失
商家、不清理测试残留的无关商家行，导致 `seed_analytics()` 的「商家集合必须恰好三个」校验失败；
改为先 `TRUNCATE TABLE merchants CASCADE` 再插入演示三商家，此修复发生在任何真实调用之前，
未产生额外费用。

**过程事故与恢复**（如实记录）：验证 Task 6 隔离扫描测试时，临时在 `app/api/dependencies.py`
末尾追加了一行违规 import 用于确认测试会失败，随后用 `git checkout -- app/api/dependencies.py`
撤销——该命令撤销的是**整个文件**的全部未提交内容，而不是刚加的这一行，导致文件被整体还原到
上一次提交，误删了该文件此前未提交的 `enforce_keyed_rate_limit`（模块 D 为
`POST /api/v2/shop/sessions` 按 `shop_slug` 限流新增的函数）。已根据其唯一调用点
（`app/api/routes/v2/shop_sessions.py`）与既有 `enforce_rate_limit`/`SlidingWindowRateLimiter`
的模式重建该函数，并跑真实 PostgreSQL 全量回归确认无其他缺失（见下方验证证据）。
**教训**：对已知存在未提交历史的文件，不应再用 `git checkout` 做一次性实验的撤销，
应改用 diff/stash。

**验证证据**（2026-09-22，模块 E 完成后复测，含上述事故恢复后的确认）：
`REQUIRE_INTEGRATION_DB=1 uv run pytest -m "not security_timing"`（真实 PostgreSQL）全量
**2060 passed / 1 deselected**（deselected 是时序哨兵，`REQUIRE_SECURITY_TIMING=1` 单独运行
**1 passed**，未被跳过；相比模块 D 收口时的 2013 passed，净增 47 项——即本轮新增的评测骨架
自测与安全门禁用例，且此前记录的 2 个模块 C 既有失败本轮均已转绿，不再复现）；
`uv run ruff check .` 与 `uv run mypy`（174 个源文件）全绿（Task 7 收口后复跑同样全绿，
新增 `app/eval/datasets/quality/`、`scripts/eval_quality_smoke.py`）。
**未执行任何 Git 提交、发布或历史改写操作**（R2）；**Task 1–6 全程未调用真实 LLM；
Task 7 步骤 1–2 按 R3 取得用户明确同意后调用了真实 DeepSeek（8 次，deepseek-flash），
是本次更新里唯一的真实模型调用**（R3）。

工具循环、Skill、记忆管线、向量检索、MCP 仍未开始。
`app/tools/`、`app/skills/`、`app/agent/loop/`、`app/memory/` 四个目录仍未创建；
`app/eval/` 已创建（本轮，见上）。

**已发现但未处理的一项**（待用户决定，详见 §三）：PRD 与契约都没写「已退款 → 关闭」「已拒绝 → 关闭」由谁触发，
留给 N3 入口条件。原第二项「8 条 v2 路径没有后端实现方」已于 2026-09-21 由用户裁定并补入计划（见 §三「计划缺口」）。

**附件已延期**：附件上传、OCR、对象存储和通用异步 Worker 不在当前 N1–N5 范围；旧代码或契约中的
附件字段仅视为 v1 兼容残留，不得作为 v2 实现依据。

**工作树说明**：当前在 `main` 的既有未提交工作树上进行文档同步。本轮未执行 commit、push、tag、
PR 创建或合并，也未改写用户已有修改。

**外部参考沙盘**：`frontend/prototypes/commerce-agents-sandbox.html` 已补充商家活动/促销草稿、
预算拦截、购物计划/指南、购物车编辑、会话订单、旅行/电信/票务代表流程，并修正模拟事件字段。
保持单文件、无后端、无真实模型调用；原 Claude 在线 Artifact 未更新。
2026-09-18 离线 DOM 检查通过（10 个界面、全部预设场景及关键状态转换）；浏览器控制服务初始化失败，
本轮未完成真实浏览器视觉验收。下一步可直接打开 HTML 体验并据反馈调整；该原型不代表生产功能进度。

---

## 二、最近有效验证

> 下列结果都标注了**原始执行日期**。标「2026-09-22 复核」的行是今天在当前未提交工作树上的**实跑结果**，
> 它取代下方 2026-09-21 的全绿结论（那些是模块 C 代码写入之前的状态，仅作历史）；
> 标「契约冻结收口」的四行是 2026-09-21 的实跑结果；更早日期的行是历史基线，不代表今天重新验证过。

| 日期 | 范围 | 结果 |
| --- | --- | --- |
| 2026-09-23 N1 完整审核 | 独占本地 PostgreSQL 16.15（55439）；`REQUIRE_INTEGRATION_DB=1`、`REQUIRE_SECURITY_TIMING=1`，`uv run pytest -q --tb=short`；定向测试与静态检查 | **2435 passed / 1 failed / 0 skipped，611.72 秒**，唯一失败为里程碑登记守卫；时序哨兵通过。另定向 342 passed，ruff / mypy（208 文件）、前端 codegen:check / typecheck、会话 Adapter 5 项通过。N1 18/18 已审、17/18 通过；E1 的语言执行缺口及里程碑冲突待整改。全程无真实模型调用；详见 N1 审核记录 |
| 2026-09-23 N2 模块 C | `REQUIRE_INTEGRATION_DB=1 uv run pytest -q`（本地一次性 PostgreSQL，端口 55432）；`ruff check .`、`mypy app`、新文件 `ruff format`；`alembic upgrade/downgrade/check`；`scripts/export_openapi.py`、`npm run codegen` + `codegen:check`、`npm run test`、`npx vue-tsc --noEmit` | **后端 2431 passed / 1 skipped / 1 failed**：跳过的是需 `REQUIRE_SECURITY_TIMING=1` 的时序哨兵（本轮未另跑）；唯一失败是 `test_no_case_is_introduced_ahead_of_its_milestone`，**本计划开工前就是红的**（模块 D 登记 `SEC-CROSS-005` 时刻意接受的过渡态），本轮新增的 9 条 N2 安全用例同属该态，`CURRENT_MILESTONE` 由 N2 最后一份计划推进——模块 B 未开工，故本轮不推进。新增测试 94 条（`tests/unit/services/v2/` 46、`tests/integration/v2/` 48）+ 前端 Adapter 契约测试 11 条；迁移 `20260923_0028`（护栏补货上限）、`20260923_0029`（`operation_evidence_nonces`）升降级与 `alembic check` 通过，单 head；两项扫描零命中（`UPDATE products` 只在 `draft_apply.py`；`app/tools/` 不含审批证据）；ruff、mypy（208 文件）全绿；前端 593 passed、vue-tsc 与 codegen:check 通过。全程 FakeLlmClient，**无真实 LLM 调用、无 Git 操作** |
| 2026-09-22 N2 模块 A | `REQUIRE_INTEGRATION_DB=1 uv run pytest -q`（本地一次性 PostgreSQL，端口 55432）；`ruff check .`、`mypy app`；新文件 `ruff format --check` | **2268 passed / 1 skipped（263 s，2026-09-23 自查整改后复测）**，跳过的是需 `REQUIRE_SECURITY_TIMING=1` 的时序哨兵（本轮未另跑）。首轮全量曾有 2 个失败：`test_gates.py` 的 caplog 断言被 alembic `fileConfig` 禁用 logger 所致（与模块 B 同一既有测试环境问题），按同法加 autouse 夹具后复现序列通过、全量转绿。新增单测 99 条（`tests/unit/tools/` 54、`tests/unit/agent/loop/` 45）+ 真实 PostgreSQL 闸门 1 条；ruff、mypy（183 文件）全绿；依赖方向与身份字段两项扫描零命中。全程 FakeLlmClient，无真实 LLM 调用、无 Git 操作 |
| 2026-09-22 模块 E 收口（含模块 C 遗留失败由 Codex 修复后的复核） | `REQUIRE_INTEGRATION_DB=1 uv run pytest -q -m "not security_timing"`（本地一次性 PostgreSQL，端口 55432）；`REQUIRE_SECURITY_TIMING=1` 时序哨兵单独跑；`ruff check .`、`mypy app`、`ruff format --check .` | **2062 passed / 1 deselected**；时序哨兵单独 **1 passed**。此前记录的模块 D 收口行「2013 passed / 2 failed」里的 2 个失败（三商家种子重复确定性、可售量派生不可超卖）**已转绿**，本轮单独重跑确认 **2 passed**（Codex 收口，Sonnet 复核，见 §一）。ruff check、mypy（174 文件）全绿；`ruff format --check .` 仍有 38 个文件待格式化（未处理，非阻断项）。新增内容：`app/eval/` 评测骨架 + N1 安全硬门禁（13 条用例）+ Task 7 真实模型质量基线（6 条，8 次真实 `deepseek-flash` 调用，按 R3 授权执行）。无 Git 发布操作 |
| 2026-09-22 模块 C 收口 | `REQUIRE_INTEGRATION_DB=1 uv run pytest -q -rs --maxfail=1`（独立 PostgreSQL）；时序哨兵在另一独占库；`ruff check .`、`mypy app`、`alembic heads/check`、`downgrade base → upgrade head`；三商家种子 CLI | **2019 passed / 1 skipped（244 s）**；跳过的是需 `REQUIRE_SECURITY_TIMING=1` 的时序哨兵，另跑 **1 passed**。C 定向最终复测 **44 passed**；Ruff 与 mypy（165 文件）通过，单 head `0026`，完整升降级与 `alembic check` 通过。180 天 Seed 31383 行，S1–S4 首次 36、重复 0，5659 单投影零漂移；完整经营与场景二次重建后 13 表规范摘要一致。C1–C5 独立复审通过。无 Git 发布操作、无真实 LLM 调用 |
| 2026-09-22 模块 D 缺口补齐 | 同上全量 + `REQUIRE_SECURITY_TIMING=1` 时序哨兵 + `ruff check .` + `mypy` + `npm run codegen:check` | **2013 passed / 2 failed / 1 deselected（394 s）**，2 个失败同为模块 C 既有项；时序哨兵 1 passed；ruff、mypy（166 文件）、codegen:check 通过。补齐项：启动对账、日志脱敏、v2 会话 OpenAPI 专用哨兵、来源状态版本号重试与清理 Cron。Astra D1–D6 未审 |
| 2026-09-22 模块 D 收口 | `$env:REQUIRE_INTEGRATION_DB='1'; uv run pytest -q -m "not security_timing"`（本地一次性 PostgreSQL） | **1984 passed / 2 failed / 1 deselected（224 s）**。迁移链已从 `0017` 一路跑到新增的 `0025`/`0026`（单 head），此前记录的「迁移 0019 失败 → 260 个 error」已不再复现。2 个失败（`test_demo_determinism.py::test_three_merchant_seed_is_repeatable_in_postgres`、`test_n1_c_core_migrations.py::test_product_stock_is_derived_and_cannot_oversell`）**均属于模块 C**，涉及的文件本轮未改动，留给模块 C 自行收口。`security_timing` 标记的时序哨兵单独以 `REQUIRE_SECURITY_TIMING=1 uv run pytest tests/integration/test_session_isolation.py -m security_timing -rs` 验证：**1 passed**，未被跳过。同日另跑 `uv run ruff check .`（All checks passed）与 `uv run mypy app`（163 个源文件无错误）；前端 `npx vue-tsc --noEmit`、`npx eslint src/api/adapters/session.ts src/api/adapters/session.spec.ts`、`npm run codegen:check` 与全量 `npm run test` 均通过（**52 files / 582 passed**） |
| 2026-09-22 复核 | `$env:REQUIRE_INTEGRATION_DB='1'; uv run pytest -q`（本地一次性 PostgreSQL，独占；无真实 LLM 调用） | **不绿：7 failed / 1641 passed / 260 errors（149 s）**。260 个 error 全是依赖 `migrated_postgres` 夹具的用例，夹具里 `alembic upgrade head` 停在 0019。7 个 failed 分**四类原因**（逐个单独复跑核实过）：① 0019 的 `A value is required for bind parameter 'ORDER_PLACED'`，2 个（`test_migrations` 的 `first_migration_upgrades_empty_postgres_and_can_repeat`、`content_locale_migration_upgrade_downgrade_round_trip`）；② `test_demo_determinism::test_scenarios_are_stable_and_cover_s1_to_s4`，1 个：`AttributeError: 'borough_scenario_seed_for_test' 无 build_scenario_rows`，测试与 `seed_demo_scenarios.py` 接口对不上，**与迁移无关**；③ `test_migrations` 另 2 个（`llm_usage_observability…`、`content_locale_migration_backfills…`）报 `Destination … is not a valid downgrade target from current head(s)`，**原因未定位**，怀疑是 0019 失败后测试库停在中间修订，未证实；④ 两个适配器的 `test_api_key_never_appears_in_failure_logs`：**全量下失败，openai 那条单独跑通过，anthropic 那条未单独复跑**，顺序依赖，见 §三。C 的 4 个集成测试文件共 13 个用例：**9 passed（都不碰迁移库：模型登记、状态映射往返、种子确定性）/ 1 failed（②）/ 3 error**；那 3 个 error 恰是真正落库验证「可售量派生且不可超卖」「订单投影约束」「事件账本追加写且去重」的用例，**没有跑起来过** |
| 2026-09-22 复核 | `alembic heads` / `uv run ruff check .` / `uv run mypy app` / `ruff format --check .` | 迁移链是**单 head `20260922_0024`**（线性，无分叉）；ruff **53 项**（E501 46、UP017 3、I001 3、F401 1）、mypy **12 项 / 4 个文件**，**全部出在模块 C 的文件**（`app/models/analytics.py` 16、迁移 0018 15、0017 9、`test_demo_determinism.py` 4、`test_n1_c_core_migrations.py` 3、0019 3、`app/models/events.py` 2、`app/analytics/demo_data.py` 1；mypy 在 `demo_data.py`、`models/events.py`、`models/analytics.py`、`jobs/rebuild_projections.py`）；`ruff format --check .` **35 个文件**待格式化（2026-09-21 记录为 27 个，增量未逐个归因） |
| 2026-09-22 | 模块 B Task 6：`uv run python -m scripts.llm_smoke --protocol <openai 或 anthropic> --yes`（**真实 DeepSeek 调用**） | 两协议各 12 次、`deepseek-flash`、思考 `disabled`；openai **PASS 10 / OBSERVED 0 / FAIL 0**（已知 5154 token），anthropic **PASS 9 / OBSERVED 1 / FAIL 0**（已知 1665 token，缓存计量一项为 OBSERVED：上游未上报缓存字段）。原始记录 `docs/history/llm-smoke-2026-09-22.md`；结论与限制见 §四「模块 B 进展」。**这是本表里唯一的真实模型调用**，我未在本轮复核中重复执行 |
| 2026-09-21 契约冻结收口 | `uv run pytest tests/unit/schemas/v2 -q` | **262 passed**（common / shop_session / merchant_session / trade / after_sales / merchant_ops / drafts / memory / validator_guards）。**Task 3–8 未走 TDD 红灯步骤**，改用变异检验补证据：删除 `app/schemas/v2` 中 93 处校验拒绝语句逐个跑测试，首轮 77 被杀死 / 16 存活（校验互相掩护，未被单独验证），补 27 项用例后 **93/93 全部杀死**；变异脚本不入库，源码已还原并核对 |
| 2026-09-21 契约冻结收口 | `uv run pytest -q`（无 Docker，全量） | 无 Docker 时 **1426 passed / 261 skipped**；随后启动本地测试库（`docker compose -p borough up -d postgres`，一次性测试数据，未接触生产）并以 `REQUIRE_INTEGRATION_DB=1` 重跑：**1687 passed / 0 skipped**（含原 261 个真实 PostgreSQL 集成用例）。收口前有 2 个既有失败（`tests/api/test_demo_merchants.py` 生产环境用例缺 `BUYER_ALIAS_SECRET`，源于工作树里已有的 `config.py` 改动），已在测试助手补齐配置后转绿 |
| 2026-09-21 契约冻结收口 | `uv run ruff check .` / `uv run mypy app` | **All checks passed / 140 source files 无错误**；`ruff format --check .` 有 27 个既有 v1 文件待格式化（非本轮引入，未改动），本轮新增的 18 个文件均已格式化 |
| 2026-09-21 契约冻结收口 | 路径覆盖、禁用字段、幂等白名单、`extra="forbid"` 扫描 | 47/47 路径覆盖；`app/schemas/v2/` 无 `merchant_id` / `buyer_key` / `attachment_ids` / `float` / 自建错误码枚举 / 会话模块外的 `session_id`；带 `client_request_id` 的 10 个请求模型与 §8.7.3 白名单逐一对应；全部模型 `extra="forbid"` |
| 2026-09-21 路由归属核对 | PRD §11.2 的 47 条路径 × N1–N5 计划原文 | 核对时 **39 条有明确认领 / 8 条无后端实现方**（5 条会话签发路由、顾客端 `GET /shop/after-sales` 两条、商家端 `GET /merchant/customer-signals`）。方法：脚本粗匹配「方法 + 路径」得 33 条，再对剩余 14 条手工读计划原文；脚本会把前端计划提到路径误算为认领，所以以手工核对为准。同日经用户裁定补入计划后 **47 / 47 有实现方**（见 §三「计划缺口」）。纯文档变更，未改代码 |
| 2026-09-21 自查整改 | `$env:REQUIRE_INTEGRATION_DB='1'; uv run pytest tests/unit -q` | **1068 passed**；全部为单元测试，不代表数据库集成验证 |
| 2026-09-21 自查整改 | `$env:REQUIRE_INTEGRATION_DB='1'; uv run pytest tests/api/test_openapi_chat_contract.py tests/unit/core/test_error_codes.py tests/api/test_errors.py tests/unit/schemas/v2/test_common.py -q` | **107 passed**；1 条既有 LangChain 弃用提示 |
| 2026-09-21 自查整改 | 前端 `npx vitest run` / `npm run lint` / `npm run codegen:check` | **51 files / 577 passed**；lint、生成一致性检查通过。错误码回归修复前 **14 failed / 38 passed**，修复后全部通过 |
| 2026-09-21 自查整改 | 前端 `npm run typecheck` | 生产代码 `vue-tsc -b` 通过；测试类型检查仍有 **7 个错误**，见 §三 |
| 2026-09-21 | `uv run pytest tests/api/test_errors.py tests/unit/schemas/v2 tests/api/test_openapi_chat_contract.py -q` | **63 passed**；OpenAPI 哨兵已恢复通过；这批测试不访问数据库 |
| 2026-09-21 | `uv run pytest -q`（无 Docker，全量） | **1188 passed / 261 skipped**；skipped 均为需真实 PostgreSQL 的集成测试，未重跑 |
| 2026-09-21 | `uv run ruff check .` / `uv run mypy app` | **All checks passed / 133 source files 无错误** |
| 2026-09-21 | 前端 `npm run codegen:check` / `npx vitest run` | **generated.ts 与 docs/api.json 一致 / 51 files、535 tests 全部通过**；`typecheck` 既有 7 个错误未重新核对 |
| 2026-09-09 | 前端 Vitest | **51 files / 535 tests 全部通过** |
| 2026-09-09 | 前端 `npm run lint` | 干净 |
| 2026-09-09 | 前端 `npm run typecheck` | **剩 7 个错误**，见 §三「既有 TypeScript 基线」 |
| 2026-09-09 | 后端 `ruff check` / `mypy app` | 全绿 |
| 2026-09-09 | 后端 `uv run pytest`（无 Docker） | **1128 passed / 261 skipped** |
| 2026-08-24 | 后端 `REQUIRE_INTEGRATION_DB=1 pytest`（真实 PostgreSQL） | **1049 passed / 0 skipped / 0 failed** |
| 2026-08-22 | B7 九题真实模型验收（当时使用 `deepseek-v4-flash`） | 执行完毕；**出口判据未达成**。该模型名现已退役，仅作历史记录 |
| 2026-08-18 | 线上真实模型端到端 | 首次零降级回答跑通 |

**自动化测试全部使用 Fake/确定性 LLM。** 真实 DeepSeek 调用只发生在 2026-08-17～08-23 的人工排查与
定向验收中（后端记账约 3.5 万 token + 约 9.4 万 token，另有本地排查脚本约 2 万 token），每次均按 R3
单独取得同意。

---

## 三、未解决风险与约束

### 验证缺口

- 旧闭环计划登记的记忆污染、反馈衡量与证据传递仍是待核实的历史风险；按现行 PRD 对应阶段复核，
  不将旧方案直接作为 N1 新功能要求（见 `plans/2026-09-16-agent-business-loop-upgrade.md`）。
- **双语本地化的隔离与翻译不变量从未在真实 PostgreSQL 上跑过**：源正文不改、历史语言回填、人工译文
  过期判定、跨商家缓存隔离反例、游标分页重试等目前只有 Fake 仓储单测覆盖。
  `LocalizationRepository.purge_expired_machine()`（30 天缓存过期清理）**尚无 Cron 调用**。
  详见归档快照的 2026-09-05/09-06 条目与 `docs/deployment.md`「双语本地化」节。
- **测试 TypeScript 检查未通过**：2026-09-21 复跑 `npm run typecheck` 仍有 **7 个错误**：
  `chat.spec.ts` 的可空字段包含 undefined、`CategoryTable.spec.ts` 的行类型过宽，以及
  `DetailTable`、`ConfirmDeleteDialog`、`DocumentEditor`、`KnowledgeTree`、`PromptDialog`
  测试辅助函数的必填 props 类型丢失。本次未修改这些测试；不能将全部错误归为 mount 泛型问题。
- **真实 PostgreSQL 全量已转绿（2026-09-22，模块 E 收口后复核为 2062 passed）**：在独立可丢弃库上
  运行后端全量得到 **2062 passed / 1 deselected**；deselected 是需独占运行的安全时序哨兵，另在
  独占库验证 **1 passed**。C 的迁移、约束、回填与种子失败均已修复（含 Codex 收口的最后 2 个失败，
  见 §一模块 C 段落），详见 §二首行。
- **本机 Docker Desktop 当前不可用**：WSL 数据盘出现只读挂载错误。C 验证改用官方 PostgreSQL 16.15 Windows 二进制在临时目录启动一次性本地实例（127.0.0.1:55442）；未修复或重置 Docker 数据盘。常规 Compose 开发前需恢复 Docker 服务。本轮（模块 E）复用同一本地实例（127.0.0.1:55432），未重新核实 Docker Desktop 状态。
- **2026-08-24 的 Chat BI 收尾遗留两项未确认执行**：Task 2 Step 7 的 alembic check、Task 4 Step 6 的手工 CLI 试跑。本轮 alembic check 已针对当前 head 通过，旧 CLI 仍未复核。
- **格式门禁**：ruff check 与 mypy app 当前通过；`ruff format --check .` 现有 **38 个**文件待格式化
  （2026-09-22 模块 D 收口时为 35 个，含本轮模块 C/E 新增文件的格式化状态未逐个核对），
  仍未做过全仓批量格式化。

### 工程与环境

- **真实 PostgreSQL 测试必须独占测试库**：并发 `TRUNCATE_ALL_TABLES` 曾导致锁竞争与死锁。
- 测试容器是**一次性数据卷**：`alembic_version` 记录了已删除的迁移号时 `upgrade head` 会直接报错，
  需重建容器与卷（`docker-compose -p borough down postgres && docker volume rm borough_borough_postgres_data`）。
- **全量 pytest 会清空 `knowledge_documents` 与经营数据表**：真实模型验收前必须重新执行
  `backend/scripts/import_wiki.py` 与 `backend/scripts/seed_demo_analytics.py`。
- **Docker Desktop 在本机偶发无法启动或容器意外退出**：曾持续返回 `500 Internal Server Error` 近 20 分钟
  后自行恢复；2026-09-21 再次出现，需手动启动 Docker Desktop 后才恢复。集成测试连不上库时先排除环境瞬时故障，
  不要先怀疑代码。本机 Docker 里还有与本项目无关的 `docker-*` 容器（nginx、weaviate 等），不要动它们。
### 模块 A 复审（2026-09-21，契约修订 E8–E11 之后）

按契约计划 Task 9 的全部自检重跑，并逐模块对照 §8.7–§8.14 通读 `backend/app/schemas/v2/`：

- **自检全部通过**：禁用字段 / 自建错误码 / `float` / `session_id` 越界扫描零命中；幂等白名单与 §8.7.3 逐条一致（10 个端点）；
  全部 v2 模型 `extra="forbid"`；后端全量 **1696 passed / 0 skipped**（真实 PostgreSQL 可用），`ruff check .` 与 `mypy app` 通过；
  v2 Schema 单测 274 passed（连同 OpenAPI 哨兵共 289）；前端 `codegen:check` 一致、错误码相关 7 个文件 127 passed。
- **本轮修正的问题**：E8 内容缺口信号缺失（契约与 Schema 均补）；E9 购物车合并规则与 `cart_adjusted`；E10 `CursorPage`
  `has_more` 与 `next_cursor` 不一致未拦截；E11 图片白名单契约文字与实现漂移；§8.0.1 与会话计划 Task 7 的 OpenAPI 导出命令
  在仓库根无法运行，改为 `cd backend; uv run python ../scripts/export_openapi.py`；`n3-customer-skills-and-after-sales` Task 7
  原要求响应带 `viewed_audit_id`，与契约「查看审计不进入响应」冲突，已按契约改正。
- **留待对应路由任务处理的问题**（只能在服务层保证，不是本轮 Schema 错误）：
  1. `FulfillmentEvent.source_timezone`、`DailyBriefResponse.business_timezone` 只校验字符集，未校验是有效 IANA 时区；
  2. `pay_by = created_at + 30 分钟`、`paid_at ≤ pay_by`、草稿 `expires_at = created_at + 7 天`、记忆 `expires_at = last_confirmed_at + 180 天`
     只校验先后，精确时长由服务层保证；
  3. `MemoryPreferenceRequest` 缺确认时 Schema 抛普通校验错误，契约要求 `422 CONFIRMATION_REQUIRED`，须由 N4 路由显式映射；
  4. `issuer_fingerprint` 为无密钥 SHA-256；演示 Token 熵低时库内指纹可被离线猜测。演示 Token 本就可下发（R6 例外），风险低，D 开工时可改为 HMAC。

### 模块 A 复审修复（2026-09-22）

- 商品与购物车共用图片 URL 结构校验；`is_trusted_image_host` 在核对主机白名单前先执行相同结构校验，拒绝非 HTTPS、非 443 端口与静态路径跳转。
- 售后详情 Schema 拒绝时间或同时间 ID 倒序的事件；同一售后事项最多发起 47 次补充信息请求，给最长退货退款结案链留足 100 条事件容量。N3 状态机须在事务内追加事件前计数并拒绝第 48 次，当前尚无 v2 售后路由。
- 新增反例测试经历失败→修复→通过；`uv run pytest tests/unit/schemas/v2 -q` **285 passed**，`ruff check app/schemas/v2 tests/unit/schemas/v2`、`mypy app` 与前端 `npm run codegen:check` 通过。真实 PostgreSQL 下第二次后端全量复测为 **1796 passed / 1 failed / 0 skipped**，唯一失败是同期 B 模块 `test_api_key_never_appears_in_failure_logs` 的日志捕获断言；单独复测该用例 **1 passed**。此前全量还曾在 B 模块配置文件写入期间出现 8 个 LLM 配置测试失败，单独复测 **8 passed**。当前不能将后端全量称为通过，A Schema 定向回归已通过。

### 计划缺口与待决事项（2026-09-21 发现）

- **已解决：8 条 v2 路径曾没有计划负责实现后端路由**（2026-09-21 发现，同日用户裁定并补入计划）。现归属：
  1. **5 条会话签发路由** → `n1-session-identity` 新增 **Task 7「会话签发路由与 §8.0.1 同步」**（原 Task 7 自检顺延为 Task 8），
     同次完成 OpenAPI 导出、商家端 `generated.ts` 与 `frontend/src/api/adapters/session.ts`。依据：PRD §15 N1 会话身份、
     `AGENTS.md` §8.3 把「商家登录 Token」「顾客会话」标为 N1 起，且评测计划 Task 2 的 `SEC-CROSS-001` 直接 HTTP 调用
     `POST /shop/sessions/demo-customer`，没有这条路由模块 E 的硬门禁跑不起来。连带同步：评测计划 Task 2 前置加 D Task 7；
     `n2-merchant-vue-v2-migration` Task 2 改为接入已有 Adapter；`n2-shop-nextjs-app` 入口条件写明顾客端类型与 Adapter 由它自建；
  2. **购物车合并的真实实现原本也无人认领**（会话计划写「归交易组」，交易计划写「归会话计划」）。现定：N1 生产装配注入
     显式的 `EmptyCartMerge`，`n2-trade-closed-loop` Task 2 替换为真实实现并加测试，交易计划与顾客端计划各加一条入口条件；
  3. **顾客端 `GET /shop/after-sales` 列表与详情** → `n3-customer-skills-and-after-sales` Task 7（改名「双端售后只读路由」）；
  4. **商家端 `GET /merchant/customer-signals` 列表** → `n3-merchant-skills` Task 7，与 `list_signals` 工具共用查询服务。
     顺带修正该任务测试里不存在的信号种类 `CONTENT_GAP`（契约 `CustomerSignalKind` 只有三种）。
- **新发现、待决：访客购物车合并到已绑定顾客购物车时，同一商品的数量规则**（相加还是取大、是否受库存/限购约束）
  PRD C3、D7⑥ 与会话计划都没写。已在 `n2-trade-closed-loop` Task 2 标注「先回 PRD 补裁定，不在实现里自选」，不阻塞 N1。
- **「已退款 → 关闭」「已拒绝 → 关闭」由谁触发**：PRD §7.2 只列了迁移链，没写触发方（系统自动、商家草稿还是超时）。
  契约允许这两跳并给事件 `actor` 留了 `SYSTEM`。**2026-09-24 用户裁定：由系统与退款 / 拒绝同事务续跳**，
  同时补齐「待顾客补充信息 → 待商家处理」的顾客接口；已写入 PRD §7.2、C6、§11.2.2 与契约 §8.11。

### 容易重犯的错误

- **门禁全绿不等于行为正确**：`history=[]` 曾在 899 passed 的前提下存活到 2026-08-21 才被发现。
  凡「参考项目传了值、我方传空值」的形参，都要有一条**断言输入内容**的测试，而不只断言不抛异常。
- **`FakeLlmClient` 会掩盖整类缺陷**：它返回预写好的合法 JSON，因此「提示词有没有告诉模型该输出什么」
  在自动化测试里完全不可见。新增或修改任何 LLM 提示词时**必须同时加一条从 Pydantic 模型推导期望值的
  提示词契约测试**（范式见 `backend/tests/unit/intent/test_prompts.py`）。
- **两套重试是乘加关系**：`MAX_INTENT_RETRIES=2`（understand 最坏 3 次）与 `QUALITY_MAX_ATTEMPTS`
  （每轮最多 2 次）互相独立但共用同一个 `LlmBudget`。当前最坏路径 10 次，`MAX_LLM_CALLS_PER_REQUEST=10`。
  任何一边加码都要重算这条路径，否则会以「预算耗尽」的面目暴露成意图识别问题。
- **文字描述不等于已提交**：核对「某能力是否完成」时先跑 `git status` / `git log`，不要只读本文件。
  2026-08-24 曾发现 D1/D3 与整套 Chat BI 只存在于工作树里。
- **治理：本项目累计出现 4 次「绕过用户审阅门」问题**，第 4 次是编造用户决策原文并写入部署文档。
  核对任何标注「用户已裁定」「用户已确认」的条目时，应能在对话记录或归档快照中找到对应的真实用户发言，
  找不到则视为未裁定。
- `backend/tests/unit/agent/test_stage_reference_hygiene.py` 的 `CURRENT_STAGE` 常量停在 `"B7"`，
  只扫 `app/agent/**` 的字符串字面量；引入新的后端 stage 标记时记得同步推进。

### 业务与安全边界（现行有效）

- 未获用户明确同意，不得调用真实 DeepSeek API、收费 OCR 或日报生成（R3）。
- v1 代码当前仍由 Bearer Token 解析商家身份；N1 目标是 Bearer Token 只用于换取商家会话，后续请求
  使用 `X-Session-Id`。顾客会话与商家会话角色不可互换，所有经营查询强制注入已验证的 `merchant_id`（R5）。
- 团队知识与商家记忆保持单向边界：团队知识优先，记忆仅作同商家回退，**绝不升级写回团队库**。
- `GET /api/admin/ops/status` 只认 `X-Admin-Token`（`hmac.compare_digest`），`Authorization` 一律忽略；
  `ADMIN_TOKEN` 未配置时端点整体不挂载路由（404 而非 401/403）。
- `yshopping-merchant-ai 4/`、`yshopping-prototype/` 与 `vendor/` 整体只读，且只提供非规范性参考；
  `docs/yshopping-parity-audit.md` 是历史差异记录，不是开工前清零清单（R8/R9）。
- 本机可能有多个 git worktree 或并行分支；核对进度前先用 `git worktree list`、`git branch -vv` 确认
  自己看的是哪个分支。

---

## 四、下一步

按优先级：

**当前执行停点（2026-09-23，N2 模块 B 完成后）**：模块 B（交易闭环）Task 0–8 全部完成，**模块 C Task 8（S3 E2E）
与模块 D Task 1/Task 3 已解锁**。下一项：① 模块 C 执行 Task 8（S3）——**已完成**；② 模块 D Task 1 会话目录——**已完成**③ 安排 Astra 审查模块 B（N2-5/N2-6，本轮只有作者自审）；④ N2 三份计划都完成后由 N2 收尾推进
`CURRENT_MILESTONE`。浏览器端 S1 E2E 待 `n2-shop-nextjs-app`。

此前停点（2026-09-23，N2 模块 C 收口后）：模块 C 的 Task 1–7、Task 9 已完成并验证，
**Task 8（S3 端到端）在等模块 B**（`n2-trade-closed-loop` Task 3–4 的真实占库与实扣）。
下一项按优先级：① 安排 Astra 审查 N2-1/N2-2（模块 A）与 N2-3/N2-4（模块 C）——
模块 A 的 Task 2–4 复选框仍留白等这次审查；② 继续模块 B（交易闭环）：**Task 1 公开浏览已完成**（2026-09-23，见
「N2 模块 B Task 1 进展」），下一步 Task 0 与 Task 2 起；B Task 3–4 同时解锁模块 C Task 8 与模块 D Task 1/Task 3；
③ 模块 E（商家端 Vue v2 迁移）**18 / 18 全部完成**（2026-09-23，见「N2 模块 E 进展」），待 Astra N2-8 抽审；
另需裁定 v2 对话界面是否纳入 N2。
模块 C 是在 N1 D1–D6 / B1–B4 / E1–E3 与 N2-1/N2-2 尚未审查时按用户安排先行开工的，
审查若改动闸门或循环接口，C 的工具注册与商家 Chat 需回头补修。
本轮只写入可丢弃的本地 PostgreSQL；没有 Git 发布操作，也没有真实 LLM 调用。
此前停点：N1 模块 A、B、C 均已完成各自实现；C 的 29 步和 C1–C5 审查已收口，
与 D 共用的迁移链现为唯一 head `20260922_0026`。下一项是完成模块 D 的 D1–D6 独立审查，
再推进模块 E 的关键安全集与评测骨架。模块 E Task 7 的真实模型评测仍须单独遵守 R3 费用授权。
本轮 C 仅写入可丢弃本地 PostgreSQL；没有 Git 发布操作，也没有真实 LLM 调用。

> **计划状态（2026-09-21）**：**N1–N5 全部 20 份实施计划已写完，合计 456 个待办复选框（含入口条件；2026-09-21 补路由归属后由 447 增加 9；2026-09-22 N2 前置条件裁定后为 457；同日工具循环计划的注入用例登记并入交易计划 Task 8 后为 456），
> 其中模块 A 的契约计划已整份完成（45 / 45）。** PRD §11.2 的 47 条 v2 路径已逐条核对：字段契约 47/47 覆盖；
> 路由实现归属 **47 / 47 已落实**：5 条会话签发路由归 N1 会话计划 Task 7，其余 42 条由 N2–N5 计划认领
> （其中 3 条是 2026-09-21 补入的 N3 只读路由，见 §三「计划缺口」）。
> N2–N5 计划每份都有「入口条件」：开工前须核对上游计划的实际落地接口，不一致先改计划再动代码——
> 这是对"提前写的计划会过时"的防护，**执行者不得跳过**。
> **架构边界层**（§5.6、§6.9–§6.15）管 N2–N5 全程。

### N2–N5 十五份计划与执行顺序

| 里程碑 | 计划（`plans/2026-09-21-*.md`） | 步骤 | 收口场景 |
| --- | --- | --- | --- |
| N2 | `n2-tool-loop-and-registry` | 20 | — |
| N2 | `n2-trade-closed-loop` | 22 | S1（后端） |
| N2 | `n2-merchant-drafts-and-inventory` | 23 | S3（后端） |
| N2 | `n2-conversations-and-feedback` | 13 | — |
| N2 | `n2-merchant-vue-v2-migration` | 18 | S3（浏览器） |
| N2 | `n2-shop-nextjs-app` | 23 | S1（浏览器） |
| N3 | `n3-skill-loader`（阶段 A） | 20 | — |
| N3 | `n3-customer-skills-and-after-sales`（阶段 B） | 41 | S4 |
| N3 | `n3-merchant-skills`（阶段 C） | 34 | S2、S5、S6、S7 |
| N4 | `n4-memory-pipeline` | 21 | — |
| N4 | `n4-context-compaction` | 15 | — |
| N4 | `n4-hybrid-retrieval` | 23 | S7 回归 |
| N5 | `n5-mcp-readonly` | 13 | S8 |
| N5 | `n5-budget-ops-and-railway` | 18 | — |
| N5 | `n5-final-eval-and-closeout` | 34 | 全量验收 |

N2 内部顺序：工具循环 → 交易闭环 ‖ 草稿与库存（Task 1–7）→ 草稿 Task 8（S3 端到端，需交易闭环 Task 3–4）；
会话目录与反馈 Task 1–3 在两端 Chat 路由之后，Task 4 在两个前端各自 Task 1–2 之后。
**N2 模块划分（0、A–F）、任务级依赖、撞点与出口标准见 `plans/2026-09-22-n2-module-roadmap.md`（N2 总览，2026-09-22）**。
2026-09-22 用户裁定两处前置条件：草稿计划「交易闭环 Task 3–4 已完成」由入口条件下移为 Task 8 前置（步骤数不变）；
会话目录计划 Task 4 补入「商家端 Vue 迁移 Task 1–2 与顾客端 Next.js Task 1–2 已完成」前置（12 → 13 步）。纯计划文字变更，不涉及 PRD 与契约。
N3 内部（2026-09-24 重排为阶段 A / B / C，见 `plans/2026-09-24-n3-module-roadmap.md`）：A Skill 底座（加载器 + `load_skill` 受信通道 + 草稿按种类分派）→ B 售后闭环与顾客 Skill（含商家客服回复、售后类信号，**S4 在 B 收口**）‖ C 商家经营 Skill 的业绩、定价、导出、口径 → C 的完整简报、商品内容与内容缺口信号（需 B 的信号服务）→ C 工作台与两页合并评审。

### 2026-09-21 用户裁定（已按 PRD → 契约 → 计划 → 索引同步，均在任何实现开工前完成）

用户在本会话中逐项作出以下裁定。**这只是方案裁定：没有签发任何 MCP 凭证，也没有执行任何计划。**

| 裁定 | PRD | 契约计划 | 实施计划 |
| --- | --- | --- | --- |
| 会话凭证只存内存；**未绑定访客刷新后原购物车暂时无法访问（不是删除，服务端记录仍在）**；已绑定顾客重新绑定同一身份可恢复。页面与测试须明示 | C3 | —（无字段变化） | `n2-shop-nextjs-app` Task 2、Task 8 |
| MCP 凭证**只经后端命令行脚本签发与撤销**，不增加 HTTP 路径与自助页；限定商家、scope、有效期；**原值只展示一次**、库存哈希；撤销后下一次请求即失效 | A8 | §8.14 | `n5-mcp-readonly`；`n2-merchant-vue-v2-migration`（取消凭证管理界面） |
| M13 回答反馈与猜你想问、双端会话目录归入 N2 | §15 N2 | 组 1、2、7（字段已有） | `n2-conversations-and-feedback` |
| S3 在 N2 用**确定性最小简报**闭环，完整 M2 留 N3 | §15 N2、N3 | 组 5 简报来源说明 | `n2-merchant-drafts-and-inventory`、`n3-merchant-skills` |
| 记忆与个性化 Skill 移至 N4 | §15 N3、N4 | — | `n3-customer-skills-and-after-sales`、`n4-memory-pipeline` |
| v1 商家记忆不迁入 v2 | §14 | — | `n4-memory-pipeline` |
| 商家售后决定统一走草稿审批 | M9 | `DraftKind.AFTER_SALE_DECISION`，payload 不含金额 | 两份 N3 计划 |

**N3–N5 的 9 份计划入口条件已统一加注**：预写计划不是已验证实现，开工前须逐项对照上游
**实际落地**的接口，不一致先按四层顺序修正再动代码。

`n5-final-eval-and-closeout` Task 9 已由"收口时回写 PRD"改为"收口时只做复核"——
**PRD 不一致必须在发现当时处理，不得攒到 N5**。

### 写计划期间修正的问题

- 契约计划 §8.7.1 原写"不存在或不属于当前主体 → **404** `RESOURCE_NOT_FOUND`"，
  核对 `AGENTS.md` R5、O1、PRD §12.1 后改为 **403** `RESOURCE_FORBIDDEN`；
- 后端计划 §6.10 原要求 v2 循环"同步 `MAX_LLM_CALLS_PER_REQUEST`"，会改变 v1 行为——
  改为 v2 独立使用 `AGENT_LOOP_MAX_LLM_CALLS`（默认 12），v1 的 10 不动；
- **三处"靠 Cron 保证正确性"的设计**（30 分钟未支付关闭、草稿 7 天过期、顾客记忆 180 天过期）——
  Railway Cron 不保证准时，已全部改为**业务路径自检截止时间，Cron 只负责清理**；
- 草稿计划的审批证据原自拟一套密钥与防重放方案，与契约计划 §8.7.9 冲突——已改为按 §8.7.9 落地；
- 数据迁移计划的迁移目录原写 `backend/alembic/versions/`，实际为 `backend/migrations/versions/`。

### N1 五个模块与执行顺序

**模块划分（A–E）、各自所在的框架层、难度、任务级依赖与出口标准，统一见
`plans/2026-09-21-n1-module-roadmap.md`（N1 总览）**；下表只保留执行顺序与当前状态，避免两处各写一份。

| 模块 | 计划 | 步骤 | 状态（2026-09-22） | 覆盖 PRD N1 |
| --- | --- | --- | --- | --- |
| A 契约层 | `plans/2026-09-20-n1-v2-contract-freeze.md` | 45 | ✅ 45 / 45（字段契约 + Schema；无路由） | v2 字段契约 |
| B 模型接入层 | `plans/2026-09-21-n1-llm-client-and-adapters.md` | 25 | ✅ 25 / 25；B1–B4 于 2026-09-23 审查通过（历史真实冒烟共 42 次，本轮未重跑） | `LlmClient` 与双协议适配 |
| C 数据层 | `plans/2026-09-21-n1-data-migration-and-seeds.md` | 29 | ✅ 29 / 29；C1–C5 独立复审通过；遗留的 2 个测试失败已由 Codex 收口（2026-09-22，Sonnet 复核）；真实 PostgreSQL 全量 2062 passed / 1 个时序哨兵另跑通过；三商家完整播种与迁移往返通过 | 数据迁移与确定性种子 |
| D 身份层 | `plans/2026-09-21-n1-session-identity.md` | 27 | ✅ 实现完成，D1–D6 于 2026-09-23 审查通过；原计划勾选 12 / 27 为历史记录 | 会话身份、双重过滤、统一 403、5 条会话签发路由 |
| E 评测层 | `plans/2026-09-21-n1-eval-harness.md` | 20 | 🟡 19 / 20；E1–E3 全部已审，E2/E3 通过、E1 待整改复审；Task 7 步骤 3 新旧对照仍未完成 | 评测骨架 + 基线冻结 |

依赖关系（模块级；任务级依赖以总览为准）：

```text
A 契约 ──┬──→ D 会话身份 ──┐
         ├──→ C 数据迁移 ──┼──→ E 评测骨架（Task 2 安全集需要 D Task 1–5、Task 7 与 C 种子）
         └    B 模型客户端（无上游依赖，可与 C、D 并行；仅 E Task 7 真实评测需要它）
```

B 与 C 互不依赖，可并行；但 C 与 D 的迁移共用一条线性 Alembic 链（修订号 `0017`–`0026`），
并行时不得共用同一个测试库升降级（数据迁移计划「迁移链与测试库规则」）；B 与 D 都会改 `config.py`，需注意合并。
**两处跨计划重叠已显式排他**：`agent_sessions` 表只在会话计划建（数据迁移计划明确排除），
模型名迁移只在模型客户端计划 Task 5 做。

契约与会话两份计划已完成交叉审查：`SessionRole` 收敛到单一领域定义；访客绑定改为保留原凭证的
原地幂等绑定；顾客写操作与商家草稿审批分开建模；资源越权用一次定形查询、统一 403 与独立时序哨兵；
MCP 固定采用 2026-07-28 无状态协议；游标、确认令牌、审批证据与顾客别名均补齐签名或密钥边界。
这些仍是**计划约束**，尚未形成可运行实现。

**两项需 R3 单独授权且不阻塞其余工作**，一项的授权不覆盖另一项：模型客户端计划 Task 6
（双协议真实冒烟，每协议 12 次、合计 24 次，覆盖流式、多轮工具历史与缓存计量）、评测计划 Task 7
（真实模型质量评测；其中"与新循环对照"须等 N2 工具循环存在，N1 内最多完成基线侧）。
未授权时两项标记「待人工验收」，**不得宣称适配器已验证或质量评测已通过**。
（2026-09-22：Task 6 已执行，见「模块 B 进展」；Task 7 尚未执行，仍未授权。）

### 2026-09-22 N2 模块 A 进展

**计划**：`plans/2026-09-21-n2-tool-loop-and-registry.md`（执行记录见文末）。实现：Opus。
**已完成**：`backend/app/tools/`（`types.py`、`registry.py`、`gates.py`、`errors.py`）与 `backend/app/agent/loop/`
（`limits.py`、`runner.py`、`fencing.py`）；`config.py` 新增 `AGENT_LOOP_MAX_TURNS / _MAX_TOOL_CALLS / _WALL_CLOCK_SECONDS /
_MAX_LLM_CALLS` 与 `COMPACTION_MAX_CALLS`，启动时按预算公式校验；`create_app()` 启动时构建工具注册表（尚无业务工具）；
`DegradeReason` 只追加 `LIMIT`/`TIMEOUT`/`CANCELLED`。v1 `MAX_LLM_CALLS_PER_REQUEST`、`graph.py`/`state.py`/`prefilter.py` 未动。

**入口核对发现的文档不一致，已先回写再写代码**（后端计划 §6.9、§6.10「N2 落地补充」）：预算公式三处写法矛盾
（§6.10 原式按默认值 13 > 12），统一为 `max_turns + compaction + 2 × quality − 1`；`stop_reason` 补 `UPSTREAM`、`CANCELLED`；
护栏规则码放 `ToolDisplay.guardrail`（复用 `GuardrailCheckResult`），`reason_code` 保持 `ErrorCode`；`ToolSpec` 追加字段。

**勾选**：10 / 20（入口第 4 条、Task 1、Task 5、Task 6 步骤 1–4）。未勾选的 10 步都在等审查，不再有待开发项：
入口第 1–3 条待 N1 B1–B4 / D1–D6 / E1–E3 审查；Task 2–4 属 Astra **N2-1、N2-2 必审**，审查通过前按清单规则不勾选。

**2026-09-22 续做（用户指示「按建议继续完成 A」）**：
- **Task 5 已完成**：`backend/tests/eval/baseline_comparison.py` 让未改动的 `MerchantQaGraph` 与 `run_loop()` 在质量集
  `chat_metric` / `chat_greeting` 共 6 条用例上各跑一遍，两侧共用同一份脚本化 Fake LLM 输出与同一个受控查询替身；
  新循环侧挂的 `query_metric` 是**仅供对照的测试侧工具**，不进生产注册表。报告
  `docs/history/eval/n2-baseline-comparison.md`：两侧代码断言全部通过、零降级；LLM 调用合计基线 20 / 新循环 14
  （指标题 4 vs 3，闲聊 2 vs 1），受控查询次数一致。报告写明**只证明结构正确、不证明质量**；规则问答与拒答未覆盖
  （N1 质量集没有这两类用例）。`tests/eval/test_baseline_comparison.py` 断言报告可逐字复现。
- **Task 6 登记注入用例已移交交易计划 Task 8**：顾客对话入口要打的 `POST /api/v2/shop/chat` 由 B Task 6 建，
  且里程碑仍为 N1 时登记 N2 用例会让门禁失败。工具循环计划 21 → 20 步，交易计划 Task 8 的登记项并入该入口
  （步数不变），并写明登记与 `CURRENT_MILESTONE` 推进须在 N2 收尾同一次变更里落地。

**2026-09-23 自查整改**（用户要求自查后按建议修改，详见计划文末「自查与整改」）：自查实测发现三处严重问题并已修复——
① 确定性数字校验对紧贴汉字的数字完全失效（「净成交额是999万」不拦，原测试只用了带空格的句子，属假绿）；
② `ToolDisplay` 不符合 §8.7.5 冻结的 SSE 契约（自由文本摘要把「补货 37 件」这样的参数带进 display，
开工核对漏看了 §8.7.5）；③ 空白最终回答被当作正常完成（违反 R7）。同时补上事件出口 `on_event`、
v2 专用 `AGENT_LOOP_QUALITY_MAX_ATTEMPTS`（与 v1 解耦）、未注册工具名改为可修正错误、致命错误携带已完成部分，
以及缺失的测试；并行 / 串行测试改为断言重叠峰值，不再依赖墙钟阈值。

**风险与限制**：
- **访客绑定后来源资格不延续**：访客主体键是 `session_record_id`，绑定后变为主体摘要；访客在对话中看过的商品，
  绑定后在同一对话里加购会被来源闸门判为致命 403。N1 计划未规定是否迁移，属 B（绑定 + 购物车合并）的产品决定；
  未写死该行为的测试。
- **`LlmCostGuard` 仍未包装 `converse*`**（模块 B 遗留）：新循环接真实模型前必须补齐，否则每日预算熔断挡不住 v2。
- 确定性校验 `number_grounding_check`（`app/agent/loop/checks.py`）仍是启发式：个位整数、日期与时长不查，
  支持万 / 亿 / 千 / % 与「分→元」换算并按写出精度比对；宁可误拦降级为可见的 `VALIDATION`。
  中文大写数字（「三千」）与「翻了一倍」这类表述不检查；N3 Skill 可按领域替换或追加校验。
- 并行只读工具不得共享同一 `AsyncSession`：`DatabaseProvenanceStore` 每次读写各开会话；业务工具的 executor 须遵守同一约束。
- `CUSTOMER_CONFIRMATION` 工具在循环内只产出预览（`CONFIRMATION_REQUIRED`），真正写入走带界面确认证据的端点（§8.7.9）。
- 契约 §6.10「预算耗尽后同一 `client_request_id` 重试仍返回 `LLM_BUDGET_EXCEEDED` 且不调 LLM」属路由层幂等，本模块未覆盖，
  留给 B/C 的 Chat 路由。

### 2026-09-23 N2 模块 C（商家草稿审批与库存运营）进展

**已完成（Task 1–9，全部）：**

| Task | 产出 | 验证 |
| --- | --- | --- |
| 1 库存告警 | `services/v2/inventory_alerts.py`、`repositories/v2/inventory.py`、`GET /api/v2/merchant/inventory/alerts` | 判定单测 12 条 + API 10 条；变异检验：去掉商家过滤后隔离用例立刻转红 |
| 2 补货草稿工具 | `tools/merchant/`（`get_inventory_alerts` READ_ONLY、`draft_restock` MERCHANT_DRAFT）、`services/v2/drafts.py` | 集成 8 条：草稿不碰 `products`、记录变更基数、7 天过期、护栏可修正、来源闸门与跨店均为致命错误 |
| 3 审批证据 | `services/v2/approval_evidence.py`、`repositories/v2/operation_evidence.py`、迁移 `20260923_0029` | 单测 23 条 + 真实 PostgreSQL 8 条（只消费一次、随业务事务回滚、并发单一赢家、换连接池仍已消费、按用途分区） |
| 4 应用事务 | `services/v2/draft_apply.py`、`POST /drafts/{id}/apply` | 真实 PostgreSQL 20 条：固定步骤顺序、并发单一赢家、幂等重试、失败不吃证据、护栏按当时配置复检、跨店 403 + 审计 |
| 5 列表/丢弃/过期 | `GET /drafts`、`DELETE /drafts/{id}`、`jobs/expire_drafts.py` | 12 条：游标不重不漏、筛选绑定游标、丢弃幂等、终态不可迁出、过期任务只动 7 天以上且幂等 |
| 6 最小当日简报 | `services/v2/daily_brief.py`、`GET /briefs/daily/current` | 8 条：来源如实标 `DATABASE` 不伪装模型分析（R7）、条目可追溯到告警/草稿 ID、两个时间戳、排名连续且超出进折叠计数 |
| 7 商家 Chat | `services/v2/merchant_chat.py`、`POST /chat`（默认 SSE） | 7 条：**模型说「已为你批准并应用」时草稿仍是 STAGED、账本为空**；工具面只有两个工具；SSE 以 `turn_complete` 收尾且事件只含固定短句 |
| 8 S3 端到端 | `tests/e2e/test_s3_inventory_loop.py`；`app/eval/datasets/quality/scenarios/n2_s3_inventory_restock.yaml` | 见下方独立说明 |
| 9 自检 | 安全集 9 条、两项扫描、全量回归、五项完成门槛 | 见上方验证表 |

**2026-09-23 Task 8 解除阻塞并完成：** 前置条件（`n2-trade-closed-loop` Task 3–4 的真实占库与实扣）
已随模块 B 当日完成而满足，不再需要用直接改库存的捷径代替真实下单链路。

`tests/e2e/test_s3_inventory_loop.py`（Fake LLM，真实 PostgreSQL）编排完整链路：顾客经
`POST /api/v2/shop/orders`、`.../pay` 真实下单并支付 → 可售量降到阈值以下 →
`GET /api/v2/merchant/briefs/daily/current` 出现 `INVENTORY_ALERT` 条目 → 商家 `POST /api/v2/merchant/chat`
依次调用 `get_inventory_alerts`、`draft_restock` 起草补货（聊天全程不改库存，草稿停在 `STAGED`）→
经 `GET /drafts/{id}` 签发的真实一次性审批证据调用 `POST /drafts/{id}/apply` 批准应用 → 最后一步
**经顾客端公开浏览接口** `GET /api/v2/shop/stores/{shop_slug}/products/{id}` 断言 `stock_band` 从
`LOW_STOCK` 恢复为 `IN_STOCK`（不直接查库，证明两端共享同一份库存事实）；`rebuild_projections`
零漂移。`REQUIRE_INTEGRATION_DB=1 uv run pytest tests/e2e/test_s3_inventory_loop.py -v` 通过。

评测登记：新增 `app/eval/datasets/quality/scenarios/n2_s3_inventory_restock.yaml`
（`QLT-S3-001` zh-CN / `QLT-S3-002` en-US，`role: MERCHANT`、`introduced_in: N2`），只登记依赖模型
质量的那一段（商家问库存 → Agent 起草补货）；批准、应用与顾客端恢复是确定性事务，已由上面的
E2E 覆盖。真实模型跑该场景属于另行授权的人工验收（R3），不进默认测试。
`tests/eval/test_quality_scenarios.py` 新增 `test_s3_is_registered_in_both_locales`，其余通用结构性
校验（路由/原语已实现、不混入 v1 基线根目录）同步覆盖新场景，全部通过。

**执行期裁定（详见计划文件「执行记录」）：**

1. **步骤顺序：状态检查先于证据检查**（按本计划 Task 4 的固定顺序）。由此，「已消费证据 + 终态草稿」
   这条自然路径对外是 `409 ILLEGAL_STATE_TRANSITION`。安全属性因此表述为：**响应只由草稿状态决定，
   不泄露令牌是否有效**；§8.7.9 的「五类失败不可区分」在同一草稿状态下成立，由两条测试分别钉住
   （`STAGED` 草稿逐字段比对、终态草稿对任意令牌同构）。
2. **证据缺失必须走中性路径**：原实现里漏带 `approval_evidence` 会被 Pydantic 必填校验拦成
   `INVALID_REQUEST`，与伪造证据的 `CONFIRMATION_REQUIRED` 可区分——这是 §8.7.9 明令禁止的。
   已加 `require_evidence_field` 依赖，在请求体校验之前把该字段的任何问题统一成中性结果。
3. **过期判定落盘**：apply 与**读取**两条路径都自检 `expires_at` 并把状态迁到 `EXPIRED`；
   apply 的过期分支由路由显式提交后再抛 409（此时尚未消费证据，提交是安全的）。
   不能开第二个连接去写——那一行正被本事务的 `FOR UPDATE` 锁着。

**计划未写、但实现必需的跨模块补充（需要下游知晓）：**

- `app/services/v2/cursor.py`：§8.7.4 的签名游标此前全仓没有实现，本轮是第一个消费者。
  游标绑定端点、商家主体摘要、资源、筛选条件、语言与 `limit`，换任一项都 `422 INVALID_CURSOR`；
- `app/core/errors.py` 补 6 个 v2 `AppError` 子类（此前只有枚举与双语文案）；
- `LlmCostGuard.converse()` / `converse_stream()`：守卫此前只包了 v1 的 `complete()`，
  **商家 Chat 接真实模型会直接 `AttributeError`**。现在工具循环的每次模型决策都过同一道费用闸；
- `guardrail_configs.max_restock_delta`（迁移 `20260923_0028`）：护栏复检需要可改的数据而非代码常量；
- `tests/postgres.py` 的 `TRUNCATE` 列表补 `operation_evidence_nonces`（该表无外键，`CASCADE` 带不走）；
- `tests/api/v2/test_openapi_session_contract.py` 的哨兵：原断言「v2 路由不得有任何查询参数」
  与契约要求的分页/筛选参数冲突，已收窄为「查询参数必须在登记白名单内，且不含身份类名字」。

**未完成 / 未验证：** `CURRENT_MILESTONE` 仍是 `"N1"`（由 N2 收口统一推进，见 2026-09-23 裁定：
N2 三份计划——工具循环、交易、草稿——都完成后由 N2 收尾这一步单独执行，不由某一份计划顺带推进）；
Astra N2-3、N2-4 未审；商家 Chat 的 SSE 前端 Adapter 未写（JSON 与 SSE 的 UI 接入属模块 E）。
（Task 8 已于 2026-09-23 完成，见上方独立说明；模块 C 现无未完成 Task。）

### 2026-09-23 N2 模块 E（商家端 Vue v2 迁移）进展

**计划**：`plans/2026-09-21-n2-merchant-vue-v2-migration.md`；逐任务记录、全部执行期裁定与验证输出见
`.superpowers/sdd/2026-09-21-n2-merchant-vue-v2-migration/progress.md`。实现：Sonnet → Opus（同一会话中途切换模型）。

**已完成**：Task 1 `merchant-session` 凭证作用域；Task 2 会话生命周期（`stores/auth.ts`：按需换取、刷新恢复、
并发共用一次换取、**任何改选商家都同步丢弃旧会话并清空会话态 Store**、换取途中切店丢弃旧商家会话）；Task 3 生成类型与
Adapter；Task 4 审批界面 `views/ApprovalView.vue` + `stores/drafts.ts`（证据只在组件内存、网络重试复用同一
`client_request_id`、`CONFIRMATION_REQUIRED` 重新取详情不自动重试）；Task 5 `InventoryView.vue` / `TodayView.vue`
+ `stores/inventory.ts`；Task 6 `api/chatTurnEnvelope.ts`（v1 `done` 与 v2 `turn_complete` 共用最终响应解析）+
`api/adapters/chatV2.ts`；Task 8 自检。新路由 `/approvals/:draftId`、`/inventory`、`/today`（无导航入口，按 URL 进入）。

**Task 7 状态**：`e2e/s3/s3-inventory-loop.spec.ts`（`npm run test:e2e:s3`，真实后端 + 本人一次性 PostgreSQL + 脚本化模型
`backend/tests/support/e2e_s3_app.py`）跑通简报 → 起草 → 聊天「批准」无效 → 审批 → 告警消失 →
**顾客端公开商品接口档位 `LOW_STOCK` → `IN_STOCK`**（末步 2026-09-23 随模块 B Task 1 补齐，1 passed、无 fixme）。
变异检验两次：错误 `target_version` 让批准那一步失败；把档位阈值放大 20 倍让末步失败。
对话一步由测试进程调真实 `/api/v2/merchant/chat`，因为 Vue 端尚无 v2 对话界面（计划未安排，见下方风险）。

**本模块自查发现并修正的问题（供 Astra N2-8 审查对照）**：
1. Task 6 的 `tool_result` 被按 `ToolCallDisplay` 类型化、`step` 事件被丢弃、夹具用了契约外枚举值——实现与 mock 一起错，
   核对契约 §8.7.5 与后端真实 SSE 后修正；
2. 应用里原本无人调用 `openSession`，且 v1 商家切换器改选商家时不动 v2 会话（切到 B 仍用 A 的 `X-Session-Id`）；
3. 早先只跑 `vue-tsc --noEmit`，漏掉测试 tsconfig 下 7 个（全在本模块 spec 里的）类型错误；
4. `scripts/e2e-process.mjs` 在 Windows 上 teardown 会遗留孙进程（`uv run uvicorn` 占住端口）。

**未完成 / 已知风险**：
- **Vue 端没有 v2 对话界面**：计划 Task 6 只要求 SSE 适配层，`TodayView` 条目动作按钮只 `emit('fill-input')`，
  没有可填入的 v2 输入框。v2 对话界面是否在 N2 内补、放在哪个页面外壳里，需要单独裁定（PRD → 计划）；
- 会话切换只清 Store、不清组件本地状态（当前 v2 页面上没有切换器，暂不触发）；
- 默认 Mock E2E 的 4 条既有失败（分类名本地化用例过时、v1 顶栏 561/580px 溢出）与 4 处既有 Prettier 格式问题未处理；
- Astra N2-8 未审。

### 2026-09-23 N2 模块 B Task 0、2–8（顾客端交易闭环）进展

执行者：Claude Opus（用户授权，接手 Task 1 之后的全部 B 任务）。台账与全部执行期裁定：
`.superpowers/sdd/2026-09-21-n2-trade-closed-loop/progress.md`。无提交（R2），无真实 LLM 调用（R3）。

**已完成**：
- Task 0：注册表自检——顾客写工具名含 `order` / `pay` / `checkout`（按下划线切词前缀）注册失败（只读工具不拦）；
- Task 2：`GET /cart`、`PUT|DELETE /cart/items/{product_id}`（新表 `cart_items`，迁移 0030）；`CartMergePort` 生产装配换成
  `DatabaseCartMerge`（相加 / 99 截顶 / 剔除下架售罄 / 保留最新 50 行 / 清空访客车，`cart_adjusted` 如实反映）；
- Task 3：`POST /orders` 结账事务（`services/v2/checkout.py`）：重读价格、按商品 ID 排序条件更新占库、逐行快照、
  `ORDER_PLACED` + `ORDER_RESERVE` 事件、清空购物车，五元组幂等；券换算复用 `services/v2/coupons.py`
  （满减最大余数分摊、折扣逐行 HALF_UP）；迁移 0031 补 `orders.coupon_id / closed_at` 与 `order_items.title_snapshot`；
- Task 4：`POST /orders/{id}/pay|cancel` 与 `app/jobs/close_expired_orders.py`：同一条件更新抢 `PENDING`；
  支付自身检查 30 分钟截止（不依赖 Cron）；支付、关闭按商品 ID 顺序更新库存行（终审发现并修复并发死锁）；
- Task 5：`GET /orders`、`/orders/{id}`、`/orders/{id}/events`（游标绑定主体 / 店铺 / order_id，无效游标写审计）；
  不存在 / 非本人 / 别家店 / 历史订单统一 403（`require_owned`）；
- Task 6：顾客工具 `search_products` / `get_product` / `get_shop_policy` / `set_cart_item`（`app/tools/customer/`）与
  `POST /api/v2/shop/chat`（默认 SSE；两端 Chat 的线协议抽到 `api/routes/v2/chat_stream.py`）；迁移 0032 给
  `conversations` 加 `owner_kind / owner_id`，顾客对话按登录主体隔离，商家不能续写顾客对话；
- Task 7：`tests/e2e/test_s1_presale_to_payment.py`；质量场景登记在 `app/eval/datasets/quality/scenarios/`；
- Task 8：安全集新增 SEC-CART-001–003、SEC-ORDER-001–008、SEC-INJECTION-001–007（及 4 个白名单原语）；
  `docs/database.md`、OpenAPI / `docs/api.md`、`generated.ts` 同步。

**下游必须知晓**：`CURRENT_MILESTONE` 未推进（草稿计划 Task 8 未完成）；`get_shop_policy` 只引用路径含
「平台规则 / 退货 / 售后」的文档；模型可见的商品数据只有价格与库存档位；S1 质量用例刻意不放 `quality/` 根目录
（N1 基线脚本会按 v1 商家 Chat 误跑）。延后的小问题（Task 1 列表游标用 `isoformat()` 排序键等）见台账 Final 节。

### 2026-09-23 N2 模块 B Task 1（顾客端店铺与商品公开浏览）进展

**背景**：模块 B 尚无执行者；为解锁模块 E Task 7 末步，用户授权本会话（Opus）只接手 **Task 1**。
Task 0、Task 2–8 仍未开始，由后续 B 执行者从 Task 0 / Task 2 接手。台账：`.superpowers/sdd/2026-09-21-n2-trade-closed-loop/progress.md`。

**已完成**：4 条公开路由 `GET /api/v2/shop/stores/{shop_slug}`、`/products`、`/products/{product_id}`、`/coupons`
（`api/routes/v2/shop_catalog.py`），配套 `services/v2/stock_tier.py`（三档，阈值与商家库存告警共用 `AlertRules`）、
`services/v2/coupons.py`（券换算唯一出口）、`services/v2/catalog.py`（商品公开映射）、`repositories/v2/catalog.py`；
`services/v2/cursor.py` 新增公用 `descending()`。§8.0.1 五项门槛：契约已有；`docs/api.json` / `api.md` 已重导
（生成类型纯增 390 行、无删除）；`codegen:check` 通过；OpenAPI 哨兵登记 4 条路由并新增「公开模型不含数量/身份字段」断言；
Adapter 归模块 F（`shop/` 工程），商家端 Vue 不消费顾客端点。安全门禁的路由覆盖守卫随之补端点用例
`app/eval/datasets/security/n2_shop_catalog_public.yaml`（SEC-CATALOG-001–004：未知店铺与本店 slug 下取别家商品统一 403）
和白名单原语 `resource_scope.resolve_shop_slugs`；公开目录的匿名 403 不写审计（裁定，待 Astra 审）。
环境备注：`tests/unit/test_eval_skip_gate.py` 在带 `PYTHONIOENCODING=utf-8` 的 PowerShell 会话下会因 GBK 解码失败，Bash 下通过，属既有脆弱点。

**下游必须知晓的裁定**（全部见台账）：
- 计划原写 `stock_tier` ∈ `IN_STOCK / LOW / SOLD_OUT`，与契约 `stock_band` ∈ `IN_STOCK / LOW_STOCK / OUT_OF_STOCK` 不符，已按契约修正计划正文；
- **券 `discount_rate` 按「减免比例」解读**（PRD M6），`discount_bps = round((1 − rate) × 10000)` 是支付比例；
  **Task 3 结账必须复用 `services/v2/coupons.py`**，否则顾客看到的折扣与实扣不一致；
- 「未停用」= `coupons.state = 'ACTIVE'` 白名单；`rules_summary` 暂返回空串（无数据来源，不编造）；
- 商品内容按源语言返回，不接 `localize_many`（缓存未命中会触发真实 LLM，R3）；外部图片主机无配置项，一律置空。

### 2026-09-23 N2 模块 D（会话目录与反馈）进展

**计划**：`plans/2026-09-21-n2-conversations-and-feedback.md`。实现：Sonnet。

**2026-09-23 下午更新：Task 1（双端会话目录）已完成**（实现：Opus）。两端 Chat 路由落地后解锁，
下方「入口核对结果」描述的是上午的状态，Task 1 部分已过时。

- 路由：`api/routes/v2/shop_conversations.py`、`merchant_conversations.py`（列表 / 详情 / 删除各 3 条）；
  服务：`services/v2/conversations.py`（两端共用，`require_owned()` 单次定形查询，签名游标带审计）；
- 归属：顾客按「本店 + 登录主体」（访客 = 本次认证会话，已绑定 = 稳定主体摘要，与来源状态同口径，
  `tools/gates.principal_owner()` 是唯一来源）；商家按本店且 `owner_kind IS NULL`，同店顾客对话不可见；
- 排序按契约：顾客 `created_at DESC`、商家 `updated_at DESC`，消息 `created_at ASC`，均以 `id` 兜底；
- 删除：软删除 + 同事务清来源状态；删除后详情 / 再次删除统一 403（契约 §8.8.2，计划草图写的
  「二次删除 200/204」与契约不符，以契约为准）；删除的对话不能被续写；
- 迁移 `20260923_0033`：`conversations.surface`（v2 端标记，**v1 历史对话不进入 v2 目录**）、
  `conversations.deleted_at`、`messages.response_payload`；两端 Chat 服务经 `record_turn()` 写消息，
  显式时间戳保证「先问后答」并推进 `updated_at`；商家 Chat 对非 UUID 的 `conversation_id` 不再 500；
- 测试：`tests/integration/v2/test_conversations.py` 15 例（含变异检查）；安全集
  `n2_conversation_directory.yaml` SEC-CROSS-006~011 + 原语 `resource_scope.seed_foreign_conversation`；
  OpenAPI 与 `generated.ts` 已重新导出。

**v2 回答反馈缺口（已修复，用户裁定方案）**：v2 Chat 回答原先不写 `answers` 表，而 `feedback.answer_id`
外键指向 `answers.id`，对 v2 回答提交反馈一律 403。迁移 `20260923_0034` 给 `answers` 加 `surface`，
v1 唯一索引 `(merchant_id, client_request_id)` 收窄为只约束 v1 行；`record_turn()` 同事务写回答行（`id` 即响应 `id`）；
商家反馈只接受 v1 与 `MERCHANT` 回答，顾客回答与不存在同为 403；**Chat BI 暂只统计 v1**——其命中率等口径按 v1 回答
结构解析，v2 接入前需先定口径（待办）。
**同时堵住一处既有 R5 泄露**（模块 B 上线顾客 Chat 后即存在）：v1 `/api/conversations` 只按 `merchant_id` 过滤，
商家可经 v1 目录列出并读取本店**顾客**的 v2 对话；现 v1 仓储的对话查找、回答幂等查找与 v1 反馈只认 v1 数据，
越界访问按 v1 既有语义返回 `403 MERCHANT_SCOPE_VIOLATION`。v2 Chat 续写也只接受本端 v2 对话。
测试 `tests/integration/v2/test_v2_answer_persistence.py` 8 例（其中 3 例经变异检查确认能拦住回退）。

**Task 3（猜你想问）2026-09-24 完成**（实现：Sonnet）：契约 §8.7.10 给 `V2ChatResponseBase` 补 `suggestions` /
`suggestion_alternates`（可选、默认 `[]`，至多 3 条 / 5 组）；`services/v2/suggestions.py` 由后端生成候选，
每条标注回答它的工具，测试核对该工具在当前角色的真实工具面上，顾客端与商家端候选互不相交；
两端 Chat 响应携带候选并随 `record_turn()` 落盘，详情读回一致，降级回答照常带候选且降级字段不变。
**用户未给内容方向，问题库由我按现有工具面拟定，待审阅**（账本 `.superpowers/sdd/2026-09-21-n2-conversations-and-feedback/progress.md`）。
**订单 / 售后问题刻意不进候选**——N2 里它们由页面回答、对话没有对应工具，N3 补工具再加；「模型只排序」只落了
`constrain_rewrite()` 校验函数，N2 没有把任何模型接进来（不增加每轮 LLM 调用）。
验证：新增 90 + 11 + 6 例；ruff / mypy（231 文件）全绿；OpenAPI / `generated.ts` 已重新导出且 `codegen:check`、
前端 `typecheck` 通过，前端 **647 passed**；后端全量（内嵌一次性 PostgreSQL，Docker Desktop 本机无法启动）
**2822 passed / 2 failed**，两项失败均与本次改动无关：`test_chatbi_rollup::test_rollup_counts_source_and_removes_stale_rows`
是内嵌库缺时区库（`Asia/Shanghai` 不识别）；`test_draft_apply::test_network_retry_with_same_request_id_returns_first_result`
是模块 C 既有问题——`require_evidence_field` 守卫先于幂等检查，缺证据的同 `client_request_id` 重放得 422，
而测试（§8.7.9「先查幂等再验证证据」）期望 200，**待模块 C 责任人裁定改测试还是改守卫**。全程 Fake LLM，无 Git 操作。
**Task 4 仍受阻**：需 `n2-shop-nextjs-app` Task 1–2 先建顾客端工程（该计划 0/23，用户 2026-09-24 裁定暂缓）。

**入口核对结果（开工前按计划要求核对）**：`n2-trade-closed-loop` Task 6（`POST /shop/chat`）与
`n2-merchant-drafts-and-inventory` Task 7（`POST /merchant/chat`）**均未开工**——两份计划本身的
Task 1–7 都还没有任何代码（`backend/app/api/routes/v2/` 只有 N1 遗留的 5 条会话路由）。
因此 **Task 1（会话目录）与 Task 3 的顾客侧候选内容按入口条件判定为受阻，未实现**：

- **Task 1 受阻原因**：v1 `conversations` 表没有 `buyer_key` / 访客会话归属 / 软删除列，
  这些列由谁加、加成什么形状是 Chat 路由（Task 6/7）落地时才会做的设计决定；在两条 Chat 路由
  都不存在、无法产生真实 v2 对话的情况下抢先建目录服务，要么等两个月后回来对接，
  要么现在就替 Sol/Opus 做设计决定并冒撞车风险——两者都不如照计划等待。**未写任何代码。**
- **Task 3 顾客侧受阻原因**：v1 `services/suggested_questions.py` 的预置问题库**全部是商家话术**
  （GMV、退款、工单……），顾客导购/订单/售后的问题库在 v1 不存在，"复用"无从谈起，需要新写内容；
  且 v2 `V2ChatResponseBase`（`backend/app/schemas/v2/common.py`）目前**没有** `suggestions` /
  `suggestion_alternates` 字段——契约层还没决定"猜你想问"在 v2 怎么下发，写了服务也接不到任何响应。
  **未写任何代码**，留待契约补上字段、且顾客内容有人拍板之后再做。

**已完成的部分（不依赖 Task 6/7，可独立验证，因此按计划"受阻不停摆其余工作"完成）**：

- **Task 2：商家回答反馈**（PRD M13，契约 §8.14）全量落地并通过验证：
  - `POST /api/v2/merchant/answers/{answer_id}/feedback`（`api/routes/v2/merchant_feedback.py`）；
  - `services/v2/feedback.py`：采纳（`ADOPTION`）与赞踩（`REACTION`）分列两条独立 SQL 更新路径
    （`AnswerRepository.set_adoption` / `set_reaction`），互不覆盖对方列——v1 旧的
    `upsert_feedback()` 一次性覆盖两列的写法**不能**直接复用，这正是 §8.14.2 不变量 4 要防的问题；
  - `require_owned()` 的单次定形查询用法（`AnswerRepository.fetch_scoped`），越权与不存在统一
    `403 RESOURCE_FORBIDDEN`，含非法 UUID 路径参数（同一判定路径，不单独走 422）；
  - **v2 幂等基础设施是本次新建**（`idempotency_records` 表此前只有迁移，没有任何消费方）：
    `repositories/v2/idempotency.py` + `services/v2/idempotency.py` 按 §8.7.3 落地唯一域
    `role + principal_digest + merchant_id + operation + client_request_id`、并发插入用嵌套事务
    捕获唯一约束冲突退回已存在分支、摘要不符 `409 IDEMPOTENCY_KEY_REUSED`、处理中
    `409 REQUEST_IN_PROGRESS`；新增 `get_principal_secret()`（`api/dependencies.py`，无配置时
    退化到 `_DEV_BUYER_ALIAS_SECRET`，与 `_DEV_EXPORT_SIGNING_SECRET` 同一模式）供
    `principal_digest()` 的全部调用方共用；这套基础设施是通用的，后续任何 N2 写路由都应直接复用，
    不要各自重新发明；
  - 迁移 `20260923_0027`：`feedback` 表新增可空 `reason` 列（v1 不写入，不影响 v1 行为）；
  - 测试：`tests/api/v2/test_merchant_feedback.py`（9 例，真实 PostgreSQL）覆盖不覆盖语义、
    跨商家 403 不可区分、访客/商家角色互调 403、同 `client_request_id` 重放与摘要不符冲突、
    **两个商家复用同一 `client_request_id` 不互相冲突**（验证幂等域确实按主体摘要隔离，不是
    简单复用 v1 单商家索引）、非法 UUID 路径参数同样 403。
  - `docs/api.json` / `docs/api.md` / `frontend/src/api/generated.ts` 已按 §8.5 流程重新导出
    （`codegen:check` 通过）；`tests/api/v2/test_openapi_session_contract.py` 从"N1 恰好 5 条
    v2 路径"改为"登记制"哨兵，登记本条新路由，其余约束不变。
  - **前端 Adapter / UI 未做**：v2 商家前端工程与会话凭证尚未接入（属 Task 4，locked 到
    `n2-merchant-vue-v2-migration` Task 1–2），本次只做到契约与后端。

- **附带的评测基础设施修复（Task 2 派生，非计划列出的文件）**：`test_every_v2_route_has_an_endpoint_security_case`
  路由覆盖守卫要求新上线的 v2 路由必须有登记的端点级安全用例，而现有 `SecurityHarness` 的
  ENDPOINT 表单不支持路径参数（此前 N1 的 5 条会话路由都没有路径参数，没暴露这个缺口）。
  已扩展 `app/eval/security_harness.py`（`{state:key}` 占位符，从前置 PRIMITIVE turn 写入的
  `state` 里取值替换进 `request.path`）与 `app/eval/primitives.py`（新增
  `resource_scope.seed_foreign_answer`），登记 `SEC-CROSS-005`
  （`app/eval/datasets/security/n2_merchant_feedback_cross_tenant.yaml`）验证跨商家反馈 403 +
  审计 + 无副作用。这套占位符机制是通用的，后续任何带路径参数的 v2 路由（订单、草稿、售后……）
  登记安全用例时都能直接用。

**已知且刻意接受的一条红测试**：`tests/eval/test_security_gate.py::test_no_case_is_introduced_ahead_of_its_milestone`
失败，报 `SEC-CROSS-005`。原因：该用例如实标注 `introduced_in: N2`，但 `CURRENT_MILESTONE` 仍是
`"N1"`（未到 `n2-trade-closed-loop` / `n2-merchant-drafts-and-inventory` 收口，APPROVAL /
SELFAPPROVE / INJECTION 三类 N2 安全用例都还是 0 条，此时把 `CURRENT_MILESTONE` 提前改成 `"N2"`
会让 `test_due_categories_have_at_least_three_cases` 对这三类新增三处失败，比现状更差）。
这与 `n2-trade-closed-loop` 计划 Task 8 为它自己的 `SEC-INJECTION-*` 用例写明的场景是同一处结构性
冲突（v2 路由先于 N2 收尾落地时，"路由覆盖守卫"与"里程碑顺序守卫"天然二选一），处理方式也一致：
如实标注、不伪造 `introduced_in`，把 `CURRENT_MILESTONE` 的推进留给 N2 收尾统一执行。
**这是本次唯一未转绿的测试**，其余不受影响。

**验证证据**：
```powershell
cd backend
$env:TEST_DATABASE_URL = 'postgresql+psycopg://borough:borough_local@127.0.0.1:55432/borough_test'
$env:REQUIRE_INTEGRATION_DB = '1'
uv run pytest -q -m "not security_timing"
```
**2279 passed / 1 failed（上述已知项）/ 1 deselected**；`uv run ruff check .`、`uv run mypy app`
（190 个源文件）全绿。前端 `npm run test -- --run`：582 passed；`npm run codegen:check` 通过。
迁移升降级往返（`tests/integration/test_migrations.py`）11 passed，含新迁移 `20260923_0027`。
无 Git 发布操作；全程 Fake/无真实 LLM 调用。

### 2026-09-22 模块 B 进展

**已完成（25 / 25）**：`app/llm/` 新增 `converse()` / `converse_stream()` 与数据类（`LlmMessage`、`ToolSchema`、`LlmToolCall`、
`LlmTurn`、`ReasoningReplay`、流式事件），OpenAI 与 Anthropic 两个适配器（`openai_adapter.py`、`anthropic_adapter.py`，
共用 `adapter_support.py`），`FakeLlmClient(turns=[...])` 工具调用脚本，`LLM_PROTOCOL`（默认 `openai`）与
`LLM_THINKING`（默认 `disabled`）两个开关，默认模型迁移到 `deepseek-flash`；契约见 `docs/backend-development-plan.md` §6.17。
**未动**：`complete()` 签名与行为、`app/agent/graph.py`；`LlmClient` 本身不加方法（工具调用放在子协议
`ConversationalLlmClient`，理由见计划「执行期记录」B1）。

**验证**：`tests/unit/llm` 227 passed（新增 193）、`tests/unit` 1522 passed；**连真实 PostgreSQL 的 `tests/unit` + `tests/api`
1729 passed / 0 failed**；变异检验 22 / 22 + 8 / 8 杀死；冒烟脚本先经假服务器离线演练。**没有执行任何 Git 操作。**

**真实调用（R3，2026-09-22，三次授权累计 42 次，估算约 $0.006）**：首轮每协议 12 次（思考 `disabled`）；追加 6 次
（Anthropic 原始 `usage` 诊断 2 次、思考 `enabled` 多轮工具历史每协议 2 次）；第三次 12 次（`--suite extended`：省略推理内容、
思考模式流式与并行工具、Anthropic 流式原始 usage）。两协议功能全部通过。**Anthropic 用量口径缺陷已证实并修复**（`input_tokens`
不含缓存命中部分），流式下同一请求两协议折算逐项相同。**文档所称「省略推理内容会 400」实测未复现**（两协议均 200），回放仍保留。
**`LLM_PROTOCOL` 默认保持 `openai`**（证据上已可切换，但无可观察收益）。详见后端计划 §6.17 与 `docs/history/llm-smoke-2026-09-22.md`。

**§三第 3 项（日志守卫用例全量下不稳定）已修复**：根因是 `migrations/env.py` 的 `fileConfig` 默认禁用已存在的 logger；
已按同样顺序复现（先触发 alembic 再跑两条用例 → 2 failed），在 `tests/unit/llm/conftest.py` 加 autouse 夹具重置
`app.llm.*` logger 后同序列 2 passed。

**未完成与限制**：
- **✅ 全量回归已转绿（2026-09-22，模块 C 收口后复核）**：`REQUIRE_INTEGRATION_DB=1 uv run pytest -q -rs`
  **2019 passed / 1 skipped（时序哨兵，需 `REQUIRE_SECURITY_TIMING=1` 单独运行）/ 0 failed**（188 秒，独占测试库）；
  此前归咎于模块 C 的两个失败（`ck_products_reserved_le_on_hand` 库存约束、三商家种子重复性）单独复测与全量中均已通过；
  `uv run ruff check .`（全绿）与 `uv run mypy app`（165 个源文件无错误）。阻塞方模块 C 已完成 29/29 步并通过 Astra C1–C5 复审
  （见 `plans/2026-09-22-astra-checklist.md`），本模块「全量回归」验收条件已满足，`plans/2026-09-21-n1-llm-client-and-adapters.md`
  的验证限制记录已同步更新；
- **Astra 清单 B1–B4 仍未审**（`plans/2026-09-22-astra-checklist.md` 规定必审项审查通过前不得勾选）——
  这是本模块唯一剩余的收尾项，全量回归已不再是阻碍；
- **仍无真实样本**：推理耗尽 `max_tokens`、写入缓存（`cache_creation_input_tokens`）非零两种情形；
- **`LlmCostGuard` 尚未包装 `converse*`**：每日预算熔断目前只挡 `complete()`，N2 工具循环接入前必须补齐；
- **本地 `backend/.env` 里 `LLM_MODEL` 仍是退役别名 `deepseek-v4-flash`**，会覆盖新默认值，需手动改（Railway 变量同理）。

### 2026-09-22 模块 D 进展

**实现完成，待 Astra 审查（勾选 12 / 27）**。文件与验证明细已写入 §一「模块 D」，此处只记录
执行期裁定，避免两处各写一份：

- **`shop_slug` 复用 `Merchant.merchant_code`**：当前没有独立店铺表，`merchant_code` 本身就是稳定、
  唯一、小写连字符格式的商家标识；新增 `MerchantRepository.get_active_by_shop_slug()`，不建冗余列；
- **迁移号从 `0025` 起**（不是计划文字写的 `0017`）：因为模块 C 已把 `0017`–`0024` 用掉，两份计划共用
  同一条线性链，动工时以 `uv run alembic heads` 的实际单 head 为准，不看计划里的旧编号；
- **来源状态清理范围**：Cron 只删除「已过期且从未绑定身份」的访客会话（`principal_kind = GUEST_SESSION`）留下的
  来源状态，与计划 Task 6 文字一致；已绑定会话与商家会话不清理（会话注销不删除业务对话）；
- **撤回此前的偏离**：`conversation_provenance` 首版曾用 `INSERT ... ON CONFLICT DO UPDATE` 代替版本号重试，
  2026-09-22 已改回计划规定的版本号条件更新 + 最多重试 3 次，并补了同一记录并发写不丢更新、重试有上限两条测试；
- **`POST /shop/sessions/demo-customer` 的 404 判定拆成两层**：路由先查 `settings.demo_deployment_mode`
  （部署开关关闭 → 404），服务层再查 `demo_customer_identities` 是否有当前店铺（未配置 → 同一 404）；
  两者对外文案与状态码完全一致，不泄露是哪一层导致不可用；
  两条 DELETE 会话路由补了 `422` 到 `error_responses(...)`（`request` 头校验失败的 FastAPI 默认形状）——
  这是仓库既有约定（`tests/api/test_openapi_chat_contract.py` 的通用漂移哨兵要求），不是本计划专属新增；
- **CORS `X-Session-Id` 补漏**：`app/main.py` 的 `_ALLOWED_HEADERS` 此前没有它，`docs/deployment.md`/
  `AGENTS.md` §八已经要求但代码没跟上；5 条 v2 路由落地后这条路径才第一次真正需要它，本轮一并修好并
  在 `tests/api/test_cors.py` 补测试参数；
- **前端 Adapter 范围按计划收紧**：`frontend/src/api/adapters/session.ts` 独立发起 `fetch`，不复用
  `transport.ts`（那是聊天专用的 `ChatTransport`/SSE 基础设施），不读 `credentials.ts` 的凭证注册表——
  Token 与会话 ID 都由调用方显式传参，因为 Store 接入本就不在本计划范围（`n2-merchant-vue-v2-migration`
  Task 2 负责）。

**测试执行说明**：安全硬门禁的独立时序哨兵（`security_timing` marker）默认在全量回归里被
`-m "not security_timing"` 排除，需要 `REQUIRE_SECURITY_TIMING=1` 单独跑；本轮两种模式都跑过，
细节见 §二「2026-09-22 模块 D 收口」一行。

### 2026-09-21 模块 A 收口记录

模块 A 的 45 步全部完成后，用户授权执行者处理遗留事项。以下是**计划文字没覆盖、由执行者裁定**的事项，
已按 PRD → 契约 → 计划 → 索引同步，**可被用户推翻**（登记在契约计划「执行期裁定」E1–E11；
2026-09-22 的 E12–E14 修复见上文「模块 A 复审修复」）：

| # | 问题 | 裁定 | 同步位置 |
| --- | --- | --- | --- |
| E1 | PRD §7.2 没有客服工单（`TICKET`）的结案路径，状态机走不到终态 | 增加「待商家处理 → 已同意（即已处理）→ 关闭」，只限工单；退货退款、仅退款走该跳一律 `409` | PRD §7.2；契约 §8.11.2；`after_sales.py`；N3 售后计划 |
| E2 | 支付状态 `CLOSED` 没有对应事件，无法「由事件派生」；数据迁移计划 M3 已有「已关闭」事件而 PRD 没有 | PRD §7.1、C5 补入「已关闭」事件；契约事件类型 `ORDER_CLOSED` | PRD；契约 §8.10.2 |
| E3 | v2 反馈要区分「采纳」与「赞踩」且互不覆盖，N2 反馈计划的字段与契约不一致 | `kind: ADOPTION \| REACTION`；响应返回两者当前完整状态 | 契约 §8.14；N2 反馈计划 |
| E4 | N2 库存与 Vue 计划引入契约没有的 `days_of_supply_note` | 删除：`days_of_supply = null` 已表示「未知 / 无近期销量」 | 两份 N2 计划 |
| E5 | N2 草稿计划的审批证据绑定少了 `target_version`、主体与勾选条目 | 以契约 §8.13 为准 | N2 草稿与库存计划 |
| E6 | N2 交易计划要求订单详情「同时返回事件数组」，与契约「不内嵌无界事件数组」冲突 | 以契约为准；支付写 `PAYMENT_CONFIRMED`，关闭写 `ORDER_CLOSED` | N2 交易计划 |
| E7 | 其余设计选择 | 购物车 `DELETE` 返回 `200` + 完整购物车；草稿 apply 增加可选 `accepted_entry_ids`；关闭记忆确认字段为 `"yes"`；当日简报未生成时 `GET` 返回 `404`；MCP 白名单不含 `regenerate_brief`、`create_export`、`list_signals` | 契约 §8.10、§8.12–§8.14 |
| E8 | PRD S2、D11④ 要求「内容缺口信号」，契约 `CustomerSignalKind` 只有三种售后类信号，`SignalSourceRef` 只能指向售后 | 2026-09-21 补入 `CONTENT_GAP`；来源加 `PRODUCT`（必带 `content_version`）；内容缺口信号恰好一条来源且等于所指商品；售后类信号只接受 `AFTER_SALE` 来源；任何信号不指向顾客对话 | 契约 §8.12.1–§8.12.2；`merchant_ops.py`；`n3-merchant-skills` Task 7 |
| E9 | 访客购物车合并规则与调整可见性 PRD 未写 | 2026-09-21 用户裁定：同商品相加、单行上限 99、剔除不可售、超 50 行保留最新、合并后清空访客购物车；绑定响应加 `cart_adjusted: bool` | PRD C3；契约 §8.8.1；`shop_session.py`；`n2-trade-closed-loop` Task 2；`n2-shop-nextjs-app` |
| E10 | `CursorPage` 未约束 `has_more` 与 `next_cursor` 一致，可能出现 `has_more=true` 却无游标 | 2026-09-21 模块 A 审查补入：`has_more` 必须等于 `next_cursor` 非空；`next_cursor` 非空时 1–2048 字符 | 契约 §8.7；`common.py` |
| E11 | 契约 §8.8.1 写「图片主机白名单经 Pydantic context 注入」，实现改为服务层 `is_trusted_image_host`，契约未同步 | 以实现为准并回写契约：`response_model` 校验不传 context，按原写法外部图片会在响应阶段 500 | 契约 §8.8.1；`shop_session.py` |

**验证方式的补救**：Task 3–8 的 Schema 与测试同一轮写完，没有单独留下「先看到红灯」的记录。补救是变异检验——逐个删掉
`app/schemas/v2` 里 93 处校验拒绝语句再跑测试：首轮 77 个被杀死、16 个存活（一条校验被另一条掩护，没人单独验证），
补 27 项用 `match=` 锁定具体校验的用例（`test_validator_guards.py`）后 93/93 全部杀死。变异脚本不入库。

**顺带修复**：`tests/api/test_demo_merchants.py` 的生产环境用例缺 `BUYER_ALIAS_SECRET`（源于工作树里已有的 `config.py` 改动），
在测试助手补齐配置后转绿；数据迁移计划页眉重复了两遍的「架构」段落已删除一份。

**文档同步**：新增 N1 总览 `plans/2026-09-21-n1-module-roadmap.md`；`docs/project-navigation.md` 登记总览与 A–E 五份计划入口、
`backend/app/schemas/v2/` 目录、计划数量更正为 39 份；`docs/backend-development-plan.md` §8.0.1 补充契约冻结状态说明。

### 2026-09-21 N1 计划审查（执行前，已按 PRD → 契约 → 计划 → 索引同步）

用户只读审查 N1 五份计划，指出六处会导致失败或假绿的问题。均已在任何实现开工前修正：

| 问题 | PRD | 契约计划 | 实施计划 |
| --- | --- | --- | --- |
| N1 安全门禁要求的七类里有三类（越权审批、模型自批、提示词注入）的被测对象 N2 才存在；门禁运行未强制真实数据库，缺库时整批 skip 也显示为绿 | §15 N1 / N2、E3：N1 四类 × ≥3 条、零 skip；其余三类随 N2 路由交付，N2 验收前七类达标；E3 最终范围不变 | — | 评测计划 Task 2 重写（`introduced_in`、路由覆盖守卫、零 skip 钩子）、Task 6；三份 N2 计划登记对应用例 |
| 迁移给既有 `orders` 加非空列却不回填；`refunds` / `returns` / `support_tickets` 扩展无人承接；`after_sales` 表无人建 | §8.1：`order_status` 保留为派生兼容列、历史行固定映射回填并补写回填事件、历史订单不进入 v2 流程；新增售后主记录与售后行 | §8.11：`after_sale_id` 指 `after_sales.id` | 数据计划 Task 2、3 重写（预检、回填、回滚往返测试）；新增 Task 7（M7 售后主记录）；N3 售后计划入口条件 |
| 订单幂等索引 `(merchant_id, client_request_id)` 与契约 §8.7.3 的五元组唯一域冲突 | §8.1 删去 `orders` 上的"幂等键" | §8.7.3：承载表 `idempotency_records`，业务表不设窄索引 | 数据计划新增 Task 8（M8）；交易、草稿计划改用该表 |
| 模型客户端未覆盖 A1 的流式与缓存计量；"非法模型名"在 Anthropic 接口会被自动映射而不报错；多轮工具历史只有单轮 mock | — | — | 模型客户端计划：`converse_stream()`、缓存字段（未上报为 `None`）、`reasoning_content` 回放与协议绑定、多轮请求体测试、`LLM_THINKING` 显式配置；冒烟改为 24 次并换用确定会报错的受控请求 |
| 种子命令路径错误；约束测试把原始 SQL 字符串传给 `execute()` 并用 `pytest.raises(Exception)`，恒绿；`respx` 不在依赖里 | — | — | 数据计划全局约束（`text()`/表达式、`DBAPIError` + SQLSTATE + 约束名、多条失败用 savepoint）；种子命令改为 `../scripts/seed_demo_data.py`；模型客户端改用既有 `httpx.MockTransport` |
| 会话计划与数据计划各自新增迁移，没有规定修订链 | — | — | 两份计划共用"迁移链与测试库规则"：单 head 线性链、`0017`–`0026` 预定顺序、已升级迁移不再修改（会话计划 Task 6 改为独立修订 `0018`）、测试库不共享 |

另外更正：此前汇报的 N1 步骤数 136 有误——统计时把每份计划页眉里的 `` `- [ ]` `` 说明也算了进去；
审查时实际为 131，本轮补全后为 141；2026-09-21 会话签发路由并入 D 后为 146。

1. **模块 D · 会话身份与租户隔离**：顾客/商家两类会话交换、`X-Session-Id`、角色不变量、跨角色与跨商家
   统一 403 非枚举响应及审计证据，以及 5 条会话签发路由（Task 7，同次完成 OpenAPI 导出、商家端生成类型与会话 Adapter）。§8.8 与 §8.9 的契约已解除 §8.0.1 对它的封锁，可以开工；配置面已提前落地，
   开工时当作前置事实核对，不要重复建设。
2. **模块 C · 数据迁移与确定性种子**（29 / 29，C1–C5 已审）：八批迁移、既有行回填、三本事件账、
   幂等表与三商家确定性场景已落地，真实 PostgreSQL 全量和升降级往返已通过；当前无需继续 C 实现。
3. **模块 B · LLM 客户端与双协议适配**（25 / 25，默认协议 `openai`）：C 修复后的全量后端回归已通过；
   可选的追加真实调用须另行取得 R3 授权。
4. **模块 E · 评测骨架与关键安全集硬门禁**（最后做）：Task 2 安全集需要 D Task 1–5、Task 7 与 C 的种子；Task 7 真实模型评测
   需要 B 与 R3 授权。
5. **迁移商家端 Vue 客户端**（N2）：生成 v2 OpenAPI 类型、更新 Adapter、会话、库存、售后、草稿审批与 MCP；
   不把附件兼容字段带入 v2。
6. **N2 开工前建立 Next.js 顾客端计划与工程**，覆盖 PRD C1–C9 和 S1–S4；不得混入 Vue 商家端目录。
7. **保留的旧基线债务**：修复 7 个 TypeScript 类型错误；补双语真实 PostgreSQL 验证、Chat BI
   `alembic check`/CLI 试跑、线上限流/SIGTERM/日志脱敏验收；提交后再跑一次真实数据库全量。
8. **旧 B7 九题真实模型复验**不再是新路线图前置门槛；若仍要执行，必须使用当前模型名
   `deepseek-flash` 并按 R3 重新取得费用授权。

---

## 五、2026-09-20 文档同步结果

**已完成**：新 PRD 的范围、里程碑、状态机、安全约束和路径表已同步到 `AGENTS.md`、前后端开发计划
与本进度快照。R9 的 1:1 基准含义已取消，三处参考目录统一只读；附件端点明确为“从未实现且已延期”；
DeepSeek 的**目标默认模型**统一为 `deepseek-flash`，两种协议适配器的真实冒烟调用纳入 R3 审批；
现有代码、`.env.example` 与 README 仍使用退役兼容别名，列为 N1 配置迁移项，尚未改动。

**尚未实现**（2026-09-20 当日的记录；其中 v2 精确字段契约已于 2026-09-21 完成，见 §一）：应用路由、会话、
数据库迁移、模型默认配置迁移、Next.js 顾客端以及 N1–N5 业务代码。
本轮是文档治理，不得据此宣称产品功能已经完成。

**本轮验证边界**：仅做 Markdown、交叉引用、路径/术语和 diff 静态检查；未跑应用测试、未启动服务、
未调用真实 LLM，未执行任何 Git 发布操作。

### 2026-09-21 追加：N 路线架构边界层

**已完成**：`docs/backend-development-plan.md` 新增 §5.6 与 §6.9–§6.15，定义新内核的模块边界。
关键裁定已写入文档，不再散落在对话里：

- **冻结的 `graph.py` 与新工具循环并存不替换**，两者不共享代码路径，只共享
  `app/llm/`、`safe_query`、`repositories`、`knowledge`、`metrics`；
- 新模块目录与**依赖方向**（`loop → skills → tools → services`，同层禁止互相 import，
  `eval/` 不得被生产模块 import）；
- **LLM 调用预算必须重算**：v1 的 `MAX_LLM_CALLS_PER_REQUEST=10` 不能沿用；按当前质量循环
  每次尝试包含“生成 + 独立 Reviewer”，最坏公式为
  `max_turns + compaction_max_calls + 2 * quality_max_attempts`。若最终作答改成循环后单独生成，
  再显式加 1；
  新增 `AGENT_LOOP_MAX_TURNS` / `AGENT_LOOP_MAX_TOOL_CALLS` / `AGENT_LOOP_WALL_CLOCK_SECONDS`
  三个配置项；改动任一侧都须附重算过程；
- 四类闸门按 A3 定为**来源 / 选项 / 护栏 / 审批**，执行顺序固定，来源状态隔离键为
  登录主体 + 店铺 + 对话 ID；
- 模型可见的工具 `args_model` 中**不得出现** `merchant_id` / `buyer_key`；内部 executor 显式接收
  `SessionContext`，由注册表强制注入。写策略分为只读、顾客直接幂等写、顾客界面确认、商家草稿，
  不把购物车、结账或顾客售后套进商家草稿审批。

同步更新 `docs/project-navigation.md` 新增 §5.3.1，列出六个计划路径并标明**全部尚未创建**。

**尚未实现**：本轮只写文档，未创建任何目录或代码文件。

**本轮验证边界**：章节结构与交叉引用静态检查（§7 之后编号未变动，既有引用不受影响；
修正了 2 处悬空引用与 1 处易失效的行号引用）；未跑测试、未启动服务、未调用 LLM、无 Git 操作。

---

## 六、关键入口

### 规则与导航

- `AGENTS.md`：R1–R9、授权与完成边界、接口路径与鉴权类别、部署硬约束。
- `plans/2026-09-21-n1-module-roadmap.md`：N1 总览（模块 A–E 的框架层、难度、任务级依赖、出口标准）。
- `plans/2026-09-22-astra-checklist.md`：N1–N5 跨模块审查清单（审查点、必须看到的证据、模型分工与审查进度）；
  **标【必审】的项通过审查前不得勾选对应计划复选框**。它是审查清单，不是实施计划。
- `docs/database.md`：N1 C 数据表与迁移说明（模块 C 产出，随 C 验收一并核对）。
- `docs/history/llm-smoke-2026-09-22.md`：模块 B Task 6 双协议真实冒烟的原始记录。
- `docs/project-navigation.md`：文件索引、目录树、测试布局、规划文档目录分工。
- `docs/PRD.md`：产品范围与验收标准。
- `docs/backend-development-plan.md` §8：ChatRequest / ChatResponse / ErrorResponse / SSE 契约。
- `docs/frontend-development-plan.md`：既有 Vue 商家端 F0–F9 实施记录，以及 N1 迁移入口。
- `docs/yshopping-parity-audit.md`：历史差异记录；不定义当前范围，也不是开工前清零清单。

### 后端核心

- `backend/app/agent/graph.py`：12 节点 LangGraph 图；真实查询、回答/审核编排、生成指标口径载荷的落点。
- `backend/app/agent/prefilter.py`：零 LLM 前置闸门。
- `backend/app/services/safe_query.py`：受控查询应用服务；`ExportSpec`/`export_detail` 供导出复用；
  `_generated_metric` 也在这里。
- `backend/app/repositories/analytics.py`：指标聚合与明细数据访问。
- `backend/app/intent/models.py`、`whitelist.py`：`GeneratedMetricPlan`/`CrossBusinessPlan`/`ComparisonMode`
  的结构校验与降级语义。
- `backend/app/services/quality_loop.py`、`quality_types.py`：生成 → 本地校验 → 独立复核 → 回喂重试 →
  确定性兜底；降级原因分 `UPSTREAM`/`VALIDATION`/`BUDGET` 三类。
- `backend/app/llm/guard.py`、`app/core/rate_limit.py`、`app/core/client_ip.py`、
  `app/repositories/llm_budget.py`：费用防护、限流、可信代理 IP。
- `backend/app/localization/`、`app/services/localization_service.py`：双语本地化级联与独立预算。
- `backend/app/analytics/demo_data.py` 的 `DEMO_ANALYTICS_SEED_BASE = 20260804`：演示经营数据随机基线的
  **唯一来源**，第 i 个商家用 `BASE + i`。`scripts/seed_demo_data.py` 的 `--random-seed 20260730`
  只作用于商家表，**别拿错常量**。

### 测试

- `backend/tests/integration/services/test_safe_query_security.py`：跨商家隔离、SQL 注入、180 天上限、
  statement timeout、拒绝原因不泄漏 SQL/表名。
- `backend/tests/unit/intent/test_prompts.py`：提示词契约测试的范式。
- `backend/tests/api/test_admin_ops.py`：`/api/admin/ops/status` 的 401/403/404/200 四态断言。
- `frontend/scripts/e2e-process.mjs`：E2E 子进程管理公共逻辑，不要退回 Playwright 自带的 `webServer`。

### 计划与历史资料

- `plans/2026-09-20-prd-authority-sync.md`：本轮 PRD 权威链同步计划。
- `plans/2026-08-21-gap-roadmap.md`：旧 P1 缺口历史记录；附件条目已被新 PRD 延后。
- `plans/2026-08-22-parity-and-resume-roadmap.md`：旧还原度路线图，不再定义范围。
- `plans/2026-09-16-agents-and-skills-remediation.md`：已完成的指令整改历史计划。
- `docs/specs/2026-08-11-mvp-exit-evidence-matrix.md`：MVP 出口证据矩阵（未回填）。
