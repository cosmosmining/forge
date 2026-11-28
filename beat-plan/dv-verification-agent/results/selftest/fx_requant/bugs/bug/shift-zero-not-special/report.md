# DV report: fx_requant (fx_requant)

**Verdict: FAIL**  (seed 1)

Reasons:
- iverilog: 119 of 4024 output beats differ from the golden model
- verilator: 119 of 4024 output beats differ from the golden model

Stimulus: 4024 input beats -> 4024 golden output beats; sources {'directed': 0, 'formal_counterexample': 0, 'corner_sample': 1024, 'random_mix': 3000}; idle cycles 0; stall cycles 0

| check | status | detail |
|---|---|---|
| lint | pass | errors 0, risk 0, style 0, waived 0 |
| structural | pass | errors 0, risk 0, style 0, waived 0 |
| sim iverilog | fail | beats 4024, mismatched 119, X 0, missing 0, extra 0, 0.06 s |
| sim verilator | fail | beats 4024, mismatched 119, X 0, missing 0, extra 0, 8.32 s |

| number | value | kind | source |
|---|---|---|---|
| golden model line coverage | 100.0% | measured | sys.settrace over golden model |
| iverilog: output beats bit-exact | 3905 of 4024 | measured | run_iverilog/iverilog_out.txt |
| verilator: output beats bit-exact | 3905 of 4024 | measured | run_verilator/verilator_out.txt |

First mismatches (iverilog):
- beat 13 port y: expected -128, got 0x7f (xor 0xff) - golden value is saturated: check clamp bounds and overflow detection
- beat 107 port y: expected -128, got 0x7f (xor 0xff) - golden value is saturated: check clamp bounds and overflow detection
- beat 143 port y: expected 1, got 0x7f (xor 0x7e) - RTL saturated but golden did not: clamp bound or compare wrong
- beat 240 port y: expected -128, got 0x81 (xor 0x1) - off by one: rounding constant, rounding direction or truncation
- beat 251 port y: expected -128, got 0x7f (xor 0xff) - golden value is saturated: check clamp bounds and overflow detection

First mismatches (verilator):
- beat 13 port y: expected -128, got 0x7f (xor 0xff) - golden value is saturated: check clamp bounds and overflow detection
- beat 107 port y: expected -128, got 0x7f (xor 0xff) - golden value is saturated: check clamp bounds and overflow detection
- beat 143 port y: expected 1, got 0x7f (xor 0x7e) - RTL saturated but golden did not: clamp bound or compare wrong
- beat 240 port y: expected -128, got 0x81 (xor 0x1) - off by one: rounding constant, rounding direction or truncation
- beat 251 port y: expected -128, got 0x7f (xor 0xff) - golden value is saturated: check clamp bounds and overflow detection

