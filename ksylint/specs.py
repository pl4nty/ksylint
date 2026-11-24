"""Knowledge about .ksy structure: which YAML maps are *spec objects*
(and therefore subject to key-ordering rules) and the canonical key orders
from the KSY style guide.

User-named maps (the keys of ``types``, ``instances``, ``enums``, an enum's
values, switch ``cases``, ``xref``) are never key-ordered.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Optional

from .yamldoc import Node

#: lower_snake_case identifier (ids and type, instance and enum names).
IDENT_RE = re.compile(r"^[a-z][a-z0-9_]*$")

# Spec kinds
TYPE = "type"
META = "meta"
META_NESTED = "meta-nested"
ATTR = "attr"
INSTANCE = "instance"
PARAM = "param"
ENUM = "enum"
ENUM_VALUE = "enum-value"
SWITCH = "switch"
XREF = "xref"


def _ranks(groups: list) -> dict[str, int]:
    """Build a rank table: each group element is a key or a tuple of keys
    that share a rank (may appear in either order)."""
    out: dict[str, int] = {}
    for i, g in enumerate(groups):
        for k in g if isinstance(g, tuple) else (g,):
            out[k] = i * 10
    return out


#: Style guide, "Order of sections in a type spec".
TYPE_ORDER = _ranks(
    ["meta", "doc", "doc-ref", "to-string", "params", "seq", "instances", ("types", "enums")]
)

#: Style guide, "Meta section" (top level). ks-debug / ks-opaque-types are
#: reserved (and reported by their own rule); placed after imports.
META_ORDER = _ranks(
    [
        "id",
        "title",
        "application",
        "file-extension",
        "xref",
        "tags",
        "license",
        "ks-version",
        "imports",
        ("ks-debug", "ks-opaque-types"),
        "encoding",
        "endian",
        "bit-endian",
    ]
)

#: Keys allowed in an intermediate (nested) meta section.
META_NESTED_KEYS = ("encoding", "endian", "bit-endian")

#: Style guide, "Sequence attributes".
ATTR_SEQUENCE = [
    "id",
    "-orig-id",
    "size",
    "size-eos",
    "type",
    "enum",
    "terminator",
    "include",
    "consume",
    "eos-error",
    "pad-right",
    "encoding",
    "process",
    ("valid", "contents"),
    "repeat",
    ("repeat-expr", "repeat-until"),
    "if",
    "doc",
    "doc-ref",
]
ATTR_ORDER = _ranks(ATTR_SEQUENCE)

#: Style guide, "Instance attributes": -orig-id, io, pos/value, then the
#: sequence-attribute order (minus id and -orig-id).
INSTANCE_ORDER = _ranks(
    ["-orig-id", "io", ("pos", "value")] + [k for k in ATTR_SEQUENCE if k not in ("id", "-orig-id")]
)

#: Not covered by the style guide; derived from the attribute order.
PARAM_ORDER = _ranks(["id", "type", "enum", "doc", "doc-ref"])
ENUM_VALUE_ORDER = _ranks(["id", "-orig-id", "doc", "doc-ref"])
SWITCH_ORDER = _ranks(["switch-on", "cases"])

ORDERS = {
    TYPE: TYPE_ORDER,
    META: META_ORDER,
    META_NESTED: META_ORDER,
    ATTR: ATTR_ORDER,
    INSTANCE: INSTANCE_ORDER,
    PARAM: PARAM_ORDER,
    ENUM_VALUE: ENUM_VALUE_ORDER,
    SWITCH: SWITCH_ORDER,
}


@dataclass
class Spec:
    kind: str
    node: Node
    #: For TYPE: True for the top-level type.
    top: bool = False
    #: For TYPE/ENUM/INSTANCE: the user-given name (None for the root type).
    name: Optional[str] = None


def iter_specs(root: Optional[Node]) -> Iterator[Spec]:
    """Yield every spec object in the document (pre-order)."""
    if root is None or not root.is_map:
        return
    yield from _walk_type(root, top=True, name=None)


def _walk_type(node: Node, top: bool, name: Optional[str]) -> Iterator[Spec]:
    yield Spec(TYPE, node, top=top, name=name)
    meta = node.get("meta")
    if meta is not None and meta.is_map:
        yield Spec(META if top else META_NESTED, meta, top=top)
        xref = meta.get("xref")
        if xref is not None and xref.is_map:
            yield Spec(XREF, xref)
    params = node.get("params")
    if params is not None and params.is_seq:
        for p in params.items:
            if p.is_map:
                yield Spec(PARAM, p)
    seq = node.get("seq")
    if seq is not None and seq.is_seq:
        for a in seq.items:
            if a.is_map:
                yield from _walk_attr(a, ATTR)
    inst = node.get("instances")
    if inst is not None and inst.is_map:
        for k, v in inst.items:
            if v.is_map:
                yield from _walk_attr(v, INSTANCE, name=k.value)
    types = node.get("types")
    if types is not None and types.is_map:
        for k, v in types.items:
            if v.is_map:
                yield from _walk_type(v, top=False, name=k.value)
    enums = node.get("enums")
    if enums is not None and enums.is_map:
        for k, v in enums.items:
            if v.is_map:
                yield Spec(ENUM, v, name=k.value)
                for _ek, ev in v.items:
                    if ev.is_map:
                        yield Spec(ENUM_VALUE, ev)


def _walk_attr(node: Node, kind: str, name: Optional[str] = None) -> Iterator[Spec]:
    yield Spec(kind, node, name=name)
    t = node.get("type")
    if t is not None and t.is_map:
        yield Spec(SWITCH, t)


def free_key(key: object, order: dict[str, int]) -> bool:
    """Keys that are not ranked (unknown keys and ``-`` extension keys other
    than ``-orig-id``) may appear anywhere."""
    return not isinstance(key, str) or key not in order
