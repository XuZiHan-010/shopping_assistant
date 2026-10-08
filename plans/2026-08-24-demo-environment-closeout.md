# 演示环境收口与数据保鲜实施计划

> **状态：全部裁定完毕，九个 Task 均可开工，无待裁定阻塞项。**
> 2026-08-24 用户裁定 **Q1=b / Q2=c / Q3=a**，同日按 R9 核对参考项目后确定知识导入机制
> （§2.4，载体形态裁定为方案 a），并顺带发现一处真实缺口（§2.4.3 导入语义与参考相反，
> 会覆盖后台改动，已排进 Task 6 Step 2 修复）。本文件由同日的知识库对齐核对派生而来。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把演示环境从「代码已完成、数据缺失」变成「本地与线上都随时可完整演示，且不会随日历自然过期」，同时把线上经营数据的写入口收敛为唯一一个。

**为什么需要这份计划：** MVP 的功能代码早已完成并部署，但两次实际打开页面看到的都是空数据——日报指标全 0、知识库目录树全空。根因不在代码，在于**演示数据的生命周期从来没有被当作交付物管理**：经营数据以「灌入当天」为终点生成 180 天、会随真实日期滑出窗口；知识库线上从未导入；本地两者都会被全量 pytest 清空。

**范围边界：** 本计划处理演示环境的数据完整性、保鲜机制，以及为此必须解决的生产写入口与日报缓存问题。功能缺口（附件 OCR、语义层校验闭环、无效意图不落表等）不在本计划内，见 §11。

---

## Global Constraints

以下为项目级约束，**每个 Task 隐含包含本节**，不再逐条重复：

- **R1** 面向用户的内容一律中文；代码标识符英文。
- **R2** 未经用户明确许可，不执行 `git commit` / `git push` / `git tag` / `gh pr create` / `gh pr merge`，也不使用 `git reset --hard`、`git clean`。**本计划各 Task 末尾的 Commit 步骤需用户逐次授权。**
- **R3** 除 Task 9 Step 3 外，本计划**全程不需要真实 LLM 调用**。所有测试 mock LLM，验证走本地数据库与只读 HTTP 探测。Task 9 Step 3 必须单独说明模型、次数与费用并取得同意。
- **R4** LLM 不生成也不执行 SQL。本计划新增的 SQL 全部是后端固定模板 + 绑定参数。
- **R5** 商家数据隔离。重算端点必须校验商家归属并写审计；Seed 与滚动任务按商家整体处理，不得跨商家写入。
- **R6** 密钥只来自环境变量与 Railway Variables。本计划不新增密钥，复用 `ADMIN_TOKEN` 与 `ALLOW_DEMO_DATA_REFRESH`。管理员令牌不得写入任何文件、日志或计划文档。
- **R7** 降级必须可见。重算失败、商家不存在、日期越界都必须返回明确错误码，不得静默返回旧缓存。
- **R8** `yshopping-merchant-ai 4/` 只读。任何导入方案都不得写入、重命名、格式化其中文件，**也不得把该目录整体打进镜像**。
- **R10** 本文件属实施计划，放 `plans/`；设计说明写 `docs/specs/`；不新建以技能命名的目录。
- **契约同步链**（Task 1 必须走完）：`docs/PRD.md` §11 → `docs/backend-development-plan.md` §8 → `AGENTS.md` §10 索引 → Pydantic Schema → OpenAPI 与 `docs/api.md` → TypeScript 类型 → 前端渲染（本端点无前端消费方，此环可空但需书面说明）→ 后端与端到端测试。
- **迁移链**：当前唯一 head 是 `20260823_0014`。本计划**默认不新增迁移**；若 §2.4 的裁定结果需要建表或加列，必须串在这条链上，**不得产生第二个 head**。
- **验证命令**：

  ```powershell
  cd backend
  uv run pytest <具体路径> -v
  uv run ruff check .
  uv run mypy app
  ```

---

## 0. 现状事实（2026-08-24 实测，非推断）

### 0.1 本地环境

| 表 | 行数 | 说明 |
| --- | --- | --- |
| `merchants` | 3 | 完整 |
| `knowledge_documents` | 23 | **2026-08-24 刚导入**，此前为 0 |
| `orders` / `refunds` / `products` / `support_tickets` | 0 | 被上一次全量 pytest 清空 |
| `answers` | 0 | 同上 |

本地库：`127.0.0.1:55432/borough_test`，容器 `merchant_assistant-postgres-1`，用户 `borough`。

**全量 pytest（`REQUIRE_INTEGRATION_DB=1`）会清空 `knowledge_documents` 与六张经营表**，这是集成测试的设计行为。因此「跑完测试 → 演示前必须重灌」是常态流程，不是异常处置。

### 0.2 线上（Railway）环境

