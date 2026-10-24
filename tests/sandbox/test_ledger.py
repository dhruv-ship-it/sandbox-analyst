import pytest

from sandbox_analyst.sandbox.base import SandboxUnavailable
from sandbox_analyst.sandbox.ledger import (
    append_entry,
    check_budget,
    estimate_cost_usd,
    ledger_total_usd,
    make_entry,
)


def test_estimate_cost_usd_matches_the_published_formula():
    cost = estimate_cost_usd(
        alive_s=10,
        cpu=0.25,
        memory_gib=1,
        usd_per_core_second=0.00003942,
        usd_per_gib_second=0.00000667,
    )
    expected = 10 * (0.25 * 0.00003942 + 1 * 0.00000667)
    assert cost == pytest.approx(expected)


def test_ledger_total_is_zero_for_a_missing_file(tmp_path):
    assert ledger_total_usd(tmp_path / "does_not_exist.jsonl") == 0.0


def test_append_and_sum_multiple_entries(tmp_path):
    ledger_path = tmp_path / "ledger.jsonl"
    for alive_s in (10, 20, 30):
        entry = make_entry(
            alive_s=alive_s,
            cpu=0.25,
            memory_gib=1,
            usd_per_core_second=0.00003942,
            usd_per_gib_second=0.00000667,
        )
        append_entry(ledger_path, entry)

    total = ledger_total_usd(ledger_path)
    expected = sum(
        estimate_cost_usd(alive_s, 0.25, 1, 0.00003942, 0.00000667) for alive_s in (10, 20, 30)
    )
    assert total == pytest.approx(expected)
    assert len(ledger_path.read_text().strip().splitlines()) == 3


def test_append_entry_creates_parent_directories(tmp_path):
    ledger_path = tmp_path / "nested" / "dir" / "ledger.jsonl"
    entry = make_entry(10, 0.25, 1, 0.00003942, 0.00000667)
    append_entry(ledger_path, entry)
    assert ledger_path.exists()


def test_check_budget_passes_when_under_cap(tmp_path):
    ledger_path = tmp_path / "ledger.jsonl"
    append_entry(ledger_path, make_entry(1, 0.25, 1, 0.00003942, 0.00000667))
    check_budget(ledger_path, budget_usd=0.80)  # must not raise


def test_check_budget_raises_when_at_or_over_cap(tmp_path):
    ledger_path = tmp_path / "ledger.jsonl"
    # A huge alive_s to push the estimate past any reasonable budget.
    append_entry(ledger_path, make_entry(10_000_000, 0.25, 1, 0.00003942, 0.00000667))
    with pytest.raises(SandboxUnavailable, match="budget"):
        check_budget(ledger_path, budget_usd=0.80)


def test_check_budget_raises_exactly_at_the_threshold(tmp_path):
    ledger_path = tmp_path / "ledger.jsonl"
    entry = make_entry(1, 0.0, 0.0, 0.0, 0.0)
    # est_usd is 0 with these inputs; a budget of exactly 0 should trip "at or over".
    append_entry(ledger_path, entry)
    with pytest.raises(SandboxUnavailable):
        check_budget(ledger_path, budget_usd=0.0)


def test_check_budget_with_empty_ledger_never_raises(tmp_path):
    ledger_path = tmp_path / "ledger.jsonl"
    check_budget(ledger_path, budget_usd=0.80)
