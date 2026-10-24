"""Unit tests for ModalSandbox's mapping logic, using fake Modal SDK objects.

No network, no real Modal account — every modal.* call that would hit
the network is monkeypatched with an in-memory fake.
"""

import json

import modal
import pytest

from sandbox_analyst.config import Settings
from sandbox_analyst.sandbox.base import SandboxCrashed, SandboxUnavailable
from sandbox_analyst.sandbox.ledger import append_entry, ledger_total_usd, make_entry
from sandbox_analyst.sandbox.modal_sandbox import ModalSandbox


class FakeStream:
    def __init__(self, data: str) -> None:
        self._data = data

    def read(self) -> str:
        return self._data


class FakeProcess:
    def __init__(self, stdout: str = "", stderr: str = "", returncode: int = 0) -> None:
        self.stdout = FakeStream(stdout)
        self.stderr = FakeStream(stderr)
        self._returncode = returncode

    def wait(self) -> int:
        return self._returncode


class FakeFileInfo:
    def __init__(self, name: str, path: str, type_: modal.types.FileType) -> None:
        self.name = name
        self.path = path
        self.type = type_


class FakeFilesystem:
    def __init__(self) -> None:
        self.text_files: dict[str, str] = {}
        self.byte_files: dict[str, bytes] = {}

    def write_bytes(self, data: bytes, remote_path: str) -> None:
        self.byte_files[remote_path] = data

    def write_text(self, data: str, remote_path: str) -> None:
        self.text_files[remote_path] = data

    def read_text(self, remote_path: str) -> str:
        if remote_path not in self.text_files:
            raise modal.exception.SandboxFilesystemNotFoundError(remote_path)
        return self.text_files[remote_path]

    def read_bytes(self, remote_path: str) -> bytes:
        return self.byte_files[remote_path]

    def list_files(self, remote_path: str) -> list[FakeFileInfo]:
        if remote_path not in self._dirs:
            raise modal.exception.SandboxFilesystemNotFoundError(remote_path)
        return self._dirs[remote_path]

    _dirs: dict[str, list[FakeFileInfo]] = {}


class FakeSandboxHandle:
    def __init__(self, process: FakeProcess, out_files: list[FakeFileInfo] | None = None) -> None:
        self.filesystem = FakeFilesystem()
        self.filesystem._dirs = {"/work/out": out_files or []}
        self._process = process
        self.terminated = False
        self.exec_calls: list[tuple] = []

    def exec(self, *args, timeout=None, workdir=None):
        self.exec_calls.append((args, timeout, workdir))
        return self._process

    def terminate(self) -> None:
        self.terminated = True


def _settings(**overrides) -> Settings:
    defaults = dict(_env_file=None, sa_sandbox="modal")
    defaults.update(overrides)
    return Settings(**defaults)


def _patch_modal(monkeypatch, sandbox_handle=None, create_error=None):
    monkeypatch.setattr("sandbox_analyst.sandbox.modal_sandbox.build_image", lambda: "fake-image")
    monkeypatch.setattr(modal.App, "lookup", lambda *a, **k: "fake-app")

    def fake_create(*args, **kwargs):
        if create_error is not None:
            raise create_error
        return sandbox_handle

    monkeypatch.setattr(modal.Sandbox, "create", fake_create)


def test_happy_path_maps_stdout_stderr_exit_code(monkeypatch, tmp_path):
    handle = FakeSandboxHandle(FakeProcess(stdout="hello\n", stderr="", returncode=0))
    _patch_modal(monkeypatch, sandbox_handle=handle)

    sandbox = ModalSandbox(_settings(), ledger_path=tmp_path / "ledger.jsonl")
    result = sandbox.run("print('hello')")

    assert result.stdout == "hello\n"
    assert result.exit_code == 0
    assert result.error is None
    assert result.timed_out is False
    assert handle.terminated is True


def test_uploads_are_written_before_exec(monkeypatch, tmp_path):
    handle = FakeSandboxHandle(FakeProcess())
    _patch_modal(monkeypatch, sandbox_handle=handle)

    sandbox = ModalSandbox(_settings(), ledger_path=tmp_path / "ledger.jsonl")
    sandbox.upload("data.csv", b"a,b\n1,2\n")
    sandbox.run("print(1)")

    assert handle.filesystem.byte_files["/work/data/data.csv"] == b"a,b\n1,2\n"
    assert handle.filesystem.text_files["/work/task.py"] == "print(1)"


def test_timeout_maps_to_timed_out_result(monkeypatch, tmp_path):
    handle = FakeSandboxHandle(FakeProcess(returncode=-1))
    _patch_modal(monkeypatch, sandbox_handle=handle)

    sandbox = ModalSandbox(_settings(), ledger_path=tmp_path / "ledger.jsonl")
    result = sandbox.run("while True: pass", timeout_s=5)

    assert result.timed_out is True
    assert result.exit_code is None


def test_error_json_is_parsed_into_exec_error(monkeypatch, tmp_path):
    handle = FakeSandboxHandle(FakeProcess(returncode=1))
    handle.filesystem.text_files["/work/error.json"] = json.dumps(
        {"name": "ValueError", "value": "bad", "traceback": "Traceback...\nValueError: bad"}
    )
    _patch_modal(monkeypatch, sandbox_handle=handle)

    sandbox = ModalSandbox(_settings(), ledger_path=tmp_path / "ledger.jsonl")
    result = sandbox.run("raise ValueError('bad')")

    assert result.error.name == "ValueError"
    assert result.error.value == "bad"
    assert result.exit_code == 1


