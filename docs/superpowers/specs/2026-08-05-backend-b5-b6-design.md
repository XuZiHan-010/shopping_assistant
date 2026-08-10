# B5 回答审核与 B6 反馈导出设计

## 目标

完成后端 B5 与 B6：将 B4 的受控查询结果转换为可验证的回答、图表和建议；提供独立 Reviewer、商家反馈以及受签名保护的动态 CSV 导出。

## 范围与约束

- 只实现后端 B5、B6，不提前实现前端 F3 或 B7 的限流、日预算和 Railway 部署。
- 真实模型固定为 DeepSeek OpenAI 兼容 API 的 `deepseek-v4-flash`；单元与集成测试均使用 Fake LLM，不产生费用。
- 完成后只做一次经用户授权的真实端到端冒烟验证：正常为回答与 Reviewer 两次调用，发生一次重试时最多四次。
- LLM 不能生成或执行 SQL；商家身份只从可信 Bearer Token 得到；数据库异常和模型异常必须转为可见降级。
- 不执行 Git commit、push、tag 或 PR 操作。

## 方案选择

采用受控数据与结构化 LLM 混合方案：后端负责事实、图表、CSV、权限和签名；模型仅在给定事实包内起草回答、建议和审核结论。模型无效、超时或不可用时，系统用确定性事实回答并标注降级，不冒充模型分析。

## B5 架构

`query_data` 保留 B4 的 `QueryResult`。新的回答编排层消费问题、已验证 Intent、指标定义、查询结果和知识检索结果：

1. `VisualizationService` 从受控列和行生成图表。日期维度优先折线图，分类维度生成柱状图并允许饼图；无数据、规则回答和不安全字段不生成图表。
2. `AnswerService` 构造只含可展示数据、指标口径、查询范围和知识来源的事实包，并通过回答 Prompt 请求结构化草稿。草稿经 Pydantic 校验后才可使用。
3. 本地校验器验证关键数字、图表字段、至少两条建议（标题、依据、行动）、无数据文案、敏感字段和 `QueryResult.non_additive`。失败的草稿不得直接返回。
4. `ReviewService` 向独立 Reviewer Prompt 提交候选回答和同一事实包，只接收通过/问题列表，不允许重写回答。审核失败时重新编排一次；整个生成和审核循环最多两次。
5. 数据型回答成功时使用 `DATABASE`，同时真实使用知识时追加 `KNOWLEDGE`；规则回答按真实知识命中填 `KNOWLEDGE` 或 `NONE`。模型不可用、无效或审核无法执行时用 `FALLBACK` 并标记 `DEGRADED`。

最终状态为：审核通过 `PASSED`；两次审核均未通过 `FAILED`；模型或审核服务不可用 `DEGRADED`；无需审核的普通聊天/规则无模型路径为 `NOT_RUN`。`quality_attempts` 记录真实尝试次数，`quality_notes` 只记录可展示的校验或审核摘要。

## B6 架构

### 反馈

增加 `POST /api/answers/{id}/feedback`。请求显式传入采纳状态和可空的互斥反应（LIKE / DISLIKE）。Repository 以 `(merchant_id, answer_id)` 唯一约束 upsert，重复请求稳定返回同一最终状态。回答必须属于当前商家；跨商家 ID 走既有范围服务并记录审计。

### CSV 导出

新增 `export_files` ORM 与迁移，记录 `merchant_id`、源回答、受控 `ExportSpec`、过期时间和创建时间。只有 DETAIL 成功查询且存在 `ExportSpec` 时才创建记录。ChatService 在回答持久化前创建该记录，并将占位 `ExportInfo` 替换为带签名的真实下载 URL。

`GET /api/exports/{id}` 不要求 Bearer Token。URL 携带导出 ID、商家 ID、到期 Unix 时间和 HMAC 签名；签名覆盖这三项。服务端校验签名、到期时间和记录归属后，使用保存的受控规格重新执行限定查询，动态输出 UTF-8 BOM CSV。列名来自 B4 明细规格；以 `=`, `+`, `-`, `@` 起始的字符串在写出前加单引号。响应加 `Content-Disposition` 与 `Referrer-Policy: no-referrer`，不记录完整签名 URL。

新增 `EXPORT_SIGNING_SECRET` 配置项。它必须只来自环境变量；不复用 LLM Key 或管理员令牌。生产环境缺失该值时导出功能拒绝启用。

## 文件边界

- `app/prompts/answer.py`、`app/prompts/reviewer.py`：仅负责模型提示词。
- `app/services/answer_service.py`、`visualization_service.py`、`review_service.py`：分别负责草稿、图表与审核。
- `app/services/feedback_service.py`、`export_service.py`：分别负责商家反馈与签名/CSV。
- `app/repositories/answer.py`、`export.py`：只负责回答反馈和导出记录的数据访问。
- `app/api/routes/feedback.py`、`exports.py`：只负责认证、参数校验和服务调用。
- `app/schemas/feedback.py`、`exports.py`：稳定的 API 输入输出契约。

## 验证

- 对回答、图表、局部校验和 Reviewer 循环写单元测试，确认每个新增行为先红后绿。
- 对反馈与导出写真实 PostgreSQL 集成测试：幂等、跨商家、15 分钟过期、签名篡改、BOM、中文表头、公式注入。
- 运行后端全量 pytest、Ruff、格式检查、mypy、OpenAPI 导出和前端生成类型漂移检查。
- 所有离线验证通过且用户填写 Key 后，执行一次真实 DeepSeek 冒烟请求并报告实际调用次数与响应的降级状态。
