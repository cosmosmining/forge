# DV report: fx_mac_stream (fx_mac_stream)

**Verdict: PASS**  (seed 5)

Stimulus: 2570 input beats -> 288 golden output beats; sources {'corner_packets': 88, 'random_uniform_packets': 85, 'random_corner_packets': 53, 'random_repeat_packets': 28, 'random_small_packets': 34}; idle cycles 2372; stall cycles 5185

| check | status | detail |
|---|---|---|
| sim iverilog | pass | beats 288, mismatched 0, X 0, missing 0, extra 0, 0.09 s |

| number | value | kind | source |
|---|---|---|---|
| iverilog: output beats bit-exact | 288 of 288 | measured | run_iverilog/iverilog_out.txt |

