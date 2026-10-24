"""The DABench grader: parse predicted answers and score them against labels.

Designed from DEV labels only (D-057): `shape_census` classifies every
DEV sub-answer value into a shape (integer, decimal-with-N-places,
scientific, yes/no, list-like, string) with counts and examples, written
to `docs/grader.md`. `count_unparseable` is then run over ALL labels
(dev AND test) as a format-only check -- it returns a count only, never
any label content, per CLAUDE.md's test-set-discipline rule (the one
sanctioned way this module ever touches a TEST label).

Only names that appear in the label are ever scored; a predicted answer
with no matching label name is counted as "extra" but never scored
against anything (D-057).
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from sandbox_analyst.agent.answer import AnswerItem

from .dabench import Label, load_labels
from .split import load_split

DEFAULT_LABELS_PATH = Path("data/dabench/da-dev-labels.jsonl")
DEFAULT_GRADER_DOC_PATH = Path("docs/grader.md")

Mode = Literal["strict", "tolerant"]

_INTEGER_RE = re.compile(r"^[-+]?\d+$")
_DECIMAL_RE = re.compile(r"^[-+]?\d+\.\d+$")
_SCIENTIFIC_RE = re.compile(r"^[-+]?\d+(\.\d+)?[eE][-+]?\d+$")
_YES_NO_VALUES = frozenset({"yes", "no", "true", "false"})
_WHITESPACE_RE = re.compile(r"\s+")
_TAG_RE = re.compile(r"@(\w+)\[([^\]]*)\]")
_MIN_TOLERANCE = 1e-9


class ShapeParseError(Exception):
    """A sub-answer value can't be classified into any known shape."""


def _unwrap_brackets(value: str) -> str:
    if len(value) >= 2 and value[0] in "[(" and value[-1] in "])":
        return value[1:-1].strip()
    return value


def classify_shape(value: str) -> str:
    """Classify one sub-answer value's shape. Raises ShapeParseError if it can't.

    A total function over every real string value -- "string" is the
    catch-all for free text, so the only actual failure mode is a value
    that isn't a string at all (a data/schema bug worth catching, not a
    content issue).
    """
    if not isinstance(value, str):
        raise ShapeParseError(f"expected a string value, got {type(value).__name__}")
    stripped = value.strip()
    if not stripped:
        return "empty"
    unwrapped = _unwrap_brackets(stripped)
    degrouped = unwrapped.replace(",", "")
    if _INTEGER_RE.fullmatch(degrouped):
        return "integer"
    if _SCIENTIFIC_RE.fullmatch(degrouped):
        return "scientific"
    if _DECIMAL_RE.fullmatch(degrouped):
        n = len(degrouped.split(".", 1)[1])
        return f"decimal_{n}dp"
    if "," in unwrapped:
        return "list_like"
    if stripped.lower() in _YES_NO_VALUES:
        return "yes_no"
    return "string"


@dataclass(frozen=True)
class ShapeCensusEntry:
    count: int
    examples: list[str]


def shape_census(labels: list[Label]) -> dict[str, ShapeCensusEntry]:
    """Classify every sub-answer value across `labels`, with counts and up to 2 examples each."""
    counts: dict[str, int] = {}
    examples: dict[str, list[str]] = {}
    for label in labels:
        for _, value in label.answers:
            shape = classify_shape(value)
            counts[shape] = counts.get(shape, 0) + 1
            bucket = examples.setdefault(shape, [])
            if len(bucket) < 2:
                bucket.append(value)
    return {shape: ShapeCensusEntry(counts[shape], examples[shape]) for shape in counts}


def count_unparseable(labels: list[Label]) -> int:
    """Format-only check: count sub-answer values that fail to classify. Must be 0.

    This is the one function allowed to run over the TEST split's
    labels directly -- it returns a bare count, never prints or returns
    any label value (CLAUDE.md rule 11).
    """
    failures = 0
    for label in labels:
        for _, value in label.answers:
            try:
                classify_shape(value)
            except ShapeParseError:
                failures += 1
    return failures


def parse_tagged_text(text: str) -> list[AnswerItem]:
    """Parse @name[value] tags from free text. The last occurrence of a name wins."""
    by_name: dict[str, str] = {}
    order: list[str] = []
    for match in _TAG_RE.finditer(text):
        name, value = match.group(1), match.group(2)
        if name not in by_name:
            order.append(name)
        by_name[name] = value
    return [AnswerItem(name=name, value=by_name[name]) for name in order]


def coerce_answers(predicted: Sequence[AnswerItem] | str) -> list[AnswerItem]:
    """Normalize either answer source (a FinalAnswer's `.answers`, or @name[value] text)."""
    if isinstance(predicted, str):
        return parse_tagged_text(predicted)
    return list(predicted)


