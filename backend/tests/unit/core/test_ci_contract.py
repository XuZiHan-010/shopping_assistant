"""CI 必须实际接线安全门禁，且永不注入真实模型凭证。"""

from pathlib import Path

import yaml

WORKFLOW = Path(__file__).resolve().parents[4] / ".github/workflows/n1-checks.yml"


def test_ci_requires_database_and_executes_security_and_timing_gates():
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert workflow["permissions"] == {"contents": "read"}
    jobs = workflow["jobs"]
    for name in ("backend", "security-timing"):
        job = jobs[name]
        assert job["env"]["REQUIRE_INTEGRATION_DB"] == "1"
        assert job["env"]["LLM_API_KEY"] == ""
        assert job["env"]["TEST_DATABASE_URL"].endswith("/borough_test")
        assert "postgres" in job["services"]
        assert not job.get("continue-on-error", False)
        for step in job["steps"]:
            assert not step.get("continue-on-error", False)
    backend_runs = [step["run"] for step in jobs["backend"]["steps"] if "run" in step]
    assert "uv run --frozen pytest tests/eval/test_security_gate.py -q" in backend_runs
    assert 'uv run --frozen pytest -m "not security_timing" -q' in backend_runs
    timing = jobs["security-timing"]
    assert timing["env"]["REQUIRE_SECURITY_TIMING"] == "1"
    assert any(
        step.get("run") == "uv run --frozen pytest -m security_timing -q"
        for step in timing["steps"]
    )


def test_ci_has_no_paid_smoke_or_secret_injection():
    source = WORKFLOW.read_text(encoding="utf-8")
    assert "secrets." not in source
    assert "llm_smoke" not in source
    assert "eval_quality_smoke" not in source
    workflow = yaml.safe_load(source)
    frontend_runs = {step["run"] for step in workflow["jobs"]["frontend"]["steps"] if "run" in step}
    assert "npm run codegen:check" in frontend_runs
    assert "npm run test -- src/api/adapters/session.spec.ts" in frontend_runs
