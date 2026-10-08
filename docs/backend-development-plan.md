# Borough 双端 Agent 平台后端开发计划

> 适用对象：后端开发人员、全栈开发人员、coding agent  
> 产品名称：Borough 双端 Agent 电商平台
> 目标技术栈：Python 3.12 + FastAPI + PostgreSQL  
> 产品范围：以 `docs/PRD.md` 为准  
> 工程规则：以根目录 `AGENTS.md` 为准
> 状态说明：B0–B9 与 P0/P1/P2 是旧单端路线的历史实施编号，只用于解释现有代码；
> 新需求排期统一使用 PRD N1–N5。未被新 PRD 保留的旧待办不得继续实施。

---

## 1. 开工前必读

按顺序读取：

1. `AGENTS.md`
2. `docs/PRD.md`
3. `docs/specs/2026-09-18-anthropic-fusion-decisions.md`
4. `docs/project-progress.md`

只在 PRD 明确保留某项历史行为时查阅只读参考项目；参考实现不再反向产生 Borough 需求。
重构时优先复用已验证的 Borough 业务契约、安全规则与测试资产。

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

### 3.2 数据处理

本版保留 CSV 导出与现有表格处理依赖，不建设附件上传、PDF/图片解析、OCR 或对象存储。
历史环境中已存在的附件相关依赖不构成继续开发附件能力的授权；未来重启时须先修改 PRD。

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

LLM 和未来确有证据后引入的外部客户端必须通过协议接口注入，测试使用 Fake 实现。

### 5.6 N 路线分层增量

§5.1–§5.5 的分层职责**不变**。本节只定义 N 路线新增的 **Agent 内核模块**住在哪里、
与冻结基线什么关系，以及这些模块允许依赖谁；N1–N5 仍会按既有分层新增 API、Service、Repository、
ORM 与前端代码，不能误读成“全部新能力只放 Agent Layer”。**它管 N2–N5 的新内核；任何新内核模块
开工前先读本节。**

#### 与冻结 LangGraph 的关系：并存，不替换

O4 裁定 `backend/app/agent/graph.py` 的 12 节点图**冻结为只读评测基线**，不再承接新能力、
不部署为新生产主流程。因此：

| | 冻结基线 | 新工具循环 |
| --- | --- | --- |
| 入口 | v1 `POST /api/chat` | v2 `POST /api/v2/shop/chat`、`/api/v2/merchant/chat` |
| 代码 | `app/agent/graph.py`、`state.py`、`prefilter.py` | `app/agent/loop/`（新建） |
| 状态 | `AgentState` TypedDict，12 个固定节点 | `LoopState`，轮次驱动 |
| 变更 | **只读**。只允许修依赖版本与安全补丁 | 正常演进 |

两者**不共享代码路径**，只共享下层设施：`app/llm/`（客户端与预算）、`app/services/safe_query.py`、
`app/repositories/`、`app/knowledge/`、`app/metrics/`。

> **不要试图"把新能力加进 graph.py"或"让新循环复用 GRAPH_NODES"。** 冻结的价值在于它是
> 可对照的评测基线——一旦被改动，N2 之后就再也没有"旧实现在同一题上怎么答"的参照。
> 新循环走通后，两者在同一评测集上的对比报告是 N2 的交付物之一。

#### 新模块目录与依赖方向

```text
app/
  tools/          A3 工具注册表与四类闸门          ← 新建
  skills/         A4 Skill 定义与按需加载          ← 新建
  agent/loop/     A2 工具调用循环与预算            ← 新建
  memory/         A6 记忆抽取、过滤与两层结构       ← 新建
  eval/           E1–E4 评测集、评分与安全门禁      ← 新建
  knowledge/      A7 混合召回与索引版本（扩展既有）  ← 扩展
  agent/graph.py  冻结基线                        ← 只读
```

依赖只允许自上而下，**同层之间不得互相 import**：

```text
loop  →  skills  →  tools  →  services / repositories / knowledge / metrics
  ↓                   ↓
memory              llm（LlmClient / LlmBudget / LlmCostGuard）
```

具体禁止项：

- `tools/` **不得** import `loop/` 或 `skills/`——工具必须能脱离循环单独测试；
- `skills/` **不得**直接 import `repositories/`——数据访问一律经 `tools/`；
- `memory/` **不得** import `loop/`——记忆抽取是异步后置流程，不能反向拉起循环；
- 任何新模块**不得** import `app/agent/graph.py` 或 `app/agent/state.py`；
- `eval/` 可以 import 任何模块，但**不得被任何生产模块 import**。

#### 与既有资产的衔接（不新造轮子）

| 新模块要用的能力 | 复用既有 | 不要另起一套 |
| --- | --- | --- |
| 模型调用 | `app.llm.client.LlmClient` Protocol；v2 工具循环用其子协议 `ConversationalLlmClient`（§6.17） | 不新增第二个客户端协议 |
| 单请求预算 | `app.llm.client.LlmBudget`（`charge_call()` / `charge()`） | 不在循环里自己数次数 |
| 每日预算与降级归因 | `app.llm.guard.LlmCostGuard`、`LlmFailureKind` | 不自定义失败分类 |
| 工具参数校验 | `app/intent/` 的 Pydantic 模式（R4：模型只输出结构化意图） | 不接受自由字符串参数 |
| 受控查询 | `app.services.safe_query` | 工具内不得拼 SQL |
| 限流与可信 IP | `app.core.rate_limit`、`app.core.client_ip` | — |
| 降级语义 | 在 `app.services.quality_types` 的单一共享枚举上复用 `UPSTREAM` / `VALIDATION` / `BUDGET`，并为新循环补 `LIMIT` / `TIMEOUT` | 不在 loop 内另写字符串或第二套枚举 |

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

**v1 没有 user 概念。** Token 直接映射到商家；管理员由独立 `ADMIN_TOKEN` 判定并走
`X-Admin-Token`。N1 将增加顾客/商家会话基础设施：商家 Bearer Token 只用于换取会话，
顾客和商家后续都用带不可变角色的 `X-Session-Id`，下游从会话解析 `merchant_id` / `buyer_key`。
真实注册登录、SSO 与 `users` 表不在本版范围。

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
- 导出、双端会话、草稿、售后与记忆隔离。

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
- `needs_attachment` 是 v1 遗留字段，本版恒为 `false`；v2 契约不得继续携带；
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

> **以下 §6.9–§6.15 是 N 路线新内核的模块边界。** §6.1–§6.8 描述的是 v1 冻结基线的模块，
> 两组模块并存且不互相 import（§5.6）。新模块开工前先读 §5.6 的依赖方向表。

## 6.9 Tool Registry

对应 PRD A3。工具是新内核唯一的数据出入口——循环与 Skill 都不直接碰 Repository。

### 输入

- `SessionContext`（由会话解析，含不可变 `role`、`merchant_id`，顾客侧另有 `buyer_key`）；
- 工具名与**未经校验**的模型输出参数。

### 输出

```python
class ToolRole(StrEnum):
    CUSTOMER = "CUSTOMER"
    MERCHANT = "MERCHANT"
    MCP_READONLY = "MCP_READONLY"   # 商家工具集的只读子集，见 A8


class WritePolicy(StrEnum):
    READ_ONLY = "READ_ONLY"
    CUSTOMER_DIRECT = "CUSTOMER_DIRECT"          # 购物车绝对数量等天然幂等写
    CUSTOMER_CONFIRMATION = "CUSTOMER_CONFIRMATION"  # 下单、售后等界面确认证据
    MERCHANT_DRAFT = "MERCHANT_DRAFT"            # 商家经营变更只生成草稿


@dataclass(frozen=True)
class ToolSpec:
    name: str
    roles: frozenset[ToolRole]
    args_model: type[BaseModel]      # 必须是 Pydantic 模型，extra="forbid"
    write_policy: WritePolicy
    parallelizable: bool


@dataclass(frozen=True)
class ToolResult:
    ok: bool
    payload: object | None            # 结构化结果，供后端确定性代码消费
    display: ToolDisplay              # 脱敏展示信息，唯一允许进 SSE 的部分
    reason_code: ErrorCode | None     # 失败时的公开稳定原因码，不用自由字符串
```

`ToolDisplay` 只含工具名、状态、耗时、行数与可公开摘要。**`payload` 永不进 SSE**，
`display` 永不含原始参数、SQL 或完整结果行（`docs/PRD.md` §11.3；精确的 `tool_call` /
`tool_result` 事件字段由 §8.7 的 v2 SSE 契约定义，该节尚待写入，见 §8.0.1）。

N2 落地补充（2026-09-22，实现与本节核对后回写；上面五个字段与四个类型名不变，只追加）：

- `ToolSpec` 追加 `description`（给模型的工具说明）、`executor`、`provenance_refs`（哪些参数引用了
  必须先在本对话出现过的对象，及其对象类型）、`option_source`（选项闸门的合法值来源）、`guardrail`、
  `draft_kind`（仅 `MERCHANT_DRAFT`）。executor 签名固定为 `(ToolContext, args) -> ...`，
  `ToolContext` 携带 `SessionContext`、`conversation_id`、`request_id`，注册时用类型注解自检；
- executor 的返回类型随 `WritePolicy` 固定，注册时同样按注解自检：`READ_ONLY` / `CUSTOMER_DIRECT`
  返回 `ToolOutput`；`MERCHANT_DRAFT` 只能返回 `DraftProposal`，由审批闸门交给草稿端口落草稿行，
  executor 在类型上就拿不到「直接写目标对象」这条路；`CUSTOMER_CONFIRMATION` 只能返回
  `ConfirmationPreview`，真正的写入走带界面确认证据的端点（§8.7.9），循环内不执行；
- **`ToolDisplay` 与 §8.7.5 一一对应**（2026-09-23 自查修正）：字段为 `tool_name`、`call_id`、
  `status: ToolDisplayStatus`、`duration_ms`、`row_count`，**没有任何自由文本字段**；`tool_call` /
  `tool_result` 载荷由 `ToolDisplay.call_event(locale)` / `result_event(locale)` 投影，摘要只取契约
  固定的双语短句，并经 `ToolCallDisplay` / `ToolResultDisplay` 校验器再核一次。首版曾让 executor
  自写摘要进 display（实测「补货 37 件」把参数带进了 SSE），已撤销；
- `ToolResult` 追加 `outcome: ToolOutcome`（`SUCCEEDED` / `DRAFT_CREATED` / `AWAITING_CONFIRMATION` /
  `REJECTED` / `INVALID_ARGUMENTS`，比对外状态细，映射见 `app.tools.types.DISPLAY_STATUS`）、
  `summary`（工具给模型的说明，可含参数，不进 SSE）与 `guardrail`；
- `ToolResult.reason_code` 维持 `ErrorCode`：护栏失败为 `GUARDRAIL_REJECTED`，参数校验失败或工具名
  不存在为 `INVALID_REQUEST`，需界面确认为 `CONFIRMATION_REQUIRED`。具体护栏规则码（如
  `DISCOUNT_EXCEEDS_LIMIT`）、当前限制与修正方法放在 `ToolResult.guardrail`，形状复用 §8.7 已有的
  `GuardrailCheckResult`，经工具消息交给模型转述给商家，不进 SSE；
- **工具名不存在**是模型的错误，返回 `INVALID_REQUEST` 的 `ToolResult` 交还模型修正，不终止回合、
  不写审计；**真实存在但不属于当前角色工具面**的工具才是安全事件；
- 进入四类闸门前还有两道致命前置检查：工具不在当前角色工具面；模型参数的顶层键出现
  `merchant_id` / `buyer_key`（企图经参数改写身份）。其余 Pydantic 校验失败不是安全事件，返回
  `INVALID_REQUEST` 的 `ToolResult`，不含原始校验信息；
- 来源状态的主体键：访客为 `GUEST_SESSION` + 内部 `session_record_id`；已绑定顾客与商家为
  `BOUND_PRINCIPAL` + `app.core.session.principal_digest()`（与幂等域同一摘要）。店铺即 `merchant_id`。

N3 阶段 C 落地补充（2026-09-27，图表可视化，§8.7.11）：

- `ToolOutput`/`ToolResult` 追加 `chart_data: object | None = None`——**不经过
  `_tool_message()` 序列化，不进 LLM 看到的工具结果消息**，只供 `LoopOutcome.tool_results`
  的消费方（`merchant_chat.py::_to_response()`）读取后构造 `MerchantChatResponse.visualization`；
  `payload` 与 `chart_data` 因此明确分工：`payload` 是"给模型引用的汇总数字"，
  `chart_data` 是"给图表用的完整数据点"，二者可以同时存在、互不影响对方的可见范围；
- 只有 `query_metrics`/`attribute_change` 两个工具会填充这个字段，其余工具恒为 `None`；
- 该字段不改变 `_check_policy()`/`_check_executor()` 的既有校验规则（不是新的
  `WritePolicy` 分支，`READ_ONLY` 工具的返回类型仍是 `ToolOutput`，只是多了一个可选属性）。

### 四类闸门

按 A3 沿用蓝图四类，执行顺序固定，**前一道不过不进下一道**：

| # | 闸门 | 判定 | 不通过 |
| --- | --- | --- | --- |
| 1 | **来源闸门** | 对象是否在**本对话**中由工具返回过 | 终止回合 |
| 2 | **选项闸门** | 参数是否在后端给出的合法选项集合内 | 终止回合 |
| 3 | **护栏闸门** | 业务限制（折扣幅度、调价幅度、库存、时效） | 返回公开原因码 |
| 4 | **审批/确认闸门** | 按 `WritePolicy` 校验：顾客直接幂等写、顾客界面确认、商家草稿审批分别处理 | — |

**来源状态的隔离键是「登录主体 + 店铺 + 对话 ID」**（D8④、O2），带版本号防并发覆盖。
一个对话里取得的对象访问资格**不得扩散到其他对话**；新建对话时来源状态从空开始。

### 规则

- 工具参数一律经 Pydantic 校验（R4），模型**不输出 SQL、不选数据源、不定指标公式**；
- `merchant_id` / `buyer_key` 由注册表从 `SessionContext` **强制注入**。
  **模型可见的 `args_model`** 不得出现这两个字段；内部 executor 明确接收 `SessionContext`，
  不得靠全局变量，也不得把可信身份重新拼回模型参数；
- `parallelizable=true` 只允许与 `write_policy=READ_ONLY` 组合，注册时发现矛盾即失败；
- `MERCHANT_DRAFT` 只生成草稿；`CUSTOMER_CONFIRMATION` 必须验证服务端签发、一次性、短期有效且
  绑定主体/资源/请求摘要的界面确认证据；`CUSTOMER_DIRECT` 只允许 PRD 明确列出的天然幂等操作。
  购物车、结账和顾客售后不得被错误套进商家草稿审批（PRD SEC6）；
- **身份、权限、安全拦截是致命错误，必须终止整个回合**（A2），
  返回 HTTP 401 / 403，**不得包装成 `ToolResult` 让模型继续尝试**；
- 失败披露分两类（A3、O5）：业务护栏对授权商家给出原因码、当前限制与修正方法；
  安全闸门对**所有角色**只给中性说明，具体规则与内部闸门名**只写安全日志**；
- 前端不得展示内部异常类名或原始校验信息；
- 角色决定可见工具面：顾客会话看不到商家工具，反之亦然；MCP 凭证只能看到只读子集。

### 必测

- 模型可见 `args_model` 中出现 `merchant_id` / `buyer_key` 时注册即失败；内部 executor 必须接收
  `SessionContext`（注册表自检）；
- `parallelizable=true` 与非 `READ_ONLY` 组合注册失败；四种 `WritePolicy` 各有正反例；
- 顾客会话调用商家工具 → 403 + 审计，且**不产生 `ToolResult`**；
- 来源闸门：A 对话取得的商品 id 在 B 对话中使用 → 拒绝；
- 来源状态并发写 → 版本号裁决，只有一方生效；
- 护栏失败对商家可见原因码与修正方法，安全闸门失败只返回中性说明；
- 商家经营写工具**只产生草稿行，不修改目标对象**；顾客直接写与确认写分别验证自己的幂等/证据边界；
- `display` 中不含参数、SQL 与完整结果行。

---

## 6.10 Agent Loop

对应 PRD A2。**这是新内核的主循环，与冻结的 `graph.py` 并存不替换（§5.6）。**

### 输入

- `SessionContext`、用户消息、`conversation_id`；
- 已加载的 Skill 集合（§6.11）与可见工具面（§6.9）；
- **同一会话最近 N 轮历史**（`LoopRequest.history`，2026-09-28 用户裁定 D-N4-1）：只含用户与助手文字，
  N 取 `CHAT_HISTORY_MAX_TURNS`（默认 6，范围 0–20；0 表示不回放）；不含工具结果与推理内容；
  顾客历史消息按 A11 围栏。回放规则见 §8.8.3 / §8.9.3。

### 输出

```python
@dataclass
class LoopLimits:
    """A2 要求五项上限同时生效，不只设固定轮数。"""
    max_turns: int          # 循环轮数
    max_tool_calls: int     # 工具调用总次数
    max_llm_calls: int      # 取 AGENT_LOOP_MAX_LLM_CALLS，构造本回合的 LlmBudget
    wall_clock_seconds: float
    max_tokens: int         # 复用 LlmBudget.max_tokens，取 MAX_LLM_TOKENS_PER_REQUEST
    quality_max_attempts: int  # N2 追加：预算公式的加数，取 AGENT_LOOP_QUALITY_MAX_ATTEMPTS


@dataclass
class LoopOutcome:
    answer: str
    tool_calls: list[ToolDisplay]
    stop_reason: Literal["COMPLETED", "MAX_TURNS", "MAX_TOOL_CALLS",
                         "BUDGET", "WALL_CLOCK", "UPSTREAM", "CANCELLED", "FATAL"]
    degraded: bool
    degraded_reason: DegradeReason | None  # 单一共享枚举，含 LIMIT / TIMEOUT / CANCELLED
    quality_status: QualityStatus          # PASSED / DEGRADED / FAILED / NOT_RUN，供 §8.7.6 降级字段
    quality_attempts: int
    quality_notes: list[str]
    llm_calls: int                         # 本回合实际发生的 LLM 调用（含 Reviewer），供评测对照
```

N2 落地补充（2026-09-22，实现与本节核对后回写）：

- `DegradeReason` 即 `app/services/quality_types.py` 的既有枚举，**只追加** `LIMIT`、`TIMEOUT`、
  `CANCELLED` 三个成员，v1 不产生它们，v1 行为不变；
- `UPSTREAM`（模型调用失败或返回降级回合）与 `CANCELLED`（客户端断开）是原清单漏掉的两种真实停止原因；
- `FATAL` 不由循环返回：致命错误以 `FatalToolError` 抛出、终止回合（§6.9），`FATAL` 留给路由层落库时记录；
- 触顶映射：`MAX_TURNS` / `MAX_TOOL_CALLS` → `LIMIT`，`WALL_CLOCK` → `TIMEOUT`，
  `BUDGET`（调用次数或 token）→ `BUDGET`，确定性校验或 Reviewer 最终不通过 → `VALIDATION`；
- `run_loop(on_event=...)` 在回合进行中逐个发出 `ToolCallStarted`（闸门之前）与 `ToolCallFinished`（带 `ToolDisplay`），供路由推送 `tool_call` / `tool_result` SSE；
- `FatalToolError` 抛出前由循环填入 `completed_tool_calls`（已完成的 `ToolDisplay`）与 `llm_calls`，供路由层把已完成部分落库；
- 模型最终回答（或重新生成的回答）为空白时按 `UPSTREAM` 降级，不当作完成（R7）；
- 最后一个允许的轮次若仍请求工具，**不执行**这批调用（没有后续轮次消费其结果，只剩副作用），直接按 `MAX_TURNS` 停止；
  一批调用会使工具总数越过 `max_tool_calls` 时整批不执行，按 `MAX_TOOL_CALLS` 停止。

### LLM 调用预算必须重算

`docs/project-progress.md` 记录过一条教训：**两套重试是乘加关系**。v1 最坏路径是 10 次
（`MAX_INTENT_RETRIES=2` 使 understand 最坏 3 次，`QUALITY_MAX_ATTEMPTS=2` 每轮最多 2 次），
`MAX_LLM_CALLS_PER_REQUEST` 恰好配成 10。**工具循环引入新的加数，必须重新计算，
不能沿用 10。** 新公式：

```text
max_llm_calls  >=  max_turns                       # 每轮一次决策调用
                 + compaction_max_calls             # 摘要压缩策略触发时（§6.12）
                 + 2 * quality_max_attempts - 1      # 每次质量尝试 = 生成 + 独立 Reviewer，
                                                     # 第一次生成就是最后一轮决策，已计入 max_turns
```

N2 实现选择「最终作答直接由最后一轮决策产生」，所以第一次质量尝试的生成不重复计数（见下段）。
按默认值：`8 + 1 + (2 × 2 − 1) = 12`，与 `AGENT_LOOP_MAX_LLM_CALLS` 默认值一致。
式中的 `quality_max_attempts` 取 v2 专用的 `AGENT_LOOP_QUALITY_MAX_ATTEMPTS`（默认 2），**不复用** v1 的
`QUALITY_MAX_ATTEMPTS`：共用一个字段时，v1 调到 3 轮会让 v2 拒绝启动（2026-09-23 自查修正）。
（2026-09-22 前本式写作 `+ 2 * quality_max_attempts`，按默认值得 13，与默认 12 自相矛盾；
实施计划写作 `+ 1 + quality_max_attempts`，只在 `quality_max_attempts=2` 时与上式相等。两处均已按本式统一。）

`compaction_max_calls` 由配置 `COMPACTION_MAX_CALLS` 提供，默认 1：N2 循环不发起压缩调用，
这 1 次是给 N4 摘要压缩（§6.12）预留的额度，现在就计入公式，N4 接入时不必重算默认值。

`SessionRole` 只在 `app.core.session` 定义 `CUSTOMER | MERCHANT`；`ToolRole` 是工具可见面枚举，
两者不是第二套登录角色。注册表用一张穷尽映射把 `SessionRole` 转成对应工具面，MCP 凭证直接进入
`MCP_READONLY`，不得伪造 `SessionContext` 或复用浏览器会话。

若最终作答直接由最后一轮决策产生，不能再重复计一次；若实现选择在循环结束后单独生成，则把那一次明确
加回公式。预算测试必须构造“每轮都调用工具、每次质量尝试都生成且复核、压缩达到上限”的最坏路径，
断言恰好不越界；不得只按配置字段做算术单测。

新增配置项（沿用无前缀命名，R6）：

```text
AGENT_LOOP_MAX_TURNS            默认 8
AGENT_LOOP_MAX_TOOL_CALLS       默认 16
AGENT_LOOP_WALL_CLOCK_SECONDS   默认 60
AGENT_LOOP_MAX_LLM_CALLS        默认 12   # = 8 + 1(压缩预留) + (2 × 2 − 1)
AGENT_LOOP_QUALITY_MAX_ATTEMPTS 默认 2    # v2 专用，不复用 v1 的 QUALITY_MAX_ATTEMPTS
COMPACTION_MAX_CALLS            默认 1    # N4 摘要压缩预留，N2 循环不使用
COMPACTION_STRATEGY             默认 TOOL_RESULT_PRUNING  # N4-A；未经真实模型对比前的保守默认（§6.12）
COMPACTION_TRIGGER_TOKENS       默认 8000 # 按字符估算；单请求 token 预算按调用累计，阈值须远低于 MAX_LLM_TOKENS_PER_REQUEST
```

**v2 循环用独立的 `AGENT_LOOP_MAX_LLM_CALLS`，不复用也不改动 v1 的
`MAX_LLM_CALLS_PER_REQUEST=10`。** v1 的 10 是按其自身最坏路径精确配出的；
让两条链路共用一个上限，任一侧加码都会在不知情时改变另一侧行为。
`Settings` 启动时校验上式，不满足即拒绝启动。

**任何一项加码都要重算这条路径并同步 `AGENT_LOOP_MAX_LLM_CALLS`**，否则预算耗尽会以
「模型不听话」的面目出现，实际是配置算错。改这四个值的 PR 必须附上重算过程。

### 规则

- 五项上限**同时**生效，任一触顶即停止并按 `stop_reason` 如实披露，**不得静默截断**；
- 触顶不是错误：返回已获得的部分结果并标注 `LIMIT` 或 `TIMEOUT`（R7），不伪装成完整回答；
- **只有 `write_policy=READ_ONLY and parallelizable` 且互不依赖的工具可并行**；有写操作或有依赖一律串行；
- 致命错误（身份、权限、安全拦截）**立即终止整个回合**，不重试、不降级、不进 Reviewer；
- **确定性校验必须先于 LLM Reviewer 执行，安全不依赖 Reviewer**（A2、Q16）；
- 循环与 `graph.py` 不共享代码，只共享 `LlmClient` / `LlmBudget` / `LlmCostGuard` / `safe_query`；
- 客户端断开时取消循环，停止后续 LLM 调用（直接关系费用），但已完成内容仍完整落库（§8.4）。

### 必测

- 五项上限各一条触顶用例，`stop_reason` 与降级字段正确；
- 预算耗尽 → 同一 `client_request_id` 重试仍返回 `LLM_BUDGET_EXCEEDED` 且**不调用 LLM**；
- 权限失败终止回合且**不产生 `ToolResult`**、不进 Reviewer；
- 并行只发生在只读且互不依赖的工具之间；含写操作的批次强制串行；
- 确定性校验不通过时，**不调用 LLM Reviewer 就已拦截**；
- 与冻结基线在共有旧能力上的对照报告可复现（N2 交付物）。

---

## 6.11 Skill Loader

对应 PRD A4。顾客端 5 个、商家端 7 个，索引 + 按需加载。

### 输入

- Skill 索引（稳定排序、确定性序列化，供 A9 前缀缓存）；
- 本轮消息与会话角色。

### 输出

```python
@dataclass(frozen=True)
class SkillSpec:
    name: str
    version: str                  # 版本化
    roles: frozenset[ToolRole]
    body: str                     # 只读白名单资源
    max_chars: int
```

### 规则

- Skill 是**可信、版本化、只读**的白名单资源——它是提示词的一部分，不是用户数据；
- **加载器不能访问任意路径**：只从编译期确定的白名单目录读取，
  路径拼接前做规范化与前缀校验（复用 `app/knowledge/path_policy.py` 的同类思路）；
- 限制**单个 Skill 长度**与**单回合加载数量**，超限拒绝加载并记录，不静默截断；
- 角色不匹配的 Skill 不进入候选集；
- Skill 正文是本系统资产，**不需要** A11 围栏；工具返回的第三方文本需要。

### 必测

- 正确触发、误触发（不该加载时没加载）；
- **多 Skill 冲突**：两个 Skill 给出相反指令时的裁决可预期；
- 更新 Skill 后的回归；
- 加载器路径逃逸尝试（`../`、绝对路径、符号链接）一律拒绝；
- 单回合加载数与单个长度触顶的行为。

### N3 阶段 A 落地补充（2026-09-24，`plans/2026-09-21-n3-skill-loader.md`）

以下均为后端内部形状，**不进 §8 契约**、不进 SSE 与响应：

- **`SkillSpec` 追加两字段**：`description: str`（索引展示）与 `source: str`（R8 来源说明，Borough 新写的填 `borough`）。
  frontmatter 只接受 `name / description / version / source` 四个键且全部必填，`yaml.safe_load` 解析；
  `version` 为数字版本号（`1` 或 `1.2`），按字符串保存。类型定义在 `app/skills/spec.py`，循环只依赖这个模块。
- **白名单与路径**：根目录固定为 `app/skills/customer`、`app/skills/merchant`（`Path(__file__).resolve()`，启动时即绝对路径）；
  **启动期**一次性扫描直接子目录，目录名须匹配 `^[a-z][a-z0-9-]{1,63}$` 且等于 frontmatter `name`，符号链接与 Windows junction
  逐级拒绝，`resolve()` 后再核前缀；没有 `SKILL.md` 的子目录拒绝（不静默跳过）。**运行期 `load()` 只查内存表**，不碰文件系统；
  名字不合格式、属于其他角色或不存在，一律同一种拒绝。不复用 `knowledge/path_policy.py`，只沿用同类思路。
- **上限**：`SKILL_MAX_CHARS`（默认 8000，范围 500–64000）超限拒绝加载、不截断；`SKILL_MAX_PER_TURN`（默认 3，范围 1–8）
  经 `LoopLimits.max_skill_loads` 进入循环。
- **索引**：按名字排序、确定性序列化（A9）；非空时带固定索引头，写明冲突裁决顺序
  **「Borough 安全与业务规则 > 更具体的 Skill > 更一般的 Skill」**，且声明 Skill 不能放宽上文规则、不能授予工具列表之外的能力。
  两端 `system_prompt` = 原 `SYSTEM_PROMPT` + 空行 + 本端索引；索引为空时与 N2 **逐字节相同**。
