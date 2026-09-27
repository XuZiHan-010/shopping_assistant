# N3 阶段 C · 商家经营 Skill 实施计划

> **给执行者：** 用 `superpowers:executing-plans` 逐任务推进。步骤用 `- [ ]` 复选框跟踪。
> **本计划不含任何 Git 提交步骤**（R2）。全程 Fake LLM，零费用。
> 简报的真实生成、定时预生成的首次上线均属 R3 范围，需单独授权。
> **阶段定位：** N3 分 A / B / C 三阶段，总览见 `plans/2026-09-24-n3-module-roadmap.md`。
> 2026-09-24 重排：原 Task 7 的「客服回复」Skill、售后类顾客信号与 S4 端到端，以及原 Task 8 的「售后与顾客信号」界面，
> 已移入阶段 B（`n3-customer-skills-and-after-sales` Task 10–13）；本计划保留 6 个经营 Skill，新 Task 7 只做内容缺口信号。
> 这样本计划不再整份等待售后状态机：Task 0、1、4、5、6 在阶段 A 完成后即可与阶段 B 并行。

**目标：** 完成 PRD M2–M8 商家端 6 个 Skill 与内容缺口信号，收口 **S2、S5、S6、S7** 四条场景，
并在商家 Skill 迁完后完成 PRD §15 N2 留下的「v2 运营助手页与 v1 分析助手是否合并」评审。

**架构：** **v1 已经实现的领域能力一律包成工具复用，不重写**——受控查询（`services/safe_query.py`）、
指标目录（`metrics/catalog.py`）、导出服务（`services/export_service.py`）、可比周期（`intent/models.py` 的 `ComparisonMode`）、
知识检索（`knowledge/retrieval.py`）。工具**直接调用这些服务，不经过冻结的 `graph.py`**（§5.6）。
所有写能力都是 `WritePolicy.MERCHANT_DRAFT`（D17：无自动执行模式），应用侧处理器挂在阶段 A 的草稿分派表上。

**技术栈：** Python 3.12、FastAPI、pytest；前端 `frontend/`（Vue）。

**规格来源：** PRD M2–M8、S2、S5–S7、§10.1、§15 N2（两页合并评审）；融合决策 D4、D11、D17–D19、O3、Q4–Q9；
后端计划 §6.3、§6.4、§6.9、§6.11；契约 §8.12–§8.13。

---

## 入口条件

> **预写计划不是已验证实现。** 本计划最初写于上游代码尚不存在时；2026-09-24 已按 N2 实际代码核对一轮（见下），
> 开工前仍须再核对一次。不一致时先按 PRD → 契约 → 计划的顺序修正，**再动代码**，不得在实现里默默适配或绕过。

- [ ] 阶段 A（`n3-skill-loader`）Task 1–6 已完成：Skill 能加载；草稿分派表可注册新种类；
- [ ] `n2-merchant-drafts-and-inventory`、`n2-merchant-vue-v2-migration` 已通过 N2 验收（审批界面、最小简报、`/ops-assistant` 可复用）；
- [ ] **M5、M6 在库**（2026-09-24 已核对模型层，开工时对真实库再查）：`coupons`、`guardrail_configs`、`customer_signals`、
      `daily_briefs`（`uq_daily_briefs_merchant_date`）；
- [ ] **复用的 v1 服务接口与本计划描述一致**（2026-09-24 已核对存在性）：`intent/models.py:48` `ComparisonMode`、
      `services/export_service.py` 约 307 行的公式注入转义、`metrics/catalog.py` 的 `UNVERIFIED` 状态、`knowledge/retrieval.py`；
      开工时逐个读签名，如需改签名**先确认 v1 零回归**；
- [ ] Astra「入口-N3」中本计划部分已核对。

与阶段 B 的任务级依赖**不写在入口**，而写在各自任务开头的前置复选框：Task 2（完整简报）、Task 3 步骤 3（S2）、
Task 7（内容缺口信号）需要 B Task 11 的顾客信号服务。

