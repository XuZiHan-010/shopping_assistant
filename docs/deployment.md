# Railway 部署与运维手册

本手册只描述部署操作；不会在本地或 Railway 自动写入真实密钥。

> **状态说明（2026-10-08）**：现网是 Railway 上的 `Frontend`（商家端）与 `Backend` 两个服务，主库是**外部
> Neon PostgreSQL**，跑的仍是 v1 时代的代码（见「只更新现有两个服务」一节的探测结果）。目标拓扑是 Railway 四服务
> （`shop`、`merchant`、`backend`、`cron`）+ 外部 Neon；其中 `shop` 与 `cron` **尚未创建**，`Frontend` 尚未改名为 `merchant`。
> 用户 2026-10-08 裁定先沿用现有两个服务更新，`shop` 与 `cron` 暂不创建。N5 的代码与配置已在仓库备好
> （统一 Cron 分发器、三级预算、MCP 只读入口、单入口演示）。
>
> **本手册写的是「怎么做」，不代表已经做了。** 每一项 Railway 控制台操作、对 Neon 的写操作、线上签发 MCP 凭证，
> 以及把真实 `LLM_API_KEY` 配到公网实例，都要逐项取得同意后才执行（`AGENTS.md` §三、R3）；
> 实际执行结果记在 `docs/project-progress.md` 与 `docs/history/deploy-preflight-<日期>.md`。

## 目标服务拓扑（N1–N5）

| Service | 位置 / Root Directory | 当前状态 |
| --- | --- | --- |
| `shop` | Railway `/shop` | Next.js 顾客端；镜像与配置已在仓库（`shop/Dockerfile`、`shop/railway.json`），**服务尚未创建** |
| `merchant` | Railway `/frontend` | Vue 商家端；现网服务名为 `Frontend`，**尚未改名**；N5 新增构建变量 `VITE_SHOP_BASE_URL` |
| `backend` | Railway `/backend` | FastAPI；发布阶段由 `preDeployCommand` 执行一次数据库迁移 |
| `cron` | Railway `/backend` | `backend/railway.cron.json`：每 5 分钟运行统一分发器；**服务尚未创建** |
| `postgres` | **外部 Neon**（不在 Railway 内） | 现网主库（数据库 `neondb`）；backend 与 cron 经 `DATABASE_URL` 连接 |

不建通用 Worker、Redis 或对象存储。Backend 公开，浏览器直连；`shop` 与 `merchant` 各用一个精确 Origin，
CORS 允许头至少包含 `Authorization`、`Accept`、`Content-Type`、`X-Request-Id`、`X-Session-Id`、`X-Admin-Token`。
后端通过 `FRONTEND_ORIGIN`（商家端）与 `SHOP_ORIGIN`（顾客端）接受两个精确 Origin，二者都禁止 `*`、路径、查询与凭据；
`SHOP_ORIGIN` 未配置时 CORS 只放行商家端。

**对外演示只公开商家端一个入口**（PRD §10.7，D-N5-4）：访问者从商家端侧栏的「顾客视角」在新标签页进入本店顾客端。
它只是链接，不传任何凭证；顾客端照常创建自己的访客会话。

## pgvector 与混合检索（N4-C，2026-10-02）

- **数据库**：生产库是外部 **Neon**（不是 Railway Postgres），`vector` 扩展可用（0.8.6，与本地一致）。
  迁移 `20261002_0047` 执行 `CREATE EXTENSION IF NOT EXISTS vector` 并建三张索引表；由 `backend/railway.json`
  的 `preDeployCommand`（`alembic upgrade head`）随部署自动执行。Neon 允许库所有者角色执行该语句，
  但线上尚未实际跑过这次迁移——首次部署时留意 preDeploy 日志里 `20261002_0047` 是否成功。
- **本地与 CI**：`docker-compose.yml` 与 `.github/workflows/n1-checks.yml` 使用 `pgvector/pgvector:pg16`
  （PostgreSQL 16，`vector` 0.8.6）。新镜像基于 Debian，与原 `postgres:16-alpine` 排序规则不同，本地改用新数据卷
  `borough_postgres_pgvector_data`，旧卷 `borough_postgres_data` 保留未删。
- **嵌入模型**：在 backend 进程内用 fastembed（ONNX Runtime，不依赖 PyTorch）推理，**不是 LLM 调用，无费用**。
  **选定模型 `BAAI/bge-small-zh-v1.5`**（2026-10-02 用户裁定，理由见 `docs/backend-development-plan.md` §6.14）。
  Railway Variables 设置 `EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5`：它同时是**构建参数**（`backend/Dockerfile` 在构建期把模型下载进镜像的
  `/app/models`）和运行时配置；运行时设 `HF_HUB_OFFLINE=1`，不访问外网。阈值 `EMBEDDING_MIN_SIMILARITY` 留空即取
  标定值；换成未标定的模型必须显式设置，否则启动失败。`EMBEDDING_MODEL` 为空时向量召回关闭，`search_rules`
  只用关键词，回答来源与知识后台都显示降级。
- **索引构建**：backend 启动后在后台预热模型，并在生效索引缺失、陈旧、换模型或语料变化时重建；知识后台每次保存
  也会触发重建。构建期间旧版本继续服务；失败时旧版本保留并标陈旧（知识后台可见）；多实例同时启动由数据库的
  单构建约束保证只建一次。手动重建：`python -m app.jobs.build_index`（定时重建归 N5 Cron）。
- **资源增量**（实测，见 `docs/backend-development-plan.md` §6.14 与 `docs/history/eval/rag-hybrid.md`）：
  fastembed 依赖使 Linux 镜像增加约 189 MB（未设模型时镜像 644 MB）。在 Linux 容器里单线程实测（backend 导入后基线 108 MB，
  与 Railway 空载约 100 MB 吻合）：

  | 模型 | 镜像模型层 | 预热后常驻 | 建索引峰值 | 建索引耗时（44 块） | 单次查询 |
  | --- | --- | --- | --- | --- | --- |
  | `google/embeddinggemma-300m` | +1.26 GB | +795 MB（进程约 0.9 GB） | +855 MB | 65 s | 约 63 ms |
  | `BAAI/bge-small-zh-v1.5` | +95 MB | +170 MB（进程约 0.28 GB） | +275 MB | 14 s | 约 11 ms |

  Railway 按内存用量计费；上线后观察 7 天内存峰值与服务卡片告警。本地 `docker-compose.yml` 已按选定模型配置。
- **回退**：把 `EMBEDDING_MODEL` 清空并重新部署即可回到纯关键词检索（降级可见）；索引表保留，不影响数据。

## 顾客端服务 `shop`（N2）

Root Directory 为 `/shop`，Config File Path 显式填 `/shop/railway.json`（Railway 的配置文件路径不跟随 Root Directory）。
镜像为 Node 多阶段构建（`shop/Dockerfile`，Next.js standalone 输出），监听 Railway 注入的 `PORT`，
健康检查路径 `/health`（不查库、不调后端、不调 LLM）。

- **构建变量**：`NEXT_PUBLIC_API_BASE_URL`（必填，Backend 公网地址）在构建期内联进浏览器产物；漏配时页面响亮失败，
  不回退同源 `/api`。可选 `NEXT_PUBLIC_DEFAULT_SHOP_SLUG` 只用于落地页的演示入口。
