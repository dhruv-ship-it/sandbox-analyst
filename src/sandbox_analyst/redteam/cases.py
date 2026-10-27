"""Shared result shape for every red-team category."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CaseResult:
    """The outcome of running one red-team case.

    `layer` is only meaningful for category A (which layer actually
    stopped the attack: "checker", "model_declined", or
    "sandbox_contained") -- every other category leaves it None.
    `extra` carries category-specific detail (e.g. the predicted vs.
    ground-truth answer for category B) for the report, without forcing
    every category into one rigid schema. `trace_path` is "" (not None,
    matching `bench.harness.QuestionResult`'s own convention) for a case
    that never calls `run_agent` (category D) or whose agent run never
    emitted an event.
    """

    case_id: str
    category: str
    handled: bool
    reason: str
    layer: str | None = None
    canary_leaked: bool = False
    status: str | None = None
    extra: dict = field(default_factory=dict)
    trace_path: str = ""
