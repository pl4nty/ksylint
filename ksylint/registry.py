"""Rule registry.

Every rule has a stable ID (``KSYnnn``), a short kebab-case name, a default
severity, a one-line summary and (where applicable) an anchor into the
official KSY style guide. Rules register themselves with the :func:`rule`
decorator; importing :mod:`ksylint.rules` populates :data:`RULES`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable

from .diagnostic import Severity

if TYPE_CHECKING:
    from .linter import LintContext

STYLE_GUIDE_URL = "https://doc.kaitai.io/ksy_style_guide.html"


@dataclass(frozen=True)
class Rule:
    id: str
    name: str
    severity: Severity
    summary: str
    check: Callable[[LintContext], None] = field(compare=False, repr=False)
    anchor: str | None = None
    fixable: bool = False
    #: "text" rules run even when the YAML cannot be parsed.
    needs: str = "yaml"
    #: Rules that are not enabled unless explicitly selected (or by a mode).
    default_enabled: bool = True
    options: dict[str, Any] = field(default_factory=dict, compare=False)

    @property
    def url(self) -> str | None:
        if self.anchor is None:
            return None
        return f"{STYLE_GUIDE_URL}#{self.anchor}"

    @property
    def category(self) -> str:
        return CATEGORIES.get(self.id[:4], "Other")


CATEGORIES = {
    "KSY0": "File format and layout",
    "KSY1": "Schema",
    "KSY2": "Meta section",
    "KSY3": "Key order",
    "KSY4": "Documentation",
    "KSY5": "Naming",
    "KSY6": "References",
    "KSY9": "Compiler",
}

RULES: dict[str, Rule] = {}
_BY_NAME: dict[str, Rule] = {}


def rule(
    id: str,
    name: str,
    severity: str,
    summary: str,
    *,
    anchor: str | None = None,
    fixable: bool = False,
    needs: str = "yaml",
    default_enabled: bool = True,
    options: dict[str, Any] | None = None,
) -> Callable[[Callable[[LintContext], None]], Callable[[LintContext], None]]:
    """Register a rule check function."""

    def deco(fn: Callable[[LintContext], None]) -> Callable[[LintContext], None]:
        if id in RULES:
            raise ValueError(f"duplicate rule id {id}")
        if name in _BY_NAME:
            raise ValueError(f"duplicate rule name {name}")
        r = Rule(
            id=id,
            name=name,
            severity=Severity.parse(severity),
            summary=summary,
            check=fn,
            anchor=anchor,
            fixable=fixable,
            needs=needs,
            default_enabled=default_enabled,
            options=dict(options or {}),
        )
        RULES[id] = r
        _BY_NAME[name] = r
        return fn

    return deco


def get_rule(key: str) -> Rule:
    """Look a rule up by ID (case-insensitive) or name."""
    _ensure_loaded()
    r = RULES.get(key.upper()) or _BY_NAME.get(key.lower())
    if r is None:
        raise KeyError(key)
    return r


def resolve_selector(selector: str) -> list[Rule]:
    """Resolve a selector to rules.

    A selector is a full rule ID (``KSY300``), an ID prefix (``KSY3``,
    ``KSY``), a rule name (``type-key-order``) or ``ALL``.
    """
    _ensure_loaded()
    s = selector.strip()
    if not s:
        return []
    if s.upper() == "ALL":
        return list(RULES.values())
    if s.lower() in _BY_NAME:
        return [_BY_NAME[s.lower()]]
    up = s.upper()
    matched = [r for rid, r in RULES.items() if rid.startswith(up)]
    if not matched:
        raise KeyError(selector)
    return matched


def all_rules() -> list[Rule]:
    _ensure_loaded()
    return sorted(RULES.values(), key=lambda r: r.id)


def _ensure_loaded() -> None:
    from . import rules  # noqa: F401  (import registers rules)
