# Railway 部署与运维手册

本手册只描述部署操作；不会在本地或 Railway 自动写入真实密钥。

## 服务与构建

在同一个 Railway 项目中创建 PostgreSQL 和 Backend 两个 Service。Backend 的 Root Directory 为 `/backend`，使用其中的 `railway.json` 与 Dockerfile。将 Backend 的 `DATABASE_URL` 引用 PostgreSQL Service，例如 `${{Postgres.DATABASE_URL}}`。发布前的 `python -m alembic upgrade head` 由 `railway.json` 的 `deploy.preDeployCommand` 执行一次，健康检查为 `/api/health`。

字段名必须是 `preDeployCommand`：Railway 的配置 schema 里**没有** `releaseCommand`，写成后者不会报错，只会被静默忽略，导致迁移从不执行、线上库始终缺表。

## 前端服务

在同一个 Railway 项目中创建 Frontend Service，并由用户在 Railway 控制台将其 Service Root 设为 `/frontend`。前端使用 Dockerfile 构建，镜像采用 Node 多阶段构建，最终运行镜像为 `caddy:2-alpine`；健康检查路径为 `/health.html`。

Caddy 不代理 `/api`。因此前端域名下不存在任何 API 路径，这是刻意的架构设计；浏览器应使用构建期注入的后端公网地址直接请求 API。

## Railway 配置文件路径

Railway 的 Config File Path 不跟随 Root Directory。即使 Service Root 已设为 `/frontend`，仍必须由用户在前端服务设置中显式填入 `/frontend/railway.json`；后端服务同理显式填入 `/backend/railway.json`。

不得省略此设置：否则两份 `railway.json` 都不会生效，前端健康检查以及后端的 `preDeployCommand`（`alembic upgrade head`）都会静默失效。

## 前端环境变量

以下变量由用户在 Railway 前端服务中配置：

| 变量 | 必填 | 说明 |
| --- | --- | --- |
| `VITE_API_BASE_URL` | 是 | 后端公网地址，在**构建期**注入静态产物。修改后必须重新构建并部署前端；只改变量但不重新部署不会生效。 |
| `VITE_USE_MOCK` | 否 | 生产环境必须不设或设为 `false`。设为 `true` 会使镜像构建直接失败；Dockerfile 已声明对应的构建参数。 |
| `VITE_VIEWER_TOKEN` | 否 | 只读令牌，取值必须与后端服务的 `VIEWER_TOKEN` 一致。配置后知识库后台与 Chat BI 看板的令牌入口会出现「使用只读令牌浏览」勾选项，访客免手输即可只读浏览；留空则不显示该入口。同样在构建期注入，改后必须重新构建。 |

`VITE_` 前缀变量会内联进公开的静态产物，绝不能用来配置任何密钥、Token 或连接串。`VITE_VIEWER_TOKEN` 是 AGENTS.md R6 明确列出的例外：它只能打开 `/api/admin/*` 的只读 GET 子集，泄露的最坏后果是「看到本来就打算公开的只读内容」。

**这三个变量都必须在 `frontend/Dockerfile` 里有对应的 `ARG` 声明。** Railway 会把服务变量作为 build-arg 传给 Dockerfile 构建，但未声明的 build-arg 会被静默丢弃——只在平台上配置而 Dockerfile 漏声明，表现是「变量明明配了却完全不生效」，且没有任何报错。新增 `VITE_` 变量时务必同步改 Dockerfile。

## 演示部署模式

`DEMO_DEPLOYMENT_MODE=true` 是仅用于对外演示部署的显式开关。开启后，生产环境的 `/api/demo/merchants` 可访问，前端才能取得并选择演示商家身份；不开启时该端点关闭，前端无法选择商家。

可通过携带 `X-Admin-Token` 的 `/api/admin/ops/status` 查看当前演示部署模式。演示 Token 只授予演示数据访问权；商家数据隔离仍由后端强制注入 `merchant_id` 保证。

