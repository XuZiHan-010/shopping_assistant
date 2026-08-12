# Borough 后端开发计划

> 适用对象：后端开发人员、全栈开发人员、coding agent  
> 产品名称：Borough 商家 AI 助手  
> 目标技术栈：Python 3.12 + FastAPI + PostgreSQL  
> 产品范围：以 `docs/PRD.md` 为准  
> 工程规则：以根目录 `AGENTS.md` 为准

---

## 1. 开工前必读

按顺序读取：

1. `AGENTS.md`
2. `docs/PRD.md`
3. `yshopping-merchant-ai 4/yshopping-merchant-ai/docs/architecture.md`
4. `yshopping-merchant-ai 4/yshopping-merchant-ai/docs/architecture-detail.md`
5. 旧项目 Agent、Intent、Query、Answer、Reviewer 和 Wiki Service
6. 旧项目对应测试
7. `yshopping-merchant-ai 4/yshopping-merchant-ai/runtime/llm-wiki/`

重构时复用业务契约、安全规则和可观察行为，不逐行翻译 Java。优先提取可独立测试的 Deep Module。

> **旧项目有一处安全反例，读到时不要沿用。** `MerchantQaLangGraph.loadMerchant()` 的注释写着"默认本地商家为 100，也支持前端透传 merchantId"——它信任前端传入的商家 ID。新实现的商家身份只能来自 Token 解析，见 §6.1 与 §15。

---

## 2. 后端目标

后端交付物必须做到：

- FastAPI 提供稳定、可生成 OpenAPI 的接口；
- 使用 PostgreSQL 支持 MVP 经营数据、会话、反馈和知识；
- 使用可信 Merchant Context 实现商家隔离；
- LLM 只输出结构化意图，不直接产生或执行 SQL；
- 安全查询模块统一处理白名单、日期、行数和参数绑定；
- `METRIC`、`DETAIL`、`RULE`、`IDENTITY`、`CHAT`、`INVALID` 六种模式形成完整闭环；
- 回答包含口径、图表数据、建议和质量状态；
- 聊天接口以 SSE 推送执行进度，用户 1 秒内看到真实的处理阶段；
- 推荐问题来自服务端预置配置，不由模型生成；
- Reviewer 有固定重试上限和显式降级；
- LLM 有单请求上限、每日预算熔断和基础限流；
- 单元和集成测试默认使用 Fake LLM；
- Docker 化并可部署到 Railway；
- 第一阶段不依赖 Redis、Doris 或 MySQL。

---

## 3. 技术选择

### 3.1 运行依赖

| 依赖 | 用途 |
| --- | --- |
| `fastapi` | API 框架 |
| `uvicorn` | ASGI Server |
| `pydantic` | 请求、响应和结构化意图 |
| `pydantic-settings` | 环境变量 |
| `sqlalchemy` | ORM 和 SQL Core |
| `alembic` | 数据库迁移 |
| `psycopg` | PostgreSQL Driver |
| `httpx` | LLM 和外部服务客户端 |
| `langgraph` | Agent 状态编排 |
| `structlog` | 结构化日志 |
| `python-multipart` | 文件上传 |
| `sse-starlette` | Chat SSE 事件流（也可直接用 FastAPI `StreamingResponse` 手写，见 §8.4） |

限流在 MVP 使用进程内计数器实现，不引入额外依赖，也不依赖 Redis。

### 3.2 附件与数据处理

P1 使用：

| 依赖 | 用途 |
| --- | --- |
| `polars` | CSV 和表格处理 |
| `openpyxl` | Excel |
| `pymupdf` | PDF |
| `pillow` | 图片检查 |
| S3 SDK | 对象存储 |

### 3.3 测试与质量

| 依赖 | 用途 |
| --- | --- |
| `pytest` | 测试 |
| `pytest-asyncio` | 异步测试 |
| `pytest-cov` | 覆盖率 |
| `respx` | mock HTTP |
| `ruff` | lint 和格式检查 |
| `mypy` 或 `pyright` | 静态类型检查 |
| `testcontainers` | 可选 PostgreSQL 集成测试 |

依赖和版本统一维护在 `pyproject.toml` 与 `uv.lock`。

---

## 4. 目标目录

```text
backend/
├── Dockerfile
├── pyproject.toml
├── uv.lock
├── alembic.ini
├── app/
│   ├── __init__.py
│   ├── main.py
│   ├── api/
│   │   ├── router.py
│   │   ├── dependencies.py
│   │   └── routes/
│   ├── agent/
│   │   ├── graph.py
│   │   ├── state.py
│   │   ├── intents.py
│   │   └── nodes/
│   ├── core/
│   │   ├── config.py
│   │   ├── security.py
│   │   ├── errors.py
│   │   └── logging.py
│   ├── db/
│   │   ├── base.py
│   │   └── session.py
│   ├── models/
│   ├── schemas/
│   ├── repositories/
│   ├── services/
│   ├── prompts/
│   └── knowledge/
├── migrations/
│   ├── env.py
│   └── versions/
└── tests/
    ├── unit/
    ├── api/
    ├── integration/
    ├── agent/
    ├── fixtures/
    └── fakes/
```

按开发阶段创建真实文件，不批量创建没有职责的空模块。

### 包名与 schema 决策

这两项曾与 `AGENTS.md` 冲突，已定稿：

| 项 | 取值 | 说明 |
| --- | --- | --- |
| Python 发行项目 | `borough-merchant-ai` | `pyproject.toml` 的 `name`，品牌名在这里体现 |
| Python 导入根包 | **`app`** | 源码在 `backend/app/`，导入写 `from app.services...`。**不存在 `borough.agent` 这类导入路径** |
| 启动命令 | `uv run fastapi dev app/main.py` | 与目录一致 |
| PostgreSQL schema | **默认 `public`** | 不使用专用 `borough` schema |

因此：ORM 模型不写 `__table_args__ = {"schema": ...}`；连接串不设 `search_path`；Alembic 不配 `version_table_schema`，`alembic_version` 留在默认 schema；测试库和 Seed 脚本同样不指定 schema。所有环境使用同一套默认值，不允许各自不同。

---

## 5. 后端架构边界

### 5.1 API Layer

负责：

- 身份依赖；
- 请求校验；
- 调用应用服务；
- HTTP 状态码；
- 响应 Schema。

不负责：

- 拼 SQL；
- 调 LLM；
- 处理业务分支；
- 直接访问 ORM Session。

### 5.2 Application Service

负责：

- 用例编排；
- 事务边界；
- 调用 Repository、Agent 和外部服务；
- 将领域结果转换为 API Schema。

### 5.3 Agent Layer

负责：

- 意图理解；
- 知识和指标检索编排；
- 调用安全查询；
- 回答生成；
- Reviewer；
- 有限重试和状态记录。

Agent 不直接依赖 FastAPI Request 或 Response。

### 5.4 Repository

负责：

- 数据库查询和持久化；
- 返回稳定领域对象或结果 DTO；
- 参数绑定；
- 必要的数据库特定优化。

Repository 不调用 LLM，也不返回开放的任意 SQL 执行能力。

### 5.5 External Client

LLM、对象存储和未来 Doris 客户端必须通过协议接口注入，测试使用 Fake 实现。

---

## 6. Deep Modules

## 6.1 Merchant Context

### 输入

- 请求头 `Authorization: Bearer <token>`；
- 服务端持有的演示 Token → 商家映射配置。

### 输出

```python
class MerchantContext:
    merchant_id: UUID
    is_admin: bool
```

**MVP 没有 user 概念。** 不建 `users` 表，Token 直接映射到商家，会话与反馈归属到商家。管理员身份由独立的 `ADMIN_TOKEN` 判定（**P0 起即需要**，用于 B7 的运维端点；P1 的知识库后台复用同一变量），走独立请求头 `X-Admin-Token`，不是用户行；真实用户体系留到 P2 的 SSO。

业务时区不是本模块的字段。全局固定为 `Asia/Shanghai`，由配置提供，见 §7.2。

### 规则

- **永不信任请求正文、查询参数或请求头中由前端指定的 `merchant_id`**；
- Token 无效或缺失返回 `401`；
- 请求的资源属于其他商家时返回 `403` 并写入审计日志；
- 所有经营查询都要求 Merchant Context；
- 管理员操作必须显式授权并审计。

### 必测

- 正文伪造商家 ID 无效；
- 缺少或非法 Token 返回 401；
- 访问其他商家资源返回 403 且产生审计记录；
- 管理员令牌未配置时管理接口返回 403；
- 导出、附件和会话隔离。

> **不要照搬旧实现的这一处。** 参考项目 `MerchantQaLangGraph.loadMerchant()` 的注释写着"默认本地商家为 100，也支持前端透传 merchantId"——旧实现信任前端传入的商家 ID。这正是本模块要消除的漏洞，读旧代码时不要沿用。

---

## 6.2 Intent Contract

### 输出字段

```text
answer_mode
category
metric
dimensions
filters
date_range
sort
limit
followup_reference
needs_attachment
analysis_requested
cross_business_plan
generated_metric_plan
```

### 规则

- `answer_mode` 使用枚举；
- metric 使用**英文 `metric_code` 枚举**，不接受中文指标名——模型输出的中文变体（空格、简繁、同义词）会造成漏命中；
- dimension、filter field 使用白名单；
- **三套白名单（指标、维度、筛选）在本阶段建立**，不留到查询阶段，否则本阶段的验收无法执行；
- 日期范围由后端再次限制；
- limit 由后端覆盖上限；
- 不允许输出 SQL 字符串；
- 不允许输出任意表名；
- 解析失败有限重试，仍失败则返回 INVALID 或显式降级。

### R9 受控扩展

`analysis_requested` 是模型输出的布尔值；后端据 `answer_mode == DETAIL and not analysis_requested`
计算纯明细模式，模型不得直接输出 `table_only`。

`cross_business_plan` 是可空的嵌套意图，只允许 `ORDER_TO_REFUND`、`ORDER_TO_GOODS`、
`ORDER_REFUND_GOODS` 与长度受限的 `sub_order_no`。计划缺失时正常走基础查询；计划对象存在但子对象
校验失败时，在 `QueryIntent` 的 before validator 中清空该计划并追加语义说明，基础意图仍保持 VALID，
不得升级为 INVALID。

`generated_metric_plan` 是可空的嵌套意图。`name`、`unit` 仅供展示；`group_by` 和 `filter_column`
只允许 `spu_id`、`address_city_name`，筛选列和值必须同时出现。后端按业务类别选择固定 SQLAlchemy
聚合模板，不接受模型给出的 SQL、公式、表名或任意列名，也不引入 `measure` 枚举。未命中白名单或形状
非法时，整条意图必须为 INVALID（`answer_mode=INVALID`、`category=UNKNOWN`）；此处故意不同于跨业务计划的
回退语义。

---

## 6.3 Safe Analytics Query

### 稳定接口

```python
async def execute(
    context: MerchantContext,
    intent: QueryIntent,
) -> QueryResult:
    ...
```

### QueryResult

```text
columns
rows
total_rows
truncated
source_tables
plan_steps
export_spec
```

### 规则

- 路由由 `answer_mode + category + metric` 决定；
- 查询模板由 Python 代码或受控 SQLAlchemy 表达式生成；
- 值参数绑定；
- 强制 `merchant_id`；
- 明细默认预览不超过 200 行；
- 最大日期范围 **180 天**，与演示数据天数对齐，避免出现"允许查询但没有数据"的区间；
- 添加 statement timeout；
- 禁止 `SELECT *`；
- 禁止把数据库异常原文直接返回用户。

---

## 6.4 Metric Catalog

每个指标具有稳定的英文标识 `metric_code`（如 `paid_gmv`、`refund_rate`）和中文展示名 `display_name`。`metric_code` 是白名单、接口路径和内部引用的唯一键；中文名只用于展示，不参与匹配。

检索顺序：

1. 正式指标表；
2. 数据库字段注释或内置映射；
3. 由模型生成的候选口径。

生成口径必须：

- `generated=true`；
- 带待核验 Notice；
- 不自动写入正式指标；
- 不作为永久事实重复使用，除非管理员确认。

---

## 6.5 Knowledge Retrieval

检索分**两层**，对应 Agent Graph 中两个不同位置的节点：

**第一层 · 索引（意图识别之前）**

加载知识库的目录与摘要，不加载正文。此时业务域未知，这一层的作用是让模型自己拆词、认出业务域和指标词汇。参考实现就是这个顺序：`loadHistoryAndWiki()` 用 `QuestionCategory.UNKNOWN` 加载 wiki index，注释写明"供 LLM 自己拆词和理解业务域"，随后才 `recognizeIntent()`。

**第二层 · 正文（意图确定之后）**

业务域已知，按域取对应的流程、名词、表结构和规则正文。

两层分开的原因：只做前置检索会把全部知识灌进 Prompt，浪费 token 且稀释相关性；只做后置检索则意图识别失去业务词汇上下文，分类准确率下降。

每层的检索顺序：

1. 团队维护知识；
2. 商家级已确认记忆（P1）；
3. 明确返回未命中。

规则：

- 团队知识只允许管理员写；
- 商家记忆按 `merchant_id` 隔离；
- 返回来源 ID、标题、版本和更新时间；
- 运行时可编辑知识保存在 PostgreSQL；
- 导入旧 Markdown 只通过受控脚本进行；
- 索引层有大小上限，超出时按业务域优先级截断而不是整体塞入。

---

## 6.6 Answer Composition

输入：

- 用户问题；
- Intent；
- Metric Definition；
- Query Result；
- Knowledge Sources；
- Attachment Extraction。

