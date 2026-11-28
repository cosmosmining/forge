# 3 GHz ASIC track: MODELLED ONLY

Forge Feature 5 (timing-closure / clocking pack).

> **Every number on this page is modelled.** ASAP7 is a *predictive* 7 nm PDK (ASU /
> ARM research kit). The analysis is pre-layout: yosys + ABC mapping, OpenSTA with
> NLDM tables, ideal clocks (no clock tree), no wire RC, one corner at a time. No
> number here was measured on silicon or on any hardware, and none should be quoted
> as a chip result. In Forge's reporting kinds these are all **model** numbers; the
> brief asked for the label "modelled", used throughout.

Sources: `results/asic_modelled/` (one STA summary, worst-path report and area report
per block and corner), produced by `flows/run_asic_modelled.sh`. The CLOCK_3GHZ_PLAN.md
of the 3 GHz session was not in this checkout and was not read or changed; this page
covers clocking, CDC and timing closure only, and should be reconciled with that plan.

## 1. Model set-up and its assumptions

| Item | Value | Note |
|---|---|---|
| Library | ASAP7 RVT, NLDM, TT (0.7 V, 25 C) primary, SS sensitivity | ORFS commit 8ba54e7, SHA-256 pinned. ORFS itself defaults asap7 to the FF corner, so compare corners before comparing numbers |
| Cells excluded | `*x1p*`, `*xp*`, `SDF*`, `ICG*` | ORFS asap7 DONT_USE_CELLS |
| Mapping | `dfflibmap`, then `abc -script abc_speed.script`, driver BUFx2, load 3.898 fF | ORFS asap7 settings and script |
| Clock | 333.333 ps on every clock, ideal, uncertainty 0 in the runs | the budget (section 3) is applied on top: with ideal clocks, slack(U) = slack(0) - U |
| Clock-domain crossings | datapath-only max delay = 333.3 ps per clock pair | constraints/asic_3ghz_modelled.sdc |
| I/O | false paths (block level) | only register-to-register paths are judged, as in ORFS' own asap7 constraints |
| Wires | none (no wire-load model in ASAP7 libs) | optimistic; see section 3 |
| Synchronizers | 3 flops (`STAGES=3`) | section 4 |

## 2. Results at 3 GHz (modelled)

Worst register-to-register (or crossing) slack, ps. Negative = does not close.

| Block | TT | SS | Area um2 (TT) | Note |
|---|---|---|---|---|
| cdc_pulse_sync, 3 stages | +221.6 | +158.4 | 4.1 | |
| cdc_handshake, 32 bit, 3 stages | +134.5 | +36.9 | 42.4 | |
| cdc_async_fifo 32x16, 3 stages | **+67.5** | -100.0 | 433.4 | after fix |
| ...same, before the fix | +17.4 | -144.5 | 429.6 | `flows/asic/prefix/` |
| cdc_async_fifo 64x64, 3 stages | +3.3 | -154.4 | 3169.5 | 4096 storage flops; margin too thin, see below |
| skid_buffer 64 bit | +135.3 | +26.7 | 88.2 | |
| slr_crossing 64 bit, 2+2 stages, depth 8 | **+83.8** | -59.5 | 436.0 | after fix |
| ...same, before the fix | +44.9 | -108.1 | 443.5 | |
| dot_reduce, 4 lanes of signed 8x8 (stand-in), no pipelining | -432.9 | -830.5 | 274.9 | not the Forge MAC row |
| ...register after multipliers and every adder level | -303.1 | -635.2 | 289.7 | |
| ...3 output registers, no retiming | -507.6 | -945.5 | 322.0 | |
| ...3 output registers, **retimed** (ORFS abc_retime) | **+62.8** | -75.9 | 386.3 | |

FO4 (INVx1 driving four INVx1, ASAP7 RVT): **19.5 ps at TT, 29.2 ps at SS**, so a
333.3 ps cycle is **17.1 FO4 at TT and 11.4 FO4 at SS** (`results/asic_modelled/fo4.*.txt`).

What the table says, read as modelled guidance:

1. **All pack primitives close at 3 GHz at TT, with zero wire delay.** The
   synchronizer, pulse, handshake and skid paths have more than 100 ps to spare at TT.
2. **The timing-closure loop worked on the FIFOs.** The first run (yosys' default ABC
   script) showed the async FIFO at -48.5 ps and the SLR crossing at -48.0 ps; the
   failing paths were the Gray-to-binary + subtract feeding `rlevel`/`wfree` and the
   combinational `full` feeding the write decode (`results/history/`). The fix,
   registering the converted pointer (levels stay conservative, one cycle later) and
   registering `full`/`empty`/`count`, is worth about +40 to +50 ps at both corners
   under the same ORFS flow (rows "before the fix"). Re-verified after the fix:
   simulation, all formal proofs, CDC check.
