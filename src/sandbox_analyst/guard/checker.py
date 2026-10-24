"""An AST-only static checker for model-written analysis scripts.

This never executes, compiles-to-run, or imports the code it checks --
only `ast.parse` touches it. It is defense in depth and fast repair
feedback for the agent, NOT the security boundary; the sandbox (no
network, gVisor-isolated) is what actually makes running this code
safe. See docs/security.md.
"""

import ast
from dataclasses import dataclass

from . import policy


@dataclass(frozen=True)
class Violation:
    rule_id: str
    line: int
    col: int
    message: str


@dataclass(frozen=True)
class CheckResult:
    ok: bool
    violations: list[Violation]


def check(code: str) -> CheckResult:
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return CheckResult(
            ok=False,
            violations=[
                Violation(
                    rule_id="SYNTAX",
                    line=exc.lineno or 1,
                    col=(exc.offset or 1) - 1,
                    message=f"syntax error: {exc.msg}. Fix the Python syntax and resubmit.",
                )
            ],
        )
    except ValueError as exc:
        return CheckResult(
            ok=False,
            violations=[Violation(rule_id="SYNTAX", line=1, col=0, message=f"syntax error: {exc}")],
        )

    violations: list[Violation] = []
    for node in ast.walk(tree):
        violations.extend(_check_import(node))
        violations.extend(_check_forbidden_call(node))
        violations.extend(_check_dunder(node))
        violations.extend(_check_forbidden_attribute(node))
        violations.extend(_check_unsafe_write(node))
        violations.extend(_check_pickle(node))

    return CheckResult(ok=not violations, violations=violations)


def _is_dunder(name: str) -> bool:
    return name.startswith("__") and name.endswith("__") and len(name) > 4