输出：

- answer；
- visualization；
- recommendations；
- 语义说明（写入 `quality_notes`，**不新增 `semantic_notes` 字段**，见 §8.2）。

**不输出 suggestions。** 推荐问题由独立的 Suggested Questions 模块从预置配置提供，见 §6.8。

规则：

- 有数据的分析至少两条建议；
- 建议包括标题、证据和行动；
- 数字必须来自 Query Result；
- 不对平均值、比例等非加和指标求和；
- 规则回答不伪造数据查询；
- 无数据时解释“无数据”，不得生成虚构数字。

---

## 6.7 Answer Review

Reviewer 输入：

- 原问题；
- 结构化意图；
- 查询结果摘要；
- 候选回答；
- 建议和图表定义。

Reviewer 输出：

```text
passed
issues
```

规则：

- Reviewer 不重写回答；
- 不执行查询；
- 最大生成/审核轮数固定，**MVP 为 2**，该上限同时体现在 Agent Graph 的 `decide_retry` 分支条件里；
- 本地确定性校验先于 Reviewer；
- Reviewer 不可用时显示 NOT_RUN 或 DEGRADED；
- 不把 Reviewer 失败吞掉。

---

## 6.8 Suggested Questions

推荐问题（"猜你想问"）**全部来自服务端预置配置，不由模型生成**。参考实现同样把它做成 `composeAnswer()` 之后的独立节点 `suggestQuestions()`。

### 稳定接口

```python
def pick(
    mode: AnswerMode,
    category: QuestionCategory,
) -> SuggestedQuestions:
    ...
```

### 输出

```text
current      # 当前返回的一组
alternates   # 同业务域的其余候选组，供前端"换一换"本地轮换
```

### 规则

- 配置按业务域分组，每域至少两组候选，每组三条；
- `CHAT` 模式返回入门问题组，用于让新用户了解助手能做什么；
- 其余模式返回对应业务域的追问组；
- **推荐的问题必须落在指标与维度白名单之内**，配置变更时由测试校验，避免用户点击后撞 `INVALID`；
- 不发额外请求：候选组随聊天响应一次性返回；
- 配置为纯数据，改推荐问题不需要改代码或发前端版本。

### 必测

- 每个业务域都有配置，无缺省域；
- 所有预置问题都能通过 Intent 白名单校验；
- `CHAT` 模式返回入门组而非追问组；
- `alternates` 不包含与 `current` 重复的组。

---

## 7. 数据库计划

## 7.1 第一批表

### Identity [P0]

```text
merchants
```

MVP 没有 user 表，见 §6.1。

### Conversation [P0]

```text
conversations
messages
answers
feedback
```

`answers` 必须包含 `client_request_id`，并在 `(merchant_id, client_request_id)` 上建唯一约束——B2 的幂等验收依赖它。

### Export [P0]

```text
export_files
```

CSV 导出属于 P0，因此这张表不能和 P1 的附件表放在同一批迁移里。

### Operations [P0]

```text
audit_logs
llm_usage
```

`audit_logs` 记录越权访问和管理员操作；`llm_usage` 累计调用次数与 token，供每日预算熔断使用。两者都是 P0 安全与费用要求的落点。

### Knowledge [P0 / P1]

```text
metric_definitions      # P0，含 metric_code 与 display_name
knowledge_documents     # P0
merchant_memories       # P1
```

### Demo Analytics [P0]

```text
orders
order_items
refunds          # 退款：金额、退款原因、退款状态
returns          # 退货：件数、退货原因、物流状态
products
support_tickets
```

**退款与退货分表。** PRD 要求 MVP 覆盖"交易、退货、商品、客服工单"四个业务域，退货是独立业务域，不能用 `refunds` 代替：退款是资金动作，退货是货品动作，二者可以单独发生，也可以同时发生。

两张表都通过 `order_item_id` 关联订单项，都含非空 `merchant_id`：

| 表 | 关键字段 |
| --- | --- |
| `refunds` | `refund_amount`、`refund_reason`、`refund_status`、`refunded_at` |
| `returns` | `return_quantity`、`return_reason`、`return_status`、`logistics_status`、`returned_at` |

对应的指标、维度和明细见 §9 B4 的第一批指标表。

### Attachments [P1]

```text
attachments
```

## 7.2 数据类型规则

- 主键优先 UUID；
- 金额使用 `NUMERIC`；
- 时间使用 `TIMESTAMPTZ` 并存 UTC；
- **业务时区全局固定为 `Asia/Shanghai`**，由配置提供，不是 per-merchant 字段。"昨天""最近 N 天"和日报区间按该时区计算日界后转 UTC 查询；时钟可注入，以便测试跨零点边界；
- 模型结构化输出和灵活元数据使用 `JSONB`；
- 所有经营表包含非空 `merchant_id`；
- 所有表包含 `created_at`，可变表包含 `updated_at`；
- 软删除只在业务确有恢复需求时使用；
- 敏感字段明确分类，不默认返回。

## 7.3 索引

最低索引：

- `merchant_id + business_date`；
- `merchant_id + created_at`；
- 会话 ID + 消息时间；
- `answers` 的 `(merchant_id, client_request_id)` **唯一索引**（幂等）；
- `metric_definitions` 的 `metric_code` **唯一索引**；
- 知识域 + 状态；
- `llm_usage` 的 `(usage_date)`（每日预算聚合）；
- `audit_logs` 的 `(merchant_id, created_at)`；
- 附件 merchant + id。

先通过 `EXPLAIN` 和真实测试数据证明，再增加复杂索引。

## 7.4 迁移

迁移分组必须与交付阶段一致，**P0 的功能不得依赖 P1 的迁移**：

- 第一迁移（P0）创建商家、会话、知识和运维表（`audit_logs`、`llm_usage`）；
- 第二迁移（P0）创建演示经营表；
- 第三迁移（P0）创建 `export_files`；
- 第四迁移（P1）创建 `attachments` 和 `merchant_memories`；
- Seed 脚本不属于 Migration；
- Migration 不调用网络或 LLM；
- Migration 可以在空库重复验证；
- 不修改已发布 Migration，新增修复 Migration。

---

## 8. API Schema

> **本章是 ChatRequest / ChatResponse / ErrorResponse / SSE 的唯一权威定义。**
> `docs/PRD.md` §11.3 只描述产品级语义，`AGENTS.md` 只做索引，前端从本章生成的 OpenAPI 取类型。
> 任何字段变化必须先改本章，再改 Pydantic Schema、OpenAPI、`docs/api.md`、前端 Adapter 和契约测试。
> 全部字段使用 **snake_case 扁平结构**，不引入 `reviewer.*`、`metric.*` 之类的嵌套对象。

## 8.0 完整 API 路由表

路径以 `docs/PRD.md` §11 为准。**每一行都必须有对应的实现任务、权限校验和错误码测试**，不允许只写"列表、详情、上传"这类能力描述。

认证列的含义：

| 记号 | 方式 | 请求头 |
| --- | --- | --- |
| `M` | 商家演示 Token | `Authorization: Bearer <token>` |
| `A` | 管理员令牌 | **`X-Admin-Token: <token>`** |
| `S` | URL 自带签名 | 无请求头，签名在 query 参数中 |
| `—` | 无需认证 | — |

**管理员令牌走独立请求头 `X-Admin-Token`，不复用 `Authorization`。** 两者语义不同、生命周期不同、泄露后果也不同；共用一个头会让后端无法区分"商家在调管理接口"和"管理员在调商家接口"，前端也容易误把管理员令牌发给商家接口。后端对 `A` 类接口只认 `X-Admin-Token`，出现 `Authorization` 一律忽略。

| 阶段 | 方法 | 路径 | 认证 | 请求 | 响应 | 主要错误码 |
| --- | --- | --- | --- | --- | --- | --- |
| P0 | `POST` | `/api/chat` | M | `ChatRequest` | SSE 流或 `ChatResponse` | 401 403 409 422 429 503 |
| P0 | `GET` | `/api/conversations` | M | 分页查询参数 | `ConversationListResponse` | 401 |
| P0 | `GET` | `/api/conversations/{id}` | M | — | `ConversationDetailResponse` | 401 403 404 |
| P0 | `DELETE` | `/api/conversations/{id}` | M | — | `204` | 401 403 404 |
| P0 | `POST` | `/api/answers/{id}/feedback` | M | `FeedbackRequest` | `FeedbackResponse` | 401 403 404 422 |
| P0 | `GET` | `/api/exports/{id}` | **S** | 签名参数 | `text/csv` 字节流 | 403 404 410 |
| P0 | `GET` | `/api/metrics/{code}` | M | — | `MetricDefinitionResponse` | 401 404 |
| P0 | `GET` | `/api/demo/merchants` | — | — | `DemoMerchantListResponse` | 404（功能关闭时） |
| P0 | `GET` | `/api/health` | — | — | `HealthResponse` | — |
| P0 | `GET` | `/api/ready` | — | — | `ReadyResponse` | 503 |
| P0 | `GET` | `/api/admin/ops/status` | A | — | `OpsStatusResponse` | 401 403 |
| P1 | `GET` | `/api/reports/daily` | M | 日期参数 | `DailyReportResponse` | 401 422 |
| P1 | `POST` | `/api/attachments` | M | `multipart/form-data` | `AttachmentResponse` | 401 413 415 422 429 |
| P1 | `GET` | `/api/attachments/{id}` | M | — | `AttachmentResponse` | 401 403 404 |
| P1 | `DELETE` | `/api/attachments/{id}` | M | — | `204` | 401 403 404 409 |
| P1 | `GET` | `/api/memories` | M | 分页与业务域参数 | `MemoryListResponse` | 401 |
| P1 | `PATCH` | `/api/memories/{id}` | M | `MemoryCorrection` | `MemoryResponse` | 401 403 404 422 |
| P1 | `DELETE` | `/api/memories/{id}` | M | — | `204` | 401 403 404 |
| P1 | `GET` | `/api/admin/knowledge/tree` | A | — | `KnowledgeTreeResponse` | 401 403 |
| P1 | `GET` | `/api/admin/knowledge/documents/{id}` | A | — | `KnowledgeDocumentResponse` | 401 403 404 |
| P1 | `POST` | `/api/admin/knowledge/documents` | A | `KnowledgeDocumentCreate` | `KnowledgeDocumentResponse` | 401 403 422 |
| P1 | `PUT` | `/api/admin/knowledge/documents/{id}` | A | `KnowledgeDocumentUpdate` | `KnowledgeDocumentResponse` | 401 403 404 409 422 |
| P1 | `DELETE` | `/api/admin/knowledge/documents/{id}` | A | — | `204` | 401 403 404 |

说明：

- **没有** `GET /api/admin/knowledge/documents` 列表接口，目录由 `tree` 提供；
- `PUT` 知识文档使用乐观锁或 ETag，版本冲突返回 `409`；
- `/api/memories` 三条是商家自己的记忆，用商家 Token 而非管理员令牌——记忆归商家所有，管理员不应替商家改记忆。语义见 §9 B8「商家记忆闭环」；
- `/api/admin/ops/status` 见 §9 B7 的运维端点定义；
- 每条路由至少有一条"未认证"、一条"跨商家越权"用例，越权必须返回 `403` 并写 `audit_logs`。

### 导出下载为什么不带 Bearer

`/api/exports/{id}` 是路由表里**唯一** `S` 类接口。原因是浏览器的原生下载（`<a download>`、新标签页打开）**不会携带自定义请求头**，如果要求 `Authorization`，前端就只能 `fetch` 整个 CSV 到内存再拼 Blob——大导出会撑爆标签页内存，还失去断点续传和下载进度。

安全性由签名本身提供，不比 Bearer 弱：

- 签名是对 `export_id + merchant_id + 过期时间` 的 HMAC，密钥只在服务端；
- 有效期 **15 分钟**，过期返回 `410 EXPORT_LINK_EXPIRED`；
- 服务端校验签名后仍要核对该导出属于签名中的商家，**不信任 URL 里的任何身份信息**；
- 签名被篡改一律返回 `403`；
- 链接不进日志、不进 Referer（响应设 `Referrer-Policy: no-referrer`）。

前端因此可以直接用 `<a href="..." download>`，不需要 `fetch` + Blob，见 `docs/frontend-development-plan.md` F4。

## 8.1 ChatRequest

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `message` | `str` | 是 | 用户问题，长度上限由配置提供 |
| `session_id` | `str \| null` | 否 | 为空表示新建会话 |
| `attachment_ids` | `list[str]` | 否 | P1 附件，P0 恒为空数组 |
| `client_request_id` | `str` | 是 | 客户端生成的幂等键，见 §8.5 |

不允许普通用户通过正文决定可信商家 ID：请求体、查询参数和自定义请求头中的 `merchant_id` 一律忽略，身份只来自 Bearer Token。

## 8.2 ChatResponse

**始终必填**（键必须存在，值可为 `null`）：

