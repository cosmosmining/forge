# 250 MHz FPGA target: clocking, SLR floorplanning, pipelining, retiming, LUTRAM

Forge Feature 5 (timing-closure / clocking pack).

**Evidence level.** Vivado was not available in the environment that built this pack
(downloading it needs an AMD account, which the session rules forbid). Everything
measured here comes from the open yosys flow (`synth_xilinx -family xcup`, UltraScale+
primitives) plus `tools/logic_depth.py`: resource mapping and register-to-register
logic levels. That is structure, not timing: no placement, no routing, no Vivado
delay model. **FPGA timing at 250 MHz, `report_cdc`, SLR placement and any hardware run
are "not yet".** The production path is Vivado synthesis of the same RTL with
`constraints/fpga_250mhz.tcl`.

The device is not chosen (STRATEGY.md is not in this checkout), so the SLR material
below is device-independent.

## 1. Clocks and crossings

Three domains (docs/CLOCKING_SPEC.md): `clk_core` at the 250 MHz target, `clk_host`
and `clk_mem` at whatever the platform shell and memory controller give. Every
crossing goes through a pack primitive, with 2-flop synchronizers at this frequency.
The constraints template (`constraints/fpga_250mhz.tcl`, Vivado unmanaged Tcl):

* `create_clock` for `clk_core` at 4.000 ns; platform clocks come from platform XDC;
* per clock pair `set_max_delay -datapath_only` = one destination period, and
  `set_bus_skew` on every async FIFO's Gray pointers; deliberately **no**
  `set_clock_groups -asynchronous` between these clocks, because in Vivado it takes
  priority over `set_max_delay` and would silently drop the Gray constraints (the same
  pattern AMD's `xpm_fifo_async` uses);
* `ASYNC_REG` on synchronizer and reset-bridge flops (also set in RTL);
* the Vivado reports to run first: `report_cdc`, `report_clock_interaction`,
  `report_bus_skew`, `report_design_analysis -logic_level_distribution`,
  `report_timing_summary`.

## 2. SLR floorplanning and the SLR crossing

AMD's UltraScale+ guidance for crossing an SLR boundary (UG949) is: leave a flop,
cross on the super long line, land in a flop, with nothing in between, so that both
flops can sit in the Laguna TX/RX sites. A valid/ready channel cannot be cut that way,
because `ready` runs backwards combinationally. `rtl/slr_crossing.sv` therefore:

* sends `data`/`valid` forward through FWD_STAGES plain flops (no enable, no logic,
  data flops without reset);
* returns a credit ("room") backwards through BWD_STAGES plain flops: that is `s_ready`;
* lands words in a LUTRAM FIFO that keeps FWD_STAGES + BWD_STAGES entries free for
  words granted before "room" fell.

Proved (unbounded): no loss, duplication, reordering or corruption; the FIFO is never
pushed while full; full throughput when the consumer is always ready. The mutant with
one entry less of margin fails, so the margin is exact. Measured in the open flow: the
512-bit crossing keeps every crossing register a flop (no SRL), and its receive FIFO
maps to LUTRAM (table below).

Floorplan pattern (commented in the constraints until the device is known): one pblock
per SLR (`resize_pblock -add SLR<n>`) or the softer `USER_SLR_ASSIGNMENT`; forward
stage 0 and backward stage 1 in the source SLR, forward stage 1 and backward stage 0 in
the destination SLR, all four marked `USER_SLL_REG`. Every bus that crosses gets its
own `slr_crossing`; nothing else crosses.

## 3. Results from the open flow (measured, yosys 0.71, not Vivado)

(Table pending: filled from `results/fpga/summary.tsv` of the final gate run, committed with the results.)

Reading it:

* **LUTRAM.** The FIFOs map to distributed RAM (RAM32M16 for 16 or 32 entries,
  RAM64M8 for 64), not to flops and not to BRAM: that is what the asynchronous-read
  array is written for. The 512-bit SLR crossing's 8-entry receive FIFO is 37 LUTRAM
  cells (512 / 14 bits per RAM32M16).
* **No SRL in synchronizers or SLR pipelines** (SRL column = 0 for every pack
  primitive). But yosys **ignores** `shreg_extract="no"`: the `pipe_w8_s4_srlprobe` row
  shows a 4-deep `pipe_reg` packed into SRL16E. Vivado honours the attribute, so the
  RTL keeps it; open-flow pipeline experiments use `-nosrl`.
* **Structural pipelining works; open-flow retiming does not.** The stand-in datapath
  (16 lanes of signed 8x8, LUT-only with `-nodsp`) goes from the unpipelined depth to
  about half with a register after the multipliers and after every adder level
  (`dot_t1o0`). Three registers at the output (`dot_t0o3`) leave the worst path where
  it was, and yosys/ABC9 sequential mapping (`-dff`) did not move them into the tree
  (`dot_t0o3_nodsp_dff`). So in this flow, place pipeline registers where they are
  needed; Vivado's own retiming (`synth_design -retiming`) is not yet tried. On the
  ASAP7 track ABC's retiming did close the same structure (docs/ASIC_3GHZ_MODELLED.md):
  the two results are tool-specific and should not be mixed.
* **Logic levels are a bracket, not a number.** yosys maps UltraScale+ adders to
  CARRY4 cells where Vivado uses CARRY8, so "levels" (every cell counts) over-counts
  carry chains and "carry-collapsed" (a cascaded chain counts once) under-counts. With
  DSP48E2 inference the multipliers sit in DSPs, which `logic_depth.py` treats as
  register boundaries, so those rows exclude the multiplier's own delay.
* **What fits 250 MHz** is not decided by these numbers: the level budget at 4.000 ns
  depends on the device, speed grade and routing, and is a Vivado result (not yet).

## 4. Not yet

Vivado synthesis, implementation and timing at 250 MHz; `report_cdc`; device choice,
SLR pblocks and Laguna placement; Vivado retiming; FPGA hardware (tokens per second,
power).