- 部署于 2026-08-17，灌入 3 个商家 + 17,955 行经营数据，覆盖 **2026-02-19 ~ 2026-08-17**；
- **知识库从未导入**。`docs/project-progress.md:31` 已把「知识库导入」列为 MVP 未完成项，本轮核对再次确认部署记录中没有任何导入动作；
- 今日 2026-08-24，经营数据末端已过期 7 天。日报取「昨天」（`report_service.py:99`）落在 08-23，故当日指标全 0；而 7 日信号窗（08-17~08-23）尚能扫到 08-17，所以建议文案仍走有数据分支——**「指标全 0 + 建议正常」正是数据窗口刚滑出的特征**；
- **线上是否已部署到 `ad2c0b1` 未知**。`origin/main` 是该提交，但最后一次记录在案的部署验证是 2026-08-18，早于 Chat BI 看板的三个提交。Task 5 用只读探测确定。

### 0.3 滚动任务在空库/断档时的行为（已核实，Q3=a 的前提）

`app/jobs/seed_demo_rolling.py` 的 `roll_forward()`：

```python
start = (
    latest + timedelta(days=1)
    if latest is not None
    else business_day - timedelta(days=window_days - 1)   # 空库回溯 180 天
)
```

- **空库**（`latest is None`）→ 自动生成完整 180 天窗口；
- **有断档**（线上当前情形，`latest = 2026-08-17`）→ 从 08-18 逐日补齐至业务今天，这是设计中的「漏跑追赶」路径；
- 双重护栏：`require_demo_refresh_permission()` 要求 `ALLOW_DEMO_DATA_REFRESH=true`；`_require_demo_merchants()` 要求商家集合与 `default_merchants()` **精确相等**，否则拒绝写入；
- 全程在一个事务内，先取 `pg_advisory_xact_lock(2026081801)`，并只清理窗口外事实（删父行前用 `NOT EXISTS` 确认无子行引用，避免 CASCADE 误删）。

**结论：Q3=a 成立，线上无需「先人工灌一次」。**

### 0.4 脚本与镜像

| 脚本 | 位置 | 关键约束 |
| --- | --- | --- |
| `app.jobs.seed_demo_rolling` | `backend/app/jobs/` | **在镜像内**（`COPY app ./app`），增量滚动，不重建历史 |
| `scripts.seed_demo_analytics` | `backend/scripts/` | **不在镜像内**；`reject_production()` 仅检查 `APP_ENV`；按商家整体 DELETE 后重写 |
| `scripts.import_wiki` | `backend/scripts/` | **不在镜像内**；必填 `--root`，读取参考项目只读 Wiki（镜像内不存在该目录） |
| `scripts.seed_demo_data` | 仓库根 `scripts/` | **不在镜像内**；同样只检查 `APP_ENV` |

`backend/railway.cron.json` 已写好（`startCommand: python -m app.jobs.seed_demo_rolling`、`cronSchedule: 10 16 * * *`、`restartPolicyType: NEVER`、无 healthcheck、无 preDeployCommand），**Cron Service 尚未在 Railway 控制台创建**。

### 0.5 未提交改动

```text
 M docs/project-progress.md
 M docs/yshopping-parity-audit.md
```

均为 2026-08-24 知识库对齐核对的产物（§5.17 偏离登记、§2 计数说明、进度快照同步）。

---

## 1. 目标与非目标

**目标：**

1. 线上经营数据的写入口收敛为**唯一一个**：`seed_demo_rolling` Cron。本机直连生产库执行破坏性 Seed 的路径彻底废弃；
2. 日报缓存失效有正式的运维入口，演示恢复不依赖「等到明天」；
3. 线上知识库补齐，且 `category` 等检索所需元数据不退化；
4. 本地任何时候能在 5 分钟内恢复成完整可演示状态，步骤写进文档而非散落在对话里。

**非目标：**

- 不改业务逻辑、不改既有契约字段、不扩大演示数据规模；
- 不实现 §11 列出的任何功能缺口；
- 不改动 `GET /api/reports/daily` 的既有幂等行为。

---

## 2. 裁定结果（2026-08-24，用户裁定）

| 问题 | 裁定 | 理由 |
| --- | --- | --- |
| **Q1** 日报幂等缓存 | **(b) 管理员重算端点** | 日报缓存失效属运维动作，不应塞进 Seed 让它跨进会话领域；也不能靠「等到明天」保证演示可靠性 |
| **Q2** 生产 Seed 护栏绕过 | **(c) 废弃线上手工灌数** | `APP_ENV=development` + 生产库是危险绕过；`ALLOW_DEMO_DATA_REFRESH` 按项目规则本就只应授予独立 Cron |
| **Q3** 线上保鲜机制 | **(a) 立即启用 Cron** | 已核实滚动任务在空库/断档时都能自动补齐（§0.3），无需先人工灌一次 |