| 字段 | 类型 | 可为 null | 说明 |
| --- | --- | --- | --- |
| `id` | `str` | 否 | 回答 ID，反馈接口用它 |
| `session_id` | `str` | 否 | 会话 ID。**不存在 `conversation_id`** |
| `answer` | `str` | 否 | 回答正文 |
| `answer_mode` | `AnswerMode` | 否 | 七种模式枚举 |
| `category` | `QuestionCategory \| null` | 是 | 业务分类枚举，见下方枚举表 |
| `thinking_steps` | `list[ThinkingStep]` | 否 | 与 SSE `step` 事件同构，可为空数组 |
| `quality_status` | `QualityStatus` | 否 | 见下方枚举 |
| `quality_attempts` | `int` | 否 | Reviewer 尝试次数，0–2 |
| `quality_notes` | `list[str]` | 否 | Reviewer 备注，**数组**，无备注时为空数组而非 `null`。语义说明也走这里，不新增 `semantic_notes` |
| `analysis_sources` | `list[AnalysisSource]` | 否 | **有序数组**，主要来源在前，至少一个元素 |
| `degraded` | `bool` | 否 | 是否降级 |
| `degraded_reason` | `str \| null` | 是 | 未降级时为 `null` |
| `suggestions` | `list[str]` | 否 | 当前一组预置推荐问题 |
| `suggestion_alternates` | `list[list[str]]` | 否 | 其余候选组，供"换一换"本地轮换 |
| `created_at` | `datetime` | 否 | UTC，ISO 8601 |

**枚举**：

```text
AnswerMode     = METRIC | DETAIL | RULE | IDENTITY | CHAT | INVALID | ATTACHMENT
QualityStatus  = PASSED | DEGRADED | FAILED | NOT_RUN
AnalysisSource = DATABASE | KNOWLEDGE | ATTACHMENT | MEMORY | FALLBACK | NONE
MetricStatus   = ACTIVE | DEPRECATED | UNVERIFIED
QuestionCategory = PLATFORM_RULE | TRADE | REFUND | CS_TICKET | COMPENSATION
                 | COUPON | GOODS | MERCHANT_OTHER | IDENTITY | SCM | UNKNOWN
```

`category` 取 `QuestionCategory` 枚举，**不是自由字符串**。业务域按 1:1 复刻参考实现
（`model/QuestionCategory.java`），少一个都会让 B3 的意图分类出现无法归类的问题。
枚举值是对外契约码，只能是英文；中文名由后端 `CATEGORY_DISPLAY_NAMES` 提供：

| 码 | 中文名 | 码 | 中文名 |
| --- | --- | --- | --- |
| `PLATFORM_RULE` | 平台商家规则 | `GOODS` | 商品管理 |
| `TRADE` | 电商交易 | `MERCHANT_OTHER` | 商家其他信息 |
| `REFUND` | 电商退货 | `IDENTITY` | 身份信息 |
| `CS_TICKET` | 电商客服工单 | `SCM` | 供应链 |
| `COMPENSATION` | 电商理赔/赔付 | `UNKNOWN` | 未知 |
| `COUPON` | 电商优惠券 | | |

B2 的 Fake Agent 只覆盖 `TRADE`、`REFUND`、`PLATFORM_RULE` 三类场景与 `UNKNOWN`
（寒暄与危险请求），其余分类由 B3/B4 接入真实意图识别与经营查询后填充。

`QualityStatus` **没有 `RETRIED`**。状态只表达最终质量结果，重试过程由 `quality_attempts` 表达：

| 实际发生 | `quality_status` | `quality_attempts` |
| --- | --- | --- |
| 一次通过 | `PASSED` | 1 |
| 重试后通过 | `PASSED` | 2 |
| 重试后仍失败 | `FAILED` | 2 |
| 校验后降级返回 | `DEGRADED` | 1 或 2 |
| 未执行校验 | `NOT_RUN` | 0 |

`analysis_sources` 是数组而非单值，因为组合场景是常态：查了数据并引用了口径返回 `["DATABASE", "KNOWLEDGE"]`，附件联合分析返回 `["ATTACHMENT", "DATABASE"]`。

**`NONE` 用于本来就没有分析来源的回答**：`CHAT` 的问候闲聊和 `INVALID` 的危险请求／无法处理，既没查库也没引知识，返回 `["NONE"]`。没有这个值时，"至少一个元素"的约束会逼着实现给普通聊天硬塞一个 `KNOWLEDGE` 或 `FALLBACK`，那是假的来源标注，直接违反 `AGENTS.md` R7。

约束：

- `NONE` 只能单独出现，不能与其他来源共存；
- `CHAT`、`INVALID` 必须是 `["NONE"]`；
- `NONE` **不代表降级**，此时 `degraded` 为 `false`——不要和 `FALLBACK` 混用；
- 含 `FALLBACK` 时 `degraded` 必须为 `true`。

**按模式必填**：

| 字段 | 类型 | 适用模式 |
| --- | --- | --- |
| `query_plan` | `QueryPlanSummary` | `METRIC`、`DETAIL`、`IDENTITY` |
| `metric_code` | `str` | `METRIC` |
| `metric_display_name` | `str` | `METRIC` |
| `metric_unit` | `str` | `METRIC` |
| `metric_definition` | `str` | `METRIC`，业务口径 |
| `metric_sql_definition` | `str` | `METRIC`，SQL 口径 |
| `metric_dimensions` | `list[str]` | `METRIC`，维度集合 |
| `metric_source_database` | `str` | `METRIC`，来源库名 |
| `metric_source_table` | `str` | `METRIC`，来源表名 |
| `metric_report_url` | `str \| None` | `METRIC` 可选，关联报表链接 |
| `metric_source` | `MetricDefinitionSource` | `METRIC`，口径来源枚举 |
| `metric_generated` | `bool` | `METRIC`，口径是否由模型生成 |
| `metric_notice` | `str \| None` | `metric_generated` 为 `true` 时必填 |
| `metric_owner` | `str` | `METRIC`，口径负责人 |
| `metric_status` | `MetricStatus` | `METRIC`，口径状态 |
| `data_rows` | `list[dict]` | `METRIC`、`DETAIL`、`IDENTITY` |
| `total_rows` | `int` | `METRIC`、`DETAIL`、`IDENTITY` |
| `truncated` | `bool` | `METRIC`、`DETAIL`、`IDENTITY` |
| `export` | `ExportInfo` | `DETAIL` |
| `visualization` | `Visualization` | `METRIC` 必填；`DETAIL`、`ATTACHMENT` 可选 |
| `recommendations` | `list[Recommendation]`（至少两条） | `METRIC`、`DETAIL`、`ATTACHMENT` |

`metric_source`、`metric_owner`、`metric_status` 是 PRD 要求指标口径面板展示的三项，缺一前端就只能显示空白，因此列为 `METRIC` 必填。

**`metric_definition`（业务口径）与 `metric_sql_definition` 必须并列存在，不得合并为单一文本字段。**
参考项目的指标平台元数据表把它们分列为 `metrics_biz_meaning` / `metrics_sql_meaning`，
面向读者不同（见 PRD §6.3）。为兼容已保存的 `answers.response_payload`，业务口径继续使用
`metric_definition`；升级器只为历史 JSONB 补齐安全默认值，前端没有第二个业务口径入口。

`metric_source` 是三取一的枚举 `METRIC_CATALOG` / `FIELD_COMMENT` / `AI_GENERATED`，
对应 PRD §10 Metric Catalog 的三级检索命中层级，**不是自由文本**：前端要据此渲染来源徽标，
自由文本会让徽标映射退化成字符串匹配。中文标签由前端负责，后端只给枚举。

`metric_generated` 是独立布尔，不要让前端从 `metric_status == UNVERIFIED` 反推——
「模型生成的口径」和「目录里登记为待核验的口径」是两件事，可以同时成立也可以各自单独成立。

Pydantic 模型**不得**把按模式必填的字段设为无条件必填，否则 `CHAT` 等模式的正常响应会校验失败。正确做法是模型级校验器：按 `answer_mode` 分支检查，`METRIC` 缺 `metric_owner` 必须报错，`CHAT` 缺 `data_rows` 必须放行。

R9 补充约束：纯明细模式的 `answer` **必须是空字符串**；其他模式必须是非空字符串。违反者由
`ChatResponse` 模型级校验拒绝，不能仅靠前端隐藏正文。`export` 除成功且未降级的 DETAIL 外，也允许
出现在结果被截断的受控临时 METRIC；下载服务须按存储的受控查询规格重放该指标查询。

### 会话详情助手载荷

`ConversationDetailResponse.messages` 的 ASSISTANT 消息增加可空 `answer_payload`。该脱敏载荷包含
`answer_id`、`answer_mode`、`thinking_steps`、`quality_status`、`quality_attempts`、`quality_notes`、
`degraded`、`degraded_reason`、`is_adopted`、`reaction`、表格列定义、`total_rows` 与 `truncated`。
`answer_id` 与两项反馈状态必须同时出现；用户消息及没有已保存回答的助手消息保持 `null`。
载荷明确不含 `data_rows`、`export` 或任何签名 URL。装配层从 `answers.response_payload` 读取后脱敏，
不把“前端不显示”当作数据保护。

为保证升级前幂等回答可重放，采用内部 `upgrade_payload()`：`_stored_response()` 在 Pydantic 校验前以
安全默认值补齐缺失字段。它必须有“旧 JSONB payload → 幂等重放 → 字段完整且不抛异常”的回归测试；
不做一次性 JSONB 全表迁移，避免大表迁移风险。

### 必测

- 一份 Schema 同时生成 Pydantic 与 TypeScript 类型，字段名零差异；
- `CHAT`、`INVALID`、`RULE` 无数据模式正常通过校验；
- `METRIC` 缺 `metric_source` / `metric_owner` / `metric_status` / `metric_definition` / `metric_generated` 校验失败；
- `metric_generated` 为 `true` 但缺 `metric_notice` 校验失败；
- `METRIC` 缺 `metric_sql_definition`、维度或来源库表时校验失败；
- `DETAIL` 缺 `export` 校验失败；
- `analysis_sources` 为空数组时校验失败；
- `CHAT`、`INVALID` 返回 `["NONE"]` 且 `degraded=false` 时校验通过；
- `NONE` 与其他来源共存时校验失败；
- 含 `FALLBACK` 但 `degraded=false` 时校验失败；
- `quality_attempts > 2` 时校验失败。

## 8.3 Error Response

统一字段：

```text
code
message
request_id
details
retryable
```

`details` 只返回可安全展示的字段错误，不返回 SQL、堆栈、密钥或数据库地址。

### 错误响应必须进入 OpenAPI

前端按 `code` 分支渲染错误（`docs/frontend-development-plan.md` §10），而前端类型只从
`docs/api.json` 生成。因此：

- `ErrorResponse` 与 `ErrorCode` **必须**出现在 `components.schemas` 里；
- 每条路由**必须**声明 §8.0 路由表列出的全部错误码，响应体一律 `$ref` 到 `ErrorResponse`；
- **必须显式声明 `422`**。FastAPI 会为带请求体或参数的路由自动注入它自己的
  `HTTPValidationError`（`{"detail": [...]}`），而我们的全局处理器返回的是
  `ErrorResponse`——不覆盖就等于契约声明的结构与实际返回的不一致；
- 导出产物里**不得**残留 `HTTPValidationError` / `ValidationError` 引用。

实现上用 `app.core.errors.error_responses(*status_codes)` 统一生成声明，
由 `backend/tests/api/test_openapi_chat_contract.py` 的哨兵测试逐条把关。

## 8.4 Chat SSE 契约

`POST /api/chat` 默认以 SSE 流式响应，让用户 1 秒内看到真实处理阶段，而不是等 10 秒以上才拿到全部结果。

### 事件类型

| 事件 | 载荷 | 时机 |
| --- | --- | --- |
| `step` | `{ label, node }` | 每个 Agent 节点完成时推送一条 |
| `done` | 完整 ChatResponse（见 §8.2） | 流程成功结束 |
| `error` | 标准 Error Response（见 §8.3） | 流程失败终止 |

### 线协议

响应头：

```text
Content-Type: text/event-stream; charset=utf-8
Cache-Control: no-cache
Connection: keep-alive
X-Accel-Buffering: no
```

**事件类型只放在 SSE 的 `event:` 字段，不在 `data` JSON 里重复一个 `type` 键。** 前端解析器读 `event:` 并转换成 TypeScript union，两处都写会出现不一致：

```text
event: step
data: {"label":"正在识别问题","node":"classify_intent"}

event: step
data: {"label":"正在查询经营数据","node":"run_query"}

event: done
data: {"id":"a1b2","session_id":"s9","answer":"...","answer_mode":"METRIC", ...}

```

- 每个事件以空行结束，`data` 是单行紧凑 JSON，不跨行；
- 每 15 秒发送一次注释心跳 `: keep-alive`，防止代理按空闲超时断连；
- 服务端不做分块对齐承诺，客户端必须按字节流累积解析，不得假设一次读取对应一个完整事件。

### 规则

- 流的最后一个事件必须是 `done` 或 `error` 之一，不允许静默结束，两者互斥；
- `done` 的载荷与非流式响应**完全一致**，前端只有一处解析逻辑；
- 请求头 `Accept: application/json` 时返回普通 JSON 响应，不走流。API 测试和契约测试使用这条路径，避免为流式解析写一套测试基础设施；
- `step` 只承载可安全展示的阶段描述，不含 Prompt 全文、SQL 或数据行；
- **错误的 HTTP 语义按响应头是否已发送区分**：
  - 响应头发送前失败（认证失败、限流、参数错误）→ 返回对应 HTTP 状态码和普通 JSON `ErrorResponse`，不进入流；
  - 响应头发送后失败 → HTTP 状态码已是 `200`，只能通过 `event: error` 传递错误，客户端据此渲染；
- **客户端断开时取消 Agent**：检测到断开后停止后续 LLM 调用（这直接关系费用），但已完成的回答仍然完整落库，不产生半条记录，后续可凭 `client_request_id` 取回。

## 8.5 `client_request_id` 幂等契约

`answers` 表在 `(merchant_id, client_request_id)` 上有唯一约束，并保存请求内容摘要（`request_digest`，对 `message` 与 `attachment_ids` 取哈希）和处理状态：

