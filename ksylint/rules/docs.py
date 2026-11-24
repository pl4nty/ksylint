"""KSY4xx: documentation strings and references.

The doc fixes (KSY400-KSY402) are planned here, next to the checks, so that
a diagnostic is reported as fixable exactly when ``--fix`` can fix it. They
are the only fixes that change the loaded data, each in one narrowly allowed
way that is verified before the fix is offered:

* KSY400 only drops the trailing newline of a one-line ``|`` doc;
* KSY401 turns folded line breaks into literal ones: folding the new text
  as YAML would must give back the old text;
* KSY402 only inserts line breaks: the text with all runs of whitespace
  collapsed, and its paragraphs (separated by blank lines), are unchanged.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlsplit

import yaml

from .. import specs
from ..config import Config
from ..linter import LintContext
from ..registry import get_rule, rule
from ..yamldoc import Node, Pos, YamlDocument, indent

DOC_KINDS = (specs.TYPE, specs.ATTR, specs.INSTANCE, specs.PARAM, specs.ENUM_VALUE)
_INDICATORS = set("-?:,[]{}#&*!|>'\"%@`")
DEFAULT_MAX_LENGTH = 80


def doc_nodes(root: Optional[Node], key: str = "doc") -> Iterator[tuple[specs.Spec, Node, Node]]:
    """(spec, key node, value node) for every ``doc`` (or ``key``) of a spec."""
    for spec in specs.iter_specs(root):
        if spec.kind in DOC_KINDS:
            k = spec.node.key_node(key)
            if k is not None and spec.node.get(key).style != "*":  # not an alias
                yield spec, k, spec.node.get(key)


def iter_docs(ctx: LintContext, key: str = "doc") -> Iterator[tuple[specs.Spec, Node]]:
    for spec, _k, n in doc_nodes(ctx.root, key):
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


def max_length(config: Config) -> int:
    return int(config.options_for(get_rule("KSY402")).get("max-length", DEFAULT_MAX_LENGTH))


def _is_multiline_content(n: Node) -> bool:
    return isinstance(n.value, str) and "\n" in n.value.rstrip("\n")


# ---------------------------------------------------------------------------
# fix planning


@dataclass(frozen=True)
class DocFix:
    """Replace ``text[start:end]`` with ``replacement``; the doc then loads
    as ``value``."""

    rule: str
    node: Node
    start: int
    end: int
    replacement: str
    value: str


_BLOCK_HEADER = re.compile(r"[|>][-+]?")


def _block_header(doc: YamlDocument, n: Node) -> Optional[str]:
    """The header (``|``, ``>-``, ...) of a block scalar, or ``None`` if it
    has an indentation indicator or a comment."""
    h = doc.lines[n.start.line][n.start.col :].rstrip()
    return h if _BLOCK_HEADER.fullmatch(h) else None


def _block_value(header: str, body: str) -> Optional[str]:
    """Load ``body`` (lines indented by at least one space) as a block
    scalar with ``header``."""
    try:
        v = yaml.safe_load(f"x: {header}\n{body}")
    except yaml.YAMLError:
        return None
    return v.get("x") if isinstance(v, dict) and isinstance(v.get("x"), str) else None


def _rest_of_line_blank(doc: YamlDocument, n: Node) -> bool:
    return doc.text[n.end.index : doc.line_end(n.end.line)].strip() == ""


def _block_parts(doc: YamlDocument, n: Node) -> Optional[tuple[str, int, int, list[str]]]:
    """(header, start and end offset of the content lines, content lines)
    of a ``|`` or ``>`` doc that the fixes can work on."""
    header = _block_header(doc, n)
    last = doc.last_line(n)
    if header is None or last <= n.start.line or doc.block_scalar_indent(n) is None:
        return None
    a, b = doc.line_start(n.start.line + 1), doc.line_end(last)
    if _block_value(header, doc.text[a : n.end.index]) != n.value:
        return None  # e.g. a tab or an odd line break: do not touch
    return header, a, b, doc.lines[n.start.line + 1 : last + 1]


def plan_single_line(doc: YamlDocument, n: Node, limit: int) -> Optional[DocFix]:
    """KSY400: a one-line doc in a ``|`` block or quotes -> plain scalar."""
    if not n.is_str:
        return None
    if n.style == "|":
        parts = _block_parts(doc, n)
        text = n.value.rstrip("\n")
        if parts is None or len(parts[3]) != 1 or n.value not in (text, text + "\n"):
            return None
        if not plain_ok(text) or _too_long(text, limit):
            return None
        return DocFix("KSY400", n, n.start.index, parts[2], text, text)
    if n.style in ("'", '"') and n.start.line == n.end.line and plain_ok(n.value):
        return DocFix("KSY400", n, n.start.index, n.end.index, n.value, n.value)
    return None


def plan_multi_line(doc: YamlDocument, key: Node, n: Node) -> Optional[DocFix]:
    """KSY401: a folded (``>``) or multi-line plain doc -> ``|`` literal."""
    if not n.is_str:
        return None
    if n.style == ">":
        parts = _block_parts(doc, n)
        if parts is None:
            return None
        header = "|" + parts[0][1:]
        value = _block_value(header, doc.text[parts[1] : n.end.index])
        if value is None:
            return None
        return DocFix("KSY401", n, n.start.index, n.start.index + 1, "|", value)
    if n.style is None and n.end.line > n.start.line and _rest_of_line_blank(doc, n):
        src = doc.text[n.start.index : n.end.index].split("\n")
        lines = [src[0].rstrip(), *(ln.strip() for ln in src[1:])]
        ind = " " * (key.start.col + 2)
        body = "".join(f"{ind}{ln}\n" if ln else "\n" for ln in lines)
        value = _block_value("|", body)
        # The literal text must fold back to the old one.
        if value is None or _block_value(">-", body) != n.value:
            return None
        end = doc.line_end(n.end.line)  # drop trailing blanks: they would become content
        return DocFix("KSY401", n, n.start.index, end, "|\n" + body.rstrip("\n"), value)
    return None


_LIST_ITEM = re.compile(r" *(?:[-*+]|\d{1,3}[.)]) +(?=\S)")
_FENCE = re.compile(r" *(?:```|~~~)")
#: Lines (stripped) that are structure, not prose: headings, tables, rules,
#: block quotes, directives.
_STRUCTURAL = re.compile(r"[#|>=]|\+[-=]|\.\. |[-=_*]{3,}\s*$")
#: Tokens that must not start a wrapped line: they would turn it into a list
#: item, heading, table row, block quote or code fence.
_NO_LINE_START = re.compile(r"(?:[-*+]|\d{1,3}[.)])$|[#|>=]|```|~~~")


def _too_long(text: str, limit: int) -> bool:
    """Longer than ``limit``, and wrapping could fix it: no single
    unbreakable token (typically a URL) is longer than the limit."""
    toks = text.split()
    return len(text.rstrip()) > limit and len(toks) > 1 and max(map(len, toks)) <= limit


def _wrap(line: str, limit: int, cont: int) -> Optional[list[str]]:
    """Break a prose line at spaces into lines of at most ``limit``
    characters; continuation lines are indented by ``cont``."""
    lead = indent(line)
    body = line[lead:].rstrip(" ")
    trailing = line[lead + len(body) :]
    if "   " in body or body.count(" | ") > 1:
        return None  # aligned columns or a table
    words = re.split(r"( +)", body)
    out: list[str] = []
    # The current line: its words, each with the separator before it.
    cur: list[tuple[str, str]] = [(line[:lead], words[0])]
    for sep, word in zip(words[1::2], words[2::2], strict=True):
        cur.append((sep, word))
        if sum(len(s) + len(w) for s, w in cur) <= limit:
            continue
        # Break before the last word that may start a line.
        for i in range(len(cur) - 1, 0, -1):
            if not _NO_LINE_START.match(cur[i][1]):
                out.append("".join(s + w for s, w in cur[:i]))
                cur = [(" " * cont, cur[i][1]), *cur[i + 1 :]]
                break
    out.append("".join(s + w for s, w in cur) + trailing)
    if len(out) < 2 or any(len(ln.rstrip(" ")) > limit for ln in out):
        return None
    return out


def wrap_plan(lines: list[str], limit: int) -> list[Optional[list[str]]]:
    """For each line of a literal doc (relative to its indentation), the
    lines to replace it with, or ``None`` to leave it alone.

    Only overlong prose lines are wrapped: paragraph text, and list items
    and their continuation lines (with a hanging indent). Code (fenced or
    indented), tables, headings and other structure are left alone.
    """
    out: list[Optional[list[str]]] = []
    fence = False
    hang: Optional[int] = None  # hanging indent of the current list item
    for ln in lines:
        new = None
        cont: Optional[int] = None
        if not ln.strip():
            hang = None
        elif _FENCE.match(ln):
            fence, hang = not fence, None
        elif not fence and "\t" not in ln:
            m = _LIST_ITEM.match(ln)
            if m:
                hang = cont = len(m.group(0))
            elif indent(ln) == 0:
                hang = None
                cont = None if _STRUCTURAL.match(ln) else 0
            elif indent(ln) == hang and not _STRUCTURAL.match(ln.lstrip()):
                cont = hang
            else:
                hang = None  # indented code or other preformatted text
        if cont is not None and _too_long(ln, limit):
            new = _wrap(ln, limit, cont)
        out.append(new)
    return out


def _collapse(s: str) -> str:
    return " ".join(s.split())


def same_prose(old: str, new: str) -> bool:
    """Same words, and the same paragraphs, possibly broken differently."""
    paras = [list(map(_collapse, re.split(r"\n[ \t]*\n", s.strip()))) for s in (old, new)]
    return paras[0] == paras[1]


def plan_line_length(doc: YamlDocument, key: Node, n: Node, limit: int) -> Optional[DocFix]:
    """KSY402: wrap the overlong prose lines of a doc (making a single-line
    doc a ``|`` block)."""
    if not n.is_str:
        return None
    if n.style == "|":
        parts = _block_parts(doc, n)
        if parts is None:
            return None
        header, a, b, lines = parts
        ind = doc.block_scalar_indent(n) or 0
        plan = wrap_plan([ln[ind:] for ln in lines], limit)
        if not any(plan):
            return None
        new_lines = []
        for ln, new in zip(lines, plan, strict=True):
            new_lines.extend([ln] if new is None else [" " * ind + w for w in new])
        content = "\n".join(new_lines)
        value = _block_value(header, content + doc.text[b : n.end.index])
        if value is None or not same_prose(n.value, value):
            return None
        return DocFix("KSY402", n, a, b, content, value)
    if n.start.line != n.end.line or "\n" in n.value or not _rest_of_line_blank(doc, n):
        return None
    if n.value != n.value.strip() or not _too_long(n.value, limit):
        return None
    wrapped = wrap_plan([n.value], limit)[0]
    if wrapped is None:
        return None
    ind = " " * (key.start.col + 2)
    body = "".join(f"{ind}{w}\n" for w in wrapped)
    value = _block_value("|", body)
    if value is None or not same_prose(n.value, value):
        return None
    end = doc.line_end(n.end.line)  # drop trailing blanks: they would become content
    return DocFix("KSY402", n, n.start.index, end, "|\n" + body.rstrip("\n"), value)


def doc_fixes(doc: YamlDocument, active: set[str], limit: int) -> list[DocFix]:
    """At most one fix per doc: the first of KSY400, KSY401, KSY402 that
    applies (fixing it may enable the next one)."""
    out = []
    for _spec, key, n in doc_nodes(doc.root):
        fix = None
        if "KSY400" in active:
            fix = plan_single_line(doc, n, limit)
        if fix is None and "KSY401" in active:
            fix = plan_multi_line(doc, key, n)
        if fix is None and "KSY402" in active:
            fix = plan_line_length(doc, key, n, limit)
        if fix is not None:
            out.append(fix)
    return out


# ---------------------------------------------------------------------------
# checks


@rule(
    "KSY400",
    "doc-single-line",
    "warning",
    "Single-line docs should be plain unquoted scalars.",
    anchor="doc",
    fixable=True,
)
def doc_single_line(ctx: LintContext) -> None:
    limit = max_length(ctx.config)
    for _spec, n in iter_docs(ctx):
        if not n.is_str or _is_multiline_content(n):
            continue
        fixable = plan_single_line(ctx.doc, n, limit) is not None
        if n.style == "|":
            text = n.value.strip()
            # A line that is too long is wrapped instead (KSY402).
            if plain_ok(text) and not _too_long(text, limit):
                ctx.report(
                    "single-line doc should be a plain scalar, not a `|` block", n, fixable=fixable
                )
        elif n.style in ("'", '"') and n.start.line == ctx.doc.last_line(n) and plain_ok(n.value):
            ctx.report("single-line doc should not be quoted", n, fixable=fixable)


@rule(
    "KSY401",
    "doc-multi-line",
    "warning",
    "Multi-line docs should use the literal block style (`doc: |`).",
    anchor="doc",
    fixable=True,
)
def doc_multi_line(ctx: LintContext) -> None:
    for _spec, key, n in doc_nodes(ctx.root):
        if not n.is_str or n.style == "|":
            continue
        fixable = plan_multi_line(ctx.doc, key, n) is not None
        if n.style == ">":
            ctx.report(
                "use a literal block (`|`) instead of a folded block (`>`) for multi-line docs",
                n,
                fixable=fixable,
            )
        elif _is_multiline_content(n) or n.start.line != ctx.doc.last_line(n):
            ctx.report(
                "multi-line doc should use a literal block scalar (`doc: |`)", n, fixable=fixable
            )


@rule(
    "KSY402",
    "doc-line-length",
    "warning",
    "Wrap doc lines at 80 columns.",
    anchor="doc",
    options={"max-length": DEFAULT_MAX_LENGTH},
    fixable=True,
)
def doc_line_length(ctx: LintContext) -> None:
    limit = int(ctx.options.get("max-length", DEFAULT_MAX_LENGTH))
    for _spec, key, n in doc_nodes(ctx.root):
        if not n.is_str:
            continue
        if n.style == "|":
            last = ctx.doc.last_line(n)
            content = ctx.lines[n.start.line + 1 : last + 1]
            nonblank = [ln for ln in content if ln.strip()]
            if not nonblank:
                continue
            ind = min(map(indent, nonblank))
            fixable = plan_line_length(ctx.doc, key, n, limit) is not None
            rel = [ln[ind:] for ln in content]
            plan = wrap_plan(rel, limit) if fixable else [None] * len(rel)
            for off, (text, new) in enumerate(zip(rel, plan, strict=True)):
                if _too_long(text, limit):
                    ctx.report(
                        f"doc line is {len(text)} characters long (limit {limit})",
                        pos=Pos(n.start.line + 1 + off, ind + limit),
                        path=n.ptr,
                        fixable=new is not None,
                    )
                    break
        elif n.start.line == ctx.doc.last_line(n) and _too_long(n.value, limit):
            ctx.report(
                f"doc is {len(n.value)} characters long (limit {limit}); wrap it into a multi-line `|` block",
                n,
                fixable=plan_line_length(ctx.doc, key, n, limit) is not None,
            )


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
