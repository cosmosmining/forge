"""Compile and run the generated testbench on Icarus Verilog and Verilator."""

from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass

from . import tools

_RESULT = re.compile(r"DVAGENT_RESULT\s+(.*)")


@dataclass
class SimResult:
    simulator: str
    compiled: bool
    finished: bool
    result: dict | None
    out_file: str
    log: str
    secs: float
    coverage_file: str | None = None
    error: str | None = None


def parse_result(log: str) -> dict | None:
    m = None
    for m in _RESULT.finditer(log or ""):
        pass
    if not m:
        return None
    out = {}
    for kv in m.group(1).split():
        if "=" in kv:
            k, v = kv.split("=", 1)
            try:
                out[k] = int(v)
            except ValueError:
                out[k] = v
    return out


def _defs(defines: dict) -> list:
    out = []
    for k, v in (defines or {}).items():
        out.append(f"-D{k}={v}" if v not in (None, "", True) else f"-D{k}")
    return out


def run_iverilog(tbdir: str, rtl_files: list, include_dirs=(), defines=None,
                 timeout_s: float = 300, tag: str = "iverilog") -> SimResult:
    if tools.which("iverilog") is None or tools.which("vvp") is None:
        return SimResult(tag, False, False, None, "", "iverilog/vvp not installed", 0.0,
                         error="tool-missing")
    vvp = os.path.join(tbdir, f"{tag}.vvp")
    out = f"{tag}_out.txt"
    cmd = ["iverilog", "-g2012", "-o", vvp, "-s", "dvagent_tb"]
    cmd += [f"-I{d}" for d in include_dirs] + _defs(defines)
    cmd += [os.path.join(tbdir, "tb.sv")] + list(rtl_files)
    c = tools.run(cmd, cwd=tbdir, timeout=timeout_s)
    if not c.ok:
        return SimResult(tag, False, False, None, "", c.out, c.secs)
    r = tools.run(["vvp", "-n", vvp, f"+dvout={out}"], cwd=tbdir, timeout=timeout_s)
    res = parse_result(r.out)
    return SimResult(tag, True, (res is not None) and not r.timed_out, res,
                     os.path.join(tbdir, out), c.out + "\n" + r.out, c.secs + r.secs,
                     error="wallclock-timeout" if r.timed_out else None)


def run_verilator(tbdir: str, rtl_files: list, include_dirs=(), defines=None, seed: int = 1,
                  coverage: bool = True, jobs: int = 4, build_timeout_s: float = 600,
                  timeout_s: float = 300, tag: str = "verilator") -> SimResult:
    if tools.which("verilator") is None:
        return SimResult(tag, False, False, None, "", "verilator not installed", 0.0,
                         error="tool-missing")
    objdir = os.path.join(tbdir, f"obj_{tag}")
    shutil.rmtree(objdir, ignore_errors=True)
    out = f"{tag}_out.txt"
    cmd = ["verilator", "--binary", "--timing", "-Wno-fatal", "-Wno-lint", "-Wno-style",
           "--top-module", "dvagent_tb", "-Mdir", objdir, "-o", "Vtb",
           "--x-assign", "unique", "--x-initial", "unique", "-j", str(max(1, jobs))]
    if coverage:
        cmd += ["--coverage-line", "--coverage-toggle"]
    cmd += [f"-I{d}" for d in include_dirs] + _defs(defines)
    cmd += [os.path.join(tbdir, "tb.sv")] + list(rtl_files)
    c = tools.run(cmd, cwd=tbdir, timeout=build_timeout_s)
    exe = os.path.join(objdir, "Vtb")
    if not c.ok or not os.path.isfile(exe):
        return SimResult(tag, False, False, None, "", c.out, c.secs)
    cov = os.path.join(tbdir, f"{tag}_coverage.dat")
    if os.path.exists(cov):
        os.remove(cov)
    run_cmd = [exe, f"+verilator+seed+{seed}", "+verilator+rand+reset+2", f"+dvout={out}"]
    r = tools.run(run_cmd, cwd=tbdir, timeout=timeout_s)
    default_cov = os.path.join(tbdir, "coverage.dat")
    if coverage and os.path.exists(default_cov):
        os.replace(default_cov, cov)
    res = parse_result(r.out)
    return SimResult(tag, True, (res is not None) and not r.timed_out, res,
                     os.path.join(tbdir, out), c.out[-4000:] + "\n" + r.out, c.secs + r.secs,
                     coverage_file=cov if os.path.exists(cov) else None,
                     error="wallclock-timeout" if r.timed_out else None)