**未采纳的两套组合及理由（备查）：**

- 「接受缓存 + Cron」：改动少，但演示恢复不确定；
- 「Seed 清日报 + 先人工后 Cron」：保留两套生产写入口，且让 Seed 跨进会话领域，安全边界最差。

### 2.1 Q1 端点契约（裁定时收紧的条件）

```text
POST /api/admin/reports/daily/recompute
```

| 条件 | 要求 |
| --- | --- |
| 鉴权 | **仅** `X-Admin-Token`，不接受 `Authorization`（AGENTS.md §10.2.1） |
| 请求体 | `merchant_id`、`report_date`、**必填 `reason`** |
| 商家范围 | 必须属于配置中的三家演示商家，否则拒绝 |
| 日期范围 | 限制在最近 180 天，**禁止未来日期** |
| 并发 | 对日报 Answer 加锁后删除并重新物化 |
| 反馈冲突 | 该日报已存在反馈时返回 **409**，避免重算后反馈指向不同内容 |
| 审计 | 全程写入管理员审计日志（含 `reason`） |
| 既有行为 | `GET /api/reports/daily` 的幂等行为**保持不变** |

### 2.2 Q2 收紧条件（超出原选项 c 的部分）

`seed_demo_analytics.py --force-full-rebuild` 明确降级为**仅本地工具**：**在代码层拒绝非本机数据库，而不只是检查 `APP_ENV`**。理由是 `APP_ENV` 是一个可以被随手改掉的环境变量，而「目标库是不是本机」是一个更难被误绕过的事实判断。`scripts/seed_demo_data.py` 同理。

线上唯一经营数据写入口是 `seed_demo_rolling` Cron。

### 2.3 Q3 执行归属

创建 Cron Service、配置变量、手工触发首次滚动**全部是 Railway 控制台操作**：Railway CLI 未安装，Windows 控制台自动化运行时不可用，**必须由有控制台权限的用户完成**，agent 无法代劳。

### 2.4 线上知识导入的机制（R9 已给出答案，载体已裁定）

裁定「知识导入独立于经营数据 Seed，不与 Q2 混在一起」**方向正确且予以保留**。但裁定时建议的具体机制——「通过管理员知识库 API 导入」——**经核实不可行**（三个障碍见 §2.4.2），且 R9 核对发现**参考项目对这个问题本来就有成熟方案**，应当照搬其语义。

#### 2.4.1 参考项目怎么做（`deploy-railway.md` §3.5「知识库怎么进容器」）

```text
构建期  runtime/{llm-wiki/index,llm-wiki/业务,wiki}  ──►  镜像 /app/wiki-seed
                                                            │
启动期  docker-entrypoint.sh  cp -rn  ─────────────────────►  卷 /app/runtime
                                       （不覆盖已存在文件）
```

- **首次部署**：卷为空，种子完整填充；
- **后续部署**：`cp -rn` **只补新增文件，不覆盖任何已存在文件**，因此通过维护后台做的线上修改不会被部署冲掉；
- **明示的代价**：镜像里更新了某篇已存在的文档时，卷里的旧版本继续生效——改线上文档必须走维护后台，只改仓库不生效；
- `memory/merchants/` 与 `exports/` 是运行时数据，被 `.gitignore` / `.dockerignore` 排除，只存在于卷里，**不进种子**。

知识库根由 `WikiRootProvider` 解析：优先 `YSHOPPING_WIKI_PATH`，否则回落 `runtime/llm-wiki`。

#### 2.4.2 能直接照搬吗——语义能，实现不能

**实现不能照搬**，因为存储介质已经是一处**已登记的有意偏离**：

| | 参考项目 | 我们 | 依据 |
| --- | --- | --- | --- |
| 知识与记忆存储 | 文件系统 + Railway Volume | PostgreSQL | `docs/yshopping-parity-audit.md` §5.8 |
| 副本数 | 必须单副本（卷只能挂单实例、进程内 store、记忆由单线程 daemon 写本地文件） | 无此约束 | 参考 `deploy-railway.md` §4 |

`AGENTS.md` §8.7 明确要求「正式部署后，运行时可编辑知识应存入 PostgreSQL 或对象存储，**不依赖 Railway 临时文件系统**」。因此不改存储介质，这一点不重开。

**但语义必须照搬**，映射如下：

| 参考语义 | 我们的对应做法 |
| --- | --- |
| 构建期烘种子进镜像 | 23 篇作为**仓库内数据文件**随镜像分发（不把只读 Wiki 目录打进镜像，R8） |
| 启动期 `cp -rn` **不覆盖** | 写库语义必须是**「不存在才插入」**，不是 upsert |
| `memory/` 不进种子 | 种子只含 `index/` 与 `业务/` 的 **21 篇**，`memory/` 那 2 篇不进（同时绕开 §2.4.3 的障碍 1） |
| 改线上文档走维护后台 | 同左，写进部署手册 |

