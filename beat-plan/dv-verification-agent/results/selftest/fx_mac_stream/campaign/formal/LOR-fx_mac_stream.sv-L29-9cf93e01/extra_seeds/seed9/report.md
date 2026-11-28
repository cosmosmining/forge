# DV report: fx_mac_stream (fx_mac_stream)

**Verdict: PASS**  (seed 9)

Stimulus: 2577 input beats -> 288 golden output beats; sources {'corner_packets': 88, 'random_corner_packets': 51, 'random_small_packets': 43, 'random_uniform_packets': 79, 'random_repeat_packets': 27}; idle cycles 2203; stall cycles 5072

| check | status | detail |
|---|---|---|
| sim iverilog | pass | beats 288, mismatched 0, X 0, missing 0, extra 0, 0.08 s |

| number | value | kind | source |
|---|---|---|---|
| iverilog: output beats bit-exact | 288 of 288 | measured | run_iverilog/iverilog_out.txt |

