# DV report: fx_argmax_stream (fx_argmax_stream)

**Verdict: PASS**  (seed 3)

Stimulus: 2113 input beats -> 244 golden output beats; sources {'corner_packets': 44, 'random_small_packets': 39, 'random_corner_packets': 54, 'random_uniform_packets': 85, 'random_repeat_packets': 22}; idle cycles 1921; stall cycles 4249

| check | status | detail |
|---|---|---|
| lint | pass | errors 0, risk 0, style 0, waived 0 |
| structural | pass | errors 0, risk 0, style 0, waived 0 |
| sim iverilog | pass | beats 244, mismatched 0, X 0, missing 0, extra 0, 0.05 s |
| sim verilator | pass | beats 244, mismatched 0, X 0, missing 0, extra 0, 4.6 s |

| number | value | kind | source |
|---|---|---|---|
| golden model line coverage | 100.0% | measured | sys.settrace over golden model |
| iverilog: output beats bit-exact | 244 of 244 | measured | run_iverilog/iverilog_out.txt |
| verilator: output beats bit-exact | 244 of 244 | measured | run_verilator/verilator_out.txt |
| DUT line coverage | 100.0% (11/11 points) | measured | verilator coverage.dat |
| DUT toggle coverage | 87.3% (145/166 points) | measured | verilator coverage.dat |

