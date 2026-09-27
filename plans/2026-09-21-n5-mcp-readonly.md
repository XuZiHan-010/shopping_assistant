# N5 MCP 只读服务实施计划（S8）

> **给执行者：** 用 `superpowers:executing-plans` 逐任务推进。步骤用 `- [ ]` 复选框跟踪。
> **本计划不含任何 Git 提交步骤**（R2）。MCP 集成测试**不经过 LLM**，零费用。

**目标：** 实现 PRD A8：通过 `POST /api/v2/merchant/mcp` 向外部 MCP 客户端暴露**只读工具子集**，
使用独立、短期、可撤销、限定商家与 scope 的凭证，使**场景 S8 可跑**：
外部客户端拿到的数字与商家工作台一致。

**架构：** MCP 是工具注册表的**另一个出口**，不是另一套工具。它消费
`registry.surface_for_mcp()`——即商家 `READ_ONLY` 工具的子集（§6.9）——
因此"数字与工作台一致"是**结构上的必然**，而不是靠两套实现对齐。

**技术栈：** Python 3.12、MCP Python SDK（显式配置协议版本）、pytest、标准 MCP 客户端。

**规格来源：** PRD A8、SEC12、S8、§12.5；契约计划 §8.14 第 4 点（**协议与鉴权的权威定义**）；
后端计划 §6.9；`AGENTS.md` §8.3；协议依据
`https://blog.modelcontextprotocol.io/posts/2026-07-28/`（O7：只读核实官方文档，零费用）。

---

## 入口条件

> **预写计划不是已验证实现。** 本计划写于上游代码尚不存在时，文中引用的类名、函数签名、
> 工具名、表字段、错误码都是**当时的设计**。开工前逐项对照上游**实际落地**的接口；
> 不一致时先按 PRD → 契约 → 计划的顺序修正，**再动代码**，不得在实现里默默适配或绕过。

- [ ] `n3-merchant-skills` 已完成：商家只读工具（指标、库存、口径）已注册；
- [ ] 契约计划 Task 8 已完成：§8.14 的 MCP 工具白名单已定；
- [ ] **核对 `n3-merchant-skills` 实际注册的只读工具名与 §8.14 白名单一致**——
      本计划写作时这些工具尚不存在，名字以实际注册表为准；
- [ ] **重新核对官方协议说明**——协议版本固定为 `2026-07-28`，但 SDK 版本可能已更新，
      开工当天确认 SDK 对该版本的支持方式。

> **2026-09-27 编组核对**（见 `plans/2026-09-27-n5-module-roadmap.md` §二）：`registry.surface_for_mcp()` 已存在
> （`app/tools/registry.py:99`，按 `ToolRole.MCP_READONLY` 过滤）。§8.14.3 白名单 7 个工具中已标 `MCP_READONLY` 的
> **只有 6 个**：`query_metrics`、`get_inventory_alerts`、`get_product_content`、`list_coupons`、`get_metric_definition`、
> `search_rules`；**`attribute_change` 只有 `ToolRole.MERCHANT`**（`app/tools/merchant/metrics.py:164`）。
> 契约是权威，按「整改实现」处理，见 Task 0。

---

### Task 0：工具面与契约对齐（2026-09-27 编组新增）

- [ ] **步骤 1：给 `attribute_change` 补 `ToolRole.MCP_READONLY`**，并写测试断言
      `{s.name for s in registry.surface_for_mcp()} == set(McpReadOnlyTool)`（白名单与注册表双向相等，
      以后任一侧漂移都会失败）；同时断言 MCP 工具输出**不含 `chart_data`**——该字段专供工作台渲染
      （§8.7.11），不属于 MCP 契约

---

## 已裁定：凭证签发与撤销（2026-09-21 用户裁定，已写入 PRD A8 与契约计划 §8.14）

- 由**后端命令行脚本**签发与撤销：`python -m scripts.mcp_credentials issue / revoke`；
- **不增加任何 HTTP 路径，不做商家自助页**；
- 凭证必须**限定商家、scope 与有效期**；
- **原值只在签发时展示一次**，库中只存哈希；
- **撤销后的下一次请求必须立即失效**，不缓存校验结果。

**本裁定只确定方案，尚未签发任何凭证**。实际签发发生在 Task 4 的 S8 集成测试中，
且只针对本地测试库；线上签发属生产变更，另行征得同意。

---

## 全局约束

- 中文（R1）；**不执行 Git 操作**（R2）；**不调用真实 LLM**（R3）。
- **只读**：MCP 工具面只能是商家 `READ_ONLY` 工具的子集，**任何写工具都不得出现**。
- **不接受 `X-Session-Id`**，不把浏览器会话 ID 交给第三方（A8、SEC12）。
- **协议固定 `2026-07-28`**：无协议会话的 Streamable HTTP，**不实现旧版 `initialize` /
  `initialized`，不接收也不签发 `Mcp-Session-Id`**（契约计划 §8.14）。
