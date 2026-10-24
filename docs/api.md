# api.md

The public demo's FastAPI app (`src/sandbox_analyst/api/`): every
endpoint, the public-safety limits, and the results of one real local
live smoke run against Groq + Modal. No React UI yet (that's Prompt 6);
`GET /` serves a placeholder page until `web/dist` exists.

## Running it

```powershell
uv run sa serve                        # host 0.0.0.0, port from $env:PORT (default 8000)
$env:PORT = "8010"; uv run sa serve    # a different port
```

`sa serve` wires real backends from `Settings` (`SA_LLM_PROVIDER`,
`SA_SANDBOX`, ...). Tests construct the app directly with
`create_app(settings, llm=FakeLLM(...), sandbox_factory=...)` instead
(CLAUDE.md rule 6: no network in unit tests).

## Endpoints

All JSON error bodies have the shape `{"error": "<code>", "detail": "<message>"}`.
There is no CORS configuration (same-origin only) and no authentication
-- every endpoint is public, protected only by the limits below.

### `GET /api/health`

No parameters. Always 200.

```json
{"status": "ok", "version": "f965e60", "provider": "groq", "model": "openai/gpt-oss-20b", "sandbox": "modal"}
```

`version` is `APP_VERSION` if set, else the current `git rev-parse --short HEAD`,
else `"unknown"`. Never includes API keys, the sandbox budget, or any
other secret/figure.

### `POST /api/datasets`

`multipart/form-data`, one field `file` (a `.csv`). Checks, in order:
file name ends in `.csv`; body size `<= API_MAX_UPLOAD_MB` (default 5 MB,
also enforced earlier by a `Content-Length` guard on every request);
parseable by the same pandas-based profiler the agent uses
(`agent/profile.py`); row/column counts `<= API_MAX_ROWS` /
`API_MAX_COLS` (default 200,000 / 100). A bad upload is a `400
invalid_dataset`; an oversized body may instead be rejected pre-parse as
a `413 request_too_large`.

On success (`200`), the bytes are stored under
`SA_DATA_DIR/uploads/<dataset_id>.csv` with a 1-hour TTL
(`API_UPLOAD_TTL_S`), and the response is:

```json
{
  "dataset_id": "...", "file_name": "sales.csv", "n_rows": 180, "n_cols": 5,
  "columns": [{"name": "date", "dtype": "str"}, ...],
  "sample_rows": [{"date": "2026-01-01", "region": "North", ...}, ...]
}
```

### `GET /api/examples`

No parameters. Returns the bundled `examples.json` keyed by dataset
name (`sales`, `students`, `weather`), each with `title`, `description`,
`file_name`, and 3 suggested `questions` (at least one asking for a
chart, per dataset).

### `POST /api/examples/{name}/load`

Copies that example's CSV into a new TTL-backed upload (same mechanics
as `POST /api/datasets`, already validated at generation time) and
returns `{"dataset_id": ..., ...same shape as the upload response}`.
Unknown `name` is a `404 not_found`.

### `POST /api/runs`

Body: `{"dataset_id": "...", "question": "..."}`. `question` must be
3-500 chars (`422 validation_error` otherwise). Checks, in order: the
dataset exists and hasn't expired (`404 not_found`); the public-safety
limits below (`429 rate_limited`). On success, starts `run_agent` in a
background thread and returns immediately:

```json
{"run_id": "1318a7afd52c4f7181672b340b73421e"}
```

This `run_id` is the API's OWN identifier, not `run_agent`'s internal
one -- see DECISIONS.md D-067 for why (`run_agent` always mints its own
id and has no parameter to accept one; the API mints its own and uses
every other endpoint below consistently with it).

### `GET /api/runs/{run_id}/events`

Server-Sent Events. Replays every event recorded so far, then streams
live events as the run progresses, then closes the connection right
after a `run_finished` event (whichever point that happens from). An
idle connection gets a `: keep-alive\n\n` comment every 15 seconds
(App Service drops long-silent connections). Each message is
`data: <json>\n\n` where the JSON matches `AgentEvent`'s shape
(`run_id` rewritten to the API's public id, `seq`, `ts`, `type`,
`attempt`, `payload`) -- the exact same event types the CLI already
prints (`run_started`, `profile`, `llm_request`, `llm_response`, `code`,
`static_check`, `exec_started`, `exec_result`, `answer`, `evidence`,
`observation`, `run_finished`). Unknown `run_id` is `404`.

### `GET /api/runs/{run_id}`

The current snapshot -- callable before the run finishes (fields are
empty/zero until `run_agent` returns) or after:

