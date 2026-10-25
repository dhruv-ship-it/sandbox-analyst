"""Malicious snippets must be blocked with the expected rule_id."""

import pytest

from sandbox_analyst.guard import check

# (name, code, expected_rule_id). Checking "expected rule_id is among the
# violations" rather than an exact violation list, since several rules
# deliberately overlap for defense in depth (e.g. `__import__` is both a
# FORBIDDEN_CALL and a DUNDER_ACCESS).
MALICIOUS_CASES: list[tuple[str, str, str]] = [
    ("import_os", "import os\n", "IMPORT_NOT_ALLOWED"),
    ("from_os_import_system", "from os import system\n", "IMPORT_NOT_ALLOWED"),
    ("dunder_import_call", "__import__('os')\n", "FORBIDDEN_CALL"),
    ("eval_call", "eval('1 + 1')\n", "FORBIDDEN_CALL"),
    ("exec_call", "exec('pass')\n", "FORBIDDEN_CALL"),
    ("compile_call", "compile('pass', '<s>', 'exec')\n", "FORBIDDEN_CALL"),
    ("open_write_etc", "open('/etc/x', 'w')\n", "UNSAFE_WRITE"),
    ("open_write_parent_traversal", "open('../x', 'w')\n", "UNSAFE_WRITE"),
    (
        "attribute_chain_os_system",
        "import pandas as pd\npd.io.common.os.system('ls')\n",
        "FORBIDDEN_ATTRIBUTE",
    ),
    (
        "class_bases_subclasses",
        "().__class__.__bases__[0].__subclasses__()\n",
        "DUNDER_ACCESS",
    ),
    ("getattr_call", "import pandas as pd\ngetattr(pd, 'io')\n", "FORBIDDEN_CALL"),
    ("globals_builtins_lookup", "globals()['__builtins__']\n", "FORBIDDEN_CALL"),
    (
        "to_csv_outside_work",
        "import pandas as pd\npd.DataFrame().to_csv('/tmp/x.csv')\n",
        "UNSAFE_WRITE",
    ),
    (
        "savefig_outside_work",
        "import matplotlib.pyplot as plt\nplt.savefig('/etc/x.png')\n",
        "UNSAFE_WRITE",
    ),
    ("read_pickle", "import pandas as pd\npd.read_pickle('x.pkl')\n", "PICKLE"),
    (
        "numpy_load_allow_pickle",
        "import numpy as np\nnp.load('x.npy', allow_pickle=True)\n",
        "PICKLE",
    ),
    ("bare_importlib_reference", "importlib\n", "FORBIDDEN_ATTRIBUTE"),
    ("sys_modules", "sys.modules\n", "FORBIDDEN_ATTRIBUTE"),
    ("bare_socket_reference", "socket.socket()\n", "FORBIDDEN_ATTRIBUTE"),
    ("subprocess_run", "subprocess.run(['ls'])\n", "FORBIDDEN_ATTRIBUTE"),
    ("ctypes_cdll", "ctypes.CDLL('libc.so.6')\n", "FORBIDDEN_ATTRIBUTE"),
    ("builtins_eval_attr", "builtins.eval('1')\n", "FORBIDDEN_ATTRIBUTE"),
    (
        "lambda_trick_dunder_import",
        "(lambda: __import__('os'))()\n",
        "FORBIDDEN_CALL",
    ),
    ("setattr_call", "import pandas as pd\nsetattr(pd, 'x', 1)\n", "FORBIDDEN_CALL"),
    ("delattr_call", "import pandas as pd\ndelattr(pd, 'x')\n", "FORBIDDEN_CALL"),
    ("vars_call", "vars()\n", "FORBIDDEN_CALL"),
    ("locals_call", "locals()\n", "FORBIDDEN_CALL"),
    ("breakpoint_call", "breakpoint()\n", "FORBIDDEN_CALL"),
    ("input_call", "input()\n", "FORBIDDEN_CALL"),
    ("help_call", "help()\n", "FORBIDDEN_CALL"),
    ("relative_import_dot", "from . import sibling\n", "IMPORT_NOT_ALLOWED"),
    ("relative_import_dotted", "from .sibling import thing\n", "IMPORT_NOT_ALLOWED"),
    ("import_xml_not_allowed", "import xml.etree.ElementTree\n", "IMPORT_NOT_ALLOWED"),
    ("shutil_rmtree", "shutil.rmtree('/')\n", "FORBIDDEN_ATTRIBUTE"),
    ("os_popen_bare", "os.popen('ls')\n", "FORBIDDEN_ATTRIBUTE"),
    (
        "numpy_save_outside_work",
        "import numpy as np\nnp.save('/etc/evil.npy', [1, 2, 3])\n",
        "UNSAFE_WRITE",
    ),
    (
        "to_pickle_outside_work",
        "import pandas as pd\npd.DataFrame().to_pickle('/tmp/x.pkl')\n",
        "UNSAFE_WRITE",
    ),
    (
        "open_write_work_with_traversal",
        "open('/work/../etc/passwd', 'w')\n",
        "UNSAFE_WRITE",
    ),
    ("dunder_globals_attr", "f.__globals__\n", "DUNDER_ACCESS"),
    ("dunder_code_attr", "f.__code__\n", "DUNDER_ACCESS"),
    ("dunder_mro_attr", "type(1).__mro__\n", "DUNDER_ACCESS"),
    # The `__name__` exemption (D-100) is narrow: only the bare NAME form
    # (`if __name__ == "__main__":`) is allowed. `.__name__` as an
    # ATTRIBUTE on some other object stays blocked -- no false positive
    # was observed for that form, so the exemption doesn't cover it.
    ("dunder_name_attr", "some_func.__name__\n", "DUNDER_ACCESS"),
    ("bare_dunder_class_name", "__class__\n", "DUNDER_ACCESS"),
    ("syntax_error", "def f(:\n", "SYNTAX"),
]


@pytest.mark.parametrize(
    "name,code,expected_rule_id", MALICIOUS_CASES, ids=[c[0] for c in MALICIOUS_CASES]
)
def test_malicious_code_is_blocked(name, code, expected_rule_id):
    result = check(code)
    assert not result.ok, f"{name} unexpectedly passed"
    rule_ids = [v.rule_id for v in result.violations]
    assert expected_rule_id in rule_ids, f"{name}: expected {expected_rule_id}, got {rule_ids}"


def test_at_least_30_malicious_cases():
    assert len(MALICIOUS_CASES) >= 30
