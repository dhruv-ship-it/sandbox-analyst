# results-dev.md

Measured DEV-split numbers from the P2 session. **Not final results** --
this is 2 of the planned 3 full dev runs (see D-063: the third run,
`dev-v1-r3`, was deferred mid-run by the project lead's own call, not
by any code-level stop condition). DEV split only (`eval/split.json`,
74 questions); no TEST question, label, or CSV content appears
anywhere below, per CLAUDE.md's test-set-discipline rule.

**Model:** `openai/gpt-oss-20b` on NVIDIA NIM (`reasoning_effort=medium`,
D-036). **Provider:** `nim`. **PROMPT_VERSION:** `v1`. **Sandbox:**
Modal (gVisor, `block_network=True`), image pins pandas==3.1.0,
numpy==2.5.4, scipy==1.18.1, scikit-learn==1.9.1, statsmodels==0.15.0,
matplotlib==3.11.2, seaborn==0.13.2. **DABench revision:**
`b455d578e30fee513abd79936cbdf7a6de026cb5`.

| Run | Date (UTC) | git SHA |
|---|---|---|
| dev-v1-r1 | 2026-10-24T15:51:09Z | `bc6beea4fd5e3b3c7230ddd697640c073d2c4762` |
| dev-v1-r2 | 2026-10-24T16:12:15Z | `bc6beea4fd5e3b3c7230ddd697640c073d2c4762` |

Report built with `uv run sa report dev-v1-r1 dev-v1-r2`; full output
in `runs/eval/dev-v1-r1+dev-v1-r2/report.md` / `report.json`
(gitignored, not committed -- the numbers below are transcribed from
that real run, not estimated).

## Why only 2 of 3 runs

`dev-v1-r1` took ~21 minutes wall-clock (74 questions, concurrency 6).
`dev-v1-r2` took ~110 minutes -- NIM was noticeably slower during that
window, with frequent `APITimeoutError`s hitting the (data-derived,
D-056) 142s per-call timeout before succeeding on retry. With `dev-v1-r3`
projected to cost another 20-110+ minutes of uncertain real time, the
project lead chose to stop there rather than let it run unattended
further: `dev-v1-r3` was killed in progress (3/74 questions already
recorded) and deferred. `runs/eval/dev-v1-r3/results.jsonl` already
has those 3 questions recorded, so resuming is a single command away:

```powershell
uv run sa eval --split dev --run-name dev-v1-r3
```

This resumes automatically -- it skips the 3 already-recorded
(non-`infra_error`) ids and continues with the remaining 71 -- and
`uv run sa report dev-v1-r1 dev-v1-r2 dev-v1-r3` then gives the full
3-run picture once it finishes. See D-063.

## Pooled accuracy (2 runs, paired by question)

| Metric | Strict | Tolerant |
|---|---|---|
| ABQ | 0.716 (95% CI 0.628-0.797) | 0.777 (95% CI 0.696-0.851) |
| PSAQ | 0.759 (95% CI 0.679-0.837) | 0.803 (95% CI 0.727-0.874) |
| UASQ | 0.760 (95% CI 0.671-0.838) | 0.802 (95% CI 0.717-0.879) |

Per-run ABQ: dev-v1-r1 = 0.743 strict / 0.797 tolerant (72/74
answered); dev-v1-r2 = 0.689 strict / 0.757 tolerant (71/74 answered).
Mean/range across the 2 runs (tolerant ABQ): 0.777 (0.757-0.797).

## Truncation ablation (tolerant, pooled)

The accuracy if the agent had stopped after attempt *k* (the answer
from the first fully-evidenced attempt at or before *k*), computed by
cutting the same recorded traces rather than re-running the benchmark
once per repair budget (D-014):

| k | Pooled ABQ | 95% CI |
|---|---|---|
| k=1 (single-shot) | 0.743 | 0.655-0.824 |
| k=2 | 0.770 | 0.682-0.851 |
| k=3 | 0.770 | 0.682-0.851 |
| k=4 (= headline) | 0.777 | 0.696-0.851 |
| unverified single-shot | 0.743 | 0.655-0.824 |

Strict-mode ablation lands 0.056-0.061 lower at every k (0.682 / 0.709
/ 0.709 / 0.716), the same shape. "Unverified single-shot" (attempt
1's answer even when its own evidence check failed) scores identically
to verified k=1 here -- in this sample, every attempt-1 answer that
later needed a repair was in fact caught by the evidence check, not
let through wrong.

## Errors and repair

- Runtime-error rate per attempt: **0.078**
- % of tasks with at least one error: **0.068**
- Of attempt-1-errored tasks, resolved within 2 / 3 / 4 attempts:
  **0.556 / 0.667 / 0.889**
- Static-checker block rate per attempt: attempt 1 = 0.007, attempt 2 =
  0.167, attempt 3 = 0.500, attempt 4 = 0.333 (6 blocked attempts
  total -- every one is listed with its trace path in
  `runs/eval/<run>/failures.md`-adjacent harness output for P3 review;
  none inspected here beyond the count, per the no-tuning-this-session
  rule)
- Evidence-failure rate: **0.027**
- Status distribution (both runs pooled, 148 tasks): answered 143,
  budget_exceeded 3, failed 1, repeated_failure 1
- infra_error count: **0** (no provider or sandbox infrastructure
  failures recorded across either run)

## Cost and speed (per task, both runs pooled)

| Metric | Mean | p50 | p95 |
|---|---|---|---|
| Tokens | 3173 | 2869 | 5078 |
| LLM latency (ms) | 78,326 | 62,749 | 170,994 |
| Wall time (ms) | 267,347 | 97,297 | 458,552 |

Sandbox spend: mean $0.000173/task, **$0.0257 total** across both
runs' real sandboxes -- four orders of magnitude under the $0.80
ledger cap. LLM requests: mean 2.18/task, 323 total across both runs.

## Per level (tolerant ABQ)

| Level | n | ABQ | 95% CI |
|---|---|---|---|
| easy | 21 | 0.857 | 0.738-0.952 |
| medium | 25 | 0.780 | 0.640-0.900 |
| hard | 28 | 0.714 | 0.571-0.857 |

## Not done this session

No prompt, sampling, or agent-logic change was made in response to any
number above (NO TUNING, per this session's own rule). The 6
checker-blocked attempts are candidates for P3's false-positive
review, not acted on here.
