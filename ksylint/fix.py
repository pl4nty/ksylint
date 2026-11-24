"""Autofix.

Fixes are applied as surgical, line-based edits computed from node
positions, so everything that is not being fixed (comments, quoting, flow
collections, alignment, blank lines) is left untouched. A full round-trip
re-serialisation (e.g. with ruamel.yaml) was evaluated and rejected: on the
official formats repository it rewrote unrelated formatting in about 10% of
the files.

Every step is verified: the result is re-loaded and its data must be
identical to the data before the step (modulo the intended change, e.g.
sorted ``tags``). A step that fails verification is discarded. The whole
pipeline is repeated until it reaches a fixed point, so ``fix_text`` is
idempotent.
"""

from __future__ import annotations

import copy
import functools
import itertools
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any, Optional, Union

import yaml

from . import specs
from .config import Config
from .linter import decode, suppressed, suppressions
from .registry import get_rule
from .rules.docs import doc_fixes, max_length
from .rules.layout import DIRECTIVE, START, document_markers, indentation_issues, is_empty
from .rules.order import sorted_positions
from .rules.schema import encoding_fixes
from .yamldoc import MAP, SCALAR, SEQ, Node, YamlDocument, indent

_BOM = "\ufeff"
_MAX_ROUNDS = 4


class _Abort(Exception):
    """The document has a layout the line-based fixer does not handle."""


@dataclass
class FixResult:
    text: str
    #: rule IDs whose fixes were applied
    applied: list[str] = field(default_factory=list)
    #: (rule ID, reason) for fixes that could not be applied safely
    skipped: list[tuple[str, str]] = field(default_factory=list)
    original: str = ""

    @property
    def changed(self) -> bool:
        return self.text != self.original


@dataclass
class _Edit:
    """The outcome of one fix step."""

    text: str
    #: rule IDs whose problems the step fixed
    rules: set[str]
    #: maps the data before the step to the data expected after it
    expect: Callable[[Any], Any] = lambda data: data


# ---------------------------------------------------------------------------
# text-level fixes


def _fix_line_endings(text: str, _active: set[str], _cfg: Config) -> _Edit:
    return _Edit(text.replace("\r\n", "\n").replace("\r", "\n"), {"KSY002"})


def _fix_doc_markers(text: str, _active: set[str], _cfg: Config) -> _Edit:
    lines = text.split("\n")
    keep: list[Optional[str]] = list(lines)
    for i, kind in document_markers([ln.rstrip("\r") for ln in lines]):
        if kind == DIRECTIVE:
            keep[i] = None
        elif kind == START:
            keep[i] = lines[i][3:].strip() or None  # keep a trailing comment
    return _Edit("\n".join(ln for ln in keep if ln is not None), {"KSY004"})


def _fix_trailing_newline(text: str, _active: set[str], _cfg: Config) -> _Edit:
    return _Edit(text.rstrip("\n") + "\n" if text else text, {"KSY003"})


# ---------------------------------------------------------------------------
# line-based fixes: common helpers


@functools.lru_cache(maxsize=1)
def _parse(text: str) -> YamlDocument:
    """Parse ``text``; consecutive steps usually see the same text. The
    steps must treat the document as read-only."""
    return YamlDocument(text)


def _block_map_document(text: str) -> Optional[YamlDocument]:
    """Parse ``text`` if the line-based fixers can work on it."""
    doc = _parse(text)
    root = doc.root
    if not doc.ok or root is None or root.kind != MAP or root.flow or doc.n_documents != 1:
        return None
    # `doc.lines` must be YAML's lines, and joining them with "\n" lossless.
    if doc.odd_breaks or "\r" in text:
        return None
    return doc


def _all_nodes(node: Node) -> Iterator[Node]:
    yield node
    if node.kind == MAP:
        for k, v in node.items:
            yield k
            yield from _all_nodes(v)
    elif node.kind == SEQ:
        for v in node.items:
            yield from _all_nodes(v)


def _protected_lines(doc: YamlDocument) -> set[int]:
    """Continuation lines of multi-line scalars and flow collections: a
    leading ``#`` there is content, not a comment."""
    out: set[int] = set()
    for n in _all_nodes(doc.root):
        if n.kind == SCALAR:
            out.update(range(n.start.line + 1, doc.last_line(n) + 1))
        elif n.flow:
            out.update(range(n.start.line + 1, n.end.line + 1))
    return out


