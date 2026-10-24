"""Metrics and reports over one or more `sa eval` runs: `uv run sa report <run-name>...`.

Reads each run's `results.jsonl` (never re-runs anything), grades every
question's final answer against its label (`bench.grader`), and
reports ABQ/PSAQ/UASQ with bootstrap 95% CIs -- per run, pooled across
runs with questions paired (D-062), and a plain mean/range across
runs' own point estimates. The truncation ablation (k=1..4, plus
"unverified single-shot") reuses the exact same grading/CI machinery
against a different answer source per k: the first fully-evidenced
attempt at or before k (or attempt 1 regardless of evidence, for the
unverified variant). Errors, cost/speed, and a per-question failure
taxonomy round out the report; everything is also broken down per
level. Outputs: `report.md` + `report.json` (combined across every
given run), and one `failures.md` per individual run (gitignored, for
manual review).
"""

import argparse
import json
import random
import sys
from collections import Counter
from pathlib import Path
from typing import Literal

from .dabench import Label, load_labels
from .grader import AnswerItem, Mode, QuestionGrade, grade_question
from .harness import DEFAULT_EVAL_DIR
from .stats import mean, mean_and_range, paired_bootstrap_ci, percentile

DEFAULT_LABELS_PATH = Path("data/dabench/da-dev-labels.jsonl")
LEVELS: tuple[str, ...] = ("easy", "medium", "hard")
MODES: tuple[Mode, ...] = ("strict", "tolerant")
RUNTIME_ERROR_OUTCOMES = frozenset({"error", "timeout", "crashed"})
AblationKey = Literal["k=1", "k=2", "k=3", "k=4", "unverified_single_shot"]
ABLATION_KEYS: tuple[AblationKey, ...] = ("k=1", "k=2", "k=3", "k=4", "unverified_single_shot")


# ---- loading ----


def load_run_results(run_name: str, eval_dir: Path = DEFAULT_EVAL_DIR) -> list[dict]:
    """Load one run's results.jsonl, keeping the last (resumed) row per question id."""
    path = eval_dir / run_name / "results.jsonl"
    latest: dict[int, dict] = {}
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                row = json.loads(line)
                latest[row["id"]] = row
    return list(latest.values())


def _labels_by_id(labels_path: Path = DEFAULT_LABELS_PATH) -> dict[int, Label]:
    return {label.id: label for label in load_labels(labels_path)}


def _answers_from(dicts: list[dict]) -> list[AnswerItem]:
    return [AnswerItem(name=d["name"], value=d["value"]) for d in dicts]


# ---- truncation ablation: which attempt's answer "counts" at k ----


def _attempt_full_answer(attempt: dict) -> list[dict]:
    return attempt["evidenced_answers"] + attempt["unverified_answers"]


def _is_fully_evidenced(attempt: dict) -> bool:
    return not attempt["unverified_answers"] and bool(attempt["evidenced_answers"])


def truncated_answer_at_k(attempts: list[dict], k: int) -> list[dict]:
    """The answer from the first fully-evidenced attempt at or before k, else none."""
    for attempt in attempts:
        if attempt["attempt"] > k:
            break
        if _is_fully_evidenced(attempt):
            return _attempt_full_answer(attempt)
    return []


def unverified_single_shot_answer(attempts: list[dict]) -> list[dict]:
    """Attempt 1's answer regardless of whether its evidence check passed."""
    for attempt in attempts:
        if attempt["attempt"] == 1:
            return _attempt_full_answer(attempt)
    return []


def _ablation_answer_fn(key: AblationKey):
    if key == "unverified_single_shot":
        return lambda row: unverified_single_shot_answer(row["attempts"])
    k = int(key.split("=")[1])
    return lambda row: truncated_answer_at_k(row["attempts"], k)


# ---- grading + accuracy with bootstrap CIs, paired across runs ----


