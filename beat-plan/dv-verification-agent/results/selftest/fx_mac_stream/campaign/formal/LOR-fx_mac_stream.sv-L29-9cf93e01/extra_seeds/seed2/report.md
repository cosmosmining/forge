# DV report: fx_mac_stream (fx_mac_stream)

**Verdict: PASS**  (seed 2)

Stimulus: 2556 input beats -> 288 golden output beats; sources {'corner_packets': 88, 'random_corner_packets': 50, 'random_repeat_packets': 22, 'random_uniform_packets': 74, 'random_small_packets': 54}; idle cycles 2201; stall cycles 5080

| check | status | detail |
|---|---|---|
| sim iverilog | pass | beats 288, mismatched 0, X 0, missing 0, extra 0, 0.1 s |

| number | value | kind | source |
|---|---|---|---|
| iverilog: output beats bit-exact | 288 of 288 | measured | run_iverilog/iverilog_out.txt |

