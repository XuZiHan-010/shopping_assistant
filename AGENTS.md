# Borough 商家 AI 助手开发指南

本文件是当前工作区的总目录索引，也是 coding agent 开始工作前必须完整阅读的开发指南。

它有三个目的：

1. 说明项目当前已经有什么；
2. 定义 Python + TypeScript 重构版应该把代码放在哪里；
3. 告诉 coding agent 每个关键文件负责什么、修改某项功能时应该从哪里开始。

---

## 一、状态标记

本文件中的路径使用以下标记：

- **[现有]**：文件或目录现在已经存在，可以直接读取或运行。
- **[参考]**：旧版 Java + Vue 项目，只作为行为、业务逻辑和视觉还原依据，不在其中继续开发新架构。
- **[规划]**：Python + TypeScript 重构版的目标路径。创建前不要假设它已经存在；首次创建后应同步更新本文件。

当前工作区根目录：

```text
D:\vscode html\merchant_assistant
```

---

## 二、不可违反的规则

### R1 · 面向用户的内容使用中文

回复、页面文案、错误提示、日志说明和项目文档默认使用中文。代码标识符保持英文，并遵循对应语言的命名规范。

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

### R3 · 真实 LLM 调用必须先说明成本

单元测试必须 mock LLM。启动后端、调用聊天接口、执行 OCR、生成日报或运行会产生 token 费用的测试前，先说明：

- 将调用什么接口；
- 预计调用多少次模型；
- 使用什么模型；
- 是否会产生费用。

只有用户明确同意后才能执行。

### R4 · LLM 不得直接生成或执行任意 SQL

模型只允许输出经过 Pydantic 校验的结构化查询意图。SQL 必须由后端模板生成，并满足：

- 表名和列名来自白名单；
- 值参数全部绑定；
- 日期范围、最大行数和商家范围由后端强制限制；
- 查询前自动注入 `merchant_id`；
- 日志不得记录隐私字段和完整查询结果。

### R5 · 商家数据必须隔离

任何经营数据、会话、附件、记忆和反馈都必须按 `merchant_id` 隔离。不得相信前端直接传来的商家编号，必须从已验证身份中获取或校验。

### R6 · 密钥不得进入代码

以下信息只能来自环境变量或 Railway Variables：

```text
DATABASE_URL                  [P0]
LLM_API_KEY                   [P0] DeepSeek API Key
LLM_BASE_URL                  [P0] 固定为 https://api.deepseek.com
DEMO_MERCHANT_TOKENS          [P0] 演示 Token 到 merchant_id 的映射
DEMO_DEPLOYMENT_MODE          [P0] 对外演示部署时显式开放生产环境的演示商家端点，默认 false
ALLOW_DEMO_DATA_REFRESH       [P0] 非密钥但高风险的演示数据写权限；仅独立 Cron 使用，默认 false，绝不暴露给前端
ADMIN_TOKEN                   [P0] 运维端点；[P1] 兼作知识库后台管理员令牌；请求头 X-Admin-Token
REDIS_URL                     [P1]
OBJECT_STORAGE_ACCESS_KEY     [P1]
OBJECT_STORAGE_SECRET_KEY     [P1]
JWT_SECRET                    [P2] 引入真实用户体系后才需要
```

`.env.example` 只能放占位符，不得包含真实密钥。

当前唯一约定的云端 LLM 提供商为 **DeepSeek**，通过其 OpenAI 兼容的
Chat Completions API 接入。MVP 默认模型为 `deepseek-v4-flash`；
`deepseek-v4-pro` 仅作为经费用评估后可配置的升级选项。不得使用已弃用的
`deepseek-chat` 或 `deepseek-reasoner`。`LLM_API_KEY` 仍沿用既有变量名，
其值必须是 DeepSeek API Key；`LLM_BASE_URL` 固定为
`https://api.deepseek.com`，`LLM_MODEL` 默认取 `deepseek-v4-flash`。

演示 Token 是例外：它只授予对演示数据的访问权，可以由 `/api/demo/merchants` 下发给演示前端，不属于本条所指的真实密钥。真实密钥仍只保存在 Railway Variables 中。

### R7 · 降级必须对用户可见

数据库、知识库、LLM、OCR 或对象存储不可用时可以降级，但必须在 API 字段和页面中明确显示，例如：

```text
analysis_sources
thinking_steps
quality_status
quality_notes
degraded
degraded_reason
```

这些字段名必须与 `docs/backend-development-plan.md` §8.2 的 ChatResponse 完全一致，本条不引入契约之外的字段。

不得把模拟数据或规则兜底包装成真实模型分析。

### R8 · 参考项目只读，永不修改

以下目录整体只读：

```text
yshopping-merchant-ai 4/
```

它是旧版 Java + Vue 实现，**只作为开发和架构参考存在**：核对业务行为、接口字段、指标口径、知识库结构、测试用例和视觉样式。

其中的代码和文件**一律不修改**，具体包括不得：

- 编辑、重写或重构其中任何源码、配置、SQL、Markdown 或知识库文件；
- 重命名、移动或删除其中任何文件与目录，包括外层目录名 `yshopping-merchant-ai 4/` 本身；
- 在其中新建文件、写入日志或生成构建产物；
- 为了统一命名而把其中的 `yshopping` 改成 `Borough`——参考项目保留旧 IP 是正确状态，见「命名与品牌」；
- 对其执行格式化、lint 自动修复、依赖升级或测试重跑等会改动文件的操作。

读取方式：用 Read、Grep、Glob 查看。需要复用其中的代码或资源时，**复制到新项目路径后再改**，不要就地修改。

新应用源码主要写在 `backend/`、`frontend/` 和按阶段启用的 `worker/` 中；脚本写入 `scripts/`，部署配置写入 `railway/`，文档写入 `docs/`，设计说明与规格写入 `docs/specs/`，实施计划与整改计划写入 `plans/`。所有新文件都与参考项目目录零交集。

### R9 · 参考项目是需求基准，冲突时改我们的文档

本项目的目标是把 `yshopping-merchant-ai 4/` **1:1 还原**为 Python + TypeScript 版本。

因此当 `docs/PRD.md` 或任何开发计划与参考项目的实际实现冲突时：

