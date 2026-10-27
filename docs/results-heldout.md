# results-heldout.md

**The held-out evaluation. Final.** One session, three full runs on the
held-out test split, after freezing the system at a tagged commit — not
iterated on afterward (D-013). TEST split only (`eval/split.json`, 183
questions / 41 files); no TEST question, label, or CSV content appears
anywhere below, per CLAUDE.md's test-set-discipline rule — only counts,
aggregate scores, and confidence intervals.

**Frozen tag:** `frozen-v1` — SHA `296de20af658baecfe4f115ec3cfe305ef1be545`.
**Model:** `openai/gpt-oss-20b`. **Provider:** NVIDIA NIM (`nim`).
**PROMPT_VERSION:** `v2`. **Dates (UTC):** 2026-10-26, 19:58–21:19.
**Number of runs:** 3 (`test-v2-r1`, `test-v2-r2`, `test-v2-r3`).

Every run's manifest records the identical `git_sha` (`296de20...`) and
`split_hash` (`405f0750...`) — nothing in the frozen tree moved between
runs. Full frozen configuration: `DECISIONS.md` D-109.

| Run | Date (UTC) | n | answered |
|---|---|---|---|
| test-v2-r1 | 2026-10-26T19:58:12Z | 183 | 177 |
| test-v2-r2 | 2026-10-26T20:43:23Z | 183 | 181 |
| test-v2-r3 | 2026-10-26T21:18:49Z | 183 | 180 |

Report built with `uv run sa report test-v2-r1 test-v2-r2 test-v2-r3`; full
output in `runs/eval/test-v2-r1+test-v2-r2+test-v2-r3/report.{md,json}`
(gitignored, not committed — every number below is transcribed from that
real run, not estimated). No infra events occurred during any of the 3
runs (0 infra_error across all 549 question-attempts; see "Errors" below).

## Pooled accuracy (3 runs, paired by question)

| Metric | Strict | Tolerant |
|---|---|---|
| ABQ | **0.750** (95% CI 0.694–0.805) | **0.818** (95% CI 0.765–0.869) |
| PSAQ | 0.806 (95% CI 0.758–0.850) | 0.847 (95% CI 0.802–0.891) |
| UASQ | 0.797 (95% CI 0.745–0.848) | 0.843 (95% CI 0.792–0.893) |

Per-run ABQ: test-v2-r1 = 0.760 strict / 0.820 tolerant (177/183 answered);
test-v2-r2 = 0.754 strict / 0.825 tolerant (181/183 answered); test-v2-r3 =
0.738 strict / 0.809 tolerant (180/183 answered). Mean/range across the 3
runs (tolerant ABQ): 0.818 (0.809–0.825); (strict ABQ): 0.750 (0.738–0.760).

## Truncation ablation (pooled)

The accuracy if the agent had stopped after attempt *k* (the answer from
the first fully-evidenced attempt at or before *k*), computed by cutting
the same recorded traces rather than re-running the benchmark once per
repair budget (D-014):

| k | Strict ABQ | 95% CI | Tolerant ABQ | 95% CI |
|---|---|---|---|---|
| k=1 (single-shot) | 0.699 | 0.639–0.758 | 0.765 | 0.707–0.821 |
| k=2 | 0.747 | 0.690–0.801 | 0.814 | 0.761–0.865 |
| k=3 | 0.749 | 0.692–0.803 | 0.816 | 0.763–0.867 |
| k=4 (= headline) | 0.750 | 0.694–0.805 | 0.818 | 0.765–0.869 |
| unverified single-shot | 0.705 | 0.645–0.763 | 0.778 | 0.721–0.832 |

### Paired lift, k=4 minus k=1

Produced by `uv run sa report test-v2-r1 test-v2-r2 test-v2-r3` itself (the
same command that built every other number on this page) — paired by
question, pooled across the 3 runs, 10,000-resample bootstrap over
questions, the same resampling scheme `bench.stats.paired_bootstrap_ci`
already uses elsewhere in this project (D-062), now via
`bench.report.paired_lift` (D-112):

| Mode | Paired lift (ABQ) | 95% CI |
|---|---|---|
| strict | **+0.051** | **(0.027, 0.080)** |
| tolerant | **+0.053** | **(0.027, 0.082)** |

Both CIs exclude zero: on this held-out split, letting the agent repair up
to 3 times (vs. judging it on attempt 1 alone) is a real, statistically
significant accuracy gain — not noise.

## Errors and repair

- Runtime-error rate per attempt: **0.092**
- % of tasks with at least one error: **0.086**
- Attempt-1-errored tasks: **45** of 549. Of those, resolved (reached
  `answered`) within:

  | Within N attempts | Fraction | 95% CI |
  |---|---|---|
  | 2 | 0.711 | 0.578–0.844 |
  | 3 | 0.844 | 0.733–0.933 |
  | 4 | **0.867** | **0.756–0.956** |

- Static-checker block rate per attempt: attempt 1 = 0.009, attempt 2 =
  0.017, attempt 3 = 0.0, attempt 4 = 0.0 (6 blocked attempts total, out of
  622 total attempts)
- Evidence-failure rate: **0.029**
- Status distribution (3 runs pooled, 549 tasks): answered 538,
  budget_exceeded 7, repeated_failure 4
- infra_error count: **0** (no provider or sandbox infrastructure failures
  across any of the 3 runs)

## Cost and speed (per task, 3 runs pooled)

| Metric | Mean | p50 | p95 |
|---|---|---|---|
| Tokens | 3323 | 2845 | 5761 |
| LLM latency (ms) | 69,935 | 57,187 | 152,728 |
| Wall time (ms) | 96,482 | 75,593 | 222,265 |

Sandbox spend: mean $0.000230/task, **$0.126 total** across all 3 runs'
real sandboxes. LLM requests: mean 2.20/task, 1209 total (per the eval
harness's own per-question count); the raw NVIDIA usage log
(`runs/llm_usage.jsonl`) grew by 1247 lines across the same 3 runs — the
harness's count is of `llm_request` events emitted by the agent loop
itself, the usage log also captures the client's own internal retry
attempts, so a small gap between the two is expected, not a discrepancy.

## Per level

| Level | n | Strict ABQ | 95% CI | Tolerant ABQ | 95% CI |
|---|---|---|---|---|---|
| easy | 61 | 0.847 | 0.760–0.923 | 0.907 | 0.831–0.973 |
| medium | 62 | 0.785 | 0.688–0.871 | 0.839 | 0.747–0.919 |
| hard | 60 | 0.617 | 0.506–0.722 | 0.706 | 0.594–0.806 |

## Not comparable: the original DABench paper's numbers

The InfiAgent-DABench paper reports GPT-4 at 78.99% and GPT-3.5 at 60.70%
(its own accuracy metric) using its own grader — a GPT-3.5-based answer
reformatter plus regex matching. This project's grader
(`src/sandbox_analyst/bench/grader.py`) is a separate implementation,
designed and tested against only this project's own dev-split labels
(D-015), and this project's agent is a different system entirely (its own
sandboxed write→check→run→repair loop, not the paper's own method). Those
published numbers are **context only** — not a baseline this project's
numbers should be read as beating, matching, or falling short of.

## What this run did not do

No prompt, sampling, or agent-logic change was made in response to any
number above, during or after these 3 runs (CLAUDE.md's no-tuning rule,
D-108's same principle extended from the red-team suite to the held-out
split). These are the only 3 held-out runs this project will ever report
for `frozen-v1` — see D-013 for why the evaluation happens once, not
iteratively.
