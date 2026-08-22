# 每日经营日报：契约与业务规则设计说明

**日期：2026-08-21　状态：已裁定（Q1–Q8 全取推荐选项 A，用户 2026-08-21 确认，无例外）**

本文件是 P1 每日经营日报的设计前置。**它不是实施计划**——前一版计划直接写了任务步骤，结果四处偏离参考语义与我方既有契约，被审查驳回。本文件先把契约和业务规则定清楚，裁定后再出实施计划。

依据：`AGENTS.md` R9（参考项目是需求基准）、`docs/PRD.md`、`docs/frontend-development-plan.md` §7.1、`docs/backend-development-plan.md` §8。

---

## 1. 参考实现事实（已读源码核对）

`DailyReportService.java:31-49`、`DailyReportResponse.java`、`DailyReportScheduler.java`、`ChatController.java:77`。

### 1.1 端点与响应

- 路径：`GET /api/daily-report`
- 响应字段：`merchantId`、`merchantName`、`date`、`metrics: Map<String, Object>`、`suggestions: List<String>`
- `date` = `LocalDate.now(Asia/Shanghai).minusDays(1)`

### 1.2 六项指标

`metrics` 是有序 Map，键是中文展示名，值取自 `ads_merchant_profile` 昨日画像：

| 展示名 | 参考字段 |
| --- | --- |
| 昨日总gmv金额 | `order_gmv_amt_1d` |
| 昨日下单用户量 | `order_user_cnt_1d` |
| 昨日总订单量 | `order_cnt_1d` |
| 昨日交易成功订单量 | `trade_success_order_cnt_1d` |
| 昨日退货量 | `return_cnt_1d` |
| 昨日退款金额 | `refund_amt_1d` |

### 1.3 两条建议的确定性规则

数据源是 `recentProfile(merchantId, 7)` 的 **7 日求和**（不是环比）。

第一条按退款金额分叉：

- `sum(refund_amt_1d) > 0` → 「近 7 日存在退款金额，建议优先查看退货退款明细，定位高频原因并优化发货/售后说明。」
- 否则 → 「近 7 日退款压力较低，可以继续保持履约和售后响应稳定。」

第二条三分叉（按顺序判断）：

- `sum(cs_ticket_cnt_1d) > sum(order_cnt_1d) * 0.2` → 「客服工单相对订单量偏高，建议排查催单、物流和商品说明类问题。」
- 否则 `sum(goods_audit_reject_cnt_1d) > 0` → 「存在商品审核拒绝记录，建议复查商品图片、品牌资质和类目填写。」
- 否则 → 「建议继续关注 GMV、交易成功订单量和优惠使用效果，挑选转化较好的商品加大运营。」

无近 7 日数据时返回两条固定兜底文案。

### 1.4 定时推送

`DailyReportScheduler` 用 `@Scheduled(cron = "0 0 10 * * *", zone = "Asia/Shanghai")`，只对配置里的单个商家跑，**推送实现就是打一行日志**，注释写明「后续可替换为站内信、IM 或商家助手消息推送」。

---

## 2. 我方现状（已核对）

| 项 | 现状 |
| --- | --- |
| 服务 | `backend/app/services/` 下**无** `report_service.py` |
| 路由 | **无** `reports.py`；但 `AGENTS.md` §10.2 与 `docs/PRD.md` §11 已把 `GET /api/reports/daily` 写进 P1 清单 |
| 前端 | **无** `DailyReportCard.vue` |
| 定时任务底座 | **`backend/app/jobs/` 目录不存在**，`backend/railway.cron.json` 不存在，只有 `backend/railway.json` |
| 指标白名单 | `backend/app/analytics/contract.py:41-55` 共 9 个指标 |
| Answer 表 | `conversation_id` 是 **NOT NULL** 外键（`backend/app/models/answer.py:49-53`） |
| 商品审核 | `Product` 模型**无审核状态/拒绝字段** |

> **重要更正**：前一版计划声称可以「照抄既有 `backend/app/jobs/seed_demo_rolling.py` 并复用 Railway Cron 底座」。那些文件**在本分支不存在**——它们描述的是 `feature/answer-loop-demo-refresh` 分支的状态，而该分支从未合并。日报的定时推送必须**从零建**这套底座，不是复用。

### 2.1 六项指标的映射与缺口

| 参考字段 | 我方 `metric_code` | 结论 |
| --- | --- | --- |
| `order_gmv_amt_1d` | `gmv` | ✅ 对得上 |
| `order_cnt_1d` | `order_count` | ✅ |
| `trade_success_order_cnt_1d` | `successful_order_count` | ✅ |
| `return_cnt_1d` | `return_count` | ✅ |
| `refund_amt_1d` | `refund_amount` | ✅ |
| `order_user_cnt_1d`（下单用户量） | `paying_user_count`（付款用户数） | 🔴 **不是同一指标** |