- **以参考项目为准**，修改我们的 PRD 与计划去跟随它；
- **不得反过来**用「PRD 没写」「契约里没有」论证参考项目里存在的字段或行为可以不做。

判定顺序也随之固定：发现某个字段、面板分区或降级分支在参考项目里存在、在我们这边缺失时——

1. 先读参考项目对应的 Java service 与 Vue 组件，确认它真实的设计，不要靠 PRD 反推；
2. 默认结论是「我们缺了，要补」，而不是「不在范围内」；
3. 同一次改动里把 PRD 与开发计划中与之冲突的条款一并改掉，让文档反映参考项目的设计；
4. 只有用户明确裁定「这一处不还原」时，才在文档里写明偏离及理由。

R8 依然完全有效：参考项目只读，本规则只改变**我们自己**文档的权威顺序。

首次适用记录：2026-08-09 按本规则修订了指标口径契约，见 `docs/PRD.md` §6.3 与 §11.3。

全量还原度差异清单见 `docs/yshopping-parity-audit.md`，开工前先查该文件是否已登记相关差异。

### R10 · 技能产出的文档写进项目自己的目录，不建 `superpowers/`

即使本轮工作用了 superpowers、`grill me` 或其他任何技能，它们产出的计划、设计说明和审查记录都一律写进项目自己的目录：

- 实施计划、整改计划 → `plans/`
- 设计说明、规格 → `docs/specs/`

**不得**新建 `docs/superpowers/`、`superpowers/` 或任何以技能名命名的目录来存放这些文档。技能只是产出文档的工作方式，不是项目结构的一部分——从最终的目录树上不应该看得出用过哪个技能。

例外只有一个：`.superpowers/`（带前导点）是技能自己的临时工作区（SDD 账本等），已被 `.gitignore` 忽略，从不进入仓库，不受本规则约束。

2026-08-10 已按本规则把原 `docs/superpowers/plans/`（10 份）与 `docs/superpowers/specs/`（13 份）迁至上述位置，`docs/superpowers/` 已删除。

---

## 三、项目是什么

Borough 商家 AI 助手是面向电商商家的 Data Agent。

### 命名与品牌

**Borough** 是本项目虚构的电商平台 IP，也是产品、仓库和代码标识的统一名称。取自伦敦 Borough Market。

| 位置 | 取值 |
| --- | --- |
| 平台 IP / 产品名 | Borough 商家 AI 助手 |
| 仓库 | `borough-merchant-ai` |
| Python 发行项目 | `borough-merchant-ai`（`pyproject.toml` 的 `name`） |
| Python 导入根包 | `app`（`app.agent` / `app.services` / `app.knowledge`） |
| 前端包 | `@borough/web` |
| PostgreSQL schema | 默认 `public`，不设专用 schema |
| 品牌资源 | `frontend/public/borough-logo.svg` |
| 默认演示商家 | `Borough商家100` |

约束：

- **旧 IP `yshopping` 只允许出现在指向参考项目和 prototype 的真实路径里**（`yshopping-merchant-ai 4/`、`yshopping-prototype/`），这些目录名不改；
- 新代码的品牌文案、prompt 话术、演示数据和发行项目名一律使用 Borough，不得残留 yshopping；
- **Borough 是品牌名，不是 Python 导入路径。** 实际导入根包是 `app`，源码位于 `backend/app/`。不存在 `borough.agent`、`borough.query`、`borough.wiki` 这类导入路径，不要按它们建目录；
- 数据库不使用 `borough` schema。ORM 不写 `__table_args__ = {"schema": ...}`，连接串不设 `search_path`，Alembic 不配 `version_table_schema`；
- 环境变量沿用本项目已确定的无前缀命名（`DATABASE_URL`、`LLM_MODEL` 等），**不要**引入 `BOROUGH_` 前缀，避免与既有配置章节冲突；
- 参考项目里的业务表名（`ads_merchant_profile`、`dwm_trade_order_detail_di` 等）本身不含 IP，可原样沿用。

核心流程：

```text
商家自然语言提问
  → 身份与会话校验
  → 业务意图识别
  → 检索知识与指标口径
  → 生成结构化查询计划
  → 后端安全查询经营数据
  → 生成结论、图表和行动建议
  → 独立质量校验
  → 保存回答与反馈
  → 异步沉淀商家记忆
```

主要能力：

- GMV、订单量、退货量、退款金额、工单量等指标查询；
- 趋势、分类、同比或环比分析；
- 订单、退款、商品、优惠券、工单、赔付和供应链明细查询；
- CSV 明细导出；
- 指标业务口径和 SQL 口径说明；
- 商品上架、交易、退货、优惠券等规则问答；
- 图片、PDF、Excel 和 CSV 附件分析；
- 至少两条带数据依据的经营建议；
- 回答采纳、点赞和点踩；
- 每日经营报告；
- 商家级会话记忆；
- 知识库维护后台；
- 独立 Reviewer 回答质量检查。

---

## 四、当前已有内容

### 4.1 [参考] 原始 Java + Vue 项目

根目录：

```text
yshopping-merchant-ai 4/yshopping-merchant-ai/
```

> **只读。** 本目录只用于开发和架构参考，其中的代码与文件一律不修改，另见 R8。需要复用时复制到新项目再改。

重要入口：

