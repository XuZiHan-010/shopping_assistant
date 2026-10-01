# N4 上下文压缩实施计划

> **给执行者：** 用 `superpowers:executing-plans` 逐任务推进。步骤用 `- [ ]` 复选框跟踪。
> **本计划不含任何 Git 提交步骤**（R2）。自动化测试全程 Fake LLM，零费用。
> **真实模型下的两策略对比（Task 5 步骤 3）需 R3 单独授权。**

**目标：** 实现 PRD A5：两种压缩策略都实现用于对比，**生产选定一种确定策略**，
并完成 E5 压缩专项评测。

**架构：** 压缩发生在工具循环内部，**不单独建目录**，随 `app/agent/loop/` 实现
（`docs/project-navigation.md` §5.3.1）。两种策略实现同一接口，由配置选择；
未被选中的策略保留在 `app/eval/` 供回归。

**技术栈：** Python 3.12、pytest。

**规格来源：** PRD A5、E5；融合决策 Q19；后端计划 §6.10（预算公式）、§6.12。

> **2026-09-27 编组修订**（见 `plans/2026-09-27-n4-module-roadmap.md` §二）：核对 N3 实际代码发现，
> `LoopRequest` 有 `history` 字段，但 `services/v2/shop_chat.py`、`merchant_chat.py` 构造请求时**都不传**——
> v2 每一回合只带本轮用户消息，跨回合对话根本不进上下文。本计划原设想的「长对话压缩」因此没有对象。
> 新增 **Task 0 多轮历史回放**（D-N4-1，**2026-09-28 用户裁定采纳推荐方案**，见 Task 0），并在 Task 1 增加跨回合锚点来源一步。
> 已在位：`compaction_max_calls`（默认 1）与 `AGENT_LOOP_MAX_LLM_CALLS` 公式校验（`app/core/config.py:29`、`:263`）；
> 尚缺：`COMPACTION_STRATEGY`、`COMPACTION_TRIGGER_TOKENS`。

---

## 入口条件

> **预写计划不是已验证实现。** 本计划写于上游代码尚不存在时，文中引用的类名、函数签名、
> 工具名、表字段、错误码都是**当时的设计**。开工前逐项对照上游**实际落地**的接口；
> 不一致时先按 PRD → 契约 → 计划的顺序修正，**再动代码**，不得在实现里默默适配或绕过。

- [x] `n2-tool-loop-and-registry` 已完成，且 `AGENT_LOOP_MAX_LLM_CALLS` 的公式校验在位；
- [x] N3 两份 Skill 计划已完成——多轮、多工具的真实对话形态要等 Skill 就位后才有代表性；
- [x] **核对 §6.12 的 `CompactionStrategy` 与本计划一致**；
- [x] **D-N4-1（多轮历史回放）已由用户裁定**（2026-09-28，采纳推荐方案，内容见 Task 0）；
      写入 PRD A5 与契约 §8.8.3 / §8.9.3 是 Task 0 步骤 1，已于 2026-09-28 完成。

---

## 全局约束

- 中文（R1）；**不执行 Git 操作**（R2）；**不调用真实 LLM**（R3）。
- **压缩后必须保留三项**：工具来源、数据截至时间、草稿版本（A5）。
- **旧对话摘要是模型生成内容，不得升级为事实来源**（A5）。
- **身份保存在服务端可信上下文，不塞进提示词**（A5）。

---

## 为什么这三项必须保留

| 丢了 | 后果 |
| --- | --- |
| 工具来源 | 下游确定性校验无法判断"这个数字是哪个工具给的"，只能判为无来源 → 降级 |
| 数据截至时间 | M3 要求每个指标回答都带截至时间；压缩后丢了，回答就不合规 |
| 草稿版本 | D9⑦ 批准绑定草案版本；丢了版本，模型可能引用一个已被修改的草稿 |

所以压缩**不是"让上下文变短"那么简单**——它必须是**结构感知**的。

---

## 文件结构

