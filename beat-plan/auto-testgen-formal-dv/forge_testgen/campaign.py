"""The test-generation agent loop for one block.

  1. spec <-> RTL port check (yosys)                 spec errors stop the run
  2. golden translation self-check                   translator errors stop the run
  3. directed + constrained-random generation
  4. coverage closure: golden-guided search, then formal witnesses;
     bins the solver proves unreachable are excluded (with the proof job named)
  5. simulation (expected values from the golden; TB compares; Python re-checks)
  6. formal: comb -> equivalence proof; stream -> protocol + data properties
  7. every formal counterexample is replayed in simulation before it counts
"""

import json
import os
import shutil
import time

from . import formal, gen, sim, tb, tools
from .spec import Spec, SpecError


class Suite:
    """Generated tests for one block, grouped by origin."""

    def __init__(self, spec):
        self.spec = spec
        self.groups = {}          # group -> list of (origin, vec)
        self.expected = {}        # group -> list of output dicts
        self.scenarios = []       # stream protocol scenarios

    def add(self, group, origin, vec, out):
        self.groups.setdefault(group, []).append((origin, vec))
        self.expected.setdefault(group, []).append(out)

    def count(self):
        return {g: len(v) for g, v in self.groups.items()}


def _hard_issues(issues):
    return [i for i in issues if not i.startswith("note:")]


def build_suite(spec, workdir, seed=1, n_random=None, closure=True, use_formal_witness=True,
                log=print):
    gm = spec.model
    g = gen.Generator(spec, seed)
    cov = gen.Coverage(spec)
    suite = Suite(spec)
    n_random = int(n_random if n_random is not None else spec.gen.get("random", 2000))

    def take(group, items):
        for origin, vec in items:
            out, gcov = gm.evaluate(vec)
            cov.add(vec, out, gcov, origin)
            suite.add(group, origin, vec, out)

    take("directed", g.directed())
    after_directed = cov.summary()
    take("random", g.random(n_random))
    after_random = cov.summary()
    closure_log = []
    if closure:
        kinds = ("data", "golden", "boundary")
        budget = int(spec.gen.get("closure_budget", 5000))
        if use_formal_witness and cov.holes(kinds=kinds):
            # 1) ask the solver: a witness vector, or a proof the bin is unreachable
            holes = cov.holes(kinds=kinds)
            found, unreachable, res = formal.witnesses(spec, os.path.join(workdir, "witness"), holes)
            for b, vec in found.items():
                if not gm.legal(vec):
                    closure_log.append({"bin": b, "how": "formal witness REJECTED (illegal vector)"})
                    continue
                out, gcov = gm.evaluate(vec)
                if not cov.hit_by(b, vec, out, gcov):
                    closure_log.append({"bin": b, "how": "formal witness REJECTED (Python golden "
                                                         "disagrees: translator issue)"})
                    continue
                take("closure", [("closure.witness:%s" % b, vec)])
                closure_log.append({"bin": b, "how": "formal witness (sby cover)"})
            for b in unreachable:
                cov.excluded[b] = "proven unreachable under the constraints (sby cover, %s)" % (
                    os.path.relpath(res.workdir, workdir))
                closure_log.append({"bin": b, "how": "proven unreachable"})
        # 2) golden-guided search for whatever is still open (or everything, without formal)
        for b in cov.holes(kinds=kinds):
            vec = g.target(cov, b, budget=budget)
            if vec is not None:
                take("closure", [("closure.search:%s" % b, vec)])
                closure_log.append({"bin": b, "how": "golden-guided search"})
    if spec.kind == "stream":
        total = sum(len(v) for v in suite.groups.values())
        suite.scenarios = g.scenarios(total)
    return suite, cov, {
        "after_directed": after_directed, "after_random": after_random,
        "closure": closure_log, "directed_dropped_unsat": len(g.dropped),
    }


