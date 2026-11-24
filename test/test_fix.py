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


HEAD = "meta:\n  id: x\n  title: X\n  license: CC0-1.0\n"
#: attribute keys out of order (KSY302)
UNORDERED = HEAD + "seq:\n  - type: u1\n    id: a\n"
ORDERED = HEAD + "seq:\n  - id: a\n    type: u1\n"


@pytest.mark.parametrize("as_bytes", [False, True], ids=["str", "bytes"])
def test_bom_is_removed(as_bytes):
    text = "\ufeff" + UNORDERED
    res = ksylint.fix_text(text.encode() if as_bytes else text, "x.ksy")
    assert res.original == text and res.text == ORDERED and res.changed
    assert res.applied == ["KSY001", "KSY302"]


def test_bom_is_kept_if_its_rule_is_disabled():
    res = ksylint.fix_text(
        ("\ufeff" + UNORDERED).encode(), "x.ksy", config=ksylint.Config(ignore=["KSY001"])
    )
    assert res.text == "\ufeff" + ORDERED and res.applied == ["KSY302"]


def test_crlf_is_kept_if_its_rule_is_disabled():
    cfg = ksylint.Config(ignore=["KSY002"])
    crlf = UNORDERED.replace("\n", "\r\n")
    res = ksylint.fix_text(crlf, "x.ksy", config=cfg)
    assert res.text == ORDERED.replace("\n", "\r\n") and res.applied == ["KSY302"]
    # nothing else to fix: the line endings alone are not a reason to rewrite
    assert not ksylint.fix_text(res.text, "x.ksy", config=cfg).changed
    # mixed line endings cannot be restored, so line-based fixes are skipped
    mixed = UNORDERED.replace("\n", "\r\n", 1)
    assert not ksylint.fix_text(mixed, "x.ksy", config=cfg).changed


@pytest.mark.parametrize("config", [ksylint.Config(), ksylint.Config(ignore=["KSY208"])])
@pytest.mark.parametrize("tags", ["  tags: [b, a]\n", "  tags:\n    - b\n    - a\n"])
def test_unsorted_tags_do_not_block_other_reordering(config, tags):
    text = UNORDERED.replace("  license", tags + "  license")
    res = ksylint.fix_text(text, "x.ksy", config=config)
    assert "- id: a\n    type: u1" in res.text and not res.skipped
    sortable = "[" not in tags and not config.ignore
    assert ("- a\n    - b" in res.text) == sortable


def test_disabled_layout_rule_is_not_fixed():
    flush = ORDERED.replace("  - id: a\n    type: u1", "- id: a\n  type: u1")
    res = ksylint.fix_text(flush, "x.ksy", config=ksylint.Config(ignore=["KSY008"]))
    assert not res.changed
    # ... not even as a side effect of fixing an enabled one
    both = flush.replace(HEAD, HEAD.replace("\n  ", "\n    "))
    res = ksylint.fix_text(both, "x.ksy", config=ksylint.Config(ignore=["KSY008"]))
    assert not res.changed and res.skipped[0][0] == "KSY007"
    assert ksylint.fix_text(both, "x.ksy").text == ORDERED


def test_disable_file_comment_is_respected():
    text = "# ksylint: disable-file=attribute-key-order\n" + UNORDERED.replace("id: x", "id:   x")
    assert not ksylint.fix_text(text, "x.ksy").changed
    text = "# ksylint: disable-file\n" + UNORDERED.replace("\n", "\r\n")
    assert not ksylint.fix_text(text, "x.ksy").changed


def test_nested_block_sequences_are_left_alone():
    text = ORDERED + "-x:\n  -   - a\n      - b\n"
    assert not ksylint.fix_text(text, "x.ksy").changed


@pytest.mark.parametrize("marker", ["---", "---  ", "--- # why", "%YAML 1.1\n---"])
def test_document_start_marker_variants(marker):
    res = ksylint.fix_text(marker + "\n" + ORDERED, "x.ksy")
    assert res.text == ("# why\n" if "#" in marker else "") + ORDERED
    assert not [d for d in ksylint.lint_text(res.text, "x.ksy") if d.fixable]


def test_marker_with_content_is_not_reported_fixable():
    text = "--- meta:\n  id: x\n"
    (d,) = (d for d in ksylint.lint_text(text, "x.ksy") if d.rule_id == "KSY004")
    assert not d.fixable and not ksylint.fix_text(text, "x.ksy").changed


def test_unparsable_file_is_left_alone():
    res = ksylint.fix_text("\ufeffmeta: [\r\n", "x.ksy")
    assert not res.changed and res.skipped


def test_deeper_comment_stays_with_the_entry_above_it():
    text = HEAD + (
        "types:\n"
        "  t:\n"
        "    seq:\n"
        "      - id: a\n"
        "        type: u1\n"
        "      # - id: b (a comment that belongs to `seq`)\n"
        "    # about doc\n"
        "    doc: T\n"
        "seq:\n"
        "  - id: a\n"
        "    type: t\n"
    )
    res = ksylint.fix_text(text, "x.ksy", config=ksylint.Config(select=["KSY300"]))
    assert res.text == HEAD + (
        "seq:\n"
        "  - id: a\n"
        "    type: t\n"
        "types:\n"
        "  t:\n"
        "    # about doc\n"
        "    doc: T\n"
        "    seq:\n"
        "      - id: a\n"
        "        type: u1\n"
        "      # - id: b (a comment that belongs to `seq`)\n"
    )
