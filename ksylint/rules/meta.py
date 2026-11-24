"""KSY2xx: the meta section."""

from __future__ import annotations

import functools
import os
import re
from typing import Optional

from ..linter import LintContext
from ..registry import rule
from ..specs import META, META_NESTED, META_NESTED_KEYS, iter_specs
from ..yamldoc import Node

HUMAN_KEYS = ("title", "application", "file-extension", "xref", "tags")
RESERVED_KEYS = ("ks-debug", "ks-opaque-types")


def _top_meta(ctx: LintContext) -> Optional[Node]:
    m = ctx.root.get("meta") if ctx.root is not None else None
    return m if m is not None and m.is_map else None


@rule("KSY200", "meta-id", "error", "The top-level type must have `meta/id`.", anchor="meta")
def meta_id(ctx: LintContext) -> None:
    if not ctx.root.is_map:
        return
    meta = _top_meta(ctx)
    if meta is None:
        ctx.report("missing top-level `meta` section with `id`", ctx.root)
    elif meta.get("id") is None:
        ctx.report("missing `meta/id`", meta)


@rule(
    "KSY201",
    "meta-id-filename",
    "error",
    "`meta/id` must match the file name (without `.ksy`).",
    anchor="meta",
)
def meta_id_filename(ctx: LintContext) -> None:
    fn = ctx.filename
    meta = _top_meta(ctx)
    if not fn or fn in ("-", "<stdin>") or meta is None:
        return
    idn = meta.get("id")
    if idn is None or not idn.is_str:
        return
    stem = os.path.basename(fn)
    if stem.endswith(".ksy"):
        stem = stem[:-4]
    if idn.value != stem:
        ctx.report(
            f"`meta/id` is `{idn.value}` but the file is named `{os.path.basename(fn)}`", idn
        )


@rule(
    "KSY202",
    "meta-human-info",
    "error",
    "Top-level meta must have at least one of title, application, file-extension, xref, tags.",
    anchor="meta",
)
def meta_human_info(ctx: LintContext) -> None:
    meta = _top_meta(ctx)
    if meta is None:
        return
    if not any(meta.get(k) is not None for k in HUMAN_KEYS):
        ctx.report("add human-readable meta information (at least `title`)", meta)


@rule(
    "KSY203",
    "license-missing",
    "warning",
    "Top-level meta should declare a `license`.",
    anchor="meta",
)
def license_missing(ctx: LintContext) -> None:
    meta = _top_meta(ctx)
    if meta is not None and meta.get("license") is None:
        ctx.report("missing `meta/license` (an SPDX license expression)", meta)


_LICENSE_REF = re.compile(r"(?:DocumentRef-[A-Za-z0-9.-]+:)?LicenseRef-[A-Za-z0-9.-]+")


@functools.lru_cache(maxsize=1)
def _licensing():
    from license_expression import get_spdx_licensing

    return get_spdx_licensing()


@functools.lru_cache(maxsize=256)
def check_spdx(expr: str) -> tuple[Optional[str], Optional[str]]:
    """Return (error, canonical) for an SPDX expression.

    ``error`` is None if valid. ``canonical`` is the normalised spelling if it
    differs from the input (e.g. deprecated ``GPL-2.0`` -> ``GPL-2.0-only``).
    """
    probe = _LICENSE_REF.sub("MIT", expr)  # license-expression does not know LicenseRef-*
    info = _licensing().validate(probe)
    if info.errors:
        bad = [s for s in info.invalid_symbols if s]
        if bad:
            return f"unknown SPDX license identifier(s): {', '.join(bad)}", None
        return f"invalid SPDX license expression ({'; '.join(info.errors)})", None
    if probe != expr:
        return None, None
    norm = info.normalized_expression

    def flat(s: str) -> str:
        return " ".join(s.replace("(", " ").replace(")", " ").split())

    if norm and flat(norm) != flat(expr):
        return None, norm
    return None, None


@rule(
    "KSY204",
    "license-spdx",
    "error",
    "`meta/license` must be a valid SPDX license expression.",
    anchor="meta",
)
def license_spdx(ctx: LintContext) -> None:
    meta = _top_meta(ctx)
    n = meta.get("license") if meta is not None else None
    if n is None:
        return
    if not n.is_str:
        ctx.report("`meta/license` must be a string (an SPDX license expression)", n)
        return
    err, _ = check_spdx(n.value.strip())
    if err:
        ctx.report(err, n)


