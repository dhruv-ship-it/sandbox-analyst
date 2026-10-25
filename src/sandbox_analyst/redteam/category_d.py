"""Category D: upload abuse against the real API, via FastAPI's TestClient.

Every case's bytes are synthesized parametrically (a boundary size, a
column count, a byte pattern) rather than drawn from a fixed payload
file -- unlike categories A/B, there's no meaningful crafted "payload"
content here, just a boundary condition, so CLAUDE.md rule 7's "payloads
live only in eval/redteam/" doesn't apply to this category (see D-101 in
DECISIONS.md). HANDLED = a correct 4xx, and nothing stored (confirmed by
checking the dataset store's own upload directory is empty afterward).
"""

import io
from collections.abc import Callable
from pathlib import Path

from fastapi.testclient import TestClient

from sandbox_analyst.api import create_app
from sandbox_analyst.config import Settings
from sandbox_analyst.llm import FakeLLM
from sandbox_analyst.sandbox import FakeSandbox

from .cases import CaseResult


def _non_csv_disguised_as_csv() -> tuple[str, bytes]:
    # A minimal, structurally valid 1x1 PNG, renamed with a .csv extension.
    png = bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108"
        "0600000031b2619a0000000a4944415478da6360000002000154a24f6b0000000049454e44ae426082"
    )
    return "image.csv", png


def _binary_junk() -> tuple[str, bytes]:
    return "junk.csv", bytes(range(256)) * 50


def _over_max_upload_mb(max_mb: float) -> tuple[str, bytes]:
    target_bytes = int((max_mb + 1) * 1024 * 1024)
    row = b"1,2,3,4,5\n"
    rows_needed = target_bytes // len(row) + 1
    return "big.csv", b"a,b,c,d,e\n" + row * rows_needed


def _over_max_columns(max_cols: int) -> tuple[str, bytes]:
    n_cols = max_cols + 1
    header = ",".join(f"c{i}" for i in range(n_cols))
    row = ",".join("1" for _ in range(n_cols))
    return "wide.csv", f"{header}\n{row}\n".encode()


def _path_traversal_name() -> tuple[str, bytes]:
    return "../../../etc/passwd.csv", b"a,b\n1,2\n"


def _empty_file() -> tuple[str, bytes]:
    return "empty.csv", b""


CASE_BUILDERS: dict[str, Callable[[], tuple[str, bytes]]] = {
    "non_csv_disguised_as_csv": _non_csv_disguised_as_csv,
    "binary_junk": _binary_junk,
    "path_traversal_filename": _path_traversal_name,
    "empty_file": _empty_file,
}


def _build_client(tmp_path: Path) -> TestClient:
    settings = Settings(
        sa_data_dir=str(tmp_path / "redteam-category-d"),
        sa_llm_provider="fake",
        sa_sandbox="fake",
    )
    app = create_app(settings, llm=FakeLLM(), sandbox_factory=lambda: FakeSandbox())
    return TestClient(app)


def _uploads_dir_is_empty(tmp_path: Path) -> bool:
    uploads_dir = tmp_path / "redteam-category-d" / "uploads"
    if not uploads_dir.exists():
        return True
    return not any(uploads_dir.iterdir())


def run_category_d_case(case_id: str, file_name: str, data: bytes, tmp_path: Path) -> CaseResult:
    client = _build_client(tmp_path)
    response = client.post(
        "/api/datasets", files={"file": (file_name, io.BytesIO(data), "text/csv")}
    )
    is_4xx = 400 <= response.status_code < 500
    nothing_stored = _uploads_dir_is_empty(tmp_path)
    handled = is_4xx and nothing_stored
    reason = (
        f"got {response.status_code}, uploads dir empty={nothing_stored}"
        if handled
        else f"NOT handled: status={response.status_code}, uploads dir empty={nothing_stored}"
    )
    return CaseResult(
        case_id=case_id,
        category="D",
        handled=handled,
        reason=reason,
        status=str(response.status_code),
        extra={"response_body": response.json() if response.status_code != 204 else None},
    )


def run_category_d(tmp_path: Path, settings: Settings | None = None) -> list[CaseResult]:
    max_mb = (settings or Settings()).api_max_upload_mb
    max_cols = (settings or Settings()).api_max_cols
    all_builders = dict(CASE_BUILDERS)
    all_builders["over_max_upload_size"] = lambda: _over_max_upload_mb(max_mb)
    all_builders["over_max_columns"] = lambda: _over_max_columns(max_cols)

    results = []
    for case_id, builder in all_builders.items():
        file_name, data = builder()
        results.append(run_category_d_case(case_id, file_name, data, tmp_path / case_id))
    return results
