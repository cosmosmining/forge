# DV report: fx_requant (fx_requant)

**Verdict: FAIL**  (seed 1)

Reasons:
- iverilog: 5 of 4024 output beats differ from the golden model
- verilator: 5 of 4024 output beats differ from the golden model

Stimulus: 4024 input beats -> 4024 golden output beats; sources {'directed': 0, 'formal_counterexample': 0, 'corner_sample': 1024, 'random_mix': 3000}; idle cycles 0; stall cycles 0

| check | status | detail |
|---|---|---|
| lint | pass | errors 0, risk 0, style 0, waived 0 |
| structural | pass | errors 0, risk 0, style 0, waived 0 |
| sim iverilog | fail | beats 4024, mismatched 5, X 0, missing 0, extra 0, 0.07 s |
| sim verilator | fail | beats 4024, mismatched 5, X 0, missing 0, extra 0, 8.36 s |

| number | value | kind | source |
|---|---|---|---|
| golden model line coverage | 100.0% | measured | sys.settrace over golden model |
| iverilog: output beats bit-exact | 4019 of 4024 | measured | run_iverilog/iverilog_out.txt |
| verilator: output beats bit-exact | 4019 of 4024 | measured | run_verilator/verilator_out.txt |

First mismatches (iverilog):
- beat 561 port y: expected 127, got 0x80 (xor 0xff) - golden value is saturated: check clamp bounds and overflow detection
- beat 890 port y: expected 127, got 0x80 (xor 0xff) - golden value is saturated: check clamp bounds and overflow detection
- beat 1010 port y: expected 127, got 0x80 (xor 0xff) - golden value is saturated: check clamp bounds and overflow detection
- beat 1748 port y: expected 127, got 0x80 (xor 0xff) - golden value is saturated: check clamp bounds and overflow detection
- beat 2982 port y: expected 127, got 0x80 (xor 0xff) - golden value is saturated: check clamp bounds and overflow detection

First mismatches (verilator):
- beat 561 port y: expected 127, got 0x80 (xor 0xff) - golden value is saturated: check clamp bounds and overflow detection
- beat 890 port y: expected 127, got 0x80 (xor 0xff) - golden value is saturated: check clamp bounds and overflow detection
- beat 1010 port y: expected 127, got 0x80 (xor 0xff) - golden value is saturated: check clamp bounds and overflow detection
- beat 1748 port y: expected 127, got 0x80 (xor 0xff) - golden value is saturated: check clamp bounds and overflow detection
- beat 2982 port y: expected 127, got 0x80 (xor 0xff) - golden value is saturated: check clamp bounds and overflow detection

