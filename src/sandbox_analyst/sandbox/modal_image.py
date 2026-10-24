"""The Modal image definition for the sandbox.

Built remotely by Modal, never locally. Package versions are pinned to
a resolver-verified, mutually compatible set (see DECISIONS.md D-024
and docs/sandbox-env.md for how they were chosen and their build time).
"""

from pathlib import Path

import modal

RUNNER_PATH = "/opt/sandbox_analyst/runner.py"

PINNED_PACKAGES = (
    "pandas==3.1.0",
    "numpy==2.5.4",
    "scipy==1.18.1",
    "scikit-learn==1.9.1",
    "statsmodels==0.15.0",
    "matplotlib==3.11.2",
    "seaborn==0.13.2",
)

_RUNNER_LOCAL_PATH = Path(__file__).parent / "runner.py"


def build_image() -> modal.Image:
    return (
        modal.Image.debian_slim(python_version="3.12")
        .pip_install(*PINNED_PACKAGES)
        .add_local_file(str(_RUNNER_LOCAL_PATH), RUNNER_PATH, copy=True)
    )
