# Anthropic 与 Shopify 参考项目增强路线图

> 状态：候选路线图，不代表功能已经实现，也不自动扩大当前 PRD 范围。
> 建立日期：2026-09-18
> 适用项目：Borough 商家 AI 助手

## 一、目标与使用方式

本文把 Anthropic Commerce Agents 与 Shopify Claude for Commerce Examples 中值得借鉴的模式，
转化为 Borough 可评审、可排期、可验收的增强事项。它解决三个问题：

1. 哪些模式能增强 Borough 现有 Agent，而不推翻当前架构；
2. 哪些新能力适合加入产品，以及应当先做什么；
3. 哪些示例只适合研究，不能直接进入生产环境。

本文不是实施计划。任何会改变产品范围、API、数据库或用户行为的条目，开工前仍须依次同步
`docs/PRD.md`、契约、前后端计划和测试。安全与架构硬约束继续以 `AGENTS.md` R1–R9 为准，
`yshopping-merchant-ai 4/` 仍是业务行为与视觉还原基准。

## 二、参考基线

| 项目 | 上游地址 | 固定提交 | 主要价值 |
| --- | --- | --- | --- |
| Anthropic Commerce Agents | <https://github.com/anthropics/commerce-agents> | `fd4d59224ab96b43c6dc6888207c67b3bd5a24cf` | Agent 分层、Skills、工具执行、安全闸门、grounding、provenance、记忆、流式事件和人工审批 |
| Shopify Claude for Commerce Examples | <https://github.com/Shopify/claude-for-commerce-examples> | `d68c7fa24f26ab138d8b4ccdd0488db140a6bfe6` | Shopify 真实接入、指标与告警、变更台账、审批写入、幂等与集成测试 |

本地只读副本：

```text
D:\vscode html\merchant_assistant-research\github\anthropic-commerce-agents
D:\vscode html\merchant_assistant-research\github\shopify-claude-for-commerce-examples
```

研究结论只基于上述固定提交。更新上游副本后，应重新核对本路线图，不把新版行为默认为已采纳。

## 三、总体判断

### 3.1 Borough 应保留的主架构

Borough 已具备 Anthropic/Shopify 示例没有完整覆盖的生产基础，以下部分不应因参考项目而替换：

- Vue 3 + TypeScript 前端和现有领域模型；
- FastAPI + LangGraph Agent 编排；
- PostgreSQL、Alembic 与 Repository 持久化；
- 可信身份、`merchant_id` 隔离、管理员/只读权限；
- 结构化查询意图、SQL 白名单、参数绑定与行数/日期限制；
- DeepSeek LLM 抽象、调用预算、限流和显式降级；
- Reviewer、质量重试、日报、知识库、商家记忆、Chat BI 和双语链路；
- 当前 Railway 部署拓扑与 API 契约。

### 3.2 应重点吸收的能力

| 能力方向 | Anthropic | Shopify | Borough 建议 |
| --- | --- | --- | --- |
| Agent 分层 | Prompt、Skills、Tools、Gates、Executor 分离 | 复用同一蓝图并接真实平台 | 适配到现有 LangGraph，不整体迁移运行时 |
| 数据可信度 | grounding、server enrichment、provenance | Admin API/ShopifyQL 结果映射 | 增加来源约束和服务端回填，继续禁止任意 SQL |
| 写操作安全 | stage → approve → apply，应用时二次校验 | 零 mutation 暂存、一次 mutation 应用 | 新增变更台账与独立审批 API |
| 经营主动性 | performance insights、digest、alerts | 低库存、滞销、延迟订单、退款异常 | 建立可解释的主动经营告警中心 |
| 集成边界 | `MerchantBackend` 抽象 | Shopify Admin GraphQL 实现 | 建立平台连接器 Protocol，先只读后写入 |
| 前端交互 | SSE 工具事件、生成式卡片、审批卡 | Storefront 卡片；Merchant 无完整 UI | 在现有 Vue 中补经营卡片和审批工作台 |
| 测试 | Fake Client、门禁和行为评测 | 录制响应、Fake Admin、Local Store、Live Smoke | 建立三层连接器测试和 Agent 场景评测 |

