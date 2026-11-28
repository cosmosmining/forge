#!/usr/bin/env python3
"""PPA-aware coding loop: the only entry point the RTL-editing agent uses.

  loop.py new    --arm ARM --block B [--from cNN]   create the next candidate (copy of cNN or of the original)
  loop.py gate   --arm ARM --block B --cand cNN     run the locked correctness gate
  loop.py eval   --arm ARM --block B --cand cNN --mode prelayout|postroute
                                                   evaluate a gated candidate at the target clock T1
  loop.py status --arm ARM --block B               candidates, verdicts, metrics, budget left
  loop.py final  --arm ARM --block B --cand cNN     declare the final candidate (once)

Arms:
  prelayout : feedback = pre-layout synthesis + STA only (no wires).  postroute evaluation is refused.
  postroute : feedback = full place-and-route at T1 (OpenRCX parasitics); pre-layout screening also allowed.

Every call first checks LOCK.sha256: if the gate, flow, targets or this file changed, it refuses to run.
Every action is appended to ledger/ledger.jsonl.
"""
import argparse
import datetime
import hashlib
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "flow"))
sys.path.insert(0, os.path.join(ROOT, "gate"))

RUNS = os.environ.get("PPA_RUNS", "/opt/eda/runs")
LEDGER = os.path.join(ROOT, "ledger", "ledger.jsonl")
LOCK = os.path.join(ROOT, "LOCK.sha256")
BUDGET = {  # evaluations per (arm, block); locked with this file
    "prelayout": {"prelayout": 20, "postroute": 0},
    "postroute": {"prelayout": 20, "postroute": 6},
}
MAX_GATE_RUNS = 40
LIMIT_PCT = 5.0


