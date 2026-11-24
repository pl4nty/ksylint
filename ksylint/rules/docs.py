"""KSY4xx: documentation strings and references."""

from __future__ import annotations

import re
from collections.abc import Iterator
from urllib.parse import urlsplit

import yaml

from .. import specs
from ..linter import LintContext
from ..registry import rule
from ..yamldoc import Node, Pos, indent

DOC_KINDS = (specs.TYPE, specs.ATTR, specs.INSTANCE, specs.PARAM, specs.ENUM_VALUE)
_INDICATORS = set("-?:,[]{}#&*!|>'\"%@`")


def iter_docs(ctx: LintContext, key: str = "doc") -> Iterator[tuple[specs.Spec, Node]]:
    for spec in specs.iter_specs(ctx.root):
        if spec.kind in DOC_KINDS:
            n = spec.node.get(key)
            if n is not None:
                yield spec, n


def plain_ok(s: str) -> bool:
    """Can ``s`` be written as a plain (unquoted) single-line scalar?"""
    if not s or s != s.strip() or "\n" in s or "\t" in s:
        return False
    if s[0] in _INDICATORS:
        return False
    if ": " in s or " #" in s or s.endswith(":"):
        return False
    try:
        return yaml.safe_load(s) == s
    except yaml.YAMLError:
        return False


def _is_multiline_content(n: Node) -> bool:
    return isinstance(n.value, str) and "\n" in n.value.rstrip("\n")


@rule(
    "KSY400",
    "doc-single-line",
    "warning",
    "Single-line docs should be plain unquoted scalars.",
    anchor="doc",
)
def doc_single_line(ctx: LintContext) -> None:
    for _spec, n in iter_docs(ctx):
        if not n.is_str or _is_multiline_content(n):
            continue
        if n.style == "|":
            if plain_ok(n.value.strip()):
                ctx.report("single-line doc should be a plain scalar, not a `|` block", n)
        elif n.style in ("'", '"') and n.start.line == ctx.doc.last_line(n) and plain_ok(n.value):
            ctx.report("single-line doc should not be quoted", n)


@rule(
    "KSY401",
    "doc-multi-line",
    "warning",
    "Multi-line docs should use the literal block style (`doc: |`).",
    anchor="doc",
)
def doc_multi_line(ctx: LintContext) -> None:
    for _spec, n in iter_docs(ctx):
        if not n.is_str or n.style == "|":
            continue
        if n.style == ">":
            ctx.report(
                "use a literal block (`|`) instead of a folded block (`>`) for multi-line docs", n
            )
        elif _is_multiline_content(n) or n.start.line != ctx.doc.last_line(n):
            ctx.report("multi-line doc should use a literal block scalar (`doc: |`)", n)


@rule(
    "KSY402",
    "doc-line-length",
    "warning",
    "Wrap doc lines at 80 columns.",
    anchor="doc",
    options={"max-length": 80},
)
def doc_line_length(ctx: LintContext) -> None:
    limit = int(ctx.options.get("max-length", 80))
    for _spec, n in iter_docs(ctx):
        if not n.is_str:
            continue
        if n.style == "|":
            last = ctx.doc.last_line(n)
            content = ctx.lines[n.start.line + 1 : last + 1]
            nonblank = [ln for ln in content if ln.strip()]
            if not nonblank:
                continue
            ind = min(map(indent, nonblank))
            for off, ln in enumerate(content):
                text = ln[ind:]
                if len(text) > limit and _wrappable(text, limit):
                    ctx.report(
                        f"doc line is {len(text)} characters long (limit {limit})",
                        pos=Pos(n.start.line + 1 + off, ind + limit),
                        path=n.ptr,
                    )
                    break
        elif (
            n.start.line == ctx.doc.last_line(n)
            and len(n.value) > limit
            and _wrappable(n.value, limit)
        ):
            ctx.report(
                f"doc is {len(n.value)} characters long (limit {limit}); wrap it into a multi-line `|` block",
                n,
            )


def _wrappable(text: str, limit: int) -> bool:
    """A long line is only a problem if wrapping could fix it, i.e. it has
    no single unbreakable token (typically a URL) longer than the limit."""
    toks = text.split()
    return len(toks) > 1 and max(len(t) for t in toks) <= limit


