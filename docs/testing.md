testing.md

What this project's automated tests actually cover, and the one piece
that's a deliberate exception to "unit tests never touch the network"
(CLAUDE.md rule 6): the replay regression suite.

## The three layers

1. **Unit tests** (`tests/`, excluding `tests/replay/`) — fast, fully
   offline, using `FakeLLM`/`FakeSandbox` or fakes of real SDK objects.
   Marked `live` tests (real Modal/NVIDIA/Groq calls) are excluded by
   default (`pyproject.toml`'s `addopts`).
2. **The replay regression suite** (`tests/replay/`) — also fully
   offline and runs in CI by default, but it replays *real, once-
   recorded* LLM and sandbox responses rather than hand-written fakes.
   Covered below.
3. **Live smoke/eval/red-team runs** (`sa dabench-smoke`, `sa eval`,
   `sa redteam`, `sa record-replay`) — real network calls, run by hand,
   never in CI.

## What the replay suite covers

`sa record-replay` (manual, live, costs money) runs 10 hand-written
questions over our own synthetic example datasets (`sales.csv`,
`students.csv`, `weather.csv` — never DABench data) once each, through
the REAL agent loop, with the real LLM wrapped in `RecordingLLM` and a
real Modal sandbox wrapped in `RecordingSandbox`
(`src/sandbox_analyst/sandbox/record.py`, mirroring `llm/record.py`'s
shape, D-038). Every LLM call and every sandbox `run()` call is appended
to a cassette (`tests/replay/cassettes/llm.jsonl` /
`sandbox.jsonl`), keyed by a hash of its own request content — the LLM
cassette by `(provider, model, messages, sampling params)`, the sandbox
cassette by `(code, the name+size of every file uploaded so far)`. The
command also scans both cassettes for credential-shaped substrings
(`ak-`, `as-`, `gsk_`, `nvapi-`) and refuses to finish if it finds any,
and writes a snapshot of what actually happened
(`tests/replay/recorded_results.json`: final status, final answers, and
the event-type sequence per task).

`tests/replay/test_replay.py` (an ordinary pytest, runs in CI, no
network) replays every task through the same real `run_agent` call, but
with `ReplayLLM`/`ReplaySandbox` serving the frozen cassette entries
instead of a network/sandbox call. For each task it asserts:

- the final **status** matches what was recorded;
- the final **answers** match what was recorded;
- the **event-type sequence** (the shape of `run_started` → `profile` →
  `llm_request`/`llm_response` → `code` → `static_check` → ... →
  `run_finished`) matches what was recorded;
- the answer **matches ground truth** computed by trusted host-side
  pandas code (`scripts/make_replay_truth.py`, over the same example
  CSVs — never model-written, never executed by the agent), checked
  with the DABench grader's own tolerant matching
  (`bench.grader.grade_question`, mode `"tolerant"`) so the comparison
  tolerates the same formatting/rounding slack the real benchmark does.

This catches real regressions in **our own code** — the agent loop's
control flow, evidence checking, answer parsing, prompt construction —
because all of that code runs for real against the frozen cassette
inputs. Two tests
(`test_replay_suite_catches_a_broken_evidence_check`,
`test_replay_suite_catches_a_broken_answer_parser`) deliberately
monkeypatch `agent.loop.check_evidence` / `agent.loop.parse_final_answer`
to prove the suite actually notices: either assertion fails outright, or
the broken code path tries to make a call the frozen cassette was never
recorded for (`CassetteMiss`/`SandboxCassetteMiss`), which `replay_task`
reports as "not ok" rather than letting it crash the test uninformatively.

## What it does NOT cover

The replay suite says nothing about **model quality**. The model's own
responses are frozen into the cassette at record time — a worse or
better model, or the same model answering differently on a different
day, would never be caught by replay, because replay never calls a real
model again. That's measured by the held-out DABench evaluation
(`docs/results-heldout.md`) instead, which *does* call the real model
every time.

Any intentional change to a prompt (`agent/prompts.py`), to
`agent/answer.py`'s name normalization, or to anything else that
changes what messages get sent to the LLM or what code gets sent to the
sandbox, changes the cassette keys — **by design**. The replay suite
will then raise `CassetteMiss`/`SandboxCassetteMiss` for every affected
task, not silently pass with stale data. That failure is the point: it
forces a deliberate, reviewed re-record (not an automatic one) before
the change can land, so nobody merges a prompt change without a human
re-checking that the 10 tasks still behave correctly against the real
model.

## Re-recording

Required whenever a change touches what's sent to the LLM or to the
sandbox (a prompt change, an answer-parsing change, a new checker rule
that would reject one of the 10 tasks' generated code, …):

```powershell
$env:SA_LLM_PROVIDER = "groq"
$env:SA_LLM_MODEL = "openai/gpt-oss-20b"
$env:SA_SANDBOX = "modal"
uv run sa record-replay
```

This costs real LLM requests and real Modal sandbox runs — review the
printed per-task status and repair count, confirm the credential scan
passed, and diff the new cassettes/`recorded_results.json` before
committing them.
