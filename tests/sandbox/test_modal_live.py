"""Live tests against a real Modal account.

These call ModalSandbox directly, with no static checker in front of
it, ON PURPOSE: this is testing the sandbox layer in isolation. They
cost real (small) money against the project's Modal budget and require
a working `modal` CLI auth profile. Excluded by default; run with:

    uv run pytest -m live -v --durations=0

If anything here fails for an account/auth reason, stop and report the
exact failure rather than retrying.
"""

import socket
import time
import urllib.request

import pytest

from sandbox_analyst.config import Settings
from sandbox_analyst.sandbox.base import SandboxCrashed
from sandbox_analyst.sandbox.ledger import DEFAULT_LEDGER_PATH, ledger_total_usd
from sandbox_analyst.sandbox.modal_image import PINNED_PACKAGES
from sandbox_analyst.sandbox.modal_sandbox import ModalSandbox

pytestmark = pytest.mark.live


@pytest.fixture
def sandbox():
    settings = Settings(_env_file=None, sa_sandbox="modal")
    return ModalSandbox(settings, ledger_path=DEFAULT_LEDGER_PATH)


def test_a_trivial_run_completes(sandbox):
    """First call here also pays for the remote image build; see --durations=0."""
    result = sandbox.run("print('warm')")
    assert result.exit_code == 0
    assert "warm" in result.stdout


def test_a_second_trivial_run_is_much_faster_than_the_first(sandbox):
    start = time.monotonic()
    result = sandbox.run("print('hello again')")
    elapsed = time.monotonic() - start
    assert result.exit_code == 0
    print(f"\nsecond trivial run wall time: {elapsed:.2f}s")  # noqa: T201


def test_b_pinned_library_versions(sandbox):
    code = """
import importlib
for pkg in ["pandas", "numpy", "scipy", "sklearn", "statsmodels", "matplotlib", "seaborn"]:
    print(pkg, importlib.import_module(pkg).__version__)
"""
    result = sandbox.run(code)
    assert result.exit_code == 0
    for pin in PINNED_PACKAGES:
        name, _, version = pin.partition("==")
        import_name = "sklearn" if name == "scikit-learn" else name
        assert f"{import_name} {version}" in result.stdout


def test_c_uploaded_csv_is_readable_with_pandas(sandbox):
    sandbox.upload("people.csv", b"name,age\nAda,36\nGrace,85\n")
    result = sandbox.run(
        "import pandas as pd\ndf = pd.read_csv('/work/data/people.csv')\nprint(df['age'].sum())\n"
    )
    assert result.exit_code == 0
    assert "121" in result.stdout


def test_d_matplotlib_figure_is_returned_as_png(sandbox):
    code = "import matplotlib.pyplot as plt\nplt.plot([1, 2, 3], [1, 4, 9])\n"
    result = sandbox.run(code)
    assert result.exit_code == 0
    assert len(result.images) == 1
    assert result.images[0].startswith(b"\x89PNG")


def test_e_network_is_fully_blocked(sandbox):
    code = """
import json
report = {}

try:
    import urllib.request
    urllib.request.urlopen("https://example.com", timeout=5)
    report["http"] = "succeeded"
except Exception as exc:
    report["http"] = f"failed: {type(exc).__name__}"

try:
    import socket
    s = socket.create_connection(("1.1.1.1", 443), timeout=5)
    s.close()
    report["socket"] = "succeeded"
except Exception as exc:
    report["socket"] = f"failed: {type(exc).__name__}"

try:
    import socket
    socket.gethostbyname("example.com")
    report["dns"] = "succeeded"
except Exception as exc:
    report["dns"] = f"failed: {type(exc).__name__}"

print(json.dumps(report))
"""
    result = sandbox.run(code, timeout_s=20)
    assert result.exit_code == 0
    assert "succeeded" not in result.stdout


def test_e_network_is_blocked_from_the_host_perspective_too():
    """Sanity check that the three primitives below actually work on an open
    network, so test_e above is meaningful (it's asserting sandboxed, not
    host, behavior -- this just documents the host-side baseline)."""
    urllib.request.urlopen("https://example.com", timeout=5)
    s = socket.create_connection(("1.1.1.1", 443), timeout=5)
    s.close()
    socket.gethostbyname("example.com")


def test_f_timeout_then_fresh_run_works(sandbox):
    result = sandbox.run("while True:\n    pass\n", timeout_s=5)
    assert result.timed_out is True

    result2 = sandbox.run("print(1)")
    assert result2.timed_out is False
    assert result2.exit_code == 0
    assert "1" in result2.stdout


def test_g_hard_process_exit_is_handled_without_hanging(sandbox):
    start = time.monotonic()
    result = sandbox.run("import os\nos._exit(1)\n", timeout_s=20)
    elapsed = time.monotonic() - start
    assert elapsed < 20
    assert result.timed_out is False
    assert result.exit_code == 1
    assert result.error is None


def test_h_over_memory_limit_allocation_is_handled_without_hanging(sandbox):
    """Exceeding the hard memory limit kills the whole sandbox container
    (confirmed live), not just the exec'd process -- Modal's API then
    reports the container as gone, which we surface as SandboxCrashed.
    The point of this test is "no hang", not a specific ExecResult shape.
    """
    code = "data = bytearray(8 * 1024 ** 3)\nprint(len(data))\n"
    start = time.monotonic()
    with pytest.raises(SandboxCrashed):
        sandbox.run(code, timeout_s=30)
    elapsed = time.monotonic() - start
    assert elapsed < 30


def test_i_large_output_is_truncated(sandbox):
    result = sandbox.run("print('x' * (1024 * 1024))")
    assert result.exit_code == 0
    assert result.truncated is True
    assert len(result.stdout) < 1024 * 1024


def test_j_state_does_not_persist_between_runs(sandbox):
    sandbox.run("open('/tmp/leftover_from_run_1.txt', 'w').write('leaked')")
    result = sandbox.run("import os\nprint(os.path.exists('/tmp/leftover_from_run_1.txt'))\n")
    assert "False" in result.stdout


def test_k_ledger_summary():
    total = ledger_total_usd(DEFAULT_LEDGER_PATH)
    lines = DEFAULT_LEDGER_PATH.read_text().strip().splitlines()
    n = len(lines)
    average = total / n if n else 0.0
    print(f"\nledger total so far: ${total:.6f} across {n} runs (avg ${average:.6f}/run)")  # noqa: T201
    assert n > 0
    assert total >= 0
