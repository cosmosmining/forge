#!/usr/bin/env python3
"""ledger.py -- evidence ledger and gate verdict for the Feature 5 pack.

Every number gets a kind, following Forge's reporting rule:
  measured  a tool printed it; the file is named
  derived   arithmetic on measured numbers; the formula is given
  modelled  computed from a model with its assumptions listed. EVERY 3 GHz / ASAP7
            number is "modelled" (predictive PDK, pre-layout), even when a tool
            printed it.
  not yet   not run; the cell says so and stays empty

Gate verdict: PASS when every step met its expectation, FAIL when any did not,
INCOMPLETE when a step could not run (missing tool or result file).
Expectations: lint clean; every simulation case passes and every simulation mutant
behaves as expected; every formal task matches (proofs PASS, mutants FAIL, covers
reached); every CDC case matches; FPGA open-flow checks (FIFOs in LUTRAM, no SRL in
synchronizers or SLR pipelines); ASIC modelled: every pack primitive (not the
stand-in datapath) has slack >= 0 at 3 GHz, TT corner.

Usage: ledger.py --results results --out results/LEDGER.md --json results/ledger.json
"""
import argparse
import csv
import datetime
import json
import os
import re
import sys


def read(path):
    try:
        return open(path).read()
    except OSError:
        return None


