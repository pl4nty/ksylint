#!/usr/bin/env python3
"""Refresh the vendored official KSY JSON schema.

Usage:
    python scripts/update_schema.py [--ref REF] [--repo OWNER/NAME]

Downloads ``ksy_schema.json`` from the official ``ksy_schema`` repository at the
given git ref (default: ``master``), resolves the ref to a commit SHA through
the GitHub API, writes the file to ``ksylint/data/ksy_schema.json`` and records
the source commit in ``ksylint/data/README.md``.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import re
import sys
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "ksylint" / "data"


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "ksylint-update-schema"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ref", default="master", help="git ref (branch, tag or SHA)")
    ap.add_argument("--repo", default="kaitai-io/ksy_schema")
    args = ap.parse_args()

    commit = json.loads(fetch(f"https://api.github.com/repos/{args.repo}/commits/{args.ref}"))
    sha = commit["sha"]
    date = commit["commit"]["committer"]["date"][:10]
    raw = fetch(f"https://raw.githubusercontent.com/{args.repo}/{sha}/ksy_schema.json")
    json.loads(raw)  # sanity check: must be valid JSON
    (DATA / "ksy_schema.json").write_bytes(raw)

    readme = DATA / "README.md"
    text = readme.read_text(encoding="utf-8")
    text = re.sub(r"- Commit: `[0-9a-f]+` \([0-9-]+\)", f"- Commit: `{sha}` ({date})", text)
    readme.write_text(text, encoding="utf-8")
    print(f"Updated ksy_schema.json to {args.repo}@{sha} ({date}); fetched {dt.date.today()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