- **构建期不读仓库根**：构建上下文里没有 `docs/` 与 `frontend/`。OpenAPI 类型（`src/api/generated.ts`）、
  设计 token（`src/styles/tokens.css`）与 logo（`public/borough-logo.svg`）都是提交进仓库的副本，
  由 `npm run codegen:check`、`npm run tokens:check` 在本地与 CI 保证没有过期；这两个检查**不要**放进 Docker 构建。
- **Backend 侧**：`SHOP_ORIGIN` 填 `shop` 的精确 Origin（含协议，不含路径与尾斜杠，不得为 `*`）。
- 会话 ID 只存浏览器内存，不写 URL、`localStorage`、`sessionStorage` 或 cookie，也不进构建产物与日志。
- **`NEXT_PUBLIC_API_BASE_URL` 必须是浏览器与 shop 服务端都能访问的地址**：首页的店铺资料、热门商品与优惠券由服务端取数（SSR），
  用的是同一个构建期内联的地址。线上填 backend 的公网域名即可；填成只有浏览器能访问的地址时，页面会因服务端取数失败而报错。
- **构建期需要访问 Google Fonts**：字体经 `next/font/google` 在构建时下载并随产物自托管（运行时不再请求 Google）。
  Railway 构建机可直连；在访问受限的网络里构建会失败（`Failed to fetch … from Google Fonts`），需给构建传 `HTTP_PROXY` / `HTTPS_PROXY`。

## 后端服务 `backend`

Root Directory 为 `/backend`，使用其中的 `railway.json` 与 Dockerfile。`DATABASE_URL` 填 **Neon 连接串**
（直接写进 Railway Variables，不进仓库；`postgresql://` 前缀会在读取时规范化为 psycopg 方言）。

**迁移只在发布阶段执行一次**：`railway.json` 的 `deploy.preDeployCommand` 运行 `python -m alembic upgrade head`，
成功后新版本才上线；backend 与 cron 的进程启动时都不迁移（Dockerfile `CMD` 是 `python -m app.run`）。
迁移 `20261002_0047` 含 `CREATE EXTENSION IF NOT EXISTS vector`，需要 `DATABASE_URL` 里的 Neon 角色有建扩展的权限
（库所有者角色即可）。字段名必须是 `preDeployCommand`：Railway 的配置 schema 里**没有** `releaseCommand`，
写成后者不会报错，只会被静默忽略，导致迁移从不执行、线上库始终缺表。

健康检查为 `/api/health`（不查库、不调 LLM），等待窗口由 `deploy.healthcheckTimeout` 设为 **120 秒**，为冷启动预留时间；
这不是单次 API 请求超时。启动入口 `python -m app.run` 监听 `0.0.0.0` 并读取 Railway 注入的 `PORT`（本地缺省 `8000`）。
若检查失败，查看同一次部署带时间戳的运行日志，核对启动耗时、实际监听端口与 `/api/health` 的响应；延长窗口不能修复启动异常。

## 商家端服务 `merchant`

现网服务名为 `Frontend`，目标名为 `merchant`。Root Directory 为 `/frontend`，Node 多阶段构建，运行镜像为
`caddy:2-alpine`，健康检查路径 `/health.html`。

Caddy 不代理 `/api`：前端域名下不存在任何 API 路径，浏览器用构建期注入的后端公网地址直接请求 API。

**改名步骤**（控制台操作，执行前取得同意）：在服务的 Settings 里把名称改为 `merchant`。改名只改显示名与 Railway
内部域名；本项目不使用 Railway 内部网络，公网域名不应变化——改完后核对公网域名与 backend 的 `FRONTEND_ORIGIN`
仍然一致，再继续后面的步骤。

## Railway 配置文件路径

Railway 的 Config File Path 不跟随 Root Directory。即使 Service Root 已设为 `/frontend`，仍必须由用户在前端服务设置中显式填入 `/frontend/railway.json`；后端服务同理显式填入 `/backend/railway.json`。

不得省略此设置：否则两份 `railway.json` 都不会生效，前端健康检查以及后端的 `preDeployCommand`（`alembic upgrade head`）都会静默失效。

## 前端环境变量

以下变量由用户在 Railway 前端服务中配置：

| 变量 | 必填 | 说明 |
| --- | --- | --- |
| `VITE_API_BASE_URL` | 是 | 后端公网地址，在**构建期**注入静态产物。修改后必须重新构建并部署前端；只改变量但不重新部署不会生效。 |
| `VITE_USE_MOCK` | 否 | 生产环境必须不设或设为 `false`。设为 `true` 会使镜像构建直接失败；Dockerfile 已声明对应的构建参数。 |
| `VITE_VIEWER_TOKEN` | 否 | 只读令牌，取值必须与后端服务的 `VIEWER_TOKEN` 一致。配置后知识库后台与运维看板的令牌入口会出现**默认勾选**的「使用只读令牌浏览」，访客直接点「进入后台」即可只读浏览，取消勾选后可输入管理员令牌；留空则不显示该入口。只读令牌读不到 `ops/status`，也不会触发记忆机器翻译（只读已有译文缓存）。同样在构建期注入，改后必须重新构建。 |
| `VITE_SHOP_BASE_URL` | 否 | 顾客端（`shop` 服务）的公网地址，含协议、不带结尾斜杠。配置后侧栏出现「顾客视角」入口，在新标签页打开 `<地址>/<本店 shop_slug>`；留空、不是 http(s) 绝对地址或带查询参数时不显示入口。商品页的演示缩略图也从这个地址加载（`<地址>/demo/products/NN.webp`，文件在 `shop/public/demo/products/`，随 `shop` 镜像发布），留空时缩略图显示占位。它只是公开链接的前缀，不是凭证。构建期注入，改后必须重新构建。 |

`VITE_` 前缀变量会内联进公开的静态产物，绝不能用来配置任何密钥、Token 或连接串。`VITE_VIEWER_TOKEN` 是 AGENTS.md R6 明确列出的例外：它只能打开 `/api/admin/*` 的只读 GET 子集，泄露的最坏后果是「看到本来就打算公开的只读内容」。

**这些变量都必须在 `frontend/Dockerfile` 里有对应的 `ARG` 声明。** Railway 会把服务变量作为 build-arg 传给 Dockerfile 构建，但未声明的 build-arg 会被静默丢弃——只在平台上配置而 Dockerfile 漏声明，表现是「变量明明配了却完全不生效」，且没有任何报错。新增 `VITE_` 变量时务必同步改 Dockerfile。`frontend/src/build/dockerfile-args.spec.ts` 会核对 `env.d.ts` 里的每个 `VITE_*` 变量都有 `ARG` 与 `ENV`。

## 演示部署模式

`DEMO_DEPLOYMENT_MODE=true` 是仅用于对外演示部署的显式开关。开启后，生产环境的 `/api/demo/merchants` 可访问，前端才能取得并选择演示商家身份；不开启时该端点关闭，前端无法选择商家。

可通过携带 `X-Admin-Token` 的 `/api/admin/ops/status` 查看当前演示部署模式。演示 Token 只授予演示数据访问权；商家数据隔离仍由后端强制注入 `merchant_id` 保证。

## 上线顺序（四服务 + 外部 Neon）

顺序由两条依赖决定：前端的后端地址在**构建期**固化；后端 CORS 又必须知道前端的精确 Origin。
下面每一步都是生产变更，**逐项取得同意后执行**，结果记入 `docs/history/deploy-preflight-<日期>.md`。

