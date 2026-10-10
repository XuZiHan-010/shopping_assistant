# 实施计划：真实模型评测遗留缺陷整改

**日期**：2026-10-10 ｜ **规格**：[spec.md](spec.md)

项目没有初始化 Spec Kit（无 `.specify/scripts` 与模板），本计划按 `speckit-plan` 的结构手工编写；
研究结论、设计与验证办法合并在本文件，不另拆 `research.md` / `data-model.md` / `quickstart.md`。
本次不改任何对外接口字段，因此没有 `contracts/`。

## 摘要

五项整改都落在后端 v2 工具循环及其周边，前端与接口契约不变：

1. 压缩：小结果原样保留；保留记录改标题、加调用序号、补知识文档出处；摘要策略同规则。
2. 触顶收尾：工具调用或轮数触顶时，用剩余预算做一次不带工具的作答。
3. 商品搜索：固定的英文到中文检索词表，另加品类列匹配。
4. 规则文档：新增 Borough 自有的规则种子，补入成文的平台售后规则。
5. 记忆：补一条固定真实模型输出的回归用例（判定逻辑已在）。

## 技术背景

- **语言与依赖**：Python 3.12、FastAPI、SQLAlchemy 2、Pydantic v2；不新增依赖。
- **存储**：PostgreSQL；不改表结构，无迁移。规则文档经现有 `knowledge_documents` 的「不存在才插入」落库。
- **测试**：pytest，全部使用脚本化 / Fake 模型与一次性库。
- **约束**：不改 LLM 调用次数的预算公式（`agent_loop_llm_call_floor`），线上可能显式配置了 `AGENT_LOOP_MAX_LLM_CALLS=12`，公式加一会让启动校验失败。

## 硬约束核对（AGENTS.md R1–R9）

| 规则 | 本次如何满足 |
| --- | --- |
| R2 Git 发布 | 不提交、不推送 |
| R3 真实 LLM | 不发起任何真实调用；真实复测列为待授权事项 |
| R4 模型不决定数据 | 搜索词表、保留记录、规则条款全部由后端确定性给出 |
| R5 隔离 | 搜索仍按会话的 `merchant_id` 过滤；保留记录只按字段白名单取值，身份字段不进 |
| R7 降级可见 | 收尾作答带 `degraded` / `degraded_reason=LIMIT` 与可见说明；无正文时说明如实 |
| R8 只读目录 | 不动参考 Wiki 与其镜像 `wiki_seed.json`（有漂移检查）；规则写在 Borough 自有种子里 |
| R9 PRD 范围 | 五项均为 PRD 已有能力（A5 压缩、A2 循环上限、C2 导购、S4 售后、M11 记忆）的缺陷修复 |

设计后复核：无违反项。

## 研究结论

### D1 清理策略：按体量决定清谁

- **决定**：较早轮次里的工具结果，正文长度不超过「触发阈值的四分之一」（默认 2,000 字符）的原样保留，只清理超过的。
- **理由**：占位加保留记录本身就有三四百字，清掉一条一两千字的结果省不下多少，却会丢掉实体详情这类后续步骤要用的事实；售后回合正是这样失败的。Anthropic 的上下文编辑里也有同类设计（`clear_at_least`：清理收益不够就不清）。
- **放弃的方案**：
  - *每个工具声明要保留哪些事实字段*：要逐个工具维护，新工具默认仍会中招。
  - *调高触发阈值*：只是把问题推后，且改变已冻结评测的前提。
  - *按体量从大到小清到够用为止*：售后回合里最大的两条在受保护的最近两轮，清不到，救不了详情。
- **上限**：单回合最多 16 次工具调用，最多多留约 3.2 万字符；单请求 token 上限（120,000）与预算守卫不变。

### D2 保留记录的写法

- 小标题「工具来源」改为「已保留的调用记录」，字段名「数据来源」不变——真实评测原文里模型就是照着「工具来源」这个标题把工具名写成了来源。
- 清理占位写明「本回合第 N 次工具调用」，N 取自完整结果列表里的位置。
- 知识检索类结果（载荷含 `documents` 列表）额外保留每篇的 `title` 与 `citation`，最多 5 篇；仍是字段白名单。
- 草稿结果很短，按 D1 原样保留，编号、类型、版本各有字段名，不再经过保留记录这一道转写。

### D3 摘要策略同规则

较早轮次里，工具结果全部不超过阈值的轮整轮原样保留（与已有的「含受信 Skill 的轮原样保留」同一处理），其余照旧交给摘要。

### D4 触顶收尾

- **决定**：模型请求的调用会超过工具调用上限、或在最后一轮仍要调工具时，不执行这批调用；给每个调用回一条「未执行，已达上限」的工具结果，再发一次不带工具的模型调用，系统提示末尾临时追加收尾说明。回答照常过确定性校验与 Reviewer，最终带 `LIMIT` 降级与说明。
- **结构合法性**：每个 `tool_call` 都有对应的工具结果，不插入额外的 user 消息——两种协议适配器都要求工具结果紧跟调用、角色交替。
- **预算**：只用回合剩余预算。收尾或其后的校验因预算、超时、上游异常走不完时，回退为今天的行为（只给说明）。
- **放弃的方案**：*把最后一轮固定为不带工具*——会让「最后一轮正常作答」与「被迫收尾」无法区分，前者不应标降级。
- **说明文案**：有正文时用「以下回答仅基于已查到的部分结果」；没有正文时（含超时、预算触顶）改为「本次未能完成回答」，不再写「以下」。

