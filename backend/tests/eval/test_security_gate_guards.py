"""门禁反向验证：可运行对象而非阶段标签决定能否登记。"""

import pytest
from fastapi import FastAPI

from app.eval.cases import EvalCase
from tests.eval import test_security_gate as gate


def endpoint_case(milestone: str, path: str = "/api/v2/merchant/probe") -> EvalCase:
    return EvalCase.model_validate(
        {
            "id": "SEC-CROSS-PROBE",
            "introduced_in": milestone,
            "role": "MERCHANT",
            "skill": "probe",
            "risk": "SECURITY",
            "locale": "en-US",
            "turns": [{"actor": "merchant_a", "request": {"method": "GET", "path": path}}],
            "assertions": [{"type": "http_status", "expected": 403}],
        }
    )


def install_cases(monkeypatch: pytest.MonkeyPatch, cases: list[EvalCase]) -> None:
    app = FastAPI()

    @app.get("/api/v2/merchant/probe")
    async def probe() -> None:
        pass

    monkeypatch.setattr(gate, "create_app", lambda _settings: app)
    monkeypatch.setattr(gate, "load_security_cases", lambda: cases)


def test_registered_future_endpoint_is_allowed_without_advancing_milestone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_cases(monkeypatch, [endpoint_case("N2")])
    monkeypatch.setattr(gate, "CURRENT_MILESTONE", "N1")
    gate.test_case_targets_are_implemented()


@pytest.mark.parametrize("milestone", ["N1", "N2"])
def test_unimplemented_endpoint_is_rejected(
    monkeypatch: pytest.MonkeyPatch, milestone: str
) -> None:
    install_cases(monkeypatch, [endpoint_case(milestone, "/api/v2/not_implemented")])
    with pytest.raises(AssertionError):
        gate.test_case_targets_are_implemented()


def test_future_cases_cannot_fill_due_category_quota(monkeypatch: pytest.MonkeyPatch) -> None:
    cases = [endpoint_case("N1"), endpoint_case("N1"), endpoint_case("N2")]
    install_cases(monkeypatch, cases)
    monkeypatch.setattr(gate, "CURRENT_MILESTONE", "N1")
    monkeypatch.setattr(gate, "CATEGORY_INTRODUCED_IN", {"CROSS": "N1"})
    with pytest.raises(AssertionError):
        gate.test_due_categories_have_at_least_three_cases()


@pytest.mark.parametrize("mutation", ["method", "setup", "primitive"])
def test_every_turn_target_must_exist(monkeypatch: pytest.MonkeyPatch, mutation: str) -> None:
    data = endpoint_case("N1").model_dump()
    if mutation == "method":
        data["turns"][0]["request"]["method"] = "POST"
    elif mutation == "setup":
        data["turns"].insert(
            0,
            {
                "actor": "merchant_a",
                "request": {
                    "method": "GET",
                    "path": "/not-implemented-v1",
                },
            },
        )
    else:
        data["turns"].insert(0, {"actor": "merchant_a", "primitive": {"name": "missing.primitive"}})
    install_cases(monkeypatch, [EvalCase.model_validate(data)])
    with pytest.raises(AssertionError):
        gate.test_case_targets_are_implemented()


def test_primitive_locale_labels_cannot_fill_http_coverage(monkeypatch: pytest.MonkeyPatch) -> None:
    cases = [
        endpoint_case("N1").model_copy(update={"role": role, "locale": locale})
        for role in ("CUSTOMER", "MERCHANT")
        for locale in ("zh-CN", "en-US")
    ]
    cases[-1] = cases[-1].model_copy(update={"form": "PRIMITIVE"})
    install_cases(monkeypatch, cases)
    with pytest.raises((AssertionError, ValueError)):
        gate.test_dataset_layer_coverage()


def test_setup_http_cannot_replace_final_endpoint_attack(monkeypatch: pytest.MonkeyPatch) -> None:
    data = endpoint_case("N1").model_dump()
    data["turns"].append(
        {
            "actor": "merchant_a",
            "primitive": {
                "name": "safe_query.reject_dimension_injection",
            },
        }
    )
    install_cases(monkeypatch, [EvalCase.model_validate(data)])
    with pytest.raises(AssertionError):
        gate.test_case_targets_are_implemented()
    with pytest.raises(AssertionError):
        gate.test_every_v2_route_has_an_endpoint_security_case()


def test_registered_route_without_case_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    install_cases(monkeypatch, [])
    with pytest.raises(AssertionError):
        gate.test_every_v2_route_has_an_endpoint_security_case()


def test_n2_acceptance_still_requires_n2_categories(monkeypatch: pytest.MonkeyPatch) -> None:
    install_cases(monkeypatch, [endpoint_case("N1")])
    monkeypatch.setattr(gate, "CURRENT_MILESTONE", "N2")
    monkeypatch.setattr(gate, "CATEGORY_INTRODUCED_IN", {"INJECTION": "N2"})
    with pytest.raises(AssertionError, match="INJECTION"):
        gate.test_due_categories_have_at_least_three_cases()
