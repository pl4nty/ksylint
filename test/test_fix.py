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
    """Undo the intended data changes: sorted tags, canonical encodings and
    reformatted docs (only whitespace may differ)."""
    from ksylint.encodings import canonical_encoding

    def walk(o):
        if isinstance(o, dict):
            out = {}
            for k, v in o.items():
                if k == "encoding" and isinstance(v, str):
                    v = canonical_encoding(v) or v
                if k == "doc" and isinstance(v, str):
                    v = " ".join(v.split())
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


def test_flow_style_xref_and_tags_are_not_reported_fixable():
    text = HEAD.replace(
        "  license", "  xref: {wikidata: Q1, justsolve: X}\n  tags: [b, a]\n  license"
    )
    diags = [d for d in ksylint.lint_text(text, "x.ksy") if d.rule_id in ("KSY207", "KSY208")]
    assert len(diags) == 2 and not any(d.fixable for d in diags)
    assert not ksylint.fix_text(text, "x.ksy").changed


def test_one_space_after_dash_for_every_kind_of_item():
    text = HEAD + (
        "seq:\n"
        "  -   {id: a, type: u1}\n"
        "  -  id: b\n"
        "     type: u1\n"
        "x-list:\n"
        "  -   plain\n"
        "  -   'quoted'\n"
        "  -   [1,\n"
        "       2]\n"
        "  -   |\n"
        "      block\n"
        "  -   |2\n"
        "      indicator\n"
    )
    res = ksylint.fix_text(text, "x.ksy")
    assert res.text == HEAD + (
        "seq:\n"
        "  - {id: a, type: u1}\n"
        "  - id: b\n"
        "    type: u1\n"
        "x-list:\n"
        "  - plain\n"
        "  - 'quoted'\n"
        "  - [1,\n"
        "       2]\n"
        "  - |\n"
        "      block\n"
        "  - |2\n"
        "      indicator\n"
    )
    assert not [d for d in ksylint.lint_text(res.text, "x.ksy") if d.fixable]


def test_trailing_deeper_comment_moves_with_the_last_entry():
    # Left in place, the comment would become part of the block scalar.
    text = HEAD + (
        "seq:\n"
        "  - doc: |\n"
        "      Text.\n"
        "    id: a\n"
        "    type: u2\n"
        "      # valid: 0\n"
        "  - id: b\n"
        "    type: u2\n"
    )
    res = ksylint.fix_text(text, "x.ksy", config=ksylint.Config(ignore=["KSY400"]))
    assert not res.skipped and res.text == HEAD + (
        "seq:\n"
        "  - id: a\n"
        "    type: u2\n"
        "      # valid: 0\n"
        "    doc: |\n"
        "      Text.\n"
        "  - id: b\n"
        "    type: u2\n"
    )


def _docs(data, out=None):
    """{path: doc string} of all docs in loaded data."""
    out = {} if out is None else out

    def walk(o, path):
        if isinstance(o, dict):
            for k, v in o.items():
                if k == "doc" and isinstance(v, str):
                    out[(*path, k)] = v
                else:
                    walk(v, (*path, k))
        elif isinstance(o, list):
            for i, v in enumerate(o):
                walk(v, (*path, i))

    walk(data, ())
    return out


DOC_INPUTS = [FIX_FIXTURES / "docs.ksy", *sorted(FORMATS.glob("*.ksy"))]


@pytest.mark.parametrize("path", DOC_INPUTS, ids=lambda p: p.stem)
@pytest.mark.parametrize("rule_id", ["KSY400", "KSY401", "KSY402"])
def test_doc_fix_changes_only_what_it_may(path, rule_id):
    from ksylint.rules.docs import same_prose

    text = path.read_text(encoding="utf-8")
    res = ksylint.fix_text(text, path.name, config=ksylint.Config(select=[rule_id]))
    before, after = yaml.safe_load(text), yaml.safe_load(res.text)
    old, new = _docs(before), _docs(after)
    assert old.keys() == new.keys()
    for k in old:
        if old[k] == new[k]:
            continue
        if rule_id == "KSY400":
            assert old[k] == new[k] + "\n"
        elif rule_id == "KSY402":
            assert same_prose(old[k], new[k])
            assert old[k].count("\n") < new[k].count("\n")
        else:
            assert " ".join(old[k].split()) == " ".join(new[k].split())
    # Nothing but docs changes.
    assert _normalise(before) == _normalise(after)


def test_doc_fix_is_suppressed_by_a_disable_comment():
    text = HEAD + 'doc: "Quoted"  # ksylint: disable=KSY400\n'
    assert not ksylint.fix_text(text, "x.ksy").changed


def test_folded_doc_with_more_indented_lines_keeps_its_breaks():
    text = HEAD + "doc: >\n  Spec:\n    A more indented line\n  joined\n  lines\n"
    res = ksylint.fix_text(text, "x.ksy")
    assert res.text == HEAD + "doc: |\n  Spec:\n    A more indented line\n  joined\n  lines\n"


def test_plain_multi_line_doc_is_dedented():
    # Plain scalars fold away the indentation of continuation lines.
    text = HEAD + "seq:\n  - id: a\n    doc: one\n      two\n        three\n"
    res = ksylint.fix_text(text, "x.ksy", config=ksylint.Config(select=["KSY401"]))
    assert res.text == HEAD + "seq:\n  - id: a\n    doc: |\n      one\n      two\n      three\n"


@pytest.mark.parametrize(
    "line",
    [
        "    indented code " + "x " * 40,
        "| a | b | " + "cell " * 20,
        "# heading " + "word " * 20,
        "see https://example.com/" + "x" * 80 + " for details",
        "aligned   columns " + "word " * 20,
        "\ttab " + "word " * 20,
    ],
)
def test_structure_is_never_wrapped(line):
    from ksylint.rules.docs import wrap_plan

    assert wrap_plan([line], 80) == [None]


def test_fenced_code_is_never_wrapped():
    from ksylint.rules.docs import wrap_plan

    long = "word " * 20
    plan = wrap_plan(["```", long, "```", long], 80)
    assert plan[:3] == [None, None, None] and plan[3] is not None


def test_wrap_backs_off_before_a_token_that_cannot_start_a_line():
    from ksylint.rules.docs import _wrap

    line = "The cookie's most significant bits store the number of containers stored minus 1."
    assert _wrap(line, 80, 0) == [
        "The cookie's most significant bits store the number of containers stored",
        "minus 1.",
    ]


def test_aliased_doc_is_left_alone():
    text = HEAD + "doc: &d >\n  Folded\n  text.\nseq:\n  - id: a\n    type: u1\n    doc: *d\n"
    diags = ksylint.lint_text(text, "x.ksy", config=ksylint.Config(select=["KSY4"]))
    assert [d.line for d in diags] == [5]