def _grade_rows(
    rows: list[dict], labels: dict[int, Label], mode: Mode, answer_fn
) -> dict[int, QuestionGrade]:
    grades = {}
    for row in rows:
        label = labels.get(row["id"])
        if label is None:
            continue
        grades[row["id"]] = grade_question(_answers_from(answer_fn(row)), label, mode)
    return grades


def _uasq_bootstrap_ci(rows: list[list[tuple[int, int]]]) -> tuple[float, float]:
    """Like stats.paired_bootstrap_ci, but for a ratio-of-sums (UASQ), not a mean."""
    n = len(rows)
    if n == 0:
        return (0.0, 0.0)
    rng = random.Random(2026)
    resample_stats = []
    for _ in range(10_000):
        correct = 0
        total = 0
        for _ in range(n):
            for c, t in rows[rng.randrange(n)]:
                correct += c
                total += t
        resample_stats.append(correct / total if total else 0.0)
    return (percentile(resample_stats, 2.5), percentile(resample_stats, 97.5))


def _metrics_over(
    grades_by_run: dict[str, dict[int, QuestionGrade]], question_ids: list[int]
) -> dict:
    """ABQ/PSAQ/UASQ (point + 95% CI) over `question_ids`, paired across every run in the pool."""
    run_names = list(grades_by_run)
    abq_rows = [
        [1.0 if grades_by_run[r][q].all_correct else 0.0 for r in run_names] for q in question_ids
    ]
    psaq_rows = [[grades_by_run[r][q].fraction_correct for r in run_names] for q in question_ids]
    uasq_rows = [
        [(grades_by_run[r][q].n_correct, len(grades_by_run[r][q].sub_answers)) for r in run_names]
        for q in question_ids
    ]
    flat_abq = [v for row in abq_rows for v in row]
    flat_psaq = [v for row in psaq_rows for v in row]
    flat_uasq = [p for row in uasq_rows for p in row]
    total = sum(t for _, t in flat_uasq)
    correct = sum(c for c, _ in flat_uasq)

    return {
        "n_questions": len(question_ids),
        "n_values": len(flat_abq),
        "abq": mean(flat_abq),
        "abq_ci": paired_bootstrap_ci(abq_rows) if abq_rows else (0.0, 0.0),
        "psaq": mean(flat_psaq),
        "psaq_ci": paired_bootstrap_ci(psaq_rows) if psaq_rows else (0.0, 0.0),
        "uasq": correct / total if total else 0.0,
        "uasq_ci": _uasq_bootstrap_ci(uasq_rows),
    }


def metric_block(
    rows_by_run: dict[str, list[dict]], labels: dict[int, Label], mode: Mode, answer_fn
) -> dict:
    """Per-run metrics (with their own CI), pooled metrics (paired by question), and mean/range."""
    grades_by_run = {
        name: _grade_rows(rows, labels, mode, answer_fn) for name, rows in rows_by_run.items()
    }
    run_names = list(rows_by_run)

    per_run = {
        name: _metrics_over({name: grades_by_run[name]}, sorted(grades_by_run[name]))
        for name in run_names
    }
    common_ids = (
        sorted(set.intersection(*(set(g) for g in grades_by_run.values()))) if grades_by_run else []
    )
    pooled = _metrics_over(grades_by_run, common_ids)
    mean_range = {
        metric: mean_and_range([per_run[n][metric] for n in run_names])
        for metric in ("abq", "psaq", "uasq")
    }
    return {"per_run": per_run, "pooled": pooled, "mean_and_range": mean_range}


def accuracy_report(rows_by_run: dict[str, list[dict]], labels: dict[int, Label]) -> dict:
    return {
        mode: metric_block(rows_by_run, labels, mode, lambda r: r["final_answers"])
        for mode in MODES
    }


def ablation_report(rows_by_run: dict[str, list[dict]], labels: dict[int, Label]) -> dict:
    return {
        mode: {
            key: metric_block(rows_by_run, labels, mode, _ablation_answer_fn(key))
            for key in ABLATION_KEYS
        }
        for mode in MODES
    }


# ---- errors ----


