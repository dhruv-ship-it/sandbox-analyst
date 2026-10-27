"""Loads tests/replay/tasks.json: one hand-written question per our own synthetic dataset.

Kept in `src/` (not duplicated into tests/) so both the live recording
command (`sa record-replay`) and the offline replay test can share one
loader.
"""

import json
from dataclasses import dataclass
from pathlib import Path

DEFAULT_TASKS_PATH = Path("tests/replay/tasks.json")
DEFAULT_EXAMPLES_DIR = Path("src/sandbox_analyst/api/examples")


@dataclass(frozen=True)
class ReplayTask:
    id: str
    category: str
    dataset: str
    question: str
    constraints: str
    answer_format: str
    expected: dict[str, str]


def load_tasks(path: Path = DEFAULT_TASKS_PATH) -> list[ReplayTask]:
    rows = json.loads(path.read_text(encoding="utf-8"))
    return [
        ReplayTask(
            id=row["id"],
            category=row["category"],
            dataset=row["dataset"],
            question=row["question"],
            constraints=row["constraints"],
            answer_format=row["answer_format"],
            expected=row["expected"],
        )
        for row in rows
    ]