## 上线顺序

前端 API 地址在构建期固化，而后端 CORS 又必须获知前端 Origin；同时后端首次启动前已要求提供 `FRONTEND_ORIGIN`。因此，用户需在 Railway 控制台按以下顺序完成双侧部署：

1. 在首次部署后端前，为 `FRONTEND_ORIGIN` 填入一个精确、临时且非敏感的 Origin，或填入已预先绑定的前端域名。该值必须含协议，不含路径和尾斜杠，且不得为 `*`。
2. 部署后端。
3. 获取后端公网域名。
4. 以该域名作为 `VITE_API_BASE_URL` 构建并部署前端。
5. 获取前端实际公网域名。
6. 将后端 `FRONTEND_ORIGIN` 替换为此前端实际的精确 Origin（含协议、不含路径和尾斜杠）。
7. 重新部署后端，使精确 CORS 配置生效。

这不是可互换的顺序：首次后端启动需要一个有效的精确 Origin，前端又需要已部署后端的公网地址；待前端实际域名确定后，必须替换临时 Origin 并再次部署后端。

## 必填环境变量

| 变量 | 用途与约束 |
| --- | --- |
| `APP_ENV=production` | 生产环境默认自动关闭演示商家端点；仅当显式设置 `DEMO_DEPLOYMENT_MODE=true` 时例外。 |
| `DATABASE_URL` | 引用 Railway PostgreSQL，不手填连接串。 |
| `FRONTEND_ORIGIN` | 精确 Origin；不得为 `*` 或含路径、查询、凭据。 |
| `DEMO_DEPLOYMENT_MODE=true` | 对外演示时必填；显式允许生产环境访问 `/api/demo/merchants`。非演示生产部署不设置或设为 `false`，端点保持关闭。 |
| `LLM_API_KEY` | DeepSeek 密钥；配置时必须同时配置 `ADMIN_TOKEN`。 |
| `ADMIN_TOKEN` | 运维端点凭据，生产环境至少 16 字符且非占位值。 |
| `EXPORT_SIGNING_SECRET` | CSV 导出签名密钥，生产环境必填且非占位值。 |
| `TRUSTED_PROXY_HOPS=1` | Railway 单层代理。 |
| `TRUSTED_PROXY_IPS` | **留空，不填任何值。** Railway 不发布稳定的边界代理地址；配置具体值会在重新部署后静默失效并导致限流退化，因此本项目明确不配置该变量。 |
| `RATE_LIMIT_PER_MINUTE` | 单 Token 与可信 IP 的每分钟上限。 |
| `LLM_DAILY_BUDGET_TOKENS` | **全局**每日模型 token 预算——`llm_daily_budget` 表只按 `usage_date` 聚合，不分商家、不分访客，公开演示时所有人共用这一个池子，它是唯一的总量闸门。默认 `500000` = 单请求上限 `25000` × 20，最坏情况也保证 20 个完整问题；按真实模型实测（每问约 6000 token）实际约 80 个。耗尽后所有人收到 `LLM_BUDGET_EXCEEDED` 的可见降级，不会静默继续扣费。 |
| `LLM_MAX_OUTPUT_TOKENS_PER_CALL` | 默认 `8000`（字段允许的上限）。**推理模型不得低于此值**：`deepseek-v4-flash` 单次结构化意图的 `reasoning_tokens` 就要 1400–2200，设为 1024 时正文返回空串，三次重试全废、回落 CHAT 模式；2026-08-22 真实模型验收又发现环比/同比这类需要更多推理步骤的回答生成在 `4096` 下同样会把预算耗尽在推理上、正文吐空，因此把默认值提到上限。这是上限不是花费。 |
| `MAX_LLM_TOKENS_PER_REQUEST` | 默认 `25000`，覆盖一轮问答最坏 10 次模型请求。 |
| `MAX_LLM_CALLS_PER_REQUEST` | 默认 `10`。最坏调用路径为 classify 2（业务关键词收到 `INVALID/UNKNOWN` 时重试 1 次）+ understand 3（意图服务自带 2 次重试）+ 指标口径 1 + （回答生成 + 独立复核）× 2 = 10 次，四个调用点共用同一个单请求预算。设低于 10 会让意图重试把质量循环挤成「预算耗尽」降级，把排查方向带偏。 |
| `QUALITY_MAX_ATTEMPTS` | 回答质量循环的最大轮次，代码支持 1–3，默认 `2`。与 `MAX_LLM_CALLS_PER_REQUEST` 联动：每加一轮最多多 2 次模型请求；若设为 `3`，完整最坏路径为 12 次，必须同步提高调用上限。 |
| `LLM_TIMEOUT_SECONDS` | 默认 `90`。推理模型出一次意图耗时明显；超时会被 `DeepSeekLlmClient` 吞成 fallback + degraded，表现为「模型没理解」而不是「超时」，很难查。 |

