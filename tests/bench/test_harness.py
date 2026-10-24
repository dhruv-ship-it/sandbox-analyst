import json
import re
import subprocess
from pathlib import Path

import pytest

from sandbox_analyst.agent.prompts import PROMPT_VERSION
from sandbox_analyst.bench.dabench import Question
from sandbox_analyst.bench.download import PINNED_REVISION
from sandbox_analyst.bench.harness import (
    HeldOutRunRequired,
    ResultsWriter,
    build_manifest,
    done_ids,
    load_questions_for_split,
    run_eval,
    run_one_question,
    write_manifest,
)
from sandbox_analyst.bench.split import SplitLockedError
from sandbox_analyst.config import Settings
from sandbox_analyst.llm import FakeLLM, LLMConfigError, LLMResponse
from sandbox_analyst.sandbox import ExecError, ExecResult, FakeSandbox, SandboxCrashed
from sandbox_analyst.sandbox.modal_image import PINNED_PACKAGES

CSV = b"x,y\n1,2\n3,4\n"


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


def _question(id_: int, file_name: str, level: str = "easy") -> Question:
    return Question(
        id=id_,
        question=f"question {id_}?",
        concepts=[],
        constraints="",
        format="",
        file_name=file_name,
        level=level,
    )


def _ok(stdout: str) -> ExecResult:
    return ExecResult(
        stdout=stdout,
        stderr="",
        exit_code=0,
        error=None,
        images=[],
        duration_ms=5,
        timed_out=False,
        truncated=False,
    )


def _err(name: str, value: str) -> ExecResult:
    return ExecResult(
        stdout="",
        stderr="",
        exit_code=1,
        error=ExecError(name=name, value=value, traceback=f"Traceback...\n{name}: {value}"),
        images=[],
        duration_ms=5,
        timed_out=False,
        truncated=False,
    )


def _code(body: str) -> str:
    return f"```python\n{body}\n```"


def _answer(name: str, value: str) -> str:
    return f'{{"answers": [{{"name": "{name}", "value": "{value}"}}], "explanation": "ok"}}'


def _read_results(run_dir: Path) -> list[dict]:
    path = run_dir / "results.jsonl"
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _generic_respond(messages, **kwargs):
    text = messages[-1].content
    if "Executed code:" in text:
        match = re.search(r"x = (\d+)", text)
        value = match.group(1) if match else "0"
        reply = f'{{"answers": [{{"name": "x", "value": "{value}"}}], "explanation": "ok"}}'
    else:
        reply = "```python\nprint('x =', 1)\n```"
    return LLMResponse(
        text=reply,
        reasoning=None,
        prompt_tokens=10,
        completion_tokens=10,
        latency_ms=0,
        provider="fake",
        model="fake-model",
        finish_reason="stop",
    )


# ---- run_one_question: per-attempt detail ----


def test_run_one_question_happy_path_builds_a_full_result(tmp_path, monkeypatch):
    import sandbox_analyst.agent.loop as loop_module

    monkeypatch.setattr(loop_module, "DEFAULT_ARTIFACTS_DIR", tmp_path / "artifacts")
    import sandbox_analyst.agent.trace as trace_module

    monkeypatch.setattr(trace_module, "DEFAULT_TRACE_DIR", tmp_path / "traces")

    q = _question(1, "a.csv")
    llm = FakeLLM([_code("print('x =', 1)"), _answer("x", "1")])
    sandbox = FakeSandbox([_ok("x = 1\n")])

    result = run_one_question(q, CSV, llm, sandbox, _settings())

    assert result.id == 1
    assert result.level == "easy"
    assert result.status == "answered"
    assert result.final_answers == [{"name": "x", "value": "1"}]
    assert len(result.attempts) == 1
    attempt = result.attempts[0]
    assert attempt.attempt == 1
    assert attempt.code_hash is not None
    assert attempt.check_ok is True
    assert attempt.exec_outcome == "ok"
    assert attempt.error_type is None
    assert attempt.evidenced_answers == [{"name": "x", "value": "1"}]
    assert attempt.unverified_answers == []
    assert result.llm_request_count == 2
    assert result.wall_time_ms >= 0
    assert Path(result.trace_path).exists()


