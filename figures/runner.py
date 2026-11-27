"""Run model-written Python (figure code, solver scratch work) in a separate process.

The code runs in a fresh temp directory with a timeout, isolated mode (-I) and a scrubbed
environment (no API keys). This is a guard against accidents, not a security sandbox:
only model output from our own pipeline is executed here.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

PRELUDE = """
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
plt.rcParams.update({"font.family": "serif", "mathtext.fontset": "cm", "font.size": 11,
                     "savefig.dpi": 200, "savefig.bbox": "tight", "savefig.pad_inches": 0.04})
"""


@dataclass
class RunResult:
    ok: bool
    stdout: str
    stderr: str
    files: dict[str, Path]


def run_python(code: str, *, timeout: int = 40, want: tuple[str, ...] = (), keep_dir: Path | None = None,
               prelude: bool = True) -> RunResult:
    """Execute `code`; return stdout/stderr and any `want` files produced (copied to keep_dir)."""
    env = {k: v for k, v in os.environ.items()
           if k in ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "MPLCONFIGDIR", "SYSTEMROOT")}
    env["MPLBACKEND"] = "Agg"
    with tempfile.TemporaryDirectory() as td:
        script = Path(td) / "main.py"
        script.write_text((PRELUDE if prelude else "") + "\n" + code, encoding="utf-8")
        try:
            p = subprocess.run([sys.executable, "-I", str(script)], cwd=td, env=env, capture_output=True,
                               text=True, timeout=timeout)
            ok, out, err = p.returncode == 0, p.stdout, p.stderr
        except subprocess.TimeoutExpired as e:
            ok, out, err = False, (e.stdout or b"").decode() if isinstance(e.stdout, bytes) else (e.stdout or ""), \
                f"timeout after {timeout}s"
        files = {}
        for name in want:
            src = Path(td) / name
            if src.exists() and keep_dir is not None:
                keep_dir.mkdir(parents=True, exist_ok=True)
                dst = keep_dir / name
                shutil.copy(src, dst)
                files[name] = dst
            elif src.exists():
                files[name] = src
        if want and len(files) < len(want):
            ok = False
            err = (err + f"\nexpected output file(s) not written: {[w for w in want if w not in files]}").strip()
    return RunResult(ok, out[-4000:], err[-4000:], files)
