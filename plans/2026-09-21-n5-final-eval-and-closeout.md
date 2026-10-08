# N5 全量评测、对外演示与文档收口实施计划

> **给执行者：** 用 `superpowers:executing-plans` 逐任务推进。步骤用 `- [ ]` 复选框跟踪。
> **本计划不含任何 Git 提交步骤**（R2）。
> **Task 3 性能基准需在 Railway 基准环境运行（生产变更，需同意）；
> Task 4 的真实模型评测与 LLM 裁判需 R3 授权。**

**目标：** 按 PRD §12 逐条产出可运行证据，完成 §10.1 性能基准、E1–E6 全量评测报告、
双端对外演示与文档收口。**本计划不新增功能**——它只证明前面 19 份计划的交付达标，
并把实施中形成的决定回写到权威文档。

**架构：** 验收以**真实运行结果**为准，不以计划文档为准。路由覆盖用 `app.routes` 对账，
场景用 E2E 与评测报告对账，性能用基准环境实测对账。

**规格来源：** PRD §10.1、§12 全节、E1–E6、§15 N5；`AGENTS.md` §三（完成边界）、§五（文档权威）。

---

## 入口条件

> **预写计划不是已验证实现。** 本计划写于上游代码尚不存在时，文中引用的类名、函数签名、
> 工具名、表字段、错误码都是**当时的设计**。开工前逐项对照上游**实际落地**的接口；
> 不一致时先按 PRD → 契约 → 计划的顺序修正，**再动代码**，不得在实现里默默适配或绕过。

- [ ] N1–N5 其余 19 份计划全部完成（N1 共 5 份、N2–N5 共 15 份，本计划除外），以及其后插入的
      `plans/2026-09-28-merchant-workbench-redesign.md`（W）、`plans/2026-09-28-shop-storefront-redesign.md`（WS）、
      `plans/2026-10-02-n5-single-entry.md`（D-N5-4）；
- [ ] `n5-budget-ops-and-railway` 的公开部署前置条件已验收通过；
- [ ] N2–N4 执行期间发现的每一项与 PRD 的不一致，**都已在发现当时**按
      PRD → 契约 → 计划 → 索引处理，没有攒到本计划。

---

## 全局约束

- 中文（R1）；**不执行 Git 操作**（R2）；**真实调用受 R3 约束**。
- **不得把局部通过称为全量通过**（`AGENTS.md` §三）。未授权、未执行、未达标的条目
  如实标注，不以"基本满足"带过。
- **不得把 Fake LLM 下的结构验证称为质量验证**。

---

### Task 1：路由覆盖对账（以代码为准）

计划文档用缩写写路径，文本匹配会漏报（写计划时的核对就出现过 10 条假阴性）。
**收口时代码已存在，用 FastAPI 的真实路由表对账**：

