"""Request body models. Response bodies are plain dicts (see api/runs.py, api/datasets.py)."""

from pydantic import BaseModel, Field


class RunCreateRequest(BaseModel):
    dataset_id: str
    question: str = Field(min_length=3, max_length=500)
