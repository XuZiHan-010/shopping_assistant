# N2 新工具循环与冻结基线结构对照（Fake LLM）

> 生成方式：`cd backend; uv run python -m tests.eval.baseline_comparison`；
> 可复现性由 `tests/eval/test_baseline_comparison.py` 断言（重新生成须与本文件逐字一致）。
> 计划：`plans/2026-09-21-n2-tool-loop-and-registry.md` Task 5。零费用，无真实模型调用。

**本对照只证明结构正确，不证明回答质量。** 两条路径使用同一份脚本化 Fake LLM 输出与同一个受控查询替身，回答正文由脚本决定；调用次数、降级路径与代码断言的差异反映编排结构，**不得据此宣称新循环质量优于或劣于基线**。真实模型对照属 N1 评测计划 Task 7 步骤 3，须按 R3 另行授权，当前状态：待人工验收。

## 范围

- 用例：`app/eval/datasets/quality/` 中 `skill ∈ {chat_metric, chat_greeting}` 的 6 条（双方共有的旧能力，A2）；
- **未覆盖**：规则问答与拒答。N1 质量集没有这两类用例，新循环也还没有知识检索工具（N3/N4）；
- 基线侧：未改动的 `MerchantQaGraph`，零 LLM 前置闸门关闭（受控查询替身之外没有知识库，开启会把指标题当作无关问题拒答，与本对照无关）；
- 新循环侧：`run_loop()` + `ToolGates`，挂一个仅供本对照的只读 `query_metric` 工具，与基线调用同一个查询替身；指标回答与基线一样做一次独立复核；
- 代码断言：沿用用例自带的 `http_status` / `response_field`；新循环不产生 `answer_mode`（v2 是否暴露由字段契约决定），该断言对新循环记为不适用。

## 汇总

| 路径 | 代码断言通过 | 降级 | 正常完成 | LLM 调用合计 | 受控查询合计 |
| --- | --- | --- | --- | --- | --- |
| 冻结基线 | 16/16 | 0/6 | 6/6 | 20 | 4 |
| 新工具循环 | 10/10 | 0/6 | 6/6 | 14 | 4 |

## 逐条

| 用例 | 能力 | 语言 | 基线 LLM | 循环 LLM | 基线查询 | 循环查询 | 基线质量 | 循环质量 | 基线断言 | 循环断言 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| QLT-001 | chat_metric | zh-CN | 4 | 3 | 1 | 1 | PASSED | PASSED | 3/3 | 2/2 |
| QLT-002 | chat_metric | en-US | 4 | 3 | 1 | 1 | PASSED | PASSED | 3/3 | 2/2 |
| QLT-003 | chat_metric | zh-CN | 4 | 3 | 1 | 1 | PASSED | PASSED | 3/3 | 2/2 |
| QLT-004 | chat_metric | en-US | 4 | 3 | 1 | 1 | PASSED | PASSED | 3/3 | 2/2 |
| QLT-005 | chat_greeting | zh-CN | 2 | 1 | 0 | 0 | NOT_RUN | NOT_RUN | 2/2 | 1/1 |
| QLT-006 | chat_greeting | en-US | 2 | 1 | 0 | 0 | NOT_RUN | NOT_RUN | 2/2 | 1/1 |

## 读法

- LLM 调用差异来自编排结构：基线先「分类 + 理解」两次结构化调用再取数，新循环由一次决策调用直接发起工具调用、再由一次决策作答；两者都对指标回答做一次独立复核；
- 闲聊：基线走分类 + 理解两次调用，新循环一次作答；两者质量状态都是 `NOT_RUN`（未复核）；
- 这些数字只随编排结构或脚本变化；改动任一路径后重新生成本报告，测试会提示差异。
