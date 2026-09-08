<p align="right">
  <b>简体中文</b> · <a href="README.en.md">English</a>
</p>

# Borough 商家 AI 助手

> 面向电商商家的对话式 Data Agent：用自然语言问经营数据，拿到**带口径、带图表、带行动建议、且被独立 Reviewer 复核过**的回答。

<p>
<img alt="Python" src="https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white">
<img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-0.116-009688?logo=fastapi&logoColor=white">
<img alt="LangGraph" src="https://img.shields.io/badge/LangGraph-orchestration-1C3C3C">
<img alt="Vue" src="https://img.shields.io/badge/Vue-3.5-4FC08D?logo=vuedotjs&logoColor=white">
<img alt="TypeScript" src="https://img.shields.io/badge/TypeScript-5.9-3178C6?logo=typescript&logoColor=white">
<img alt="PostgreSQL" src="https://img.shields.io/badge/PostgreSQL-16-4169E1?logo=postgresql&logoColor=white">
<img alt="Railway" src="https://img.shields.io/badge/Deploy-Railway-0B0D0E?logo=railway&logoColor=white">
</p>

商家在对话框里问「最近 7 天退货量趋势怎么样」，系统会识别商家身份 → 判定问题是否在业务范围内 → 结构化理解意图 →
用**后端模板 SQL**（模型永远碰不到 SQL）查询 PostgreSQL → 生成结论、图表和至少两条有数据依据的建议 →
交给独立 Reviewer 复核 → 落库并异步沉淀商家记忆。任何一环不可用都会**显式降级并在界面上说明原因**，
而不是编造一个像样的答案。

---

## 目录