#### 2.4.3 🔴 顺带发现的真实缺口：我方导入语义与参考相反

`import_wiki.py` 用的是 `KnowledgeRepository.upsert_by_source_path()`——**每次执行都覆盖同 `source_path` 的既有内容**。参考项目是 `cp -rn`，**明确不覆盖**。

后果：线上管理员通过 `/knowledge-base` 后台修改过某篇文档后，只要再跑一次导入，改动就被静默冲掉，且不触发任何降级或冲突提示——这与后台自身的 SHA-256 乐观锁（428/412）设计意图直接矛盾：后台费力防住了并发覆盖，导入脚本却从旁边绕过去了。

**这是 R9 意义上的真实缺口，不是有意偏离。** 处置随本节机制一并落地：种子导入路径改为 insert-if-absent；若确实需要强制覆盖（例如本地重置），由一个显式的 `--overwrite` 开关承担，**默认关闭**，并在文档中写明它会丢失后台改动。

#### 2.4.4 种子的载体形态：裁定为 (a) 仓库内 JSON 快照

**2026-08-24 用户裁定：采用 (a)。**

| 项 | 取值 |
| --- | --- |
| 种子文件 | `backend/app/knowledge/wiki_seed.json` |
| 生成脚本 | `backend/scripts/export_wiki_seed.py`（从只读 Wiki 生成，R8 只读） |
| 漂移检查 | 重新生成到临时文件并与提交版本逐字节比对，不一致即失败；比照 `frontend/scripts/check-generated.mjs` |
| 每条记录字段 | `source_path` / `category` / `title` / `content` / `is_complete` / `source` |
| 内容范围 | 只含 `index/` 与 `业务/`，共 **21 篇**；`memory/` 不进种子 |

**放在 `app/knowledge/` 下是有意的**：`backend/Dockerfile` 已有 `COPY app ./app`，`backend/.dockerignore` 只排除 `.env`/`.venv`/缓存/`tests`/`*.pyc`，**不排除 `.json`**。因此种子随镜像分发**不需要改动 Dockerfile**——放到 `scripts/` 下则需要额外加一行 COPY，反而多一处可漏配的地方。

**未采纳的两个候选（备查）：**

- **(b) Python 常量模块**（`app/knowledge/seed_data.py`）：类型更强、无需读文件，但 23 篇 Markdown 全文塞进 Python 字符串常量后 diff 几乎不可读，知识内容的评审成本会显著上升；
- **(c) Alembic data migration**：随迁移链自动执行、无需启动钩子，但知识内容变更会污染迁移历史，且「迁移必须永远可复现」与「知识会被后台改」直接冲突。

#### 2.4.5 原「管理员 API 导入」不可行的三个障碍（备查）

| # | 障碍 | 位置 | 后果 |
| --- | --- | --- | --- |
| 1 | `memory/` 根写入直接 403 | `path_policy.py:60-61`（`resolve_writable_document` 第一条判断） | 23 篇里有 2 篇位于 `memory/`（`memory/README.md`、`memory/merchants/100-…/电商交易-….md`），API 创建不了 |
| 2 | 建业务域会写 4 篇占位文档 | `knowledge_admin_service.py:112-119` | 10 个域 = 40 篇 `待补充.md`，其中 20 篇落在 `ddl` / `指标或调用指标平台mcp的skill` 两板块，**与 §5.17 登记的「两板块为空目录」状态不符** |
| 3 | `create_document` 硬编码 `category="UNKNOWN"` | `knowledge_admin_service.py:77` | `import_wiki` 是从目录名推导 `TRADE`/`GOODS`/`PLATFORM_RULE` 等十类的；退化成 `UNKNOWN` 会**打断知识检索的分类收窄**，导进去也检索不到——等于白导 |

第 3 条最致命：结果是「线上有文档但查不到」，且不触发任何降级分支，属静默失效。

障碍 1 在照搬参考语义后自动消失——参考项目的种子本就不含 `memory/`，我们的种子同样只取 `index/` 与 `业务/` 的 21 篇。障碍 2、3 则说明**管理员 API 是给人用的维护入口，不是给机器用的批量导入入口**，两者不应混用。

---

## 3. Task 1 · 日报重算的产品与 API 契约

**前置：** 无。**产出：** 文档与契约，不含实现。

