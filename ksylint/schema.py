"""Loading the vendored official KSY JSON schema."""

from __future__ import annotations

import copy
import functools
import json
from dataclasses import dataclass
from importlib import resources
from typing import Any

#: The ``process`` values kaitai-struct-compiler 0.11 accepts: a built-in
#: (``zlib``, ``xor(key)``, ``rol(n)``, ``ror(n)``) or a custom processor,
#: i.e. a (possibly dotted) lower-case name with an optional, non-empty
#: argument list (``kaitai.compress.zlib(15, "raw")``, ``my_rle``). This is
#: the shape the compiler checks before it parses the arguments; it rejects
#: ``Foo``, ``_foo``, ``foo-bar``, ``foo()`` and ``foo(1) x``. Multi-line
#: plain scalars are folded into one line by YAML before this applies.
PROCESS_PATTERN = r"^[a-z][a-z0-9_.]*(\(.+\))?$"

_OFFICIAL_PROCESS_PATTERN = r"^zlib|(xor|rol|ror)\(.*\)$"


@dataclass(frozen=True)
class SchemaPatch:
    """A correction applied on top of the vendored schema.

    ``parent[key]`` (``parent`` given as a JSON pointer) is set to ``new``,
    or deleted if ``new`` is :data:`DELETE`. ``old`` is the value the patch
    expects to find (:data:`MISSING` if the key must not exist yet): a
    refreshed schema that no longer needs, or no longer fits, a patch makes
    :func:`schema` fail instead of silently applying it somewhere else.
    """

    parent: str
    key: str | int
    old: Any
    new: Any
    reason: str


MISSING = object()
DELETE = object()

SCHEMA_PATCHES: list[SchemaPatch] = [
    SchemaPatch(
        "/definitions/Attribute/properties",
        "parent",
        MISSING,
        {"type": "string"},
        "`parent` (override `_parent` of the created object) is accepted by "
        "the compiler (0.11) but missing from the schema",
    ),
    SchemaPatch(
        "/definitions/Attribute/properties/process",
        "pattern",
        _OFFICIAL_PROCESS_PATTERN,
        PROCESS_PATTERN,
        "the official pattern only allows `zlib`, `xor(...)`, `rol(...)` and "
        "`ror(...)`, but the compiler (0.11) also accepts custom processors "
        "such as `kaitai.compress.lz4` or `my_rle(5, 2)`",
    ),
    # The two conditions below describe specs that the compiler (0.11)
    # accepts; KSY102 and KSY103 report them with a clearer message.
    SchemaPatch(
        "/definitions/Attribute/allOf",
        1,
        {
            "if": {"required": ["pad-right"]},
            "then": {
                "anyOf": [
                    {"required": ["size"]},
                    {"required": ["size-eos"], "properties": {"size-eos": {"const": True}}},
                ]
            },
        },
        DELETE,
        "`pad-right` without `size`/`size-eos` is accepted (and ignored) by "
        "the compiler (0.11); reported by KSY102",
    ),
    SchemaPatch(
        "/definitions/Attribute/allOf",
        0,
        {
            "if": {"required": ["type"], "properties": {"type": {"const": "strz"}}},
            "then": {"not": {"required": ["terminator"]}},
        },
        DELETE,
        "`terminator` with `type: strz` is accepted by the compiler (0.11) and "
        "overrides the implied NUL terminator; reported by KSY103",
    ),
]


def _resolve_pointer(doc: Any, ptr: str) -> Any:
    cur = doc
    for seg in ptr.strip("/").split("/"):
        seg = seg.replace("~1", "/").replace("~0", "~")
        cur = cur[int(seg)] if isinstance(cur, list) else cur[seg]
    return cur


def apply_patch(s: dict, p: SchemaPatch) -> None:
    parent = _resolve_pointer(s, p.parent)
    if isinstance(parent, list):
        present = isinstance(p.key, int) and 0 <= p.key < len(parent)
    else:
        present = p.key in parent
    cur = parent[p.key] if present else MISSING
    if cur is not p.old and cur != p.old:
        raise RuntimeError(f"schema patch for {p.parent}/{p.key} no longer applies: {p.reason}")
    if p.new is DELETE:
        del parent[p.key]
    else:
        parent[p.key] = p.new


@functools.lru_cache(maxsize=1)
def raw_schema() -> dict:
    data = resources.files("ksylint").joinpath("data/ksy_schema.json").read_text(encoding="utf-8")
    return json.loads(data)


@functools.lru_cache(maxsize=1)
def schema() -> dict:
    s = copy.deepcopy(raw_schema())
    # Deleting list items shifts later ones, so the patches are listed with
    # the higher index first.
    for p in SCHEMA_PATCHES:
        apply_patch(s, p)
    return s


@functools.lru_cache(maxsize=1)
def validator() -> Any:
    from jsonschema import Draft7Validator

    return Draft7Validator(schema())


def canonical_encodings() -> list[str]:
    return list(schema()["definitions"]["CharacterEncoding"]["enum"])