---

## 全局约束

- 中文（R1）；**不执行 Git 操作**（R2）；**不调用真实 LLM**（R3）。
- **模型不写 SQL、不选数据源、不定指标公式、不产生图表数据点**（R4、D19 总边界）。
- **缺数据就显示缺数据**：不用估算值、示例值或模型常识补齐（D17④）。
- **不得把退款冲减后的值称为 GMV**（O3）。
- **不做营销活动 Skill**（D4）。
- **不修改 `app/agent/graph.py`**；**不改阶段 A 的加载器与分派骨架**，要改先回阶段 A 计划。
- 客服回复、售后类信号与售后界面属于阶段 B，本计划不重复实现。

---

## 6 个 Skill 与其工具

| Skill | 来源 | 工具（`WritePolicy`） | 复用 |
| --- | --- | --- | --- |
| 业绩洞察 | 蓝图 `performance-insights` | `query_metrics`、`attribute_change`（RO） | `safe_query`、`ComparisonMode` |
| 库存运营与每日简报 | 蓝图 `inventory-operations` | `get_inventory_alerts`（RO）、`draft_restock`（DRAFT）、`regenerate_brief`（RO） | 前两个为 N2 已有 |
| 商品内容 | 蓝图 `catalog-listings` | `get_product_content`（RO）、`draft_content_change`（DRAFT） | — |
| 定价与促销 | 蓝图 `pricing-promotions` | `list_coupons`（RO）、`draft_coupon`、`draft_price_change`（DRAFT） | N2 `services/v2/coupons.py`、`guardrails.py` |
| 明细导出 | Borough 新写 | `create_export`（RO，只建记录） | `export_service` |
| 规则与指标口径问答 | Borough 新写 | `get_metric_definition`、`search_rules`（RO） | `metrics/catalog`、`knowledge/retrieval` |

`regenerate_brief` 是 `READ_ONLY`：它替换的是**当日简报这份派生文档的版本**，
不修改任何业务事实，因此不需要草稿审批（D18⑥"版本替换"）。

---

### Task 0：Skill 文件

- [ ] **步骤 1：** 复制 4 个蓝图 Skill 到 `app/skills/merchant/`，按阶段 A 计划的「复制后改」三步处理；**不复制 `marketing-campaigns`**
- [ ] **步骤 2：** 新写 2 个 Skill（`source: borough`）：明细导出、规则与指标口径问答
- [ ] **步骤 3：** 每个 Skill 写 `cases.yaml`：2 条正确触发、1 条误触发、1 条边界反例；另写 1 条与阶段 B 客服回复 Skill 的
      **冲突用例**（同一句「这单怎么处理、顺便看看本周退款率」同时命中两个 Skill），按阶段 A Task 4 的裁决规则断言

必须写进 Skill 的边界：

| 边界 | Skill |
| --- | --- |
| 只能起草，**不能自批或自动应用** | 库存、商品内容、定价 |
| 数字全部来自工具，**缺了就说缺什么** | 业绩洞察、简报 |
| 时间吻合**只是线索**，无机制证据不用因果措辞 | 业绩洞察 |
| 明细**不进对话**，只给导出链接 | 明细导出 |
| 口径只引用受控资产，**不自拟公式** | 规则与指标口径问答 |

---

### Task 1：业绩洞察与归因（M3、D19、S5）

复用 `safe_query` 与 `ComparisonMode`。工具只接收**结构化分析意图**（R4），数据源由**后端查询规划器**选择。

#### 必须落地的 D19 规则

