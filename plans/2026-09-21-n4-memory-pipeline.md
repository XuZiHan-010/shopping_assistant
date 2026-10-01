# N4 双端记忆管线实施计划

> **给执行者：** 用 `superpowers:executing-plans` 逐任务推进。步骤用 `- [ ]` 复选框跟踪。
> **本计划不含任何 Git 提交步骤**（R2）。自动化测试全程 Fake LLM，零费用。
> **抽取模型选型评测（Task 7）会产生费用，需 R3 单独授权。**

**目标：** 实现 PRD A6 记忆沉淀、C7 顾客记忆、M11 商家两层记忆，上线**记忆与个性化 Skill**
（从 N3 顺延而来），并完成 E5 记忆专项评测。

**架构：** 抽取是**回合结束后的异步后置流程**，只读对话文字，失败不影响主回答（A6）。
`memory/` 不得 import `loop/`（§5.6）——记忆不能反向拉起循环。
**v1 的 `merchant_memories` 表保持不动**，继续服务冻结基线；v2 使用数据迁移计划 M6 建的新表。
**异步交付走 outbox，不走进程内后台任务**（后端计划 §6.13）：主事务只追加幂等任务行，
由短批次排空任务以 `FOR UPDATE SKIP LOCKED` + 租约 + 重试上限处理；Railway Cron 接线归 N5。

**技术栈：** Python 3.12、SQLAlchemy 2（outbox + `FOR UPDATE SKIP LOCKED`）、pytest。

> **2026-09-27 编组修订**（见 `plans/2026-09-27-n4-module-roadmap.md` §二）：本计划原写
> 「FastAPI BackgroundTasks」，与后端计划 §6.13「不得用进程内 `BackgroundTasks` 冒充可靠异步交付」冲突，
> 按契约改写 Task 3；新增 Task 0（迁移补齐）与 Task 8、9（两端记忆界面，PRD §12.4），原 Task 8 自检顺延为 Task 10。
> **2026-09-28 裁定落地**：D-N4-2（访客回合不抽取、绑定后不补抽）写入 Task 3；D-N4-3（商家记忆面板做最小版，列为第一个可砍项）写入 Task 9。

**规格来源：** PRD A6、C7、M11、E5；融合决策 D16、Q10、Q20；后端计划 §5.6、§6.13；
契约计划 §8.14（记忆契约）。

---

## 入口条件

> **预写计划不是已验证实现。** 本计划写于上游代码尚不存在时，文中引用的类名、函数签名、
> 工具名、表字段、错误码都是**当时的设计**。开工前逐项对照上游**实际落地**的接口；
> 不一致时先按 PRD → 契约 → 计划的顺序修正，**再动代码**，不得在实现里默默适配或绕过。

- [x] `n3-customer-skills-and-after-sales`、`n3-merchant-skills` 已完成（N3 整体验收通过，见 N4 总览阶段 0）；
- [x] 数据迁移计划 M6 已完成：`customer_memories`、`merchant_memory_facts`、
      `merchant_memory_summaries` 三表在库（2026-09-27 已核对：迁移 `20260922_0022`、模型 `app/models/memory_v2.py`；
      开工时对真实库再查）；
- [x] 契约计划 Task 8（组 7 记忆）已完成：§8.14 字段已定（2026-09-27 已核对：`app/schemas/v2/memory.py` 已有
      `CustomerMemoryItem` 至 `MerchantMemoryDeleteResponse`，路由未挂载）；
- [x] **核对 §6.13 与 §8.14 的实际内容**，冲突时以契约为准回改本计划（2026-09-27 已发现并回改一处：Task 3 的异步方式）；
- [x] `n4-context-compaction` Task 0（多轮历史回放）与本计划 Task 4 的「随提示词注入」都改两端 Chat 服务，
      **两者串行**，先完成的一方在进度快照写明实际装配顺序。

---

## 全局约束

- 中文（R1）；**不执行 Git 操作**（R2）；**不调用真实 LLM**（R3）。
- **记忆是默认值不是命令**：与本次对话冲突时以本次为准（D16④）。
- **两层都不得回答规则、替代知识库或充当经营数字来源**（M11）。
- **团队知识与记忆单向边界**：记忆绝不升级写回团队知识库。
- 抽取任务用**独立预算**，不与主回合共享 `LlmBudget`。

