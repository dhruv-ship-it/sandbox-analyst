import json

import pytest

from sandbox_analyst.agent.answer import AnswerItem
from sandbox_analyst.bench.dabench import Label
from sandbox_analyst.bench.grader import grade_question
from sandbox_analyst.bench.report import (
    ABLATION_KEYS,
    build_report,
    categorize_failure,
    cost_speed_report,
    error_report,
    failure_taxonomy,
    load_run_results,
    metric_block,
    truncated_answer_at_k,
    unverified_single_shot_answer,
    write_report,
)


def _attempt(
    n,
    *,
    check_ok=True,
    exec_outcome="ok",
    error_type=None,
    evidenced=None,
    unverified=None,
):
    return {
        "attempt": n,
        "code_hash": "abc123",
        "check_ok": check_ok,
        "exec_outcome": exec_outcome,
        "error_type": error_type,
        "evidenced_answers": evidenced or [],
        "unverified_answers": unverified or [],
    }


def _row(
    id_,
    *,
    level="easy",
    status="answered",
    final_answers=None,
    attempts=None,
    prompt_tokens=10,
    completion_tokens=10,
    total_latency_ms=100,
    wall_time_ms=200,
    sandbox_usd=0.001,
    llm_request_count=2,
):
    return {
        "id": id_,
        "level": level,
        "status": status,
        "infra_cause": "llm_error" if status == "infra_error" else None,
        "attempts": attempts if attempts is not None else [],
        "final_answers": final_answers if final_answers is not None else [],
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_latency_ms": total_latency_ms,
        "wall_time_ms": wall_time_ms,
        "sandbox_usd": sandbox_usd,
        "llm_request_count": llm_request_count,
        "trace_path": f"runs/traces/{id_}.jsonl",
    }


def _label(id_, pairs):
    return Label(id=id_, answers=pairs)


# ---- truncation logic ----


def test_truncated_answer_at_k_uses_the_first_fully_evidenced_attempt():
    attempts = [
        _attempt(1, unverified=[{"name": "x", "value": "9"}]),
        _attempt(2, evidenced=[{"name": "x", "value": "1"}]),
    ]
    assert truncated_answer_at_k(attempts, 1) == []
    assert truncated_answer_at_k(attempts, 2) == [{"name": "x", "value": "1"}]


def test_truncated_answer_at_k_stops_scanning_past_k():
    attempts = [
        _attempt(1, unverified=[{"name": "x", "value": "9"}]),
        _attempt(2, evidenced=[{"name": "x", "value": "1"}]),
    ]
    assert truncated_answer_at_k(attempts, 1) == []  # attempt 2's evidence never consulted


def test_truncated_answer_at_k_with_no_evidenced_attempt_is_empty():
    attempts = [_attempt(1, unverified=[{"name": "x", "value": "9"}])]
    assert truncated_answer_at_k(attempts, 4) == []


def test_unverified_single_shot_uses_attempt_1_regardless_of_evidence():
    attempts = [
        _attempt(1, unverified=[{"name": "x", "value": "9"}]),
        _attempt(2, evidenced=[{"name": "x", "value": "1"}]),
    ]
    assert unverified_single_shot_answer(attempts) == [{"name": "x", "value": "9"}]


def test_unverified_single_shot_with_no_attempt_1_is_empty():
    assert unverified_single_shot_answer([]) == []


# ---- failure taxonomy ----


def test_categorize_failure_none_when_correct():
    label = _label(1, [("x", "1")])
    grade = grade_question([AnswerItem(name="x", value="1")], label, "strict")
    row = _row(1, status="answered", final_answers=[{"name": "x", "value": "1"}])
    assert categorize_failure(row, grade) is None


def test_categorize_failure_infra():
    label = _label(1, [("x", "1")])
    grade = grade_question([], label, "strict")
    row = _row(1, status="infra_error")
    assert categorize_failure(row, grade) == "infra"


def test_categorize_failure_budget():
    label = _label(1, [("x", "1")])
    grade = grade_question([], label, "strict")
    row = _row(1, status="budget_exceeded")
    assert categorize_failure(row, grade) == "budget"


def test_categorize_failure_repeated_failure():
    label = _label(1, [("x", "1")])
    grade = grade_question([], label, "strict")
    row = _row(1, status="repeated_failure")
    assert categorize_failure(row, grade) == "repeated_failure"