## 四、决策原则

所有候选项统一采用以下结论：

- **采纳**：核心模式与 Borough 现有约束一致，可按当前技术栈实现；
- **适配**：保留思想，但必须改造模型、鉴权、数据隔离、存储、协议或 UI；
- **拒绝**：与 R1–R9、产品定位或当前阶段冲突，不进入路线图。

实施优先级含义：

- **P0**：先增强 Agent 的可信性、安全性和可测试性，不引入外部写操作；
- **P1**：形成可见的商家产品能力，以只读分析、告警和变更草稿为主；
- **P2**：在独立授权和审计体系完成后，接入第三方平台并执行真实写操作。

## 五、P0：增强现有 Agent 内核

### P0-1 第三方内容 Fencing 与 Prompt 注入防护

| 项目 | 内容 |
| --- | --- |
| 来源 | Anthropic `commerce_common/fencing.py` 与 `docs/safety.md` |
| 结论 | 适配 |
| Borough 现状 | 已有结构化意图、安全查询和知识检索，但尚未形成统一的“不可信外部文本”包装层 |
| 增强内容 | 对知识文档、附件文本、商品描述、工单内容和未来平台数据统一清洗；移除控制字符、伪造角色/工具标签；使用固定边界标签；限制单段和总字符数；明确这些内容是数据而非指令 |
| 建议落点 | `backend/app/knowledge/`、未来 `attachment_service.py`、新增 `backend/app/agent/fencing.py` |
| 前置依赖 | 无；附件路径上线时必须复用同一能力 |
| 验收标准 | 注入样例不能改变系统指令或工具选择；超长内容被截断并显式记录；中英文测试均通过 |

### P0-2 动态工具白名单与能力开关

| 项目 | 内容 |
| --- | --- |
| 来源 | Anthropic tool registry 与 deployment config |
| 结论 | 采纳 |
| Borough 现状 | 回答模式和查询路由已受控，但工具能力尚未形成独立、可枚举的注册表 |
| 增强内容 | 按部署配置、商家权限和回答模式生成可用工具集合；执行器拒绝未注册工具；未接入的能力从 Prompt 和工具面同时移除 |
| 建议落点 | 新增 `backend/app/agent/tools/registry.py`；由 `graph.py` 和依赖注入层消费 |
| 前置依赖 | 明确工具 Schema 与权限元数据，不改变现有 ChatResponse 契约 |
| 验收标准 | 禁用工具不会出现在模型上下文；伪造工具名被确定性拒绝；不同商家能力互不泄漏 |

### P0-3 数据与操作 Provenance

| 项目 | 内容 |
| --- | --- |
| 来源 | Anthropic cart/staging provenance gates |
| 结论 | 适配 |
| Borough 现状 | 查询强制注入 `merchant_id`，回答包含 `analysis_sources`，但尚未为本轮出现过的业务对象建立细粒度来源集合 |
| 增强内容 | 记录本轮由后端返回过的商品、订单、库存、工单和变更 ID；后续详情读取、导出或写操作只能引用已授权且已出现的对象；集合设置容量和过期规则 |
| 建议落点 | `backend/app/agent/state.py`、`merchant_scope.py`、会话持久化层 |
| 前置依赖 | 先定义 provenance 领域模型和会话并发语义 |
| 验收标准 | 模型凭空构造的对象 ID 无法被读取或修改；跨商家 ID 始终 403 并写审计 |

### P0-4 强制 Grounding 规则

