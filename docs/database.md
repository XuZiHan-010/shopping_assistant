# 数据库结构与迁移

本页记录 Borough 当前 PostgreSQL `public` schema 的业务表分工。产品状态机与验收规则以
[`PRD.md`](PRD.md) §7–§8 为准；API 字段以 [`backend-development-plan.md`](backend-development-plan.md)
§8 为准。ORM 在 `backend/app/models/`，迁移在 `backend/migrations/versions/`。

## N1 C 数据表

六张 v1 经营表原地扩展，不复制第二套商品或订单事实：

| 表 | N1 扩展 | 事实边界 |
| --- | --- | --- |
| `products` | 内容描述、带来源的属性、图片、在库量、占用量、缺货阈值、内容版本和源语言 | 可售量由 `stock_on_hand - stock_reserved` 派生；数据库拒绝负库存和超占用 |
| `orders` | 支付、履约、售后三维投影；关闭原因、生命周期来源、源时区 | `order_status` 是 v1 兼容投影，必须与三维状态一致；`LEGACY_V1` 不进入 v2 交易流程 |
| `order_items` | 单价、优惠额、行总额价格快照 | 行总额与旧 `item_amount` 保持一致；金额为 `Numeric(14, 2)` 元 |
| `refunds`、`returns` | 可空 `after_sale_id` | 历史行保持 NULL，不伪造 v2 售后事项 |
| `support_tickets` | 唯一的可空 `after_sale_id` | 一个 v2 售后事项至多对应一个工单 |

新表按功能分组：

| 表 | 用途与隔离键 |
| --- | --- |
| `inventory_events`、`fulfillment_events`、`after_sale_events` | 按商家隔离的追加写事件账本；`dedupe_key` 唯一，数据库触发器拒绝 UPDATE / DELETE |
| `drafts`、`change_ledger` | 按商家隔离的待批准草稿与已应用变更记录；批准不保存为草稿状态 |
| `coupons`、`guardrail_configs` | 按商家隔离的促销券与定价护栏 |
| `customer_memories` | `merchant_id + buyer_key` 双键隔离的顾客记忆；唯一键 `(merchant_id, buyer_key, category, key)`（2026-10-01 迁移 `20261001_0046` 加入 `category`，同类同 key 更新、不同类不互相覆盖） |
| `merchant_memory_facts`、`merchant_memory_summaries` | 按商家隔离的事实层与摘要层；事实必须有来源 |
| `customer_signals` | 按商家隔离的顾客信号；`CONTENT_GAP` 表示商品内容缺口，不保存顾客提问原文 |
| `daily_briefs` | 按商家和营业日唯一的当日简报 |
| `after_sales`、`after_sale_lines` | 售后状态机主记录与订单行退款快照；历史退款/退货不会自动生成主记录 |
| `idempotency_records` | 按角色、主体摘要、商家、操作和客户端请求 ID 唯一的 v2 幂等记录；主体摘要复用 `app/core/session.py` 的 `principal_digest`，不存明文 `buyer_key` |

既有 `merchants`、会话/消息、回答与反馈、导出、审计、LLM 用量、知识库、商家 v1 记忆、
Chat BI 汇总及本地化表继续保留。`agent_sessions` 与来源状态表由 N1 D 会话身份计划负责，
不属于 C 的八个迁移。数据库不使用专用 Borough schema。

`feedback` 表新增可空 `reason` 列（迁移 `20260923_0027`），只供 v2 反馈契约（§8.14.1）的
赞踩原因使用；v1 反馈从不写入该列，v1 路径与响应不受影响。

## N4 B 记忆内部状态

迁移 `20260928_0042` 补齐 v2 记忆管线的内部状态，不改变 §8.14 的 API 字段，也不迁移 v1 `merchant_memories`。

