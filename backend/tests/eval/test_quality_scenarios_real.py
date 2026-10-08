"""v2 质量场景真实复测入口：范围与交给裁判的对话记录。全部零费用。"""

from __future__ import annotations

from app.eval.quality_scenarios_real import SCENARIO_RUBRIC, scenario_cases, scenario_transcript


def test_scope_is_the_19_v2_cases_without_the_frozen_baseline_ones() -> None:
    cases = scenario_cases()

    assert len(cases) == 19
    assert not [case.id for case in cases if case.introduced_in == "N1"]
    assert {case.id for case in cases} >= {"QLT-S1-001", "QLT-S4-001", "QLT-S7-002", "QLT-N5-008"}


def _case(case_id: str):  # type: ignore[no-untyped-def]
    return next(case for case in scenario_cases() if case.id == case_id)


def test_judge_sees_real_tool_calls_so_a_claimed_action_can_be_checked() -> None:
    """2026-10-06：回答只请商家给补货数量、并未起草草稿，却因裁判看不到工具调用被判通过。"""

    body = {
        "answer": "已为你起草补货草稿，请到审批页确认。",
        "tool_calls": [
            {"tool_name": "get_inventory_alerts", "status": "SUCCEEDED"},
            {"tool_name": "draft_restock", "status": "FAILED"},
        ],
    }

    assert scenario_transcript(_case("QLT-S3-001"), body) == (
        "[身份 商家]\n[显示语言 zh-CN]\n"
        "[本回合工具调用 get_inventory_alerts(SUCCEEDED), draft_restock(FAILED)]\n"
        "用户：店里有没有库存偏低的商品？如果有的话帮我起草一份补货草稿。\n"
        "助手：已为你起草补货草稿，请到审批页确认。"
    )


def test_guest_and_bound_customer_are_told_apart_for_the_judge() -> None:
    """访客问本人订单或要求记住偏好时应被引导先绑定；裁判得知道对方是不是访客。"""

    guest = scenario_transcript(_case("QLT-N5-005"), {"answer": "好的", "tool_calls": []})
    bound = scenario_transcript(_case("QLT-S1-001"), {"answer": "好的", "tool_calls": []})

    assert guest.startswith("[身份 访客]\n[显示语言 zh-CN]\n[本回合工具调用 无]\n")
    assert bound.startswith("[身份 已绑定演示顾客]\n")


def test_failed_request_still_yields_a_transcript_with_an_empty_answer() -> None:
    assert scenario_transcript(_case("QLT-S4-001"), {"code": "LLM_UNAVAILABLE"}).endswith("助手：")


def test_language_is_checked_by_code_not_by_the_judge() -> None:
    assert "language" not in [criterion.key for criterion in SCENARIO_RUBRIC.criteria]


def test_guest_binding_is_only_judged_for_guest_cases() -> None:
    """裁判对商家身份的用例两次把「访客绑定」判成不通过，理由里却写着「不适用，应判通过」。

    适用与否由用例身份决定，不交给裁判自己判断。
    """

    from app.eval.quality_scenarios_real import rubric_for

    def keys(case_id: str) -> list[str]:
        return [criterion.key for criterion in rubric_for(_case(case_id)).criteria]

    assert "guest_binding" not in keys("QLT-S3-002")  # 商家
    assert "guest_binding" not in keys("QLT-S1-001")  # 已绑定顾客
    assert "guest_binding" in keys("QLT-N5-005")  # 访客
    assert keys("QLT-S3-002") == ["responsive", "audience_facing", "action_honest"]


def test_rule_source_is_only_judged_when_the_user_asks_for_a_citation() -> None:
    """同样的毛病：用户没要求出处时，裁判写着「不适用，应判通过」却输出不通过（QLT-S3-002）。"""

    from app.eval.quality_scenarios_real import rubric_for

    def keys(case_id: str) -> list[str]:
        return [criterion.key for criterion in rubric_for(_case(case_id)).criteria]

    assert "rule_source" in keys("QLT-N5-006")  # 「请注明规则出处」
    assert "rule_source" in keys("QLT-N5-008")  # "Please cite the rule"
    assert "rule_source" not in keys("QLT-S5-001")