| 项目 | 内容 |
| --- | --- |
| 来源 | Anthropic grounding rules 与 forced tool choice |
| 结论 | 采纳 |
| Borough 现状 | Agent 已检索知识并查询经营数据，但“哪些问题必须先读哪类数据”主要由图路由和 Prompt 共同保证 |
| 增强内容 | 为指标、规则、订单、退款、库存和身份问题建立确定性 grounding policy；没有读取成功时禁止生成确定数值或操作结论，转为显式降级 |
| 建议落点 | 新增 `backend/app/agent/grounding.py`，在 `query_data` 与 `compose_answer` 之间校验 |
| 前置依赖 | 复用 `analysis_sources`、`degraded`、`degraded_reason`，不新增重复字段 |
| 验收标准 | 每类问题有“必须读取/允许回答/降级”测试；缺少来源时 Reviewer 之前就被拦截 |

### P0-5 服务端生成与回填 UI 数据

| 项目 | 内容 |
| --- | --- |
| 来源 | Anthropic presentation schema validation 与 server enrichment |
| 结论 | 采纳 |
| Borough 现状 | 图表数据由后端确定生成，已经具备良好基础 |
| 增强内容 | 模型只选择卡片类型和业务对象 ID；标题、金额、库存、指标值、链接等由后端可信记录回填；无 provenance 的对象被丢弃并记录质量说明 |
| 建议落点 | `visualization_service.py`、新增 presentation registry、前端领域 Adapter |
| 前置依赖 | 定义有限的卡片 Schema，不允许任意组件或 HTML |
| 验收标准 | 模型不能伪造金额、指标和 URL；未知卡片类型被拒绝；空卡片不发送到前端 |

### P0-6 Session 并发和状态版本控制

| 项目 | 内容 |
| --- | --- |
| 来源 | Anthropic versioned session state 与 racing write protection |
| 结论 | 采纳 |
| Borough 现状 | 有会话持久化和幂等请求 ID，但需要独立核对同一会话并发轮次的覆盖风险 |
| 增强内容 | 会话状态增加版本号或乐观锁；相同会话并发请求只能按规则串行或发生显式冲突；后台记忆任务不得覆盖更新后的状态 |
| 建议落点 | 会话 Repository、`chat_service.py`、记忆后台任务 |
| 前置依赖 | PostgreSQL 集成测试必须覆盖并发事务 |
| 验收标准 | 并发请求不能丢消息、串商家或回滚新状态；冲突返回稳定错误码并可重试 |

### P0-7 Agent 场景评测与安全不变量测试

| 项目 | 内容 |
| --- | --- |
| 来源 | Anthropic Fake Client/evals；Shopify scripted turn、Fake Admin、Local Store |
| 结论 | 采纳 |
| Borough 现状 | 单元、API、集成和前端测试数量充足，但 Agent 行为评测仍可按业务场景统一建模 |
| 增强内容 | 建立 YAML/JSON 场景集，描述输入、身份、允许工具、必须来源、禁止动作、预期回答模式与降级；真实模型验收和 Fake LLM 契约共用同一场景定义 |
| 建议落点 | `backend/tests/evals/`、`backend/tests/support/`、独立评测 CLI |
| 前置依赖 | 自动化仍只用 Fake/确定性模型；真实模型运行继续遵守 R3 |
| 验收标准 | 覆盖跨商家、提示注入、虚构 ID、超预算、数据源失败、审批绕过；CI 不产生模型费用 |

## 六、P1：新增商家产品能力

### P1-1 主动经营告警中心

| 项目 | 内容 |
| --- | --- |
| 来源 | Shopify `alerts.py`、`thresholds.json` 与 merchant overview |
| 结论 | 适配 |
| 用户价值 | 商家不必先知道要问什么，系统主动指出需要处理的问题 |
| 首批告警 | 低库存、滞销商品、退款异常、延迟发货订单、指标突降、待审批变更 |
| 核心原则 | 告警由确定性规则和可信数据生成；LLM 只解释影响、建议优先级和生成行动草稿 |
| 建议落点 | 新增告警领域模型、Repository、Service、API；前端新增“经营待办/告警”视图 |
| 验收标准 | 阈值可配置且有版本；每条告警显示依据、时间窗和数据更新时间；无数据不能伪装成零 |

### P1-2 可解释阈值和告警规则管理