| 文件 | 责任 |
| --- | --- |
| `backend/app/agent/loop/compaction/__init__.py` | `Compactor` 协议 |
| `backend/app/agent/loop/compaction/pruning.py` | `TOOL_RESULT_PRUNING` |
| `backend/app/agent/loop/compaction/summarization.py` | `SUMMARIZATION` |
| `backend/app/agent/loop/compaction/anchors.py` | 三项必保留信息的提取与回填 |
| `backend/app/core/config.py` | `COMPACTION_STRATEGY`、`COMPACTION_TRIGGER_TOKENS`、`COMPACTION_MAX_CALLS`、`CHAT_HISTORY_MAX_TURNS`（Task 0） |
| `backend/app/services/v2/shop_chat.py`、`merchant_chat.py` | Task 0：按会话读取最近 N 轮并构造 `LoopRequest.history` |
| `backend/app/eval/datasets/compaction/` | E5 压缩评测集 |

---

### Task 0：多轮历史回放（2026-09-27 编组新增；D-N4-1 于 2026-09-28 裁定）

现状：两端 Chat 服务只把本轮消息交给循环；已持久化的只有用户消息与最终响应（`messages.response_payload`），
**工具结果不落库**。因此回放只可能是「用户话 + 助手最终回答」的文字，跨回合的工具来源、截至时间、草稿版本
只能从已持久化的响应字段里取（见 Task 1 步骤 0）。

**裁定方案（2026-09-28 用户采纳）：**

1. 回放**同一会话**最近 N 轮的用户与助手文字，N 由新配置 `CHAT_HISTORY_MAX_TURNS` 控制，默认 6；
   E5 压缩评测后可按数据调整默认值，调整须同步 §6.12；
2. 顾客原话按 A11 照常围栏；
3. **不回放工具结果与推理内容**（工具结果未持久化；跨协议回放已被 §6.17 禁止）；超出 N 轮的部分交给本计划的压缩；
4. **回放的助手旧回答属于模型生成内容，与压缩摘要同一性质**：模型若直接引用其中的数字而不重新调用工具，
   下游确定性校验一律视为**无来源**并按降级处理。否则历史回放会成为绕过 R4「数字必须来自工具」的后门。

- [x] **步骤 1：契约先行**——把上述四条写入 PRD A5 与后端计划 §8.8.3 / §8.9.3（回放范围、条数上限、围栏规则、
      历史数字无来源），并在 §6.10 登记 `CHAT_HISTORY_MAX_TURNS`；再改代码；本步不新增对外字段
      （2026-09-28 已完成：PRD A5、§15 N4；后端计划 §6.10 输入、§6.12 规则与必测、§8.8.3、§8.9.3）
- [x] **步骤 2：写失败测试 → 实现 → 确认通过**——第二轮请求的出站消息含第一轮文字；超过 N 轮只回放最近 N 轮；
      跨会话、跨角色不回放；顾客历史消息仍被围栏；删除会话后不再回放；
      **本轮回答只复述历史回答里的数字、未调用工具时，该数字被判为无来源并降级**；
      N1 `test_history_serialization.py` 与两端 Chat 既有测试零回归

```python
async def test_number_only_in_replayed_history_is_unsourced(loop) -> None:
    """D-N4-1 第 4 条：历史里的助手文字不是事实来源。"""
    history = [user("本周净成交额多少"), assistant("净成交额是 12.3 万")]
    out = await loop.run(history=history, user="再说一遍净成交额",
                         script=[end_turn(text="净成交额是 12.3 万")])
    assert out.degraded is True
```

**2026-09-28 完成记录（Opus）：** `services/v2/conversations.py::load_history()` 按对话与 `merchant_id` 读取最近 N 轮
`USER / ASSISTANT` 文字（截断落在一轮中间时丢掉开头孤立的助手回答），两端 Chat 服务在调用循环前装入
`LoopRequest.history`，路由从 `CHAT_HISTORY_MAX_TURNS`（默认 6，0–20）传入。**顺带堵住一个既有漏洞**：循环原本把
全部历史消息（含助手回答）都算作数字来源（`runner.py`），历史回放一上线，模型复述自己编过的数字就能通过校验；
现只认历史中的用户消息。测试：`tests/unit/agent/loop/test_runner.py` 两例（助手历史数字无来源——修复前失败；
用户历史数字可引用）、`tests/integration/v2/test_chat_history_replay.py` 六例（续轮回放、新对话不串、只留最近 N 轮、
N=0 关闭、顾客历史围栏、请求体不能提交历史）。相关回归 1947 passed，`ruff`、`mypy app` 通过。

