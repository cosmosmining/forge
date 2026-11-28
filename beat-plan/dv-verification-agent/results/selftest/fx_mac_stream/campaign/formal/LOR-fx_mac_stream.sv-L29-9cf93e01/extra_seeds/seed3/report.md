# DV report: fx_mac_stream (fx_mac_stream)

**Verdict: PASS**  (seed 3)

Stimulus: 2580 input beats -> 288 golden output beats; sources {'corner_packets': 88, 'random_uniform_packets': 78, 'random_corner_packets': 43, 'random_small_packets': 55, 'random_repeat_packets': 24}; idle cycles 2326; stall cycles 5146

| check | status | detail |
|---|---|---|
| sim iverilog | pass | beats 288, mismatched 0, X 0, missing 0, extra 0, 0.08 s |

| number | value | kind | source |
|---|---|---|---|
| iverilog: output beats bit-exact | 288 of 288 | measured | run_iverilog/iverilog_out.txt |