| 路径 | 用途 |
| --- | --- |
| `yshopping-merchant-ai 4/yshopping-merchant-ai/AGENTS.md` | 旧项目开发规则与目录说明 |
| `yshopping-merchant-ai 4/yshopping-merchant-ai/docs/architecture.md` | 旧项目业务流程概览 |
| `yshopping-merchant-ai 4/yshopping-merchant-ai/docs/architecture-detail.md` | 旧项目详细架构 |
| `yshopping-merchant-ai 4/yshopping-merchant-ai/docs/deploy-railway.md` | 旧项目 Railway 部署方式 |
| `yshopping-merchant-ai 4/yshopping-merchant-ai/frontend/src/App.vue` | 原商家助手主界面 |
| `yshopping-merchant-ai 4/yshopping-merchant-ai/frontend/src/components/` | 原聊天、图表、建议、日报组件 |
| `yshopping-merchant-ai 4/yshopping-merchant-ai/frontend/src/assets/styles.css` | 原界面视觉样式 |
| `yshopping-merchant-ai 4/yshopping-merchant-ai/frontend/src/api/client.js` | 原前端 API 协议和 mock 数据 |
| `yshopping-merchant-ai 4/yshopping-merchant-ai/backend/src/main/java/com/yshopping/merchantai/graph/` | 原 Agent 主流程 |
| `yshopping-merchant-ai 4/yshopping-merchant-ai/backend/src/main/java/com/yshopping/merchantai/service/` | 原业务服务与查询逻辑 |
| `yshopping-merchant-ai 4/yshopping-merchant-ai/backend/src/test/` | 原业务行为测试，可用于重构对照 |
| `yshopping-merchant-ai 4/yshopping-merchant-ai/runtime/llm-wiki/` | 原业务知识库、指标说明和记忆 |

迁移功能时，应先读取旧实现和测试，再在新架构中重写，不做逐行翻译。

### 4.2 [现有] 无后端交互 Prototype

根目录：

```text
yshopping-prototype/
```

| 路径 | 用途 |
| --- | --- |
| `yshopping-prototype/index.html` | Prototype 页面结构和 SVG 图标 |
| `yshopping-prototype/styles.css` | 1:1 视觉样式和响应式布局 |
| `yshopping-prototype/app.js` | 预置问答、图表、附件和反馈交互 |
| `yshopping-prototype/yshopping-logo.svg` | Prototype 沿用的旧品牌标志；复刻时替换为 `borough-logo.svg`，不要直接拷贝 |

本地预览：

```powershell
cd yshopping-prototype
python -m http.server 4173
```

然后访问：

```text
http://127.0.0.1:4173
```

Prototype 只用于确认产品效果，不代表最终工程结构，也不连接数据库或 LLM。

### 4.3 [现有] 产品与开发计划

根目录：

```text
docs/
```

| 路径 | 用途 |
| --- | --- |
| `docs/PRD.md` | 产品目标、用户故事、范围、架构决策和总体验收标准 |
| `docs/frontend-development-plan.md` | Vue 3 + TypeScript 前端目录、阶段任务、测试与 Definition of Done |
| `docs/backend-development-plan.md` | FastAPI + PostgreSQL 后端目录、Deep Module、数据模型、Agent 流程、测试与部署任务 |

coding agent 开始实现前，应按顺序阅读 `AGENTS.md`、`docs/project-progress.md` 和 `docs/PRD.md`，再根据负责范围阅读对应开发计划。进度快照提供当前阶段、最近验证结果、下一步和已知风险；它是跨日工作的外部记忆入口，不替代本文件的规则或 PRD 的产品定义。

### 4.3.1 [现有] 项目进度快照

根目录：

```text
docs/project-progress.md
```

它只记录带日期的**当前快照**：当前阶段、已完成、最近验证、下一步、风险与关键入口；不追加每日流水账。每次完成一段可验证工作后，都要更新其日期和内容，使下一位 coding agent 能直接继续推进。

#### 文档权威关系

同一件事只在一个地方定义，其余文档引用它。出现冲突时按下表判定，**不要就地改成自己需要的样子**：

```text
docs/PRD.md
  ├── 产品范围、阶段划分、用户故事、验收标准
  └── API 的产品级语义与路径清单（§11）

docs/backend-development-plan.md §8
  └── ChatRequest / ChatResponse / ErrorResponse / SSE 的精确字段与错误契约
        ↓ 实现后由 FastAPI 生成
      docs/api.md（OpenAPI 导出，最终唯一来源）

docs/backend-development-plan.md（其余）
  └── 依据 PRD 与上述契约定义后端实现步骤

docs/frontend-development-plan.md
  └── 依据 PRD 与生成类型定义前端实现步骤

AGENTS.md（本文件）
  └── 规则、目录索引、入口导航和不可违反的约束；只做索引和摘要，不复制字段表
```

范围发生变化时的顺序是：先改 PRD → 再改契约 → 再改前后端计划 → 最后同步本文件索引。

### 4.4 [现有] 文档审查与整改计划（已结项，目录当前为空）

根目录：

```text
plans/
```

2026-07-30 的三份一致性审查（PRD + AGENTS、后端方案、前端方案）**已全部整改并结项，审查文件已移除**，结论已合入 `docs/PRD.md`、`docs/backend-development-plan.md`、`docs/frontend-development-plan.md` 和本文件。目录保留供后续整改计划使用，当前为空。

不要因为这里为空就认为那些约束不存在——它们已经是上述四份文档的正文，尤其是：扁平 snake_case 契约、`app` 包与 `public` schema、商家隔离前置、P0 费用防护、MVP 阶段边界（后端 B0–B7 / 前端 F0–F6）。

### 4.5 [现有] Python 后端 B0–B7 与 R9 整改入口

根目录：

```text
backend/
```

当前已完成 B0–B7 的工程、身份、经营查询、回答质量、反馈导出和费用防护基础设施：

- Python 3.12、FastAPI App Factory、Pydantic Settings、结构化日志和统一错误；
- `/api/health`、`/api/ready`、`/api/demo/merchants`；
- SQLAlchemy Async、Alembic 与默认 `public` schema；
- `merchants`、会话、反馈、指标、知识、`audit_logs`、`llm_usage` 的 P0 基础迁移；
- 演示 Token → `merchant_id` 的可信解析；
- Conversation Repository、商家隔离服务和跨商家审计基础；
- `ChatRequest`、`ChatResponse`、会话列表/详情、扁平 snake_case OpenAPI 契约；
- `POST /api/chat` 的 SSE 与 `Accept: application/json` 双路径、`client_request_id` 幂等重放；
- B2 Fake Agent、服务端预置推荐问题、用户/助手消息和回答持久化；
- `/api/conversations` 列表、详情和删除，复用可信商家范围与跨商家审计；
- `docs/api.md` 由 `scripts/export_openapi.py` 从 FastAPI 自动导出；
- 三个演示商家的可重复 Seed；
- B3 结构化意图、B4 受控经营查询、B5 回答/图表/Reviewer、B6 反馈/签名 CSV、B7 限流/预算/部署配置；
- pytest、Ruff、mypy、Dockerfile 和本地 PostgreSQL Compose 配置。

