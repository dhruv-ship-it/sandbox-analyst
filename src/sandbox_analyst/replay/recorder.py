"""`sa record-replay`: LIVE, one-time recording of the replay regression cassettes.

Runs every task in tests/replay/tasks.json once through the REAL agent
loop (`run_agent`), with the real LLM wrapped in `RecordingLLM` and a
real sandbox wrapped in `RecordingSandbox`. Nothing here is a test --
`tests/replay/test_replay.py` is the offline, no-network pytest that
replays these cassettes in CI.
"""

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from sandbox_analyst.agent import run_agent
from sandbox_analyst.llm import LLMClient, RecordingLLM, make_llm
from sandbox_analyst.sandbox import RecordingSandbox, Sandbox, make_sandbox

from .tasks import DEFAULT_EXAMPLES_DIR, DEFAULT_TASKS_PATH, ReplayTask, load_tasks

if TYPE_CHECKING:
    from sandbox_analyst.config import Settings

DEFAULT_LLM_CASSETTE_PATH = Path("tests/replay/cassettes/llm.jsonl")
DEFAULT_SANDBOX_CASSETTE_PATH = Path("tests/replay/cassettes/sandbox.jsonl")
DEFAULT_RECORDED_RESULTS_PATH = Path("tests/replay/recorded_results.json")


@dataclass(frozen=True)
class RecordedTaskResult:
    task_id: str
    status: str
    n_attempts: int
    n_repairs: int
    answers: dict[str, str]
    event_types: list[str]


@dataclass(frozen=True)
class RecordReplayOutcome:
    results: list[RecordedTaskResult]
    n_needed_repair: int
    llm_cassette_path: Path
    sandbox_cassette_path: Path
    recorded_results_path: Path


def _record_one_task(
    task: ReplayTask,
    *,
    examples_dir: Path,
    recording_llm: LLMClient,
    sandbox_factory: Callable[[], Sandbox],
    settings: "Settings",
) -> RecordedTaskResult:
    csv_bytes = (examples_dir / task.dataset).read_bytes()
    event_types: list[str] = []
    result = run_agent(
        csv_bytes,
        task.dataset,
        task.question,
        llm=recording_llm,
        sandbox_factory=sandbox_factory,
        settings=settings,
        on_event=lambda e: event_types.append(e.type),
        constraints=task.constraints or None,
        answer_format=task.answer_format,
    )
    return RecordedTaskResult(
        task_id=task.id,
        status=result.status,
        n_attempts=len(result.attempts),
        n_repairs=max(0, len(result.attempts) - 1),
        answers={a.name: a.value for a in result.answers},
        event_types=event_types,
    )


def write_recorded_results(
    results: list[RecordedTaskResult], path: Path = DEFAULT_RECORDED_RESULTS_PATH
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([asdict(r) for r in results], indent=2) + "\n", encoding="utf-8")
    return path


def run_record_replay(
    *,
    settings: "Settings",
    tasks: list[ReplayTask] | None = None,
    tasks_path: Path = DEFAULT_TASKS_PATH,
    examples_dir: Path = DEFAULT_EXAMPLES_DIR,
    llm_cassette_path: Path = DEFAULT_LLM_CASSETTE_PATH,
    sandbox_cassette_path: Path = DEFAULT_SANDBOX_CASSETTE_PATH,
    recorded_results_path: Path = DEFAULT_RECORDED_RESULTS_PATH,
) -> RecordReplayOutcome:
    if tasks is None:
        tasks = load_tasks(tasks_path)

    real_llm = make_llm(settings)
    recording_llm = RecordingLLM(real_llm, cassette_path=llm_cassette_path)

    results = []
    for task in tasks:
        real_sandbox = make_sandbox(settings)
        recording_sandbox = RecordingSandbox(real_sandbox, cassette_path=sandbox_cassette_path)
        results.append(
            _record_one_task(
                task,
                examples_dir=examples_dir,
                recording_llm=recording_llm,
                sandbox_factory=lambda sb=recording_sandbox: sb,
                settings=settings,
            )
        )

    write_recorded_results(results, recorded_results_path)
    n_needed_repair = sum(1 for r in results if r.n_repairs > 0)
    return RecordReplayOutcome(
        results=results,
        n_needed_repair=n_needed_repair,
        llm_cassette_path=llm_cassette_path,
        sandbox_cassette_path=sandbox_cassette_path,
        recorded_results_path=recorded_results_path,
    )
