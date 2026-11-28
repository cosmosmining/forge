# DV report: fx_argmax_stream (fx_argmax_stream)

**Verdict: PASS**  (seed 2)

Stimulus: 2234 input beats -> 244 golden output beats; sources {'corner_packets': 44, 'random_uniform_packets': 78, 'random_small_packets': 54, 'random_repeat_packets': 31, 'random_corner_packets': 37}; idle cycles 1929; stall cycles 4492

| check | status | detail |
|---|---|---|
| sim iverilog | pass | beats 244, mismatched 0, X 0, missing 0, extra 0, 0.06 s |

| number | value | kind | source |
|---|---|---|---|
| iverilog: output beats bit-exact | 244 of 244 | measured | run_iverilog/iverilog_out.txt |

