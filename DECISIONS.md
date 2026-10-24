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

**Confirmed 2026-10-24:** `openai/gpt-oss-20b` on NVIDIA replied; a
two-word answer used 68 completion tokens because reasoning tokens
count toward `max_tokens`.

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

## D-029 — `FORBIDDEN_CALL` blocks bare references, not just calls

**Date:** 2026-10-24

**Decision:** `FORBIDDEN_CALL` fires on any `ast.Name` in `Load` context
whose id is in the denylist (`eval`, `getattr`, ...) — not only when
that name is the function of an `ast.Call`.

**Why:** Checking only `ast.Call(func=Name(...))` would miss aliasing
(`x = eval; x(code)`), which is a trivial bypass of a call-site-only
check. These 15 names have no legitimate use in a CSV-analysis script,
so blocking every reference to them (not just every call) has no
real cost in false positives.

**Alternatives rejected:** Call-site-only detection — rejected as
trivially bypassable by aliasing.

## D-030 — `UNSAFE_WRITE` and `PICKLE` fail closed on non-literal inputs

**Date:** 2026-10-24

**Decision:** When `open()`'s mode, or `allow_pickle`'s value, is not a
literal the checker can read directly (e.g. a variable instead of a
string/bool constant), the checker blocks rather than passing it
through.

**Why:** The checker's whole value proposition is "provably safe from
the source text alone." A non-literal value can't be proven safe
without executing the code, which the checker must never do — so the
only sound choice is to treat "can't tell" as "treat as unsafe."

**Alternatives rejected:** Treating unverifiable values as safe (fail
open) — rejected, defeats the purpose of the check.

## D-031 — `PICKLE`'s `allow_pickle=True` check doesn't verify the call is `numpy.load`

**Date:** 2026-10-24

**Decision:** Any call carrying a literal `allow_pickle=True` keyword
is flagged, regardless of what function is being called or what module
it came from.

**Why:** No function outside `numpy.load` (and a few numpy-family
loaders) accepts an `allow_pickle` keyword at all — passing it to
anything else is a `TypeError` at runtime, so it would never appear in
real code. Checking for the keyword's presence is therefore precise
without needing to track which module `np`/`numpy` was imported as.

**Alternatives rejected:** Resolving the call's base object to confirm
it's actually `numpy` — rejected as unnecessary complexity (import-alias
tracking) for no precision gain.

## D-032 — `guard/policy.py` hardcodes `/work` instead of importing it from `sandbox/base.py`

**Date:** 2026-10-24

**Decision:** `policy.WORK_DIR = "/work"` is a separate, independent
constant from `sandbox.base.WORKDIR`, not imported from it.

**Why:** The checker and the sandbox are described throughout this
project as two independently-testable security layers (D-009); the
checker's test suite (`tests/guard/`) should be able to run — and be
reasoned about — with zero dependency on the sandbox package. The
duplication is two lines of string, not worth a cross-package import
for.

**Alternatives rejected:** Importing `WORKDIR` from `sandbox.base` —
rejected, adds a real dependency between the two layers for a trivial
string constant, and makes the checker's test suite not stand alone.

## D-033 — Two static-checker bypasses found and accepted, not closed

**Date:** 2026-10-24

**Decision:** 30 minutes of red-teaming `check()` in isolation (no
sandbox) found two real bypasses — format-string attribute traversal
(`"{0.__class__}".format(x)`) and aliasing the `open` builtin before
calling it. Both are captured as `xfail(strict=True)` tests
(`tests/guard/test_bypass_hunt.py`) and documented in
`docs/security.md`, rather than being closed.

**Why:** Closing either one at the AST layer requires either scanning
string *contents* (false-positives on any benign string containing
`__`) or a real dataflow/alias-tracking pass (well beyond "AST-only,
fast feedback"). Both bypasses only grant access to things the sandbox
already permits a cooperative script to do (introspect its own
objects; write inside its own ephemeral, non-sensitive filesystem) —
neither is a sandbox escape, which is the actual property that
matters (D-009).

**Alternatives rejected:** Adding ad hoc heuristics for each (e.g.
scanning strings for `__`, or flagging any two-string-literal call) —
rejected after confirming they would misfire on ordinary benign code
(docstrings, `re.sub` with two string literals).

## D-034 — CI's forbidden-files check is a `git ls-files` + `grep` gate

**Date:** 2026-10-24

**Decision:** `.github/workflows/ci.yml` fails the build if
`git ls-files` lists anything under `data/`, `runs/`, or `notes/`, any
`.env*` file other than `.env.example`, or any file named `da-dev-*`
anywhere in the tree — checked with one `grep` pass over
`git ls-files`, not `.gitignore` itself.

**Why:** `.gitignore` only stops *new* untracked files from being
added by accident; it does nothing once a file has been force-added
(`git add -f`) or was committed before a gitignore rule existed. CI
checking what's *actually tracked* is the only check that still catches
that case. `git ls-files` is also exactly what a reviewer or `git clone`
sees, so it's the right thing to assert against.

**Alternatives rejected:** Relying on `.gitignore` alone — rejected, it
provides no protection against `git add -f` or pre-existing commits.

## D-035 — CI uses `astral-sh/setup-uv`, runs on every push and PR

**Date:** 2026-10-24

**Decision:** CI uses the `astral-sh/setup-uv` action (official uv
GitHub Action) rather than `actions/setup-python` + manual `pip install
uv`, and triggers on both `push` and `pull_request` with no branch
filter.

**Why:** `astral-sh/setup-uv` installs uv and a matching Python version
in one step, matching how the project is run locally (`uv sync`, `uv
run ...`) with no separate tool to keep in sync. Running on every push
(not just PRs) catches breakage on `main` itself, not only on branches
being merged in — relevant since this repo currently only has a
`main` branch.

**Alternatives rejected:** PR-only triggers — rejected, would miss
direct pushes to `main` during solo development, where there's no PR
to gate.

## D-036 — LLM sampling defaults are fixed, not tuned per call

**Date:** 2026-10-24

**Decision:** `temperature=1.0`, `top_p=1.0` (gpt-oss's own defaults, per
NVIDIA's sample code), `max_tokens=4096`, `reasoning_effort="medium"`.
These are used for every headline benchmark number; run-to-run variance
from the LLM's own stochasticity is handled by reporting 3 runs with a
confidence interval (D-013), not by forcing `temperature=0`.

**Why:** `temperature=0` would make the benchmark numbers look falsely
reproducible while hiding the model's actual variance; reporting
multiple runs is the honest way to show that variance instead of
suppressing it.

**Alternatives rejected:** `temperature=0` for "reproducible" numbers —
rejected, this is exactly the single-run-looks-stable trap D-013
already rejects for a different reason (sandbox transience); the fix
is the same (report multiple runs), not forcing determinism.

## D-037 — LLM error policy: dispatch on status code, not exception class

**Date:** 2026-10-24

**Decision:** `OpenAICompatClient` retries only 429, 5xx, request
timeouts, and connection errors (up to 6 attempts, exponential backoff
with full jitter, honoring a `Retry-After` header when present). Every
other 4xx raises `LLMConfigError` immediately, carrying the provider's
own error message, with no retry. The retryable/non-retryable split is
decided by reading `exc.status_code` off the caught `openai.APIError`
(plus the two timeout/connection classes), not by matching on which
exception subclass the SDK happened to raise.

**Why:** Reading the installed `openai` SDK's source (`_client.py`'s
`_make_status_error`) showed that only 400/401/403/404/409/422/429 and
anything ≥500 get a dedicated exception subclass; a 410 (the exact
error this project hit when `gpt-oss-120b` was retired — see D-003)
falls through to the generic `APIStatusError` with no subclass of its
own. Matching on `status_code` handles that case correctly without a
special-cased branch for 410; matching on exception class would have
silently missed it (generic `APIStatusError` isn't `BadRequestError`,
`NotFoundError`, or any other named subclass).

**Alternatives rejected:** Matching on exception subclass (e.g.
`except openai.NotFoundError`) — rejected, provably wrong for 410 and
any other status code without a dedicated subclass, confirmed by
reading the SDK source rather than assuming the taxonomy was complete.

## D-038 — Record/replay cassettes, keyed by a canonical-JSON hash

**Date:** 2026-10-24

**Decision:** `RecordingLLM` appends every request/response pair to a
JSONL cassette file; `ReplayLLM` serves responses by looking up the
sha256 of a canonical JSON encoding of `(provider, model, messages,
sampling params)`, raising `CassetteMiss` on an unknown key. Cassettes
live under `tests/cassettes/`, are committed (they contain no secrets,
just request/response pairs), and must never contain DABench data.

**Why:** Deterministic, offline tests for LLM-dependent code need real
recorded provider behavior (including provider-specific quirks like
`reasoning_content`), not hand-written fixtures that might not match
what a real response actually looks like. Hashing the full request
(not just a label) means a cassette can never silently serve the wrong
answer for a changed prompt.

**Alternatives rejected:** Hand-written fixture responses — rejected,
risks drifting from what providers actually return. A sequential/
positional cassette format (match by call order, not content) —
rejected, too fragile to call-order changes during refactors.

## D-039 — `reasoning_effort` is sent as the native OpenAI-compatible parameter

**Date:** 2026-10-24

**Decision:** `OpenAICompatClient` sends `reasoning_effort` as a normal
top-level parameter on the chat-completions request, exactly as the
`openai` SDK types it (no `extra_body`, no system-message fallback).

**Why:** A live test against NVIDIA NIM (`openai/gpt-oss-20b`), same
question (`"What is 15 + 27? Answer with just the number."`), 2 calls
at `reasoning_effort="low"` and 2 at `"high"`, measured mean completion
tokens of **16 (low) vs. 60 (high)** — a clear, consistent difference,
confirming NIM honors the parameter natively. The fallback design
(injecting a `"Reasoning: <level>"` line into the system message) was
never needed.

**Alternatives rejected:** The system-message fallback — not built,
since the native parameter demonstrably works; keeping unused fallback
code around would be dead code with no test coverage backing it.

## D-040 — Pinned DABench revision; verification stops on mismatch, never adjusts expectations

**Date:** 2026-10-24

**Decision:** Pinned `infiagent/DABench` (dataset repo) to revision
`b455d578e30fee513abd79936cbdf7a6de026cb5`, resolved live via
`HfApi().dataset_info(...).sha` rather than assumed. The download
script (`bench/download.py`) hardcodes the dataset's known-good shape
(257 questions, 257 labels with matching ids, every referenced CSV
present, exactly 52 distinct CSVs referenced) as constants and raises
`VerificationError` with the actual numbers on any mismatch — it never
changes the expected constants to match what it finds.

**Why:** A pinned revision means every future run downloads the exact
same dataset, regardless of upstream changes; this project already
learned the cost of an unpinned dependency moving out from under it
(D-003's model retirement). Treating the expected counts as fixed
constants rather than "whatever the current download says" is what
makes verification meaningful — a check that silently adopts the data
it's checking can never fail.

**Alternatives rejected:** Downloading `revision="main"` (always
latest) — rejected, defeats the purpose of a benchmark whose numbers
should be reproducible against a fixed dataset version. Letting
verification auto-update its expected counts on mismatch — rejected
outright, that's not verification, that's just recording whatever
showed up.

## D-041 — Split seed and resulting counts

**Date:** 2026-10-24

**Decision:** `SPLIT_SEED = 2026`. Splitting the 52 distinct CSV files
(sorted, then shuffled with that seed) and adding files to dev until
dev's cumulative question count reaches at least 20% of all 257
questions produced: **dev = 11 files / 74 questions** (easy 21, medium
25, hard 28), **test = 41 files / 183 questions** (easy 61, medium 62,
hard 60). Recorded in `eval/split.json` (committed — file names and
question ids only, per the test-set-discipline rule this task also
adds to `CLAUDE.md`).

**Why:** Splitting by file rather than by question (D-012) means the
dev fraction lands close to, but not exactly at, 20% — it's a property
of which files' question counts happen to cross the threshold first in
shuffled order, not a number tuned to hit exactly 20.0%. 28.8% dev was
accepted as-is rather than re-seeding to chase a rounder number, since
re-seeding until a "nicer" split appears would itself be a (very mild)
form of tuning against the split.

**Alternatives rejected:** Re-seeding to land closer to exactly 20% —
rejected for the reason above; the threshold is a floor, not a target.

## D-042 — Dataset profiling runs on the host with pandas, inside unforgeable delimiters

**Date:** 2026-10-24

**Decision:** `agent/profile.py` parses a CSV with pandas directly on
the host, not inside the Modal sandbox. `to_prompt_text()` renders a
compact preview (column names/dtypes/null counts/capped unique counts/
3 example values, 5 sample rows, every cell truncated to 40 chars),
hard-capped at 4,000 chars, wrapped in explicit "UNTRUSTED DATASET
PREVIEW" delimiters. Any occurrence of the literal delimiter strings
inside the CSV's own content (a column name, a cell value, a parse
warning, even the file name) is replaced with `[blocked-delimiter]`
before interpolation, so nothing in the file can forge a fake
end-of-block marker. The full file is never sent to the LLM — only
this preview is.

**Why:** Parsing a CSV's structure (column names, dtypes, a few sample
values) is not executing anything the file contains — the host never
runs a formula, a macro, or any code path controlled by the file's
content, so this doesn't cross the "never execute untrusted code on
the host" line (CLAUDE.md rule 1). Doing it on the host instead of
spinning up a sandbox avoids real sandbox cost and ~6-10s of latency
for every single preview. The delimiter-forgery defense matters
because the preview's whole purpose is to tell the LLM "the following
is data, not instructions" — a cell that could fake the block's own
end marker would let attacker-controlled CSV content pose as trusted
instructions again after that point.

