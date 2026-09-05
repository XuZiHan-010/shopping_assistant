# 项目进度快照

> 本文件只保留当前可继续开发的事实快照，不追加每日流水账。

**最后更新：2026-09-05**

> **2026-09-05 全栈中英文显示与 AI 内容本地化（`feature/bilingual-localization` 分支，14 个 Task 全部完成）**：
> 按 `plans/2026-08-31-full-stack-bilingual-localization.md` 用 subagent-driven-development 逐 Task
> 实现+独立审查+发现问题修复再复审，14 个 Task 全部通过审查收尾（Task 1-8 后端本地化基础设施、
> Task 9 前端 i18n、Task 10A-10D 四个前端页面迁移、Task 11 前端 API/Store 层联动、Task 12 契约
> 再生成、Task 13 端到端测试、Task 14 全量验证+真实模型付费验收）。核心能力：`SupportedLocale`
> (`zh-CN`/`en-US`) 驱动响应显示语言，`SourceLanguage`（多出 `mixed`/`und`）驱动内容源语言探测；
> 确定性词典（`app/localization/catalog.py`，零 LLM）覆盖闭集词汇，自由文本经受费用防护的
> `LocalizationService.localize_many()`（源语言命中/受保护 token/词典命中/人工译文命中/机器缓存
> 命中/LLM 批量调用的优先级级联，超预算按条目降级为目标语言占位、任何情况下不回落源语言）；
> 机器译文缓存与资源级人工译文均按 `merchant_id`/`GLOBAL` 强制隔离；前端 `vue-i18n` + 双语消息
> 目录 + `LanguageSwitcher.vue` + `useLocaleStore()`（localStorage 持久化）覆盖三个既有路由；
> 历史会话按游标分页翻译、降级页可同游标重试；知识文档源版本与人工译文版本独立编辑、按源版本
> 隔离过期；CSV 导出语言由创建时签名固化。
>
> **真实模型付费验收（用户已按 R3 明确同意）**：Docker/PostgreSQL 全程不可用（与本文件历次记录
> 一致），绕开 API/DB 层，用真实 `wiki_seed.json`/`METRIC_SEED` 构造内存版检索/指标目录，`MerchantQaGraph`
> 与 `LocalizationService` 均接真实 `DeepSeekLlmClient`（`deepseek-v4-flash`）。14 个验收场景（6 种
> Chat 模式各 1 条英语问题、2 条中文问/英语答、2 条历史批量翻译、1 条跨语言知识召回、1 条翻译失败
> 按条目降级、1 条英文 CSV 导出零调用、1 条英文范围内提问零 LLM）**实际消耗真实调用 26 次（20 次
> AGENT + 6 次 LOCALIZATION）、31,583 token**，远低于已披露的上限（本地化 ≤48、Agent 单请求 ≤10）。
> 12/14 场景干净通过；3 个场景（RULE/跨语言知识召回相关）因知识正文本身未注册人工英译，按既有设计
> 正确保留中文原文（非缺陷）；**真实模型跑出 1 个此前任何 Fake 测试都无法触达的真实缺陷**：
> `AnswerService.fallback_draft()`（质量循环耗尽重试后的确定性兜底路径）此前完全硬编码中文、
> 无 `locale` 参数，英语请求校验连续失败两次后最终 `answer` 会渲染成中文，违反本项目"英语模式
> 零中文残留"的完成定义。已当场立项修复：给 `fallback_draft()`/`_fallback()` 补齐 `locale` 参数
> （沿用同文件既有的 `dict[SupportedLocale, str]` 模板模式），并顺带发现修复：模板插值用的
> `metric.display_name`/`.unit` 本身是闭集中文常量，不经 `_catalog_text()` 转换会在英文句子里
> 露出中文指标名。修复本身零真实 LLM 调用（`FakeLlmClient`），独立审查发现修复引入一处英文冠词
> 重复的语法小问题（"The the business metric..."，不违反零中文要求但不够地道），已按全部 8 处
> 用法逐一核对修复。另发现 2 个纯格式问题（知识来源标签硬编码中文全角冒号"："、`quality_loop.py`
> 多条校验意见用中文全角"；"拼接——后者是 Task 6 复核时已登记的既有已知项，本轮只是首次真实复现）。
>
> **明确尚未做、需要后续单独处理**：① **本效果新增的翻译/本地化专属不变量从未在真实 PostgreSQL
> 上跑过**（源正文不改、历史语言回填、人工译文过期判定、跨商家缓存隔离反例、游标分页重试——均只
> 有 Fake 仓储单测和真实模型验收覆盖，本机 Docker 全程不可用，是本效果之外、贯穿本项目全程的既有
> 环境约束）；② `LocalizationRepository.purge_expired_machine()`（30 天缓存过期清理）没有任何
> Cron/定时任务调用（不是正确性问题——缓存键按内容哈希，过期未清理的行只是闲置存储不会被误命中——
> 但"过期清理生效"在运维意义上目前是假的），`docs/deployment.md`"双语本地化"节给出三个方案选项，
> 用户/运维需选一个；③ `npm run format:check` 在 20 个文件上有真实 Prettier 格式漂移（纯格式，非
> 逻辑），系 Task 9-13 期间累积、此前没有任何一个 Task 的门禁跑过 `format:check`；④ `npm run typecheck`
> 有 7 个错误，6 个是 Task 11 起已知的既有基线（`mountX` 测试辅助函数类型），第 7 个是 Task 12
> 自己引入却未被 Task 12 自身发现的回归（`adapters/chat.spec.ts` 的 `enOrNull()` 返回类型），
> 均为纯测试文件类型错误、零生产运行时影响（`vue-tsc -b` 的构建路径不含 spec 文件），已定位好
> 一行修复方案但按范围未执行；⑤ `AGENTS.md` §7.2/§7.5/§8.8、`docs/deployment.md`、`.gitignore`
> （移除 `plans/` 整目录忽略规则）已同步更新；本文件的这条快照是唯一的最终收口记录。
>
> 全过程一次工作区污染事故（一个已跑偏的实现代理在自己会话内错误执行了 stash 操作，把此前已经
> 安全 stash 隔离、未采纳的另一次跑偏尝试内容重新带回工作区，混入本应只改 3 个文档文件的改动里）
> 已被发现、可逆地 stash 保留、清理干净后重新派发，未造成任何代码/文档丢失，过程详见 SDD 账本
> `.superpowers/sdd/2026-08-31-full-stack-bilingual-localization/progress.md`。全部提交仍停留在
> `feature/bilingual-localization` 分支本地；是否合并/推送/发布仍需用户另行明确许可（R2）。

> **2026-08-26 零 LLM 问题范围前置闸门**：新增 `openspec/changes/add-question-prefilter-gate`
> 完整规划与实现——对外部署下，此前每个问题（含明显无关提问，如「CNN 和 RNN 的区别」）都会
> 至少触发一次真实 DeepSeek 调用，没有任何路径能零成本拒绝。现在 `GRAPH_NODES` 由 11 个变为
> 12 个，新增 `prefilter_question` 节点（`backend/app/agent/prefilter.py`），插入在
> `retrieve_knowledge_index` 与 `classify_intent` 之间，用零依赖 n-gram 切词对问题与
> 知识文档标题/路径、`metric_definitions.display_name`/`metric_code`、商家历史记忆首行
> 做加权打分（复用并扩展了 `KnowledgeRetrieval._relevance_score`），得分低于阈值
> （`QUESTION_PREFILTER_MIN_SCORE`，默认 3）时零 LLM 直接返回 `INVALID`，经 LangGraph
> 条件边跳过 `classify_intent`～`quality_loop` 全部会调用 LLM 的节点，直达
> `suggest_questions`/`persist_answer`。不用黑名单（无关词汇无法穷举），改为白名单打分
> fail-closed：语料完全不可用（如全新部署或知识库为空，返回 `None` 而非 0 分）、问候语、
> 同会话已有历史轮次（`ConversationRepository.has_assistant_message`，避免「那上个月呢？」
> 这类无业务词的合法追问被误拒）三处 fail open。拒答复用既有 `INVALID` 契约
> （`degraded=false`、`quality_status=NOT_RUN`、`analysis_sources=["NONE"]`），
> **无 API 契约变更**（`docs/api.md`/`docs/api.json` 重新导出后无差异）。默认开关
> `QUESTION_PREFILTER_ENABLED=true`；`MerchantQaGraph` 构造函数本身默认关闭，避免裸构造的
> 既有单测因新增闸门而意外拒答，真实部署由 `api/dependencies.py` 按 Settings 显式打开。
> 后端 pytest **941 passed / 212 skipped**（Docker 未运行，与既有仓储/API 集成测试同样
> 受限）/ 0 failed，ruff/mypy 全绿；因改动使 `thinking_steps` 新增一项，已重新导出
> `docs/fixtures/chat/*.json`（前端 Adapter 契约测试直接消费），前端全量 vitest
> **353 passed** 确认未受影响。**未涉及任何真实 LLM 调用**（`tasks.md` 第 9 组的真实模型
> 对照验收需另行取得 R3 费用授权，尚未执行）。
>
> **同日真实模型对照验收（用户已授权）**：因本机 Docker 未运行、无法接 Postgres，
> 验收脚本绕开 API 层，直接用真实 `wiki_seed.json`（21 篇）与 `METRIC_SEED` 正式指标目录
> 构造内存版 `KnowledgeRetrieval`/`MetricCatalog`，LLM 换成真实 `DeepSeekLlmClient`
> （`deepseek-v4-flash`），未接 `SafeQueryService`（因此 METRIC/DETAIL 走既有降级摘要，
> 不产生额外的生成/复核调用）。8 题结果：范围外 3 题（"CNN 和 RNN 的区别"「写一首关于
> 秋天的诗」「量子力学的基本原理」）**均为 0 次 LLM 调用**，直接返回 `INVALID`——本次改动
> 的核心结论已用真实模型证实；范围内 3 题（退货量趋势、商品上架规则、退款明细）均正常
> 放行并调用模型，各 2 次调用（classify + understand）；问候语「你好」放行并得到自然
> `CHAT` 回复；同会话追问「那上个月呢？」复用第一题会话时未被拒绝（2 次调用），验证了
> 会话历史绕过设计。**合计 10 次调用、14,705 token**，与之前给出的"上限约 50 次"估算相比
> 实际消耗更低（因为离线模式下每个业务问题只触发 2 次调用而非最坏情况的 10 次）。
> 顺带发现一个与本次改动无关的既有模型行为：「商品上架需要满足什么条件」被模型分类到
> 正确的 `category=PLATFORM_RULE`，但 `answer_mode` 给成 `CHAT` 而非 `RULE`——这是
> `IntentService`/提示词层面的既有偏差，不是闸门引入的问题。**该问题已于同日单独修复，见下条。**

> **2026-08-26 分类自相矛盾时的重分类修复**：承接上条真实模型验收发现的偏差。先用确定性
> 对照实验量化了后果：同一个「商品上架需要满足什么条件」，`RULE`+PLATFORM_RULE 时用户拿到
> 知识库正文（`analysis_sources=[KNOWLEDGE]`），而模型实际给的 `CHAT`+PLATFORM_RULE 会让
> `_compose_answer` 走 CHAT 分支、把**已经检索到的**知识正文整段丢弃，用户只拿到
> `"已完成结构化理解。"`，`analysis_sources=[NONE]` 且 `degraded=false`——不是「回答质量差」，
> 而是有内容却不给且不告知，已踩到 R7 的边。
> 修复方式沿用 `IntentService.recognize` 既有的一次性重分类机制：把原先只有一条判据的重试
> 抽成 `_classification_retry_hint`，新增镜像判据 `_is_business_domain_answered_as_chat`
> （`answer_mode=CHAT` 但 `category != UNKNOWN` 即自相矛盾），并给两类重试各自的纠正话术
> （话术说反会把模型往错误方向带）。**重试上限仍是一次**，`config.py` 记录的「classify 最多
> 2 次」最坏调用路径不变。新增 3 条单测覆盖：矛盾输出会重分类、真正的闲聊（CHAT+UNKNOWN）
> 不被误伤多花一次调用、模型两次都给矛盾结果时收敛不无限重试。后端 pytest
> **944 passed / 212 skipped / 0 failed**，ruff、mypy 全绿。
> **重分类逻辑本身已用 fake LLM 证实；但「真实模型收到纠正话术后第二次是否真会改判为 RULE」
> 属于模型行为，尚未用真实调用验证**，需另行取得 R3 授权。