`paying_user_count` 的实现是 `count(distinct buyer_key) filter (paid_at is not null)`（`backend/app/repositories/analytics.py:94-96`）——**下过单但未付款的用户不计入**。参考的 `order_user_cnt_1d` 是下单用户，口径更宽。数据层有能力算（`Order.buyer_key` 存在、`paid_at` 可空），只是没有这个指标。

第二条建议还需要 `goods_audit_reject_cnt_1d`，**我方无对应数据**（`Product` 无审核字段）。

---

## 3. 八个待决问题

### Q1 · 「昨日下单用户量」怎么办

| 选项 | 说明 |
| --- | --- |
| **A（推荐）新增 `ordering_user_count` 指标** | `count(distinct buyer_key)` 不加 paid 过滤，加进 `METRIC_SPECS` 与字段注释。日报口径与参考一致，且这个指标本身对商家有价值，问「昨天多少人下单」也能答 |
| B 用 `paying_user_count` 顶替并登记偏离 | 零新增代码，但日报会给出一个比参考口径小的数，且「下单用户量」这个展示名会名不副实 |
| C 展示名改成「昨日付款用户数」 | 诚实，但与参考日报的六项不再一一对应 |

推荐 A：新增一个白名单指标的成本远小于长期背一个口径不一致的日报。

### Q2 · 第二条建议的「商品审核拒绝」分支怎么办

我方无 `goods_audit_reject_cnt` 数据源。

| 选项 | 说明 |
| --- | --- |
| **A（推荐）降为两分叉并登记偏离** | 保留「工单占比过高」与「兜底运营建议」两支，删掉审核拒绝那支，在 parity-audit §5 登记原因（无数据源） |
| B 给 `Product` 加审核状态字段 | 要动 ORM + 迁移 + Seed + 演示数据生成器，为一条建议文案引入一整块商品审核域，YAGNI |
| C 用别的信号替代 | 需要先想清楚替代什么，容易变成编造 |

推荐 A。

### Q3 · 响应形状：`metrics` 用 Map 还是数组

参考是 `Map<String, Object>`（键为中文展示名）。我方指标体系以稳定的 `metric_code` 做机器键、中文名只负责展示。`AGENTS.md` §10.4 的“扁平 snake_case / 不使用嵌套对象”只约束 `ChatResponse`，**不能直接拿来约束本端点**；这里选择数组的理由是类型稳定、可扩展和与既有指标体系一致，不是假称全局禁止嵌套对象。

| 选项 | 说明 |
| --- | --- |
| **A（推荐）`metrics` 为对象数组** | 每项 `{metric_code, display_name, unit, value}`。与我方 `metric_code` 体系一致（parity-audit §5.1 已登记「用英文 code、中文名降为展示字段」这条偏离），前端渲染稳定，新增指标不改结构。需在 §5 登记「响应形状偏离参考的 Map」 |
| B 严格还原 Map | 键是中文，前端拿不到稳定 key，与 §5.1 已有的偏离自相矛盾 |

推荐 A，并作为 §5.1 的延伸登记。

### Q4 · `answer_id` 与「建议采纳」怎么落

`docs/frontend-development-plan.md:897` 明确要求：**日报响应返回 `answer_id`，采纳时调用 `POST /api/answers/{id}/feedback`，不新增接口。**

障碍：`Answer.conversation_id` 是 NOT NULL 外键，日报不属于任何对话。

| 选项 | 说明 |
| --- | --- |
| **A（推荐）为日报建一条有稳定类型的系统会话，并从普通会话列表隐藏** | 给 `Conversation` 增加 `conversation_kind: CHAT | DAILY_REPORT`（默认 `CHAT`），每个商家只建一条 `DAILY_REPORT` 会话；日报 Answer 挂在其下，`user_message_id` 留空。`GET /api/conversations` 只返回 `CHAT`。反馈接口零改动，且不靠易变标题识别系统会话 |
| B 放宽 `conversation_id` 为可空 | 一条迁移，但会削弱「回答必属于某会话」这个既有不变量，影响面比看起来大 |
| C 不返回 `answer_id`，日报建议不可采纳 | 与 F7 冲突，要先改前端计划 |

推荐 A。实现时增加数据库迁移，并用 PostgreSQL 条件唯一索引保证每个商家最多一条 `DAILY_REPORT` 会话；会话列表按 `conversation_kind` 过滤，**不得靠标题“每日经营报告”判断**。这样“是否隐藏”不再是藏在选项里的第九个未决问题。