**Alternatives rejected:** Profiling inside the sandbox — rejected,
unnecessary cost/latency for something that's just reading a file's
shape, not running code. Truncating/escaping only *some* known
dangerous substrings (e.g. just looking for "ignore previous
instructions") — rejected, that's a content-based heuristic that will
always miss a rephrasing; neutralizing the exact delimiter strings
(the actual thing being defended) is precise and can't be talked
around by rewording the attack.

## D-043 — One shared AgentEvent schema; a `TraceWriter` is just an `on_event` subscriber

**Date:** 2026-10-24

**Decision:** `agent/events.py` defines one frozen dataclass,
`AgentEvent(run_id, seq, ts, type, attempt, payload)`, with `payload` a
plain JSON-serializable `dict`. `EventEmitter` is the only thing that
assigns `run_id`/`seq`/`ts` and forwards the result to an optional
`on_event` callback. `TraceWriter` (`agent/trace.py`) is a callable
class that *is* that `on_event` callback -- it has no special
relationship with the emitter beyond being handed to it. Large binary
payloads (matplotlib PNGs) never go in `payload`; the agent loop writes
them to `runs/artifacts/<run_id>/` and puts the file paths in the event
instead.

**Why:** This schema is deliberately reused as the SSE stream schema in
P4 (see docs/PLAN.md) -- designing it as "one dataclass + one callback
protocol" now means the API layer can attach its own `on_event`
(stream to the client) alongside the CLI's (print + trace) with zero
changes to the agent loop. Keeping `payload` plain-dict-shaped (no
nested dataclasses, no bytes) means `json.dumps` always works on it
without a custom encoder.

**Alternatives rejected:** A dedicated event bus / pub-sub class —
rejected, the agent loop only ever has 0 or 1 subscriber at a time (the
CLI composes "write trace" and "print timeline" into one closure
itself); a full bus is unused generality. Inlining images as base64 in
the payload — rejected, bloats every trace line and every (future) SSE
frame for data the viewer can instead fetch once by reference.

## D-044 — `FinalAnswer` JSON is extracted with a brace-depth scanner, not a regex

**Date:** 2026-10-24

**Decision:** `agent/answer.py`'s `extract_json` finds the first
balanced top-level `{...}` span by walking the text and tracking brace
depth (ignoring braces inside quoted strings), rather than matching
`\{.*\}` or similar. It checks inside a fenced code block first (if the
reply has one), then falls back to scanning the raw reply.

**Why:** A greedy `\{.*\}` regex over a whole reply happily consumes
past the real end of the JSON object if the model adds any trailing
prose containing a brace, and a non-greedy version breaks as soon as
the JSON itself contains a nested object (which `FinalAnswer`'s
`answers` list always does). A brace-depth scanner gets the exact
object boundary right either way, including when a string value
contains a literal `{` or `}`.

**Alternatives rejected:** Regex-only extraction — rejected for the
reason above. Requiring the model's entire reply to be bare JSON with
no surrounding text — rejected, real provider replies routinely wrap
JSON in a fenced block even when explicitly asked not to.

## D-045 — Evidence checking: numbers first, then lists, then substrings; a known ambiguity is left open

**Date:** 2026-10-24

**Decision:** `agent/evidence.py` checks each answer value in this
order: (1) if the whole value parses as one number (after unwrapping
optional `[...]`/`(...)` brackets), compare it against every number
found in stdout, passing if stdout's number rounds to the answer's own
decimal places *or* is within relative `1e-9`; (2) else if the value
contains a comma, split on commas and require every element to pass
this same check recursively; (3) else, do a case-insensitive,
whitespace-normalized substring check. Numbers are extracted from
stdout with a single regex pass that treats thousands-grouped digits
(`12,345`) as one token, so a longer number is never mistaken for
containing a shorter one as a substring (`14.5` does not evidence
`4.5`).

**Why:** Trying the single-number parse *before* the list split is
what resolves the one real ambiguity in this scheme: `"12,345"` could
be one number or a two-element list `["12", "345"]`. Preferring "it's a
number if it parses as one, whole-string, after stripping thousands
separators" matches how DABench labels actually look (rounded numbers,
occasionally with thousands separators) far more often than a
two-element list would.

**Known limit, left open rather than fixed:** a *list* whose own
elements use thousands separators (e.g. `"1,234, 5,678"`) still gets
split on every comma, including the ones inside each element, because
the list-splitting step doesn't re-run the single-number check on the
raw unsplit text before splitting. Closing this would need look-ahead
across comma-separated groups of exactly three digits, which is more
complexity than any real dev-set label has needed so far; documenting
the gap here is cheaper than guessing at a fix with no failing example
to test it against.

**Alternatives rejected:** Treating any value with a comma as a list
first (checking single-number second) — rejected, this is the
ordering that gets the far more common `"12,345"`-is-one-number case
wrong. A full tokenizer/parser for answer values — rejected as
over-engineering for a format this simple.

## D-046 — Every LLM call is a fresh two-message exchange, not accumulated chat history

**Date:** 2026-10-24