def test_run_one_question_checker_blocked_attempt(tmp_path, monkeypatch):
    import sandbox_analyst.agent.loop as loop_module

    monkeypatch.setattr(loop_module, "DEFAULT_ARTIFACTS_DIR", tmp_path / "artifacts")
    import sandbox_analyst.agent.trace as trace_module

    monkeypatch.setattr(trace_module, "DEFAULT_TRACE_DIR", tmp_path / "traces")

    q = _question(1, "a.csv")
    llm = FakeLLM(
        [_code("import os\nprint(os.getcwd())"), _code("print('x =', 1)"), _answer("x", "1")]
    )
    sandbox = FakeSandbox([_ok("x = 1\n")])

    result = run_one_question(q, CSV, llm, sandbox, _settings())

    assert result.status == "answered"
    blocked = result.attempts[0]
    assert blocked.check_ok is False
    assert blocked.exec_outcome == "no_exec"


def test_run_one_question_crash_is_distinguished_from_an_exec_error(tmp_path, monkeypatch):
    import sandbox_analyst.agent.loop as loop_module

    monkeypatch.setattr(loop_module, "DEFAULT_ARTIFACTS_DIR", tmp_path / "artifacts")
    import sandbox_analyst.agent.trace as trace_module

    monkeypatch.setattr(trace_module, "DEFAULT_TRACE_DIR", tmp_path / "traces")

    q = _question(1, "a.csv")
    llm = FakeLLM([_code("x = 1"), _code("print('x =', 1)"), _answer("x", "1")])
    sandbox = FakeSandbox([SandboxCrashed("oom"), _ok("x = 1\n")])

    result = run_one_question(q, CSV, llm, sandbox, _settings())

    crashed = result.attempts[0]
    assert crashed.exec_outcome == "crashed"
    assert crashed.error_type == "SandboxCrashed"


def test_run_one_question_exec_error_records_the_exception_name(tmp_path, monkeypatch):
    import sandbox_analyst.agent.loop as loop_module

    monkeypatch.setattr(loop_module, "DEFAULT_ARTIFACTS_DIR", tmp_path / "artifacts")
    import sandbox_analyst.agent.trace as trace_module

    monkeypatch.setattr(trace_module, "DEFAULT_TRACE_DIR", tmp_path / "traces")

    q = _question(1, "a.csv")
    llm = FakeLLM([_code("raise KeyError('bad')"), _code("print('x =', 1)"), _answer("x", "1")])
    sandbox = FakeSandbox([_err("KeyError", "'bad'"), _ok("x = 1\n")])

    result = run_one_question(q, CSV, llm, sandbox, _settings())

    errored = result.attempts[0]
    assert errored.exec_outcome == "error"
    assert errored.error_type == "KeyError"


def test_run_one_question_llm_error_is_an_infra_status(tmp_path, monkeypatch):
    import sandbox_analyst.agent.trace as trace_module

    monkeypatch.setattr(trace_module, "DEFAULT_TRACE_DIR", tmp_path / "traces")

    q = _question(1, "a.csv")
    llm = FakeLLM([LLMConfigError("bad key")])
    sandbox = FakeSandbox([])

    result = run_one_question(q, CSV, llm, sandbox, _settings())

    assert result.status == "infra_error"
    assert result.infra_cause == "llm_error"
    assert result.attempts == []


# ---- ResultsWriter / done_ids ----


def test_results_writer_append_and_load_latest(tmp_path):
    from sandbox_analyst.bench.harness import QuestionResult

    writer = ResultsWriter(tmp_path / "results.jsonl")
    writer.append(
        QuestionResult(
            id=1,
            level="easy",
            status="answered",
            infra_cause=None,
            attempts=[],
            final_answers=[],
            prompt_tokens=1,
            completion_tokens=1,
            total_latency_ms=1,
            wall_time_ms=1,
            sandbox_usd=0.0,
            llm_request_count=2,
            trace_path="",
        )
    )
    latest = writer.load_latest()
    assert latest[1]["status"] == "answered"


def test_done_ids_excludes_infra_error():
    latest = {1: {"status": "answered"}, 2: {"status": "infra_error"}, 3: {"status": "failed"}}
    assert done_ids(latest) == {1, 3}


# ---- resume: skip done ids, re-queue infra errors ----