@rule(
    "KSY205",
    "license-canonical",
    "warning",
    "Use the current, canonical SPDX identifier (e.g. `GPL-2.0-only`, not deprecated `GPL-2.0`).",
    anchor="meta",
)
def license_canonical(ctx: LintContext) -> None:
    meta = _top_meta(ctx)
    n = meta.get("license") if meta is not None else None
    if n is None or not n.is_str:
        return
    err, canon = check_spdx(n.value.strip())
    if not err and canon:
        ctx.report(f"use `{canon}` instead of `{n.value}`", n)


@rule(
    "KSY206",
    "file-extension-style",
    "error",
    "`file-extension`: a string if there is one, a block sequence if there are several.",
    anchor="meta",
)
def file_extension_style(ctx: LintContext) -> None:
    meta = _top_meta(ctx)
    n = meta.get("file-extension") if meta is not None else None
    if n is None:
        return
    if n.is_seq:
        if len(n.items) == 1:
            ctx.report("a single file extension must be a string, not a sequence", n)
        elif n.flow:
            ctx.report("multiple file extensions must be a block sequence, not `[ ... ]`", n)
        exts = [i.value for i in n.items if i.is_scalar]
        dups = {e for e in exts if exts.count(e) > 1}
        if dups:
            ctx.report(f"duplicate file extension(s): {', '.join(sorted(map(str, dups)))}", n)
        for i in n.items:
            if i.is_str and i.value.startswith("."):
                ctx.report("file extensions are given without the leading dot", i)
    elif n.is_str and n.value.startswith("."):
        ctx.report("file extensions are given without the leading dot", n)


@rule(
    "KSY207",
    "xref-order",
    "error",
    "Keys inside `meta/xref` must be in alphabetical order.",
    anchor="meta",
    fixable=True,
)
def xref_order(ctx: LintContext) -> None:
    meta = _top_meta(ctx)
    n = meta.get("xref") if meta is not None else None
    if n is None or not n.is_map:
        return
    keys = [str(k.value) for k, _ in n.items]
    for i in range(1, len(keys)):
        if keys[i] < keys[i - 1]:
            ctx.report(
                f"xref keys must be sorted: `{keys[i]}` should come before `{keys[i - 1]}`",
                n.items[i][0],
                path=n.ptr,
            )
            return


@rule(
    "KSY208",
    "tags-order",
    "error",
    "Values inside `meta/tags` must be in alphabetical order.",
    anchor="meta",
    fixable=True,
)
def tags_order(ctx: LintContext) -> None:
    meta = _top_meta(ctx)
    n = meta.get("tags") if meta is not None else None
    if n is None or not n.is_seq:
        return
    vals = [str(i.value) for i in n.items]
    for i in range(1, len(vals)):
        if vals[i] < vals[i - 1]:
            ctx.report(
                f"tags must be sorted: `{vals[i]}` should come before `{vals[i - 1]}`",
                n.items[i],
                path=n.ptr,
                fixable=not n.flow,
            )
            return


@rule(
    "KSY209",
    "nested-meta-keys",
    "error",
    "Nested (non-top-level) meta sections may only set encoding, endian and bit-endian.",
    anchor="meta",
)
def nested_meta_keys(ctx: LintContext) -> None:
    for spec in iter_specs(ctx.root):
        if spec.kind != META_NESTED:
            continue
        for k, _ in spec.node.items:
            key = k.value
            if isinstance(key, str) and (key.startswith("-") or key in META_NESTED_KEYS):
                continue
            if key in RESERVED_KEYS:
                continue  # KSY210
            ctx.report(f"`{k.raw}` must not be used in a nested meta section", k)


@rule(
    "KSY210",
    "reserved-keys",
    "error",
    "`ks-debug` and `ks-opaque-types` are reserved for internal use.",
    anchor="meta",
)
def reserved_keys(ctx: LintContext) -> None:
    for spec in iter_specs(ctx.root):
        if spec.kind not in (META, META_NESTED):
            continue
        for k, _ in spec.node.items:
            if k.value in RESERVED_KEYS:
                ctx.report(f"`{k.raw}` is reserved for internal use and must not be used", k)
