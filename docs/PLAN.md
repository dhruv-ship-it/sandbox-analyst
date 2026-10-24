# PLAN.md

Phased plan with an exit check for each phase. See `DECISIONS.md` for the
reasoning behind individual choices referenced here.

## Reorder (2026-10-25)

A resume deadline moved P4 (API) and P5 (deploy) ahead of P3
(guardrail hardening) and P6 (freeze + held-out run) -- see D-064. The
new order is: ship a public demo now, keep improving the agent behind
that stable URL, then harden and freeze. The sections below are listed
in that new execution order; each phase keeps its original P-number so
existing `DECISIONS.md` references stay valid. Nothing about the
agent's own behavior changes because of this reorder (D-064) -- the
deployed system is the evaluated system until the freeze.

## P0 — Setup (done)

Scaffold the repo, settings, docs, sandbox interface, static checker,
and minimal CI.

**Exit check:** The NVIDIA key (for `gpt-oss-20b`) and Modal auth both
work; the repo, `CLAUDE.md`, `DECISIONS.md`, and `notes/` exist.

## P1 — Core agent loop (done, no API, no UI yet)

Sandbox interface (done in P0), static checker (done in P0), LLM wrapper
with record/replay for tests, DABench download + dev split, the agent
loop (write -> check -> run -> repair, max 3 repairs), evidence check,
trace recording, and a CLI.

**Exit check:** The CLI answers 5 dev-set questions end to end on Modal;
all unit tests pass using fakes (no network).

## P2 — DABench harness (done)

Run the agent loop across the full dev split and report numbers.

**Exit check:** Dev-set numbers with confidence intervals for
single-shot vs. up-to-1/2/3-repair accuracy; runtime-error rate; token
usage and latency per question. (2 of 3 planned dev runs recorded so
far -- `docs/results-dev.md`, D-063.)

## P4 — API and UI (API done; UI is Prompt 6)

FastAPI app with Server-Sent Events for the step timeline (done --
`src/sandbox_analyst/api/`, `docs/api.md`); React (Vite) frontend
(not started -- `GET /` serves a placeholder page until then); trace
display.

**Exit check:** The live step timeline (code written -> checked -> run
-> result) works end to end locally. Met for the API (verified with a
real Groq + Modal smoke run, `docs/api.md`); the UI's own version of
this check is Prompt 6's.

## P5 — CI and deploy (CI done; the Azure resource is created by hand)

CI with a deterministic evaluation smoke test (recorded responses, not
live DABench) -- done, predates this reorder. A Dockerfile, a GHCR push
workflow, and deployment to an Azure Web App -- done in this session
(`Dockerfile`, `.github/workflows/ci.yml`'s `image`/`deploy-azure`
jobs, `docs/deploy.md`); the Web App resource itself is created by hand
in the Azure portal, per `docs/deploy.md`, not by this repo's tooling.

**Exit check:** Public URL live; CI green.

## Dev improvements (ongoing, behind the live demo)

Once the demo is live, continue improving the agent (prompts, repair
logic, evidence checking, ...) with each push to `main` redeploying to
the same URL (automatically if Azure continuous deployment is
configured, per `docs/deploy.md`, otherwise via a manual restart). No
evaluation run happens during this window -- the deployed agent and the
agent that gets measured at the freeze stay identical by construction
(D-064). One standing rule carried over from P2: don't change
dependencies while a long evaluation is running in the same
environment.

## P3 — Guardrail hardening and red-team suite (next, after dev improvements)

Red-team the static checker and the sandbox, each with the other layer
disabled. Optional Docker backend (insurance only, see D-008 — first
thing cut if behind schedule).

**Exit check:** A report of "handled N of M" attack attempts per
category, plus the checker's false-positive rate on benign dev-set
tasks.

## P6 — Freeze and held-out evaluation (last)

Freeze the system at a `frozen-*` tag, run the held-out evaluation once
(3 full runs, bootstrap 95% CIs, see D-013), write up the README and
resume bullets.

**Exit check:** Evaluation report with confidence intervals published;
README written; resume bullets use only numbers from that report.
