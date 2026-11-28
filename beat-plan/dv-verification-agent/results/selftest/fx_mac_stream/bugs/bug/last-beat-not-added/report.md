# DV report: fx_mac_stream (fx_mac_stream)

**Verdict: FAIL**  (seed 1)

Reasons:
- iverilog: 267 of 288 output beats differ from the golden model
- verilator: 267 of 288 output beats differ from the golden model

Stimulus: 2536 input beats -> 288 golden output beats; sources {'corner_packets': 88, 'random_uniform_packets': 81, 'random_small_packets': 44, 'random_corner_packets': 51, 'random_repeat_packets': 24}; idle cycles 2272; stall cycles 5095

| check | status | detail |
|---|---|---|
| lint | pass | errors 0, risk 0, style 0, waived 0 |
| structural | pass | errors 0, risk 0, style 0, waived 0 |
| sim iverilog | fail | beats 288, mismatched 267, X 0, missing 0, extra 0, 0.08 s |
| sim verilator | fail | beats 288, mismatched 267, X 0, missing 0, extra 0, 8.07 s |

| number | value | kind | source |
|---|---|---|---|
| golden model line coverage | 100.0% | measured | sys.settrace over golden model |
| iverilog: output beats bit-exact | 21 of 288 | measured | run_iverilog/iverilog_out.txt |
| verilator: output beats bit-exact | 21 of 288 | measured | run_verilator/verilator_out.txt |

First mismatches (iverilog):
- beat 0 port acc_out: expected 12288, got 0x00000000 (xor 0x3000) - output is zero: not updated, cleared too early, or wrong select
- beat 1 port acc_out: expected 22272, got 0x00005200 (xor 0x500) - value differs: check the datapath against the golden model
- beat 2 port acc_out: expected -13589, got 0x00000000 (xor 0xffffcaeb) - output is zero: not updated, cleared too early, or wrong select
- beat 3 port acc_out: expected -5207, got 0xffffb713 (xor 0x5cba) - value differs: check the datapath against the golden model
- beat 4 port acc_out: expected -6278, got 0x00000000 (xor 0xffffe77a) - output is zero: not updated, cleared too early, or wrong select

First mismatches (verilator):
- beat 0 port acc_out: expected 12288, got 0x00000000 (xor 0x3000) - output is zero: not updated, cleared too early, or wrong select
- beat 1 port acc_out: expected 22272, got 0x00005200 (xor 0x500) - value differs: check the datapath against the golden model
- beat 2 port acc_out: expected -13589, got 0x00000000 (xor 0xffffcaeb) - output is zero: not updated, cleared too early, or wrong select
- beat 3 port acc_out: expected -5207, got 0xffffb713 (xor 0x5cba) - value differs: check the datapath against the golden model
- beat 4 port acc_out: expected -6278, got 0x00000000 (xor 0xffffe77a) - output is zero: not updated, cleared too early, or wrong select