- 审批证据与确认令牌**不得通过 MCP 获得**（契约计划 §8.7.9）。

---

## 文件结构

| 文件 | 责任 |
| --- | --- |
| `backend/app/mcp/__init__.py` | 包 |
| `backend/app/mcp/credentials.py` | MCP 凭证：签发、哈希存储、校验、撤销 |
| `backend/app/mcp/server.py` | 协议头校验、JSON-RPC 分发、工具面投影 |
| `backend/app/api/routes/v2/merchant_mcp.py` | `POST /api/v2/merchant/mcp` |
| `backend/app/models/mcp_credential.py` | 凭证表 |
| `backend/migrations/versions/*_mcp_credentials.py` | 建表 |
| `backend/scripts/mcp_credentials.py` | 凭证签发、撤销与列表（列表不含原值）的命令行脚本 |
| `backend/tests/integration/mcp/test_standard_client.py` | **标准 MCP 客户端集成测试** |

---

### Task 1：凭证

与会话凭证同一安全等级：**高熵生成、库里只存指纹、可过期、可撤销**
（复用 `app/core/session.py` 的 `new_session_token()` 与 `token_fingerprint()`，不另写）。

表 `mcp_credentials`：`id`、`token_fingerprint`（UNIQUE）、`merchant_id`、`scopes`（JSONB）、
`created_at`、`expires_at`、`revoked_at`、`label`。

- 默认有效期短（建议 24 小时）；
- `scopes` 限定可用工具子集，**只能是 MCP 只读白名单的子集**；
- **撤销立即生效**：每次请求都查库校验 `revoked_at IS NULL`，**不缓存校验结果**
  （PRD §12.5"撤销后立即失效"——缓存哪怕 60 秒也会违反它）。

- [ ] **步骤 1：写失败测试**

```python
async def test_revocation_takes_effect_on_next_request(client) -> None:
    token = await issue(merchant=M, scopes={"query_metrics"})
    assert (await mcp_call(client, token, "tools/list")).status_code == 200
    await revoke(token)
    assert (await mcp_call(client, token, "tools/list")).status_code == 401


async def test_token_stored_as_fingerprint_only(db) -> None:
    token = await issue(merchant=M, scopes={"query_metrics"})
    assert token not in json.dumps(await dump_table(db, "mcp_credentials"))


def test_plaintext_shown_exactly_once(capsys) -> None:
    """裁定：原值只在签发时展示一次；此后没有任何命令能再取回。"""
    token = run_cli("issue", merchant=M, scopes="query_metrics", ttl_hours=24)
    assert token in capsys.readouterr().out
    listing = run_cli("list", merchant=M)
    assert token not in listing


def test_issue_requires_merchant_scope_and_expiry() -> None:
    for missing in ("merchant", "scopes", "ttl_hours"):
        with pytest.raises(SystemExit):
            run_cli("issue", **without(missing, merchant=M, scopes="query_metrics",
                                         ttl_hours=24))


def test_no_http_route_for_credentials() -> None:
    """裁定：不增加 HTTP 路径。"""
    from app.main import app
    assert not [r for r in app.routes if "credential" in r.path or "mcp/token" in r.path]


def test_scopes_cannot_include_write_tools() -> None:
    with pytest.raises(ValueError):
        issue_sync(merchant=M, scopes={"draft_restock"})


async def test_browser_session_id_rejected(client) -> None:
    r = await client.post("/api/v2/merchant/mcp", headers={"X-Session-Id": MERCHANT_SID,
                                                           **MCP_HEADERS}, json=LIST_TOOLS)
    assert r.status_code == 401
```

- [ ] **步骤 2：确认失败 → 实现 → 确认通过**

---

### Task 2：协议头与鉴权顺序（契约计划 §8.14）

**处理顺序固定**：

```text
1. 鉴权：Authorization: Bearer <MCP access token>
   缺失或无效 → HTTP 401 + WWW-Authenticate，**不解析 JSON-RPC 正文**
2. 协议头：MCP-Protocol-Version 必须等于 2026-07-28
3. 一致性：Mcp-Method、Mcp-Name 请求头与 JSON-RPC 2.0 正文中的 method、name 一致
4. 分发到工具
   方法 / 参数 / 工具错误 → JSON-RPC error，**不包装成 v2 ErrorResponse**
```

第 1 步在解析正文之前，是为了让未认证的请求**连正文解析器都碰不到**——
解析器本身也是攻击面。

- [ ] **步骤 1：写失败测试**

