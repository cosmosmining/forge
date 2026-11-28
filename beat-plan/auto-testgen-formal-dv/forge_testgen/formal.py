"""Formal pack: SymbiYosys jobs generated from the block spec + golden model.

Jobs
  equiv     comb blocks: every output == translated golden, for every legal
            input (complete proof; the miter has no state).
  witness   coverage closure: one cover per hole bin over the golden +
            constraints; reached -> concrete test vector, unreached -> the
            bin is proven unreachable and excluded from the denominator.
  stream    valid/ready blocks: environment assumptions (upstream holds
            valid+data until accepted, legal data), assertions (quiet after
            reset, output held under backpressure, no output without input,
            capacity bound, bounded latency, symbolic-tracking data check
            against the golden) and cover properties (non-vacuity).
  miter     mutant vs original RTL (equivalent-mutant detection).

Status vocabulary (honest, never upgraded):
  PROVEN      unbounded proof (comb miter, k-induction or PDR)
  BOUNDED(n)  no counterexample within n cycles from reset; not a proof
  FAIL        counterexample found (and replayed in simulation when possible)
  UNKNOWN     solver gave up / timed out without either result
"""

import os
import re
import shutil
import time

from . import tools
from .golden import _vname
from .tb import total_bits

# --------------------------------------------------------------------------
# sby runner


class SbyResult:
    def __init__(self, name, workdir):
        self.name, self.workdir = name, workdir
        self.status = "ERROR"
        self.failed = []          # assertion labels with a real (basecase/bmc) cex
        self.cex_trace = None     # VCD of the real counterexample
        self.induction_failed = False
        self.reached = {}         # cover label -> VCD trace
        self.unreached = []
        self.seconds = 0.0
        self.log = ""
        self.engine = None

    def to_dict(self):
        return {"job": self.name, "status": self.status, "failed": self.failed,
                "reached": sorted(self.reached), "unreached": self.unreached,
                "seconds": round(self.seconds, 2), "engine": self.engine,
                "workdir": self.workdir}


def run_sby(workdir, name, mode, script, files, engines, depth=20, timeout=300, extra_opts=()):
    tools.require("sby", "yosys", "yosys-smtbmc")
    os.makedirs(workdir, exist_ok=True)
    job_dir = os.path.join(workdir, name)
    if os.path.isdir(job_dir):
        shutil.rmtree(job_dir)
    sby = ["[options]", "mode %s" % mode, "depth %d" % depth, "timeout %d" % timeout]
    sby += list(extra_opts)
    sby += ["", "[engines]"] + list(engines)
    sby += ["", "[script]"] + list(script)
    sby += ["", "[files]"] + list(files)
    path = os.path.join(workdir, name + ".sby")
    with open(path, "w") as fh:
        fh.write("\n".join(sby) + "\n")
    t0 = time.time()
    rc, out, timed_out = tools.run(["sby", "-f", name + ".sby"], cwd=workdir, timeout=timeout + 120)
    res = SbyResult(name, job_dir)
    res.seconds = time.time() - t0
    res.log = out
    res.engine = "; ".join(engines)
    status_file = os.path.join(job_dir, "status")
    if os.path.exists(status_file):
        with open(status_file) as fh:
            first = (fh.read().split() or ["ERROR"])[0]
        res.status = first
    if timed_out:
        res.status = "TIMEOUT"
    _parse_summary(res, out)
    return res


_SUM_CEX = re.compile(r"summary: counterexample trace(?: \[(\w+)\])?: (\S+)")
_SUM_FAIL = re.compile(r"summary:\s+failed assertion (\S+) at")
_REACHED = re.compile(r"Reached cover statement in step \d+ at \S+: (\S+)")
_TRACE = re.compile(r"Writing trace to VCD file: (\S+)")
_SUM_COVTRACE = re.compile(r"summary: cover trace: (\S+)")
_SUM_REACHED = re.compile(r"summary:\s+reached cover statement (\S+) at")
_UNREACHED_SUM = re.compile(r"summary:\s+(\S+) at \S+$")


