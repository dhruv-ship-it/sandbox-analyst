"""The dev/test split, by CSV file, with a fixed seed.

Splitting by file (not by question) keeps every question about a
given CSV on the same side of the split, so nothing learned from a
file's structure while developing on dev can leak into the held-out
test set (D-041). `load_split("test")` is gated: it only works on a
clean working tree checked out at a `frozen-*` tag, so loading the
test split outside a real, intentional frozen evaluation run requires
actively lying to this function, not just forgetting a flag.
"""

import json
import random
import subprocess
from collections.abc import Callable
from pathlib import Path

from .dabench import Question, load_questions

SPLIT_SEED = 2026
DEV_MIN_FRACTION = 0.20
FROZEN_TAG_PREFIX = "frozen-"

DEFAULT_SPLIT_PATH = Path("eval/split.json")
DEFAULT_QUESTIONS_PATH = Path("data/dabench/da-dev-questions.jsonl")

GitRunner = Callable[..., subprocess.CompletedProcess]


class SplitLockedError(Exception):
    """load_split("test") is refused unless the repo is clean and tagged frozen-*."""


def _run_git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=False)


def _repo_is_clean(git_run: GitRunner) -> bool:
    result = git_run("status", "--porcelain")
    return result.returncode == 0 and result.stdout.strip() == ""


def _head_has_frozen_tag(git_run: GitRunner) -> bool:
    result = git_run("tag", "--points-at", "HEAD")
    if result.returncode != 0:
        return False
    tags = result.stdout.strip().splitlines()
    return any(tag.startswith(FROZEN_TAG_PREFIX) for tag in tags)


def compute_split(questions: list[Question], seed: int = SPLIT_SEED) -> dict[str, list[str]]:
    """Return {"dev": [file names...], "test": [file names...]}, sorted."""
    questions_per_file: dict[str, int] = {}
    for q in questions:
        questions_per_file[q.file_name] = questions_per_file.get(q.file_name, 0) + 1

    shuffled_files = sorted(questions_per_file)
    random.Random(seed).shuffle(shuffled_files)

    threshold = DEV_MIN_FRACTION * len(questions)
    dev_files: list[str] = []
    dev_question_count = 0
    for name in shuffled_files:
        if dev_question_count >= threshold:
            break
        dev_files.append(name)
        dev_question_count += questions_per_file[name]

    dev_set = set(dev_files)
    test_files = [name for name in shuffled_files if name not in dev_set]
    return {"dev": sorted(dev_files), "test": sorted(test_files)}


def _side_payload(file_names: list[str], questions_by_file: dict[str, list[Question]]) -> dict:
    side_questions = [q for name in file_names for q in questions_by_file.get(name, [])]
    by_level: dict[str, int] = {}
    for q in side_questions:
        level = q.level or "unknown"
        by_level[level] = by_level.get(level, 0) + 1
    return {
        "files": file_names,
        "question_ids": sorted(q.id for q in side_questions),
        "n_questions": len(side_questions),
        "by_level": by_level,
    }


def write_split(
    questions: list[Question],
    path: Path = DEFAULT_SPLIT_PATH,
    seed: int = SPLIT_SEED,
) -> dict:
    """Compute the split and write it to `path`. Returns the written payload."""
    split = compute_split(questions, seed=seed)

    questions_by_file: dict[str, list[Question]] = {}
    for q in questions:
        questions_by_file.setdefault(q.file_name, []).append(q)

    payload = {
        "seed": seed,
        "dev": _side_payload(split["dev"], questions_by_file),
        "test": _side_payload(split["test"], questions_by_file),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return payload


def load_split(
    name: str,
    split_path: Path = DEFAULT_SPLIT_PATH,
    git_run: GitRunner = _run_git,
) -> dict:
    """Load one side of eval/split.json. "test" is gated -- see module docstring."""
    if name not in ("dev", "test"):
        raise ValueError(f"unknown split name: {name!r} (expected 'dev' or 'test')")

    if name == "test":
        if not _repo_is_clean(git_run):
            raise SplitLockedError(
                "the working tree is not clean; commit or stash before loading the test split"
            )
        if not _head_has_frozen_tag(git_run):
            raise SplitLockedError(
                f"HEAD has no tag starting with {FROZEN_TAG_PREFIX!r}; "
                "the test split only loads for a real frozen evaluation run"
            )

    payload = json.loads(split_path.read_text(encoding="utf-8"))
    return payload[name]


def main() -> int:
    questions = load_questions(DEFAULT_QUESTIONS_PATH)
    payload = write_split(questions)
    print(  # noqa: T201
        f"wrote {DEFAULT_SPLIT_PATH}: "
        f"dev={payload['dev']['n_questions']} questions/{len(payload['dev']['files'])} files, "
        f"test={payload['test']['n_questions']} questions/{len(payload['test']['files'])} files"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
