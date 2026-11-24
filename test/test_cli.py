import io
import json
import sys

import pytest

from ksylint.cli import main

GOOD = "meta:\n  id: good\n  title: Good\n  license: CC0-1.0\nseq:\n  - id: one\n    type: u1\n"
BAD = "meta:\n  id: bad\n  title: Bad\n  license: CC0-1.0\nseq:\n  - id: one\n    type: str\n    size: 1\n    encoding: ascii\n"


@pytest.fixture
def files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "good.ksy").write_text(GOOD)
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "bad.ksy").write_text(BAD)
    return tmp_path


def test_exit_codes(files, capsys):
    assert main(["good.ksy"]) == 0
    assert "All checks passed" in capsys.readouterr().out
    assert main(["."]) == 1
    out = capsys.readouterr().out
    assert "sub/bad.ksy:9:15: error [KSY101 encoding-name]" in out
    assert "fixable with `--fix`" in out
    assert main([".", "--exit-zero"]) == 0
    assert main(["nope.ksy"]) == 2


def test_select_ignore(files, capsys):
    assert main([".", "--ignore", "KSY101,KSY302"]) == 0
    assert main([".", "--select", "KSY101"]) == 1
    out = capsys.readouterr().out
    assert "KSY302" not in out and "KSY101" in out
    assert main([".", "--select", "KSY999"]) == 2


def test_fail_on(files):
    (files / "sub" / "bad.ksy").write_text(
        GOOD.replace("good", "bad").replace("seq:", "doc: 'quoted'\nseq:")
    )
    assert main(["."]) == 1  # warning fails by default
    assert main([".", "--fail-on", "error"]) == 0


def test_json_and_github_and_sarif(files, capsys):
    main([".", "--format", "json"])
    data = json.loads(capsys.readouterr().out)
    assert {d["rule_id"] for d in data} == {"KSY101", "KSY302"}
    assert all(d["file"].endswith("bad.ksy") for d in data)
    main([".", "--format", "github"])
    out = capsys.readouterr().out
    assert out.startswith("::error file=sub/bad.ksy,line=")
    assert ",title=KSY" in out
    main([".", "--format", "sarif"])
    sarif = json.loads(capsys.readouterr().out)
    assert sarif["version"] == "2.1.0"
    results = sarif["runs"][0]["results"]
    assert {r["ruleId"] for r in results} == {"KSY101", "KSY302"}
    assert results[0]["locations"][0]["physicalLocation"]["region"]["startLine"] > 0


def test_diff_does_not_write(files, capsys):
    before = (files / "sub" / "bad.ksy").read_text()
    assert main([".", "--diff"]) == 1
    out = capsys.readouterr().out
    assert "+    encoding: ASCII" in out and out.startswith("--- a/")
    assert (files / "sub" / "bad.ksy").read_text() == before


def test_fix_writes(files, capsys):
    assert main([".", "--fix"]) == 0
    text = (files / "sub" / "bad.ksy").read_text()
    assert "encoding: ASCII" in text and "size: 1\n    type: str" in text
    assert main([".", "--diff"]) == 0


def test_config_pyproject(files, capsys):
    (files / "pyproject.toml").write_text(
        '[tool.ksylint]\nignore = ["KSY101"]\n[tool.ksylint.severity]\nKSY302 = "info"\n'
    )
    assert main(["."]) == 0  # KSY302 is info now; info does not fail
    assert "info [KSY302" in capsys.readouterr().out
    assert main([".", "--isolated"]) == 1


def test_config_dotfile(files, capsys):
    (files / ".ksylint.toml").write_text('select = ["KSY3"]\nfail-on = "error"\n')
    assert main(["."]) == 1
    assert "KSY101" not in capsys.readouterr().out
    (files / ".ksylint.toml").write_text("bogus = 1\n")
    assert main(["."]) == 2


