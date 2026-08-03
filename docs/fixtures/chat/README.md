# Chat 契约 Fixture

> 本目录由 `scripts/export_chat_fixtures.py` 生成，请勿手改。
> 改动后端 `FakeAgent` 输出后必须重新导出，否则
> `backend/tests/api/test_chat_fixtures.py` 会失败。

前端 `src/api/adapters/chat.spec.ts` 直接消费这些文件，用于验证 Adapter 能正确
消化后端**真实产生**的载荷，而不是前端自己按类型造出来的载荷。

`id` 与 `created_at` 在导出时被冻结为确定性值（命名空间 UUID5 + 固定时间戳），
其余字段均为 `FakeAgent` 的真实输出。

| 文件 | 触发问题 | 验证点 |
| --- | --- | --- |
| `metric-refund.json` | 最近7天退货量趋势 | METRIC 八字段 + visualization + recommendations + FALLBACK 降级 |
| `metric-gmv.json` | 昨天总 GMV 是多少？ | METRIC + TRADE 分类 |
| `metric-order-detail.json` | 查看最近订单明细 | total_rows=327、truncated=true、export 为 null |
| `rule-platform.json` | 我要货品上架，具体规则有吗？ | RULE 模式下按模式字段全部缺省 |
| `chat-greeting.json` | 你好 | CHAT + [NONE] + degraded=false |
| `invalid-refused.json` | 帮我修改订单金额 | INVALID 拒绝语义 |
