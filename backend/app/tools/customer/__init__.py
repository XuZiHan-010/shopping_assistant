"""顾客工具面（PRD C2，交易计划 Task 6）。

顾客导购与售后工具按写策略分三类：

- `search_products` / `get_product` / `get_shop_policy`：`READ_ONLY`，可并行；
- `set_cart_item`：`CUSTOMER_DIRECT`，设置绝对数量，天然幂等。
- `check_after_sale_eligibility`：`READ_ONLY`；`prepare_after_sale`：
  `CUSTOMER_CONFIRMATION`，只产出预览，界面另行确认。

没有下单、支付或取消工具——它们只走带 `client_request_id` 的界面路由，
模型连这个能力都拿不到（注册表对顾客写工具的名称自检兜底）。
"""

from __future__ import annotations

from app.db.session import Database
from app.tools.customer.after_sale import build_after_sale_tools
from app.tools.customer.cart import build_cart_tools
from app.tools.customer.catalog import build_catalog_tools
from app.tools.types import ToolSpec


def build_customer_tools(database: Database) -> tuple[ToolSpec, ...]:
    """顾客工具面的装配点；`build_tool_registry()` 在进程启动时调用它。"""

    return (
        *build_catalog_tools(database),
        *build_cart_tools(database),
        *build_after_sale_tools(database),
    )


__all__ = ["build_customer_tools"]
