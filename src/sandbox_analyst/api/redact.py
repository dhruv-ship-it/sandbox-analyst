"""Mask secrets before they ever reach a log line (CLAUDE.md rule 2's spirit,
applied to runtime output rather than committed files).

Two independent passes: known credential prefixes (Modal, Groq, NVIDIA NIM),
which catches a leaked key even if it's not one of this project's own
configured settings; and the literal value of any configured `SecretStr`
field, which catches a configured secret regardless of its prefix.
"""

import re

from pydantic import SecretStr

from sandbox_analyst.config import Settings

REDACTED = "[redacted]"

# Modal (`ak-`/`as-`), Groq (`gsk_`), NVIDIA NIM (`nvapi-`).
_CREDENTIAL_RE = re.compile(r"\b(?:ak-|as-|gsk_|nvapi-)[A-Za-z0-9_-]+")


def redact_secrets(text: str, settings: Settings | None = None) -> str:
    redacted = _CREDENTIAL_RE.sub(REDACTED, text)
    if settings is not None:
        for name in type(settings).model_fields:
            value = getattr(settings, name)
            if isinstance(value, SecretStr):
                secret_value = value.get_secret_value()
                if secret_value:
                    redacted = redacted.replace(secret_value, REDACTED)
    return redacted
