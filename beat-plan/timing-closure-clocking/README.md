# Feature 5: timing-closure and clocking pack

Forge beat plan, feature 5 of 8. Built in a separate cloud worktree of
`cosmosmining/forge` on 2026-11-27/28, to be merged into
`~/Desktop/startup/beat-plan/timing-closure-clocking/`.

Multi-clock domains, clock-domain crossing (CDC), SLR floorplanning and pipelining,
retiming and LUTRAM: reusable RTL primitives, their constraints, and the checks that
prove them, for two targets:

* **250 MHz FPGA target** (AMD UltraScale+): open-flow evidence only. Vivado was not
  available, so FPGA timing is **not yet**.
* **3 GHz ASIC track**: **MODELLED ONLY**, on the ASAP7 *predictive* 7 nm PDK,
  pre-layout. Never silicon, never measured hardware.

Gate verdict and every number, with its kind and source file: **`results/LEDGER.md`**.

## What was missing, and what that limits

The brief asked to read STRATEGY.md, BEAT_PLAN.md, HANDOFF.md,
beat-plan/strategy/{PPA_LOOP_PLAN, PROBLEMS_AND_IMPROVEMENTS, CLOCK_3GHZ_PLAN}.md and
the skills chip-physical-design, chip-routing and forge-timing-closure
(chip-design-skills/ and forge/). **None of them is in this repository** (it holds only
the public landing page, `index.html`), on any branch, and the session's code search
found none in the account's repositories it can reach. So:

* the pack was built from the brief and the landing page (forge-silicon.com, status
  20 November 2026), not from the strategy documents;
* the FPGA device, and so its SLR count and Laguna budget, is not chosen: the SLR
  constraints are written as a commented template;
* the Forge engine RTL is not here, so nothing was integrated into it, and **no number
  here is an engine number**. `rtl/dot_reduce.sv` is a stand-in datapath for the
  pipelining and retiming experiments, not the Forge MAC row;
* CLOCK_3GHZ_PLAN.md (owned by the 3 GHz session) was neither read nor touched; the
  3 GHz work here is limited to clocking, CDC and timing closure and needs reconciling
  with it.

## Contents

| Path | What |
|---|---|
| `rtl/cdc_sync_bit.sv` | N-flop synchronizer (ASYNC_REG), formal metastability model |
| `rtl/cdc_reset_sync.sv` | reset bridge: async assert, sync release |
| `rtl/cdc_pulse_sync.sv` | event crossing (toggle + acknowledge, `src_busy`) |
| `rtl/cdc_handshake.sv` | multi-bit word crossing (2-phase req/ack) |
| `rtl/cdc_async_fifo.sv` | dual-clock FIFO: Gray pointers, LUTRAM, FWFT, conservative `rlevel`/`wfree` |
| `rtl/skid_buffer.sv` | fully registered valid/ready stage |
| `rtl/sync_fifo_lutram.sv` | single-clock LUTRAM FIFO, registered flags |
| `rtl/slr_crossing.sv` | SLR / long-route crossing, all crossing wires flop-to-flop, credit return |
| `rtl/pipe_reg.sv` | fixed-latency pipeline, no SRL packing |
| `rtl/dot_reduce.sv` | stand-in datapath (not Forge RTL) for pipelining / retiming experiments |
| `examples/three_domain_top.sv` | host / core / memory wiring of all of the above |
| `constraints/fpga_250mhz.tcl` | Vivado unmanaged Tcl constraints template: clocks, CDC max delay + bus skew, ASYNC_REG, SLR pblocks and Laguna registers (not yet run) |
| `constraints/asic_3ghz_modelled.sdc` | 3 GHz SDC for the modelled track |
| `tools/cdc_check.py` | structural CDC checker on yosys netlists |
| `tools/logic_depth.py` | register-to-register logic levels of an UltraScale+ netlist |
| `tools/asap7_prepare_libs.py` | stage, hash-check and merge the ASAP7 libraries |
| `tools/mtbf_model.py` | synchronizer MTBF sweep (modelled) |
| `tools/ledger.py` | evidence ledger and gate verdict |
| `flows/run_all.sh` | the gate: lint, sim, formal, CDC, FPGA open flow, ASIC modelled, ledger |
| `docs/CLOCKING_SPEC.md` | domains, crossing rules, which primitive for which crossing |
| `docs/FPGA_250MHZ.md` | FPGA track: LUTRAM, SLR plan, pipelining, retiming |
| `docs/ASIC_3GHZ_MODELLED.md` | 3 GHz track, all modelled |
| `docs/VERIFICATION.md` | what is proved, mutants, findings |
| `TOOLS.md` | tool versions, why not the OSS CAD Suite tarball, tool problems found |
| `results/` | every result file of the last gate run, and `results/history/` |

## Run it

```bash
cd beat-plan/timing-closure-clocking
```

```bash
flows/run_all.sh
```

Needs yosys, yosys-abc, yosys-smtbmc, sby, yices-smt2, iverilog, verilator and sta on
PATH (TOOLS.md has the versions used), plus the ASAP7 liberty files from
OpenROAD-flow-scripts (set `ASAP7_LIB_DIR`; their SHA-256 is checked). About 40
minutes on 4 cores. Single steps: `flows/run_lint.sh`, `run_sim.sh`, `run_formal.sh`,
`run_cdc.sh`, `run_fpga.sh`, `run_asic_modelled.sh`.

## Headline results

See `results/LEDGER.md` for the full list and sources. In short:

* **CDC primitives are proved, not only simulated**: unbounded SymbiYosys proofs for
  every crossing primitive under any interleaving of two unrelated clocks, with a
  metastability model; six mutants, each caught; covers reached.
* **One finding about Gray coding**: with registered, equality-compared flags, binary
  FIFO pointers keep full/empty safe; they break the first time the synchronized pointer
  is used as a number (the FIFO's burst levels). Simulation cannot see this at all.
* **The structural CDC checker** passes the pack and the three-domain example, and
  catches each of its six rule-breaking test designs.
* **FPGA open flow** (yosys `synth_xilinx -family xcup`, measured, not Vivado): FIFOs
  map to LUTRAM, synchronizers and SLR pipeline flops stay flops; structural pipelining
  halves the stand-in's logic depth; the open flow's sequential mapping does not retime
  it; yosys ignores `shreg_extract`.
* **3 GHz, modelled (ASAP7 TT, no wires)**: every pack primitive closes at TT. One
  timing-closure loop on the FIFOs (found with the first mapping flow, where they
  missed by about 48 ps) added about 40-50 ps of margin at both corners; at SS the
  FIFO and SLR blocks still do not close. 3-flop synchronizers are the default (MTBF
  sweep; tau not characterized). Retiming closes the stand-in datapath where
  hand-placed per-level registers do not.

## Not yet

Vivado timing and `report_cdc` at 250 MHz; device choice and SLR placement; FPGA
hardware; ASAP7 placement / clock tree / routing; tau characterization; silicon;
integration with the Forge engine RTL.
