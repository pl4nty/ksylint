import pathlib

import pytest
import yaml
from conftest import FIX_FIXTURES, FORMATS, RULE_FIXTURES

import ksylint

FIX_CASES = sorted(p for p in FIX_FIXTURES.glob("*.ksy") if not p.name.endswith(".expected.ksy"))


@pytest.mark.parametrize("path", FIX_CASES, ids=lambda p: p.stem)
def test_fix_expected(path):
    expected = path.with_name(path.stem + ".expected.ksy").read_bytes().decode("utf-8")
    res = ksylint.fix_text(path.read_bytes(), str(path))
    assert res.text == expected
    assert res.changed and not res.skipped


ALL_INPUTS = sorted(RULE_FIXTURES.glob("*/*/*.ksy")) + FIX_CASES + sorted(FORMATS.glob("*.ksy"))


def _id(p: pathlib.Path) -> str:
    return "-".join(p.parts[-3:])


@pytest.mark.parametrize("path", ALL_INPUTS, ids=_id)
def test_fix_idempotent_and_semantics_preserving(path):
    raw = path.read_bytes()
    once = ksylint.fix_text(raw, str(path))
    twice = ksylint.fix_text(once.text, str(path))
    assert twice.text == once.text, "fix is not idempotent"
    try:
        before = yaml.safe_load(raw.decode("utf-8"))
    except (UnicodeDecodeError, yaml.YAMLError):
        return  # unparsable inputs are left alone
    after = yaml.safe_load(once.text)
    norm = _normalise(before)
    assert _normalise(after) == norm


def _normalise(data):
    """Undo the two intended data changes: sorted tags, canonical encodings."""
    from ksylint.encodings import canonical_encoding

    def walk(o):
        if isinstance(o, dict):
            out = {}
            for k, v in o.items():
                if k == "encoding" and isinstance(v, str):
                    v = canonical_encoding(v) or v
                if k == "tags" and isinstance(v, list):
                    v = sorted(v, key=str)
                out[k] = walk(v)
            return out
        if isinstance(o, list):
            return [walk(x) for x in o]
        return o

    return walk(data)


@pytest.mark.parametrize("path", ALL_INPUTS, ids=_id)
def test_fix_resolves_fixable_diagnostics(path):
    raw = path.read_bytes()
    res = ksylint.fix_text(raw, str(path))
    left = [d for d in ksylint.lint_text(res.text, str(path)) if d.fixable]
    if res.skipped or b"\xe9" in raw:
        return
    assert not left, [str(d) for d in left]


def test_clean_file_untouched():
    text = (FORMATS / "gif.ksy").read_text(encoding="utf-8")
    fixable = [d for d in ksylint.lint_text(text, "gif.ksy") if d.fixable]
    res = ksylint.fix_text(text, "gif.ksy")
    assert bool(fixable) == res.changed


def test_fix_respects_config():
    text = "meta:\n  id: x\n  title: X\n  license: CC0-1.0\nseq:\n  - id: a\n    type: str\n    size: 1\n    encoding: ascii\n"
    res = ksylint.fix_text(text, "x.ksy", config=ksylint.Config(ignore=["KSY101"]))
    assert "encoding: ascii" in res.text and "size: 1\n    type: str" in res.text
    res = ksylint.fix_text(text, "x.ksy", config=ksylint.Config(select=["KSY101"]))
    assert "encoding: ASCII" in res.text and "type: str\n    size: 1" in res.text


def test_invalid_utf8_is_not_touched():
    raw = b"meta:\n  id: x\n# \xff\n"
    res = ksylint.fix_text(raw, "x.ksy")
    assert not res.changed and res.skipped


def test_keep_chomping_trailing_newlines_preserved():
    text = "meta:\n  id: x\n  title: X\n  license: CC0-1.0\ndoc: |+\n  text\n\n\n"
    res = ksylint.fix_text(text, "x.ksy")
    assert yaml.safe_load(res.text) == yaml.safe_load(text)