---

## v1 记忆不迁入 v2

v1 `merchant_memories` 是"每商家每分类一份全量覆盖的文本"，**没有来源引用**。
它既不满足 v2 事实层的 `source_ref NOT NULL` 约束，也不能当作总结层——
总结层必须能从事实层**重建**，而 v1 文本没有可追溯的事实。

**决定：v1 记忆不迁移。** v1 链路继续使用它（冻结基线需要），v2 从空开始沉淀。
这意味着商家切到 v2 后，之前积累的记忆不会出现在 v2 对话里——
**这是有意的取舍，已写入 PRD §14 需求迁移表（2026-09-21 用户裁定）**，不得静默发生。

---

## 文件结构

| 文件 | 责任 |
| --- | --- |
| `backend/app/memory/__init__.py` | 包 |
| `backend/app/memory/extractor.py` | 从对话文字抽取候选事实 |
| `backend/app/memory/filters.py` | **写入前后双重过滤** |
| `backend/app/memory/customer_store.py` | 顾客事实层：写入、合并同义、180 天滚动 |
| `backend/app/memory/merchant_store.py` | 商家事实层与总结层 |
| `backend/app/memory/summary_rebuild.py` | 总结层重建 |
| `backend/app/memory/pipeline.py` | 异步任务编排：幂等、租户隔离、重试上限 |
| `backend/app/tools/customer/memory.py` | `recall_preferences`（RO） |
| `backend/app/tools/merchant/memory.py` | `recall_merchant_preferences`（RO） |
| `backend/app/skills/customer/memory-personalization/` | 从 N3 顺延的 Skill |
| `backend/app/api/routes/v2/shop_memory.py` | 顾客三条路由 |
| `backend/app/api/routes/v2/merchant_memory.py` | 商家两条路由 |
| `backend/app/jobs/purge_expired_customer_memory.py` | 180 天过期清理 |
| `backend/app/jobs/drain_memory_outbox.py` | outbox 排空：领取、抽取、写入、重试（Task 3） |
| `backend/migrations/versions/*_memory_outbox_and_state.py` | Task 0 迁移 |
| `shop/src/app/[shop_slug]/memories/` | 顾客记忆页（Task 8） |
| `frontend/src/views/MerchantMemoryView.vue` | 商家记忆面板（Task 9，D-N4-3 已裁定做最小版） |
| `backend/app/eval/datasets/memory/` | E5 记忆专项评测集 |

---

### Task 0：迁移补齐（2026-09-27 编组新增）

N1 迁移 `20260922_0022` 只建了三张记忆主表。按本计划后续任务与契约核对，还缺三处存储，
**都不改 §8.14 的对外字段**，只补内部状态：

| 缺口 | 证据 | 需要 |
| --- | --- | --- |
| 抽取任务 outbox | §6.13 要求幂等 outbox 行；库中无对应表 | 以回合（`messages.id`）为唯一键的任务表：状态、尝试次数、租约截止、最后错误 |
| 总结层陈旧标记与依赖 | Task 5 要求删事实后依赖它的总结标为陈旧、不再注入；`merchant_memory_summaries` 只有 `content`/`rebuilt_at` | 陈旧标记 + 总结所依赖的事实集合 |
| 顾客「记住我的偏好」开关 | §8.14 `memory_enabled`；库中无存储位置（`rg memory_enabled app` 仅命中 Schema） | 按 `merchant_id + buyer_key` 的开关状态，默认开启 |
| outbox 的可信身份回溯 | `messages` / `conversations` 仅有商家与顾客主体摘要，无法从消息 ID 反查原始 `buyer_key` | `messages.session_record_id` 可空外键指向服务端 `agent_sessions.id`；仅 v2 用户回合写入，任务行仍只存消息 ID；会话记录已清理时安全放弃，不猜测身份 |

- [x] **步骤 1：先写 `docs/database.md`**（表名、列、约束、索引），再写 ORM 与 Alembic 迁移；
      创建前后都确认 `uv run alembic heads` 恰好一个 head（与 `n4-hybrid-retrieval` 的迁移串行，见 N4 总览 §三）
