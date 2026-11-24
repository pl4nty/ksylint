"""KSY0xx: file encoding, line endings and YAML layout."""

from __future__ import annotations

from collections.abc import Iterator

from ..linter import LintContext
from ..registry import rule
from ..yamldoc import MAP, SCALAR, SEQ, Node, Pos, YamlDocument


@rule(
    "KSY001",
    "utf8-encoding",
    "error",
    "File must be UTF-8 encoded, without a byte order mark.",
    anchor="general",
    fixable=True,
    needs="text",
)
def utf8_encoding(ctx: LintContext) -> None:
    src = ctx.source
    if src.utf8_error is not None:
        line, off, reason = src.utf8_error
        ctx.report(
            f"file is not valid UTF-8 ({reason} at byte {off})", line=line, col=0, fixable=False
        )
    if src.bom:
        ctx.report("file starts with a UTF-8 byte order mark; remove it", line=0, col=0)


@rule(
    "KSY002",
    "line-endings",
    "error",
    "Lines must end with LF (Unix line endings), not CRLF or CR.",
    anchor="general",
    fixable=True,
    needs="text",
)
def line_endings(ctx: LintContext) -> None:
    text = ctx.text
    if "\r" not in text:
        return
    n_crlf = text.count("\r\n")
    n_cr = text.count("\r") - n_crlf
    kinds = []
    if n_crlf:
        kinds.append(f"{n_crlf} CRLF")
    if n_cr:
        kinds.append(f"{n_cr} CR")
    ctx.report(
        f"use LF line endings ({' and '.join(kinds)} line ending(s) found)",
        pos=ctx.doc.pos(text.index("\r")),
    )


@rule(
    "KSY003",
    "trailing-newline",
    "error",
    "File must end with a single newline character.",
    anchor="general",
    fixable=True,
    needs="text",
)
def trailing_newline(ctx: LintContext) -> None:
    text = ctx.text
    if not text:
        return
    if not text.endswith("\n"):
        last = len(ctx.lines) - 1
        ctx.report("no newline at end of file", line=last, col=len(ctx.lines[last]))
        return
    stripped = text.rstrip("\r\n")
    extra = text[len(stripped) :].count("\n") - 1
    if extra > 0 and stripped:
        line = stripped.count("\n") + 1
        ctx.report(f"{extra} blank line(s) at end of file", line=line, col=0)


DIRECTIVE = "directive"
#: The first `---`, alone on its line (or with a comment): removable.
START = "start"
#: The first `---`, with content on the same line (`--- foo: 1`).
START_INLINE = "start-inline"
#: A further `---`: the file has several documents.
EXTRA_START = "extra-start"
END = "end"


def document_markers(lines: list[str]) -> Iterator[tuple[int, str]]:
    """Yield ``(line index, kind)`` for YAML directives and document
    markers. Stops at the second ``---``."""
    in_header = True
    for i, ln in enumerate(lines):
        s = ln.strip()
        if in_header and (s == "" or s.startswith("#")):
            continue
        if in_header and ln.startswith("%"):
            yield i, DIRECTIVE
            continue
        marker, rest = ln[:3], ln[3:]
        if rest[:1] not in ("", " ", "\t"):
            marker = ""
        if marker == "---":
            if not in_header:
                yield i, EXTRA_START
                return
            in_header = False
            yield i, START if rest.strip()[:1] in ("", "#") else START_INLINE
        elif marker == "...":
            yield i, END
        else:
            in_header = False


@rule(
    "KSY004",
    "single-document",
    "error",
    "Single implicit YAML document: no `---` marker, no `%YAML`/`%TAG` directives, no `...`.",
    anchor="general",
    fixable=True,
    needs="text",
)
def single_document(ctx: LintContext) -> None:
    single = ctx.doc.n_documents <= 1
    for i, kind in document_markers(ctx.lines):
        if kind == DIRECTIVE:
            directive = ctx.lines[i].split()[0]
            ctx.report(f"remove the `{directive}` directive", line=i, col=0, fixable=single)
        elif kind in (START, START_INLINE):
            ctx.report(
                "remove the `---` document start marker",
                line=i,
                col=0,
                fixable=single and kind == START,
            )
        elif kind == EXTRA_START:
            ctx.report("file contains multiple YAML documents", line=i, col=0, fixable=False)
        else:
            ctx.report("remove the `...` document end marker", line=i, col=0, fixable=False)


@rule(
    "KSY005",
    "yaml-syntax",
    "error",
    "File must be well-formed YAML with a mapping at the top level.",
    needs="text",
)
def yaml_syntax(ctx: LintContext) -> None:
    doc = ctx.doc
    if doc.error is not None:
        pos = doc.error_pos or Pos(0, 0)
        ctx.report(f"YAML syntax error: {doc.error_message}", pos=pos)
        return
    if doc.root is None:
        ctx.report("file is empty", line=0, col=0)
    elif not doc.root.is_map:
        ctx.report("top level of a .ksy file must be a mapping", doc.root)


