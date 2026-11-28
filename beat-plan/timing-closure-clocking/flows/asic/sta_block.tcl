# sta_block.tcl -- OpenSTA run for one synthesized block. MODELLED ONLY (ASAP7).
# Environment: STA_LIBS (space-separated .lib), STA_NETLIST, STA_TOP, STA_CLOCKS,
# STA_PERIOD, STA_UNCERTAINTY, STA_SDC, STA_OUT (prefix for reports).
# STA-1212 "timing group from output port": intentional CON->SN arcs of the ASAP7
# mirror adders (FAx1, HAxp5); ORFS suppresses it too (asap7/liberty_suppressions.tcl).
suppress_msg 1212
foreach lib $::env(STA_LIBS) { read_liberty $lib }
read_verilog $::env(STA_NETLIST)
link_design $::env(STA_TOP)

set PERIOD      $::env(STA_PERIOD)
set CLOCKS      $::env(STA_CLOCKS)
set UNCERTAINTY $::env(STA_UNCERTAINTY)
source $::env(STA_SDC)

set out $::env(STA_OUT)
set f [open "${out}.summary" w]

# Every flop must be clocked and every register endpoint constrained.
set unclk 0
foreach pin [get_pins -hierarchical */CLK] {
  if {[llength [get_property $pin clocks]] == 0} { incr unclk }
}
puts $f "unclocked_flop_clock_pins $unclk"

puts $f "tns_ps [format %.2f [sta::total_negative_slack_cmd max]]"

# Worst path in detail, and the per-path summary used by the ledger.
report_checks -path_delay max -group_path_count 1 -fields {slew cap fanout} -digits 2 > "${out}.worst_path.rpt"
report_checks -path_delay max -group_path_count 5 -endpoint_path_count 1 -format end -digits 2 > "${out}.endpoints.rpt"

# One worst path per path group (each clock, plus the CDC max_delay group).
set paths [find_timing_paths -path_delay max -group_path_count 1 -sort_by_slack]
set ws 1e9
foreach pe $paths {
  set pts [get_property $pe points]
  set cells {}
  foreach pt $pts {
    set pname [get_full_name [get_property $pt pin]]
    set slash [string last "/" $pname]
    if {$slash > 0} {
      set inst [string range $pname 0 [expr {$slash - 1}]]
      if {[lsearch -exact $cells $inst] < 0} { lappend cells $inst }
    }
  }
  set sclk [get_property $pe startpoint_clock]
  set eclk [get_property $pe endpoint_clock]
  set sname [expr {$sclk eq "" ? "-" : [get_name $sclk]}]
  set ename [expr {$eclk eq "" ? "-" : [get_name $eclk]}]
  set kind [expr {$sname ne $ename ? "cdc_max_delay" : "reg2reg"}]
  set slk [get_property $pe slack]
  if {$slk < $ws} { set ws $slk }
  puts $f "path kind=$kind launch=$sname capture=$ename slack_ps=[format %.2f $slk] arrival_ps=[format %.2f [get_property [lindex $pts end] arrival]] cells=[llength $cells] start=[get_full_name [get_property $pe startpoint]] end=[get_full_name [get_property $pe endpoint]]"
}
puts $f "worst_slack_ps [format %.2f $ws]"
close $f
exit
