"""N4 B：单列记忆抽取的 LLM 用量用途。"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260928_0044"
down_revision: str | Sequence[str] | None = "20260928_0043"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_llm_usage_purpose", "llm_usage", type_="check")
    op.create_check_constraint(
        "ck_llm_usage_purpose", "llm_usage",
        "purpose IN ('AGENT', 'LOCALIZATION', 'MEMORY')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_llm_usage_purpose", "llm_usage", type_="check")
    op.create_check_constraint(
        "ck_llm_usage_purpose", "llm_usage",
        "purpose IN ('AGENT', 'LOCALIZATION')",
    )
