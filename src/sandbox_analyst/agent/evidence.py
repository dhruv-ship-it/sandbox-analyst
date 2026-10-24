"""Evidence checking: does the script's stdout actually back up each claimed answer?

This is the grounding check that catches a hallucinated or mis-copied
value -- the model must answer FROM the executed output, not from its own
guess. Known limits of the matching rules (documented, not fixed, see
DECISIONS.md): a comma inside a single thousands-separated number is
disambiguated from a comma-separated list by trying a full-string number
parse first, but a list whose own elements use thousands separators
(e.g. "1,234, 5,678") is still split on every comma.
"""

import re
from dataclasses import dataclass

from .answer import AnswerItem

# A single numeric token: optional sign, digits (optionally thousands-grouped),
# optional fractional part, optional scientific-notation exponent.
_NUMBER_PATTERN = r"[-+]?(?:\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)(?:[eE][-+]?\d+)?"
_NUMBER_RE = re.compile(_NUMBER_PATTERN)
_FULL_NUMBER_RE = re.compile(f"^{_NUMBER_PATTERN}$")
_WHITESPACE_RE = re.compile(r"\s+")
_RELATIVE_TOLERANCE = 1e-9


@dataclass(frozen=True)
class EvidenceResult:
    name: str
    value: str
    passed: bool
    reason: str


def _strip_thousands(num_str: str) -> str:
    return num_str.replace(",", "")


def _decimal_places(num_str: str) -> int:
    mantissa = re.split(r"[eE]", num_str)[0]
    if "." not in mantissa:
        return 0
    return len(mantissa.split(".", 1)[1])


def _numbers_in(text: str) -> list[float]:
    numbers = []
    for match in _NUMBER_RE.finditer(text):
        try:
            numbers.append(float(_strip_thousands(match.group(0))))
        except ValueError:
            continue
    return numbers


def _normalize_whitespace(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", text.strip())


def _unwrap_brackets(value: str) -> str:
    if len(value) >= 2 and value[0] in "[(" and value[-1] in "])":
        return value[1:-1].strip()
    return value


def _check_number(answer_str: str, numbers_in_stdout: list[float]) -> tuple[bool, str]:
    expected = float(_strip_thousands(answer_str))
    decimals = _decimal_places(answer_str)
    for found in numbers_in_stdout:
        if round(found, decimals) == expected:
            return True, f"matched {found!r} in stdout, rounded to {decimals} decimal place(s)"
        if expected == 0:
            if abs(found) < _RELATIVE_TOLERANCE:
                return True, f"matched {found!r} within absolute tolerance of zero"
        elif abs(found - expected) <= _RELATIVE_TOLERANCE * abs(expected):
            return True, f"matched {found!r} within relative tolerance"
    return (
        False,
        f"no number in stdout matches {expected!r} (rounded to {decimals} decimal place(s))",
    )


def _check_string(answer_str: str, stdout: str) -> tuple[bool, str]:
    normalized_answer = _normalize_whitespace(answer_str).lower()
    normalized_stdout = _normalize_whitespace(stdout).lower()
    if normalized_answer and normalized_answer in normalized_stdout:
        return True, "matched as a case-insensitive substring of stdout"
    return False, "not found as a substring of stdout"


def _check_value(value: str, stdout: str, numbers_in_stdout: list[float]) -> tuple[bool, str]:
    unwrapped = _unwrap_brackets(value.strip())
    if not unwrapped:
        return False, "the answer value is empty"
    if _FULL_NUMBER_RE.fullmatch(unwrapped):
        return _check_number(unwrapped, numbers_in_stdout)
    if "," in unwrapped:
        elements = [e.strip() for e in unwrapped.split(",")]
        if all(elements):
            sub_results = [_check_value(e, stdout, numbers_in_stdout) for e in elements]
            if all(ok for ok, _ in sub_results):
                return True, f"every element of the list matched ({len(elements)} elements)"
            failed = [e for e, (ok, _) in zip(elements, sub_results, strict=True) if not ok]
            return False, f"list element(s) not evidenced in stdout: {failed}"
    return _check_string(unwrapped, stdout)


def check_evidence(answers: list[AnswerItem], stdout: str) -> list[EvidenceResult]:
    """Check every answer against `stdout`, returning a pass/fail + reason for each."""
    numbers_in_stdout = _numbers_in(stdout)
    results = []
    for answer in answers:
        passed, reason = _check_value(answer.value, stdout, numbers_in_stdout)
        results.append(
            EvidenceResult(name=answer.name, value=answer.value, passed=passed, reason=reason)
        )
    return results


def all_evidenced(results: list[EvidenceResult]) -> bool:
    return all(r.passed for r in results)