def _is_comment(lines: list[str], i: int, protected: set[int]) -> bool:
    return i not in protected and lines[i].lstrip().startswith("#")


# ---------------------------------------------------------------------------
# indentation


def _fix_indentation(text: str, _active: set[str], _cfg: Config) -> Optional[_Edit]:
    doc = _block_map_document(text)
    if doc is None:
        return None
    root = doc.root
    lines = doc.lines
    n = len(lines)
    #: number of columns each line moves to the right
    shift: list[int] = [0] * n
    #: line -> (dash column, content column): rewrite as `<indent>- <content>`
    rewrite: dict[int, tuple[int, int]] = {}
    delete: set[int] = set()
    content_lines: set[int] = set()

    def set_span(a: int, b: int, s: int) -> None:
        for i in range(a, min(b, n - 1) + 1):
            shift[i] = s

    def fix_value(v: Node, kexp: int) -> None:
        if v.kind == MAP and not v.flow and v.items:
            fix_map(v, kexp + 2, False)
        elif v.kind == SEQ and not v.flow and v.items:
            fix_seq(v, kexp + 2)
        elif v.kind == SCALAR and v.style in ("|", ">"):
            ind = doc.block_scalar_indent(v)
            if ind is None:
                return  # empty, or explicit indentation indicator: leave alone
            for i in range(v.start.line + 1, doc.last_line(v) + 1):
                shift[i] = kexp + 2 - ind
                content_lines.add(i)

    def fix_map(m: Node, exp: int, first_on_dash: bool) -> None:
        for idx, (k, v) in enumerate(m.items):
            if k.kind != SCALAR:
                raise _Abort("complex key")
            if doc.line_starts_at(k.start) or (first_on_dash and idx == 0):
                end = max(k.end.line, doc.last_line(v))
                set_span(k.start.line, end, exp - k.start.col)
            elif idx > 0:
                raise _Abort("key does not start its line")
            fix_value(v, exp)

    def fix_seq(s: Node, dexp: int) -> None:
        for item in s.items:
            d = doc.dash_of(item)
            if d is None:
                raise _Abort("cannot locate `-`")
            dline, dcol, same = d
            end = max(dline, doc.last_line(item))
            set_span(dline, end, dexp - dcol)
            if item.kind == MAP and not item.flow and item.items:
                if not same:
                    if lines[dline].strip() != "-":
                        raise _Abort("comment on a bare `-` line")
                    delete.add(dline)
                rewrite[item.start.line] = (dexp, item.start.col)
                fix_map(item, dexp + 2, True)
            elif item.kind == SEQ and not item.flow and item.items:
                raise _Abort("nested block sequence")
            elif same and item.start.col != dcol + 2 and not is_empty(item):
                rewrite[dline] = (dexp, item.start.col)  # scalar or flow collection

    try:
        if root.start.col != 0 and not doc.line_starts_at(root.start):
            return None
        fix_map(root, 0, False)
    except _Abort:
        return None

    protected = _protected_lines(doc) | content_lines
    # Comment lines follow the indentation of the next content line.
    nxt: Optional[int] = None
    for i in range(n - 1, -1, -1):
        if not lines[i].strip():
            continue
        if not _is_comment(lines, i, protected):
            nxt = i
        elif nxt is not None:
            shift[i] = rewrite[nxt][0] - indent(lines[nxt]) if nxt in rewrite else shift[nxt]

    out = []
    for i, ln in enumerate(lines):
        if i in delete:
            continue
        s = shift[i]
        if i in rewrite:
            dexp, ccol = rewrite[i]
            out.append(" " * dexp + "- " + ln[ccol:])
        elif not ln.strip() or s == 0:
            out.append(ln)
        elif s > 0:
            out.append(" " * s + ln)
        elif indent(ln) >= -s:
            out.append(ln[-s:])
        elif _is_comment(lines, i, protected):
            out.append(ln.lstrip(" "))
        else:
            return None  # not enough indentation to remove
    new = "\n".join(out)
    if new == text:
        return None
    before = {rid for rid, _, _ in indentation_issues(doc)}
    after = {rid for rid, _, _ in indentation_issues(_parse(new))}
    return _Edit(new, before - after or {"KSY007"})