def error_report(rows_by_run: dict[str, list[dict]]) -> dict:
    all_rows = [r for rows in rows_by_run.values() for r in rows]
    all_attempts = [a for r in all_rows for a in r["attempts"]]

    n_attempts = len(all_attempts)
    n_runtime_errors = sum(1 for a in all_attempts if a["exec_outcome"] in RUNTIME_ERROR_OUTCOMES)
    n_tasks = len(all_rows)
    tasks_with_error = sum(
        1
        for r in all_rows
        if any(a["exec_outcome"] in RUNTIME_ERROR_OUTCOMES for a in r["attempts"])
    )

    attempt1_errored = [
        r
        for r in all_rows
        if r["attempts"] and r["attempts"][0]["exec_outcome"] in RUNTIME_ERROR_OUTCOMES
    ]
    resolved_within = {}
    for n in (2, 3, 4):
        denom = len(attempt1_errored)
        numer = sum(
            1 for r in attempt1_errored if r["status"] == "answered" and len(r["attempts"]) <= n
        )
        resolved_within[n] = numer / denom if denom else 0.0

    blocks_per_attempt: dict[int, dict[str, int]] = {}
    blocked_list = []
    for r in all_rows:
        for a in r["attempts"]:
            bucket = blocks_per_attempt.setdefault(a["attempt"], {"n_blocked": 0, "n_total": 0})
            bucket["n_total"] += 1
            if a["check_ok"] is False:
                bucket["n_blocked"] += 1
                blocked_list.append(
                    {"question_id": r["id"], "attempt": a["attempt"], "trace_path": r["trace_path"]}
                )
    checker_block_rate = {
        n: (b["n_blocked"] / b["n_total"] if b["n_total"] else 0.0)
        for n, b in sorted(blocks_per_attempt.items())
    }

    answer_attempts = [a for a in all_attempts if a["evidenced_answers"] or a["unverified_answers"]]
    n_evidence_failures = sum(1 for a in answer_attempts if a["unverified_answers"])

    status_counts = Counter(r["status"] for r in all_rows)

    return {
        "n_tasks": n_tasks,
        "n_attempts": n_attempts,
        "runtime_error_rate_per_attempt": n_runtime_errors / n_attempts if n_attempts else 0.0,
        "pct_tasks_with_at_least_one_error": tasks_with_error / n_tasks if n_tasks else 0.0,
        "attempt1_errored_count": len(attempt1_errored),
        "attempt1_errored_resolved_within": resolved_within,
        "checker_block_rate_per_attempt": checker_block_rate,
        "checker_blocked_attempts": blocked_list,
        "evidence_failure_rate": n_evidence_failures / len(answer_attempts)
        if answer_attempts
        else 0.0,
        "status_distribution": dict(status_counts),
        "n_infra_error": status_counts.get("infra_error", 0),
    }


# ---- cost and speed ----


def _stat_block(values: list[float]) -> dict:
    if not values:
        return {"mean": 0.0, "p50": 0.0, "p95": 0.0}
    return {"mean": mean(values), "p50": percentile(values, 50), "p95": percentile(values, 95)}


def cost_speed_report(rows_by_run: dict[str, list[dict]]) -> dict:
    all_rows = [r for rows in rows_by_run.values() for r in rows]
    tokens = [r["prompt_tokens"] + r["completion_tokens"] for r in all_rows]
    latencies = [float(r["total_latency_ms"]) for r in all_rows]
    wall_times = [float(r["wall_time_ms"]) for r in all_rows]
    sandbox_costs = [r["sandbox_usd"] for r in all_rows]
    requests = [r["llm_request_count"] for r in all_rows]

    return {
        "n_tasks": len(all_rows),
        "tokens_per_task": _stat_block(tokens),
        "llm_latency_ms_per_task": _stat_block(latencies),
        "wall_time_ms_per_task": _stat_block(wall_times),
        "sandbox_usd_per_task": {"mean": mean(sandbox_costs), "total": sum(sandbox_costs)},
        "llm_requests_per_task": {"mean": mean(requests), "total": sum(requests)},
    }


# ---- per-question failure taxonomy ----