1. **backend**：补齐 N4 / N5 新变量（`EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5`，三级预算上限可先用默认值），重新部署。
   发布阶段的 `preDeployCommand` 会把 Neon 迁移到最新 head——首次包含 `20261002_0047`（建 `vector` 扩展与索引表）到
   `20261004_0051`（MCP 凭证、三级预算、价格版本、Cron 状态表）。看 preDeploy 日志确认每条迁移成功，
   再核对 `/api/health` 与 `/api/ready`。迁移失败时新版本不会上线，按「迁移失败与回滚」处理。
2. **cron**：新建服务，按「cron 服务：统一分发器」一节配置，手工触发一次，确认输出的任务报告没有 `FAILED`。
3. **shop**：新建服务（Root `/shop`，Config File Path `/shop/railway.json`），构建变量 `NEXT_PUBLIC_API_BASE_URL` 填
   backend 公网地址，部署后记下 `shop` 的公网域名。此时 backend 还没有放行它的 Origin，页面里的 API 请求会被 CORS 拒绝，属预期。
4. **merchant**：把 `Frontend` 改名为 `merchant`，新增构建变量 `VITE_SHOP_BASE_URL`（上一步的 `shop` 域名），重新构建并部署。
5. **backend**：设置 `SHOP_ORIGIN` 为 `shop` 的精确 Origin（含协议，不含路径与尾斜杠，不得为 `*`），重新部署。
6. **验收**：从商家端进入，点侧栏「顾客视角」，新标签页打开本店顾客端并能正常对话（未配置 `LLM_API_KEY` 时是可见降级，
   不是报错）；再按「运维验收」与「公开部署前置条件验收」逐项核对。

全新环境（没有任何既有服务）时，backend 首次启动前就需要一个合法的 `FRONTEND_ORIGIN`：先填一个精确、临时且非敏感的
Origin 或预先绑定好的前端域名，等 `merchant` 的实际域名确定后替换并重新部署 backend。它必须含协议，不含路径和尾斜杠，且不得为 `*`。

## 只更新现有两个服务（`Frontend` + `Backend`，2026-10-08）

用户 2026-10-08 裁定：线上先沿用现有的 `Frontend` 与 `Backend` 两个服务，不新建 `shop` 与 `cron`。
本节是这条路径的最小步骤；四服务的完整拓扑仍按上一节。

**现网基线（2026-10-08 只读探测）**：现网 Backend 的 OpenAPI 只有 v1 的 20 条路径，`/api/v2/*` 全部 404，
与 GitHub 默认分支 `feature/f2-mock-conversation`（提交 `c286eca`，迁移 head `20260831_0016`）一致。
也就是说 `main` 上自 2026-09-27 起的 v2 代码**从未部署过**，Neon 仍在 `0016`。

**升级演练（本地，2026-10-08）**：用现网那版代码在 `pgvector/pgvector:pg16`（`vector` 0.8.6）上建库到 `0016`、灌 v1 演示数据并产生
对话行，再用新代码按 `APP_ENV=production` 执行发布迁移与分发器，脚本化地重复了两遍：

| 步骤 | 结果 |
| --- | --- |
| 不配 `BUYER_ALIAS_SECRET` 执行 `alembic upgrade head` | 配置校验失败、非零退出，库停在 `0016`——**新版本不会上线，旧版本继续服务** |
| 配上后执行 | 35 条迁移（`0017` → `0051`）4–7 秒完成，v1 的对话、回答、订单、知识文档行数不变 |
| 新 Backend 以生产配置启动 | `/api/health`、`/api/ready`、v1 与 v2 商家端点、运维状态全部 200；未配 Key 时对话是可见降级 |
| 分发器（不开演示数据写权限） | 全部 `OK` / `DISABLED`，退出码 0 |
| 分发器（`ALLOW_DEMO_DATA_REFRESH=true`） | 72 件商品换成现行标题与图片地址，**补上初始库存**并各记一条 `INITIAL_STOCK` 事件，订单补到当前业务日 |

演练限制：本地库不是 Neon（没有连接池代理、网络延迟与套餐限额），演示数据是按现网版本重新生成的，不是 Neon 的真实行。

**更新步骤**（每一步都是生产变更，由用户执行）：

1. **先在 `Backend` 服务加一个变量 `BUYER_ALIAS_SECRET`**：稳定的高熵随机串（例如 `openssl rand -hex 32`），不得是占位值。
   这是新版本唯一新增的必填项；漏配时发布迁移在读配置阶段就失败，现网不受影响，但也不会更新。
2. 顺手核对 `Backend` 的几个旧值（默认值变了不会覆盖已设置的变量）：`LLM_MODEL` 若还是 `deepseek-v4-flash` 或 `deepseek-chat`
   须改为 `deepseek-flash`；`MAX_LLM_TOKENS_PER_REQUEST` 若显式设成了 `25000` 须删掉或改为 `120000`，否则多步回合在第三次模型调用被拒；
   `LLM_DAILY_BUDGET_TOKENS` 若显式设成了 `500000` 须删掉，让三级预算取新默认值。
3. 让 Railway 两个服务跟踪的分支拿到 `main` 的提交（合并 `main` 到该分支，或把两个服务改为跟踪 `main`），触发重新部署。
   看 `Backend` 的 preDeploy 日志：35 条迁移逐条成功，其中 `20261002_0047` 建 `vector` 扩展。
4. 核对 `/api/health`、`/api/ready`，打开商家端确认能进入工作台。

**这条路径上不工作的部分**：

| 能力 | 现象 | 补上的办法 |
| --- | --- | --- |
| 顾客端 | 没有 `shop` 服务；`VITE_SHOP_BASE_URL` 未配置时侧栏不显示「顾客视角」，商品缩略图显示占位 | 建 `shop` 服务（上一节步骤 3–5） |
| 演示数据刷新 | 没有 `cron` 服务就没有任何进程执行滚动任务：商品仍是「演示商品 NN」、库存为 0、经营数据停在上次灌数那天 | 见下 |
| 其余定时任务 | 超时订单关闭、草稿过期、记忆抽取、Chat BI 汇总不自动执行；业务读写路径仍按截止时间判定，结果不变，只是不清理 | 建 `cron` 服务 |
| 混合检索 | 未设 `EMBEDDING_MODEL` 时规则检索按关键词运行，来源标注降级 | 设 `EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5` 并重新部署 |

**刷新演示数据**：`ALLOW_DEMO_DATA_REFRESH` 按 `AGENTS.md` R6 只给独立的 Cron 进程，**不要**配到 `Backend` 这个 Web 服务上。
不建 `cron` 服务时，在一份仓库检出里手工跑一次分发器（对 Neon 的写操作，执行前确认连的是演示库）：

```powershell
cd backend
$env:APP_ENV = "production"
$env:BUSINESS_TIMEZONE = "Asia/Shanghai"
$env:ALLOW_DEMO_DATA_REFRESH = "true"
$env:LLM_API_KEY = ""          # 必须显式置空：本机 .env 里若有 Key，记忆抽取任务会被启用并真实调用模型（R3）
$env:DATABASE_URL = "<Neon 连接串，只放在当前终端里>"
uv run python -m app.jobs.run_scheduled
```

