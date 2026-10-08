# N1–N4 收口执行准备（2026-10-04）

本记录承接 [原冻结口径](n1-n4-acceptance-2026-10-03.md)，不重定义样本、分母、评分或人工合格标准。
真实评测尚未获得 R3 费用授权，尚未执行。免费回归结果写入
[验收结果](n1-n4-acceptance-results-2026-10-03.md)。这不是发布验收，也不授予生产或 Git 权限。

## 独立复核与整改范围

`review_acceptance_readiness` 只读核对原清单发现 5 文件已变化：`eval/report.py`、`eval/runner.py`、
`eval/security_harness.py`、`services/v2/merchant_chat.py`、`services/v2/shop_chat.py`。
原文件内容没有另存快照，不能把相对 Git HEAD 的 diff 当作冻结后的差异。
原四个评测入口、数据集、Skill 用例及评分源码在本次修改前仍匹配旧哈希。

发现并整改的执行准备缺口：

- 新增 `app/eval/acceptance_evidence.py`，四个手动入口必须传同一 `--ledger`。
  每次调用前持锁追加预留并落盘，返回后立即保存合成请求、响应和用量。批次上限固定不超过
  **442 次 / 2,000,000 token**，重新打开账本或跨日期均不重置。原数据库费用守卫继续生效。
- 输入 UTF-8 字节数（含工具 Schema）加输出上限与协议余量作为保守预留，并至少预留原单次预算。
  重复 ID、未完成调用、未知用量、损坏日志或残留锁均阻止自动继续；不得删除账本/换路径绕过预算。
  预算不足时停止，不自动补跑。提供商异常计量须人工核对，不承诺在供应商违规计量时仍能严格控制费用。
- 运行前锁定本地 `_test` 数据库、`deepseek-flash`、OpenAI 协议、DeepSeek 根地址及记忆预算 4000；
  配置快照只含白名单字段，绝不含 API Key 或数据库密码。输出文件以独占新建预检，禁止覆盖已有结果。
- 记忆评测通过逐例回调保存候选、双过滤结果与接受结果；异常时保留已执行证据，整批没有完成标记，
  不生成虚假的全量通过结果。RAG 额外保存检索快照、裁判原文、降级状态与人工复核清单，包含拒答失败。
- 这些改动只补执行防护与本地合成证据，不改变发送给模型的提示、样本、自动判分或分母。
  独立盲审继续只读 `.blind.json`、冻结样本和人工标准，判定锁定后再揭示策略映射。

## 待授权的具体执行范围

接口：`https://api.deepseek.com/chat/completions`；模型：`deepseek-flash`；会按 DeepSeek 账户价格收费。
仍为 48 次首次 Skill 选择 + 8 次售后摘要 + 90 次压缩 + 128 次关键词 RAG + 128 次混合 RAG +
40 次记忆抽取，共最多 442 次，整个批次最多 200 万 token。不是每组各有 200 万。
尚未核实当前人民币单价，不承诺人民币金额。任何失败后的追加调用也计入同一额度，不自动重跑整批。

取得明确授权后才可运行以下命令。执行目录为 `backend/`；`<out>` 为仅保存合成评测证据的本地目录，
所有命令共用 `<out>/batch.jsonl`。Key 仅由环境注入，不写命令或日志。
先核对新版清单全部哈希与源码快照；不一致即停止并重新复核。

```text
uv run python -m app.eval.n3_quality_acceptance --real --dump <out>/n3.json --ledger <out>/batch.jsonl
uv run python -m app.eval.compaction_e5_model --real --dump <out>/compaction.json --ledger <out>/batch.jsonl
uv run python -m app.eval.rag_judge_e5 --real --retrieval keyword --dump <out>/rag-keyword.json --ledger <out>/batch.jsonl
uv run python -m app.eval.rag_judge_e5 --real --retrieval hybrid --dump <out>/rag-hybrid.json --ledger <out>/batch.jsonl
uv run python -m app.eval.memory_e5 --real --dump <out>/memory.jsonl --ledger <out>/batch.jsonl
```

环境显式指定本地独立库、`APP_ENV=test`、`LLM_PROTOCOL=openai`、
`LLM_BASE_URL=https://api.deepseek.com`、`LLM_MODEL=deepseek-flash`、
`MEMORY_EXTRACTION_MAX_TOKENS=4000`、`LLM_DAILY_BUDGET_TOKENS=2000000`。
日预算不替代批次预算；执行库不得与 pytest 共用，否则测试清表会损坏用量证据。
保持既有 `LLM_MAX_OUTPUT_TOKENS_PER_CALL` 并在账本记录，不使用真实数据、不启动公开服务。

中断时先核对 JSONL 与数据库 `llm_usage`；已执行调用不能静默重放。原始证据中未出现的样本记为未执行。
自动结果、逐条人工复核与盲审差异分别保存；原验收口径要求的人工部分未完成时，N4-3 保持未勾选。

## 冻结状态

新版候选清单 `n1-n4-acceptance-2026-10-04.sha256.json` 与源码快照
`n1-n4-acceptance-source-2026-10-04.zip` 在免费验证后生成；旧 manifest 与旧记录保留不覆盖。
独立复审已确认样本与评分不变并提出末次调用用量条件；条件已通过本地反例测试整改。
最后一次独立复核因代理额度限制未执行，因此此版本标为**候选冻结，待末次补丁独立复核**，
不能声称已获完整独立验收。真实评测前还须重新核对所有哈希并完成该复核。
源码快照仅包含清单列出的代码、合成数据与口径文档，不包括 `.env`、密钥、生产数据或运行日志。