def _normalize_ws(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", text.strip())


def _to_float(value: str) -> float | None:
    try:
        return float(value.replace(",", ""))
    except ValueError:
        return None


def _tolerance_for(label_value: str) -> float:
    """Half a unit in `label_value`'s own last decimal place, scaled by any exponent."""
    s = label_value.replace(",", "")
    parts = re.split(r"[eE]", s)
    mantissa = parts[0]
    exponent = int(parts[1]) if len(parts) > 1 else 0
    decimals = len(mantissa.split(".", 1)[1]) if "." in mantissa else 0
    return max(0.5 * (10 ** (exponent - decimals)), _MIN_TOLERANCE)


def _tolerant_number_match(label_value: str, predicted_value: str) -> bool:
    label_f = _to_float(_unwrap_brackets(label_value.strip()))
    pred_f = _to_float(_unwrap_brackets(predicted_value.strip()))
    if label_f is None or pred_f is None:
        return False
    return abs(label_f - pred_f) <= _tolerance_for(label_value.strip())


def _tolerant_string_match(label_value: str, predicted_value: str) -> bool:
    return _normalize_ws(label_value).lower() == _normalize_ws(predicted_value).lower()


def _split_list(value: str) -> list[str]:
    unwrapped = _unwrap_brackets(value.strip())
    return [e.strip() for e in unwrapped.split(",")]


def _tolerant_list_match(label_value: str, predicted_value: str) -> bool:
    label_elems = _split_list(label_value)
    pred_elems = _split_list(predicted_value)
    if len(label_elems) != len(pred_elems):
        return False
    return all(_tolerant_match(le, pe) for le, pe in zip(label_elems, pred_elems, strict=True))


def _tolerant_match(label_value: str, predicted_value: str) -> bool:
    shape = classify_shape(label_value)
    if shape in ("integer", "scientific") or shape.startswith("decimal_"):
        return _tolerant_number_match(label_value, predicted_value)
    if shape == "list_like":
        return _tolerant_list_match(label_value, predicted_value)
    return _tolerant_string_match(label_value, predicted_value)


def _match(label_value: str, predicted_value: str, mode: Mode) -> bool:
    if mode == "strict":
        return label_value.strip() == predicted_value.strip()
    return _tolerant_match(label_value, predicted_value)


@dataclass(frozen=True)
class SubAnswerGrade:
    name: str
    label_value: str
    predicted_value: str | None
    correct: bool


@dataclass(frozen=True)
class QuestionGrade:
    question_id: int
    sub_answers: list[SubAnswerGrade]
    n_extra_predicted: int

    @property
    def n_correct(self) -> int:
        return sum(1 for s in self.sub_answers if s.correct)

    @property
    def all_correct(self) -> bool:
        return len(self.sub_answers) > 0 and self.n_correct == len(self.sub_answers)

    @property
    def fraction_correct(self) -> float:
        if not self.sub_answers:
            return 0.0
        return self.n_correct / len(self.sub_answers)


def grade_question(
    predicted: Sequence[AnswerItem] | str, label: Label, mode: Mode
) -> QuestionGrade:
    """Grade one question's predicted answers against its label. Only label names are scored."""
    answers = coerce_answers(predicted)
    predicted_by_name = {a.name: a.value for a in answers}
    label_names = {name for name, _ in label.answers}

    sub_answers = []
    for name, label_value in label.answers:
        predicted_value = predicted_by_name.get(name)
        correct = predicted_value is not None and _match(label_value, predicted_value, mode)
        sub_answers.append(SubAnswerGrade(name, label_value, predicted_value, correct))

    n_extra = sum(1 for name in predicted_by_name if name not in label_names)
    return QuestionGrade(question_id=label.id, sub_answers=sub_answers, n_extra_predicted=n_extra)


@dataclass(frozen=True)
class GradeSummary:
    n_questions: int
    abq: float
    psaq: float
    uasq: float
    n_sub_answers: int
    n_correct_sub_answers: int


def summarize(grades: list[QuestionGrade]) -> GradeSummary:
    """ABQ (all sub-answers correct), PSAQ (mean per-question fraction), UASQ (pooled fraction)."""
    n_questions = len(grades)
    if n_questions == 0:
        return GradeSummary(0, 0.0, 0.0, 0.0, 0, 0)
    abq = sum(1 for g in grades if g.all_correct) / n_questions
    psaq = sum(g.fraction_correct for g in grades) / n_questions
    total_sub = sum(len(g.sub_answers) for g in grades)
    total_correct = sum(g.n_correct for g in grades)
    uasq = total_correct / total_sub if total_sub else 0.0
    return GradeSummary(n_questions, abq, psaq, uasq, total_sub, total_correct)


def _dev_labels() -> list[Label]:
    dev_ids = set(load_split("dev")["question_ids"])
    return [label for label in load_labels(DEFAULT_LABELS_PATH) if label.id in dev_ids]


def main() -> int:
    """Write docs/grader.md: a DEV-only shape census, plus an all-labels format check."""
    dev_labels = _dev_labels()
    all_labels = load_labels(DEFAULT_LABELS_PATH)
    census = shape_census(dev_labels)
    n_failures = count_unparseable(all_labels)
    n_sub_answers = sum(len(label.answers) for label in all_labels)

    lines = [
        "# grader.md",
        "",
        "Shape census over DEV labels only (never test), by `classify_shape`. "
        f"{len(dev_labels)} dev labels, {sum(len(label.answers) for label in dev_labels)} "
        "sub-answers.",
        "",
        "| shape | count | examples |",
        "|---|---|---|",
    ]
    for shape in sorted(census):
        entry = census[shape]
        examples = ", ".join(repr(e) for e in entry.examples)
        lines.append(f"| {shape} | {entry.count} | {examples} |")
    lines += [
        "",
        f"Format-only check across all {len(all_labels)} labels "
        f"({n_sub_answers} sub-answers, dev + test): **{n_failures}** failed to classify "
        "into a known shape (must be 0). Counts only -- no label content from the test "
        "split is read anywhere above this line.",
    ]
    DEFAULT_GRADER_DOC_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(  # noqa: T201
        f"wrote {DEFAULT_GRADER_DOC_PATH}: {len(census)} shapes over {len(dev_labels)} dev labels; "
        f"{n_failures} format failures across all {len(all_labels)} labels"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