- [x] **步骤 2：真实 PostgreSQL 下升级、降级、再升级通过**；`uv run alembic check` 无待生成操作

---

### Task 1：双重过滤

**写入前**过滤抽取出的候选，**写入后**再扫一遍落库值——第二道挡住第一道之后的
任何改写（合并、规范化）重新引入敏感内容。

| 拒绝 | 类型 |
| --- | --- |
| 标识信息 | 手机号、身份证、银行卡、地址、邮箱 |
| 敏感推断 | 健康、宗教、政治 |

- [x] **步骤 1：写失败测试**

```python
@pytest.mark.parametrize("text", [
    "我电话 13800138000", "身份证 110101199001011234", "卡号 6222 0212 3456 7890",
    "寄到朝阳区XX路1号", "邮箱 a@b.com",
])
def test_identifiers_rejected(text) -> None:
    assert filter_candidate(fact(text)).rejected


@pytest.mark.parametrize("text", ["顾客可能有糖尿病", "顾客信仰佛教", "顾客支持某政党"])
def test_sensitive_inferences_rejected(text) -> None:
    assert filter_candidate(fact(text)).rejected


def test_post_write_filter_catches_merge_reintroduction() -> None:
    """合并两条各自干净的事实，不得拼出敏感信息。"""
    merged = merge_facts(fact("送货前打 138"), fact("00138000 这个号"))
    assert filter_persisted(merged).rejected
```

- [x] **步骤 2：确认失败 → 实现 → 确认通过**

---

### Task 2：抽取规则（A6、D16②）

- **只读对话文字，不读工具结果**；
- **只记录顾客（或商家）明确表达或确认过的事实**；助手的文字只用于理解上下文，
  **不能仅凭助手推测写入**；
- 单条长度沿用蓝图上限；**同义事实更新而非堆叠**。

- [x] **步骤 1：写失败测试**

```python
async def test_assistant_speculation_is_not_stored(extractor) -> None:
    conv = [assistant("看起来你可能喜欢素色"), customer("嗯我看看")]
    assert await extractor.extract(conv, llm=fake_proposing("偏好素色")) == []


async def test_explicit_customer_statement_is_stored(extractor) -> None:
    conv = [customer("我家没有洗碗机")]
    facts = await extractor.extract(conv, llm=fake_proposing("家里没有洗碗机"))
    assert facts[0].value == "家里没有洗碗机"


async def test_tool_results_are_not_read(extractor, spy) -> None:
    await extractor.extract(conv_with_tool_results())
    assert all(m.role != "tool" for m in spy.prompt_messages)


async def test_synonymous_fact_updates_not_stacks(store) -> None:
    await store.write(fact("偏好素色", category="审美"))
    await store.write(fact("喜欢素色的", category="审美"))
    assert len(await store.list(category="审美")) == 1
```

第一条的关键：模型提议写入"偏好素色"，但这条来自助手的推测、顾客只说了"嗯我看看"——
**抽取器必须按发言者过滤，不能只信模型的提议**。

- [x] **步骤 2：确认失败 → 实现 → 确认通过**

**2026-09-30 核实（Opus）：** 实现与测试由先前会话写入未勾选。`tests/unit/memory/test_extractor.py` 10 例覆盖助手推测不写入、
显式陈述写入并带来源、工具结果不进提示词、模型改写否定被拒等；同义更新由 `(merchant_id, buyer_key, category, key)` 唯一键
upsert 实现，`test_write_updates_same_fact_and_renews_from_confirmation_only` 覆盖（同一 key 的新值覆盖旧值，不堆叠）。

---

### Task 3：异步管线（A6、Q20、§6.13）

- **回合落库的同一事务里追加一行 outbox 任务**（Task 0 的任务表），**主回答不等抽取**；
  **不得使用 FastAPI `BackgroundTasks`**——进程重启即丢任务，不是可靠交付（§6.13）；
- 排空任务 `app/jobs/drain_memory_outbox.py`：短批次、`FOR UPDATE SKIP LOCKED`、租约超时后可被重新领取，
  接受 `now` 参数、不读墙钟；本计划只提供可手动运行的模块与测试，**Railway Cron 接线归 `n5-budget-ops-and-railway` Task 4**；