| 项目 | 内容 |
| --- | --- |
| 来源 | Shopify 文件化 `AlertRules` |
| 结论 | 适配 |
| 增强内容 | 阈值从代码常量升级为平台默认值 + 商家覆盖值；保留变更人、版本和生效时间；提供预览命中数量 |
| 建议落点 | PostgreSQL 新表、管理员/商家配置 API、前端设置页 |
| 验收标准 | 配置修改不影响其他商家；非法阈值被拒绝；规则版本可追溯 |

### P1-3 变更草稿台账

| 项目 | 内容 |
| --- | --- |
| 来源 | Anthropic staged changes；Shopify staging ledger |
| 结论 | 采纳 |
| 用户价值 | Agent 从“只给建议”升级为“生成可审阅、可执行的行动草稿” |
| 首批草稿 | 商品标题/描述优化、库存补货建议、价格调整建议、优惠券/促销方案、工单处理建议 |
| 状态 | `DRAFT → PENDING_APPROVAL → APPROVED → APPLYING → APPLIED / FAILED / EXPIRED / DISCARDED` |
| 安全要求 | 草稿生成阶段零业务写入；保存 before/after、依据、影响对象、风险、创建人和过期时间 |
| 建议落点 | 新 ORM/Alembic/Repository/Service/API；不得塞进现有回答表 |
| 验收标准 | 创建草稿不会修改经营数据；状态转换受后端约束；所有读取按 `merchant_id` 隔离 |

### P1-4 审批工作台与变更预览卡

| 项目 | 内容 |
| --- | --- |
| 来源 | Anthropic host approval 与 change preview UI |
| 结论 | 采纳 |
| 增强内容 | 在 Vue 前端展示变更前后对比、数据依据、影响范围、风险提示、批准/拒绝；聊天中的“我同意”不能代替按钮审批 |
| 建议落点 | 新 Vue View/Store/API Adapter；聊天回答只返回草稿引用和摘要 |
| 前置依赖 | P1-3 变更台账、可信用户身份；MVP 演示 Token 不开放真实写入 |
| 验收标准 | 预览本身不产生批准；只有有权限的操作人能批准；重复点击保持幂等 |

### P1-5 经营分析委派器

| 项目 | 内容 |
| --- | --- |
| 来源 | Anthropic merchant analysis delegate |
| 结论 | 适配 |
| 增强内容 | 将复杂多指标分析拆为受预算约束的只读子任务；主 Agent 提交结构化 brief，委派器只能调用安全查询和指标工具，返回结构化结论与来源 |
| 不采用 | 不允许子 Agent 执行任意 SQL，不默认启用托管代码执行，不绕过现有 LLM 调用上限 |
| 建议落点 | `backend/app/services/analysis_delegate.py`，复用 `safe_query.py` 和 `LlmBudget` |
| 验收标准 | 子任务调用次数、总耗时和结果行数有上限；不能扩大写入 provenance；失败时回到普通分析并显式降级 |

### P1-6 生成式经营卡片

| 项目 | 内容 |
| --- | --- |
| 来源 | Anthropic/Shopify product、comparison、plan、change cards |
| 结论 | 适配 |
| 首批卡片 | 告警卡、指标对比卡、商品表现卡、订单问题卡、行动计划卡、变更预览卡 |
| 数据规则 | 卡片字段由服务端可信数据回填；前端只消费受控领域模型，不直接渲染模型 HTML |
| 建议落点 | 后端 presentation registry；前端 `types/`、Adapter、Store 和新组件 |
| 验收标准 | SSE 与普通 JSON 共享同一最终契约；双语、移动端、加载/降级状态均覆盖测试 |

### P1-7 “从洞察到行动”的闭环追踪

| 项目 | 内容 |
| --- | --- |
| 来源 | Shopify metrics → alerts → staged change → apply → refresh |
| 结论 | 采纳 |
| 增强内容 | 将回答、告警、草稿、审批、执行和执行后指标关联起来；展示建议是否被采纳以及行动后的指标变化 |
| 建议落点 | 变更台账关联 `answer_id`/`alert_id`；Chat BI 增加闭环转化指标 |
| 验收标准 | 能追溯“为什么建议、谁批准、执行了什么、结果如何”；不把相关性描述成因果性 |

