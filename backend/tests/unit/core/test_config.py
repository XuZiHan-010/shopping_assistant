from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.core.config import AppEnvironment, Settings


def make_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "database_url": "postgresql+psycopg://user:pass@localhost/db",
        "frontend_origin": "https://merchant.example.com",
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def test_production_disables_demo_merchant_endpoint() -> None:
    settings = make_settings(
        app_env=AppEnvironment.PRODUCTION,
        export_signing_secret="test-export-signing-secret",
        demo_merchant_tokens={"demo-token": UUID("00000000-0000-0000-0000-000000000001")},
        demo_merchants_endpoint_enabled=True,
    )

    assert settings.demo_merchants_endpoint_enabled is False


def test_production_keeps_demo_endpoint_closed_by_default() -> None:
    settings = make_settings(
        app_env=AppEnvironment.PRODUCTION,
        export_signing_secret="a-secure-export-signing-secret",
        demo_merchants_endpoint_enabled=True,
    )

    assert settings.demo_merchants_endpoint_enabled is False


def test_production_opens_demo_endpoint_only_with_explicit_deployment_mode() -> None:
    settings = make_settings(
        app_env=AppEnvironment.PRODUCTION,
        export_signing_secret="a-secure-export-signing-secret",
        demo_deployment_mode=True,
    )

    assert settings.demo_deployment_mode is True
    assert settings.demo_merchants_endpoint_enabled is True


def test_demo_deployment_mode_defaults_to_false() -> None:
    settings = make_settings(
        app_env=AppEnvironment.PRODUCTION,
        export_signing_secret="a-secure-export-signing-secret",
    )

    assert settings.demo_deployment_mode is False


def test_production_requires_export_signing_secret() -> None:
    with pytest.raises(ValidationError, match="EXPORT_SIGNING_SECRET"):
        make_settings(app_env=AppEnvironment.PRODUCTION)


def test_cors_origin_must_be_exact() -> None:
    with pytest.raises(ValidationError):
        make_settings(frontend_origin="*")


@pytest.mark.parametrize(
    "origin",
    [
        "https://merchant.example.com/path",
        "https://merchant.example.com?source=test",
        "https://user:pass@merchant.example.com",
    ],
)
def test_cors_origin_rejects_non_origin_url_parts(origin: str) -> None:
    with pytest.raises(ValidationError):
        make_settings(frontend_origin=origin)


def test_railway_postgres_url_uses_psycopg_driver() -> None:
    settings = make_settings(database_url="postgresql://user:pass@localhost/db")

    assert settings.database_url == "postgresql+psycopg://user:pass@localhost/db"


def test_business_timezone_is_fixed() -> None:
    with pytest.raises(ValidationError):
        make_settings(business_timezone="UTC")


def test_max_llm_env_keys_from_the_plan_actually_bind() -> None:
    settings = Settings.model_validate(
        {
            "database_url": "postgresql+psycopg://user:pass@localhost/db",
            "frontend_origin": "https://merchant.example.com",
            "MAX_LLM_CALLS_PER_REQUEST": 7,
            "MAX_LLM_TOKENS_PER_REQUEST": 1234,
        }
    )

    assert settings.llm_max_calls_per_request == 7
    assert settings.llm_max_tokens_per_request == 1234


def test_default_llm_call_cap_covers_the_documented_worst_case() -> None:
    """默认质量循环不能让 10 次请求上限在正常最坏路径上自相矛盾。"""

    settings = make_settings()
    worst_case_calls = 2 + 3 + 1 + (2 * settings.quality_max_attempts)

    assert settings.quality_max_attempts == 2
    assert worst_case_calls == 10
    assert worst_case_calls <= settings.llm_max_calls_per_request


def test_settings_can_still_be_built_by_field_name() -> None:
    settings = make_settings(llm_max_tokens_per_request=1234)

    assert settings.llm_max_tokens_per_request == 1234


def test_production_with_real_llm_key_requires_admin_token() -> None:
    with pytest.raises(ValidationError, match="ADMIN_TOKEN"):
        make_settings(
            app_env=AppEnvironment.PRODUCTION,
            llm_api_key="real-deepseek-key",
            export_signing_secret="a-secure-export-signing-secret",
        )


@pytest.mark.parametrize("secret", ["short", "<development-placeholder>"])
def test_production_rejects_weak_placeholder_secrets(secret: str) -> None:
    with pytest.raises(ValidationError):
        make_settings(
            app_env=AppEnvironment.PRODUCTION,
            llm_api_key="real-deepseek-key",
            admin_token=secret,
            export_signing_secret=secret,
        )


def test_trusted_proxy_ips_parses_comma_separated_env_value() -> None:
    settings = make_settings(trusted_proxy_ips=" 203.0.113.7, 198.51.100.9 ,, ")

    assert settings.trusted_proxy_ip_set == frozenset({"203.0.113.7", "198.51.100.9"})


def test_settings_in_tests_ignore_ambient_dotenv(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """测试构造的 Settings 不得读取运行目录下的 `.env`。

    `Settings.model_config` 声明了 `env_file=(".env", "../.env")`，生产运行时
    需要它；但在测试里它会让结果取决于开发者本机 `.env` 的内容——例如本仓库根
    的 `backend/.env` 有 `LLM_API_KEY` 而无 `ADMIN_TOKEN`，就会让所有构造生产
    Settings 的用例撞上「生产环境配置 LLM_API_KEY 时必须设置 ADMIN_TOKEN」而集体
    失败。这个缺陷此前被「在无 `.env` 的 worktree 里跑回归」掩盖过一次，因此用
    临时目录自造 `.env` 把它钉死，不依赖任何本机文件是否存在。
    """

    (tmp_path / ".env").write_text(
        "LLM_API_KEY=ambient-key-must-not-leak\nLLM_MODEL=ambient-model-must-not-leak\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    settings = make_settings(
        app_env=AppEnvironment.PRODUCTION,
        export_signing_secret="a-secure-export-signing-secret",
    )

    assert settings.llm_api_key is None
    assert settings.llm_model != "ambient-model-must-not-leak"


def test_settings_in_tests_ignore_ambient_environment_variables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """测试构造的 Settings 也不得读取进程环境变量。

    与 dotenv 那条同源：参考项目 `yshopping-merchant-ai 4/` 的测试一律
    `new AppProperties()` 手工赋值，从不走 Spring 的配置解析路径，因此环境变量和
    配置文件都影响不到测试结果。按 R9 以参考项目为基准，我们的测试也必须做到
    「配置只能来自显式传参」——只堵 `.env` 而放行环境变量，等于只还原了一半。
    """

    monkeypatch.setenv("LLM_API_KEY", "ambient-env-key-must-not-leak")
    monkeypatch.setenv("LLM_MODEL", "ambient-env-model-must-not-leak")

    settings = make_settings(
        app_env=AppEnvironment.PRODUCTION,
        export_signing_secret="a-secure-export-signing-secret",
    )

    assert settings.llm_api_key is None
    assert settings.llm_model != "ambient-env-model-must-not-leak"