- **幂等**：同一回合重复触发只产生一次写入（以回合 ID 为幂等键，outbox 唯一约束兜底）；
- **租户隔离**：任务行只带回合 ID，身份从回合记录解析，不接收外部传入的 `merchant_id` / `buyer_key`；
- **访客回合不抽取、绑定后不补抽**（D-N4-2，2026-09-28 用户裁定）：以**回合落库时**会话是否已绑定演示顾客为准——
  未绑定（`buyer_key` 为空）的回合**不追加 outbox 行**；访客绑定身份后，只有绑定之后的回合进入抽取，
  绑定前的访客回合永不补抽；关闭「记住我的偏好」期间的回合同样不追加；
- **重试上限**（默认 2），超限记录失败并放弃，不无限重试；
- **单独预算**：新增 `MEMORY_EXTRACTION_MAX_CALLS` / `MEMORY_EXTRACTION_MAX_TOKENS`，
  参照既有 `localization_max_calls_per_request` 的独立预算做法。

- [x] **步骤 1：写失败测试**

```python
async def test_main_answer_persisted_even_if_extraction_fails(client, db) -> None:
    with failing_extractor():
        r = await chat(client, "我家没有洗碗机")
    assert r.status_code == 200
    assert await count(db, "answers", status="SUCCEEDED") == 1


async def test_duplicate_trigger_writes_once(pipeline, db) -> None:
    await asyncio.gather(pipeline.run(turn_id=T), pipeline.run(turn_id=T))
    assert await count(db, "customer_memories") == 1


async def test_concurrent_drains_claim_each_job_once(db_pool) -> None:
    """两个排空实例并发：SKIP LOCKED 保证同一任务只被一方领取。"""
    await enqueue(turn_id=T)
    await asyncio.gather(drain(now=NOW), drain(now=NOW))
    assert await extraction_attempts(turn_id=T) == 1


async def test_expired_lease_is_reclaimed(db) -> None:
    await claim(turn_id=T, lease_until=NOW - timedelta(minutes=1))   # 上一实例崩溃
    await drain(now=NOW)
    assert await job_status(turn_id=T) == "DONE"


async def test_extraction_budget_is_independent(pipeline) -> None:
    turn = turn_with_exhausted_main_budget()
    assert (await pipeline.run(turn_id=turn.id)).ran is True


async def test_outbox_row_has_no_identity_fields(client, db) -> None:
    await chat(client, "我家没有洗碗机")
    row = await latest(db, "memory_extraction_jobs")          # 表名以 Task 0 实际定名为准
    assert "merchant_id" not in row and "buyer_key" not in row


def test_no_background_tasks_in_memory_path() -> None:
    assert not rg("BackgroundTasks", "app/memory/", "app/services/v2/")


async def test_guest_turns_never_enqueued_even_after_binding(client, db) -> None:
    """D-N4-2：访客期间说的话，绑定后也不补抽。"""
    sid = await new_guest_session(client, shop=S1)
    await chat(client, "我家没有洗碗机", session=sid)          # 访客回合
    assert await count(db, "memory_extraction_jobs") == 0
    await bind_demo_customer(client, sid, buyer=B)
    await chat(client, "我喜欢素色", session=sid)              # 绑定后的回合
    jobs = await list_jobs(db)
    assert len(jobs) == 1 and jobs[0].turn_text == "我喜欢素色"
```

- [x] **步骤 1a：契约先行**（D-N4-2）——在 PRD C7 与后端计划 §6.13 补一句「访客回合不抽取，绑定后不补抽；
      记忆关闭期间的回合不抽取」，再写本 Task 代码（2026-09-28 编组新增；同日已完成：PRD C7、§15 N4；
      后端计划 §6.13 规则与必测）
- [x] **步骤 2：确认失败 → 实现 → 确认通过**

**2026-09-30 核实（Opus）：** `tests/integration/v2/test_memory_outbox.py` 10 例覆盖访客不入队且绑定后不补抽、关闭期间不入队、
随用户消息同事务落 outbox、幂等、重试上限、租约回收、并发只领取一次、入队后关闭不写入；outbox 无身份列由
`tests/unit/models/test_memory_pipeline_metadata.py` 覆盖；独立预算由 `tests/unit/memory/test_budget_config.py` 覆盖。
本次补 `tests/unit/memory/test_async_delivery.py`（记忆、v2 服务与路由不出现 `BackgroundTasks`）。

