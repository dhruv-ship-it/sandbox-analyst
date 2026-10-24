# CLAUDE.md

Instructions for any AI agent (or human) working in this repository.

## Hard rules

1. Never execute model-written code or test payloads on the host machine:
   no `exec`/`eval`/`compile`/`subprocess` of such code. Payloads run only
   inside the Modal sandbox, or are only parsed (as AST) by the static
   checker in `src/sandbox_analyst/guard/`.
2. Never commit `.env`, `data/`, `runs/`, `notes/`, keys, or tokens. Never
   read the Modal token file (`%USERPROFILE%\.modal.toml`) or `.env`.
   Stage files by name only; never `git add -A` or `git add .`.
3. One commit per task.
   - Write the commit message to a temp file outside the repo and commit
     with `git commit -F <file>`.
   - Use the git identity already configured (`git config user.name` /
     `user.email`).
   - Do not push unless explicitly asked.
4. Before every commit: `uv run ruff check`, `uv run ruff format --check`,
   `uv run pytest`. All must pass.
5. No agent/RAG frameworks (LangChain, LlamaIndex, CrewAI, ...).
6. Unit tests never touch the network. They use `FakeSandbox` or fake SDK
   objects. Tests that use real services are marked `live` and are
   excluded by default (see `pyproject.toml`'s `addopts`).
7. Do not install Docker or any large host tool. Keep host dependencies
   small — the analysis libraries (pandas, numpy, ...) live only in the
   Modal sandbox image, not on the host.
8. Document every task, with no exceptions:
   - every design choice gets a `DECISIONS.md` entry in plain English;
   - after each task, update `notes/` (see "Documentation" below).
9. On a rate limit or external-service failure, stop cleanly and print
   the exact command to resume with, rather than retrying in a loop.
10. Never poll or loop while waiting on something. If something needs a
    human, stop and say exactly what is needed.

## Commands (PowerShell)

```powershell
uv sync                       # install/update dependencies
uv run ruff check             # lint
uv run ruff format            # format
uv run ruff format --check    # check formatting without changing files
uv run pytest                 # unit tests only (live tests excluded)
uv run pytest -m live -v      # live tests: real Modal sandboxes, costs money
```

## Repo map

Current:

```
src/sandbox_analyst/
  config.py          # pydantic-settings Settings, reads .env
  sandbox/           # Sandbox protocol, ExecResult/ExecError, FakeSandbox,
                      # ModalSandbox, budget ledger
  guard/             # AST-only static checker: policy.py (allowlists/
                      # denylists as data) + check()
tests/               # unit tests, all offline (FakeSandbox / fake SDK)
docs/                # public design docs (PLAN.md, sandbox-env.md, security.md)
notes/               # PRIVATE engineering notes, gitignored, never committed
```

Planned (later tasks, see `docs/PLAN.md`):

```
src/sandbox_analyst/
  llm/               # provider-agnostic LLM client (record/replay for tests)
  agent/             # the write -> check -> run -> repair loop
  bench/             # InfiAgent-DABench download, split, grader
  api/                # FastAPI app (SSE step timeline)
web/                 # React UI
```

## Documentation rule

- `DECISIONS.md` gets one entry per design choice, in plain English,
  with what was decided, why, and what was rejected.
- `notes/` is updated after every task — it is Dhruv's private engineering
  journal, interview prep, and project storyline. It is never committed.
- Any "NOTES CONTEXT" section included in a task prompt gets folded into
  `notes/` (journal, storyline, interview prep, concepts) as part of that
  task's documentation update.
