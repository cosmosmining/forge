#!/usr/bin/env python3
"""Baseline measurements on the ORIGINAL (golden) RTL, run once before any loop.

For one block:
  1. pre-layout minimum period P_pre: bisection on pre-layout WNS >= 0 (synthesis
     is redone at every probe, because ABC targets the clock period).
  2. clock-latency calibration (only for blocks whose ORFS nangate45 SDC does
     not exist): one post-route run at 1.3 * P_pre with latency 0; the average
     clock arrival at the launching flops of the worst paths becomes the ideal
     latency used for the real and the virtual IO clock from then on.
  3. T0: bisection on post-route closure of the original RTL
     (setup WNS >= 0, hold WNS >= 0, 0 DRC errors), resolution max(4 ps, 1 %).
  4. T1 = 0.9 * T0, and the references:
       post-route: original @T0 (area, power), original @T1 (fails, as expected),
                   original @T0 layout re-timed at the T1 frequency (power reference)
       pre-layout: original @T0 and @T1, original @T0 netlist at T1 frequency
Writes targets/baseline_<block>.json. Every run directory is kept under RUNS.
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "flow"))
import run_flow  # noqa: E402

RUNS = os.environ.get("PPA_RUNS", "/opt/eda/runs")


def golden_dir(block):
    """Materialize the golden sources into one directory (hash-checked)."""
    import hashlib
    import shutil
    gate = json.load(open(os.path.join(ROOT, "gate", "blocks.json")))
    b = gate["blocks"][block]
    d = os.path.join(RUNS, "golden", block)
    os.makedirs(d, exist_ok=True)
    for rel in b["golden_files"]:
        src = os.path.join(run_flow.ORFS_ROOT, rel)
        if hashlib.sha256(open(src, "rb").read()).hexdigest() != b["golden_sha256"][rel]:
            raise SystemExit("golden source hash mismatch: " + rel)
        shutil.copy(src, os.path.join(d, os.path.basename(rel)))
    return d


def passes(m):
    """prelayout: setup only (hold and reset-removal are repaired during place and route and
    checked post-route). postroute: setup, hold and 0 DRC errors."""
    if m.get("status") != "OK" or m.get("wns_setup") is None:
        return False
    if m["mode"] == "prelayout":
        return m["wns_setup"] >= 0
    return m["wns_setup"] >= 0 and m["wns_hold"] >= 0 and m.get("drc_errors") == 0


def slim(m):
    keys = ("status", "period_ns", "wns_setup", "tns_setup", "wns_hold", "setup_violating_endpoints",
            "area_um2", "power_total_w", "drc_errors", "cells", "seq_cells", "run_dir", "flow_seconds")
    return {k: m.get(k) for k in keys}


def log(block, msg):
    print("[%s] %s" % (block, msg), flush=True)


def bisect(block, rtl, mode, lo_fail, hi_pass, tol_abs, tol_rel, latency, trail, tag):
    """lo_fail fails, hi_pass passes; shrink until hi - lo <= tol."""
    best = None
    while hi_pass - lo_fail > max(tol_abs, tol_rel * hi_pass):
        mid = round((lo_fail + hi_pass) / 2, 4)
        m = run_flow.evaluate(block, rtl, mid, mode, os.path.join(RUNS, "baseline", block, "%s_p%.4f" % (tag, mid)),
                              latency=latency)
        ok = passes(m)
        trail.append(slim(m))
        log(block, "%s %.4f ns -> %s (wns %s)" % (mode, mid, "PASS" if ok else "FAIL", m.get("wns_setup")))
        if ok:
            hi_pass = mid
            best = m
        else:
            lo_fail = mid
    return lo_fail, hi_pass, best


def bracket(block, rtl, mode, start, latency, trail, tag):
    """Find (lo_fail, hi_pass, pass_metrics) around start."""
    p = start
    m = run_flow.evaluate(block, rtl, p, mode, os.path.join(RUNS, "baseline", block, "%s_p%.4f" % (tag, p)),
                          latency=latency)
    trail.append(slim(m))
    log(block, "%s %.4f ns -> %s (wns %s)" % (mode, p, "PASS" if passes(m) else "FAIL", m.get("wns_setup")))
    if passes(m):
        hi, hi_m = p, m
        lo = None
        while lo is None:
            q = round(hi * 0.9, 4)
            mq = run_flow.evaluate(block, rtl, q, mode, os.path.join(RUNS, "baseline", block, "%s_p%.4f" % (tag, q)),
                                   latency=latency)
            trail.append(slim(mq))
            log(block, "%s %.4f ns -> %s (wns %s)" % (mode, q, "PASS" if passes(mq) else "FAIL", mq.get("wns_setup")))
            if passes(mq):
                hi, hi_m = q, mq
            else:
                lo = q
        return lo, hi, hi_m
    lo = p
    while True:
        q = round(lo * 1.12, 4)
        mq = run_flow.evaluate(block, rtl, q, mode, os.path.join(RUNS, "baseline", block, "%s_p%.4f" % (tag, q)),
                               latency=latency)
        trail.append(slim(mq))
        log(block, "%s %.4f ns -> %s (wns %s)" % (mode, q, "PASS" if passes(mq) else "FAIL", mq.get("wns_setup")))
        if passes(mq):
            return lo, q, mq
        lo = q


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--block", required=True)
    ap.add_argument("--pre-start", type=float, default=1.0)
    a = ap.parse_args()
    block = a.block
    rtl = golden_dir(block)
    flow = json.load(open(os.path.join(ROOT, "flow", "flow_config.json")))
    out = {"block": block, "rtl": rtl}
    out_path = os.path.join(HERE, "baseline_%s.json" % block)

    # 1. pre-layout minimum period (latency 0 is fine here: ideal clocks, IO paths balanced either way)
    lat_fixed = flow["blocks"][block]["clock_latency_ns"]
    lat_pre = lat_fixed if lat_fixed is not None else 0.0
    trail = []
    lo, hi, _ = bracket(block, rtl, "prelayout", a.pre_start, lat_pre, trail, "pre")
    lo, hi, _ = bisect(block, rtl, "prelayout", lo, hi, 0.002, 0.005, lat_pre, trail, "pre")
    out["prelayout_min_period_ns"] = hi
    out["prelayout_search"] = trail
    log(block, "pre-layout minimum period %.4f ns" % hi)

    # 2. latency calibration
    if lat_fixed is None:
        pcal = round(1.3 * hi, 4)
        m = run_flow.evaluate(block, rtl, pcal, "postroute", os.path.join(RUNS, "baseline", block, "cal_p%.4f" % pcal),
                              latency=0.0)
        lmin, lmax = m.get("clock_latency_min_ns"), m.get("clock_latency_max_ns")
        if lmin is None or lmax is None:
            raise SystemExit("calibration run has no clock latency report: %s" % m.get("run_dir"))
        lat = round((lmin + lmax) / 2, 3)
        out["calibration"] = {"period_ns": pcal, "cts_latency_min_ns": lmin, "cts_latency_max_ns": lmax,
                              "clock_latency_ns": lat, "run": slim(m)}
        log(block, "calibrated clock latency %.3f ns (CTS insertion delay %.4f-%.4f)" % (lat, lmin, lmax))
    else:
        lat = lat_fixed
        out["calibration"] = {"clock_latency_ns": lat, "source": "ORFS nangate45 SDC for this design"}
    out["clock_latency_ns"] = lat
    json.dump(out, open(out_path, "w"), indent=1)

    # 3. T0 by bisection on post-route closure
    trail = []
    lo, hi, best = bracket(block, rtl, "postroute", round(out["prelayout_min_period_ns"], 4), lat, trail, "post")
    lo, hi, b2 = bisect(block, rtl, "postroute", lo, hi, 0.004, 0.01, lat, trail, "post")
    best = b2 or best
    t0 = hi
    out["postroute_search"] = trail
    out["T0_ns"] = t0
    out["T1_ns"] = round(0.9 * t0, 4)
    log(block, "T0 %.4f ns, T1 %.4f ns" % (t0, out["T1_ns"]))
    json.dump(out, open(out_path, "w"), indent=1)

    # 4. references
    t1 = out["T1_ns"]
    post_t0 = best
    post_t1 = run_flow.evaluate(block, rtl, t1, "postroute", os.path.join(RUNS, "baseline", block, "ref_post_T1"),
                                latency=lat)
    pre_t0 = run_flow.evaluate(block, rtl, t0, "prelayout", os.path.join(RUNS, "baseline", block, "ref_pre_T0"),
                               latency=lat)
    pre_t1 = run_flow.evaluate(block, rtl, t1, "prelayout", os.path.join(RUNS, "baseline", block, "ref_pre_T1"),
                               latency=lat)
    nick = flow["blocks"][block]["nickname"]
    sdc_t1 = run_flow.write_sdc(os.path.join(RUNS, "baseline", block, "T1.sdc"), block, t1, lat)
    rc, txt = run_flow.run_sta(post_t0["run_dir"], "postroute", nick, sdc=sdc_t1, tag="atT1")
    mp, _, _, _ = run_flow.parse_sta(txt)
    rc, txt = run_flow.run_sta(pre_t0["run_dir"], "prelayout", nick, sdc=sdc_t1, tag="atT1")
    mq, _, _, _ = run_flow.parse_sta(txt)
    out["references"] = {
        "postroute": {"orig_at_T0": slim(post_t0), "orig_at_T1": slim(post_t1),
                      "orig_T0_layout_power_at_T1_freq_w": mp.get("power_total_w"),
                      "area_ref_um2": post_t0["area_um2"],
                      "power_ref_w": mp.get("power_total_w")},
        "prelayout": {"orig_at_T0": slim(pre_t0), "orig_at_T1": slim(pre_t1),
                      "orig_T0_netlist_power_at_T1_freq_w": mq.get("power_total_w"),
                      "area_ref_um2": pre_t0["area_um2"],
                      "power_ref_w": mq.get("power_total_w")},
    }
    out["original_fails_postroute_at_T1"] = not passes(post_t1)
    json.dump(out, open(out_path, "w"), indent=1)
    log(block, "done: orig@T1 post-route wns %s (fails=%s)" % (post_t1.get("wns_setup"),
                                                                out["original_fails_postroute_at_T1"]))


if __name__ == "__main__":
    main()
