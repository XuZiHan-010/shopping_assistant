# 任务清单：真实模型评测遗留缺陷整改

**输入**：[spec.md](spec.md)、[plan.md](plan.md)
**测试**：全部使用脚本化 / Fake 模型。**与清单顺序的偏差**：实际执行时测试与实现在同一轮写成，没有先单独跑红；
改为事后验证测试确实能拦住回退——去掉「小结果保留」后 `test_loop_keeps_the_after_sale_detail_through_compaction`
变红；触顶收尾在改动后有 1 条既有用例按旧行为失败、已按新规则更新。

没有需要先行搭建的公共基础，五个故事互不依赖，可按优先级逐个完成、逐个验证。

## 阶段 1：用户故事 1 —— 售后回合不再丢详情（P1）

**目标**：压缩不清掉本回合还要用的小结果；规则库有成文售后规则。
**独立验证**：`uv run pytest tests/unit/agent/loop/compaction tests/unit/knowledge -q`

- [x] T001 [US1] 在 `backend/tests/unit/agent/loop/test_compaction_small_results.py` 补测试：较早轮次里不超过阈值的工具结果原样保留、超过的仍被清理、全部很短时 `changed=False`
- [x] T002 [US1] 在 `backend/app/agent/loop/compaction/__init__.py` 增加最小可清理长度（触发阈值的四分之一）并写入 `CompactionPolicy`；`backend/app/agent/loop/compaction/pruning.py` 按它跳过小结果；`backend/app/agent/loop/runner.py` 传入
- [x] T003 [US1] 在 `backend/app/agent/loop/compaction/summarization.py` 让工具结果全部不超过阈值的较早轮整轮原样保留，并补对应测试
- [x] T004 [US1] 在 `backend/tests/unit/agent/loop/test_compaction_small_results.py` 补售后回合的脚本化用例：队列 → 详情 → 两次长规则检索 → 起草，断言第五次模型调用的上下文仍含详情事实字段
- [x] T005 [P] [US1] 新增 `backend/app/knowledge/borough_rules.py`（《Borough 平台售后规则》，条款与 `after_sale_eligibility.py`、`after_sale_decision.py` 一致），`backend/app/knowledge/wiki_seed.py` 的 `seed_wiki_documents` 一并落库
- [x] T006 [P] [US1] 在 `backend/tests/unit/knowledge/` 补测试：规则文档标记完整、路径对顾客可见、条款里的时限与 `after_sale_eligibility.py` 的常量一致、镜像种子 `load_wiki_seed_entries()` 仍是 21 篇

## 阶段 2：用户故事 2 —— 压缩后说得全出处（P1）

**目标**：保留记录不再误导模型把工具名当来源；带调用序号；知识文档出处不丢。
**独立验证**：`uv run pytest tests/unit/agent/loop/compaction tests/eval -q -k compaction`

- [x] T007 [US2] 在 `backend/tests/unit/agent/loop/test_compaction_small_results.py` 补测试：标题不含「工具来源」、清理占位含「本回合第 N 次工具调用」、知识结果保留 `title` 与 `citation` 且不带入其他字段
- [x] T008 [US2] 修改 `backend/app/agent/loop/compaction/anchors.py`（小标题、知识文档出处）与 `backend/app/agent/loop/compaction/pruning.py`（调用序号）
- [x] T009 [US2] 调整 `backend/app/eval/compaction_e5.py` 与 `backend/app/eval/compaction_e5_model.py` 为口径 v3（提示词问「数据来源」；身份陷阱只查压缩新写入的消息），同步 `backend/tests/eval/` 里的对应用例

## 阶段 3：用户故事 3 —— 触顶也有内容（P2）

**目标**：工具调用或轮数触顶时给一次不带工具的收尾作答。
**独立验证**：`uv run pytest tests/unit/agent/loop/test_runner.py -q`

