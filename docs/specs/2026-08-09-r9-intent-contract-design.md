# R9 意图、会话详情与导出契约设计

**状态：待用户审阅（2026-08-12）**

本设计依据参考项目的 `SemanticLayerService`、`DorisQueryService`、`ConversationContextStore`、
`PromptLoopAnalysisService`、`CsvExportService` 与 `VisualizationService` 的只读审计形成。它规定后续
Task 8–12 的共同边界，不直接修改生产代码。

## 1. 纯明细

LLM 仅输出 `analysis_requested: bool`。后端在 `DETAIL && !analysis_requested` 时进入纯明细模式：
表格和元数据照常返回，`ChatResponse.answer` 必须为 `""`，不生成建议和分析正文。其它回答模式的
`answer` 必须非空；此规则由 Pydantic 模型校验，违反时为内部契约错误。

## 2. 跨业务计划

`CrossBusinessPlan` 仅允许 `ORDER_TO_REFUND`、`ORDER_TO_GOODS`、`ORDER_REFUND_GOODS` 和受长度限制的
`sub_order_no`。查询总是先在已验证 `merchant_id` 内定位订单，再以受控关系查退款或商品。

计划不存在时正常查询。计划对象存在但字段非法时，在外层 `QueryIntent` 的 before validator 捕获其
子模型校验错误，清空计划、保留 VALID 基础意图、写入“计划已拒绝”的语义备注，并将该说明展示给用户。
这是与生成指标不同的可见回退，不得改为 INVALID。

## 3. 临时分组指标

`GeneratedMetricPlan` 包含展示用 `name`、`unit`，可选 `group_by`，以及成对出现的
`filter_column` / `filter_value`。列白名单只有 `spu_id` 与 `address_city_name`；没有分组时仅允许合法的
城市筛选。类别决定固定聚合模板（交易或退款），而非由名称、单位、自由公式或模型 SQL 决定。

形状或维度不合法时，整条意图必须转为 `INVALID`、类别 `UNKNOWN` 并附拒绝说明。结果超过展示上限时
创建受保护的导出记录；下载按记录的受控查询规格重放生成指标查询，不能误走明细导出。

## 4. 会话详情

助手消息添加 `answer_payload`，包含回答 ID、回答模式、步骤、质量轨迹、降级状态、当前反馈状态和表格元数据。
装配层读取 JSONB 后先脱敏：永不回传完整 `data_rows`、`export` 或签名 URL。前端据元数据显示“历史明细未保留”，
而非空白消息。`answer_id`、`is_adopted`、`reaction` 必须一并提供，以免历史加载覆盖已保存反馈。

## 5. 兼容策略与测试

采用 `upgrade_payload()` 的内部兼容升级器，而非迁移全部历史 JSONB：在 `_stored_response()` 校验前为旧 payload
补齐新增字段的安全默认值。理由是 answers 表可能很大，逐行迁移风险和回滚成本高。每次新增必填字段必须补一条
旧 payload 幂等重放测试。

## 审阅结论

实现 Task 8 前，需用户确认上述五项业务契约及兼容策略；确认后按 Task 8、9、10、11、12 分切片 TDD 实施。