@rule("KSY006", "duplicate-key", "error", "Mapping keys must be unique.")
def duplicate_key(ctx: LintContext) -> None:
    for n in ctx.root.walk():
        if n.kind != MAP:
            continue
        seen: dict = {}
        for k, _ in n.items:
            key = (type(k.value), k.value)
            if key in seen:
                first = seen[key]
                ctx.report(
                    f"duplicate key `{k.raw}` (first defined on line {first.start.line + 1})", k
                )
            else:
                seen[key] = k


# ---------------------------------------------------------------------------
# indentation


def _report_indentation(ctx: LintContext, rule_id: str) -> None:
    if "indentation" not in ctx.cache:
        ctx.cache["indentation"] = indentation_issues(ctx.doc)
    for rid, msg, pos in ctx.cache["indentation"]:
        if rid == rule_id:
            ctx.report(msg, pos=pos)


@rule(
    "KSY007",
    "indentation",
    "error",
    "Use 2-space indentation (and exactly one space after `-`).",
    anchor="general",
    fixable=True,
)
def indentation(ctx: LintContext) -> None:
    _report_indentation(ctx, "KSY007")


@rule(
    "KSY008",
    "sequence-indent",
    "error",
    "Block sequences must be indented relative to their parent key.",
    anchor="general",
    fixable=True,
)
def sequence_indent(ctx: LintContext) -> None:
    _report_indentation(ctx, "KSY008")


@rule(
    "KSY009",
    "seq-map-first-key",
    "error",
    "A map inside a sequence must start on the `-` line (`- id: foo`).",
    anchor="general",
    fixable=True,
)
def seq_map_first_key(ctx: LintContext) -> None:
    _report_indentation(ctx, "KSY009")


def indentation_issues(doc: YamlDocument) -> list[tuple[str, str, Pos]]:
    """``(rule ID, message, position)`` for every KSY007/008/009 problem."""
    out: list[tuple[str, str, Pos]] = []
    root = doc.root
    if root is not None and root.is_block and not doc.odd_breaks:
        if root.start.col != 0 and root.is_map:
            out.append(
                (
                    "KSY007",
                    f"top-level keys must start at column 1, not {root.start.col + 1}",
                    root.start,
                )
            )
        _check(doc, root, out)
    return out


def _check(doc: YamlDocument, node: Node, out: list) -> None:
    if node.kind == MAP and not node.flow:
        for k, v in node.items:
            kcol = k.start.col
            if v.kind == MAP and not v.flow and v.items:
                if v.start.col != kcol + 2:
                    out.append(
                        (
                            "KSY007",
                            f"expected indentation of {kcol + 2} spaces, found {v.start.col}",
                            v.start,
                        )
                    )
            elif v.kind == SEQ and not v.flow and v.items:
                d = doc.dash_of(v.items[0])
                if d is not None:
                    dline, dcol, _ = d
                    if dcol == kcol:
                        out.append(
                            (
                                "KSY008",
                                f"sequence under `{k.raw}` must be indented by 2 spaces (`- ` at column {kcol + 3})",
                                Pos(dline, dcol),
                            )
                        )
                    elif dcol != kcol + 2:
                        out.append(
                            (
                                "KSY007",
                                f"expected sequence indentation of {kcol + 2} spaces, found {dcol}",
                                Pos(dline, dcol),
                            )
                        )
            elif v.kind == SCALAR and v.style in ("|", ">"):
                ind = doc.block_scalar_indent(v)
                if ind is not None and ind != kcol + 2:
                    out.append(
                        (
                            "KSY007",
                            f"block scalar content should be indented by {kcol + 2} spaces, found {ind}",
                            Pos(v.start.line + 1, ind),
                        )
                    )
            _check(doc, v, out)
    elif node.kind == SEQ and not node.flow:
        for item in node.items:
            d = doc.dash_of(item)
            if d is None:
                _check(doc, item, out)
                continue
            dline, dcol, same = d
            if item.kind == MAP and not item.flow:
                if not same:
                    out.append(
                        (
                            "KSY009",
                            "put the first key of this map on the `-` line (`- key: value`)",
                            Pos(dline, dcol),
                        )
                    )
                elif item.start.col != dcol + 2:
                    out.append(("KSY007", "use exactly one space after `-`", Pos(dline, dcol + 1)))
            elif same and item.start.col != dcol + 2 and item.kind != SEQ:
                out.append(("KSY007", "use exactly one space after `-`", Pos(dline, dcol + 1)))
            _check(doc, item, out)


@rule(
    "KSY010",
    "block-style",
    "info",
    "Prefer block style over flow style for maps (`{ ... }`).",
    anchor="general",
)
def block_style(ctx: LintContext) -> None:
    for n in ctx.root.walk():
        if n.kind == MAP and n.flow and n.items and n is not ctx.root:
            ctx.report("use block style instead of a flow mapping `{ ... }`", n)


@rule(
    "KSY011",
    "file-name",
    "error",
    "File name must end with `.ksy`.",
    needs="text",
)
def file_name(ctx: LintContext) -> None:
    fn = ctx.filename
    if fn and fn not in ("-", "<stdin>") and not fn.endswith(".ksy"):
        ctx.report("file name should end with `.ksy`", line=0, col=0)
