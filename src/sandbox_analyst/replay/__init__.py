"""Replay regression fixtures: synthetic-dataset tasks, LIVE recording, credential scanning.

See docs/testing.md for what the replay suite covers and doesn't, and
`tests/replay/test_replay.py` for the offline pytest that actually runs
in CI.
"""

from .credentials import CREDENTIAL_PATTERNS, scan_cassette_files, scan_text_for_credentials
from .recorder import RecordedTaskResult, RecordReplayOutcome, run_record_replay
from .tasks import ReplayTask, load_tasks

__all__ = [
    "ReplayTask",
    "load_tasks",
    "RecordedTaskResult",
    "RecordReplayOutcome",
    "run_record_replay",
    "CREDENTIAL_PATTERNS",
    "scan_text_for_credentials",
    "scan_cassette_files",
]
