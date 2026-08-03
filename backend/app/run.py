"""容器和本地开发启动入口。"""

from __future__ import annotations

import os

import uvicorn

from app.core.runtime import loop_factory


def main() -> None:
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(
        "app.main:create_app",
        factory=True,
        host="0.0.0.0",
        port=port,
        proxy_headers=False,
        # uvicorn 不看全局事件循环策略，必须显式传工厂，
        # 否则 Windows 上会拿到 ProactorEventLoop 而连不上数据库。
        loop=loop_factory(),
    )


if __name__ == "__main__":
    main()
