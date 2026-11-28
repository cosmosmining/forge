# DV report: fx_argmax_stream (fx_argmax_stream)

**Verdict: FAIL**  (seed 1)

Reasons:
- iverilog: 138 of 244 output beats differ from the golden model
- verilator: 138 of 244 output beats differ from the golden model

Stimulus: 2167 input beats -> 244 golden output beats; sources {'corner_packets': 44, 'random_repeat_packets': 21, 'random_uniform_packets': 81, 'random_small_packets': 55, 'random_corner_packets': 43}; idle cycles 1920; stall cycles 4416

| check | status | detail |
|---|---|---|
| lint | pass | errors 0, risk 0, style 0, waived 0 |
| structural | pass | errors 0, risk 0, style 0, waived 0 |
| sim iverilog | fail | beats 244, mismatched 138, X 0, missing 0, extra 0, 0.05 s |
| sim verilator | fail | beats 244, mismatched 138, X 0, missing 0, extra 0, 8.14 s |

| number | value | kind | source |
|---|---|---|---|
| golden model line coverage | 100.0% | measured | sys.settrace over golden model |
| iverilog: output beats bit-exact | 106 of 244 | measured | run_iverilog/iverilog_out.txt |
| verilator: output beats bit-exact | 106 of 244 | measured | run_verilator/verilator_out.txt |

First mismatches (iverilog):
- beat 45 port idx: expected 1, got 0x00 (xor 0x1) - output is zero: not updated, cleared too early, or wrong select
- beat 45 port max_val: expected 30932, got 0xf791 (xor 0x8f45) - value differs: check the datapath against the golden model
- beat 47 port idx: expected 0, got 0x01 (xor 0x1) - off by one: rounding constant, rounding direction or truncation
- beat 47 port max_val: expected 29992, got 0xf33b (xor 0x8613) - value differs: check the datapath against the golden model
- beat 48 port idx: expected 9, got 0x07 (xor 0xe) - value differs: check the datapath against the golden model

First mismatches (verilator):
- beat 45 port idx: expected 1, got 0x00 (xor 0x1) - output is zero: not updated, cleared too early, or wrong select
- beat 45 port max_val: expected 30932, got 0xf791 (xor 0x8f45) - value differs: check the datapath against the golden model
- beat 47 port idx: expected 0, got 0x01 (xor 0x1) - off by one: rounding constant, rounding direction or truncation
- beat 47 port max_val: expected 29992, got 0xf33b (xor 0x8613) - value differs: check the datapath against the golden model
- beat 48 port idx: expected 9, got 0x07 (xor 0xe) - value differs: check the datapath against the golden model

