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
> 新增 **Task 0 多轮历史回放**（回放什么、回放多少属待裁定 D-N4-1），并在 Task 1 增加跨回合锚点来源一步。
> 已在位：`compaction_max_calls`（默认 1）与 `AGENT_LOOP_MAX_LLM_CALLS` 公式校验（`app/core/config.py:29`、`:263`）；
> 尚缺：`COMPACTION_STRATEGY`、`COMPACTION_TRIGGER_TOKENS`。

---

## 入口条件

> **预写计划不是已验证实现。** 本计划写于上游代码尚不存在时，文中引用的类名、函数签名、
> 工具名、表字段、错误码都是**当时的设计**。开工前逐项对照上游**实际落地**的接口；
> 不一致时先按 PRD → 契约 → 计划的顺序修正，**再动代码**，不得在实现里默默适配或绕过。

- [ ] `n2-tool-loop-and-registry` 已完成，且 `AGENT_LOOP_MAX_LLM_CALLS` 的公式校验在位；
- [ ] N3 两份 Skill 计划已完成——多轮、多工具的真实对话形态要等 Skill 就位后才有代表性；
- [ ] **核对 §6.12 的 `CompactionStrategy` 与本计划一致**；
- [ ] **D-N4-1（多轮历史回放）已由用户裁定**并写入 PRD A5 与契约 §8.8.3 / §8.9.3——未裁定不开工 Task 0，
      Task 1–5 可先按「单回合内工具结果增长」这一种形态推进。

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
| `backend/app/core/config.py` | `COMPACTION_STRATEGY`、`COMPACTION_TRIGGER_TOKENS`、`COMPACTION_MAX_CALLS` |
| `backend/app/eval/datasets/compaction/` | E5 压缩评测集 |

---

### Task 0：多轮历史回放（2026-09-27 编组新增，待裁定 D-N4-1）

现状：两端 Chat 服务只把本轮消息交给循环；已持久化的只有用户消息与最终响应（`messages.response_payload`），
**工具结果不落库**。因此回放只可能是「用户话 + 助手最终回答」的文字，跨回合的工具来源、截至时间、草稿版本
只能从已持久化的响应字段里取（见 Task 1 步骤 0）。

推荐方案（待用户确认）：回放同一会话最近 N 轮（默认 6）的用户与助手文字；顾客原话按 A11 照常围栏；
**不回放工具结果与推理内容**（跨协议回放已被 §6.17 禁止，且工具结果未持久化）；超出 N 轮的部分交给本计划的压缩。

- [ ] **步骤 1：契约先行**——把裁定结果写入 PRD A5 与后端计划 §8.8.3 / §8.9.3（回放范围、条数上限、围栏规则），
      再改代码；本步不新增对外字段
- [ ] **步骤 2：写失败测试 → 实现 → 确认通过**——第二轮请求的出站消息含第一轮文字；跨会话、跨角色不回放；
      顾客历史消息仍被围栏；删除会话后不再回放；N1 `test_history_serialization.py` 与两端 Chat 既有测试零回归

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

- [ ] **步骤 0：定跨回合锚点来源**（依赖 Task 0 裁定）——本回合的锚点从工具结果抽取；
      历史回合的锚点只能从 `messages.response_payload` 的持久化字段（`analysis_sources`、数据截至时间、草稿引用）重建，
      逐项核对这些字段是否足够，不足时先按「契约 → Schema」补字段，不得从助手文字里正则抠数字
- [ ] **步骤 1：写失败测试**

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

- [ ] **步骤 2：确认失败 → 实现 → 确认通过**

---

### Task 2：策略一——工具结果清理

`TOOL_RESULT_PRUNING`：**不调用 LLM**。按时间从旧到新，把已被后续回合消费过的
工具结果正文替换为占位符 + 锚点引用。

- 最近 N 轮（默认 2）的工具结果不动；
- 替换后的占位符形如 `[工具结果已清理：query_metrics#c7，关键值见锚点]`；
- **零 LLM 调用**，不消耗 `COMPACTION_MAX_CALLS`。

- [ ] **步骤 1：写失败测试**——清理后 token 数下降；最近 2 轮保留；锚点完整；零 LLM 调用。
- [ ] **步骤 2：确认失败 → 实现 → 确认通过**

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

- [ ] **步骤 1：写失败测试**

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

- [ ] **步骤 2：确认失败 → 实现 → 确认通过**

---

### Task 4：接入循环

- 回合开始前估算上下文 token 数，超过 `COMPACTION_TRIGGER_TOKENS` 即触发；
- 按 `COMPACTION_STRATEGY` 选择策略；
- 压缩发生时通过 SSE `step` 事件告知用户（"正在整理较早的对话"），不静默发生；
- **重新核对预算公式**：`AGENT_LOOP_MAX_LLM_CALLS` 默认 12 已预留 1 次压缩；
  若 `COMPACTION_MAX_CALLS` 调大，**必须同步调大 `AGENT_LOOP_MAX_LLM_CALLS`**，
  `Settings` 的启动校验会拦住配错的情况。

- [ ] **步骤 1：写失败测试**——超阈值触发；未超不触发；压缩时有 `step` 事件；
      `COMPACTION_MAX_CALLS=3` 而 `AGENT_LOOP_MAX_LLM_CALLS=12` 时启动失败。
- [ ] **步骤 2：确认失败 → 实现 → 确认通过**

---

### Task 5：E5 压缩专项评测与生产选型

| 指标 | 含义 |
| --- | --- |
| 身份保持率 | 压缩后回答仍作用于正确的商家 / 顾客 |
| 来源保持率 | 压缩后回答中的数字仍可追溯到工具来源 |
| 草稿版本保持率 | 压缩后引用的草稿版本与实际一致 |
| 安全约束保持率 | 压缩后模型仍遵守禁止项（不自批、不跨店、不谈价） |

- [ ] **步骤 1：建评测集** `app/eval/datasets/compaction/`，≥ 30 条长对话，
      每条都跨过压缩阈值，且在压缩点之后提问依赖早期信息的问题
- [ ] **步骤 2：Fake LLM 下两策略各跑一遍**（验证锚点与结构，不代表摘要质量）
- [ ] **步骤 3：按 R3 提交真实对比评测的审批请求**，填入实际的条数、调用次数与费用上限；
      **取得同意前不得执行**
- [ ] **步骤 4：据四项保持率选定生产策略**，写入 §6.12 并设置 `COMPACTION_STRATEGY` 默认值；
      未选中的策略保留在 `app/eval/` 作为回归对照

**若未获真实评测授权**：默认选 `TOOL_RESULT_PRUNING`——它零 LLM 调用、行为完全确定，
在没有质量证据时是更保守的选择。**进度快照须写明"未经真实模型对比，暂按保守默认"**。

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

---

## 本计划明确不做的事

| 不做 | 归属 |
| --- | --- |
| 跨会话的长期记忆 | `n4-memory-pipeline`（压缩只管单个对话内） |
| 提示词缓存命中率 | `n5-budget-ops-and-railway` |
