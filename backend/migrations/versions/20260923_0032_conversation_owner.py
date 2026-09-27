"""N2 模块 B Task 6：对话归属到登录主体（顾客导购 Chat 上线的前置）。

v1 `conversations` 只按 `merchant_id` 隔离，这对商家够用，对顾客不够：同店两位顾客共用
`merchant_id`，拿到别人的 `conversation_id` 就能往别人的对话里续写。

`owner_kind / owner_id` 与 `conversation_provenance` 同一套主体口径：
访客存内部会话记录 ID（`GUEST_SESSION`），已绑定顾客存稳定主体摘要（`BOUND_PRINCIPAL`），
都不是明文凭证或原始 `buyer_key`。商家对话与历史行两列为空。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260923_0032"
down_revision: str | Sequence[str] | None = "20260923_0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("conversations", sa.Column("owner_kind", sa.String(16), nullable=True))
    op.add_column("conversations", sa.Column("owner_id", sa.String(64), nullable=True))
    op.create_check_constraint(
        "ck_conversations_owner_pair",
        "conversations",
        "(owner_kind IS NULL) = (owner_id IS NULL)",
    )
    op.create_check_constraint(
        "ck_conversations_owner_kind",
        "conversations",
        "owner_kind IS NULL OR owner_kind IN ('GUEST_SESSION','BOUND_PRINCIPAL')",
    )
    op.create_index(
        "ix_conversations_merchant_owner",
        "conversations",
        ["merchant_id", "owner_kind", "owner_id"],
        postgresql_where=sa.text("owner_kind IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_conversations_merchant_owner", "conversations")
    op.drop_constraint("ck_conversations_owner_kind", "conversations", type_="check")
    op.drop_constraint("ck_conversations_owner_pair", "conversations", type_="check")
    op.drop_column("conversations", "owner_id")
    op.drop_column("conversations", "owner_kind")
