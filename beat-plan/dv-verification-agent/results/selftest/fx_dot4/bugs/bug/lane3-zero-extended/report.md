# DV report: fx_dot4 (fx_dot4)

**Verdict: FAIL**  (seed 1)

Reasons:
- iverilog: 1784 of 4024 output beats differ from the golden model
- verilator: 1784 of 4024 output beats differ from the golden model

Stimulus: 4024 input beats -> 4024 golden output beats; sources {'directed': 0, 'formal_counterexample': 0, 'corner_sample': 1024, 'random_mix': 3000}; idle cycles 3621; stall cycles 0

| check | status | detail |
|---|---|---|
| lint | pass | errors 0, risk 0, style 0, waived 0 |
| structural | pass | errors 0, risk 0, style 0, waived 0 |
| sim iverilog | fail | beats 4024, mismatched 1784, X 0, missing 0, extra 0, 0.13 s |
| sim verilator | fail | beats 4024, mismatched 1784, X 0, missing 0, extra 0, 8.22 s |

| number | value | kind | source |
|---|---|---|---|
| golden model line coverage | 100.0% | measured | sys.settrace over golden model |
| iverilog: output beats bit-exact | 2240 of 4024 | measured | run_iverilog/iverilog_out.txt |
| verilator: output beats bit-exact | 2240 of 4024 | measured | run_verilator/verilator_out.txt |

First mismatches (iverilog):
- beat 0 port y: expected -1431657750, got 0xaaaab2ea (xor 0x1000) - value differs: check the datapath against the golden model
- beat 2 port y: expected -2147461634, got 0x7ffffffe (xor 0xffffaa00) - value differs: check the datapath against the golden model
- beat 5 port y: expected -2147475520, got 0x7fffa0c0 (xor 0xffffbf00) - value differs: check the datapath against the golden model
- beat 9 port y: expected -2147483392, got 0x7fffff00 (xor 0xfffffe00) - sign flipped: negation or subtract/add swapped
- beat 10 port y: expected -536870399, got 0xdfff8201 (xor 0x3fff8000) - value differs: check the datapath against the golden model

First mismatches (verilator):
- beat 0 port y: expected -1431657750, got 0xaaaab2ea (xor 0x1000) - value differs: check the datapath against the golden model
- beat 2 port y: expected -2147461634, got 0x7ffffffe (xor 0xffffaa00) - value differs: check the datapath against the golden model
- beat 5 port y: expected -2147475520, got 0x7fffa0c0 (xor 0xffffbf00) - value differs: check the datapath against the golden model
- beat 9 port y: expected -2147483392, got 0x7fffff00 (xor 0xfffffe00) - sign flipped: negation or subtract/add swapped
- beat 10 port y: expected -536870399, got 0xdfff8201 (xor 0x3fff8000) - value differs: check the datapath against the golden model

