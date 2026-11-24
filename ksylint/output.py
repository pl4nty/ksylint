"""Output formats: text, json, sarif, github."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable
from pathlib import PurePath
from urllib.parse import quote

from .diagnostic import Diagnostic, Severity
from .registry import all_rules

FORMATS = ("text", "json", "sarif", "github")


def _plural(n: int, noun: str) -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"


def format_text(
    diags: list[Diagnostic], n_files: int, *, statistics: bool = False, summary: bool = True
) -> str:
    out = [str(d) for d in diags]
    if statistics and diags:
        out.append("")
        counts = Counter((d.rule_id, d.rule_name) for d in diags)
        for (rid, name), n in sorted(counts.items()):
            out.append(f"{n:6d}  {rid}  {name}")
    if not summary:
        pass
    elif diags:
        sev = Counter(d.severity for d in diags)
        parts = [
            f"{sev[s]} info" if s is Severity.INFO else _plural(sev[s], s.value)
            for s in Severity
            if sev[s]
        ]
        msg = (
            f"Found {_plural(len(diags), 'problem')} ({', '.join(parts)}) "
            f"in {len({d.file for d in diags})} of {_plural(n_files, 'file')}."
        )
        nfix = sum(d.fixable for d in diags)
        if nfix:
            msg += f" {nfix} fixable with `--fix`."
        out.append(msg)
    else:
        out.append(f"All checks passed ({_plural(n_files, 'file')}).")
    return "".join(ln + "\n" for ln in out)


def format_json(diags: list[Diagnostic]) -> str:
    return json.dumps([d.to_dict() for d in diags], indent=2) + "\n"


_SARIF_LEVEL = {Severity.ERROR: "error", Severity.WARNING: "warning", Severity.INFO: "note"}


def _uri(file: str) -> str:
    """A file name as a URI reference (``file:`` URI if it is absolute)."""
    path = PurePath(file)
    return path.as_uri() if path.is_absolute() else quote(path.as_posix())


def format_sarif(diags: list[Diagnostic], version: str) -> str:
    rules = all_rules()
    index = {r.id: i for i, r in enumerate(rules)}
    results = []
    for d in diags:
        region = {"startLine": d.line, "startColumn": d.column}
        if d.end_line is not None:
            region["endLine"] = d.end_line
        if d.end_column is not None:
            region["endColumn"] = d.end_column
        res = {
            "ruleId": d.rule_id,
            "level": _SARIF_LEVEL[d.severity],
            "message": {"text": d.message},
            "locations": [
                {
                    "physicalLocation": {
                        "artifactLocation": {"uri": _uri(d.file)},
                        "region": region,
                    }
                }
            ],
        }
        if d.rule_id in index:
            res["ruleIndex"] = index[d.rule_id]
        if d.path:
            res["properties"] = {"yamlPath": d.path}
        results.append(res)
    driver = {
        "name": "ksylint",
        "version": version,
        "informationUri": "https://github.com/pl4nty/ksylint",
        "rules": [
            {
                "id": r.id,
                "name": r.name,
                "shortDescription": {"text": r.summary},
                **({"helpUri": r.url} if r.url else {}),
                "defaultConfiguration": {"level": _SARIF_LEVEL[r.severity]},
            }
            for r in rules
        ],
    }
    doc = {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {"driver": driver},
                "columnKind": "unicodeCodePoints",
                "results": results,
            }
        ],
    }
    return json.dumps(doc, indent=2) + "\n"


def _esc_data(s: str) -> str:
    return s.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _esc_prop(s: str) -> str:
    return _esc_data(s).replace(":", "%3A").replace(",", "%2C")


_GH_LEVEL = {Severity.ERROR: "error", Severity.WARNING: "warning", Severity.INFO: "notice"}


def format_github(diags: Iterable[Diagnostic]) -> str:
    out = []
    for d in diags:
        props = [f"file={_esc_prop(d.file)}", f"line={d.line}", f"col={d.column}"]
        if d.end_line is not None:
            props.append(f"endLine={d.end_line}")
        if d.end_column is not None:
            props.append(f"endColumn={d.end_column}")
        props.append(f"title={_esc_prop(d.rule_id + ' ' + d.rule_name)}")
        out.append(f"::{_GH_LEVEL[d.severity]} {','.join(props)}::{_esc_data(d.message)}")
    return "\n".join(out) + ("\n" if out else "")
