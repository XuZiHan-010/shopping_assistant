"""三级 LLM 预算的级别定义（N5 B，PRD §10.2、Q37）。

独立成模块是为了让守卫（`app.llm.guard`）与仓储（`app.repositories.llm_budget`）
共用同一份定义而不互相导入。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final
from uuid import UUID

from app.core.config import Settings
from app.core.session import SessionRole

GLOBAL_SCOPE: Final = "GLOBAL"


@dataclass(frozen=True)
class BudgetScope:
    """一级预算：`key` 决定在 `llm_daily_budget` 里记到哪一行，`budget` 是该级当日上限。"""

    key: str
    budget: int


def budget_scopes(
    settings: Settings, role: SessionRole | None, merchant_id: UUID | None
) -> tuple[BudgetScope, ...]:
    """一次调用要同时扣减的各级预算（PRD §10.2）。

    - 全局：所有调用都扣；
    - 角色：顾客 / 商家各一池；
    - 店铺：按「角色 + 店铺」计——一家店耗尽不影响另一家，
      同一家店的顾客流量也不会挤掉它自己的工作台。
    没有角色的调用（管理员后台的全局本地化等）只扣全局。
    """

    scopes = [BudgetScope(GLOBAL_SCOPE, settings.llm_daily_budget_tokens)]
    if role is SessionRole.CUSTOMER:
        scopes.append(BudgetScope("ROLE:CUSTOMER", settings.llm_customer_daily_budget_tokens))
    elif role is SessionRole.MERCHANT:
        scopes.append(BudgetScope("ROLE:MERCHANT", settings.llm_merchant_daily_budget_tokens))
    if role is not None and merchant_id is not None:
        scopes.append(
            BudgetScope(f"SHOP:{role.value}:{merchant_id}", settings.llm_shop_daily_budget_tokens)
        )
    return tuple(scopes)
