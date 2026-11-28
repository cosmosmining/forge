# sync_stage.tcl -- resolution-time budget of one synchronizer stage at 3 GHz.
# MODELLED ONLY (ASAP7 predictive PDK, NLDM, ideal clock). Env: STA_LIBS.
# For each variant: clk->Q (+ INVx1 for variant a), the capture flop's setup time, and
# the slack left over = the time a metastable first stage has to resolve before the
# second stage samples it.
suppress_msg 1212
foreach lib $::env(STA_LIBS) { read_liberty $lib }
read_verilog [file join [file dirname [info script]] sync_stage.v]
link_design sync_stage
create_clock -name clk -period 333.333 [get_ports clk]
set_false_path -from [get_ports {d rst_n}]
set_false_path -to [all_outputs]
foreach {v from to} {a a0 a1 b b0 b1} {
  set pe [lindex [find_timing_paths -path_delay max -from [get_cells $from] -to [get_cells $to]] 0]
  set pts [get_property $pe points]
  set arr [get_property [lindex $pts end] arrival]
  set slack [get_property $pe slack]
  set setup [expr {333.333 - $arr - $slack}]
  puts [format "SYNCSTAGE variant=%s arrival_ps=%.2f setup_ps=%.2f resolution_slack_ps=%.2f" $v $arr $setup $slack]
}
exit
