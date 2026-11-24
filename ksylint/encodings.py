"""Canonical character encoding names (style guide, "Encoding name").

The canonical list comes from the vendored schema (which mirrors the
compiler's ``EncodingList``); aliases follow the compiler's alias table.
"""

from __future__ import annotations

import functools
import re
from typing import Optional

from .schema import canonical_encodings

_EXTRA_ALIASES = {
    "ASCII": ["US-ASCII", "US_ASCII", "IBM367", "cp367", "ANSI_X3.4-1968", "646"],
    "UTF-8": ["UTF8", "UTF_8", "cp65001"],
    "IBM437": ["cp437", "437", "IBM-437"],
    "IBM866": ["cp866", "866", "IBM-866"],
    "Shift_JIS": ["Shift-JIS", "ShiftJIS", "S-JIS", "SJIS", "PCK", "MS_Kanji", "csShiftJIS"],
    "Big5": ["csBig5", "Big-5"],
    "EUC-KR": ["EUCKR", "EUC_KR", "korean", "csEUCKR"],
}
_LATIN = {1: 1, 2: 2, 3: 3, 4: 4, 5: 9, 6: 10, 7: 13, 8: 14, 9: 15, 10: 16}


def _norm(s: str) -> str:
    return re.sub(r"[-_\s]", "", s).lower()


@functools.lru_cache(maxsize=1)
def _alias_table() -> dict[str, str]:
    table: dict[str, str] = {}
    canon = canonical_encodings()
    for c in canon:
        table[_norm(c)] = c
    for c, aliases in _EXTRA_ALIASES.items():
        for a in aliases:
            table[_norm(a)] = c
    for c in canon:
        m = re.fullmatch(r"ISO-8859-(\d+)", c)
        if m:
            table[_norm(f"windows-2859{m.group(1)}")] = c
        m = re.fullmatch(r"windows-(\d+)", c)
        if m:
            table[_norm(f"cp{m.group(1)}")] = c
    table[_norm("cp819")] = "ISO-8859-1"
    for k, v in _LATIN.items():
        table[_norm(f"latin{k}")] = f"ISO-8859-{v}"
        table[_norm(f"l{k}")] = f"ISO-8859-{v}"
    return table


def canonical_encoding(name: str) -> Optional[str]:
    """Return the canonical spelling for an encoding name or alias, or None."""
    return _alias_table().get(_norm(name))


def is_canonical(name: str) -> bool:
    return name in canonical_encodings()