---

### Task 4：顾客记忆（C7、D16）

路由：`GET /shop/memories`、`DELETE /shop/memories/{memory_id}`、`PUT /shop/memory-preference`。

> **（2026-09-28，WS）** 本 Task 与 WS Task 4 都会改顾客工具注册 `backend/app/tools/customer/__init__.py`：本 Task 注册 `recall_preferences`，WS 注册 `get_my_order`。
> - 两边改动须串行，先改的一方在进度快照登记；
> - 后改的一方基于前者的结果追加，不覆盖；
> - 评测与 Skill 加载测试里凡是断言顾客工具全集的用例，最终要同时包含两个新工具。

- 按**顾客 + 店铺**隔离；商家不可见；
- 响应只含 `shop_slug`，**不含 `buyer_key` 与 `merchant_id`**（§8.14）；
- 保留 **180 天**，按单条的**最后确认或更新时间**滚动；**仅被读取不续期**；
- 关闭"记住我的偏好"会**清空已有记忆**，须带 `purge_confirmation`；关闭后不再写入；
- 近期少量事实随提示词注入，其余按需检索；注入段**位于稳定前缀之后**（A9：按用户变化的内容不得打乱缓存前缀），
  且**按外部文本围栏**（A11：记忆抽取自顾客原话，属于非本系统产生的文本）。

- [x] **步骤 1：写失败测试**

```python
async def test_reading_does_not_renew_retention(store, clock) -> None:
    m = await store.write(fact("x"), at=clock.now - timedelta(days=179))
    await store.recall(at=clock.now)                  # 读一次
    await purge_expired(now=clock.now + timedelta(days=2))
    assert await store.get(m.id) is None


async def test_expired_memory_not_recalled_before_purge_runs(store, clock) -> None:
    """过期判定在读取时做，不依赖清理任务是否已跑。"""
    await store.write(fact("x"), at=clock.now - timedelta(days=181))
    assert await store.recall(at=clock.now) == []


async def test_disable_purges_and_blocks_future_writes(client, pipeline, db) -> None:
    await client.put("/api/v2/shop/memory-preference",
                     json={"enabled": False, "purge_confirmation": "yes"}, headers=CUST)
    assert await count(db, "customer_memories", buyer=B) == 0
    await pipeline.run(turn_id=turn_of(B))
    assert await count(db, "customer_memories", buyer=B) == 0


async def test_memory_not_visible_across_shops(client) -> None:
    await write_memory(buyer=B, shop=S1, value="偏好素色")
    items = (await client.get("/api/v2/shop/memories", headers=cust(B, S2))).json()["items"]
    assert items == []


async def test_merchant_cannot_see_customer_memory(client) -> None:
    r = await client.get("/api/v2/shop/memories", headers=MERCHANT_SESSION)
    assert r.status_code == 403
```

- [x] **步骤 2：确认失败 → 实现 → 确认通过 → 五项完成门槛**

**2026-09-30 核实（Opus）：** 存储层 `test_customer_memory_store.py`（读取不续期、过期不召回、跨商家/跨顾客隔离、关闭清空并阻断写入）、
路由层 `test_shop_memory.py`（访客不可列、列表与删除、关闭需确认、注入围栏且位于静态前缀之后）、清理任务 `test_memory_maintenance.py`；
商家会话读顾客记忆 403 + 审计由安全集 `n4_memory.yaml` SEC-N4M-001～005 覆盖；§8.0.1 五项（契约、OpenAPI、两端生成类型、Adapter、哨兵）齐备。
本次补 `test_memory_number_is_not_a_price_source`（见 Task 5 修复）。

---

### Task 5：商家两层记忆（M11、Q10）

| 层 | 内容 | 删除语义 |
| --- | --- | --- |
| 事实层 `FACT` | 商家明确表达或确认的偏好，**带来源** | 可逐条删除 |
| 总结层 `SUMMARY` | 按类别管理的**可重建文档** | 删来源后重建；**不承诺逐条删除** |

路由：`GET /merchant/memories`、`DELETE /merchant/memories/{memory_id}`（响应带
`summary_rebuild_scheduled`）。

