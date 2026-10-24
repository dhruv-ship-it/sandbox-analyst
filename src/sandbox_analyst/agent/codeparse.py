"""Extract the model's Python script from a chat reply."""

import re

_PYTHON_BLOCK_RE = re.compile(r"```python\s*\n(.*?)```", re.DOTALL)


def extract_code(reply: str) -> str | None:
    """Return the code inside the first ```python fenced block, or None."""
    match = _PYTHON_BLOCK_RE.search(reply)
    if match is None:
        return None
    return match.group(1).rstrip("\n")