```text
PROCESSING        # 正在处理
SUCCEEDED         # 已产出完整回答
FAILED_RETRYABLE  # 可用同一 ID 重试（超时、上游 5xx、流中断、限流、预算耗尽）
FAILED_FINAL      # 不可重试（参数非法、越权、内容被拒）
```

**预算耗尽和限流属于 `FAILED_RETRYABLE`，不是 `FAILED_FINAL`。** 每日预算按业务时区跨日重置，限流窗口以分钟计，两者都是**暂时性**资源约束：把它们归为终态会导致预算恢复后同一 `client_request_id` 永远返回旧错误，用户只能换个问题重问，而这恰恰会绕开幂等保护、产生本可避免的重复计费。

判定标准是"**同样的请求过一会儿有没有可能成功**"：

| 失败原因 | 归类 | 理由 |
| --- | --- | --- |
| LLM 超时、上游 5xx、流中断 | `FAILED_RETRYABLE` | 瞬时故障 |
| `RATE_LIMITED` | `FAILED_RETRYABLE` | 限流窗口滑动后可通过 |
| `LLM_BUDGET_EXCEEDED` | `FAILED_RETRYABLE` | **次日预算重置后可通过** |
| 参数非法（422） | `FAILED_FINAL` | 请求本身错误，重试无意义 |
| 越权（403） | `FAILED_FINAL` | 权限不会自己变 |
| `INVALID` 模式的危险请求 | 不进本状态机 | 它是正常 `200` 回答，落 `SUCCEEDED` |

重复提交同一 `client_request_id` 的处理规则：

| 已有状态 | 摘要一致 | 行为 |
| --- | --- | --- |
| 任意 | **否** | `409 IDEMPOTENCY_KEY_REUSED`，拒绝"同一 ID、不同内容" |
| `PROCESSING` | 是 | `409 REQUEST_IN_PROGRESS`，`retryable=true`，提示稍后重取，**不重复调用 LLM** |
| `SUCCEEDED` | 是 | `200` 返回原回答（流式则直接推 `done`），**不重复计费** |
| `FAILED_RETRYABLE` | 是 | 允许重新执行，复用同一行并置回 `PROCESSING`。**重试前重新检查限流与预算**，仍不满足则再次返回对应错误码，不进入 Agent |
| `FAILED_FINAL` | 是 | 返回原错误，不重新执行 |

必测：预算耗尽 → 同一 ID 重试仍返回 `LLM_BUDGET_EXCEEDED` 且**不调用 LLM** → 模拟跨日重置 → 同一 ID 重试成功产出回答。

前端的 ID 生成与复用规则见 `docs/frontend-development-plan.md` §6.1，两边必须一致：网络重试复用原 ID，用户改问题或主动重新生成则换新 ID。

### 必测

- 事件顺序：至少一个 `step`，以 `done` 结尾；
- 失败路径以 `error` 结尾且不含 `done`；
- `Accept: application/json` 返回非流式响应，且载荷与 `done` 逐字段一致；
- **真实字节流解析**：把响应按随机边界切块（含切断 UTF-8 多字节字符和切断事件中间），解析结果仍然正确；
- 心跳注释不被当作业务事件；
- 认证失败在流开始前返回 `401` 而非 `200` + `error` 事件；
- 客户端提前断开：Agent 被取消，不再产生新的 LLM 调用，且不产生半条回答记录；
- 同一 `client_request_id` 的五种状态分支各一条用例；
- 同一 `client_request_id` 并发提交两次，只产生一次 LLM 调用；
- 降级场景下仍然正常收尾。

---

## 9. 开发阶段

**执行顺序即编号顺序，MVP 在 B7 收口，不要为了做 P1 功能而推迟部署。**

| 阶段 | 内容 | 归属 |
| --- | --- | --- |
| B0 | 工程骨架 | P0 |
| B1 | PostgreSQL、迁移与身份上下文 | P0 |
| B2 | Chat API 与 Fake Agent | P0 |
| B3 | 指标、知识与结构化意图 | P0 |
| B4 | 安全经营数据查询 | P0 |
| B5 | 回答、图表和 Reviewer | P0 |
| B6 | 反馈与 CSV 导出 | P0 |
| **B7** | **Railway、费用防护与 MVP 收口** | **P0 · MVP 完成** |
| B8 | 附件、日报、商家记忆、对象存储和异步任务 | P1 |
| B9 | 知识库后台 | P1 |

对应 PRD 的里程碑：B0 → M0，B1–B2 → M1，B1/B4 → M2，B3/B5 → M3，B7 → M4，B8–B9 → M5。

**商家隔离必须早于经营查询。** B1 建立 Merchant Context 与隔离 Repository 并跑通反例测试，B4 才实现第一条经营查询。顺序颠倒会导致 Repository 和 Service 返工。

## B0 · 工程骨架

### 任务

- [ ] 创建 `backend/pyproject.toml`；
- [ ] 使用 `uv` 锁定依赖；
- [ ] 创建 FastAPI App Factory；
- [ ] 创建配置、日志和错误模块；
- [ ] 创建 `/api/health`；
- [ ] 配置 CORS；
- [ ] 创建 Dockerfile；
- [ ] 创建 pytest、Ruff 和类型检查配置；
- [ ] 增加 `.env.example`；
- [ ] 关闭未配置的管理接口，而不是使用默认弱令牌。

### 健康检查

`GET /api/health`：

- 不调用 LLM；
- 不执行重型数据库查询；
- 返回应用版本和基本状态；
- 如需要数据库 readiness，使用单独 `/api/ready`。

### 验收

```powershell
uv sync
uv run ruff check .
uv run pytest
uv run fastapi dev app/main.py
```

均成功，Docker 中可以监听 Railway `PORT`。

---

## B1 · PostgreSQL、迁移与身份上下文

### 任务

- [ ] SQLAlchemy Async Engine 和 Session；
- [ ] Alembic 配置；
- [ ] 创建商家、会话、知识和运维基础表（含 `audit_logs`、`llm_usage`）；
- [ ] 创建 Merchant Context（仅 merchant，无 user）；
- [ ] 实现演示 Token 白名单解析与认证 Dependency；
- [ ] 实现 `GET /api/demo/merchants`，可通过配置关闭，生产环境禁用；
- [ ] 实现越权访问返回 `403` 并写审计日志；
- [ ] 创建 Repository Protocol；
- [ ] 实现基本 Conversation Repository；
- [ ] Seed 三个演示商家及其 Token 映射；
- [ ] 增加启动连接重试；
- [ ] 设置连接池与 statement timeout。

### 验收

- Migration 可在空 PostgreSQL 执行；
- 三个商家的数据隔离测试通过；
- 请求正文伪造商家 ID 无效；
- 缺失或非法 Token 返回 `401`；
- 访问其他商家资源返回 `403` 且产生审计记录；
- 演示商家端点在关闭配置下返回 404 或 403；
- 数据库异常转换为安全错误；
- Session 在请求结束后正确关闭。

---

## B2 · Chat API 与 Fake Agent

### 任务

- [ ] 定义 ChatRequest 和 ChatResponse（按 §8.2 的两组字段划分必填性）；
- [ ] 创建 Conversation、Message、Answer ORM，含 `client_request_id` 唯一约束；
- [ ] 创建 `POST /api/chat`，实现 SSE 流式与 `Accept: application/json` 双路径（见 §8.4）；
- [ ] 创建会话列表、详情和 `DELETE /api/conversations/{id}`；
- [ ] 创建 Fake Agent，逐节点推送 `step` 事件；
- [ ] 实现预置推荐问题配置与 Suggested Questions 模块（见 §6.8）；
- [ ] 支持 Prototype 的预置场景；
- [ ] 保存用户消息和助手回答；
- [ ] 支持 session_id；
- [ ] 返回 thinking steps、口径、数据、图表、建议和推荐问题；
- [ ] Mock/Fake 结果带 `analysis_sources=["FALLBACK"]` 或明确演示标记。

### 验收

- 前端无需真实 LLM 即可完成整套 UI；
- SSE 事件顺序正确，以 `done` 或 `error` 收尾；
- `Accept: application/json` 的载荷与 `done` 事件一致；
- 连续追问保持会话；
- 删除会话后列表和详情均不可见，且不影响其他商家；
- 同一 `client_request_id` 不重复创建回答；
- API Schema 可以生成前端类型；
- 自动化测试不访问网络。

### Fake Agent 的退役

B3 引入 Fake LLM 之后，**Fake Agent 即退役**，不保留两条并行的假实现路径。B3 起所有 Agent 测试都走真实 Graph + Fake LLM，避免出现"Fake Agent 测试通过但真实链路未覆盖"。

---

## B3 · 指标、知识与结构化意图

### 任务

- [x] 创建 `AnswerMode`（P0 六种，`ATTACHMENT` 在 B8 扩展为第七种）、业务分类和 Query Intent；
- [x] 创建指标定义表和 Seed，含 `metric_code` 与 `display_name`；
- [x] **建立指标、维度、筛选三套白名单**（本阶段完成，不留到 B4）；
- [x] 创建知识文档表和旧 Wiki 导入脚本；
- [x] 实现 Metric Catalog；
- [x] 实现 Knowledge Retrieval 的两层检索（索引层 + 正文层，见 §6.5）；
- [x] 定义 LLM Client Protocol；
- [x] 实现 Fake LLM，并退役 B2 的 Fake Agent；
- [x] 实现 DeepSeek LLM Adapter，但测试不启用：使用 OpenAI 兼容 Chat Completions API，`base_url=https://api.deepseek.com`，默认 `model=deepseek-v4-flash`；
- [x] 实现单请求 LLM 调用次数与 token 上限；
- [x] 实现两阶段意图：分类 → 结构化理解；
- [x] 结构化输出用 Pydantic 严格校验；
- [x] 实现非法输出、超时和有限重试；
- [x] 建立 LangGraph State 和基础节点。

### 验收

- 指标、明细、规则、身份、聊天和无效请求六类问题正确路由；
- 模型输出 SQL 字符串会被拒绝；
- 模型输出中文指标名而非 `metric_code` 时被拒绝；
- 非白名单指标和维度不能进入查询；
- 索引层检索不加载正文，正文层只加载命中业务域；
- 知识回答包含来源；
- 未命中知识明确返回未命中；
- 单请求超出 LLM 调用次数或 token 上限时显式降级；
- Fake LLM 覆盖正常、非法 JSON、超时和空响应。

### 实现说明（2026-08-04）

- 三套不可变白名单位于 `app/intent/whitelist.py`；B4 必须在 SQL 模板层再次校验，不能把 B3 校验作为唯一防线。
- 查询日期范围由后端截断为最多 180 天；参考实现的 365 天范围未沿用，以降低单次分析的成本和超时风险。
- 日期校验顺序固定为**起止方向 → 未来截断 → 180 天截断**：起止颠倒和整段落在未来的区间一律拒绝（属模型输出错误，替它猜方向会把错误结果当成正常回答），结束日在未来则截断到今天并留可见备注。`today` 由调用方注入，便于冻结时钟测试跨零点行为。
- 指标口径三级检索在 `retrieve_knowledge_detail` 之后执行：第三级要用知识**正文**生成候选口径，索引层只有目录词汇。生成口径的待核验文案必须进入 `quality_notes`。
- DeepSeek 适配器把「单请求剩余 token」作为 `max_tokens` 随请求发出，并在预算耗尽时于本地拦截、不发起请求；只做事后记账挡不住已经产生费用的那一次调用。
- `MerchantQaGraph` 使用 LangGraph 的 13 节点骨架。B4/B5 未实现的节点仍产生可见步骤，所有尚未查询数据的 METRIC、DETAIL、IDENTITY 回答均以 `FALLBACK` 和明确降级原因返回。
- `FakeAgent` 已退役；测试仅使用 `FakeLlmClient` 或 HTTP Mock。首次真实 DeepSeek 调用尚未发生，仍需用户明确同意模型、调用次数和费用。

---

### B3 与 B4 共享字段契约（2026-08-04）

B3 的三个意图白名单已经与 B4 第一批受控查询契约对齐，不能再使用参考项目的
`*_1d` 指标或 `*_detail` 表名：

- 指标：`gmv`、`order_count`、`paying_user_count`、`successful_order_count`、`refund_count`、`refund_amount`、`return_count`、`return_rate`、`support_ticket_count`；
- 维度和可筛选字段：`date`、`product`、`category`、`order_status`、`refund_reason`、`return_reason`、`return_status`、`ticket_status`；
- 表路由：交易使用 `orders` + `order_items`，退款/退货使用独立的 `refunds` + `returns`，客服使用 `support_tickets`，商品使用 `products`。所有 B4 经营表均由后端强制注入 `merchant_id`，不得使用 `seller_id`。

规则回答命中知识正文时必须在正文中列出文档路径，并返回 `analysis_sources=["KNOWLEDGE"]`；未命中时必须明确说明未命中。若 LLM 未配置、不可用或单请求预算耗尽，任何回答模式都必须保留可见的 `degraded=true`、`degraded_reason` 和 `FALLBACK` 来源；仅未降级的 `CHAT` 与 `INVALID` 使用 `["NONE"]`。

