"""E6 线上反馈回流（N5 D Task 5；PRD E6，Q30）——纯函数部分，不连库。

回流脚本只产出**候选清单**给人审阅：脱敏、去重、归因，自己不写评测集；
调优集与最终测试集按案例指纹互斥。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

import pytest

from app.eval.feedback_harvest import (
    DATASETS_ROOT,
    FeedbackSample,
    assert_disjoint,
    build_candidates,
    case_fingerprint,
    dataset_fingerprints,
    redact,
    write_candidates,
)

T = datetime(2026, 10, 4, 8, 0, tzinfo=UTC)


def _sample(question: str, **overrides: object) -> FeedbackSample:
    values: dict[str, object] = {
        "role": "CUSTOMER",
        "locale": "zh-CN",
        "question": question,
        "signal": "DISLIKE",
        "answer_mode": "CHAT",
        "degraded_reason": None,
        "quality_status": "PASSED",
        "feedback_reason": None,
        "created_at": T,
    }
    values.update(overrides)
    return FeedbackSample(**values)  # type: ignore[arg-type]


def snapshot_dir(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


# ---- 指纹 -----------------------------------------------------------------------------------


def test_fingerprint_ignores_spacing_case_and_punctuation_width() -> None:
    base = case_fingerprint("CUSTOMER", "这条围巾可以退货吗？")

    assert case_fingerprint("CUSTOMER", "  这条围巾  可以退货吗?  ") == base
    assert case_fingerprint("CUSTOMER", "这条围巾可以退货吗") == base
    assert case_fingerprint("CUSTOMER", "Can I Return it?") == case_fingerprint(
        "CUSTOMER", "can i return it"
    )


def test_fingerprint_separates_roles_and_different_questions() -> None:
    assert case_fingerprint("CUSTOMER", "今天卖得怎么样") != case_fingerprint(
        "MERCHANT", "今天卖得怎么样"
    )
    assert case_fingerprint("MERCHANT", "今天卖得怎么样") != case_fingerprint(
        "MERCHANT", "昨天卖得怎么样"
    )


# ---- 脱敏 -----------------------------------------------------------------------------------


def test_redact_masks_contact_details_identifiers_and_long_numbers() -> None:
    text = (
        "我手机 13912345678，邮箱 a.b@example.com，身份证 11010119900307123X，"
        "订单 3f2b8c1e-9a4d-4e21-8b7c-0a1b2c3d4e5f 和 BR20261004000123 到哪了"
    )

    cleaned = redact(text)

    for leaked in (
        "13912345678",
        "a.b@example.com",
        "11010119900307123X",
        "3f2b8c1e-9a4d-4e21-8b7c-0a1b2c3d4e5f",
        "20261004000123",
    ):
        assert leaked not in cleaned
    assert "到哪了" in cleaned  # 问题本身的意思保留


def test_redact_leaves_ordinary_questions_untouched() -> None:
    assert redact("预算 500 元以内的通勤鞋有推荐吗？") == "预算 500 元以内的通勤鞋有推荐吗？"


# ---- 去重与归因 -----------------------------------------------------------------------------


def test_candidates_are_deduplicated_and_attributed() -> None:
    samples = [
        _sample("这条围巾可以退货吗？", signal="DISLIKE", feedback_reason="答非所问"),
        _sample("这条围巾可以退货吗", signal="DEGRADED", degraded_reason="LLM_BUDGET_EXCEEDED"),
        _sample(
            "今天卖得怎么样",
            role="MERCHANT",
            answer_mode="METRIC",
            signal="DEGRADED",
            degraded_reason="UPSTREAM",
        ),
    ]

    candidates = build_candidates(samples, known_fingerprints=frozenset())

    assert len(candidates) == 2
    scarf = next(c for c in candidates if c.role == "CUSTOMER")
    assert scarf.occurrences == 2
    assert scarf.signals == ["DEGRADED", "DISLIKE"]
    assert scarf.degraded_reasons == ["LLM_BUDGET_EXCEEDED"]
    assert scarf.feedback_reasons == ["答非所问"]
    assert scarf.already_in_dataset is False
    # 出现次数多的排前面，方便人工先看高频问题。
    assert candidates[0] is scarf


def test_candidate_already_covered_by_a_dataset_is_flagged() -> None:
    known = frozenset({case_fingerprint("CUSTOMER", "这条围巾可以退货吗")})

    [candidate] = build_candidates([_sample("这条围巾可以退货吗？")], known_fingerprints=known)

    assert candidate.already_in_dataset is True


def test_candidate_never_carries_identity_or_answer_text() -> None:
    [candidate] = build_candidates(
        [_sample("我的手机 13912345678 收不到验证码")], known_fingerprints=frozenset()
    )

    payload = json.dumps(candidate.to_json(), ensure_ascii=False)

    assert "13912345678" not in payload
    for forbidden in ("merchant_id", "buyer_key", "session_id", "answer_text", "conversation_id"):
        assert forbidden not in payload


def test_question_that_is_only_personal_data_is_dropped() -> None:
    assert build_candidates([_sample("13912345678")], known_fingerprints=frozenset()) == []


# ---- 调优集与最终测试集互斥 ------------------------------------------------------------------


def test_tuning_and_final_sets_are_disjoint() -> None:
    tuning = dataset_fingerprints("tuning")
    final = dataset_fingerprints("final")

    assert final, "最终测试集不应为空"
    assert tuning.isdisjoint(final)


def test_overlap_between_tuning_and_final_is_reported() -> None:
    shared = case_fingerprint("CUSTOMER", "这条围巾可以退货吗")

    with pytest.raises(ValueError, match="同时出现在调优集与最终测试集"):
        assert_disjoint(tuning=frozenset({shared}), final=frozenset({shared, "other"}))
    assert_disjoint(tuning=frozenset({"only-tuning"}), final=frozenset({shared}))


# ---- 脚本不写评测集 --------------------------------------------------------------------------


def test_feedback_script_never_writes_eval_datasets(tmp_path: Path) -> None:
    before = snapshot_dir(DATASETS_ROOT)
    candidates = build_candidates([_sample("这条围巾可以退货吗？")], known_fingerprints=frozenset())

    written = write_candidates(candidates, output=tmp_path)

    assert written.parent == tmp_path and written.suffix == ".jsonl"
    lines = written.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1 and json.loads(lines[0])["question"] == "这条围巾可以退货吗？"
    assert snapshot_dir(DATASETS_ROOT) == before


def test_output_inside_the_datasets_tree_is_refused() -> None:
    candidates = build_candidates([_sample("这条围巾可以退货吗？")], known_fingerprints=frozenset())
    before = snapshot_dir(DATASETS_ROOT)

    for target in (DATASETS_ROOT, DATASETS_ROOT / "tuning", DATASETS_ROOT / "quality" / "new"):
        with pytest.raises(ValueError, match="不得写入评测集目录"):
            write_candidates(candidates, output=target)

    assert snapshot_dir(DATASETS_ROOT) == before
