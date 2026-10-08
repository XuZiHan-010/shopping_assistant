# Borough 双端 Agent 电商平台开发指南

本文件是当前工作区的**稳定约束与入口索引**：项目目标、不可违反的规则、授权与完成边界、
按任务读什么、文档之间谁说了算。

它**不是**全量文件清单，也不定义接口字段。

| 你要找的 | 去哪里 |
| --- | --- |
| 哪个文件负责什么、目录结构、测试布局 | `docs/project-navigation.md` |
| 当前阶段、最近验证结果、未决风险 | `docs/project-progress.md` |
| 产品范围、用户故事、验收标准、API 路径清单 | `docs/PRD.md` |
| ChatRequest / ChatResponse / ErrorResponse / SSE 的精确字段 | `docs/backend-development-plan.md` §8 → `docs/api.md` |
| 历史参考项目差异记录 | `docs/yshopping-parity-audit.md`（非当前待办清单） |

当前工作区根目录：

```text
D:\vscode html\merchant_assistant
```

---

## 一、项目是什么

Borough 是一个双端 Agent 电商演示平台：顾客端负责店铺内导购、购物与售后，商家端负责经营分析、
库存与内容运营、受控审批和客服处理。两端共享同一套可信身份、租户隔离、订单/库存/售后事实与审计边界。

现有 12 节点 LangGraph 位于 `backend/app/agent/graph.py`，从 2026-09-20 起冻结为只读评测基线，
不再承接新 Skill、工具或写操作，也不部署为新生产主流程。目标流程由 `docs/PRD.md` A1–A11 定义：

```text
可信会话身份与角色工具面
  → 零 LLM 安全/权限闸门
  → 按需加载受信 Skill 与检索上下文
  → 有轮数、工具、LLM、时间和 token 上限的工具循环
  → 后端确定性查询、计算与写操作复检
  → 顾客界面确认或商家审批界面批准
  → 回答、引用、降级与质量信息
  → 异步记忆沉淀与可重复评测
```

主要能力：店铺级顾客 Agent、购物车与演示结账、订单履约与售后闭环；商家指标查询、趋势/分类/归因、
库存运营、商品内容、定价促销、客服回复与受控草稿审批；CSV 明细导出；指标业务口径与受控 SQL 口径；
平台规则问答；顾客与商家隔离记忆；每日简报；知识库后台；Chat BI 与评测；中英双语；独立 Reviewer。
附件、OCR、对象存储与通用异步 Worker 不在本版范围。

### 命名与品牌

**Borough** 是本项目虚构的电商平台 IP，也是产品、仓库和代码标识的统一名称。取自伦敦 Borough Market。

| 位置 | 取值 |
| --- | --- |
| 平台 IP / 产品名 | Borough 双端 Agent 电商平台 |
| 仓库 | `borough-merchant-ai` |
| Python 发行项目 | `borough-merchant-ai`（`pyproject.toml` 的 `name`） |
| Python 导入根包 | `app`（`app.agent` / `app.services` / `app.knowledge`） |
| 前端包 | `@borough/web` |
| PostgreSQL schema | 默认 `public`，不设专用 schema |
| 品牌资源 | `frontend/public/borough-logo.svg` |
| 默认演示商家 | `Borough商家100` |

约束：

- **旧 IP `yshopping` 只允许出现在指向参考项目和 prototype 的真实路径里**（`yshopping-merchant-ai 4/`、
  `yshopping-prototype/`），这些目录名不改；
- 新代码的品牌文案、prompt 话术、演示数据和发行项目名一律使用 Borough，不得残留 yshopping；
- **Borough 是品牌名，不是 Python 导入路径。** 实际导入根包是 `app`，源码位于 `backend/app/`。
  不存在 `borough.agent`、`borough.query`、`borough.wiki` 这类导入路径；
- 数据库不使用 `borough` schema。ORM 不写 `__table_args__ = {"schema": ...}`，连接串不设 `search_path`，
  Alembic 不配 `version_table_schema`；
- 环境变量沿用无前缀命名（`DATABASE_URL`、`LLM_MODEL` 等），**不要**引入 `BOROUGH_` 前缀；
- 参考项目里的业务表名（`ads_merchant_profile`、`dwm_trade_order_detail_di` 等）本身不含 IP，可原样沿用。

---

## 二、不可违反的规则

### R1 · 面向用户的内容使用中文

开发交流、提交说明、日志说明和项目文档默认使用中文。代码标识符保持英文，并遵循对应语言的命名规范。

