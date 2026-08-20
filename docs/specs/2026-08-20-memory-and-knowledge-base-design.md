# 记忆沉淀子 agent 与双知识库设计说明

**日期：2026-08-20　状态：待实施　依据：R9（参考项目是需求基准）**

本文件是 `yshopping-merchant-ai 4/` 中「知识库 + 记忆」两块能力的逐行对照结果，
以及它们在 Borough 上的落地设计。它补上了 `docs/yshopping-parity-audit.md` §6
挂账的两项待核实条目：`WikiMemoryService`（441 行）与 `WikiAdminService`（498 行）。

参考目录在本轮审计中**未作任何修改**，全部结论来自只读读取（R8）。

---

## 1. 术语澄清

参考项目里 **`runtime/llm-wiki/` 就是它的知识库**，不存在「llm wiki 之外还有一个知识库」。
两个名字指同一个东西，区别只在存储介质是磁盘 markdown 而不是数据库。
`WikiAdminService` 提供的就是知识库维护后台，只不过它维护的是文件。

参考项目的知识库结构：

```text
runtime/llm-wiki/
├── index/                                  业务域索引，模型拆词时先读
├── 业务/
│   └── {业务域}/                            10 个业务域
│       ├── 业务流程/                        ┐
│       ├── 业务名词解释/                     ├ WikiPathPolicy.BUSINESS_SECTIONS
│       ├── ddl/                            │ 四个固定板块，展示顺序固定
│       └── 指标或调用指标平台mcp的skill/      ┘
└── memory/
    └── merchants/{商家目录}/{分类}.md        记忆库，后台只读
```

---

## 2. 参考实现行为审计

### 2.1 双知识库路由（`WikiMemoryService.loadRelevantWiki`）

调用顺序固定为四步：

1. 按业务分类取人工维护文档 `loadMaintainedDocuments(category)`；
2. 分类非 `UNKNOWN` 且带意图关键词时，用关键词二次收窄；
3. **人工库非空 → 直接返回，标记 `[LLM_WIKI_SOURCE=maintained]`，记忆完全不参与**；
4. 人工库为空 → 取该商家记忆，标记 `[LLM_WIKI_SOURCE=memory-fallback]`。

渲染上限 `MAX_WIKI_CHARS = 24_000`，超出即截断。

关键词收窄规则（`matchesIntentKeywords`）：先全词匹配；不中则剥掉中文指标问法词尾
`(指标|明细|数据|情况|趋势|数量|金额|次数|量|数)$`，词干长度 ≥ 2 时再匹配一次。

维护文档判定（`isMaintainedDocument`）按顺序排除：

- 内容含 `本轮自动沉淀` 标记；
- 文件名含 `memory`；
- 路径含 `/记忆/`；
- 分类为 `UNKNOWN` 时只认路径含 `index` / `rule` / `目录` 的文档；
- 分类为 `PLATFORM_RULE` 时认 `rule` 或含 `规则` / `政策` / `平台要求`；
- **根级 `rule.md` 不得冒充业务知识**——它包含所有业务词，只能服务平台规则或首轮索引；
- 其余按该分类的关键词表匹配「路径 + 正文」。

### 2.2 问答图中的三个检索点（`MerchantQaLangGraph`）

| 节点 | 分类参数 | 用途 |
| --- | --- | --- |
| `loadHistoryAndWiki`（节点 2） | `UNKNOWN` | 只取索引，供模型自己拆词与理解业务域 |
| `recognizeIntent`（节点 3） | 初次意图分类 + 意图关键词 | 取业务知识喂给 `understand` |
| 意图定稿后 / 上文复用分支 | 最终意图分类 + 关键词 | 刷新 `state.wiki` |

### 2.3 记忆沉淀子 agent（`MemoryConsolidationService`）

- 单线程 daemon executor，线程名 `merchant-ai-memory-agent`；
- 在 persist 节点 `submit()` 后立即返回，**不阻塞本轮回复**；
- 取该商家最近 80 条问答，按 `question_category_name` 过滤出同分类；
- 拼装人工补充 markdown，固定六个字段加正文：
  `question` / `category` / `doris_tables` / `semantic_notes` / `suggested_questions` / `csv_export` / `answer`；
- 交由 `WikiMemoryService.compressToWiki` 压缩后**全量覆盖写入**；
- 任何异常只 `log.warn`，主链路不受影响；
- `@PreDestroy` 时 `shutdownNow()`。

`compressToWiki` 的四条硬约束（写在压缩提示词里）：

1. 只沉淀当前商家、当前业务分类的意图、可用表、字段、口径和话术；
2. 信息要短、准、可复用，**不要编造数据库字段**；
3. 人工补充内容存在时优先保留；
4. **不得引用、推测或合并其他商家和其他业务分类的信息**。

失败兜底：LLM 返回空或异常时写确定性 fallback 文本（标题 + `本轮自动沉淀` +
人工补充 + 更新时间）。写入前强制校验内容含 `本轮自动沉淀` 标记，缺失则补加标题。

