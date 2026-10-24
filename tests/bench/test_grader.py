import pytest

from sandbox_analyst.agent.answer import AnswerItem
from sandbox_analyst.bench.dabench import Label
from sandbox_analyst.bench.grader import (
    ShapeParseError,
    classify_shape,
    count_unparseable,
    grade_question,
    parse_tagged_text,
    shape_census,
    summarize,
)


def _label(id_: int, pairs: list[tuple[str, str]]) -> Label:
    return Label(id=id_, answers=pairs)


SYNTHETIC_LABELS = [
    _label(1, [("mean_fare", "34.65")]),
    _label(2, [("count", "42"), ("flag", "yes")]),
    _label(3, [("name", "Alice")]),
    _label(4, [("values", "[1, 2, 3]")]),
    _label(5, [("big", "7.46e+21")]),
]


def _answers_from(label: Label) -> list[AnswerItem]:
    return [AnswerItem(name=n, value=v) for n, v in label.answers]


# ---- classify_shape: one case per shape ----


@pytest.mark.parametrize(
    ("value", "expected_shape"),
    [
        ("42", "integer"),
        ("-7", "integer"),
        ("1,234", "integer"),
        ("3.14", "decimal_2dp"),
        ("0.0", "decimal_1dp"),
        ("12,345.67", "decimal_2dp"),
        ("7.46e+21", "scientific"),
        ("-1.2E-5", "scientific"),
        ("yes", "yes_no"),
        ("No", "yes_no"),
        ("true", "yes_no"),
        ("1, 2, 3", "list_like"),
        ("[1, 2, 3]", "list_like"),
        ("hello world", "string"),
        ("", "empty"),
        ("   ", "empty"),
    ],
)
def test_classify_shape(value, expected_shape):
    assert classify_shape(value) == expected_shape


def test_classify_shape_raises_for_a_non_string_value():
    with pytest.raises(ShapeParseError):
        classify_shape(42)  # type: ignore[arg-type]


# ---- shape_census ----


def test_shape_census_counts_and_examples():
    census = shape_census(SYNTHETIC_LABELS)
    assert census["integer"].count == 1
    assert census["integer"].examples == ["42"]
    assert census["decimal_2dp"].count == 1
    assert census["yes_no"].count == 1
    assert census["string"].count == 1
    assert census["list_like"].count == 1
    assert census["scientific"].count == 1


def test_shape_census_caps_examples_at_two():
    labels = [_label(i, [("x", "1")]) for i in range(5)]
    census = shape_census(labels)
    assert census["integer"].count == 5
    assert len(census["integer"].examples) == 2


# ---- count_unparseable: the format-only, counts-only check ----


def test_count_unparseable_is_zero_for_well_formed_labels():
    assert count_unparseable(SYNTHETIC_LABELS) == 0


def test_count_unparseable_counts_a_non_string_value():
    bad_label = Label(id=99, answers=[("x", 42)])  # type: ignore[list-item]
    assert count_unparseable([bad_label]) == 1


# ---- parse_tagged_text ----


def test_parse_tagged_text_single_tag():
    assert parse_tagged_text("@x[5]") == [AnswerItem(name="x", value="5")]


def test_parse_tagged_text_multiple_tags_in_order():
    answers = parse_tagged_text("@a[1] some prose @b[2]")
    assert [(a.name, a.value) for a in answers] == [("a", "1"), ("b", "2")]


def test_parse_tagged_text_duplicate_name_last_occurrence_wins():
    answers = parse_tagged_text("@x[1] @x[2]")
    assert len(answers) == 1
    assert answers[0].value == "2"


def test_parse_tagged_text_with_no_tags_is_empty():
    assert parse_tagged_text("no tags here at all") == []


def test_parse_tagged_text_with_an_unclosed_bracket_is_simply_not_matched():
    assert parse_tagged_text("@broken[ no closing bracket at all") == []


# ---- grade_question: self-validation ----


def test_labels_graded_against_themselves_score_100_percent_strict():
    grades = [grade_question(_answers_from(label), label, "strict") for label in SYNTHETIC_LABELS]
    assert summarize(grades).abq == 1.0


def test_labels_graded_against_themselves_score_100_percent_tolerant():
    grades = [grade_question(_answers_from(label), label, "tolerant") for label in SYNTHETIC_LABELS]
    assert summarize(grades).abq == 1.0


def test_shuffled_labels_score_low():
    n = len(SYNTHETIC_LABELS)
    grades = [
        grade_question(_answers_from(SYNTHETIC_LABELS[(i + 1) % n]), SYNTHETIC_LABELS[i], "strict")
        for i in range(n)
    ]
    assert summarize(grades).abq == 0.0


