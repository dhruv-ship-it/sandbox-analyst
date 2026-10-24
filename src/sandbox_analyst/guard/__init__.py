"""The static checker: AST-only, defense in depth, never executes anything."""

from .checker import CheckResult, Violation, check

__all__ = ["CheckResult", "Violation", "check"]