R9 还原度差异的持续清单见 `docs/yshopping-parity-audit.md`；其阶段 B 的契约设计和整改顺序见
`plans/2026-08-09-b7-f4-integration-and-r9-remediation.md`。P1 功能仍按后端计划的 B8–B9 实施。

---

## 五、目标技术栈

### 前端

- Vue 3
- TypeScript
- Vite
- Vue Router
- Pinia
- ECharts
- Lucide Vue Next
- Vitest
- Playwright

### 后端

- Python 3.12
- FastAPI
- Uvicorn
- Pydantic v2
- SQLAlchemy 2
- Alembic
- psycopg
- LangGraph
- Polars 或 Pandas
- PyMuPDF
- openpyxl
- pytest
- Ruff

### 数据与基础设施

- PostgreSQL：第一阶段必需的主数据库；
- Redis：缓存和异步任务，第二阶段可选；
- S3、Cloudflare R2 或兼容对象存储：正式附件存储；
- Apache Doris：大规模分析场景才启用，第一阶段不需要；
- Docker：本地一致性和 Railway 部署；
- Railway：Frontend、Backend、PostgreSQL 和可选 Worker 服务。

不要同时引入 PostgreSQL 和 MySQL，除非真实上游系统必须使用 MySQL。

---

## 六、Python + TypeScript 目标目录

下方 `backend/` 的 B0+B1 路径、根目录 `.env.example`、`.gitignore`、`docker-compose.yml` 和 `scripts/seed_demo_data.py` 已存在；`docs/` 中的 PRD 和前后端计划已经存在，`plans/` 目录存在但当前为空；其余路径仍为 **[规划]**：

```text
merchant_assistant/
├── AGENTS.md
├── README.md
├── .env.example
├── .gitignore
├── docker-compose.yml
├── frontend/
│   ├── Dockerfile
│   ├── railway.json
│   ├── package.json
│   ├── package-lock.json
│   ├── vite.config.ts
│   ├── tsconfig.json
│   ├── index.html
│   ├── public/
│   │   └── borough-logo.svg
│   └── src/
│       ├── main.ts
│       ├── App.vue
│       ├── router/
│       ├── stores/
│       ├── api/
│       ├── types/
│       ├── composables/
│       ├── components/
│       ├── views/
│       └── assets/
├── backend/
│   ├── Dockerfile
│   ├── railway.json
│   ├── pyproject.toml
│   ├── uv.lock
│   ├── alembic.ini
│   ├── app/
│   │   ├── main.py
│   │   ├── api/
│   │   ├── agent/
│   │   ├── core/
│   │   ├── db/
│   │   ├── models/
│   │   ├── schemas/
│   │   ├── repositories/
│   │   ├── services/
│   │   ├── prompts/
│   │   └── knowledge/
│   ├── migrations/
│   └── tests/
├── worker/
│   ├── Dockerfile
│   ├── pyproject.toml
│   └── app/
├── docs/
│   ├── PRD.md
│   ├── project-progress.md
│   ├── frontend-development-plan.md
│   ├── backend-development-plan.md
│   ├── architecture.md
│   ├── agent-flow.md
│   ├── database.md
│   ├── api.md
│   ├── metrics.md
│   └── deployment.md
├── plans/                       # 当前为空，供后续整改计划使用
├── scripts/
│   ├── seed_demo_data.py
│   └── import_legacy_wiki.py
```

---

## 七、前端文件索引

### 7.1 应用入口

| [规划] 路径 | 职责 |
| --- | --- |
| `frontend/src/main.ts` | 创建 Vue 应用，注册 Router、Pinia 和全局样式 |
| `frontend/src/App.vue` | 全局应用外壳，只放路由出口和全局通知 |
| `frontend/src/router/index.ts` | `/` [P0] 实页；`/knowledge-base` [P0 注册占位路由，P1 实现页面]；`/login` 属于 P2，MVP 与 P1 都不建该路由 |
| `frontend/src/assets/styles.css` | 全局变量、基础布局和原界面视觉样式 |

### 7.2 页面

| [规划] 路径 | 阶段 | 职责 |
| --- | --- | --- |
| `frontend/src/views/AssistantView.vue` | P0 | 商家助手三栏主页面 |
| `frontend/src/components/layout/MerchantSwitcher.vue` | P0 | 演示商家切换器，MVP 的唯一身份入口 |
| `frontend/src/views/KnowledgeBaseView.vue` | P1 | 知识库维护后台，用 `ADMIN_TOKEN` 进入 |
| `frontend/src/views/LoginView.vue` | **P2** | 真实用户体系上线后才创建。**MVP 和 P1 都不做登录页**，不要提前建这个文件 |

### 7.3 聊天组件

| [规划] 路径 | 职责 |
| --- | --- |
| `frontend/src/components/chat/ConversationColumn.vue` | 消息流和输入区整体布局 |
| `frontend/src/components/chat/ChatMessage.vue` | 用户及助手消息、质量轨迹、反馈按钮 |
| `frontend/src/components/chat/ChatComposer.vue` | 文本输入、附件上传、拖拽和发送 |
| `frontend/src/components/chat/ConversationNav.vue` | 对话轮次目录 |
| `frontend/src/components/chat/DailyReportCard.vue` | 每日经营报告 |

### 7.4 分析组件

| [规划] 路径 | 职责 |
| --- | --- |
| `frontend/src/components/insights/MetricDefinitionPanel.vue` | 指标业务口径和 SQL 口径 |
| `frontend/src/components/insights/MetricChartPanel.vue` | 折线图、柱状图和饼图 |
| `frontend/src/components/insights/RecommendationPanel.vue` | 经营建议和行动项 |
| `frontend/src/components/insights/DetailTable.vue` | 明细表、分页、截断说明和 CSV 下载 |
| `frontend/src/components/chat/ChatMessage.vue` | 消息正文、质量轨迹与回答反馈；质量轨迹不另建独立组件 |

### 7.5 状态、API 与类型

