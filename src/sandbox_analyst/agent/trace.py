"""TraceWriter: an append-only JSONL subscriber for AgentEvents.

Mirrors sandbox/ledger.py and llm/usage.py's pattern: pure host-side
bookkeeping, one line per event, no network. Traces live under
runs/traces/ (gitignored, never committed).
"""

import json
from dataclasses import asdict
from pathlib import Path

from .events import AgentEvent

DEFAULT_TRACE_DIR = Path("runs/traces")


class TraceWriter:
    """Callable on_event subscriber: appends every event it receives to one file."""

    def __init__(self, run_id: str, trace_dir: Path = DEFAULT_TRACE_DIR) -> None:
        self.path = trace_dir / f"{run_id}.jsonl"

    def __call__(self, event: AgentEvent) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(event)) + "\n")