def test_resume_skips_already_done_ids(tmp_path):
    q1, q2 = _question(1, "a.csv"), _question(2, "b.csv")
    run_dir = tmp_path / "run1"

    llm1 = FakeLLM([_code("print('x =', 1)"), _answer("x", "1")])
    sandbox1 = FakeSandbox([_ok("x = 1\n")])
    outcome1 = run_eval(
        split="dev",
        run_name="r1",
        settings=_settings(),
        questions=[q1],
        csv_loader=lambda q: CSV,
        llm=llm1,
        sandbox_factory=lambda q: sandbox1,
        run_dir=run_dir,
        concurrency=1,
    )
    assert outcome1.n_answered == 1

    llm2 = FakeLLM([_code("print('y =', 2)"), _answer("y", "2")])
    sandbox2 = FakeSandbox([_ok("y = 2\n")])
    outcome2 = run_eval(
        split="dev",
        run_name="r1",
        settings=_settings(),
        questions=[q1, q2],
        csv_loader=lambda q: CSV,
        llm=llm2,
        sandbox_factory=lambda q: sandbox2,
        run_dir=run_dir,
        concurrency=1,
    )
    assert outcome2.n_remaining == 0
    assert len(llm2.calls) == 2  # only q2's calls; q1 was never re-submitted
    results = _read_results(run_dir)
    assert {r["id"] for r in results} == {1, 2}


def test_infra_errors_are_requeued_on_resume(tmp_path):
    q1 = _question(1, "a.csv")
    run_dir = tmp_path / "run1"

    llm1 = FakeLLM([LLMConfigError("bad key")])
    outcome1 = run_eval(
        split="dev",
        run_name="r1",
        settings=_settings(),
        questions=[q1],
        csv_loader=lambda q: CSV,
        llm=llm1,
        sandbox_factory=lambda q: FakeSandbox([]),
        run_dir=run_dir,
        concurrency=1,
    )
    assert outcome1.n_infra_errors == 1
    assert outcome1.n_answered == 0

    llm2 = FakeLLM([_code("print('x =', 1)"), _answer("x", "1")])
    sandbox2 = FakeSandbox([_ok("x = 1\n")])
    outcome2 = run_eval(
        split="dev",
        run_name="r1",
        settings=_settings(),
        questions=[q1],
        csv_loader=lambda q: CSV,
        llm=llm2,
        sandbox_factory=lambda q: sandbox2,
        run_dir=run_dir,
        concurrency=1,
    )
    assert outcome2.n_answered == 1
    assert outcome2.n_infra_errors == 0

    rows = _read_results(run_dir)
    assert len([r for r in rows if r["id"] == 1]) == 2  # append-only: both attempts recorded
    latest_status = {r["id"]: r["status"] for r in rows}
    assert latest_status[1] == "answered"  # last line wins


# ---- clean stop: token budget ----


def test_token_budget_stop(tmp_path):
    questions = [_question(i, f"{i}.csv") for i in (1, 2, 3)]
    llm = FakeLLM([_code("print('x =', 1)"), _answer("x", "1")])  # exactly one question's worth

    outcome = run_eval(
        split="dev",
        run_name="r1",
        settings=_settings(),
        questions=questions,
        csv_loader=lambda q: CSV,
        llm=llm,
        sandbox_factory=lambda q: FakeSandbox([_ok("x = 1\n")]),
        run_dir=tmp_path / "run1",
        concurrency=1,
        token_budget=10,
    )

    assert outcome.stopped_clean is True
    assert outcome.stop_reason == "token_budget"
    assert outcome.n_done == 1
    assert outcome.n_remaining == 2
    assert outcome.resume_command is not None
    assert "--run-name r1" in outcome.resume_command


def test_no_stop_reason_when_everything_finishes(tmp_path):
    q = _question(1, "a.csv")
    llm = FakeLLM([_code("print('x =', 1)"), _answer("x", "1")])
    outcome = run_eval(
        split="dev",
        run_name="r1",
        settings=_settings(),
        questions=[q],
        csv_loader=lambda q: CSV,
        llm=llm,
        sandbox_factory=lambda q: FakeSandbox([_ok("x = 1\n")]),
        run_dir=tmp_path / "run1",
        concurrency=1,
    )
    assert outcome.stopped_clean is False
    assert outcome.stop_reason is None
    assert outcome.resume_command is None


# ---- thread-safe writing under real concurrency ----