@pytest.mark.parametrize(
    "toml",
    [
        "bogus = 1",
        "select = 5",
        "select = [1]",
        'select = ["KSY999"]',
        'severity = "error"',
        '[severity]\nKSY999 = "error"',
        '[severity]\nKSY400 = "fatal"',
        'fail-on = "fatal"',
        'compile = "no"',
        "ksc = 1",
        "rules = 5",
        "[rules]\nKSY402 = 3",
        "[rules.nope]\nx = 1",
        "[rules.KSY402]\nmax_length = 100",
        '[rules.KSY402]\nmax-length = "100"',
        "not toml",
    ],
)
def test_bad_config_is_a_usage_error(files, capsys, toml):
    (files / ".ksylint.toml").write_text(toml + "\n")
    assert main(["."]) == 2
    assert ".ksylint.toml: " in capsys.readouterr().err


def test_bad_pyproject_table(files, capsys):
    (files / "pyproject.toml").write_text('[tool]\nksylint = "x"\n')
    assert main(["."]) == 2


def test_list_rules(capsys):
    assert main(["--list-rules"]) == 0
    out = capsys.readouterr().out
    assert "KSY302  attribute-key-order" in out
    main(["--list-rules", "--format", "json"])
    rules = json.loads(capsys.readouterr().out)
    assert any(r["id"] == "KSY900" and not r["default_enabled"] for r in rules)


def test_stdin(monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(BAD.encode())))
    assert main(["-", "--stdin-filename", "bad.ksy"]) == 1
    assert "bad.ksy:9:15" in capsys.readouterr().out


@pytest.mark.parametrize("text", [GOOD, BAD], ids=["clean", "fixable"])
def test_stdin_fix_always_writes_the_result(monkeypatch, capsys, text):
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(text.encode())))
    assert main(["-", "--fix"]) == 0
    fixed = (
        GOOD if text is GOOD else BAD.replace("type: str\n    size: 1", "size: 1\n    type: str")
    )
    assert capsys.readouterr().out == fixed.replace("ascii", "ASCII")


def test_quiet_and_statistics(files, capsys):
    main([".", "-q"])
    out = capsys.readouterr().out
    assert len(out.splitlines()) == 2 and "Found" not in out
    main([".", "-q", "--statistics"])
    out = capsys.readouterr().out
    assert "     1  KSY101  encoding-name\n" in out and "Found" not in out
    assert main(["good.ksy", "-q"]) == 0
    assert capsys.readouterr().out == ""


def test_sarif_locations_are_uri_references(files, capsys):
    odd = files / "a dir"
    odd.mkdir()
    (odd / "bäd.ksy").write_text(BAD)
    main(["a dir", str(odd), "--format", "sarif"])
    run = json.loads(capsys.readouterr().out)["runs"][0]
    uris = {
        r["locations"][0]["physicalLocation"]["artifactLocation"]["uri"] for r in run["results"]
    }
    assert uris == {"a%20dir/b%C3%A4d.ksy", (odd / "bäd.ksy").as_uri()}
    assert run["columnKind"] == "unicodeCodePoints"


def test_fix_write_error_is_reported(files, capsys, monkeypatch):
    import builtins

    real_open = builtins.open

    def deny(file, mode="r", *a, **k):
        if "w" in mode:
            raise PermissionError(13, "Permission denied", str(file))
        return real_open(file, mode, *a, **k)

    monkeypatch.setattr(builtins, "open", deny)
    assert main([".", "--fix"]) == 2
    assert "Permission denied" in capsys.readouterr().err


def test_compile_mode(files, capsys, tmp_path):
    import shutil

    ksc = shutil.which("kaitai-struct-compiler") or shutil.which("ksc")
    if not ksc:
        import os

        ksc = os.environ.get("KSC")
    if not ksc:
        pytest.skip("kaitai-struct-compiler not available")
    (files / "broken.ksy").write_text(
        GOOD.replace("good", "broken").replace("type: u1", "type: u1x")
    )
    assert main(["broken.ksy", "--compile", "--ksc", ksc, "--select", "KSY9"]) == 1
    out = capsys.readouterr().out
    assert "broken.ksy:7:11: error [KSY900 ksc-error]" in out
