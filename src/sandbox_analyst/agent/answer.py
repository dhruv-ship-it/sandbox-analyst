"""The FinalAnswer schema: pydantic models plus JSON extraction from a free-form reply.

The model is asked to reply with ONLY a JSON object, but providers
sometimes wrap it in a fenced code block or add stray text around it, so
extraction has to find a balanced `{...}` span rather than assume the
whole reply is clean JSON.

Name normalization happens at this boundary (D-054): the model sometimes
writes its own leading "@" into the JSON `name` field (e.g.
`"name": "@mean_fare"`) and sometimes varies the case of a name relative
to the `@name[...]` placeholders in the question's required answer
format. `AnswerItem.name` always strips whitespace and any leading "@";
`parse_final_answer` additionally re-cases a name to match the format's
own placeholder spelling, case-insensitively, when a format is given.

`AnswerItem.name` also strips a trailing `[...]` suffix (D-095): the
model sometimes copies the whole `@name[hint]` placeholder -- or even
`@name[<the value it just computed>]` -- into the JSON `name` field
instead of the bare name. Every real answer-format placeholder is a
bare word-character identifier with no brackets of its own, so a trailing
bracket group on a submitted name is always contamination, never
legitimate content -- stripping it is safe unconditionally.
"""

import json
import re

from pydantic import BaseModel, Field, ValidationError, field_validator

MAX_EXPLANATION_CHARS = 600

_FORMAT_PLACEHOLDER_RE = re.compile(r"@(\w+)\[")
_TRAILING_BRACKET_RE = re.compile(r"^(.+?)\[[^\[\]]*\]$")


class AnswerItem(BaseModel):
    name: str
    value: str

    @field_validator("name")
    @classmethod
    def _normalize_name(cls, v: str) -> str:
        name = v.strip().lstrip("@").strip()
        match = _TRAILING_BRACKET_RE.fullmatch(name)
        if match:
            name = match.group(1).strip()
        return name


class FinalAnswer(BaseModel):
    answers: list[AnswerItem]
    explanation: str = Field(max_length=MAX_EXPLANATION_CHARS)


class AnswerParseError(Exception):
    """The reply had no valid FinalAnswer JSON. `str(exc)` is safe to feed back to the model."""


def extract_format_placeholders(answer_format: str) -> list[str]:
    """Return the `@name` placeholders (in order) declared by an answer-format string."""
    return _FORMAT_PLACEHOLDER_RE.findall(answer_format)


def match_names_to_format(answers: list[AnswerItem], answer_format: str) -> list[AnswerItem]:
    """Re-case each answer's name to match a format placeholder it equals case-insensitively.

    An answer whose (already-normalized) name doesn't match any
    placeholder is passed through unchanged -- this only fixes casing,
    it never invents or drops an answer.
    """
    placeholders_by_lower = {p.lower(): p for p in extract_format_placeholders(answer_format)}
    matched = []
    for answer in answers:
        canonical = placeholders_by_lower.get(answer.name.lower())
        if canonical is not None and canonical != answer.name:
            matched.append(AnswerItem(name=canonical, value=answer.value))
        else:
            matched.append(answer)
    return matched


def _first_balanced_object(text: str) -> str | None:
    """Return the first top-level `{...}` span in `text`, respecting string quoting."""
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def extract_json(reply: str) -> str | None:
    """Best-effort extraction of a JSON object from a model reply.

    Prefers the contents of a fenced code block (``` or ```json) if one is
    present, then falls back to scanning the raw reply. Returns None if no
    balanced `{...}` span is found anywhere.
    """
    fence_start = reply.find("```")
    if fence_start != -1:
        after_fence = reply[fence_start + 3 :]
        newline = after_fence.find("\n")
        body = after_fence[newline + 1 :] if newline != -1 else after_fence
        fence_end = body.find("```")
        if fence_end != -1:
            body = body[:fence_end]
        span = _first_balanced_object(body)
        if span is not None:
            return span
    return _first_balanced_object(reply)


def parse_final_answer(reply: str, answer_format: str | None = None) -> FinalAnswer:
    """Extract and validate a FinalAnswer from a model's reply.

    When `answer_format` is given, each answer's name is re-cased to
    match that format's own `@name[...]` placeholders, case-insensitively
    (see module docstring).

    Raises AnswerParseError with a message suitable for feeding back to the
    model as a repair instruction on failure.
    """
    raw = extract_json(reply)
    if raw is None:
        raise AnswerParseError(
            "no JSON object found in the reply; respond with ONLY a JSON object of the "
            'form {"answers": [{"name": "...", "value": "..."}, ...], "explanation": "..."}'
        )
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AnswerParseError(f"the JSON object could not be parsed: {exc}") from exc
    try:
        final = FinalAnswer.model_validate(data)
    except ValidationError as exc:
        raise AnswerParseError(f"the JSON object did not match the required schema: {exc}") from exc
    if answer_format:
        final = final.model_copy(
            update={"answers": match_names_to_format(final.answers, answer_format)}
        )
    return final
