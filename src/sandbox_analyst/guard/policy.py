"""Every allowlist/denylist the static checker uses, as plain data.

Changes to any of these sets are design decisions: log them in
DECISIONS.md (see D-010 for the ground rule — the import allowlist
grows only on false-positive evidence from real dev tasks).
"""

# Only these top-level packages (and their submodules) may be imported.
# Relative imports are always blocked, regardless of this list.
ALLOWED_IMPORT_ROOTS = frozenset(
    {
        "pandas",
        "numpy",
        "scipy",
        "sklearn",
        "statsmodels",
        "matplotlib",
        "seaborn",
        "math",
        "statistics",
        "re",
        "datetime",
        "json",
        "collections",
        "itertools",
    }
)

# Bare names that are never allowed to be referenced (called or merely
# aliased), because each one is a generic route to dynamic execution or
# reflection that would let code route around every other rule here.
#
# `exit`/`quit` were removed here after the P3 checker-block review (D-100):
# both only ever appeared as a plain early-return guard after an
# already-printed message (`exit()`/`exit(1)`), raising `SystemExit`, which
# `sandbox/runner.py` already treats as a normal end of script (D-028) --
# neither takes code to run nor exposes any introspection, so they don't
# belong in a "dynamic execution/reflection" denylist at all.
FORBIDDEN_CALL_NAMES = frozenset(
    {
        "eval",
        "exec",
        "compile",
        "__import__",
        "getattr",
        "setattr",
        "delattr",
        "globals",
        "locals",
        "vars",
        "breakpoint",
        "input",
        "help",
    }
)

# A dunder NAME (not attribute) exempted from DUNDER_ACCESS -- deliberately
# narrow (D-100): `__name__` alone is a read-only module-identity string
# with no reflection capability (it's not on the D-033 bypass chain, e.g.
# `.__class__.__bases__...`), and `if __name__ == "__main__":` is one of
# the most common idioms in real Python. `.__name__` as an ATTRIBUTE is
# NOT exempted -- no false positive was observed for that form, so widening
# the exemption to it would be an unjustified, un-narrow change.
ALLOWED_DUNDER_NAMES = frozenset({"__name__"})

# Names that are blocked anywhere they appear as a bare name or as any
# component of an attribute chain (e.g. `pd.io.common.os.system` is
# blocked because `os` and `system` both appear in the chain).
FORBIDDEN_ATTRIBUTE_NAMES = frozenset(
    {
        "os",
        "sys",
        "subprocess",
        "socket",
        "shutil",
        "ctypes",
        "ctypeslib",
        "builtins",
        "importlib",
        "system",
        "popen",
        "fork",
        "kill",
        "remove",
        "unlink",
        "rmtree",
        "execv",
        "execve",
        "spawn",
        "chmod",
        "chown",
        "pty",
        "fcntl",
        "mmap",
        "signal",
    }
)

# Method names that can write a file. Flagged unless called with no
# path/buffer argument at all, or with a literal path inside WORK_DIR.
WRITER_METHOD_NAMES = frozenset(
    {
        "to_csv",
        "to_excel",
        "to_json",
        "to_parquet",
        "to_pickle",
        "to_html",
        "to_feather",
        "to_hdf",
        "to_stata",
        "to_latex",
        "to_markdown",
        "savefig",
        "savetxt",
        "save",
        "tofile",
    }
)

# Keyword argument names, across the writer methods above, that carry
# the destination path/buffer.
PATH_KEYWORD_NAMES = frozenset(
    {
        "path",
        "path_or_buf",
        "fname",
        "file",
        "buf",
        "excel_writer",
        "filepath_or_buffer",
    }
)

# The only directory scripts may write into (see sandbox.base.WORKDIR;
# duplicated as a plain string here so the checker has no dependency on
# the sandbox package -- these are two independently-testable layers).
WORK_DIR = "/work"