| [规划] 路径 | 职责 |
| --- | --- |
| `frontend/src/stores/chat.ts` | 会话、消息、当前轮次和加载状态 |
| `frontend/src/stores/auth.ts` | 当前演示商家、Token 与管理员权限；P0 不含登录态 |
| `frontend/src/stores/knowledge.ts` | 知识库目录和编辑状态 |
| `frontend/src/api/client.ts` | API 基础地址的唯一读取点 [P0/F0]；HTTP 客户端、鉴权和统一错误处理 [F3]。**不提供同源 `/api` 回退**——静态镜像不代理 `/api`，配置缺失必须报错而非静默 404 |
| `frontend/scripts/check-generated.mjs` | `generated.ts` 漂移检查：重新生成到临时文件并与提交版本比对。构建期不跑 codegen，全靠它兜住脱节 |
| `frontend/scripts/check-first-paint.mjs` | 生产构建的首屏静态依赖门禁：阻止 ECharts 被预加载或经入口静态 import 链带入首屏 |
| `frontend/scripts/check-no-secrets.mjs` | 递归扫描 `dist/` 的 JS、CSS、HTML、JSON 与 source map，阻止密钥形态字符串进入构建产物 |
| `frontend/src/api/sse.ts` | `fetch` + `ReadableStream` 的 SSE 解析器（不使用 `EventSource`） |
| `frontend/src/api/chat.ts` | 聊天、反馈、日报和导出接口 |
| `frontend/src/api/attachments.ts` | 附件上传和解析状态接口 |
| `frontend/src/api/knowledge.ts` | 知识库维护接口 |
| `frontend/src/api/generated.ts` | **由 OpenAPI 生成，禁止手改** |
| `frontend/src/api/adapters/` | 生成类型 → 前端领域模型的唯一转换点，每个 Adapter 配契约测试 |
| `frontend/src/types/chat.ts` | 消息、图表、建议和质量轨迹的前端领域模型 |
| `frontend/src/composables/useChat.ts` | 发送、取消、重试和自动滚动逻辑 |

字段流向是单向的，**组件不得直接消费 `generated.ts`，也不得自行做字段转换**：

```text
OpenAPI → api/generated.ts → api/adapters/*.ts → types/*.ts → Store → 组件
```

后端字段变化时，只有 `generated.ts` 和对应 Adapter 需要改动，Adapter 的契约测试会立刻暴露不兼容。

---

## 八、后端文件索引

### 8.1 应用入口与配置

| [规划] 路径 | 职责 |
| --- | --- |
| `backend/app/main.py` | 创建 FastAPI 应用、注册路由、中间件和生命周期 |
| `backend/app/core/config.py` | 使用 Pydantic Settings 读取环境变量 |
| `backend/app/core/seed_config.py` | 演示数据滚动 Cron 的最小配置，仅读取数据库与显式写权限 |
| `backend/app/core/security.py` | 演示 Token 解析与商家身份校验 [P0]；管理员令牌 [P1]；JWT 属于 P2，MVP 不实现 |
| `backend/app/core/logging.py` | 结构化日志与敏感字段脱敏 |
| `backend/app/core/errors.py` | 统一业务异常和 API 错误格式 |

### 8.2 API 路由

| [规划] 路径 | 职责 |
| --- | --- |
| `backend/app/api/router.py` | 汇总所有 `/api` 路由 |
| `backend/app/api/routes/chat.py` | `/api/chat`、会话与反馈接口 |
| `backend/app/api/routes/attachments.py` | 附件上传、状态和删除 |
| `backend/app/api/routes/reports.py` | 每日经营报告 |
| `backend/app/api/routes/exports.py` | CSV 导出 |
| `backend/app/api/routes/knowledge.py` | 知识库目录和文档 CRUD |
| `backend/app/api/routes/metrics.py` | 指标检索和口径查询 |
| `backend/app/api/routes/health.py` | Railway 健康检查 |

路由只负责认证、参数校验和调用 Service，不写业务查询。

### 8.3 Agent 编排

| [规划] 路径 | 职责 |
| --- | --- |
| `backend/app/agent/graph.py` | LangGraph 主流程和节点连接 |
| `backend/app/agent/state.py` | 一轮问答共享状态 |
| `backend/app/agent/intents.py` | 允许模型输出的结构化意图 |
| `backend/app/agent/nodes/identity.py` | 商家身份和会话节点 |
| `backend/app/agent/nodes/retrieve.py` | 指标、知识和记忆检索 |
| `backend/app/agent/nodes/understand.py` | 两阶段意图识别 |
| `backend/app/agent/nodes/query.py` | 调用安全查询服务 |
| `backend/app/agent/nodes/compose.py` | 生成回答、图表描述和建议 |
| `backend/app/agent/nodes/review.py` | 独立 Reviewer 质量校验 |
| `backend/app/agent/nodes/persist.py` | 保存回答和触发异步记忆 |

所有节点通过 `AgentState` 交换数据，不在节点之间传递无类型字典。

### 8.4 业务服务

| [规划] 路径 | 职责 |
| --- | --- |
| `backend/app/services/chat_service.py` | 一轮聊天的应用层入口 |
| `backend/app/services/intent_service.py` | 调用 LLM 并解析结构化意图 |
| `backend/app/services/query_service.py` | 白名单校验、查询路由和 SQL 模板 |
| `backend/app/services/metric_service.py` | 指标口径三级检索 |
| `backend/app/services/knowledge_service.py` | 团队知识和商家记忆检索 |
| `backend/app/services/answer_service.py` | 回答组织和不同模式分发 |
| `backend/app/services/review_service.py` | 独立质量审核和有限重试 |
| `backend/app/services/visualization_service.py` | 确定安全的图表字段和类型 |
| `backend/app/services/attachment_service.py` | 图片、PDF、Excel、CSV 解析 |
| `backend/app/services/export_service.py` | P0 动态生成受权限保护的 CSV（不引入 S3 SDK）；P1 再增加对象存储和签名对象 URL |
| `backend/app/services/report_service.py` | 每日经营报告 |
| `backend/app/services/memory_service.py` | 商家记忆提取、压缩和召回 |
| `backend/app/jobs/seed_demo_rolling.py` | 专用演示数据库的增量滚动 Seed；需显式写权限与商家集合精确匹配 |