def categorize_failure(result: dict, grade: QuestionGrade) -> str | None:
    """None if fully correct; else exactly one of a fixed set of failure categories."""
    if grade.all_correct:
        return None
    status = result["status"]
    if status == "infra_error":
        return "infra"
    if status == "budget_exceeded":
        return "budget"
    if status == "repeated_failure":
        return "repeated_failure"
    if status == "failed":
        return "evidence_failure" if result["final_answers"] else "max_attempts"
    if any(s.predicted_value is None for s in grade.sub_answers):
        return "wrong_format_or_name"
    return "wrong_value"


def failure_taxonomy(
    rows: list[dict], labels: dict[int, Label], mode: Mode
) -> dict[str, list[int]]:
    taxonomy: dict[str, list[int]] = {}
    for row in rows:
        label = labels.get(row["id"])
        if label is None:
            continue
        grade = grade_question(_answers_from(row["final_answers"]), label, mode)
        category = categorize_failure(row, grade)
        if category is not None:
            taxonomy.setdefault(category, []).append(row["id"])
    return taxonomy


# ---- per-level breakdown + the top-level report ----


def _filter_level(rows_by_run: dict[str, list[dict]], level: str) -> dict[str, list[dict]]:
    return {name: [r for r in rows if r["level"] == level] for name, rows in rows_by_run.items()}


def _level_block(rows_by_run: dict[str, list[dict]], labels: dict[int, Label]) -> dict:
    return {
        "accuracy": accuracy_report(rows_by_run, labels),
        "ablation": ablation_report(rows_by_run, labels),
        "errors": error_report(rows_by_run),
        "cost_speed": cost_speed_report(rows_by_run),
    }


def build_report(
    run_names: list[str],
    eval_dir: Path = DEFAULT_EVAL_DIR,
    labels_path: Path = DEFAULT_LABELS_PATH,
) -> dict:
    rows_by_run = {name: load_run_results(name, eval_dir) for name in run_names}
    labels = _labels_by_id(labels_path)

    report = {
        "run_names": run_names,
        **_level_block(rows_by_run, labels),
        "by_level": {
            level: _level_block(_filter_level(rows_by_run, level), labels) for level in LEVELS
        },
    }
    return report


# ---- outputs: report.md / report.json / failures.md ----


def _combined_report_name(run_names: list[str]) -> str:
    return "+".join(run_names)


def _fmt_ci(point: float, ci: tuple[float, float]) -> str:
    return f"{point:.3f} (95% CI {ci[0]:.3f}-{ci[1]:.3f})"


