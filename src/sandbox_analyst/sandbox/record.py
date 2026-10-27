"""Record/replay ("VCR"-style) testing for sandbox runs.

Mirrors `llm/record.py`'s shape (D-038). `RecordingSandbox` wraps a real
`Sandbox` backend; every `run()` call is also appended to a JSONL
cassette, keyed by the sha256 of a canonical JSON encoding of (the code,
the name+size of every file uploaded so far on this sandbox instance --
not the file bytes themselves, matching what the task spec asks for).
`ReplaySandbox` serves cassette entries by that same key with no real
sandbox at all, and raises `SandboxCassetteMiss` for a request it has
never seen.

Cassettes live under tests/replay/cassettes/ and must never contain
DABench data or secrets -- see docs/testing.md.
"""

import base64
import hashlib
import json
from dataclasses import asdict
from pathlib import Path

from .base import (
    UPLOAD_DIR,
    ExecError,
    ExecResult,
    Sandbox,
    validate_upload_name,
    validate_upload_size,
)


class SandboxCassetteMiss(Exception):
    """Raised by ReplaySandbox when a run() call has no matching cassette entry."""


def _cassette_key(code: str, uploads: list[tuple[str, int]]) -> str:
    canonical = {
        "code": code,
        "uploads": [{"name": name, "size": size} for name, size in uploads],
    }
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _encode_result(result: ExecResult) -> dict[str, object]:
    row = asdict(result)
    row["images"] = [
        {
            "sha256": hashlib.sha256(image).hexdigest(),
            "png_b64": base64.b64encode(image).decode("ascii"),
        }
        for image in result.images
    ]
    return row


def _decode_result(row: dict[str, object]) -> ExecResult:
    error = row["error"]
    return ExecResult(
        stdout=row["stdout"],
        stderr=row["stderr"],
        exit_code=row["exit_code"],
        error=None if error is None else ExecError(**error),
        images=[base64.b64decode(image["png_b64"]) for image in row["images"]],
        duration_ms=row["duration_ms"],
        timed_out=row["timed_out"],
        truncated=row["truncated"],
    )


class RecordingSandbox:
    """Wraps a real Sandbox; every run() call is also appended to a cassette file."""

    def __init__(self, sandbox: Sandbox, cassette_path: Path) -> None:
        self._sandbox = sandbox
        self._cassette_path = cassette_path
        self._uploads: list[tuple[str, int]] = []
        self.backend = sandbox.backend

    @property
    def last_run_cost_usd(self) -> float:
        return self._sandbox.last_run_cost_usd

    def __enter__(self) -> "RecordingSandbox":
        self._sandbox.__enter__()
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self._sandbox.__exit__(exc_type, exc, tb)

    def upload(self, name: str, data: bytes) -> str:
        remote_path = self._sandbox.upload(name, data)
        self._uploads.append((name, len(data)))
        return remote_path

    def run(self, code: str, timeout_s: int | None = None) -> ExecResult:
        key = _cassette_key(code, self._uploads)
        result = self._sandbox.run(code, timeout_s=timeout_s)
        self._cassette_path.parent.mkdir(parents=True, exist_ok=True)
        with self._cassette_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"key": key, "result": _encode_result(result)}) + "\n")
        return result

    def close(self) -> None:
        self._sandbox.close()


class ReplaySandbox:
    """Serves ExecResult objects from a cassette file, by request key. No real sandbox."""

    backend = "replay"
    last_run_cost_usd = 0.0

    def __init__(self, cassette_path: Path, max_upload_mb: int = 25) -> None:
        self._max_upload_mb = max_upload_mb
        self._uploads: list[tuple[str, int]] = []
        self._entries: dict[str, ExecResult] = {}
        if cassette_path.exists():
            with cassette_path.open(encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    row = json.loads(line)
                    self._entries[row["key"]] = _decode_result(row["result"])

    def __enter__(self) -> "ReplaySandbox":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    def upload(self, name: str, data: bytes) -> str:
        validate_upload_name(name)
        validate_upload_size(len(data), self._max_upload_mb)
        self._uploads.append((name, len(data)))
        return f"{UPLOAD_DIR}/{name}"

    def run(self, code: str, timeout_s: int | None = None) -> ExecResult:
        key = _cassette_key(code, self._uploads)
        try:
            return self._entries[key]
        except KeyError:
            raise SandboxCassetteMiss(
                f"no cassette entry for this code+uploads (key={key}); record a cassette first"
            ) from None

    def close(self) -> None:
        pass