### 8.5 数据库和 Repository

| [规划] 路径 | 职责 |
| --- | --- |
| `backend/app/db/session.py` | SQLAlchemy Engine 和 Session |
| `backend/app/db/base.py` | ORM Base 和模型导入 |
| `backend/app/repositories/conversation.py` | 会话和消息读写 |
| `backend/app/repositories/answer.py` | 回答、反馈和质量记录 |
| `backend/app/repositories/merchant.py` | 商家读写 [P0]。**不含用户**，用户 Repository 属于 P2 |
| `backend/app/repositories/knowledge.py` | 知识库与记忆文档 |
| `backend/app/repositories/analytics.py` | 经营数据查询统一出口 |
| `backend/migrations/` | Alembic 数据库版本迁移 |

Repository 只负责数据访问，不调用 LLM，也不拼接来自用户的列名。

### 8.6 模型和 API Schema

| [规划] 路径 | 职责 |
| --- | --- |
| `backend/app/models/merchant.py` | 商家 ORM [P0]。用户 ORM 属于 P2，届时单独建 `user.py`，不要合进本文件 |
| `backend/app/models/conversation.py` | 会话和消息 ORM |
| `backend/app/models/answer.py` | 回答、反馈和 Reviewer 结果 ORM |
| `backend/app/models/knowledge.py` | 指标、知识文档和商家记忆 ORM |
| `backend/app/models/attachment.py` | 附件元数据和解析状态 ORM |
| `backend/app/schemas/chat.py` | `ChatRequest`、`ChatResponse` |
| `backend/app/schemas/intent.py` | 模型可输出的查询意图 |
| `backend/app/schemas/visualization.py` | 图表数据协议 |
| `backend/app/schemas/recommendation.py` | 建议、证据和行动协议 |
| `backend/app/schemas/quality.py` | Reviewer 和降级协议 |

ORM 模型与 API Schema 分开，禁止直接把 ORM 对象作为外部接口协议。

### 8.7 Prompt 与知识库

| [规划] 路径 | 职责 |
| --- | --- |
| `backend/app/prompts/intent.py` | 意图识别提示词 |
| `backend/app/prompts/answer.py` | 数据分析和回答提示词 |
| `backend/app/prompts/reviewer.py` | 独立质量审核提示词 |
| `backend/app/prompts/memory.py` | 商家记忆提取提示词 |
| `backend/app/knowledge/index/` | 业务域索引 |
| `backend/app/knowledge/business/` | 团队维护的业务知识 |

正式部署后，运行时可编辑知识应存入 PostgreSQL 或对象存储，不依赖 Railway 临时文件系统。

---

## 九、数据库职责

### 9.1 PostgreSQL：第一阶段必需

保存：

- 商家身份（**MVP 不建用户表**）；
- 会话和消息；
- 回答、Reviewer 结果和用户反馈；
- 导出记录；
- 安全审计事件与 LLM 用量；
- 指标定义；
- 业务知识和商家记忆；
- 附件元数据；
- MVP 阶段的订单、退款、商品和工单数据。

核心表与阶段（权威定义见 `docs/backend-development-plan.md` §7.1）：

```text
[P0] merchants
[P0] conversations
[P0] messages
[P0] answers            # 含 client_request_id 幂等唯一约束
[P0] feedback
[P0] export_files
[P0] audit_logs         # 越权访问与管理员操作
[P0] llm_usage          # 调用次数与 token，供每日预算熔断
[P0] metric_definitions # 含 metric_code 与 display_name
[P0] knowledge_documents
[P0] orders / order_items / refunds / products / support_tickets
[P1] merchant_memories
[P1] attachments
[P2] users              # 真实用户体系上线时才创建
```

`users` 表属于 P2。MVP 用演示 Token 直接映射 `merchant_id`，不要在 P0 迁移里创建用户、密码或会话凭证表。

### 9.2 Redis：按需启用

用于：

- 高频指标缓存；
- 限流；
- 异步任务队列；
- 多实例共享短期状态；
- 附件解析和日报任务状态。

没有这些需求时不要提前引入。

### 9.3 Doris：达到规模后启用

只有出现以下情况才增加 Doris：

- 经营数据达到千万级以上；
- PostgreSQL 聚合查询明显成为瓶颈；
- 需要跨多张宽表进行高并发分析；
- 已经存在 ETL、实时同步或企业数据仓库。

Doris 只负责分析数据。用户、会话、反馈、知识库仍放在 PostgreSQL。

### 9.4 MySQL

新项目默认不需要 MySQL。只有企业现有业务数据源必须使用 MySQL 时，才把它作为上游数据源接入，不再同时承担新项目主数据库职责。

---

## 十、接口协议

**接口路径必须保持下表取值**，除非先同步修改 `docs/PRD.md` §11、前后端开发计划和所有契约测试。本表是索引，`docs/PRD.md` §11 是权威来源。

### 10.1 P0 接口

除 `/api/health`、`/api/ready` 和 `/api/demo/merchants` 外，所有接口都必须携带 `Authorization: Bearer <token>`，服务端由此解析可信商家身份。

```text
POST   /api/chat
GET    /api/conversations
GET    /api/conversations/{id}
DELETE /api/conversations/{id}
POST   /api/answers/{id}/feedback
GET    /api/exports/{id}
GET    /api/metrics/{code}
GET    /api/demo/merchants
GET    /api/health
GET    /api/ready
GET    /api/admin/ops/status
```

- `/api/metrics/{code}` 的路径参数是 `metric_code`，不是中文指标名；
- `/api/demo/merchants` 仅用于演示环境，默认可通过配置关闭且在生产环境关闭；只有对外演示部署显式设置 `DEMO_DEPLOYMENT_MODE=true` 时才可在生产环境开放；
- `/api/ready` 可选，只在需要数据库 readiness 探针时提供；`/api/health` 不查库、不调 LLM；
- `/api/admin/ops/status` 需要 `ADMIN_TOKEN`，返回预算余量、限流命中和降级计数，**禁止返回 Token、Prompt、商家经营数据或完整请求正文**。

### 10.2 P1 接口

