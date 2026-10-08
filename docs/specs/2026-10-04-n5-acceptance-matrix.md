# N5 验收矩阵：PRD §12 逐条证据

> **2026-10-06 复核：本矩阵原有的 Fake 结构通过项不等于真实质量通过。** N5 固定 25 条真实质量用例已执行，最终快照 13/25、N5 新增快捷提问 6/8，质量验收未通过；见 `docs/history/eval/n5-real-quality-2026-10-06.md`。N4 压缩冻结复测的来源完整保留为当前默认清理 3/12、摘要 10/12（自动判分，独立盲审未完成），§12.5 #4 仍未通过。远端 CI、性能基准和公网演示仍未执行。下表原有 2026-10-04/05 的运行标记保留为历史快照，以本段及专项报告为较新证据。

> 对应 `plans/2026-09-21-n5-final-eval-and-closeout.md` Task 2。状态只有四种：**通过 / 未通过 / 待授权 / 未执行**。
> 「通过」表示所列证据在下述运行中实际通过，**不代表真实模型质量已验证**——除特别注明外全部是 Fake LLM / 空 `LLM_API_KEY`。
> 本矩阵的本地测试快照日期为 2026-10-04；2026-10-05 的 N1–N4 真实评测结果已在下方补录。代码再变，按「最近运行」里的命令重跑。

## 运行环境与命令（2026-10-04）

| 项 | 取值 |
| --- | --- |
| 机器 | Intel Core i7-10750H（6 核 12 线程）、16 GB 内存、Windows 11 Home 10.0.26200 |
| 数据库 | 一次性容器 `pgvector/pgvector:pg16`（PostgreSQL 16.15，`fsync=off`），本机 Docker 29.6.2；除本次验收外无其他连接 |
| 模型 | 无；`LLM_API_KEY` 为空，对话由脚本化 Fake LLM 驱动 |

| 代号 | 命令 | 结果 |
| --- | --- | --- |
| **B-全量** | `cd backend; REQUIRE_INTEGRATION_DB=1 LLM_API_KEY= uv run pytest`（2026-10-04 凌晨） | 4568 passed / 4 skipped / 0 failed。跳过：3 项 Windows 符号链接权限、1 项时序哨兵（见 B-时序） |
| **B-增量** | 同上，只跑全量之后新增或改动的用例：`tests/eval`（除另一会话在改的 `test_acceptance_evidence.py`）、`tests/api/test_admin_ops.py`、`tests/unit/core/test_metrics.py`、`tests/integration/v2/test_turn_metrics.py`、`tests/integration/v2/test_feedback_harvest_db.py`、`tests/unit/services`、`tests/api/test_chat.py` | 全部通过 |
| **B-矩阵** | 本矩阵引用的全部后端测试一次性运行（101 个文件或用例节点，`REQUIRE_SECURITY_TIMING=1`，独占库） | 344 passed / 3 skipped（Windows 符号链接权限）/ 0 failed |
| **B-时序** | `REQUIRE_SECURITY_TIMING=1 REQUIRE_INTEGRATION_DB=1 uv run pytest tests/integration/test_session_isolation.py`；2026-10-05 另跑 `tests/api/v2/test_shop_orders.py::test_order_detail_missing_and_foreign_timing` | 商品探针 4 passed；真实订单详情端点各 500 次，1 passed，0 skipped。均使用一次性独占 PostgreSQL |
| **M-单测** | `cd frontend; npm run test` | 785 passed（补图表切换两例之前连续 3 次 783 全绿） |
| **M-E2E** | `npm run test:e2e`（Mock 传输层） | 41 passed |
| **M-S3 / M-S4 / M-N3** | `npm run test:e2e:s3`、`npx playwright test --config playwright.s4.config.ts`、`npm run test:e2e:n3`（真实后端 + 一次性库 + 脚本化模型） | 2 / 1 / 4 passed；N3 首轮 S2 因 Next 开发服务器冷启动失败 1 次，重跑 4/4 |
| **C-单测** | `cd shop; npm run test` | 141 passed |
| **C-E2E / C-S4** | `npm run test:e2e`、`npx playwright test --config playwright.s4.config.ts` | 10 / 1 passed |
| **对账** | `cd backend; uv run python -m scripts.audit_routes` | v2 53 / 53，缺 0 多 0；v1 25 条全在 |

