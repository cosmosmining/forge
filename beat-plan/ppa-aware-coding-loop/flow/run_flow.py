#!/usr/bin/env python3
"""Flow harness for the PPA-aware coding loop.

Two evaluation modes for one RTL directory at one clock period:

  prelayout : ORFS synthesis (yosys + ABC, delay target = clock period), then
              OpenSTA on the synthesized netlist with no placement and no wires.
              This is the kind of number a pre-layout gate reports.
  postroute : the full ORFS flow (floorplan, placement, CTS, global + detailed
              route, fill), OpenRCX extraction from the routed layout, then
              OpenSTA with propagated clocks and the extracted parasitics.

Both modes run the same synthesis with the same settings; only the layout and
the parasitics differ. Settings come from flow_config.json (locked).

Outputs in the run directory: metrics.json, feedback.txt, sta.log, ORFS logs.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ORFS_ROOT = os.environ.get("ORFS_ROOT", "/opt/eda/orfs")
ORFS_FLOW = os.path.join(ORFS_ROOT, "flow")
YOSYS_EXE = os.environ.get("YOSYS_EXE", "/opt/eda/oss-cad-suite/bin/yosys")
OPENROAD_EXE = os.environ.get("OPENROAD_EXE", "/opt/eda/openroad/bin/openroad")
LIB = os.path.join(ORFS_FLOW, "platforms/nangate45/lib/NangateOpenCellLibrary_typical.lib")

SDC_TEMPLATE = """current_design {top}

set clk_name core_clock
set clk_port_name {clk}
set clk_period {period}
set clk_io_pct {io_pct}

set clk_port [get_ports $clk_port_name]

create_clock -name $clk_name -period $clk_period $clk_port
set clk_io_name vclk_$clk_name
create_clock -name $clk_io_name -period $clk_period
set_clock_latency {lat} [get_clocks $clk_name]
set_clock_latency {lat} [get_clocks $clk_io_name]

set non_clock_inputs [all_inputs -no_clocks]

