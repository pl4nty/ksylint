"""Command-line interface."""

from __future__ import annotations

import argparse
import difflib
import fnmatch
import os
import sys
from pathlib import Path
from typing import Optional

from . import __version__
from .config import Config, ConfigError, load_config
from .diagnostic import Diagnostic, Severity
from .fix import fix_text
from .linter import lint_text
from .output import FORMATS, format_github, format_json, format_sarif, format_text
from .registry import all_rules


def _csv(values: Optional[list[str]]) -> list[str]:
    out: list[str] = []
    for v in values or []:
        out.extend(s.strip() for s in v.split(",") if s.strip())
    return out


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ksylint",
        description="Lint and format Kaitai Struct .ksy files according to the official KSY style guide.",
    )
    p.add_argument(
        "paths",
        nargs="*",
        help="files or directories (searched recursively for *.ksy); `-` reads stdin",
    )
    p.add_argument("--fix", action="store_true", help="apply safe autofixes in place")
    p.add_argument(
        "--diff", action="store_true", help="print the autofix diff instead of writing files"
    )
    p.add_argument(
        "--format", choices=FORMATS, default="text", help="output format (default: text)"
    )
    p.add_argument(
        "--select",
        action="append",
        metavar="RULES",
        help="comma-separated rule IDs/prefixes/names to enable (replaces defaults)",
    )
    p.add_argument(
        "--extend-select", action="append", metavar="RULES", help="enable additional rules"
    )
    p.add_argument(
        "--ignore",
        action="append",
        metavar="RULES",
        help="comma-separated rule IDs/prefixes/names to disable",
    )
    p.add_argument(
        "--config",
        metavar="FILE",
        help="config file (.ksylint.toml or pyproject.toml); default: search upwards",
    )
    p.add_argument("--isolated", action="store_true", help="ignore configuration files")
    p.add_argument(
        "--fail-on",
        choices=[s.value for s in Severity],
        help="lowest severity that makes the exit code 1 (default: warning)",
    )
    p.add_argument(
        "--exit-zero", action="store_true", help="always exit with 0 unless ksylint itself fails"
    )
    p.add_argument(
        "--compile",
        action="store_true",
        help="also run kaitai-struct-compiler and report its errors/warnings",
    )
    p.add_argument("--ksc", metavar="PATH", help="path to kaitai-struct-compiler")
    p.add_argument(
        "-I",
        "--import-path",
        action="append",
        metavar="DIR",
        help="import path for --compile (repeatable)",
    )
    p.add_argument("--stdin-filename", metavar="NAME", help="file name to use for stdin input")
    p.add_argument("--statistics", action="store_true", help="show per-rule counts (text format)")
    p.add_argument("--list-rules", action="store_true", help="list all rules and exit")
    p.add_argument("-q", "--quiet", action="store_true", help="only print diagnostics (no summary)")
    p.add_argument("--version", action="version", version=f"ksylint {__version__}")
    return p


def list_rules(fmt: str) -> str:
    rules = all_rules()
    if fmt == "json":
        import json

        return (
            json.dumps(
                [
                    {
                        "id": r.id,
                        "name": r.name,
                        "severity": r.severity.value,
                        "fixable": r.fixable,
                        "default_enabled": r.default_enabled,
                        "summary": r.summary,
                        "url": r.url,
                        "options": r.options,
                    }
                    for r in rules
                ],
                indent=2,
            )
            + "\n"
        )
    w = max(len(r.name) for r in rules)
    lines = []
    for r in rules:
        flags = ("fix" if r.fixable else "   ") + (" off" if not r.default_enabled else "    ")
        lines.append(f"{r.id}  {r.name:<{w}}  {r.severity.value:<7}  {flags}  {r.summary}")
    return "\n".join(lines) + "\n"


def collect_files(paths: list[str], exclude: list[str]) -> list[str]:
    out: list[str] = []
    for p in paths:
        if p == "-":
            out.append(p)
            continue
        if os.path.isdir(p):
            for f in sorted(Path(p).rglob("*.ksy")):
                if any(
                    part.startswith(".") and part not in (".", "..")
                    for part in f.relative_to(p).parts[:-1]
                ):
                    continue
                rel = f.as_posix()
                if any(
                    fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(f.relative_to(p).as_posix(), pat)
                    for pat in exclude
                ):
                    continue
                out.append(f.as_posix())
        else:
            out.append(p)
    seen: set[str] = set()
    return [f for f in out if not (f in seen or seen.add(f))]