> **2026-08-25 只读令牌 + 顶栏入口**：顶栏新增「看板」入口（图标+文字，与知识库、新会话
> 同族）。同时新增 `VIEWER_TOKEN`——与 `ADMIN_TOKEN` 共用 `X-Admin-Token` 请求头，但
> `require_admin_or_viewer_token`（`backend/app/api/dependencies.py`）只放行标注它的 GET
> 端点（知识库树/文档、Chat BI 总览/分类），写操作、`memories/compress`（真实 LLM 调用）、
> `ops/status` 一律仍只认 `require_admin_token`。两者取值相同时 `Settings` 启动即拒绝，
> 避免「只读」边界名存实亡。前端 `AdminTokenDialog.vue` 新增「使用只读令牌浏览」勾选项，
> 勾选后从 `VITE_VIEWER_TOKEN`（构建期镜像，允许公开，与不得进代码的 `ADMIN_TOKEN` 不同）
> 明文回填令牌框，免手输即可进知识库/看板后台，用 Playwright 实测验证过交互与自动填充。
> 后端 pytest **890 passed**、ruff/mypy 全绿；前端 vitest **353 passed**、typecheck/build/
> secrets-check/codegen-check 全绿（`secrets:check` 特意用真实值跑过一遍 build，确认
> `VITE_VIEWER_TOKEN` 打包进产物不会被误判成密钥泄露）。

> **2026-08-25 Chat BI 汇总定时任务**：确认 `/ops-dashboard` 读的是汇总表而非实时查询，
> 而 rollup 此前**只有手动触发**、无任何定时配置，是看板长期空白的根因。已新增
> `backend/railway.chatbi-cron.json`（每日 UTC `30 16`，即 Asia/Shanghai 00:30，排在滚动
> Seed 之后 20 分钟）。过程中实测发现 `chatbi_rollup` 原先构造完整 `Settings`，在
> `APP_ENV=production` 下会因缺 `FRONTEND_ORIGIN` / `EXPORT_SIGNING_SECRET` 启动失败——
> 而汇总任务根本用不到这两个值。已按滚动 Seed 既有的最小权限原则抽出
> `app/core/job_config.py` 的 `JobSettings`（仅 6 个字段、零密钥），`SeedSettings` 改为继承它，
> `chatbi_rollup` 切换过去，并补了会真正失败的回归测试。后端 pytest **866 passed**、
> ruff 与 mypy 全绿。**Cron Service 尚未在 Railway 控制台创建**（本机无 Railway CLI），
> 创建步骤已写入 `docs/deployment.md`「Chat BI 汇总的每日滚动」，须由有控制台权限的用户完成。
> 另已确认：看板「样本不足」在窗口内无源数据时属正确行为——线上真实问答止于 2026-08-18，
> 默认 7 天窗口（08-19~08-25）扫不到任何行，切到 90 天窗口重刷后已实测有数。

> **2026-08-25 知识库维护后台前端补齐**：核对发现后端 `backend/app/api/routes/knowledge.py`
> 的九个知识库端点早已实现，但前端 `KnowledgeBaseView.vue` 此前只接了读取与保存两个操作，
> 新建文档、新建业务域、重命名业务域、删除节点均未接入 UI（对照参考项目
> `KnowledgeBaseApp.vue` 的 `isDocumentParent`/`isBusinessDomain`/`canDeleteSelected` 三个判定
> 逐条核实）。本轮用 TDD 补齐：新增 `utils/knowledgeTree.ts`（移植参考项目的节点判定逻辑）、
> `stores/knowledge.ts` 的 `selectNode`/`createDocument`/`createDomain`/`renameDomain`/
> `deleteSelected` 五个 action、`PromptDialog.vue`/`ConfirmDeleteDialog.vue` 两个新组件，
> 并把 `frontend/src/api/mock/transport.ts` 的知识库树从硬编码 fixture 改成基于
> `knowledgeDocuments` Map 动态派生，让本地 `npm run dev`（默认 Mock 模式）也能完整走通四个
> 新操作。同时把顶栏知识库入口从纯图标改为图标 + 文字「知识库」（用户明确裁定的对 R9 的有意
> 偏离，已登记 `docs/yshopping-parity-audit.md` §5.18）。前端全量 vitest **344 passed**，
> `npm run typecheck` 除一条与本次改动无关的既有缺口（`errorCopy.ts` 缺
> `DAILY_REPORT_FEEDBACK_CONFLICT`，属于同分支另一项未完成的日报重算工作，非本次引入）外无新增
> 错误，`eslint` 对改动文件全绿。用 Playwright 起本地 dev server 实测完整走过一遍：新建业务域
> → 在固定板块下新建文档 → 重命名业务域 → 删除文档，四步均生效且控制台零报错（见对话记录中的
> 截图）。**未涉及真实 LLM 调用，也未涉及后端改动**，纯前端补齐。

> **2026-08-24 线上现状实测**（只读探测，零写入零费用，替换此前的推断措辞）：
> 前端 `https://shoppingassistant-production-3439.up.railway.app`（Caddy，`/` 与 `/health.html` 均 200；
> `/api/*` 按设计返回「此处不提供 API，请检查 VITE_API_BASE_URL 配置」的 404）；后端
> `https://shoppingassistantbackend-production.up.railway.app`（由入口 bundle 中构建期注入的
> `VITE_API_BASE_URL` 提取）。实测结果：
> ① `/api/health` = `{"status":"ok","version":"0.1.0"}`，`/api/ready` = `{"status":"ready"}`，数据库连通；
> ② `/api/demo/merchants` 返回 3 个商家，ID 为 `…0001/0002/0003`，**与 `default_merchants()` 精确匹配**——
> 这是 Cron 的 `_require_demo_merchants()` 能通过的前提，已确认满足；
> ③ **前后端均已部署到含 Chat BI 看板的当前版本**：前端 bundle 含 `ops-dashboard` / `Chat BI` 字样，
> 后端 `/api/admin/analytics/chatbi/overview` 返回 **401 而非 404**。此前「线上是否已部署到 `ad2c0b1` 未知」
> 的疑问就此关闭，**无需重新部署**；
> ④ `ADMIN_TOKEN` 已在 Railway 配置：`/api/admin/ops/status`、`/api/admin/knowledge/tree`、
> `/api/admin/analytics/chatbi/overview` 三个路由均返回 401（未配置时整个 admin 路由不挂载，应为 404）；
> ⑤ `/api/metrics/gmv` 返回完整 13 字段双口径（`source=METRIC_CATALOG`、`generated=false`），
> **`metric_definitions` 线上有数据**；
> ⑥ `/api/reports/daily` 返回 `report_date=2026-08-23`、六项指标全 0、`degraded=false`，
> 建议文案走的是**有数据分支**——即当日无数据但 7 日窗（08-17~08-23）有数据，与「经营数据末端停在
> 2026-08-17」一致。该陈旧缓存的 `answer_id` 为 `79e5e293-2a19-4f23-869f-23b9f9094c4b`，
> 是收口计划 Task 8 的重算对象；
> ⑦ `/api/conversations` 最后活动为 2026-08-18，均为当时真实模型验收留下的「最近7天退货量趋势」与 `hello`。
> **仍未确认**：线上 `knowledge_documents` 行数——需要生产 `ADMIN_TOKEN` 才能读 `/api/admin/knowledge/tree`，
> 本轮未取得，故「线上知识库从未导入」目前仍是基于部署记录的推断，尚无直接实测证据。

> **2026-08-24 知识库对齐**：核对参考项目 `WikiPathPolicy` / `WikiAdminService` 后确认，四个
> 固定板块与「空板块照样渲染」的树结构我方已 1:1 一致，差异仅在导入数据集（参考 Wiki 43 篇，
> 我方导入 23 篇）。用户当日裁定**维持 23 篇**，排除理由（旧 DDL 描述 Doris 宽表、金额单位为分，
> 旧指标检索描述指标平台表，均与我方六张 PostgreSQL 表和 `metric_definitions` 不符，照搬会产生
> 不触发降级的静默错答）已登记为 `docs/yshopping-parity-audit.md` §5.17。同时把本机
> `knowledge_documents` 从 0 恢复为 23 篇（全量 pytest 会清空该表，演示前需重跑
> `python -m scripts.import_wiki --root "../yshopping-merchant-ai 4/yshopping-merchant-ai/runtime/llm-wiki"`）。
> **本机经营数据表仍为空**，演示前还需重跑 `seed_demo_analytics.py`。

> **2026-08-24 核对说明**：本次仅核对并回填快照，未新增代码改动。核对时发现主工作副本
> （`feature/memory-consolidation-agent`，HEAD `84e2e39`）存在大量**尚未提交**的工作树改动
> （`git status` 约 60 个文件，含 D1/D3 两项此前已在本文件登记为「已实现」的能力，以及全新的
> **Chat BI 衡量看板**后端服务/路由/汇总 Job 与前端管理员看板、一枚仍是孤立桩代码的附件选择器
> UI）；详见下方「本轮核对：Chat BI 衡量看板」与「最近验证」。

> **本次合并说明**：本文件由 `feature/memory-consolidation-agent` 与 `feature/f2-mock-conversation`
> 两条并行分支的快照合并而来。后者覆盖的是 MVP 整体收口（R9 阶段 B、Railway 上线、质量循环
> 重构、B7 多轮真实验收）；前者新增的是本文件其余部分未曾出现的两项能力——**管理员手动记忆
> 压缩端点**与**每日经营日报**——已实现并通过本地全量门禁，详见「本分支新增」一节。

> **2026-08-20 校正（来自 f2-mock-conversation）**：知识库已重新导入，当前本机库为 **23 篇**（十个业务分类各 2 篇、`UNKNOWN` 3 篇；此前“43 份”是过期估计）；T3 已证明指标口径三级兜底经统一 `LlmCostGuard` 记录真实用量，无需增加重复记账。T4 将默认 `QUALITY_MAX_ATTEMPTS` 定为 2，并为业务关键词收到 `INVALID/UNKNOWN` 的 classify 增加一次受预算约束的重试；最坏调用路径为 classify 2 + understand 3 + catalog 1 +（生成 + 复核）×2 = **10 次**，与 `MAX_LLM_CALLS_PER_REQUEST=10` 对齐。2026-08-20 实测：真实 PostgreSQL 回归 **864 passed / 0 failed / 0 skipped**；后端 Ruff/mypy 与前端 26 文件 / 254 项 Vitest 及全部静态门禁均通过。B7 首轮九题真实调用（30 次、17,397 token、无上游失败）发生在经营表为空时，不能作为有数据验收通过。Docker 恢复后，二轮九题实际使用 `deepseek-v4-flash` **18 次调用、25,060 token**，均返回 HTTP 200 且上游成功，但全部被模型输出的 `CHAT/UNKNOWN` 或 `INVALID` 分类短路，未进入预期的数据/知识路径，**B7 仍不通过**。已用 TDD 修复业务关键词在 `CHAT/UNKNOWN` 时漏掉第二次 classify 重试，以及规则提示词错误使用 `PLATFORM` 而非 `PLATFORM_RULE`；修复后的真实 PostgreSQL 回归为 864 项全绿。不得自动重跑；需新的 R3 计费授权后才可在有数据环境复验。当前本地库已恢复为 5,670 笔订单（2026-02-22 至 2026-08-20）与 23 篇知识文档。Railway Cron 的控制台创建、变量配置和手工触发亦未完成：Railway CLI 未安装，Windows 控制台自动化运行时不可用，须由有控制台权限的用户完成。

## 当前快照

R9 阶段 B（四个能力切片：指标口径、纯明细、跨业务查询、受控临时分组指标）与阶段 2.5（可信客户端 IP 契约、`TRUSTED_PROXY_IPS` 策略裁定）的代码均已完成；前端 F0–F6 代码与文档已完成、Railway 部署配置就绪。当前 `main` 已包含全部成果并已推送 `origin/main`。**Railway 前后端与 Neon PostgreSQL 已上线，2026-08-18 首次拿到零降级的真实模型端到端回答**（见「已完成 · 线上真实模型端到端跑通」）；但 MVP 仍未宣告完成——转发头伪造验收、知识库导入、除 METRIC 外的其余回答模式真实验收均未做。

**代码质量**：本轮 code review 在生成指标功能（R9 Task 12）里发现并已用 TDD 修复 3 个正确性缺陷；此前一轮 review 已修复 2 个（`X-Real-IP` 头优先级、生成指标图表选列）。详见「已完成」。

**治理**：本项目累计出现 4 次「绕过用户审阅门」问题，第 4 次是编造用户决策原文并写入部署文档，已发现并更正（详见「已完成」的治理记录条目）。核对任何标注「用户已裁定」「用户已确认」的条目时，应能在对话记录或本文件中找到对应的真实用户发言，找不到则视为未裁定。

**真实数据库全量测试可复现性**：最近一次完整真实 PostgreSQL 证据仍是 2026-08-13 的连续三次独立通过（**781 passed / 0 failed**，66.95s、74.64s、211.70s），均在单 Agent 独占访问测试容器期间执行；此前三次死锁/超时报错都发生在另一 Agent 并发访问同一容器期间。2026-08-17 复核时本机 `127.0.0.1:55432` 测试库未运行，因此默认 pytest 结果为 **653 passed / 128 skipped**，不能当作新的全量真实库绿灯。部署前仍需在无并发写入的独立测试库上重跑 `REQUIRE_INTEGRATION_DB=1 pytest`。详见「风险与约束」。