- [项目简介](#项目简介)
- [核心能力](#核心能力)
- [系统架构](#系统架构)
- [Agent 问答流水线](#agent-问答流水线)
- [安全与成本设计](#安全与成本设计)
- [技术栈](#技术栈)
- [快速开始](#快速开始)
- [测试与质量门禁](#测试与质量门禁)
- [API 一览](#api-一览)
- [部署](#部署)
- [目录结构](#目录结构)
- [文档索引](#文档索引)

---

## 项目简介

Borough 商家 AI 助手是一个面向电商商家的对话式 Data Agent。商家用自然语言提问，
系统负责把问题变成受控的数据查询，并给出带口径、带图表、带行动建议的回答。

它针对的是商家日常经营分析里几个具体的问题：

- 经营数据分散在订单、退款、商品、优惠券、工单等多张表里，跨业务分析成本高；
- 商家不知道指标是怎么算出来的，也不应该接触数据库细节，更不该去写 SQL；
- 指标回答常常只有一个数字，缺少口径、趋势解释和「接下来该做什么」；
- 平台规则和指标口径散落在文档与个人经验里，问一次要找很久；
- 把 LLM 直接接上数据库，会带来误解问题、编造字段、算错数和越权查询的风险。

技术选型上刻意保持很小的组件面：Python + TypeScript，单一 PostgreSQL 承担全部存储职责，
不额外引入分析型数据库或数据管道；Redis、异步 Worker 和对象存储都按真实需求逐步接入，
而不是一开始就摆上。组件少，理解、开发、测试和部署的门槛都会低很多。

`Borough` 是本项目虚构的电商平台 IP；演示商家与全部经营数据均为**程序生成的虚构数据**，
不含任何真实商家信息。演示身份用 Token 白名单直接映射到三个虚构商家（顶栏可切换，
用于验证数据隔离），不需要注册登录。

## 界面

<img src="docs/images/01-assistant.png" alt="Borough 商家 AI 助手主界面">

<p align="center"><i>助手主界面：左栏每日经营日报与指标口径，中栏对话与 12 步质量轨迹，右栏行动建议与「猜你想问」</i></p>

| Chat BI 运营看板 | 知识库维护后台 |
| :---: | :---: |
| <img src="docs/images/04-ops-dashboard.png" alt="Chat BI 运营看板"> | <img src="docs/images/03-knowledge-base.png" alt="知识库维护后台"> |
| 六项北极星指标、日趋势与分类下钻；样本不足时显示「样本不足」而不是伪造 0% | 固定三根目录树、业务域四板块、文档编辑与只读记忆 |

<table>
<tr>
<td width="26%"><img src="docs/images/02-chart.png" alt="指标图表面板"></td>
<td>

**指标图表**

字段只能取自后端已登记的维度与指标列，模型无法指定任意列；可切换的图表类型由后端
`allowed_types` 决定。摘要与明细表共用同一套数字格式，不会把浮点求和的误差尾数写给用户。

</td>
</tr>
<tr>
<td width="26%"><img src="docs/images/05-mobile.png" alt="移动端布局"></td>
<td>

**移动端**

三栏在窄屏收敛为对话优先的单列布局，指标口径、图表与建议改为随对话展开，
输入区固定在底部。

</td>
</tr>
</table>

## 核心能力

### 对话与分析

- **六类回答模式**：`METRIC` 指标趋势 / `DETAIL` 业务明细 / `RULE` 平台规则 / `IDENTITY` 商家资料 /
  `CHAT` 普通对话 / `INVALID` 范围外拒答，路由由结构化意图决定；
- **指标查询**：GMV、订单量、退货量、退款金额、工单量等，支持趋势、分类维度、环比与同比；
- **指标口径**：同时给出业务口径与 SQL 口径（13 字段），命中指标目录 / 知识库 / 模型生成三级检索，
  来源与是否为生成口径均对用户可见；
- **明细与导出**：订单、退款、商品、优惠券、工单五类明细；CSV 导出走 HMAC 签名 URL、15 分钟过期、
  UTF-8 BOM，并做了公式注入防护；
- **图表**：折线 / 柱状 / 饼图，字段只能取自已登记的维度与指标列，模型无法指定任意列；
- **经营建议**：至少两条带数据依据的行动建议；
- **质量轨迹**：界面显示 12 个真实处理阶段、质量状态（`PASSED` / `DEGRADED` / `FAILED` / `NOT_RUN`）、
  复核轮次与降级原因；
- **反馈闭环**：采纳 / 点赞 / 点踩，幂等写入，跨商家操作 403 并记审计。

### 平台能力

- **每日经营报告**：固定返回 `Asia/Shanghai` 昨日的六项指标与两条确定性建议，结果按
  `daily-report:{date}` 幂等物化，全程不调用 LLM；
- **商家记忆**：回答成功后异步沉淀同商家同分类的历史问答；团队知识优先、商家记忆仅作回退，
  **绝不反向写回团队知识库**；
- **「猜你想问」**：按同商家同分类的历史高频问题排序，聚合与排序全部下推 SQL；统计失败时用
  savepoint 隔离并回落静态推荐，不污染主聊天事务；
- **知识库维护后台**：管理员令牌进入，固定三根目录树、业务域四板块、文档 CRUD、`If-Match` 乐观锁
  与 412 冲突保留输入；
- **Chat BI 运营看板**：采纳率、准确率、平均思考时长、问题命中率、回答失效率等北极星指标，
  按「日 × 商家 × 分类」幂等汇总，支持分类下钻与重刷 Job。

## 系统架构

```mermaid
flowchart LR
    U["商家浏览器<br/>Vue 3 + Pinia + ECharts"]
    C["Caddy 静态托管"]
    A["FastAPI<br/>鉴权 / 限流 / 费用守卫"]
    G["LangGraph 问答图<br/>12 节点"]
    L["DeepSeek<br/>OpenAI 兼容 API"]
    Q["SafeQueryService<br/>白名单 + 模板 SQL"]
    K["知识库 / 指标目录 / 商家记忆"]
    P[("PostgreSQL")]

    U --> C
    U -- "SSE / JSON" --> A
    A --> G
    G -- "结构化意图（非 SQL）" --> L
    G --> K
    G --> Q
    Q --> P
    K --> P
    A --> P
```

要点：

- **前端不代理 API**。Caddy 只托管静态产物，浏览器直连后端公网地址，因此 CORS 只允许精确 Origin，
  且漏配 `VITE_API_BASE_URL` 会**响亮失败**，而不是把请求打到静态服务器上静默拿 404；
- **类型单向流动**：`OpenAPI → api/generated.ts → api/adapters/*.ts → types/*.ts → Store → 组件`。
  组件不得直接消费生成类型，Adapter 是唯一转换点且每个都配契约测试——后端字段一变，契约测试立刻爆红；
- **ORM 与 API Schema 分离**，ORM 对象永不直接作为外部协议。

## Agent 问答流水线

```text
load_context → retrieve_knowledge_index → prefilter_question ─┬→ classify_intent → understand_intent
                                                              │  → validate_intent → retrieve_knowledge_detail
                                                              │  → query_data → compose_answer → quality_loop ─┐
                                                              │                                                ↓
                                                              └───────────（零 LLM 拒答）──────────→ suggest_questions → persist_answer
```

两个值得单独说的节点：

**`prefilter_question` —— 零 LLM 的问题范围前置闸门。**
在它出现之前，「CNN 和 RNN 的区别」这类明显无关的提问也会至少触发一次真实模型调用，没有任何路径能零成本拒绝。
现在用零依赖 n-gram 切词，对问题与知识文档标题 / 路径、指标目录的 `display_name` / `metric_code`、
商家历史记忆做加权打分，低于阈值时经条件边直接跳过全部会调用 LLM 的节点。
**不用黑名单**（无关词汇无法穷举），而是白名单打分 fail-closed，并在三处 fail open：
语料完全不可用（全新部署 / 知识库为空）、问候语、同会话已有历史轮次——最后一条是为了避免
「那上个月呢？」这类不含业务词的合法追问被误拒。真实模型验收中，3 道范围外问题均为 **0 次 LLM 调用**。

**`quality_loop` —— 生成 → 本地确定性校验 → 独立 Reviewer → 回喂重试 → 兜底。**
降级原因分 `UPSTREAM` / `VALIDATION` / `BUDGET` 三类，轮次由 `QUALITY_MAX_ATTEMPTS` 注入。
受控降级只汇总来自本次查询的事实；明细被截断时**不提供不完整的总计**。

## 安全与成本设计

这部分是本项目着力最多的地方，也是把一个 LLM Demo 和一个敢对外开放的服务区分开的地方。

| 风险 | 设计 |
| --- | --- |
| 模型生成任意 SQL | 模型**只能**输出经 Pydantic 校验的结构化查询意图；SQL 由后端模板生成，表名列名走白名单、值全部绑定、日期范围与最大行数由后端强制 |
| 跨商家越权 | `merchant_id` 只从 Bearer Token 解析，**永不采信前端传入**；所有经营查询强制注入商家范围，跨商家访问返回 403 并落 `audit_logs` |
| 被刷爆 token | 三层闸门：单请求 LLM 调用次数上限（最坏路径 10 次，已与两套重试的乘加关系对齐）、单请求 token 上限、全局每日 token 预算熔断；再叠加上面的零 LLM 前置闸门 |
| 提示词注入 / 越权读取 | 知识与记忆按商家隔离检索；日志脱敏，不记录隐私字段与完整查询结果 |
| 管理接口与商家接口混淆 | **两套独立凭证**：商家走 `Authorization: Bearer`，管理端走 `X-Admin-Token`，后端对 `/api/admin/*` 只认后者；`ADMIN_TOKEN` 未配置时整个 admin 路由**不挂载**（返回 404 而非 401，避免暴露端点存在性） |
| 只读演示需求 | 可选 `VIEWER_TOKEN` 与管理员令牌共用请求头，但后端只放行其中的 GET，写操作、记忆压缩、运维状态一律拒绝；两者取值相同时启动即拒绝 |
| 降级被伪装成正常回答 | `analysis_sources` / `thinking_steps` / `quality_status` / `quality_notes` / `degraded` / `degraded_reason` 全部进入 API 契约并在界面渲染；**不得把规则兜底包装成模型分析** |
| 导出链接泄露 | 签名 URL：HMAC + 15 分钟 TTL，是唯一不要求请求头的鉴权路径 |
| 代理头伪造 | 只信任平台注入的转发头（`TRUSTED_PROXY_HOPS`），本地开发一律不信任客户端 `X-Forwarded-For` |
| 密钥进代码 | 全部密钥只来自环境变量 / Railway Variables，`.env.example` 只放占位符；构建产物由 `secrets:check` 递归扫描 JS / CSS / HTML / JSON / sourcemap 拦截 |

## 技术栈

**后端**　Python 3.12 · FastAPI · Pydantic v2 · SQLAlchemy 2（async）· Alembic · psycopg · LangGraph ·
structlog · pytest · Ruff · mypy（strict）

**前端**　Vue 3 · TypeScript · Vite · Pinia · Vue Router · ECharts · Zod · Vitest · Playwright · ESLint · Prettier

**数据与基础设施**　PostgreSQL 16 · Docker · Caddy · Railway（Frontend / Backend / Cron）

**模型**　DeepSeek（OpenAI 兼容 Chat Completions），默认 `deepseek-v4-flash`

## 快速开始

### 前置

Python 3.12、[uv](https://github.com/astral-sh/uv)、Node.js 20+、Docker。

```powershell
git clone https://github.com/XuZiHan-010/shopping_assistant.git
cd shopping_assistant
```

### 1. 启动 PostgreSQL

```powershell
docker-compose -p borough up -d postgres   # 监听 127.0.0.1:55432
```

### 2. 启动后端

```powershell
cd backend
uv sync

$env:DATABASE_URL = 'postgresql+psycopg://borough:borough_local@127.0.0.1:55432/borough_test'
$env:FRONTEND_ORIGIN = 'http://localhost:5173'
$env:DEMO_MERCHANT_TOKENS = '{"merchant-100-token":"00000000-0000-0000-0000-000000000001","merchant-101-token":"00000000-0000-0000-0000-000000000002","merchant-102-token":"00000000-0000-0000-0000-000000000003"}'

uv run alembic upgrade head
uv run python -m app.run                   # http://127.0.0.1:8000
```

验证：`GET /api/health`（不查库、不调 LLM）、`GET /api/ready`（只执行 `SELECT 1`）。

> **Windows 注意**：psycopg 的异步模式跑不了默认的 `ProactorEventLoop`。新增入口时必须显式选择事件循环
> （见 `backend/app/core/runtime.py`），否则会表现为 `/api/ready` 返回 503。

### 3. 灌入演示数据

```powershell
# 仓库根目录
uv run --project backend python scripts/seed_demo_data.py --seed      # 三个虚构商家

cd backend
# 180 天经营数据。日常由 app.jobs.seed_demo_rolling 增量滚动维护，
# 全量重灌会抹掉历史，因此必须显式传 --force-full-rebuild
uv run python -m scripts.seed_demo_analytics --force-full-rebuild

# 团队业务知识文档，指向一个存放 Markdown 的目录
uv run python -m scripts.import_wiki --root <知识库目录>
```

> 全量 pytest 会清空 `knowledge_documents` 与经营数据表，跑完测试后需要重新执行后两条。

### 4. 启动前端

```powershell
cd frontend
npm ci
npm run dev                                # http://localhost:5173
```

前端通过 `VITE_API_BASE_URL` 指向后端地址；它没有同源 `/api` 回退，缺失时会直接报错。

### 5.（可选）接入真实模型

不配置 `LLM_API_KEY` 时系统走确定性 Fake Client，全流程可跑通且不产生任何费用。接入真实 DeepSeek：

```text
LLM_API_KEY=<deepseek-api-key>
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-v4-flash
LLM_ENABLED=true
```

完整环境变量清单见 [`.env.example`](.env.example)，其中逐条注释了每个阈值为什么取当前值——
例如 `LLM_MAX_OUTPUT_TOKENS_PER_CALL` 取字段上限 8000，是因为推理模型会把偏低的配额耗尽在 reasoning 上、
正文返回空串，进而让整条链路必然降级。

## 测试与质量门禁

自动化测试**全部使用 Fake / 确定性 LLM，不产生任何模型费用**。

```powershell
# 后端
cd backend
uv run ruff check . ; uv run ruff format --check . ; uv run mypy app
uv run pytest                                     # 无真实测试库时集成用例自动跳过
$env:REQUIRE_INTEGRATION_DB = '1'; uv run pytest  # CI 必须这样跑：库连不上直接硬失败

# 前端
cd frontend
npm run lint ; npm run typecheck ; npm run test
npm run test:e2e            # Playwright（Mock API）
npm run codegen:check       # generated.ts 是否与 OpenAPI 脱节
npm run fixtures:check      # Adapter 契约 fixture 是否过期
npm run firstpaint:check    # 阻止 ECharts 被带进首屏静态依赖链
npm run secrets:check       # 扫描 dist/ 是否混入密钥形态字符串
npm run mock:check          # 阻止 mock 载荷进入生产构建
```

最近记录的结果：带真实 PostgreSQL 的后端全量回归 **1049 passed / 0 failed / 0 skipped**（2026-08-24）；
最近一次改动后为后端 **941 passed**（未启动集成库时另有 212 skipped）、前端 Vitest **353 passed**、E2E **29 passed**。

几条从踩坑里固化下来的测试约束：

- **集成测试必须连真实 PostgreSQL，不用 SQLite**——商家隔离、迁移和 Seed 的验收全在这些用例里；
- **`FakeLlmClient` 会掩盖整类缺陷**：它返回预写好的合法 JSON，于是「提示词到底有没有告诉模型该输出什么」
  在自动化测试里完全不可见。因此新增或修改任何提示词，必须同时加一条**从 Pydantic 模型推导期望值**的
  提示词契约测试；
- **门禁全绿不等于行为正确**：曾有一处 `history=[]` 在 899 项全绿的前提下存活数周。凡是「本该传值、
  实际传了空值」的形参，都要有断言输入内容的测试，而不只断言不抛异常。

## API 一览

完整契约由 FastAPI 自动导出到 [`docs/api.md`](docs/api.md) 与 [`docs/api.json`](docs/api.json)。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/api/chat` | 默认 SSE 流（`step` / `done` / `error`）；`Accept: application/json` 走同步路径，`done` 载荷与之完全一致 |
| `GET` | `/api/conversations`、`/api/conversations/{id}` | 会话列表与详情 |
| `DELETE` | `/api/conversations/{id}` | 删除会话 |
| `POST` | `/api/answers/{id}/feedback` | 采纳 / 点赞 / 点踩（幂等） |
| `GET` | `/api/exports/{id}` | 签名 CSV 下载（唯一免请求头的鉴权路径） |
| `GET` | `/api/metrics/{code}` | 指标口径（路径参数是 `metric_code`，不是中文指标名） |
| `GET` | `/api/reports/daily` | 每日经营报告 |
| `GET` | `/api/demo/merchants` | 演示商家列表（生产环境默认关闭） |
| `GET` | `/api/health`、`/api/ready` | 健康检查 / 就绪探针 |
| `GET` `POST` `PUT` `DELETE` | `/api/admin/knowledge/*` | 知识库目录树、文档 CRUD、业务域维护、记忆压缩 |
| `GET` `POST` | `/api/admin/analytics/chatbi/*` | Chat BI 总览、分类下钻、汇总重刷 |
| `POST` | `/api/admin/reports/daily/recompute` | 重算指定商家日报 |
| `GET` | `/api/admin/ops/status` | 预算余量、限流命中与降级计数（不返回 Token、Prompt 或经营数据） |

## 部署

Railway 上运行四类服务：`frontend`（Node 多阶段构建 → `caddy:2-alpine`）、`backend`、PostgreSQL，
以及两个独立 Cron（演示数据滚动 Seed、Chat BI 日汇总）。配置即代码在 `frontend/railway.json`、
`backend/railway.json`、`backend/railway.cron.json`、`backend/railway.chatbi-cron.json`，
运维手册见 [`docs/deployment.md`](docs/deployment.md)。

几个已定的约束：

- 镜像构建期**不跑 codegen**——Railway 的前端构建上下文里没有仓库根的 `docs/`，因此
  `src/api/generated.ts` 是提交进仓库的生成产物，由 `codegen:check` 保证它不过期；
- `VITE_API_BASE_URL` 在构建期注入静态产物，必须由 Railway Variables 提供；
- 数据库迁移在发布阶段执行，不由每个 Worker 并发执行；
- 附件不依赖容器临时磁盘。

## 目录结构

```text
merchant_assistant/
├── backend/                    # FastAPI 后端
│   ├── app/
│   │   ├── agent/              # LangGraph 问答图、状态、前置闸门与各节点
│   │   ├── api/routes/         # chat / conversations / metrics / exports / reports / admin ...
│   │   ├── services/           # safe_query · answer · review · quality_loop · memory · chatbi ...
│   │   ├── intent/             # 结构化意图模型与白名单校验
│   │   ├── repositories/       # 数据访问（商家隔离在此强制）
│   │   ├── analytics/          # 指标公式与演示数据生成
│   │   ├── llm/                # DeepSeek Client 与费用守卫
│   │   ├── jobs/               # 滚动 Seed、Chat BI 汇总 CLI
│   │   └── knowledge/ prompts/ models/ schemas/ core/ db/
│   ├── migrations/             # Alembic
│   └── tests/                  # unit / integration / api / agent
├── frontend/                   # Vue 3 前端
│   ├── src/
│   │   ├── views/              # AssistantView · KnowledgeBaseView · OpsDashboardView
│   │   ├── components/         # chat / insights / knowledge / analytics / layout
│   │   ├── api/                # client · sse · generated.ts（禁止手改）· adapters/
│   │   └── stores/ types/ composables/
│   └── e2e/                    # Playwright
├── docs/                       # PRD、前后端计划、API 导出、部署手册
├── scripts/                    # 演示 Seed、OpenAPI 导出、fixture 导出
└── plans/                      # 实施与整改计划
```

## 文档索引

| 文档 | 内容 |
| --- | --- |
| [`AGENTS.md`](AGENTS.md) | 开发规则、目录索引与开发顺序（协作 agent 的入口） |
| [`docs/PRD.md`](docs/PRD.md) | 产品范围、用户故事、架构决策与验收标准 |
| [`docs/project-progress.md`](docs/project-progress.md) | 当前进度快照：阶段、验证结果、下一步与风险 |
| [`docs/backend-development-plan.md`](docs/backend-development-plan.md) | 后端阶段划分与 `ChatRequest` / `ChatResponse` / SSE 精确契约 |
| [`docs/frontend-development-plan.md`](docs/frontend-development-plan.md) | 前端阶段划分与 Definition of Done |
| [`docs/api.md`](docs/api.md) | OpenAPI 导出（接口字段的最终来源） |
| [`docs/deployment.md`](docs/deployment.md) | Railway 部署与运维手册 |

---

## 说明

- 演示商家、经营数据与知识文档均为虚构，仅用于功能演示；
- 本项目为个人工程实践，与任何真实电商平台无关。
