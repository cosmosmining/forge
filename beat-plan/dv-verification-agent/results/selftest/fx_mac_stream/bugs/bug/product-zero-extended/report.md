# DV report: fx_mac_stream (fx_mac_stream)

**Verdict: FAIL**  (seed 1)

Reasons:
- iverilog: 225 of 288 output beats differ from the golden model
- verilator: 225 of 288 output beats differ from the golden model

Stimulus: 2536 input beats -> 288 golden output beats; sources {'corner_packets': 88, 'random_uniform_packets': 81, 'random_small_packets': 44, 'random_corner_packets': 51, 'random_repeat_packets': 24}; idle cycles 2272; stall cycles 5095

| check | status | detail |
|---|---|---|
| lint | pass | errors 0, risk 0, style 0, waived 0 |
| structural | pass | errors 0, risk 0, style 0, waived 0 |
| sim iverilog | fail | beats 288, mismatched 225, X 0, missing 0, extra 0, 0.06 s |
| sim verilator | fail | beats 288, mismatched 225, X 0, missing 0, extra 0, 8.12 s |

| number | value | kind | source |
|---|---|---|---|
| golden model line coverage | 100.0% | measured | sys.settrace over golden model |
| iverilog: output beats bit-exact | 63 of 288 | measured | run_iverilog/iverilog_out.txt |
| verilator: output beats bit-exact | 63 of 288 | measured | run_verilator/verilator_out.txt |

First mismatches (iverilog):
- beat 1 port acc_out: expected 22272, got 0x00065700 (xor 0x60000) - only high bits differ: sign extension, overflow width or carry
- beat 2 port acc_out: expected -13589, got 0x0000caeb (xor 0xffff0000) - only high bits differ: sign extension, overflow width or carry
- beat 3 port acc_out: expected -5207, got 0x0008eba9 (xor 0xfff70000) - only high bits differ: sign extension, overflow width or carry
- beat 4 port acc_out: expected -6278, got 0x0000e77a (xor 0xffff0000) - only high bits differ: sign extension, overflow width or carry
- beat 5 port acc_out: expected -9460, got 0x0006db0c (xor 0xfff90000) - only high bits differ: sign extension, overflow width or carry

First mismatches (verilator):
- beat 1 port acc_out: expected 22272, got 0x00065700 (xor 0x60000) - only high bits differ: sign extension, overflow width or carry
- beat 2 port acc_out: expected -13589, got 0x0000caeb (xor 0xffff0000) - only high bits differ: sign extension, overflow width or carry
- beat 3 port acc_out: expected -5207, got 0x0008eba9 (xor 0xfff70000) - only high bits differ: sign extension, overflow width or carry
- beat 4 port acc_out: expected -6278, got 0x0000e77a (xor 0xffff0000) - only high bits differ: sign extension, overflow width or carry
- beat 5 port acc_out: expected -9460, got 0x0006db0c (xor 0xfff90000) - only high bits differ: sign extension, overflow width or carry

