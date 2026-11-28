# pnr_agent generated script: stage=grt design=standin_aes_250mhz

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
read_liberty {/nix/store/sp1shfcy9livvw7zskwd4wqz9nz3l92z-source/test/Nangate45/Nangate45_slow.lib}
read_db {/tmp/claude-0/-home-user-forge/5ce94ace-2cb9-5c7a-a28a-46f486100577/scratchpad/agent_work_aes/standin_aes_250mhz/flow/cache/cts/84fd76d22939c289/cts.odb}
read_sdc {/home/user/forge/beat-plan/pnr-tuning-agent/designs/standin_aes_250mhz.sdc}
source {/nix/store/sp1shfcy9livvw7zskwd4wqz9nz3l92z-source/test/Nangate45/Nangate45.rc}
set_wire_rc -signal -layer metal3
set_wire_rc -clock -layer metal6
set_dont_use {CLKBUF_* AOI211_X1 OAI211_X1}
set_routing_layers -signal metal2-metal10 -clock metal6-metal10
set_global_routing_layer_adjustment metal2-metal10 0.5
set_propagated_clock [all_clocks]
pin_access -bottom_routing_layer metal2 -top_routing_layer metal10
global_route -congestion_iterations 100 -verbose -congestion_report_file {/tmp/claude-0/-home-user-forge/5ce94ace-2cb9-5c7a-a28a-46f486100577/scratchpad/agent_work_aes/standin_aes_250mhz/flow/cache/grt/14e9311e8202b580/congestion.rpt}
estimate_parasitics -global_routing
global_route -start_incremental
repair_timing -setup_margin 0.1300 -skip_gate_cloning
set_placement_padding -global -left 1 -right 1
detailed_placement
global_route -end_incremental -congestion_report_file {/tmp/claude-0/-home-user-forge/5ce94ace-2cb9-5c7a-a28a-46f486100577/scratchpad/agent_work_aes/standin_aes_250mhz/flow/cache/grt/14e9311e8202b580/congestion_eco.rpt}
estimate_parasitics -global_routing
pa_timing_metrics grt
repair_antennas -iterations 5
pa_metric grt_antenna_nets [check_antennas]
write_guides {/tmp/claude-0/-home-user-forge/5ce94ace-2cb9-5c7a-a28a-46f486100577/scratchpad/agent_work_aes/standin_aes_250mhz/flow/cache/grt/14e9311e8202b580/route.guide}
pa_metric utilization [rsz::utilization]
pa_metric design_area [rsz::design_area]
write_db {/tmp/claude-0/-home-user-forge/5ce94ace-2cb9-5c7a-a28a-46f486100577/scratchpad/agent_work_aes/standin_aes_250mhz/flow/cache/grt/14e9311e8202b580/grt.odb}
pa_write_metrics {/tmp/claude-0/-home-user-forge/5ce94ace-2cb9-5c7a-a28a-46f486100577/scratchpad/agent_work_aes/standin_aes_250mhz/flow/cache/grt/14e9311e8202b580/metrics.json}
