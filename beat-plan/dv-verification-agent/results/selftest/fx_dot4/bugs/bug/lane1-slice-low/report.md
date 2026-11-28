# DV report: fx_dot4 (fx_dot4)

**Verdict: FAIL**  (seed 1)

Reasons:
- iverilog: 3642 of 4024 output beats differ from the golden model
- verilator: 3642 of 4024 output beats differ from the golden model

Stimulus: 4024 input beats -> 4024 golden output beats; sources {'directed': 0, 'formal_counterexample': 0, 'corner_sample': 1024, 'random_mix': 3000}; idle cycles 3621; stall cycles 0

| check | status | detail |
|---|---|---|
| lint | pass | errors 0, risk 0, style 0, waived 0 |
| structural | pass | errors 0, risk 0, style 0, waived 0 |
| sim iverilog | fail | beats 4024, mismatched 3642, X 0, missing 0, extra 0, 0.1 s |
| sim verilator | fail | beats 4024, mismatched 3642, X 0, missing 0, extra 0, 8.39 s |

| number | value | kind | source |
|---|---|---|---|
| golden model line coverage | 100.0% | measured | sys.settrace over golden model |
| iverilog: output beats bit-exact | 382 of 4024 | measured | run_iverilog/iverilog_out.txt |
| verilator: output beats bit-exact | 382 of 4024 | measured | run_verilator/verilator_out.txt |

First mismatches (iverilog):
- beat 0 port y: expected -1431657750, got 0xaaaaa0fa (xor 0x210) - value differs: check the datapath against the golden model
- beat 1 port y: expected 536874751, got 0x200012bf (xor 0x1c40) - value differs: check the datapath against the golden model
- beat 2 port y: expected -2147461634, got 0x80006b3e (xor 0x3ec0) - value differs: check the datapath against the golden model
- beat 3 port y: expected -1073758208, got 0xbfffb020 (xor 0x7020) - value differs: check the datapath against the golden model
- beat 5 port y: expected -2147475520, got 0x800027a0 (xor 0x3860) - value differs: check the datapath against the golden model

First mismatches (verilator):
- beat 0 port y: expected -1431657750, got 0xaaaaa0fa (xor 0x210) - value differs: check the datapath against the golden model
- beat 1 port y: expected 536874751, got 0x200012bf (xor 0x1c40) - value differs: check the datapath against the golden model
- beat 2 port y: expected -2147461634, got 0x80006b3e (xor 0x3ec0) - value differs: check the datapath against the golden model
- beat 3 port y: expected -1073758208, got 0xbfffb020 (xor 0x7020) - value differs: check the datapath against the golden model
- beat 5 port y: expected -2147475520, got 0x800027a0 (xor 0x3860) - value differs: check the datapath against the golden model

