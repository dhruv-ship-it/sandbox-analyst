"""Record/replay ("VCR"-style) testing for LLM calls.

`RecordingLLM` wraps a real `LLMClient` and appends every request/response
pair to a JSONL cassette, keyed by the sha256 of a canonical JSON
encoding of (provider, model, messages, sampling params). `ReplayLLM`
serves cassette entries by that same key with no network access at all,
and raises `CassetteMiss` for a request it has never seen.

Cassettes live under tests/cassettes/ and must never contain DABench
data -- see CLAUDE.md's test-set-discipline rule once the dev/test split
exists.
"""

import hashlib
import json
from dataclasses import asdict
from pathlib import Path

from .base import LLMClient, LLMResponse, Message


class CassetteMiss(Exception):
    """Raised by ReplayLLM when a request has no matching cassette entry."""


def _cassette_key(
    provider: str,
    model: str,
    messages: list[Message],
    params: dict[str, object],
) -> str:
    canonical = {
        "provider": provider,
        "model": model,
        "messages": [{"role": m.role, "content": m.content} for m in messages],
        "params": params,
    }
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class RecordingLLM:
    """Wraps a real LLMClient; every call is also appended to a cassette file."""

    def __init__(self, client: LLMClient, cassette_path: Path) -> None:
        self._client = client
        self._cassette_path = cassette_path
        self.provider = client.provider
        self.model = client.model

    def complete(
        self,
        messages: list[Message],
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        reasoning_effort: str | None = None,
    ) -> LLMResponse:
        params = {
            "max_tokens": max_tokens,
            "temperature": temperature,
            "top_p": top_p,
            "reasoning_effort": reasoning_effort,
        }
        key = _cassette_key(self.provider, self.model, messages, params)
        response = self._client.complete(
            messages,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            reasoning_effort=reasoning_effort,
        )
        self._cassette_path.parent.mkdir(parents=True, exist_ok=True)
        with self._cassette_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"key": key, "response": asdict(response)}) + "\n")
        return response


class ReplayLLM:
    """Serves LLMResponse objects from a cassette file, by request key. No network."""

    def __init__(self, cassette_path: Path, provider: str, model: str) -> None:
        self.provider = provider
        self.model = model
        self._entries: dict[str, LLMResponse] = {}
        if cassette_path.exists():
            with cassette_path.open(encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    row = json.loads(line)
                    self._entries[row["key"]] = LLMResponse(**row["response"])

    def complete(
        self,
        messages: list[Message],
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        reasoning_effort: str | None = None,
    ) -> LLMResponse:
        params = {
            "max_tokens": max_tokens,
            "temperature": temperature,
            "top_p": top_p,
            "reasoning_effort": reasoning_effort,
        }
        key = _cassette_key(self.provider, self.model, messages, params)
        try:
            return self._entries[key]
        except KeyError:
            raise CassetteMiss(
                f"no cassette entry for provider={self.provider!r} model={self.model!r} "
                f"(key={key}); record a cassette first"
            ) from None
