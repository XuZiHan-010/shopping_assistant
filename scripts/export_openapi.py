"""从 FastAPI 应用导出 OpenAPI，禁止手写 docs/api.md。

产出两份，同源同时写：

- `docs/api.json`：机器可读，前端 `openapi-typescript` 直接消费（见
  `docs/frontend-development-plan.md` F0）。JSON 不能包在 markdown 代码块里，
  否则代码生成工具解析不了。
- `docs/api.md`：人读版，把同一份 JSON 包进代码块，方便在文档里翻阅和 diff。

两份是否与当前应用一致由 `backend/tests/api/test_openapi_chat_contract.py`
把关，避免改了 Schema 忘记重新导出。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.core.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402

GENERATED_NOTICE = "> 本文件由 `scripts/export_openapi.py` 生成，请勿手改；改契约请改 Pydantic Schema 后重新导出。"


def export_settings() -> Settings:
    """导出用的固定配置，保证同一份代码在任何机器上导出结果一致。"""

    return Settings(
        app_env="test",
        database_url="postgresql+psycopg://user:pass@localhost/test",
        frontend_origin="http://localhost:5173",
    )


def render_openapi_json(schema: dict[str, object]) -> str:
    return json.dumps(schema, ensure_ascii=False, indent=2) + "\n"


def render_openapi_markdown(schema: dict[str, object]) -> str:
    payload = json.dumps(schema, ensure_ascii=False, indent=2)
    return f"# OpenAPI\n\n{GENERATED_NOTICE}\n\n```json\n{payload}\n```\n"


def main() -> None:
    schema = create_app(export_settings()).openapi()
    docs = ROOT / "docs"
    (docs / "api.json").write_text(render_openapi_json(schema), encoding="utf-8")
    (docs / "api.md").write_text(render_openapi_markdown(schema), encoding="utf-8")


if __name__ == "__main__":
    main()