def test_results_are_written_safely_from_multiple_threads(tmp_path):
    n = 12
    questions = [_question(i, f"{i}.csv") for i in range(n)]
    sandboxes = {q.id: FakeSandbox([_ok(f"x = {q.id}\n")]) for q in questions}
    llm = FakeLLM(respond=_generic_respond)

    outcome = run_eval(
        split="dev",
        run_name="r1",
        settings=_settings(),
        questions=questions,
        csv_loader=lambda q: CSV,
        llm=llm,
        sandbox_factory=lambda q: sandboxes[q.id],
        run_dir=tmp_path / "run1",
        concurrency=6,
    )

    assert outcome.n_answered == n
    results = _read_results(tmp_path / "run1")
    assert len(results) == n
    assert {r["id"] for r in results} == set(range(n))
    for r in results:
        assert r["final_answers"] == [{"name": "x", "value": str(r["id"])}]


# ---- manifest ----


def test_build_manifest_fields():
    settings = _settings(sa_llm_provider="nim", sa_llm_model="openai/gpt-oss-20b")
    manifest = build_manifest(
        run_name="r1",
        split="dev",
        settings=settings,
        concurrency=6,
        token_budget=1_500_000,
        git_sha="abc123",
    )
    assert manifest.run_name == "r1"
    assert manifest.split == "dev"
    assert manifest.git_sha == "abc123"
    assert manifest.prompt_version == PROMPT_VERSION
    assert manifest.provider == "nim"
    assert manifest.model == "openai/gpt-oss-20b"
    assert manifest.temperature == settings.llm_temperature
    assert manifest.top_p == settings.llm_top_p
    assert manifest.max_tokens == settings.llm_max_tokens
    assert manifest.reasoning_effort == settings.llm_reasoning_effort
    assert manifest.llm_timeout_s == settings.llm_timeout_s
    assert manifest.sandbox_image_pins == list(PINNED_PACKAGES)
    assert manifest.dabench_revision == PINNED_REVISION
    assert manifest.concurrency == 6
    assert manifest.run_timeout_s == settings.run_timeout_s
    assert manifest.token_budget == 1_500_000
    assert manifest.date


def test_write_manifest_creates_a_real_json_file(tmp_path):
    manifest = build_manifest(
        run_name="r1", split="dev", settings=_settings(), concurrency=6, token_budget=100
    )
    path = write_manifest(manifest, tmp_path / "run1")
    assert path.exists()
    data = json.loads(path.read_text())
    assert data["run_name"] == "r1"


def test_run_eval_writes_a_manifest(tmp_path):
    q = _question(1, "a.csv")
    llm = FakeLLM([_code("print('x =', 1)"), _answer("x", "1")])
    run_eval(
        split="dev",
        run_name="r1",
        settings=_settings(),
        questions=[q],
        csv_loader=lambda q: CSV,
        llm=llm,
        sandbox_factory=lambda q: FakeSandbox([_ok("x = 1\n")]),
        run_dir=tmp_path / "run1",
        concurrency=1,
    )
    assert (tmp_path / "run1" / "manifest.json").exists()


# ---- test-split refusal ----


def test_load_questions_for_split_refuses_test_without_the_flag():
    with pytest.raises(HeldOutRunRequired):
        load_questions_for_split("test", final_held_out_run=False)


def test_load_questions_for_split_still_enforces_the_git_gate_when_flagged(tmp_path):
    questions_path = tmp_path / "questions.jsonl"
    questions_path.write_text(
        '{"id": 1, "question": "q", "concepts": [], "constraints": "c", "format": "f", '
        '"file_name": "a.csv", "level": "easy"}\n',
        encoding="utf-8",
    )
    split_path = tmp_path / "split.json"
    split_path.write_text(json.dumps({"test": {"question_ids": [1]}}), encoding="utf-8")

    def dirty_git_run(*args):
        return subprocess.CompletedProcess(args, 0, stdout=" M dirty_file.py\n", stderr="")

    with pytest.raises(SplitLockedError):
        load_questions_for_split(
            "test",
            final_held_out_run=True,
            split_path=split_path,
            questions_path=questions_path,
            git_run=dirty_git_run,
        )


def test_run_eval_refuses_test_split_without_the_flag(tmp_path):
    with pytest.raises(HeldOutRunRequired):
        run_eval(
            split="test",
            run_name="r1",
            settings=_settings(),
            run_dir=tmp_path / "run1",
        )
