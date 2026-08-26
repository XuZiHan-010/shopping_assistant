## 1. 配置项

- [x] 1.1 在 `backend/app/core/config.py` 新增 `question_prefilter_enabled`（默认 `true`，别名 `QUESTION_PREFILTER_ENABLED`）与 `question_prefilter_min_score`（默认 `3`，`ge=0`，别名 `QUESTION_PREFILTER_MIN_SCORE`），验证方式：新增单测断言两项默认值，以及通过环境变量覆盖后 `Settings` 取到新值
- [x] 1.2 在根目录 `.env.example` 补上两个占位配置项与中文注释，验证方式：文件中可见两行且不含真实值

## 2. 确定性切词（零依赖）

- [x] 2.1 新建 `backend/app/agent/prefilter.py`，实现 `tokenize(question) -> tuple[str, ...]`：中文按 2~4 字滑窗切分，英文单词与连续数字整体保留，全部转小写，验证方式：单测覆盖纯中文、纯英文、中英数字混排三类输入，断言候选词集合
- [x] 2.2 在同文件加入极小通用停用词表并在切词后过滤，验证方式：单测断言「什么」「怎么」「请问」等不出现在候选词中，且「退货」「订单」等业务词保留
- [x] 2.3 为切词补边界用例：空字符串、纯标点、超长问题（>200 字），验证方式：单测断言不抛异常且候选词数量有上界

## 3. 打分接口

- [x] 3.1 在 `backend/app/knowledge/retrieval.py` 给 `_relevance_score` 增加「是否计入正文权重」的开关参数，保持既有调用方行为不变，验证方式：既有 `retrieve_knowledge_detail` 相关测试全部仍通过
- [x] 3.2 在 `KnowledgeRetrieval` 新增仅按标题与路径打分的公开方法，覆盖知识文档、指标目录 `display_name` / `metric_code` 与本商家历史记忆三类语料，取最高分，验证方式：单测断言「退货量」得分 ≥ 3、「区别」得分为 0
- [x] 3.3 为打分方法补商家隔离测试：商家 A 的记忆不得影响商家 B 的得分，验证方式：单测构造两商家记忆，断言 B 的得分不受 A 影响（对应 spec「判定必须限定在已验证商家范围内」）
- [x] 3.4 为打分方法补 fail open 测试：语料为空、语料读取抛异常两种情况均返回「放行」而非 0 分拒绝，验证方式：单测断言两种情况下闸门判定结果为放行

## 4. 闸门判定逻辑

- [x] 4.1 在 `prefilter.py` 实现问候语识别（短问题 + 问候语模式），验证方式：单测断言「你好」「在吗」「谢谢」判定为放行，且「CNN 和 RNN 的区别是什么」不被问候语规则放行
- [x] 4.2 实现判定入口：依次执行「配置停用 → 放行」「会话已有助手消息 → 放行」「问候语 → 放行」「打分 ≥ 阈值 → 放行」「否则拒绝」，返回带分数与放行原因的结果对象，验证方式：单测逐条覆盖五个分支
- [x] 4.3 实现「会话是否已有助手消息」的判定并接入仓储，注意用助手消息而非用户消息作判据（见 design.md D6），验证方式：单测断言首轮走打分、第二轮直接放行（`ConversationRepository.has_assistant_message`；集成测试因本机 Docker 未运行而 skip，与既有仓储集成测试同样受限，见 §8.1 前的说明）

## 5. 图接线