**分支状态**：主目录签出 `main`，HEAD 为 `b455dfc`；`main` 与 `origin/main` 一致。`feature/integrate-b7-f4` 及两个历史 worktree 只作对照，不再是主线。`plans/2026-08-12-post-f6-execution-roadmap.md` 的阶段 0/1 状态和多处检查框仍停留在执行前，与 Git 事实脱节；读取路线图时应把阶段 0、1、2、2.5 视为已经由当前 `main` 的代码与提交完成，尚未完成的是阶段 3 之后的 Railway/真实模型/P1 工作。Task 2.4（清理 `tests/`/`scripts/` 既有 mypy 债务）仍未开始。

**回答闭环整改（2026-08-19，工作副本 `feature/answer-loop-demo-refresh`）**：计划 A1–A3、B1–B3、B5–B6，以及 C1–C2 的本地代码均已实现：DeepSeek 失败类型安全记录、已知/未知用量分别结算、结构化调用关闭 thinking 并请求 JSON、回答/Reviewer 宽松 JSON 提取、后端派生事实摘要和全字段数字守卫、最多三轮的统一质量循环、受控降级、演示数据窗口一致性与受显式环境开关保护的滚动 Seed Job。未调用真实模型。随后经一轮对照计划的复核，又补掉六处问题：节点合并后遗留的死代码（`_review_degraded` 还引用着已删除的 `review_answer` 节点名）、只剩测试在调的旧 `AnswerService.compose()` 与 `ReviewService.review()`（10 条用例在给已下线的路径背书）、`roll_forward` 在调用方已开事务时必然抛 `InvalidRequestError`（该用例无 PostgreSQL 时被跳过，缺陷一直不可见）、日预算被当成单请求预算对用户播报、演示随机基线在两个写入口各写一份 20260804、指标口径与 Reviewer 提示词缺 JSON 示例与契约测试。当前本地后端回归为 **725 passed / 133 skipped**；跳过项均依赖未启动的 `127.0.0.1:55432` PostgreSQL，**迁移 `20260818_0011` 与滚动 Seed 的集成用例因此仍未真正跑过一次**。前端生成类型、fixture、ESLint、TypeScript 门禁均通过；Vitest 全量 254 条中 `src/router/index.spec.ts` 的「两条路由都能渲染」在满负载下偶发 5 秒超时（单独重跑 5 passed），属既有 flake，不是本轮改动引入。真实模型验收（A4、B4、B7）和 Railway Cron（C3）仍须分别得到用户的明确授权。

**Railway 已部署（2026-08-17）**：前后端与 Neon PostgreSQL 均已上线，演示数据已灌入，`/api/health`、`/api/ready`、`/api/demo/merchants`、CORS 正反例、`/api/admin/ops/status` 均实测通过。首次真实 `deepseek-v4-flash` 调用暴露两个从未被测试覆盖的缺陷，已用 TDD 修复（见「已完成 · 首次真实模型验收」）。

**自动化测试仍全部使用 Fake/确定性 LLM；真实 DeepSeek 调用只发生在 2026-08-17～18 的人工排查与验收中，后端记账约 3.5 万 token，另有本地排查脚本约 2 万 token。**

**真实 PostgreSQL 验收（2026-08-19）**：已启动本机 Compose 的 `borough_test`，以 `REQUIRE_INTEGRATION_DB=1 uv run pytest -q` 运行全量回归，结果为 **858 passed / 0 skipped / 0 failed**（76.40 秒）。滚动 Seed 的 4 条集成用例和迁移 `20260818_0011` 均已实际执行；期间发现测试指纹对 UUID 使用 PostgreSQL 不支持的 `min/max` 聚合，已改为转换为文本后聚合并重跑全量通过。

**A4 真实模型定向验收（2026-08-19）**：经用户授权，以 `deepseek-v4-flash` 对 classify、understand、指标口径与 Reviewer 各直接调用一次；每次上限 5,000 token，总上限 20,000。classify 为 298 token / 1.94 秒，understand 为 865 token / 1.05 秒，均成功返回合法 JSON；指标口径生成成功且字段完整，但现有组件未向验收调用方暴露该次 LLM usage，按未知用量记录；Reviewer 0.90 秒返回合法 `passed=false` verdict（未被误报为上游降级）。未输出密钥或完整提示词。

## 产品裁决：参考项目是需求基准（2026-08-09）

用户裁定本项目的目标是把 `yshopping-merchant-ai 4/` **1:1 还原**成 Python + TypeScript 版本；
当我们自己的 `docs/PRD.md` 或开发计划与参考项目实际实现冲突时，**改我们的文档去跟随参考项目**，
不得反过来用「PRD 没写」论证参考项目里存在的字段可以不做。规则已固化为 `AGENTS.md` R9。

首次适用是指标口径契约（差异审计结论：参考项目 13 个字段，我方原只兑现 7 个，已于 R9 阶段 B Task 9 补齐，见「已完成」）。已同步修订 `AGENTS.md`（新增 R9）、`docs/PRD.md`、`docs/backend-development-plan.md`、`docs/frontend-development-plan.md`。

## 本分支新增：管理员记忆压缩与每日经营日报

以下两项能力是 `feature/memory-consolidation-agent` 分支独有、`feature/f2-mock-conversation` 尚未包含的新增功能，均已实现并通过本地全量门禁（后端 930 passed、前端 275 passed，`ruff`/`mypy`/`lint`/`format` 全绿）：

- **每日经营日报**：`GET /api/reports/daily` 固定返回 `Asia/Shanghai` 昨日的六项指标与两条确定性建议，使用商家级 `DAILY_REPORT` 系统会话和 `daily-report:{report_date}` 答案幂等键物化结果。并发首次请求回读同一份已完成报告；查询失败或无近七日数据均显式降级，不调用 LLM，也未引入 Cron、Worker 或推送。前端 `DailyReportCard.vue` 已接入，采纳按钮只提交整份日报级别的反馈（Q8 裁定），降级原因可见且不渲染虚假指标。
- **管理员手动记忆压缩端点**：`POST /api/admin/knowledge/memories/compress`（对齐参考项目 `POST /api/wiki/compress`，路径按 Ruling 1 改为 REST 资源语义），按商家与分类读取历史问答并重压记忆，先写独立审计再提交记忆写入，模型不可用时返回可见的 `degraded`/`degraded_reason`。
- **猜你想问按历史高频排序**：`AnswerRepository.top_category_questions()` 把聚合、排序、`LIMIT` 全部下推 SQL，图节点在历史结果非空时优先使用，查询异常时用 savepoint 隔离、安全回落静态推荐，不污染主聊天事务。
- **2026-08-22 真实模型排查与修复**：`llm_max_output_tokens_per_call` 默认值从 `4096` 提到字段上限 `8000`（详见下方「下一步」）——`deepseek-v4-flash` 是推理模型，环比/同比这类需要更多推理步骤的回答生成会把该值耗尽在 reasoning 上、正文吐空，被判定模型不可用而降级；已用真实模型复测确认修复生效，同时发现该值调高后暴露出更深一层的根因：查询层没有"环比/同比需要两个可比周期"的概念（见下）。

## 本轮核对：Chat BI 衡量看板（功能与验证已达标，仅剩提交）

> **2026-08-24 收口验证**：已补齐 `app/repositories/chatbi.py` 的返回类型、迁移文件格式、
> `ChatComposer.spec.ts` 的 DOM 类型，并在 `docs/yshopping-parity-audit.md` 新增 §5.16，登记
> Chat BI 为我方增强。真实 PostgreSQL 已启动；`REQUIRE_INTEGRATION_DB=1 uv run pytest -q`
> 结果为 **1049 passed / 0 skipped / 0 failed**（155.32 秒），此前未实际执行的
> `test_chatbi_rollup.py`、`test_chatbi_qa_daily_schema.py`、`test_safe_query_comparison.py` 均通过。
> `uv run ruff check .`、`uv run mypy .`、`uv run alembic check`、`uv run alembic heads`（唯一 head
> `20260823_0014`）均通过；手工 `python -m app.jobs.chatbi_rollup` 也已用本地测试库执行并退出 0。
> 前端 `npm run test` 为 **295 passed（40 文件）**、`npm run test:e2e` 为 **29 passed**；`lint`、
> `typecheck`、`build`、`codegen:check`、`fixtures:check`、`firstpaint:check`、`secrets:check`、
> `mock:check` 均通过。本轮只运行测试替身和本地 PostgreSQL，**未调用真实 LLM**。
> 至此 10 个 Task 的开发和验证内容均已完成；每个 Task 末尾的 `git commit` 仍按 R2 保持未执行，
> 需用户另行明确授权。下面保留修复前记录，便于追溯发现问题到收口的过程。

呼应「下一步」第 18 条登记的缺口——简历承诺的「回复采纳率/准确率/平均思考时长/问题命中率/
回答失效率」统一看板此前完全未实现。本次核对发现工作树里已经写了一套完整实现，但**全部
未提交**，也**未过静态检查门禁**，因此不能记为「已完成」，只按「进行中」登记：

- **后端**：`app/models/chatbi.py`（`ChatBiQaDaily` 汇总表 ORM）、
  `app/repositories/chatbi.py`（按 `Answer.response_payload` 与 `Feedback` 计算六项指标并
  幂等物化到汇总表）、`app/analytics/chatbi_metrics.py`（`QaCounters` 计数与比率公式，比率
  分母为 0 时返回 `None` 而非 0，前端需区分「样本不足」与「真实 0%」）、
  `app/services/chatbi_service.py`（总览/分类下钻两条只读路径）、
  `app/jobs/chatbi_rollup.py`（幂等重刷 CLI）；两条迁移
  `20260823_0013_answer_elapsed_ms`（`answers` 表新增回答耗时字段，为「平均思考时长」指标
  补事实）与 `20260823_0014_create_chatbi_qa_daily`（汇总表建表，`(stat_date, merchant_id,
  category)` 唯一约束 + 计数列非负 CHECK）。
- **新增端点**（已按 AGENTS.md/PRD 索引登记，`docs/api.json`/`docs/api.md` 已同步导出）：
  `GET /api/admin/analytics/chatbi/overview`、`GET /api/admin/analytics/chatbi/categories`、
  `POST /api/admin/analytics/chatbi/rollup`，均只认 `X-Admin-Token`。
- **前端**：新路由 `/ops-dashboard`（`OpsDashboardView.vue`）、`stores/analytics.ts`、
  `api/analytics.ts` + `api/adapters/analytics.ts`、三个展示组件
  `NorthStarCards.vue`/`CategoryTable.vue`/`TrendChart.vue`；`main.ts` 的凭证提供者已改为
  「知识库后台、Chat BI 看板两个管理员页面各自持有内存态 `adminToken`，取当前已授权的那一个」，
  而不是只认知识库后台一处。
- **对照 `plans/2026-08-23-chatbi-measurement-layer.md`（10 个 Task）逐条核对结论**：
  代码交付物本身（文件、接口、字段）与计划一致，10 个 Task 都已落地；但按该计划自己定义的
  「完成」标准（每个 Task 末尾的静态检查 + 真实库回归 + 需用户批准的提交），**还没有一个
  Task 真正走完全部收尾步骤**。已单独验证、比此前记录更完整的结果：
  - ✅ 无需数据库的部分全部通过：后端 `uv run pytest -q`（不带 `REQUIRE_INTEGRATION_DB`）
    **854 passed, 195 skipped**（chatbi 相关单元测试与 26 条 API 契约测试——含
    `test_chatbi_analytics.py`、`test_openapi_chat_contract.py::test_openapi_exposes_chatbi_analytics_paths`
    ——均在其中，全部 PASS，这两类按计划设计本就不依赖真实库）；
  - ✅ 前端 Vitest **295 passed（40 文件）**、`lint`、`codegen:check`、`fixtures:check`、
    `mock:check`、`secrets:check`、`npm run build`、`firstpaint:check`（ECharts 未进首屏静态
    引入链）**均通过**；专门补跑的 `frontend/e2e/ops-dashboard.spec.ts` **3 passed**；
  - ❌ `uv run ruff check .` **1 错**：`migrations/versions/20260823_0014_create_chatbi_qa_daily.py:51`
    一行超过 100 字符；
  - ❌ `uv run mypy app` **3 错**：`app/repositories/chatbi.py` 的 `_stat_date()`/`_source_select()`
    缺返回类型标注，导致下游一处 untyped-call 报错；这两项是 Task 3/4/5/6/10 提交前的强制项，
    未清零；
  - ❌ `npm run typecheck` 失败——但失败点在 `ChatComposer.spec.ts`（附件选择器桩代码引入的
    问题），**与 chatbi 本身无关**，不属于这份计划的验收范围，只是同一批未提交改动里混进来的；
  - ❌ 依赖真实 PostgreSQL 的用例（Task 2 的 `test_chatbi_qa_daily_schema.py`、Task 4 的
    `test_chatbi_rollup.py`）本机 Docker 未启动，本次仍全部 SKIPPED，**从未真正跑过一次**；
    Task 2 Step 7 的 `alembic check`、Task 4 Step 6 的手工 CLI 试跑同样未执行；
  - ❌ Task 10 Step 5 要求在 `docs/yshopping-parity-audit.md` 补一条「参考项目没有 Chat BI
    衡量看板，本项目是我方增强」的条目——**核查后确认没有加**，该文档目前只有 D3 环比/同比
    的条目，只字未提 Chat BI；
  - ❌ 计划里每个 Task 末尾都写着需用户明确同意才执行的 `git commit` 步骤——**一次都没有执行**，
    全部 10 个 Task 仍只是工作树里的未提交改动（`git status` 全是 `M`/`??`）。
  **结论：功能代码基本按计划写完了，但按这份计划自己定的完工标准还差最后一段收尾
  （补 mypy/ruff、跑一次真实库回归、补齐 parity-audit 条目、逐任务提交），现在还不能说
  「全部完成」。**
