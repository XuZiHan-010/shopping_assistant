# 评测报告

> **标题更正（人工补注，2026-09-22）**：下面「安全硬门禁」的标题是脚本当时的一个标签缺陷——
> 这次跑的是 Task 7 的**质量基线**，不是安全集，`report.py` 当时还没有 `gate_title` 参数。
> 已在 `app/eval/report.py` 补上 `gate_title` 参数并在脚本里改用正确标题，
> 本文件保留原始输出不改写数据本身。「门禁结论」在这里应读作「6 条用例是否全部通过」，
> 不代表任何安全判定。

## 安全硬门禁（零失败，门禁判据）
- QLT-001：通过
- QLT-002：失败
  - [response_field] 路径 answer_mode 期望 'METRIC'，实得 'INVALID'
- QLT-003：失败
  - [response_field] 路径 answer_mode 期望 'METRIC'，实得 'INVALID'
- QLT-004：失败
  - [response_field] 路径 answer_mode 期望 'METRIC'，实得 'INVALID'
- QLT-005：失败
  - 裁判分数 0.30（rubric=greeting_quality@v1）
- QLT-006：失败
  - 裁判分数 0.20（rubric=greeting_quality@v1）
- 门禁结论：不通过

## 补注：实际回答内容（人工核对，只读查询 `answers.response_payload`，不产生新调用）

| 用例 | 模式 | 回答 |
| --- | --- | --- |
| QLT-001 zh-CN | METRIC | 今天成交 GMV 为 16996.10 元。 |
| QLT-002 en-US | INVALID | "I'm the Borough Merchant AI Assistant, and I can only answer questions related to your store's operations..."（拒答模板） |
| QLT-003 zh-CN | INVALID | 我是 Borough 商家 AI 助手，只能回答与您店铺经营相关的问题……（拒答模板，中文同款问题在 zh-CN 下也被判定超范围） |
| QLT-004 en-US | INVALID | 同 QLT-002 的拒答模板 |
| QLT-005 zh-CN | CHAT | 已完成结构化理解。 |
| QLT-006 en-US | CHAT | Structured understanding complete. |

**两类真实发现**（v1 冻结基线本身的特征，按 O4 不在本轮修复）：

1. **问候语路径产出的是内部占位文案，不是真正的问候回复**：中英文都是——「已完成结构化理解」/
   「Structured understanding complete.」。这明显不是给顾客看的话术，像是某个内部步骤的完成态
   文案泄漏进了最终 `answer` 字段。这是冻结基线的真实缺陷，不是评测脚本的问题
   （`degraded=false`，说明模型没有降级，是真实生成路径产出了这个结果）。
2. **同一个中文问题，`Accept-Language: en-US` 时被判定 INVALID（拒答），`zh-CN` 时正常回答**
   （QLT-001 vs QLT-002，均为「今天销售额」）：说明分类/理解步骤对显示语言与消息语言不一致的
   输入不够健壮。QLT-003（「最近7天退款金额」，zh-CN）本身也被拒答，说明拒答不只发生在
   语言不一致的场景，基线对这类问法的覆盖本来就不完整。

按 O4，基线冻结、不做新修复；这些发现的价值在于**作为未来与新工具循环对照评测的已知基线特征**，
留给 N2 起的对照评测参考，不代表需要现在处理。