- **`load_skill` 工具**（`app/skills/tool.py`，由 `create_app()` 装配注册，`app/tools` 不 import 它）：`READ_ONLY`、可并行，
  参数只有 `name`，合法取值由**护栏**从当前会话角色的索引给出——拼错、编造的名字或他端 Skill 以
  `GuardrailRejection(code="SKILL_NOT_IN_INDEX")` 交还模型修正，回合继续、不写安全审计、不占单回合加载额度
  （与编造不存在的工具名同一处理）。不用选项闸门：它失败即整轮 403 + 安全审计，而 Skill 只读、按角色分表、
  名字本就公开在提示词里，判成越权没有安全收益、只会让用户对话白白失败（2026-09-25 自查整改）。executor 内仍保留
  `FatalToolError(gate="options")` 作闸门被绕过时的纵深防御。只有索引非空的角色能看到它；两端都为空时不注册。
- **受信通道**（`app/agent/loop/runner.py`）：工具名为 `load_skill`、结果成功、`payload` 类型为 `SkillSpec` 且属于当前会话角色，
  四者同时成立才免 A11 围栏，消息固定为 `<skill name="…" version="…">\n{body}\n</skill>`；其他工具返回的文本即便伪造 `<skill>`
  标记、甚至返回 `SkillSpec` 对象，照常围栏。单回合第 `max_skill_loads + 1` 次调用不执行，换成 `ToolOutcome.REJECTED`
  结果告知模型已达上限并写日志，**回合继续**。`LoopOutcome` 追加 `loaded_skills: list[str]` 与 `skill_limit_hit: bool`。
- **数字校验**：确定性数字校验（`agent/loop/checks.py`）**不把** Skill 正文当来源——它是做法说明，示例数字若能作证，
  模型照抄示例（「满 199 减 20」）就能骗过 R4 校验。
- **来源与模式**：只加载了 Skill 的回合没有查过数据，两端 `analysis_sources` 仍为 `NONE`、模式仍为 `CHAT`；`load_skill` 调用本身照实进 `tool_calls`。
- **回归框架**（`app/eval/skill_cases.py`，属评测侧，生产代码不 import）：Skill 目录可放 `cases.yaml`（`EvalCase` 格式，`skill` 字段必须等于目录名）；
  `stale_skill_cases()` 对比上次运行记录的版本号给出必须重跑的 Skill。记录的持久化归评测流水线（N4/N5）。

---

## 6.12 Context Compactor

对应 PRD A5。**两种策略都要实现用于对比，但生产选定一种确定策略**（Q19）。

### 输出

```python
class CompactionStrategy(StrEnum):
    TOOL_RESULT_PRUNING = "TOOL_RESULT_PRUNING"   # 工具结果清理
    SUMMARIZATION = "SUMMARIZATION"                # 摘要压缩（消耗 LLM 调用）
```

### 规则

- 压缩后**必须保留**三项：工具来源、数据截至时间、草稿版本。丢了任一项，
  后续回答就无法满足 M3「必须返回数据截至时间与来源」和 D9「批准绑定草案版本」；
- 指标工具的同一次调用锚点在同一行并排呈现指标、结果值、数据来源、截至时间和定义版本，
  以 `工具名#call_id` 绑定；不同调用不得把数值与另一调用的定义版本拼接。此结构只改善模型可见上下文，
  真实回答是否保留全部来源字段仍须按 PRD §12.5 专项评测判定；
- **旧对话摘要是模型生成内容，不得升级为事实来源**——它只能影响语气与上下文理解，
  不能充当数字、规则或状态的依据（与 D18① 同一条原则）；
- **回放的助手历史回答同样是模型生成内容**（D-N4-1）：本轮回答中的数字若只能在历史回答里找到、
  不能追溯到本轮工具结果或锚点，确定性校验判为无来源并降级；**跨回合不重建锚点**——回放只含文字，
  不从 `messages.response_payload` 或助手文字中抽取数字，需要旧数字时本轮必须重新调用工具
  （2026-10-02 按实现更正，原文「从 response_payload 重建」从未实现）；
- **身份保存在服务端可信上下文，不反复塞进提示词**；
- `SUMMARIZATION` 策略的 LLM 调用计入 `compaction_max_calls`，见 §6.10 的预算公式；
- 两策略在同一评测集上的对比报告是 N4 交付物；选定后另一策略保留在 `eval/` 供回归。
- **2026-09-30 选型（保守默认；同日的真实对比经 2026-10-01 独立复审判定为未冻结口径的探索性运行，不作为选型证据）**：生产默认 `TOOL_RESULT_PRUNING`
  （`COMPACTION_STRATEGY`），触发阈值 `COMPACTION_TRIGGER_TOKENS` 默认 8000（字符估算）。E5 Fake 评测两策略
  四项保持率均为 100%，摘要策略吸收历史、多一次计费调用，证据见 `docs/history/eval/n4-e5-compaction-fake.md`。
  `SUMMARIZATION` 仍可配置切换并由该评测回归。真实对比（`deepseek-flash` 90 次、383,755 token）人工复核后两策略各 28/30，
  摘要策略总 token 约为清理的 1.87 倍，证据见 `docs/history/eval/n4-e5-compaction-real.md`；
- 截至时间锚点带产出它的 `工具名#call_id`，与带数值的来源行同键（真实对比发现模型无法关联数值与定义版本）；
- 模型正文出现上游内部工具调用标记（DeepSeek `DSML`）时按上游异常可见降级，不当回答展示、不当调用执行；
- 压缩在每次工具轮决策前判断；生效时推送 SSE `step`（`node="compact_context"`）并写入最终响应 `thinking_steps`，
  不静默发生；

### 必测

- 压缩前后，工具来源 / 数据截至时间 / 草稿版本三项无损；
- 摘要内容不会被下游当作事实来源引用（断言引用链只指向工具结果）；
- 只复述历史回答中的数字、本轮未调用工具时，回答判为无来源并降级；
- 提示词中不出现 `merchant_id` / `buyer_key` 原值；
- `SUMMARIZATION` 触发时预算正确扣减且不突破总上限。

---

## 6.13 Memory Pipeline

对应 PRD A6，顾客侧规则见 C7、商家侧见 M11。

### 规则

- **回合结束后异步抽取**，只读对话文字（不读工具结果），**失败不影响主回答**；
- 本版不引入通用 Worker / Redis 队列。主事务只追加幂等 outbox 任务行，现有 `cron` Service 用
  短批次、`FOR UPDATE SKIP LOCKED`、租约超时与重试上限处理；不得用进程内 `BackgroundTasks`
  冒充可靠异步交付，也不得让 Web 请求等待真实抽取完成；
- 幂等任务 + 租户隔离 + 重试上限 + **单独预算**（不与主回合共享 `LlmBudget`，
  参照既有 `localization_max_calls_per_request` 的独立预算做法）；「单独预算」只是单次任务的调用上限，
  抽取调用仍计入 PRD §10.2 的全局、角色、商家三级每日预算；
- 抽取调用在 `llm_usage.purpose` 记为 `MEMORY`，与 `AGENT` / `LOCALIZATION` 分列审计；排空生产入口只构造带每日预算熔断的 LLM 客户端，Fake 测试注入走受测底层函数；
- **抽取范围**（2026-09-28 用户裁定 D-N4-2）：只有回合落库时会话已绑定演示顾客（`buyer_key` 非空）且
  「记住我的偏好」开启的顾客回合才追加 outbox 行；访客回合不追加，访客绑定后**不补抽**绑定前的回合；
  商家回合按商家会话照常追加；
- **写入前后双重过滤**：拒绝手机号、身份证、银行卡、地址、邮箱等标识信息，
  以及健康、宗教、政治等敏感推断；
- 商家侧两层：`FACT`（带来源，可逐条删除）与 `SUMMARY`（可重建文档，删来源后重建）；
  顾客侧只做事实型，按**顾客 + 店铺**隔离，保留 180 天且**仅被读取不续期**；
- **两层都不得回答规则、替代知识库或充当经营数字来源**；
- 记忆经 `LoopRequest.memory_context` 注入：拼在系统消息的稳定前缀与围栏策略之后（A9），整体按外部文本围栏（A11），
  且**不计入确定性校验的数字来源**——只凭记忆复述的数字判无来源并降级（2026-09-30 修复：此前记忆拼进 `system_prompt`，
  会被当作来源）；
- **访客回合的身份说明（2026-10-03，N5 E，D-N5-4）**：顾客会话未绑定演示身份（`buyer_key` 为空）时没有记忆可注入，
  同一位置改放 `GUEST_SESSION_NOTE`（`services/v2/shop_chat.py`）：告知模型当前是访客、没有可查的订单 / 售后 / 记忆，
  遇到这类请求引导顾客先在页面绑定演示顾客，不调用 `get_my_order`、`check_after_sale_eligibility`、`prepare_after_sale`。
  说明只来自服务端会话，不含顾客文字，不进数字来源；三个工具的归属闸门不变（访客调用仍是致命错误 + 审计），
  说明只是让正常提问得到引导而不是 403。必测：访客回合的系统消息含该说明且位于静态提示词之后；已绑定顾客回合不含。
- 团队知识与记忆是**单向边界**：记忆绝不升级写回团队知识库；
- **不预设「更便宜的模型足够」**——抽取模型须经敏感信息误写率与事实准确率评测后选择（A6）；
  真实调用遵守 R3。
- **2026-09-30 选型**：抽取模型 `deepseek-flash`。E5 真实评测 40 条（应写 20、不应写 20）错误写入率 5%（2 条，均出自 1 条更正类用例），
  敏感信息与助手推测零误写，精确率 0.905、漏记 0；40 次调用共 8,731 token。证据 `docs/history/eval/n4-e5-memory-real.md`；
  未对比 `deepseek-v4-pro`。

### 必测

- 抽取任务失败不影响主回答已落库；
- 访客回合不产生 outbox 行，绑定后也不补抽；
- 同一回合重复触发只产生一条记忆（幂等）；
- 双重过滤的每类敏感信息各一条反例；
- 顾客记忆跨店铺不可见、跨顾客不可见；
- 商家删除 `FACT` 来源后 `SUMMARY` 被标记重建；
- 记忆预算耗尽不影响主回合预算。
- 回答只复述记忆里的数字（商家经营数字、顾客记忆里的价格）时降级，两端各一条。

---

## 6.14 Hybrid Retrieval

对应 PRD A7，是 §6.5 Knowledge Retrieval 的演进，**不是另起一套**。

### 规则

- 混合召回 = 关键词 + pgvector 向量；**先建关键词基线**，再选嵌入模型；
- **不锁死 `bge-m3`**：选较小的多语种模型并实测 Railway 部署内存与镜像体积后决定；
- 重排（rerank）**须证明收益**才保留，否则不引入；
- 索引更新走版本化原子切换（状态机见 `docs/PRD.md` §7.6）：
  构建中 → 验证中 → 已就绪 →（原子切换）→ 生效；
  失败时**优先继续使用上一生效版本并标记陈旧**，无可用旧版本才降级为关键词检索并显式标注（R7）；
- 知识文档正文是外部文本，进提示词前须按 A11 围栏。

### 实现（N4-C，2026-10-02）

```text
backend/app/knowledge/
  embedding.py        Embedder 协议；FastEmbedEmbedder（ONNX Runtime，不依赖 PyTorch，懒加载，失败即降级）
  index_versions.py   KnowledgeIndexService（build / activate / rebuild_until_fresh / snapshot）、
                      VectorIndexSearch（一条 SQL 读指针 + 分块）、验证探针 Recall@5 闸门
  fusion.py           rrf_fuse（k=60）
  probes/n4_e5_rag.yaml   E5 评测集，兼作切换验证探针（§5.6：评测依赖生产，不反向）
  retrieval.py        search_documents(keywords, *, vector_ranking=()) 做 RRF 融合；load_domain 与 v1 不变
backend/app/jobs/build_index.py   手动/Cron 构建入口；日常由启动后台与知识后台保存触发
```

- **分块**：按空行切段、累加到约 400 字一块，每块前缀标题；文档取最高块相似度。
- **融合**：关键词候选（≥ min(2, 查询片段数) 个片段命中）与向量候选（相似度 ≥ 模型阈值，前 10）做 RRF，
  取前 5；正文始终取自当前生效文档，索引里残留的已删文档不会返回。两路都空时如实返回未命中。
- **触发**：backend 启动后在后台预热并 `rebuild_until_fresh()`；知识后台写入在同一事务标陈旧，提交后后台重建
  （契约 §8.6.7）。分块只按版本插入、只 `DELETE` 旧版本，从不 `UPDATE`。
- **配置**：`EMBEDDING_MODEL`（空 = 关闭向量，`search_rules` 标注 `INDEX_UNAVAILABLE_KEYWORD_FALLBACK`）、
  `EMBEDDING_MIN_SIMILARITY`（留空取 `CALIBRATED_MIN_SIMILARITY` 标定值；未标定模型必须显式给出，否则启动失败）、
  `EMBEDDING_CACHE_DIR`、`EMBEDDING_THREADS`。镜像构建期按同名构建参数下载模型，运行时 `HF_HUB_OFFLINE=1`。

### 嵌入模型选型（Task 3，本机实测，2026-10-02）

Railway 现状（用户提供）：Hobby 套餐，backend 空载约 100 MB、CPU 近 0（只看了 15 分钟曲线，未看 7 天峰值）；
数据库为外部 Neon（`vector` 0.8.6）。Railway 未给出单服务内存硬上限的实测值，下表增量为本机
（Windows，ONNX Runtime 2 线程）进程 RSS，用于横向比较；**部署估算以 Linux 容器单线程实测为准**：gemma 镜像模型层 +1.26 GB、
预热后常驻 +795 MB、建索引峰值 +855 MB；bge-small-zh 分别 +95 MB、+170 MB、+275 MB（`docs/deployment.md`）。
完整对比见 `docs/history/eval/rag-hybrid.md`。

| 候选 | 多语种 | 模型体积 | 常驻 +RSS | 建索引峰值 +RSS | 查询 p50 | 混合 R@5（拒答率 0.90） | 结论 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `google/embeddinggemma-300m` | 是 | 1.2 GB | +536 MB | +815 MB | 30 ms | **0.935**（τ=0.40） | 质量最高；成本约为 bge 的 4–13 倍 |
| `BAAI/bge-small-zh-v1.5` | 否（中文） | 91 MB | +138 MB | +244 MB | 11 ms | 0.870（τ=0.575） | **选定**（2026-10-02 用户裁定） |
| `minishlab/potion-multilingual-128M` | 是 | 522 MB | +1018 MB | +1050 MB | 0.3 ms | 0.852（τ=0.425） | 内存大、效果次 |
| `paraphrase-multilingual-MiniLM-L12-v2` | 是 | 440 MB | +562 MB | +590 MB | 15 ms | 0.769（τ=0.65） | 增益不足 |
| `jinaai/jina-embeddings-v2-base-zh` | 中英 | 943 MB | +679 MB | +847 MB | 29 ms | 0.787（τ=0.50） | 增益不足 |
| `Qwen/Qwen3-Embedding-0.6B-Q` | 是 | 1.1 GB | +1166 MB | +1714 MB | 2775 ms | 0.898（τ=0.50） | 查询延迟不可接受，排除 |

关键词基线（同一评测集、当前生产路径）：R@5 0.759、MRR 0.639、nDCG@5 0.652、拒答率 0.90。
阈值在同一评测集上选取，二折交叉验证显示召回提升稳定、拒答率对阈值敏感（每折仅 5 条「应找不到」），
故 gemma 取 0.40 而非最优点 0.375。`bge-m3` 未列入：体积约 2.2 GB，已超过「多语种小模型」定位。

**选定 `BAAI/bge-small-zh-v1.5`（2026-10-02 用户裁定：产品以中文场景为主，英文为锦上添花）。**
这偏离了计划 Task 3「只列多语种候选」的规则，理由：计划写作时把跨语言当作硬需求，用户裁定后不再是。
只看 46 条中文问题，三者 Recall@5 为 关键词 0.761 / **bge 0.891** / gemma 0.946（MRR 0.674 / 0.791 / 0.834），
bge 已拿到大部分收益，与 gemma 的差距约 2–3 条用例；而 Linux 常驻内存 +170 MB 对 +795 MB、镜像 +95 MB 对 +1.26 GB、
44 块建索引 14 s 对 65 s，许可证为 MIT（gemma 为 Gemma 使用条款）。代价：英文提问无增益（维持关键词 0.75）；
字段名查询仍漏 2 条（`repay_status_name`、`appeal_status_name`），可在关键词侧补字段名精确匹配，不必换大模型。
语料扩充后用同一评测器复评，换模型只改 `EMBEDDING_MODEL`（阈值须按新模型重新标定）。

代码默认 `EMBEDDING_MODEL` 为空（测试不加载模型）；`docker-compose.yml` 与 Railway Variables 设为
`BAAI/bge-small-zh-v1.5`，阈值取标定值 0.575。

### 必测

- 索引切换是原子的，不存在「一半新一半旧」的检索结果；
- 构建失败时旧索引仍可用且被标记陈旧；
- 无可用旧索引时降级为关键词检索，且 `analysis_sources` 如实标注降级；
- 检索指标可复现：Recall@k、MRR / nDCG、引用正确率、回答忠实度。

---

## 6.15 Eval Runner

对应 PRD E1–E4。**`eval/` 可以 import 任何生产模块，但不得被任何生产模块 import**（§5.6）。

### 实现（N1，骨架 + 安全硬门禁；来自 `plans/2026-09-21-n1-eval-harness.md` Task 1–6）

```text
backend/app/eval/
  cases.py              EvalCase / Assertion / load_cases() / validate_coverage() / summarize()
  primitives.py          安全原语白名单（PRIMITIVES 字典），按名称调用，不接受任意函数
  security_harness.py    安全集执行器：真实 ASGI + 真实 PostgreSQL + 白名单原语的统一调度
  graders/assertions.py  第一层：http_status / error_code / audit_written / no_side_effect
  graders/llm_judge.py   第二层：grade_with_rubric()，签名结构上不接受候选身份参数
  runner.py              QualityRunner：断言先跑，失败即短路，不调用裁判
  report.py              render_report()：脱敏（密钥环境变量取值、手机号、buyer_key 等字段名）
  datasets/security/*.yaml  N1 四类 CROSS/SQLI/IDENTITY/BUYERKEY，每类 ≥3 条，共 13 条
  baseline/FROZEN.md      LangGraph 基线冻结记录（O4）
backend/tests/eval/
  test_eval_harness.py   Task 1（用例模型）+ Task 3（runner/裁判）自测
  test_security_gate.py  CI 硬门禁入口，含路由覆盖守卫、里程碑门槛、零 skip
  test_report.py         Task 4 报告脱敏与门禁独立性
  test_baseline_freeze.py Task 5 冻结守卫（节点顺序、不接入 /api/v2）
  test_isolation.py      §5.6 单向依赖扫描
  conftest.py             安全集专用夹具 + 零 skip pytest 钩子
```

用例有两种形态（`EvalCase.form`）：**端点用例**用 `httpx.AsyncClient` 打真实 ASGI 应用；
**原语用例**在被测对象还没有端点时，按名称调用 `primitives.py` 白名单登记的函数
（例如 `resource_scope.access_foreign_product` 直接调用 `require_owned()`）。两种形态共用
同一套四种断言；`no_side_effect` 用「最后一轮执行前后」的表快照比对实现，不判定 setup 轮次
产生的合法变化。

N1 安全集覆盖 CROSS/SQLI/IDENTITY/BUYERKEY 四类（`introduced_in: N1`），
APPROVAL/SELFAPPROVE/INJECTION 三类归 N2（`test_no_case_is_introduced_ahead_of_its_milestone`
按 `CURRENT_MILESTONE` 常量强制，提前混入即失败）。`test_every_v2_route_has_an_endpoint_security_case`
用 `app.openapi()` 枚举 v2 路由——FastAPI 近期版本把 `include_router` 折叠进内部
`_IncludedRouter` 惰性结构，`app.routes` 顶层不再能直接读出子路由的有效路径，
枚举必须走这条稳定的公开契约产出，不能假设 `app.routes` 是扁平列表。

**已知限制**（如实记录，未在本轮修复）：`POST /api/v2/shop/sessions/demo-customer` 的路由处理器
没有捕获仓储层 `SessionAlreadyBoundError` 并翻译成 409 `SESSION_ALREADY_BOUND`——已绑定顾客
试图改绑另一 `buyer_key` 时会走到未预期异常处理器（500），不是契约文档的 409。
`SEC-BUYERKEY-003` 只断言仓储层不变量本身（拒绝改绑 + `buyer_key` 不变），不声称该 HTTP
路径已修复；此项留给会话身份模块的后续收口。

Task 1–6 全部不需要真实模型（Fake/确定性），零费用。Task 7 步骤 1–2（真实模型质量评测）
2026-09-22 按 R3 取得用户明确同意后已执行：`app/eval/datasets/quality/n1_baseline_quality.yaml`
（6 条）+ `scripts/eval_quality_smoke.py`（双段式，默认只打印计划，硬编码
`deepseek-flash`/`https://api.deepseek.com` 并强制覆盖 `.env` 里的已退役别名，不信任环境取值），
实际发出 8 次真实调用，跑的是 v1 冻结商家 Chat 基线（当前唯一现成的真实端到端链路）。
6 条中 1 通过、5 失败，发现两类基线自身的真实缺陷（按 O4 不修复，只记录为基线特征，详见
`docs/project-progress.md` 与 `docs/history/eval/n1-quality-baseline-2026-09-22.md`）：
CHAT 问候语路径产出内部占位文案而非真正问候语；显示语言与消息语言不一致时分类会误判为 INVALID。
Task 7 步骤 3（与新工具循环对照）仍需 N2 工具循环存在才能执行，本轮未做。
质量数据集目前只有这 6 条 N1 基线用例，不含 E5 专项评测——那部分的被测对象在 N4 才存在。

### 规则

- 默认全部使用 Fake / 确定性 LLM，**不产生费用**；真实模型评测按 R3 单独授权；
- **关键安全集是硬门禁**：跨商家、跨角色、跨顾客访问、prompt injection、
  越权写操作等用例**零失败**才算通过，不允许「大部分通过」；
- 安全门禁在 N1 就要可跑，不等功能开发结束（PRD §15 N1、融合原则第 5 条）；
- 评测集、评分脚本与结果一并版本管理，保证可重复；
- 与冻结基线的对照只比**双方共有的旧能力**，不要求新功能实现两遍（A2）。

### 必测

- 安全集中任一用例失败时，评测整体判定为失败（门禁不可绕过）；
- 同一评测集重复运行结果一致（确定性）；
- 未授权时真实模型评测被跳过且**明确标注「待人工验收」**，不伪装成已通过。

---

## 6.16 Session Identity

对应 PRD §7.5、§9 SEC3、§12.1，`docs/specs/2026-09-18-anthropic-fusion-decisions.md` D7、D8、O1、O2，
实施计划 `plans/2026-09-21-n1-session-identity.md`。**顾客与商家复用同一套会话基础设施，
但角色、状态模型与路由依赖不同，不是可互换的凭证**（D8①）。v1 的 `MerchantContext` 与
Bearer 路径不受影响，两套并存直到 v2 前端切换完成。

### 输入

- 顾客：公开 `shop_slug`（签发访客会话）、`X-Session-Id`（后续所有顾客请求）；
- 商家：既有演示 `Authorization: Bearer <token>`（只用于换会话）、`X-Session-Id`（后续所有商家请求）；
- 服务端专属配置：`SESSION_TTL_SECONDS`、`BUYER_ALIAS_SECRET`、`DEMO_CUSTOMER_IDENTITIES`
  （`shop_slug` → 演示 `buyer_key`，仅服务端持有，不下发给前端）。

### 输出

```python
class SessionContext:
    session_record_id: UUID       # 内部主键，不是凭证
    role: SessionRole             # CUSTOMER | MERCHANT，签发后不可变
    merchant_id: UUID
    buyer_key: str | None         # 仅顾客会话；访客为 None
    shop_slug: str | None         # 仅顾客会话
    expires_at: datetime | None   # 供签发/绑定响应回显
```

`SessionRepository.resolve(token) -> SessionContext | None`：过期、已注销、已撤销三种情况
对外不可区分，统一 `None`。`require_customer_session` / `require_merchant_session` /
`require_bound_customer_session` 是仅有的三个角色守卫，管理员端点不使用它们（D8⑥⑦）。

### 规则

- 会话 ID 是**凭证**：`secrets.token_urlsafe(32)` 生成，库里只存 `sha256` 指纹，明文只在签发
  响应中出现一次；
- **角色签发后不可变**，由数据库触发器（而不仅是应用层）强制，堵住修数据脚本等旁路写入；
- 统一 `401 SESSION_REQUIRED`（缺头）/ `401 SESSION_INVALID`（过期、已注销、已撤销、格式错误）；
- **角色不符一律 `403 SESSION_ROLE_MISMATCH` 并写审计**，不降级为 401；
- 未绑定顾客调用要求已绑定的端点返回 `403 CUSTOMER_BINDING_REQUIRED`，不复用
  `SESSION_ROLE_MISMATCH`（访客与已绑定顾客的 `role` 都是 `CUSTOMER`）；
- 演示顾客绑定是**一次性、事务性、幂等**的（D7⑥）：同一 `buyer_key` 重试直接返回，
  不同 `buyer_key` 返回 `409 SESSION_ALREADY_BOUND`；绑定与购物车合并共用同一个数据库
  事务，任一失败整体回滚；
- **统一 403 非枚举响应**（O1、R5）：目标不存在与目标不属于当前主体在状态码、`code`、
  `message`、`details` 上逐字段一致，且两条路径执行完全相同形状的查询，不允许"先查存在性
  再早退"——那样的早退路径天然更快，构成时序侧信道；
- **双重过滤**（D7①）：顾客侧订单、退款、售后等查询强制 `merchant_id` + `buyer_key`
  同时过滤，跨店也要挡；
- **来源状态不跨对话扩散**（D8④/O2）：`conversation_provenance` 按
  `(principal_kind, principal_id, merchant_id, conversation_id, object_type, object_id)`
  隔离，登录会话本身不携带任何对象访问资格；写入用版本号条件更新，冲突重读最多重试 3 次，
  超限报错而不盲写；过期且未绑定的访客会话留下的来源状态由 Cron `app.jobs.purge_guest_provenance` 清理；
- 撤销演示 Token 时，由它换取的**全部**商家会话级联失效（D8⑤）；应用启动时按指纹把当前
  `DEMO_MERCHANT_TOKENS` 与已签发会话对账，撤销已移除 issuer 的会话，对账失败即中止启动，
  日志只记撤销行数；
- 顾客脱敏别名（D7⑤）按商家派生子密钥后取 `buyer_key` 的 HMAC 摘要：同一顾客在同一店铺
  稳定，不同商家之间不可关联，且不可从别名反解 `buyer_key`；
- 会话签发/绑定响应带 `Cache-Control: no-store`；日志、审计与异常上下文对 `X-Session-Id`
  与明文 `buyer_key` 全量脱敏（结构化日志由 `app/core/logging.py` 的 `redact_sensitive_values`
  按凭证键名脱敏，含嵌套请求头）；
- 购物车合并在 N1 只接端口（`CartMergePort`），生产装配 `EmptyCartMerge`
  （恒 `cart_adjusted=false`），真实实现由 `n2-trade-closed-loop` 通过
  `app.dependency_overrides[get_cart_merge_port]` 换入，不改路由代码。

### 必测

- 会话凭证高熵、唯一、指纹不可逆、原值不落库；
- 过期、已注销、已撤销三种情况对外响应逐字段一致；
- 顾客会话调商家端点、商家会话调顾客端点均 403 且写审计；
- 未绑定顾客调用绑定专属端点返回 `CUSTOMER_BINDING_REQUIRED`；
- 并发绑定不同身份只有一方生效（真实 PostgreSQL 行锁）；
- 购物车合并失败时绑定整体回滚，`buyer_key` 保持 `NULL`；
- 目标不存在与跨商家访问的响应体逐字段相同、状态码同为 403、耗时无系统性差异
  （独立 `security_timing` 门禁，中位数差 ≤10ms、p95 比值 0.8–1.25）；
- 双重过滤挡住跨顾客、跨店铺访问；
- 来源状态不跨对话、不跨店铺、不跨对象类型泄漏；同一记录并发写不丢版本；重试有上限；
  清理任务只删过期未绑定访客的来源状态且幂等；
- 撤销演示 Token 级联撤销其全部商家会话，未涉及的会话不受影响；启动对账撤销已移除 issuer 的会话，
  日志不含 Token；
- 日志不出现明文 `X-Session-Id`；5 条会话路由的方法、鉴权头、模型名与错误码由专用 OpenAPI 哨兵固定；
- 5 条会话签发路由的 HTTP 契约、跨角色门禁与审计，v1 API 零回归。

---

## 6.17 Model Client

对应 PRD A1，实施计划 `plans/2026-09-21-n1-llm-client-and-adapters.md`。**为 §6.10 的工具循环提供上游能力；
不含循环本身。** 编号 §6.16 留给 Session Identity（模块 D），两者互不依赖。