---

### Task 1：锚点——三项必保留信息

两种策略共用。**先把必须保留的信息从消息里抽出来，压缩后再无损回填**，
而不是指望压缩过程"记得保留"。

```python
@dataclass(frozen=True)
class CompactionAnchors:
    tool_sources: list[ToolSourceRef]      # 工具名 + call_id + 返回的关键数值引用
    data_cutoffs: list[DataCutoff]         # 指标名 + 截至时间 + 来源 + 定义版本
    draft_versions: list[DraftRef]         # draft_id + draft_version
```

- [x] **步骤 0：定跨回合锚点来源**（依赖 Task 0 裁定）——本回合的锚点从工具结果抽取；
      历史回合的锚点只能从 `messages.response_payload` 的持久化字段（`analysis_sources`、数据截至时间、草稿引用）重建，
      逐项核对这些字段是否足够，不足时先按「契约 → Schema」补字段，不得从助手文字里正则抠数字
- [x] **步骤 1：写失败测试**

```python
def test_anchors_extracted_from_tool_results() -> None:
    msgs = conversation_with(tool_result_metric(cutoff="2026-09-21T09:00Z", version="v3"),
                             tool_result_draft(draft_id=D, version=4))
    a = extract_anchors(msgs)
    assert a.data_cutoffs[0].cutoff == "2026-09-21T09:00Z"
    assert a.draft_versions[0] == DraftRef(D, 4)


def test_anchors_never_contain_identity() -> None:
    a = extract_anchors(conversation_with_session_context())
    assert "merchant_id" not in repr(a) and "buyer_key" not in repr(a)
```

- [x] **步骤 2：确认失败 → 实现 → 确认通过**

**2026-09-28 完成记录（Opus）：**
- **步骤 0 结论**：已落库响应（`messages.response_payload`）里的工具信息只有工具名、调用 ID 与通用状态短句
  （`ToolCallDisplay`/`PublicToolSummary`），**没有数值、截至时间或草稿版本**；而 D-N4-1 规定历史里的数字不是事实来源，
  模型须重新调用工具。因此跨回合锚点既无从重建也不需要，**锚点只取本回合工具结果**，不补契约字段、不从助手文字里抠数字。
- **实现**：`app/agent/loop/compaction/anchors.py`——`extract_anchors()` 按字段白名单抽取（失败调用与 Skill 不算锚点，
  身份字段不进），`format_anchors()` 确定性序列化，`render_anchors()` 外包围栏回填。锚点从 `ToolResult` 列表抽取而非解析
  已围栏的消息文本；计划原写的 `extract_anchors(msgs)` 签名据此调整。
- **草稿版本**：起草工具结果原本只有 `draft_id`/`kind`，模型看不到版本。新增 `app/schemas/v2/drafts.py::INITIAL_DRAFT_VERSION`，
  起草结果 payload 带 `draft_version`（`app/tools/gates.py`），`services/v2/drafts.py` 建草稿时引用同一常量。
- **验证**：`tests/unit/agent/loop/test_compaction_anchors.py` 6 例（先红后绿）；循环与工具单测 195 passed；`ruff`、`mypy app` 通过。

---

### Task 2：策略一——工具结果清理

`TOOL_RESULT_PRUNING`：**不调用 LLM**。按时间从旧到新，把已被后续回合消费过的
工具结果正文替换为占位符 + 锚点引用。

- 最近 N 轮（默认 2）的工具结果不动；
- 替换后的占位符形如 `[工具结果已清理：query_metrics#c7，关键值见锚点]`；
- **零 LLM 调用**，不消耗 `COMPACTION_MAX_CALLS`。

- [x] **步骤 1：写失败测试**——清理后 token 数下降；最近 2 轮保留；锚点完整；零 LLM 调用。
- [x] **步骤 2：确认失败 → 实现 → 确认通过**

---

### Task 3：策略二——摘要压缩

`SUMMARIZATION`：调用 LLM 把早期回合压成一段摘要。

### 规则

- 摘要**只替代对话叙述**，锚点**另行回填**，不交给摘要"顺便保留"；
- 摘要在提示词中**显式标注为模型生成内容**：
  `[以下是早期对话的模型摘要，仅供理解上下文，不是事实来源]`；