现有代码已强制精确 CORS、生产 JSON 日志、`create_app()` 不启用 Debug，以及数据库连接重试。B8 附件功能尚未实现，不得把正式附件写入容器临时磁盘。

### Railway 转发头信任策略与回退条件

本项目在 Railway 生产环境使用 `TRUSTED_PROXY_HOPS=1`、留空 `TRUSTED_PROXY_IPS`。留空时，`resolve_client_ip()` 中的 `trusted_proxy_ips and ...` 短路，跳过对直连 peer 的可信判定，即信任任何 peer 送来的转发头。

采用此策略的原因是 Railway 不发布稳定的边界代理地址；静态白名单会在重新部署后静默过期，函数随后返回 peer，令限流无声退化。该策略成立的前提是 Railway 容器没有公网直连入口，公网流量只能经 Railway 边界代理进入。

因此上线后必须完成「转发头伪造验收」：经 Railway 公网域名，使用同一演示 Token，连续发送超过 `RATE_LIMIT_PER_MINUTE` 的请求，并在每次请求中更换 `X-Real-IP`；超限后仍必须返回 429。再以 `X-Forwarded-For` 重复同一测试。记录 429 的实际触发次序。该验收不需要 LLM Key，费用为零。

若任一伪造头能够获得新限流桶（超限后未返回 429），立即将 Railway 配置改为 `TRUSTED_PROXY_HOPS=0`，接受限流收敛为按 Token 的已知可用性限制，并在 `docs/project-progress.md` 记录；后续在 F6 之后改用「按 XFF 最右跳解析」或引入 Redis 限流解决。在得到该实测证据前，不得宣告线上部署验收通过。

## 演示数据的每日滚动

线上演示库的经营数据唯一写入口是 Cron；全量 Seed 仅用于本机恢复，代码会拒绝任何非本机数据库地址：

| 入口 | 用途 | 触发方式 |
| --- | --- | --- |
| `python -m app.jobs.seed_demo_rolling` | 唯一常态入口：补齐所有漏跑业务日、清理 180 天窗口外事实，历史分区一行不改写。 | 独立 Cron Service，每日 `10 16 * * *`（UTC，等于 Asia/Shanghai 00:10） |
| `backend/scripts/seed_demo_analytics.py --force-full-rebuild` | 一次性整体重置：先 DELETE 六张经营表该商家全部行再重写。 | 仅本机或本地 Compose；线上禁止执行 |

全量重灌会连同已落库 `answers` 引用的数据依据一起抹掉，因此它已改为必须显式传 `--force-full-rebuild`，缺参数时直接非零退出；它还会按 `DATABASE_URL` 主机白名单拒绝非本机地址，`APP_ENV` 的生产环境拒绝规则仍作为第二道护栏保留。

滚动任务的护栏（任一不满足即在写入前失败）：