# ---------------------------------------------------------------------------
# reordering (key order, xref, tags)

_ORDER_RULES = {
    specs.TYPE: "KSY300",
    specs.META: "KSY301",
    specs.META_NESTED: "KSY301",
    specs.ATTR: "KSY302",
    specs.INSTANCE: "KSY303",
    specs.PARAM: "KSY304",
    specs.ENUM_VALUE: "KSY305",
    specs.SWITCH: "KSY306",
}
_REORDER_RULES = (*dict.fromkeys(_ORDER_RULES.values()), "KSY207", "KSY208")

#: (first line, last line) of an entry of a map or sequence.
_Span = tuple[int, int]


def _blocks(doc: YamlDocument, anchors: list[_Span], protected: set[int]) -> Optional[list[_Span]]:
    """Given (first line, last line) of each entry, extend each entry upward
    over the comment lines directly above it and down to the last non-blank
    line before the next entry. Returns (start, end) per entry.

    A comment that is indented deeper than the entry below it is taken to
    belong to the entry above it (typically commented-out nested content);
    this includes such comments directly below the last entry, which would
    otherwise become part of a block scalar that is moved in front of them.
    """
    lines = doc.lines

    def comment(i: int, entry: _Span, *, deeper: bool) -> bool:
        return _is_comment(lines, i, protected) and (
            (indent(lines[i]) > indent(lines[entry[0]])) == deeper
        )

    out = []
    prev_end = -1
    for i, (a, b) in enumerate(anchors):
        start = a
        if i > 0:
            while start - 1 > prev_end and comment(start - 1, (a, b), deeper=False):
                start -= 1
        out.append([start, b])
        prev_end = b
    for cur, nxt in itertools.pairwise(out):
        e = nxt[0] - 1
        if e < cur[1]:
            return None  # entries share a line
        while e > cur[1] and not lines[e].strip():
            e -= 1
        cur[1] = e
    while out[-1][1] + 1 < len(lines) and comment(out[-1][1] + 1, anchors[-1], deeper=True):
        out[-1][1] += 1
    return [(a, b) for a, b in out]


def _apply_perm(
    lines: list[str],
    blocks: list[_Span],
    perm: list[int],
    dash: Optional[tuple[str, list[int]]],
) -> None:
    chunks = [lines[a : b + 1] for a, b in blocks]
    seps = [lines[blocks[i][1] + 1 : blocks[i + 1][0]] for i in range(len(blocks) - 1)]
    if dash is not None:
        prefix, key_offsets = dash
        # strip the dash from the first entry, re-add it to the new first entry
        first = chunks[0]
        first[0] = " " * len(prefix) + first[0][len(prefix) :]
        tgt = chunks[perm[0]]
        off = key_offsets[perm[0]]
        tgt[off] = prefix + tgt[off][len(prefix) :]
    new: list[str] = []
    for i, src in enumerate(perm):
        new.extend(chunks[src])
        if i < len(seps):
            new.extend(seps[i])
    a, b = blocks[0][0], blocks[-1][1]
    assert len(new) == b - a + 1
    lines[a : b + 1] = new


def _reorder_tasks(doc: YamlDocument, active: set[str]) -> list[tuple[Node, list[int], str]]:
    """(node, new order of its items, rule ID) for everything out of order."""
    tasks: list[tuple[Node, list[int], str]] = []

    def add(node: Node, perm: list[int], rid: str) -> None:
        if rid in active and not node.flow and perm != sorted(perm):
            tasks.append((node, perm, rid))

    def by_str(values: list[Any]) -> list[int]:
        return sorted(range(len(values)), key=lambda i: str(values[i]))

    for spec in specs.iter_specs(doc.root):
        if spec.kind in _ORDER_RULES:
            perm = sorted_positions(spec.node, specs.ORDERS[spec.kind])
            add(spec.node, perm, _ORDER_RULES[spec.kind])
        elif spec.kind == specs.XREF:
            add(spec.node, by_str([k.value for k, _ in spec.node.items]), "KSY207")
    meta = doc.root.get("meta")
    tags = meta.get("tags") if meta is not None else None
    if tags is not None and tags.is_seq:
        add(tags, by_str([i.value for i in tags.items]), "KSY208")
    return tasks


