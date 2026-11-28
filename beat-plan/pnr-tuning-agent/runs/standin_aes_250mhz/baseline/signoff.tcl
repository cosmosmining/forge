# pnr_agent sign-off (OpenSTA, golden SDC only) design=standin_aes_250mhz
source {/home/user/forge/beat-plan/pnr-tuning-agent/designs/openroad_test_sdc_helpers.tcl}
read_liberty {/nix/store/sp1shfcy9livvw7zskwd4wqz9nz3l92z-source/test/Nangate45/Nangate45_slow.lib}
read_verilog {/tmp/claude-0/-home-user-forge/5ce94ace-2cb9-5c7a-a28a-46f486100577/scratchpad/agent_work_aes/standin_aes_250mhz/flow/cache/drt/fda5a0a52f7d2b2a/final.v}
link_design aes_cipher_top
read_sdc {/home/user/forge/beat-plan/pnr-tuning-agent/designs/standin_aes_250mhz.sdc}
set_propagated_clock [all_clocks]
read_spef {/tmp/claude-0/-home-user-forge/5ce94ace-2cb9-5c7a-a28a-46f486100577/scratchpad/agent_work_aes/standin_aes_250mhz/flow/cache/drt/fda5a0a52f7d2b2a/final.spef}
foreach clk [all_clocks] { puts "PA_CLOCK [get_name $clk] [get_property $clk period]" }
puts "PA_WNS_MAX [sta::worst_slack -max]"
puts "PA_WNS_MIN [sta::worst_slack -min]"
puts "PA_TNS_MAX [sta::total_negative_slack -max]"
puts "PA_TNS_MIN [sta::total_negative_slack -min]"
puts "PA_SKEW_SETUP [sta::worst_clock_skew -setup]"
report_checks -path_delay max -format json -digits 5 -group_path_count 10 -endpoint_path_count 1 -fields {slew capacitance fanout input_pin net} > {/tmp/claude-0/-home-user-forge/5ce94ace-2cb9-5c7a-a28a-46f486100577/scratchpad/agent_work_aes/standin_aes_250mhz/flow/cache/drt/fda5a0a52f7d2b2a/signoff/paths_max.json}
report_checks -path_delay min -format json -digits 5 -group_path_count 5 -endpoint_path_count 1 -fields {slew capacitance fanout input_pin net} > {/tmp/claude-0/-home-user-forge/5ce94ace-2cb9-5c7a-a28a-46f486100577/scratchpad/agent_work_aes/standin_aes_250mhz/flow/cache/drt/fda5a0a52f7d2b2a/signoff/paths_min.json}
report_checks -path_delay max -format end -slack_max 0 -group_path_count 1000000 -digits 5 > {/tmp/claude-0/-home-user-forge/5ce94ace-2cb9-5c7a-a28a-46f486100577/scratchpad/agent_work_aes/standin_aes_250mhz/flow/cache/drt/fda5a0a52f7d2b2a/signoff/violators_max.rpt}
report_checks -path_delay min -format end -slack_max 0 -group_path_count 1000000 -digits 5 > {/tmp/claude-0/-home-user-forge/5ce94ace-2cb9-5c7a-a28a-46f486100577/scratchpad/agent_work_aes/standin_aes_250mhz/flow/cache/drt/fda5a0a52f7d2b2a/signoff/violators_min.rpt}
report_checks -path_delay max -format full_clock_expanded -digits 4 -group_path_count 10 -endpoint_path_count 1 -fields {slew capacitance fanout input_pin net} > {/tmp/claude-0/-home-user-forge/5ce94ace-2cb9-5c7a-a28a-46f486100577/scratchpad/agent_work_aes/standin_aes_250mhz/flow/cache/drt/fda5a0a52f7d2b2a/signoff/top_paths_max.rpt}
report_check_types -max_slew -max_capacitance -max_fanout -violators > {/tmp/claude-0/-home-user-forge/5ce94ace-2cb9-5c7a-a28a-46f486100577/scratchpad/agent_work_aes/standin_aes_250mhz/flow/cache/drt/fda5a0a52f7d2b2a/signoff/drv.rpt}
report_power > {/tmp/claude-0/-home-user-forge/5ce94ace-2cb9-5c7a-a28a-46f486100577/scratchpad/agent_work_aes/standin_aes_250mhz/flow/cache/drt/fda5a0a52f7d2b2a/signoff/power.rpt}
