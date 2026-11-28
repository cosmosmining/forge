# fo4.tcl -- FO4 inverter delay of ASAP7 RVT INVx1 (MODELLED: predictive PDK, NLDM).
# A chain of INVx1 stages, each driving four INVx1 inputs (one continues the chain,
# three are loads). The FO4 delay is the average per-stage delay over the middle
# stages, so input slews are those of a real FO4 chain. Env: STA_LIBS.
suppress_msg 1212
foreach lib $::env(STA_LIBS) { read_liberty $lib }
read_verilog [file join [file dirname [info script]] fo4_chain.v]
link_design fo4_chain
create_clock -name vclk -period 1000
set_input_delay 0 -clock vclk [get_ports in]
set_output_delay 0 -clock vclk [get_ports out]
set_input_transition 20 [get_ports in]

# Arrival at the output of stages s1..s6 along the worst (max) path.
set pe [lindex [find_timing_paths -path_delay max -from [get_ports in] -to [get_ports out]] 0]
set arr {}
foreach pt [get_property $pe points] {
  set pin [get_full_name [get_property $pt pin]]
  if {[regexp {^s([0-9])/Y$} $pin -> k]} { set arr_k($k) [get_property $pt arrival] }
}
# stages 2..5 are away from both ends of the chain
set d [expr {($arr_k(5) - $arr_k(1)) / 4.0}]
puts [format "FO4 INVx1_ASAP7_75t_R per-stage delay = %.2f ps (average of stages 2-5, max path)" $d]
puts [format "FO4 period_in_FO4_at_3GHz = %.1f" [expr {333.333 / $d}]]
exit