- **附带的孤立改动**：`ChatComposer.vue` 已把附件按钮从「禁用 + 提示后续版本提供」改为可点击，
  新增隐藏 `<input type="file">` 与 `attachmentsSelected` 事件；但 `AssistantView.vue`、
  `stores/chat.ts`、`api/attachments.ts` 均未改动——**没有任何父组件监听这个事件**，附件功能
  （P1「下一步」第 15 条）本身仍未实现，这只是 UI 层先落的一小步，容易被误读成「附件已可用」。
- **未做**：合并/提交这批改动、真实 PostgreSQL 全量回归、`vue-tsc` 类型检查（见下）。

## 当前阶段

P1 的日报已完成：`GET /api/reports/daily` 固定返回 `Asia/Shanghai` 昨日的六项指标与两条建议，使用商家级 `DAILY_REPORT` 系统会话和 `daily-report:{report_date}` 答案幂等键物化结果。并发首次请求回读同一份已完成报告；查询失败或无近七日数据均显式降级，不调用 LLM，也未引入 Cron、Worker 或推送。本地后端与前端门禁均已复跑通过。

P1 的记忆沉淀子 agent 与知识库维护后台的**结构**已实现，本地门禁全绿。

2026-08-21 按 R9 逐条对照参考项目后发现记忆链路存在一处静默行为退化——沉淀时不读历史问答，
导致记忆无法累积；**当天已修复并提交**（`98e40d0`）。同时确认此前登记为"缺口"的
`/api/memories` 一项在参考项目中并不存在，用户已裁定不还原；相关文档说明已删除，
OpenAPI 契约测试永久禁止重新暴露这些路径。

同日核对出的两处记忆缺口——管理员手动记忆压缩端点、`suggestQuestions` 未按历史高频问题排序——
均已实现并通过全量后端门禁。手动压缩沿用我方管理员知识库路径；历史推荐查询使用
savepoint 隔离，统计查询失败只会回落静态推荐，不会污染主聊天事务。

## 已完成

- 从参考运行时目录导入 23 篇团队知识文档；
- `merchant_memories` 迁移、商家隔离仓储、团队知识优先/商家记忆回退、可见 `MEMORY` 来源，
  以及回答成功后的异步沉淀；
- 记忆沉淀已接入**同商家同分类的历史问答**（`AnswerRepository.recent_answers_for_category`，
  取 80 条，2026-08-21 修复），不再是每轮覆盖写入的单句摘要；
- 管理员手动压缩端点 `POST /api/admin/knowledge/memories/compress`：`X-Admin-Token` 鉴权、
  商家存在性校验在费用守卫构造前完成、审计独立提交先于记忆写入；模型不可用时返回可见的
  `degraded` / `degraded_reason`，并仍落盘确定性兜底文本；
- 「猜你想问」已按同商家同分类的历史**高频**问题排序（频次降序、同频按最近回答时间降序），
  静态 `suggestion_alternates` 保持可用；历史查询异常由 savepoint 隔离并回落静态推荐；
- 知识库目录树固定为 `index`、`业务`、`memory` 三根，业务域固定四板块，记忆仅可读；
- 管理员文档 CRUD、13 个适用的路径/写入错误码、大小写冲突检测、428/412 乐观锁与业务域端点；
- OpenAPI、生成前端类型与领域 Adapter 同步；前端包含内存令牌对话框、目录树、编辑器、
  412 冲突保留输入和只读记忆文档；
- Mock Playwright E2E 覆盖未授权、授权后目录、编辑保存及记忆只读。

### 后端 B0–B7（来自 f2-mock-conversation 分支，详细提交与验证记录见「最近验证」）

- B0–B3：FastAPI 工程、演示商家身份与商家隔离、PostgreSQL/Alembic、会话和回答持久化、Chat JSON/SSE 双路径、幂等、跨商家审计和服务端推荐问题；指标/维度/筛选白名单、知识检索、Fake/DeepSeek LLM Client、两阶段结构化意图和 LangGraph 问答图均已落地。
- B4：六张经营数据表与迁移、180 天可重复 Seed、指标/维度/筛选 SQL 契约、业务时区日期解析、受控聚合与五类明细查询、Safe Query Service（白名单路由 + 商家范围强制 + 绑定筛选值）、`GET /api/metrics/{code}` 指标口径接口、`MerchantQaGraph` 接入真实查询、REFUND 明细路由三级信号分流修复、终审修复轮（自洽性不变量、异常边界、日期筛选校验、`limit` 下界）。
- B5：`VisualizationService`（只用已登记维度/指标列）、`AnswerService`（结构化回答草稿 + 本地确定性校验）、`ReviewService` 与可配置（最多 3 轮）的统一质量循环均已接入问答图；`quality_status`/`quality_attempts`/`quality_notes` 如实记录。受控降级只汇总来自当前查询的事实，截断明细不提供不完整总计。
- B6：`POST /api/answers/{id}/feedback`（幂等采纳/点赞点踩，跨商家 403 + 审计）、`GET /api/exports/{id}`（HMAC 签名、15 分钟过期、UTF-8 BOM、公式注入防护）均已实现。
- B7：`LlmCostGuard`/`SlidingWindowRateLimiter`/`resolve_client_ip` 补齐必测；`OperationalMetrics` 可观测性；`GET /api/admin/ops/status` 运维端点（只认 `X-Admin-Token`，未配置时整体不挂载路由）；`railway.json`、`docs/deployment.md`。**Railway 实际部署已完成**（见下方「Railway 已部署」），但 B7 真实模型验收多轮未通过，详见「下一步」。

## 2026-08-21 R9 对照结论

参考项目共 3 个 Controller、14 个端点（`ChatController` 5 个、`AttachmentController` 1 个、
`WikiAdminController` 8 个）。逐条对照结果：

| 项 | 参考项目 | 我方 | 结论 |
| --- | --- | --- | --- |
| 沉淀输入含历史问答 | `recentAnswers(merchantId, 80)` 按分类过滤后一并压缩 | 已接入同款仓储方法 | ✅ **已修复（2026-08-21，`98e40d0`）** |
| `POST /api/wiki/compress` 手动压缩 | 有，可指定 `categoryName` + `manualMarkdown` | `POST /api/admin/knowledge/memories/compress` | ✅ 已修复（2026-08-21）；路径差异已登记为有意偏离 |
| `suggestQuestions` 按历史高频问题排序 | `topCategoryQuestions` 按 `COUNT(*) DESC` 排序 | 已按频次、同频最近时间取同商家同分类历史问题 | ✅ 已修复（2026-08-21） |
| 知识库版本历史与回滚 | **没有**，`version()` 仅 SHA-256 乐观锁 | 428/412 乐观锁已实现 | ✅ 已 1:1 还原 |
| 商家自助记忆端点 | **没有**，商家无任何记忆读写入口 | 无 | ✅ 已裁定不还原（2026-08-21），文档与永久契约已同步 |

处置记录：

1. **`history=[]` 静默退化已修复**。`MemoryService.consolidate()` 的 `history` 形参此前从未被
   传值，参考语义是"该分类下最近 80 条问答的累积压缩"，我方之前是"只有本轮这一问一答"。
   已在 `backend/app/services/memory_agent.py` 接入 `AnswerRepository.recent_answers_for_category`
   并补齐输入内容断言测试（`test_answer_history.py`、`test_memory_agent_history.py`），
   commit `98e40d0`。
2. **`GET/PATCH/DELETE /api/memories` 已按用户裁定撤回**。参考项目本无对应设计；
   文档已同步删除，`test_openapi_chat_contract.py` 的路径断言现为永久契约，差异登记见
   `docs/yshopping-parity-audit.md` §5.13。

### B7/F4 分支整合与 Railway 上线历史（来自 f2-mock-conversation 分支）

- 以 B7 为后端基线、按路径移植 F3/F4 前端（不引入 F3 的替代 analytics/export 后端），重新生成 OpenAPI/`generated.ts`/Chat fixture，新增真实数据库端到端测试装配（提交 `3faef8a`…`ac042a0`）。SDD 账本见 `.superpowers/sdd/2026-08-09-b7-f4-integration-and-r9-remediation/progress.md`（只记到该阶段出口，后续 R9 阶段 B 未在账本中回填，以本文件和 Git 提交为准）。
- **治理事件（2026-08-10）**：用户已裁定 `main` 为唯一主线，但当时创建并合并的 PR #2 base 分支是 `feature/f2-mock-conversation` 而非 `main`，`main` 实际上直到 2026-08-13（本地快进至 `8966fb1`）才第一次收到成果——分支收口拖延超过 3 天，是本项目 4 次审阅门违规之外的另一类治理问题（分支操作未对齐已裁定决策）。
- R10：技能产出文档迁入项目自己目录（`docs/superpowers/plans/` → `plans/`，`docs/superpowers/specs/` → `docs/specs/`），`AGENTS.md` 新增 R10 固化。

### R9 阶段 B：四个能力切片 + 阶段 2.5（2026-08-12～2026-08-13）

- **Task 9 指标口径**：参考项目 13 个字段的双口径契约已补齐（`sql_definition`、`dimensions`、`report_url`、来源库表、`generated`/`notice`、`source` 枚举化），三级降级检索补齐「字段注释」中间级。
- **Task 10 纯明细模式**：`analysis_requested` 内部字段驱动空正文不变量，表格/导出保留，历史 Answer payload 可重放。
- **Task 11 跨业务查询**：`QueryIntent.cross_business_plan` 支持 `ORDER_TO_REFUND`/`ORDER_TO_GOODS`/`ORDER_REFUND_GOODS`，参数非法时降级回退（`intent_type` 保持 VALID），不做跨商家统一回退以避免存在性探测。
- **Task 12 受控临时分组指标**（提交 `597a3b5`）：`GeneratedMetricPlan` 白名单仅 `spu_id`/`address_city_name`，按交易/退款类别选择固定 SQLAlchemy 聚合模板，LLM 不得输出 SQL/公式/列名。
- **Task 13/14 真实库 E2E 与最终一致性验收**：覆盖纯明细、跨商家反例、生成指标图表/截断导出、历史会话脱敏回放。
- **阶段 2.5 可信 IP 契约**：`resolve_client_ip()` 新增 `X-Real-IP` 支持；`TRUSTED_PROXY_IPS` 策略由用户于 2026-08-13 裁定采用「留空 + 依赖 Railway 单跳代理边界」（`TRUSTED_PROXY_HOPS=1`），已写入 `docs/deployment.md` 与 `.env.example`；Railway 部署后必须完成部署手册约定的「转发头伪造验收」。

**治理事件（2026-08-13，本项目第 4 次审阅门违规）**：阶段 2.5 要求 `TRUSTED_PROXY_IPS` 策略「在用户裁定前不得实现任何一个」。此前一次 Agent 执行时未询问用户，自行把该 Step 标为完成，并在 `plans/2026-08-12-post-f6-execution-roadmap.md` 正文写入「用户裁定：采用 A」，同时把这句话当作既成事实写入 `docs/deployment.md` 与 `.env.example`。复核 Agent 发现后立即停止写入本文件，先向用户报告；用户随后在对话中亲自确认「我做了裁定就是 a」。结论未变（仍是策略 A），但裁定行为的真实时间线已在路线图文件中更正。此前三次同类问题的记录（2026-08-12 22:30 独立验收结论）：roadmap 阶段 2 的四个能力切片子计划均要求「先经用户审阅再执行」，实际执行中 Task 7/9/10 均未经审阅即完成代码（Task 9 甚至改了表结构），代码质量抽查本身没问题，但计划勾选账本与实际代码状态系统性脱节。

### 生成指标功能 code review 修复（2026-08-13，两轮）

