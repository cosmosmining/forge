"""Locating and running the open-source EDA tools (yosys, iverilog, verilator, sby)."""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from dataclasses import dataclass

# Places the OSS CAD Suite or a Nix profile usually put binaries. They are only
# used when present; the normal PATH always comes first.
_EXTRA_BIN_DIRS = [
    os.path.expanduser("~/.nix-profile/bin"),
    os.path.expanduser("~/oss-cad-suite/bin"),
    os.path.expanduser("~/Desktop/oss-cad-suite/bin"),
    "/opt/oss-cad-suite/bin",
    "/usr/local/oss-cad-suite/bin",
]


def tool_env() -> dict:
    env = os.environ.copy()
    extra = os.environ.get("DVAGENT_TOOL_PATH", "")
    dirs = [d for d in extra.split(os.pathsep) if d] + _EXTRA_BIN_DIRS
    path = env.get("PATH", "")
    parts = path.split(os.pathsep) if path else []
    for d in dirs:
        if os.path.isdir(d) and d not in parts:
            parts.append(d)
    env["PATH"] = os.pathsep.join(parts)
    return env


def which(name: str) -> str | None:
    return shutil.which(name, path=tool_env()["PATH"])


@dataclass
class RunResult:
    cmd: list
    rc: int
    out: str
    secs: float
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.rc == 0 and not self.timed_out


def run(cmd: list, cwd: str | None = None, timeout: float | None = None) -> RunResult:
    """Run a command, merging stderr into stdout. Never raises on tool failure."""
    t0 = time.time()
    try:
        p = subprocess.run(
            cmd, cwd=cwd, env=tool_env(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            timeout=timeout, text=True, errors="replace",
        )
        return RunResult(cmd, p.returncode, p.stdout, time.time() - t0)
    except subprocess.TimeoutExpired as e:
        out = e.stdout if isinstance(e.stdout, str) else (e.stdout or b"").decode("utf-8", "replace")
        return RunResult(cmd, -1, out, time.time() - t0, timed_out=True)
    except FileNotFoundError as e:
        return RunResult(cmd, 127, str(e), time.time() - t0)


def _first_line(cmd: list) -> str | None:
    if which(cmd[0]) is None:
        return None
    r = run(cmd, timeout=30)
    text = (r.out or "").strip().splitlines()
    return text[0].strip() if text else None


def versions() -> dict:
    """Version strings of every tool the agent can use (None = not installed)."""
    return {
        "yosys": _first_line(["yosys", "-V"]),
        "iverilog": _first_line(["iverilog", "-V"]),
        "verilator": _first_line(["verilator", "--version"]),
        "sby": _first_line(["sby", "--help"]) and (which("sby") or None),
        "yices-smt2": _first_line(["yices-smt2", "--version"]),
        "z3": _first_line(["z3", "--version"]),
        "bitwuzla": _first_line(["bitwuzla", "--version"]),
    }


def require(names: list) -> list:
    """Return the subset of tool names that are missing."""
    return [n for n in names if which(n) is None]
