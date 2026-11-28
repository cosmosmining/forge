#!/usr/bin/env python3
"""Builds results/tables.md and results/comparison.json from measured files only:
targets/targets.json, results/final_eval.json and ledger/ledger.jsonl.
Every number in the output is either printed by a tool (measured) or computed
from such numbers with the formula stated next to it (derived)."""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BLOCKS = ["gcd", "aes_cipher_top", "riscv", "dct_mac", "dctub", "jpeg_qnr"]


def ledger():
    p = os.path.join(ROOT, "ledger", "ledger.jsonl")
    return [json.loads(l) for l in open(p)] if os.path.exists(p) else []


def fmt(x, nd=4, sign=False):
    if x is None:
        return "–"
    return ("%+." + str(nd) + "f") % x if sign else ("%." + str(nd) + "f") % x


def main():
    tg = json.load(open(os.path.join(ROOT, "targets", "targets.json")))
    fe = json.load(open(os.path.join(HERE, "final_eval.json")))["results"]
    led = ledger()
    L = []
    comp = {"blocks": {}, "summary": {}}

    L.append("## Table 1 — Targets and the original RTL (measured)\n")
    L.append("Source: `targets/targets.json` (written by `targets/measure.py` from ORFS 26Q3 runs).\n")
    L.append("| block | pre-layout min period (ns) | T0 (ns) | T1 = 0.9·T0 (ns) | original @T1: post-route setup WNS (ns) | "
             "original @T0: area (µm²) | power ref @T1 freq (mW) | original @T1: area (µm²) | original @T1: power (mW) |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    for b in BLOCKS:
        t = tg["blocks"][b]
        r = t["references"]["postroute"]
        o1 = r["orig_at_T1"]
        L.append("| %s | %s | %s | %s | %s | %.1f | %.4f | %.1f | %.4f |" % (
            b, fmt(t["prelayout_min_period_ns"]), fmt(t["T0_ns"]), fmt(t["T1_ns"]), fmt(o1["wns_setup"], sign=True),
            r["area_ref_um2"], r["power_ref_w"] * 1e3, o1["area_um2"], o1["power_total_w"] * 1e3))
    L.append("")

    L.append("## Table 2 — Final candidates, judged post-route at T1 (measured; Δ derived)\n")
    L.append("Source: `results/final_eval.json` (fresh gate + fresh ORFS run of each declared final). "
             "Δ area = area / area ref − 1; Δ power = power / power ref − 1 (refs in Table 1). "
             "Pass = setup WNS ≥ 0, hold WNS ≥ 0, 0 DRC, Δ area ≤ +5 %, Δ power ≤ +5 %, gate PASS.\n")
    L.append("| block | arm | final | setup WNS (ns) | hold WNS (ns) | DRC | Δ area | Δ power | gate (formal) | evals pre/post | pass |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|")
    passes = {"prelayout": 0, "postroute": 0}
    for b in BLOCKS:
        comp["blocks"][b] = {}
        for arm in ("prelayout", "postroute"):
            r = fe.get("%s/%s" % (arm, b))
            if not r:
                L.append("| %s | %s | (not evaluated) | | | | | | | | |" % (b, arm))
                continue
            m, j = r["metrics"], r["judgement"]
            ok = r["success"]
            passes[arm] += 1 if ok else 0
            comp["blocks"][b][arm] = {"final": r["final_candidate"], "wns_setup": m["wns_setup"],
                                      "wns_hold": m["wns_hold"], "drc": m["drc_errors"],
                                      "area_delta_pct": j.get("area_delta_pct"),
                                      "power_delta_pct": j.get("power_delta_pct"), "pass": ok}
            L.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s (%s) | %d / %d | %s |" % (
                b, arm, r["final_candidate"], fmt(m["wns_setup"], sign=True), fmt(m["wns_hold"], sign=True),
                m["drc_errors"], "%+.2f %%" % j["area_delta_pct"] if "area_delta_pct" in j else "–",
                "%+.2f %%" % j["power_delta_pct"] if "power_delta_pct" in j else "–", r["gate_verdict"],
                r.get("gate_formal") or "–", r["evaluations_used"]["prelayout"], r["evaluations_used"]["postroute"],
                "**yes**" if ok else "no"))
    L.append("")
    comp["summary"] = {"blocks_passing": passes, "of": len(BLOCKS)}
    L.append("**Blocks passing:** pre-layout-only loop %d of %d; post-route loop %d of %d.\n"
             % (passes["prelayout"], len(BLOCKS), passes["postroute"], len(BLOCKS)))

    # pre-layout vs post-route on the same candidate
    L.append("## Table 3 — Same candidate, two views (measured)\n")
    L.append("Every candidate evaluated both pre-layout and post-route at T1 (post-route arm, plus the "
             "pre-layout arm's finals from Table 2). Source: `ledger/ledger.jsonl`, `results/final_eval.json`.\n")
    L.append("| block | arm/cand | pre-layout setup WNS (ns) | post-route setup WNS (ns) | difference (ns) |")
    L.append("|---|---|---|---|---|")
    rows = []
    by = {}
    for e in led:
        if e.get("action") == "eval":
            by.setdefault((e["arm"], e["block"], e["sha"]), {})[e["mode"]] = e["metrics"].get("wns_setup")
    for b in BLOCKS:
        for arm in ("prelayout", "postroute"):
            r = fe.get("%s/%s" % (arm, b))
            if r and r.get("sha"):
                by.setdefault((arm, b, r["sha"]), {}).setdefault("postroute_final", r["metrics"]["wns_setup"])
    names = {}
    for e in led:
        if e.get("action") == "gate":
            names[(e["arm"], e["block"], e["sha"])] = e["cand"]
    for (arm, b, sha), v in sorted(by.items(), key=lambda kv: (BLOCKS.index(kv[0][1]), kv[0][0])):
        pre = v.get("prelayout")
        post = v.get("postroute", v.get("postroute_final"))
        if pre is None or post is None:
            continue
        rows.append(post - pre)
        L.append("| %s | %s/%s | %s | %s | %s |" % (b, arm, names.get((arm, b, sha), sha[:8]), fmt(pre, sign=True),
                                                  fmt(post, sign=True), fmt(post - pre, sign=True)))
    if rows:
        L.append("\npost-route minus pre-layout setup WNS over %d candidates: min %+.4f ns, max %+.4f ns "
                 "(derived from the rows above)." % (len(rows), min(rows), max(rows)))
    open(os.path.join(HERE, "tables.md"), "w").write("\n".join(L) + "\n")
    json.dump(comp, open(os.path.join(HERE, "comparison.json"), "w"), indent=1)
    print("\n".join(L))


if __name__ == "__main__":
    main()
