# DV report: fx_pwl (fx_pwl)

**Verdict: FAIL**  (seed 1)

Reasons:
- iverilog: 32768 of 65536 output beats differ from the golden model
- verilator: 32768 of 65536 output beats differ from the golden model

Stimulus: 65536 input beats -> 65536 golden output beats; sources {'directed': 0, 'formal_counterexample': 0, 'exhaustive': 65536}; idle cycles 0; stall cycles 0

| check | status | detail |
|---|---|---|
| lint | pass | errors 0, risk 0, style 0, waived 1 |
| structural | pass | errors 0, risk 0, style 0, waived 0 |
| sim iverilog | fail | beats 65536, mismatched 32768, X 0, missing 0, extra 0, 0.5 s |
| sim verilator | fail | beats 65536, mismatched 32768, X 0, missing 0, extra 0, 8.21 s |

| number | value | kind | source |
|---|---|---|---|
| golden model line coverage | 100.0% | measured | sys.settrace over golden model |
| iverilog: output beats bit-exact | 32768 of 65536 | measured | run_iverilog/iverilog_out.txt |
| verilator: output beats bit-exact | 32768 of 65536 | measured | run_verilator/verilator_out.txt |

First mismatches (iverilog):
- beat 4096 port y: expected -18032, got 0xb9d0 (xor 0x40) - value differs: check the datapath against the golden model
- beat 4097 port y: expected -18033, got 0xb9cf (xor 0x40) - value differs: check the datapath against the golden model
- beat 4098 port y: expected -18033, got 0xb9cf (xor 0x40) - value differs: check the datapath against the golden model
- beat 4099 port y: expected -18033, got 0xb9cf (xor 0x40) - value differs: check the datapath against the golden model
- beat 4100 port y: expected -18033, got 0xb9cf (xor 0x40) - value differs: check the datapath against the golden model

First mismatches (verilator):
- beat 4096 port y: expected -18032, got 0xb9d0 (xor 0x40) - value differs: check the datapath against the golden model
- beat 4097 port y: expected -18033, got 0xb9cf (xor 0x40) - value differs: check the datapath against the golden model
- beat 4098 port y: expected -18033, got 0xb9cf (xor 0x40) - value differs: check the datapath against the golden model
- beat 4099 port y: expected -18033, got 0xb9cf (xor 0x40) - value differs: check the datapath against the golden model
- beat 4100 port y: expected -18033, got 0xb9cf (xor 0x40) - value differs: check the datapath against the golden model

