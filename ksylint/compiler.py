"""Running kaitai-struct-compiler to collect its diagnostics."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from typing import Optional

from .config import Config


class CompilerError(RuntimeError):
    pass


def find_ksc(cfg: Config) -> str:
    for cand in (cfg.ksc, "kaitai-struct-compiler", "ksc"):
        if cand and (os.path.isfile(cand) or shutil.which(cand)):
            return shutil.which(cand) or cand
    raise CompilerError(
        f"kaitai-struct-compiler not found (tried {cfg.ksc!r}); install it or set `ksc` in the config"
    )


def _import_paths(files: list[str], cfg: Config) -> list[str]:
    paths = list(cfg.import_paths)
    if not paths:
        # Heuristic: the root of the repository containing the files, so
        # that absolute imports like `/common/foo` resolve.
        for f in files:
            d = os.path.dirname(os.path.abspath(f))
            while True:
                if os.path.isdir(os.path.join(d, ".git")) or os.path.isdir(
                    os.path.join(d, "common")
                ):
                    if d not in paths:
                        paths.append(d)
                    break
                parent = os.path.dirname(d)
                if parent == d:
                    break
                d = parent
    return paths


def run_ksc(files: list[str], cfg: Config, timeout: Optional[float] = 600) -> dict[str, dict]:
    """Compile ``files`` in one ksc invocation and return the per-file JSON
    results (keys are the file names as passed in)."""
    if not files:
        return {}
    ksc = find_ksc(cfg)
    with tempfile.TemporaryDirectory(prefix="ksylint-") as out:
        cmd = [ksc, "--ksc-json-output", "-t", cfg.ksc_target, "--outdir", out]
        ip = _import_paths(files, cfg)
        if ip:
            cmd += ["-I", os.pathsep.join(ip)]
        cmd += files
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise CompilerError(f"failed to run {ksc}: {e}") from None
    stdout = proc.stdout.strip()
    start = stdout.find("{")
    if start < 0:
        raise CompilerError(f"unexpected output from {ksc}: {(proc.stderr or stdout)[:500]}")
    try:
        data = json.loads(stdout[start:])
    except json.JSONDecodeError as e:
        raise CompilerError(f"cannot parse ksc JSON output: {e}") from None
    return data
