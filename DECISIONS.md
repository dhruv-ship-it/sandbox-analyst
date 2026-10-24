# DECISIONS.md

One entry per design decision, in plain English. Dated by when the decision
was made (not necessarily when it was written down).

## D-001 — Project name and licensing

**Date:** 2026-10-24

**Decision:** Name the project "Sandbox Analyst", repo
`dhruv-ship-it/sandbox-analyst`, public, MIT licensed.

**Why:** The name says what it does — it is an AI analyst that works
inside a sandbox.

**Alternatives rejected:** none considered seriously; naming is not a
load-bearing decision here.

## D-002 — Stack

**Date:** 2026-10-24

**Decision:** Python 3.12 + uv, FastAPI, React (Vite). No agent/RAG
frameworks (LangChain, LlamaIndex, CrewAI, ...). The `openai` Python SDK
is used only as an HTTP client for OpenAI-compatible providers (NVIDIA
NIM, Groq), not as a framework.

**Why:** The project's point is to demonstrate hand-rolled agent-loop and
sandboxing logic, not framework usage. uv gives fast, reproducible
dependency resolution.

**Alternatives rejected:** LangChain/LlamaIndex-style frameworks — they
would hide the exact mechanics (prompt construction, repair loop,
evidence checking) that this project exists to show.

## D-003 — Model: openai/gpt-oss-20b

**Date:** 2026-10-24

**Decision:** Use `openai/gpt-oss-20b` for every headline benchmark
number AND the live demo (provisional until the provider key check
passes).

**Why:** `openai/gpt-oss-120b` was retired from NVIDIA's free endpoints
on 2026-09-03 (HTTP 410 Gone). `gpt-oss-20b` is a current NVIDIA free
endpoint and is also available on Groq's free plan, so the evaluated
model is the same model used in the live demo.

**Trade-off:** Lower absolute accuracy than larger models.

**Alternatives rejected:**
- Larger NVIDIA-only models (Nemotron 3 Ultra, DeepSeek V4.1 Flash,
  GLM 5.3 Flash): the live demo could not use the same model, since
  they are not available on Groq.
- Groq `gpt-oss-120b`: its free quota is already shared with the
  ZoneWise project.
- Cerebras: requires a card on file, 30-day free-tier expiry.
- Gemini: roughly 20 requests/day on the free tier — too tight for
  benchmark runs.
- Mistral free tier: requires training-data opt-in.

## D-004 — Providers

**Date:** 2026-10-24

