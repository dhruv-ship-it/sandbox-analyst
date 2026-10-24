# PLAN.md

Phased plan with an exit check for each phase. See `DECISIONS.md` for the
reasoning behind individual choices referenced here.

## P0 — Setup

Scaffold the repo, settings, docs, sandbox interface, static checker,
and minimal CI.

**Exit check:** The NVIDIA key (for `gpt-oss-20b`) and Modal auth both
work; the repo, `CLAUDE.md`, `DECISIONS.md`, and `notes/` exist.

## P1 — Core agent loop (no API, no UI yet)

Sandbox interface (done in P0), static checker (done in P0), LLM wrapper
with record/replay for tests, DABench download + dev split, the agent
loop (write -> check -> run -> repair, max 3 repairs), evidence check,
trace recording, and a CLI.

**Exit check:** The CLI answers 5 dev-set questions end to end on Modal;
all unit tests pass using fakes (no network).

## P2 — DABench harness

Run the agent loop across the full dev split and report numbers.

**Exit check:** Dev-set numbers with confidence intervals for
single-shot vs. up-to-1/2/3-repair accuracy; runtime-error rate; token
usage and latency per question.

## P3 — Guardrail hardening and red-team suite

Red-team the static checker and the sandbox, each with the other layer
disabled. Optional Docker backend (insurance only, see D-008 — first
thing cut if behind schedule).

**Exit check:** A report of "handled N of M" attack attempts per
category, plus the checker's false-positive rate on benign dev-set
tasks.

## P4 — API and UI

FastAPI app with Server-Sent Events for the step timeline; React (Vite)
frontend; trace display.

**Exit check:** The live step timeline (code written -> checked -> run
-> result) works end to end locally.

## P5 — CI and deploy

CI with a deterministic evaluation smoke test (recorded responses, not
live DABench), a Dockerfile, a GHCR push workflow, and deployment to an
Azure Web App.

**Exit check:** Public URL live; CI green.

## P6 — Freeze and held-out evaluation

Freeze the system at a `frozen-*` tag, run the held-out evaluation once
(3 full runs, bootstrap 95% CIs, see D-013), write up the README and
resume bullets.

**Exit check:** Evaluation report with confidence intervals published;
resume bullets use only numbers from that report.