### 2.4 防污染的四道机制

| 层 | 机制 |
| --- | --- |
| 写侧 | 记忆只写 `memory/merchants/{商家}/`，强制注入 `本轮自动沉淀` 标记 |
| 读侧 | `isMaintainedDocument` 排除含标记、文件名含 `memory`、路径含 `/记忆/` 的文档 |
| API 侧 | `resolveWritableDocument` 对 `memory/**` 返回 403 `WIKI_READ_ONLY` |
| 目录树 | `tree()` 把 memory 根节点标 `readOnly=true` |

### 2.5 知识库后台（`WikiAdminService` + `WikiPathPolicy`）

**虚拟层级**（`WikiPathPolicy`）：

- 可读：`index` / `index/**`、`业务` / `业务/**`、`memory` / `memory/**`（只读）；
- 可写文档只有两种形态：`index/{名}.md`（2 段）、`业务/{域}/{板块}/{名}.md`（4 段）；
- 板块必须属于 `BUSINESS_SECTIONS` 四个之一，且目录树展示顺序按该列表下标固定；
- 业务域名保留字：`index`、`memory`、`业务`，且不得以 `.md` 结尾。

**路径校验**（逐条）：拒绝空路径、反斜杠、前导 `/`、绝对路径、控制字符；NFC 归一化；
整串 ≤ 512 字符；每段 ≤ 120 字符；拒绝 `.`、`..`、前导点、首尾空白；拒绝 `:*?"<>|`；
逐段检查符号链接；候选路径必须位于根目录内。文档名必须以 `.md` 结尾且长度 > 3。

**并发控制**：SHA-256 十六进制串作版本号。文件版本 = 内容摘要；目录版本 =
`"directory:" + 虚拟路径` 与各子节点 `path:version` 逐行拼接后再摘要。
`If-Match` **缺失返回 428 `WIKI_VERSION_REQUIRED`**，不匹配返回 412 `WIKI_VERSION_CONFLICT`；
比对前剥掉 `W/` 前缀与包裹的双引号。

**写入语义**：临时文件 + `ATOMIC_MOVE`，不支持原子移动时退化为普通移动；
建业务域使用 staging 临时目录建好四个板块后整体移动，失败清理；
删业务域在含文档且未传 `recursive=true` 时返回 409 `WIKI_DIRECTORY_NOT_EMPTY`，
含符号链接时返回 400 `SYMLINK_NOT_ALLOWED`；大小写不同的同名节点视为冲突
（NFC + lowercase 折叠比对）。

**内容校验**：UTF-8 严格解码，非法编码 415 `INVALID_WIKI_ENCODING`；
含 NUL 字节 400 `INVALID_WIKI_CONTENT`；超过 `maxDocumentBytes` 返回 413
`WIKI_DOCUMENT_TOO_LARGE`。全服务由一把 `ReentrantReadWriteLock` 串行化。

**错误码全集**（14 个）：`INVALID_WIKI_PATH`、`WIKI_READ_ONLY`、`INVALID_FILE_TYPE`、
`INVALID_WIKI_PARENT`、`WIKI_NODE_EXISTS`、`WIKI_NODE_NOT_FOUND`、
`WIKI_DIRECTORY_NOT_EMPTY`、`WIKI_VERSION_REQUIRED`、`WIKI_VERSION_CONFLICT`、
`WIKI_DOCUMENT_TOO_LARGE`、`INVALID_WIKI_ENCODING`、`INVALID_WIKI_CONTENT`、
`SYMLINK_NOT_ALLOWED`、`WIKI_IO_ERROR`。

---

## 3. Borough 的现状映射

| 参考项目 | Borough | 状态 |
| --- | --- | --- |
| 磁盘目录树 | `knowledge_documents.source_path`（Text，唯一索引） | ✅ 已有 |
| 文件正文 | `knowledge_documents.content` | ✅ 已有 |
| 目录归属业务域 | `knowledge_documents.category`（10 个枚举，逐字对应参考 `QuestionCategory`） | ✅ 已有 |
| `Files.walk` 遍历 | `SELECT ... WHERE source_path LIKE ...` | 待做 |
| `matchesIntentKeywords` 词干规则 | `retrieval.strip_metric_suffix()` | ✅ 已 1:1 复刻 |
| 根级 `rule.md` 不冒充业务知识 | `retrieval._is_domain_document()` 排除索引文档 | ✅ 已有 |
| `MAX_WIKI_CHARS = 24_000` | `domains.MAX_KNOWLEDGE_CHARS = 24_000` | ✅ 一致 |
| `UNKNOWN` / 业务分类两种调用 | `load_index()` / `load_domain()` | ✅ 已有 |
| `memory/merchants/{商家}/` | `merchant_memories` 表 | ❌ 未建 |
| `[LLM_WIKI_SOURCE=*]` | `KnowledgeResult.source` + `AnalysisSource.MEMORY` | ❌ 未做（枚举已存在） |
| `MemoryConsolidationService` | `services/memory_service.py` | ❌ 未建 |
| `WikiAdminService` / `WikiPathPolicy` | B9 未开工 | ❌ 未建 |
| `KnowledgeBaseApp.vue`（660 行） | `KnowledgeBaseView.vue`（占位页） | ❌ 未实现 |