## 七、P2：平台连接与受控执行

### P2-1 `MerchantBackend` 式统一连接器接口

| 项目 | 内容 |
| --- | --- |
| 来源 | Anthropic `MerchantBackend`；Shopify `shopify_backend.py` |
| 结论 | 采纳 |
| 增强内容 | 在 Borough 业务服务与外部平台之间增加能力导向 Protocol：商品、库存、订单、价格、促销、活动；连接器负责凭证、API 版本、重试、限流和字段映射 |
| 设计要求 | Agent 不接触平台 Token；工具参数不接受 `merchant_id`；身份由服务端上下文注入 |
| 建议落点 | 新增 `backend/app/connectors/`，平台实现与领域接口分离 |
| 验收标准 | Fake Connector、Local Connector、真实 Sandbox Connector 通过同一契约测试 |

### P2-2 Shopify 只读连接器

| 项目 | 内容 |
| --- | --- |
| 来源 | Shopify Admin GraphQL transport、catalog/order cache、ShopifyQL |
| 结论 | 适配 |
| 首批范围 | 商品、变体、库存、订单、退款和基础经营指标；不包含任何 mutation |
| 凭证 | 服务端加密存储或密钥服务；按商家隔离；不进入模型、浏览器、普通日志和 API 响应 |
| 建议落点 | `connectors/shopify/`、连接配置表、后台授权流程 |
| 验收标准 | 缺 scope 时明确关闭对应能力；分页、速率限制、API 版本和过期凭证有可观察错误；跨商家访问测试通过 |

### P2-3 Shopify 商品、库存与价格受控写入

| 项目 | 内容 |
| --- | --- |
| 来源 | Shopify `staging.py`、Admin mutations、approval route |
| 结论 | 适配 |
| 开放顺序 | 商品文案 → 库存 → 价格；促销和营销活动最后评估 |
| 强制链路 | 读取当前值 → 创建草稿 → 人工审批 → 应用前重读 → 二次 guardrail → 幂等 mutation → 回读验证 → 审计 |
| 风险控制 | 价格变化比例、补货数量、目标数量、批量对象数和受保护字段均由后端配置限制 |
| 验收标准 | 模型工具不能直接触达 mutation；旧值变化时拒绝或重新审批；一次批准最多产生约定数量的 mutation |

### P2-4 幂等、乐观并发和部分失败处理

| 项目 | 内容 |
| --- | --- |
| 来源 | Shopify inventory idempotency、`changeFromQuantity`、partial apply reporting |
| 结论 | 采纳 |
| 增强内容 | 每次执行携带幂等键；应用前比较当前值/版本；多目标操作逐项记录成功和失败；失败不伪装成全量成功，也不盲目自动回滚外部系统 |
| 建议落点 | 变更执行器、审计日志、连接器错误模型 |
| 验收标准 | 重放请求不重复写；库存被其他操作改变后旧草稿不能覆盖；部分成功结果完整可见并可重试失败项 |

### P2-5 促销和营销活动草稿

| 项目 | 内容 |
| --- | --- |
| 来源 | Anthropic pricing/promotions、marketing campaigns；Shopify ledger-only changes |
| 结论 | 先草稿，后评估写入 |
| 增强内容 | Agent 可生成目标人群、预算、时间窗、优惠结构、渠道文案和预期指标，但默认只进入台账，不自动创建真实广告或折扣 |
| 前置依赖 | 预算审批、渠道所有权、合规规则和真实平台 API 另行设计 |
| 验收标准 | 页面明确显示“草稿/未发布”；预算上限后端校验；文案和行动分开审批 |

## 八、明确不照搬的模式