`tests/eval/test_acceptance_evidence.py` 是另一个并行会话正在修改的文件，当前有 1 例失败；它不属于 N5，本矩阵不引用它。

## 12.1 安全与隔离（硬门禁，零失败）

| # | 条目 | 证据 | 状态 | 最近运行 |
| --- | --- | --- | --- | --- |
| 1 | 商家访问他店数据、顾客访问他人订单：全部 403，正文逐字段一致，审计有记录 | 安全集 `tests/eval/test_security_gate.py::test_security_case_passes`（79 条，含 `n1_cross_tenant`、`n2_shop_orders`、`w_merchant_orders`）；`tests/api/v2/test_merchant_orders.py::test_other_merchants_order_returns_resource_forbidden_and_audits`；`tests/api/v2/test_shop_orders.py::test_other_customers_orders_are_indistinguishable_from_missing`；`tests/api/test_session_deps.py::test_*_is_forbidden_and_audited` | 通过 | B-全量 |
| 2 | 订单不存在与不属于本人的响应逐字段一致 | `tests/api/v2/test_shop_orders.py::test_detail_of_foreign_missing_and_legacy_orders_is_one_403`；`tests/integration/v2/test_conversations.py::test_foreign_conversation_detail_indistinguishable_from_missing` | 通过 | B-全量 |
| 3 | 订单不存在与越权两组各 ≥500 次：中位数差 ≤10ms、p95 比值 0.8–1.25 | `tests/api/v2/test_shop_orders.py::test_order_detail_missing_and_foreign_timing` 请求真实订单详情端点，各 500 次，阈值即断言；2026-10-05 独占一次性 PostgreSQL 运行 1 passed。原 `test_no_timing_side_channel` 测商品探针，只作补充。测试未输出原始中位数与 p95；换机器须重测 | 通过 | 2026-10-05 B-时序 |
| 4 | 前端提交 `merchant_id` / `buyer_key` 被忽略或拒绝 | `tests/api/v2/test_openapi_session_contract.py::test_session_requests_reject_client_supplied_identity`；`tests/integration/v2/test_shop_chat.py::test_request_rejects_identity_fields`；安全集 `n1_identity_override`、`n1_buyer_key_forgery`；`tests/api/v2/test_session_routes.py::test_merchant_session_request_cannot_supply_shop_slug` | 通过 | B-全量 |
| 5 | 聊天中的「批准」「确认」不产生写副作用 | `tests/integration/v2/test_merchant_chat.py::test_chat_approval_has_no_effect`；安全集 `n2_merchant_self_approval`；`tests/integration/v2/test_shop_after_sales.py::test_challenge_writes_no_sale_then_confirm_creates_once`；浏览器 S3「聊天里『批准』无效」 | 通过 | B-全量、M-S3 |
| 6 | 提示词注入（顾客对话、商品描述、知识文档）不改变工具权限与审批结论 | 安全集 `n2_shop_chat_injection.yaml` SEC-INJECTION-001–007（三个入口各有中英用例）；`tests/integration/v2/test_shop_chat.py::test_injected_product_description_reaches_the_model_only_as_fenced_data` | 通过 | B-全量 |
| 7 | 模型输出的 SQL 片段一律无法执行 | 安全集 `n1_sql_injection`；`tests/integration/services/test_safe_query_security.py`；`tests/unit/intent/test_whitelist.py::test_sql_in_metric_is_rejected`；`tests/integration/v2/test_merchant_chat_definitions.py::test_metric_definition_shows_both_calibers_and_sql_never_executed` | 通过 | B-全量 |
| 8 | `VIEWER_TOKEN` 调写端点、`memories/compress`、`ops/status` 全部 403 | `tests/api/test_viewer_token_scope.py::test_viewer_token_rejected_on_write_endpoints`、`::test_viewer_token_rejected_on_admin_only_reads` | 通过 | B-全量 |

