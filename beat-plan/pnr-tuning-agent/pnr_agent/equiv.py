"""Gate-level logic equivalence: golden input netlist vs. routed netlist (Yosys).

Physical optimization (sizing, buffering, pin swapping, gate cloning, clock
tree insertion) must not change logic.  We prove it with Yosys:

* cell functions come from the liberty file (read_liberty);
* both netlists are flattened;
* only primary I/O and flip-flop/latch state variables keep their names
  (state variables are named <instance>.<state> after flattening, and
  OpenROAD never renames registers), every other name is hidden so that
  legitimate rewiring (e.g. swapped NAND inputs) does not create false
  correspondences;
* equiv_simple + equiv_induct prove every matched point.

The check fails if any point is unproven or if the register sets differ.
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class EquivResult:
    ok: bool
    proven: int
    unproven: int
    gold_states: int
    gate_states: int
    message: str
    log: Path

    def as_dict(self) -> dict:
        return {"ok": self.ok, "proven": self.proven, "unproven": self.unproven,
                "gold_states": self.gold_states, "gate_states": self.gate_states,
                "message": self.message, "log": str(self.log)}


def liberty_state_names(liberty: Path) -> list[str]:
    """Names of ff/latch state variables in a liberty file, e.g. IQ, IQN."""
    names: set[str] = set()
    pat = re.compile(r'\b(?:ff|latch)\s*\(\s*"?([A-Za-z_]\w*)"?\s*,\s*"?([A-Za-z_]\w*)"?\s*\)')
    for m in pat.finditer(liberty.read_text(errors="replace")):
        names.update(m.groups())
    return sorted(names)


def check(gold: Path, gate: Path, top: str, liberties: list[Path], out_dir: Path,
          yosys: str = "yosys", timeout_s: int = 3600,
          physical_cells: tuple[str, ...] = ("TAPCELL*", "FILLCELL*", "FILL_*", "DECAP*")) -> EquivResult:
    out_dir.mkdir(parents=True, exist_ok=True)
    states = sorted({n for lib in liberties for n in liberty_state_names(lib)}) or ["IQ", "IQN"]
    keep = " ".join(f"{{m}}/w:*.{s} %d" for s in states)
    lines = [f"read_liberty -ignore_miss_func {lib}" for lib in liberties]
    lines += [
        f"read_verilog {gold}", f"rename {top} gold",
        f"read_verilog {gate}", f"rename {top} gate",
        # physical-only cells (taps, fillers) carry no logic and may have no liberty pins
        "delete " + " ".join(f"{m}/t:{c}" for m in ("gold", "gate") for c in physical_cells),
        "hierarchy -check",
        "flatten gold gate",
        "opt_clean",
        "tee -o gold_states.txt select -list " + " ".join(f"gold/w:*.{s}" for s in states),
        "tee -o gate_states.txt select -list " + " ".join(f"gate/w:*.{s}" for s in states),
    ]
    for m in ("gold", "gate"):
        lines.append(f"rename -hide {m}/w:* {m}/i:* %d {m}/o:* %d " + keep.format(m=m))
    lines += [
        "equiv_make gold gate equiv",
        "hierarchy -top equiv",
        "equiv_simple -seq 2",
        "equiv_induct -seq 2",
        "tee -o equiv_status.txt equiv_status",
    ]
    script = out_dir / "equiv.ys"
    script.write_text("\n".join(lines) + "\n")
    log = out_dir / "equiv.log"
    with open(log, "w") as fh:  # -q: warnings/errors only (a full -l log can be huge)
        proc = subprocess.run([yosys, "-q", str(script)], cwd=out_dir, stdout=fh,
                              stderr=subprocess.STDOUT, timeout=timeout_s)
    proc.stderr = log.read_text(errors="replace")[-2000:]

    def names(fname):
        p = out_dir / fname
        if not p.exists():
            return set()
        return {l.split("/", 1)[1].strip() for l in p.read_text().splitlines() if "/" in l}

    gold_s, gate_s = names("gold_states.txt"), names("gate_states.txt")
    status = (out_dir / "equiv_status.txt").read_text() if (out_dir / "equiv_status.txt").exists() else ""
    m = re.search(r"Of those cells (\d+) are proven and (\d+) are unproven", status)
    proven, unproven = (int(m.group(1)), int(m.group(2))) if m else (0, -1)
    if "No $equiv cells found" in status:
        proven, unproven = 0, 0
    if proc.returncode != 0:
        msg = f"yosys exit {proc.returncode}: {proc.stderr.strip()[-300:]}"
        ok = False
    elif gold_s != gate_s:
        missing = sorted(gold_s - gate_s)[:5]
        extra = sorted(gate_s - gold_s)[:5]
        msg = f"register sets differ (missing in gate: {missing}, extra in gate: {extra})"
        ok = False
    elif unproven != 0 or proven == 0:
        msg = f"{unproven} unproven equivalence points"
        ok = False
    else:
        msg = f"equivalent: {proven} points proven ({len(gold_s)} state bits matched by name)"
        ok = True
    return EquivResult(ok, proven, unproven, len(gold_s), len(gate_s), msg, log)