- `ALLOW_DEMO_DATA_REFRESH=true` 必须显式设置。它是**非密钥但高风险的写权限**，默认 false，绝不下发给前端或写进构建产物；
- 数据库里的商家 UUID 集合必须与三个固定演示商家**精确相等**，多一个少一个都拒绝。真实商家数据库永远不得配置该 Cron Service；
- 校验、追加与窗口清理在同一事务内完成，入口先取 `pg_advisory_xact_lock`，两个实例同时触发时第二个等待而不是交叉写入；
- 只读取 `DATABASE_URL`、`APP_ENV`、`ALLOW_DEMO_DATA_REFRESH`、`BUSINESS_TIMEZONE` 四个变量（`app/core/seed_config.py` 的 `SeedSettings`），**不注入** `LLM_API_KEY`、`ADMIN_TOKEN`、`EXPORT_SIGNING_SECRET`、`FRONTEND_ORIGIN`；
- 随机基线为 `DEMO_ANALYTICS_SEED_BASE = 20260804`，第 i 个演示商家用 `BASE + i`，与全量重灌脚本共用同一常量。

任务本身不跑 Alembic 迁移：启用前先确认同环境 Backend 已迁移到位并通过 `/api/ready`，缺表时任务必须失败退出而不是自动修库。Railway Cron 按 UTC 调度、不保证精确到秒，上一次未结束时可能跳过本次，因此漏跑追赶是正确性要求而非容错优化。

已新增 `backend/railway.cron.json`（无 `healthcheckPath`、无 `preDeployCommand`、`restartPolicyType: NEVER`），不复用 `backend/railway.json`。**Cron Service 尚未创建。** 创建 Service、配置上述四个变量与手工触发首次执行均为 Railway 控制台操作；完成后必须按本节的验收项核对。

## Chat BI 汇总的每日滚动

`/ops-dashboard` 读的是汇总表 `chatbi_qa_daily`，**不是实时查询 `answers`**。新回答落库后不会自动出现在看板上，必须先跑一次 rollup。触发方式：

| 入口 | 覆盖范围 | 触发方式 |
| --- | --- | --- |
| `python -m app.jobs.chatbi_rollup` | 默认最近 7 天（业务时区）；可用 `--start-date` / `--end-date` 指定任意区间 | 独立 Cron Service，每日 `30 16 * * *`（UTC，等于 Asia/Shanghai 00:30） |
| 看板上的「重刷」按钮 | **仅当前选中的窗口**（7 / 30 / 90 天） | 管理员手动，需 `X-Admin-Token` |

**为什么是 7 天滑动窗口而不是只算昨天**：采纳、点赞、点踩可能在回答产生几天后才发生，只补昨天会让既往日期的采纳率和用户侧准确率永久偏低。每天重刷最近 7 天，迟到的反馈会被带进对应的 `stat_date`。汇总表只存可加计数、不存比率（比率在应用层由 `compute_north_star` 现算），因此重刷是幂等的，口径调整后也能安全重算历史。

**排障提示**：看板显示「样本不足」时，先确认所选窗口内**确实有源数据**——`rollup_range` 只扫 `answers.processing_status = 'SUCCEEDED'` 且落在窗口内的行。窗口内无回答时，重刷写入 0 行，读回来仍然是空，再点多少次都一样；此时应切换到更长的窗口（30 / 90 天）再重刷。

任务护栏与最小权限：

- 只读取 `DATABASE_URL`、`APP_ENV`、`BUSINESS_TIMEZONE` 及三个数据库连接参数（`app/core/job_config.py` 的 `JobSettings`，共 6 个字段）。**不注入** `LLM_API_KEY`、`ADMIN_TOKEN`、`EXPORT_SIGNING_SECRET`、`FRONTEND_ORIGIN`——与滚动 Seed 同一原则；
- 该任务**只读 `answers` / `feedback`、只写 `chatbi_qa_daily`**，不触碰经营数据，因此不需要 `ALLOW_DEMO_DATA_REFRESH`，真实商家数据库也可安全配置；
- 与滚动 Seed 一样不跑 Alembic 迁移：启用前先确认同环境 Backend 已迁移到位并通过 `/api/ready`；
- 排在滚动 Seed（`10 16`）之后 20 分钟，避免两个任务同时抢连接。