def _map_entries(doc: YamlDocument, node: Node) -> Optional[tuple[list[_Span], Optional[str]]]:
    """Line spans of the entries of a block map, plus the ``  - `` prefix of
    the first key if the map starts on a sequence dash. ``None`` if the map
    cannot be reordered by moving whole lines."""
    keys = [k for k, _ in node.items]
    if any(k.kind != SCALAR or k.start.line != k.end.line for k in keys):
        return None
    if len({(type(k.value), k.value) for k in keys}) != len(keys):
        return None  # duplicate keys: leave to the user
    if not all(doc.line_starts_at(k.start) for k in keys[1:]):
        return None
    prefix = doc.lines[keys[0].start.line][: keys[0].start.col]
    if prefix.strip() not in ("", "-"):
        return None
    spans = [(k.start.line, max(k.end.line, doc.last_line(v))) for k, v in node.items]
    return spans, (prefix if prefix.strip() else None)


def _seq_entries(doc: YamlDocument, node: Node) -> Optional[list[_Span]]:
    """Line spans of the items of a block sequence of single-line scalars."""
    spans = []
    for item in node.items:
        dash = doc.dash_of(item)
        if dash is None or not dash[2] or item.kind != SCALAR:
            return None
        if doc.last_line(item) != item.start.line:
            return None
        spans.append((item.start.line, item.start.line))
    return spans


def _sorted_tags(data: Any) -> Any:
    out = copy.deepcopy(data)
    out["meta"]["tags"].sort(key=str)
    return out


def _fix_reorder(text: str, active: set[str], _cfg: Config) -> Optional[_Edit]:
    doc = _block_map_document(text)
    if doc is None:
        return None
    protected = _protected_lines(doc)
    lines = list(doc.lines)
    applied: set[str] = set()
    # Innermost first: moving the lines of a nested map does not change the
    # line span of any entry of the maps around it.
    for node, perm, rid in sorted(_reorder_tasks(doc, active), key=lambda t: -len(t[0].path)):
        if node.kind == MAP:
            entries = _map_entries(doc, node)
            if entries is None:
                continue
            anchors, prefix = entries
        else:
            anchors, prefix = _seq_entries(doc, node), None
            if anchors is None:
                continue
        blocks = _blocks(doc, anchors, protected)
        if blocks is None:
            continue
        dash = None
        if prefix is not None:
            dash = (prefix, [a - start for (a, _), (start, _) in zip(anchors, blocks, strict=True)])
        _apply_perm(lines, blocks, perm, dash)
        applied.add(rid)
    if not applied:
        return None
    # Dict equality ignores order, so only sorted `tags` change the data.
    if "KSY208" in applied:
        return _Edit("\n".join(lines), applied, _sorted_tags)
    return _Edit("\n".join(lines), applied)


# ---------------------------------------------------------------------------
# encoding names


def _fix_encodings(text: str, _active: set[str], _cfg: Config) -> Optional[_Edit]:
    doc = _parse(text)
    fixes = [
        (n, canon)
        for n, canon in encoding_fixes(doc.root)
        if n.start.line == n.end.line and n.style in (None, "'", '"')
    ]
    if not fixes:
        return None
    out = text
    for n, canon in sorted(fixes, key=lambda t: -t[0].start.index):
        quote = n.style or ""
        out = out[: n.start.index] + quote + canon + quote + out[n.end.index :]

    return _Edit(out, {"KSY101"}, _set_values([(n.path, canon) for n, canon in fixes]))


def _set_values(changes: list[tuple[tuple, Any]]) -> Callable[[Any], Any]:
    """``expect`` function: the data with the values at these paths replaced."""

    def expect(data: Any) -> Any:
        data = copy.deepcopy(data)
        for path, value in changes:
            parent = data
            for seg in path[:-1]:
                parent = parent[seg]
            parent[path[-1]] = value
        return data

    return expect


# ---------------------------------------------------------------------------
# doc strings