def test_missing_sub_answer_is_marked_incorrect_not_a_crash():
    label = _label(10, [("a", "1"), ("b", "2")])
    grade = grade_question([AnswerItem(name="a", value="1")], label, "strict")
    assert grade.all_correct is False
    assert grade.n_correct == 1
    b_grade = next(s for s in grade.sub_answers if s.name == "b")
    assert b_grade.predicted_value is None
    assert b_grade.correct is False


def test_grading_duplicate_tagged_text_uses_the_last_value():
    label = _label(11, [("x", "2")])
    grade = grade_question("@x[1] @x[2]", label, "strict")
    assert grade.all_correct is True


def test_extra_predicted_answers_are_ignored_but_counted():
    label = _label(24, [("a", "1")])
    predicted = [AnswerItem(name="a", value="1"), AnswerItem(name="extra", value="99")]
    grade = grade_question(predicted, label, "strict")
    assert grade.all_correct is True
    assert grade.n_extra_predicted == 1


# ---- matching modes ----


def test_strict_mode_requires_an_exact_match_after_trimming():
    label = _label(30, [("x", "34.65")])
    assert grade_question([AnswerItem(name="x", value=" 34.65 ")], label, "strict").all_correct
    assert not grade_question([AnswerItem(name="x", value="34.650")], label, "strict").all_correct


def test_tolerant_mode_accepts_numeric_rounding_within_half_a_unit():
    label = _label(31, [("x", "34.65")])  # tolerance = 0.005
    assert grade_question([AnswerItem(name="x", value="34.654")], label, "tolerant").all_correct
    assert not grade_question([AnswerItem(name="x", value="34.66")], label, "tolerant").all_correct


def test_tolerant_mode_integer_tolerance_is_half_a_unit():
    label = _label(32, [("x", "10")])  # tolerance = 0.5
    assert grade_question([AnswerItem(name="x", value="10.4")], label, "tolerant").all_correct
    assert not grade_question([AnswerItem(name="x", value="10.6")], label, "tolerant").all_correct


def test_tolerant_string_match_is_case_and_whitespace_insensitive():
    label = _label(33, [("name", "Alice")])
    predicted = [AnswerItem(name="name", value="  alice  ")]
    assert grade_question(predicted, label, "tolerant").all_correct
    assert not grade_question(predicted, label, "strict").all_correct


def test_tolerant_list_match_is_element_wise():
    label = _label(34, [("vals", "[1.0, 2.0, 3.0]")])  # per-element tolerance 0.05
    predicted = [AnswerItem(name="vals", value="[1.02, 2.0, 3.0]")]
    assert grade_question(predicted, label, "tolerant").all_correct


def test_tolerant_list_match_fails_on_a_wrong_element():
    label = _label(35, [("vals", "[1, 2, 3]")])
    predicted = [AnswerItem(name="vals", value="[1, 9, 3]")]
    assert not grade_question(predicted, label, "tolerant").all_correct


def test_tolerant_list_match_fails_on_length_mismatch():
    label = _label(36, [("vals", "[1, 2, 3]")])
    predicted = [AnswerItem(name="vals", value="[1, 2]")]
    assert not grade_question(predicted, label, "tolerant").all_correct


def test_tolerant_yes_no_match_is_case_insensitive():
    label = _label(37, [("flag", "Yes")])
    predicted = [AnswerItem(name="flag", value="yes")]
    assert grade_question(predicted, label, "tolerant").all_correct
    assert not grade_question(predicted, label, "strict").all_correct


# ---- summarize: ABQ, PSAQ, UASQ ----


def test_summarize_abq_psaq_uasq_on_a_small_set():
    label_a = _label(1, [("x", "1"), ("y", "2")])
    label_b = _label(2, [("z", "3")])
    grade_a = grade_question([AnswerItem(name="x", value="1")], label_a, "strict")  # 1/2 correct
    grade_b = grade_question([AnswerItem(name="z", value="3")], label_b, "strict")  # 1/1 correct

    summary = summarize([grade_a, grade_b])
    assert summary.abq == 0.5
    assert summary.psaq == pytest.approx((0.5 + 1.0) / 2)
    assert summary.uasq == pytest.approx(2 / 3)
    assert summary.n_sub_answers == 3
    assert summary.n_correct_sub_answers == 2


def test_summarize_of_no_grades_is_all_zero():
    summary = summarize([])
    assert summary == summarize([])
    assert summary.n_questions == 0
    assert summary.abq == 0.0
