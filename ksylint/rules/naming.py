"""KSY5xx naming and KSY6xx reference rules."""

from __future__ import annotations

import re
from collections.abc import Iterator

from .. import specs
from ..linter import LintContext
from ..registry import rule
from ..specs import IDENT_RE
from ..yamldoc import Node

_ID_KINDS = {
    specs.ATTR: "attribute id",
    specs.PARAM: "parameter id",
    specs.ENUM_VALUE: "enum value id",
}


def _identifiers(ctx: LintContext) -> Iterator[tuple[str, Node]]:
    root = ctx.root
    meta = root.get("meta")
    if meta is not None and meta.is_map:
        n = meta.get("id")
        if n is not None and n.is_str:
            yield "meta/id", n
    for spec in specs.iter_specs(root):
        node = spec.node
        if spec.kind == specs.TYPE:
            for section, what in (
                ("types", "type name"),
                ("instances", "instance name"),
                ("enums", "enum name"),
            ):
                sec = node.get(section)
                if sec is not None and sec.is_map:
                    for k, _ in sec.items:
                        yield what, k
        elif spec.kind in _ID_KINDS:
            n = node.get("id")
            if n is not None and n.is_str:
                yield _ID_KINDS[spec.kind], n
        elif spec.kind == specs.ENUM:
            for _k, v in node.items:
                if v.is_str:
                    yield "enum value id", v


@rule(
    "KSY500",
    "identifier-case",
    "error",
    "Identifiers (ids, type, enum and instance names) must be lower_snake_case.",
    anchor="attr-id",
)
def identifier_case(ctx: LintContext) -> None:
    for what, n in _identifiers(ctx):
        name = n.value if isinstance(n.value, str) else n.raw
        if not IDENT_RE.match(str(name)):
            ctx.report(f"{what} `{name}` must be lower_snake_case (`{_suggest(str(name))}`)", n)


def _suggest(name: str) -> str:
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name)
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", s)
    s = re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_").lower()
    if not s or not s[0].isalpha():
        s = "x_" + s
    return s


# ---------------------------------------------------------------------------
# references

_CAST_RE = re.compile(r"\b(?:as|sizeof|bitsizeof)\s*<\s*([A-Za-z0-9_:\[\]]+)\s*>")
_ENUM_USE_RE = re.compile(r"\b([a-z][a-z0-9_]*)::")


def _type_ref_names(s: str) -> set[str]:
    s = s.split("(", 1)[0].strip()
    s = s.replace("[]", "")
    return {p for p in s.split("::") if p}


def _all_strings(node: Node) -> Iterator[str]:
    for n in node.walk():
        if n.is_str:
            yield n.value
        if n.is_map:
            for k, _ in n.items:
                if isinstance(k.value, str):
                    yield k.value


def _used_names(ctx: LintContext) -> tuple[set[str], set[str]]:
    cache = ctx.cache.get("used_names")
    if cache is not None:
        return cache
    types: set[str] = set()
    enums: set[str] = set()
    for spec in specs.iter_specs(ctx.root):
        node = spec.node
        if spec.kind in (specs.ATTR, specs.INSTANCE, specs.PARAM):
            t = node.get("type")
            if t is not None and t.is_str:
                types |= _type_ref_names(t.value)
            e = node.get("enum")
            if e is not None and e.is_str:
                enums |= _type_ref_names(e.value)
        elif spec.kind == specs.SWITCH:
            cases = node.get("cases")
            if cases is not None and cases.is_map:
                for _k, v in cases.items:
                    if v.is_str:
                        types |= _type_ref_names(v.value)
    for s in _all_strings(ctx.root):
        for m in _CAST_RE.finditer(s):
            types |= _type_ref_names(m.group(1))
        for m in _ENUM_USE_RE.finditer(s):
            enums.add(m.group(1))
            types.add(m.group(1))
    ctx.cache["used_names"] = (types, enums)
    return types, enums


@rule(
    "KSY600",
    "unused-type",
    "warning",
    "Types that are defined but never referenced.",
)
def unused_type(ctx: LintContext) -> None:
    used, _ = _used_names(ctx)
    for spec in specs.iter_specs(ctx.root):
        if spec.kind != specs.TYPE:
            continue
        sec = spec.node.get("types")
        if sec is None or not sec.is_map:
            continue
        for k, _ in sec.items:
            if isinstance(k.value, str) and k.value not in used:
                ctx.report(f"type `{k.value}` is never used", k)


@rule(
    "KSY601",
    "unused-enum",
    "warning",
    "Enums that are defined but never referenced.",
)
def unused_enum(ctx: LintContext) -> None:
    _, used = _used_names(ctx)
    for spec in specs.iter_specs(ctx.root):
        if spec.kind != specs.TYPE:
            continue
        sec = spec.node.get("enums")
        if sec is None or not sec.is_map:
            continue
        for k, _ in sec.items:
            if isinstance(k.value, str) and k.value not in used:
                ctx.report(f"enum `{k.value}` is never used", k)
