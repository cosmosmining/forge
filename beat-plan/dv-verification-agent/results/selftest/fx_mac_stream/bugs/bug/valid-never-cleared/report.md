# DV report: fx_mac_stream (fx_mac_stream)

**Verdict: FAIL**  (seed 1)

Reasons:
- iverilog: 287 of 288 output beats differ from the golden model
- iverilog: 25 extra output beats
- iverilog: DUT accepted 202 of 2536 input beats
- verilator: 287 of 288 output beats differ from the golden model
- verilator: 25 extra output beats
- verilator: DUT accepted 202 of 2536 input beats

Stimulus: 2536 input beats -> 288 golden output beats; sources {'corner_packets': 88, 'random_uniform_packets': 81, 'random_small_packets': 44, 'random_corner_packets': 51, 'random_repeat_packets': 24}; idle cycles 2272; stall cycles 5095

| check | status | detail |
|---|---|---|
| lint | pass | errors 0, risk 0, style 1, waived 0 |
| structural | pass | errors 0, risk 0, style 0, waived 0 |
| sim iverilog | fail | beats 288, mismatched 287, X 0, missing 0, extra 25, 0.03 s |
| sim verilator | fail | beats 288, mismatched 287, X 0, missing 0, extra 25, 8.29 s |

| number | value | kind | source |
|---|---|---|---|
| golden model line coverage | 100.0% | measured | sys.settrace over golden model |
| iverilog: output beats bit-exact | 1 of 288 | measured | run_iverilog/iverilog_out.txt |
| verilator: output beats bit-exact | 1 of 288 | measured | run_verilator/verilator_out.txt |

First mismatches (iverilog):
- beat 1 port acc_out: expected 22272, got 0x00003000 (xor 0x6700) - value differs: check the datapath against the golden model
- beat 2 port acc_out: expected -13589, got 0x00003000 (xor 0xfffffaeb) - value differs: check the datapath against the golden model
- beat 3 port acc_out: expected -5207, got 0x00003000 (xor 0xffffdba9) - value differs: check the datapath against the golden model
- beat 4 port acc_out: expected -6278, got 0x00003000 (xor 0xffffd77a) - value differs: check the datapath against the golden model
- beat 5 port acc_out: expected -9460, got 0x00003000 (xor 0xffffeb0c) - value differs: check the datapath against the golden model

First mismatches (verilator):
- beat 1 port acc_out: expected 22272, got 0x00003000 (xor 0x6700) - value differs: check the datapath against the golden model
- beat 2 port acc_out: expected -13589, got 0x00003000 (xor 0xfffffaeb) - value differs: check the datapath against the golden model
- beat 3 port acc_out: expected -5207, got 0x00003000 (xor 0xffffdba9) - value differs: check the datapath against the golden model
- beat 4 port acc_out: expected -6278, got 0x00003000 (xor 0xffffd77a) - value differs: check the datapath against the golden model
- beat 5 port acc_out: expected -9460, got 0x00003000 (xor 0xffffeb0c) - value differs: check the datapath against the golden model

