from pathlib import Path

from sandbox_analyst.redteam.cases import CaseResult
from sandbox_analyst.redteam.report import build_report, render_markdown, write_report


def _cr(category: str, case_id: str, handled: bool, **kwargs) -> CaseResult:
    return CaseResult(case_id=case_id, category=category, handled=handled, reason="x", **kwargs)


def _sample_report() -> dict:
    return build_report(
        category_a=[
            _cr("A", "a1", True, layer="checker"),
            _cr("A", "a2", True, layer="sandbox_contained"),
            _cr("A", "a3", False, layer="model_declined", canary_leaked=True),
        ],
        category_b=[_cr("B", "b1", True), _cr("B", "b2", False)],
        category_c=[_cr("C", "c1", True)],
        category_d=[_cr("D", "d1", True), _cr("D", "d2", True)],
        sandbox_only_results=[_cr("A-sandbox-only", "s1", True)],
        checker_only_category_a_block_rate=0.5,
        checker_only_known_bad_block_rate=1.0,
    )


def test_overall_handled_and_total_are_summed_across_every_category():
    report = _sample_report()
    assert report["overall"] == {"handled": 6, "total": 8}


def test_per_category_counts():
    report = _sample_report()
    assert report["categories"]["A"]["handled"] == 2
    assert report["categories"]["A"]["total"] == 3
    assert report["categories"]["B"]["handled"] == 1
    assert report["categories"]["B"]["total"] == 2


def test_layer_breakdown_only_counts_category_a():
    report = _sample_report()
    assert report["layer_breakdown_category_a"] == {
        "checker": 1,
        "sandbox_contained": 1,
        "model_declined": 1,
    }


def test_canary_block_reports_the_leaking_case():
    report = _sample_report()
    assert report["canary"]["n_leaks"] == 1
    assert report["canary"]["leaked_case_ids"] == ["a3"]


def test_failures_list_every_unhandled_case_with_its_category():
    report = _sample_report()
    failures = {f["case_id"]: f["category"] for f in report["failures"]}
    assert failures == {"A:a3": "A", "B:b2": "B"}


def test_layer_isolation_blocks_are_included_when_provided():
    report = _sample_report()
    assert report["layer_isolation_sandbox_only"]["handled"] == 1
    assert report["layer_isolation_checker_only_category_a_block_rate"] == 0.5
    assert report["layer_isolation_checker_only_known_bad_block_rate"] == 1.0


def test_layer_isolation_blocks_are_omitted_when_not_provided():
    report = build_report(category_a=[], category_b=[], category_c=[], category_d=[])
    assert "layer_isolation_sandbox_only" not in report
    assert "layer_isolation_checker_only_category_a_block_rate" not in report


def test_render_markdown_mentions_every_category_and_the_overall_line():
    report = _sample_report()
    md = render_markdown(report, "test-run")
    assert "handled 6 of 8" in md
    assert "Category A: handled 2 of 3" in md
    assert "A:a3" in md  # failures are listed by "category:case_id"


def test_write_report_creates_both_files(tmp_path: Path):
    report = _sample_report()
    md_path, json_path = write_report(report, "test-run", tmp_path / "out")
    assert md_path.exists()
    assert json_path.exists()
    assert "test-run" in md_path.read_text(encoding="utf-8")
