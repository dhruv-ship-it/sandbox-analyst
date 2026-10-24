import pytest

from sandbox_analyst.config import Settings
from sandbox_analyst.sandbox.factory import make_sandbox
from sandbox_analyst.sandbox.fake import FakeSandbox


def test_make_sandbox_fake_returns_fake_sandbox():
    settings = Settings(_env_file=None, sa_sandbox="fake")
    sandbox = make_sandbox(settings)
    assert isinstance(sandbox, FakeSandbox)
    assert sandbox.backend == "fake"


def test_make_sandbox_fake_uses_configured_upload_limit():
    settings = Settings(_env_file=None, sa_sandbox="fake", max_upload_mb=1)
    sandbox = make_sandbox(settings)
    too_big = b"x" * (2 * 1024 * 1024)
    with pytest.raises(ValueError):
        sandbox.upload("big.csv", too_big)


def test_make_sandbox_rejects_unknown_backend():
    settings = Settings(_env_file=None, sa_sandbox="fake")
    settings.sa_sandbox = "nonsense"  # bypass the Literal type for this check
    with pytest.raises(ValueError, match="unknown sandbox backend"):
        make_sandbox(settings)
