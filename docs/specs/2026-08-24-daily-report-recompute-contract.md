# 每日经营日报管理员重算契约

## 目标

在不改变商家端 `GET /api/reports/daily` 幂等读取语义的前提下，为演示数据首次滚动、数据恢复或受控纠错提供显式的管理员重算入口。

## 接口

```text
POST /api/admin/reports/daily/recompute
```

该接口仅供运维通过 curl 或 Postman 调用，没有前端页面或前端领域模型消费者。

### 鉴权

只接受 `X-Admin-Token`。`Authorization` 不能替代管理员令牌。未提供令牌返回 `401 AUTH_REQUIRED`；令牌错误或管理员功能未启用时返回 `403 FORBIDDEN`。

### 请求体

```json
{
  "merchant_id": "uuid",
  "report_date": "YYYY-MM-DD",
  "reason": "Cron 首次滚动前生成的空数据缓存"
}
```

| 字段 | 约束 |
| --- | --- |
| `merchant_id` | 必填 UUID，且必须是服务端配置的三家演示商家之一 |
| `report_date` | 必填日期；不得晚于业务时区今日，且不得早于业务时区今日往前 179 天 |
| `reason` | 必填，去首尾空白后 1–200 字符 |

### 成功响应

返回 `200 DailyReportResponse`，结构与 `GET /api/reports/daily` 完全一致。`answer_id` 是本次重新物化后的日报 Answer 标识。

### 处理语义

1. 在同一事务中锁定指定商家及 `daily-report:{report_date}` 对应的日报 Answer。
2. 不存在旧日报时直接物化；存在且没有反馈时删除旧 Answer 并重新物化；存在反馈时不做任何数据修改。
3. 重算只影响指定商家与指定日期；普通日报读取仍使用原有幂等键，不接受日期参数。
4. 操作完成后以独立审计事务写入 `DAILY_REPORT_RECOMPUTED`，元数据仅记录 `reason` 与 `report_date`，不得记录令牌、经营指标或完整响应。

### 错误契约

| 场景 | HTTP | 错误码 |
| --- | --- | --- |
| 缺少管理员令牌 | 401 | `AUTH_REQUIRED` |
| 管理员令牌无效 | 403 | `FORBIDDEN` |
| 商家不存在 | 404 | `NOT_FOUND` |
| 商家不是演示商家 | 403 | `FORBIDDEN` |
| 请求体缺字段、日期越界、未来日期或 `reason` 不合法 | 422 | `INVALID_REQUEST` |
| 既有日报已有反馈 | 409 | `DAILY_REPORT_FEEDBACK_CONFLICT` |
| 并发操作未取得可重算状态 | 409 | `REQUEST_IN_PROGRESS` |
| 数据库不可用 | 503 | `DATA_SOURCE_UNAVAILABLE` |

## 测试边界

必须覆盖：正常重算、非演示商家拒绝、未来日期与 180 天外日期拒绝、空 reason 拒绝、已有反馈冲突、管理员令牌失败、并发重算收敛、审计记录与商家隔离。测试仅使用 Fake LLM 或不构造 LLM。