**产品页面文案与 API 响应按受支持的显示语言渲染**，不是一律中文：当前支持 `zh-CN` 与 `en-US`，
由 `Accept-Language` / `useLocaleStore()` 决定。英文模式下返回英文内容是正确行为，不违反本条。
语言边界见 `backend/app/localization/locales.py` 与 `frontend/src/i18n/`。

### R2 · 未经用户明确许可，不执行 Git 发布操作

不得自行执行：

```text
git commit
git push
git tag
gh pr create
gh pr merge
```

也不得使用 `git reset --hard`、`git clean` 等可能丢失用户修改的命令。

授权是按次的：一次提交许可不延伸到下一次。未获授权时，把代码和验证做完直接汇报，
**不要反复索要提交许可，也不要因为没有提交授权就停下其他已授权的工作**。

### R3 · 真实或可能产生费用的 LLM 调用必须先说明成本

自动化测试必须 mock LLM。执行**真实或可能产生费用的调用**前，先说明：

- 将调用什么接口；
- 预计调用多少次模型；
- 使用什么模型；
- 是否会产生费用。

只有用户明确同意后才能执行。具体判定：

- **需要审批**：调用真实聊天接口、OCR、生成日报、记忆压缩、批量本地化，以及任何走真实
  `LLM_API_KEY` 的路径；真实模型评测、LLM 裁判、模型适配冒烟测试同样属于此类；启动后端前先核实
  启动钩子、定时任务、预热逻辑是否会触发真实调用。
- **无需审批**：已确认走 mock/fake LLM、不写生产数据、使用可丢弃测试数据的本地操作
  （`uv run pytest`、`npm run test`、lint、typecheck、mock e2e、OpenAPI 导出）。
- **无法确认时不擅自运行**，先说明不确定点。

授权范围沿用规则：同一接口、同一模型、同一次数或费用上限范围内的授权，在本次会话内继续有效，
不必逐次重问。**换模型、扩大调用范围或超过授权上限须重新取得同意**；时间流逝本身不构成授权，
泛化的「执行这个计划」也不构成费用授权。

真实调用属于另行授权的人工验收，**不加入默认测试套件**。

当前唯一约定的云端 LLM 提供商为 **DeepSeek**。Borough 自有 `LlmClient` 下允许实现两种协议适配器：

- OpenAI 兼容接口：根地址 `https://api.deepseek.com`；
- Anthropic 兼容接口：协议地址 `https://api.deepseek.com/anthropic`。

默认模型为 `deepseek-flash`；`deepseek-v4-pro` 仅作为经费用评估后可配置的升级选项。
不得在新配置中使用已弃用的 `deepseek-chat`、`deepseek-reasoner` 或已退役兼容别名
`deepseek-v4-flash`。`LLM_API_KEY` 必须是 DeepSeek API Key；`LLM_BASE_URL` 保存提供商根地址
`https://api.deepseek.com`，Anthropic Adapter 在内部使用 `/anthropic` 端点；`LLM_MODEL` 默认取
`deepseek-flash`。

### R4 · LLM 不得直接生成或执行任意 SQL

模型只允许输出经过 Pydantic 校验的结构化查询意图。SQL 必须由后端模板生成，并满足：

- 表名和列名来自白名单；
- 值参数全部绑定；
- 日期范围、最大行数和商家范围由后端强制限制；
- 查询前自动注入 `merchant_id`；
- 日志不得记录隐私字段和完整查询结果。

模型也不得决定指标公式、数据源选择、实时/汇总合并、金额、库存变化或图表数据点；这些都由后端
确定性代码产生。指标详情中的 SQL 口径只能来自受控指标资产，供人核对，不得作为待执行 SQL 回流。

### R5 · 商家数据必须隔离

任何经营数据、会话、记忆、反馈、本地化缓存、草稿、库存事件、售后单据和评测派生数据都必须按
`merchant_id` 隔离。顾客订单、购物车、售后与记忆还必须叠加服务端解析的 `buyer_key`；商家只能看到
店铺级脱敏别名。不得相信前端或模型直接传来的 `merchant_id` / `buyer_key`，必须从已验证会话中解析。

**可信身份与租户隔离必须早于任何经营数据查询或写入接口上线**。商家会话调用顾客端点、顾客会话
调用商家端点，以及任何跨商家/跨顾客访问均须 403 并写审计；目标不存在与目标不属于当前主体使用
相同公开错误结构，不得泄露对象存在性。