已新增 `backend/railway.chatbi-cron.json`（无 `healthcheckPath`、无 `preDeployCommand`、`restartPolicyType: NEVER`），不复用 `backend/railway.json`。**Cron Service 尚未创建**——创建 Service、配置变量与手工触发首次执行均为 Railway 控制台操作，步骤如下：

1. Railway 项目内 **New → GitHub Repo**，选同一仓库，Root Directory 设为 `/backend`；
2. Service **Settings → Config as code** 填 `railway.chatbi-cron.json`（不填会默认读 `railway.json`，那份带健康检查，Cron 会被判失败）；
3. **Variables** 只加 `DATABASE_URL`（建议用 Railway 的引用变量指向同一个 Postgres）、`APP_ENV=production`、`BUSINESS_TIMEZONE=Asia/Shanghai`，其余一个都不要加；
4. 首次部署后在 **Deployments** 手工触发一次，确认退出码为 0；
5. 验收：打开 `/ops-dashboard`，选「最近 7 天」，六张卡应能出数（分母不足的仍显示「样本不足」，属正确行为）。

## 演示前数据检查清单

以下命令仅用于本地演示库。执行前必须确认 `DATABASE_URL` 指向本地测试库，并确认不会与滚动 Seed Cron 并发执行。完整 `pytest` 会清空经营数据和知识库数据；如需演示，应在全量测试后重新恢复。

1. 确认 PostgreSQL 容器已启动且为 healthy：

   ```powershell
   docker ps
   ```

2. 确认迁移已到唯一的最新 head：

   ```powershell
   cd backend
   uv run alembic heads
   uv run alembic current
   ```

3. 先恢复三家演示商家。完整 `pytest` 会清空 `merchants`，经营数据表的外键要求此步先于全量经营 Seed：

   ```powershell
   uv run python ../scripts/seed_demo_data.py --seed
   ```

4. 恢复 180 天的本地经营演示数据。该命令会删除并重写三家演示商家的经营历史，所以必须显式确认参数：

   ```powershell
   uv run python -m scripts.seed_demo_analytics --force-full-rebuild
   ```

5. 恢复镜像知识种子（共 21 篇，且不会覆盖后台已维护的同路径文档）：

   ```powershell
   uv run python -m scripts.import_wiki --root "../yshopping-merchant-ai 4/yshopping-merchant-ai/runtime/llm-wiki"
   ```

6. 校验数据量和日期窗口：`orders` 应为数千行，`business_date` 应连续覆盖 180 天并截止于当前业务日；`knowledge_documents` 应为 21 篇种子文档（`index/README.md` 一篇、十个业务分类各两篇）。如确需本机强制覆盖同路径的后台维护内容，才传入 `--overwrite`；该开关会丢失这些后台改动，线上不得使用。

## 运维验收

- 确认 `/api/health` 持续正常，重启 Backend 后数据仍在 PostgreSQL 中。
- 非演示生产部署中，确认 `/api/demo/merchants` 不可用；对外演示部署中（`DEMO_DEPLOYMENT_MODE=true`），确认该端点可用且只返回服务端配置的演示商家。
- 超额频率返回 `RATE_LIMITED`；达到模型日预算后显示明确降级。
- `GET /api/admin/ops/status` 仅接受 `X-Admin-Token`，不得返回 Token、Prompt、商家数据或连接串。
- 本地或预发做一次 SIGTERM 验收：发起长 SSE 请求后执行 `docker stop <container-id>`，确认连接以 `done` 或 `error` 收尾，容器在 `backend/app/run.py::GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS`（30 秒）内退出。

