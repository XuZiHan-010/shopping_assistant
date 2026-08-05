# Chat 契约 Fixture

> 本目录由 `scripts/export_chat_fixtures.py` 生成，请勿手改。除 `IDENTITY` 仍是 B4 受控空结果外，
> 载荷均来自 `MerchantQaGraph` 在 `FakeLlmClient` + `_StubQueryService` 下的真实输出。

| 文件 | 触发问题 | 验证点 |
| --- | --- | --- |
| `metric-refund.json` | 最近7天退货量趋势 | METRIC + REFUND 分类，含真实数据行 |
| `metric-gmv.json` | 昨天总 GMV 是多少？ | METRIC + TRADE 分类，含真实数据行 |
| `detail-order.json` | 查看最近订单明细 | DETAIL 含真实数据行与截断标记 |
| `identity-profile.json` | 我的商家资料是什么？ | IDENTITY 的 B4 受控空结果 |
| `rule-platform.json` | 我要货品上架，具体规则有吗？ | RULE 模式 |
| `chat-greeting.json` | 你好 | CHAT + [NONE] |
| `invalid-refused.json` | 帮我删除订单 A1 | INVALID 拒绝语义 |
