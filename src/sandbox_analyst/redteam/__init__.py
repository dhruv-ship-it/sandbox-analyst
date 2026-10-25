"""The red-team suite: categories A-D, layer isolation, canaries, and the report.

Every case uses our own synthetic data (never DABench). See
`docs/redteam-dry-run.md` / `docs/PLAN.md` for the design, and
DECISIONS.md (D-101+) for why each category is shaped the way it is.
"""

from .cases import CaseResult
from .runner import RedteamOutcome, run_redteam

__all__ = ["CaseResult", "RedteamOutcome", "run_redteam"]
