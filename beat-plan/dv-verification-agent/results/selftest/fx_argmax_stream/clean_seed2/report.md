# DV report: fx_argmax_stream (fx_argmax_stream)

**Verdict: PASS**  (seed 2)

Stimulus: 2234 input beats -> 244 golden output beats; sources {'corner_packets': 44, 'random_uniform_packets': 78, 'random_small_packets': 54, 'random_repeat_packets': 31, 'random_corner_packets': 37}; idle cycles 1929; stall cycles 4492

| check | status | detail |
|---|---|---|
| lint | pass | errors 0, risk 0, style 0, waived 0 |
| structural | pass | errors 0, risk 0, style 0, waived 0 |
| sim iverilog | pass | beats 244, mismatched 0, X 0, missing 0, extra 0, 0.05 s |
| sim verilator | pass | beats 244, mismatched 0, X 0, missing 0, extra 0, 4.53 s |

| number | value | kind | source |
|---|---|---|---|
| golden model line coverage | 100.0% | measured | sys.settrace over golden model |
| iverilog: output beats bit-exact | 244 of 244 | measured | run_iverilog/iverilog_out.txt |
| verilator: output beats bit-exact | 244 of 244 | measured | run_verilator/verilator_out.txt |
| DUT line coverage | 100.0% (11/11 points) | measured | verilator coverage.dat |
| DUT toggle coverage | 98.2% (163/166 points) | measured | verilator coverage.dat |

