#!/usr/bin/env python3
"""Final evaluation of both arms (run by the harness after the agents stop).

For every (arm, block): take the candidate declared with `loop.py final` (the
original RTL if none was declared), re-run the locked gate, run the full
post-route flow at T1 in a fresh directory, and apply the success rule from
targets.json. Also checks that a post-route result the post-route arm saw for
the same candidate is reproduced (the flow is deterministic).

Writes results/final_eval.json and copies each final RTL to results/finals/.
"""
import argparse
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "flow"))
sys.path.insert(0, os.path.join(ROOT, "gate"))
sys.path.insert(0, os.path.join(ROOT, "loop"))
import loop  # noqa: E402
import run_flow  # noqa: E402
import gate as gate_mod  # noqa: E402

RUNS = os.environ.get("PPA_RUNS", "/opt/eda/runs")
BLOCKS = ["gcd", "aes_cipher_top", "riscv", "dct_mac", "dctub", "jpeg_qnr"]
ARMS = ["prelayout", "postroute"]


def final_candidate(arm, block):
    fin = [e for e in loop.ledger_entries(arm, block) if e.get("action") == "final"]
    return (fin[-1]["cand"], fin[-1]["sha"]) if fin else (None, None)


def evaluate_one(arm, block, t, manifest):
    cand, sha = final_candidate(arm, block)
    if cand is None:
        rtl = os.path.join(RUNS, "final", "original", block)
        os.makedirs(rtl, exist_ok=True)
        for p in loop.golden_files(block):
            shutil.copy(p, rtl)
        cand = "original (no final declared)"
    else:
        rtl = loop.cand_rtl(arm, block, cand)
        if loop.cand_sha(rtl) != sha:
            raise SystemExit("final candidate %s/%s/%s changed after it was declared" % (arm, block, cand))
    keep = os.path.join(HERE, "finals", arm, block)
    shutil.rmtree(keep, ignore_errors=True)
    shutil.copytree(rtl, keep)
    g = gate_mod.Gate(block, rtl, os.path.join(RUNS, "final", "gate", arm, block), manifest).run()
    t1 = t["T1_ns"]
    ref = t["references"]["postroute"]
    m = run_flow.evaluate(block, rtl, t1, "postroute", os.path.join(RUNS, "final", "flow", arm, block), refs=ref)
    j = loop.judge(m, ref, "postroute", t1) if m.get("status") == "OK" else {"meets_target": False}
    # did the arm itself see a post-route result for this exact candidate?
    seen = [e for e in loop.ledger_entries(arm, block)
            if e.get("action") == "eval" and e.get("mode") == "postroute" and e.get("sha") == sha]
    repro = None
    if seen:
        a = seen[-1]["metrics"]
        repro = {"in_loop_wns": a.get("wns_setup"), "final_wns": m.get("wns_setup"),
                 "in_loop_area": a.get("area_um2"), "final_area": m.get("area_um2"),
                 "identical": a.get("wns_setup") == m.get("wns_setup") and a.get("area_um2") == m.get("area_um2")}
    n_eval = {mode: sum(1 for e in loop.ledger_entries(arm, block) if e.get("action") == "eval"
                        and e.get("mode") == mode) for mode in ("prelayout", "postroute")}
    n_gate = sum(1 for e in loop.ledger_entries(arm, block) if e.get("action") == "gate")
    return {"arm": arm, "block": block, "final_candidate": cand, "sha": sha,
            "gate_verdict": g["verdict"], "gate_formal": g["checks"].get("formal", {}).get("strength"),
            "T1_ns": t1, "metrics": {k: m.get(k) for k in ("status", "wns_setup", "tns_setup", "wns_hold",
                                                          "setup_violating_endpoints", "area_um2",
                                                          "power_total_w", "drc_errors", "cells", "seq_cells")},
            "judgement": j, "success": bool(j.get("meets_target") and g["verdict"] == "PASS"),
            "evaluations_used": n_eval, "gate_runs": n_gate, "reproduced": repro, "run_dir": m.get("run_dir")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arms", default=",".join(ARMS))
    ap.add_argument("--blocks", default=",".join(BLOCKS))
    a = ap.parse_args()
    loop.verify_lock()
    tg = json.load(open(os.path.join(ROOT, "targets", "targets.json")))
    manifest = json.load(open(os.path.join(ROOT, "gate", "blocks.json")))
    path = os.path.join(HERE, "final_eval.json")
    out = json.load(open(path)) if os.path.exists(path) else {"results": {}}
    for arm in a.arms.split(","):
        for block in a.blocks.split(","):
            r = evaluate_one(arm, block, tg["blocks"][block], manifest)
            out["results"]["%s/%s" % (arm, block)] = r
            json.dump(out, open(path, "w"), indent=1)
            print(json.dumps({k: r[k] for k in ("arm", "block", "final_candidate", "gate_verdict", "success")}),
                  r["metrics"]["wns_setup"], r["judgement"], flush=True)


if __name__ == "__main__":
    main()