def _parse_summary(res, log):
    lines = log.splitlines()
    current_real = None
    in_unreached = False
    pending_covers = []
    sum_trace = None
    for line in lines:
        m = _SUM_CEX.search(line)
        if m:
            kind, trace = m.group(1), m.group(2)
            current_real = kind in (None, "basecase")
            if kind == "induction":
                res.induction_failed = True
            if current_real and res.cex_trace is None:
                res.cex_trace = os.path.join(os.path.dirname(res.workdir), trace)
            continue
        m = _SUM_FAIL.search(line)
        if m and current_real:
            res.failed.append(m.group(1).split(".")[-1])
            continue
        m = _SUM_COVTRACE.search(line)
        if m:
            sum_trace = os.path.join(os.path.dirname(res.workdir), m.group(1))
            continue
        m = _SUM_REACHED.search(line)
        if m and sum_trace:
            res.reached[m.group(1).split(".")[-1]] = sum_trace
            continue
        m = _REACHED.search(line)
        if m:
            pending_covers.append(m.group(1))
            continue
        m = _TRACE.search(line)
        if m and pending_covers:
            # several covers reached in the same step share one trace
            for lab in pending_covers:
                res.reached.setdefault(lab, os.path.join(res.workdir, m.group(1)))
            pending_covers = []
            continue
        if "summary: unreached cover statements:" in line:
            in_unreached = True
            continue
        if in_unreached:
            m = _UNREACHED_SUM.search(line)
            if m and "summary:   " in line:
                lab = m.group(1).split(".")[-1]
                if lab not in res.unreached:
                    res.unreached.append(lab)
                continue
            in_unreached = False
        if "Unreached cover statement at" in line:
            lab = line.rsplit(":", 1)[-1].strip()
            if lab not in res.unreached:
                res.unreached.append(lab)


# --------------------------------------------------------------------------
# VCD


def read_vcd(path):
    """-> (signals {(scope_path, name): width}, steps [ {(scope,name): int} ])."""
    ids, scope = {}, []
    signals = {}
    steps, cur, cur_t = [], {}, None
    t_id = None

    def flush():
        if cur_t is not None:
            while len(steps) <= cur_t:
                steps.append({})
            steps[cur_t] = {ids[k]: v for k, v in cur.items() if k in ids}

    with open(path) as fh:
        tokens_mode = True
        for raw in fh:
            line = raw.strip()
            if not line:
                continue
            if line.startswith("$scope"):
                scope.append(line.split()[2])
            elif line.startswith("$upscope"):
                scope.pop()
            elif line.startswith("$var"):
                parts = line.split()
                width, vid, name = int(parts[2]), parts[3], parts[4]
                if name == "smt_step":
                    t_id = vid
                    continue
                key = (".".join(scope), name)
                ids[vid] = key
                signals[key] = width
            elif line.startswith("#"):
                continue
            elif line[0] in "bB":
                val, vid = line[1:].split()
                v = int(val.replace("x", "0").replace("z", "0"), 2)
                if vid == t_id:
                    flush()
                    cur_t = v
                else:
                    cur[vid] = v
            elif line[0] in "01xz" and len(line) > 1:
                vid = line[1:]
                v = 0 if line[0] in "0xz" else 1
                cur[vid] = v
    flush()
    # carry values forward
    last = {}
    for i, s in enumerate(steps):
        merged = dict(last)
        merged.update(s)
        steps[i] = merged
        last = merged
    return signals, steps


def top_value(steps, step, top, name):
    return steps[step].get((top, name))


# --------------------------------------------------------------------------
# helpers to emit wrappers


def _decl_ports(fields, prefix):
    return ["  input  [%d:0] %s%s" % (f.total_bits - 1, prefix, f.name) for f in fields]


def _slices(fields, bus):
    out, off = {}, 0
    for f in fields:
        out[f.name] = "%s[%d:%d]" % (bus, off + f.total_bits - 1, off)
        off += f.total_bits
    return out


def write_ref(spec, workdir):
    tr = spec.model.translate()
    path = os.path.join(workdir, "ref_%s.v" % spec.name)
    with open(path, "w") as fh:
        fh.write(tr.verilog("ref_%s" % spec.name))
    return path, tr


def _ref_inst(spec, tr, inst, in_map, out_map, ok=None, cok=None, extra=None):
    conns = [".g_%s(%s)" % (f.name, in_map[f.name]) for f in spec.inputs]
    conns += [".g_%s(%s)" % (f.name, out_map.get(f.name, "")) for f in spec.outputs]
    conns.append(".ok(%s)" % (ok or ""))
    conns.append(".constraints_ok(%s)" % (cok or ""))
    extra = extra or {}
    for k in sorted(tr.golden_covers):
        conns.append(".gcov_%s(%s)" % (_vname(k), extra.get("gcov_" + _vname(k), "")))
    for k in sorted(tr.spec_bins):
        conns.append(".bin_%s(%s)" % (_vname(k), extra.get("bin_" + _vname(k), "")))
    for k in sorted(tr.boundary_bins):
        conns.append(".bnd_%s(%s)" % (_vname(k), extra.get("bnd_" + _vname(k), "")))
    return "  ref_%s %s (\n    %s\n  );" % (spec.name, inst, ",\n    ".join(conns))


def _read_lines(paths):
    return ["read -formal %s" % os.path.basename(p) for p in paths]


# --------------------------------------------------------------------------
# comb equivalence


