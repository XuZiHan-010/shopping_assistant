"""生产部署前置条件：FastAPI 应用永远不以 debug=True 构造。"""

from __future__ import annotations

from app.core.config import AppEnvironment, Settings
from app.main import create_app


def test_create_app_never_enables_debug_mode() -> None:
    for env in (AppEnvironment.DEVELOPMENT, AppEnvironment.TEST, AppEnvironment.PRODUCTION):
        settings = Settings(
            app_env=env,
            database_url="postgresql+psycopg://user:pass@localhost/test",
            frontend_origin="http://localhost:5173",
            export_signing_secret=(
                "a-genuinely-long-random-signing-secret-value"
                if env is AppEnvironment.PRODUCTION
                else None
            ),
        )
        app = create_app(settings)

        assert app.debug is False
