"""Autofix.

Fixes are applied as surgical, line-based edits computed from node
positions, so everything that is not being fixed (comments, quoting, flow
collections, alignment, blank lines) is left untouched. A full round-trip
re-serialisation (e.g. with ruamel.yaml) was evaluated and rejected: on the
official formats repository it rewrote unrelated formatting in about 10% of
the files.

Every step is verified: the file is re-parsed and the plain-loaded data must
be identical to the data before the step (modulo the intended change, e.g.
sorted ``tags``). A step that fails verification is discarded. The whole
pipeline is repeated until it reaches a fixed point, so ``fix_text`` is
idempotent.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Union

import yaml

from . import specs
from .config import Config
from .linter import decode
from .rules.order import sorted_positions
from .rules.schema import encoding_fixes
from .yamldoc import MAP, SCALAR, SEQ, Node, YamlDocument


class _Abort(Exception):
    pass


@dataclass
class FixResult:
    text: str
    #: rule IDs whose fixes were applied
    applied: list[str] = field(default_factory=list)
    #: (step, reason) for fixes that could not be applied safely
    skipped: list[tuple[str, str]] = field(default_factory=list)
    original: str = ""

    @property
    def changed(self) -> bool:
        return self.text != self.original


def _load(text: str) -> Any:
    return yaml.safe_load(text)


# ---------------------------------------------------------------------------
# text-level fixes


def _fix_line_endings(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _fix_doc_markers(text: str) -> str:
    lines = text.split("\n")
    out = []
    in_header = True
    removed_marker = False
    for ln in lines:
        s = ln.strip()
        if in_header and (s == "" or s.startswith("#")):
            out.append(ln)
            continue
        if in_header and ln.startswith("%"):
            continue
        if (
            in_header
            and not removed_marker
            and (ln == "---" or ln.startswith("--- #") or ln.startswith("---\t#"))
        ):
            rest = ln[3:].strip()
            if rest:
                out.append(rest)
            removed_marker = True
            in_header = False
            continue
        in_header = False
        out.append(ln)
    return "\n".join(out)


def _fix_trailing_newline(text: str) -> str:
    if not text:
        return text
    return text.rstrip("\n") + "\n"


# ---------------------------------------------------------------------------
# indentation


def _protected_lines(doc: YamlDocument) -> set[int]:
    """Lines inside multi-line scalars (their content must not be touched
    by comment heuristics)."""
    out: set[int] = set()
    if doc.root is None:
        return out
    for n in _all_nodes(doc.root):
        if n.kind == SCALAR:
            last = doc.last_line(n)
            if last > n.start.line:
                out.update(range(n.start.line + 1, last + 1))
        elif n.flow and n.end.line > n.start.line:
            out.update(range(n.start.line + 1, n.end.line + 1))
    return out


def _all_nodes(node: Node):
    yield node
    if node.kind == MAP:
        for k, v in node.items:
            yield k
            yield from _all_nodes(v)
    elif node.kind == SEQ:
        for v in node.items:
            yield from _all_nodes(v)


def _is_comment(lines: list[str], i: int, protected: set[int]) -> bool:
    return i not in protected and lines[i].lstrip().startswith("#")


def _fix_indentation(text: str) -> Optional[str]:
    doc = YamlDocument(text)
    root = doc.root
    if not doc.ok or root is None or root.kind != MAP or root.flow or doc.n_documents != 1:
        return None
    lines = doc.lines
    n = len(lines)
    shift: list[Optional[int]] = [None] * n
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
            head = lines[v.start.line][v.start.col :].split("#", 1)[0]
            if any(c.isdigit() for c in head):
                return  # explicit indentation indicator: leave alone
            last = doc.last_line(v)
            ind = None
            for i in range(v.start.line + 1, last + 1):
                if lines[i].strip():
                    ind = len(lines[i]) - len(lines[i].lstrip(" "))
                    break
            if ind is None:
                return
            s = kexp + 2 - ind
            for i in range(v.start.line + 1, last + 1):
                shift[i] = s
                content_lines.add(i)

    def fix_map(m: Node, exp: int, first_on_dash: bool) -> None:
        for idx, (k, v) in enumerate(m.items):
            if k.kind != SCALAR:
                raise _Abort("complex key")
            starts = doc.line_starts_at(k.start)
            if starts or (first_on_dash and idx == 0):
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
                if not same:
                    raise _Abort("nested sequence on its own line")
                fix_seq(item, dexp + 2)
            elif (
                same
                and item.start.col != dcol + 2
                and item.kind == SCALAR
                and item.style not in ("|", ">")
            ):
                rewrite[dline] = (dexp, item.start.col)

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
        if _is_comment(lines, i, protected):
            if nxt is not None:
                shift[i] = (
                    shift[nxt]
                    if nxt not in rewrite
                    else rewrite[nxt][0] - (len(lines[nxt]) - len(lines[nxt].lstrip(" ")))
                )
        else:
            nxt = i

    out = []
    for i, ln in enumerate(lines):
        if i in delete:
            continue
        if i in rewrite:
            dexp, ccol = rewrite[i]
            out.append(" " * dexp + "- " + ln[ccol:])
            continue
        s = shift[i] or 0
        if not ln.strip() or s == 0:
            out.append(ln)
        elif s > 0:
            out.append(" " * s + ln)
        else:
            lead = len(ln) - len(ln.lstrip(" "))
            if lead < -s:
                if _is_comment(lines, i, protected):
                    out.append(ln.lstrip(" "))
                    continue
                return None
            out.append(ln[-s:])
    return "\n".join(out)


# ---------------------------------------------------------------------------
# reordering (key order, xref, tags)


def _blocks(
    doc: YamlDocument, anchors: list[tuple[int, int]], protected: set[int]
) -> Optional[list[tuple[int, int]]]:
    """Given (first line, last line) of each entry, extend each entry upward
    over directly-preceding comment lines and down to the last non-blank line
    before the next entry. Returns (start, end) per entry."""
    lines = doc.lines
    out = []
    prev_end = -1
    for i, (a, b) in enumerate(anchors):
        start = a
        j = a - 1
        while j > prev_end and _is_comment(lines, j, protected):
            j -= 1
        if i > 0:
            start = j + 1
        out.append([start, b])
        prev_end = b
    for i in range(len(out) - 1):
        nxt = out[i + 1][0]
        e = nxt - 1
        while e > out[i][1] and not lines[e].strip():
            e -= 1
        if e < out[i][1]:
            return None
        out[i][1] = e
    return [(a, b) for a, b in out]


def _apply_perm(
    lines: list[str],
    blocks: list[tuple[int, int]],
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


def _reorder_tasks(
    doc: YamlDocument, enabled: Callable[[str], bool]
) -> list[tuple[Node, list[int], str]]:
    tasks: list[tuple[Node, list[int], str]] = []
    rule_for = {
        specs.TYPE: "KSY300",
        specs.META: "KSY301",
        specs.META_NESTED: "KSY301",
        specs.ATTR: "KSY302",
        specs.INSTANCE: "KSY303",
        specs.PARAM: "KSY304",
        specs.ENUM_VALUE: "KSY305",
        specs.SWITCH: "KSY306",
    }
    for spec in specs.iter_specs(doc.root):
        node = spec.node
        if node.flow or len(node.items) < 2:
            continue
        if spec.kind in rule_for:
            rid = rule_for[spec.kind]
            if not enabled(rid):
                continue
            perm = sorted_positions(node, specs.order_of(spec.kind))
        elif spec.kind == specs.XREF:
            rid = "KSY207"
            if not enabled(rid):
                continue
            perm = sorted(
                range(len(node.items)), key=lambda i, node=node: str(node.items[i][0].value)
            )
        else:
            continue
        if perm != list(range(len(perm))):
            tasks.append((node, perm, rid))
    meta = doc.root.get("meta") if doc.root is not None else None
    tags = meta.get("tags") if meta is not None and meta.is_map else None
    if (
        tags is not None
        and tags.is_seq
        and not tags.flow
        and len(tags.items) > 1
        and enabled("KSY208")
        and all(i.kind == SCALAR and doc.last_line(i) == i.start.line for i in tags.items)
    ):
        perm = sorted(range(len(tags.items)), key=lambda i: str(tags.items[i].value))
        if perm != list(range(len(perm))):
            tasks.append((tags, perm, "KSY208"))
    return tasks


def _fix_reorder(text: str, enabled: Callable[[str], bool]) -> tuple[Optional[str], set[str]]:
    applied: set[str] = set()
    for _ in range(8):
        doc = YamlDocument(text)
        if not doc.ok or doc.root is None or doc.root.kind != MAP or doc.n_documents != 1:
            return None, applied
        tasks = _reorder_tasks(doc, enabled)
        if not tasks:
            return text, applied
        protected = _protected_lines(doc)
        lines = list(doc.lines)
        tasks.sort(key=lambda t: -len(t[0].path))
        done_any = False
        for node, perm, rid in tasks:
            if node.kind == MAP:
                keys = [k for k, _ in node.items]
                if any(k.kind != SCALAR or k.start.line != k.end.line for k in keys):
                    continue
                if len({(type(k.value), k.value) for k in keys}) != len(keys):
                    continue  # duplicate keys: leave to the user
                first_on_dash = not doc.line_starts_at(keys[0].start)
                if any(not doc.line_starts_at(k.start) for k in keys[1:]):
                    continue
                anchors = [(k.start.line, max(k.end.line, doc.last_line(v))) for k, v in node.items]
                if first_on_dash:
                    line0 = doc.lines[keys[0].start.line]
                    prefix = line0[: keys[0].start.col]
                    if prefix.strip() != "-":
                        continue
            else:  # tags sequence
                dashes = [doc.dash_of(i) for i in node.items]
                if any(d is None or not d[2] for d in dashes):
                    continue
                anchors = [(d[0], doc.last_line(i)) for d, i in zip(dashes, node.items)]
                first_on_dash = False
            blocks = _blocks(doc, anchors, protected)
            if blocks is None:
                continue
            dash = None
            if first_on_dash:
                offsets = [a - blocks[i][0] for i, (a, _b) in enumerate(anchors)]
                dash = (prefix, offsets)
            _apply_perm(lines, blocks, perm, dash)
            applied.add(rid)
            done_any = True
        if not done_any:
            return text, applied
        text = "\n".join(lines)
    return text, applied


def _expected_after_reorder(data: Any) -> Any:
    """Dict equality ignores order; only `meta/tags` (a list) changes."""
    d = copy.deepcopy(data)
    try:
        tags = d["meta"]["tags"]
        if isinstance(tags, list):
            d["meta"]["tags"] = sorted(tags, key=str)
    except (KeyError, TypeError):
        pass
    return d


# ---------------------------------------------------------------------------
# encoding names


def _fix_encodings(text: str) -> tuple[Optional[str], list[tuple[tuple, str]]]:
    doc = YamlDocument(text)
    if not doc.ok:
        return None, []
    fixes = [(n, c) for n, c in encoding_fixes(doc.root) if n.start.line == n.end.line]
    if not fixes:
        return text, []
    out = text
    for n, canon in sorted(fixes, key=lambda t: -t[0].start.index):
        a, b = n.start.index, n.end.index
        if n.style in ("'", '"'):
            rep = n.style + canon + n.style
        elif n.style is None:
            rep = canon
        else:
            continue
        out = out[:a] + rep + out[b:]
    return out, [(n.path, c) for n, c in fixes]


def _set_path(data: Any, path: tuple, value: Any) -> None:
    cur = data
    for seg in path[:-1]:
        cur = cur[seg]
    cur[path[-1]] = value


# ---------------------------------------------------------------------------


def fix_text(
    text: Union[str, bytes],
    filename: Optional[str] = None,
    *,
    config: Optional[Config] = None,
) -> FixResult:
    """Apply all safe autofixes for the enabled, fixable rules.

    Pure function. Returns a :class:`FixResult`; ``result.text`` is the fixed
    text (identical to the input if nothing could be fixed).
    """
    cfg = config or Config()
    enabled_ids = {r.id for r in cfg.enabled_rules() if r.fixable}

    def enabled(rid: str) -> bool:
        return rid in enabled_ids

    src = decode(text, filename)
    original = text if isinstance(text, str) else src.text
    result = FixResult(text=original, original=original)
    if src.utf8_error is not None:
        result.skipped.append(("KSY001", "file is not valid UTF-8; nothing fixed"))
        return result

    cur = src.text if enabled("KSY001") else original
    applied: set[str] = set()
    if cur != original:
        applied.add("KSY001")

    for _round in range(4):
        before_round = cur
        # --- text-level fixes (verified together) ---
        steps: list[tuple[str, Callable[[str], str]]] = [
            ("KSY002", _fix_line_endings),
            ("KSY004", _fix_doc_markers),
            ("KSY003", _fix_trailing_newline),
        ]
        for rid, fn in steps:
            if not enabled(rid):
                continue
            if rid == "KSY004" and YamlDocument(cur).n_documents > 1:
                continue
            new = fn(cur)
            if new != cur:
                if _same_data(cur, new):
                    cur = new
                    applied.add(rid)
                else:
                    result.skipped.append((rid, "fix would change the parsed data"))

        # --- indentation ---
        if any(enabled(r) for r in ("KSY007", "KSY008", "KSY009")):
            new = _fix_indentation(cur)
            if new is not None and new != cur:
                if _same_data(cur, new):
                    rids = _layout_rules_fixed(cur, new)
                    cur = new
                    applied |= rids
                else:
                    result.skipped.append(("KSY007", "re-indentation would change the parsed data"))

        # --- key order / xref / tags ---
        new, rids = _fix_reorder(cur, enabled)
        if new is not None and new != cur:
            try:
                ok = _load(new) == _expected_after_reorder(_load(cur))
            except yaml.YAMLError:
                ok = False
            if ok:
                cur = new
                applied |= rids
            else:
                result.skipped.append(("KSY300", "reordering would change the parsed data"))

        # --- encoding names ---
        if enabled("KSY101"):
            new, changes = _fix_encodings(cur)
            if new is not None and new != cur:
                try:
                    expected = _load(cur)
                    for path, canon in changes:
                        _set_path(expected, path, canon)
                    ok = _load(new) == expected
                except (yaml.YAMLError, KeyError, IndexError, TypeError):
                    ok = False
                if ok:
                    cur = new
                    applied.add("KSY101")
                else:
                    result.skipped.append(("KSY101", "renaming encodings would change other data"))

        if cur == before_round:
            break

    result.text = cur
    result.applied = sorted(applied)
    # de-duplicate skipped entries
    seen = set()
    result.skipped = [s for s in result.skipped if not (s in seen or seen.add(s))]
    return result


def _same_data(a: str, b: str) -> bool:
    try:
        return _load(a) == _load(b)
    except yaml.YAMLError:
        return False


def _layout_rules_fixed(before: str, after: str) -> set[str]:
    from .linter import lint_text

    cfg = Config(select=["KSY007", "KSY008", "KSY009"])
    b = {d.rule_id for d in lint_text(before, None, config=cfg)}
    a = {d.rule_id for d in lint_text(after, None, config=cfg)}
    return b - a or {"KSY007"}