| 规则 | 实现 |
| --- | --- |
| 周期不完整先试**等长可比周期** | 本周前 3 天 vs 上周前 3 天；只有数据缺口、异常基期或样本不足才停止归因 |
| 混合结果边界不重不漏 | 已结束日期走日汇总，当天走实时明细 |
| 响应必带三项 | 数据截至时间、数据来源（实时 / 日汇总 / 混合）、指标定义版本 |
| 整体变化接近零或正负抵消 | 改报**绝对贡献值**，说明不计算比例 |
| 超出查询上限 | 明确返回限制并建议可用范围，**不静默截断** |
| 退款口径（O3） | `gross_gmv` 按支付日、`refund_amount` 按退款日、`net_gmv` = 前两者之差 |
| 图表数据量（PRD §10.1） | 单序列最多 180 点，多序列合计最多 720 点；超出时**由后端聚合**（如按周），不交给前端截断 |

五步归因中**模型负责组织语言，数字全部来自 `attribute_change` 的确定性输出**。

- [ ] **步骤 1：写失败测试**

```python
async def test_incomplete_week_uses_equal_length_comparison(tool) -> None:
    r = await tool.attribute_change(metric="net_gmv", period="THIS_WEEK", today=WEDNESDAY)
    assert r.comparison == ("本周前 3 天", "上周前 3 天")
    assert r.stopped is False


async def test_near_zero_change_reports_absolute_contribution(tool) -> None:
    r = await tool.attribute_change(metric="net_gmv", data=offsetting_segments())
    assert r.mode == "ABSOLUTE_CONTRIBUTION"
    assert all(s.share is None for s in r.segments)


async def test_response_always_carries_cutoff_source_and_version(tool) -> None:
    r = await tool.query_metrics(metric="gross_gmv", days=14)
    assert r.data_cutoff and r.source in {"REALTIME", "DAILY_ROLLUP", "MIXED"}
    assert r.definition_version


async def test_mixed_boundary_neither_overlaps_nor_gaps(tool, db) -> None:
    r = await tool.query_metrics(metric="gross_gmv", days=14, today=TODAY)
    assert sum(r.series) == await ground_truth_gross_gmv(db, days=14, today=TODAY)


async def test_long_series_aggregated_by_backend(tool) -> None:
    """PRD §10.1：单序列 ≤180 点，超出由后端聚合。"""
    r = await tool.query_metrics(metric="gross_gmv", days=365, granularity="DAY")
    assert len(r.series) <= 180 and r.aggregated_to == "WEEK"


async def test_multi_series_total_points_capped(tool) -> None:
    r = await tool.query_metrics(metric="gross_gmv", days=180, split_by="category")
    assert sum(len(s) for s in r.multi_series) <= 720


def test_refund_adjusted_value_never_labelled_gmv() -> None:
    for code, d in METRIC_CATALOG.items():
        if "refund" in d.formula_description:
            assert "gmv" not in code or code == "net_gmv"
```

- [ ] **步骤 2：确认失败 → 实现 → 确认通过**
- [ ] **步骤 3：S5 场景**——"为什么本周下滑" → 五步归因 → 分项贡献 + 数据截至时间 + 证据分级表述。
      断言回答中出现"线索"而**不出现**"导致""造成"等因果词，除非工具结果带了机制证据标记。
      登记 `app/eval/datasets/quality/scenarios/n3_s5_attribution.yaml`。

---

### Task 2：完整每日简报（M2、D18）

**前置：** 阶段 B Task 11（顾客信号查询服务）已完成——简报的顾客信号区只读它的聚合结果。

扩展 N2 的 `services/v2/daily_brief.py`（现有 `build_minimal_brief()` 只汇总库存告警与待批准草稿）。
**这是本计划唯一有定时任务的能力**；Cron 接线归 N5。