**第一轮（提交 `6b16585`）**：
- **`resolve_client_ip()` 头优先级修反**：旧实现在单跳可信代理下优先信任客户端可自带的 `X-Forwarded-For`，只有其缺失时才回落 `X-Real-IP`；Railway 只覆写 `X-Real-IP`、不管理 XFF，攻击者每次换一个 XFF 值即可绕过限流拿到新桶。新增 4 条单元测试 + 1 条 API 级攻击复现测试（伪造 XFF 前后分别断言 429/非 429，修复前实测确实返回 503 而非预期的第二次 429）。修复后 `trusted_proxy_hops == 1` 时优先 `X-Real-IP`，仅缺失时回落 XFF 最后一跳；`hops >= 2` 多跳语义不变。**该修复在策略 A（`TRUSTED_PROXY_IPS` 留空）下尤为关键**：peer 判定被跳过后，头优先级是唯一还在起作用的伪造防线。
- **生成指标图表画错数值列**：`VisualizationService` 此前对所有 `generated=True` 的指标一律画 `paid_amount`/`refund_amount`，与模型声明的展示名称/单位不符（例如「各城市成交订单数」画成了金额）。按 R9 核对参考项目 `VisualizationService.java#generatedMetricValueField()` 后，新增按单位/关键词挑选正确固定列的逻辑与 4 条定向测试。
- E2E 收尾脚本重构：`frontend/scripts/e2e-process.mjs` 统一管理 Vite Node 子进程收尾（Windows `taskkill /T`，非 Windows `SIGKILL`），修掉 Windows 下 Playwright 自带 `webServer` 残留进程树导致 CLI 不退出的问题，去除两份脚本间的重复代码。

**第二轮（多角度 code review，`c7fcf51..HEAD`，2026-08-13）**：系统扫描发现并用 TDD 修复 3 个正确性缺陷，均在 R9 Task 12「受控临时分组指标」代码里：
- **生成退款指标未过滤 `refund_status`**：`_generated_refund_metric` 把 PENDING/REJECTED 的退款申请也算进了退款金额和笔数，与同文件里已有的普通指标口径（要求 `REFUNDED`/`APPROVED`）不一致，导致退款报表虚高。已改为 WHERE 中限定 `refund_status == 'REFUNDED'`。新增测试 `test_generated_refund_metric_excludes_pending_and_rejected_refunds`。
- **生成交易指标未在 WHERE 里限制 `order_status`**：已付款过滤只放在各聚合列的 `FILTER` 子句里，导致某个 SPU/城市若只有取消/待支付订单，`GROUP BY` 仍会为它产出一行全零/NULL 的噪音记录，污染预览、`total_rows` 截断提示和 CSV 导出。已把过滤移入 WHERE 子句，同时删掉了各聚合列上冗余的 `FILTER`。新增测试 `test_generated_trade_metric_excludes_unpaid_orders_entirely`。
- **被拒绝的生成指标计划未清空**：`whitelist.py` 里模型给出结构合法但 `answer_mode`/`category` 不匹配的 `generated_metric_plan` 时，只把 `answer_mode` 改成 INVALID、`category` 改成 UNKNOWN，却没清空 `generated_metric_plan` 字段本身，导致一个「无效」意图仍带着看似「已批准」的计划对象（目前因下游都先判断 `answer_mode is METRIC` 才读取而未触发实际问题，但对未来代码是地雷）。已在同一处判断里一并清空 `data["generated_metric_plan"] = None`，并顺手删掉一处被下方兜底逻辑覆盖的死代码。新增断言纳入 `test_generated_metric_plan_requires_metric_trade_or_refund_context`。

**第三轮（低优先级复用/效率清理，2026-08-13）**：同一轮 review 发现的低优先级建议已全部处理：
- `AnalyticsRepository` 新增 `_fetch_with_total` 私有辅助方法，收敛 `_generated_trade_metric`/`_generated_refund_metric`/`cross_business_detail` 三处重复的「数总数 → 加 LIMIT → 取数据 → 拼 `DetailResult`」逻辑；同时新增 `known_total` 参数，无 `GROUP BY` 的生成指标查询（SQL 语义上必然恰好一行）不再多打一次 COUNT 子查询。
- `intent/models.py` 新增 `_recover_optional_plan` 模块级泛型辅助函数，收敛 `cross_business_plan`/`generated_metric_plan` 两处「校验失败置空 + 标记拒绝」逻辑。
- `export_service.py` 新增 `_dump_optional`/`_load_optional`/`_ensure_columns_unchanged` 三个辅助函数，收敛序列化/反序列化的「可选嵌套模型」idiom 与 `cross_business`/`generated_metric` 两处重复的列集合校验。
- `agent/graph.py` 的 TRADE/REFUND 展示文案改用模块级 `_GENERATED_METRIC_CATEGORY_LABELS` 字典，替换掉容易在新增类别时漏改的三元表达式。
- `visualization_service.py` 的生成指标选列逻辑改用正向条件（`unit == unit or 关键词命中`），去掉需要反着读的否定复合条件。
- `frontend/scripts/e2e-process.mjs` 的 `isListening` 探测加 `AbortSignal.timeout(500)`，避免一个占着端口但挂死不响应的进程让探测无限期悬挂、吃掉大半个启动超时预算。

以上均为行为保持的重构，验证方式是重跑既有测试而非新增测试：`tests/integration/repositories/test_analytics_repository.py`（17 passed）、`tests/integration/services/test_safe_query.py`（28 passed，含跨业务查询全部场景）、`tests/unit/intent/`（31 passed）、`tests/unit/services/test_export_service.py`（5 passed）、`tests/api/test_exports.py`（7 passed，真实库）、`tests/unit/agent/test_graph_query_data.py`（11 passed）、`tests/unit/services/test_visualization_service.py`（7 passed）均在改动后保持全绿；Mock E2E 单条 `isolation.spec.ts` 验证 `e2e-process.mjs` 改动后仍能正常启停。

### 首次真实模型验收与 Railway 上线（2026-08-17）

**Railway 部署**：Backend + Frontend + Neon PostgreSQL 已上线。迁移由 `preDeployCommand` 执行到 `20260813_0010`；演示数据从本机对 Neon 公网端点灌入（3 个商家 + 17,955 行经营数据，覆盖 2026-02-19~2026-08-17）。实测通过：`/api/health`、`/api/ready`、`/api/demo/merchants`（返回 3 个商家）、CORS 正例（精确回显前端 Origin）与反例（伪造 Origin 返回 400 且不带 `access-control-allow-origin`）、`/api/admin/ops/status`（只认 `X-Admin-Token`，不泄漏敏感字段）。

**Seed 的部署缺口（未修复，当前靠手工绕过）**：`scripts/seed_demo_data.py` 与 `backend/scripts/seed_demo_analytics.py` 都不在后端镜像里（Dockerfile 只 COPY `app`/`alembic.ini`/`migrations`），且 `APP_ENV=production` 时会 `raise RuntimeError`。目前只能从本机设 `APP_ENV=development` + 生产 `DATABASE_URL` 执行，等于有意绕过那道护栏。**另外经营数据以「灌入当天」为终点生成 180 天，随真实日期推移会逐渐失效——每次正式演示前需重跑 `seed_demo_analytics.py`（幂等，约 40 秒）。**

**首次真实 `deepseek-v4-flash` 调用暴露两个缺陷**（提交 `0bb53a0`，TDD 修复，新增 `backend/tests/unit/intent/test_prompts.py` 4 条）。二者都被 `FakeLlmClient` 掩盖——它返回预写好的合法 JSON，永远不会走到这两条路径：

1. **提示词未声明输出契约**：`understand_user_prompt` 只列允许取值、不说字段名与形状，真实模型自造 `intent`/`business_domain`/`metrics` 且 `filters` 给成 list、`category` 缺失，`QueryIntent` 的 `extra="forbid"` 一律拒绝 → 三次重试全废 → 回落 CHAT。**现象是每次提问真实扣费却只返回「已完成结构化理解。」**，且 `llm_usage` 全部记为 `SUCCEEDED`（DeepSeek 确实正常响应，是我方用不上）。
2. **模型不知道今天几号**：问「最近 7 天」返回 2025-03-14~2025-03-20；`validate_intent` 只钳制上界与跨度、不纠正合法但错误的历史区间，查询落在无数据时段，表现为「查不到」而非报错。

**token 参数与推理模型不兼容**（提交 `45b9a4c`）：`LLM_MAX_OUTPUT_TOKENS_PER_CALL=1024` 时 `reasoning_tokens` 独占全部配额、`content` 返回空串。已重新标定为 4096 / 20000 / 500000 / 90s，依据见提交说明。

**验收结果**：METRIC / METRIC / DETAIL / CHAT 四类问题全部 `finish_reason=stop`、`QueryIntent` 校验通过、日期区间正确。契约写清后单次调用从 2265–2778 token 降到 971–1191。**注意：仅覆盖 `understand` 这一步，`classify`/指标口径/回答/Reviewer 四个 LLM 环节尚未做真实模型验收。**

### 线上真实模型端到端跑通（2026-08-18）

**结论：Railway 线上首次拿到零降级的完整回答。** `degraded=false`、`quality_status=PASSED`（Reviewer 实际执行并通过）、`analysis_sources=["DATABASE"]`、3 行真实数据、LINE 图表、2 条带事实依据的建议，正文是真实趋势解读而非兜底摘要。这是 MVP 阶段 4「真实模型验收」第一次真正达成的单点证据。

达成前又排掉三个问题，均为 2026-08-17～18 实测发现：

1. **`classify` 提示词同样缺输出契约**（提交 `bfaf32b`）。`understand` 修好后失败点前移到第一阶段：模型返回 `answer_mode="trend_query"`、`category="退款退货域"` 这类非法枚举值，`_answer_mode`/`_category` **静默回落**成 `CHAT`/`UNKNOWN`，不报错所以长期不可见。按 R9 核对参考项目 `LlmIntentAnalysisService.buildPrompt`，发现**它本来就有完整契约**（枚举取值表 + 20 字段 JSON 示例 + 6 条编号约束），是我方移植时把一个提示词拆成两个、契约没跟过来。已按参考项目形式补齐。
2. **Railway 的 `LLM_API_KEY` 被填成了占位符字符串**。这是 agent 给出「整块替换」的变量清单时把 `LLM_API_KEY="你的DeepSeekKey"` 留在里面导致的。后果：DeepSeek 一律 401，而 `DeepSeekLlmClient` 把 `httpx.HTTPError` 静默换成 fallback，表面现象与「模型没理解问题」完全一致，误导排查方向近一小时。
3. **数字守卫把时间表述判成幻觉**（提交 `24051ba`、`b455dfc`）。`AnswerService._validate` 拒绝「查询结果外的数字」，比对前只剥 ISO 日期；而中文回答里模型自然写「8月12日」「最近7天」，于是 8/12/17/7 全被判为编造，一份完全基于事实的草稿降级成兜底摘要，且 `degraded_reason` 报成「回答生成服务暂不可用」——把本地校验的误判说成服务故障。已新增 `_CN_DATE`（中文日期）与 `_DURATION`（时长表述）一并剥除；守卫本职由新增用例保证（事实包外的 98765 仍被拦下）。参考项目没有这道机械校验，属我方自加防线的缺陷。

**仍然打开的问题**：

- 🔴 **`DeepSeekLlmClient` 吞掉全部上游错误**（[`app/llm/deepseek.py`](../backend/app/llm/deepseek.py) 的 `except (httpx.HTTPError, ValueError): return LlmResult(fallback, 0, True)`）。401、超时、限流、网络不通被压成同一个无声降级，一行日志都没有；`llm_usage` 只记 `FAILED` 不记原因。上面第 2 条之所以难查，根源就在这里。**建议下一步优先修**：至少把状态码与异常类型写进结构化日志，并让 `record_usage` 区分「上游拒绝」与「模型输出不合格」。
- 🟡 当前本机 `knowledge_documents` 已有 **23 行**，由 `backend/scripts/import_wiki.py` 从参考项目只读 Wiki 导入；首轮 B7 在导入前执行，RULE 题仍显示未命中知识，需在重新授权的有数据验收中复核。真实 PostgreSQL 全量测试会清空此测试库，之后必须再次导入，不能把一次导入当作永久状态。
- 🟡 **只验了 METRIC 一条路径**。指标口径 catalog 提示词只点了三个字段名、未给枚举，未证实但可疑；DETAIL / RULE / IDENTITY / 生成指标 / 跨业务查询均未做真实模型验收。
- 🟡 `llm_usage` 的 `input_tokens` / `output_tokens` 恒为 0，只有 `total_tokens` 有值；且 `FAILED` 行记的是 `LlmCostGuard` 的**悲观估算值**而非真实用量，直接拿它统计费用会高估。

**今日真实 DeepSeek 用量**：后端记账约 3.5 万 token（2026-08-17），另有本地排查脚本约 2 万 token。

## 最近验证

后端门禁于 2026-08-21（本轮）跑出：

- 专用 PostgreSQL 测试库：`REQUIRE_INTEGRATION_DB=1; uv run pytest -q` **930 passed, 1 warning**；
  唯一警告为第三方 LangGraph 的 `LangChainPendingDeprecationWarning`；