现有 `LlmClient.complete(system, user, ...)` 只能「问一句答一句」，挡住工具循环的三点：输入是两个字符串而不是
消息列表、没有工具定义入参、返回只有 `text`。因此 A1 的实质工作是**扩协议**，而不是再写一个适配器。

### 输入

```python
class ConversationalLlmClient(LlmClient, Protocol):      # app/llm/client.py
    async def converse(self, *, messages: list[LlmMessage], tools: list[ToolSchema],
                       budget: LlmBudget, options: LlmCallOptions = ...) -> LlmTurn: ...
    def converse_stream(self, *, messages, tools, budget, options = ...) -> AsyncIterator[LlmStreamEvent]: ...
```

- `LlmMessage(role, content, tool_call_id?, tool_calls?, reasoning?)`：`role="tool"` 必带 `tool_call_id`；
- `ToolSchema(name, description, parameters)`：`parameters` 是 JSON Schema，由 Pydantic 模型导出；
- 现有 `complete()` **签名与行为不变**，v1 链路继续用它；`LlmClient` 本身**不加方法**——
  `LlmCostGuard` 等 v1 实现按结构满足它，给它加方法会让它们集体失去资格，所以工具调用能力放在子协议里
  （这是扩展而非第二个客户端协议，§5.6 衔接表的「不新增第二个客户端协议」仍成立）。

### 输出

```python
@dataclass(frozen=True)
class LlmTurn:
    text: str | None
    tool_calls: list[LlmToolCall]          # LlmToolCall(call_id, tool_name, arguments_json: str)
    stop_reason: Literal["END_TURN", "TOOL_USE", "MAX_TOKENS", "ERROR"]
    tokens: int; input_tokens: int; output_tokens: int
    degraded: bool; failure_kind: LlmFailureKind | None; usage_known: bool
    cache_hit_tokens: int | None           # None = 提供方未上报，不等于 0
    cache_miss_tokens: int | None
    reasoning: ReasoningReplay | None      # 原样回放给同一协议；适配器之外不解读
```

流式事件为 `TextDelta(text)` 与 `TurnComplete(turn)`；`TurnComplete.turn` 与 `converse()` 的返回值同构。
构造期不变量：`TOOL_USE` 必带 `tool_calls`，`END_TURN` 的 `text` 不为 `None`（空串允许，表示模型返回了空内容，
由调用方降级）。

### 两种协议的差异

适配器吸收全部差异，**让 `LlmTurn` 在两种协议下形状完全一致**：

| | OpenAI 兼容（`openai_adapter.py`） | Anthropic 兼容（`anthropic_adapter.py`） |
| --- | --- | --- |
| 端点 | `{LLM_BASE_URL}/chat/completions` | `{LLM_BASE_URL}/anthropic/v1/messages`（`/anthropic` 由适配器拼接，`LLM_BASE_URL` 仍存根地址） |
| 认证头 | `authorization: Bearer <key>` | `x-api-key: <key>` + `anthropic-version: 2023-06-01` |
| system | `messages` 里的一条 | 顶层 `system` 参数（多条以空行连接），不在 `messages` 里 |
| 工具定义 | `{"type":"function","function":{name,description,parameters}}` | `{name, description, input_schema}` |
| 工具调用 | `message.tool_calls[]`，`arguments` 是**字符串** | `content[]` 里 `type="tool_use"` 的块，`input` 是**对象**——适配器序列化回紧凑 JSON 字符串 |
| 工具结果 | `role="tool"` 消息，逐条独立 | `user` 消息里的 `tool_result` 块；同一轮的多个结果**合并进同一条**消息（角色要交替） |
| 推理回放 | assistant 消息的 `reasoning_content` | assistant 内容里的 `thinking` 块（`ReasoningReplay.payload` 是块列表的 JSON） |
| 用量 | `usage.total_tokens` 等三项，`prompt_tokens` 含缓存命中部分 | `input_tokens` + `output_tokens`，**没有 total，自己相加**；`input_tokens` **不含**缓存命中部分（实测），总输入 = `input_tokens` + `cache_creation_input_tokens` + `cache_read_input_tokens`；缺 `input_tokens` / `output_tokens` 任一项即 `usage_known=False` |
| 缓存字段 | `prompt_cache_hit_tokens` / `prompt_cache_miss_tokens` | `cache_read_input_tokens`（命中）/ `cache_creation_input_tokens`（写入，归入未命中）；文档未列出，实测上报；未上报时为 `None` |
| 结构化输出 | `options.json_output` → `response_format: json_object` | 无对应能力，`json_output` 无效；靠提示词与下游 Pydantic 校验 |
| 流式 | `data:` 分片、`[DONE]`；请求带 `stream_options.include_usage` | `event:` 流：`message_start` / `content_block_*` / `message_delta` / `message_stop` |
| 结束判定 | 见到 `finish_reason` | 见到 `message_delta.delta.stop_reason` |

### 规则

- **预算先扣后发。** 先 `charge_call()`，再把 `min(剩余额度, LLM_MAX_OUTPUT_TOKENS_PER_CALL)` 作为 `max_tokens` 随请求发出；
  调用次数或 token 额度耗尽时**不发出请求**（发出去就要付钱）。成功后按上报的 `tokens` 记账；
- **不解析工具参数。** `arguments_json` 原样上交，解析与校验是工具注册表的职责（R4）。适配器若 `json.loads()` 并吞掉
  异常，畸形参数就会以「空字典」的面目进入工具而绕过闸门。Anthropic 适配器是唯一会碰参数的地方，且只做序列化；
- **上游失败是降级回合，不是异常。** 401 / 403 / 429 / 其他 HTTP / 超时 / 网络 / 响应损坏一律映射到既有
  `LlmFailureKind`（**不新增枚举**），返回 `stop_reason="ERROR"`、`degraded=True`、`text=None`、`tool_calls=[]`
  的回合（R7：降级必须可见）。认证失败被上游拒绝在计费之前，记 `usage_known=True`；
- **本地错误抛异常，且发生在扣预算之前**：未配置 `LLM_API_KEY`（`LlmUnavailableError`）、预算耗尽、
  推理回放来自另一协议、Anthropic 历史里的工具参数不是 JSON 对象——这些是调用方的 bug，不该被吞成「上游降级」，
  也不该白扣一次配额；
- **截断即丢弃工具调用。** `finish_reason=length` / `stop_reason=max_tokens` 时参数可能是半截的，
  `stop_reason="MAX_TOKENS"` 且 `tool_calls=[]`；
- **思考模式显式发送。** 官方默认开启，因此每次请求都发送 `thinking: {"type": ...}`。`LLM_THINKING`
  是**上限**，单次调用的 `LlmCallOptions.thinking` 只能把它收紧，不能越过它放开（两者都为 `enabled` 才开启）；
  默认 `disabled`，改默认值须以冒烟实测为据。官方文档要求思考模式下带 `tools` 的多轮请求回传此前每一轮的推理内容
  （文档称否则 400）；2026-09-22 实测 `deepseek-flash` 两协议省略推理内容都**未被拒**，但仍按文档回传——
  `LlmTurn.reasoning` 原样带回下一轮的 assistant 消息，无害且防上游收紧；
- **推理回放绑定协议。** `ReasoningReplay.protocol` 与适配器不符时抛 `ValueError`。`LLM_PROTOCOL` 是进程级配置，
  同一次对话的循环只用一种协议，切换协议须新开对话，不跨协议回放历史；
- **缓存未上报记 `None`，不记 0**：记成 0 会让成本估算误以为全部未命中。缓存字段只是附带信息，
  单个字段非法记 `None`，不因此判整次响应损坏；
- **流式：** 文本增量逐段产出，**工具调用不产出增量**（参数分片在适配器内按 `index` 拼完，只在最后的
  `TurnComplete.turn.tool_calls` 出现，半截参数交给上层没有用处还可能被误执行）；流以且仅以一个 `TurnComplete`
  结束；中途断流时为降级回合（`NETWORK`），已收到的工具调用分片一律丢弃，**已经展示给用户的文本保留在 `text` 里**；
  流内显式错误事件归为 `HTTP_OTHER`；令牌在流结束时记账一次；
- **协议开关：** `LLM_PROTOCOL` = `openai`（默认）| `anthropic`，只影响 `converse*`；`complete()` 固定走
  OpenAI 兼容协议。默认模型 `deepseek-flash`；`deepseek-chat`、`deepseek-reasoner` 与已退役别名
  `deepseek-v4-flash` 不得出现在任何生效配置（AGENTS.md R3）；
- **Fake：** `FakeLlmClient(turns=[LlmTurn, ...])` 按序回放回合，记录每次调用的消息快照、工具与选项，
  是 N2 全部循环测试的基础设施。脚本耗尽抛 `FakeScriptExhaustedError`（`AssertionError` 子类）——
  静默编造一个回合会掩盖「循环比预期多转一轮」的缺陷。

### 真实冒烟实测（2026-09-22，R3 授权）

范围：DeepSeek，`deepseek-flash`，三次授权共 **42 次**真实调用，估算约 $0.006（按 token 数与高峰价上限估，非平台账单）：
首轮思考 `disabled`、每协议 12 次；追加 Anthropic 原始 `usage` 诊断 2 次与思考 `enabled` 多轮工具历史每协议 2 次；
第三次为 `--suite extended`（思考 `enabled`，单次输出上限 1024）OpenAI 5 次、Anthropic 7 次。
逐项原始记录见 `docs/history/llm-smoke-2026-09-22.md`。

| 项 | OpenAI 兼容 | Anthropic 兼容 |
| --- | --- | --- |
| 普通问答、结构化 JSON（Pydantic 校验通过）、单工具调用、多工具并行 | 通过 | 通过 |
| 多轮工具历史（第 2 轮成功） | 通过（`disabled` 与 `enabled`） | 通过（`disabled` 与 `enabled`） |
| 思考 `enabled` 下的推理内容回放 | 通过：第 1 轮拿到 `reasoning_content`，原样回放后第 2 轮成功 | 通过：第 1 轮拿到 `thinking` 块，原样回放后第 2 轮成功 |
| **思考 `enabled` 下故意省略推理内容** | **未被拒**：HTTP 200、`END_TURN` | **未被拒**：HTTP 200、`END_TURN` |
| 思考 `enabled` 下的流式文本 / 流式工具调用 / 多工具并行 | 通过：增量只含正文，推理单独捕获；参数分片拼接可解析；一次 2 个调用 | 通过（同左） |
| 流式文本、流式工具调用（`disabled`） | 通过；流式返回用量（`stream_options.include_usage` 被接受） | 通过；流式返回用量 |
| 错误分类：无效 Key → `HTTP_401`；不存在的 `tool_call_id` → 被拒，归为 `HTTP_OTHER` | 通过 | 通过 |
| `thinking` 参数显式发送（`disabled` 与 `enabled`） | 被接受 | 被接受 |
| 缓存计量（非流式） | 上报 `prompt_cache_hit/miss_tokens`：同一前缀第 1 次 0 / 1570，第 2 次 1408 / 162 | 上报 `cache_read_input_tokens` / `cache_creation_input_tokens`（见下） |
| 缓存计量（流式，原始事件） | 末尾用量块含 `prompt_cache_hit/miss_tokens` | `message_start` 已含完整缓存字段；`message_delta` 带**完整** usage（输入、缓存与最终输出），不只输出数 |

**Anthropic 协议的用量缺陷：已证实并修复。** 原始 `usage` 对象为
`{"cache_creation_input_tokens": 0, "cache_read_input_tokens": 1408, "input_tokens": 162, "output_tokens": 1}`：
`input_tokens` **只含缓存未命中的部分**，命中数另在 `cache_read_input_tokens`，162 + 1408 = 1570，与 OpenAI 协议同一提示的
`prompt_tokens` 吻合。修复前适配器只读 `input_tokens`，缓存命中时 `tokens` 会低估、缓存计量恒为 `None`；现在总输入 =
`input_tokens` + 写入缓存 + 命中缓存，`cache_hit_tokens = cache_read_input_tokens`，写入缓存的部分归入 `cache_miss_tokens`
（`cache_creation_input_tokens` 实测恒为 0，这一归类是语义推定，未见非零样本）。流式下适配器按字段覆盖合并
`message_start` 与 `message_delta` 的 usage，对真实的「delta 带完整 usage」形状同样正确：同一次流式工具调用两协议折算
逐项相同（377 / 317 / 60，缓存 128 / 189），并有按真实事件原样构造的单测（`test_streaming.py`）。

**结论：`LLM_PROTOCOL` 生产默认保持 `openai`。** 两协议的功能、思考模式行为与用量口径（含流式）现在都有真实证据且互相对得上，
切换已不再有证据上的阻碍；保持 `openai` 是因为 v1 链路已在用它，而实测没有发现 Anthropic 协议带来任何可观察的收益——
切换只增加迁移成本。若日后需要 Anthropic 协议独有的能力，可直接切换，无需再补冒烟。

### 尚未验证与已知缺口

- **「省略推理内容会 400」经实测不成立**（`deepseek-flash`，2026-09-22）。回放仍保留：它是官方文档要求，上游随时可能收紧；
  在上游明确不再需要之前，不得为省 token 而去掉回放；
- 思考模式下「推理耗尽 `max_tokens` 导致正文为空」在 1024 上限下未出现，没有真实样本；适配器对它的处理
  （`MAX_TOKENS` / 空正文降级）只有 mock 证据。`cache_creation_input_tokens` 非零的情况也没有真实样本；
- 「非法请求被拒」只知归入 `HTTP_OTHER`（首轮冒烟当时未记录状态码；脚本已补传输层状态码记录，此项未重跑）；
- **`LlmCostGuard` 尚未包装 `converse*`。** 每日全局预算熔断目前只挡 `complete()`；工具循环接入 `converse()`
  前必须补齐，否则 v2 路径会绕过每日预算（上线前置条件，AGENTS.md 十一）。这属于 N5 三级预算，本模块不含；
- 流式中途断流时，若上游已在断流前扣费，`tokens` 记为 0 会低估——这是可见的降级（`degraded=True`），不是静默。

### 必测

- 数据类构造期不变量：`tool` 消息缺 `tool_call_id`、`TOOL_USE` 无工具调用、`END_TURN` 无文本都拒绝；
  `complete()` 签名不变；`LlmClient` 不新增必需方法（`test_converse_contract.py`）；
- 每个适配器：工具调用映射、并行调用保序、畸形参数原样上交、截断丢弃工具调用、预算先扣后发、
  429 / 401 / 超时 / 网络 / 响应损坏各自的 `LlmFailureKind`、思考模式每次显式发送且只能收紧、
  日志不含 Key（`test_openai_adapter.py`、`test_anthropic_adapter.py`）；
- **多轮工具历史的出站请求体**：工具调用、结果与推理内容按原样回放，跨协议回放被拒
  （`test_history_serialization.py`）——单轮 mock 证明不了「第二轮请求发得对」；
- 流式：文本拼接、参数分片拼接、并行调用按 `index` 分开、断流丢弃分片并保留已展示文本、错误事件降级
  （`test_streaming.py`）；
- 两适配器等价：喂等价响应，`LlmTurn` 在 `text / tool_calls / stop_reason / tokens / usage_known /
  degraded / failure_kind` 上逐字段相等，含缓存命中场景下两协议折算出同样的 `tokens`、`input_tokens` 与
  `cache_hit / miss_tokens`（数值取自真实冒烟）；**只证明解析一致，不证明两个真实接口行为等价**
  （`test_adapter_parity.py`）；
- Anthropic 用量折算：`input_tokens` 不含命中部分、写入缓存计入总输入与未命中、命中 0 与未上报（`None`）区分、
  非法缓存字段按未上报处理、缓存命中的调用按完整提示记账，流式 `message_start` 同理
  （`test_anthropic_adapter.py`、`test_streaming.py`）；
- 协议开关委派与 `complete()` 不受影响（`test_protocol_switch.py`）；Fake 脚本（`test_fake_converse.py`）；
  默认模型哨兵（`test_default_model.py`）；
- **零费用自检**：测试目录里 `api.deepseek.com` 只出现在 `_transport.py` 的 URL 断言常量里；
  无 `respx`；`llm_smoke` 不被 `app/` 或 `tests/` 引用（真实调用不加入默认测试套件，R3）。

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

CSV 导出记录是现有 v1 基线的一部分，继续独立保留。

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

先通过 `EXPLAIN` 和真实测试数据证明，再增加复杂索引。

## 7.4 迁移

以下编号记录旧路线的已执行迁移顺序；新迁移按 PRD N1–N5 规划，不复用 P0/P1 作为优先级：

- 第一迁移（P0）创建商家、会话、知识和运维表（`audit_logs`、`llm_usage`）；
- 第二迁移（P0）创建演示经营表；
- 第三迁移（P0）创建 `export_files`；
- 后续已创建 `merchant_memories`；本版不得新建 `attachments` 表；
- Seed 脚本不属于 Migration；
- Migration 不调用网络或 LLM；
- Migration 可以在空库重复验证；
- 不修改已发布 Migration，新增修复 Migration。

---

## 8. API Schema

> **本章是 ChatRequest / ChatResponse / ErrorResponse / SSE 的唯一权威定义，§8.6 起同时是
> 本地化 Header 与 Schema 变更的唯一权威定义。**
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
| `A/V` | 管理员或只读令牌 | **`X-Admin-Token: <token>`**；写操作仍只允许管理员 |
| `S` | URL 自带签名 | 无请求头，签名在 query 参数中 |
| `—` | 无需认证 | — |

**管理员令牌走独立请求头 `X-Admin-Token`，不复用 `Authorization`。** 两者语义不同、生命周期不同、泄露后果也不同；共用一个头会让后端无法区分"商家在调管理接口"和"管理员在调商家接口"，前端也容易误把管理员令牌发给商家接口。后端对 `A` 类接口只认 `X-Admin-Token`，出现 `Authorization` 一律忽略。

| 状态 | 方法 | 路径 | 认证 | 请求 | 响应 | 主要错误码 |
| --- | --- | --- | --- | --- | --- | --- |
| v1 已实现 | `POST` | `/api/chat` | M | `ChatRequest` | SSE 流或 `ChatResponse` | 401 403 409 422 429 503 |
| v1 已实现 | `GET` | `/api/conversations` | M | 分页查询参数 | `ConversationListResponse` | 401 |
| v1 已实现 | `GET` | `/api/conversations/{conversation_id}` | M | — | `ConversationDetailResponse` | 401 403 404 |
| v1 已实现 | `DELETE` | `/api/conversations/{conversation_id}` | M | — | `204` | 401 403 404 |
| v1 已实现 | `POST` | `/api/answers/{answer_id}/feedback` | M | `FeedbackRequest` | `FeedbackResponse` | 401 403 404 422 |
| v1 已实现 | `GET` | `/api/exports/{export_id}` | **S** | 签名参数 | `text/csv` 字节流 | 403 404 410 |
| v1 已实现 | `GET` | `/api/metrics/{code}` | M | — | `MetricDefinitionResponse` | 401 404 |
| v1 已实现 | `GET` | `/api/demo/merchants` | — | — | `DemoMerchantListResponse` | 404（功能关闭时） |
| v1 已实现 | `GET` | `/api/health` | — | — | `HealthResponse` | — |
| v1 已实现 | `GET` | `/api/ready` | — | — | `ReadyResponse` | 503 |
| v1 已实现 | `GET` | `/api/admin/ops/status` | A | — | `OpsStatusResponse` | 401 403 |
| v1 已实现 | `GET` | `/api/reports/daily` | M | 无参数；业务时区昨日由后端固定 | `DailyReportResponse` | 401 422 429 500 503 |
| v1 已实现 | `POST` | `/api/admin/reports/daily/recompute` | A | `merchant_id`、`report_date`、`reason`；仅演示商家、最近 180 天且非未来日期 | `DailyReportResponse` | 401 403 404 409 422 503 |
| v1 已实现 | `GET` | `/api/admin/analytics/chatbi/overview` | A/V | `ChatBiWindow` 查询参数 | `ChatBiOverviewResponse` | 401 403 422 |
| v1 已实现 | `GET` | `/api/admin/analytics/chatbi/categories` | A/V | `ChatBiWindow` 查询参数 | `ChatBiCategoriesResponse` | 401 403 422 |
| v1 已实现 | `POST` | `/api/admin/analytics/chatbi/rollup` | A | `ChatBiWindow` | `ChatBiRollupResponse` | 401 403 422 |
| v1 已实现 | `GET` | `/api/admin/knowledge/tree` | A/V | — | `KnowledgeTreeResponse` | 401 403 |
| v1 已实现 | `GET` | `/api/admin/knowledge/documents/{document_path}` | A/V | 可选 `content_locale` | `KnowledgeDocumentResponse` | 400 401 403 404 422 |
| v1 已实现 | `POST` | `/api/admin/knowledge/documents` | A | `KnowledgeDocumentRequest` | `KnowledgeDocumentResponse` | 400 401 403 409 413 415 422 |
| v1 已实现 | `PUT` | `/api/admin/knowledge/documents/{document_path}` | A | `KnowledgeDocumentUpdateRequest` + `If-Match` | `KnowledgeDocumentResponse` | 400 401 403 404 412 413 415 422 428 |
| v1 已实现 | `DELETE` | `/api/admin/knowledge/documents/{document_path}` | A | `If-Match` | `204` | 400 401 403 404 412 422 428 |
| v1 已实现 | `POST` | `/api/admin/knowledge/business-domains` | A | `BusinessDomainRequest` | `KnowledgeTreeNode` | 400 401 403 409 422 |
| v1 已实现 | `PUT` | `/api/admin/knowledge/business-domains` | A | `name` + `BusinessDomainRenameRequest` + `If-Match` | `KnowledgeTreeNode` | 400 401 403 404 409 412 422 428 |
| v1 已实现 | `DELETE` | `/api/admin/knowledge/business-domains` | A | `name` + `recursive` + `If-Match` | `204` | 400 401 403 404 409 412 422 428 |
| v1 已实现 | `POST` | `/api/admin/knowledge/memories/compress` | A | `MemoryCompressRequest` | `MemoryCompressResponse` | 401 403 404 422 |

说明：

- **没有** `GET /api/admin/knowledge/documents` 列表接口，目录由 `tree` 提供；
- `PUT` / `DELETE` 知识文档使用 ETag / `If-Match`，前置条件失败返回 `412`，缺头返回 `428`；
- 附件三个端点从未实现，已按 PRD D6 从本版路由计划移除；
- `/api/admin/knowledge/memories/compress` 使用 `X-Admin-Token` 对指定商家分类执行人工重压；先写独立审计日志再提交记忆，模型不可用时响应必须返回 `degraded=true` 与原因；
- `/api/admin/ops/status` 见 §9 B7 的运维端点定义；
- 每条路由至少有一条"未认证"、一条"跨商家越权"用例，越权必须返回 `403` 并写 `audit_logs`。

### 8.0.1 v2 契约迁移门槛

`docs/PRD.md` §11.2.2–§11.2.3 已固定 v2 方法与路径，但请求、响应、错误、幂等键和 SSE 事件字段
尚未迁入本章。N1 的第一项工作必须按七组逐项补齐字段契约：顾客会话与店铺浏览、商家会话与对话目录、交易（购物车与订单履约）、
售后（双端）、商家经营只读面（当日简报、库存告警、顾客信号）、草稿审批与变更账本、
记忆与反馈与 MCP。七组合计覆盖 PRD §11.2 的全部 47 条路径；原「六组」表述遗漏了
`briefs/daily/current`、`briefs/daily/current/regenerate`、`inventory/alerts`、
`customer-signals`、`customer-signals/{signal_id}/ignore` 五条。

在某一路径的字段契约完成前：

- 不得创建 FastAPI 路由或前端请求封装；
- 不得直接复用 v1 `ChatRequest` / `ChatResponse` 假装完成 v2；
- 不得接受前端传入 `merchant_id` / `buyer_key`；
- 不得把顾客会话、商家会话或 MCP 凭证互相复用；
- 不得宣称对应 N1 契约任务完成。

**OpenAPI 的生成时点：** 当前路由驱动的 OpenAPI 导出无法包含未被路由引用的 v2 Schema 和路径。
共享组件（如 ErrorCode）改变既有 v1 契约时，须在同次变更同步现有 OpenAPI、生成类型与错误处理映射，不能等到 v2 路由实现。
因此契约冻结的交付物是本章的字段定义，加上 `backend/app/schemas/v2/` 的 Pydantic 模型与其单测；
`docs/api.json`、`docs/api.md`、生成类型与 Adapter 在该组路由实现的**同一次变更内**同步。

这不放宽门槛，而是把门槛拆成前后两道。**每组路由的完成门槛必须同时满足**：

1. 本章对应小节的字段契约已写完（路由创建的前置条件）；
2. `cd backend; uv run python ../scripts/export_openapi.py` 已重新导出 `docs/api.json` 与 `docs/api.md`（仓库根目录没有 `pyproject.toml`，不能在根目录用 `-m` 方式运行）；
3. `npm run codegen` 已重新生成 `frontend/src/api/generated.ts`，且 `npm run codegen:check` 通过；
4. 对应 Adapter 与 Adapter 契约测试已更新；
5. OpenAPI 快照/哨兵测试通过（`backend/tests/api/test_openapi_chat_contract.py` 同类）。

五项缺一，该组不得标记完成。

**契约冻结状态（2026-09-21）：** 七组字段契约已全部写入 §8.7–§8.14，PRD §11.2 的 47 条路径逐条覆盖；`backend/app/schemas/v2/` 的 Pydantic 模型与单测已落地。上述五项中的第 1 项（字段契约）对七组均已满足，第 2–5 项仍随各组路由实现的同一次变更完成——**契约冻结不等于 v2 功能已实现**，v2 路由、OpenAPI 导出、生成类型与 Adapter 尚未开始。

**2026-09-28 追加**：PRD §11.2.3 按 M1 裁定新增三条商家只读路径：
- `metrics/overview`；
- `orders`；
- `orders/{order_id}`。

字段契约在 §8.12.4，路由由 `plans/2026-09-28-merchant-workbench-redesign.md` 实现。上文「47 条」是 N1 冻结时的历史计数；当前 PRD 路径总数以 §11.2 为准，由 v2 路径清单哨兵核对。

### 8.0.2 Chat BI 衡量层契约

三个端点的精确字段由 `app/schemas/analytics.py` 定义并以导出的 OpenAPI 为最终来源。`ChatBiWindow` 的 `start_date` 与 `end_date` 是闭区间，必须满足起日不晚于止日且窗口不超过 180 天；GET 端点使用查询参数，Rollup 使用 JSON 请求体。

- `ChatBiOverviewResponse`：窗口、问答/业务问题/反馈/思考样本计数、六项北极星指标与每日趋势；
- `ChatBiCategoriesResponse`：窗口与按问答量降序的分类项，每项带分类代码、中文展示名、问答量和六项指标；
- `ChatBiRollupResponse`：已执行的窗口和写入行数；
- 六项比率字段均为 `float | null`，其中 `null` 仅表示样本不足，前端必须区别于 0。

看板响应不得包含 `merchant_id`、问题原文或回答正文；它只服务全平台质量聚合，不提供商家数据检索能力。

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
| `attachment_ids` | `list[str]` | 否 | v1 遗留保留字段；本版必须省略或为空数组，v2 不继承该字段 |
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
| `quality_attempts` | `int` | 否 | 质量循环尝试次数，0–3 |
| `quality_notes` | `list[str]` | 否 | Reviewer 备注，**数组**，无备注时为空数组而非 `null`。语义说明也走这里，不新增 `semantic_notes` |
| `analysis_sources` | `list[AnalysisSource]` | 否 | **有序数组**，主要来源在前，至少一个元素 |
| `degraded` | `bool` | 否 | 是否降级 |
| `degraded_reason` | `str \| null` | 是 | 未降级时为 `null` |
| `suggestions` | `list[str]` | 否 | 当前一组预置推荐问题 |
| `suggestion_alternates` | `list[list[str]]` | 否 | 其余候选组，供"换一换"本地轮换 |
| `created_at` | `datetime` | 否 | UTC，ISO 8601 |

**枚举**：

```text
AnswerMode     = METRIC | DETAIL | RULE | IDENTITY | CHAT | INVALID | ATTACHMENT（v1 遗留保留值，本版不产生）
QualityStatus  = PASSED | DEGRADED | FAILED | NOT_RUN
AnalysisSource = DATABASE | KNOWLEDGE | ATTACHMENT | MEMORY | FALLBACK | NONE
MetricStatus   = ACTIVE | DEPRECATED | UNVERIFIED
QuestionCategory = PLATFORM_RULE | TRADE | REFUND | CS_TICKET | COMPENSATION
                 | COUPON | GOODS | MERCHANT_OTHER | IDENTITY | SCM | UNKNOWN
```

