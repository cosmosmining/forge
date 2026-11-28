#!/usr/bin/env python3
"""mtbf_model.py -- synchronizer MTBF at 3 GHz. MODELLED ONLY (ASAP7 predictive PDK).

Forge Feature 5 (timing-closure / clocking pack).

    MTBF = exp(t_r / tau) / (T_w * f_clk * f_data)

t_r   resolution time. For an N-flop synchronizer, t_r = (N - 1) * s, where s is the
      per-stage resolution slack from OpenSTA on the ASAP7 libraries
      (flows/asic/sync_stage.tcl: period - clk->Q [- INVx1] - setup). Modelled.
tau   metastability time constant of the ASAP7 flop, and
T_w   its metastability window: NEITHER IS CHARACTERIZED. They need transistor-level
      simulation of DFFASRHQNx1 with the ASAP7 SPICE models, which this pack has not
      done. So tau is swept, T_w is fixed at an assumed value with a sensitivity note,
      and the decision quantity is tau_max: the largest tau for which N stages still
      meet the MTBF target. Compare tau_max with a characterized tau when one exists.
f_clk destination clock, 3 GHz.
f_data rate of changes on the synchronized signal. Worst case for a Gray pointer:
      one bit changes per source write, writes every cycle at 3 GHz -> 3e9 /s.

Usage: mtbf_model.py --stage <sync_stage summary file> [--json out.json]
"""
import argparse
import json
import math
import re

YEAR = 365.25 * 24 * 3600.0
F_CLK = 3.0e9
F_DATA = 3.0e9
TW_ASSUMED = 20e-12          # assumption, not characterized (see docstring)
TAUS_PS = [3, 5, 8, 10, 15, 20, 30]
TARGET_YEARS = 1e9            # per synchronizer; a chip has many, see the doc
STAGES = [2, 3, 4]


def mtbf_years(tr_ps, tau_ps, tw=TW_ASSUMED, fclk=F_CLK, fdata=F_DATA):
    x = tr_ps / tau_ps
    if x > 700:                      # exp overflow: effectively infinite
        return float("inf")
    return math.exp(x) / (tw * fclk * fdata) / YEAR


def tau_max_ps(tr_ps, target_years=TARGET_YEARS, tw=TW_ASSUMED, fclk=F_CLK, fdata=F_DATA):
    return tr_ps / math.log(target_years * YEAR * tw * fclk * fdata)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", nargs="+", required=True, help="files with SYNCSTAGE lines (one per corner)")
    ap.add_argument("--json")
    a = ap.parse_args()
    rows = []
    for path in a.stage:
        corner = re.search(r"\.(TT|SS|FF)\.", path)
        corner = corner.group(1) if corner else "?"
        for line in open(path):
            m = re.search(r"variant=(\w) arrival_ps=([0-9.]+) setup_ps=([0-9.]+) resolution_slack_ps=([0-9.]+)", line)
            if not m:
                continue
            v, s = m.group(1), float(m.group(4))
            for n in STAGES:
                tr = (n - 1) * s
                rows.append(dict(label="MODELLED", corner=corner, variant=v, stages=n, stage_slack_ps=s,
                                 t_r_ps=round(tr, 2), tau_max_ps_for_1e9y=round(tau_max_ps(tr), 2),
                                 mtbf_years={str(t): mtbf_years(tr, t) for t in TAUS_PS}))
    print("MODELLED synchronizer MTBF at 3 GHz (ASAP7, f_data=3e9/s, T_w=20 ps ASSUMED, tau SWEPT)")
    print(f"{'corner':6} {'var':3} {'N':>2} {'t_r ps':>8} {'tau_max(1e9 y) ps':>18}  MTBF years at tau = " + " ".join(f"{t}ps" for t in TAUS_PS))
    for r in rows:
        mt = " ".join(f"{r['mtbf_years'][str(t)]:.1e}" for t in TAUS_PS)
        print(f"{r['corner']:6} {r['variant']:3} {r['stages']:>2} {r['t_r_ps']:>8.1f} {r['tau_max_ps_for_1e9y']:>18.2f}  {mt}")
    # Sensitivity to the assumed window: tau_max scales with 1/ln(...), so a 10x larger
    # T_w only lowers tau_max by ln(10)/ln(...) (a few percent).
    if rows:
        base = rows[0]["t_r_ps"]
        print("T_w sensitivity (first row): tau_max at T_w = 2, 20, 200 ps -> " +
              ", ".join(f"{tau_max_ps(base, tw=tw):.2f}" for tw in (2e-12, 20e-12, 200e-12)))
    if a.json:
        json.dump(dict(assumptions=dict(f_clk=F_CLK, f_data=F_DATA, T_w_s=TW_ASSUMED, target_years=TARGET_YEARS,
                                        tau_swept_ps=TAUS_PS, tau_characterized=False, T_w_characterized=False),
                       rows=rows), open(a.json, "w"), indent=1, default=str)


if __name__ == "__main__":
    main()
