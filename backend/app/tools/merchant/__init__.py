"""商家工具面（PRD M3、M5、M10）。

写策略是这个模块的全部要点：

- `get_inventory_alerts`、`query_metrics`、`attribute_change`：`READ_ONLY`，可并行；
- `draft_restock`：`MERCHANT_DRAFT`，**在类型层面**只能返回 `DraftProposal`——
  它写不出「直接改库存」这条路径（注册表自检 `_RETURN_TYPE`）。

没有「应用草稿」或「批准草稿」的工具：批准只能来自审批界面（D9①、§8.13.2 不变量 6），
Agent 连证据都拿不到。
"""

from __future__ import annotations

from app.db.session import Database
from app.repositories.audit import AuditRepository
from app.services.v2.inventory_alerts import AlertRules
from app.tools.merchant.after_sale import build_after_sale_tools
from app.tools.merchant.content import build_content_tools
from app.tools.merchant.definitions import build_definitions_tools
from app.tools.merchant.export import build_export_tools
from app.tools.merchant.inventory import build_inventory_tools
from app.tools.merchant.metrics import build_metrics_tools
from app.tools.merchant.pricing import build_pricing_tools
from app.tools.merchant.signals import build_signal_tools
from app.tools.types import ToolSpec


def build_merchant_tools(
    database: Database,
    *,
    rules: AlertRules | None = None,
    business_timezone: str = "Asia/Shanghai",
    alias_secret: bytes = b"development-buyer-alias-secret",
    export_signing_secret: str | None = None,
    export_url_ttl_minutes: int = 15,
) -> tuple[ToolSpec, ...]:
    """商家工具面的装配点；`build_tool_registry()` 在进程启动时调用它。"""

    return (
        build_inventory_tools(database, rules=rules or AlertRules())
        + build_metrics_tools(database, business_timezone=business_timezone)
        + build_after_sale_tools(database, alias_secret=alias_secret)
        + build_signal_tools(database)
        + build_pricing_tools(database)
        + build_export_tools(
            database,
            AuditRepository(database),
            signing_secret=export_signing_secret,
            export_url_ttl_minutes=export_url_ttl_minutes,
        )
        + build_definitions_tools(database)
        + build_content_tools(database)
    )


__all__ = ["build_merchant_tools"]
