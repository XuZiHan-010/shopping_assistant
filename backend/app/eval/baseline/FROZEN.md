# LangGraph 基线冻结记录（O4）

> 本文件是冻结点的**记录**，不是操作指南。冻结本身由
> `tests/eval/test_baseline_freeze.py` 的守卫测试强制——改动被冻结的对象会让
> 那些测试失败，倒逼改动者在这里解释为什么。

## 冻结范围

`backend/app/agent/graph.py` 定义的 12 节点 LangGraph（`GRAPH_NODES`），
自 2026-09-20 起冻结为只读评测基线：

- 不再承接新 Skill、工具或写操作；
- 不部署为新生产主流程（不接入任何 `/api/v2/*` 路由）；
- 只用于与目标架构（PRD A1–A11 的新工具循环，N2 起落地）做质量对照评测。

## 冻结点

| 项 | 取值 |
| --- | --- |
| 冻结日期 | 2026-09-20（决策日期）；本记录写入日期 2026-09-22 |
| `graph.py` git blob 哈希（`git hash-object`） | `5e466bd48cb6bce2fe3d4d13c78a533b00615d47` |
| `GRAPH_NODES`（12 节点，见下） | 见 `FROZEN_NODES`，与 `app/agent/graph.py` 逐字一致 |
| LangGraph 依赖版本 | `langgraph==0.6.11`（`uv.lock` 锁定） |
| `uv.lock` 内容哈希（sha256，本记录写入时） | `772d9cd2acd8fb9bbc3e1e459c7db242fb9c8da7067e1baef26230302f36a314` |
| 评测数据种子常量 | `DEMO_ANALYTICS_SEED_BASE = 20260804`（`app/analytics/demo_data.py`） |

## GRAPH_NODES（12 节点，冻结顺序）

```text
load_context
retrieve_knowledge_index
prefilter_question
classify_intent
understand_intent
validate_intent
retrieve_knowledge_detail
query_data
compose_answer
quality_loop
suggest_questions
persist_answer
```

## 说明

- `uv.lock` 哈希会随其他模块新增依赖而变化（例如本轮为评测骨架新增
  `pyyaml`/`types-pyyaml`），这不代表基线本身被改动——基线冻结只约束
  `graph.py` 与 `GRAPH_NODES` 本身，`uv.lock` 哈希只作参考快照，不是守卫断言的对象；
- 真正被测试强制的是 `GRAPH_NODES` 的值与 `graph.py` 不接入 `/api/v2/*`，
  见 `tests/eval/test_baseline_freeze.py`；
- 与冻结基线的真实模型对照评测是 `plans/2026-09-21-n1-eval-harness.md` Task 7
  步骤 3 的范围，需要 N2 工具循环存在后才能执行，且需 R3 单独授权。