- 总结层**只由事实层生成**，是派生物；
- 两层都**只影响语气与呈现**，不得回答规则、替代知识库或充当数字来源；
- 删事实后，**依赖它的总结必须重建**，重建完成前总结标为陈旧，**不得继续被注入提示词**。

- [x] **步骤 1：写失败测试**

```python
async def test_deleting_fact_marks_dependent_summary_stale(store) -> None:
    f = await store.add_fact("回复语气偏正式", source_ref=TURN)
    await rebuild_summaries(merchant=M)
    await store.delete_fact(f.id)
    assert (await store.summary(M, "tone")).stale is True


async def test_stale_summary_not_injected(loop) -> None:
    await mark_summary_stale(M, "tone")
    await loop.run(...)
    assert "回复语气偏正式" not in loop.llm.last_system_prompt


async def test_memory_never_used_as_number_source(loop) -> None:
    await store.add_fact("上月净成交额大约 50 万", source_ref=TURN)
    out = await loop.run(script=scripted_metric_question())
    assert all(n.source == "TOOL" for n in out.traced_numbers)
```

- [x] **步骤 2：确认失败 → 实现 → 确认通过 → 五项完成门槛**

**2026-09-30 修复（Opus）：** 核实时发现缺陷——两端把记忆拼进 `LoopRequest.system_prompt`，而循环把系统提示词整体算作数字来源，
记忆里的「上月净成交额大约 50 万」能让回答中的「50 万」通过确定性校验，违反 M11。新增 `LoopRequest.memory_context`：拼在系统消息
稳定前缀与围栏策略之后（A9），**不进数字来源**；两端服务改为 `_memory_context()`。先红后绿：`test_merchant_memory.py::test_memory_never_used_as_number_source`、
`test_shop_memory.py::test_memory_number_is_not_a_price_source` 修复前 `degraded is False` 失败；循环层 `test_number_only_in_memory_context_is_unsourced` 与
空记忆不改系统消息各 1 例。其余：陈旧标记、陈旧不注入（`active_summaries`）、跨商家隔离、敏感与超长拒写、总结契约由
`test_merchant_memory_store.py`、`test_memory_maintenance.py`、`test_merchant_memory.py` 覆盖。§6.13 已补规则与必测。

---

### Task 6：记忆与个性化 Skill

从 `n3-customer-skills-and-after-sales` 顺延。按 `n3-skill-loader` 的「复制后改」处理
蓝图 `shopping-agent/skills/memory-personalization`。

- 工具 `recall_preferences` 只读；**写入不经工具**——写入是回合后的异步抽取，
  模型不能直接决定"记住什么"；
- Skill 里写明：记忆是默认值不是命令；顾客本次说的与记忆冲突，以本次为准。

- [x] **步骤 1：复制并改写，补 `version` 与 `source`**
- [x] **步骤 2：写 `cases.yaml`**，含"记忆与本次冲突时以本次为准"的用例

```python
async def test_current_turn_overrides_memory(loop) -> None:
    await write_memory(buyer=B, value="偏好素色")
    out = await loop.run(user="这次想要彩色的", script=scripted_search())
    assert out.search_args["color"] != "素色"
```

- [x] **步骤 3：确认失败 → 实现 → 确认通过**

**2026-09-30 核实（Opus）：** `app/skills/customer/memory-personalization/SKILL.md` 带 `version: 1` 与 `source`，写明记忆是默认值、本次优先、
不作事实来源、不在对话里宣称已删除；`cases.yaml` 4 例含 `memory-personalization-current-turn-wins`；`tests/unit/skills/test_customer_skill_content.py`
覆盖正文；`recall_preferences` 已注册且与 WS 的 `get_my_order` 共存（`test_shop_chat.py` 工具全集断言含两者）。

---

### Task 7：E5 记忆专项评测与抽取模型选型

A6：**不预设"更便宜的模型足够"**，抽取模型须经评测后选择。

> **（2026-09-28，WS Task 5）** 24 个演示商品会从「演示商品 NN」换成真实商品名。本 Task 的评测数据集不要写死商品名：
> - 需要商品时从 `build_demo_catalog()` 取，或者用数据集自带的商品；
> - 避免 WS 换名后评测数据集整体失效。

