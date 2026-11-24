"""YAML document model with source positions.

We parse with PyYAML (YAML 1.1, like the SnakeYAML parser that the Kaitai
Struct compiler uses) into a small tree of :class:`Node` objects. Each node
knows its source span, its scalar style / flow style and its JSON-pointer-like
path, which lets rules report precise positions and lets the fixer make
surgical, line-based edits instead of re-serialising the whole document.
"""

from __future__ import annotations

import bisect
import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Optional

import yaml
from yaml.constructor import SafeConstructor

MAP = "map"
SEQ = "seq"
SCALAR = "scalar"

#: Line breaks (to YAML) that do not end a line in :attr:`YamlDocument.lines`.
_ODD_BREAK_RE = re.compile("\r(?!\n)|[\x85\u2028\u2029]")


@dataclass(frozen=True)
class Pos:
    """0-based source position. Lines are separated by ``\n`` only (see
    :meth:`YamlDocument.pos`); ``index`` is the character offset."""

    line: int
    col: int
    index: int = 0


class Node:
    """A YAML node.

    * ``kind`` is one of ``map``, ``seq``, ``scalar``.
    * For maps, ``items`` is a list of ``(key_node, value_node)`` pairs in
      source order (duplicates preserved); ``key_node.value`` is the
      constructed key.
    * For sequences, ``items`` is a list of nodes.
    * For scalars, ``value`` is the constructed Python value and ``raw`` the
      scalar text.
    """

    __slots__ = (
        "end",
        "flow",
        "is_key",
        "items",
        "kind",
        "parent",
        "path",
        "ptr",
        "raw",
        "start",
        "style",
        "tag",
        "value",
    )

    def __init__(self, kind: str, start: Pos, end: Pos) -> None:
        self.kind = kind
        self.start = start
        self.end = end
        self.tag: str = ""
        self.value: Any = None
        self.raw: str = ""
        self.items: list = []
        self.style: Optional[str] = None
        self.flow: bool = False
        self.path: tuple = ()
        self.ptr: str = ""
        self.parent: Optional[Node] = None
        self.is_key = False

    # -- convenience -------------------------------------------------------
    @property
    def is_map(self) -> bool:
        return self.kind == MAP

    @property
    def is_seq(self) -> bool:
        return self.kind == SEQ

    @property
    def is_scalar(self) -> bool:
        return self.kind == SCALAR

    @property
    def is_str(self) -> bool:
        return self.kind == SCALAR and isinstance(self.value, str)

    @property
    def is_block(self) -> bool:
        return self.kind in (MAP, SEQ) and not self.flow

    def keys(self) -> list:
        return [k.value for k, _ in self.items] if self.kind == MAP else []

    def get(self, key: Any, default: Optional[Node] = None) -> Optional[Node]:
        if self.kind != MAP:
            return default
        found = default
        for k, v in self.items:
            if k.value == key and type(k.value) is type(key):
                found = v
        return found

    def key_node(self, key: Any) -> Optional[Node]:
        if self.kind != MAP:
            return None
        found = None
        for k, _ in self.items:
            if k.value == key and type(k.value) is type(key):
                found = k
        return found

    def map_items(self) -> list[tuple[Node, Node]]:
        return list(self.items) if self.kind == MAP else []

    def seq_items(self) -> list[Node]:
        return list(self.items) if self.kind == SEQ else []

    def walk(self) -> Iterator[Node]:
        """Pre-order traversal over value nodes (keys excluded)."""
        yield self
        if self.kind == MAP:
            for _, v in self.items:
                yield from v.walk()
        elif self.kind == SEQ:
            for v in self.items:
                yield from v.walk()

    def to_data(self) -> Any:
        if self.kind == MAP:
            return {_hashable(k.value): v.to_data() for k, v in self.items}
        if self.kind == SEQ:
            return [v.to_data() for v in self.items]
        return self.value

    def __repr__(self) -> str:
        return f"<Node {self.kind} {self.ptr or '/'} @{self.start.line + 1}:{self.start.col + 1}>"


def _hashable(v: Any) -> Any:
    try:
        hash(v)
        return v
    except TypeError:
        return repr(v)


def escape_ptr(seg: str) -> str:
    return seg.replace("~", "~0").replace("/", "~1")