输出的一行 JSON 里 `seed_demo_rolling` 应为 `OK`、`drain_memory_outbox` 应为 `DISABLED`。它会补齐所有漏跑的业务日，之后每隔几天再跑一次即可保持「最近 7 天」有数据；
建了 `cron` 服务后这一步就不需要了。

## 必填环境变量

| 变量 | 用途与约束 |
| --- | --- |
| `APP_ENV=production` | 生产环境默认自动关闭演示商家端点；仅当显式设置 `DEMO_DEPLOYMENT_MODE=true` 时例外。 |
| `DATABASE_URL` | 外部 Neon 的连接串，只写进 Railway Variables。backend 与 cron 用同一个库。 |
| `FRONTEND_ORIGIN` | 商家端（`merchant`）的精确 Origin；不得为 `*` 或含路径、查询、凭据。 |
| `SHOP_ORIGIN` | 顾客端（`shop`）的精确 Origin，约束同上。上线 `shop` 后必填，否则顾客端的请求被 CORS 拒绝。 |
| `DEMO_DEPLOYMENT_MODE=true` | 对外演示时必填；显式允许生产环境访问 `/api/demo/merchants`。非演示生产部署不设置或设为 `false`，端点保持关闭。 |
| `SESSION_TTL_SECONDS` | 会话凭证的有效期，默认 `86400` 秒；允许范围 `300`–`2592000`。 |
| `BUYER_ALIAS_SECRET` | 生产环境必填的稳定高熵密钥，用于派生店铺范围内的顾客脱敏别名；不得使用占位值，轮换会改变既有别名。 |
| `DEMO_CUSTOMER_IDENTITIES` | 仅后端读取的 JSON 映射（`shop_slug` → 演示 `buyer_key`）；不得发送到浏览器、日志或 API 响应。 |
| `LLM_API_KEY` | DeepSeek 密钥；配置时必须同时配置 `ADMIN_TOKEN`。 |
| `LLM_BASE_URL` | 固定为 `https://api.deepseek.com`。Anthropic 协议适配器使用 `https://api.deepseek.com/anthropic`。 |
| `LLM_MODEL` | 新配置默认 `deepseek-flash`；不得再使用已退役的 `deepseek-v4-flash` 或 `deepseek-chat`。**既有部署里若仍是旧值，须手动改**——默认值变化不会覆盖已设置的环境变量。 |
| `LLM_PROTOCOL` | `openai`（默认）或 `anthropic`，只决定 v2 `converse()` 走哪种 DeepSeek 协议；v1 `complete()` 固定走 OpenAI 兼容协议。改默认值须以双协议真实冒烟为据（后端计划 §6.17）。 |
| `LLM_THINKING` | `disabled`（默认）或 `enabled`，每次请求都显式发送；开启后成本、延迟与推理内容回放要求都不同，须以实测为据。 |
| `EMBEDDING_MODEL` | 填 `BAAI/bge-small-zh-v1.5`（选定）。混合检索的本地嵌入模型；同时作为构建参数把模型烘焙进镜像。留空则只用关键词（降级可见）。会增加镜像体积与常驻内存，按「pgvector 与混合检索」一节的实测值评估费用后再设。 |
| `EMBEDDING_MIN_SIMILARITY` | 可选。留空取模型的标定阈值；设置未标定的模型时必填。 |
| `EMBEDDING_THREADS` | 可选，默认 `1`；嵌入推理线程数。 |
| `ADMIN_TOKEN` | 运维端点凭据，生产环境至少 16 字符且非占位值。 |
| `EXPORT_SIGNING_SECRET` | CSV 导出签名密钥，生产环境必填且非占位值。 |
| `TRUSTED_PROXY_HOPS=1` | Railway 单层代理。 |
| `TRUSTED_PROXY_IPS` | **留空，不填任何值。** Railway 不发布稳定的边界代理地址；配置具体值会在重新部署后静默失效并导致限流退化，因此本项目明确不配置该变量。 |
| `RATE_LIMIT_PER_MINUTE` | 单 Token 与可信 IP 的每分钟上限。 |
| `LLM_DAILY_BUDGET_TOKENS` | **全局**每日模型 token 预算，三级预算的最上一级：公开演示时所有人共用这一个池子，它是总量闸门。默认 `1600000` = 商家角色级 `1350000` + 顾客角色级 `200000` 后取整，一天最多花掉这么多（按 2026-10-07 实测单价约合 0.56 美元）。三级预算按「每个商家每天能问 25 个左右」配出，增减演示商家数量或目标问题数时三项要一起改。耗尽后所有人收到 `LLM_BUDGET_EXCEEDED` 的可见降级，不会静默继续扣费。 |
| `LLM_CUSTOMER_DAILY_BUDGET_TOKENS` | **角色级**每日预算（顾客端全部店铺合计），默认 `200000`。顾客端是公开流量，这一级保证它耗尽时商家工作台不受影响（PRD §10.2）。 |
| `LLM_MERCHANT_DAILY_BUDGET_TOKENS` | 角色级每日预算（商家端合计），默认 `1350000` = 店铺级 × 3 个演示商家，保证三家各自用满店铺级额度时互不挤占。 |
| `LLM_SHOP_DAILY_BUDGET_TOKENS` | **店铺级**每日预算，按「角色 + 店铺」各算一份，默认 `450000`：一家店耗尽不影响其他店。2026-10-07 真实模型实测商家回合约 8700 token、用到 Skill 的三步回合约 14600；每次调用前还要按字节上界预留约 23000–28000（用完按实际对账），所以 25 个三步回合至少要约 387000，`450000` 留了余量：按同样的尺寸模拟，每个商家每天约能完成 29 个用到 Skill 的问题，或约 50 个简单问题（原默认 `100000` 时是 5 个和 9 个）。三级同时生效，任一耗尽即熔断，检查发生在请求发出之前；记忆抽取、压缩摘要等非对话调用同样计入。 |
| `AGENT_LOOP_MAX_LLM_CALLS` | v2 工具循环单回合的模型调用上限，默认 `12`；低于最坏路径所需次数时启动失败。与 v1 的 `MAX_LLM_CALLS_PER_REQUEST` 一起构成「单请求 LLM 上限」这一项公开部署前置条件。 |
| `LLM_MAX_OUTPUT_TOKENS_PER_CALL` | 默认 `8000`（字段允许的上限）。**推理模型不得低于此值**：2026-08-22 使用当时模型别名的验收中，单次结构化意图 `reasoning_tokens` 达 1400–2200，设为 1024 时正文返回空串；环比/同比回答在 `4096` 下也曾耗尽输出预算。因此保留 8000 上限。迁移到 `deepseek-flash` 后须重新测量，不能把历史数据当作当前模型承诺。 |
| `MAX_LLM_TOKENS_PER_REQUEST` | 默认 `120000`。调用前检查按输入的 UTF-8 字节数保守估算（2026-10-07 实测稳定在真实 token 的 3.5 倍左右），所以这个值要按「已用 token + 下一次输入的字节数」来配，明显高于一个回合的实际用量：`25000` 时「加载 Skill → 查数据 → 作答」的第三次调用必被拒并降级；`60000` 时售后回合（列表 → 详情 → 查三次规则）在第 5 次调用被拒；`120000` 容得下这类工具结果很长的回合走到第 9 次调用左右。一个请求的真实花费仍受循环的调用次数上限和每日预算约束。 |
| `MAX_LLM_CALLS_PER_REQUEST` | 默认 `10`。最坏调用路径为 classify 2（业务关键词收到 `INVALID/UNKNOWN` 时重试 1 次）+ understand 3（意图服务自带 2 次重试）+ 指标口径 1 + （回答生成 + 独立复核）× 2 = 10 次，四个调用点共用同一个单请求预算。设低于 10 会让意图重试把质量循环挤成「预算耗尽」降级，把排查方向带偏。 |
| `QUALITY_MAX_ATTEMPTS` | 回答质量循环的最大轮次，代码支持 1–3，默认 `2`。与 `MAX_LLM_CALLS_PER_REQUEST` 联动：每加一轮最多多 2 次模型请求；若设为 `3`，完整最坏路径为 12 次，必须同步提高调用上限。 |
| `LLM_TIMEOUT_SECONDS` | 默认 `90`。推理模型出一次意图耗时明显；超时会被 `DeepSeekLlmClient` 吞成 fallback + degraded，表现为「模型没理解」而不是「超时」，很难查。 |

