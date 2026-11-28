# HANDOFF

> This cloud worktree of `cosmosmining/forge` had no HANDOFF.md (the repository holds
> only the public landing page). This file carries **only the Feature 5 entry**. When
> merging into `~/Desktop/startup/HANDOFF.md`, append the section below; do not
> replace that file with this one.

## Feature 5: timing-closure / clocking pack (2026-11-28, cloud session)

**Where:** `beat-plan/timing-closure-clocking/` (start with `README.md`; every number,
with its kind and source file, is in `results/LEDGER.md`).
**Branch:** `claude/affectionate-wright-pvlo2d`.
**Gate:** final gate run in progress at the time of this commit; its verdict and every result file land in the next commit (`results/LEDGER.md`).

### Done

* Pack RTL, written for the pack (not Forge engine RTL): 2/3-flop synchronizer, reset
  bridge, pulse synchronizer, 2-phase handshake, Gray-pointer async FIFO (LUTRAM,
  conservative burst levels), skid buffer, LUTRAM sync FIFO, SLR crossing (every
  crossing wire flop-to-flop, credit return), pipeline register, stand-in datapath for
  pipelining/retiming; a three-clock integration example.
* Verification: Verilator lint; 24 multi-clock simulations (clock ratios 13:1 both
  ways, jitter); SymbiYosys unbounded proofs of every crossing primitive under any
  clock interleaving with a metastability model; 6 mutants caught (formal) and 5 of 6
  in simulation (the binary-pointer mutant cannot be caught by RTL simulation, by
  design of the test); covers reached; a structural CDC checker on yosys netlists with
  its own negative tests.
* FPGA 250 MHz track (open yosys flow, measured, **not Vivado**): FIFOs in LUTRAM,
  synchronizers and SLR pipelines stay flops, logic-level bracket per block; Vivado
  constraints template (clocks, per-pair datapath-only max delay + Gray bus skew,
  ASYNC_REG, SLR pblocks / Laguna `USER_SLL_REG` pattern) **not yet run**.
* 3 GHz ASIC track, **MODELLED ONLY** (ASAP7 predictive PDK, pre-layout, ideal clocks,
  no wires): all pack primitives close at TT; FIFO/SLR do not at SS; one closure loop
  on the FIFOs (+40-50 ps); FO4 19.5 ps TT / 29.2 ps SS; 3-flop synchronizers by
  default from an MTBF sweep (tau not characterized); ABC retiming closes the stand-in
  datapath where per-level registers do not.

### Findings worth carrying into other features

* Binary FIFO pointers keep registered full/empty safe but break any use of the
  synchronized pointer as a number (levels); only formal with a metastability model
  sees it.
* In Vivado, `set_clock_groups -asynchronous` overrides `set_max_delay`: do not use it
  between clocks that carry Gray buses.
* yosys ignores `shreg_extract`; yosys/ABC9 `-dff` did not retime the stand-in on
  UltraScale+, while ABC retiming did on ASAP7. Place FPGA pipeline registers by hand.
* ORFS defaults ASAP7 to the FF corner: state the corner with every ASAP7 number.

### Inputs that were missing here

STRATEGY.md, BEAT_PLAN.md, HANDOFF.md, beat-plan/strategy/* (PPA_LOOP_PLAN,
PROBLEMS_AND_IMPROVEMENTS, CLOCK_3GHZ_PLAN), chip-design-skills/ and forge/ skill packs,
and the Forge engine RTL are not in this repository. The pack was built from the brief
and index.html; the device choice, the engine integration and the reconciliation with
CLOCK_3GHZ_PLAN.md are open.

### Next

1. Merge the pack into `~/Desktop/startup/beat-plan/timing-closure-clocking/`; run
   `flows/run_all.sh` there (tools by name, `ASAP7_LIB_DIR` for the libraries).
2. Bind `docs/CLOCKING_SPEC.md` to the engine top and run `flows/run_cdc.sh` on it.
3. Pick the FPGA device; fill the SLR section of `constraints/fpga_250mhz.tcl`; run
   Vivado (`report_cdc`, `report_bus_skew`, `report_timing_summary` at 4.000 ns).
4. 3 GHz (with the 3 GHz session): place-and-route on ASAP7, characterize tau, fix the
   FIFO/SLR SS-corner paths (pointer fan-out split, pre-decoded write enables).

### Rules kept

No applications, accounts, spending or contact; no Q8 run; no edits outside
`beat-plan/timing-closure-clocking/` except this file; Q7, Build 6 last-mile, b11 and
the 3 GHz session's files not touched; no messages to other sessions. The OSS CAD
Suite tarball could not be downloaded (session network policy serves GitHub git clones
only); the same free tools came from conda-forge, Ubuntu apt and source builds
(`TOOLS.md`).