| 指标 | 含义 |
| --- | --- |
| 抽取精确率 | 写入的事实中确为顾客明确表达的比例 |
| **错误写入率** | 写入了推测、敏感信息或错误事实的比例——**选型的首要指标** |
| 纠正生效 | 顾客更正后旧事实被更新 |
| 删除生效 | 删除后不再出现在任何回答中 |

- [x] **步骤 1：建评测集** `app/eval/datasets/memory/`，≥ 40 条，含敏感信息诱导、
      助手推测、同义更新、跨店隔离等
- [x] **步骤 2：Fake LLM 下跑通评测管线**（验证结构，不代表模型质量）
- [x] **步骤 3：按 R3 提交真实选型评测的审批请求**（2026-09-30 已提交用户，见下方实际数字；**未获授权，未执行**）

```text
接口：DeepSeek（协议以 llm-client 计划 Task 6 的结论为准）
模型：deepseek-flash（如需对比 deepseek-v4-pro，另列并说明费用差）
次数：评测集 N 条 × 每条 1 次抽取 = N 次
费用：预计 ¥Y；上限 ¥Z
```

提交时填入**实际数字**。**取得同意前不得执行步骤 4。**

**2026-09-30 实际申请：** 接口 DeepSeek OpenAI 兼容接口（经 `build_guarded_llm`，`purpose=MEMORY`，受每日预算熔断）；模型 `deepseek-flash`；
次数 40 条 × 1 次 = **40 次**；token 每次上限 `MEMORY_EXTRACTION_MAX_TOKENS` 4000，合计 **≤ 16 万**，低于每日预算 50 万；会产生费用，
金额以 DeepSeek 当前价目表为准；入口 `uv run python -m app.eval.memory_e5 --real`，只允许本地 `_test` 库、条数变化即拒绝运行。

- [x] **步骤 4：执行并据错误写入率选定抽取模型**，结论写入 §6.13
      （2026-09-30 用户授权后执行：40 次 `deepseek-flash`、8,731 token；错误写入率 5%，敏感与推测零误写，选定 `deepseek-flash`，
      写入 §6.13；报告 `docs/history/eval/n4-e5-memory-real.md`。入口补 `configure_event_loop_policy()`，否则 Windows 连库失败）

---

### Task 8：顾客端记忆页（C7、§12.4，2026-09-27 编组新增，`shop/`）

PRD §12.4 验收要求「顾客记忆可查看、逐条删除、一键关闭（关闭前有确认且清空数据）」，原计划只有后端路由。
前置：Task 4 三条顾客路由已导出 OpenAPI；`shop/src/api/generated.ts` 由 codegen 生成，禁止手改。

**（2026-09-28，顾客端店面重设计 WS，`plans/2026-09-28-shop-storefront-redesign.md`）** 本页之后会并入 WS 的「动态抽屉」：
- WS Task 10 把本页的逻辑与测试迁到抽屉的「我记住的」页签；
- `/{shop}/memories` 改为重定向到 `/{shop}?panel=memory`，`memories-responsive.spec.ts` 改为从抽屉进入，375px 断言保留。

因此本 Task 的做法：
- 功能与测试按下面三条做完整：列表、逐条删除、关闭确认、访客不请求；
- 样式只做到可用即可，不必投入；
- 逻辑放进可复用的客户端组件，不写死在 `page.tsx` 里，方便 WS 整体搬迁；
- 完成后在进度快照写明状态，WS Task 0 据此决定是迁移还是直接在抽屉里实现。

- 路径 `shop/src/app/[shop_slug]/memories/`（未绑定演示顾客的访客显示绑定提示，不调用接口）；
- 关闭开关前弹出确认，写明「会清空已有 N 条记忆，关闭后不再记住」；确认后才发 `purge_confirmation: "yes"`；
- 过期时间按 `expires_at` 展示；**页面不显示也不接收任何 `buyer_key` / `merchant_id`**。

- [x] **步骤 1：写组件测试**——列表渲染与空态、逐条删除后移除、关闭需二次确认且取消不发请求、访客态不请求、375px 无横向溢出
- [x] **步骤 2：确认失败 → 实现 → 确认通过**；`shop` 的 `test`、`typecheck`、`lint`、`codegen:check`、`build` 通过