**Decision:** `agent/prompts.py` builds every call -- the first code
generation, every repair, the answer step, and the one answer-JSON
retry -- as exactly two messages: a system prompt and one user
message. A repair call's user message (`build_repair_message`) embeds
the previous script and the observation text directly; it never
replays the model's own prior replies or re-sends the dataset preview.

**Why:** Each attempt is already a complete, independent script (D-006
"every attempt runs a complete script in a fresh sandbox"), so the
model doesn't need the full conversation to write a corrected one --
the previous code plus what went wrong is sufficient context. This
also keeps the per-task token budget (60,000, landing in Task 3) from
being dominated by re-sending the ~600-900-token dataset preview on
every one of up to 4 attempts, and keeps every prompt-building
function pure and trivially testable (built from explicit arguments,
not from mutable conversation state).

**Alternatives rejected:** Accumulating full chat history across
attempts — rejected, it would re-send the preview block repeatedly
(token cost) and makes "no message reveals the attempt count" harder
to reason about (a growing message list is itself a count, even if no
message states one in words).

## D-047 — `run_agent` calls `sandbox_factory()` exactly once per run, not once per attempt

**Date:** 2026-10-24

**Decision:** `agent/loop.py`'s `run_agent` calls `sandbox_factory()`
a single time at the start of a run, uses the returned `Sandbox` as a
context manager for the whole run, uploads the CSV once, and calls
`.run(code)` once per attempt on that same object.

**Why:** D-006 already establishes that *attempt-level* freshness is
`ModalSandbox.run()`'s own job -- it creates and terminates a real
Modal sandbox internally on every call, so the `run_agent` layer
doesn't need to construct a new Python `Sandbox` object per attempt to
get that property. Calling the factory once also matches the `Sandbox`
protocol's documented contract ("files uploaded earlier are available
to every run") and means `FakeSandbox` in tests can be constructed
once with a queue of scripted per-attempt results, rather than needing
a fresh scripted object assembled for every attempt.

**Alternatives rejected:** Calling `sandbox_factory()` once per
attempt — rejected, it would duplicate the freshness guarantee
`ModalSandbox.run()` already provides, require re-uploading the CSV on
every attempt, and would need a factory that returns a *different*
`FakeSandbox` per call in tests, instead of one object holding the
whole scripted sequence.

## D-048 — `run_agent`'s stop conditions for repeated failure only cover identical code or identical *consecutive* exec-error signatures

**Date:** 2026-10-24

**Decision:** The `"repeated_failure"` stop condition fires on exactly
two triggers: (a) the generated code is byte-identical to *any* earlier
attempt's code in this run (checked before the checker or sandbox ever
sees it -- the code is never executed), or (b) a Python exception
raised by the script has the same normalized `(name, value)` signature
as the *immediately preceding* attempt's exception. Checker violations,
timeouts, crashes, and evidence failures do not get their own
consecutive-signature check -- only the identical-code check applies to
them, and that check applies regardless of whether the earlier,
identical attempt itself succeeded or failed.

**Why:** The task's own wording ties "error signature" to "type +
message", which is exactly an `ExecError`'s `(name, value)`; nothing in
the spec asks for signature-matching on checker/evidence/timeout
observations, and those already have a safety net via the
identical-code check. Applying the identical-code check unconditionally
(not just after a failure) is deliberate: it is cheap, and a model that
resubmits byte-identical code is stuck regardless of why.

**Known trade-off:** if an evidence check fails only because the
*answer step* misread otherwise-correct stdout, the honest repair is
to resubmit the same (correct) code and let the answer step try again
-- but resubmitting identical code always stops the run as
`repeated_failure`, even in this case. This is accepted as the cost of
a cheap, unconditional check rather than threading "was the previous
identical attempt's *code* actually fine" through the comparison.

**Alternatives rejected:** Generalizing the signature check to every
observation kind — rejected as reading more into the spec than it
states. Exempting the identical-code check when the earlier attempt's
code executed successfully — rejected as the one case this would need
to special-case is not explicitly required, and doing so would make
"byte-identical" a conditional check instead of the simple, absolute
one the spec describes.

## D-049 — Per-attempt sandbox cost is estimated from `ExecResult.duration_ms`, not read back from the ledger file

**Date:** 2026-10-24

**Decision:** `agent/loop.py` computes each attempt's `est_usd` by
calling `sandbox.ledger.estimate_cost_usd(...)` directly on the
attempt's own `duration_ms` (plus the configured CPU/memory
reservation), and sums that across attempts for `AgentResult`'s
per-run total. It never reads `runs/sandbox_ledger.jsonl` back to
compute a run's cost.

**Why:** The ledger file (`ModalSandbox.run()`'s own side effect) is a
lifetime-cumulative total across every run the process has ever made,
with no run-id boundaries recorded in it -- there's no way to slice
"just this run's share" back out of it. `estimate_cost_usd` is already
a pure function of `(alive_s, cpu, memory_gib, rates)` with no file
I/O, so calling it a second time with the attempt's own duration gives
an equally valid lower-bound estimate (D-007) scoped correctly to one
run, and it works identically for `FakeSandbox` in tests (which never
writes to the ledger at all).

**Alternatives rejected:** Reading the ledger file's tail after each
run and diffing against a pre-run snapshot — rejected, fragile under
any concurrent run and adds file I/O for a value `run_agent` can
compute directly from data it already has.

## D-050 — The attempt loop's control flow is one internal exception (`_StopRun`), never a return value threaded through `continue`/`break`

**Date:** 2026-10-24

**Decision:** `_run_attempts` has a `NoReturn` return type: every path
through it ends by either `continue`-ing to the next attempt or
raising `_StopRun(status, ...)` -- including success (`"answered"`)
and the natural fall-through after 4 attempts (`"failed"`). `run_agent`
catches exactly one `_StopRun` and builds `AgentResult` from its
attributes. Per-attempt bookkeeping (token/latency totals, the set of
seen code strings, the consecutive-crash counter, the last exec-error
signature) lives on one mutable `_RunState` object threaded through
both functions, rather than as a chain of returned tuples.

**Why:** The loop has many distinct terminal conditions (answered,
failed, repeated_failure, tool_failure, budget_exceeded, llm_error)
that can each fire from several different places in the attempt body.
Modeling every one of them as a `raise` with the terminal status and
whatever evidence it's carrying (the answer, the exec result, the
code) keeps each exit point a single, self-contained statement instead
of a `status = ...; break` pattern repeated at every exit, and the
`NoReturn` annotation makes "this function always ends by raising"
checkable by a reader (and by `ruff`/a type checker) rather than just
asserted in a comment.

**Alternatives rejected:** Returning a `(status, ...)` tuple or sentinel
object from `_run_attempts` and having every call site check it before
deciding to `continue` -- rejected, it's the same number of exit points
with none of the benefit (every `continue` site would still need the
full status-tuple construction logic, just without `raise`'s "this
really does stop everything" guarantee).

## D-051 — The smoke selection's level spread (2/2/1 for n=5) is "divide evenly, remainder to earlier levels first"

**Date:** 2026-10-24

**Decision:** `cli.select_smoke_questions` spreads `n` across
`["easy", "medium", "hard"]` with `base, remainder = divmod(n,
3)`, giving every level `base` questions and then one extra each to
the first `remainder` levels in that fixed order. For `n=5` this gives
exactly the requested 2 easy / 2 medium / 1 hard; for `n=3`/`6` it
gives an even 1/1/1 or 2/2/2 split. Within each level, the candidate
pool is sorted by question id (for a stable starting order) and then
shuffled with `random.Random(seed)` before taking the first `count`.

**Why:** This is the simplest rule that reproduces the one example the
task spec gives (2/2/1 at n=5) and generalizes sensibly to other `n`
without hardcoding a table of per-n splits. It deliberately does NOT
mirror the dev split's own easy/medium/hard proportions (21/25/28,
roughly 28/34/38%) -- the task asked for a spread across levels for a
human to eyeball quickly, not a representative sample.

**Alternatives rejected:** Proportional allocation matching the dev
split's actual level distribution — rejected, it wouldn't reproduce
the spec's own 2/2/1 example for n=5 (which is closer to even than
proportional-to-28/34/38 would give).

## D-052 — `sa dabench-smoke` is dev-only by construction, not by a flag check

**Date:** 2026-10-24

**Decision:** `cli.load_dev_questions()` is the only place
`dabench-smoke` gets its question pool from, and it calls
`bench.split.load_split("dev")` -- never `"test"` -- with no CLI flag,
environment variable, or code path anywhere in `cli.py` that can reach
`load_split("test")`. "Never touches the test split" is therefore true
because the test split is simply never named in this file, not because
of a runtime guard that could be bypassed or misconfigured.

