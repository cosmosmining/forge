# DV report: fx_mac_stream (fx_mac_stream)

**Verdict: PASS**  (seed 1)

Stimulus: 2536 input beats -> 288 golden output beats; sources {'corner_packets': 88, 'random_uniform_packets': 81, 'random_small_packets': 44, 'random_corner_packets': 51, 'random_repeat_packets': 24}; idle cycles 2272; stall cycles 5095

| check | status | detail |
|---|---|---|
| lint | pass | errors 0, risk 0, style 0, waived 0 |
| structural | pass | errors 0, risk 0, style 0, waived 0 |
| sim iverilog | pass | beats 288, mismatched 0, X 0, missing 0, extra 0, 0.07 s |
| sim verilator | pass | beats 288, mismatched 0, X 0, missing 0, extra 0, 4.7 s |

| number | value | kind | source |
|---|---|---|---|
| golden model line coverage | 100.0% | measured | sys.settrace over golden model |
| iverilog: output beats bit-exact | 288 of 288 | measured | run_iverilog/iverilog_out.txt |
| verilator: output beats bit-exact | 288 of 288 | measured | run_verilator/verilator_out.txt |
| DUT line coverage | 100.0% (9/9 points) | measured | verilator coverage.dat |
| DUT toggle coverage | 99.6% (273/274 points) | measured | verilator coverage.dat |

