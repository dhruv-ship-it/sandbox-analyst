# Sandbox Analyst

**Status: under construction.**

Sandbox Analyst is an AI data analyst: a user uploads a CSV and asks a
question in plain English, an agent writes a pandas script, statically
checks it, and runs it in a network-isolated Modal Sandbox (gVisor). It
reads the output or the error, repairs its script (up to 3 times), and
answers with executed evidence — the code that ran, its output, and any
chart it produced. It is measured on
[InfiAgent-DABench](https://github.com/InfiAgent/InfiAgent).

## Setup (PowerShell)

```powershell
# Install uv if you don't have it: https://docs.astral.sh/uv/
uv sync

# Authenticate Modal (one-time, stores credentials in your Modal CLI profile)
uvx modal token new

# Copy the env template and fill in real values (.env is gitignored)
Copy-Item .env.example .env

uv run pytest
```

See [CLAUDE.md](CLAUDE.md) for the full set of development rules and
commands, and [docs/PLAN.md](docs/PLAN.md) for the phased build plan.

## Data notice

This project uses the InfiAgent-DABench validation set, downloaded by
script from Hugging Face at a pinned revision. Per the original
authors' GitHub README, the dataset is licensed CC BY-NC 4.0. It is
never redistributed in this repository — only downloaded locally by the
scripts in this repo.
