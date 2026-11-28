# DV report: fx_requant (fx_requant)

**Verdict: FAIL**  (seed 1)

Reasons:
- iverilog: 494 of 4024 output beats differ from the golden model
- verilator: 494 of 4024 output beats differ from the golden model

Stimulus: 4024 input beats -> 4024 golden output beats; sources {'directed': 0, 'formal_counterexample': 0, 'corner_sample': 1024, 'random_mix': 3000}; idle cycles 0; stall cycles 0

| check | status | detail |
|---|---|---|
| lint | pass | errors 0, risk 0, style 0, waived 0 |
| structural | pass | errors 0, risk 0, style 0, waived 0 |
| sim iverilog | fail | beats 4024, mismatched 494, X 0, missing 0, extra 0, 0.05 s |
| sim verilator | fail | beats 4024, mismatched 494, X 0, missing 0, extra 0, 7.92 s |

| number | value | kind | source |
|---|---|---|---|
| golden model line coverage | 100.0% | measured | sys.settrace over golden model |
| iverilog: output beats bit-exact | 3530 of 4024 | measured | run_iverilog/iverilog_out.txt |
| verilator: output beats bit-exact | 3530 of 4024 | measured | run_verilator/verilator_out.txt |

First mismatches (iverilog):
- beat 4 port y: expected -127, got 0x7f (xor 0xfe) - RTL saturated but golden did not: clamp bound or compare wrong
- beat 5 port y: expected -16, got 0x7f (xor 0x8f) - RTL saturated but golden did not: clamp bound or compare wrong
- beat 24 port y: expected -32, got 0x7f (xor 0x9f) - RTL saturated but golden did not: clamp bound or compare wrong
- beat 38 port y: expected -30, got 0x7f (xor 0x9d) - RTL saturated but golden did not: clamp bound or compare wrong
- beat 42 port y: expected -128, got 0x7f (xor 0xff) - golden value is saturated: check clamp bounds and overflow detection

First mismatches (verilator):
- beat 4 port y: expected -127, got 0x7f (xor 0xfe) - RTL saturated but golden did not: clamp bound or compare wrong
- beat 5 port y: expected -16, got 0x7f (xor 0x8f) - RTL saturated but golden did not: clamp bound or compare wrong
- beat 24 port y: expected -32, got 0x7f (xor 0x9f) - RTL saturated but golden did not: clamp bound or compare wrong
- beat 38 port y: expected -30, got 0x7f (xor 0x9d) - RTL saturated but golden did not: clamp bound or compare wrong
- beat 42 port y: expected -128, got 0x7f (xor 0xff) - golden value is saturated: check clamp bounds and overflow detection