现有代码已强制精确 CORS Origin（商家端与顾客端各一个）、生产 JSON 日志、`create_app()` 不启用 Debug，以及数据库连接
重试。附件功能不在当前范围，不得为其引入容器临时磁盘或对象存储。

### Railway 转发头信任策略与回退条件

本项目在 Railway 生产环境使用 `TRUSTED_PROXY_HOPS=1`、留空 `TRUSTED_PROXY_IPS`。留空时，`resolve_client_ip()` 中的 `trusted_proxy_ips and ...` 短路，跳过对直连 peer 的可信判定，即信任任何 peer 送来的转发头。

采用此策略的原因是 Railway 不发布稳定的边界代理地址；静态白名单会在重新部署后静默过期，函数随后返回 peer，令限流无声退化。该策略成立的前提是 Railway 容器没有公网直连入口，公网流量只能经 Railway 边界代理进入。

因此上线后必须完成「转发头伪造验收」：经 Railway 公网域名，使用同一演示 Token，连续发送超过 `RATE_LIMIT_PER_MINUTE` 的请求，并在每次请求中更换 `X-Real-IP`；超限后仍必须返回 429。再以 `X-Forwarded-For` 重复同一测试。记录 429 的实际触发次序。该验收不需要 LLM Key，费用为零。

若任一伪造头能够获得新限流桶（超限后未返回 429），立即将 Railway 配置改为 `TRUSTED_PROXY_HOPS=0`，接受限流收敛为按 Token 的已知可用性限制，并在 `docs/project-progress.md` 记录；后续在 F6 之后改用「按 XFF 最右跳解析」或引入 Redis 限流解决。在得到该实测证据前，不得宣告线上部署验收通过。

## cron 服务：统一分发器（N5）

PRD §10.7 定义**一个** `cron` 服务。`backend/railway.cron.json` 每 5 分钟（`*/5 * * * *`，UTC）运行
`python -m app.jobs.run_scheduled`，分发器按下表依次检查每个任务在当前时间片是否已成功跑过，没跑过就执行。
原先的三份 Cron 配置（演示数据滚动、Chat BI 汇总、访客来源状态清理）已合并进来，都没有在 Railway 创建过。

| 任务 | 频率 | 说明 | 启用条件 |
| --- | --- | --- | --- |
| `close_expired_orders` | 每次（5 分钟） | 关闭超过 30 分钟未支付的 v2 订单并释放占用 | 始终 |
| `drain_memory_outbox` | 每次 | 记忆抽取 outbox 排空；**调用 LLM**，按角色与店铺计入三级预算 | 配置了 `LLM_API_KEY`（R3 授权之后） |
| `expire_drafts` | 每小时 | 把过期的待批准草稿置为已过期 | 始终 |
| `purge_operation_evidence` | 每小时 | 清理过期的操作证据 nonce 与对应的售后确认摘要快照 | 始终 |
| `rebuild_memory_summaries` | 每小时 | 重建因来源事实删除而陈旧的商家记忆总结 | 始终 |
| `build_index` | 每小时 | 知识索引陈旧时兜底重建（知识保存与 backend 启动本就会重建） | 配置了 `EMBEDDING_MODEL` |
| `seed_demo_rolling` | 每个业务日 | 演示经营数据滚动，补齐所有漏跑日 | `ALLOW_DEMO_DATA_REFRESH=true` |
| `chatbi_rollup` | 每个业务日 | Chat BI 日汇总，默认最近 7 天；漏跑后窗口前移到上次成功那天（最多 31 天） | 始终 |
| `purge_machine_translations` | 每个业务日 | 清理过期 30 天的机器译文缓存 | 始终 |
| `purge_guest_provenance` | 每个业务日 | 清理过期且未绑定的访客会话留下的来源状态 | 始终 |
| `purge_expired_customer_memory` | 每个业务日 | 删除超过 180 天未确认的顾客记忆 | 始终 |
| `rebuild_projections` | 每个业务日 | 订单投影漂移检查，**只报告、不修复** | 始终 |
| `daily_brief`（预留） | — | 每日简报预生成：会调用 LLM，默认关闭；本版没有任务模块，`DAILY_BRIEF_SCHEDULE_ENABLED=true` 时只报告 `UNAVAILABLE` | 不启用 |

业务日按 `Asia/Shanghai` 切分：每日任务在上海零点后的第一次调度执行。

**Cron 只负责清理，不负责正确性。** 订单超时、草稿过期、证据过期、记忆保存期都在各自的业务读写路径上按截止时间判定。
Railway Cron 按 UTC 调度、不保证精确到秒、上一次没结束时可能跳过本次——迟跑、漏跑，业务结果都不变。

行为约定：

- **不重叠**：每个任务执行前取事务级 advisory lock；另一个实例正在跑同一任务时本次标 `SKIPPED_LOCKED`。
- **漏跑追赶**：到期与否看状态表 `scheduled_job_runs` 里「上次成功的时间片」是否早于当前时间片，停多久都只需恢复后的一次调度。
- **失败隔离**：一个任务失败不影响后面的任务，也不推进它的时间片，下一次调度会重试。状态表与日志只记异常类别，不记正文。
- **输出**：标准输出一行 JSON（任务名 → `OK` / `FAILED` / `NOT_DUE` / `SKIPPED_LOCKED` / `DISABLED`）；有任务失败时进程以 1 退出，
  这次运行在 Railway 上显示为失败。

变量（最小权限：清理任务只需要能连库）：

| 变量 | 说明 |
| --- | --- |
| `DATABASE_URL` | 与 backend 同一个 Neon 库 |
| `APP_ENV=production`、`BUSINESS_TIMEZONE=Asia/Shanghai` | 必填 |
| `ALLOW_DEMO_DATA_REFRESH=true` | 只在**演示库**设置：非密钥但高风险的写权限，护栏见「演示数据的每日滚动」；真实商家库永远不设 |
| `LLM_API_KEY` | **R3 授权之前不配置**。不配置时 `drain_memory_outbox` 标 `DISABLED`，outbox 留待以后处理；不得为了让任务跑起来而提前配 Key |
| `EMBEDDING_MODEL` | 可选，默认不设。索引重建由 backend 启动与知识后台保存触发，Cron 只是兜底；设置它还会把模型烘焙进 cron 镜像（它同时是构建参数） |

