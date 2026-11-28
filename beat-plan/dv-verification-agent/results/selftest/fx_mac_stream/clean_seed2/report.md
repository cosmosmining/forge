# DV report: fx_mac_stream (fx_mac_stream)

**Verdict: PASS**  (seed 2)

Stimulus: 2556 input beats -> 288 golden output beats; sources {'corner_packets': 88, 'random_corner_packets': 50, 'random_repeat_packets': 22, 'random_uniform_packets': 74, 'random_small_packets': 54}; idle cycles 2201; stall cycles 5080

| check | status | detail |
|---|---|---|
| lint | pass | errors 0, risk 0, style 0, waived 0 |
| structural | pass | errors 0, risk 0, style 0, waived 0 |
| sim iverilog | pass | beats 288, mismatched 0, X 0, missing 0, extra 0, 0.06 s |
| sim verilator | pass | beats 288, mismatched 0, X 0, missing 0, extra 0, 4.56 s |

| number | value | kind | source |
|---|---|---|---|
| golden model line coverage | 100.0% | measured | sys.settrace over golden model |
| iverilog: output beats bit-exact | 288 of 288 | measured | run_iverilog/iverilog_out.txt |
| verilator: output beats bit-exact | 288 of 288 | measured | run_verilator/verilator_out.txt |
| DUT line coverage | 100.0% (9/9 points) | measured | verilator coverage.dat |
| DUT toggle coverage | 99.6% (273/274 points) | measured | verilator coverage.dat |

