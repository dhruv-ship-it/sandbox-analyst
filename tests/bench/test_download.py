"""Unit tests for the DABench shape checks and manifest writer.

Entirely offline: builds a tiny synthetic directory tree that mimics
DABench's shape (never real DABench data) and checks verify()/
write_manifest() against it. download() itself (a thin wrapper around
huggingface_hub.snapshot_download) is exercised for real by actually
running `python -m sandbox_analyst.bench.download`, not by a unit test.
"""

import json

import pytest

from sandbox_analyst.bench.download import VerificationError, verify, write_manifest


def _write_jsonl(path, rows):
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


def _make_dabench_dir(tmp_path, *, n_questions=3, n_labels=3, csv_names=None, write_csvs=True):
    if csv_names is None:
        csv_names = [f"table_{i}.csv" for i in range(n_questions)]
    questions = [
        {
            "id": i,
            "question": "q",
            "concepts": [],
            "constraints": "c",
            "format": "f",
            "file_name": csv_names[i % len(csv_names)],
            "level": "easy",
        }
        for i in range(n_questions)
    ]
    labels = [{"id": i, "common_answers": [["x", "1"]]} for i in range(n_labels)]

    _write_jsonl(tmp_path / "da-dev-questions.jsonl", questions)
    _write_jsonl(tmp_path / "da-dev-labels.jsonl", labels)

    tables_dir = tmp_path / "da-dev-tables"
    tables_dir.mkdir()
    if write_csvs:
        for name in set(csv_names):
            (tables_dir / name).write_text("a,b\n1,2\n", encoding="utf-8")

    return tmp_path


def test_verify_passes_with_matching_counts(tmp_path, monkeypatch):
    monkeypatch.setattr("sandbox_analyst.bench.download.EXPECTED_N_QUESTIONS", 3)
    monkeypatch.setattr("sandbox_analyst.bench.download.EXPECTED_N_LABELS", 3)
    monkeypatch.setattr("sandbox_analyst.bench.download.EXPECTED_N_DISTINCT_CSVS", 3)

    local_dir = _make_dabench_dir(tmp_path, n_questions=3, csv_names=["a.csv", "b.csv", "c.csv"])
    counts = verify(local_dir)
    assert counts == {"n_questions": 3, "n_labels": 3, "n_distinct_csvs": 3}


def test_verify_fails_on_question_count_mismatch(tmp_path, monkeypatch):
    monkeypatch.setattr("sandbox_analyst.bench.download.EXPECTED_N_QUESTIONS", 999)
    local_dir = _make_dabench_dir(tmp_path, n_questions=3)
    with pytest.raises(VerificationError, match="expected 999 questions, found 3"):
        verify(local_dir)


def test_verify_fails_on_id_mismatch_between_questions_and_labels(tmp_path, monkeypatch):
    monkeypatch.setattr("sandbox_analyst.bench.download.EXPECTED_N_QUESTIONS", 3)
    monkeypatch.setattr("sandbox_analyst.bench.download.EXPECTED_N_LABELS", 3)
    local_dir = _make_dabench_dir(tmp_path, n_questions=3)
    # Overwrite labels with non-matching ids.
    _write_jsonl(
        local_dir / "da-dev-labels.jsonl",
        [{"id": i + 100, "common_answers": [["x", "1"]]} for i in range(3)],
    )
    with pytest.raises(VerificationError, match="id mismatch"):
        verify(local_dir)


def test_verify_fails_when_a_referenced_csv_is_missing(tmp_path, monkeypatch):
    monkeypatch.setattr("sandbox_analyst.bench.download.EXPECTED_N_QUESTIONS", 3)
    monkeypatch.setattr("sandbox_analyst.bench.download.EXPECTED_N_LABELS", 3)
    local_dir = _make_dabench_dir(
        tmp_path, n_questions=3, csv_names=["a.csv", "b.csv", "c.csv"], write_csvs=False
    )
    with pytest.raises(VerificationError, match="missing from da-dev-tables"):
        verify(local_dir)


def test_verify_fails_on_distinct_csv_count_mismatch(tmp_path, monkeypatch):
    monkeypatch.setattr("sandbox_analyst.bench.download.EXPECTED_N_QUESTIONS", 3)
    monkeypatch.setattr("sandbox_analyst.bench.download.EXPECTED_N_LABELS", 3)
    monkeypatch.setattr("sandbox_analyst.bench.download.EXPECTED_N_DISTINCT_CSVS", 999)
    local_dir = _make_dabench_dir(tmp_path, n_questions=3, csv_names=["a.csv", "b.csv", "c.csv"])
    with pytest.raises(VerificationError, match="expected 999 distinct"):
        verify(local_dir)


def test_verify_never_mutates_expectations_on_failure(tmp_path, monkeypatch):
    """Verification reports what it found; it must never adjust the hardcoded expectations."""
    monkeypatch.setattr("sandbox_analyst.bench.download.EXPECTED_N_QUESTIONS", 999)
    local_dir = _make_dabench_dir(tmp_path, n_questions=3)
    with pytest.raises(VerificationError):
        verify(local_dir)

    import sandbox_analyst.bench.download as download_module

    assert download_module.EXPECTED_N_QUESTIONS == 999  # unchanged by the failed call


def test_write_manifest_includes_revision_counts_and_file_hashes(tmp_path):
    local_dir = _make_dabench_dir(tmp_path, n_questions=2, csv_names=["a.csv", "b.csv"])
    manifest_path = local_dir / "manifest.json"
    counts = {"n_questions": 2, "n_labels": 2, "n_distinct_csvs": 2}

    write_manifest(local_dir, counts, manifest_path=manifest_path)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["n_questions"] == 2
    assert manifest["revision"]
    assert "da-dev-questions.jsonl" in manifest["sha256"]
    assert "da-dev-tables/a.csv" in manifest["sha256"]
    assert all(len(h) == 64 for h in manifest["sha256"].values())


def test_write_manifest_excludes_itself(tmp_path):
    local_dir = _make_dabench_dir(tmp_path, n_questions=1, csv_names=["a.csv"])
    manifest_path = local_dir / "manifest.json"
    counts = {"n_questions": 1, "n_labels": 1, "n_distinct_csvs": 1}
    write_manifest(local_dir, counts, manifest_path)
    write_manifest(local_dir, counts, manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert "manifest.json" not in manifest["sha256"]
