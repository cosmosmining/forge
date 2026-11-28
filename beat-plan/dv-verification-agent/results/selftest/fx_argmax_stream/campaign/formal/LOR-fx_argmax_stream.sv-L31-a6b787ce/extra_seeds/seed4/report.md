# DV report: fx_argmax_stream (fx_argmax_stream)

**Verdict: PASS**  (seed 4)

Stimulus: 2173 input beats -> 244 golden output beats; sources {'corner_packets': 44, 'random_small_packets': 36, 'random_repeat_packets': 29, 'random_corner_packets': 53, 'random_uniform_packets': 82}; idle cycles 1856; stall cycles 4504

| check | status | detail |
|---|---|---|
| sim iverilog | pass | beats 244, mismatched 0, X 0, missing 0, extra 0, 0.06 s |

| number | value | kind | source |
|---|---|---|---|
| iverilog: output beats bit-exact | 244 of 244 | measured | run_iverilog/iverilog_out.txt |