| 表 / 列 | 约束与用途 |
| --- | --- |
| `memory_extraction_jobs` | `message_id` 唯一并外键引用 `messages.id`，一条已落库的用户回合至多一项任务；仅保存消息 ID、状态（`PENDING` / `PROCESSING` / `DONE` / `FAILED`）、尝试次数、租约截止、最后错误与时间戳，不复制 `merchant_id` 或 `buyer_key`。按状态和租约截止建立领取索引；任务执行时从消息及会话解析身份 |
| `messages.session_record_id` | v2 用户回合可空的服务端会话记录外键，历史/v1 消息保持 NULL；outbox 排空时由消息反查当时可信会话角色、商家和已绑定顾客。会话记录被清理时置空，该任务安全放弃，不猜测身份 |
| `customer_memory_preferences` | `(merchant_id, buyer_key)` 复合主键；`memory_enabled` 默认为 true，未建行也视为开启；按店铺和已绑定顾客隔离。关闭开关与清空该顾客记忆必须在同一事务完成 |
| `merchant_memory_summaries.is_stale`、`source_fact_ids` | 陈旧标记默认 false；`source_fact_ids` 为生成该总结时使用的事实 UUID 列表（JSONB，默认空数组）。删除事实后，依赖它的总结标为陈旧，重建前不注入 Chat |
| `llm_usage.purpose = MEMORY` | N4 B 抽取用量与主回答 `AGENT`、本地化 `LOCALIZATION` 分列统计；三者共用同一每日预算熔断，抽取单任务另有独立调用与 token 上限。迁移 `20260928_0044` 扩展检查约束 |

迁移 `20260928_0043` 为商家事实增加可空 `deleted_at` 墓碑，以区分「重复删除本人事实」与「目标不存在/跨商家」；事实列表、总结重建和召回均排除墓碑。总结表增加 `(merchant_id, category)` 唯一约束，保证每类一份文档。

outbox 领取使用 `FOR UPDATE SKIP LOCKED`；任务租约到期后允许重新领取，完成写入以消息 ID 幂等。180 天顾客记忆过期在读取路径判断，清理 Cron 迟跑不能延长可召回期限。

## N4 C 知识索引版本

迁移 `20261002_0047` 启用 `vector` 扩展（`CREATE EXTENSION IF NOT EXISTS vector`；外部 Neon 与本地
`pgvector/pgvector:pg16` 均为 0.8.6），并新增三张表实现 PRD §7.6 的版本化原子切换。团队知识对所有商家一致，
三张表都不含 `merchant_id`，也不含任何商家数据或记忆。

| 表 / 列 | 约束与用途 |
| --- | --- |
| `knowledge_index_versions` | 每次构建一行，`id` 即版本号（自增）。`status` 只取 `BUILDING` / `VALIDATING` / `READY` / `FAILED`——「生效」不是状态而是指针；`failure_reason` 为稳定原因码，与 `FAILED` 成对（检查约束），不存异常原文。另存嵌入模型名、维度、语料指纹（按文档路径与内容哈希）、文档/分块数、本版本与上一生效版本的验证 Recall@5。部分唯一索引 `uq_knowledge_index_versions_single_build`（`WHERE status IN ('BUILDING','VALIDATING')`）保证同一时刻至多一个构建；崩溃遗留的构建行超过 30 分钟在下次构建前回收为 `BUILD_TIMEOUT` |
| `knowledge_chunks` | 按版本写入的分块与向量；`version_id` 外键级联删除；`(version_id, source_path, chunk_index)` 唯一。`embedding` 为**不带维度**的 `vector`：语料只有几十块，查询精确扫描，不建 ANN 索引；换模型时新版本可直接写入不同维度。**从不 `UPDATE`**：切换后只 `DELETE` 更早版本的分块（保留生效版本与上一版），版本行保留作历史 |
| `knowledge_index_state` | 单行指针（`id = 1` 检查约束）：`active_version_id`（外键 `RESTRICT`）、`stale` 与 `stale_reason`（`BUILD_FAILED` / `CORPUS_CHANGED`，与 `stale` 成对）。原子切换只在一个事务里改这一行；知识后台写文档时在同一事务把它标陈旧 |

查询用一条 SQL 同时连接指针、版本与分块（并要求模型名与维度一致），READ COMMITTED 下单条语句只看到一个快照，
所以一次检索不会混合新旧版本。分块正文只用于排序，返回给模型的正文始终取自当前 `knowledge_documents`。

## N5 MCP 凭证、三级预算、价格版本与 Cron 状态

四条迁移都是纯新增，接在 `20261002_0047` 之后，唯一 head 为 `20261004_0051`。