**§12.1 八条本地证据全部通过。** 安全集里另有 MCP 类别（`n5_mcp.yaml`：撤销后仍可调用即失败）。`CURRENT_MILESTONE` 已切到 `"N5"`，`N5MCP` 已列入最低 3 条数量门槛；2026-10-05 定向运行数量与分层守卫 2 passed。N5 登记的用例本身此前也在门禁里执行。

## 12.2 双端闭环

| # | 条目 | 证据 | 状态 | 最近运行 |
| --- | --- | --- | --- | --- |
| 1 | S1–S8 端到端：S1–S4 浏览器 E2E，S5–S7 工作台 E2E，S8 标准 MCP 客户端 | S1：`shop/e2e/s1-presale-to-payment.spec.ts`；S2、S5、S6、S7：`frontend/e2e/n3/merchant-skills.spec.ts`；S3：`frontend/e2e/s3/s3-inventory-loop.spec.ts`；S4：`frontend/e2e/s4/` + `shop/e2e/s4/`；S8：`backend/tests/integration/mcp/test_standard_client.py`。后端同名场景 `backend/tests/e2e/test_s1…s7_*.py` | 通过 | C-E2E、C-S4、M-S3、M-S4、M-N3、B-全量 |
| 2 | 并发下单不超卖；支付与超时关闭并发只有一方生效 | `tests/integration/v2/test_checkout_concurrency.py::test_many_buyers_never_oversell`、`::test_last_unit_race_has_exactly_one_winner`；`tests/integration/v2/test_payment_race.py::test_pay_and_timeout_job_race_has_one_winner` | 通过 | B-全量 |
| 3 | 重复提交订单 / 支付 / 关闭 / 批准 / 应用无二次副作用 | `tests/api/v2/test_shop_orders.py::test_duplicate_submission_replays_the_original_response`；`test_payment_race.py::test_pay_is_idempotent`、`::test_second_payment_with_new_request_id_is_illegal`；`tests/integration/v2/test_draft_apply.py::test_terminal_states_cannot_be_applied_again`、`::test_concurrent_apply_has_one_winner`；`tests/integration/v2/test_approval_evidence_db.py::test_concurrent_consumption_has_exactly_one_winner`；`tests/integration/jobs/test_run_scheduled.py`（关闭任务同一时间片只执行一次） | 通过 | B-全量 |
| 4 | 库存账本可重算出当前在库与占用 | `tests/integration/test_demo_determinism.py::test_catalog_stock_matches_initial_stock_ledger`；`tests/integration/v2/test_checkout_concurrency.py::test_order_writes_events_that_rebuild_the_projection`；`tests/integration/test_n1_c_core_migrations.py::test_product_stock_is_derived_and_cannot_oversell`、`::test_projection_rebuild_reports_drift_without_overwriting` | 通过 | B-全量 |
| 5 | 退货回补只在验货判定可售时发生 | `tests/integration/v2/test_after_sale_decision_handler.py::test_return_receipt_restocks_only_sellable_and_refund_uses_snapshot`；`tests/unit/services/v2/test_after_sale_decision_payload.py::test_receipt_requires_explicit_sellable_choice` | 通过 | B-全量 |

## 12.3 商家端质量