`drain_memory_outbox` 与 `build_index` 执行时要构造完整的应用配置，所以**启用这两项时**，cron 还需要与 backend 相同的那组变量
（`FRONTEND_ORIGIN`、`EXPORT_SIGNING_SECRET`、`BUYER_ALIAS_SECRET`、`LLM_*`、三级预算上限；配置了 Key 时还有 `ADMIN_TOKEN`）。
用 Railway 的引用变量（`${{backend.变量名}}`）指向 backend，不要另存一份；缺失时这两项会标 `FAILED`，其余清理任务不受影响。
不启用这两项时，这些变量一个都不要加。

创建步骤（控制台操作，执行前取得同意）：

1. Railway 项目内 **New → GitHub Repo**，选同一仓库，Root Directory 设为 `/backend`；
2. **Settings → Config as code** 填 `/backend/railway.cron.json`（不填会读 `railway.json`，那份带健康检查与迁移命令，Cron 会被判失败）；
3. **Variables** 按上表配置；
4. 确认 backend 已迁移到最新 head 并通过 `/api/ready`——分发器不跑迁移，缺 `scheduled_job_runs` 表时所有任务都会失败；
5. 在 **Deployments** 手工触发一次，核对输出报告没有 `FAILED`；演示库再核对经营数据已补到当前业务日。

单个任务仍可手工运行，用于排障或回补更长的窗口，例如 `python -m app.jobs.chatbi_rollup --start-date 2026-09-01`、
`python -m app.jobs.seed_demo_rolling --business-day 2026-10-04`、`python -m app.jobs.build_index`。

## 演示数据的每日滚动

线上演示库的经营数据唯一写入口是 Cron；全量 Seed 仅用于本机恢复，代码会拒绝任何非本机数据库地址：

| 入口 | 用途 | 触发方式 |
| --- | --- | --- |
| `python -m app.jobs.seed_demo_rolling` | 唯一常态入口：补齐所有漏跑业务日、清理 180 天窗口外的旧经营行，历史分区一行不改写；追加写事件账本继续留存审计记录。 | cron 分发器的 `seed_demo_rolling` 任务，每个业务日（Asia/Shanghai 零点后的第一次调度）执行一次；也可手工运行 |
| `backend/scripts/seed_demo_analytics.py --force-full-rebuild` | 一次性整体重置：只在本地且商家 UUID 集合恰好为三家固定商家时重建经营行及事件账本。 | 仅本机或本地 Compose；线上禁止执行 |
| `python -m scripts.seed_demo_scenarios --seed` | 在本地生成 S1–S4 顾客与商家双端场景。 | 全量经营 Seed 之后手工执行 |

全量重灌会连同已落库 `answers` 引用的数据依据一起抹掉，也会在本地重建三张事件账本，因此必须显式传 `--force-full-rebuild`，缺参数时直接非零退出；它还会按 `DATABASE_URL` 主机白名单拒绝非本机地址，`APP_ENV` 的生产环境拒绝规则仍作为第二道护栏保留。

滚动任务的护栏（任一不满足即在写入前失败）：

- `ALLOW_DEMO_DATA_REFRESH=true` 必须显式设置。它是**非密钥但高风险的写权限**，默认 false，绝不下发给前端或写进构建产物；
- 数据库里的商家 UUID 集合必须与三个固定演示商家**精确相等**，多一个少一个都拒绝。真实商家数据库永远不得配置该 Cron Service；
- 校验、追加与窗口清理在同一事务内完成，入口先取 `pg_advisory_xact_lock`，两个实例同时触发时第二个等待而不是交叉写入；
- 只需要 `DATABASE_URL`、`APP_ENV`、`ALLOW_DEMO_DATA_REFRESH`、`BUSINESS_TIMEZONE` 四个变量（`app/core/seed_config.py` 的 `SeedSettings`），不需要 `LLM_API_KEY`、`ADMIN_TOKEN`、`EXPORT_SIGNING_SECRET`、`FRONTEND_ORIGIN`；
- 随机基线为 `DEMO_ANALYTICS_SEED_BASE = 20260804`，第 i 个演示商家用 `BASE + i`，与全量重灌脚本共用同一常量。

任务本身不跑 Alembic 迁移：启用前先确认同环境 Backend 已迁移到位并通过 `/api/ready`，缺表时任务必须失败退出而不是自动修库。Railway Cron 按 UTC 调度、不保证精确到秒，上一次未结束时可能跳过本次，因此漏跑追赶是正确性要求而非容错优化。

调度配置与创建步骤见上一节「cron 服务：统一分发器」。**Cron Service 尚未创建**；创建并手工触发首次执行后，按本节护栏逐条核对。

## Chat BI 汇总的每日滚动

运维看板（商家端「管理 → 运维看板」，`/ops-status`）的 Chat BI 概览读的是汇总表 `chatbi_qa_daily`，**不是实时查询 `answers`**。
新回答落库后不会自动出现在看板上，必须先跑一次汇总。触发方式：

| 入口 | 覆盖范围 | 触发方式 |
| --- | --- | --- |
| cron 分发器的 `chatbi_rollup` 任务 | 最近 7 天（业务时区）；漏跑后前移到上次成功那天，最多 31 天 | 每个业务日一次，排在演示数据滚动之后 |
| `python -m app.jobs.chatbi_rollup` | 默认最近 7 天；可用 `--start-date` / `--end-date` 指定任意区间 | 手工运行，用于回补更长的窗口 |
| `POST /api/admin/analytics/chatbi/rollup` | 请求里指定的窗口 | 管理员手动，需 `X-Admin-Token`。运维看板是只读页，不提供这个按钮 |

**为什么是 7 天滑动窗口而不是只算昨天**：采纳、点赞、点踩可能在回答产生几天后才发生，只补昨天会让既往日期的采纳率和用户侧准确率
永久偏低。每天重算最近 7 天，迟到的反馈会被带进对应的 `stat_date`。汇总表只存可加计数、不存比率（比率在应用层由
`compute_north_star` 现算），因此重算是幂等的，口径调整后也能安全重算历史。

**排障提示**：看板显示样本不足时，先确认所选窗口内**确实有源数据**——`rollup_range` 只扫 `answers.processing_status = 'SUCCEEDED'`
且落在窗口内的行。窗口内无回答时，重算写入 0 行，读回来仍然是空。

该任务只读 `answers` / `feedback`、只写 `chatbi_qa_daily`，不触碰经营数据，因此不需要 `ALLOW_DEMO_DATA_REFRESH`，
真实商家数据库也可安全运行；与其他任务一样不跑 Alembic 迁移。

## v2 会话：演示 Token 撤销与来源状态清理

**撤销某个演示 Token**：本版没有公开撤销端点。从 Railway Variables 的 `DEMO_MERCHANT_TOKENS` 删掉该 Token 并重启 Backend，
启动时 `app/services/session_reconciliation.py` 会把配置与已签发商家会话按 SHA-256 指纹对账，撤销已移除 Token
换出的全部商家会话；日志只输出 `session_issuers_reconciled revoked_sessions=<行数>`，不含 Token 或指纹。
对账失败会中止启动，不会带着未撤销的会话对外服务。

**过期访客来源状态清理**：`python -m app.jobs.purge_guest_provenance` 删除「已过期且从未绑定身份」的访客会话留下的
`conversation_provenance` 行，不删业务对话，不碰已绑定或商家会话，重复执行只删 0 行。