**Why:** A structural guarantee (the code to load the test split
doesn't exist in this command at all) is strictly stronger than a
runtime check (e.g. "refuse if `args.split == 'test'`"), which would
still require a `--split` flag to exist in the first place and be
trusted not to default to the wrong thing. This also matches
`load_split("test")`'s own design (D-012/CLAUDE.md rule 11): the
held-out split is meant to be reached deliberately, for a real frozen
evaluation run, not as an option sitting next to `dev` in a smoke
script.

**Alternatives rejected:** A `--split {dev,test}` flag defaulting to
`dev` — rejected outright; even with a safe default, its mere
existence is exactly the kind of accidental-tuning risk the test-set
discipline rule exists to prevent.

## D-053 — The CLI reads trace/usage-log run_id from the first emitted event, not generated up front

**Date:** 2026-10-24

**Decision:** `cli._LazyTraceWriter` has no `run_id` at construction
time; it creates its `TraceWriter` lazily, the first time it's called
as an `on_event` subscriber, using that event's own `run_id`. `sa ask`
composes this with console printing (`_TracingPrinter`);
`sa dabench-smoke` uses the trace-only variant per question, with no
printing, to keep the per-question summary table readable.

**Why:** `run_agent` generates its own `run_id` internally
(`events.new_run_id()`) and has no parameter for a caller to inject
one -- by design, the CLI is not meant to know or choose a run's id in
advance. Since every `AgentEvent` already carries `run_id`, waiting
for the first event to arrive is the only point at which the CLI
*can* know it, so the trace file's name is naturally derived from the
run rather than threaded in from outside.

**Alternatives rejected:** Adding a `run_id` parameter to `run_agent`
so the CLI can pre-generate the trace path — rejected, it would make
every other caller (tests, the future API) pass through an id they
don't otherwise need, just to serve this one piece of CLI plumbing.

## D-054 — Answer-name normalization happens at the answer boundary, in two steps

**Date:** 2026-10-24

**Decision:** `AnswerItem.name` always strips whitespace and any
leading `@` (a pydantic `field_validator`, so it fires no matter where
an `AnswerItem` is constructed). Separately, `parse_final_answer`
accepts an optional `answer_format` and, when given one, re-cases each
already-@-stripped name to match that format's own `@name[...]`
placeholders case-insensitively (`match_names_to_format`); a name that
doesn't match any placeholder is left alone. `agent/loop.py` passes the
question's `answer_format` through on both the primary answer call and
its one JSON-retry call.

**Why:** The P1 smoke run (`docs/smoke-p1.md`) showed the model
sometimes puts the leading `@` *inside* the JSON `name` field itself
(producing a doubled `@@` once the CLI's own display adds its own `@`),
and separately can vary a name's casing relative to the format string's
placeholders. Splitting this into "always clean" (strip/`@`) and
"format-aware" (re-case to match placeholders) keeps the first part
correct even when no `answer_format` is available (e.g. the `sa ask`
command, which has no DABench format string at all), while the second
part only activates where there's an actual format to match against.

**Alternatives rejected:** Fixing this only in the CLI's display code —
rejected, the grader (Task 2) also reads `answer.name` directly and
needs the same clean value; fixing it once at the pydantic-model
boundary covers every consumer. Normalizing names by exact match only
(no case-insensitivity) — rejected, the smoke run's doubled-`@` case
also showed the model doesn't reliably match a format's own casing.

## D-055 — The sandbox ledger is the single source of truth for `AgentResult.sandbox_usd`

**Date:** 2026-10-24

**Decision:** The `Sandbox` protocol gains a `last_run_cost_usd: float`
attribute, updated by a backend after every `run()` call to the exact
lifecycle cost (create + exec + terminate) it just recorded in the
ledger -- including when `run()` raises `SandboxCrashed` (a sandbox was
still created and billed), but left unchanged when it raises
`SandboxUnavailable` before any sandbox was created. `agent/loop.py`
sums `sandbox.last_run_cost_usd` after every attempt (success or crash)
into `AgentResult.sandbox_usd` (renamed from `sandbox_est_usd`), instead
of calling `estimate_cost_usd` a second time against `ExecResult`'s
exec-only `duration_ms`. `FakeSandbox` gets a `run_cost_usd` constructor
parameter so tests can script a per-run cost without touching Modal.

**Why:** `docs/smoke-p1.md` found the old exec-only estimate
(`$0.0002`) was about 4x lower than the ledger's own lifecycle total
for the same run (`$0.000797`), because `ModalSandbox.run()`'s ledger
entry spans sandbox creation and teardown while `ExecResult.duration_ms`
only spans the `exec()` call inside it. Reading the cost back off the
same backend that just recorded it to the ledger (rather than
recomputing a different, narrower estimate from a different
measurement) makes the two numbers agree by construction, and also
fixes a real gap: the old code never charged anything for a crashed
attempt at all, even though a real sandbox was created and billed for
it.

**Alternatives rejected:** Reading `runs/sandbox_ledger.jsonl` back and
diffing against a pre-run snapshot to recover "this run's share" (the
alternative D-049 already rejected) — still rejected, fragile under
concurrency (Task 3's harness runs several tasks' sandboxes at once)
and unnecessary now that the backend can just report its own last
recorded cost directly.

## D-056 — LLM timeout set from measured latency, not a round number

**Date:** 2026-10-24

**Decision:** `Settings.llm_timeout_s` default changed from the
previous round number (120s) to **142s**, computed as
`max(45, ceil(2 * p95))` over every call recorded as `ok: true` in
`runs/llm_usage.jsonl` as of this session. Measured (n=20 successful
calls, `openai/gpt-oss-20b` on NIM): p50 = 14.22s, p95 = 70.57s, max =
77.30s (linear-interpolation percentile, matching numpy's default
method). The retry policy (D-037: retry 429/5xx/timeout/connection
errors, up to 6 attempts, exponential backoff with full jitter) is
unchanged -- only how long a single attempt waits before giving up and
retrying.

**Why:** The P1 smoke run's lesson (`docs/smoke-p1.md`) was that a mean
latency of 54s/task was dominated by two calls that hung all the way to
the old 120s timeout and only succeeded on retry -- the *tail*, not the
mean, is what a timeout has to budget for. Doubling the real p95 (not
the max, and not the mean) gives headroom above the typical slow case
without waiting through two full worst-case latencies before giving up;
flooring at 45s guards against a p95 computed from too few or
unusually fast samples producing an unreasonably short timeout.

**Alternatives rejected:** Doubling the mean — rejected, this project's
own smoke run is the direct counterexample for why the mean
under-represents tail latency here. Doubling the max — rejected, one
outlier (e.g. a provider hiccup) would then set the timeout for every
future call. Leaving the timeout at a round guessed number — rejected,
exactly the kind of unmeasured constant this task exists to replace
with data.

## D-057 — The grader: shape-driven tolerant matching, designed from DEV, extra answers ignored

**Date:** 2026-10-24

**Decision:** `bench/grader.py`'s `classify_shape` is a total function
over any string value (integer / `decimal_Ndp` / scientific / yes_no /
list_like / string / empty — "string" is the catch-all), and only
raises `ShapeParseError` for a non-string value. `shape_census` runs
over DEV labels only and is written to `docs/grader.md` (8 shapes
found live: decimal_1dp through decimal_4dp, integer, list_like,
string, yes_no — no dev label is scientific-notation or empty, though
both shapes are still handled and unit-tested). `count_unparseable`
then runs over **all 257** real labels (dev + test) and returns a bare
count (confirmed **0** against the real downloaded dataset) — the one
place this project touches TEST label content directly, and it is
restricted to printing/returning that single integer, never a value
(CLAUDE.md rule 11's explicitly sanctioned exception). TOLERANT mode's
numeric tolerance is `max(0.5 * 10^(exponent - decimals), 1e-9)`,
derived from the label value's own written precision (so it scales
correctly for both `"0.01"` and scientific-notation values like
`"7.46e+21"`); strings are case/whitespace-normalized; lists are
split and compared element-wise with the same rule recursively. Only
label sub-answer *names* are ever scored — a predicted answer with no
matching label name is counted (`n_extra_predicted`) but never
compared against anything.

**Why:** Classifying *every* real value (with "string" as a safe
catch-all) rather than raising on anything unexpected means the
format-only check over the full dataset is a meaningful robustness
proof (it would still catch a genuinely malformed, non-string label)
without ever needing to special-case content the grader hasn't seen.
Deriving numeric tolerance from the label's own last written decimal
place (D-045's same idea, reused here at the grading layer instead of
the evidence layer) means the tolerance automatically matches whatever
rounding convention each individual label actually used, instead of
one fixed epsilon for the whole dataset. Ignoring (not penalizing)
extra predicted names matches the smoke run's own observation
(`docs/smoke-p1.md`, question 275: the model answered two sub-answers
beyond what the label scored) — answering more than asked isn't itself
a scoring-worthy mistake.

**Alternatives rejected:** A single fixed epsilon (e.g. `1e-6`) for
every numeric comparison — rejected, it would be far too strict for a
label rounded to 0 decimal places and far too loose for one rounded to
4. Penalizing extra predicted answers as wrong — rejected, the label
schema only defines what *is* being asked; an extra, uncounted answer
isn't evidence of a wrong one. Tuning the shape classifier against
TEST label content to raise the dev-measured shape coverage — never
done; the census is DEV-only by construction and the all-labels check
reports only a count.

## D-058 — `results.jsonl` is append-only; infra errors are excluded and re-queued, never scored as wrong

**Date:** 2026-10-24

**Decision:** `bench/harness.py`'s `ResultsWriter` only ever appends to
`results.jsonl`, never rewrites a line in place. `ResultsWriter.
load_latest()` reads the whole file back and keeps the LAST row per
question id, so a re-queued retry's new line supersedes an earlier
`infra_error` line for the same id without needing to edit the file.
`done_ids()` returns every id whose latest row is NOT `infra_error` --
those, and only those, are skipped on resume. A question's recorded
`AgentResult.status` of `llm_error` or `tool_failure` is rewritten to
`status="infra_error"` in `QuestionResult` (keeping the original cause
in `infra_cause`), and Task 4's metrics must treat `infra_error` as its
own bucket, never as a wrong answer.

**Why:** Append-only logging is the same event-sourcing pattern already
used for traces and the usage/ledger logs (D-043) -- it's trivially
safe to resume from (just read what's there) and trivially safe to
write from multiple threads (one lock around one `open(...).write()`,
no read-modify-write race). Treating infra failures as a distinct,
excluded, always-retried category matters because a flaky provider
call or a transient sandbox hiccup says nothing about whether the
*model* got the right answer -- counting it as wrong would make the
accuracy number measure infrastructure reliability on a given day
instead of the thing it's supposed to measure.

**Alternatives rejected:** Rewriting/truncating `results.jsonl` in
place on resume (e.g. removing infra_error lines before re-running) --
rejected, turns a simple append into a read-entire-file-then-rewrite
operation that's far more exposed to corruption from a crash or a
concurrent writer mid-rewrite. Scoring `infra_error` questions as wrong
(0 credit) in accuracy metrics -- rejected for the reason above;
excluded and reported separately instead (D-013/D-014 already
established that this project treats transient infrastructure failure
as a different axis from model correctness).

## D-059 — The harness's three clean-stop conditions, and why "provider daily limit" isn't a fourth check

**Date:** 2026-10-24

**Decision:** `run_eval` stops submitting new work (lets in-flight
questions finish, then exits) on exactly three conditions, checked
after every completed question: (1) cumulative prompt+completion
tokens across the run `>= --token-budget`; (2) the sandbox ledger's
running total (`sandbox.ledger.ledger_total_usd`) `>=
settings.sa_sandbox_budget_usd`; (3) 3 consecutive `infra_error`
results, in completion order. A stopped run's `HarnessOutcome` carries
the exact resume command (same split/run-name/concurrency/token-budget/
limit) and the CLI exits non-zero. No separate "provider daily limit"
check exists.

**Why:** A hard provider daily cap and a transient rate-limit storm
both surface through the exact same path from here -- the LLM client's
own retry policy (D-037) already exhausts its 6 attempts and raises
`RateLimitExhausted`, which `run_agent` reports as `llm_error`, which
the harness reports as `infra_error`. From the harness's vantage point
there is no way to distinguish "this 429 will clear in a minute" from
"this account is out of quota for the day" -- both look like a
sustained run of 429s, and the consecutive-infra-error check already
stops the run after 3 of them either way, which is the only
*actionable* difference a stop condition can make (continuing to burn
the token/request budget against a wall that won't move before the
run ends).

**Alternatives rejected:** Trying to detect a provider's specific
"daily quota exceeded" error text or status code and treating it as a
fourth, distinct stop condition — rejected; NVIDIA's free tier is
documented as having no daily token cap (D-004), so there's no known
real error shape to design this against yet, and a guessed string match
would be exactly the kind of brittle, unverified check this project's
rules (CLAUDE.md: stop cleanly on a real failure, don't guess at ones
that haven't been observed) argue against.

## D-060 — Concurrency 6, one shared LLM client, and the thread-safety that requires

**Date:** 2026-10-24

**Decision:** The harness constructs exactly one `LLMClient` and passes
it to every worker thread (default concurrency 6); each worker still
gets its own, independent sandbox (`sandbox_factory(question)`, a
fresh real Modal sandbox per question, consistent with D-006/D-047).
Making this safe required three small changes: `RateLimiter.wait()`
now holds a lock across its whole check-sleep-record sequence (so the
`60/rpm` spacing guarantee holds globally across threads, not just
against whichever thread happened to read `_last_start` first);
`sandbox/ledger.append_entry` and `llm/usage.append_usage` now
lock their file write (several real `ModalSandbox`/`OpenAICompatClient`
instances, one per in-flight question, append to the same shared
ledger/usage files); and `bench/harness.ResultsWriter` has its own
lock around `results.jsonl`'s append. `check_budget`'s read-then-decide
is deliberately left as a soft, unlocked check.

**Why:** Before this task, every one of these shared files/limiters
only ever had a single caller (the CLI's `sa ask`/`dabench-smoke`, one
question at a time) -- concurrency is a genuinely new requirement this
task introduces, not a pre-existing gap. A single shared LLM client
(rather than one per thread) is what makes "one shared rate limiter"
true by construction instead of by convention. Locking only the
write/append (not the read-then-decide budget check) matches D-007's
own framing: the budget is already a lower-bound estimate with a
margin, so a race window of at most `concurrency` in-flight attempts'
worth of overshoot is immaterial next to the $0.20 margin, while file
corruption from an interleaved write is not acceptable at any size.

**Alternatives rejected:** One `LLMClient` per worker thread, each with
its own `RateLimiter` -- rejected, it would make "shared rate limiter"
false (each thread's limiter would independently allow up to
`concurrency * rpm` requests/minute in aggregate, defeating the whole
point of client-side pacing). Making `check_budget` itself atomic
(e.g. a file lock spanning read-then-decide-then-append) -- rejected
as unnecessary complexity given the budget's own built-in margin.

## D-062 — The bootstrap resamples questions (rows), paired across runs; report outputs and naming

**Date:** 2026-10-24

**Decision:** `bench/stats.paired_bootstrap_ci(rows, statistic, n_resamples=10_000, seed=2026)`
treats each element of `rows` as everything belonging to one question
(a single value for a lone run, or one value per run when pooling --
D-058's `results.jsonl` already keys everything by question id, which
is what makes this pairing possible). Every resample draws question
*rows* with replacement, never individual (question, run) pairs, so a
question's several runs are always kept or dropped together. A plain
unpaired `bootstrap_ci` is the same function with one-element rows.
UASQ gets its own bootstrap (`report._uasq_bootstrap_ci`, same
row-resampling shape) since it's a ratio-of-sums, not a mean, and a
mean-based resample over a per-question ratio would give equal-sized
questions equal resampling weight regardless of how many sub-answers
each one actually has. `sa report run-a run-b run-c` writes its
combined `report.md`/`report.json` to `runs/eval/<run-a>+<run-b>+
<run-c>/`, and one `failures.md` per individual run name under that
run's own existing directory -- the task didn't specify a combined
output path, so `"+".join(run_names)` was chosen as the simplest rule
that works for any number of runs, including one.

**Why:** Pairing is what makes "3 dev runs" a more informative
estimate than "222 independent question-attempts" -- the whole reason
to run the dev set 3 times (per the project lead's own framing) is to
separate the model's run-to-run stochastic variance from each
question's own difficulty; resampling (question,run) pairs
independently would blur that distinction back together and understate
how much variance comes from *which question* rather than *which run*.
10,000 resamples at dev scale (74 questions x 3 runs, every accuracy +
ablation + per-level combination) measured at ~80 seconds real
wall-clock for one full `sa report` call -- a one-time cost per report,
not a hot path, so no further optimization (e.g. fewer resamples, or a
numpy dependency this project's own rules forbid outside the sandbox
image -- D-002) was pursued.

**Alternatives rejected:** Resampling individual (question, run) data
points independently (the textbook single-sample bootstrap) --
rejected, exactly the design this decision's "why" argues against.
Deriving UASQ's CI from a mean-based resample of each question's own
ratio -- rejected, it would silently treat a 1-sub-answer question and
an 8-sub-answer question as equally "one data point," which UASQ's own
definition (pooled correct/total across every sub-answer) explicitly
does not do.

## D-063 — `dev-v1-r3` deferred mid-run; `docs/results-dev.md` reports 2 of 3 planned runs

**Date:** 2026-10-24

**Decision:** `dev-v1-r1` (74/74 done, 72 answered, 0 infra_error)
took ~21 minutes wall-clock at concurrency 6. `dev-v1-r2` (74/74 done,
71 answered, 0 infra_error) took ~110 minutes -- NIM was visibly
slower during that window (frequent `APITimeoutError`s hitting the
142s timeout before succeeding on retry, confirmed in
`runs/llm_usage.jsonl`). With `dev-v1-r3` already at only 3/74 after
starting and its remaining time uncertain, the project lead chose to
kill it mid-run rather than let a third, open-ended-length run
continue unattended. `docs/results-dev.md` is built from
`dev-v1-r1`/`dev-v1-r2` only (`uv run sa report dev-v1-r1 dev-v1-r2`)
and says so explicitly at the top, with the exact resume command for
`dev-v1-r3` (plain `uv run sa eval --split dev --run-name dev-v1-r3` --
the harness's own resume logic, D-058, skips the 3 already-recorded
ids automatically, no special flag needed).

**Why:** This is a direct, human, in-the-moment call on real
infrastructure's actual behavior that session, not a design decision
baked into the code -- the harness itself has no "provider is being
slow today, abort" condition (and D-059 already explains why it
shouldn't guess at one). Documenting the real timing numbers and the
exact resume command is what makes "2 of 3 runs, deferred, here's how
to finish it" an honest, reproducible state rather than a silently
incomplete result.

**Alternatives rejected:** Letting `dev-v1-r3` run to completion
regardless of elapsed time -- rejected by the project lead's explicit
instruction; an open-ended wait against a third-party API's variable
load isn't a cost this session chose to pay. Discarding `dev-v1-r3`'s
partial 3 recorded questions -- rejected, they're valid, already-paid-
for results that the harness's own resume logic can build on for free
later; no reason to throw them away.

## D-064 — Reorder: ship a public demo now, guardrail hardening and the frozen held-out run later

**Date:** 2026-10-24

**Decision:** P4 (API) and P5 (deploy) move ahead of P3 (guardrail
hardening) and P6 (freeze + held-out run). The agent's own behavior
(prompts, sampling, the repair loop) is untouched by this work -- the
API is a new caller of the existing `run_agent`, nothing more.

**Why:** A resume deadline needs a live link quickly. A shipped,
improvable system behind a stable URL is worth more than a perfect
unshipped one, and it is safe to ship before the red-team suite because
the actual security boundary is already in place: the Modal sandbox
(gVisor, no network, D-009) plus the public-safety limits this same
task adds (upload caps, per-IP/day/global run caps, concurrency cap).
The deployed agent is identical to the evaluated agent until the freeze,
so nothing about this reorder invalidates a future held-out run.

**Alternatives rejected:** Finishing P3/P6 first -- rejected under the
deadline; the static checker and sandbox are already independently
red-teamed in isolation at the unit-test level (D-009), which is enough
defense-in-depth to expose a sandboxed, network-isolated, rate-limited
demo publicly.

## D-065 — Demo LLM is Groq `gpt-oss-20b`; NVIDIA stays evaluation-only

**Date:** 2026-10-24

**Decision:** The deployed API's `SA_LLM_PROVIDER=groq`, same model
(`openai/gpt-oss-20b`) as every benchmark number. NVIDIA NIM is never
used from the public demo.

**Why:** NVIDIA's free endpoint's terms permit evaluation/testing, not
production traffic from arbitrary members of the public (D-004); Groq's
own free quota for this model is separate from NVIDIA's and from
ZoneWise's own Groq usage (which uses `gpt-oss-120b`, a different
per-model quota). Using the same model as the benchmark means whatever
the demo shows is representative of the measured numbers.

**Alternatives rejected:** Running the demo against NVIDIA too --
rejected, would mix evaluation-only traffic with public production
traffic against the same free-tier terms.

## D-066 — Synthetic example datasets, generated by us, no licence question

**Date:** 2026-10-24

**Decision:** `scripts/make_examples.py` generates 3 small CSVs
(sales, students, weather) with `random.Random(2026)`, written to
`src/sandbox_analyst/api/examples/`, plus `examples.json` (title,
description, 3 suggested questions per dataset, at least one asking for
a chart). Every value -- names, numbers, dates -- is fabricated by the
script; nothing is copied from a real dataset. Re-running the script
produces byte-identical output.

**Why:** The public demo needs example datasets a stranger can click
through with no upload step, and DABench's CSVs can never be used here
(CC BY-NC, never redistributed -- CLAUDE.md rule 11, D-011). Synthetic,
self-generated data sidesteps any licensing question entirely: there is
no source to attribute and nothing to restrict.

**Alternatives rejected:** Using a well-known public dataset (e.g. Iris,
Titanic) -- rejected as unnecessary; a fully synthetic generator is just
as illustrative for showing off chart/aggregation questions and has
zero licence surface. Using `pandas`/`numpy` in the generator -- not
needed; the three datasets are simple enough that the standard-library
`csv`/`random`/`datetime` modules are sufficient, so the script adds no
new host dependency.

## D-067 — API module layout and the agent-loop boundary this task does not cross

**Date:** 2026-10-24

**Decision:** The API lives entirely in `src/sandbox_analyst/api/`
(`app.py`, `schemas.py`, `limits.py`, `datasets.py`, `runs.py`,
`examples/`) and calls `run_agent` exactly as the CLI does -- as an
external caller, through its existing public parameters
(`llm`, `sandbox_factory`, `settings`, `on_event`). No line in
`agent/`, `llm/`, `sandbox/`, or `guard/` is changed by this task, per
this task's own rule against agent-loop changes.

Two consequences of not touching `agent/loop.py` or `agent/trace.py`:
- `run_agent` has no parameter for a caller to choose its internal
  `run_id` in advance (D-053 already established this is deliberate),
  so the API mints its OWN run id up front (returned synchronously from
  `POST /api/runs`) and separately records the agent's internal
  `run_id` (from the first `AgentEvent`, or from `AgentResult.run_id`)
  only for the one thing that needs it: locating chart PNGs, because
  `agent/loop.py`'s `_write_artifacts` hardcodes
  `runs/artifacts/<internal run_id>/` with no override parameter.
- `agent/trace.py`'s `TraceWriter` already takes a `trace_dir` parameter
  (no edit needed there), so the API *can* and does write traces under
  `SA_DATA_DIR/traces/<api run_id>.jsonl`, naming the file after its own
  public run id.

One real limitation follows from the artifacts point: chart PNGs land
at the agent's fixed, repo-relative `runs/artifacts/` path (relative to
the server process's working directory), not under `SA_DATA_DIR` like
everything else the API writes. In the production container this means
charts live under `/app/runs/artifacts/` -- ephemeral, not the
persistent `/home` volume -- which is accepted because the whole run
store is already documented as in-memory, single-instance, and
best-effort (results do not need to survive a restart).

**Why:** The task's own rule 9 ("NO agent changes... do not edit... the
agent loop logic") is explicit, and `_write_artifacts`'s directory
constant is part of that file. Routing the one artifact-path need
through the already-returned `AgentResult.run_id` (or the first event's
`run_id`) costs nothing and keeps the boundary clean: the API is a
pure caller, not a co-maintainer, of the agent loop.

**Alternatives rejected:** Adding an `artifacts_dir` parameter to
`run_agent`/`_write_artifacts` so artifacts could live under
`SA_DATA_DIR` too -- rejected outright, exactly the kind of agent-loop
edit this task forbids. Making the API's public run id identical to the
agent's internal one by having the API generate it and somehow
threading it through -- not possible without the same forbidden edit,
since `run_agent` always calls `new_run_id()` itself.

## D-068 — Hand-rolled rate limiting (no new library), mirroring ZoneWise's pattern

**Date:** 2026-10-24

**Decision:** Public-safety limiting (`src/sandbox_analyst/api/
limits.py`) is a small hand-written `RateLimiter` class (in-memory
counters, one lock), not a third-party rate-limiting library. It
extends ZoneWise's proven design (per-IP window + one global daily
cap, `X-Forwarded-For` read from the right with a trusted-hop count) by
also reserving a concurrency slot atomically with the rate-limit check,
since this task additionally caps concurrent runs (ZoneWise's API has
no equivalent concurrency limit).

**Why:** ZoneWise's own working API (`D:\projects\delhi-plan-rag\app\
api.py`) uses no rate-limiting library at all -- a `RateLimiter` class
with a `dict[str, deque[float]]` per IP and one more `deque` for the
global cap, all under one lock, single-process, in-memory. That design
is already proven in production for the same "public demo, protect a
free-tier API budget" problem this task has, and this project's own
rule against unnecessary dependencies favors reusing a known-correct
~40-line class over adding a library for something this simple.

**Alternatives rejected:** A library (e.g. `slowapi`) -- rejected, no
new dependency is needed for logic this small, and ZoneWise's own
choice not to use one is direct precedent in this exact codebase family.

## D-069 — New dependencies: fastapi, uvicorn, python-multipart

**Date:** 2026-10-24

**Decision:** Three new runtime dependencies: `fastapi` (the API
framework the task specifies), `uvicorn` (the ASGI server `sa serve`
runs), and `python-multipart` (required by FastAPI/Starlette to parse
the `multipart/form-data` body of `POST /api/datasets`'s CSV upload --
FastAPI raises at request time without it installed). No agent/RAG
framework is added (CLAUDE.md rule 5 is unaffected -- FastAPI is a web
framework, not an agent framework).

**Why:** These are exactly what the task asks for, matching ZoneWise's
own choice of `fastapi`/`uvicorn` versions where sensible.

**Alternatives rejected:** None seriously considered; the task names
these dependencies directly.

## D-070 — Separate upload limits for the public API vs. the sandbox's own cap

**Date:** 2026-10-24

**Decision:** New `Settings` fields (`api_max_upload_mb=5`,
`api_max_rows=200_000`, `api_max_cols=100`, `api_upload_ttl_s=3600`)
guard `POST /api/datasets` specifically, left separate from the
existing `max_upload_mb=25` field that `Sandbox.upload()` already
enforces before a file reaches Modal.

**Why:** These are two different limits for two different reasons: the
API's upload cap exists to keep a stranger from parking a large file on
disk or burning CPU in the host-side CSV profiler (D-042's profiling
step runs on the host, outside the sandbox), while the sandbox's own
cap exists to keep an oversized upload out of the sandbox filesystem.
They happen to currently differ in size (5 MB vs. 25 MB) because the
public-facing limit is deliberately the stricter of the two.

**Alternatives rejected:** Reusing `max_upload_mb` for both purposes --
rejected, conflates two independent concerns and would make tightening
one limit for public-safety reasons silently also change the other.

## D-071 — Public safety limit values and why

**Date:** 2026-10-24

**Decision:** Per-IP: 5 runs/hour, 20 runs/day. Global: 50 runs/day.
Max 2 concurrent runs. Sandbox budget: $0.30 in production (vs. $0.60
reserved for local/laptop use out of the existing $1 total Modal free
credit -- see D-072). All six values are `Settings` fields, overridable
by environment variable without a code change.

**Why:** The whole point of these numbers is protecting two finite,
shared resources from an anonymous public visitor: the $1 Modal free
credit (D-007) and Groq's free per-model quota. 50 global runs/day at
up to 4 attempts each, each attempt a sandbox call, is comfortably
inside both budgets even on a day that hits the cap; 2 concurrent runs
keeps a single visitor from serializing the whole demo for everyone
else behind it, appropriate for a single-instance, single-worker B1
deployment (D-073).

**Alternatives rejected:** No caps at all -- rejected outright, a
public link with no limits against a free-tier budget is a guaranteed
way to exhaust it on day one. Much higher caps -- rejected without
evidence of real demand; these are easy to raise later via an App
Service setting with no redeploy of code.

## D-072 — Modal budget split: $0.60 local, $0.30 production, independent ledgers

**Date:** 2026-10-24

**Decision:** `SA_SANDBOX_BUDGET_USD` is set to `0.30` in the
production App Service setting, leaving the existing local default
(`0.80` in `Settings`, used for `uv run sa ...` on the laptop) alone.
Each environment's ledger file lives on its own machine/container --
the production container's ledger is a fresh file under `SA_DATA_DIR`
there, with no way to read the laptop's `runs/sandbox_ledger.jsonl` or
vice versa.

**Why:** Both environments draw from the same underlying $1 Modal
free-credit account, so splitting the *budget guard's cap* (not the
actual account limit, which Modal itself enforces) keeps either
environment from being able to single-handedly exhaust the whole
credit before the other notices. $0.30 + $0.60 = $0.90, leaving a
$0.10 margin below the $1 total. Modal stops workloads rather than
billing past the free credit (D-005), so the real failure mode of
mis-sizing this is "the demo stops answering," not an unexpected
charge.

**Alternatives rejected:** One shared budget cap/ledger across both
environments -- not possible without a shared, networked ledger store,
which is far more infrastructure than this project's cost story
(D-007) justifies. Giving production the full $0.80 -- rejected, would
leave nothing for continued local development once the demo is live.

## D-073 — Single-instance, in-memory run store on a B1 plan; SSE with keep-alives

**Date:** 2026-10-24

**Decision:** The run store (`api/runs.py`) is a plain in-process
`dict[str, RunRecord]` -- no database, no Redis, no multi-worker
coordination. `sa serve` is documented as a single-worker process.
`GET /api/runs/{id}/events` streams Server-Sent Events, with a
keep-alive comment sent every 15 seconds on an otherwise-idle
connection.

**Why:** The target is a single Azure App Service B1 instance (one
container, no autoscale), the same documented design ZoneWise uses for
its own in-memory rate limiter and request counters. A run's data
living only in that one process's memory is an acceptable trade for a
demo whose whole point is showing a live step timeline, not durable
history. Keep-alives matter because App Service (like most reverse
proxies) drops a connection that's been silent too long; a periodic
SSE comment line (`: keep-alive\n\n`, ignored by `EventSource` clients)
keeps the connection open through a long "the LLM is thinking" gap
between attempts without the client having to poll.

**Alternatives rejected:** A real database for run state -- rejected as
infrastructure this single-instance demo doesn't need. WebSockets
instead of SSE -- rejected; the data only flows server -> client (the
browser never needs to send anything mid-run), which is exactly SSE's
use case, and SSE gets automatic reconnection and plain-HTTP
infrastructure compatibility (proxies, `curl`, no extra handshake) for
free, where WebSockets would need that built by hand for no benefit
here.

## D-074 — Client IP: `X-Forwarded-For`'s rightmost trusted entry when `SA_TRUST_PROXY=true`, else the socket peer

**Date:** 2026-10-24

**Decision:** `api/limits.py`'s `client_ip()` reuses ZoneWise's exact
correctness property: read `X-Forwarded-For` from the **right** (the
entry closest to us, appended by the one proxy we trust), never the
left (attacker-suppliable). `SA_TRUST_PROXY=true` means "trust exactly
one hop" (Azure App Service's own front end); `false` (the default, for
local dev) ignores the header entirely and uses the raw socket peer
address.

**Why:** This is a direct reuse of a already-correct, already-live
pattern from `D:\projects\delhi-plan-rag\app\api.py` (read-only
reference, per this task's instructions) -- that code's own comment
explains why counting from the right matters: a caller sending a forged
`X-Forwarded-For: 1.2.3.4` just gets their real address appended after
it by the trusted proxy and is rate-limited by that real address
anyway, whereas reading the left-most entry would let anyone bypass the
limiter by rotating a fake header. The one simplification from
ZoneWise's `TRUSTED_PROXY_HOPS: int` is a plain `bool`, since this
deployment only ever sits behind at most one trusted proxy (Azure's own
front end) -- a hop *count* is unneeded generality here.

**Alternatives rejected:** Reading the left-most `X-Forwarded-For`
entry, or trusting the header unconditionally -- both rejected for the
spoofing reason above; this is exactly the mistake ZoneWise's own
design note warns against.

## D-075 — Chart artifacts stay PNG-only, served by strict-pattern name, not by trusting the agent's own path string

**Date:** 2026-10-24

**Decision:** `GET /api/runs/{run_id}/artifacts/{name}` validates
`name` against a fixed pattern (`^attempt\d+_\d+\.png$`, matching
exactly what `agent/loop.py`'s `_write_artifacts` ever generates) before
joining it to the run's artifact directory, and re-checks the resolved
path's parent against that same directory before reading the file. The
endpoint never opens a path built from unvalidated user input, even
though in practice the only paths a legitimate client would ever ask
for come from chart URLs the API itself generated.

**Why:** Defense in depth for a public, unauthenticated endpoint that
takes a path segment from the client and turns it into a filesystem
read -- validating strictly here costs nothing and removes path
traversal as a question entirely, rather than relying on "no legitimate
client would ever send something else."

**Alternatives rejected:** Trusting `name` once it's been checked to
not contain `/`, `\`, or `..` -- rejected as weaker than a full allowed-
pattern match; a fixed regex that matches the agent's own naming scheme
exactly is strictly safer and no harder to write.

## D-076 — Production sandbox budget ledger path reuses `ModalSandbox`'s existing constructor parameter; SSE drops `Request.is_disconnected()`

**Date:** 2026-10-25

**Decision:** `build_app`'s `sandbox_factory` constructs
`ModalSandbox(settings, ledger_path=SA_DATA_DIR/"sandbox_ledger.jsonl")`
directly -- `ModalSandbox.__init__` already accepts an optional
`ledger_path` (predates this task), so routing the budget ledger under
`SA_DATA_DIR` needed no sandbox-code change, only a different call site
in the API layer. Separately, `GET /api/runs/{id}/events`'s SSE
generator does NOT call Starlette's `Request.is_disconnected()` to
detect an abandoned client; the loop relies solely on
`asyncio.wait_for(queue.get(), timeout=15)` plus the run's own terminal
state/close-sentinel to end the generator.

**Why:** For the ledger path: exactly the same "reuse an existing seam
instead of editing agent/sandbox code" approach as D-067's artifact/
trace handling. For dropping `is_disconnected()`: building this task's
own test suite against `TestClient` reproduced a real, reliably
repeatable hang -- opening an SSE stream and calling
`await request.is_disconnected()` inside the generator's wait loop
never returned under Starlette's `TestClient` transport (confirmed by
isolating the exact line with staged, flushed prints; removing only
that call made the identical test pass immediately). This is a known
category of issue with that call across various ASGI execution
contexts, not something safe to assume away for a public endpoint.
Since the generator already terminates deterministically once the run
reaches a terminal status (the worker thread always pushes a close
signal in its `finally` block, and the run itself is bounded by
`agent/loop.py`'s own `TIME_BUDGET_S=300s`), disconnect detection isn't
load-bearing for correctness -- worst case, an abandoned connection's
generator keeps a small amount of server state alive for at most one
run's duration, which is an acceptable cost at this demo's scale.

**Alternatives rejected:** Keeping `is_disconnected()` and papering over
the hang with a timeout wrapper around it -- rejected as treating a
known-flaky primitive as load-bearing when the design doesn't actually
need it; simpler to remove the dependency entirely. Pinning the
investigation to "maybe it's a TestClient-only artifact, so it's safe
in production" -- rejected as an unverified assumption not worth
risking against a real, reproduced failure.

## D-077 — Production Dockerfile: single Python stage today, a marked spot for Prompt 6's Node stage

**Date:** 2026-10-25

**Decision:** `Dockerfile` mirrors the ZoneWise project's working
pattern (`python:3.12-slim`, `uv` copied from its own published image
and used with `--frozen`, a non-root user, `HEALTHCHECK` hitting
`/api/health`) but is single-stage for now, since there is no `web/`
directory yet -- Prompt 6 is explicitly the one that adds the React UI.
The spot where ZoneWise's `FROM node:20-slim AS web` stage and its
later `COPY --from=web ...` line would go is left as a commented block
in place, not an empty stub stage, so Prompt 6 can paste ZoneWise's own
proven commands in directly. `SA_DATA_DIR=/home/sa-data` and
`SA_SANDBOX=modal`/`SA_LLM_PROVIDER=groq`/`SA_LLM_MODEL=openai/gpt-oss-20b`
are baked in as image defaults (every one still overridable by an App
Service setting); `GROQ_API_KEY`, `MODAL_TOKEN_ID`, `MODAL_TOKEN_SECRET`,
`SA_SANDBOX_BUDGET_USD`, and `SA_TRUST_PROXY` are deliberately left
unset in the image, since Task 6's deploy guide requires them to be set
explicitly as App Service settings (D-071/D-072's production-specific
values), and baking a default here would make that instruction
misleading.

**Why:** Copying a working, already-debugged pattern (uv's own
published-image copy trick, the non-root user, the `HEALTHCHECK`
shape) is strictly better than re-deriving it from scratch, and this
task's instructions explicitly ask for that. A commented-out stage
(rather than silence, or a stub that does nothing) documents the
intended shape for whoever writes Prompt 6, without actually adding a
Node toolchain or any web/ dependency to this image today.

**Alternatives rejected:** A fully generic two-stage Dockerfile with an
empty `web/` placeholder directory committed now -- rejected, adds
files and a build stage for a frontend that doesn't exist yet, for no
benefit over a clear comment. Baking `SA_SANDBOX_BUDGET_USD=0.30` into
the image -- rejected, Task 6 explicitly lists it as an App Setting the
user configures by hand, and a baked default would make that setting
look redundant instead of required.

## D-078 — `.dockerignore` mirrors ZoneWise's structure and reasoning

**Date:** 2026-10-25

**Decision:** `.dockerignore` excludes exactly what this task asked for
(`.env*` with `!.env.example`, `data/`, `runs/`, `notes/`, `.venv/`,
`tests/`, `.git/`) plus the same obviously-safe additions ZoneWise's
own `.dockerignore` already makes (`__pycache__/`, tool caches,
`.github/`, `docs/` and `*.md` except `README.md`, editor/OS litter,
`web/node_modules/`/`web/dist/` for Prompt 6's future stage). `eval/`
is also excluded -- it holds only `split.json` (file names and question
counts, D-041), which the running API never reads.

**Why:** Direct reuse of a pattern already proven to keep secrets and
unnecessary bulk out of a real image for a structurally similar
project, with the comment explaining WHY each group is excluded kept
alongside it (consistent with this project's own documentation
discipline) rather than a bare file list.

**Alternatives rejected:** A minimal `.dockerignore` with only the six
things this task named -- rejected, the extra entries cost nothing and
close real gaps (e.g. an accidentally-committed `.mypy_cache/` or a
stray `web/node_modules/` from local frontend work would otherwise
bloat the build context once Prompt 6 adds `web/`).

## D-079 — CI's image job mirrors ZoneWise's GHCR push exactly; Azure redeploy is new (ZoneWise has none to mirror)

**Date:** 2026-10-25

**Decision:** `.github/workflows/ci.yml` keeps the existing `test` job
unchanged and adds `image` (builds/pushes
`ghcr.io/dhruv-ship-it/sandbox-analyst:latest` and `:<short sha>`,
`needs: test`, gated to `push` + `refs/heads/main`, `packages: write`,
`APP_VERSION=<short sha>` passed as a `--build-arg`) using the exact
same steps as ZoneWise's `image.yml` job (owner lower-casing, short-SHA
tagging, `docker/build-push-action@v6` with `cache-from`/`cache-to:
type=gha`). A third job, `deploy-azure`, is new -- checked ZoneWise's
own `.github/workflows/` and `docs/DEPLOY.md` directly (read-only
reference) and confirmed it has **no** automatic Azure-redeploy step at
all: its own documented flow is "image workflow runs, then a human
clicks Restart in the Azure portal," which is also this project's
default/fallback. `deploy-azure` is guarded on two things being present
-- the `AZURE_WEBAPP_PUBLISH_PROFILE_SA` secret and an
`AZURE_WEBAPP_NAME_SA` repo variable (the app name, not secret) -- and
cleanly no-ops (prints why, in the step summary) when either is
missing, which is the expected state today since the Azure Web App
doesn't exist until Task 6 is done by hand.

**Why:** The task instruction was explicitly conditional ("if ZoneWise
triggers Azure to pull the new image... mirror that step"), and it
doesn't -- so there is nothing to copy there, only to add net-new,
carefully guarded so it changes nothing about today's deploy story
(still manual, still matching ZoneWise's own proven pattern) until
someone deliberately sets the secret. The `APP_VERSION` build-arg
exists because the running container has no `.git` directory
(`.dockerignore`) for `Settings.app_version`'s git-SHA fallback to use
at runtime -- baking the real commit SHA in at build time is what makes
`GET /api/health`'s `version` field meaningful in production at all,
and tying it to the same short SHA used for the image tag means "the
version the container reports" and "the tag that container was built
from" are always the same string.

**Alternatives rejected:** Inventing an Azure CD mechanism and
presenting it as "what ZoneWise does" -- rejected as inaccurate; the
task's own phrasing already anticipates "if" ZoneWise has this, so
reporting the true negative (checked, it doesn't) is the honest answer,
with the optional job added as separate, clearly-labeled new scope.
Requiring `AZURE_WEBAPP_NAME_SA` as a second secret instead of a plain
repo variable -- rejected, the app name isn't sensitive and a plain
variable is one fewer thing for the user to mark as a secret
unnecessarily.

## D-080 — Frontend pinned to Vite 5 / React 18 / TypeScript 5.7, not the newest majors

**Date:** 2026-10-25

**Decision:** `web/package.json` pins `vite@^5.4.21`,
`@vitejs/plugin-react@^4.7.0`, `react@^18.3.1`, `react-dom@^18.3.1`,
`typescript@^5.7.3`, `vitest@^2.1.9`, `jsdom@^25.0.1`. `npm create
vite@latest` (the obvious starting point) scaffolds Vite 8 + TypeScript
6 today, and `npm install` on that scaffold failed outright on this
machine's Node v20.14.0 (`npm warn EBADENGINE ... required: { node:
'^20.19.0 || >=22.12.0' }`, then a hard npm resolver crash). Node itself
clears this task's own gate (>=18), but the newest tool majors don't
run on it, so `web/` was rebuilt by hand on the last minor version in
each major line that still supports Node 18+.

**Why:** A frontend that can't `npm install` on the actual development
machine is useless regardless of how current its dependency versions
are; "current and broken" is strictly worse than "a few minor versions
behind and working." Vite 5 / React 18 / TS 5.7 are all still
actively-maintained lines, not abandoned ones.

**Known trade-off:** `npm audit` reports 6 vulnerabilities (3 moderate,
1 high, 2 critical) in `esbuild`/`vitest`'s `tinypool`/`@vitest/mocker`
transitive deps, all fixed only by upgrading to the Vite 6 / Vitest 4
line (a breaking change this task didn't take). Every one of them is a
*dev-server-only* issue (the esbuild CVE is "a malicious website can
query your local `vite dev` server"; the vitest ones are in the test
runner's worker-pool/mocking internals) -- none of it ships in
`vite build`'s output or runs inside the production Docker image,
which never executes `vite dev` or `vitest`. Accepted as-is rather than
chasing a breaking upgrade for a risk with no production exposure.

**Alternatives rejected:** Forcing the Node-incompatible latest majors
through anyway (e.g. by overriding the engine check) -- rejected, that
papers over a real compatibility problem rather than fixing it, and
risks subtler runtime breakage than the install-time crash already
surfaced.

## D-081 — The two extra frontend libraries: `prismjs` (code highlighting) and `diff` (line diff), both consumed as data, never as HTML

**Date:** 2026-10-25

**Decision:** Of the "at most two small libraries" this task's
dependency budget allows beyond react/react-dom/vite/typescript/vitest,
the two chosen are `prismjs` (tokenizing Python source for syntax
highlighting) and `diff` (`diffLines`, for the repair-step code diff).
Both are used purely as *data* producers -- Prism's tokenizer and
`diffLines` each return plain arrays of strings/objects, which the UI
renders as ordinary React children (`<span>{token}</span>`), never by
building an HTML string and injecting it.

**Why:** Rule 7 for this task is categorical: no
`dangerouslySetInnerHTML`, model output (which includes the LLM-written
Python code itself) rendered as plain text only. A conventional
highlighter that hands back an HTML string (or a React wrapper that
calls `dangerouslySetInnerHTML` internally, as most do) would violate
that outright. Using Prism's lower-level tokenize API instead of its
`highlight()`-to-HTML API keeps syntax coloring while every character
of the model's own code still only ever reaches the DOM through React's
normal, auto-escaping text-child rendering -- so even a code string
engineered to contain literal `<script>` tags can never execute.

**Alternatives rejected:** `react-syntax-highlighter` -- pulls in
`refractor`/`lowlight` plus per-language grammar bundles, far heavier
than this project's "minimal dependencies, no UI kit" rule wants for
one language (Python). `highlight.js` -- its primary API expects to own
a DOM node (`hljs.highlightElement`), which is a worse fit than
Prism's string-in/tokens-out `tokenize()` for a React-controlled tree.

## D-082 — No `@testing-library/react`; component tests use a ~20-line custom render helper

**Date:** 2026-10-25

**Decision:** `web/src/testUtils.tsx` exports one helper,
`renderToContainer`, built directly from `react-dom/client`'s
`createRoot` and React's own `act`. Component tests render through it
and assert on `container.textContent` / `container.querySelector(...)`
rather than through `@testing-library/react`'s `render`/`screen` API.

**Why:** This task's dependency budget is explicit and small (five
named packages plus at most two "small libraries," already spent on
`prismjs` and `diff` -- D-081). `@testing-library/react` is exactly the
kind of well-justified-but-still-a-dependency addition that budget
exists to push back on, and a full DOM-query/event-simulation library
isn't needed for this project's test list (render fixture data, check
rendered text, check a tag didn't parse as an element) -- `jsdom` +
`vitest` (both already explicitly sanctioned for component tests by
this task's own text) plus ~20 lines of `createRoot`/`act` cover it.

**Alternatives rejected:** Treating `@testing-library/react` as
"basically part of vitest" and adding it anyway -- rejected, it's a
separate, real package with its own version lifecycle and the budget
language doesn't carve out an exception for test-only libraries beyond
the jsdom/vitest combination the task itself names.

