"""Output formats: text, json, sarif, github."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable

from .diagnostic import Diagnostic, Severity
from .registry import all_rules

FORMATS = ("text", "json", "sarif", "github")


def format_text(diags: list[Diagnostic], n_files: int, *, statistics: bool = False) -> str:
    out = [str(d) for d in diags]
    if statistics and diags:
        out.append("")
        counts = Counter((d.rule_id, d.rule_name) for d in diags)
        for (rid, name), n in sorted(counts.items()):
            out.append(f"{n:6d}  {rid}  {name}")
    sev = Counter(d.severity for d in diags)
    nfix = sum(1 for d in diags if d.fixable)
    if diags:
        files = len({d.file for d in diags})
        parts = [
            f"{sev[s]} {s.value}{'s' if sev[s] != 1 and s != Severity.INFO else ''}"
            for s in Severity
            if sev[s]
        ]
        msg = f"Found {len(diags)} problem{'s' if len(diags) != 1 else ''} ({', '.join(parts)}) in {files} of {n_files} file{'s' if n_files != 1 else ''}."
        if nfix:
            msg += f" {nfix} fixable with `--fix`."
        out.append(msg)
    else:
        out.append(f"All checks passed ({n_files} file{'s' if n_files != 1 else ''}).")
    return "\n".join(out) + "\n"


def format_json(diags: list[Diagnostic]) -> str:
    return json.dumps([d.to_dict() for d in diags], indent=2) + "\n"


_SARIF_LEVEL = {Severity.ERROR: "error", Severity.WARNING: "warning", Severity.INFO: "note"}


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
                        "artifactLocation": {"uri": d.file.replace("\\", "/")},
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
        "runs": [{"tool": {"driver": driver}, "results": results}],
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
