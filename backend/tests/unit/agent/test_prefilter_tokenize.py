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


# ---------------------------------------------------------------------------
# Task 5：英文停用词表，与中文并列（都来自 app.localization.catalog）。
# ---------------------------------------------------------------------------


def test_english_stopwords_are_filtered_out() -> None:
    tokens = tokenize("What are the refund amounts for the last 7 days?")

    assert "what" not in tokens
    assert "are" not in tokens
    assert "the" not in tokens
    assert "for" not in tokens
    assert "refund" in tokens
    assert "amounts" in tokens
    assert "last" in tokens
    assert "7" in tokens
    assert "days" in tokens


def test_english_conjunctions_are_not_treated_as_stopwords() -> None:
    """"and"/"or" 可能出现在正当的合并问法里（如 "CNN and RNN 的区别"），
    不能和真正的通用功能词一样被滤掉。"""

    tokens = tokenize("What is the difference between CNN and RNN")

    assert "and" in tokens


# ---------------------------------------------------------------------------
# Task 5：英文业务词反查出中文同义词，一并追加进候选词——语料仍是纯中文时，
# 这是英文问题能命中打分的唯一途径（见 `test_prefilter_decide.py` 的
# `test_prefilter_scores_english_business_question`）。
# ---------------------------------------------------------------------------


def test_english_business_word_expands_to_its_chinese_synonym() -> None:
    tokens = tokenize("What is the refund amount today?")

    assert "退款" in tokens or "退款金额" in tokens


def test_english_word_without_a_catalog_match_does_not_add_synonyms() -> None:
    """反查不到中文同义词的英文词不该凭空长出候选词——例如泛用词 "weather"。"""

    tokens = tokenize("What is the weather like today?")

    assert not any("一" <= char <= "鿿" for token in tokens for char in token)
