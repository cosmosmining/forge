# Static timing / power / area report used for loop feedback.
# Environment:
#   STA_MODE   prelayout | postroute
#   STA_LIB    liberty file
#   STA_DB     OpenDB file (1_synth.odb for prelayout, 6_final.odb for postroute)
#   STA_SDC    SDC file
#   STA_SPEF   SPEF from OpenRCX (postroute only)
#   STA_PATHS  number of worst paths per path group to dump as JSON
# Prelayout = the synthesized netlist with no placement and no wires: ideal clocks,
# zero wire capacitance/resistance. Postroute = the routed design, propagated
# clocks after CTS, parasitics extracted by OpenRCX from the detailed routing.

read_liberty $::env(STA_LIB)
read_db $::env(STA_DB)
read_sdc $::env(STA_SDC)
if { $::env(STA_MODE) == "postroute" } {
  set_propagated_clock [all_clocks]
  read_spef $::env(STA_SPEF)
}

puts "@@WNS_SETUP [sta::format_time [sta::worst_slack_cmd max] 6]"
puts "@@TNS_SETUP [sta::format_time [sta::total_negative_slack_cmd max] 6]"
puts "@@WNS_HOLD [sta::format_time [sta::worst_slack_cmd min] 6]"
puts "@@TNS_HOLD [sta::format_time [sta::total_negative_slack_cmd min] 6]"

# count failing setup endpoints
set n_viol 0
foreach pin [sta::endpoints] {
  set s [get_property $pin slack_max]
  if { $s < 0 } { incr n_viol }
}
puts "@@SETUP_VIOLATING_ENDPOINTS $n_viol"
puts "@@ENDPOINTS [llength [sta::endpoints]]"

puts "@@BEGIN_PATHS"
report_checks -path_delay max -group_path_count $::env(STA_PATHS) -endpoint_path_count 1 \
  -fields {input_pins slew cap fanout} -digits 4 -format json
puts "@@END_PATHS"

puts "@@BEGIN_HOLD_PATH"
report_checks -path_delay min -group_path_count 1 -endpoint_path_count 1 -digits 4 -format json
puts "@@END_HOLD_PATH"

if { $::env(STA_MODE) == "postroute" } {
  puts "@@BEGIN_CLKLAT"
  report_clock_latency -clock core_clock -digits 4
  puts "@@END_CLKLAT"
}

puts "@@BEGIN_POWER"
report_power -digits 6
puts "@@END_POWER"

puts "@@BEGIN_AREA"
report_design_area
puts "@@END_AREA"

# nets with fanout >= 8 (driver, fanout); used to annotate path stages
puts "@@BEGIN_FANOUT"
foreach net [get_nets -hierarchical *] {
  set loads [get_pins -quiet -of_objects $net -filter "direction==input"]
  set f [llength $loads]
  if { $f >= 8 } {
    puts "[get_full_name $net] $f"
  }
}
puts "@@END_FANOUT"

set ncells 0
set nseq 0
foreach inst [get_cells -hierarchical *] {
  incr ncells
  # nangate45 sequential cells: DFF*, SDFF*, DLH*, DLL*
  if { [regexp {^(S?DFF|DLH|DLL)} [get_property $inst ref_name]] } { incr nseq }
}
puts "@@CELLS $ncells"
puts "@@SEQ_CELLS $nseq"