| 上游模式 | 决策 | 原因 |
| --- | --- | --- |
| 将 Claude/Anthropic SDK 作为 Borough 唯一运行时 | 拒绝 | 当前唯一约定提供商是 DeepSeek，继续通过 `LlmClient` 抽象接入 |
| 用 Agent SDK/Claude Code CLI 承载生产 Web 请求 | 拒绝 | 进程模型、凭证和可观察性不符合当前部署边界 |
| 任意 SQL 或托管代码执行 | 拒绝 | 违反 R4；继续使用结构化意图、白名单和后端模板 |
| 无鉴权 Demo 路由 | 拒绝 | 违反 R5；所有经营数据必须绑定可信身份和 `merchant_id` |
| 内存 Session、内存台账、JSON 文件持久化 | 拒绝 | Railway 重启和多副本不可靠，必须使用 PostgreSQL/Redis |
| 把平台 Token 交给模型或前端 | 拒绝 | 违反 R6；凭证只存在于服务端连接器 |
| React/Next.js 全量迁移 | 拒绝 | 现有 Vue 架构成熟，只借鉴交互和领域模型 |
| 聊天文本直接视为审批 | 拒绝 | 审批必须来自独立、鉴权的宿主界面操作 |
| 模型直接生成任意 UI/HTML | 拒绝 | 只允许受控组件类型和服务端回填数据 |
| 自动付款、下单或无审批发布 | 拒绝 | 风险过高且不属于当前商家 Data Agent 核心范围 |

## 九、推荐实施顺序

```text
阶段 A：可信 Agent 基座
  P0-1 Fencing
  → P0-2 工具注册表
  → P0-4 Grounding
  → P0-3 Provenance
  → P0-6 Session 并发
  → P0-7 场景评测

阶段 B：主动经营与可视化
  P1-1 告警中心
  → P1-2 阈值管理
  → P0-5 服务端 UI 回填
  → P1-6 经营卡片

阶段 C：建议到审批
  P1-3 变更台账
  → P1-4 审批工作台
  → P1-7 闭环追踪
  → P1-5 受限分析委派器

阶段 D：外部平台执行
  P2-1 连接器接口
  → P2-2 Shopify 只读
  → P2-4 幂等与并发保护
  → P2-3 受控写入
  → P2-5 促销/活动草稿
```

阶段 A 不依赖外部平台，应优先完成。阶段 B 可以完全基于 Borough 当前 PostgreSQL 数据实现。
阶段 C 的草稿和审批可以先只作用于 Borough 内部演示数据。只有真实身份、完整审计、凭证管理、
Sandbox 验收和回滚/补偿策略全部完成后，阶段 D 才能开放生产写入。

## 十、候选任务总表

| ID | 任务 | 优先级 | 价值 | 主要风险 | 推荐状态 |
| --- | --- | --- | --- | --- | --- |
| P0-1 | 第三方内容 Fencing | P0 | 高 | 清洗误伤业务文本 | 建议立项 |
| P0-2 | 动态工具白名单 | P0 | 高 | 工具元数据重复 | 建议立项 |
| P0-3 | 数据/操作 Provenance | P0 | 高 | 会话状态复杂度 | 建议立项 |
| P0-4 | 强制 Grounding | P0 | 高 | 过度拦截可回答问题 | 建议立项 |
| P0-5 | 服务端 UI 数据回填 | P0 | 中高 | 契约扩展 | 随经营卡片实施 |
| P0-6 | Session 并发控制 | P0 | 高 | 事务与兼容性 | 先审计再立项 |
| P0-7 | Agent 场景评测 | P0 | 高 | 场景维护成本 | 建议立项 |
| P1-1 | 主动经营告警中心 | P1 | 高 | 误报和数据时效 | 建议优先新增 |
| P1-2 | 阈值管理 | P1 | 中 | 配置复杂度 | 告警 MVP 后增加 |
| P1-3 | 变更草稿台账 | P1 | 高 | 状态机和审计 | 建议新增 |
| P1-4 | 审批工作台 | P1 | 高 | 权限和误操作 | 随台账新增 |
| P1-5 | 经营分析委派器 | P1 | 中 | 调用成本和复杂度 | 基座稳定后评估 |
| P1-6 | 生成式经营卡片 | P1 | 中高 | 契约膨胀 | 小集合起步 |
| P1-7 | 洞察到行动闭环 | P1 | 高 | 因果误判 | 台账稳定后增加 |
| P2-1 | 统一连接器接口 | P2 | 高 | 抽象过早 | 以 Shopify 只读需求驱动 |
| P2-2 | Shopify 只读连接器 | P2 | 高 | Scope、限流、版本 | Sandbox 先行 |
| P2-3 | Shopify 受控写入 | P2 | 高 | 真实业务损失 | 最后开放 |
| P2-4 | 幂等与并发保护 | P2 | 高 | 外部状态不一致 | 写入前置门槛 |
| P2-5 | 促销/活动草稿 | P2 | 中 | 预算与渠道合规 | 先只做草稿 |