def render_markdown(report: dict) -> str:
    lines = [f"# Evaluation report: {', '.join(report['run_names'])}", ""]

    lines.append("## Accuracy")
    for mode in MODES:
        block = report["accuracy"][mode]
        lines.append(f"### {mode}")
        lines.append(f"- Pooled ABQ: {_fmt_ci(block['pooled']['abq'], block['pooled']['abq_ci'])}")
        lines.append(
            f"- Pooled PSAQ: {_fmt_ci(block['pooled']['psaq'], block['pooled']['psaq_ci'])}"
        )
        lines.append(
            f"- Pooled UASQ: {_fmt_ci(block['pooled']['uasq'], block['pooled']['uasq_ci'])}"
        )
        for name, per_run in block["per_run"].items():
            lines.append(
                f"  - {name}: ABQ={per_run['abq']:.3f} PSAQ={per_run['psaq']:.3f} "
                f"UASQ={per_run['uasq']:.3f}"
            )
        mean_r = block["mean_and_range"]["abq"]
        lines.append(
            f"- ABQ mean/range across runs: {mean_r[0]:.3f} ({mean_r[1]:.3f}-{mean_r[2]:.3f})"
        )
        lines.append("")

    lines.append("## Truncation ablation")
    for mode in MODES:
        lines.append(f"### {mode}")
        lines.append("| k | pooled ABQ | 95% CI |")
        lines.append("|---|---|---|")
        for key in ABLATION_KEYS:
            pooled = report["ablation"][mode][key]["pooled"]
            ci = pooled["abq_ci"]
            lines.append(f"| {key} | {pooled['abq']:.3f} | {ci[0]:.3f}-{ci[1]:.3f} |")
        lines.append("")

    errors = report["errors"]
    lines.append("## Errors")
    lines.append(
        f"- Runtime-error rate per attempt: {errors['runtime_error_rate_per_attempt']:.3f}"
    )
    lines.append(f"- % tasks with >=1 error: {errors['pct_tasks_with_at_least_one_error']:.3f}")
    for n, frac in errors["attempt1_errored_resolved_within"].items():
        lines.append(f"- Of attempt-1-errored tasks, resolved within {n} attempts: {frac:.3f}")
    lines.append(f"- Checker block rate per attempt: {errors['checker_block_rate_per_attempt']}")
    lines.append(f"- Checker-blocked attempts (count): {len(errors['checker_blocked_attempts'])}")
    lines.append(f"- Evidence-failure rate: {errors['evidence_failure_rate']:.3f}")
    lines.append(f"- Status distribution: {errors['status_distribution']}")
    lines.append(f"- infra_error count: {errors['n_infra_error']}")
    lines.append("")

    cs = report["cost_speed"]
    lines.append("## Cost and speed")
    lines.append(f"- Tokens/task: {cs['tokens_per_task']}")
    lines.append(f"- LLM latency ms/task: {cs['llm_latency_ms_per_task']}")
    lines.append(f"- Wall time ms/task: {cs['wall_time_ms_per_task']}")
    lines.append(f"- Sandbox $/task: {cs['sandbox_usd_per_task']}")
    lines.append(f"- LLM requests/task: {cs['llm_requests_per_task']}")
    lines.append("")

    lines.append("## Per-level breakdown")
    for level in LEVELS:
        level_block = report["by_level"][level]
        tolerant = level_block["accuracy"]["tolerant"]["pooled"]
        lines.append(
            f"- {level}: n={tolerant['n_questions']} tolerant ABQ={tolerant['abq']:.3f} "
            f"(95% CI {tolerant['abq_ci'][0]:.3f}-{tolerant['abq_ci'][1]:.3f})"
        )
    lines.append("")

    return "\n".join(lines) + "\n"


def write_failures_md(
    run_name: str, rows: list[dict], labels: dict[int, Label], run_dir: Path
) -> Path:
    taxonomy = failure_taxonomy(rows, labels, "tolerant")
    lines = [f"# Failure taxonomy: {run_name}", "", "Tolerant-mode grading. For manual review.", ""]
    for category in sorted(taxonomy):
        ids = taxonomy[category]
        lines.append(f"## {category} ({len(ids)})")
        lines.append(", ".join(str(i) for i in ids))
        lines.append("")
    path = run_dir / "failures.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def write_report(
    run_names: list[str],
    eval_dir: Path = DEFAULT_EVAL_DIR,
    labels_path: Path = DEFAULT_LABELS_PATH,
) -> tuple[Path, Path, list[Path]]:
    """Build the combined report.md/report.json, plus one failures.md per run."""
    report = build_report(run_names, eval_dir, labels_path)
    labels = _labels_by_id(labels_path)

    out_dir = eval_dir / _combined_report_name(run_names)
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / "report.md"
    json_path = out_dir / "report.json"
    md_path.write_text(render_markdown(report), encoding="utf-8")
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    failure_paths = []
    for name in run_names:
        rows = load_run_results(name, eval_dir)
        failure_paths.append(write_failures_md(name, rows, labels, eval_dir / name))

    return md_path, json_path, failure_paths


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sa report")
    parser.add_argument("run_names", nargs="+")
    args = parser.parse_args(argv)

    md_path, json_path, failure_paths = write_report(args.run_names)
    print(f"wrote {md_path}, {json_path}, and {len(failure_paths)} failures.md file(s)")  # noqa: T201
    return 0


if __name__ == "__main__":
    sys.exit(main())
