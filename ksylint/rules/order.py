"""KSY3xx: key order inside spec objects (never inside user-named maps)."""

from __future__ import annotations

from typing import Optional

from .. import specs
from ..linter import LintContext
from ..registry import rule
from ..yamldoc import Node


def misordered(node: Node, order: dict[str, int]) -> Optional[tuple[Node, Node, list[str]]]:
    """Return (offending key node, key it should precede, expected order of
    ranked keys) for the first ordering violation, or None."""
    ranked = [(k, order[k.value]) for k, _ in node.items if not specs.free_key(k.value, order)]
    best: Optional[tuple[Node, int]] = None
    for k, r in ranked:
        if best is not None and r < best[1]:
            # find the first key that has a higher rank than k
            first_higher = next(kk for kk, rr in ranked if rr > r)
            expected = [str(kk.value) for kk, _ in sorted(ranked, key=lambda t: t[1])]
            return k, first_higher, expected
        if best is None or r > best[1]:
            best = (k, r)
    return None


def sorted_positions(node: Node, order: dict[str, int]) -> list[int]:
    """New order of item indices: ranked keys sorted (stable) into the slots
    that ranked keys occupy; free keys keep their slots."""
    idx = list(range(len(node.items)))
    slots = [i for i in idx if not specs.free_key(node.items[i][0].value, order)]
    ranked = sorted(slots, key=lambda i: order[node.items[i][0].value])
    out = idx[:]
    for slot, src in zip(slots, ranked):
        out[slot] = src
    return out


def _check(ctx: LintContext, kinds: tuple[str, ...], what: str) -> None:
    for spec in specs.iter_specs(ctx.root):
        if spec.kind not in kinds or spec.node.flow:
            continue
        res = misordered(spec.node, specs.ORDERS[spec.kind])
        if res is None:
            continue
        k, before, expected = res
        ctx.report(
            f"{what}: `{k.raw}` should come before `{before.raw}` (expected order: {', '.join(expected)})",
            k,
            path=spec.node.ptr,
        )


@rule(
    "KSY300",
    "type-key-order",
    "error",
    "Sections of a type spec must follow the style guide order.",
    anchor="type",
    fixable=True,
)
def type_key_order(ctx: LintContext) -> None:
    _check(ctx, (specs.TYPE,), "type spec key order")


@rule(
    "KSY301",
    "meta-key-order",
    "error",
    "Keys of a meta section must follow the style guide order.",
    anchor="meta",
    fixable=True,
)
def meta_key_order(ctx: LintContext) -> None:
    _check(ctx, (specs.META, specs.META_NESTED), "meta key order")


@rule(
    "KSY302",
    "attribute-key-order",
    "error",
    "Keys of a sequence attribute must follow the style guide order.",
    anchor="seq-attr",
    fixable=True,
)
def attribute_key_order(ctx: LintContext) -> None:
    _check(ctx, (specs.ATTR,), "attribute key order")


@rule(
    "KSY303",
    "instance-key-order",
    "error",
    "Keys of an instance must follow the style guide order.",
    anchor="inst-attr",
    fixable=True,
)
def instance_key_order(ctx: LintContext) -> None:
    _check(ctx, (specs.INSTANCE,), "instance key order")


@rule(
    "KSY304",
    "param-key-order",
    "warning",
    "Keys of a parameter spec should be ordered id, type, enum, doc, doc-ref.",
    fixable=True,
)
def param_key_order(ctx: LintContext) -> None:
    _check(ctx, (specs.PARAM,), "parameter key order")


@rule(
    "KSY305",
    "enum-value-key-order",
    "warning",
    "Keys of an enum value spec should be ordered id, -orig-id, doc, doc-ref.",
    fixable=True,
)
def enum_value_key_order(ctx: LintContext) -> None:
    _check(ctx, (specs.ENUM_VALUE,), "enum value key order")


@rule(
    "KSY306",
    "switch-key-order",
    "warning",
    "A switch type should list `switch-on` before `cases`.",
    fixable=True,
)
def switch_key_order(ctx: LintContext) -> None:
    _check(ctx, (specs.SWITCH,), "switch key order")
