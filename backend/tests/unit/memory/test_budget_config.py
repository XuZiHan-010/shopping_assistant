"""记忆抽取使用独立于主 Chat 的单任务预算。"""

from app.core.config import Settings


def test_memory_extraction_budget_is_independent_of_main_loop() -> None:
    settings = Settings(
        app_env="test",
        database_url="postgresql+psycopg://borough:borough_local@127.0.0.1:55432/borough_test",
        frontend_origin="http://localhost:5173",
    )
    assert settings.memory_extraction_max_calls >= 1
    assert settings.memory_extraction_max_tokens >= 100
    assert settings.memory_extraction_max_calls != settings.agent_loop_max_llm_calls
