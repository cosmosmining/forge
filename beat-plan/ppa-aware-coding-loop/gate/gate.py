#!/usr/bin/env python3
"""Locked correctness gate for the PPA-aware coding loop.

The gate decides whether a candidate RTL directory may replace the golden
(original) RTL of a block. The agent that edits RTL cannot change this file,
blocks.json, the golden sources or the targets: loop/loop.py checks every
locked file against LOCK.sha256 before it runs anything.

Verdicts: PASS, FAIL, INCOMPLETE. Only PASS counts.

Checks, in order (all must pass):
  1. sources    : only .v files; no `initial`, no system tasks, no preprocessor
                  directive that the golden sources do not already contain.
  2. structure  : yosys reads it; top exists with exactly the golden ports;
                  no latches; every flip-flop is clocked by the top clock port
                  (no gated or derived clocks); `check -assert` passes.
  3. lint       : verilator --lint-only reports no errors.
  4. simulation : the generated testbench drives identical random + corner
                  stimulus into golden and candidate for every seed; every
                  output bit that is 0/1 in the golden trace must be equal in
                  the candidate trace, every cycle (registers start as X, so a
                  candidate cannot rely on power-up values the golden does not).
  5. formal     : miter(golden, candidate), all flops start at 0; ABC bmc3
                  must find no difference up to the block's depth. An
                  unbounded ABC pdr proof is attempted and recorded when it
                  succeeds; a pdr counterexample is a FAIL.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import tbgen  # noqa: E402

OSS = os.environ.get("OSS_CAD_BIN", "/opt/eda/oss-cad-suite/bin")
ORFS_ROOT = os.environ.get("ORFS_ROOT", "/opt/eda/orfs")
CACHE = os.environ.get("GATE_CACHE", "/opt/eda/gate_cache")
YOSYS = os.path.join(OSS, "yosys")
IVERILOG = os.path.join(OSS, "iverilog")
VVP = os.path.join(OSS, "vvp")
VERILATOR = os.path.join(OSS, "verilator")
SBY = os.path.join(OSS, "sby")

SYSTEM_TASK = re.compile(r"\$(display|write|monitor|strobe|finish|stop|fopen|fclose|fdisplay|fwrite|"
                         r"readmem[hb]|random|urandom|time|realtime|dumpfile|dumpvars|value\$plusargs|"
                         r"test\$plusargs|signed|unsigned|clog2|bits|countones|onehot|isunknown)\b")
ALLOWED_SYSTEM_FUNCS = {"signed", "unsigned", "clog2", "bits"}


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def dir_digest(files):
    h = hashlib.sha256()
    for f in sorted(files, key=os.path.basename):
        h.update(os.path.basename(f).encode() + b"\0")
        with open(f, "rb") as fh:
            h.update(fh.read())
        h.update(b"\0")
    return h.hexdigest()


def run(cmd, cwd=None, timeout=None, log=None):
    t0 = time.time()
    try:
        p = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           timeout=timeout, text=True, errors="replace")
        rc, out = p.returncode, p.stdout
    except subprocess.TimeoutExpired as e:
        rc, out = "timeout", (e.stdout or "") if isinstance(e.stdout, str) else ""
    if log:
        with open(log, "w") as f:
            f.write(" ".join(cmd) + "\n\n" + out)
    return rc, out, time.time() - t0


def strip_comments(text):
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    return re.sub(r"//[^\n]*", "", text)


def preprocessor_lines(text):
    lines = set()
    for ln in strip_comments(text).splitlines():
        s = ln.strip()
        if s.startswith("`") and not s.startswith("`define_") :
            m = re.match(r"`(\w+)", s)
            if m and m.group(1) in ("ifdef", "ifndef", "elsif", "else", "endif", "define", "undef",
                                    "include", "timescale", "default_nettype", "resetall", "celldefine",
                                    "endcelldefine", "line", "pragma"):
                lines.add(re.sub(r"\s+", " ", s))
    return lines


class Gate:
    def __init__(self, block, cand_dir, out_dir, manifest):
        self.block = block
        self.cfg = manifest["blocks"][block]
        self.manifest = manifest
        self.cand_dir = os.path.abspath(cand_dir)
        self.out = os.path.abspath(out_dir)
        os.makedirs(self.out, exist_ok=True)
        self.report = {"block": block, "candidate_dir": self.cand_dir, "checks": {}}

    # ---------------------------------------------------------------- golden
    def golden_files(self):
        files = [os.path.join(ORFS_ROOT, p) for p in self.cfg["golden_files"]]
        for p in files:
            want = self.cfg["golden_sha256"][os.path.relpath(p, ORFS_ROOT)]
            if sha256_file(p) != want:
                raise RuntimeError("golden source changed: %s" % p)
        return files

    def golden_compile_files(self):
        return [f for f in self.golden_files() if os.path.basename(f) not in self.cfg.get("include_only", [])]

    def golden_inc_dirs(self):
        return sorted({os.path.dirname(f) for f in self.golden_files()})

    # ------------------------------------------------------------- candidate
    def cand_all_files(self):
        return sorted(os.path.join(self.cand_dir, f) for f in os.listdir(self.cand_dir)
                      if os.path.isfile(os.path.join(self.cand_dir, f)) and not f.startswith("."))

    def cand_compile_files(self):
        return [f for f in self.cand_all_files() if os.path.basename(f) not in self.cfg.get("include_only", [])]

    # ---------------------------------------------------------------- checks
    def check_sources(self):
        res = {"ok": True, "problems": []}
        files = self.cand_all_files()
        if not files:
            res["ok"] = False
            res["problems"].append("candidate directory is empty")
            return res
        golden_pp = set()
        for g in self.golden_files():
            golden_pp |= preprocessor_lines(open(g, errors="replace").read())
        include_only = set(self.cfg.get("include_only", []))
        for f in files:
            name = os.path.basename(f)
            if not name.endswith(".v"):
                res["ok"] = False
                res["problems"].append("%s: only .v files are allowed" % name)
                continue
            text = open(f, errors="replace").read()
            extra = preprocessor_lines(text) - golden_pp
            if extra:
                res["ok"] = False
                res["problems"].append("%s: preprocessor lines not in golden: %s" % (name, sorted(extra)))
            if name in include_only:
                continue  # checked as part of the files that include it
            # judge the code that synthesis and simulation actually see (-DSYNTHESIS, includes expanded)
            pre = os.path.join(self.out, "pp_" + name)
            rc, out, _ = run([IVERILOG, "-E", "-DSYNTHESIS", "-I" + self.cand_dir, "-o", pre, f],
                             cwd=self.out, timeout=300)
            if rc != 0:
                res["ok"] = False
                res["problems"].append("%s: preprocessing failed: %s" % (name, out[-800:]))
                continue
            code = strip_comments(open(pre, errors="replace").read())
            if re.search(r"\binitial\b", code):
                res["ok"] = False
                res["problems"].append("%s: 'initial' blocks are not allowed" % name)
            for m in SYSTEM_TASK.finditer(code):
                if m.group(1) not in ALLOWED_SYSTEM_FUNCS:
                    res["ok"] = False
                    res["problems"].append("%s: system task $%s is not allowed" % (name, m.group(1)))
            if re.search(r"\bforce\b|\brelease\b|\bdeassign\b", code):
                res["ok"] = False
                res["problems"].append("%s: force/release/deassign not allowed" % name)
        return res

    def yosys_ports(self, files, inc_dirs, tag):
        js = os.path.join(self.out, "ports_%s.json" % tag)
        incs = " ".join("-I" + d for d in inc_dirs)
        script = ("read_verilog -DSYNTHESIS %s %s; hierarchy -check -top %s; proc; write_json %s"
                  % (incs, " ".join(files), self.cfg["top"], js))
        rc, out, _ = run([YOSYS, "-q", "-p", script], log=os.path.join(self.out, "yosys_ports_%s.log" % tag),
                         timeout=600)
        if rc != 0:
            return None, out
        mod = json.load(open(js))["modules"][self.cfg["top"]]
        ports = [(n, p["direction"], len(p["bits"])) for n, p in mod["ports"].items()]
        return ports, out

    def check_structure(self):
        res = {"ok": True, "problems": []}
        gports, gout = self.yosys_ports(self.golden_compile_files(), self.golden_inc_dirs(), "golden")
        if gports is None:
            raise RuntimeError("golden RTL does not elaborate:\n" + gout[-2000:])
        self.golden_ports = gports
        cports, cout = self.yosys_ports(self.cand_compile_files(), [self.cand_dir], "cand")
        if cports is None:
            res["ok"] = False
            res["problems"].append("yosys cannot elaborate the candidate:\n" + cout[-3000:])
            return res
        if sorted(gports) != sorted(cports):
            res["ok"] = False
            res["problems"].append("ports differ from golden. golden=%s candidate=%s" % (gports, cports))
            return res
        # flatten, latches, clocks, check -assert
        js = os.path.join(self.out, "flat_cand.json")
        script = ("read_verilog -DSYNTHESIS -I%s %s; hierarchy -check -top %s; proc; flatten; opt_clean; "
                  "tee -o %s/check_cand.txt check -assert; write_json %s"
                  % (self.cand_dir, " ".join(self.cand_compile_files()), self.cfg["top"], self.out, js))
        rc, out, _ = run([YOSYS, "-q", "-p", script], log=os.path.join(self.out, "yosys_struct.log"), timeout=900)
        if rc != 0:
            res["ok"] = False
            res["problems"].append("yosys structural check failed (check -assert / elaboration):\n" + out[-3000:])
            return res
        mod = json.load(open(js))["modules"][self.cfg["top"]]
        clk = self.cfg["stim"]["clock"]
        clk_bits = mod["ports"][clk]["bits"]
        n_ff = 0
        for cname, cell in mod["cells"].items():
            t = cell["type"]
            if "latch" in t.lower() or t.startswith("$dlatch") or t.startswith("$_DLATCH"):
                res["ok"] = False
                res["problems"].append("latch inferred: %s (%s)" % (cname, t))
            if "CLK" in cell["connections"] and ("dff" in t.lower() or "ff" in t.lower()):
                n_ff += 1
                if cell["connections"]["CLK"] != clk_bits:
                    res["ok"] = False
                    res["problems"].append("flip-flop %s is not clocked directly by '%s'" % (cname, clk))
                pol = cell.get("parameters", {}).get("CLK_POLARITY", "1")
                if str(pol).lstrip("0") not in ("1",):
                    res["ok"] = False
                    res["problems"].append("flip-flop %s uses the falling clock edge" % cname)
            if t in ("$mem", "$mem_v2", "$memrd", "$memwr", "$memrd_v2", "$memwr_v2"):
                pass
        res["flip_flop_cells"] = n_ff
        return res

    def _verilator(self, files, inc_dirs, tag):
        cmd = [VERILATOR, "--lint-only", "-Wno-fatal", "-Wno-BADVLTPRAGMA", "--no-timing", "-DSYNTHESIS",
               "--top-module", self.cfg["top"]] + ["-I" + d for d in inc_dirs] + files
        rc, out, _ = run(cmd, cwd=self.out, log=os.path.join(self.out, "verilator_%s.log" % tag), timeout=600)
        lines = out.splitlines()
        errors = [l for l in lines if l.startswith("%Error")]
        warns = [l for l in lines if l.startswith("%Warning")]
        return errors, warns

    @staticmethod
    def _lint_sig(line):
        # drop "path:line:col:" so the same message on another line has the same signature
        return re.sub(r"\s\S+?:\d+:\d+:", "", line).strip()

    def check_lint(self):
        """Errors that the golden RTL itself produces are pre-existing and do not fail a candidate."""
        res = {"ok": True, "problems": []}
        gerr, gwarn = self._verilator(self.golden_compile_files(), self.golden_inc_dirs(), "golden")
        golden_sigs = {self._lint_sig(e) for e in gerr}
        cerr, cwarn = self._verilator(self.cand_compile_files(), [self.cand_dir], "cand")
        new = [e for e in cerr if self._lint_sig(e) not in golden_sigs
               and not e.startswith("%Error: Exiting due to")]
        res["errors_new"] = len(new)
        res["errors_preexisting_in_golden"] = len(cerr) - len(new)
        res["warnings"] = len(cwarn)
        res["warnings_golden"] = len(gwarn)
        if new:
            res["ok"] = False
            res["problems"] += new[:20]
        return res

    # ------------------------------------------------------------ simulation
    def build_tb(self):
        tb = tbgen.generate_tb(self.cfg["top"], self.golden_ports, self.cfg["stim"])
        path = os.path.join(self.out, "tb_%s.v" % self.block)
        open(path, "w").write(tb)
        return path

    def compile_sim(self, tb, files, inc_dirs, exe):
        incs = ["-I" + d for d in inc_dirs]
        cmd = [IVERILOG, "-g2005", "-DSYNTHESIS", "-o", exe, "-s", "tb"] + incs + [tb] + files
        return run(cmd, cwd=self.out, log=exe + ".compile.log", timeout=600)

    def golden_trace(self, tb, seed, cycles):
        key = hashlib.sha256((open(tb).read() + "|%d|%d|" % (seed, cycles) +
                              "".join(self.cfg["golden_sha256"][k] for k in sorted(self.cfg["golden_sha256"])))
                             .encode()).hexdigest()[:20]
        d = os.path.join(CACHE, self.block)
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, "golden_%s_s%d.trace" % (key, seed))
        if not os.path.exists(path):
            exe = os.path.join(self.out, "golden_sim.vvp")
            if not os.path.exists(exe):
                rc, out, _ = self.compile_sim(tb, self.golden_compile_files(), self.golden_inc_dirs(), exe)
                if rc != 0:
                    raise RuntimeError("golden simulation does not compile:\n" + out[-2000:])
            tmp = path + ".tmp"
            rc, out, _ = run([VVP, "-n", exe, "+seed=%d" % seed, "+cycles=%d" % cycles, "+trace=" + tmp],
                             cwd=self.out, timeout=3600)
            if rc != 0:
                raise RuntimeError("golden simulation failed:\n" + out[-2000:])
            os.replace(tmp, path)
        return path

    def check_sim(self):
        res = {"ok": True, "problems": [], "seeds": {}}
        tb = self.build_tb()
        exe = os.path.join(self.out, "cand_sim.vvp")
        rc, out, _ = self.compile_sim(tb, self.cand_compile_files(), [self.cand_dir], exe)
        if rc != 0:
            res["ok"] = False
            res["problems"].append("candidate does not compile in iverilog:\n" + out[-3000:])
            return res
        sim = self.cfg["sim"]
        outs = [n for (n, d, w) in self.golden_ports if d == "output"]
        total_known_bits = 0
        for seed in sim["seeds"]:
            gpath = self.golden_trace(tb, seed, sim["cycles"])
            cname = "cand_s%d.trace" % seed  # relative to self.out (vvp runs there)
            cpath = os.path.join(self.out, cname)
            rc, out, el = run([VVP, "-n", exe, "+seed=%d" % seed, "+cycles=%d" % sim["cycles"], "+trace=" + cname],
                              cwd=self.out, timeout=3600)
            if rc == 0 and not os.path.exists(cpath):
                raise RuntimeError("simulation wrote no trace file " + cpath)
            if rc != 0:
                res["ok"] = False
                res["problems"].append("candidate simulation failed (seed %d): %s" % (seed, out[-1500:]))
                return res
            mism, known, cycles = compare_traces(gpath, cpath, outs)
            total_known_bits += known
            res["seeds"][str(seed)] = {"cycles": cycles, "known_output_bits": known,
                                       "first_mismatch": mism, "seconds": round(el, 1)}
            if mism:
                res["ok"] = False
                res["problems"].append("seed %d: first mismatch %s" % (seed, mism))
                return res
        res["known_output_bits_compared"] = total_known_bits
        if total_known_bits == 0:
            res["ok"] = False
            res["problems"].append("golden outputs were never known (0/1); the comparison is empty")
        return res

    # ---------------------------------------------------------------- formal
    def check_formal(self):
        """miter(golden, candidate) -> AIGER (all flops start at 0) -> ABC.

        1. `dprove` (CEC, retiming, latch correspondence, induction, interpolation, PDR):
           "equivalent" = unbounded proof; "NOT EQUIVALENT" = counterexample -> FAIL.
        2. If dprove is undecided: `bmc3` must reach the block's depth with no counterexample.
        """
        res = {"ok": True, "problems": []}
        f = self.cfg["formal"]
        top = self.cfg["top"]
        fdir = os.path.join(self.out, "formal")
        os.makedirs(fdir, exist_ok=True)
        aig = os.path.join(fdir, "miter.aig")
        gi = " ".join("-I" + d for d in self.golden_inc_dirs())
        script = "\n".join([
            "read_verilog -DSYNTHESIS %s %s" % (gi, " ".join(self.golden_compile_files())),
            "hierarchy -check -top %s" % top,
            "proc; flatten; memory -nomap; opt_clean",
            "rename %s gold" % top,
            "design -stash gold",
            "read_verilog -DSYNTHESIS -I%s %s" % (self.cand_dir, " ".join(self.cand_compile_files())),
            "hierarchy -check -top %s" % top,
            "proc; flatten; memory -nomap; opt_clean",
            "rename %s gate" % top,
            "design -stash gate",
            "design -copy-from gold -as gold gold",
            "design -copy-from gate -as gate gate",
            "miter -equiv -flatten -ignore_gold_x gold gate miter",
            "hierarchy -top miter",
            "flatten",
            "memory_map",
            "opt -fast",
            "async2sync",
            "setundef -zero -init",
            "setundef -undriven -zero",
            "opt -full",
            "techmap",
            "opt -fast",
            "simplemap",
            "dffunmap",
            "aigmap",
            "opt_clean",
            "stat",
            "write_aiger -zinit -map %s %s" % (os.path.join(fdir, "miter.aim"), aig),
        ])
        ys = os.path.join(fdir, "miter.ys")
        open(ys, "w").write(script + "\n")
        rc, out, _ = run([YOSYS, "-q", ys], cwd=fdir, log=os.path.join(fdir, "miter.log"), timeout=1800)
        if rc != 0 or not os.path.exists(aig):
            res["ok"] = False
            res["incomplete"] = True
            res["problems"].append("could not build the miter:\n" + str(out)[-2000:])
            return res

        abc = os.path.join(OSS, "yosys-abc")
        t_dp = f.get("dprove_timeout", 900)
        # scorr: signal correspondence by 2-step induction (merges only proven-equal signals,
        # so it never hides a difference); then dprove on what is left.
        rc, out, el = run([abc, "-c", "read_aiger %s; strash; scorr -C 100000 -F 2; print_stats; dprove -T %d"
                           % (aig, min(t_dp // 2, 300))],
                          cwd=fdir, timeout=t_dp, log=os.path.join(fdir, "dprove.log"))
        text = str(out)
        low = text.lower()
        # when scorr removes every latch, dprove falls back to combinational CEC and prints
        # "UNSATISFIABLE" (miter output can never be 1 = proven) or "SATISFIABLE" (counterexample)
        if ("not equivalent" in low or "was asserted in frame" in low
                or re.search(r"^SATISFIABLE\b", text, re.M)):
            dp = "COUNTEREXAMPLE"   # checked first: a counterexample always wins
        elif rc == "timeout":
            dp = "TIMEOUT"
        elif "networks are equivalent" in low or re.search(r"^UNSATISFIABLE\b", text, re.M):
            dp = "PROVED"
        else:
            dp = "UNDECIDED"
        res["dprove"] = {"status": dp, "seconds": round(el, 1)}
        if dp == "COUNTEREXAMPLE":
            res["ok"] = False
            res["problems"].append("formal: golden and candidate differ (ABC dprove counterexample, see formal/dprove.log)")
            return res
        if dp == "PROVED":
            res["strength"] = "unbounded proof (ABC dprove)"
            return res
        t_bmc = f.get("bmc_timeout", 1800)
        rc, out, el = run([abc, "-c", "read_aiger %s; strash; bmc3 -F %d -T %d" % (aig, f["depth"], t_bmc - 30)],
                          cwd=fdir, timeout=t_bmc, log=os.path.join(fdir, "bmc3.log"))
        m = re.search(r"No output asserted in (\d+) frames", str(out))
        if "was asserted in frame" in str(out):
            res["bmc"] = {"status": "COUNTEREXAMPLE", "seconds": round(el, 1)}
            res["ok"] = False
            res["problems"].append("formal: BMC counterexample (see formal/bmc3.log)")
            return res
        frames = int(m.group(1)) if m else 0
        res["bmc"] = {"status": "PASS" if frames >= f["depth"] else "INCOMPLETE",
                      "frames": frames, "required": f["depth"], "seconds": round(el, 1)}
        if frames < f["depth"]:
            res["ok"] = False
            res["incomplete"] = True
            res["problems"].append("formal: BMC reached only %d of %d frames" % (frames, f["depth"]))
            return res
        res["strength"] = "bounded (BMC %d cycles from reset state)" % frames
        return res

    # -------------------------------------------------------------------- run
    def run(self, skip=()):
        t0 = time.time()
        files = self.cand_all_files()
        self.report["candidate_sha256"] = dir_digest(files) if files else None
        self.report["candidate_files"] = [os.path.basename(f) for f in files]
        verdict = "PASS"
        order = [("sources", self.check_sources), ("structure", self.check_structure),
                 ("lint", self.check_lint), ("simulation", self.check_sim), ("formal", self.check_formal)]
        for name, fn in order:
            if name in skip:
                continue
            try:
                r = fn()
            except Exception as e:  # tool problem -> INCOMPLETE, never PASS
                r = {"ok": False, "incomplete": True, "problems": ["gate error: %r" % (e,)]}
            self.report["checks"][name] = r
            if not r["ok"]:
                verdict = "INCOMPLETE" if r.get("incomplete") else "FAIL"
                break
        self.report["verdict"] = verdict
        self.report["seconds"] = round(time.time() - t0, 1)
        with open(os.path.join(self.out, "gate_report.json"), "w") as fh:
            json.dump(self.report, fh, indent=1)
        return self.report


def compare_traces(gpath, cpath, outs):
    known = 0
    n = 0
    with open(gpath) as g, open(cpath) as c:
        for n, (gl, cl) in enumerate(zip(g, c)):
            gv, cv = gl.split(), cl.split()
            for i, (a, b) in enumerate(zip(gv, cv)):
                if a == b:
                    known += sum(1 for ch in a if ch in "01")
                    continue
                for j, (x, y) in enumerate(zip(a, b)):
                    if x in "01":
                        if x != y:
                            return ({"cycle": n, "output": outs[i], "bit": len(a) - 1 - j,
                                     "golden": a, "candidate": b}, known, n + 1)
                        known += 1
        rest_g, rest_c = g.read(), c.read()
        if rest_g or rest_c:
            return ({"cycle": n + 1, "output": "-", "golden": "trace length differs"}, known, n + 1)
    return None, known, n + 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--block", required=True)
    ap.add_argument("--cand", required=True, help="directory holding the candidate .v files")
    ap.add_argument("--out", required=True)
    ap.add_argument("--skip", default="", help="comma list of checks to skip (debug only; never PASS)")
    a = ap.parse_args()
    manifest = json.load(open(os.path.join(HERE, "blocks.json")))
    skip = tuple(s for s in a.skip.split(",") if s)
    rep = Gate(a.block, a.cand, a.out, manifest).run(skip=skip)
    if skip and rep["verdict"] == "PASS":
        rep["verdict"] = "INCOMPLETE"
    print(json.dumps({"verdict": rep["verdict"], "seconds": rep["seconds"],
                      "candidate_sha256": rep["candidate_sha256"],
                      "problems": [p for c in rep["checks"].values() for p in c.get("problems", [])][:5]},
                     indent=1))
    sys.exit(0 if rep["verdict"] == "PASS" else 1)


if __name__ == "__main__":
    main()