---

### Task 9：商家端记忆面板（M11，2026-09-27 编组新增，`frontend/`）

M11 要求事实层「可逐条删除」，但商家没有入口就无法删除。**D-N4-3 于 2026-09-28 裁定：做最小版**。
范围只到下面三条，不做搜索、编辑或批量操作。

**本 Task 是 N4 的第一个可砍项**：它不是 §12 硬验收（顾客记忆页 Task 8 才是）。N4 进度吃紧时由用户决定砍掉；
砍掉时删除本 Task，并在 PRD M11 写明「本版商家记忆仅提供 API」，同步 N4 总览步骤数。

- 事实层列表带来源（跳转到来源对话）；总结层只读展示，标注「由事实自动生成，陈旧时暂停使用」；
- 删除事实后按响应 `summary_rebuild_scheduled` 提示「相关总结将重新生成」；
- **与知识库后台视觉上明确区分**，不提供「提升为团队知识」入口（`docs/frontend-development-plan.md` 知识库一节、§8.14.2 第 5 条）。
- **（2026-09-28，PRD §15「W」）** 本 Task 的页面在 W Task 5（新外壳与 token）完成后再做：
  - 页面直接建在 `MerchantShell` 的「运营」分组，使用新 token，不按旧样式先做一版；
  - 知识库在「管理」分组，两者位置不同，满足上一条的区分要求；
  - 工作区已有的未跟踪草稿 `MerchantMemoryView.vue` 由同一执行者与 W Task 10 步骤 2 协调，见 `plans/2026-09-28-merchant-workbench-redesign.md` §三。

- [x] **步骤 1：写组件测试**——两层分区展示、总结层无删除按钮、删除后提示重建、Adapter 契约测试
- [x] **步骤 2：确认失败 → 实现 → 确认通过**；`npm run test`、`typecheck`、`lint`、`codegen:check`、`build` 通过

**2026-09-30 核实（Opus）：** `frontend/src/views/MerchantMemoryView.vue` 已由 W Task 10 迁入外壳「运营」分组；事实层带来源链接
（`{name:'assistant', query:{conversation}}`，由 `MerchantShell` 转成打开助手栏并载入该对话）、总结层只读并注明陈旧暂停、删除后按
`summary_rebuild_scheduled` 提示重建；`MerchantMemoryView.spec.ts` 与 `merchantMemory.spec.ts` 覆盖；W 收尾时前端全量 746 passed。

---

### Task 10：自检

```powershell
cd backend
rg -n "from app.agent.loop" app/memory/
rg -n "buyer_key|merchant_id" app/api/routes/v2/shop_memory.py
rg -n "knowledge_documents" app/memory/
uv run pytest; uv run ruff check .; uv run mypy app
```

三条期望零命中：记忆不反向依赖循环；顾客记忆响应不含身份原值；
**记忆模块不写团队知识库**（单向边界）。

更新 `docs/project-progress.md`：确认 v1 记忆未被迁入（PRD §14）；
记忆与个性化 Skill 已上线（补齐 PRD C2 的第 5 个）；E5 记忆评测状态；未执行 Git。

**2026-09-30 完成记录（Opus）：** 第 1、3 条 grep 零命中；第 2 条命中 7 处，均为路由用服务端会话身份做查询，不是响应字段——
响应不含身份原值由 `CustomerMemoryItem` 无该字段及 `test_bound_customer_can_list_and_delete_memory`（本次加强为断言原值不出现）验证。
v2 不读写 v1 `merchant_memories`。后端全量 `REQUIRE_INTEGRATION_DB=1`（本地 compose PostgreSQL、空 `LLM_API_KEY`）
**4246 passed / 13 skipped / 0 failed**，`ruff check .`、`mypy app`（291 文件）通过。Task 7 步骤 4 已于同日获授权完成（见 Task 7）。

---

## 本计划明确不做的事

| 不做 | 归属 |
| --- | --- |
| 迁移 v1 商家记忆 | 不做（见上文） |
| 顾客侧总结型画像 | 不做（D16） |
| 过期清理、outbox 排空、总结重建的 Railway Cron 接线 | `n5-budget-ops-and-railway` Task 4 |