| D18 条款 | 实现 |
| --- | --- |
| ① 事实只来自本轮授权工具结果 | 生成时实时调工具；**昨天的简报、历史总结、记忆不进数字来源** |
| ② 正文 3–6 条，其余折叠 | 超出部分显示"另有 N 项" |
| ③ 金额为主排序；硬时限可置顶；**金额未知不自动排末尾** | 排序函数单独测试 |
| ④ 动作按钮只填输入框 | 前端，见 Task 8 |
| ⑤ 商家时区；截至时间 + 生成时间 | 响应必带 |
| ⑥ 一商家一营业日一份；版本替换 | `uq_daily_briefs_merchant_date` 已在库；重新生成 = `brief_version + 1` |
| ⑦ 顾客信号只用聚合或脱敏结果 | 简报不含 `buyer_key` 或别名 |
| ⑧ 失败显示安全降级说明；旧简报不得标为今日 | 降级文案不含异常、SQL、模型信息 |
| ⑨ 重新生成限流、冷却、预算熔断 | `POST /api/v2/merchant/briefs/daily/current/regenerate`，按契约 §8.12 与 §8.7.3 幂等 |
| ⑩ 定时任务默认关闭；真实调用 R3 | 配置开关默认 `false` |

N2 最小简报「来源如实标注为确定性规则」的约定保留：完整简报中由 LLM 组织的部分与确定性条目**分别标注来源**（R7）。

- [ ] **步骤 1：写失败测试**

```python
def test_unknown_amount_is_not_sunk_to_bottom() -> None:
    """D18③：金额未知不自动排到末尾。"""
    items = [item(amount=5000), item(amount=None, deadline=None), item(amount=100)]
    ranked = rank_brief_items(items)
    assert ranked[-1].amount is not None


def test_hard_deadline_can_outrank_amount() -> None:
    items = [item(amount=90000), item(amount=200, deadline_in=timedelta(hours=2))]
    assert rank_brief_items(items)[0].amount == 200


async def test_yesterdays_brief_is_not_a_fact_source(generator, spy_tools) -> None:
    await generator.generate(merchant=M, business_date=TODAY)
    assert "daily_briefs" not in spy_tools.tables_read_for_facts


async def test_regenerate_replaces_version_not_row(client, db) -> None:
    await regenerate(client); await regenerate(client, after_cooldown=True)
    rows = await rows_for(db, "daily_briefs", merchant=M, business_date=TODAY)
    assert len(rows) == 1 and rows[0].brief_version == 3


async def test_concurrent_regenerate_is_serialized(db_pool) -> None:
    await asyncio.gather(*[regenerate_raw(M, crid=f"r{i}") for i in range(5)])
    assert (await brief(M, TODAY)).brief_version == 2


def test_scheduled_generation_disabled_by_default() -> None:
    assert Settings().daily_brief_schedule_enabled is False
```

- [ ] **步骤 2：确认失败 → 实现 → 确认通过 → 同次变更内导出 OpenAPI、codegen、Adapter 与快照测试**；
      重新生成路由的越权用例登记进关键安全集（`introduced_in: N3`）

---

### Task 3：商品内容（M4、D11、S2）

#### 规则

- **先读商品记录再起草**；缺失属性列为"待补"，**不由模型补全**（Q5）；
- 属性值只接受三种来源（D11①）：商家已填、商家在对话中明确给出、描述原文可直接读出；**"同类通常如此"不是来源**；
- 每个写入的属性值带 `source_type`、来源引用、更新时间；从描述提取的须指向原文片段（D11②）；
- **批量起草**：先展示 1–2 个样例确认风格，再生成完整批次。

#### 批量草稿的"勾选批准"

M4 要求审批绑定完整条目清单、每项 diff 与目标版本，并**支持勾选批准**。
若把一批商品做成一个草稿，勾选部分批准就会破坏"一份草稿一个版本"的状态机。

**做法：** 批量起草时**拆成每个商品一份子草稿**，共享一个 `batch_id`。审批界面按批次分组展示，
勾选批准 = 对选中的子草稿逐个应用。每个子草稿有自己的 `draft_version`、目标版本与审批证据，**草稿状态机完全不变**。

**2026-09-24 核对发现：`batch_id` 目前不存在**于 `drafts` 表、契约 §8.13 与 `DraftSummary`。按契约先行（`AGENTS.md` §8.5），
先做步骤 0，再写实现。

