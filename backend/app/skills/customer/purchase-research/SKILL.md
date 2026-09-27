---
name: purchase-research
description: 顾客尚未选定商品，询问某类商品怎样挑、哪些属性重要或本店几个候选如何比较时使用。
version: 1
source: vendor/anthropic-commerce-agents@fd4d592 shopping-agent/skills/purchase-research
---

# 本店选购研究

先确认顾客关心的用途和关键限制。通过 `get_shop_policy` 查可引用的本店或平台规则，再用 `search_products`、`get_product` 核对本店商品；只根据查得的事实比较。

- 只比较本店在售商品；不跨店比价，不做站外搜索。
- 属性「缺失」就说明缺失，不能用常识或同类产品推断材质、适龄、安全性等。
- 价格和库存只来自工具；不谈价，只告知已生效且可核实的优惠券。
- 涉及医疗、用药、法律、金融的问题，只说明已查到的商品信息并建议咨询专业人士，不作专业结论。
- 给出选择标准、各候选的已知差异和无法核实的点。不要把缺资料说成商品不具备该属性。
