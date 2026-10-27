"""Offline regression replay: every tests/replay/tasks.json task through the REAL agent loop.

No network, no real sandbox -- LLM and sandbox responses come from the
committed cassettes under tests/replay/cassettes/, recorded once by
`sa record-replay` (see docs/testing.md). These tests catch regressions
in OUR code (the agent loop, evidence checking, answer parsing, prompt
construction) -- they say nothing about model quality, since the
model's own responses are frozen into the cassette.
"""

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from sandbox_analyst.agent import run_agent
from sandbox_analyst.bench.dabench import Label
from sandbox_analyst.bench.grader import grade_question
from sandbox_analyst.config import Settings
from sandbox_analyst.llm.record import CassetteMiss, ReplayLLM
from sandbox_analyst.replay.recorder import (
    DEFAULT_LLM_CASSETTE_PATH,
    DEFAULT_RECORDED_RESULTS_PATH,
    DEFAULT_SANDBOX_CASSETTE_PATH,
)
from sandbox_analyst.replay.tasks import DEFAULT_EXAMPLES_DIR, DEFAULT_TASKS_PATH, load_tasks
from sandbox_analyst.sandbox.record import ReplaySandbox, SandboxCassetteMiss

# The real provider/model `sa record-replay` recorded the cassettes against
# (see docs/testing.md) -- ReplayLLM's cassette key includes both, so replay
# must ask for the exact same pair the recording used.
RECORDED_LLM_PROVIDER = "groq"
RECORDED_LLM_MODEL = "openai/gpt-oss-20b"

ALL_TASKS = load_tasks(DEFAULT_TASKS_PATH)


@dataclass(frozen=True)
class ReplayComparison:
    task_id: str
    status_ok: bool
    answers_ok: bool
    truth_ok: bool
    event_shape_ok: bool
    error: str | None = None

    @property
    def ok(self) -> bool:
        return (
            self.error is None
            and self.status_ok
            and self.answers_ok
            and self.truth_ok
            and self.event_shape_ok
        )


def _load_recorded_results(path: Path = DEFAULT_RECORDED_RESULTS_PATH) -> dict[str, dict]:
    rows = json.loads(path.read_text(encoding="utf-8"))
    return {row["task_id"]: row for row in rows}


def replay_task(
    task,
    recorded_row: dict,
    *,
    examples_dir: Path = DEFAULT_EXAMPLES_DIR,
    llm_cassette_path: Path = DEFAULT_LLM_CASSETTE_PATH,
    sandbox_cassette_path: Path = DEFAULT_SANDBOX_CASSETTE_PATH,
    settings: Settings | None = None,
) -> ReplayComparison:
    """Replay one task through the real agent loop and compare it against the recorded snapshot.

    A CassetteMiss/SandboxCassetteMiss (the replay needing a call that was
    never recorded -- e.g. because a broken repair loop now takes a
    different path) is treated as "not ok", not as an uncaught error: the
    suite needing an unrecorded call is itself evidence something changed.
    """
    settings = settings or Settings()
    csv_bytes = (examples_dir / task.dataset).read_bytes()
    llm = ReplayLLM(llm_cassette_path, provider=RECORDED_LLM_PROVIDER, model=RECORDED_LLM_MODEL)
    sandbox = ReplaySandbox(sandbox_cassette_path)
    event_types: list[str] = []

    try:
        result = run_agent(
            csv_bytes,
            task.dataset,
            task.question,
            llm=llm,
            sandbox_factory=lambda: sandbox,
            settings=settings,
            on_event=lambda e: event_types.append(e.type),
            constraints=task.constraints or None,
            answer_format=task.answer_format,
        )
    except (CassetteMiss, SandboxCassetteMiss) as exc:
        return ReplayComparison(
            task_id=task.id,
            status_ok=False,
            answers_ok=False,
            truth_ok=False,
            event_shape_ok=False,
            error=str(exc),
        )

    status_ok = result.status == recorded_row["status"]
    replayed_answers = {a.name: a.value for a in result.answers}
    answers_ok = replayed_answers == recorded_row["answers"]
    event_shape_ok = event_types == recorded_row["event_types"]

    label = Label(id=0, answers=list(task.expected.items()))
    grade = grade_question(result.answers, label, mode="tolerant")
    truth_ok = grade.all_correct

    return ReplayComparison(
        task_id=task.id,
        status_ok=status_ok,
        answers_ok=answers_ok,
        truth_ok=truth_ok,
        event_shape_ok=event_shape_ok,
    )


@pytest.mark.parametrize("task", ALL_TASKS, ids=[t.id for t in ALL_TASKS])
def test_replay_matches_the_recording_and_the_host_computed_truth(task):
    recorded = _load_recorded_results()
    comparison = replay_task(task, recorded[task.id])
    assert comparison.error is None, f"{task.id}: {comparison.error}"
    assert comparison.status_ok, f"{task.id}: final status changed from the recorded run"
    assert comparison.answers_ok, f"{task.id}: final answers changed from the recorded run"
    assert comparison.event_shape_ok, (
        f"{task.id}: event-type sequence changed from the recorded run"
    )
    assert comparison.truth_ok, f"{task.id}: answer no longer matches the host-computed truth"


def test_replay_suite_catches_a_broken_evidence_check(monkeypatch):
    """Prove the suite actually detects regressions, not just confirms the happy path.

    Breaking `check_evidence` so nothing ever passes changes the recorded
    task's control flow (it tries to repair instead of stopping at
    "answered"), which the frozen cassettes can't serve -- replay_task
    reports that as "not ok" rather than reproducing the original result.
    """
    import sandbox_analyst.agent.loop as agent_loop

    recorded = _load_recorded_results()
    task = ALL_TASKS[0]
    assert recorded[task.id]["status"] == "answered", "test assumes this task's recording succeeded"

    def _always_fail_evidence(answers, stdout):
        return [
            agent_loop.EvidenceResult(name=a.name, value=a.value, passed=False, reason="broken")
            for a in answers
        ]

    monkeypatch.setattr(agent_loop, "check_evidence", _always_fail_evidence)

    comparison = replay_task(task, recorded[task.id])

    assert not comparison.ok
    assert not comparison.status_ok or comparison.error is not None


def test_replay_suite_catches_a_broken_answer_parser(monkeypatch):
    """Same proof, via the other example the task spec names: a corrupted answer parser."""
    import sandbox_analyst.agent.loop as agent_loop

    recorded = _load_recorded_results()
    task = ALL_TASKS[0]
    assert recorded[task.id]["status"] == "answered", "test assumes this task's recording succeeded"

    original_parse = agent_loop.parse_final_answer

    def _corrupting_parse(reply, answer_format=None):
        final = original_parse(reply, answer_format)
        tampered = [
            type(a)(name=a.name, value="definitely-not-the-real-answer") for a in final.answers
        ]
        return final.model_copy(update={"answers": tampered})

    monkeypatch.setattr(agent_loop, "parse_final_answer", _corrupting_parse)

    comparison = replay_task(task, recorded[task.id])

    assert not comparison.ok