| # | 条目 | 证据 | 状态 | 最近运行 |
| --- | --- | --- | --- | --- |
| 1 | 每日简报同店同营业日只有一份当前版本，重新生成为版本替换 | `tests/integration/v2/test_daily_brief_repository.py::test_stage_or_replace_bumps_version_not_row_count`、`::test_concurrent_writes_never_lose_an_update`；`tests/integration/test_n1_c_aux_migrations.py::test_memory_isolation_source_and_daily_brief_uniqueness` | 通过 | B-全量 |
| 2 | 简报每条含问题、数字依据与下一步动作；缺数据条目显示缺什么 | `tests/integration/v2/test_merchant_brief.py::test_brief_items_trace_back_to_alerts_and_drafts`、`::test_brief_next_action_prompt_points_at_existing_abilities`；`tests/unit/services/v2/test_daily_brief.py::test_every_brief_item_carries_problem_evidence_and_next_action`、`::test_brief_item_says_what_is_missing_instead_of_estimating`（近 30 天无销量时条目写「可售天数未知」而不是估一个天数；2026-10-04 补测试，实现原本就如此，已做变异验证） | 通过 | B-矩阵 |
| 3 | 归因响应含数据截至时间、数据来源与指标定义版本 | `tests/unit/services/v2/test_attribution.py::test_response_always_carries_cutoff_source_and_version`；`tests/e2e/test_s5_attribution_loop.py` | 通过 | B-全量 |
| 4 | `gross_gmv` / `refund_amount` / `net_gmv` 与对账口径一致性：时区边界、退款跨日、订单取消、零值分母、未完整周期 | 同一真实 PostgreSQL 快照联合对账：`tests/integration/repositories/test_analytics_repository.py::test_gross_refund_and_net_reconcile_with_daily_ledger`（毛额 1000、退款 200、净额 800，并与逐日报表对齐）；时区边界：`test_attribution.py::test_today_is_taken_in_business_timezone_across_utc_midnight`；退款跨日：`tests/integration/v2/test_after_sale_decision_handler.py::test_refund_and_return_use_business_day_across_utc_midnight`；订单取消：`tests/integration/repositories/test_analytics_repository.py::test_gmv_by_category_still_excludes_disqualifying_order_status`；零值：`test_attribution.py::test_near_zero_change_reports_absolute_contribution`、`::test_net_gmv_treats_missing_refunds_as_zero`；未完整周期：`::test_incomplete_week_uses_equal_length_comparison` | 通过 | B-全量；2026-10-05 联合对账 1 passed |
| 5 | 目标对象版本变化后草稿应用被拒绝并保持暂存 | `tests/integration/v2/test_draft_apply.py::test_stale_base_rejects_and_keeps_staged` | 通过 | B-全量 |
| 6 | 导出 CSV 的 `=`、`+`、`-`、`@` 开头单元格已转义；创建与下载各有审计 | `tests/api/test_exports.py::test_download_escapes_formula_looking_cells`；`tests/integration/v2/test_merchant_chat_export.py::test_export_is_created_and_audited`、`::test_signed_download_is_audited_separately_from_creation` | 通过 | B-全量 |
| 7 | 指标详情展示业务口径、受控 SQL 口径等；未命中正式资产显示「待核验」 | `tests/integration/v2/test_merchant_chat_definitions.py::test_metric_definition_shows_both_calibers_and_sql_never_executed`、`::test_unverified_metric_returns_status_without_llm_generation`；`tests/unit/tools/merchant/test_definitions.py::test_unverified_metric_is_labelled_not_generated`；浏览器 S7 | 通过 | B-全量、M-N3 |
| 8 | 时间趋势默认折线，分类结果可在后端声明的柱状 / 饼图集合内切换，数据点来自查询结果 | 后端：`tests/unit/services/v2/test_visualization.py::test_attribution_defaults_to_bar_or_pie`、`tests/integration/v2/test_merchant_chat_visualization.py`；前端：`frontend/src/utils/chart.spec.ts`、`components/home/HomeTrendChart.spec.ts`、`components/insights/InsightPanels.spec.ts`「类型切换只提供后端声明且前端支持的图表类型，点击后摘要按新类型重算」「后端只声明一种类型时不显示类型切换」（2026-10-04 补测试并做变异验证） | 通过 | B-全量、M-单测 |

