"""KSY9xx: diagnostics reported by the Kaitai Struct compiler (``--compile``)."""

from __future__ import annotations

import os

from ..linter import LintContext
from ..registry import rule

#: ksc warnings that a native rule already reports (KSY101).
_NATIVE = ("use canonical encoding name",)


def _report(ctx: LintContext, kind: str) -> None:
    result = ctx.external.get("ksc")
    if not result:
        return
    for item in result.get(kind, []):
        path = [str(p) for p in item.get("path", [])]
        node = ctx.doc.find_nearest(path)
        msg = item.get("message", "").strip()
        if kind == "warnings" and any(msg.startswith(p) for p in _NATIVE):
            continue  # covered by a native rule with autofix
        f = item.get("file")
        if f and ctx.filename and not _same_file(f, ctx.filename):
            if kind == "warnings":
                continue  # reported when the imported file itself is linted
            msg = f"in imported file {f}: {msg}"
            node = None
        ptr = "/" + "/".join(path) if path else ""
        if node is not None:
            ctx.report(msg, node, path=ptr)
        else:
            ctx.report(msg, line=0, col=0, path=ptr)


def _same_file(a: str, b: str) -> bool:
    try:
        return os.path.samefile(a, b)
    except OSError:
        return os.path.normpath(a) == os.path.normpath(b)


@rule(
    "KSY900",
    "ksc-error",
    "error",
    "Errors reported by kaitai-struct-compiler (only with `--compile`).",
    default_enabled=False,
)
def ksc_error(ctx: LintContext) -> None:
    _report(ctx, "errors")


@rule(
    "KSY901",
    "ksc-warning",
    "warning",
    "Warnings reported by kaitai-struct-compiler (only with `--compile`).",
    default_enabled=False,
)
def ksc_warning(ctx: LintContext) -> None:
    _report(ctx, "warnings")