- [ ] **Step 1** 写 `docs/specs/2026-08-24-daily-report-recompute-contract.md`，把 §2.1 的表格展开为完整契约：请求/响应 Schema、全部错误码（商家不存在、非演示商家、日期越界、未来日期、反馈冲突 409、并发冲突）、审计事件字段、`reason` 的长度与字符约束。
- [ ] **Step 2** 在 `docs/PRD.md` §11 的 P1 接口清单新增该路径，并说明它**不改变** `GET /api/reports/daily` 的幂等语义。
- [ ] **Step 3** 在 `docs/backend-development-plan.md` §8 补精确字段与错误契约。
- [ ] **Step 4** 在 `AGENTS.md` §10.2 的 P1 接口清单与 §8.2 路由索引同步补一行。
- [ ] **Step 5** 书面说明本端点**无前端消费方**（运维用 curl/Postman 调用），因此契约同步链的「前端渲染」一环为空——这是有意决定，不是遗漏。
- [ ] **Step 6** 【需用户授权】Commit。

**验收：** 契约文档能独立回答「什么情况返回什么码」，无需读代码。

---

## 4. Task 2 · TDD 实现日报重算端点

**前置：** Task 1 完成。**全程 mock LLM（R3）。**

- [ ] **Step 1** 先写失败测试，覆盖：正常重算、非演示商家拒绝、未来日期拒绝、超 180 天拒绝、缺 `reason` 拒绝、已有反馈返回 409、跨商家越权 403 + 审计、并发重算不产生重复行。**看着它们红。**
- [ ] **Step 2** 实现 `POST /api/admin/reports/daily/recompute`，依赖 `require_admin_token`（只认 `X-Admin-Token`）。
- [ ] **Step 3** 实现锁 → 删除旧 Answer → 重新物化的事务流程，复用 `DailyReportService` 已有的构建逻辑，**不复制一份**。
- [ ] **Step 4** 实现审计写入，`reason` 落 `audit_logs`；确认日志不记录商家经营数据与令牌。
- [ ] **Step 5** 确认 `GET /api/reports/daily` 的既有测试全部保持绿——**幂等行为不得被本次改动影响**。
- [ ] **Step 6** 重新导出 OpenAPI：`uv run python -m scripts.export_openapi`，同步 `docs/api.json` / `docs/api.md`。
- [ ] **Step 7** 前端 `npm run codegen`，确认 `generated.ts` 变更只含新端点；跑 `npm run codegen:check`。
- [ ] **Step 8** 门禁：`uv run pytest`（含 `REQUIRE_INTEGRATION_DB=1`）、`ruff check`、`ruff format --check`、`mypy app`。
- [ ] **Step 9** 【需用户授权】Commit。

---

## 5. Task 3 · 把全量 Seed 收紧为仅本地数据库可运行

**前置：** 无（可与 Task 1/2 并行）。

- [ ] **Step 1** 先写失败测试：给定一个非本机 `DATABASE_URL`（如 Neon 域名），`seed_demo_analytics` 与 `seed_demo_data` 必须拒绝执行，**且拒绝不依赖 `APP_ENV` 的取值**（测试里显式设 `APP_ENV=development` 仍须拒绝）。
- [ ] **Step 2** 实现本机判定。判定依据需在实现时明确并写进注释（建议：解析 `DATABASE_URL` 的 host，只允许 `localhost` / `127.0.0.1` / `::1` 与 compose 服务名 `postgres`；**白名单而非黑名单**）。
- [ ] **Step 3** 保留原有 `reject_production()` 作为第二道，不删——两道护栏语义不同，一道判环境、一道判目标。
- [ ] **Step 4** 在两个脚本的 docstring 与 `docs/deployment.md` 写明：**它们是仅本地工具；线上唯一经营数据写入口是 `seed_demo_rolling` Cron**。
- [ ] **Step 5** 门禁同 Task 2 Step 8。
- [ ] **Step 6** 【需用户授权】Commit。

**验收：** 把生产 `DATABASE_URL` 喂给这两个脚本，无论 `APP_ENV` 取什么值都必须失败退出。

---

## 6. Task 4 · 恢复并验收本地环境

**前置：** 无。**零费用。**

- [ ] **Step 1** 确认容器运行：`docker ps` 含 `merchant_assistant-postgres-1` 且 healthy。
- [ ] **Step 2** 确认迁移：`uv run alembic heads` 输出唯一 head `20260823_0014`，`alembic current` 与之一致。
- [ ] **Step 3** 先灌三家演示商家：`uv run python ../scripts/seed_demo_data.py --seed`；完整 pytest 会清空 `merchants`，经营数据表的外键要求此步先于下一步。
- [ ] **Step 4** 灌经营数据：`uv run python -m scripts.seed_demo_analytics --force-full-rebuild`（约 40 秒）。**Task 3 完成后此步须在本机库上仍然成功**；若失败说明本机判定过严，回到 Task 3 Step 2。
- [ ] **Step 5** 验证：`orders` 回到数千量级，`max(business_date)` 等于业务今天。
- [ ] **Step 6** 确认 `knowledge_documents` 为 21 篇镜像种子；若期间跑过全量 pytest 则重跑：

  ```powershell
  uv run python -m scripts.import_wiki --root "../yshopping-merchant-ai 4/yshopping-merchant-ai/runtime/llm-wiki"
  ```

