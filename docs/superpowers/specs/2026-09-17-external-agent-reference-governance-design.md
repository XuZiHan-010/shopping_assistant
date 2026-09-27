# 外部 Agent 参考项目登记与治理设计

## 1. 背景与目标

Borough 商家 AI 助手在继续以 `yshopping-merchant-ai 4/` 作为业务行为与视觉还原基准的同时，
引入 Anthropic 和 Shopify 的两个开源电商 Agent 项目作为辅助架构参考。

本次工作的目标是：

- 在项目文档中登记两个上游仓库的源码地址、只读本地副本和固定提交；
- 明确它们只提供 Agent 架构、工程治理和安全模式方面的参考，不改变现有需求权威关系；
- 建立一份可持续维护的对照审计，记录 Borough 对上游模式的采纳、适配或拒绝决定；
- 为后续研究提供稳定入口，避免只凭 README 或二手描述作出设计判断。

## 2. 不在本次范围内

- 不修改产品范围、接口契约、数据库结构或前后端运行代码；
- 不把两个上游项目加入 Borough 的构建依赖或 Git 子模块；
- 不改变 `yshopping-merchant-ai 4/` 作为业务行为与视觉唯一还原基准的地位；
- 不改变 DeepSeek 作为当前唯一约定云端 LLM 提供商的约束；
- 不执行真实 LLM 调用、生产变更或 Git 发布操作；
- 不因上游示例存在某项能力，就自动把该能力纳入 Borough 产品范围。

## 3. 参考项目登记

| 项目 | 上游仓库 | 本地只读副本 | 固定提交 | 许可证 | 主要研究方向 |
| --- | --- | --- | --- | --- | --- |
| Anthropic Commerce Agents | <https://github.com/anthropics/commerce-agents> | `D:\vscode html\merchant_assistant-research\github\anthropic-commerce-agents` | `fd4d59224ab96b43c6dc6888207c67b3bd5a24cf` | Apache-2.0 | Merchant Agent 蓝图、安全边界、工具调用、状态/记忆、流式交互与变更闸门 |
| Shopify Claude for Commerce Examples | <https://github.com/Shopify/claude-for-commerce-examples> | `D:\vscode html\merchant_assistant-research\github\shopify-claude-for-commerce-examples` | `d68c7fa24f26ab138d8b4ccdd0488db140a6bfe6` | Apache-2.0 | Shopify Admin API 接入、指标与告警、变更暂存、审批执行和集成测试 |

本地副本位于 Borough 工作区之外，保持只读研究用途。更新副本时必须先记录新的提交号，随后同步更新
项目导航和对照审计，避免文档与实际研究版本漂移。

## 4. 权威关系与冲突处理

新增参考项目不改变现有权威顺序：

1. `AGENTS.md` 的安全与架构硬约束（R1–R9）始终优先；
2. `yshopping-merchant-ai 4/` 仍是业务行为与视觉的还原基准；
3. `docs/PRD.md`、聊天契约和开发计划按现有文档权威关系执行；
4. Anthropic 与 Shopify 项目仅是辅助架构参考，用于寻找可验证的设计模式和实现思路。

当外部项目与 Borough 现有规则冲突时，不能直接照搬。必须先按现有权威顺序判断，并在对照审计中记录：

- `采纳`：模式与 Borough 约束一致，可以直接采用其核心思想；
- `适配`：思想有价值，但必须调整技术栈、鉴权、数据隔离、模型供应商或查询方式；
- `拒绝`：与产品范围或硬约束冲突，明确说明不采用的理由。

## 5. 文档变更设计

### 5.1 `AGENTS.md`

新增外部 Agent 参考入口和稳定约束，内容包括：

- 两个 GitHub 仓库地址；
- 本地只读副本路径；
- 它们是辅助架构参考，不是需求基准；
- 上游设计不得覆盖 R1–R9、`yshopping` 还原基准或现有接口契约；
- 研究结论统一写入 `docs/external-agent-reference-audit.md`。

不把完整研究清单写进 `AGENTS.md`，以免稳定约束文件膨胀为流水账。

### 5.2 `docs/project-navigation.md`

在参考项目章节增加两个条目，登记：

- 上游地址、本地路径、固定提交和许可证；
- 适合优先阅读的目录或文件；
- 与 Borough 的用途边界；
- 对照审计文档的入口。

### 5.3 `docs/external-agent-reference-audit.md`

新建持续维护的研究审计，至少包含：

- 来源版本和读取入口；
- 上游模式的事实描述及对应源码位置；
- Borough 当前实现或约束；
- `采纳 / 适配 / 拒绝` 结论；
- 后续可能形成的独立需求或实施项，但不在审计文档中直接扩大产品范围。

首轮重点研究：

- Anthropic：安全文档、Merchant Agent 核心流程、grounding/gates、记忆、流式响应；
- Shopify：merchant 示例说明、Shopify 后端适配、metrics、alerts、staging 及测试。

### 5.4 `docs/project-progress.md`

更新快照日期，记录两个外部参考项目已经固定版本并开始对照研究；将后续的架构对照审计列为当前工作，
但不宣称任何业务功能已因此实现。

## 6. 研究与采用流程

后续在相关功能开工前，按以下流程使用外部参考：

1. 先查 `docs/external-agent-reference-audit.md` 是否已有对应结论；
2. 阅读固定提交中的具体源码、测试或文档，不仅依赖 README；
3. 对照 Borough 的产品需求、安全规则和当前实现；
4. 给出 `采纳 / 适配 / 拒绝` 结论及证据；
5. 如果结论会改变产品范围，先修改 PRD 和相应计划，再进入实现；
6. 实现完成后，把验证结果和最终差异回填到审计与项目进度。

## 7. 不可直接照搬的模式

- 上游对 Claude 或 Anthropic SDK 的直接依赖，不得替换 Borough 的 DeepSeek 接入约束；
- 允许模型生成或执行任意 SQL 的方案，不得突破 R4 的结构化意图、白名单和后端模板限制；
- 缺少可信身份或商家隔离的演示路径，不得用于 Borough 经营数据；
- 把密钥、完整业务数据、完整查询结果或敏感 Prompt 交给日志或模型的做法不得采用；
- 商品、价格、库存等写操作即使上游已有示例，也必须另行进入 Borough 的产品范围、审批和审计设计；
- 上游中的英文品牌文案、数据模型和平台专属概念不能直接覆盖 Borough 的双语与业务契约。

## 8. 验证标准

文档修改完成后需要验证：

- 两个本地副本存在，远端地址、固定提交和许可证信息与登记一致；
- `AGENTS.md`、项目导航、对照审计和项目进度中的地址与提交号一致；
- 文档明确保留 `yshopping` 的需求基准地位和 R1–R9 的优先级；
- 文档没有把上游功能误写成 Borough 已实现能力；
- Markdown 链接、标题层级和表格可读；
- `git diff --check` 不报告空白或补丁格式问题；
- 本次仅修改文档，因此无需运行应用测试；若后续据此修改代码，再按改动范围补充测试。
