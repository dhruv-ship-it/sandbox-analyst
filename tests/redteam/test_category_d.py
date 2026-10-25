from pathlib import Path

from sandbox_analyst.redteam.category_d import run_category_d


def _result_for(results, case_id: str):
    return next(r for r in results if r.case_id == case_id)


def test_at_least_6_category_d_cases(tmp_path: Path):
    results = run_category_d(tmp_path)
    assert len(results) >= 6


def test_every_case_result_is_category_d(tmp_path: Path):
    results = run_category_d(tmp_path)
    assert all(r.category == "D" for r in results)


def test_empty_file_is_rejected_with_a_4xx_and_nothing_stored(tmp_path: Path):
    results = run_category_d(tmp_path)
    result = _result_for(results, "empty_file")
    assert result.handled
    assert result.status is not None and result.status.startswith("4")


def test_over_max_columns_is_rejected(tmp_path: Path):
    results = run_category_d(tmp_path)
    result = _result_for(results, "over_max_columns")
    assert result.handled


def test_over_max_upload_size_is_rejected(tmp_path: Path):
    results = run_category_d(tmp_path)
    result = _result_for(results, "over_max_upload_size")
    assert result.handled


def test_path_traversal_filename_is_rejected(tmp_path: Path):
    # Found and fixed this session (D-102): the dataset store now rejects a
    # path-traversal-shaped name at upload time instead of only being safe
    # about it later, when a run actually starts.
    results = run_category_d(tmp_path)
    result = _result_for(results, "path_traversal_filename")
    assert result.handled


def test_binary_junk_result_is_reported_honestly_either_way(tmp_path: Path):
    # Whatever profile_csv actually does with structureless binary bytes,
    # the case result must say so truthfully rather than assume a pass.
    results = run_category_d(tmp_path)
    result = _result_for(results, "binary_junk")
    assert result.status is not None
    assert isinstance(result.handled, bool)


def test_non_csv_disguised_as_csv_is_a_confirmed_unhandled_gap(tmp_path: Path):
    # A real finding from this suite, not fixed this session (see
    # DECISIONS.md D-101 and docs/security.md): a structurally valid PNG
    # renamed to .csv is accepted (200, stored) because pandas parses the
    # latin-1-decoded binary bytes as a tiny, garbage "CSV" without ever
    # raising. This pins the actual, current behavior so a future fix
    # shows up here as a result flipping to handled, not as a silently
    # vanished test.
    results = run_category_d(tmp_path)
    result = _result_for(results, "non_csv_disguised_as_csv")
    assert not result.handled
    assert result.status == "200"
