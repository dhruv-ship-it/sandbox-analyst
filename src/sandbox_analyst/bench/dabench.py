"""DABench's own JSONL schema: a question, its label, and loaders.

Field names and shapes confirmed by reading the real downloaded JSONL
(see docs/dabench.md) rather than assumed from the paper. Notably, a
label's raw field is `common_answers` (not `answers`) and holds a list
of `[name, value]` pairs -- more than one for multi-part questions.
"""

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Question:
    id: int
    question: str
    concepts: list[str]
    constraints: str
    format: str
    file_name: str
    level: str | None = None


@dataclass(frozen=True)
class Label:
    id: int
    answers: list[tuple[str, str]]


def _read_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def load_questions(path: Path) -> list[Question]:
    return [
        Question(
            id=row["id"],
            question=row["question"],
            concepts=row["concepts"],
            constraints=row["constraints"],
            format=row["format"],
            file_name=row["file_name"],
            level=row.get("level"),
        )
        for row in _read_jsonl(path)
    ]


def load_labels(path: Path) -> list[Label]:
    return [
        Label(id=row["id"], answers=[(name, value) for name, value in row["common_answers"]])
        for row in _read_jsonl(path)
    ]
