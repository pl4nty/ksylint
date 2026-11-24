"""KSY1xx: JSON schema validation and encoding names."""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any

from ..encodings import canonical_encoding, is_canonical
from ..linter import LintContext
from ..registry import rule
from ..schema import schema, validator
from ..specs import ATTR, IDENT_RE, INSTANCE, META, META_NESTED, iter_specs
from ..yamldoc import Node


def _jsonable(o: Any) -> Any:
    if isinstance(o, dict):
        return {_key(k): _jsonable(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_jsonable(v) for v in o]
    return o


def _key(k: Any) -> str:
    if isinstance(k, bool):
        return "true" if k else "false"
    return str(k)


def _def_names() -> dict[int, str]:
    s = schema()
    out = {id(s): "top-level type"}
    for name, d in s["definitions"].items():
        out[id(d)] = name
    return out


_FRIENDLY = {
    "MetaSpec": "meta section",
    "TypeSpec": "type spec",
    "Attribute": "attribute",
    "ParamSpec": "parameter",
    "EnumValueSpec": "enum value",
    "ValidationSpec": "`valid` spec",
    "top-level type": "top-level type",
}


def _shorten(msg: str, limit: int = 160) -> str:
    msg = " ".join(msg.split())
    return msg if len(msg) <= limit else msg[: limit - 3] + "..."


def _flatten(err: Any) -> Iterator[Any]:
    """Pick the most relevant leaf errors for anyOf/oneOf failures."""
    from jsonschema.exceptions import best_match

    if err.validator in ("anyOf", "oneOf") and err.context:
        best = best_match(_relevant_alternatives(err.context))
        if best is not None:
            yield from _flatten(best)
            return
    yield err


def _relevant_alternatives(errors: list[Any]) -> list[Any]:
    """The errors of the alternatives of an anyOf/oneOf that come closest to
    matching. An alternative whose type does not even match (``X`` vs. a
    list of ``X``) is dropped, then the errors deepest in the instance win:
    they point at the actual problem (an item of a list, a key of a map)."""
    branches: dict[Any, list[Any]] = {}
    for e in errors:
        branches.setdefault(e.schema_path[0] if e.schema_path else None, []).append(e)
    kept = [
        e
        for errs in branches.values()
        if not any(x.validator == "type" and not x.relative_path for x in errs)
        for e in errs
    ] or errors
    depth = max(len(e.relative_path) for e in kept)
    return [e for e in kept if len(e.relative_path) == depth]


@rule(
    "KSY100",
    "schema",
    "error",
    "File must validate against the official KSY JSON schema.",
)
def schema_validation(ctx: LintContext) -> None:
    data = _jsonable(ctx.data)
    names = _def_names()
    seen: set[tuple] = set()
    for top in validator().iter_errors(data):
        for err in _flatten(top):
            path = list(err.absolute_path)
            node = ctx.doc.find_nearest(path)
            if _handled_elsewhere(ctx, err, path):
                continue
            if err.validator == "additionalProperties" and isinstance(err.instance, dict):
                where = _FRIENDLY.get(names.get(id(err.schema), ""), "this object")
                for k in _extra_keys(err):
                    if (tuple(path), k) in seen:
                        continue
                    seen.add((tuple(path), k))
                    if _is_ident_key_error(path, k):
                        continue
                    kn = node.key_node(_orig_key(node, k)) if node is not None else None
                    ctx.report(f"unknown key `{k}` in {where}", kn or node)
                continue
            key = (tuple(path), err.message)
            if key in seen:
                continue
            seen.add(key)
            loc = "/" + "/".join(str(p) for p in path) if path else "top level"
            ctx.report(f"{loc}: {_message(err)}", node)


def _message(err: Any) -> str:
    if err.validator == "not":
        req = err.validator_value.get("required") if isinstance(err.validator_value, dict) else None
        if req:
            return _shorten(f"key(s) {', '.join(f'`{k}`' for k in req)} not allowed here")
        return _shorten(f"value must not match {err.validator_value}")
    msg = err.message
    r = repr(err.instance)
    if len(r) > 40 and msg.startswith(r):
        msg = "value" + msg[len(r) :]
    return _shorten(msg)


def _orig_key(node: Node, k: str) -> Any:
    for kn, _ in node.items:
        if _key(kn.value) == k:
            return kn.value
    return k


def _extra_keys(err: Any) -> list[str]:
    props = err.schema.get("properties", {})
    pats = err.schema.get("patternProperties", {})
    return [k for k in err.instance if k not in props and not any(re.search(p, k) for p in pats)]


def _is_ident_key_error(path: list, k: str) -> bool:
    """Bad names of types/instances/enums are reported by KSY500."""
    return bool(path) and path[-1] in ("types", "instances", "enums") and not IDENT_RE.match(k)


def _handled_elsewhere(ctx: LintContext, err: Any, path: list) -> bool:
    # Encoding names: KSY101.
    if path and path[-1] == "encoding" and err.validator == "enum":
        return True
    # Identifier spelling: KSY500.
    inst = err.instance
    if isinstance(inst, str) and not IDENT_RE.match(inst):
        if path and path[-1] == "id":
            return True
        if len(path) >= 3 and path[-3] == "enums":
            return True
    return False


def _encodings(root: Node | None) -> Iterator[tuple[Node, str | None]]:
    """(``encoding`` scalar, canonical name or None) for every encoding that
    is not spelled canonically."""
    for spec in iter_specs(root):
        if spec.kind in (META, META_NESTED, ATTR, INSTANCE):
            n = spec.node.get("encoding")
            if n is not None and n.is_str and not is_canonical(n.value):
                yield n, canonical_encoding(n.value)


@rule(
    "KSY101",
    "encoding-name",
    "error",
    "Use canonical, byte-order-explicit encoding names (e.g. `UTF-8`, `ASCII`, `UTF-16LE`).",
    anchor="encoding-name",
    fixable=True,
)
def encoding_name(ctx: LintContext) -> None:
    for n, canon in _encodings(ctx.root):
        name = n.value
        if canon is not None:
            ctx.report(f"use canonical encoding name `{canon}` instead of `{name}`", n)
        elif re.sub(r"[-_]", "", name).upper() in ("UTF16", "UTF32", "UCS2", "UNICODE"):
            ctx.report(
                f"encoding `{name}` does not specify a byte order; use the BE or LE variant "
                f"(e.g. `UTF-16LE`)",
                n,
                fixable=False,
            )
        else:
            ctx.report(f"unknown encoding `{name}`", n, fixable=False)


def encoding_fixes(root: Node | None) -> list[tuple[Node, str]]:
    """(scalar node, canonical name) pairs for the autofixer."""
    return [(n, canon) for n, canon in _encodings(root) if canon is not None]


def _attrs(root: Node | None) -> Iterator[Node]:
    for spec in iter_specs(root):
        if spec.kind in (ATTR, INSTANCE):
            yield spec.node


@rule(
    "KSY102",
    "ineffective-pad-right",
    "warning",
    "`pad-right` has no effect without `size` or `size-eos: true`.",
)
def ineffective_pad_right(ctx: LintContext) -> None:
    # The compiler accepts `pad-right` with only a `terminator` but never
    # strips the padding: it reads up to the terminator and stops.
    for attr in _attrs(ctx.root):
        pad = attr.key_node("pad-right")
        if pad is None or attr.get("size") is not None:
            continue
        size_eos = attr.get("size-eos")
        if size_eos is not None and size_eos.value is True:
            continue
        ctx.report(
            "`pad-right` is ignored without `size` or `size-eos: true`; remove it or give a size",
            pad,
        )


@rule(
    "KSY103",
    "strz-terminator",
    "warning",
    "`type: strz` already implies `terminator: 0`; use `type: str` for other terminators.",
)
def strz_terminator(ctx: LintContext) -> None:
    # The compiler accepts `terminator` with `type: strz`; the explicit
    # terminator replaces the implied NUL.
    for attr in _attrs(ctx.root):
        t = attr.get("type")
        term = attr.get("terminator")
        if t is None or term is None or t.value != "strz":
            continue
        if term.value == 0:
            ctx.report(
                "`terminator: 0` is redundant with `type: strz`", attr.key_node("terminator")
            )
        else:
            ctx.report(
                f"`terminator: {term.raw}` overrides the NUL terminator implied by `type: strz`; "
                "use `type: str` with this terminator",
                attr.key_node("terminator"),
            )
