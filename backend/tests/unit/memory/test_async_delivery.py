"""记忆抽取走 outbox，不走进程内后台任务（§6.13，N4-B Task 3）。"""

from __future__ import annotations

from pathlib import Path

APP = Path(__file__).resolve().parents[3] / "app"


def test_no_background_tasks_in_memory_path() -> None:
    """进程重启即丢任务的 `BackgroundTasks` 不是可靠交付：记忆与 v2 服务、路由里不得出现。"""

    roots = [APP / "memory", APP / "services" / "v2", APP / "api" / "routes" / "v2"]
    offenders = [
        str(path.relative_to(APP))
        for root in roots
        for path in root.rglob("*.py")
        if "BackgroundTasks" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []
