"""Configuration.

Configuration is read from (first match, searching upwards from the current
directory): ``.ksylint.toml`` (top-level keys) or ``pyproject.toml``
(``[tool.ksylint]`` table). Example::

    [tool.ksylint]
    select = ["ALL"]             # rule IDs, ID prefixes or names
    ignore = ["KSY601"]
    fail-on = "warning"          # error | warning | info
    exclude = ["_build/**"]
    compile = false              # also run ksc (KSY900/KSY901)
    ksc = "kaitai-struct-compiler"
    import-paths = ["."]

    [tool.ksylint.severity]
    KSY600 = "info"

    [tool.ksylint.rules.doc-line-length]
    max-length = 100
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .diagnostic import Severity
from .registry import Rule, all_rules, get_rule, resolve_selector

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib


class ConfigError(ValueError):
    pass


@dataclass
class Config:
    select: Optional[list[str]] = None
    ignore: list[str] = field(default_factory=list)
    extend_select: list[str] = field(default_factory=list)
    severity: dict[str, str] = field(default_factory=dict)
    rule_options: dict[str, dict[str, Any]] = field(default_factory=dict)
    fail_on: str = "warning"
    exclude: list[str] = field(default_factory=list)
    compile: bool = False
    ksc: str = "kaitai-struct-compiler"
    ksc_target: str = "python"
    import_paths: list[str] = field(default_factory=list)
    source: Optional[str] = None

    # -- resolution --------------------------------------------------------
    def enabled_rules(self) -> list[Rule]:
        rules = all_rules()
        if self.select is None:
            enabled = {r.id for r in rules if r.default_enabled}
        else:
            enabled = set()
            for s in self.select:
                enabled |= {r.id for r in _resolve(s)}
        for s in self.extend_select:
            enabled |= {r.id for r in _resolve(s)}
        if self.compile:
            enabled |= {r.id for r in rules if r.id.startswith("KSY9")}
        for s in self.ignore:
            enabled -= {r.id for r in _resolve(s)}
        return [r for r in rules if r.id in enabled]

    def severity_of(self, r: Rule) -> Severity:
        """Severity of ``r``; the most specific matching selector wins."""
        best: Optional[tuple[int, str]] = None
        for selector, severity in self.severity.items():
            matched = _resolve(selector)
            if r in matched and (best is None or len(matched) < best[0]):
                best = (len(matched), severity)
        return Severity.parse(best[1]) if best else r.severity

    def options_for(self, r: Rule) -> dict[str, Any]:
        out = dict(r.options)
        for key, options in self.rule_options.items():
            if _rule(key) is r:
                out.update(options)
        return out

    def validate(self) -> None:
        for s in [*(self.select or []), *self.ignore, *self.extend_select]:
            _resolve(s)
        for k, v in self.severity.items():
            _resolve(k)
            Severity.parse(v)
        Severity.parse(self.fail_on)
        for k, options in self.rule_options.items():
            r = _rule(k)
            if not isinstance(options, dict):
                raise ConfigError(f"options of rule {k!r} must be a table")
            for name, value in options.items():
                if name not in r.options:
                    raise ConfigError(f"rule {r.id} ({r.name}) has no option {name!r}")
                expected = type(r.options[name])
                if type(value) is not expected:
                    raise ConfigError(
                        f"option {name!r} of rule {r.id} must be of type {expected.__name__}"
                    )


def _resolve(selector: str) -> list[Rule]:
    try:
        return resolve_selector(selector)
    except KeyError:
        raise ConfigError(f"unknown rule selector {selector!r}") from None


def _rule(key: str) -> Rule:
    try:
        return get_rule(key)
    except KeyError:
        raise ConfigError(f"unknown rule {key!r} in rule options") from None


#: Configuration file key -> (Config attribute, type).
_KEYS: dict[str, tuple[str, type]] = {
    "select": ("select", list),
    "ignore": ("ignore", list),
    "extend-select": ("extend_select", list),
    "severity": ("severity", dict),
    "rules": ("rule_options", dict),
    "fail-on": ("fail_on", str),
    "exclude": ("exclude", list),
    "compile": ("compile", bool),
    "ksc": ("ksc", str),
    "ksc-target": ("ksc_target", str),
    "import-paths": ("import_paths", list),
}
_TYPE_NAMES = {list: "list of strings", dict: "table", str: "string", bool: "boolean"}


def config_from_mapping(data: dict[str, Any], source: Optional[str] = None) -> Config:
    """Build a validated :class:`Config` from parsed TOML. ``source`` is the
    path of the file it came from (relative ``import-paths`` resolve against
    its directory)."""
    if not isinstance(data, dict):
        raise ConfigError("configuration must be a table")
    cfg = Config(source=source)
    for k, v in data.items():
        attr, typ = _KEYS.get(str(k).replace("_", "-"), (None, None))
        if attr is None:
            raise ConfigError(f"unknown configuration key {k!r}")
        if typ is list and isinstance(v, str):
            v = [s.strip() for s in v.split(",") if s.strip()]
        if not isinstance(v, typ) or (typ is list and not all(isinstance(s, str) for s in v)):
            raise ConfigError(f"{k} must be a {_TYPE_NAMES[typ]}")
        setattr(cfg, attr, v)
    if source and cfg.import_paths:
        base = Path(source).parent
        cfg.import_paths = [str((base / p).resolve()) for p in cfg.import_paths]
    cfg.validate()
    return cfg


def load_config_file(path: str | os.PathLike) -> Config:
    p = Path(path)
    with p.open("rb") as f:
        try:
            data = tomllib.load(f)
        except tomllib.TOMLDecodeError as e:
            raise ConfigError(f"{p}: {e}") from None
    if p.name == "pyproject.toml":
        data = data.get("tool", {}).get("ksylint", {})
    try:
        return config_from_mapping(data, source=str(p))
    except ValueError as e:
        raise ConfigError(f"{p}: {e}") from None


def find_config(start: str | os.PathLike | None = None) -> Optional[Path]:
    d = Path(start or os.getcwd()).resolve()
    for cand_dir in [d, *d.parents]:
        dot = cand_dir / ".ksylint.toml"
        if dot.is_file():
            return dot
        pp = cand_dir / "pyproject.toml"
        if pp.is_file():
            try:
                with pp.open("rb") as f:
                    if "ksylint" in tomllib.load(f).get("tool", {}):
                        return pp
            except (OSError, tomllib.TOMLDecodeError):
                pass
    return None


def load_config(
    path: str | os.PathLike | None = None, start: str | os.PathLike | None = None
) -> Config:
    if path is not None:
        return load_config_file(path)
    found = find_config(start)
    return load_config_file(found) if found else Config()
