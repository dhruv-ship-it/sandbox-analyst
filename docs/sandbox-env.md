# sandbox-env.md

The Modal sandbox image, and what the live test suite
(`tests/sandbox/test_modal_live.py`, `pytest -m live`) found when run
against a real Modal account.

## Image

`modal.Image.debian_slim(python_version="3.12")`, with the analysis
libraries pinned to a resolver-verified, mutually compatible set (`uv
pip compile` against live PyPI metadata on 2026-10-24 — not guessed
from memory, since package ecosystems move fast and this repo's
knowledge cutoff predates "now"):

```
pandas==3.1.0
numpy==2.5.4
scipy==1.18.1
scikit-learn==1.9.1
statsmodels==0.15.0
matplotlib==3.11.2
seaborn==0.13.2
```

The trusted runner (`src/sandbox_analyst/sandbox/runner.py`) is baked
into the image at `/opt/sandbox_analyst/runner.py` via
`Image.add_local_file(..., copy=True)`, so it's part of the built image
layer rather than synced from local disk on every sandbox creation.

The image is built remotely by Modal on first use per build-cache key;
the build is never run on the host.

## Live test results — 2026-10-24, Modal profile `dhruv-ship-it`

All 13 live checks pass (`uv run pytest -m live -v --durations=0`).

| Check (task spec item) | Result |
|---|---|
| (a) first run incl. image build / wall time | cold: **38.6s** wall (ledger `alive_s` 36.4s); warm trivial run: **9.2s** wall, settling to **6.3-10.3s** across later runs |
| (b) pinned library versions printed from inside the sandbox | confirmed all 7 pins match exactly |
| (c) uploaded CSV readable with pandas | pass — `pd.read_csv` on an uploaded file sums correctly |
| (d) matplotlib figure returned as PNG | pass — 1 PNG captured, starts with the PNG magic bytes |
| (e) network fully blocked (HTTP, raw socket, DNS) | **all three fail** inside the sandbox; a host-side control test confirms the same three succeed outside it, so the block is real, not an artifact of a dead network path |
| (f) `while True: pass` @ 5s timeout -> next run works | pass — timed out as expected, and the next call (a fresh sandbox) ran normally |
| (g) `os._exit(1)` | pass — structured result, `exit_code == 1`, `error is None` (no Python exception to capture), no hang |
| (h) ~8 GB allocation under the 2 GiB limit | **the whole sandbox container is OOM-killed**, not just the exec'd process — Modal's API then reports the container gone (`NotFoundError`), which `ModalSandbox` maps to `SandboxCrashed`. No hang either way; see D-025. |
| (i) 1 MB of stdout | pass — `truncated=True`, capped output |
| (j) state isolation between runs | pass — a file written in one run does not exist in the next |
| (k) ledger total / average | see below |

### Cost (lower bound — reservation only, bursting above it is billed but not counted here)

- Sandboxes created during this test session: **14** (13 test functions;
  two of them each create two sandboxes to prove fresh-per-run
  behavior).
- Ledger total so far: **$0.002372**
- Average per sandbox: **$0.000169**
- At this rate, the $0.80 ledger cap covers roughly 4,700 more
  sandboxes of this size — comfortably inside the project's expected
  usage. Cross-check this estimate against Modal's own usage page
  (it will read somewhat higher, since it also bills any bursting
  above the 0.25 CPU / 1 GiB reservation that this estimate doesn't
  count).

## Findings worth documenting

- **Exec-level timeout is a synthetic `-1` returncode, not an
  exception.** Reading the installed SDK source (modal 1.6.2)
  confirmed `Sandbox.exec(..., timeout=...)`'s `ContainerProcess.wait()`
  swallows `ExecTimeoutError` internally and sets `returncode = -1`
  rather than raising — so `ModalSandbox` checks for that sentinel
  value rather than catching an exception (see D-026).
- **A hard memory-limit violation kills the sandbox container, not
  just the process.** `bytearray(8 * 1024**3)` under a 2048 MiB hard
  limit causes the *entire* sandbox to disappear; the next SDK call
  against it (reading `stdout`/`stderr`) raises
  `modal.exception.NotFoundError`. `ModalSandbox` already maps any
  `modal.exception.Error` raised mid-run to `SandboxCrashed`, which
  turns out to be exactly the right semantics for this case (see
  D-025) — no special-casing was needed once the taxonomy was already
  there for "infrastructure failure, not user-code failure."