**预置推荐问题同样受这套契约约束（§6.8 必测）。** `app/services/suggested_questions.py` 的每条问题都标注了期望的回答路径（`DATA` / `KNOWLEDGE` / `IDENTITY`）：`DATA` 问题必须声明白名单内的指标、维度或明细表，`KNOWLEDGE` 与 `IDENTITY` 问题不得声明查询字段，由测试逐条校验。由此产生一处产品取舍：**理赔、优惠券、商家其他和供应链四个业务域在 B4 第一批经营表里没有数据，因此只推荐知识型问题**；原型入口问题里的「我想查看保证金」和「查看优惠券明细」按同一理由替换，避免用户点击后撞 `INVALID`。这四个域补齐经营表后，可把对应问题改回数据型。

## B4 · 安全经营数据查询

### 任务

- [x] 创建订单、订单项、**退款、退货**、商品和工单表；
- [x] 创建 **180 天**演示数据 Seed（含退款与退货两类记录，且存在"只退款不退货""退货并退款"两种样本）；
- [x] 实现 `GET /api/metrics/{code}` 指标口径接口，返回 `metric_source`、`metric_owner`、`metric_status`；
  - [ ] **未完成（2026-08-09 按 AGENTS.md R9 登记）**：该端点只返回 `business_definition`，
        `sql_definition`（库里已有值）、维度、来源库表、关联报表、`generated` / `notice`
        都没有出口，参考项目 `MetricDefinitionPayload` 的 13 个字段我们只兑现了 7 个。
        补齐范围见 §8.2 字段表；三级检索缺第二级（字段注释）见 PRD §10 Metric Catalog。
- [x] 实现 Analytics Repository；
- [x] 实现 Safe Query Service；
- [x] 将 B3 建立的三套白名单接入查询路由；
- [x] 实现日期解析和最大范围（180 天，业务时区 `Asia/Shanghai`）；
- [x] 实现指标聚合；
- [x] 实现明细路由；
- [x] 实现总数、预览、截断和排序；
- [x] 实现查询计划摘要；
- [x] 添加 statement timeout；
- [x] 添加 Decimal 和日期序列化。

### 第一批指标

至少以下 `metric_code`，每个都要配中文 `display_name` 和单位：

```text
gmv
order_count
paying_user_count
successful_order_count
refund_count
refund_amount
return_count
return_rate
support_ticket_count
```

`return_count` 取自 `returns`，`refund_count` / `refund_amount` 取自 `refunds`，**两者不得互相替代**。`return_rate` = 退货件数 ÷ 同期订单项件数，属于比例指标，不可跨日期求和。

### 第一批维度

至少：

```text
date
product
category
order_status
refund_reason
return_reason
return_status
ticket_status
```

### 第一批明细

```text
订单明细      orders + order_items
退款明细      refunds
退货明细      returns
商品明细      products
工单明细      support_tickets
```

### 验收

- 用户输入不能改变表名或列名；
- 所有查询强制商家过滤；
- 最大日期（180 天）和行数（200 行）限制生效；
- 跨零点的"昨天"按 `Asia/Shanghai` 归属，冻结时钟测试通过；
- 平均值和比例不被错误求和，`return_rate` 按区间重新计算而非按日均值；
- **"最近 30 天退货量趋势"能返回退货数据，且与退款金额不混淆**；
- **退货明细可查询、跨商家退货记录不可见**（导出：`ExportSpec` 已由 Task 7 产出，
  **导出端点本身落在 B6**，B4 的 `ExportInfo` 仍是占位 id/url，不要当成 B4 已交付导出）；
- 多商家同日期数据不会串用；
- SQL 注入测试通过；
- 查询结果包含稳定列顺序和安全中文标签元数据。

### 实现说明（2026-08-05，B4 收口）

**指标口径表**（`app/analytics/contract.py` 的 `METRIC_SPECS`，与迁移
20260804_0006 的指标 SQL 口径迁移写入 `metric_definitions.sql_definition`
的文案逐字一致）。

下表的「SQL 口径」列就是 `metric_definitions.sql_definition` 的内容，对应契约字段
SQL 口径对应 §8.2 的并列口径字段；业务口径是另一列 `business_definition`，两者并列存在，见 §8.2。
**这张表在 B4 收口时还没有出口到
API**——`sql_definition` 只落库未进 `MetricDefinitionResponse`，属于已登记的契约缺口，
补齐范围见 §8.2 的字段表。

| `metric_code` | 中文名 | 单位 | 主表 | SQL 口径 | 可加和 |
| --- | --- | --- | --- | --- | --- |
| `gmv` | 成交 GMV | 元 | `orders` | `SUM(orders.paid_amount)`，限 `order_status IN ('PAID','SHIPPED','COMPLETED')` | 是 |
| `order_count` | 订单量 | 单 | `orders` | `COUNT(orders.id)`，不限状态 | 是 |
| `paying_user_count` | 付款用户数 | 人 | `orders` | `COUNT(DISTINCT orders.buyer_key)`，限 `paid_at IS NOT NULL` | **否**（去重计数） |
| `successful_order_count` | 成功订单量 | 单 | `orders` | `COUNT(orders.id)`，限 `order_status = 'COMPLETED'` | 是 |
| `refund_count` | 退款量 | 单 | `refunds` | `COUNT(refunds.id)`，限 `refund_status IN ('APPROVED','REFUNDED')` | 是 |
| `refund_amount` | 退款金额 | 元 | `refunds` | `SUM(refunds.refund_amount)`，限 `refund_status = 'REFUNDED'` | 是 |
| `return_count` | 退货量 | 件 | `returns` | `SUM(returns.return_quantity)` | 是 |
| `return_rate` | 退货率 | % | `order_items` | 退货件数 ÷ 同期订单项件数（按区间重算，见下） | **否**（比例） |
| `support_ticket_count` | 客服工单量 | 单 | `support_tickets` | `COUNT(support_tickets.id)` | 是 |

`refund_count`/`refund_amount` 取自 `refunds`（资金动作），`return_count` 取自
`returns`（货品动作），两者不得互相替代——这也是 Task 5/10 专门用真实
PostgreSQL 钉住的一条（`test_return_count_reads_returns_not_refunds`）。

**`return_rate` 的归属选择**：退货件数按**订单项所属的下单日**（`order_items.business_date`）
归属，而不是按退货实际发生日。原因是分母固定为「同期下的订单项件数」，如果分子按退货发生日
归属，一笔跨期退货会让分子落在退货当天、分母却落在下单当天，区间对不上会算出无意义的比例。
为避免同一个订单项有多条退货记录时把分母重复计入，实现（`AnalyticsRepository._aggregate_ratio`）
先把 `returns` 按 `order_item_id` 聚合成子查询，再 `LEFT JOIN` 回 `order_items`，而不是直接
`JOIN order_items` 到 `returns` 逐行相乘。`return_rate` 标记为**不可加和**：按区间整体重算一次，
不是把每天的比例算出来再求平均或求和（B5 的答案组装依赖这个标记，见 `non_additive` 字段）。

**`business_date` 为什么是物理列而不是查询期 `AT TIME ZONE` 表达式**：六张经营表都在写入
（目前只有 Seed 一处写入路径）时把 UTC 时间戳按 `Asia/Shanghai` 换算成业务日、落成一个真实的
`date` 列，而不是在每次查询时对 `created_at`/`placed_at` 做时区转换。原因有两条：一是所有查询
都要按 `merchant_id + business_date` 过滤和分组，物理列上能建复合索引，表达式索引在 PostgreSQL
里既拿不到同等的范围扫描收益，又要求每条 SQL 都重复一次时区换算逻辑；二是业务时区目前是
写死的应用配置（不按商家可变），换算规则只有一处产生分歧的可能（Seed），不存在多处写入导致
物理列与实时计算结果漂移的风险。冻结时钟对「跨零点的昨天」的校验因此只需要覆盖
`app/analytics/dates.py` 的日期解析，不需要在每条查询上重复验证时区语义。

**维度表不按业务日过滤**（`DetailSpec.date_filtered`，B5/B6 会依赖这条语义决定）：
六张经营表都有 `business_date`，但语义不同。事件表（`orders`/`refunds`/`returns`/
`support_tickets`）的 `business_date` 是**事件发生日**，明细查询按查询区间过滤它是对的；
`products.business_date` 是**上架日**，商品上架后一直存在，套用同一条时间窗规则会让
「看看我的商品明细」只返回默认 7 天窗口里恰好上架的那一两个商品（演示数据把 24 个商品
铺在 180 天里），其余被静默丢掉且没有任何提示。修复为在契约层给 `DetailSpec` 增加
`date_filtered`（默认 `True`，`products` 为 `False`），由 `AnalyticsRepository.detail()`
尊重它；该路径下 `plan_steps` 写「不限时间范围」而不是一个假的时间范围承诺，`notes` 也
换成「不按日期筛选，返回该商家的全部记录」。标记放在契约层而不是服务层特判某张表：
这是「这张表的时间语义是什么」的声明，和列名、标签一样属于表本身的性质。**新增明细表时
先想清楚它是事件表还是维度表**，默认值是更保守的按业务日过滤。

**遗留给 B6 的一处不一致（`ExportSpec` 与预览的时间范围）**：`date_filtered=False` 的
明细（当前只有 `products`）预览时忽略查询区间，但 `SafeQueryService` 交给下游的
`ExportSpec` 仍然带着 `start`/`end`。B4 内无副作用——导出端点尚不存在、`ExportInfo`
是占位——但 **B6 实现导出时若直接采信 `ExportSpec.start`/`end`，导出的 CSV 会和用户刚
看到的预览不一致**（预览是全量商品，CSV 只有 7 天内上架的）。B6 动手前必须先决定：
让 `ExportSpec` 也尊重 `date_filtered`（推荐，保持预览与导出同源），还是显式声明导出
永远按区间。这是 B4 终审后定向复审发现的，记录在此以免 B6 重新踩一遍。

**期间发现并按人工裁定纠正的四处偏离**（原计划字面没有覆盖，均已由集成测试钉住回归）：

1. **按 `product`/`category` 拆分时的 join 放大**（Task 5）：`orders` join 到 `order_items`/`products`
   会把订单行按订单项展开，直接对展开后的行 `SUM(orders.paid_amount)` 或 `COUNT(orders.id)`
   会把同一张跨类目订单的金额/订单数重复计入每个类目。修复为：这条路径下金额类指标改为
   `SUM(order_items.item_amount)`（按订单项分摊，而不是复述整单金额），计数类指标改为
   `COUNT(DISTINCT orders.id)`。不需要该维度的默认路径未受影响。见
   `tests/integration/repositories/test_analytics_repository.py` 的
   `test_gmv_by_category_sums_back_to_the_order_amount` 等用例。
2. **完全落在未来的日期区间改为显式拒绝，不是静默截断**（Task 4）：原计划的截断逻辑会把
   「结束日超过今天」截到今天，但对「起始日也在未来」的区间同样截断会静默地用「今天」的数据
   回答一个问未来的问题。改为：起始日期晚于业务今天时抛 `FutureRangeError`，服务层转成
   `UnsupportedQueryError`，与 B3 `validate_intent` 对同型输入的处理保持一致。
3. **指标口径端点必须能返回已废弃指标**（Task 8）：`GET /api/metrics/{code}` 最初复用了
   `MetricRepository.get_by_code`（聊天路径用来把已废弃指标排除出查询范围的同一个方法），
   导致 `status=DEPRECATED` 的指标查口径时和拼写错误一样 404，文档承诺的「口径面板可查已废弃
   指标」实际不可达。修复为新增一个不过滤状态的独立仓储方法给口径端点专用，`get_by_code`
   本身（及它在聊天路径的排除语义）保持不变。
4. **REFUND 分类的明细按信号分流到 `returns` 或 `refunds`**（Task 9 收口）：`DETAIL_BY_CATEGORY`
   把 `REFUND` 静态指向 `refunds`，而 PRD 里退款（资金动作）与退货（货品动作）是两件可以
   分开发生的事——B3 的分类粒度只到 `REFUND` 这一级，于是 `returns` 表的明细永远查不到。
   修复为在 `SafeQueryService._resolve_refund_table` 里做二次路由，信号按可靠性从高到低取，
   命中即返回、**不叠加判断**：
   1. 维度/筛选字段落在哪张表就查哪张（用户已明确说了按什么筛选，最强信号，直接复用
      `DIMENSION_SPECS`，不引入新词表）；
   2. 分类阶段产出的 `intent_keywords` 命中「退货 / 退回」或「退款」（词表是契约的一部分，
      见 `contract.REFUND_CATEGORY_*_KEYWORDS`，不下放到服务层）；
   3. 两种信号都没有时维持既有兜底（查 `refunds`），不去猜——猜错会让商家把退款明细当成
      退货明细看，比「查不到」更危险。
   `DETAIL_BY_CATEGORY[REFUND]` 保持 `refunds` 作为兜底值不变。见
   `tests/integration/services/test_safe_query.py` 的 `test_refund_category_with_*` 系列。

这四处均记在 `.superpowers/sdd/2026-08-04-backend-b4-safe-analytics-query/progress.md`
的逐 Task 账本里；B5/B6 若要触碰同一批聚合表达式或口径端点，先读那份账本，避免把已经
裁定过的偏离当成待发现的新缺陷重新讨论一遍。

**终审修复轮（2026-08-05）另外确定的三条约束**：

1. **响应不得自相矛盾**：查到数据时 `ChatResponse.answer` 必须如实说查询已经执行过。
   此前 `answer` 无条件输出「经营数据查询将在 B4 接入」，和同一条响应里的
   `analysis_sources=["DATABASE"]`、真实 `data_rows` 直接打架，用户会连旁边的真数字
   一起不信（AGENTS.md R7）。自洽性不变量因此作用在**整个响应**上而不是单个字段：
   `tests/unit/agent/test_graph_query_data.py::_assert_no_denial` 同时扫 `answer`、
   `recommendations`、`quality_notes`、`degraded_reason`——字段作用域的不变量挡不住
   相邻字段，这正是上一轮只改 `recommendations` 却让缺陷溜过 Task 级评审的原因。
   B5 接入真正的回答正文时，替换的是这条如实文案，不是重新引入前向引用。
   **没有查询结果的降级分支保持「尚未执行」的措辞**——那条路径上它说的是真话。
