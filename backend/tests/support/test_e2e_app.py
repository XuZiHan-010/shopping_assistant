from __future__ import annotations

import importlib
import sys

from pytest import MonkeyPatch


def test_f4_e2e_assembly_overrides_chat_with_deterministic_b7_service(
    monkeypatch: MonkeyPatch,
) -> None:
    """浏览器验收运行时必须用确定性入口替换默认聊天服务。"""

    monkeypatch.setenv(
        "F4_E2E_DATABASE_URL",
        "postgresql+psycopg://borough:borough_local@127.0.0.1:55443/borough_f4_test",
    )
    sys.modules.pop("tests.support.e2e_app", None)
    e2e_app = importlib.import_module("tests.support.e2e_app")
    app = e2e_app.build_e2e_app(
        "postgresql+psycopg://borough:borough_local@127.0.0.1:55443/borough_f4_test"
    )

    assert app.dependency_overrides[e2e_app.get_chat_service] is e2e_app.get_e2e_chat_service