## 双语本地化（Bilingual Localization）

### 本地化限制环境变量

以下四个变量控制批量翻译通道 `LocalizationService.localize_many()` 的费用上限，与主 Agent 问答的 `MAX_LLM_CALLS_PER_REQUEST`/`MAX_LLM_TOKENS_PER_REQUEST` 完全独立（互不挤占预算，`llm_usage.purpose` 用 `AGENT`/`LOCALIZATION` 分别记账）。定义见 `backend/app/core/config.py`：

| 变量 | 默认值 | 用途与约束 |
| --- | --- | --- |
| `LOCALIZATION_MAX_CALLS_PER_REQUEST` | `4` | 单次 HTTP 请求内允许的本地化 LLM 调用次数上限（1–20）。会话列表/详情按页翻译、聊天回答翻译等所有本地化调用点共用同一预算。 |
| `LOCALIZATION_MAX_TOKENS_PER_REQUEST` | `12000` | 单次 HTTP 请求内本地化调用允许消耗的 token 总量上限（100–200000）。 |
| `LOCALIZATION_MAX_BATCH_ITEMS` | `20` | 单次批量翻译调用最多打包的待译条目数（1–200）；超出的条目留给下一批调用，仍受上面的调用次数上限约束。 |
| `LOCALIZATION_MAX_BATCH_CHARS` | `12000` | 单次批量翻译调用里所有条目文本长度之和的上限（100–200000）；单条本身超过此值永远凑不成一批，直接缺席（不抛异常，按条目降级）。 |

超出任一预算的条目按 R7 降级为目标语言占位文案，**不回落源语言**；调用方据此把 `localization_degraded`/`localization_degraded_reason` 置入响应，前端对同一游标/分页参数重新请求即为重试，已成功条目命中机器缓存不会重复计费。

### 英语 Smoke Test（零/低成本）

部署后验证英语路径可用，优先走零 LLM 调用的路径，不需要真实模型费用：

1. `GET /api/demo/merchants`（无需 Token）确认端点存活；
2. 携带任一演示商家 Token、`Accept-Language: en-US` 调用 `POST /api/chat`，问题选一句英文问候语（如 `"hello"`）或英文范围外提问——两者都经零 LLM 前置闸门/CHAT 分支处理，验证响应 `quality_notes`/`degraded_reason`/错误 `message` 均渲染为英文，且不产生任何 `llm_usage` 记录；
3. 携带同一 Token、`Accept-Language: en-US` 调用 `GET /api/conversations`，确认历史列表按英语渲染且已有中文历史正确回填 `source_locale`；
4. 用 `X-Admin-Token` 调用一次 `GET /api/admin/knowledge/tree`，确认业务域名称按英语渲染（走确定性词典 `catalog.py`，零 LLM）；
5. 若需要验证真正需要模型翻译的路径（跨语言知识召回、自由文本批量翻译等），必须先按 AGENTS.md R3 向用户说明会调用的接口、预计调用次数、模型（`deepseek-v4-flash`）与费用，取得明确同意后才执行——不属于本 Smoke Test 默认范围。

### 数据库迁移与缓存说明

本效果新增两个迁移，链接在既有单一 head 之后：

- `20260831_0015_localization_tables.py`：创建 `machine_translation_cache`（机器译文缓存）与 `resource_localizations`（资源级人工译文）两张表；均按 `scope_kind`（`MERCHANT`/`GLOBAL`）+ `merchant_id` 的 CHECK 约束与按作用域拆分的表达式唯一索引强制隔离，避免 PostgreSQL 唯一索引中 `NULL` 互不相等导致 `GLOBAL` 行无限重复插入。
- `20260831_0016_content_locale_metadata.py`：给 `messages`/`answers`/`knowledge_documents`/`merchant_memories` 各加一个内容语言分类列（历史行按迁移内冻结的确定性分类函数逐行回填，禁止用数据库默认值把历史内容一律标成 `zh-CN`），给 `merchants` 加人工维护列 `display_name_en`，给 `llm_usage` 加调用用途列 `purpose`（历史行按 `server_default` 回填为 `AGENT`）。