`retrieval.py` 在 `load_domain` 返回前已预留插入点注释：
「团队知识未命中后的商家记忆回退属于 P1/B8；当前必须显式表明未命中。」

---

## 4. 有意偏离登记

以下四项**不还原参考项目**，依据均为本项目既定规则，须同步登记进
`docs/yshopping-parity-audit.md` §5。

### 4.1 存储介质：文件系统 → PostgreSQL

参考项目把知识与记忆全部落在 `runtime/llm-wiki/` 并要求 Railway 挂载 Volume。
AGENTS.md §8.7 规定「运行时可编辑知识应存入 PostgreSQL 或对象存储，不依赖 Railway
临时文件系统」。**必须偏离**：不偏离则容器重启后记忆与后台改动全部丢失。

本偏离早于本轮设计，已写在 `backend/app/knowledge/retrieval.py` 的模块 docstring 中。

后果：`WikiPathPolicy` 的符号链接检查（`ensureNoSymbolicLinks`）无对应物，不实现；
其余 13 条路径校验全部保留，校验对象由真实路径改为 `source_path` 虚拟路径字符串。
它们防的是逻辑越权而非文件系统越权，与介质无关。

### 4.2 记忆文件名：`isolatedPathSegment()` → 数据库唯一约束

参考项目用「净化名截 64 字符 + `-` + 原值 UUID 摘要前 12 位」生成防穿越的目录名与
文件名。数据库中不存在路径穿越，改用 `(merchant_id, category)` 唯一约束表达
「每商家每分类各一份、全量覆盖」的同一语义。

### 4.3 管理员鉴权头：`Authorization: Bearer` → `X-Admin-Token`

参考项目的 `WikiAdminController` 复用 `Authorization: Bearer`。AGENTS.md §10.2.1
明确禁止：两者语义、生命周期与泄露后果均不同，共用一个请求头会让后端无法区分
「商家在调管理接口」与「管理员在调商家接口」。按既定规则走 `X-Admin-Token`。

### 4.4 接口路径：`/api/admin/wiki/*` → `/api/admin/knowledge/*`

路径按 AGENTS.md §10.2 与 `docs/PRD.md` §11 的既有清单，不改成参考项目的命名。

---

## 5. 需补进我方文档的差异

参考项目有三个业务域管理端点，**我方接口清单里没有**。按 R9，判定为「我们缺了要补」，
须在实施时同步修改 `AGENTS.md` §10.2 与 `docs/PRD.md` §11：

```text
POST   /api/admin/knowledge/business-domains          建业务域（自动建齐四个板块）
PUT    /api/admin/knowledge/business-domains          业务域改名
DELETE /api/admin/knowledge/business-domains          删业务域（recursive 保护）
```

---

## 6. 待裁定：四个板块中的两个

`backend/app/knowledge/wiki_import.py` 当前排除两个板块：

```python
_EXCLUDED_DIRS = ("ddl", "指标或调用指标平台mcp的skill")
```

理由是它们描述参考项目 Doris 那 11 张表的结构，Borough 不存在这些表。
但参考项目的 `BUSINESS_SECTIONS` 是四个且展示顺序固定，后台目录树按此渲染。

**本设计采用的方案（待用户确认）**：保留四板块结构，`ddl` 板块内容改写为 Borough
自己六张经营表的结构说明，`指标或调用指标平台mcp的skill` 板块内容改写为 Borough 的
`metric_code` 目录。结构 1:1，内容跟随本项目的数据模型。

改动面：`_EXCLUDED_DIRS` 一个常量 + 一次重新导入。若用户改判为「只保留两个板块」，
需同步修改 `BUSINESS_SECTIONS` 并在 parity-audit §5 追加一条偏离登记。

---

## 7. 实施拆分

分两份计划，记忆先行：

1. **`plans/2026-08-20-memory-consolidation-agent.md`** —— `merchant_memories` 表、
   `MemoryService`、双库硬优先级检索、来源标记、后台异步接入。
   记忆是「知识库后台 memory 只读分区」的数据前提。

2. **`plans/2026-08-20-knowledge-admin-backend.md`** —— 虚拟路径策略、目录树、
   文档 CRUD、业务域三端点、`X-Admin-Token` 守卫、前端知识库后台页面。

**前置依赖**：`plans/2026-08-19-codex-remaining-development-tasks.md` 的 T1
（导入知识库）必须先完成。`knowledge_documents` 当前 0 行，人工库为空时
「人工库优先」行为上等同于「永远走记忆 fallback」，优先级是否生效无法验收。