- [ ] **Step 7** 在 `docs/deployment.md` 新增「演示前数据检查清单」一节，写明上述命令、**全量 pytest 会清空这些数据**这一前提，以及日报缓存需用 Task 2 的端点重算。
- [ ] **Step 8** 端到端手工验收（本地，mock 或真实模型均可，用真实模型须先取得费用授权）：日报六项指标非 0；指标类问题出图表；**RULE 类问题「我要货品上架，具体规则有吗？」命中知识而非降级**。
- [ ] **Step 9** 【需用户授权】Commit。

---

## 7. Task 5 · 只读探测线上现状（**2026-08-24 已执行，仅剩 Step 5 与 Step 8**）

**前置：** 无。**零写入、零费用。**

**线上地址（已确认）：**

```text
前端  https://shoppingassistant-production-3439.up.railway.app
后端  https://shoppingassistantbackend-production.up.railway.app
```

后端地址由前端入口 bundle 中构建期注入的 `VITE_API_BASE_URL` 提取，无需另行索取。

- [x] **Step 1** 域名已由用户提供（前端），后端从 bundle 提取。
- [x] **Step 2** `/api/health` = `{"status":"ok","version":"0.1.0"}`；`/api/ready` = `{"status":"ready"}`，数据库连通。
- [x] **Step 3** `/api/demo/merchants` 返回 3 个商家，ID `…0001/0002/0003`，**与 `default_merchants()` 精确匹配**。Cron 的 `_require_demo_merchants()` 前提已满足，Task 7 可以放心创建。
- [x] **Step 4** **前后端均已部署到含 Chat BI 看板的当前版本**：前端 bundle 含 `ops-dashboard` / `Chat BI`；后端 `/api/admin/analytics/chatbi/overview` 返回 **401 而非 404**。**无需重新部署**，本 Step 原先设想的「若 404 则先重部署」分支不成立。
  - 附带确认：`/api/admin/ops/status`、`/api/admin/knowledge/tree` 同样 401，说明 **`ADMIN_TOKEN` 已在 Railway 配置**（未配置时整个 admin 路由不挂载，应为 404）。
  - 方法学备注：`/ops-dashboard` 是 SPA history 路由，**直接 GET 它永远返回 200 index.html，不能作为版本信号**；可靠信号是 bundle 内的字符串与后端路由的 401/404 差异。
- [ ] **Step 5** 带 `X-Admin-Token` 请求 `GET /api/admin/knowledge/tree`，确认三个根下有无文档节点。**阻塞：需用户提供生产 `ADMIN_TOKEN`**（与本地 `backend/.env` 中的值不同）。**令牌不得写入任何文件或日志。** 在此之前，「线上知识库从未导入」仍只是基于部署记录的推断。
- [x] **Step 6** `/api/reports/daily`（商家100）= `report_date=2026-08-23`、六项指标全 0、`degraded=false`，建议文案走**有数据分支**——当日无数据、7 日窗有数据，与经营数据末端停在 2026-08-17 一致。陈旧缓存 `answer_id = 79e5e293-2a19-4f23-869f-23b9f9094c4b`，是 Task 8 的重算对象。
  - 附带：`/api/metrics/gmv` 返回完整 13 字段双口径（`source=METRIC_CATALOG`、`generated=false`），**`metric_definitions` 线上有数据**；`/api/conversations` 最后活动 2026-08-18，均为当时验收残留。
- [x] **Step 7** 结果已回填 `docs/project-progress.md`（2026-08-24「线上现状实测」条目），推断措辞已替换为实测出处。
- [ ] **Step 8** 【需用户授权】Commit。

**验收：** 进度快照中关于线上状态的每一句都有实测出处——**除 `knowledge_documents` 行数外均已达成**，该项待 Step 5 解除阻塞。

---

## 8. Task 6 · 线上知识种子导入（**前置：Task 5**）

> 机制语义由 R9 定死（§2.4.2），载体已裁定为 JSON 快照（§2.4.4），障碍备查见 §2.4.5。