由 cron 分发器的 `purge_guest_provenance` 任务每个业务日执行一次，只需要能连库，不需要任何 Web 服务密钥；也可手工运行上面的命令。

## 本地全栈（docker compose）

`docker-compose.yml` 按线上拓扑起一套本地环境，用来在部署前验证镜像、迁移、CORS 与单入口跳转：

| 服务 | 说明 |
| --- | --- |
| `postgres` | `pgvector/pgvector:pg16`，端口 55432 |
| `migrate` | 一次性执行 `alembic upgrade head` 后退出——对应线上的 `preDeployCommand`；`backend` 等它成功后才启动 |
| `backend` | 端口 8000；`FRONTEND_ORIGIN=http://localhost:5173`、`SHOP_ORIGIN=http://localhost:3000` |
| `shop` | 端口 3000；与 backend 共用网络命名空间，让服务端取数与浏览器用同一个 `http://localhost:8000` |
| `merchant` | 端口 5173；构建参数 `VITE_SHOP_BASE_URL=http://localhost:3000` |
| `cron` | 不随 `up` 启动；`docker compose --profile cron run --rm cron` 相当于平台触发一次调度 |

默认连 `borough_test`——它同时是 pytest 的默认测试库，跑测试会清空它，也常留有测试商家（演示数据种子会因此拒绝写入）。
要保留一份本地演示数据，另建一个库并用 `COMPOSE_DB_NAME` 指过去：

```powershell
docker compose up -d postgres
docker compose exec postgres createdb -U borough borough_compose_demo
$env:COMPOSE_DB_NAME = "borough_compose_demo"
docker compose up -d --build
```

然后按下一节向该库灌演示数据（`DATABASE_URL` 指向 `127.0.0.1:55432/borough_compose_demo`），打开 `http://localhost:5173`。
全栈冒烟：`cd frontend; npx playwright test --config playwright.compose.config.ts`（商家首页 → 「顾客视角」→ 顾客端快捷提问）。
本地没有配置 `LLM_API_KEY`，助手回答是可见降级；带脚本化模型的 S1–S8 场景由各自的测试套件覆盖，不在这套环境里跑。

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

5. 补齐 S1–S4 的确定性场景数据：

   ```powershell
   uv run python -m scripts.seed_demo_scenarios --seed
   ```

6. 恢复镜像知识种子（共 21 篇，且不会覆盖后台已维护的同路径文档）：

   ```powershell
   uv run python -m scripts.import_wiki --root "../yshopping-merchant-ai 4/yshopping-merchant-ai/runtime/llm-wiki"
   ```

7. 校验数据量和日期窗口：经营历史 `orders` 应为数千行，`business_date` 应连续覆盖 180 天并截止于当前业务日；另有 S1–S4 场景行。`knowledge_documents` 应为 21 篇种子文档（`index/README.md` 一篇、十个业务分类各两篇）。如确需本机强制覆盖同路径的后台维护内容，才传入 `--overwrite`；该开关会丢失这些后台改动，线上不得使用。

## 运维验收

- 确认 `/api/health` 持续正常，重启 Backend 后数据仍在 PostgreSQL 中。
- 非演示生产部署中，确认 `/api/demo/merchants` 不可用；对外演示部署中（`DEMO_DEPLOYMENT_MODE=true`），确认该端点可用且只返回服务端配置的演示商家。
- 超额频率返回 `RATE_LIMITED`；达到模型日预算后显示明确降级。
- `GET /api/admin/ops/status` 仅接受 `X-Admin-Token`，不得返回 Token、Prompt、商家数据或连接串。
- 商家端「管理 → 运维看板」（`/ops-status`）输入管理员令牌后显示三级预算余量、当日成本、限流与降级计数、工具错误率、路由 p95 与 Chat BI 概览；页面只读，没有任何写操作按钮；只读令牌只能看到 Chat BI 概览。
- 任意请求带上 `X-Request-Id` 后，响应头回写同一个值，`llm_usage` 与审计行可按它查到该次请求。
- cron 服务手工触发一次，输出报告没有 `FAILED`；紧接着再触发一次，全部为 `NOT_DUE` 或 `DISABLED`。
- 从商家端点「顾客视角」，新标签页的地址只有 `shop` 域名与店铺标识，没有任何查询参数。
- 本地或预发做一次 SIGTERM 验收：发起长 SSE 请求后执行 `docker stop <container-id>`，确认连接以 `done` 或 `error` 收尾，容器在 `backend/app/run.py::GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS`（30 秒）内退出。

## 公开部署前置条件验收（N5）

Backend 是公开的，**下面三项全部在公网域名上验收通过之前，不得把真实 `LLM_API_KEY` 配到公网实例**（`AGENTS.md` §十一）。
每一项验收都不需要 LLM Key，费用为零；经公网域名打限流与熔断属于生产变更，执行前取得同意。结果逐项记入
`docs/history/deploy-preflight-<日期>.md`（时间、请求次数、实际状态码序列、结论）。

| 前置条件 | 验收方式 | 通过标准 |
| --- | --- | --- |
| 基础限流 | 经公网域名、用同一演示 Token 连续请求超过 `RATE_LIMIT_PER_MINUTE` 次，**每次更换 `X-Real-IP`**；再换成每次更换 `X-Forwarded-For` 重复一遍（即下文「转发头伪造验收」） | 超限后返回 429 `RATE_LIMITED`，伪造的转发头换不到新的限流桶 |
| 单请求 LLM 上限 | 核对生产配置里 `AGENT_LOOP_MAX_LLM_CALLS`、`AGENT_LOOP_MAX_TURNS`、`AGENT_LOOP_MAX_TOOL_CALLS` 与 v1 的 `MAX_LLM_CALLS_PER_REQUEST`、`MAX_LLM_TOKENS_PER_REQUEST` 已生效（`/api/admin/ops/status` 不返回配置值，以 Railway Variables 与启动日志为准）；触顶行为由自动化测试用 Fake 注入证明 | 配置值在预期范围内；触顶时回答带降级标注，不继续调用 |
| 每日预算熔断 | 未配置 Key 时线上**触发不了**熔断（守卫在预留额度之前就按「模型未配置」降级），所以分两步：① 配 Key 之前，以自动化测试为证（三级隔离、耗尽时请求数为 0：`tests/unit/llm/test_guard_three_level.py`、`tests/integration/repositories/test_llm_budget_repository.py`），并在运维看板核对三级预算行存在、额度与配置一致；② 取得两项授权、配置 Key 的**同一次部署**里把三级预算都设为最小值 `1000`，发一次对话后再调回正常值 | ① 测试全绿、看板三级预算行正确；② 单次调用的预留额度大于 `1000`，请求在发出之前被拒，返回 `LLM_BUDGET_EXCEEDED` 的可见降级，`llm_usage` 只有 `BUDGET_REJECTED` 行、没有成功调用，费用为零 |

前两项与第三项的 ① 全过后，向用户报告并请求配置真实 Key；第三项的 ② 在配置 Key 的那次部署里立即完成。这一步同时属于**生产变更**与 **R3**，两项授权都要有，并写明模型、
预计调用量与每日费用上限；授权前公网实例只跑不调用模型的降级路径。

## MCP 只读入口与凭证（N5）

