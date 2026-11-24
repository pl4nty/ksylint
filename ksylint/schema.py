"""Loading the vendored official KSY JSON schema."""

from __future__ import annotations

import copy
import functools
import json
from importlib import resources
from typing import Any

#: Corrections applied on top of the vendored schema. Each entry is
#: (JSON-pointer to an object's ``properties``, key, sub-schema, reason).
SCHEMA_PATCHES: list[tuple[str, str, dict, str]] = [
    (
        "/definitions/Attribute/properties",
        "parent",
        {"type": "string"},
        "`parent` (override `_parent` of the created object) is accepted by "
        "the compiler (0.11) but missing from the schema",
    ),
]


def _resolve_pointer(doc: Any, ptr: str) -> Any:
    cur = doc
    for seg in ptr.strip("/").split("/"):
        cur = cur[seg.replace("~1", "/").replace("~0", "~")]
    return cur


@functools.lru_cache(maxsize=1)
def raw_schema() -> dict:
    data = resources.files("ksylint").joinpath("data/ksy_schema.json").read_text(encoding="utf-8")
    return json.loads(data)


@functools.lru_cache(maxsize=1)
def schema() -> dict:
    s = copy.deepcopy(raw_schema())
    for ptr, key, sub, _why in SCHEMA_PATCHES:
        _resolve_pointer(s, ptr).setdefault(key, sub)
    return s


@functools.lru_cache(maxsize=1)
def validator() -> Any:
    from jsonschema import Draft7Validator

    return Draft7Validator(schema())


def canonical_encodings() -> list[str]:
    return list(schema()["definitions"]["CharacterEncoding"]["enum"])