```text
GET    /api/reports/daily
POST   /api/attachments
GET    /api/attachments/{id}
DELETE /api/attachments/{id}
GET    /api/memories
PATCH  /api/memories/{id}
DELETE /api/memories/{id}
GET    /api/admin/knowledge/tree
GET    /api/admin/knowledge/documents/{id}
POST   /api/admin/knowledge/documents
PUT    /api/admin/knowledge/documents/{id}
DELETE /api/admin/knowledge/documents/{id}
```

- 知识目录由 `GET /api/admin/knowledge/tree` 提供，**没有** `GET /api/admin/knowledge/documents` 列表接口，文档按 `{id}` 单独读取；
- `/api/memories` 三条让商家查询、纠错和删除自己的记忆，用**商家 Token**——记忆归商家所有，管理员不替商家改记忆。

### 10.2.1 两套凭证

| 凭证 | 请求头 | 用于 | 阶段 |
| --- | --- | --- | --- |
| 商家演示 Token | `Authorization: Bearer <token>` | 所有商家接口 | P0 |
| `ADMIN_TOKEN` | **`X-Admin-Token: <token>`** | `/api/admin/*` | **P0**（运维端点）起，P1 知识后台复用 |
| 导出签名 | 无头，签名在 query 中 | 仅 `/api/exports/{id}` | P0 |

**管理员令牌不复用 `Authorization`。** 两者语义、生命周期和泄露后果都不同；共用一个头会让后端无法区分"商家在调管理接口"和"管理员在调商家接口"。后端对 `/api/admin/*` 只认 `X-Admin-Token`，前端按接口分组装配请求头，不做"有什么加什么"。

`/api/exports/{id}` 是唯一不要求请求头的鉴权接口：签名 URL 让浏览器可以原生下载，理由见 `docs/backend-development-plan.md` §8.0。

### 10.3 Chat 传输协议

`POST /api/chat` 默认返回 **SSE 流**，让用户在 1 秒内看到真实处理阶段，而不是等全部结果返回：

```text
Content-Type: text/event-stream
事件类型：step | done | error
```

- 客户端发送 `Accept: application/json` 时返回普通 JSON；
- `done` 事件的载荷与非流式 `ChatResponse` **完全一致**，前端不得为两条路径维护两套解析；
- 完整事件字段与错误语义见 `docs/backend-development-plan.md` §8.4。

只实现普通 JSON 请求无法满足 PRD 的首字延迟要求，SSE 不是可选项。

### 10.4 ChatResponse 契约位置

**本文件不维护字段清单。** ChatResponse、ChatRequest、ErrorResponse 的唯一权威定义是：

```text
docs/backend-development-plan.md §8.1 / §8.2 / §8.3
   ↓ 实现后由 FastAPI 生成
docs/api.md（OpenAPI 导出）
```

结构要点（细节以上面的契约为准）：

- 单一**扁平** snake_case 结构，不使用 `reviewer.*`、`metric.*` 这类嵌套对象；
- 会话标识统一为 `session_id`，不存在 `conversation_id`；
- 指标字段是 `metric_code` 等扁平键，不是 `metric_name`；导出字段是 `export`，不是 `export_url`；
- 分析来源是**有序数组** `analysis_sources`（主要来源在前），不是单值 `analysis_source`；`CHAT` 和 `INVALID` 返回 `["NONE"]`，不要为了凑"至少一项"而编造来源；
- Reviewer 备注 `quality_notes` 是**字符串数组**，无备注时为 `[]` 而非 `null`；
- 质量状态是 `quality_status`（`PASSED` / `DEGRADED` / `FAILED` / `NOT_RUN`）配 `quality_attempts`，**没有 `RETRIED`**——重试次数由 attempts 表达；
- 不存在 `semantic_notes`，语义说明统一走 `quality_notes` 和 `degraded_reason`；
- 字段分两组：**始终必填**（键必须存在，值可为 `null`）与**按模式必填**。Pydantic 模型不得把按模式必填字段设为无条件必填，否则 `CHAT`、`INVALID` 模式的正常响应会校验失败。

接口字段发生变化时，必须同步：

1. `docs/backend-development-plan.md` §8；
2. Pydantic Schema；
3. OpenAPI 与 `docs/api.md`；
4. TypeScript 类型；
5. 前端渲染；
6. 后端和端到端测试。

---

## 十一、回答模式

建议保留以下模式：

| 模式 | 用途 |
| --- | --- |
| `METRIC` | 指标、趋势和聚合分析 |
| `DETAIL` | 业务明细和 CSV 导出 |
| `RULE` | 平台规则和业务知识 |
| `IDENTITY` | 商家资料和身份信息 |
| `ATTACHMENT` | 附件分析 |
| `CHAT` | 问候和普通对话 |
| `INVALID` | 无法处理或不安全的问题 |

新增模式时，至少检查：

- 意图 Schema；
- Agent 路由；
- 查询服务；
- 回答服务；
- 前端展示；
- 测试用例。

---

## 十二、测试索引

### 后端 [规划]

```text
backend/tests/unit/
backend/tests/integration/
backend/tests/api/
backend/tests/agent/
```

重点测试：

- 商家隔离；
- SQL 白名单和参数绑定；
- 日期范围和行数限制；
- 不同回答模式的路由；
- 指标口径命中与降级；
- Reviewer 重试上限；
- 附件类型、大小和恶意内容；
- 数据库不可用时的显式降级；
- LLM 输出非法 JSON 时的处理。

### 前端 [规划]

```text
frontend/src/**/*.spec.ts
frontend/e2e/
```

重点测试：

- 发送问题和连续追问；
- 加载、错误和降级状态；
- 图表切换；
- 明细表和 CSV 下载；
- 附件上传和移除；
- 采纳、点赞和点踩；
- 桌面端与移动端布局；
- 知识库权限。

真实 LLM 不进入自动化测试。

---

## 十三、本地开发命令

以下命令在对应目标文件创建后使用。

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

启动真实聊天前仍需遵守 R3。

---

## 十四、Railway 部署约定

目标 Railway Project 包含：

