# llm.md

The provider-agnostic LLM layer (`src/sandbox_analyst/llm/`): providers,
sampling parameters, the `reasoning_effort` finding, and token
observations from live testing.

## Providers

Both NVIDIA NIM and Groq expose an OpenAI-compatible chat-completions
endpoint, so one client (`OpenAICompatClient`) serves both — only the
base URL, API key, and client-side request-rate cap differ:

| Provider | Base URL | Key env var | Client-side RPM cap |
|---|---|---|---|
| `nim` | `https://integrate.api.nvidia.com/v1` | `NIM_API_KEY` | 30 |
| `groq` | `https://api.groq.com/openai/v1` | `GROQ_API_KEY` | 25 |

The `openai` Python SDK (v3.37.0 at the time of writing) is used purely
as an HTTP client (D-002); its own retry logic is disabled
(`max_retries=0`). This module's own retry policy (D-037) retries only
429, 5xx, timeouts, and connection errors — up to 6 attempts,
exponential backoff with full jitter, honoring a `Retry-After` header
when present — and raises `LLMConfigError` immediately, with no retry,
for any other 4xx (400/401/403/404/410/...).

`make_llm(settings)` builds the right backend from `SA_LLM_PROVIDER`
(`nim` | `groq` | `fake`); `"fake"` returns an empty-script `FakeLLM`.

## Sampling parameters

Fixed for every headline number (D-036), matching `openai/gpt-oss-20b`'s
own defaults per NVIDIA's sample code:

| Parameter | Value |
|---|---|
| `temperature` | 1.0 |
| `top_p` | 1.0 |
| `max_tokens` | 4096 |
| `reasoning_effort` | `medium` |
| `timeout` | 120s |

Run-to-run variance from the model's own stochasticity is handled by
reporting multiple runs with a confidence interval (D-013), not by
forcing `temperature=0`.

## The `reasoning_effort` finding

**NVIDIA NIM honors `reasoning_effort` as a native parameter — no
fallback was needed** (D-039).

Live test, `openai/gpt-oss-20b` on NIM, 2026-10-24, same question
twice per level (`"What is 15 + 27? Answer with just the number."`):

| `reasoning_effort` | Mean completion tokens (n=2) |
|---|---|
| `low` | 16 |
| `high` | 60 |

The ~4x gap is consistent and in the expected direction, confirming the
parameter is actually honored rather than silently ignored. The code
sends it as a normal top-level request parameter, exactly as the
`openai` SDK types it.

## Token observations

- **Reasoning tokens count toward `completion_tokens`, which counts
  toward `max_tokens`.** A single live call (`openai/gpt-oss-20b` on
  NIM, `"What is 15 + 27? Answer with just the number."`, default
  sampling) measured: `latency_ms=5296`, `prompt_tokens=79`,
  `completion_tokens=24`, `finish_reason=stop`, and a separate
  `reasoning_content` field was returned alongside the two-word visible
  answer. An earlier ad hoc check during P0 found an even starker case:
  a two-word answer ("ok") used 68 completion tokens total (see D-003) —
  almost all of it reasoning, none of it visible content. This is why
  `max_tokens` must stay generous (4096) and why `LLMTruncated` exists:
  if reasoning alone exhausts the budget, `finish_reason="length"`
  comes back with **empty** visible `text`, which must be detected and
  treated as a failure, not silently returned as "the answer is ''".
- **Token estimation**: `FakeLLM`'s string-script convenience (and any
  place in this project that needs a rough token count without a real
  API call) uses ~4 characters per token, a well-known rule of thumb
  for English text with this tokenizer family. It is an estimate, not
  the real token count.

## Error taxonomy

| Exception | Raised when |
|---|---|
| `RateLimitExhausted` | A 429 persisted through all 6 attempts |
| `LLMUnavailable` | A 5xx, timeout, or connection error persisted through all 6 attempts |
| `LLMConfigError` | Any other 4xx (400/401/403/404/410/...) — carries the provider's own error message, no retry |
| `LLMTruncated` | `finish_reason == "length"` with empty visible `text` |

The retryable/non-retryable split is decided by reading the caught
exception's `status_code` directly, not by matching on which `openai`
SDK exception subclass was raised — the SDK only has dedicated
subclasses for a handful of status codes (400/401/403/404/409/422/429/
5xx); a 410, the exact error this project hit when `gpt-oss-120b` was
retired, falls through to the SDK's generic `APIStatusError` with no
subclass of its own (see D-037).

## Record/replay

`RecordingLLM` wraps a real client and appends every request/response
pair to a JSONL cassette, keyed by the sha256 of a canonical JSON
encoding of `(provider, model, messages, sampling params)`. `ReplayLLM`
serves cassette entries by that same key, with no network access at
all, and raises `CassetteMiss` on an unknown request. Cassettes live
under `tests/cassettes/` and must never contain DABench data (D-038).

## Usage log

Every real call (success or failure) appends one line to
`runs/llm_usage.jsonl`: `{ts, provider, model, prompt_tokens,
completion_tokens, latency_ms, finish_reason, ok, error_type}`. This
file is gitignored (under `runs/`) and never committed.
