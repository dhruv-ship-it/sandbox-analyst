"""Trusted code, baked into the sandbox image, that runs the user's script.

This file is never generated or modified by the LLM — it is written once,
by us, and copied into the Modal image at build time. Its only job is to
run /work/task.py and capture what happened in a form the host can parse
reliably (structured JSON, not freeform stderr text).
"""

import json
import os
import runpy
import sys
import traceback
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402 (backend must be set first)

WORKDIR = Path("/work")
TASK_PATH = WORKDIR / "task.py"
OUT_DIR = WORKDIR / "out"
ERROR_PATH = WORKDIR / "error.json"


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for existing in OUT_DIR.iterdir():
        existing.unlink()
    os.chdir(WORKDIR)

    exit_code = 0
    try:
        runpy.run_path(str(TASK_PATH), run_name="__main__")
    except Exception as exc:
        error = {
            "name": type(exc).__name__,
            "value": str(exc),
            "traceback": "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
        }
        ERROR_PATH.write_text(json.dumps(error))
        exit_code = 1
    finally:
        for i, num in enumerate(plt.get_fignums()):
            plt.figure(num).savefig(OUT_DIR / f"fig_{i}.png")

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