def comb_equiv(spec, workdir, rtl=None, timeout=600, engine="smtbmc bitwuzla"):
    rtl = rtl or spec.rtl
    os.makedirs(workdir, exist_ok=True)
    ref_path, tr = write_ref(spec, workdir)
    lines = ["module fv_equiv ("]
    lines.append(",\n".join(_decl_ports(spec.inputs, "i_")))
    lines.append(");")
    for f in spec.outputs:
        lines.append("  wire [%d:0] d_%s, r_%s;" % (f.total_bits - 1, f.name, f.name))
    lines.append("  wire r_ok, r_cok;")
    conns = [".%s(i_%s)" % (f.port, f.name) for f in spec.inputs]
    conns += [".%s(d_%s)" % (f.port, f.name) for f in spec.outputs]
    lines.append("  %s dut (%s);" % (spec.top, ", ".join(conns)))
    lines.append(_ref_inst(spec, tr, "ref", {f.name: "i_" + f.name for f in spec.inputs},
                           {f.name: "r_" + f.name for f in spec.outputs}, "r_ok", "r_cok"))
    lines.append("  always @* begin")
    lines.append("    assume (r_cok);")
    lines.append("    golden_fits_ports: assert (r_ok);")
    for f in spec.outputs:
        lines.append("    eq_%s: assert (d_%s == r_%s);" % (f.name, f.name, f.name))
    lines.append("  end")
    lines.append("endmodule")
    wrap = os.path.join(workdir, "fv_equiv.sv")
    with open(wrap, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    files = list(rtl) + [ref_path, wrap]
    script = _read_lines(files) + ["prep -flatten -top fv_equiv"]
    res = run_sby(workdir, "equiv", "prove", script, files, [engine], depth=1, timeout=timeout)
    res.kind = "comb_equiv"
    if res.status == "PASS":
        res.verdict = "PROVEN"
    elif res.status == "FAIL" and res.failed:
        res.verdict = "FAIL"
        res.cex_vector = _comb_cex_vector(spec, res.cex_trace)
    else:
        res.verdict = "UNKNOWN"
    return res


def _comb_cex_vector(spec, trace):
    if not trace or not os.path.exists(trace):
        return None
    sigs, steps = read_vcd(trace)
    top = [k for k in sigs if k[1].startswith("i_")]
    if not top or not steps:
        return None
    scope = top[0][0]
    vec = {}
    for f in spec.inputs:
        bits = steps[0].get((scope, "i_" + f.name))
        if bits is None:
            return None
        vec[f.name] = f.decode(bits)
    return vec


# --------------------------------------------------------------------------
# coverage witnesses


def witnesses(spec, workdir, bins, timeout=300, engine="smtbmc bitwuzla"):
    """Cover each data/golden bin over the golden + constraints.

    Returns {bin: vector} for reached bins and a list of proven-unreachable bins.
    """
    os.makedirs(workdir, exist_ok=True)
    ref_path, tr = write_ref(spec, workdir)
    lines = ["module fv_witness ("]
    lines.append(",\n".join(_decl_ports(spec.inputs, "i_")))
    lines.append(");")
    extra, labels = {}, {}
    for b in bins:
        if b.startswith("golden."):
            port = "gcov_" + _vname(b[7:])
        elif b.startswith("boundary."):
            port = "bnd_" + _vname(b)
        else:
            port = "bin_" + _vname(b)
        wire = "h_" + _vname(b)
        extra[port] = wire
        labels["c_" + _vname(b)] = b
        lines.append("  wire %s;" % wire)
    lines.append("  wire r_cok;")
    lines.append(_ref_inst(spec, tr, "ref", {f.name: "i_" + f.name for f in spec.inputs}, {},
                           None, "r_cok", extra))
    lines.append("  always @* begin")
    lines.append("    assume (r_cok);")
    for lab, b in labels.items():
        lines.append("    %s: cover (h_%s);" % (lab, _vname(b)))
    lines.append("  end")
    lines.append("endmodule")
    wrap = os.path.join(workdir, "fv_witness.sv")
    with open(wrap, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    files = [ref_path, wrap]
    script = _read_lines(files) + ["prep -flatten -top fv_witness"]
    res = run_sby(workdir, "witness", "cover", script, files, [engine], depth=1, timeout=timeout)
    found, unreachable = {}, []
    for lab, trace in res.reached.items():
        b = labels.get(lab)
        if b is None:
            continue
        sigs, steps = read_vcd(trace)
        scope = [k for k in sigs if k[1].startswith("i_")][0][0]
        step = len(steps) - 1
        vec = {f.name: f.decode(steps[step][(scope, "i_" + f.name)]) for f in spec.inputs}
        found[b] = vec
    complete = res.status in ("PASS", "FAIL")
    for lab in res.unreached:
        if lab in labels and complete:
            unreachable.append(labels[lab])
    return found, unreachable, res


# --------------------------------------------------------------------------
# stream properties


def stream_wrapper(spec, tr, top=None):
    s = spec.stream
    top = top or spec.top
    iw, ow = total_bits(spec.inputs), total_bits(spec.outputs)
    cap = s.get("capacity")
    maxlat = int(s.get("max_latency", 16))
    cw = max(4, (int(cap) + 2).bit_length() + 1) if cap else 8
    lw = max(4, (maxlat + 2).bit_length() + 1)
    max_stall = int(s.get("max_stall", maxlat + (int(cap) if cap else 0) + 1))
    sw = max(4, (max_stall + 2).bit_length() + 1)
    below_cap = bool(s.get("accepts_below_capacity")) and bool(cap)
    has_rdy_in, has_rdy_out = bool(s.get("in_ready")), bool(s.get("out_ready"))
    isl, osl = _slices(spec.inputs, "in_data"), _slices(spec.outputs, "out_data")
    conns = [".%s(clk)" % s["clk"],
             ".%s(%s)" % (s["rst"], "rst_i" if s.get("rst_active", "high") == "high" else "!rst_i"),
             ".%s(in_valid)" % s["in_valid"], ".%s(out_valid)" % s["out_valid"]]
    if has_rdy_in:
        conns.append(".%s(in_ready)" % s["in_ready"])
    if has_rdy_out:
        conns.append(".%s(out_ready)" % s["out_ready"])
    conns += [".%s(%s)" % (f.port, isl[f.name]) for f in spec.inputs]
    conns += [".%s(%s)" % (f.port, osl[f.name]) for f in spec.outputs]
    expn = _slices(spec.outputs, "exp_now")
    L = []
    L.append("module fv_stream (")
    L.append("  input clk,")
    L.append("  input rst_i,")
    L.append("  input in_valid,")
    L.append("  input [%d:0] in_data," % (iw - 1))
    L.append("  input out_ready_i,")
    L.append("  input f_pick")
    L.append(");")
    L.append("  wire in_ready, out_valid;")
    L.append("  wire [%d:0] out_data;" % (ow - 1))
    L.append("  wire out_ready = %s;" % ("out_ready_i" if has_rdy_out else "1'b1"))
    if not has_rdy_in:
        L.append("  assign in_ready = 1'b1;")
    L.append("  %s dut (%s);" % (top, ", ".join(conns)))
    L.append("  reg f_past_valid = 1'b0;")
    L.append("  always @(posedge clk) f_past_valid <= 1'b1;")
    L.append("  wire acc = in_valid && in_ready;")
    L.append("  wire emit = out_valid && out_ready;")
    L.append("  reg [%d:0] f_inflight = 0;" % (cw - 1))
    L.append("  reg [%d:0] f_wait = 0;" % (lw - 1))
    L.append("  reg [%d:0] f_istall = 0;" % (sw - 1))
    L.append("  reg f_armed = 1'b0, f_done = 1'b0;")
    L.append("  reg [%d:0] f_ahead = 0;" % (cw - 1))
    L.append("  wire pick_now = !f_armed && acc && f_pick;")
    L.append("  wire passthru = pick_now && emit && (f_inflight == 0);")
    L.append("  wire tracked_out = f_armed && !f_done && emit && (f_ahead == 0);")
    L.append("  // The golden is applied to the input in the cycle it is accepted and the")
    L.append("  // EXPECTED OUTPUT is stored: DUT and golden then operate on the same input")
    L.append("  // variables, which keeps the data proof tractable for SAT/PDR.")
    L.append("  wire [%d:0] exp_now;" % (ow - 1))
    L.append("  reg  [%d:0] f_exp = 0;" % (ow - 1))
    L.append("  wire c_ok;")
    L.append(_ref_inst(spec, tr, "ref_now", {f.name: isl[f.name] for f in spec.inputs},
                       {f.name: expn[f.name] for f in spec.outputs}, None, "c_ok"))
    L.append("  always @(posedge clk) begin")
    L.append("    if (rst_i) begin")
    L.append("      f_inflight <= 0; f_wait <= 0; f_istall <= 0; f_armed <= 1'b0; f_done <= 1'b0;")
    L.append("    end else begin")
    L.append("      if (in_valid && !in_ready && out_ready) begin")
    L.append("        if (f_istall != {%d{1'b1}}) f_istall <= f_istall + 1;" % sw)
    L.append("      end else f_istall <= 0;")
    L.append("      f_inflight <= f_inflight + (acc ? 1 : 0) - (emit ? 1 : 0);")
    L.append("      if (emit || f_inflight == 0 || (f_inflight == 1 && emit)) f_wait <= 0;")
    L.append("      else if (out_ready && f_wait != {%d{1'b1}}) f_wait <= f_wait + 1;" % lw)
    L.append("      if (pick_now) begin")
    L.append("        f_armed <= 1'b1;")
    L.append("        f_exp <= exp_now;")
    L.append("        if (passthru) f_done <= 1'b1;")
    L.append("        else f_ahead <= f_inflight - (emit ? 1 : 0);")
    L.append("      end else if (f_armed && !f_done && emit) begin")
    L.append("        if (f_ahead == 0) f_done <= 1'b1;")
    L.append("        else f_ahead <= f_ahead - 1;")
    L.append("      end")
    L.append("    end")
    L.append("  end")
    # environment
    L.append("  always @(*) if (!f_past_valid) assume (rst_i);")
    L.append("  always @(*) if (in_valid) assume (c_ok);")
    L.append("  always @(posedge clk) if (f_past_valid && !$past(rst_i) && !rst_i && "
             "$past(in_valid && !in_ready)) begin")
    L.append("    assume (in_valid);")
    L.append("    assume (in_data == $past(in_data));")
    L.append("  end")
    # assertions
    L.append("  always @(posedge clk) if (f_past_valid && $past(rst_i) && !rst_i && !in_valid) begin")
    L.append("    a_quiet_after_reset: assert (!out_valid);")
    L.append("  end")
    if has_rdy_out:
        L.append("  always @(posedge clk) if (f_past_valid && !$past(rst_i) && !rst_i && "
                 "$past(out_valid && !out_ready)) begin")
        L.append("    a_hold_valid: assert (out_valid);")
        L.append("    a_hold_data: assert (out_data == $past(out_data));")
        L.append("  end")
    L.append("  always @(*) if (!rst_i) begin")
    L.append("    a_no_spurious_output: assert (!emit || f_inflight != 0 || acc);")
    if cap:
        L.append("    a_capacity: assert (f_inflight <= %d);" % int(cap))
    L.append("    a_bounded_latency: assert (f_wait <= %d);" % maxlat)
    if has_rdy_in:
        L.append("    a_input_progress: assert (f_istall <= %d);" % max_stall)
    if below_cap and has_rdy_in:
        # an offered input must be taken while fewer than `capacity` are in flight
        # (ready may legally wait for valid, so only checked when in_valid is high)
        L.append("    a_accepts_below_capacity: assert (!in_valid || in_ready || f_inflight >= %d);" % int(cap))
    L.append("    a_data_matches_golden: assert (!(tracked_out && out_data != f_exp) &&")
    L.append("                                   !(passthru && out_data != exp_now));")
    L.append("    c_output: cover (emit);")
    L.append("    c_tracked_checked: cover (tracked_out);")
    if has_rdy_out:
        L.append("    c_backpressure: cover (out_valid && !out_ready);")
    if has_rdy_in:
        L.append("    c_input_stall: cover (in_valid && !in_ready);")
    if cap:
        L.append("    c_full: cover (f_inflight == %d);" % int(cap))
    L.append("  end")
    L.append("endmodule")
    return "\n".join(L) + "\n"


ASSERT_LABELS = ["a_quiet_after_reset", "a_hold_valid", "a_hold_data", "a_no_spurious_output",
                 "a_capacity", "a_bounded_latency", "a_input_progress", "a_accepts_below_capacity",
                 "a_data_matches_golden"]


def stream_props(spec, workdir, rtl=None, depth=None, prove_timeout=None, do_cover=True):
    rtl = rtl or spec.rtl
    os.makedirs(workdir, exist_ok=True)
    ref_path, tr = write_ref(spec, workdir)
    wrap = os.path.join(workdir, "fv_stream.sv")
    text = stream_wrapper(spec, tr)
    with open(wrap, "w") as fh:
        fh.write(text)
    labels = [l for l in ASSERT_LABELS if (l + ":") in text]
    files = list(rtl) + [ref_path, wrap]
    script = _read_lines(files) + ["prep -flatten -top fv_stream"]
    depth = int(depth or spec.formal.get("depth", 24))
    prove_timeout = int(prove_timeout or spec.formal.get("prove_timeout", 300))
    out = {"labels": labels, "jobs": []}
    # 1. unbounded attempt: PDR (finds inductive invariants itself)
    prove = run_sby(workdir, "prove", "prove", script, files, ["abc pdr"], depth=depth,
                    timeout=prove_timeout)
    out["jobs"].append(prove.to_dict())
    verdict = None
    if prove.status == "PASS":
        verdict = ("PROVEN", None)
    elif prove.status == "FAIL" and prove.failed:
        verdict = ("FAIL", prove)
    # 2. bounded model check (always when not proven; finds shortest cex)
    bmc = None
    if verdict is None or verdict[0] == "FAIL":
        bmc = run_sby(workdir, "bmc", "bmc", script, files, ["smtbmc bitwuzla"], depth=depth,
                      timeout=prove_timeout)
        out["jobs"].append(bmc.to_dict())
        if bmc.status == "FAIL" and bmc.failed:
            verdict = ("FAIL", bmc)
        elif verdict is None and bmc.status == "PASS":
            verdict = ("BOUNDED(%d)" % depth, None)
        elif verdict is None:
            verdict = ("UNKNOWN", None)
    out["verdict"] = verdict[0]
    failing = verdict[1]
    out["failed"] = failing.failed if failing else []
    out["cex_trace"] = failing.cex_trace if failing else None
    out["per_property"] = {l: (("FAIL" if failing and l in failing.failed else
                               ("PASS-by-%s" % verdict[0] if not failing else "not-failed-before-cex")))
                           for l in labels}
    if do_cover:
        cov = run_sby(workdir, "cover", "cover", script, files, ["smtbmc bitwuzla"],
                      depth=depth, timeout=prove_timeout)
        out["jobs"].append(cov.to_dict())
        out["covers_reached"] = sorted(cov.reached)
        out["covers_unreached"] = cov.unreached
    return out


def stream_cex_inputs(spec, trace):
    """Per-step stimulus from a stream counterexample (for simulation replay)."""
    sigs, steps = read_vcd(trace)
    scope = [k for k in sigs if k[1] == "rst_i"][0][0]
    seq = []
    for st in steps:
        seq.append({k: st.get((scope, k), 0) for k in ("rst_i", "in_valid", "in_data", "out_ready_i")})
    return seq


# --------------------------------------------------------------------------
# mutant vs original miters (equivalent-mutant detection)


def _rename_modules(src_text, names, suffix):
    for n in sorted(names, key=len, reverse=True):
        src_text = re.sub(r"\b%s\b" % re.escape(n), n + suffix, src_text)
    return src_text


def module_names(paths):
    names = set()
    for p in paths:
        with open(p) as fh:
            names |= set(re.findall(r"^\s*module\s+(\w+)", fh.read(), flags=re.M))
    return names


def miter(spec, workdir, mutant_files, depth=None, timeout=300):
    """Prove mutant == original (all outputs, every legal input sequence)."""
    os.makedirs(workdir, exist_ok=True)
    names = module_names(spec.rtl)
    renamed = []
    for p in mutant_files:
        with open(p) as fh:
            text = _rename_modules(fh.read(), names, "__mut")
        q = os.path.join(workdir, "mut_" + os.path.basename(p))
        with open(q, "w") as fh:
            fh.write(text)
        renamed.append(q)
    ref_path, tr = write_ref(spec, workdir)
    if spec.kind == "comb":
        L = ["module fv_miter ("] + [",\n".join(_decl_ports(spec.inputs, "i_"))] + [");"]
        for f in spec.outputs:
            L.append("  wire [%d:0] a_%s, b_%s;" % (f.total_bits - 1, f.name, f.name))
        L.append("  wire r_cok;")
        for inst, mod, pre in (("orig", spec.top, "a_"), ("mut", spec.top + "__mut", "b_")):
            conns = [".%s(i_%s)" % (f.port, f.name) for f in spec.inputs]
            conns += [".%s(%s%s)" % (f.port, pre, f.name) for f in spec.outputs]
            L.append("  %s %s (%s);" % (mod, inst, ", ".join(conns)))
        L.append(_ref_inst(spec, tr, "legal", {f.name: "i_" + f.name for f in spec.inputs}, {},
                           None, "r_cok"))
        L.append("  always @* begin")
        L.append("    assume (r_cok);")
        for f in spec.outputs:
            L.append("    same_%s: assert (a_%s == b_%s);" % (f.name, f.name, f.name))
        L.append("  end")
        L.append("endmodule")
        top, mode, engines, d = "fv_miter", "prove", ["smtbmc bitwuzla"], 1
    else:
        s = spec.stream
        iw, ow = total_bits(spec.inputs), total_bits(spec.outputs)
        isl = _slices(spec.inputs, "in_data")
        L = ["module fv_miter (input clk, input rst_i, input in_valid, input [%d:0] in_data, "
             "input out_ready_i);" % (iw - 1)]
        L.append("  wire out_ready = %s;" % ("out_ready_i" if s.get("out_ready") else "1'b1"))
        for pre in ("a_", "b_"):
            L.append("  wire %sin_ready, %sout_valid;" % (pre, pre))
            L.append("  wire [%d:0] %sout_data;" % (ow - 1, pre))
            if not s.get("in_ready"):
                L.append("  assign %sin_ready = 1'b1;" % pre)
        for inst, mod, pre in (("orig", spec.top, "a_"), ("mut", spec.top + "__mut", "b_")):
            osl = _slices(spec.outputs, pre + "out_data")
            conns = [".%s(clk)" % s["clk"],
                     ".%s(%s)" % (s["rst"], "rst_i" if s.get("rst_active", "high") == "high" else "!rst_i"),
                     ".%s(in_valid)" % s["in_valid"], ".%s(%sout_valid)" % (s["out_valid"], pre)]
            if s.get("in_ready"):
                conns.append(".%s(%sin_ready)" % (s["in_ready"], pre))
            if s.get("out_ready"):
                conns.append(".%s(out_ready)" % s["out_ready"])
            conns += [".%s(%s)" % (f.port, isl[f.name]) for f in spec.inputs]
            conns += [".%s(%s)" % (f.port, osl[f.name]) for f in spec.outputs]
            L.append("  %s %s (%s);" % (mod, inst, ", ".join(conns)))
        L.append("  wire c_ok;")
        L.append(_ref_inst(spec, tr, "legal", {f.name: isl[f.name] for f in spec.inputs}, {},
                           None, "c_ok"))
        L.append("  reg f_past_valid = 1'b0;")
        L.append("  always @(posedge clk) f_past_valid <= 1'b1;")
        L.append("  always @(*) if (!f_past_valid) assume (rst_i);")
        L.append("  always @(*) if (in_valid) assume (c_ok);")
        L.append("  always @(posedge clk) if (f_past_valid && !$past(rst_i) && !rst_i && "
                 "$past(in_valid && !a_in_ready)) begin")
        L.append("    assume (in_valid); assume (in_data == $past(in_data));")
        L.append("  end")
        L.append("  always @(*) if (!rst_i) begin")
        L.append("    same_in_ready: assert (a_in_ready == b_in_ready);")
        L.append("    same_out_valid: assert (a_out_valid == b_out_valid);")
        L.append("    if (a_out_valid) same_out_data: assert (a_out_data == b_out_data);")
        L.append("  end")
        L.append("endmodule")
        top, mode, engines = "fv_miter", "prove", ["abc pdr"]
        d = int(depth or spec.formal.get("depth", 24))
    wrap = os.path.join(workdir, "fv_miter.sv")
    with open(wrap, "w") as fh:
        fh.write("\n".join(L) + "\n")
    files = list(spec.rtl) + renamed + [ref_path, wrap]
    script = _read_lines(files) + ["prep -flatten -top %s" % top]
    res = run_sby(workdir, "miter", mode, script, files, engines, depth=d, timeout=timeout)
    if res.status == "PASS":
        return "EQUIVALENT", res
    if res.status == "FAIL" and res.failed:
        return "DIFFERENT", res
    if spec.kind == "stream":
        b = run_sby(workdir, "miter_bmc", "bmc", script, files, ["smtbmc bitwuzla"], depth=d,
                    timeout=timeout)
        if b.status == "FAIL" and b.failed:
            return "DIFFERENT", b
        if b.status == "PASS":
            return "EQUIVALENT-BOUNDED(%d)" % d, b
    return "UNKNOWN", res