```json
{
  "run_id": "...", "dataset_id": "...", "question": "...", "status": "answered",
  "answers": [{"name": "...", "value": "..."}],
  "explanation": "...", "code": "...", "stdout_tail": "...",
  "evidence": [{"name": "...", "value": "...", "passed": true, "reason": "..."}],
  "attempts": [{"attempt": 1, "has_code": true, "check_ok": true, "n_check_violations": 0,
                "exec_ok": true, "timed_out": false, "answered": true, "observation": null}],
  "chart_urls": ["/api/runs/.../artifacts/attempt1_0.png"],
  "prompt_tokens": 1027, "completion_tokens": 618, "latency_ms": 1983,
  "error": null
}
```

`status` is one of `pending`, `running`, or a terminal `run_agent`
status (`answered`, `failed`, `repeated_failure`, `tool_failure`,
`budget_exceeded`, `llm_error`) or `error` (an unexpected failure
outside `run_agent`'s own status machine). `stdout_tail` is capped at
2000 chars. Unknown `run_id` is `404`.

### `GET /api/runs/{run_id}/artifacts/{name}`

PNG only. `name` must match `^attempt\d+_\d+\.png$` exactly (what
`agent/loop.py` ever generates) and the resolved path is re-checked
against the run's own artifact directory before it's read (D-075) --
anything else, or a run/chart that doesn't exist, is `404`. Chart PNGs
currently live at the agent's own fixed, repo-relative
`runs/artifacts/<id>/` path rather than under `SA_DATA_DIR`, because
redirecting them would require editing `agent/loop.py`, out of scope
for this task (D-067).

### `GET /api/runs/{run_id}/trace`

The run's JSONL trace file (one line per `AgentEvent`, same content as
the SSE stream) as a download, `Content-Type: application/x-ndjson`.
`404` if the run id is unknown or no trace has been written yet.

## Public-safety limits

All configurable via `Settings` / environment variables, enforced in
`api/limits.py`'s `RateLimiter` (see DECISIONS.md D-068/D-071):

| Limit | Default | Env var |
|---|---|---|
| Runs per IP per hour | 5 | `SA_RATE_LIMIT_PER_IP_HOUR` |
| Runs per IP per day | 20 | `SA_RATE_LIMIT_PER_IP_DAY` |
| Runs globally per day | 50 | `SA_RATE_LIMIT_GLOBAL_DAY` |
| Concurrent runs | 2 | `SA_MAX_CONCURRENT_RUNS` |
| Upload size | 5 MB | `API_MAX_UPLOAD_MB` |
| Upload rows | 200,000 | `API_MAX_ROWS` |
| Upload columns | 100 | `API_MAX_COLS` |
| Upload TTL | 1 hour | `API_UPLOAD_TTL_S` |

A limit hit returns `429 rate_limited` (or `busy, try again shortly`
for the concurrency cap specifically). The client IP used for the
per-IP limits is the raw socket peer unless `SA_TRUST_PROXY=true`, in
which case it's the right-most entry of `X-Forwarded-For` (the one
Azure's own front end appended) -- see D-074.

## Local live smoke (real Groq + Modal)

**Date:** 2026-10-25. **Provider/model:** Groq, `openai/gpt-oss-20b`
(same model as every benchmark number -- D-065). **Sandbox:** Modal,
real (gVisor, `block_network=True`). Server started with
`SA_LLM_PROVIDER=groq`, `SA_DATA_DIR=runs/api-smoke`, `PORT=8010`.
Dataset: the `sales` example, loaded via `POST /api/examples/sales/load`.
Both questions are from `examples.json`'s own suggested questions.

| Question | Needs chart | Status | SSE wall-clock | LLM latency (reported) | Attempts | Chart returned |
|---|---|---|---|---|---|---|
| "Which product has the highest average unit price?" | no | answered | 7.11 s | 1,983 ms | 1 | n/a |
| "Plot total units sold per region as a bar chart." | yes | answered | 5.31 s | 1,858 ms | 1 | **yes** -- `800x600` PNG, 19,860 bytes |

Both questions answered correctly on the first attempt (no repair loop
exercised). Totals for this smoke run: 4 LLM requests, 2 sandbox runs
(well inside this task's 12-request/8-run live budget), sandbox spend
≈ $0.00026 (from `runs/api-smoke/sandbox_ledger.jsonl`, not committed).
The chart question's script called `plt.show()` rather than
`plt.savefig(...)` and the chart still came back -- confirming the
sandboxed runner (`sandbox/runner.py`) captures every open matplotlib
figure itself, regardless of how the script ends.

Verified live during this run: `GET /api/health` (status/provider/model/
sandbox, no secrets); `POST /api/examples/sales/load`; `POST /api/runs`;
`GET /api/runs/{id}/events` (SSE, full replay-to-`run_finished`);
`GET /api/runs/{id}` (final summary matched the SSE stream's own
`answer`/`evidence` events); `GET /api/runs/{id}/artifacts/{name}`
(served a real, valid PNG); `GET /api/runs/{id}/trace` (13-line JSONL
download, last line `run_finished`). The server was then stopped
(`Stop-Process`) and a follow-up request to `/api/health` confirmed it
was no longer listening.