`POST /api/v2/merchant/mcp` 是给标准 MCP 客户端用的只读入口（协议版本固定 `2026-07-28`，`GET` 返回 405）。
它不认商家会话，只认独立的 MCP 凭证：`Authorization: Bearer <凭证>`。凭证限定一家店与一组只读工具，默认 24 小时、
最长 7 天，撤销后下一次请求立即 401。鉴权在读取请求正文之前完成，未认证请求碰不到 JSON-RPC 解析器。

**凭证没有任何 HTTP 管理路径**，只经后端命令行脚本签发、撤销与列出。脚本在仓库的 `backend/scripts/` 下，
**不在 backend 镜像里**（镜像只带 `app/`），所以要在一份仓库检出里运行，并让 `DATABASE_URL` 指向目标库：

```powershell
cd backend
uv run python -m scripts.mcp_credentials issue --merchant <店铺标识> --scopes query_metrics --ttl-hours 24
uv run python -m scripts.mcp_credentials list --merchant <店铺标识>
uv run python -m scripts.mcp_credentials revoke --id <凭证 ID>
```

`issue` 是凭证原值唯一一次出现的地方：只打印到标准输出，不写日志、不落库（库里只有指纹）。
**对生产库签发凭证属于生产变更，须先取得同意**；本项目目前只在本地测试库签发过。

## 迁移失败与回滚

- **发布阶段迁移失败**：`preDeployCommand` 非零退出时 Railway 不会切换到新版本，旧版本继续服务。查看 preDeploy 日志定位失败的迁移，
  修复后重新部署；不要在 backend 或 cron 的启动命令里加迁移来「绕过」。
- **N5 的四条迁移都是纯新增**：`20261003_0048`（`mcp_credentials` 表）、`20261003_0049`（`llm_daily_budget` 按预算范围分行）、
  `20261003_0050`（`model_price_versions` 表与 `llm_usage` 的角色、缓存命中、价格版本、成本列）、`20261004_0051`
  （`scheduled_job_runs` 表）。只回退应用代码、不回退迁移是安全的：旧代码不知道新表与新列。
- **确需回退迁移**：`alembic downgrade <目标版本>`。回退 `0050` 会丢弃已记录的调用成本与价格版本；回退 `0049` 会把当日预算用量并回全局一行。
  `model_price_versions` 有「只允许追加」的触发器，价格变动一律新增版本行，不要手工改旧行。
- **迁移前的保险**：对 Neon 做任何生产迁移之前，先在 Neon 控制台确认时间点恢复可用，或为当前状态建一个分支。这是用户侧操作。
- **关闭某项能力而不动数据库**：清空 `EMBEDDING_MODEL` 回到纯关键词检索；清空 `VITE_SHOP_BASE_URL` 并重新构建商家端可隐藏「顾客视角」；
  不配置 `LLM_API_KEY` 时所有模型路径进入可见降级；撤销全部 MCP 凭证即关闭 MCP 访问。

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
5. 若需要验证真正需要模型翻译的路径（跨语言知识召回、自由文本批量翻译等），必须先按 AGENTS.md R3 向用户说明会调用的接口、预计调用次数、模型（默认 `deepseek-flash`）与费用，取得明确同意后才执行——不属于本 Smoke Test 默认范围。

### 数据库迁移与缓存说明

本效果新增两个迁移，链接在既有单一 head 之后：

- `20260831_0015_localization_tables.py`：创建 `machine_translation_cache`（机器译文缓存）与 `resource_localizations`（资源级人工译文）两张表；均按 `scope_kind`（`MERCHANT`/`GLOBAL`）+ `merchant_id` 的 CHECK 约束与按作用域拆分的表达式唯一索引强制隔离，避免 PostgreSQL 唯一索引中 `NULL` 互不相等导致 `GLOBAL` 行无限重复插入。
- `20260831_0016_content_locale_metadata.py`：给 `messages`/`answers`/`knowledge_documents`/`merchant_memories` 各加一个内容语言分类列（历史行按迁移内冻结的确定性分类函数逐行回填，禁止用数据库默认值把历史内容一律标成 `zh-CN`），给 `merchants` 加人工维护列 `display_name_en`，给 `llm_usage` 加调用用途列 `purpose`（历史行按 `server_default` 回填为 `AGENT`）。

迁移仍由 `railway.json` 的 `deploy.preDeployCommand`（`alembic upgrade head`）在发布阶段执行一次；两个新迁移都已验证支持 `alembic upgrade --sql`（离线 SQL 渲染），不依赖真实数据库连接即可静态核对。

### 30 天过期清理

`machine_translation_cache` 的每一行写入/覆盖时都把 `expires_at` 设为 `now() + interval '30 days'`（`LocalizationRepository.upsert_machine()`）。**读路径（`get_merchant_machine_many()`/`get_global_machine_many()`）当前不按 `expires_at` 过滤**——过期只影响是否被批量清理，不影响该行在被清理前继续被当作有效缓存命中；由于缓存键包含内容哈希，源文本一旦变化会产生新哈希、自然不会命中旧行，因此这不是正确性问题，只是存储卫生问题。

批量清理由 `LocalizationRepository.purge_expired_machine()` 提供，有专门的集成测试覆盖（`backend/tests/integration/repositories/test_localization_repository.py`），由 cron 分发器的 `purge_machine_translations` 任务每个业务日调用一次（N5 接线）。cron 服务创建之前，`machine_translation_cache` 会持续增长，但不会造成翻译结果错误。

### 回滚指引

- **只回滚代码、不回滚迁移**：本效果的两个迁移是纯增量（新表 + 新增列），不修改任何既有列的语义或删除任何数据；只回退应用代码到迁移前版本即可安全共存于已迁移的数据库——旧代码不知道新列/新表存在，会继续按原有行为工作。
- **确需回滚迁移**（例如新表结构本身有缺陷）：`alembic downgrade 20260823_0014` 会依次撤销 `20260831_0016`（先删除六个新增列——`messages.source_locale`、`answers.response_locale`、`knowledge_documents.source_locale`、`merchant_memories.source_locale`、`merchants.display_name_en`、`llm_usage.purpose`；`display_name_en`/`purpose` 之外的四个分类列因为已回填真实历史数据，降级会永久丢弃这些回填结果）和 `20260831_0015`（删除两张新表，连同其中已经产生的机器译文缓存和人工译文一起丢弃）。降级前必须确认没有依赖这些列/表的代码仍在运行。
- **只想临时关闭翻译功能、不动数据库**：把四个 `LOCALIZATION_MAX_*` 中的 `LOCALIZATION_MAX_CALLS_PER_REQUEST` 设为最小值（`1`）不能完全禁用，因为它仍允许 1 次调用；真正的开关是上游是否发起翻译请求（前端语言切换与 `Accept-Language`），本效果没有提供单独的 `LOCALIZATION_ENABLED` 总开关。如需紧急止损，可临时不配置 `LLM_API_KEY`（主 Agent 与本地化共用同一把 DeepSeek Key），两条调用路径会一起进入现有的 LLM 不可用降级分支，而不是只关翻译。

## 单 worker 与多实例限制

容器保持单 worker。限流器、运行时可观测性计数与预算估算协调均为进程内状态；多 worker 会使限流与指标失真。`LlmBudgetRepository.reserve` 的数据库条件更新仍可防止预算超发，但多个 Backend 副本只会产生近似的限流与运维计数。需要多副本前，应先引入共享状态存储。