- 下游确定性校验**不接受摘要作为数字来源**——数字必须能追溯到锚点里的工具来源；
- 每次压缩消耗 1 次 LLM 调用，计入 `COMPACTION_MAX_CALLS`；
  超出则回退到策略一，**不突破 `AGENT_LOOP_MAX_LLM_CALLS`**；
- 被摘要的原文里若有外部文本（顾客话、商品描述），**摘要提示词里同样要围栏**（A11）。

- [x] **步骤 1：写失败测试**

```python
async def test_summary_marked_as_model_generated(compactor) -> None:
    out = await compactor.compact(long_conversation(), llm=fake_summary("…"))
    assert "不是事实来源" in out.messages[0].content


async def test_number_only_in_summary_is_rejected_downstream(loop) -> None:
    """A5：摘要不得升级为事实来源。"""
    out = await loop.run(conversation=compacted_with_number_only_in_summary("净成交额 50 万"),
                         script=[end_turn(text="净成交额是 50 万")])
    assert out.degraded is True


async def test_over_budget_falls_back_to_pruning(compactor) -> None:
    out = await compactor.compact(long_conversation(), remaining_compaction_calls=0)
    assert out.strategy_used == "TOOL_RESULT_PRUNING"


async def test_anchors_survive_summarization(compactor) -> None:
    before = extract_anchors(long_conversation())
    out = await compactor.compact(long_conversation(), llm=fake_summary_that_drops_everything())
    assert extract_anchors(out.messages) == before
```

最后一条的 Fake 故意返回"丢掉所有信息"的摘要——验证锚点靠**回填**保留，而不靠摘要质量。

- [x] **步骤 2：确认失败 → 实现 → 确认通过**

---

### Task 4：接入循环

- 回合开始前估算上下文 token 数，超过 `COMPACTION_TRIGGER_TOKENS` 即触发；
- 按 `COMPACTION_STRATEGY` 选择策略；
- 压缩发生时通过 SSE `step` 事件告知用户（"正在整理较早的对话"），不静默发生；
- **重新核对预算公式**：`AGENT_LOOP_MAX_LLM_CALLS` 默认 12 已预留 1 次压缩；
  若 `COMPACTION_MAX_CALLS` 调大，**必须同步调大 `AGENT_LOOP_MAX_LLM_CALLS`**，
  `Settings` 的启动校验会拦住配错的情况。

- [x] **步骤 1：写失败测试**——超阈值触发；未超不触发；压缩时有 `step` 事件；
      `COMPACTION_MAX_CALLS=3` 而 `AGENT_LOOP_MAX_LLM_CALLS=12` 时启动失败。
- [x] **步骤 2：确认失败 → 实现 → 确认通过**

**2026-09-30 完成记录（Opus）：** Task 2、3 的实现与单测由先前会话写入但未勾选，本次以变异检查代替追溯红灯
（忽略保留窗口、丢锚点、摘要不回填锚点、预算用尽不回退、去掉「不是事实来源」标注，均使测试变红）。
Task 4：`CompactionPolicy`（`compaction/__init__.py`）随 `LoopLimits.from_settings` 进入循环；新增配置
`COMPACTION_STRATEGY`（默认 `TOOL_RESULT_PRUNING`）与 `COMPACTION_TRIGGER_TOKENS`（默认 8000，按字符估算）；
`runner.py` 每次工具轮决策前判断，压缩生效时发出 `ContextCompacted`，SSE 投影为 `step`
（`{label:"正在整理较早的对话", node:"compact_context"}`），最终响应 `thinking_steps` 记同一步；摘要调用走回合预算，
额度用尽回退清理。测试：`tests/unit/agent/loop/test_compaction_loop.py` 8 例（含摘要数字循环级降级、最坏路径恰好 8 次、
两策略身份不进提示词）、`test_limits.py` 新增 4 例、`tests/integration/v2/test_chat_compaction.py` 3 例（两端 JSON + 商家 SSE）。

---

### Task 5：E5 压缩专项评测与生产选型