- [ ] **步骤 0：契约先行**——`docs/backend-development-plan.md` §8.13 的 `DraftSummary` 增加 `batch_id: PublicId或null`
      （仅 `CONTENT_CHANGE` 可非空；列表支持按 `batch_id` 过滤则同时写查询参数）→ `app/schemas/v2/drafts.py` 与单测 →
      新迁移（接在当时唯一 head 之后，`uv run alembic heads` 前后各确认一次）→ 导出 OpenAPI 与两端 codegen。
      这是字段新增、不改变既有语义，不涉及 PRD 修改。
- [ ] **步骤 1：写失败测试**

```python
async def test_missing_attribute_is_listed_not_invented(merchant_turn, db) -> None:
    await merchant_turn(script=scripted_content_draft(product_without("产地")))
    d = await latest_draft(db)
    assert "产地" not in d.payload["attributes"]
    assert "产地" in d.payload["pending_attributes"]


async def test_extracted_attribute_points_to_source_span(merchant_turn, db) -> None:
    await merchant_turn(script=scripted_content_draft(product_with_desc("容量 240ml")))
    attr = (await latest_draft(db)).payload["attributes"]["容量"]
    assert attr["source_type"] == "DESCRIPTION_EXTRACT"
    assert "240ml" in attr["source_ref"]["span"]


async def test_batch_is_split_into_per_product_drafts(merchant_turn, db) -> None:
    await merchant_turn(script=scripted_batch_draft(products=[P1, P2, P3]))
    rows = await drafts_in_batch(db)
    assert len(rows) == 3 and len({r.batch_id for r in rows}) == 1


async def test_partial_batch_approval_leaves_others_staged(client, db) -> None:
    ids = await stage_batch(db, products=[P1, P2, P3])
    await approve(client, ids[0])
    assert [d.state for d in await drafts_by_id(db, ids)] == ["APPLIED", "STAGED", "STAGED"]
```

- [ ] **步骤 2：确认失败 → 实现 `draft_content_change` 与 `ContentChangeHandler`（注册进分派表、加入 `ENABLED_DRAFT_KINDS`）→ 确认通过**
- [ ] **步骤 3：S2 场景**（**前置：** 阶段 B Task 11 与本计划 Task 7 已完成）——顾客问未填写的产地 → 顾客端 Agent 说明缺失、
      内容缺口信号 +1 → 商家简报出现该信号 → 商家让 Agent 起草补充 → 审批应用 → **顾客端再问同一问题能回答**、
      该信号不再计数。最后一步通过顾客端接口断言，证明两端共享同一商品事实。

---

### Task 4：定价与促销（M6、D4、S6）

#### 护栏（可配置，修改留审计）

| 护栏 | 规则 |
| --- | --- |
| 最大优惠幅度 | **实付不得低于原价 80%**（Q6） |
| 单次调价幅度 | 上限可配 |
| 结束日期 | 促销必须有结束日期（数据库 CHECK 已兜底） |
| 最低售价 | **无成本价时不得声称"未低于成本"**；未配置最低允许售价则**阻止应用** |

- 券型只有满减券、折扣券；同一订单不可叠加多券；
- 券生效后只能停用，停用不影响已下单订单；
- 金额最小货币单位，舍入规则见契约 §8.7.8；
- 护栏读 N2 `services/v2/guardrails.py` 的 `load_limits()`，**应用时按当时生效配置复检**（D9②），不沿用起草时快照。

- [ ] **步骤 1：写失败测试**

```python
async def test_price_draft_blocked_when_min_price_unconfigured(apply) -> None:
    """M6：没有成本依据就不能放行调价。"""
    d = await stage_price_change(P, new_price_cents=9900, min_allowed_price=None)
    r = await apply(d)
    assert r.status_code == 422 and r.json()["code"] == "GUARDRAIL_REJECTED"


async def test_agent_never_claims_not_below_cost_without_cost_data(merchant_turn) -> None:
    outcome = await merchant_turn(script=scripted_price_advice(cost_known=False))
    assert "未低于成本" not in outcome.answer and "不低于成本" not in outcome.answer


async def test_discount_over_20_percent_rejected(apply) -> None:
    d = await stage_coupon(kind="DISCOUNT", rate=Decimal("0.75"))   # 实付 75%
    assert (await apply(d)).status_code == 422


async def test_guardrail_tightened_after_drafting_is_enforced_at_apply(apply, db) -> None:
    d = await stage_coupon(kind="DISCOUNT", rate=Decimal("0.85"))
    await set_guardrail(db, max_discount_rate=Decimal("0.10"))
    assert (await apply(d)).status_code == 422


async def test_coupons_do_not_stack(checkout) -> None:
    r = await checkout(coupons=[C1, C2])
    assert r.status_code == 422
```

