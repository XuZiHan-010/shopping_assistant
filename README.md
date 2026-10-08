<p align="right">
  <b>简体中文</b> · <a href="README.en.md">English</a>
</p>

# Borough 双端 Agent 电商平台

> 基于 Anthropic 的 [Claude Commerce Agents 参考蓝图](https://github.com/anthropics/commerce-agents)进行二次设计与实现。
> 上游来源、改编范围和版权许可见[项目来源与许可](#项目来源与许可)。

> 一套后端、两个 Agent：**顾客端**在店铺里导购、加购和办售后，**商家端**查经营数据、管库存和内容、审批草稿。
> 两端共用同一份身份、订单、库存与审计事实；模型负责理解和选择工具，**金额、库存、SQL 与每一次写入都由后端确定性代码决定**。

<p>
<img alt="Python" src="https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white">
<img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-0.116-009688?logo=fastapi&logoColor=white">
<img alt="Next.js" src="https://img.shields.io/badge/Next.js-16-000000?logo=nextdotjs&logoColor=white">
<img alt="Vue" src="https://img.shields.io/badge/Vue-3.5-4FC08D?logo=vuedotjs&logoColor=white">
<img alt="TypeScript" src="https://img.shields.io/badge/TypeScript-5.9-3178C6?logo=typescript&logoColor=white">
<img alt="PostgreSQL" src="https://img.shields.io/badge/PostgreSQL-16%20%2B%20pgvector-4169E1?logo=postgresql&logoColor=white">
<img alt="MCP" src="https://img.shields.io/badge/MCP-read--only%20server-6E56CF">
<img alt="Railway" src="https://img.shields.io/badge/Deploy-Railway-0B0D0E?logo=railway&logoColor=white">
</p>

这是一个个人工程实践项目，目标是把 Agent 应用里常被一笔带过的部分做实：
有上限的工具循环、按需加载的 Skill、上下文压缩、双端记忆、混合检索、MCP 接入，
以及一套**分层的、敢写出失败数字的评测**。

`Borough` 是虚构的电商平台 IP，三家演示商家与全部经营数据均由程序生成。

---

## 目录

- [一分钟看懂](#一分钟看懂)
- [项目来源与许可](#项目来源与许可)
- [界面](#界面)
- [能力一览](#能力一览)
- [系统架构](#系统架构)
- [一个回合是怎么跑的](#一个回合是怎么跑的)
- [评测](#评测)
- [安全与成本](#安全与成本)
- [技术栈](#技术栈)
- [快速开始](#快速开始)
- [测试与质量门禁](#测试与质量门禁)
- [API 一览](#api-一览)
- [部署](#部署)
- [目录结构](#目录结构)
- [当前状态与已知限制](#当前状态与已知限制)
- [文档索引](#文档索引)

---

## 一分钟看懂

| 主题 | 做法 | 证据 |
| --- | --- | --- |
| Agent 循环 | 自研工具循环，回合数、工具调用、模型调用、token 四项都有硬上限，触顶即可见降级 | 单回合最多 8 轮决策 / 16 次工具调用 / 12 次模型调用 |
| 工具与 Skill | 26 个工具按角色划分工具面；12 个 Skill（顾客 5、商家 7）按需加载，不常驻提示词 | 首次 Skill 选择 46/48（真实模型） |
| 写操作 | 商家端所有写入先成**草稿**，由人在审批界面批准，应用时按当前状态复检；聊天里说「批准」不生效 | 并发批准只有一个赢家、重复批准无二次副作用（确定性测试） |
| 检索 | 关键词 + 向量（pgvector、`bge-small-zh-v1.5` 本地推理）RRF 融合；索引分版本、原子切换、质量不达标不切换 | Recall@5 0.759 → **0.907**，引用正确率 85.19% → **90.74%** |
| 记忆 | 回合结束后经 outbox 异步抽取；顾客与商家记忆隔离，记忆**不能**作为回答里数字的来源 | 错误写入率 5%（2/40），10 条敏感信息诱导零泄露 |
| 上下文压缩 | 工具结果清理与摘要两种策略，身份、来源、草稿版本、安全约束作为锚点保留 | 结构保持率 100%（脚本化模型）；真实模型下来源保留仅 13/24，**未达标** |
| MCP | 只读 MCP 服务端，短期、可撤销、限定店铺与工具范围的独立凭证 | 标准 MCP 客户端集成测试 |
| 安全 | 79 条安全用例作为硬门禁：跨租户、身份伪造、SQL 注入、提示词注入、模型自批 | 79/79，`skip` 不计入通过 |
| 成本 | 全局 / 角色 / 店铺三级每日预算，先查后发；价格分版本，写入时计成本 | 耗尽时上游请求数为 0 |
| 回归 | 自动化测试全部使用脚本化模型，不产生费用 | 后端 4700+、商家端 793、顾客端 141 |

失败的数字同样写在这张表里。完整结果、分母与复核记录见[评测](#评测)。

## 项目来源与许可

Borough 基于 Anthropic 的 [Claude Commerce Agents](https://github.com/anthropics/commerce-agents) 参考蓝图构建，
参考版本为 [`fd4d592`](https://github.com/anthropics/commerce-agents/tree/fd4d59224ab96b43c6dc6888207c67b3bd5a24cf)。
双端 Agent、按需加载的 Skill、受控工具循环及商家写入审批等设计借鉴了该蓝图；
顾客端 4 个、商家端 4 个 Skill 根据上游内容改编，具体来源保留在各 `SKILL.md` 的 `source` 字段中。
Borough 自行实现电商领域模型、可信身份与租户隔离、后端工具和状态机、前端界面、接口契约及评测。
它使用 DeepSeek 模型和自有 `LlmClient`；支持 Anthropic 兼容协议并不表示调用 Claude 或使用 Anthropic 托管服务。

**版权与许可**：上游 `commerce-agents` 版权所有 © 2026 Anthropic PBC，按
[Apache License 2.0](https://github.com/anthropics/commerce-agents/blob/fd4d59224ab96b43c6dc6888207c67b3bd5a24cf/LICENSE)
发布；其版权和许可声明适用于本项目包含或改编的上游材料。Borough 原创部分的版权归相应贡献者所有。
本仓库目前没有根级 `LICENSE`，因此上游的 Apache-2.0 许可**不等于**整个 Borough 仓库都按 Apache-2.0 授权。
Borough 是独立的个人工程项目，与 Anthropic 无隶属或官方背书关系。

## 界面

<img src="docs/images/zh/01-merchant-home.png" alt="商家工作台首页">

<p align="center"><i>商家工作台：今日简报、待处理事项与核心指标；右侧是运营助手</i></p>

| 顾客端店铺 | 草稿审批 |
| :---: | :---: |
| <img src="docs/images/zh/02-shop-home.png" alt="顾客端店铺首页"> | <img src="docs/images/zh/03-merchant-drafts.png" alt="商家端草稿审批"> |
| 智能助手首页：快捷提问、进行中的订单、热门商品与常驻购物车 | 模型只能起草；改动前后对照，由人批准后才生效 |

| 商品与库存 | 运维看板 |
| :---: | :---: |
| <img src="docs/images/zh/04-merchant-catalog.png" alt="商家端商品管理"> | <img src="docs/images/zh/05-ops-status.png" alt="运维看板"> |
| 商品内容完整度由后端按类目规范核对，缺口可让助手起草补充 | 三级预算余量、当日成本、限流与降级计数、工具错误率 |

<p align="center"><i>截图取自本地 Docker Compose 全栈与演示数据，未配置模型 Key。</i></p>

## 能力一览

### 顾客端（Next.js）

- **导购与成单**：按需求检索本店商品、对比、加入购物车；提交订单时占用库存，演示支付与 30 分钟超时关单；
- **售后**：退货资格由后端按时效判定，顾客确认后才建单；寄回、收货、退款全程有事件记录；
- **缺失就是缺失**：商家没填的属性，助手说明没有并生成「内容缺口」信号，不替商家编造；
- **记忆**：偏好经顾客确认才保存，180 天未确认自动过期，可随时查看与删除；
- **访客与绑定**：访客可浏览和加购，订单、售后、记忆需要绑定演示顾客身份。

### 商家端（Vue 3）

- **经营分析**：指标查询、趋势与分类、五步归因；指标公式和 SQL 由后端模板生成；
- **库存运营**：低库存告警进当日简报，补货走草稿审批，库存有事件账本可重算；
- **内容与促销**：内容缺口 → 起草补充 → 批准生效；折扣券有最大优惠幅度护栏；
- **客服与售后**：查看售后单、起草处理决定，顾客只以店铺级脱敏别名出现；
- **口径问答**：检索指标口径与平台规则文档，带引用回答并声明定义版本；
- **明细导出**：CSV 走 HMAC 签名 URL，15 分钟过期，做了公式注入防护。

### 平台

- **MCP 只读入口**：外部 MCP 客户端用受限凭证拿到与工作台一致的数字；
- **知识库后台**：文档维护、`If-Match` 乐观锁、索引状态可见；
- **运维看板**：预算、成本、限流、降级、路由 p95 与 Chat BI 概览；
- **中英双语**：界面、API 响应与回答语言跟随显示语言。

## 系统架构

```mermaid
flowchart LR
    S["顾客端<br/>Next.js"]
    M["商家端<br/>Vue 3"]
    X["外部 MCP 客户端"]

    subgraph API["FastAPI 后端"]
        ID["会话身份<br/>角色工具面"]
        GATE["零 LLM 闸门<br/>限流 / 三级预算"]
        LOOP["工具循环<br/>轮数 / 工具 / LLM / token 上限"]
        SK["Skill 按需加载"]
        TOOLS["工具注册表<br/>确定性查询与写入复检"]
        DRAFT["草稿与审批"]
        MEM["记忆 outbox"]
        RAG["混合检索<br/>关键词 + 向量 RRF"]
    end

    LLM["DeepSeek<br/>OpenAI / Anthropic 兼容协议"]
    PG[("PostgreSQL 16<br/>+ pgvector")]
    CRON["Cron 分发器"]

    S -- "X-Session-Id · SSE" --> ID
    M -- "X-Session-Id · SSE" --> ID
    X -- "MCP 凭证" --> TOOLS
    ID --> GATE --> LOOP
    LOOP <--> LLM
    LOOP --> SK
    LOOP --> TOOLS
    TOOLS --> RAG
    TOOLS --> DRAFT
    LOOP --> MEM
    TOOLS --> PG
    RAG --> PG
    DRAFT --> PG
    MEM --> PG
    CRON --> PG
```

要点：

- **身份只从服务端会话解析**。`merchant_id` 与 `buyer_key` 不采信前端或模型传入；顾客会话与商家会话角色不可互换，
  跨角色、跨商家、跨顾客一律 403 并写审计，「不存在」与「不属于你」返回相同的错误结构；
- **模型的工具面按角色裁剪**。顾客端的模型只能调整购物车数量，下单、支付、取消是界面动作，不在工具面里；
- **前端不代理 API**。两个前端都直连后端公网地址，CORS 只放行两个精确 Origin；漏配后端地址会响亮失败；
- **类型单向流动**：`OpenAPI → generated.ts → Adapter → 领域类型 → Store → 组件`，生成文件禁止手改，由 `codegen:check` 守住。

## 一个回合是怎么跑的

```text
可信会话身份与角色工具面
  → 零 LLM 安全/权限闸门
  → 按需加载受信 Skill 与检索上下文
  → 有轮数、工具、LLM、时间和 token 上限的工具循环
  → 后端确定性查询、计算与写操作复检
  → 顾客界面确认 或 商家审批界面批准
  → 回答、引用、降级与质量信息
  → 异步记忆沉淀
```

几处值得展开的设计：

**工具结果是不可信输入。** 工具返回的文本用带随机标识的围栏包起来再交给模型，围栏内的「指令」不被当作指令；
回答里的每个数字都要能在本回合的工具结果里找到来源，找不到就扣下重写或降级。记忆召回工具被明确标为
「不能作为数字来源」——否则一句「上月净成交额大约 50 万」就能让模型的同款数字通过校验。

**写操作分三段：起草、批准、应用。** 模型只产出草稿（改价、出券、补货、改内容、售后决定）。批准发生在界面上，
绑定草稿版本；应用时按**当前**库存与状态复检，而不是起草时的快照。模型没有批准自己草稿的路径。

**压缩要保住什么。** 长回合里较早的工具结果会被清理或摘要。身份、数据来源与截至时间、指标定义版本、草稿版本、
安全约束作为锚点原样保留；受信 Skill 不参与压缩。

**记忆走 outbox。** 回合成功后只写一条 outbox 记录，由定时任务抽取：幂等、`SKIP LOCKED`、租约与重试上限。
抽取只看用户自己说的话，敏感信息（健康、住址、账号等）在写入前过滤；访客不入队，绑定后也不补抽。

**索引切换是一行指针。** 知识索引分版本构建，验证通过后在单事务里改指针；新版本 Recall@5 低于上一版 95% 就不切换；
构建失败保留旧版本并标陈旧；没有可用版本时检索降级为关键词，并在回答来源上如实标注。

**降级必须看得见。** 数据库、知识库或模型不可用时可以降级，但来源、质量状态和降级原因都进 API 契约并渲染到界面，
不把规则兜底包装成模型分析。

> 仓库里还保留着一条 12 节点 LangGraph 流水线（`backend/app/agent/graph.py`）。它是上一代单端实现，
> 自 2026-09-20 起冻结为**只读评测基线**，用于和新工具循环做对照，不再承接新能力。

## 评测

评测结论分三层，**不能互相替代**：

| 层级 | 用什么跑 | 能证明什么 |
| --- | --- | --- |
| 确定性回归 | 脚本化模型，无费用，进 CI | 身份、闸门、工具路径、状态迁移与降级标注符合设计 |
| 探索性真实运行 | 真实模型，但口径未冻结 | 发现问题，不作选型或验收依据 |
| 真实评测 | 真实模型，样本与评分口径先冻结并记录哈希，调用有账本和上限 | 回答质量 |

评测集：主评测集 104 条（安全 79、质量 25；顾客 49、商家 55；中文 74、英文 30），
另有专项集——RAG 64 条、记忆抽取 40 条、压缩长对话 30 条。

真实模型结果（DeepSeek `deepseek-flash`，2026 年 10 月）：

| 项目 | 结果 | 说明 |
| --- | --- | --- |
| 混合检索 Recall@5 / MRR | 0.759 → **0.907** / 0.639 → **0.802** | 对比纯关键词基线；拒答率 0.90 不变。本地嵌入推理，无模型费用 |
| RAG 引用正确率 | 85.19% → **90.74%** | 忠实度 98.15%，如实拒答 100%；9 个失败里 7 个是没检到但诚实拒答 |
| 新循环 vs 冻结基线 | **6/6** vs 1/6 | 两代实现在共有的 6 项旧能力上对照 |
| 首次 Skill 选择 | 46/48 | 2 例首轮先追问 |
| 记忆抽取错误写入率 | 5%（2/40） | 都出自同一条多句更正用例；敏感诱导 10 条零泄露 |
| v2 质量场景 | **16/19** | 人工逐条阅读 15/19，修复后定向复测为 16/19；自动裁判也给 16/19，但它判通过的用例里有 2 条实际答错 |
| 压缩后来源保留 | 13/24 | **未达标**：两种策略压缩后都补不全来源、截至时间与定义版本 |

几条从评测里学到的事：

- **自动裁判判不了事实对错。** 它判通过的用例里有实际答错的，所以裁判结论不单独作为通过依据，语言一致性等能用代码判的改用代码判；
- **脚本化模型会掩盖整类缺陷。** 它返回预写好的合法输出，「提示词有没有告诉模型该输出什么」在自动化测试里完全不可见，
  所以提示词改动要配一条从 Schema 推导期望值的契约测试；
- **真实模型暴露的问题是另一类。** 比如模型不知道今天几号、把英文时长「30 days」当成无来源数字、工具的自由字符串参数传错取值时悄悄返回 0 条。

报告与原始记录在 [`docs/history/eval/`](docs/history/eval/)，汇总见
[`n5-full-report.md`](docs/history/eval/n5-full-report.md)。

## 安全与成本

| 风险 | 设计 |
| --- | --- |
| 模型生成任意 SQL | 模型只输出经 Pydantic 校验的结构化意图；SQL 由后端模板生成，表名列名走白名单，值全部绑定，日期范围与行数由后端强制 |
| 跨商家 / 跨顾客越权 | 身份只从已验证会话解析；所有查询强制注入商家范围，顾客数据再叠加 `buyer_key`；越权 403 并写审计 |
| 对象存在性泄露 | 「不存在」与「无权访问」同一错误结构；订单详情两种情况各 500 次的响应时间差有时序测试守住 |
| 提示词注入 | 工具结果与检索内容进围栏；模型不能决定金额、库存变化或批准 |
| 模型自批 | 批准只发生在界面，绑定草稿版本；应用时按当前状态复检 |
| 被刷爆 token | 会话级限流、单请求调用与 token 上限、三级每日预算熔断；检查在请求发出之前 |
| 管理与商家凭证混淆 | 商家走 `X-Session-Id`，管理端只认 `X-Admin-Token`；未配置管理令牌时管理路由不挂载 |
| 降级被伪装成正常回答 | 来源、质量状态、降级原因全部进契约并渲染 |
| 密钥进代码 | 全部来自环境变量；构建产物由 `secrets:check` 扫描 |

## 技术栈

**后端**　Python 3.12 · FastAPI · Pydantic v2 · SQLAlchemy 2（async）· Alembic · psycopg · MCP SDK · fastembed（ONNX）·
structlog · pytest · Ruff · mypy

**顾客端**　Next.js 16 · React 19 · TypeScript · Vitest · Playwright

**商家端**　Vue 3 · TypeScript · Vite · Pinia · Vue Router · vue-i18n · ECharts · Vitest · Playwright

**数据与基础设施**　PostgreSQL 16 + pgvector · Docker · Caddy · Railway

**模型**　DeepSeek `deepseek-flash`，经自有 `LlmClient` 接 OpenAI 兼容与 Anthropic 兼容两种协议

## 快速开始

### 方式一：Docker Compose 起全栈

需要 Docker。首次构建会下载嵌入模型（约 95 MB）。

```powershell
git clone https://github.com/XuZiHan-010/shopping_assistant.git
cd shopping_assistant

docker compose up -d postgres
docker compose exec postgres createdb -U borough borough_compose_demo
$env:COMPOSE_DB_NAME = "borough_compose_demo"
docker compose up -d --build
```

再灌演示数据（需要 Python 3.12 与 [uv](https://github.com/astral-sh/uv)）：

```powershell
cd backend
uv sync
$env:DATABASE_URL = "postgresql+psycopg://borough:borough_local@127.0.0.1:55432/borough_compose_demo"
uv run python ../scripts/seed_demo_data.py --seed                    # 三家演示商家
uv run python -m scripts.seed_demo_analytics --force-full-rebuild    # 180 天经营数据
uv run python -m scripts.seed_demo_scenarios --seed                  # 双端场景数据
```

打开商家端 <http://localhost:5173>，从侧栏「顾客视角」进入顾客端（<http://localhost:3000>）。
没有配置 `LLM_API_KEY` 时助手给出**可见的降级说明**，界面动作（加购、下单、支付、审批、售后、看板）都能演示。

### 方式二：本地开发

```powershell
docker compose up -d postgres                 # 127.0.0.1:55432

cd backend
uv sync
$env:DATABASE_URL = "postgresql+psycopg://borough:borough_local@127.0.0.1:55432/borough_test"
$env:FRONTEND_ORIGIN = "http://localhost:5173"
$env:SHOP_ORIGIN = "http://localhost:3000"
$env:DEMO_MERCHANT_TOKENS = '{"merchant-100-token":"00000000-0000-0000-0000-000000000001","merchant-101-token":"00000000-0000-0000-0000-000000000002","merchant-102-token":"00000000-0000-0000-0000-000000000003"}'
uv run alembic upgrade head
uv run python -m app.run                      # http://127.0.0.1:8000

cd ../frontend ; npm ci ; npm run dev         # 商家端 http://localhost:5173
cd ../shop     ; npm ci ; npm run dev         # 顾客端 http://localhost:3000
```

环境变量见 [`.env.example`](.env.example)，每个阈值为什么取当前值都写在注释里。

### 接入真实模型（可选，会产生费用）

```text
LLM_API_KEY=<deepseek-api-key>
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-flash
```

## 测试与质量门禁

自动化测试**全部使用脚本化模型，不产生模型费用**。

```powershell
# 后端
cd backend
uv run ruff check . ; uv run mypy app
$env:REQUIRE_INTEGRATION_DB = "1"; uv run pytest      # 集成测试连真实 PostgreSQL，连不上直接失败

# 商家端
cd frontend
npm run lint ; npm run typecheck ; npm run test
npm run codegen:check       # generated.ts 是否与 OpenAPI 脱节
npm run test:e2e            # Playwright（Mock API）

# 顾客端
cd shop
npm run lint ; npm run typecheck ; npm run test
npm run codegen:check ; npm run tokens:check
```

最近一次记录：后端全量 **4747 passed / 3 skipped / 0 failed**、商家端 **793 passed**、顾客端 **141 passed**
（2026-10-08，后端连真实 PostgreSQL + pgvector；跳过的 3 项是 Windows 上无权创建符号链接的用例）。

几条固化下来的约束：

- 集成测试连真实 PostgreSQL，不用 SQLite——租户隔离、迁移、并发与时序的验收都在这里；
- 安全用例是硬门禁：数据库连不上或用例被 skip，门禁直接失败，而不是悄悄少跑；
- 门禁全绿不等于行为正确：凡是「本该传值、实际传了空值」的形参，都要有断言输入内容的测试。

## API 一览

完整契约由 FastAPI 导出到 [`docs/api.md`](docs/api.md) 与 [`docs/api.json`](docs/api.json)。

| 范围 | 路径 | 凭证 |
| --- | --- | --- |
| 顾客端 | `/api/v2/shop/*`：会话、Chat（SSE）、商品、购物车、订单、售后、记忆 | 公开浏览免凭证，其余 `X-Session-Id`（顾客会话） |
| 商家端 | `/api/v2/merchant/*`：会话、Chat（SSE）、指标、商品、库存、订单、售后、草稿、信号、简报、记忆 | `X-Session-Id`（商家会话） |
| MCP | `POST /api/v2/merchant/mcp` | 独立的短期只读凭证 |
| 管理 | `/api/admin/*`：知识库、索引、运维状态、Chat BI | `X-Admin-Token` |
| v1 兼容 | `/api/chat` 等上一代接口 | 演示 Token |
| 探针 | `/api/health`、`/api/ready` | 无 |

v2 共 53 条路径，与 PRD 逐条对账（`backend/scripts/audit_routes.py`）。

## 部署

目标拓扑是 Railway 上的四个服务加外部 PostgreSQL：

| 服务 | 目录 | 说明 |
| --- | --- | --- |
| `merchant` | `/frontend` | Vue 静态产物，Caddy 托管，不代理 `/api` |
| `backend` | `/backend` | FastAPI；数据库迁移在发布阶段执行一次 |
| `shop` | `/shop` | Next.js standalone |
| `cron` | `/backend` | 每 5 分钟运行统一分发器：关单、草稿过期、记忆抽取、索引重建、演示数据滚动 |

配置即代码在各目录的 `railway.json` 与 `backend/railway.cron.json`，步骤与环境变量见
[`docs/deployment.md`](docs/deployment.md)。公开部署真实模型 Key 之前，限流、单请求上限与每日预算熔断三项要先在公网域名上验收。

只部署 `merchant` 与 `backend` 两个服务也能运行：商家工作台完整可用，侧栏不显示「顾客视角」入口，定时任务不自动执行。

## 目录结构

```text
├── backend/                    # FastAPI 后端
│   ├── app/
│   │   ├── agent/loop/         # 工具循环：runner、上限、围栏、数字校验、压缩
│   │   ├── agent/graph.py      # 上一代 12 节点 LangGraph，冻结为评测基线
│   │   ├── tools/              # 工具注册表、闸门与顾客 / 商家工具
│   │   ├── skills/             # Skill 规格、加载器与 12 个 SKILL.md
│   │   ├── memory/             # 双端记忆：抽取、过滤、存储、outbox 管线
│   │   ├── knowledge/          # 混合检索、嵌入、RRF 融合、索引版本
│   │   ├── mcp/                # MCP 只读服务端与凭证
│   │   ├── llm/                # LlmClient、双协议适配器、预算守卫、价格版本
│   │   ├── eval/               # 评测集、评分器、裁判与真实评测入口
│   │   ├── api/routes/v2/      # 顾客端与商家端路由
│   │   ├── jobs/               # Cron 分发器与各定时任务
│   │   └── services/ repositories/ models/ schemas/ ...
│   ├── migrations/             # Alembic
│   └── tests/                  # unit / integration / api / eval / e2e
├── frontend/                   # 商家端（Vue 3）
├── shop/                       # 顾客端（Next.js）
├── docs/                       # PRD、契约、API 导出、部署手册、评测报告
├── plans/                      # 实施计划
└── scripts/                    # 演示数据、OpenAPI 导出
```

## 当前状态与已知限制

项目按 N1–N5 五个里程碑推进。N1–N4 的验收检查已完成（带遗留缺陷），N5 的本地实现已完成、整体验收尚未收口。
下面这些是已知且尚未解决的：

- **售后场景在真实模型下还没有端到端走通**：默认压缩策略会清掉同一回合后面还要用的工具结果；
- 触到工具调用上限时回答可能为空；
- 顾客端商品搜索不跨语言，英文关键词搜不到中文商品；
- 记忆抽取在「多句更正」这一种说法上会误抽历史片段；
- 平台规则库里的售后文档内容还很薄，规则问答的依据有限；
- 预算熔断按保守估算预留，上游实际用量高于预留时，单次调用仍可能略微超出当日上限；
- 性能基准、随机攻击集的置信区间、裁判与人工一致性校准尚未执行。

演示边界：演示商家与演示顾客不是真实登录；支付与退款是模拟的；附件、OCR、真实用户体系、多规格商品与 MCP 写工具不在本版范围。

进度快照见 [`docs/project-progress.md`](docs/project-progress.md)。

## 文档索引

| 文档 | 内容 |
| --- | --- |
| [`docs/PRD.md`](docs/PRD.md) | 产品范围、用户故事、状态机与验收标准 |
| [`docs/backend-development-plan.md`](docs/backend-development-plan.md) | 后端架构边界与接口字段契约 |
| [`docs/api.md`](docs/api.md) | OpenAPI 导出 |
| [`docs/demo-script.md`](docs/demo-script.md) | S1–S8 演示脚本：每一步体现哪条工程规则 |
| [`docs/history/eval/`](docs/history/eval/) | 评测报告、人工复核与原始记录 |
| [`docs/deployment.md`](docs/deployment.md) | Railway 部署与运维手册 |
| [`docs/project-progress.md`](docs/project-progress.md) | 进度快照、验证结果与风险 |
| [`AGENTS.md`](AGENTS.md) | 开发规则与入口索引 |

---

- 演示商家、经营数据与知识文档均为虚构，仅用于功能演示；
- 本项目为个人工程实践，与任何真实电商平台无关。