def tsv(path):
    try:
        with open(path) as f:
            return list(csv.DictReader(f, delimiter="\t"))
    except OSError:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default="results")
    ap.add_argument("--out", default="results/LEDGER.md")
    ap.add_argument("--json", default="results/ledger.json")
    ap.add_argument("--missing-tools", default="")
    a = ap.parse_args()
    R = a.results
    entries, steps = [], []

    def add(id_, value, kind, source, note=""):
        entries.append(dict(id=id_, value=value, kind=kind, source=source, note=note))

    def step(name, ok, detail, source):
        steps.append(dict(step=name, result=("PASS" if ok else "FAIL") if ok is not None else "INCOMPLETE",
                          detail=detail, source=source))

    # ---------------- lint
    s = read(f"{R}/lint/summary.txt")
    if s:
        m = re.search(r"LINT (\d+)/(\d+)", s)
        ok = (m.group(1) == m.group(2)) if m else None   # no final line: step did not finish
        step("lint (verilator -Wall + yosys elaboration)", ok, m.group(0) if m else "no summary", f"{R}/lint/summary.txt")
        add("lint.modules_clean", m.group(0) if m else "?", "measured", f"{R}/lint/summary.txt")
    else:
        step("lint (verilator -Wall + yosys elaboration)", None, "not run", "-")

    # ---------------- simulation
    s, mu = read(f"{R}/sim/summary.txt"), read(f"{R}/sim/mutants.txt")
    if s and mu:
        m = re.search(r"SIM (\d+)/(\d+)", s)
        mm = re.search(r"SIM_MUTANTS (\d+)/(\d+)", mu)
        ok = (m.group(1) == m.group(2) and mm.group(1) == mm.group(2)) if (m and mm) else None
        step("simulation (icarus, multi-clock, jittered)", ok,
             f"{m.group(0) if m else '?'}; {mm.group(0) if mm else '?'}", f"{R}/sim/summary.txt, {R}/sim/mutants.txt")
        for line in s.splitlines():
            mt = re.match(r"(PASS|FAIL) (\S+) :: (.*)", line)
            if mt:
                add(f"sim.{mt.group(2)}", mt.group(1), "measured", f"{R}/sim/{mt.group(2)}.log", mt.group(3))
        for line in mu.splitlines():
            mt = re.match(r"(MATCH|MISMATCH)\s+(\S+)\s+(\S+)\s+sim=(\S+) expected=(\S+)", line)
            if mt:
                add(f"sim_mutant.{mt.group(2)}", f"sim {mt.group(4)} (expected {mt.group(5)})", "measured",
                    f"{R}/sim/mutants.txt", mt.group(3))
    else:
        step("simulation (icarus, multi-clock, jittered)", None, "not run", "-")

    # ---------------- formal
    s = read(f"{R}/formal/summary.txt")
    if s:
        m = re.search(r"FORMAL (\d+)/(\d+)", s)
        ok = (m.group(1) == m.group(2)) if m else None
        step("formal (SymbiYosys: proofs, mutants, covers)", ok, m.group(0) if m else "no final line: did not finish", f"{R}/formal/summary.txt")
        for line in s.splitlines():
            mt = re.match(r"(MATCH|MISMATCH)\s+(\S+)\s+status=(\S+)\s+expected=(\S+)\s+(\d+)s", line)
            if mt:
                add(f"formal.{mt.group(2)}", f"{mt.group(3)} (expected {mt.group(4)})", "measured",
                    f"{R}/formal/{mt.group(2).replace(':', '_')}.log", f"{mt.group(5)} s")
    else:
        step("formal (SymbiYosys: proofs, mutants, covers)", None, "not run", "-")

    # ---------------- CDC structural
    s = read(f"{R}/cdc/summary.txt")
    if s:
        m = re.search(r"CDC (\d+)/(\d+)", s)
        ok = (m.group(1) == m.group(2)) if m else None
        step("CDC structural check (tools/cdc_check.py)", ok, m.group(0) if m else "?", f"{R}/cdc/summary.txt")
        for line in s.splitlines():
            mt = re.match(r"(MATCH|MISMATCH)\s+(\S+)\s+expected=(\S+)\s+(\S+)\s+::\s+(.*)", line)
            if mt:
                add(f"cdc.{mt.group(2)}", mt.group(5), "measured", f"{R}/cdc/{mt.group(2)}.txt",
                    f"expected {mt.group(3)} {mt.group(4)}")
    else:
        step("CDC structural check (tools/cdc_check.py)", None, "not run", "-")

    # ---------------- FPGA open flow
    rows = tsv(f"{R}/fpga/summary.tsv")
    if rows:
        by = {r["case"]: r for r in rows}
        checks = []
        for c in ("afifo_w64_d16", "afifo_w64_d64", "sfifo_w64_d16", "slr_w512_f2b2"):
            if c in by:
                checks.append(int(by[c]["LUTRAM_cells"]) > 0)
        for c in ("afifo_w64_d16", "afifo_w64_d64", "handshake_w32", "pulse_sync", "slr_w512_f2b2", "three_domain"):
            if c in by:
                checks.append(int(by[c]["SRL"]) == 0)
        ok = bool(checks) and all(checks)
        step("FPGA open-flow synthesis (yosys synth_xilinx -family xcup)", ok,
             "FIFOs in LUTRAM, no SRL in synchronizers/SLR pipelines" if ok else "LUTRAM/SRL expectation not met",
             f"{R}/fpga/summary.tsv")
        for r in rows:
            add(f"fpga.{r['case']}",
                f"LUT {r['LUT']}, FF {r['FF']}, LUTRAM {r['LUTRAM_cells']}, SRL {r['SRL']}, DSP {r['DSP']}, "
                f"levels {r['max_levels']} (LUT {r['max_lut_levels']}, carry-collapsed {r.get('carry_collapsed', '?')})",
                "measured", f"{R}/fpga/{r['case']}.log",
                f"{r['top']} {r['params']} {r['opts']}; open-flow yosys, not Vivado")
    else:
        step("FPGA open-flow synthesis (yosys synth_xilinx -family xcup)", None, "not run", "-")

    # ---------------- ASIC modelled
    rows = tsv(f"{R}/asic_modelled/summary.tsv")
    if rows:
        prim = [r for r in rows if r["corner"] == "TT" and r["rtl"] == "fixed" and not r["case"].startswith("dot")]
        bad = [r["case"] for r in prim if not (float(r["worst_slack_ps"]) >= 0)]
        ok = bool(prim) and not bad
        step("ASIC 3 GHz MODELLED (ASAP7 TT, pre-layout): pack primitives close", ok,
             "all pack primitives slack >= 0 at 3 GHz TT (modelled)" if ok else f"negative modelled slack: {', '.join(bad)}",
             f"{R}/asic_modelled/summary.tsv")
        for r in rows:
            add(f"asic.{r['case']}.{r['corner']}",
                f"worst slack {r['worst_slack_ps']} ps ({r['worst_kind']}, {r['worst_path_cells']} cells), "
                f"area {r['area_um2']} um2, {r['flops']} flops",
                "modelled", f"{R}/asic_modelled/{r['case']}.{r['corner']}.worst_path.rpt",
                f"ASAP7 RVT {r['corner']}, 3 GHz, ideal clocks, no wires; rtl={r['rtl']}, retime={r['retime']}")
        for corner in ("TT", "SS"):
            s = read(f"{R}/asic_modelled/fo4.{corner}.txt")
            if s:
                m = re.search(r"per-stage delay = ([0-9.]+) ps", s)
                m2 = re.search(r"period_in_FO4_at_3GHz = ([0-9.]+)", s)
                if m:
                    add(f"asic.fo4.{corner}", f"{m.group(1)} ps; {m2.group(1) if m2 else '?'} FO4 per 333.3 ps cycle",
                        "modelled", f"{R}/asic_modelled/fo4.{corner}.txt", "INVx1 FO4 chain, NLDM")
            s = read(f"{R}/asic_modelled/sync_stage.{corner}.txt")
            if s:
                for v, arr, su, sl in re.findall(r"variant=(\w) arrival_ps=([0-9.]+) setup_ps=([0-9.]+) resolution_slack_ps=([0-9.]+)", s):
                    add(f"asic.sync_stage.{corner}.{v}", f"resolution slack {sl} ps (clk->D {arr} ps, setup {su} ps)",
                        "modelled", f"{R}/asic_modelled/sync_stage.{corner}.txt",
                        "a: QN->INVx1->D, b: QN->D")
        mj = read(f"{R}/asic_modelled/mtbf_model.json")
        if mj:
            for row in json.loads(mj)["rows"]:
                add(f"asic.mtbf.{row['corner']}.{row['variant']}.N{row['stages']}",
                    f"tau_max {row['tau_max_ps_for_1e9y']} ps for MTBF >= 1e9 years", "modelled",
                    f"{R}/asic_modelled/mtbf_model.json",
                    "tau, T_w NOT characterized (T_w=20 ps assumed, tau swept); f_data=3e9/s")
    else:
        step("ASIC 3 GHz MODELLED (ASAP7 TT, pre-layout): pack primitives close", None, "not run", "-")

    # ---------------- not yet
    for id_, note in (
        ("fpga.vivado_timing_250MHz", "Vivado not available (needs an AMD account); constraints/fpga_250mhz.tcl not run"),
        ("fpga.vivado_report_cdc", "not run"),
        ("fpga.slr_placement", "device not chosen (STRATEGY.md not in this checkout)"),
        ("fpga.hardware_run", "no board"),
        ("asic.placement_cts_route", "OpenROAD not installed; wires and clock tree not modelled"),
        ("asic.tau_characterization", "needs SPICE on the ASAP7 flop"),
        ("asic.silicon", "no silicon"),
        ("engine.integration", "Forge engine RTL not in this checkout"),
    ):
        add(id_, "", "not yet", "-", note)

    missing = a.missing_tools.split()
    if missing:
        steps.append(dict(step="tools", result="INCOMPLETE", detail="missing: " + " ".join(missing), source="flows/env.sh"))
    results = [s_["result"] for s_ in steps]
    verdict = "INCOMPLETE" if "INCOMPLETE" in results else ("FAIL" if "FAIL" in results else "PASS")

    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# Evidence ledger: Feature 5 timing-closure / clocking pack",
        "",
        f"Generated by `tools/ledger.py` from `{R}/` at {now}. Gate verdict: **{verdict}**.",
        "",
        "Kinds: **measured** (a tool printed it, file named), **derived** (arithmetic on",
        "measured numbers), **modelled** (from a model with listed assumptions; every 3 GHz /",
        "ASAP7 number is modelled: predictive PDK, pre-layout, ideal clocks, no wires),",
        "**not yet** (not run). No number here is from silicon or FPGA hardware.",
        "",
        "## Gate",
        "",
        "| Step | Result | Detail | Source |",
        "|---|---|---|---|",
    ]
    for s_ in steps:
        lines.append(f"| {s_['step']} | {s_['result']} | {s_['detail']} | `{s_['source']}` |")
    lines += ["", "## Entries", "", "| Id | Value | Kind | Source | Note |", "|---|---|---|---|---|"]
    for e in entries:
        val = e["value"].replace("|", "/")
        lines.append(f"| {e['id']} | {val} | {e['kind']} | `{e['source']}` | {e['note'].replace('|', '/')} |")
    open(a.out, "w").write("\n".join(lines) + "\n")
    json.dump(dict(generated=now, verdict=verdict, steps=steps, entries=entries), open(a.json, "w"), indent=1)
    print(f"GATE {verdict}")
    for s_ in steps:
        print(f"  {s_['result']:10s} {s_['step']} :: {s_['detail']}")
    return 0 if verdict == "PASS" else (2 if verdict == "INCOMPLETE" else 1)


if __name__ == "__main__":
    sys.exit(main())