2. **仓储与图之间必须有异常边界**：`SafeQueryService` 的两处仓储调用都包了
   `except SQLAlchemyError → UnsupportedQueryError`。不收口的话任何数据库异常
   （含本阶段专门加的 statement timeout）都会一路上抛到 `ChatService._abort` →
   全局处理器 → 500，合法意图的用户拿到服务端错误而不是可见降级。拒绝原因是固定
   文案，不带异常原文、表名、列名和驱动名。
3. **筛选字段的「值」也要校验**：B3 白名单只校验筛选字段的**键**。`date` 落到 `date`
   类型的列上，模型抽出的「昨天」这类中文时间表达传到 PostgreSQL 就是
   `invalid input syntax for type date`。值校验放在 `SafeQueryService` 而不是扩
   `FILTER_WHITELIST`——白名单成员是 B3 的契约（有测试钉住它与 `DIMENSION_WHITELIST`
   相等）。同理 `intent.limit` 的下界在服务层夹紧（`min(max(limit, 1), MAX_DETAIL_LIMIT)`），
   与 B3 `validate_intent` 对上界「覆盖成合法值而不是判整条意图非法」的处理方式一致。

---

## B5 · 回答、图表和 Reviewer

### 任务

- [x] 实现 Answer Composition；
- [x] 创建回答 Prompt；
- [x] 创建 Visualization Service；
- [x] 创建 Recommendation Schema；
- [x] 实现本地确定性校验；
- [x] 实现独立 Reviewer；
- [x] 固定最大尝试次数 `MAX_REVIEW_ATTEMPTS=2`；
- [x] 实现 `PASSED` / `DEGRADED` / `FAILED` / `NOT_RUN` **四种最终状态**（无 `RETRIED`，重试次数由 `quality_attempts` 表达，见 §8.2）；
- [x] 保存 `quality_attempts` 和 `quality_notes`；
- [x] 按实际使用的来源填充 `analysis_sources` 有序数组；
- [x] 实现非加和指标保护；
- [x] 确保规则回答不创建假图表。

推荐问题不在本阶段生成——它是 B2 已完成的预置配置模块（§6.8）在 Graph 中的独立节点。

### 本地校验至少包括

- 回答提到的关键数字是否存在于 Query Result；
- 图表字段是否存在；
- 建议数量是否满足要求；
- 建议是否包含 evidence 和 action；
- 无数据时是否编造数字；
- 非加和指标是否被求和；
- 商家敏感字段是否出现在回答。

**「非加和指标是否被求和」与「敏感字段」的落地方式**（`app/services/answer_service.py`
`AnswerService._validate`）：`QueryResult.non_additive=True` 且返回多行时，草稿文本命中
「合计/总计/累计/总和/加总/汇总」任一字样即拒绝——单纯引用某一行的原始数值不受影响，
拦的是把多行摊平成一个新结论。`non_additive` 同时写进喂给模型和 Reviewer 的事实包
（`facts_json` 的 `non_additive` 字段），两条 Prompt 都要求据此避免/否决求和式表达，
本地校验是最后一道机械防线，不依赖模型自觉。敏感字段方面，受控查询契约
（`DETAIL_SPECS`）本身不含任何 PII 列，真正的泄露面是模型可能在回答里提到不属于
展示字段的内部标识符（`merchant_id`、`answer_id` 等 UUID）——校验器用 UUID 形状的
正则拦这一类，命中即判定为幻觉走降级路径。

### 验收

- 有数据回答至少两条建议；
- 图表字段完全来自查询结果；
- Reviewer 不重写回答；
- 最多执行 2 次尝试，达到上限后不再重试；
- 重试后通过返回 `PASSED` + `quality_attempts=2`，重试后失败返回 `FAILED` + `quality_attempts=2`；
- Reviewer 不可用时返回显式 `DEGRADED`；
- 回答记录保存最终候选和质量摘要。

---

## B6 · 反馈与 CSV 导出

本阶段属于 P0。日报是 P1，已移至 B7。

### Feedback

- [x] `POST /api/answers/{id}/feedback`；
- [x] 采纳、点赞和点踩；
- [x] 点赞点踩互斥；
- [x] 幂等更新；
- [x] 只能反馈本商家回答。

### CSV

- [x] Export Service；
- [x] 实现 `GET /api/exports/{id}` 下载接口；
- [x] UTF-8 BOM；
- [x] 中文列名；
- [x] CSV 公式注入防护；
- [x] 权限校验；
- [x] **P0 动态生成，不引入 S3 SDK**；对象存储和签名对象 URL 属于 P1；
- [x] 导出记录写入 `export_files`；
- [x] **签名 URL 自带鉴权**：`GET /api/exports/{id}` 不要求 `Authorization`，校验 HMAC 签名 + 商家归属即可，浏览器可原生下载（理由见 §8.0）；
- [x] 签名有效期 **15 分钟**，过期返回 `410 EXPORT_LINK_EXPIRED`；
- [x] 响应设 `Referrer-Policy: no-referrer`，签名链接不进日志（应用层不打印请求 URL；
      生产环境 access log 的脱敏留给 B7 部署配置）。

### 验收

- 不能下载其他商家的导出；
- 以 `= + - @` 开头的文本不会触发电子表格公式；
- 导出链接超过 15 分钟失效；
- 篡改签名的链接被拒绝；
- 反馈重复提交结果稳定。

**复审发现并修复的一处偏离（BOM 重复）**：`ExportService._to_csv` 已经在字符串开头拼了
一次 BOM（`﻿`），路由层最初又用 `content.encode("utf-8-sig")` 编码——这个编码本身
会自动加一次 BOM，叠加已有字符后实际下载字节是两段 BOM（`EF BB BF EF BB BF...`）。
`tests/api/test_exports.py::test_download_returns_a_single_bom_prefixed_csv_with_safe_headers`
钉住只允许一段。修复为路由层改用 `content.encode("utf-8")`，BOM 只在 `_to_csv` 里拼一次；
新增该测试前这条回归完全不会被发现——单元测试只测了 `ExportService` 自己返回的字符串，
从未测过 HTTP 路由实际吐出的字节。

---

## B7 · Railway、费用防护与 MVP 收口

**本阶段属于 P0，是 MVP 的最后一步。执行顺序是 B0 → B7，不要先做 B8/B9 的 P1 功能再部署。**

PRD 的里程碑是 M0–M4 完成 MVP 并上线，M5 才是 P1。把 Railway 排在附件和知识库之后，会让部署、迁移和费用风险暴露得过晚。

> **更新（2026-08-06，Task 1-18 收口）**：费用防护/限流/可信 IP 补齐了必测，Docker 优雅关闭、
> `OperationalMetrics` 可观测性、`GET /api/admin/ops/status` 运维端点、`railway.json` 与
> `docs/deployment.md` 均已实现并提交（`feature/b5-b6-answer-feedback-export` 分支）。
> `REQUIRE_INTEGRATION_DB=1 pytest` 在真实 PostgreSQL 上 **703 passed、0 skipped、0 failed**
> （首次跑通时发现并修复一个真实 bug：`tests/postgres.py::TRUNCATE_ALL_TABLES` 漏了
> `llm_daily_budget`，导致同一天内所有集成测试共用一行预算，跑到后段用例就把默认
> 20\_000 token 预算耗尽而误报 503——已修复，见提交 `64e60e3`）。`ruff`/`ruff format`/`mypy`
> （88 源文件）全绿。**Railway 一节仍未勾选**：本轮按计划约束只产出 `railway.json` 和
> `docs/deployment.md`，没有实际创建 Railway 项目/连接 PostgreSQL/填写环境变量，也没有做
> 「验收（MVP 出口）」清单里依赖真实部署的项目（重启后数据仍在、健康检查、SSE 真实 CORS 环境
> 等）——这些需要用户在 Railway 控制台执行后才能勾。可观测性一节里的「查询耗时」（SQL 语句本身
> 的执行耗时，区别于已实现的 Agent 节点整体耗时）尚未单独实现，也保持未勾。

### Docker

- [x] 从官方 Python 基础镜像构建；
- [x] 使用非 root 用户；
- [x] 安装依赖利用缓存；
- [x] Exec form CMD；
- [x] 监听 `0.0.0.0:$PORT`；
- [x] 不把 `.env`、测试数据或密钥复制进镜像；
- [x] 优雅关闭：收到 SIGTERM 后停止接收新请求，允许在途 SSE 流收尾（`app/run.py::GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS = 30`）；
- [x] 设置合理 worker 数量，避免超出内存（刻意保持单 worker，决策记录见 `app/run.py` 注释与 `docs/deployment.md`）。

### Railway

**网络拓扑：Backend 公开 + 严格 CORS**（前端不做反向代理，见 `docs/frontend-development-plan.md` §8.3）。

- [ ] Backend Service Root `/backend`；
- [ ] PostgreSQL Service；
- [ ] Backend 引用 `DATABASE_URL`；
- [ ] 健康检查；
- [ ] 数据库连接重试；
- [ ] Migration 发布步骤；
- [ ] CORS 只允许 Frontend 的**精确 Origin**，不使用 `*`；允许头包含 `Authorization`、`Accept`、`Content-Type`、`X-Request-Id`；限制方法与预检缓存时长；
- [ ] 配置日志；
- [ ] 生产环境关闭 Debug；
- [ ] 确认容器临时磁盘不保存正式附件。

### 可信来源 IP

限流按 Token 和来源 IP 计数，但 Railway 位于反向代理之后，**不能直接采信客户端自带的转发头**，否则攻击者随手伪造 `X-Forwarded-For` 就绕过限流。

- [x] 只信任 Railway 代理注入的转发头，通过可信代理跳数配置解析，不接受任意客户端提供的 `X-Forwarded-For`、`Forwarded`、`X-Real-IP`（`app/core/client_ip.py::resolve_client_ip`）；
- [x] ASGI Server 显式配置 proxy headers 与 `forwarded-allow-ips`，不使用通配（`app/run.py` 显式传 `proxy_headers=False`，改由应用层按可信跳数自行解析，不依赖 uvicorn 的隐式信任）；
- [x] 多级代理时取**最右侧可信跳数之外的第一个地址**，规则写在 `app/core/client_ip.py` 与 `docs/deployment.md`；
- [x] 本地开发和测试环境回退到直连 socket 地址（`trusted_proxy_hops=0` 默认值）；
- [x] 必测：伪造 `X-Forwarded-For` 不能重置限流计数（`tests/api/test_rate_limit_trust_boundary.py`，真实库回归已过）。

### LLM 费用与限流

**这一步不能省。** MVP 的部署形态是：公开的 Railway 地址 + 免鉴权的 `/api/demo/merchants` 端点 + 环境变量里的真实 LLM key。任何人扫到这个地址就能取到演示 Token 并无限调用聊天接口，费用是真金白银。

- [x] 单请求上限：最大 LLM 调用次数与最大输入/输出 token（B3 已实现，此处纳入部署校验）；
- [x] 用量累计写入按日聚合调用次数与 token 的表（实为 `llm_daily_budget` + 明细表 `llm_usage`，非计划早期文案里的单一 `llm_usage` 聚合）；
- [x] **每日预算熔断，扣减必须原子**：`LlmBudgetRepository.reserve` 用单语句条件 `UPDATE ... WHERE usage_date = :d AND consumed_tokens + :tokens <= :budget RETURNING consumed_tokens`，不先 `SELECT` 再判断；
- [x] 预扣后回填：`LlmCostGuard` 按预估 token 先 `reserve`，调用结束后用实际 token `reconcile` 差额；请求失败也记录已消耗部分（`tests/unit/llm/test_guard.py`）；
- [x] 超预算后全局停止调用 LLM，转显式降级回答，复用已有降级路径；
- [x] 基础限流：按 Token 和可信来源 IP 限制频次，命中返回 `RATE_LIMITED`；
- [x] MVP 无 Redis，限流使用进程内计数器，`docs/deployment.md` 已说明多实例下为近似限制。

必测：

- [x] 10 个并发请求逼近预算边界时，放行数量不超过预算，无超发（`tests/integration/repositories/test_llm_budget_repository.py`，真实 PostgreSQL 回归已过）；
- [x] 预估 token 与实际 token 有差异时，日累计值最终收敛到实际值（`tests/unit/llm/test_guard.py::test_complete_reconciles_estimate_to_actual_tokens_and_records_success`）；
- [x] 请求失败后已消耗的 token 仍被计费记录（`tests/unit/llm/test_guard.py::test_complete_still_bills_estimate_when_inner_call_fails`）；
- [x] 多进程实例下预算不会各算各的：由 PostgreSQL 的原子条件更新保证（预算本身不超发），限流命中数/可观测性计数仍是进程内近似值，`docs/deployment.md` 已写明该限制。

### 运维端点

熔断和限流状态必须可观察，但不能裸奔。