迁移仍由 `railway.json` 的 `deploy.preDeployCommand`（`alembic upgrade head`）在发布阶段执行一次；两个新迁移都已验证支持 `alembic upgrade --sql`（离线 SQL 渲染），不依赖真实数据库连接即可静态核对。

### 30 天过期清理

`machine_translation_cache` 的每一行写入/覆盖时都把 `expires_at` 设为 `now() + interval '30 days'`（`LocalizationRepository.upsert_machine()`）。**读路径（`get_merchant_machine_many()`/`get_global_machine_many()`）当前不按 `expires_at` 过滤**——过期只影响是否被批量清理，不影响该行在被清理前继续被当作有效缓存命中；由于缓存键包含内容哈希，源文本一旦变化会产生新哈希、自然不会命中旧行，因此这不是正确性问题，只是存储卫生问题。

批量清理由 `LocalizationRepository.purge_expired_machine()` 提供，并有专门的集成测试覆盖（`backend/tests/integration/repositories/test_localization_repository.py`）。**该方法目前没有被任何 Cron Service 或定时任务调用**——不同于 `seed_demo_rolling`/`chatbi_rollup` 已经各自配好独立 Cron，本效果尚未新增第三个 Cron Service 来定期执行它。上线前需要用户决定：

- 在现有某个 Cron（如每日的 `chatbi_rollup`）收尾处追加一次调用，或
- 新建第三个最小权限 Cron Service（只需 `DATABASE_URL`/`APP_ENV`），仿照 `backend/railway.chatbi-cron.json` 的模式，或
- 暂不清理，接受缓存表随时间增长，后续按需再补。

在决定并配置前，`machine_translation_cache` 会持续增长但不会造成翻译结果错误。

### 回滚指引

- **只回滚代码、不回滚迁移**：本效果的两个迁移是纯增量（新表 + 新增列），不修改任何既有列的语义或删除任何数据；只回退应用代码到迁移前版本即可安全共存于已迁移的数据库——旧代码不知道新列/新表存在，会继续按原有行为工作。
- **确需回滚迁移**（例如新表结构本身有缺陷）：`alembic downgrade 20260823_0014` 会依次撤销 `20260831_0016`（先删除五个新增列，`display_name_en`/`purpose` 之外的四个分类列因为已回填真实历史数据，降级会永久丢弃这些回填结果）和 `20260831_0015`（删除两张新表，连同其中已经产生的机器译文缓存和人工译文一起丢弃）。降级前必须确认没有依赖这些列/表的代码仍在运行。
- **只想临时关闭翻译功能、不动数据库**：把四个 `LOCALIZATION_MAX_*` 中的 `LOCALIZATION_MAX_CALLS_PER_REQUEST` 设为最小值（`1`）不能完全禁用，因为它仍允许 1 次调用；真正的开关是上游是否发起翻译请求（前端语言切换与 `Accept-Language`），本效果没有提供单独的 `LOCALIZATION_ENABLED` 总开关。如需紧急止损，可临时不配置 `LLM_API_KEY`（主 Agent 与本地化共用同一把 DeepSeek Key），两条调用路径会一起进入现有的 LLM 不可用降级分支，而不是只关翻译。

## 单 worker 与多实例限制

容器保持单 worker。限流器、运行时可观测性计数与预算估算协调均为进程内状态；多 worker 会使限流与指标失真。`LlmBudgetRepository.reserve` 的数据库条件更新仍可防止预算超发，但多个 Backend 副本只会产生近似的限流与运维计数。需要多副本前，应先引入共享状态存储。
