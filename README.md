# Sandbox Analyst

**[Live demo →](https://sandbox-analyst-dhruv-b7fxbugddpemc6hr.uaenorth-01.azurewebsites.net/)**

Sandbox Analyst is an AI data analyst: upload a CSV, ask a question in
plain English, and get back an answer backed by code that actually ran.
The agent writes a pandas script, a static checker screens it, and it
executes inside a network-isolated Modal Sandbox (gVisor) -- never on
the host. If the script fails, the agent reads the structured error and
repairs it, up to three times, each attempt in a brand-new sandbox. The
final answer is checked against the script's own output before it's
shown, and a React UI streams the whole pipeline live: code written,
checked, run, repaired, answered.

![Sandbox Analyst, mid-run](docs/img/demo.png)

## How it works

```mermaid
flowchart LR
    Upload[Upload CSV] --> Profile["Profile<br/>(5-row preview only)"]
    Profile --> Write[LLM writes a script]
    Write --> Check[AST static check]
    Check --> Sandbox["Fresh Modal sandbox<br/>(no network, memory/time limits)"]
    Sandbox --> Evidence[Evidence check]
    Evidence --> Answer[Answer]
    Check -. repair, up to 3x .-> Write
    Sandbox -. repair, up to 3x .-> Write
    Evidence -. repair, up to 3x .-> Write
```

- Every attempt is a complete, fresh script -- no hidden state carries
  over between repairs, so the "evidence" shown is exactly what ran.
- The static checker gives fast, cheap repair feedback; the sandbox
  (gVisor, no outbound network) is the actual security boundary.
- The model never sees the full file -- only a capped, delimited
  preview of column names, dtypes, and a 5-row sample.
- Up to 3 repairs per question, each running in a brand-new sandbox.
- An answer is checked against the script's own stdout before it's
  shown; a value with no matching evidence is reported as unverified,
  not hidden.
- The agent's steps (write, check, run, repair, answer) stream live to
  the browser over Server-Sent Events, so a visitor watches the agent
  work rather than waiting on a single final response.

## Safety model

The Modal sandbox (gVisor isolation, outbound network fully blocked,
memory/CPU/time limits) is the actual security boundary for running
LLM-written code. The AST-only static checker in front of it is defense
in depth and fast repair feedback -- not the thing that makes untrusted
code safe to run; its two known bypasses are documented, not hidden,
because the sandbox is what actually contains them. The dataset preview
sent to the model is wrapped in unforgeable delimiters, so nothing in an
uploaded CSV can pose as a trusted instruction. Every piece of model
output -- code, stdout, explanations, answer values -- renders as plain
text in the UI, never as parsed HTML. The public demo adds one more
layer on top of all that: per-visitor and global run caps, upload
size/row/column limits, and a rate limiter -- needed to keep a public,
free-tier demo from being exhausted by one visitor, not to make
untrusted code safe (the sandbox already does that).

See [docs/security.md](docs/security.md) for the full threat model, the
exact checker rules, and the two known (sandboxed, non-escaping)
bypasses found by red-teaming it.

## Evaluation

Sandbox Analyst is measured on
[InfiAgent-DABench](https://github.com/InfiAgent/InfiAgent), a benchmark
of CSV question-answering tasks with an automatic grader, using a
file-level dev/test split (split by CSV file, not by question, so no
file's structure leaks between the two sets).

The held-out evaluation run happens once, after the system is frozen at
a tagged commit -- not continuously during development, so there's no
way to tune against it by accident. **Results will be published after
the held-out run.** Until then, this README reports no accuracy
numbers.

The original DABench paper reports GPT-4/GPT-3.5 scores using its own
grader; this project's grader is a separate implementation, designed
from (and tested against) only the dev split's labels, so those
published numbers are context, not a direct comparison.

## Tech stack

Python 3.12 + [uv](https://docs.astral.sh/uv/) · FastAPI · React (Vite +
TypeScript) · [Modal](https://modal.com) Sandboxes (gVisor) · Groq
(`openai/gpt-oss-20b`) -- no agent/RAG framework.

## Repo map

```
src/sandbox_analyst/
  config.py     settings, read from the environment and .env
  agent/        the write -> check -> run -> repair loop, profiling, events/traces
  guard/        the AST-only static checker
  sandbox/      the Sandbox protocol, FakeSandbox, ModalSandbox
  llm/          a provider-agnostic LLM client (record/replay for tests)
  bench/        InfiAgent-DABench download, dev/test split, grader, eval harness
  api/          the FastAPI app: uploads, runs, SSE, public-safety limits
web/            the React (Vite + TypeScript) UI
eval/split.json file names + question ids per split -- no question/label content
docs/           design docs: security, API, UI, deploy, DABench, results
notes/          private engineering journal (gitignored, never committed)
```

## Local setup (PowerShell)

```powershell
# Backend
uv sync
uvx modal token new         # one-time Modal auth
Copy-Item .env.example .env
# fill in GROQ_API_KEY (or NIM_API_KEY) in .env
uv run sa serve              # http://localhost:8000

# Frontend, in a second terminal
cd web
npm install
npm run dev                  # proxies /api to localhost:8000
```

See [docs/ui.md](docs/ui.md) and [docs/api.md](docs/api.md) for the
full local-dev and endpoint details, and [CLAUDE.md](CLAUDE.md) for
development rules and commands.

## Project status

**Done:** the agent loop (write/check/run/repair), the static checker,
the Modal sandbox backend, a provider-agnostic LLM client, the DABench
download and dev/test split, a FastAPI app with an SSE step timeline,
the React UI, CI, and a live deployment on Azure.

**Next:** a red-team suite for the static checker and the sandbox (each
tested with the other layer disabled), and the frozen, held-out DABench
evaluation (3 runs, bootstrap confidence intervals) this README's
Evaluation section is waiting on.

See [docs/PLAN.md](docs/PLAN.md) for the full phased plan.

## Licence

MIT -- see [LICENSE](LICENSE).

This project uses the InfiAgent-DABench validation set, downloaded by
script from Hugging Face at a pinned revision. Per the original
authors' GitHub README, the dataset is licensed CC BY-NC 4.0. It is
never redistributed in this repository -- only downloaded locally by
the scripts here.

## Credits

[InfiAgent-DABench](https://github.com/InfiAgent/InfiAgent)
([paper](https://arxiv.org/abs/2401.05507)) for the benchmark this
project is measured on.