3. **At SS the FIFOs and the SLR crossing do not close** (-60 to -155 ps). The
   remaining paths are pointer -> increment -> Gray -> full/empty compare, and pointer
   -> write decode -> buffer tree -> storage flop. Next steps, not done here:
   duplicate pointer flops to split decode fan-out from the compare, pre-decoded
   (one-hot) write enables, or a register-file macro instead of 512+ storage flops.
4. **64x64 in flops is the wrong structure at 3 GHz** (+3.3 ps at TT with no wires is
   no margin). Keep 3 GHz CDC FIFOs at 16 entries or less, or use a macro.
5. **Retiming matters on this track.** Registers placed by hand after each tree level
   do not help when one 8x8 multiplier alone takes about 600 ps (worst path entirely
   inside it); the same three registers placed at the output and retimed by ABC split
   the multiplier and close at +62.8 ps (TT). On the FPGA track the open flow did not
   retime at all (docs/FPGA_250MHZ.md), so do not carry this result over.

## 3. What the slack has to cover (modelled)

The STA above has ideal clocks and no wires. Before a block is called 3 GHz-ready, its
TT slack must cover U = clock uncertainty (jitter + skew after clock-tree synthesis) +
post-route wire delay on the worst path + on-chip-variation derate. **This pack does
not estimate U**; it needs a placed-and-routed ASAP7 run (not yet). The table only
shows what is left for two illustrative thresholds (arithmetic on the modelled slack):

| Block (TT) | slack | slack - 50 ps | slack - 100 ps |
|---|---|---|---|
| cdc_pulse_sync | +221.6 | +171.6 | +121.6 |
| skid_buffer 64 | +135.3 | +85.3 | +35.3 |
| cdc_handshake 32 | +134.5 | +84.5 | +34.5 |
| slr_crossing 64 (fixed) | +83.8 | +33.8 | -16.2 |
| cdc_async_fifo 32x16 (fixed) | +67.5 | +17.5 | -32.5 |
| dot_reduce stand-in, retimed | +62.8 | +12.8 | -37.2 |
| cdc_async_fifo 64x64 | +3.3 | -46.7 | -96.7 |

So the CDC primitives and the skid buffer keep margin even at U = 100 ps; the FIFO and
SLR blocks need the SS-corner fixes listed in section 2 before U is known; the 64x64
flop FIFO is out.

## 4. Synchronizer depth at 3 GHz: MTBF model

`MTBF = exp(t_r / tau) / (T_w * f_clk * f_data)`, per synchronizer.

* t_r comes from STA (`flows/asic/sync_stage.tcl`): per-stage resolution slack =
  period - clk->Q - setup. At TT: **252.2 ps** with the inverter yosys inserts between
  DFFASRHQNx1 stages (QN output), **258.7 ps** with QN wired straight to the next D;
  at SS: 204.1 / 224.0 ps. An N-flop synchronizer has (N-1) stages of resolution.
* **tau and T_w of the ASAP7 flop are not characterized here** (that needs SPICE on
  the cell). So tau is swept and the result is stated as tau_max: the largest tau for
  which the synchronizer still reaches 1e9 years at f_clk = 3 GHz and f_data = 3e9/s
  (a Gray pointer written every cycle). T_w is set to 20 ps; tau_max barely depends
  on it (4.61 / 4.42 / 4.25 ps for T_w = 2 / 20 / 200 ps, N = 2, TT).

| Corner | Stages | tau_max for MTBF >= 1e9 years |
|---|---|---|
| TT | 2 | 4.4 ps |
| TT | 3 | 8.9 ps |
| TT | 4 | 13.3 ps |
| SS | 2 | 3.6 ps |
| SS | 3 | 7.2 ps |
| SS | 4 | 10.7 ps |

**Rule for the 3 GHz track:** 3-flop synchronizers by default; 2 flops only after a
characterized tau below about 3.5 ps (SS); 4 flops if tau turns out above about 7 ps.
A chip has hundreds of synchronizer bits, so the per-synchronizer target should be
divided by their number. Full sweep: `results/asic_modelled/mtbf_model.txt`.

## 5. Not yet

* Placement, clock-tree synthesis, routing, parasitic extraction (OpenROAD not
  installed here). Until then wires and clock skew are the allowances in section 3.
* tau / T_w characterization of DFFASRHQNx1 (and a dedicated synchronizer cell).
* LVT/SLVT variants, multi-corner signoff, hold analysis (hold is meaningless with
  ideal clocks and no wires).
* The Forge engine's own blocks at 3 GHz: their RTL was not in this checkout. The
  stand-in datapath is not the Forge MAC row.
