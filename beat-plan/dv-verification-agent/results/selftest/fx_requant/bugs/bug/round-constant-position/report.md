# DV report: fx_requant (fx_requant)

**Verdict: FAIL**  (seed 1)

Reasons:
- iverilog: 586 of 4024 output beats differ from the golden model
- verilator: 586 of 4024 output beats differ from the golden model

Stimulus: 4024 input beats -> 4024 golden output beats; sources {'directed': 0, 'formal_counterexample': 0, 'corner_sample': 1024, 'random_mix': 3000}; idle cycles 0; stall cycles 0

| check | status | detail |
|---|---|---|
| lint | pass | errors 0, risk 0, style 0, waived 0 |
| structural | pass | errors 0, risk 0, style 0, waived 0 |
| sim iverilog | fail | beats 4024, mismatched 586, X 0, missing 0, extra 0, 0.06 s |
| sim verilator | fail | beats 4024, mismatched 586, X 0, missing 0, extra 0, 8.32 s |

| number | value | kind | source |
|---|---|---|---|
| golden model line coverage | 100.0% | measured | sys.settrace over golden model |
| iverilog: output beats bit-exact | 3438 of 4024 | measured | run_iverilog/iverilog_out.txt |
| verilator: output beats bit-exact | 3438 of 4024 | measured | run_verilator/verilator_out.txt |

First mismatches (iverilog):
- beat 5 port y: expected -16, got 0xf1 (xor 0x1) - off by one: rounding constant, rounding direction or truncation
- beat 7 port y: expected 63, got 0x40 (xor 0x7f) - off by one: rounding constant, rounding direction or truncation
- beat 24 port y: expected -32, got 0xe1 (xor 0x1) - off by one: rounding constant, rounding direction or truncation
- beat 35 port y: expected 32, got 0x21 (xor 0x1) - off by one: rounding constant, rounding direction or truncation
- beat 42 port y: expected -128, got 0x81 (xor 0x1) - off by one: rounding constant, rounding direction or truncation

First mismatches (verilator):
- beat 5 port y: expected -16, got 0xf1 (xor 0x1) - off by one: rounding constant, rounding direction or truncation
- beat 7 port y: expected 63, got 0x40 (xor 0x7f) - off by one: rounding constant, rounding direction or truncation
- beat 24 port y: expected -32, got 0xe1 (xor 0x1) - off by one: rounding constant, rounding direction or truncation
- beat 35 port y: expected 32, got 0x21 (xor 0x1) - off by one: rounding constant, rounding direction or truncation
- beat 42 port y: expected -128, got 0x81 (xor 0x1) - off by one: rounding constant, rounding direction or truncation