- [ ] **步骤 2：确认失败 → 实现 `PriceChangeHandler`、`CouponHandler`（注册进分派表、加入 `ENABLED_DRAFT_KINDS`）→ 确认通过**
- [ ] **步骤 3：S6 场景**——滞销告警 → 商家让 Agent 起草折扣券 → 护栏校验 → 批准生效 → **顾客端券列表出现该券**。
      登记 `app/eval/datasets/quality/scenarios/n3_s6_promotion.yaml`。

---

### Task 5：明细导出（M7，Astra N3-4 必审）

复用 `export_service`（建记录 → 限时签名链接 → 下载时查询生成）与其已有的公式注入转义。本任务补的是 v2 所需的差异：

- 五类：订单、订单明细、退款、退货、工单；**列白名单固定**，顾客标识脱敏，无手机号与地址；
- 导出范围由后端强制 `merchant_id` 与行数上限（R4），模型只给结构化意图；
- 响应显示满足条件的总行数、当前行数、是否达上限，**不把截断结果伪装成完整结果**；
- **明细数据不进模型上下文**：`create_export` 只返回导出记录与链接，不返回行；
- **不承诺异步导出**：超出行数上限时拒绝并建议缩小范围；
- **创建导出与实际下载分别审计**。

- [ ] **步骤 1：写失败测试**

```python
async def test_export_rows_never_enter_model_context(merchant_turn, fake_llm) -> None:
    await merchant_turn(script=[tool_use_turn(call("create_export", kind="ORDERS", days=7)), end_turn()])
    assert all("order_no" not in m.content for m in fake_llm.last_messages)


async def test_create_and_download_are_audited_separately(client, db) -> None:
    link = await create_export(client)
    await download(client, link)
    events = [r.event_type for r in await rows(db, "audit_logs")]
    assert events.count("EXPORT_CREATED") == 1 and events.count("EXPORT_DOWNLOADED") == 1


async def test_export_is_scoped_to_session_merchant(merchant_gates, ctx_merchant_a, db) -> None:
    result = await merchant_gates.invoke(ctx_merchant_a, "create_export", {"kind": "ORDERS", "days": 7})
    assert await export_rows_merchants(db, result.payload) == {MERCHANT_A}


@pytest.mark.parametrize("prefix", ["=", "+", "-", "@"])
def test_formula_injection_escaped(prefix) -> None:
    assert not escape_cell(f"{prefix}SUM(A1)").startswith(prefix)
```

最后一条是**回归哨兵**——v1 已实现，确保 v2 复用时没有绕过它。审计事件名以 v1 现有常量为准，开工时核对后写死。

- [ ] **步骤 2：确认失败 → 实现 → 确认通过**

---

### Task 6：规则与指标口径问答（M8、S7，Astra N3-4 必审）

复用 `metrics/catalog.py` 与 `knowledge/retrieval.py`（混合检索在 N4 替换底层，接口不变）。

- 回答**必须引用知识库文档**，并**声明指标定义版本**；
- 指标详情并列两个字段：**业务口径**与**受控 SQL 口径**；后者来自受控指标资产，**只供人核对，不由模型生成，也不回流执行**（R4）；
- 同时展示单位、来源层级、负责人、来源库表、可用维度与可选关联报表；
- **正式指标资产未命中时标"待核验"**（v1 目录已有 `UNVERIFIED` 状态），不得把生成说明冒充正式口径。

