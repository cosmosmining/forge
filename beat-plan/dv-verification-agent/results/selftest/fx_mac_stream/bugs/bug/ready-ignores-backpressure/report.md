# DV report: fx_mac_stream (fx_mac_stream)

**Verdict: FAIL**  (seed 1)

Reasons:
- iverilog: 242 of 288 output beats differ from the golden model
- iverilog: 43 expected output beats never appeared
- iverilog: testbench cycle timeout
- iverilog: output protocol broken in 43 cycles (out_valid dropped or data changed before out_ready)
- verilator: 242 of 288 output beats differ from the golden model
- verilator: 43 expected output beats never appeared
- verilator: testbench cycle timeout
- verilator: output protocol broken in 43 cycles (out_valid dropped or data changed before out_ready)

Stimulus: 2536 input beats -> 288 golden output beats; sources {'corner_packets': 88, 'random_uniform_packets': 81, 'random_small_packets': 44, 'random_corner_packets': 51, 'random_repeat_packets': 24}; idle cycles 2272; stall cycles 5095

| check | status | detail |
|---|---|---|
| lint | pass | errors 0, risk 0, style 0, waived 0 |
| structural | pass | errors 0, risk 0, style 0, waived 0 |
| sim iverilog | fail | beats 288, mismatched 242, X 0, missing 43, extra 0, 0.85 s |
| sim verilator | fail | beats 288, mismatched 242, X 0, missing 43, extra 0, 8.21 s |

| number | value | kind | source |
|---|---|---|---|
| golden model line coverage | 100.0% | measured | sys.settrace over golden model |
| iverilog: output beats bit-exact | 3 of 288 | measured | run_iverilog/iverilog_out.txt |
| verilator: output beats bit-exact | 3 of 288 | measured | run_verilator/verilator_out.txt |

First mismatches (iverilog):
- beat 3 port acc_out: expected -5207, got 0xffffe77a (xor 0xcd3) - value differs: check the datapath against the golden model
- beat 4 port acc_out: expected -6278, got 0xffffff80 (xor 0x18fa) - value differs: check the datapath against the golden model
- beat 5 port acc_out: expected -9460, got 0x00005100 (xor 0xffff8a0c) - value differs: check the datapath against the golden model
- beat 6 port acc_out: expected -128, got 0xffffffc1 (xor 0x41) - only low bits differ: rounding, shift amount or truncation
- beat 7 port acc_out: expected 20736, got 0x00000da0 (xor 0x5ca0) - value differs: check the datapath against the golden model

First mismatches (verilator):
- beat 3 port acc_out: expected -5207, got 0xffffe77a (xor 0xcd3) - value differs: check the datapath against the golden model
- beat 4 port acc_out: expected -6278, got 0xffffff80 (xor 0x18fa) - value differs: check the datapath against the golden model
- beat 5 port acc_out: expected -9460, got 0x00005100 (xor 0xffff8a0c) - value differs: check the datapath against the golden model
- beat 6 port acc_out: expected -128, got 0xffffffc1 (xor 0x41) - only low bits differ: rounding, shift amount or truncation
- beat 7 port acc_out: expected 20736, got 0x00000da0 (xor 0x5ca0) - value differs: check the datapath against the golden model

