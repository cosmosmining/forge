# DV report: fx_argmax_stream (fx_argmax_stream)

**Verdict: PASS**  (seed 7)

Stimulus: 2098 input beats -> 244 golden output beats; sources {'corner_packets': 44, 'random_uniform_packets': 74, 'random_corner_packets': 62, 'random_small_packets': 45, 'random_repeat_packets': 19}; idle cycles 1948; stall cycles 4484

| check | status | detail |
|---|---|---|
| sim iverilog | pass | beats 244, mismatched 0, X 0, missing 0, extra 0, 0.05 s |

| number | value | kind | source |
|---|---|---|---|
| iverilog: output beats bit-exact | 244 of 244 | measured | run_iverilog/iverilog_out.txt |