## 12.4 顾客端质量

| # | 条目 | 证据 | 状态 | 最近运行 |
| --- | --- | --- | --- | --- |
| 1 | 属性缺失时说明缺失并生成内容缺口信号，不给推断值 | `tests/integration/v2/test_content_gap_tool.py::test_missing_required_attribute_counts_content_gap`、`::test_content_gap_signal_never_stores_question_text`；`tests/e2e/test_s2_content_gap_loop.py`；浏览器 S2 | 通过 | B-全量、M-N3 |
| 2 | 购物车只接受本轮对话工具返回过的商品 | `tests/integration/v2/test_shop_chat.py::test_agent_cannot_add_product_not_seen_in_conversation`、`::test_agent_cannot_reach_another_shops_product` | 通过 | B-全量 |
| 3 | 结账重算价格与库存，不一致时提示不可用项 | `tests/api/v2/test_shop_orders.py::test_order_is_priced_by_the_backend_and_reserves_stock`、`::test_client_supplied_amounts_are_rejected`、`::test_insufficient_stock_lists_the_line_with_only_a_band`、`::test_delisted_line_is_product_not_in_scope` | 通过 | B-全量 |
| 4 | 顾客记忆可查看、逐条删除、一键关闭（先确认并清空）；超过 180 天自动清理 | `tests/api/v2/test_shop_memory.py::test_bound_customer_can_list_and_delete_memory`、`::test_disabling_memory_requires_confirmation_and_purges`；`tests/integration/v2/test_customer_memory_store.py::test_read_excludes_expired_without_renewing_retention`；`tests/integration/v2/test_memory_maintenance.py::test_purge_only_expired_customer_facts`；清理任务已接入 Cron 分发器（`purge_expired_customer_memory`）；`shop/e2e/memories-responsive.spec.ts` | 通过 | B-全量、C-E2E |
| 5 | 切换语言时缺译文回退源文并标注 | `shop/src/components/components.test.tsx`「机器译文和缺译回退在顾客商品卡片上明确标记」「属性名和值分别标记机器译文与源文回退」；`shop/e2e/storefront-home.spec.ts`「语言切换后界面、商品和回答使用英文」 | 通过 | C-单测、C-E2E |
| 6 | 两端均可新建、浏览、跳转、删除自己的会话；移动端无横向溢出 | 后端 `tests/integration/v2/test_conversations.py`；商家端 `frontend/e2e/ops-assistant-conversation.spec.ts`（6 例）、`e2e/s3/ops-assistant-responsive.spec.ts`（375px）；顾客端 `shop/e2e/conversations-responsive.spec.ts`（375px） | 通过 | B-全量、M-E2E、M-S3、C-E2E |

## 12.5 Agent 内核