- [ ] **步骤 1：写失败测试**

```python
async def test_sql_caliber_is_display_only(tool, spy_db) -> None:
    await tool.get_metric_definition("net_gmv")
    assert spy_db.executed_sql_from_catalog == []


async def test_unverified_metric_is_labelled(tool) -> None:
    d = await tool.get_metric_definition("some_field_comment_metric")
    assert d.status == "UNVERIFIED"


async def test_rule_answer_cites_document(merchant_turn) -> None:
    outcome = await merchant_turn(script=scripted_rule_question("退货运费谁出"))
    assert outcome.citations and outcome.citations[0].document_path
```

- [ ] **步骤 2：确认失败 → 实现 → 确认通过**
- [ ] **步骤 3：S7 场景**——"净成交额怎么算" → 检索口径文档 → 带引用回答并声明定义版本。
      N3 用关键词检索跑通；**N4 换成混合检索后此场景必须回归通过**。登记 `n3_s7_metric_caliber.yaml`。

---

### Task 7：内容缺口信号（S2、D11③④、契约 §8.12，E8）

**前置：** 阶段 B Task 11（顾客信号服务、列表与忽略路由、`list_signals`）已完成。本任务只在同一服务上追加 `CONTENT_GAP`。

- **事实源是商品内容与后端确定性完整度规则**（`services/v2/content_completeness.py`，与 Task 3 共用）：
  每个品类的必填属性清单由后端配置，不由模型判断；
- 顾客侧触发：新增顾客工具 `get_product_attribute(product_id, attribute)`（`READ_ONLY`）——值存在返回值；
  属于必填清单且缺失时返回「缺失」并**由服务**对 `(merchant_id, CONTENT_GAP, product_id, signal_date)` upsert 计数；
  非必填属性缺失只回答缺失、不计数；
- 信号 `derived_from` 恰好 1 项 `PRODUCT` 来源且 `source_id = product_id`、带当时 `content_version`；
  **不保存或引用顾客提问原文**；
- 商品内容更新（Task 3 应用）后重算完整度，缺口消失的商品当天不再计数；
- **核对点：** §6.9 对 `READ_ONLY` 的定义是否允许「派生提醒计数」这类副作用（它不改业务事实，但确实写库）。
  开工时读 §6.9 与 `registry.py` `_check_policy()`；若不允许，先在 §6.9 补一条明确例外或改为路由层计数，
  **不在实现里默默绕过**。

- [ ] **步骤 1：写失败测试**

```python
async def test_missing_required_attribute_counts_content_gap(shop_gates, customer_ctx, db) -> None:
    await shop_gates.invoke(customer_ctx, "get_product_attribute", {"product_id": P, "attribute": "产地"})
    s = await signal(P, "CONTENT_GAP", TODAY)
    assert s.count == 1 and s.derived_from == [{"source_type": "PRODUCT", "source_id": P, "content_version": V1}]


async def test_optional_attribute_missing_does_not_count(shop_gates, customer_ctx, db) -> None:
    await shop_gates.invoke(customer_ctx, "get_product_attribute", {"product_id": P, "attribute": "包装颜色"})
    assert await signal_rows(P, "CONTENT_GAP", TODAY) == 0


async def test_gap_stops_counting_after_content_update(shop_gates, customer_ctx, db) -> None:
    await apply_content_change(db, P, {"产地": "云南"})
    await shop_gates.invoke(customer_ctx, "get_product_attribute", {"product_id": P, "attribute": "产地"})
    assert (await signal(P, "CONTENT_GAP", TODAY)).count == 1   # 更新前的那一次，不再增加


async def test_content_gap_signal_never_stores_question_text(db) -> None:
    assert "产地" not in json.dumps((await signal(P, "CONTENT_GAP", TODAY)).derived_from, ensure_ascii=False)
```