def sha256_file(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def verify_lock():
    if not os.path.exists(LOCK):
        sys.exit("LOCK.sha256 is missing: the harness is not locked yet")
    bad = []
    lock_lines = open(LOCK).read().splitlines()
    for line in lock_lines:
        if not line.strip() or line.startswith("#"):
            continue
        h, rel = line.split(None, 1)
        p = os.path.join(ROOT, rel)
        if not os.path.exists(p) or sha256_file(p) != h:
            bad.append(rel)
    if bad:
        sys.exit("LOCK VIOLATION: locked files changed or missing: %s. Nothing was run." % bad)
    tools = json.load(open(os.path.join(ROOT, "targets", "targets.json")))["tools"]
    oss = os.environ.get("OSS_CAD_BIN", "/opt/eda/oss-cad-suite/bin")
    ore = os.environ.get("OPENROAD_EXE", "/opt/eda/openroad/bin/openroad")
    now_y = subprocess.run([os.path.join(oss, "yosys"), "-V"], stdout=subprocess.PIPE, text=True).stdout.strip()
    now_o = subprocess.run([ore, "-version"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           text=True).stdout.strip().splitlines()[-1].strip()
    if now_y != tools["yosys"] or now_o != tools["openroad"]:
        sys.exit("LOCK VIOLATION: tool versions differ from the locked ones (%s / %s)" % (now_y, now_o))
    return hashlib.sha256(open(LOCK, "rb").read()).hexdigest()


def ledger_append(entry):
    entry["utc"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
    with open(LEDGER, "a") as f:
        f.write(json.dumps(entry, sort_keys=True) + "\n")


def ledger_entries(arm=None, block=None):
    if not os.path.exists(LEDGER):
        return []
    out = []
    for line in open(LEDGER):
        e = json.loads(line)
        if (arm is None or e.get("arm") == arm) and (block is None or e.get("block") == block):
            out.append(e)
    return out


def targets():
    return json.load(open(os.path.join(ROOT, "targets", "targets.json")))


def block_dir(arm, block):
    return os.path.join(ROOT, "candidates", arm, block)


def cand_rtl(arm, block, cand, must_exist=True):
    p = os.path.join(block_dir(arm, block), cand, "rtl")
    if must_exist and not os.path.isdir(p):
        sys.exit("no candidate '%s' in arm %s, block %s (create it with 'loop.py new')" % (cand, arm, block))
    return p


def cand_sha(rtl):
    import gate as gate_mod
    files = sorted(os.path.join(rtl, f) for f in os.listdir(rtl)
                   if os.path.isfile(os.path.join(rtl, f)) and not f.startswith("."))
    return gate_mod.dir_digest(files)


def golden_files(block):
    gate_cfg = json.load(open(os.path.join(ROOT, "gate", "blocks.json")))
    orfs = os.environ.get("ORFS_ROOT", "/opt/eda/orfs")
    b = gate_cfg["blocks"][block]
    out = []
    for rel in b["golden_files"]:
        p = os.path.join(orfs, rel)
        if sha256_file(p) != b["golden_sha256"][rel]:
            sys.exit("golden source hash mismatch: %s" % rel)
        out.append(p)
    return out


def cmd_new(a, lock):
    bd = block_dir(a.arm, a.block)
    os.makedirs(bd, exist_ok=True)
    existing = sorted(d for d in os.listdir(bd) if d.startswith("c") and d[1:].isdigit())
    n = int(existing[-1][1:]) + 1 if existing else 0
    name = "c%02d" % n
    dst = os.path.join(bd, name, "rtl")
    os.makedirs(dst)
    if a.from_cand:
        src = cand_rtl(a.arm, a.block, a.from_cand)
        for f in os.listdir(src):
            shutil.copy(os.path.join(src, f), dst)
    else:
        for p in golden_files(a.block):
            shutil.copy(p, dst)
    ledger_append({"action": "new", "arm": a.arm, "block": a.block, "cand": name,
                   "from": a.from_cand or "original", "lock": lock})
    print(json.dumps({"candidate": name, "rtl_dir": dst}))


def gate_passed(arm, block, sha):
    for e in ledger_entries(arm, block):
        if e.get("action") == "gate" and e.get("sha") == sha and e.get("verdict") == "PASS":
            return e
    return None


def cmd_gate(a, lock):
    import gate as gate_mod
    n_runs = sum(1 for e in ledger_entries(a.arm, a.block) if e.get("action") == "gate")
    if n_runs >= MAX_GATE_RUNS:
        sys.exit("gate budget used up (%d runs)" % MAX_GATE_RUNS)
    rtl = cand_rtl(a.arm, a.block, a.cand)
    out = os.path.join(RUNS, "gate", a.arm, a.block, a.cand)
    shutil.rmtree(out, ignore_errors=True)
    manifest = json.load(open(os.path.join(ROOT, "gate", "blocks.json")))
    rep = gate_mod.Gate(a.block, rtl, out, manifest).run()
    problems = [p for c in rep["checks"].values() for p in c.get("problems", [])]
    formal = rep["checks"].get("formal", {})
    entry = {"action": "gate", "arm": a.arm, "block": a.block, "cand": a.cand, "sha": rep["candidate_sha256"],
             "verdict": rep["verdict"], "seconds": rep["seconds"], "problems": problems[:5],
             "formal_strength": formal.get("strength"),
             "sim_bits": rep["checks"].get("simulation", {}).get("known_output_bits_compared"),
             "lock": lock}
    ledger_append(entry)
    rdir = os.path.join(block_dir(a.arm, a.block), a.cand)
    json.dump(rep, open(os.path.join(rdir, "gate_report.json"), "w"), indent=1)
    print(json.dumps({"verdict": rep["verdict"], "formal": formal.get("strength"), "problems": problems[:5],
                      "report": os.path.join(rdir, "gate_report.json")}, indent=1))


def judge(m, ref, mode, t1):
    ok_t = m.get("status") == "OK" and m["wns_setup"] >= 0
    if mode == "postroute":
        ok_t = ok_t and m["wns_hold"] >= 0 and m.get("drc_errors") == 0
    da = 100 * (m["area_um2"] / ref["area_ref_um2"] - 1)
    dp = 100 * (m["power_total_w"] / ref["power_ref_w"] - 1)
    return {"timing_met": ok_t, "area_delta_pct": round(da, 3), "power_delta_pct": round(dp, 3),
            "meets_target": bool(ok_t and da <= LIMIT_PCT and dp <= LIMIT_PCT)}


def cmd_eval(a, lock):
    import run_flow
    if BUDGET[a.arm][a.mode] == 0:
        sys.exit("arm '%s' may not use %s evaluation" % (a.arm, a.mode))
    used = sum(1 for e in ledger_entries(a.arm, a.block) if e.get("action") == "eval" and e.get("mode") == a.mode)
    if used >= BUDGET[a.arm][a.mode]:
        sys.exit("%s evaluation budget used up (%d)" % (a.mode, BUDGET[a.arm][a.mode]))
    rtl = cand_rtl(a.arm, a.block, a.cand)
    sha = cand_sha(rtl)
    if not gate_passed(a.arm, a.block, sha):
        sys.exit("candidate %s (sha %s) has no gate PASS in this arm: run 'loop.py gate' first "
                 "(any edit after gating needs a new gate run)" % (a.cand, sha[:12]))
    t = targets()["blocks"][a.block]
    t1 = t["T1_ns"]
    ref = t["references"][a.mode]
    run_dir = os.path.join(RUNS, "loop", a.arm, a.block, "%s_%s" % (a.cand, a.mode))
    m = run_flow.evaluate(a.block, rtl, t1, a.mode, run_dir, refs=ref)
    j = judge(m, ref, a.mode, t1) if m.get("status") == "OK" else {"meets_target": False}
    rdir = os.path.join(block_dir(a.arm, a.block), a.cand, "eval_%s" % a.mode)
    os.makedirs(rdir, exist_ok=True)
    fb = open(os.path.join(run_dir, "feedback.txt")).read()
    verdict = ("MEETS TARGET in this view" if j.get("meets_target") else "DOES NOT MEET TARGET in this view")
    fb = fb + "\nTarget: setup WNS >= 0 at T1 = %.4f ns%s, area and power <= +%.0f %% vs reference.\n%s %s\n" % (
        t1, " (and hold WNS >= 0, 0 DRC errors)" if a.mode == "postroute" else "", LIMIT_PCT, verdict,
        json.dumps(j))
    open(os.path.join(rdir, "feedback.txt"), "w").write(fb)
    slim = {k: m.get(k) for k in ("status", "wns_setup", "tns_setup", "wns_hold", "setup_violating_endpoints",
                                  "area_um2", "power_total_w", "drc_errors", "cells", "seq_cells", "flow_seconds")}
    json.dump({"metrics": slim, "judgement": j, "period_ns": t1, "worst_paths": m.get("worst_paths")},
              open(os.path.join(rdir, "metrics.json"), "w"), indent=1)
    ledger_append({"action": "eval", "arm": a.arm, "block": a.block, "cand": a.cand, "sha": sha, "mode": a.mode,
                   "period_ns": t1, "metrics": slim, "judgement": j, "run_dir": run_dir, "lock": lock})
    print(fb)
    print("budget used: %d of %d %s evaluations" % (used + 1, BUDGET[a.arm][a.mode], a.mode))


def cmd_status(a, lock):
    t = targets()["blocks"][a.block]
    print("block %s | arm %s | T0 %.4f ns | T1 %.4f ns" % (a.block, a.arm, t["T0_ns"], t["T1_ns"]))
    # each arm sees only the references of the views it is allowed to evaluate
    for mode in ("prelayout", "postroute"):
        if BUDGET[a.arm][mode] == 0:
            continue
        r = t["references"][mode]
        print("  %s reference: area %.1f um2, power %.4f mW" % (mode, r["area_ref_um2"], r["power_ref_w"] * 1e3))
    es = ledger_entries(a.arm, a.block)
    for mode in ("prelayout", "postroute"):
        used = sum(1 for e in es if e.get("action") == "eval" and e.get("mode") == mode)
        print("  %s evaluations used: %d of %d" % (mode, used, BUDGET[a.arm][mode]))
    for e in es:
        if e["action"] == "gate":
            print("  %s gate %s %s" % (e["cand"], e["verdict"], (e.get("problems") or [""])[0][:100]))
        elif e["action"] == "eval":
            mm = e["metrics"]
            print("  %s %s: wns %+.4f hold %s area %.1f power %.4f mW -> %s" % (
                e["cand"], e["mode"], mm.get("wns_setup") or 0, mm.get("wns_hold"), mm.get("area_um2") or 0,
                (mm.get("power_total_w") or 0) * 1e3, e["judgement"]))
        elif e["action"] == "final":
            print("  FINAL: %s" % e["cand"])


def cmd_final(a, lock):
    if any(e.get("action") == "final" for e in ledger_entries(a.arm, a.block)):
        sys.exit("a final candidate is already declared for this arm and block")
    rtl = cand_rtl(a.arm, a.block, a.cand)
    sha = cand_sha(rtl)
    if not gate_passed(a.arm, a.block, sha):
        sys.exit("the final candidate must have a gate PASS")
    ledger_append({"action": "final", "arm": a.arm, "block": a.block, "cand": a.cand, "sha": sha,
                   "note": a.note or "", "lock": lock})
    print(json.dumps({"final": a.cand, "sha": sha}))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("new", "gate", "eval", "status", "final"):
        p = sub.add_parser(name)
        p.add_argument("--arm", required=True, choices=["prelayout", "postroute"])
        p.add_argument("--block", required=True)
        if name in ("gate", "eval", "final"):
            p.add_argument("--cand", required=True)
        if name == "new":
            p.add_argument("--from", dest="from_cand", default=None)
        if name == "eval":
            p.add_argument("--mode", required=True, choices=["prelayout", "postroute"])
        if name == "final":
            p.add_argument("--note", default="")
    a = ap.parse_args()
    lock = verify_lock()
    {"new": cmd_new, "gate": cmd_gate, "eval": cmd_eval, "status": cmd_status, "final": cmd_final}[a.cmd](a, lock)


if __name__ == "__main__":
    main()