set_input_delay [expr $clk_period * $clk_io_pct] -clock $clk_io_name $non_clock_inputs
set_output_delay [expr $clk_period * $clk_io_pct] -clock $clk_io_name [all_outputs]
"""


def load_cfg():
    flow = json.load(open(os.path.join(HERE, "flow_config.json")))
    gate = json.load(open(os.path.join(ROOT, "gate", "blocks.json")))
    lat_file = os.path.join(ROOT, "targets", "calibration.json")
    lat = json.load(open(lat_file))["clock_latency_ns"] if os.path.exists(lat_file) else {}
    return flow, gate, lat


def rtl_files(block, rtl_dir, gate):
    include_only = set(gate["blocks"][block].get("include_only", []))
    files = sorted(os.path.join(rtl_dir, f) for f in os.listdir(rtl_dir)
                   if f.endswith(".v") and f not in include_only)
    if not files:
        raise SystemExit("no .v files in %s" % rtl_dir)
    return files


def write_sdc(path, block, period, latency=None):
    flow, gate, cal = load_cfg()
    b = flow["blocks"][block]
    lat = latency if latency is not None else b["clock_latency_ns"]
    if lat is None:
        lat = cal.get(block)
    with open(path, "w") as f:
        f.write(SDC_TEMPLATE.format(top=b["top"], clk=b["clock_port"], period="%.4f" % period,
                                    io_pct=flow["clk_io_pct"], lat="%.3f" % lat))
    return path


def prepare(run_dir, block, rtl_dir, period, latency=None):
    flow, gate, cal = load_cfg()
    b = flow["blocks"][block]
    lat = latency if latency is not None else b["clock_latency_ns"]
    if lat is None:
        lat = cal.get(block)
    if lat is None:
        raise SystemExit("no clock latency for %s (run calibration first)" % block)
    os.makedirs(run_dir, exist_ok=True)
    sdc = os.path.join(run_dir, "constraint.sdc")
    with open(sdc, "w") as f:
        f.write(SDC_TEMPLATE.format(top=b["top"], clk=b["clock_port"], period="%.4f" % period,
                                    io_pct=flow["clk_io_pct"], lat="%.3f" % lat))
    rtl_dir = os.path.abspath(rtl_dir)
    lines = ["export DESIGN_NICKNAME = %s" % b["nickname"],
             "export DESIGN_NAME = %s" % b["top"],
             "export PLATFORM = %s" % flow["platform"],
             "export VERILOG_FILES = %s" % " ".join(rtl_files(block, rtl_dir, gate)),
             "export VERILOG_INCLUDE_DIRS = %s" % rtl_dir,
             "export SDC_FILE = %s" % sdc]
    for k, v in list(flow["common"].items()) + list(b["vars"].items()):
        lines.append("export %s := %s" % (k, v) if v == "" else "export %s = %s" % (k, v))
    with open(os.path.join(run_dir, "config.mk"), "w") as f:
        f.write("\n".join(lines) + "\n")
    return b, flow


def orfs(run_dir, target, nick, num_cores, timeout):
    env = dict(os.environ)
    env.update({"YOSYS_EXE": YOSYS_EXE, "OPENROAD_EXE": OPENROAD_EXE})
    cmd = ["make", "-C", ORFS_FLOW, "DESIGN_CONFIG=%s" % os.path.join(run_dir, "config.mk"),
           "WORK_HOME=%s" % run_dir, "FLOW_VARIANT=base", "NUM_CORES=%d" % num_cores, target]
    t0 = time.time()
    with open(os.path.join(run_dir, "make.log"), "a") as log:
        log.write("\n### %s\n" % " ".join(cmd))
        log.flush()
        try:
            p = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, env=env, timeout=timeout)
            rc = p.returncode
        except subprocess.TimeoutExpired:
            rc = "timeout"
    return rc, time.time() - t0


def run_sta(run_dir, mode, nick, npaths=6, sdc=None, tag=None):
    """STA on a finished run. sdc overrides the run's own constraints (used to evaluate
    an existing netlist/layout at another clock frequency, e.g. power references)."""
    res = os.path.join(run_dir, "results", "nangate45", nick, "base")
    env = dict(os.environ)
    env.update({"STA_MODE": mode, "STA_LIB": LIB, "STA_PATHS": str(npaths)})
    if mode == "prelayout":
        env.update({"STA_DB": os.path.join(res, "1_synth.odb"), "STA_SDC": sdc or os.path.join(res, "1_synth.sdc")})
    else:
        env.update({"STA_DB": os.path.join(res, "6_final.odb"), "STA_SDC": sdc or os.path.join(res, "6_1_fill.sdc"),
                    "STA_SPEF": os.path.join(res, "6_final.spef")})
    log = os.path.join(run_dir, "sta_%s%s.log" % (mode, ("_" + tag) if tag else ""))
    with open(log, "w") as f:
        p = subprocess.run([OPENROAD_EXE, "-no_init", "-exit", os.path.join(HERE, "sta_report.tcl")],
                           stdout=f, stderr=subprocess.STDOUT, env=env, timeout=3600)
    return p.returncode, open(log, errors="replace").read()


def _section(txt, name):
    m = re.search(r"@@BEGIN_%s\n(.*?)@@END_%s" % (name, name), txt, re.S)
    return m.group(1) if m else ""


def _json_checks(chunk):
    out = []
    dec = json.JSONDecoder()
    i = chunk.find('{"checks"')
    while i >= 0:
        obj, end = dec.raw_decode(chunk[i:])
        out += obj.get("checks", [])
        i = chunk.find('{"checks"', i + end)
    return out


def parse_sta(txt):
    m = {}
    for key in ("WNS_SETUP", "TNS_SETUP", "WNS_HOLD", "TNS_HOLD"):
        mm = re.search(r"@@%s (\S+)" % key, txt)
        m[key.lower()] = float(mm.group(1)) if mm else None
    for key in ("SETUP_VIOLATING_ENDPOINTS", "ENDPOINTS", "CELLS", "SEQ_CELLS"):
        mm = re.search(r"@@%s (\d+)" % key, txt)
        m[key.lower()] = int(mm.group(1)) if mm else None
    pw = re.search(r"^Total\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)", _section(txt, "POWER"), re.M)
    if pw:
        m["power_internal_w"], m["power_switching_w"], m["power_leakage_w"], m["power_total_w"] = \
            [float(x) for x in pw.groups()]
    cl = re.search(r"^\s*([\d.]+)\s+([\d.]+)\s+latency\s*$", _section(txt, "CLKLAT"), re.M)
    if cl:
        m["clock_latency_min_ns"], m["clock_latency_max_ns"] = float(cl.group(1)), float(cl.group(2))
    ar = re.search(r"Design area ([\d.]+) u", _section(txt, "AREA"))
    m["area_um2_rounded"] = float(ar.group(1)) if ar else None
    fan = {}
    for line in _section(txt, "FANOUT").splitlines():
        parts = line.rsplit(" ", 1)
        if len(parts) == 2 and parts[1].isdigit():
            fan[parts[0]] = int(parts[1])
    paths = _json_checks(_section(txt, "PATHS"))
    hold = _json_checks(_section(txt, "HOLD_PATH"))
    return m, paths, hold, fan


def summarize_path(p, fan, mode):
    """Turn one OpenSTA JSON path into stage-level numbers (ns, um)."""
    ns = 1e9
    src = p.get("source_path", [])
    clk_launch = (p["source_clock_path"][-1]["arrival"] * ns) if p.get("source_clock_path") else 0.0
    stages = []
    wire_total = 0.0
    cell_total = 0.0
    prev = None
    for pt in src:
        pin = pt["pin"]
        arr = pt["arrival"] * ns
        if prev is None:
            prev = pt
            continue
        d = arr - prev["arrival"] * ns
        same_inst = pt.get("instance") and pt.get("instance") == prev.get("instance")
        if same_inst:
            cell_total += d
            cap = pt.get("capacitance")
            stages.append({"inst": pt["instance"], "cell": pt["cell"], "out_pin": pin, "cell_delay": d,
                           "load_ff": cap * 1e15 if cap is not None else None,
                           "net": pt.get("net", ""), "fanout": fan.get(pt.get("net", ""), None)})
        else:
            wire_total += d
            dist = None
            if prev.get("x") is not None and pt.get("x") is not None:
                dist = (abs(pt["x"] - prev["x"]) + abs(pt["y"] - prev["y"])) * 1e6
            if stages:
                stages[-1]["wire_to_next"] = d
                stages[-1]["dist_um"] = dist
            elif d > 0:
                stages.append({"inst": "(input)", "cell": "", "out_pin": prev["pin"], "cell_delay": 0.0,
                               "net": prev.get("net", ""), "wire_to_next": d, "dist_um": dist,
                               "fanout": fan.get(prev.get("net", ""), None)})
        prev = pt
    first_arr = src[0]["arrival"] * ns if src else 0.0
    end_arr = p["data_arrival_time"] * ns
    tclk = p.get("target_clock_path") or []
    capture_lat = None
    if tclk:
        capture_lat = tclk[-1]["arrival"] * ns
    return {
        "slack": p["slack"] * ns,
        "startpoint": p["startpoint"], "endpoint": p["endpoint"],
        "path_group": p.get("path_group"),
        "arrival": end_arr, "required": p["required_time"] * ns,
        "launch_clock_or_input_delay": first_arr,
        "clk_launch_latency": clk_launch,
        "clk_capture_arrival": capture_lat,
        "setup_or_margin": (p.get("margin") or 0.0) * ns,
        "cell_delay": cell_total, "wire_delay": wire_total, "stages": stages,
    }


def rtl_name(pin):
    """dpath.a_reg.out[15]$_DFFE_PP_/Q -> dpath.a_reg.out[15]"""
    name = pin.rsplit("/", 1)[0] if "/" in pin else pin
    return re.sub(r"\$_[A-Z0-9_]+_?$", "", name)


def feedback_text(block, mode, period, metrics, paths, hold, refs=None, top_n=5):
    L = []
    title = "POST-ROUTE (routed layout, OpenRCX parasitics, propagated clocks)" if mode == "postroute" \
        else "PRE-LAYOUT (synthesized netlist, no wires, ideal clocks)"
    L.append("=== %s feedback | block %s | clock period %.4f ns ===" % (title, block, period))
    L.append("setup WNS %+.4f ns | TNS %.4f ns | failing endpoints %s of %s"
             % (metrics["wns_setup"], metrics["tns_setup"], metrics["setup_violating_endpoints"],
                metrics["endpoints"]))
    if mode == "postroute":
        L.append("hold WNS %+.4f ns | DRC errors %s" % (metrics["wns_hold"], metrics.get("drc_errors")))
    area, pw = metrics.get("area_um2"), metrics.get("power_total_w")
    if refs:
        L.append("area %.1f um2 (reference %.1f, %+.2f %%) | power %.4f mW (reference %.4f, %+.2f %%)"
                 % (area, refs["area_um2"], 100 * (area / refs["area_um2"] - 1), pw * 1e3,
                    refs["power_total_w"] * 1e3, 100 * (pw / refs["power_total_w"] - 1)))
    else:
        L.append("area %.1f um2 | power %.4f mW" % (area, pw * 1e3))
    L.append("cells %s (sequential %s)" % (metrics.get("cells"), metrics.get("seq_cells")))
    if mode == "postroute" and metrics.get("orfs"):
        o = metrics["orfs"]
        L.append("timing-repair buffers %s (%.1f um2) | clock buffers %s | ORFS setup WS %+.4f ns"
                 % (o.get("repair_buffers"), o.get("repair_buffer_area") or 0, o.get("clock_buffers"),
                    o.get("setup_ws") or 0))
    L.append("")
    seen = set()
    shown = 0
    L.append("Worst setup paths (one per endpoint, worst first). Delays in ns.")
    for sp in sorted(paths, key=lambda s: s["slack"]):
        key = rtl_name(sp["endpoint"])
        if key in seen:
            continue
        seen.add(key)
        shown += 1
        tot = sp["cell_delay"] + sp["wire_delay"]
        wpct = 100 * sp["wire_delay"] / tot if tot > 0 else 0
        L.append("#%d slack %+.4f | %s -> %s | group %s" % (shown, sp["slack"], rtl_name(sp["startpoint"]),
                                                             sp["endpoint"], sp["path_group"]))
        L.append("   arrival %.4f (path starts at %.4f) | logic %.4f = cell delays %.4f + interconnect RC %.4f | %d stages"
                 % (sp["arrival"], sp["launch_clock_or_input_delay"], tot, sp["cell_delay"], sp["wire_delay"],
                    len(sp["stages"])))
        if sp["clk_capture_arrival"] is not None:
            L.append("   capture clock arrival %.4f | required %.4f" % (sp["clk_capture_arrival"], sp["required"]))
        if shown <= 2:
            L.append("   stages (output pin, cell: cell delay incl. load | RC to next pin | load fF, fanout, driver-to-sink distance | net):")
            for st in sp["stages"]:
                extra = []
                if st.get("load_ff") is not None:
                    extra.append("%.1f fF" % st["load_ff"])
                if st.get("fanout"):
                    extra.append("fanout %d" % st["fanout"])
                if st.get("dist_um"):
                    extra.append("%.1f um" % st["dist_um"])
                L.append("     %-34s %-12s %.4f | %.4f | %s | net %s"
                         % (st["out_pin"][:34], st["cell"], st["cell_delay"], st.get("wire_to_next", 0.0),
                            ", ".join(extra) or "-", st["net"][:50]))
        if shown >= top_n:
            break
    if hold:
        h = summarize_path(hold[0], {}, mode)
        L.append("")
        L.append("Worst hold path: slack %+.4f | %s -> %s" % (h["slack"], rtl_name(h["startpoint"]), h["endpoint"]))
    hf = sorted(((n, f) for n, f in metrics.get("high_fanout", {}).items() if not n.startswith("clknet")),
                key=lambda x: -x[1])[:8]
    if hf:
        L.append("")
        L.append("Highest-fanout signal nets: " + ", ".join("%s (%d)" % (n, f) for n, f in hf))
    return "\n".join(L) + "\n"


def orfs_metrics(run_dir, nick):
    logs = os.path.join(run_dir, "logs", "nangate45", nick, "base")
    out = {}
    try:
        r = json.load(open(os.path.join(logs, "6_report.json")))
        out = {"setup_ws": r.get("finish__timing__setup__ws"), "setup_tns": r.get("finish__timing__setup__tns"),
               "hold_ws": r.get("finish__timing__hold__ws"), "power_total": r.get("finish__power__total"),
               "area_stdcell": r.get("finish__design__instance__area__stdcell"),
               "repair_buffers": r.get("finish__design__instance__count__class:timing_repair_buffer"),
               "repair_buffer_area": r.get("finish__design__instance__area__class:timing_repair_buffer"),
               "clock_buffers": r.get("finish__design__instance__count__class:clock_buffer"),
               "core_area": r.get("finish__design__core__area"), "die_area": r.get("finish__design__die__area")}
    except Exception:
        pass
    try:
        r = json.load(open(os.path.join(logs, "5_2_route.json")))
        out["drc_errors"] = r.get("detailedroute__route__drc_errors")
    except Exception:
        pass
    try:
        r = json.load(open(os.path.join(logs, "1_synth.json")))
        out["synth_area"] = r.get("synth__design__instance__area__stdcell")
    except Exception:
        pass
    return out


def prune(run_dir, nick):
    res = os.path.join(run_dir, "results", "nangate45", nick, "base")
    keep = {"1_synth.odb", "1_synth.sdc", "1_2_yosys.v", "6_final.odb", "6_final.spef", "6_final.v",
            "6_1_fill.sdc", "clock_period.txt"}
    if os.path.isdir(res):
        for f in os.listdir(res):
            if f not in keep:
                p = os.path.join(res, f)
                if os.path.isfile(p):
                    os.remove(p)
    shutil.rmtree(os.path.join(run_dir, "objects"), ignore_errors=True)


def evaluate(block, rtl_dir, period, mode, run_dir, latency=None, refs=None, keep_all=False):
    run_dir = os.path.abspath(run_dir)
    if os.path.exists(run_dir):
        shutil.rmtree(run_dir)
    b, flow = prepare(run_dir, block, rtl_dir, period, latency)
    nick = b["nickname"]
    t0 = time.time()
    res_dir = os.path.join(run_dir, "results", "nangate45", nick, "base")
    if mode == "prelayout":
        target = os.path.join(res_dir, "1_synth.odb")
        rc, el = orfs(run_dir, target, nick, flow["num_cores"], 3600)
    else:
        target = os.path.join(run_dir, "logs", "nangate45", nick, "base", "6_report.log")
        rc, el = orfs(run_dir, target, nick, flow["num_cores"], 4 * 3600)
    metrics = {"block": block, "mode": mode, "period_ns": period, "rtl_dir": os.path.abspath(rtl_dir),
               "run_dir": run_dir, "flow_seconds": round(el, 1)}
    if rc != 0:
        tail = open(os.path.join(run_dir, "make.log"), errors="replace").read()[-3000:]
        metrics.update({"status": "FLOW_FAIL", "error_tail": tail})
        json.dump(metrics, open(os.path.join(run_dir, "metrics.json"), "w"), indent=1)
        open(os.path.join(run_dir, "feedback.txt"), "w").write(
            "FLOW FAILED in mode %s (exit %s). Last lines of the log:\n%s\n" % (mode, rc, tail))
        return metrics
    src, txt = run_sta(run_dir, mode, nick)
    m, paths, hold, fan = parse_sta(txt)
    metrics.update(m)
    metrics["high_fanout"] = fan
    if mode == "postroute":
        o = orfs_metrics(run_dir, nick)
        metrics["orfs"] = o
        metrics["drc_errors"] = o.get("drc_errors")
        metrics["area_um2"] = o.get("area_stdcell")
    else:
        o = orfs_metrics(run_dir, nick)
        metrics["area_um2"] = o.get("synth_area")
    if metrics.get("area_um2") is None:
        metrics["area_um2"] = metrics.get("area_um2_rounded")
    sp = [summarize_path(p, fan, mode) for p in paths]
    metrics["worst_paths"] = [{k: v for k, v in s.items() if k != "stages"} for s in
                              sorted(sp, key=lambda s: s["slack"])[:6]]
    metrics["status"] = "OK" if src == 0 and metrics.get("wns_setup") is not None else "STA_FAIL"
    metrics["seconds"] = round(time.time() - t0, 1)
    json.dump(metrics, open(os.path.join(run_dir, "metrics.json"), "w"), indent=1)
    open(os.path.join(run_dir, "feedback.txt"), "w").write(
        feedback_text(block, mode, period, metrics, sp, hold, refs))
    if mode == "postroute" and not keep_all:
        prune(run_dir, nick)
    return metrics


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--block", required=True)
    ap.add_argument("--rtl", required=True)
    ap.add_argument("--period", type=float, required=True)
    ap.add_argument("--mode", choices=["prelayout", "postroute"], required=True)
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--latency", type=float, default=None, help="calibration only")
    a = ap.parse_args()
    m = evaluate(a.block, a.rtl, a.period, a.mode, a.run_dir, a.latency)
    print(json.dumps({k: m.get(k) for k in ("status", "wns_setup", "tns_setup", "wns_hold", "area_um2",
                                            "power_total_w", "drc_errors", "seconds")}))


if __name__ == "__main__":
    main()