`category` 取 `QuestionCategory` 枚举，**不是自由字符串**。该枚举是现有 v1 契约的兼容集合；
参考实现可用于追溯来源，但不再定义新需求。N1 若要调整分类，须先在 v2 字段契约中定稿并提供迁移映射。
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
| 重试后仍未通过 | `DEGRADED` | 2 或 3 |
| 上游、预算或缺 Reviewer 降级 | `DEGRADED` | 0 至 3 |
| 未执行校验 | `NOT_RUN` | 0 |

`analysis_sources` 是数组而非单值，因为组合场景是常态：查了数据并引用了口径返回
`["DATABASE", "KNOWLEDGE"]`。`ATTACHMENT` 仅为 v1 遗留枚举兼容值，本版不产生。

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
| `visualization` | `Visualization` | `METRIC` 必填；`DETAIL` 可选 |
| `recommendations` | `list[Recommendation]`（至少两条） | `METRIC`、要求分析的 `DETAIL`；纯明细必须为空列表 |

`metric_source`、`metric_owner`、`metric_status` 是 PRD 要求指标口径面板展示的三项，缺一前端就只能显示空白，因此列为 `METRIC` 必填。

**`metric_definition`（业务口径）与 `metric_sql_definition` 必须并列存在，不得合并为单一文本字段。**
参考项目的指标平台元数据表把它们分列为 `metrics_biz_meaning` / `metrics_sql_meaning`，
面向读者不同（见 PRD M8）。为兼容已保存的 `answers.response_payload`，业务口径继续使用
`metric_definition`；升级器只为历史 JSONB 补齐安全默认值，前端没有第二个业务口径入口。

`metric_source` 是三取一的枚举 `METRIC_CATALOG` / `FIELD_COMMENT` / `AI_GENERATED`，
对应 PRD M8 的受控指标资产来源层级，**不是自由文本**：前端要据此渲染来源徽标，
自由文本会让徽标映射退化成字符串匹配。中文标签由前端负责，后端只给枚举。

`metric_generated` 是独立布尔，不要让前端从 `metric_status == UNVERIFIED` 反推——
「模型生成的口径」和「目录里登记为待核验的口径」是两件事，可以同时成立也可以各自单独成立。

Pydantic 模型**不得**把按模式必填的字段设为无条件必填，否则 `CHAT` 等模式的正常响应会校验失败。正确做法是模型级校验器：按 `answer_mode` 分支检查，`METRIC` 缺 `metric_owner` 必须报错，`CHAT` 缺 `data_rows` 必须放行。

R9 补充约束：纯明细模式的 `answer` **必须是空字符串**且 `recommendations` 必须为空；要求分析的
`DETAIL` 与其他模式的 `answer` 必须非空，要求分析的 `DETAIL` 仍至少两条建议。违反者由
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
- `DETAIL` 缺 `export` 校验失败；纯明细非空正文或建议、分析型 DETAIL 缺两条建议均校验失败；
- `analysis_sources` 为空数组时校验失败；
- `CHAT`、`INVALID` 返回 `["NONE"]` 且 `degraded=false` 时校验通过；
- `NONE` 与其他来源共存时校验失败；
- 含 `FALLBACK` 但 `degraded=false` 时校验失败；
- `quality_attempts > 3` 时校验失败。

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

## 8.6 本地化 Header 与 Schema 契约

> **本节是 `Accept-Language` / `Content-Language` 请求响应头，以及 `ChatResponse`、
> `ConversationListResponse`、`ConversationDetailResponse`、`KnowledgeDocumentResponse`、
> `KnowledgeDocumentRequest`、`KnowledgeDocumentUpdateRequest`、`ExportSpec` 新增本地化字段的唯一权威定义。**
> 对应产品级语义见 `docs/PRD.md` C9、§10.6 与 §11.3，前端消费方式见 `docs/frontend-development-plan.md`
> §5.10。设计出处是 `plans/2026-08-31-full-stack-bilingual-localization.md` §1 与 §3.3；
> 后续实施任务（该计划的 Task 2–13）必须原样使用本节字段名，不得另起名字或改变失败语义。
> `SupportedLocale` 只允许 `zh-CN | en-US`；`SourceLanguage` 允许 `zh-CN | en-US | mixed | und`，
> 用于标注消息、回答、知识正文等内容本身使用的语言，与表达"界面显示语言"的 `SupportedLocale`
> 是两个不同的类型，不得混用。

### 8.6.1 请求与响应 Header

- 所有前端请求发送 `Accept-Language: zh-CN | en-US`；解析函数 `parse_accept_language()` 在
  Header 缺失时返回 `zh-CN`，只接受 `zh-CN`/`en-US` 及各自通用前缀（如 `en`、`en;q=0.9`）；
- 所有成功和错误响应都发送 `Content-Language`，值与本次请求解析出的 `SupportedLocale` 一致；
  可能因语言变化而不同的 GET 响应额外发送 `Vary: Accept-Language`；
- 错误响应仍使用稳定 `code`（见 §8.3、§14），展示 `message` 由统一异常处理器根据请求 locale 和
  受控 `message_params` 生成。业务异常、Pydantic validation、404、限流和 500 都不得把已有中文
  异常字符串直接放入英语响应；幂等失败只持久化 `code + message_params`，重放时按当前请求 locale
  重新渲染 `message`（与 §8.6.4 一致）；
- `ChatRequest` **不新增** `locale` 字段，避免请求体与 Header 出现两个事实源；显示语言只经
  `Accept-Language` 传递，路由层解析后显式向下传递，不在节点间读取原始 Request。

### 8.6.2 ChatResponse 新增字段

`ChatResponse` 的"始终必填"字段组（见 §8.2）新增：

| 字段 | 类型 | 可为 null | 说明 |
| --- | --- | --- | --- |
| `displayed_user_message` | `str` | 否 | 当前这一轮用户消息在目标语言下的显示副本 |

原始问题仍只存入 `messages.content`，不因翻译被覆盖；`ConversationDetailResponse.messages[].content`
（用户消息）与既有 `answer_payload` 承载的助手可读字段（正文、建议、思考步骤、质量说明、降级原因）
均始终是**请求语言下的显示内容**——API 不在英语响应中附带中文原文，反之亦然。

不新增与 R7 冲突的 Chat 降级字段：聊天翻译失败继续复用现有 `degraded`、`degraded_reason`、
`quality_status`、`quality_notes`，不引入第二套降级语义。

### 8.6.3 会话列表与详情：分页与按条目降级

会话历史条目量大——一个 40 条消息的会话还要拆出正文、建议、思考步骤、质量说明和图表标签，
几百个待翻译条目是常态；因此按可见页翻译，超限按条目降级，不整页失败：

- `GET /api/conversations/{conversation_id}` 增加消息游标分页：`message_limit` 默认 `20`、
  范围 `1–50`，`message_before` 为不透明游标；响应增加 `next_message_cursor: string | null`
  与 `has_more_messages: boolean`。第一页返回最新 20 条并在页内按时间正序排列，继续加载只获取
  更早一页；游标必须绑定可信 `merchant_id + conversation_id`，跨商家或跨会话复用返回稳定错误码；
- 会话列表与详情响应新增扁平字段 `localization_degraded: boolean` 与
  `localization_degraded_reason: string | null`（未降级时为 `false` / `null`），表达"本页有条目
  未能翻译"。未翻译条目返回目标语言占位文案（例如 `Translation unavailable — retry`），
  **不返回源语言正文**；对降级页使用同一游标重新 GET 即为重试，已缓存条目不重复调用模型；
- `LOCALIZATION_UNAVAILABLE`（见 §14）只用于知识库人工翻译保存这类**写路径**的硬失败，不用于
  会话列表/详情这类**读路径**——读路径永远用 `localization_degraded` + 占位文案表达部分失败，
  绝不整页失败。

### 8.6.4 `client_request_id` 幂等契约与 locale 的交互

在 §8.5 既有状态机基础上追加，三个分支语义**不因语言切换而改变**：

- `_request_digest()` 继续只散列 `message` 与 `attachment_ids`，**locale 不进入摘要**。相同
  `client_request_id` 在另一语言重放时复用同一份 Answer 事实，不重复查询经营数据、不重复生成答案；
- `SUCCEEDED` 才按**当前请求的 `Accept-Language`** 重新渲染 `displayed_user_message` 与 `answer`
  等显示字段返回；`FAILED_FINAL` 从持久化的稳定 `code + message_params` 按当前 locale 重建同一
  业务错误并渲染 `message`，**不持久化并重放旧语言整句**；
- `PROCESSING` 仍返回 `409 REQUEST_IN_PROGRESS`，**不重放**。正在处理中的那一轮，正确做法是让
  旧流在服务端跑完并落库，前端改为在目标语言下从 `GET /api/conversations/{id}` 读取该轮的本地化
  显示副本（见 §8.6.3），期间该条消息在目标语言下显示"生成中"占位，不渲染源语言正文。**不得为了
  支持切换语言而放宽 `PROCESSING` 分支**——那等于允许同一轮问答并发执行两次。

测试要求：使用同一失败 `client_request_id` 先中文、后英语重放，断言 `code` 相同、`message`
语言不同、业务执行次数仍为 1；`PROCESSING` 状态下换 `Accept-Language` 重放仍返回 `409`。

### 8.6.5 KnowledgeDocument 契约新增字段

- `KnowledgeDocumentResponse` 增加 `source_locale: SourceLanguage`、
  `content_locale: SupportedLocale` 和 `is_source_version: boolean`；`path` 仍是稳定 API 标识符，
  不翻译；
- `KnowledgeDocumentRequest`（对应 `POST /api/admin/knowledge/documents`）增加可选
  `source_locale: SourceLanguage`，缺失时后端用 `detect_source_language()` 检测并持久化；
- `KnowledgeDocumentUpdateRequest`（对应 `PUT /api/admin/knowledge/documents/{id}`）增加
  `is_source_version: boolean` 与 `content_locale: SupportedLocale | null`：
  - `is_source_version=true` 时只更新事实源正文并重新检测语言；
  - 为 `false` 时 `content_locale` 必填，按资源 ID/字段/源版本保存人工译文；
  - **不允许靠"`content_locale` 是否等于 `source_locale`"猜测写入目标**，因为源内容可能是
    `mixed`/`und`。

### 8.6.6 导出与签名

- `/api/exports/{id}` 是签名 URL、浏览器直接下载，**没有 `Accept-Language`**（沿用 §8.0
  "导出下载为什么不带 Bearer"的同一约束）。导出语言因此必须在创建导出、生成签名时固化：内部
  `ExportSpec` 增加 `locale: SupportedLocale` 字段并纳入签名，下载时按 spec 的 `locale` 渲染
  列名与自由文本，并回 `Content-Language`；
- 同一份数据的中英文导出是**两个独立签名**，互不复用；旧签名不带 `locale` 时按 `zh-CN` 解释，
  保持既有链接可用（向后兼容，不使已发出的旧签名失效）。

### 8.6.7 知识索引状态（N4-C，PRD M12、§7.6）

不新增端点：`GET /api/admin/knowledge/tree` 的 `KnowledgeTreeResponse` 增加**必填**字段
`index_status: KnowledgeIndexStatus`（管理员与只读令牌均可读，不含分块正文、向量或异常原文）：

| 字段 | 类型 | 必填 | 可空 | 说明 |
| --- | --- | --- | --- | --- |
| `retrieval_mode` | `HYBRID` / `KEYWORD_ONLY` | 是 | 否 | 有生效版本且其模型与当前配置的嵌入模型一致时为 `HYBRID`；否则 `search_rules` 只用关键词并在来源上标注降级 |
| `active_version` | integer | 是 | 是 | 生效索引版本号；从未成功构建时为 null |
| `embedding_model` | string | 是 | 是 | 生效版本使用的嵌入模型标识 |
| `configured_model` | string | 是 | 是 | 当前进程配置的嵌入模型（`EMBEDDING_MODEL`）；未配置时为 null |
| `stale` | boolean | 是 | 否 | 生效版本落后于语料（最近一次构建失败，或文档已改而新版本未生效） |
| `stale_reason` | `BUILD_FAILED` / `CORPUS_CHANGED` | 是 | 是 | 与 `stale` 成对：`stale=false` 时必须为 null，`true` 时必须非 null |
| `building` | boolean | 是 | 否 | 是否有版本处于构建中/验证中（同一时刻至多一个） |
| `last_failure_reason` | `EMBEDDING_UNAVAILABLE` / `EMBEDDING_FAILED` / `QUALITY_REGRESSION` / `EMPTY_CORPUS` / `BUILD_TIMEOUT` / `BUILD_ABORTED` / `STORAGE_FAILED` | 是 | 是 | 生效版本之后最近一次失败构建的稳定原因码；没有则 null |

写入语义：文档创建、源正文更新、删除，以及业务域创建/改名/删除，**在同一事务内**把生效索引标为
`CORPUS_CHANGED` 陈旧；提交后在进程内后台触发重建（构建期间旧版本继续服务，不原地改分块）。
人工译文（`is_source_version=false`）不进入索引，不触发重建。切换时若语料指纹已与该版本不一致
（构建期间又有保存），切换后仍保持陈旧并再构建一轮。

Chat 侧（v2 商家）：本回合调用过 `search_rules` 时 `analysis_sources` 含 `KNOWLEDGE` 项；向量索引
不可用时该项 `degraded=true`、`degraded_reason="INDEX_UNAVAILABLE_KEYWORD_FALLBACK"`，陈旧时为
`"INDEX_STALE"`；单来源降级不使整轮 `degraded=true`（§8.7.6）。

---

## 8.7 v2 共用契约组件

本节定义无路由共用模型。全部模型拒绝未声明字段；表中的“必填”指输入键必须存在，
“可空”指允许 JSON null，两者独立。字符串未列长度限制时不另设上限。
共用模型不执行鉴权、游标签名、幂等持久化或证据消费；这些由后续路由与领域服务实现。

| 模型 / 字段 | 类型 | 必填 | 可空 | 范围、默认值与说明 |
| --- | --- | --- | --- | --- |
| `CursorPageRequest.cursor` | string | 否 | 是 | 默认 null；提供时长度 1–2048；不透明游标，签名校验由服务层执行 |
| `CursorPageRequest.limit` | integer | 否 | 否 | 1–100，默认 20 |
| `CursorPage[T].items` | T[] | 是 | 否 | 本页条目，允许空数组 |
| `CursorPage[T].next_cursor` | string | 是 | 是 | 最后一页为 null；非空时长度 1–2048 |
| `CursorPage[T].has_more` | boolean | 是 | 否 | 是否存在下一页；必须等于 `next_cursor` 非空（执行期裁定 E10） |
| `IdempotentWriteRequest.client_request_id` | string | 是 | 否 | 1–128 个 ASCII 字符；首字符为字母或数字，后续仅允许字母、数字、`.`、`_`、`:`、`-`；适用端点见 §8.7.3 |
| `MoneyCents` | integer | — | 否 | 严格整数，0–99999999999999 分；不接受布尔、字符串或小数 |

`yuan_to_cents` 只接受范围内的有限 Decimal 元，`cents_to_yuan` 只接受范围内的整数分；
非法类型、负值、非有限值及超上界值拒绝转换。舍入规则见 §8.7.8。

### 8.7.1 会话与角色

顾客与商家会话端点使用请求头 `X-Session-Id: <session id>` 传递会话凭证；
公开端点不需要此头；创建商家会话使用演示 Bearer Token（AGENTS.md §8.3）；MCP 只接受独立的 `Authorization: Bearer <MCP access token>`，
不得接受 `X-Session-Id`（见 §8.14）。会话记录包含
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

### 8.7.2 错误信封与新增错误码

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

### 8.7.3 幂等写契约与适用白名单

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
| `POST /shop/after-sales/{id}/supplements` | | |

白名单之外的端点**不得**声明 `client_request_id`；白名单之内的**必须**声明。

两个 Chat 端点沿用 §8.5 聊天重试幂等（五种状态分支、并发重复提交只产生一次 LLM 调用、断开后凭 ID
取回、预算耗尽/限流为 `FAILED_RETRYABLE` 且重试不调用 LLM）与 §8.6.4 的 locale 重放规则，但：

- 唯一域按本节五元组，承载于 `idempotency_records`；**不复用** v1 `answers(merchant_id, client_request_id)`
  索引，否则同店不同顾客会互相冲突；
- `request_digest` 取规范化后的 `message` 与 `conversation_id`；v2 无附件字段，摘要不含 `attachment_ids`。

（2026-09-21 执行核对补全：原白名单漏列 Chat，与 Task 2 不变量 3 冲突。）
新增 v2 写端点时同步更新本表。

### 8.7.4 游标分页

v2 列表端点一律游标分页，不提供 offset（裁定 A4）。**这是新约定**：v1 会话列表用的是
`limit + offset`，只有会话详情的消息用游标，两者不构成先例。

请求：`cursor: str | null`（省略表示首页）、`limit: int`（1–100，默认 20）。
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

### 8.7.5 v2 SSE 事件契约

`step` 复用 `ThinkingStep`：`label` 为 1–120 字符，`node` 匹配
`^[a-z][a-z0-9_]{0,63}$`；均必填且不可空。以下工具展示模型全部拒绝额外字段，
不提供接收原始参数或原始结果的扩展字典。`summary` 只允许下列固定短句；
工具参数、结果、模型文本不得直接填入。日后需要动态业务摘要时，须先定义受控投影、脱敏规则和反例测试，
再扩充契约。显示语言由路由选择对应短句。

| 字段 | 闭集 |
| --- | --- |
| `status` | `STARTED` / `RUNNING` / `SUCCEEDED` / `DEGRADED` / `FAILED` / `UNAVAILABLE` |
| `summary` | `正在处理` / `处理完成` / `暂时不可用` / `处理失败`，及对应英语 `Processing` / `Completed` / `Unavailable` / `Failed` |

| 模型 / 字段 | 类型 | 必填 | 可空 | 说明 |
| --- | --- | --- | --- | --- |
| `ToolCallDisplay.tool_name` | string | 是 | 否 | 匹配 `^[a-z][a-z0-9_]{0,63}$`；具体工具名仍须由注册表白名单验证 |
| `ToolCallDisplay.call_id` | string | 是 | 否 | 匹配 `^[A-Za-z0-9_-]{1,64}$` |
| `ToolCallDisplay.status` | ToolDisplayStatus | 是 | 否 | 上述状态闭集 |
| `ToolCallDisplay.summary` | PublicToolSummary | 是 | 否 | 上述双语固定短句，不接受任意正文 |
| `ToolResultDisplay.call_id` | string | 是 | 否 | 匹配 `^[A-Za-z0-9_-]{1,64}$` |
| `ToolResultDisplay.status` | ToolDisplayStatus | 是 | 否 | 上述状态闭集 |
| `ToolResultDisplay.duration_ms` | integer | 是 | 否 | ≥0，单位毫秒 |
| `ToolResultDisplay.row_count` | integer | 是 | 是 | ≥0；不适用时为 null |
| `ToolResultDisplay.summary` | PublicToolSummary | 是 | 否 | 上述双语固定短句，不接受任意正文 |

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

### 8.7.6 降级披露字段

| 模型 / 字段 | 类型 | 必填 | 可空 | 范围、默认值与说明 |
| --- | --- | --- | --- | --- |
| `AnalysisSourceEntry.source` | AnalysisSource | 是 | 否 | DATABASE / KNOWLEDGE / MEMORY / FALLBACK / NONE；拒绝 ATTACHMENT |
| `AnalysisSourceEntry.degraded` | boolean | 是 | 否 | 本来源是否降级 |
| `AnalysisSourceEntry.degraded_reason` | string | 是 | 是 | 降级时非空且不能只有空白；未降级时必须 null |
| `DegradationMixin.analysis_sources` | AnalysisSourceEntry[] | 是 | 否 | 至少一项，主来源在前；NONE 必须独占 |
| `DegradationMixin.thinking_steps` | ThinkingStep[] | 否 | 否 | 默认 []，字段限制见 §8.7.5 |
| `DegradationMixin.quality_status` | QualityStatus | 是 | 否 | PASSED / DEGRADED / FAILED / NOT_RUN |
| `DegradationMixin.quality_attempts` | integer | 是 | 否 | 0–3 |
| `DegradationMixin.quality_notes` | string[] | 否 | 否 | 默认 [] |
| `DegradationMixin.degraded` | boolean | 是 | 否 | 整轮是否降级 |
| `DegradationMixin.degraded_reason` | string | 是 | 是 | 与整轮降级标识成对，规则同来源原因 |

R7 的六个字段在 v2 保持同名：`analysis_sources`、`thinking_steps`、`quality_status`、
`quality_notes`、`degraded`、`degraded_reason`。v2 新增区分**整轮降级与单来源降级**（PRD §11.3）：
`analysis_sources` 的每个元素从字符串升为对象 `{ source, degraded, degraded_reason }`，
顶层 `degraded` 表示整轮是否降级。**顶层 `degraded=false` 时允许存在单个来源 `degraded=true`。**
`source` 使用现有 `app.schemas.chat.AnalysisSource` 成员构成的 v2 字面值子集，
使运行时校验与 OpenAPI 都不包含已移出本版的 `ATTACHMENT`；
`NONE` 只能单独出现。单来源 `degraded=true` 时该元素的 `degraded_reason` 必须为非空字符串，
否则必须为 `null`。顶层也遵守同一成对规则：`degraded=true` 必须给出非空原因，`false` 必须为 `null`。
`FALLBACK` 来源自身及顶层都必须标记 `degraded=true` 并给出原因；不得以 `PASSED` 的未降级结果展示规则兜底。

### 8.7.7 `session_id` 与 `conversation_id` 的命名冻结

`V2ChatResponseBase` 继承全部降级字段，并增加以下必填、不可空字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | string | 回答标识 |
| `conversation_id` | string | 业务对话标识 |
| `answer` | string | 当前显示语言下的回答正文 |
| `tool_calls` | ToolCallDisplay[] | 脱敏调用摘要，无调用时为 [] |
| `created_at` | datetime | 带时区 ISO 8601；拒绝无时区值，归一化至 UTC 输出 |

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

### 8.7.8 金额表示与转换

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

### 8.7.9 界面操作证据的通用语义

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

### 8.7.10 猜你想问（PRD M13，2026-09-24 补入）

`V2ChatResponseBase` 增加两个**可选**字段，两端 Chat 响应与对话详情中的 `answer` 共用：

| 字段 | 类型 | 必填 | 可空 | 范围、默认值与说明 |
| --- | --- | --- | --- | --- |
| `suggestions` | string[] | 否 | 否 | 默认 `[]`；至多 3 条，每条 1–200 字符；当前一组推荐问题 |
| `suggestion_alternates` | string[][] | 否 | 否 | 默认 `[]`；至多 5 组，每组 1–3 条；供「换一换」本地轮换 |

约束：

- 备选组不得与当前组逐条相同；**没有当前组时不得出现备选组**；
- 候选**全部由后端生成**，与 v1 `suggestions` 同名同形，但候选内容按会话角色分开：
  顾客端只含顾客工具面（`search_products` / `get_product` / `get_shop_policy` / `set_cart_item`）答得了的问题，
  商家端只含商家工具面答得了的问题，两端候选互不相交；
- 订单与售后问题在 N2 由页面而不是对话回答，对话里没有对应工具，**不进候选**；N3 补上对应工具再加；
- 语言随 `Accept-Language`，文案是人工维护的固定词典，不经 LLM 也不经本地化缓存；
- 模型只允许对候选**排序**：排序后的问题必须仍属于本角色的候选集合、条数一致且互不重复，
  否则回退原候选（`constrain_rewrite`）。N2 尚未把任何模型接到该环节，因此不增加每轮的 LLM 调用；
- 字段带默认值，落盘在 `messages.response_payload` 里、本字段上线前写入的回答仍能读回；
- 降级回答照常给候选，**降级字段不因此改变**（R7）。

### 8.7.11 图表可视化（PRD M3，2026-09-27 补入）

`MerchantChatResponse` 增加一个**可选**字段：

| 字段 | 类型 | 必填 | 可空 | 范围、默认值与说明 |
| --- | --- | --- | --- | --- |
| `visualization` | `Visualization` | 否 | 否 | 默认 `enabled=false`；本回合是否有可画的指标结果，及数据点本身 |

`Visualization` 复用 v1 已冻结的模型（`app.schemas.chat.Visualization`/`ChartType`），
不新定义第二套形状——v1/v2 并存不互相 import 业务逻辑（§5.6），但共用类型定义已有先例
（`AnalysisSource`/`QualityStatus`/`ThinkingStep`，§8.7.1 起），图表模型属于同一类：

```python
class ChartType(StrEnum):
    LINE = "LINE"
    BAR = "BAR"
    PIE = "PIE"

class Visualization(BaseModel):
    enabled: bool
    type: ChartType | None = None
    allowed_types: list[ChartType] = Field(default_factory=list)
    title: str | None = None
    dimension_key: str | None = None
    metric_key: str | None = None
    unit: str | None = None
    data: list[dict[str, str | int | float | None]] = Field(default_factory=list)
```

约束（与 M3「图表数据点由后端生成」「只允许在后端声明的兼容图表类型之间切换」一致）：

- **只有本回合调用了 `query_metrics` 或 `attribute_change` 且返回的 `MetricQueryResult`/
  `AttributionResult` 带有可画的时间序列或分类构成时才 `enabled=true`**；纯文字问答、
  规则问答（`search_rules`/`get_metric_definition`）、导出、草稿起草等回合恒为
  `enabled=false`；同一回合调用多个指标工具时，只取**最后一次**成功的指标查询结果
  （与 `answer` 正文引用的数字保持同一个来源，不让图表和文字对不上）；
- `data` 的每一行只能包含 `dimension_key`/`metric_key` 两个键对应的值，值只能来自
  `MetricQueryResult`/`AttributionResult` 已经算好的数值——**Agent/LLM 不经手这份数据**，
  工具循环内部直接从服务层结果构造 `Visualization`，模型只在 `tool_calls` 摘要里看到
  行数，看不到 `visualization.data` 本身（与 `ToolDisplay.payload` 永不进 SSE 同一原则）；
  复用 `app/services/visualization_service.py` 的既有构造逻辑，不重写一套新的映射规则；
- `type` 与 `allowed_types` 的取值规则复用 M3 既有约束：时间维度（`dimension_key == "date"`）
  默认折线图、只允许折线图；分类维度默认柱状图、允许柱状图或饼图；前端只能在
  `allowed_types` 内切换，不能凭空选择契约未声明的图表类型；
- 字段带默认值，落盘在 `messages.response_payload` 里、本字段上线前写入的历史回答
  读回时得到默认值 `enabled=false`，不回填历史数据（不伪造历史图表）；
- 降级回答（`degraded=true`）时 `visualization.enabled` 必须为 `false`——降级意味着
  本回合至少一个数据来源不可信，绝不能仍然展示一份看似正常的图表（同 R7 底线）。

---

### 8.8 顾客会话与店铺浏览（组 1）

本节为 N1 纯模型契约，不挂载路由；其中 3 条会话签发路由由 N1 会话计划 Task 7 挂载（2026-09-21 裁定），其余路由归 N2。全部请求、响应模型拒绝额外字段。
身份只从凭证解析，响应不返回 `merchant_id`、`buyer_key` 或精确库存。
`Accept-Language` 沿用 §8.6；时间必填时必须带时区并归一化 UTC。

#### 8.8.1 基础字段与模型

下表的字段全部必填且不可空，除非明确标注默认值或可空；字符串长度按字符计算。
`PublicId` 为 1–128 字符的非空标识，`shop_slug` 为 1–64 字符，匹配 `[a-z0-9]+(?:-[a-z0-9]+)*`。
`session_id` 是至少 43、至多 128 字符的无前缀 base64url 凭证，不接受 UUID 代替。
模型中的价格全部用 §8.7.8 的非负整数分，不接受 float 或 bool。

| 模型 | 字段、类型与范围 |
| --- | --- |
| `ShopSessionCreateRequest` | `shop_slug: string`，规则如上 |
| `ShopSessionCreateResponse` | `session_id: string`；`role: CUSTOMER`；`expires_at: UTC datetime` |
| `DemoCustomerBindRequest` | 空对象 `{}`，不接受任何身份或幂等键字段 |
| `DemoCustomerBindResponse` | `role: CUSTOMER`；`is_bound: true`；`expires_at: UTC datetime`；`cart_adjusted: bool`（严格布尔；合并时发生数量截顶、剔除不可售商品或超 50 行截断为 true，幂等重绑不再合并恒为 false；规则见 PRD C3，执行期裁定 E9）。原凭证保持有效，不再次返回凭证 |
| `StoreProfileResponse` | `shop_slug: string`；`display_name: string[1..120]`；`rules_summary: string[0..10000]` |
| `StockBand` | `IN_STOCK / LOW_STOCK / OUT_OF_STOCK` |
| `ProductSummary` | `id: PublicId`；`name: string[1..200]`；`short_description: string[0..500]`；`price_cents: MoneyCents`；`stock_band: StockBand`；`image_url: string[1..2048]或null`；`source_locale: zh-CN / en-US / mixed / und`；`content_version: int≥1`；`requested_locale: zh-CN / en-US`；`name_translation_status / short_description_translation_status: SOURCE / MACHINE / FALLBACK`；`category: string[1..64]`（商品类目的**源值**，如“鞋靴”；不翻译，前端用固定词表显示，词表未登记的类目原样显示；WS 2026-09-30 为商品浮层与缺图占位加入） |
| `ProductAttribute` | `name: string[1..100]`；`value: string[1..2000]`；`source: MERCHANT / DEMO`；`updated_at: UTC datetime`；`name_translation_status / value_translation_status: SOURCE / MACHINE / FALLBACK` |
| `ProductDetailResponse` | ProductSummary 全部字段；`description: string[0..20000]`；`attributes: ProductAttribute[]`（0–100 项）；`description_translation_status: SOURCE / MACHINE / FALLBACK`；`missing_attributes: string[]`（0–20 项，该类目在 `REQUIRED_ATTRIBUTES_BY_CATEGORY` 中的必填属性里缺失或值为空的源属性名，按名称升序；类目未登记时为空数组，不翻译） |

