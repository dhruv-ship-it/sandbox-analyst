import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sandbox_analyst.agent.prompts import ANSWER_SYSTEM_PROMPT
from sandbox_analyst.api import create_app
from sandbox_analyst.config import Settings
from sandbox_analyst.llm import FakeLLM, LLMResponse
from sandbox_analyst.sandbox import FakeSandbox
from sandbox_analyst.sandbox.base import ExecResult


def repeatable_llm(value: str = "42", name: str = "result") -> FakeLLM:
    """An LLM that answers the same way for every run, never exhausting a queue."""

    def respond(messages, **kwargs) -> LLMResponse:
        if messages and messages[0].content == ANSWER_SYSTEM_PROMPT:
            text = json.dumps({"answers": [{"name": name, "value": value}], "explanation": "ok"})
        else:
            text = f"```python\nprint({value})\n```"
        return LLMResponse(
            text=text,
            reasoning=None,
            prompt_tokens=10,
            completion_tokens=10,
            latency_ms=0,
            provider="fake",
            model="fake-model",
            finish_reason="stop",
        )

    return FakeLLM(respond=respond)


def repeatable_sandbox_factory(stdout: str = "42\n", images: list[bytes] | None = None):
    """A sandbox_factory producing a fresh, single-use FakeSandbox each call."""

    def factory() -> FakeSandbox:
        result = ExecResult(
            stdout=stdout,
            stderr="",
            exit_code=0,
            error=None,
            images=list(images or []),
            duration_ms=5,
            timed_out=False,
            truncated=False,
        )
        return FakeSandbox(script=[result])

    return factory


@pytest.fixture
def build_client(tmp_path: Path):
    """Build a TestClient; defaults to repeatable fakes and a tmp_path data dir.

    Any Settings field can be overridden via a kwarg (e.g. `api_max_rows=5`).
    `client_addr` controls the TestClient's reported socket peer, for
    testing X-Forwarded-For trust behavior; `images` scripts the fake
    sandbox's chart output for the artifact-serving tests.
    """

    def build(
        *,
        llm=None,
        answer_value: str = "42",
        answer_name: str = "result",
        images: list[bytes] | None = None,
        client_addr: tuple[str, int] = ("testclient", 50000),
        **settings_overrides,
    ) -> TestClient:
        settings_overrides.setdefault("sa_data_dir", str(tmp_path / "api-data"))
        settings_overrides.setdefault("sa_llm_provider", "fake")
        settings_overrides.setdefault("sa_sandbox", "fake")
        settings = Settings(**settings_overrides)
        app = create_app(
            settings,
            llm=llm if llm is not None else repeatable_llm(answer_value, answer_name),
            sandbox_factory=repeatable_sandbox_factory(images=images),
        )
        return TestClient(app, client=client_addr)

    return build


@pytest.fixture
def client(build_client) -> TestClient:
    return build_client()


@pytest.fixture
def load_sales_dataset():
    def _load(client: TestClient) -> str:
        response = client.post("/api/examples/sales/load")
        assert response.status_code == 200
        return response.json()["dataset_id"]

    return _load


@pytest.fixture
def drain_sse():
    """Read an SSE stream to completion, returning the parsed event dicts in order."""

    def _drain(client: TestClient, run_id: str) -> list[dict]:
        events = []
        with client.stream("GET", f"/api/runs/{run_id}/events") as response:
            assert response.status_code == 200
            for line in response.iter_lines():
                if line.startswith("data:"):
                    events.append(json.loads(line[len("data:") :]))
        return events

    return _drain


@pytest.fixture
def wait_for_run():
    """Poll the run summary until it reaches a terminal status. Test-only synchronization."""

    def _wait(client: TestClient, run_id: str, timeout: float = 5.0) -> dict:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            body = client.get(f"/api/runs/{run_id}").json()
            if body["status"] not in ("pending", "running"):
                return body
            time.sleep(0.01)
        raise TimeoutError(f"run {run_id} did not finish within {timeout}s")

    return _wait
