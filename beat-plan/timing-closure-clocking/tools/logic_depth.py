#!/usr/bin/env python3
"""logic_depth.py -- register-to-register logic depth of a yosys synth_xilinx netlist.

Forge Feature 5 (timing-closure / clocking pack).

Reads the JSON written after `synth_xilinx -family xcup` and reports, over all paths
from a start point (flop output, LUTRAM read output, primary input) to an end point
(flop input, LUTRAM write input, primary output):
  levels      every combinational cell counts one level (LUT*, CARRY*, MUXF*, LUTRAM
              read), which is how Vivado counts "logic levels";
  lut_levels  only LUT* and LUTRAM-read cells counted;
  carry_collapsed_levels  like levels, but a CARRY cell fed by another CARRY cell
              (a cascaded chain) adds nothing, so a whole carry chain counts once.
              yosys maps UltraScale+ adders to CARRY4 here, where Vivado would use
              CARRY8, so `levels` over-counts adders and this metric under-counts:
              the two bracket what Vivado would report.
Also counts cells by class. This is a structural measure. It is not timing: no
placement, no routing, no Vivado delay model.

Usage: logic_depth.py netlist.json --top <module> [--json out.json] [--paths N]
"""
import argparse
import json
import re
import sys
from collections import Counter, defaultdict

