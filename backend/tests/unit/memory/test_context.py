"""有界上下文：目录可发现旧类别、正文去重、超长条目不拆分。"""

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4


def test_directory_does_not_load_old_memory_body() -> None:
    from app.memory.context import build_context

    recent = SimpleNamespace(
        id=uuid4(),
        category="color",
        key="color",
        value="blue",
        last_confirmed_at=datetime(2026, 10, 13, tzinfo=UTC),
    )
    text, ids = build_context(
        [recent], [{"category": "fit"}, {"category": "color"}], source="customer_memory"
    )
    assert '"fit"' in text and "blue" in text
    assert "2026-10-13" in text
    assert ids == (str(recent.id),)


def test_budget_discards_complete_items_and_reports_truncation() -> None:
    from app.memory.context import build_context

    long = SimpleNamespace(
        id=uuid4(),
        category="tone",
        key="tone",
        value="x" * 5000,
        last_confirmed_at=datetime(2026, 10, 13, tzinfo=UTC),
    )
    small = SimpleNamespace(
        id=uuid4(),
        category="color",
        key="color",
        value="blue",
        last_confirmed_at=datetime(2026, 10, 13, tzinfo=UTC),
    )
    text, ids = build_context([long, small], [{"category": "color"}], source="customer_memory")
    assert len(text) <= 4000
    assert "blue" in text and "xxxx" not in text
    assert '"truncated": true' in text
    assert ids == (str(small.id),)


def test_same_memory_id_is_only_loaded_once() -> None:
    from app.memory.context import build_context

    row = SimpleNamespace(
        id=uuid4(),
        category="color",
        key="color",
        value="blue",
        last_confirmed_at=datetime(2026, 10, 13, tzinfo=UTC),
    )
    text, ids = build_context([row, row], [], source="customer_memory")
    assert text.count('"blue"') == 1 and ids == (str(row.id),)


def test_merchant_context_does_not_repeat_summary_body() -> None:
    from app.memory.context import build_context

    row = SimpleNamespace(
        id=uuid4(),
        category="presentation",
        key="tone",
        content="语气正式",
        created_at=datetime(2026, 10, 13, tzinfo=UTC),
    )
    text, ids = build_context([row], [{"category": "presentation"}], source="merchant_memory")
    assert text.count("语气正式") == 1
    assert "last_confirmed_at" in text and ids == (str(row.id),)
