# Clocking and CDC specification

Forge Feature 5 (timing-closure / clocking pack). This is the rulebook the pack's RTL,
constraints and checkers implement. Numbers live in `results/LEDGER.md`, each with its
kind (measured, derived, modelled, not yet) and source file.

**Scope note.** The Forge engine RTL, STRATEGY.md, BEAT_PLAN.md and
beat-plan/strategy/CLOCK_3GHZ_PLAN.md were not in this checkout, so the domain plan
below is generic (host, core, memory) and has not been bound to the engine's real
blocks or to a chosen FPGA device. Binding it is the first integration step (see
"Open items").

## 1. Clock domains

### FPGA, 250 MHz target

| Domain | Clock | Rate | Source | Carries |
|---|---|---|---|---|
| core | `clk_core` | 250 MHz target (4.000 ns) | MMCM from the platform reference | the engine; may span SLRs |
| host | `clk_host` | set by the platform shell | shell | command stream in, result stream out, CSRs |
| mem | `clk_mem` | set by the memory controller | DDR4 / HBM IP | weight refill stream, refill-done event |

### ASIC, 3 GHz track (modelled only)

| Domain | Clock | Rate | Notes |
|---|---|---|---|
| core | `clk_core` | 3 GHz (333.3 ps) | on-chip PLL and clock tree are **not modelled** (ideal clocks + an uncertainty budget) |
| io | `clk_io` | lower, set by the interface | all core <-> io traffic through `cdc_async_fifo` with 3-flop synchronizers |

Every 3 GHz number in this pack is **modelled**: ASAP7 predictive PDK, pre-layout,
one corner at a time. None of it is silicon or measured hardware.

## 2. Which primitive for which crossing

| Crossing | Primitive | Latency (dst cycles) | Rate | Notes |
|---|---|---|---|---|
| single-bit level (status, enable) | `cdc_sync_bit` | STAGES | any | source must be a flop |
| single event (done, interrupt) | `cdc_pulse_sync` | STAGES+1 | one event per round trip; `src_busy` refuses more | for bursts, cross a Gray counter instead |
| multi-bit word, low rate (CSR, config) | `cdc_handshake` | about STAGES+2 | one word per round trip | data held stable, captured under the synchronized request |
| stream | `cdc_async_fifo` | about STAGES+1 | one word per cycle of the slower clock | LUTRAM storage, FWFT read, conservative `rlevel`/`wfree` for bursts |
| multi-bit counter (credits, levels) | Gray code + `cdc_sync_bit`, source marked `(* cdc_gray *)` | STAGES | | binary counters are rejected by the checker |
| reset | `cdc_reset_sync`, one per domain | STAGES (release) | | asynchronous assert, synchronous release |
| long route inside one clock (SLR, far blocks) | `slr_crossing` (valid/ready) or `pipe_reg` (fixed latency) | FWD_STAGES+1 | full rate | every crossing wire flop-to-flop |

Deep stream buffers (hundreds of entries) are not in this pack: use a BRAM FIFO with a
registered read (on AMD, `xpm_fifo_async`).

## 3. Rules, and what enforces each one

| # | Rule | Enforced by |
|---|---|---|
| R1 | Every crossing goes through exactly one primitive from section 2. | `tools/cdc_check.py` (ERROR `unsynchronized`) |
| R2 | A synchronizer's input comes straight from a flop in the source domain: no logic, one source. | checker (`logic_before_sync`) |
| R3 | Synchronizers are >= 2 flops for the 250 MHz FPGA target and 3 flops on the 3 GHz track; all stages carry `ASYNC_REG`. | RTL parameter check; checker (`sync_too_short`); MTBF model in docs/ASIC_3GHZ_MODELLED.md |
| R4 | A multi-bit value crosses through bit synchronizers only if it is Gray coded (at most one bit changes per source update). | checker (`multibit_not_gray`); formal one-bit-change assertion on the FIFO pointers |
| R5 | One source is synchronized once per destination domain; fan out after the synchronizer. | checker (WARNING `divergent_sync`) |
| R6 | One raw reset, one reset bridge per domain; every async reset pin is driven by its own domain's bridge. Both sides of a FIFO reset together. | checker (`reset_not_bridged`); FIFO formal environment |
| R7 | Per clock pair: datapath-only max delay of one destination period; bus skew on Gray pointers. No `set_clock_groups -asynchronous` between clocks that carry Gray buses (in Vivado it overrides `set_max_delay`). | `constraints/fpga_250mhz.tcl`, `constraints/asic_3ghz_modelled.sdc` |
| R8 | Every primitive is verified three ways: structure (checker), function (multi-clock simulation with jitter and clock ratios from 13:1 to 1:13), proof (SymbiYosys, any clock interleaving, metastability model). | `flows/run_cdc.sh`, `flows/run_sim.sh`, `flows/run_formal.sh` |
| R9 | Registers meant to break timing paths (SLR crossing, `pipe_reg`, retiming registers) carry `SHREG_EXTRACT="NO"`, so Vivado cannot fold them into one SRL. | RTL attributes; open-flow probe in `results/fpga` |

## 4. The metastability model used in the proofs

`cdc_sync_bit` has a formal-only model (`FORMAL_META`). A bit that changed in the
global step just before the capturing edge may resolve to either its old or its new
value, freely per bit and per edge; a stable bit is captured correctly; the extra
latency is at most one destination cycle. Without such a model a formal tool, like RTL
simulation, sees every bus change atomically and cannot tell a Gray pointer from a
binary one. The pack shows this directly: the binary-pointer FIFO mutant passes
simulation and passes the proof without the model, and fails the proof with it.

## 5. Integration example

`examples/three_domain_top.sv` wires all of the above for three clocks: one reset
bridge per domain, command and result FIFOs between host and core, a refill FIFO and a
refill-done event from memory to core, a CSR handshake, a busy status bit, and an
`slr_crossing` between two halves of the core. It passes lint and the CDC checker
(33 synchronized crossings, 64 qualified captures, 0 errors).

## 6. Open items

* Bind the domain plan to the Forge engine's real top once its RTL is in the
  worktree, and run `flows/run_cdc.sh` on it.
* Choose the FPGA device (STRATEGY.md); then fill the SLR pblocks and Laguna
  register patterns in `constraints/fpga_250mhz.tcl` and run Vivado `report_cdc`,
  `report_bus_skew` and `report_timing_summary` (not yet: no Vivado here).
* Characterize tau and T_w of the ASAP7 flop (SPICE) before trusting any MTBF figure;
  until then the 3 GHz rule is 3 stages (docs/ASIC_3GHZ_MODELLED.md).
* Reconcile with CLOCK_3GHZ_PLAN.md (owned by the 3 GHz session; not read here
  because it was not in this checkout).
