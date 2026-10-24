# smoke-p1.md

The P1 exit check: `uv run sa dabench-smoke --n 5 --seed 2026`, run once,
for real, against NVIDIA NIM (`openai/gpt-oss-20b`) and a real Modal
sandbox. DEV split only (`eval/split.json`); no TEST question, label, or
CSV content appears anywhere below or was inspected while producing this
file, per CLAUDE.md's test-set-discipline rule.

## Run

**Date:** 2026-10-24. **Command:** `uv run sa dabench-smoke --n 5 --seed 2026`.
**Provider/model:** NIM, `openai/gpt-oss-20b` (`llm_reasoning_effort=medium`,
the project defaults -- D-036). **Sandbox:** Modal, real (gVisor,
`block_network=True`). Run exactly once; nothing below was used to tune
a prompt or retry the run.

```
   id  level  status           attempts  predicted | label
   58  easy   answered                1  @@percentage_cases_min[36.45] @@percentage_deaths_max[38.79] | @percentage_cases_min[36.45] @percentage_deaths_max[38.79]
   55  easy   answered                1  @@mean_cases[2081990] | @mean_cases[2081990]
   69  medium answered                1  @@correlation[0.252] | @correlation[0.252]
  179  medium answered                1  @@correlation_coefficient[-0.123] | @correlation_coefficient[-0.123]
  275  hard   answered                1  @duplicate_count[0] @usflux_mean[7.463837954032957e+21] @new_feature_mean[-89.04] @model_accuracy[99.746] | @duplicate_count[0] @new_feature_mean[-89.04]

answered 5/5  mean_tokens=3220  mean_latency_ms=53833  sandbox_est_usd=$0.0002  llm_requests_used=12
```

## Totals

| Metric | Value |
|---|---|
| Answered | 5/5 |
| Attempts used (all 5 questions) | 1 of up to 4 (single-shot every time) |
| Mean tokens per task (prompt + completion) | 3220 |
| Mean LLM latency per task (summed across that task's calls) | 53,833 ms |
| Sandbox spend (lower-bound estimate, D-007) | $0.0002 |
| LLM requests used (usage-log line count, this run) | 12 |

This is a human-eyeball smoke check, not a grader (by design -- see
`cli.cmd_dabench_smoke`'s docstring and D-052): "predicted" and "label"
are printed side by side for a person to read, with no pass/fail scoring
applied here.

## What actually happened

Read from `runs/llm_usage.jsonl` and `runs/sandbox_ledger.jsonl` (both
local, gitignored, never committed) for this run's entries.

- All 5 questions were answered correctly on the **first attempt** --
  no repair loop was exercised by this particular sample. That's a
  property of this specific seeded selection, not a claim about the
  system's repair-loop behavior in general (P2's full dev-split run is
  what will actually measure single-shot vs. up-to-N-repair accuracy,
  per D-014).
- `llm_requests_used=12`, not the "expected" 10 (5 questions x {1
  code-gen call, 1 answer call}), because NIM's endpoint hit two
  **`APITimeoutError`s** (120 s each) during this run, both
  transparently retried and succeeded inside `OpenAICompatClient`'s own
  retry policy (D-037) -- each timeout writes its own failed usage-log
  line before the successful retry's line, adding 2 extra lines.
  Neither one ever reached `run_agent` as a failure, and neither counts
  as an agent-level ATTEMPT. This is the first real-world confirmation
  that retry path actually fires in practice, not just in the live
  unit tests.
- The last 5 `sandbox_ledger.jsonl` entries (one per question, matching
  5 single-attempt execs) have `alive_s` (full sandbox lifecycle --
  create, exec, terminate) of 8.7-11.9 s each, summing to an actual
  ledger cost of **$0.000797** for this run's real sandboxes.
- The CLI's own printed `sandbox_est_usd=$0.0002` is a *different,
  smaller* number than that $0.000797 ledger figure, and re-checking
  the two sources against each other surfaced a real gap worth
  recording: `AgentResult.sandbox_est_usd` (D-049) estimates each
  attempt's cost from `ExecResult.duration_ms` -- the `sandbox.exec()`
  call's own duration only -- while the ledger's `alive_s`
  (`ModalSandbox.run()`'s own measurement) spans the sandbox's whole
  lifecycle: creation, exec, and termination. The per-attempt estimate
  in `AgentResult` is therefore missing the sandbox creation/teardown
  overhead, making it a tighter lower bound than D-049's write-up
  assumed -- still correctly a lower bound (per D-007's own framing),
  just a looser one than "exec time at the configured reservation
  rate" suggests. Either figure is four to five orders of magnitude
  under the $0.80 budget cap; this is a documentation gap to fix
  (clarify D-049, or compute the estimate from the sandbox's own
  lifetime), not a budget risk, so it is recorded here rather than
  patched mid-session.

## One cosmetic observation (not fixed this session, by design)

The printed "predicted" column shows a doubled `@@` for most sub-answers
(e.g. `@@percentage_cases_min[36.45]`) where the "label" column shows a
single `@`. This is because the model sometimes puts the leading `@`
*inside* the JSON `name` field itself (e.g. `"name": "@percentage_cases_min"`)
rather than the bare tag name the grader will expect, and
`cli.cmd_dabench_smoke`'s row formatting always prepends its own `@`
unconditionally. This is not a crash in our code (`CLAUDE.md`'s only
stated bar for an in-session fix), it doesn't affect evidence checking
(which only ever reads `answer.value`, never `answer.name`), and fixing
either the prompt wording or the CLI's display would be tuning based on
this exact smoke run's output -- explicitly out of scope for this
session. Left as a note for the grader task (which will need to decide
how strictly it matches `@name` against the format string's own
placeholders) and for a future prompt-wording pass.

Likewise, question 275 (hard) answered two extra sub-answers
(`usflux_mean`, `model_accuracy`) beyond the two the label has
(`duplicate_count`, `new_feature_mean`) -- the model answered more of
the question than the label scores for. Again: a modeling-quality
observation, not a bug, and not touched this session.

## Exit check

CLI answers 5 DEV-set questions end to end on real Modal + NIM: **met**.
All unit tests pass using fakes (no network): **met** (see the task's
final summary message for the exact count).