def _url_targets(ctx: LintContext) -> Iterator[Node]:
    for _spec, n in iter_docs(ctx, "doc-ref"):
        if n.is_str:
            yield n
        elif n.is_seq:
            yield from (i for i in n.items if i.is_str)
    meta = ctx.root.get("meta")
    xref = meta.get("xref") if meta is not None and meta.is_map else None
    if xref is not None and xref.is_map:
        for _k, v in xref.items:
            if v.is_str:
                yield v
            elif v.is_seq:
                yield from (i for i in v.items if i.is_str)


_URLISH = re.compile(r"^(?:[A-Za-z][A-Za-z0-9+.-]*:/{1,}|www\.)")


def _first_url(n: Node) -> str | None:
    tok = n.value.strip().split(None, 1)
    if not tok:
        return None
    t = tok[0]
    return t if _URLISH.match(t) else None


@rule(
    "KSY403",
    "insecure-url",
    "warning",
    "Prefer `https://` URLs in doc-ref and xref.",
    anchor="doc-ref",
)
def insecure_url(ctx: LintContext) -> None:
    for n in _url_targets(ctx):
        u = _first_url(n)
        if u and u.lower().startswith("http://"):
            ctx.report(f"use https instead of http: `{u}`", n)


@rule(
    "KSY404",
    "malformed-url",
    "warning",
    "URLs in doc-ref and xref must be well-formed (`URL description`).",
    anchor="doc-ref",
)
def malformed_url(ctx: LintContext) -> None:
    for n in _url_targets(ctx):
        u = _first_url(n)
        if not u:
            v = n.value.strip()
            if re.match(r"^https?:\S", v) and not re.match(r"^https?://", v):
                ctx.report(f"malformed URL `{v.split()[0]}` (missing `//`?)", n)
            continue
        if u.lower().startswith("www."):
            ctx.report(f"URL `{u}` has no scheme; add `https://`", n)
            continue
        try:
            parts = urlsplit(u)
        except ValueError as e:
            ctx.report(f"malformed URL `{u}` ({e})", n)
            continue
        if (
            parts.scheme.lower() not in ("http", "https", "ftp")
            or not parts.netloc
            or "." not in parts.netloc
        ):
            ctx.report(f"malformed URL `{u}`", n)


def _norm_words(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


@rule(
    "KSY405",
    "trivial-doc",
    "info",
    "`doc` should not just repeat the attribute id.",
    anchor="seq-attr",
)
def trivial_doc(ctx: LintContext) -> None:
    for spec, n in iter_docs(ctx):
        if spec.kind not in (specs.ATTR, specs.PARAM) or not n.is_str:
            continue
        idn = spec.node.get("id")
        if idn is None or not idn.is_str:
            continue
        if _norm_words(n.value) and _norm_words(n.value) == _norm_words(idn.value):
            ctx.report(f"doc `{n.value.strip()}` only repeats the id; remove it or say more", n)


_PADDING_ID = re.compile(
    r"^(?:_?pad(?:ding)?|reserved|unused|rest|remainder|remaining|filler|garbage|slack)\d*$"
)


@rule(
    "KSY406",
    "trailing-padding",
    "info",
    "Do not read trailing padding just to consume the rest of a substream.",
    anchor="seq-attr",
)
def trailing_padding(ctx: LintContext) -> None:
    for spec in specs.iter_specs(ctx.root):
        if spec.kind != specs.TYPE or spec.top:
            continue
        seq = spec.node.get("seq")
        if seq is None or not seq.is_seq or not seq.items:
            continue
        last = seq.items[-1]
        if not last.is_map:
            continue
        idn = last.get("id")
        se = last.get("size-eos")
        if idn is None or not idn.is_str or se is None or se.value is not True:
            continue
        if any(
            last.get(k) is not None
            for k in ("type", "process", "contents", "valid", "repeat", "if")
        ):
            continue
        if _PADDING_ID.match(idn.value):
            ctx.report(
                f"trailing `{idn.value}` with `size-eos: true` is unnecessary; a sized substream "
                "does not need to be consumed fully",
                last,
            )
