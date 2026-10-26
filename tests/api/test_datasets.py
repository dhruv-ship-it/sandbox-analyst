import io

import pytest

from sandbox_analyst.api.datasets import DatasetError, DatasetStore, sniff_binary


def _upload(client, name: str, content: bytes, content_type: str = "text/csv"):
    return client.post("/api/datasets", files={"file": (name, io.BytesIO(content), content_type)})


# ---- POST /api/datasets ----


def test_upload_rejects_non_csv_name(client):
    response = _upload(client, "data.txt", b"a,b\n1,2\n")
    assert response.status_code == 400
    body = response.json()
    assert body["error"] == "invalid_dataset"
    assert ".csv" in body["detail"]


def test_upload_rejects_too_large(build_client):
    # Sized to land between the dataset-level cap and the request-size middleware's
    # own (more generous) cap, so this exercises the dataset-level 400 specifically.
    client = build_client(api_max_upload_mb=0.01)  # ~10.5 KB
    big_csv = b"a,b\n" + b"1,2\n" * 3_500  # ~14 KB
    response = _upload(client, "big.csv", big_csv)
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_dataset"


def test_upload_size_guard_middleware_rejects_oversized_bodies(build_client):
    client = build_client(api_max_upload_mb=0.001)  # ~1 KB, body will exceed even the headroom
    big_csv = b"a,b\n" + b"1,2\n" * 10_000
    response = _upload(client, "big.csv", big_csv)
    assert response.status_code == 413
    assert response.json()["error"] == "request_too_large"


def test_upload_rejects_unparseable_csv(client):
    # A completely empty file has no header for pandas to parse.
    response = _upload(client, "empty.csv", b"")
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_dataset"


def test_upload_rejects_too_many_columns(build_client):
    client = build_client(api_max_cols=2)
    csv = b"a,b,c\n1,2,3\n"
    response = _upload(client, "wide.csv", csv)
    assert response.status_code == 400
    assert "column" in response.json()["detail"]


def test_upload_rejects_too_many_rows(build_client):
    client = build_client(api_max_rows=2)
    csv = "a\n" + "\n".join(str(i) for i in range(5)) + "\n"
    response = _upload(client, "tall.csv", csv.encode())
    assert response.status_code == 400
    assert "row" in response.json()["detail"]


# ---- binary-content sniffing (D-107) ----


# A minimal, structurally valid 1x1 PNG -- the exact red-team-D payload
# (`non_csv_disguised_as_csv`) that previously got a 200 and was stored.
_PNG_BYTES = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108"
    "0600000031b2619a0000000a4944415478da6360000002000154a24f6b0000000049454e44ae426082"
)


@pytest.mark.parametrize(
    ("name", "data"),
    [
        ("png", _PNG_BYTES),
        ("zip_xlsx", b"PK\x03\x04" + b"\x00" * 20),
        ("pdf", b"%PDF-1.4\n" + b"\x00" * 20),
        ("gzip", b"\x1f\x8b\x08\x00" + b"\x00" * 20),
        ("jpeg", b"\xff\xd8\xff\xe0" + b"\x00" * 20),
        ("gif", b"GIF89a" + b"\x00" * 20),
        ("nul_bytes", b"a,b\n1,\x002\n"),
        ("mostly_control_bytes", bytes(range(32)) * 100),
    ],
)
def test_sniff_binary_flags_binary_content(name, data):
    assert sniff_binary(data) is not None


def test_sniff_binary_accepts_plain_utf8_csv():
    assert sniff_binary(b"a,b\n1,2\n") is None


def test_sniff_binary_accepts_latin1_csv_with_accented_bytes():
    # 0xE9 ("é" in latin-1) is a high byte, not a control byte -- must pass.
    csv = "name,city\nAndre,Montreal\n".encode("latin-1")
    accented = csv.replace(b"Montreal", "Montréal".encode("latin-1"))
    assert sniff_binary(accented) is None


def test_sniff_binary_accepts_empty_file():
    # Rejected elsewhere for being unparseable, not as "binary".
    assert sniff_binary(b"") is None


def test_upload_rejects_png_disguised_as_csv(client):
    response = _upload(client, "image.csv", _PNG_BYTES)
    assert response.status_code == 400
    body = response.json()
    assert body["error"] == "invalid_dataset"
    assert "binary" in body["detail"]


def test_upload_accepts_a_valid_csv(client):
    csv = b"a,b\n1,2\n3,4\n"
    response = _upload(client, "ok.csv", csv)
    assert response.status_code == 200
    body = response.json()
    assert body["dataset_id"]
    assert body["file_name"] == "ok.csv"
    assert body["n_rows"] == 2
    assert body["n_cols"] == 2
    assert [c["name"] for c in body["columns"]] == ["a", "b"]
    assert len(body["sample_rows"]) == 2


# ---- GET /api/examples, POST /api/examples/{name}/load ----


def test_list_examples_has_three_datasets_with_questions(client):
    body = client.get("/api/examples").json()
    assert set(body.keys()) == {"sales", "students", "weather"}
    for info in body.values():
        assert info["title"]
        assert info["description"]
        assert len(info["questions"]) == 3


def test_load_unknown_example_is_404(client):
    response = client.post("/api/examples/not-a-real-one/load")
    assert response.status_code == 404
    assert response.json()["error"] == "not_found"


def test_load_example_returns_a_usable_dataset_id(client):
    response = client.post("/api/examples/students/load")
    assert response.status_code == 200
    body = response.json()
    assert body["dataset_id"]
    assert body["file_name"] == "students.csv"
    assert body["n_rows"] > 0


# ---- TTL expiry ----


def test_dataset_store_expires_entries_past_their_ttl(tmp_path):
    store = DatasetStore(tmp_path, ttl_s=-1, max_upload_mb=5, max_rows=1000, max_cols=100)
    dataset_id = store.store("x.csv", b"a\n1\n")
    assert store.get(dataset_id) is None  # ttl_s=-1: expired the instant it's created


def test_dataset_store_rejects_and_keeps_valid_entries(tmp_path):
    store = DatasetStore(tmp_path, ttl_s=3600, max_upload_mb=5, max_rows=1000, max_cols=100)
    try:
        store.validate_and_profile("x.txt", b"a\n1\n")
        raise AssertionError("expected DatasetError")
    except DatasetError:
        pass
    dataset_id = store.store("x.csv", b"a\n1\n")
    assert store.get(dataset_id) is not None


def test_run_against_an_expired_dataset_is_404(build_client):
    client = build_client(api_upload_ttl_s=-1)
    response = client.post("/api/examples/sales/load")
    dataset_id = response.json()["dataset_id"]
    run_response = client.post(
        "/api/runs", json={"dataset_id": dataset_id, "question": "anything?"}
    )
    assert run_response.status_code == 404
    assert run_response.json()["error"] == "not_found"