SEQ = re.compile(r"^(FD[CPRS]E(_1)?|FD[CPRS]|LD[CP]E?|SRL16E|SRLC32E|SRLC16E|RAMB\w+|FIFO\w+|DSP48E\d*|URAM\w+)$")
LUTRAM = re.compile(r"^RAM(32M16|64M8|32M|64M|32X1D|64X1D|128X1D|256X1D|512X1S|32X1S|64X1S|128X1S|256X1S)$")
LUT = re.compile(r"^LUT[1-6](_2)?$")
COMB = re.compile(r"^(LUT[1-6](_2)?|CARRY\d|MUXF\d|MUXCY|XORCY|INV|BUF|\$_\w+_)$")
CONST = {"GND", "VCC"}
# LUTRAM inputs that feed the read data combinationally (read addresses); the rest
# (data in, write enable, write address of single-port shapes is shared) are sinks.
LUTRAM_READ_PORT = re.compile(r"^(ADDR[A-G]|DPRA\d*|A\d*|RADR\w*)$")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("netlist")
    ap.add_argument("--top", required=True)
    ap.add_argument("--json")
    ap.add_argument("--paths", type=int, default=1)
    a = ap.parse_args()
    sys.setrecursionlimit(200000)

    mod = json.load(open(a.netlist))["modules"][a.top]
    cells = mod["cells"]
    driver = {}
    for cname, c in cells.items():
        for p, bits in c["connections"].items():
            if c.get("port_directions", {}).get(p) == "output":
                for b in bits:
                    if isinstance(b, int):
                        driver[b] = cname
    counts = Counter()
    unknown = Counter()
    for c in cells.values():
        t = c["type"]
        if SEQ.match(t):
            counts["seq:" + t] += 1
        elif LUTRAM.match(t):
            counts["lutram:" + t] += 1
        elif COMB.match(t):
            counts["comb:" + t] += 1
        elif t in CONST:
            counts["const"] += 1
        else:
            unknown[t] += 1

    memo = {}

    def depth_of_cell(cname):
        """(levels, lut_levels, path) ending at the output of comb/LUTRAM cell cname."""
        if cname in memo:
            return memo[cname]
        memo[cname] = (0, 0, [])  # cycle guard (combinational loops are not expected)
        c = cells[cname]
        t = c["type"]
        best = (0, 0, [])
        for p, bits in c["connections"].items():
            if c.get("port_directions", {}).get(p) != "input":
                continue
            if LUTRAM.match(t) and not LUTRAM_READ_PORT.match(p):
                continue
            for b in bits:
                d = depth_of_bit(b)
                if (d[0], d[1]) > (best[0], best[1]):
                    best = d
        lut = 1 if (LUT.match(t) or LUTRAM.match(t)) else 0
        res = (best[0] + 1, best[1] + lut, best[2] + [f"{t}:{cname}"])
        memo[cname] = res
        return res

    def depth_of_bit(b):
        if not isinstance(b, int) or b not in driver:
            return (0, 0, [])           # constant or primary input
        cname = driver[b]
        t = cells[cname]["type"]
        if SEQ.match(t) or t in CONST:
            return (0, 0, [])           # start point
        if COMB.match(t) or LUTRAM.match(t):
            return depth_of_cell(cname)
        return (0, 0, [])               # unknown cell: treated as a start point

    # end points: inputs of sequential cells, write-side inputs of LUTRAMs, outputs
    ends = []
    for cname, c in cells.items():
        t = c["type"]
        if SEQ.match(t) or LUTRAM.match(t):
            for p, bits in c["connections"].items():
                if c.get("port_directions", {}).get(p) != "input":
                    continue
                if p in ("C", "CLK", "WCLK", "CLKARDCLK", "CLKBWRCLK"):
                    continue
                if LUTRAM.match(t) and LUTRAM_READ_PORT.match(p):
                    continue
                for b in bits:
                    ends.append((f"{t}:{cname}.{p}", depth_of_bit(b)))
    for pname, p in mod["ports"].items():
        if p["direction"] == "output":
            for i, b in enumerate(p["bits"]):
                ends.append((f"PO:{pname}[{i}]", depth_of_bit(b)))

    # carry-collapsed depth (separate pass, own memo)
    cmemo = {}
    CARRY = re.compile(r"^CARRY\d$")

    def cdepth_bit(b):
        if not isinstance(b, int) or b not in driver:
            return 0
        cname = driver[b]
        t = cells[cname]["type"]
        if not (COMB.match(t) or LUTRAM.match(t)):
            return 0
        if cname in cmemo:
            return cmemo[cname]
        cmemo[cname] = 0
        c = cells[cname]
        best, fed_by_carry = 0, False
        for p, bits in c["connections"].items():
            if c.get("port_directions", {}).get(p) != "input":
                continue
            if LUTRAM.match(t) and not LUTRAM_READ_PORT.match(p):
                continue
            for bb in bits:
                best = max(best, cdepth_bit(bb))
                if CARRY.match(t) and isinstance(bb, int) and bb in driver and CARRY.match(cells[driver[bb]]["type"]):
                    fed_by_carry = True
        cmemo[cname] = best + (0 if fed_by_carry else 1)
        return cmemo[cname]

    max_collapsed = 0
    for cname, c in cells.items():
        t = c["type"]
        if SEQ.match(t) or LUTRAM.match(t):
            for p, bits in c["connections"].items():
                if c.get("port_directions", {}).get(p) != "input" or p in ("C", "CLK", "WCLK"):
                    continue
                if LUTRAM.match(t) and LUTRAM_READ_PORT.match(p):
                    continue
                for b in bits:
                    max_collapsed = max(max_collapsed, cdepth_bit(b))
    for pname, p in mod["ports"].items():
        if p["direction"] == "output":
            for b in p["bits"]:
                max_collapsed = max(max_collapsed, cdepth_bit(b))

    ends.sort(key=lambda e: (e[1][0], e[1][1]), reverse=True)
    max_levels = ends[0][1][0] if ends else 0
    max_lut = max((e[1][1] for e in ends), default=0)
    hist = Counter(e[1][0] for e in ends)

    report = dict(top=a.top, max_levels=max_levels, max_lut_levels=max_lut,
                  max_carry_collapsed_levels=max_collapsed,
                  level_histogram=dict(sorted(hist.items())),
                  cell_counts=dict(sorted(counts.items())), unknown_cells=dict(unknown),
                  worst_paths=[dict(end=e[0], levels=e[1][0], lut_levels=e[1][1], path=e[1][2])
                               for e in ends[:a.paths]])
    print(f"logic_depth top={a.top} max_levels={max_levels} max_lut_levels={max_lut} "
          f"max_carry_collapsed_levels={max_collapsed} endpoints={len(ends)}")
    for k, v in sorted(counts.items()):
        print(f"  {k:24s} {v}")
    for k, v in unknown.items():
        print(f"  unknown:{k:16s} {v}")
    for w in report["worst_paths"]:
        print(f"  worst: {w['levels']} levels ({w['lut_levels']} LUT) -> {w['end']}")
        print("    " + " > ".join(w["path"]))
    if a.json:
        json.dump(report, open(a.json, "w"), indent=1)


if __name__ == "__main__":
    main()
