"""The sandbox spend ledger: a lower-bound cost estimate and a budget gate.

Pure host-side bookkeeping, no Modal dependency, so it's fully testable
with a temp file. The estimate only counts the CPU/memory *reservation*
held for `alive_s`; bursting above the reservation is billed by Modal
too but not counted here, so `est_usd` is always a lower bound on actual
spend (see DECISIONS.md D-007).
"""

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from .base import SandboxUnavailable

DEFAULT_LEDGER_PATH = Path("runs/sandbox_ledger.jsonl")


@dataclass(frozen=True)
class LedgerEntry:
    created_at: float
    alive_s: float
    cpu: float
    memory_gib: float
    est_usd: float


def estimate_cost_usd(
    alive_s: float,
    cpu: float,
    memory_gib: float,
    usd_per_core_second: float,
    usd_per_gib_second: float,
) -> float:
    return alive_s * (cpu * usd_per_core_second + memory_gib * usd_per_gib_second)


def make_entry(
    alive_s: float,
    cpu: float,
    memory_gib: float,
    usd_per_core_second: float,
    usd_per_gib_second: float,
) -> LedgerEntry:
    est_usd = estimate_cost_usd(alive_s, cpu, memory_gib, usd_per_core_second, usd_per_gib_second)
    return LedgerEntry(
        created_at=time.time(),
        alive_s=alive_s,
        cpu=cpu,
        memory_gib=memory_gib,
        est_usd=est_usd,
    )


def append_entry(ledger_path: Path, entry: LedgerEntry) -> None:
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with ledger_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(asdict(entry)) + "\n")


def ledger_total_usd(ledger_path: Path) -> float:
    if not ledger_path.exists():
        return 0.0
    total = 0.0
    with ledger_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            total += json.loads(line)["est_usd"]
    return total


def check_budget(ledger_path: Path, budget_usd: float) -> None:
    """Raise SandboxUnavailable if the ledger's running total is at or over budget."""
    total = ledger_total_usd(ledger_path)
    if total >= budget_usd:
        raise SandboxUnavailable(
            f"sandbox budget exhausted: ledger total ${total:.4f} >= ${budget_usd:.2f} cap "
            f"({ledger_path})"
        )
