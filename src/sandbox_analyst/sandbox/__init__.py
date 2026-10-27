"""The Sandbox interface: types, FakeSandbox, and the backend factory."""

from .base import (
    OUTPUT_DIR,
    UPLOAD_DIR,
    WORKDIR,
    ExecError,
    ExecResult,
    Sandbox,
    SandboxCrashed,
    SandboxError,
    SandboxUnavailable,
    cap_exec_result,
    validate_upload_name,
    validate_upload_size,
)
from .factory import make_sandbox
from .fake import FakeSandbox
from .record import RecordingSandbox, ReplaySandbox, SandboxCassetteMiss

__all__ = [
    "WORKDIR",
    "UPLOAD_DIR",
    "OUTPUT_DIR",
    "ExecError",
    "ExecResult",
    "Sandbox",
    "SandboxError",
    "SandboxUnavailable",
    "SandboxCrashed",
    "cap_exec_result",
    "validate_upload_name",
    "validate_upload_size",
    "FakeSandbox",
    "make_sandbox",
    "RecordingSandbox",
    "ReplaySandbox",
    "SandboxCassetteMiss",
]