| 迁移 | 表 / 列 | 约束与用途 |
| --- | --- | --- |
| `20261003_0048` | `mcp_credentials` | MCP 只读凭证（PRD A8）。只存凭证的 SHA-256 指纹（`token_fingerprint` 唯一），不存原值；`merchant_id` 外键级联删除；`scopes` 为非空 JSONB 数组；`expires_at > created_at`；`revoked_at` 非空即已撤销。签发、撤销只经 `backend/scripts/mcp_credentials.py`，没有 HTTP 路径 |
| `20261003_0049` | `llm_daily_budget.scope_key` | 每日预算按级别分行：`GLOBAL`、`ROLE:CUSTOMER` / `ROLE:MERCHANT`、`SHOP:<角色>:<merchant_id>`；唯一约束由 `(usage_date)` 改为 `(usage_date, scope_key)`。历史行默认 `GLOBAL`。预留额度时三级在同一事务里全有或全无 |
| `20261003_0050` | `model_price_versions` | 模型价格版本：高峰 / 非高峰 × 缓存命中 / 未命中 / 输出共六个单价（每百万 token）、`currency`、`effective_from`、`source_note`；`(model, effective_from)` 唯一。`BEFORE UPDATE OR DELETE` 触发器强制**只追加**——价格变动新增一行，不改旧行。初始两行为 2026-10-03 核实的 `deepseek-flash` 与 `deepseek-v4-pro` 官方价格 |
| `20261003_0050` | `llm_usage` 新列 | `role`、`cache_hit_tokens`、`price_version_id`、计价时段与成本列。成本在**写入时**按当时生效的价格版本算好并存储，查询不重算；历史行这些列为 `NULL`（未定价），不按新价格回算 |
| `20261004_0051` | `scheduled_job_runs` | Cron 分发器的任务状态，每个任务一行：`job_name` 主键、`last_slot`（最近一次成功的时间片起点，失败不推进）、`last_status`（`OK` / `FAILED`）、`last_error`（只存异常类别）、`last_run_at`、`run_count` |

`mcp_credentials` 按 `merchant_id` 隔离。`llm_daily_budget`、`model_price_versions`、`scheduled_job_runs` 是系统级表，
不含经营数据，没有 `merchant_id`；`llm_daily_budget` 的店铺级行只在 `scope_key` 里带商家 ID，运维接口对外只给它的脱敏摘要。

## N3 B 售后闭环

| 迁移 | 表 / 列 | 事实边界 |
| --- | --- | --- |
| `20260925_0035` | `after_sales` 对话摘要快照列、`after_sale_supplements` | 顾客补充说明按商家和售后事项隔离；脱敏后保存；摘要只保存确认时的可用性和脱敏正文 |
| `20260925_0038` | `customer_signals` 的按日部分唯一索引 | 同商家、日期、类型、商品聚合一条提醒；信号只是售后事实的派生，不存顾客标识 |
| `20260925_0039` | `after_sale_challenge_previews` | 一次性确认证据对应的摘要快照，按商家与主体摘要绑定；提交后复用预览结果 |
| `20260925_0040` | `after_sale_replies` | 商家审批回复与售后决定同事务生效；`draft_id` 唯一；顾客和商家只从售后详情读取已送达正文 |

售后退款写 `refunds`，收到退货写 `returns`，可售回补写 `inventory_events`；
`after_sale_events` 仍是状态迁移的追加写账本。历史退款/退货不回填售后主记录。

## N3 C 商家经营指标

迁移 `20260927_0041` 在既有 `metric_definitions` 中登记 `net_gmv` 的受控口径资产：
净成交额按支付日毛成交额减去按退款发生日退款额，分类维度通过已退款订单项归属。
该资产供口径问答展示，不作为可执行 SQL，也不扩大 v1 指标查询白名单。

## N2 交易闭环（模块 B）

`n2-trade-closed-loop` 新增三个迁移，均可升降级：

