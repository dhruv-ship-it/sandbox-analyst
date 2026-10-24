"""Known static-checker bypasses, found by red-teaming `check()` directly
(static checker disabled from the sandbox's perspective: these snippets
would still be stopped by gVisor isolation and `block_network=True`, but
the checker alone does not catch them).

Each is `xfail(strict=True)`: if one of these starts failing (i.e. the
checker starts blocking it), the xfail is stale and should be removed
along with its entry in docs/security.md. Do not delete a case here
just because it would be hard to explain -- see docs/security.md for
why each one isn't worth closing at the AST layer.
"""

import pytest

from sandbox_analyst.guard import check


@pytest.mark.xfail(
    strict=True,
    reason="format-string attribute traversal: '__class__' etc. live inside a "
    "str literal's *content*, interpreted by str.format()'s mini-language at "
    "runtime, never appearing as a real ast.Attribute node. See docs/security.md.",
)
def test_known_bypass_1_format_string_attribute_traversal():
    code = "'{0.__class__.__bases__[0].__subclasses__()}'.format(object())\n"
    result = check(code)
    assert not result.ok, "this bypass has apparently been closed -- update docs/security.md"


@pytest.mark.xfail(
    strict=True,
    reason="aliasing the `open` builtin to another name routes around the "
    "open()-specific write-path check, which matches on the literal name "
    "`open`. See docs/security.md.",
)
def test_known_bypass_2_open_builtin_aliasing():
    code = "o = open\no('/etc/passwd', 'w')\n"
    result = check(code)
    assert not result.ok, "this bypass has apparently been closed -- update docs/security.md"
