# Helper proc used by OpenROAD's test SDC files (gcd/aes/tinyRocket *_nangate45.sdc).
# Copied verbatim from OpenROAD test/flow_helpers.tcl
# (BSD-3-Clause, Copyright (c) 2019, The Regents of the University of California).
# It is part of the golden constraint definition: input/output delays = 20% of the period.
proc set_all_input_output_delays {{clk_period_factor .2}} {
  set clk [lindex [all_clocks] 0]
  set period [get_property $clk period]
  set delay [expr $period * $clk_period_factor]
  set_input_delay $delay -clock $clk [delete_from_list [all_inputs] [all_clocks]]
  set_output_delay $delay -clock $clk [delete_from_list [all_outputs] [all_clocks]]
}