```python
# backend/scripts/audit_routes.py
import re
from pathlib import Path
from app.main import app

prd = Path("../docs/PRD.md").read_text("utf-8")
sec = prd.split("#### 11.2.2")[1].split("#### 11.2.4")[0]
expected = set(re.findall(r"`(GET|POST|PUT|DELETE) (/api/v2/[^`]+)`", sec))

actual = {(m, r.path) for r in app.routes if r.path.startswith("/api/v2/")
          for m in getattr(r, "methods", ()) if m in {"GET", "POST", "PUT", "DELETE"}}

missing, extra = expected - actual, actual - expected
print(f"PRD {len(expected)} 条；已实现 {len(expected & actual)}；缺 {len(missing)}；多 {len(extra)}")
for m, p in sorted(missing): print("  缺", m, p)
for m, p in sorted(extra):   print("  多", m, p)
```

2026-09-28 以同一口径对 `docs/api.json` 预跑：PRD 50 条、已导出 44 条、**缺 6、多 0**——
N4 记忆 5 条、N5 MCP 1 条（N3 的 `GET /merchant/products/content`、`GET /merchant/coupons` 已于 2026-09-27 补齐）。
**2026-10-02 复跑**（N4 收尾后）：PRD 53 条（含 W 新增 3 条）、已导出 52 条，**只缺 `POST /api/v2/merchant/mcp`**，多 0。
收口时以 `app.routes` 重跑为准，本数字只作进度参照。

**2026-10-04 执行**：`backend/scripts/audit_routes.py`（`uv run python -m scripts.audit_routes`）+ `tests/api/test_route_audit.py` 7 例。
当前 FastAPI 把 `include_router` 的子路由放在惰性结构里，上面的示例直接遍历 `app.routes` 读到 0 条；脚本改经
`effective_route_contexts()` 展开，并把不进 OpenAPI 的隐藏路由也算进「多」（只点名放行 MCP 入口对 GET 的显式 405）。
结果：v2 PRD 53 条、已实现 53、**缺 0、多 0**；v1 25 条全在；附件三个端点不存在。

- [x] **步骤 1：运行**，期望 **缺 0、多 0**
- [x] **步骤 2：附加检查**——附件三个端点**不存在**（PRD §11.2.4）；v1 端点全部仍在（PRD §11.1 迁移期不废弃）
- [x] **步骤 3："多"不为 0 时**：多出的路径要么补进 PRD §11.2（按 `AGENTS.md` §五先改 PRD），
      要么删除——**不允许代码里存在 PRD 之外的 v2 路径**

---

### Task 2：PRD §12 验收矩阵

逐条列出 §12.1–§12.6 的每一项，每项必须指向**可运行证据**：

| 列 | 内容 |
| --- | --- |
| 条目 | §12 原文 |
| 证据 | 测试文件 + 用例名，或报告文件路径 |
| 状态 | `通过` / `未通过` / `待授权` / `未执行` |
| 最近运行 | 日期与命令 |

落 `docs/specs/2026-XX-XX-n5-acceptance-matrix.md`。

**§12.1 安全与隔离是硬门禁，零失败**。其中时序侧信道一项的阈值是**各 500 次、
中位数绝对差 ≤ 10ms、p95 比值 0.8–1.25**（会话计划已按此实现），
**必须在本地独占测试库上跑**，并记录机器配置——该指标对环境敏感，换机器要重测。

- [x] **步骤 1：生成矩阵骨架**（§12 每条一行）
- [x] **步骤 2：逐条填证据并实际运行**
- [x] **步骤 3：§12.1 任一未通过即停止收口**，回到对应计划修复

---

### Task 3：§10.1 性能基准

**基准环境是规格的一部分**：Railway Hobby 级 Backend + PostgreSQL（生产主库为外部 Neon；**基准库不得直接用现网演示库灌 5 万订单**，
用哪个实例在步骤 2 请求同意时一并说明，PRD §10.1 2026-10-02 修订），3 个商家、180 天数据，
约 5 万订单 / 12 万订单项 / 各 5 千退款与退货 / 3 千工单；并发 10 个会话持续 3 分钟。

- [x] **步骤 1：生成基准规模数据**——扩展确定性种子到上述规模，**同种子可复现**
- [ ] **步骤 2：请求用户同意后在 Railway 基准环境部署并灌数**（生产变更）
- [ ] **步骤 3：跑基准**，逐项对照：

| 指标 | 阈值 |
| --- | --- |
| 健康检查 | p95 < 200ms |
| 首个 SSE 事件 | 1 秒内 |
| 非 LLM 普通 API | p95 < 500ms，单请求超时 5 秒 |
| 商家指标数据工具 | p95 < 500ms |
| 顾客商品检索 | p95 < 500ms，且质量不劣于关键词基线 |
| 聊天总时限 | 60 秒内完成或明确错误 / 降级 |
| 每日简报读取 | p95 < 500ms |
| 图表数据量 | 单序列 ≤ 180 点，多序列合计 ≤ 720 点 |
| 并发稳定性 | 10 会话 / 3 分钟无超时，非预期错误率 0 |

聊天相关指标在基准中**用 Fake LLM**（测的是系统开销，不是模型延迟），报告写明这一点。

- [ ] **步骤 4：报告落 `docs/history/perf/`**，记录数据快照、并发数、版本与**原始统计结果**——
      PRD 明确"不能只报孤立数字"

---

### Task 4：E1–E5 全量评测报告

- [x] **步骤 1：评测集规模与分层检查**——≥ 100 条，按 Skill / 角色 / 风险 / 语言分层，含多轮
      （`app/eval/cases.py` 的分层校验应已拦截不达标的集合）
- [x] **步骤 2：CI Fake LLM 回归**——确定性通过，`skip` 不计入分母，关键安全集零失败
- [x] **步骤 3：E5 专项汇总**——RAG、记忆、压缩三份专项报告（N4 已产出：`docs/history/eval/rag-baseline.md`、`rag-hybrid.md`、
      `n4-e5-memory-real.md`、`n4-e5-compaction-fake.md`、`n4-e5-compaction-real.md`）合并引用，逐份保留「Fake / 探索性 / 真实」分层
- [x] **步骤 4：真实模型评测已执行，质量未通过**——2026-10-06 用户允许在已说明的 DeepSeek `deepseek-flash` 批次上限内运行；N5 固定 25 条，三轮加售后单例复测共 179 次上游调用、按账本计 383,738 token（授权上限 325 次 / 500,000 token）。最终快照 13/25，N5 快捷提问 6/8；详见 `docs/history/eval/n5-real-quality-2026-10-06.md`，不能将“已执行”当成“验收通过”。
      **未授权则报告明确标注"真实模型质量未评测"**，不以 Fake 结果代替。
      **一并列入同一次审批说明的遗留真实评测**（2026-10-02 登记，均 `deepseek-flash`，可逐项同意）：
      N4 三项——压缩冻结口径（数据集哈希 `186448b48530a528`）后重跑（N4-3③）、混合检索下的引用正确率 / 忠实度裁判（约 128 次）、
      收紧后的记忆抽取复测（约 40 次）；N3 三项可选费用点的真实模型验收（`plans/2026-09-26-n3-independent-review.md` 顶部清单第 7 项，
      开工时先核对入口与样本再报调用量）
- [x] **步骤 5：报告落 `docs/history/eval/n5-full-report.md`**

---

### Task 5：E6 线上反馈回流

- 点踩与降级样本先**脱敏、去重、归因**，再由**人工决定**是否进入评测集（Q30）；
- **不得自动把线上内容用于训练或写入提示词**；
- **防止同一案例同时进入调优集与最终测试集**——两个集合按案例指纹互斥。

- [x] **步骤 1：写回流脚本**，产出候选清单供人工审阅，**脚本本身不写评测集**
- [x] **步骤 2：写互斥测试**

```python
def test_tuning_and_final_sets_are_disjoint() -> None:
    tuning = {fingerprint(c) for c in load_cases("tuning")}
    final = {fingerprint(c) for c in load_cases("final")}
    assert tuning.isdisjoint(final)


def test_feedback_script_never_writes_eval_datasets(tmp_path, monkeypatch) -> None:
    before = snapshot_dir("app/eval/datasets")
    run_feedback_harvest(output=tmp_path)
    assert snapshot_dir("app/eval/datasets") == before
```

---

### Task 6：冻结基线最终对照

- [x] **步骤 1：确认 `graph.py` 未部署到生产**——生产路由表中不存在把 v2 请求导向冻结图的路径
- [x] **步骤 2：在共有旧能力上跑最终对照**，与 N2 的对照报告对比趋势
- [x] **步骤 3：`test_frozen_graph_nodes_unchanged` 仍通过**——冻结在整个 N2–N5 期间未被破坏

---

### Task 7：双端对外演示

PRD §15 N5「双端对外演示」。

- [x] **步骤 1：写演示脚本** `docs/demo-script.md`，按 S1–S8 组织，每条场景写明：
      入口（**对外只给商家端一个链接**，顾客端场景从商家端侧栏「顾客视角」新标签进入，D-N5-4）、操作步骤、
      **此处体现的安全或治理规则**（例如「顾客视角只是链接，顾客端另起访客会话，两端会话不可互换」）
- [x] **步骤 2：标注演示边界**——支付、退款为演示；演示身份非真实登录；数据为确定性演示数据
- [ ] **步骤 3：按脚本在部署环境完整走一遍**，记录每条场景的实际结果

演示脚本中"此处体现的规则"一列，是把工程约束**讲出来**的关键——
例如 S3 批准时点出"批准绑定草案版本、应用时复检当前库存、聊天里的批准不生效"。
可参考 `frontend/prototypes/borough-dual-end-prototype.html` 的治理标注方式组织讲解。
商家端按 PRD §15「W」重设计后的界面演示：入口 URL 为首页 `/`，助手从助手栏打开；不再使用 `/ops-assistant` 整页。
顾客端按「WS」重设计后的界面演示：
- 入口 `/{shop_slug}` 为智能助手首页，购物车在右侧常驻；
- 旧路径 `/assistant`、`/cart`、`/memories` 只做重定向；
- 商品图片未交付时如实演示“暂无图片”占位。

---

### Task 8：v1 退役准备（不执行退役）

PRD §11.1：v1 端点在"相应 v2 能力实现、前端切换、契约测试通过并完成弃用公告"前继续有效。

- [x] **步骤 1：逐条核对四个条件**，形成 v1 端点退役就绪清单
- [x] **步骤 2：起草弃用公告**，列出每个 v1 端点对应的 v2 替代
- [ ] **步骤 3：交用户决定**是否及何时退役——**本计划不删除任何 v1 代码**

---

### Task 9：文档收口与一致性复核

`AGENTS.md` §五：范围变化的顺序是**先改 PRD → 再改契约 → 再改计划 → 最后同步索引**，
而且**必须在对应实现开工之前**完成。**N5 收口不是回写 PRD 的时机**——等到这里才回写，
等于 N2–N4 一直按与 PRD 不一致的计划在实现。

写计划时发现的 7 项不一致，**已于 2026-09-21 按用户裁定在任何实现开工前完成四层同步**：

| 裁定 | PRD 位置 | 契约 / 计划 |
| --- | --- | --- |
| S3 在 N2 用确定性最小简报闭环，完整 M2 留 N3 | §15 N2、N3 | 契约计划组 5；`n2-merchant-drafts-and-inventory` |
| 记忆与个性化 Skill 移至 N4 | §15 N3、N4 | `n3-customer-skills-and-after-sales`、`n4-memory-pipeline` |
| M13 与双端会话目录归入 N2 | §15 N2 | `n2-conversations-and-feedback` |
| v1 商家记忆不迁入 v2 | §14 | `n4-memory-pipeline` |
| 商家售后决定统一走草稿审批 | M9 | 契约计划 `DraftKind.AFTER_SALE_DECISION`；两份 N3 计划 |
| MCP 凭证只经后端命令行脚本签发与撤销 | A8 | 契约计划 §8.14；`n5-mcp-readonly` |
| 未绑定访客刷新后原购物车暂时无法访问（非删除） | C3 | `n2-shop-nextjs-app` |

此后 N2–N4 执行期间又有下列裁定（2026-09-27 编组时补录，复核范围同上表）：

| 裁定 | PRD 位置 | 契约 / 计划 |
| --- | --- | --- |
| 售后各跳的触发方与顾客补充说明路径（2026-09-24） | §7.2、C6、§11.2.2 | 契约 §8.11；`n3-customer-skills-and-after-sales` Task 4、7、8 |
| 商家端 v2 运营助手页与 v1 分析助手并存（2026-09-24） | §15 N2 | `n2-merchant-vue-v2-migration` |
| 商品内容批量草稿 `batch_id`（2026-09-25，契约先行） | M4 | 契约 §8.13.1–§8.13.3；`n3-merchant-skills` Task 3 |
| 商品属性值统一为 Mapping 结构（2026-09-26） | M4、D11 | `n3-merchant-skills` Task 3、7 |
| 两页合并「选项 C」：先补图表可视化再合并，v1 前端下线、v1 后端保留（2026-09-27） | §15 N2 | 契约 §8.7.11；`n3-merchant-skills` Task 9 |
| D-N4-1 多轮历史回放：同会话最近 6 轮文字，不回放工具结果；**历史中的数字视为无来源**（2026-09-28） | A5 | 契约 §8.8.3 / §8.9.3、§6.10；`n4-context-compaction` Task 0 |
| D-N4-2 访客回合不抽取记忆，绑定后不补抽（2026-09-28） | C7 | 后端计划 §6.13；`n4-memory-pipeline` Task 3 |
| D-N4-3 商家记忆面板做最小版，列为 N4 第一个可砍项（2026-09-28） | M11（若被砍则改写） | `n4-memory-pipeline` Task 9 |
| D-N5-1 运维看板为新建只读管理员页 `OpsStatusView.vue`（2026-09-28） | §14、§10.4 | `n5-budget-ops-and-railway` Task 3 步骤 3 |
| D-N5-2 已删 E2E：会话目录与双语已重建；`real-api/analytics.spec.ts` 不在浏览器层重建；`ops-dashboard.spec.ts` 随新看板重写（2026-09-28） | §12.4、§10.6 | 本计划 Task 9 步骤 1a |
| D-N5-3 MCP 默认不提前；用户提出时间节点时启用「N4-A 完成后 Opus 接做 N5-A」（2026-09-28） | —（排期） | `plans/2026-09-27-n5-module-roadmap.md` §三 |
| W 商家工作台界面重设计：`/` 为首页、助手栏默认收起、知识库入「管理」分组须管理员令牌、新增订单区与首页主指标（2026-09-28） | M1、§11.2.3、§14、§15「W」 | 契约 §8.12.4；`plans/2026-09-28-merchant-workbench-redesign.md` |
| WS 顾客端店面重设计：智能助手首页、右侧常驻购物车、订单视图、动态抽屉；热门排序、缺失属性、订单摘要首件商品、只读工具 `get_my_order`；演示商品换真实名与图片（2026-09-28） | C1、C2、§8.3、§11.2.2 语义、§15「WS」（由 WS Task 1 写入） | 契约 §8.8.1、§8.8.2、§8.10.1、顾客工具说明；`plans/2026-09-28-shop-storefront-redesign.md` |
| `search_rules` 改为全文档检索（不再固定「平台规则」域），v1 与 `load_domain` 不变（2026-10-01） | A7、C2 规则问答 | 后端计划 §6.14；`n4-hybrid-retrieval`；E5 报告 `rag-baseline.md` |
| 嵌入模型选 `BAAI/bge-small-zh-v1.5`（中文为主、成本约为 gemma 的 1/5），加字段名精确匹配；重排器不保留（2026-10-02） | A7、M12、§7.6 | 后端计划 §6.14；`docs/deployment.md`；E5 报告 `rag-hybrid.md` |
| 生产主库为外部 Neon（`vector` 0.8.6），Railway 内为四个服务（2026-10-02 确认） | §10.1、§10.7、§15 N5 | `AGENTS.md` §十一；`docs/deployment.md`；`n5-budget-ops-and-railway` Task 5 |
| D-N5-4 单入口演示：商家端侧栏「顾客视角」新标签打开本店顾客端，顾客端快捷提问覆盖五个 Skill 与规则问答（2026-10-02 裁定；2026-10-04 本地联调确认位置） | M1、C1、§10.7、§15 N5 | 契约 §8.9.1 `MerchantSessionCreateResponse.shop_slug`；前端计划第 18 条；`plans/2026-10-02-n5-single-entry.md` |

本任务在收口时**只做复核**：确认上表每一项在 PRD、契约、实现与测试中仍然一致；
若实施中又出现新的不一致，它应当已在**发现当时**按四层顺序处理，
**在这里发现未处理的不一致，说明流程在前面失守了**，须如实记入进度快照。

唯一留到 N4 才能确定的是**压缩策略选型依据**（真实评测或保守默认），
由 `n4-context-compaction` 在选定时写入后端计划 §6.12，本任务复核其已写入。

- [x] **步骤 1：逐项复核上表**，并检查 N2–N4 执行期间是否有新增的不一致被遗漏
- [x] **步骤 1a：前端 E2E 验证缺口复核**（2026-09-27 编组新增；D-N5-2 于 2026-09-28 裁定）——两页合并时整份删除的
      4 份 E2E 按下表逐项核对，**矩阵中每一行都要有落点，不得静默略过**：

  | 已删除 | 处置 | 状态（2026-10-02 更新） |
  | --- | --- | --- |
  | `conversation.spec.ts`（13 例） | 以 `e2e/support/v2MerchantMock.ts` 重建为 `ops-assistant-conversation.spec.ts` | 已重建 **6 例**（一问一答、打开历史、删除、反馈回执、切换商家清空，2026-09-28 补「新建对话」一例并做变异检验）；顾客端 375px 的新建 / 浏览 / 跳转 / 删除由 `shop/e2e/conversations-responsive.spec.ts` 覆盖；收口时对照 §12.4 逐条核对 |
  | `localization.spec.ts` | 重建为 `ops-assistant-localization.spec.ts` | 已重建 2 例；**§10.6「缺译文回退源文并标注」**由 `shop/src/components/components.test.tsx` 两例组件测试覆盖（N4 阶段 0 复核，2026-09-28），不另补浏览器用例；矩阵写明替代证据文件 |
  | `ops-dashboard.spec.ts` | 随 D-N5-1 新页面重写为 `ops-status.spec.ts` | 待 `n5-budget-ops-and-railway` Task 3 步骤 3 |
  | `real-api/analytics.spec.ts`（8 例） | **不在浏览器层重建**：对应的 v1 前端已下线；v1 后端能力由后端集成测试覆盖，v2 导出与隔离由后端集成、`tests/e2e/` 场景与安全集覆盖 | 矩阵中写「浏览器层不重复验证」并列出替代证据文件；**不得写成「已覆盖」而不给文件** |

  前两行已重建的用例在 W Task 6 步骤 3 中只改入口（`/` 改为首页，助手从助手栏打开），不删断言。收口时以改入口后的版本核对。
  顾客端的 `conversations-responsive.spec.ts`、`memories-responsive.spec.ts`、S1、S4 同理，以 WS Task 13 改过入口的版本为准，核对 375px 与 §12.4 断言都还在。
- [ ] **步骤 2：更新 `docs/project-progress.md`** 为 N5 完成后的快照
- [ ] **步骤 3：更新 `docs/project-navigation.md`**——新目录（`shop/`、`app/tools/` 等）
      的"尚未创建"标记改为实际状态
- [ ] **步骤 4：仅当稳定约束变化时更新 `AGENTS.md`**（`AGENTS.md` §十二）
- [ ] **步骤 5：最终自检**

```powershell
cd "d:/vscode html/merchant_assistant"
git status --porcelain vendor/ "yshopping-merchant-ai 4/" yshopping-prototype/
git diff --check
```

第一条期望无输出（R8）。

---

## 执行记录（2026-10-04，部分完成）

本计划的入口条件尚未全部满足（公开部署前置条件未验收）。按 N5 总览 §三，先做了不依赖部署与授权的部分：

| Task | 状态 | 说明 |
| --- | --- | --- |
| 1 路由对账 | 完成 | v2 PRD 53 / 已实现 53 / 缺 0 / 多 0；v1 25 条全在；附件端点不存在 |
| 2 验收矩阵 | 已建立，尚未全通过 | `docs/specs/2026-10-04-n5-acceptance-matrix.md`：§12 共 40 条；2026-10-05 复核发现 §12.5 #4 真实压缩来源保留未通过；§12.1 八条本地证据通过；待授权与未执行项单列 |
| 3 性能基准 | 步骤 1 完成 | 基准规模数据可确定性生成并已在本地一次性库实灌（56,390 订单）；步骤 2–4 需基准环境（生产变更，待同意），**未执行** |
| 4 全量评测报告 | 步骤 1–3、5 完成 | `docs/history/eval/n5-full-report.md`；步骤 4 真实模型评测 **待 R3 授权，未执行** |
| 5 E6 回流 | 完成 | `app/eval/feedback_harvest.py`；未对任何线上库运行 |
| 6 冻结基线 | 完成 | 三项测试在后端全量中通过 |
| 7 对外演示 | 步骤 1–2 完成 | `docs/demo-script.md`；步骤 3（部署环境走查）未执行 |
| 8 v1 退役准备 | 步骤 1–2 完成 | `docs/specs/2026-10-04-v1-retirement-readiness.md`；步骤 3 待用户决定 |
| 9 文档收口 | 步骤 1、1a 完成 | 22 项裁定锚点核对，发现 1 处未处理的不一致（D-N5-4 按钮位置，待用户裁定）；步骤 2–5 留到收口（`CURRENT_MILESTONE` 仍为 `"N4"`） |

证据与偏离裁定见 `.superpowers/sdd/2026-09-21-n5-final-eval-and-closeout/progress.md`。**N1–N5 尚不能宣称完成。**

## 完成的定义

**以下全部成立，N1–N5 才算完成**：

- Task 1 路由对账：缺 0、多 0；
- Task 2 验收矩阵：§12.1 全部通过；其余条目状态如实，`待授权` 与 `未执行` 单独列出；
- Task 3 性能报告存在且附原始统计；
- Task 4 报告写明哪些是 Fake 结构验证、哪些是真实模型评测；
- Task 9 复核：七项裁定在 PRD、契约、实现与测试中一致，且无遗漏的新增不一致。

任何一项不成立时，在进度快照中**如实写明缺什么**，不宣称全量完成。
