# DV report: fx_argmax_stream (fx_argmax_stream)

**Verdict: PASS**  (seed 5)

Stimulus: 2089 input beats -> 244 golden output beats; sources {'corner_packets': 44, 'random_corner_packets': 57, 'random_uniform_packets': 74, 'random_small_packets': 46, 'random_repeat_packets': 23}; idle cycles 1921; stall cycles 4143

| check | status | detail |
|---|---|---|
| sim iverilog | pass | beats 244, mismatched 0, X 0, missing 0, extra 0, 0.05 s |

| number | value | kind | source |
|---|---|---|---|
| iverilog: output beats bit-exact | 244 of 244 | measured | run_iverilog/iverilog_out.txt |