### Q5 · 定时推送做到哪一步

底座要从零建：`backend/app/jobs/` 目录、`daily_report_push.py`、`backend/railway.cron.json`（无 `healthcheckPath`、无 `preDeployCommand`、`restartPolicyType: NEVER`）。

必须一并定的细节：

- **Cron 表达式**：Railway Cron 按 UTC，`10:00 Asia/Shanghai` = **`0 2 * * *`**（02:00 UTC）。参考的 `0 0 10 * * *` 是 Spring 六段式且带 zone，不能直接抄；
- **推谁**：参考只推配置里的单个商家。我方有多个演示商家 → 推全部 `is_demo=True AND status='ACTIVE'` 的商家，逐个独立事务、单个失败不影响其余（R5 隔离）；这是有意偏离，实施时必须登记到 `docs/yshopping-parity-audit.md` §5；
- **推送出口**：与参考一致，先落结构化日志，注释写明接入站内信/IM 后替换。**不引入 Celery/Redis**；
- **失败重试**：`restartPolicyType: NEVER` 意味着不自动重试，失败靠次日再跑 + 日志告警。

| 选项 | 说明 |
| --- | --- |
| **A（推荐）本轮只做端点与前端卡片，推送单列一个任务** | 日报能用、能看、能采纳；推送是纯运维增量，可与 Railway 控制台操作一起做 |
| B 端点 + 推送一起做 | 一次做完，但把「需要控制台操作才能验收」的部分绑进了主线 |

推荐 A。

### Q6 · 是否允许客户端指定日报日期

参考端点没有日期参数，永远返回业务时区的昨日；我方 `docs/backend-development-plan.md` 现有摘要却写了“日期参数”，两者冲突。若允许历史日期，还要定义可查范围、未来日期、无数据日期和时区解释，已经不是“每日卡片”的同一个最小契约。

| 选项 | 说明 |
| --- | --- |
| **A（推荐）本轮不接收日期参数，固定返回昨日** | 对齐参考语义；OpenAPI 里没有 query parameter，`report_date` 只出现在响应。将后端计划中的“日期参数”同步删除 |
| B 接受可选 `report_date` | 可兼作历史日报查询，但必须先补日期范围、权限和缓存/幂等规则 |
| C 必填 `report_date` | 变成通用历史报告接口，与首页“每日经营日报”用途及参考行为都不一致 |

推荐 A。以后若产品确实要日报历史，另设计历史列表或详情端点，不把范围暗塞进本轮 GET。

### Q7 · 同一商家同一日报日期重复读取是否幂等

日报响应要返回可反馈的 `answer_id`。如果每次 GET 都新建 Answer，同一天刷新页面会产生多个 id 和多份反馈，统计口径无法解释；若每次重算又复用 id，指标和建议还可能在同一天悄悄变化。

| 选项 | 说明 |
| --- | --- |
| **A（推荐）首次物化、同日复用同一 Answer** | 使用 `client_request_id = "daily-report:{report_date}"`，复用既有商家级幂等唯一约束；首次 GET 或 Cron 通过同一事务服务生成，之后返回同一 `answer_id` 和同一 payload。并发首次请求用冲突后重读收敛到同一行 |
| B 每次 GET 新建 Answer | 实现直观，但刷新会制造重复报告和分裂反馈，不可接受 |
| C 每次重算但复用 Answer | id 稳定、内容不稳定，用户已采纳的对象会被改写 |

推荐 A。Cron 与用户 GET 必须调用同一个 `get_or_create_daily_report()`，不能各自维护一套生成逻辑。

### Q8 · “采纳建议”按整份日报还是按单条建议

既有 `Feedback` 只关联 `answer_id`，没有 `suggestion_id`。日报固定两条建议，因此直接复用反馈接口时，采纳只能表达“采纳这份回答/本期建议集合”，不能精确表示采纳其中哪一条。

| 选项 | 说明 |
| --- | --- |
| **A（推荐）本轮按整份日报采纳** | 卡片只放一个“采纳本期建议”动作，提交到既有 `POST /api/answers/{id}/feedback`；文档和埋点口径明确为 answer-level |
| B 支持逐条建议采纳 | 必须给建议稳定 id，并新增关联表或扩展反馈模型、接口和前端交互；应单独设计 |
| C 日报不支持采纳 | 与前端计划 F7 的既定要求冲突 |

推荐 A。若后续运营分析确实需要逐条归因，再以独立需求扩展，不能让前端用数组下标伪装稳定建议 id。

---

## 4. 裁定后的契约草案（按各推荐选项）

若八个问题都取推荐选项，`GET /api/reports/daily` **不接收任何 query parameter**，响应形如：

