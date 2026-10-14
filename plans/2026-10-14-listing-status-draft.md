# 商家 Agent 起草下架 / 重新上架（补齐 PRD M5）

日期：2026-10-14 · 状态：本地已实现并验证，未提交

## 背景

PRD M5 要求「补货、下架、降价均进审批」（融合决策 Q7）。目前实现了补货与降价，**下架漏做**：
`DraftKind` 只有 `RESTOCK / CONTENT_CHANGE / PRICE_CHANGE / COUPON / AFTER_SALE_DECISION`，
商家工具只有 `draft_restock`，但库存运营 Skill 照搬上游写了「库存暂停、下架属于本 Skill 的起草范围」。
上游 `vendor/anthropic-commerce-agents` 的 `stage_inventory_action` 支持 `restock / pause / activate`。

## 范围决定

- 新增一种草稿 `LISTING_STATUS`，同时覆盖**下架**（`PAUSE`：ONLINE → OFFLINE）与**重新上架**
  （`ACTIVATE`：OFFLINE → ONLINE）。理由：商家工作台没有手动上下架入口，只做下架会让它成为单向操作。
  PRD M5 同步补一句「重新上架同样进审批」。
- 只在 `ONLINE ↔ OFFLINE` 之间切换；`AUDITING / REJECTED` 状态拒绝起草与应用（业务护栏，公开原因码）。
- 单商品一份草稿，不做批量（`batch_id` 仍只给 `CONTENT_CHANGE`）。
- 不写库存事件账本：上下架不改在库量，与调价一致，审计由 `change_ledger` 承担。
- 不开放给 MCP（起草工具都不对外）。
- 顾客端的下架效果（目录过滤、购物车剔除、下单 `PRODUCT_NOT_IN_SCOPE`）已存在，不改。
- 库存告警只看 `ONLINE` 商品（已有行为），下架后告警自然消失。

## 设计

| 项 | 取值 |
| --- | --- |
| DraftKind | `LISTING_STATUS` |
| 工具 | `draft_listing_status(product_id, action: PAUSE \| ACTIVATE)`，`MERCHANT_DRAFT`，不可并行，来源闸门要求 `product_id` 为本对话产出的 `PRODUCT` 引用 |
| 护栏 | `check_listing_status`：PAUSE 要求当前 `ONLINE`，ACTIVATE 要求当前 `OFFLINE`；否则 `LISTING_STATUS_NOT_TOGGLEABLE`（双语 current_limit / remediation） |
| target_version | 起草时状态编码：`ONLINE=1`、`OFFLINE=0`（与调价把基数编进 target_version 的做法一致） |
| payload | `action`、`base_status`、`new_status`、`product_title` |
| 差异 | 一个条目：`entry_id={draft_id}:status`，`field=status`，`unit=TEXT`，`before/after` 为状态值，`is_preview=false` |
| 应用 | `ListingStatusHandler`：核对 entry、target_version；应用时重跑护栏；`UPDATE products SET status=new WHERE id, merchant_id, status=base`，rowcount≠1 → `VersionConflictError(TARGET)` |
| 前端 | 审批列表种类标签（中/英）；审批详情把 `status` 字段的值显示为「在售 / 已下架」 |

## 同步清单

PRD M5 → `docs/backend-development-plan.md` §8.13（DraftKind、target_version 说明、已开放处理器）→
Pydantic Schema → OpenAPI / `docs/api.md` / `docs/api.json` → 两端 `generated.ts`（codegen）→
商家端 Adapter / 标签 / 测试 → Skill 文案 → `docs/project-progress.md`。

## 验收

- 单测：Schema、护栏、工具（来源闸门、护栏拒绝、提案形状）、差异、分派。
- 集成（一次性 pgvector 库）：起草 → 审批详情 → 批准 → 商品状态改变并写账本；并发改状态后批准 409；
  应用时护栏不过 → 拒绝；跨商家不可见；重新上架同样走通。
- 前端单测、typecheck、lint、两端 `codegen:check`；后端 Ruff、mypy。
- 全程 Fake LLM，不调用真实模型。