- [ ] **Step 1** 落地种子载体（§2.4.4）：
  - 写 `backend/scripts/export_wiki_seed.py`，复用 `parse_wiki_tree()` 从只读 Wiki 生成 `backend/app/knowledge/wiki_seed.json`，六个字段齐全，**只含 `index/` 与 `业务/`**；输出需稳定排序且格式确定（`ensure_ascii=False`、固定缩进），否则漂移检查会因无关的键序变化误报；
  - 写漂移检查（`backend/scripts/check_wiki_seed.py` 或等价的 pytest 用例）：重新生成到临时文件并与提交版本逐字节比对，不一致即失败；
  - 确认无需改 `Dockerfile`——`COPY app ./app` 已覆盖，`.dockerignore` 不排除 `.json`。**若发现需要改 Dockerfile，说明文件放错了位置。**
- [ ] **Step 2** **把导入语义从 upsert 改为 insert-if-absent**（§2.4.3 的真实缺口）。先写失败测试：库中已存在被管理员改过内容的同 `source_path` 文档时，再次导入**不得覆盖**。强制覆盖由默认关闭的 `--overwrite` 开关承担，且该开关必须在文档中写明会丢失后台改动。
- [ ] **Step 3** 明确种子边界：**只含 `index/` 与 `业务/`，共 21 篇**，`memory/` 不进种子（与参考项目 `.dockerignore` 排除 `memory/merchants/` 的做法一致）。
- [ ] **Step 4** 处置 `memory/` 两篇死行（2026-08-24 实测发现）：本地 `knowledge_documents` 现有 `memory/README.md` 与 `memory/merchants/100-…/电商交易-….md`，二者 `category` 均为 `UNKNOWN`，**且树上永远不渲染**——`_memory_root()` 读的是 `merchant_memories` 表而非本表。它们是 `import_wiki` 盲目遍历整棵 Wiki 带进来的、跨层的死行，唯一实际作用是给 `UNKNOWN` 分类的知识检索添噪。本 Step 决定：种子不含它们，并在导入脚本中显式跳过 `memory/` 前缀；**是否清理本地已有的两行单独确认，不在本 Step 内擅自 DELETE**。
- [ ] **Step 5** 执行前记录线上 `knowledge_documents` 行数作为回滚基线。
- [ ] **Step 6** 执行导入。
- [ ] **Step 7** 复验三项，缺一不可：
  - 总数为 **21**（`index/README.md` 1 篇 + `业务/` 20 篇）；
  - **`category` 分布正确**：十个业务分类各 2 篇、`index/README.md` 为 `UNKNOWN`。**若出现全 `UNKNOWN`，说明走了管理员 API 路径，立即停止**（§2.4.5 障碍 3）；
  - `GET /api/admin/knowledge/tree` 中 `ddl` 与 `指标或调用指标平台mcp的skill` 两板块为**空目录**（§5.17 登记的预期状态，不是缺陷）。
- [ ] **Step 8** 重跑一次导入，确认幂等且**不产生任何 UPDATE**（验证 Step 2 的 insert-if-absent 生效）。
- [ ] **Step 9** 线上验证一道 RULE 类问题命中知识（**需费用授权，R3**）。
- [ ] **Step 10** 把「知识库导入」从 `docs/project-progress.md:31` 的 MVP 未完成项中划掉；把 §2.4.3 的缺口与其修复登记到 `docs/yshopping-parity-audit.md`（新增一条 🔴 真实缺口并标注已修复）。
- [ ] **Step 11** 【需用户授权】Commit。

---

## 9. Task 7 · 创建 Railway Cron Service 并首次滚动（**前置：Task 3、Task 5**）

> **本 Task 全部由用户在 Railway 控制台执行**，agent 只负责核对结果（§2.3）。

- [ ] **Step 1** 创建 Cron Service，Root Directory `/backend`，**Config File Path 显式填 `/backend/railway.cron.json`**（Railway 的 Config File Path 不跟随 Root Directory，不填则整份配置静默失效）。
- [ ] **Step 2** 只配四个变量：`DATABASE_URL`（引用同一 PostgreSQL）、`APP_ENV`、`ALLOW_DEMO_DATA_REFRESH=true`、`BUSINESS_TIMEZONE`。**不注入** `LLM_API_KEY` / `ADMIN_TOKEN` / `EXPORT_SIGNING_SECRET` / `FRONTEND_ORIGIN`。
- [ ] **Step 3** 确认同环境 Backend 已迁移到位并通过 `/api/ready`——**Cron 任务本身不跑迁移，缺表时必须失败退出而不是自动修库**。
- [ ] **Step 4** 手工触发首次执行，确认退出码 0，输出形如「演示数据滚动完成：补齐至 <业务今天>，已追加 N 行」。
- [ ] **Step 5** 若报「商家集合不匹配」，回到 Task 5 Step 3 核对商家集合，**不要放宽 `_require_demo_merchants()`**——那道护栏是防止误写非演示库的最后一道。
- [ ] **Step 6** 更新 `docs/deployment.md` 的 Cron 一节，把「Cron Service 尚未创建」改为已创建并记录首次执行结果。
- [ ] **Step 7** 【需用户授权】Commit。