- [x] `GET /api/admin/ops/status`，**需要 `X-Admin-Token` 请求头**（值为 `ADMIN_TOKEN`），未配置管理员令牌时端点整体关闭（不挂载路由，404）；`Authorization` 头一律忽略；
- [x] 返回：当日 token 用量与预算剩余、限流命中计数、降级计数、各错误码计数、Agent 节点平均耗时；
- [x] **禁止返回**：任何 Token 明文、Prompt 内容、商家经营数据、完整请求正文、数据库连接串（`tests/api/test_admin_ops.py` 断言响应体不含管理员/商家 Token 与 `postgresql` 字样）；
- [x] 商家标识以脱敏形式返回（哈希或序号），不返回商家名称：响应本身是系统级聚合，不含任何商家维度字段，天然满足；
- [x] 必测：无管理员令牌返回 `401`，普通商家 Token 返回 `403`，响应体不含敏感字段（`tests/api/test_admin_ops.py`，真实库回归已过）。

### 可观测性

- [x] request ID（`main.py::request_id_middleware`，响应头回写 `X-Request-Id`）；
- [x] 结构化日志（`request_completed` 事件：request_id/method/route/status_code/duration_ms）；
- [x] 路由耗时（同上，`OperationalMetrics.record_route_duration`）；
- [x] Agent 节点耗时（`MerchantQaGraph._timed_node` 包装每个图节点，计入 `OperationalMetrics`）；
- [ ] 查询耗时：SQL 查询本身的独立耗时尚未单独记录（目前只随 `query_data` 节点的整体 Agent 节点耗时被间接计入，没有单独的日志字段或指标）；
- [x] LLM 调用次数、token 用量和状态：通过 `GET /api/admin/ops/status` 可查（`llm_calls_today`/`llm_tokens_used_today`），未做成逐次调用的结构化日志行；
- [x] 每日预算剩余量（`llm_tokens_remaining_today`，同上）；
- [x] 降级计数与限流命中计数（`OperationalMetrics.degraded_count`/`rate_limit_hits`）；
- [x] 不记录 Prompt 全文和敏感数据（结构化日志只含 request_id/method/route/status_code/duration_ms，未接触请求体或 Prompt）。

### 验收（MVP 出口）

- Railway 重启后数据仍在；
- 健康检查稳定；
- Migration 只执行一次；
- 应用服务早于数据库启动时可以重试；
- 超过每日预算后不再调用 LLM，且返回显式降级而非报错；
- 超过频次限制返回 `RATE_LIMITED`；
- 伪造转发头无法绕过限流；
- 运维端点需要管理员令牌且不泄露敏感数据；
- 演示商家端点在生产配置下不可访问；
- 日志可以定位请求但不泄露隐私；
- 前端可以通过部署域名完成核心 E2E，SSE 在真实 CORS 环境下正常流式；
- **`docs/PRD.md` §16 全部验收条目通过。到此后端 MVP 完成。**

---

## B8 · 附件、日报、商家记忆、对象存储和异步任务

**本阶段属于 P1，在 MVP 上线之后执行。**

### Daily Report

- [ ] `GET /api/reports/daily`；
- [ ] 昨日核心指标；
- [ ] 摘要；
- [ ] 至少两条建议；
- [ ] **日报建议复用回答反馈通道**：日报响应返回可反馈的 `answer_id`，前端"采纳"直接调用 `POST /api/answers/{id}/feedback`，不新增反馈接口；
- [ ] 无数据日报；
- [ ] 昨日区间按业务时区 `Asia/Shanghai` 计算；
- [ ] 定时 Worker。

### Attachment API

- [ ] 上传；
- [ ] 状态查询；
- [ ] 删除；
- [ ] 所有权校验；
- [ ] 数量、类型和大小限制；
- [ ] 文件签名检查；
- [ ] 安全文件名；
- [ ] SHA-256；
- [ ] 对象存储；
- [ ] TTL 和删除策略。

附件解析状态枚举（前端状态机依赖它，必须先稳定）：

```text
UPLOADING → PENDING → PARSING → PARSED
                            └─→ FAILED
```

### Extraction

- [ ] PDF 文本；
- [ ] Excel 工作表摘要；
- [ ] CSV 编码和分隔符；
- [ ] 最大行列限制；
- [ ] 附件正文不可信标记；
- [ ] 解析失败原因；
- [ ] 不把完整大文件塞进 Prompt。

### OCR Adapter

方案在实现前必须确定，不能只写"图片 OCR Adapter"：

- [ ] **默认使用本地 OCR**（如 PaddleOCR 或 Tesseract），不默认调用收费的多模态模型；
- [ ] 输入限制：单图最大边长、最大像素、最大文件大小、PDF 最大页数；
- [ ] 单次 OCR 超时与总超时；
- [ ] 定义 `OcrAdapter` Protocol，测试注入 `FakeOcrAdapter`，CI 不跑真实 OCR；
- [ ] 识别结果中的手机号、身份证、银行卡等按脱敏规则处理后才可进入日志；
- [ ] **如果改用收费模型 OCR，必须遵守 `AGENTS.md` R3**：先说明模型、次数和预计费用并获得同意，且纳入 §9 B7 的每日预算熔断统计。

### `ATTACHMENT` 模式进入 Agent Graph

B3 建立的是六种 `AnswerMode`，本阶段扩展为七种。仅在 ChatResponse 里加枚举值不够，Graph 必须有对应路径：

- [ ] 新增节点：`load_attachments` → `validate_attachment_ownership` → `wait_or_reject_unparsed_attachment` → `extract_attachment_context` → `route_attachment_query`；
- [ ] 所有权校验失败返回 `403` 并写 `audit_logs`，**跨商家附件 ID 必须测**；
- [ ] 解析未完成时的行为：短暂等待后仍未完成则返回明确的"附件仍在解析"回答，不阻塞整个请求；解析失败返回 `FAILED` 原因，不静默忽略；
- [ ] 附件与经营数据联合分析时，`analysis_sources` 返回 `["ATTACHMENT", "DATABASE"]`；
- [ ] 附件正文以不可信数据块注入 Prompt，明确标注不得改变系统规则；
- [ ] 必测：附件中的"忽略以上所有指令"不改变 Agent 行为；跨商家附件 ID 返回 403；未解析完成不产生编造结论。

### 商家记忆闭环

当前只有 `merchant_memories` 表和"检索时可读取"，不足以实现。P1 需要完整链路：

| 环节 | 要求 |
| --- | --- |
| Memory Extraction | 从**已成功回答的会话**中提取，不从原始用户输入直接提取；有独立 Prompt 和 Pydantic Schema |
| Memory Validation | 提取结果必须通过结构校验和白名单检查；**不得把未审核的模型输出升级为团队知识** |
| Memory Persistence | 写入时机为一轮问答成功落库之后的异步任务；带幂等键，重试不产生重复记忆 |
| Memory Retrieval | 检索优先级：团队知识 > 商家记忆；命中记忆时 `analysis_sources` 含 `MEMORY` |
| Memory Deletion | 见下方 API；**删除会话时同时删除由该会话产生的记忆** |

记忆必须对商家可见可控，否则它就是个不可审查的黑盒。三条正式接口（已进 §8.0 路由表，用商家 Token）：

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `GET` | `/api/memories` | 列出本商家记忆，支持按业务域筛选与分页；返回内容、来源会话 ID、生成时间、状态 |
| `PATCH` | `/api/memories/{id}` | **纠错**：修正内容或置为 `INVALIDATED`，请求体 `MemoryCorrection` |
| `DELETE` | `/api/memories/{id}` | 删除单条记忆 |

- [ ] 记忆状态：`ACTIVE`、`INVALIDATED`（商家标记失效，保留痕迹但不再召回）；
- [ ] `PATCH` 修正后的内容**不再经过模型改写**，直接作为事实存储，并标记为商家确认；
- [ ] 商家确认过的记忆在检索时优先级高于模型自动提取的记忆；
- [ ] 三条接口全部强制 `merchant_id` 过滤，跨商家记忆 ID 返回 `403` 并写 `audit_logs`；
- [ ] 删除和失效都要立刻影响后续召回，不依赖缓存过期。

- [ ] 压缩与去重：同一事实重复出现时合并，不无限增长；
- [ ] 过期策略：超过保留期的记忆自动失效（清理策略本身属于 P2）；
- [ ] 提取失败时静默降级，不影响主回答链路；
- [ ] 必测：记忆提取、召回、列表、纠错、删除各一条；**跨商家记忆 ID 返回 403**；会话删除后记忆不再被召回；标记 `INVALIDATED` 后不再进入 Prompt。

### Worker 独立工程

`AGENTS.md` 规划了独立 `worker/`，实现前必须先定这几项：

- [ ] **队列框架**：Redis + RQ（简单、与 FastAPI 同步代码兼容好）；不引入 Celery 的完整生态；
- [ ] **共享代码方式**：`backend/app` 中与业务无关的模型、Schema 和配置抽为可安装包，`worker/pyproject.toml` 依赖它；不允许两边各拷一份 ORM 定义；
- [ ] **版本兼容规则**：Worker 与 Backend 同版本发布；任务载荷只传 ID 和幂等键，不传序列化的 ORM 对象，避免跨版本反序列化失败；
- [ ] **任务 Schema**：`task_type`、`payload`、`idempotency_key`、`attempt`、`max_attempts`；
- [ ] **重试与死信**：指数退避，超过 `max_attempts` 进入死信表并记录最后错误；
- [ ] **Railway 启动命令**与健康检查方式；
- [ ] Worker **不执行数据库 Migration**；
- [ ] 幂等键格式：`{task_type}:{merchant_id}:{business_id}`。

### 验收

- 非法文件被拒绝；
- 扩展名与实际类型不一致被拒绝或隔离；
- 其他商家不能读取附件；
- 附件中的"忽略系统提示"不会改变 Agent 规则；
- 大文件不会导致 API 进程内存失控；
- Worker 重试不会重复创建导出或记忆；
- 无数据时返回正常日报而非 500；
- 日报返回的 `answer_id` 可以正常提交反馈；
- 昨日区间按 `Asia/Shanghai` 计算，冻结时钟测试通过；
- `ATTACHMENT` 模式端到端可用，跨商家附件 ID 返回 403；
- 商家记忆可提取、可召回、可删除，且跨商家隔离。

---

## B9 · 知识库后台

### 任务

- [ ] 管理员认证；
- [ ] 知识目录；
- [ ] 文档读取；
- [ ] 创建、更新和删除；
- [ ] 乐观锁或 ETag；
- [ ] 版本历史；
- [ ] Markdown 内容限制；
- [ ] 路径或文档 ID 安全；
- [ ] 团队知识和商家记忆隔离；
- [ ] 知识检索索引更新；
- [ ] 未配置管理员令牌时 403。

### 验收

- 非管理员只能读取允许内容；
- 并发覆盖返回 409；
- 删除需要正确版本；
- 不存在路径穿越；
- 商家记忆不能通过知识后台改成团队事实；
- 旧 Wiki 导入脚本可以 dry-run。

---


## 10. Agent Graph 计划

建议状态节点顺序：

```text
START
  → load_context                  # 商家上下文（Token 解析结果）+ 会话历史
  → retrieve_knowledge_index      # 第一层：只加载目录与摘要，业务域未知
  → classify_intent
  → understand_intent
  → validate_intent
  → retrieve_knowledge_detail     # 第二层：业务域已知，加载对应正文
  → query_data
  → compose_answer
  → local_validate
  → review_answer
  → decide_retry                  # attempt < MAX_REVIEW_ATTEMPTS(=2) 才可重试
      ├── retry → compose_answer
      └── finish
  → suggest_questions             # 从预置配置取，不调用 LLM
  → persist_answer
  → END
```

三点说明：

- **知识检索拆成两个节点。** 索引层必须在 `classify_intent` 之前——业务域未知时，索引给模型提供拆词和领域识别所需的词汇；正文层必须在意图确定之后，否则会把全部知识灌进 Prompt。参考实现的顺序与此一致，见 §6.5。
- **`decide_retry` 的上限写进分支条件**，不只写在文字说明里，避免实现时漏掉而形成无限循环。
- **`suggest_questions` 是独立节点且不调用 LLM**，位置与参考实现的 `suggestQuestions()` 一致，见 §6.8。

每个节点完成时向 SSE 推送一个 `step` 事件（见 §8.4）。

### AgentState 最低字段

```text
request_id
merchant_context
session_context
question
attachments
knowledge_index          # 第一层检索结果：目录与摘要
knowledge_sources        # 第二层检索结果：命中业务域的正文
metric_definition
intent
query_result
candidate_answer
visualization
recommendations
suggestions              # 预置配置取得的当前组
suggestion_alternates    # 预置配置取得的其余候选组
quality_status
quality_issues
attempt
degraded
degraded_reason
llm_calls                # 本次请求已消耗的调用次数，用于单请求上限
llm_tokens               # 本次请求已消耗的 token
```

AgentState 使用 TypedDict、Pydantic 或 LangGraph 支持的明确类型，不使用随意扩展的匿名字典。

---

## 11. 测试计划

## 11.1 Unit

必须覆盖：

- [ ] Config 缺少必需密钥；
- [ ] Merchant Context；
- [ ] Intent Schema；
- [ ] 日期解析；
- [ ] 指标和维度白名单；
- [ ] Safe Query Builder；
- [ ] Metric Catalog 优先级；
- [ ] Knowledge Retrieval 隔离；
- [ ] Answer Composition；
- [ ] 非加和指标；
- [ ] Visualization 字段安全；
- [ ] Reviewer 重试；
- [ ] CSV 注入防护；
- [ ] Attachment 类型和大小。

## 11.2 API