def _fix_docs(text: str, active: set[str], cfg: Config) -> Optional[_Edit]:
    """KSY400-KSY402. Unlike the other fixes these change the doc strings,
    each in the one way :mod:`ksylint.rules.docs` verified; docs whose
    diagnostic is suppressed by a ``disable`` comment are left alone."""
    doc = _parse(text)
    if not doc.ok or "\r" in text:
        return None
    _, line_off = suppressions(doc.lines)
    fixes = []
    for fix in doc_fixes(doc, active, max_length(cfg)):
        r = get_rule(fix.rule)
        lines = range(fix.node.start.line, doc.last_line(fix.node) + 1)
        if not any(suppressed(line_off.get(i + 1, set()), r.id, r.name) for i in lines):
            fixes.append(fix)
    if not fixes:
        return None
    out = text
    for fix in sorted(fixes, key=lambda f: -f.start):
        out = out[: fix.start] + fix.replacement + out[fix.end :]
    changes = [(f.node.path, f.value) for f in fixes]
    return _Edit(out, {f.rule for f in fixes}, _set_values(changes))


# ---------------------------------------------------------------------------

#: (rule IDs the step fixes, step, why a result that fails verification is
#: rejected). A step runs if any of its rules is enabled.
_STEPS: list[tuple[tuple[str, ...], Callable[[str, set[str], Config], Optional[_Edit]], str]] = [
    (("KSY002",), _fix_line_endings, "fix would change the parsed data"),
    (("KSY004",), _fix_doc_markers, "fix would change the parsed data"),
    (("KSY003",), _fix_trailing_newline, "fix would change the parsed data"),
    (
        ("KSY007", "KSY008", "KSY009"),
        _fix_indentation,
        "re-indentation would change the parsed data",
    ),
    (_REORDER_RULES, _fix_reorder, "reordering would change the parsed data"),
    (("KSY101",), _fix_encodings, "renaming encodings would change other data"),
    (("KSY400", "KSY401", "KSY402"), _fix_docs, "doc fix would change other data"),
]


def _load(text: str) -> Any:
    return yaml.safe_load(text)


def fix_text(
    text: Union[str, bytes],
    filename: Optional[str] = None,
    *,
    config: Optional[Config] = None,
) -> FixResult:
    """Apply all safe autofixes for the enabled, fixable rules.

    Pure function. Returns a :class:`FixResult`; ``result.text`` is the fixed
    text (identical to the input if nothing could be fixed). Rules disabled
    for the whole file with ``# ksylint: disable-file`` are not fixed.
    """
    cfg = config or Config()
    src = decode(text, filename)
    bom = _BOM if src.bom else ""
    result = FixResult(text=bom + src.text, original=bom + src.text)
    if src.utf8_error is not None:
        result.skipped.append(("KSY001", "file is not valid UTF-8; nothing fixed"))
        return result
    cur = src.text
    try:
        data = _load(cur)
    except yaml.YAMLError:
        result.skipped.append(
            ("KSY005", "file is not a single well-formed YAML document; nothing fixed")
        )
        return result

    file_off, _ = suppressions(cur.split("\n"))
    enabled = {
        r.id for r in cfg.enabled_rules() if r.fixable and not suppressed(file_off, r.id, r.name)
    }
    applied: set[str] = set()
    if bom and "KSY001" in enabled:
        bom = ""
        applied.add("KSY001")
    # The fixers work on LF-terminated lines. If CRLF line endings are to be
    # kept, convert them for the duration (mixed line endings are left alone).
    keep_crlf = (
        "KSY002" not in enabled and "\r\n" in cur and re.search(r"\r(?!\n)|(?<!\r)\n", cur) is None
    )
    if keep_crlf:
        cur = cur.replace("\r\n", "\n")

    for _round in range(_MAX_ROUNDS):
        before_round = cur
        for rule_ids, step, why_rejected in _STEPS:
            active = enabled.intersection(rule_ids)
            edit = step(cur, active, cfg) if active else None
            if edit is None or edit.text == cur:
                continue
            expected = None
            if not edit.rules <= enabled:
                ok = False
                others = ", ".join(sorted(edit.rules - enabled))
                reason = f"fix would also change what the disabled rule(s) {others} cover"
            else:
                reason = why_rejected
                try:
                    expected = edit.expect(data)
                    ok = _load(edit.text) == expected
                except (yaml.YAMLError, LookupError, TypeError):
                    ok = False
            if ok:
                cur, data = edit.text, expected
                applied |= edit.rules
            elif (rule_ids[0], reason) not in result.skipped:
                result.skipped.append((rule_ids[0], reason))
        if cur == before_round:
            break

    result.text = bom + (cur.replace("\n", "\r\n") if keep_crlf else cur)
    result.applied = sorted(applied)
    return result