- [x] T010 [US3] 在 `backend/tests/unit/agent/loop/test_runner.py` 补红灯测试：超限批次不执行且每个调用得到「未执行」结果；收尾调用不带工具；回答非空并带 `LIMIT` 降级；收尾里的无来源数字仍被拦下；收尾时预算用尽回退为如实说明
- [x] T011 [US3] 在 `backend/app/agent/loop/runner.py` 实现收尾作答，并把无正文时的降级说明改为「未能完成回答」
- [x] T012 [US3] 更新 `backend/tests/` 中断言旧降级文案或旧触顶行为的既有用例

## 阶段 4：用户故事 4 —— 英文搜得到商品（P2）

**目标**：英文关键词经固定词表对应到中文目录。
**独立验证**：`uv run pytest tests/unit/tools -q -k search`

- [x] T013 [P] [US4] 新增 `backend/app/tools/customer/search_terms.py`（英文词 → 中文检索词，含单复数归一）及其单元测试 `backend/tests/unit/tools/test_customer_search_terms.py`
- [x] T014 [US4] 修改 `backend/app/tools/customer/catalog.py` 的 `search_products`：展开检索词、匹配 `category` 列、英文无结果时在说明里提示改用中文；在既有集成测试文件里补英文关键词用例

## 阶段 5：用户故事 5 —— 更正偏好不留旧值（P3）

- [x] T015 [P] [US5] 在 `backend/tests/eval/` 的记忆评测用例里补回放测试：把真实运行中 MEM-016 的两条候选原样喂给 `app.eval.memory_e5.evaluate`，断言 `wrong_writes == 0`

## 阶段 6：收口

- [x] T016 同步 `docs/backend-development-plan.md` §6.10（触顶收尾）与 §6.12（小结果保留、保留记录字段）
- [x] T017 运行 `uv run ruff check .`、`uv run mypy app` 与后端测试（有一次性库时跑全量，否则跑不依赖库的部分并如实说明）
- [x] T018 更新 `docs/project-progress.md` 文首快照与 §四 A 组状态；`docs/project-navigation.md` 登记新增模块

## 依赖与顺序

- T002 依赖 T001；T003、T004 依赖 T002；T008 依赖 T007，且与 T002 改同一文件 `pruning.py`，须在 T002 之后。
- T011 依赖 T010；T014 依赖 T013。
- T005/T006、T013、T015 与其余任务不共享文件，可并行。
- 最小可交付：阶段 1（售后回合）。

## 本清单之外

真实模型复测（v2 质量集 19 条、压缩来源保留、记忆抽取）须另取 R3 授权；Railway 前置验收与线上走查须用户逐项同意。

## 阶段 7：真实复测后的追加整改（2026-10-10 下午）

真实模型复测（报告 `docs/history/eval/real-retest-2026-10-10.md`）之后，用户要求「改完一起提交」并裁定新增后端合计工具。

- [x] T019 [US3] `backend/app/agent/loop/runner.py` 的重写提示要求直接给出完整回答、不提上一版（重写稿曾向顾客解释「上一条算错了」）
- [x] T020 [US4] `backend/app/tools/customer/search_terms.py` 补中文近义词（「外套」→ 夹克 / 开衫 / 大衣 等）
- [x] T021 `backend/app/tools/customer/catalog.py` 商品卡增加可直接引用的 `price`；`backend/app/services/v2/shop_chat.py`、`merchant_chat.py` 的提示词规定金额写成元、顾客端不自己算合计、不提工具名与内部过程；`tests/unit/prompts/test_structured_prompts.py` 守住提示词里不出现示例数字
- [x] T022 [US2] `backend/app/eval/compaction_e5_model.py` 两条评分正则修正（口径 v3.1），用当日回答离线重判
- [x] T023 [US3] 新增顾客端只读工具 `estimate_bundle_total`（`backend/app/tools/customer/catalog.py`），穿搭 Skill 与提示词改为调用它；`shop/src/i18n/toolNames.ts` 补显示名；`backend/tests/integration/v2/test_shop_chat.py` 补用例并更新工具面断言
- [x] T024 定向真实重跑 QLT-N5-003、QLT-N5-005，结果写入报告