- [x] 5.1 在 `backend/app/agent/state.py` 的 `AgentState` 新增闸门结果字段，验证方式：mypy 通过且既有图测试仍通过
- [x] 5.2 在 `graph.py` 的 `GRAPH_NODES` 与 `_STEP_LABELS` 加入 `prefilter_question`（标签「判定问题范围」），位置在 `retrieve_knowledge_index` 与 `classify_intent` 之间，验证方式：单测断言节点数为 12 且顺序正确
- [x] 5.3 实现 `_prefilter_question` 节点方法，验证方式：单测断言节点写入判定结果并推送对应 `ThinkingStep`
- [x] 5.4 把 `prefilter_question` 的出边改为条件边（放行 → `classify_intent`，拒绝 → `suggest_questions`），其余节点保持 `pairwise` 线性连边，验证方式：新增建图测试断言两条分支的目标节点
- [x] 5.5 新增集成测试：范围外提问走完整图后，注入的 mock LLM 客户端调用次数为 0（对应 spec「范围外提问必须零 LLM 成本拒绝」）
- [x] 5.6 新增集成测试：断言拒绝分支实际跳过的节点集合，使后续误连边立刻暴露（见 design.md 风险项）

## 6. 拒答响应

- [x] 6.1 生成拒答响应：`answer_mode=INVALID`、`degraded=false`、`degraded_reason=null`、`quality_status=NOT_RUN`、`quality_attempts=0`、`analysis_sources=["NONE"]`，验证方式：单测逐字段断言（对应 spec「拒答响应必须表述为正常结果而非系统降级」）
- [x] 6.2 编写中文引导文案，说明助手服务范围并提示可问的方向，验证方式：单测断言拒答正文非空且不含「失败」「错误」「降级」等误导性表述
- [x] 6.3 确认 `suggestions_for` 在 `INVALID` + `UNKNOWN` 组合下返回产品入口问题；若不返回则扩展该配置，验证方式：单测断言拒答响应的推荐问题列表非空（已确认现有配置直接满足，无需扩展）
- [x] 6.4 确认拒答经 `persist_answer` 正常落库且能在 `GET /api/conversations/{id}` 中读回，验证方式：API 测试断言被拒问答出现在会话详情中（`tests/api/test_chat.py`；因本机 Docker 未运行而 skip，与既有 e2e 套件同样受限）

## 7. 可观测

- [x] 7.1 拒答时输出结构化日志，至少含判定分数、所用阈值、会话标识，遵循既有脱敏约束不记录隐私字段，验证方式：单测用 `caplog` 断言字段存在，并断言日志中不含商家标识以外的隐私字段

## 8. 回归与文档

- [x] 8.1 运行 `uv run pytest` 全量后端测试，验证方式：全绿且总数不低于既有基线（890）——实测 941 passed / 212 skipped（因本机 Docker 未运行，与既有仓储/API 集成测试同样受限）/ 0 failed
- [x] 8.2 运行 `uv run ruff check .` 与 `uv run mypy`，验证方式：两者均无告警——均通过
- [x] 8.3 确认未产生 API 契约变更：重新执行 `python scripts/export_openapi.py` 后 `docs/api.md` 与 `docs/api.json` 无差异，验证方式：`git diff --exit-code docs/api.md docs/api.json` 返回 0——实测无差异
- [x] 8.4 更新 `docs/backend-development-plan.md` 的 Agent 节点清单，把 11 节点改为 12 节点并补充 `prefilter_question` 的职责，验证方式：文档中节点表与 `GRAPH_NODES` 逐项一致（同时顺手修正了同节 §10 之前一处已过期的「13 节点」表述）
- [x] 8.5 更新 `docs/project-progress.md` 的日期、当前阶段、验证结果与下一步（AGENTS.md §十七 要求），验证方式：文件顶部日期为本次改动完成日
- [x] 8.6 在 `AGENTS.md` §8.3 Agent 编排表补上 `prefilter.py` 一行，验证方式：表中路径与实际文件一致

## 9. 真实模型验收（需 R3 授权，不得自动执行）

- [x] 9.1 在取得用户明确的费用授权后，用真实 DeepSeek 跑一组对照提问（范围内 3 题、范围外 3 题、问候语 1 题、追问 1 题），记录实际调用次数与 token 消耗，验证方式：范围外 3 题的调用次数为 0，其余题目行为与引入本能力前一致——2026-08-26 已用 `deepseek-v4-flash` 实测：范围外 3 题均为 0 次调用，合计 10 次调用 / 14,705 token；结果与结论见 `docs/project-progress.md` 当日条目