商品公开列表与详情按 `Accept-Language` 选择 `requested_locale`。`source_locale` 与 `content_version`
来自当前商品源记录，译文逐字段按当前源文本哈希从**本商家**未过期的机器译文缓存读取；商品字段更新后，
旧哈希立即不再命中。超出目标字段长度或内容为空的缓存译文也视为未命中。公开 GET 只读缓存，绝不触发 LLM 或写入新译文。`SOURCE` 表示源语言与请求
语言一致，或字段只是数字、单位、编码等无需翻译的内容；`MACHINE` 表示命中机器译文，页面须显式
标注；`FALLBACK` 表示缺少可用译文并原样显示源文，页面须显式提示。属性的 `source: MERCHANT /
DEMO` 仍表示**业务内容来源**，与翻译状态独立，不得把 `MACHINE` 译文标作商家原文。
| `CouponSummary` | `id: PublicId`；`name: string[1..200]`；`kind: AMOUNT_OFF / PERCENT_OFF`；`min_spend_cents: MoneyCents`；`amount_off_cents: MoneyCents或null`；`discount_bps: int[1..9999]或null`（折扣后的支付比例，单位基点）；`product_ids: PublicId[]`（0–100 项，空表示全店）；`starts_at / ends_at: UTC datetime` |
| `ShopChatRequest` | `message: string[1..2000]`（strip 后非空）；`conversation_id: PublicId或null`（可省略，默认null）；`client_request_id` 按 §8.7.3，必填 |
| `ShopAnswerMode` | `SHOP_GUIDE / ORDER / AFTER_SALE / CHAT / INVALID` |
| `ShopChatResponse` | §8.7.7 `V2ChatResponseBase` 的全部字段；`answer_mode: ShopAnswerMode` |
| `ShopConversationSummary` | `id: PublicId`；`title: string[1..200]`；`created_at / updated_at: UTC datetime` |
| `ShopConversationMessage` | `id: PublicId`；`role: user / assistant`；`content: string[1..20000]`；`created_at: UTC datetime`；`answer: ShopChatResponse或null`（user 必须null；assistant 必須包含最终响应） |
| `ShopConversationDetailResponse` | `conversation: ShopConversationSummary`；`messages: CursorPage[ShopConversationMessage]` |

优惠券 `ends_at > starts_at`；满减券 `amount_off_cents>0` 且 `discount_bps=null`；折扣券
`amount_off_cents=null` 且 `discount_bps` 必填。商品属性名、券的商品标识不得重复。
商品与购物车图片共用 `ImageUrl` 结构校验，仅接受 `/demo/products/` 下无查询串、片段、路径跳转或编码逃逸的静态资源路径，
或显式受信配置允许的 HTTPS 主机（不接受用户信息、非443端口、IP地址）。HTTPS 主机白名单**不在 Schema 内判定**：Schema 只做与部署无关的结构校验，
主机是否可信由服务层在入库或组装响应前调用 `is_trusted_image_host(url, allowed_hosts)` 判定；该函数也先执行同一结构校验，不能只按主机名放行不安全地址。缺配置时拒绝全部外部主机，Schema 不联网抓图。
（原写法依赖 Pydantic 校验 context，但 FastAPI 校验 `response_model` 时不传 context，会让所有外部图片在响应阶段 500；执行期裁定 E11。）
`CHAT / INVALID` 的回答来源必须是单独的 `NONE`；其余模式仍遵守共用降级约束。
历史 user 消息不带回答；assistant 消息须携带完整最终响应且 content 与 answer.answer 一致。

#### 8.8.2 逐路径契约

下表的“无”表示不接受请求体或该类参数；列表参数统一为 `cursor: string[1..2048]或null`（默认null）、
`limit: int[1..100]`（默认20），响应 `CursorPage` 的三字段按 §8.7.4 全部必填。
所有错误返回 §8.3 ErrorResponse。表中的 401 为 `SESSION_REQUIRED / SESSION_INVALID`，
403 角色错误为 `SESSION_ROLE_MISMATCH`；资源不存在与越权统一 `RESOURCE_FORBIDDEN`、空 details。
本节沿用的既有错误 `INVALID_REQUEST`（422）、`NOT_FOUND`（404）、`INTERNAL_ERROR`（500）
与 §8.7.2 已列共用码使用同一 ErrorCode；不另建枚举。

| 方法与完整路径 | 鉴权、路径/查询/请求体 | 成功响应 | 错误、幂等与传输 |
| --- | --- | --- | --- |
| `POST /api/v2/shop/sessions` | 公开；路径/查询无；体 ShopSessionCreateRequest | 201 ShopSessionCreateResponse，Cache-Control: no-store | 403 RESOURCE_FORBIDDEN（店铺不可用）；422 INVALID_REQUEST；429 RATE_LIMITED；503 DATA_SOURCE_UNAVAILABLE。每次签发新凭证，无client_request_id |
| `POST /api/v2/shop/sessions/demo-customer` | X-Session-Id 顾客；路径/查询无；体 DemoCustomerBindRequest | 200 DemoCustomerBindResponse，Cache-Control: no-store | 401；403角色错误；404 NOT_FOUND（演示模式关闭，统一公开不可用）；409 SESSION_ALREADY_BOUND；422 INVALID_REQUEST；503 DATA_SOURCE_UNAVAILABLE。同一身份原地绑定与购物车合并事务幂等，无client_request_id |
| `DELETE /api/v2/shop/sessions/current` | X-Session-Id 顾客；路径/查询/体无 | 204，无体 | 401；403角色错误；503 DATA_SOURCE_UNAVAILABLE。注销当前会话；后续用该凭证返回401，无client_request_id |
| `GET /api/v2/shop/stores/{shop_slug}` | 公开；路径shop_slug；查询/体无 | 200 StoreProfileResponse | 403 RESOURCE_FORBIDDEN；422 INVALID_REQUEST；503 DATA_SOURCE_UNAVAILABLE。只读，无幂等键 |
| `GET /api/v2/shop/stores/{shop_slug}/products` | 公开；路径shop_slug；查询cursor/limit/sort；`sort: newest / popular`，默认 `newest`；体无 | 200 CursorPage[ProductSummary] | 403 RESOURCE_FORBIDDEN；422 INVALID_REQUEST / INVALID_CURSOR；503 DATA_SOURCE_UNAVAILABLE。只返回在售商品；只读 |
| `GET /api/v2/shop/stores/{shop_slug}/products/{product_id}` | 公开；路径shop_slug、product_id:PublicId；查询/体无 | 200 ProductDetailResponse | 403 RESOURCE_FORBIDDEN（含非本店或不可售）；422 INVALID_REQUEST；503 DATA_SOURCE_UNAVAILABLE。只读 |
| `GET /api/v2/shop/stores/{shop_slug}/coupons` | 公开；路径shop_slug；查询cursor/limit；体无 | 200 CursorPage[CouponSummary] | 403 RESOURCE_FORBIDDEN；422 INVALID_REQUEST / INVALID_CURSOR；503 DATA_SOURCE_UNAVAILABLE。仅当前已生效券（starts_at≤now<ends_at）；只读 |
| `POST /api/v2/shop/chat` | X-Session-Id 顾客；路径/查询无；体ShopChatRequest | 200 SSE 或 ShopChatResponse | 401；403角色错误 / RESOURCE_FORBIDDEN；409 IDEMPOTENCY_KEY_REUSED / REQUEST_IN_PROGRESS；422 INVALID_REQUEST；429 RATE_LIMITED；503 LLM_BUDGET_EXCEEDED / DATA_SOURCE_UNAVAILABLE。幂等域、摘要与语言重放按 §8.7.3；默认SSE |
| `GET /api/v2/shop/conversations` | X-Session-Id 顾客；路径无；查询cursor/limit；体无 | 200 CursorPage[ShopConversationSummary] | 401；403角色错误；422 INVALID_REQUEST / INVALID_CURSOR；503 DATA_SOURCE_UNAVAILABLE。仅当前主体本店对话；只读 |
| `GET /api/v2/shop/conversations/{conversation_id}` | X-Session-Id 顾客；路径conversation_id:PublicId；查询cursor/limit用于消息；体无 | 200 ShopConversationDetailResponse | 401；403角色错误 / RESOURCE_FORBIDDEN；422 INVALID_REQUEST / INVALID_CURSOR；503 DATA_SOURCE_UNAVAILABLE。只读 |
| `DELETE /api/v2/shop/conversations/{conversation_id}` | X-Session-Id 顾客；路径conversation_id:PublicId；查询/体无 | 204，无体 | 401；403角色错误 / RESOURCE_FORBIDDEN；422 INVALID_REQUEST；503 DATA_SOURCE_UNAVAILABLE。删除后再次请求统一403；同事务删除来源状态，无client_request_id |

所有受限对象查询强制当前主体 + 店铺范围；公开浏览按 slug 在服务端解析店铺，不让前端提供租户ID。
列表排序：商品 `newest` 为 `created_at DESC, id DESC`；`popular` 为近 30 个业务日（Asia/Shanghai）已支付订单件数 DESC，并列 `created_at DESC, id DESC`；优惠券、对话均 `created_at DESC, id DESC`；消息 `created_at ASC, id ASC`。
签名游标绑定端点、公开店铺或会话主体+店铺、资源类型、语言与limit；商品游标额外绑定 `sort`，换 `sort` 复用游标返回 422 `INVALID_CURSOR`；消息还绑定conversation_id。
签名、24小时过期、锚点删除与从首页重取规则严格沿用 §8.7.4，不跨资源复用。

#### 8.8.3 Chat 与 v1 迁移

SSE 逐事件使用 §8.7.5 的 `step / tool_call / tool_result / turn_complete / error`；
turn_complete 携带唯一完整 ShopChatResponse，和 JSON 响应逐字段相同，工具载荷只能用受控展示模型。
开流前错误保留HTTP状态；开流后error为唯一终态，不再发送turn_complete；断流不得当成功。
切换语言重放按 §8.6.4，不重复推理或产生副作用。请求拒绝 session_id、attachment_ids 和身份字段。

**多轮历史回放**（2026-09-28 用户裁定 D-N4-1，PRD A5）：服务端按 `conversation_id` 读取同一会话最近
`CHAT_HISTORY_MAX_TURNS` 轮（默认 6）的用户与助手文字作为模型上下文；顾客历史消息按 A11 围栏；
不回放工具结果与推理内容；已删除会话不回放；**客户端不能提交历史**，请求体不新增字段，历史只由服务端从已落库消息读取。
回放的助手文字不是事实来源（§6.12）。

**顾客只读订单工具 `get_my_order`**：模型参数仅 `order_id: string[1..128]`，拒绝额外字段；结果包含 `payment_status`、`fulfillment_status`、`after_sale_status`、`pay_by`、`items[{name, quantity}]`、`recent_events[{event_type, occurred_at}]`（最多 5 条，按时间升序）。与 `check_after_sale_eligibility` 使用相同的 `merchant_id + buyer_key` 归属过滤，访客不可用；归属失败抛 `FatalToolError(gate="ownership")`。写策略为 `READ_ONLY`，可并行。`tool_call` / `tool_result` 展示摘要只含状态文字，不含 `buyer_key` 等内部字段。

| v1 AnswerMode | 顾客端处理 |
| --- | --- |
| CHAT / INVALID | 同名映射 |
| METRIC / DETAIL / RULE / IDENTITY | 不自动映射；由顾客请求语义选择 SHOP_GUIDE / ORDER / AFTER_SALE，商家能力不得透传 |
| ATTACHMENT | 拒绝，本版无附件能力 |

### 8.9 商家会话与对话目录（组 2）

本节为 N1 纯模型契约，不挂载路由；其中 2 条会话签发路由由 N1 会话计划 Task 7 挂载（2026-09-21 裁定），其余路由归 N2。全部请求、响应模型拒绝额外字段。身份只从凭证解析，
响应不返回 `merchant_id`。`Accept-Language` 沿用 §8.6；时间带时区并归一化 UTC。
`PublicId`、`SessionToken` 与 §8.8.1 定义相同；本节不引用顾客端模块（两端只共享 `common.py`）。

#### 8.9.1 基础字段与模型

| 模型 | 字段、类型与范围 |
| --- | --- |
| `MerchantSessionCreateRequest` | 空对象 `{}`；身份只来自 `Authorization: Bearer <演示 Token>`，不接受 `merchant_id` 等任何字段 |
| `MerchantSessionCreateResponse` | `session_id: string`（43–128 字符 base64url 凭证）；`role: MERCHANT`；`expires_at: UTC datetime`；`merchant_display_name: string[1..120]`；`shop_slug: string`（2026-10-02 增补，D-N5-4：本商家顾客端店铺标识，规则同 §8.8.1 `ShopSlug`，取值即该商家的 `merchant_code`；只供商家端「顾客视角」拼接新标签链接，后端从已验证会话的 `merchant_id` 解析，不接受请求传入。约束由 `common.py` 共享，商家模块不引用顾客端模块） |
| `MerchantChatRequest` | `message: string[1..2000]`（strip 后非空）；`conversation_id: PublicId或null`（可省略，默认null）；`client_request_id` 按 §8.7.3，必填 |
| `MerchantAnswerMode` | `METRIC / DETAIL / RULE / IDENTITY / CHAT / INVALID`，无 `ATTACHMENT` |
| `MerchantChatResponse` | §8.7.7 `V2ChatResponseBase` 的全部字段；`answer_mode: MerchantAnswerMode` |
| `MerchantConversationSummary` | `id: PublicId`；`title: string[1..200]`；`created_at / updated_at: UTC datetime` |
| `MerchantConversationFeedbackState` | `adopted: bool`；`reaction: FeedbackReaction或null`；`reason: string[1..500]或null`，原因只可附着于非空赞踩；无反馈记录时返回 `false / null / null` |
| `MerchantConversationMessage` | `id: PublicId`；`role: user / assistant`；`content: string[1..20000]`；`created_at: UTC datetime`；`answer: MerchantChatResponse或null`；`feedback: MerchantConversationFeedbackState或null`（user 的 answer、feedback 均必须为null；assistant 必须携带最终响应和非空 feedback，且 content 与 answer.answer 一致） |
| `MerchantConversationDetailResponse` | `conversation: MerchantConversationSummary`；`messages: CursorPage[MerchantConversationMessage]` |

`CHAT / INVALID` 的回答来源必须是单独的 `NONE`；其余模式遵守共用降级约束。
顾客的店铺级脱敏别名 `buyer_alias` 只在商家售后契约（§8.11）中出现；对话目录本身不含任何顾客标识，
因此两端目录摘要字段完全对称，且都不含 `merchant_id` / `buyer_key`。
详情只对本店商家会话返回回答反馈；按当前消息页的回答 ID 与服务端解析的 `merchant_id` 批量读取反馈，
不得信任请求中的商家标识，也不得把同店顾客回答或其他商家的反馈混入结果。顾客会话详情契约不增加此字段。

#### 8.9.2 逐路径契约

列表参数统一为 `cursor: string[1..2048]或null`（默认null）、`limit: int[1..100]`（默认20）；
错误沿用 §8.3 ErrorResponse。401 为 `SESSION_REQUIRED / SESSION_INVALID`，
403 角色错误为 `SESSION_ROLE_MISMATCH`，资源不存在与越权统一 `RESOURCE_FORBIDDEN`、空 details。

| 方法与完整路径 | 鉴权、路径/查询/请求体 | 成功响应 | 错误、幂等与传输 |
| --- | --- | --- | --- |
| `POST /api/v2/merchant/sessions` | `Authorization: Bearer <演示 Token>`（唯一使用 Bearer 的 v2 商家端点）；路径/查询无；体 MerchantSessionCreateRequest | 201 MerchantSessionCreateResponse，Cache-Control: no-store | 401 AUTH_REQUIRED（Token 缺失、无效或已撤销）；422 INVALID_REQUEST；429 RATE_LIMITED；503 DATA_SOURCE_UNAVAILABLE。每次签发新凭证，无client_request_id |
| `DELETE /api/v2/merchant/sessions/current` | X-Session-Id 商家；路径/查询/体无 | 204，无体 | 401；403角色错误；503 DATA_SOURCE_UNAVAILABLE。后续用该凭证返回401，无client_request_id |
| `POST /api/v2/merchant/chat` | X-Session-Id 商家；路径/查询无；体MerchantChatRequest | 200 SSE 或 MerchantChatResponse | 401；403角色错误 / RESOURCE_FORBIDDEN；409 IDEMPOTENCY_KEY_REUSED / REQUEST_IN_PROGRESS；422 INVALID_REQUEST；429 RATE_LIMITED；503 LLM_BUDGET_EXCEEDED / DATA_SOURCE_UNAVAILABLE。幂等域、摘要与语言重放按 §8.7.3；默认SSE |
| `GET /api/v2/merchant/conversations` | X-Session-Id 商家；路径无；查询cursor/limit；体无 | 200 CursorPage[MerchantConversationSummary] | 401；403角色错误；422 INVALID_REQUEST / INVALID_CURSOR；503 DATA_SOURCE_UNAVAILABLE。仅当前商家对话；只读 |
| `GET /api/v2/merchant/conversations/{conversation_id}` | X-Session-Id 商家；路径conversation_id:PublicId；查询cursor/limit用于消息；体无 | 200 MerchantConversationDetailResponse | 401；403角色错误 / RESOURCE_FORBIDDEN；422 INVALID_REQUEST / INVALID_CURSOR；503 DATA_SOURCE_UNAVAILABLE。只读 |
| `DELETE /api/v2/merchant/conversations/{conversation_id}` | X-Session-Id 商家；路径conversation_id:PublicId；查询/体无 | 204，无体 | 401；403角色错误 / RESOURCE_FORBIDDEN；422 INVALID_REQUEST；503 DATA_SOURCE_UNAVAILABLE。删除后再次请求统一403；同事务删除来源状态，无client_request_id |

**Token 撤销级联**（PRD §7.5 不变量 5）：撤销演示 Token 时，由它换取的全部现存会话同步失效；
会话失效一律返回 `401 SESSION_INVALID`，客户端据此重新走 `POST /merchant/sessions`。
排序：对话 `updated_at DESC, id DESC`；消息 `created_at ASC, id ASC`。签名游标绑定端点、商家主体摘要、
资源类型、语言与 limit，消息还绑定 conversation_id；规则严格沿用 §8.7.4。

#### 8.9.3 Chat 与 v1 迁移

SSE 逐事件使用 §8.7.5；turn_complete 携带唯一完整 MerchantChatResponse，与 JSON 响应逐字段相同。
请求拒绝 `session_id`、`attachment_ids` 与身份字段。多轮历史回放规则与 §8.8.3 相同（D-N4-1），
商家消息不围栏（商家是店铺经营者本人，其指令就是任务本身）。v1 `AnswerMode` 一一映射：

| v1 AnswerMode | 商家端处理 |
| --- | --- |
| METRIC / DETAIL / RULE / IDENTITY / CHAT / INVALID | 同名映射 |
| ATTACHMENT | 不进入 v2；请求侧无附件字段，响应枚举无此值 |

### 8.10 交易：购物车与订单履约（组 3）

本节为 N1 纯模型契约，不挂载路由。全部请求、响应模型拒绝额外字段。金额一律 §8.7.8 的非负整数分；
时间带时区并归一化 UTC。`PublicId`、`StockBand` 与 §8.8.1 相同（`StockBand` 由 `shop_session` 导出，本节不重复定义）。
`merchant_id`、`buyer_key`、精确库存数量不出现在任何请求或响应中。

#### 8.10.1 基础字段与模型

| 模型 | 字段、类型与范围 |
| --- | --- |
| `PaymentStatus` | `PENDING / PAID / CLOSED`（支付维度，与履约维度值集不相交） |
| `FulfillmentStatus` | `NOT_SHIPPED / SHIPPED / IN_TRANSIT / OUT_FOR_DELIVERY / DELIVERED`（履约维度） |
| `OrderAfterSaleProjection` | `NONE / ACTIVE / CLOSED`；订单级聚合投影，与 §8.11 的 `AfterSaleState` 不是同一个枚举 |
| `CartItem` | `product_id: PublicId`；`name: string[1..200]`；`image_url: ImageUrl或null`（与 §8.8.1 商品图片结构校验完全一致）；`quantity: int[1..99]`；`unit_price_cents: MoneyCents`；`line_total_cents: MoneyCents`（必须等于 unit_price × quantity）；`stock_band: StockBand` |
| `CartResponse` | `items: CartItem[]`（0–50 项，`product_id` 不重复）；`subtotal_cents: MoneyCents`（必须等于各行之和）。购物车不占库存，价格仅作展示，结算以后端重算为准 |
| `CartItemSetRequest` | `quantity: int[0..99]`（严格整数，0 表示删除）；**不含 `client_request_id`**：设置绝对数量，天然幂等 |
| `OrderCreateRequest` | `client_request_id` 按 §8.7.3，必填；`coupon_id: PublicId或null`（可省略，默认null）。订单行来自当前购物车，请求不接受商品、单价、金额或库存字段 |
| `OrderItemPriceSnapshot` | `order_item_id: PublicId`；`product_id: PublicId`；`name: string[1..200]`；`quantity: int[1..99]`；`unit_price_cents`、`discount_cents`、`line_total_cents: MoneyCents`。约束：`discount_cents ≤ unit_price_cents × quantity`；`line_total_cents = unit_price_cents × quantity − discount_cents` |
| `OrderLeadItem` | `product_id: PublicId`；`name: string[1..200]`（取订单首行价格快照名称）；`image_url: ImageUrl或null`（取商品当前图片，经 `is_trusted_image_host` 判定，商品不存在或不可信时为 null） |
| `OrderSummary` | `id: PublicId`；`payment_status`；`fulfillment_status`；`after_sale_status: OrderAfterSaleProjection`；`total_cents: MoneyCents`；`item_count: int≥1`；`created_at: UTC datetime`；`pay_by: UTC datetime`（支付截止，创建后 30 分钟）；`lead_item: OrderLeadItem`（按订单明细 `created_at, id` 升序的首行）；`last_event_at: UTC datetime`（该订单最新履约事件的 `occurred_at`；不早于 `created_at`）。约束：`fulfillment_status ≠ NOT_SHIPPED` 时 `payment_status` 必须是 `PAID` |
| `OrderDetailResponse` | OrderSummary 全部字段（含 `lead_item`、`last_event_at`）；`items: OrderItemPriceSnapshot[]`（1–50 项，`order_item_id` 不重复）；`subtotal_cents`、`discount_cents: MoneyCents`；`coupon_id: PublicId或null`；`paid_at: UTC datetime或null`；`closed_at: UTC datetime或null`；`close_reason: USER_CANCELLED / PAYMENT_TIMEOUT / null`；`is_demo: true`。约束见下。下单、支付、取消的响应同样携带 `lead_item`、`last_event_at` |
| `FulfillmentEventType` | `ORDER_PLACED / PAYMENT_CONFIRMED / SHIPPED / IN_TRANSIT / OUT_FOR_DELIVERY / DELIVERED / ORDER_CLOSED` |
| `FulfillmentEvent` | `id: PublicId`；`event_type: FulfillmentEventType`；`occurred_at: UTC datetime`；`source_timezone: string[1..64]`（IANA 时区名，来源时区，不做隐式推断） |
| `FulfillmentEventPage` | 即 `CursorPage[FulfillmentEvent]`（`items / next_cursor / has_more`，§8.7.4） |
| `OrderPayRequest` / `OrderCancelRequest` | 仅 `client_request_id` 按 §8.7.3，必填，不接受其他字段 |
| `IllegalTransitionDetail` | `payment_status: PaymentStatus`。仅用于 `ILLEGAL_STATE_TRANSITION.details` 的唯一元素，不含任何锁、版本或内部状态 |
| `UnavailableItemDetail` | `product_id: PublicId`；`reason: OUT_OF_STOCK / INSUFFICIENT_STOCK / DELISTED`；`stock_band: StockBand`。用于下单不可用项提示，只给档位，不给数量 |

`OrderDetailResponse` 的一致性约束：`subtotal_cents = Σ unit_price × quantity`；`discount_cents = Σ 行 discount`；
`total_cents = subtotal_cents − discount_cents = Σ line_total_cents`；`item_count = Σ quantity`；
`paid_at` 非空当且仅当 `payment_status = PAID`；`closed_at` 与 `close_reason` 同时非空当且仅当 `payment_status = CLOSED`；
`pay_by` 不早于 `created_at`；`last_event_at` 不早于 `created_at`（`OrderSummary` 同一约束）。

关闭原因在数据库保留 `CUSTOMER_CANCEL` / `TIMEOUT`，分别对应 API 的
`USER_CANCELLED` / `PAYMENT_TIMEOUT`。响应装配与写入边界须调用
`app/domain/order_status_mapping.py` 中的 `close_reason_to_api` / `close_reason_from_api`；
`null` 原样传递，未知值拒绝。存储词汇不得直接下发，历史迁移不改写。

#### 8.10.2 不变量

1. **支付与履约是两个独立字段，不合并**（PRD §7.1 D14⑥）。事件表才是事实源；`OrderSummary / OrderDetailResponse`
   的三维字段是查询投影，**由事件重算，客户端不得据投影推断事件缺失**。`OrderDetailResponse`
   **不内嵌无界 `events` 数组**，履约事件只由 `/orders/{order_id}/events` 游标分页提供。
   `ORDER_CLOSED` 是让 `payment_status = CLOSED` 能由事件派生的事件类型，已回写 PRD §7.1 与 §C5，并与数据迁移计划 M3 的 `fulfillment_events` 类型一致。
2. **顾客侧只暴露库存档位**：购物车、订单与公开商品响应只含 `stock_band`，不得返回 `stock_on_hand / stock_reserved / stock_available`。
3. **`POST /orders` 响应含完整价格快照**（`OrderItemPriceSnapshot`），§8.11 的行级退款上限直接依赖它；
   舍入顺序按 §8.7.8：先逐行 `ROUND_HALF_UP` 到分，再对行结果求和。
4. **`PUT /cart/items/{product_id}` 设置绝对数量**，天然幂等，不带 `client_request_id`；`quantity = 0` 等价于删除。
   商品不属于本店或未通过来源闸门返回 `403 PRODUCT_NOT_IN_SCOPE`；`quantity > 0` 但商品已售罄返回 `409 INSUFFICIENT_STOCK`。
5. **`POST /orders`、`/pay`、`/cancel` 全部携带 `client_request_id`**。`pay` 与 `cancel`（以及超时关闭）并发互斥：
   败者返回 `409 ILLEGAL_STATE_TRANSITION`，`details` 只含一个 `IllegalTransitionDetail`。

#### 8.10.3 逐路径契约

列表参数为 `cursor: string[1..2048]或null`（默认null）、`limit: int[1..100]`（默认20）；错误沿用 §8.3 ErrorResponse。
401 为 `SESSION_REQUIRED / SESSION_INVALID`，403 角色错误为 `SESSION_ROLE_MISMATCH`；
「演示顾客会话」指已绑定演示顾客的会话，访客会话访问返回 `403 CUSTOMER_BINDING_REQUIRED`。
资源不存在与越权统一 `RESOURCE_FORBIDDEN`、空 details。

