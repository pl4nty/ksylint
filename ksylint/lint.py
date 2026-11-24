"""Backwards-compatible entry points from ksylint < 1.0.

Prefer :func:`ksylint.lint_text` / :func:`ksylint.lint_file`.
"""

from __future__ import annotations

from .cli import main
from .linter import lint_file as _lint_file


def lint_file(filename: str) -> int:
    """Lint a file, print its diagnostics and return how many errors and
    warnings were found (0 means the file is clean)."""
    diags = [d for d in _lint_file(filename) if d.severity.value != "info"]
    for d in diags:
        print(d)
    return len(diags)


__all__ = ["lint_file", "main"]