```json
{
  "merchant_id": "…",
  "merchant_name": "Borough商家100",
  "report_date": "2026-08-20",
  "answer_id": "…",
  "metrics": [
    {"metric_code": "gmv", "display_name": "昨日总 GMV", "unit": "元", "value": "128350.00"},
    {"metric_code": "ordering_user_count", "display_name": "昨日下单用户量", "unit": "人", "value": "412"},
    {"metric_code": "order_count", "display_name": "昨日总订单量", "unit": "单", "value": "487"},
    {"metric_code": "successful_order_count", "display_name": "昨日交易成功订单量", "unit": "单", "value": "451"},
    {"metric_code": "return_count", "display_name": "昨日退货量", "unit": "件", "value": "23"},
    {"metric_code": "refund_amount", "display_name": "昨日退款金额", "unit": "元", "value": "4210.50"}
  ],
  "suggestions": ["…", "…"],
  "degraded": false,
  "degraded_reason": null
}
```

约束：

- **金额用 `Decimal`，不用 `float`**（`docs/PRD.md:726`）。序列化为 JSON 字符串以免精度在传输层丢失，前端按字符串渲染；非金额指标（用户数、订单量、退货量）用 `int`；
- 请求不接受 `merchant_id`、`report_date` 或其他 query parameter；商家只来自已验证身份，`report_date` 按业务时区 `Asia/Shanghai` 取昨日；
- 每个商家只有一条 `conversation_kind=DAILY_REPORT` 的系统会话，受数据库条件唯一索引保护；普通会话列表只返回 `CHAT`，不靠标题过滤；
- 同一 `(merchant_id, report_date)` 首次物化后不可变，重复或并发请求返回同一 `answer_id` 与同一 payload；幂等键为 `daily-report:{report_date}`，GET 与未来 Cron 共用同一个 service；
- **`degraded` / `degraded_reason` 必填**（R7）：查询失败时 `metrics` 为空数组、`degraded=true` 并写明原因，**不得返回一堆 0** 让商家以为昨天没生意；
- `suggestions` 恒为 2 条（含无数据时的兜底两条）；`POST /api/answers/{id}/feedback` 的采纳语义覆盖整份日报/两条建议集合，不代表某一条建议。

---

## 5. 实施计划的前置条件

裁定完成后，实施计划必须覆盖以下测试，缺一不可：

- [ ] 六项指标齐全且顺序固定；
- [ ] 金额字段是 `Decimal` 而非 `float`（断言类型，不只断言数值）；
- [ ] `report_date` 是业务时区昨日，**含跨零点边界用例**（PRD 要求系统时钟可注入）；
- [ ] OpenAPI 中该 GET 没有 `report_date` / `merchant_id` query parameter，并同步删除后端计划中冲突的“日期参数”描述；
- [ ] 建议规则四个分支各一条：退款>0、退款=0、工单占比>20%、兜底；
- [ ] 无近 7 日数据时返回两条固定兜底；
- [ ] 查询失败时 `degraded=true` 且 `metrics == []`；
- [ ] 401：无 `Authorization`；
- [ ] **商家隔离**：端点不接受任何指定商家的查询参数，`merchant_id` 只来自已验证身份（R5）；
- [ ] 同一商家同一天重复 GET 返回同一 `answer_id` 与 payload，数据库只有一条对应 Answer；并发首次请求也收敛到同一行；
- [ ] 不同商家的同一日期互不复用 Answer，幂等键作用域符合既有商家级唯一约束；
- [ ] 每个商家最多一条 `DAILY_REPORT` 会话，且 `GET /api/conversations` 不返回该系统会话；普通 `CHAT` 会话不受影响；
- [ ] `answer_id` 可被 `POST /api/answers/{id}/feedback` 采纳（端到端一条），前端只有一个“采纳本期建议”动作，断言口径是整份日报而非数组中的单条建议；
- [ ] Q2、Q3 与“Cron 推全部活跃演示商家”的有意偏离登记到 `docs/yshopping-parity-audit.md` §5；Q4/Q6/Q8 的裁定同步到 PRD、前后端计划与 `AGENTS.md` 路径/职责索引。

**测试夹具注意**：`backend/tests/conftest.py:119` 提供的是 `client`，`backend/tests/api/conftest.py` 提供 `knowledge_admin_app` / `admin_client`。**不存在 `merchant_client` / `anonymous_client`**——实施计划里要用真实存在的夹具名，或显式新建并说明。

---

## 6. 裁定结果

Q1–Q8 全取推荐选项 A，用户 2026-08-21 确认，无例外。§4 的契约草案按此定稿，已据此写出
`plans/2026-08-21-daily-report-implementation.md`。