| 方法与完整路径 | 鉴权、路径/查询/请求体 | 成功响应 | 错误、幂等与传输 |
| --- | --- | --- | --- |
| `GET /api/v2/shop/cart` | X-Session-Id 顾客（含访客）；路径/查询/体无 | 200 CartResponse | 401；403角色错误；503 DATA_SOURCE_UNAVAILABLE。只读 |
| `PUT /api/v2/shop/cart/items/{product_id}` | X-Session-Id 顾客（含访客）；路径product_id:PublicId；查询无；体 CartItemSetRequest | 200 CartResponse（设置后的完整购物车） | 401；403角色错误 / PRODUCT_NOT_IN_SCOPE；409 INSUFFICIENT_STOCK；422 INVALID_REQUEST；503 DATA_SOURCE_UNAVAILABLE。绝对数量，天然幂等，无client_request_id；不占库存 |
| `DELETE /api/v2/shop/cart/items/{product_id}` | X-Session-Id 顾客（含访客）；路径product_id:PublicId；查询/体无 | 200 CartResponse（删除后的完整购物车） | 401；403角色错误；422 INVALID_REQUEST；503 DATA_SOURCE_UNAVAILABLE。天然幂等：商品不在购物车时同样 200，不探测商品是否存在 |
| `POST /api/v2/shop/orders` | X-Session-Id 演示顾客；路径/查询无；体 OrderCreateRequest | 201 OrderDetailResponse（含价格快照）；幂等重放返回原响应，状态码不变 | 401；403角色错误 / CUSTOMER_BINDING_REQUIRED；409 INSUFFICIENT_STOCK（details: UnavailableItemDetail[]）/ IDEMPOTENCY_KEY_REUSED / REQUEST_IN_PROGRESS；403 PRODUCT_NOT_IN_SCOPE（商品下架，details同上）；422 INVALID_REQUEST（购物车为空或优惠券不可用，details: [{field, reason}]）；503 DATA_SOURCE_UNAVAILABLE。幂等域按 §8.7.3；同一事务创建订单、占库、写事件，任一失败整体回滚 |
| `GET /api/v2/shop/orders` | X-Session-Id 演示顾客；路径无；查询cursor/limit；体无 | 200 CursorPage[OrderSummary] | 401；403角色错误 / CUSTOMER_BINDING_REQUIRED；422 INVALID_REQUEST / INVALID_CURSOR；503 DATA_SOURCE_UNAVAILABLE。仅本人订单（merchant_id + buyer_key 双重过滤）；只读 |
| `GET /api/v2/shop/orders/{order_id}` | X-Session-Id 演示顾客；路径order_id:PublicId；查询/体无 | 200 OrderDetailResponse | 401；403角色错误 / CUSTOMER_BINDING_REQUIRED / RESOURCE_FORBIDDEN；422 INVALID_REQUEST；503 DATA_SOURCE_UNAVAILABLE。只读；历史订单（迁移前创建）同样统一 RESOURCE_FORBIDDEN |
| `GET /api/v2/shop/orders/{order_id}/events` | X-Session-Id 演示顾客；路径order_id:PublicId；查询cursor/limit；体无 | 200 FulfillmentEventPage | 401；403角色错误 / CUSTOMER_BINDING_REQUIRED / RESOURCE_FORBIDDEN；422 INVALID_REQUEST / INVALID_CURSOR；503 DATA_SOURCE_UNAVAILABLE。只读；游标额外绑定 order_id |
| `POST /api/v2/shop/orders/{order_id}/pay` | X-Session-Id 演示顾客；路径order_id:PublicId；查询无；体 OrderPayRequest | 200 OrderDetailResponse | 401；403角色错误 / CUSTOMER_BINDING_REQUIRED / RESOURCE_FORBIDDEN；409 ILLEGAL_STATE_TRANSITION（details: IllegalTransitionDetail）/ IDEMPOTENCY_KEY_REUSED / REQUEST_IN_PROGRESS；422 INVALID_REQUEST；503 DATA_SOURCE_UNAVAILABLE。模拟支付；已过 `pay_by` 视为已关闭 |
| `POST /api/v2/shop/orders/{order_id}/cancel` | X-Session-Id 演示顾客；路径order_id:PublicId；查询无；体 OrderCancelRequest | 200 OrderDetailResponse | 同 `/pay`。仅 `PENDING` 可取消；成功释放占用 |

排序：订单 `created_at DESC, id DESC`；履约事件 `occurred_at ASC, id ASC`。签名游标绑定端点、会话主体+店铺、资源类型、语言与 limit，
事件游标另绑定 order_id，规则严格沿用 §8.7.4。

#### 8.10.4 实现期约束（由路由实现任务承接，不属于 Schema 冻结）

以下 PRD §7.1、§7.4 不变量无法落到字段上，登记在此，**不得静默丢弃**：

- 订单创建、占库、写 `ORDER_PLACED` 事件在同一事务内原子完成（§7.4 不变量 2）；
- 库存扣减使用带条件更新，任何路径不得产生负可售量（§7.4 不变量 1）；每条库存变化写账本并注明来源（§7.4 不变量 3）；
- 事件表追加写，投影与事件同事务更新，并提供由事件重算校验的任务（§7.1 不变量 1）；
- 非法迁移拒绝写入（如未支付直接出库、已签收回退运输中），事件按去重键幂等（§7.1 不变量 2、3）；
- 「已支付」与「已关闭」以条件更新裁决，只有一方生效（§7.1 不变量 4）；30 分钟未支付关闭由**业务路径自检 `pay_by`**保证，Cron 只清理；
- 一个订单只有一条履约流，不做拆单（§7.1 不变量 5）；时间存 UTC 并记录来源时区（§7.1 不变量 6）。

### 8.11 售后（双端）（组 4）

本节为 N1 纯模型契约，不挂载路由。全部请求、响应模型拒绝额外字段。金额一律 §8.7.8 的非负整数分；
时间带时区并归一化 UTC。`after_sale_id` 指售后主记录 `after_sales.id`（PRD §8.1、数据迁移计划 M7）；
`refunds` / `returns` 是它名下的资金 / 货品动作记录，工单以唯一外键挂在它上面，均不单独作为 `after_sale_id` 暴露。
`OrderItemPriceSnapshot` 复用 §8.10.1，本节不重复定义。范围：退货退款、仅退款、客服工单，不做换货。

#### 8.11.1 基础字段与模型

| 模型 | 字段、类型与范围 |
| --- | --- |
| `AfterSaleType` | `RETURN_REFUND / REFUND_ONLY / TICKET` |
| `AfterSaleState` | `PENDING_MERCHANT / APPROVED / REJECTED / AWAITING_RETURN / RECEIVED / REFUNDED / AWAITING_CUSTOMER_INFO / CLOSED` |
| `AfterSaleActor` | `CUSTOMER / MERCHANT / SYSTEM`；只表示动作来源类别，不含任何主体标识 |
| `AfterSaleCreateRequest` | `client_request_id` 按 §8.7.3，必填；`order_id: PublicId`；`after_sale_type: AfterSaleType`；`order_item_ids: PublicId[]`（0–50 项，不重复；空表示整单全部订单行，售后按整行处理，不支持行内部分数量）；`reason: string[0..1000]`（strip，默认空串；`TICKET` 必须非空）；`include_conversation_summary: bool`（默认 false）；`confirmation_token: string[1..2048]或null`（默认 null；字符集 `A-Za-z0-9._~-`）。**不含任何金额、可否发起、状态、身份或库存字段**；提交任何此类字段一律**拒绝**并返回 `422 INVALID_REQUEST`（不是忽略）。`RETURN_REFUND` / `REFUND_ONLY` 的 `order_item_ids` 可为空但不可重复 |
| `AfterSaleChallengeLine` | `order_item_id: PublicId`；`name: string[1..200]`；`quantity: int[1..99]`；`line_total_cents: MoneyCents` |
| `AfterSaleChallengeSummary` | `order_id: PublicId`；`after_sale_type`；`lines: AfterSaleChallengeLine[]`（0–50 项）；`estimated_refund_cents: MoneyCents或null`（`TICKET` 必须 null，其余必填）；`reason: string[0..1000]`；`conversation_summary_status: NOT_SHARED / INCLUDED / UNAVAILABLE`；`conversation_summary: string[1..2000]或null`（仅 `INCLUDED` 时非空；已脱敏预览）。供人核对，不含 token 与身份 |
| `AfterSaleConfirmationChallenge` | `confirmation_token: string[1..2048]`（服务端签发的 opaque 证据，§8.7.9）；`expires_at: UTC datetime`（签发后不超过 10 分钟）；`summary: AfterSaleChallengeSummary` |
| `AfterSaleSummary` | `id: PublicId`；`order_id: PublicId`；`after_sale_type`；`state: AfterSaleState`；`refund_amount_cents: MoneyCents或null`（`TICKET` 必须 null，其余必填）；`created_at / updated_at: UTC datetime`（`updated_at ≥ created_at`）。**不含 `confirmation_token`** |
| `AfterSaleLine` | `snapshot: OrderItemPriceSnapshot`；`refund_cents: MoneyCents`，且 `refund_cents ≤ snapshot.line_total_cents` |
| `AfterSaleEvent` | `id: PublicId`；`from_state: AfterSaleState或null`（仅创建事件为 null）；`to_state: AfterSaleState`；`actor: AfterSaleActor`；`occurred_at: UTC datetime` |
| `AfterSaleDetailBase` | AfterSaleSummary 全部字段；`reason: string[0..1000]`（顾客提交时的脱敏原因）；`lines: AfterSaleLine[]`（0–50 项，`TICKET` 可空，其余非空；`order_item_id` 不重复）；`events: AfterSaleEvent[]`（1–100 项，严格按 `occurred_at ASC, id ASC`）；`supplements: AfterSaleSupplement[]`（0–47 项，按 `submitted_at ASC, id ASC`）；`replies: AfterSaleReply[]`（按 `sent_at ASC, id ASC`）。约束：首个事件为 `null → PENDING_MERCHANT`；事件首尾相接；每一跳属于 §8.11.2 允许迁移表与补充信息次数上限；最后一个 `to_state` 等于 `state`；`refund_amount_cents = Σ lines.refund_cents`（`TICKET` 为 null） |
| `AfterSaleSupplementRequest` | `client_request_id` 按 §8.7.3，必填；`note: string[1..1000]`（strip 后非空）。**不含任何金额、状态、身份或附件字段**，提交此类字段一律 `422 INVALID_REQUEST`（2026-09-24 用户裁定补入） |
| `AfterSaleSupplement` | `id: PublicId`；`note: string[1..1000]`（入库前按 C8 同一规则脱敏：不含手机号、地址、支付信息）；`submitted_at: UTC datetime`。进入商家端 Agent 上下文时按 A11 围栏（顾客原文是数据，不是指令） |
| `AfterSaleReply` | `id: PublicId`；`text: string[1..2000]`（商家批准的回复正文）；`sent_at: UTC datetime`。平台内送达与售后决定在同一数据库事务生效；按 `sent_at ASC, id ASC` 展示，不含原始身份 |
| `CustomerAfterSaleDetailResponse` | AfterSaleDetailBase 全部字段；`conversation_summary_shared: bool`（是否已随申请提交给商家，C8 透明性）。**无 `buyer_alias`、无审计字段** |
| `ConversationSnapshot` | `status: NOT_SHARED / AVAILABLE / UNAVAILABLE`；`text: string[1..2000]或null`（仅 `AVAILABLE` 非空）；`unavailable_reason: string[1..200]或null`（仅 `UNAVAILABLE` 非空）。提交时固化的不可变快照，已脱敏，不含手机号、地址、支付信息 |
| `MerchantAfterSaleSummary` | AfterSaleSummary 全部字段；`buyer_alias: string[1..64]`（店铺级脱敏别名）；`first_response_due_at: UTC datetime`（仅提示，不强制考核） |
| `MerchantAfterSaleDetailResponse` | AfterSaleDetailBase 全部字段；`buyer_alias`、`first_response_due_at` 同上；`ticket_id: PublicId`（每个售后事项唯一的处理入口）；`conversation_summary: ConversationSnapshot`。**无 `buyer_key`、无 `viewed_audit_id` / `audit_id`**：查看审计是服务端副作用，不进入响应 |

#### 8.11.2 不变量与允许迁移表

1. **发起条件由后端判定，模型不得决定**（PRD §7.2 不变量 1）：请求没有任何「是否符合发起条件」的客户端断言字段。
   不符合条件（订单未签收、超时效、已有进行中或已全额退款的售后）返回 `422 GUARDRAIL_REJECTED`，
   `details` 为 `[AfterSaleIneligibleDetail]`（`reason: ORDER_NOT_DELIVERED / WINDOW_EXPIRED / ALREADY_IN_PROGRESS / ALREADY_REFUNDED`；
   `rule_reference: string[1..200]`，依据的平台规则条款，不许诺特例）。历史订单（迁移前创建）与他人订单统一 `403 RESOURCE_FORBIDDEN`。
2. **退款金额只由后端计算**：`refund_amount_cents` 由后端按 `OrderItemPriceSnapshot.line_total_cents` 计算，
   单行累计退款不得超过该行快照金额；多行分摊按 §8.7.8（先逐行舍入到分，再求和）。
   客户端提交任何金额字段一律**拒绝并返回 `422 INVALID_REQUEST`**。
3. **界面确认证据**（PRD §7.2 不变量 6）：`POST /shop/after-sales` 采用同一路径两阶段提交（§8.7.9）。
   不带 `confirmation_token` 时只做确定性预检、不写业务数据，返回 `200 AfterSaleConfirmationChallenge`（`Cache-Control: no-store`）；
   界面展示 `summary` 由用户确认后，用**同一个** `client_request_id` 加 token 重交，成功返回 `201 AfterSaleSummary`。
   两个响应分支互斥，OpenAPI 与 Adapter 必须能分辨（状态码不同、模型不同）。token 只能由服务端预检响应签发，
   **聊天中的确认不生效，Agent 不得代为生成**；token 服务端签名、一次性、短期有效，绑定
   `session_record_id + merchant_id + buyer_key 摘要 + order_id + 售后类型 + 请求摘要`；无效、过期或已消费返回 `422 CONFIRMATION_REQUIRED`；
   不得重复创建单据。challenge 响应不登记为终态幂等结果。
4. **双端响应结构不对称且必须不对称**：商家侧顾客标识只能是店铺级脱敏别名 `buyer_alias`（R5）；读取商家详情必须在返回前写查看审计
   （谁、何时、查看哪个单据的摘要，C8），响应不暴露审计标识。商家只能看到摘要与快照，不能展开完整对话。
   顾客侧不含 `buyer_alias`。摘要生成失败不阻断提交，快照为 `UNAVAILABLE` 并说明原因。
5. **商家没有售后直接写端点**：同意、拒绝、要求补充、确认收货与退款都经草稿审批（M9、§8.13）；本节只有商家读取。

**允许迁移表**（源状态 → 目标状态；非法迁移返回 `409 ILLEGAL_STATE_TRANSITION`）。PRD §7.2 的各条链（含客服工单）逐跳如下：

| 源状态 | 允许的目标状态 | 适用类型 | PRD §7.2 来源 |
| --- | --- | --- | --- |
| （创建） | `PENDING_MERCHANT` | 全部 | 各链起点 |
| `PENDING_MERCHANT` | `APPROVED` | 全部 | 待商家处理 → 已同意 |
| `PENDING_MERCHANT` | `REJECTED` | 全部 | 待商家处理 → 已拒绝 |
| `PENDING_MERCHANT` | `AWAITING_CUSTOMER_INFO` | 全部 | 待商家处理 → 待顾客补充信息 |
| `AWAITING_CUSTOMER_INFO` | `PENDING_MERCHANT` | 全部 | 待顾客补充信息 → 待商家处理 |
| `APPROVED` | `AWAITING_RETURN` | `RETURN_REFUND` | 已同意 → 待顾客寄回 |
| `APPROVED` | `REFUNDED` | `REFUND_ONLY` | 仅退款：已同意 → 已退款 |
| `AWAITING_RETURN` | `RECEIVED` | `RETURN_REFUND` | 待顾客寄回 → 商家已收货 |
| `RECEIVED` | `REFUNDED` | `RETURN_REFUND` | 商家已收货 → 已退款 |
| `REFUNDED` | `CLOSED` | `RETURN_REFUND`、`REFUND_ONLY` | 已退款 → 关闭 |
| `REJECTED` | `CLOSED` | 全部 | 已拒绝 → 关闭 |
| `APPROVED` | `CLOSED` | **仅 `TICKET`** | 客服工单：待商家处理 → 已同意（即已处理）→ 关闭（PRD §7.2，2026-09-21 回写）：工单没有退款与寄回，否则无法结案 |

`CLOSED` 是终态。除上表外的任何迁移（含 `TICKET` 进入 `AWAITING_RETURN / RECEIVED / REFUNDED`）都非法。
对 `PENDING_MERCHANT → AWAITING_CUSTOMER_INFO` 再加同一售后事项累计 **47 次**的上限；第 48 次
返回 `409 ILLEGAL_STATE_TRANSITION`，不追加事件、不改变状态。`is_allowed_transition()` 判断这条边时
必须取得此前已发起的补充信息请求次数，不能省略计数；服务层在同一事务内锁定记录、计数并追加事件，
避免并发越过上限。47 次完整往返后仍保留最长结案链的 5 条事件容量（`1 + 47×2 + 5 = 100`）。
状态变化追加写售后事件，与 §8.10 同机制；库存回补只在 `RECEIVED` 且商家明确判定可售时发生，
并写来源为退货的库存事件（PRD §7.2 不变量 3），该判定是草稿载荷的一部分，不出现在本节模型中。

**触发方与系统续跳**（PRD §7.2「各跳的触发方」，2026-09-24 用户裁定）：允许迁移表只说「能不能走」，下表说「谁能触发」；
服务层必须同时校验两者，`actor` 与触发方不符同样是非法迁移。

| 迁移 | 唯一合法触发 | `actor` |
| --- | --- | --- |
| （创建）→ `PENDING_MERCHANT` | `POST /shop/after-sales` 第二阶段 | `CUSTOMER` |
| `PENDING_MERCHANT` → `APPROVED` / `REJECTED` / `AWAITING_CUSTOMER_INFO` | 应用 `AFTER_SALE_DECISION` 草稿（§8.13） | `MERCHANT` |
| `AWAITING_CUSTOMER_INFO` → `PENDING_MERCHANT` | `POST /shop/after-sales/{id}/supplements` | `CUSTOMER` |
| `APPROVED` → `AWAITING_RETURN`（`RETURN_REFUND`） | 与「同意」同一事务的系统续跳 | `SYSTEM` |
| `APPROVED` → `CLOSED`（`TICKET`） | 与「同意」同一事务的系统续跳 | `SYSTEM` |
| `AWAITING_RETURN` → `RECEIVED` | 应用「确认收货」草稿（载荷含可售判定） | `MERCHANT` |
| `APPROVED`（`REFUND_ONLY`）/ `RECEIVED` → `REFUNDED` | 应用「退款」草稿 | `MERCHANT` |
| `REFUNDED` → `CLOSED` | 与「退款」同一事务的系统续跳 | `SYSTEM` |
| `REJECTED` → `CLOSED` | 与「拒绝」同一事务的系统续跳 | `SYSTEM` |

系统续跳与触发它的那一跳同事务、各写一条事件，失败整体回滚；因此 `APPROVED`（退货退款、工单）、`REFUNDED`、`REJECTED`
只出现在事件里，不会是提交后的当前状态（仅退款的 `APPROVED` 除外，它等待退款草稿）。不设任何超时迁移。

#### 8.11.3 逐路径契约

列表参数为 `cursor: string[1..2048]或null`（默认null）、`limit: int[1..100]`（默认20）；商家列表另有 `state: AfterSaleState或null`（默认null，不过滤）。
错误沿用 §8.3 ErrorResponse。401 为 `SESSION_REQUIRED / SESSION_INVALID`，403 角色错误为 `SESSION_ROLE_MISMATCH`；
「演示顾客会话」指已绑定演示顾客的会话，访客访问返回 `403 CUSTOMER_BINDING_REQUIRED`。资源不存在与越权统一 `RESOURCE_FORBIDDEN`、空 details。

| 方法与完整路径 | 鉴权、路径/查询/请求体 | 成功响应 | 错误、幂等与传输 |
| --- | --- | --- | --- |
| `POST /api/v2/shop/after-sales` | X-Session-Id 演示顾客；路径/查询无；体 AfterSaleCreateRequest | 200 AfterSaleConfirmationChallenge（无 token，预检，`Cache-Control: no-store`）或 201 AfterSaleSummary（带有效 token，已创建） | 401；403角色错误 / CUSTOMER_BINDING_REQUIRED / RESOURCE_FORBIDDEN；409 IDEMPOTENCY_KEY_REUSED / REQUEST_IN_PROGRESS；422 INVALID_REQUEST（含客户端金额等禁止字段）/ GUARDRAIL_REJECTED（details: AfterSaleIneligibleDetail[]）/ CONFIRMATION_REQUIRED；503 DATA_SOURCE_UNAVAILABLE。幂等域与处理顺序按 §8.7.3、§8.7.9；创建与证据消费同一事务 |
| `GET /api/v2/shop/after-sales` | X-Session-Id 演示顾客；路径无；查询cursor/limit；体无 | 200 CursorPage[AfterSaleSummary] | 401；403角色错误 / CUSTOMER_BINDING_REQUIRED；422 INVALID_REQUEST / INVALID_CURSOR；503 DATA_SOURCE_UNAVAILABLE。仅本人（merchant_id + buyer_key 双重过滤）；只读 |
| `GET /api/v2/shop/after-sales/{after_sale_id}` | X-Session-Id 演示顾客；路径after_sale_id:PublicId；查询/体无 | 200 CustomerAfterSaleDetailResponse | 401；403角色错误 / CUSTOMER_BINDING_REQUIRED / RESOURCE_FORBIDDEN；422 INVALID_REQUEST；503 DATA_SOURCE_UNAVAILABLE。只读 |
| `POST /api/v2/shop/after-sales/{after_sale_id}/supplements` | X-Session-Id 演示顾客；路径after_sale_id:PublicId；查询无；体 AfterSaleSupplementRequest | 200 AfterSaleSummary（`state = PENDING_MERCHANT`） | 401；403角色错误 / CUSTOMER_BINDING_REQUIRED / RESOURCE_FORBIDDEN；409 ILLEGAL_STATE_TRANSITION（当前不是 `AWAITING_CUSTOMER_INFO`）/ IDEMPOTENCY_KEY_REUSED / REQUEST_IN_PROGRESS；422 INVALID_REQUEST；503 DATA_SOURCE_UNAVAILABLE。仅本人（双重过滤）；幂等按 §8.7.3；补充说明入库、事件追加与状态投影同一事务；界面表单提交即界面确认，不走 §8.7.9 两阶段；无 Agent 工具（2026-09-24 用户裁定补入） |
| `GET /api/v2/merchant/after-sales` | X-Session-Id 商家；路径无；查询cursor/limit/state；体无 | 200 CursorPage[MerchantAfterSaleSummary] | 401；403角色错误；422 INVALID_REQUEST / INVALID_CURSOR；503 DATA_SOURCE_UNAVAILABLE。仅本店；只读 |
| `GET /api/v2/merchant/after-sales/{after_sale_id}` | X-Session-Id 商家；路径after_sale_id:PublicId；查询/体无 | 200 MerchantAfterSaleDetailResponse，`Cache-Control: no-store` | 401；403角色错误 / RESOURCE_FORBIDDEN；422 INVALID_REQUEST；503 DATA_SOURCE_UNAVAILABLE。返回前写查看审计；审计写入失败则不返回摘要正文 |

排序：两端列表均 `created_at DESC, id DESC`；商家列表游标额外绑定 `state` 筛选。签名游标规则严格沿用 §8.7.4，
绑定端点、会话主体+店铺、资源类型、语言与 limit。

### 8.12 商家经营只读面（组 5）

本节为 N1 纯模型契约，不挂载路由。全部请求、响应模型拒绝额外字段。时间带时区并归一化 UTC；
金额一律 §8.7.8 的整数分。**精确库存三元组只出现在本节的商家响应中**，不得进入 §8.8、§8.10 的顾客响应。
本节不引用顾客端模块，只消费 `common.py`。PRD §11.2.3 把简报重生成描述为「限流、幂等地替换当日简报版本」。

#### 8.12.1 基础字段与模型

| 模型 | 字段、类型与范围 |
| --- | --- |
| `DailyBriefItemKind` | `INVENTORY_ALERT / PENDING_DRAFT / CUSTOMER_SIGNAL / METRIC_CHANGE / ORDER_EXCEPTION` |
| `DailyBriefItem` | `rank: int≥1`；`kind: DailyBriefItemKind`；`title: string[1..200]`；`evidence: string[1..500]`（数字依据；数字缺失时说明缺什么，不估算）；`amount_cents: MoneyCents或null`（涉及金额；金额未知为 null，不自动排末尾）；`next_action_prompt: string[1..500]或null`（只把问题填入输入框，不发送、不批准、不执行，只能指向已有能力） |
| `DailyBriefResponse` | §8.7.6 `DegradationMixin` 的全部字段（`analysis_sources`、`thinking_steps`、`quality_status`、`quality_attempts`、`quality_notes`、`degraded`、`degraded_reason`）；`brief_version: int≥1`；`business_date: date`（按商家配置时区的营业日）；`business_timezone: string[1..64]`（IANA 时区名）；`data_as_of: UTC datetime`（数据截至时间）；`generated_at: UTC datetime`（生成时间，`≥ data_as_of`）；`trigger: SCHEDULED / REGENERATED`；`items: DailyBriefItem[]`（0–6 项，`rank` 从 1 连续且不重复）；`collapsed_count: int≥0`（折叠为「另有 N 项」的数量） |
| `BriefRegenerateRequest` | 仅 `client_request_id` 按 §8.7.3，必填，不接受其他字段 |
| `InventoryAlertKind` | `LOW_STOCK / OUT_OF_STOCK / SLOW_MOVING` |
| `InventoryAlert` | `id: PublicId`；`kind: InventoryAlertKind`；`product_id: PublicId`；`product_name: string[1..200]`；`stock_on_hand: int≥0`；`stock_reserved: int≥0`；`stock_available: int≥0`；`low_stock_threshold: int≥0`；`sold_last_30d: int≥0`；`days_of_supply: int≥0或null`。约束见下 |
| `CustomerSignalKind` | `RETURN_REQUESTS / REFUND_REQUESTS / SUPPORT_TICKETS / CONTENT_GAP`（`CONTENT_GAP` 为 PRD S2 / D11④ 的内容缺口信号，2026-09-21 补入，执行期裁定 E8） |
| `SignalSourceRef` | `source_type: AFTER_SALE / PRODUCT`；`source_id: PublicId`；`content_version: int≥1或null`（可省略，默认null）。`AFTER_SALE` 指向售后主记录（§8.11），`content_version` 必须为 null；`PRODUCT` 指向商品，`content_version` 必填，记录发现缺口时的商品内容版本。**任何信号都不指向顾客对话** |
| `CustomerSignal` | `id: PublicId`；`kind: CustomerSignalKind`；`product_id: PublicId或null`；`product_name: string[1..200]或null`（二者同时为空或同时非空）；`signal_date: date`；`count: int≥1`（同商品同类信号按天聚合去重计数）；`derived_from: SignalSourceRef[]`（1–50 项，不重复，项数 ≤ `count`；`CONTENT_GAP` 恰好 1 项 `PRODUCT` 来源且 `source_id = product_id`，`product_id` 必填；其余三类只接受 `AFTER_SALE` 来源）；`is_ignored: bool`；`ignore_reason: string[1..500]或null`（仅 `is_ignored=true` 时非空）。**不含任何顾客标识**（PRD M9：前端不显示顾客标识） |
| `SignalIgnoreRequest` | `client_request_id` 按 §8.7.3，必填；`reason: string[1..500]`（strip 后非空，必填） |

`InventoryAlert` 一致性约束：`stock_reserved ≤ stock_on_hand`；`stock_available = stock_on_hand − stock_reserved`（可售 = 在库 − 占用）；
`OUT_OF_STOCK` 要求 `stock_available = 0`；`LOW_STOCK` 要求 `0 < stock_available ≤ low_stock_threshold`；
`SLOW_MOVING` 要求 `stock_available > 0`；`days_of_supply` 为 null 当且仅当 `sold_last_30d = 0`（销量为零时显示「未知 / 无近期销量」，不产生伪精确值）。
库存值全部由后端确定性计算，客户端不可写。

#### 8.12.2 不变量

1. **简报有版本**：同一商家、同一营业日只有一份当前简报；定时重试与手动重新生成都是版本替换，`brief_version` 单调递增，
   有并发锁与幂等保护。**旧简报可作历史保留，但不得标为今日简报**：`GET .../current` 只返回当前营业日的当前版本。
2. **简报必须如实披露降级**（R7）：`DailyBriefResponse` 混入 §8.7.6 全部降级字段。由确定性规则生成的简报
   `analysis_sources` 只能填实际来源（如 `DATABASE`），**不得包装成模型分析**；`FALLBACK` 来源必须同时 `degraded=true`。
   **N2 最小简报**只汇总库存告警与待批准草稿、不调用 LLM，属于此情形；同一响应结构在 N3 扩展为完整 M2，字段不变，只是来源与条目变多。
   生成失败时返回 `degraded=true` 且 `items` 可为空的当前版本，`degraded_reason` 是安全可理解的说明，不泄露内部异常、SQL 或模型信息。
3. **顾客信号是派生提醒，不是事实源**（PRD §8.1、M9）：业务记录才是事实源，信号只经 `derived_from` 指回它。
   内容缺口信号的事实源是商品内容与后端确定性完整度规则（D11③④）：顾客提问只触发重算与计数，信号本身只指回商品与内容版本，不保存或引用顾客提问原文。
   **忽略信号不改变任何事实数据**，只写忽略记录（操作者、时间、原因）。
