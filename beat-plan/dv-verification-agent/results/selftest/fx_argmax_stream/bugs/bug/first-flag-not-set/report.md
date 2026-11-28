# DV report: fx_argmax_stream (fx_argmax_stream)

**Verdict: FAIL**  (seed 1)

Reasons:
- iverilog: 199 of 244 output beats differ from the golden model
- verilator: 199 of 244 output beats differ from the golden model

Stimulus: 2167 input beats -> 244 golden output beats; sources {'corner_packets': 44, 'random_repeat_packets': 21, 'random_uniform_packets': 81, 'random_small_packets': 55, 'random_corner_packets': 43}; idle cycles 1920; stall cycles 4416

| check | status | detail |
|---|---|---|
| lint | pass | errors 0, risk 0, style 0, waived 0 |
| structural | pass | errors 0, risk 0, style 0, waived 0 |
| sim iverilog | fail | beats 244, mismatched 199, X 0, missing 0, extra 0, 0.04 s |
| sim verilator | fail | beats 244, mismatched 199, X 0, missing 0, extra 0, 7.99 s |

| number | value | kind | source |
|---|---|---|---|
| golden model line coverage | 100.0% | measured | sys.settrace over golden model |
| iverilog: output beats bit-exact | 45 of 244 | measured | run_iverilog/iverilog_out.txt |
| verilator: output beats bit-exact | 45 of 244 | measured | run_verilator/verilator_out.txt |

First mismatches (iverilog):
- beat 44 port max_val: expected 9, got 0x7fff (xor 0x7ff6) - RTL saturated but golden did not: clamp bound or compare wrong
- beat 45 port idx: expected 1, got 0x00 (xor 0x1) - output is zero: not updated, cleared too early, or wrong select
- beat 45 port max_val: expected 30932, got 0x7fff (xor 0x72b) - RTL saturated but golden did not: clamp bound or compare wrong
- beat 46 port max_val: expected -2, got 0x7fff (xor 0x8001) - RTL saturated but golden did not: clamp bound or compare wrong
- beat 47 port max_val: expected 29992, got 0x7fff (xor 0xad7) - RTL saturated but golden did not: clamp bound or compare wrong

First mismatches (verilator):
- beat 44 port max_val: expected 9, got 0x7fff (xor 0x7ff6) - RTL saturated but golden did not: clamp bound or compare wrong
- beat 45 port idx: expected 1, got 0x00 (xor 0x1) - output is zero: not updated, cleared too early, or wrong select
- beat 45 port max_val: expected 30932, got 0x7fff (xor 0x72b) - RTL saturated but golden did not: clamp bound or compare wrong
- beat 46 port max_val: expected -2, got 0x7fff (xor 0x8001) - RTL saturated but golden did not: clamp bound or compare wrong
- beat 47 port max_val: expected 29992, got 0x7fff (xor 0xad7) - RTL saturated but golden did not: clamp bound or compare wrong