class YamlDocument:
    """A parsed .ksy file."""

    def __init__(self, text: str) -> None:
        self.text = text
        raw_lines = text.split("\n")
        self.lines: list[str] = [ln.rstrip("\r") for ln in raw_lines]
        self._line_starts = [0]
        for ln in raw_lines[:-1]:
            self._line_starts.append(self._line_starts[-1] + len(ln) + 1)
        #: True if YAML's idea of a line differs from :attr:`lines`, in
        #: which case column-based layout checks and fixes are meaningless.
        self.odd_breaks = _ODD_BREAK_RE.search(text) is not None
        self.root: Optional[Node] = None
        self.n_documents = 0
        self.error: Optional[yaml.YAMLError] = None
        self.error_pos: Optional[Pos] = None
        self.error_message = ""
        self.nodes_by_ptr: dict[str, Node] = {}
        self._constructor = SafeConstructor()
        self._parse()

    def pos(self, index: int) -> Pos:
        """Position of a character offset.

        PyYAML's own line/column counters are not used: they also count a
        lone CR, NEL, LS and PS as line breaks (and skip a BOM), which does
        not match :attr:`lines`, editors or ``git diff``.
        """
        line = bisect.bisect_right(self._line_starts, index) - 1
        return Pos(line, index - self._line_starts[line], index)

    # -- parsing -----------------------------------------------------------
    def _parse(self) -> None:
        loader = None
        try:
            loader = yaml.SafeLoader(self.text)
            raw_root = None
            while loader.check_node():
                n = loader.get_node()
                self.n_documents += 1
                if raw_root is None:
                    raw_root = n
            if raw_root is not None:
                self.root = self._build(raw_root, (), "", None)
        except yaml.YAMLError as e:
            self.error = e
            mark = getattr(e, "problem_mark", None) or getattr(e, "context_mark", None)
            # ReaderError (e.g. a control character) has a bare `position`.
            index = mark.index if mark is not None else getattr(e, "position", None)
            if isinstance(index, int):
                self.error_pos = self.pos(index)
            problem = getattr(e, "problem", None) or getattr(e, "reason", None) or str(e)
            context = getattr(e, "context", None)
            self.error_message = f"{context}: {problem}" if context else str(problem)
            self.root = None
        finally:
            if loader is not None:
                loader.dispose()

    def _construct_scalar(self, raw: yaml.Node) -> Any:
        c = self._constructor
        try:
            return c.construct_object(raw, deep=True)
        except yaml.YAMLError:
            return raw.value
        finally:
            c.constructed_objects.clear()
            c.recursive_objects.clear()

    def _span(self, raw: yaml.Node) -> tuple[Pos, Pos]:
        return self.pos(raw.start_mark.index), self.pos(raw.end_mark.index)

    def _build(self, raw: yaml.Node, path: tuple, ptr: str, parent: Optional[Node]) -> Node:
        if isinstance(raw, yaml.MappingNode):
            node = Node(MAP, *self._span(raw))
            node.flow = bool(raw.flow_style)
        elif isinstance(raw, yaml.SequenceNode):
            node = Node(SEQ, *self._span(raw))
            node.flow = bool(raw.flow_style)
        else:
            node = Node(SCALAR, *self._span(raw))
            node.style = raw.style
            node.raw = raw.value
            node.value = self._construct_scalar(raw)
        node.tag = raw.tag
        node.path = path
        node.ptr = ptr
        node.parent = parent
        self.nodes_by_ptr.setdefault(ptr, node)
        if node.kind == MAP:
            for kraw, vraw in raw.value:
                if isinstance(kraw, yaml.ScalarNode):
                    key = Node(SCALAR, *self._span(kraw))
                    key.style = kraw.style
                    key.raw = kraw.value
                    key.value = self._construct_scalar(kraw)
                    key.tag = kraw.tag
                else:
                    key = self._build(kraw, path, ptr, node)
                    key.value = _hashable(key.to_data())
                    key.raw = str(key.value)
                key.is_key = True
                key.parent = node
                seg = key.raw if key.kind == SCALAR else str(key.value)
                key.ptr = ptr + "/" + escape_ptr(seg)
                key.path = (*path, key.value)
                val = self._build(vraw, (*path, key.value), key.ptr, node)
                node.items.append((key, val))
        elif node.kind == SEQ:
            for i, vraw in enumerate(raw.value):
                node.items.append(self._build(vraw, (*path, i), f"{ptr}/{i}", node))
        return node

    # -- data / positions ------------------------------------------------------
    @property
    def ok(self) -> bool:
        return self.root is not None and self.error is None

    def data(self) -> Any:
        return self.root.to_data() if self.root is not None else None

    def find(self, path: tuple | list) -> Optional[Node]:
        """Find a node by a path of keys / indices (str keys also match raw)."""
        node = self.root
        for seg in path:
            if node is None:
                return None
            if node.kind == SEQ:
                try:
                    node = node.items[int(seg)]
                except (ValueError, IndexError):
                    return None
            elif node.kind == MAP:
                nxt = None
                for k, v in node.items:
                    if k.value == seg or k.raw == str(seg) or str(k.value) == str(seg):
                        nxt = v
                node = nxt
            else:
                return None
        return node

    def line_starts_at(self, pos: Pos) -> bool:
        """True if only whitespace precedes ``pos`` on its line."""
        line = self.lines[pos.line] if pos.line < len(self.lines) else ""
        return line[: pos.col].strip() == ""

    def last_line(self, node: Node) -> int:
        """0-based index of the last source line that belongs to ``node``."""
        if node.kind == SCALAR:
            line = node.end.line
            if node.style in ("|", ">") or (node.end.line > node.start.line and node.style is None):
                if node.end.col == 0 and line > node.start.line:
                    line -= 1
                while line > node.start.line and self._blank(line):
                    line -= 1
            return line
        if node.flow or not node.items:
            return node.end.line
        if node.kind == MAP:
            k, v = node.items[-1]
            return max(k.end.line, self.last_line(v))
        return self.last_line(node.items[-1])

    def _blank(self, i: int) -> bool:
        return i >= len(self.lines) or self.lines[i].strip() == ""

    def dash_of(self, item: Node) -> Optional[tuple[int, int, bool]]:
        """Locate the ``-`` indicator of a block sequence item.

        Returns ``(line, column, same_line)`` (0-based), or ``None`` if it
        cannot be found.
        """
        line = self.lines[item.start.line]
        c = item.start.col - 1
        while c >= 0 and line[c] == " ":
            c -= 1
        if c >= 0 and line[c] == "-":
            return item.start.line, c, True
        if line[: item.start.col].strip() != "":
            return None
        i = item.start.line - 1
        while i >= 0:
            s = self.lines[i].strip()
            if s == "" or s.startswith("#"):
                i -= 1
                continue
            if s == "-" or s.startswith("- #") or s.startswith("-\t#") or s.startswith("-  #"):
                return i, self.lines[i].index("-"), False
            return None
        return None


def plain_load(text: str) -> Any:
    """Load YAML the plain way (for semantic comparisons)."""
    return yaml.safe_load(text)
