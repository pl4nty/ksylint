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
from collections.abc import Iterable
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
        for key in (r.id, r.name):
            if key in self.severity:
                return Severity.parse(self.severity[key])
        return r.severity

    def options_for(self, r: Rule) -> dict[str, Any]:
        out = dict(r.options)
        for key in (r.id, r.name):
            out.update(self.rule_options.get(key, {}))
        return out

    def validate(self) -> None:
        for s in [*(self.select or []), *self.ignore, *self.extend_select]:
            _resolve(s)
        for k, v in self.severity.items():
            _resolve(k)
            Severity.parse(v)
        Severity.parse(self.fail_on)
        for k in self.rule_options:
            try:
                get_rule(k)
            except KeyError:
                raise ConfigError(f"unknown rule {k!r} in rule options") from None


def _resolve(selector: str) -> list[Rule]:
    try:
        return resolve_selector(selector)
    except KeyError:
        raise ConfigError(f"unknown rule selector {selector!r}") from None


_KEYMAP = {
    "select": "select",
    "ignore": "ignore",
    "extend-select": "extend_select",
    "severity": "severity",
    "rules": "rule_options",
    "fail-on": "fail_on",
    "exclude": "exclude",
    "compile": "compile",
    "ksc": "ksc",
    "ksc-target": "ksc_target",
    "import-paths": "import_paths",
}


def config_from_mapping(data: dict[str, Any], source: Optional[str] = None) -> Config:
    cfg = Config(source=source)
    for k, v in data.items():
        attr = _KEYMAP.get(k) or _KEYMAP.get(k.replace("_", "-"))
        if attr is None:
            raise ConfigError(
                f"unknown configuration key {k!r}" + (f" in {source}" if source else "")
            )
        if attr in ("select", "ignore", "extend_select", "exclude", "import_paths"):
            v = _as_list(v, k)
        setattr(cfg, attr, v)
    if source and cfg.import_paths:
        base = Path(source).parent
        cfg.import_paths = [str((base / p).resolve()) for p in cfg.import_paths]
    cfg.validate()
    return cfg


def _as_list(v: Any, key: str) -> list[str]:
    if isinstance(v, str):
        return [s.strip() for s in v.split(",") if s.strip()]
    if isinstance(v, Iterable):
        return [str(s) for s in v]
    raise ConfigError(f"{key} must be a list of strings")


def load_config_file(path: str | os.PathLike) -> Config:
    p = Path(path)
    with p.open("rb") as f:
        try:
            data = tomllib.load(f)
        except tomllib.TOMLDecodeError as e:
            raise ConfigError(f"{p}: {e}") from None
    if p.name == "pyproject.toml":
        data = data.get("tool", {}).get("ksylint", {})
    return config_from_mapping(data, source=str(p))


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
