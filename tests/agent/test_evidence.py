from sandbox_analyst.agent.answer import AnswerItem
from sandbox_analyst.agent.evidence import all_evidenced, check_evidence


def _check_one(name: str, value: str, stdout: str):
    return check_evidence([AnswerItem(name=name, value=value)], stdout)[0]


# ---- numbers ----


def test_exact_number_match():
    result = _check_one("mean_fare", "34.65", "mean_fare = 34.65\n")
    assert result.passed


def test_number_matches_after_rounding_a_more_precise_stdout_value():
    result = _check_one("mean_fare", "34.65", "mean_fare = 34.652871\n")
    assert result.passed


def test_number_does_not_match_a_different_value():
    result = _check_one("mean_fare", "34.65", "mean_fare = 40.00\n")
    assert not result.passed


def test_a_number_is_not_evidenced_by_a_longer_number_containing_it_as_a_substring():
    # 4.5 must NOT be considered evidenced by 14.5.
    result = _check_one("x", "4.5", "x = 14.5\n")
    assert not result.passed


def test_a_longer_number_is_still_matched_correctly():
    result = _check_one("x", "14.5", "x = 14.5\n")
    assert result.passed


def test_negative_numbers():
    result = _check_one("delta", "-3.2", "delta = -3.2\n")
    assert result.passed


def test_negative_number_not_confused_with_positive():
    result = _check_one("delta", "-3.2", "delta = 3.2\n")
    assert not result.passed


def test_thousands_separator_in_stdout():
    result = _check_one("total", "12345", "total = 12,345\n")
    assert result.passed


def test_thousands_separator_in_answer_value():
    result = _check_one("total", "12,345", "total = 12345\n")
    assert result.passed


def test_scientific_notation_in_stdout():
    result = _check_one("big", "15000000000.0", "big = 1.5e10\n")
    assert result.passed


def test_integer_answer_matches_zero_decimal_rounding():
    result = _check_one("count", "5", "count = 5.00000001\n")
    assert result.passed


def test_zero_answer_matches_near_zero_stdout_value():
    result = _check_one("diff", "0", "diff = 0.0000000001\n")
    assert result.passed


def test_zero_answer_does_not_match_a_nonzero_value():
    result = _check_one("diff", "0", "diff = 1.0\n")
    assert not result.passed


def test_no_numbers_in_stdout_at_all():
    result = _check_one("x", "5", "no numbers here\n")
    assert not result.passed
    assert "no number" in result.reason


# ---- strings ----


def test_string_substring_match_case_insensitive():
    result = _check_one("gender", "Male", "the most common gender is MALE overall\n")
    assert result.passed


def test_string_substring_no_match():
    result = _check_one("gender", "nonbinary", "the most common gender is Female\n")
    assert not result.passed


def test_string_whitespace_is_normalized_on_both_sides():
    result = _check_one("label", "high  risk", "classification:   high   risk   group\n")
    assert result.passed


def test_bracketed_single_value_is_unwrapped():
    result = _check_one("top", "[Male]", "top category: Male\n")
    assert result.passed


# ---- list-like values ----


def test_comma_separated_list_all_elements_present():
    result = _check_one("ages", "21, 34, 56", "ages printed: 21 and 34 and 56\n")
    assert result.passed


def test_comma_separated_list_one_element_missing():
    result = _check_one("ages", "21, 34, 56", "ages printed: 21 and 34\n")
    assert not result.passed


def test_bracketed_list_of_numbers():
    result = _check_one("ages", "[21, 34]", "21 ... 34\n")
    assert result.passed


def test_bracketed_list_of_strings():
    result = _check_one("labels", "[low, high]", "levels: low then high\n")
    assert result.passed


def test_single_thousands_number_with_a_comma_is_not_treated_as_a_two_item_list():
    # "12,345" is one number, not the list ["12", "345"].
    result = _check_one("total", "12,345", "total = 12345.0\n")
    assert result.passed


# ---- multiple answers / aggregate ----


def test_check_evidence_returns_one_result_per_answer_in_order():
    answers = [AnswerItem(name="a", value="1"), AnswerItem(name="b", value="2")]
    results = check_evidence(answers, "a = 1\nb = 2\n")
    assert [r.name for r in results] == ["a", "b"]
    assert all(r.passed for r in results)


def test_all_evidenced_true_when_every_result_passes():
    answers = [AnswerItem(name="a", value="1"), AnswerItem(name="b", value="2")]
    results = check_evidence(answers, "a = 1\nb = 2\n")
    assert all_evidenced(results)


def test_all_evidenced_false_when_any_result_fails():
    answers = [AnswerItem(name="a", value="1"), AnswerItem(name="b", value="999")]
    results = check_evidence(answers, "a = 1\nb = 2\n")
    assert not all_evidenced(results)


def test_reason_is_present_for_both_pass_and_fail():
    results = check_evidence([AnswerItem(name="a", value="1")], "a = 1\n")
    assert results[0].reason
    results = check_evidence([AnswerItem(name="a", value="999")], "a = 1\n")
    assert results[0].reason


# ---- explicit empty-collection literals (D-095) ----
#
# Unwrapping "[]" strips both brackets and leaves an empty string, which the
# generic path rejects as "the answer value is empty" -- so a genuinely
# correct empty-list answer could never be evidenced without this special
# case, and the agent would burn its whole repair budget resubmitting it.


def test_empty_list_literal_passes_when_stdout_contains_it():
    result = _check_one("outlier_list", "[]", "outlier_list = []\n")
    assert result.passed


def test_empty_tuple_literal_passes_when_stdout_contains_it():
    result = _check_one("outlier_tuple", "()", "outlier_tuple = ()\n")
    assert result.passed


def test_empty_list_literal_fails_when_stdout_never_prints_it():
    result = _check_one("outlier_list", "[]", "no outliers were found\n")
    assert not result.passed
    assert "no literal" in result.reason


def test_a_truly_empty_string_value_still_fails():
    result = _check_one("x", "", "x = 1\n")
    assert not result.passed
    assert "empty" in result.reason


def test_a_non_empty_bracketed_list_is_unaffected_by_the_empty_collection_check():
    result = _check_one("ages", "[21, 34]", "21 ... 34\n")
    assert result.passed
