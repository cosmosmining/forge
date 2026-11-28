# DV report: fx_pwl (fx_pwl)

**Verdict: FAIL**  (seed 1)

Reasons:
- iverilog: 57344 of 65536 output beats differ from the golden model
- verilator: 57344 of 65536 output beats differ from the golden model

Stimulus: 65536 input beats -> 65536 golden output beats; sources {'directed': 0, 'formal_counterexample': 0, 'exhaustive': 65536}; idle cycles 0; stall cycles 0

| check | status | detail |
|---|---|---|
| lint | pass | errors 0, risk 0, style 1, waived 1 |
| structural | pass | errors 0, risk 0, style 0, waived 0 |
| sim iverilog | fail | beats 65536, mismatched 57344, X 0, missing 0, extra 0, 0.62 s |
| sim verilator | fail | beats 65536, mismatched 57344, X 0, missing 0, extra 0, 8.25 s |

| number | value | kind | source |
|---|---|---|---|
| golden model line coverage | 100.0% | measured | sys.settrace over golden model |
| iverilog: output beats bit-exact | 8192 of 65536 | measured | run_iverilog/iverilog_out.txt |
| verilator: output beats bit-exact | 8192 of 65536 | measured | run_verilator/verilator_out.txt |

First mismatches (iverilog):
- beat 0 port y: expected -18000, got 0x0000 (xor 0xb9b0) - output is zero: not updated, cleared too early, or wrong select
- beat 1 port y: expected -18001, got 0x0000 (xor 0xb9af) - output is zero: not updated, cleared too early, or wrong select
- beat 2 port y: expected -18001, got 0x0000 (xor 0xb9af) - output is zero: not updated, cleared too early, or wrong select
- beat 3 port y: expected -18001, got 0x0000 (xor 0xb9af) - output is zero: not updated, cleared too early, or wrong select
- beat 4 port y: expected -18001, got 0x0000 (xor 0xb9af) - output is zero: not updated, cleared too early, or wrong select

First mismatches (verilator):
- beat 0 port y: expected -18000, got 0x0000 (xor 0xb9b0) - output is zero: not updated, cleared too early, or wrong select
- beat 1 port y: expected -18001, got 0x0000 (xor 0xb9af) - output is zero: not updated, cleared too early, or wrong select
- beat 2 port y: expected -18001, got 0x0000 (xor 0xb9af) - output is zero: not updated, cleared too early, or wrong select
- beat 3 port y: expected -18001, got 0x0000 (xor 0xb9af) - output is zero: not updated, cleared too early, or wrong select
- beat 4 port y: expected -18001, got 0x0000 (xor 0xb9af) - output is zero: not updated, cleared too early, or wrong select