- [ ] **步骤 2：确认失败 → 实现 → 确认通过**
- [ ] **步骤 3：更新搜索发现、选购研究两个顾客 Skill 的正文**，指示「问到具体属性时调用 `get_product_attribute`」，
      `version + 1` 并重跑两者的 `cases.yaml`（阶段 A Task 4 的更新后回归规则）

---

### Task 8：商家工作台补全

在 `n2-merchant-vue-v2-migration` 与阶段 B Task 12 的基础上，补齐 M1 业务区域中的剩余两块：

| 区域 | 内容 |
| --- | --- |
| 经营 | 指标、趋势、归因、图表（ECharts，图表数据点来自后端） |
| 商品与库存 | 内容完整度、库存告警、促销与券 |

- 审批界面支持**按 `batch_id` 分组 + 勾选批准**（Task 3）；
- 今日简报扩展为完整简报的展示：3–6 条正文、「另有 N 项」、截至时间与生成时间、重新生成按钮（冷却中禁用）；
  动作按钮**只把问题填入 `/ops-assistant` 输入框，不发送、不批准、不执行**（D18④）；
- **知识库不进普通商家工作台**（M1）；
- 字段流向 `generated.ts → adapters → types → stores → 组件`。

- [ ] **步骤 1：写组件测试**——动作按钮不触发请求；图表不在前端计算数据点；批次勾选只对选中子草稿发起应用；
      重新生成在冷却期内禁用。
- [ ] **步骤 2：确认失败 → 实现 → 确认通过**；`npm run test`、`typecheck`、`lint`、`codegen:check`、`build` 通过
- [ ] **步骤 3：S2、S5、S6、S7 浏览器 E2E**（Fake LLM、一次性库；S2 的顾客端部分走 `shop/` 的 Playwright）

---

### Task 9：自检与两页合并评审

- [ ] **步骤 1：跑检查**

```powershell
cd backend
rg -n "from app.agent.graph|from app.agent.state" app/tools/ app/skills/
rg -n "marketing" app/skills/
rg -n "execute\(|text\(" app/tools/merchant/definitions.py
$env:REQUIRE_INTEGRATION_DB=1; uv run pytest; uv run ruff check .; uv run mypy app
cd ..; git status --porcelain vendor/
```

三条 `rg` 期望零命中：工具不经冻结基线；无营销 Skill；口径工具不执行任何 SQL。最后一条期望无输出（R8）。

- [ ] **步骤 2：v2 运营助手页与 v1 分析助手合并评审**（PRD §15 N2：「两页是否合并在 N3 商家 Skill 迁完后另行评审」）——
      逐项对照 v1 分析助手的能力（指标、明细、规则、图表、导出、猜你想问、反馈）在 v2 是否已有等价证据，
      写成 `docs/specs/<评审当日 YYYY-MM-DD>-merchant-assistant-page-merge-review.md`，给出建议并**交用户裁定**；
      **本计划不执行合并**，裁定为合并时另立计划并先改 PRD。
- [ ] **步骤 3：同步文档**——`docs/project-progress.md`：6 个 Skill 用例、S2/S5/S6/S7 两层结果、**S7 待 N4 混合检索后回归**、
      简报真实生成「待人工验收」、未执行 Git、未调用 LLM；`docs/project-navigation.md` 登记新文件；
      `plans/2026-09-24-n3-module-roadmap.md` §一状态。

---

## 本计划明确不做的事

| 不做 | 归属 |
| --- | --- |
| 客服回复 Skill、售后类信号、售后与信号界面、S4 | 阶段 B（`n3-customer-skills-and-after-sales` Task 10–13） |
| 营销活动 | 不做（D4） |
| 商家两层记忆 | `n4-memory-pipeline` |
| 混合检索 | `n4-hybrid-retrieval`（S7 届时回归） |
| 简报定时任务的 Cron 接线与首次真实生成 | `n5-budget-ops-and-railway`，真实生成需 R3 |
| 异步导出 | 不做（M7，无 Worker 与对象存储） |
| 执行两页合并 | 评审后由用户裁定，另立计划 |
