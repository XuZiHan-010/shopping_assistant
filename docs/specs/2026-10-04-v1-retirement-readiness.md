# v1 端点退役就绪清单与弃用公告草稿

> 对应 `plans/2026-09-21-n5-final-eval-and-closeout.md` Task 8 步骤 1–2（2026-10-04）。
> **本文件只做核对与起草，不退役、不删除任何 v1 代码**；是否退役、何时退役由用户决定（步骤 3）。
> 状态取值只有「满足 / 不满足 / 不适用」。

## 一、判定依据

PRD §11.1：v1 端点在 **① 相应 v2 能力实现、② 前端切换、③ 契约测试通过、④ 完成弃用公告** 四项都满足之前继续有效。

核对方法：

- ①③：路由对账（`backend/scripts/audit_routes.py`，v2 缺 0 多 0）与 `tests/api/v2/test_openapi_session_contract.py`；
- ②：在 `frontend/src`（不含测试、生成类型与 Mock）里搜索各 v1 路径的调用点；
- ④：本文件第三节是草稿，**尚未发布**，所以所有端点的第四项目前都是「不满足」。

## 二、逐端点清单

### 可以考虑退役的端点（有 v2 替代）

| v1 端点 | v2 替代 | ① v2 已实现 | ② 前端已切换 | ③ 契约测试 | ④ 公告 | 结论 |
| --- | --- | --- | --- | --- | --- | --- |
| `POST /api/chat` | `POST /api/v2/merchant/chat` | 满足 | 满足——页面只走 v2；`frontend/src/api/chat.ts::submitChat` 仍在但没有任何页面调用 | 满足 | 不满足 | 公告后可退役；同时删除前端残留函数与其测试 |
| `GET /api/conversations`、`GET` / `DELETE /api/conversations/{conversation_id}` | `/api/v2/merchant/conversations` 同名三条 | 满足 | 满足——`listConversations` 无页面调用 | 满足 | 不满足 | 同上 |
| `POST /api/answers/{answer_id}/feedback` | `POST /api/v2/merchant/answers/{answer_id}/feedback` | 满足 | 满足——`submitFeedback` 无页面调用 | 满足 | 不满足 | 同上 |
| `GET /api/reports/daily` | `GET /api/v2/merchant/briefs/daily/current` | 满足 | 满足——前端无调用 | 满足 | 不满足 | 语义不同（昨日经营日报 → 当日简报），公告里要写明；`POST /api/admin/reports/daily/recompute` 随之失去对象 |
| `GET /api/metrics/{code}` | 助手工具 `get_metric_definition`（经 v2 Chat）；没有同形的 v2 REST 端点 | 不满足（无 REST 等价物） | 满足——前端无调用 | 不适用 | 不满足 | 若仍需要按机器码直接读取指标定义，先在 PRD §11.2 增加 v2 路径；否则在公告里说明改由助手回答 |

### 不属于退役对象的端点（v1 与 v2 共用，或没有版本之分）

| 端点 | 原因 |
| --- | --- |
| `GET /api/exports/{export_id}` | 签名导出下载；v2 商家助手生成的导出同样经它下载 |
| `GET /api/demo/merchants` | 演示身份入口；商家端用它取得演示 Token 再换 v2 会话 |
| `GET /api/health`、`GET /api/ready` | 健康与就绪检查，部署平台依赖 |
| `GET /api/admin/ops/status` | 运维看板的数据源（N5 已扩展） |
| `GET /api/admin/analytics/chatbi/overview`、`/categories`、`POST …/rollup` | 运维看板与 Cron 汇总使用 |
| `/api/admin/knowledge/*` 全部 9 条 | 知识库后台；v2 规则检索读的就是它维护的文档 |

### 退役 v1 Chat 之前还要处理的依赖

- **冻结评测基线**：`backend/app/agent/graph.py` 与 v1 Chat 链路是只读评测基线（`tests/eval/test_baseline_freeze.py`、
  `tests/eval/baseline_comparison.py`）。退役 HTTP 端点不等于删除基线代码；若要连同代码一起移除，先决定基线对照是否还保留。
- **Chat BI 汇总**：`chatbi_qa_daily` 统计 `answers` 表，v1 与 v2 的回答都在里面；退役 v1 不影响汇总口径。
- **v1 商家记忆**：`merchant_memories` 与 `POST /api/admin/knowledge/memories/compress` 属 v1 记忆，v2 不读写它（PRD §14）。
  退役 v1 Chat 后这部分不再有新数据，是否保留只读展示需单独裁定。

## 三、弃用公告草稿（未发布）

> **Borough v1 商家对话接口弃用说明（草稿）**
>
> 自 ________ 起，下列 v1 接口进入弃用期，并将于 ________ 停止服务。商家工作台已全部改用 v2 接口，使用工作台的商家不受影响；
> 直接调用这些接口的集成需在停止服务前完成迁移。
>
> | 弃用接口 | 替代接口 | 迁移要点 |
> | --- | --- | --- |
> | `POST /api/chat` | `POST /api/v2/merchant/chat` | 鉴权由 `Authorization: Bearer <演示 Token>` 改为 `X-Session-Id`（先用 Token 调 `POST /api/v2/merchant/sessions` 换会话）；流式事件以 `turn_complete` 携带最终响应 |
> | `GET /api/conversations` 及 `GET` / `DELETE /api/conversations/{conversation_id}` | `/api/v2/merchant/conversations` 对应三条 | 列表改为游标分页 |
> | `POST /api/answers/{answer_id}/feedback` | `POST /api/v2/merchant/answers/{answer_id}/feedback` | 采纳与赞踩分别记录，赞踩可带原因 |
> | `GET /api/reports/daily` | `GET /api/v2/merchant/briefs/daily/current` | 由「昨日经营日报」改为「当日简报」，内容与字段不同 |
> | `GET /api/metrics/{code}` | 在运营助手中询问指标口径 | 不再提供按机器码读取指标定义的独立接口 |
>
> 以下接口**不受影响**：健康检查、演示身份入口、签名导出下载、运维与知识库管理接口。
> 精确字段见 `docs/api.md`。

## 四、交用户决定（步骤 3）

1. 是否退役上表第一组端点，弃用期多长；
2. `GET /api/metrics/{code}` 是直接退役，还是先补一条 v2 REST 路径；
3. 退役后冻结基线代码（`graph.py` 与 v1 Chat 服务）是保留作评测对照，还是一并移除；
4. v1 商家记忆的处置。

在用户决定之前，全部 v1 端点继续有效，路由对账也继续要求它们全部存在。
