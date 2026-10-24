"""Construct a Sandbox backend from configuration."""

from typing import TYPE_CHECKING

from .base import Sandbox
from .fake import FakeSandbox

if TYPE_CHECKING:
    from sandbox_analyst.config import Settings


def make_sandbox(settings: "Settings") -> Sandbox:
    """Build the sandbox backend selected by `settings.sa_sandbox`.

    "fake" returns an empty-script FakeSandbox, useful for wiring and
    tests that don't need specific scripted results (tests that do
    should construct FakeSandbox directly). "modal" builds the real
    Modal-backed sandbox.
    """
    if settings.sa_sandbox == "fake":
        return FakeSandbox(max_upload_mb=settings.max_upload_mb)
    if settings.sa_sandbox == "modal":
        from .modal_sandbox import ModalSandbox

        return ModalSandbox(settings)
    raise ValueError(f"unknown sandbox backend: {settings.sa_sandbox!r}")