**Decision:** Evaluation runs against NVIDIA's free API (its terms
permit testing/evaluation, not production; no daily token cap; ~40
requests/min). The live demo runs against Groq (per-model free quota,
separate from ZoneWise's `gpt-oss-120b` usage; a daily run cap applies).
Every reported number names its provider, model, and date. The LLM
client is provider-agnostic so a retired model is a config change, not a
code change.

**Why:** Free-tier availability and rate limits differ by provider;
splitting evaluation and demo traffic across two providers avoids
hitting either one's cap, while using the same model keeps the
evaluated system identical to the demoed system.

**Alternatives rejected:** Single-provider setup — rejected because no
single free tier covers both bulk evaluation traffic and demo-time
responsiveness for this model.

## D-005 — Sandbox: Modal Sandboxes (gVisor)

**Date:** 2026-10-24

**Decision:** Use Modal Sandboxes (gVisor-isolated) for development,
evaluation, and production execution of model-written code.

**Why:**
- E2B blocked all API use behind a $5 card-verification requirement at
  signup (checked 2026-10-24), despite its pricing page advertising a
  free tier.
- Modal gives $1 of free credit with no card on file (a further
  $29/month tier needs a payment method); without a card, Modal stops
  workloads instead of billing an unbound amount.
- `block_network=True` drops all outbound traffic, including DNS.
- The sandbox image is defined in code with pinned packages and built
  remotely by Modal, not on the host.

**Alternatives rejected:**
- E2B: card required to use the API at all.
- Azure Container Apps dynamic sessions: Hyper-V isolation, but billed
  at $0.03 per session in 1-hour increments, drawn from the same
  student credit that hosts the ZoneWise project, and packages cannot
  be pinned in the session image. Kept as the documented fallback
  (see D-008's sibling note below — Docker, not this — this option has
  no code in the repo).
- Local Docker: large host install, shares the host kernel (weaker
  isolation than gVisor), and cannot run on Azure App Service.

## D-006 — Execution model

**Date:** 2026-10-24

**Decision:** Every attempt runs a complete script in a fresh sandbox,
through a trusted runner (`runner.py`, copied into the sandbox image)
that captures errors as structured JSON and saves matplotlib figures.
No hidden state carries between attempts; the evidence code shown to
the user is exactly what ran.

**Why:** Fresh-per-attempt execution makes failures reproducible and
means a crashed or timed-out attempt cannot corrupt the next repair
attempt. Structured JSON error capture (rather than parsing stderr text)
makes repair-loop error handling reliable.

**Alternatives rejected:** A long-lived REPL-style sandbox that persists
variables across repair attempts — rejected because it makes failures
stateful and harder to reproduce, and because the "evidence" shown to
the user would not match a single, complete, re-runnable script.

## D-007 — Cost design

**Date:** 2026-10-24

**Decision:** Sandboxes exist only while code is actually running (not
while the LLM is "thinking" between attempts). They reserve 0.25 CPU
core and 1 GiB memory, with bursting above the reservation allowed by
Modal. A local JSON-lines ledger caps estimated spend at $0.80 of the
$1 free credit. Estimates are cross-checked against Modal's usage page.

**Why:** Keeps the whole project inside Modal's no-card $1 free credit
while leaving a $0.20 margin for estimation error — the ledger's cost
estimate only counts the reservation, but bursting above it is billed
too, so the estimate is a lower bound on actual spend.

**Alternatives rejected:** Adding a card to unlock the $29/month paid
tier — rejected to keep the project's cost story at "$0 beyond existing
free tiers / student credit."

## D-008 — Docker backend (optional, insurance only)

**Date:** 2026-10-24

**Decision:** A Docker-based sandbox backend is optional scope in P3, as
insurance for heavy local evaluation runs, and the first thing cut if
the project falls behind schedule. If built, it is tested only in GitHub
Actions, never locally.

**Why:** Keeps a fallback path for high-volume benchmark runs without
requiring Docker on the development machine (violates the "keep host
dependencies small" rule otherwise).

**Alternatives rejected:** Making Docker a required backend — rejected,
conflicts with the goal of a small host footprint.

## D-009 — Security model

**Date:** 2026-10-24

**Decision:** The Modal sandbox (gVisor, no network) is the actual
security boundary. The AST-only static checker is defense in depth and
fast repair feedback for the agent, not the thing that makes untrusted
code safe to run. Each layer is red-teamed with the other layer
disabled. Known static-checker bypasses are documented rather than
hidden.

**Why:** AST-level checks can always be bypassed by sufficiently clever
Python (e.g., attribute-chain obfuscation, reflection). Treating the
checker as the security boundary would be a false sense of safety; the
sandbox's OS-level isolation and network block are what actually contain
a successful bypass.

**Alternatives rejected:** Relying on the static checker alone (no
sandbox) — rejected outright as unsafe. Relying on the sandbox alone (no
checker) — rejected because the checker gives much faster, cheaper
repair signal than waiting for a sandboxed failure.

## D-010 — Checker policy

**Date:** 2026-10-24

**Decision:** Import allowlist as enumerated in `policy.py`. Writes are
allowed only to literal string paths inside `/work` (relative without
`..`, or absolute under `/work`); reads are allowed anywhere, because the
sandbox holds no secrets. Dunder access (`__x__`) is blocked outright.
The allowlist grows only on false-positive evidence found during actual
dev-task runs, and each change is logged here.

**Why:** A narrow, explicit allowlist (data in `policy.py`, not scattered
logic) is easy to audit and easy to extend deliberately.

**Alternatives rejected:** A denylist-only approach for imports —
rejected because it is much easier to bypass (new unsafe modules just
aren't on the list yet) than an allowlist.

## D-011 — Benchmark

**Date:** 2026-10-24

**Decision:** Use the InfiAgent-DABench validation set from the Hugging
Face `infiagent/DABench` dataset at a pinned revision. Licensing is
treated as CC BY-NC 4.0 per the original paper authors' GitHub README,
even though the Hugging Face dataset card itself is tagged Apache-2.0 —
the stricter license is followed. The dataset is never committed to this
repo; it is downloaded by script.

**Why:** DABench is a known, automatically-graded benchmark for
CSV-question-answering agents, which fits this project's "measured on a
benchmark" goal.

**Alternatives rejected:** None seriously considered; DABench is the
standard benchmark for this task shape.

## D-012 — Split

**Date:** 2026-10-24

**Decision:** Split by CSV file (not by question) with a fixed random
seed; dev set is at least 20% of questions. The held-out test split only
loads when the working tree is clean and checked out at a `frozen-*` tag.

**Why:** Splitting by file (not by question) avoids leaking information
about a specific CSV's structure from dev into test, since multiple
questions can share a CSV. Gating test-split loading on a clean,
frozen tag makes it structurally hard to accidentally tune on the test
set.

**Alternatives rejected:** Splitting by question — rejected, leaks
per-file structure between dev and test.

## D-013 — Held-out evaluation

**Date:** 2026-10-24

**Decision:** One evaluation session on the frozen system: 3 full runs
on the test split, all three reported, with bootstrap 95% confidence
intervals. Nothing in the system changes between the three runs.

**Why:** A single LLM run proves nothing — LLM outputs are stochastic,
and sandboxed execution can have transient failures. Three runs with a
CI gives an honest uncertainty estimate instead of a single lucky (or
unlucky) number.

**Alternatives rejected:** Reporting a single run — rejected as
unreliable; this is a lesson carried over from the ZoneWise project.

## D-014 — Ablation

**Date:** 2026-10-24

**Decision:** Single-shot and up-to-1/2/3-repair accuracy are all
computed from the same recorded traces, by cutting each trajectory at
attempt *k*, rather than re-running the benchmark once per repair
budget.

**Why:** This is only valid because the agent is never told how many
repair attempts remain, so its behavior at attempt *k* doesn't change
based on the configured repair budget. Reusing traces this way saves
3-4x the evaluation cost and LLM-provider rate-limit budget.

**Alternatives rejected:** Running the benchmark separately once per
repair-budget setting — rejected as unnecessarily expensive given free-
tier rate limits.

## D-015 — Grader

**Date:** 2026-10-24

**Decision:** The grader is designed from dev-set labels; it must be
able to parse every dev label, but no grading rule is tuned against test
labels. It reports both a strict score and a tolerant score, with ABQ
(all sub-answers correct on a question) as the headline metric. The
original DABench paper's GPT-4/GPT-3.5 scores are reported only as
context, not as a direct comparison (different grader implementation,
different model generation).

**Why:** Keeps the grader honest (not overfit to test quirks) while
still being usable on every dev example.

**Alternatives rejected:** Tuning the grader against test labels for a
higher reported score — rejected, this is exactly the kind of test-set
leakage the project's rules exist to prevent.

## D-016 — CI and deploy

**Date:** 2026-10-24

**Decision:** CI's evaluation smoke test uses ~10 handwritten tasks on
synthetic CSVs with recorded (record/replay) LLM and sandbox responses —
never the real DABench data. Deployment is a single container (FastAPI
serving the built React app) as a second Azure Web App on the existing
B1 plan in the `zonewise-rg` resource group. Secrets, including
`MODAL_TOKEN_ID` / `MODAL_TOKEN_SECRET`, live in App Service application
settings. The image is built by GitHub Actions and pushed to GHCR.

**Why:** Keeps CI fast, deterministic, and free of live network/API
calls, while reusing existing paid-for infrastructure (the B1 plan)
instead of provisioning new paid resources.

**Alternatives rejected:** Running real DABench samples in CI —
rejected, too slow and non-deterministic for a CI gate.

## D-017 — Documentation

**Date:** 2026-10-24

**Decision:** Public documentation lives in `DECISIONS.md` plus `docs/`,
for engineering transparency. Private documentation lives in `notes/`
(journal, storyline, interview prep, concepts), is gitignored, and is
updated after every task so the full journey is recorded even though it
is never shared publicly.

**Why:** Separates "what and why, for anyone reading the repo" from
"the messy real story, for interview prep and personal record," without
either one compromising the other (no half-finished private thoughts in
public docs; no sanitized-only story in private notes).

**Alternatives rejected:** A single docs location — rejected, the two
audiences (public readers vs. interview-prep-Dhruv) need different
levels of candor and detail.

## D-018 — uv `--lib` scaffold

**Date:** 2026-10-24

**Decision:** Scaffolded the project with `uv init --lib`, which gives a
`src/sandbox_analyst/` layout with a `py.typed` marker directly, rather
than hand-building the src layout.

**Why:** Matches the requested src-layout exactly with less manual file
creation, and `py.typed` is harmless even though this project isn't
published as a typed library dependency for others yet.

**Alternatives rejected:** `uv init --package` (flat layout, no `src/`)
— rejected, doesn't match the requested src layout.

## D-019 — Settings field naming

**Date:** 2026-10-24

**Decision:** `Settings` fields use the exact snake_case form of each
env var (e.g. `sa_sandbox` for `SA_SANDBOX`, `sandbox_cpu` for an
unprefixed `sandbox_cpu`), relying on pydantic-settings' default
case-insensitive env-var matching rather than explicit `Field(alias=...)`
declarations. LLM provider fields (`sa_llm_provider`, `sa_llm_model`,
`nim_api_key`, `groq_api_key`) are modeled in `Settings` now, as
`SecretStr` for the two API keys, even though no LLM client code
consumes them yet — this guarantees that whenever that client is built,
the keys are never introduced as plain `str`.

**Why:** Keeping all configuration — including future secrets — in one
`Settings` class from the start means the "secrets are always
`SecretStr`" rule can be unit-tested now and never needs retrofitting.

**Alternatives rejected:** Leaving LLM fields out of `Settings` until the
LLM layer is built — rejected, `.env.example` already documents these
keys, and leaving them as untyped `extra="ignore"` values would mean
they could be loaded as plain strings by future code that doesn't go
through `Settings`.

## D-020 — Sandbox data types are plain frozen dataclasses, not pydantic

**Date:** 2026-10-24

**Decision:** `ExecError` and `ExecResult` are `@dataclass(frozen=True)`,
not pydantic models.

**Why:** These are internal, host-constructed evidence objects built
from already-trusted data (sandbox output after capping) — they are
never parsed from untrusted external input, so pydantic's validation
machinery adds nothing. `Settings` uses pydantic because it validates
and coerces values arriving from the environment.

**Alternatives rejected:** pydantic `BaseModel` for consistency with
`Settings` — rejected as unnecessary overhead for a value that's only
ever constructed in-process.

## D-021 — One shared `cap_exec_result` function, not per-field helpers

**Date:** 2026-10-24

**Decision:** All four output caps (stdout, stderr, traceback, images)
are applied by a single public function, `cap_exec_result(result) ->
ExecResult`, in `sandbox/base.py`, with private per-field helpers
underneath. The overall `truncated` flag is `True` if *any* of the four
caps actually fired (the task prompt only explicitly mentions
`truncated=True` for the stdout/stderr and image caps; traceback
truncation is folded into the same flag for consistency, since the flag
exists to tell the agent "some evidence here is incomplete").

**Why:** Every real sandbox backend needs to apply the exact same caps
before handing output to the agent; a single function makes that
contract impossible to apply inconsistently between backends.

**Alternatives rejected:** Separate `cap_stdout`/`cap_stderr`/etc.
functions called individually by each backend — rejected, that's how
you get one backend forgetting to cap something.

## D-022 — Upload validation raises `ValueError`, not `SandboxError`

**Date:** 2026-10-24

**Decision:** `validate_upload_name` / `validate_upload_size` raise
plain `ValueError` on bad input, rather than a `SandboxError` subtype.

**Why:** These catch programmer/caller mistakes (a bad file name or an
oversized upload chosen by calling code), not sandbox-infrastructure
failures. `SandboxError` and its subtypes are reserved for failures of
the sandbox itself (can't create it, it crashed, budget exhausted).

**Alternatives rejected:** A dedicated `UploadError(SandboxError)` —
possible later if callers need to catch upload problems alongside other
sandbox errors, but not justified yet by any actual caller.

## D-023 — `make_sandbox("fake")` returns an empty-script FakeSandbox

**Date:** 2026-10-24

**Decision:** The factory's "fake" branch returns a `FakeSandbox` with
no scripted results queued, built only from `settings.max_upload_mb`.
Tests that need specific scripted behavior construct `FakeSandbox`
directly instead of going through the factory.

**Why:** `make_sandbox(settings)` only has `Settings` to work with, which
has no concept of "what should this run return" — that's necessarily
supplied by the calling test or code, not by configuration.

**Alternatives rejected:** Making `make_sandbox` raise for "fake" and
requiring direct construction always — rejected, the factory should
still work end-to-end for wiring/smoke-test code that doesn't care about
specific results.

## D-024 — Sandbox image package pins resolved with `uv pip compile`, not memory

**Date:** 2026-10-24

**Decision:** The 7 pinned package versions in `modal_image.py`
(pandas, numpy, scipy, scikit-learn, statsmodels, matplotlib, seaborn)
were chosen by running `uv pip compile` against live PyPI metadata for
Python 3.12 with no version constraints, and taking the resolver's
output — not by recalling version numbers from training data.

**Why:** Package ecosystems move fast (this is the same lesson as
D-003's model retirement) and a resolver that actually queries the
index on the day the pins are written is strictly more trustworthy than
guessed version strings, especially for a 2026 "current" requirement.

**Alternatives rejected:** Picking versions from memory/training data —
rejected outright, likely to be stale or mutually incompatible by now.

## D-025 — An OOM-killed sandbox container is a `SandboxCrashed`, not a structured error

**Date:** 2026-10-24

**Decision:** No special-casing was added for out-of-memory behavior.
When a script exceeds the sandbox's hard memory limit, the *entire*
sandbox container disappears (confirmed live: the next SDK call against
it raises `modal.exception.NotFoundError`), and `ModalSandbox.run()`'s
existing `except modal.exception.Error` handler already turns that into
`SandboxCrashed`.

**Why:** This is exactly the right semantics already — the agent's
contract is "a Python exception or timeout *inside user code* comes
back as a structured `ExecResult`; an infrastructure-level death raises
an exception" (D-006-adjacent). An OOM kill of the whole container is
an infrastructure death, not a catchable Python exception in the user's
script, so it belongs on the `SandboxCrashed` side of that line.

**Alternatives rejected:** Trying to detect this case specifically and
synthesize a fake `ExecError` for it — rejected, would blur a
distinction (user-code failure vs. infrastructure failure) that the
rest of the design deliberately keeps sharp, and the agent's repair
loop should retry on infra failures differently than on a script bug
anyway.

## D-026 — Exec timeout is detected via Modal's `-1` returncode sentinel

**Date:** 2026-10-24

**Decision:** `ModalSandbox` treats `returncode == -1` from
`ContainerProcess.wait()` as "this exec timed out," rather than relying
on catching `modal.exception.ExecTimeoutError`.

**Why:** Reading the installed SDK source directly (not guessing)
showed `ContainerProcess.wait()`/`poll()` currently swallow
`ExecTimeoutError` internally and set `returncode = -1` instead of
propagating it — confirmed live in `test_f_timeout_then_fresh_run_works`.
Catching the exception alone would miss real timeouts on this SDK
version.

**Alternatives rejected:** Catching `ExecTimeoutError` only — rejected,
doesn't match this SDK version's actual behavior as verified by both
source reading and a live test.

## D-027 — Sandbox entrypoint is `sleep <lifetime_s>`, work happens via `exec`

**Date:** 2026-10-24

**Decision:** `Sandbox.create("sleep", str(sandbox_lifetime_s), ...)` is
the sandbox's main command; the actual task script runs via a separate
`sandbox.exec("python", RUNNER_PATH, ...)` call, and the sandbox is
terminated explicitly afterward rather than left to exit on its own.

**Why:** `Sandbox.create`'s `*args` set the container's CMD; without a
long-running placeholder command the container could exit before (or
while) files are written into it via the filesystem API. `sleep
<lifetime_s>` bounds the container's own maximum lifetime to the same
number already used for Modal's `timeout=` parameter, so the two limits
agree.

**Alternatives rejected:** Running the task script directly as the CMD
(`Sandbox.create("python", RUNNER_PATH, ...)`) — rejected, that would
require uploading files *before* the sandbox exists (not possible — the
filesystem API needs a running sandbox) and would reuse `Sandbox.create`'s
output-capture path instead of `exec`'s, which is less uniform with how
the host actually wants to read stdout/stderr/returncode.

## D-028 — The runner catches `Exception`, not `BaseException`

**Date:** 2026-10-24

**Decision:** `runner.py` wraps `runpy.run_path(...)` in
`except Exception`, not `except BaseException`.

**Why:** `BaseException` would also catch `SystemExit`, which would
turn a deliberate `sys.exit(0)` in a user script into a reported
"error." In practice the static checker (Task 5) blocks `exit`/`quit`
calls anyway, but the runner itself shouldn't rely on that — it should
do the Python-idiomatic thing on its own.

**Alternatives rejected:** `except BaseException` for maximal safety
net — rejected, would misreport a clean `SystemExit` as a crash.
