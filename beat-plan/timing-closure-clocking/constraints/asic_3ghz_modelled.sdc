# asic_3ghz_modelled.sdc -- 3 GHz ASIC track. MODELLED ONLY (ASAP7 predictive PDK).
# Forge Feature 5 (timing-closure / clocking pack).
#
# This file is the template; flows/run_asic_modelled.sh fills in the clocks per block.
# Every number produced with it is labelled "modelled": ASAP7 is a predictive PDK,
# analysis is pre-layout (no wires, ideal clocks, no clock tree), at one corner.
# Nothing here is measured on silicon, and nothing here should be quoted as a chip result.
#
# Units: ps (ASAP7 liberty time_unit is 1ps).
#
# Variables expected from the caller (Tcl):
#   PERIOD        clock period in ps (333.333 for 3 GHz)
#   CLOCKS        list of clock port names; every clock gets PERIOD
#   UNCERTAINTY   setup uncertainty in ps (0 = raw slack; the budget is applied in
#                 docs/ASIC_3GHZ_MODELLED.md, slack(U) = slack(0) - U with ideal clocks)

foreach c $CLOCKS {
  create_clock -name $c -period $PERIOD [get_ports $c]
  set_clock_uncertainty -setup $UNCERTAINTY [get_clocks $c]
}

# Clock-domain crossings: no normal clock relationship between different clocks.
# Each crossing path is limited to one period of datapath delay (clock latency
# ignored). This is what keeps the bits of a Gray pointer arriving within one cycle of
# each other, and what lets a handshake's held data settle before its capture.
foreach a $CLOCKS {
  foreach b $CLOCKS {
    if {$a ne $b} {
      set_max_delay -ignore_clock_latency -from [get_clocks $a] -to [get_clocks $b] $PERIOD
    }
  }
}

# Block-level analysis: only register-to-register paths can fail timing closure here.
# Inputs and outputs are constrained by the integration, not by the block.
set_false_path -from [all_inputs -no_clocks]
set_false_path -to [all_outputs]
