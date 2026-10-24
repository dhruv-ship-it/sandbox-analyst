import json

from sandbox_analyst.agent.events import EventEmitter
from sandbox_analyst.agent.trace import TraceWriter


def test_trace_writer_creates_one_jsonl_line_per_event(tmp_path):
    writer = TraceWriter("run-1", trace_dir=tmp_path)
    emitter = EventEmitter("run-1", on_event=writer)

    emitter.emit("run_started", 0, {"prompt_version": "v1"})
    emitter.emit("code", 1, {"code": "print(1)"})

    lines = writer.path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["type"] == "run_started"
    assert first["seq"] == 0
    assert first["payload"] == {"prompt_version": "v1"}


def test_trace_writer_path_is_named_after_run_id(tmp_path):
    writer = TraceWriter("abc123", trace_dir=tmp_path)
    assert writer.path == tmp_path / "abc123.jsonl"


def test_trace_writer_appends_across_multiple_runs_to_separate_files(tmp_path):
    writer_a = TraceWriter("run-a", trace_dir=tmp_path)
    writer_b = TraceWriter("run-b", trace_dir=tmp_path)
    emitter_a = EventEmitter("run-a", on_event=writer_a)
    emitter_b = EventEmitter("run-b", on_event=writer_b)

    emitter_a.emit("run_started", 0, {})
    emitter_b.emit("run_started", 0, {})
    emitter_a.emit("run_finished", 0, {})

    assert len(writer_a.path.read_text(encoding="utf-8").splitlines()) == 2
    assert len(writer_b.path.read_text(encoding="utf-8").splitlines()) == 1


def test_trace_writer_creates_the_trace_dir_if_missing(tmp_path):
    nested = tmp_path / "nested" / "traces"
    writer = TraceWriter("run-1", trace_dir=nested)
    emitter = EventEmitter("run-1", on_event=writer)
    emitter.emit("run_started", 0, {})
    assert writer.path.exists()
