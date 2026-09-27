"""N2 模块 D Task 1：双端会话目录的存储前置。

三处缺口，都是目录路由落地才暴露的：

- `conversations.surface`：标出由 v2 顾客 / 商家 Chat 创建的对话。v1 对话与 v2 商家对话同样
  `owner_kind IS NULL`，不打标记就分不开；而 v1 历史回答是 v1 结构，拼不出 v2 详情要求的
  完整 `MerchantChatResponse`。历史行保持 NULL，不进入 v2 目录。
- `conversations.deleted_at`：目录删除是软删除；删除后对外统一 403，也不能再被续写。
- `messages.response_payload`：v2 助手消息的完整最终响应。契约要求详情里每条助手消息都
  携带与 Chat 响应逐字段相同的 `answer`，只存正文拼不回来。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260923_0033"
down_revision: str | Sequence[str] | None = "20260923_0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("conversations", sa.Column("surface", sa.String(16), nullable=True))
    op.add_column(
        "conversations", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_check_constraint(
        "ck_conversations_surface",
        "conversations",
        "surface IS NULL OR surface IN ('SHOP','MERCHANT')",
    )
    op.create_index(
        "ix_conversations_directory",
        "conversations",
        ["merchant_id", "surface", "owner_kind", "owner_id"],
        postgresql_where=sa.text("surface IS NOT NULL AND deleted_at IS NULL"),
    )
    op.add_column(
        "messages",
        sa.Column("response_payload", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("messages", "response_payload")
    op.drop_index("ix_conversations_directory", "conversations")
    op.drop_constraint("ck_conversations_surface", "conversations", type_="check")
    op.drop_column("conversations", "deleted_at")
    op.drop_column("conversations", "surface")