4. **库存告警只读**：补货、下架、降价都经草稿审批（§8.13），本组没有任何库存写端点。

#### 8.12.3 逐路径契约

列表参数为 `cursor: string[1..2048]或null`（默认null）、`limit: int[1..100]`（默认20）；错误沿用 §8.3 ErrorResponse。
401 为 `SESSION_REQUIRED / SESSION_INVALID`，403 角色错误为 `SESSION_ROLE_MISMATCH`，资源不存在与越权统一 `RESOURCE_FORBIDDEN`、空 details。

`MerchantProductContent` 必填字段：`id: PublicId`、`title: string[1..200]`、`category: string[1..64]`、`status: string`、`image_url: ImageUrl或null`（2026-10-04 补入；与顾客端 §8.8.1 同一类型和同一份主机白名单，无图或不可信来源为 null；演示图 `/demo/products/NN.webp` 是顾客端站点的静态资源，商家端按 `VITE_SHOP_BASE_URL` 拼出完整地址，未配置时显示占位）、`content_version: int≥1`、`missing_required_attributes: string[]`（后端排序）、`missing_content_fields: string[]`（后端排序，取值 `商品描述`/`商品图片`）、`content_complete: bool`、`stock_on_hand/stock_reserved/stock_available: int≥0`。三项库存满足 `stock_available = stock_on_hand - stock_reserved`；完整度由后端按类目同时核对必填属性、最短详情描述及图片期望，未登记类目不臆造要求。

`MerchantCoupon` 继承顾客券 `CouponSummary` 的金额、支付比例和时间字段，另必填 `state: string`、`currently_active: bool`；商家列表包含未生效及停用券，`currently_active` 与顾客可见券使用同一判定函数。两类列表均为 `CursorPage`，不接受业务写入。

| 方法与完整路径 | 鉴权、路径/查询/请求体 | 成功响应 | 错误、幂等与传输 |
| --- | --- | --- | --- |
| `GET /api/v2/merchant/briefs/daily/current` | X-Session-Id 商家；路径/查询/体无 | 200 DailyBriefResponse | 401；403角色错误；422；503 DATA_SOURCE_UNAVAILABLE。只读；**不返回 404**——尚无已存储简报时现算并以 `trigger=SCHEDULED` 落为第 1 版再返回（2026-09-26 修正：定时任务默认关闭，若严格 404 则商家在首次手动重新生成前永远看不到任何简报） |
| `POST /api/v2/merchant/briefs/daily/current/regenerate` | X-Session-Id 商家；路径/查询无；体 BriefRegenerateRequest | 200 DailyBriefResponse（替换后的新版本） | 401；403角色错误；409 IDEMPOTENCY_KEY_REUSED / REQUEST_IN_PROGRESS；422 INVALID_REQUEST；429 RATE_LIMITED（限流或冷却，`FAILED_RETRYABLE`，重试不调用 LLM）；503 LLM_BUDGET_EXCEEDED / DATA_SOURCE_UNAVAILABLE。幂等域按 §8.7.3；同营业日并发只产生一个新版本 |
| `GET /api/v2/merchant/inventory/alerts` | X-Session-Id 商家；路径无；查询cursor/limit/kind（`InventoryAlertKind或null`，默认不过滤）；体无 | 200 CursorPage[InventoryAlert] | 401；403角色错误；422 INVALID_REQUEST / INVALID_CURSOR；503 DATA_SOURCE_UNAVAILABLE。仅本店；只读 |
| `GET /api/v2/merchant/products/content` | X-Session-Id 商家；路径无；查询cursor/limit；体无 | 200 CursorPage[MerchantProductContent] | 401；403角色错误；422 INVALID_REQUEST / INVALID_CURSOR；503 DATA_SOURCE_UNAVAILABLE。按商家会话取本店全部状态商品，后端按类目完整度规则计算两类缺口与 `content_complete`，并返回精确库存三元组；不接受前端商家标识 |
| `GET /api/v2/merchant/coupons` | X-Session-Id 商家；路径无；查询cursor/limit；体无 | 200 CursorPage[MerchantCoupon] | 401；403角色错误；422 INVALID_REQUEST / INVALID_CURSOR；503 DATA_SOURCE_UNAVAILABLE。按商家会话取本店全部状态优惠券，金额单位为分、折扣为支付比例基点，`currently_active` 由后端依据状态和当前时间判定；不接受前端商家标识 |
| `GET /api/v2/merchant/customer-signals` | X-Session-Id 商家；路径无；查询cursor/limit/include_ignored（bool，默认false）；体无 | 200 CursorPage[CustomerSignal] | 401；403角色错误；422 INVALID_REQUEST / INVALID_CURSOR；503 DATA_SOURCE_UNAVAILABLE。仅聚合或脱敏结果；只读 |
| `POST /api/v2/merchant/customer-signals/{signal_id}/ignore` | X-Session-Id 商家；路径signal_id:PublicId；查询无；体 SignalIgnoreRequest | 200 CustomerSignal（`is_ignored=true`） | 401；403角色错误 / RESOURCE_FORBIDDEN；409 IDEMPOTENCY_KEY_REUSED / REQUEST_IN_PROGRESS；422 INVALID_REQUEST；503 DATA_SOURCE_UNAVAILABLE。幂等域按 §8.7.3；不改变任何事实数据 |

排序：库存告警按严重度 `OUT_OF_STOCK → LOW_STOCK → SLOW_MOVING`，同级 `product_id ASC`（`id` 兜底）；商品内容与优惠券按 `created_at DESC, id DESC`；顾客信号 `signal_date DESC, id DESC`。
签名游标绑定端点、商家主体摘要、资源类型、筛选条件、语言与 limit，规则严格沿用 §8.7.4。

#### 8.12.4 首页经营主指标与订单只读面（2026-09-28 补入）

**来源**：PRD M1（新增「订单」区域、首页经营主指标）、§11.2.3 新增三条路径、§15「W」。
规划与迁移方案见 `plans/2026-09-28-merchant-workbench-redesign.md`。本节字段写完之前，不得创建这三条路由或前端请求封装（§8.0.1）。

本节三条路径的约定：

- 全部只读，不调用任何 LLM（零费用），`merchant_id` 只从商家会话解析；
- 全部模型拒绝额外字段，金额按 §8.7.8 为整数分，时间归一化为 UTC；
- 本节新增 `SignedMoneyCents`：`int`，strict，`−MAX_MONEY_CENTS ≤ x ≤ MAX_MONEY_CENTS`。净成交额与贡献值在退款大于成交时可为负，不能用非负的 `MoneyCents` 表示。

**模型：**

| 模型 | 字段、类型与范围 |
| --- | --- |
| `OverviewPeriod` | `start: date`；`end: date`（闭区间，按商家业务时区，`start ≤ end`，跨度 1–7 天）；`label: string[1..40]`（后端生成的本地化说明，如「本周前 3 天」，按 §8.6 语言协商） |
| `OverviewMetricPoint` | `date: date`；`value_cents: SignedMoneyCents` |
| `OverviewHeadline` | `metric_code: "net_gmv"`（字面值，本版只有这一项主指标）；`current_cents: SignedMoneyCents`；`baseline_cents: SignedMoneyCents或null`（基期无可比数据为 null）；`change_ratio_bp: int[−1000000..1000000]或null`（相对变化，万分比，`ROUND_HALF_UP`；`baseline_cents` 为 null 或 ≤ 0 时必须为 null，不产生伪精确比例）；`current_series: OverviewMetricPoint[]`（本期每天恰好一点，日期连续，无数据的日子补 0）；`baseline_series: OverviewMetricPoint[]`（与 `current_series` 等长，按星期几逐日对齐；基期无可比数据时为 []） |
| `OverviewAttributionMode` | `SHARE / ABSOLUTE_CONTRIBUTION / STOPPED` |
| `OverviewAttributionSegment` | `name: string[1..64]`（类目名）；`current_cents`、`baseline_cents`、`contribution_cents: SignedMoneyCents`（`contribution = current − baseline`）；`share_bp: int[−1000000..1000000]或null`（仅 `mode = SHARE` 时非空） |
| `OverviewAttribution` | `dimension: "category"`（字面值）；`mode: OverviewAttributionMode`；`segments: OverviewAttributionSegment[]`（0–5 项，按 `abs(contribution_cents)` 降序，同值按 `name ASC`；`STOPPED` 时为 []）；`remaining_count: int≥0`；`remaining_contribution_cents: SignedMoneyCents`（其余类目的贡献合计。超过 5 个类目时**必须**用这两个字段说明其余部分，不得静默截断，M3）；`stopped_reason: string[1..200]或null`（仅 `STOPPED` 非空，安全可理解，不含 SQL 或内部异常） |
| `OverviewSecondaryMetricCode` | `order_count / refund_amount / return_rate`。只允许已登记的受控指标（`app/analytics/contract.py`），不新造「客单价」「退款率」等口径 |
| `OverviewSecondaryUnit` | `COUNT / CENTS / RATIO_BP` |
| `OverviewSecondaryMetric` | `metric_code: OverviewSecondaryMetricCode`；`unit: OverviewSecondaryUnit`（`order_count→COUNT`、`refund_amount→CENTS`、`return_rate→RATIO_BP`，固定映射）；`current_value: int≥0或null`；`baseline_value: int≥0或null`（null 表示无数据，不得写成 0）。`RATIO_BP` 为万分比整数，由指标注册表声明的单位按 Decimal 换算并 `ROUND_HALF_UP`，禁止经过 float |
| `MerchantMetricsOverviewResponse` | §8.7.6 `DegradationMixin` 全部字段；`business_timezone: string[1..64]`；`data_as_of: UTC datetime`；`source: REALTIME / DAILY_ROLLUP / MIXED`；`definition_version: string[1..64]`；`current_period`、`baseline_period: OverviewPeriod`；`headline: OverviewHeadline`；`attribution: OverviewAttribution`；`secondary: OverviewSecondaryMetric[]`（恰好 3 项，依次为 `order_count`、`refund_amount`、`return_rate`） |
| `MerchantOrderSummary` | §8.10.1 `OrderSummary` 全部字段，含顾客端店面重设计（WS）加入的 `lead_item`、`last_event_at`，商家端直接继承、不另起字段；`buyer_alias: string[1..64]`（店铺级脱敏别名，与 §8.11.1 `MerchantAfterSaleSummary` 使用同一派生函数）；`line_count: int[1..50]`（订单行数） |
| `MerchantOrderDetailResponse` | §8.10.1 `OrderDetailResponse` 全部字段；`buyer_alias`（同上） |

**不变量：**

1. **周期规则与归因工具相同**：
   - 本期为本周一至今天（业务时区），基期为上周的等长区间，与 `attribute_change` 共用 `AttributionService` 的周期计算，不另写一套；
   - `current_period.label`、`baseline_period.label` 与该服务的 `comparison_label` 语义一致；
   - 本期包含今天，数据来源可能是 `MIXED`，必须如实返回（M3）。
2. **所有数字都由后端确定性计算**（R4）：
   - `headline`、`attribution`、`secondary` 复用 `AttributionService.query_metrics`、`query_metrics_series`、`attribute_change`，以及 `SafeQueryService` 的受控查询；
   - 模型不参与，前端不得据序列自行重算比例或贡献。
   - 一致性约束：
     - `headline.current_cents = Σ current_series.value_cents`；
     - 基期非空时，`headline.baseline_cents = Σ baseline_series.value_cents`；
     - 归因 `mode ≠ STOPPED` 时，`Σ segments.contribution_cents + remaining_contribution_cents = current_cents − baseline_cents`。
3. **降级披露**（R7）：
   - 任一分项查询失败时整体 `degraded=true` 并给出原因。失败的分项取空值（`headline` 的 `baseline_cents` 为 null、归因为 `STOPPED`、辅助指标值为 null），**不回退到示意数字**。
   - `analysis_sources` 只填实际来源（`DATABASE`），不得出现模型分析来源。
   - `quality_status` 恒为 `NOT_RUN`，`quality_attempts = 0`：本端点没有 Reviewer。
4. **订单只读、按商家隔离**（R5）：
   - 列表与详情只返回本店、具备 v2 交易投影的订单。迁移前历史订单与他店订单一样返回 `403 RESOURCE_FORBIDDEN`，列表中不出现，与 §8.10.3 顾客端口径一致。
   - 响应**不含** `buyer_key`、顾客会话或任何联系方式；订单详情不含对话内容，因此不写查看审计（与 §8.11 售后详情不同）。
   - 本节没有订单写端点：发货、关闭、改价都不经本组。

**逐路径契约：**

列表参数同本节开头：`cursor: string[1..2048]或null`（默认null）、`limit: int[1..100]`（默认20）。401、403 角色错误与 `RESOURCE_FORBIDDEN` 的约定同 §8.12.3。

| 方法与完整路径 | 鉴权、路径/查询/请求体 | 成功响应 | 错误、幂等与传输 |
| --- | --- | --- | --- |
| `GET /api/v2/merchant/metrics/overview` | X-Session-Id 商家；路径/查询/体无（周期由后端固定，不接受日期参数） | 200 MerchantMetricsOverviewResponse | 401；403角色错误；503 DATA_SOURCE_UNAVAILABLE（数据库整体不可用；分项失败走降级字段而不是 503）。只读，不调用 LLM |
| `GET /api/v2/merchant/orders` | X-Session-Id 商家；路径无；查询 cursor/limit，以及筛选 `payment_status: PaymentStatus或null`、`fulfillment_status: FulfillmentStatus或null`、`after_sale_status: OrderAfterSaleProjection或null`（均默认null，不过滤）；体无 | 200 CursorPage[MerchantOrderSummary] | 401；403角色错误；422 INVALID_REQUEST / INVALID_CURSOR；503 DATA_SOURCE_UNAVAILABLE。仅本店；只读 |
| `GET /api/v2/merchant/orders/{order_id}` | X-Session-Id 商家；路径order_id:PublicId；查询/体无 | 200 MerchantOrderDetailResponse | 401；403角色错误 / RESOURCE_FORBIDDEN；422 INVALID_REQUEST；503 DATA_SOURCE_UNAVAILABLE。只读；不存在、他店订单与历史订单同一错误结构 |

**与 WS 的共用实现**：
- `lead_item` / `last_event_at` 由 WS（`plans/2026-09-28-shop-storefront-redesign.md` Task 1 步骤 7）写入 §8.10.1。
- 两端共用 `services/v2/orders.py` 的 `to_order_summary()`、`order_leads()`、`last_event_times()`。
- W Task 3 与 WS Task 3 改同一文件，须串行；先做的一方实现，后做的一方复用。
- W Task 3 先开工时，须先完成 WS Task 1 步骤 7 的契约，再按该契约实现这两个字段。

**排序与游标**：订单按 `created_at DESC, id DESC`。签名游标绑定端点、商家主体摘要、资源类型、三项筛选、语言与 limit，规则沿用 §8.7.4。

**安全集**：
- 三条路径都随路由登记两类用例：未认证、顾客会话越权（`SESSION_ROLE_MISMATCH`）。
- 订单详情另登记跨商家用例：返回 `RESOURCE_FORBIDDEN` 并写审计。
- 订单列表另登记用例：伪造他店游标，返回 `INVALID_CURSOR`。
- 全部用例都要通过路由覆盖守卫。

### 8.13 草稿审批与变更账本（组 6）

本节为 N1 纯模型契约，不挂载路由。全部请求、响应模型拒绝额外字段。时间带时区并归一化 UTC。
草稿是商家端所有写操作的唯一出口（PRD M10）；本组只有商家会话端点，没有任何顾客端点。本节不引用其他组的模块，只消费 `common.py`。

#### 8.13.1 基础字段与模型

| 模型 | 字段、类型与范围 |
| --- | --- |
| `DraftState` | `STAGED / APPLIED / DISCARDED / EXPIRED`。**没有 `APPROVED`**（PRD §7.3 不变量 1）：批准是 apply 事务的入参，不是可被后续请求复用的持久状态 |
| `DraftKind` | `RESTOCK / CONTENT_CHANGE / PRICE_CHANGE / COUPON / AFTER_SALE_DECISION` |
| `DraftSummary` | `id: PublicId`；`kind: DraftKind`；`state: DraftState`；`title: string[1..200]`；`draft_version: int≥1`（草案内容变更即递增）；`target_version: int≥0`（目标对象版本：库存为当前在库量基数，商品内容为内容版本号，售后为售后记录版本，新建优惠券为 0）；`batch_id: PublicId或null`（N3 阶段 C 新增：商品内容批量起草时，同一批次的各子草稿共享同一个值；**仅 `CONTENT_CHANGE` 可非空**，其余 `DraftKind` 恒为 null）；`created_at / updated_at: UTC datetime`；`expires_at: UTC datetime`（创建后 7 天）。约束：`updated_at ≥ created_at`；`expires_at > created_at` |
| `DiffUnit` | `TEXT / COUNT / CENTS / BPS / BOOL` |
| `DraftDiffEntry` | `entry_id: PublicId`；`target_type: PRODUCT / COUPON / AFTER_SALE`；`target_id: PublicId`；`field: string[1..100]`；`unit: DiffUnit`；`before: 值或null`；`after: 值或null`（值类型必须与 `unit` 一致：`TEXT` 为长度 ≤2000 的字符串，`COUNT / CENTS / BPS` 为非负整数（`CENTS` 不超过 §8.7.8 上界），`BOOL` 为布尔；均不接受 float 与隐式转换）；`is_preview: bool`（该值是应用时才计算的预览，以应用结果为准） |
| `DraftDiff` | `entries: DraftDiffEntry[]`（1–100 项，`entry_id` 不重复） |
| `GuardrailCheckResult` | `code: string[1..64]`（匹配 `^[A-Z][A-Z0-9_]*$` 的公开原因码）；`passed: bool`；`current_limit: string[1..200]或null`；`remediation: string[1..300]或null`。`passed=false` 时后两者必填。只表达**业务护栏**（价格、折扣、库存、时效），安全闸门的内部规则名不出现在此 |
| `DraftDetailResponse` | DraftSummary 全部字段；`diff: DraftDiff`；`guardrail_checks: GuardrailCheckResult[]`（0–20 项）；`guardrails_checked_at: UTC datetime`；`approval_evidence: string[1..2048]或null`；`approval_evidence_expires_at: UTC datetime或null`。`state=STAGED` 时两个证据字段必须同时非空，其余状态必须同时为 null。**这两个字段只供工作台 Adapter 消费**，不得进入 Agent / MCP 工具投影、SSE、日志或审计元数据 |
| `DraftApplyRequest` | `client_request_id` 按 §8.7.3，必填；`draft_version: int≥1`（必填）；`target_version: int≥0`（必填）；`approval_evidence: string[1..2048]`（必填，字符集 `A-Za-z0-9._~-`）；`accepted_entry_ids: PublicId[]或null`（1–100 项，不重复；null 表示批准全部条目；商品内容批量草稿支持勾选，未勾选条目不应用，PRD M4） |
| `LedgerActor` | `actor_type: AGENT / MERCHANT`；`label: string[1..120]`（展示名，不含会话或 Token 标识） |
| `ChangeLedgerEntry` | `id: PublicId`；`draft_id: PublicId`；`kind: DraftKind`；`drafted_by: LedgerActor`；`approved_by: LedgerActor`（`actor_type` 必须是 `MERCHANT`）；`approved_at: UTC datetime`；`applied_entry_ids: PublicId[]`（1–100 项，不重复）；`guardrail_results: GuardrailCheckResult[]`（0–20 项，全部 `passed=true`：应用时重查未通过则不会有账本条目） |
| `DraftApplyResponse` | `draft: DraftSummary`（`state` 必须是 `APPLIED`）；`ledger_entry: ChangeLedgerEntry`（`draft_id` 必须等于 `draft.id`，`kind` 必须等于 `draft.kind`） |
| `VersionConflictDetail` | `scope: DRAFT / TARGET`；仅用于 `VERSION_CONFLICT.details` 的唯一元素 |
| `DraftStateDetail` | `state: DraftState`；仅用于 `ILLEGAL_STATE_TRANSITION.details` 的唯一元素 |

**`AFTER_SALE_DECISION` 的特殊约束**：承载商家售后决定（同意、拒绝、要求补充、确认收货含可售判定、退款）与随附回复
（PRD M9，2026-09-21 裁定，§11.2.3 无售后直接写端点）。其草稿载荷**不得含任何金额字段**，退款金额在应用时按价格快照计算（§8.11.2）；
`diff` 中单位为 `CENTS` 的条目只能作为**应用时将计算的预览**展示，必须 `is_preview=true`，并标注以应用结果为准。
`is_preview=true` 只允许出现在 `AFTER_SALE_DECISION` 草稿中。

#### 8.13.2 不变量与迁移表

`DraftState` 迁移：`STAGED → APPLIED`（apply 事务内）、`STAGED → DISCARDED`（丢弃）、`STAGED → EXPIRED`（超过 7 天）；三个终态不再迁出。
非法迁移返回 `409 ILLEGAL_STATE_TRANSITION`，`details` 为唯一的 `DraftStateDetail`。逐条落地 PRD §7.3：

1. **只有 `STAGED` 可进入批准并应用事务**（不变量 1），终态都不可复用。
2. **批准绑定草案版本**（不变量 2）：`draft_version` 与服务端当前版本不符返回 `409 VERSION_CONFLICT`（`retryable=false`，
   `details=[VersionConflictDetail(scope=DRAFT)]`），客户端须重取详情、重新确认后发新请求。草案内容变更即递增版本，旧证据随之失效。
3. **目标对象版本校验**（不变量 3）：`target_version` 与目标对象当前值不符同样返回 `409 VERSION_CONFLICT`
   （`scope=TARGET`），**草稿保持 `STAGED`**——失败不推进状态、不写账本、不消费证据。
4. **应用时重查护栏**（不变量 4）：`DraftDetailResponse.guardrail_checks` 是**预检快照**，仅供展示，不构成通过承诺。
   apply 时按**当时生效**的配置重查，不通过返回 `422 GUARDRAIL_REJECTED`，`details` 为未通过的 `GuardrailCheckResult[]`，草稿保持 `STAGED`。
5. **幂等原子**（不变量 5）：`client_request_id` 按 §8.7.3；状态迁移、业务写入、账本条目与证据消费在同一事务内完成。
   同一 `client_request_id` 重试返回第一次结果，不产生二次副作用。
6. **批准只能来自审批界面**（不变量 6）：`approval_evidence` 由 `GET /drafts/{draft_id}` 签发，服务端签名、一次性、短期有效
   （≤10 分钟），绑定 `session_record_id + merchant_id + draft_id + draft_version + target_version`，请求摘要另含 `accepted_entry_ids`。
   处理顺序、持久化消费、重放语义严格按 §8.7.9：先查幂等；同一证据换新请求 ID 重放返回 `422 CONFIRMATION_REQUIRED`。
   **聊天里的「批准」不生效**；Agent 与 MCP 都没有签发或生成该证据的工具。批准与丢弃只能由**同店铺**商家会话执行，跨店铺 `403 RESOURCE_FORBIDDEN` 并写审计。
7. **变更账本**（不变量 7）：`DraftApplyResponse.ledger_entry` 记录起草者、批准者、批准时间与应用时的护栏检查结果。

**按种类分派（N3 阶段 A Task 5）**：应用事务只有一份骨架（`services/v2/draft_apply.py`）——锁行 → 状态 → 过期 → 草案版本 →
消费证据 → **种类处理器** → 置 `APPLIED` → 写账本。目标对象复检、按当时生效护栏复检、条件写入与领域事件（上文不变量 3、4
与实际写入）由 `services/v2/draft_handlers/` 中按 `DraftKind` 注册的处理器执行，返回 `HandlerResult(checks,
applied_entry_ids, ledger_result)`；构造时即核对：`ledger_result` 只能是 `APPLIED`（失败必须抛异常回滚），
`applied_entry_ids` 1–100 项且不重复，与 `ChangeLedgerEntry` 契约一致。处理器收到的是去掉证据与幂等键的 `HandlerRequest(draft_version, target_version,
accepted_entry_ids)`，结构上拿不到证据；不得提交事务、不得推进草稿状态或写账本，失败即整体回滚（证据消费随之回滚）。
分派表在导入期构建并自检：同一种类重复注册、`ENABLED_DRAFT_KINDS` 中的种类缺处理器都让服务起不来；运行期遇到未注册种类是
部署缺陷，在消费证据前抛出并返回 `500 INTERNAL_ERROR`，不是 409/422。当前已开放 `RESTOCK`、`PRICE_CHANGE`、`COUPON`
（N3 阶段 C）；B 注册 `AFTER_SALE_DECISION`、C 注册 `CONTENT_CHANGE` 时同步加入 `ENABLED_DRAFT_KINDS`。

过期由业务路径自检 `expires_at` 决定：读取或 apply 时 `now ≥ expires_at` 一律按 `EXPIRED` 处理，不依赖 Cron 是否已清理；
对已过期草稿 apply 返回 `409 DRAFT_EXPIRED`。

#### 8.13.3 逐路径契约

列表参数为 `cursor: string[1..2048]或null`（默认null）、`limit: int[1..100]`（默认20）。错误沿用 §8.3 ErrorResponse。
401 为 `SESSION_REQUIRED / SESSION_INVALID`，403 角色错误为 `SESSION_ROLE_MISMATCH`，资源不存在与越权统一 `RESOURCE_FORBIDDEN`、空 details。

| 方法与完整路径 | 鉴权、路径/查询/请求体 | 成功响应 | 错误、幂等与传输 |
| --- | --- | --- | --- |
| `GET /api/v2/merchant/drafts` | X-Session-Id 商家；路径无；查询cursor/limit/state（`DraftState`，默认 `STAGED`）/kind（`DraftKind或null`，默认不过滤）/batch_id（`PublicId或null`，默认不过滤；N3 阶段 C 新增，供审批界面按批次分组查看）；体无 | 200 CursorPage[DraftSummary] | 401；403角色错误；422 INVALID_REQUEST / INVALID_CURSOR；503 DATA_SOURCE_UNAVAILABLE。仅本店；只读；不含证据字段 |
| `GET /api/v2/merchant/drafts/{draft_id}` | X-Session-Id 商家；路径draft_id:PublicId；查询/体无 | 200 DraftDetailResponse，`Cache-Control: no-store` | 401；403角色错误 / RESOURCE_FORBIDDEN；422 INVALID_REQUEST；503 DATA_SOURCE_UNAVAILABLE。`STAGED` 时每次读取签发新的一次性证据；重复读取可有多个未消费 nonce，过期由 Cron 清理 |
| `POST /api/v2/merchant/drafts/{draft_id}/apply` | X-Session-Id 商家；路径draft_id:PublicId；查询无；体 DraftApplyRequest | 200 DraftApplyResponse | 401；403角色错误 / RESOURCE_FORBIDDEN；409 VERSION_CONFLICT / DRAFT_EXPIRED / ILLEGAL_STATE_TRANSITION / IDEMPOTENCY_KEY_REUSED / REQUEST_IN_PROGRESS；422 INVALID_REQUEST / GUARDRAIL_REJECTED / CONFIRMATION_REQUIRED；503 DATA_SOURCE_UNAVAILABLE。幂等域与处理顺序按 §8.7.3、§8.7.9；失败不推进状态 |
| `DELETE /api/v2/merchant/drafts/{draft_id}` | X-Session-Id 商家；路径draft_id:PublicId；查询/体无 | 204，无体 | 401；403角色错误 / RESOURCE_FORBIDDEN；409 ILLEGAL_STATE_TRANSITION（`APPLIED` 或 `EXPIRED`，details: DraftStateDetail）；422 INVALID_REQUEST；503 DATA_SOURCE_UNAVAILABLE。仅 `STAGED → DISCARDED`；对已 `DISCARDED` 的草稿重复请求仍返回 204（DELETE 天然幂等，§8.7.3）；无client_request_id |

排序：草稿 `created_at DESC, id DESC`。签名游标绑定端点、商家主体摘要、资源类型、筛选条件（state、kind）、语言与 limit，规则严格沿用 §8.7.4。

### 8.14 记忆、反馈与 MCP（组 7）

本节为 N1 纯模型契约，不挂载路由。全部请求、响应模型拒绝额外字段。时间带时区并归一化 UTC。
`FeedbackReaction`（`LIKE / DISLIKE`）沿用 v1 既有枚举；`ShopSlug`、`PublicId` 与 §8.8.1 定义相同。
`merchant_id`、`buyer_key` 不出现在任何请求或响应中。

#### 8.14.1 基础字段与模型

