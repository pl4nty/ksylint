"""Linting entry points."""

from __future__ import annotations

import functools
import re
from dataclasses import dataclass
from typing import Any, Optional, Union

from .config import Config
from .diagnostic import Diagnostic, Severity
from .registry import Rule
from .yamldoc import Node, Pos, YamlDocument

_SUPPRESS_RE = re.compile(
    r"#\s*ksylint:\s*(disable-next-line|disable-file|disable)"
    r"(?:\s*=\s*([\w-]+(?:\s*,\s*[\w-]+)*))?"
)


def suppressions(lines: list[str]) -> tuple[set[str], dict[int, set[str]]]:
    """Parse ``# ksylint: disable...`` comments.

    Returns the selectors (upper-cased rule IDs or names, or ``ALL``)
    disabled for the whole file and per 1-based line.
    """
    file_off: set[str] = set()
    line_off: dict[int, set[str]] = {}
    for i, ln in enumerate(lines, start=1):
        m = _SUPPRESS_RE.search(ln) if "ksylint" in ln else None
        if not m:
            continue
        kind, ids = m.groups()
        selectors = {s.strip().upper() for s in (ids or "ALL").split(",")}
        if kind == "disable-file":
            file_off |= selectors
        else:
            line_off.setdefault(i + (kind == "disable-next-line"), set()).update(selectors)
    return file_off, line_off


def suppressed(selectors: set[str], rule_id: str, rule_name: str) -> bool:
    return bool(selectors & {"ALL", rule_id, rule_name.upper()})


@dataclass
class Source:
    """Decoded input text plus facts about the raw bytes."""

    text: str
    filename: Optional[str]
    utf8_error: Optional[tuple[int, int, str]] = None  # (line, byte offset, reason)
    bom: bool = False


def decode(data: Union[str, bytes], filename: Optional[str] = None) -> Source:
    """Decode file contents and strip a byte order mark."""
    err = None
    if isinstance(data, bytes):
        try:
            data = data.decode("utf-8")
        except UnicodeDecodeError as e:
            err = (data[: e.start].count(b"\n"), e.start, e.reason)
            data = data.decode("utf-8", errors="replace")
    bom = data.startswith("\ufeff")
    return Source(data[1:] if bom else data, filename, utf8_error=err, bom=bom)


class LintContext:
    """What a rule check function gets to look at."""

    def __init__(self, source: Source, config: Config, external: Optional[dict] = None) -> None:
        self.source = source
        self.text = source.text
        self.filename = source.filename
        self.config = config
        self.doc = YamlDocument(source.text)
        self.lines = self.doc.lines
        self.root: Optional[Node] = self.doc.root
        #: extra inputs supplied by callers (e.g. compiler results)
        self.external = external or {}
        self.diagnostics: list[Diagnostic] = []
        #: per-lint scratch space shared between rules
        self.cache: dict[str, Any] = {}
        self._rule: Optional[Rule] = None
        self._severity = Severity.ERROR
        #: options of the rule that is currently running
        self.options: dict[str, Any] = {}

    @functools.cached_property
    def data(self) -> Any:
        """The document as plain Python data (like ``yaml.safe_load``)."""
        return self.doc.data()

    @property
    def display_name(self) -> str:
        return self.filename or "<stdin>"

    def report(
        self,
        message: str,
        node: Optional[Node] = None,
        *,
        pos: Optional[Pos] = None,
        line: Optional[int] = None,
        col: Optional[int] = None,
        path: Optional[str] = None,
        end: Optional[Pos] = None,
        severity: Optional[Severity] = None,
        fixable: Optional[bool] = None,
    ) -> None:
        """Report a problem. Position is taken from ``node`` (start of the
        node), ``pos`` (0-based), or ``line``/``col`` (0-based)."""
        assert self._rule is not None
        r = self._rule
        if node is not None and pos is None:
            pos = node.start
            if end is None and node.start.line == node.end.line:
                end = node.end
        if pos is not None:
            line, col = pos.line, pos.col
        line = line or 0
        col = col or 0
        if path is None:
            path = node.ptr if node is not None else ""
        self.diagnostics.append(
            Diagnostic(
                rule_id=r.id,
                rule_name=r.name,
                severity=severity or self._severity,
                message=message,
                file=self.display_name,
                line=line + 1,
                column=col + 1,
                path=path,
                end_line=end.line + 1 if end is not None else None,
                end_column=end.col + 1 if end is not None else None,
                fixable=r.fixable if fixable is None else fixable,
                url=r.url,
            )
        )

    def run(self, rules: list[Rule]) -> list[Diagnostic]:
        for r in rules:
            if r.needs == "yaml" and self.root is None:
                continue
            self._rule = r
            self._severity = self.config.severity_of(r)
            self.options = self.config.options_for(r)
            r.check(self)
        self._rule = None
        return self._suppress(self.diagnostics)

    def _suppress(self, diags: list[Diagnostic]) -> list[Diagnostic]:
        file_off, line_off = suppressions(self.lines)
        return [
            d
            for d in diags
            if not suppressed(file_off | line_off.get(d.line, set()), d.rule_id, d.rule_name)
        ]


def lint_text(
    text: Union[str, bytes],
    filename: Optional[str] = None,
    *,
    config: Optional[Config] = None,
    external: Optional[dict] = None,
) -> list[Diagnostic]:
    """Lint the contents of a .ksy file.

    This is a pure function (no file system or network access), suitable for
    editors, language servers and Pyodide. ``filename`` is only used for
    reporting and for the filename-related rules (``meta/id`` must match the
    file name, ``.ksy`` extension); pass ``None`` to skip those.
    """
    cfg = config or Config()
    ctx = LintContext(decode(text, filename), cfg, external=external)
    diags = ctx.run(cfg.enabled_rules())
    return sorted(diags, key=lambda d: d.sort_key)


def lint_file(
    path: str, *, config: Optional[Config] = None, external: Optional[dict] = None
) -> list[Diagnostic]:
    """Read ``path`` and lint it."""
    with open(path, "rb") as f:
        data = f.read()
    return lint_text(data, path, config=config, external=external)