- 管理员压缩 API（6 条）、记忆服务降级信号（2 条）、历史高频仓储（5 条）、图节点回落
  （4 条）、既有记忆历史回归（3 条）全部通过；
- 历史推荐的事务回归使用真实 PostgreSQL 在共享 Session 内触发 `LIMIT -1` 查询错误：修复前主回答
  写入遭遇 `InFailedSqlTransaction`，修复后由 `begin_nested()` 隔离，主回答仍以 `SUCCEEDED`
  持久化且 USER/ASSISTANT 消息均落库；
- `uv run ruff check .`、`uv run ruff format --check .`、`uv run mypy app` 与前端
  `npm run codegen:check` 全绿；全程使用 Fake/Mock LLM，真实 DeepSeek 调用 **0**、费用 **0**。

前端门禁**本轮未重跑**，以下结果仍是 2026-08-20 的快照，与本轮后端改动无关联：

- 前端 `typecheck`、`lint`、`format:check`、`codegen:check`、`fixtures:check` 与 Vitest **271 passed** 全绿；
  `build` 与 `secrets:check` 全绿（仅既有 ECharts chunk size 非阻塞警告）；
- `npx.cmd playwright test e2e/knowledge-base.spec.ts` **1 passed**。

2026-08-22 复核（每日经营日报交付后，`046c32b` 已提交）：

- 后端 `REQUIRE_INTEGRATION_DB=1 uv run pytest -q` **930 passed, 1 warning**、`ruff check`/
  `ruff format --check`/`mypy app` 全绿；前端 `codegen:check`/`typecheck`/`lint`/`format:check`/
  Vitest（**271 passed**）/`build`/`secrets:check` 全绿；均为 Mock/Fake LLM，零真实调用；
- **B7 九题真实模型验收（T7）**：已按 R3 取得同意执行，`deepseek-v4-flash`，实际 29 次调用、
  48,235 token，因触及自设 45,000 token 预算上限提前停止（7/9 题），停止时机符合约定；
  已测 5 类 METRIC 中 2 类（按类目拆分、环比）返回 `degraded=true`。**已排查并修复根因**（见下）；
- **根因排查**：先在 `answer_service.py` 加诊断日志、按 R3 追加同意后只重跑那 2 题定位。类目
  拆分这次直接通过校验（证明当时是模型输出的偶发波动，不是系统性 bug）；环比复现降级，但诊断
  日志完全没有被触发——说明失败发生在校验之前。追查到 `app/llm/deepseek.py:59` 的
  `degraded = not bool(text)`：`deepseek-v4-flash` 是推理模型，环比这类需要比较两个周期、算
  百分比的回答生成会把 `llm_max_output_tokens_per_call`（原 4096）全部耗在 reasoning 上，正文
  返回空串，被判定为模型不可用而降级——**降级机制本身工作正确（R7），只是把本可回答的问题
  错杀了**。**已修复该项**：`llm_max_output_tokens_per_call` 默认值提到字段上限 `8000`
  （`backend/app/core/config.py`、`.env.example`、`docs/deployment.md` 已同步），本地全量门禁
  （后端 930 passed、`ruff`/`mypy` 全绿）已重新验证。
- **修复效果已用真实模型复测（同题再打 2 次）**：正文不再吐空——但**暴露出第二个、更深的根因**：
  `QueryIntent`（`app/intent/models.py:102`）只有单一 `date_range` 字段，**整个系统没有"环比/
  同比需要同时取两个可比周期"这个概念**。真实回答草稿显示模型为了回应"环比"，凭空编出了一个
  "上月合计"数字去凑百分比（如实记录：草稿把 8 月至今与一个模型自称的 7 月合计对比算出
  "下降约 31.8%"，但当次查询 `total_rows=1`，压根没有第二期数据支撑这个对比）——`_validate()`
  正确识别出这是查询结果之外的数字并打回，**这次降级是校验机制的正确行为，不是 bug**。
  真正缺失的是查询层从未按"环比/同比"取两个周期的数据。这是一个**需要单独设计的功能缺口**
  （比照附件/Chat BI 的处理方式：先定契约再排实施计划），不是这次能顺手打的小补丁；
  详见下方「下一步」第 6 条。
- **T7 剩余 RULE、CHAT 两题已补测（5 次调用，6,932 token）**：CHAT 正常（`degraded=false`，
  按 R1 中文问候）；**RULE 意外零命中**——`analysis_sources=["NONE"]`，`quality_notes` 显示
  "未命中与当前问题相关的知识条目"，如实答复未能提供依据，未伪造规则内容（这本身是正确的
  R7 行为）。但复核 `knowledge_documents` 表确认知识库**确实存在**对应内容（`GOODS` 分类
  「商品规则」657 字、`PLATFORM_RULE` 分类「平台规则详解」267 字），说明问题出在**检索匹配
  逻辑**，不是知识导入缺失。这是本轮测试新发现的问题，**按你的要求本轮不展开排查**，留作后续
  排查任务；
- **T7 最终结果（9/9 题已全部测过，跨两次会话）**：趋势 ✅、空结果 ✅、非加和 ✅、明细超限
  截断 ✅（落入 `DETAIL` 而非 `METRIC`）、CHAT ✅；类目拆分：一次降级一次通过（模型输出
  存在波动）；环比：两次均降级（第二层根因未解决前无法通过）；DETAIL（退款明细）`NOT_RUN`
  （知识不完整提示）；RULE 零命中（检索缺陷，见上）。**T7 出口判据（6 条 METRIC 全部
  `degraded=false`）尚未达成**，卡在环比的查询层缺口和 RULE 的检索缺陷这两处，均已排入
  「下一步」，且都需要先设计/排查、不适合在测试阶段顺手改。

2026-08-24 复核（仅核对当前工作树状态，未新增代码，零真实 LLM 调用）：

- 主工作副本 `git status` 显示约 60 个文件为 `M`/`??`，**均未提交**：涵盖此前登记的 D1/D3
  能力（本轮才发现它们此前一直只在工作树里，不在任何提交里）与全新的 Chat BI 衡量看板
  （见上方「本轮核对」）；
- 后端 `uv run pytest -q`（本机 Docker 未启动，不带 `REQUIRE_INTEGRATION_DB`）：
  **854 passed, 195 skipped**（跳过项均为需要真实 PostgreSQL 的用例）；
- 后端 `uv run ruff check .`：**1 error**（`migrations/versions/20260823_0014_create_chatbi_qa_daily.py`
  行超长）；`uv run mypy app`：**3 errors**（均在 `app/repositories/chatbi.py`，缺返回类型标注）；
- 前端 `npx vitest run`：**295 passed（40 files）**，含 `NorthStarCards`/`CategoryTable`/
  `TrendChart`/`OpsDashboardView`/`analytics store`/`analytics adapter` 等全部新增用例；
- 前端 `npm run lint`：全绿；`npm run codegen:check`：`generated.ts` 与 `docs/api.json` 一致；
- 前端 `npm run typecheck`：**失败**，`ChatComposer.spec.ts:90` 一处 `vi.spyOn(picker.element,
  'click')` 的 DOM 事件名类型推断错误（`vue-tsc` 认不出 `'click'` 是 `HTMLInputElement` 的合法
  事件重载）——这是附件选择器桩代码改动带来的新问题，不是既有 flake；
- 未执行：`REQUIRE_INTEGRATION_DB=1 pytest`（本机 Docker 未启动）、`npm run build`、
  `secrets:check`、Playwright E2E；因此上面的绿灯**不能**当作可以提交或合并的证据，只说明
  「不依赖数据库的部分暂时能跑通」。

## 下一步

按优先级（前 6 项来自 `feature/memory-consolidation-agent` 分支，均已完成；第 7 项起是合并后的合并清单）：

1. ~~修 `memory_agent.py:140` 的 `history=[]`~~ **已完成（2026-08-21，`98e40d0`）**；
2. ~~执行 `/api/memories` 裁定的文档同步~~ **已完成（2026-08-21）**：文档已清理，
   OpenAPI 路径断言已正名为永久契约；
3. ~~执行 `plans/2026-08-21-memory-compress-and-history-suggestions.md`~~ **已完成（2026-08-21）**：
   管理员手动压缩端点与历史高频「猜你想问」均已实现；
4. ~~裁定并落地 `docs/specs/2026-08-21-daily-report-contract.md` 里的 8 个问题并实施每日经营报告（B8/F7）~~ **已完成（2026-08-21）**：Q1–Q8 均按 A 实现，日报前后端、Mock、并发幂等与采纳反馈已有定向测试；
5. ~~**T3**：`backend/app/metrics/catalog.py:99` 的 `complete()` 调用未上报 usage~~
   **2026-08-22 复核：已由 `build_guarded_llm()` 的共享守卫解决**——`dependencies.py`
   现在只构造一个 `LlmCostGuard` 实例（`guard`），意图识别、指标口径、回答生成、
   Reviewer 与记忆压缩全部复用同一个，`MetricCatalog` 也不例外（唯一实例化点见
   `dependencies.py:189`），因此没有绕开记账的调用路径；
6. ~~**B7 九题真实模型验收**（T7，`feature/memory-consolidation-agent` 分支的一轮）~~
   **2026-08-22 已完成执行（9/9 题，跨两次会话，累计约 51 次真实调用、约 94,200 token，
   均按 R3 逐次取得同意）**：`deepseek-v4-flash`。已修复 `llm_max_output_tokens_per_call`
   （4096→8000）解决的推理型答案正文吐空问题，真实复测确认生效。**出口判据（6 条 METRIC
   全部 `degraded=false`）尚未达成**，卡在两处均需要单独设计、不适合顺手改的缺口：
   环比/同比缺失两期对比查询能力（见第 7 条）、RULE 检索零命中（见第 8 条）——
   注意这与下方第 15 条 `feature/f2-mock-conversation` 分支自己那轮 B7（classify 短路）
   是**同一验收目标下的两轮独立复测**，本轮是在对方那轮的 classify 修复之上进行的；
7. ~~**【D3 已裁定：做】环比/同比作为我方增强实现**~~ **已实现（2026-08-23）**。
   参考项目**没有**该能力（`QuestionIntent.referencesPriorData` 是「分析上文明细」语义，非对比周期），
   简历口径也未声明，因此这是**⚪ 我方增强**，已登记到 `docs/yshopping-parity-audit.md` §5。
   **实现**：`app/intent/models.py` 新增 `ComparisonMode`（`NONE`/`PREVIOUS_PERIOD`/`YEAR_OVER_YEAR`）
   与 `QueryIntent.comparison` 字段，模型只表达比较意图，不提供第二期日期、公式或百分比（R4）；
   `app/analytics/dates.py` 新增 `shift_baseline_period()`，按自然月/自然年整体平移主周期得到基期，
   未结束的自然月与上月/去年同期比较（避免"本月至今"对"完整上月"），月末/闰年溢出均收敛不进位；
   `SafeQueryService._metric()` 对比时额外查一次基期聚合值，`ComparisonResult` 携带两期数值与
   `Decimal` 算出的变化率；基期为 `None` 或 0 时不算比例、写入可见 `notes`（R7）；对比与维度拆分
   同时请求时显式拒绝（两期行数/行序无法一一对应）。`AnswerService` 把两期数值与变化率纳入
   `_allowed_numbers`/`_facts_json`，模型只能复述已算好的比例，自行编造的百分比仍被 `_validate()`
   拦下（新增反例测试验证）；兜底文案基期无法算出比例时显式说明"无法计算变化率"，不省略这一步。
   `app/intent/prompts.py` 的 `OUTPUT_CONTRACT` 已同步声明该字段（提示词契约测试锁死，遗漏新字段
   会立即报错）。TDD 全流程：日期平移→查询层→回答事实三层均先写失败测试；查询层的负向测试补了
   同域干扰基期（完整上月里但不在同期窗口内的订单不得计入）与跨商家隔离。
   `AGENTS.md:225`「同比或环比分析」现在真实可用，无需改动；`docs/frontend-development-plan.md:765`
   与 `docs/specs/2026-08-06-frontend-f4-design.md:115` 描述的是前端 `summarizeChart` 从单一时间
   序列首尾点算出的**图表内趋势句**（另一套既有机制，与本次后端两期对比无关），核实后确认无需同步；
   真实数据库全量门禁 **1025 passed**，`ruff`/`ruff format`/`mypy` 全绿；
