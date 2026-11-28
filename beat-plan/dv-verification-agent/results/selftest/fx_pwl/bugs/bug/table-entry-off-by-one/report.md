# DV report: fx_pwl (fx_pwl)

**Verdict: FAIL**  (seed 1)

Reasons:
- iverilog: 8192 of 65536 output beats differ from the golden model
- verilator: 8192 of 65536 output beats differ from the golden model

Stimulus: 65536 input beats -> 65536 golden output beats; sources {'directed': 0, 'formal_counterexample': 0, 'exhaustive': 65536}; idle cycles 0; stall cycles 0

| check | status | detail |
|---|---|---|
| lint | pass | errors 0, risk 0, style 0, waived 1 |
| structural | pass | errors 0, risk 0, style 0, waived 0 |
| sim iverilog | fail | beats 65536, mismatched 8192, X 0, missing 0, extra 0, 0.53 s |
| sim verilator | fail | beats 65536, mismatched 8192, X 0, missing 0, extra 0, 8.51 s |

| number | value | kind | source |
|---|---|---|---|
| golden model line coverage | 100.0% | measured | sys.settrace over golden model |
| iverilog: output beats bit-exact | 57344 of 65536 | measured | run_iverilog/iverilog_out.txt |
| verilator: output beats bit-exact | 57344 of 65536 | measured | run_verilator/verilator_out.txt |

First mismatches (iverilog):
- beat 8192 port y: expected -18064, got 0xb971 (xor 0x1) - off by one: rounding constant, rounding direction or truncation
- beat 8193 port y: expected -18064, got 0xb971 (xor 0x1) - off by one: rounding constant, rounding direction or truncation
- beat 8194 port y: expected -18064, got 0xb971 (xor 0x1) - off by one: rounding constant, rounding direction or truncation
- beat 8195 port y: expected -18064, got 0xb971 (xor 0x1) - off by one: rounding constant, rounding direction or truncation
- beat 8196 port y: expected -18064, got 0xb971 (xor 0x1) - off by one: rounding constant, rounding direction or truncation

First mismatches (verilator):
- beat 8192 port y: expected -18064, got 0xb971 (xor 0x1) - off by one: rounding constant, rounding direction or truncation
- beat 8193 port y: expected -18064, got 0xb971 (xor 0x1) - off by one: rounding constant, rounding direction or truncation
- beat 8194 port y: expected -18064, got 0xb971 (xor 0x1) - off by one: rounding constant, rounding direction or truncation
- beat 8195 port y: expected -18064, got 0xb971 (xor 0x1) - off by one: rounding constant, rounding direction or truncation
- beat 8196 port y: expected -18064, got 0xb971 (xor 0x1) - off by one: rounding constant, rounding direction or truncation