| # | 条目 | 证据 | 状态 | 最近运行 |
| --- | --- | --- | --- | --- |
| 1 | 轮数、工具次数、LLM 次数、墙钟时间、token 五类上限各有触发测试 | `tests/unit/agent/loop/test_runner.py::test_stops_at_max_turns_and_discloses`、`::test_batch_exceeding_tool_limit_is_not_executed`、`::test_worst_path_one_call_short_stops_on_budget`、`::test_wall_clock_interrupts_read_only_tools`、`::test_tokens_over_limit_stop_on_budget` | 通过 | B-全量 |
| 2 | 安全拦截导致回合终止，不作为工具结果继续 | `test_runner.py::test_fatal_error_terminates_without_reviewer`；`tests/integration/v2/test_merchant_tools.py::test_restock_for_another_merchants_product_is_fatal` | 通过 | B-全量 |
| 3 | Skill 加载器拒绝白名单外路径；触发与误触发均有测试 | `tests/unit/skills/test_path_policy.py`（其中 3 例符号链接用例在 Windows 上因权限跳过，曾在 Linux 容器补跑）；`tests/unit/skills/test_real_skill_cases.py`、`test_customer_skill_content.py`、`test_merchant_skill_content.py`；`docs/history/eval/n1-n4-n3-manual-review-2026-10-05.md`（真实首次选择 46/48） | 通过（结构）；真实首次选择有 2 例未满足冻结断言 | B-全量；2026-10-05 人工复核 |
| 4 | 压缩后仍保留工具来源、数据截至时间与草稿版本（专项评测通过） | `tests/eval/test_n4_compaction_e5_fake.py`；`docs/history/eval/n4-e5-compaction-fake.md`（Fake）；`docs/history/eval/n1-n4-final-acceptance-synthesis-2026-10-05.md` 与已锁定盲审：历史真实来源保留 `TOOL_RESULT_PRUNING` 6/12、`SUMMARIZATION` 7/12。2026-10-06 冻结复测自动判分为当前默认清理 3/12、摘要 10/12，详见 `docs/history/eval/n4-e5-compaction-retest-2026-10-06.md`；两种判分口径不能直接比较 | 未通过；最新真实自动判分不足，独立盲审未完成 | 2026-10-06 冻结复测 |
| 5 | 记忆抽取异步失败不影响主回答；敏感信息误写率有量化报告 | `tests/integration/v2/test_memory_outbox.py::test_failed_extraction_retries_only_to_limit`、`tests/unit/memory/test_async_delivery.py`；`docs/history/eval/n1-n4-rag-memory-manual-review-2026-10-05.md`（收紧后真实错误写入率 2/40，敏感诱导零泄露） | 通过（量化报告已具备）；MEM-016 的多句更正误抽为遗留 | B-全量；2026-10-05 逐条复核 |
| 6 | 混合召回相对关键词基线在 Recall@k 与引用正确率上有可比报告；重排若保留须有收益证据 | `docs/history/eval/rag-baseline.md`、`rag-hybrid.md`（Recall@5 0.759 → 0.907，本地推理）；`docs/history/eval/n1-n4-rag-memory-manual-review-2026-10-05.md`（冻结口径下真实引用正确率：关键词 85.19%、混合 90.74%；忠实度均 98.15%）；重排器未保留，报告含否决依据 | 通过（可比报告已具备）；召回与轻度越界推断缺陷继续遗留 | 2026-10-05 人工复核 |
| 7 | MCP 只读工具可被外部客户端调用，凭证可撤销，撤销后立即失效 | `tests/integration/mcp/test_standard_client.py`（官方 SDK 客户端，协议 `2026-07-28`）；安全集 SEC-N5MCP-002 | 通过 | B-全量 |

## 12.6 评测与运维

