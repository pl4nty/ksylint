import re

import pytest

from ksylint.schema import PROCESS_PATTERN, SCHEMA_PATCHES, raw_schema, schema

# Checked against kaitai-struct-compiler 0.11.
KSC_ACCEPTS = [
    "zlib",
    "xor(0x55)",
    "rol(3)",
    "ror(n)",
    'kaitai.compress.zlib(15, "raw")',
    "kaitai.compress.lz4",
    "concat(metablock_list)",
    "rot(5, 2)",
    "my_rle",
    "xor",  # a custom processor called `xor`
    "foo_9.bar_1(1)",
]
KSC_REJECTS = ["Foo", "_foo", "foo-bar", "foo.Bar(1)", "foo()", "xor()", "foo bar", "foo(1) x"]


@pytest.mark.parametrize("value", KSC_ACCEPTS)
def test_process_pattern_accepts(value):
    assert re.search(PROCESS_PATTERN, value)


@pytest.mark.parametrize("value", KSC_REJECTS)
def test_process_pattern_rejects(value):
    assert not re.search(PROCESS_PATTERN, value)


def test_patches_apply_to_a_copy():
    before = raw_schema()["definitions"]["Attribute"]
    assert "parent" not in before["properties"]
    assert schema()["definitions"]["Attribute"]["properties"]["parent"] == {"type": "string"}
    assert len(schema()["definitions"]["Attribute"]["allOf"]) == len(before["allOf"]) - 2
    assert all(p.reason for p in SCHEMA_PATCHES)