| Service | Root Directory | 说明 |
| --- | --- | --- |
| `frontend` | `/frontend` | Vue 静态前端 |
| `backend` | `/backend` | FastAPI API |
| `postgres` | Railway Database | 主数据库 |
| `redis` | Railway Database | 可选缓存和队列 |
| `worker` | `/worker` | 可选异步任务 |

**网络拓扑已定：Backend 公开 + 严格 CORS。** 浏览器直接访问 Backend 公网地址，前端通过 `VITE_API_BASE_URL` 指向它，不引入反向代理容器。因此：

- CORS 只允许 Frontend 的精确 Origin，不使用 `*`；
- 允许头至少包含 `Authorization`、`Accept`、`Content-Type`、`X-Request-Id`；
- Backend 既然公开，**基础限流、单请求 LLM 上限和每日预算熔断就是上线前置条件**，见 §十六 第 10 步。

**Frontend 镜像用 Caddy 托管静态产物**（Node 多阶段构建 → `caddy:2-alpine`）。选它而不是 nginx，是因为 SPA 回退和 `$PORT` 变量注入各只需一行配置。约束：

- **Caddy 不代理 `/api`**——这是上面「不引入反向代理容器」的直接结果。因此 `frontend/src/api/client.ts` 也刻意不提供同源 `/api` 回退：漏配 `VITE_API_BASE_URL` 必须响亮失败，而不是静默把请求打到静态服务器上拿 404；
- **镜像构建期不跑 `npm run codegen`**。Railway 的 frontend Root Directory 是 `/frontend`，构建上下文里没有仓库根的 `docs/`，读不到 `docs/api.json`。`frontend/src/api/generated.ts` 是**提交进仓库**的生成产物，由 `npm run codegen:check` 在本地和 CI 保证它没过期；
- `VITE_API_BASE_URL` 在构建期注入静态产物，必须由 Railway Variables 提供。

部署要求：

- Frontend 和 Backend 使用独立 Dockerfile；
- Backend 监听 Railway 提供的 `PORT`；
- 只信任 Railway 代理注入的转发头，不直接采信客户端的 `X-Forwarded-For`；
- `/api/health` 不调用 LLM；
- 数据库连接必须有启动重试；
- 前后端通过 Railway Variables 引用地址；
- 附件不得依赖容器临时磁盘；
- 数据库迁移在发布阶段执行，不能每个 Worker 同时执行；
- Doris 如需启用，优先部署在 Railway 外部的托管服务或独立集群。

详细步骤写入：

```text
docs/deployment.md
```

---

## 十五、修改功能时先看哪里

| 任务 | 先看 |
| --- | --- |
| 还原主界面 | `yshopping-prototype/`、旧版 `frontend/src/App.vue` 和 `styles.css` |
| 修改聊天协议 | `backend/app/schemas/chat.py`、`frontend/src/types/chat.ts` |
| 修改 Agent 流程 | `backend/app/agent/graph.py`、`state.py` 和对应节点 |
| 增加指标 | `metric_service.py`、`query_service.py`、`metrics.md` |
| 增加业务分类 | 意图 Schema、Agent 路由、查询服务、知识库和前端展示 |
| 修改 SQL | `query_service.py` 和 `repositories/analytics.py` |
| 修改图表 | `visualization_service.py` 和 `MetricChartPanel.vue` |
| 修改经营建议 | `answer_service.py`、回答 Prompt 和 `RecommendationPanel.vue` |
| 修改 Reviewer | `review_service.py`、Reviewer Prompt 和质量测试 |
| 修改附件处理 | `attachment_service.py`、附件 API 和 `ChatComposer.vue` |
| 修改知识库 | `knowledge_service.py`、知识 API 和 `KnowledgeBaseView.vue` |
| 修改数据库表 | ORM Model、Alembic Migration、Repository 和 `docs/database.md` |
| 修改部署 | Dockerfile、Railway 配置和 `docs/deployment.md` |

---

## 十六、开发顺序

按以下顺序完成 0 到 1。**可信身份和商家隔离必须排在任何经营数据查询之前**，否则查询层会先形成没有强制 `merchant_id` 过滤的接口，后续补隔离要重写 Repository 和 Service。

1. 建立 `frontend/` 和 `backend/` 工程骨架；
2. 实现演示 Token 解析和 Merchant Context；
3. 定义 PostgreSQL 模型和 Alembic 迁移；
4. 建立商家隔离 Repository 基础设施，并写**反例测试**（跨商家访问必须 403 并写审计）；
5. 定义 Pydantic / OpenAPI 契约并生成 TypeScript 类型；
6. 迁移 Prototype UI，用 Mock API 打通完整前后端流程；
7. 实现知识检索和结构化意图；
8. 实现安全查询模板；
9. 实现回答、图表、建议和 Reviewer；
10. 实现基础限流、单请求 LLM 上限和每日预算熔断（**部署到公开地址前必须完成**）；
11. Docker 化并部署 Railway；
12. P1：附件、日报、对象存储、知识库后台和商家记忆；
13. P2：真实用户体系、完整审计系统和数据保留策略；
14. 数据规模证明 PostgreSQL 不够时，再评估 Doris。

第 4 步的商家隔离测试必须在第一条经营查询接口上线前通过。第 10 步与 R3 配套：未配置这三项防护时，不得把真实 LLM Key 部署到公开可访问的地址。

详细阶段拆分：后端见 `docs/backend-development-plan.md` §9（**MVP = B0–B7**，B8–B9 为 P1），前端见 `docs/frontend-development-plan.md` §13（**MVP = F0–F6**，F7–F9 为 P1）。

---

## 十七、维护本文件

出现以下情况必须更新 `AGENTS.md`：

- 创建或删除一级目录；
- 移动关键入口文件；
- 新增数据库或外部服务；
- 修改 Agent 主流程；
- 修改部署架构；
- 新增重要安全规则；
- 规划路径正式落地后，需要把 `[规划]` 改成实际状态。
- 每次完成一段可验证工作后，更新 `docs/project-progress.md` 的日期、当前阶段、验证结果、下一步和风险；该文件只保留当前快照，不追加每日流水账。

本文件是索引，不应复制每个模块的全部实现细节。详细设计分别维护在 `docs/` 中，并从本文件链接过去。
