"""容器启动入口：优雅关闭窗口与单 worker 决策。"""

from __future__ import annotations

import pytest
import uvicorn

from app.run import GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS, main


def test_main_configures_graceful_shutdown_and_stays_single_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_run(app: str, **kwargs: object) -> None:
        captured["app"] = app
        captured.update(kwargs)

    monkeypatch.setattr(uvicorn, "run", fake_run)
    monkeypatch.delenv("PORT", raising=False)

    main()

    assert captured["app"] == "app.main:create_app"
    assert captured["timeout_graceful_shutdown"] == GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS
    assert "workers" not in captured