```python
async def test_unauthenticated_request_not_parsed(client, spy_parser) -> None:
    r = await client.post("/api/v2/merchant/mcp", content=b"{malformed", headers=MCP_HEADERS)
    assert r.status_code == 401 and "www-authenticate" in r.headers
    assert spy_parser.call_count == 0


async def test_wrong_protocol_version_rejected(client, token) -> None:
    r = await mcp_call(client, token, "tools/list",
                       headers={"MCP-Protocol-Version": "2025-06-18"})
    assert r.status_code == 400


async def test_legacy_initialize_handshake_rejected(client, token) -> None:
    """契约：不实现旧版 initialize。SDK 默认旧协议时这条会暴露问题。"""
    r = await mcp_call(client, token, "initialize")
    assert "error" in r.json()


async def test_mcp_session_id_never_issued(client, token) -> None:
    r = await mcp_call(client, token, "tools/list")
    assert "mcp-session-id" not in {k.lower() for k in r.headers}


async def test_header_body_method_mismatch_rejected(client, token) -> None:
    r = await mcp_call(client, token, body_method="tools/call",
                       headers={"Mcp-Method": "tools/list"})
    assert "error" in r.json()


async def test_tool_errors_are_json_rpc_errors(client, token) -> None:
    body = (await mcp_call(client, token, "tools/call", name="query_metrics",
                           arguments={"metric": "not_a_metric"})).json()
    assert body["jsonrpc"] == "2.0" and "error" in body
    assert "request_id" not in body                  # 不是 v2 ErrorResponse
```

- [ ] **步骤 2：确认失败 → 实现 → 确认通过**

契约计划明确：**若 SDK 仍默认旧协议，必须显式配置版本**，并保留第三条反例测试。

---

### Task 3：工具面投影

- `tools/list` 只返回 `registry.surface_for_mcp()` 与凭证 `scopes` 的**交集**；
- `merchant_id` 从凭证解析并注入，**与商家会话走同一个注入路径**（§6.9）；
- 工具输出的 `ToolDisplay` 与 `payload` 按 MCP 格式返回，
  **审批证据、确认令牌、完整明细行一律不出现**。

- [ ] **步骤 1：写失败测试**

```python
async def test_tools_list_is_intersection_of_whitelist_and_scopes(client) -> None:
    token = await issue(merchant=M, scopes={"query_metrics"})
    names = {t["name"] for t in (await mcp_call(client, token, "tools/list")).json()["result"]["tools"]}
    assert names == {"query_metrics"}


async def test_no_write_tool_reachable_even_if_named(client, token) -> None:
    body = (await mcp_call(client, token, "tools/call", name="draft_restock",
                           arguments={})).json()
    assert "error" in body


async def test_cross_merchant_data_unreachable(client) -> None:
    token = await issue(merchant=M_A, scopes={"query_metrics"})
    body = (await mcp_call(client, token, "tools/call", name="query_metrics",
                           arguments={"metric": "gross_gmv"})).json()
    assert body["result"]["merchant_scope"] == str(M_A)
```

- [ ] **步骤 2：确认失败 → 实现 → 确认通过**

---

### Task 4：标准客户端集成测试与 S8

契约计划要求：**必须用标准 MCP 客户端做无 LLM 集成测试**。

- [ ] **步骤 1：用官方 MCP 客户端库，显式指定协议版本 `2026-07-28`，连接本地 backend**
- [ ] **步骤 2：S8 场景**

```text
脚本签发 24 小时、限 query_metrics 的凭证
→ 标准客户端 tools/list → tools/call query_metrics(gross_gmv, 近 7 天)
→ 同一时刻商家工作台调用同一指标
→ 两者数值、数据截至时间、指标定义版本逐项一致
→ 撤销凭证 → 客户端下一次调用收到 401
```

"逐项一致"是因为两者走**同一个工具、同一个服务**——若不一致，说明 MCP 路径绕开了注册表，
那才是要修的问题。

- [ ] **步骤 3：把 S8 登记进 `app/eval/datasets/security/`**——撤销后仍可调用即为安全门禁失败

---

### Task 5：自检

```powershell
cd backend
rg -n "X-Session-Id|x_session_id" app/mcp/
rg -n "Mcp-Session-Id" app/mcp/ --glob '!*test*'
rg -n "WritePolicy.MERCHANT_DRAFT|CUSTOMER_" app/mcp/
uv run pytest tests/integration/mcp/ -v
uv run pytest; uv run ruff check .; uv run mypy app
```

前三条期望零命中（第二条允许出现在"拒绝该头"的校验代码里，逐条确认）。

更新 `docs/project-progress.md`：S8 状态、协议版本与 SDK 配置方式、未执行 Git。

---

## 本计划明确不做的事

| 不做 | 归属 |
| --- | --- |
| MCP 写工具 | 不做（A8：只读子集） |
| 顾客侧 MCP | 不做（A8 只定义商家只读子集） |
| 商家自助凭证管理页、凭证 HTTP 路径 | 不做（PRD A8，2026-09-21 用户裁定） |
| 完整 OAuth 授权流程 | "正式兼容外部客户端时按 MCP 授权规范实现"（A8），本版为演示级短期凭证 |
