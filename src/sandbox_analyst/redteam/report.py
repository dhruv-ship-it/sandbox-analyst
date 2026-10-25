"""Aggregate every category's `CaseResult`s into one report: handled N of M,
the layer breakdown, the canary result, and every failure with its case id.
"""

import json
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from .cases import CaseResult

CATEGORIES = ("A", "B", "C", "D")


def _category_block(results: list[CaseResult]) -> dict:
    n_handled = sum(1 for r in results if r.handled)
    return {
        "handled": n_handled,
        "total": len(results),
        "cases": [asdict(r) for r in results],
    }


def _layer_breakdown(category_a_results: list[CaseResult]) -> dict[str, int]:
    return dict(Counter(r.layer for r in category_a_results if r.layer is not None))


def _canary_block(all_results: list[CaseResult]) -> dict:
    leaked = [r for r in all_results if r.canary_leaked]
    return {"n_leaks": len(leaked), "leaked_case_ids": [r.case_id for r in leaked]}


def _failures(all_results: list[CaseResult]) -> list[dict]:
    return [
        {"case_id": r.category + ":" + r.case_id, "category": r.category, "reason": r.reason}
        for r in all_results
        if not r.handled
    ]


def build_report(
    *,
    category_a: list[CaseResult],
    category_b: list[CaseResult],
    category_c: list[CaseResult],
    category_d: list[CaseResult],
    sandbox_only_results: list[CaseResult] | None = None,
    checker_only_category_a_block_rate: float | None = None,
    checker_only_known_bad_block_rate: float | None = None,
) -> dict:
    by_category = {"A": category_a, "B": category_b, "C": category_c, "D": category_d}
    all_results = [r for results in by_category.values() for r in results]

    report = {
        "categories": {cat: _category_block(results) for cat, results in by_category.items()},
        "overall": {
            "handled": sum(1 for r in all_results if r.handled),
            "total": len(all_results),
        },
        "layer_breakdown_category_a": _layer_breakdown(category_a),
        "canary": _canary_block(all_results),
        "failures": _failures(all_results),
    }
    if sandbox_only_results is not None:
        report["layer_isolation_sandbox_only"] = _category_block(sandbox_only_results)
    if checker_only_category_a_block_rate is not None:
        report["layer_isolation_checker_only_category_a_block_rate"] = (
            checker_only_category_a_block_rate
        )
    if checker_only_known_bad_block_rate is not None:
        report["layer_isolation_checker_only_known_bad_block_rate"] = (
            checker_only_known_bad_block_rate
        )
    return report


def render_markdown(report: dict, run_name: str) -> str:
    lines = [f"# Red-team report: {run_name}", ""]

    overall = report["overall"]
    lines.append(f"## Overall: handled {overall['handled']} of {overall['total']}")
    lines.append("")

    lines.append("## Per category")
    for cat in CATEGORIES:
        block = report["categories"][cat]
        lines.append(f"- Category {cat}: handled {block['handled']} of {block['total']}")
    lines.append("")

    lines.append("## Category A layer breakdown")
    breakdown = report["layer_breakdown_category_a"]
    for layer in ("checker", "model_declined", "sandbox_contained"):
        lines.append(f"- {layer}: {breakdown.get(layer, 0)}")
    lines.append("")

    if "layer_isolation_sandbox_only" in report:
        iso = report["layer_isolation_sandbox_only"]
        lines.append(
            "## Layer isolation: sandbox alone (checker disabled, category A scripts replayed)"
        )
        lines.append(f"- handled {iso['handled']} of {iso['total']}")
        lines.append("")

    if "layer_isolation_checker_only_category_a_block_rate" in report:
        lines.append("## Layer isolation: checker alone (never executed)")
        lines.append(
            "- block rate over category A's own generated scripts: "
            f"{report['layer_isolation_checker_only_category_a_block_rate']:.3f}"
        )
        lines.append(
            "- block rate over the known-bad snippet corpus: "
            f"{report['layer_isolation_checker_only_known_bad_block_rate']:.3f}"
        )
        lines.append("")

    canary = report["canary"]
    lines.append(f"## Canary leaks: {canary['n_leaks']}")
    if canary["leaked_case_ids"]:
        lines.append(f"- leaked in: {', '.join(canary['leaked_case_ids'])}")
    lines.append("")

    lines.append(f"## Failures ({len(report['failures'])})")
    for failure in report["failures"]:
        lines.append(f"- {failure['case_id']}: {failure['reason']}")
    lines.append("")

    return "\n".join(lines) + "\n"


def write_report(report: dict, run_name: str, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / "report.md"
    json_path = out_dir / "report.json"
    md_path.write_text(render_markdown(report, run_name), encoding="utf-8")
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return md_path, json_path
