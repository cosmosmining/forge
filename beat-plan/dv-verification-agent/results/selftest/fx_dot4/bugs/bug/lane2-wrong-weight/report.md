# DV report: fx_dot4 (fx_dot4)

**Verdict: FAIL**  (seed 1)

Reasons:
- iverilog: 2796 of 4024 output beats differ from the golden model
- verilator: 2796 of 4024 output beats differ from the golden model

Stimulus: 4024 input beats -> 4024 golden output beats; sources {'directed': 0, 'formal_counterexample': 0, 'corner_sample': 1024, 'random_mix': 3000}; idle cycles 3621; stall cycles 0

| check | status | detail |
|---|---|---|
| lint | pass | errors 0, risk 0, style 1, waived 0 |
| structural | pass | errors 0, risk 0, style 0, waived 0 |
| sim iverilog | fail | beats 4024, mismatched 2796, X 0, missing 0, extra 0, 0.09 s |
| sim verilator | fail | beats 4024, mismatched 2796, X 0, missing 0, extra 0, 8.07 s |

| number | value | kind | source |
|---|---|---|---|
| golden model line coverage | 100.0% | measured | sys.settrace over golden model |
| iverilog: output beats bit-exact | 1228 of 4024 | measured | run_iverilog/iverilog_out.txt |
| verilator: output beats bit-exact | 1228 of 4024 | measured | run_verilator/verilator_out.txt |

First mismatches (iverilog):
- beat 1024 port y: expected 536883363, got 0x20002313 (xor 0x13b0) - value differs: check the datapath against the golden model
- beat 1025 port y: expected -1363248601, got 0xaebe5369 (xor 0x294e) - value differs: check the datapath against the golden model
- beat 1026 port y: expected -363, got 0xfffffe55 (xor 0xc0) - only low bits differ: rounding, shift amount or truncation
- beat 1027 port y: expected 560, got 0x00000178 (xor 0x348) - value differs: check the datapath against the golden model
- beat 1028 port y: expected 10274, got 0x000019a4 (xor 0x3186) - value differs: check the datapath against the golden model

First mismatches (verilator):
- beat 1024 port y: expected 536883363, got 0x20002313 (xor 0x13b0) - value differs: check the datapath against the golden model
- beat 1025 port y: expected -1363248601, got 0xaebe5369 (xor 0x294e) - value differs: check the datapath against the golden model
- beat 1026 port y: expected -363, got 0xfffffe55 (xor 0xc0) - only low bits differ: rounding, shift amount or truncation
- beat 1027 port y: expected 560, got 0x00000178 (xor 0x348) - value differs: check the datapath against the golden model
- beat 1028 port y: expected 10274, got 0x000019a4 (xor 0x3186) - value differs: check the datapath against the golden model

