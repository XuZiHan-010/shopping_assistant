# Chat 契约 Fixture

> 本目录由 `scripts/export_chat_fixtures.py` 生成，请勿手改。除 `DETAIL` 的 B4 受控空结果外，
> 载荷均来自 B3 `MerchantQaGraph` 在 `FakeLlmClient` 下的真实输出。

| 文件 | 触发问题 | 验证点 |
| --- | --- | --- |
| `metric-refund.json` | 最近7天退货量趋势 | METRIC 受控降级 |
| `metric-gmv.json` | 昨天总 GMV 是多少？ | METRIC + TRADE 分类 |
| `detail-order.json` | 查看最近订单明细 | DETAIL 的 B4 受控空结果 |
| `identity-profile.json` | 我的商家资料是什么？ | IDENTITY 的 B4 受控空结果 |
| `rule-platform.json` | 我要货品上架，具体规则有吗？ | RULE 模式 |
| `chat-greeting.json` | 你好 | CHAT + [NONE] |
| `invalid-refused.json` | 帮我删除订单 A1 | INVALID 拒绝语义 |