---

## 10. Task 8 · 验证 180 天窗口并重算陈旧日报（**前置：Task 2、Task 7**）

- [ ] **Step 1** 查线上 `orders` 的 `min/max(business_date)`，确认末端已推进到业务今天、跨度约 180 天。
- [ ] **Step 2** `GET /api/reports/daily` 检查是否命中全零缓存（Cron 之前生成的那张）。
- [ ] **Step 3** 若命中，对每个演示商家调用 `POST /api/admin/reports/daily/recompute`，`reason` 写明「Cron 首次滚动前生成的空数据缓存」。
- [ ] **Step 4** 若返回 409（已有反馈），按 Task 1 契约的约定处置——**不得为了通过而绕过 409**，该冲突是有意设计。
- [ ] **Step 5** 复验六项指标非 0、`degraded=false`。
- [ ] **Step 6** 次日复查 Cron 是否按 `10 16 * * *`（UTC）自动执行，确认非首次执行也正常。
- [ ] **Step 7** 【需用户授权】Commit。

---

## 11. Task 9 · 补完线上验收缺口并更新快照（**前置：Task 6、Task 8**）

进度文档登记的三项线上验收至今未做，前两项零费用：

- [ ] **Step 1** **转发头伪造验收**（零费用）：经公网域名用同一演示 Token 连续发送超过 `RATE_LIMIT_PER_MINUTE` 的请求，每次更换 `X-Real-IP`，超限后必须仍返回 429；再以 `X-Forwarded-For` 重复一遍，记录 429 实际触发次序。**若任一伪造头能拿到新限流桶，立即把 Railway 改为 `TRUSTED_PROXY_HOPS=0` 并记录**（依据 `docs/deployment.md` §转发头信任策略）。
- [ ] **Step 2** SIGTERM 收尾验收与日志脱敏抽查（零费用）。
- [ ] **Step 3** 【**需单独费用授权，R3**】除 METRIC 外其余回答模式的真实模型验收：DETAIL / RULE / IDENTITY / 生成指标 / 跨业务查询。执行前必须说明模型、预计调用次数与费用并取得同意。**有了 Task 6 的知识库与 Task 7 的新鲜数据后，RULE 类才第一次具备通过条件。**
- [ ] **Step 4** 更新 `docs/project-progress.md`，逐项写明通过或未通过及证据，并划掉 MVP 未完成项中已达成的条目。
- [ ] **Step 5** 【需用户授权】Commit。

---

## 12. 验收标准

本计划视为完成，当且仅当：

1. 本地与线上都能打开页面看到**非 0 的日报指标**与**非空且 `category` 正确的知识库**；
2. `POST /api/admin/reports/daily/recompute` 已上线，§2.1 的每一条收紧条件都有对应测试；
3. `seed_demo_analytics` / `seed_demo_data` 在非本机数据库上**无论 `APP_ENV` 取何值都拒绝执行**；
4. Railway Cron Service 已创建并至少自动执行成功一次（非手工触发那次）；
5. `docs/deployment.md` 有可照着执行的「演示前数据检查清单」，并写明线上唯一经营数据写入口是 Cron；
6. 知识种子以 `app/knowledge/wiki_seed.json` 随镜像分发，漂移检查已接入 CI；§2.4.3 的导入语义缺口已修复——**重跑导入不覆盖后台改动**，并已登记到 `docs/yshopping-parity-audit.md`；
7. `docs/project-progress.md:31` 的 MVP 未完成项中，「知识库导入」与「转发头伪造验收」已划掉。

---

## 13. 不在本计划范围

以下缺口在本轮对话中确认存在，但属**功能开发**而非环境收口，各需独立计划：

| 缺口 | 归类 | 上游文档 |
| --- | --- | --- |
| 附件上传 + OCR 解析（`ChatComposer.vue` 现有孤立桩代码，无父组件监听） | A 类还原 | `plans/2026-08-22-parity-and-resume-roadmap.md` §7 |
| 无效意图不落记录表 + 引导提工单（须先解 `client_request_id` 幂等冲突） | A 类还原 | 同上 §5 |
| 语义层 Agent 校验闭环（读 Session + 历史记忆再分析） | B 类自研 | 同上 §8 |
| 新词语义层补齐 | B 类自研 | 同上 §8 |
| 简单问题绕过大模型省 Token | B 类自研 | 同上 §2 |
| 日报**定时推送**（端点已有，调度未做；与本计划的重算端点是两件事） | A 类还原 | 同上 §6 |

**不要在本计划的任何 Task 里顺手实现上述任何一项。** 若执行中发现某项是演示环境可用的硬前置，停下来回到 §2 追加裁定问题，而不是扩大本计划范围。
