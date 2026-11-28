# pnr_agent generated script: stage=drt design=standin_gcd

set ::pa_metrics {}
proc pa_metric {key value} { lappend ::pa_metrics $key $value }
proc pa_num {v} {
  if {[string is double -strict $v]} {
    if {abs($v) > 1e29} { return null }
    return [format %.6g $v]
  }
  return "\"$v\""
}
proc pa_write_metrics {path} {
  set fh [open $path w]
  puts $fh "\{"
  set n [llength $::pa_metrics]
  for {set i 0} {$i < $n} {incr i 2} {
    set k [lindex $::pa_metrics $i]
    set v [pa_num [lindex $::pa_metrics [expr {$i + 1}]]]
    set sep [expr {$i + 2 < $n ? "," : ""}]
    puts $fh "  \"$k\": $v$sep"
  }
  puts $fh "\}"
  close $fh
}
proc pa_timing_metrics {prefix} {
  pa_metric ${prefix}_wns [sta::worst_slack -max]
  pa_metric ${prefix}_tns [sta::total_negative_slack -max]
  pa_metric ${prefix}_hold_wns [sta::worst_slack -min]
}
proc pa_have_macros {} {
  foreach inst [[[[::ord::get_db] getChip] getBlock] getInsts] {
    if {[string match [[$inst getMaster] getType] "BLOCK"]} { return 1 }
  }
  return 0
}

source {/home/user/forge/beat-plan/pnr-tuning-agent/designs/openroad_test_sdc_helpers.tcl}
set_thread_count 1
sta::set_thread_count 1
read_lef {/nix/store/sp1shfcy9livvw7zskwd4wqz9nz3l92z-source/test/Nangate45/Nangate45_tech.lef}
read_lef {/nix/store/sp1shfcy9livvw7zskwd4wqz9nz3l92z-source/test/Nangate45/Nangate45_stdcell.lef}
read_liberty {/nix/store/sp1shfcy9livvw7zskwd4wqz9nz3l92z-source/test/Nangate45/Nangate45_typ.lib}
read_db {/tmp/claude-0/-home-user-forge/5ce94ace-2cb9-5c7a-a28a-46f486100577/scratchpad/agent_work_gcd/standin_gcd/flow/cache/grt/f1fb19d50689df94/grt.odb}
read_sdc {/nix/store/sp1shfcy9livvw7zskwd4wqz9nz3l92z-source/test/gcd_nangate45.sdc}
source {/nix/store/sp1shfcy9livvw7zskwd4wqz9nz3l92z-source/test/Nangate45/Nangate45.rc}
set_wire_rc -signal -layer metal3
set_wire_rc -clock -layer metal6
set_dont_use {CLKBUF_* AOI211_X1 OAI211_X1}
set_routing_layers -signal metal2-metal10 -clock metal6-metal10
set_global_routing_layer_adjustment metal2-metal10 0.5
set_propagated_clock [all_clocks]
read_guides {/tmp/claude-0/-home-user-forge/5ce94ace-2cb9-5c7a-a28a-46f486100577/scratchpad/agent_work_gcd/standin_gcd/flow/cache/grt/f1fb19d50689df94/route.guide}
pin_access -bottom_routing_layer metal2 -top_routing_layer metal10
detailed_route -output_drc {/tmp/claude-0/-home-user-forge/5ce94ace-2cb9-5c7a-a28a-46f486100577/scratchpad/agent_work_gcd/standin_gcd/flow/cache/drt/247ac001647cae81/drc.rpt} -no_pin_access -save_guide_updates -bottom_routing_layer metal2 -top_routing_layer metal10 -verbose 0
set ant_iter 0
while {[check_antennas] && $ant_iter < 5} {
  repair_antennas
  detailed_route -output_drc {/tmp/claude-0/-home-user-forge/5ce94ace-2cb9-5c7a-a28a-46f486100577/scratchpad/agent_work_gcd/standin_gcd/flow/cache/drt/247ac001647cae81/drc_ant.rpt} -save_guide_updates -bottom_routing_layer metal2 -top_routing_layer metal10 -verbose 0
  incr ant_iter
}
if {![catch {detailed_route_num_drvs} pa_drc]} { puts "PA_DRC_COUNT $pa_drc"; pa_metric drc_count $pa_drc }
pa_metric antenna_nets [check_antennas]
pa_metric routed [design_is_routed]
filler_placement FILLCELL*
pa_metric placement_ok [expr {[catch {check_placement -verbose}] == 0}]
pa_metric utilization [rsz::utilization]
pa_metric design_area [rsz::design_area]
write_verilog -remove_cells {FILLCELL* TAPCELL*} {/tmp/claude-0/-home-user-forge/5ce94ace-2cb9-5c7a-a28a-46f486100577/scratchpad/agent_work_gcd/standin_gcd/flow/cache/drt/247ac001647cae81/final.v}
write_def {/tmp/claude-0/-home-user-forge/5ce94ace-2cb9-5c7a-a28a-46f486100577/scratchpad/agent_work_gcd/standin_gcd/flow/cache/drt/247ac001647cae81/final.def}
define_process_corner -ext_model_index 0 X
extract_parasitics -ext_model_file {/nix/store/sp1shfcy9livvw7zskwd4wqz9nz3l92z-source/test/Nangate45/Nangate45.rcx_rules}
write_spef {/tmp/claude-0/-home-user-forge/5ce94ace-2cb9-5c7a-a28a-46f486100577/scratchpad/agent_work_gcd/standin_gcd/flow/cache/drt/247ac001647cae81/final.spef}
write_db {/tmp/claude-0/-home-user-forge/5ce94ace-2cb9-5c7a-a28a-46f486100577/scratchpad/agent_work_gcd/standin_gcd/flow/cache/drt/247ac001647cae81/drt.odb}
pa_write_metrics {/tmp/claude-0/-home-user-forge/5ce94ace-2cb9-5c7a-a28a-46f486100577/scratchpad/agent_work_gcd/standin_gcd/flow/cache/drt/247ac001647cae81/metrics.json}