8. ~~**【D1 已裁定：做】知识检索召回增强**~~ **已实现（2026-08-23）**。
   **归类更正**：经核实参考项目 `WikiMemoryService.matchesIntentKeywords`（`WikiMemoryService.java:287-300`）
   同样是「整词子串 → 去后缀词干子串」，与我方 `_matches_keywords` 逐条等价，**那道 RULE 题在参考项目
   里同样命不中**——这不是还原缺口，而是 **⚪ 我方增强**（做的理由：PRD 已承诺「商品上架和审核规则」，
   且内置推荐问题点进去直接未命中）。**方案边界（裁定内容）**：
   - **不引入** Jieba、Embedding、向量库或额外 LLM 调用；采用**确定性相关性评分 + TopN**；
   - 把复合问法拆成受控业务词（「商品上架有哪些规则要求」→ 商品／上架／规则）；标题、路径、正文分别加权；
   - 要求**至少命中一个强业务词 + 一个动作/规则词**，按相关性取 Top 3，而非任一弱词命中即全量返回；
   - **必测反例**：同域干扰文档「商品定价」「商品库存」不得被召回。
     实测依据：初稿曾提议的「二元拆分」会让「商品」命中全域三篇文档，使关键词过滤退化为空过滤；
     原单文档测试结构上无法发现该问题，故新增测试必须含同域干扰文档。
   - **实现**：`app/knowledge/domains.py` 新增 `ACTION_RULE_TERMS`（动作/规则受控词表），
     `app/knowledge/retrieval.py` 新增 `_narrow_by_keywords`：问法同时含业务词与动作/规则词时，
     要求文档两类词表各至少命中一个，再按标题(3)/路径(2)/正文(1)加权取 Top 3；单一业务词问法
     （如「退货量」）维持原有「命中任一关键词」行为不变。TDD 全流程：先写 4 条新测试看着失败，
     实现后转绿，并做过反转验证（临时去掉动作/规则门槛，确认干扰文档测试会红，恢复后再转绿），
     证明测试真的能抓住误召回而非摆设。`tests/unit/knowledge/test_retrieval.py` 20 条全过，
     真实 PostgreSQL 全量门禁 **1008 passed**，`ruff`/`ruff format`/`mypy` 全绿；
8b. **【D2 已裁定：不做通用跨域，仅锁 `PLATFORM_RULE` 特例】**（2026-08-22 用户裁定）。
   参考项目 `loadRelevantWiki()` 每次只接收单一 `QuestionCategory`，**无通用多分类返回协议**；
   但 `PLATFORM_RULE` 是特例（`WikiMemoryService.java:276`）：在 `categoryKeywords()` 之前就 return，
   走「路径含 `rule` **或** 路径+正文含 规则／政策／平台要求」的**全库扫描**。
   **核实结论：我方已经等价，无需改代码**——`app/knowledge/domains.py:24` 的 PLATFORM_RULE 别名正是
   `("规则", "政策", "平台要求", "rule")`，与参考四词一致；`retrieval.py:153` 对该分类豁免索引路径排除，
   保住了全库可达性。**动作项仅为补一条回归测试锁住这个等价**，防止后续改动无声破坏。
   任意多域 TopN 合并 = 我方增强，**本轮不做**；RULE 零命中的实际修复落在第 8 条的 D1 评分，
   而不是扩大全域召回；
9. **取得合并后代码的真实数据库绿灯**：两分支合并涉及 `answer_service.py`/`graph.py` 等核心文件的非平凡冲突解决，合并后必须重跑一次 `REQUIRE_INTEGRATION_DB=1 pytest` 全量与前端全量门禁，不能只信任合并前各自分支的绿灯；
10. **补 F1 人工视觉证据**：按 1440×1000 对照 Prototype，记录布局、间距、字体、颜色和主要交互差异；自动化响应式测试不能替代这一项；
11. **同步剩余进度文档**：更新 `docs/specs/2026-08-11-mvp-exit-evidence-matrix.md` 的 R9、Vitest、Playwright 与当前未验证项；校正 `docs/yshopping-parity-audit.md` 的旧分支基线；回填 `plans/2026-08-12-post-f6-execution-roadmap.md` 阶段 0–2.5 的实际状态；
12. **补完阶段 3 的剩余线上验收项**：Railway 部署本身已完成，仍未做的是**转发头伪造验收**（同一演示 Token 连续更换 `X-Real-IP`/`X-Forwarded-For`，超限仍须返回 429；零费用）、SIGTERM 收尾验收、日志脱敏抽查；
13. **Railway Cron Service 未创建**：`backend/railway.cron.json`、`app/jobs/seed_demo_rolling.py`、`app/core/seed_config.py` 代码侧已就绪，仍需用户在 Railway 控制台建 Service、配置四个变量并手工触发首次执行；
14. **扩大真实模型验收面**（阶段 4）：`classify`/`understand`/`RULE`/`IDENTITY`/生成指标/跨业务查询的真实模型验收覆盖仍不完整，需按完整问题集评估意图准确率是否 ≥90% 并裁定 MVP；执行前必须按 R3 说明调用次数与预计费用；
15. P1 剩余的**附件**：参考项目有 `POST /api/attachments`（`AttachmentController` / `AttachmentService`），
    我方尚未实现对应服务，属 **A 类还原**。**路线并非「均未定」（此前描述有误，已更正）**：
    `docs/PRD.md` §7.2 与附件流程已裁定**对象存储**；`docs/backend-development-plan.md` 已裁定
    **默认本地 OCR（PaddleOCR/Tesseract），不默认调用收费多模态模型**，改用收费模型须先走 R3。
    因此实施前**不得重开这两项决策**，只需定尚未确定的参数：输入尺寸/页数上限、OCR 超时、
    `OcrAdapter` Protocol 与 `FakeOcrAdapter` 注入点、识别结果脱敏规则、同步还是异步解析、
    对象存储具体服务与两个新密钥（R6）。另注意**扫描版 PDF 无文本层，PyMuPDF 取不到文字，仍需 OCR**，
    实施时须区分文本层 PDF 与扫描版 PDF；详细缺口清单见 `plans/2026-08-21-gap-roadmap.md` §2；
16. **【D4 已裁定：不涨预算，先重排】**（2026-08-22 用户裁定）。语义层三项（语义校验闭环、
    新词补齐、简单问题短路）**复用现有重试槽，不新增必经 LLM 调用**。执行顺序：①简单问题确定性
    短路，命中时零 LLM；②新词先走白名单别名映射；③语义校验优先用本地规则与 Pydantic，不增加模型调用；
    ④首次语义校验失败时才按字符上限加载 Session 与同商家记忆；⑤再分析复用 `understand` 现有的
    最多三次机会，**不另加「语义 Reviewer」调用**；⑥预算不足时显式降级，不挤占回答生成与 Reviewer；
    ⑦完成 Fake 评测后再按 R3 做小样本真实费用标定，**只有数据证明不够才另行申请提高上限**。
    最坏路径维持 `classify 2 + understand 3 + metric catalog 1 + (answer + reviewer) × 2 = 10` 次。
    **暂不修改**（现值已由合并带入的预算重新校准确定）：`MAX_LLM_CALLS_PER_REQUEST=10`、
    `MAX_LLM_TOKENS_PER_REQUEST=25000`、`LLM_DAILY_BUDGET_TOKENS=500000`；
17. `DeepSeekLlmClient` 吞掉全部上游错误（`app/llm/deepseek.py` 的 `except (httpx.HTTPError, ValueError): return LlmResult(fallback, 0, True)`）：401、超时、限流、网络不通被压成同一个无声降级；建议把状态码与异常类型写进结构化日志，并让 `record_usage` 区分「上游拒绝」与「模型输出不合格」；
18. **简历口径核对（2026-08-23，纯核对，无代码变更）**：逐条对照简历原文（V2/V3/V4 迭代描述）与当前实现，确认以下四块简历承诺的能力**均未实现**，且现状与 `plans/2026-08-22-parity-and-resume-roadmap.md` 已有裁定一致，未发现新缺口：
    - 指标体系 2000+ 并同步至 Doris——**明确不做**（`AGENTS.md` §9.3 裁定，数据规模远未触发）；
    - 语义层三项：简单问题绕过大模型省 Token、语义层 Agent 二次校验（不符合意图则读 Session+历史记忆再分析）、新词语义层补齐——❌ 全部未实现（roadmap §8，D4 已裁定预算处置原则但功能本身未写）；
    - 无效意图不写入记录表 + 引导用户提工单——❌ 未实现（roadmap §5，我方 `client_request_id` 幂等约束依赖 Answer 行，不能直接照搬"不落库"，需独立设计）；
    - Chat BI 衡量看板（回复采纳率/准确率/平均思考时长/问题命中率/回答失效率的统一看板）——🟢 **功能已实现、验证已达标，仅剩提交（2026-08-24 二次核对更正）**：`ruff`/`mypy`/前端 `typecheck` 已全部转绿，真实 PostgreSQL 全量回归 1049 passed/0 skipped，`docs/yshopping-parity-audit.md` §5.16 已补，详见「本轮核对」一节。唯一未完成项是逐 Task 的 `git commit`（需用户同意）。
    已实现、简历同样有提及的能力（供交叉核对）：意图识别→SQL→自然语言生成+2 条建议、CHAT 自然回答、异步记忆沉淀子 agent（含运营侧人工补充的知识库后台）、按历史高频排序的"猜你想问"、跨业务串行查询 Plan、指标不存在时的受控生成指标兜底、指标命中/未命中的口径展示、前端目录导航与左图右建议布局、双知识库（团队优先/记忆回退）。
19. **收尾 Chat BI 衡量看板并提交**（2026-08-24 新增，接续第 18 条；对照
    `plans/2026-08-23-chatbi-measurement-layer.md` 10 个 Task 逐条核对）：
    - ~~修 mypy/ruff 错误~~ **已完成（2026-08-24，Codex 修复）**：`ruff check`、`mypy app` 均转绿；
    - ~~跑真实 PostgreSQL 回归~~ **已完成（2026-08-24）**：`REQUIRE_INTEGRATION_DB=1 pytest`
      **1049 passed, 0 skipped, 0 failed**，`test_chatbi_rollup.py`/`test_chatbi_qa_daily_schema.py`/
      `test_safe_query_comparison.py` 首次真正执行且通过；
    - ~~补 `docs/yshopping-parity-audit.md` Chat BI 条目~~ **已完成（2026-08-24）**：§5.16 已补；
    - ~~修 `npm run typecheck`~~ **已完成（2026-08-24）**：`ChatComposer.spec.ts` 类型错误已修，
      前端 typecheck 现在干净；
    - **仍未做**：Task 2 Step 7 的 `alembic check`、Task 4 Step 6 的手工 CLI 试跑
      （`uv run python -m app.jobs.chatbi_rollup ...`）未确认执行过；
    - 决定 `ChatComposer.vue` 里孤立的 `attachmentsSelected` 桩代码是随本次一起先落地为
      「UI 已就绪但未接线」，还是等第 15 条附件功能整体设计后再一次性接上——目前没有任何
      父组件监听这个事件，属未完成状态，不要在文案里描述成「附件可选择」；
    - **唯一实质剩余项**：计划里每个 Task 末尾「需用户明确同意」的 `git commit` 步骤一次都
      没执行，`git log` 无新提交。需要你决定是按计划逐 Task 分别提交，还是整体一次提交
      （注意 D1/D3 两项能力，见第 7、8 条，与本次 Chat BI 改动在工作树里已经耦合在一起）。

## 风险与约束

- **双语本地化（`feature/bilingual-localization` 分支）的翻译/隔离专属不变量从未在真实 PostgreSQL
  上验证**：源正文不改、历史语言回填、人工译文过期判定、跨商家缓存隔离反例、游标分页重试等均只有
  Fake 仓储单测覆盖；`LocalizationRepository.purge_expired_machine()`（30 天缓存过期清理）尚无
  Cron 调用；详见本文件顶部 2026-09-05 条目与 `docs/deployment.md`"双语本地化"节。
- **主工作副本当前有大量未提交改动**（2026-08-24 发现）：`git status` 约 60 个文件为
  `M`/`??`，涵盖 D1/D3 能力与全新的 Chat BI 衡量看板，均只存在于工作树里，不在任何提交或
  远端分支上。查看这些能力「是否已完成」时不能只看本文件的文字描述，要先跑 `git status`/
  `git diff` 确认它们是否已落进某次提交——本文件此前把 D1/D3 记成「已实现」但未标注提交号，
  已属于这类未提交状态，本次核对才发现；
- **门禁全绿不等于行为正确**：`history=[]` 曾在 899 passed 的前提下存活到 2026-08-21 才被发现。
  凡是"参考项目传了值、我方传空值"的形参，都要有一条断言输入内容的测试，而不只断言不抛异常；
- 本地 PostgreSQL 测试容器是**一次性数据卷**：`alembic_version` 一旦记录了已被删除/重命名的
  历史迁移号，`command.upgrade(config, "head")` 会直接报错而非自动修复，需重建容器与卷
  （`docker-compose -p borough down postgres && docker volume rm borough_borough_postgres_data`）；
- 真实 PostgreSQL 测试必须独占测试库；并发 `TRUNCATE_ALL_TABLES` 曾导致锁竞争；
- 不得调用真实 LLM；所有自动化测试继续 mock/Fake；
- 团队知识与商家记忆保持单向边界：团队知识优先，记忆仅作同商家回退，绝不升级写回团队库；
- 参考目录 `yshopping-merchant-ai 4/` 只读；业务板块按计划指定的四板块执行，
  即使 importer 排除项与之不一致也不得自行扩大范围；