| # | 条目 | 证据 | 状态 | 最近运行 |
| --- | --- | --- | --- | --- |
| 1 | 评测集 ≥100 条并按 Skill / 角色 / 风险 / 语言分层，含多轮 | `tests/eval/test_quality_scenarios.py::test_main_evaluation_set_meets_the_e1_size_and_layers`：主评测集 104 条（安全 79、质量基线 6、质量场景 19），多轮 36 条，无 skip。2026-10-04 之前为 96 条，本次登记 N5 顾客端快捷提问 8 条后达标。另有专项集：压缩 30、记忆 40、RAG 64 | 通过 | B-增量 |
| 2 | CI 的 Fake LLM 回归确定性通过；`skip` 不计入分母 | `tests/eval/test_eval_harness.py::test_skipped_cases_excluded_from_denominator`；`tests/eval/test_security_gate.py::test_security_set_has_no_skips`；`tests/unit/core/test_ci_contract.py`。**GitHub Actions 工作流的改动尚未提交，远端 CI 没有在当前代码上跑过**——这里的「通过」只指本地运行 | 通过（本地）；远端 CI **未执行** | B-全量 |
| 3 | 关键安全集零失败作为合并门禁 | `tests/eval/test_security_gate.py`（79 条全部通过）；`test_ci_contract.py::test_ci_requires_database_and_executes_security_and_timing_gates` | 通过（本地）；远端门禁 **未执行** | B-增量 |
| 4 | 看板展示每回合 token、成本、耗时、降级原因；成本绑定价格版本 | 后端 `tests/api/test_admin_ops.py::test_ops_status_reports_per_turn_tokens_cost_latency_and_degradation_reasons`、`tests/integration/v2/test_turn_metrics.py`、`tests/integration/repositories/test_llm_cost_pricing.py`；前端 `OpsStatusView.spec.ts`、`e2e/ops-status.spec.ts`。2026-10-04 之前这条不成立：看板只有当日合计，且 v2 回合的降级从不计数，本次补齐 | 通过 | B-增量、M-单测、M-E2E |
| 5 | LangGraph 基线可运行并产出与新循环的对照报告，且未部署到生产 | `tests/eval/test_baseline_freeze.py`、`tests/eval/test_baseline_comparison.py`；报告 `docs/history/eval/n2-baseline-comparison.md`（Fake，只证明结构） | 通过 | B-全量 |
| 6 | §10.1 基准环境下的性能报告满足全部阈值 | 无。基准环境需要生产变更同意 | 未执行 | — |

## 汇总

| 小节 | 条数 | 通过 | 未通过 | 含待授权 / 未执行的条目 |
| --- | --- | --- | --- | --- |
| 12.1 安全与隔离 | 8 | 8 | 0 | — |
| 12.2 双端闭环 | 5 | 5 | 0 | — |
| 12.3 商家端质量 | 8 | 8 | 0 | — |
| 12.4 顾客端质量 | 6 | 6 | 0 | — |
| 12.5 Agent 内核 | 7 | 6 | 1（#4 真实来源保留） | #3 首次选择、#5 多句更正、#6 召回与越界推断仍有已记录缺陷 |
| 12.6 评测与运维 | 6 | 5（其中 2 条只在本地成立） | 0 | #2、#3 远端 CI 未执行；#6 性能基准未执行 |

**2026-10-05 复核后有 1 条「未通过」：§12.5 #4 的真实来源保留不足。** 它与 N4-3「有条件通过、缺陷未清零」的汇总判定一致。§12.3 #4 曾缺同一真实数据快照下的三指标联合对账证据，已补集成测试并在独立的一次性 PostgreSQL 库运行通过。初稿里有两条因缺测试标为未通过（§12.3 #2 简报缺数据的表述、#8 图表类型切换），
核对实现无误后补了测试并做了变异验证，已改为通过。取证过程中另外发现并修复了两处真实缺口：

1. §12.6 #4：运维看板只有当日合计，没有每回合 token / 成本 / 耗时与降级原因；且 v2 两端回合的降级从不计入 `degraded_count`；
2. §12.6 #1：主评测集只有 96 条，不足 100 条。

**不能据本矩阵宣称的事：** N5 新增能力在真实模型下的回答质量；N4 已发现的真实质量缺陷已修复；远端 CI 门禁；性能阈值；
公网部署前置条件（未部署）。§12.1 的本地证据全部通过；§12.5 #4 仍未达标，且 N5 待授权、未执行项尚在，不能宣称 §12 全量通过。

## 附：前端 E2E 验证缺口复核（Task 9 步骤 1a，D-N5-2）

两页合并时整份删除的 4 份商家端 E2E，逐行落点如下（2026-10-04 核对并实际运行）：

