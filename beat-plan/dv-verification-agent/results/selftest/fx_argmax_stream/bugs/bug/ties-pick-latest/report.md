# DV report: fx_argmax_stream (fx_argmax_stream)

**Verdict: FAIL**  (seed 1)

Reasons:
- iverilog: 52 of 244 output beats differ from the golden model
- verilator: 52 of 244 output beats differ from the golden model

Stimulus: 2167 input beats -> 244 golden output beats; sources {'corner_packets': 44, 'random_repeat_packets': 21, 'random_uniform_packets': 81, 'random_small_packets': 55, 'random_corner_packets': 43}; idle cycles 1920; stall cycles 4416

| check | status | detail |
|---|---|---|
| lint | pass | errors 0, risk 0, style 0, waived 0 |
| structural | pass | errors 0, risk 0, style 0, waived 0 |
| sim iverilog | fail | beats 244, mismatched 52, X 0, missing 0, extra 0, 0.04 s |
| sim verilator | fail | beats 244, mismatched 52, X 0, missing 0, extra 0, 8.13 s |

| number | value | kind | source |
|---|---|---|---|
| golden model line coverage | 100.0% | measured | sys.settrace over golden model |
| iverilog: output beats bit-exact | 192 of 244 | measured | run_iverilog/iverilog_out.txt |
| verilator: output beats bit-exact | 192 of 244 | measured | run_verilator/verilator_out.txt |

First mismatches (iverilog):
- beat 1 port idx: expected 0, got 0x0f (xor 0xf) - value differs: check the datapath against the golden model
- beat 3 port idx: expected 0, got 0x0f (xor 0xf) - value differs: check the datapath against the golden model
- beat 5 port idx: expected 0, got 0x0f (xor 0xf) - value differs: check the datapath against the golden model
- beat 7 port idx: expected 0, got 0x0f (xor 0xf) - value differs: check the datapath against the golden model
- beat 9 port idx: expected 0, got 0x0f (xor 0xf) - value differs: check the datapath against the golden model

First mismatches (verilator):
- beat 1 port idx: expected 0, got 0x0f (xor 0xf) - value differs: check the datapath against the golden model
- beat 3 port idx: expected 0, got 0x0f (xor 0xf) - value differs: check the datapath against the golden model
- beat 5 port idx: expected 0, got 0x0f (xor 0xf) - value differs: check the datapath against the golden model
- beat 7 port idx: expected 0, got 0x0f (xor 0xf) - value differs: check the datapath against the golden model
- beat 9 port idx: expected 0, got 0x0f (xor 0xf) - value differs: check the datapath against the golden model

