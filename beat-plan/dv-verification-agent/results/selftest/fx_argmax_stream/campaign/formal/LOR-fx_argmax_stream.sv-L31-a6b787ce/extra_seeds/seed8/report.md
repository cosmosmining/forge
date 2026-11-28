# DV report: fx_argmax_stream (fx_argmax_stream)

**Verdict: PASS**  (seed 8)

Stimulus: 2139 input beats -> 244 golden output beats; sources {'corner_packets': 44, 'random_repeat_packets': 28, 'random_uniform_packets': 85, 'random_corner_packets': 49, 'random_small_packets': 38}; idle cycles 1742; stall cycles 4219

| check | status | detail |
|---|---|---|
| sim iverilog | pass | beats 244, mismatched 0, X 0, missing 0, extra 0, 0.05 s |

| number | value | kind | source |
|---|---|---|---|
| iverilog: output beats bit-exact | 244 of 244 | measured | run_iverilog/iverilog_out.txt |