| 已删除 | 处置 | 现有证据 | 状态 |
| --- | --- | --- | --- |
| `conversation.spec.ts`（13 例） | 以 `e2e/support/v2MerchantMock.ts` 重建 | `frontend/e2e/ops-assistant-conversation.spec.ts` 6 例：发送并展示回答、打开历史对话、新建对话、删除会话、采纳与点赞回执、切换商家清空；375px 的新建 / 浏览 / 跳转 / 删除由 `e2e/s3/ops-assistant-responsive.spec.ts`（真实后端）与顾客端 `shop/e2e/conversations-responsive.spec.ts` 覆盖。入口已按 W 改为首页 + 助手栏，断言未删 | 已重建（M-E2E、M-S3、C-E2E 通过） |
| `localization.spec.ts` | 重建 | `frontend/e2e/ops-assistant-localization.spec.ts` 2 例；§10.6「缺译文回退源文并标注」由 `shop/src/components/components.test.tsx` 两例组件测试覆盖，不另补浏览器用例 | 已重建 + 替代证据（M-E2E、C-单测 通过） |
| `ops-dashboard.spec.ts` | 随 D-N5-1 新页面重写 | `frontend/e2e/ops-status.spec.ts` 3 例：令牌闸门、三级预算 / 每回合统计 / 降级原因 / Chat BI、只读且不露凭证、英语、375px 不溢出 | 已重写（M-E2E 通过） |
| `real-api/analytics.spec.ts`（8 例） | **浏览器层不重复验证**：对应的 v1 前端已下线 | 替代证据：v1 后端能力由 `backend/tests/api/test_chat.py`、`test_metrics.py`、`test_exports.py`、`test_conversations.py` 覆盖；v2 导出与隔离由 `backend/tests/integration/v2/test_merchant_chat_export.py`、`backend/tests/e2e/test_s5_attribution_loop.py`、`test_s7_definitions_loop.py` 与安全集（`n1_cross_tenant`、`w_merchant_orders`、`n2_merchant_feedback_cross_tenant`）覆盖 | 不重建（替代证据在 B-全量 中通过） |

顾客端的 `conversations-responsive.spec.ts`、`memories-responsive.spec.ts`、S1、S4 均为 WS 改过入口后的版本，375px 与 §12.4 的断言都在（C-E2E 10/10、C-S4 1/1）。

## 附：裁定一致性复核（Task 9 步骤 1）

对 `n5-final-eval-and-closeout` Task 9 两张表登记的 22 项裁定做了**锚点核对**：每项在 PRD、契约、实现、测试里各取一处，
确认对应内容确实存在（脚本逐项匹配，2026-10-04）。这是「每一层都有落点」的核对，不是逐句审计。

- 22 项全部在各层找到落点：最小简报与完整简报、记忆 Skill、会话目录、v1 记忆不迁入、售后决定走草稿、MCP 凭证只经命令行、
  访客购物车、售后各跳、批量草稿、属性 Mapping、两页合并、D-N4-1 至 D-N4-3、D-N5-1、W、WS、全文档检索、嵌入模型选型、
  外部 Neon、D-N5-4、压缩策略选型依据（后端计划 §6.12 已写入保守默认 `TOOL_RESULT_PRUNING`）。
- D-N5-2 的处置见上一节；D-N5-3 是排期裁定，已随 N4 完成失效，无实现层。

**D-N5-4 位置措辞已同步**：W 重设计之后桌面端没有顶栏，实现位于侧栏账号区上方。2026-10-04 本地联调中用户看过侧栏位置后要求入口更明显，未要求改回顶栏；现按该反馈将 PRD M1、§10.7、§15、前端计划、实施计划和索引统一为侧栏。此项不再记为实现与 PRD 不一致。

N5 实施中新增、已在发现当时同步到契约的三处：访客身份说明（后端计划 §6.13）、运维端点两次字段扩展（「运维端点」一节）、
Cron 状态表（`docs/database.md`、`docs/deployment.md`）。它们都没有改变 PRD 的范围或验收标准。
