"""N3 C：export_files.answer_id 改为可空，支持工具循环内创建导出。

v1 的导出总是由已完成的 Chat 回答触发（`ExportInfo` 随 `ChatResponse` 一起返回），
`answer_id` 此前必填。v2 的 `create_export` 工具在工具循环**执行期间**创建导出记录，
此时本轮的 `Answer` 行尚未落库（`services/v2/merchant_chat.py` 在循环结束后才写
`Answer`），继续要求 `answer_id` 非空会导致外键约束失败。放宽为可空后：

- v1 路径不受影响，继续总是传入真实 `answer_id`；
- v2 `create_export` 传入 `answer_id=None`：访问控制完全由 `merchant_id` 承担，
  `answer_id` 只是 v1 遗留的溯源字段，v2 路径没有它一样安全。

降级时必须先处理已存在的 `NULL` 行（v2 上线后产生的导出记录），否则
`ALTER COLUMN ... SET NOT NULL` 会因为这些行直接失败——降级把它们的 `answer_id`
清空关联外键前先各自新建一条最小占位 `Answer` 行并指过去，保留数据可回退，
而不是删除这些导出记录（降级不应该销毁数据）。
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260925_0036"
down_revision: str | Sequence[str] | None = "20260925_0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("export_files", "answer_id", nullable=True)


def downgrade() -> None:
    connection = op.get_bind()
    # 为每一行 answer_id 为空的导出记录新建一条最小占位 Answer（关联同一 merchant_id、
    # 同一 conversation 的第一条会话；找不到会话时新建一条空对话），使降级后的
    # NOT NULL 约束能够满足，且不删除任何既有导出记录。
    orphans = connection.exec_driver_sql(
        "SELECT id, merchant_id FROM export_files WHERE answer_id IS NULL"
    ).fetchall()
    for export_id, merchant_id in orphans:
        conversation_id = connection.exec_driver_sql(
            "SELECT id FROM conversations WHERE merchant_id = %(merchant_id)s LIMIT 1",
            {"merchant_id": merchant_id},
        ).scalar()
        if conversation_id is None:
            conversation_id = connection.exec_driver_sql(
                "INSERT INTO conversations (id, merchant_id, surface, created_at, updated_at) "
                "VALUES (gen_random_uuid(), %(merchant_id)s, 'MERCHANT', now(), now()) "
                "RETURNING id",
                {"merchant_id": merchant_id},
            ).scalar()
        placeholder_answer_id = connection.exec_driver_sql(
            "INSERT INTO answers (id, merchant_id, conversation_id, client_request_id, "
            "request_digest, processing_status, response_payload, elapsed_ms, "
            "response_locale, surface, created_at) "
            "VALUES (gen_random_uuid(), %(merchant_id)s, %(conversation_id)s, "
            "%(client_request_id)s, %(client_request_id)s, 'SUCCEEDED', '{}'::jsonb, 0, "
            "'zh-CN', 'MERCHANT', now()) RETURNING id",
            {
                "merchant_id": merchant_id,
                "conversation_id": conversation_id,
                "client_request_id": f"downgrade-placeholder-{export_id}",
            },
        ).scalar()
        connection.exec_driver_sql(
            "UPDATE export_files SET answer_id = %(answer_id)s WHERE id = %(export_id)s",
            {"answer_id": placeholder_answer_id, "export_id": export_id},
        )
    op.alter_column("export_files", "answer_id", nullable=False)