### D5 商品搜索

- **决定**：新增固定词表（英文商品词 / 材质词 / 品类词 → 中文检索词），查询词里的英文单词经小写与简单单复数归一后查表，展开出的中文词与原词一起做包含匹配；展开词的匹配列加上 `category`。品类词（如 women → 女装）范围很宽，只在没有任何商品词命中时才用，免得把具体商品挤出结果。
- **理由**：与闸门里已有的「英文业务词反查中文」（`zh_business_terms_for_english_word`）同一思路，零模型调用、结果可复现。
- **放弃的方案**：*给商品加英文名*（要改表、改种子、改两端展示，超出缺陷修复）；*调模型翻译查询*（每次搜索多一次调用，且不确定）。
- **兜底**：英文关键词无结果时，给模型的说明里提示商品名称为中文。

### D6 规则文档

- **决定**：新增 `backend/app/knowledge/borough_rules.py`，以 Python 常量保存 Borough 自有规则文档；`seed_wiki_documents` 在镜像种子之后一并「不存在才插入」。首篇为《Borough 平台售后规则（退货退款）》，路径 `业务/退货/业务流程/Borough平台售后规则.md`（知识后台只接受 `业务/<域>/<四个固定板块>/<文件>` 四段路径；路径含「退货」，顾客与商家两端可见），分类 `REFUND`，标记完整。标题带「退货退款」是为了在标题加权的检索里排到同域骨架文档之前。顾客端 `get_shop_policy` 另把标记完整的文档排在骨架之前。
- **内容来源**：`after_sale_eligibility.py`（签收后七天、未签收只受理仅退款或工单、不可重复申请）、`after_sales.py`（首次响应 24 小时）、`after_sale_decision.py`（拒绝须附条款、确认收货须标记可否二次销售、金额由后端计算）。第五章「审核标准」没有对应代码，是新写的演示准则，待用户审阅。
- **为什么不改镜像种子**：`wiki_seed.json` 必须与只读参考 Wiki 逐字节一致（`scripts/check_wiki_seed.py`）。
- **为什么不覆盖骨架**：落库是「不存在才插入」，线上已有的骨架行不会被替换；新路径的文档下次启动即补入。
- **评测隔离**：`load_wiki_seed_entries()` 不变，RAG 评测语料（21 篇）与其冻结指标不受影响。

### D7 记忆

判定逻辑不动。新增回归用例：把 2026-10-05 真实运行里模型对 MEM-016 返回的两条候选原样喂给评测的 `evaluate()`，断言错误写入为 0。

### D8 压缩评测口径

- 提示词里「工具来源」改为「数据来源」（与评分检查的内容一致）。
- 身份陷阱：只检查压缩**新写入**的消息与回答，不检查原样保留的原消息——原消息本来就在上下文里，保留它不构成新的泄露。
- 口径版本记为 v3；此后的真实结果与 13/24 不可直接比较。

## 改动范围

```text
backend/app/agent/loop/compaction/__init__.py     最小可清理长度
backend/app/agent/loop/compaction/pruning.py      小结果保留、调用序号
backend/app/agent/loop/compaction/anchors.py      标题、知识文档出处
backend/app/agent/loop/compaction/summarization.py 小结果轮原样保留
backend/app/agent/loop/runner.py                  触顶收尾、说明文案
backend/app/tools/customer/catalog.py             搜索词展开、品类列
backend/app/tools/customer/search_terms.py        新增：检索词表
backend/app/knowledge/borough_rules.py            新增：自有规则文档
backend/app/knowledge/wiki_seed.py                一并落库
backend/app/eval/compaction_e5.py、compaction_e5_model.py  口径 v3
backend/tests/unit/agent/loop/test_compaction_small_results.py、test_runner.py
backend/tests/unit/tools/test_customer_search_terms.py
backend/tests/unit/knowledge/test_borough_rules.py
backend/tests/integration/v2/test_shop_chat.py、tests/eval/test_n4_memory_e5_fake.py
docs/backend-development-plan.md §6.10、§6.12      循环与压缩规则同步
docs/project-progress.md                           快照
```

## 验证办法

```powershell
cd backend
uv run pytest tests/unit/agent tests/unit/memory tests/unit/knowledge tests/unit/tools tests/eval -q
uv run ruff check .
uv run mypy app
# 需要本地一次性 PostgreSQL（pgvector 镜像）时：
$env:REQUIRE_INTEGRATION_DB = "1"; uv run pytest -q
```

预期：新增用例先红后绿；既有用例里断言旧文案或旧清理行为的按新规则更新并说明原因。
真实模型下的效果（售后端到端、来源保留率、英文搜索、穿搭类提问）本计划不验证，须另取 R3 授权。
