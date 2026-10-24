"""Download and verify the InfiAgent-DABench dataset.

Run as:

    uv run python -m sandbox_analyst.bench.download

Downloads into data/dabench/ (gitignored, never committed), with the
Hugging Face cache also kept under data/ so nothing lands on the
system drive. Verifies the dataset's known-good shape (D-011/D-040),
then writes data/dabench/manifest.json. If any check fails, this
script stops and reports the actual numbers it found -- it never
adjusts the expected counts to match the data (see CLAUDE.md rule 9).
"""

import hashlib
import json
import sys
from pathlib import Path

from huggingface_hub import snapshot_download

REPO_ID = "infiagent/DABench"

# Resolved via HfApi().dataset_info("infiagent/DABench").sha on 2026-10-24.
# Pinned so a re-run always downloads this exact dataset version, not
# whatever the repo looks like whenever the script happens to run (D-040).
PINNED_REVISION = "b455d578e30fee513abd79936cbdf7a6de026cb5"

DATA_DIR = Path("data")
LOCAL_DIR = DATA_DIR / "dabench"
CACHE_DIR = DATA_DIR / ".cache" / "huggingface"
MANIFEST_PATH = LOCAL_DIR / "manifest.json"

QUESTIONS_FILE = "da-dev-questions.jsonl"
LABELS_FILE = "da-dev-labels.jsonl"
TABLES_DIR = "da-dev-tables"

EXPECTED_N_QUESTIONS = 257
EXPECTED_N_LABELS = 257
EXPECTED_N_DISTINCT_CSVS = 52


class VerificationError(Exception):
    """One or more DABench shape checks failed; see .errors for the detail lines."""

    def __init__(self, errors: list[str]) -> None:
        super().__init__("DABench verification failed:\n" + "\n".join(f"  - {e}" for e in errors))
        self.errors = errors


def _read_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(local_dir: Path = LOCAL_DIR, cache_dir: Path = CACHE_DIR) -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    snapshot_download(
        repo_id=REPO_ID,
        repo_type="dataset",
        revision=PINNED_REVISION,
        local_dir=str(local_dir),
        cache_dir=str(cache_dir),
    )
    return local_dir


def verify(local_dir: Path) -> dict:
    """Check the dataset's known-good shape. Raises VerificationError; never adjusts
    the expected counts to match what it finds."""
    questions = _read_jsonl(local_dir / QUESTIONS_FILE)
    labels = _read_jsonl(local_dir / LABELS_FILE)

    errors = []

    if len(questions) != EXPECTED_N_QUESTIONS:
        errors.append(f"expected {EXPECTED_N_QUESTIONS} questions, found {len(questions)}")
    if len(labels) != EXPECTED_N_LABELS:
        errors.append(f"expected {EXPECTED_N_LABELS} labels, found {len(labels)}")

    question_ids = {q["id"] for q in questions}
    label_ids = {label["id"] for label in labels}
    if question_ids != label_ids:
        missing_labels = question_ids - label_ids
        extra_labels = label_ids - question_ids
        errors.append(
            f"question/label id mismatch: {len(missing_labels)} question(s) without a "
            f"label, {len(extra_labels)} label(s) without a question"
        )

    referenced_csvs = {q["file_name"] for q in questions}
    missing_csvs = sorted(
        name for name in referenced_csvs if not (local_dir / TABLES_DIR / name).exists()
    )
    if missing_csvs:
        errors.append(
            f"{len(missing_csvs)} referenced CSV(s) missing from {TABLES_DIR}/: {missing_csvs}"
        )

    if len(referenced_csvs) != EXPECTED_N_DISTINCT_CSVS:
        errors.append(
            f"expected {EXPECTED_N_DISTINCT_CSVS} distinct referenced CSVs, "
            f"found {len(referenced_csvs)}"
        )

    if errors:
        raise VerificationError(errors)

    return {
        "n_questions": len(questions),
        "n_labels": len(labels),
        "n_distinct_csvs": len(referenced_csvs),
    }


def write_manifest(local_dir: Path, counts: dict, manifest_path: Path = MANIFEST_PATH) -> None:
    files = sorted(
        p
        for p in local_dir.rglob("*")
        if p.is_file() and p != manifest_path and ".cache" not in p.relative_to(local_dir).parts
    )
    sha256_by_relpath = {p.relative_to(local_dir).as_posix(): _sha256(p) for p in files}
    manifest = {
        "repo_id": REPO_ID,
        "revision": PINNED_REVISION,
        **counts,
        "sha256": sha256_by_relpath,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")


def main() -> int:
    local_dir = download()
    try:
        counts = verify(local_dir)
    except VerificationError as exc:
        print(str(exc), file=sys.stderr)  # noqa: T201
        return 1
    write_manifest(local_dir, counts)
    print(f"DABench verified at revision {PINNED_REVISION}: {counts}")  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