### R6 · 密钥不得进入代码

以下信息只能来自环境变量或 Railway Variables：

```text
DATABASE_URL                  [N1]
LLM_API_KEY                   [N1，可选] DeepSeek API Key；无真实调用授权时不配置也不使用
LLM_BASE_URL                  [N1] 固定为 https://api.deepseek.com
LLM_MODEL                     [N1] 默认 deepseek-flash
DEMO_MERCHANT_TOKENS          [N1] 演示 Token 到 merchant_id 的映射
DEMO_DEPLOYMENT_MODE          [N1] 对外演示部署时显式开放演示身份入口，默认 false
SESSION_TTL_SECONDS           [N1] 会话有效期，默认 86400 秒，范围 300–2592000
BUYER_ALIAS_SECRET            [N1] 稳定的高熵别名派生密钥；生产环境必填，禁止弱占位值
DEMO_CUSTOMER_IDENTITIES      [N1] 仅服务端的 shop_slug 到演示 buyer_key 映射，不得下发给前端
ALLOW_DEMO_DATA_REFRESH       [N1] 非密钥但高风险；仅独立 Cron 使用，默认 false，绝不暴露给前端
ADMIN_TOKEN                   [N1] 运维、知识后台与评测管理令牌；请求头 X-Admin-Token
VIEWER_TOKEN                  [N1，可选] `/api/admin/*` 明确标注的只读 GET，与 ADMIN_TOKEN 共用请求头
REDIS_URL                     [按证据引入] 仅在多实例共享限流或队列确有需求时配置
OBJECT_STORAGE_ACCESS_KEY     [未来附件版本]
OBJECT_STORAGE_SECRET_KEY     [未来附件版本]
JWT_SECRET                    [未来真实用户体系]
```

`.env.example` 只能放占位符，不得包含真实密钥。

**两个例外**，范围不得扩大：

- **演示 Token** 只授予对演示数据的访问权，可以由 `/api/demo/merchants` 下发给演示前端；
- **`VIEWER_TOKEN`** 与 `ADMIN_TOKEN` 认同一批 `/api/admin/*` 端点，但后端只放行其中的 GET
  （见 `require_admin_or_viewer_token`）；写操作、`memories/compress`（真实 LLM 调用）、
  `ops/status` 一律拒绝。因为泄露的最坏后果只是"看到本来就想公开的只读内容"，
  它允许打包进 `VITE_VIEWER_TOKEN` 构建产物。

`ADMIN_TOKEN` 本身仍绝不进代码或构建产物。两者配置时不可取值相同，否则"只读"这条边界名存实亡
（`Settings` 启动时拒绝）。

### R7 · 降级必须对用户可见

数据库、知识库、LLM、OCR 或对象存储不可用时可以降级，但必须在 API 字段和页面中明确显示：

```text
analysis_sources
thinking_steps
quality_status
quality_notes
degraded
degraded_reason
```

这些字段名必须与 `docs/backend-development-plan.md` §8.2 的 ChatResponse 完全一致，
本条不引入契约之外的字段。

**不得把模拟数据或规则兜底包装成真实模型分析。**

### R8 · 所有参考项目与 vendor 快照只读，永不修改

以下目录整体只读：

```text
yshopping-merchant-ai 4/
yshopping-prototype/
vendor/
```

它们只作为历史行为、视觉或上游设计参考，不是可直接开发的源码目录。其中的代码和文件
**一律不修改**，具体包括不得：

- 编辑、重写或重构其中任何源码、配置、SQL、Markdown 或知识库文件；
- 重命名、移动或删除其中任何文件与目录，包括外层目录名 `yshopping-merchant-ai 4/` 本身；
- 在其中新建文件、写入日志或生成构建产物；
- 为了统一命名而改写旧 IP 或上游品牌——快照保留原样是正确状态；
- 对其执行格式化、lint 自动修复、依赖升级或测试重跑等会改动文件的操作。

读取方式：用只读命令查看。需要复用时优先通过 Borough 自有 Adapter / 组合层接入；确需复制代码或资源时，
复制到新项目路径并保留来源说明后再改。升级 vendor 时只能整体替换到经审查的固定提交，不在快照上打补丁。

新应用源码写在 `backend/`、`frontend/` 与 N2 创建的 `shop/` 中；脚本写入 `scripts/`，文档写入 `docs/`，
设计说明与规格写入 `docs/specs/`，实施计划与整改计划写入 `plans/`。所有新文件都与上述只读目录零交集。

### R9 · 产品范围由现行 PRD 决定，参考项目不反向定义需求

本项目不再以任何参考项目的 1:1 还原为目标。`docs/PRD.md` 定义现行产品范围、状态机、路径和验收标准；
更晚的用户明确裁定可修改 PRD，但必须在同一次变更中同步受影响的契约、计划与索引。

- 参考项目可以用于理解一种已有做法、比较行为或借鉴视觉，但“参考项目里存在”不自动构成 Borough 需求；
- 参考项目与 PRD 冲突时按 PRD 实现，不得为了贴合参考结构而绕过 R4–R7 或扭曲 Borough 领域模型；
- `docs/yshopping-parity-audit.md` 是历史差异记录，不是开工门禁或必须清零的待办清单；
- 只有 PRD 明确纳入的历史能力才继续实现；取消或延后的能力按 PRD §13–§14 处理；
- 已验证且仍在 PRD 范围内的 Borough 领域逻辑、安全边界、测试资产和生产契约继续保留。

---

## 三、授权与完成边界

在用户已授权的任务范围内，持续完成实现、相关验证和本次修改导致的问题修复。已确认不访问生产、
不调用真实付费模型、使用可丢弃测试数据的本地操作，无需逐步询问是否继续。沿用当前会话已经明确的
授权及其范围。

只有在缺少影响产品行为的必要决策、需要扩大实质范围，或将触及真实费用、生产变更、重要数据、
Git 发布权限时，才请求用户决定。**某项操作受阻时，继续完成不依赖它的工作**，把受阻项如实列出。

用户明确要求「只分析」「先列建议」「等审阅后修改」时，严格停在该边界，不写实现文件。

实施完成须有与变更范围匹配的验证证据，说明**已完成、未完成及验证限制**；
不得仅交付第一版就把修复和验证留给下一轮，也不得把局部通过称为全量通过。

本节不授予任何 R2/R3 未授予的权限：它降低的是重复确认的成本，不是安全边界。

---

## 四、按任务读什么

| 任务 | 先看 |
| --- | --- |
| 接手工作、判断当前做到哪 | `docs/project-progress.md` |
| 找某个文件在哪、某个模块归谁 | `docs/project-navigation.md` |
| 比较历史行为或视觉（只在 PRD 已纳入时） | `docs/PRD.md` → `docs/yshopping-parity-audit.md` → 只读参考目录 |
| 改聊天协议或任何 API 字段 | `docs/backend-development-plan.md` §8 → `backend/app/schemas/` → `docs/api.md` → `frontend/src/api/generated.ts` 与 Adapter |
| 改产品范围、阶段或验收标准 | `docs/PRD.md`（先改这里，再改契约与前后端计划） |
| 改 Agent 流程 | 先读 `docs/PRD.md` A1–A11；`backend/app/agent/graph.py` 只作冻结基线，新循环写入 Borough 自有模块 |
| 增加指标 | `backend/app/metrics/`、`backend/app/services/safe_query.py`、`docs/metrics.md` |
| 增加业务分类 | 意图 Schema（`backend/app/intent/`）→ Agent 路由 → 查询服务 → 知识库 → 前端展示 |
| 改 SQL | `backend/app/services/safe_query.py`、`backend/app/repositories/` |
| 改图表 | `backend/app/services/visualization_service.py`、`MetricChartPanel.vue`、`frontend/src/utils/chart.ts` |
| 改经营建议 | `answer_service.py`、回答 Prompt、`RecommendationPanel.vue` |
| 改 Reviewer | `review_service.py`、`quality_loop.py`、Reviewer Prompt 和质量测试 |
| 改知识库 | `backend/app/knowledge/`、`knowledge_admin_service.py`、知识 API、`KnowledgeBaseView.vue` |
| 改数据库表 | ORM Model → Alembic Migration → Repository → `docs/database.md` |
| 改显示语言、翻译或格式化 | `backend/app/localization/`、`frontend/src/i18n/`、`utils/localizedFormat.ts` |
| 改部署 | Dockerfile、Railway 配置、`docs/deployment.md` |
| 重启附件能力（未来版本） | 先修改 `docs/PRD.md` §13–§14 并重新核实当时模型、对象存储与 OCR 方案；本版不得先行实现 |

---

## 五、文档权威关系

同一件事只在一个地方定义，其余文档引用它。出现冲突时按下表判定，**不要就地改成自己需要的样子**：

```text
AGENTS.md（本文件）
  └── 安全与架构硬约束（R1–R9）、授权与完成边界
        ↑ 这些不被下面任何一层推翻

docs/PRD.md
  ├── 产品范围、阶段划分、用户故事、验收标准
  └── API 的产品级语义与路径清单（§11）

只读参考项目与 vendor/
  └── 非规范性参考；不能推翻 PRD 或自动产生需求（R8、R9）

docs/backend-development-plan.md §8
  └── ChatRequest / ChatResponse / ErrorResponse / SSE 的精确字段与错误契约
        ↓ 实现后由 FastAPI 生成
      docs/api.md（OpenAPI 导出）+ backend/app/schemas/（实现结果）

docs/backend-development-plan.md（其余）/ docs/frontend-development-plan.md
  └── 依据 PRD 与上述契约定义实现步骤

docs/project-navigation.md / docs/project-progress.md
  └── 索引与当前状态；不定义需求，也不改变上述判定顺序
```

`docs/api.md` 与 `backend/app/schemas/` 是**实现结果的表达**，不是需求来源。实现与约定不一致时应整改实现，
不能反过来用生成文档倒推取消需求。

范围发生变化时的顺序是：先改 PRD → 再改契约 → 再改前后端计划 → 最后同步索引文件。

---

## 六、当前状态与目录约定

**当前阶段、已完成内容、最近验证结果、下一步和风险统一记录在 `docs/project-progress.md`。**
本文件不复写阶段清单，避免两处各自漂移。

摘要（细节以进度快照为准）：旧商家单端 MVP、日报、知识库后台、商家记忆、Chat BI 与双语链路已落地，
并冻结为迁移基线；新路线处于 N1（契约、身份、数据与评测基线）。顾客端、会话模式身份、工具循环、
受控写操作与新评测体系尚未实现。附件、对象存储、通用 Worker 和真实用户体系不在本版范围。

目录约定：

- `plans/` 存放实施与整改计划，**当前非空**；`docs/specs/` 存放设计说明与规格；
  OpenSpec change 走 `openspec/changes/` 与主 specs；`docs/superpowers/` 是历史遗留产出，保留不迁移。
  同一个需求只建一份主计划，详见 `docs/project-navigation.md` §八。
- `.agents/skills/` 是项目 OpenSpec 工作流 Skill 的**语义维护来源**，`.claude/skills/` 同步语义，
  见 `.agents/skills/README.md`。

进度维护要求（合并为一处）：**完成影响后续开发的阶段后，更新 `docs/project-progress.md` 的日期、
当前阶段、验证结果、下一步和风险**；该文件只保留当前快照，不追加每日流水账。
纯咨询、只读审查和不改变代码状态的问答不产生文档写入义务。

---

## 七、技术栈与基础设施

**前端**：商家端保留 Vue 3 + TypeScript + Vite + Vue Router + Pinia + vue-i18n + ECharts；
顾客端新增 Next.js + TypeScript。两端共享 OpenAPI 类型、领域 Schema、设计 token 与图标，不共享框架组件；
测试使用 Vitest / 对应 React 测试工具与 Playwright。

**后端**：Python 3.12、FastAPI、Uvicorn、Pydantic v2、SQLAlchemy 2、Alembic、psycopg、LangGraph、
Polars 或 Pandas、PyMuPDF、openpyxl、pytest、Ruff、mypy。

**数据与基础设施**：

- **PostgreSQL**：主数据库，必需。保存双端会话与消息、回答/Reviewer 结果/反馈、导出记录、
  安全审计与 LLM 用量、指标定义、业务知识、双端记忆、本地化缓存、草稿与变更账本、
  订单/库存/履约/退款/退货/工单和评测结果。表清单见 `docs/project-navigation.md` §六，
  权威定义见 `docs/backend-development-plan.md` §7.1。
- **Redis**：缓存、限流、异步任务队列、多实例共享短期状态。没有这些需求时不要提前引入。
- **对象存储**：本版不引入；未来重启附件或异步导出时再选择 S3 / R2 / 兼容服务。
- **Apache Doris**：只有在经营数据达到千万级以上、PostgreSQL 聚合明显成为瓶颈、需要跨多张宽表
  高并发分析，或已存在 ETL / 实时同步 / 企业数仓时才引入。Doris 只负责分析数据，
  用户、会话、反馈、知识库仍放 PostgreSQL。
- **MySQL**：新项目默认不需要。只有企业现有业务数据源必须使用 MySQL 时，才把它作为上游数据源接入。
  **不要同时引入 PostgreSQL 和 MySQL 作为主库。**
- **Docker**：本地一致性和 Railway 部署。

---

## 八、接口协议

**接口路径必须保持下表取值**，除非先同步修改 `docs/PRD.md` §11、前后端开发计划和所有契约测试。
本表是索引，`docs/PRD.md` §11 是权威来源。

### 8.1 已实现 v1 兼容接口

```text
POST   /api/chat
GET    /api/conversations
GET    /api/conversations/{conversation_id}
DELETE /api/conversations/{conversation_id}
POST   /api/answers/{answer_id}/feedback
GET    /api/exports/{export_id}
GET    /api/metrics/{code}
GET    /api/demo/merchants
GET    /api/health
GET    /api/ready
GET    /api/admin/ops/status
GET    /api/reports/daily
POST   /api/admin/reports/daily/recompute
GET    /api/admin/analytics/chatbi/overview
GET    /api/admin/analytics/chatbi/categories
POST   /api/admin/analytics/chatbi/rollup
GET    /api/admin/knowledge/tree
GET    /api/admin/knowledge/documents/{document_path}
POST   /api/admin/knowledge/documents
PUT    /api/admin/knowledge/documents/{document_path}
DELETE /api/admin/knowledge/documents/{document_path}
POST   /api/admin/knowledge/business-domains
PUT    /api/admin/knowledge/business-domains
DELETE /api/admin/knowledge/business-domains
POST   /api/admin/knowledge/memories/compress
```

- `/api/metrics/{code}` 接受指标机器码，不接受中文指标名；
- `/api/demo/merchants` 仅在 `DEMO_DEPLOYMENT_MODE=true` 时开放；
- `/api/health` 不查库、不调 LLM；`/api/ready` 可查数据库 readiness，但不调 LLM；
- `/api/admin/ops/status` 禁止返回 Token、Prompt、经营数据或完整请求正文；
- 知识目录由 `GET /api/admin/knowledge/tree` 提供，**没有** `GET /api/admin/knowledge/documents`
  列表接口，文档按 `{document_path}` 单独读取；
- 业务域改名需 `If-Match`，删除需 `If-Match` 且以 `recursive=true` 显式确认非空删除；
- 附件三个规划端点从未实现，已按 PRD D6 移出本版，不得继续加入当前 OpenAPI。

### 8.2 v2 目标接口

新能力只使用 `/api/v2/shop/*` 与 `/api/v2/merchant/*`。完整且不可缩写的方法/路径清单见
`docs/PRD.md` §11.2.2–§11.2.3；它覆盖顾客/商家会话、双端 Chat 与会话目录、店铺商品、购物车、
订单与履约、售后、双端记忆、当日简报、库存告警、顾客信号、草稿审批、反馈和 MCP。

v2 路由实施硬门槛：先在 `docs/backend-development-plan.md` §8 写完请求、响应、错误、幂等与 SSE
字段契约，再生成 OpenAPI、类型和 Adapter；不得从本索引或前端调用反推字段。

### 8.3 鉴权：按端点类别选凭证

每个端点属于且只属于下面一类，按类别装配请求头；前端不做「有什么加什么」：

| 类别 | 请求头 | 端点 | 阶段 |
| --- | --- | --- | --- |
| 公开 | 无 | 健康/就绪、演示身份入口、v2 店铺/商品公开浏览与创建访客会话 | 全程 |
| v1 商家 | `Authorization: Bearer <演示 Token>` | 现有非管理 `/api/*` 商家端点 | 迁移兼容 |
| 商家登录 Token | `Authorization: Bearer <演示 Token>` | 仅 `POST /api/v2/merchant/sessions` | N1 起 |
| 顾客会话 | `X-Session-Id: <session id>` | `/api/v2/shop/*` 中非公开端点 | N1 起 |
| 商家会话 | `X-Session-Id: <session id>` | `/api/v2/merchant/*`，MCP 除外 | N1 起 |
| MCP | 独立、短期、可撤销且限定商家/scope 的凭证 | `POST /api/v2/merchant/mcp` | N5 |
| 管理员 | **`X-Admin-Token: <ADMIN_TOKEN>`** | `/api/admin/*` 全部（读 + 写） | 全程 |
| 只读（可选） | **`X-Admin-Token: <VIEWER_TOKEN>`** | 明确标注 `require_admin_or_viewer_token` 的 GET；其余一律 403 | 全程 |
| 签名导出 | 无头，签名在 query 中 | 仅 `GET /api/exports/{export_id}` | 全程 |

**管理员令牌不复用 `Authorization`。** 两者语义、生命周期和泄露后果都不同；共用一个头会让后端无法区分
「商家在调管理接口」和「管理员在调商家接口」。后端对 `/api/admin/*` 只认 `X-Admin-Token`。

顾客与商家虽共用 `X-Session-Id` 传输方式，但会话记录包含不可变角色；两类会话不能互换，跨角色端点
访问一律 403 + 审计。`merchant_id` / `buyer_key` 只从服务端会话解析。

`/api/exports/{export_id}` 是唯一不要求请求头的鉴权接口：签名 URL 让浏览器可以原生下载，
理由见 `docs/backend-development-plan.md` §8.0。

### 8.4 Chat 传输协议

v1 `POST /api/chat` 默认返回 **SSE 流**，让用户在 1 秒内看到真实处理阶段：

```text
Content-Type: text/event-stream
事件类型：step | done | error
```

- 客户端发送 `Accept: application/json` 时返回普通 JSON；
- `done` 事件的载荷与非流式 `ChatResponse` **完全一致**，前端不得为两条路径维护两套解析；
- 完整事件字段与错误语义见 `docs/backend-development-plan.md` §8.4。

v2 `POST /api/v2/shop/chat` 与 `POST /api/v2/merchant/chat` 使用版本化事件契约；迁移期不直接废弃
`step` / `done` / `error`，新契约的 `turn_complete` 携带唯一最终响应，`tool_call` / `tool_result`
只能包含脱敏展示信息。精确事件字段先写入 `docs/backend-development-plan.md` §8。

只实现普通 JSON 请求无法满足 PRD 的首字延迟要求，SSE 不是可选项。

### 8.5 ChatResponse 契约位置

**本文件不维护字段清单。** v1 Chat 唯一权威定义是 `docs/backend-development-plan.md` §8.1 / §8.2 / §8.3，
实现后由 `docs/api.md`（OpenAPI 导出）确认。

结构要点（细节以上述契约为准）：

- 单一**扁平** snake_case 结构，不使用 `reviewer.*`、`metric.*` 这类嵌套对象；
- 会话标识统一为 `session_id`，不存在 `conversation_id`；
- 指标字段是 `metric_code` 等扁平键，不是 `metric_name`；导出字段是 `export`，不是 `export_url`；
- 分析来源是**有序数组** `analysis_sources`（主要来源在前），不是单值 `analysis_source`；
  `CHAT` 和 `INVALID` 返回 `["NONE"]`，不要为了凑"至少一项"而编造来源；
- Reviewer 备注 `quality_notes` 是**字符串数组**，无备注时为 `[]` 而非 `null`；
- 质量状态是 `quality_status`（`PASSED` / `DEGRADED` / `FAILED` / `NOT_RUN`）配 `quality_attempts`，
  **没有 `RETRIED`**——重试次数由 attempts 表达；
- 不存在 `semantic_notes`，语义说明统一走 `quality_notes` 和 `degraded_reason`；
- 字段分两组：**始终必填**（键必须存在，值可为 `null`）与**按模式必填**。Pydantic 模型不得把按模式
  必填字段设为无条件必填，否则 `CHAT`、`INVALID` 模式的正常响应会校验失败。

接口字段发生变化时，必须同步：

1. `docs/backend-development-plan.md` §8；
2. Pydantic Schema；
3. OpenAPI 与 `docs/api.md`；
4. TypeScript 生成类型与 Adapter；
5. 前端领域模型、Store 与渲染（仅当领域语义变化时）；
6. 后端和端到端测试。

字段流向是单向的，组件不得直接消费 `generated.ts`：

```text
OpenAPI → api/generated.ts → api/adapters/*.ts → types/*.ts → Store → 组件
```

**仅传输字段变化且领域语义不变时**，改动可限定在生成类型与 Adapter，Adapter 的契约测试会立刻暴露
不兼容；**领域语义变化时**，同步受影响的类型、Store、组件与测试。`generated.ts` 任何情况下禁止手改。

---

## 九、回答模式

| 模式 | 用途 |
| --- | --- |
| `METRIC` | 指标、趋势和聚合分析 |
| `DETAIL` | 业务明细和 CSV 导出 |
| `RULE` | 平台规则和业务知识 |
| `IDENTITY` | 商家资料和身份信息 |
| `CHAT` | 问候和普通对话 |
| `INVALID` | 无法处理或不安全的问题 |

这是 v1 兼容 Chat 的模式表；`ATTACHMENT` 已移出本版。v2 双端契约是否继续暴露 `mode` 由 N1
字段契约决定，不得直接照搬。新增模式时至少检查：意图 Schema、Agent 路由、查询服务、回答服务、
前端展示与测试用例。

---

## 十、本地开发命令

### 前端

```powershell
cd frontend
npm ci
npm run dev
npm run test
npm run build
```

### 后端

```powershell
cd backend
uv sync
uv run fastapi dev app/main.py
uv run pytest
uv run ruff check .
uv run alembic upgrade head
```

### Docker

```powershell
docker compose up --build
```

上述命令默认走 mock / fake LLM，不需要费用审批。**启动会触发真实 LLM 调用的路径前仍需遵守 R3**。

---

## 十一、Railway 部署约定

目标 Railway Project 包含：

| Service | Root Directory | 说明 |
| --- | --- | --- |
| `shop` | `/shop` | 顾客端 Next.js；N2 创建 |
| `merchant` | `/frontend` | 现有 Vue 商家工作台；由当前 `frontend` Service 迁移命名 |
| `backend` | `/backend` | FastAPI API |
| `postgres` | 外部 Neon PostgreSQL（不在 Railway 内） | 主数据库，经 `DATABASE_URL` 连接；N4 起启用 pgvector（`vector` 0.8.6，迁移 `20261002_0047` 执行 `CREATE EXTENSION`） |
| `cron` | `/backend` | 幂等短任务：简报、汇总回补、演示数据刷新与过期清理 |

本版不创建通用 `worker`、对象存储或默认 Redis Service；确有多实例共享限流/队列证据时另行评审 Redis。

**网络拓扑已定：Backend 公开 + 严格 CORS。** `shop` 与 `merchant` 通过各自构建变量指向 Backend，
不引入反向代理容器。因此：

- CORS 只允许 `shop` 与 `merchant` 两个精确 Origin，不使用 `*`；
- 允许头至少包含 `Authorization`、`Accept`、`Content-Type`、`X-Request-Id`、`X-Session-Id`、
  `X-Admin-Token`；
- Backend 既然公开，**基础限流、单请求 LLM 上限和每日预算熔断是上线前置条件**：
  未配置这三项防护时，不得把真实 LLM Key 部署到公开可访问的地址（与 R3 配套）。

**商家端镜像继续用 Caddy 托管静态产物**（Node 多阶段构建 → `caddy:2-alpine`）。约束：

- **Caddy 不代理 `/api`**——这是「不引入反向代理容器」的直接结果。因此 `frontend/src/api/client.ts`
  也刻意不提供同源 `/api` 回退：漏配 `VITE_API_BASE_URL` 必须响亮失败，而不是静默拿 404；
- **镜像构建期不跑 `npm run codegen`**。Railway 的 frontend Root Directory 是 `/frontend`，
  构建上下文里没有仓库根的 `docs/`，读不到 `docs/api.json`。`frontend/src/api/generated.ts` 是
  **提交进仓库**的生成产物，由 `npm run codegen:check` 在本地和 CI 保证它没过期；
- `VITE_API_BASE_URL` 在构建期注入静态产物，必须由 Railway Variables 提供。

其他部署要求：

- `shop`、`merchant` 和 Backend 使用独立 Dockerfile；Backend 监听 Railway 提供的 `PORT`；
- 只信任 Railway 代理注入的转发头，不直接采信客户端的 `X-Forwarded-For`；
- `/api/health` 不调用 LLM；数据库连接必须有启动重试；
- 两个前端通过 Railway Variables 引用 Backend 地址；会话 ID 不写 URL；
- 数据库迁移在发布阶段单独执行，不能由 Backend 或 Cron 实例并发执行；
- Doris 如需启用，优先部署在 Railway 外部的托管服务或独立集群。

详细步骤见 `docs/deployment.md`。

---

## 十二、维护本文件

本文件只在**稳定约束**变化时更新：

- 新增或修改不可违反的规则；
- 改变授权与完成边界；
- 改变接口路径清单或鉴权类别；
- 改变部署架构或新增外部服务；
- 改变文档权威关系。

**不要**在这里更新阶段进度、文件清单或目录树——它们分别属于 `docs/project-progress.md` 和
`docs/project-navigation.md`。本文件是索引和约束，不复制各模块的实现细节。
