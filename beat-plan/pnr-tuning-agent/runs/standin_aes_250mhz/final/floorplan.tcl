# pnr_agent generated script: stage=floorplan design=standin_aes_250mhz

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
read_verilog {/nix/store/sp1shfcy9livvw7zskwd4wqz9nz3l92z-source/test/aes_nangate45.v}
link_design aes_cipher_top
read_sdc {/home/user/forge/beat-plan/pnr-tuning-agent/designs/standin_aes_250mhz.sdc}
source {/nix/store/sp1shfcy9livvw7zskwd4wqz9nz3l92z-source/test/Nangate45/Nangate45.rc}
set_wire_rc -signal -layer metal3
set_wire_rc -clock -layer metal6
set_dont_use {CLKBUF_* AOI211_X1 OAI211_X1}
initialize_floorplan -site FreePDK45_38x28_10R_NP_162NW_34O -die_area {0.0 0.0 1020.0 920.8} -core_area {10.0 12.0 1010.0 911.2}
source {/nix/store/sp1shfcy9livvw7zskwd4wqz9nz3l92z-source/test/Nangate45/Nangate45.tracks}
remove_buffers
place_pins -random -hor_layers metal3 -ver_layers metal2
if {[pa_have_macros]} {
  rtl_macro_placer -halo_width 22.4 -halo_height 15.12 -report_directory {/tmp/claude-0/-home-user-forge/5ce94ace-2cb9-5c7a-a28a-46f486100577/scratchpad/agent_work_aes/standin_aes_250mhz/flow/cache/floorplan/8a67ccb319879d59/rtlmp}
}
tapcell -distance 120 -tapcell_master TAPCELL_X1 -endcap_master TAPCELL_X1
source {/nix/store/sp1shfcy9livvw7zskwd4wqz9nz3l92z-source/test/Nangate45/Nangate45.pdn.tcl}
pdngen
pa_metric instance_count [llength [get_cells *]]
write_db {/tmp/claude-0/-home-user-forge/5ce94ace-2cb9-5c7a-a28a-46f486100577/scratchpad/agent_work_aes/standin_aes_250mhz/flow/cache/floorplan/8a67ccb319879d59/floorplan.odb}
pa_write_metrics {/tmp/claude-0/-home-user-forge/5ce94ace-2cb9-5c7a-a28a-46f486100577/scratchpad/agent_work_aes/standin_aes_250mhz/flow/cache/floorplan/8a67ccb319879d59/metrics.json}
