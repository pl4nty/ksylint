"""Fixture-per-rule tests.

``fixtures/rules/<RULE>/invalid/*.ksy`` must trigger <RULE>;
``fixtures/rules/<RULE>/valid/*.ksy`` must produce no diagnostics at all.
"""

import pytest
from conftest import RULE_FIXTURES

import ksylint

CASES = sorted(p for p in RULE_FIXTURES.glob("*/*/*") if p.is_file())


def _id(p):
    return f"{p.parts[-3]}-{p.parts[-2]}-{p.stem}"


@pytest.mark.parametrize("path", CASES, ids=_id)
def test_rule_fixture(path, all_rules_config):
    rule_id, kind = path.parts[-3], path.parts[-2]
    diags = ksylint.lint_file(str(path), config=all_rules_config)
    ids = {d.rule_id for d in diags}
    if kind == "invalid":
        assert rule_id in ids, f"{rule_id} not reported; got {[str(d) for d in diags]}"
    else:
        assert not diags, [str(d) for d in diags]


def test_every_rule_has_an_invalid_fixture():
    have = {p.parts[-3] for p in RULE_FIXTURES.glob("*/invalid/*")}
    missing = [
        r.id for r in ksylint.all_rules() if r.id not in have and not r.id.startswith("KSY9")
    ]
    assert not missing, f"rules without an invalid fixture: {missing}"


def test_invalid_fixtures_select_only_their_rule():
    """Selecting only the rule under test still reports it (no hidden
    dependency on other rules)."""
    for path in sorted(RULE_FIXTURES.glob("*/invalid/*")):
        rule_id = path.parts[-3]
        diags = ksylint.lint_file(str(path), config=ksylint.Config(select=[rule_id]))
        assert {d.rule_id for d in diags} == {rule_id}, path


def test_registry_metadata():
    rules = ksylint.all_rules()
    ids = [r.id for r in rules]
    assert len(ids) == len(set(ids))
    for r in rules:
        assert r.id.startswith("KSY") and len(r.id) == 6
        assert r.name == r.name.lower() and " " not in r.name
        assert r.summary.endswith(".")
        if r.anchor:
            assert r.url.startswith("https://doc.kaitai.io/ksy_style_guide.html#")


def test_positions_and_paths():
    text = (
        "meta:\n  id: pos\n  title: T\n  license: CC0-1.0\n"
        "seq:\n  - id: one\n    type: str\n    size: 4\n    encoding: ascii\n"
    )
    diags = {d.rule_id: d for d in ksylint.lint_text(text, "pos.ksy")}
    enc = diags["KSY101"]
    assert (enc.line, enc.column) == (9, 15)
    assert enc.path == "/seq/0/encoding"
    order = diags["KSY302"]
    assert (order.line, order.column) == (8, 5)
    assert order.path == "/seq/0"
    assert order.fixable


def test_old_fixtures():
    from conftest import HERE

    for p in sorted((HERE / "valid").glob("*")):
        assert ksylint.lint_file(str(p)) == [], p
    for p in sorted((HERE / "invalid").glob("*")):
        assert [d for d in ksylint.lint_file(str(p)) if d.severity.value == "error"], p


def test_legacy_lint_module(capsys):
    from conftest import HERE

    from ksylint import lint

    assert lint.lint_file(str(HERE / "valid" / "hello_world.ksy")) == 0
    assert lint.lint_file(str(HERE / "invalid" / "no_newline.ksy")) > 0
