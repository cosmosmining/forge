# DV report: fx_argmax_stream (fx_argmax_stream)

**Verdict: PASS**  (seed 6)

Stimulus: 2200 input beats -> 244 golden output beats; sources {'corner_packets': 44, 'random_repeat_packets': 31, 'random_uniform_packets': 67, 'random_corner_packets': 58, 'random_small_packets': 44}; idle cycles 1823; stall cycles 4529

| check | status | detail |
|---|---|---|
| sim iverilog | pass | beats 244, mismatched 0, X 0, missing 0, extra 0, 0.06 s |

| number | value | kind | source |
|---|---|---|---|
| iverilog: output beats bit-exact | 244 of 244 | measured | run_iverilog/iverilog_out.txt |