def _configure(args: argparse.Namespace) -> Config:
    cfg = Config() if args.isolated else load_config(args.config)
    if args.select:
        cfg.select = _csv(args.select)
    if args.extend_select:
        cfg.extend_select = [*cfg.extend_select, *_csv(args.extend_select)]
    if args.ignore:
        cfg.ignore = [*cfg.ignore, *_csv(args.ignore)]
    if args.fail_on:
        cfg.fail_on = args.fail_on
    if args.compile:
        cfg.compile = True
    if args.ksc:
        cfg.ksc = args.ksc
    if args.import_path:
        cfg.import_paths = [*cfg.import_paths, *args.import_path]
    cfg.validate()
    return cfg


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    out = sys.stdout

    if args.list_rules:
        out.write(list_rules("json" if args.format == "json" else "text"))
        return 0
    if not args.paths:
        build_parser().print_usage(sys.stderr)
        sys.stderr.write("ksylint: error: no files given\n")
        return 2
    try:
        cfg = _configure(args)
    except (ConfigError, ValueError, OSError) as e:
        sys.stderr.write(f"ksylint: error: {e}\n")
        return 2

    files = collect_files(args.paths, cfg.exclude)
    texts: dict[str, bytes] = {}
    for f in files:
        try:
            if f == "-":
                texts[f] = sys.stdin.buffer.read()
            else:
                with open(f, "rb") as fh:
                    texts[f] = fh.read()
        except OSError as e:
            sys.stderr.write(f"ksylint: error: {e}\n")
            return 2

    changed_any = False
    final: dict[str, str | bytes] = {}
    for f, data in texts.items():
        name = (args.stdin_filename or "<stdin>") if f == "-" else f
        if args.fix or args.diff:
            res = fix_text(data, name, config=cfg)
            if res.changed:
                changed_any = True
                if args.diff:
                    out.writelines(
                        difflib.unified_diff(
                            res.original.splitlines(True),
                            res.text.splitlines(True),
                            fromfile=f"a/{name}",
                            tofile=f"b/{name}",
                        )
                    )
                elif f == "-":
                    out.write(res.text)
                else:
                    with open(f, "w", encoding="utf-8", newline="") as fh:
                        fh.write(res.text)
            final[f] = res.text if (args.fix and not args.diff) else data
        else:
            final[f] = data

    externals: dict[str, dict] = {}
    if cfg.compile:
        from .compiler import CompilerError, run_ksc

        disk = [f for f in final if f != "-"]
        try:
            results = run_ksc(disk, cfg)
        except CompilerError as e:
            sys.stderr.write(f"ksylint: error: {e}\n")
            return 2
        for f in disk:
            r = results.get(f) or results.get(os.path.normpath(f))
            if r is not None:
                externals[f] = {"ksc": r}

    diags: list[Diagnostic] = []
    for f, data in final.items():
        name = (args.stdin_filename or "<stdin>") if f == "-" else f
        diags.extend(lint_text(data, name, config=cfg, external=externals.get(f)))

    if args.diff:
        pass  # diff already printed; diagnostics are not shown
    elif args.fix and "-" in final:
        pass  # fixed text went to stdout
    elif args.format == "json":
        out.write(format_json(diags))
    elif args.format == "sarif":
        out.write(format_sarif(diags, __version__))
    elif args.format == "github":
        out.write(format_github(diags))
    else:
        text = format_text(diags, len(final), statistics=args.statistics)
        if args.quiet:
            text = "".join(ln + "\n" for ln in text.splitlines()[: len(diags)])
        out.write(text)

    if args.exit_zero:
        return 0
    if args.diff:
        return 1 if changed_any else 0
    threshold = Severity.parse(cfg.fail_on).rank
    return 1 if any(d.severity.rank >= threshold for d in diags) else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
