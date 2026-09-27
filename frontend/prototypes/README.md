# 前端原型

本目录只放独立的学习 / 设计原型，不属于 Borough 生产功能，不放入 `public/` 或生产入口。

| 文件 | 用途 |
| --- | --- |
| `borough-dual-agent-prototype.html` | Borough 在 Anthropic commerce-agents 蓝图上融合后的双端 Agent 设想：顾客商城 + 商家工作台 + 双端全景 |
| `commerce-agents-sandbox.html` | 外部参考项目（Anthropic / Shopify）的交互沙盘 |

## Borough 双端 Agent 原型

双击 `borough-dual-agent-prototype.html` 打开，无需依赖、后端或外部字体；刷新即重置。

- **顾客商城**：顾客 Agent 做推荐、加购、结账交接、查物流、起草退货申请（须顾客在页面确认）、记住偏好。
- **商家工作台**：商家 Agent 做每日简报、GMV 归因（结构化查询意图 → 模板 SQL）、明细导出、规则问答，
  以及商品内容、优惠券、工单回复三类暂存改动（须商家审批）。
- **双端联动**：顾客侧产生的「商品信息缺口」「退货申请」会作为脱敏信号进入商家简报；商家批准的改动
  （补全保质期、上线优惠券、同意退货）会回到顾客侧。
- **双端全景**：平台内核、数据层、从蓝图带过来的部分（原样 / 适配 / 新增 / 不引入），以及待确认的决策清单。

页面顶部虚线标签是**尚未裁定的假设**（模型、R4、融合方式、顾客身份），原型按推荐答案搭建，
不代表已定方案。商品、价格、经营数字均为示意。

---

# 外部 Commerce Agents 交互沙盘

双击 `commerce-agents-sandbox.html`，用浏览器打开即可。无需安装依赖或启动后端。
沿用 Claude Code 原沙盘的布局和零售流程，补充交互；原始文件和 Claude 在线 Artifact 没有被覆盖。

## 使用方式

1. 顶部选择 Anthropic 或 Shopify，再选择顾客/商家界面。
2. 左侧「场景目录」选择流程，右侧查看对话；事件页展示模拟事件。
3. 商家草稿可以批准或丢弃，修改预算可以体验护栏拦截。
4. 购物车可以增减数量、移除商品；Shopify 订单需要模拟完成结账并打开凭据和权限开关。
5. 旅行可选择日期与晚数，电信可选择套餐与线路，票务可体验保留、过期、候补与转赠。
6. 页面底部可查看覆盖说明、重置沙盘。刷新也会重置所有数据。

## 范围

这是独立的前端学习原型，不属于 Borough 生产功能，未放入 `public/` 或生产入口。
使用本地状态与预设脚本，无模型、Shopify、UCP、支付或调度服务调用，也不加载外部字体。
新增场景的数字均为示意；上游没有界面的 Shopify 商家端使用自绘界面。

事件外层字段修正了工具名、调用 ID、状态与 UI component 名；卡片 payload 仍然是缩减示意，
不能作为上游完整 API 契约。旅行、电信、票务覆盖代表流程，未宣称实现全部上游能力。
部署、MCP、提示缓存、历史压缩、评测和脚手架不做伪后端，仅标注为源码阅读方向。

Shopify 的促销与活动批准后仅记录决策，不创建实际折扣或投放广告，与固定版本的
`merchant/api/staging.py` 中 `_LEDGER_ONLY` 行为一致。

上游固定版本：

- [Anthropic Commerce Agents](https://github.com/anthropics/commerce-agents/tree/fd4d59224ab96b43c6dc6888207c67b3bd5a24cf)
- [Shopify Commerce Examples](https://github.com/Shopify/claude-for-commerce-examples/tree/d68c7fa24f26ab138d8b4ccdd0488db140a6bfe6)

## 验证

已安装前端开发依赖时，从仓库根目录运行：

```powershell
node frontend/scripts/check-commerce-sandbox.mjs
```

检查全部界面与预设场景、事件字段、预算拦截、草稿审批、购物车编辑、订单关联和行业状态转换。
这是离线 DOM 测试，不调用模型或后端，不替代真实浏览器的视觉验收。
