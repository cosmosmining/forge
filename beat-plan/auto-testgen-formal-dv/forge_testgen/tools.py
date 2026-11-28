"""Locate the open-source EDA tools and record their versions (provenance)."""

import os
import shutil
import subprocess

_EXTRA_PATHS = [os.path.expanduser("~/.nix-profile/bin"), "/opt/oss-cad-suite/bin",
                os.path.expanduser("~/oss-cad-suite/bin")]


def env():
    e = dict(os.environ)
    parts = e.get("PATH", "").split(os.pathsep)
    for p in _EXTRA_PATHS:
        if os.path.isdir(p) and p not in parts:
            parts.append(p)
    e["PATH"] = os.pathsep.join(parts)
    return e


def which(name):
    return shutil.which(name, path=env()["PATH"])


def require(*names):
    missing = [n for n in names if not which(n)]
    if missing:
        raise RuntimeError(
            "missing tools: %s. Install the open-source OSS CAD Suite "
            "(yosys, sby, iverilog, verilator, solvers) and put its bin/ on PATH."
            % ", ".join(missing))


def run(cmd, cwd=None, timeout=600, stdin=None):
    """Run a tool; returns (returncode, combined output, timed_out)."""
    try:
        p = subprocess.run(cmd, cwd=cwd, env=env(), stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, timeout=timeout, text=True,
                           input=stdin)
        return p.returncode, p.stdout, False
    except subprocess.TimeoutExpired as ex:
        out = ex.stdout or ""
        if isinstance(out, bytes):
            out = out.decode(errors="replace")
        return -1, out, True


def versions():
    probes = {
        "yosys": ["yosys", "-V"],
        "sby": None,
        "iverilog": ["iverilog", "-V"],
        "verilator": ["verilator", "--version"],
        "bitwuzla": ["bitwuzla", "--version"],
        "yices-smt2": ["yices-smt2", "--version"],
        "z3": ["z3", "--version"],
    }
    out = {}
    for name, cmd in probes.items():
        path = which(name)
        if not path:
            out[name] = None
            continue
        if cmd is None:
            # sby has no --version; report its store path / location instead.
            out[name] = path
            continue
        rc, text, _ = run(cmd, timeout=30)
        first = (text.strip().splitlines() or [""])[0]
        out[name] = first[:120]
    return out
