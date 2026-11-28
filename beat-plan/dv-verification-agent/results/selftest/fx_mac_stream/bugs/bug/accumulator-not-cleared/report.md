# DV report: fx_mac_stream (fx_mac_stream)

**Verdict: FAIL**  (seed 1)

Reasons:
- iverilog: 286 of 288 output beats differ from the golden model
- verilator: 286 of 288 output beats differ from the golden model

Stimulus: 2536 input beats -> 288 golden output beats; sources {'corner_packets': 88, 'random_uniform_packets': 81, 'random_small_packets': 44, 'random_corner_packets': 51, 'random_repeat_packets': 24}; idle cycles 2272; stall cycles 5095

| check | status | detail |
|---|---|---|
| lint | pass | errors 0, risk 0, style 0, waived 0 |
| structural | pass | errors 0, risk 0, style 0, waived 0 |
| sim iverilog | fail | beats 288, mismatched 286, X 0, missing 0, extra 0, 0.06 s |
| sim verilator | fail | beats 288, mismatched 286, X 0, missing 0, extra 0, 8.21 s |

| number | value | kind | source |
|---|---|---|---|
| golden model line coverage | 100.0% | measured | sys.settrace over golden model |
| iverilog: output beats bit-exact | 2 of 288 | measured | run_iverilog/iverilog_out.txt |
| verilator: output beats bit-exact | 2 of 288 | measured | run_verilator/verilator_out.txt |

First mismatches (iverilog):
- beat 2 port acc_out: expected -13589, got 0x00001ceb (xor 0xffffd600) - value differs: check the datapath against the golden model
- beat 3 port acc_out: expected -5207, got 0x00003da9 (xor 0xffffd600) - value differs: check the datapath against the golden model
- beat 4 port acc_out: expected -6278, got 0xfffff08d (xor 0x17f7) - value differs: check the datapath against the golden model
- beat 5 port acc_out: expected -9460, got 0xffffe41f (xor 0x3f13) - value differs: check the datapath against the golden model
- beat 6 port acc_out: expected -128, got 0xffffd787 (xor 0x2807) - value differs: check the datapath against the golden model

First mismatches (verilator):
- beat 2 port acc_out: expected -13589, got 0x00001ceb (xor 0xffffd600) - value differs: check the datapath against the golden model
- beat 3 port acc_out: expected -5207, got 0x00003da9 (xor 0xffffd600) - value differs: check the datapath against the golden model
- beat 4 port acc_out: expected -6278, got 0xfffff08d (xor 0x17f7) - value differs: check the datapath against the golden model
- beat 5 port acc_out: expected -9460, got 0xffffe41f (xor 0x3f13) - value differs: check the datapath against the golden model
- beat 6 port acc_out: expected -128, got 0xffffd787 (xor 0x2807) - value differs: check the datapath against the golden model

