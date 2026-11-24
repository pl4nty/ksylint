"""Integration tests over copies of real specifications."""

import os
import pathlib
import shutil

import pytest
from conftest import FORMATS

import ksylint
from ksylint.cli import main

FILES = sorted(FORMATS.glob("*.ksy"))


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.stem)
def test_real_formats_parse_and_validate(path):
    diags = ksylint.lint_file(str(path))
    ids = {d.rule_id for d in diags}
    # These are well-formed, schema-valid specs.
    assert not ids & {"KSY005", "KSY100", "KSY200", "KSY201"}, [str(d) for d in diags]


def test_cli_fix_over_copy(tmp_path, capsys):
    work = tmp_path / "formats"
    shutil.copytree(FORMATS, work)
    assert main([str(work), "--fix", "--select", "KSY0,KSY1,KSY2,KSY3", "-q"]) in (0, 1)
    capsys.readouterr()
    # after fixing, nothing fixable is left and a second run changes nothing
    assert main([str(work), "--diff", "--select", "KSY0,KSY1,KSY2,KSY3"]) == 0
    assert capsys.readouterr().out == ""
    diags = []
    for p in sorted(work.glob("*.ksy")):
        diags += [d for d in ksylint.lint_file(str(p)) if d.fixable]
    assert diags == []


FORMATS_DIR = os.environ.get("KSYLINT_FORMATS_DIR")


@pytest.mark.skipif(
    not FORMATS_DIR, reason="set KSYLINT_FORMATS_DIR to a kaitai_struct_formats checkout"
)
def test_full_formats_repository():
    files = sorted(pathlib.Path(FORMATS_DIR).rglob("*.ksy"))
    assert files
    for p in files:
        raw = p.read_bytes()
        ksylint.lint_text(raw, str(p))
        res = ksylint.fix_text(raw, str(p))
        assert ksylint.fix_text(res.text, str(p)).text == res.text, p