def _is_literal_str(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _is_safe_work_path(path: str) -> bool:
    normalized = path.replace("\\", "/")
    if ".." in normalized.split("/"):
        return False
    if normalized.startswith("/"):
        return normalized == policy.WORK_DIR or normalized.startswith(policy.WORK_DIR + "/")
    return True


def _kwarg(node: ast.Call, name: str) -> ast.AST | None:
    for kw in node.keywords:
        if kw.arg == name:
            return kw.value
    return None


def _kwarg_any(node: ast.Call, names: frozenset[str]) -> ast.AST | None:
    for kw in node.keywords:
        if kw.arg in names:
            return kw.value
    return None


def _check_import(node: ast.AST) -> list[Violation]:
    if isinstance(node, ast.Import):
        violations = []
        for alias in node.names:
            root = alias.name.split(".")[0]
            if root not in policy.ALLOWED_IMPORT_ROOTS:
                violations.append(
                    Violation(
                        "IMPORT_NOT_ALLOWED",
                        node.lineno,
                        node.col_offset,
                        f"import of `{alias.name}` is blocked; allowed top-level packages are "
                        f"{sorted(policy.ALLOWED_IMPORT_ROOTS)}.",
                    )
                )
        return violations

    if isinstance(node, ast.ImportFrom):
        if node.level > 0:
            return [
                Violation(
                    "IMPORT_NOT_ALLOWED",
                    node.lineno,
                    node.col_offset,
                    "relative imports are blocked; import the top-level package directly.",
                )
            ]
        root = (node.module or "").split(".")[0]
        if root not in policy.ALLOWED_IMPORT_ROOTS:
            return [
                Violation(
                    "IMPORT_NOT_ALLOWED",
                    node.lineno,
                    node.col_offset,
                    f"import from `{node.module}` is blocked; allowed top-level packages are "
                    f"{sorted(policy.ALLOWED_IMPORT_ROOTS)}.",
                )
            ]
    return []


def _check_forbidden_call(node: ast.AST) -> list[Violation]:
    if (
        isinstance(node, ast.Name)
        and isinstance(node.ctx, ast.Load)
        and node.id in policy.FORBIDDEN_CALL_NAMES
    ):
        return [
            Violation(
                "FORBIDDEN_CALL",
                node.lineno,
                node.col_offset,
                f"`{node.id}` is blocked (dynamic execution/reflection). "
                "Use plain pandas/numpy/stdlib operations instead.",
            )
        ]
    return []


def _check_dunder(node: ast.AST) -> list[Violation]:
    if isinstance(node, ast.Name) and _is_dunder(node.id):
        return [
            Violation(
                "DUNDER_ACCESS",
                node.lineno,
                node.col_offset,
                f"`{node.id}` is a dunder name and is blocked. "
                "Use normal attributes and methods instead of introspection.",
            )
        ]
    if isinstance(node, ast.Attribute) and _is_dunder(node.attr):
        return [
            Violation(
                "DUNDER_ACCESS",
                node.lineno,
                node.col_offset,
                f"`.{node.attr}` is a dunder attribute and is blocked. "
                "Use normal attributes and methods instead of introspection.",
            )
        ]
    return []


def _check_forbidden_attribute(node: ast.AST) -> list[Violation]:
    if isinstance(node, ast.Name) and node.id in policy.FORBIDDEN_ATTRIBUTE_NAMES:
        return [
            Violation(
                "FORBIDDEN_ATTRIBUTE",
                node.lineno,
                node.col_offset,
                f"`{node.id}` is blocked. Scripts may only read and analyze data: "
                "no OS, process, or network access.",
            )
        ]
    if isinstance(node, ast.Attribute) and node.attr in policy.FORBIDDEN_ATTRIBUTE_NAMES:
        return [
            Violation(
                "FORBIDDEN_ATTRIBUTE",
                node.lineno,
                node.col_offset,
                f"`.{node.attr}` is blocked. Scripts may only read and analyze data: "
                "no OS, process, or network access.",
            )
        ]
    return []


def _check_unsafe_write(node: ast.AST) -> list[Violation]:
    if not isinstance(node, ast.Call):
        return []
    func = node.func

    if isinstance(func, ast.Name) and func.id == "open":
        mode_node = node.args[1] if len(node.args) > 1 else _kwarg(node, "mode")
        if mode_node is None:
            return []  # default mode "r" is always safe
        mode = _is_literal_str(mode_node)
        if mode is None:
            return [
                Violation(
                    "UNSAFE_WRITE",
                    node.lineno,
                    node.col_offset,
                    "open() with a non-literal mode can't be verified as read-only; "
                    "use a literal mode string.",
                )
            ]
        if not any(c in mode for c in "wax+"):
            return []  # a literal read-only mode
        path_node = node.args[0] if node.args else _kwarg(node, "file")
        path = _is_literal_str(path_node) if path_node is not None else None
        if path is not None and _is_safe_work_path(path):
            return []
        return [
            Violation(
                "UNSAFE_WRITE",
                node.lineno,
                node.col_offset,
                f"open() in mode {mode!r} must use a literal path inside {policy.WORK_DIR} "
                "(relative without '..', or absolute under it).",
            )
        ]

    if isinstance(func, ast.Attribute) and func.attr in policy.WRITER_METHOD_NAMES:
        path_node = node.args[0] if node.args else _kwarg_any(node, policy.PATH_KEYWORD_NAMES)
        if path_node is None:
            return []  # called with no path/buffer: safe
        path = _is_literal_str(path_node)
        if path is not None and _is_safe_work_path(path):
            return []
        return [
            Violation(
                "UNSAFE_WRITE",
                node.lineno,
                node.col_offset,
                f"`.{func.attr}(...)` must write to a literal path inside {policy.WORK_DIR}, "
                "or be called with no path at all.",
            )
        ]

    return []


def _check_pickle(node: ast.AST) -> list[Violation]:
    if not isinstance(node, ast.Call):
        return []
    func = node.func
    name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)

    if name == "read_pickle":
        return [
            Violation(
                "PICKLE",
                node.lineno,
                node.col_offset,
                "`read_pickle` deserializes arbitrary objects and is blocked; "
                "use a non-pickle format (csv/json/parquet).",
            )
        ]

    allow_pickle = _kwarg(node, "allow_pickle")
    if allow_pickle is not None:
        if isinstance(allow_pickle, ast.Constant) and allow_pickle.value is True:
            return [
                Violation(
                    "PICKLE",
                    node.lineno,
                    node.col_offset,
                    "`allow_pickle=True` enables arbitrary deserialization and is blocked; "
                    "load without it.",
                )
            ]
        if not isinstance(allow_pickle, ast.Constant):
            return [
                Violation(
                    "PICKLE",
                    node.lineno,
                    node.col_offset,
                    "`allow_pickle=<non-literal>` can't be verified as False; "
                    "use a literal `allow_pickle=False` or omit it.",
                )
            ]
    return []
