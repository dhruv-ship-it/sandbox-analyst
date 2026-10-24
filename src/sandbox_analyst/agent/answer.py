"""The FinalAnswer schema: pydantic models plus JSON extraction from a free-form reply.

The model is asked to reply with ONLY a JSON object, but providers
sometimes wrap it in a fenced code block or add stray text around it, so
extraction has to find a balanced `{...}` span rather than assume the
whole reply is clean JSON.
"""

import json

from pydantic import BaseModel, Field, ValidationError

MAX_EXPLANATION_CHARS = 600


class AnswerItem(BaseModel):
    name: str
    value: str


class FinalAnswer(BaseModel):
    answers: list[AnswerItem]
    explanation: str = Field(max_length=MAX_EXPLANATION_CHARS)


class AnswerParseError(Exception):
    """The reply had no valid FinalAnswer JSON. `str(exc)` is safe to feed back to the model."""


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


def parse_final_answer(reply: str) -> FinalAnswer:
    """Extract and validate a FinalAnswer from a model's reply.

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
        return FinalAnswer.model_validate(data)
    except ValidationError as exc:
        raise AnswerParseError(f"the JSON object did not match the required schema: {exc}") from exc