def _write_comb_run(spec, suite, groups, workdir, rtl, simulator):
    os.makedirs(workdir, exist_ok=True)
    vecs, exps = [], []
    for grp in groups:
        vecs += [v for _, v in suite.groups.get(grp, [])]
        exps += suite.expected.get(grp, [])
    if not vecs:
        return None, []
    exp_bits = [tb.pack(spec.outputs, o) for o in exps]
    tb.write_hex(os.path.join(workdir, "stim.hex"), [tb.pack(spec.inputs, v) for v in vecs],
                 tb.total_bits(spec.inputs))
    tb.write_hex(os.path.join(workdir, "exp.hex"), exp_bits, tb.total_bits(spec.outputs))
    with open(os.path.join(workdir, "tb.v"), "w") as fh:
        fh.write(tb.comb_tb(spec.top, spec.inputs, spec.outputs, len(vecs)))
    res = sim.run(workdir, "tb.v", rtl, simulator=simulator)
    return res, exp_bits


def _write_stream_run(spec, suite, groups, scenario, workdir, rtl, simulator):
    os.makedirs(workdir, exist_ok=True)
    name, gaps, rdy = scenario
    vecs, exps = [], []
    for grp in groups:
        vecs += [v for _, v in suite.groups.get(grp, [])]
        exps += suite.expected.get(grp, [])
    if not vecs:
        return None, []
    gaps = (gaps * (len(vecs) // max(1, len(gaps)) + 1))[:len(vecs)]
    if not spec.stream.get("out_ready"):
        rdy = [1]
    exp_bits = [tb.pack(spec.outputs, o) for o in exps]
    tb.write_hex(os.path.join(workdir, "stim.hex"), [tb.pack(spec.inputs, v) for v in vecs],
                 tb.total_bits(spec.inputs))
    tb.write_hex(os.path.join(workdir, "gap.hex"), gaps, 8)
    tb.write_hex(os.path.join(workdir, "rdy.hex"), rdy, 1)
    tb.write_hex(os.path.join(workdir, "exp.hex"), exp_bits, tb.total_bits(spec.outputs))
    with open(os.path.join(workdir, "tb.v"), "w") as fh:
        fh.write(tb.stream_tb(spec.top, spec.inputs, spec.outputs, len(vecs), len(exps), len(rdy),
                              spec.stream, int(spec.stream.get("max_latency", 16))))
    res = sim.run(workdir, "tb.v", rtl, simulator=simulator)
    return res, exp_bits


def run_sims(spec, suite, workdir, rtl=None, simulator="iverilog", groups=None):
    """Run every test group (and every protocol scenario for streams).

    Returns {run_name: {"ok", "errors", "messages", "recheck"...}}.
    """
    rtl = rtl or spec.rtl
    groups = groups or list(suite.groups)
    results = {}
    for grp in groups:
        if spec.kind == "comb":
            runs = [(grp, None)]
        else:
            runs = [("%s.%s" % (grp, sc[0]), sc) for sc in suite.scenarios]
        for run_name, sc in runs:
            wd = os.path.join(workdir, run_name)
            if spec.kind == "comb":
                res, exp_bits = _write_comb_run(spec, suite, [grp], wd, rtl, simulator)
            else:
                res, exp_bits = _write_stream_run(spec, suite, [grp], sc, wd, rtl, simulator)
            if res is None:
                continue
            entry = {"ok": res.ok, "errors": res.errors, "compiled": res.compiled,
                     "timed_out": res.timed_out, "messages": res.first_messages, "cov": res.cov,
                     "vectors": len(exp_bits)}
            # independent Python re-check of what the DUT produced
            got_path = os.path.join(wd, "got.hex")
            if res.compiled and os.path.exists(got_path):
                got = tb.read_hex(got_path)
                bad = sum(1 for a, b in zip(got, exp_bits) if a != b) + abs(len(got) - len(exp_bits))
                entry["recheck_mismatches"] = bad
                if res.ok and bad:
                    entry["ok"] = False
                    entry["messages"].append("python re-check found %d mismatches the TB missed" % bad)
            results[run_name] = entry
    return results


# --------------------------------------------------------------------------
# counterexample replay


def replay_comb(spec, vec, workdir, rtl, simulator="iverilog"):
    os.makedirs(workdir, exist_ok=True)
    out, _ = spec.model.evaluate(vec)
    exp = tb.pack(spec.outputs, out)
    tb.write_hex(os.path.join(workdir, "stim.hex"), [tb.pack(spec.inputs, vec)], tb.total_bits(spec.inputs))
    tb.write_hex(os.path.join(workdir, "exp.hex"), [exp], tb.total_bits(spec.outputs))
    with open(os.path.join(workdir, "tb.v"), "w") as fh:
        fh.write(tb.comb_tb(spec.top, spec.inputs, spec.outputs, 1))
    res = sim.run(workdir, "tb.v", rtl, simulator=simulator)
    got = tb.read_hex(os.path.join(workdir, "got.hex")) if res.compiled else []
    confirmed = bool(res.compiled and not res.ok)
    return {"confirmed": confirmed, "vector": vec, "expected": out,
            "got_bits": got[0] if got else None, "messages": res.first_messages}


def replay_stream(spec, seq, workdir, rtl, simulator="iverilog"):
    """Drive the DUT with the per-step stimulus of a formal counterexample and
    check the same properties in Python on what the simulator produced."""
    os.makedirs(workdir, exist_ok=True)
    s = spec.stream
    iw, ow = tb.total_bits(spec.inputs), tb.total_bits(spec.outputs)
    words = []
    for st in seq:
        w = (st["in_data"] & ((1 << iw) - 1))
        w |= (st["rst_i"] & 1) << iw
        w |= (st["in_valid"] & 1) << (iw + 1)
        w |= (st["out_ready_i"] & 1) << (iw + 2)
        words.append(w)
    tb.write_hex(os.path.join(workdir, "seq.hex"), words, iw + 3)
    conns = [".%s(clk)" % s["clk"],
             ".%s(%s)" % (s["rst"], "rst_i" if s.get("rst_active", "high") == "high" else "~rst_i"),
             ".%s(in_valid)" % s["in_valid"], ".%s(out_valid)" % s["out_valid"]]
    if s.get("in_ready"):
        conns.append(".%s(in_ready)" % s["in_ready"])
    if s.get("out_ready"):
        conns.append(".%s(out_ready)" % s["out_ready"])
    off = 0
    for f in spec.inputs:
        conns.append(".%s(in_data[%d:%d])" % (f.port, off + f.total_bits - 1, off))
        off += f.total_bits
    off = 0
    for f in spec.outputs:
        conns.append(".%s(out_data[%d:%d])" % (f.port, off + f.total_bits - 1, off))
        off += f.total_bits
    text = """`timescale 1ns/1ps
module tb;
  reg clk = 1'b0, rst_i = 1'b1, in_valid = 1'b0, out_ready_r = 1'b0;
  reg [%(iw1)d:0] in_data = 0;
  wire out_valid;
  %(in_ready)s
  wire out_ready = %(out_ready)s;
  wire [%(ow1)d:0] out_data;
  %(top)s dut (%(conns)s);
  reg [%(sw1)d:0] seq [0:%(n1)d];
  integer k, fd;
  initial begin
    $readmemh("seq.hex", seq);
    fd = $fopen("obs.txt", "w");
    for (k = 0; k <= %(n1)d; k = k + 1) begin
      {out_ready_r, in_valid, rst_i, in_data} = seq[k];
      #1;
      $fwrite(fd, "%%0d %%b %%b %%h\\n", k, in_ready, out_valid, out_data);
      #4 clk = 1'b1;
      #5 clk = 1'b0;
    end
    $fclose(fd);
    $display("RESULT errors=0");
    $finish;
  end
endmodule
""" % {"iw1": iw - 1, "ow1": ow - 1, "top": spec.top, "conns": ", ".join(conns),
       "sw1": iw + 2, "n1": len(words) - 1,
       "in_ready": "wire in_ready;" if s.get("in_ready") else "wire in_ready = 1'b1;",
       "out_ready": "out_ready_r" if s.get("out_ready") else "1'b1"}
    with open(os.path.join(workdir, "tb.v"), "w") as fh:
        fh.write(text)
    res = sim.run(workdir, "tb.v", rtl, simulator=simulator)
    if not res.compiled or not os.path.exists(os.path.join(workdir, "obs.txt")):
        return {"confirmed": False, "violations": ["replay did not run"], "log": res.log[-1500:]}
    obs = []
    with open(os.path.join(workdir, "obs.txt")) as fh:
        for line in fh:
            k, rdy, vld, dat = line.split()
            obs.append((int(k), rdy, vld, dat))
    return {"confirmed": None, **check_stream_trace(spec, seq, obs)}


def check_stream_trace(spec, seq, obs):
    gm = spec.model
    s = spec.stream
    cap = s.get("capacity")
    maxlat = int(s.get("max_latency", 16))
    has_out_ready = bool(s.get("out_ready"))
    has_in_ready = bool(s.get("in_ready"))
    max_stall = int(s.get("max_stall", maxlat + (int(cap) if cap else 0) + 1))
    below_cap = bool(s.get("accepts_below_capacity")) and bool(cap) and has_in_ready
    viol, queue, wait, istall = [], [], 0, 0
    prev = None
    for (k, rdy, vld, dat), st in zip(obs, seq):
        rst = st["rst_i"] & 1
        in_valid = st["in_valid"] & 1
        out_ready = (st["out_ready_i"] & 1) if has_out_ready else 1
        if "x" in rdy + vld or "z" in rdy + vld:
            if not rst:
                viol.append("step %d: X/Z on in_ready/out_valid" % k)
            prev = None
            continue
        in_ready, out_valid = int(rdy), int(vld)
        data = None if any(c in dat.lower() for c in "xz") else int(dat, 16)
        if rst:
            queue, wait, istall = [], 0, 0
            prev = ("rst",)
            continue
        if in_valid and not in_ready and out_ready:
            istall += 1
            if istall > max_stall:
                viol.append("step %d: input not accepted for %d cycles with out_ready high" % (k, istall))
        else:
            istall = 0
        if below_cap and in_valid and not in_ready and len(queue) < int(cap):
            viol.append("step %d: input refused with %d of %s in flight" % (k, len(queue), cap))
        if prev and prev[0] == "rst" and not in_valid and out_valid:
            viol.append("step %d: out_valid right after reset with no input" % k)
        if prev and prev[0] == "run" and has_out_ready and prev[1] and not prev[2]:
            if not out_valid:
                viol.append("step %d: out_valid dropped while stalled" % k)
            elif data != prev[3]:
                viol.append("step %d: out_data changed while stalled" % k)
        acc = in_valid and in_ready
        emit = out_valid and out_ready
        if acc:
            vec = tb.unpack(spec.inputs, st["in_data"])
            queue.append(gm.evaluate(vec)[0] if gm.legal(vec) else None)
        if emit:
            if not queue:
                viol.append("step %d: output with no accepted input" % k)
            else:
                exp = queue.pop(0)
                if exp is not None and data != tb.pack(spec.outputs, exp):
                    viol.append("step %d: out_data %s != golden %s" % (k, dat, exp))
        if cap and len(queue) > int(cap):
            viol.append("step %d: %d in flight > capacity %s" % (k, len(queue), cap))
        if emit or not queue:
            wait = 0
        elif out_ready:
            wait += 1
            if wait > maxlat:
                viol.append("step %d: no output for %d ready cycles (latency bound %d)" % (k, wait, maxlat))
        prev = ("run", out_valid, out_ready, data)
    return {"confirmed": bool(viol), "violations": viol[:5]}


# --------------------------------------------------------------------------


def run_formal(spec, workdir, rtl=None, replay=True, simulator="iverilog"):
    rtl = rtl or spec.rtl
    t0 = time.time()
    if spec.kind == "comb":
        res = formal.comb_equiv(spec, os.path.join(workdir, "formal"), rtl=rtl,
                                timeout=int(spec.formal.get("prove_timeout", 600)))
        out = {"kind": "comb_equivalence", "verdict": res.verdict, "failed": res.failed,
               "properties": ["golden_fits_ports"] + ["eq_%s" % f.name for f in spec.outputs],
               "job": res.to_dict()}
        if res.verdict == "FAIL" and replay:
            vec = getattr(res, "cex_vector", None)
            out["cex"] = (replay_comb(spec, vec, os.path.join(workdir, "replay"), rtl, simulator)
                          if vec else {"confirmed": False, "note": "could not read cex"})
    else:
        r = formal.stream_props(spec, os.path.join(workdir, "formal"), rtl=rtl)
        out = {"kind": "stream_properties", **r}
        if r["verdict"] == "FAIL" and replay and r.get("cex_trace"):
            seq = formal.stream_cex_inputs(spec, r["cex_trace"])
            out["cex"] = replay_stream(spec, seq, os.path.join(workdir, "replay"), rtl, simulator)
    out["seconds"] = round(time.time() - t0, 1)
    return out


def run_block(spec_path, outdir, seed=1, n_random=None, simulator="iverilog", do_formal=True,
              closure=True, log=print):
    spec = Spec(spec_path)
    outdir = os.path.abspath(outdir)
    if os.path.isdir(outdir):
        shutil.rmtree(outdir)
    os.makedirs(outdir)
    t0 = time.time()
    report = {"block": spec.summary(), "seed": seed, "simulator": simulator,
              "tool_versions": tools.versions()}
    issues = spec.check_against_rtl(outdir)
    report["spec_vs_rtl"] = issues
    if _hard_issues(issues):
        report["verdict"] = "SPEC-ERROR"
        _save(outdir, report)
        return report, None
    tr = spec.model.translate()
    report["golden_translation"] = tr.stats()
    suite, cov, gen_info = build_suite(spec, outdir, seed=seed, n_random=n_random, closure=closure,
                                       use_formal_witness=do_formal, log=log)
    # translator self-check on every generated vector
    bad = 0
    for grp, items in suite.groups.items():
        for (origin, vec), exp in zip(items, suite.expected[grp]):
            if tr.evaluate(vec)[0] != exp:
                bad += 1
    report["translator_selfcheck_mismatches"] = bad
    report["tests"] = suite.count()
    report["generation"] = gen_info
    sims = run_sims(spec, suite, os.path.join(outdir, "sim"), simulator=simulator)
    for name, entry in sims.items():
        if spec.kind == "stream" and entry.get("cov"):
            cov.add_proto(entry["cov"], "sim:" + name)
    report["simulation"] = sims
    report["coverage"] = cov.summary()
    sim_ok = all(e["ok"] for e in sims.values())
    if do_formal:
        report["formal"] = run_formal(spec, outdir, simulator=simulator)
        fv = report["formal"]["verdict"]
    else:
        fv = "SKIPPED"
    if bad:
        verdict = "TOOL-ERROR"
    elif not sim_ok or fv == "FAIL":
        verdict = "FAIL"
    elif fv in ("UNKNOWN",):
        verdict = "INCOMPLETE"
    else:
        verdict = "PASS"
    report["verdict"] = verdict
    report["seconds"] = round(time.time() - t0, 1)
    _save(outdir, report)
    with open(os.path.join(outdir, "suite.json"), "w") as fh:
        json.dump({"groups": {g: [{"origin": o, "vec": v} for o, v in items]
                              for g, items in suite.groups.items()},
                   "scenarios": [list(s) for s in suite.scenarios]}, fh)
    return report, suite


def _save(outdir, report):
    with open(os.path.join(outdir, "report.json"), "w") as fh:
        json.dump(report, fh, indent=1, sort_keys=True, default=str)
