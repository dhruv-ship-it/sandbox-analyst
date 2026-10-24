import subprocess

import pytest

from sandbox_analyst.bench.dabench import Question
from sandbox_analyst.bench.split import (
    SplitLockedError,
    compute_split,
    load_split,
    write_split,
)


def _make_questions(files_and_levels: list[tuple[str, str]]) -> list[Question]:
    return [
        Question(
            id=i,
            question="q",
            concepts=[],
            constraints="c",
            format="f",
            file_name=file_name,
            level=level,
        )
        for i, (file_name, level) in enumerate(files_and_levels)
    ]


def _completed(stdout: str = "", returncode: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout)


# ---- compute_split ----


def test_split_is_deterministic_for_a_fixed_seed():
    questions = _make_questions([(f"f{i}.csv", "easy") for i in range(10)])
    first = compute_split(questions, seed=2026)
    second = compute_split(questions, seed=2026)
    assert first == second


def test_different_seeds_can_produce_different_splits():
    questions = _make_questions([(f"f{i}.csv", "easy") for i in range(10)])
    a = compute_split(questions, seed=1)
    b = compute_split(questions, seed=2)
    assert a != b  # not guaranteed in general, but true for this fixture/seed pair


def test_every_file_appears_in_exactly_one_side():
    questions = _make_questions([(f"f{i}.csv", "easy") for i in range(10)])
    split = compute_split(questions, seed=2026)
    dev, test = set(split["dev"]), set(split["test"])
    assert dev | test == {f"f{i}.csv" for i in range(10)}
    assert dev & test == set()


def test_dev_holds_at_least_20_percent_of_questions():
    # 10 files, 1 question each -> dev must hold at least 2 questions (20% of 10).
    questions = _make_questions([(f"f{i}.csv", "easy") for i in range(10)])
    split = compute_split(questions, seed=2026)
    assert len(split["dev"]) >= 2


def test_all_questions_for_a_file_stay_on_one_side():
    """Splitting is by file: a file with multiple questions never straddles the split."""
    shared = [("shared.csv", "easy")] * 5
    singles = [(f"f{i}.csv", "easy") for i in range(5)]
    questions = _make_questions(shared + singles)
    split = compute_split(questions, seed=2026)
    assert ("shared.csv" in split["dev"]) != ("shared.csv" in split["test"])


# ---- write_split ----


def test_write_split_records_seed_counts_and_levels(tmp_path):
    questions = _make_questions(
        [("a.csv", "easy"), ("a.csv", "hard"), ("b.csv", "medium"), ("c.csv", "easy")]
    )
    path = tmp_path / "split.json"
    payload = write_split(questions, path=path, seed=2026)

    assert payload["seed"] == 2026
    assert payload["dev"]["n_questions"] + payload["test"]["n_questions"] == 4
    assert sum(payload["dev"]["by_level"].values()) == payload["dev"]["n_questions"]
    assert path.exists()


def test_write_split_question_ids_match_the_files_assigned_to_each_side(tmp_path):
    questions = _make_questions([("a.csv", "easy"), ("b.csv", "easy"), ("c.csv", "easy")])
    path = tmp_path / "split.json"
    payload = write_split(questions, path=path, seed=2026)

    id_to_file = {q.id: q.file_name for q in questions}
    for side in ("dev", "test"):
        for qid in payload[side]["question_ids"]:
            assert id_to_file[qid] in payload[side]["files"]


# ---- load_split ----


def test_load_split_dev_works_without_any_git_check(tmp_path):
    questions = _make_questions([("a.csv", "easy"), ("b.csv", "easy")])
    path = tmp_path / "split.json"
    write_split(questions, path=path, seed=2026)

    def _fail_if_called(*args):
        raise AssertionError("load_split('dev') must not call git at all")

    dev = load_split("dev", split_path=path, git_run=_fail_if_called)
    assert "files" in dev
    assert "question_ids" in dev


def test_load_split_test_succeeds_when_clean_and_frozen_tagged(tmp_path):
    questions = _make_questions([("a.csv", "easy"), ("b.csv", "easy")])
    path = tmp_path / "split.json"
    write_split(questions, path=path, seed=2026)

    def git_run(*args):
        if args[0] == "status":
            return _completed(stdout="")
        if args[0] == "tag":
            return _completed(stdout="frozen-v1\n")
        raise AssertionError(f"unexpected git call: {args}")

    test = load_split("test", split_path=path, git_run=git_run)
    assert "files" in test


def test_load_split_test_raises_when_working_tree_is_dirty(tmp_path):
    questions = _make_questions([("a.csv", "easy")])
    path = tmp_path / "split.json"
    write_split(questions, path=path, seed=2026)

    def git_run(*args):
        if args[0] == "status":
            return _completed(stdout=" M some_file.py\n")
        return _completed(stdout="frozen-v1\n")

    with pytest.raises(SplitLockedError, match="not clean"):
        load_split("test", split_path=path, git_run=git_run)


def test_load_split_test_raises_when_head_has_no_frozen_tag(tmp_path):
    questions = _make_questions([("a.csv", "easy")])
    path = tmp_path / "split.json"
    write_split(questions, path=path, seed=2026)

    def git_run(*args):
        if args[0] == "status":
            return _completed(stdout="")
        if args[0] == "tag":
            return _completed(stdout="v1.0\nsome-other-tag\n")
        raise AssertionError(f"unexpected git call: {args}")

    with pytest.raises(SplitLockedError, match="frozen-"):
        load_split("test", split_path=path, git_run=git_run)


def test_load_split_test_raises_when_git_status_itself_fails(tmp_path):
    questions = _make_questions([("a.csv", "easy")])
    path = tmp_path / "split.json"
    write_split(questions, path=path, seed=2026)

    def git_run(*args):
        return _completed(stdout="", returncode=1)

    with pytest.raises(SplitLockedError):
        load_split("test", split_path=path, git_run=git_run)


def test_load_split_rejects_unknown_split_name(tmp_path):
    missing_path = tmp_path / "split.json"
    with pytest.raises(ValueError, match="unknown split"):
        load_split("validation", split_path=missing_path, git_run=lambda *a: _completed())