| 模型 | 字段、类型与范围 |
| --- | --- |
| `MemoryLayer` | `FACT / SUMMARY`（仅商家记忆有两层；顾客记忆只有事实层，PRD C7、D16） |
| `CustomerMemoryItem` | `id: PublicId`；`shop_slug: ShopSlug`；`category: string[1..64]`；`key: string[1..100]`；`value: string[1..500]`；`last_confirmed_at: UTC datetime`；`expires_at: UTC datetime`（= `last_confirmed_at` + 180 天；仅被读取不续期）。**不含 `buyer_key`、`merchant_id`** |
| `CustomerMemoriesResponse` | `memory_enabled: bool`；`memories: CursorPage[CustomerMemoryItem]`（§8.7.4） |
| `MemoryPreferenceRequest` | `enabled: bool`；`purge_confirmation: "yes"或null`（默认 null）。**条件必填**：`enabled=false` 时必须为 `"yes"`；`enabled=true` 时必须为 null。无客户端幂等键：设置绝对状态，天然幂等 |
| `MemoryPreferenceResponse` | `memory_enabled: bool`；`purged_count: int≥0`（本次清空的记忆条数；未关闭或本无记忆时为 0） |
| `MemorySourceRef` | `conversation_id: PublicId`；`message_id: PublicId`（事实来源于哪条商家消息） |
| `MerchantMemoryItem` | `id: PublicId`；`layer: MemoryLayer`；`category: string[1..64]`；`content: string[1..2000]`；`source_ref: MemorySourceRef或null`；`updated_at: UTC datetime`。约束：`layer=FACT` 时 `source_ref` 必填；`layer=SUMMARY` 时 `source_ref` 必须为 null |
| `MerchantMemoriesResponse` | `facts: CursorPage[MerchantMemoryItem]`（每项必须是 `FACT` 层）；`summaries: MerchantMemoryItem[]`（0–20 项，每项必须是 `SUMMARY` 层，`category` 不重复） |
| `MerchantMemoryDeleteResponse` | `deleted_id: PublicId`；`summary_rebuild_scheduled: bool`（删除事实来源会触发总结层重建） |
| `FeedbackKind` | `ADOPTION / REACTION`：采纳与赞踩是**不同语义，不得互相覆盖**，每次请求只改其中一种 |
| `V2FeedbackRequest` | `client_request_id` 按 §8.7.3，必填；`kind: FeedbackKind`；`adopted: bool或null`；`reaction: FeedbackReaction或null`；`reason: string[1..500]或null`（strip 后非空）。`kind=ADOPTION`：`adopted` 必填，`reaction` 与 `reason` 必须为 null。`kind=REACTION`：`adopted` 必须为 null，`reaction=null` 表示撤销赞踩，`reason` 仅在 `reaction` 非空时允许 |
| `V2FeedbackResponse` | `answer_id: PublicId`；`adopted: bool`；`reaction: FeedbackReaction或null`；`reason: string[1..500]或null`；`updated_at: UTC datetime`。总是返回两种反馈的当前完整状态 |
| `McpReadOnlyTool` | MCP 工具白名单，见 §8.14.3 |

#### 8.14.2 不变量

1. **商家记忆分两层**（PRD §8.1、M11）：事实层只存商家明确表达或确认的偏好，必带来源引用，可逐条删除；
   总结层是按类别管理的**可重建文档**，不承诺逐条删除，删除事实来源后重新生成。总结层条目不可作为删除目标
   （`DELETE /merchant/memories/{id}` 指向总结层返回 `422 INVALID_REQUEST`）。两层都不得回答规则、替代知识库或充当经营数字来源。
2. **顾客记忆按顾客 + 店铺双重隔离**（R5）：仅当前主体在当前店铺范围内可见，商家不可见；
   保留期 180 天、按最后确认或更新时间滚动、仅被读取不续期；**过期以业务路径自检 `expires_at` 为准，Cron 只负责清理**。
3. **关闭记忆须显式确认并清空**（PRD §11.2.2、C7）：`enabled=false` 缺少 `purge_confirmation` 返回 `422 CONFIRMATION_REQUIRED`
   （路由把该条件必填校验映射为此码，不是普通 `INVALID_REQUEST`）；关闭后清空已有记忆并不再写入。Agent 没有关闭记忆的工具，聊天中的确认不生效。
4. **反馈的采纳与赞踩互不覆盖**（PRD M13）：`kind` 决定本次只改哪一种；未涉及的一种保持原值，响应返回两者当前状态。
   反馈进入评测集前须脱敏并经人工确认（不属于本契约）。
5. **团队知识与商家记忆单向边界**：记忆**绝不升级写回团队知识库**；契约层不提供任何「提升为团队知识」的字段或端点。

#### 8.14.3 MCP 入口

`POST /api/v2/merchant/mcp` 是 MCP 的唯一入口，只暴露**只读工具子集**（PRD A8）。协议依据固定为官方 2026-07-28 发布说明
（`https://blog.modelcontextprotocol.io/posts/2026-07-28/`）；实施时若所选 SDK 仍默认旧协议，必须显式配置版本并增加握手被拒绝的反例测试。
本契约**不另造**与标准漂移的信封模型：请求与响应直接使用所选官方 SDK 的协议类型，本节只冻结它之外的边界。

- **协议版本固定 `2026-07-28`**：采用无协议会话的 Streamable HTTP；**不实现旧版 `initialize` / `initialized`，不接收也不签发 `Mcp-Session-Id`**。
  请求必须校验 `MCP-Protocol-Version: 2026-07-28`、`Mcp-Method`、`Mcp-Name` 与 JSON-RPC 2.0 正文的一致性，任一不一致按 JSON-RPC error 拒绝。
- **鉴权**：只认 `Authorization: Bearer <MCP access token>`，凭证独立、短期、可撤销，限定商家、scope 与有效期；**不接受 `X-Session-Id`**，
  不把浏览器会话交给第三方（AGENTS.md §8.3）。`merchant_id` 只从凭证解析。
- **凭证签发与撤销（PRD A8，2026-09-21 用户裁定）只经后端命令行脚本**，契约中**不存在**签发、撤销或查询凭证的 HTTP 路径，也没有自助页；
  原值只在签发时展示一次，库中只存哈希；撤销后的下一次请求立即返回 401，校验结果不缓存。
  有效期必须为正且**不超过 7 天**（签发脚本默认按命令行给定小时数，建议 24 小时）；商家停用或白名单收紧后，旧凭证随之失效
  （2026-10-03 实现时补录，N5 A）。
- **错误分层**：缺失或无效凭证在解析 JSON-RPC **之前**返回 HTTP `401` 并带 `WWW-Authenticate`；协议解析之后的方法、参数与工具错误使用 JSON-RPC error，
  **不包装成普通 v2 `ErrorResponse`**。该入口不支持 GET，返回 `405`（`Allow: POST`）。
  HTTP 层的其余状态（2026-10-03 实现时补录，N5 A 审查 F2）：
  - `429`：鉴权之前按来源限流（键为固定的 `mcp` + 客户端 IP，不含凭证，换 token 不换桶），沿用 v2 `ErrorResponse`；
  - `503`：凭证库不可用、无法鉴权，正文为 `id: null` 的 JSON-RPC error，不解析请求正文；
  - `400`：正文解析失败、批量请求、协议头与正文不一致或协议版本不受支持（JSON-RPC error，错误码沿用官方 SDK 定义）；
  - `413`：请求正文超过 256 KiB（JSON-RPC error）；
  - `202`：无 `id` 的通知在通过协议头校验后只确认、不处理，无正文。
  解析之后的任何意外错误都以 JSON-RPC `INTERNAL_ERROR` 答复，不外泄异常细节。
- **幂等**：本版只读、无写副作用，JSON-RPC `id` 只做请求/响应关联，不携带 `client_request_id`（§8.7.3）。
- **工具白名单**（`McpReadOnlyTool`，全部只读）：`query_metrics`、`attribute_change`、`get_inventory_alerts`、`get_product_content`、
  `list_coupons`、`get_metric_definition`、`search_rules`。`tools/list` 只返回白名单与凭证 `scopes` 的交集；`scopes` 只能是白名单的子集。
  **不在白名单内的**：一切 `draft_*` 写工具；`regenerate_brief` 与 `create_export`（虽是 `READ_ONLY`，但会写简报版本或导出记录，不属于纯读取）；
  `list_signals`（顾客派生数据不外发给第三方客户端）。工具名以 N3 实际注册表为准，不一致先改契约再动代码。
- **审批证据与确认令牌不得通过 MCP 获得**（§8.7.9）：MCP 工具结果、日志与审计元数据均不出现 `approval_evidence`、`confirmation_token`。
- 必须用标准 MCP 客户端做无 LLM 集成测试（N5）。

#### 8.14.4 逐路径契约

列表参数为 `cursor: string[1..2048]或null`（默认null）、`limit: int[1..100]`（默认20）。错误沿用 §8.3 ErrorResponse（MCP 入口除外，见上）。
401 为 `SESSION_REQUIRED / SESSION_INVALID`，403 角色错误为 `SESSION_ROLE_MISMATCH`；「演示顾客会话」指已绑定演示顾客的会话，
访客访问返回 `403 CUSTOMER_BINDING_REQUIRED`。资源不存在与越权统一 `RESOURCE_FORBIDDEN`、空 details。

| 方法与完整路径 | 鉴权、路径/查询/请求体 | 成功响应 | 错误、幂等与传输 |
| --- | --- | --- | --- |
| `GET /api/v2/shop/memories` | X-Session-Id 演示顾客；路径无；查询cursor/limit；体无 | 200 CustomerMemoriesResponse | 401；403角色错误 / CUSTOMER_BINDING_REQUIRED；422 INVALID_REQUEST / INVALID_CURSOR；503 DATA_SOURCE_UNAVAILABLE。仅本人本店；只读 |
| `DELETE /api/v2/shop/memories/{memory_id}` | X-Session-Id 演示顾客；路径memory_id:PublicId；查询/体无 | 204，无体 | 401；403角色错误 / CUSTOMER_BINDING_REQUIRED / RESOURCE_FORBIDDEN；422 INVALID_REQUEST；503 DATA_SOURCE_UNAVAILABLE。天然幂等，无client_request_id |
| `PUT /api/v2/shop/memory-preference` | X-Session-Id 演示顾客；路径/查询无；体 MemoryPreferenceRequest | 200 MemoryPreferenceResponse | 401；403角色错误 / CUSTOMER_BINDING_REQUIRED；422 INVALID_REQUEST / CONFIRMATION_REQUIRED（`enabled=false` 缺确认）；503 DATA_SOURCE_UNAVAILABLE。设置绝对状态，天然幂等，无client_request_id；关闭时清空与状态写入同一事务 |
| `GET /api/v2/merchant/memories` | X-Session-Id 商家；路径无；查询cursor/limit（分页作用于事实层）；体无 | 200 MerchantMemoriesResponse | 401；403角色错误；422 INVALID_REQUEST / INVALID_CURSOR；503 DATA_SOURCE_UNAVAILABLE。仅本店；只读 |
| `DELETE /api/v2/merchant/memories/{memory_id}` | X-Session-Id 商家；路径memory_id:PublicId；查询/体无 | 200 MerchantMemoryDeleteResponse | 401；403角色错误 / RESOURCE_FORBIDDEN；422 INVALID_REQUEST（目标是总结层）；503 DATA_SOURCE_UNAVAILABLE。天然幂等：重复删除同一事实仍 200 且 `summary_rebuild_scheduled=false`；无client_request_id |
| `POST /api/v2/merchant/answers/{answer_id}/feedback` | X-Session-Id 商家；路径answer_id:PublicId；查询无；体 V2FeedbackRequest | 200 V2FeedbackResponse | 401；403角色错误 / RESOURCE_FORBIDDEN；409 IDEMPOTENCY_KEY_REUSED / REQUEST_IN_PROGRESS；422 INVALID_REQUEST；503 DATA_SOURCE_UNAVAILABLE。幂等域按 §8.7.3；只有回答所属商家可提交 |
| `POST /api/v2/merchant/mcp` | `Authorization: Bearer <MCP access token>`；头 `MCP-Protocol-Version`、`Mcp-Method`、`Mcp-Name`；体 JSON-RPC 2.0（SDK 协议类型） | 200 JSON-RPC result 或 JSON-RPC error | HTTP 401 + `WWW-Authenticate`（凭证缺失、无效或已撤销，解析 JSON-RPC 前）；其余错误一律 JSON-RPC error；不接受 `X-Session-Id`；不签发 `Mcp-Session-Id`；无client_request_id |

排序：顾客记忆 `last_confirmed_at DESC, id DESC`；商家事实 `updated_at DESC, id DESC`；总结按 `category ASC`。
签名游标绑定端点、主体摘要（+店铺）、资源类型、语言与 limit，规则严格沿用 §8.7.4。

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
| B8 | 日报与商家记忆（附件/对象存储待办已由新 PRD 取消） | 历史 P1 |
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

- [x] 创建 v1 `AnswerMode` 与 Query Intent；`ATTACHMENT` 仅保留兼容枚举值，本版不产生；
- [x] 创建指标定义表和 Seed，含 `metric_code` 与 `display_name`；
- [x] **建立指标、维度、筛选三套白名单**（本阶段完成，不留到 B4）；
- [x] 创建知识文档表和旧 Wiki 导入脚本；
- [x] 实现 Metric Catalog；
- [x] 实现 Knowledge Retrieval 的两层检索（索引层 + 正文层，见 §6.5）；
- [x] 定义 LLM Client Protocol；
- [x] 实现 Fake LLM，并退役 B2 的 Fake Agent；
- [x] 实现 v1 DeepSeek OpenAI 兼容 Adapter，测试不启用真实调用；N1 将默认模型迁为
  `deepseek-flash` 并新增 Anthropic 兼容 Adapter，两种接口的真实冒烟测试均须另行取得 R3 授权；
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
- `MerchantQaGraph` 使用 LangGraph 的 12 节点骨架（见 §10）。B4/B5 未实现的节点仍产生可见步骤，所有尚未查询数据的 METRIC、DETAIL、IDENTITY 回答均以 `FALLBACK` 和明确降级原因返回。
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
  - [x] **已完成（2026-08-12，R9 Task 9）**：端点与聊天响应均返回双口径、维度、来源库表、关联报表、
        `generated` / `notice`；三级检索按正式目录、受控字段注释、明确标记的 LLM 候选执行，详见 §8.2。
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
- [x] 可配置最大质量循环次数 `QUALITY_MAX_ATTEMPTS`（代码最多 3 轮）；
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
- 最多执行 `QUALITY_MAX_ATTEMPTS` 次尝试（代码最大 3），达到上限后返回确定性 `DEGRADED` 摘要；
- 重试后通过返回 `PASSED`；上游、预算、缺 Reviewer 或校验用尽时返回可见的 `DEGRADED`；
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
- [x] 动态生成 CSV，不引入对象存储；本版继续使用限时签名下载并限制同步导出规模；
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

**历史说明：** 这是旧单端 MVP 的最后一步，已完成。新路线的部署拓扑与交付顺序以 PRD N1–N5 为准；
本段 P0/M0–M5 术语不得用于新需求排期。

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
- [x] 本版不保存正式附件；导出按请求生成，不把容器临时磁盘当持久存储。

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

**N5 B Task 3 扩展（2026-10-03 契约先行，PRD §10.2、§10.4、D-N5-1）。** 只**新增**字段，既有字段语义不变；
本端点仍是 `require_admin_or_viewer_token` 之外的**仅管理员**端点（`VIEWER_TOKEN` 403，见 R6 例外的范围）：

| 新增字段 | 类型 | 语义 |
| --- | --- | --- |
| `budget_levels` | `BudgetLevelStatus[]` | 当日三级预算各行：`level`（`GLOBAL / ROLE / SHOP`）、`scope`（`GLOBAL`、`ROLE:CUSTOMER`、`ROLE:MERCHANT`，或店铺级的脱敏标识 `SHOP:<角色>:<商家 ID 的 SHA-256 前 8 位>`）、`budget_tokens`、`used_tokens`、`remaining_tokens`。店铺级只列当日已有用量的行，按 `used_tokens` 降序，最多 20 行 |
| `llm_cost_today` | `CostByCurrency[]` | 当日已定价用量的成本合计：`currency`、`amount`（十进制字符串，8 位小数）；未定价的用量（`cost` 为 NULL）不计入，另由 `unpriced_calls_today` 说明 |
| `unpriced_calls_today` | `int≥0` | 当日成本为 NULL 的调用数（用量未知或缺价格版本），避免把「未定价」误读为 0 |
| `cache_hit_tokens_today` | `int≥0` | 当日记录到的缓存命中 token；`cache_hit_rate_today` 为它占输入 token 的比例，没有输入时为 `null` |
| `tool_calls_total`、`tool_errors_total` | `int≥0` | 进程启动以来工具调用总数与失败数（含参数校验失败与护栏拒绝；闸门拦截的安全事件计入失败） |
| `route_p95_ms` | `object<string, number>` | 各路由最近至多 500 次请求的 p95 耗时（进程内近似值，多实例不同步，同 `route_average_ms` 的约束） |


**2026-10-04 再扩展（验收矩阵 §12.6「看板展示每回合 token、成本、耗时、降级原因」，契约先行）。** 同样只新增字段：

| 新增字段 | 类型 | 语义 |
| --- | --- | --- |
| `turns_today` | `int≥0` | 当日发生过模型调用的对话回合数：`llm_usage` 中 `purpose = AGENT` 的不同追踪 ID 数 |
| `avg_tokens_per_turn_today` | `number \| null` | 当日 `AGENT` 用量的 token 合计 ÷ `turns_today`；没有回合时为 `null`，不显示为 0 |
| `avg_cost_per_turn_today` | `CostByCurrency[]` | 当日已定价 `AGENT` 用量的成本 ÷ `turns_today`，按币种；金额为十进制字符串（8 位小数） |
| `avg_turn_elapsed_ms_today` | `number \| null` | 当日已完成回答的平均耗时（`answers.elapsed_ms`，v1 与 v2 一并统计）；没有回答时为 `null` |
| `degraded_reason_counts` | `object<string, int>` | 进程启动以来**整轮降级**按原因码计数。v2 用 `DegradeReason`（`UPSTREAM / VALIDATION / BUDGET / LIMIT / TIMEOUT / CANCELLED`）；v1 回合统一记为 `V1`（v1 响应只有文案，没有原因码）；缺原因码记 `UNKNOWN`。各项之和等于 `degraded_count` |
| `source_degraded_counts` | `object<string, int>` | 进程启动以来回答**未整轮降级**、但某个来源降级的次数，按来源（如 `KNOWLEDGE` 的关键词兜底）计数；与整轮降级分开统计 |

`degraded_count` 的语义修正：此前只有 v1 回合计入，v2 两端的回合从不计数（看板恒为偏低）；自本次起 v1 与 v2 的整轮降级都计入。
同一 `client_request_id` 的幂等重放不重复计数。前四项读数据库（跨实例一致），后两项与 `degraded_count` 是进程内近似值。
这些字段只有计数与平均值，不含回答正文、提问文本、商家或顾客标识。

禁止返回项不变：响应中不得出现任何 Token、Prompt、经营数据、完整请求正文与连接串；店铺级只给脱敏标识，不给商家 ID 或名称。

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
- **`docs/PRD.md` §12 中适用于 v1 迁移基线的验收条目通过。到此后端 v1 基线完成；新路线按 N1–N5 另行验收。**

---

## B8 · 日报与商家记忆（旧路线历史阶段）

本节保留已完成的日报与商家记忆实施记录。原附件、对象存储与 OCR 待办已被 PRD D6 取代，
不再属于当前开发计划；未来如重启必须新建需求与契约，不得从历史勾选框直接开工。

### Daily Report

- [x] `GET /api/reports/daily`：仅商家认证，不接受 `merchant_id` 或日期参数，固定返回业务时区昨日；
- [x] 按固定顺序返回 `gmv` 、`ordering_user_count` 、`order_count` 、`successful_order_count` 、`return_count` 、`refund_amount`；响应的 `metrics` 是含 `metric_code` 的数组；
- [x] 日报建议固定两条：第一条按退款金额分支，第二条仅按工单占订单量是否超过 20% 分支；无近七日数据或查询失败均显式降级，不伪造零指标；
- [x] 为每个商家建立唯一 `DAILY_REPORT` 系统会话；`daily-report:{report_date}` 复用既有 `answers` 幂等约束，并发首次请求回读胜出的已物化结果；
- [ ] `POST /api/admin/reports/daily/recompute`：仅 `X-Admin-Token`；校验演示商家、日期窗口和 1–200 字符 `reason`，在无反馈时锁定、删除并重新物化指定日报；已有反馈返回 `409 DAILY_REPORT_FEEDBACK_CONFLICT`，成功与拒绝范围均写独立管理员审计。该端点没有前端消费者，精确字段见 `docs/specs/2026-08-24-daily-report-recompute-contract.md`。
- [x] **日报建议复用回答反馈通道**：日报响应返回可反馈的 `answer_id`，前端"采纳"直接调用 `POST /api/answers/{id}/feedback`，不新增反馈接口；
- [x] 本阶段不引入 Railway Cron、Worker、Redis 或推送；按需在后续业务要求中另行设计。

### 商家记忆闭环

**已完成（2026-08-20）**：`merchant_memories` 已由独立迁移创建；成功回答持久化后通过
`BackgroundTasks` 异步提交 `MemoryAgent`，使用独立数据库 Session 与单次 LLM 预算完成按
`(merchant_id, category)` 覆盖式压缩。团队知识优先，未命中才按已验证的 `merchant_id` 读取记忆，
命中记忆时 `analysis_sources` 返回 `MEMORY`；每日预算耗尽、数据库或模型异常只记录日志，绝不影响主回答。
本轮没有调用真实模型，记忆压缩的真实模型验收仍须按 R3 单独申报。

商家记忆向新路线迁移时仍需完成：

| 环节 | 要求 |
| --- | --- |
| Memory Extraction | ✅ 从**已成功回答的会话**中提取，不从原始用户输入直接提取；有独立 Prompt；真实模型验收待 R3 单独申报 |
| Memory Validation | 提取结果必须通过结构校验和白名单检查；**不得把未审核的模型输出升级为团队知识** |
| Memory Persistence | ✅ 写入时机为一轮问答成功落库之后的异步任务；以 `(merchant_id, category)` 唯一约束保证覆盖写入 |
| Memory Retrieval | ✅ 检索优先级：团队知识 > 商家记忆；命中记忆时 `analysis_sources` 含 `MEMORY` |
- [ ] 压缩与去重：同一事实重复出现时合并，不无限增长；
- [ ] 过期策略：超过保留期的记忆自动失效；
- [ ] 提取失败时静默降级，不影响主回答链路；
- [ ] 必测：记忆提取、召回、压缩各一条；提取失败不影响主回答，过期记忆不再进入 Prompt。

### 后台执行边界

本版不创建通用 Worker。N4 记忆抽取与 N5 简报/汇总/过期清理使用幂等短任务和数据库锁；
Railway Cron 不等于队列 Worker。只有异步导出、持久文件处理等新需求重新进入 PRD 时，
才评审 Redis、队列、死信和独立 Worker。

### 验收

- 无数据时返回正常日报而非 500；
- 日报返回的 `answer_id` 可以正常提交反馈；
- 昨日区间按 `Asia/Shanghai` 计算，冻结时钟测试通过；
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
  → prefilter_question            # 零 LLM 前置闸门：范围外提问在此拒绝，见下方说明
  → classify_intent               # 仅放行分支到达；拒绝分支直接跳到 suggest_questions
  → understand_intent
  → validate_intent
  → retrieve_knowledge_detail     # 第二层：业务域已知，加载对应正文
  → query_data
  → compose_answer
  → quality_loop                  # 生成 → 本地校验 → 独立复核 → 回喂重试
  → suggest_questions             # 从预置配置取，不调用 LLM；闸门拒绝分支也会经过这里
  → persist_answer
  → END
```

四点说明：

- **知识检索拆成两个节点。** 索引层必须在 `classify_intent` 之前——业务域未知时，索引给模型提供拆词和领域识别所需的词汇；正文层必须在意图确定之后，否则会把全部知识灌进 Prompt。参考实现的顺序与此一致，见 §6.5。
- **`decide_retry` 的上限写进分支条件**，不只写在文字说明里，避免实现时漏掉而形成无限循环。
- **`suggest_questions` 是独立节点且不调用 LLM**，位置与参考实现的 `suggestQuestions()` 一致，见 §6.8。
- **`prefilter_question` 是唯一的条件边节点。** 它对问题与业务知识库/指标目录/商家历史记忆做加权打分（不调用 LLM），命中判为范围外时直接返回 `answer_mode=INVALID`（复用既有 INVALID 契约，不新增字段），并跳过 `classify_intent` 到 `quality_loop` 之间的全部节点，直达 `suggest_questions`；问候语、同会话已有历史轮次，以及语料完全不可用（如全新部署或知识库为空）时一律 fail open 放行。默认阈值与开关见 `QUESTION_PREFILTER_MIN_SCORE` / `QUESTION_PREFILTER_ENABLED`，设计细节见 `openspec/changes/add-question-prefilter-gate/design.md`。

每个节点完成时向 SSE 推送一个 `step` 事件（见 §8.4）。

### AgentState 最低字段

```text
request_id
merchant_context
session_context
question
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
- [ ] 达到 `QUALITY_MAX_ATTEMPTS` 后返回确定性降级摘要；
- [ ] 每日预算熔断后的降级；
- [ ] 商家记忆提取、召回、删除与跨商家隔离；

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
LLM_MODEL=deepseek-flash
LLM_ENABLED=false
BUSINESS_TIMEZONE=Asia/Shanghai
DEMO_MERCHANT_TOKENS=<token:merchant_id,token:merchant_id,token:merchant_id>
DEMO_MERCHANTS_ENDPOINT_ENABLED=true
DEMO_DEPLOYMENT_MODE=false             # 仅对外演示部署时显式开启
ADMIN_TOKEN=<development-placeholder>   # 运维、知识后台与评测管理复用；请求头 X-Admin-Token
EXPORT_URL_TTL_MINUTES=15
MAX_QUERY_DAYS=180
MAX_DETAIL_ROWS=200
QUALITY_MAX_ATTEMPTS=3
MAX_LLM_CALLS_PER_REQUEST=10
MAX_LLM_TOKENS_PER_REQUEST=<int>
LLM_DAILY_BUDGET_TOKENS=<int>
RATE_LIMIT_PER_MINUTE=<int>
TRUSTED_PROXY_HOPS=1
REDIS_URL=<optional>
```

`JWT_SECRET` 已移除——MVP 不做 JWT 登录，商家身份来自演示 Token 白名单（见 §6.1）。

`LLM_API_KEY` 的值是 DeepSeek API Key。OpenAI 兼容 Adapter 使用根地址，Anthropic 兼容 Adapter
使用根地址下的 `/anthropic` 端点；默认模型为 `deepseek-flash`。新配置不得使用已弃用的
`deepseek-chat`、`deepseek-reasoner` 或退役兼容别名 `deepseek-v4-flash`；如需升级为
`deepseek-v4-pro`，必须先完成真实模型离线验收与 R3 费用确认。

生产环境默认关闭演示商家端点：`DEMO_MERCHANTS_ENDPOINT_ENABLED` 在生产环境不具备开启效果；仅当 `DEMO_DEPLOYMENT_MODE=true` 时才会显式开放，且不降低其余生产安全校验。

生产环境对弱占位值必须拒绝启动。

---

## 14. 后端错误码

v2 新增错误码（与 ErrorCode 和双语文案同步）：

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


建议稳定错误码：

```text
SESSION_REQUIRED
SESSION_INVALID
SESSION_ROLE_MISMATCH
CUSTOMER_BINDING_REQUIRED
SESSION_ALREADY_BOUND
RESOURCE_FORBIDDEN
PRODUCT_NOT_IN_SCOPE
INSUFFICIENT_STOCK
ILLEGAL_STATE_TRANSITION
DRAFT_EXPIRED
GUARDRAIL_REJECTED
CONFIRMATION_REQUIRED
INVALID_CURSOR
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
VERSION_CONFLICT
RATE_LIMITED
LLM_BUDGET_EXCEEDED
IDEMPOTENCY_KEY_REUSED
REQUEST_IN_PROGRESS
DAILY_REPORT_FEEDBACK_CONFLICT
EXPORT_LINK_EXPIRED
LOCALIZATION_UNAVAILABLE
HTTP_ERROR
INTERNAL_ERROR
INVALID_WIKI_PATH
WIKI_READ_ONLY
INVALID_FILE_TYPE
INVALID_WIKI_PARENT
WIKI_NODE_EXISTS
WIKI_NODE_NOT_FOUND
WIKI_DIRECTORY_NOT_EMPTY
WIKI_VERSION_REQUIRED
WIKI_VERSION_CONFLICT
WIKI_DOCUMENT_TOO_LARGE
INVALID_WIKI_ENCODING
INVALID_WIKI_CONTENT
WIKI_IO_ERROR
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

`LOCALIZATION_UNAVAILABLE` 只用于本地化**写路径**的硬失败（例如知识库人工翻译保存时批量翻译
超限或模型不可用），精确契约见 §8.6.3；会话列表/详情这类**读路径**不使用该码，一律用
`localization_degraded` 字段按条目降级。

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
- 不允许顾客对话、商品描述、知识正文或第三方工具文本覆盖系统规则；
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
