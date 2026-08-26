import pytest

from app.agent.prefilter import is_greeting


@pytest.mark.parametrize("question", ["你好", "在吗", "谢谢", "嗨", "早上好", "hello"])
def test_recognizes_common_greetings(question: str) -> None:
    assert is_greeting(question) is True


@pytest.mark.parametrize(
    "question",
    [
        "CNN 和 RNN 的区别是什么",
        "最近 7 天退货量趋势",
        "你好，帮我查一下最近的订单量",
    ],
)
def test_does_not_treat_business_or_offtopic_questions_as_greetings(question: str) -> None:
    assert is_greeting(question) is False
