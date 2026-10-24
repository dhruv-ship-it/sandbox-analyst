import json

import pytest

from sandbox_analyst.agent import loop as agent_loop


def _create_run(client, dataset_id: str, question: str = "what is the total revenue?"):
    return client.post("/api/runs", json={"dataset_id": dataset_id, "question": question})


# ---- full lifecycle ----


def test_full_run_lifecycle(client, load_sales_dataset, wait_for_run):
    dataset_id = load_sales_dataset(client)
    response = _create_run(client, dataset_id)
    assert response.status_code == 200
    run_id = response.json()["run_id"]
    assert run_id

    summary = wait_for_run(client, run_id)
    assert summary["status"] == "answered"
    assert summary["answers"] == [{"name": "result", "value": "42"}]
    assert summary["explanation"] == "ok"
    assert "print(42)" in summary["code"]
    assert summary["stdout_tail"].strip() == "42"
    assert summary["evidence"][0]["passed"] is True
    assert len(summary["attempts"]) == 1
    assert summary["attempts"][0]["exec_ok"] is True
    assert summary["chart_urls"] == []
    assert summary["prompt_tokens"] > 0
    assert summary["latency_ms"] >= 0

    trace_response = client.get(f"/api/runs/{run_id}/trace")
    assert trace_response.status_code == 200
    lines = [json.loads(line) for line in trace_response.text.splitlines() if line]
    assert lines[-1]["type"] == "run_finished"


def test_run_create_rejects_a_question_that_is_too_short(client, load_sales_dataset):
    dataset_id = load_sales_dataset(client)
    response = _create_run(client, dataset_id, question="hi")
    assert response.status_code == 422
    assert response.json()["error"] == "validation_error"


def test_run_create_rejects_a_question_that_is_too_long(client, load_sales_dataset):
    dataset_id = load_sales_dataset(client)
    response = _create_run(client, dataset_id, question="x" * 501)
    assert response.status_code == 422


def test_run_create_unknown_dataset_is_404(client):
    response = _create_run(client, "no-such-dataset")
    assert response.status_code == 404
    assert response.json()["error"] == "not_found"


# ---- SSE ordering and termination ----


def test_sse_replays_events_in_order_and_closes_after_run_finished(
    client, load_sales_dataset, wait_for_run, drain_sse
):
    dataset_id = load_sales_dataset(client)
    run_id = _create_run(client, dataset_id).json()["run_id"]
    wait_for_run(client, run_id)  # let it finish before we even subscribe (replay path)

    events = drain_sse(client, run_id)
    assert [e["type"] for e in events][0] == "run_started"
    assert [e["type"] for e in events][-1] == "run_finished"
    assert [e["seq"] for e in events] == sorted(e["seq"] for e in events)
    assert all(e["run_id"] == run_id for e in events)


def test_sse_unknown_run_id_is_404(client):
    response = client.get("/api/runs/no-such-run/events")
    assert response.status_code == 404


# ---- unknown ids -> 404 everywhere ----


def test_run_summary_unknown_id_is_404(client):
    assert client.get("/api/runs/no-such-run").status_code == 404


def test_run_trace_unknown_id_is_404(client):
    assert client.get("/api/runs/no-such-run/trace").status_code == 404


def test_run_artifact_unknown_run_id_is_404(client):
    assert client.get("/api/runs/no-such-run/artifacts/attempt1_0.png").status_code == 404


# ---- chart artifacts ----


def test_run_with_a_chart_returns_a_chart_url_that_serves_a_png(
    build_client, monkeypatch, tmp_path, load_sales_dataset, wait_for_run
):
    monkeypatch.setattr(agent_loop, "DEFAULT_ARTIFACTS_DIR", tmp_path / "artifacts")
    png_bytes = b"\x89PNG\r\n\x1a\nnot a real png but bytes are bytes"
    client = build_client(images=[png_bytes])
    dataset_id = load_sales_dataset(client)
    run_id = _create_run(client, dataset_id, "plot units per region as a bar chart").json()[
        "run_id"
    ]
    summary = wait_for_run(client, run_id)

    assert summary["status"] == "answered"
    assert len(summary["chart_urls"]) == 1
    chart_url = summary["chart_urls"][0]
    assert chart_url == f"/api/runs/{run_id}/artifacts/attempt1_0.png"

    image_response = client.get(chart_url)
    assert image_response.status_code == 200
    assert image_response.headers["content-type"] == "image/png"
    assert image_response.content == png_bytes


@pytest.mark.parametrize(
    "bad_name",
    [
        "../secret.png",
        "..%2fsecret.png",
        "attempt1_0.png/../../etc",
        "attempt1_0",
        "attempt1_0.jpg",
        "attempt1_0.png.txt",
        "ATTEMPT1_0.PNG",
    ],
)
def test_run_artifact_path_traversal_and_bad_names_are_blocked(
    build_client, monkeypatch, tmp_path, load_sales_dataset, wait_for_run, bad_name
):
    monkeypatch.setattr(agent_loop, "DEFAULT_ARTIFACTS_DIR", tmp_path / "artifacts")
    png_bytes = b"not-really-a-png"
    client = build_client(images=[png_bytes])
    dataset_id = load_sales_dataset(client)
    run_id = _create_run(client, dataset_id, "plot a chart please").json()["run_id"]
    wait_for_run(client, run_id)

    response = client.get(f"/api/runs/{run_id}/artifacts/{bad_name}")
    assert response.status_code == 404
