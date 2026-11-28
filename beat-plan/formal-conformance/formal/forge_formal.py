#!/usr/bin/env python3
"""forge_formal: property checking on generated RTL blocks with SymbiYosys.

    discover   list modules and ports in RTL files; write a spec skeleton to start from
    run        check block specs: structure + prove (k-induction) + cover  ->  verdict.json
    mutate     mutation analysis: do the contract properties catch yosys-generated mutants?
    summarize  collect verdicts and mutation results into summary.json and RESULTS.md

Verdicts follow the Forge gate: PASS, FAIL or INCOMPLETE, and only PASS counts.
  * PASS        structure clean, every assert proven unbounded (k-induction), every cover reached
  * FAIL        a structural problem, a counterexample, or a cover that cannot be reached
                within the cover depth (the proof could be vacuous)
  * INCOMPLETE  tool error, timeout, induction did not converge, or the spec has no
                asserts or no covers
A property is never weakened to get a PASS; a bounded result is reported as bounded.

Specs are JSON (schema forge.formal.spec/v1); see formal/specs/*.json and README.md.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fc_common import (FC_ROOT, Sanitizer, find_tools, load_json, rel_to_root,  # noqa: E402
                       sby_env, sha256_file, sha256_text, tool_versions, write_json)

SPEC_SCHEMA = "forge.formal.spec/v1"
VERDICT_SCHEMA = "forge.formal.verdict/v1"
MUTATION_SCHEMA = "forge.formal.mutation/v1"
DISCOVER_SCHEMA = "forge.formal.discover/v1"
DEFAULT_FRONTEND = "read_verilog -formal -sv"
DEFAULT_RESULTS = FC_ROOT / "results"
DEFAULT_WORK = FC_ROOT / "work"
IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
PROP_TYPES = {"assert", "assume", "assert_next", "assert_after_reset", "stream_out", "stream_in"}
ROLES = {"contract", "strengthening", "environment"}
HARNESS_TOP = "forge_harness"
RTL_SUFFIXES = {".v", ".sv"}
SKIP_DIRS = {".git", "work", "results", "pack", "__pycache__", "node_modules"}


class SpecError(ValueError):
    pass


# =========================================================================== specs
def load_spec(path: Path) -> dict:
    path = Path(path).resolve()
    raw = path.read_bytes()
    spec = load_json(path)
    base_ref = None
    if spec.get("extends"):
        # A control spec: the base spec minus some properties, so it cannot drift from it.
        base_path = (path.parent / spec["extends"]).resolve()
        base = load_json(base_path)
        base["rtl"] = [str((base_path.parent / r).resolve()) for r in base.get("rtl", [])]
        drop = set(spec.get("drop_properties", []))
        unknown = drop - {p["id"] for p in base.get("properties", [])}
        if unknown:
            raise SpecError(f"{path.name}: drop_properties not in base: {sorted(unknown)}")
        base["properties"] = [p for p in base.get("properties", []) if p["id"] not in drop]
        base.update({k: v for k, v in spec.items() if k not in ("extends", "drop_properties")})
        base_ref = {"file": base_path, "sha256": sha256_file(base_path), "dropped": sorted(drop)}
        spec = base
    spec["_base"] = base_ref
    if spec.get("schema") != SPEC_SCHEMA:
        raise SpecError(f"{path.name}: schema must be {SPEC_SCHEMA!r}")
    for key in ("block", "rtl", "instances"):
        if not spec.get(key):
            raise SpecError(f"{path.name}: missing {key!r}")
    if not IDENT.match(spec["block"]):
        raise SpecError(f"{path.name}: block name must be an identifier")
    spec["_path"] = path
    spec["_sha256"] = sha256_text(raw.decode("utf-8"))
    spec["_rtl_abs"] = []
    for r in spec["rtl"]:
        p = (path.parent / r).resolve()
        if not p.is_file():
            raise SpecError(f"{path.name}: RTL file not found: {r}")
        spec["_rtl_abs"].append(p)
    spec.setdefault("frontend", DEFAULT_FRONTEND)
    spec.setdefault("clock", None)
    spec.setdefault("reset", None)
    spec.setdefault("free_inputs", {})
    spec.setdefault("anyconst", {})
    spec.setdefault("helper_sv", [])
    spec.setdefault("properties", [])
    spec.setdefault("covers", [])
    spec.setdefault("depth", {})
    spec["depth"].setdefault("prove", 8 if spec["clock"] else 1)
    spec["depth"].setdefault("cover", 20 if spec["clock"] else 1)
    spec.setdefault("timeout_s", 900)
    names = set()
    for inst in spec["instances"]:
        if not IDENT.match(inst.get("name", "")) or not IDENT.match(inst.get("module", "")):
            raise SpecError(f"{path.name}: instance name/module must be identifiers")
        if inst["name"] in names:
            raise SpecError(f"{path.name}: duplicate instance {inst['name']}")
        names.add(inst["name"])
        inst.setdefault("expose", [])
        inst.setdefault("expose_prep", [])
        inst.setdefault("connect", {})
    ids = set()
    for p in spec["properties"] + spec["covers"]:
        if not IDENT.match(p.get("id", "")):
            raise SpecError(f"{path.name}: property id {p.get('id')!r} is not an identifier")
        if p["id"] in ids:
            raise SpecError(f"{path.name}: duplicate property id {p['id']}")
        ids.add(p["id"])
    for p in spec["properties"]:
        if p.get("type") not in PROP_TYPES:
            raise SpecError(f"{path.name}: {p['id']}: type must be one of {sorted(PROP_TYPES)}")
        p.setdefault("role", "environment" if p["type"] in ("assume", "stream_in") else "contract")
        if p["role"] not in ROLES:
            raise SpecError(f"{path.name}: {p['id']}: role must be one of {sorted(ROLES)}")
        if not spec["clock"] and p["type"] not in ("assert", "assume"):
            raise SpecError(f"{path.name}: {p['id']}: {p['type']} needs a clock")
    if spec["reset"] and not spec["clock"]:
        raise SpecError(f"{path.name}: reset given without clock")
    return spec


# =========================================================================== processes
def run_cmd(cmd, cwd: Path, timeout: float, env=None, log: Path | None = None):
    """Run a command in its own process group; kill the whole group on timeout."""
    t0 = time.time()
    with open(log, "w") if log else open(os.devnull, "w") as out:
        proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=out, stderr=subprocess.STDOUT,
                                start_new_session=True)
        try:
            rc = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()
            rc = "TIMEOUT"
    return rc, round(time.time() - t0, 2)


def yosys(tools, script: list[str], cwd: Path, log: Path, timeout=600):
    return run_cmd([tools["yosys"], "-q", "-l", log.name, "-p", "; ".join(script)],
                   cwd=cwd, timeout=timeout, log=cwd / (log.stem + ".stdout"))


# =========================================================================== job setup
def prepare_job(spec, work_root: Path, tag: str) -> tuple[Path, list[str]]:
    job = work_root / spec["block"] / tag
    if job.exists():
        shutil.rmtree(job)
    (job / "src").mkdir(parents=True)
    names = []
    for i, src in enumerate(spec["_rtl_abs"]):
        name = f"rtl{i}_{src.name}"
        shutil.copyfile(src, job / "src" / name)
        names.append(name)
    return job, names


def dut_script(spec, rtl_names) -> list[str]:
    """Yosys commands that read the RTL and expose internal signals. Shared by every
    step, so port lists, proofs and mutation lists all see the same design."""
    lines = [f"{spec['frontend']} {' '.join(rtl_names)}"]
    done = set()
    for inst in spec["instances"]:
        mod = inst["module"]
        if mod in done:
            continue
        done.add(mod)
        for cmd in inst["expose_prep"]:
            lines.append(f"{cmd} {mod}")
        if inst["expose"]:
            lines.append("expose " + " ".join(f"{mod}/{sel}" for sel in inst["expose"]))
    return lines


def extract_ports(spec, job: Path, rtl_names, tools) -> dict:
    script = dut_script(spec, rtl_names) + ["write_json ports.json"]
    rc, _ = yosys(tools, script, cwd=job / "src", log=job / "src" / "ports.log")
    pj = job / "src" / "ports.json"
    if rc != 0 or not pj.exists():
        raise SpecError("could not read the RTL with yosys (see ports.log)")
    data = load_json(pj)
    out = {}
    for inst in spec["instances"]:
        mod = inst["module"]
        if mod not in data["modules"]:
            raise SpecError(f"module {mod} not found in the RTL")
        out[mod] = [{"name": n, "dir": p["direction"], "width": len(p["bits"]),
                     "signed": bool(p.get("signed"))}
                    for n, p in data["modules"][mod]["ports"].items()]
    return out


# =========================================================================== harness
def _sv_name(port: str) -> str:
    return re.sub(r"_+$", "", re.sub(r"[^A-Za-z0-9_]", "_", port))


def _decl(kind: str, width: int, signed: bool, name: str) -> str:
    rng = f"[{width - 1}:0] " if width > 1 else ""
    return f"{kind} {'signed ' if signed else ''}{rng}{name}"


class Harness:
    def __init__(self, spec, ports):
        self.spec = spec
        self.ports = ports
        self.single = len(spec["instances"]) == 1
        self.wire = {}                       # (inst, port) -> harness wire name
        for inst in spec["instances"]:
            for p in ports[inst["module"]]:
                base = _sv_name(p["name"])
                self.wire[(inst["name"], p["name"])] = base if self.single else f"{inst['name']}__{base}"
        self.by_sv = {}                      # (inst, sanitized port) -> original port name
        for (i, pn) in self.wire:
            self.by_sv[(i, _sv_name(pn))] = pn

    def rw(self, expr: str) -> str:
        """Rewrite inst.port references to harness wire names."""
        def sub(m):
            inst, port = m.group(1), m.group(2)
            if (inst, port) not in self.by_sv:
                raise SpecError(f"unknown port {inst}.{port} in expression: {expr}")
            return self.wire[(inst, self.by_sv[(inst, port)])]
        names = "|".join(re.escape(i["name"]) for i in self.spec["instances"])
        return re.sub(rf"\b({names})\.([A-Za-z_][A-Za-z0-9_]*)\b", sub, expr)

    def build(self, roles=("contract", "strengthening", "environment"), with_covers=True) -> str:
        s = self.spec
        clocked = bool(s["clock"])
        rst = s["reset"] or None
        inputs, body = [], []
        if clocked:
            inputs.append("input wire f_clk")
        if rst:
            inputs.append("input wire f_rst_in")
        for name, w in s["free_inputs"].items():
            inputs.append(_decl("input wire", int(w), False, name))
        wires, insts = [], []
        for inst in s["instances"]:
            conns = []
            for p in self.ports[inst["module"]]:
                pn, hw = p["name"], self.wire[(inst["name"], p["name"])]
                port_ref = pn if IDENT.match(pn) else f"\\{pn} "
                if p["dir"] == "input":
                    if clocked and pn == s["clock"]:
                        conns.append(f".{port_ref}(f_clk)")
                        continue
                    if rst and pn == rst["port"]:
                        conns.append(f".{port_ref}({'!f_rst' if rst.get('active_low') else 'f_rst'})")
                        continue
                    if pn in inst["connect"]:
                        wires.append(_decl("wire", p["width"], p["signed"], hw)
                                     + f" = {self.rw(inst['connect'][pn])};")
                    else:
                        inputs.append(_decl("input wire", p["width"], p["signed"], hw))
                else:
                    wires.append(_decl("wire", p["width"], p["signed"], hw) + ";")
                conns.append(f".{port_ref}({hw})")
            insts.append(f"    {inst['module']} {inst['name']} (\n        "
                         + ",\n        ".join(conns) + "\n    );")
        hdr = [
            f"// Generated by forge_formal.py from spec {s['block']} (spec sha256 {s['_sha256'][:16]}).",
            "// Do not edit: regenerate from the spec. Free inputs are unconstrained every cycle",
            "// unless an assume below says otherwise.",
            "`default_nettype none",
            f"module {HARNESS_TOP} (",
            "    " + ",\n    ".join(inputs),
            ");",
        ]
        if clocked:
            body += [
                "    // ---- reset sequencing and the 'checked' window",
                "    reg f_past_valid = 1'b0;",
                "    always @(posedge f_clk) f_past_valid <= 1'b1;",
            ]
            if rst:
                n = int(rst.get("init_cycles", 1))
                body += [
                    "    reg [7:0] f_cycle = 8'd0;",
                    "    always @(posedge f_clk) if (f_cycle != 8'hff) f_cycle <= f_cycle + 8'd1;",
                    f"    wire f_in_init = (f_cycle < 8'd{n});",
                    "    wire f_rst = f_rst_in;",
                    "    always @(*) begin",
                    "        if (f_in_init) f_assume_reset_held: assume(f_rst);",
                    "        else f_assume_no_later_reset: assume(!f_rst);",
                    "    end",
                    "    wire f_active = !f_in_init;",
                ]
            else:
                body += ["    wire f_active = 1'b1;"]
        for name, w in s["anyconst"].items():
            body.append(f"    (* anyconst *) {_decl('wire', int(w), False, name)};")
        body += ["    // ---- design under test"] + [f"    {w}" for w in wires] + insts
        if s["helper_sv"]:
            body.append("    // ---- helper logic from the spec")
            body += [f"    {self.rw(line)}" for line in s["helper_sv"]]
        body.append("    // ---- properties")
        for p in s["properties"]:
            if p["role"] in roles:
                body += self._prop(p, clocked)
        if with_covers:
            body.append("    // ---- covers (non-vacuity: each must be reachable)")
            for c in s["covers"]:
                g = "if (f_active) " if clocked else ""
                body.append(f"    always @(*) {g}{c['id']}: cover({self.rw(c['expr'])});")
        return "\n".join(hdr + body + ["endmodule", "`default_nettype wire", ""])

    def _prop(self, p, clocked) -> list[str]:
        pid, t = p["id"], p["type"]
        kw = "assume" if t in ("assume", "stream_in") else "assert"
        e = self.rw(p.get("expr", "1'b1"))
        if t in ("assert", "assume"):
            g = "if (f_active) " if clocked else ""
            return [f"    always @(*) {g}{pid}: {kw}({e});"]
        past_ok = "f_past_valid && $past(f_active) && f_active"
        if t == "assert_after_reset":
            return [f"    always @(posedge f_clk) if (f_past_valid && f_active && !$past(f_active)) {pid}: assert({e});"]
        if t == "assert_next":
            cond = past_ok + (f" && $past({self.rw(p['when'])})" if p.get("when") else "")
            return [f"    always @(posedge f_clk) if ({cond}) {pid}: assert({e});"]
        v, r, d = self.rw(p["valid"]), self.rw(p["ready"]), self.rw(p["data"])
        return [f"    always @(posedge f_clk) if ({past_ok} && $past(({v}) && !({r}))) "
                f"{pid}: {kw}(({v}) && (({d}) == $past({d})));"]


# =========================================================================== sby
def sby_file(spec, mode: str, depth: int, script: list[str], files: list[str], tools) -> str:
    return "\n".join(["[options]", f"mode {mode}", f"depth {depth}", "",
                      "[engines]", f"smtbmc {tools['solver']}", "",
                      "[script]", *script, "", "[files]", *files, ""])


RE_FAILED = re.compile(r"summary:\s+failed assertion (\S+) at (\S+)(?: step (\d+))?")
RE_CEX = re.compile(r"summary: counterexample trace(?: \[(\w+)\])?: (\S+)")
RE_COVER_TRACE = re.compile(r"summary: cover trace: (\S+)")
RE_REACHED = re.compile(r"summary:\s+reached cover statement (\S+) at (\S+)(?: step (\d+))?")
RE_ENGINE_REACHED = re.compile(r"Reached cover statement in step (\d+) at \S+: (\S+)")
RE_UNREACHED_ITEM = re.compile(r"summary:\s+(\S+) at (\S+)\s*$")
RE_ENGINE_STEP = re.compile(r"engine_\d+(?:\.basecase)?: .*Checking assertions in step (\d+)")
RE_ENGINE_FAIL = re.compile(r"engine_\d+(?:\.basecase)?: .*Assert failed in \S+: (\S+)")


def _pname(raw: str) -> str:
    return raw.split(".", 1)[1] if raw.startswith(HARNESS_TOP + ".") else raw


def parse_sby(log_text: str, workdir: Path, rc) -> dict:
    status = "TIMEOUT" if rc == "TIMEOUT" else None
    st = workdir / "status"
    if status is None and st.exists():
        status = (st.read_text().split() or ["ERROR"])[0]
    if status is None:
        m = re.search(r"DONE \((\w+), rc=", log_text)
        status = m.group(1) if m else "ERROR"
    res = {"status": status, "failed": [], "induction_failed": [], "cex_traces": [],
           "cover_traces": [], "reached": [], "unreached": [],
           "k_induction": "successful proof by k-induction" in log_text}
    in_unreached = False
    trace_kind = "basecase"        # summary lists failed assertions under the trace they belong to
    cur_step, fail_step = None, {}  # bmc/basecase engine lines give the step of each failure
    reach_step = {}
    for line in log_text.splitlines():
        m = RE_ENGINE_REACHED.search(line)
        if m:
            reach_step.setdefault(m.group(2), int(m.group(1)))
        m = RE_ENGINE_STEP.search(line)
        if m:
            cur_step = int(m.group(1))
        m = RE_ENGINE_FAIL.search(line)
        if m and cur_step is not None:
            fail_step.setdefault(m.group(1), cur_step)
        if "summary: unreached cover statements:" in line:
            in_unreached = True
            continue
        if in_unreached:
            m = RE_UNREACHED_ITEM.search(line)
            if m and "reached cover statement" not in line:
                res["unreached"].append(_pname(m.group(1)))
                continue
            in_unreached = False
        m = RE_CEX.search(line)
        if m:
            trace_kind = m.group(1) or "basecase"
            res["cex_traces"].append({"kind": trace_kind, "path": m.group(2)})
            continue
        m = RE_FAILED.search(line)
        if m:
            name = _pname(m.group(1))
            entry = {"property": name, "at": m.group(2)}
            step = m.group(3)
            if trace_kind == "induction":
                if entry not in res["induction_failed"]:
                    res["induction_failed"].append(entry)
            else:
                entry["step"] = int(step) if step is not None else fail_step.get(name)
                if entry not in res["failed"]:
                    res["failed"].append(entry)
            continue
        m = RE_COVER_TRACE.search(line)
        if m:
            res["cover_traces"].append(m.group(1))
            continue
        m = RE_REACHED.search(line)
        if m:
            name = _pname(m.group(1))
            step = int(m.group(3)) if m.group(3) is not None else reach_step.get(name)
            res["reached"].append({"cover": name, "step": step})
    return res


def run_sby(spec, job: Path, task: str, mode: str, depth: int, script, files, tools):
    sby = job / f"{task}.sby"
    sby.write_text(sby_file(spec, mode, depth, script, files, tools))
    rc, elapsed = run_cmd([tools["sby"], "-f", "-d", task, sby.name], cwd=job,
                          timeout=spec["timeout_s"], env=sby_env(tools), log=job / f"{task}.log")
    log_text = (job / f"{task}.log").read_text(errors="replace")
    res = parse_sby(log_text, job / task, rc)
    res.update({"mode": mode, "depth": depth, "elapsed_s": elapsed})
    return res


# =========================================================================== run
def structural_check(spec, job, rtl_names, tools) -> dict:
    out = {"status": "PASS", "modules": {}}
    for mod in dict.fromkeys(i["module"] for i in spec["instances"]):
        log = job / "src" / f"structure_{mod}.log"
        script = [f"{spec['frontend']} {' '.join(rtl_names)}", f"hierarchy -top {mod}", "proc",
                  "check -assert",
                  "select -assert-none t:$dlatch t:$adlatch t:$dlatchsr t:$sr"]
        rc, _ = yosys(tools, script, cwd=job / "src", log=log)
        ok = rc == 0
        out["modules"][mod] = "PASS" if ok else ("TIMEOUT" if rc == "TIMEOUT" else "FAIL")
        if not ok:
            out["status"] = "FAIL" if rc != "TIMEOUT" else "INCOMPLETE"
    return out


def decide(spec, structure, prove, cover) -> tuple[str, list[str]]:
    reasons, verdict = [], "PASS"
    n_assert = sum(1 for p in spec["properties"] if p["type"] not in ("assume", "stream_in"))
    if structure["status"] == "FAIL":
        verdict = "FAIL"
        reasons.append("structural check failed: " + ", ".join(
            m for m, s in structure["modules"].items() if s != "PASS"))
    if prove and prove["status"] == "FAIL":
        verdict = "FAIL"
        reasons.append("counterexample for: " + ", ".join(
            sorted({f["property"] for f in prove["failed"]})))
    if cover and cover["status"] == "FAIL":
        verdict = "FAIL"
        reasons.append(f"cover(s) not reached within depth {cover['depth']} (proof may be "
                       "vacuous): " + ", ".join(cover["unreached"]))
    if verdict == "FAIL":
        return verdict, reasons
    if n_assert == 0:
        return "INCOMPLETE", ["spec has no assertions"]
    if not spec["covers"]:
        return "INCOMPLETE", ["spec has no covers: without them a proof can be vacuous"]
    if structure["status"] != "PASS":
        return "INCOMPLETE", ["structural check did not finish"]
    for name, t in (("prove", prove), ("cover", cover)):
        if t["status"] != "PASS":
            msg = {"UNKNOWN": "induction did not converge (bounded result only)",
                   "TIMEOUT": f"timed out after {spec['timeout_s']} s"}.get(t["status"], t["status"])
            reasons.append(f"{name}: {msg}")
    if reasons:
        return "INCOMPLETE", reasons
    # Do not take sby's word alone: every cover in the spec needs its own 'reached' line.
    reached = {r["cover"] for r in cover.get("reached", [])}
    missing = [c["id"] for c in spec["covers"] if c["id"] not in reached]
    if missing:
        return "INCOMPLETE", ["cover task passed but no 'reached' evidence for: " + ", ".join(missing)]
    if not prove.get("k_induction"):
        return "INCOMPLETE", ["prove passed without the 'successful proof by k-induction' line"]
    return "PASS", ["all assertions proven by k-induction; all covers reached"]


def _evidence(src: Path, dst: Path, san: Sanitizer) -> dict:
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(san(src.read_text(errors="replace")))
    return {"file": rel_to_root(dst), "sha256": sha256_file(dst)}


def run_spec(spec_path: Path, results_root: Path, work_root: Path, tools) -> dict:
    out_dir = results_root / Path(spec_path).stem
    try:
        spec = load_spec(spec_path)
    except SpecError as exc:
        verdict = {"schema": VERDICT_SCHEMA, "block": Path(spec_path).stem,
                   "verdict": "INCOMPLETE", "reasons": [f"spec invalid: {exc}"]}
        write_json(out_dir / "verdict.json", verdict)
        return verdict
    out_dir = results_root / spec["block"]
    if out_dir.exists():                      # only this step's files; mutation results stay
        for old in out_dir.iterdir():
            if not old.name.startswith("mutation"):
                shutil.rmtree(old) if old.is_dir() else old.unlink()
    job, rtl_names = prepare_job(spec, work_root, "run")
    san = Sanitizer({"<work>": job})
    evidence = []
    try:
        ports = extract_ports(spec, job, rtl_names, tools)
        harness = Harness(spec, ports).build()
    except SpecError as exc:
        verdict = {"schema": VERDICT_SCHEMA, "block": spec["block"], "verdict": "INCOMPLETE",
                   "reasons": [f"harness generation failed: {exc}"]}
        write_json(out_dir / "verdict.json", verdict)
        return verdict
    (job / "src" / "forge_harness.sv").write_text(harness)
    structure = structural_check(spec, job, rtl_names, tools)
    script = dut_script(spec, rtl_names) + [f"read_verilog -formal -sv forge_harness.sv",
                                            f"prep -top {HARNESS_TOP}"]
    files = [f"src/{n}" for n in rtl_names] + ["src/forge_harness.sv"]
    prove = run_sby(spec, job, "prove", "prove", spec["depth"]["prove"], script, files, tools)
    cover = run_sby(spec, job, "cover", "cover", spec["depth"]["cover"], script, files, tools)
    verdict, reasons = decide(spec, structure, prove, cover)

    evidence.append(_evidence(job / "src" / "forge_harness.sv", out_dir / "harness.sv", san))
    for mod in structure["modules"]:
        evidence.append(_evidence(job / "src" / f"structure_{mod}.log",
                                  out_dir / f"structure_{mod}.log", san))
    for task, res in (("prove", prove), ("cover", cover)):
        evidence.append(_evidence(job / f"{task}.sby", out_dir / f"{task}.sby", san))
        evidence.append(_evidence(job / f"{task}.log", out_dir / f"{task}.log", san))
        traces = [t["path"] for t in res["cex_traces"] if t["kind"] == "basecase"] if task == "prove" \
            else res["cover_traces"]
        kept = []
        for i, t in enumerate(traces):
            src = job / t
            if src.exists():
                name = f"{task}_cex.vcd" if task == "prove" else f"cover_trace{i}.vcd"
                ev = _evidence(src, out_dir / "traces" / name, san)
                evidence.append(ev)
                kept.append(ev["file"])
        res["cex_traces"] = kept if task == "prove" else res["cex_traces"]
        if task == "cover":
            res["cover_traces"] = kept

    props = []
    failed = {f["property"] for f in prove.get("failed", [])}
    for p in spec["properties"]:
        if p["type"] in ("assume", "stream_in"):
            st = "assumed"
        elif prove["status"] == "PASS":
            st = "proven"
        elif p["id"] in failed:
            st = "failed"
        else:
            st = "not decided"
        props.append({"id": p["id"], "type": p["type"], "role": p["role"], "status": st,
                      "source": p.get("source", "")})
    reached = {r["cover"]: r["step"] for r in cover.get("reached", [])}
    covers = [{"id": c["id"], "status": "reached" if c["id"] in reached else "unreached",
               "step": reached.get(c["id"]), "source": c.get("source", "")} for c in spec["covers"]]
    verdict_obj = {
        "schema": VERDICT_SCHEMA,
        "block": spec["block"],
        "standin": bool(spec.get("standin")),
        "control": bool(spec.get("control")),
        "description": spec.get("description", ""),
        "verdict": verdict,
        "reasons": reasons,
        "kind": "measured",
        "inputs": {
            "spec": {"file": rel_to_root(spec["_path"]), "sha256": sha256_file(spec["_path"])},
            "rtl": [{"file": rel_to_root(p), "sha256": sha256_file(p)} for p in spec["_rtl_abs"]],
            "harness_sha256": sha256_text(harness),
        },
        "structure": structure,
        "tasks": {
            "prove": {k: prove[k] for k in ("status", "mode", "depth", "elapsed_s", "k_induction",
                                             "failed", "induction_failed", "cex_traces")},
            "cover": {k: cover[k] for k in ("status", "mode", "depth", "elapsed_s", "reached",
                                             "unreached", "cover_traces")},
        },
        "properties": props,
        "covers": covers,
        "counts": {
            "asserts": sum(1 for p in props if p["status"] != "assumed"),
            "asserts_proven": sum(1 for p in props if p["status"] == "proven"),
            "contract_asserts_proven": sum(1 for p in props if p["status"] == "proven" and p["role"] == "contract"),
            "assumes": sum(1 for p in props if p["status"] == "assumed"),
            "covers": len(covers),
            "covers_reached": sum(1 for c in covers if c["status"] == "reached"),
        },
        "tools": tool_versions(tools),
        "evidence": evidence,
    }
    if spec["_base"]:
        verdict_obj["inputs"]["spec_base"] = {"file": rel_to_root(spec["_base"]["file"]),
                                              "sha256": spec["_base"]["sha256"],
                                              "dropped_properties": spec["_base"]["dropped"]}
    if spec.get("bit_exact"):
        be = dict(spec["bit_exact"])
        be["status"] = "proven" if verdict == "PASS" else "not proven"
        be["counterexamples"] = len(prove.get("failed", []))
        verdict_obj["bit_exact"] = be
    write_json(out_dir / "verdict.json", verdict_obj)
    return verdict_obj


# =========================================================================== mutate
RE_MUT_SRC = re.compile(r"\s-src\s+\S+")


def mutate_spec(spec_path: Path, results_root: Path, work_root: Path, tools,
                count=None, seed=None, jobs=4) -> dict:
    spec = load_spec(spec_path)
    mcfg = dict(spec.get("mutation") or {})
    if not mcfg.get("module"):
        raise SpecError("spec has no mutation.module")
    count = int(count or mcfg.get("count", 30))
    seed = int(seed if seed is not None else mcfg.get("seed", 1))
    depth = int(mcfg.get("depth", spec["depth"]["cover"]))
    job, rtl_names = prepare_job(spec, work_root, "mutate")
    san = Sanitizer({"<work>": job})
    ports = extract_ports(spec, job, rtl_names, tools)
    # Mutation runs check the contract only: strengthening invariants describe the
    # original design's internals, so a mutant tripping one may still be correct.
    harness = Harness(spec, ports).build(roles=("contract", "environment"), with_covers=False)
    (job / "src" / "forge_harness.sv").write_text(harness)
    base = dut_script(spec, rtl_names) + ["read_verilog -formal -sv forge_harness.sv",
                                          f"prep -top {HARNESS_TOP}"]
    rc, _ = yosys(tools, base + [f"mutate -list {count} -seed {seed} -o mutations.ys "
                                 f"-s mutations.txt {mcfg['module']}"],
                  cwd=job / "src", log=job / "src" / "mutate_list.log")
    ys = job / "src" / "mutations.ys"
    if rc != 0 or not ys.exists():
        raise SpecError("yosys mutate -list failed (see mutate_list.log)")
    muts = [l.strip() for l in ys.read_text().splitlines() if l.strip().startswith("mutate ")]
    files = [f"src/{n}" for n in rtl_names] + ["src/forge_harness.sv"]

    def one(idx_line):
        idx, line = idx_line
        sub = job / f"m{idx:03d}"
        if sub.exists():
            shutil.rmtree(sub)
        (sub / "src").mkdir(parents=True)
        for f in files:
            shutil.copyfile(job / f, sub / f)
        res = run_sby(spec, sub, "bmc", "bmc", depth, base + [line], files, tools)
        equiv = None
        if res["status"] == "FAIL":
            cls = "killed"
        elif res["status"] == "PASS":
            # A survivor may be an equivalent mutant (no behaviour change at all). Ask yosys'
            # own equivalence flow; only a proof moves it out of 'survived' (conservative).
            mod = mcfg["module"]
            rc, _ = yosys(tools, base + [f"copy {mod} forge_gold", line,
                                         f"equiv_make forge_gold {mod} forge_equiv",
                                         "hierarchy -top forge_equiv", "equiv_simple -seq 5",
                                         "equiv_induct -seq 5", "equiv_status -assert"],
                          cwd=sub / "src", log=sub / "src" / "equiv.log")
            equiv = "proven equivalent" if rc == 0 else "not proven equivalent"
            cls = "equivalent" if rc == 0 else "survived"
        else:
            cls = "inconclusive"
        roles = {p["id"]: p["role"] for p in spec["properties"]}
        return {"id": idx, "mutation": RE_MUT_SRC.sub("", line), "bmc_status": res["status"],
                "class": cls, "equivalence_check": equiv,
                "killed_by": sorted({f["property"] for f in res["failed"]}),
                "killed_by_roles": sorted({roles.get(f["property"], "?") for f in res["failed"]}),
                "first_fail_step": min((f["step"] for f in res["failed"] if f.get("step") is not None),
                                       default=None),
                "elapsed_s": res["elapsed_s"]}

    with cf.ThreadPoolExecutor(max_workers=jobs) as ex:
        results = list(ex.map(one, enumerate(muts)))
    killed = sum(r["class"] == "killed" for r in results)
    survived = sum(r["class"] == "survived" for r in results)
    equivalent = sum(r["class"] == "equivalent" for r in results)
    inconclusive = sum(r["class"] == "inconclusive" for r in results)
    decided = killed + survived
    out_dir = results_root / spec["block"]
    out_dir.mkdir(parents=True, exist_ok=True)
    for stale in out_dir.glob("mutation*"):      # only this step's files; run's verdict stays
        stale.unlink()
    ev = [_evidence(job / "src" / "mutations.ys", out_dir / "mutation_list.ys", san),
          _evidence(job / "src" / "forge_harness.sv", out_dir / "mutation_harness.sv", san)]
    obj = {
        "schema": MUTATION_SCHEMA,
        "block": spec["block"],
        "standin": bool(spec.get("standin")),
        "control": bool(spec.get("control")),
        "kind": "measured",
        "method": ("yosys `mutate -list` mutants of module " + mcfg["module"]
                   + f"; each mutant checked by sby bmc to depth {depth} against the contract "
                   "and environment properties only (no strengthening invariants, no covers); "
                   "each survivor then put through yosys equiv_make/equiv_simple/equiv_induct "
                   "against the original: proven equivalent -> 'equivalent', else 'survived'"),
        "module": mcfg["module"], "count_requested": count, "seed": seed, "bmc_depth": depth,
        "mutants": len(results), "killed": killed, "survived": survived,
        "equivalent": equivalent, "inconclusive": inconclusive,
        "kill_rate": None if decided == 0 else round(killed / decided, 4),
        "kill_rate_formula": ("killed / (killed + survived); mutants proven equivalent and "
                              "inconclusive runs excluded"),
        "results": results,
        "tools": tool_versions(tools),
        "inputs": {"spec": {"file": rel_to_root(spec["_path"]), "sha256": sha256_file(spec["_path"])},
                   "rtl": [{"file": rel_to_root(p), "sha256": sha256_file(p)} for p in spec["_rtl_abs"]]},
        "evidence": ev,
    }
    if spec["_base"]:
        obj["inputs"]["spec_base"] = {"file": rel_to_root(spec["_base"]["file"]),
                                      "sha256": spec["_base"]["sha256"],
                                      "dropped_properties": spec["_base"]["dropped"]}
    write_json(out_dir / "mutation.json", obj)
    return obj


# =========================================================================== discover
CLOCK_RE = re.compile(r"^(clk|clock|.*_clk|clk_.*|.*_clock)$", re.I)
RESET_RE = re.compile(r"^(rst|reset|rst_n|resetn|reset_n|nrst|.*_rst|.*_rst_n|.*_reset|.*_reset_n|aresetn)$", re.I)


def discover(paths, tools, work_root: Path) -> dict:
    files = []
    for p in paths:
        p = Path(p).resolve()
        if p.is_file() and p.suffix in RTL_SUFFIXES:
            files.append(p)
        elif p.is_dir():
            for f in sorted(p.rglob("*")):
                if f.suffix in RTL_SUFFIXES and f.is_file() and not (set(f.relative_to(p).parts[:-1]) & SKIP_DIRS):
                    files.append(f)
    job = work_root / "_discover"
    if job.exists():
        shutil.rmtree(job)
    job.mkdir(parents=True)
    report = {"schema": DISCOVER_SCHEMA, "rtl_files_found": len(files), "files": []}
    for i, f in enumerate(files):
        name = f"f{i}_{f.name}"
        shutil.copyfile(f, job / name)
        rc, _ = yosys(tools, [f"read_verilog -sv {name}", "proc", f"write_json d{i}.json"], cwd=job,
                      log=job / f"d{i}.log")
        try:
            shown = rel_to_root(f)
        except ValueError:
            shown = f.name
        entry = {"file": shown, "sha256": sha256_file(f), "parsed": rc == 0, "modules": []}
        if rc == 0:
            for mod, m in load_json(job / f"d{i}.json")["modules"].items():
                if m.get("attributes", {}).get("blackbox"):
                    continue
                ports = [{"name": n, "dir": p["direction"], "width": len(p["bits"])}
                         for n, p in m["ports"].items()]
                ins = [p["name"] for p in ports if p["dir"] == "input"]
                guess = {"clock": next((n for n in ins if CLOCK_RE.match(n)), None),
                         "reset": next((n for n in ins if RESET_RE.match(n)), None)}
                names = {p["name"] for p in ports}
                hs = []
                for n in sorted(names):
                    for v, r in (("_valid", "_ready"), ("_vld", "_rdy"), ("_en", "_rdy"), ("valid", "ready")):
                        if n.endswith(v) and n[: -len(v)] + r in names:
                            hs.append({"valid": n, "ready": n[: -len(v)] + r})
                entry["modules"].append({"module": mod, "ports": ports, "guess": guess,
                                         "handshake_candidates": hs})
        report["files"].append(entry)
    return report


def spec_skeleton(entry_file: str, mod: dict) -> dict:
    g = mod["guess"]
    sk = {
        "schema": SPEC_SCHEMA,
        "block": mod["module"],
        "description": "TODO: what this block must do, in one line",
        "rtl": [f"TODO-relative-path-to/{Path(entry_file).name}"],
        "instances": [{"name": "dut", "module": mod["module"]}],
        "clock": g["clock"],
        "reset": {"port": g["reset"], "active_low": bool(g["reset"] and g["reset"].lower().endswith("n")),
                  "init_cycles": 1} if g["reset"] else None,
        "properties": [],
        "covers": [],
        "_todo": ["add contract properties with their source (spec line, doc, integer model)",
                  "add at least one cover per property group (non-vacuity)",
                  "handshake candidates: " + (", ".join(f"{h['valid']}/{h['ready']}"
                                                         for h in mod["handshake_candidates"]) or "none")],
    }
    return sk


# =========================================================================== summarize
def summarize(results_root: Path, out_md: Path | None, discover_report: dict | None = None) -> dict:
    blocks = []
    for d in sorted(p for p in results_root.iterdir() if p.is_dir()):
        v = d / "verdict.json"
        m = d / "mutation.json"
        row = {"block": d.name}
        if v.exists():
            vj = load_json(v)
            row.update({"verdict": vj["verdict"], "standin": vj.get("standin", False),
                        "control": vj.get("control", False),
                        "reasons": vj.get("reasons", []),
                        "asserts": sum(1 for p in vj.get("properties", []) if p["status"] != "assumed"),
                        "proven": sum(1 for p in vj.get("properties", []) if p["status"] == "proven"),
                        "covers": len(vj.get("covers", [])),
                        "covers_reached": sum(1 for c in vj.get("covers", []) if c["status"] == "reached"),
                        "prove_depth": vj.get("tasks", {}).get("prove", {}).get("depth"),
                        "bit_exact": vj.get("bit_exact"),
                        "verdict_file": rel_to_root(v), "verdict_sha256": sha256_file(v)})
        if m.exists():
            mj = load_json(m)
            row["mutation"] = {k: mj.get(k, 0) for k in ("mutants", "killed", "survived", "equivalent",
                                                         "inconclusive", "kill_rate", "bmc_depth")}
            row["mutation"]["file"] = rel_to_root(m)
            row["mutation"]["sha256"] = sha256_file(m)
        blocks.append(row)
    summary = {"schema": "forge.formal.summary/v1", "blocks": blocks}
    if discover_report is not None:
        summary["discover"] = {"rtl_files_found": discover_report["rtl_files_found"],
                               "files": [f["file"] for f in discover_report["files"]]}
    write_json(results_root / "summary.json", summary)
    if out_md:
        out_md.write_text(render_md(summary))
    return summary


def render_md(summary: dict) -> str:
    L = ["# Formal results (generated by `formal/forge_formal.py summarize`)", "",
         "Every row is a tool output from this checkout (kind: measured). Stand-in blocks are",
         "Amaranth-generated RTL used to exercise the tool; they are not Forge blocks.", ""]
    if "discover" in summary:
        L += [f"RTL files found in the checkout: {summary['discover']['rtl_files_found']} "
              f"({', '.join(summary['discover']['files']) or 'none'}).", ""]
    L += ["| Block | Verdict | Asserts proven | Covers reached | Mutants killed / (killed + survived) | Note |",
          "|---|---|---|---|---|---|"]
    for b in summary["blocks"]:
        mut = b.get("mutation")
        extra = []
        if mut and mut.get("equivalent"):
            extra.append(f"{mut['equivalent']} proven equivalent")
        if mut and mut.get("inconclusive"):
            extra.append(f"{mut['inconclusive']} inconclusive")
        mtxt = "not run" if not mut else (
            f"{mut['killed']} / {mut['killed'] + mut['survived']} of {mut['mutants']}, bmc depth {mut['bmc_depth']}"
            + (f" ({', '.join(extra)})" if extra else ""))
        note = "; ".join(b.get("reasons", []))
        tag = " (control)" if b.get("control") else (" (stand-in)" if b.get("standin") else "")
        L.append(f"| {b['block']}{tag} | {b.get('verdict', '-')} "
                 f"| {b.get('proven', 0)} / {b.get('asserts', 0)} | {b.get('covers_reached', 0)} / {b.get('covers', 0)} "
                 f"| {mtxt} | {note} |")
    L.append("")
    return "\n".join(L)


# =========================================================================== cli
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("discover", help="list modules/ports in RTL and write spec skeletons")
    d.add_argument("paths", nargs="+")
    d.add_argument("--out", type=Path, help="write the discover report (JSON) here")
    d.add_argument("--skeletons", type=Path, help="write one spec skeleton per module into this dir")
    r = sub.add_parser("run", help="check block specs")
    r.add_argument("specs", nargs="+", type=Path)
    m = sub.add_parser("mutate", help="mutation analysis of a spec's property set")
    m.add_argument("spec", type=Path)
    m.add_argument("--count", type=int)
    m.add_argument("--seed", type=int)
    m.add_argument("--jobs", type=int, default=4)
    s = sub.add_parser("summarize", help="collect results into summary.json and RESULTS.md")
    s.add_argument("--md", type=Path, default=FC_ROOT / "RESULTS.md")
    s.add_argument("--discover", type=Path, help="discover report to include")
    for p in (d, r, m, s):
        p.add_argument("--results", type=Path, default=DEFAULT_RESULTS)
        p.add_argument("--work", type=Path, default=DEFAULT_WORK)
    a = ap.parse_args(argv)
    tools = find_tools()
    if a.cmd != "summarize" and not (tools["yosys"] and tools["sby"]):
        print("ERROR: yosys/sby not found (install OSS CAD Suite or `pip install yowasp-yosys`)",
              file=sys.stderr)
        return 2
    if a.cmd == "discover":
        rep = discover(a.paths, tools, a.work)
        if a.out:
            write_json(a.out, rep)
        if a.skeletons:
            for f in rep["files"]:
                for mod in f["modules"]:
                    write_json(a.skeletons / f"{mod['module']}.skeleton.json", spec_skeleton(f["file"], mod))
        print(f"rtl files: {rep['rtl_files_found']}")
        for f in rep["files"]:
            print(f"  {f['file']}: " + (", ".join(m["module"] for m in f["modules"]) if f["parsed"] else "PARSE ERROR"))
        return 0
    if a.cmd == "run":
        worst = 0
        for sp in a.specs:
            v = run_spec(sp, a.results, a.work, tools)
            print(f"{v['block']}: {v['verdict']}  ({'; '.join(v['reasons'])})")
            worst = max(worst, {"PASS": 0, "INCOMPLETE": 1, "FAIL": 2}[v["verdict"]])
        return worst
    if a.cmd == "mutate":
        o = mutate_spec(a.spec, a.results, a.work, tools, a.count, a.seed, a.jobs)
        print(f"{o['block']}: {o['killed']} killed, {o['survived']} survived, "
              f"{o['equivalent']} proven equivalent, {o['inconclusive']} inconclusive "
              f"of {o['mutants']} mutants; kill rate {o['kill_rate']}")
        for r_ in o["results"]:
            if r_["class"] != "killed":
                print(f"  {r_['class']}: m{r_['id']:03d} {r_['mutation']}")
        return 0
    if a.cmd == "summarize":
        rep = load_json(a.discover) if a.discover else None
        summ = summarize(a.results, a.md, rep)
        for b in summ["blocks"]:
            print(f"{b['block']}: {b.get('verdict')}  mutation={b.get('mutation', {}).get('kill_rate')}")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