## 十一、每阶段统一验收门槛

### 11.1 产品与契约

- 新功能先进入 `docs/PRD.md`，再更新精确契约和开发计划；
- 中英文文案、空状态、错误状态、降级状态同步定义；
- 页面不得把模拟、缓存或规则结果描述为实时平台数据；
- 所有新能力都能从 UI 看出数据来源、更新时间和执行状态。

### 11.2 安全与数据

- 身份校验和 `merchant_id` 隔离早于任何查询或写入；
- 模型不能决定商家身份、凭证、SQL、审批标记或 guardrail 上限；
- 写操作必须保存 before/after、操作者、来源、审批、执行结果和错误；
- 外部凭证不进入模型、浏览器、日志、测试 fixture 或构建产物；
- 所有降级继续使用现有 `analysis_sources`、`quality_status`、`quality_notes`、`degraded`、
  `degraded_reason` 契约表达。

### 11.3 测试与发布

- 自动化测试只使用 Fake LLM，不产生模型费用；
- Agent 场景测试、API 契约测试、Repository 隔离测试和前端交互测试成套增加；
- 外部连接器至少具备 Fake Transport、Local/Sandbox、Live Smoke 三层验证；
- Live Smoke 只能针对开发商店和可逆数据，执行前另行确认凭证、次数和影响范围；
- 写入功能上线前必须完成幂等、并发、部分失败、超时、限流和凭证失效测试；
- Railway 部署继续执行严格 CORS、健康检查、单请求调用上限和每日预算熔断。

## 十二、开工时需要同步的文件

| 变更类型 | 必须检查/更新 |
| --- | --- |
| 产品范围 | `docs/PRD.md` |
| Chat/API 字段 | `docs/backend-development-plan.md` §8、Pydantic Schema、OpenAPI、`generated.ts`、Adapter |
| Agent 流程 | `backend/app/agent/graph.py`、`state.py`、`prefilter.py`、相关测试 |
| 数据表 | ORM → Alembic → Repository → `docs/database.md` |
| 告警/指标 | `backend/app/metrics/`、安全查询、指标文档、前端卡片 |
| 前端功能 | 领域类型 → Adapter → Store → Vue 组件 → Vitest/Playwright |
| 外部连接器 | 凭证配置、商家隔离、审计、限流、错误映射、Sandbox 测试、部署文档 |
| 阶段完成 | `docs/project-progress.md` 当前快照 |

## 十三、建议首先形成的三个独立 Change

为控制范围，不建议把整份路线图作为一个超大实施计划。首轮可拆成三个互不混杂的 Change：

1. **Agent Trust Foundation**：P0-1、P0-2、P0-3、P0-4、P0-7；
2. **Merchant Alert Center**：P1-1、P1-2、P0-5、P1-6 的告警卡子集；
3. **Staged Merchant Actions**：P1-3、P1-4、P1-7，复用第一个 Change 建立的 provenance 基础。

推荐先做第一个 Change。它不需要新增外部平台或真实写权限，却能为附件、连接器、主动告警和执行型
Agent 提供共同的安全基础。完成并验证后，再决定告警中心与变更台账的先后顺序。
