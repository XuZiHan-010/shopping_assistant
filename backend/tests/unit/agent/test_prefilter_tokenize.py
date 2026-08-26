from app.agent.prefilter import tokenize


def test_tokenizes_pure_chinese_into_2_to_4_char_ngrams() -> None:
    tokens = tokenize("退货量")

    assert "退货" in tokens
    assert "货量" in tokens
    assert "退货量" in tokens


def test_tokenizes_pure_english_into_whole_words() -> None:
    tokens = tokenize("CNN and RNN")

    assert "cnn" in tokens
    assert "and" in tokens
    assert "rnn" in tokens
    # 不应把英文单词再拆成 n-gram 子串。
    assert "cn" not in tokens


def test_tokenizes_mixed_chinese_english_and_digits() -> None:
    tokens = tokenize("最近7天退货量")

    assert "7" in tokens
    assert "退货" in tokens
    assert "最近" in tokens


def test_all_tokens_are_lowercase() -> None:
    tokens = tokenize("GMV趋势")

    assert "gmv" in tokens
    assert all(token == token.lower() for token in tokens)


def test_stopwords_are_filtered_out() -> None:
    tokens = tokenize("请问退货规则是什么")

    assert "请问" not in tokens
    assert "什么" not in tokens
    assert "退货" in tokens


def test_stopwords_do_not_remove_business_terms() -> None:
    tokens = tokenize("最近7天退货量趋势")

    assert "退货" in tokens
    assert "趋势" in tokens


def test_empty_string_returns_no_tokens() -> None:
    assert tokenize("") == ()


def test_pure_punctuation_returns_no_tokens() -> None:
    assert tokenize("？！。，、……") == ()


def test_very_long_question_does_not_raise_and_has_bounded_token_count() -> None:
    question = "退货" * 250  # 500 字，远超真实问题长度

    tokens = tokenize(question)

    assert len(tokens) <= 3 * len(question)