| 指标 | 含义 |
| --- | --- |
| 身份保持率 | 压缩后回答仍作用于正确的商家 / 顾客 |
| 来源保持率 | 压缩后回答中的数字仍可追溯到工具来源 |
| 草稿版本保持率 | 压缩后引用的草稿版本与实际一致 |
| 安全约束保持率 | 压缩后模型仍遵守禁止项（不自批、不跨店、不谈价） |

- [x] **步骤 1：建评测集** `app/eval/datasets/compaction/`，≥ 30 条长对话，
      每条都跨过压缩阈值，且在压缩点之后提问依赖早期信息的问题
- [x] **步骤 2：Fake LLM 下两策略各跑一遍**（验证锚点与结构，不代表摘要质量）
- [x] **步骤 3：按 R3 提交真实对比评测的审批请求**，填入实际的条数、调用次数与费用上限；
      **取得同意前不得执行**
- [x] **步骤 4：据四项保持率选定生产策略**，写入 §6.12 并设置 `COMPACTION_STRATEGY` 默认值；
      未选中的策略保留在 `app/eval/` 作为回归对照

**若未获真实评测授权**：默认选 `TOOL_RESULT_PRUNING`——它零 LLM 调用、行为完全确定，
在没有质量证据时是更保守的选择。**进度快照须写明"未经真实模型对比，暂按保守默认"**。

**2026-09-30 完成记录（Opus）：** 评测集 `app/eval/datasets/compaction/n4_e5_compaction.yaml` 30 条（商家 18、顾客 12），
评估器 `app/eval/compaction_e5.py`，校验 `tests/eval/test_n4_compaction_e5_fake.py` 6 例。Fake LLM 下两策略身份、来源、
草稿版本、安全约束四项均 100%；诊断项历史用户原话可见率：清理 100%、摘要 0%（Fake 最坏摘要）。步骤 3 的审批请求
（90 次 `deepseek-flash` 调用、约 84 万 token、超过每日预算）写在 `docs/history/eval/n4-e5-compaction-fake.md` 并已提交用户，
同日获用户授权后执行（见下）。步骤 4：先按保守默认选 `TOOL_RESULT_PRUNING`，真实对比后确认维持，写入 §6.12；`SUMMARIZATION` 保留在
`app/agent/loop/compaction/` 可配置切换，由 E5 评测与单测回归（未移入 `app/eval/`，见台账裁定）。

**2026-09-30 真实对比（用户授权，R3）：** `app/eval/compaction_e5_model.py --real`，`deepseek-flash` 90 次、383,755 token（测试库保险丝经用户同意临时提到 100 万）。
人工复核后两策略回答各 28/30 合格，身份、安全均 30/30；摘要保留历史用户约束 29/30；摘要策略总 token 约为清理的 1.87 倍，**维持 `TOOL_RESULT_PRUNING`**。
发现并修复：截至时间锚点补 `[工具#call_id]`（数值与定义版本可关联）；正文出现 DeepSeek `DSML` 工具调用标记按上游异常降级（循环两条路径各一测）。
评测集商家问题按依赖轮次重写（原问题与依赖不一致）。报告 `docs/history/eval/n4-e5-compaction-real.md`；修复后未重跑真实对比。

---

### Task 6：自检

```powershell
cd backend
rg -n "merchant_id|buyer_key" app/agent/loop/compaction/
uv run pytest tests/unit/agent/loop/ -v
uv run pytest; uv run ruff check .; uv run mypy app
```

第一条期望零命中（身份不进压缩后的提示词）。

更新 `docs/project-progress.md`：选定策略及依据（真实评测或保守默认）、E5 压缩评测状态、未执行 Git。

**2026-09-30 完成记录（Opus）：** `rg "merchant_id|buyer_key" app/agent/loop/compaction/` 零命中（anchors.py 说明文字改为中文描述）；
`tests/unit/agent/loop/` 125 passed；后端全量 `REQUIRE_INTEGRATION_DB=1`（本地 compose PostgreSQL、空 `LLM_API_KEY`）
**4241 passed / 13 skipped / 0 failed**，`ruff check .`、`mypy app`（291 文件）通过；进度快照已更新。

---

## 本计划明确不做的事

| 不做 | 归属 |
| --- | --- |
| 跨会话的长期记忆 | `n4-memory-pipeline`（压缩只管单个对话内） |
| 提示词缓存命中率 | `n5-budget-ops-and-railway` |
