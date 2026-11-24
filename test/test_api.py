import pytest

import ksylint
from ksylint import Config, Severity

GOOD = "meta:\n  id: good\n  title: Good\n  license: CC0-1.0\nseq:\n  - id: one\n    type: u1\n"


def test_lint_text_clean():
    assert ksylint.lint_text(GOOD, "good.ksy") == []


def test_lint_text_accepts_bytes_and_no_filename():
    assert ksylint.lint_text(GOOD.encode(), None) == []
    # without a filename, meta/id is not compared to it
    assert ksylint.lint_text(GOOD.replace("id: good", "id: other")) == []


def test_lint_text_does_no_io(monkeypatch):
    import builtins

    def boom(*a, **k):
        raise AssertionError("lint_text must not open files")

    ksylint.lint_text(GOOD, "good.ksy")  # warm caches (schema is package data)
    monkeypatch.setattr(builtins, "open", boom)
    assert ksylint.lint_text(GOOD.replace("u1", "u1\n    type: u2"), "good.ksy")


def test_diagnostic_dict():
    d = ksylint.lint_text(GOOD.replace("CC0-1.0", "Nope"), "good.ksy")[0]
    data = d.to_dict()
    assert data["rule_id"] == "KSY204"
    assert data["severity"] == "error"
    assert data["line"] == 4 and data["column"] == 12
    assert data["path"] == "/meta/license"
    assert data["url"].endswith("#meta")


def test_select_ignore_prefix_and_name():
    text = GOOD.replace("  title: Good\n", "")
    assert {d.rule_id for d in ksylint.lint_text(text, "good.ksy")} == {"KSY202"}
    assert ksylint.lint_text(text, "good.ksy", config=Config(ignore=["meta-human-info"])) == []
    assert ksylint.lint_text(text, "good.ksy", config=Config(ignore=["KSY2"])) == []
    assert ksylint.lint_text(text, "good.ksy", config=Config(select=["KSY3"])) == []


def test_severity_override_and_options():
    text = GOOD.replace("seq:", "doc: " + "word " * 20 + "\nseq:")
    d = ksylint.lint_text(text, "good.ksy")
    assert [x.rule_id for x in d] == ["KSY402"]
    cfg = Config(severity={"KSY402": "info"})
    assert ksylint.lint_text(text, "good.ksy", config=cfg)[0].severity is Severity.INFO
    cfg = Config(rule_options={"doc-line-length": {"max-length": 120}})
    assert ksylint.lint_text(text, "good.ksy", config=cfg) == []


def test_inline_suppression():
    text = GOOD.replace(
        "    type: u1\n", '    type: u1\n    doc: "Quoted"  # ksylint: disable=KSY400\n'
    )
    assert ksylint.lint_text(text, "good.ksy") == []
    text2 = "# ksylint: disable-file=KSY203\n" + GOOD.replace("  license: CC0-1.0\n", "")
    assert ksylint.lint_text(text2, "good.ksy") == []
    text3 = GOOD.replace(
        "seq:", "# ksylint: disable-next-line=doc-single-line\ndoc: 'Quoted'\nseq:"
    )
    assert ksylint.lint_text(text3, "good.ksy") == []


def test_parse_error_still_runs_text_rules():
    d = ksylint.lint_text("meta: [\r\n", "x.ksy")
    assert {x.rule_id for x in d} >= {"KSY005", "KSY002"}


def test_yaml11_semantics():
    # PyYAML (YAML 1.1) like the compiler's SnakeYAML: 0x10 keys are ints
    text = GOOD + "enums:\n  e:\n    0x10: a\n    0x01: b\n"
    d = [x for x in ksylint.lint_text(text, "good.ksy") if x.rule_id != "KSY601"]
    assert d == []


def test_rule_lookup():
    assert ksylint.get_rule("ksy302").name == "attribute-key-order"
    assert ksylint.get_rule("attribute-key-order").id == "KSY302"


@pytest.mark.parametrize("brk", ["\r", "\x85", "\u2028", "\u2029"])
def test_positions_with_unusual_line_breaks(brk):
    # PyYAML treats these as line breaks; reported lines must still be
    # `\n`-based (and a CR-only file must not crash the layout rules).
    text = GOOD.replace("seq:", f'doc: "a{brk}b"\nseq:') + "    encoding: ascii\n"
    d = [x for x in ksylint.lint_text(text, "good.ksy") if x.rule_id == "KSY101"]
    assert [(x.line, x.column) for x in d] == [(9, 15)]
    assert "encoding: ASCII" in ksylint.fix_text(text, "good.ksy").text
    ksylint.lint_text(GOOD.replace("\n", brk), "good.ksy")
    ksylint.fix_text(GOOD.replace("\n", brk), "good.ksy")


def test_line_ending_position():
    d = ksylint.lint_text(GOOD.replace("Good\n", "Good\r\n"), "good.ksy")
    assert [(x.rule_id, x.line, x.column) for x in d] == [("KSY002", 3, 14)]


def test_reader_error_position():
    d = ksylint.lint_text(GOOD.replace("one", "o\x01e"), "good.ksy")
    assert [(x.rule_id, x.line, x.column) for x in d] == [("KSY005", 6, 10)]