| 迁移 | 表 / 列 | 事实边界 |
| --- | --- | --- |
| `20260923_0030` | 新表 `cart_items` | 主体二选一：已绑定顾客 `(merchant_id, buyer_key)` 或访客 `guest_session_id`（`agent_sessions.id`），CHECK 互斥；两条部分唯一索引支撑「设置绝对数量」的 upsert。**不占库存、不存价格**，价格与可售性在提交订单时重算。访客购物车在绑定演示顾客时并入并清空 |
| `20260923_0031` | `orders.coupon_id`、`orders.closed_at`、`order_items.title_snapshot`；部分索引 `ix_orders_v2_pending_placed_at` | 均可空，历史行为空。`closed_at` 与 `payment_status = 'CLOSED'` 由支付 / 关闭服务在同一条条件更新里一起写；`title_snapshot` 是价格快照的一部分，商品改名不影响历史订单 |
| `20260923_0032` | `conversations.owner_kind`、`conversations.owner_id` | 顾客对话的登录主体，与 `conversation_provenance` 同口径（访客 = 会话记录 ID，已绑定 = 主体摘要，不存 `buyer_key`）；两列成对为空或非空。商家对话与历史行为空，商家不能续写顾客对话 |
| `20260923_0033` | `conversations.surface`、`conversations.deleted_at`、`messages.response_payload` | 双端会话目录（N2 模块 D Task 1）：`surface` 标记 v2 顾客 / 商家 Chat 创建的对话（`SHOP` / `MERCHANT`，v1 历史行为空、不进入 v2 目录）；`deleted_at` 为目录软删除，非空后对外 403 且不能续写；`response_payload` 存 v2 助手消息的完整最终响应，供目录详情逐字段回放。部分索引 `ix_conversations_directory` 只覆盖未删除的 v2 对话 |
| `20260923_0034` | `answers.surface`；`uq_answers_merchant_client_request` 改为部分唯一索引 | v2 Chat 回答落 `answers`（`id` 即响应 `id`），使 `feedback.answer_id` 外键可指向 v2 回答。`surface` 为 `SHOP` / `MERCHANT`，v1 行为空；唯一索引只约束 v1 行（`WHERE surface IS NULL`），v2 幂等由 `idempotency_records` 按主体裁决（契约 §8.7.3）。v1 仓储、v1 反馈与 Chat BI 只读 `surface IS NULL` 的行；降级会删除全部 v2 回答行 |

v2 订单写入路径（结账、支付、取消、超时关闭）在同一事务里更新三维投影与兼容 `order_status`，
并追加 `fulfillment_events`（`ORDER_PLACED` / `PAYMENT_CONFIRMED` / `ORDER_CLOSED`，后者载荷带存储值
`close_reason`）与 `inventory_events`（`ORDER_RESERVE` / `PAYMENT_DEDUCT` / `RESERVATION_RELEASE`）。
`rebuild_projections` 对这些订单重算零漂移（有测试守住）。

## 历史数据与投影

关闭原因的存储值保持 `CUSTOMER_CANCEL` / `TIMEOUT`；API 使用冻结契约的
`USER_CANCELLED` / `PAYMENT_TIMEOUT`。边界统一调用
`app/domain/order_status_mapping.py` 的 `close_reason_to_api` / `close_reason_from_api`，
空值原样传递，未知值拒绝；不为统一词汇改写既有事实或历史迁移。

M2 在一个 PostgreSQL 事务中预检既有订单的 `paid_at` 与状态是否相符、订单行数量及单价能否无损回推。
预检失败时整个迁移回滚；通过后才回填三维状态、`LEGACY_V1` 来源和价格快照。
`order_status` 与 `item_amount` 原值不改，降级删除新增列后 v1 数据仍可读取。

M3 为既有订单补写带 `LEGACY_V1_BACKFILL` 来源的履约事件。推定时间标记为
`time_inferred`，只用于投影重算，不作为履约时效的真实证据。投影重算只报告漂移，
不自动覆盖订单状态。v2 写入路径须在同一事务中写事件、三维投影及兼容状态。

## 迁移与本地验证

C 的 M1–M8 各占一个独立可升降级迁移，按实际创建顺序接在单一 Alembic head 后面。
迁移文件不得 import 可变的应用状态映射代码；映射与迁移 SQL 用对照测试保持一致。
全部升降级及约束测试只连接名称以 `_test` 结尾的可丢弃本地 PostgreSQL 库：

```powershell
cd backend
$env:TEST_DATABASE_URL = 'postgresql+psycopg://borough:borough_local@127.0.0.1:55432/borough_test'
$env:REQUIRE_INTEGRATION_DB = '1'
uv run pytest tests/integration/test_migrations.py tests/integration/test_legacy_backfill.py -q
```

完整测试会清空测试库中的演示与知识数据。恢复本地三家商家、经营数据和 S1–S4 场景的顺序见
[`deployment.md`](deployment.md)「演示前数据检查清单」。追加写事件在每日滚动经营窗口清理后仍保留为审计记录；
其保留期与受控归档由后续运维阶段定义。
