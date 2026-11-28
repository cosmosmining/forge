# Stand-in constraints: OpenROAD's test/aes_nangate45.sdc with only the period
# changed from 0.8109 ns to 4.0 ns (250 MHz, Build 6's target).
# I/O delays are 20% of the period (set_all_input_output_delays, OpenROAD helper).
create_clock [get_ports clk] -period 4.0
set_all_input_output_delays
