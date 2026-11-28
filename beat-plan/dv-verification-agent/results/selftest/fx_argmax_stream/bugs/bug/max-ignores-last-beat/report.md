# DV report: fx_argmax_stream (fx_argmax_stream)

**Verdict: FAIL**  (seed 1)

Reasons:
- iverilog: 70 of 244 output beats differ from the golden model
- verilator: 70 of 244 output beats differ from the golden model

Stimulus: 2167 input beats -> 244 golden output beats; sources {'corner_packets': 44, 'random_repeat_packets': 21, 'random_uniform_packets': 81, 'random_small_packets': 55, 'random_corner_packets': 43}; idle cycles 1920; stall cycles 4416

| check | status | detail |
|---|---|---|
| lint | pass | errors 0, risk 0, style 0, waived 0 |
| structural | pass | errors 0, risk 0, style 0, waived 0 |
| sim iverilog | fail | beats 244, mismatched 70, X 0, missing 0, extra 0, 0.05 s |
| sim verilator | fail | beats 244, mismatched 70, X 0, missing 0, extra 0, 8.31 s |

| number | value | kind | source |
|---|---|---|---|
| golden model line coverage | 100.0% | measured | sys.settrace over golden model |
| iverilog: output beats bit-exact | 174 of 244 | measured | run_iverilog/iverilog_out.txt |
| verilator: output beats bit-exact | 174 of 244 | measured | run_verilator/verilator_out.txt |

First mismatches (iverilog):
- beat 0 port max_val: expected -32768, got 0x0000 (xor 0x8000) - output is zero: not updated, cleared too early, or wrong select
- beat 2 port max_val: expected -32767, got 0x8000 (xor 0x1) - off by one: rounding constant, rounding direction or truncation
- beat 4 port max_val: expected -21846, got 0x8001 (xor 0x2aab) - value differs: check the datapath against the golden model
- beat 6 port max_val: expected -16384, got 0xaaaa (xor 0x6aaa) - value differs: check the datapath against the golden model
- beat 8 port max_val: expected -16383, got 0xc000 (xor 0x1) - off by one: rounding constant, rounding direction or truncation

First mismatches (verilator):
- beat 0 port max_val: expected -32768, got 0x0000 (xor 0x8000) - output is zero: not updated, cleared too early, or wrong select
- beat 2 port max_val: expected -32767, got 0x8000 (xor 0x1) - off by one: rounding constant, rounding direction or truncation
- beat 4 port max_val: expected -21846, got 0x8001 (xor 0x2aab) - value differs: check the datapath against the golden model
- beat 6 port max_val: expected -16384, got 0xaaaa (xor 0x6aaa) - value differs: check the datapath against the golden model
- beat 8 port max_val: expected -16383, got 0xc000 (xor 0x1) - off by one: rounding constant, rounding direction or truncation