def test_categorize_failure_max_attempts_when_no_final_answer():
    label = _label(1, [("x", "1")])
    grade = grade_question([], label, "strict")
    row = _row(1, status="failed", final_answers=[])
    assert categorize_failure(row, grade) == "max_attempts"


def test_categorize_failure_evidence_failure_when_an_answer_exists():
    label = _label(1, [("x", "1")])
    grade = grade_question([AnswerItem(name="x", value="999")], label, "strict")
    row = _row(1, status="failed", final_answers=[{"name": "x", "value": "999"}])
    assert categorize_failure(row, grade) == "evidence_failure"


def test_categorize_failure_wrong_format_or_name_when_name_missing():
    label = _label(1, [("x", "1")])
    grade = grade_question([], label, "strict")
    row = _row(1, status="answered", final_answers=[])
    assert categorize_failure(row, grade) == "wrong_format_or_name"


def test_categorize_failure_wrong_value():
    label = _label(1, [("x", "1")])
    grade = grade_question([AnswerItem(name="x", value="999")], label, "strict")
    row = _row(1, status="answered", final_answers=[{"name": "x", "value": "999"}])
    assert categorize_failure(row, grade) == "wrong_value"


def test_failure_taxonomy_groups_ids_by_category():
    labels = {1: _label(1, [("x", "1")]), 2: _label(2, [("x", "1")])}
    rows = [
        _row(1, status="answered", final_answers=[{"name": "x", "value": "1"}]),  # correct
        _row(2, status="infra_error"),
    ]
    taxonomy = failure_taxonomy(rows, labels, "strict")
    assert taxonomy == {"infra": [2]}


# ---- error_report ----


def test_error_report_runtime_error_rate_and_resolution():
    rows = [
        _row(
            1,
            status="answered",
            attempts=[_attempt(1, exec_outcome="error", error_type="KeyError"), _attempt(2)],
        ),
        _row(2, status="answered", attempts=[_attempt(1)]),
    ]
    report = error_report({"r1": rows})
    assert report["n_attempts"] == 3
    assert report["runtime_error_rate_per_attempt"] == pytest.approx(1 / 3)
    assert report["pct_tasks_with_at_least_one_error"] == pytest.approx(1 / 2)
    assert report["attempt1_errored_count"] == 1
    assert report["attempt1_errored_resolved_within"][2] == pytest.approx(1.0)


def test_error_report_checker_block_rate_and_list():
    rows = [
        _row(1, attempts=[_attempt(1, check_ok=False), _attempt(2)]),
    ]
    report = error_report({"r1": rows})
    assert report["checker_block_rate_per_attempt"][1] == pytest.approx(1.0)
    assert report["checker_block_rate_per_attempt"][2] == pytest.approx(0.0)
    assert report["checker_blocked_attempts"] == [
        {"question_id": 1, "attempt": 1, "trace_path": "runs/traces/1.jsonl"}
    ]


def test_error_report_evidence_failure_rate():
    rows = [
        _row(
            1,
            attempts=[
                _attempt(1, unverified=[{"name": "x", "value": "9"}]),
                _attempt(2, evidenced=[{"name": "x", "value": "1"}]),
            ],
        ),
    ]
    report = error_report({"r1": rows})
    assert report["evidence_failure_rate"] == pytest.approx(0.5)


def test_error_report_status_distribution_and_infra_count():
    rows = [_row(1, status="answered"), _row(2, status="infra_error"), _row(3, status="failed")]
    report = error_report({"r1": rows})
    assert report["status_distribution"] == {"answered": 1, "infra_error": 1, "failed": 1}
    assert report["n_infra_error"] == 1


# ---- cost_speed_report ----


def test_cost_speed_report_means_and_percentiles():
    rows = [
        _row(1, prompt_tokens=10, completion_tokens=10, total_latency_ms=100, sandbox_usd=0.001),
        _row(2, prompt_tokens=20, completion_tokens=20, total_latency_ms=200, sandbox_usd=0.002),
    ]
    report = cost_speed_report({"r1": rows})
    assert report["n_tasks"] == 2
    assert report["tokens_per_task"]["mean"] == pytest.approx(30.0)
    assert report["sandbox_usd_per_task"]["total"] == pytest.approx(0.003)
    assert report["llm_requests_per_task"]["mean"] == pytest.approx(2.0)


# ---- accuracy metric_block: point estimates + determinism ----