def test_missing_error_json_means_no_error(monkeypatch, tmp_path):
    handle = FakeSandboxHandle(FakeProcess(returncode=0))
    _patch_modal(monkeypatch, sandbox_handle=handle)

    sandbox = ModalSandbox(_settings(), ledger_path=tmp_path / "ledger.jsonl")
    result = sandbox.run("print(1)")

    assert result.error is None


def test_png_outputs_are_collected_as_images(monkeypatch, tmp_path):
    out_files = [
        FakeFileInfo("fig_0.png", "/work/out/fig_0.png", modal.types.FileType.FILE),
        FakeFileInfo("fig_1.png", "/work/out/fig_1.png", modal.types.FileType.FILE),
        FakeFileInfo("subdir", "/work/out/subdir", modal.types.FileType.DIRECTORY),
    ]
    handle = FakeSandboxHandle(FakeProcess(), out_files=out_files)
    handle.filesystem.byte_files["/work/out/fig_0.png"] = b"PNGDATA0"
    handle.filesystem.byte_files["/work/out/fig_1.png"] = b"PNGDATA1"
    _patch_modal(monkeypatch, sandbox_handle=handle)

    sandbox = ModalSandbox(_settings(), ledger_path=tmp_path / "ledger.jsonl")
    result = sandbox.run("plt.savefig(...)")

    assert result.images == [b"PNGDATA0", b"PNGDATA1"]


def test_sandbox_create_failure_raises_sandbox_unavailable(monkeypatch, tmp_path):
    _patch_modal(monkeypatch, create_error=modal.exception.AuthError("bad token"))

    sandbox = ModalSandbox(_settings(), ledger_path=tmp_path / "ledger.jsonl")
    with pytest.raises(SandboxUnavailable):
        sandbox.run("print(1)")


def test_exec_failure_raises_sandbox_crashed_and_still_terminates(monkeypatch, tmp_path):
    handle = FakeSandboxHandle(FakeProcess())

    def broken_exec(*args, **kwargs):
        raise modal.exception.ServiceError("worker died")

    handle.exec = broken_exec
    _patch_modal(monkeypatch, sandbox_handle=handle)

    sandbox = ModalSandbox(_settings(), ledger_path=tmp_path / "ledger.jsonl")
    ledger_path = tmp_path / "ledger.jsonl"
    with pytest.raises(SandboxCrashed):
        sandbox.run("print(1)")

    assert handle.terminated is True
    assert ledger_total_usd(ledger_path) >= 0  # a ledger entry was still recorded


def test_budget_exhausted_raises_before_touching_modal(monkeypatch, tmp_path):
    ledger_path = tmp_path / "ledger.jsonl"
    settings = _settings(sa_sandbox_budget_usd=0.01)
    append_entry(
        ledger_path,
        make_entry(
            alive_s=1000,
            cpu=settings.sandbox_cpu,
            memory_gib=1,
            usd_per_core_second=settings.usd_per_core_second,
            usd_per_gib_second=settings.usd_per_gib_second,
        ),
    )
    assert ledger_total_usd(ledger_path) >= settings.sa_sandbox_budget_usd

    called = {"lookup": False}
    monkeypatch.setattr(modal.App, "lookup", lambda *a, **k: called.__setitem__("lookup", True))

    sandbox = ModalSandbox(settings, ledger_path=ledger_path)
    with pytest.raises(SandboxUnavailable, match="budget"):
        sandbox.run("print(1)")

    assert called["lookup"] is False


def test_ledger_entry_recorded_on_success(monkeypatch, tmp_path):
    handle = FakeSandboxHandle(FakeProcess())
    _patch_modal(monkeypatch, sandbox_handle=handle)
    ledger_path = tmp_path / "ledger.jsonl"

    sandbox = ModalSandbox(_settings(), ledger_path=ledger_path)
    sandbox.run("print(1)")

    assert ledger_path.exists()
    entry_line = ledger_path.read_text().strip().splitlines()[0]
    entry = json.loads(entry_line)
    assert entry["cpu"] == sandbox._settings.sandbox_cpu
    assert entry["memory_gib"] == sandbox._settings.sandbox_memory_mib / 1024
    assert entry["alive_s"] >= 0


def test_last_run_cost_usd_equals_the_recorded_ledger_entry(monkeypatch, tmp_path):
    handle = FakeSandboxHandle(FakeProcess())
    _patch_modal(monkeypatch, sandbox_handle=handle)
    ledger_path = tmp_path / "ledger.jsonl"

    sandbox = ModalSandbox(_settings(), ledger_path=ledger_path)
    sandbox.run("print(1)")

    entry = json.loads(ledger_path.read_text().strip().splitlines()[0])
    assert sandbox.last_run_cost_usd == pytest.approx(entry["est_usd"])


def test_last_run_cost_usd_is_recorded_even_when_the_sandbox_crashes(monkeypatch, tmp_path):
    handle = FakeSandboxHandle(FakeProcess())

    def broken_exec(*args, **kwargs):
        raise modal.exception.ServiceError("worker died")

    handle.exec = broken_exec
    _patch_modal(monkeypatch, sandbox_handle=handle)
    ledger_path = tmp_path / "ledger.jsonl"

    sandbox = ModalSandbox(_settings(), ledger_path=ledger_path)
    with pytest.raises(SandboxCrashed):
        sandbox.run("print(1)")

    entry = json.loads(ledger_path.read_text().strip().splitlines()[0])
    assert sandbox.last_run_cost_usd == pytest.approx(entry["est_usd"])
    assert sandbox.last_run_cost_usd >= 0