- [ ] Chat 正常（`Accept: application/json` 非流式路径）；
- [ ] Chat SSE 事件顺序与收尾；
- [ ] **SSE 真实字节流解析**：按随机边界切块，含切断多字节 UTF-8 字符与切断事件中间，解析结果仍正确；
- [ ] Chat 422；
- [ ] 401 和 403；
- [ ] 越权产生审计记录；
- [ ] 会话隔离；
- [ ] 删除会话；
- [ ] 反馈幂等；
- [ ] `client_request_id` 五种状态分支（§8.5）与并发重复提交；
- [ ] 导出权限与链接过期；
- [ ] 演示商家端点开关；
- [ ] 限流命中 `RATE_LIMITED`；
- [ ] **伪造 `X-Forwarded-For` 不能重置限流计数**；
- [ ] 运维端点鉴权与脱敏；
- [ ] 附件权限；
- [ ] 知识版本冲突；
- [ ] Health；
- [ ] 全局安全错误格式；
- [ ] **OpenAPI 契约快照测试**：Schema 变化必须显式更新快照，防止无声破坏前端类型；
- [ ] **§8.0 路由表逐行覆盖**：每条路由至少一条未认证用例和一条跨商家越权用例。

## 11.3 Integration

**集成测试必须连真实 PostgreSQL，不得用 SQLite 替代。** 本项目依赖 `JSONB`、`NUMERIC`、`TIMESTAMPTZ`、部分索引和条件更新语义，SQLite 会让测试通过但线上失败。CI 用 Docker 起 PostgreSQL 服务。

### CI 必须禁止静默跳过

测试库不可达时会自动 `skip`，这对本地开发是便利，**对 CI 是隐患**：商家隔离、迁移和 Seed 的验收全在集成测试里，postgres 服务起不来时套件照样全绿，安全地基一次没验就放行了。

因此 **CI 必须设 `REQUIRE_INTEGRATION_DB=1`**，此时库不可达会硬失败而不是跳过：

```powershell
# 本地：库没起就跳过，不打断开发
uv run pytest

# CI：库必须真的连上
$env:REQUIRE_INTEGRATION_DB = "1"; uv run pytest
```

本地起测试库：

```powershell
docker-compose -p borough up -d postgres
```

测试库地址默认 `127.0.0.1:55432`（与 compose 一致），可用 `TEST_DATABASE_URL` 覆盖。库名不含 `test` 时 `assert_test_database` 会直接拒绝，防止误连真实库后被 `TRUNCATE`。

- [ ] PostgreSQL Migration（空库与已有数据两种起点）；
- [ ] Repository；
- [ ] 多商家真实查询；
- [ ] **退货域查询**：退货趋势、退货明细、退货与退款不混淆；
- [ ] 事务回滚；
- [ ] statement timeout；
- [ ] **每日预算原子扣减**：10 个并发请求逼近预算边界时无超发；
- [ ] Seed；
- [ ] 对象存储 Fake 或本地兼容实现。

## 11.4 Agent

使用 Fake LLM 覆盖：

- [ ] METRIC；
- [ ] DETAIL；
- [ ] RULE；
- [ ] IDENTITY；
- [ ] CHAT；
- [ ] INVALID；
- [ ] 非法 JSON；
- [ ] 非白名单字段；
- [ ] 中文指标名而非 `metric_code`；
- [ ] 空数据；
- [ ] Reviewer 一次通过（`PASSED` / attempts=1）；
- [ ] Reviewer 重试后通过（`PASSED` / attempts=2）；
- [ ] Reviewer 重试后失败（`FAILED` / attempts=2）；
- [ ] Reviewer 降级（`DEGRADED`）；
- [ ] Reviewer 未执行（`NOT_RUN` / attempts=0）；
- [ ] 达到 `MAX_REVIEW_ATTEMPTS` 后不再重试；
- [ ] 每日预算熔断后的降级；
- [ ] `ATTACHMENT` 模式路由（P1）；
- [ ] 商家记忆提取、召回、删除与跨商家隔离（P1）；
- [ ] 附件提示词注入。

## 11.5 回归问题集

`tests/regression/questions.yaml` 维护 40–60 条固定问题，纳入版本管理，每条标注期望回答模式和期望业务域（含退货域）。

它测的是**确定性路由回归**，不是真实模型准确率。Fake LLM 为每条问题返回预置意图，因此它只能证明夹具正确、Agent 路由无回归、Pydantic 契约可解析：

| 指标 | 执行 | 阈值 |
| --- | --- | --- |
| 确定性路由回归通过率 | Fake LLM，进 CI | **100%**，任何一条不通过即阻断 |
| 真实模型意图准确率 | 真实模型离线跑同一问题集 | ≥ 90%，**人工验收项，不进 CI** |

- 使用 Fake LLM 执行，不产生费用；
- 真实模型评估执行前遵守 `AGENTS.md` R3，在 B7 阶段执行一次并记入验收记录；
- 新增或调整回答模式、业务域时同步维护；
- 断言失败时输出逐条对比，便于定位是哪类问题退化。

---

## 12. Seed 数据计划

`scripts/seed_demo_data.py` 应支持：

```text
--dry-run
--seed
--merchant-count
--days
--random-seed
```

要求：

- 固定随机种子可以重现；
- 默认 3 个商家；
- 默认最近 **180 天**，与 `MAX_QUERY_DAYS` 对齐；
- 每个商家数据分布不同；
- 包含明显趋势和异常，便于验证建议；
- 不包含真实个人信息；
- 可以重复执行而不无限重复；
- 不调用 LLM；
- 不直接写生产数据库，除非显式环境保护和确认。

---

## 13. 环境变量

`.env.example` 至少列出：

```text
APP_ENV=development
APP_VERSION=0.1.0
DATABASE_URL=<postgresql-url>
FRONTEND_ORIGIN=http://localhost:5173
LLM_API_KEY=<deepseek-api-key>
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-v4-flash
LLM_ENABLED=false
BUSINESS_TIMEZONE=Asia/Shanghai
DEMO_MERCHANT_TOKENS=<token:merchant_id,token:merchant_id,token:merchant_id>
DEMO_MERCHANTS_ENDPOINT_ENABLED=true
DEMO_DEPLOYMENT_MODE=false             # 仅对外演示部署时显式开启
ADMIN_TOKEN=<development-placeholder>   # P0 起必需（运维端点），P1 知识库后台复用；请求头 X-Admin-Token
EXPORT_URL_TTL_MINUTES=15
MAX_QUERY_DAYS=180
MAX_DETAIL_ROWS=200
MAX_REVIEW_ATTEMPTS=2
MAX_LLM_CALLS_PER_REQUEST=6
MAX_LLM_TOKENS_PER_REQUEST=<int>
LLM_DAILY_BUDGET_TOKENS=<int>
RATE_LIMIT_PER_MINUTE=<int>
TRUSTED_PROXY_HOPS=1
MAX_ATTACHMENTS=8
MAX_ATTACHMENT_MB=15
OCR_ENABLED=false
OCR_PROVIDER=local
OBJECT_STORAGE_ENDPOINT=<optional>
OBJECT_STORAGE_BUCKET=<optional>
REDIS_URL=<optional>
```

`JWT_SECRET` 已移除——MVP 不做 JWT 登录，商家身份来自演示 Token 白名单（见 §6.1）。

`LLM_API_KEY` 的值是 DeepSeek API Key。真实 Adapter 使用 DeepSeek 的 OpenAI 兼容
Chat Completions API；`LLM_BASE_URL` 和 `LLM_MODEL` 采用上面的固定默认值。MVP 不使用
已弃用的 `deepseek-chat` 或 `deepseek-reasoner`，也不在此阶段引入双模型路由；如需升级为
`deepseek-v4-pro`，必须先完成真实模型离线验收与 R3 费用确认。

生产环境默认关闭演示商家端点：`DEMO_MERCHANTS_ENDPOINT_ENABLED` 在生产环境不具备开启效果；仅当 `DEMO_DEPLOYMENT_MODE=true` 时才会显式开放，且不降低其余生产安全校验。

生产环境对弱占位值必须拒绝启动。

---

## 14. 后端错误码

建议稳定错误码：

```text
AUTH_REQUIRED
FORBIDDEN
MERCHANT_SCOPE_VIOLATION
NOT_FOUND
METHOD_NOT_ALLOWED
INVALID_REQUEST
INVALID_INTENT
UNSUPPORTED_METRIC
UNSUPPORTED_DIMENSION
QUERY_RANGE_TOO_LARGE
QUERY_TIMEOUT
DATA_SOURCE_UNAVAILABLE
LLM_UNAVAILABLE
KNOWLEDGE_NOT_FOUND
ATTACHMENT_TOO_LARGE
ATTACHMENT_TYPE_UNSUPPORTED
ATTACHMENT_PARSE_FAILED
VERSION_CONFLICT
RATE_LIMITED
LLM_BUDGET_EXCEEDED
IDEMPOTENCY_KEY_REUSED
REQUEST_IN_PROGRESS
EXPORT_LINK_EXPIRED
HTTP_ERROR
INTERNAL_ERROR
```

**本表是后端错误码的唯一登记处。** 代码侧的唯一出处是 `app.core.errors.ErrorCode` 枚举，两者由
`tests/unit/core/test_error_codes.py` 强制对齐：枚举里出现未登记的码，CI 直接失败。新增错误码时
先加枚举成员、再补本表，最后检查 `docs/frontend-development-plan.md` §10 是否需要展示规则。

几个通用码的语义边界：

| 码 | HTTP | 用途 |
| --- | --- | --- |
| `NOT_FOUND` | 404 | 商家范围内资源不存在，或路由不存在。**与 `KNOWLEDGE_NOT_FOUND` 不同**，后者是知识检索未命中，属于正常业务回答而非错误 |
| `FORBIDDEN` | 403 | 权限不足但不涉及跨商家。跨商家越权用 `MERCHANT_SCOPE_VIOLATION`，因为它是安全事件、要写 `audit_logs` |
| `METHOD_NOT_ALLOWED` | 405 | 路径存在但方法不对 |
| `HTTP_ERROR` | 其他 4xx | 未单独映射的 HTTP 异常兜底，前端按通用错误展示 |
| `INTERNAL_ERROR` | 500 | 未捕获异常兜底，响应体不含任何内部细节 |

幂等相关的三个错误码见 §8.5，`EXPORT_LINK_EXPIRED` 对应 `GET /api/exports/{id}` 的 `410`。

`RATE_LIMITED` 和 `LLM_BUDGET_EXCEEDED` 在 **B7** 落地，见该阶段的「LLM 费用与限流」。

前端根据错误码展示，不解析后端内部异常字符串。

---

## 15. 后端禁止事项

- 不允许 LLM 直接执行 SQL；
- 不允许用户输入成为表名或列名；
- 不允许从 ChatRequest 信任商家 ID，**也不允许照搬旧实现的 `merchantId` 前端透传**；
- 不允许模型生成推荐问题；
- 不允许在没有预算熔断和限流的情况下把真实 LLM key 部署到公开地址；
- 不允许 Repository 调用 LLM；
- 不允许 API Route 写复杂业务逻辑；
- 不允许真实 LLM 进入默认测试；
- 不允许无限 Reviewer 循环；
- 不允许把 Fake 结果标记为数据库结果；
- 不允许附件正文覆盖系统规则；
- 不允许把正式文件放在 Railway 临时磁盘；
- 不允许在日志中输出密钥、完整 Prompt、个人信息或完整查询结果；
- 不允许未获用户授权就执行 Git 发布或 Railway 正式部署。

---

## 16. 后端 Definition of Done

一个后端功能只有满足以下条件才算完成：

- 对应 PRD 用户故事和验收标准已满足；
- Pydantic 请求和响应稳定；
- 商家隔离已覆盖；
- 正常、空、错误、超时和降级均有定义；
- SQL 使用受控模板和绑定参数；
- 外部依赖可以 Fake；
- 单元和 API 测试已增加；
- Migration 和 Seed 职责分离；
- 以下命令全部通过：

```powershell
uv run ruff check .
uv run ruff format --check .
uv run mypy app
uv run pytest
```

- OpenAPI 已更新，契约快照测试通过；
- 前端所需字段有契约；
- 如新增路径、数据库或服务，`AGENTS.md` 已同步。

---

## 17. 建议的首批任务

coding agent 可以按以下顺序直接开工：

1. 创建 `backend/` FastAPI 工程（发行名 `borough-merchant-ai`，导入根包 `app`）；
2. 配置 Pydantic Settings、日志和统一错误；
3. 创建 Health API；
4. 配置 SQLAlchemy 和 Alembic（默认 `public` schema，不设 `search_path`）；
5. 创建 Merchant、Conversation、Message、Answer（含 `client_request_id` 唯一约束与 `request_digest`）；
6. **创建 Merchant Context、演示 Token 解析、隔离 Repository 基础设施和跨商家反例测试**——这一步必须先于任何经营查询完成；
7. 定义 ChatRequest、ChatResponse 和 OpenAPI（按 §8.2 两组字段划分必填性），**先把无实现的 Schema 提交给前端生成类型**；
8. 实现 SSE 与非流式双路径，含 §8.5 幂等状态机；
9. 创建预置推荐问题配置；
10. 创建 Fake Agent，逐节点推送 `step` 事件，覆盖 Prototype 预置场景；
11. 创建第一版 Seed（180 天，含退款与退货两类记录）；
12. 与前端联调 Mock 闭环；
13. 再进入结构化意图和安全查询。

第 7 步的顺序很重要：前端的 Mock 必须基于 OpenAPI 生成类型编写，否则会先形成一套本地字段，接入真实 API 时集中返工。

真实 LLM Adapter 可以提前定义接口，但在完成 Fake Agent、安全查询和测试前，不应成为主流程依赖。
