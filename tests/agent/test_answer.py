import pytest

from sandbox_analyst.agent.answer import (
    MAX_EXPLANATION_CHARS,
    AnswerItem,
    AnswerParseError,
    extract_format_placeholders,
    extract_json,
    match_names_to_format,
    parse_final_answer,
)


def _payload(explanation: str = "the mean was computed from the printed stdout value.") -> str:
    return (
        '{"answers": [{"name": "mean_fare", "value": "34.65"}], '
        f'"explanation": "{explanation}"}}'
    )


# ---- extract_json ----


def test_extract_json_from_bare_object():
    raw = '{"a": 1}'
    assert extract_json(raw) == raw


def test_extract_json_from_fenced_json_block():
    reply = f"Here is the answer:\n```json\n{_payload()}\n```\nThanks."
    assert extract_json(reply) == _payload()


def test_extract_json_from_fenced_block_with_no_language_tag():
    reply = f"```\n{_payload()}\n```"
    assert extract_json(reply) == _payload()


def test_extract_json_from_object_surrounded_by_prose_no_fence():
    reply = f"Sure, here you go: {_payload()} let me know if you need more."
    assert extract_json(reply) == _payload()


def test_extract_json_handles_nested_braces():
    raw = '{"answers": [{"name": "x", "value": "{1,2}"}], "explanation": "ok"}'
    assert extract_json(raw) == raw


def test_extract_json_ignores_braces_inside_strings_when_counting_depth():
    # The stray "}" inside the string value must not end the object early.
    raw = '{"answers": [{"name": "x", "value": "a} b"}], "explanation": "ok"}'
    assert extract_json(raw) == raw


def test_extract_json_returns_none_when_no_braces_present():
    assert extract_json("the mean fare is 34.65") is None


def test_extract_json_returns_none_for_unbalanced_braces():
    assert extract_json('{"answers": [') is None


# ---- parse_final_answer: success ----


def test_parse_final_answer_happy_path():
    final = parse_final_answer(_payload())
    assert len(final.answers) == 1
    assert final.answers[0].name == "mean_fare"
    assert final.answers[0].value == "34.65"
    assert "stdout" in final.explanation


def test_parse_final_answer_multiple_answers():
    raw = (
        '{"answers": [{"name": "a", "value": "1"}, {"name": "b", "value": "2"}], '
        '"explanation": "two sub-answers"}'
    )
    final = parse_final_answer(raw)
    assert [a.name for a in final.answers] == ["a", "b"]


def test_parse_final_answer_extracts_from_a_fenced_reply():
    reply = f"```json\n{_payload()}\n```"
    final = parse_final_answer(reply)
    assert final.answers[0].value == "34.65"


def test_parse_final_answer_allows_an_explanation_at_exactly_the_cap():
    explanation = "x" * MAX_EXPLANATION_CHARS
    final = parse_final_answer(_payload(explanation))
    assert len(final.explanation) == MAX_EXPLANATION_CHARS


# ---- parse_final_answer: failure ----


def test_parse_final_answer_raises_when_no_json_found():
    with pytest.raises(AnswerParseError, match="no JSON object"):
        parse_final_answer("I think the mean fare is 34.65.")


def test_parse_final_answer_raises_on_malformed_json():
    # Braces balance (so extraction succeeds) but the trailing comma makes it invalid JSON.
    with pytest.raises(AnswerParseError, match="could not be parsed"):
        parse_final_answer('{"answers": [{"name": "a", "value": "1"},], "explanation": "x"}')


def test_parse_final_answer_raises_when_answers_field_missing():
    with pytest.raises(AnswerParseError, match="schema"):
        parse_final_answer('{"explanation": "no answers field here"}')


def test_parse_final_answer_raises_when_answer_item_missing_value():
    with pytest.raises(AnswerParseError, match="schema"):
        parse_final_answer('{"answers": [{"name": "a"}], "explanation": "x"}')


def test_parse_final_answer_raises_when_explanation_exceeds_cap():
    explanation = "x" * (MAX_EXPLANATION_CHARS + 1)
    with pytest.raises(AnswerParseError, match="schema"):
        parse_final_answer(_payload(explanation))


def test_parse_final_answer_raises_when_explanation_missing():
    with pytest.raises(AnswerParseError, match="schema"):
        parse_final_answer('{"answers": [{"name": "a", "value": "1"}]}')


# ---- name normalization at the answer boundary (D-054) ----


def test_answer_item_strips_whitespace_and_leading_at():
    assert AnswerItem(name="  @mean_fare  ", value="1").name == "mean_fare"


def test_answer_item_strips_a_doubled_leading_at():
    assert AnswerItem(name="@@mean_fare", value="1").name == "mean_fare"


def test_answer_item_name_with_no_at_is_unaffected():
    assert AnswerItem(name="mean_fare", value="1").name == "mean_fare"


def test_parse_final_answer_normalizes_a_leading_at_in_the_name():
    raw = '{"answers": [{"name": "@mean_fare", "value": "1"}], "explanation": "ok"}'
    final = parse_final_answer(raw)
    assert final.answers[0].name == "mean_fare"


# ---- extract_format_placeholders ----


def test_extract_format_placeholders_single():
    fmt = '@mean_fare[mean] where "mean" is a float.'
    assert extract_format_placeholders(fmt) == ["mean_fare"]


def test_extract_format_placeholders_multiple_in_order():
    fmt = "@a[val_a] @b[val_b] @c[val_c]"
    assert extract_format_placeholders(fmt) == ["a", "b", "c"]


def test_extract_format_placeholders_empty_when_none_present():
    assert extract_format_placeholders("no placeholders here") == []


# ---- match_names_to_format ----


def test_match_names_to_format_recases_a_case_insensitive_match():
    answers = [AnswerItem(name="Mean_Fare", value="34.65")]
    matched = match_names_to_format(answers, "@mean_fare[mean]")
    assert matched[0].name == "mean_fare"
    assert matched[0].value == "34.65"


def test_match_names_to_format_leaves_an_exact_match_unchanged():
    answers = [AnswerItem(name="mean_fare", value="34.65")]
    matched = match_names_to_format(answers, "@mean_fare[mean]")
    assert matched[0].name == "mean_fare"


def test_match_names_to_format_leaves_a_non_matching_name_unchanged():
    answers = [AnswerItem(name="unrelated_name", value="1")]
    matched = match_names_to_format(answers, "@mean_fare[mean]")
    assert matched[0].name == "unrelated_name"


def test_match_names_to_format_handles_multiple_answers():
    answers = [AnswerItem(name="A", value="1"), AnswerItem(name="B", value="2")]
    matched = match_names_to_format(answers, "@a[x] @b[y]")
    assert [a.name for a in matched] == ["a", "b"]


def test_parse_final_answer_recases_names_to_match_the_format():
    raw = '{"answers": [{"name": "Mean_Fare", "value": "34.65"}], "explanation": "ok"}'
    final = parse_final_answer(raw, answer_format="@mean_fare[mean]")
    assert final.answers[0].name == "mean_fare"


def test_parse_final_answer_with_no_format_does_not_recase():
    raw = '{"answers": [{"name": "Mean_Fare", "value": "34.65"}], "explanation": "ok"}'
    final = parse_final_answer(raw)
    assert final.answers[0].name == "Mean_Fare"
