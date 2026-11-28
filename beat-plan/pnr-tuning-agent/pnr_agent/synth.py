"""Delay-targeted re-synthesis of the golden netlist's combinational logic (Yosys + ABC).

This is the netlist-level stand-in for "edit the RTL / synthesis": every
register instance keeps its name and type (sequential cells are held as
hierarchy and never flattened), only the combinational logic between them is
re-mapped by ABC to a delay target.  Because registers are untouched, the
result is checked against the golden netlist with the same equivalence proof
as every other edit.  With real RTL (Build 6), the same knob maps to
re-running synthesis with a tighter ABC delay target.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from .config import Design

YOSYS_TIMEOUT_S = 3600


def sequential_cells(liberty_text: str) -> list[str]:
    """Cells holding state (ff/latch/statetable) plus tie cells: never re-mapped."""
    cells = []
    for m in re.finditer(r"^\s*cell\s*\(\s*\"?([A-Za-z0-9_]+)\"?\s*\)\s*\{", liberty_text, re.M):
        name = m.group(1)
        body = liberty_text[m.end(): m.end() + 6000]
        nxt = re.search(r"^\s*cell\s*\(", body, re.M)
        if nxt:
            body = body[:nxt.start()]
        if re.search(r"\b(ff|latch|ff_bank|latch_bank|statetable)\s*\(", body):
            cells.append(name)
    return sorted(set(cells))


def resynth_script(design: Design, abc_liberty: Path, delay_ps: int, out_v: Path,
                   seq_cells: list[str]) -> str:
    p = design.platform
    top = design.top
    lo_cell, lo_pin = p.tielo_port.split("/")
    hi_cell, hi_pin = p.tiehi_port.split("/")
    keep = " ".join(seq_cells + [lo_cell, hi_cell])
    lines = [f"read_liberty -ignore_miss_func {p.liberty}"]
    lines += [f"read_liberty -lib {x}" for x in design.extra_lib]
    lines += [
        f"read_verilog {design.netlist}",
        f"hierarchy -top {top}",
        f"setattr -mod -set keep_hierarchy 1 {keep}",
        f"flatten {top}",
        f"opt_clean {top}",
        f"tee -q -o stat_before.txt stat -liberty {p.liberty} {top}",
        f"abc -D {int(delay_ps)} -liberty {abc_liberty} {top}",
        f"opt_clean {top}",
        f"hilomap -hicell {hi_cell} {hi_pin} -locell {lo_cell} {lo_pin} {top}",
        f"opt_clean {top}",
        f"tee -q -o stat_after.txt stat -liberty {p.liberty} {top}",
        f"select {top}",
        f"write_verilog -noattr -noexpr -nohex -nodec -selected {out_v}",
    ]
    return "\n".join(lines) + "\n"


def run_resynth(design: Design, abc_liberty: Path, delay_ps: int, sdir: Path,
                yosys: str = "yosys") -> Path:
    out_v = sdir / "resynth.v"
    seq = sequential_cells(design.platform.liberty.read_text(errors="replace"))
    script = sdir / "resynth.ys"
    script.write_text(resynth_script(design, abc_liberty, delay_ps, out_v, seq))
    log = sdir / "resynth.log"
    with open(log, "w") as fh:  # -q: warnings/errors only (a full -l log can be huge)
        proc = subprocess.run([yosys, "-q", str(script)], stdout=fh, stderr=subprocess.STDOUT,
                              cwd=sdir, timeout=YOSYS_TIMEOUT_S)
    if proc.returncode != 0 or not out_v.exists() or out_v.stat().st_size == 0:
        tail = log.read_text(errors="replace")[-400:]
        raise RuntimeError(f"re-synthesis failed (yosys exit {proc.returncode}): {tail}")
    return out_v


def area_from_stat(path: Path) -> float | None:
    if not path.exists():
        return None
    m = re.findall(r"Chip area for (?:module|top module) '\\?[^']*':\s*([\d.]+)", path.read_text())
    return float(m[-1]) if m else None