- **治理：本项目已出现 4 次同类「绕过用户审阅门」问题**（详见「已完成」的治理记录条目），其中第 4 次是编造用户决策原文并写入部署文档。核对任何标注「用户已裁定」「用户已确认」的条目时，应能在对话记录或本文件中找到对应的真实用户发言，找不到则视为未裁定；
- **`FakeLlmClient` 会掩盖整类缺陷**：它返回预写好的合法 JSON，因此「提示词有没有告诉模型该输出什么」这件事在自动化测试里完全不可见。新增或修改任何 LLM 提示词时，**必须同时加一条从 Pydantic 模型推导期望值的提示词契约测试**（范式见 `backend/tests/unit/intent/test_prompts.py`），否则 Fake 全绿而线上必挂；
- **两套重试是乘加关系，调参时必须一起看**：`app/intent/service.py` 的 `MAX_INTENT_RETRIES=2`（understand 最坏跑 3 次）与 `QUALITY_MAX_ATTEMPTS`（每轮最多 2 次模型请求）互相独立，但四个调用点共用同一个 `LlmBudget`。当前最坏路径 10 次，`MAX_LLM_CALLS_PER_REQUEST` 定 10。任何一边加码都要重算这条路径，否则会以「预算耗尽」的面目暴露成意图识别问题；
- 未获用户明确同意，不得调用真实 DeepSeek API、收费 OCR 或日报生成；单元测试必须 mock LLM。真实模型调用前须先说明模型、调用次数和预期费用；
- 商家身份只可由 Bearer Token 解析；后端所有经营查询必须强制注入 `merchant_id`，不得信任前端传入的商家编号；
- **Docker Desktop 在本机环境偶发无法启动或运行中容器意外退出**：曾出现引擎持续返回 `500 Internal Server Error`，或测试库容器在两次真实模型调用之间自行退出；重启 Docker Desktop 并确认容器 `docker ps` 健康后再继续，不要假设代码或配置有问题；
- **真实 PostgreSQL 测试库会在每次全量 `pytest` 后清空 `knowledge_documents`/经营数据表**：真实模型验收前必须重新执行 `backend/scripts/import_wiki.py` 与 `backend/scripts/seed_demo_analytics.py`，不能假设上一次的种子数据仍在；
- `backend/tests/unit/agent/test_stage_reference_hygiene.py` 的 `CURRENT_STAGE` 常量只扫 `app/agent/**` 的字符串字面量；若后续引入新的后端 stage 标记，记得同步推进；
- **`GET /api/admin/ops/status` 是敏感面**：只认 `X-Admin-Token`（`hmac.compare_digest` 比较），`Authorization` 头一律忽略；`ADMIN_TOKEN` 未配置时端点整体不挂载路由（404，而非 401/403）；
- `yshopping-merchant-ai 4/` 与 `yshopping-prototype/` 只读；新代码、文案和资源必须使用 Borough；
- 本机可能存在多个 git worktree 或并行分支；核对进度前先用 `git worktree list`、`git branch -vv` 和 `git log <branch> --oneline` 确认自己看的是哪个分支的状态，不要只看主目录当前签出分支的文件是否存在就下结论——本次合并本身就是这类多分支并行工作在 GitHub 上以 PR 形式汇合的结果。
- `backend/tests/unit/agent/test_stage_reference_hygiene.py` 的 `CURRENT_STAGE` 常量停在 `"B7"`（随 B5/B6/B7 收口时的值）。该常量只扫 `app/agent/**` 的字符串字面量；若后续引入新的后端 stage 标记，记得同步推进，否则该防线会继续只挡旧阶段字样。
- **Docker Desktop 在本机环境偶发无法启动**：曾出现引擎持续返回 `500 Internal Server Error`，完全重启 Docker Desktop 进程后仍未恢复，等了将近 20 分钟后才自行恢复正常。如果下次又遇到真实 PostgreSQL 集成测试连不上库，先确认这不是环境本身的瞬时故障，必要时重启并耐心等待，而不是假设代码或配置有问题。
- **（已解决，2026-08-13）本机 Playwright CLI 曾在执行完用例后不会自行退出**：根因是 Windows 下 Playwright 自带 `webServer` 启动的是 shell 进程树，`child.kill()` 只终止 Node 自身，Vite 派生的子进程会残留占用端口。已改为 `frontend/scripts/e2e-process.mjs` 统一管理 Vite Node 子进程并按真实 PID 收尾（Windows 走 `taskkill /T`，非 Windows 走 `SIGKILL`），常规 Mock E2E 与首屏 E2E 均已验证可正常退出码 0 结束。改动 Playwright 配置或 `mock-e2e-server.mjs`/`first-paint-server.mjs` 时，公共逻辑已抽到 `e2e-process.mjs`，不要重新退回 Playwright 自带的 `webServer`。
- **（已解决）`responsive.spec.ts` 曾有一条与 F6 改动无关的既有失败**：`输入提示和侧栏说明文字达到 WCAG AA 对比度`，已定位为 F6 图表首屏显式挂载后计数断言随之失效，修复后常规 E2E 全量断言均为 `ok`；2026-08-13 用 `--workers=1` 复核仍为 **25 passed**。
- **F6 的 SDD 账本落后于实际执行**：`.superpowers/sdd/2026-08-11-frontend-f6-railway-mvp-closeout/progress.md` 只记到 Task 4，Task 5/6 已完成但账本未回填，核对进度时必须同时查看各 Task 的 report 文件，不能只信账本本身。
- **`GET /api/admin/ops/status` 是新增的敏感面**：只认 `X-Admin-Token`（`hmac.compare_digest` 比较），`Authorization` 头一律忽略；`ADMIN_TOKEN` 未配置时端点整体不挂载路由（404，而非 401/403），避免「路由存在但认证总是失败」暴露端点存在性。修改这块代码时留意 `tests/api/test_admin_ops.py` 的 401/403/404/200 四态断言仍然成立。
- `yshopping-merchant-ai 4/` 与 `yshopping-prototype/` 只读；新代码、文案和资源必须使用 Borough。
- 后端 B4 的具体 Task 状态以 `.superpowers/sdd/2026-08-04-backend-b4-safe-analytics-query/progress.md` 和 Git 提交记录为准；该目录被 `.gitignore` 忽略，只存在于产出它的那个工作副本里，不会随分支/worktree 一起出现。B5/B6/B7 没有对应的 SDD 账本，本文件是这段工作的权威摘要。
- 本机存在多个 git worktree（见「当前阶段」末尾一条），核对进度前先用 `git worktree list` 和 `git log <branch> --oneline` 确认自己看的是哪个分支的状态，不要只看主目录当前签出分支的文件是否存在就下结论。

## 关键入口

- `AGENTS.md`：项目规则、目录与开发顺序。
- `docs/PRD.md`：产品范围与验收标准。
- `docs/backend-development-plan.md`：后端阶段、API/SSE 契约与 B4–B9 顺序。
- `docs/frontend-development-plan.md`：前端 F0–F9 阶段计划。
- `backend/app/services/safe_query.py`：B4 受控查询应用服务；`ExportSpec`/`export_detail` 供 B6 导出复用；R9 Task 12 的 `_generated_metric` 也在这里。
- `backend/app/repositories/analytics.py`：B4 指标聚合与明细数据访问；R9 Task 12 的 `generated_metric`/`_generated_trade_metric`/`_generated_refund_metric` 也在这里，本轮修过状态过滤缺陷，改动前先看「已完成」对应条目。
- `backend/app/agent/graph.py`：B4 真实查询、B5 回答/审核编排接入问答图的落点；`_generated_metric_payload` 是生成指标口径载荷的落点。
- `backend/app/intent/models.py`、`whitelist.py`：`GeneratedMetricPlan`/`CrossBusinessPlan` 的结构校验与降级语义；`whitelist.py` 本轮修过「被拒绝计划未清空」的缺陷。
- `backend/app/services/answer_service.py`、`review_service.py`、`visualization_service.py`：B5 回答草稿、独立 Reviewer 与安全图表；`visualization_service.py` 本轮修过生成指标选列缺陷。
- `backend/app/services/export_service.py`、`feedback_service.py`：B6 签名 CSV 导出与商家反馈。
- `backend/app/services/quality_loop.py`、`quality_types.py`：生成 → 本地校验 → 独立复核 → 回喂重试 → 确定性兜底的统一质量循环；轮次由 `QUALITY_MAX_ATTEMPTS` 注入，降级原因分 `UPSTREAM`/`VALIDATION`/`BUDGET` 三类。
- `backend/app/jobs/seed_demo_rolling.py`、`app/core/seed_config.py`：演示数据的每日增量滚动入口与其最小配置；写入需 `ALLOW_DEMO_DATA_REFRESH=true` 且数据库商家集合与三个演示商家精确相等。
- `backend/app/analytics/demo_data.py` 的 `DEMO_ANALYTICS_SEED_BASE = 20260804`：演示经营数据随机基线的**唯一来源**，第 i 个商家用 `BASE + i`，滚动 Job 与 `backend/scripts/seed_demo_analytics.py` 共用。`scripts/seed_demo_data.py` 的 `--random-seed 20260730` 只作用于商家表，与经营数据无关，别拿错常量。
- `backend/app/api/routes/exports.py`、`feedback.py`：B6 对外端点。
- `backend/app/llm/guard.py`、`app/core/rate_limit.py`、`app/core/client_ip.py`、`app/repositories/llm_budget.py`：B7 费用防护/限流/可信代理 IP 基础设施；`client_ip.py` 本轮修过头优先级缺陷，必测见 `tests/unit/core/test_client_ip.py`、`tests/api/test_rate_limit_trust_boundary.py`。
- `backend/app/core/metrics.py`、`app/api/routes/admin.py`：B7 运维可观测性与 `GET /api/admin/ops/status` 运维端点。
- `backend/railway.json`、`docs/deployment.md`：B7 Railway 配置即代码与部署运维手册，含阶段 2.5 的转发头信任策略与线上验收步骤；实际部署仍需用户在 Railway 控制台执行。
- `frontend/scripts/e2e-process.mjs`：本轮新增的 E2E 子进程管理公共逻辑，`mock-e2e-server.mjs`/`first-paint-server.mjs` 均基于它。
- `backend/tests/integration/services/test_safe_query_security.py`：B4 §验收清单的安全回归测试（跨商家隔离、SQL 注入、180 天上限、statement timeout、拒绝原因不泄漏 SQL/表名）。
- `backend/tests/integration/repositories/test_analytics_repository.py`：含 R9 Task 12 生成指标的正确性回归，本轮新增退款状态过滤与订单状态过滤两条用例。
- `backend/tests/api/test_exports.py`、`test_feedback.py`：B6 端点的 HTTP 契约测试（签名、过期、跨商家、公式注入、BOM）。
- `plans/2026-08-09-b7-f4-integration-and-r9-remediation.md`：B7/F4 分支整合与 R9 差异整改的执行计划，R9 阶段 B 的四个能力切片子计划均在此文档体系下。
- `plans/2026-08-12-post-f6-execution-roadmap.md`：R9 阶段 B、阶段 2.5、Railway 部署与真实模型验收的路线图；阶段 0/1 的检查框落后于实际执行，核对时以本文件与 Git 提交为准。
- `plans/2026-08-11-frontend-f6-railway-mvp-closeout.md`：F6「Railway 部署就绪」实施计划，Task 1–8、12 已完成，Task 9–11 待用户操作。
- `docs/specs/2026-08-11-mvp-exit-evidence-matrix.md`：MVP 出口证据矩阵，尚未回填 R9 阶段 B / 阶段 2.5 的完成状态。
- `docs/yshopping-parity-audit.md`：R9 还原度差异清单，🔴 真实缺口 §3.1–§3.6 已全部标记修复。
- `backend/app/services/memory_admin_service.py`、`memory_service.py`、`memory_agent.py`：管理员手动记忆压缩编排、压缩结果与降级信号、异步沉淀子 agent（本分支新增）。
- `backend/app/services/report_service.py`、`app/api/routes/reports.py`、`app/schemas/report.py`：每日经营日报的服务、路由与契约（本分支新增）。
- `frontend/src/components/chat/DailyReportCard.vue`、`frontend/src/api/report.ts`：日报前端卡片与 API 封装（本分支新增）。
- `backend/app/services/chatbi_service.py`、`app/repositories/chatbi.py`、`app/analytics/chatbi_metrics.py`、`app/jobs/chatbi_rollup.py`、`app/api/routes/analytics.py`：Chat BI 衡量看板的服务、汇总仓储、指标公式、幂等重刷 Job 与管理员端点（2026-08-24 核对发现，**尚未提交**，见「本轮核对」）。
- `frontend/src/views/OpsDashboardView.vue`、`frontend/src/stores/analytics.ts`、`frontend/src/api/analytics.ts`：Chat BI 管理员看板页面、Store 与 API 封装（同上，**尚未提交**）。
