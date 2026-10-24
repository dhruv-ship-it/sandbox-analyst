"""The LLM usage log: an append-only JSON-lines record of every call made.

Mirrors sandbox/ledger.py's pattern -- pure host-side bookkeeping, no
provider dependency, fully testable with a temp file. The append is
lock-protected (D-061) since the evaluation harness's thread pool
shares one LLM client, and therefore one file, across every thread.
"""

import json
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path

DEFAULT_USAGE_LOG_PATH = Path("runs/llm_usage.jsonl")
_write_lock = threading.Lock()


@dataclass(frozen=True)
class UsageEntry:
    ts: float
    provider: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int
    finish_reason: str | None
    ok: bool
    error_type: str | None


def make_entry(
    *,
    provider: str,
    model: str,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    latency_ms: int = 0,
    finish_reason: str | None = None,
    ok: bool,
    error_type: str | None = None,
) -> UsageEntry:
    return UsageEntry(
        ts=time.time(),
        provider=provider,
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        latency_ms=latency_ms,
        finish_reason=finish_reason,
        ok=ok,
        error_type=error_type,
    )


def append_usage(entry: UsageEntry, path: Path = DEFAULT_USAGE_LOG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with _write_lock, path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(asdict(entry)) + "\n")
