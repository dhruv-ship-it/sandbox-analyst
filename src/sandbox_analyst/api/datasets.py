"""Dataset storage: TTL-backed uploads under SA_DATA_DIR, and the bundled examples."""

import json
import secrets
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from sandbox_analyst.agent.profile import DatasetProfile, profile_csv

EXAMPLES_DIR = Path(__file__).resolve().parent / "examples"


class DatasetError(Exception):
    """A client-facing dataset validation failure. `str(exc)` is safe to return."""


@dataclass
class StoredDataset:
    dataset_id: str
    file_name: str
    path: Path
    created_at: float


def profile_summary(profile: DatasetProfile) -> dict:
    """The JSON shape returned for a newly stored dataset."""
    return {
        "file_name": profile.file_name,
        "n_rows": profile.n_rows,
        "n_cols": profile.n_cols,
        "columns": [{"name": c.name, "dtype": c.dtype} for c in profile.columns],
        "sample_rows": profile.sample_rows,
    }


def load_examples() -> dict[str, dict]:
    return json.loads((EXAMPLES_DIR / "examples.json").read_text(encoding="utf-8"))


def load_example_bytes(name: str) -> tuple[str, bytes] | None:
    """(file_name, data) for example `name`, or None if `name` is unknown."""
    info = load_examples().get(name)
    if info is None:
        return None
    file_name = info["file_name"]
    return file_name, (EXAMPLES_DIR / file_name).read_bytes()


class DatasetStore:
    """Validates and stores uploaded CSVs under `<data_dir>/uploads/`, with a TTL.

    Expiry is lazy (checked on access, swept opportunistically on new
    uploads) rather than a background sweep loop -- no idle polling, per
    this task's own rule against polling while waiting.
    """

    def __init__(
        self,
        data_dir: Path,
        *,
        ttl_s: int,
        max_upload_mb: float,
        max_rows: int,
        max_cols: int,
    ) -> None:
        self._uploads_dir = data_dir / "uploads"
        self._uploads_dir.mkdir(parents=True, exist_ok=True)
        self._ttl_s = ttl_s
        self.max_upload_mb = max_upload_mb
        self.max_rows = max_rows
        self.max_cols = max_cols
        self._records: dict[str, StoredDataset] = {}
        self._lock = threading.Lock()

    def _expired(self, record: StoredDataset, now: float) -> bool:
        return now - record.created_at > self._ttl_s

    def _forget(self, dataset_id: str, record: StoredDataset) -> None:
        self._records.pop(dataset_id, None)
        record.path.unlink(missing_ok=True)

    def validate_and_profile(self, file_name: str, data: bytes) -> DatasetProfile:
        """Raise DatasetError on a bad upload; otherwise return its profile."""
        if not file_name.lower().endswith(".csv"):
            raise DatasetError("file name must end with .csv")
        max_bytes = int(self.max_upload_mb * 1024 * 1024)
        if len(data) > max_bytes:
            raise DatasetError(
                f"upload is {len(data)} bytes, over the {self.max_upload_mb} MB limit"
            )
        try:
            profile = profile_csv(data, file_name)
        except Exception as exc:
            raise DatasetError(f"could not parse as a CSV file: {exc}") from exc
        if profile.n_rows > self.max_rows:
            raise DatasetError(f"{profile.n_rows} rows exceeds the {self.max_rows}-row limit")
        if profile.n_cols > self.max_cols:
            raise DatasetError(f"{profile.n_cols} columns exceeds the {self.max_cols}-column limit")
        return profile

    def store(self, file_name: str, data: bytes) -> str:
        """Store already-validated bytes; return a new dataset id."""
        now = time.time()
        with self._lock:
            expired = [id_ for id_, r in self._records.items() if self._expired(r, now)]
            for id_ in expired:
                self._forget(id_, self._records[id_])

            dataset_id = secrets.token_urlsafe(16)
            path = self._uploads_dir / f"{dataset_id}.csv"
            path.write_bytes(data)
            self._records[dataset_id] = StoredDataset(dataset_id, file_name, path, now)
        return dataset_id

    def get(self, dataset_id: str) -> StoredDataset | None:
        now = time.time()
        with self._lock:
            record = self._records.get(dataset_id)
            if record is None:
                return None
            if self._expired(record, now):
                self._forget(dataset_id, record)
                return None
            return record

    def read_bytes(self, record: StoredDataset) -> bytes:
        return record.path.read_bytes()