def test_metric_block_point_estimates_match_hand_computation():
    labels = {1: _label(1, [("x", "1")]), 2: _label(2, [("x", "1")])}
    rows = [
        _row(1, final_answers=[{"name": "x", "value": "1"}]),  # correct
        _row(2, final_answers=[{"name": "x", "value": "999"}]),  # wrong
    ]
    block = metric_block({"r1": rows}, labels, "strict", lambda r: r["final_answers"])
    assert block["per_run"]["r1"]["abq"] == pytest.approx(0.5)
    assert block["pooled"]["abq"] == pytest.approx(0.5)
    lo, hi = block["pooled"]["abq_ci"]
    assert 0.0 <= lo <= hi <= 1.0


def test_metric_block_pooled_is_deterministic_across_calls():
    labels = {1: _label(1, [("x", "1")]), 2: _label(2, [("x", "1")])}
    rows1 = [_row(1, final_answers=[{"name": "x", "value": "1"}])]
    rows2 = [_row(1, final_answers=[{"name": "x", "value": "999"}])]
    a = metric_block({"r1": rows1, "r2": rows2}, labels, "strict", lambda r: r["final_answers"])
    b = metric_block({"r1": rows1, "r2": rows2}, labels, "strict", lambda r: r["final_answers"])
    assert a == b


def test_metric_block_pools_only_common_question_ids_across_runs():
    labels = {1: _label(1, [("x", "1")]), 2: _label(2, [("x", "1")])}
    rows1 = [
        _row(1, final_answers=[{"name": "x", "value": "1"}]),
        _row(2, final_answers=[{"name": "x", "value": "1"}]),
    ]
    rows2 = [_row(1, final_answers=[{"name": "x", "value": "1"}])]  # missing id 2
    block = metric_block({"r1": rows1, "r2": rows2}, labels, "strict", lambda r: r["final_answers"])
    assert block["pooled"]["n_questions"] == 1


# ---- end-to-end: build_report / write_report on a tiny synthetic run ----


def _write_run(eval_dir, run_name, rows):
    run_dir = eval_dir / run_name
    run_dir.mkdir(parents=True)
    with (run_dir / "results.jsonl").open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


def test_build_report_end_to_end_tiny_synthetic_run(tmp_path):
    eval_dir = tmp_path / "eval"
    labels_path = tmp_path / "labels.jsonl"
    labels_path.write_text(
        '{"id": 1, "common_answers": [["x", "1"]]}\n{"id": 2, "common_answers": [["x", "2"]]}\n',
        encoding="utf-8",
    )
    rows = [
        _row(
            1,
            level="easy",
            final_answers=[{"name": "x", "value": "1"}],
            attempts=[_attempt(1, evidenced=[{"name": "x", "value": "1"}])],
        ),
        _row(
            2,
            level="hard",
            status="failed",
            final_answers=[],
            attempts=[_attempt(1, exec_outcome="error", error_type="KeyError")],
        ),
    ]
    _write_run(eval_dir, "r1", rows)

    report = build_report(["r1"], eval_dir=eval_dir, labels_path=labels_path)
    assert report["run_names"] == ["r1"]
    assert set(ABLATION_KEYS) == set(report["ablation"]["strict"].keys())
    assert report["by_level"]["easy"]["accuracy"]["strict"]["pooled"]["n_questions"] == 1
    assert report["by_level"]["hard"]["accuracy"]["strict"]["pooled"]["n_questions"] == 1
    assert report["errors"]["n_infra_error"] == 0

    md_path, json_path, failure_paths = write_report(
        ["r1"], eval_dir=eval_dir, labels_path=labels_path
    )
    assert md_path.exists()
    assert json_path.exists()
    assert len(failure_paths) == 1
    assert failure_paths[0].exists()

    loaded = json.loads(json_path.read_text())
    assert loaded["run_names"] == ["r1"]


def test_load_run_results_dedups_keeping_the_last_line(tmp_path):
    eval_dir = tmp_path / "eval"
    run_dir = eval_dir / "r1"
    run_dir.mkdir(parents=True)
    rows = [_row(1, status="infra_error"), _row(1, status="answered")]
    with (run_dir / "results.jsonl").open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")

    loaded = load_run_results("r1", eval_dir=eval_dir)
    assert len(loaded) == 1
    assert loaded[0]["status"] == "answered"
