# DV report: fx_pwl (fx_pwl)

**Verdict: FAIL**  (seed 1)

Reasons:
- iverilog: 8191 of 65536 output beats differ from the golden model
- verilator: 8191 of 65536 output beats differ from the golden model

Stimulus: 65536 input beats -> 65536 golden output beats; sources {'directed': 0, 'formal_counterexample': 0, 'exhaustive': 65536}; idle cycles 0; stall cycles 0

| check | status | detail |
|---|---|---|
| lint | pass | errors 0, risk 0, style 0, waived 1 |
| structural | pass | errors 0, risk 0, style 0, waived 0 |
| sim iverilog | fail | beats 65536, mismatched 8191, X 0, missing 0, extra 0, 0.49 s |
| sim verilator | fail | beats 65536, mismatched 8191, X 0, missing 0, extra 0, 4.66 s |

| number | value | kind | source |
|---|---|---|---|
| golden model line coverage | 100.0% | measured | sys.settrace over golden model |
| iverilog: output beats bit-exact | 57345 of 65536 | measured | run_iverilog/iverilog_out.txt |
| verilator: output beats bit-exact | 57345 of 65536 | measured | run_verilator/verilator_out.txt |
| DUT line coverage | 100.0% (10/10 points) | measured | verilator coverage.dat |
| DUT toggle coverage | 91.5% (302/330 points) | measured | verilator coverage.dat |

First mismatches (iverilog):
- beat 1 port y: expected -18001, got 0x39af (xor 0x8000) - only the sign bit differs: signedness or sign extension
- beat 2 port y: expected -18001, got 0x39af (xor 0x8000) - only the sign bit differs: signedness or sign extension
- beat 3 port y: expected -18001, got 0x39af (xor 0x8000) - only the sign bit differs: signedness or sign extension
- beat 4 port y: expected -18001, got 0x39af (xor 0x8000) - only the sign bit differs: signedness or sign extension
- beat 5 port y: expected -18001, got 0x39af (xor 0x8000) - only the sign bit differs: signedness or sign extension

First mismatches (verilator):
- beat 1 port y: expected -18001, got 0x39af (xor 0x8000) - only the sign bit differs: signedness or sign extension
- beat 2 port y: expected -18001, got 0x39af (xor 0x8000) - only the sign bit differs: signedness or sign extension
- beat 3 port y: expected -18001, got 0x39af (xor 0x8000) - only the sign bit differs: signedness or sign extension
- beat 4 port y: expected -18001, got 0x39af (xor 0x8000) - only the sign bit differs: signedness or sign extension
- beat 5 port y: expected -18001, got 0x39af (xor 0x8000) - only the sign bit differs: signedness or sign extension

