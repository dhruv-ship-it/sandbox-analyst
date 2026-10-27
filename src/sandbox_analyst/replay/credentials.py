"""Scan cassette text for credential-shaped substrings before it's ever committed.

Recorded cassettes hold real provider responses and real sandbox output;
this is a defense-in-depth check, not a replacement for not logging
secrets in the first place -- see docs/testing.md.
"""

from pathlib import Path

# Known API-key prefixes for this project's providers/services: NVIDIA
# NIM (nvapi-), Groq (gsk_), and the two generic access/secret-key-style
# prefixes (ak-/as-) the task spec itself names.
CREDENTIAL_PATTERNS = ("ak-", "as-", "gsk_", "nvapi-")


def scan_text_for_credentials(text: str) -> list[str]:
    """Return every credential-pattern match found in `text` (pattern + a short snippet)."""
    found = []
    for pattern in CREDENTIAL_PATTERNS:
        index = text.find(pattern)
        if index != -1:
            snippet = text[index : index + len(pattern) + 8]
            found.append(f"{pattern!r} at offset {index} ({snippet!r}...)")
    return found


def scan_cassette_files(paths: list[Path]) -> list[str]:
    """Scan every existing path in `paths`; returns one message per file+pattern found."""
    findings = []
    for path in paths:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        for finding in scan_text_for_credentials(text):
            findings.append(f"{path}: {finding}")
    return findings
