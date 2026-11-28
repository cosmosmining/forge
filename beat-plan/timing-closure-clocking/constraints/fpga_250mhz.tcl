# fpga_250mhz.tcl -- clocking, CDC and SLR constraints template for the 250 MHz FPGA
# target (AMD UltraScale+). Forge Feature 5 (timing-closure / clocking pack).
#
# This is an UNMANAGED Tcl constraints file (it uses proc/foreach/if, which a managed
# .xdc does not allow). Load it with:  read_xdc -unmanaged constraints/fpga_250mhz.tcl
#
# STATUS: NOT YET RUN. Vivado is not available in the environment that built this pack
# (it needs an AMD account to download; the session rules forbid accounts). Nothing in
# this file has been checked by Vivado. Cell-name patterns follow Vivado's usual naming
# of the pack RTL (<reg>_reg[...], generate blocks as g_name[i].); confirm each pattern
# with get_cells after the first synth_design before trusting it.
#
# Bind the clock ports to the real top. The Forge engine top is not in this checkout, so
# the names below are those of examples/three_domain_top.sv.

## ---------------------------------------------------------------- 1. clocks
# Compute clock: the 250 MHz target.
create_clock -name clk_core -period 4.000 [get_ports clk_core]
# Host/shell and memory-controller clocks are defined by the platform's own constraints
# (shell XDC, memory IP). Uncomment only for a standalone build of this example:
# create_clock -name clk_host -period <platform period> [get_ports clk_host]
# create_clock -name clk_mem  -period <platform period> [get_ports clk_mem]

## ---------------------------------------------------- 2. clock-domain crossings
# Do NOT use set_clock_groups -asynchronous between these clocks: in Vivado it takes
# priority over set_max_delay and would silently drop the Gray-pointer constraints
# below. Every crossing goes through a pack primitive (checked by tools/cdc_check.py),
# so each clock pair gets one destination period of datapath-only delay. This is the
# same pattern AMD's xpm_fifo_async uses.
proc forge_cdc_pair {src dst} {
  set p [get_property PERIOD [get_clocks $dst]]
  set_max_delay -datapath_only -from [get_clocks $src] -to [get_clocks $dst] $p
}
foreach {src dst} {clk_host clk_core  clk_core clk_host  clk_mem clk_core} {
  if {[llength [get_clocks -quiet $src]] && [llength [get_clocks -quiet $dst]]} {
    forge_cdc_pair $src $dst
  }
}

# Gray pointers: all bits of a pointer must arrive within one destination period of
# each other, so the synchronized value is always the old or the new pointer.
foreach fifo [get_cells -quiet -hier -filter {REF_NAME == cdc_async_fifo || ORIG_REF_NAME == cdc_async_fifo}] {
  set wclk_p [get_property PERIOD [get_clocks -of_objects [get_pins -quiet $fifo/wclk]]]
  set rclk_p [get_property PERIOD [get_clocks -of_objects [get_pins -quiet $fifo/rclk]]]
  set skew [expr {min($wclk_p, $rclk_p)}]
  set_bus_skew -from [get_cells $fifo/wgray_reg[*]] -to [get_cells $fifo/u_wptr_sync/sync_q_reg[*]] $skew
  set_bus_skew -from [get_cells $fifo/rgray_reg[*]] -to [get_cells $fifo/u_rptr_sync/sync_q_reg[*]] $skew
}

# Synchronizer and reset-bridge flops (ASYNC_REG is also set in the RTL).
set_property ASYNC_REG TRUE [get_cells -quiet -hier -filter {NAME =~ */sync_q_reg[*]}]
set_property ASYNC_REG TRUE [get_cells -quiet -hier -filter {NAME =~ */r_reg[*] && PARENT =~ *rst*}]

## -------------------------------------------------- 3. pipelines stay flops
# SHREG_EXTRACT=NO is set in the RTL on slr_crossing / pipe_reg / dot_reduce pipeline
# registers. An SRL would put the whole delay line in one SLICE and undo the pipelining.
# (yosys ignores this attribute; Vivado honours it.)

## --------------------------------------------------- 4. SLR floorplan (pblocks)
# Device-specific. The target device and its SLR count come from STRATEGY.md, which is
# not in this checkout, so these lines are commented. Pattern for a 2-SLR split of the
# example core: half A (command/refill side) in SLR0, half B (accumulator, results) in
# SLR1, the slr_crossing straddling the boundary.
# create_pblock pb_slr0
# resize_pblock pb_slr0 -add SLR0
# create_pblock pb_slr1
# resize_pblock pb_slr1 -add SLR1
# add_cells_to_pblock pb_slr0 [get_cells {u_cmd_fifo u_ref_fifo u_csr u_done}]
# add_cells_to_pblock pb_slr1 [get_cells {u_res_fifo u_slr/u_rx_fifo}]
# Softer alternative: let the placer choose sites but keep the SLR:
# set_property USER_SLR_ASSIGNMENT SLR0 [get_cells {u_cmd_fifo u_ref_fifo}]

# Laguna registers on every wire that crosses the boundary (UG949 SLR-crossing
# guidance): forward stage 0 is TX (source SLR) and stage 1 is RX (destination SLR);
# backward stage 0 is TX (destination SLR) and stage 1 is RX (source SLR).
# set_property USER_SLL_REG TRUE [get_cells -hier -filter {NAME =~ */g_fwd[0].d_q_reg* || NAME =~ */g_fwd[0].v_q_reg*}]
# set_property USER_SLL_REG TRUE [get_cells -hier -filter {NAME =~ */g_fwd[1].d_q_reg* || NAME =~ */g_fwd[1].v_q_reg*}]
# set_property USER_SLL_REG TRUE [get_cells -hier -filter {NAME =~ */g_bwd[0].r_q_reg* || NAME =~ */g_bwd[1].r_q_reg*}]

## ----------------------------------------------- 5. checks to run in Vivado (not yet)
# report_cdc -details -file cdc.rpt                      ;# every crossing must be a known safe structure
# report_clock_interaction -file clock_interaction.rpt   ;# no unexpected "Timed (unsafe)" pairs
# report_bus_skew -file bus_skew.rpt                     ;# the Gray pointer constraints above
# report_design_analysis -logic_level_distribution -file logic_levels.rpt
# report_timing_summary -file timing_summary.rpt         ;# WNS >= 0 at 4.000 ns
# Retiming, if wanted: synth_design -retiming (and compare logic levels with this pack's
# open-flow numbers in results/fpga/summary.tsv).
