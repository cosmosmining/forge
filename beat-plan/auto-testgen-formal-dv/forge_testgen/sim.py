"""Compile and run a generated testbench with Icarus Verilog or Verilator."""

import os
import re

from . import tools

RESULT_RE = re.compile(r"RESULT errors=(\d+)")
COV_RE = re.compile(r"COV (.*)")


class SimResult:
    def __init__(self, ok, errors, log, compiled=True, timed_out=False, cov=None):
        self.ok, self.errors, self.log = ok, errors, log
        self.compiled, self.timed_out = compiled, timed_out
        self.cov = cov or {}

    @property
    def first_messages(self):
        keep = [l for l in self.log.splitlines()
                if l.startswith(("MISMATCH", "PROTO", "TIMEOUT", "EXTRA", "XPROP", "STALL"))]
        return keep[:5]


def run(workdir, tb_file, rtl_files, simulator="iverilog", timeout=600, defines=()):
    """Returns SimResult.  ok == compiled and ran to RESULT with errors == 0."""
    rtl_files = [os.path.abspath(f) for f in rtl_files]
    log = ""
    if simulator == "iverilog":
        tools.require("iverilog", "vvp")
        cmd = ["iverilog", "-g2012", "-o", "sim.vvp", "-s", "tb"]
        cmd += ["-D%s" % d for d in defines]
        cmd += [tb_file] + rtl_files
        rc, out, to = tools.run(cmd, cwd=workdir, timeout=timeout)
        log += out
        if rc != 0:
            return SimResult(False, None, log, compiled=False, timed_out=to)
        rc, out, to = tools.run(["vvp", "-n", "sim.vvp"], cwd=workdir, timeout=timeout)
        log += out
    elif simulator == "verilator":
        tools.require("verilator")
        cmd = ["verilator", "--binary", "--timing", "-j", "0", "--top-module", "tb",
               "-Wno-fatal", "-Wno-lint", "-Wno-style", "-o", "simv"]
        cmd += ["-D%s" % d for d in defines]
        cmd += [tb_file] + rtl_files
        rc, out, to = tools.run(cmd, cwd=workdir, timeout=max(timeout, 900))
        log += out
        if rc != 0:
            return SimResult(False, None, log, compiled=False, timed_out=to)
        rc, out, to = tools.run([os.path.join(workdir, "obj_dir", "simv")], cwd=workdir,
                                timeout=timeout)
        log += out
    else:
        raise ValueError("unknown simulator %r" % simulator)
    m = RESULT_RE.search(log)
    if to or not m:
        return SimResult(False, None, log, timed_out=to)
    cov = {}
    cm = COV_RE.search(log)
    if cm:
        for kv in cm.group(1).split():
            k, v = kv.split("=")
            cov[k] = int(v)
    errors = int(m.group(1))
    with open(os.path.join(workdir, "sim.log"), "w") as fh:
        fh.write(log)
    return SimResult(errors == 0, errors, log, cov=cov)
